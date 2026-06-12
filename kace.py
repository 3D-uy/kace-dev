#!/usr/bin/env python3

import os as _os
from core.loader import read_version as _read_version
__version__ = _read_version()

import os
import sys
import time

# ── Normalize stdout/stderr to UTF-8 (critical for Windows) ──
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, OSError):
    # Python < 3.7 or non-reconfigurable streams (e.g., piped output in some CI)
    pass

# ── Early argument handling (no heavy imports needed) ─────────
if len(sys.argv) > 1:
    if sys.argv[1] in ("--version", "-v"):
        print(f"KACE {__version__}")
        sys.exit(0)
    
    for i, arg in enumerate(sys.argv):
        if arg == "--auto":
            os.environ["KACE_AUTO"] = "1"

import questionary
from core.validators import questionary_pin_validator

if os.environ.get("KACE_AUTO") == "1":
    print("\n\033[93m[AUTO MODE]\033[0m User interactions disabled. Using safe defaults for all prompts.", flush=True)
    
    class MockQuestionary:
        def __init__(self, default_val):
            self.default_val = default_val
        def ask(self):
            return self.default_val

    def mock_select(msg, choices, default=None, **kwargs):
        if not choices:
            val = default
        elif isinstance(choices[0], str):
            val = choices[0]
        elif isinstance(choices[0], dict):
            val = choices[0].get('value')
        else:
            val = getattr(choices[0], 'value', None)
        return MockQuestionary(default if default is not None else val)

    def mock_autocomplete(msg, choices, **kwargs):
        val = choices[0] if choices else None
        return MockQuestionary(val)

    def mock_text(msg, default="", **kwargs):
        return MockQuestionary(default)
        
    def mock_confirm(msg, default=False, **kwargs):
        return MockQuestionary(default) # Safe default: aborts builds/deployments

    def mock_password(msg, **kwargs):
        return MockQuestionary("")

    questionary.select = mock_select
    questionary.autocomplete = mock_autocomplete
    questionary.text = mock_text
    questionary.confirm = mock_confirm
    questionary.password = mock_password

from core.scraper import fetch_raw_config, parse_config
from core.wizard import run_wizard
from core.exceptions import WizardExit, GenerationError
from core.style import custom_style
from core.generator import generate_config, has_todo_pins
from core.deployer import deploy_config, deploy_usb, deploy_local, deploy_avrdude, deploy_moonraker
from core.banner import print_kace_banner
from core.translations import t
from core.display_checker import check_display_compatibility
from core.summary import print_summary

# print_summary has been refactored into core.summary to improve testability.


