"""One-time move of every move's inventory from its saved report JSON into the inventory tables.

Each row keeps its question key (its position and contents in the report, as its item questions were identified), so
answers and signed estimates stay as they are; who added each item, the units answers took off, the rooms and the
move's volume all stay as they were. Approved estimates are not touched.
"""
import json
from decimal import Decimal

INVENTORY_KEYS = ('spark_inventory_snapshot', 'question_original_rows', 'manual_rooms', 'question_excluded_items',
                  'question_original_cuft', 'question_original_weight', 'report_list_rows', 'report_list_body',
                  'report_list_cuft', 'report_list_weight')


def keyed_rows(rows, source, listed):
    """The report's rows with their question keys and who added them, as the report identified and treated them."""
    from inventory_questions import revision
    result = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        keyed = dict(row, question_key=f'{index}:{revision(row)}')
        if keyed.get('manual') is None:
            # Saved before rows recorded where they came from: a list's rows, or a combined report's list part.
            keyed['manual'] = source == 'manual' or (source == 'combined' and (str(row.get('room') or ''), str(row.get('name') or '')) in listed)
        result.append(keyed)
    return result


def listed_items(details):
    return {(str(row.get('room') or ''), str(row.get('name') or '')) for row in details.get('report_list_rows') or [] if isinstance(row, dict)}


def migrate_move(saved, db):
    """Move one lead's inventory into its job's tables. Returns whether anything changed. Does not commit."""
    from models import Lead, LeadJob, Company, InventoryEditState
    from inventory_edits import fill_inventory, active_report, shipping_rows, lead_job_id, _money
    from inventory_questions import apply_answers
    details = json.loads(saved.details or '{}')
    lead = db.get(Lead, saved.lead_id)
    job_id = lead_job_id(saved.lead_id, db) if lead else None
    job = db.get(LeadJob, job_id) if job_id else None
    changed = False
    # Past reports keep their saved form; a past report chosen again gets its rows' keys then (activate_report).
    report_id = active_report(details)
    rows = details.get('question_original_rows') or details.get('spark_inventory_snapshot')
    carried = details.get('carried_question_state') or {}
    if job and report_id and rows:
        source = details.get('report_source', 'liveswitch')
        keyed = keyed_rows(rows, source, listed_items(details))
        state = fill_inventory(job, keyed, details.get('manual_rooms') or [], report_id, db.get(InventoryEditState, job.id), db)
        company = lead.company or db.query(Company).filter(Company.is_default_company.is_(True)).one_or_none()
        apply_answers(company, details, job.id, db)
        shipped = shipping_rows(job.id, db)
        # The move's volume and weight stay as they are: the part its items do not add up to is kept with the report.
        details['report_volume_offset'] = float(_money(lead.volume) - sum((_money(r['unit_cuft']) * r['amount'] for r in shipped), Decimal(0)))
        details['report_weight_offset'] = float(_money(lead.weight) - sum((_money(r['unit_weight']) * r['amount'] for r in shipped), Decimal(0)))
        # A list edited after its report saved its rows from the editor; a list report always did.
        if source != 'manual' and any(isinstance(row, dict) and 'inventory_row_id' in row for row in rows):
            details['report_edited'] = True
        state.source_hash = ''
        changed = True
    elif job and (carried.get('question_original_rows') or carried.get('spark_inventory_snapshot')):
        # A report is running: the previous report's items wait in the table for it, with their answers.
        previous = carried.get('question_original_rows') or carried.get('spark_inventory_snapshot')
        fill_inventory(job, keyed_rows(previous, 'liveswitch', set()), [], None, db.get(InventoryEditState, job.id), db)
        changed = True
    if carried and set(carried) - {'report_question_answers'}:
        details['carried_question_state'] = {'report_question_answers': carried.get('report_question_answers', {})}
        changed = True
    for key in INVENTORY_KEYS:
        if key in details:
            details.pop(key)
            changed = True
    if changed:
        saved.details = json.dumps(details)
    return changed


def migrate_inventories(session_factory):
    """Every lead whose saved report holds an inventory, one commit each. Approved estimates are left as they are."""
    from sqlalchemy import event, or_
    from sqlalchemy.orm import Session
    from models import LeadLiveSwitch
    import estimate_approval
    hook = estimate_approval._clear_changed_approvals
    hooked = event.contains(Session, 'before_flush', hook)
    if hooked:
        event.remove(Session, 'before_flush', hook)
    moved = 0
    try:
        with session_factory() as db:
            lead_ids = [lead_id for (lead_id,) in db.query(LeadLiveSwitch.lead_id).filter(or_(
                *[LeadLiveSwitch.details.contains(f'"{key}"') for key in ('spark_inventory_snapshot', 'question_original_rows', 'carried_question_state')]))]
        for lead_id in lead_ids:
            with session_factory() as db:
                saved = db.query(LeadLiveSwitch).filter_by(lead_id=lead_id).with_for_update().first()
                if saved and migrate_move(saved, db):
                    db.commit()
                    moved += 1
    finally:
        if hooked:
            event.listen(Session, 'before_flush', hook)
    return moved
