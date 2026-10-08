import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from unittest.mock import Mock
import pytest
from report_question_images import question_images, report_api_url

BASE = 'https://scribe-workflow-assets-production.s3.us-east-1.amazonaws.com/photo.jpg'
URL = BASE + '?X-Amz-Date=20260922T180000Z&X-Amz-Expires=14400'
NOW = 1790100000.0

def fixture():
    from datetime import datetime, timezone
    now = datetime(2026, 9, 22, 18, tzinfo=timezone.utc).timestamp()
    data = {'structuredResult': {'sections': [{'id': 'item-list', 'rows': [
        {'item_name': 'Plant', 'room': 'Living room', 'max_of_two_images': [{'reference': URL}]},
        {'item_name': 'Chair', 'room': 'Kitchen', 'max_of_two_images': [{'reference': URL}]},
    ]}]}}
    fetch = Mock(return_value=Mock(json=lambda: data))
    details = {'last_spark_id': 'report1', 'last_spark_share_url': 'https://app.scribe.liveswitch.com/public/reports/abc'}
    return now, fetch, details

def test_fetches_only_requested_items_and_reuses_until_expiry():
    now, fetch, details = fixture()
    images = question_images(details, ['Plant'], now=now, fetch=fetch)
    assert set(images) == {'Plant'}
    assert images['Plant'][0]['room'] == 'Living room'
    assert set(details['question_image_cache']['items']) == {'plant', 'chair'}
    question_images(details, ['Plant'], now=now + 100, fetch=fetch)
    assert fetch.call_count == 1
    question_images(details, ['Plant'], now=now + 14400 - 59, fetch=fetch)
    assert fetch.call_count == 2

def test_new_report_invalidates_cache_and_manual_has_no_photos():
    now, fetch, details = fixture()
    question_images(details, ['Plant'], now=now, fetch=fetch)
    details['last_spark_id'] = 'report2'
    question_images(details, ['Plant'], now=now, fetch=fetch)
    assert fetch.call_count == 2
    details['report_source'] = 'manual'
    assert question_images(details, ['Plant'], now=now, fetch=fetch) == {}
    assert fetch.call_count == 2

def test_unknown_item_does_not_receive_another_items_photo():
    now, fetch, details = fixture()
    assert question_images(details, ['Piano'], now=now, fetch=fetch) == {'Piano': []}


def test_not_going_items_keep_photos_and_refresh_legacy_cache():
    now, fetch, details = fixture()
    rows = fetch.return_value.json()['structuredResult']['sections'][0]['rows']
    rows[0]['going'] = False
    details['question_image_cache'] = {
        'report': details['last_spark_id'] + ':' + details['last_spark_share_url'],
        'items': {'plant': {'images': [], 'expires_at': now + 3600}},
    }
    images = question_images(details, ['Plant'], now=now, fetch=fetch)
    assert images['Plant'][0]['url'] == URL
    assert images['Plant'][0]['room'] == 'Living room'
    question_images(details, ['Plant'], now=now + 10, fetch=fetch)
    assert fetch.call_count == 1

@pytest.mark.parametrize('url', ['http://127.0.0.1/reports/abc', 'https://evil.test/reports/abc', 'https://app.scribe.liveswitch.com/public/reports/../../secret'])
def test_report_urls_are_restricted(url):
    with pytest.raises(ValueError): report_api_url(url)


def test_different_items_share_one_report_fetch():
    now, fetch, details = fixture()
    question_images(details, ['Plant'], now=now, fetch=fetch)
    assert question_images(details, ['Chair'], now=now+1, fetch=fetch)['Chair']
    for index in range(100):
        name = f'No photo {index}'
        assert question_images(details, [name], now=now+2, fetch=fetch) == {name: []}
    assert fetch.call_count == 1
