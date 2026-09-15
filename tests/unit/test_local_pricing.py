import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[2] / 'backend'
sys.path.insert(0, str(BACKEND))
from local_pricing import LocalSettings, LocalCalculation, calculate_local


@pytest.mark.parametrize('volume,crew,trucks', [
    (1, 2, 1), (500, 2, 1), (501, 3, 1), (1600, 3, 1), (1601, 4, 2),
    (2000, 4, 2), (2001, 5, 2), (3200, 5, 2), (3201, 6, 3),
    (4201, 7, 3), (4801, 7, 4), (5201, 8, 4), (6201, 9, 4),
    (6801, 9, 5), (7201, 10, 5), (8501, 10, 6), (10201, 10, 7),
    (11901, 10, 8), (13601, 10, 9), (15301, 10, 10),
])
def test_exact_screenshot_thresholds(volume, crew, trucks):
    quote = calculate_local(LocalSettings(), LocalCalculation(cubic_feet=volume))
    assert quote['crew_size'] == crew
    assert quote['trucks'] == trucks
    assert quote['capacity'] == crew * 50


def test_minimum_hours_and_full_pack_is_once_per_hour():
    quote = calculate_local(LocalSettings(), LocalCalculation(cubic_feet=100, full_pack=True))
    assert quote['billable_hours'] == 3
    assert quote['hourly_rate'] == 150
    assert quote['full_pack_hourly'] == 65
    assert quote['total'] == Decimal('645.00')
    assert [line['totalCost'] for line in quote['charges']] == [Decimal('450.00'), Decimal('195.00')]


def test_volume_estimate_and_no_truck_fee():
    quote = calculate_local(LocalSettings(), LocalCalculation(cubic_feet=1800))
    assert quote['crew_size'] == 4
    assert quote['billable_hours'] == 9
    assert quote['trucks'] == 2
    assert quote['total'] == Decimal('2178.00')
    assert len(quote['charges']) == 1


def test_manual_crew_hours_and_minimum():
    quote = calculate_local(LocalSettings(), LocalCalculation(cubic_feet=1800, crew_size=6, hours=2))
    assert quote['recommended_crew'] == 4
    assert quote['crew_size'] == 6
    assert quote['billable_hours'] == 3
    assert quote['total'] == Decimal('966.00')


def test_missing_rate_blocks_quote_without_extrapolating():
    quote = calculate_local(LocalSettings(), LocalCalculation(cubic_feet=4500))
    assert quote['crew_size'] == 7
    assert quote['hourly_rate'] is None
    assert quote['total'] is None
    assert quote['charges'] == []
    assert '7 movers' in quote['warning']


def test_configured_rate_and_full_pack_override():
    settings = LocalSettings()
    settings.hourly_rates[6] = Decimal('400')
    settings.full_pack_hourly = Decimal('70')
    quote = calculate_local(settings, LocalCalculation(cubic_feet=4500, hours=10, full_pack=True))
    assert quote['total'] == Decimal('4700.00')


@pytest.mark.parametrize('body', [{'minimum_hours': 0}, {'capacity_per_mover': 0}, {'full_pack_hourly': -1},
    {'crew_thresholds': [0]*9}, {'truck_thresholds': [1600, 1500] + list(range(2000, 2007))},
    {'hourly_rates': [-1] + [None]*9}, {'hourly_rates': [float('inf')] + [None]*9}])
def test_invalid_settings_rejected(body):
    with pytest.raises(ValueError):
        LocalSettings(**body)


@pytest.fixture
def api():
    spec = importlib.util.spec_from_file_location('local_pricing_api_test', BACKEND / 'routes/local_pricing.py')
    module = importlib.util.module_from_spec(spec)
    mocks = {name: MagicMock() for name in ['auth', 'database', 'models', 'routes.pricing']}
    with patch.dict(sys.modules, mocks):
        spec.loader.exec_module(module)
    return module


def test_only_gorilla_east_has_prefilled_values(api):
    db = MagicMock(); db.get.return_value = None
    for company, book, seeded in [('Gorilla Haulers', 'East', True), ('Gorilla Haulers', 'Midwest', False), ('Top Tier Van Lines', 'East', False)]:
        settings = api.load_settings(SimpleNamespace(id=book, company_name=company, name=book), db)
        assert (settings is not None) == seeded


def test_saved_settings_are_book_scoped(api):
    db = MagicMock(); db.get.return_value = SimpleNamespace(value=LocalSettings(full_pack_hourly=80).model_dump_json())
    settings = api.load_settings(SimpleNamespace(id='book-2'), db)
    assert settings.full_pack_hourly == 80
    db.get.assert_called_once_with(api.AppSetting, 'local_pricing:book-2')


def test_unauthorized_book_never_reads_settings(api):
    db = MagicMock()
    api._plan_or_404.side_effect = HTTPException(404, 'Pricing plan not found')
    with pytest.raises(HTTPException):
        api.get_settings('other-book', object(), db)
    db.get.assert_not_called()


@pytest.mark.parametrize('pickup,delivery,expected', [('20853', '21201', 'Local'), ('20853', '11223', 'Long Distance'), ('Unknown', '11223', '')])
def test_job_context_selects_pricing_by_state(pickup, delivery, expected):
    import ast
    import re
    from zip_state import delivery_location
    source = BACKEND / 'routes/pricing.py'
    node = next(node for node in ast.parse(source.read_text()).body if getattr(node, 'name', '') == 'get_job_pricing_context')
    node.decorator_list = []
    node.args.defaults = []
    for arg in node.args.args:
        arg.annotation = None
    job = SimpleNamespace(lead_id='lead', company_id='company', pickup_zip=pickup, delivery_zip=delivery, to_dict=lambda: {'id': 'job'})
    lead = SimpleNamespace(id='lead', full_name='Customer', volume=1000, weight=None)
    db = MagicMock(); db.get.return_value = lead
    accessible = MagicMock()
    accessible.return_value.filter.return_value.order_by.return_value.all.return_value = []
    scope = {'re': re, 'delivery_location': delivery_location, 'Lead': object(), 'PricingPlan': MagicMock(), '_accessible_query': accessible}
    with patch.dict(sys.modules, {'routes.leads': SimpleNamespace(_get_job_or_404=MagicMock(return_value=job))}):
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
        assert scope['get_job_pricing_context']('lead', 'job', object(), db)['move_type'] == expected


def test_saving_settings_preserves_book_isolation(api):
    db = MagicMock(); db.get.return_value = None
    settings = LocalSettings(full_pack_hourly=90)
    api.save_settings('book-1', settings, object(), db)
    assert api.AppSetting.call_args.kwargs['key'] == 'local_pricing:book-1'
    assert LocalSettings.model_validate_json(api.AppSetting.call_args.kwargs['value']).full_pack_hourly == 90
    db.commit.assert_called_once()
