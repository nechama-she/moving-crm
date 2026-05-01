import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Header, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user
from config import get_config
from database import get_db
from models import AutoAssignEvent, Company, Lead, User, UserCompany, AdminUnavailability, AdminUnavailabilityRep, RepAvailabilityWindow

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api", tags=["Assignment"])


def _get_user_company_ids(user: User, db: Session) -> list[str]:
    if user.role == "admin":
        return [row[0] for row in db.query(Company.id).all()]
    rows = db.query(UserCompany.company_id).filter(UserCompany.user_id == user.id).all()
    return [r[0] for r in rows]


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_admin_unavailable_now(admin_user_id: str, db: Session, now: datetime | None = None) -> bool:
    ts = now or _utcnow()
    return (
        db.query(AdminUnavailability)
        .filter(
            AdminUnavailability.admin_user_id == admin_user_id,
            AdminUnavailability.start_at <= ts,
            AdminUnavailability.end_at > ts,
        )
        .first()
        is not None
    )


def _any_admin_available_now(db: Session, now: datetime | None = None) -> bool:
    ts = now or _utcnow()
    admins = db.query(User).filter(User.role == "admin").all()
    if not admins:
        return False
    for admin in admins:
        if not _is_admin_unavailable_now(admin.id, db, ts):
            return True
    return False


def _active_available_rep_ids(db: Session, now: datetime | None = None) -> set[str]:
    ts = now or _utcnow()
    window_ids = [
        row[0]
        for row in (
            db.query(AdminUnavailability.id)
            .filter(AdminUnavailability.start_at <= ts, AdminUnavailability.end_at > ts)
            .all()
        )
    ]
    if not window_ids:
        return set()
    rep_rows = db.query(AdminUnavailabilityRep.rep_user_id).filter(AdminUnavailabilityRep.window_id.in_(window_ids)).all()
    return {r[0] for r in rep_rows if r[0]}


def _filter_by_rep_availability(rep_ids: list[str], db: Session, now: datetime | None = None) -> set[str]:
    if not rep_ids:
        return set()

    ts = now or _utcnow()
    configured_rows = (
        db.query(RepAvailabilityWindow.rep_user_id)
        .filter(RepAvailabilityWindow.rep_user_id.in_(rep_ids))
        .distinct()
        .all()
    )
    configured_rep_ids = {r[0] for r in configured_rows if r[0]}

    active_rows = (
        db.query(RepAvailabilityWindow.rep_user_id)
        .filter(
            RepAvailabilityWindow.rep_user_id.in_(rep_ids),
            RepAvailabilityWindow.start_at <= ts,
            RepAvailabilityWindow.end_at > ts,
        )
        .distinct()
        .all()
    )
    active_rep_ids = {r[0] for r in active_rows if r[0]}
    return {rid for rid in rep_ids if (rid not in configured_rep_ids or rid in active_rep_ids)}


def _active_reps_for_company(company_id: str, db: Session, allowed_rep_ids: set[str], now: datetime | None = None) -> list[User]:
    reps = (
        db.query(User)
        .join(UserCompany, UserCompany.user_id == User.id)
        .filter(User.role == "sales_rep", UserCompany.company_id == company_id)
        .order_by(User.name.asc())
        .all()
    )
    reps = [r for r in reps if r.id in allowed_rep_ids]
    active_ids = _filter_by_rep_availability([r.id for r in reps], db, now=now)
    return [r for r in reps if r.id in active_ids]


def _next_round_robin_start_index(company_id: str, rep_ids: list[str], db: Session) -> int:
    if not rep_ids:
        return 0
    last_event = (
        db.query(AutoAssignEvent)
        .filter(
            AutoAssignEvent.company_id == company_id,
            AutoAssignEvent.assignment_mode == "auto",
            AutoAssignEvent.assigned_to.in_(rep_ids),
        )
        .order_by(AutoAssignEvent.created_at.desc(), AutoAssignEvent.id.desc())
        .first()
    )
    if not last_event or not last_event.assigned_to:
        return 0
    try:
        last_idx = rep_ids.index(last_event.assigned_to)
    except ValueError:
        return 0
    return (last_idx + 1) % len(rep_ids)


