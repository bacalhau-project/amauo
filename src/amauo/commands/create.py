"""Create command implementation."""

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, cast

import boto3
from botocore.exceptions import ClientError
from rich.layout import Layout
from rich.panel import Panel

from .._version import __version__
from ..core.config import SimpleConfig
from ..core.deployment import DeploymentConfig
from ..core.deployment_discovery import DeploymentDiscovery, DeploymentMode
from ..core.state import SimpleStateManager
from ..utils.aws import check_aws_auth
from ..utils.config_validator import ConfigValidator
from ..utils.display import (
    Live,
    Table,
    console,
    rich_error,
    rich_print,
    rich_success,
    rich_warning,
)
from ..utils.logging import ConsoleLogger, setup_logger
from ..utils.portable_cloud_init import PortableCloudInitGenerator
from ..utils.shutdown_handler import ShutdownContext
from ..utils.ssh import transfer_files_scp, wait_for_ssh_only
from ..utils.tables import add_instance_row, create_instance_table


def update_instance_state(state: Any, instance_id: str, status: str) -> None:
    """Update the deployment state of an instance in the state file."""
    instances = state.load_instances()
    for inst in instances:
        if inst["id"] == instance_id:
            inst["state"] = status
            break
    state.save_instances(instances)


def transfer_portable_files(
    host: str,
    username: str,
    key_path: str,
    deployment_config: Any,
    progress_callback: Optional[Any] = None,
    log_function: Optional[Any] = None,
    state: Optional[Any] = None,
    instance_id: Optional[str] = None,
    shared_tarball_path: Optional[str] = None,
) -> bool:
    """Transfer files for portable deployment based on deployment config."""

    from ..utils.file_uploader import FileUploader
    from ..utils.ssh_manager import SSHManager
    from ..utils.tarball_handler import TarballHandler

    if not log_function:
        log_function = print

    try:
        # Use shared tarball if available, otherwise check deployment config
        if shared_tarball_path and os.path.exists(shared_tarball_path):
            log_function(f"Using shared tarball: {shared_tarball_path}")

            # Get tarball size for verification
            local_size = os.path.getsize(shared_tarball_path)
            tarball_size_mb = local_size / 1024 / 1024
            log_function(
                f"Local tarball size: {local_size} bytes ({tarball_size_mb:.1f} MB)"
            )

            # Connect via SSH
            log_function("Establishing SSH connection...")
            ssh_manager = SSHManager(host, username, key_path)

            # Test SSH connection
            test_success, _, _ = ssh_manager.execute_command(
                "echo 'SSH connection test'"
            )
            if not test_success:
                log_function("ERROR: SSH connection failed")
                return False
            log_function("✓ SSH connection established")

            if progress_callback:
                progress_callback(
                    "Upload", 10, f"Uploading tarball ({tarball_size_mb:.1f} MB)"
                )

            # Update state
            if state and instance_id:
                update_instance_state(state, instance_id, "uploading")

            # Upload the tarball
            log_function("Uploading tarball to /tmp/deployment.tar.gz...")
            success = ssh_manager.transfer_file(
                shared_tarball_path, "/tmp/deployment.tar.gz"
            )

            if not success:
                log_function("ERROR: Tarball upload failed")
                return False

            if progress_callback:
                progress_callback("Upload", 50, "Verifying upload...")

            # Verify upload by checking remote file size
            log_function("Verifying upload completion...")
            success, stdout, stderr = ssh_manager.execute_command(
                "stat -c%s /tmp/deployment.tar.gz 2>/dev/null || echo 'ERROR'"
            )

            if not success or stdout.strip() == "ERROR":
                log_function("ERROR: Failed to verify remote file size")
                return False

            try:
                remote_size = int(stdout.strip())
                log_function(f"Remote file size: {remote_size} bytes")

                if remote_size != local_size:
                    log_function(
                        f"ERROR: Size mismatch! Local: {local_size}, Remote: {remote_size}"
                    )
                    return False

                log_function("✓ Upload verified - sizes match")

            except ValueError:
                log_function(f"ERROR: Invalid remote size response: {stdout}")
                return False

            if progress_callback:
                progress_callback("Setup", 75, "Upload verified")

            # Create upload complete marker
            log_function("Creating upload completion marker...")
            ssh_manager.execute_command("touch /tmp/UPLOAD_COMPLETE")
            log_function("✓ Upload complete marker created")

            if progress_callback:
                progress_callback("Complete", 100, "Upload verified and complete")

            # Update state
            if state and instance_id:
                update_instance_state(state, instance_id, "complete")

            return True

        # Fallback to old logic if no shared tarball
        tarball_source = getattr(deployment_config, "tarball_source", None)
        log_function(
            f"No shared tarball available, checking for tarball_source: '{tarball_source}'"
        )

        if tarball_source:
            log_function(f"Creating tarball from {tarball_source}...")

            handler = TarballHandler()
            source_path = Path(tarball_source)

            if not source_path.exists():
                log_function(f"ERROR: Tarball source not found: {source_path}")
                return False

            # Create the tarball using the generic method
            # (create_deployment_tarball expects specific structure we don't have)
            tarball_path = handler.create_tarball(source_path)
            log_function(f"Created tarball: {tarball_path}")

            # Upload the tarball
            if progress_callback:
                progress_callback("Uploading", 0, "Uploading deployment tarball...")

            # Use ssh_manager with proper initialization
            log_function("Connecting via SSH...")
            ssh_manager = SSHManager(host, username, key_path)

            # Test SSH connection first
            test_success, _, _ = ssh_manager.execute_command(
                "echo 'SSH connection established'"
            )
            if test_success:
                log_function("✓ SSH connected successfully")
            else:
                log_function("ERROR: SSH connection failed")
                return False

            # Update state to uploading
            if state and instance_id:
                update_instance_state(state, instance_id, "uploading")

            # Upload the tarball
            tarball_size_mb = os.path.getsize(tarball_path) / 1024 / 1024
            log_function(f"Uploading tarball ({tarball_size_mb:.1f} MB)...")
            if progress_callback:
                progress_callback(
                    "Upload", 25, f"Uploading tarball ({tarball_size_mb:.1f} MB)"
                )

            success = ssh_manager.transfer_file(
                str(tarball_path), "/tmp/deployment.tar.gz"
            )

            if not success:
                log_function("ERROR: Failed to upload tarball")
                if progress_callback:
                    progress_callback("Upload", 0, "Failed to upload tarball")
                return False

            log_function("✓ Tarball uploaded successfully")

            # Update state to uploaded
            if state and instance_id:
                update_instance_state(state, instance_id, "uploaded")
            if progress_callback:
                progress_callback("Upload", 50, "Tarball uploaded")

            # Create upload complete marker
            log_function("Creating upload complete marker...")
            ssh_manager.execute_command("touch /tmp/UPLOAD_COMPLETE")
            log_function("✓ Upload complete marker created")
            if progress_callback:
                progress_callback("Setup", 75, "Signaled upload complete")

            # Trigger setup.sh in background (non-blocking)
            log_function("Starting setup.sh in background...")

            # Update state to setup
            if state and instance_id:
                update_instance_state(state, instance_id, "setup")

            # Wait a bit for cloud-init to detect the marker, then run setup
            setup_cmd = "nohup bash -c 'sleep 5 && cd /opt/deployment && [ -f setup.sh ] && chmod +x setup.sh && ./setup.sh > /var/log/setup.log 2>&1' > /dev/null 2>&1 &"
            ssh_manager.execute_command(setup_cmd)
            log_function("✓ Setup.sh started (running in background)")
            if progress_callback:
                progress_callback("Complete", 100, "Setup.sh launched in background")

            # Update state to complete (setup is async, so we mark it complete after launching)
            if state and instance_id:
                update_instance_state(state, instance_id, "complete")

            # Clean up local tarball
            handler.cleanup()

            if progress_callback:
                progress_callback("Uploading", 100, "Tarball uploaded")

            return True

        # Otherwise use manifest-based uploads
        ssh_manager = SSHManager(host, username, key_path)

        if not deployment_config.uploads:
            log_function("No files to upload (no uploads defined in deployment config)")
            # Still create the marker file to signal completion
            ssh_manager.execute_command("touch /tmp/UPLOAD_COMPLETE")
            log_function("Created upload complete marker")
            return True

        # Use FileUploader for manifest-based uploads
        uploader = FileUploader(deployment_config, deployment_config.spot_dir)

        # Create a progress wrapper if callback provided
        def progress_wrapper(message: str, percent: float) -> None:
            if progress_callback:
                progress_callback("Uploading", int(percent), message)

        # Upload all files according to manifest
        success, message = uploader.upload_all(
            host=host,
            username=username,
            key_path=key_path,
            progress_callback=progress_wrapper if progress_callback else None,
        )

        log_function(message)

        # Get and log statistics
        stats = uploader.get_stats()
        if stats["uploaded_files"] > 0:
            size_mb = stats["total_bytes"] / (1024 * 1024)
            log_function(f"Uploaded {stats['uploaded_files']} files ({size_mb:.1f} MB)")

        # Create upload complete marker
        if success:
            ssh_manager.execute_command("touch /tmp/UPLOAD_COMPLETE")
            log_function("Created upload complete marker")

        return success

    except Exception as e:
        if log_function:
            log_function(f"Error during file transfer: {e}")

        # Still try to create the marker so cloud-init doesn't hang forever
        try:
            ssh_manager = SSHManager(host, username, key_path)
            ssh_manager.execute_command("touch /tmp/UPLOAD_COMPLETE")
            log_function("Created upload complete marker (despite errors)")
        except Exception:
            pass

        return False


