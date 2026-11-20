import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from estimate_pdf import build_estimate_pdf, inventory_entries
from estimate_pdf import compact_inventory_entries


def test_compact_inventory_groups_only_matching_items_and_answers():
    rows = [{'name': 'Gun Safe', 'room': 'Bedroom', 'amount': 2, 'cuft': 200, 'weight': 1400}]
    rows += [{'name': 'Box', 'room': 'Bedroom', 'amount': 1, 'cuft': 3, 'weight': 21} for _ in range(20)]
    entries = compact_inventory_entries(inventory_entries(rows, sample()['item_questions']))
    assert len(entries) == 3
    assert [entry['excluded'] for entry in entries[:2]] == [False, True]
    assert entries[-1]['quantity'] == 20
    assert entries[-1]['cuft'] == 60
    assert entries[-1]['weight'] == 420


def sample():
    return dict(name='Sample Customer', phone='202-555-0100', email='customer@example.com',
                move_date='2026-09-29', pickup='Rockville, MD', delivery='Phoenix, AZ',
                company_details={'name': 'Sample Moving Company', 'phone': '202-555-0199'},
                estimate={'price': '1910', 'cuft': '100', 'charges': [
                    {'name': 'Transportation', 'description': 'Minimum transportation charge', 'total': 1500},
                    {'name': 'Packing', 'description': '286 cu ft at $1 per cu ft', 'total': 286},
                    {'name': 'Additional service', 'description': 'Selected service', 'total': 124}]},
                packing_package={'minimum_cubic_feet': 286}, item_questions=[
                    {'item_index': 0, 'unit_index': 0, 'question': 'Will it be empty before the movers arrive?',
                     'saved': {'answer': 'Yes', 'action': 'none'}},
                    {'item_index': 0, 'unit_index': 1, 'question': 'Will it be empty before the movers arrive?',
                     'saved': {'answer': 'No', 'action': 'exclude', 'notice': 'Remove everything inside.', 'acknowledged': True}}])


def test_declared_inventory_includes_service_counts_and_defaults():
    import pymupdf
    data = sample()
    data['item_questions'] = []
    data['item_services'] = {'tv': [dict(id='unmount', options=['Owner Unmounts', 'Movers Unmount'], default='Owner Unmounts')]}
    rows = [dict(name='TV Flat Screen (80 - 100)', catalog_item_id='tv', room='Bedroom', amount=2,
                 cuft=40, weight=280, selections={'unmount': {'Owner Unmounts': 1, 'Movers Unmount': 1}}),
            dict(name='TV Flat Screen (80 - 100)', catalog_item_id='tv', room='Bedroom', amount=3, cuft=60, weight=420)]
    entries = compact_inventory_entries(inventory_entries(rows, [], data['item_services']))
    assert len(entries) == 2
    assert entries[0]['service_notes'] == ['Movers Unmount: 1', 'Owner Unmounts: 1']
    assert entries[1]['service_notes'] == ['Owner Unmounts: 3']
    doc = pymupdf.open(stream=build_estimate_pdf(data, rows), filetype='pdf')
    text = ''.join(page.get_text() for page in doc)
    assert 'Movers Unmount: 1' in text and 'Owner Unmounts: 3' in text
    assert sum(entry['cuft'] for entry in entries) == 100


def test_individual_answers_and_volume_are_not_combined():
    rows = [{'name': 'Gun Safe', 'room': 'Bedroom', 'amount': 2, 'cuft': 200, 'weight': 1400}]
    entries = list(inventory_entries(rows, sample()['item_questions']))
    assert [e['cuft'] for e in entries] == [100, 0]
    assert [e['weight'] for e in entries] == [700, 0]
    assert [e['excluded'] for e in entries] == [False, True]
    assert [e['label'] for e in entries] == ['Gun Safe (1 of 2)', 'Gun Safe (2 of 2)']
    assert rows[0]['cuft'] == 200


def test_pending_exclusion_keeps_volume():
    data = sample()
    data['item_questions'][1]['saved']['pending'] = True
    entries = list(inventory_entries([{'name': 'Safe', 'amount': 2, 'cuft': 200}], data['item_questions']))
    assert sum(e['cuft'] for e in entries) == 200
    assert all(e['weight'] is None for e in entries)


