"""Packing and materials share storage but have independent save boundaries."""
def merge_packing(current, incoming, section):
    result = dict(current)
    keys = ('materials',) if section == 'materials' else ('full', 'partial', 'unpacking', 'items')
    for key in keys:
        if key in incoming:
            result[key] = incoming[key]
    return result