def post_creation_setup(
    instances: Any,
    config: Any,
    update_status_func: Any,
    logger: Any,
    deployment_config: Optional[Any] = None,
    state: Optional[Any] = None,
    shared_tarball_path: Optional[str] = None,
) -> None:
    """Handle post-creation setup for all instances."""
    if not instances:
        return

    private_key_path = config.private_ssh_key_path()
    if not private_key_path:
        logger.error("No private SSH key path configured")
        return

    expanded_key_path = os.path.expanduser(private_key_path)
    if not os.path.exists(expanded_key_path):
        logger.error(f"Private SSH key not found at {expanded_key_path}")
        return

    username = config.username()

    # For portable deployments, we'll handle file uploads differently
    if deployment_config:
        files_directory = None  # Will be handled by deployment config
        scripts_directory = None
    else:
        # Legacy mode - use config directories
        files_directory = config.files_directory()
        scripts_directory = config.scripts_directory()

    # Check for additional_commands.sh in current directory
    additional_commands_path = os.path.join(os.getcwd(), "additional_commands.sh")
    if not os.path.exists(additional_commands_path):
        # Check in output directory as fallback
        output_dir = os.environ.get("SPOT_OUTPUT_DIR", ".")
        additional_commands_path = os.path.join(output_dir, "additional_commands.sh")
        if not os.path.exists(additional_commands_path):
            logger.warning(
                "No additional_commands.sh found in current directory. Deployment will continue without custom commands."
            )
            logger.info(
                "To add custom commands, create additional_commands.sh in the directory where you run spot-deployer."
            )
            additional_commands_path = None  # type: ignore[assignment]

    def setup_instance(instance: Any, instance_key: str) -> None:
        instance_id = instance["id"]
        instance_ip = instance.get("public_ip")

        if not instance_ip:
            logger.error(f"[{instance_id}] No public IP available")
            update_status_func(instance_key, "ERROR: No public IP", is_final=True)
            return

        thread_name = f"Setup-{instance_id}"
        threading.current_thread().name = thread_name

        try:
            # Wait for SSH to be available
            logger.info(f"[{instance_id} @ {instance_ip}] Waiting for SSH...")
            update_status_func(instance_key, "⏳ Waiting for SSH...")

            if not wait_for_ssh_only(
                instance_ip, username, expanded_key_path, timeout=300
            ):
                logger.error(f"[{instance_id} @ {instance_ip}] SSH timeout")
                update_status_func(instance_key, "❌ SSH timeout", is_final=True)
                return

            logger.info(f"[{instance_id} @ {instance_ip}] SSH available")
            update_status_func(instance_key, "✅ SSH connected")

            # Transfer files
            logger.info(f"[{instance_id} @ {instance_ip}] Starting file transfer...")
            update_status_func(instance_key, "📦 Preparing upload...")

            def progress_callback(phase: str, progress: int, status: str) -> None:
                # Show detailed progress with icons
                if "SSH" in status:
                    icon = "🔐"
                elif "tarball" in status.lower():
                    icon = "📦"
                elif "setup" in status.lower():
                    icon = "⚙️"
                elif "complete" in status.lower():
                    icon = "✅"
                else:
                    icon = "📤"
                update_status_func(instance_key, f"{icon} {status}")

            if deployment_config:
                # Portable deployment - upload based on deployment config
                logger.info(
                    f"[{instance_id} @ {instance_ip}] Using portable deployment with tarball"
                )
                try:
                    success = transfer_portable_files(
                        instance_ip,
                        username,
                        expanded_key_path,
                        deployment_config,
                        progress_callback=progress_callback,
                        log_function=lambda msg: logger.info(
                            f"[{instance_id} @ {instance_ip}] {msg}"
                        ),
                        state=state,
                        instance_id=instance_id,
                        shared_tarball_path=shared_tarball_path,
                    )
                except Exception as e:
                    logger.error(
                        f"[{instance_id} @ {instance_ip}] Transfer failed: {e}"
                    )
                    success = False
            else:
                # Legacy deployment or no files to upload
                logger.info(
                    f"[{instance_id} @ {instance_ip}] No deployment config, creating marker"
                )
                # Still create the marker so cloud-init doesn't hang
                try:
                    from ..utils.ssh_manager import SSHManager

                    ssh_manager = SSHManager(instance_ip, username, expanded_key_path)
                    ssh_manager.execute_command("touch /tmp/UPLOAD_COMPLETE")
                    logger.info(
                        f"[{instance_id} @ {instance_ip}] Created upload complete marker (no files)"
                    )
                except Exception as e:
                    logger.error(
                        f"[{instance_id} @ {instance_ip}] Failed to create marker: {e}"
                    )

                if files_directory and scripts_directory:
                    success = transfer_files_scp(
                        instance_ip,
                        username,
                        expanded_key_path,
                        files_directory,
                        scripts_directory,
                        additional_commands_path=additional_commands_path,
                        progress_callback=progress_callback,
                        log_function=lambda msg: logger.info(
                            f"[{instance_id} @ {instance_ip}] {msg}"
                        ),
                    )
                else:
                    logger.error(
                        f"[{instance_id} @ {instance_ip}] No files/scripts directories configured"
                    )
                    success = False

            if not success:
                logger.error(f"[{instance_id} @ {instance_ip}] File transfer failed")
                update_status_func(
                    instance_key, "ERROR: File upload failed", is_final=True
                )
                return

            logger.info(
                f"[{instance_id} @ {instance_ip}] SUCCESS: Files uploaded and setup.sh started"
            )
            update_status_func(
                instance_key, "✅ Setup running in background", is_final=True
            )

            # Deployment script is now running in background
            logger.info(
                f"[{instance_id} @ {instance_ip}] Setup.sh running in background - check /var/log/setup.log"
            )

        except Exception as e:
            logger.error(f"[{instance_id} @ {instance_ip}] Setup failed: {e}")
            error_msg = str(e)
            if len(error_msg) > 40:
                error_msg = f"{error_msg[:37]}..."
            update_status_func(instance_key, f"ERROR: {error_msg}", is_final=True)

    # Process instances in parallel
    with ThreadPoolExecutor(
        max_workers=len(instances), thread_name_prefix="Setup"
    ) as executor:
        futures = []
        for i, instance in enumerate(instances):
            region = instance.get("region", "unknown")
            instance_key = f"{region}-{i + 1}"
            futures.append(executor.submit(setup_instance, instance, instance_key))

        # Wait for all setups to complete
        for future in futures:
            future.result()