def test_general_instructions_attach_only_to_selected_inventory_unit():
    rows = [{'name': 'Mower', 'amount': 2, 'cuft': 20}]
    question = {'all_items': True, 'question': 'Any gas-powered items?',
                'items': [{'id': '0:0', 'item_index': 0, 'unit_index': 0},
                          {'id': '0:1', 'item_index': 0, 'unit_index': 1}],
                'saved': {'answer': 'Yes', 'action': 'prepare', 'selected_items': ['0:1'],
                          'notice': 'Empty the gas tank.', 'acknowledged': True}}
    entries = list(inventory_entries(rows, [question]))
    assert entries[0]['questions'] == []
    assert entries[1]['questions'][0]['saved']['notice'] == 'Empty the gas tank.'
    assert sum(entry['cuft'] for entry in entries) == 20
    data = sample()
    data['item_questions'] = [question]
    assert build_estimate_pdf(data, rows).startswith(b'%PDF-')


def test_pdf_with_long_instructions_and_many_rooms():
    data = sample()
    data['item_questions'][1]['saved']['notice'] = 'Empty the safe before moving. ' * 150
    rows = [{'name': 'Gun Safe', 'room': 'Bedroom', 'amount': 2, 'cuft': 200}]
    rows += [{'name': f'Chair <special> & item {i}', 'room': f'Room {i // 20}', 'amount': 1, 'cuft': 5} for i in range(100)]
    pdf = build_estimate_pdf(data, rows)
    assert pdf.startswith(b'%PDF-')
    assert len(pdf) > 5000


def test_fully_discounted_stairs_moves_from_breakdown_to_details():
    import pymupdf
    from routes.pricing import customer_packing_charge_id
    data=sample()
    data['job_id']='job-1'
    data['estimate']['charges'].append({'id':customer_packing_charge_id('job-1','stairs:pickup'),'name':'Pickup stairs','description':'One additional flight',
        'subtotal':57.2,'discount_amount':57.2,'discount_percent':100,'total':0})
    data['stairs']={'steps_per_flight':13,'free_flights':1,'rate_per_cuft':0.2,'locations':[
        {'location':'pickup','flights':2,'subtotal':57.2,'discount_amount':57.2,'discount_percent':100,'total':0}]}
    doc=pymupdf.open(stream=build_estimate_pdf(data,[]),filetype='pdf')
    text=' '.join(' '.join(page.get_text().split()) for page in doc)
    # Not in the page-one breakdown; its row in the services table shows the answer and the discounted charge.
    # The breakdown adds the fees' discounts up under their total.
    assert 'Pickup stairs' not in text and 'Before discount' not in text
    assert 'Stairs - pickup' in text and '2 flights $57.20 $0.00 Discount: -$57.20 (100%)' in text
    assert 'Discount -$57.20' in text and '% off' not in text


def test_material_price_list_is_appended_with_no_packing_and_does_not_change_total():
    import copy
    import pymupdf
    data = sample()
    data['packing_package'].update(selection={'mode': 'none'}, material_rates=[
        {'name': 'Mattress Bag (Queen)', 'mattress_size': 'queen', 'material_price': '26', 'packing_price': '12', 'unpacking_price': '15'},
        {'name': 'Book Box', 'capacity': '2', 'capacity_unit': 'cuft', 'material_price': '9', 'packing_price': '5'},
    ])
    original = copy.deepcopy(data)
    doc = pymupdf.open(stream=build_estimate_pdf(data, []), filetype='pdf')
    text = doc[-1].get_text()
    assert 'Materials price list' in text
    assert 'Queen mattress' in text and '2 cu ft' in text
    assert '$26.00' in text and '$12.00' in text and '$9.00' in text
    assert 'Unpacking' not in text and '$15.00' not in text
    assert '$1,910.00' in doc[0].get_text()
    assert data == original


