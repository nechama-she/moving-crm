import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from catalog_names import resolve_catalog_names


def test_id_resolution_preserves_measurements_and_original_photo_name():
    item = SimpleNamespace(id='chair', name='New Chair', cuft=30)
    row = {'item_id':'chair', 'name':'Old Chair', 'amount':2, 'cuft':40, 'going':False}
    resolved = resolve_catalog_names([row], catalog=[item])[0]
    assert resolved['name'] == 'New Chair'
    assert resolved['reference_name'] == 'Old Chair'
    assert resolved['cuft'] == 40 and resolved['amount'] == 2 and resolved['going'] is False
    assert row['name'] == 'Old Chair'


def test_custom_name_and_packing_suffix_are_preserved():
    item = SimpleNamespace(id='box', name='New Box (CP)', cuft=3)
    rows = resolve_catalog_names([{'item_id':'box','name':'Old Box (CP)'},
                                  {'item_id':'box','name':'My box','name_override':True}], catalog=[item])
    assert [r['name'] for r in rows] == ['New Box (CP)', 'My box']
