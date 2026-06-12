import unittest
from unittest.mock import patch, MagicMock
from core.wizard import run_wizard
from core.exceptions import WizardExit

class TestWizard(unittest.TestCase):

    @patch("questionary.select")
    @patch("core.wizard.discover_mcu")
    @patch("core.wizard.fetch_config_list")
    def test_wizard_exit_on_quit(self, mock_fetch, mock_mcu, mock_select):
        """Verify that choosing Quit raises WizardExit exception."""
        mock_mcu.return_value = {"mcu_path": "/dev/serial/by-id/mock", "derived_mcu": "stm32f103"}
        mock_fetch.return_value = ["printer-mock.cfg"]
        
        # Mock questionary select to return __quit__
        mock_ask = MagicMock(return_value="__quit__")
        mock_select.return_value.ask = mock_ask
        
        user_data = {
            "printer_profile": "Custom / Scratch Build",
            "board": "generic-bigtreetech-skr-v1.4.cfg",
            "kinematics": "cartesian",
            "x_size": "235",
            "y_size": "235",
            "z_size": "250",
            "probe": "None",
            "hotend_thermistor": "Generic 3950",
            "bed_thermistor": "Generic 3950",
            "driver_type": "None (Standard)",
            "driver_mode": "Standalone",
            "web_interface": "Mainsail",
            "z_motors": "1",
            "mcu_path": "/dev/serial/by-id/mock"
        }
        
        with self.assertRaises(WizardExit):
            run_wizard(user_data)

    @patch("questionary.select")
    @patch("questionary.text")
    def test_interactive_profile_review_edit_kinematics(self, mock_text, mock_select):
        """Verify interactive_profile_review can edit kinematics and updates correctly."""
        from core.wizard import interactive_profile_review
        
        defaults = {"kinematics": "cartesian"}
        parsed = {"printer": {"kinematics": "cartesian"}}
        user_data = {"kinematics": "cartesian"}
        
        # 1st select: choose 'edit'
        # 2nd select: choose 'kinematics'
        # 3rd select: choose 'corexy'
        # 4th select: choose 'save'
        # 5th select: choose 'confirm'
        mock_select.return_value.ask.side_effect = ["edit", "kinematics", "corexy", "save", "confirm"]
        
        result = interactive_profile_review(defaults, parsed, user_data)
        
        self.assertEqual(result, "confirm")
        self.assertEqual(user_data["kinematics"], "corexy")
        self.assertEqual(defaults["kinematics"], "corexy")
        self.assertEqual(parsed["printer"]["kinematics"], "corexy")

    @patch("questionary.select")
    @patch("questionary.text")
    def test_interactive_profile_review_edit_volume(self, mock_text, mock_select):
        """Verify interactive_profile_review can edit build volume and validates inputs."""
        from core.wizard import interactive_profile_review
        
        defaults = {"x_size": "235", "y_size": "235", "z_size": "250"}
        parsed = {}
        user_data = {"x_size": "235", "y_size": "235", "z_size": "250"}
        
        # Select edit -> volume -> save -> confirm
        mock_select.return_value.ask.side_effect = ["edit", "volume", "save", "confirm"]
        
        # Enter valid dimensions: 300, 300, 350
        mock_text.return_value.ask.side_effect = ["300", "300", "350"]
        
        result = interactive_profile_review(defaults, parsed, user_data)
        
        self.assertEqual(result, "confirm")
        self.assertEqual(user_data["x_size"], "300")
        self.assertEqual(user_data["y_size"], "300")
        self.assertEqual(user_data["z_size"], "350")
        self.assertEqual(parsed["stepper_x"]["position_max"], "300")
        self.assertEqual(parsed["stepper_y"]["position_max"], "300")
        self.assertEqual(parsed["stepper_z"]["position_max"], "350")

    @patch("questionary.select")
    @patch("core.wizard.fetch_raw_config")
    def test_run_z_motor_configuration_one_motor(self, mock_fetch, mock_select):
        """z_motors <= 1 should return True immediately without prompting."""
        from core.wizard import run_z_motor_configuration
        parsed = {}
        res = run_z_motor_configuration({"z_motors": "1"}, parsed)
        self.assertTrue(res)
        mock_fetch.assert_not_called()

    @patch("questionary.select")
    @patch("core.wizard.fetch_raw_config")
    def test_run_z_motor_configuration_success(self, mock_fetch, mock_select):
        """Verify successful mapping of extra Z stepper to E1 socket."""
        from core.wizard import run_z_motor_configuration
        mock_fetch.return_value = "[extruder1]\nstep_pin: PE1\ndir_pin: PE2\nenable_pin: PE3\n[tmc2209 extruder1]\nuart_pin: PD12\n"
        
        # Select choices: user picks E1 (extruder1)
        mock_select.return_value.ask.return_value = "extruder1"
        
        parsed = {
            "extruder1": {
                "step_pin": "PE1",
                "dir_pin": "PE2",
                "enable_pin": "PE3"
            },
            "tmc2209 extruder1": {
                "uart_pin": "PD12"
            }
        }
        user_data = {
            "z_motors": "2",
            "board": "generic-mock.cfg",
            "driver_type": "TMC2209",
            "driver_mode": "UART"
        }
        
        res = run_z_motor_configuration(user_data, parsed)
        self.assertTrue(res)
        self.assertIn("stepper_z1", parsed)
        self.assertEqual(parsed["stepper_z1"]["step_pin"], "PE1")
        self.assertIn("tmc2209 stepper_z1", parsed)
        self.assertEqual(parsed["tmc2209 stepper_z1"]["uart_pin"], "PD12")
        # extruder1 socket should be deleted (consumed)
        self.assertNotIn("extruder1", parsed)
        self.assertNotIn("tmc2209 extruder1", parsed)

    @patch("questionary.select")
    @patch("core.wizard.fetch_raw_config")
    def test_run_z_motor_configuration_back(self, mock_fetch, mock_select):
        """Selecting back on step 1 should return False."""
        from core.wizard import run_z_motor_configuration
        mock_fetch.return_value = "[extruder1]\n"
        mock_select.return_value.ask.return_value = "back"
        
        parsed = {}
        user_data = {"z_motors": "2", "board": "generic-mock.cfg"}
        
        res = run_z_motor_configuration(user_data, parsed)
        self.assertFalse(res)


