"""The welcome email: sent where the welcome SMS is, from the company's template (else the system default), never
partly filled, to the test address on dev, and not at all on a dry run."""
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import AppSetting, Base, Company, Lead
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Company(id='c', name='Gorilla Haulers', phone='202-937-2625', sender_email='sales@gorillahaulers.com',
                            dot_number='3467429', valuation_per_lb=Decimal('0.60')))
        session.add_all([AppSetting(key='email_system_default.welcome_email_subject', value='{company_name} - Quick Quote for Your Move'),
                         AppSetting(key='email_system_default.welcome_email_body',
                                    value='<p>Hi {first_name},</p><p>US DOT # {company_dot_number}, ${company_valuation_per_lb}/lb</p>')])
        session.add(Lead(id='lead', full_name='Chaim <Gluckowsky>', email='chaim@example.com', company_id='c'))
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def sent(monkeypatch):
    import customer_email_auth
    emails = []
    monkeypatch.setattr(customer_email_auth, 'send_company_email',
                        lambda to, subject, text, company, html_body=None: emails.append((to, subject, text, html_body)))
    monkeypatch.setenv('WELCOME_EMAIL_DRY_RUN', 'false')
    monkeypatch.delenv('WELCOME_EMAIL_REDIRECT_TO', raising=False)
    return emails


def send(db):
    from models import Company, Lead
    from routes.leads import _send_welcome_email
    _send_welcome_email(db.get(Lead, 'lead'), db.get(Company, 'c'), db)


def test_the_welcome_email_is_filled_and_sent_to_the_customer(db, sent):
    send(db)
    [(to, subject, text, html_body)] = sent
    assert to == 'chaim@example.com' and subject == 'Gorilla Haulers - Quick Quote for Your Move'
    # The customer's name goes into the HTML as text.
    assert html_body == '<p>Hi Chaim,</p><p>US DOT # 3467429, $0.60/lb</p>'
    assert text == 'Hi Chaim,\nUS DOT # 3467429, $0.60/lb'


def test_a_name_with_markup_goes_in_as_text(db, sent):
    from models import Lead
    db.get(Lead, 'lead').full_name = '<b>Chaim</b> Gluckowsky'
    send(db)
    assert sent[0][3].startswith('<p>Hi &lt;b&gt;Chaim&lt;/b&gt;,</p>')


def test_on_dev_every_welcome_email_goes_to_the_test_address(db, sent, monkeypatch):
    monkeypatch.setenv('WELCOME_EMAIL_REDIRECT_TO', 'tester@example.com')
    send(db)
    assert [email[0] for email in sent] == ['tester@example.com']


def test_a_dry_run_sends_nothing(db, sent, monkeypatch):
    monkeypatch.setenv('WELCOME_EMAIL_DRY_RUN', 'true')
    send(db)
    assert sent == []


def test_a_companys_own_email_is_used_before_the_system_default(db, sent):
    from models import CompanyMessageTemplate
    db.add(CompanyMessageTemplate(company_id='c', welcome_email_subject='Welcome, {first_name}'))
    db.commit()
    send(db)
    assert sent[0][1] == 'Welcome, Chaim' and sent[0][3].startswith('<p>Hi Chaim')  # Its body: the default's.


def test_no_email_without_a_template_or_with_an_empty_placeholder(db, sent):
    from models import AppSetting, Company
    db.get(Company, 'c').dot_number = ''
    db.commit()
    send(db)
    assert sent == []  # {company_dot_number} has no value: never sent partly filled.
    db.delete(db.get(AppSetting, 'email_system_default.welcome_email_body'))
    db.get(Company, 'c').dot_number = '3467429'
    db.commit()
    send(db)
    assert sent == []  # No body anywhere.


def test_a_failed_send_does_not_stop_the_lead(db, monkeypatch):
    import customer_email_auth
    monkeypatch.setenv('WELCOME_EMAIL_DRY_RUN', 'false')
    def fail(*args, **kwargs):
        raise RuntimeError('SES is down')
    monkeypatch.setattr(customer_email_auth, 'send_company_email', fail)
    send(db)  # Logged, not raised.
