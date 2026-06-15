import sys
import os
import copy
import questionary
from .scraper import fetch_config_list, fetch_raw_config, parse_config, extract_profile_defaults, detect_driver_info, is_socketed_board, get_reusable_driver_sockets, detect_fan_pins
from firmware.detector import discover_mcu_hardware
from core.style import custom_style
from data.profiles import THERMISTOR_PRESETS
from core.translations import t, get_lang
from core.display_wizard import run_display_setup_step
from core.probe_offset_visualizer import run_probe_offset_step
from .exceptions import WizardExit
from core.validators import questionary_pin_validator, questionary_numeric_validator, questionary_pos_numeric_validator

_BACK = "__back__"
_QUIT = "__quit__"

PHASE_MAP = {
    "board": "Hardware",
    "fan_assignment": "Hardware",
    "z_motors": "Hardware",
    "z_socket_assignment": "Hardware",
    "driver_type": "Hardware",
    "driver_mode": "Hardware",
    "printer_profile": "Motion",
    "profile_review": "Motion",
    "kinematics": "Motion",
    "x_volume": "Motion",
    "y_volume": "Motion",
    "z_volume": "Motion",
    "x_limits": "Motion",
    "y_limits": "Motion",
    "z_limits": "Motion",
    "probe": "Sensors",
    "bltouch_pins": "Sensors",
    "probe_offsets": "Sensors",
    "hotend_therm": "Sensors",
    "bed_therm": "Sensors",
    "display": "Software",
    "web_ui": "Software",
}

PHASE_KEYS = {
    "Hardware": "wizard.phase.hardware",
    "Motion": "wizard.phase.motion",
    "Sensors": "wizard.phase.sensors",
    "Software": "wizard.phase.software",
}

PHASE_ORDER = ["Hardware", "Motion", "Sensors", "Software"]

def _get_active_phase_steps(phase: str, user_data: dict) -> list:
    """Dynamically determine which steps in the given phase are active/visible."""
    all_steps = [step_id for step_id, p in PHASE_MAP.items() if p == phase]
    active = []
    for step_id in all_steps:
        if step_id == "fan_assignment":
            if not _has_fan_options(user_data):
                continue
        elif step_id == "z_socket_assignment":
            z_motors = user_data.get("z_motors")
            if z_motors is None or int(z_motors) <= 1:
                continue
        elif step_id == "driver_mode":
            d_type = user_data.get("driver_type")
            if d_type in ["None (Standard)", "A4988", "DRV8825"]:
                continue
        elif step_id == "profile_review":
            if not user_data.get("profile_loaded"):
                continue
        elif step_id == "kinematics":
            if "kinematics" in user_data.get("_authoritative", set()):
                continue
        elif step_id == "x_volume":
            if "x_size" in user_data.get("_authoritative", set()):
                continue
        elif step_id == "y_volume":
            if "y_size" in user_data.get("_authoritative", set()):
                continue
        elif step_id == "z_volume":
            if "z_size" in user_data.get("_authoritative", set()):
                continue
        elif step_id == "x_limits":
            if "x_position_min" in user_data.get("_authoritative", set()):
                continue
        elif step_id == "y_limits":
            if "y_position_min" in user_data.get("_authoritative", set()):
                continue
        elif step_id == "z_limits":
            if "z_position_min" in user_data.get("_authoritative", set()):
                continue
        elif step_id == "probe_offsets":
            probe = user_data.get("probe")
            if probe is None or probe == "None":
                continue
        elif step_id == "hotend_therm":
            if "hotend_thermistor" in user_data.get("_authoritative", set()):
                continue
        elif step_id == "bed_therm":
            if "bed_thermistor" in user_data.get("_authoritative", set()):
                continue
        active.append(step_id)
    return active

def _print_step_header(step_id: str, user_data: dict) -> None:
    """Print a visually rich step header box in stdout if quiet/auto mode is not enabled."""
    if os.environ.get("KACE_TESTING") == "1":
        return
    if os.environ.get("KACE_AUTO") == "1":
        return
    if os.environ.get("KACE_QUIET") == "1":
        return

    phase = PHASE_MAP.get(step_id)
    if not phase:
        return

    # Translate phase name
    phase_key = PHASE_KEYS.get(phase)
    translated_phase = t(phase_key) if phase_key else phase

    # Get active steps in phase
    active_steps = _get_active_phase_steps(phase, user_data)
    try:
        step_idx = active_steps.index(step_id) + 1
    except ValueError:
        step_idx = 1
    total_steps = len(active_steps)

    # Get header and hint translations
    header_key = f"wizard.step.{step_id}.header"
    hint_key = f"wizard.step.{step_id}.hint"
    header_text = t(header_key)
    hint_text = t(hint_key)

    # Styling colors
    C_BORDER = "\033[36m"   # Cyan border
    C_PHASE = "\033[1;96m"  # Bold Cyan phase name
    C_STEP = "\033[1;92m"   # Bold Green step counter
    C_HEADER = "\033[1;97m" # Bold White step header
    C_HINT = "\033[37m"     # Light gray hint
    C_RESET = "\033[0m"

    lbl_phase = t("wizard.phase_label") or "Phase"
    lbl_step = t("wizard.step_label") or "Step"
    lbl_of = t("wizard.of_label") or "of"

    # Print the beautiful UI block
    box_width = 72
    print(f"\n{C_BORDER}┌" + "─" * (box_width - 2) + f"┐{C_RESET}")
    
    # Phase & Step progress line
    content = f"{lbl_phase}: {translated_phase} | {lbl_step} {step_idx} {lbl_of} {total_steps}"
    padding_len = box_width - 4 - len(content)
    left_padding = padding_len // 2
    right_padding = padding_len - left_padding
    print(f"{C_BORDER}│ {C_RESET}{' ' * left_padding}{C_PHASE}{lbl_phase}: {translated_phase}{C_RESET} | {C_STEP}{lbl_step} {step_idx} {lbl_of} {total_steps}{C_RESET}{' ' * right_padding} {C_BORDER}│{C_RESET}")
    
    print(f"{C_BORDER}├" + "─" * (box_width - 2) + f"┤{C_RESET}")
    
    # Header line
    header_line = f"  {header_text}"
    header_padding = box_width - 4 - len(header_line)
    if header_padding > 0:
        print(f"{C_BORDER}│ {C_HEADER}{header_line}{C_RESET}{' ' * header_padding} {C_BORDER}│{C_RESET}")
    else:
        print(f"{C_BORDER}│ {C_HEADER}{header_line[:box_width-4]}{C_RESET} {C_BORDER}│{C_RESET}")
        
    # Hint line(s) (word wrap to fit box_width - 4)
    words = hint_text.split()
    lines = []
    current_line = "  "
    for word in words:
        if len(current_line) + len(word) + 1 <= box_width - 4:
            if current_line == "  ":
                current_line += word
            else:
                current_line += " " + word
        else:
            lines.append(current_line)
            current_line = "  " + word
    if current_line.strip():
        lines.append(current_line)
        
    for line in lines:
        line_padding = box_width - 4 - len(line)
        print(f"{C_BORDER}│ {C_HINT}{line}{C_RESET}{' ' * line_padding} {C_BORDER}│{C_RESET}")
        
    print(f"{C_BORDER}└" + "─" * (box_width - 2) + f"┘{C_RESET}\n")


def _back_choice():
    return {"name": t("choice.back"), "value": _BACK}

def _quit_choice():
    return {"name": t("choice.quit"), "value": _QUIT}


# ── Hardware database ──────────────────────────────────────────────────────────
_MCU_SEARCH_TERMS_FALLBACK = {
    "lpc1769":    ["skr-v1.4", "skr-v1.3", "sgen-l"],
    "lpc1768":    ["mks-sgenl", "sbase"],
    "stm32f103":  ["creality-v4.2.2", "creality-v4.2.7", "skr-mini-e3"],
    "stm32f407":  ["mks-robin-nano-v3", "skr-pro"],
    "stm32f429":  ["skr-2", "octopus-pro-v1.0"],
    "stm32f446":  ["octopus", "spider"],
    "stm32g0b1":  ["manta", "skr-mini-e3-v3.0"],
    "stm32h723":  ["octopus-max-ez"],
    "stm32f042":  ["cheetah-v2.0"],
    "rp2040":     ["skr-pico"],
    "atmega2560": ["ramps", "mega2560"],
    "atmega1284p":["melzi"],
    "at90usb1286":["printrboard"],
    "sam4e8e":    ["duet2"],
    "samd51":     ["duet3-mini"],
}

def _load_mcu_search_terms() -> dict:
    try:
        from core.loader import load_boards_yaml
        db = load_boards_yaml()
        result = {}
        for entry in db.get('boards', []):
            mcu = entry.get('mcu')
            terms = entry.get('search_terms', [])
            if mcu and terms:
                result[mcu] = terms
        return result if result else _MCU_SEARCH_TERMS_FALLBACK
    except Exception:
        return _MCU_SEARCH_TERMS_FALLBACK

_MCU_SEARCH_TERMS = None
_PRINTER_PROFILES_DB = None

def _get_mcu_search_terms() -> dict:
    global _MCU_SEARCH_TERMS
    if _MCU_SEARCH_TERMS is None:
        _MCU_SEARCH_TERMS = _load_mcu_search_terms()
    return _MCU_SEARCH_TERMS

def _get_printer_profiles() -> list:
    global _PRINTER_PROFILES_DB
    if _PRINTER_PROFILES_DB is None:
        _PRINTER_PROFILES_DB = _load_printer_profiles()
    return _PRINTER_PROFILES_DB

def __getattr__(name: str):
    if name == "MCU_SEARCH_TERMS":
        return _get_mcu_search_terms()
    if name == "PRINTER_PROFILES_DB":
        return _get_printer_profiles()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

def _normalize_mcu_family(mcu: str) -> str:
    if not mcu:
        return ""
    m = mcu.lower()
    if m.startswith("lpc176"): return "lpc176x"
    if m.startswith("stm32f103"): return "stm32f103"
    if m.startswith("stm32f4"): return "stm32f4"
    if m.startswith("stm32g0b"): return "stm32g0b"
    if m.startswith("atmega2560"): return "atmega2560"
    if m.startswith("rp2040"): return "rp2040"
    return m

