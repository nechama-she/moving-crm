"""Read-only estimate export. All quantities, answers and prices come from saved data."""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from math import ceil
import json
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak


def inventory_entries(rows, questions, services=None):
    by_item = defaultdict(list)
    for question in questions:
        if question.get('all_items'):
            selected = set((question.get('saved') or {}).get('selected_items', []))
            for item in question.get('items', []):
                if item['id'] in selected:
                    by_item[item['item_index']].append({**question, 'unit_index': item['unit_index']})
        else:
            by_item[question['item_index']].append(question)
    for index, row in enumerate(rows):
        count = max(1, int(row.get('amount') or 1))
        related = by_item[index]
        service_notes = []
        from item_selectors import option_counts
        definitions = (services or {}).get(row.get('catalog_item_id') or row.get('item_id'), [])
        for definition in definitions:
            counts = option_counts(definition, (row.get('selections') or {}).get(definition['id']), count)
            service_notes.extend(f"{option}: {quantity}" for option, quantity in counts.items() if quantity)
        # Service counts describe the entire saved row, not a particular question's unit.
        if related and count > 1 and service_notes:
            service_notes.insert(0, f'Services for these {count} items:')
        for unit in range(count if related else 1):
            answers = [q for q in related if q.get('unit_index', 0) == unit]
            excluded = row.get('going') is False or any((q.get('saved') or {}).get('action') == 'exclude'
                           and not (q.get('saved') or {}).get('pending') for q in answers)
            yield dict(name=row.get('name') or 'Item', room=row.get('room') or 'Inventory',
                       label=f"{row.get('name', 'Item')} ({unit + 1} of {count})" if related and count > 1 else row.get('name', 'Item'),
                       quantity=1 if related else count, excluded=excluded, questions=answers,
                       service_notes=service_notes if unit == 0 else [], service_row=index if service_notes else None,
                       cuft=0 if excluded else float(row.get('cuft') or 0) / (count if related else 1),
                       weight=0 if excluded else (float(row['weight']) / (count if related else 1) if row.get('weight') is not None else None))


def compact_inventory_entries(entries):
    grouped = {}
    for entry in entries:
        notes = []
        for question in entry['questions']:
            saved = question.get('saved') or {}
            notes.append((saved.get('question') or question['question'], saved.get('answer'),
                          saved.get('notice'), saved.get('action'), saved.get('pending'), saved.get('acknowledged')))
        key = (entry['room'], entry['name'], entry['excluded'], json.dumps(notes),
               entry.get('service_row'), tuple(entry.get('service_notes', [])),
               entry['cuft'] / entry['quantity'],
               entry['weight'] / entry['quantity'] if entry['weight'] is not None else None)
        if key not in grouped:
            grouped[key] = {**entry, 'label': entry['name']}
        else:
            group = grouped[key]
            group['quantity'] += entry['quantity']
            group['cuft'] += entry['cuft']
            if group['weight'] is not None:
                group['weight'] += entry['weight']
    return list(grouped.values())


# Largest first: the type shrinks only as far as needed to keep the summary
# (everything before the declared inventory) on the first page.
FONT_SIZES = (10, 9.5, 9, 8.5, 8)
NAVY = colors.HexColor('#15354b')
MUTED = colors.HexColor('#526473')


def money(value):
    return f"${Decimal(str(value or 0)):,.2f}"


def _is_service(charge):
    """Service and fee lines have ids made from the job and the service; the plan's own lines are random."""
    from uuid import UUID
    try:
        return UUID(str(charge.get('id'))).version != 4
    except ValueError:
        return bool(charge.get('id'))


def _services_total(estimate):
    lines = [charge for charge in estimate.get('charges') or [] if _is_service(charge)]
    return lines, sum(float(charge.get('total') or 0) for charge in lines), any(charge.get('pending') for charge in lines)


