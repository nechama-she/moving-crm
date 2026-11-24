"""Company document templates shared by settings, estimates and signed snapshots."""
from datetime import datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
import re

DEFAULT_KEY = 'ld-binding-estimate'
DEFAULT_TITLE = 'LD Binding Estimate for Moving Services'
BILL_OF_LADING_KEY = 'bill-of-lading'
BILL_OF_LADING_TITLE = 'Interstate Bill of Lading Contract'

# Details of the move a document can show, filled from the signed estimate.
MOVE_FIELDS = {
    'customer_name': 'Customer name', 'customer_phone': 'Customer phone', 'customer_email': 'Customer email',
    'pickup_address': 'Pickup address', 'delivery_address': 'Delivery address', 'stops': 'Additional stops',
    'pickup_date': 'Pickup date', 'first_available_delivery_date': 'First available delivery date',
    'order_number': 'Order number', 'total_estimate': 'Total estimated charges', 'minimum_cuft': 'Minimum cu ft',
    'minimum_charge': 'Total minimum charge', 'services_ordered': 'Services ordered',
}
MOVE_PARAMETER = re.compile(r'\{\{\s*([a-z_]+)\s*\}\}')

FIELD_LABELS = {
    'name': 'Company name', 'phone': 'Phone number', 'sender_email': 'Email address',
    'office_address': 'Office address', 'dot_number': 'USDOT number', 'mc_number': 'MC number', 'id': 'Company ID',
    'samrtmoving_branch_id': 'SmartMoving branch ID', 'is_default_company': 'Default company',
    'created_at': 'Company created date', 'logo': 'Logo data', 'color': 'Brand color',
}
PARAMETER = re.compile(r'\{\{\s*(company_[a-z_]+)\s*\}\}')


def company_fields(company):
    from models import Company
    result = []
    for column in Company.__table__.columns:
        raw = getattr(company, column.name, None)
        value = ('Yes' if raw else 'No') if isinstance(raw, bool) else raw.isoformat() if isinstance(raw, datetime) else str(raw or '')
        result.append({'key': 'company_' + column.name,
                       'label': FIELD_LABELS.get(column.name, column.name.replace('_', ' ').capitalize()),
                       'value': value, 'missing': not bool(value.strip())})
    return sorted(result, key=lambda row: (row['key'] not in {'company_name', 'company_phone', 'company_sender_email', 'company_office_address', 'company_dot_number'}, row['label']))


def resolve_parameters(text, company, html=False):
    values = {row['key']: row['value'] for row in company_fields(company)}
    values['company_email'] = values.get('company_sender_email', '')
    missing = set()
    def replace(match):
        key = match.group(1)
        value = values.get(key, '')
        if not value:
            missing.add(key)
        return escape(value, quote=True) if html else value
    return PARAMETER.sub(replace, text), sorted(missing)


def safe_link(value):
    value = value.strip()
    if any(ord(c) < 32 for c in value):
        return ''
    parsed = urlsplit(value)
    if parsed.scheme.lower() in {'http', 'https'} and parsed.netloc:
        return value
    if parsed.scheme.lower() in {'mailto', 'tel'} and parsed.path:
        return value
    return ''


class DocumentHTML(HTMLParser):
    allowed = {'p', 'br', 'strong', 'b', 'em', 'i', 'u', 'ul', 'ol', 'li', 'h2', 'h3', 'a'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {'tag': 'root', 'children': []}
        self.stack = [self.root]
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'iframe', 'object'}:
            self.blocked += 1
        if self.blocked:
            return
        tag = 'p' if tag == 'div' else tag
        if tag not in self.allowed:
            return
        node = {'tag': tag, 'children': []}
        if tag == 'a':
            node['href'] = safe_link(dict(attrs).get('href', '') or '')
        self.stack[-1]['children'].append(node)
        if tag != 'br':
            if len(self.stack) >= 50:
                raise ValueError('Document formatting is nested too deeply')
            self.stack.append(node)

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'iframe', 'object'}:
            self.blocked = max(0, self.blocked - 1)
            return
        if self.blocked:
            return
        tag = 'p' if tag == 'div' else tag
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index]['tag'] == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, data):
        if not self.blocked:
            self.stack[-1]['children'].append(data)


