"""The inventory migration keeps every estimate that shows as signed showing as signed, through the real customer page
code, without touching the signed estimate: the same move written the tables' way is noted beside it."""
import json
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')

# As LiveSwitch reports saved their rows: the tables write each of these differently.
SAVED_ROWS = [dict(name='Book', room='', going=True, unit_cuft=3.333, cuft=10.0, weight=100.0, amount=3.0),
              dict(name='Lamp (CP)', room='Bedroom', going=True, unit_cuft=3.33, cuft=3.33, weight=10.0, amount=1.0),
              dict(name='Desk', room='Office', going=True, unit_cuft=30.0, cuft=30.0, weight=100.0, amount=1.0),
              dict(name='Rug', room='Office', going=False, unit_cuft=5.0, cuft=0.0, weight=0, amount=0.0)]


@pytest.fixture
def move():
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session
    from models import Base, Lead, LeadJob, LeadLiveSwitch, PublicMoveAccess
    import estimate_approval
    hook = estimate_approval._clear_changed_approvals
    hooked = event.contains(Session, 'before_flush', hook)
    if hooked:
        event.remove(Session, 'before_flush', hook)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Lead(id='L1', full_name='Pat Customer', phone='2405550100', volume=Decimal('43.33'), weight=Decimal('210')))
        db.add(LeadJob(id='J1', lead_id='L1', job_order=1, pickup_zip='1 Main St, Rockville, MD 20850', delivery_zip='2 Elm St, Austin, TX 78701',
                       move_date='2026-12-01', customer_packing_package='{}'))
        db.add(PublicMoveAccess(id='A1', lead_id='L1', job_id='J1', key_hash='k' * 64, request_hash='r' * 64, token_hash='t' * 64,
                                expires_at=datetime.utcnow() + timedelta(days=1)))
        db.add(LeadLiveSwitch(lead_id='L1', details=json.dumps({
            'last_spark_id': 'r1', 'last_spark_status': 'completed', 'spark_extracted_id': 'r1', 'report_source': 'liveswitch',
            'question_original_rows': SAVED_ROWS, 'spark_inventory_snapshot': SAVED_ROWS})))
        db.commit()
        yield db
    engine.dispose()
    if hooked:
        event.listen(Session, 'before_flush', hook)


def estimate_now(db):
    from routes.public_moves import _move_details
    from models import PublicMoveAccess
    db.info.pop('request_cache', None)
    return _move_details(db.get(PublicMoveAccess, 'A1'), db, pricing_only=True, estimate_only=True)


def sign(db, data, rows):
    """A signature as the page saved it before the move: its data, and the list as the page read it then."""
    from fastapi.encoders import jsonable_encoder
    from catalog_names import resolve_catalog_names
    from models import EstimateSignature
    db.add(EstimateSignature(id='S1', lead_id='L1', job_id='J1', report_id='r1', pdf=b'signed-pdf', signer_name='Pat',
                             signature='{"name": "Pat"}', signed_at=datetime(2026, 11, 1),
                             snapshot=json.dumps(jsonable_encoder({'data': data, 'rows': resolve_catalog_names(rows, db)}))))
    db.commit()


def page_status(db):
    from estimate_signature_history import estimate_signature_status
    return estimate_signature_status(db, 'L1', 'J1', lambda: estimate_now(db), None)


def signed_data(db):
    """The move's estimate data (people, addresses, dates, charges), as it was when signed: worked out here in a
    savepoint, then undone, so the move is still saved the old way."""
    from inventory_migration import migrate_move
    from models import LeadLiveSwitch
    savepoint = db.begin_nested()
    migrate_move(db.get(LeadLiveSwitch, 'L1'), db)
    data, _ = estimate_now(db)
    savepoint.rollback()
    db.expire_all()
    db.info.pop('request_cache', None)
    return data


