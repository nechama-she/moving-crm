"""Signed estimates matched to the inventory report each one was signed for."""
import json

from models import EstimateSignature


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
