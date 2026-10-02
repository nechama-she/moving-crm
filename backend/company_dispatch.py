"""Resolve an incoming dispatch company to its contract company."""

from fastapi import HTTPException
from sqlalchemy import func

from models import Company


def validate_dispatches_for(db, value, company_id=None):
    target_id = (value or "").strip() or None
    if not target_id:
        return None
    if target_id == company_id:
        raise HTTPException(400, "A company cannot dispatch for itself")
    target = db.get(Company, target_id)
    if not target:
        raise HTTPException(400, "Contract company not found")
    if target.dispatches_for_company_id:
        raise HTTPException(400, "Choose a contract company that does not dispatch for another company")
    if company_id and db.query(Company).filter(Company.dispatches_for_company_id == company_id).first():
        raise HTTPException(400, "This company is already a contract company for another dispatch company")
    return target_id


def resolve_company_dispatch(db, company):
    if not company or not company.dispatches_for_company_id:
        return company, None
    contract = db.get(Company, company.dispatches_for_company_id)
    if not contract or contract.dispatches_for_company_id:
        raise HTTPException(400, "Invalid dispatch company mapping; check company settings")
    return contract, company.id


def smartmoving_dispatch_company(db, opportunity):
    branch = opportunity.get("branch") or {}
    branch_id = str(branch.get("id") or opportunity.get("branchId") or "").strip()
    company = None
    if branch_id:
        matches = db.query(Company).filter(Company.samrtmoving_branch_id == branch_id).all()
        if len(matches) > 1:
            raise HTTPException(400, "SmartMoving branch ID matches multiple companies")
        company = matches[0] if matches else None
    name = str(branch.get("name") or "").strip()
    if company is None and name:
        matches = db.query(Company).filter(func.lower(Company.name) == name.lower()).all()
        if len(matches) > 1:
            raise HTTPException(400, "SmartMoving branch name matches multiple companies")
        company = matches[0] if matches else None
    return company if company and company.dispatches_for_company_id else None


def apply_job_dispatch(job, contract_id, dispatch_id):
    if dispatch_id:
        job.company_id = contract_id
        # A manual dispatch assignment takes precedence over an import default.
        if not job.dispatch_company_id:
            job.dispatch_company_id = dispatch_id
