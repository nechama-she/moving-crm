import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from inventory_questions import QuestionRule, matches, questions, adjusted_inventory

def rule():
    return dict(id='plants', title='Plants', question='Is this live?', enabled=True, item_ids=[], words=['plant'], photo=True,
        answers=[dict(id='yes', label='Yes', action='exclude', notice='We cannot transport live plants.', acknowledge=True),
                 dict(id='no', label='No', action='none', notice='', acknowledge=False)])

def test_matching_is_explicit_and_whole_word():
    r=rule()
    assert matches(r, {'name':'Large potted plant'}, {})
    assert not matches(r, {'name':'Plantation table'}, {})
    r['item_ids']=['catalog-1']
    assert matches(r, {'item_id':'catalog-1', 'name':'Changed name'}, {})
    assert matches(r, {'name':'Artificial Tree'}, {'catalog-1':'Artificial Tree'})
    assert not matches(r, {'name':'Tree'}, {'catalog-1':'Artificial Tree'})

def test_actions_require_explanation_and_matching():
    assert QuestionRule(**rule())
    r=rule(); r['answers'][0]['notice']=' '
    with pytest.raises(ValueError): QuestionRule(**r)
    r=rule(); r['words']=[]
    with pytest.raises(ValueError): QuestionRule(**r)

def test_exclusion_is_idempotent_and_reversible():
    company=SimpleNamespace(customer_questions=json.dumps([rule()]))
    state={}; db=MagicMock()
    rows=[dict(name='Plant',amount=2,cuft=12,weight=4),dict(name='Chair',amount=1,cuft=20,weight=10)]
    kept,volume,weight=adjusted_inventory(company,state,rows,32,14,db)
    question=questions(company,state,db)[0]
    state['report_question_answers']={question['id']:{'answer_id':'yes','acknowledged':True}}
    for _ in range(3):
        kept,volume,weight=adjusted_inventory(company,state,kept,volume,weight,db)
        assert (volume,weight)==(26,12)
        assert [r['name'] for r in kept]==['Plant', 'Chair']
        assert kept[0]['amount'] == 1
    state['report_question_answers'][question['id']]['answer_id']='no'
    kept,volume,weight=adjusted_inventory(company,state,kept,volume,weight,db)
    assert (kept,volume,weight)==(rows,32,14)

def test_rule_changes_invalidate_old_answers():
    r=rule(); company=SimpleNamespace(customer_questions=json.dumps([r])); state={}; db=MagicMock()
    rows=[dict(name='Plant',amount=1,cuft=12)]
    adjusted_inventory(company,state,rows,12,0,db)
    q=questions(company,state,db)[0]
    state['report_question_answers']={q['id']:{'answer_id':'yes','acknowledged':True}}
    r['question']='Is this plant alive?'; company.customer_questions=json.dumps([r])
    assert questions(company,state,db)[0]['saved'] is None
    assert adjusted_inventory(company,state,[],0,0,db)[1]==12

def test_company_without_rules_has_no_questions():
    assert questions(SimpleNamespace(customer_questions=None), {'spark_inventory_snapshot':[{'name':'Plant'}]},MagicMock())==[]


def test_pending_acknowledgment_does_not_exclude_and_can_restore_item():
    company=SimpleNamespace(customer_questions=json.dumps([rule()]))
    state={}; db=MagicMock(); rows=[dict(name='Plant',amount=1,cuft=12,weight=4)]
    adjusted_inventory(company,state,rows,12,4,db)
    key=questions(company,state,db)[0]['id']
    state['report_question_answers']={key:{'answer_id':'yes','acknowledged':False,'pending':True}}
    assert adjusted_inventory(company,state,rows,12,4,db)==(rows,12,4)
    state['report_question_answers'][key].update(acknowledged=True,pending=False)
    assert adjusted_inventory(company,state,rows,12,4,db)==([],0,0)
    state['report_question_answers'][key].update(acknowledged=False,pending=True)
    assert adjusted_inventory(company,state,[],0,0,db)==(rows,12,4)


def test_each_unit_has_independent_acknowledgment_and_legacy_answers():
    company = SimpleNamespace(customer_questions=json.dumps([rule()]))
    db = MagicMock()
    rows = [dict(name='Plant', amount=2, cuft=12, weight=4)]
    state = {}
    adjusted_inventory(company, state, rows, 12, 4, db)
    first, second = questions(company, state, db)
    assert first['label'] == 'Plant (1 of 2)'
    assert second['label'] == 'Plant (2 of 2)'
    assert first['id'] != second['id']
    state['report_question_answers'] = {first['id']: {'answer_id': 'yes', 'acknowledged': False, 'pending': True}}
    assert adjusted_inventory(company, state, rows, 12, 4, db)[1] == 12
    state['report_question_answers'][first['id']].update(acknowledged=True, pending=False)
    assert adjusted_inventory(company, state, rows, 12, 4, db)[1] == 6
    assert questions(company, state, db)[1]['saved'] is None
    legacy_key = first['id'].rsplit(':', 1)[0]
    state['report_question_answers'] = {legacy_key: {'answer_id': 'yes', 'acknowledged': True}}
    assert adjusted_inventory(company, state, rows, 12, 4, db)[1] == 0
