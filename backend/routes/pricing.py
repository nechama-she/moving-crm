"""Pricing book API backed by normalized Excel imports."""

from __future__ import annotations

from decimal import Decimal

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
    User,
    UserCompany,
)

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
