"""Report snapshots stored with the lead's existing LiveSwitch conversation."""
from copy import deepcopy

REPORT_KEYS = ('carried_question_state', 'report_question_answers', 'question_original_rows', 'question_original_cuft', 'question_original_weight', 'question_excluded_items', 'last_spark_id', 'last_spark_status', 'last_spark_at', 'last_spark_share_url',
               'spark_extracted_id', 'spark_extracted_cuft', 'spark_extracted_weight',
               'spark_processing', 'spark_inventory_snapshot', 'spark_pricing_ready',
               'report_conversation', 'report_files', 'pending_spark_payload',
               'report_customer_packing', 'report_customer_package', 'report_source', 'manual_rooms', 'report_list_body', 'report_list_rows', 'report_list_cuft', 'report_list_weight',
               'report_edited', 'report_volume_offset', 'report_weight_offset')


CONVERSATION_KEYS = ('id', 'name', 'hostJoinUrl', 'participantJoinUrl', 'conversationUrl', 'embeddedConversationUrl')

def remember_report(details, inventory=None):
    """Keep the current report in history. inventory: its inventory from the inventory table (report_inventory), kept
    with it in the form history has always had."""
    report_id = details.get('last_spark_id')
    if not report_id:
        return
    if 'report_conversation' not in details:
        details['report_conversation'] = {key: details.get(key, '') for key in CONVERSATION_KEYS}
    reports = details.setdefault('spark_history', [])
    # Before per-run conversations, all reports shared the lead's conversation.
    for legacy in reports:
        if 'report_conversation' not in legacy:
            legacy['report_conversation'] = deepcopy(details['report_conversation'])
    snapshot = {key: deepcopy(details[key]) for key in REPORT_KEYS if key in details}
    if inventory is not None:
        snapshot.update(deepcopy(inventory))
    index = next((i for i, row in enumerate(reports) if row.get('last_spark_id') == report_id), None)
    if index is None:
        reports.append(snapshot)
    else:
        reports[index] = snapshot


def _listing(rows, rooms, body=None):
    names = {row.get('room') for row in rows}
    going = [row for row in rows if row.get('going') is not False]
    return dict(body=body, rows=rows, cuft=sum(float(row.get('cuft') or 0) for row in going),
                weight=sum(float(row.get('weight') or 0) for row in going),
                rooms=[room for room in rooms if room.get('name') in names])


def list_for_next_report(details, table_rows=(), table_rooms=()):
    """The customer's own items in the inventory table: a new report keeps them and replaces only the report's items."""
    kept = [row for row in table_rows if isinstance(row, dict) and row.get('manual') is not False]
    return _listing(kept, list(table_rooms)) if kept else None


def start_report_list(details, listing):
    """Record the list a new report combines with its media, or a media-only report without one."""
    # The list's items stay in the inventory table; the report records only that it has them.
    details.update(report_source='combined' if (listing or {}).get('rows') else 'liveswitch')


def archive_report_for_new_media(details, inventory=None):
    """Move the active run to history before starting a new media selection. inventory: report_inventory."""
    if not details.get('last_spark_id'):
        return False
    if details.get('pending_spark_payload'):
        details['last_spark_status'] = 'cancelled'
        details.pop('pending_spark_payload', None)
        details.pop('spark_start_queued_for', None)
    remember_report(details, inventory)
    # The items stay in the inventory table until the next report replaces them; their answers wait with them.
    details['carried_question_state'] = details.get('carried_question_state') or {
        'report_question_answers': deepcopy(details.get('report_question_answers', {}))}
    for key in REPORT_KEYS:
        if key != 'carried_question_state':
            details.pop(key, None)
    for key in ('notification_report_id', 'notification_until', 'notification_error',
                'report_check_timed_out', 'spark_start_queued_for', 'upload_error'):
        details.pop(key, None)
    media = details.get('media_upload') or {}
    media.pop('report_id', None)
    if media:
        details['media_upload'] = media
    return True


