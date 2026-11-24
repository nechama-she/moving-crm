"""The Bill of Lading's first page as each company sets it: drawn from its blocks, loaded with its document in one
query, started as the form drawn until now, saved with its checks, and filled once from a mover's PDF."""
import asyncio
import os
import sys
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')

COMPANY = {'name': 'Gorilla Haulers', 'office_address': '19960 Wild Cherry Ln, Germantown, MD 20874', 'phone': '202-937-2625'}
VALUES = {'customer_name': 'Dana Customer', 'pickup_address': '20540 Frederick Road, Germantown, Maryland 20876',
          'delivery_address': '5 Main St, Austin, TX 78701', 'order_number': '1-1', 'total_estimate': '$1,000.00'}


def text(pdf):
    from pypdf import PdfReader
    return ' '.join(PdfReader(BytesIO(pdf)).pages[0].extract_text().split())


def build(blocks, signatures=None):
    from bill_of_lading_pdf import build_bill_of_lading_pdf
    return build_bill_of_lading_pdf(COMPANY, VALUES, [{'title': 'Terms', 'body_html': '<p>Terms.</p>', 'blocks': blocks}], signatures)


def test_a_changed_block_changes_the_page():
    from bill_of_lading_form import DEFAULT_BLOCKS
    blocks = [dict(row) for row in DEFAULT_BLOCKS]
    payment = next(row for row in blocks if row['kind'] == 'paragraph')
    payment['text'] = '<b>A. FORM / TERMS OF PAYMENT:</b> A 15% deposit is due at booking to {{company_name}}.'
    destination = [row for row in blocks if row['area'] == 'destination' and row['kind'] == 'field']
    destination[1]['fill'] = 'delivery_street'
    page = text(build(blocks))
    assert 'A 15% deposit is due at booking to Gorilla Haulers.' in page and '5 Main St' in page
    assert 'up to 50% deposit' not in page


def test_the_customers_two_spots_are_the_forms_signature_lines():
    from pypdf import PdfReader
    from bill_of_lading_form import DEFAULT_BLOCKS
    links = lambda pdf: sorted(annotation.get_object()['/Contents'] for annotation in PdfReader(BytesIO(pdf)).pages[0].get('/Annots', [])
                               if annotation.get_object().get('/Subtype') == '/Link')
    assert links(build(DEFAULT_BLOCKS)) == ['sign-here 0', 'sign-here 1']
    signature = {'name': 'Dana', 'date': '11/24/2026', 'strokes': [[[0, 0], [1, 1]]]}
    assert links(build(DEFAULT_BLOCKS, {0: signature})) == ['sign-here 1']


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, Company, CompanyDocument, Lead, LeadJob
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Company(id='c', name='Top Tier Van Lines'))
        session.flush()
        session.add_all([CompanyDocument(company_id='c', key='bol', title='Bill of Lading', body_html='<p>Terms</p>', used_in='bill_of_lading', revision=1),
                         CompanyDocument(company_id='c', key='estimate', title='Estimate', body_html='', used_in='estimate', revision=1)])
        session.add(Lead(id='lead', full_name='Dana', company_id='c', move_type='Long Distance'))
        session.flush()
        session.add(LeadJob(id='job', lead_id='lead', job_order=1, company_id='c'))
        session.commit()
        from company_documents import seed_bill_of_lading_forms
        assert seed_bill_of_lading_forms(session.connection()) == 1
        session.commit()
        yield session
    engine.dispose()


def test_every_bill_of_lading_starts_with_the_form_drawn_until_now(db):
    from bill_of_lading_form import DEFAULT_DIGEST, form_digest
    from company_documents import form_payload, seed_bill_of_lading_forms
    from models import BillOfLadingBlock, CompanyDocument
    blocks = db.get(CompanyDocument, ('c', 'bol')).blocks
    # Read back from the database, it is the same form: Bills of Lading signed before keep their version.
    assert form_digest(form_payload(blocks)) == DEFAULT_DIGEST
    assert db.query(BillOfLadingBlock).filter_by(document_key='estimate').count() == 0
    assert seed_bill_of_lading_forms(db.connection()) == 0  # Once.


def test_the_form_comes_in_the_documents_query(db):
    from sqlalchemy import event
    from company_documents import documents_for
    from models import Lead, LeadJob
    lead, job = db.get(Lead, 'lead'), db.get(LeadJob, 'job')
    db.expire_all()
    lead, job = db.get(Lead, 'lead'), db.get(LeadJob, 'job')
    lead.move_type, job.company_id
    statements = []
    listener = lambda conn, cursor, statement, *args: statements.append(statement)
    event.listen(db.get_bind(), 'before_cursor_execute', listener)
    try:
        documents = documents_for(lead, job, db, 'bill_of_lading')
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', listener)
    assert len(documents) == 1 and len(documents[0]['blocks']) > 50
    assert len(statements) == 2  # The company, then the documents with their blocks joined.


def save(db, blocks, revision=1):
    from routes.companies import FormInput, save_bill_of_lading_form
    return save_bill_of_lading_form('c', 'bol', FormInput(revision=revision, blocks=blocks), None, db)


def test_saving_the_form_makes_a_new_version(db):
    from bill_of_lading_form import DEFAULT_BLOCKS
    blocks = [dict(row) for row in DEFAULT_BLOCKS]
    next(row for row in blocks if row['title'] == 'Vehicle ID:')['title'] = 'Truck No.:'
    result = save(db, blocks)
    assert result['revision'] == 2 and [row['title'] for row in result['blocks'] if row['area'] == 'order'][-1] == 'Truck No.:'


