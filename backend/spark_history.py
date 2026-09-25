"""Report snapshots stored with the lead's existing LiveSwitch conversation."""
from copy import deepcopy

REPORT_KEYS = ('carried_question_state', 'report_question_answers', 'question_original_rows', 'question_original_cuft', 'question_original_weight', 'question_excluded_items', 'last_spark_id', 'last_spark_status', 'last_spark_at', 'last_spark_share_url',
               'spark_extracted_id', 'spark_extracted_cuft', 'spark_extracted_weight',
               'spark_processing', 'spark_inventory_snapshot', 'spark_pricing_ready',
               'report_conversation', 'report_files', 'pending_spark_payload',
               'report_customer_packing', 'report_customer_package', 'report_source', 'manual_rooms', 'report_list_body', 'report_list_rows', 'report_list_cuft', 'report_list_weight')


CONVERSATION_KEYS = ('id', 'name', 'hostJoinUrl', 'participantJoinUrl', 'conversationUrl', 'embeddedConversationUrl')

def remember_report(details):
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
    index = next((i for i, row in enumerate(reports) if row.get('last_spark_id') == report_id), None)
    if index is None:
        reports.append(snapshot)
    else:
        reports[index] = snapshot


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


def report_history(details, staff=False):
    # Merge the live snapshot without requiring writes during read-only requests.
    details = deepcopy(details)
    remember_report(details)
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


def activate_report(details, report_id):
    remember_report(details)
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
