from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, desc
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models import AccessAuditLog, User

router = APIRouter(prefix="/api", tags=["System"])


@router.get("/health")
def health():
    return {"status": "ok"}


def _apply_audit_filters(
    query,
    user_id: str = "",
    ip_address: str = "",
    path: str = "",
    method: str = "",
    status_filter: str = "",
    search: str = "",
    start_date: str = "",
    end_date: str = "",
):
    if user_id.strip():
        if user_id == "anonymous":
            query = query.filter(AccessAuditLog.user_id.is_(None))
        else:
            query = query.filter(AccessAuditLog.user_id == user_id.strip())

    if ip_address.strip():
        query = query.filter(AccessAuditLog.ip_address.ilike(f"%{ip_address.strip()}%"))

    if path.strip():
        query = query.filter(AccessAuditLog.path == path.strip())

    if method.strip():
        query = query.filter(AccessAuditLog.method == method.strip().upper())

    if status_filter.strip():
        sf = status_filter.strip().lower()
        if sf == "errors":
            query = query.filter(AccessAuditLog.status_code >= 400)
        elif sf == "client_errors":
            query = query.filter(AccessAuditLog.status_code >= 400, AccessAuditLog.status_code < 500)
        elif sf == "server_errors":
            query = query.filter(AccessAuditLog.status_code >= 500)
        elif sf.isdigit():
            query = query.filter(AccessAuditLog.status_code == int(sf))

    if search.strip():
        pattern = f"%{search.strip()}%"
        query = query.filter(
            (AccessAuditLog.path.ilike(pattern)) |
            (AccessAuditLog.user_name.ilike(pattern)) |
            (AccessAuditLog.user_email.ilike(pattern)) |
            (AccessAuditLog.ip_address.ilike(pattern)) |
            (AccessAuditLog.user_agent.ilike(pattern))
        )

    if start_date.strip():
        try:
            start_dt = datetime.fromisoformat(start_date.strip())
            query = query.filter(AccessAuditLog.created_at >= start_dt)
        except ValueError:
            pass

    if end_date.strip():
        try:
            end_dt = datetime.fromisoformat(end_date.strip())
            query = query.filter(AccessAuditLog.created_at <= end_dt)
        except ValueError:
            pass

    return query


