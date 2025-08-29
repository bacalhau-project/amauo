#!/bin/bash
# additional_commands.sh - Additional deployment commands for sensor setup
# This script is executed by deploy_services.py after the main deployment

set -e

echo "[$(date)] Starting additional commands for sensor setup"

# Install sensor service
if [ -f /opt/uploaded_files/scripts/sensor.service ]; then
    echo "[$(date)] Installing sensor.service"
    sudo cp /opt/uploaded_files/scripts/sensor.service /etc/systemd/system/
    sudo chmod 644 /etc/systemd/system/sensor.service

    # Reload systemd and enable the service
    sudo systemctl daemon-reload
    sudo systemctl enable sensor.service
    echo "[$(date)] Sensor service enabled"
else
    echo "[$(date)] WARNING: sensor.service not found in uploaded files"
fi

# Create sensor directories if they don't exist
echo "[$(date)] Creating sensor directories"
sudo mkdir -p /opt/sensor/{config,data,logs,exports}
sudo chown -R ubuntu:ubuntu /opt/sensor

# Copy sensor config if it exists
if [ -f /opt/uploaded_files/config/sensor-config.yaml ]; then
    echo "[$(date)] Copying sensor configuration"
    sudo cp /opt/uploaded_files/config/sensor-config.yaml /opt/sensor/config/
    sudo chown ubuntu:ubuntu /opt/sensor/config/sensor-config.yaml
fi

# Generate node identity if script exists
if [ -f /opt/uploaded_files/scripts/generate_node_identity.py ]; then
    if [ ! -f /opt/sensor/config/node_identity.json ]; then
        echo "[$(date)] Generating node identity"
        cd /opt/uploaded_files/scripts
        /usr/bin/uv run generate_node_identity.py
    else
        echo "[$(date)] Node identity already exists"
    fi
fi

# Enable and start sensor service
if [ -f /etc/systemd/system/sensor.service ]; then
    echo "[$(date)] Enabling and starting sensor service"
    sudo systemctl enable sensor.service
    sudo systemctl start sensor.service

    # Wait a moment and check if it started successfully
    sleep 5
    if systemctl is-active sensor.service >/dev/null 2>&1; then
        echo "[$(date)] ✅ Sensor service is running"
    else
        echo "[$(date)] ⚠️  Sensor service failed to start"
        sudo systemctl status sensor.service --no-pager -l
    fi
else
    echo "[$(date)] WARNING: sensor.service file not found"
fi

# Verify sensor directories and permissions
echo "[$(date)] Verifying sensor directory structure"
for dir in /opt/sensor/{config,data,logs,exports}; do
    if [ -d "$dir" ]; then
        echo "[$(date)] ✓ Directory exists: $dir ($(ls -la $dir | head -1 | awk '{print $1, $3, $4}'))"
    else
        echo "[$(date)] ✗ Missing directory: $dir"
    fi
done

# Show sensor data generation status
echo "[$(date)] Sensor data will be generated to /opt/sensor/data"
echo "[$(date)] Job outputs should be written to /opt/sensor/exports"

echo "[$(date)] Additional sensor commands completed"