def _load_printer_profiles() -> list:
    try:
        from core.loader import load_boards_yaml
        db = load_boards_yaml()
        return db.get('printer_profiles', [])
    except Exception:
        return []


def get_current_board_parsed(user_data) -> dict:
    if user_data.get("board") == user_data.get("printer_profile") and user_data.get("profile_loaded"):
        raw = user_data.get("raw_config", "")
    else:
        board_name = user_data.get("board")
        if not board_name:
            return {}
        raw = fetch_raw_config(board_name)
    if not raw:
        return {}
    return parse_config(raw, user_data.get("board") or "", keep_comments=True)

def print_detected_profile_summary(defaults: dict, parsed: dict, user_data: dict = None) -> None:
    """Print detected profile as a clean information screen.

    Layout:
      Motion System header
        - Kinematics  (blank line after)
        - X axis group (blank line after)
        - Y axis group (blank line after)
        - Z axis group (blank line after)
      Build Volume header
      Thermistors header

    All Klipper educational comments are mandatory on every value line.
    """
    is_custom = False
    if user_data:
        is_custom = user_data.get("printer_profile") == "Custom / Scratch Build"
    elif defaults:
        is_custom = defaults.get("printer_profile") == "Custom / Scratch Build"

    header_key = "profile.custom_header" if is_custom else "profile.detected_header"
    print(f"\n\033[92m{t(header_key)}\033[0m")

    def print_val(label: str, val: str, comment_key: str) -> None:
        comment = t(comment_key)
        dim_comment = f"\033[2m# {comment}\033[0m"
        print(f"  - {label:<24} {str(val):<8} {dim_comment}")

    # ── Motion System ─────────────────────────────────────────────────────────
    kinematics = parsed.get('printer', {}).get('kinematics') or defaults.get('kinematics')
    has_any_axis = any(
        parsed.get(f'stepper_{a}', {}).get(k) is not None or (is_custom and defaults.get(f'{a}_{k}') is not None)
        for a in ['x', 'y', 'z']
        for k in ('position_min', 'position_max', 'position_endstop')
    )
    has_motion = bool(kinematics or has_any_axis)

    if has_motion:
        print("  \033[96mMotion System\033[0m")
        print("  \033[96m─────────────\033[0m")
        print("")

        if kinematics:
            print_val("Kinematics:", kinematics, "profile.comment_kinematics")
            print("")

        for axis in ['x', 'y', 'z']:
            sec = f'stepper_{axis}'
            axis_data = parsed.get(sec, {})
            axis_rows = [
                (f"{axis.upper()} position_min:",     axis_data.get('position_min') or (defaults.get(f'{axis}_position_min') if is_custom else None),     f"profile.comment_position_min_{axis}"),
                (f"{axis.upper()} position_max:",     axis_data.get('position_max') or (defaults.get(f'{axis}_position_max') if is_custom else None),     f"profile.comment_position_max_{axis}"),
                (f"{axis.upper()} position_endstop:", axis_data.get('position_endstop') or (defaults.get(f'{axis}_position_endstop') if is_custom else None), f"profile.comment_position_endstop_{axis}"),
            ]
            if any(v is not None for _, v, _ in axis_rows):
                for label, val, comment_key in axis_rows:
                    if val is not None:
                        print_val(label, val, comment_key)
                print("")

    # ── Build Volume ──────────────────────────────────────────────────────────
    x_size = parsed.get('stepper_x', {}).get('position_max') or defaults.get('x_size')
    y_size = parsed.get('stepper_y', {}).get('position_max') or defaults.get('y_size')
    z_size = parsed.get('stepper_z', {}).get('position_max') or defaults.get('z_size')
    if x_size and y_size and z_size:
        print("  \033[96mBuild Volume\033[0m")
        print("  \033[96m────────────\033[0m")
        print("")
        print_val("Build volume:", f"{x_size} x {y_size} x {z_size}", "profile.comment_build_volume")
        print("")

    # ── Thermistors ───────────────────────────────────────────────────────────
    hotend_therm = parsed.get('extruder', {}).get('sensor_type') or (defaults.get('hotend_thermistor') if is_custom else None)
    bed_therm = parsed.get('heater_bed', {}).get('sensor_type') or (defaults.get('bed_thermistor') if is_custom else None)
    if hotend_therm or bed_therm:
        print("  \033[96mThermistors\033[0m")
        print("  \033[96m───────────\033[0m")
        print("")
        if hotend_therm:
            print_val("Hotend thermistor:", hotend_therm, "profile.comment_hotend_therm")
        if bed_therm:
            print_val("Bed thermistor:", bed_therm, "profile.comment_bed_therm")
        print("")


def interactive_profile_review(defaults: dict, parsed: dict, user_data: dict) -> str:
    """Legacy shim: delegates to _step_profile_review_inner.

    Kept for backward compatibility with tests and any external callers.
    Returns 'confirm' or 'back'.
    """
    return _step_profile_review_inner(defaults, parsed, user_data)
# ── Profile Review + Editor (split into info screen and staged editor) ────────

def _step_profile_review_inner(defaults: dict, parsed: dict, user_data: dict) -> str:
    """Profile information screen.

    Shows the detected profile values exactly once per visit.
    Offers three choices: Continue | Edit Profile | Back.

    If the user selects Edit, opens the staged editor.  On Save from the
    editor, this screen is re-shown with the updated values so the user
    can confirm before proceeding.

    Returns 'confirm' or 'back'.
    """
    while True:
        print_detected_profile_summary(defaults, parsed, user_data)

        action = questionary.select(
            t("wizard.profile_review_prompt"),
            choices=[
                {"name": t("choice.continue"),      "value": "confirm"},
                {"name": t("choice.edit_profile"),  "value": "edit"},
                {"name": t("choice.arrow_back"),    "value": "back"},
            ],
            style=custom_style
        ).ask()

        if action is None:
            raise WizardExit()
        if action == "confirm":
            return "confirm"
        if action == "back":
            return "back"

        # Open staged editor; loop back to show updated summary on Save.
        editor_result = _step_profile_editor_inner(defaults, parsed, user_data)
        if editor_result == "back":
            # Editor Back = discard + return to this review screen
            continue
        # editor_result == "save" → loop back to reprint summary with updates