def _services_table(data, p, table, styles):
    """Additional services and fees: each answer with its charge, then the other service lines, and their total."""
    from routes.pricing import customer_packing_charge_id
    lines, total, pending = _services_total(data['estimate'])
    by_id = {charge.get('id'): charge for charge in lines}
    job_id = data.get('job_id')
    shown = set()
    def charge_of(key):
        charge = by_id.get(customer_packing_charge_id(job_id, key)) if job_id else None
        if charge is None:
            return 'No charge'
        shown.add(charge.get('id'))
        if charge.get('pending'):
            return 'Pending'
        if charge.get('discount_amount'):
            # As on the customer page: the price before the discount crossed out, then the price, then the discount.
            title = (data.get('discount_titles') or {}).get(charge.get('id')) or 'Discount'
            return [Paragraph(f"<strike>{money(charge.get('subtotal'))}</strike>  <b>{money(charge.get('total'))}</b>", styles['RightEstimate']),
                    p(f"{title}: -{money(charge['discount_amount'])} ({charge.get('discount_percent') or 0:g}%)", 'NoteEstimate')]
        return amount(charge.get('total'))
    def charge_cell(key):
        value = charge_of(key)
        return value if isinstance(value, list) else p(value, 'RightEstimate')
    def amount(value):
        return money(value) if float(value or 0) else 'No charge'
    def service(name, terms):
        return [p(name)] + ([p(terms, 'NoteEstimate')] if terms else [])
    body = [[p('SERVICE'), p('DETAILS'), p('CHARGE', 'RightEstimate')]]
    stops = data.get('extra_stops')
    for group in (stops or {}).get('locations', []):
        terms = f"{group['free_miles']:g} miles free; ${group['stop_fee']:.2f} per chargeable stop plus ${group['per_mile']:.2f} per mile beyond the allowance."
        answer = '\n'.join(row['address'] + (f" - {row['miles']} miles" if row.get('miles') is not None else ' - distance pending')
                           for row in group['stops']) or (f"No extra {group['location']} stops" if group['answer'] is False else 'Not answered')
        amounts = [row['total'] for row in group['stops']]
        for row in group['stops']:
            shown.update(charge.get('id') for charge in lines if str(charge.get('id', '')).startswith('extra-stop:'))
        cost = 'Pending' if any(value is None for value in amounts) else amount(sum(amounts))
        body.append([service('Extra ' + group['location'] + ' stops', terms), p(answer, 'NoteEstimate'), p(cost, 'RightEstimate')])
    elevator = data.get('elevator')
    for row in (elevator or {}).get('locations', []):
        answer = ('Not sure - pending confirmation' if row.get('unknown') else 'Elevator used' if row['uses_elevator']
                  else 'No elevator' if row['uses_elevator'] is not None else 'Not answered')
        body.append([service('Elevator - ' + row['location'], elevator['terms']), p(answer, 'NoteEstimate'),
                     charge_cell('elevator:' + row['location'])])
    carry = data.get('long_carry')
    for row in (carry or {}).get('locations', []):
        answer = ('Truck access unknown - pending confirmation' if row.get('unknown')
                  else f"{row['distance_feet']} feet" if row['distance_feet'] is not None else 'Not answered')
        terms = f"First {carry['included_feet']} feet included; ${carry['rate_per_cuft']:.2f} per cu ft per additional {carry['increment_feet']} feet."
        body.append([service('Long carry - ' + row['location'], terms), p(answer, 'NoteEstimate'),
                     charge_cell('long_carry:' + row['location'])])
    stairs = data.get('stairs')
    for row in (stairs or {}).get('locations', []):
        answer = ('Not sure - pending confirmation' if row.get('unknown') else 'Not answered' if row['flights'] is None
                  else 'No stairs' if not row['flights'] else f"{row['flights']} flight" + ('' if row['flights'] == 1 else 's'))
        terms = f"Up to {stairs['steps_per_flight']} steps is one flight; {stairs['free_flights']} free per address; ${stairs['rate_per_cuft']:.2f} per cu ft per additional flight."
        body.append([service('Stairs - ' + row['location'], terms), p(answer, 'NoteEstimate'),
                     charge_cell('stairs:' + row['location'])])
    storage = data.get('storage')
    if storage:
        answer = (f"Earliest delivery date: {storage.get('available_date') or 'Not answered'}"
                  + (f"\n{storage['paid_periods']} paid period(s)" if storage.get('valid') else ''))
        terms = f"First {storage['free_days']} days free; ${storage['rate_per_cuft']:.2f} per cu ft per additional {storage['period_days']} days or part thereof."
        body.append([service('Storage', terms), p(answer, 'NoteEstimate'), charge_cell('storage-periods')])
    shuttle = data.get('shuttle')
    if shuttle:
        answer = ('Shuttle required for this delivery area' if shuttle['automatic']
                  else {True: 'Semi-trailer can park at delivery: Yes', False: 'Semi-trailer can park at delivery: No - shuttle required'}.get(shuttle.get('answer'), 'Not answered'))
        body.append([service('Delivery truck access', None), p(answer, 'NoteEstimate'), charge_cell('shuttle')])
    # Lines with no answer of their own: packing, materials, item services, mileage fees.
    for charge in lines:
        if charge.get('id') in shown or (not charge.get('pending') and not charge.get('total')):
            continue
        cost = 'Pending' if charge.get('pending') else amount(charge['total'])
        body.append([service(charge['name'], None), p(charge.get('description') or '', 'NoteEstimate'), p(cost, 'RightEstimate')])
    body.append([p('TOTAL ADDITIONAL SERVICES AND FEES'), p('Includes charges pending calculation' if pending else '', 'NoteEstimate'),
                 p(money(total), 'RightEstimate')])
    services = table(body, [170, 257, 95], header=True)
    services.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), .4, colors.HexColor('#bdc9d0')),
                                  ('BACKGROUND', (0, len(body) - 1), (-1, len(body) - 1), colors.HexColor('#edf2f5'))]))
    return services


