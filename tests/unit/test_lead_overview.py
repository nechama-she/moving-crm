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
        assert {k: result[k] for k in ("new_today", "new_month", "quotes", "quote_value", "booked_value")} == dict(new_today=55, new_month=56, quotes=56, quote_value=5700, booked_value=2500)

        historical = overview(db.query(Lead).filter(Lead.company_id=='a'), db,
            datetime(2026,10,8,16,tzinfo=timezone.utc), month='2026-09')
        assert historical['new_month'] == 1
        assert historical['quotes'] == 0
        assert historical['booked_value'] == 0


def test_overview_adds_previous_period_and_daily_trend():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Company(id='a', name='A'))
        db.flush()
        rows = [
            ('t1', '2026-10-08T14:00:00Z', 1, 100), ('t2', '2026-10-08T15:00:00Z', 0, 0),
            ('d2', '2026-10-02T14:00:00Z', 1, 300),
            ('lw', '2026-10-01T14:00:00Z', 0, 0),          # same weekday last week
            ('p1', '2026-09-05T14:00:00Z', 1, 400),         # inside Sep 1-8
            ('p2', '2026-09-20T14:00:00Z', 1, 900),         # outside the comparison window
        ]
        for lead_id, created, priority, total in rows:
            db.add(Lead(id=lead_id, full_name='Lead', company_id='a', priority=priority,
                created_time=created, estimated_total=json.dumps({'finalTotal': total})))
        db.add(Lead(id='bk', full_name='Booked', company_id='a', status='booked', created_time='2026-08-01T14:00:00Z',
            estimated_total='{"finalTotal":2500}'))
        db.add(Lead(id='bp', full_name='Booked before', company_id='a', status='booked', created_time='2026-08-01T14:00:00Z',
            estimated_total='{"finalTotal":700}'))
        db.flush()
        db.add(LeadJob(lead_id='bk', job_order=1, booked_move_date=date(2026, 10, 3)))
        db.add(LeadJob(lead_id='bp', job_order=1, booked_move_date=date(2026, 9, 4)))
        db.commit()
        result = overview(db.query(Lead).filter(Lead.company_id == 'a'), db, datetime(2026, 10, 8, 16, tzinfo=timezone.utc))

        assert result['new_today'] == 2 and result['quotes'] == 2 and result['quote_value'] == 400
        assert result['previous'] == dict(new_today=1, new_month=1, quotes=1, quote_value=400, booked_value=700)
        assert len(result['trend']['new_leads']) == 8
        assert result['trend']['new_leads'] == [1, 1, 0, 0, 0, 0, 0, 2]
        assert result['trend']['quotes'] == [0, 1, 0, 0, 0, 0, 0, 1]
        assert result['trend']['quote_value'] == [0, 300, 0, 0, 0, 0, 0, 100]
        assert result['trend']['booked_value'] == [0, 0, 2500, 0, 0, 0, 0, 0]


def test_previous_period_handles_january_and_short_months():
    from lead_overview import previous_period
    assert previous_period(date(2026, 1, 1), date(2026, 1, 31)) == (date(2025, 12, 1), date(2025, 12, 31))
    assert previous_period(date(2026, 3, 1), date(2026, 3, 31)) == (date(2026, 2, 1), date(2026, 2, 28))
