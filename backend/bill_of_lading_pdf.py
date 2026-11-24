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

from bill_of_lading_form import ADDRESS_FILLS, AREAS

LEFT, MIDDLE, RIGHT, TOP, BOTTOM = 36, 303, 576, 776, 22
BLACK = colors.black

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
        flowable = Paragraph(html, style)
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


def _value(values, fill):
    """What a box shows: the move's detail, or one of its addresses' two lines."""
    if fill in ADDRESS_FILLS:
        street, city = _split_address(values.get(fill.split('_')[0] + '_address'))
        return street if fill.endswith('street') else city
    return values.get(fill) or '' if fill else ''


def _front(canvas, company, values, signatures, logo, blocks):
    """The front page, drawn from the company's form (blocks) area by area. Returns where its columns end."""
    name = company.get('name') or ''
    form = _Form(canvas, name)
    street, city = _split_address(company.get('office_address'))
    details = {'company_name': name, 'company_office_street': street, 'company_office_city': city,
               'company_phone': company.get('phone') or '', 'company_dot_number': company.get('dot_number') or '',
               'company_mc_number': values.get('mc_number') or ''}
    # The company's details in a part's words; escaped in a paragraph, whose words are formatting.
    fill = lambda value, html=False: re.sub(r'\{\{\s*(company_[a-z_]+)\s*\}\}', lambda match: (
        escape(details.get(match.group(1), '')) if html else details.get(match.group(1), '')), value or '')
    label = fill
    if len(signatures) < SIGN_SPOTS:
        canvas.bookmarkPage(SIGN_HERE)
    areas = {area: [row for row in blocks if row['area'] == area] for area in AREAS}
    # Header: the company's lines, its logo, the order boxes and the title.
    for index, row in enumerate(areas['company']):
        form.text(LEFT, TOP - 4 - index * 10.5, label(row['title']), row['size'] or 8.5, bold=row['kind'] == 'heading')
    if logo is not None:
        width, height = logo.wrapOn(canvas, 100, 80)
        logo.drawOn(canvas, 306 - width / 2, TOP - 4 - height)
    order_top = TOP + 6
    for row in areas['order']:
        form.box(426, order_top, RIGHT - 426, 22)
        form.text(428, order_top - 7, label(row['title']), 6)
        form.text(430, order_top - 18, _value(values, row['fill']), 8)
        order_top -= 22
    for index, row in enumerate(areas['header']):
        canvas.setFont('Helvetica-Bold', row['size'] or 14)
        canvas.drawCentredString(306, 680 - index * 16, label(row['title']))
    # Origin and destination, side by side: a bar, then its boxes.
    top = 674
    tallest = 0
    for x, area in ((LEFT, 'origin'), (MIDDLE + 6, 'destination')):
        width = MIDDLE - LEFT if x == LEFT else RIGHT - x
        row_top = top
        for row in areas[area]:
            if row['kind'] == 'bar':
                row_top = form.bar(x, row_top, width, 14, label(row['title']), row['size'] or 9)
            else:
                form.labeled(x, row_top, width, 15, label(row['title']), _value(values, row['fill']))
                row_top -= 15
        tallest = max(tallest, top - row_top)
    top -= tallest + 4
    # The agent row: its boxes across the page, the last one to the right edge.
    x = LEFT
    for index, row in enumerate(areas['agent']):
        width = RIGHT - x if index == len(areas['agent']) - 1 or not row['width'] else row['width']
        form.labeled(x, top, width, 12, label(row['title']), _value(values, row['fill']))
        x += width
    column = top - 16
    # Left column: payment, estimated charges, services, disclosures and the shipper's acknowledgment.
    width = MIDDLE - LEFT
    left = column
    options = 0
    for row in areas['left']:
        if row['kind'] != 'option' and options:
            left -= 9.5 if options % 4 else 0  # A last row with fewer than four.
            options = 0
        kind = row['kind']
        if kind == 'paragraph':
            left = form.paragraph(LEFT + 2, left, width - 4, fill(row['text'], html=True), row['size'] or 5.6)
        elif kind == 'signature':
            left = _signature_row(form, left, label(row['title']), signatures, row['height'] or 24,
                                  spot=row['spot'] - 1 if row['spot'] else None, date_label=label(row['note']))
        elif kind == 'total':
            form.box(LEFT, left, 170, 20)
            form.box(LEFT + 170, left, width - 170, 20)
            canvas.setFont('Helvetica-Bold', 7.5)
            canvas.drawCentredString(LEFT + 85, left - (11 if row['note'] else 13), label(row['title']))
            if row['note']:
                form.text(LEFT + 12, left - 17, label(row['note']), 4.6)
            value = _value(values, row['fill'])
            form.text(LEFT + 174, left - 13, value or label(row['text']), 8.5)
            left -= 20
        elif kind == 'heading':
            form.text(LEFT, left - 7, label(row['title']), row['size'] or 6.2, bold=True)
            left -= 10
        elif kind == 'option':
            # Four to a row, for circling by hand.
            form.text(LEFT + (options % 4) * (width / 4) + 2, left - 7, label(row['title']), 6)
            options += 1
            if options % 4 == 0:
                left -= 9.5
            if row['space']:
                left -= (9.5 if options % 4 else 0) + row['space']
                options = 0
            continue
        elif kind == 'bar':
            left = form.bar(LEFT, left, width, row['height'] or 13, label(row['title']), row['size'] or 7.5)
        left -= row['space'] or 0
    # Right column: the actual charges, filled in on moving day.
    x, width = MIDDLE + 6, RIGHT - MIDDLE - 6
    right = column
    for row in areas['right']:
        kind = row['kind']
        if kind == 'caption':
            canvas.setFont('Helvetica-Bold', 7.5)
            canvas.drawCentredString(x + width / 2, right - 7, label(row['title']))
            right -= 10
        elif kind == 'bar':
            right = form.bar(x, right, width, row['height'] or 10.5, label(row['title']), row['size'] or 7.5)
        elif kind == 'charge':
            height, amount = row['height'] or 10.2, row['note']
            form.box(x, right, width - 40, height)
            form.box(x + width - 40, right, 40, height)
            form.text(x + 2, right - height + 3.2, label(row['title']), 6)
            form.text(x + width - 38, right - height + 3.2, amount, 6 if amount == '$' else 4.4, bold=amount != '$')
            right -= height
        elif kind == 'paragraph':
            right = form.paragraph(x + 2, right, width - 4, fill(row['text'], html=True), row['size'] or 5.5)
        elif kind == 'summary':
            form.box(x, right, width - 40, 9.6)
            form.box(x + width - 40, right, 40, 9.6)
            title = label(row['title'])
            if title:
                form.text(x + (2 if row['align'] == 'left' else width - 42 - canvas.stringWidth(title, 'Helvetica-Bold', 6)),
                          right - 7.2, title, 6, bold=True)
            form.text(x + width - 38, right - 7.2, '$', 6)
            right -= 9.6
        elif kind == 'signature':
            height = row['height'] or 20
            form.box(x, right, width - 60, height)
            form.box(x + width - 60, right, 60, height)
            form.text(x + 2, right - height + 3, label(row['title']), 6, bold=True)
            form.text(x + width - 58, right - 7, label(row['note']), 6, bold=True)
            right -= height
        right -= row['space'] or 0
    return left, right


