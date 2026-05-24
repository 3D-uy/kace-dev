# Dockerfile — KACE Simulation & Development Container
FROM python:3.11-slim-bookworm

# Install required system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Set up workspace
WORKDIR /workspace

# Pre-install python package requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir paramiko==3.4.0

# Set up mock systemctl to intercept systemd service checks in KACE dashboard
COPY docker/mock_systemctl /usr/local/bin/systemctl
RUN chmod +x /usr/local/bin/systemctl

# Expose Moonraker API mock port
EXPOSE 7125

# Run the entrypoint script
CMD ["/bin/bash", "/workspace/docker/entrypoint.sh"]
