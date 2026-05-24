# KACE Docker Simulation & Testing Guide

This guide explains how to build, run, and develop KACE inside the isolated **Docker Simulation Testbed**.

Since KACE is a hardware-focused Klipper installation wizard, testing it directly on Windows development machines is normally impossible because:
1. Windows does not have `/dev/serial/by-id/*` serial ports.
2. Windows does not run Linux `systemd` services (`systemctl`).
3. You may not have a physical MainsailOS Raspberry Pi or 3D printer connected to your local network.

This Docker container solves all three problems by **simulating** multiple types of Raspberry Pi operating systems and connected hardware MCU chips.

---

## 🛠️ Prerequisites

* **Docker Desktop** installed and running on your Windows host.
* Command line access (PowerShell, CMD, or Git Bash).

---

## 🚀 How to Run the Simulation

1. Open PowerShell and navigate to your `docker` folder:
   ```powershell
   cd e:\GitHub\KACE\docker
   ```

2. Build and run the interactive container:
   ```powershell
   docker-compose run --rm kace-dev
   ```

3. You will immediately see the **KACE Docker Simulation Menu**:
   ```
   ==============================================
     ⚙️  KACE DOCKER SIMULATION TESTBED MENU
   ==============================================
   Select a Raspberry Pi environment to simulate:
    1) MainsailOS (Klipper + Moonraker + Mainsail + BTT Octopus v1.1)
    2) FluiddPI (Klipper + Moonraker + Fluidd + SKR Pico RP2040)
    3) Clean Pi OS (No Klipper/Moonraker, raw board at /dev/ttyUSB0)
    4) Dual MCU Setup (Klipper + Moonraker + Octopus & SKR Pico)
    5) Drop to Interactive Bash Shell
    6) Run KACE Automated Test Suite (run_tests.py)
    7) Exit
   ==============================================
   Enter choice [1-7]: 
   ```

---

## 🔍 How Scenarios Work

When you select a scenario (options 1–4), the container's entrypoint script (`entrypoint.sh`) dynamically builds a mock environment inside the container before starting KACE:

### 1. MainsailOS Simulation
* **Mocked Directories**: Creates `~/klipper`, `~/moonraker`, and `~/mainsail`.
* **Mocked Services**: Registers `klipper`, `moonraker`, and `crowsnest` as active.
* **Mocked Hardware**: Creates a persistent symlink at `/dev/serial/by-id/usb-Klipper_stm32f446xx_Octopus-v1.1-if00` representing a **BigTreeTech Octopus v1.1** board.
* **Mocked Moonraker Server**: Launches the lightweight mock REST API server in the background on port `7125`.

### 2. FluiddPI Simulation
* **Mocked Directories**: Creates `~/klipper`, `~/moonraker`, and `~/fluidd`.
* **Mocked Services**: Registers `klipper` and `moonraker` as active.
* **Mocked Hardware**: Creates a symlink at `/dev/serial/by-id/usb-Klipper_rp2040_SKRPico-if00` representing a **BigTreeTech SKR Pico** (RP2040).
* **Mocked Moonraker Server**: Launches the mock REST API server on port `7125`.

### 3. Clean Pi Simulation
* **Mocked Directories**: None.
* **Mocked Services**: None.
* **Mocked Hardware**: Creates `/dev/ttyUSB0` (a raw serial device node, representing a printer motherboard connected but not yet flashed with Klipper firmware).
* **Mocked Moonraker Server**: Stopped/disabled.

### 4. Dual MCU Setup
* **Mocked Directories**: Creates MainsailOS directory layout.
* **Mocked Services**: Registers `klipper` and `moonraker` as active.
* **Mocked Hardware**: Creates both the Octopus and SKR Pico serial paths inside `/dev/serial/by-id/` to test multi-board detection.

---

## 📡 Testing Moonraker REST API Deployments

If you simulate **MainsailOS** or **FluiddPI** (Scenarios 1, 2, or 4), KACE will start and detect Klipper/Moonraker as active. 

During Phase 4 (Configuration Deployment), you can test KACE's new **Moonraker API Integration**:
1. Select **🌐 Deploy to Moonraker API** from the KACE deployment menu.
2. Enter `localhost` (or `127.0.0.1`) as the Moonraker host.
3. Enter `7125` as the port.
4. KACE will perform an HTTP request to the background mock server, upload your generated `printer.cfg`, and prompt you to issue a restart.
5. If you select **Firmware Restart** or **Service Restart**, KACE will send a POST command to the mock Moonraker API, which logs the request and returns success.

You can verify the file was uploaded by checking:
```bash
cat ~/printer_data/config/printer.cfg
```

---

## 🛠️ Developing KACE Inside Docker

Because `docker-compose.yml` mounts the root of your KACE project as a volume:
* Any edits you make to Python files (`kace.py`, `core/*.py`, etc.) on your Windows host are **immediately active** inside the container.
* You do not need to rebuild the container to test code edits. Just exit the wizard to return to the simulation menu, and run KACE again!

---

## 🧪 Running Automated Tests

To run the full suite of unit and regression tests in a clean Linux environment:
1. Select option `6` from the simulation menu, or select option `5` to drop to bash and run:
   ```bash
   python3 tests/run_tests.py
   ```
2. Verify all tests pass successfully.
