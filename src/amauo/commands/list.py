"""List command for spot-deployer - shows instances from local state."""

import boto3
from botocore.exceptions import ClientError

from ..core.state import SimpleStateManager
from ..utils.display import RICH_AVAILABLE, console, rich_print
from ..utils.tables import add_instance_row, create_instance_table


def get_instance_status(instance_id: str, region: str) -> str:
    """Get the current status of an instance from AWS."""
    try:
        ec2 = boto3.client("ec2", region_name=region)
        response = ec2.describe_instances(InstanceIds=[instance_id])
        if response["Reservations"] and response["Reservations"][0]["Instances"]:
            return response["Reservations"][0]["Instances"][0]["State"]["Name"]
    except (ClientError, KeyError):
        pass
    return "unknown"


def cmd_list(state: SimpleStateManager, refresh: bool = False) -> None:
    """List instances from local state file, optionally refreshing status from AWS.

    Args:
        state: State manager instance
        refresh: If True, query AWS for current instance status
    """

    # Load instances from local state
    instances = state.load_instances()
    if not instances:
        rich_print("No instances found in state file.", style="yellow")
        return

    # Create and display table
    if RICH_AVAILABLE and console:
        # Create table with proper title
        table = create_instance_table(title="Instances from Local State")

        # Add all instances to table
        for instance in instances:
            # Get status - either from AWS or show as unknown
            if refresh:
                status = get_instance_status(instance["id"], instance["region"])
            else:
                status = instance.get("state", "unknown")
                # Translate internal states to user-friendly status
                if status == "deployed":
                    status = "✅ Deployed"
                elif status == "provisioned":
                    status = "⏳ Provisioning"
                elif status == "complete":
                    status = "✅ Deployed"

            add_instance_row(
                table,
                region=instance["region"],
                instance_id=instance["id"],  # Changed from instance_id to id
                status=status,
                instance_type=instance.get(
                    "type", "unknown"
                ),  # Changed from instance_type to type
                public_ip=instance.get("public_ip", "pending"),
                created=instance.get(
                    "created", "unknown"
                ),  # Changed from created_at to created
                upload_status=instance.get("upload_status", "-"),
            )

        # Display the table
        console.print(table)

        # Show summary
        total = len(instances)
        regions = len({i["region"] for i in instances})
        rich_print(
            f"\n[green]Total: {total} instances across {regions} regions[/green]"
        )
    else:
        # Simple text output
        print(f"\nInstances ({len(instances)} total):")
        print("-" * 60)
        for instance in instances:
            print(
                f"  • {instance['region']}: {instance['id']} - {instance.get('public_ip', 'pending')}"
            )
        print()
