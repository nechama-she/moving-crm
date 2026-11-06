"""The Interstate Bill of Lading: the company's form, drawn to match it box for box, filled from the signed estimate,
with the terms from the company's Bill of Lading documents on the back."""
from io import BytesIO
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

LEFT, MIDDLE, RIGHT, TOP, BOTTOM = 36, 303, 576, 776, 22
BLACK = colors.black

# The form's wording, as printed; {company} is the company's name.
FORM_OF_PAYMENT = ('<b>A. FORM OF PAYMENT:</b> Upon booking, up to 50% deposit is required to be paid in the form of Visa, MasterCard, '
    'Cashier&rsquo;s Check. Prior to pickup 50% of the balance is due in the form of Cash, Money Order, Certified Check. At delivery the '
    'balance is due prior to unloading in the form of Post Office Money Order or Cash only. {company} reserves the right to collect up to '
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
    'as first available for delivery.<br/><b>Filing of claims:</b> {company} shall not be liable for the loss or damage of the goods unless '
    'claim is made in writing supported by proof of ownership, value, and weight. All outstanding money due to {company} must be paid in '
    'full before any claim can be made. Claims must be filed withing 9 months of delivery or demand thereof is refused ad must be '
    'limited to the destination descriptions of damages for each item on the inventory logs. All damages and missing items must be noted on '
    'the inventory logs. Damage indications must specify each item damaged at the time of delivery. Shipper or agent has full authority to '
    'order services and enter into agreement.<br/><b>Special Services:</b> Shipper will be notified by {company} of fnial charges prior to '
    'delivery and while in transit. On interstate moves and 18 wheelr may be used to deliver the property. If destination address does not '
    'have access for an 18 wheeler the shipper will be required to pay for shuttle service. Full re-handling/delivery fees are applied when '
    '{company} must take a second attempt to deliver the property if for any reason the shipper did not accept delivery on the first '
    'attampt. For all estimates there may be additional charges for flights of stairs, elevators, extra drop-offs or pick-ups, re-delivery, '
    'long carries, and shuttles for residences in restrictive areas.')
ACKNOWLEDGE = ('<b>I acknowledge, have read, and agree to all the terms and conditions on both sides of this bill of lading contract and '
    'order for service. I have received the arbitration information and the booklet: Your Rights and Responsibilities When you Move and '
    'pamphlet Ready to Move. I agree to pay for the total charges for moving services. I approved the total estimated charges prior to the '
    'moving services beginning.</b>')
MAXIMUM_DUE = ('<b>Notice of Maximum amount due upon delivery:</b> Final charges will be based on actual weight or cubic feet of property '
    'and services provided or time. Maximum amount to be paid to {company} and demanded at destination is the amountof the last issued '
    'non-binding estimate plus 10%; or 100% of the binding estimate; plus post contract services; any remaining balances due will be billed '
    'after 30 days of delivery. <b>Payment in full of all charges is due before unloading.</b> Fees for post contract services must be paid '
    'in advance of delivery and prior to unloading. There may be a fuel surcharge on all orders. <b>Conversion formula:</b> Conversion from '
    'weight to cubic feet, or vice versa, is a multiple of 7 to perform the calcualtions for the total charges.')
DELIVERY = ('The shipper hereby acknowledges that the shipment was received in apparently good conditiond except as noted on the invntory '
    'list/s. Furthermore, the shipper acknowledges that all the services that were ordered have been performed, have been fully satisfied, '
    'and the truck was inspected and nothing has been left behind. Shipper and/or agent has full authority to accept the shipment and enter '
    'into this agreement.')
# Optional accessorial services, as on the form; left for circling by hand.
SERVICES = [['STORAGE', 'SHUTTLE', 'STAIRS', 'MOTORCYCLE'], ['LONG CARRY', 'PIANO', 'FULL VALUATION', 'EXTRA INSURANCE'],
            ['BULKY', 'OTHER:__________', 'P.G.S. pickup/delivery', '']]


def _split_address(address):
    """The street on one line, and the city, state and ZIP on the next, as the form asks. Without a street (a house
    number and name, such as only a ZIP code or a city), it all goes on the city, state and ZIP line."""
    address = re.sub(r',?\s*(USA|United States)\s*$', '', (address or '').strip(), flags=re.I)
    street, _, rest = address.partition(',')
    if not re.match(r'\d[\w-]*\s+\D', street.strip()):
        return '', address
    return street.strip(), rest.strip()


