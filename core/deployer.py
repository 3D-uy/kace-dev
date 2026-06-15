import os
import platform
import posixpath
import shutil
import subprocess
import sys

# paramiko is an optional dependency — only needed for SSH deployment.
# It is imported lazily here so users who never use SSH deploy do not
# pay the install cost. On first SSH use, KACE will install it
# automatically via pip if it is not already present.


def _require_paramiko():
    """Return the paramiko module, installing it on-demand if needed."""
    try:
        import paramiko  # noqa: PLC0415
        return paramiko
    except ImportError:
        print("\n\033[96m[SSH Deployment]\033[0m")
        print("\033[93m[*] SSH support requires the 'paramiko' library.\033[0m")
        print("\033[93m[*] Downloading and installing (this may take a moment)...\033[0m")
        try:
            # Locate requirements-ssh.txt relative to this file to enforce hash verification
            current_dir = os.path.dirname(os.path.abspath(__file__))
            req_path = os.path.abspath(os.path.join(current_dir, "..", "requirements-ssh.txt"))
            pip_cmd = [sys.executable, "-m", "pip", "install", "-r", req_path, "--require-hashes"]
            if platform.system() != "Windows":
                pip_cmd.append("--break-system-packages")
            subprocess.check_output(
                pip_cmd,
                stderr=subprocess.STDOUT
            )
            import paramiko  # noqa: PLC0415
            print("\033[92m[OK] paramiko installed successfully.\033[0m\n")
            return paramiko
        except subprocess.CalledProcessError as e:
            output = e.output.decode('utf-8', errors='ignore') if e.output else ""
            print(f"\n\033[91m[!] ERROR: Failed to install paramiko automatically.\033[0m")
            if "SSL" in output or "certificate" in output:
                print("\033[93m    System time might be out of sync, causing SSL certificate validation to fail.\033[0m")
            elif "NewConnectionError" in output or "Network is unreachable" in output:
                print("\033[93m    Network unreachable. Please check your internet connection.\033[0m")
            else:
                print(f"\033[93m    Pip error output:\n    {output.strip()}\033[0m")
                
            print("\n\033[96mTo use SSH deployment, please install it manually:\033[0m")
            print("    pip3 install paramiko==3.4.0 --break-system-packages")
            print("\033[96mContinuing without SSH support...\033[0m\n")
            return None
        except Exception as e:
            print(f"\n\033[91m[!] Unexpected error installing paramiko: {e}\033[0m")
            print("\033[96mContinuing without SSH support...\033[0m\n")
            return None


class _InteractiveHostKeyPolicy:
    """Paramiko MissingHostKeyPolicy that asks the user before connecting.

    WarningPolicy prints a warning and proceeds silently — the user has no
    chance to abort. This policy shows the key fingerprint and requires an
    explicit yes before the connection is made.

    On acceptance the key is saved to ~/.ssh/known_hosts so the prompt
    only appears once per host (standard SSH behaviour).
    """

    def missing_host_key(self, client, hostname, key):
        import questionary
        from core.style import custom_style

        algo = key.get_name()
        # Format fingerprint as colon-separated hex pairs (e.g. ab:cd:ef:...)
        raw = key.get_fingerprint()
        fingerprint = ':'.join(f'{b:02x}' for b in raw)

        print(f"\n\033[93m[!] Unknown host key for {hostname}\033[0m")
        print(f"    Algorithm  : {algo}")
        print(f"    Fingerprint: {fingerprint}")
        print(f"\033[93m    Verify this fingerprint matches your Pi before continuing.\033[0m\n")

        trust = questionary.confirm(
            f"Trust and connect to {hostname}?",
            default=False,
            style=custom_style,
        ).ask()

        if not trust:
            # Raising SSHException aborts the connection cleanly
            paramiko = _require_paramiko()
            raise paramiko.SSHException(
                f"Connection to {hostname} rejected — unknown host key not trusted."
            )

        # Save to known_hosts so the prompt doesn't repeat next time
        client.get_host_keys().add(hostname, algo, key)
        try:
            known_hosts = os.path.expanduser("~/.ssh/known_hosts")
            client.save_host_keys(known_hosts)
        except Exception:
            pass  # Non-fatal — key is still trusted for this session


