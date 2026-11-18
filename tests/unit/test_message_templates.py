"""Message templates picked when writing to a lead: a default text for every company, a company's own text instead
where it has one, filled in with the lead's, company's and rep's details."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


@pytest.fixture
def setup(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, Company, Lead, LeadJob, User
    for name in list(sys.modules):
        if name in ('database', 'routes.leads', 'routes.message_templates', 'libs') or name.startswith('libs.'):
            monkeypatch.delitem(sys.modules, name)
    import importlib
    leads = importlib.import_module('routes.leads')
    templates = importlib.import_module('routes.message_templates')
    monkeypatch.setattr(leads, '_get_visible_lead_or_404', lambda lead_id, user, db: db.get(Lead, lead_id))
    monkeypatch.setattr(leads, '_read_job_route', lambda db, job: ('Norfolk, VA', [], 'Moyock, NC'))
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Company(id='movers95', name='Movers 95', phone='240-226-3174', website='https://www.movers95.com', sender_email='sales@movers95.com'), Company(id='gorilla', name='Gorilla Haulers', phone='555-0100'),
                    User(id='eli', name='Eli Jones', email='eli@example.com', phone='555-0199', password_hash='x', role='admin')])
        db.flush()
        db.add_all([Lead(id='a', full_name='Gabrielle Taylor', phone='5512752490', company_id='movers95', assigned_to='eli'),
                    Lead(id='b', full_name='Pat Mover', company_id='gorilla')])
        db.flush()
        db.add(LeadJob(id='j', lead_id='a', job_order=1, move_date='12/23/2026'))
        db.commit()
        yield templates, db, db.get(User, 'eli')
    engine.dispose()


def test_default_text_filled_in_and_a_companys_own_text(setup):
    templates, db, admin = setup
    created = templates.create_template(templates.TemplateInput(name='Follow up', body='Hi @FirstName, this is @RepName from @CompanyName (@CompanyPhone). Moving @Pickup to @Delivery on @MoveDate. Email us at office@movers95.com.'), admin, db)
    filled = templates.lead_templates('a', admin, db)['items']
    assert filled == [{'id': created['id'], 'name': 'Follow up',
                       'text': 'Hi Gabrielle, this is Eli Jones from Movers 95 ((240) 226-3174). Moving Norfolk, VA to Moyock, NC on 12/23/2026. Email us at office@movers95.com.'}]
    # Movers 95 gets its own text; Gorilla Haulers keeps the default.
    templates.save_company_text(created['id'], 'movers95', templates.OverrideInput(body='Movers 95 here, @FirstName!'), admin, db)
    assert templates.lead_templates('a', admin, db)['items'][0]['text'] == 'Movers 95 here, Gabrielle!'
    assert templates.lead_templates('b', admin, db)['items'][0]['text'].startswith('Hi Pat, this is  from Gorilla Haulers')
    listed = templates.list_templates('movers95', admin, db)['templates'][0]
    assert listed['override'] == 'Movers 95 here, @FirstName!' and listed['body'].startswith('Hi @FirstName')
    # Blank: Movers 95 uses the default again.
    templates.save_company_text(created['id'], 'movers95', templates.OverrideInput(body=''), admin, db)
    assert templates.lead_templates('a', admin, db)['items'][0]['text'].startswith('Hi Gabrielle')


def test_deleting_a_template_removes_company_texts(setup):
    from models import MessageTemplateOverride
    templates, db, admin = setup
    created = templates.create_template(templates.TemplateInput(name='One', body='x'), admin, db)
    templates.save_company_text(created['id'], 'movers95', templates.OverrideInput(body='y'), admin, db)
    templates.delete_template(created['id'], admin, db)
    assert templates.lead_templates('a', admin, db)['items'] == []
    assert db.query(MessageTemplateOverride).count() == 0


def test_only_an_at_starting_a_word_is_a_field(setup):
    templates, _, _ = setup
    values = {'FirstName': 'Gabrielle', 'RepName': 'Eli Jones'}
    assert templates.fill('Hi @FirstName, (@RepName) sales@FirstName.com @Unknown', values) == 'Hi Gabrielle, (Eli Jones) sales@FirstName.com @Unknown'


def test_blank_name_or_text_is_refused(setup):
    import pydantic
    templates, _, _ = setup
    for name, body in (('   ', 'text'), ('Name', '  \n ')):
        with pytest.raises(pydantic.ValidationError):
            templates.TemplateInput(name=name, body=body)


def test_every_field_in_the_list_is_filled_in(setup):
    from models import Lead
    templates, db, admin = setup
    lead = db.get(Lead, 'a')
    lead.volume, lead.weight, lead.move_size, lead.move_type, lead.referral_source = 286, 2002.5, '2 bedroom', 'long_distance', 'Facebook'
    db.commit()
    body = ' | '.join('@' + token for token, _, _ in templates.PLACEHOLDERS)
    templates.create_template(templates.TemplateInput(name='All', body=body), admin, db)
    text = templates.lead_templates('a', admin, db)['items'][0]['text']
    assert not any('@' + token in text for token, _, _ in templates.PLACEHOLDERS)  # Every field was replaced.
    filled = dict(zip([token for token, _, _ in templates.PLACEHOLDERS], text.split(' | ')))
    assert filled['FirstName'] == 'Gabrielle' and filled['LastName'] == 'Taylor'
    assert filled['LeadPhone'] == '(551) 275-2490' and filled['MoveType'] == 'Long Distance'
    assert filled['Volume'] == '286 cu ft' and filled['Weight'] == '2,002.50 lb' and filled['MoveSize'] == '2 bedroom'
    # Eli is an admin: his name, with the company's phone and email, not his profile's.
    assert filled['RepName'] == 'Eli Jones' and filled['RepPhone'] == '(240) 226-3174' and filled['RepEmail'] == 'sales@movers95.com'
    assert filled['JobNumber'].endswith('-1') and filled['ReferralSource'] == 'Facebook'
    assert filled['CompanyWebsite'] == 'https://www.movers95.com'


def test_a_sales_reps_own_phone_and_email(setup):
    from models import Lead, User
    templates, db, admin = setup
    db.add(User(id='sam', name='Sam Rep', email='sam@example.com', phone='2029372625', password_hash='x', role='sales_rep'))
    db.get(Lead, 'a').assigned_to = 'sam'
    db.commit()
    templates.create_template(templates.TemplateInput(name='Call', body='@RepName: @RepPhone, @RepEmail'), admin, db)
    assert templates.lead_templates('a', admin, db)['items'][0]['text'] == 'Sam Rep: (202) 937-2625, sam@example.com'
