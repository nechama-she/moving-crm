import json
from datetime import datetime

from dateutil.tz import gettz

from sqlalchemy.orm import Session

from models import AppSetting, Company


SETTING_KEY = "referral_source_assignment_rules_v1"


def normalize_referral_source(value: str | None) -> str:
    return " ".join((value or "").strip().casefold().split())


def load_referral_assignment_rules(db: Session) -> list[dict]:
    row = db.query(AppSetting).filter(AppSetting.key == SETTING_KEY).first()
    if not row or not row.value:
        return []
    try:
        value = json.loads(row.value)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def save_referral_assignment_rules(db: Session, rules: list[dict]) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == SETTING_KEY).first()
    value = json.dumps(rules, separators=(",", ":"))
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=SETTING_KEY, value=value))


def configured_rep_ids_for_referral(
    db: Session,
    company_id: str,
    referral_source: str | None,
    rules: list[dict] | None = None,
    now: datetime | None = None,
    timezone_name: str | None = None,
) -> set[str] | None:
    normalized = normalize_referral_source(referral_source)
    if not normalized:
        return None
    for rule in rules if rules is not None else load_referral_assignment_rules(db):
        if not rule.get("active", True):
            continue
        if str(rule.get("company_id") or "") != company_id:
            continue
        if normalize_referral_source(str(rule.get("referral_source") or "")) != normalized:
            continue
        assignments = rule.get("rep_assignments")
        if not isinstance(assignments, list):
            assignments = [
                {"rep_user_id": rep_id, "schedule": "always"}
                for rep_id in (rule.get("rep_user_ids") or [])
                if rep_id
            ]
        if timezone_name is None:
            company = db.query(Company.timezone).filter(Company.id == company_id).first()
            timezone_name = (company[0] if company else None) or "America/New_York"
        zone = gettz(timezone_name) or gettz("America/New_York")
        current = now or datetime.now(zone)
        if current.tzinfo is None:
            current = current.replace(tzinfo=zone)
        else:
            current = current.astimezone(zone)
        today = current.date().isoformat()
        eligible: set[str] = set()
        for assignment in assignments:
            rep_id = str(assignment.get("rep_user_id") or "")
            if not rep_id:
                continue
            if assignment.get("schedule", "always") == "always":
                eligible.add(rep_id)
                continue
            start_date = str(assignment.get("start_date") or "")
            end_date = str(assignment.get("end_date") or "")
            if start_date and today < start_date:
                continue
            if end_date and today > end_date:
                continue
            eligible.add(rep_id)
        return eligible
    return None
