import os
import time
import shutil
import subprocess
from .derivation import derive_config
from .firmware_generator import generate_firmware_config
from .validator import validate_config
from core.translations import t
from core.exceptions import DerivationAmbiguityError

def build_firmware_orchestrator(mcu_path=None, derived_mcu=None, hint=None, klipper_path="~/klipper", output_dir="~/kace", config_dict=None):
    """
    Orchestrates the firmware derivation, generation, validation, and build process.
    Runs headlessly without questionary prompts.
    """
    klipper_path = os.path.expanduser(klipper_path)
    output_dir = os.path.expanduser(output_dir)

    # 1. Derive Configuration if not provided
    if config_dict is None:
        try:
            config_dict = derive_config(derived_mcu, hint)
        except Exception as e:
            return {"status": "error", "message": t("builder.derivation_failed", error=str(e))}

    # Clean stale build binaries in the out path first to prevent old files from being copied
    out_path = os.path.join(klipper_path, "out")
    expected_outputs = ["klipper.bin", "klipper.uf2", "klipper.elf.hex"]
    if os.path.exists(out_path):
        for binary in expected_outputs:
            p = os.path.join(out_path, binary)
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    # Record the build start time
    build_start_time = time.time()
        
    # 2. Generate minimal .config
    success, msg = generate_firmware_config(config_dict, klipper_path)
    if not success:
         return {"status": "error", "message": msg}

    try:
        # 3. Resolve full configuration with olddefconfig
        subprocess.run(
            ["make", "olddefconfig"],
            cwd=klipper_path,
            check=True,
            capture_output=True,
            text=True
        )
        
        # 4. Post-olddefconfig Validation
        val_success, val_msg = validate_config(klipper_path)
        if not val_success:
             return {"status": "error", "message": val_msg}
        
        # 5. Clean and Compile
        subprocess.run(
            ["make", "clean"],
            cwd=klipper_path,
            check=True,
            capture_output=True,
            text=True
        )
        
        build_cmd = ["make"]
        try:
            nproc = subprocess.check_output(["nproc"]).decode().strip()
            build_cmd.append(f"-j{nproc}")
        except Exception:
            pass # Fallback if nproc is not available

        subprocess.run(
            build_cmd,
            cwd=klipper_path,
            check=True,
            capture_output=True,
            text=True
        )
            
        # 6. Locate output artifact, verify its timestamp is fresh, and copy
        os.makedirs(output_dir, exist_ok=True)
            
        # Determine the expected output artifact based on the CONFIG_MCU architecture
        # We try to read CONFIG_MCU from the generated .config file first, falling back to config_dict
        mcu_arch = ""
        config_path = os.path.expanduser(os.path.join(klipper_path, ".config"))
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("CONFIG_MCU="):
                            mcu_arch = line.split("=", 1)[1].strip().replace('"', '')
                            break
            except Exception:
                pass
        
        if not mcu_arch and config_dict:
            mcu_arch = config_dict.get("CONFIG_MCU", "").replace('"', '').strip()

        # If the architecture is unrecognized or missing, fall back to the heuristic sequential scan
        if mcu_arch == "avr":
            target_binaries = ["klipper.elf.hex"]
        elif mcu_arch == "rp2040":
            target_binaries = ["klipper.uf2"]
        elif mcu_arch in ("stm32", "lpc176x", "esp32"):
            target_binaries = ["klipper.bin"]
        else:
            target_binaries = expected_outputs

        for binary in target_binaries:
            p = os.path.join(out_path, binary)
            if os.path.exists(p):
                # Check modification time to guarantee it was compiled during this run
                # 2-second buffer for file system time resolution tolerances
                if os.path.getmtime(p) >= (build_start_time - 2.0):
                    dest = os.path.join(output_dir, binary)
                    shutil.copy2(p, dest)
                    return {
                        "status": "success",
                        "mcu": derived_mcu,
                        "firmware": binary,
                        "path": dest
                    }
                
        return {"status": "error", "message": t("builder.no_binary")}
        
    except subprocess.CalledProcessError as e:
         return {"status": "error", "message": t("builder.make_error", code=e.returncode, error=e.stderr)}
    except FileNotFoundError:
         return {"status": "error", "message": t("builder.make_not_found")}
    except Exception as e:
         return {"status": "error", "message": t("builder.unexpected_error", error=str(e))}