def signed_record(db):
    from models import EstimateSignature
    record = db.get(EstimateSignature, 'S1')
    return (record.snapshot, record.pdf, record.signer_name, record.signature, record.signed_at)


def test_signed_stays_signed_untouched(move):
    """Signed before, signed after; the signed estimate itself is exactly as it was. A real change after the move
    (here the pickup address) shows as changed."""
    from inventory_migration import migrate_move
    from models import EstimateSignature, LeadJob, LeadLiveSwitch
    db = move
    sign(db, signed_data(db), SAVED_ROWS)
    before = signed_record(db)
    assert migrate_move(db.get(LeadLiveSwitch, 'L1'), db) is True
    db.commit()
    assert page_status(db) == 'signed'
    assert signed_record(db) == before
    assert db.get(EstimateSignature, 'S1').migrated_state
    db.get(LeadJob, 'J1').pickup_zip = '9 Other Rd, Rockville, MD 20850'
    db.commit()
    assert page_status(db) == 'changed'


def test_without_keeping_it_would_show_changed(move, monkeypatch):
    """The tables do write this list differently: without keep_signed the same move would show as changed."""
    import inventory_migration
    from models import LeadLiveSwitch
    db = move
    sign(db, signed_data(db), SAVED_ROWS)
    monkeypatch.setattr(inventory_migration, 'keep_signed', lambda *args: None)
    inventory_migration.migrate_move(db.get(LeadLiveSwitch, 'L1'), db)
    db.commit()
    assert page_status(db) == 'changed'


@pytest.mark.parametrize('change', ['list', 'address'])
def test_already_changed_stays_changed(move, change):
    """Changed since signing (the list, or the address): it showed as changed before the move and still does."""
    from inventory_migration import migrate_move
    from models import EstimateSignature, LeadLiveSwitch
    db = move
    data = signed_data(db)
    if change == 'address':
        data = dict(data, pickup='9 Other Rd, Rockville, MD 20850')
    sign(db, data, SAVED_ROWS[:2] if change == 'list' else SAVED_ROWS)
    before = signed_record(db)
    migrate_move(db.get(LeadLiveSwitch, 'L1'), db)
    db.commit()
    assert page_status(db) == 'changed'
    assert signed_record(db) == before
    assert db.get(EstimateSignature, 'S1').migrated_state is None


def test_a_failure_leaves_every_move_as_it_was(move, monkeypatch):
    """One commit for every move: if anything fails, nothing is saved and every move stays saved the old way."""
    import inventory_migration
    from sqlalchemy.orm import sessionmaker
    from models import InventoryEditItem, LeadLiveSwitch
    db = move
    sign(db, signed_data(db), SAVED_ROWS)
    def fail(*args):
        raise RuntimeError('stop')
    monkeypatch.setattr(inventory_migration, 'keep_signed', fail)
    with pytest.raises(RuntimeError):
        inventory_migration.migrate_inventories(sessionmaker(bind=db.get_bind()))
    db.expire_all()
    assert 'question_original_rows' in json.loads(db.get(LeadLiveSwitch, 'L1').details)
    assert db.query(InventoryEditItem).count() == 0


PACKAGE = {'minimum_cubic_feet': 286, 'rates': {'full': {'rate': 2.5}}, 'selection': {'mode': 'none', 'box_quantities': {'b1': 2}},
           'box_items': [{'id': 'b1', 'room': '', 'label': 'Small Box', 'quantity': 3}], 'other_inventory': [{'room': '', 'name': 'Lamp (CP)'}]}
QUESTION = {'id': 'q1', 'rule_id': 'plants', 'question': 'Is this live?', 'answers': [], 'saved': None,
            'name': 'Lamp (CP)', 'label': 'Lamp (CP)', 'room': '', 'item_index': 1, 'photo': True}


