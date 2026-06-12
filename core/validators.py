# core/validators.py
import re

def validate_klipper_pin(s: str) -> bool:
    """Validate a Klipper pin name.

    Leading/trailing whitespace is stripped before validation — " PA0" is
    treated as "PA0" and considered valid. Internal whitespace is rejected.
    Accepts optional prefix chars: !, ^, ~ (combinable, e.g. !^PA0).
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