def _step_profile_editor_inner(defaults: dict, parsed: dict, user_data: dict) -> str:
    """Staged profile editor.

    Works on a deep-copy of defaults/parsed/user_data values.
    Save & Continue  → commits the staged copy to the live dicts.
    Back             → discards the staged copy entirely.

    Returns 'save' (committed) or 'back' (discarded).
    """
    # ── Build staged copies ───────────────────────────────────────────────────
    staged_defaults  = copy.deepcopy(defaults)
    staged_parsed    = copy.deepcopy(parsed)
    staged_user_data = copy.deepcopy(user_data)

    def validate_float(val):
        try:
            float(val)
            return True
        except (ValueError, TypeError):
            return False

    def validate_pos_float(val):
        try:
            return float(val) > 0
        except (ValueError, TypeError):
            return False

    def _resolve(sd, sp):
        """Resolve current field values from staged parsed / staged defaults."""
        kin   = sp.get('printer', {}).get('kinematics') or sd.get('kinematics', 'cartesian')
        x_sz  = sp.get('stepper_x', {}).get('position_max') or sd.get('x_size', '235')
        y_sz  = sp.get('stepper_y', {}).get('position_max') or sd.get('y_size', '235')
        z_sz  = sp.get('stepper_z', {}).get('position_max') or sd.get('z_size', '250')
        x_min = sp.get('stepper_x', {}).get('position_min') or sd.get('x_position_min', '0')
        x_max = sp.get('stepper_x', {}).get('position_max') or sd.get('x_position_max', '235')
        x_end = sp.get('stepper_x', {}).get('position_endstop') or sd.get('x_position_endstop', '0')
        y_min = sp.get('stepper_y', {}).get('position_min') or sd.get('y_position_min', '0')
        y_max = sp.get('stepper_y', {}).get('position_max') or sd.get('y_position_max', '235')
        y_end = sp.get('stepper_y', {}).get('position_endstop') or sd.get('y_position_endstop', '0')
        z_min = sp.get('stepper_z', {}).get('position_min') or sd.get('z_position_min', '0')
        z_max = sp.get('stepper_z', {}).get('position_max') or sd.get('z_position_max', '250')
        z_end = sp.get('stepper_z', {}).get('position_endstop') or sd.get('z_position_endstop', '0')
        ht    = sp.get('extruder', {}).get('sensor_type') or sd.get('hotend_thermistor', 'EPCOS 100K B57560G104F')
        bt    = sp.get('heater_bed', {}).get('sensor_type') or sd.get('bed_thermistor', 'EPCOS 100K B57560G104F')
        return kin, x_sz, y_sz, z_sz, x_min, x_max, x_end, y_min, y_max, y_end, z_min, z_max, z_end, ht, bt

    # ── Editor loop ───────────────────────────────────────────────────────────
    while True:
        kin, x_sz, y_sz, z_sz, x_min, x_max, x_end, \
            y_min, y_max, y_end, z_min, z_max, z_end, ht, bt = _resolve(staged_defaults, staged_parsed)

        C = "\033[96m"   # cyan
        D = "\033[2m"    # dim
        B = "\033[1m"    # bold
        R = "\033[0m"    # reset
        SEP = "─" * 62

        def _row(idx, label, value, comment_key):
            comment = t(comment_key)
            return f"  {B}{idx:>2}.{R}  {label:<22} {C}{value}{R}  {D}# {comment}{R}"

        print(f"\n  {B}{t('choice.edit_profile')}{R}")
        print(f"  {SEP}")
        print(_row(1,  "Kinematics",         kin,                             "profile.comment_kinematics"))
        print(_row(2,  "Build Volume",        f"{x_sz} x {y_sz} x {z_sz} mm", "profile.comment_build_volume"))
        print(f"  {SEP}")
        print(_row(3,  "X position_min",      x_min, "profile.comment_position_min_x"))
        print(_row(4,  "X position_max",      x_max, "profile.comment_position_max_x"))
        print(_row(5,  "X position_endstop",  x_end, "profile.comment_position_endstop_x"))
        print(f"  {SEP}")
        print(_row(6,  "Y position_min",      y_min, "profile.comment_position_min_y"))
        print(_row(7,  "Y position_max",      y_max, "profile.comment_position_max_y"))
        print(_row(8,  "Y position_endstop",  y_end, "profile.comment_position_endstop_y"))
        print(f"  {SEP}")
        print(_row(9,  "Z position_min",      z_min, "profile.comment_position_min_z"))
        print(_row(10, "Z position_max",      z_max, "profile.comment_position_max_z"))
        print(_row(11, "Z position_endstop",  z_end, "profile.comment_position_endstop_z"))
        print(f"  {SEP}")
        print(_row(12, "Hotend Thermistor",   ht,    "profile.comment_hotend_therm"))
        print(_row(13, "Bed Thermistor",      bt,    "profile.comment_bed_therm"))
        print(f"  {SEP}")
        print()

        prop = questionary.select(
            t("wizard.profile_editor_prompt"),
            choices=[
                {"name": t("choice.save_continue"),            "value": "save"},
                {"name": t("choice.editor_kinematics"),        "value": "kinematics"},
                {"name": t("choice.editor_volume"),            "value": "volume"},
                {"name": t("choice.editor_x_min"),             "value": "x_position_min"},
                {"name": t("choice.editor_x_max"),             "value": "x_position_max"},
                {"name": t("choice.editor_x_endstop"),         "value": "x_position_endstop"},
                {"name": t("choice.editor_y_min"),             "value": "y_position_min"},
                {"name": t("choice.editor_y_max"),             "value": "y_position_max"},
                {"name": t("choice.editor_y_endstop"),         "value": "y_position_endstop"},
                {"name": t("choice.editor_z_min"),             "value": "z_position_min"},
                {"name": t("choice.editor_z_max"),             "value": "z_position_max"},
                {"name": t("choice.editor_z_endstop"),         "value": "z_position_endstop"},
                {"name": t("choice.editor_hotend_thermistor"), "value": "hotend_thermistor"},
                {"name": t("choice.editor_bed_thermistor"),    "value": "bed_thermistor"},
                {"name": t("choice.back_discard"),              "value": "back"},
            ],
            style=custom_style
        ).ask()

        if prop is None:
            raise WizardExit()

        if prop == "save":
            # Commit staged copies back to live dicts
            defaults.clear()
            defaults.update(staged_defaults)
            parsed.clear()
            parsed.update(staged_parsed)
            user_data.clear()
            user_data.update(staged_user_data)
            return "save"

        if prop == "back":
            return "back"

        # ── Field edit handlers (operate on staged copies) ────────────────────
        if prop == "kinematics":
            new_kin = questionary.select(
                "Select Kinematics:",
                choices=["cartesian", "corexy", "delta"],
                default=kin if kin in ["cartesian", "corexy", "delta"] else "cartesian",
                style=custom_style
            ).ask()
            if new_kin:
                staged_user_data["kinematics"] = new_kin
                staged_defaults["kinematics"] = new_kin
                staged_parsed.setdefault('printer', {})['kinematics'] = new_kin

        elif prop == "volume":
            new_x = questionary.text("Enter X build volume (mm):", default=str(x_sz), style=custom_style).ask()
            if new_x is not None and validate_pos_float(new_x):
                new_y = questionary.text("Enter Y build volume (mm):", default=str(y_sz), style=custom_style).ask()
                if new_y is not None and validate_pos_float(new_y):
                    new_z = questionary.text("Enter Z build volume (mm):", default=str(z_sz), style=custom_style).ask()
                    if new_z is not None and validate_pos_float(new_z):
                        for key, val in [("x_size", new_x), ("y_size", new_y), ("z_size", new_z),
                                         ("x_position_max", new_x), ("y_position_max", new_y), ("z_position_max", new_z)]:
                            staged_user_data[key] = val
                            staged_defaults[key] = val
                        staged_parsed.setdefault('stepper_x', {})['position_max'] = new_x
                        staged_parsed.setdefault('stepper_y', {})['position_max'] = new_y
                        staged_parsed.setdefault('stepper_z', {})['position_max'] = new_z

        elif prop in ("x_position_min", "x_position_max", "x_position_endstop",
                      "y_position_min", "y_position_max", "y_position_endstop",
                      "z_position_min", "z_position_max", "z_position_endstop"):
            # Extract axis (x, y, z) and field (position_min, position_max, position_endstop)
            axis = prop.split("_")[0]
            field = prop.replace(f"{axis}_", "")
            
            # Map current value
            val_map = {
                "x_position_min": x_min, "x_position_max": x_max, "x_position_endstop": x_end,
                "y_position_min": y_min, "y_position_max": y_max, "y_position_endstop": y_end,
                "z_position_min": z_min, "z_position_max": z_max, "z_position_endstop": z_end,
            }
            curr_val = val_map[prop]
            
            new_val = questionary.text(
                f"Enter {axis.upper()} {field} (mm):",
                default=str(curr_val),
                validate=questionary_numeric_validator,
                style=custom_style
            ).ask()
            
            if new_val is not None and new_val.strip().lower() not in ("<", "back", "volver", ""):
                val_clean = new_val.strip()
                staged_user_data[prop] = val_clean
                staged_defaults[prop] = val_clean
                
                # Update staged_parsed
                sx = staged_parsed.setdefault(f"stepper_{axis}", {})
                sx[field] = val_clean
                
                # Synchronization: if position_max changes, update _size
                if field == "position_max":
                    size_key = f"{axis}_size"
                    staged_user_data[size_key] = val_clean
                    staged_defaults[size_key] = val_clean

        elif prop == "hotend_thermistor":
            th_choices = list(THERMISTOR_PRESETS) + ["Other (Manual Entry)"]
            new_th = questionary.select(
                "Select Hotend Thermistor:",
                choices=th_choices,
                default=ht if ht in THERMISTOR_PRESETS else None,
                style=custom_style
            ).ask()
            if new_th == "Other (Manual Entry)":
                new_th = questionary.text("Enter custom hotend thermistor name:", style=custom_style).ask()
            if new_th:
                staged_user_data["hotend_thermistor"] = new_th
                staged_defaults["hotend_thermistor"] = new_th
                staged_parsed.setdefault('extruder', {})['sensor_type'] = new_th

        elif prop == "bed_thermistor":
            bt_choices = list(THERMISTOR_PRESETS) + ["Other (Manual Entry)"]
            new_tb = questionary.select(
                "Select Bed Thermistor:",
                choices=bt_choices,
                default=bt if bt in THERMISTOR_PRESETS else None,
                style=custom_style
            ).ask()
            if new_tb == "Other (Manual Entry)":
                new_tb = questionary.text("Enter custom bed thermistor name:", style=custom_style).ask()
            if new_tb:
                staged_user_data["bed_thermistor"] = new_tb
                staged_defaults["bed_thermistor"] = new_tb
                staged_parsed.setdefault('heater_bed', {})['sensor_type'] = new_tb


def discover_mcu():
    return discover_mcu_hardware()


# ── Declarative Wizard Runner & Catalog ────────────────────────────────────────

class WizardRunner:
    def __init__(self, steps_config, step_order, initial_data=None):
        self.steps_config = steps_config
        self.step_order = step_order
        self.history_stack = []
        self.snapshots = {}
        self.user_data = initial_data if initial_data is not None else {}
        self.last_step_id = None
        self.completed_phases = set()

    def run(self, start_step_id):
        current_id = start_step_id
        
        while current_id:
            step_cfg = self.steps_config[current_id]
            
            # Take snapshot before executing the step
            self.snapshots[current_id] = copy.deepcopy(self.user_data)
            
            # Detect forward transitions between phases
            current_phase = PHASE_MAP.get(current_id)
            if self.last_step_id:
                last_phase = PHASE_MAP.get(self.last_step_id)
                if last_phase and current_phase and last_phase != current_phase:
                    if PHASE_ORDER.index(current_phase) > PHASE_ORDER.index(last_phase):
                        if last_phase not in self.completed_phases:
                            self.completed_phases.add(last_phase)
                            if os.environ.get("KACE_AUTO") != "1" and os.environ.get("KACE_QUIET") != "1":
                                last_phase_key = PHASE_KEYS.get(last_phase)
                                translated_last_phase = t(last_phase_key) if last_phase_key else last_phase
                                print(f"\033[92m{t('wizard.phase.complete', phase=translated_last_phase)}\033[0m")
            
            # Print the header orientation box for the step
            _print_step_header(current_id, self.user_data)
            
            try:
                ans = step_cfg["prompt"](self.user_data)
            except (KeyboardInterrupt, EOFError):
                raise WizardExit()
                
            if ans == _BACK:
                if self.history_stack:
                    prev_id = self.history_stack[-1]
                    self.rollback_to(prev_id)
                    current_id = prev_id
                continue
                
            if ans == "__retry__":
                self.rollback_to(current_id)
                continue
                
            if current_id not in self.history_stack:
                self.history_stack.append(current_id)
            self.last_step_id = current_id
                
            next_func = step_cfg.get("next")
            if next_func:
                next_id = next_func(ans, self.user_data)
            else:
                next_id = self.get_default_next(current_id)
                
            current_id = next_id
            
        return self.user_data

    def rollback_to(self, step_id):
        """Rolls back user_data state to the snapshot taken before step_id was run,
        and removes step_id and all subsequent steps from history and snapshots."""
        snapshot = self.snapshots.get(step_id)
        if snapshot is not None:
            self.user_data.clear()
            self.user_data.update(copy.deepcopy(snapshot))
            
        if step_id in self.history_stack:
            idx = self.history_stack.index(step_id)
            self.history_stack = self.history_stack[:idx]
            
        # Clean up all snapshots that are not in the active history stack path.
        # This prevents orphaned snapshots from branch changes or back navigation.
        active_steps = set(self.history_stack)
        for sid in list(self.snapshots.keys()):
            if sid not in active_steps:
                self.snapshots.pop(sid, None)
                
        self.last_step_id = self.history_stack[-1] if self.history_stack else None
        target_phase = PHASE_MAP.get(step_id)
        if target_phase in PHASE_ORDER:
            target_idx = PHASE_ORDER.index(target_phase)
            self.completed_phases = {p for p in self.completed_phases if PHASE_ORDER.index(p) < target_idx}

    def get_default_next(self, step_id):
        try:
            idx = self.step_order.index(step_id)
            if idx + 1 < len(self.step_order):
                return self.step_order[idx + 1]
        except ValueError:
            pass
        return None


