"""The invoice: the estimate's prices and fees (no charge shows $0.00), each payment with its confirmation number, and the
balance due."""
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


def test_invoice_lists_prices_payments_and_balance():
    import pymupdf
    from invoice_pdf import build_invoice_pdf
    from test_estimate_pdf import sample
    data = sample()
    data['job_id'] = 'job'
    data['company_details']['dot_number'] = '3456789'
    data['elevator'] = {'terms': '$150.00 through 500 cu ft', 'locations': [{'location': 'pickup', 'uses_elevator': False}]}
    payments = [SimpleNamespace(paid_at=date(2026, 11, 2), method='Credit card', confirmation_number='K7Q3X9M2PA', amount=Decimal('1000')),
                SimpleNamespace(paid_at=None, method=None, confirmation_number=None, amount=Decimal('500'))]
    pdf = build_invoice_pdf(data, payments, '48213075526-1', date(2026, 11, 10))
    document = pymupdf.open(stream=pdf, filetype='pdf')
    text = ' '.join(' '.join(page.get_text().split()) for page in document)
    for expected in ('INVOICE 48213075526-1', 'USDOT: 3456789', 'BILLED TO Sample Customer', 'ORIGIN ADDRESS Rockville, MD',
                     'DESTINATION ADDRESS Phoenix, AZ', 'INVOICE DATE 11/10/2026', 'INVOICE AMOUNT $1,910.00',
                     'Transportation', 'TOTAL $1,910.00', 'Elevator - pickup', 'No elevator $0.00',
                     '11/02/2026 Credit card K7Q3X9M2PA $1,000.00', 'Not set Not set - $500.00',
                     'Total paid -$1,500.00', 'Balance due $410.00'):
        assert expected in text, expected
    assert 'No charge' not in text and 'TOTAL ESTIMATED PRICE' not in text and 'Estimated shipment volume' not in text
    if os.getenv('INVOICE_PREVIEW'):
        document[0].get_pixmap(dpi=90).save(os.environ['INVOICE_PREVIEW'])


def test_invoice_shows_the_signed_estimate_not_changes_since(monkeypatch):
    """With a signed estimate, the invoice is built from the signed copy: a fee added after signing is not on it."""
    import json
    import sys
    from datetime import datetime
    from pathlib import Path
    from types import SimpleNamespace
    sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'backend')]
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import invoice_pdf
    from models import Base, EstimateSignature, Lead, LeadJob
    import routes.public_moves as page
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    built = []
    monkeypatch.setattr(invoice_pdf, 'build_invoice_pdf', lambda data, payments, number, today: built.append(data) or b'%PDF')
    monkeypatch.setattr(page, '_estimate_document', lambda access, db: ({'estimate': {'price': '2200', 'charges': [{'name': 'Shuttle', 'total': 700}]}}, []))
    signed = {'name': 'Pat', 'estimate': {'price': '1800', 'charges': [{'name': 'Transportation charge', 'total': 1800}]}}
    with Session(engine) as db:
        db.add(Lead(id='lead', full_name='Pat'))
        db.flush()
        db.add(LeadJob(id='job', lead_id='lead', job_order=1))
        db.flush()
        access = SimpleNamespace(lead_id='lead', job_id='job')
        page.invoice_document(access, db)  # Nothing signed: the live prices.
        db.add(EstimateSignature(lead_id='lead', job_id='job', pdf=b'%PDF', signed_at=datetime(2026, 11, 1),
                                 snapshot=json.dumps({'data': signed, 'rows': []})))
        db.commit()
        page.invoice_document(access, db)
    assert built[0]['estimate']['price'] == '2200'
    assert built[1] == signed
    engine.dispose()
