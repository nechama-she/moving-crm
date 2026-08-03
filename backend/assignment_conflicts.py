from dataclasses import dataclass, field
from typing import Any

from libs.common.phone import normalize_digits


def normalize_assignment_phone(value: str | None) -> str:
    digits = normalize_digits(value or "")
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def normalize_assignment_email(value: str | None) -> str:
    return (value or "").strip().lower()


def assignment_identifiers_match(
    phone: str | None,
    email: str | None,
    other_phone: str | None,
    other_email: str | None,
) -> bool:
    normalized_phone = normalize_assignment_phone(phone)
    normalized_email = normalize_assignment_email(email)
    return bool(
        (normalized_phone and normalized_phone == normalize_assignment_phone(other_phone))
        or (normalized_email and normalized_email == normalize_assignment_email(other_email))
    )


@dataclass
class AssignmentConflicts:
    same_company_match: bool = False
    excluded_rep_ids: set[str] = field(default_factory=set)
    matched_lead_ids: list[str] = field(default_factory=list)


def find_assignment_conflicts(
    db: Any,
    company_id: str,
    phone: str | None,
    email: str | None,
    exclude_lead_id: str | None = None,
) -> AssignmentConflicts:
    from models import Lead

    if not normalize_assignment_phone(phone) and not normalize_assignment_email(email):
        return AssignmentConflicts()

    query = db.query(Lead).filter(Lead.assigned_to.isnot(None))
    if exclude_lead_id:
        query = query.filter(Lead.id != exclude_lead_id)

    result = AssignmentConflicts()
    for existing in query.all():
        if not assignment_identifiers_match(phone, email, existing.phone, existing.email):
            continue
        result.matched_lead_ids.append(existing.id)
        if existing.company_id == company_id:
            result.same_company_match = True
        elif existing.assigned_to:
            result.excluded_rep_ids.add(existing.assigned_to)
    return result