def create_instances_in_region_with_table(
    config: SimpleConfig,
    region: str,
    count: int,
    creation_status: dict,
    lock: threading.Lock,
    logger: Any,
    update_status_func: Any,
    instance_ip_map: dict,
    deployment_id: str,
    created_at: str,
    creator: str,
    state: SimpleStateManager,
    deployment_config: Optional[DeploymentConfig] = None,
) -> list[dict]:
    """Create spot instances in a specific region with live table updates."""
    if count <= 0:
        return []

    instance_keys = [f"{region}-{i + 1}" for i in range(count)]

    def log_message(msg: str) -> None:
        """Thread-safe logging to file."""
        logger.info(msg)

    for key in instance_keys:
        update_status_func(key, "Finding VPC")

    try:
        from ..utils.aws_manager import AWSResourceManager

        # Use the new AWS manager
        aws_manager = AWSResourceManager(region)
        ec2 = aws_manager.ec2

        # Find or create VPC
        vpc_status = (
            "Creating dedicated VPC" if config.use_dedicated_vpc() else "Finding VPC"
        )
        for key in instance_keys:
            update_status_func(key, vpc_status)

        try:
            vpc_id, subnet_id = aws_manager.find_or_create_vpc(
                use_dedicated=config.use_dedicated_vpc(), deployment_id=deployment_id
            )
            log_message(f"Using VPC in {region}: {vpc_id}")
            log_message(f"Using subnet in {region}: {subnet_id}")
        except Exception as e:
            log_message(f"Failed to setup VPC in {region}: {e}")
            for key in instance_keys:
                update_status_func(key, f"ERROR: {str(e)}", is_final=True)
            return []

        for key in instance_keys:
            update_status_func(key, "Creating security group")

        # Create security group
        try:
            sg_id = aws_manager.create_security_group(vpc_id)
            log_message(f"Security group in {region}: {sg_id}")
        except Exception as e:
            log_message(f"Failed to create security group: {e}")
            for key in instance_keys:
                update_status_func(key, "ERROR: Security group failed", is_final=True)
            return []

        # Get region config
        region_cfg = config.region_config(region)
        machine_type = region_cfg.get("machine_type", "t3.medium")

        for key in instance_keys:
            update_status_func(key, "Finding AMI")

        # Get AMI
        ami_id = None
        if region_cfg.get("image") == "auto":
            ami_id = aws_manager.find_ubuntu_ami()
            if ami_id:
                log_message(f"Found Ubuntu AMI: {ami_id}")
        else:
            ami_id = region_cfg.get("image")

        if not ami_id:
            log_message(f"No AMI found for {region}")
            for key in instance_keys:
                update_status_func(key, "ERROR: No AMI found", is_final=True)
            return []

        log_message(f"Using AMI in {region}: {ami_id}")

        for key in instance_keys:
            update_status_func(key, "Launching instance")

        # Generate cloud-init script
        if not deployment_config:
            log_message("ERROR: No deployment configuration available")
            for key in instance_keys:
                update_status_func(key, "ERROR: No config", is_final=True)
            return []

        # Use portable cloud-init generator for portable deployments
        log_message("Using portable cloud-init generator")

        # Read SSH public key if available
        ssh_public_key = None
        public_key_path = config.public_ssh_key_path()
        if public_key_path:
            try:
                expanded_path = os.path.expanduser(public_key_path)
                with open(expanded_path) as f:
                    ssh_public_key = f.read().strip()
                    log_message(f"Loaded SSH public key from {public_key_path}")
            except Exception as e:
                log_message(f"WARNING: Could not read SSH public key: {e}")

        generator = PortableCloudInitGenerator(
            deployment_config, ssh_public_key=ssh_public_key
        )

        # Check if a template is specified
        if deployment_config.template:
            from pathlib import Path

            # Check if it's a file path or template name
            template_path = Path(deployment_config.template)
            if template_path.exists():
                log_message(f"Using custom template file: {deployment_config.template}")
                cloud_init_script = generator.generate_with_template(
                    template_path=template_path
                )
            else:
                log_message(f"Using library template: {deployment_config.template}")
                cloud_init_script = generator.generate_with_template(
                    template_name=deployment_config.template
                )
        else:
            cloud_init_script = generator.generate()

        # Create instances
        market_options = {
            "MarketType": "spot",
            "SpotOptions": {"SpotInstanceType": "one-time"},
        }

        # Build run_instances parameters
        run_params = {
            "ImageId": ami_id,
            "MinCount": count,
            "MaxCount": count,
            "InstanceType": machine_type,
            "SecurityGroupIds": [sg_id],
            "SubnetId": subnet_id,
            "InstanceMarketOptions": market_options,
            "BlockDeviceMappings": [
                {
                    "DeviceName": "/dev/sda1",
                    "Ebs": {
                        "VolumeSize": config.instance_storage_gb(),
                        "VolumeType": "gp3",
                        "DeleteOnTermination": True,
                    },
                }
            ],
            "TagSpecifications": [
                {
                    "ResourceType": "instance",
                    "Tags": [
                        {"Key": "Name", "Value": f"spot-{region}-{created_at}"},
                        {"Key": "ManagedBy", "Value": "amauo"},
                        {"Key": "DeploymentId", "Value": deployment_id},
                        {"Key": "CreatedAt", "Value": datetime.now().isoformat()},
                        {"Key": "CreatedBy", "Value": creator},
                        {"Key": "Region", "Value": region},
                        {"Key": "AmauoVersion", "Value": __version__},
                        {"Key": "App", "Value": "amauo"},
                    ]
                    + [
                        {"Key": k, "Value": v}
                        for k, v in config.tags().items()
                        if k
                        not in [
                            "Name",
                            "ManagedBy",
                            "DeploymentId",
                            "CreatedAt",
                            "CreatedBy",
                            "Region",
                            "amauoVersion",
                        ]
                    ],
                }
            ],
            "UserData": cloud_init_script,
        }

        # We don't use AWS KeyName - SSH key is injected via cloud-init

        # Add retry logic for instance creation
        max_retries = 3
        retry_count = 0
        result = None
        last_error = None

        while retry_count < max_retries:
            try:
                result = ec2.run_instances(**run_params)
                break  # Success, exit retry loop
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code in ["InsufficientInstanceCapacity", "SpotMaxPriceTooLow"]:
                    # These are terminal errors, don't retry
                    raise
                elif error_code in ["RequestLimitExceeded", "Throttling"]:
                    # These are retryable errors
                    retry_count += 1
                    last_error = e
                    if retry_count < max_retries:
                        wait_time = (
                            2**retry_count
                        )  # Exponential backoff: 2, 4, 8 seconds
                        log_message(
                            f"Rate limited in {region}, retrying in {wait_time} seconds..."
                        )
                        time.sleep(wait_time)
                    else:
                        raise
                else:
                    # Unknown error, don't retry
                    raise

        if not result:
            if last_error:
                raise last_error
            else:
                raise Exception(f"Failed to create instances in {region}")

        # Wait for instances to get public IPs
        created_instances: list[dict[str, Any]] = []

        typed_instances = cast(list[dict[str, Any]], result["Instances"])
        instance_ids = [inst["InstanceId"] for inst in typed_instances]

        log_message(
            f"Created {len(instance_ids)} instances in {region}, waiting for public IPs..."
        )

        # Immediately save instances to state with minimal info
        if state:
            with lock:
                for inst_id in instance_ids:
                    partial_instance = {
                        "id": inst_id,
                        "region": region,
                        "type": machine_type,
                        "state": "provisioned",  # Deployment state, not AWS state
                        "public_ip": "pending",
                        "created": datetime.now().isoformat(),
                        "ami": ami_id,
                        "vpc_id": vpc_id,
                        "subnet_id": subnet_id,
                        "security_group_id": sg_id,
                        "deployment_id": deployment_id,
                        "creator": creator,
                    }
                    # Add to state immediately
                    existing_instances = state.load_instances()
                    existing_instances.append(partial_instance)
                    state.save_instances(existing_instances)

        for i, inst_id in enumerate(instance_ids):
            key = instance_keys[i]
            update_status_func(key, "Waiting for public IP", instance_id=inst_id)

        # Poll for public IPs
        time.sleep(1)  # Give AWS a moment to register the instances
        max_attempts = 30
        for attempt in range(max_attempts):
            try:
                instances_data = ec2.describe_instances(InstanceIds=instance_ids)

                typed_reservations = cast(
                    list[dict[str, Any]], instances_data["Reservations"]
                )

                for reservation in typed_reservations:
                    typed_reservation = reservation
                    for inst in typed_reservation["Instances"]:
                        inst_id = inst["InstanceId"]
                        idx = instance_ids.index(inst_id)
                        key = instance_keys[idx]

                        public_ip = inst.get("PublicIpAddress")
                        inst["State"]["Name"]

                        if public_ip:
                            instance_data = {
                                "id": inst_id,
                                "region": region,
                                "type": machine_type,
                                "state": "provisioned",  # Deployment state, not AWS state
                                "public_ip": public_ip,
                                "created": datetime.now().isoformat(),
                                "ami": ami_id,
                                "vpc_id": vpc_id,
                                "subnet_id": subnet_id,
                                "security_group_id": sg_id,
                            }

                            # Check if we already added this instance
                            if not any(ci["id"] == inst_id for ci in created_instances):
                                created_instances.append(instance_data)
                                update_status_func(
                                    key,
                                    "SUCCESS: Created",
                                    instance_id=inst_id,
                                    ip=public_ip,
                                    created=datetime.now().strftime(
                                        "%Y-%m-%d %H:%M:%S"
                                    ),
                                )

                                # Update the IP map for logging context
                                with lock:
                                    instance_ip_map[inst_id] = public_ip

                                    # Update state with the public IP
                                    if state:
                                        instances = state.load_instances()
                                        for inst in instances:
                                            if inst["id"] == inst_id:
                                                inst["public_ip"] = public_ip
                                                # Don't update state here - we track deployment state, not AWS state
                                                break
                                        state.save_instances(instances)

                if len(created_instances) == len(instance_ids):
                    break

                time.sleep(2)

            except Exception as e:
                # Instances might not be ready yet, just continue
                if attempt < 5:  # Only log after a few attempts
                    time.sleep(2)
                    continue
                log_message(f"Error checking instance status: {e}")

        # Mark any instances without IPs as errors
        for i, inst_id in enumerate(instance_ids):
            if not any(ci["id"] == inst_id for ci in created_instances):
                key = instance_keys[i]
                update_status_func(
                    key, "ERROR: No public IP", instance_id=inst_id, is_final=True
                )

        return created_instances

    except Exception as e:
        error_msg = str(e)
        log_message(f"Error creating instances in {region}: {error_msg}")

        # Handle capacity errors specially - just skip this region
        if "InsufficientInstanceCapacity" in error_msg:
            log_message(f"No capacity in {region}, skipping")
            for key in instance_keys:
                update_status_func(key, "SKIPPED: No capacity", is_final=True)
            return []  # Return empty list, no instances created
        elif "Parameter validation failed" in error_msg:
            # AWS parameter validation errors often have the details after a colon
            if "Invalid" in error_msg:
                # Try to extract the specific validation error
                parts = error_msg.split("Invalid")
                if len(parts) > 1:
                    short_error = f"Invalid{parts[1][:40]}..."
                else:
                    short_error = error_msg[:50]
            else:
                short_error = "Parameter validation failed"
        elif len(error_msg) > 50:
            short_error = f"{error_msg[:47]}..."
        else:
            short_error = error_msg

        for key in instance_keys:
            update_status_func(key, f"ERROR: {short_error}", is_final=True)
        return []


