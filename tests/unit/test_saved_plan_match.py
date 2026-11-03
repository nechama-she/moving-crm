import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
import models
import routes.pricing as pricing


def test_plan_match_is_saved_and_redone_only_when_its_inputs_change(monkeypatch):
    engine = create_engine('sqlite://')
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(models.Company(id='co', name='Co'))
        plan = models.PricingPlan(id='east', source_key='east', company_id='co', company_name='Co', name='East',
                                  source_file='', source_sheet='', active=True, updated_at=datetime(2026, 11, 1, tzinfo=timezone.utc))
        lead = models.Lead(id='lead', full_name='Customer', company_id='co')
        job = models.LeadJob(id='job', lead_id='lead', company_id='co', pickup_zip='20850', delivery_zip='30301')
        db.add_all([plan, lead, job])
        db.commit()
        matches = []
        monkeypatch.setattr(pricing, '_match_job_move_type', lambda lead, job, db, plans=None: matches.append(1) or ('Long Distance', plan))

        assert pricing.infer_job_move_type(lead, job, db) == ('Long Distance', plan)
        assert pricing.infer_job_move_type(lead, job, db) == ('Long Distance', plan)
        assert len(matches) == 1 and job.pricing_plan_id == 'east'

        # The minimum is worked out once, then read from the job until the match changes.
        lookups = []
        monkeypatch.setattr(pricing, '_service_billable_volume', lambda plan, destination, cuft: lookups.append(1) or 286)
        monkeypatch.setattr(pricing, '_plan_destination_for_delivery', lambda *args: 'GA')
        assert pricing.customer_minimum_volume(lead, job, db) == 286
        assert pricing.customer_minimum_volume(lead, job, db) == 286
        assert len(lookups) == 1 and job.minimum_cuft == 286

        job.delivery_zip = '10001'
        pricing.infer_job_move_type(lead, job, db)
        assert len(matches) == 2 and job.minimum_cuft is None

        plan.updated_at = plan.updated_at + timedelta(minutes=1)
        db.commit()
        pricing.infer_job_move_type(lead, job, db)
        assert len(matches) == 3

        db.add(models.LocalPricingRoute(company_id='co', pickup='MD', delivery='VA'))
        db.commit()
        pricing.infer_job_move_type(lead, job, db)
        pricing.infer_job_move_type(lead, job, db)
        assert len(matches) == 4
    engine.dispose()
