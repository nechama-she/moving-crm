import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from settings_transfer import company_mapping, setting_allowed, validate, TABLES


def test_apply_preserves_clients_and_remaps_configuration():
    from sqlalchemy import create_engine, select
    from models import Base, Company, Lead, PricingPlan, PricingRate, AppSetting, LeadDuplicationRule
    from settings_transfer import export_settings, apply_settings
    source = create_engine('sqlite://')
    target = create_engine('sqlite://')
    Base.metadata.create_all(source)
    Base.metadata.create_all(target)
    with source.begin() as conn:
        conn.execute(Company.__table__.insert().values(id='dev-company', name='Moving Co',
            facebook_page_id='dev-page', aircall_number_id='dev-number', aircall_name='Dev line',
            samrtmoving_branch_id='dev-branch', granot_api_id='dev-api', granot_mover_ref='dev-mover'))
        conn.execute(LeadDuplicationRule.__table__.insert().values(id='dev-rule', source_company_id='dev-company', target_company_id='dev-company', source_referral_source='dev', target_referral_source='dev', delay_minutes=1))
        conn.execute(PricingPlan.__table__.insert().values(id='dev-plan', company_id='dev-company', company_name='Moving Co', name='East', source_key='dev'))
        conn.execute(PricingRate.__table__.insert().values(id='dev-rate', plan_id='dev-plan', destination='FL', band_label='All', rate=5))
        conn.execute(AppSetting.__table__.insert().values(key='lead_job_stops:dev-client', value='private'))
        conn.execute(AppSetting.__table__.insert().values(key='local_pricing:dev-plan', value='{}'))
    with source.connect() as conn:
        bundle = export_settings(conn)
    assert 'lead_duplication_rules' not in bundle['tables']
    with target.begin() as conn:
        conn.execute(Company.__table__.insert().values(id='prod-company', name='Moving Co', aircall_number_id='keep-sender'))
        conn.execute(LeadDuplicationRule.__table__.insert().values(id='prod-rule', source_company_id='prod-company', target_company_id='prod-company', source_referral_source='prod', target_referral_source='prod', delay_minutes=480))
        conn.execute(Lead.__table__.insert().values(id='prod-lead', full_name='Existing Client', company_id='prod-company'))
        conn.execute(PricingPlan.__table__.insert().values(id='prod-plan', company_id='prod-company', company_name='Moving Co', name='East', source_key='prod'))
        conn.execute(AppSetting.__table__.insert().values(key='lead_job_stops:prod-client', value='keep'))
    for _ in range(2):
        with target.begin() as conn:
            apply_settings(conn, bundle)
    with target.connect() as conn:
        assert conn.execute(select(Lead.id, Lead.company_id)).all() == [('prod-lead', 'prod-company')]
        company = conn.execute(select(Company.__table__)).mappings().one()
        assert company['id'] == 'prod-company'
        for key, value in {'facebook_page_id': 'dev-page', 'aircall_number_id': 'dev-number',
                           'aircall_name': 'Dev line', 'samrtmoving_branch_id': 'dev-branch',
                           'granot_api_id': 'dev-api', 'granot_mover_ref': 'dev-mover'}.items():
            assert company[key] == value
        assert conn.execute(select(LeadDuplicationRule.id, LeadDuplicationRule.delay_minutes)).all() == [('prod-rule', 480)]
        assert conn.execute(select(PricingRate.plan_id, PricingRate.rate)).all() == [('prod-plan', 5)]
        values = dict(conn.execute(select(AppSetting.key, AppSetting.value)).all())
        assert values == {'lead_job_stops:prod-client': 'keep', 'local_pricing:prod-plan': '{}'}
    # A late failure must roll back changes already made earlier in the transaction.
    bundle['tables']['companies'][0]['phone'] = 'changed'
    bundle['tables']['app_settings'].append({'key': 'local_pricing:missing', 'value': '{}'})
    with pytest.raises(KeyError):
        with target.begin() as conn:
            apply_settings(conn, bundle)
    with target.connect() as conn:
        assert conn.execute(select(Company.phone)).scalar() is None
    source.dispose()
    target.dispose()


def test_keeps_production_company_ids():
    assert company_mapping([{'id': 'dev', 'name': ' Gorilla Haulers '}],
                           [{'id': 'prod', 'name': 'gorilla haulers'}]) == {'dev': 'prod'}


