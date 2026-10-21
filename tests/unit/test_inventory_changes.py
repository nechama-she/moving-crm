from backend.inventory_changes import inventory_draft_changed


def test_request_id_is_not_an_inventory_change():
    rooms = [{'name': 'Bedroom', 'items': [{'item_id': 'bed', 'quantity': 1}]}]
    assert not inventory_draft_changed({
        'inventory_draft': {'body': {'request_id': 'new', 'rooms': rooms}},
        'report_list_body': {'request_id': 'old', 'rooms': rooms}})


def test_snapshot_report_does_not_require_a_matching_submission_payload():
    rows = [{'name': 'Bed', 'quantity': 1, 'cuft': 70}]
    assert not inventory_draft_changed({
        'inventory_draft': {'body': {'rooms': [{'name': 'Bedroom'}]}, 'rows': rows},
        'report_list_body': {'request_id': 'new', 'rooms': []},
        'spark_inventory_snapshot': rows})


def test_changed_quantity_remains_a_change():
    assert inventory_draft_changed({
        'inventory_draft': {'body': {'rooms': [{'quantity': 2}]}, 'rows': [{'quantity': 2}]},
        'report_list_body': {'rooms': [{'quantity': 1}]},
        'spark_inventory_snapshot': [{'quantity': 1}]})


def test_no_draft_is_not_a_change():
    assert not inventory_draft_changed({'report_list_body': {'rooms': [{'name': 'Bedroom'}]}})
