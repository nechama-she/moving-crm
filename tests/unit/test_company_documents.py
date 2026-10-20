import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from company_documents import clean_html, default_body, estimate_documents, new_company_document


def test_document_formatting_and_links_are_sanitized():
    html = clean_html('<h3>Terms</h3><ul><li><b>Moving</b> <a href="https://example.com" onclick="bad()">Details</a></li></ul>'
                      '<script>alert(1)</script><img src=x onerror="bad()"><a href="javascript:bad()">Unsafe</a>')
    assert '<h3>Terms</h3>' in html
    assert '<ul><li><b>Moving</b>' in html
    assert '<a href="https://example.com">Details</a>' in html
    assert 'onclick' not in html and 'onerror' not in html and 'javascript' not in html
    assert 'alert' not in html and '<script' not in html
    assert 'Unsafe' in html


def test_default_keeps_supplied_terms_and_company_parameter():
    body = default_body()
    assert '{{company_name}}' in body and 'Gorilla Haulers' not in body
    assert 'mailto:sales@gorillahaulers.com' in body
    assert 'href="https://www.insurmedixbrokers.com"' in body
    assert '$0.50/per cubic foot' in body
    assert 'CLAIMS &amp; CHARGEBACKS' in body


def test_estimate_documents_are_company_and_move_specific():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, Company, Lead, LeadJob
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Company(id='a', name='A & Sons'), Company(id='b', name='B Movers')])
        db.flush()
        db.add_all([new_company_document('a'), new_company_document('b')])
        lead = Lead(id='lead', company_id='a', move_type='Long Distance')
        job = LeadJob(id='job', lead_id='lead', company_id='b')
        db.add(lead); db.flush(); db.add(job); db.commit()
        documents = estimate_documents(lead, job, db)
        assert len(documents) == 1
        assert 'Thank you for choosing B Movers' in documents[0]['body_html']
        job.company_id = 'a'
        assert 'Thank you for choosing A &amp; Sons' in estimate_documents(lead, job, db)[0]['body_html']
        lead.move_type = 'Local'
        assert estimate_documents(lead, job, db) == []
    engine.dispose()
