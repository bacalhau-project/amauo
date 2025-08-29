# Spot Deployer - Bacalhau Compute Cluster on AWS Spot Instances

A production-ready deployment tool for creating Bacalhau compute clusters on AWS spot instances. Each deployed instance automatically joins a Bacalhau cluster as a compute node, ready to process distributed computing jobs. Features portable deployment manifests, beautiful Rich terminal UI, and comprehensive state management.

## ✨ What's New

- **Updated Sensor Configuration**: Compatible with latest sensor-log-generator Docker image
- **Default Bacalhau Integration**: Each instance automatically joins the Bacalhau cluster
- **Compute Node Ready**: Instances connect to orchestrator at 147.135.16.87
- **Docker-based Deployment**: Bacalhau runs as a Docker container for easy management
- **Portable Manifests**: Define deployments with `.spot/deployment.yaml`
- **Validation**: Pre-deployment validation with `spot validate`
- **Service Management**: Automatic SystemD service installation
- **File Uploads**: Manifest-based file upload with permissions
- **Tarball Support**: Bundle and deploy local directories

## 🎯 Default: Bacalhau Compute Cluster

By default, every instance deployed will:
1. **Install Docker and Docker Compose**
2. **Run Bacalhau as a compute node** in a Docker container
3. **Connect to the orchestrator** at 147.135.16.87
4. **Join the cluster** using authentication token
5. **Start processing jobs** immediately

The Bacalhau compute nodes support:
- **Docker jobs** - Run any Docker container as a job
- **WASM jobs** - Execute WebAssembly workloads
- **Distributed computing** - Process jobs across the cluster
- **Auto-scaling** - Add more nodes as needed

## 🚀 Quick Start

### One-liner Installation (Recommended)

```bash
# List running instances with a single command!
curl -sSL https://tada.wang/install.sh | bash -s -- list

# Deploy spot instances
curl -sSL https://tada.wang/install.sh | bash -s -- create

# Destroy all instances
curl -sSL https://tada.wang/install.sh | bash -s -- destroy
```

The installer will:

- Check prerequisites (uvx, AWS credentials)
- Install uvx if needed (Python package runner)
- Set up configuration directory
- Run the deployment directly from GitHub

#### Available Commands

```bash
# Initial setup - creates default configuration
curl -sSL https://tada.wang/install.sh | bash -s -- setup

# Create spot instances
curl -sSL https://tada.wang/install.sh | bash -s -- create

# List running instances
curl -sSL https://tada.wang/install.sh | bash -s -- list

# Destroy all instances
curl -sSL https://tada.wang/install.sh | bash -s -- destroy

# Dry run - see what would happen
curl -sSL https://tada.wang/install.sh | bash -s -- create --dry-run
```

### Manual uvx Usage

```bash
# Run directly from GitHub
uvx --from git+https://github.com/bacalhau-project/aws-spot-deployer spot-deployer setup

# Deploy instances
uvx --from git+https://github.com/bacalhau-project/aws-spot-deployer spot-deployer create

# List instances
uvx --from git+https://github.com/bacalhau-project/aws-spot-deployer spot-deployer list

# Destroy instances
uvx --from git+https://github.com/bacalhau-project/aws-spot-deployer spot-deployer destroy
```

## 📋 Prerequisites

- **Python 3.12+** (uvx will be installed automatically if needed)
- **AWS Account** with EC2, VPC, and Security Group permissions
- **AWS Credentials** configured locally
- **Bacalhau Orchestrator** credentials (optional)

## 🔧 Usage

### AWS Authentication

The spot deployer includes a unified `spot` command that automatically detects and uses your AWS credentials:

```bash
# The spot command automatically detects your credentials
./spot-dev.sh create

# It will show which credentials are being used:
# 🔍 Detecting AWS credentials...
# ✓ Using AWS SSO session
# → Running spot-deployer with uvx...
```

**Supported Authentication Methods** (in order of detection):

1. **Environment Variables** - If AWS_ACCESS_KEY_ID is set
2. **EC2 Instance Role** - When running on EC2
3. **AWS SSO** - If you have an active SSO session
4. **AWS Config Files** - ~/.aws/credentials or ~/.aws/config

**Manual Authentication Options**:

