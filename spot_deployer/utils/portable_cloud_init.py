#!/usr/bin/env python3
"""Portable cloud-init generator that creates cloud-init from DeploymentConfig."""

import logging
import textwrap
from pathlib import Path
from typing import Optional

from spot_deployer.core.deployment import DeploymentConfig

logger = logging.getLogger(__name__)


class PortableCloudInitGenerator:
    """Generates cloud-init configuration from DeploymentConfig."""

    def __init__(self, deployment_config: DeploymentConfig):
        """Initialize generator with deployment configuration.

        Args:
            deployment_config: DeploymentConfig object with deployment specs
        """
        self.config = deployment_config

    def generate(self) -> str:
        """Generate complete cloud-init YAML configuration.

        Returns:
            String containing the cloud-init YAML
        """
        sections = []

        # Start with cloud-init header
        sections.append("#cloud-config")

        # Add package installation
        if self.config.packages:
            sections.append(self._generate_packages_section())

        # Add users section (for creating directories)
        sections.append(self._generate_users_section())

        # Add write_files section for inline files
        write_files = self._generate_write_files_section()
        if write_files:
            sections.append(write_files)

        # Add runcmd section for scripts and setup
        runcmd = self._generate_runcmd_section()
        if runcmd:
            sections.append(runcmd)

        # Join all sections with newlines
        cloud_init = "\n\n".join(filter(None, sections))

        logger.debug(f"Generated cloud-init with {len(sections)} sections")
        return cloud_init

    def _generate_packages_section(self) -> str:
        """Generate packages section for cloud-init.

        Returns:
            YAML string for packages section
        """
        if not self.config.packages:
            return ""

        packages_yaml = "packages:\n"
        for package in self.config.packages:
            packages_yaml += f"  - {package}\n"

        logger.debug(f"Generated packages section with {len(self.config.packages)} packages")
        return packages_yaml.rstrip()

    def _generate_users_section(self) -> str:
        """Generate users section to ensure ubuntu user exists.

        Returns:
            YAML string for users section
        """
        users_yaml = """users:
  - default
  - name: ubuntu
    groups: sudo, docker
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL"""

        return users_yaml

    def _generate_write_files_section(self) -> str:
        """Generate write_files section for inline configuration files.

        Returns:
            YAML string for write_files section
        """
        write_files = []

        # Add a minimal deployment script that waits for uploads
        deployment_script = """#!/bin/bash
set -e

echo "Waiting for file uploads to complete..."
# Wait for upload marker file that SSH uploader creates
while [ ! -f /opt/uploads.complete ]; do
    sleep 2
done

echo "Starting deployment..."

# Make uploaded scripts executable
find /opt/deployment -name "*.sh" -type f -exec chmod +x {} \\; 2>/dev/null || true

# Execute main setup script if it exists
if [ -f /opt/deployment/setup.sh ]; then
    cd /opt/deployment
    ./setup.sh
elif [ -f /opt/deployment/init.sh ]; then
    cd /opt/deployment
    ./init.sh
fi

# Extract tarball if it exists
if [ -f /opt/deployment.tar.gz ]; then
    echo "Extracting deployment tarball..."
    cd /opt
    tar -xzf deployment.tar.gz
    rm -f deployment.tar.gz
fi

echo "Deployment completed"
touch /opt/deployment.complete
"""

        write_files.append(
            {"path": "/opt/deploy.sh", "content": deployment_script, "permissions": "0755"}
        )

        # Only add small marker files, not service files (those get uploaded)
        write_files.append(
            {
                "path": "/opt/deployment.marker",
                "content": "Portable deployment\n",
                "permissions": "0644",
            }
        )

        if not write_files:
            return ""

        # Build YAML
        yaml_lines = ["write_files:"]
        for file_spec in write_files:
            yaml_lines.append(f"  - path: {file_spec['path']}")
            yaml_lines.append(f"    permissions: '{file_spec['permissions']}'")
            yaml_lines.append("    content: |")
            # Indent content properly
            for line in file_spec["content"].splitlines():
                yaml_lines.append(f"      {line}")

        return "\n".join(yaml_lines)

    def _generate_runcmd_section(self) -> str:
        """Generate minimal runcmd section for script execution.

        Returns:
            YAML string for runcmd section
        """
        commands = []

        # Create necessary directories
        commands.extend(
            [
                "mkdir -p /opt/deployment",
                "mkdir -p /opt/configs",
                "mkdir -p /opt/files",
                "mkdir -p /opt/secrets",
                "mkdir -p /opt/uploaded_files",
            ]
        )

        # Run the deployment script in background after delay
        # This allows SSH to connect and upload files first
        commands.append("nohup bash -c 'sleep 30; /opt/deploy.sh' > /opt/deploy.log 2>&1 &")

        if not commands:
            return ""

        # Build YAML
        yaml_lines = ["runcmd:"]
        for cmd in commands:
            # Escape special characters in YAML
            escaped_cmd = cmd.replace("'", "''")
            yaml_lines.append(f"  - '{escaped_cmd}'")

        return "\n".join(yaml_lines)

    def generate_with_template(self, template_path: Optional[Path] = None) -> str:
        """Generate cloud-init using a template file.

        Args:
            template_path: Path to cloud-init template file

        Returns:
            String containing the cloud-init YAML
        """
        if template_path and template_path.exists():
            try:
                with open(template_path, "r") as f:
                    template = f.read()

                # Replace template variables
                replacements = {
                    "{{PACKAGES}}": self._generate_packages_list(),
                    "{{SCRIPTS}}": self._generate_scripts_list(),
                    "{{SERVICES}}": self._generate_services_list(),
                }

                for key, value in replacements.items():
                    template = template.replace(key, value)

                logger.info(f"Generated cloud-init from template: {template_path}")
                return template
            except Exception as e:
                logger.warning(f"Could not use template {template_path}: {e}")

        # Fall back to regular generation
        return self.generate()

    def _generate_packages_list(self) -> str:
        """Generate formatted list of packages for template.

        Returns:
            Formatted package list string
        """
        if not self.config.packages:
            return ""

        return "\n".join(f"  - {pkg}" for pkg in self.config.packages)

    def _generate_scripts_list(self) -> str:
        """Generate formatted list of scripts for template.

        Returns:
            Formatted scripts list string
        """
        if not self.config.scripts:
            return ""

        script_cmds = []
        for script in self.config.scripts:
            cmd = script.get("command", "")
            if cmd:
                script_cmds.append(f"  - '{cmd}'")

        return "\n".join(script_cmds)

    def _generate_services_list(self) -> str:
        """Generate formatted list of services for template.

        Returns:
            Formatted services list string
        """
        if not self.config.services:
            return ""

        service_names = []
        for s in self.config.services:
            if isinstance(s, dict):
                path = s.get("path")
                if path:
                    service_names.append(Path(path).name)
            else:
                service_names.append(Path(s).name)
        return "\n".join(f"  - {name}" for name in service_names)

    def validate(self) -> tuple[bool, list[str]]:
        """Validate the deployment configuration for cloud-init generation.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Check for excessively large package lists
        if len(self.config.packages) > 100:
            errors.append(
                f"Too many packages ({len(self.config.packages)}), may exceed cloud-init limits"
            )

        # Check for script paths
        for script in self.config.scripts:
            command = script.get("command", "")
            if command and not command.startswith("/"):
                errors.append(f"Script command should use absolute path: {command}")

        # Check service files exist
        for service_item in self.config.services:
            if isinstance(service_item, dict):
                service_path = service_item.get("path")
                if not service_path:
                    continue
            else:
                service_path = service_item
            service_file = Path(service_path)
            if not service_file.exists():
                errors.append(f"Service file not found: {service_path}")

        # Check upload destinations
        for upload in self.config.uploads:
            dest = upload.get("destination", "")
            if not dest.startswith("/"):
                errors.append(f"Upload destination should use absolute path: {dest}")

        return len(errors) == 0, errors


class CloudInitBuilder:
    """Builder pattern for constructing cloud-init configurations."""

    def __init__(self):
        """Initialize an empty cloud-init builder."""
        self.packages = []
        self.files = []
        self.commands = []
        self.users = []

    def add_package(self, package: str) -> "CloudInitBuilder":
        """Add a package to install.

        Args:
            package: Package name

        Returns:
            Self for chaining
        """
        self.packages.append(package)
        return self

    def add_packages(self, packages: list[str]) -> "CloudInitBuilder":
        """Add multiple packages to install.

        Args:
            packages: List of package names

        Returns:
            Self for chaining
        """
        self.packages.extend(packages)
        return self

    def add_file(self, path: str, content: str, permissions: str = "0644") -> "CloudInitBuilder":
        """Add a file to write.

        Args:
            path: File path
            content: File content
            permissions: File permissions

        Returns:
            Self for chaining
        """
        self.files.append({"path": path, "content": content, "permissions": permissions})
        return self

    def add_command(self, command: str) -> "CloudInitBuilder":
        """Add a command to run.

        Args:
            command: Shell command

        Returns:
            Self for chaining
        """
        self.commands.append(command)
        return self

    def add_commands(self, commands: list[str]) -> "CloudInitBuilder":
        """Add multiple commands to run.

        Args:
            commands: List of shell commands

        Returns:
            Self for chaining
        """
        self.commands.extend(commands)
        return self

    def build(self) -> str:
        """Build the final cloud-init YAML.

        Returns:
            Complete cloud-init YAML string
        """
        sections = ["#cloud-config"]

        # Add packages
        if self.packages:
            sections.append("packages:")
            for pkg in self.packages:
                sections.append(f"  - {pkg}")

        # Add files
        if self.files:
            sections.append("\nwrite_files:")
            for file_spec in self.files:
                sections.append(f"  - path: {file_spec['path']}")
                sections.append(f"    permissions: '{file_spec['permissions']}'")
                sections.append("    content: |")
                for line in file_spec["content"].splitlines():
                    sections.append(f"      {line}")

        # Add commands
        if self.commands:
            sections.append("\nruncmd:")
            for cmd in self.commands:
                escaped = cmd.replace("'", "''")
                sections.append(f"  - '{escaped}'")

        return "\n".join(sections)