def _send_assignment_webhook_todo(lead: Lead, rep: User | None):
    if not rep:
        return
    # TODO: Call external assignment webhook/API here to mirror CRM assignment downstream.
    logger.info("TODO assignment webhook (runner): lead=%s rep=%s(%s)", lead.id, rep.id, rep.name)


@router.get("/auto-assign-filters")
def get_auto_assign_filters(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company_ids = _get_user_company_ids(user, db)
    if not company_ids:
        return {"companies": [], "sales_reps": []}

    company_rows = db.query(Company).filter(Company.id.in_(company_ids)).order_by(Company.name.asc()).all()
    companies = [{"id": c.id, "name": c.name or ""} for c in company_rows]

    rep_rows = (
        db.query(User)
        .join(UserCompany, UserCompany.user_id == User.id)
        .filter(User.role == "sales_rep", UserCompany.company_id.in_(company_ids))
        .order_by(User.name.asc())
        .all()
    )
    seen = set()
    reps = []
    for rep in rep_rows:
        if rep.id in seen:
            continue
        seen.add(rep.id)
        reps.append({"id": rep.id, "name": rep.name or "", "email": rep.email or ""})

    return {"companies": companies, "sales_reps": reps}


@router.get("/auto-assign-events")
def get_auto_assign_events(
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    company_id: str = Query(default=""),
    rep_user_id: str = Query(default=""),
    assignment_mode: str = Query(default=""),
    start_at: str = Query(default=""),
    end_at: str = Query(default=""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company_ids = _get_user_company_ids(user, db)
    if not company_ids:
        return {"items": [], "total": 0, "has_more": False, "stats": {"total": 0, "queued": 0, "auto": 0}}

    try:
        query = db.query(AutoAssignEvent).filter(AutoAssignEvent.company_id.in_(company_ids))

        if company_id.strip() and company_id in company_ids:
            query = query.filter(AutoAssignEvent.company_id == company_id.strip())

        if rep_user_id.strip():
            query = query.filter(AutoAssignEvent.assigned_to == rep_user_id.strip())

        if assignment_mode.strip():
            query = query.filter(AutoAssignEvent.assignment_mode == assignment_mode.strip())

        if start_at.strip():
            try:
                parsed_start = _parse_iso_datetime(start_at.strip())
                query = query.filter(AutoAssignEvent.created_at >= parsed_start)
            except Exception:
                pass

        if end_at.strip():
            try:
                parsed_end = _parse_iso_datetime(end_at.strip())
                query = query.filter(AutoAssignEvent.created_at <= parsed_end)
            except Exception:
                pass

        total = query.count()
        rows = query.order_by(AutoAssignEvent.created_at.desc()).offset(offset).limit(limit).all()

        company_map = {c.id: c.name or "" for c in db.query(Company).filter(Company.id.in_(company_ids)).all()}
        rep_ids = list({r.assigned_to for r in rows if r.assigned_to})
        rep_map = {}
        if rep_ids:
            rep_map = {u.id: u.name or "" for u in db.query(User).filter(User.id.in_(rep_ids)).all()}

        lead_ids = [r.lead_id for r in rows if r.lead_id]
        lead_map = {}
        if lead_ids:
            lead_rows = db.query(Lead).filter(Lead.id.in_(lead_ids)).all()
            lead_map = {lead.id: lead for lead in lead_rows}

        items = []
        for row in rows:
            item = row.to_dict()
            lead = lead_map.get(row.lead_id)
            item["lead_name"] = lead.full_name if lead else ""
            item["lead_url"] = f"/leads/{row.lead_id}" if row.lead_id else ""
            item["company_name"] = company_map.get(row.company_id, "")
            item["rep_name"] = rep_map.get(row.assigned_to, "") if row.assigned_to else ""
            items.append(item)

        queued_count = db.query(AutoAssignEvent).filter(
            AutoAssignEvent.company_id.in_(company_ids),
            AutoAssignEvent.assignment_mode == "queued",
        ).count()
        auto_count = db.query(AutoAssignEvent).filter(
            AutoAssignEvent.company_id.in_(company_ids),
            AutoAssignEvent.assignment_mode == "auto",
        ).count()

        return {
            "items": items,
            "total": total,
            "has_more": offset + limit < total,
            "stats": {
                "total": total,
                "queued": queued_count,
                "auto": auto_count,
            },
        }
    except Exception as exc:
        logger.warning("Non-fatal auto assignment events read failure: %s", exc)
        return {"items": [], "total": 0, "has_more": False, "stats": {"total": 0, "queued": 0, "auto": 0}}


def _run_backlog_core(db: Session, dry_run: bool = False) -> dict:
    """Core backlog runner — callable internally (scheduler) or via HTTP endpoint."""
    now = _utcnow()
    if _any_admin_available_now(db, now=now):
        return {
            "ok": True,
            "message": "Admins are available; backlog auto-assignment skipped.",
            "dry_run": dry_run,
            "stats": {"queued_found": 0, "assigned": 0, "companies_touched": 0},
        }

    # Only process leads that arrived after the currently active admin-unavailability
    # window started. This prevents sweeping old historical unassigned leads.
    active_window_start = (
        db.query(func.min(AdminUnavailability.start_at))
        .filter(
            AdminUnavailability.start_at <= now,
            AdminUnavailability.end_at > now,
        )
        .scalar()
    )
    if not active_window_start:
        return {
            "ok": True,
            "message": "No active admin unavailability window found.",
            "dry_run": dry_run,
            "stats": {"queued_found": 0, "assigned": 0, "companies_touched": 0},
        }

    # Backlog scope is constrained to the active unavailability window.
    queued_leads = (
        db.query(Lead)
        .filter(
            Lead.assigned_to.is_(None),
            Lead.created_at >= active_window_start,
        )
        .order_by(Lead.created_at.asc())
        .all()
    )
    if not queued_leads:
        return {
            "ok": True,
            "message": "No unassigned leads found in active admin unavailability window.",
            "dry_run": dry_run,
            "stats": {"queued_found": 0, "assigned": 0, "companies_touched": 0},
        }

    allowed_rep_ids = _active_available_rep_ids(db, now=now)
    if not allowed_rep_ids:
        return {
            "ok": True,
            "message": "No reps mapped as available in active admin windows.",
            "dry_run": dry_run,
            "stats": {"queued_found": len(queued_leads), "assigned": 0, "companies_touched": 0},
        }

    by_company: dict[str, list[Lead]] = {}
    for lead in queued_leads:
        by_company.setdefault(lead.company_id, []).append(lead)

    assigned_count = 0
    touched_companies = 0

    for company_id, company_leads in by_company.items():
        active_reps = _active_reps_for_company(company_id, db, allowed_rep_ids=allowed_rep_ids, now=now)
        if not active_reps:
            continue

        touched_companies += 1
        rep_ids = [r.id for r in active_reps]
        start_idx = _next_round_robin_start_index(company_id, rep_ids, db)

        for idx, lead in enumerate(company_leads):
            rep = active_reps[(start_idx + idx) % len(active_reps)]
            if not dry_run:
                lead.assigned_to = rep.id
            db.add(
                AutoAssignEvent(
                    lead_id=lead.id,
                    company_id=lead.company_id,
                    assigned_to=rep.id,
                    assignment_mode="auto",
                    assignment_reason="dry_run_queued_backlog_round_robin" if dry_run else "queued_backlog_round_robin",
                    note="DRY RUN: would assign from queued backlog" if dry_run else "Assigned from queued backlog by scheduler run",
                )
            )
            if not dry_run:
                _send_assignment_webhook_todo(lead, rep)
            assigned_count += 1

    db.commit()

    return {
        "ok": True,
        "message": "Dry-run backlog simulation completed." if dry_run else "Backlog assignment run completed.",
        "dry_run": dry_run,
        "stats": {
            "queued_found": len(queued_leads),
            "assigned": assigned_count,
            "companies_touched": touched_companies,
            "window_start_at": active_window_start.isoformat() if active_window_start else "",
        },
    }


@router.post("/auto-assign-run")
def run_auto_assign_backlog(
    dry_run: bool = Query(default=True),
    x_api_secret: str = Header(...),
    db: Session = Depends(get_db),
):
    cfg = get_config()
    secret = cfg.get("API_SECRET", os.getenv("API_SECRET", ""))
    if not secret:
        raise HTTPException(status_code=500, detail="API secret not configured")
    if x_api_secret != secret:
        raise HTTPException(status_code=401, detail="Invalid API secret")

    return _run_backlog_core(db, dry_run=dry_run)
