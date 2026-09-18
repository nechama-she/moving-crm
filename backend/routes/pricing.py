"""Pricing book API backed by normalized Excel imports."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
import math
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import (
    LocalPricingRoute,
    PricingPlan,
    PricingRate,
    PricingRule,
    PricingService,
    Lead,
    LeadJob,
    LeadJobCharge,
    User,
    UserCompany,
)
from uuid import uuid4
from zip_state import delivery_location
from local_pricing import local_route_matches, match_region_from_address

router = APIRouter(prefix="/api/pricing", tags=["Pricing"])


def _plan_matches_pickup(plan: PricingPlan, pickup_state: str) -> bool:
    if not pickup_state:
        return False
    coverage = f"{plan.pickup_regions} {plan.name}".upper()
    return re.search(rf"\b{re.escape(pickup_state)}\b", coverage) is not None


def _plan_destination_for_delivery(
    plan: PricingPlan,
    delivery_address: str,
    delivery_state: str,
    delivery_zip: str,
) -> str:
    options = list({row.destination for row in plan.rates if row.destination})
    if not options:
        return ""
    destination = match_region_from_address(delivery_address, options, delivery_state or "", delivery_zip or "")
    if not destination and delivery_state:
        destination = next((option for option in options if delivery_state.lower() in option.lower()), "")
    if not destination and options:
        destination = options[0]
    return destination


def infer_job_move_type(
    lead: Lead,
    job: LeadJob,
    db: Session,
    plans: list[PricingPlan] | None = None,
) -> tuple[str | None, PricingPlan | None]:
    pickup_address = (job.pickup_zip or "").strip()
    delivery_address = (job.delivery_zip or "").strip()
    pickup_state, _ = delivery_location(pickup_address)
    delivery_state, _ = delivery_location(delivery_address)
    company_id = job.company_id or lead.company_id
    if not company_id:
        return None, None

    if plans is None and company_id:
        plans = (
            db.query(PricingPlan)
            .filter(PricingPlan.company_id == company_id, PricingPlan.active.is_(True))
            .order_by(PricingPlan.sort_order, PricingPlan.name)
            .all()
        )
    plans = [plan for plan in (plans or []) if plan.company_id == company_id]
    matched_plan = next((plan for plan in plans if _plan_matches_pickup(plan, pickup_state)), None) or (plans[0] if plans else None)

    routes = (
        db.query(LocalPricingRoute)
        .filter(LocalPricingRoute.company_id == company_id)
        .order_by(LocalPricingRoute.sort_order, LocalPricingRoute.created_at)
        .all()
    )
    for route in routes:
        if local_route_matches(pickup_address, delivery_address, route.pickup, route.delivery):
            return "Local", matched_plan

    if pickup_state and delivery_state:
        return "Long Distance", matched_plan
    return (getattr(lead, "move_type", None) or "").strip() or None, matched_plan


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
    bulky_items: list[str] = Field(default_factory=list)
    selected_charges: dict[str, bool] = Field(default_factory=dict)
    quantities: dict[str, float] = Field(default_factory=dict)
    manual_amounts: dict[str, float] = Field(default_factory=dict)

    @field_validator("cubic_feet", mode="before")
    @classmethod
    def round_up_cubic_feet(cls, value: object) -> int:
        if value is None or value == "":
            return 0
        parsed = float(value)
        if parsed < 0:
            return parsed
        return math.ceil(parsed)


def _rounded_cubic_feet(value: float | int | Decimal | None) -> int:
    if value is None:
        return 0
    return max(0, math.ceil(float(value)))


def _number(value: str) -> Decimal | None:
    match = re.search(r"\$?\s*(\d+(?:\.\d+)?)", value.replace(",", ""))
    return Decimal(match.group(1)) if match else None


def _parsed_move_date(value: str) -> date | None:
    try:
        return date.fromisoformat((value or "").strip()[:10])
    except ValueError:
        return None


BULKY_ITEM_MARKER = "__bulky_item__"
BULKY_ITEM_PREFIX = f"{BULKY_ITEM_MARKER}:"


def _normalize_item_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _is_bulky_service(service: PricingService) -> bool:
    return service.comments == BULKY_ITEM_MARKER or service.comments.startswith(BULKY_ITEM_PREFIX)


def _bulky_item_prices(service: PricingService) -> dict[str, str]:
    if service.comments.startswith(BULKY_ITEM_PREFIX):
        try:
            data = json.loads(service.comments[len(BULKY_ITEM_PREFIX):])
            if isinstance(data, dict):
                return {
                    "handling": str(data.get("handling") or service.rate_text or ""),
                    "packing": str(data.get("packing") or ""),
                    "crating": str(data.get("crating") or ""),
                }
        except (TypeError, ValueError):
            pass
    return {"handling": service.rate_text or "", "packing": "", "crating": ""}


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
    service_context = f"{service.name} {combined}".lower()
    calc_type = "manual"
    rate = 0.0
    quantity_label = ""
    free_months = 0
    if re.fullmatch(r"\s*free\s*", service.rate_text, re.IGNORECASE):
        calc_type = "fixed"
    elif re.search(r"/\s*(?:cf|cu-?ft)", lower):
        parsed = _number(combined)
        if parsed is not None:
            is_monthly = bool(re.search(r"\b(?:months?|mnths?)\b", service_context))
            calc_type = "per_cf_month" if is_monthly else "per_cf"
            rate = float(parsed)
            quantity_label = "Months" if calc_type == "per_cf_month" else ""
            if is_monthly and re.search(r"\b(?:1st|first)\s+month\s+free\b", service_context):
                free_months = 1
    elif re.fullmatch(r"\s*\$?\s*\d+(?:\.\d+)?\s*", service.rate_text):
        calc_type = "fixed"
        rate = float(_number(service.rate_text) or 0)
    minimum_amount = re.search(r"minimum\s*\$?\s*(\d+(?:\.\d+)?)", service.comments, re.IGNORECASE)
    minimum_cubic_feet = re.search(r"min(?:imum)?\s*(\d+(?:\.\d+)?)\s*(?:cf|cu-?ft)", service.comments, re.IGNORECASE)
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
        "free_months": free_months,
        "minimum_amount": float(minimum_amount.group(1)) if minimum_amount else 0,
        "minimum_cubic_feet": float(minimum_cubic_feet.group(1)) if minimum_cubic_feet else 0,
    }


def _packing_service_charges(
    services: list[PricingService],
    cubic_feet: int,
    quantities: dict[str, float],
) -> list[dict]:
    """Collapse imported rate tiers into simple job-level packing and storage choices."""
    packing_groups: dict[str, list[PricingService]] = {"full": [], "partial": []}
    remaining: list[PricingService] = []
    for service in services:
        if _is_bulky_service(service):
            continue
        match = re.match(r"\s*(full|partial)\s+packing\b", service.name, re.IGNORECASE)
        if match and re.search(r"(?:up\s+to|\d+\s*-\s*\d+|&\s*up)", service.name, re.IGNORECASE):
            packing_groups[match.group(1).lower()].append(service)
        else:
            remaining.append(service)

    storage_services = [
        service for service in remaining
        if re.match(r"\s*(?:long\s+term\s+)?storage\b", service.name, re.IGNORECASE)
    ]
    if len(storage_services) > 1:
        remaining = [service for service in remaining if service not in storage_services]

    charges = [_service_charge(service) for service in remaining]
    for packing_type, tiers in packing_groups.items():
        if not tiers:
            continue

        def tier_rank(service: PricingService) -> int:
            name = service.name.lower()
            if "up to" in name:
                return 0
            if re.search(r"\d+\s*-\s*\d+", name):
                return 1
            return 2

        desired_rank = 0 if cubic_feet <= 500 else 1 if cubic_feet <= 1000 else 2
        selected_tier = next(
            (service for service in tiers if tier_rank(service) == desired_rank),
            sorted(tiers, key=lambda service: abs(tier_rank(service) - desired_rank))[0],
        )
        charge = _service_charge(selected_tier)
        charge.update({
            "id": f"packing:{packing_type}",
            "name": f"{packing_type.title()} packing",
            "description": (
                f"{selected_tier.name} · {selected_tier.rate_text}"
                + (f" · {selected_tier.comments}" if selected_tier.comments else "")
            ),
            "quantity_label": "",
        })
        charges.append(charge)

    if len(storage_services) > 1:
        months = max(1, quantities.get("storage", 1))
        regular = next(
            (service for service in storage_services if not re.match(r"\s*long\s+term\b", service.name, re.IGNORECASE)),
            storage_services[0],
        )
        long_term_tiers: list[tuple[int, PricingService]] = []
        for service in storage_services:
            threshold = re.search(r"(\d+)\s*(?:months?|mnths?)", service.name, re.IGNORECASE)
            if threshold:
                long_term_tiers.append((int(threshold.group(1)), service))
        eligible = [tier for tier in long_term_tiers if months >= tier[0]]
        selected_storage = max(eligible, key=lambda tier: tier[0])[1] if eligible else regular
        charge = _service_charge(selected_storage)
        regular_charge = _service_charge(regular)
        charge.update({
            "id": "storage",
            "name": "Storage",
            "description": (
                f"{selected_storage.name} · {selected_storage.rate_text}"
                + (f" · {selected_storage.comments}" if selected_storage.comments else "")
            ),
            "calculation_type": "per_cf_month",
            "quantity_label": "Months",
            "free_months": regular_charge.get("free_months", 0),
            "minimum_amount": max(charge.get("minimum_amount", 0), regular_charge.get("minimum_amount", 0)),
            "minimum_cubic_feet": max(charge.get("minimum_cubic_feet", 0), regular_charge.get("minimum_cubic_feet", 0)),
        })
        charges.append(charge)
    return charges


def _bulky_item_charges(services: list[PricingService], item_names: list[str]) -> list[dict]:
    matched_counts: dict[str, int] = {}
    for name in item_names:
        normalized = _normalize_item_name(name)
        if normalized:
            matched_counts[normalized] = matched_counts.get(normalized, 0) + 1
    if not matched_counts:
        return []
    charges: list[dict] = []
    for service in services:
        if not _is_bulky_service(service):
            continue
        matched_count = matched_counts.get(_normalize_item_name(service.name), 0)
        if matched_count <= 0:
            continue
        prices = _bulky_item_prices(service)
        for key, label, default_selected, required in (
            ("handling", "Handling", True, True),
            ("packing", "Packing", False, False),
            ("crating", "Crating", False, False),
        ):
            parsed = _number(prices.get(key, ""))
            if parsed is None:
                continue
            charges.append({
                "id": f"bulky:{service.id}:{key}",
                "name": f"{service.name} {label}",
                "description": f"Bulky item matched from report · {matched_count:g} × {prices[key]}",
                "calculation_type": "fixed",
                "rate": float(parsed * matched_count),
                "default_selected": default_selected,
                "automatic": required,
                "required": required,
                "applies": True,
                "quantity_label": "",
            })
    return charges


def _material_item_names(materials: list[dict]) -> list[str]:
    names: list[str] = []
    for item in materials:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        try:
            quantity = max(1, int(float(item.get("quantity") or 1)))
        except (TypeError, ValueError):
            quantity = 1
        names.extend(str(item["name"]) for _ in range(quantity))
    return names


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
    billable_cubic_feet = max(
        Decimal(cubic_feet),
        Decimal(str(charge.get("minimum_cubic_feet", 0))),
    )
    minimum_amount = Decimal(str(charge.get("minimum_amount", 0)))
    if kind == "fixed":
        return rate
    if kind == "per_cf":
        return max(rate * billable_cubic_feet, minimum_amount)
    if kind == "per_cf_month":
        months = max(Decimal(0), Decimal(str(quantity)))
        billable_months = max(
            Decimal(0),
            months - Decimal(str(charge.get("free_months", 0))),
        )
        return max(rate * billable_cubic_feet * billable_months, minimum_amount if billable_months else Decimal(0))
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
    from routes.leads import _get_job_or_404
    job = _get_job_or_404(lead_id, job_id, user, db)
    lead = db.get(Lead, job.lead_id)
    plans = (
        _accessible_query(db, user)
        .filter(PricingPlan.company_id == job.company_id, PricingPlan.active.is_(True))
        .order_by(PricingPlan.sort_order, PricingPlan.name)
        .all()
    )
    pickup_state, pickup_zip_code = delivery_location(job.pickup_zip)
    delivery_state, delivery_zip_code = delivery_location(job.delivery_zip)

    inferred_move_type, recommended = infer_job_move_type(lead, job, db, plans)
    if not pickup_state:
        serviceability = "unknown_pickup"
    elif recommended is None:
        serviceability = "unsupported_pickup"
    else:
        serviceability = "supported"

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
        "recommended_plan_id": recommended.id if recommended else "",
        "serviceability": serviceability,
        "move_type": inferred_move_type,
    }


def compute_plan_calculation(plan: PricingPlan, body: CalculationInput) -> dict:
    cubic_feet = _rounded_cubic_feet(body.cubic_feet)
    normalized = body.destination.strip().lower()
    candidates = [
        row
        for row in plan.rates
        if row.destination.strip().lower() == normalized
        and (row.cubic_feet_min is None or cubic_feet >= row.cubic_feet_min)
        and (row.cubic_feet_max is None or cubic_feet <= row.cubic_feet_max)
    ]
    matched = candidates[0] if candidates else None
    transport = (
        Decimal(cubic_feet) * matched.rate
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
    charges.extend(_packing_service_charges(list(plan.services), cubic_feet, body.quantities))
    charges.extend(_bulky_item_charges(list(plan.services), body.bulky_items))
    charges.extend(charge for rule in plan.rules for charge in _rule_charges(rule))

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
        quantity = body.quantities.get(charge["id"], 1)
        selected = body.selected_charges.get(
            charge["id"],
            bool(charge["default_selected"] and charge["applies"]),
        )
        if charge.get("required"):
            selected = True
        if charge["automatic"] and not charge["applies"]:
            selected = False
        if charge["calculation_type"] == "percent":
            amount = (base or Decimal(0)) * Decimal(str(charge["rate"])) / Decimal(100)
        else:
            amount = _charge_amount(
                charge,
                cubic_feet,
                quantity,
                body.manual_amounts.get(charge["id"], 0),
            )
        if selected:
            total += amount
        description = charge["description"]
        breakdown = []
        if charge["calculation_type"] == "per_cf_month":
            months = max(0, quantity)
            billable_months = max(0, months - charge.get("free_months", 0))
            free_months = min(months, charge.get("free_months", 0))
            description = f"${charge['rate']:g} / CF"
            if free_months:
                breakdown.append({
                    "label": f"Storage · {free_months:g} free month{'s' if free_months != 1 else ''}",
                    "amount": 0,
                })
            if billable_months:
                breakdown.append({
                    "label": f"Storage · {billable_months:g} billable month{'s' if billable_months != 1 else ''}",
                    "amount": float(amount),
                })
        calculated.append({
            **charge,
            "description": description,
            "breakdown": breakdown,
            "selected": selected,
            "amount": float(amount),
        })

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


def calculate_and_save_lead_job_price(lead: Lead, job: LeadJob, db: Session) -> float | None:
    if not lead or not job:
        return None
    vol = _rounded_cubic_feet(lead.volume)
    if vol <= 0:
        return None

    company_id = job.company_id or lead.company_id
    if not company_id:
        from models import Company
        default_co = db.query(Company).filter(Company.is_default_company.is_(True)).first()
        if default_co:
            company_id = default_co.id
            if not job.company_id:
                job.company_id = default_co.id
    if not company_id:
        return None

    pickup_addr = (job.pickup_zip or "").strip()
    delivery_addr = (job.delivery_zip or "").strip()

    pickup_state, pickup_zip = delivery_location(pickup_addr)
    delivery_state, delivery_zip = delivery_location(delivery_addr)

    plans = (
        db.query(PricingPlan)
        .filter(PricingPlan.company_id == company_id, PricingPlan.active.is_(True))
        .order_by(PricingPlan.sort_order, PricingPlan.name)
        .all()
    )
    if not plans:
        return None

    move_type, matched_plan = infer_job_move_type(lead, job, db, plans)
    if move_type:
        lead.move_type = move_type
    if not move_type or not matched_plan:
        return None

    if move_type.lower() == "local":
        from routes.local_pricing import calculate_book_price
        from local_pricing import LocalCalculation
        quote = calculate_book_price(matched_plan, LocalCalculation(cubic_feet=Decimal(vol)),
                                     db, pickup_addr, delivery_addr)
        total = quote.get("total")
        if total is None or total <= 0:
            return None

        db.query(LeadJobCharge).filter_by(job_id=job.id).delete()
        for idx, line in enumerate(quote.get("charges", [])):
            if line.get("totalCost", 0) > 0:
                db.add(LeadJobCharge(
                    id=str(uuid4()),
                    job_id=job.id,
                    name=line["name"],
                    description=line.get("description", ""),
                    sort_order=idx,
                    subtotal=line["subtotal"],
                    discount_amount=line.get("discountAmount", Decimal(0)),
                    total_cost=line["totalCost"],
                ))
        job.price = total
        from routes.leads import _refresh_lead_estimated_total
        _refresh_lead_estimated_total(lead.id, db)
        return float(total)

    else:
        destination = _plan_destination_for_delivery(matched_plan, delivery_addr, delivery_state or "", delivery_zip or "")
        if not destination:
            return None

        calc_body = CalculationInput(
            destination=destination,
            cubic_feet=vol,
            move_date=job.move_date or "",
            bulky_items=_material_item_names(job._estimated_materials_data()),
        )
        quote = compute_plan_calculation(matched_plan, calc_body)
        total = quote.get("total", 0.0)
        if total <= 0:
            return None

        lines = []
        if quote.get("base_price", 0) > 0:
            lines.append({
                "name": "Transportation charge",
                "description": f"{vol} cf · {quote.get('match', {}).get('band_label', 'Transportation')}",
                "subtotal": Decimal(str(quote["base_price"])),
                "discount_amount": Decimal(0),
                "total_cost": Decimal(str(quote["base_price"])),
            })
        for c in quote.get("charges", []):
            if c.get("selected") and c.get("amount", 0) > 0:
                amt = Decimal(str(c["amount"]))
                lines.append({
                    "name": c["name"],
                    "description": c.get("description", ""),
                    "subtotal": amt,
                    "discount_amount": Decimal(0),
                    "total_cost": amt,
                })
        if not lines:
            return None

        db.query(LeadJobCharge).filter_by(job_id=job.id).delete()
        for idx, line in enumerate(lines):
            db.add(LeadJobCharge(
                id=str(uuid4()),
                job_id=job.id,
                name=line["name"],
                description=line["description"],
                sort_order=idx,
                subtotal=line["subtotal"],
                discount_amount=line["discount_amount"],
                total_cost=line["total_cost"],
            ))
        job.price = sum(l["total_cost"] for l in lines)
        from routes.leads import _refresh_lead_estimated_total
        _refresh_lead_estimated_total(lead.id, db)
        return float(job.price)


@router.post("/{plan_id}/calculate")
def calculate_pricing(
    plan_id: str,
    body: CalculationInput,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = _plan_or_404(db, user, plan_id)
    return compute_plan_calculation(plan, body)


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
    cubic_feet: float = Query(ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = _plan_or_404(db, user, plan_id)
    rounded_cubic_feet = _rounded_cubic_feet(cubic_feet)
    normalized = destination.strip().lower()
    candidates = [
        row
        for row in plan.rates
        if row.destination.strip().lower() == normalized
        and (row.cubic_feet_min is None or rounded_cubic_feet >= row.cubic_feet_min)
        and (row.cubic_feet_max is None or rounded_cubic_feet <= row.cubic_feet_max)
    ]
    rate = candidates[0] if candidates else None
    transport = (
        Decimal(rounded_cubic_feet) * rate.rate if rate and rate.rate is not None else None
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
