"""The Bill of Lading's front page as each company sets it (bill_of_lading_blocks): its boxes, paragraphs, bars, tables
and signature lines, in order, per area of the page. DEFAULT_BLOCKS is the form every company starts with; reading an
uploaded PDF fills its paragraphs' wording and the back's terms once."""
import hashlib
import json
import re
from xml.sax.saxutils import escape

# Where a block goes, top to bottom in each: the order boxes (top right), the title, the origin and destination boxes,
# the agent row, and the page's two columns.
AREAS = ('company', 'order', 'header', 'origin', 'destination', 'agent', 'left', 'right')
# What a block is, and the areas it can go in.
KINDS = {'field': {'order', 'origin', 'destination', 'agent'}, 'title': {'header'}, 'bar': {'origin', 'destination', 'left', 'right'},
         'paragraph': {'left', 'right'}, 'signature': {'left', 'right'}, 'total': {'left'}, 'heading': {'left', 'company'}, 'line': {'company'},
         'option': {'left'}, 'caption': {'right'}, 'charge': {'right'}, 'summary': {'right'}}
# Details a box can be filled with besides the move's (company_documents.MOVE_FIELDS): the addresses' two lines.
ADDRESS_FILLS = {'pickup_street': 'Pickup street', 'pickup_city': 'Pickup city, state and ZIP',
                 'delivery_street': 'Delivery street', 'delivery_city': 'Delivery city, state and ZIP'}
# The columns a block has, as saved and compared.
FIELDS = ('area', 'kind', 'title', 'text', 'fill', 'note', 'align', 'size', 'height', 'width', 'space', 'spot')
COMPANY = '{{company_name}}'
# The company's details a part's words can show, filled from the company when the form is drawn.
COMPANY_DETAILS = {'company_name': 'Company name', 'company_office_street': 'Office street', 'company_office_city': 'Office city, state and ZIP',
                   'company_phone': 'Phone number', 'company_dot_number': 'USDOT number', 'company_mc_number': 'MC number'}


def block(area, kind, title='', text='', fill='', note='', align='', size=None, height=None, width=None, space=0.0, spot=None):
    return {'area': area, 'kind': kind, 'title': title, 'text': text, 'fill': fill, 'note': note, 'align': align,
            'size': size, 'height': height, 'width': width, 'space': space, 'spot': spot}


FORM_OF_PAYMENT = ('<b>A. FORM OF PAYMENT:</b> Upon booking, up to 50% deposit is required to be paid in the form of Visa, MasterCard, '
    'Cashier&rsquo;s Check. Prior to pickup 50% of the balance is due in the form of Cash, Money Order, Certified Check. At delivery the '
    'balance is due prior to unloading in the form of Post Office Money Order or Cash only. {{company_name}} reserves the right to collect up to '
    '70% of balance due prior to the goods leaving the origin state. <b>Payment in FULL of all charges is required before delivery truck '
    'is opened and before unloading.</b>')
ESTIMATED_CHARGES = ('<b>B. TOTAL ESTIMATED CHARGES AND MINIMUM CHARGES:</b> By this reference bill of lading and order for service and '
    'all their terms, conditions, and estimated charges are combined and incorporated by reference in accordance with 49 CFR '
    '&sect;375.505(b)(17). The total estimated charges for service is not guarantee of the final total actual charges - which may increase '
    'or decrease based upon actual services performed, quantity of item shipped, accessorial services, destination services, and/or weight '
    'of shipment. Carrier may use agents/independent sub-contractors on all orders. Unless customer purchased an &ldquo;exclusive use of '
    'the vehicle&rdquo; option, there is no guarantee that the property will not be temporarily stored or offloaded and reloaded onto a '
    'different vehicle then performed pickup and consolidated with other shipments or transported by a subcontractor.')