def test_material_table_repeats_headers_across_pages():
    import pymupdf
    data = sample()
    data['packing_package']['material_rates'] = [
        {'name': f'Material {i} with a longer description that wraps onto another line',
         'material_price': i, 'packing_price': '0'} for i in range(80)]
    doc = pymupdf.open(stream=build_estimate_pdf(data, []), filetype='pdf')
    material_pages = [page.get_text() for page in doc][1:]
    assert len(material_pages) > 1
    assert all('Material / unit' in text for text in material_pages)
    assert 'Material 79' in material_pages[-1]


def test_work_order_adds_notes_and_payments_after_the_signature():
    import pymupdf
    data = sample()
    data['signature'] = {'name': 'Sample Customer', 'signed_at': '2026-11-04T15:00:00Z',
                         'strokes': [[[0.1, 0.5], [0.9, 0.6]]], 'estimate_id': 'copy'}
    work_order = {'payments': [{'amount': 900, 'takenByUser': 'Rep', 'paidAt': '2026-11-02'}],
                  'internal_notes': 'Gate code', 'foreman_notes': 'Two trucks'}
    text = ''.join(page.get_text() for page in pymupdf.open(stream=build_estimate_pdf(data, [], work_order=work_order), filetype='pdf'))
    assert 'WORK ORDER' in text
    assert 'Client signature' not in text
    assert text.index('TOTAL ESTIMATED PRICE') < text.index('Team notes') < text.index('Gate code') < text.index('Payments')
    assert 'Total estimate' in text and 'Balance due' in text and '$1,010.00' in text
    assert 'FOREMAN NOTES' in text
    # No notes: no Team notes section.
    empty = dict(work_order, internal_notes='', foreman_notes=None)
    text = ''.join(page.get_text() for page in pymupdf.open(stream=build_estimate_pdf(data, [], work_order=empty), filetype='pdf'))
    assert 'Team notes' not in text and 'Payments' in text


def test_discounted_extra_stop_shows_its_discount_in_the_fees_table():
    import base64
    import uuid
    import pymupdf
    data = sample()
    data['job_id'] = 'job'
    row_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'extra-stop:job:delivery:Stop address'))
    charge_id = 'extra-stop:' + base64.urlsafe_b64encode(uuid.UUID(row_id).bytes).decode().rstrip('=')
    data['extra_stops'] = {'locations': [{'location': 'delivery', 'answer': True, 'free_miles': 0, 'stop_fee': 50, 'per_mile': 5,
                                          'stops': [{'id': row_id, 'address': 'Stop address', 'miles': 100.0, 'total': 550}]}]}
    data['estimate']['charges'].append({'id': charge_id, 'name': 'Extra delivery stop 1', 'description': 'Stop address',
                                        'subtotal': 550, 'discount_amount': 275, 'total': 275})
    text = ' '.join(' '.join(page.get_text().split()) for page in pymupdf.open(stream=build_estimate_pdf(data, []), filetype='pdf'))
    assert 'Stop address - 100.0 miles $550.00 $275.00 Discount: -$275.00 (50%)' in text
    assert 'Extra delivery stop 1' not in text  # shown once, in its stops row