class TestWizardRunner(unittest.TestCase):

    def test_runner_basic_flow_and_back_pruning(self):
        """Verify that WizardRunner handles forward steps and prunes state on back navigation."""
        from core.wizard import WizardRunner
        
        step_order = ["stepA", "stepB", "stepC"]
        steps_config = {
            "stepA": {
                "prompt": lambda ud: ud.update({"keyA": "valueA"}) or "valueA"
            },
            "stepB": {
                "prompt": lambda ud: ud.update({"keyB": "valueB"}) or "valueB",
                "next": lambda ans, ud: "stepC"
            },
            "stepC": {
                "prompt": lambda ud: "__back__" if ud.get("trigger_back") else "valueC"
            }
        }
        
        # Test 1: Straight forward execution
        user_data = {"trigger_back": False}
        runner = WizardRunner(steps_config, step_order, initial_data=user_data)
        res = runner.run("stepA")
        
        self.assertEqual(res["keyA"], "valueA")
        self.assertEqual(res["keyB"], "valueB")
        self.assertEqual(runner.history_stack, ["stepA", "stepB", "stepC"])
        
        # Test 2: Trigger back from stepC -> should prune stepB's keyB and stepC's inputs
        user_data = {"trigger_back": True}
        # Step C will return __back__, so runner will undo Step C, pop Step B from history stack, and undo Step B.
        # Then, since we went back to Step B, the runner will execute Step B again.
        # On this second execution of Step B, we will change trigger_back to False so it advances and stops.
        call_count = 0
        def step_b_prompt(ud):
            nonlocal call_count
            call_count += 1
            ud["keyB"] = f"valueB_run{call_count}"
            if call_count == 2:
                ud["trigger_back"] = False
            return "valueB"
            
        steps_config["stepB"]["prompt"] = step_b_prompt
        
        runner = WizardRunner(steps_config, step_order, initial_data=user_data)
        res = runner.run("stepA")
        
        # We expect stepB to be run twice, stepC run twice (first returned back, second succeeded)
        self.assertEqual(call_count, 2)
        self.assertEqual(res["keyA"], "valueA")
        self.assertEqual(res["keyB"], "valueB_run2")
        self.assertEqual(runner.history_stack, ["stepA", "stepB", "stepC"])

    def test_runner_snapshot_rollback(self):
        """Verify that rollback_to restores the user_data snapshot and trims history."""
        from core.wizard import WizardRunner
        
        step_order = ["stepA", "stepB", "stepC"]
        steps_config = {
            "stepA": {
                "prompt": lambda ud: ud.update({"keyA": "valueA"}) or "valueA"
            },
            "stepB": {
                "prompt": lambda ud: ud.update({"keyB": "valueB"}) or "valueB"
            },
            "stepC": {
                "prompt": lambda ud: ud.update({"keyC": "valueC"}) or "valueC"
            }
        }
        
        runner = WizardRunner(steps_config, step_order, initial_data={"initial": "state"})
        runner.run("stepA")
        
        # Verify initial execution state
        self.assertEqual(runner.user_data["keyA"], "valueA")
        self.assertEqual(runner.user_data["keyB"], "valueB")
        self.assertEqual(runner.user_data["keyC"], "valueC")
        self.assertEqual(runner.user_data["initial"], "state")
        
        # Rollback to stepB -> should revert changes made by stepB and stepC
        runner.rollback_to("stepB")
        
        self.assertEqual(runner.user_data["keyA"], "valueA")
        self.assertNotIn("keyB", runner.user_data)
        self.assertNotIn("keyC", runner.user_data)
        self.assertEqual(runner.user_data["initial"], "state")
        self.assertEqual(runner.history_stack, ["stepA"])
        self.assertNotIn("stepB", runner.snapshots)
        self.assertNotIn("stepC", runner.snapshots)

    def test_runner_retry_rollback(self):
        """Verify that returning __retry__ restores step snapshots without advancing."""
        from core.wizard import WizardRunner
        
        step_order = ["stepA"]
        
        call_count = 0
        def step_a_prompt(ud):
            nonlocal call_count
            call_count += 1
            ud["keyA"] = f"try_{call_count}"
            if call_count == 1:
                return "__retry__"
            return "valueA"
            
        steps_config = {
            "stepA": {
                "prompt": step_a_prompt
            }
        }
        
        runner = WizardRunner(steps_config, step_order, initial_data={"initial": "state"})
        res = runner.run("stepA")
        
        # In the first run, keyA was set to "try_1" and __retry__ was returned.
        # So rollback reverted keyA. Then the second run completed successfully.
        self.assertEqual(res["keyA"], "try_2")
        self.assertEqual(res["initial"], "state")
        self.assertEqual(runner.history_stack, ["stepA"])
        self.assertEqual(call_count, 2)

    def test_runner_no_orphaned_snapshots_consecutive_back(self):
        """Verify that multiple consecutive back operations do not leave orphaned snapshots."""
        from core.wizard import WizardRunner
        
        step_order = ["stepA", "stepB", "stepC", "stepD"]
        steps_config = {
            "stepA": {"prompt": lambda ud: "valA"},
            "stepB": {"prompt": lambda ud: "valB"},
            "stepC": {"prompt": lambda ud: "valC"},
            "stepD": {"prompt": lambda ud: "__back__"}
        }
        
        runner = WizardRunner(steps_config, step_order, initial_data={"initial": "state"})
        # Run manually/simulate steps to test snapshots and rollback
        runner.user_data = {"initial": "state", "step": "D"}
        runner.history_stack = ["stepA", "stepB", "stepC"]
        runner.snapshots = {
            "stepA": {"initial": "state"},
            "stepB": {"initial": "state", "keyA": "valA"},
            "stepC": {"initial": "state", "keyA": "valA", "keyB": "valB"},
            "stepD": {"initial": "state", "keyA": "valA", "keyB": "valB", "keyC": "valC"}
        }
        
        # Rollback to stepC
        runner.rollback_to("stepC")
        # stepC and stepD snapshots should be cleaned up. Only A and B remain.
        self.assertEqual(list(runner.snapshots.keys()), ["stepA", "stepB"])
        self.assertEqual(runner.history_stack, ["stepA", "stepB"])

    def test_runner_branch_switching_cleanup(self):
        """Verify that branch switching correctly resets values and cleans up abandoned step snapshots."""
        from core.wizard import WizardRunner
        
        # Branching layout:
        # A -> B -> C (if B returns C_val)
        #   -> D (if B returns D_val)
        step_order = ["stepA", "stepB", "stepC", "stepD"]
        steps_config = {
            "stepA": {"prompt": lambda ud: "valA"},
            "stepB": {
                "prompt": lambda ud: ud.update({"branch_key": "C"}) or "C",
                "next": lambda ans, ud: "stepC" if ans == "C" else "stepD"
            },
            "stepC": {
                "prompt": lambda ud: ud.update({"c_only_key": "valC"}) or "valC",
                "next": lambda ans, ud: None
            },
            "stepD": {
                "prompt": lambda ud: ud.update({"d_only_key": "valD"}) or "valD",
                "next": lambda ans, ud: None
            }
        }
        
        runner = WizardRunner(steps_config, step_order, initial_data={})
        
        # 1. Run branch A -> B -> C
        runner.run("stepA")
        self.assertEqual(runner.user_data.get("c_only_key"), "valC")
        self.assertEqual(runner.history_stack, ["stepA", "stepB", "stepC"])
        self.assertIn("stepC", runner.snapshots)
        
        # 2. Rollback to stepB and change the branch to D
        # Simulate user going back to stepB
        runner.rollback_to("stepB")
        # B and C snapshots should be popped, history stack becomes ["stepA"]
        self.assertEqual(list(runner.snapshots.keys()), ["stepA"])
        self.assertEqual(runner.history_stack, ["stepA"])
        self.assertNotIn("c_only_key", runner.user_data)
        
        # Now prompt for stepB returns D
        steps_config["stepB"]["prompt"] = lambda ud: ud.update({"branch_key": "D"}) or "D"
        # Resume run
        res = runner.run("stepB")
        self.assertEqual(res.get("d_only_key"), "valD")
        self.assertNotIn("c_only_key", res)  # Verify no stale value leaked from branch C
        self.assertEqual(runner.history_stack, ["stepA", "stepB", "stepD"])
        self.assertNotIn("stepC", runner.snapshots)  # Verify branch C snapshot is cleaned up