def deploy_config(user_data):
    """Deploys the generated printer.cfg to the Klipper host via SSH/SCP."""
    # Wipes password from user_data immediately to reduce the credential exposure window
    password = user_data.pop('password', '')
    paramiko = _require_paramiko()
    if paramiko is None:
        return  # error already printed by _require_paramiko

    # BUG-007: Verify the config file exists locally before attempting upload.
    # sftp.put() raises a cryptic FileNotFoundError that the broad except below
    # would swallow without telling the user the real cause.
    cfg_path = os.path.expanduser('~/kace/printer.cfg')
    if not os.path.isfile(cfg_path):
        print(f"\033[91m[!] Deployment aborted: printer.cfg not found at {cfg_path}\033[0m")
        print("\033[93m    Run 'Generate new config' first to create the file.\033[0m")
        return

    try:
        ssh = paramiko.SSHClient()
        # UNSAFE-002: WarningPolicy warns the user on unknown host keys instead
        # of silently accepting them (AutoAddPolicy is MITM-vulnerable).
        # Known hosts are still loaded from ~/.ssh/known_hosts for verification.
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(_InteractiveHostKeyPolicy())

        print(f"Connecting to {user_data['host']}...")
        ssh.connect(
            user_data['host'],
            username=user_data['user'],
            password=password
        )

        sftp = ssh.open_sftp()

        # Expand user path (e.g., ~) if necessary
        dest = user_data['dest_path']
        if dest.startswith('~/'):
            # Simple expansion for common Klipper setups
            dest = dest.replace('~/', f"/home/{user_data['user']}/")

        # Ensure dest is a full file path — if it ends with '/', it's a directory
        if dest.endswith('/') or not dest.endswith('.cfg'):
            dest_file = posixpath.join(dest.rstrip('/'), 'printer.cfg')
        else:
            dest_file = dest
        print(f"Uploading printer.cfg to {dest_file}...")
        sftp.put(cfg_path, dest_file)

        # Upload macros.cfg if it exists
        macros_path = os.path.expanduser('~/kace/macros.cfg')
        if os.path.exists(macros_path):
            dest_macros = posixpath.join(posixpath.dirname(dest_file), 'macros.cfg')
            print(f"Uploading macros.cfg to {dest_macros}...")
            sftp.put(macros_path, dest_macros)

        sftp.close()
        ssh.close()
    except paramiko.AuthenticationException:
        print("\033[91mDeployment failed: Authentication error — check username and password.\033[0m")
    except TimeoutError:
        print("\033[91mDeployment failed: Connection timed out — is the Pi powered on and reachable?\033[0m")
    except OSError as e:
        print(f"\033[91mDeployment failed: Network error — {e}\033[0m")
    except Exception as e:
        print(f"\033[91mDeployment failed: {e}\033[0m")


