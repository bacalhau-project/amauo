#!/usr/bin/env python3
"""
Simplified deployment script for instance-files mirroring approach.
Most deployment logic is now handled by setup.sh during cloud-init.
"""

import subprocess
import time


def log(message):
    """Log with timestamp"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")
    # Write to deployment log
    try:
        with open("/opt/deployment.log", "a") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def run_command(cmd):
    """Run shell command and return result"""
    log(f"Running: {cmd}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.stdout:
            log(f"Output: {result.stdout.strip()}")
        return result
    except Exception as e:
        log(f"Error running command: {e}")
        return None


def main():
    """Main deployment routine - simplified for instance-files mirroring"""
    log("=== Amauo Deploy Services - Simplified ===")
    log("Using instance-files direct mirroring approach")

    # Check that the instance-files structure is properly deployed
    expected_files = [
        "/etc/bacalhau/orchestrator_endpoint",
        "/etc/bacalhau/orchestrator_token",
        "/etc/bacalhau/bacalhau-config-template.yaml",
        "/opt/compose/docker-compose-bacalhau.yaml",
        "/etc/systemd/system/bacalhau.service",
        "/etc/systemd/system/sensor.service",
    ]

    missing_files = []
    for file in expected_files:
        result = run_command(f"test -f {file}")
        if result and result.returncode != 0:
            missing_files.append(file)

    if missing_files:
        log(f"WARNING: Missing files: {missing_files}")
        log("Files should be deployed via instance-files directory structure")
    else:
        log("SUCCESS: All expected files are present")

    # Check if setup.sh has run (it creates this marker)
    setup_marker = "/opt/amauo_setup_complete"
    result = run_command(f"test -f {setup_marker}")

    if result and result.returncode == 0:
        log("SUCCESS: setup.sh has completed - deployment ready")
    else:
        log("INFO: setup.sh not yet complete - will run via cloud-init")

    log("=== Deploy Services Complete ===")


if __name__ == "__main__":
    main()
