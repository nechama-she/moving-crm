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
