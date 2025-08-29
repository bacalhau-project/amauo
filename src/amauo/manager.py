"""
SkyPilot Cluster Manager - Core cluster operations.

Handles Docker container management, SkyPilot interactions, and cluster lifecycle.
Uses proper YAML parsing and Rich output instead of fragile bash scripting.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table


class ClusterManager:
    """Manages SkyPilot cluster operations through Docker container."""

    def __init__(
        self, log_to_console: bool = False, log_file: str = "cluster-deploy.log"
    ):
        self.console = Console()
        self.log_to_console = log_to_console
        self.log_file = Path(log_file)
        self.docker_container = "skypilot-cluster-deploy"
        self.skypilot_image = "berkeleyskypilot/skypilot"

    def log(self, level: str, message: str, style: str = "") -> None:
        """Log message to console and/or file."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if self.log_to_console:
            self.console.print(f"[{level}] {message}", style=style)
        else:
            # Write to file
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] [{level}] {message}\n")
            # Also show brief status to console
            self.console.print(f"[{level}] {message}", style=style)

    def log_info(self, message: str) -> None:
        """Log info message."""
        self.log("INFO", message, "blue")

    def log_success(self, message: str) -> None:
        """Log success message."""
        self.log("SUCCESS", message, "green")

    def log_warning(self, message: str) -> None:
        """Log warning message."""
        self.log("WARNING", message, "yellow")

    def log_error(self, message: str) -> None:
        """Log error message."""
        self.log("ERROR", message, "red")

    def log_header(self, message: str) -> None:
        """Log header message."""
        if self.log_to_console:
            self.console.print(f"\n🌍 {message}", style="bold blue")
            self.console.print()
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"\n[{timestamp}] [HEADER] 🌍 {message}\n\n")
            self.console.print(f"\n🌍 {message}", style="bold blue")
            self.console.print()

    def load_cluster_config(self, config_file: str = "cluster.yaml") -> dict[str, Any]:
        """Load and parse cluster configuration from YAML."""
        config_path = Path(config_file)
        if not config_path.exists():
            self.log_error(f"Config file not found: {config_file}")
            raise FileNotFoundError(f"Config file not found: {config_file}")

        try:
            with open(config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f)
                if not isinstance(config, dict):
                    raise ValueError("Config file must contain a YAML object")
                return config
        except yaml.YAMLError as e:
            self.log_error(f"Invalid YAML in {config_file}: {e}")
            raise
        except Exception as e:
            self.log_error(f"Failed to load config {config_file}: {e}")
            raise

    def get_cluster_name_from_config(self, config_file: str = "cluster.yaml") -> str:
        """Extract cluster name from YAML config."""
        try:
            config = self.load_cluster_config(config_file)
            return str(config.get("name", "cluster"))
        except Exception:
            return "cluster"

    def ensure_docker_container(self) -> bool:
        """Ensure Docker container is running."""
        try:
            # Check if container is already running
            result = subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    f"name={self.docker_container}",
                    "--filter",
                    "status=running",
                    "--quiet",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.stdout.strip():
                return True  # Container already running

            self.log_info("Starting SkyPilot Docker container...")

            # Remove any existing stopped container
            subprocess.run(
                ["docker", "rm", self.docker_container],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

            # Start new container
            home = Path.home()
            cwd = Path.cwd()

            cmd = [
                "docker",
                "run",
                "-td",
                "--rm",
                "--name",
                self.docker_container,
                "-v",
                f"{home}/.sky:/root/.sky:rw",
                "-v",
                f"{home}/.aws:/root/.aws:rw",
                "-v",
                f"{home}/.config/gcloud:/root/.config/gcloud:rw",
                "-v",
                f"{cwd}:/workspace:rw",
                "-w",
                "/workspace",
                self.skypilot_image,
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                self.log_success("SkyPilot Docker container started")
                return True
            else:
                self.log_error("Failed to start SkyPilot Docker container")
                if result.stderr:
                    self.log_error(f"Docker error: {result.stderr}")
                return False

        except FileNotFoundError:
            self.log_error("Docker command not found. Please install Docker.")
            return False
        except Exception as e:
            self.log_error(f"Failed to manage Docker container: {e}")
            return False

    def restart_docker_container(self) -> bool:
        """Restart the Docker container to refresh credentials."""
        self.log_info("Restarting SkyPilot Docker container...")

        # Stop and remove existing container
        subprocess.run(
            ["docker", "stop", self.docker_container],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        subprocess.run(
            ["docker", "rm", self.docker_container],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

        # Start fresh container
        return self.ensure_docker_container()

    def debug_container_credentials(self) -> None:
        """Debug AWS credentials inside the Docker container."""
        if not self.ensure_docker_container():
            self.log_error("Cannot debug - container not running")
            return

        self.log_info("Debugging AWS credentials inside container:")

        # Check if .aws directory exists
        result = subprocess.run(
            ["docker", "exec", self.docker_container, "ls", "-la", "/root/.aws/"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            self.log_info("AWS directory contents:")
            for line in result.stdout.strip().split("\n"):
                self.log_info(f"  {line}")
        else:
            self.log_error("No /root/.aws directory in container")

        # Test AWS CLI in container
        result = subprocess.run(
            [
                "docker",
                "exec",
                self.docker_container,
                "aws",
                "sts",
                "get-caller-identity",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            self.log_success("AWS CLI works in container")
        else:
            self.log_error(f"AWS CLI failed in container: {result.stderr[:100]}")

        # Check SkyPilot config
        result = subprocess.run(
            ["docker", "exec", self.docker_container, "ls", "-la", "/root/.sky/"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            self.log_info("SkyPilot directory contents:")
            for line in result.stdout.strip().split("\n"):
                self.log_info(f"  {line}")

    def run_sky_cmd(self, *args: str, timeout: int = 10) -> tuple[bool, str, str]:
        """Run sky command in Docker container. Returns (success, stdout, stderr)."""
        if not self.ensure_docker_container():
            return False, "", "Failed to start container"

        cmd = ["docker", "exec", self.docker_container, "sky"] + list(args)
        cmd_str = " ".join(args)

        if self.log_to_console:
            print(f"[DEBUG] Running: sky {cmd_str} (timeout={timeout}s)")

        start_time = time.time()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=False, timeout=timeout
            )
            elapsed = time.time() - start_time
            if self.log_to_console:
                print(
                    f"[DEBUG] Completed in {elapsed:.1f}s (returncode={result.returncode})"
                )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            if self.log_to_console:
                print(f"[DEBUG] Timed out after {elapsed:.1f}s")
            return (
                False,
                "",
                f"Command 'sky {cmd_str}' timed out after {timeout} seconds",
            )
        except Exception as e:
            elapsed = time.time() - start_time
            if self.log_to_console:
                print(f"[DEBUG] Failed after {elapsed:.1f}s: {e}")
            return False, "", str(e)

    def get_sky_cluster_name(self) -> Optional[str]:
        """Get actual SkyPilot cluster name from status."""
        # Try JSON format first with shorter timeout
        success, stdout, stderr = self.run_sky_cmd(
            "status", "--format", "json", timeout=5
        )
        if success and stdout.strip():
            try:
                data = json.loads(stdout)
                clusters = data.get("clusters", [])
                if clusters and isinstance(clusters, list):
                    cluster_name = clusters[0].get("name")
                    return str(cluster_name) if cluster_name else None
            except json.JSONDecodeError:
                pass
        elif "timed out" in stderr:
            self.log_warning("Status command timed out, SkyPilot may be having issues")
            return None

        # Fallback to text parsing
        success, stdout, stderr = self.run_sky_cmd("status", timeout=5)
        if success and stdout:
            for line in stdout.split("\n"):
                line = line.strip()
                if line and not line.startswith(("NAME", "Enabled", "No", "Clusters")):
                    parts = line.split()
                    if parts and parts[0].startswith("sky-"):
                        return parts[0]
        elif "timed out" in stderr:
            self.log_warning("Status command timed out, SkyPilot may be having issues")

        return None

    def check_prerequisites(self) -> bool:
        """Check Docker and SkyPilot availability."""
        self.log_header("Checking Prerequisites")

        # Check Docker
        try:
            subprocess.run(["docker", "--version"], capture_output=True, check=True)
            subprocess.run(["docker", "info"], capture_output=True, check=True)
            self.log_success("Docker is available and running")
        except subprocess.CalledProcessError as e:
            self.log_error(f"Docker check failed: {e}")
            return False
        except FileNotFoundError:
            self.log_error("Docker not found. Please install Docker.")
            return False

        # Check SkyPilot image
        self.log_info("Ensuring SkyPilot Docker image is available...")
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", self.skypilot_image],
                capture_output=True,
                check=False,
            )

            if result.returncode != 0:
                self.log_info("Pulling SkyPilot Docker image...")
                result = subprocess.run(
                    ["docker", "pull", self.skypilot_image], check=False
                )
                if result.returncode != 0:
                    self.log_error("Failed to pull SkyPilot Docker image")
                    return False
        except Exception as e:
            self.log_error(f"Failed to check Docker image: {e}")
            return False

        # Test SkyPilot
        success, stdout, stderr = self.run_sky_cmd("--version")
        if not success:
            self.log_error("SkyPilot not available in Docker container")
            if stderr:
                self.log_error(f"SkyPilot error: {stderr}")
            return False

        version = stdout.split("\n")[0] if stdout else "unknown"
        self.log_success(f"SkyPilot available: {version}")

        # Check AWS credentials - this should fail fast to prevent deployment errors
        aws_creds_path = Path.home() / ".aws" / "credentials"
        if aws_creds_path.exists() or os.getenv("AWS_ACCESS_KEY_ID"):
            # First do a quick AWS CLI check
            try:
                aws_result = subprocess.run(
                    [
                        "aws",
                        "sts",
                        "get-caller-identity",
                        "--query",
                        "Account",
                        "--output",
                        "text",
                        "--no-paginate",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                if aws_result.returncode != 0:
                    self.log_error("AWS credentials not working")
                    if "ExpiredToken" in aws_result.stderr:
                        self.log_error("AWS credentials expired. Run: aws sso login")
                    elif (
                        "Invalid" in aws_result.stderr
                        or "AccessDenied" in aws_result.stderr
                    ):
                        self.log_error(
                            "AWS credentials invalid. Check: aws sts get-caller-identity"
                        )
                    else:
                        self.log_error(f"AWS error: {aws_result.stderr.strip()}")
                    self.log_error(
                        "Fix AWS credentials before deployment. Common fixes:"
                    )
                    self.log_error("  - Run: aws sso login")
                    self.log_error("  - Or check: aws sts get-caller-identity")
                    self.log_error("  - Or verify ~/.aws/credentials")
                    return False

                account = aws_result.stdout.strip()
            except subprocess.TimeoutExpired:
                self.log_error("AWS credential check timed out")
                self.log_error(
                    "This usually means credential issues. Try: aws sso login"
                )
                return False
            except FileNotFoundError:
                self.log_error("AWS credentials configured but aws CLI not available")
                return False

            # Now check SkyPilot's AWS integration with timeout
            success, stdout, stderr = self.run_sky_cmd("check", timeout=15)
            if success and stdout and "AWS: enabled" in stdout:
                self.log_success(f"AWS credentials available (Account: {account})")
            else:
                self.log_warning(
                    "AWS credentials work locally but not in SkyPilot container"
                )
                self.log_info(
                    "Attempting to restart Docker container to refresh credentials..."
                )

                if self.restart_docker_container():
                    # Try SkyPilot check again after restart
                    success2, stdout2, stderr2 = self.run_sky_cmd("check", timeout=15)
                    if success2 and stdout2 and "AWS: enabled" in stdout2:
                        self.log_success(
                            f"AWS credentials available after restart (Account: {account})"
                        )
                        return True

                self.log_error(
                    "AWS credentials still not working with SkyPilot after restart"
                )

                if "timed out" in stderr:
                    self.log_error("SkyPilot check timed out - this usually indicates:")
                    self.log_error("  - AWS credential expiration")
                    self.log_error("  - Network connectivity issues")
                    self.log_error("  - SkyPilot server problems")
                elif "500 Server Error" in stderr or "HTTPError" in stderr:
                    self.log_error("SkyPilot server error - this usually indicates:")
                    self.log_error("  - AWS credential issues (expired/invalid)")
                    self.log_error("  - Stale SkyPilot server state")
                elif stderr:
                    self.log_error(f"SkyPilot check error: {stderr[:200]}...")

                self.log_error("Try these additional fixes:")
                self.log_error("  - Run: aws sso login (again)")
                self.log_error("  - Check: aws sts get-caller-identity")
                self.log_error("  - Wait a few minutes for SSO tokens to propagate")
                return False
        else:
            self.log_error("AWS credentials not found. Configure them in ~/.aws/")
            self.log_error(
                "Run 'aws configure' or 'aws sso login' to set up credentials"
            )
            return False

        return True

    def _parse_deployment_log_line(self, line: str) -> Optional[dict[str, Any]]:
        """Parse a single log line to extract node information."""
        # Pattern: (worker8, rank=8, pid=2816, ip=172.31.41.250) message
        pattern = r"\(([^,]+),\s*rank=(\d+),\s*pid=\d+,\s*ip=([^)]+)\)\s*(.*)"
        match = re.match(pattern, line)

        if match:
            node_name, rank, ip, message = match.groups()
            return {
                "node": node_name,
                "rank": int(rank),
                "ip": ip,
                "message": message.strip(),
                "timestamp": time.time(),
            }
        return None

    def _create_deployment_table(self, nodes: dict[str, dict[str, Any]]) -> Table:
        """Create a Rich table showing deployment progress."""
        table = Table(title="🌍 Global Cluster Deployment Progress", show_header=True)
        table.add_column("Node", style="bold blue", width=12)
        table.add_column("Rank", justify="center", width=6)
        table.add_column("IP Address", style="cyan", width=15)
        table.add_column("Status", width=40)
        table.add_column("Last Update", style="dim", width=12)

        # Sort nodes by rank
        sorted_nodes = sorted(nodes.items(), key=lambda x: x[1].get("rank", 999))

        for node_id, info in sorted_nodes:
            # Determine status from recent messages
            status = self._get_node_status(info)
            status_color = self._get_status_color(status)

            # Format last update time
            last_update = info.get("timestamp", 0)
            time_ago = (
                f"{int(time.time() - last_update)}s ago"
                if last_update > 0
                else "Unknown"
            )

            table.add_row(
                info.get("node", node_id),
                str(info.get("rank", "?")),
                info.get("ip", "Unknown"),
                f"[{status_color}]{status}[/{status_color}]",
                time_ago,
            )

        return table

    def _get_node_status(self, node_info: dict[str, Any]) -> str:
        """Determine node status from recent messages."""
        recent_messages = node_info.get("recent_messages", [])
        if not recent_messages:
            return "Initializing"

        latest_message = recent_messages[-1].lower()

        # Check for specific status indicators
        if "deployment complete" in latest_message:
            return "✅ Deployed"
        elif "health check summary" in latest_message:
            return "🔍 Health Check"
        elif "bacalhau node running" in latest_message:
            return "🚀 Bacalhau Started"
        elif "docker daemon is running" in latest_message:
            return "🐳 Docker Ready"
        elif "pulling" in latest_message or "pull" in latest_message:
            return "📦 Pulling Images"
        elif "starting" in latest_message or "start" in latest_message:
            return "⚡ Starting Services"
        elif "error" in latest_message or "failed" in latest_message:
            return "❌ Error"
        elif "warning" in latest_message:
            return "⚠️ Warning"
        else:
            return "🔄 Working"

    def _get_status_color(self, status: str) -> str:
        """Get Rich color for status."""
        if "✅" in status:
            return "green"
        elif "❌" in status:
            return "red"
        elif "⚠️" in status:
            return "yellow"
        elif "🔄" in status or "⚡" in status or "🚀" in status:
            return "blue"
        elif "🐳" in status or "📦" in status:
            return "cyan"
        else:
            return "white"

    def _monitor_deployment_progress(self, log_file_path: Path) -> None:
        """Monitor deployment log file and update progress display."""
        nodes: dict[str, dict[str, Any]] = {}

        try:
            with Live(
                self._create_deployment_table(nodes), refresh_per_second=2
            ) as live:
                last_position = 0

                # Monitor for up to 20 minutes
                start_time = time.time()
                timeout = 20 * 60  # 20 minutes

                while time.time() - start_time < timeout:
                    try:
                        if log_file_path.exists():
                            with open(log_file_path) as f:
                                f.seek(last_position)
                                new_lines = f.readlines()
                                last_position = f.tell()

                                for line in new_lines:
                                    node_info = self._parse_deployment_log_line(
                                        line.strip()
                                    )
                                    if node_info:
                                        node_id = (
                                            f"{node_info['node']}-{node_info['rank']}"
                                        )

                                        if node_id not in nodes:
                                            nodes[node_id] = {
                                                "node": node_info["node"],
                                                "rank": node_info["rank"],
                                                "ip": node_info["ip"],
                                                "recent_messages": [],
                                                "timestamp": node_info["timestamp"],
                                            }

                                        # Update node info
                                        nodes[node_id]["ip"] = node_info["ip"]
                                        nodes[node_id]["timestamp"] = node_info[
                                            "timestamp"
                                        ]

                                        # Keep last 5 messages for status determination
                                        nodes[node_id]["recent_messages"].append(
                                            node_info["message"]
                                        )
                                        if len(nodes[node_id]["recent_messages"]) > 5:
                                            nodes[node_id]["recent_messages"].pop(0)

                                        # Update the display
                                        live.update(
                                            self._create_deployment_table(nodes)
                                        )

                        time.sleep(1)  # Check for updates every second

                    except Exception:
                        # Continue monitoring even if there are parsing errors
                        continue

        except KeyboardInterrupt:
            # User interrupted - that's fine
            pass

    def _monitor_deployment_progress_streaming(self, cluster_name: str) -> None:
        """Monitor deployment progress using reliable cluster and job status detection."""
        try:
            initial_panel = Panel(
                "🔄 Starting deployment monitoring...\nScanning for clusters...",
                title="🌍 Deployment Monitor",
                border_style="blue",
            )

            with Live(initial_panel, refresh_per_second=1) as live:
                start_time = time.time()
                timeout = 20 * 60  # 20 minutes
                deployment_cluster = None
                job_name = cluster_name  # The job name we're looking for
                last_status = ""
                completion_detected = False

                while time.time() - start_time < timeout and not completion_detected:
                    try:
                        elapsed = int(time.time() - start_time)
                        status_lines = []

                        # Step 1: Find any active cluster (SkyPilot generates internal names)
                        status_success, status_stdout, _ = self.run_sky_cmd("status")
                        if status_success and status_stdout:
                            lines = status_stdout.split("\n")
                            for line in lines:
                                if "sky-" in line and ("INIT" in line or "UP" in line):
                                    parts = line.split()
                                    if len(parts) >= 1:
                                        potential_cluster = parts[0]
                                        if deployment_cluster is None:
                                            deployment_cluster = potential_cluster

                                        # Determine cluster status
                                        if "UP" in line:
                                            cluster_status = "✅ Running"
                                            border_color = "green"
                                        elif "INIT" in line:
                                            cluster_status = "🔄 Initializing"
                                            border_color = "yellow"
                                        else:
                                            cluster_status = "❓ Unknown"
                                            border_color = "dim"

                                        status_lines.append(
                                            f"🏗️  Cluster: {deployment_cluster} ({cluster_status})"
                                        )

                                        # Step 2: Check for running jobs on this cluster
                                        if "UP" in line:
                                            queue_success, queue_stdout, _ = (
                                                self.run_sky_cmd(
                                                    "queue", deployment_cluster
                                                )
                                            )
                                            if queue_success and queue_stdout:
                                                queue_lines = queue_stdout.split("\n")
                                                for qline in queue_lines:
                                                    if job_name in qline:
                                                        qparts = qline.split()
                                                        if len(qparts) >= 7:
                                                            duration = qparts[5]
                                                            status = qparts[6]
                                                            if status == "RUNNING":
                                                                status_lines.append(
                                                                    f"📋 Job: {job_name} - RUNNING for {duration}"
                                                                )

                                                                # Get recent activity
                                                                (
                                                                    log_success,
                                                                    log_stdout,
                                                                    _,
                                                                ) = self.run_sky_cmd(
                                                                    "logs",
                                                                    deployment_cluster,
                                                                    "--tail=3",
                                                                )
                                                                if (
                                                                    log_success
                                                                    and log_stdout
                                                                ):
                                                                    recent_lines = [
                                                                        line.strip()
                                                                        for line in log_stdout.split(
                                                                            "\n"
                                                                        )[-3:]
                                                                        if line.strip()
                                                                    ]
                                                                    if recent_lines:
                                                                        status_lines.append(
                                                                            "\n📝 Recent Activity:"
                                                                        )
                                                                        for log_line in recent_lines:
                                                                            # Clean up log formatting
                                                                            if (
                                                                                "] "
                                                                                in log_line
                                                                            ):
                                                                                clean_line = log_line.split(
                                                                                    "] ",
                                                                                    1,
                                                                                )[-1]
                                                                            else:
                                                                                clean_line = log_line
                                                                            if (
                                                                                "Container"
                                                                                in clean_line
                                                                                and (
                                                                                    "Starting"
                                                                                    in clean_line
                                                                                    or "Started"
                                                                                    in clean_line
                                                                                )
                                                                            ):
                                                                                status_lines.append(
                                                                                    f"  ✅ {clean_line[:70]}..."
                                                                                )
                                                                            elif (
                                                                                "Pulled"
                                                                                in clean_line
                                                                            ):
                                                                                status_lines.append(
                                                                                    f"  📦 {clean_line[:70]}..."
                                                                                )
                                                                            else:
                                                                                status_lines.append(
                                                                                    f"  • {clean_line[:70]}..."
                                                                                )

                                                                # Check for deployment completion indicators
                                                                if any(
                                                                    keyword
                                                                    in log_stdout.lower()
                                                                    for keyword in [
                                                                        "deployment complete",
                                                                        "cluster is running",
                                                                        "node is ready",
                                                                    ]
                                                                ):
                                                                    completion_detected = True
                                                                    status_lines.append(
                                                                        "\n🎉 Deployment appears to be complete!"
                                                                    )

                                                            elif status == "PENDING":
                                                                status_lines.append(
                                                                    f"📋 Job: {job_name} - PENDING for {duration}"
                                                                )
                                                            elif status == "SUCCEEDED":
                                                                status_lines.append(
                                                                    f"📋 Job: {job_name} - SUCCEEDED in {duration}"
                                                                )
                                                                completion_detected = (
                                                                    True
                                                                )
                                                            elif status == "FAILED":
                                                                status_lines.append(
                                                                    f"📋 Job: {job_name} - FAILED after {duration}"
                                                                )
                                                                completion_detected = (
                                                                    True
                                                                )
                                        break

                        # If no cluster found yet
                        if deployment_cluster is None:
                            status_lines = [
                                "⏳ Waiting for cluster to appear...",
                                f"Looking for job: {job_name}",
                                f"Elapsed: {elapsed}s",
                            ]
                            border_color = "yellow"
                        else:
                            status_lines.insert(0, f"⏱️  Elapsed: {elapsed}s")

                        # Build and display panel
                        content = (
                            "\n".join(status_lines)
                            if status_lines
                            else "Scanning for deployment..."
                        )
                        panel = Panel(
                            content,
                            title="🌍 Deployment Monitor",
                            border_style=border_color,
                        )
                        live.update(panel)

                        # Update last status for change detection
                        current_status = "\n".join(status_lines)
                        if current_status != last_status:
                            last_status = current_status

                    except Exception as inner_e:
                        error_panel = Panel(
                            f"⚠️ Monitor error: {inner_e}\nElapsed: {elapsed}s",
                            title="🌍 Deployment Monitor",
                            border_style="red",
                        )
                        live.update(error_panel)

                    time.sleep(3)

                # Final status
                if completion_detected:
                    final_panel = Panel(
                        "🎉 Deployment monitoring complete!\nUse 'amauo status' to check cluster health.",
                        title="🌍 Deployment Monitor",
                        border_style="green",
                    )
                    live.update(final_panel)
                    time.sleep(2)  # Show completion message briefly
                else:
                    timeout_panel = Panel(
                        f"⚠️ Monitoring timeout after {timeout // 60} minutes\nCluster may still be deploying in background.",
                        title="🌍 Deployment Monitor",
                        border_style="yellow",
                    )
                    live.update(timeout_panel)
                    time.sleep(2)

        except KeyboardInterrupt:
            self.console.print("\n[yellow]⚠️ Monitoring interrupted by user[/yellow]")
        except Exception as e:
            self.console.print(f"\n[red]❌ Monitor error: {e}[/red]")

    def _detect_deployment_completion(self, cluster_name: str) -> tuple[bool, str]:
        """
        Detect if deployment has completed successfully.
        Returns (is_complete, status_message)
        """
        try:
            # Check if cluster is UP
            status_success, status_stdout, _ = self.run_sky_cmd("status")
            if not status_success or not status_stdout:
                return False, "Cannot get cluster status"

            cluster_up = False
            actual_cluster_name = None

            # Find our cluster in the status output
            for line in status_stdout.split("\n"):
                if "sky-" in line and "UP" in line:
                    parts = line.split()
                    if len(parts) >= 1:
                        actual_cluster_name = parts[0]
                        cluster_up = True
                        break

            if not cluster_up or actual_cluster_name is None:
                return False, "Cluster not yet UP"

            # Check job status
            queue_success, queue_stdout, _ = self.run_sky_cmd(
                "queue", actual_cluster_name
            )
            if not queue_success:
                return False, "Cannot check job queue"

            # Look for our job in the queue
            for line in queue_stdout.split("\n"):
                if cluster_name in line:  # cluster_name is actually the job name
                    parts = line.split()
                    if len(parts) >= 7:
                        status = parts[6]
                        duration = parts[5]
                        if status == "SUCCEEDED":
                            return True, f"Job completed successfully in {duration}"
                        elif status == "FAILED":
                            return True, f"Job failed after {duration}"
                        elif status == "RUNNING":
                            # Check if it's been running long enough to be considered "setup complete"
                            # Parse duration (e.g., "5m30s" -> seconds)
                            try:
                                duration_seconds = self._parse_duration_to_seconds(
                                    duration
                                )
                                if duration_seconds > 300:  # 5 minutes
                                    # Check logs for completion indicators
                                    if actual_cluster_name is not None:
                                        log_success, log_stdout, _ = self.run_sky_cmd(
                                            "logs", actual_cluster_name, "--tail=10"
                                        )
                                        if log_success and log_stdout:
                                            completion_indicators = [
                                                "deployment complete",
                                                "cluster is running",
                                                "sensor simulator started",
                                                "bacalhau compute started",
                                                "deployment status",
                                                "node is ready",
                                            ]
                                            if any(
                                                indicator in log_stdout.lower()
                                                for indicator in completion_indicators
                                            ):
                                                return (
                                                    True,
                                                    f"Deployment setup completed (running for {duration})",
                                                )

                            except Exception:
                                pass
                            return False, f"Job still running ({duration})"
                        elif status == "PENDING":
                            return False, f"Job pending ({duration})"

            return False, "Job not found in queue"

        except Exception as e:
            return False, f"Error checking completion: {e}"

    def _parse_duration_to_seconds(self, duration: str) -> int:
        """Parse duration string like '5m30s' to total seconds."""
        import re

        total_seconds = 0

        # Handle formats like \"5m30s\", \"2h15m\", \"45s\"
        hours = re.search(r"(\\d+)h", duration)
        minutes = re.search(r"(\\d+)m", duration)
        seconds = re.search(r"(\\d+)s", duration)

        if hours:
            total_seconds += int(hours.group(1)) * 3600
        if minutes:
            total_seconds += int(minutes.group(1)) * 60
        if seconds:
            total_seconds += int(seconds.group(1))

        return total_seconds

    def _extract_node_info_from_logs(self) -> dict[str, dict[str, Any]]:
        """Extract node information from recent cluster logs."""
        cluster_name = self.get_sky_cluster_name()
        if not cluster_name:
            return {}

        try:
            # Get recent logs with longer timeout
            success, stdout, stderr = self.run_sky_cmd(
                "logs", cluster_name, "--tail=100", timeout=20
            )
            if not success or not stdout:
                if "timed out" in stderr:
                    self.log_warning("Log retrieval timed out, using minimal node info")
                return {}

            nodes: dict[str, dict[str, Any]] = {}

            for line in stdout.split("\n"):
                node_info = self._parse_deployment_log_line(line.strip())
                if node_info:
                    node_id = f"{node_info['node']}-{node_info['rank']}"
                    nodes[node_id] = node_info

            return nodes
        except Exception:
            return {}

    def _extract_nodes_from_status(self, status_output: str) -> list[dict[str, str]]:
        """Extract node information from 'sky status' output."""
        nodes = []
        try:
            # Look for lines that contain instance information
            # Format usually includes instance IDs, IPs, zones, etc.
            for line in status_output.split("\n"):
                line = line.strip()
                # Skip header and empty lines
                if not line or "NAME" in line or "----" in line or "Enabled" in line:
                    continue

                # Look for lines with instance details
                # SkyPilot status format varies, but usually has instance info
                if "i-" in line and ("running" in line.lower() or "up" in line.lower()):
                    parts = line.split()
                    node_info = {}

                    # Try to extract instance ID (starts with i-)
                    for part in parts:
                        if part.startswith("i-"):
                            node_info["instance_id"] = part
                            break

                    # Try to extract IP (looks like x.x.x.x)
                    for part in parts:
                        if "." in part and len(part.split(".")) == 4:
                            try:
                                # Validate it's an IP address
                                ip_parts = part.split(".")
                                if all(0 <= int(p) <= 255 for p in ip_parts):
                                    node_info["public_ip"] = part
                                    break
                            except (ValueError, IndexError):
                                continue

                    # Try to extract zone (usually has format like us-west-2a)
                    for part in parts:
                        if len(part) >= 8 and "-" in part and part[-1:].isalpha():
                            if any(
                                region in part
                                for region in ["us-", "eu-", "ap-", "ca-", "sa-"]
                            ):
                                node_info["zone"] = part
                                break

                    if node_info:  # Only add if we found some useful info
                        nodes.append(node_info)
        except Exception:
            pass

        return nodes

    def deploy_cluster(
        self, config_file: str = "cluster.yaml", follow: bool = False
    ) -> bool:
        """Deploy cluster using SkyPilot."""
        config_path = Path(config_file)
        if not config_path.exists():
            self.log_error(f"Config file not found: {config_file}")
            return False

        try:
            cluster_name = self.get_cluster_name_from_config(config_file)
            deployment_id = f"cluster-deploy-{datetime.now().strftime('%Y%m%d%H%M%S')}"

            self.log_header(f"Deploying Global Cluster: {cluster_name}")
            self.log_info(f"Using config: {config_file}")
            self.log_info(f"Cluster name: {cluster_name}")
            self.log_info(f"Deployment ID: {deployment_id}")

            # Set environment variable for deployment ID
            os.environ["CLUSTER_DEPLOYMENT_ID"] = deployment_id

            self.log_info("Launching cluster (this may take 5-10 minutes)...")

            # Launch cluster
            if self.log_to_console:
                # Show output when --console flag used
                success, stdout, stderr = self.run_sky_cmd(
                    "launch", config_file, "--name", cluster_name, "--yes", timeout=600
                )
                if stdout:
                    print(stdout)
                if stderr:
                    print(stderr, file=sys.stderr)
            elif follow:
                # Follow mode - real-time monitoring UI
                self.console.print(
                    "🚀 Starting deployment with real-time progress monitor..."
                )
                self.console.print(f"📄 Detailed logs: {self.log_file}")
                self.console.print(
                    "💡 [dim]Tip: Use 'amauo create' (without --follow) to run in background[/dim]"
                )

                # Ensure log file directory exists
                self.log_file.parent.mkdir(parents=True, exist_ok=True)

                # Start streaming progress monitor in background thread
                monitor_thread = None
                try:
                    monitor_thread = threading.Thread(
                        target=self._monitor_deployment_progress_streaming,
                        args=(cluster_name,),
                        daemon=True,
                    )
                    monitor_thread.start()

                    # Give monitor a moment to start
                    time.sleep(2)

                    # Run deployment (the streaming monitor will track progress)
                    success, stdout, stderr = self.run_sky_cmd(
                        "launch",
                        config_file,
                        "--name",
                        cluster_name,
                        "--yes",
                        timeout=600,
                    )

                    # Log output to file
                    with open(self.log_file, "a", encoding="utf-8") as f:
                        if stdout:
                            f.write(f"=== SkyPilot Launch Output ===\n{stdout}\n")
                        if stderr:
                            f.write(f"=== SkyPilot Launch Errors ===\n{stderr}\n")

                except Exception as e:
                    self.log_error(f"Deployment monitoring error: {e}")
                    success, stdout, stderr = self.run_sky_cmd(
                        "launch",
                        config_file,
                        "--name",
                        cluster_name,
                        "--yes",
                        timeout=600,
                    )
                finally:
                    # Wait a bit for final status updates
                    if monitor_thread and monitor_thread.is_alive():
                        time.sleep(3)
            else:
                # Default background mode - start deployment and return immediately
                self.console.print(
                    "🚀 [green]Starting deployment in background...[/green]"
                )
                self.console.print(f"📄 Logs: {self.log_file}")
                self.console.print(
                    "💡 [dim]Use 'amauo monitor --follow' to track progress[/dim]"
                )

                # Ensure log file directory exists
                self.log_file.parent.mkdir(parents=True, exist_ok=True)

                # Start SkyPilot deployment in background using detached docker exec
                cmd = [
                    "docker",
                    "exec",
                    "-d",
                    self.docker_container,
                    "sky",
                    "launch",
                    config_file,
                    "--name",
                    cluster_name,
                    "--yes",
                ]

                try:
                    # Start the process in detached mode (-d flag to docker exec)
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, check=False
                    )

                    if result.returncode == 0:
                        success = True
                        self.console.print(
                            "✅ [green]Deployment started successfully![/green]"
                        )
                        # Write initial log entry
                        with open(self.log_file, "a", encoding="utf-8") as f:
                            f.write("=== Deployment Started ===\n")
                            f.write(f"Cluster: {cluster_name}\n")
                            f.write(f"Config: {config_file}\n")
                            f.write(f"Started at: {datetime.now().isoformat()}\n")
                            f.write(
                                "Use 'amauo monitor --follow' to track progress\n\n"
                            )
                    else:
                        success = False
                        self.console.print("❌ [red]Failed to start deployment[/red]")
                        if result.stderr:
                            self.console.print(f"[red]Error: {result.stderr}[/red]")

                except Exception as e:
                    success = False
                    self.console.print(f"❌ [red]Failed to start deployment: {e}[/red]")

            if success:
                if not follow:
                    # Background mode - deployment started, not completed
                    self.log_success(f"Deployment started for cluster '{cluster_name}'")
                    self.console.print(
                        "\n💡 [dim]Deployment is running in background[/dim]"
                    )
                    self.console.print(
                        "🔍 [dim]Use 'amauo monitor' to check status[/dim]"
                    )
                    self.console.print(
                        "📋 [dim]Use 'amauo monitor --follow' for live updates[/dim]"
                    )
                else:
                    # Follow mode - deployment completed
                    self.log_success(f"Cluster '{cluster_name}' deployed successfully!")
                    self._show_completion_banner()
                return True
            else:
                self.log_error(
                    "Deployment failed to start" if not follow else "Deployment failed"
                )
                return False

        except Exception as e:
            self.log_error(f"Deployment failed with exception: {e}")
            return False

    def _show_completion_banner(self) -> None:
        """Show deployment completion banner."""
        self.console.print()
        self.console.print(
            "┌─────────────────────────────────────────────────┐", style="green"
        )
        self.console.print(
            "│               🎉 Deployment Complete            │", style="green"
        )
        self.console.print(
            "├─────────────────────────────────────────────────┤", style="green"
        )
        self.console.print(
            "│ Next Steps:                                     │", style="green"
        )
        self.console.print(
            "│ • Check status: uvx spot-deployer status   │", style="green"
        )
        self.console.print(
            "│ • List nodes: uvx spot-deployer list       │", style="green"
        )
        self.console.print(
            "│ • SSH to cluster: uvx spot-deployer ssh    │", style="green"
        )
        self.console.print(
            "│ • View logs: uvx spot-deployer logs        │", style="green"
        )
        self.console.print(
            "│ • Destroy cluster: uvx spot-deployer destroy│", style="green"
        )
        self.console.print(
            "└─────────────────────────────────────────────────┘", style="green"
        )
        self.console.print()

    def show_status(self) -> bool:
        """Show cluster status."""
        self.log_header("Cluster Status")
        success, stdout, stderr = self.run_sky_cmd("status")
        if success:
            if stdout:
                print(stdout)
            return True
        else:
            self.log_error("Failed to get cluster status")
            if stderr:
                self.log_error(f"SkyPilot error: {stderr}")
            return False

    def list_nodes(self) -> bool:
        """Show detailed node information in a table."""
        cluster_name = self.get_sky_cluster_name()
        if not cluster_name:
            self.log_error("No running cluster found")
            return False

        self.log_header(f"Cluster Nodes: {cluster_name}")

        # Get cluster info
        success, stdout, stderr = self.run_sky_cmd("status", cluster_name, timeout=10)
        if not success:
            self.log_error("Failed to get cluster information")
            if "timed out" in stderr:
                self.log_error("SkyPilot status command timed out. This may indicate:")
                self.log_error("  - AWS credential issues (try: aws sso login)")
                self.log_error("  - SkyPilot server problems")
                self.log_error("  - Network connectivity issues")
            elif stderr:
                self.log_error(f"SkyPilot error: {stderr}")
            return False

        # Parse launch time
        launch_time = "unknown"
        if stdout:
            for line in stdout.split("\n"):
                if cluster_name in line:
                    parts = line.split()
                    if len(parts) >= 8:
                        launch_time = " ".join(parts[5:8])
                    break

        # Get number of nodes from config
        try:
            config = self.load_cluster_config()
            num_nodes = config.get("num_nodes", 9)
        except Exception:
            num_nodes = 9

        # Create table
        table = Table(title=f"Cluster: {cluster_name}")
        table.add_column("Node", style="cyan")
        table.add_column("Instance ID", style="magenta")
        table.add_column("Public IP", style="green")
        table.add_column("Zone", style="yellow")
        table.add_column("Launched", style="blue")

        # Try to get real node information from recent logs first
        nodes_info = self._extract_node_info_from_logs()

        if nodes_info:
            # Show real node data from logs
            for node_id, info in nodes_info.items():
                table.add_row(
                    info.get("node", node_id),
                    f"rank-{info.get('rank', '?')}",
                    f"{info.get('ip', 'unknown')} (private)",
                    "AWS VPC",
                    launch_time,
                )
        else:
            # Fallback: try to get node info from status output
            status_nodes = self._extract_nodes_from_status(stdout)
            if status_nodes:
                for i, node_info in enumerate(status_nodes):
                    table.add_row(
                        f"worker-{i}",
                        node_info.get("instance_id", "unknown"),
                        node_info.get("public_ip", "unknown"),
                        node_info.get("zone", "unknown"),
                        launch_time,
                    )
            else:
                # Last resort: generic info with explanatory message
                for i in range(num_nodes):
                    table.add_row(
                        f"worker-{i}",
                        "cluster-running",
                        "see-sky-status",
                        "distributed",
                        launch_time,
                    )
                self.console.print(
                    "\n[yellow]ℹ️  Use 'sky status cluster-name' for detailed instance information[/yellow]"
                )

        self.console.print(table)
        self.console.print(f"\n[green]Total nodes: {num_nodes}[/green]")
        self.console.print("[green]Cluster status: UP[/green]")

        return True

    def ssh_cluster(self) -> bool:
        """SSH to cluster head node."""
        cluster_name = self.get_sky_cluster_name()
        if not cluster_name:
            self.log_error("No running cluster found")
            return False

        self.log_info(f"Connecting to head node of cluster: {cluster_name}")

        # Use interactive docker exec to SSH
        try:
            cmd = ["docker", "exec", "-it", self.docker_container, "ssh", cluster_name]
            result = subprocess.run(cmd, check=False)
            return result.returncode == 0
        except Exception as e:
            self.log_error(f"SSH failed: {e}")
            return False

    def show_logs(self) -> bool:
        """Show cluster logs."""
        cluster_name = self.get_sky_cluster_name()
        if not cluster_name:
            self.log_error("No running cluster found")
            return False

        self.log_info(f"Showing logs for cluster: {cluster_name}")
        success, stdout, stderr = self.run_sky_cmd("logs", cluster_name, timeout=30)
        if success:
            if stdout:
                print(stdout)
            return True
        else:
            self.log_error("Failed to get cluster logs")
            if stderr:
                self.log_error(f"SkyPilot error: {stderr}")
            return False

    def destroy_cluster(self) -> bool:
        """Destroy the cluster."""
        cluster_name = self.get_sky_cluster_name()
        if not cluster_name:
            self.log_info("No running cluster found to destroy")
            return True

        self.log_header(f"Destroying Cluster: {cluster_name}")
        self.log_warning("This will terminate all instances and delete all data!")

        success, stdout, stderr = self.run_sky_cmd(
            "down", cluster_name, "--yes", timeout=300
        )
        if success:
            if stdout and "not found" in stdout:
                self.log_info(f"Cluster '{cluster_name}' does not exist")
            else:
                self.log_success(f"Cluster '{cluster_name}' destroyed")
            return True
        else:
            self.log_error("Failed to destroy cluster")
            if stderr:
                self.log_error(f"SkyPilot error: {stderr}")
            return False

    def monitor_deployments(self, follow: bool = False) -> bool:
        """Monitor active deployments and cluster health."""
        try:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.console.print(
                f"\n🔍 [bold cyan]Deployment Health Monitor[/bold cyan] [dim]({current_time})[/dim]\n"
            )

            # Check if SkyPilot container is running
            if not self.ensure_docker_container():
                self.log_error("SkyPilot container not available")
                return False

            # Get cluster status
            success, stdout, stderr = self.run_sky_cmd("status")
            if not success:
                self.log_error(f"Failed to get cluster status: {stderr}")
                return False

            # Parse and display cluster information
            lines = stdout.split("\n")
            clusters_found = []

            # Find cluster information
            in_clusters_section = False
            for line in lines:
                if "NAME" in line and "INFRA" in line and "RESOURCES" in line:
                    in_clusters_section = True
                    continue
                elif in_clusters_section and line.strip():
                    # Stop if we hit another section
                    if line.startswith("Managed jobs") or line.startswith("Services"):
                        break
                    # Look for cluster lines (they contain status info)
                    if any(
                        status in line for status in ["INIT", "UP", "STOPPED", "DOWN"]
                    ):
                        clusters_found.append(line.strip())

            if not clusters_found:
                self.console.print("✅ [green]No active clusters found[/green]")
                return True

            # Display cluster status
            self.console.print("📊 [bold]Active Clusters:[/bold]")
            for cluster_line in clusters_found:
                parts = cluster_line.split()
                if len(parts) >= 3:
                    name = parts[0]

                    # Find status in the line
                    if "INIT" in cluster_line:
                        status_color = "yellow"
                        status_icon = "🔄"
                        health = "Initializing"
                    elif "UP" in cluster_line:
                        status_color = "green"
                        status_icon = "✅"
                        health = "Running"
                    elif "STOPPED" in cluster_line:
                        status_color = "red"
                        status_icon = "⏹️"
                        health = "Stopped"
                    else:
                        status_color = "gray"
                        status_icon = "❓"
                        health = "Unknown"

                    # Extract infrastructure and resources
                    infra = parts[1] if len(parts) > 1 else "Unknown"
                    resources_start = (
                        cluster_line.find(parts[2]) if len(parts) > 2 else -1
                    )
                    status_start = (
                        cluster_line.rfind("INIT")
                        if "INIT" in cluster_line
                        else cluster_line.rfind("UP")
                        if "UP" in cluster_line
                        else -1
                    )

                    if resources_start != -1 and status_start != -1:
                        resources = cluster_line[resources_start:status_start].strip()
                    elif len(parts) > 2:
                        resources = parts[2]
                    else:
                        resources = "Unknown"

                    self.console.print(
                        f"  {status_icon} [{status_color}]{name}[/{status_color}] - {health}"
                    )
                    self.console.print(f"     Infrastructure: {infra}")
                    self.console.print(f"     Resources: {resources}")

            # Check for managed jobs
            job_success, job_stdout, job_stderr = self.run_sky_cmd("jobs", "queue")
            if job_success and "No in-progress managed jobs" not in job_stdout:
                self.console.print("\n⚡ [bold]Active Managed Jobs:[/bold]")
                job_lines = job_stdout.split("\n")
                for line in job_lines:
                    if line.strip() and "job" in line.lower():
                        self.console.print(f"  🔄 {line.strip()}")

            # If following, monitor continuously
            if follow:
                self.console.print(
                    "\n👀 [dim]Monitoring continuously (Ctrl+C to exit)...[/dim]"
                )

                # Use the existing streaming monitor but for active clusters
                active_cluster = None
                for cluster_line in clusters_found:
                    if "INIT" in cluster_line:
                        parts = cluster_line.split()
                        active_cluster = parts[0]
                        break

                if active_cluster:
                    self.console.print(
                        f"🔍 [blue]Following deployment of: {active_cluster}[/blue]"
                    )
                    self._monitor_deployment_progress_streaming(active_cluster)
                else:
                    # Just refresh status periodically
                    import time

                    while True:
                        time.sleep(5)
                        # Re-run status check
                        success, stdout, stderr = self.run_sky_cmd("status")
                        if success:
                            timestamp = time.strftime("%H:%M:%S")
                            self.console.print(
                                f"[dim]{timestamp} - Cluster status updated[/dim]"
                            )

            return True

        except KeyboardInterrupt:
            self.console.print("\n[yellow]⚠️  Monitoring stopped by user[/yellow]")
            return True
        except Exception as e:
            self.log_error(f"Monitoring failed: {e}")
            return False

    def cleanup_docker(self) -> bool:
        """Clean up Docker container."""
        try:
            result = subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    f"name={self.docker_container}",
                    "--quiet",
                ],
                capture_output=True,
                check=False,
            )

            if result.stdout.strip():
                self.log_info("Stopping SkyPilot Docker container...")
                subprocess.run(
                    ["docker", "stop", self.docker_container],
                    capture_output=True,
                    check=False,
                )
                self.log_success("Docker container stopped")

            return True
        except Exception as e:
            self.log_error(f"Failed to cleanup Docker container: {e}")
            return False
