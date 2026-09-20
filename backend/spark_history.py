"""Report snapshots stored with the lead's existing LiveSwitch conversation."""
from copy import deepcopy

REPORT_KEYS = ('last_spark_id', 'last_spark_status', 'last_spark_at', 'last_spark_share_url',
               'spark_extracted_id', 'spark_extracted_cuft', 'spark_extracted_weight',
               'spark_processing', 'spark_inventory_snapshot', 'spark_pricing_ready')


def remember_report(details):
    report_id = details.get('last_spark_id')
    if not report_id:
        return
    reports = details.setdefault('spark_history', [])
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
                'inventory': row.get('spark_inventory_snapshot', [])}
        if staff:
            item['processing'] = row.get('spark_processing')
        result.append(item)
    return result


def activate_report(details, report_id):
    remember_report(details)
    row = next((row for row in details.get('spark_history', []) if row.get('last_spark_id') == report_id), None)
    if row is None:
        raise ValueError('Report does not belong to this move.')
    if row.get('last_spark_status') != 'completed' or not row.get('last_spark_share_url'):
        raise ValueError('Only completed reports can be selected for pricing.')
    for key in REPORT_KEYS:
        details.pop(key, None)
    details.update(deepcopy(row))
