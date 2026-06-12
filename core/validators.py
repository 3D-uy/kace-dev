# core/validators.py
import re
from typing import Union

# Covers standard Klipper pin formats (PA0, ^PB7, !gpio4, P0.10, etc.)
# CAN bus pins (can0:gpio4) are intentionally out of scope for now.
_PIN_RE = re.compile(r'^[!^~]*[A-Za-z0-9_.]+$')


def validate_klipper_pin(s: str) -> bool:
    """Validate a Klipper pin name.

    Leading/trailing whitespace is stripped before validation — " PA0" is
    treated as "PA0" and considered valid. Internal whitespace is rejected.
    Accepts optional prefix chars: !, ^, ~ (combinable, e.g. !^PA0).
    """
    if not s:
        return False
    return bool(_PIN_RE.match(s.strip()))


def questionary_pin_validator(value: str) -> Union[bool, str]:
    """Validator for questionary.text pin inputs."""
    if validate_klipper_pin(value):
        return True
    return "Invalid Klipper pin format. Use alphanumeric characters, dots, underscores, and optional prefixes (!, ^, ~)"
