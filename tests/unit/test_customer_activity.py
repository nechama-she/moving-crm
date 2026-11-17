"""Work queue customer activity: each event on customer pages saved as its own row, newest first, and kept after a
signature is removed."""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


def move(db):
    from models import Company, Lead, LeadJob
    db.add(Company(id='gorilla', name='Gorilla Haulers'))
    db.add(Lead(id='lead', full_name='Jane Doe', number='48213075526'))
    db.flush()
    db.add(LeadJob(id='job', lead_id='lead', job_order=1, company_id='gorilla'))
    db.flush()


def test_past_signatures_are_copied_in_once():
    """The table starts with every signature saved so far; an unsigned copy is not one."""
    from models import Base, BillOfLadingSignature, CustomerActivity, EstimateSignature
    from customer_activity_log import create_activity_table
    engine = create_engine('sqlite://')
    tables = [table for table in Base.metadata.sorted_tables if table.name not in {'customer_activity', 'customer_activity_kinds'}]
    Base.metadata.create_all(engine, tables=tables)
    now = datetime.utcnow()
    with Session(engine) as db:
        move(db)
        db.add_all([
            EstimateSignature(id='signed', lead_id='lead', job_id='job', snapshot='{}', pdf=b'', signer_name='Jane', signed_at=now - timedelta(hours=2)),
            EstimateSignature(id='unsigned', lead_id='lead', job_id='job', snapshot='{}', pdf=b'')])
        db.flush()
        db.add(BillOfLadingSignature(id='bol', lead_id='lead', job_id='job', estimate_signature_id='signed', content_hash='x', spot=1,
                                     pdf=b'', signer_name='Jane D', signature='{}', signed_at=now - timedelta(hours=1)))
        db.commit()
    with engine.begin() as connection:
        assert create_activity_table(connection) == 2
    with engine.begin() as connection:
        assert create_activity_table(connection) == 0
    with Session(engine) as db:
        rows = sorted((row.kind_id, row.spot, row.actor) for row in db.query(CustomerActivity))
    assert rows == [(1, None, 'Jane'), (2, 2, 'Jane D')]
    engine.dispose()


def test_events_newest_first_and_a_removed_signature_stays_listed():
    from models import Base, CustomerActivity, CustomerActivityKind
    from customer_activity_log import KINDS, record
    from routes.customer_activity import list_customer_activity
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([CustomerActivityKind(id=kind_id, label=label) for kind_id, label in KINDS.items()])
        db.commit()
    now = datetime.utcnow()
    with Session(engine) as db:
        move(db)
        for kind, hours, actor, by_rep, spot in [(1, 4, 'Jane', False, None), (2, 3, 'Jane', False, 1), (4, 2, 'Eli Jones', True, None),
                                                 (3, 1, 'Eli Jones', True, None)]:
            activity_id = record(db, 'lead', 'job', kind, actor, by_rep, spot)
            db.flush()
            db.get(CustomerActivity, activity_id).created_at = now - timedelta(hours=hours)
        old = record(db, 'lead', 'job', 1, 'Jane')
        db.flush()
        db.get(CustomerActivity, old).created_at = now - timedelta(days=40)
        db.commit()
        items = list_customer_activity(30, SimpleNamespace(role='admin'), db)['items']
    assert [(row['label'], row['spot'], row['actor'], row['by_rep']) for row in items] == [
        ('Removed the estimate signature', None, 'Eli Jones', True), ('Changed the estimate: needs signing again', None, 'Eli Jones', True),
        ('Signed the Bill of Lading', 1, 'Jane', False), ('Signed the estimate', None, 'Jane', False)]
    assert (items[0]['client'], items[0]['company'], items[0]['job_number']) == ('Jane Doe', 'Gorilla Haulers', '48213075526-1')
    engine.dispose()