def _print_display_warning(findings: list) -> bool:
    """Print a formatted ANSI display compatibility warning block.

    For findings with status 'partial' or 'unsupported', prompts the user
    to confirm before continuing. Returns True to continue, False to abort.
    """
    Y  = "\033[93m"   # amber / warning
    R  = "\033[91m"   # red / error
    C  = "\033[96m"   # cyan / info
    G  = "\033[92m"   # green / ok
    B  = "\033[1m"    # bold
    RS = "\033[0m"    # reset
    W  = "\033[97m"   # bright white
    M  = "\033[95m"   # magenta
    O  = "\033[38;5;208m" # orange for experimental

    _CLASS_COLORS = {
        "fully_compatible":        G,
        "compatible_with_adapter": Y,
        "experimental":            O,
        "unsafe":                  R,
    }

    # If all findings are fully_compatible, skip warnings and prompts
    if all(f.get("compatibility_class") == "fully_compatible" for f in findings):
        return True

    # Check if we have any unsafe findings
    has_unsafe = any(f.get("compatibility_class") == "unsafe" for f in findings)
    needs_confirm = any(f.get("compatibility_class") != "fully_compatible" for f in findings)

    border_color = R if has_unsafe else Y

    print("")
    print(f"  {border_color}{B}{'═' * 52}{RS}")
    if has_unsafe:
        print(f"  {border_color}{B}  ⚠️  HARDWARE SAFETY WARNING — DO NOT IGNORE{RS}")
    else:
        print(f"  {border_color}{B}  ⚠️  {t('display.warning_header')}{RS}")
    print(f"  {border_color}{B}{'═' * 52}{RS}")
    print("")
    print(f"  {W}{t('display.oem_explanation')}{RS}")
    print("")

    for finding in findings:
        section = finding.get("section", "?")
        comp_class = finding.get("compatibility_class", "experimental")
        rec = finding.get("recommendation", "none")
        notes = finding.get("notes", [])
        sc = _CLASS_COLORS.get(comp_class, C)

        class_names = {
            "fully_compatible":        "Fully Compatible",
            "compatible_with_adapter": "Compatible with Adapter/Modification",
            "experimental":            "Experimental",
            "unsafe":                  "UNSAFE / HIGH RISK",
        }
        status_str = class_names.get(comp_class, comp_class.upper())
        print(f"  {B}{t('display.section_label')}:{RS} [{section}]   {sc}{B}{status_str}{RS}")

        if comp_class == "unsafe":
            print(f"\n  {R}{B}WHY THIS IS UNSAFE:{RS}")
            for note in notes:
                print(f"    {R}•{RS} {note}")
            
            risks = finding.get("damage_risks", [])
            if risks:
                print(f"\n  {R}{B}WHAT CAN BE PERMANENTLY DAMAGED:{RS}")
                for risk in risks:
                    print(f"    {R}•{RS} {risk}")
            
            mods = finding.get("required_modifications", [])
            if mods:
                print(f"\n  {W}{B}REQUIRED MODIFICATIONS:{RS}")
                for mod in mods:
                    print(f"    {W}•{RS} {mod}")
            
            print(f"\n  {Y}KACE will NOT generate a plug-and-play config for this combination.{RS}")
            print(f"  {Y}Generated config will contain safety comments and TODO markers.{RS}")

        elif comp_class == "compatible_with_adapter":
            print(f"\n  {Y}{B}WHY ADAPTER/MODIFICATION IS REQUIRED:{RS}")
            for note in notes:
                print(f"    {Y}•{RS} {note}")
                
            mods = finding.get("required_modifications", [])
            if mods:
                print(f"\n  {W}{B}REQUIRED ADAPTERS / STEPS:{RS}")
                for mod in mods:
                    print(f"    {W}•{RS} {mod}")
            
            risks = finding.get("damage_risks", [])
            if risks:
                print(f"\n  {Y}{B}POTENTIAL RISKS IF UNMODIFIED:{RS}")
                for risk in risks:
                    print(f"    {Y}•{RS} {risk}")

        else:
            for note in notes:
                print(f"    {C}•{RS} {note}")

        if rec == "disconnect":
            print(f"\n    {R}{B}{t('display.recommendation_disconnect')}{RS}")
        elif rec == "optional":
            print(f"\n    {Y}{t('display.recommendation_optional')}{RS}")

        print("")

    print(f"  {M}{t('display.web_ui_hint')}{RS}")
    print(f"  {C}{t('display.docs_hint')}{RS}")
    print(f"  {border_color}{B}{'─' * 52}{RS}")
    print("")

    if needs_confirm:
        if has_unsafe:
            ans = questionary.text(
                "Type \"I understand the risks\" to continue anyway, or press Enter to abort:",
                style=custom_style
            ).ask()
            if ans != "I understand the risks":
                return False
        else:
            ans = questionary.confirm(
                t("display.continue_prompt"),
                default=True,
                style=custom_style
            ).ask()
            if ans is None or not ans:
                return False
        print("")

    return True