def _kit(size):
    styles = getSampleStyleSheet()
    styles['Title'].fontSize = size * 1.8
    styles['Title'].leading = size * 2.2
    styles.add(ParagraphStyle(name='BodyEstimate', fontName='Helvetica', fontSize=size, leading=size * 1.2, textColor=NAVY, spaceAfter=2))
    styles.add(ParagraphStyle(name='NoteEstimate', parent=styles['BodyEstimate'], textColor=MUTED))
    styles.add(ParagraphStyle(name='SectionEstimate', parent=styles['BodyEstimate'], fontSize=size + 2, leading=size + 4, spaceBefore=10, spaceAfter=5, fontName='Helvetica-Bold', keepWithNext=True))
    styles.add(ParagraphStyle(name='RightEstimate', parent=styles['BodyEstimate'], alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name='CompanyEstimate', parent=styles['SectionEstimate'], alignment=TA_RIGHT, spaceBefore=0))
    styles.add(ParagraphStyle(name='CompanyDetailsEstimate', parent=styles['NoteEstimate'], alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name='LabelEstimate', parent=styles['NoteEstimate'], fontName='Helvetica-Bold', fontSize=size - 1.5, leading=size * 1.1))
    def p(value, style='BodyEstimate'):
        return Paragraph(escape(str(value or '')).replace('\n', '<br/>'), styles[style])
    def table(body, widths, header=False):
        result = Table(body, colWidths=widths, repeatRows=1 if header else 0, hAlign='LEFT')
        commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 9),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 7), ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4), ('LINEBELOW', (0, 0), (-1, -1), .4, colors.HexColor('#dce4e8'))]
        if header:
            commands.append(('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#edf2f5')))
        result.setStyle(TableStyle(commands))
        return result
    return styles, p, table


def _template(output, company):
    return SimpleDocTemplate(output, pagesize=letter, rightMargin=45, leftMargin=45, topMargin=38,
                             bottomMargin=53, title='Moving estimate', author=company.get('name') or '')