class _Form:
    """Drawing helpers for the form's boxes, bars and wrapped text."""
    def __init__(self, canvas, company):
        self.c, self.company = canvas, company

    def text(self, x, y, value, size=7, bold=False, color=BLACK):
        self.c.setFillColor(color)
        self.c.setFont('Helvetica-Bold' if bold else 'Helvetica', size)
        self.c.drawString(x, y, str(value or ''))

    def box(self, x, top, width, height):
        self.c.setStrokeColor(BLACK)
        self.c.setLineWidth(.6)
        self.c.rect(x, top - height, width, height)

    def bar(self, x, top, width, height, title, size=7.5):
        self.c.setFillColor(BLACK)
        self.c.rect(x, top - height, width, height, fill=1, stroke=0)
        self.c.setFillColor(colors.white)
        self.c.setFont('Helvetica-Bold', size)
        self.c.drawCentredString(x + width / 2, top - height + (height - size) / 2 + 1.2, title)
        return top - height

    def paragraph(self, x, top, width, html, size=5.6, bold=False):
        style = ParagraphStyle('Form', fontName='Helvetica-Bold' if bold else 'Helvetica', fontSize=size,
                               leading=size * 1.16, alignment=TA_JUSTIFY)
        flowable = Paragraph(html.replace('{company}', escape(self.company)), style)
        _, height = flowable.wrapOn(self.c, width, 1000)
        flowable.drawOn(self.c, x, top - height)
        return top - height

    def labeled(self, x, top, width, height, label, value='', size=8):
        """A box with its small label, and the value after it."""
        self.box(x, top, width, height)
        self.text(x + 2, top - height + (height - 6) / 2 + 1, label, 6, bold=True)
        if value:
            self.text(x + 4 + self.c.stringWidth(label, 'Helvetica-Bold', 6), top - height + (height - size) / 2 + 1, value, size)

    def signature(self, x, top, width, height, signature):
        """The drawn signature inside a box's area."""
        self.c.setStrokeColor(colors.HexColor('#15354b'))
        self.c.setLineWidth(1.1)
        box_w, box_h = min(width, height * 4), height - 6
        for stroke in signature['strokes']:
            points = [(x + px * box_w, top - 3 - py * box_h) for px, py in stroke]
            if len(points) > 1:
                path = self.c.beginPath()
                path.moveTo(*points[0])
                for point in points[1:]:
                    path.lineTo(*point)
                self.c.drawPath(path, stroke=1, fill=0)


# The customer's unsigned signature spots are links marked with this text and the spot's number; the viewer finds
# them to open that spot's signing there.
SIGN_HERE = 'sign-here'
# The customer signs each spot on its own, top to bottom: the customer's signature, then the shipper's.
SIGN_SPOTS = 2


def _signature_row(form, top, label, signatures, height=24, spot=None, date_label='Date:'):
    """A signature line and its date, as the form's yellow spots; spot: the customer's spot number, signed from signatures."""
    form.box(LEFT, top, 190, height)
    form.box(LEFT + 190, top, MIDDLE - LEFT - 190, height)
    form.text(LEFT + 2, top - height + 3, label, 6, bold=True)
    form.text(LEFT + 192, top - 8, date_label, 6, bold=True)
    if spot is None:
        return top - height
    signature = signatures.get(spot)
    if signature:
        form.signature(LEFT + 70, top, 115, height, signature)
        form.text(LEFT + 192, top - height + 4, signature['date'], 7.5)
    else:
        form.c.linkRect(f'{SIGN_HERE} {spot}', SIGN_HERE, (LEFT + 70, top - height, LEFT + 188, top), thickness=0)
    return top - height


