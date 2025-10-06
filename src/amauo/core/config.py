"""Configuration management for spot deployer."""

import logging
import os
from typing import Any, Optional, cast

import yaml

logger = logging.getLogger(__name__)


class SimpleConfig:
    """Enhanced configuration loader with full options support."""

    # Class-level singleton for deployment ID
    _deployment_id = None

    def __init__(
        self,
        config_file: str = "config.yaml",
        files_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
    ):
        self.config_file = config_file
        self.files_dir = files_dir
        self.output_dir = output_dir
        self.data = self._load_config()

    def _load_config(self) -> dict:
        """Load YAML configuration."""
        try:
            with open(self.config_file) as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.error(
                f"Config file {self.config_file} not found. Run 'setup' first."
            )
            return {}
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return {}

    def regions(self) -> list[str]:
        """Get list of regions."""
        return [list(region.keys())[0] for region in self.data.get("regions", [])]

    def instance_count(self) -> int:
        """Get total instance count."""
        return cast(int, self.data.get("aws", {}).get("total_instances", 3))

    def username(self) -> str:
        """Get SSH username."""
        return cast(str, self.data.get("aws", {}).get("username", "ubuntu"))

    def ssh_key_name(self) -> Optional[str]:
        """Get SSH key name if configured. (Deprecated - we use local SSH keys via cloud-init)"""
        return cast(Optional[str], self.data.get("aws", {}).get("ssh_key_name"))

    def public_ssh_key_path(self) -> Optional[str]:
        """Get public SSH key file path."""
        path = self.data.get("aws", {}).get("public_ssh_key_path")
        if path:
            return self._resolve_ssh_path(path)
        return None

    def private_ssh_key_path(self) -> Optional[str]:
        """Get private SSH key file path."""
        path = self.data.get("aws", {}).get("private_ssh_key_path")
        if path:
            return self._resolve_ssh_path(path)
        return None

    def _raw_public_ssh_key_path(self) -> Optional[str]:
        """Get raw public SSH key path from config (unresolved)."""
        return cast(Optional[str], self.data.get("aws", {}).get("public_ssh_key_path"))

    def _resolve_ssh_path(self, path: str) -> str:
        """Resolve SSH path - just expand user paths."""
        return os.path.expanduser(path)

    def public_ssh_key_content(self) -> Optional[str]:
        """Get public SSH key content."""
        key_path = self.public_ssh_key_path()  # Already resolved
        if key_path:
            if os.path.exists(key_path):
                try:
                    with open(key_path) as f:
                        return f.read().strip()
                except Exception as e:
                    logger.error(f"Error reading public key from {key_path}: {e}")
            else:
                logger.error(f"❌ Public SSH key not found at '{key_path}'")
        return None

    def files_directory(self) -> str:
        """Get files directory path."""
        # If explicitly provided, use that
        if self.files_dir:
            return self.files_dir

        # Otherwise get from config or use default
        return cast(
            str, self.data.get("aws", {}).get("files_directory", "instance-files")
        )

    def scripts_directory(self) -> str:
        """Get scripts directory path."""
        return cast(
            str, self.data.get("aws", {}).get("scripts_directory", "instance/scripts")
        )

    def output_directory(self) -> str:
        """Get output directory path."""
        # If explicitly provided, use that
        if self.output_dir:
            return self.output_dir

        # Otherwise use default from constants
        from .constants import DEFAULT_OUTPUT_DIR

        return DEFAULT_OUTPUT_DIR

    def cloud_init_template(self) -> str:
        """Get cloud-init template path."""
        return cast(
            str,
            self.data.get("aws", {}).get(
                "cloud_init_template", "instance/cloud-init/init-vm-template.yml"
            ),
        )

    def startup_script(self) -> str:
        """Get startup script path."""
        return cast(
            str,
            self.data.get("aws", {}).get(
                "startup_script", "instance/scripts/startup.py"
            ),
        )

    def additional_commands_script(self) -> Optional[str]:
        """Get additional commands script path."""
        return cast(
            Optional[str], self.data.get("aws", {}).get("additional_commands_script")
        )

    def docker_compose_template(self) -> str:
        """Get Docker Compose template path."""
        return cast(
            str,
            self.data.get("aws", {}).get(
                "docker_compose_template", "instance/scripts/docker-compose.yaml"
            ),
        )

    def spot_price_limit(self) -> Optional[float]:
        """Get spot price limit."""
        return cast(Optional[float], self.data.get("aws", {}).get("spot_price_limit"))

    def instance_storage_gb(self) -> int:
        """Get instance storage size in GB."""
        return cast(int, self.data.get("aws", {}).get("instance_storage_gb", 50))

    def security_group_name(self) -> str:
        """Get security group name."""
        return cast(
            str, self.data.get("aws", {}).get("security_group_name", "amauo-sg")
        )

    def vpc_tag_name(self) -> Optional[str]:
        """Get VPC tag name for filtering."""
        return cast(Optional[str], self.data.get("aws", {}).get("vpc_tag_name"))

    def associate_public_ip(self) -> bool:
        """Whether to associate public IP addresses."""
        return cast(bool, self.data.get("aws", {}).get("associate_public_ip", True))

    def tags(self) -> dict[str, str]:
        """Get additional tags for instances."""
        return cast(dict[str, str], self.data.get("aws", {}).get("tags", {}))

    def use_dedicated_vpc(self) -> bool:
        """Whether to create dedicated VPCs for each deployment."""
        return cast(bool, self.data.get("aws", {}).get("use_dedicated_vpc", False))

    def ensure_default_vpc(self) -> bool:
        """Whether to create default VPCs if they don't exist."""
        return cast(bool, self.data.get("aws", {}).get("ensure_default_vpc", True))

    def region_config(self, region: str) -> dict[Any, Any]:
        """Get config for specific region."""
        for r in cast(list[dict[str, Any]], self.data.get("regions", [])):
            if region in r:
                return cast(dict[Any, Any], r[region])
        return {"machine_type": "t3.medium", "image": "auto"}

    def get_deployment_id(self) -> str:
        """Get or create a singleton deployment ID for this session."""
        if SimpleConfig._deployment_id is None:
            import time

            SimpleConfig._deployment_id = f"amauo-{int(time.time())}"
        return SimpleConfig._deployment_id