def parse_document(value):
    parser = DocumentHTML()
    parser.feed(value)
    parser.close()
    return parser.root['children']


def html_node(node):
    if isinstance(node, str):
        return escape(node)
    tag = node['tag']
    inner = ''.join(html_node(child) for child in node['children'])
    if tag == 'br':
        return '<br/>'
    if tag == 'a':
        return f'<a href="{escape(node["href"], quote=True)}">{inner}</a>' if node.get('href') else inner
    return f'<{tag}>{inner}</{tag}>'


def clean_html(value):
    return ''.join(html_node(node) for node in parse_document(value))


def default_body():
    return clean_html((Path(__file__).parent / 'data' / 'default_estimate_document.html').read_text(encoding='utf-8'))


def bill_of_lading_body():
    return clean_html((Path(__file__).parent / 'data' / 'bill_of_lading_document.html').read_text(encoding='utf-8'))


def seed_documents(connection):
    """Insert defaults only; redeploying never overwrites company edits."""
    from sqlalchemy import select, update
    from sqlalchemy.dialects.postgresql import insert
    from models import Company, CompanyDocument
    body = default_body()
    # Upgrade only the exact original seed, never a company's edited wording.
    legacy = body.replace('<a href="tel:{{company_phone}}">{{company_phone}}</a>', '202-937-2625')
    legacy = legacy.replace('{{company_sender_email}}', 'sales@gorillahaulers.com')
    legacy = legacy.replace('contact dispatch at: <a href="mailto:sales@gorillahaulers.com">sales@gorillahaulers.com</a>',
                            'contact dispatch at: <a href="mailto:gorillahaulers@gmail.com">gorillahaulers@gmail.com</a>')
    connection.execute(update(CompanyDocument).where(CompanyDocument.key == DEFAULT_KEY,
        CompanyDocument.body_html == legacy).values(body_html=body,
        revision=CompanyDocument.revision + 1, updated_at=datetime.utcnow()))
    bill_of_lading = bill_of_lading_body()
    # The form prints the front itself, so a Bill of Lading document holds the back's terms only: anything saved before
    # SECTION 1 (the first version's front) is dropped. A copy of the earlier seed's terms, which differed from the printed
    # ones in a few marks, takes the printed terms; edited terms are kept as saved.
    start = '<p><strong>SECTION 1:'
    first_seed = (Path(__file__).parent / 'data' / 'bill_of_lading_document.html').read_text(encoding='utf-8')
    for printed, seeded in (("inventory list.(b)", "inventory list. (b)"),
                            ("excess of the carrier's liability", "excess of the carrier&rsquo;s liability"),
                            ("solely the shipper's responsibility with respect", "solely the shipper&rsquo;s responsibility with respect"),
                            ("subject to the arbitrator's discretion. ", "subject to the arbitrator&rsquo;s discretion. "),
                            ("that the Arbitrator's decision", "that the Arbitrator&rsquo;s decision"),
                            ("as it doesn't exceed", "as it doesn&rsquo;t exceed")):
        first_seed = first_seed.replace(printed, seeded)
    first_seed = clean_html(first_seed)
    for company_id, saved in connection.execute(select(CompanyDocument.company_id, CompanyDocument.body_html).where(
            CompanyDocument.key == BILL_OF_LADING_KEY, CompanyDocument.body_html.contains(start))).all():
        terms = saved[saved.index(start):]
        terms = bill_of_lading if terms == first_seed else terms
        if terms != saved:
            connection.execute(update(CompanyDocument).where(CompanyDocument.company_id == company_id,
                CompanyDocument.key == BILL_OF_LADING_KEY).values(body_html=terms, revision=CompanyDocument.revision + 1,
                updated_at=datetime.utcnow()))
    for company_id in connection.execute(select(Company.id)).scalars():
        connection.execute(insert(CompanyDocument).values(company_id=company_id, key=DEFAULT_KEY,
            title=DEFAULT_TITLE, body_html=body, move_type='Long Distance', enabled=True,
            revision=1, updated_at=datetime.utcnow()).on_conflict_do_nothing())
        # Off until a company turns it on: its terms (venue, MC number) are the company's to check first.
        connection.execute(insert(CompanyDocument).values(company_id=company_id, key=BILL_OF_LADING_KEY,
            title=BILL_OF_LADING_TITLE, body_html=bill_of_lading, move_type='Long Distance', used_in='bill_of_lading',
            enabled=False, revision=1, updated_at=datetime.utcnow()).on_conflict_do_nothing())


