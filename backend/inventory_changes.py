"""Compare inventory content without treating submission IDs as edits."""


def inventory_draft_changed(state):
    draft = state.get('inventory_draft')
    if not draft:
        return False
    # Snapshot-based report generation can store an empty rooms payload.
    # Compare the input rows before any question-driven exclusions first.
    report_rows = state.get('question_original_rows', state.get('spark_inventory_snapshot'))
    if 'rows' in draft and report_rows is not None and draft['rows'] == report_rows:
        return False
    body = draft.get('body')
    report = state.get('report_list_body')
    if isinstance(body, dict) and isinstance(report, dict):
        return {k: v for k, v in body.items() if k != 'request_id'} != {
            k: v for k, v in report.items() if k != 'request_id'}
    return body != report
