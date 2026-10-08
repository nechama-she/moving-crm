"""Printable inventory snapshot, independent of estimate readiness."""
from io import BytesIO
import base64
import binascii
from concurrent.futures import ThreadPoolExecutor
import re
import time
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def pieces_per_item(name):
    match = re.search(r'\b([0-9]+)\s*[-–—]?\s*pieces?\b', name, re.I)
    pieces = int(match[1]) if match else 1
    return pieces if 0 < pieces <= 9007199254740991 else 1


def inventory_photos(rooms, details):
    """Resolve selected-report photos and embed bounded thumbnails, never arbitrary URLs."""
    import httpx
    from PIL import Image as PillowImage, ImageOps
    from report_question_images import question_images, image_expiry

    names = list(dict.fromkeys(row.get('reference_name') or row['name']
                              for room in rooms for row in room['items']))
    references = question_images(details, names)
    matches = {}
    for room in rooms:
        for row in room['items']:
            name = row.get('reference_name') or row['name']
            matches[(room['name'], name)] = list(dict.fromkeys(
                image['url'] for image in references.get(name, [])
                if image['room'].lower() == room['name'].lower()))[:2]

    def thumbnail(url):
        if not image_expiry(url, time.time()):
            return None
        try:
            with httpx.stream('GET', url, timeout=10, follow_redirects=False) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 10 * 1024 * 1024:
                        return None
            with PillowImage.open(BytesIO(content)) as source:
                if source.width * source.height > 20_000_000:
                    return None
                photo = ImageOps.exif_transpose(source)
                photo.thumbnail((240, 240))
                output = BytesIO()
                photo.convert('RGB').save(output, format='JPEG', quality=85)
                return output.getvalue()
        except (httpx.HTTPError, OSError, ValueError, PillowImage.DecompressionBombError):
            return None

    urls = list(dict.fromkeys(url for values in matches.values() for url in values))
    with ThreadPoolExecutor(max_workers=6) as executor:
        downloaded = dict(zip(urls, executor.map(thumbnail, urls)))
    return {key: [downloaded[url] for url in urls if downloaded.get(url)]
            for key, urls in matches.items()}