def run_wizard(user_data_arg=None):
    """Runs the interactive CLI wizard to gather user preferences.

    New step order (all hardware decisions first):
      board → z_motors → z_socket_assignment → driver_type → driver_mode
      → printer_profile → profile_review → kinematics → x/y/z_volume
      → probe → probe_offsets → hotend_therm → bed_therm → display → web_ui

    The wizard now also handles Z socket wiring and display setup internally,
    so kace.py only handles file generation and deployment after the wizard
    returns a fully-populated user_data.
    """
    if os.environ.get("KACE_AUTO") != "1" and os.environ.get("KACE_QUIET") != "1":
        print("\033[2m  Starting Hardware Discovery...\033[0m")
    mcu_context = discover_mcu()
    mcu_path = mcu_context.get("mcu_path")
    detected_mcu = mcu_context.get("derived_mcu")
    mcu_hint = mcu_context.get("hint")

    if os.environ.get("KACE_AUTO") != "1" and os.environ.get("KACE_QUIET") != "1":
        print("\033[2m  Fetching board database...\033[0m")
    boards = fetch_config_list()

    printer_configs = [b for b in boards if b.startswith("printer-")]
    board_configs   = [b for b in boards if b.startswith("generic-")]

    suggested_configs = []
    if detected_mcu:
        print(f"\n{t('wizard.detected_mcu')}: {detected_mcu.upper()}\n")
        exact_matches = []
        for base_mcu, terms in _get_mcu_search_terms().items():
            if detected_mcu == base_mcu or detected_mcu.startswith(base_mcu):
                for b in board_configs:
                    if any(term in b.lower() for term in terms) and b not in exact_matches:
                        exact_matches.append(b)
                if exact_matches:
                    break
        if exact_matches:
            suggested_configs = exact_matches
        else:
            norm_det = _normalize_mcu_family(detected_mcu)
            if norm_det:
                fallback_matches = []
                for base_mcu, terms in _get_mcu_search_terms().items():
                    if (_normalize_mcu_family(base_mcu) == norm_det
                            or base_mcu.startswith(norm_det)
                            or norm_det.startswith(base_mcu)):
                        for b in board_configs:
                            if any(term in b.lower() for term in terms) and b not in fallback_matches:
                                fallback_matches.append(b)
                suggested_configs = fallback_matches

    if mcu_hint == "manual" and not detected_mcu:
        print("\nUsing manual MCU. You will have a chance to enter the compiler configuration later.")

    initial_defaults = {
        "mcu_path":              mcu_path,
        "mcu_type":              detected_mcu,
        "mcu_hint":              mcu_hint,
        "language":              get_lang(),
        "printer_profile":       None,
        "profile_loaded":        False,
        "board":                 None,
        "board_raw_config":      None,   # loaded in _step_board
        "board_parsed":          None,   # parsed in _step_board
        "kinematics":            "cartesian",
        "x_size":                "235",
        "y_size":                "235",
        "z_size":                "250",
        "x_position_endstop":    "0",
        "x_position_min":        "0",
        "x_position_max":        "235",
        "y_position_endstop":    "0",
        "y_position_min":        "0",
        "y_position_max":        "235",
        "z_position_endstop":    "0",
        "z_position_min":        "0",
        "z_position_max":        "250",
        "probe":                 "None",
        "hotend_thermistor":     "EPCOS 100K B57560G104F",
        "bed_thermistor":        "EPCOS 100K B57560G104F",
        "driver_type":           None,
        "driver_mode":           "Standalone",
        "z_motors":              None,
        "web_interface":         None,
        "display_choice":        None,
        "display_section":       None,
        "display_compat_class":  None,
        "display_risk_accepted": False,
        "probe_x_offset":        "0",
        "probe_y_offset":        "0",
        "fan_part_cooling_pin":  None,
        "fan_hotend_pin":        None,
    }

    # ── Step order: hardware first, software last ──────────────────────────────
    step_order = [
        "board",
        "fan_assignment",
        "z_motors",
        "z_socket_assignment",
        "driver_type",
        "driver_mode",
        "printer_profile",
        "profile_review",
        "kinematics",
        "x_volume",
        "y_volume",
        "z_volume",
        "x_limits",
        "y_limits",
        "z_limits",
        "probe",
        "bltouch_pins",
        "probe_offsets",
        "hotend_therm",
        "bed_therm",
        "display",
        "web_ui",
    ]

    # ── Step catalog ───────────────────────────────────────────────────────────
    steps_config = {
        "board": {
            "prompt": lambda ud: _step_board(ud, suggested_configs, board_configs),
            "next":   lambda ans, ud: "fan_assignment" if _has_fan_options(ud) else "z_motors"
        },
        "fan_assignment": {
            "prompt": lambda ud: _step_fan_assignment(ud),
            "next":   lambda ans, ud: "z_motors"
        },
        "z_motors": {
            "prompt": lambda ud: _step_z_motors(ud),
            "next":   lambda ans, ud: "driver_type" if int(ans or 1) <= 1 else "z_socket_assignment"
        },
        "z_socket_assignment": {
            "prompt": lambda ud: _step_z_socket_assignment(ud),
            # Skip assignment entirely when only 1 Z motor is used.
            "next":   lambda ans, ud: "driver_type"
        },
        "driver_type": {
            "prompt": lambda ud: _step_driver_type(ud),
            # Skip driver mode for basic/standalone drivers.
            "next":   lambda ans, ud: "printer_profile" if ans in ["None (Standard)", "A4988", "DRV8825"] else "driver_mode"
        },
        "driver_mode": {
            "prompt": lambda ud: _step_driver_mode(ud)
        },
        "printer_profile": {
            "prompt": lambda ud: _step_printer_profile(ud, printer_configs),
            # Skip profile_review when no real profile was loaded.
            "next":   lambda ans, ud: "kinematics" if not ud.get("profile_loaded") else "profile_review"
        },
        "profile_review": {
            "prompt": lambda ud: _step_profile_review(ud),
            # After review always continue to the next authoritative-skip steps.
            "next":   lambda ans, ud: "probe" if ans == "confirm" else _BACK
        },
        "kinematics": {
            "prompt": lambda ud: _step_kinematics(ud)
        },
        "x_volume": {
            "prompt": lambda ud: _step_volume(ud, "x_size", "x_position_max", t("wizard.x_volume"))
        },
        "y_volume": {
            "prompt": lambda ud: _step_volume(ud, "y_size", "y_position_max", t("wizard.y_volume"))
        },
        "z_volume": {
            "prompt": lambda ud: _step_volume(ud, "z_size", "z_position_max", t("wizard.z_volume"))
        },
        "x_limits": {
            "prompt": lambda ud: _step_x_limits(ud)
        },
        "y_limits": {
            "prompt": lambda ud: _step_y_limits(ud)
        },
        "z_limits": {
            "prompt": lambda ud: _step_z_limits(ud)
        },
        "probe": {
            "prompt": lambda ud: _step_probe(ud),
            "next":   lambda ans, ud: "hotend_therm" if ans == "None" else (
                "bltouch_pins" if ans in ("BLTouch", "CR-Touch") and _needs_bltouch_pins(ud) else "probe_offsets"
            )
        },
        "bltouch_pins": {
            "prompt": lambda ud: _step_bltouch_pins(ud),
            "next":   lambda ans, ud: "probe_offsets"
        },
        "probe_offsets": {
            "prompt": lambda ud: _step_probe_offsets(ud)
        },
        "hotend_therm": {
            "prompt": lambda ud: _step_therm(ud, "hotend_thermistor", t("wizard.select_hotend_therm"), t("wizard.custom_hotend_therm"))
        },
        "bed_therm": {
            "prompt": lambda ud: _step_therm(ud, "bed_thermistor", t("wizard.select_bed_therm"), t("wizard.custom_bed_therm"))
        },
        "display": {
            "prompt": lambda ud: _step_display(ud)
        },
        "web_ui": {
            "prompt": lambda ud: _step_web_ui(ud)
        },
    }

    if user_data_arg is None:
        user_data  = dict(initial_defaults)
        start_step = "board"
    else:
        user_data  = user_data_arg
        start_step = "web_ui"

    runner = WizardRunner(steps_config, step_order, initial_data=user_data)
    result_data = runner.run(start_step)
    _apply_z_tmc_mappings(result_data)

    # Merge printer profile pins into board_parsed to override board-default pins
    profile_parsed = result_data.get("_profile_parsed")
    board_parsed = result_data.get("board_parsed")
    if profile_parsed and board_parsed is not None:
        for section, section_data in profile_parsed.items():
            if section not in board_parsed:
                board_parsed[section] = {}
            for key, value in section_data.items():
                board_parsed[section][key] = value

    return result_data


