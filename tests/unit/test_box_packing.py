import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from box_packing import movers_pack_count


@pytest.mark.parametrize('row,expected', [
    ({'name': 'Wardrobe Box', 'amount': 16, 'mover_pack_count': 5}, 5),
    ({'name': 'Wardrobe Box', 'amount': 16, 'mover_pack_count': 40}, 16),
    ({'name': 'Wardrobe Box', 'amount': 16, 'mover_pack_count': 0, 'mover_pack': True}, 0),
    ({'name': 'Wardrobe Box (CP)', 'amount': 4}, 4),
    ({'name': 'Wardrobe Box (PBO)', 'amount': 4}, 0),
    ({'name': 'Wardrobe Box', 'amount': 3, 'mover_pack': True}, 3),
    ({'name': 'Wardrobe Box (CP)', 'amount': 3, 'mover_pack': False}, 0),
    ({'name': 'Book Box', 'amount': 2}, 0),
])
def test_movers_count_comes_from_the_row_and_reads_older_cp_rows(row, expected):
    assert movers_pack_count(row) == expected
