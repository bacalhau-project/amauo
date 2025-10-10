"""SSH Manager - Centralized SSH and file transfer operations."""

import subprocess
import time
from typing import Callable, Optional

from ..core.constants import DEFAULT_SSH_TIMEOUT


class SSHManager:
    """Manages SSH connections and file transfers to instances."""

    def __init__(self, hostname: str, username: str, private_key_path: str):
        """Initialize SSH manager for a specific host."""
        self.hostname = hostname
        self.username = username
        self.private_key_path = private_key_path
        self.ssh_base_args = [
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
        ]

    def wait_for_ssh(self, timeout: int = DEFAULT_SSH_TIMEOUT) -> bool:
        """Wait for SSH to become available on the host."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            if self._test_ssh_connection():
                return True
            time.sleep(2)

        return False

    def _test_ssh_connection(self) -> bool:
        """Test if SSH connection is available."""
        try:
            cmd = [
                "ssh",
                "-i",
                self.private_key_path,
                *self.ssh_base_args,
                f"{self.username}@{self.hostname}",
                "echo 'SSH ready'",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False

    def execute_command(
        self, command: str, timeout: int = 30, retries: int = 3
    ) -> tuple[bool, str, str]:
        """
        Execute a command on the remote host with retry logic.

        Returns:
            Tuple of (success, stdout, stderr)
        """
        cmd = [
            "ssh",
            "-i",
            self.private_key_path,
            *self.ssh_base_args,
            f"{self.username}@{self.hostname}",
            command,
        ]

        for attempt in range(retries):
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout
                )
                if result.returncode == 0:
                    return True, result.stdout, result.stderr
                elif attempt < retries - 1:
                    time.sleep(2**attempt)  # Exponential backoff
                else:
                    return False, result.stdout, result.stderr
            except subprocess.TimeoutExpired:
                if attempt < retries - 1:
                    time.sleep(2**attempt)
                else:
                    return False, "", "Command timed out"
            except Exception as e:
                if attempt == retries - 1:
                    return False, "", str(e)

        return False, "", "Failed after all retries"

    def transfer_file(
        self, local_path: str, remote_path: str, timeout: int = 120, retries: int = 3
    ) -> tuple[bool, str]:
        """Transfer a single file to the remote host with retry logic.

        Returns:
            Tuple of (success, error_message)
        """
        return self._scp_with_retry(local_path, remote_path, timeout, retries)

    def transfer_directory(
        self, local_path: str, remote_path: str, timeout: int = 300, retries: int = 3
    ) -> tuple[bool, str]:
        """Transfer a directory to the remote host with retry logic.

        Returns:
            Tuple of (success, error_message)
        """
        return self._scp_with_retry(
            local_path, remote_path, timeout, retries, recursive=True
        )

    def _scp_with_retry(
        self,
        local_path: str,
        remote_path: str,
        timeout: int,
        retries: int,
        recursive: bool = False,
    ) -> tuple[bool, str]:
        """Execute SCP with retry logic.

        Returns:
            Tuple of (success, error_message)
        """
        scp_cmd = ["scp", "-i", self.private_key_path, *self.ssh_base_args]

        if recursive:
            scp_cmd.append("-r")

        scp_cmd.extend([local_path, f"{self.username}@{self.hostname}:{remote_path}"])

        last_error = ""
        for attempt in range(retries):
            try:
                result = subprocess.run(
                    scp_cmd, capture_output=True, text=True, timeout=timeout
                )
                if result.returncode == 0:
                    return True, ""
                else:
                    last_error = (
                        result.stderr.strip()
                        or result.stdout.strip()
                        or "Unknown error"
                    )
                    if attempt < retries - 1:
                        time.sleep(2**attempt)  # Exponential backoff
            except subprocess.TimeoutExpired:
                last_error = f"Timeout after {timeout}s"
                if attempt < retries - 1:
                    time.sleep(2**attempt)
            except Exception as e:
                last_error = str(e)
                if attempt == retries - 1:
                    return False, last_error

        return False, last_error

    def create_remote_directory(self, path: str, retries: int = 3) -> bool:
        """Create a directory on the remote host."""
        success, _, _ = self.execute_command(f"mkdir -p {path}", retries=retries)
        return success

    def file_exists(self, path: str) -> bool:
        """Check if a file exists on the remote host."""
        success, _, _ = self.execute_command(f"test -e {path}")
        return success

    def read_file(self, path: str) -> Optional[str]:
        """Read a file from the remote host."""
        success, stdout, _ = self.execute_command(f"cat {path}")
        return stdout if success else None


class BatchSSHManager:
    """Manages SSH operations across multiple hosts concurrently."""

    def __init__(self, hosts: list[dict[str, str]], private_key_path: str):
        """
        Initialize batch SSH manager.

        Args:
            hosts: List of dicts with 'hostname' and 'username' keys
            private_key_path: Path to SSH private key
        """
        self.managers = {
            host["hostname"]: SSHManager(
                host["hostname"], host["username"], private_key_path
            )
            for host in hosts
        }

    def wait_for_all_ssh(
        self, timeout: int = DEFAULT_SSH_TIMEOUT, callback: Optional[Callable] = None
    ) -> dict[str, bool]:
        """
        Wait for SSH to be available on all hosts.

        Returns:
            Dict mapping hostname to success status
        """
        results = {}
        start_time = time.time()
        remaining_timeout = timeout

        for hostname, manager in self.managers.items():
            if callback:
                callback(f"Waiting for SSH on {hostname}...")

            elapsed = time.time() - start_time
            remaining_timeout = max(
                10, int(timeout - elapsed)
            )  # At least 10 seconds per host

            results[hostname] = manager.wait_for_ssh(remaining_timeout)

            if callback:
                status = "ready" if results[hostname] else "failed"
                callback(f"SSH {status} on {hostname}")

        return results

    def execute_on_all(
        self, command: str, timeout: int = 30
    ) -> dict[str, tuple[bool, str, str]]:
        """
        Execute a command on all hosts.

        Returns:
            Dict mapping hostname to (success, stdout, stderr) tuple
        """
        results = {}
        for hostname, manager in self.managers.items():
            results[hostname] = manager.execute_command(command, timeout)
        return results

    def transfer_to_all(
        self, local_path: str, remote_path: str, timeout: int = 120
    ) -> dict[str, tuple[bool, str]]:
        """
        Transfer a file to all hosts.

        Returns:
            Dict mapping hostname to (success, error_message) tuple
        """
        results = {}
        for hostname, manager in self.managers.items():
            results[hostname] = manager.transfer_file(local_path, remote_path, timeout)
        return results
