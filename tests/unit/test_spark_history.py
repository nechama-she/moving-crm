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
