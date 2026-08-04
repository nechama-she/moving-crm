import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from assignment_conflicts import assignment_identifiers_match, normalize_assignment_phone


def test_phone_comparison_ignores_formatting_and_us_country_code():
    assert normalize_assignment_phone("+1 (917) 555-0123") == "9175550123"
    assert assignment_identifiers_match("(917) 555-0123", "", "1-917-555-0123", "")


def test_email_comparison_is_trimmed_and_case_insensitive():
    assert assignment_identifiers_match("", " Sales@Example.com ", "", "sales@example.com")


def test_phone_or_email_match_is_enough():
    assert assignment_identifiers_match("2025550199", "first@example.com", "2025550199", "different@example.com")
    assert assignment_identifiers_match("2025550100", "same@example.com", "2025550199", "SAME@example.com")


def test_blank_identifiers_do_not_match():
    assert not assignment_identifiers_match("", "", "", "")
