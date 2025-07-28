"""Nuke command - finds and destroys ALL spot instances across all regions."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

import boto3
from botocore.exceptions import ClientError

from ..core.config import SimpleConfig
from ..core.state import SimpleStateManager
from ..utils.aws import check_aws_auth
from ..utils.display import console, rich_error, rich_success

# AWS regions to scan
AWS_REGIONS = [
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
    "eu-west-1",
    "eu-west-2",
    "eu-west-3",
    "eu-central-1",
    "eu-north-1",
    "ap-northeast-1",
    "ap-northeast-2",
    "ap-northeast-3",
    "ap-southeast-1",
    "ap-southeast-2",
    "ap-south-1",
    "ca-central-1",
    "sa-east-1",
    "me-south-1",
    "af-south-1",
    "ap-east-1",
]


def find_spot_instances_in_region(region: str) -> List[Dict[str, str]]:
    """Find all spot instances in a specific region."""
    try:
        ec2 = boto3.client("ec2", region_name=region)

        # Find all instances with lifecycle=spot
        response = ec2.describe_instances(
            Filters=[
                {"Name": "instance-lifecycle", "Values": ["spot"]},
                {
                    "Name": "instance-state-name",
                    "Values": ["pending", "running", "stopping", "stopped"],
                },
            ]
        )

        instances = []
        for reservation in response["Reservations"]:
            for instance in reservation["Instances"]:
                instances.append(
                    {
                        "id": instance["InstanceId"],
                        "region": region,
                        "state": instance["State"]["Name"],
                        "type": instance.get("InstanceType", "unknown"),
                        "public_ip": instance.get("PublicIpAddress", "N/A"),
                        "launch_time": str(instance.get("LaunchTime", "unknown")),
                        "tags": {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])},
                    }
                )

        return instances
    except ClientError as e:
        if e.response["Error"]["Code"] == "UnauthorizedOperation":
            # Skip regions where we don't have access
            return []
        raise


def terminate_instances_in_region(region: str, instance_ids: List[str]) -> Dict[str, str]:
    """Terminate instances in a specific region."""
    if not instance_ids:
        return {}

    try:
        ec2 = boto3.client("ec2", region_name=region)

        # Terminate instances
        response = ec2.terminate_instances(InstanceIds=instance_ids)

        # Extract termination status
        results = {}
        for inst in response["TerminatingInstances"]:
            results[inst["InstanceId"]] = inst["CurrentState"]["Name"]

        return results
    except Exception as e:
        # Return error status for all instances
        return {inst_id: f"ERROR: {str(e)}" for inst_id in instance_ids}


def cmd_nuke(state: SimpleStateManager, config: SimpleConfig, force: bool = False) -> None:
    """Find and destroy ALL spot instances across all AWS regions."""
    if not check_aws_auth():
        return

    console.print("\n[bold red]🚨 NUCLEAR OPTION - DESTROY ALL SPOT INSTANCES 🚨[/bold red]\n")
    console.print("[yellow]This command will:[/yellow]")
    console.print("  • Scan ALL AWS regions for spot instances")
    console.print("  • Terminate ALL spot instances found")
    console.print("  • This includes instances NOT managed by this tool\n")

    if not force:
        console.print("[bold red]Are you ABSOLUTELY sure?[/bold red]")
        confirmation = input("Type 'DESTROY ALL SPOTS' to confirm: ")
        if confirmation != "DESTROY ALL SPOTS":
            rich_error("Aborted. No instances were terminated.")
            return

    # Phase 1: Scan all regions for spot instances
    console.print("\n[cyan]Phase 1: Scanning all AWS regions for spot instances...[/cyan]")

    all_instances = []
    region_errors = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all region scans
        future_to_region = {
            executor.submit(find_spot_instances_in_region, region): region for region in AWS_REGIONS
        }

        # Process results as they complete
        for future in as_completed(future_to_region):
            region = future_to_region[future]
            try:
                instances = future.result()
                if instances:
                    all_instances.extend(instances)
                    console.print(
                        f"  [green]✓[/green] {region}: Found {len(instances)} spot instances"
                    )
                else:
                    console.print(f"  [dim]✓[/dim] {region}: No spot instances")
            except Exception as e:
                region_errors.append((region, str(e)))
                console.print(f"  [red]✗[/red] {region}: Error - {str(e)}")

    if region_errors:
        console.print(f"\n[yellow]⚠️  Failed to scan {len(region_errors)} regions[/yellow]")

    if not all_instances:
        rich_success("No spot instances found in any region!")
        return

    # Display found instances
    console.print(f"\n[bold]Found {len(all_instances)} spot instances:[/bold]\n")

    # Group by region for display
    by_region = {}
    for inst in all_instances:
        region = inst["region"]
        if region not in by_region:
            by_region[region] = []
        by_region[region].append(inst)

    for region, instances in sorted(by_region.items()):
        console.print(f"\n[bold]{region}:[/bold]")
        for inst in instances:
            tags_str = ", ".join(f"{k}={v}" for k, v in inst["tags"].items() if k != "Name")
            name_tag = inst["tags"].get("Name", "")
            if name_tag:
                name_str = f" [cyan]({name_tag})[/cyan]"
            else:
                name_str = ""

            console.print(
                f"  • {inst['id']}{name_str} - {inst['type']} - "
                f"{inst['state']} - {inst['public_ip']} - "
                f"[dim]{inst['launch_time']}[/dim]"
            )
            if tags_str:
                console.print(f"    [dim]Tags: {tags_str}[/dim]")

    # Phase 2: Confirm and terminate
    console.print(f"\n[bold red]About to terminate {len(all_instances)} instances![/bold red]")

    if not force:
        final_confirm = input("Type 'YES' to proceed with termination: ")
        if final_confirm != "YES":
            rich_error("Aborted. No instances were terminated.")
            return

    console.print("\n[cyan]Phase 2: Terminating instances...[/cyan]")

    # Group instances by region for termination
    termination_groups = {}
    for inst in all_instances:
        region = inst["region"]
        if region not in termination_groups:
            termination_groups[region] = []
        termination_groups[region].append(inst["id"])

    terminated_count = 0
    failed_count = 0

    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit termination requests
        future_to_region = {
            executor.submit(terminate_instances_in_region, region, instance_ids): region
            for region, instance_ids in termination_groups.items()
        }

        # Process results
        for future in as_completed(future_to_region):
            region = future_to_region[future]
            try:
                results = future.result()
                success = sum(1 for status in results.values() if "ERROR" not in status)
                failed = len(results) - success

                terminated_count += success
                failed_count += failed

                if failed > 0:
                    console.print(
                        f"  [yellow]⚠[/yellow] {region}: {success} terminated, {failed} failed"
                    )
                    for inst_id, status in results.items():
                        if "ERROR" in status:
                            console.print(f"    [red]✗[/red] {inst_id}: {status}")
                else:
                    console.print(f"  [green]✓[/green] {region}: {success} instances terminated")

            except Exception as e:
                console.print(f"  [red]✗[/red] {region}: Failed - {str(e)}")
                failed_count += len(termination_groups[region])

    # Summary
    console.print("\n" + "=" * 60)
    console.print("\n[bold]NUKE COMPLETE:[/bold]")
    console.print(f"  [green]✅ Terminated: {terminated_count} instances[/green]")
    if failed_count > 0:
        console.print(f"  [red]❌ Failed: {failed_count} instances[/red]")

    # Update local state to remove any terminated instances
    if terminated_count > 0:
        console.print("\n[dim]Updating local state...[/dim]")
        current_instances = state.load_instances()
        terminated_ids = {
            inst["id"]
            for inst in all_instances
            if inst["id"]
            not in [i for r in future_to_region.values() for i in termination_groups.get(r, [])]
        }
        remaining_instances = [
            inst for inst in current_instances if inst["id"] not in terminated_ids
        ]
        state.save_instances(remaining_instances)
        console.print("[dim]Local state updated.[/dim]")

    console.print("\n[bold green]🏁 Nuke operation completed![/bold green]\n")
