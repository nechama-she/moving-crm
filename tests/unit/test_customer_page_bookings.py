"""The customer page bookings report: leads signed on the customer page, their payments less 3.5% card fees and the
third-party payout, and Hallin's 15% of that."""
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


def test_report_lists_signed_leads_with_their_fees():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, EstimateSignature, Lead, LeadJob, LeadJobCharge, LeadPayment
    from routes.stats import customer_page_bookings
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Lead(id='signed', full_name='Gabrielle Taylor', third_party_payout_amount=100),
                    Lead(id='no-payments', full_name='Pat Mover'), Lead(id='not-signed', full_name='Not Signed')])
        db.flush()
        db.add_all([LeadJob(id=f'job-{lead}', lead_id=lead, job_order=1) for lead in ('signed', 'no-payments', 'not-signed')])
        db.flush()
        db.add_all([LeadJobCharge(job_id='job-signed', name='Transportation', total_cost=1801, subtotal=1801),
                    EstimateSignature(lead_id='signed', job_id='job-signed', snapshot='{}', pdf=b'%PDF', signed_at=datetime(2026, 11, 16)),
                    EstimateSignature(lead_id='no-payments', job_id='job-no-payments', snapshot='{}', pdf=b'%PDF', signed_at=datetime(2026, 11, 17)),
                    LeadPayment(lead_id='signed', source='crm', amount=540.30, sort_order=0),
                    LeadPayment(lead_id='signed', source='crm', amount=459.70, sort_order=1),
                    LeadPayment(lead_id='not-signed', source='crm', amount=999, sort_order=0)])
        db.commit()
        report = customer_page_bookings(None, db)
        assert [item['lead_id'] for item in report['items']] == ['no-payments', 'signed']  # Newest signature first.
        row = report['items'][1]
        # 1000 paid, 35 card fees, 100 third party: 865 total payment; 15% of it is 129.75.
        assert (row['estimate_total'], row['payments'], row['card_fees'], row['third_party'], row['total_payment'], row['crm_fees']) == \
            (1801.0, 1000.0, 35.0, 100.0, 865.0, 129.75)
        assert report['items'][0]['total_payment'] == 0 and report['items'][0]['crm_fees'] == 0
        assert report['totals']['crm_fees'] == 129.75 and report['totals']['total_payment'] == 865.0
    engine.dispose()
