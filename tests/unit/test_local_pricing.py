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
    assert quote['billable_hours'] == 5
    assert quote['hourly_rate'] == 150
    assert quote['full_pack_hourly'] == 65
    assert quote['total'] == Decimal('1174.00')
    assert [line['totalCost'] for line in quote['charges']] == [Decimal('750.00'), Decimal('325.00'), Decimal('99.00')]


def test_volume_estimate_and_no_truck_fee():
    quote = calculate_local(LocalSettings(), LocalCalculation(cubic_feet=1800))
    assert quote['crew_size'] == 4
    assert quote['billable_hours'] == 9
    assert quote['trucks'] == 2
    assert quote['total'] == Decimal('2277.00')
    assert len(quote['charges']) == 2


def test_manual_crew_hours_and_minimum():
    quote = calculate_local(LocalSettings(), LocalCalculation(cubic_feet=1800, crew_size=6, hours=2))
    assert quote['recommended_crew'] == 4
    assert quote['crew_size'] == 6
    assert quote['billable_hours'] == 3
    assert quote['total'] == Decimal('1065.00')


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
    assert quote['total'] == Decimal('7619.00')


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


@pytest.mark.parametrize('fuel', [0, 99, 125])
def test_fuel_is_editable_flat_fee_and_zero_is_omitted(fuel):
    quote = calculate_local(LocalSettings(fuel_charge=fuel), LocalCalculation(cubic_feet=1800))
    assert quote['total'] == Decimal('2178') + fuel
    lines = [line for line in quote['charges'] if line['name'] == 'Fuel charge']
    assert len(lines) == (1 if fuel else 0)
    if fuel:
        assert lines[0]['totalCost'] == fuel


def test_existing_settings_get_default_fuel():
    data = LocalSettings().model_dump()
    del data['fuel_charge']
    assert LocalSettings.model_validate(data).fuel_charge == 99


def test_negative_fuel_rejected():
    with pytest.raises(ValueError):
        LocalSettings(fuel_charge=-1)


@pytest.mark.parametrize('packing', [False, True])
def test_travel_charged_once_at_total_hourly_rate_outside_minimum(packing):
    quote = calculate_local(LocalSettings(), LocalCalculation(cubic_feet=100, full_pack=packing,
        office_to_pickup_miles=30, delivery_to_office_miles=45))
    assert quote['travel_complete']
    assert quote['billable_hours'] == (5 if packing else 3)
    assert quote['travel_hours'] == Decimal('1')
    assert quote['travel_hourly_rate'] == (215 if packing else 150)
    travel = next(line for line in quote['charges'] if line['name'] == 'Travel fee')
    assert travel['totalCost'] == (Decimal('215.00') if packing else Decimal('150.00'))
    assert quote['total'] == Decimal('699.00') + (Decimal('690') if packing else 0)


def test_travel_minimum_is_editable_and_legacy_rate_does_not_override_total_rate():
    quote = calculate_local(LocalSettings(travel_in_minimum=True, travel_hourly_rate=100),
        LocalCalculation(cubic_feet=100, office_to_pickup_miles=30, delivery_to_office_miles=45))
    assert quote['billable_hours'] == Decimal('2')
    assert quote['total'] == Decimal('549.00')  # 2*150 moving + 1*150 travel + 99 fuel


def test_missing_travel_is_incomplete_and_zero_distance_has_minimum_fee():
    missing = calculate_local(LocalSettings(), LocalCalculation(cubic_feet=100))
    assert not missing['travel_complete']
    zero = calculate_local(LocalSettings(), LocalCalculation(cubic_feet=100, office_to_pickup_miles=0, delivery_to_office_miles=0))
    assert zero['travel_complete']
    assert zero['travel_hours'] == 1
    assert next(line for line in zero['charges'] if line['name'] == 'Travel fee')['totalCost'] == 150
    with pytest.raises(ValueError):
        LocalCalculation(cubic_feet=100, office_to_pickup_miles=30)
    with pytest.raises(ValueError):
        LocalCalculation(cubic_feet=100, office_to_pickup_miles=-1, delivery_to_office_miles=0)