def _apply_z_tmc_mappings(user_data: dict) -> None:
    """Post-processing step: maps Z stepper TMC configurations.

    This runs after the user has selected their driver_type and driver_mode,
    so we know exactly whether TMC sections are needed and what type/mode they are.
    """
    z_motors = int(user_data.get('z_motors') or 1)
    if z_motors <= 1:
        return

    assignments = user_data.get("z_socket_assignments")
    if not assignments:
        return

    parsed_data = user_data.get("board_parsed")
    if parsed_data is None:
        return

    raw_cfg = user_data.get("board_raw_config")
    if not raw_cfg:
        return

    driver_type = user_data.get("driver_type") or "None (Standard)"
    driver_mode = user_data.get("driver_mode") or ""

    if "TMC" not in driver_type:
        return

    # Parse full config with comments to find source TMC configuration blocks
    _parsed_full = parse_config(raw_cfg, user_data.get('board', ''), keep_comments=True)

    for motor_name, selected_driver in assignments.items():
        dest_tmc = f"{driver_type.lower()} {motor_name}"

        if selected_driver == "custom":
            if driver_mode in ["UART", "SPI"]:
                # Prompt for custom pin
                pin_key = "uart_pin" if driver_mode == "UART" else "cs_pin"
                if dest_tmc not in parsed_data or pin_key not in parsed_data[dest_tmc]:
                    uart_pin = questionary.text(
                        t("wizard.custom_uart_pin", mode=driver_mode.lower(), motor=motor_name),
                        validate=questionary_pin_validator,
                        style=custom_style
                    ).ask()
                    if not uart_pin:
                        print(f"\n\033[91m{t('kace.abort_no_uart', mode=driver_mode)}\033[0m")
                        raise WizardExit()
                    parsed_data[dest_tmc] = {pin_key: uart_pin, "run_current": "0.650"}
        else:
            # Socketed driver: copy TMC details from board config
            found_tmc = False
            for possible_tmc in ["tmc2209", "tmc2208", "tmc2130", "tmc5160", "tmc2225", "tmc2240"]:
                src_tmc = f"{possible_tmc} {selected_driver}"
                tmc_src_data = parsed_data.get(src_tmc) or _parsed_full.get(src_tmc)
                if tmc_src_data is not None:
                    parsed_data[dest_tmc] = tmc_src_data.copy()
                    parsed_data.pop(src_tmc, None)
                    found_tmc = True
                    break

            if not found_tmc and driver_mode in ["UART", "SPI"]:
                print(f"\n\033[91m{t('kace.abort_no_tmc_map', mode=driver_mode, driver=selected_driver)}\033[0m")
                print(f"\033[93m{t('kace.abort_generation')}\033[0m")
                raise WizardExit()


def _has_fan_options(user_data: dict) -> bool:
    raw_cfg = user_data.get("board_raw_config")
    if not raw_cfg:
        return False
    return len(detect_fan_pins(raw_cfg)) > 0


def _step_fan_assignment(user_data: dict) -> str:
    raw_cfg = user_data.get("board_raw_config", "")
    detected_fans = detect_fan_pins(raw_cfg)
    if not detected_fans:
        return "success"

    # Find board default pin if available
    default_fan_pin = None
    for f in detected_fans:
        if f["section"].lower() == "fan":
            default_fan_pin = f["pin"]
            break

    # ── 1. Part Cooling Fan ──
    part_choices = []
    if default_fan_pin:
        part_choices.append({
            "name": t("wizard.fan_board_default").format(pin=default_fan_pin),
            "value": "default"
        })

    # Add other detected pins
    for f in detected_fans:
        # Avoid duplicating the default fan choice
        if f["pin"] == default_fan_pin:
            continue
        part_choices.append({
            "name": f["label"],
            "value": f["pin"]
        })

    part_choices.extend([
        {"name": t("wizard.fan_custom"), "value": "custom"},
        {"name": t("wizard.fan_none"), "value": "none"},
        _back_choice(),
        _quit_choice()
    ])

    ans_part = questionary.select(
        t("wizard.part_cooling_prompt"),
        choices=part_choices,
        style=custom_style
    ).ask()

    if ans_part is None:
        raise WizardExit()
    if ans_part in [_BACK, _QUIT]:
        return ans_part

    final_part_pin = None
    if ans_part == "custom":
        custom_pin = questionary.text(
            t("wizard.fan_enter_custom"),
            validate=questionary_pin_validator,
            style=custom_style
        ).ask()
        if custom_pin is None:
            raise WizardExit()
        if not custom_pin.strip():
            return "__retry__"
        final_part_pin = custom_pin.strip()
    else:
        final_part_pin = ans_part

    # ── 2. Hotend Heatsink Fan ──
    # Filter choices to remove the selected part cooling pin
    used_part_pin = default_fan_pin if final_part_pin == "default" else final_part_pin

    hotend_choices = [
        {"name": t("wizard.fan_none"), "value": "none"}
    ]

    for f in detected_fans:
        if f["pin"] == used_part_pin:
            continue
        hotend_choices.append({
            "name": f["label"],
            "value": f["pin"]
        })

    hotend_choices.extend([
        {"name": t("wizard.fan_custom"), "value": "custom"},
        _back_choice(),
        _quit_choice()
    ])

    ans_hotend = questionary.select(
        t("wizard.hotend_fan_prompt"),
        choices=hotend_choices,
        style=custom_style
    ).ask()

    if ans_hotend is None:
        raise WizardExit()
    if ans_hotend in [_BACK, _QUIT]:
        return ans_hotend

    final_hotend_pin = None
    if ans_hotend == "custom":
        custom_pin = questionary.text(
            t("wizard.fan_enter_custom"),
            validate=questionary_pin_validator,
            style=custom_style
        ).ask()
        if custom_pin is None:
            raise WizardExit()
        if not custom_pin.strip():
            return "__retry__"
        final_hotend_pin = custom_pin.strip()
    else:
        final_hotend_pin = ans_hotend

    # Save the answers
    user_data["fan_part_cooling_pin"] = final_part_pin
    user_data["fan_hotend_pin"] = final_hotend_pin
    return "success"


# ── Step Helpers ──────────────────────────────────────────────────────────────

def _step_board(user_data, suggested_configs, board_configs):
    """Board selection step.

    Presents MCU-suggested boards at the top of the list.
    After selection, loads and stores the raw board config so subsequent
    wizard steps (Z socket assignment, display) can use it without re-fetching.
    """
    choices = []
    if suggested_configs:
        choices.append(questionary.Separator(f"── {t('wizard.select_board_suggested')} ──"))
        choices.extend(suggested_configs)
        choices.append(questionary.Separator("──────────────────────────────────────────────────"))
    choices.extend([
        {"name": t("choice.search_manually"), "value": "__search__"},
        _back_choice(),
        _quit_choice(),
    ])

    ans = questionary.select(
        t("wizard.select_board"),
        choices=choices,
        style=custom_style
    ).ask()

    if ans == _QUIT or ans is None:
        raise WizardExit()
    if ans == _BACK:
        return _BACK

    if ans == "__search__":
        ans = questionary.autocomplete(
            t("wizard.select_board_manual"),
            choices=board_configs,
            style=custom_style
        ).ask()
        if ans is None:
            return "__retry__"

    user_data["board"] = ans

    # ── Load board config immediately so subsequent steps have it ─────────────
    raw = fetch_raw_config(ans)
    if raw:
        user_data["board_raw_config"] = raw
        user_data["board_parsed"]     = parse_config(raw, ans, keep_comments=True)
    else:
        user_data["board_raw_config"] = None
        user_data["board_parsed"]     = {}

    return ans


def _step_printer_profile(user_data, printer_configs):
    """Printer profile selection step.

    Loads defaults from the selected profile and stores them in user_data.
    Does NOT call the profile review — that is a separate step.
    Returns the profile name, 'Custom / Scratch Build', or '__retry__'.
    """
    custom_choice_str = t("choice.custom_scratch")
    search_choice_str = t("choice.search_manually")
    
    choices = [
        {"name": f"✨  {custom_choice_str}", "value": "custom"},
        {"name": f"🔍  {search_choice_str}", "value": "search"},
        _back_choice(),
        _quit_choice(),
    ]

    ans = questionary.select(
        t("wizard.select_printer_model_menu"),
        choices=choices,
        style=custom_style
    ).ask()

    if ans == _QUIT or ans is None:
        raise WizardExit()
    if ans == _BACK:
        return _BACK

    if ans == "custom":
        user_data["printer_profile"] = "Custom / Scratch Build"
        user_data["profile_loaded"]  = False
        user_data.pop("_profile_parsed", None)
        user_data.pop("_profile_defaults", None)
        return "Custom / Scratch Build"

    if ans == "search":
        ans = questionary.autocomplete(
            t("wizard.select_printer_model"),
            choices=printer_configs,
            style=custom_style
        ).ask()
        if ans is None:
            return "__retry__"

    print(f"\n\033[96m>>> Loading defaults for {ans}...\033[0m")
    raw = fetch_raw_config(ans)
    if not raw:
        print(f"\n\033[91m[!] Failed to load printer profile: '{ans}'\033[0m")
        fallback = questionary.confirm(
            "Continue as Custom / Scratch Build?",
            default=True,
            style=custom_style
        ).ask()
        if fallback:
            user_data["printer_profile"] = "Custom / Scratch Build"
            user_data["profile_loaded"]  = False
            user_data.pop("_profile_parsed", None)
            user_data.pop("_profile_defaults", None)
            return "Custom / Scratch Build"
        return "__retry__"

    user_data["printer_profile"] = ans
    user_data["raw_config"]      = raw
    parsed   = parse_config(raw, ans)
    defaults = extract_profile_defaults(parsed)
    for k, v in defaults.items():
        user_data[k] = v
    user_data["profile_loaded"]  = True
    # Store parsed profile for the review step
    user_data["_profile_parsed"]   = parsed
    user_data["_profile_defaults"] = defaults
    return ans


