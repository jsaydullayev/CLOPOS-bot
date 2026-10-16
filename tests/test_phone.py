"""Phone numbers as clients type them."""

import pytest

from bot.utils.phone import format_phone, parse_phone


@pytest.mark.parametrize(
    ("typed", "phone"),
    [
        ("+998 90 123 45 67", "+998901234567"),
        ("998901234567", "+998901234567"),
        ("90 123-45-67", "+998901234567"),  # an Uzbek number without its code
        ("(90) 123.45.67", "+998901234567"),
        ("+7 916 123 45 67", "+79161234567"),  # another country, with its + code
        ("salom", None),
        ("123", None),
        ("+998 90 123 45", None),  # an Uzbek number one digit short
        ("8 916 123 45 67", None),  # no + code: whose number it is would be a guess
        ("+99890123456²", None),
    ],
)
def test_parse_phone(typed: str, phone: str | None) -> None:
    assert parse_phone(typed) == phone


def test_format_phone() -> None:
    assert format_phone("+998901234567") == "+998 90 123 45 67"
    assert format_phone("+79161234567") == "+79161234567"
