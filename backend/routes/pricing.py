"""Pricing book API backed by normalized Excel imports."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import (
    PricingPlan,
    PricingRate,
    PricingRule,
    PricingService,
    Lead,
    LeadJob,
    User,
    UserCompany,
)
from zip_state import delivery_location

router = APIRouter(prefix="/api/pricing", tags=["Pricing"])


def _accessible_query(db: Session, user: User):
    query = db.query(PricingPlan)
    if user.role == "admin":
        return query
    company_ids = [
        row[0]
        for row in db.query(UserCompany.company_id)
        .filter(UserCompany.user_id == user.id)
        .all()
    ]
    return query.filter(PricingPlan.company_id.in_(company_ids))


def _plan_or_404(db: Session, user: User, plan_id: str) -> PricingPlan:
    plan = _accessible_query(db, user).filter(PricingPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Pricing plan not found")
    return plan


class RuleInput(BaseModel):
    category: str = "general"
    title: str = "Pricing rule"
    description: str


class RateInput(BaseModel):
    destination: str
    destination_group: str = ""
    minimum_price: float | None = None
    minimum_text: str = ""
    band_label: str
    cubic_feet_min: int | None = None
    cubic_feet_max: int | None = None
    rate: float | None = None
    rate_text: str = ""


class ServiceInput(BaseModel):
    name: str
    rate_text: str = ""
    comments: str = ""


class PlanUpdate(BaseModel):
    name: str
    pickup_regions: str = ""
    fuel_percent: float | None = Field(default=None, ge=0, le=100)
    active: bool = True
    rules: list[RuleInput]
    rates: list[RateInput]
    services: list[ServiceInput]


class CalculationInput(BaseModel):
    destination: str
    cubic_feet: int = Field(ge=0)
    move_date: str = ""
    selected_charges: dict[str, bool] = Field(default_factory=dict)
    quantities: dict[str, float] = Field(default_factory=dict)
    manual_amounts: dict[str, float] = Field(default_factory=dict)


def _number(value: str) -> Decimal | None:
    match = re.search(r"\$?\s*(\d+(?:\.\d+)?)", value.replace(",", ""))
    return Decimal(match.group(1)) if match else None


def _parsed_move_date(value: str) -> date | None:
    try:
        return date.fromisoformat((value or "").strip()[:10])
    except ValueError:
        return None


def _seasonal_charge(plan: PricingPlan, move_date: date | None) -> dict | None:
    if not move_date:
        return None
    for rule in plan.rules:
        description = rule.description
        match = re.search(
            r"(?:after|of)\s+(Sep(?:tember)?|Oct(?:ober)?)\s+(\d{1,2})(?:st|nd|rd|th)?"
            r".*?(?:reduce|take)\s+\$?(\d+(?:\.\d+)?)\s*(?:off|per)?\s*(?:the\s+rate|per\s*cf|/cf)?",
            description,
            re.IGNORECASE,
        )
        if not match:
            continue
        month = 9 if match.group(1).lower().startswith("sep") else 10
        threshold = date(move_date.year, month, int(match.group(2)))
        applies = move_date >= threshold
        return {
            "id": f"seasonal:{rule.id}",
            "name": "Seasonal rate adjustment",
            "description": description,
            "calculation_type": "per_cf",
            "rate": -float(match.group(3)),
            "default_selected": applies,
            "automatic": True,
            "applies": applies,
            "quantity_label": "",
        }
    return None


def _service_charge(service: PricingService) -> dict:
    combined = f"{service.rate_text} {service.comments}".strip()
    lower = combined.lower()
    calc_type = "manual"
    rate = 0.0
    quantity_label = ""
    if "free" in lower:
        calc_type = "fixed"
    elif re.search(r"/\s*(?:cf|cu-?ft)", lower):
        parsed = _number(combined)
        if parsed is not None:
            calc_type = "per_cf_month" if "month" in lower else "per_cf"
            rate = float(parsed)
            quantity_label = "Months" if calc_type == "per_cf_month" else ""
    elif re.fullmatch(r"\s*\$?\s*\d+(?:\.\d+)?\s*", service.rate_text):
        calc_type = "fixed"
        rate = float(_number(service.rate_text) or 0)
    return {
        "id": f"service:{service.id}",
        "name": service.name,
        "description": " · ".join(value for value in (service.rate_text, service.comments) if value),
        "calculation_type": calc_type,
        "rate": rate,
        "default_selected": "all jobs" in service.name.lower(),
        "automatic": False,
        "applies": True,
        "quantity_label": quantity_label,
    }


def _rule_charges(rule: PricingRule) -> list[dict]:
    text = rule.description
    lower = text.lower()
    charges: list[dict] = []
    all_jobs = re.search(
        r"destination\s*&\s*origin\s*\(all jobs\)\s*\$?\s*(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if all_jobs:
        charges.append({
            "id": f"rule:{rule.id}:all-jobs",
            "name": "DESTINATION & ORIGIN (All Jobs)",
            "description": text,
            "calculation_type": "fixed",
            "rate": float(all_jobs.group(1)),
            "default_selected": True,
            "automatic": False,
            "applies": True,
            "quantity_label": "",
        })
    adjustment_pattern = re.compile(
        r"(add|take off|reduce).*?\$?(\d+(?:\.\d+)?)\s*(?:/|per\s+)(cf|mile)",
        re.IGNORECASE,
    )
    seasonal_text = ("after" in lower or "move dates of" in lower) and (
        "sep" in lower or "oct" in lower
    )
    for index, match in enumerate(adjustment_pattern.finditer(text)):
        if seasonal_text and match.group(1).lower() == "reduce":
            continue
        rate = float(match.group(2)) * (-1 if match.group(1).lower() != "add" else 1)
        unit = match.group(3).lower()
        charges.append({
            "id": f"rule:{rule.id}:adjustment:{index}",
            "name": "Cubic-foot adjustment" if unit == "cf" else "Mileage adjustment",
            "description": text,
            "calculation_type": "per_cf" if unit == "cf" else "per_unit",
            "rate": rate,
            "default_selected": False,
            "automatic": False,
            "applies": True,
            "quantity_label": "" if unit == "cf" else "Extra miles",
        })
    origin_fee = re.search(
        r"(?:add\s+(?:a\s+)?)\$?(\d+(?:\.\d+)?)\s+origin fee",
        text,
        re.IGNORECASE,
    )
    if origin_fee:
        charges.append({
            "id": f"rule:{rule.id}:origin",
            "name": "Origin fee",
            "description": text,
            "calculation_type": "fixed",
            "rate": float(origin_fee.group(1)),
            "default_selected": "all jobs" in lower,
            "automatic": False,
            "applies": True,
            "quantity_label": "",
        })
    if ("ask" in lower or "not included" in lower) and not charges:
        charges.append({
            "id": f"rule:{rule.id}:manual",
            "name": rule.title or "Manual pricing rule",
            "description": text,
            "calculation_type": "manual",
            "rate": 0.0,
            "default_selected": False,
            "automatic": False,
            "applies": True,
            "quantity_label": "Amount",
        })
    return charges


def _charge_amount(charge: dict, cubic_feet: int, quantity: float, manual: float) -> Decimal:
    rate = Decimal(str(charge["rate"]))
    kind = charge["calculation_type"]
    if kind == "fixed":
        return rate
    if kind == "per_cf":
        return rate * cubic_feet
    if kind == "per_cf_month":
        return rate * cubic_feet * Decimal(str(quantity or 1))
    if kind == "per_unit":
        return rate * Decimal(str(quantity or 0))
    return Decimal(str(manual or 0))


@router.get("")
def list_pricing_plans(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plans = (
        _accessible_query(db, user)
        .order_by(PricingPlan.company_name, PricingPlan.sort_order, PricingPlan.name)
        .all()
    )
    return [plan.summary_dict() for plan in plans]


@router.get("/context")
def get_job_pricing_context(
    lead_id: str,
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    job = (
        db.query(LeadJob)
        .filter(LeadJob.id == job_id, LeadJob.lead_id == lead_id)
        .first()
    )
    if not lead or not job:
        raise HTTPException(status_code=404, detail="Lead job not found")
    plans = (
        _accessible_query(db, user)
        .filter(PricingPlan.company_id == job.company_id, PricingPlan.active.is_(True))
        .order_by(PricingPlan.sort_order, PricingPlan.name)
        .all()
    )
    if not plans:
        raise HTTPException(status_code=404, detail="No pricing book is configured for this job company")
    pickup_state, pickup_zip_code = delivery_location(job.pickup_zip)
    delivery_state, delivery_zip_code = delivery_location(job.delivery_zip)

    def plan_matches_pickup(plan: PricingPlan) -> bool:
        if not pickup_state:
            return False
        coverage = f"{plan.pickup_regions} {plan.name}".upper()
        return re.search(rf"\b{re.escape(pickup_state)}\b", coverage) is not None

    recommended = next((plan for plan in plans if plan_matches_pickup(plan)), plans[0])
    return {
        "lead": {
            "id": lead.id,
            "full_name": lead.full_name,
            "volume": float(lead.volume) if lead.volume is not None else None,
            "weight": float(lead.weight) if lead.weight is not None else None,
        },
        "job": {
            **job.to_dict(),
            "pickup_state": pickup_state,
            "pickup_zip_code": pickup_zip_code,
            "delivery_state": delivery_state,
            "delivery_zip_code": delivery_zip_code,
        },
        "plans": [plan.summary_dict() for plan in plans],
        "recommended_plan_id": recommended.id,
    }


@router.post("/{plan_id}/calculate")
def calculate_pricing(
    plan_id: str,
    body: CalculationInput,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = _plan_or_404(db, user, plan_id)
    normalized = body.destination.strip().lower()
    candidates = [
        row
        for row in plan.rates
        if row.destination.strip().lower() == normalized
        and (row.cubic_feet_min is None or body.cubic_feet >= row.cubic_feet_min)
        and (row.cubic_feet_max is None or body.cubic_feet <= row.cubic_feet_max)
    ]
    matched = candidates[0] if candidates else None
    transport = (
        Decimal(body.cubic_feet) * matched.rate
        if matched and matched.rate is not None
        else None
    )
    minimum = matched.minimum_price if matched else None
    if transport is not None and minimum is not None:
        base = max(transport, minimum)
    else:
        base = transport if transport is not None else minimum

    charges: list[dict] = []
    if plan.fuel_percent is not None:
        charges.append({
            "id": "fuel",
            "name": "Fuel surcharge",
            "description": f"{float(plan.fuel_percent):g}% of transportation/minimum",
            "calculation_type": "percent",
            "rate": float(plan.fuel_percent),
            "default_selected": True,
            "automatic": False,
            "applies": True,
            "quantity_label": "",
        })
    seasonal = _seasonal_charge(plan, _parsed_move_date(body.move_date))
    if seasonal:
        charges.append(seasonal)
    charges.extend(_service_charge(service) for service in plan.services)
    charges.extend(charge for rule in plan.rules for charge in _rule_charges(rule))

    # The same all-jobs fee can appear in both the notes and additional services.
    # Keep the structured service entry and suppress repeated normalized descriptions.
    deduped: list[dict] = []
    seen = set()
    for charge in charges:
        identity = charge["name"]
        if identity.lower() in {"pricing rule", "exception", "manual pricing rule"}:
            identity = charge["description"]
        key = re.sub(r"[^a-z0-9]+", " ", identity.lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(charge)

    total = base or Decimal(0)
    calculated = []
    for charge in deduped:
        selected = body.selected_charges.get(
            charge["id"],
            bool(charge["default_selected"] and charge["applies"]),
        )
        if charge["automatic"] and not charge["applies"]:
            selected = False
        if charge["calculation_type"] == "percent":
            amount = (base or Decimal(0)) * Decimal(str(charge["rate"])) / Decimal(100)
        else:
            amount = _charge_amount(
                charge,
                body.cubic_feet,
                body.quantities.get(charge["id"], 1),
                body.manual_amounts.get(charge["id"], 0),
            )
        if selected:
            total += amount
        calculated.append({**charge, "selected": selected, "amount": float(amount)})

    return {
        "match": matched.to_dict() if matched else None,
        "transport": float(transport) if transport is not None else None,
        "minimum": float(minimum) if minimum is not None else None,
        "minimum_applied": bool(
            transport is not None and minimum is not None and minimum > transport
        ),
        "base_price": float(base) if base is not None else None,
        "charges": calculated,
        "total": float(total),
        "warning": "" if matched and matched.rate is not None else "No numeric transportation rate matched. Select another destination or enter manual pricing.",
    }


@router.get("/{plan_id}")
def get_pricing_plan(
    plan_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _plan_or_404(db, user, plan_id).to_dict()


@router.get("/{plan_id}/quote")
def lookup_pricing(
    plan_id: str,
    destination: str = Query(min_length=1),
    cubic_feet: int = Query(ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = _plan_or_404(db, user, plan_id)
    normalized = destination.strip().lower()
    candidates = [
        row
        for row in plan.rates
        if row.destination.strip().lower() == normalized
        and (row.cubic_feet_min is None or cubic_feet >= row.cubic_feet_min)
        and (row.cubic_feet_max is None or cubic_feet <= row.cubic_feet_max)
    ]
    rate = candidates[0] if candidates else None
    transport = (
        Decimal(cubic_feet) * rate.rate if rate and rate.rate is not None else None
    )
    minimum = rate.minimum_price if rate else None
    base = max(transport, minimum) if transport is not None and minimum is not None else transport or minimum
    fuel = (
        base * plan.fuel_percent / Decimal(100)
        if base is not None and plan.fuel_percent is not None
        else None
    )
    return {
        "match": rate.to_dict() if rate else None,
        "transport": float(transport) if transport is not None else None,
        "minimum_applied": bool(
            transport is not None and minimum is not None and minimum > transport
        ),
        "base_price": float(base) if base is not None else None,
        "fuel": float(fuel) if fuel is not None else None,
        "total_before_services": float(base + fuel) if base is not None and fuel is not None else (float(base) if base is not None else None),
        "warning": "" if rate and rate.rate is not None else "No numeric rate matched; review the rate instruction.",
    }


@router.put("/{plan_id}")
def update_pricing_plan(
    plan_id: str,
    body: PlanUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    plan = db.query(PricingPlan).filter(PricingPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Pricing plan not found")
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Plan name is required")
    if not body.rates:
        raise HTTPException(status_code=400, detail="At least one pricing rate is required")

    plan.name = body.name.strip()
    plan.pickup_regions = body.pickup_regions.strip()
    plan.fuel_percent = body.fuel_percent
    plan.active = body.active
    plan.rules.clear()
    plan.rates.clear()
    plan.services.clear()
    db.flush()
    plan.rules.extend(
        PricingRule(
            category=row.category.strip() or "general",
            title=row.title.strip() or "Pricing rule",
            description=row.description.strip(),
            sort_order=index,
        )
        for index, row in enumerate(body.rules)
        if row.description.strip()
    )
    plan.rates.extend(
        PricingRate(
            destination=row.destination.strip(),
            destination_group=row.destination_group.strip(),
            minimum_price=row.minimum_price,
            minimum_text=row.minimum_text.strip(),
            band_label=row.band_label.strip(),
            cubic_feet_min=row.cubic_feet_min,
            cubic_feet_max=row.cubic_feet_max,
            rate=row.rate,
            rate_text=row.rate_text.strip(),
            sort_order=index,
        )
        for index, row in enumerate(body.rates)
        if row.destination.strip() and row.band_label.strip()
    )
    plan.services.extend(
        PricingService(
            name=row.name.strip(),
            rate_text=row.rate_text.strip(),
            comments=row.comments.strip(),
            sort_order=index,
        )
        for index, row in enumerate(body.services)
        if row.name.strip()
    )
    db.commit()
    db.refresh(plan)
    return plan.to_dict()
