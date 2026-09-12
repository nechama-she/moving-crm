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
    assert result['review_count'] == 1
    assert result['undated_moves'] == 1
    assert result['total_moves'] == 1
    assert any(any('exactly matches CRM' in issue for issue in r['issues']) for r in result['moves'])


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


def test_city_state_zip_matches_zip_only_for_matts_move():
    rows = [lead('a', pickup='Riverdale, Maryland 20737', delivery='Sumrall, Mississippi 39482'),
            lead('b', pickup='20737', delivery='39482'),
            lead('c', pickup='Riverdale MD 20737', delivery='Sumrall MS 39482')]
    result = report(rows)
    assert result['total_moves'] == 1
    assert result['duplicates_removed'] == 2


def test_job_details_override_blank_or_stale_lead_fields():
    from types import SimpleNamespace
    from booking_report import report_lead_row
    original = SimpleNamespace(id='a', full_name='Matt', phone='6016410186', email='',
        move_date='2026-09-15', pickup_zip='', delivery_zip='',
        created_time='2026-09-12T15:20:54Z', created_at=None,
        status='quoted', booked_move_date=None, company=None, company_id='c', assigned_to=None)
    job = SimpleNamespace(move_date='2026-09-16', pickup_zip='Riverdale, Maryland 20737',
        delivery_zip='Sumrall, Mississippi 39482')
    row = report_lead_row(original, job)
    result = report([row])
    assert result['moves'][0]['move_date'] == '2026-09-16'
    assert result['moves'][0]['pickup'] == job.pickup_zip
    assert result['review_count'] == 0
    assert report_lead_row(original)['move_date'] == '2026-09-15'


def test_different_street_addresses_in_same_zip_merge():
    result = report([lead('a', pickup='100 Main St Baltimore MD 21201'),
                     lead('b', pickup='200 Main St Baltimore MD 21201')])
    assert result['total_moves'] == 1


def test_crm_import_date_never_places_missing_signup_in_september():
    result = report([lead('a', created_time='', created_at='2026-09-12T18:00:00Z')])
    assert result['total_moves'] == 0
    assert result['undated_moves'] == 1
    assert result['percentage'] is None


def test_old_smartmoving_signup_does_not_use_recent_import_date():
    result = report([lead('a', created_time='2025-01-01T15:00:00Z')])
    assert result['total_moves'] == 0


def test_review_reasons_are_specific_to_each_linked_lead():
    result = report([lead('a', pickup='', move_date=''), lead('b', delivery='')])
    by_id = {row['id']: row for move in result['moves'] for row in move['leads']}
    assert by_id['a']['issues'] == ['Move date is missing or invalid', 'Pickup is missing']
    assert by_id['b']['issues'] == ['Delivery is missing']


def test_company_and_rep_filters_preserve_original_cohort():
    rows = [lead('a', company_id='a', rep_id='r1', created_time='2026-08-10T15:00:00Z'),
            lead('b', company_id='b', rep_id='r2', status='booked')]
    august = booking_report(rows, date(2026,8,1), date(2026,8,31), ['b'], ['r2'])
    assert august['total_moves'] == august['booked_moves'] == 1
    assert len(august['moves'][0]['leads']) == 1
    assert booking_report(rows, date(2026,9,1), date(2026,9,30), ['b'])['total_moves'] == 0
    assert booking_report(rows, date(2026,8,1), date(2026,8,31), ['a'])['booked_moves'] == 0
    assert booking_report(rows, date(2026,8,1), date(2026,8,31), ['b'], ['r1'])['total_moves'] == 0