def _step_profile_review(user_data):
    """Profile Review step — information screen with 3-choice menu.

    Shown only when a real printer profile was loaded.  Calls the staged editor
    on request.  After editor Save, reprints the review with updated values.
    Marks profile keys as authoritative on Continue so downstream steps skip.

    Returns 'confirm', '__back__', or '__retry__'.
    """
    parsed   = user_data.get("_profile_parsed",   {})
    defaults = user_data.get("_profile_defaults",  {})

    result = _step_profile_review_inner(defaults, parsed, user_data)

    if result == "back":
        # Clear profile so printer_profile step reruns cleanly
        user_data["profile_loaded"] = False
        user_data.pop("_profile_parsed", None)
        user_data.pop("_profile_defaults", None)
        return _BACK

    # result == "confirm" → mark keys as authoritative
    _profile_keys = {
        "kinematics",
        "x_size", "y_size", "z_size",
        "x_position_min", "x_position_max", "x_position_endstop",
        "y_position_min", "y_position_max", "y_position_endstop",
        "z_position_min", "z_position_max", "z_position_endstop",
        "hotend_thermistor", "bed_thermistor",
    }
    existing_auth = user_data.get("_authoritative", set())
    user_data["_authoritative"] = existing_auth | _profile_keys
    return "confirm"



def _step_z_socket_assignment(user_data):
    """Z motor socket assignment step — runs inside the wizard.

    Uses user_data['board_parsed'] (already loaded in _step_board).
    Modifies board_parsed in place so kace.py can use it directly.
    Returns '__skip__' when only 1 Z motor is configured.
    """
    z_motors = int(user_data.get('z_motors', 1))
    if z_motors <= 1:
        return "__skip__"

    raw_cfg   = user_data.get('board_raw_config') or fetch_raw_config(user_data['board'])
    parsed_data = user_data.get('board_parsed')
    if parsed_data is None:
        parsed_data = parse_config(raw_cfg, user_data.get('board', ''), keep_comments=True)
        user_data['board_parsed'] = parsed_data

    available_driver_sockets = list(get_reusable_driver_sockets(raw_cfg, user_data.get('board', '')))

    _parsed_full   = None
    z_idx          = 2
    assigned_drivers = {}

    while z_idx <= z_motors:
        motor_name = f"stepper_z{z_idx - 1}"

        if motor_name in parsed_data:
            z_idx += 1
            continue

        driver_choices = []
        for idx_s, (sock_key, sock_label) in enumerate(available_driver_sockets):
            display_label = f"{sock_label}  ✓ Recommended" if idx_s == 0 else sock_label
            driver_choices.append({"name": display_label, "value": sock_key})

        driver_choices.append({"name": t("choice.custom_pins"),  "value": "custom"})
        driver_choices.append({"name": t("choice.back") or "Back", "value": "back"})
        driver_choices.append({"name": t("choice.quit_setup"),   "value": "quit"})

        print(f"\n\033[96m{t('wizard.mapping_pins', motor=motor_name)}\033[0m")
        selected_driver = questionary.select(
            t("wizard.select_driver_z", motor=motor_name.upper()),
            choices=driver_choices,
            style=custom_style
        ).ask()

        if selected_driver == "quit" or selected_driver is None:
            raise WizardExit()

        if selected_driver == "back":
            if z_idx > 2:
                z_idx -= 1
                prev_motor = f"stepper_z{z_idx - 1}"
                if prev_motor in assigned_drivers:
                    prev_key = assigned_drivers[prev_motor]
                    if prev_key != "custom":
                        _label = prev_key.replace("extruder_stepper ", "").upper() \
                            if prev_key.startswith("extruder_stepper ") \
                            else f"E{prev_key.replace('extruder', '')}"
                        available_driver_sockets.append((prev_key, _label))
                        available_driver_sockets.sort(key=lambda t_: t_[0])
                        parsed_data.pop(prev_motor, None)
                continue
            else:
                return _BACK

        if selected_driver == "custom":
            print(t("wizard.assign_custom_pins_header", motor=motor_name))
            step_pin = questionary.text(t("wizard.custom_step_pin"), validate=questionary_pin_validator, style=custom_style).ask()
            dir_pin  = questionary.text(t("wizard.custom_dir_pin"),  validate=questionary_pin_validator, style=custom_style).ask()
            en_pin   = questionary.text(t("wizard.custom_en_pin"),   validate=questionary_pin_validator, style=custom_style).ask()
            if not step_pin or not dir_pin or not en_pin:
                print(f"\n\033[91m{t('kace.abort_valid_pins')}\033[0m")
                raise WizardExit()
            parsed_data[motor_name] = {"step_pin": step_pin, "dir_pin": dir_pin, "enable_pin": en_pin}
            assigned_drivers[motor_name] = "custom"
        else:
            src_data = parsed_data.get(selected_driver)
            if src_data is None:
                if _parsed_full is None:
                    _parsed_full = parse_config(raw_cfg, user_data.get('board', ''), keep_comments=True)
                src_data = _parsed_full.get(selected_driver, {})
            parsed_data[motor_name] = {
                "step_pin":   src_data.get("step_pin",   ""),
                "dir_pin":    src_data.get("dir_pin",    ""),
                "enable_pin": src_data.get("enable_pin", ""),
            }
            parsed_data.pop(selected_driver, None)
            available_driver_sockets = [(k, l) for k, l in available_driver_sockets if k != selected_driver]
            assigned_drivers[motor_name] = selected_driver

        z_idx += 1

    user_data["z_socket_assignments"] = assigned_drivers
    return "done"


def _step_display(user_data):
    """Display setup step — wraps run_display_setup_step inside the wizard."""
    parsed_cfg = user_data.get('board_parsed') or {}
    display_result = run_display_setup_step(
        user_data=user_data,
        parsed_cfg=parsed_cfg,
        board_filename=user_data.get("board") or "",
    )
    if display_result.get("display_choice") == "__back__":
        return _BACK
    user_data.update({
        "display_choice":        display_result.get("display_choice"),
        "display_section":       display_result.get("display_section"),
        "display_compat_class":  display_result.get("display_compat_class"),
        "display_risk_accepted": display_result.get("display_risk_accepted", False),
    })
    return display_result.get("display_choice") or "none"


def _step_kinematics(user_data):
    if "kinematics" in user_data.get("_authoritative", set()):
        return user_data["kinematics"]
    ans = questionary.select(
        t("wizard.select_kinematics"),
        choices=["cartesian", "corexy", "delta", _back_choice(), _quit_choice()],
        default=user_data["kinematics"] if user_data["kinematics"] in ["cartesian", "corexy", "delta"] else None,
        style=custom_style
    ).ask()
    if ans == _QUIT or ans is None: raise WizardExit()
    if ans == _BACK: return _BACK
    user_data["kinematics"] = ans
    return ans

def _step_volume(user_data, size_key, max_key, msg_text):
    if size_key in user_data.get("_authoritative", set()):
        return user_data[size_key]
    ans = questionary.text(
        msg_text,
        default=str(user_data.get(size_key) or ""),
        validate=questionary_pos_numeric_validator,
        style=custom_style
    ).ask()
    if ans is None or ans.strip().lower() in ("<", "back", "volver"):
        return _BACK
    val_clean = ans.strip()
    old_val = user_data.get(size_key)
    user_data[size_key] = val_clean
    if user_data.get(max_key) == old_val or not user_data.get(max_key):
        user_data[max_key] = val_clean
    return val_clean

def _step_x_limits(user_data):
    prompts = ["min", "max", "endstop"]
    idx = 0
    while idx < len(prompts):
        curr = prompts[idx]
        if curr == "min":
            val = questionary.text(
                t("wizard.x_position_min") or "Enter X position_min (mm) [type '<' to go back]:",
                default=str(user_data.get("x_position_min") if user_data.get("x_position_min") is not None else "0"),
                validate=questionary_numeric_validator,
                style=custom_style
            ).ask()
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                return _BACK
            user_data["x_position_min"] = val.strip()
            idx += 1
        elif curr == "max":
            val = questionary.text(
                t("wizard.x_position_max") or "Enter X position_max (mm) [type '<' to go back]:",
                default=str(user_data.get("x_position_max") or user_data.get("x_size") or "235"),
                validate=questionary_numeric_validator,
                style=custom_style
            ).ask()
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["x_position_max"] = val.strip()
            user_data["x_size"] = val.strip()
            idx += 1
        elif curr == "endstop":
            val = questionary.text(
                t("wizard.x_position_endstop") or "Enter X position_endstop (mm) [type '<' to go back]:",
                default=str(user_data.get("x_position_endstop") if user_data.get("x_position_endstop") is not None else "0"),
                validate=questionary_numeric_validator,
                style=custom_style
            ).ask()
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["x_position_endstop"] = val.strip()
            idx += 1
    return "done"

def _step_y_limits(user_data):
    prompts = ["min", "max", "endstop"]
    idx = 0
    while idx < len(prompts):
        curr = prompts[idx]
        if curr == "min":
            val = questionary.text(
                t("wizard.y_position_min") or "Enter Y position_min (mm) [type '<' to go back]:",
                default=str(user_data.get("y_position_min") if user_data.get("y_position_min") is not None else "0"),
                validate=questionary_numeric_validator,
                style=custom_style
            ).ask()
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                return _BACK
            user_data["y_position_min"] = val.strip()
            idx += 1
        elif curr == "max":
            val = questionary.text(
                t("wizard.y_position_max") or "Enter Y position_max (mm) [type '<' to go back]:",
                default=str(user_data.get("y_position_max") or user_data.get("y_size") or "235"),
                validate=questionary_numeric_validator,
                style=custom_style
            ).ask()
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["y_position_max"] = val.strip()
            user_data["y_size"] = val.strip()
            idx += 1
        elif curr == "endstop":
            val = questionary.text(
                t("wizard.y_position_endstop") or "Enter Y position_endstop (mm) [type '<' to go back]:",
                default=str(user_data.get("y_position_endstop") if user_data.get("y_position_endstop") is not None else "0"),
                validate=questionary_numeric_validator,
                style=custom_style
            ).ask()
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["y_position_endstop"] = val.strip()
            idx += 1
    return "done"

