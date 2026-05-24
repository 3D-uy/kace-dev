# Guía de Pruebas y Simulación en Docker para KACE

Esta guía explica cómo construir, ejecutar y desarrollar KACE dentro del entorno aislado de la **Plataforma de Simulación en Docker (Docker Simulation Testbed)**.

Dado que KACE es un asistente enfocado en hardware para la instalación de Klipper, probarlo directamente en máquinas de desarrollo con Windows suele ser imposible debido a que:
1. Windows no dispone de los puertos de comunicación serie `/dev/serial/by-id/*`.
2. Windows no ejecuta servicios `systemd` de Linux (`systemctl`).
3. Es posible que no tengas una Raspberry Pi física con MainsailOS o una impresora 3D conectada a tu red local.

Este contenedor Docker soluciona estos tres problemas **simulando** varios perfiles de sistemas operativos de Raspberry Pi y chips MCU de hardware conectados.

---

## 🛠️ Requisitos Previos

* **Docker Desktop** instalado y ejecutándose en tu sistema anfitrión Windows.
* Acceso a la línea de comandos (PowerShell, CMD, o Git Bash).

---

## 🚀 Cómo Ejecutar la Simulación

1. Abre PowerShell y ve a la carpeta `docker` de KACE:
   ```powershell
   cd e:\GitHub\KACE\docker
   ```

2. Construye e inicia el contenedor interactivo:
   ```powershell
   docker-compose run --rm kace-dev
   ```

3. Verás de inmediato el **Menú de Simulación de Docker de KACE**:
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

## 🔍 Cómo Funcionan los Escenarios

Cuando seleccionas un escenario (opciones 1–4), el script de inicio del contenedor (`entrypoint.sh`) construye dinámicamente el entorno de pruebas antes de lanzar KACE:

### 1. Simulación de MainsailOS
* **Directorios Simulados**: Crea `~/klipper`, `~/moonraker` y `~/mainsail`.
* **Servicios Simulados**: Registra `klipper`, `moonraker` y `crowsnest` como activos.
* **Hardware Simulado**: Crea un enlace simbólico en `/dev/serial/by-id/usb-Klipper_stm32f446xx_Octopus-v1.1-if00` que representa una placa **BigTreeTech Octopus v1.1**.
* **Servidor Moonraker Simulado**: Lanza un servidor REST API mock en segundo plano en el puerto `7125`.

### 2. Simulación de FluiddPI
* **Directorios Simulados**: Crea `~/klipper`, `~/moonraker` y `~/fluidd`.
* **Servicios Simulados**: Registra `klipper` y `moonraker` como activos.
* **Hardware Simulado**: Crea un enlace simbólico en `/dev/serial/by-id/usb-Klipper_rp2040_SKRPico-if00` que representa una placa **BigTreeTech SKR Pico** (RP2040).
* **Servidor Moonraker Simulado**: Lanza el servidor REST API mock en el puerto `7125`.

### 3. Simulación de Clean Pi (Pi Limpia)
* **Directorios Simulados**: Ninguno.
* **Servicios Simulados**: Ninguno.
* **Hardware Simulado**: Crea `/dev/ttyUSB0` (un nodo de dispositivo serie crudo, que representa una placa de impresora conectada pero que aún no tiene el firmware Klipper instalado).
* **Servidor Moonraker Simulado**: Detenido/desactivado.

### 4. Simulación de MCU Dual
* **Directorios Simulados**: Crea la estructura de MainsailOS.
* **Servicios Simulados**: Registra `klipper` y `moonraker` como activos.
* **Hardware Simulado**: Crea las rutas serie para la Octopus y la SKR Pico dentro de `/dev/serial/by-id/` para probar la detección multichip.

---

## 📡 Probando el Despliegue con la REST API de Moonraker

Si simulas **MainsailOS** o **FluiddPI** (Escenarios 1, 2 o 4), KACE detectará que Klipper y Moonraker están activos.

Durante la Fase 4 (Despliegue de Configuración), puedes probar la integración con **Moonraker API**:
1. Selecciona **🌐 Deploy to Moonraker API** en el menú de despliegue de KACE.
2. Ingresa `localhost` (o `127.0.0.1`) como host de Moonraker.
3. Ingresa `7125` como puerto.
4. KACE hará una petición HTTP al servidor de simulación en segundo plano, subirá tu `printer.cfg` generado y te preguntará si deseas reiniciar la impresora.
5. Si seleccionas **Firmware Restart** o **Service Restart**, KACE enviará un comando POST a la API mock de Moonraker, la cual registrará la llamada en consola y devolverá una respuesta de éxito.

Puedes verificar que el archivo se subió correctamente ejecutando:
```bash
cat ~/printer_data/config/printer.cfg
```

---

## 🛠️ Desarrollando KACE dentro de Docker

Debido a que `docker-compose.yml` monta la raíz del proyecto KACE como un volumen:
* Cualquier cambio que hagas en los archivos Python (`kace.py`, `core/*.py`, etc.) en tu máquina anfitriona Windows estará **activo de inmediato** dentro del contenedor.
* No necesitas reconstruir la imagen de Docker para probar tus modificaciones de código. Solo sal del asistente interactivo para volver al menú de simulación y vuelve a iniciar KACE.

---

## 🧪 Ejecutar Pruebas Automatizadas

Para ejecutar toda la suite de pruebas unitarias y de regresión en un entorno Linux limpio:
1. Selecciona la opción `6` en el menú de simulación, o selecciona la opción `5` para abrir una terminal de bash y ejecuta:
   ```bash
   python3 tests/run_tests.py
   ```
2. Verifica que las 76 pruebas pasen de manera exitosa.
