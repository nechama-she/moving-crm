"""Match complete North American phone numbers regardless of formatting."""
import re

from sqlalchemy import false, func


def phone_search_condition(column, search):
    text = search.strip()
    if not re.fullmatch(r"[+0-9().\s-]+", text):
        return false()
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return false()
    stored_digits = func.regexp_replace(column, r"\D", "", "g")
    return stored_digits.in_([digits, "1" + digits])