DISCLOSURES = ('<b>C. DISCLOSURES:</b> Packing materials/labor are not included and will be charged extra per items ordered on the packing '
    'materials list. The space reservation option, if selected by shipper, will be used to determine line haul charges. Bill of Lading is '
    'the controlling shipping contract. All charges including additional services will be charged based on the full tariff rates. See '
    'reverse side for important information including arbitration information. Tariff is available for inspection upon reasonable request '
    'by calling carrier.<br/><b>Agreed pickup/deliery periods:</b> Guaranteed pickup and delivery dates are an optional service available '
    'for purhcase. Pickup and delivery dates are not guaranteed unless the optional Premium Guaranteed Service (P.G.S) is purchased. In '
    'Compliance with 49 CFR Section &sect;375.505(b)(6) the non-guaranteed <b>Standard Service (S.S.) delivery &ldquo;period in time&rdquo; '
    'is up to thirty (30) business weekdays, not including storage time, beginning on the first date indicated as available for delivery '
    '(not the date of pickup).</b> The date above indicated as &ldquo;1st available for delivery&rdquo; is first date of the delivery period '
    'of time and not the promised delivery date. Per diem delay rate is $30.00 (thirty dollars) per business weekday. Business days do not '
    'include holidays or weekends. Unless P.G.S. is purchased, estimated delivery period is up to thirty business days from date indicated '
    'as first available for delivery.<br/><b>Filing of claims:</b> {{company_name}} shall not be liable for the loss or damage of the goods unless '
    'claim is made in writing supported by proof of ownership, value, and weight. All outstanding money due to {{company_name}} must be paid in '
    'full before any claim can be made. Claims must be filed withing 9 months of delivery or demand thereof is refused ad must be '
    'limited to the destination descriptions of damages for each item on the inventory logs. All damages and missing items must be noted on '
    'the inventory logs. Damage indications must specify each item damaged at the time of delivery. Shipper or agent has full authority to '
    'order services and enter into agreement.<br/><b>Special Services:</b> Shipper will be notified by {{company_name}} of fnial charges prior to '
    'delivery and while in transit. On interstate moves and 18 wheelr may be used to deliver the property. If destination address does not '
    'have access for an 18 wheeler the shipper will be required to pay for shuttle service. Full re-handling/delivery fees are applied when '
    '{{company_name}} must take a second attempt to deliver the property if for any reason the shipper did not accept delivery on the first '
    'attampt. For all estimates there may be additional charges for flights of stairs, elevators, extra drop-offs or pick-ups, re-delivery, '
    'long carries, and shuttles for residences in restrictive areas.')
ACKNOWLEDGE = ('<b>I acknowledge, have read, and agree to all the terms and conditions on both sides of this bill of lading contract and '
    'order for service. I have received the arbitration information and the booklet: Your Rights and Responsibilities When you Move and '
    'pamphlet Ready to Move. I agree to pay for the total charges for moving services. I approved the total estimated charges prior to the '
    'moving services beginning.</b>')
MAXIMUM_DUE = ('<b>Notice of Maximum amount due upon delivery:</b> Final charges will be based on actual weight or cubic feet of property '
    'and services provided or time. Maximum amount to be paid to {{company_name}} and demanded at destination is the amountof the last issued '
    'non-binding estimate plus 10%; or 100% of the binding estimate; plus post contract services; any remaining balances due will be billed '
    'after 30 days of delivery. <b>Payment in full of all charges is due before unloading.</b> Fees for post contract services must be paid '
    'in advance of delivery and prior to unloading. There may be a fuel surcharge on all orders. <b>Conversion formula:</b> Conversion from '
    'weight to cubic feet, or vice versa, is a multiple of 7 to perform the calcualtions for the total charges.')
DELIVERY = ('<b>The shipper hereby acknowledges that the shipment was received in apparently good conditiond except as noted on the invntory '
    'list/s. Furthermore, the shipper acknowledges that all the services that were ordered have been performed, have been fully satisfied, '
    'and the truck was inspected and nothing has been left behind. Shipper and/or agent has full authority to accept the shipment and enter '
    'into this agreement.</b>')


