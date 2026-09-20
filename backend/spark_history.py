"""Report snapshots stored with the lead's existing LiveSwitch conversation."""
from copy import deepcopy

REPORT_KEYS = ('last_spark_id', 'last_spark_status', 'last_spark_at', 'last_spark_share_url',
               'spark_extracted_id', 'spark_extracted_cuft', 'spark_extracted_weight',
               'spark_processing', 'spark_inventory_snapshot', 'spark_pricing_ready',
               'report_conversation', 'report_files', 'pending_spark_payload',
               'report_customer_packing', 'report_customer_package', 'report_source', 'manual_rooms')


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
