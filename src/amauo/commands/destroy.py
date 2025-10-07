"""Destroy command with full Rich UI and concurrent operations."""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from logging import Logger
from threading import Lock
from typing import Any, Optional

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from ..core.config import SimpleConfig
from ..core.state import SimpleStateManager
from ..utils.aws import check_aws_auth
from ..utils.logging import setup_logger
from ..utils.shutdown_handler import ShutdownContext
from ..utils.ui_manager import UIManager


class DestroyManager:
    """Manages instance destruction with live Rich updates."""

    def __init__(
        self,
        config: SimpleConfig,
        state: SimpleStateManager,
        console: Console,
        debug: bool = False,
    ):
        self.config = config
        self.state = state
        self.console = console
        self.debug = debug
        self.logger: Optional[Logger] = None
        self.status_lock = Lock()
        self.instance_status: dict[str, dict[str, Any]] = {}
        self.start_time = datetime.now()
        self.ui_manager = UIManager(console)

    def initialize_logger(self) -> Optional[str]:
        """Set up logging."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"amauo_destroy_{timestamp}.log" if self.debug else None
        self.logger = setup_logger("amauo_destroyer", log_filename)
        return log_filename

    def update_status(
        self, instance_id: str, region: str, status: str, detail: str = ""
    ) -> None:
        """Thread-safe status update."""
        with self.status_lock:
            self.instance_status[instance_id] = {
                "region": region,
                "status": status,
                "detail": detail,
                "timestamp": datetime.now(),
            }
            if self.logger:
                self.logger.info(f"[{instance_id}] {status} {detail}")

    def create_status_table(self) -> Table:
        """Create the status table for display."""
        table = self.ui_manager.create_instance_table(
            title="Instance Destruction Status", header_style="bold red"
        )

        # Sort by region for consistent display
        sorted_instances = sorted(
            self.instance_status.items(), key=lambda x: (x[1]["region"], x[0])
        )

        for instance_id, info in sorted_instances:
            # Use UI manager to format status
            status_display = self.ui_manager.format_status(
                info["status"], info["detail"]
            )

            # Add row with all available data
            self.ui_manager.add_instance_row(
                table,
                info["region"],
                instance_id,
                status_display,
                info.get("type", "unknown"),
                info.get("public_ip", "N/A"),
                info.get("created", "N/A"),
            )

        return table

    def create_summary_panel(self) -> Panel:
        """Create summary panel showing progress."""
        elapsed = (datetime.now() - self.start_time).total_seconds()

        # Count statuses
        total = len(self.instance_status)
        completed = sum(1 for s in self.instance_status.values() if "✓" in s["status"])
        failed = sum(1 for s in self.instance_status.values() if "✗" in s["status"])
        in_progress = total - completed - failed

        content = {
            "title": "Destruction Progress",
            "Total": f"{total} instances",
            "Completed": completed,
            "Failed": failed,
            "In Progress": in_progress,
            "Elapsed": f"{elapsed:.1f}s",
        }

        return self.ui_manager.create_progress_panel("Summary", content)

    def _check_aws_orphaned_instances(self) -> None:
        """Check AWS for any orphaned spot instances that aren't in state file."""
        try:
            from ..utils.aws_manager import AWSResourceManager

            regions_checked = 0
            orphaned_found = 0

            # Get all regions
            regions = self.config.regions()
            self.console.print(
                f"[dim]Scanning {len(regions)} regions: {', '.join(regions)}[/dim]"
            )

            # Check each region from config
            for region in regions:
                regions_checked += 1

                self.console.print(f"[dim]  • Checking {region}...[/dim]", end="")

                try:
                    aws_manager = AWSResourceManager(region)

                    # Look for instances with our tags (both old and new tag formats)
                    response = aws_manager.ec2.describe_instances(
                        Filters=[
                            {
                                "Name": "tag:ManagedBy",
                                "Values": [
                                    "Amauo",
                                    "amauo",
                                    "amauo",
                                    "aws-amauo",
                                ],
                            },
                            {
                                "Name": "instance-state-name",
                                "Values": ["running", "pending", "stopping", "stopped"],
                            },
                        ]
                    )

                    found_in_region = 0
                    for reservation in response.get("Reservations", []):
                        for instance in reservation.get("Instances", []):
                            orphaned_found += 1
                            found_in_region += 1
                            instance_id = instance.get("InstanceId", "Unknown")
                            state = instance.get("State", {}).get("Name", "unknown")
                            public_ip = instance.get("PublicIpAddress", "N/A")

                            if found_in_region == 1:
                                self.console.print("")  # New line after region check

                            self.console.print(
                                f"[yellow]    ⚠️  Found orphaned instance: "
                                f"{instance_id} ({state}) - IP: {public_ip}[/yellow]"
                            )

                            # Terminate the orphaned instance
                            if state not in ["terminated", "terminating"]:
                                self.console.print(
                                    f"[dim]    → Terminating {instance_id}...[/dim]"
                                )
                                try:
                                    aws_manager.ec2.terminate_instances(
                                        InstanceIds=[instance_id]
                                    )
                                    self.console.print(
                                        f"[green]    ✓ Terminated {instance_id}[/green]"
                                    )
                                    if self.logger:
                                        self.logger.info(
                                            f"Terminated orphaned instance {instance_id} in {region}"
                                        )
                                except Exception as e:
                                    self.console.print(
                                        f"[red]    ✗ Failed to terminate {instance_id}[/red]"
                                    )
                                    if self.logger:
                                        self.logger.error(
                                            f"Failed to terminate orphaned instance {instance_id}: {e}"
                                        )

                    if found_in_region == 0:
                        self.console.print(" [green]✓[/green]")

                except Exception as e:
                    self.console.print(" [red]✗[/red]")
                    if self.logger:
                        self.logger.debug(f"Error checking region {region}: {e}")

            self.console.print(f"[dim]Checked {regions_checked} regions[/dim]")

            if orphaned_found > 0:
                self.console.print(
                    f"\n[green]✅ Found and terminated {orphaned_found} orphaned instances[/green]"
                )

        except Exception as e:
            if self.logger:
                self.logger.error(f"Error checking for orphaned instances: {e}")

    def destroy_instance(self, instance: dict) -> bool:
        """Destroy a single instance and its resources."""
        instance_id = instance["id"]
        region = instance["region"]

        try:
            from ..utils.aws_manager import AWSResourceManager

            aws_manager = AWSResourceManager(region)
            ec2 = aws_manager.ec2

            # First check if instance exists
            instance_state = aws_manager.get_instance_state(instance_id)

            if instance_state in ["terminated", "terminating", "not-found"]:
                self.update_status(instance_id, region, "✓ Terminated", "Already gone")
                return True

            # Step 1: Terminate instance
            self.update_status(instance_id, region, "⏳ Terminating instance...")
            if not aws_manager.terminate_instance(instance_id):
                self.update_status(
                    instance_id, region, "✗ Failed", "Termination failed"
                )
                return False

            # Step 3: Check for VPC
            self.update_status(instance_id, region, "⏳ Checking VPC...")

            # Get instance details to find VPC
            try:
                response = ec2.describe_instances(InstanceIds=[instance_id])
                vpc_id = None
                for reservation in response.get("Reservations", []):
                    for inst in reservation.get("Instances", []):
                        vpc_id = inst.get("VpcId")
                        break

                if vpc_id:
                    # Check if it's a dedicated VPC
                    vpcs = ec2.describe_vpcs(VpcIds=[vpc_id])
                    for vpc in vpcs.get("Vpcs", []):
                        # Extract tags safely
                        tags = {}
                        for tag in vpc.get("Tags", []):
                            if "Key" in tag and "Value" in tag:
                                tags[tag["Key"]] = tag["Value"]
                        if tags.get("ManagedBy") == "amauo":
                            self.update_status(
                                instance_id, region, "⏳ Deleting VPC...", vpc_id
                            )
                            if aws_manager.delete_vpc_resources(vpc_id):
                                self.update_status(
                                    instance_id, region, "✓ Complete", "VPC deleted"
                                )
                            else:
                                self.update_status(
                                    instance_id,
                                    region,
                                    "✓ Complete",
                                    "VPC deletion failed",
                                )
                            return True

            except Exception:
                pass

            # No dedicated VPC, just mark as complete
            self.update_status(instance_id, region, "✓ Complete", "")
            return True

        except Exception as e:
            error_msg = str(e)
            if "InsufficientInstanceCapacity" in error_msg:
                error_msg = "No capacity"
            elif len(error_msg) > 30:
                error_msg = error_msg[:30] + "..."

            self.update_status(instance_id, region, "✗ Failed", error_msg)
            return False

    def run(self, verbose: bool = False) -> None:
        """Execute the destruction process."""
        # Check state file
        self.console.print("[dim]Checking local state file for instances...[/dim]")
        instances = self.state.load_instances()

        # Debug environment variables if verbose
        if verbose:
            self.console.print(f"""[dim]Environment variables:[/dim]
[dim]BACALHAU_API_HOST: {os.environ.get("BACALHAU_API_HOST", "NOT SET")}[/dim]
[dim]BACALHAU_API_KEY: {"SET" if os.environ.get("BACALHAU_API_KEY") else "NOT SET"}[/dim]
""")

        # If no instances to destroy, we're done
        if not instances:
            self.console.print("[yellow]ℹ️  No instances found in state file[/yellow]")
            self.console.print(
                "[dim]   State file exists but contains no instance records[/dim]"
            )

            # Also check AWS for any orphaned instances
            self.console.print(
                "\n[dim]Checking AWS for orphaned spot instances...[/dim]"
            )
            self._check_aws_orphaned_instances()
            return

        # Show what we found
        self.console.print(
            f"[green]Found {len(instances)} instances in state file[/green]"
        )

        # Group by region for summary
        instances_by_region: dict[str, Any] = {}
        for instance in instances:
            region = instance["region"]
            if region not in instances_by_region:
                instances_by_region[region] = []
            instances_by_region[region].append(instance)

        # Show summary by region
        for region, region_instances in instances_by_region.items():
            self.console.print(f"  • {region}: {len(region_instances)} instances")

        # Initialize status for all instances
        for instance in instances:
            self.instance_status[instance["id"]] = {
                "region": instance["region"],
                "status": "⏳ Queued",
                "detail": "",
                "timestamp": datetime.now(),
                "type": instance.get("type", "unknown"),
                "public_ip": instance.get("public_ip", "N/A"),
                "created": instance.get("created", "N/A"),
            }

        # Show warning (but no confirmation needed - user explicitly ran destroy)
        self.console.print(
            f"\n[bold red]🗑️  Terminating {len(instances)} instances...[/bold red]\n"
        )

        # Create layout
        def generate_layout() -> Layout:
            layout = Layout()
            layout.split_column(
                Layout(self.create_status_table(), ratio=4),
                Layout(self.create_summary_panel(), size=8),
            )
            return layout

        # Initialize logger
        log_filename = self.initialize_logger()

        # Process instances with max concurrency of 10
        with ShutdownContext("Saving instance destruction state...") as shutdown_ctx:
            # Define cleanup function
            def cleanup_on_shutdown() -> None:
                if self.logger:
                    self.logger.warning("Shutdown requested - saving current state...")
                # Save state with any instances that were successfully destroyed
                self.state.save_instances(self.state.load_instances())
                # Update status for any pending instances
                with self.status_lock:
                    for _instance_id, status in self.instance_status.items():
                        if "⏳" in status["status"]:
                            status["status"] = "⚠️ INTERRUPTED"
                            status["detail"] = "Shutdown requested"

            shutdown_ctx.add_cleanup(cleanup_on_shutdown)

            with Live(
                generate_layout(),
                refresh_per_second=4,
                console=self.console,
                screen=True,
                redirect_stdout=False,
            ) as live:
                with ThreadPoolExecutor(
                    max_workers=min(10, len(instances))
                ) as executor:
                    # Submit all tasks
                    future_to_instance = {
                        executor.submit(self.destroy_instance, instance): instance
                        for instance in instances
                        if not shutdown_ctx.shutdown_requested  # Don't submit new tasks if shutting down
                    }

                    # Process as they complete
                    for future in as_completed(future_to_instance):
                        if shutdown_ctx.shutdown_requested:
                            # Cancel remaining futures
                            for f in future_to_instance:
                                if not f.done():
                                    f.cancel()
                            break

                        instance = future_to_instance[future]
                        try:
                            success = future.result()
                            # Always remove from state if terminated or not found
                            if success or "Terminated" in self.instance_status.get(
                                instance["id"], {}
                            ).get("status", ""):
                                self.state.remove_instance(instance["id"])
                        except Exception as e:
                            # Still try to remove from state if instance doesn't exist
                            if "InvalidInstanceID" in str(e):
                                self.state.remove_instance(instance["id"])

                        # Update display
                        live.update(generate_layout())

                # Final update
                live.update(generate_layout())

        # Show summary
        total = len(instances)
        completed = sum(1 for s in self.instance_status.values() if "✓" in s["status"])
        failed = total - completed

        summary_lines = ["\n[bold]Destruction Summary:[/bold]"]
        if completed == total:
            summary_lines.append(
                f"[green]✅ All {total} instances destroyed successfully[/green]"
            )
        else:
            summary_lines.append(
                f"[yellow]⚠️  {completed}/{total} instances destroyed[/yellow]"
            )
            if failed > 0:
                summary_lines.append(f"[red]❌ {failed} instances failed[/red]")
        self.console.print("\n".join(summary_lines))

        self.console.print(f"\n[dim]Destruction log saved to: {log_filename}[/dim]")


def cmd_destroy(
    config: SimpleConfig,
    state: SimpleStateManager,
    verbose: bool = False,
    debug: bool = False,
) -> None:
    """Destroy all instances with enhanced UI."""
    if not check_aws_auth():
        return

    # Create console and let Rich handle terminal detection
    console = Console(
        force_terminal=True,
        force_interactive=True,
        legacy_windows=False,
    )
    manager = DestroyManager(config, state, console, debug=debug)
    manager.run(verbose=verbose)
