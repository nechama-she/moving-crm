"""Resolve a US state from a delivery address or five-digit ZIP code."""

from __future__ import annotations

import re


# USPS ZIP prefix allocations. Explicit state abbreviations in an address take
# precedence because a handful of special-purpose ZIP prefixes cross boundaries.
ZIP_PREFIX_RANGES = (
    ("CT", ((60, 69),)),
    ("MA", ((10, 27), (55, 55))),
    ("ME", ((39, 49),)),
    ("NH", ((30, 38),)),
    ("RI", ((28, 29),)),
    ("VT", ((50, 59),)),
    ("NJ", ((70, 89),)),
    ("NY", ((100, 149), (5, 5))),
    ("PA", ((150, 196),)),
    ("DE", ((197, 199),)),
    ("DC", ((200, 200), (202, 205), (569, 569))),
    ("MD", ((206, 219),)),
    ("VA", ((201, 201), (220, 246),)),
    ("WV", ((247, 268),)),
    ("NC", ((270, 289),)),
    ("SC", ((290, 299),)),
    ("GA", ((300, 319), (398, 399))),
    ("FL", ((320, 349),)),
    ("AL", ((350, 369),)),
    ("TN", ((370, 385),)),
    ("MS", ((386, 397),)),
    ("KY", ((400, 427),)),
    ("OH", ((430, 459),)),
    ("IN", ((460, 479),)),
    ("MI", ((480, 499),)),
    ("IA", ((500, 528),)),
    ("WI", ((530, 549),)),
    ("MN", ((550, 567),)),
    ("SD", ((570, 577),)),
    ("ND", ((580, 588),)),
    ("MT", ((590, 599),)),
    ("IL", ((600, 629),)),
    ("MO", ((630, 658),)),
    ("KS", ((660, 679),)),
    ("NE", ((680, 693),)),
    ("LA", ((700, 714),)),
    ("AR", ((716, 729),)),
    ("OK", ((730, 749),)),
    ("TX", ((733, 733), (750, 799), (885, 885))),
    ("CO", ((800, 816),)),
    ("WY", ((820, 831),)),
    ("ID", ((832, 838),)),
    ("UT", ((840, 847),)),
    ("AZ", ((850, 865),)),
    ("NM", ((870, 884),)),
    ("NV", ((889, 898),)),
    ("CA", ((900, 961),)),
    ("HI", ((967, 968),)),
    ("OR", ((970, 979),)),
    ("WA", ((980, 994),)),
    ("AK", ((995, 999),)),
)

STATE_CODES = {state for state, _ in ZIP_PREFIX_RANGES}

STATE_NAMES = dict(zip(
    ('Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|District of Columbia|'
     'Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|'
     'Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|'
     'New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|'
     'Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|'
     'West Virginia|Wisconsin|Wyoming').lower().split('|'),
    'AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split(),
))


def delivery_location(value: str | None) -> tuple[str, str]:
    raw = (value or "").strip()
    zip_match = re.search(r"\b(\d{5})(?:-\d{4})?\b", raw)
    zip_code = zip_match.group(1) if zip_match else ""

    explicit_codes = re.findall(r"(?:,\s*|\b)([A-Za-z]{2})(?=\s+\d{5}(?:-\d{4})?\b)", raw)
    if explicit_codes:
        state = explicit_codes[-1].upper()
        if state in STATE_CODES:
            return state, zip_code

    suffix = re.sub(r',?\s*(?:USA|US|United States(?: of America)?)\s*$', '', raw, flags=re.IGNORECASE).strip()
    suffix = re.sub(r'\s+\d{5}(?:-\d{4})?$', '', suffix).strip()
    for name in sorted(STATE_NAMES, key=len, reverse=True):
        if re.search(r'(?:^|,\s*|\s)' + re.escape(name) + r'$', suffix, re.IGNORECASE):
            return STATE_NAMES[name], zip_code
    code = re.search(r'(?:^|,\s*|\s)([A-Z]{2})$', suffix, re.IGNORECASE)
    if code and code.group(1).upper() in STATE_CODES:
        return code.group(1).upper(), zip_code

    if not zip_code:
        return "", ""
    prefix = int(zip_code[:3])
    for state, ranges in ZIP_PREFIX_RANGES:
        if any(start <= prefix <= end for start, end in ranges):
            return state, zip_code
    return "", zip_code