def main():
    print_kace_banner("Klipper Automated Configuration Ecosystem", __version__)
    
    # ── Dashboard (bypassed in CI / auto / dev modes) ─────────
    _bypassed = os.environ.get("KACE_AUTO") == "1"
    if not _bypassed:
        # Deferred import to optimize startup performance on slow Raspberry Pi hardware
        from core.dashboard import detect_system_state, run_dashboard
        _state = detect_system_state()
        _action = run_dashboard(_state)
        if _action == "quit":
            sys.exit(0)
    
    # Interactive Wizard & Phase 1 Execution Loop
    import copy
    user_data = None
    
    while True:
        try:
            user_data = run_wizard(user_data)
        except WizardExit:
            print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
            sys.exit(0)
        except (KeyboardInterrupt, EOFError):
            print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
            sys.exit(0)
        except ImportError as e:
            print(f"\n\033[91mERROR:\033[0m {t('kace.missing_dep', error=e)}")
            print(f"\033[93m{t('kace.missing_dep_hint')}\033[0m")
            sys.exit(1)

        # ==========================================
        # PHASE 1: CONFIGURATION FETCH & DRIVER SETUP
        # ==========================================
        parsed_data = user_data.get("board_parsed")
        if not parsed_data:
            raw_cfg = fetch_raw_config(user_data['board'])
            if not raw_cfg:
                print(f"\n\033[91m[!] Board configuration could not be fetched for: '{user_data['board']}'\033[0m")
                print(f"\033[93m    This may indicate an invalid board selection or a network error.\033[0m")
                print(f"\033[93m    Please re-run KACE and select a valid board configuration.\033[0m")
                print(f"\033[2m[!] Aborting — cannot generate a configuration without board data.\033[0m")
                sys.exit(1)
            parsed_data = parse_config(raw_cfg, user_data['board'], keep_comments=True)
            user_data["board_parsed"] = parsed_data

        # ── Validation Gate 1b: BLTouch pin resolution ──────────────────────
        # When the user selected BLTouch/CR-Touch but the board has no mapped
        # pins in the database, the template would emit '^TODO'/'TODO' into
        # active config lines and trigger a GenerationError.  Catch this early
        # and ask for the pins interactively so the workflow succeeds.
        _probe_choice = user_data.get("probe", "None")
        if _probe_choice in ("BLTouch", "CR-Touch"):
            _blt = parsed_data.get("bltouch", {})
            _missing_sensor  = not _blt.get("sensor_pin")
            _missing_control = not _blt.get("control_pin")
            if _missing_sensor or _missing_control:
                print(f"\n\033[93m[!] BLTouch/CR-Touch selected but pin mapping is unknown for:\033[0m")
                print(f"\033[93m    {user_data['board']}\033[0m")
                print(f"\033[96m    Enter the pins manually below (check your board's wiring diagram).\033[0m")
                print(f"\033[2m    Example — Octopus Pro: sensor_pin=^PB7  control_pin=PB6\033[0m\n")
                if _missing_sensor:
                    _sp = questionary.text(
                        "BLTouch sensor_pin (e.g. ^PB7 or ^PC5):",
                        validate=questionary_pin_validator,
                        style=custom_style
                    ).ask()
                    if not _sp:
                        print(f"\n\033[91m[!] No sensor_pin provided — aborting.\033[0m")
                        sys.exit(1)
                    parsed_data.setdefault("bltouch", {})["sensor_pin"] = _sp.strip()
                if _missing_control:
                    _cp = questionary.text(
                        "BLTouch control_pin (e.g. PB6 or PE5):",
                        validate=questionary_pin_validator,
                        style=custom_style
                    ).ask()
                    if not _cp:
                        print(f"\n\033[91m[!] No control_pin provided — aborting.\033[0m")
                        sys.exit(1)
                    parsed_data.setdefault("bltouch", {})["control_pin"] = _cp.strip()

        break

    # ── Display Compatibility Check ───────────────────────────────────────────
    # Run before generation so users can make an informed decision about
    # their display. Non-invasive: never modifies the parsed config.
    #
    # Conditional logic:
    #   display_choice == "none"         → skip entirely (user opted out of display)
    #   display_choice starts with "recommended:" and risk_accepted → skip
    #     (user already saw board-aware recommendations in the wizard)
    #   display_choice starts with "manual:" or "override:" → run check, but
    #     the wizard already showed the full risk panel; confirm only if new findings
    #   display_choice is None (auto/CI) → run full check as before
    _display_choice      = user_data.get("display_choice")
    _display_risk_accepted = user_data.get("display_risk_accepted", False)

    _skip_display_check = (
        _display_choice == "none"
        or (
            _display_choice is not None
            and _display_choice.startswith("recommended:")
            and _display_risk_accepted
        )
    )

    if not _skip_display_check:
        _display_findings = check_display_compatibility(
            parsed_data,
            printer_filename=user_data.get('printer_profile', ''),
            board_filename=user_data.get('board', ''),
        )

        # If the user made a manual/override selection in the wizard, filter findings
        # to only show truly new issues not already covered by the wizard risk panel.
        if _display_choice and (_display_choice.startswith("manual:") or _display_choice.startswith("override:")):
            chosen_section = _display_choice.split(":", 1)[1] if ":" in _display_choice else None
            if chosen_section:
                # Suppress findings for the chosen section if risk was already accepted
                _display_findings = [
                    f for f in _display_findings
                    if not (f.get("section") == chosen_section and _display_risk_accepted)
                ]

        if _display_findings:
            _should_continue = _print_display_warning(_display_findings)
            if not _should_continue:
                print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
                sys.exit(0)

    time.sleep(0.5)
    print(f"\033[92m[*]\033[0m {t('kace.fetching_cfg_done', board=user_data['board'])}")

    # ==========================================
    # PHASE 2: FIRMWARE COMPILATION & DEPLOYMENT
    # ==========================================
    mcu = user_data.get('mcu_type')
    hint = user_data.get('mcu_hint')
    if mcu or hint == "manual":
        prompt_mcu = mcu if mcu else "manually selected board"

        # ── Validation Gate 2: Pre-compilation TODO scan ──────────────────
        # If the parsed config already has unresolved TODO pins, compilation
        # would produce a broken printer.cfg anyway. Skip the prompt entirely
        # and explain why instead of wasting the user's time on a compile
        # that is guaranteed to fail at the generation step.
        _early_todos = has_todo_pins(parsed_data)
        if _early_todos:
            print(f"\n\033[91m[!] Firmware compilation skipped.\033[0m")
            print(f"\033[93m    Board mapping incomplete — the following required pins could not be resolved:\033[0m")
            for section, key in _early_todos:
                print(f"\033[93m      • [{section}] → {key}\033[0m")
            print(f"\033[93m    Select a specific board config instead of the stock profile, or\033[0m")
            print(f"\033[93m    configure the missing pins manually in the generated printer.cfg.\033[0m")
            print(f"\033[2m[!] Skipping firmware compilation — configuration has unresolved TODO pins.\033[0m")
        else:
            # Deferred import to optimize startup performance on slow Raspberry Pi hardware
            from core.firmware_wizard import run_firmware_wizard
            run_firmware_wizard(user_data)

    generate_macros = questionary.confirm(
        f"\n{t('kace.generate_macros_prompt')}",
        default=True,
        style=custom_style
    ).ask()
    user_data["macros_generated"] = generate_macros

    # ==========================================
    # PHASE 3: CONFIGURATION GENERATION
    # ==========================================
    print(f"\033[91m[*]\033[0m {t('kace.generating_cfg')}", end="", flush=True)
    try:
        generate_config(parsed_data, user_data, include_macros=generate_macros)
    except GenerationError as gen_err:
        print(f"\r\033[91m[!]\033[0m {t('kace.generating_cfg')} FAILED")
        print(f"\n\033[91mERROR:\033[0m {gen_err}")
        if gen_err.todos:
            print("\033[93m    Unresolved TODO pins:\033[0m")
            for section, key in gen_err.todos:
                print(f"\033[93m      • {section} → {key}\033[0m")
        print("\033[93m    Resolve the missing pins and re-run KACE.\033[0m")
        sys.exit(1)
    time.sleep(0.5)
    print(f"\r\033[92m[*]\033[0m {t('kace.generating_cfg_done')}")
    
    cfg_path = os.path.expanduser('~/kace/printer.cfg')
    print(f"\n\033[92mSUCCESS:\033[0m {t('kace.cfg_success', path=cfg_path)}")

    # Print Configuration Summary before deployment
    print_summary(user_data, parsed_data)

    # ==========================================
    # PHASE 4: CONFIGURATION DEPLOYMENT
    # ==========================================
    deploy_cfg = questionary.select(
        f"\n{t('kace.deploy_cfg_prompt')}",
        choices=[
            {"name": f"✅  {t('kace.deploy_none')}",       "value": "none"},
            {"name": f"📁  {t('kace.deploy_local')}",       "value": "local"},
            {"name": f"💾  {t('kace.deploy_usb')}",         "value": "usb"},
            {"name": f"🔗  {t('kace.deploy_ssh')}",         "value": "ssh"},
            {"name": f"🌐  {t('kace.deploy_moonraker')}",   "value": "moonraker"},
        ],
        style=custom_style
    ).ask()

    if deploy_cfg == "usb":
        deploy_usb(user_data, artifact_type="config")
    elif deploy_cfg == "local":
        deploy_local(user_data, artifact_type="config")
    elif deploy_cfg == "ssh":
        user_data['host'] = questionary.text(t("kace.ssh_host_prompt"), style=custom_style).ask()
        user_data['user'] = questionary.text(t("kace.ssh_user_prompt"), default="pi", style=custom_style).ask()
        user_data['password'] = questionary.password(t("kace.ssh_pass_prompt"), style=custom_style).ask()
        user_data['dest_path'] = questionary.text(t("kace.ssh_dest_prompt"), default="~/printer_data/config/", style=custom_style).ask()
        if user_data['host'] and user_data['user'] and user_data['dest_path']:
            deploy_config(user_data)
    elif deploy_cfg == "moonraker":
        deploy_moonraker(user_data)

    sys.exit(0)

if __name__ == "__main__":
    main()
