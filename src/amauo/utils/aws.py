"""AWS-specific utility functions."""

import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Optional, cast

import boto3

from ..core.constants import (
    CACHE_DIR,
    CANONICAL_OWNER_ID,
    DEFAULT_CACHE_AGE_HOURS,
    DEFAULT_UBUNTU_AMI_PATTERN,
)
from .display import rich_error

logger = logging.getLogger(__name__)

# Global AMI cache
AMI_CACHE: dict[str, str] = {}
CACHE_LOCK = threading.Lock()


def cache_file_fresh(
    filepath: str, max_age_hours: int = DEFAULT_CACHE_AGE_HOURS
) -> bool:
    """Check if cache file is fresh."""
    if not os.path.exists(filepath):
        return False
    age_hours = (time.time() - os.path.getmtime(filepath)) / 3600
    return age_hours < max_age_hours


def load_cache(filepath: str) -> Optional[dict]:
    """Load data from cache file."""
    if cache_file_fresh(filepath):
        try:
            with open(filepath) as f:
                return cast(Optional[dict[Any, Any]], json.load(f))
        except Exception:
            pass
    return None


def save_cache(filepath: str, data: dict) -> None:
    """Save data to cache file."""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception:
        pass


def get_latest_ubuntu_ami(
    region: str, log_function: Optional[Any] = None, cache_dir: Optional[str] = None
) -> Optional[str]:
    """Get latest Ubuntu 24.04 LTS AMI for region."""
    if cache_dir is None:
        cache_dir = os.environ.get("SPOT_OUTPUT_DIR", CACHE_DIR)
        if cache_dir != CACHE_DIR:
            cache_dir = os.path.join(cache_dir, ".aws_cache")
    cache_file = f"{cache_dir}/ami_{region}.json"

    def log_message(msg: str) -> None:
        if log_function:
            log_function(msg)
        else:
            logger.info(msg)

    # Check memory cache first (fastest)
    with CACHE_LOCK:
        if region in AMI_CACHE:
            log_message(f"Using memory-cached AMI for {region}: {AMI_CACHE[region]}")
            return AMI_CACHE[region]

    # Try file cache second
    cached = load_cache(cache_file)
    if cached and "ami_id" in cached:
        log_message(f"Using file-cached AMI for {region}: {cached['ami_id']}")
        # Also store in memory cache
        with CACHE_LOCK:
            AMI_CACHE[region] = cached["ami_id"]
        return cast(Optional[str], cached["ami_id"])

    # Fetch from AWS
    try:
        log_message(f"Fetching AMI for {region}...")
        ec2 = boto3.client("ec2", region_name=region)
        response = ec2.describe_images(
            Owners=[CANONICAL_OWNER_ID],  # Canonical
            Filters=[
                {
                    "Name": "name",
                    "Values": [DEFAULT_UBUNTU_AMI_PATTERN],
                },
                {"Name": "state", "Values": ["available"]},
            ],
        )

        log_message(
            f"AMI response for {region}: {len(response.get('Images', []))} images found"
        )

        if response["Images"]:
            # Sort by creation date to get latest
            images = sorted(
                response["Images"], key=lambda x: x["CreationDate"], reverse=True
            )
            ami_id = images[0]["ImageId"]
            log_message(f"Found AMI for {region}: {ami_id}")
            # Cache result
            save_cache(
                cache_file, {"ami_id": ami_id, "timestamp": datetime.now().isoformat()}
            )
            # Store in memory cache
            with CACHE_LOCK:
                AMI_CACHE[region] = ami_id
            return ami_id
        else:
            log_message(f"No Ubuntu AMIs found for {region}")
    except Exception as e:
        log_message(f"Error getting AMI for {region}: {e}")

    return None


def check_aws_auth() -> bool:
    """Check AWS authentication and display which credentials are being used."""
    try:
        sts = boto3.client("sts")
        caller_identity = sts.get_caller_identity()

        # Get the ARN and extract useful information
        arn = caller_identity.get("Arn", "")
        account = caller_identity.get("Account", "unknown")

        # Determine the type of credentials being used
        if "assumed-role" in arn:
            # SSO or assumed role
            role_name = arn.split("/")[-2] if "/" in arn else "unknown"
            user_name = arn.split("/")[-1] if "/" in arn else "unknown"
            cred_type = "AWS SSO/AssumedRole"
            cred_info = f"{role_name} (user: {user_name})"
        elif ":user/" in arn:
            # IAM user
            user_name = arn.split("/")[-1] if "/" in arn else "unknown"
            cred_type = "IAM User"
            cred_info = user_name
        elif "arn:aws:iam::" in arn and ":root" in arn:
            # Root account (not recommended)
            cred_type = "Root Account"
            cred_info = "⚠️  WARNING: Using root credentials"
        else:
            # Environment credentials or other
            cred_type = "AWS Credentials"
            cred_info = "from environment or config"

        # Display the authentication information
        from .display import console

        if console:
            # Just print simple message, don't build unused panel
            console.print(
                f"✓ AWS Auth: {cred_type} - {cred_info} (Account: {account})",
                style="green",
            )
        else:
            logger.info(f"✓ AWS Auth: {cred_type} - {cred_info} (Account: {account})")

        return True
    except Exception as e:
        if "token has expired" in str(e).lower():
            rich_error("AWS credentials expired. Run: aws sso login")
        else:
            rich_error(f"AWS authentication failed: {e}")
        return False