class TestZSocketAssignment(unittest.TestCase):

    @patch("questionary.select")
    @patch("core.wizard.fetch_raw_config")
    def test_z_socket_assignment_and_tmc_post_processing(self, mock_fetch, mock_select):
        from core.wizard import _step_z_socket_assignment, _apply_z_tmc_mappings
        mock_fetch.return_value = "[extruder1]\nstep_pin: PE1\ndir_pin: PE2\nenable_pin: PE3\n[tmc2209 extruder1]\nuart_pin: PD12\n"
        
        # User selects E1 (extruder1) for stepper_z1
        mock_select.return_value.ask.return_value = "extruder1"
        
        board_parsed = {
            "extruder1": {
                "step_pin": "PE1",
                "dir_pin": "PE2",
                "enable_pin": "PE3"
            },
            "tmc2209 extruder1": {
                "uart_pin": "PD12"
            }
        }
        
        user_data = {
            "z_motors": "2",
            "board": "generic-mock.cfg",
            "board_raw_config": mock_fetch.return_value,
            "board_parsed": board_parsed,
            "driver_type": None,  # driver_type is not selected yet!
            "driver_mode": None
        }
        
        # 1. Run step
        res = _step_z_socket_assignment(user_data)
        self.assertEqual(res, "done")
        self.assertEqual(user_data["z_socket_assignments"], {"stepper_z1": "extruder1"})
        self.assertIn("stepper_z1", board_parsed)
        self.assertEqual(board_parsed["stepper_z1"]["step_pin"], "PE1")
        # Ensure the TMC section was not copied yet because driver_type is None
        self.assertNotIn("tmc2209 stepper_z1", board_parsed)
        
        # 2. Later in wizard, user selects TMC2209 UART
        user_data["driver_type"] = "TMC2209"
        user_data["driver_mode"] = "UART"
        
        # 3. Post-processing maps Z stepper TMC configuration
        _apply_z_tmc_mappings(user_data)
        self.assertIn("tmc2209 stepper_z1", board_parsed)
        self.assertEqual(board_parsed["tmc2209 stepper_z1"]["uart_pin"], "PD12")
        # Ensure the original extruder1 TMC section is gone
        self.assertNotIn("tmc2209 extruder1", board_parsed)


