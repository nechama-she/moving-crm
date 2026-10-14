"""Customer-facing move categories, including legacy and provider aliases."""


def normalize_move_type(value):
    raw = (value or '').strip()
    key = raw.lower().replace('_', ' ').replace('-', ' ')
    if key in {'local', 'intrastate', 'in state', 'within state', 'within the state'}:
        return 'Local'
    if key in {'long distance', 'interstate', 'out of state'}:
        return 'Long Distance'
    return raw
