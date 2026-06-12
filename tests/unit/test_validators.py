import unittest
from core.validators import validate_klipper_pin, questionary_pin_validator

class TestValidators(unittest.TestCase):

    def test_valid_pins(self):
        valid = ["PA1", "^PC14", "!PB6", "^!PB7", "PC14.2", "gpio22", "ar2", "~PC13", "!^~PE5", "!^PA0"]
        for p in valid:
            with self.subTest(pin=p):
                self.assertTrue(validate_klipper_pin(p))
                self.assertTrue(questionary_pin_validator(p))

    def test_invalid_pins(self):
        invalid = ["", "   ", "PA1$", "P@1", "P A1", "PA-1", "PB6#", "!^", "~", "PA 0", "../bad"]
        for p in invalid:
            with self.subTest(pin=p):
                self.assertFalse(validate_klipper_pin(p))
                self.assertNotEqual(questionary_pin_validator(p), True)

if __name__ == "__main__":
    unittest.main()