class TestWizardTransitions(unittest.TestCase):

    def test_run_wizard_transition_lambdas(self):
        from core.wizard import run_wizard, WizardRunner
        
        captured_config = {}
        original_init = WizardRunner.__init__
        
        def mock_init(self_runner, steps_config, step_order, initial_data=None):
            captured_config.update(steps_config)
            original_init(self_runner, steps_config, step_order, initial_data)
            
        with patch("core.wizard.WizardRunner.__init__", mock_init), \
             patch("core.wizard.discover_mcu", return_value={}), \
             patch("core.wizard.fetch_config_list", return_value=[]), \
             patch("core.wizard.WizardRunner.run", return_value={}):
            run_wizard()
            
        # Assert transition lambdas are configured properly and don't return None
        self.assertIn("z_socket_assignment", captured_config)
        self.assertIn("driver_type", captured_config)
        self.assertIn("printer_profile", captured_config)
        
        # 1. z_socket_assignment transitions
        next_fn = captured_config["z_socket_assignment"]["next"]
        self.assertEqual(next_fn("__skip__", {}), "driver_type")
        self.assertEqual(next_fn("done", {}), "driver_type")
        
        # 2. driver_type transitions
        next_fn = captured_config["driver_type"]["next"]
        self.assertEqual(next_fn("TMC2209", {}), "driver_mode")
        self.assertEqual(next_fn("TMC2208", {}), "driver_mode")
        self.assertEqual(next_fn("None (Standard)", {}), "printer_profile")
        self.assertEqual(next_fn("A4988", {}), "printer_profile")
        self.assertEqual(next_fn("DRV8825", {}), "printer_profile")
        
        # 3. printer_profile transitions
        next_fn = captured_config["printer_profile"]["next"]
        self.assertEqual(next_fn("some-profile", {"profile_loaded": True}), "profile_review")
        self.assertEqual(next_fn("some-profile", {"profile_loaded": False}), "kinematics")

        # 4. board transitions (with fan_assignment)
        next_fn = captured_config["board"]["next"]
        # If board has fan options, next is fan_assignment
        self.assertEqual(next_fn("generic-skr.cfg", {"board_raw_config": "[fan]\npin: PA8"}), "fan_assignment")
        # Otherwise, next is z_motors
        self.assertEqual(next_fn("generic-skr.cfg", {"board_raw_config": ""}), "z_motors")


