import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Header, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user
from config import get_config
from database import get_db
from libs.smartmoving.client import update_opportunity_salesperson
from models import AutoAssignEvent, Company, Lead, User, UserCompany, AdminUnavailability, AdminUnavailabilityRep, RepAvailabilityWindow

logger = logging.getLogger("moving-crm")
DRY_RUN_BACKLOG_REASON = "dry_run_queued_backlog_round_robin"
QUEUE_REASONS_MANAGED_BY_BACKLOG = {
    "active_window_no_mapped_rep",
    "active_window_no_active_rep",
}

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


def _latest_assignment_event_by_lead(lead_ids: list[str], db: Session) -> dict[str, AutoAssignEvent]:
    if not lead_ids:
        return {}

    rows = (
        db.query(AutoAssignEvent)
        .filter(AutoAssignEvent.lead_id.in_(lead_ids))
        .order_by(AutoAssignEvent.lead_id.asc(), AutoAssignEvent.created_at.desc(), AutoAssignEvent.id.desc())
        .all()
    )

    latest_by_lead: dict[str, AutoAssignEvent] = {}
    for row in rows:
        if row.lead_id and row.lead_id not in latest_by_lead:
            latest_by_lead[row.lead_id] = row
    return latest_by_lead


def _queue_backlog_leads(
    leads: list[Lead],
    assignment_reason: str,
    note: str,
    latest_events_by_lead: dict[str, AutoAssignEvent],
    db: Session,
) -> int:
    queued_count = 0
    for lead in leads:
        latest_event = latest_events_by_lead.get(lead.id)
        if latest_event and latest_event.assignment_mode == "auto" and latest_event.assignment_reason == DRY_RUN_BACKLOG_REASON:
            logger.info(
                "Backlog lead queue skipped (already dry-run simulated): lead_id=%s company_id=%s",
                lead.id,
                lead.company_id,
            )
            continue
        if latest_event and latest_event.assignment_mode == "queued" and latest_event.assignment_reason == assignment_reason:
            logger.info(
                "Backlog lead queued (unchanged): lead_id=%s company_id=%s reason=%s",
                lead.id,
                lead.company_id,
                assignment_reason,
            )
            continue
        db.add(
            AutoAssignEvent(
                lead_id=lead.id,
                company_id=lead.company_id,
                assigned_to=None,
                assignment_mode="queued",
                assignment_reason=assignment_reason,
                note=note,
            )
        )
        logger.info(
            "Backlog lead queued: lead_id=%s company_id=%s reason=%s",
            lead.id,
            lead.company_id,
            assignment_reason,
        )
        queued_count += 1
    return queued_count


def _clear_stale_queued_events_for_window(active_window_start: datetime, db: Session) -> int:
    stale_ids = [
        row[0]
        for row in (
            db.query(AutoAssignEvent.id)
            .join(Lead, Lead.id == AutoAssignEvent.lead_id)
            .filter(
                AutoAssignEvent.assignment_mode == "queued",
                AutoAssignEvent.assignment_reason.in_(QUEUE_REASONS_MANAGED_BY_BACKLOG),
                Lead.assigned_to.is_(None),
                Lead.created_at < active_window_start,
            )
            .all()
        )
    ]
    if not stale_ids:
        return 0

    db.query(AutoAssignEvent).filter(AutoAssignEvent.id.in_(stale_ids)).delete(synchronize_session=False)
    return len(stale_ids)


def _clear_queued_events_for_leads(lead_ids: list[str], db: Session) -> int:
    if not lead_ids:
        return 0

    queued_ids = [
        row[0]
        for row in (
            db.query(AutoAssignEvent.id)
            .filter(
                AutoAssignEvent.lead_id.in_(lead_ids),
                AutoAssignEvent.assignment_mode == "queued",
                AutoAssignEvent.assignment_reason.in_(QUEUE_REASONS_MANAGED_BY_BACKLOG),
            )
            .all()
        )
    ]
    if not queued_ids:
        return 0

    db.query(AutoAssignEvent).filter(AutoAssignEvent.id.in_(queued_ids)).delete(synchronize_session=False)
    return len(queued_ids)


