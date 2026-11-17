"""The lead's total is added up from its jobs whenever it is read: each job's lines, or its saved price when it has no
lines. Only the tax comes from the saved total."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


def test_total_is_the_jobs_lines_not_the_saved_copy():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, Lead, LeadJob, LeadJobCharge
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        stale = json.dumps({'subtotal': 3494.33, 'taxableAmount': 0, 'tax': 10, 'finalTotal': 3390.83})
        db.add_all([Lead(id='lines', full_name='A', estimated_total=stale),
                    Lead(id='saved-only', full_name='B', estimated_total=json.dumps({'subtotal': 500, 'taxableAmount': 0, 'tax': 0, 'finalTotal': 500})),
                    Lead(id='nothing', full_name='C')])
        db.flush()
        db.add_all([LeadJob(id='priced', lead_id='lines', job_order=1, price=3390.83),
                    LeadJob(id='no-lines', lead_id='lines', job_order=2, price=100),
                    LeadJob(id='empty', lead_id='saved-only', job_order=1)])
        db.flush()
        db.add_all([LeadJobCharge(job_id='priced', name='Transportation charge', total_cost=1855, subtotal=2252.5, discount_amount=397.5),
                    LeadJobCharge(job_id='priced', name='Fees', total_cost=1241.83, subtotal=1241.83)])
        db.commit()
        # 3096.83 of lines, 100 for the job without lines, and the saved tax.
        assert db.get(Lead, 'lines').estimated_total_data() == {'subtotal': 3594.33, 'taxableAmount': 0.0, 'tax': 10.0, 'finalTotal': 3206.83}
        assert db.get(Lead, 'saved-only').estimated_total_data()['finalTotal'] == 500
        assert db.get(Lead, 'nothing').estimated_total_data() is None
    engine.dispose()