class TestWizardFanAssignment(unittest.TestCase):
    def test_has_fan_options(self):
        from core.wizard import _has_fan_options
        # No raw config -> False
        self.assertFalse(_has_fan_options({}))
        
        # Raw config without fan -> False
        self.assertFalse(_has_fan_options({"board_raw_config": "[stepper_x]\npin: P2.0"}))
        
        # Raw config with fan -> True
        self.assertTrue(_has_fan_options({"board_raw_config": "[fan]\npin: PA8"}))

    @patch("questionary.select")
    def test_step_fan_assignment_default_and_none(self, mock_select):
        from core.wizard import _step_fan_assignment
        
        # Board with only default [fan]
        raw_cfg = "[fan]\npin: PA8\n"
        user_data = {"board_raw_config": raw_cfg}
        
        # Select "default" for part cooling, and "none" for hotend
        mock_select.return_value.ask.side_effect = ["default", "none"]
        
        res = _step_fan_assignment(user_data)
        self.assertEqual(res, "success")
        self.assertEqual(user_data["fan_part_cooling_pin"], "default")
        self.assertEqual(user_data["fan_hotend_pin"], "none")

    @patch("questionary.text")
    @patch("questionary.select")
    def test_step_fan_assignment_custom(self, mock_select, mock_text):
        from core.wizard import _step_fan_assignment
        
        # Board with fan and heater fan
        raw_cfg = "[fan]\npin: PA8\n#[heater_fan fan1]\n#pin: PE5\n"
        user_data = {"board_raw_config": raw_cfg}
        
        # Select "custom" for part cooling, then enter "PB6". Then select "PE5" for hotend.
        mock_select.return_value.ask.side_effect = ["custom", "PE5"]
        mock_text.return_value.ask.side_effect = ["PB6"]
        
        res = _step_fan_assignment(user_data)
        self.assertEqual(res, "success")
        self.assertEqual(user_data["fan_part_cooling_pin"], "PB6")
        self.assertEqual(user_data["fan_hotend_pin"], "PE5")


class TestWizardProfileMerging(unittest.TestCase):
    def test_run_wizard_merges_profile_pins(self):
        from core.wizard import run_wizard
        # We mock WizardRunner.run to return our mocked user_data
        mock_user_data = {
            "board_parsed": {
                "heater_bed": {
                    "heater_pin": "PD2",
                    "sensor_pin": "PA6"
                },
                "stepper_x": {
                    "step_pin": "PD7",
                    "dir_pin": "PC5"
                }
            },
            "_profile_parsed": {
                "heater_bed": {
                    "heater_pin": "PD4",
                    "sensor_type": "Generic 3950"
                },
                "stepper_x": {
                    "dir_pin": "!PC5"
                }
            }
        }
        with patch("core.wizard.WizardRunner.run", return_value=mock_user_data), \
             patch("core.wizard.discover_mcu", return_value={}), \
             patch("core.wizard._apply_z_tmc_mappings"):
            res = run_wizard()
            
        board_parsed = res.get("board_parsed", {})
        self.assertEqual(board_parsed["heater_bed"]["heater_pin"], "PD4")
        self.assertEqual(board_parsed["heater_bed"]["sensor_pin"], "PA6")
        self.assertEqual(board_parsed["heater_bed"]["sensor_type"], "Generic 3950")
        self.assertEqual(board_parsed["stepper_x"]["dir_pin"], "!PC5")
        self.assertEqual(board_parsed["stepper_x"]["step_pin"], "PD7")


if __name__ == '__main__':
    unittest.main()