def build_inventory_pdf(rooms, cuft, weight, photos=None, *, company=None, client=None):
    output = BytesIO()
    from company_colors import resolve_company_color
    brand = colors.HexColor(resolve_company_color((company or {}).get('name'), (company or {}).get('color')))
    def tint(strength):
        return colors.Color(*(1 - (1 - channel) * strength for channel in (brand.red, brand.green, brand.blue)))
    border_color = tint(.25)
    header_color = tint(.08)
    heading_color = colors.Color(*(channel * .65 for channel in (brand.red, brand.green, brand.blue)))
    styles = getSampleStyleSheet()
    for name in ('Title', 'Heading2', 'Heading3'):
        styles[name].textColor = heading_color
    styles['Normal'].fontSize = 9
    styles['Normal'].leading = 12
    company_name_style = ParagraphStyle('CompanyName', parent=styles['Heading3'], alignment=TA_RIGHT)
    company_details_style = ParagraphStyle('CompanyDetails', parent=styles['Normal'], alignment=TA_RIGHT)

    def p(value):
        return Paragraph(escape(str(value)).replace('\n', '<br/>'), styles['Normal'])

    story = []
    if company or client:
        company = company or {}
        client = client or {}
        company_block = []
        logo_block = []
        logo = company.get('logo') or ''
        if logo.startswith('data:image/png;base64,') and len(logo) <= 400000:
            try:
                from PIL import Image as PillowImage, ImageChops
                with PillowImage.open(BytesIO(base64.b64decode(logo.split(',', 1)[1], validate=True))) as source:
                    rgba = source.convert('RGBA')
                    # The editor saves a square canvas. Size the visible logo,
                    # rather than its transparent or white outer padding.
                    background = PillowImage.new('RGBA', rgba.size, 'white')
                    flattened = PillowImage.alpha_composite(background, rgba).convert('RGB')
                    difference = ImageChops.difference(flattened, PillowImage.new('RGB', rgba.size, 'white'))
                    bounds = difference.point(lambda value: 255 if value > 12 else 0).getbbox()
                    if bounds:
                        rgba = rgba.crop(bounds)
                    prepared = BytesIO()
                    rgba.save(prepared, format='PNG')
                prepared.seek(0)
                picture = Image(prepared, mask='auto')
                scale = min(150 / picture.imageWidth, 64 / picture.imageHeight)
                picture.drawWidth = picture.imageWidth * scale
                picture.drawHeight = picture.imageHeight * scale
                picture.hAlign = 'LEFT'
                logo_block.append(picture)
            except (ValueError, OSError, binascii.Error):
                pass
        company_block.append(Paragraph(escape(company.get('name') or 'Your moving team'), company_name_style))
        company_block.extend(Paragraph(escape(str(value)).replace('\n', '<br/>'), company_details_style)
                             for value in [company.get('office_address'), company.get('phone')] if value)
        if company.get('dot_number'):
            company_block.append(Paragraph(escape(f"USDOT: {company['dot_number']}"), company_details_style))
        customer_block = [p(f'{label}: {client.get(key) or ""}') for label, key in [
            ('Customer', 'name'), ('Phone number', 'phone'), ('Email', 'email')]]
        if logo_block:
            header = Table([[logo_block, company_block], [customer_block, '']], colWidths=[166, 346])
        else:
            header = Table([[company_block], [customer_block]], colWidths=[512])
        header.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (-1, 0), (-1, 0), 0),
            ('SPAN', (0, 1), (-1, 1)),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('LINEBELOW', (0, 1), (-1, 1), .5, border_color),
        ]))
        story.extend([header, Spacer(1, 14)])

    count = sum(row['amount'] for room in rooms for row in room['items'])
    pieces = sum(row['amount'] * pieces_per_item(row['name']) for room in rooms for row in room['items'])
    story += [Paragraph('Your inventory', styles['Title']),
             p(f'{len(rooms)} rooms | {count} items | {pieces} pieces | {cuft:,.2f} cu ft going | {weight:,.2f} lb'),
             Spacer(1, 12)]
    for room in rooms:
        story.append(Paragraph(escape(room['name']), styles['Heading2']))
        body = [[p(value) for value in ['Photo', 'Item name', 'Unit volume\n(cu ft)', 'Total volume\n(cu ft)', 'Qty', 'Going']]]
        for row in room['items']:
            name = row['name']
            if re.search(r'\bbox(?:es)?\b|\bdish\s*pack\b', name, re.I) and not re.search(r'\((CP|PBO)\)\s*$', name, re.I):
                name += ' (PBO)'
            pictures = []
            for content in (photos or {}).get((room['name'], row.get('reference_name') or row['name']), []):
                picture = Image(BytesIO(content))
                scale = min(54 / picture.imageWidth, 54 / picture.imageHeight)
                picture.drawWidth = picture.imageWidth * scale
                picture.drawHeight = picture.imageHeight * scale
                pictures.extend([picture, Spacer(1, 3)])
            body.append([pictures or p('-'), p(name), p(f"{row['unit_cuft']:,.2f}"),
                         p(f"{row['unit_cuft'] * row['amount']:,.2f}"),
                         p(row['amount']), p('No' if row.get('going') is False else 'Yes')])
        if len(body) == 1:
            story.append(p('No items in this room.'))
            continue
        table = Table(body, colWidths=[66, 201, 75, 75, 40, 55], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), header_color),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ('LINEBELOW', (0, 0), (-1, -1), .4, border_color),
        ]))
        story.extend([table, Spacer(1, 10)])
    story.extend([Spacer(1, 8), p('CP: movers pack. PBO: you pack. Volume going excludes items marked No.')])

    def footer(canvas, doc):
        canvas.setFont('Helvetica', 9)
        canvas.drawRightString(562, 22, f'Page {doc.page}')

    SimpleDocTemplate(output, pagesize=letter, rightMargin=50, leftMargin=50,
                      topMargin=36, bottomMargin=36, title='Your inventory').build(
                          story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