def _run_cleanup_script() -> None:
    """Run the cleanup script to prevent file conflicts."""
    import subprocess
    from pathlib import Path

    cleanup_script = (
        Path(__file__).parent.parent.parent.parent / "scripts" / "cleanup.sh"
    )
    if cleanup_script.exists():
        try:
            subprocess.run([str(cleanup_script)], check=False, capture_output=True)
        except Exception:
            pass  # Cleanup failures shouldn't block deployment


def cmd_create(
    config: SimpleConfig, state: SimpleStateManager, debug: bool = False
) -> None:
    """Create spot instances across configured regions with enhanced real-time progress tracking."""
    # Run aggressive cleanup before deployment to prevent file conflicts
    _run_cleanup_script()

    if not check_aws_auth():
        return

    # Initialize deployment_config as None (for legacy mode)
    deployment_config = None

    # Use deployment discovery to detect mode
    discovery = DeploymentDiscovery()
    discovery_result = discovery.discover()

    if discovery_result.mode == DeploymentMode.PORTABLE:
        # Portable deployment mode
        if not discovery_result.is_valid:
            rich_error("❌ Invalid portable deployment structure:")
            for error in discovery_result.validation_errors:
                rich_error(f"   • {error}")
            rich_print(
                "\n[yellow]Run 'amauo generate' to create the required structure.[/yellow]"
            )
            return

        deployment_config = discovery_result.deployment_config
        if deployment_config:
            rich_success("✅ Using portable deployment (.spot directory)")
        else:
            rich_error("❌ Failed to load deployment configuration")
            return

    elif discovery_result.mode == DeploymentMode.CONVENTION:
        # Convention-based deployment mode
        if not discovery_result.is_valid:
            rich_error("❌ Invalid convention deployment structure:")
            for error in discovery_result.validation_errors:
                rich_error(f"   • {error}")
            return

        deployment_config = discovery_result.deployment_config
        if deployment_config:
            rich_success("✅ Using convention-based deployment (deployment/ directory)")
        else:
            rich_error("❌ Failed to build deployment configuration from conventions")
            return

    else:
        # No deployment structure found
        rich_error("❌ No deployment structure found")
        rich_print(
            "\n[yellow]Run 'amauo generate' to create the required structure.[/yellow]"
        )
        return

    # Validate configuration first
    validator = ConfigValidator()
    config_path = config.config_file
    is_valid, _ = validator.validate_config_file(config_path)

    if not is_valid:
        validator.suggest_fixes()
        return

    # Pre-create deployment tarball if needed (one-time creation for all instances)
    shared_tarball_path = None
    if deployment_config:
        tarball_source = getattr(deployment_config, "tarball_source", None)
        if tarball_source:
            try:
                from ..utils.tarball_handler import TarballHandler

                rich_print(f"📦 Creating deployment tarball from {tarball_source}...")
                handler = TarballHandler()
                source_path = Path(tarball_source)

                if not source_path.exists():
                    rich_error(f"❌ Deployment source not found: {source_path}")
                    return

                # Create unique tarball in /tmp
                unique_id = str(uuid.uuid4())[:8]
                shared_tarball_path = f"/tmp/amauo-deployment-{unique_id}.tar.gz"

                # Use the generic tarball creation method
                temp_tarball = handler.create_tarball(source_path)

                # Move to our shared location
                import shutil

                shutil.move(str(temp_tarball), shared_tarball_path)

                # Get tarball size for verification
                tarball_size = os.path.getsize(shared_tarball_path)
                rich_success(
                    f"✅ Created shared tarball: {shared_tarball_path} ({tarball_size / 1024 / 1024:.1f} MB)"
                )

            except Exception as e:
                rich_error(f"❌ Failed to create deployment tarball: {e}")
                return

    # Initial header will be shown in the Live display

    # Setup local logging
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"amauo_creation_{timestamp}.log" if debug else None

    # Generate unique deployment ID for this batch
    deployment_id = f"amauo-{timestamp}-{str(uuid.uuid4())[:8]}"

    # Get AWS caller identity for creator tag
    try:
        sts = boto3.client("sts")
        caller_identity = sts.get_caller_identity()
        creator = caller_identity.get("Arn", "unknown").split("/")[
            -1
        ]  # Get username from ARN
    except Exception:
        creator = "unknown"

    # Create log buffer for in-memory storage (always enabled)
    from ..utils.logging import LogBuffer

    log_buffer = LogBuffer(maxlen=100)

    # Create console handler with instance IP map and log buffer
    instance_ip_map: dict[str, str] = {}
    console_handler = ConsoleLogger(console, instance_ip_map, log_buffer)
    logger = setup_logger("amauo_creator", log_filename, console_handler)

    # Check for SSH key configuration
    public_key_path = config.public_ssh_key_path()
    private_key_path = config.private_ssh_key_path()

    if not public_key_path:
        rich_error("❌ No 'public_ssh_key_path' configured in config.yaml")
        rich_error("   This is required to inject your SSH key into instances.")
        return

    # Check if public key exists
    expanded_public_path = os.path.expanduser(public_key_path)
    if not os.path.exists(expanded_public_path):
        rich_error(f"Public SSH key not found at '{public_key_path}'")
        return

    # Check private key for SSH operations
    if private_key_path:
        expanded_private_path = os.path.expanduser(private_key_path)
        if not os.path.exists(expanded_private_path):
            rich_error(f"Private SSH key not found at '{private_key_path}'")
            return
    else:
        rich_warning(
            "Private SSH key path is not set in config.yaml. SSH-based operations will fail."
        )

    regions = config.regions()
    if not regions:
        rich_error("No regions configured. Run 'setup' first.")
        return

    # Show configuration summary
    rich_print("[dim]Reading configuration...[/dim]")

    # Calculate instance distribution
    total_instances = config.instance_count()
    instances_per_region = total_instances // len(regions)
    remainder = total_instances % len(regions)

    region_instance_map = {}
    for i, region in enumerate(regions):
        # Distribute remainder instances across first regions
        count = instances_per_region + (1 if i < remainder else 0)
        if count > 0:
            region_instance_map[region] = count

    total_instances_to_create = sum(region_instance_map.values())

    if total_instances_to_create == 0:
        rich_warning("No instances configured to be created.")
        return

    # Show deployment plan
    rich_print(
        f"\n[green]Planning to create {total_instances_to_create} instances across {len(region_instance_map)} regions:[/green]"
    )
    for region, count in region_instance_map.items():
        region_cfg = config.region_config(region)
        instance_type = region_cfg.get("machine_type", "t3.medium")
        rich_print(f"  • {region}: {count} × {instance_type}")

    rich_print("\n[dim]Preparing deployment resources...[/dim]")

    # Track regions that were skipped due to capacity
    skipped_regions: set[str] = set()

    creation_status = {}
    all_instances: list[dict[str, Any]] = []
    lock = threading.Lock()

    # Initialize status for all instances
    for region, count in region_instance_map.items():
        region_cfg = config.region_config(region)
        instance_type = region_cfg.get("machine_type", "t3.medium")
        for i in range(count):
            key = f"{region}-{i + 1}"
            creation_status[key] = {
                "region": region,
                "instance_id": "pending...",
                "status": "WAIT: Starting...",
                "type": instance_type,
                "public_ip": "pending...",
                "created": "pending...",
            }

    def generate_layout() -> Any:
        # Count active (non-skipped) instances
        active_count = sum(
            1 for item in creation_status.values() if "SKIPPED" not in item["status"]
        )

        # Count completed instances (SUCCESS or ERROR)
        completed_count = sum(
            1
            for item in creation_status.values()
            if "SUCCESS" in item["status"] or "ERROR" in item["status"]
        )

        # Calculate progress percentage
        progress_pct = (completed_count / active_count * 100) if active_count > 0 else 0

        # Create progress bar [████░░░] X/Y (Z%)
        bar_length = 8
        filled = int(bar_length * progress_pct / 100)
        bar = "█" * filled + "░" * (bar_length - filled)
        progress_str = f"[{bar}] {completed_count}/{active_count} ({progress_pct:.0f}%)"

        table = create_instance_table(
            title=f"Creating instances {progress_str}",
            show_lines=False,
            padding=(0, 1),
        )

        sorted_items = sorted(creation_status.items(), key=lambda x: x[0])

        # Limit table rows to prevent pushing log panel off screen
        # Show priority: in-progress, then errors, then success (changed order per summary)
        error_items = []
        progress_items = []
        success_items = []

        for key, item in sorted_items:
            status = item["status"]
            # Don't show skipped instances in the table
            if "SKIPPED" in status:
                continue

            if "ERROR" in status:
                error_items.append((key, item))
            elif "SUCCESS" in status:
                success_items.append((key, item))
            else:
                progress_items.append((key, item))

        # Combine in priority order: in-progress → errors → completed (keep active visible)
        all_items = progress_items + error_items + success_items

        # Apply 20-row limit with overflow summary
        MAX_ROWS = 20
        displayed_items = all_items[:MAX_ROWS]
        overflow_count = len(all_items) - MAX_ROWS

        for _key, item in displayed_items:
            status = item["status"]

            if "SUCCESS" in status:
                status_style = f"[bold green]{status}[/bold green]"
            elif "ERROR" in status:
                status_style = f"[bold red]{status}[/bold red]"
            else:
                status_style = status

            add_instance_row(
                table,
                item["region"],
                item["instance_id"],
                status_style,
                item["type"],
                item["public_ip"],
                item["created"],
            )

        # Add overflow summary row if needed
        if overflow_count > 0:
            # Count overflow by status
            overflow_deployed = sum(
                1 for _, item in all_items[MAX_ROWS:] if "SUCCESS" in item["status"]
            )
            overflow_errors = sum(
                1 for _, item in all_items[MAX_ROWS:] if "ERROR" in item["status"]
            )
            overflow_pending = overflow_count - overflow_deployed - overflow_errors

            summary_parts = []
            if overflow_deployed > 0:
                summary_parts.append(f"{overflow_deployed} deployed")
            if overflow_errors > 0:
                summary_parts.append(f"{overflow_errors} errors")
            if overflow_pending > 0:
                summary_parts.append(f"{overflow_pending} pending")

            overflow_summary = (
                f"... | +{overflow_count} more | {', '.join(summary_parts)}"
            )
            add_instance_row(
                table,
                "[dim]...[/dim]",
                "[dim]...[/dim]",
                f"[dim]{overflow_summary}[/dim]",
                "",
                "",
                "",
            )

        # Create layout with table taking most space and logs at bottom
        layout = Layout()

        # Create log panel - read from buffer or file
        log_content = ""
        if log_filename:
            # Debug mode: read from file
            try:
                with open(log_filename) as f:
                    # Read last 10 lines for the log panel
                    lines = [line.rstrip() for line in f.readlines()[-10:]]
                    log_content = "\n".join(lines)
            except (OSError, FileNotFoundError):
                log_content = "Log file not available yet..."
            log_title = f"[dim]Log: {log_filename}[/dim]"
        else:
            # Normal mode: read from buffer
            lines = log_buffer.get_lines()[-10:]  # Last 10 messages
            log_content = (
                "\n".join(lines) if lines else "[dim]Waiting for logs...[/dim]"
            )
            log_title = "[dim]Recent Activity[/dim]"

        log_panel = Panel(
            log_content,
            title=log_title,
            border_style="dim",
        )

        # Split layout: table takes most space, log panel at bottom
        layout.split_column(
            Layout(table, ratio=4),
            Layout(log_panel, size=12),  # Fixed size for log panel
        )

        return layout

    def update_status(
        key: str,
        status: str,
        instance_id: Optional[str] = None,
        ip: Optional[str] = None,
        created: Optional[bool] = None,
        is_final: bool = False,
    ) -> bool:
        with lock:
            if key in creation_status:
                creation_status[key]["status"] = status
                if instance_id:
                    creation_status[key]["instance_id"] = instance_id
                if ip:
                    creation_status[key]["public_ip"] = ip
                if created:
                    creation_status[key]["created"] = created

                log_ip = ip if ip else "N/A"
                log_id = instance_id if instance_id else key
                logger.info(f"[{log_id} @ {log_ip}] {status}")
        return True

    # Set up graceful shutdown handling
    with ShutdownContext("Cleaning up spot instance creation...") as shutdown_ctx:
        # Define cleanup function
        def cleanup_on_shutdown() -> None:
            logger.warning("Shutdown requested - cleaning up...")
            # Save any instances that were created
            if all_instances:
                state.save_instances(all_instances)
                logger.info(f"Saved state for {len(all_instances)} instances")
            # Update status for any pending instances
            with lock:
                for _key, item in creation_status.items():
                    if "Waiting" in item["status"] or "Creating" in item["status"]:
                        item["status"] = "INTERRUPTED"

        shutdown_ctx.add_cleanup(cleanup_on_shutdown)

        with Live(
            generate_layout(),
            refresh_per_second=4,
            console=console,
            screen=True,
            redirect_stdout=False,
        ) as live:

            def create_region_instances(region: str, count: int) -> None:
                try:
                    # Check for shutdown before starting
                    if shutdown_ctx.shutdown_requested:
                        logger.warning(f"Skipping {region} due to shutdown request")
                        return

                    instances = create_instances_in_region_with_table(
                        config,
                        region,
                        count,
                        creation_status,
                        lock,
                        logger,
                        update_status,
                        instance_ip_map,
                        deployment_id,
                        timestamp,
                        creator,
                        state,
                        deployment_config,
                    )
                    with lock:
                        all_instances.extend(instances)
                except Exception as e:
                    logger.error(f"Error in create_region_instances for {region}: {e}")

            with ThreadPoolExecutor(
                max_workers=len(regions), thread_name_prefix="Create"
            ) as executor:
                futures = [
                    executor.submit(create_region_instances, r, c)
                    for r, c in region_instance_map.items()
                ]
                while (
                    any(f.running() for f in futures)
                    and not shutdown_ctx.shutdown_requested
                ):
                    live.update(generate_layout())
                    time.sleep(0.25)

            live.update(generate_layout())  # Final update after creation phase

            if all_instances and not shutdown_ctx.shutdown_requested:
                # Status will be shown in the layout, not printed separately
                live.update(generate_layout())

                # Always run post-creation setup to upload files
                post_creation_setup(
                    all_instances,
                    config,
                    update_status,
                    logger,
                    deployment_config,
                    state,
                    shared_tarball_path,
                )

                # Keep the live display running during setup
                live.update(generate_layout())
            elif not all_instances:
                rich_error("No instances were successfully created.")
            else:
                rich_warning("Creation interrupted by shutdown request")

    # Show summary
    rich_success(f"Deployment process complete for {len(all_instances)} instances.")

    # Count skipped regions
    skipped_count = sum(
        1 for item in creation_status.values() if "SKIPPED" in item["status"]
    )
    if skipped_count > 0:
        skipped_regions = set()
        for _key, item in creation_status.items():
            if "SKIPPED" in item["status"]:
                skipped_regions.add(item["region"])
        if skipped_regions:
            rich_warning(
                f"Skipped {len(skipped_regions)} region(s) due to no capacity: {', '.join(sorted(skipped_regions))}"
            )

    state.save_instances(all_instances)

    # Show deployment summary table
    if all_instances:
        summary_table = Table(
            title="📊 Deployment Summary",
            title_style="bold cyan",
            expand=True,
            padding=(0, 1),
            show_lines=True,
        )

        # Add columns with specific styles
        summary_table.add_column("Metric", style="bold white")
        summary_table.add_column("Value", style="green", justify="left")

        # Calculate summary statistics
        total_instances = len(all_instances)
        regions_used = len({inst["region"] for inst in all_instances})
        instance_types: dict[str, int] = {}
        total_cost_estimate = 0.0

        # Estimate costs (rough estimates)
        cost_per_hour = {
            "t2.micro": 0.0116,
            "t3.micro": 0.0104,
            "t3.small": 0.0208,
            "t3.medium": 0.0416,
            "t3.large": 0.0832,
            "t3.xlarge": 0.1664,
            "c5.large": 0.085,
            "c5.xlarge": 0.17,
            "m5.large": 0.096,
            "m5.xlarge": 0.192,
        }

        for inst in all_instances:
            inst_type = inst.get("type", "unknown")
            instance_types[inst_type] = instance_types.get(inst_type, 0) + 1
            total_cost_estimate += cost_per_hour.get(
                inst_type, 0.05
            )  # Default to $0.05/hr

        # Add rows to the summary table
        summary_table.add_row("Total Instances", str(total_instances))
        summary_table.add_row("Regions Used", str(regions_used))
        summary_table.add_row("Deployment ID", deployment_id)
        summary_table.add_row("Creator", creator)

        # Instance type breakdown
        type_breakdown = ", ".join(
            [f"{count}x {itype}" for itype, count in sorted(instance_types.items())]
        )
        summary_table.add_row("Instance Types", type_breakdown)

        # Cost estimate
        summary_table.add_row("Est. Cost/Hour", f"${total_cost_estimate:.2f}")
        summary_table.add_row("Est. Cost/Day", f"${total_cost_estimate * 24:.2f}")

        # Show table
        console.print("")
        console.print(summary_table)
        console.print("")

    # Show deployment completion message
    console.print("")
    rich_print("[bold green]✅ Deployment Complete![/bold green]")
    console.print("")

    # Clean up shared tarball
    if shared_tarball_path and os.path.exists(shared_tarball_path):
        try:
            os.remove(shared_tarball_path)
            logger.info(f"Cleaned up shared tarball: {shared_tarball_path}")
        except Exception as e:
            logger.warning(f"Failed to clean up tarball: {e}")

    # Import and call cmd_list to show final state
    from .list import cmd_list

    cmd_list(state)
