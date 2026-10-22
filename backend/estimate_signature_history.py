"""Signed estimates matched to the inventory report each one was signed for."""
import json

from models import EstimateSignature


# Document inputs only: transport metadata (report IDs, load status, preparation
# time and signature history) is not part of what the customer signs.
ESTIMATE_FIELDS = (
    'estimate', 'storage', 'stairs', 'elevator', 'long_carry', 'shuttle',
    'extra_stops', 'packing_package', 'packing_items', 'item_questions',
    'name', 'phone', 'email', 'move_date', 'pickup', 'delivery', 'stops',
    'company_details', 'item_services', 'documents',
)


def estimate_state(data, rows):
    from fastapi.encoders import jsonable_encoder
    from decimal import Decimal
    def normalize(value):
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in sorted(value.items())
                    if key not in {'revision', '_inventory_record_id', 'request_id'}}
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            return str(Decimal(str(value)).normalize())
        return value
    fields = ('room', 'name', 'amount', 'cuft', 'weight', 'going', 'not_shipping', 'mover_pack')
    inventory = [{key: row.get(key) for key in fields} for row in rows]
    inventory = sorted((normalize(row) for row in inventory), key=lambda row: json.dumps(row, sort_keys=True))
    return {'data': normalize(jsonable_encoder({key: data.get(key) for key in ESTIMATE_FIELDS})), 'rows': inventory}


def estimate_signature_status(db, lead_id, job_id, current, inventory_rows, inventory_pending=False):
    record = db.query(EstimateSignature.snapshot).filter(
        EstimateSignature.lead_id == lead_id, EstimateSignature.job_id == job_id,
        EstimateSignature.signed_at.isnot(None),
    ).order_by(EstimateSignature.signed_at.desc()).first()
    if not record:
        return 'unsigned'
    if inventory_pending:
        return 'changed'
    try:
        snapshot = json.loads(record.snapshot)
        previous = estimate_state(snapshot['data'], snapshot.get('rows', []))
    except (ValueError, KeyError, TypeError, AttributeError):
        return 'changed'
    return 'signed' if previous == estimate_state(current, inventory_rows) else 'changed'


def estimate_requires_signature(db, lead_id, job_id, report_id, current, inventory_rows=None, inventory_pending=False):
    # Compatibility for callers; a report identity is not an estimate version.
    return estimate_signature_status(db, lead_id, job_id, current, inventory_rows or [], inventory_pending) == 'changed'


def _snapshot_report_id(snapshot):
    # Signatures saved before report_id existed: the signed snapshot holds the report used for pricing.
    try:
        return ((json.loads(snapshot or '{}').get('data') or {}).get('spark') or {}).get('id')
    except (ValueError, AttributeError):
        return None


def signed_estimates(db, lead_id, job_id=None):
    """Signed estimates for a lead (or one job), newest first, without loading the PDFs."""
    query = db.query(EstimateSignature.id, EstimateSignature.signer_name, EstimateSignature.signed_at,
                     EstimateSignature.report_id).filter(EstimateSignature.lead_id == lead_id,
                                                         EstimateSignature.signed_at.isnot(None))
    if job_id:
        query = query.filter(EstimateSignature.job_id == job_id)
    rows = query.order_by(EstimateSignature.signed_at.desc()).all()
    legacy = [row.id for row in rows if not row.report_id]
    snapshots = dict(db.query(EstimateSignature.id, EstimateSignature.snapshot)
                     .filter(EstimateSignature.id.in_(legacy)).all()) if legacy else {}
    return [{'id': row.id, 'name': row.signer_name, 'signed_at': row.signed_at.isoformat() + 'Z',
             'report_id': row.report_id or _snapshot_report_id(snapshots.get(row.id))} for row in rows]


def attach_signatures(reports, signatures):
    """Add each report's signed estimates (newest first) to the report history rows."""
    by_report = {}
    for signature in signatures:
        by_report.setdefault(signature['report_id'], []).append(
            {key: signature[key] for key in ('id', 'name', 'signed_at')})
    for report in reports:
        report['signatures'] = by_report.get(report['id'], [])
    return reports