def deploy_usb(user_data, artifact_type="all"):
    """Deploys the generated artifact(s) to a USB/SD card."""
    try:
        import questionary
        from core.style import custom_style
        
        name_prompt = "Configuration (printer.cfg)" if artifact_type == "config" else \
                      "Firmware (klipper.bin/.uf2)" if artifact_type == "firmware" else "Configuration and Firmware"
                      
        is_non_windows = platform.system() != "Windows"
        is_docker = os.path.exists('/.dockerenv') or os.environ.get('KACE_DOCKER') == '1'
        
        while True:
            dest = questionary.text(
                f"Enter USB/SD Card mount path for {name_prompt} (e.g. D:\\ or /media/usb):",
                style=custom_style
            ).ask()
            
            if not dest:
                return
                
            if is_non_windows and (dest.strip().startswith(tuple(f"{c}:" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")) or '\\' in dest):
                if is_docker:
                    print("\033[91m[Error] Windows drive paths (containing '\\' or drive letters) are not accessible inside Docker.\033[0m")
                    print("\033[93m        To write to your Windows machine, please use /workspace (e.g., /workspace/outputs).\033[0m\n")
                else:
                    print("\033[91m[Error] Windows drive paths (containing '\\' or drive letters) are not supported on non-Windows platforms.\033[0m\n")
                continue
            break
        
        if not dest or not os.path.isdir(dest):
            print(f"\033[91mDeployment failed: Invalid path or directory does not exist: {dest}\033[0m")
            return
            
        success = False
        
        if artifact_type in ["config", "all"]:
            cfg_path = os.path.expanduser('~/kace/printer.cfg')
            if os.path.exists(cfg_path):
                print(f"Copying printer.cfg to {dest}...")
                shutil.copy2(cfg_path, os.path.join(dest, 'printer.cfg'))
                success = True
            
            # Copy macros.cfg if it exists
            macros_path = os.path.expanduser('~/kace/macros.cfg')
            if os.path.exists(macros_path):
                print(f"Copying macros.cfg to {dest}...")
                shutil.copy2(macros_path, os.path.join(dest, 'macros.cfg'))
        
        if artifact_type in ["firmware", "all"]:
            fw_path = user_data.get("firmware_path")
            if fw_path and os.path.exists(os.path.expanduser(fw_path)):
                firmware_bin = os.path.expanduser(fw_path)
                ext = os.path.basename(firmware_bin)
                print(f"Copying firmware {ext} to {dest}...")
                shutil.copy2(firmware_bin, os.path.join(dest, ext))
                success = True
            else:
                for ext in ['klipper.bin', 'klipper.uf2', 'klipper.elf.hex']:
                    firmware_bin = os.path.expanduser(f'~/kace/{ext}')
                    if os.path.exists(firmware_bin):
                        print(f"Copying firmware {ext} to {dest}...")
                        shutil.copy2(firmware_bin, os.path.join(dest, ext))
                        success = True
                    
        if success:
            print("\033[92mUSB Deployment Successful!\033[0m")
        else:
            print("\033[93mNo requested artifacts found to copy.\033[0m")
            
    except Exception as e:
        print(f"\033[91mDeployment failed: {e}\033[0m")

def deploy_local(user_data, artifact_type="all"):
    """Copies the requested artifact(s) to a local folder on the PC."""
    try:
        import questionary
        from core.style import custom_style
        
        name_prompt = "Configuration (printer.cfg)" if artifact_type == "config" else \
                      "Firmware (klipper.bin/.uf2)" if artifact_type == "firmware" else "Configuration and Firmware"
                      
        is_non_windows = platform.system() != "Windows"
        is_docker = os.path.exists('/.dockerenv') or os.environ.get('KACE_DOCKER') == '1'
        
        while True:
            dest = questionary.text(
                f"Enter local destination folder path for {name_prompt} (e.g. C:\\3DPrinter or ~/Documents):",
                style=custom_style
            ).ask()
            
            if not dest:
                return

            if is_non_windows and (dest.strip().startswith(tuple(f"{c}:" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")) or '\\' in dest):
                if is_docker:
                    print("\033[91m[Error] Windows drive paths (containing '\\' or drive letters) are not accessible inside Docker.\033[0m")
                    print("\033[93m        To write to your Windows machine, please use /workspace (e.g., /workspace/outputs).\033[0m\n")
                else:
                    print("\033[91m[Error] Windows drive paths (containing '\\' or drive letters) are not supported on non-Windows platforms.\033[0m\n")
                continue
            break

        dest = os.path.expanduser(dest)
        
        if not os.path.exists(dest):
            os.makedirs(dest, exist_ok=True)
            
        success = False
        
        if artifact_type in ["config", "all"]:
            cfg_path = os.path.expanduser('~/kace/printer.cfg')
            if os.path.exists(cfg_path):
                print(f"Copying printer.cfg to {dest}...")
                shutil.copy2(cfg_path, os.path.join(dest, 'printer.cfg'))
                success = True
            
            # Copy macros.cfg if it exists
            macros_path = os.path.expanduser('~/kace/macros.cfg')
            if os.path.exists(macros_path):
                print(f"Copying macros.cfg to {dest}...")
                shutil.copy2(macros_path, os.path.join(dest, 'macros.cfg'))
        
        if artifact_type in ["firmware", "all"]:
            fw_path = user_data.get("firmware_path")
            if fw_path and os.path.exists(os.path.expanduser(fw_path)):
                firmware_bin = os.path.expanduser(fw_path)
                ext = os.path.basename(firmware_bin)
                print(f"Copying firmware {ext} to {dest}...")
                shutil.copy2(firmware_bin, os.path.join(dest, ext))
                success = True
            else:
                for ext in ['klipper.bin', 'klipper.uf2', 'klipper.elf.hex']:
                    firmware_bin = os.path.expanduser(f'~/kace/{ext}')
                    if os.path.exists(firmware_bin):
                        print(f"Copying firmware {ext} to {dest}...")
                        shutil.copy2(firmware_bin, os.path.join(dest, ext))
                        success = True
                    
        if success:
            print(f"\033[92mSuccessfully saved to {dest}!\033[0m")
        else:
            print("\033[93mNo requested artifacts found to copy.\033[0m")
            
    except Exception as e:
        print(f"\033[91mSave failed: {e}\033[0m")

def deploy_avrdude(user_data, artifact_path, mcu_type):
    """Deploys firmware via USB using avrdude (for AVR MCUs)."""
    import questionary
    from core.style import custom_style

    if not shutil.which("avrdude"):
        print("\n\033[91mERROR:\033[0m 'avrdude' is not installed or not in PATH.")
        print("\033[93mPlease install it (e.g., 'sudo apt install avrdude') and try again.\033[0m")
        return

    # Try to derive the avrdude mcu part from mcu_type (e.g. atmega1284p -> atmega1284p)
    # Most times user_data['mcu_type'] is already correct, but just in case
    mcu_part = mcu_type.lower() if mcu_type else "atmega2560"
    
    default_port = user_data.get('mcu_path')
    if not default_port or default_port == "TODO" or "TODO" in default_port:
        default_port = "/dev/ttyUSB0"

    print("\n\033[96m>>> AVR Flashing via avrdude\033[0m")
    port = questionary.text(
        "Enter the serial port for flashing:",
        default=default_port,
        style=custom_style
    ).ask()

    if not port:
        print("\033[93mFlashing cancelled.\033[0m")
        return

    cmd = [
        "avrdude", 
        "-p", mcu_part, 
        "-c", "arduino", 
        "-P", port, 
        "-b", "115200", 
        "-U", f"flash:w:{artifact_path}:i"
    ]
    
    cmd_str = " ".join(cmd)
    print(f"\n\033[93mGenerated Command:\033[0m {cmd_str}")
    
    confirm = questionary.confirm("Execute this command now?").ask()
    if confirm:
        print("\n\033[96m>>> Running avrdude...\033[0m")
        try:
            subprocess.run(cmd, check=True)
            print("\n\033[92mSUCCESS:\033[0m Firmware flashed successfully!")
        except subprocess.CalledProcessError as e:
            print(f"\n\033[91mERROR:\033[0m avrdude failed with return code {e.returncode}.")
    else:
        print("\n\033[93mCommand execution cancelled. You can run it manually.\033[0m")


def deploy_moonraker(user_data):
    """Deploy printer.cfg to a Klipper host via the Moonraker REST API.

    Workflow:
      1. Prompt for Moonraker host, port, and optional API key.
      2. Probe reachability via GET /server/info.
      3. Upload printer.cfg via POST /server/files/upload.
      4. Optionally trigger FIRMWARE_RESTART or service restart.
      5. On failure, offer to fall back to SSH deployment.
    """
    import questionary
    from core.style import custom_style
    from core.translations import t
    from core.moonraker import (
        DEFAULT_PORT,
        check_moonraker,
        upload_printer_cfg,
        restart_firmware,
        restart_klipper_service,
    )

    # ── Step 1: Gather connection details ─────────────────────────
    host = questionary.text(
        t("moonraker.host_prompt"),
        default=user_data.get("moonraker_host", ""),
        style=custom_style,
    ).ask()

    if not host:
        print("\033[93mMoonraker deployment cancelled.\033[0m")
        return

    port_str = questionary.text(
        t("moonraker.port_prompt"),
        default=str(user_data.get("moonraker_port", DEFAULT_PORT)),
        style=custom_style,
    ).ask()

    try:
        port = int(port_str) if port_str else DEFAULT_PORT
    except ValueError:
        port = DEFAULT_PORT

    api_key = questionary.text(
        t("moonraker.api_key_prompt"),
        default="",
        style=custom_style,
    ).ask() or ""

    # Warn if using plain HTTP with an API key
    if api_key and host.strip().lower().startswith("http://"):
        warning_ok = questionary.confirm(
            t("moonraker.http_warning"),
            default=False,
            style=custom_style,
        ).ask()
        if warning_ok is None or not warning_ok:
            print(f"\n\033[91m[!] {t('moonraker.http_warning_cancelled')}\033[0m")
            return

    # Persist for potential SSH fallback later
    user_data["moonraker_host"] = host
    user_data["moonraker_port"] = port

    # ── Step 2: Probe reachability ────────────────────────────────
    print(f"\n\033[96m[*]\033[0m {t('moonraker.connecting', host=host, port=port)}")
    ok, info = check_moonraker(host, port, api_key=api_key)

    if not ok:
        print(f"\033[91m[!] {t('moonraker.unreachable', host=host, port=port, error=info)}\033[0m")
        # Offer SSH fallback
        fallback = questionary.confirm(
            t("moonraker.fallback_ssh"),
            default=False,
            style=custom_style,
        ).ask()
        if fallback:
            user_data['host']      = host
            ssh_user = questionary.text(t("kace.ssh_user_prompt"), default="pi", style=custom_style).ask()
            ssh_pass = questionary.password(t("kace.ssh_pass_prompt"), style=custom_style).ask()
            ssh_dest = questionary.text(t("kace.ssh_dest_prompt"), default="~/printer_data/config/", style=custom_style).ask()
            if user_data['host'] and ssh_user and ssh_dest:
                user_data['user']      = ssh_user
                user_data['dest_path'] = ssh_dest
                user_data['password']  = ssh_pass   # deploy_config pops this immediately
                deploy_config(user_data)
            # ssh_pass goes out of scope here whether deploy ran or not
        return

    print(f"\033[92m[OK] {t('moonraker.connected', version=info)}\033[0m")

    # ── Step 3: Upload printer.cfg & macros.cfg ────────────────────────────────
    print(f"\033[96m[*]\033[0m {t('moonraker.uploading')}")
    cfg_path = os.path.expanduser("~/kace/printer.cfg")
    ok, result = upload_printer_cfg(host, port, cfg_path, api_key=api_key)

    if not ok:
        print(f"\033[91m[!] {t('moonraker.upload_fail', error=result)}\033[0m")
        return

    # Upload macros.cfg if it exists
    macros_path = os.path.expanduser("~/kace/macros.cfg")
    if os.path.exists(macros_path):
        print(f"\033[96m[*]\033[0m Uploading macros.cfg...")
        ok_m, res_m = upload_printer_cfg(host, port, macros_path, api_key=api_key)
        if not ok_m:
            print(f"\033[91m[!] Failed to upload macros.cfg: {res_m}\033[0m")

    print(f"\033[92m[OK] {t('moonraker.upload_ok')}\033[0m")

    # ── Step 4: Restart prompt ────────────────────────────────────
    restart_choice = questionary.select(
        t("moonraker.restart_prompt"),
        choices=[
            {"name": t("moonraker.restart_firmware"), "value": "firmware"},
            {"name": t("moonraker.restart_service"),  "value": "service"},
            {"name": t("moonraker.restart_skip"),     "value": "skip"},
        ],
        style=custom_style,
    ).ask()

    if restart_choice == "firmware":
        ok, msg = restart_firmware(host, port, api_key=api_key)
    elif restart_choice == "service":
        ok, msg = restart_klipper_service(host, port, api_key=api_key)
    else:
        return   # user skipped

    if ok:
        print(f"\033[92m[OK] {t('moonraker.restart_ok')}\033[0m")
    else:
        print(f"\033[91m[!] {t('moonraker.restart_fail', error=msg)}\033[0m")