def _sync_assignment_to_smartmoving(lead: Lead, rep: User | None):
    if not rep:
        return
    if not lead.smartmoving_id:
        logger.info("Assignment sync skipped: lead %s has no smartmoving_id", lead.id)
        return
    if not rep.smartmoving_rep_id:
        logger.info("Assignment sync skipped: rep %s has no smartmoving_rep_id", rep.id)
        return
    result = update_opportunity_salesperson(lead.smartmoving_id, rep.smartmoving_rep_id)
    if not result.get("ok"):
        logger.error(
            "SmartMoving assignment sync failed: lead=%s opportunity=%s rep=%s error=%s",
            lead.id,
            lead.smartmoving_id,
            rep.id,
            result.get("error", "unknown"),
        )


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
            item["lead_created_at"] = lead.created_at.isoformat() if lead and lead.created_at else ""
            item["lead_url"] = f"/leads/{row.lead_id}" if row.lead_id else ""
            item["company_name"] = company_map.get(row.company_id, "")
            item["rep_name"] = rep_map.get(row.assigned_to, "") if row.assigned_to else ""
            items.append(item)

        queued_count = query.filter(AutoAssignEvent.assignment_mode == "queued").count()
        auto_count = query.filter(AutoAssignEvent.assignment_mode == "auto").count()

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
    logger.info("Backlog run started: dry_run=%s now=%s", dry_run, now.isoformat())
    if _any_admin_available_now(db, now=now):
        logger.info("Backlog run skipped: at least one admin is available now")
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
        logger.info("Backlog run skipped: no active admin unavailability window found")
        return {
            "ok": True,
            "message": "No active admin unavailability window found.",
            "dry_run": dry_run,
            "stats": {"queued_found": 0, "assigned": 0, "companies_touched": 0},
        }
    logger.info("Backlog active window start: %s", active_window_start.isoformat())

    cleared_stale_queued = _clear_stale_queued_events_for_window(active_window_start, db)
    if cleared_stale_queued:
        logger.info(
            "Backlog cleared stale queued events outside active window: %s",
            cleared_stale_queued,
        )

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
    logger.info("Backlog queued leads found in active window: %s", len(queued_leads))
    if not queued_leads:
        logger.info("Backlog run skipped: no unassigned leads found in active window")
        return {
            "ok": True,
            "message": "No unassigned leads found in active admin unavailability window.",
            "dry_run": dry_run,
            "stats": {"queued_found": 0, "assigned": 0, "companies_touched": 0},
        }

    latest_events_by_lead = _latest_assignment_event_by_lead([lead.id for lead in queued_leads], db)

    allowed_rep_ids = _active_available_rep_ids(db, now=now)
    logger.info("Backlog active reps mapped to current admin window: %s", len(allowed_rep_ids))
    if not allowed_rep_ids:
        queued_count = _queue_backlog_leads(
            queued_leads,
            assignment_reason="active_window_no_mapped_rep",
            note="Queued during active admin window because no reps are mapped to the current admin window",
            latest_events_by_lead=latest_events_by_lead,
            db=db,
        )
        db.commit()
        logger.info(
            "Backlog run skipped: no reps mapped as available in active admin windows; queued_events=%s",
            queued_count,
        )
        return {
            "ok": True,
            "message": "No reps mapped as available in active admin windows.",
            "dry_run": dry_run,
            "stats": {"queued_found": len(queued_leads), "assigned": 0, "queued_events": queued_count, "companies_touched": 0},
        }

    by_company: dict[str, list[Lead]] = {}
    for lead in queued_leads:
        by_company.setdefault(lead.company_id, []).append(lead)

    assigned_count = 0
    touched_companies = 0
    queued_count = 0

    for company_id, company_leads in by_company.items():
        active_reps = _active_reps_for_company(company_id, db, allowed_rep_ids=allowed_rep_ids, now=now)
        if not active_reps:
            logger.info(
                "Backlog company skipped: company_id=%s queued_leads=%s active_reps=0",
                company_id,
                len(company_leads),
            )
            queued_count += _queue_backlog_leads(
                company_leads,
                assignment_reason="active_window_no_active_rep",
                note="Queued during active admin window because no company rep is currently active",
                latest_events_by_lead=latest_events_by_lead,
                db=db,
            )
            continue

        cleared_for_company = _clear_queued_events_for_leads([lead.id for lead in company_leads], db)
        if cleared_for_company:
            logger.info(
                "Backlog cleared queued events for assignable company: company_id=%s cleared=%s",
                company_id,
                cleared_for_company,
            )

        touched_companies += 1
        logger.info(
            "Backlog company processing: company_id=%s queued_leads=%s active_reps=%s dry_run=%s",
            company_id,
            len(company_leads),
            len(active_reps),
            dry_run,
        )
        rep_ids = [r.id for r in active_reps]
        start_idx = _next_round_robin_start_index(company_id, rep_ids, db)

        for idx, lead in enumerate(company_leads):
            rep = active_reps[(start_idx + idx) % len(active_reps)]
            dry_run_reason = DRY_RUN_BACKLOG_REASON
            if dry_run:
                latest_event = latest_events_by_lead.get(lead.id)
                if (
                    latest_event
                    and latest_event.assignment_mode == "auto"
                    and latest_event.assignment_reason == dry_run_reason
                ):
                    logger.info(
                        "Backlog lead dry-run already recorded (unchanged): lead_id=%s rep_id=%s",
                        lead.id,
                        rep.id,
                    )
                    assigned_count += 1
                    continue
            logger.info(
                "Backlog lead assigned: lead_id=%s company_id=%s rep_id=%s dry_run=%s",
                lead.id,
                lead.company_id,
                rep.id,
                dry_run,
            )
            if not dry_run:
                lead.assigned_to = rep.id
                _sync_assignment_to_smartmoving(lead, rep)
            db.add(
                AutoAssignEvent(
                    lead_id=lead.id,
                    company_id=lead.company_id,
                    assigned_to=rep.id,
                    assignment_mode="auto",
                    assignment_reason=dry_run_reason if dry_run else "queued_backlog_round_robin",
                    note="DRY RUN: would assign from queued backlog" if dry_run else "Assigned from queued backlog by scheduler run",
                )
            )
            assigned_count += 1

    db.commit()

    logger.info(
        "Backlog run finished: dry_run=%s queued_found=%s assigned=%s queued_events=%s companies_touched=%s",
        dry_run,
        len(queued_leads),
        assigned_count,
        queued_count,
        touched_companies,
    )

    return {
        "ok": True,
        "message": "Dry-run backlog simulation completed." if dry_run else "Backlog assignment run completed.",
        "dry_run": dry_run,
        "stats": {
            "queued_found": len(queued_leads),
            "assigned": assigned_count,
            "queued_events": queued_count,
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