def _summary(data, styles, p, table, link=True, title='MOVING ESTIMATE'):
    """Details, price breakdown, customer note and signature: the part that belongs on page one."""
    company = data.get('company_details') or {}
    estimate = data['estimate']
    from inventory_pdf import company_logo_image
    company_block = [p(company.get('name') or data.get('company'), 'CompanyEstimate')]
    company_block += [p(value, 'CompanyDetailsEstimate') for value in [company.get('office_address'), company.get('phone')] if value]
    if company.get('dot_number'):
        company_block.append(p(f"USDOT: {company['dot_number']}", 'CompanyDetailsEstimate'))
    logo = company_logo_image(company.get('logo'))
    header = Table([[logo, company_block]] if logo else [[company_block]], colWidths=[166, 356] if logo else [522], hAlign='LEFT')
    header.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                                ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
    story = [header,
             Spacer(1, 12), Paragraph(title, styles['Title']),
             p('Prepared ' + (data.get('prepared_at') or datetime.now(timezone.utc).strftime('%B %d, %Y (UTC)')), 'NoteEstimate')]
    # Every phone and every email: the main one first, then the extras.
    def contacts(kind):
        return '\n'.join(filter(None, [data.get(kind), *[row['value'] for row in data.get('contacts') or [] if row['kind'] == kind]]))
    # A small grey label over each value; empty ones are left out, and rows of three line up with each other.
    def row(*fields):
        fields = [(label, value) for label, value in fields if value]
        if not fields:
            return Spacer(0, 0)
        return table([[[p(label, 'LabelEstimate'), p(value)] for label, value in fields]], [522 / max(len(fields), 3)] * len(fields))
    def stops(kind):
        return '\n'.join(stop.get('address', '') for stop in data.get('stops', []) if stop.get('type') == kind)
    # The earliest delivery date is the customer's storage answer, so it shows only where storage is offered.
    storage = data.get('storage')
    story += [p('Customer', 'SectionEstimate'),
              row(('NAME', data.get('name', '')), ('PHONE', contacts('phone')), ('EMAIL', contacts('email'))),
              p('Move details', 'SectionEstimate'),
              row(('PICKUP', data.get('pickup', '')), ('PICKUP STOPS', stops('pickup')),
                  ('DELIVERY', data.get('delivery', '')), ('DELIVERY STOPS', stops('delivery'))),
              row(('PICKUP DATE', str(data.get('move_date') or 'Not scheduled')),
                  ('FIRST AVAILABLE DELIVERY DATE', storage and (storage.get('available_date') or 'Not answered')),
                  ('PARTIAL ESTIMATE' if any(c.get('pending') for c in estimate.get('charges', [])) else 'ESTIMATED TOTAL', money(estimate['price'])))]
    for stop in data.get('stops', []):
        if stop.get('type') not in ('pickup', 'delivery'):
            story.append(p(f"Additional stop (unspecified): {stop.get('address', '')}"))
    story += [p('Price breakdown', 'SectionEstimate'), p(f"Estimated shipment volume: {ceil(float(estimate.get('cuft') or 0))} cu ft")]
    package = data.get('packing_package') or {}
    minimum = package.get('minimum_cubic_feet')
    if minimum and float(minimum) > float(estimate.get('cuft') or 0):
        story.append(p(f"Minimum billable volume for applicable services: {float(minimum):g} cu ft.", 'NoteEstimate'))
    charges = [[p('ITEM'), p('RATE / BASIS'), p('COST', 'RightEstimate')]]
    for charge in estimate.get('charges') or []:
        # Zero lines, including ones discounted to zero, are explained in their detail section.
        if _is_service(charge) or (not charge.get('pending') and not charge.get('total')):
            continue
        basis = charge.get('description') or 'Not specified'
        rate = re.fullmatch(r'\$([\d,]+\.\d{2}) per cu ft(?: \(minimum charge \$([\d,]+\.\d{2})\))?', basis) if charge.get('name') == 'Transportation charge' else None
        if rate and rate[2]:
            # The plan's two minimums: its minimum volume and its minimum charge.
            minimum_cuft = estimate.get('minimum_cuft') or minimum
            basis = (f"Up to {float(minimum_cuft):g} cu ft: ${rate[2]} | Each additional cu ft: ${rate[1]}" if minimum_cuft
                     else f"Minimum charge: ${rate[2]} | Each cu ft: ${rate[1]}")
        elif rate:
            basis = f"{float(estimate.get('cuft') or 0):,.2f} cuft @ ${rate[1]} per cuft"
        if charge.get('discount_amount', 0) > 0:
            # A rep discount adds "| <title>: -$X" to the saved description; these two lines say it once.
            basis = re.sub(r' \| [^|]*: -\$[\d,]+\.\d{2}( \(new rate [^)]*\))?$', '', basis)
            title = (data.get('discount_titles') or {}).get(charge.get('id')) or 'Discount'
            basis += f"\nBefore discount: {money(charge['subtotal'])}\n{title} ({charge['discount_percent']:g}%): -{money(charge['discount_amount'])}"
        charges.append([p(charge['name']), p(basis, 'NoteEstimate'), p('Pending' if charge.get('pending') else money(charge['total']), 'RightEstimate')])
    service_lines, service_total, service_pending = _services_total(estimate)
    if service_lines:
        # A link to the services table further down.
        # Measuring page one builds it alone, without the table to link to; the text takes the same room.
        text = 'See Additional services and fees'
        text = f'<a href="#additional-services" color="#1a5fb4"><u>{text}</u></a>' if link else f'<u>{text}</u>'
        link = Paragraph(text + (' (includes pending charges)' if service_pending else ''), styles['NoteEstimate'])
        charges.append([p('Additional services and fees'), link,
                        p(money(service_total), 'RightEstimate')])
    if len(charges) == 1:
        charges.append([p('Moving estimate'), p('Not specified', 'NoteEstimate'), p(money(estimate['price']), 'RightEstimate')])
    charge_table = table(charges, [180, 247, 95], header=True)
    charge_table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), .4, colors.HexColor('#bdc9d0'))]))
    story.append(charge_table)
    story.append(table([[p('PARTIAL ESTIMATE - PENDING CHARGES EXCLUDED' if any(c.get('pending') for c in estimate.get('charges', [])) else 'TOTAL ESTIMATED PRICE'), p(money(estimate['price']), 'RightEstimate')]], [417, 105]))
    if data.get('list_changed') or data.get('files_changed'):
        story.append(p('This estimate reflects the current generated report. New inventory edits or files are not included until a new report is generated.', 'NoteEstimate'))
    note = (data.get('customer_notes') or '').strip()
    if note:
        story += [p('Notes', 'SectionEstimate'), p(note)]
    story.append(_signature_block(data, p))
    return story