@pytest.mark.parametrize('change', [
    lambda blocks: [row for row in blocks if row['spot'] != 2],                       # The customer signs two spots.
    lambda blocks: blocks + [dict(next(row for row in blocks if row['kind'] == 'field'), area='left')],   # A box does not go in a column.
    lambda blocks: [dict(row, fill='anything') if row['kind'] == 'field' else row for row in blocks],    # Only move details fill a box.
    lambda blocks: blocks + [{**blocks[0], 'area': 'left', 'kind': 'paragraph', 'text': '<b>Unclosed'}],  # Formatting that can be read.
    lambda blocks: blocks + [dict(next(row for row in blocks if row['area'] == 'order'))],                # Four order boxes fit.
])
def test_a_form_that_cannot_be_drawn_is_not_saved(db, change):
    from bill_of_lading_form import DEFAULT_BLOCKS
    with pytest.raises(HTTPException) as error:
        save(db, change([dict(row) for row in DEFAULT_BLOCKS]))
    assert error.value.status_code == 422


def mover_pdf(scanned=False):
    """A mover's two-page form: its lettered paragraphs on the front, its SECTION terms on the back."""
    from reportlab.pdfgen.canvas import Canvas
    output = BytesIO()
    canvas = Canvas(output, pagesize=(612, 792))
    if not scanned:
        lines = ['A. FORM / TERMS OF PAYMENT:', 'Upon booking a 15% deposit is required. Top Tier Van Lines reserves the',
                 'right to collect up to 70% of balance due.', "Customer's signature", 'E. NOTICE OF AGREED PICK UP AND DELIVERY PERIODS:',
                 'Guaranteed pickup and delivery dates are optional.']
        for index, line in enumerate(lines):
            canvas.drawString(40, 740 - index * 14, line)
    canvas.showPage()
    if not scanned:
        canvas.drawString(40, 740, 'SECTION 1: Liability of Top Tier Van Lines is limited.')
        canvas.drawString(40, 726, 'SECTION 2: Form of Payment: cash only.')
    canvas.showPage()
    canvas.save()
    return output.getvalue()


def test_reading_a_movers_pdf_fills_the_wording_once(db):
    from bill_of_lading_form import DEFAULT_BLOCKS, read_upload
    blocks, terms, unmatched = read_upload(mover_pdf(), 'Top Tier Van Lines', DEFAULT_BLOCKS)
    payment = next(row for row in blocks if row['kind'] == 'paragraph')
    assert payment['text'] == ('<b>A. FORM / TERMS OF PAYMENT:</b> Upon booking a 15% deposit is required. {{company_name}} '
                               'reserves the right to collect up to 70% of balance due.')
    assert terms == ('<p><strong>SECTION 1:</strong> Liability of {{company_name}} is limited.</p>'
                     '<p><strong>SECTION 2:</strong> Form of Payment: cash only.</p>')
    assert unmatched == ['E. NOTICE OF AGREED PICK UP AND DELIVERY PERIODS:']
    # Only the wording changed: the same parts, in the same places.
    assert [(row['area'], row['kind']) for row in blocks] == [(row['area'], row['kind']) for row in DEFAULT_BLOCKS]


def test_a_scanned_pdf_has_no_wording_to_read(db):
    from bill_of_lading_form import DEFAULT_BLOCKS, read_upload
    with pytest.raises(ValueError):
        read_upload(mover_pdf(scanned=True), 'Top Tier Van Lines', DEFAULT_BLOCKS)


def test_the_read_endpoint_keeps_nothing(db):
    from starlette.datastructures import UploadFile
    from models import CompanyDocument
    from routes.companies import read_bill_of_lading_pdf
    result = asyncio.run(read_bill_of_lading_pdf('c', 'bol', UploadFile(BytesIO(mover_pdf()), filename='bol.pdf'), None, db))
    assert result['unmatched'] and result['body_html'].startswith('<p><strong>SECTION 1:')
    document = db.get(CompanyDocument, ('c', 'bol'))
    assert document.revision == 1 and document.body_html == '<p>Terms</p>'


def test_the_header_shows_the_companys_details_from_the_form():
    from bill_of_lading_form import DEFAULT_BLOCKS
    blocks = [dict(row) for row in DEFAULT_BLOCKS]
    next(row for row in blocks if row['title'] == 'USDOT No.: {{company_dot_number}}')['title'] = 'US DOT # {{company_dot_number}}'
    page = text(build(blocks))
    assert 'Gorilla Haulers' in page and '19960 Wild Cherry Ln' in page and 'US DOT #' in page and 'USDOT No.' not in page


def test_a_total_shows_its_own_text_without_a_value():
    from bill_of_lading_form import DEFAULT_BLOCKS
    blocks = [dict(row) for row in DEFAULT_BLOCKS]
    next(row for row in blocks if row['fill'] == 'minimum_cuft')['text'] = 'cu ft'
    assert 'cu ft' in text(build(blocks))


def test_a_form_that_does_not_fit_one_page_is_not_saved(db):
    from bill_of_lading_form import DEFAULT_BLOCKS
    from bill_of_lading_pdf import form_problems
    paragraph = next(row for row in DEFAULT_BLOCKS if row['kind'] == 'paragraph')
    long = [dict(row) for row in DEFAULT_BLOCKS] + [dict(paragraph) for _ in range(3)]
    assert form_problems(DEFAULT_BLOCKS, 'Top Tier Van Lines') == []
    assert form_problems(long, 'Top Tier Van Lines') == ['The left column runs past the bottom of the page. Shorten or remove parts of it.']
    with pytest.raises(HTTPException) as error:
        save(db, long)
    assert error.value.status_code == 422
