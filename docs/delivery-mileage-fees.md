# Destination fees

Each long-distance pricing book has a collapsed **Destination fees** card.
Enable it and add delivery-state rules, optional ZIP patterns/ranges, a starting
five-digit ZIP, and a dollar rate per driving mile. Blank delivery ZIPs cover the
state. Narrower matching ZIP intervals override broader rules; equal-specificity
matches use the first row. Only one mileage fee applies per delivery.

Example: VT, all ZIPs, origin 20815, $5/mile. The charge uses one-way driving
miles from Google's mapped location for 20815 to the job's delivery address.
A full delivery address is more precise than a delivery ZIP. This is Google's
driving route, not a truck-clearance or truck-restriction assessment.

The backend uses the existing `GOOGLE_MAPS_SERVER_KEY` with the
[Google Routes API](https://developers.google.com/maps/documentation/routes/compute_route_directions).
The Google Cloud project must have Routes API enabled and the server key's API
restrictions must permit it. The key never reaches the browser. Existing Places
access alone does not confirm Routes access. Local tests mock Google; production
credentials and API enablement still need a live deployment check.

Route distance is converted from meters to miles and rounded to two decimals,
then multiplied by the configured rate and rounded to cents. Route failures
block pricing with a retryable error instead of omitting the charge or using
straight-line mileage. The charge description records miles, origin ZIP, and
rate and appears in the customer estimate and PDF.

Rules are stored in existing pricing-service rows. The job's existing package
JSON holds the route basis for its estimate. Repricing reuses that basis until
the origin or delivery address changes; rate changes reuse miles. No route
lookup runs on customer-page reads, packing answers, or a polling timer.
Public delivery-address changes update only the mileage/shuttle charges. A new
inventory report may establish a new route basis with the new estimate.