def _signature_block(data, p):
    """The client's signature under the price breakdown and note, on page one: an empty line to sign
    on, or the signature once signed."""
    from reportlab.graphics.shapes import Drawing, PolyLine
    signature = data.get('signature')
    width, height = 260, 64
    if signature:
        drawing = Drawing(width, height)
        for stroke in signature['strokes']:
            drawing.add(PolyLine([coordinate for x, y in stroke for coordinate in (x * width, (1 - y) * height)],
                                 strokeColor=NAVY, strokeWidth=1.5))
        line = Table([[drawing]], colWidths=[width], rowHeights=[height], hAlign='LEFT')
        details = [p(signature['name']), p('Signed: ' + signature['signed_at'], 'NoteEstimate'),
                   p('Estimate version: ' + signature['estimate_id'], 'NoteEstimate')]
    else:
        line = Table([['']], colWidths=[width], rowHeights=[height], hAlign='LEFT')
        details = [p('Name and date are added when you sign.', 'NoteEstimate')]
    line.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), .8, MUTED), ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
    return KeepTogether([p('Client signature', 'SectionEstimate'),
                         p('I have reviewed this estimate and agree to sign it electronically.'), line, *details])


def _summary_pages(data, size):
    doc = _template(BytesIO(), {})
    doc.build(_summary(data, *_kit(size), link=False))
    return doc.page