def _front(canvas, company, values, signatures, logo):
    form = _Form(canvas, company.get('name') or '')
    if len(signatures) < SIGN_SPOTS:
        canvas.bookmarkPage(SIGN_HERE)
    # Header: the company, its logo, the order boxes and the title.
    street, city = _split_address(company.get('office_address'))
    lines = [company.get('name'), street, city, f"Phone Number: {company.get('phone') or ''}", '',
             f"USDOT No.: {company.get('dot_number') or ''}", f"ICC/MC No.: {values.get('mc_number') or ''}"]
    for index, line in enumerate(lines):
        form.text(LEFT, TOP - 4 - index * 10.5, line, 8.5, bold=index == 0)
    if logo is not None:
        width, height = logo.wrapOn(canvas, 100, 80)
        logo.drawOn(canvas, 306 - width / 2, TOP - 4 - height)
    order_top = TOP + 6
    for label, value in (('Order No.:', values.get('order_number')), ('Pick Up Date:', values.get('pickup_date')),
                         ('1st date available for delivery:', ''), ('Vehicle ID:', '')):
        form.box(426, order_top, RIGHT - 426, 22)
        form.text(428, order_top - 7, label, 6)
        form.text(430, order_top - 18, value, 8)
        order_top -= 22
    canvas.setFont('Helvetica-Bold', 14)
    canvas.drawCentredString(306, 680, 'INTERSTATE BILL OF LADING CONTRACT')
    # Origin, filled from the move; the destination is left empty.
    top = 674
    for x, title, filled in ((LEFT, 'ORIGIN', True), (MIDDLE + 6, 'DESTINATION', False)):
        width = MIDDLE - LEFT if x == LEFT else RIGHT - x
        row = form.bar(x, top, width, 14, title, 9)
        street, city = _split_address(values.get('pickup_address')) if filled else ('', '')
        for label, value in (('NAME:', values.get('customer_name') if filled else ''), ('ADDRESS:', street), ('CITY/STATE/ZIP:', city),
                             ('PHONE:', values.get('customer_phone') if filled else '')):
            form.labeled(x, row, width, 15, label, value)
            row -= 15
    top -= 14 + 60 + 4
    # Filled in by hand; the boxes split as on the printed form.
    for x, width, label in ((LEFT, 177, 'Agent name:'), (LEFT + 177, 185, 'Address:'), (LEFT + 362, 118, 'Phone:'), (LEFT + 480, RIGHT - LEFT - 480, 'US DOT No.:')):
        form.labeled(x, top, width, 12, label)
    column = top - 16
    # Left column: payment, estimated charges, services, disclosures and the shipper's acknowledgment.
    width = MIDDLE - LEFT
    left = form.paragraph(LEFT + 2, column, width - 4, FORM_OF_PAYMENT, 6.1) - 4
    left = _signature_row(form, left, "Customer's Signatrue", signatures, spot=0, date_label='Date') - 3
    left = form.paragraph(LEFT + 2, left, width - 4, ESTIMATED_CHARGES, 5.9) - 4
    for label, value, note in (('TOTAL ESTIMATED CHARGES:', values.get('total_estimate'), 'Estimates are not guaranteed per 49 CFR §375.403(6)'),
                               ('MINIMUM Cu.Ft. / lbs.:', values.get('minimum_cuft'), ''),
                               ('TOTAL MINIMUM CHARGE:', values.get('minimum_charge'), '')):
        form.box(LEFT, left, 170, 20)
        form.box(LEFT + 170, left, width - 170, 20)
        canvas.setFont('Helvetica-Bold', 7.5)
        canvas.drawCentredString(LEFT + 85, left - (11 if note else 13), label)
        if note:
            form.text(LEFT + 12, left - 17, note, 4.6)
        form.text(LEFT + 174, left - 13, value if value else ('$' if 'CHARGE' in label else ''), 8.5)
        left -= 20
    left -= 2
    form.text(LEFT, left - 7, 'C. OPTIONAL ACCESSORIAL SERVICES ORDERED(Round off applied services):', 6.2, bold=True)
    left -= 10
    for row in SERVICES:
        for index, label in enumerate(row):
            form.text(LEFT + index * (width / 4) + 2, left - 7, label, 6)
        left -= 9.5
    left = form.paragraph(LEFT + 2, left - 2, width - 4, DISCLOSURES, 5.65) - 5
    left = form.bar(LEFT, left, width, 13, 'SIGN AT LEAST 3 DAYS BEFORE PICKUP DATE:', 7.5) - 2
    left = form.paragraph(LEFT + 2, left, width - 4, ACKNOWLEDGE, 6.3) - 4
    left = _signature_row(form, left, 'Shipper/Agent/Representative:', signatures, spot=1)
    left = _signature_row(form, left, f"{company.get('name') or ''} representative:", signatures, 18)
    # Right column: the actual charges, filled in on moving day.
    x, width = MIDDLE + 6, RIGHT - MIDDLE - 6
    canvas.setFont('Helvetica-Bold', 7.5)
    canvas.drawCentredString(x + width / 2, column - 7, 'SUMMARY OF ACTUAL CHARGES')
    right = column - 10
    def rows(title, lines, height=10.2):
        nonlocal right
        right = form.bar(x, right, width, 10.5, title)
        for line in lines:
            # A line is its label, or (label, what the amount box says instead of $).
            line, amount = line if isinstance(line, tuple) else (line, '$')
            form.box(x, right, width - 40, height)
            form.box(x + width - 40, right, 40, height)
            form.text(x + 2, right - height + 3.2, line, 6)
            form.text(x + width - 38, right - height + 3.2, amount, 6 if amount == '$' else 4.4, bold=amount != '$')
            right -= height
    rows('WEIGHT CHARGES:', ['Base: _______________ lbs. @ $ _______________ per lbs.',
                             'Additional: _______________ lbs. @ $ _______________ per lbs.',
                             'Additional: _______________ lbs. @ $ _______________ per lbs.'])
    rows('CUBIC FEET CHARGES', ['Base: ______________ cu.ft. @ $______________ per cu.ft.',
                                'Additional: ______________ cu.ft. @ $______________ per cu.ft.',
                                'Additional: ______________ cu.ft. @ $______________ per cu.ft.'])
    rows('HOURLY CHARGES:', [('Part One: ___________ Start Time ___________ End Time ___________ Hours', ''),
                             ('Part Two: ___________ Start Time ___________ End Time ___________ Hours', ''),
                             '___________ hrs. ___________ men ___________ Trucks @ $ ___________ /hr',
                             '___________ hrs. ___________ men ___________ Trucks @ $ ___________ /hr'])
    rows('PACKING MAERIALS AND LABOR:', ['Total Material and Packing (See attached materials price list):', 'Full Packing Service:', 'Other:'])
    rows('OTHER SERVICES', ['Fuel surcharge:', 'Stairs: $ _________ origin $ _________ destination',
                            'Long Carry: $ _________ origin $ _________ destination', 'Shuttle: $ _________ origin $ _________ destination', 'Misc. Bulky Item:', 'Split pickup/delivery or extra stop-off',
                            'P.G.S. pickup/delivery service:', ('Valuation at $0.60 per pound per item:', 'INCLUDED FREE'), 'Other:'])
    rows('STORAGE CHARGES', ['______ Days @ cu.ft. ______ @ $ ______ per cu.ft. per month', 'Other:'])
    right = form.paragraph(x + 2, right - 3, width - 4, MAXIMUM_DUE, 5.5) - 3
    right = form.bar(x, right, width, 10.5, 'SUMMARY OF CHARGES:')
    for label in ('GRAND TOTAL:', 'PARTIAL PAYMENT:', 'PARTIAL PAYMENT:', '', '', 'BALANCE DUE:', '', '', 'PRICE ADJUSTMENT:', 'NEW BALANCE DUE IN 30 DAYS:'):
        form.box(x, right, width - 40, 9.6)
        form.box(x + width - 40, right, 40, 9.6)
        if label:
            form.text(x + (2 if label.startswith('P') and 'ADJUST' not in label else width - 42 - canvas.stringWidth(label, 'Helvetica-Bold', 6)),
                      right - 7.2, label, 6, bold=True)
        form.text(x + width - 38, right - 7.2, '$', 6)
        right -= 9.6
    right = form.bar(x, right - 3, width, 10.5, 'DELIVERY ACKNOWLEDGEMENT:')
    right = form.paragraph(x + 2, right - 2, width - 4, DELIVERY, 5.5, bold=True) - 3
    form.box(x, right, width - 60, 20)
    form.box(x + width - 60, right, 60, 20)
    form.text(x + 2, right - 17, 'Shipper/Agent/Representative:', 6, bold=True)
    form.text(x + width - 58, right - 7, 'Date:', 6, bold=True)
    return left, right - 20