def form_problems(blocks, company_name):
    """Why a form would not fit on the page as one sheet (empty when it fits): each area's room, and the columns drawn
    with the company's name, as tall as they will print."""
    from reportlab.pdfgen.canvas import Canvas
    count = lambda area: sum(row['area'] == area for row in blocks)
    problems = []
    if count('company') > 8:
        problems.append('The company header has room for 8 lines.')
    if count('order') > 4:
        problems.append('There is room for 4 order boxes.')
    if count('header') > 1:
        problems.append('The form has one title.')
    agent = [row for row in blocks if row['area'] == 'agent']
    if sum(row['width'] or 0 for row in agent[:-1]) > RIGHT - LEFT - 20:
        problems.append("The agent row's boxes are wider than the page.")
    left, right = _front(Canvas(BytesIO(), pagesize=letter), {'name': company_name}, {}, {}, None, blocks)
    if left < BOTTOM:
        problems.append('The left column runs past the bottom of the page. Shorten or remove parts of it.')
    if right < BOTTOM:
        problems.append('The right column runs past the bottom of the page. Shorten or remove parts of it.')
    return problems


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
    # The front page: the company's form, from its Bill of Lading document's blocks.
    blocks = next(document['blocks'] for document in documents if document.get('blocks'))
    doc.build(story, onFirstPage=lambda canvas, _: _front(canvas, company, values, signatures, logo, blocks))
    return output.getvalue()
