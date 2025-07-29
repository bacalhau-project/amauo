"""List command implementation."""

from concurrent.futures import ThreadPoolExecutor

import boto3

from ..core.state import SimpleStateManager
from ..utils.aws import check_aws_auth
from ..utils.display import RICH_AVAILABLE, console, rich_print
from ..utils.tables import add_instance_row, create_instance_table


def get_instance_state(instance_id: str, region: str) -> str:
    """Get current state of an instance from AWS."""
    try:
        ec2 = boto3.client("ec2", region_name=region)
        response = ec2.describe_instances(InstanceIds=[instance_id])

        for reservation in response.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                return instance.get("State", {}).get("Name", "unknown")

        return "not-found"
    except Exception:
        return "error"


def cmd_list(state: SimpleStateManager) -> None:
    """List running instances with live state from AWS."""
    if not check_aws_auth():
        return

    instances = state.load_instances()
    if not instances:
        rich_print("No instances found in state file.", style="yellow")
        return

    # Show status while fetching
    if RICH_AVAILABLE and console:
        console.print("[dim]Fetching current instance states from AWS...[/dim]")

    # Update instance states from AWS in parallel
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Create a mapping of futures to instances
        future_to_instance = {
            executor.submit(get_instance_state, inst["id"], inst["region"]): inst
            for inst in instances
        }

        # Update states as futures complete
        for future in future_to_instance:
            instance = future_to_instance[future]
            try:
                current_state = future.result()
                instance["state"] = current_state
            except Exception:
                instance["state"] = "error"

    if RICH_AVAILABLE and console:
        table = create_instance_table(title="Running Spot Instances")

        for inst in sorted(instances, key=lambda i: i.get("region", "")):
            instance_state = inst.get("state", "unknown")

            # Keep status display simple
            state_display = instance_state

            add_instance_row(
                table,
                inst.get("region", "unknown"),
                inst.get("id", "unknown"),
                state_display,
                inst.get("type", "unknown"),
                inst.get("public_ip", "N/A"),
                inst.get("created", "unknown"),
            )

        console.print(table)
    else:
        # Fallback to basic output
        print(f"\nTotal instances: {len(instances)}")
        for inst in instances:
            print(
                f"  {inst.get('region', 'unknown')}: "
                f"{inst.get('id', 'unknown')} "
                f"({inst.get('public_ip', 'no-ip')})"
            )
