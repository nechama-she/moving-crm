"""Lead and job numbers: random digits with a check digit, and each job numbered from its lead."""
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import generate_lead_number, job_number, luhn_digit


def test_lead_numbers_are_eleven_digits_with_a_check_digit():
    numbers = {generate_lead_number() for _ in range(2000)}
    # Random, not counting up: 2000 draws give 2000 different numbers.
    assert len(numbers) == 2000
    for number in numbers:
        assert len(number) == 11 and number.isdigit() and number[0] != '0'
        assert luhn_digit(number[:-1]) == number[-1]


def test_check_digit_catches_a_mistyped_or_swapped_digit():
    # The Luhn digit of a known card number's first fifteen digits.
    assert luhn_digit('411111111111111') == '1'
    number = generate_lead_number()
    mistyped = number[:3] + str((int(number[3]) + 1) % 10) + number[4:]
    assert luhn_digit(mistyped[:-1]) != mistyped[-1]


def test_job_number_is_the_lead_number_and_the_job_order():
    assert job_number(SimpleNamespace(number='48213075526'), SimpleNamespace(job_order=2)) == '48213075526-2'
