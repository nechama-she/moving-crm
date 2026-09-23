import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from spark_history import activate_report, remember_report, report_history


def test_history_selection_preserves_runs_and_hides_internal_logs():
    details = {'last_spark_id': 'one', 'last_spark_status': 'completed', 'last_spark_at': 100,
               'last_spark_share_url': 'https://example.com/reports/one',
               'spark_processing': {'steps': [{'error': 'internal error'}]}}
    remember_report(details)
    details.update(last_spark_id='two', last_spark_share_url='https://example.com/reports/two')
    remember_report(details)
    activate_report(details, 'one')
    reports = report_history(details)
    assert [r['id'] for r in reports] == ['two', 'one']
    assert [r['id'] for r in reports if r['current']] == ['one']
    assert all('processing' not in r for r in reports)
    assert report_history(details, staff=True)[1]['processing']['steps'][0]['error'] == 'internal error'
    details.update(last_spark_id='three', last_spark_status='queued', last_spark_at=200)
    remember_report(details)
    assert [r['id'] for r in report_history(details) if r['current']] == ['three']
    assert len(report_history(details)) == 3


def test_incomplete_or_foreign_reports_cannot_be_selected():
    details = {'last_spark_id': 'pending', 'last_spark_status': 'queued'}
    for report_id in ['pending', 'foreign']:
        with pytest.raises(ValueError):
            activate_report(details, report_id)
    assert details['last_spark_id'] == 'pending'


def test_excluded_items_remain_visible_with_zero_shipping_volume():
    from copy import deepcopy
    pool = {'item_id': 'pool', 'room': 'Bedroom', 'name': 'Pool Table', 'amount': 1, 'cuft': 100}
    chair = {'item_id': 'chair', 'room': 'Bedroom', 'name': 'Chair', 'amount': 1, 'cuft': 24}
    details = {'last_spark_id': 'one', 'last_spark_status': 'completed', 'report_source': 'manual',
               'spark_extracted_cuft': 24, 'spark_inventory_snapshot': [chair],
               'question_original_rows': [pool, chair], 'question_excluded_items': [pool],
               'manual_rooms': [{'name': 'Bedroom', 'items': [pool, chair]}]}
    original = deepcopy(details)
    report = report_history(details)[0]
    for rows in (report['inventory'], report['rooms'][0]['items']):
        assert rows[0]['not_shipping'] is True
        assert rows[0]['cuft'] == 0
        assert rows[0]['amount'] == 1
        assert sum(item['cuft'] for item in rows) == report['cuft'] == 24
    assert details == original
    details['question_excluded_items'] = []
    restored = report_history(details)[0]
    assert restored['rooms'][0]['items'][0]['cuft'] == 100
    assert 'not_shipping' not in restored['inventory'][0]


def test_exclusion_marks_only_one_matching_occurrence():
    row = {'name': 'Chair', 'room': 'Bedroom', 'amount': 1, 'cuft': 10}
    details = {'last_spark_id': 'one', 'question_original_rows': [row, row],
               'question_excluded_items': [row], 'manual_rooms': [{'name': 'Bedroom', 'items': [row, row]}]}
    report = report_history(details)[0]
    for rows in (report['inventory'], report['rooms'][0]['items']):
        assert [item['cuft'] for item in rows] == [0, 10]
