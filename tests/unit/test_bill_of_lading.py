"""The Bill of Lading: the company's form filled from the signed estimate, the terms from settings on the back,
and the customer's signature and date on both signature lines."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from bill_of_lading_pdf import build_bill_of_lading_pdf
from company_documents import bill_of_lading_body, clean_html, resolve_parameters
from models import Company
from test_public_moves import portal  # noqa: F401  (fixture)

COMPANY = {'name': 'Gorilla Haulers LLC', 'office_address': '19960 Wild Cherry Ln, Germantown, MD 20874', 'phone': '(301) 747-5811',
           'dot_number': '3467429'}
VALUES = {'mc_number': '1654219', 'order_number': '28288-1', 'pickup_date': '2026-10-31', 'first_available_delivery_date': '2026-12-31',
          'customer_name': 'Pat Customer', 'customer_phone': '2405550100', 'pickup_address': '1 Origin St, Clarksville, MD 21029',
          'delivery_address': '2 Destination Ave, San Antonio, TX 78253', 'total_estimate': '$5,561.79', 'minimum_cuft': '286 cu ft',
          'minimum_charge': '$1,875.00'}
SIGNATURE = {'name': 'Pat Customer', 'signed_at': '2026-11-06T15:00:00Z', 'date': '11/06/2026', 'strokes': [[[0.1, 0.5], [0.9, 0.6]]]}


def terms():
    company = Company(name='Gorilla Haulers LLC', phone='(301) 747-5811')
    body, missing = resolve_parameters(bill_of_lading_body(), company, html=True)
    assert missing == []
    return [{'title': 'Interstate Bill of Lading Contract', 'body_html': clean_html(body)}]


def pages(pdf):
    import pymupdf
    return [' '.join(page.get_text().split()) for page in pymupdf.open(stream=pdf, filetype='pdf')]


def test_front_is_the_form_filled_from_the_estimate():
    front, back = pages(build_bill_of_lading_pdf(COMPANY, VALUES, terms()))
    for value in ('INTERSTATE BILL OF LADING CONTRACT', 'Gorilla Haulers LLC', 'Phone Number: (301) 747-5811', 'USDOT No.: 3467429',
                  'ICC/MC No.: 1654219', 'Order No.: 28288-1', 'Pick Up Date: 2026-10-31', 'NAME: Pat Customer',
                  'ADDRESS: 1 Origin St', 'CITY/STATE/ZIP: Clarksville, MD 21029',
                  'TOTAL ESTIMATED CHARGES:', '$5,561.79', '286 cu ft', '$1,875.00', 'SUMMARY OF ACTUAL CHARGES', 'DELIVERY ACKNOWLEDGEMENT'):
        assert value in front, value
    # The destination is left empty.
    assert 'Destination Ave' not in front and 'San Antonio' not in front
    # The 1st date available for delivery is left empty.
    assert '2026-12-31' not in front
    # The back: the terms from settings, starting at SECTION 1.
    assert back.startswith('SECTION 1: Liability of Gorilla Haulers LLC') and 'SECTION 19' in back


def test_each_spot_is_signed_on_its_own():
    from bill_of_lading_pdf import SIGN_HERE

    def build(signatures=None):
        pdf = build_bill_of_lading_pdf(COMPANY, VALUES, terms(), signatures)
        # The spots left to sign, as the viewer finds them.
        return pages(pdf)[0], [spot for spot in (0, 1) if f'/Contents ({SIGN_HERE} {spot})'.encode() in pdf]
    unsigned, unsigned_spots = build()
    assert '11/06/2026' not in unsigned and unsigned_spots == [0, 1]
    # The top spot signed: its date is on, and only the next spot is left.
    first, first_spots = build({0: SIGNATURE})
    assert first.count('11/06/2026') == 1 and first_spots == [1]
    both, both_spots = build({0: SIGNATURE, 1: dict(SIGNATURE, date='11/07/2026')})
    assert '11/06/2026' in both and '11/07/2026' in both and both_spots == []


def test_signed_spots_are_of_the_version_shown_or_the_one_signed_in_full(portal):
    from datetime import datetime, timedelta
    from models import BillOfLadingSignature
    from types import SimpleNamespace
    mod, db, lead, access = portal
    start = datetime(2026, 11, 6, 15)
    estimate = SimpleNamespace(id='estimate-1', signed_at=start)

    def sign(spot, version, minutes):
        db.add(BillOfLadingSignature(lead_id=lead.id, job_id=access.job_id, estimate_signature_id='estimate-1', content_hash=version,
                                     spot=spot, pdf=b'%PDF', signer_name='Pat', signature='{}', signed_at=start + timedelta(minutes=minutes)))
        db.commit()
    # The top spot signed on an earlier version is signed again on the version shown now.
    sign(0, 'old', 0)
    assert mod._signed_spots(estimate, 'new', db) == {}
    assert set(mod._signed_spots(estimate, 'old', db)) == {0}
    sign(0, 'new', 1)
    assert set(mod._signed_spots(estimate, 'new', db)) == {0}
    # Signed in full: that version stays signed, whatever is shown now.
    sign(1, 'new', 2)
    assert set(mod._signed_spots(estimate, 'newer', db)) == {0, 1}
    # The estimate's signature removed and the same estimate signed again: the Bill of Lading is signed again too.
    estimate.signed_at = start + timedelta(minutes=10)
    assert mod._signed_spots(estimate, 'new', db) == {}


def test_address_goes_under_its_titles():
    from bill_of_lading_pdf import _split_address
    # A full address: the street, then the city, state and ZIP.
    assert _split_address('12 Main St, Rockville, MD 20852, USA') == ('12 Main St', 'Rockville, MD 20852')
    # Only a ZIP code or a city: no street, all on the city, state and ZIP line.
    assert _split_address('20852') == ('', '20852')
    assert _split_address('Rockville, MD 20852') == ('', 'Rockville, MD 20852')
