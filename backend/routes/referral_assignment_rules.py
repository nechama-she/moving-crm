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
    rep_assignments: list[dict]
    active: bool = True


def _validate(body: RuleBody, db: Session, exclude_rule_id: str = "") -> tuple[str, list[dict]]:
    referral_source = " ".join(body.referral_source.strip().split())
    assignments: list[dict] = []
    seen_rep_ids: set[str] = set()
    for raw in body.rep_assignments:
        rep_id = str(raw.get("rep_user_id") or "").strip()
        if not rep_id or rep_id in seen_rep_ids:
            continue
        seen_rep_ids.add(rep_id)
        schedule = "scheduled" if raw.get("schedule") == "scheduled" else "always"
        assignment = {"rep_user_id": rep_id, "schedule": schedule}
        if schedule == "scheduled":
            start_date = str(raw.get("start_date") or "").strip()
            end_date = str(raw.get("end_date") or "").strip()
            if not start_date or not end_date:
                raise HTTPException(status_code=400, detail="Scheduled reps need both a start date and an end date")
            if start_date and end_date and end_date < start_date:
                raise HTTPException(status_code=400, detail="Rep schedule end date must be on or after its start date")
            assignment.update({"start_date": start_date, "end_date": end_date})
        assignments.append(assignment)
    rep_ids = [assignment["rep_user_id"] for assignment in assignments]
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
        if str(rule.get("company_id") or "") != body.company_id or normalize_referral_source(rule.get("referral_source")) != normalized:
            continue
        existing_assignments = rule.get("rep_assignments")
        if not isinstance(existing_assignments, list):
            existing_assignments = [
                {"rep_user_id": rep_id, "schedule": "always"}
                for rep_id in (rule.get("rep_user_ids") or [])
            ]
        for assignment in assignments:
            for existing in existing_assignments:
                if str(existing.get("rep_user_id") or "") != assignment["rep_user_id"]:
                    continue
                if assignment["schedule"] == "always" or existing.get("schedule", "always") == "always":
                    raise HTTPException(status_code=409, detail="This rep already has an overlapping rule for this company and Referral Source")
                starts_before_existing_ends = assignment["start_date"] <= str(existing.get("end_date") or "")
                ends_after_existing_starts = assignment["end_date"] >= str(existing.get("start_date") or "")
                if starts_before_existing_ends and ends_after_existing_starts:
                    raise HTTPException(status_code=409, detail="This rep already has an overlapping date rule for this company and Referral Source")
    return referral_source, assignments


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
        if not isinstance(rule.get("rep_assignments"), list):
            rule["rep_assignments"] = [
                {"rep_user_id": rep_id, "schedule": "always"}
                for rep_id in (rule.get("rep_user_ids") or [])
            ]
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
    referral_source, assignments = _validate(body, db)
    rules = load_referral_assignment_rules(db)
    rules.append({
        "id": str(uuid4()),
        "company_id": body.company_id,
        "referral_source": referral_source,
        "rep_assignments": assignments,
        "active": body.active,
    })
    save_referral_assignment_rules(db, rules)
    db.commit()
    return _response(db)


@router.put("/{rule_id}")
def update_rule(rule_id: str, body: RuleBody, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    referral_source, assignments = _validate(body, db, exclude_rule_id=rule_id)
    rules = load_referral_assignment_rules(db)
    target = next((rule for rule in rules if str(rule.get("id") or "") == rule_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Assignment rule not found")
    target.update({
        "company_id": body.company_id,
        "referral_source": referral_source,
        "rep_assignments": assignments,
        "active": body.active,
    })
    target.pop("rep_user_ids", None)
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
