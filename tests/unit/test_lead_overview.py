import sys
from pathlib import Path
from datetime import datetime, date, timezone
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import Base, Company, Lead, LeadJob
from lead_overview import overview


def test_overview_counts_full_scope_and_eastern_dates_without_duplicate_jobs():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Company(id='a', name='A'), Company(id='b', name='B')])
        db.flush()
        for i in range(55):
            db.add(Lead(id=str(i), full_name='Lead', company_id='a', priority=1,
                created_time='2026-10-08T14:00:00Z', estimated_total=json.dumps({'finalTotal':100})))
        db.add(Lead(id='hidden', full_name='Hidden', company_id='b', priority=1,
            created_time='2026-10-08T14:00:00Z', estimated_total='{"finalTotal":99999}'))
        db.add(Lead(id='booked', full_name='Booked', company_id='a', status='booked',
            created_time='2026-09-01T14:00:00Z', estimated_total='{"finalTotal":2500}'))
        db.add(Lead(id='yesterday', full_name='Yesterday', company_id='a', priority=1,
            created_time='2026-10-08T02:00:00Z', estimated_total='{"finalTotal":200}'))
        db.flush()
        db.add_all([LeadJob(lead_id='booked', job_order=n, booked_move_date=date(2026,10,7)) for n in [1,2]])
        db.commit()
        result = overview(db.query(Lead).filter(Lead.company_id=='a'), db,
            datetime(2026,10,8,16,tzinfo=timezone.utc))
        assert result == dict(new_today=55, quotes=56, quote_value=5700, booked_value=2500)
