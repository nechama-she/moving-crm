"""Pieces and boxes in an inventory, by the same rules as the customer page (inventoryPieces.ts, inventoryBoxes.ts)."""
import re

_PIECES = re.compile(r'\b(\d+)\s*[-–—]?\s*pieces?\b', re.I)
_NOT_BOX = re.compile(r'\bbox\s*springs?\b|\blitter\b|\b(?:bookshelf|bookcase|cabinet|dresser|shelving)\b', re.I)
_BOX = re.compile(r'\bbox(?:es)?\b|\bbins?\b|\bbinssmall\b|\btotes?\b|\bsuit\s*cases?\b|\bduff(?:el|le)\s*bags?\b|\bamazon\s+bags?\b'
                  r'|\b(?:moving|storage|packing|garment)\s+bags?\b|\bluggage\b|\bdish\s*packs?\b|\bcartons?\b', re.I)


def pieces_per_item(name):
    """Explicit piece counts in item names; otherwise one piece per inventory unit."""
    match = _PIECES.search(name or '')
    pieces = int(match[1]) if match else 1
    return pieces if pieces > 0 else 1


def is_box(name):
    return not _NOT_BOX.search(name or '') and bool(_BOX.search(name or ''))