def test_room_names_preserve_production_ids():
    from sqlalchemy import create_engine, select
    from models import Base, InventoryRoomType
    from settings_transfer import export_settings, apply_settings
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(InventoryRoomType.__table__.insert().values(id='prod-room', name='Bedroom'))
        bundle = export_settings(connection)
        bundle['tables']['inventory_room_types'][0].update(id='dev-room', sort_order=5)
        apply_settings(connection, bundle)
        assert connection.execute(select(InventoryRoomType.id, InventoryRoomType.sort_order)).all() == [('prod-room', 5)]
    engine.dispose()


def test_ambiguous_or_missing_company_is_blocked():
    source = [{'id': 'dev', 'name': 'A'}]
    for target in ([], [{'id': '1', 'name': 'A'}, {'id': '2', 'name': 'a'}]):
        with pytest.raises(ValueError):
            company_mapping(source, target)


def test_sms_templates_and_defaults_are_not_transferred():
    from sqlalchemy import create_engine, select
    from models import Base, Company, CompanyMessageTemplate, AppSetting
    from settings_transfer import export_settings, apply_settings
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    keys = ['sms_system_default.' + name for name in
            ('welcome_sms', 'rep_assignment_sms', 'day2_followup_sms', 'day3_followup_sms')]
    with engine.begin() as connection:
        connection.execute(Company.__table__.insert().values(id='company', name='Moving Co'))
        connection.execute(CompanyMessageTemplate.__table__.insert().values(company_id='company', welcome_sms='production template'))
        for key in keys:
            connection.execute(AppSetting.__table__.insert().values(key=key, value='production default'))
        bundle = export_settings(connection)
        assert 'company_message_templates' not in bundle['tables']
        assert bundle['tables']['app_settings'] == []
        apply_settings(connection, bundle)
        assert connection.execute(select(CompanyMessageTemplate.welcome_sms)).scalar() == 'production template'
        assert dict(connection.execute(select(AppSetting.key, AppSetting.value)).all()) == dict.fromkeys(keys, 'production default')
        for key in keys:
            bundle['tables']['app_settings'] = [{'key': key, 'value': 'dev default'}]
            with pytest.raises(ValueError):
                validate(bundle)
        bundle['tables']['app_settings'] = []
        bundle['tables']['company_message_templates'] = []
        with pytest.raises(ValueError):
            validate(bundle)
    engine.dispose()


@pytest.mark.parametrize('key', ['lead_job_stops:123', 'migration:x', 'sales_rep_commission_percent:123', 'JWT_SECRET',
                               'sales_work_queue.ignored_call_numbers', 'rep_activity.ignored_sms_numbers'])
def test_client_and_unmapped_settings_excluded(key):
    assert not setting_allowed(key)


def test_ignored_number_lists_are_preserved():
    from sqlalchemy import create_engine, select
    from models import Base, AppSetting
    from settings_transfer import export_settings, apply_settings
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    saved = {'sales_work_queue.ignored_call_numbers': '["111"]',
             'rep_activity.ignored_sms_numbers': '["222"]'}
    with engine.begin() as connection:
        for key, value in saved.items():
            connection.execute(AppSetting.__table__.insert().values(key=key, value=value))
        bundle = export_settings(connection)
        assert bundle['tables']['app_settings'] == []
        apply_settings(connection, bundle)
        assert dict(connection.execute(select(AppSetting.key, AppSetting.value)).all()) == saved
        for key in saved:
            bundle['tables']['app_settings'] = [{'key': key, 'value': '[]'}]
            with pytest.raises(ValueError):
                validate(bundle)
    engine.dispose()


def test_bundle_rejects_client_tables_and_settings():
    bundle = {'format': 1, 'tables': {name: [] for name in (*TABLES, 'app_settings')}}
    validate(bundle)
    bundle['tables']['lead_duplication_rules'] = []
    with pytest.raises(ValueError):
        validate(bundle)
    del bundle['tables']['lead_duplication_rules']
    bundle['tables']['leads'] = []
    with pytest.raises(ValueError):
        validate(bundle)
    del bundle['tables']['leads']
    bundle['tables']['app_settings'] = [{'key': 'lead_job_stops:123', 'value': '[]'}]
    with pytest.raises(ValueError):
        validate(bundle)