1. **AWS SSO** (Recommended):
   ```bash
   # Login with SSO first
   aws sso login

   # Then use spot command
   ./spot-dev.sh create
   ```

2. **Environment Variables**:
   ```bash
   export AWS_ACCESS_KEY_ID=your-key-id
   export AWS_SECRET_ACCESS_KEY=your-secret-key
   ./spot-dev.sh create
   ```

3. **AWS Profile**:
   ```bash
   export AWS_PROFILE=myprofile
   ./spot-dev.sh create
   ```

The tool will display detailed information about which AWS credentials are being used during execution:

```
╭─────────────────── AWS Credentials ───────────────────╮
│ ✓ AWS Authentication Successful                       │
│                                                       │
│ Credential Type: AWS SSO/AssumedRole                  │
│ Credential Source: AWS SSO                            │
│ Identity: AWSReservedSSO_AdministratorAccess_xxx     │
│ Account: 123456789012                                 │
│ Region: us-west-2                                     │
╰───────────────────────────────────────────────────────╯
```



### Configuration

1. **Generate Config**:

```bash
   # Using the one-liner
   curl -sSL https://tada.wang | bash -s -- setup

   # Or using uvx directly
   uvx --from git+https://github.com/bacalhau-project/aws-spot-deployer spot-deployer setup

   # Or using the local wrapper
   ./spot-dev.sh setup
```

2. **Edit `config.yaml`**:

```yaml
   aws:
     total_instances: 10
     username: ubuntu
     use_dedicated_vpc: true
   regions:
     - us-west-2:
         machine_type: t3.medium
         image: auto
```

### Portable Deployments (NEW!)

Deploy any application using portable deployment manifests:

```bash
# Generate deployment structure
./spot-dev.sh generate

# Edit .spot/deployment.yaml
cat > .spot/deployment.yaml << 'EOF'
version: 1
packages:
  - nodejs
  - npm
scripts:
  - name: setup
    path: scripts/setup.sh
    order: 1
services:
  - webapp.service
uploads:
  - source: configs/app.config
    destination: /opt/app/config.json
EOF

# Validate deployment
./spot-dev.sh validate

# Deploy
./spot-dev.sh create
```

See [PORTABLE_DEPLOYMENT_GUIDE.md](PORTABLE_DEPLOYMENT_GUIDE.md) for complete documentation.

### Bacalhau Integration

For Bacalhau compute nodes (runs as Docker container on instances):

```bash
# Create credential files
mkdir -p files
echo "nats://orchestrator.example.com:4222" > deployment-files/orchestrator_endpoint
echo "your-secret-token" > deployment-files/orchestrator_token

# Deploy with credentials
curl -sSL https://tada.wang/install.sh | bash -s -- create

# Or using the local wrapper
./spot-dev.sh create
```

**Note**: Bacalhau runs as a Docker container (`ghcr.io/bacalhau-project/bacalhau:latest-dind`) on each instance.

### Sensor Simulation

The sensor log generator runs alongside Bacalhau to simulate IoT sensor data:

```yaml
# Sensor docker-compose.yml configuration
services:
  sensor-simulators:
    image: ghcr.io/bacalhau-project/sensor-log-generator:latest
    pull_policy: always
    restart: unless-stopped
    environment:
      - CONFIG_FILE=/config/config.yaml
      - IDENTITY_FILE=/config/node-identity.json
    volumes:
      - ./config:/config
      - ./data:/app/data  # Database persistence
      - ./logs:/app/logs  # Log files
      - ./exports:/app/exports  # Data exports
```

The sensor generator:
- **Always pulls the latest image** on deployment
- **Uses simplified paths** for configuration files
- **Persists data** in local SQLite database
- **Generates realistic sensor data** based on node identity

### Custom Commands

Run custom setup commands on each instance by creating `additional_commands.sh`:

```bash
# Create custom commands script
cat > additional_commands.sh << 'EOF'
#!/bin/bash
# Custom setup commands run after deployment

echo "[$(date)] Running custom commands"

# Example: Install additional software
sudo apt-get update
sudo apt-get install -y htop iotop

# Example: Configure monitoring
echo "custom-monitoring-config" > /opt/monitoring.conf

# Example: Set up custom environment
echo "export CUSTOM_VAR=value" >> /home/ubuntu/.bashrc

echo "[$(date)] Custom commands completed"
EOF

chmod +x additional_commands.sh

# Deploy with custom commands (script is automatically detected)
./spot-dev.sh create
```