def test_every_kind_of_fee_shows_once_with_its_discount():
    """Each fee the pricing code creates, by its real id, appears once in the fees table, discounted where it is."""
    import base64
    import json
    import uuid
    import pymupdf
    from routes.pricing import customer_packing_charge_id as fee_id
    data = sample()
    data['job_id'] = 'job'
    stop_row = str(uuid.uuid5(uuid.NAMESPACE_URL, 'extra-stop:job:delivery:Stop A'))
    ids = {
        'stop': 'extra-stop:' + base64.urlsafe_b64encode(uuid.UUID(stop_row).bytes).decode().rstrip('='),
        'elevator': fee_id('job', 'elevator:pickup'), 'carry': fee_id('job', 'long_carry:delivery'), 'stairs': fee_id('job', 'stairs:pickup'),
        'storage': fee_id('job', 'storage-periods'), 'shuttle': fee_id('job', 'shuttle'), 'package': fee_id('job', 'full-packing'),
        'item': fee_id('job', 'piano'), 'origin': fee_id('job', 'origin-mileage'), 'delivery': fee_id('job', 'delivery-mileage'),
        'service': str(uuid.uuid5(uuid.NAMESPACE_URL, 'item-service:job:' + json.dumps(['tv', 'unmount', 'Movers']))),
        'pending': str(uuid.uuid5(uuid.NAMESPACE_URL, 'pending-charge:job:add_charges')),
    }
    names = {'stop': 'Extra delivery stop 1', 'elevator': 'Pickup elevator', 'carry': 'Delivery long carry', 'stairs': 'Pickup stairs',
             'storage': 'Storage', 'shuttle': 'Delivery shuttle', 'package': 'Full packing', 'item': 'Piano Crating',
             'origin': 'Origin mileage fee', 'delivery': 'Delivery mileage fee', 'service': 'TV Unmount — Movers', 'pending': 'Item services'}
    # Each fee is $100, discounted $10 under its own name; the pending one has no price yet.
    data['estimate']['charges'] = [{'id': ids[key], 'name': names[key], 'subtotal': 100, 'discount_amount': 10, 'total': 90,
                                    'description': f'{key} detail | {key} deal: -$10.00'} for key in ids if key != 'pending']
    data['estimate']['charges'].append({'id': ids['pending'], 'name': names['pending'], 'subtotal': 0, 'discount_amount': 0, 'total': 0,
                                        'pending': True, 'description': 'Calculation pending: no rate'})
    data['discount_titles'] = {ids[key]: f'{key} deal' for key in ids}
    data['extra_stops'] = {'locations': [{'location': 'delivery', 'answer': True, 'free_miles': 0, 'stop_fee': 50, 'per_mile': 5,
                                          'stops': [{'id': stop_row, 'address': 'Stop A', 'miles': 10.0, 'total': 100}]}]}
    data['elevator'] = {'terms': 'terms', 'locations': [{'location': 'pickup', 'uses_elevator': True}]}
    data['long_carry'] = {'included_feet': 75, 'rate_per_cuft': 0.2, 'increment_feet': 75, 'locations': [{'location': 'delivery', 'distance_feet': 150}]}
    data['stairs'] = {'steps_per_flight': 13, 'free_flights': 1, 'rate_per_cuft': 0.2, 'locations': [{'location': 'pickup', 'flights': 2}]}
    data['storage'] = {'available_date': '2026-12-31', 'free_days': 30, 'rate_per_cuft': 0.5, 'period_days': 30, 'valid': True, 'paid_periods': 1}
    data['shuttle'] = {'automatic': False, 'answer': False}
    text = ' '.join(' '.join(page.get_text().split()) for page in pymupdf.open(stream=build_estimate_pdf(data, []), filetype='pdf'))
    fees = text[text.index('SERVICE DETAILS CHARGE'):text.index('TOTAL ADDITIONAL SERVICES AND FEES')]
    for key in ids:
        if key == 'pending':
            assert 'Item services Calculation pending: no rate Pending' in fees
        else:
            assert fees.count(f'{key} deal: -$10.00 (10%)') == 1, key
            assert f'| {key} deal' not in fees, key  # the discount shows in the charge cell, not also in the description
    # The breakdown adds the fees' own discounts up once: 11 fees at $100, $10 off each.
    assert ('Additional services and fees See Additional services and fees (includes pending charges) $1,100.00 $990.00 Discount -$110.00'
            in text)


