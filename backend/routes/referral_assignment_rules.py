from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models import Company, Lead, User, UserCompany
from referral_assignment_rules import (
    load_referral_assignment_rules,
    normalize_referral_source,
    save_referral_assignment_rules,
)


router = APIRouter(prefix="/api/referral-assignment-rules", tags=["Referral Assignment Rules"])


class RuleBody(BaseModel):
    company_id: str
    referral_source: str
    rep_user_ids: list[str]
    active: bool = True


def _validate(body: RuleBody, db: Session, exclude_rule_id: str = "") -> tuple[str, list[str]]:
    referral_source = " ".join(body.referral_source.strip().split())
    rep_ids = list(dict.fromkeys(str(value).strip() for value in body.rep_user_ids if str(value).strip()))
    if not referral_source:
        raise HTTPException(status_code=400, detail="Referral Source is required")
    if not rep_ids:
        raise HTTPException(status_code=400, detail="Select at least one rep")
    if not db.query(Company.id).filter(Company.id == body.company_id).first():
        raise HTTPException(status_code=400, detail="Company not found")

    valid_rows = (
        db.query(User.id)
        .join(UserCompany, UserCompany.user_id == User.id)
        .filter(
            User.id.in_(rep_ids),
            User.role == "sales_rep",
            UserCompany.company_id == body.company_id,
        )
        .all()
    )
    valid_ids = {row[0] for row in valid_rows}
    if valid_ids != set(rep_ids):
        raise HTTPException(status_code=400, detail="Every selected rep must belong to the selected company")

    normalized = normalize_referral_source(referral_source)
    for rule in load_referral_assignment_rules(db):
        if str(rule.get("id") or "") == exclude_rule_id:
            continue
        if str(rule.get("company_id") or "") == body.company_id and normalize_referral_source(rule.get("referral_source")) == normalized:
            raise HTTPException(status_code=409, detail="A rule already exists for this company and Referral Source")
    return referral_source, rep_ids


def _response(db: Session) -> dict:
    companies = db.query(Company).order_by(Company.name.asc()).all()
    users = (
        db.query(User)
        .filter(User.role == "sales_rep")
        .order_by(User.name.asc())
        .all()
    )
    company_ids_by_rep: dict[str, list[str]] = {}
    for user_id, company_id in db.query(UserCompany.user_id, UserCompany.company_id).all():
        company_ids_by_rep.setdefault(user_id, []).append(company_id)
    source_rows = (
        db.query(Lead.company_id, Lead.referral_source)
        .filter(Lead.referral_source.isnot(None), Lead.referral_source != "")
        .distinct()
        .order_by(Lead.company_id.asc(), Lead.referral_source.asc())
        .all()
    )
    sources: dict[str, list[str]] = {}
    for company_id, source in source_rows:
        sources.setdefault(company_id, []).append(source)
    rules = load_referral_assignment_rules(db)
    for rule in rules:
        values = sources.setdefault(str(rule.get("company_id") or ""), [])
        source = str(rule.get("referral_source") or "")
        if source and source not in values:
            values.append(source)
            values.sort(key=str.casefold)
    return {
        "rules": rules,
        "companies": [{"id": company.id, "name": company.name} for company in companies],
        "reps": [
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "company_ids": company_ids_by_rep.get(user.id, []),
            }
            for user in users
        ],
        "referral_sources": sources,
    }


@router.get("")
def list_rules(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _response(db)


@router.post("", status_code=201)
def create_rule(body: RuleBody, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    referral_source, rep_ids = _validate(body, db)
    rules = load_referral_assignment_rules(db)
    rules.append({
        "id": str(uuid4()),
        "company_id": body.company_id,
        "referral_source": referral_source,
        "rep_user_ids": rep_ids,
        "active": body.active,
    })
    save_referral_assignment_rules(db, rules)
    db.commit()
    return _response(db)


@router.put("/{rule_id}")
def update_rule(rule_id: str, body: RuleBody, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    referral_source, rep_ids = _validate(body, db, exclude_rule_id=rule_id)
    rules = load_referral_assignment_rules(db)
    target = next((rule for rule in rules if str(rule.get("id") or "") == rule_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Assignment rule not found")
    target.update({
        "company_id": body.company_id,
        "referral_source": referral_source,
        "rep_user_ids": rep_ids,
        "active": body.active,
    })
    save_referral_assignment_rules(db, rules)
    db.commit()
    return _response(db)


@router.delete("/{rule_id}")
def delete_rule(rule_id: str, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    rules = load_referral_assignment_rules(db)
    kept = [rule for rule in rules if str(rule.get("id") or "") != rule_id]
    if len(kept) == len(rules):
        raise HTTPException(status_code=404, detail="Assignment rule not found")
    save_referral_assignment_rules(db, kept)
    db.commit()
    return _response(db)
