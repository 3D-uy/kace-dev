# Guia de Simulação e Testes em Docker para o KACE

Este guia explica como compilar, executar e desenvolver o KACE dentro do ambiente isolado do **Docker Simulation Testbed**.

Como o KACE é um assistente focado em hardware para a instalação do Klipper, testá-lo diretamente em sistemas Windows de desenvolvimento normalmente é impossível porque:
1. O Windows não possui as portas de comunicação serial `/dev/serial/by-id/*`.
2. O Windows não executa serviços `systemd` do Linux (`systemctl`).
3. Você pode não ter uma Raspberry Pi física com MainsailOS ou uma impressora 3D conectada à sua rede local.

Este contêiner Docker resolve esses três problemas **simulando** múltiplos tipos de sistemas operacionais de Raspberry Pi e microcontroladores (MCU) de hardware conectados.

---

## 🛠️ Pré-requisitos

* **Docker Desktop** instalado e em execução no seu Windows hospedeiro.
* Acesso à linha de comando (PowerShell, CMD, ou Git Bash).

---

## 🚀 Como Executar a Simulação

1. Abra o PowerShell e navegue até a pasta `docker` do KACE:
   ```powershell
   cd e:\GitHub\KACE\docker
   ```

2. Construa e execute o contêiner interativo:
   ```powershell
   docker-compose run --rm kace-dev
   ```

3. Você verá imediatamente o **Menu de Simulação Docker do KACE**:
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

## 🔍 Como Funcionam os Cenários

Quando você seleciona um cenário (opções 1 a 4), o script de entrada do contêiner (`entrypoint.sh`) constrói dinamicamente um ambiente simulado dentro do contêiner antes de iniciar o KACE:

### 1. Simulação do MainsailOS
* **Pastas Simuladas**: Cria `~/klipper`, `~/moonraker` e `~/mainsail`.
* **Serviços Simulados**: Registra `klipper`, `moonraker` e `crowsnest` como ativos.
* **Hardware Simulado**: Cria um link simbólico em `/dev/serial/by-id/usb-Klipper_stm32f446xx_Octopus-v1.1-if00` representando uma placa **BigTreeTech Octopus v1.1**.
* **Servidor Moonraker Simulado**: Executa o servidor mock da REST API em segundo plano na porta `7125`.

### 2. Simulação do FluiddPI
* **Pastas Simuladas**: Cria `~/klipper`, `~/moonraker` e `~/fluidd`.
* **Serviços Simulados**: Registra `klipper` e `moonraker` como ativos.
* **Hardware Simulado**: Cria um link simbólico em `/dev/serial/by-id/usb-Klipper_rp2040_SKRPico-if00` representando uma placa **BigTreeTech SKR Pico** (RP2040).
* **Servidor Moonraker Simulado**: Executa o servidor mock da REST API na porta `7125`.

### 3. Simulação de Clean Pi (Pi Limpa)
* **Pastas Simuladas**: Nenhuma.
* **Serviços Simulados**: Nenhum.
* **Hardware Simulado**: Cria `/dev/ttyUSB0` (um nó de dispositivo serial bruto, representando uma placa-mãe de impressora conectada mas que ainda não está rodando o firmware do Klipper).
* **Servidor Moonraker Simulado**: Parado/desabilitado.

### 4. Simulação de MCU Duplo
* **Pastas Simuladas**: Cria a estrutura de pastas do MainsailOS.
* **Serviços Simulados**: Registra `klipper` e `moonraker` como ativos.
* **Hardware Simulado**: Cria as duas rotas seriais para a Octopus e a SKR Pico dentro de `/dev/serial/by-id/` para testar a detecção multichip.

---

## 📡 Testando Implantações pela REST API do Moonraker

Se você simular o **MainsailOS** ou o **FluiddPI** (Cenários 1, 2 ou 4), o KACE detectará o Klipper/Moonraker como ativos.

Durante a Fase 4 (Implantação da Configuração), você pode testar a nova **Integração com a API do Moonraker**:
1. Selecione **🌐 Deploy to Moonraker API** no menu de deploy do KACE.
2. Insira `localhost` (ou `127.0.0.1`) como host do Moonraker.
3. Insira `7125` como a porta.
4. O KACE fará uma requisição HTTP para o servidor mock rodando em segundo plano, enviará o seu `printer.cfg` gerado e pedirá para realizar o reinício.
5. Se você selecionar **Firmware Restart** ou **Service Restart**, o KACE enviará um comando POST para a API mock do Moonraker, que registrará a solicitação no console e responderá com sucesso.

Você pode verificar que o arquivo foi enviado com sucesso lendo o arquivo local:
```bash
cat ~/printer_data/config/printer.cfg
```

---

## 🛠️ Desenvolvendo o KACE dentro do Docker

Como o arquivo `docker-compose.yml` monta a raiz do seu projeto KACE como um volume:
* Qualquer modificação feita nos arquivos Python (`kace.py`, `core/*.py`, etc.) no seu Windows hospedeiro estará **ativa imediatamente** dentro do contêiner.
* Você não precisa recompilar a imagem para testar as mudanças. Apenas saia do assistente para voltar ao menu do testbed, e execute o KACE novamente!

---

## 🧪 Executando os Testes Automatizados

Para rodar a suíte completa de testes unitários e de regressão em um ambiente Linux limpo:
1. Selecione a opção `6` no menu de simulação, ou a opção `5` para abrir o terminal bash e execute:
   ```bash
   python3 tests/run_tests.py
   ```
2. Verifique se todos os 76 testes passam com sucesso.
