import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import Base, Company, Lead, LeadJob, LeadLiveSwitch, InventoryEditItem
from inventory_questions import QuestionRule, matches, questions, apply_answers, carried_answers, revision, rule_revision
from inventory_edits import fill_inventory, list_rows, shipping_rows, apply_inventory


def rule():
    return dict(id='plants', title='Plants', question='Is this live?', enabled=True, item_ids=[], words=['plant'], photo=True,
        answers=[dict(id='yes', label='Yes', action='exclude', notice='We cannot transport live plants.', acknowledge=True),
                 dict(id='no', label='No', action='none', notice='', acknowledge=False)])


@pytest.fixture
def move():
    """A move whose inventory table holds the given rows. Saving rows runs the estimate-approval hook, which is not what
    these tests check (and which imports modules other tests replace), so it is off while each test runs."""
    import estimate_approval
    hook = estimate_approval._clear_changed_approvals
    hooked = event.contains(Session, 'before_flush', hook)
    if hooked:
        event.remove(Session, 'before_flush', hook)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Lead(id='L1', full_name='Customer'))
        db.flush()
        job = LeadJob(id='J1', lead_id='L1', job_order=1)
        db.add(job)
        db.flush()
        def fill(rows):
            fill_inventory(job, [dict(row, inventory_row_id=row.get('inventory_row_id') or f'row-{index}', room=row.get('room', 'Living Room'),
                                      unit_cuft=row['cuft'] / row['amount'], unit_weight=row.get('weight', 0) / row['amount'])
                                 for index, row in enumerate(rows)], [], None, None, db)
            return list_rows(job.id, db)[0]
        yield db, job, fill
    if hooked:
        event.listen(Session, 'before_flush', hook)


def shipped(db, job):
    rows = shipping_rows(job.id, db)
    return sum(row['cuft'] for row in rows), sum(row['weight'] for row in rows)


@pytest.mark.parametrize('raw, expected', [(721.1, 722), (764.5, 765), (721.01, 722), (721, 721), (0, 0)])
def test_shipment_volume_rounds_up_without_compounding(move, raw, expected):
    db, job, fill = move
    if raw:
        fill([{'name': 'Item', 'amount': 1, 'cuft': raw, 'weight': 0}])
    details = {}
    assert apply_inventory(job, details, db)[0] == expected
    assert apply_inventory(job, details, db)[0] == expected


def test_report_total_the_items_do_not_show_is_kept_in_the_volume(move):
    db, job, fill = move
    fill([{'name': 'Item', 'amount': 1, 'cuft': 10, 'weight': 5}])
    assert apply_inventory(job, {'report_volume_offset': 0.4, 'report_weight_offset': 1}, db) == (11, Decimal(6))


def test_matching_is_explicit_and_whole_word():
    r = rule()
    assert matches(r, {'name': 'Large potted plant'}, {})
    assert not matches(r, {'name': 'Plantation table'}, {})
    r['item_ids'] = ['catalog-1']
    assert matches(r, {'item_id': 'catalog-1', 'name': 'Changed name'}, {})
    assert matches(r, {'name': 'Artificial Tree'}, {'catalog-1': 'Artificial Tree'})
    assert not matches(r, {'name': 'Tree'}, {'catalog-1': 'Artificial Tree'})


def test_actions_require_explanation_and_matching():
    assert QuestionRule(**rule())
    r = rule(); r['answers'][0]['notice'] = ' '
    with pytest.raises(ValueError): QuestionRule(**r)
    r = rule(); r['words'] = []
    with pytest.raises(ValueError): QuestionRule(**r)


def test_exclusion_is_recorded_on_the_row_idempotent_and_reversible(move):
    db, job, fill = move
    company = SimpleNamespace(customer_questions=json.dumps([rule()]))
    rows = fill([dict(name='Plant', amount=2, cuft=12, weight=4), dict(name='Chair', amount=1, cuft=20, weight=10)])
    state = {}
    question = questions(company, state, db, rows)[0]
    state['report_question_answers'] = {question['id']: {'answer_id': 'yes', 'acknowledged': True}}
    assert apply_answers(company, state, job.id, db) is True
    for _ in range(3):
        assert apply_answers(company, state, job.id, db) is False
        assert shipped(db, job) == (26, 12)
        assert db.get(InventoryEditItem, 'row-0').quantity == 2 and db.get(InventoryEditItem, 'row-0').excluded_quantity == 1
    state['report_question_answers'][question['id']]['answer_id'] = 'no'
    assert apply_answers(company, state, job.id, db) is True
    assert shipped(db, job) == (32, 14)


