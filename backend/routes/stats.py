"""Admin-only operational statistics."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from auth import require_admin
from database import get_db
from models import Lead, User


router = APIRouter(prefix="/api/stats", tags=["Stats"])
EASTERN = ZoneInfo("America/New_York")


def _created_at(lead: Lead) -> datetime:
    raw = str(lead.created_time or "").strip()
    if raw:
        try:
            if raw.replace(".", "", 1).isdigit():
                value = float(raw)
                if value >= 1_000_000_000_000:
                    value /= 1000
                return datetime.fromtimestamp(value, tz=timezone.utc)
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
    fallback = lead.created_at or datetime.min.replace(tzinfo=timezone.utc)
    return fallback if fallback.tzinfo else fallback.replace(tzinfo=timezone.utc)


@router.get("/priority-one-quote-size")
def priority_one_quote_size(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    leads = (
        db.query(Lead)
        .options(joinedload(Lead.assignee), joinedload(Lead.company))
        .filter(Lead.priority == 1)
        .order_by(Lead.created_at.desc())
        .all()
    )
    days: dict[str, dict] = {}
    for lead in leads:
        created_at = _created_at(lead).astimezone(EASTERN)
        day_key = created_at.date().isoformat()
        rep_id = lead.assigned_to or "unassigned"
        rep_name = lead.assignee.name if lead.assignee else "Unassigned"
        volume = float(lead.volume) if lead.volume is not None and float(lead.volume) > 0 else None
        day = days.setdefault(day_key, {"date": day_key, "quotes": 0, "sized_quotes": 0, "total_cuft": 0.0, "reps": {}})
        rep = day["reps"].setdefault(rep_id, {"rep_id": rep_id, "rep": rep_name, "quotes": 0, "sized_quotes": 0, "total_cuft": 0.0, "leads": []})
        day["quotes"] += 1
        rep["quotes"] += 1
        if volume is not None:
            day["sized_quotes"] += 1
            day["total_cuft"] += volume
            rep["sized_quotes"] += 1
            rep["total_cuft"] += volume
        rep["leads"].append({
            "lead_id": lead.id,
            "client": lead.full_name or "Unnamed lead",
            "company": lead.company.name if lead.company else "",
            "rep": rep_name,
            "created_at": created_at.isoformat(),
            "volume": volume,
            "smartmoving_id": lead.smartmoving_id or "",
        })

    result = []
    for day in sorted(days.values(), key=lambda item: item["date"], reverse=True):
        reps = []
        for rep in sorted(day.pop("reps").values(), key=lambda item: item["rep"].lower()):
            rep["average_cuft"] = round(rep.pop("total_cuft") / rep["sized_quotes"], 2) if rep["sized_quotes"] else None
            reps.append(rep)
        day["average_cuft"] = round(day.pop("total_cuft") / day["sized_quotes"], 2) if day["sized_quotes"] else None
        day["reps"] = reps
        result.append(day)
    return {"days": result}