@router.get("/system/access-logs")
def get_access_logs(
    user_id: str = Query(default=""),
    ip_address: str = Query(default=""),
    path: str = Query(default=""),
    status_filter: str = Query(default=""),  # "errors", "success", "401", "403", etc.
    method: str = Query(default=""),
    search: str = Query(default=""),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = _apply_audit_filters(
        db.query(AccessAuditLog),
        user_id=user_id,
        ip_address=ip_address,
        path=path,
        method=method,
        status_filter=status_filter,
        search=search,
        start_date=start_date,
        end_date=end_date,
    )

    total = query.count()
    items = (
        query.order_by(AccessAuditLog.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return {
        "items": [item.to_dict() for item in items],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/system/access-logs/grouped")
def get_access_logs_grouped(
    group_by: str = Query(default="user"),  # "user", "ip", "path", "status"
    user_id: str = Query(default=""),
    ip_address: str = Query(default=""),
    path: str = Query(default=""),
    method: str = Query(default=""),
    status_filter: str = Query(default=""),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
    search: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=500),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if group_by == "user":
        query = (
            db.query(
                AccessAuditLog.user_id,
                AccessAuditLog.user_name,
                AccessAuditLog.user_email,
                AccessAuditLog.user_role,
                func.count(AccessAuditLog.id).label("total_requests"),
                func.count(func.distinct(AccessAuditLog.ip_address)).label("distinct_ips"),
                func.sum(case((AccessAuditLog.status_code >= 400, 1), else_=0)).label("total_errors"),
                func.max(AccessAuditLog.created_at).label("last_active"),
                func.avg(AccessAuditLog.duration_ms).label("avg_duration_ms"),
            )
            .group_by(
                AccessAuditLog.user_id,
                AccessAuditLog.user_name,
                AccessAuditLog.user_email,
                AccessAuditLog.user_role,
            )
            .order_by(desc("total_requests"))
        )
        query = _apply_audit_filters(
            query,
            user_id=user_id,
            ip_address=ip_address,
            path=path,
            method=method,
            status_filter=status_filter,
            search=search,
            start_date=start_date,
            end_date=end_date,
        )
        rows = query.limit(limit).all()
        return {
            "group_by": "user",
            "results": [
                {
                    "user_id": r.user_id,
                    "user_name": r.user_name,
                    "user_email": r.user_email,
                    "user_role": r.user_role,
                    "total_requests": int(r.total_requests or 0),
                    "distinct_ips": int(r.distinct_ips or 0),
                    "total_errors": int(r.total_errors or 0),
                    "last_active": r.last_active.isoformat() if r.last_active else None,
                    "avg_duration_ms": round(float(r.avg_duration_ms or 0), 1),
                }
                for r in rows
            ],
        }

    elif group_by == "ip":
        query = (
            db.query(
                AccessAuditLog.ip_address,
                func.count(AccessAuditLog.id).label("total_requests"),
                func.count(func.distinct(AccessAuditLog.user_id)).label("distinct_users"),
                func.sum(case((AccessAuditLog.status_code >= 400, 1), else_=0)).label("total_errors"),
                func.max(AccessAuditLog.created_at).label("last_active"),
                func.max(AccessAuditLog.user_agent).label("sample_user_agent"),
            )
            .group_by(AccessAuditLog.ip_address)
            .order_by(desc("total_requests"))
        )
        query = _apply_audit_filters(
            query,
            user_id=user_id,
            ip_address=ip_address,
            path=path,
            method=method,
            status_filter=status_filter,
            search=search,
            start_date=start_date,
            end_date=end_date,
        )
        rows = query.limit(limit).all()
        return {
            "group_by": "ip",
            "results": [
                {
                    "ip_address": r.ip_address,
                    "total_requests": int(r.total_requests or 0),
                    "distinct_users": int(r.distinct_users or 0),
                    "total_errors": int(r.total_errors or 0),
                    "last_active": r.last_active.isoformat() if r.last_active else None,
                    "sample_user_agent": r.sample_user_agent or "",
                }
                for r in rows
            ],
        }

    elif group_by == "path":
        query = (
            db.query(
                AccessAuditLog.method,
                AccessAuditLog.path,
                func.count(AccessAuditLog.id).label("total_requests"),
                func.sum(case((AccessAuditLog.status_code >= 400, 1), else_=0)).label("total_errors"),
                func.avg(AccessAuditLog.duration_ms).label("avg_duration_ms"),
                func.max(AccessAuditLog.created_at).label("last_active"),
            )
            .group_by(AccessAuditLog.method, AccessAuditLog.path)
            .order_by(desc("total_requests"))
        )
        query = _apply_audit_filters(
            query,
            user_id=user_id,
            ip_address=ip_address,
            path=path,
            method=method,
            status_filter=status_filter,
            search=search,
            start_date=start_date,
            end_date=end_date,
        )
        rows = query.limit(limit).all()
        return {
            "group_by": "path",
            "results": [
                {
                    "method": r.method,
                    "path": r.path,
                    "total_requests": int(r.total_requests or 0),
                    "total_errors": int(r.total_errors or 0),
                    "avg_duration_ms": round(float(r.avg_duration_ms or 0), 1),
                    "last_active": r.last_active.isoformat() if r.last_active else None,
                }
                for r in rows
            ],
        }

    elif group_by == "status":
        query = (
            db.query(
                AccessAuditLog.status_code,
                func.count(AccessAuditLog.id).label("total_requests"),
                func.count(func.distinct(AccessAuditLog.user_id)).label("distinct_users"),
                func.count(func.distinct(AccessAuditLog.ip_address)).label("distinct_ips"),
                func.avg(AccessAuditLog.duration_ms).label("avg_duration_ms"),
                func.max(AccessAuditLog.created_at).label("last_active"),
            )
            .group_by(AccessAuditLog.status_code)
            .order_by(desc("total_requests"))
        )
        query = _apply_audit_filters(
            query,
            user_id=user_id,
            ip_address=ip_address,
            path=path,
            method=method,
            status_filter=status_filter,
            search=search,
            start_date=start_date,
            end_date=end_date,
        )
        rows = query.limit(limit).all()
        return {
            "group_by": "status",
            "results": [
                {
                    "status_code": r.status_code,
                    "total_requests": int(r.total_requests or 0),
                    "distinct_users": int(r.distinct_users or 0),
                    "distinct_ips": int(r.distinct_ips or 0),
                    "avg_duration_ms": round(float(r.avg_duration_ms or 0), 1),
                    "last_active": r.last_active.isoformat() if r.last_active else None,
                }
                for r in rows
            ],
        }

    else:
        return {"group_by": group_by, "results": []}
        # Default or fallback
        return {"group_by": group_by, "results": []}