def _charges(title, lines, last_space=0.0):
    rows = [block('right', 'bar', title, height=10.5)]
    for index, line in enumerate(lines):
        label, amount = line if isinstance(line, tuple) else (line, '$')
        rows.append(block('right', 'charge', label, note=amount, height=10.2, space=last_space if index == len(lines) - 1 else 0.0))
    return rows


# The form as the CRM drew it before companies could set their own: every company starts from it.
DEFAULT_BLOCKS = [
    block('company', 'heading', COMPANY, size=8.5),
    *[block('company', 'line', words, size=8.5) for words in ('{{company_office_street}}', '{{company_office_city}}',
                                                             'Phone Number: {{company_phone}}', '', 'USDOT No.: {{company_dot_number}}',
                                                             'ICC/MC No.: {{company_mc_number}}')],
    *[block('order', 'field', label, fill=fill) for label, fill in (('Order No.:', 'order_number'), ('Pick Up Date:', 'pickup_date'),
                                                                     ('1st date available for delivery:', ''), ('Vehicle ID:', ''))],
    block('header', 'title', 'INTERSTATE BILL OF LADING CONTRACT', size=14),
    block('origin', 'bar', 'ORIGIN', size=9),
    *[block('origin', 'field', label, fill=fill) for label, fill in (('NAME:', 'customer_name'), ('ADDRESS:', 'pickup_street'),
                                                                      ('CITY/STATE/ZIP:', 'pickup_city'), ('PHONE:', 'customer_phone'))],
    block('destination', 'bar', 'DESTINATION', size=9),
    *[block('destination', 'field', label) for label in ('NAME:', 'ADDRESS:', 'CITY/STATE/ZIP:', 'PHONE:')],
    *[block('agent', 'field', label, width=width) for label, width in (('Agent name:', 177), ('Address:', 185), ('Phone:', 118), ('US DOT No.:', None))],
    block('left', 'paragraph', text=FORM_OF_PAYMENT, size=6.1, space=4),
    block('left', 'signature', "Customer's Signatrue", note='Date', height=24, spot=1, space=3),
    block('left', 'paragraph', text=ESTIMATED_CHARGES, size=5.9, space=4),
    # A total's text: what its box shows without a value.
    block('left', 'total', 'TOTAL ESTIMATED CHARGES:', text='$', fill='total_estimate', note='Estimates are not guaranteed per 49 CFR §375.403(6)'),
    block('left', 'total', 'MINIMUM Cu.Ft. / lbs.:', fill='minimum_cuft'),
    block('left', 'total', 'TOTAL MINIMUM CHARGE:', text='$', fill='minimum_charge', space=2),
    block('left', 'heading', 'C. OPTIONAL ACCESSORIAL SERVICES ORDERED(Round off applied services):', size=6.2),
    *[block('left', 'option', label, space=2 if label == 'P.G.S. pickup/delivery' else 0.0)
      for label in ('STORAGE', 'SHUTTLE', 'STAIRS', 'MOTORCYCLE', 'LONG CARRY', 'PIANO', 'FULL VALUATION', 'EXTRA INSURANCE',
                    'BULKY', 'OTHER:__________', 'P.G.S. pickup/delivery')],
    block('left', 'paragraph', text=DISCLOSURES, size=5.65, space=5),
    block('left', 'bar', 'SIGN AT LEAST 3 DAYS BEFORE PICKUP DATE:', size=7.5, height=13, space=2),
    block('left', 'paragraph', text=ACKNOWLEDGE, size=6.3, space=4),
    block('left', 'signature', 'Shipper/Agent/Representative:', note='Date:', height=24, spot=2),
    block('left', 'signature', f'{COMPANY} representative:', note='Date:', height=18),
    block('right', 'caption', 'SUMMARY OF ACTUAL CHARGES'),
    *_charges('WEIGHT CHARGES:', ['Base: _______________ lbs. @ $ _______________ per lbs.',
                                  'Additional: _______________ lbs. @ $ _______________ per lbs.',
                                  'Additional: _______________ lbs. @ $ _______________ per lbs.']),
    *_charges('CUBIC FEET CHARGES', ['Base: ______________ cu.ft. @ $______________ per cu.ft.',
                                     'Additional: ______________ cu.ft. @ $______________ per cu.ft.',
                                     'Additional: ______________ cu.ft. @ $______________ per cu.ft.']),
    *_charges('HOURLY CHARGES:', [('Part One: ___________ Start Time ___________ End Time ___________ Hours', ''),
                                  ('Part Two: ___________ Start Time ___________ End Time ___________ Hours', ''),
                                  '___________ hrs. ___________ men ___________ Trucks @ $ ___________ /hr',
                                  '___________ hrs. ___________ men ___________ Trucks @ $ ___________ /hr']),
    *_charges('PACKING MAERIALS AND LABOR:', ['Total Material and Packing (See attached materials price list):', 'Full Packing Service:', 'Other:']),
    *_charges('OTHER SERVICES', ['Fuel surcharge:', 'Stairs: $ _________ origin $ _________ destination',
                                 'Long Carry: $ _________ origin $ _________ destination', 'Shuttle: $ _________ origin $ _________ destination',
                                 'Misc. Bulky Item:', 'Split pickup/delivery or extra stop-off', 'P.G.S. pickup/delivery service:',
                                 ('Valuation at $0.60 per pound per item:', 'INCLUDED FREE'), 'Other:']),
    *_charges('STORAGE CHARGES', ['______ Days @ cu.ft. ______ @ $ ______ per cu.ft. per month', 'Other:'], last_space=3),
    block('right', 'paragraph', text=MAXIMUM_DUE, size=5.5, space=3),
    block('right', 'bar', 'SUMMARY OF CHARGES:', height=10.5),
    *[block('right', 'summary', label, align='left' if label.startswith('P') and 'ADJUST' not in label else 'right',
            space=3 if index == 9 else 0.0)
      for index, label in enumerate(('GRAND TOTAL:', 'PARTIAL PAYMENT:', 'PARTIAL PAYMENT:', '', '', 'BALANCE DUE:', '', '',
                                     'PRICE ADJUSTMENT:', 'NEW BALANCE DUE IN 30 DAYS:'))],
    block('right', 'bar', 'DELIVERY ACKNOWLEDGEMENT:', height=10.5, space=2),
    block('right', 'paragraph', text=DELIVERY, size=5.5, space=3),
    block('right', 'signature', 'Shipper/Agent/Representative:', note='Date:', height=20),
]


