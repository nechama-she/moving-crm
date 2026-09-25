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


def test_fully_discounted_stairs_remains_in_pdf():
    import pymupdf
    data=sample()
    data['estimate']['charges'].append({'name':'Pickup stairs','description':'One additional flight',
        'subtotal':57.2,'discount_amount':57.2,'discount_percent':100,'total':0})
    doc=pymupdf.open(stream=build_estimate_pdf(data,[]),filetype='pdf')
    text=''.join(page.get_text() for page in doc)
    assert 'Pickup stairs' in text and 'Before discount: $57.20' in text
    assert 'Discount (100%): -$57.20' in text and '$0.00' in text
