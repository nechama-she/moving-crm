"""Required saved answers before issuing a customer estimate PDF."""
def unanswered_questions(data, package_saved=True):
    missing = []
    for group in (data.get('extra_stops') or {}).get('locations', []):
        if group.get('answer') is None or (group.get('answer') and (not group.get('stops') or any(row.get('miles') is None for row in group['stops']))):
            missing.append('stops_' + group['location'])
    for key, field, step in [('elevator', 'uses_elevator', 'elevator'), ('long_carry', 'distance_feet', 'carry'), ('stairs', 'flights', 'stairs')]:
        for row in (data.get(key) or {}).get('locations', []):
            if key == 'long_carry':
                if row.get('unknown') and row.get('acknowledged'):
                    continue
                shuttle = data.get('shuttle') or {}
                if row['location'] == 'delivery' and shuttle and not shuttle.get('automatic') and shuttle.get('answer') is True:
                    continue
            if row.get(field) is None:
                missing.append('shuttle' if step == 'carry' and row['location'] == 'delivery' and data.get('shuttle') else step + '_' + row['location'])
    shuttle = data.get('shuttle')
    if shuttle and not shuttle.get('automatic') and shuttle.get('answer') is None:
        missing.append('shuttle')
    if data.get('storage') and not data['storage'].get('valid'):
        missing.append('storage')
    if any(row.get('selected') and not row.get('selected_service') for row in data.get('packing_items', [])):
        missing.append('bulky')
    if data.get('packing_package') and not package_saved:
        missing.append('package')
    for question in data.get('item_questions', []):
        saved = question.get('saved') or {}
        answer = next((row for row in question['answers'] if row['id'] == saved.get('answer_id')), None)
        if not answer or saved.get('pending') or (answer.get('acknowledge') and not saved.get('acknowledged')):
            missing.append('items')
            break
    return list(dict.fromkeys(missing))
