"""Shared phone normalization helpers."""

import re


def normalize_digits(phone: str) -> str:
    """Strip everything except digits from a phone number."""
    return re.sub(r"\D", "", str(phone or ""))


def phone_variants(phone: str, include_formatted: bool = True) -> list[str]:
    """Generate common phone number formats to try as lookup keys."""
    digits = normalize_digits(phone)
    variants: set[str] = set()

    if len(digits) == 11 and digits.startswith("1"):
        d10 = digits[1:]
        variants.update({f"+{digits}", digits, d10, f"+1{d10}"})
        if include_formatted:
            variants.update({f"({d10[:3]}) {d10[3:6]}-{d10[6:]}", f"{d10[:3]}-{d10[3:6]}-{d10[6:]}"})
    elif len(digits) == 10:
        variants.update({f"+1{digits}", f"1{digits}", digits})
        if include_formatted:
            variants.update({f"({digits[:3]}) {digits[3:6]}-{digits[6:]}", f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"})
    else:
        raw = str(phone or "").strip()
        if raw:
            variants.add(raw)
        if digits:
            variants.update({digits, f"+{digits}"})

    return list(variants)
