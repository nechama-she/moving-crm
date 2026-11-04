"""SmartMoving's sync changes only its own payments; CRM payments stay as entered."""
import ast
from decimal import Decimal
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import Base, Lead, LeadPayment


def sync_function():
    source = Path(__file__).resolve().parents[2] / 'backend/routes/leads.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                if isinstance(n, ast.FunctionDef) and n.name == '_sync_smartmoving_payments')
    scope = {'Lead': Lead, 'LeadPayment': LeadPayment, 'Decimal': Decimal}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    return scope['_sync_smartmoving_payments']


def test_sync_keeps_crm_payments_and_payouts():
    sync = sync_function()
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        lead = Lead(id='lead', full_name='Customer')
        lead.payments = [
            LeadPayment(id='sm-1', source='smartmoving', sort_order=0, amount=Decimal('100'), taken_by_user='rep', rep_paid=True),
            LeadPayment(id='crm', source='crm', sort_order=1, amount=Decimal('50'), taken_by_user='office'),
            LeadPayment(id='sm-2', source='smartmoving', sort_order=2, amount=Decimal('25'), taken_by_user='rep'),
        ]
        db.add(lead)
        db.commit()

        # SmartMoving now has one payment, changed.
        sync(lead, [{'amount': 120, 'takenByUser': 'rep'}])
        db.commit()
        db.expire_all()
        rows = {row.id: row for row in db.query(LeadPayment).all()}
        assert set(rows) == {'sm-1', 'crm'}
        assert rows['sm-1'].amount == Decimal('120') and rows['sm-1'].rep_paid is True
        assert rows['crm'].amount == Decimal('50') and rows['crm'].source == 'crm'

        # A new SmartMoving payment is added after the CRM one; SmartMoving with none removes only its own.
        sync(lead, [{'amount': 120, 'takenByUser': 'rep'}, {'amount': 30, 'takenByUser': 'rep'}])
        db.commit()
        assert [(row.source, float(row.amount)) for row in lead.payments] == [('smartmoving', 120), ('crm', 50), ('smartmoving', 30)]
        sync(lead, [])
        db.commit()
        assert [(row.id, row.source) for row in db.query(LeadPayment).all()] == [('crm', 'crm')]
    engine.dispose()
