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
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


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
    styles = getSampleStyleSheet()
    styles['Normal'].fontSize = 9
    styles['Normal'].leading = 12

    def p(value):
        return Paragraph(escape(str(value)).replace('\n', '<br/>'), styles['Normal'])

    story = []
    if company or client:
        company = company or {}
        client = client or {}
        company_block = []
        logo = company.get('logo') or ''
        if logo.startswith('data:image/png;base64,') and len(logo) <= 400000:
            try:
                picture = Image(BytesIO(base64.b64decode(logo.split(',', 1)[1], validate=True)))
                scale = min(100 / picture.imageWidth, 60 / picture.imageHeight)
                picture.drawWidth = picture.imageWidth * scale
                picture.drawHeight = picture.imageHeight * scale
                picture.hAlign = 'LEFT'
                company_block.extend([picture, Spacer(1, 6)])
            except (ValueError, OSError, binascii.Error):
                pass
        company_block.append(Paragraph(escape(company.get('name') or 'Your moving team'), styles['Heading3']))
        company_block.extend(p(value) for value in [company.get('office_address'), company.get('phone')] if value)
        client_block = [Paragraph('Client', styles['Heading3'])]
        client_block.extend(p(value) for value in [client.get('name'), client.get('phone'), client.get('email')] if value)
        header = Table([[company_block, client_block]], colWidths=[292, 220])
        header.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('LINEBELOW', (0, 0), (-1, -1), .5, colors.HexColor('#e5dada')),
        ]))
        story.extend([header, Spacer(1, 14)])

    count = sum(row['amount'] for room in rooms for row in room['items'])
    story += [Paragraph('Your inventory', styles['Title']),
             p(f'{len(rooms)} rooms | {count} items | {cuft:,.2f} cu ft going | {weight:,.2f} lb'),
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
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f7f1f1')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ('LINEBELOW', (0, 0), (-1, -1), .4, colors.HexColor('#e5dada')),
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