def new_company_document(company_id):
    from models import CompanyDocument
    return CompanyDocument(company_id=company_id, key=DEFAULT_KEY, title=DEFAULT_TITLE,
                           body_html=default_body(), move_type='Long Distance')


def document_payload(row):
    return {key: getattr(row, key) for key in ('key', 'title', 'body_html', 'move_type', 'used_in', 'enabled', 'revision')}


# The paperwork a document can go with; each has a part built from the move, followed by its documents.
DOCUMENT_USES = ('estimate', 'work_order', 'bill_of_lading')


def move_fields():
    """The move details as settings lists them next to the company details; their values come from each move."""
    return [{'key': key, 'label': 'Move: ' + label, 'value': 'Filled from the move', 'missing': False} for key, label in MOVE_FIELDS.items()]


def fill_move_fields(html, values):
    """Each move detail in the document's text, escaped as text."""
    def replace(match):
        key = match.group(1)
        if key not in MOVE_FIELDS:
            return match.group(0)
        return escape(str(values.get(key) or ''), quote=True)
    return MOVE_PARAMETER.sub(replace, html)


def documents_for(lead, job, db, used_in='estimate'):
    from sqlalchemy import case
    from models import Company, CompanyDocument
    from move_types import normalize_move_type
    company = db.get(Company, job.company_id or lead.company_id) if (job.company_id or lead.company_id) else None
    if company is None:
        return []
    move_type = normalize_move_type(lead.move_type)
    rows = db.query(CompanyDocument).filter(CompanyDocument.company_id == company.id,
        CompanyDocument.enabled.is_(True), CompanyDocument.used_in == used_in,
        CompanyDocument.move_type.in_([move_type, 'All'])).order_by(
            case((CompanyDocument.key == DEFAULT_KEY, 0), else_=1), CompanyDocument.title).all()
    result = []
    for row in rows:
        # Escape substituted values before parsing: names are text, never markup.
        body, _ = resolve_parameters(row.body_html, company, html=True)
        title, _ = resolve_parameters(row.title, company)
        body = clean_html(body)
        result.append({'key': row.key, 'revision': row.revision,
                       'title': title, 'body_html': body})
    return result


def pdf_document_flowables(document, body, heading):
    """The document's title and text, in the given body and heading styles."""
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle
    normal = ParagraphStyle('CompanyDocumentBody', parent=body, spaceAfter=7)
    bullet = ParagraphStyle('CompanyDocumentList', parent=normal, leftIndent=14, firstLineIndent=0)
    blocks = {'p', 'h2', 'h3', 'ul', 'ol', 'li'}

    def inline(node):
        if isinstance(node, str):
            return escape(node)
        inner = ''.join(inline(child) for child in node['children'])
        tag = node['tag']
        if tag == 'br':
            return '<br/>'
        if tag == 'a':
            return f'<a href="{escape(node["href"], quote=True)}" color="#0b5cab"><u>{inner}</u></a>' if node.get('href') else inner
        tag = {'strong': 'b', 'em': 'i'}.get(tag, tag)
        return f'<{tag}>{inner}</{tag}>' if tag in {'b', 'i', 'u'} else inner

    def walk(nodes, style=normal, marker=None):
        output, pending = [], []
        def flush():
            if ''.join(pending).strip():
                output.append(Paragraph(''.join(pending), style, bulletText=marker))
            pending.clear()
        for node in nodes:
            if isinstance(node, str) or node['tag'] not in blocks:
                pending.append(inline(node))
                continue
            flush()
            tag = node['tag']
            if tag in {'ul', 'ol'}:
                for index, child in enumerate(node['children']):
                    if isinstance(child, dict) and child['tag'] == 'li':
                        output.extend(walk(child['children'], bullet, f'{index + 1}.' if tag == 'ol' else '-'))
            else:
                output.extend(walk(node['children'], heading if tag in {'h2', 'h3'} else style, marker))
        flush()
        return output
    return [Paragraph(escape(document['title']), heading), Spacer(1, 6), *walk(parse_document(document['body_html']))]
