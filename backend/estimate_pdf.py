"""Read-only estimate export. All quantities, answers and prices come from saved data."""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak


def inventory_entries(rows, questions):
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
        for unit in range(count if related else 1):
            answers = [q for q in related if q.get('unit_index', 0) == unit]
            excluded = any((q.get('saved') or {}).get('action') == 'exclude'
                           and not (q.get('saved') or {}).get('pending') for q in answers)
            yield dict(name=row.get('name') or 'Item', room=row.get('room') or 'Inventory',
                       label=f"{row.get('name', 'Item')} ({unit + 1} of {count})" if related and count > 1 else row.get('name', 'Item'),
                       quantity=1 if related else count, excluded=excluded, questions=answers,
                       cuft=0 if excluded else float(row.get('cuft') or 0) / (count if related else 1),
                       weight=0 if excluded else (float(row['weight']) / (count if related else 1) if row.get('weight') is not None else None))


def build_estimate_pdf(data, rows):
    output = BytesIO()
    navy = colors.HexColor('#15354b')
    muted = colors.HexColor('#526473')
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='BodyEstimate', fontName='Helvetica', fontSize=9, leading=13, textColor=navy, spaceAfter=5))
    styles.add(ParagraphStyle(name='NoteEstimate', parent=styles['BodyEstimate'], fontSize=8, leading=11, textColor=muted))
    styles.add(ParagraphStyle(name='SectionEstimate', parent=styles['BodyEstimate'], fontSize=13, leading=17, spaceBefore=16, spaceAfter=9, fontName='Helvetica-Bold', keepWithNext=True))
    styles.add(ParagraphStyle(name='RightEstimate', parent=styles['BodyEstimate'], alignment=TA_RIGHT))
    def p(value, style='BodyEstimate'):
        return Paragraph(escape(str(value or '')).replace('\n', '<br/>'), styles[style])
    def money(value):
        return f"${Decimal(str(value or 0)):,.2f}"
    def table(body, widths, header=False):
        result = Table(body, colWidths=widths, repeatRows=1 if header else 0, hAlign='LEFT')
        commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 9),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 9), ('TOPPADDING', (0, 0), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8), ('LINEBELOW', (0, 0), (-1, -1), .4, colors.HexColor('#dce4e8'))]
        if header:
            commands.append(('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#edf2f5')))
        result.setStyle(TableStyle(commands))
        return result
    company = data.get('company_details') or {}
    estimate = data['estimate']
    story = [p(company.get('name') or data.get('company'), 'SectionEstimate'),
             p(' | '.join(filter(None, [company.get('phone'), company.get('office_address')])), 'NoteEstimate'),
             Spacer(1, 12), Paragraph('MOVING ESTIMATE', styles['Title']),
             p('Prepared ' + datetime.now(timezone.utc).strftime('%B %d, %Y (UTC)'), 'NoteEstimate')]
    story.append(table([[p('CUSTOMER\n' + data.get('name', '')), p('MOVE DATE\n' + str(data.get('move_date') or 'Not scheduled'))],
                        [p('\n'.join(filter(None, [data.get('phone'), data.get('email')]))), p('ESTIMATED TOTAL\n' + money(estimate['price']))],
                        [p('PICKUP\n' + data.get('pickup', '')), p('DELIVERY\n' + data.get('delivery', ''))]], [261, 261]))
    for stop in data.get('stops', []):
        story.append(p(f"Additional stop ({stop.get('type') or 'unspecified'}): {stop.get('address', '')}"))
    story += [p('Price breakdown', 'SectionEstimate'), p(f"Estimated shipment volume: {float(estimate.get('cuft') or 0):g} cu ft")]
    package = data.get('packing_package') or {}
    minimum = package.get('minimum_cubic_feet')
    if minimum and float(minimum) > float(estimate.get('cuft') or 0):
        story.append(p(f"Minimum billable volume for applicable services: {float(minimum):g} cu ft. This is a billing minimum, not your inventory volume.", 'NoteEstimate'))
    charges = [[p('ITEM'), p('RATE / BASIS'), p('COST', 'RightEstimate')]]
    for charge in estimate.get('charges') or []:
        basis = charge.get('description') or 'Not specified'
        if charge.get('discount_amount', 0) > 0:
            basis += f"\nBefore discount: {money(charge['subtotal'])}\nDiscount ({charge['discount_percent']:g}%): -{money(charge['discount_amount'])}"
        charges.append([p(charge['name']), p(basis, 'NoteEstimate'), p(money(charge['total']), 'RightEstimate')])
    if len(charges) == 1:
        charges.append([p('Moving estimate'), p('Not specified', 'NoteEstimate'), p(money(estimate['price']), 'RightEstimate')])
    charge_table = table(charges, [180, 247, 95], header=True)
    charge_table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), .4, colors.HexColor('#bdc9d0'))]))
    story.append(charge_table)
    story.append(table([[p('TOTAL ESTIMATED PRICE'), p(money(estimate['price']), 'RightEstimate')]], [417, 105]))
    if data.get('list_changed') or data.get('files_changed'):
        story.append(p('This estimate reflects the current generated report. New inventory edits or files are not included until a new report is generated.', 'NoteEstimate'))
    if data.get('long_carry'):
        carry = data['long_carry']
        story.append(p('Long carry', 'SectionEstimate'))
        story.append(p(f"First {carry['included_feet']} feet included at each address. Each additional {carry['increment_feet']} feet or part thereof costs ${carry['rate_per_cuft']:.2f} per cu ft. Distance follows the walking route between the parked truck and the entrance.", 'NoteEstimate'))
        for row in carry['locations']:
            answer = f"{row['distance_feet']} feet; charge {money(row['total'])}" if row['distance_feet'] is not None else 'Not answered - long carry charges may apply'
            story.append(p(row['location'].title() + ': ' + answer, 'NoteEstimate'))
    if data.get('stairs'):
        stairs = data['stairs']
        story.append(p('Outdoor and building stairs', 'SectionEstimate'))
        story.append(p(f"Up to {stairs['steps_per_flight']} steps counts as one flight. {stairs['free_flights']} free flight(s) at each address; ${stairs['rate_per_cuft']:.2f} per cu ft per additional flight. Stairs inside the house or apartment are excluded.", 'NoteEstimate'))
        for row in stairs['locations']:
            answer = f"{row['flights']} flight(s); charge {money(row['total'])}" if row['flights'] is not None else 'Not answered - stair charges may apply'
            story.append(p(row['location'].title() + ': ' + answer, 'NoteEstimate'))
    if data.get('storage'):
        storage = data['storage']
        story.append(p('Delivery availability and storage', 'SectionEstimate'))
        story.append(p(storage['question']))
        story.append(p('Earliest available date: ' + (storage.get('available_date') or 'Not answered'), 'NoteEstimate'))
        story.append(p(f"First {storage['free_days']} days after pickup free; ${storage['rate_per_cuft']:.2f} per cu ft for each additional {storage['period_days']} days or part thereof.", 'NoteEstimate'))
        if storage['valid']:
            story.append(p(f"{storage['paid_periods']} paid period(s). Storage charge: {money(storage['total'])}.", 'NoteEstimate'))
        else:
            story.append(p('A valid earliest delivery date is needed to determine storage charges.', 'NoteEstimate'))
    if data.get('shuttle'):
        shuttle = data['shuttle']
        story.append(p('Delivery truck access', 'SectionEstimate'))
        if shuttle['automatic']:
            story.append(p('Delivery shuttle required for this delivery area.', 'NoteEstimate'))
        else:
            story.append(p(shuttle['question']))
            answer = shuttle.get('answer')
            story.append(p('Answer: ' + ('Yes' if answer is True else 'No - shuttle required' if answer is False else 'Not answered - shuttle charges may apply'), 'NoteEstimate'))
    story.append(PageBreak())
    story.append(p('Declared inventory', 'SectionEstimate'))
    story.append(p('Volume and weight reflect items going. Item answers and instructions appear directly below the relevant item. A dash means the weight was not recorded.', 'NoteEstimate'))
    rooms = defaultdict(list)
    entries_all = list(inventory_entries(rows, data.get('item_questions') or []))
    for entry in entries_all:
        rooms[entry['room']].append(entry)
    def totals(entries):
        going = sum(e['quantity'] for e in entries if not e['excluded'])
        not_going = sum(e['quantity'] for e in entries if e['excluded'])
        volume = sum(e['cuft'] for e in entries)
        weight = f"{sum(e['weight'] or 0 for e in entries):,.2f} lbs" if all(e['weight'] is not None for e in entries) else 'Not fully recorded'
        return f"Going: {going}   |   Not going: {not_going}   |   Volume: {volume:,.2f} cu ft   |   Weight: {weight}"
    for room, entries in rooms.items():
        body = [[p(room + '\n' + totals(entries)), '', '', '', ''],
                [p(label, 'NoteEstimate') for label in ['ITEM DESCRIPTION', 'GOING', 'NOT GOING', 'VOL (cu ft)', 'WT (lbs)']]]
        commands = [('SPAN', (0, 0), (-1, 0)), ('BACKGROUND', (0, 0), (-1, 1), colors.HexColor('#edf2f5'))]
        for entry in entries:
            item_row = len(body)
            body.append([p(entry['label']), p(str(0 if entry['excluded'] else entry['quantity']), 'RightEstimate'),
                         p(str(entry['quantity'] if entry['excluded'] else 0), 'RightEstimate'),
                         p(f"{entry['cuft']:,.2f}", 'RightEstimate'),
                         p(f"{entry['weight']:,.2f}" if entry['weight'] is not None else '-', 'RightEstimate')])
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
                    body.append([p(note, 'NoteEstimate'), '', '', '', ''])
                    commands += [('SPAN', (0, row_index), (-1, row_index)),
                                 ('BACKGROUND', (0, row_index), (-1, row_index), colors.HexColor('#f8fafb'))]
            if entry['questions']:
                commands.append(('NOSPLIT', (0, item_row), (-1, item_row + 1)))
        room_table = Table(body, colWidths=[272, 50, 58, 71, 71], repeatRows=2, splitInRow=1, hAlign='LEFT')
        room_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), .4, colors.HexColor('#bdc9d0')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ] + commands))
        story += [room_table, Spacer(1, 14)]
    story.append(p('Inventory totals', 'SectionEstimate'))
    story.append(p(totals(entries_all)))
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
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#dce4e8'))
        canvas.line(45, 39, 567, 39)
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(muted)
        if doc.page > 1:
            canvas.drawString(45, 770, 'MOVING ESTIMATE - CONTINUED')
            canvas.drawRightString(567, 770, str(data.get('name') or '')[:70])
        canvas.drawString(45, 26, 'Moving estimate | ' + str(data.get('move_date') or 'Date pending'))
        canvas.drawRightString(567, 26, f'Page {doc.page}')
        canvas.restoreState()
    SimpleDocTemplate(output, pagesize=letter, rightMargin=45, leftMargin=45, topMargin=38,
                      bottomMargin=53, title='Moving estimate', author=company.get('name') or '').build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
