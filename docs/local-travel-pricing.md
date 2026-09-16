# Approximate local travel fees

Company Management has an editable Office address for each company. The normal deployment migration adds companies.office_address. No office addresses are prefilled.

## Automatic, account-free estimate

Local pricing locates the company office, pickup, and delivery using the US Census public geocoder for street addresses, or Zippopotam.us ZIP coordinates for ZIP-only inputs and unmatched addresses with a ZIP. No account, billing setup, API key, Google Routes, or self-hosted routing server is used.

Successful coordinate lookups are cached in memory (up to 4,096 inputs per API worker). Missing or unavailable locations are errors, not guessed zero miles. Estimates automatically refresh when the selected book or addresses change; volume/crew changes reuse the mileage. A retry button is available on lookup failures.

**These are straight-line miles, not road miles.** The UI labels this approximation and identifies ZIP-center estimates. It can underestimate routes around rivers and indirect road networks, including zero miles for two locations using the same ZIP center. Public lookup services still require network access and can be unavailable.

Reference: https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html and https://www.zippopotam.us/.

## Formula

Total miles = approximate office-to-pickup miles + approximate delivery-to-office miles.
Estimated travel hours = total miles / 60. At 60 mph, 1 mile equals 1 minute.
Billable travel hours = estimated travel hours rounded to the nearest whole hour, with half hours rounding up. Sum both legs before rounding. The minimum is one billable travel hour, even when the estimated distance is zero. Missing estimates remain incomplete, not a guessed one-hour fee.
Travel fee = travel hours * travel hourly rate (defaults to moving crew rate).

Pickup-to-delivery is excluded from this office travel fee. Travel is charged once per move, not per truck/mover. Full packing applies to moving hours only. Fuel is separate.

Travel is additional to the moving minimum by default. Each book can override the rate and whether travel counts toward the minimum. Both legs must be estimated before saving a job price; incomplete totals say before travel. Nonzero travel fees are saved in the existing job charges and lead estimated total.
