"""Phone numbers clients leave with their problems, kept as +<digits>."""

import re

# What people put between the digits: spaces, dashes, brackets, dots.
_SEPARATORS = re.compile(r"[\s\-().]")
_DIGITS = re.compile(r"[0-9]{7,15}")
UZ_CODE = "998"
# An Uzbek number: the code and 9 digits (operator and subscriber).
UZ_LENGTH = 12


def parse_phone(text: str) -> str | None:
    """+998901234567 from +998 90 123-45-67, 998901234567 or 90 123 45 67 (an Uzbek number
    without its code). A number of another country is taken with its + code. None: not a number."""
    raw = _SEPARATORS.sub("", text)
    plus = raw.startswith("+")
    digits = raw.removeprefix("+")
    if not _DIGITS.fullmatch(digits):
        return None
    if not plus and len(digits) == UZ_LENGTH - len(UZ_CODE):
        digits = UZ_CODE + digits
    elif not plus and not digits.startswith(UZ_CODE):
        return None  # without a + code it would be a guess
    if digits.startswith(UZ_CODE) and len(digits) != UZ_LENGTH:
        return None
    return "+" + digits


def format_phone(phone: str) -> str:
    """+998 90 123 45 67 for an Uzbek number; any other as stored."""
    digits = phone.removeprefix("+")
    if not (digits.startswith(UZ_CODE) and len(digits) == UZ_LENGTH):
        return phone
    local = digits[len(UZ_CODE) :]
    return f"+{UZ_CODE} {local[:2]} {local[2:5]} {local[5:7]} {local[7:]}"
