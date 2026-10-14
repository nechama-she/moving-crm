"""Read-only booking cohorts derived entirely from stored CRM data."""
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from dateutil.parser import parse

EASTERN = ZoneInfo('America/New_York')
BOOKED = {'booked', 'scheduled', 'completed'}


def timestamp(value):
    if not value:
        return None
    try:
        raw = str(value).strip()
        if re.fullmatch(r'\d+(\.\d+)?', raw):
            number = float(raw)
            result = datetime.fromtimestamp(number / 1000 if number >= 1e12 else number, timezone.utc)
        else:
            result = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def move_day(value):
    raw = str(value or '').strip()
    if not raw:
        return ''
    try:
        # Do not infer today's missing month/day for incomplete date strings.
        if not re.search(r'\b\d{4}\b', raw):
            return ''
        first = parse(raw, fuzzy=False, default=datetime(2000, 1, 1)).date()
        second = parse(raw, fuzzy=False, default=datetime(2000, 2, 2)).date()
        return first.isoformat() if first == second else ''
    except (ValueError, OverflowError):
        return ''


def location(value):
    raw = str(value or '').strip()
    matches = list(re.finditer(r'(?<!\d)(\d{5})(?:-\d{4})?(?!\d)', raw))
    postal = matches[-1] if matches else None
    # Match by ZIP even when street text differs, per reporting rules.
    if postal:
        return 'zip:' + postal.group(1)
    return re.sub(r'\W+', ' ', raw.casefold()).strip()


def identities(row):
    phone = re.sub(r'\D', '', row.get('phone') or '')
    if len(phone) == 11 and phone.startswith('1'):
        phone = phone[1:]
    result = []
    if len(phone) >= 10 and len(set(phone)) > 1:
        result.append('phone:' + phone)
    email = str(row.get('email') or '').strip().casefold()
    if '@' in email:
        result.append('email:' + email)
    return result


def lead_issues(row):
    issues = []
    smart = timestamp(row.get('created_time'))
    if not smart:
        issues.append('SmartMoving signup time is missing or invalid')
    elif smart == timestamp(row.get('created_at')):
        issues.append('SmartMoving signup time exactly matches CRM creation time; verify it')
    if not move_day(row.get('move_date')):
        issues.append('Move date is missing or invalid')
    if not location(row.get('pickup')):
        issues.append('Pickup is missing')
    if not location(row.get('delivery')):
        issues.append('Delivery is missing')
    if not identities(row):
        issues.append('No usable phone number or email for customer matching')
    return issues


def booking_report(rows, start: date, end: date, company_ids=None, rep_ids=None):
    # Resolve identities over ALL dates before choosing a cohort. This also joins
    # phone-only/email-only records when another record contains both identifiers.
    parent = list(range(len(rows)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    known = {}
    for i, row in enumerate(rows):
        for key in identities(row):
            if key in known:
                parent[root(i)] = root(known[key])
            else:
                known[key] = i
    groups = defaultdict(list)
    for i, row in enumerate(rows):
        signature = (move_day(row.get('move_date')), location(row.get('pickup')), location(row.get('delivery')))
        # Unknown details must not silently combine two distinct moves.
        complete = all(signature) and bool(identities(row))
        key = (root(i), signature) if complete else ('incomplete', row['id'])
        groups[key].append(row)
    selected = []
    undated = 0
    for members in groups.values():
        scoped = [row for row in members
                  if (not company_ids or row.get('company_id') in company_ids)
                  and (not rep_ids or (row.get('rep_id') or '__unassigned__') in rep_ids)]
        if not scoped:
            continue
        dates = []
        issues = set()
        for row in members:
            smart = timestamp(row.get('created_time'))
            issues.update(lead_issues(row))
            if smart:
                dates.append(smart)
        if not dates:
            undated += 1
            continue
        first = min(dates)
        if not start <= first.astimezone(EASTERN).date() <= end:
            continue
        members = scoped
        issues = {issue for row in members for issue in lead_issues(row)}
        representative = min(members, key=lambda r: timestamp(r.get('created_time')) or datetime.max.replace(tzinfo=timezone.utc))
        booked = any(str(r.get('status') or '').casefold() in BOOKED or r.get('booked_move_date') for r in members)
        selected.append({
            'id': representative['id'], 'customer': representative.get('name') or 'Unnamed customer',
            'first_signup': first.isoformat(), 'move_date': move_day(representative.get('move_date')),
            'pickup': representative.get('pickup') or '', 'delivery': representative.get('delivery') or '',
            'booked': booked, 'issues': sorted(issues),
            'leads': [{'id': r['id'], 'company': r.get('company') or '', 'status': r.get('status') or '',
                       'created_time': str(r.get('created_time') or ''), 'created_at': str(r.get('created_at') or ''),
                       'issues': lead_issues(r)} for r in members],
        })
    selected.sort(key=lambda r: (r['first_signup'], r['id']), reverse=True)
    total = len(selected)
    booked = sum(r['booked'] for r in selected)
    lead_count = sum(len(r['leads']) for r in selected)
    return {'start': start.isoformat(), 'end': end.isoformat(), 'timezone': 'America/New_York',
            'total_moves': total, 'booked_moves': booked,
            'percentage': round(booked / total * 100, 2) if total else None,
            'lead_count': lead_count, 'duplicates_removed': lead_count - total,
            'review_count': sum(bool(r['issues']) for r in selected), 'undated_moves': undated,
            'moves': selected}


def report_lead_row(lead, primary_job=None):
    def move_value(field):
        value = getattr(primary_job, field, None) if primary_job else None
        return value if str(value or '').strip() else getattr(lead, field, None)
    return {
        'id': lead.id, 'name': lead.full_name, 'phone': lead.phone, 'email': lead.email,
        'move_date': move_value('move_date'), 'pickup': move_value('pickup_zip'),
        'delivery': move_value('delivery_zip'),
        'created_time': lead.created_time, 'created_at': lead.created_at,
        'status': lead.status, 'booked_move_date': lead.booked_move_date,
        'company': lead.company.name if lead.company else '',
        'company_id': lead.company_id, 'rep_id': lead.assigned_to,
    }