def form_digest(blocks):
    """A fingerprint of a form's blocks, for the Bill of Lading's version: the same for the same wording and boxes
    (numbers compared as numbers: the database gives 4.0 for 4)."""
    number = lambda value: float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value
    return hashlib.sha256(json.dumps([[number(row.get(field)) for field in FIELDS] for row in blocks], default=str).encode()).hexdigest()


DEFAULT_DIGEST = form_digest(DEFAULT_BLOCKS)


# ---- Reading a mover's PDF once, for the form's wording and the back's terms ------------------------------------------------

# Words that say nothing about which paragraph a heading is.
_COMMON = {'a', 'b', 'c', 'd', 'e', 'f', 'and', 'the', 'of', 'for', 'to', 'upon', 'on', 'in', 'terms', 'agreed'}


def _words(text):
    return {word for word in re.findall(r'[a-z]+', text.lower()) if word not in _COMMON}


def _clean(text):
    """A paragraph's lines joined back into one: words broken at a line's end rejoined, spacing evened."""
    text = re.sub(r'-\n(?=[a-z])', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def _with_company(text, company_name):
    return text.replace(company_name, COMPANY) if company_name else text


# A front-page paragraph begins with its heading: a lettered heading ("A. FORM / TERMS OF PAYMENT:"), or one of these.
_HEADING = re.compile(r'(?m)^\s*((?:[A-Z]\.\s+[A-Z][A-Z /&,.\'’-]{3,}?|SIGN AT LEAST[^:\n]*|Notice of Maximum amount due upon delivery|'
                      r'DELIVERY ACKNOWLEDGEMENT|SUMMARY OF CHARGES|SUMMARY OF ACTUAL CHARGES[^:\n]*)\s*:+)')
# Where a paragraph's text stops before the next heading: the form's own boxes under it.
_STOP = re.compile(r"(?m)^\s*(?:Customer[’']?s signature|TOTAL ESTIMATED CHARGES:|[A-Z][\w ,.&’']+ (?:representative )?signature)")


def _front_paragraphs(text):
    """The front page's paragraphs: {heading: its text}, from the PDF's text."""
    found = list(_HEADING.finditer(text))
    paragraphs = {}
    for index, match in enumerate(found):
        end = found[index + 1].start() if index + 1 < len(found) else len(text)
        body = text[match.end():end]
        stop = _STOP.search(body)
        body = _clean(body[:stop.start()] if stop else body)
        if body:
            paragraphs[_clean(match.group(1)).rstrip(':').strip() + ':'] = body
    return paragraphs


def _paragraph_heading(block_text):
    """A paragraph block's heading: its first bold words, or the bar above it (the acknowledgment's)."""
    match = re.match(r'\s*<b>(.*?)</b>', block_text)
    return re.sub(r'<[^>]+>', '', match.group(1)) if match else ''


def read_upload(pdf, company_name, blocks):
    """Once, from a mover's PDF: its front paragraphs' wording into the form's matching paragraph blocks (a copy of
    blocks), its SECTION terms as the back's text, and the front paragraphs no block matched. Raises ValueError when
    the PDF has no text to read (a scan)."""
    from io import BytesIO
    from pypdf import PdfReader
    pages = [page.extract_text() or '' for page in PdfReader(BytesIO(pdf)).pages]
    if not any(page.strip() for page in pages):
        raise ValueError('This PDF has no text to read (a scanned page). Type the wording in instead.')
    whole = '\n'.join(pages)
    start = re.search(r'(?m)^\s*SECTION\s+1\b', whole)
    front, back = (whole[:start.start()], whole[start.start():]) if start else (whole, '')
    sections = re.split(r'(?m)^\s*(SECTION\s+\d+\s*[:.])', back)
    terms = ''.join(f'<p><strong>{escape(_clean(head))}</strong> {escape(_with_company(_clean(body), company_name))}</p>'
                    for head, body in zip(sections[1::2], sections[2::2]) if _clean(body))
    paragraphs = _front_paragraphs(front)
    used = set()
    result = [dict(row) for row in blocks]
    previous = None
    for row in result:
        if row['kind'] == 'paragraph':
            # The acknowledgment's heading is the bar above it ("SIGN AT LEAST 3 DAYS BEFORE PICKUP DATE:").
            own = _paragraph_heading(row['text']) or (previous['title'] if previous and previous['kind'] == 'bar' else '')
            wanted = _words(own)
            best = max(((len(wanted & _words(heading)) / max(1, len(wanted | _words(heading))), heading)
                        for heading in paragraphs if heading not in used), default=(0, None))
            if best[1] and best[0] >= .34:
                heading = best[1]
                used.add(heading)
                body = escape(_with_company(paragraphs[heading], company_name))
                # A paragraph that had its heading in bold keeps the mover's heading, in bold.
                row['text'] = (f'<b>{escape(heading)}</b> ' if _paragraph_heading(row['text']) else '') + body
        previous = row
    return result, terms, [heading for heading in paragraphs if heading not in used]
