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


# The fields of the estimate worked out from the item list, in each part: the tables write the same list their way, so
# those fields come out written their way too. Everything else in the parts (the price sheet's rates and minimums, the questions, prices
# and answers) is not from the list, and must match as signed.
PACKAGE_LIST_FIELDS = ('items', 'box_items', 'other_inventory', 'material_quotes')
BULKY_LIST_FIELDS = ('name', 'label')
QUESTION_LIST_FIELDS = ('item_index', 'reference_name', 'name', 'label', 'room', 'items', 'photo')


def _without_list_fields(data):
    """The estimate's data less the fields worked out from the item list."""
    data = dict(data)
    package = data.get('packing_package')
    if isinstance(package, dict):
        package = {key: value for key, value in package.items() if key not in PACKAGE_LIST_FIELDS}
        if isinstance(package.get('selection'), dict):
            # The boxes the movers pack are counted from the list's box rows.
            package['selection'] = {key: value for key, value in package['selection'].items() if key != 'box_quantities'}
        data['packing_package'] = package
    for part, fields in (('packing_items', BULKY_LIST_FIELDS), ('item_questions', QUESTION_LIST_FIELDS)):
        if isinstance(data.get(part), list):
            data[part] = [{key: value for key, value in row.items() if key not in fields} if isinstance(row, dict) else row
                          for row in data[part]]
    return data


def signed_now(job, rows, db):
    """Before the move: the job's latest signed estimate, when it shows as signed now. Its list is compared as the page
    compares it before this move: the saved rows with their catalog names. Else None."""
    from models import EstimateSignature
    from catalog_names import resolve_catalog_names
    from estimate_signature_history import estimate_state
    signed = (db.query(EstimateSignature).filter(EstimateSignature.lead_id == job.lead_id, EstimateSignature.job_id == job.id,
                                                 EstimateSignature.signed_at.isnot(None))
              .order_by(EstimateSignature.signed_at.desc()).first())
    if signed is None:
        return None
    try:
        snapshot = json.loads(signed.snapshot)
        signed_rows = snapshot.get('rows', [])
    except (ValueError, AttributeError):
        return None
    if estimate_state({}, signed_rows)['rows'] != estimate_state({}, resolve_catalog_names(rows, db))['rows']:
        return None
    return signed


def keep_signed(signed, job, db):
    """After the move: a signed estimate that showed as signed before it keeps showing as signed. The tables write the
    same list in another form, so the move is noted as it is now (a fingerprint beside the signature): the estimate
    shows as signed until the move changes from this. The signed estimate itself (its content, PDF and signature) and
    the Bill of Lading are not touched. Everything not written from the list (people, addresses, dates, charges,
    answers, the price sheet's rates and minimums) must still match the signed estimate, or it already showed as
    changed and is left so. Does not commit."""
    from estimate_signature_history import estimate_state, state_fingerprint
    from models import PublicMoveAccess
    from routes.public_moves import _move_details
    db.flush()
    access = db.query(PublicMoveAccess).filter_by(lead_id=job.lead_id, job_id=job.id).first()
    if access is None:
        return
    db.info.pop('request_cache', None)  # Worked out from the tables as they are now.
    current, rows = _move_details(access, db, pricing_only=True, estimate_only=True)
    db.info.pop('request_cache', None)
    snapshot = json.loads(signed.snapshot)
    data = snapshot.get('data') if isinstance(snapshot.get('data'), dict) else {}
    if estimate_state(_without_list_fields(data), [])['data'] != estimate_state(_without_list_fields(current), [])['data']:
        return
    signed.migrated_state = state_fingerprint(estimate_state(current, rows))


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
    signed = None
    # Past reports keep their saved form; a past report chosen again gets its rows' keys then (activate_report).
    report_id = active_report(details)
    rows = details.get('question_original_rows') or details.get('spark_inventory_snapshot')
    carried = details.get('carried_question_state') or {}
    if job and report_id and rows:
        source = details.get('report_source', 'liveswitch')
        # Noted before anything changes: the list the page compares with now.
        signed = signed_now(job, details.get('question_original_rows', details.get('spark_inventory_snapshot', [])), db)
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
    if signed is not None:
        keep_signed(signed, job, db)
    return changed


def migrate_inventories(session_factory):
    """Every lead whose saved report holds an inventory, in one commit: any failure leaves every move as it was.
    Approved estimates are left as they are, and signed ones stay signed."""
    from sqlalchemy import event, or_
    from sqlalchemy.orm import Session
    from models import LeadLiveSwitch
    import estimate_approval
    # Loaded before anything changes: keep_signed reads the customer page's estimate.
    import routes.public_moves  # noqa: F401
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
                saved = db.query(LeadLiveSwitch).filter_by(lead_id=lead_id).with_for_update().first()
                if saved and migrate_move(saved, db):
                    db.flush()
                    moved += 1
            db.commit()
    finally:
        if hooked:
            event.listen(Session, 'before_flush', hook)
    return moved
