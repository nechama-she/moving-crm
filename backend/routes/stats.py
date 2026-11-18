"""Admin-only operational statistics."""

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from auth import require_admin
from database import get_db
from models import Lead, LeadJob, User


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

from datetime import date
from fastapi import HTTPException, Query
from booking_report import booking_report, report_lead_row


@router.get("/booking-percentage")
def booking_percentage(start: date, end: date, company_ids: list[str] = Query(default=[]), rep_ids: list[str] = Query(default=[]), _: User = Depends(require_admin), db: Session = Depends(get_db)):
    if start > end:
        raise HTTPException(400, "Start date must be on or before end date")
    # Never prefilter leads by date: a duplicate's earliest signup and booking
    # can belong to another company or fall outside the requested date range.
    leads = db.query(Lead).options(joinedload(Lead.company), joinedload(Lead.assignee)).all()
    primary_jobs = {}
    for job in db.query(LeadJob).order_by(LeadJob.lead_id, LeadJob.job_order, LeadJob.created_at, LeadJob.id).all():
        primary_jobs.setdefault(job.lead_id, job)
    result = booking_report([report_lead_row(lead, primary_jobs.get(lead.id)) for lead in leads], start, end, company_ids, rep_ids)
    companies = {lead.company_id: lead.company.name if lead.company else lead.company_id for lead in leads}
    reps = {lead.assigned_to or '__unassigned__': lead.assignee.name if lead.assignee else 'Unassigned' for lead in leads}
    result['options'] = {'companies': [{'id': key, 'name': name} for key, name in sorted(companies.items(), key=lambda item: item[1])],
                         'reps': [{'id': key, 'name': name} for key, name in sorted(reps.items(), key=lambda item: item[1])]}
    return result


# The customer page bookings report: card fees on every payment, and Hallin's (the CRM company's) share of the rest.
CARD_FEE_PERCENT = Decimal("3.5")
CRM_FEE_PERCENT = Decimal("15")


def _cents(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@router.get("/customer-page-bookings")
def customer_page_bookings(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Every lead whose estimate was signed on the customer page: its estimate total, its payments less 3.5% card fees
    and its third-party payout (the total payment), and Hallin's 15% of that (the CRM fees). Read from what is saved."""
    from sqlalchemy import func
    from models import EstimateSignature, LeadPayment
    signed = (db.query(EstimateSignature.lead_id, func.max(EstimateSignature.signed_at).label("signed_at"))
              .filter(EstimateSignature.signed_at.isnot(None)).group_by(EstimateSignature.lead_id).subquery())
    paid = (db.query(LeadPayment.lead_id, func.sum(LeadPayment.amount).label("payments"))
            .group_by(LeadPayment.lead_id).subquery())
    rows = (db.query(Lead, signed.c.signed_at, paid.c.payments)
            .join(signed, signed.c.lead_id == Lead.id).outerjoin(paid, paid.c.lead_id == Lead.id)
            .order_by(signed.c.signed_at.desc()).all())
    items = []
    for lead, signed_at, payments in rows:
        payments = Decimal(str(payments or 0))
        card_fees = _cents(payments * CARD_FEE_PERCENT / 100)
        third_party = Decimal(str(lead.third_party_payout_amount or 0))
        total_payment = payments - card_fees - third_party
        crm_fees = _cents(max(Decimal(0), total_payment) * CRM_FEE_PERCENT / 100)
        estimate = (lead.estimated_total_data() or {}).get("finalTotal") or 0
        items.append({"lead_id": lead.id, "name": lead.full_name or "", "signed_at": signed_at.isoformat() + "Z",
                      "estimate_total": float(estimate), "payments": float(payments), "card_fees": float(card_fees),
                      "third_party": float(third_party), "total_payment": float(total_payment), "crm_fees": float(crm_fees)})
    keys = ("estimate_total", "payments", "card_fees", "third_party", "total_payment", "crm_fees")
    totals = {key: float(sum((Decimal(str(item[key])) for item in items), Decimal(0))) for key in keys}
    return {"items": items, "totals": totals, "card_fee_percent": float(CARD_FEE_PERCENT), "crm_fee_percent": float(CRM_FEE_PERCENT)}
