"""On-demand reference photos from the selected report, cached by signed expiry."""
from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qs
import re
import time
import httpx


def normalized(value):
    return re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).strip()


def image_expiry(url, now):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'scribe-workflow-assets-production.s3.us-east-1.amazonaws.com':
        return None
    params = parse_qs(parsed.query)
    try:
        issued = datetime.strptime(params['X-Amz-Date'][0], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).timestamp()
        expires = issued + int(params['X-Amz-Expires'][0]) - 60
        return expires if expires > now else None
    except (KeyError, ValueError, IndexError, OverflowError):
        return None


def report_api_url(share_url):
    parsed = urlsplit(share_url)
    if parsed.scheme != 'https' or parsed.hostname not in ('app.scribe.liveswitch.com', 'app.scribe.production.liveswitch.com'):
        raise ValueError('Unsupported report URL')
    match = re.fullmatch(r'/(?:public/)?reports/([A-Za-z0-9_-]+)', parsed.path.rstrip('/'))
    if not match:
        raise ValueError('Unsupported report path')
    return 'https://api.scribe.production.liveswitch.com/api/public/reports/' + match[1]


def question_images(details, names, now=None, fetch=None):
    now = time.time() if now is None else now
    if details.get('report_source') == 'manual' or not details.get('last_spark_share_url'):
        return {}
    report_key = str(details.get('last_spark_id')) + ':' + details['last_spark_share_url']
    cache = details.get('question_image_cache') or {}
    if cache.get('report') != report_key:
        cache = {'report': report_key, 'items': {}}
    keys = {normalized(name) for name in names if normalized(name)}
    missing = {key for key in keys if cache['items'].get(key, {}).get('expires_at', 0) <= now}
    if missing:
        url = report_api_url(details['last_spark_share_url'])
        response = (fetch or httpx.get)(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        rows = [row for section in (data.get('structuredResult') or {}).get('sections', [])
                if section.get('id') == 'item-list' for row in section.get('rows', [])]
        found = {key: [] for key in missing}
        for row in rows:
            key = normalized(row.get('item_name') or row.get('name') or row.get('item'))
            if key not in missing or not row.get('going', True): continue
            for image in row.get('max_of_two_images') or []:
                url = image.get('reference', '') if isinstance(image, dict) else ''
                expires = image_expiry(url, now)
                if expires:
                    found[key].append({'url': url, 'room': str(row.get('room') or ''),
                        'name': str(row.get('item_name') or row.get('name') or ''), 'expires_at': expires})
        for key, images in found.items():
            unique = list({(image['room'], image['url']): image for image in images}.values())
            cache['items'][key] = {'images': unique, 'expires_at': min((image['expires_at'] for image in unique), default=now + 60)}
    details['question_image_cache'] = cache
    return {name: cache['items'][normalized(name)]['images'] for name in names if normalized(name) in keys}