def test_travel_uses_saved_job_addresses_and_current_company_office(api):
    plan = SimpleNamespace(id='book', company_id='company')
    api._plan_or_404.return_value = plan
    db = MagicMock(); db.get.return_value = SimpleNamespace(office_address='123 Office St, Rockville MD 20850')
    get_job = MagicMock(return_value=SimpleNamespace(company_id='company', pickup_zip='456 Pickup St, Rockville MD 20850', delivery_zip='789 Delivery St, Baltimore MD 21201'))
    estimate = MagicMock(return_value={'total_minutes': 75})
    with patch.dict(sys.modules, {'routes.leads': SimpleNamespace(_get_job_or_404=get_job), 'travel_routes': SimpleNamespace(estimate_travel=estimate)}):
        result = api.travel_times('book', api.TravelRequest(lead_id='lead', job_id='job', pickup='ignored', delivery='ignored'), object(), db)
    assert result['total_minutes'] == 75
    estimate.assert_called_once_with('123 Office St, Rockville MD 20850', '456 Pickup St, Rockville MD 20850', '789 Delivery St, Baltimore MD 21201')


def test_travel_rejects_wrong_company_book(api):
    api._plan_or_404.return_value = SimpleNamespace(company_id='other-company')
    db = MagicMock(); estimate = MagicMock()
    get_job = MagicMock(return_value=SimpleNamespace(company_id='company'))
    with patch.dict(sys.modules, {'routes.leads': SimpleNamespace(_get_job_or_404=get_job), 'travel_routes': SimpleNamespace(estimate_travel=estimate)}):
        with pytest.raises(HTTPException) as error:
            api.travel_times('book', api.TravelRequest(lead_id='lead', job_id='job'), object(), db)
    assert error.value.status_code == 400
    estimate.assert_not_called()


@pytest.mark.parametrize('miles,hours', [('0', 1), ('29.99', 1), ('30', 1), ('60', 1), ('89.99', 1), ('90', 2), ('150', 3)])
def test_travel_rounds_combined_hours_half_up(miles, hours):
    half = Decimal(miles) / 2
    quote = calculate_local(LocalSettings(), LocalCalculation(cubic_feet=100,
        office_to_pickup_miles=half, delivery_to_office_miles=half))
    assert quote['travel_hours'] == hours
    assert quote['total'] == Decimal('549') + hours * 150
    assert any(line['name'] == 'Travel fee' for line in quote['charges']) == (hours > 0)


def test_travel_full_pack_uses_configured_addon_for_all_travel_hours():
    quote = calculate_local(LocalSettings(full_pack_hourly=80, travel_hourly_rate=100),
        LocalCalculation(cubic_feet=100, full_pack=True,
                         office_to_pickup_miles=45, delivery_to_office_miles=45))
    assert quote['travel_hours'] == 2
    assert quote['travel_hourly_rate'] == 230
    travel = next(line for line in quote['charges'] if line['name'] == 'Travel fee')
    assert travel['totalCost'] == 460
    assert '$230.00/hour' in travel['description']
    assert quote['total'] == 1709  # 5*230 moving/packing + 2*230 travel + 99 fuel


@pytest.mark.parametrize('volume,extra', [('1', 2), ('1000', 2), ('1000.01', 3), ('1800', 3), ('2000', 3), ('2000.01', 4)])
def test_packing_hours_round_each_additional_thousand_up(volume, extra):
    quote = calculate_local(LocalSettings(), LocalCalculation(cubic_feet=volume, full_pack=True))
    assert quote['packing_hours'] == extra
    assert quote['billable_hours'] == quote['base_hours'] + extra
    without = calculate_local(LocalSettings(), LocalCalculation(cubic_feet=volume))
    assert without['packing_hours'] == 0
    assert without['billable_hours'] == quote['base_hours']


def test_full_pack_screenshot_has_twelve_hours_and_separate_travel():
    quote = calculate_local(LocalSettings(), LocalCalculation(cubic_feet=1800, full_pack=True,
        office_to_pickup_miles=Decimal('12.12'), delivery_to_office_miles=Decimal('25.77')))
    assert quote['base_hours'] == 9
    assert quote['packing_hours'] == 3
    assert quote['billable_hours'] == 12
    assert quote['travel_hours'] == 1
    assert [line['totalCost'] for line in quote['charges']] == [2904, 780, 307, 99]
    assert quote['total'] == 4090


def test_packing_is_added_to_manual_moving_hours_even_with_zero_packing_rate():
    quote = calculate_local(LocalSettings(full_pack_hourly=0), LocalCalculation(cubic_feet=1800, hours=4, full_pack=True))
    assert quote['billable_hours'] == 7
    assert quote['total'] == 1793  # 7*242 + 99