def test_rule_changes_invalidate_old_answers(move):
    db, job, fill = move
    r = rule(); company = SimpleNamespace(customer_questions=json.dumps([r]))
    rows = fill([dict(name='Plant', amount=1, cuft=12)])
    state = {}
    q = questions(company, state, db, rows)[0]
    state['report_question_answers'] = {q['id']: {'answer_id': 'yes', 'acknowledged': True}}
    apply_answers(company, state, job.id, db)
    assert shipped(db, job)[0] == 0
    r['question'] = 'Is this plant alive?'; company.customer_questions = json.dumps([r])
    assert questions(company, state, db, rows)[0]['saved'] is None
    apply_answers(company, state, job.id, db)
    assert shipped(db, job)[0] == 12


def test_company_without_rules_has_no_questions(move):
    db, job, fill = move
    assert questions(SimpleNamespace(customer_questions=None), {}, db, fill([dict(name='Plant', amount=1, cuft=5)])) == []


def test_all_items_question_is_asked_once_and_targets_selected_units(move):
    db, job, fill = move
    r = rule()
    r.update(all_items=True, words=[], item_ids=[])
    QuestionRule.model_validate(r)
    company = SimpleNamespace(customer_questions=json.dumps([r]))
    rows = fill([dict(name='Mower', room='Garage', amount=2, cuft=20, weight=100),
                 dict(name='Chair', room='Bedroom', amount=1, cuft=5, weight=20)])
    state = {}
    question, = questions(company, state, db, rows)
    assert question['all_items'] and [item['id'] for item in question['items']] == ['0:0', '0:1', '1:0']
    state['report_question_answers'] = {question['id']: {'answer_id': 'yes', 'acknowledged': True, 'selected_items': ['0:1']}}
    apply_answers(company, state, job.id, db)
    assert shipped(db, job) == (15, 70)
    state['report_question_answers'][question['id']]['pending'] = True
    apply_answers(company, state, job.id, db)
    assert shipped(db, job) == (25, 120)


def test_default_all_items_flag_preserves_existing_question_ids(move):
    db, job, fill = move
    r = rule()
    company = SimpleNamespace(customer_questions=json.dumps([r]))
    rows = fill([dict(name='Plant', amount=1, cuft=5)])
    original = questions(company, {}, db, rows)[0]['id']
    r['all_items'] = False
    company.customer_questions = json.dumps([r])
    assert questions(company, {}, db, rows)[0]['id'] == original


def test_pending_acknowledgment_does_not_exclude_and_can_restore_item(move):
    db, job, fill = move
    company = SimpleNamespace(customer_questions=json.dumps([rule()]))
    rows = fill([dict(name='Plant', amount=1, cuft=12, weight=4)])
    key = questions(company, {}, db, rows)[0]['id']
    state = {'report_question_answers': {key: {'answer_id': 'yes', 'acknowledged': False, 'pending': True}}}
    apply_answers(company, state, job.id, db)
    assert shipped(db, job) == (12, 4)
    state['report_question_answers'][key].update(acknowledged=True, pending=False)
    apply_answers(company, state, job.id, db)
    assert shipped(db, job) == (0, 0)
    state['report_question_answers'][key].update(acknowledged=False, pending=True)
    apply_answers(company, state, job.id, db)
    assert shipped(db, job) == (12, 4)


def test_each_unit_has_independent_acknowledgment_and_legacy_answers(move):
    db, job, fill = move
    company = SimpleNamespace(customer_questions=json.dumps([rule()]))
    rows = fill([dict(name='Plant', amount=2, cuft=12, weight=4)])
    first, second = questions(company, {}, db, rows)
    assert (first['label'], second['label']) == ('Plant (1 of 2)', 'Plant (2 of 2)')
    assert first['id'] != second['id']
    state = {'report_question_answers': {first['id']: {'answer_id': 'yes', 'acknowledged': False, 'pending': True}}}
    apply_answers(company, state, job.id, db)
    assert shipped(db, job)[0] == 12
    state['report_question_answers'][first['id']].update(acknowledged=True, pending=False)
    apply_answers(company, state, job.id, db)
    assert shipped(db, job)[0] == 6
    assert questions(company, state, db, rows)[1]['saved'] is None
    state = {'report_question_answers': {first['id'].rsplit(':', 1)[0]: {'answer_id': 'yes', 'acknowledged': True}}}
    apply_answers(company, state, job.id, db)
    assert shipped(db, job)[0] == 0


def test_rerun_preserves_answers_for_reordered_unchanged_items(move):
    db, job, fill = move
    company = SimpleNamespace(customer_questions=json.dumps([rule()]))
    old_rows = fill([dict(name='Plant', amount=1, cuft=12), dict(name='Chair', amount=1, cuft=20)])
    answers = {questions(company, {}, db, old_rows)[0]['id']: {'answer_id': 'yes', 'acknowledged': True}}
    # The new report has the same plant (a new row, in another position) and the chair.
    new_rows = fill([dict(name='Chair', amount=1, cuft=20, inventory_row_id='chair-2'), dict(name='Plant', amount=1, cuft=12, inventory_row_id='plant-2')])
    state = {'report_question_answers': carried_answers(company, answers, old_rows, new_rows, db)}
    assert questions(company, state, db, new_rows)[0]['saved']['acknowledged'] is True
    apply_answers(company, state, job.id, db)
    assert shipped(db, job)[0] == 20
    # A changed plant (now two) is a different item: no answer carries over.
    changed = fill([dict(name='Plant', amount=2, cuft=24, inventory_row_id='plant-3')])
    carried = carried_answers(company, answers, old_rows, changed, db)
    assert all(q['saved'] is None for q in questions(company, {'report_question_answers': carried}, db, changed))