def _work_order_section(work_order, estimate, p, table):
    """The work order's two sections after the signature: the team's notes (customer notes are already above), then the CRM payments."""
    # Each note on its own row, a small grey label over it; a note left empty is left out, and so is the section.
    notes = [[[p(label, 'LabelEstimate'), p(text)]] for label, text in
             (('INTERNAL NOTES', (work_order.get('internal_notes') or '').strip()), ('FOREMAN NOTES', (work_order.get('foreman_notes') or '').strip())) if text]
    story = [p('Team notes', 'SectionEstimate'), table(notes, [522])] if notes else []
    story.append(p('Payments', 'SectionEstimate'))
    payments = work_order['payments']
    body = [[p('DATE'), p('TAKEN BY'), p('AMOUNT', 'RightEstimate')]]
    body += [[p(payment.get('paidAt') or 'Not set'), p(payment.get('takenByUser') or 'Not set'), p(money(payment['amount']), 'RightEstimate')]
             for payment in payments]
    total = Decimal(str(estimate['price'] or 0))
    paid = sum(Decimal(str(payment['amount'])) for payment in payments)
    totals = [('Total estimate', total), ('Total paid', paid), ('Balance due', total - paid)]
    body += [[p(label), '', p(money(value), 'RightEstimate')] for label, value in totals]
    payment_table = table(body, [150, 277, 95], header=True)
    payment_table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), .4, colors.HexColor('#bdc9d0'))]
                                      + [('SPAN', (0, len(body) - n), (1, len(body) - n)) for n in range(1, len(totals) + 1)]))
    story.append(payment_table)
    return story