@pytest.mark.parametrize('sheet_changed', [False, True])
def test_only_list_fields_may_differ(move, monkeypatch, sheet_changed):
    """The packing options, bulky items and item questions may differ from the signed estimate only in their fields from
    the list. The price sheet's minimum (on the Bill of Lading) and rates, and the questions and answers, must match as
    signed: a minimum changed since signing showed as changed, and still does. The signed estimate is not touched."""
    import routes.public_moves as page
    from inventory_migration import keep_signed
    from models import EstimateSignature, LeadJob
    db = move
    signed = {'name': 'Pat Customer', 'packing_package': PACKAGE, 'item_questions': [QUESTION],
              'packing_items': [{'id': 'piano:1', 'name': 'Piano (CP)', 'label': 'Piano (CP)', 'price': 300, 'selected': False}]}
    sign(db, signed, SAVED_ROWS)
    # The same move, built from the tables: the list's fields written their way.
    current = dict(signed,
                   packing_package=dict(PACKAGE, minimum_cubic_feet=300 if sheet_changed else 286,
                                        selection={'mode': 'none', 'box_quantities': {'b9': 2}},
                                        box_items=[{'id': 'b9', 'room': 'Other items', 'label': 'Small Box', 'quantity': 3}],
                                        other_inventory=[{'room': 'Bedroom', 'name': 'Lamp'}]),
                   item_questions=[dict(QUESTION, name='Lamp', label='Lamp', room='Bedroom')],
                   packing_items=[{'id': 'piano:1', 'name': 'Piano', 'label': 'Piano', 'price': 300, 'selected': False}])
    monkeypatch.setattr(page, '_move_details', lambda *args, **kwargs: (current, []))
    before = signed_record(db)
    keep_signed(db.get(EstimateSignature, 'S1'), db.get(LeadJob, 'J1'), db)
    db.commit()
    assert signed_record(db) == before
    from estimate_signature_history import estimate_signature_status
    assert estimate_signature_status(db, 'L1', 'J1', current, []) == ('changed' if sheet_changed else 'signed')


def test_a_change_after_signing_is_logged_once(move, monkeypatch):
    """Customer Activity: when the page's own comparison first finds its signed estimate changed, that is logged once per
    signing, by whoever's page it is, and the CRM is told. While it still matches, nothing is logged."""
    import realtime
    from inventory_migration import migrate_move
    from models import CustomerActivity, CustomerActivityKind, Lead, LeadJob, LeadLiveSwitch, PublicMoveAccess, User
    from customer_activity_log import KINDS
    from routes.public_moves import _move_details
    db = move
    db.add_all([CustomerActivityKind(id=kind_id, label=label) for kind_id, label in KINDS.items()])
    db.add(User(id='rep', name='Eli Jones', email='eli@example.com', password_hash='x', role='sales_rep'))
    db.get(Lead, 'L1').assigned_to = 'rep'
    migrate_move(db.get(LeadLiveSwitch, 'L1'), db)
    db.commit()
    data, rows = estimate_now(db)
    sign(db, data, rows)
    sent = []
    monkeypatch.setattr(realtime, 'publish_realtime_event', sent.append)
    def page_load(rep):
        db.info.pop('request_cache', None)
        result = _move_details(db.get(PublicMoveAccess, 'A1'), db, pricing_only=True, individual_charges=rep)
        # A change keeps the estimate signed: the page says signed, with the note that changes were made.
        assert result['signature_status'] == 'signed'
        return 'changed' if result['signature_changed'] else 'signed'
    assert page_load(False) == 'signed'
    assert db.query(CustomerActivity).count() == 0
    db.get(LeadJob, 'J1').pickup_zip = '9 Other Rd, Rockville, MD 20850'
    db.commit()
    assert page_load(True) == 'changed'
    assert page_load(False) == 'changed'
    db.expire_all()
    [row] = db.query(CustomerActivity).all()
    assert (row.kind_id, row.actor, row.by_rep) == (4, 'Eli Jones', True)
    assert [event['activity']['label'] for event in sent] == ['Changed the estimate: needs signing again']