def build_bill_of_lading_pdf(company, values, documents, signatures=None):
    """The form, filled from the signed estimate (values), then the terms from settings (documents) on the back.
    signatures: {spot number: the customer's drawn signature with its 'date'} for the spots signed so far."""
    signatures = signatures or {}
    from company_documents import pdf_document_flowables
    from inventory_pdf import company_logo_image
    logo = company_logo_image(company.get('logo'))
    # The back: the terms, small and dense, as the printed form's reverse side.
    body = ParagraphStyle('BillOfLadingBody', fontName='Helvetica', fontSize=5.6, leading=6.6, alignment=TA_JUSTIFY, spaceAfter=0)
    heading = ParagraphStyle('BillOfLadingHeading', parent=body, fontName='Helvetica-Bold', fontSize=7, leading=9, alignment=0)
    story = [PageBreak()]
    for document in documents:
        # The printed back starts with SECTION 1, without the document's title (its first two flowables).
        for flowable in pdf_document_flowables(document, body, heading)[2:]:
            if isinstance(flowable, Paragraph):
                flowable.style = ParagraphStyle('Tight', parent=flowable.style, spaceAfter=2.5)
            story.append(flowable)
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=letter, leftMargin=LEFT, rightMargin=612 - RIGHT, topMargin=24, bottomMargin=BOTTOM,
                            title='Interstate Bill of Lading Contract', author=company.get('name') or '')
    doc.build(story, onFirstPage=lambda canvas, _: _front(canvas, company, values, signatures, logo))
    return output.getvalue()
