"""Customer activity for the work queue: what happened on customer pages, as saved in customer_activity."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import require_admin
from customer_activity_log import activity_items
from database import get_db
from models import User

router = APIRouter(prefix="/api/customer-activity", tags=["Customer activity"])


@router.get("")
def list_customer_activity(days: int = Query(30, ge=1, le=365), _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Signatures, removed signatures and estimates changed after signing, newest first. Each stays listed."""
    return {'items': activity_items(db, since=datetime.utcnow() - timedelta(days=days))}
