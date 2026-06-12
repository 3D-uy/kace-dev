# core/validators.py
import re

def validate_klipper_pin(s: str) -> bool:
    """Validate that a string is a valid Klipper pin identifier.

    Klipper pin format allows pull-up (^), pull-down (~), and invert (!) prefixes
    in any order or combination, followed by an alphanumeric name which can also
    contain underscores or dots (e.g. PA1, PC14, ar2, gpio22, etc.).
    """
    if not s:
        return False
    # Strip whitespace
    s = s.strip()
    return bool(re.match(r'^[!^~]*[A-Za-z0-9_.]+$', s))


def questionary_pin_validator(value: str) -> bool | str:
    """Validator for questionary.text pin inputs."""
    if validate_klipper_pin(value):
        return True
    return "Invalid Klipper pin format. Use alphanumeric characters, dots, underscores, and optional prefixes (!, ^, ~)"
