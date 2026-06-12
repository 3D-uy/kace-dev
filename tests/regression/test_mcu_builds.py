import os
import shutil
import subprocess
import tempfile
import unittest

from firmware.builder import build_firmware_orchestrator
from firmware.derivation import derive_config


class TestMCUBuilds(unittest.TestCase):
    def setUp(self):
        # We need a real Klipper clone to compile firmware.
        self.klipper_path = os.path.expanduser("~/klipper")
        if not os.path.exists(self.klipper_path):
            print("Cloning Klipper for compilation tests...", flush=True)
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "https://github.com/Klipper3d/klipper.git",
                    self.klipper_path,
                ],
                check=True,
            )

        self.output_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.output_dir.cleanup()

    def _run_build_test(self, mcu, hint, expected_filename, compiler_binary):
        # Check if compiler is available in the environment
        if not shutil.which(compiler_binary) or not shutil.which("make"):
            self.skipTest(f"Compiler {compiler_binary} or make not found")

        # 1. Derive configuration
        config_dict = derive_config(mcu, hint=hint)

        # 2. Bypass /usr/local/bin/make by renaming it temporarily if it exists
        mock_make_path = "/usr/local/bin/make"
        backup_make_path = "/usr/local/bin/make.bak"
        renamed = False
        if os.path.exists(mock_make_path):
            try:
                shutil.move(mock_make_path, backup_make_path)
                renamed = True
            except Exception as e:
                print(f"Warning: could not move mock make: {e}", flush=True)

        try:
            # 3. Call build_firmware_orchestrator
            result = build_firmware_orchestrator(
                mcu_path=f"/dev/serial/by-id/usb-Klipper_{mcu}_test-if00",
                derived_mcu=mcu,
                hint=hint,
                klipper_path=self.klipper_path,
                output_dir=self.output_dir.name,
                config_dict=config_dict,
            )

            # 4. Assert success and verify output artifact
            self.assertEqual(
                result.get("status"),
                "success",
                f"Build failed for {mcu}: {result.get('message')}",
            )
            self.assertEqual(result.get("firmware"), expected_filename)

            dest_path = result.get("path")
            self.assertIsNotNone(dest_path)
            self.assertTrue(os.path.exists(dest_path))
            self.assertGreater(
                os.path.getsize(dest_path),
                0,
                f"Generated binary {expected_filename} for {mcu} must not be empty",
            )

        finally:
            # Restore mock make
            if renamed and os.path.exists(backup_make_path):
                try:
                    shutil.move(backup_make_path, mock_make_path)
                except Exception as e:
                    print(f"Warning: could not restore mock make: {e}", flush=True)

    def test_lpc1769_build(self):
        """Verify LPC1769 builds successfully to klipper.bin."""
        self._run_build_test("lpc1769", "usb", "klipper.bin", "arm-none-eabi-gcc")

    def test_stm32f103_build(self):
        """Verify STM32F103 builds successfully to klipper.bin."""
        self._run_build_test("stm32f103", "usb", "klipper.bin", "arm-none-eabi-gcc")

    def test_stm32f446_build(self):
        """Verify STM32F446 builds successfully to klipper.bin."""
        self._run_build_test("stm32f446", "usb", "klipper.bin", "arm-none-eabi-gcc")

    def test_rp2040_build(self):
        """Verify RP2040 builds successfully to klipper.uf2."""
        self._run_build_test("rp2040", "usb", "klipper.uf2", "arm-none-eabi-gcc")

    def test_atmega2560_build(self):
        """Verify AVR ATmega2560 builds successfully to klipper.elf.hex."""
        self._run_build_test("atmega2560", "uart", "klipper.elf.hex", "avr-gcc")


if __name__ == "__main__":
    unittest.main()