def create_simple_security_group(
    ec2: Any, vpc_id: str, group_name: str = "amauo-sg"
) -> str:
    """Create basic security group."""
    try:
        # Check for existing security group
        response = ec2.describe_security_groups(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "group-name", "Values": [group_name]},
            ]
        )

        if response["SecurityGroups"]:
            return cast(str, response["SecurityGroups"][0]["GroupId"])

        # Create new security group
        response = ec2.create_security_group(
            GroupName=group_name,
            Description="Simple security group for spot instances",
            VpcId=vpc_id,
        )
        sg_id = cast(str, response["GroupId"])

        # Add basic rules
        ec2.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                },
                {
                    "IpProtocol": "tcp",
                    "FromPort": 80,
                    "ToPort": 80,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                },
                {
                    "IpProtocol": "tcp",
                    "FromPort": 443,
                    "ToPort": 443,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                },
                {
                    "IpProtocol": "tcp",
                    "FromPort": 1234,
                    "ToPort": 1234,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                },
                {
                    "IpProtocol": "tcp",
                    "FromPort": 4222,
                    "ToPort": 4222,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                },
            ],
        )

        return sg_id
    except Exception as e:
        logger.error(f"Error creating security group: {e}")
        raise


def create_deployment_vpc(
    ec2_client: Any, region: str, deployment_id: Optional[str] = None
) -> tuple[str, str, str]:
    """
    Create a dedicated VPC for spot deployment with all necessary components.

    Returns: (vpc_id, subnet_id, internet_gateway_id)
    """
    if not deployment_id:
        deployment_id = f"spot-deploy-{int(time.time())}"

    try:
        # Create VPC with a /16 CIDR block
        vpc_response = ec2_client.create_vpc(CidrBlock="10.0.0.0/16")
        vpc_id = vpc_response["Vpc"]["VpcId"]

        # Wait for VPC to be available
        waiter = ec2_client.get_waiter("vpc_available")
        waiter.wait(VpcIds=[vpc_id])

        # Enable DNS hostnames for the VPC
        ec2_client.modify_vpc_attribute(
            VpcId=vpc_id, EnableDnsHostnames={"Value": True}
        )

        # Tag the VPC
        ec2_client.create_tags(
            Resources=[vpc_id],
            Tags=[
                {"Key": "Name", "Value": f"amauo-{region}"},
                {"Key": "ManagedBy", "Value": "amauo"},
                {"Key": "DeploymentId", "Value": deployment_id},
            ],
        )

        # Create subnet in the first availability zone
        azs = ec2_client.describe_availability_zones(
            Filters=[{"Name": "state", "Values": ["available"]}]
        )
        first_az = azs["AvailabilityZones"][0]["ZoneName"]

        subnet_response = ec2_client.create_subnet(
            VpcId=vpc_id, CidrBlock="10.0.1.0/24", AvailabilityZone=first_az
        )
        subnet_id = subnet_response["Subnet"]["SubnetId"]

        # Enable auto-assign public IP on subnet
        ec2_client.modify_subnet_attribute(
            SubnetId=subnet_id, MapPublicIpOnLaunch={"Value": True}
        )

        # Tag the subnet
        ec2_client.create_tags(
            Resources=[subnet_id],
            Tags=[
                {"Key": "Name", "Value": f"amauo-subnet-{region}"},
                {"Key": "ManagedBy", "Value": "amauo"},
                {"Key": "DeploymentId", "Value": deployment_id},
            ],
        )

        # Create Internet Gateway
        igw_response = ec2_client.create_internet_gateway()
        igw_id = igw_response["InternetGateway"]["InternetGatewayId"]

        # Tag the Internet Gateway
        ec2_client.create_tags(
            Resources=[igw_id],
            Tags=[
                {"Key": "Name", "Value": f"amauo-igw-{region}"},
                {"Key": "ManagedBy", "Value": "amauo"},
                {"Key": "DeploymentId", "Value": deployment_id},
            ],
        )

        # Attach Internet Gateway to VPC
        ec2_client.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)

        # Get the main route table for the VPC
        route_tables = ec2_client.describe_route_tables(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "association.main", "Values": ["true"]},
            ]
        )
        main_route_table_id = route_tables["RouteTables"][0]["RouteTableId"]

        # Add route to Internet Gateway
        ec2_client.create_route(
            RouteTableId=main_route_table_id,
            DestinationCidrBlock="0.0.0.0/0",
            GatewayId=igw_id,
        )

        # Tag the route table
        ec2_client.create_tags(
            Resources=[main_route_table_id],
            Tags=[
                {"Key": "Name", "Value": f"amauo-rt-{region}"},
                {"Key": "ManagedBy", "Value": "amauo"},
                {"Key": "DeploymentId", "Value": deployment_id},
            ],
        )

        return vpc_id, subnet_id, igw_id

    except Exception as e:
        logger.error(f"Error creating VPC in {region}: {e}")
        # Clean up any resources that were created
        try:
            if "vpc_id" in locals():
                delete_deployment_vpc(ec2_client, vpc_id)
        except Exception:
            pass
        raise