def _shipping_rows(rows, excluded, *, consume=False):
    # Consume matching occurrences so identical items are not all marked by one exclusion.
    remaining = excluded if consume else deepcopy(excluded)
    result = []
    for original in rows:
        item = deepcopy(original)
        match = next((entry for entry in remaining
                      if {k: v for k, v in entry.items() if k != 'excluded_quantity'} == original), None)
        if match is not None:
            remaining.remove(match)
            count = max(1, int(item.get('amount') or 1))
            excluded_count = match.get('excluded_quantity', count)
            if excluded_count < count:
                shipping = deepcopy(item)
                shipping['amount'] = count - excluded_count
                shipping['cuft'] = item['cuft'] * (count - excluded_count) / count
                result.append(shipping)
            item['amount'] = excluded_count
            item['not_shipping'] = True
            item['cuft'] = 0
        result.append(item)
    return result


def report_history(details, staff=False, inventory=None):
    """The move's reports, newest first. inventory: the current report's inventory (report_inventory)."""
    # Merge the live report without requiring writes during read-only requests.
    details = deepcopy(details)
    remember_report(details, inventory)
    rows = [row for _, row in sorted(enumerate(details.get('spark_history', [])),
            key=lambda entry: (entry[1].get('last_spark_at') or 0, entry[0]), reverse=True)]
    result = []
    for row in rows:
        item = {'id': row['last_spark_id'], 'status': row.get('last_spark_status', 'queued'),
                'created_at': row.get('last_spark_at'), 'shareUrl': row.get('last_spark_share_url'),
                'cuft': row.get('spark_extracted_cuft'), 'weight': row.get('spark_extracted_weight'),
                'current': row['last_spark_id'] == details.get('last_spark_id'),
                'source': row.get('report_source', 'liveswitch'), 'rooms': row.get('manual_rooms', []),
                'inventory': row.get('spark_inventory_snapshot', []), 'files': row.get('report_files', [])}
        excluded = row.get('question_excluded_items', [])
        item['inventory'] = _shipping_rows(row.get('question_original_rows', item['inventory']), excluded)
        remaining = deepcopy(excluded)
        for room in item['rooms']:
            room['items'] = _shipping_rows(room.get('items', []), remaining, consume=True)
        if staff:
            item['processing'] = row.get('spark_processing')
        result.append(item)
    return result


def activate_report(details, report_id, inventory=None):
    """Make a past report current again. inventory: the current report's (report_inventory), kept in history.
    Returns the chosen report's rows and rooms, for the inventory table; the record keeps no copy of them."""
    remember_report(details, inventory)
    row = next((row for row in details.get('spark_history', []) if row.get('last_spark_id') == report_id), None)
    if row is None:
        raise ValueError('Report does not belong to this move.')
    if row.get('last_spark_status') != 'completed' or (row.get('report_source') != 'manual' and not row.get('last_spark_share_url')):
        raise ValueError('Only completed reports can be selected for pricing.')
    for key in REPORT_KEYS:
        details.pop(key, None)
    details.update(deepcopy(row))
    details['report_files'] = deepcopy(row.get('report_files', []))
    for key in CONVERSATION_KEYS:
        details[key] = row.get('report_conversation', {}).get(key, '')
    rows = deepcopy(row.get('question_original_rows') or row.get('spark_inventory_snapshot') or [])
    rooms = deepcopy(row.get('manual_rooms') or [])
    if rows and not any(isinstance(r, dict) and 'question_key' in r for r in rows):
        # Kept before the inventory table: its rows get the keys their questions had, and who added each.
        from inventory_migration import keyed_rows, listed_items
        rows = keyed_rows(rows, row.get('report_source', 'liveswitch'), listed_items(row))
    if 'report_volume_offset' not in details and row.get('question_original_cuft') is not None:
        # Saved before the inventory table: its volume was the report's total less what answers took off.
        details['report_volume_offset'] = float(row['question_original_cuft']) - sum(
            float(r.get('cuft') or 0) for r in rows if isinstance(r, dict) and r.get('going') is not False)
        details['report_weight_offset'] = float(row.get('question_original_weight') or 0) - sum(
            float(r.get('weight') or 0) for r in rows if isinstance(r, dict) and r.get('going') is not False)
    for key in ('spark_inventory_snapshot', 'question_original_rows', 'manual_rooms', 'question_excluded_items',
                'question_original_cuft', 'question_original_weight', 'report_list_body', 'report_list_rows',
                'report_list_cuft', 'report_list_weight'):
        details.pop(key, None)
    return rows, rooms
