import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from move_types import normalize_move_type


@pytest.mark.parametrize('value', ['Local', 'Intrastate', 'in_state', 'within the state', ' INTRASTATE '])
def test_same_state_is_local(value):
    assert normalize_move_type(value) == 'Local'


@pytest.mark.parametrize('value', ['Interstate', 'out_of_state', 'out of state', 'long_distance', 'Long Distance'])
def test_out_of_state_is_long_distance(value):
    assert normalize_move_type(value) == 'Long Distance'


def test_unknown_does_not_guess_category():
    assert normalize_move_type(None) == ''
    assert normalize_move_type('unknown') == 'unknown'
