"""Local hourly pricing transcribed from the supplied rate and capacity tables."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from pydantic import BaseModel, Field, field_validator, model_validator


class LocalSettings(BaseModel):
    minimum_hours: Decimal = Field(default=Decimal('3'), gt=0, le=24, allow_inf_nan=False)
    capacity_per_mover: Decimal = Field(default=Decimal('50'), gt=0, allow_inf_nan=False)
    # Retained for previously saved settings; travel now uses the total job hourly rate.
    travel_hourly_rate: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    travel_in_minimum: bool = False
    fuel_charge: Decimal = Field(default=Decimal('99'), ge=0, allow_inf_nan=False)
    full_pack_hourly: Decimal = Field(default=Decimal('65'), ge=0, allow_inf_nan=False)
    hourly_rates: list[Decimal | None] = Field(default_factory=lambda: [Decimal(n) for n in (65, 150, 195, 242, 282, 322)] + [None]*4, min_length=10, max_length=10)
    crew_thresholds: list[int] = Field(default_factory=lambda: [0, 500, 1600, 2000, 3200, 4200, 5200, 6200, 7200], min_length=9, max_length=9)
    truck_thresholds: list[int] = Field(default_factory=lambda: [1600, 3200, 4800, 6800, 8500, 10200, 11900, 13600, 15300], min_length=9, max_length=9)

    @model_validator(mode='after')
    def valid_tables(self):
        for thresholds in (self.crew_thresholds, self.truck_thresholds):
            if any(value < 0 for value in thresholds) or any(a >= b for a, b in zip(thresholds, thresholds[1:])):
                raise ValueError('Volume thresholds must be nonnegative and strictly increasing')
        for rate in self.hourly_rates:
            if rate is not None and (not rate.is_finite() or rate <= 0):
                raise ValueError('Hourly rates must be positive, or blank when not configured')
        return self


class LocalCalculation(BaseModel):
    cubic_feet: Decimal = Field(gt=0, allow_inf_nan=False)
    crew_size: int | None = Field(default=None, ge=1, le=10)
    hours: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    full_pack: bool = False
    office_to_pickup_miles: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    delivery_to_office_miles: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator('cubic_feet', mode='before')
    @classmethod
    def round_up_cubic_feet(cls, value):
        if value is None or value == '':
            return value
        return Decimal(str(value)).to_integral_value(rounding=ROUND_CEILING)

    @model_validator(mode='after')
    def both_travel_legs(self):
        if (self.office_to_pickup_miles is None) != (self.delivery_to_office_miles is None):
            raise ValueError('Both office travel distances are required')
        return self


def calculate_local(settings: LocalSettings, body: LocalCalculation):
    money = lambda value: value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    recommended_crew = 1 + sum(body.cubic_feet > threshold for threshold in settings.crew_thresholds)
    trucks = 1 + sum(body.cubic_feet > threshold for threshold in settings.truck_thresholds)
    crew = body.crew_size or recommended_crew
    capacity = settings.capacity_per_mover * crew
    estimated_hours = body.cubic_feet / capacity
    travel_complete = body.office_to_pickup_miles is not None and body.delivery_to_office_miles is not None
    estimated_travel_hours = ((body.office_to_pickup_miles or Decimal(0)) + (body.delivery_to_office_miles or Decimal(0))) / 60
    travel_hours = max(Decimal('1'), estimated_travel_hours.quantize(Decimal('1'), rounding=ROUND_HALF_UP)) if travel_complete else Decimal(0)
    moving_hours = body.hours if body.hours is not None else estimated_hours
    minimum_moving_hours = max(Decimal(0), settings.minimum_hours - travel_hours) if settings.travel_in_minimum else settings.minimum_hours
    base_hours = max(minimum_moving_hours, moving_hours)
    packing_hours = (Decimal(1) + (body.cubic_feet / 1000).to_integral_value(rounding=ROUND_CEILING)) if body.full_pack else Decimal(0)
    hours = base_hours + packing_hours
    rate = settings.hourly_rates[crew - 1]
    travel_rate = rate + (settings.full_pack_hourly if body.full_pack else Decimal(0)) if rate is not None else None
    charges = []
    if rate is not None:
        charges.append({'name': 'Local moving', 'description': f'{crew} movers for {hours:.2f} hours at ${rate:.2f}/hour',
                        'subtotal': money(rate * hours), 'discountAmount': Decimal(0), 'totalCost': money(rate * hours)})
        if body.full_pack and settings.full_pack_hourly:
            amount = money(settings.full_pack_hourly * hours)
            charges.append({'name': 'Full packing', 'description': f'{hours:.2f} hours at ${settings.full_pack_hourly:.2f}/hour',
                            'subtotal': amount, 'discountAmount': Decimal(0), 'totalCost': amount})
        if travel_complete and travel_hours and travel_rate:
            amount = money(travel_hours * travel_rate)
            if amount:
                charges.append({'name': 'Travel fee',
                    'description': f'Office to pickup: {body.office_to_pickup_miles:.2f} miles; delivery to office: {body.delivery_to_office_miles:.2f} miles (estimated mileage including 39% allowance, 60 mph). {travel_hours:.0f} rounded hours at ${travel_rate:.2f}/hour',
                    'subtotal': amount, 'discountAmount': Decimal(0), 'totalCost': amount})
        if settings.fuel_charge:
            amount = money(settings.fuel_charge)
            charges.append({'name': 'Fuel charge', 'description': 'Flat fuel charge per move',
                            'subtotal': amount, 'discountAmount': Decimal(0), 'totalCost': amount})
    return {'estimated_travel_hours': estimated_travel_hours, 'travel_complete': travel_complete, 'travel_hours': travel_hours, 'travel_hourly_rate': travel_rate,
            'recommended_crew': recommended_crew, 'crew_size': crew, 'trucks': trucks,
            'capacity': capacity, 'estimated_hours': estimated_hours, 'base_hours': base_hours, 'packing_hours': packing_hours, 'billable_hours': hours,
            'hourly_rate': rate, 'full_pack_hourly': settings.full_pack_hourly if body.full_pack else Decimal(0),
            'minimum_applied': moving_hours < minimum_moving_hours,
            'charges': charges, 'total': sum((line['totalCost'] for line in charges), Decimal(0)) if rate is not None else None,
            'warning': f'Enter an hourly rate for {crew} movers in Local settings before quoting.' if rate is None else ''}
