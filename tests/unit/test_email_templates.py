"""The automated email templates: a system default and each company's own, as the SMS ones, with no text of their own."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')

ADMIN = SimpleNamespace(id='admin', role='admin')


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, Company
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Company(id='c', name='Movers'))
        session.commit()
        yield session
    engine.dispose()


def test_the_welcome_email_starts_empty(db):
    from routes.templates import get_email_templates, get_system_default_email_templates
    assert get_system_default_email_templates(ADMIN, db)['defaults'] == {'welcome_email_subject': '', 'welcome_email_body': ''}
    company = get_email_templates('c', ADMIN, db)
    assert (company['welcome_email_subject'], company['welcome_email_body']) == ('', '')


def test_the_system_default_and_a_companys_own_are_saved(db):
    from routes.templates import (EmailTemplatesUpdate, get_email_templates, update_email_templates,
                                  update_system_default_email_templates)
    defaults = update_system_default_email_templates(
        EmailTemplatesUpdate(welcome_email_subject='Welcome to {company_name}', welcome_email_body='Hi {first_name}'), ADMIN, db)
    assert defaults['welcome_email_subject'] == 'Welcome to {company_name}'
    own = update_email_templates('c', EmailTemplatesUpdate(welcome_email_body='Hello {first_name}'), ADMIN, db)
    assert own['welcome_email_body'] == 'Hello {first_name}' and own['welcome_email_subject'] == ''
    assert own['defaults']['welcome_email_body'] == 'Hi {first_name}'
    assert get_email_templates('c', ADMIN, db)['welcome_email_body'] == 'Hello {first_name}'


def test_the_sms_templates_are_unchanged(db):
    from routes.templates import DEFAULTS, TemplatesUpdate, get_templates, update_email_templates, EmailTemplatesUpdate
    update_email_templates('c', EmailTemplatesUpdate(welcome_email_body='Hello'), ADMIN, db)
    sms = get_templates('c', ADMIN, db)
    assert set(sms) == {'company_id', 'defaults', 'welcome_sms', 'rep_assignment_sms', 'day2_followup_sms', 'day3_followup_sms',
                        'updated_by', 'updated_at'}
    assert sms['defaults'] == DEFAULTS and sms['welcome_sms'] == ''


def test_the_html_body_sent_as_base64_is_saved_as_written(db):
    import base64
    from routes.templates import EmailTemplatesUpdate, get_email_templates, update_email_templates
    html = '<div style="color:#c92e2e">Hi {first_name} — We’re here ✓</div>'
    body = EmailTemplatesUpdate(welcome_email_body_base64=base64.b64encode(html.encode('utf-8')).decode())
    update_email_templates('c', body, ADMIN, db)
    assert get_email_templates('c', ADMIN, db)['welcome_email_body'] == html
    with pytest.raises(ValueError):
        EmailTemplatesUpdate(welcome_email_body_base64='not base64!')