def test_migration_keeps_question_ids_answers_exclusions_and_volume(move):
    """A move saved as report JSON moves into the table: its questions keep their ids (so answers and signed estimates
    stay valid), the units its answers took off stay off, the volume stays, and no JSON copy is left."""
    from inventory_migration import migrate_move
    db, job, fill = move
    db.add(Company(id='C1', name='Movers', customer_questions=json.dumps([rule()])))
    lead = db.get(Lead, 'L1')
    lead.company_id, lead.volume, lead.weight = 'C1', Decimal('27'), Decimal('12')
    original = [dict(name='Plant', room='Living Room', amount=2, cuft=12, weight=4, going=True, manual=False),
                dict(name='Chair', room='Bedroom', amount=1, cuft=20, weight=10, going=True, manual=False)]
    old_id = hashlib.sha256((rule_revision(rule()) + ':0:' + revision(original[0])).encode()).hexdigest()
    details = {'last_spark_id': 'r1', 'last_spark_status': 'completed', 'report_source': 'liveswitch',
               'question_original_rows': original, 'spark_inventory_snapshot': [dict(original[0], amount=1, cuft=6), original[1]],
               'report_question_answers': {f'{old_id}:0': {'answer_id': 'yes', 'acknowledged': True}}, 'question_original_cuft': 32.4}
    saved = LeadLiveSwitch(lead_id='L1', details=json.dumps(details))
    db.add(saved)
    db.flush()
    assert migrate_move(saved, db) is True
    migrated = json.loads(saved.details)
    assert not {'spark_inventory_snapshot', 'question_original_rows', 'question_original_cuft'} & set(migrated)
    company = db.get(Company, 'C1')
    rows = list_rows(job.id, db)[0]
    assert [q['id'] for q in questions(company, migrated, db, rows)] == [f'{old_id}:0', f'{old_id}:1']
    assert questions(company, migrated, db, rows)[0]['saved']['acknowledged'] is True
    assert shipped(db, job)[0] == 26
    assert apply_inventory(job, migrated, db)[0] == 27


@pytest.mark.parametrize('source, ends', [('manual', True), ('liveswitch', False)])
def test_deleting_a_list_reports_whole_list_ends_the_report(move, source, ends):
    """A list report is only its list: deleting all of it leaves the move with no report. A report with photos or
    videos stays current."""
    from datetime import datetime, timedelta
    from uuid import uuid4
    from models import PublicMoveAccess
    from inventory_edits import InventoryEdits, load_inventory_editor, save_inventory_edits
    db, job, _ = move
    access = PublicMoveAccess(id='A1', lead_id='L1', job_id=job.id, token_hash='t', key_hash='k', request_hash='r',
                              expires_at=datetime.utcnow() + timedelta(days=1))
    details = {'last_spark_id': 'report-1', 'last_spark_status': 'completed', 'spark_extracted_id': 'report-1',
               'report_source': source, 'spark_history': []}
    db.add_all([access, LeadLiveSwitch(lead_id='L1', details=json.dumps(details))])
    db.flush()
    fill_inventory(job, [dict(name='Sofa', room='Living Room', inventory_row_id=str(uuid4()), amount=1, cuft=40, unit_cuft=40,
                              unit_weight=100, weight=100, going=True, manual=source == 'manual')], [], 'report-1', None, db)
    db.commit()
    view = load_inventory_editor(access, db)
    result = save_inventory_edits(InventoryEdits(request_id=uuid4(), revision=view['revision'], report_id=view['report_id'],
                                                 rooms={'delete': [room['id'] for room in view['rooms']]}), access, db)
    saved = json.loads(db.get(LeadLiveSwitch, 'L1').details)
    assert list_rows(job.id, db)[0] == []
    if ends:
        assert result['report_id'] is None and 'last_spark_id' not in saved and 'report_source' not in saved
        # It goes to history as it was before the delete.
        [past] = saved['spark_history']
        assert past['last_spark_id'] == 'report-1' and [row['name'] for row in past['question_original_rows']] == ['Sofa']
        # The window keeps working: the next edit belongs to no report.
        view = load_inventory_editor(access, db)
        assert view['report_id'] is None
    else:
        assert result['report_id'] == 'report-1' and saved['last_spark_id'] == 'report-1'