The `additional_commands.sh` script will be uploaded to each instance and executed during deployment.

### Local Installation

For frequent use, clone the repository and use the local wrapper:

```bash
# Clone repository
git clone https://github.com/bacalhau-project/aws-spot-deployer.git
cd aws-spot-deployer

# Use the spot-dev wrapper (auto-detects AWS credentials)
./spot-dev.sh setup
./spot-dev.sh create
./spot-dev.sh list
./spot-dev.sh destroy
```

## 🎨 Features

- **No Docker Required** - Deployment tool runs via uvx (Python package runner)
- **Beautiful Terminal UI** - Rich tables and progress tracking
- **Hands-Off Deployment** - No SSH connection held during setup
- **State Management** - Automatic state tracking via AWS tags
- **Multi-Region** - Deploy across multiple AWS regions
- **Dedicated VPCs** - Isolated network per deployment
- **Bacalhau Ready** - Compute nodes run as Docker containers on instances
- **Sensor Simulation** - Compatible with latest sensor-log-generator Docker image
- **Custom Commands** - Run your own setup scripts on instances

## 📁 Configuration Options

See [config.yaml.example](config.yaml.example) for all available options:

- Instance types and counts
- Region selection
- VPC configuration
- SSH key settings
- Bacalhau integration
- Custom scripts and commands

## 🆘 Troubleshooting

### No AWS Credentials Found

Ensure AWS credentials are available:

```bash
# Check credentials
aws sts get-caller-identity

# Or use environment variables
export AWS_ACCESS_KEY_ID=xxx
export AWS_SECRET_ACCESS_KEY=yyy
```

### No Config File Found

Create a config file first:

```bash
curl -sSL https://tada.wang | bash -s -- setup
# or
./spot-dev.sh setup
```

### Permission Denied

Ensure proper file permissions:

- Check file ownership in current directory
- Verify AWS credentials are readable
- Ensure SSH keys have correct permissions (600)

### Debugging Deployments

Use the debug script after deployment:

```bash
# Download debug script
curl -O https://raw.githubusercontent.com/bacalhau-project/spot/main/debug_deployment.sh
chmod +x debug_deployment.sh

# Run diagnostics
./debug_deployment.sh <instance-ip>
```

## 📦 Architecture

### Deployment Tool (Your Machine)
- Runs via **uvx** - no Docker required
- Instant execution from GitHub
- Automatic dependency management

### On EC2 Instances
- **Bacalhau**: Runs as Docker container (`ghcr.io/bacalhau-project/bacalhau:latest-dind`)
- **Sensor Generator**: Runs as Docker container (`ghcr.io/bacalhau-project/sensor-log-generator:latest`)
  - Updated configuration for compatibility with latest image
  - Simplified volume mounts: `/config` for configuration, `/app/data` for persistence
  - Always pulls latest image on deployment
- **Docker**: Automatically installed via cloud-init
- **SystemD**: Manages container lifecycle

## 🚦 Development

For development and contributions:

```bash
# Clone repository
git clone https://github.com/bacalhau-project/aws-spot-deployer.git
cd aws-spot-deployer

# Set up development environment
uv sync

# Install pre-commit hooks (IMPORTANT: prevents CI failures)
uv run pre-commit install

# Run pre-commit manually on all files
uv run pre-commit run --all-files

# Run locally with uv
uv run python -m spot_deployer help

# Or use the development wrapper
./spot-dev help
```

### Code Quality

This project uses:
- **ruff** for linting and formatting
- **mypy** for type checking
- **pre-commit** hooks to ensure code quality

**Important**: Always install pre-commit hooks after cloning to avoid CI failures:
```bash
uv run pre-commit install
```

## 📄 License

[Your License Here]

## 🤝 Support

- **Issues**: [GitHub Issues](https://github.com/bacalhau-project/aws-spot-deployer/issues)
- **Configuration**: [config.yaml.example](config.yaml.example)
- **Debug Guide**: [DEPLOYMENT_DEBUG_CHECKLIST.md](DEPLOYMENT_DEBUG_CHECKLIST.md)
