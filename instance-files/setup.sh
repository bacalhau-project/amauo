#!/bin/bash
# Main setup script for deployment
# This script runs after the deployment package is extracted

set -e  # Exit on error

echo "Starting amauo deployment setup..."


# First, deploy files from the extracted structure to their proper locations
echo "Deploying files to system locations..."

# Deploy usr files
if [ -d "usr" ]; then
    sudo cp -r usr/* /usr/ 2>/dev/null || true
fi

# Deploy etc files
if [ -d "etc" ]; then
    sudo cp -r etc/* /etc/ 2>/dev/null || true
fi

# Deploy opt files
if [ -d "opt" ]; then
    sudo cp -r opt/* /opt/ 2>/dev/null || true
fi

# Set proper permissions for scripts and services (be very specific)
find /usr/local/bin -name "*.py" -exec sudo chmod 755 {} \; 2>/dev/null || true
find /usr/local/bin -name "*.sh" -exec sudo chmod 755 {} \; 2>/dev/null || true
find /etc/systemd/system -name "*.service" -exec sudo chmod 644 {} \; 2>/dev/null || true

echo "Files deployed successfully"

# Install uv (required for Python scripts) as ubuntu user
if ! sudo -u ubuntu bash -c 'command -v uv' &> /dev/null; then
    echo "Installing uv..."
    sudo -u ubuntu bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
    # Create system-wide symlink for uv so shebangs work
    sudo ln -sf /home/ubuntu/.local/bin/uv /usr/local/bin/uv
    sudo ln -sf /home/ubuntu/.local/bin/uvx /usr/local/bin/uvx
    echo "uv installed successfully and made available system-wide"
else
    echo "uv already installed"
fi

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."

    # Install GPG tools first to fix verification issues
    sudo apt-get update -qq || true
    sudo apt-get install -y gnupg lsb-release ca-certificates curl || true

    # Try the official Docker installation script
    if curl -fsSL https://get.docker.com -o /tmp/get-docker.sh 2>/dev/null; then
        sudo sh /tmp/get-docker.sh 2>/dev/null || {
            echo "Docker script failed, trying alternative installation..."
            # Fallback: install from Ubuntu repositories
            sudo apt-get update -qq || true
            sudo apt-get install -y docker.io docker-compose || true
        }
    else
        echo "Could not download Docker script, using package manager..."
        sudo apt-get update -qq || true
        sudo apt-get install -y docker.io docker-compose || true
    fi

    # Configure Docker
    sudo usermod -aG docker ubuntu || true
    sudo systemctl enable docker || true
    sudo systemctl start docker || true

    # Clean up
    rm -f /tmp/get-docker.sh

    # Verify installation
    if command -v docker &> /dev/null; then
        echo "Docker installed and started successfully"
    else
        echo "Warning: Docker installation may have failed"
    fi
else
    echo "Docker already installed"
fi

# Wait for Docker to be ready
echo "Waiting for Docker to be ready..."
sleep 5

# Reload systemd daemon to pick up new service files
sudo systemctl daemon-reload

# Enable services
echo "Enabling services..."
sudo systemctl enable bacalhau.service 2>/dev/null && echo "Enabled bacalhau.service" || echo "Could not enable bacalhau.service"
sudo systemctl enable sensor.service 2>/dev/null && echo "Enabled sensor.service" || echo "Could not enable sensor.service"

# Set up proper ownership and permissions for data directories
sudo mkdir -p /bacalhau_data /bacalhau_node /opt/bacalhau_node
sudo mkdir -p /opt/sensor/config /opt/sensor/logs /opt/sensor/data /opt/sensor/exports
sudo chown -R ubuntu:ubuntu /bacalhau_data /bacalhau_node /opt/compose /opt/sensor 2>/dev/null || true
sudo chmod 755 /bacalhau_data /bacalhau_node /opt/sensor 2>/dev/null || true

# Docker compose file is used directly from /opt/compose/ - no copying needed


# Generate Bacalhau configuration from template - STRICT MODE
echo "Generating Bacalhau configuration from template..."

# STRICT: Check for required files
if [ ! -f /etc/bacalhau/bacalhau-config-template.yaml ]; then
    echo "ERROR: Bacalhau config template not found at /etc/bacalhau/bacalhau-config-template.yaml"
    echo "ERROR: Required template file is missing from deployment"
    exit 1
fi

if [ ! -f /etc/bacalhau/orchestrator_endpoint ]; then
    echo "ERROR: Orchestrator endpoint file not found at /etc/bacalhau/orchestrator_endpoint"
    echo "ERROR: Required credential file is missing from deployment"
    exit 1
fi

if [ ! -f /etc/bacalhau/orchestrator_token ]; then
    echo "ERROR: Orchestrator token file not found at /etc/bacalhau/orchestrator_token"
    echo "ERROR: Required credential file is missing from deployment"
    exit 1
fi

# STRICT: Read credentials and validate
ENDPOINT=$(cat /etc/bacalhau/orchestrator_endpoint | tr -d '[:space:]')
TOKEN=$(cat /etc/bacalhau/orchestrator_token | tr -d '[:space:]')

if [ -z "$ENDPOINT" ]; then
    echo "ERROR: Orchestrator endpoint is empty"
    echo "ERROR: Invalid or empty orchestrator endpoint file"
    exit 1
fi

if [ -z "$TOKEN" ]; then
    echo "ERROR: Orchestrator token is empty"
    echo "ERROR: Invalid or empty orchestrator token file"
    exit 1
fi

# Get instance metadata for node labeling
echo "Retrieving instance metadata..."
INSTANCE_ID=$(curl -s --max-time 5 http://169.254.169.254/latest/meta-data/instance-id || echo "unknown")
REGION=$(curl -s --max-time 5 http://169.254.169.254/latest/meta-data/placement/region || echo "unknown")

if [ "$INSTANCE_ID" = "unknown" ]; then
    echo "WARNING: Could not retrieve instance ID from metadata service"
    INSTANCE_ID=$(hostname)
fi

    if [ -z "$REGION" ] || [ "$REGION" = "unknown" ]; then
        echo "WARNING: Could not retrieve region from metadata service"
        REGION="us-west-2"
        echo "INFO: Using default region: $REGION"
    fi
else
    echo "WARNING: EC2 metadata service is not accessible"
    INSTANCE_ID=$(hostname)
    REGION="us-west-2"
fi

echo "SUCCESS: Using orchestrator endpoint: $ENDPOINT"
echo "SUCCESS: Using orchestrator token: ${TOKEN:0:15}..."
echo "SUCCESS: Instance ID: $INSTANCE_ID"
echo "SUCCESS: Region: $REGION"

# STRICT: Render template with validation
echo "SUCCESS: Rendering Bacalhau config from template..."
echo "DEBUG: Template substitution variables:"
echo "  ENDPOINT='$ENDPOINT'"
echo "  TOKEN='${TOKEN:0:15}...'"
echo "  INSTANCE_ID='$INSTANCE_ID'"
echo "  REGION='$REGION'"

# Generate the config with substitution
if ! sed -e "s|{{ORCHESTRATOR_ENDPOINT}}|$ENDPOINT|g" \
         -e "s|{{ORCHESTRATOR_TOKEN}}|$TOKEN|g" \
         -e "s|{{INSTANCE_ID}}|$INSTANCE_ID|g" \
         -e "s|{{REGION}}|$REGION|g" \
         /etc/bacalhau/bacalhau-config-template.yaml | sudo -u ubuntu tee /bacalhau_node/config.yaml > /dev/null; then
    echo "ERROR: Failed to render Bacalhau config template"
    echo "ERROR: Template rendering failed - deployment aborted"
    exit 1
fi

echo "SUCCESS: Bacalhau configuration generated from template"

# Debug: Show a few key lines from generated config
echo "DEBUG: Generated config preview:"
grep -A 1 -E "(Name:|ClientID:|Token:|Orchestrators:)" /bacalhau_node/config.yaml | head -10

# CRITICAL: Validate that template substitution actually worked
if grep -q "{{" /bacalhau_node/config.yaml; then
    echo "ERROR: Template placeholders still found in generated config!"
    echo "ERROR: Failed substitution patterns:"
    grep "{{" /bacalhau_node/config.yaml
    echo "ERROR: This indicates template substitution failed - aborting"
    exit 1
fi

# Validate that the node has a unique identifier
if ! grep -q "Name.*bacalhau-" /bacalhau_node/config.yaml; then
    echo "ERROR: Node name not properly configured"
    echo "ERROR: Node identity validation failed - aborting"
    exit 1
fi

echo "SUCCESS: Configuration validation passed"

# Debug: Show a few key lines from generated config
echo "DEBUG: Generated config preview:"
grep -A 1 -E "(Token:|Orchestrators:|NameProvider:)" /bacalhau_node/config.yaml | head -10

# CRITICAL: Validate that template substitution actually worked
if grep -q "{{" /bacalhau_node/config.yaml; then
    echo "ERROR: Template placeholders still found in generated config!"
    echo "ERROR: Failed substitution patterns:"
    grep "{{" /bacalhau_node/config.yaml
    echo "ERROR: This indicates template substitution failed - aborting"
    exit 1
fi

echo "SUCCESS: Configuration validation passed"

# Create a node-specific Docker Compose file with proper node name
echo "Creating node-specific Docker Compose configuration..."
NODE_NAME="bacalhau-${INSTANCE_ID:-$(hostname)}"
sed "s|command: \\[\"serve\", \"--config\", \"/etc/bacalhau/config.yaml\"\\]|command: [\"serve\", \"--config\", \"/etc/bacalhau/config.yaml\", \"--name\", \"$NODE_NAME\"]|" /opt/compose/docker-compose-bacalhau.yaml > /opt/compose/docker-compose-bacalhau-node.yaml

echo "DEBUG: Created node-specific compose with name: $NODE_NAME"


# Setup AWS credentials for Bacalhau compute nodes (for S3 job access)
echo "Setting up AWS credentials..."
AWS_CREDS_SOURCE="/etc/aws/credentials/aws-credentials"
if [ -f "$AWS_CREDS_SOURCE" ]; then
    # Setup for root user (Docker containers including Bacalhau)
    sudo mkdir -p /root/.aws
    sudo cp "$AWS_CREDS_SOURCE" /root/.aws/credentials
    sudo chown root:root /root/.aws/credentials
    sudo chmod 600 /root/.aws/credentials

    # Create basic AWS config for root
    sudo tee /root/.aws/config > /dev/null << EOF
[default]
region = us-west-2
output = json
EOF
    sudo chown root:root /root/.aws/config
    sudo chmod 600 /root/.aws/config

    # Setup for ubuntu user
    sudo mkdir -p /home/ubuntu/.aws
    sudo cp "$AWS_CREDS_SOURCE" /home/ubuntu/.aws/credentials
    sudo chown ubuntu:ubuntu /home/ubuntu/.aws/credentials
    sudo chmod 600 /home/ubuntu/.aws/credentials

    # Create basic AWS config for ubuntu
    sudo tee /home/ubuntu/.aws/config > /dev/null << EOF
[default]
region = us-west-2
output = json
EOF
    sudo chown ubuntu:ubuntu /home/ubuntu/.aws/config
    sudo chmod 600 /home/ubuntu/.aws/config

    echo "SUCCESS: AWS credentials and config set up for both root and ubuntu users"
    echo "INFO: Bacalhau compute jobs will have S3 access via mounted credentials"
    echo "INFO: Sensor simulator writes to host directories only - no AWS access needed"
else
    echo "WARNING: AWS credentials not found at $AWS_CREDS_SOURCE"
    echo "INFO: Bacalhau nodes may not be able to access S3 (sensor simulator doesn't need S3)"
fi

# Setup AWS credentials for Bacalhau compute nodes (for S3 job access)
echo "Setting up AWS credentials..."
AWS_CREDS_SOURCE="/etc/aws/credentials/aws-credentials"
if [ -f "$AWS_CREDS_SOURCE" ]; then
    # Setup for root user (Docker containers including Bacalhau)
    sudo mkdir -p /root/.aws
    sudo cp "$AWS_CREDS_SOURCE" /root/.aws/credentials
    sudo chown root:root /root/.aws/credentials
    sudo chmod 600 /root/.aws/credentials

    # Create basic AWS config for root
    sudo tee /root/.aws/config > /dev/null << EOF
[default]
region = us-west-2
output = json
EOF
    sudo chown root:root /root/.aws/config
    sudo chmod 600 /root/.aws/config

    # Setup for ubuntu user
    sudo mkdir -p /home/ubuntu/.aws
    sudo cp "$AWS_CREDS_SOURCE" /home/ubuntu/.aws/credentials
    sudo chown ubuntu:ubuntu /home/ubuntu/.aws/credentials
    sudo chmod 600 /home/ubuntu/.aws/credentials

    # Create basic AWS config for ubuntu
    sudo -u ubuntu tee /home/ubuntu/.aws/config > /dev/null << EOF
[default]
region = us-west-2
output = json
EOF
    sudo chmod 600 /home/ubuntu/.aws/config

    echo "SUCCESS: AWS credentials and config set up for both root and ubuntu users"
    echo "INFO: Bacalhau compute jobs will have S3 access via mounted credentials"
    echo "INFO: Sensor simulator writes to host directories only - no AWS access needed"
else
    echo "WARNING: AWS credentials not found at $AWS_CREDS_SOURCE"
    echo "INFO: Bacalhau nodes may not be able to access S3 (sensor simulator doesn't need S3)"
fi

# Generate node identity if the script exists
if [ -x /usr/local/bin/generate_node_identity.py ]; then
    echo "Generating node identity..."
    # Run the script with proper output path (uv should now be available system-wide)
    sudo -u ubuntu /usr/local/bin/generate_node_identity.py -o /opt/sensor/config/node_identity.json
fi

# Start services (Docker should be ready now)
echo "Starting services..."
sudo systemctl start bacalhau.service 2>/dev/null && echo "Started bacalhau.service" || echo "Could not start bacalhau.service"
sudo systemctl start sensor.service 2>/dev/null && echo "Started sensor.service" || echo "Could not start sensor.service"

echo "✅ Amauo deployment setup complete!"

# Create completion marker for deploy_services.py
sudo touch /opt/amauo_setup_complete
sudo chown ubuntu:ubuntu /opt/amauo_setup_complete
