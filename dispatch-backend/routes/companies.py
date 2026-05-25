from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Company, User, UserCompany

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/me")
def my_companies(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Returns only the companies this user is assigned to."""
    if user.role == "admin":
        companies = db.query(Company).order_by(Company.name).all()
    else:
        company_ids = [
            uc.company_id
            for uc in db.query(UserCompany).filter(UserCompany.user_id == user.id).all()
        ]
        companies = (
            db.query(Company)
            .filter(Company.id.in_(company_ids))
            .order_by(Company.name)
            .all()
        )
    return [c.to_dict() for c in companies]