def test_fee_rows_are_grouped_by_the_customer_page_tabs():
    """The PDF's fee rows sit under the same tabs the customer page groups its price lines by, each with its total;
    every row it had is still there."""
    from uuid import uuid5, NAMESPACE_URL
    from estimate_pdf import _kit, _services_table
    from fee_tabs import fee_tabs
    service_id = lambda key: str(uuid5(NAMESPACE_URL, f'customer-packing:job:{key}'))
    data = dict(job_id='job', elevator={'terms': '$150 per elevator', 'locations': [
                    {'location': 'pickup', 'uses_elevator': False}, {'location': 'delivery', 'uses_elevator': True}]},
                packing_items=[{'label': 'TV Flat Screen (80 - 100)', 'services': [{'kind': '— Movers Unmount', 'price': 286}]}],
                packing_package={'box_items': [{'label': 'Kitchen'}]},
                estimate={'price': '1000', 'charges': [
                    {'id': service_id('elevator:delivery'), 'name': 'Elevator', 'description': 'Elevator at delivery', 'total': 75},
                    {'id': service_id('tv'), 'name': 'TV Flat Screen (80 - 100) — Movers Unmount', 'description': '1 item', 'total': 286},
                    {'id': service_id('mirror'), 'name': 'Mirror Boxing', 'description': 'Mirror box', 'total': 35},
                    {'id': service_id('sofa'), 'name': 'Sofa - 5 Cushions Boxing', 'description': 'Crate', 'total': 148},
                    {'id': service_id('kitchen'), 'name': 'Kitchen Packing', 'description': 'Boxes', 'total': 90},
                    {'id': service_id('fee'), 'name': 'Mileage fee', 'description': 'Long drive', 'total': 40}]})
    styles, p, table = _kit(9)
    def text(cell):
        if isinstance(cell, list):
            return ' '.join(text(item) for item in cell)
        return getattr(cell, 'text', cell) or ''
    cells = [[text(cell) for cell in row] for row in _services_table(data, p, table, styles)._cellvalues]
    flat = [row[0] for row in cells]
    def index(value):
        return next(i for i, row in enumerate(flat) if value in row)
    # A line of no tab first, then the tabs in the page's order, each title before its rows.
    assert index('Mileage fee') < index('<b>Elevator</b>') < index('Elevator - pickup') < index('Elevator - delivery')
    assert index('Elevator - delivery') < index('<b>Packing &amp; crating</b>') < index('Movers Unmount')
    assert index('Movers Unmount') < index('<b>Packing services - Item protection</b>') < index('Mirror Boxing') < index('Sofa - 5')
    assert index('Sofa - 5') < index('<b>Packing services - Boxes</b>') < index('Kitchen Packing')
    # Each tab's total, as the page shows it.
    assert '$183.00' in cells[index('<b>Packing services - Item protection</b>')][2]
    assert '$75.00' in cells[index('<b>Elevator</b>')][2]
    # The page gets the very same tabs.
    tabs = fee_tabs(data)
    assert tabs[service_id('mirror')] == 'package:protection' and tabs[service_id('kitchen')] == 'package:boxes'
    assert tabs[service_id('tv')] == 'bulky:' and tabs[service_id('elevator:delivery')] == 'elevator:' and service_id('fee') not in tabs


@pytest.mark.parametrize('fillers,boxes', [(n, 3) for n in range(10, 40)] + [(5, 45)])
def test_a_tab_is_not_split_across_pages(fillers, boxes):
    """Wherever the page ends, a tab's title and its rows stay on one page; a tab too long for a page still prints."""
    from io import BytesIO
    from uuid import uuid5, NAMESPACE_URL
    from pypdf import PdfReader
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate
    from estimate_pdf import _kit, _services_table
    service_id = lambda key: str(uuid5(NAMESPACE_URL, f'customer-packing:job:{key}'))
    charges = [{'id': service_id(f'fee{i}'), 'name': f'Filler fee {i}', 'description': 'Fee', 'total': 10} for i in range(fillers)]
    charges += [{'id': service_id(f'box{i}'), 'name': f'Size{i} Packing', 'description': 'Boxes', 'total': 20} for i in range(boxes)]
    data = dict(job_id='job', packing_package={'box_items': [{'label': f'Size{i}'} for i in range(boxes)]},
                estimate={'price': '1', 'charges': charges})
    styles, p, table = _kit(9)
    out = BytesIO()
    SimpleDocTemplate(out, pagesize=letter).build([_services_table(data, p, table, styles)])
    pages = [page.extract_text() for page in PdfReader(BytesIO(out.getvalue())).pages]
    title = next(i for i, text in enumerate(pages) if 'Packing services - Boxes' in text)
    on_title_page = sum(f'Size{i} Packing' in pages[title] for i in range(boxes))
    if boxes <= 20:
        assert on_title_page == boxes
    else:
        assert on_title_page >= 1 and all(any(f'Size{i} Packing' in text for text in pages) for i in range(boxes))
