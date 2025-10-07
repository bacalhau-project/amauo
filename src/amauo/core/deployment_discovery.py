"""Deployment discovery module for detecting and validating deployment structures."""

import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from .convention_scanner import ConventionScanner
from .deployment import DeploymentConfig

logger = logging.getLogger(__name__)


class DeploymentMode(Enum):
    """Deployment mode enumeration."""

    PORTABLE = "portable"  # .spot/ directory with deployment.yaml
    CONVENTION = "convention"  # deployment/ directory with convention-based structure
    NONE = "none"  # No deployment structure found


@dataclass
class DeploymentDiscoveryResult:
    """Result of deployment discovery."""

    mode: DeploymentMode
    project_root: Optional[Path]
    deployment_config: Optional[DeploymentConfig]
    validation_errors: list[str]

    @property
    def is_valid(self) -> bool:
        """Check if the discovery result is valid."""
        return len(self.validation_errors) == 0 and self.mode != DeploymentMode.NONE


class DeploymentDiscovery:
    """Discovers and validates deployment structures."""

    def __init__(self, start_path: Optional[Path] = None):
        """Initialize deployment discovery.

        Args:
            start_path: Starting path for discovery (defaults to current directory)
        """
        if start_path:
            self.start_path = Path(start_path)
        else:
            # Try to get the original working directory where user executed the command
            # This handles cases where tools like `uv run --directory` change cwd
            # Use PWD environment variable which preserves the shell's working directory
            original_cwd = os.environ.get("PWD")
            current_cwd = str(Path.cwd())
            if original_cwd and original_cwd != current_cwd:
                # PWD differs from Python's cwd, use PWD (user's original directory)
                self.start_path = Path(original_cwd)
            else:
                self.start_path = Path.cwd()

    def discover(self) -> DeploymentDiscoveryResult:
        """Discover deployment mode and configuration.

        Returns:
            DeploymentDiscoveryResult with discovered information
        """
        # Check for portable mode (.spot directory)
        if self._has_spot_directory():
            return self._discover_portable()

        # Check for convention mode (deployment directory)
        if self._has_deployment_directory():
            return self._discover_convention()

        # No deployment structure found
        return DeploymentDiscoveryResult(
            mode=DeploymentMode.NONE,
            project_root=None,
            deployment_config=None,
            validation_errors=["No deployment structure found"],
        )

    def detect_deployment_mode(self) -> DeploymentMode:
        """Detect the deployment mode based on directory structure.

        Returns:
            DeploymentMode indicating the type of deployment structure found
        """
        # Debug output
        logger.debug(f"Checking from path {self.start_path}")

        # Check for portable mode (.spot directory with deployment.yaml)
        spot_dir = self.start_path / ".spot"
        logger.debug(f"Checking .spot at {spot_dir}, exists: {spot_dir.exists()}")
        if spot_dir.exists() and (spot_dir / "deployment.yaml").exists():
            return DeploymentMode.PORTABLE

        # Check for convention mode (deployment/ directory)
        deployment_dir = self.start_path / "deployment"
        logger.debug(
            f"Checking deployment at {deployment_dir}, exists: {deployment_dir.exists()}"
        )
        if deployment_dir.exists() and deployment_dir.is_dir():
            # Check if it has expected convention structure
            if (deployment_dir / "setup.sh").exists() or (
                deployment_dir / "init.sh"
            ).exists():
                return DeploymentMode.CONVENTION

        # No deployment structure found
        return DeploymentMode.NONE

    def find_project_root(self, max_depth: int = 5) -> Optional[Path]:
        """Find the project root by looking for deployment markers.

        Args:
            max_depth: Maximum directory levels to traverse up

        Returns:
            Path to project root or None if not found
        """
        current = self.start_path.resolve()

        for _ in range(max_depth):
            # Check for .spot directory
            if (current / ".spot").exists():
                return current

            # Check for deployment directory
            if (current / "deployment").exists():
                return current

            # Check for config.yaml (common root marker)
            if (current / "config.yaml").exists():
                return current

            # Move up one directory
            parent = current.parent
            if parent == current:  # Reached root
                break
            current = parent

        # If we're in a directory with any deployment markers, use it
        if (self.start_path / ".spot").exists() or (
            self.start_path / "deployment"
        ).exists():
            return self.start_path

        return None

    def validate_discovered_structure(
        self, mode: DeploymentMode, root: Path
    ) -> tuple[bool, list]:
        """Validate the discovered deployment structure.

        Args:
            mode: The deployment mode detected
            root: The project root path

        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []

        if mode == DeploymentMode.PORTABLE:
            spot_dir = root / ".spot"

            # Check required files for portable mode
            required_files = [
                spot_dir / "deployment.yaml",
                spot_dir / "config.yaml",
            ]

            for file_path in required_files:
                if not file_path.exists():
                    errors.append(
                        f"Missing required file: {file_path.relative_to(root)}"
                    )

            # Check optional but recommended directories
            recommended_dirs = [
                spot_dir / "scripts",
                spot_dir / "files",
                spot_dir / "services",
                spot_dir / "configs",
            ]

            for dir_path in recommended_dirs:
                if not dir_path.exists():
                    # Not an error, just note it doesn't exist
                    pass

        elif mode == DeploymentMode.CONVENTION:
            deployment_dir = root / "deployment"

            if not deployment_dir.exists():
                errors.append("Deployment directory not found")
            else:
                # Must have at least one setup script
                has_setup = (deployment_dir / "setup.sh").exists() or (
                    deployment_dir / "init.sh"
                ).exists()
                if not has_setup:
                    errors.append(
                        "No setup.sh or init.sh found in deployment directory"
                    )

        return len(errors) == 0, errors

    def get_deployment_config(self) -> Optional[DeploymentConfig]:
        """Get deployment configuration based on discovered structure.

        Returns:
            DeploymentConfig object or None if discovery failed
        """
        # Find project root
        root = self.find_project_root()
        if not root:
            return None

        # Detect mode
        mode = self.detect_deployment_mode()

        # Validate structure
        is_valid, errors = self.validate_discovered_structure(mode, root)
        if not is_valid:
            # Log errors but continue
            for error in errors:
                print(f"Warning: {error}")

        # Create deployment config based on mode
        if mode == DeploymentMode.PORTABLE:
            spot_dir = root / ".spot"
            if spot_dir.exists():
                try:
                    return DeploymentConfig.from_spot_dir(spot_dir)
                except Exception as e:
                    logger.error(f"Failed to load deployment config: {e}")
                    return None

        elif mode == DeploymentMode.CONVENTION:
            # For convention mode, build config from discovered files
            # This will be implemented in the convention scanner (Item 4)
            return None

        # No other modes, return None
        return None

    def _has_spot_directory(self) -> bool:
        """Check if .spot directory exists."""
        return (self.start_path / ".spot").is_dir()

    def _has_deployment_directory(self) -> bool:
        """Check if deployment directory exists."""
        return (self.start_path / "deployment").is_dir()

    def _discover_portable(self) -> DeploymentDiscoveryResult:
        """Discover portable deployment (.spot directory)."""
        project_root = self.find_project_root()
        if not project_root:
            project_root = self.start_path

        errors: list[str] = []
        is_valid, errors = self.validate_discovered_structure(
            DeploymentMode.PORTABLE, project_root
        )

        # Try to load deployment config
        deployment_config = None
        if is_valid:
            try:
                deployment_config = DeploymentConfig.from_spot_dir(
                    project_root / ".spot"
                )
            except Exception as e:
                errors.append(f"Failed to load deployment config: {e}")

        return DeploymentDiscoveryResult(
            mode=DeploymentMode.PORTABLE,
            project_root=project_root,
            deployment_config=deployment_config,
            validation_errors=errors,
        )

    def _discover_convention(self) -> DeploymentDiscoveryResult:
        """Discover convention-based deployment (deployment directory)."""
        project_root = self.find_project_root()
        if not project_root:
            project_root = self.start_path

        is_valid, errors = self.validate_discovered_structure(
            DeploymentMode.CONVENTION, project_root
        )

        # Build deployment config from conventions using scanner
        deployment_config = None
        if is_valid:
            scanner = ConventionScanner(project_root / "deployment")
            deployment_config = scanner.scan()
            if not deployment_config:
                errors.append("Failed to build configuration from conventions")

        return DeploymentDiscoveryResult(
            mode=DeploymentMode.CONVENTION,
            project_root=project_root,
            deployment_config=deployment_config,
            validation_errors=errors,
        )

        # Build deployment config from conventions (will be implemented later)
        deployment_config = None  # type: ignore[unreachable]

        return DeploymentDiscoveryResult(
            mode=DeploymentMode.CONVENTION,
            project_root=project_root,
            deployment_config=deployment_config,
            validation_errors=errors,
        )
