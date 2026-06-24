import re


HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def normalize_company_color(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if not raw.startswith("#"):
        raw = f"#{raw}"
    if not HEX_COLOR_RE.fullmatch(raw):
        return None
    return raw.lower()


def generate_company_color(name: str | None) -> str:
    normalized_name = (name or "company").strip().lower() or "company"
    digest = _fnv1a_32(normalized_name)
    hue = ((digest[0] << 8) | digest[1]) % 360
    saturation = 58 + (digest[2] % 15)
    lightness = 42 + (digest[3] % 12)
    return _hsl_to_hex(hue, saturation / 100.0, lightness / 100.0)


def resolve_company_color(name: str | None, color: str | None) -> str:
    return normalize_company_color(color) or generate_company_color(name)


def _hsl_to_hex(hue: int, saturation: float, lightness: float) -> str:
    chroma = (1 - abs(2 * lightness - 1)) * saturation
    hue_section = hue / 60.0
    x_val = chroma * (1 - abs(hue_section % 2 - 1))

    if 0 <= hue_section < 1:
        red1, green1, blue1 = chroma, x_val, 0
    elif 1 <= hue_section < 2:
        red1, green1, blue1 = x_val, chroma, 0
    elif 2 <= hue_section < 3:
        red1, green1, blue1 = 0, chroma, x_val
    elif 3 <= hue_section < 4:
        red1, green1, blue1 = 0, x_val, chroma
    elif 4 <= hue_section < 5:
        red1, green1, blue1 = x_val, 0, chroma
    else:
        red1, green1, blue1 = chroma, 0, x_val

    match = lightness - chroma / 2
    red = round((red1 + match) * 255)
    green = round((green1 + match) * 255)
    blue = round((blue1 + match) * 255)
    return f"#{red:02x}{green:02x}{blue:02x}"


def _fnv1a_32(value: str) -> bytes:
    hash_value = 2166136261
    for char in value:
        hash_value ^= ord(char)
        hash_value = (hash_value * 16777619) & 0xFFFFFFFF
    return bytes(
        (
            (hash_value >> 24) & 0xFF,
            (hash_value >> 16) & 0xFF,
            (hash_value >> 8) & 0xFF,
            hash_value & 0xFF,
        )
    )