def delete_deployment_vpc(ec2_client: Any, vpc_id: str) -> bool:
    """
    Delete a VPC and all its associated resources.
    This handles dependencies in the correct order.
    """
    try:
        # First, delete all instances in the VPC
        instances = ec2_client.describe_instances(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {
                    "Name": "instance-state-name",
                    "Values": ["pending", "running", "stopping", "stopped"],
                },
            ]
        )

        instance_ids = []
        for reservation in instances["Reservations"]:
            for instance in reservation["Instances"]:
                instance_ids.append(instance["InstanceId"])

        if instance_ids:
            ec2_client.terminate_instances(InstanceIds=instance_ids)
            # Don't wait for termination

        # Delete security groups (except default)
        security_groups = ec2_client.describe_security_groups(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )

        for sg in security_groups["SecurityGroups"]:
            if sg["GroupName"] != "default":
                try:
                    ec2_client.delete_security_group(GroupId=sg["GroupId"])
                except Exception:
                    pass  # Ignore errors and continue

        # Detach and delete Internet Gateways
        igws = ec2_client.describe_internet_gateways(
            Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
        )

        for igw in igws["InternetGateways"]:
            igw_id = igw["InternetGatewayId"]
            ec2_client.detach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
            ec2_client.delete_internet_gateway(InternetGatewayId=igw_id)

        # Delete subnets
        subnets = ec2_client.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )

        for subnet in subnets["Subnets"]:
            ec2_client.delete_subnet(SubnetId=subnet["SubnetId"])

        # Delete route tables (except main)
        route_tables = ec2_client.describe_route_tables(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )

        for rt in route_tables["RouteTables"]:
            # Skip if it's the main route table
            if not any(
                assoc.get("Main", False) for assoc in rt.get("Associations", [])
            ):
                try:
                    ec2_client.delete_route_table(RouteTableId=rt["RouteTableId"])
                except Exception as e:
                    logger.warning(
                        f"Warning: Could not delete route table {rt['RouteTableId']}: {e}"
                    )

        # Finally, delete the VPC
        ec2_client.delete_vpc(VpcId=vpc_id)

        return True

    except Exception as e:
        logger.error(f"Error deleting VPC {vpc_id}: {e}")
        return False


def ensure_default_vpc(ec2_client: Any, region: str) -> Optional[str]:
    """
    Ensure a default VPC exists in the region. Create one if it doesn't.
    Returns the VPC ID of the default VPC.
    """
    try:
        # Check for existing default VPC
        vpcs = ec2_client.describe_vpcs(
            Filters=[{"Name": "isDefault", "Values": ["true"]}]
        )

        if vpcs["Vpcs"]:
            return cast(Optional[str], vpcs["Vpcs"][0]["VpcId"])

        # Create default VPC if it doesn't exist
        logger.info(f"No default VPC found in {region}, creating one...")
        response = ec2_client.create_default_vpc()
        vpc_id = cast(str, response["Vpc"]["VpcId"])

        # Wait for VPC to be available
        waiter = ec2_client.get_waiter("vpc_available")
        waiter.wait(VpcIds=[vpc_id])

        logger.info(f"Created default VPC {vpc_id} in {region}")
        return vpc_id

    except Exception as e:
        logger.error(f"Error ensuring default VPC in {region}: {e}")
        return None
