import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from estimate_questions import unanswered_questions


def test_no_packing_requires_additional_item_confirmation():
    package = {'selection':{'mode':'none'}}
    assert 'protection' in unanswered_questions({'packing_package':package})
    package['selection']['has_additional_protection'] = False
    assert 'protection' not in unanswered_questions({'packing_package':package})
    package['selection']['has_additional_protection'] = True
    assert 'protection' in unanswered_questions({'packing_package':package})
    package['selection']['additional_items'] = {'bed':{'protection':'fabric','service':'self'}}
    assert 'protection' not in unanswered_questions({'packing_package':package})


def test_full_and_partial_packing_skip_protection_question():
    for mode in ('full','partial'):
        assert 'protection' not in unanswered_questions({'packing_package':{'selection':{'mode':mode}}})