def _step_z_limits(user_data):
    prompts = ["min", "max", "endstop"]
    idx = 0
    while idx < len(prompts):
        curr = prompts[idx]
        if curr == "min":
            val = questionary.text(
                t("wizard.z_position_min") or "Enter Z position_min (mm) [type '<' to go back]:",
                default=str(user_data.get("z_position_min") if user_data.get("z_position_min") is not None else "0"),
                validate=questionary_numeric_validator,
                style=custom_style
            ).ask()
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                return _BACK
            user_data["z_position_min"] = val.strip()
            idx += 1
        elif curr == "max":
            val = questionary.text(
                t("wizard.z_position_max") or "Enter Z position_max (mm) [type '<' to go back]:",
                default=str(user_data.get("z_position_max") or user_data.get("z_size") or "250"),
                validate=questionary_numeric_validator,
                style=custom_style
            ).ask()
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["z_position_max"] = val.strip()
            user_data["z_size"] = val.strip()
            idx += 1
        elif curr == "endstop":
            val = questionary.text(
                t("wizard.z_position_endstop") or "Enter Z position_endstop (mm) [type '<' to go back]:",
                default=str(user_data.get("z_position_endstop") if user_data.get("z_position_endstop") is not None else "0"),
                validate=questionary_numeric_validator,
                style=custom_style
            ).ask()
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["z_position_endstop"] = val.strip()
            idx += 1
    return "done"

def _step_probe(user_data):
    ans = questionary.select(
        t("wizard.select_probe"),
        choices=["None", "BLTouch", "Inductive", "CR-Touch", _back_choice(), _quit_choice()],
        default=user_data["probe"] if user_data["probe"] in ["None", "BLTouch", "Inductive", "CR-Touch"] else None,
        style=custom_style
    ).ask()
    if ans == _QUIT or ans is None: raise WizardExit()
    if ans == _BACK: return _BACK
    user_data["probe"] = ans
    return ans

def _needs_bltouch_pins(user_data) -> bool:
    parsed_board = get_current_board_parsed(user_data)
    blt = parsed_board.get("bltouch", {})
    s_pin = blt.get("sensor_pin")
    c_pin = blt.get("control_pin")

    def is_missing(p):
        if not p:
            return True
        p_clean = str(p).strip().upper().lstrip('^!~')
        return p_clean == "TODO" or p_clean == ""

    return is_missing(s_pin) or is_missing(c_pin)

def _get_mcu_for_board(board_name: str) -> str:
    if not board_name:
        return ""
    try:
        from core.loader import load_boards_yaml
        db = load_boards_yaml()
        board_lower = board_name.lower()
        for entry in db.get('boards', []):
            mcu = entry.get('mcu', '')
            search_terms = entry.get('search_terms', [])
            for term in search_terms:
                if term.lower() in board_lower:
                    return mcu
    except Exception:
        pass
    return ""

def _get_unused_pins(user_data) -> list:
    """Scan parsed board config for all used pins, and return a list of typical unused microcontroller pins."""
    import re
    parsed_board = get_current_board_parsed(user_data)
    
    # Collect all used pins in the config
    used_pins = set()
    pin_pattern = re.compile(r'^[!^~]*([A-Za-z0-9_.]+)$')
    for section, sdata in parsed_board.items():
        if isinstance(sdata, dict):
            for key, val in sdata.items():
                if isinstance(val, str):
                    match = pin_pattern.match(val.strip())
                    if match:
                        used_pins.add(match.group(1).lower())
                    
    # Let's get the MCU
    board_name = user_data.get("board", "")
    mcu = _get_mcu_for_board(board_name)
    if not mcu:
        mcu = user_data.get("mcu_type", "").lower()
    else:
        mcu = mcu.lower()
        
    # We can also get all pins mentioned in aliases
    board_pins = parsed_board.get("board_pins", {})
    aliases_str = board_pins.get("aliases", "") if isinstance(board_pins, dict) else ""
    all_alias_pins = {}
    if aliases_str:
        # e.g. EXP1_1=PB5, EXP1_2=PB6
        for part in aliases_str.replace('\n', ',').split(','):
            if '=' in part:
                parts = part.split('=', 1)
                alias_name = parts[0].strip()
                target_pin = parts[1].strip().lstrip('!^~')
                if target_pin:
                    all_alias_pins[target_pin.lower()] = alias_name
                    
    # Generate list of candidate pins based on MCU type
    all_mcu_pins = []
    if "1284" in mcu or "atmega1284" in mcu:
        # Melzi / AVR 1284p
        all_mcu_pins = [f"PA{i}" for i in range(8)] + [f"PB{i}" for i in range(8)] + [f"PC{i}" for i in range(8)] + [f"PD{i}" for i in range(8)]
    elif "2560" in mcu or "atmega2560" in mcu:
        all_mcu_pins = [f"PA{i}" for i in range(8)] + [f"PB{i}" for i in range(8)] + [f"PC{i}" for i in range(8)] + [f"PD{i}" for i in range(8)] + \
                       [f"PE{i}" for i in range(8)] + [f"PF{i}" for i in range(8)] + [f"PG{i}" for i in range(6)] + [f"PH{i}" for i in range(8)] + \
                       [f"PJ{i}" for i in range(8)] + [f"PK{i}" for i in range(8)] + [f"PL{i}" for i in range(8)]
    elif "stm32" in mcu:
        all_mcu_pins = [f"PA{i}" for i in range(16)] + [f"PB{i}" for i in range(16)] + [f"PC{i}" for i in range(16)] + [f"PD{i}" for i in range(16)] + \
                       [f"PE{i}" for i in range(16)] + [f"PF{i}" for i in range(16)] + [f"PG{i}" for i in range(16)] + [f"PH{i}" for i in range(16)]
    elif "rp2040" in mcu:
        all_mcu_pins = [f"gpio{i}" for i in range(30)]
    elif "lpc176" in mcu:
        all_mcu_pins = [f"P0.{i}" for i in range(32)] + [f"P1.{i}" for i in range(32)] + [f"P2.{i}" for i in range(14)]
        
    unused = []
    # First, let's suggest EXP alias pins that are not used
    for pin_lower, alias in all_alias_pins.items():
        if pin_lower not in used_pins:
            unused.append((alias, pin_lower.upper()))
            
    # Then suggest raw unused MCU pins
    for pin in all_mcu_pins:
        if pin.lower() not in used_pins and pin.lower() not in all_alias_pins:
            unused.append((pin, pin.upper()))
            
    return unused

def make_pin_validator_with_collision_check(user_data):
    import re
    parsed_board = get_current_board_parsed(user_data)
    
    # Pre-build a map of pin -> component name
    pin_pattern = re.compile(r'^[!^~]*([A-Za-z0-9_.]+)$')
    used_pins_map = {}
    aliases = []
    
    if isinstance(parsed_board, dict):
        # Extract aliases from [board_pins]
        board_pins = parsed_board.get("board_pins", {})
        aliases_str = board_pins.get("aliases", "") if isinstance(board_pins, dict) else ""
        if aliases_str:
            for part in aliases_str.replace('\n', ',').split(','):
                if '=' in part:
                    alias_name = part.split('=', 1)[0].strip()
                    if alias_name:
                        aliases.append(alias_name)
                        
        for section, sdata in parsed_board.items():
            if isinstance(sdata, dict):
                for key, val in sdata.items():
                    if isinstance(val, str):
                        match = pin_pattern.match(val.strip())
                        if match:
                            pin_name = match.group(1).upper()
                            comp = section
                            if section.startswith("stepper_"):
                                comp = f"stepper {section.replace('stepper_', '').upper()}"
                            used_pins_map[pin_name] = f"{comp} ({key})"

    def validator(value: str):
        val_strip = value.strip()
        val_lower = val_strip.lower()
        if val_lower in ("<", "back", "volver"):
            return True
            
        # Standard format check first
        fmt_res = questionary_pin_validator(val_strip)
        if fmt_res != True:
            return fmt_res
            
        # Collision check
        match = pin_pattern.match(val_strip)
        if not match:
            return "Invalid Klipper pin format"
            
        pin_name = match.group(1).upper()
        if pin_name in used_pins_map:
            lang = get_lang()
            comp_info = used_pins_map[pin_name]
            if lang == "Español":
                return f"El pin {pin_name} ya está en uso por: {comp_info}"
            elif lang == "Português":
                return f"O pino {pin_name} já está em uso por: {comp_info}"
            else:
                return f"Pin {pin_name} is already in use by: {comp_info}"
                
        # MCU specific physical pin checks
        board_name = user_data.get("board", "")
        mcu = _get_mcu_for_board(board_name)
        if not mcu:
            mcu = user_data.get("mcu_type", "").lower()
        else:
            mcu = mcu.lower()
            
        if mcu:
            pin_clean = pin_name.lower()
            
            # Check if it is a defined board alias
            is_alias = False
            for alias in aliases:
                if pin_clean == alias.lower():
                    is_alias = True
                    break
                    
            if not is_alias:
                # Validate against MCU architecture specs
                if "1284" in mcu or "atmega1284" in mcu:
                    if not re.match(r'^p[a-d][0-7]$', pin_clean):
                        lang = get_lang()
                        if lang == "Español":
                            return f"Pin inválido para ATMEGA1284P. Debe ser tipo PA0-PD7 (ej. PA5)."
                        elif lang == "Português":
                            return f"Pino inválido para ATMEGA1284P. Deve ser tipo PA0-PD7 (ex. PA5)."
                        else:
                            return f"Invalid pin for ATMEGA1284P. Must be PA0-PD7 (e.g. PA5)."
                            
                elif "2560" in mcu or "atmega2560" in mcu or mcu == "avr":
                    if not (re.match(r'^p[a-l][0-7]$', pin_clean) or re.match(r'^(ar|analog)\d+$', pin_clean)):
                        lang = get_lang()
                        if lang == "Español":
                            return f"Pin inválido para AVR/ATMEGA2560. Debe ser tipo PA0-PL7 o ar0-ar69."
                        elif lang == "Português":
                            return f"Pino inválido para AVR/ATMEGA2560. Deve ser tipo PA0-PL7 ou ar0-ar69."
                        else:
                            return f"Invalid pin for AVR/ATMEGA2560. Must be PA0-PL7 or ar0-ar69."
                            
                elif "stm32" in mcu:
                    if not re.match(r'^p[a-i](1[0-5]|\d)$', pin_clean):
                        lang = get_lang()
                        if lang == "Español":
                            return f"Pin inválido para STM32. Debe ser tipo PA0-PI15 (ej. PB7)."
                        elif lang == "Português":
                            return f"Pino inválido para STM32. Deve ser tipo PA0-PI15 (ex. PB7)."
                        else:
                            return f"Invalid pin for STM32. Must be PA0-PI15 (e.g. PB7)."
                            
                elif "rp2040" in mcu:
                    if not re.match(r'^gpio(2[0-9]|[0-1]?\d)$', pin_clean):
                        lang = get_lang()
                        if lang == "Español":
                            return f"Pin inválido para RP2040. Debe ser tipo gpio0-gpio29."
                        elif lang == "Português":
                            return f"Pino inválido para RP2040. Deve ser tipo gpio0-gpio29."
                        else:
                            return f"Invalid pin for RP2040. Must be gpio0-gpio29."
                            
                elif "lpc176" in mcu:
                    if not re.match(r'^p[0-4]\.(3[0-1]|[0-2]?\d)$', pin_clean):
                        lang = get_lang()
                        if lang == "Español":
                            return f"Pin inválido para LPC176x. Debe ser tipo P0.0-P4.29 (ej. P0.10)."
                        elif lang == "Português":
                            return f"Pino inválido para LPC176x. Deve ser tipo P0.0-P4.29 (ex. P0.10)."
                        else:
                            return f"Invalid pin for LPC176x. Must be P0.0-P4.29 (e.g. P0.10)."
                            
        return True
        
    return validator

