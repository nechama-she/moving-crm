import sys
from pathlib import Path
from datetime import date
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from booking_report import booking_report


def lead(id, **changes):
    row = dict(id=id, name='Customer', phone='2405707987', email='client@example.com',
               move_date='2026-10-01', pickup='100 Main St, Baltimore MD', delivery='200 Oak St, Miami FL',
               created_time='2026-09-10T15:00:00Z', created_at='2026-09-12T15:00:00Z',
               status='new', booked_move_date=None, company=id)
    row.update(changes)
    return row


def report(rows, start='2026-09-01', end='2026-09-30'):
    return booking_report(rows, date.fromisoformat(start), date.fromisoformat(end))


def test_duplicates_across_companies_and_later_booking():
    result = report([lead('a'), lead('b', created_time='2026-10-10T15:00:00Z', status='booked')])
    assert result['total_moves'] == result['booked_moves'] == 1
    assert result['percentage'] == 100
    assert result['duplicates_removed'] == 1


def test_second_signup_does_not_reenter_next_day_cohort():
    rows = [lead('a'), lead('b', created_time='2026-09-11T15:00:00Z')]
    assert report(rows, '2026-09-11', '2026-09-11')['total_moves'] == 0
    assert report(rows, '2026-09-10', '2026-09-11')['total_moves'] == 1


def test_different_moves_count_separately():
    for changes in [dict(move_date='2026-11-01'), dict(pickup='300 Other St'), dict(delivery='400 Other St')]:
        result = report([lead('a', status='booked'), lead('b', **changes)])
        assert result['total_moves'] == 2
        assert result['percentage'] == 50


def test_phone_email_bridges_and_formatting():
    rows = [lead('a', email='', phone='+1 (240) 570-7987'), lead('b'), lead('c', phone='', email=' CLIENT@EXAMPLE.COM ', pickup='100 MAIN ST Baltimore MD', move_date='10/01/2026')]
    assert report(rows)['total_moves'] == 1


def test_missing_details_do_not_merge_and_are_flagged():
    result = report([lead('a', pickup=''), lead('b', pickup='')])
    assert result['total_moves'] == result['review_count'] == 2


def test_names_alone_do_not_merge_customers():
    result = report([lead('a', phone='', email=''), lead('b', phone='', email='')])
    assert result['total_moves'] == 2


def test_fallback_and_matching_timestamp_flags():
    result = report([lead('a', created_time='bad'), lead('b', phone='3015551234', email='other@example.com', created_time='2026-09-12T15:00:00Z')])
    assert result['review_count'] == 2
    assert any('CRM timestamp used' in r['issues'] for r in result['moves'])
    assert any('Created timestamps match' in r['issues'] for r in result['moves'])


def test_eastern_boundaries_and_zero_denominator():
    rows = [lead('a', created_time='2026-09-11T03:59:59Z')]
    assert report(rows, '2026-09-10', '2026-09-10')['total_moves'] == 1
    assert report(rows, '2026-09-11', '2026-09-11')['percentage'] is None


def test_undated_records_are_reported_without_fake_date():
    result = report([lead('a', created_time='', created_at=None)])
    assert result['undated_moves'] == 1
    assert result['total_moves'] == 0


def test_booking_date_preserves_previous_booking():
    assert report([lead('a', status='cancelled', booked_move_date='2026-09-12')])['booked_moves'] == 1


def test_incomplete_move_dates_are_not_invented():
    result = report([lead('a', move_date='October 2026'), lead('b', move_date='October 2026')])
    assert result['total_moves'] == 2
    assert all(not row['move_date'] for row in result['moves'])