def build_estimate_pdf(data, rows, work_order=None):
    """The estimate. With work_order (its notes and payments), the work order: the same document with those after the signature."""
    output = BytesIO()
    muted = MUTED
    size = next((size for size in FONT_SIZES if _summary_pages(data, size) == 1), FONT_SIZES[-1])
    styles, p, table = _kit(size)
    company = data.get('company_details') or {}
    package = data.get('packing_package') or {}
    title = 'WORK ORDER' if work_order else 'MOVING ESTIMATE'
    story = _summary(data, styles, p, table, title=title)
    if work_order:
        story += _work_order_section(work_order, data['estimate'], p, table)
    story.append(p('Declared inventory', 'SectionEstimate'))
    rooms = defaultdict(list)
    entries_all = compact_inventory_entries(inventory_entries(rows, data.get('item_questions') or [], data.get('item_services')))
    for entry in entries_all:
        rooms[entry['room']].append(entry)
    def totals(entries):
        going = sum(e['quantity'] for e in entries if not e['excluded'])
        not_going = sum(e['quantity'] for e in entries if e['excluded'])
        volume = sum(e['cuft'] for e in entries)
        return f"Going: {going}   |   Not going: {not_going}   |   Volume: {volume:,.2f} cu ft"
    for room, entries in rooms.items():
        body = [[p(room + '\n' + totals(entries)), '', '', ''],
                [p(label, 'NoteEstimate') for label in ['ITEM', 'GOING', 'NOT GOING', 'CU FT']]]
        commands = [('SPAN', (0, 0), (-1, 0)), ('BACKGROUND', (0, 0), (-1, 1), colors.HexColor('#edf2f5'))]
        for entry in entries:
            item_row = len(body)
            item_text = [p(entry['label'])] + [p(note, 'NoteEstimate') for note in entry.get('service_notes', [])]
            body.append([item_text, p(str(0 if entry['excluded'] else entry['quantity']), 'RightEstimate'),
                         p(str(entry['quantity'] if entry['excluded'] else 0), 'RightEstimate'),
                         p(f"{entry['cuft']:,.2f}", 'RightEstimate')])
            for question in entry['questions']:
                saved = question.get('saved') or {}
                notes = [str(saved.get('question') or question['question']) + '\nAnswer: ' + (saved.get('answer') or 'Not answered')]
                if saved.get('notice'):
                    notes.append('Instructions: ' + saved['notice'])
                if saved.get('pending'):
                    notes.append('Acknowledgment required - not yet completed.')
                elif saved.get('acknowledged'):
                    notes.append('Customer acknowledged these instructions.')
                for note in notes:
                    row_index = len(body)
                    body.append([p(note, 'NoteEstimate'), '', '', ''])
                    commands += [('SPAN', (0, row_index), (-1, row_index)),
                                 ('BACKGROUND', (0, row_index), (-1, row_index), colors.HexColor('#f8fafb'))]
            if entry['questions']:
                commands.append(('NOSPLIT', (0, item_row), (-1, item_row + 1)))
        room_table = Table(body, colWidths=[343, 50, 58, 71], repeatRows=2, splitInRow=1, hAlign='LEFT')
        room_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), .4, colors.HexColor('#bdc9d0')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ] + commands))
        story += [room_table, Spacer(1, 7)]
    story.append(p('Inventory totals', 'SectionEstimate'))
    story.append(p(totals(entries_all)))
    if _services_total(data['estimate'])[0] or any(data.get(key) for key in ('extra_stops', 'elevator', 'long_carry', 'stairs', 'storage', 'shuttle')):
        story += [Paragraph('<a name="additional-services"/>Additional services and fees', styles['SectionEstimate']),
                  _services_table(data, p, table, styles)]
    general = [q for q in data.get('item_questions', []) if q.get('all_items')
               and not (q.get('saved') or {}).get('selected_items')]
    if general:
        story.append(p('Moving terms', 'SectionEstimate'))
        for question in general:
            saved = question.get('saved') or {}
            story.append(p(question['question']))
            story.append(p('Answer: ' + (saved.get('answer') or 'Not answered'), 'NoteEstimate'))
            if saved.get('notice'):
                story.append(p(saved['notice'], 'NoteEstimate'))
            if saved.get('pending'):
                story.append(p('Answer incomplete - item selection or acknowledgment required.', 'NoteEstimate'))
    materials = package.get('material_rates') or []
    if materials:
        story += [PageBreak(), p('Materials price list', 'SectionEstimate'),
                  p('Price reference only. Materials and packing labor are priced separately per unit. Only selected services are included in the estimate total.', 'NoteEstimate'),
                  Spacer(1, 8)]
        body = [[p('Description'), p('Capacity / size'),
                 p('Material / unit', 'RightEstimate'), p('Packing / unit', 'RightEstimate')]]
        units = {'cuft': 'cu ft', 'inches': 'inches', 'sheets': 'sheets', 'feet': 'feet', 'items': 'items'}
        for material in materials:
            size = '-'
            if material.get('mattress_size'):
                size = material['mattress_size'].title() + ' mattress'
            else:
                capacity = material.get('capacity')
                unit = material.get('capacity_unit') or 'cuft'
                if capacity is None and material.get('box_capacity_cuft') is not None:
                    capacity, unit = material['box_capacity_cuft'], 'cuft'
                if capacity is not None:
                    prefix = 'Over ' if material.get('capacity_kind') == 'over' else ''
                    size = f"{prefix}{Decimal(str(capacity)):g} {units.get(unit, unit)}"
            body.append([p(material['name']), p(size, 'NoteEstimate'),
                         p(money(material.get('material_price')), 'RightEstimate'),
                         p(money(material.get('packing_price')), 'RightEstimate')])
        story.append(table(body, [228, 104, 95, 95], header=True))
    from company_documents import pdf_document_flowables
    for document in data.get('documents', []):
        story.append(PageBreak())
        story.extend(pdf_document_flowables(document, styles))
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#dce4e8'))
        canvas.line(45, 39, 567, 39)
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(muted)
        if doc.page > 1:
            canvas.drawString(45, 770, title + ' - CONTINUED')
            canvas.drawRightString(567, 770, str(data.get('name') or '')[:70])
        canvas.drawString(45, 26, title.capitalize() + ' | ' + str(data.get('move_date') or 'Date pending'))
        canvas.drawRightString(567, 26, f'Page {doc.page}')
        canvas.restoreState()
    _template(output, company).build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
