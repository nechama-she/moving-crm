"""Seed the normalized pricing tables from the approved Excel extraction."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from models import Company, PricingPlan, PricingRate, PricingRule, PricingService


def seed_pricing(db: Session) -> int:
    seed_path = Path(__file__).with_name("pricing_seed.json")
    if not seed_path.exists():
        return 0
    plans = json.loads(seed_path.read_text(encoding="utf-8"))
    companies = {row.name.strip().lower(): row for row in db.query(Company).all()}
    inserted = 0
    for payload in plans:
        source_key = payload["source_key"]
        if db.query(PricingPlan).filter(PricingPlan.source_key == source_key).first():
            continue
        company = companies.get(payload["company_name"].strip().lower())
        plan = PricingPlan(
            company_id=company.id if company else None,
            company_name=payload["company_name"],
            name=payload["name"],
            source_key=source_key,
            source_file=payload["source_file"],
            source_sheet=payload["source_sheet"],
            pickup_regions=payload.get("pickup_regions", ""),
            fuel_percent=payload.get("fuel_percent"),
            active=payload.get("active", True),
            sort_order=payload.get("sort_order", 0),
        )
        db.add(plan)
        db.flush()
        db.add_all(
            [
                PricingRule(plan_id=plan.id, **row)
                for row in payload.get("rules", [])
            ]
        )
        db.add_all(
            [
                PricingRate(plan_id=plan.id, **row)
                for row in payload.get("rates", [])
            ]
        )
        db.add_all(
            [
                PricingService(plan_id=plan.id, **row)
                for row in payload.get("services", [])
            ]
        )
        inserted += 1
    db.commit()
    return inserted
