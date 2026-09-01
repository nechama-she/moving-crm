import json

from sqlalchemy.orm import Session

from models import AppSetting


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
        return {str(rep_id) for rep_id in (rule.get("rep_user_ids") or []) if rep_id}
    return None