def _step_bltouch_pins(user_data):
    parsed_board = get_current_board_parsed(user_data)
    blt = parsed_board.get("bltouch", {})
    missing_sensor = not blt.get("sensor_pin")
    missing_control = not blt.get("control_pin")
    
    if os.environ.get("KACE_AUTO") != "1" and os.environ.get("KACE_QUIET") != "1":
        board_name = user_data.get("board", "")
        unused = _get_unused_pins(user_data)
        lang = get_lang()
        if lang == "Español":
            msg = f"\n[!] Se seleccionó BLTouch/CR-Touch pero se desconoce el mapa de pines para la placa:\n    {board_name}\n"
            msg += "    Ingrese los pines manualmente a continuación (puedes escribir '<' o 'volver' para regresar).\n"
            if unused:
                suggested_str = ", ".join([f"{u[0]}" for u in unused[:6]])
                msg += f"    Pines no asignados que podrían estar libres: {suggested_str}\n"
        elif lang == "Português":
            msg = f"\n[!] BLTouch/CR-Touch selecionado, mas o mapeamento de pinos é desconhecido para a placa:\n    {board_name}\n"
            msg += "    Insira os pinos manualmente abaixo (digite '<' ou 'voltar' para retornar).\n"
            if unused:
                suggested_str = ", ".join([f"{u[0]}" for u in unused[:6]])
                msg += f"    Pinos não atribuídos que podem estar livres: {suggested_str}\n"
        else:
            msg = f"\n[!] BLTouch/CR-Touch selected but pin mapping is unknown for board:\n    {board_name}\n"
            msg += "    Enter the pins manually below (you can type '<' or 'back' to go back).\n"
            if unused:
                suggested_str = ", ".join([f"{u[0]}" for u in unused[:6]])
                msg += f"    Unassigned pins that might be free: {suggested_str}\n"
        print(msg)

    prompts = []
    if missing_sensor:
        prompts.append("sensor")
    if missing_control:
        prompts.append("control")
        
    idx = 0
    while idx < len(prompts):
        current_prompt = prompts[idx]
        if current_prompt == "sensor":
            sp = questionary.text(
                t("wizard.bltouch_sensor_prompt") or "BLTouch sensor_pin (e.g. ^PB7 or ^PC5):",
                default=user_data.get("bltouch_sensor_pin") or "",
                validate=make_pin_validator_with_collision_check(user_data),
                style=custom_style
            ).ask()
            if sp is None or sp.strip().lower() in ("<", "back", "volver"):
                return _BACK
            user_data["bltouch_sensor_pin"] = sp.strip()
            idx += 1
            
        elif current_prompt == "control":
            cp = questionary.text(
                t("wizard.bltouch_control_prompt") or "BLTouch control_pin (e.g. PB6 or PE5):",
                default=user_data.get("bltouch_control_pin") or "",
                validate=make_pin_validator_with_collision_check(user_data),
                style=custom_style
            ).ask()
            if cp is None or cp.strip().lower() in ("<", "back", "volver"):
                if idx > 0:
                    idx -= 1
                    continue
                else:
                    return _BACK
            user_data["bltouch_control_pin"] = cp.strip()
            idx += 1
            
    return "done"

def _step_probe_offsets(user_data):
    offset_result = run_probe_offset_step(
        user_data=user_data,
        board_filename=user_data.get("board") or "",
    )
    if offset_result.get("probe_x_offset") == "__back__" or \
       offset_result.get("probe_y_offset") == "__back__":
        return _BACK
    user_data["probe_x_offset"] = offset_result.get("probe_x_offset", "0")
    user_data["probe_y_offset"] = offset_result.get("probe_y_offset", "0")
    return "done"

def _step_therm(user_data, therm_key, select_msg, custom_msg):
    if therm_key in user_data.get("_authoritative", set()):
        return user_data[therm_key]
    preset_choices = list(THERMISTOR_PRESETS)
    if user_data[therm_key] not in preset_choices:
        preset_choices.insert(0, user_data[therm_key])
    choices = preset_choices + [{"name": t("choice.other_manual"), "value": "__other__"}, _back_choice(), _quit_choice()]

    ans = questionary.select(
        select_msg,
        choices=choices,
        default=user_data[therm_key] if user_data[therm_key] in preset_choices else None,
        style=custom_style
    ).ask()
    if ans == _QUIT or ans is None: raise WizardExit()
    if ans == _BACK: return _BACK
    if ans == "__other__":
        manual_ans = questionary.text(custom_msg, style=custom_style).ask()
        if manual_ans is None:
            return "__retry__"
        user_data[therm_key] = manual_ans
    else:
        user_data[therm_key] = ans
    return ans

def _step_driver_type(user_data):
    base_choices = ["None (Standard)", "TMC2208", "TMC2209", "TMC2225", "TMC2130", "TMC5160", "A4988", "DRV8825"]
    parsed_board = get_current_board_parsed(user_data)
    driver_info = detect_driver_info(parsed_board, user_data.get("board") or "")
    detected_type = driver_info.get("driver_type")
    is_integrated = driver_info.get("integrated")
    is_socketed = driver_info.get("is_socketed")
    
    formatted_choices = []
    preselected_index = 0
    for idx, choice in enumerate(base_choices):
        name = choice
        value = choice
        if is_integrated and choice == detected_type:
            name = f"{choice}  ✓ Recommended (Detected from board profile)"
            preselected_index = idx
        elif is_integrated and choice == "None (Standard)":
            name = f"{choice}  (Not Recommended for integrated TMC)"
        formatted_choices.append(questionary.Choice(title=name, value=value))
        
    back_ch = _back_choice()
    quit_ch = _quit_choice()
    formatted_choices.append(questionary.Choice(title=back_ch["name"], value=back_ch["value"]))
    formatted_choices.append(questionary.Choice(title=quit_ch["name"], value=quit_ch["value"]))
    
    default_choice = formatted_choices[preselected_index].value
    
    ans = questionary.select(
        t("wizard.select_driver") or "Select Stepper Driver Type:",
        choices=formatted_choices,
        default=default_choice,
        style=custom_style
    ).ask()
    
    if ans == _QUIT or ans is None: raise WizardExit()
    if ans == _BACK: return _BACK
    
    if not is_integrated and not is_socketed and ans == "None (Standard)":
        confirm_standalone = questionary.confirm(
            t("wizard.confirm_standalone"),
            default=False,
            style=custom_style
        ).ask()
        if not confirm_standalone:
            return "__retry__"

    user_data["driver_type"] = ans
    return ans

def _step_driver_mode(user_data):
    base_modes = ["UART", "SPI", "Standalone"]
    parsed_board = get_current_board_parsed(user_data)
    driver_info = detect_driver_info(parsed_board, user_data.get("board") or "")
    is_integrated = driver_info.get("integrated")
    detected_mode = driver_info.get("driver_mode")
    preselected_mode_index = 0
    
    formatted_modes = []
    for idx, mode in enumerate(base_modes):
        name = mode
        value = mode
        if is_integrated and mode == detected_mode:
            name = f"{mode}  ✓ Recommended (Detected from board profile)"
            preselected_mode_index = idx
        formatted_modes.append(questionary.Choice(title=name, value=value))
        
    back_ch = _back_choice()
    quit_ch = _quit_choice()
    formatted_modes.append(questionary.Choice(title=back_ch["name"], value=back_ch["value"]))
    formatted_modes.append(questionary.Choice(title=quit_ch["name"], value=quit_ch["value"]))
    
    default_mode = formatted_modes[preselected_mode_index].value
    
    ans = questionary.select(
        t("wizard.select_driver_mode", driver=user_data["driver_type"]) or f"Select communication mode for {user_data['driver_type']}:",
        choices=formatted_modes,
        default=default_mode,
        style=custom_style
    ).ask()
    
    if ans == _QUIT or ans is None: raise WizardExit()
    if ans == _BACK: return _BACK
    user_data["driver_mode"] = ans
    return ans

def _step_web_ui(user_data):
    ans = questionary.select(
        t("wizard.select_web_ui"),
        choices=["Mainsail", "Fluidd", "None", _back_choice(), _quit_choice()],
        style=custom_style
    ).ask()
    if ans == _QUIT or ans is None: raise WizardExit()
    if ans == _BACK: return _BACK
    user_data["web_interface"] = ans
    return ans

def _step_z_motors(user_data):
    ans = questionary.select(
        t("wizard.z_motors"),
        choices=["1", "2", "3", "4", _back_choice(), _quit_choice()],
        style=custom_style
    ).ask()
    if ans == _QUIT or ans is None: raise WizardExit()
    if ans == _BACK: return _BACK
    user_data["z_motors"] = ans
    return ans



