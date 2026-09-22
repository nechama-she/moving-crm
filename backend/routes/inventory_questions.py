import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from auth import require_admin
from database import get_db
from models import Company, User, InventoryCatalogItem
from inventory_questions import QuestionRule, rules_for, revision
from manual_inventory import catalog
from routes.leads import _get_user_company_ids

router = APIRouter(prefix='/api/customer-questions', tags=['Customer questions'])

def company_for(company_id, user, db, lock=False):
    if company_id not in _get_user_company_ids(user, db): raise HTTPException(403, 'Company not available')
    query = db.query(Company).filter_by(id=company_id)
    company = (query.with_for_update() if lock else query).first()
    if not company: raise HTTPException(404, 'Company not found')
    return company

@router.get('/{company_id}')
def get_rules(company_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    rules = rules_for(company_for(company_id, user, db))
    return {'rules': rules, 'revision': revision(rules), 'catalog': catalog(db)['items']}

class RulesInput(BaseModel):
    revision: str
    rules: list[QuestionRule] = Field(max_length=100)

@router.put('/{company_id}')
def save_rules(company_id: str, body: RulesInput, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    company = company_for(company_id, user, db, True)
    if revision(rules_for(company)) != body.revision: raise HTTPException(409, 'Questions changed in another window. Reload before saving.')
    if len({rule.id for rule in body.rules}) != len(body.rules): raise HTTPException(400, 'Question IDs must be unique')
    ids = {i for rule in body.rules for i in rule.item_ids}
    found = {i[0] for i in db.query(InventoryCatalogItem.id).filter(InventoryCatalogItem.id.in_(ids)).all()} if ids else set()
    if ids != found: raise HTTPException(400, 'Some selected catalog items no longer exist')
    rules = [rule.model_dump() for rule in body.rules]
    company.customer_questions = json.dumps(rules)
    db.commit()
    return {'rules': rules, 'revision': revision(rules)}
