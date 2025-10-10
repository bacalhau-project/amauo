# 🌍 Amauo - AWS Spot Instance Deployment Tool

**Modern AWS spot instance deployment tool** for deploying Bacalhau compute nodes and sensor simulations. Features a clean Python package structure with beautiful Rich terminal output.

Deploy Bacalhau compute nodes across AWS regions using spot instances for cost-effective distributed computing.

## 🚀 **One-Command Global Deployment**

Deploy clusters across worldwide regions with a single command:

```bash
# Install and run instantly with uvx (no local setup required)
uvx amauo create

# Check status
uvx amauo list

# Setup configuration
uvx amauo setup

# Clean up
uvx amauo destroy
```

## ✨ **PyPI Package Architecture**

### 🌟 **Zero Setup Required**
- **uvx execution**: No installation or environment setup needed
- **Python packaging**: Clean CLI with Rich output and proper error handling
- **Direct AWS deployment**: Uses boto3 for native AWS integration
- **Cross-platform**: Works on any system with Python 3.12+

### 🔥 **What This Provides**
- ✅ **Instant execution** → `uvx amauo` works immediately
- ✅ **Rich terminal UI** → Beautiful tables and progress indicators
- ✅ **Proper YAML parsing** → Clean configuration management
- ✅ **Type safety** → Full type annotations throughout
- ✅ **AWS-native** → Direct boto3 integration, no container overhead

### 🎯 **Superior Features**
- **Automatic spot preemption handling** - Cost-effective deployment
- **Built-in health monitoring** - Comprehensive node validation
- **Multi-region deployment** - Distributed across AWS regions
- **Deterministic node identity** - Consistent sensor identities
- **Secure credential management** - Never commit secrets

## 🏗️ **Architecture**

### Modern Stack
- **Python Package**: PyPI-distributed CLI with Rich output
- **AWS Integration**: Direct boto3 calls for native cloud operations
- **Bacalhau**: Distributed compute with Docker engine support
- **YAML Processing**: Proper PyYAML parsing and configuration management
- **Type Safety**: Full mypy type checking throughout

### Deployment Flow
```
uvx amauo create → Python CLI → AWS boto3 → Spot Instance Deploy → Health check
```

### Package Architecture
```
PyPI Package (amauo):
├── CLI framework with Rich UI
├── AWS Resource Manager
├── SSH Manager for remote operations
├── YAML configuration parsing
├── State management (JSON-based)
└── Node identity generation
```

## 📋 **Prerequisites**

### Required
- **Python 3.12+** (for uvx, usually already installed)
- **AWS Account** with EC2 permissions
- **AWS Credentials** configured in `~/.aws/credentials` or environment

### Automatic
The CLI automatically handles:
- **AWS resource management** (VPC, Security Groups, Key Pairs)
- **Prerequisites checking** (AWS access, SSH keys)
- **YAML configuration** parsing and validation
- **File synchronization** to remote nodes

## 🎛️ **Configuration**

### Credential Setup
Create these files in the project directory before deployment:

```bash
# Required credential files
mkdir -p credentials/

# Bacalhau orchestrator endpoint
echo "nats://your-orchestrator.example.com:4222" > credentials/orchestrator_endpoint

# Bacalhau authentication token
echo "your-secret-token" > credentials/orchestrator_token

# AWS credentials for S3 access (optional)
cp ~/.aws/credentials credentials/aws-credentials
```

### Deployment Settings
Edit `config.yaml` to customize:

```yaml
aws:
  total_instances: 3
  username: ubuntu
  ssh_key_name: my-key
  files_directory: "deployment-files"
  scripts_directory: "instance/scripts"

regions:
  - us-west-2:
      machine_type: t3.medium
      image: auto  # Auto-discovers latest Ubuntu 24.04
  - us-east-1:
      machine_type: t3.medium
      image: auto
```

## 🔧 **Commands**

### Core Operations
```bash
# Deploy instances across AWS regions
uvx amauo create

# List all running instances with details
uvx amauo list

# Destroy all instances
uvx amauo destroy

# Setup initial configuration
uvx amauo setup

# Show version
uvx amauo version

# Show help
uvx amauo help

# Migrate from legacy spot-deployer
uvx amauo migrate
```

### Advanced Options
```bash
# Use custom config file (default: config.yaml)
uvx amauo create --config my-config.yaml

# Dry run to validate configuration without deploying
uvx amauo create --dry-run

# Verbose output for debugging
uvx amauo create --verbose
```

## 🧪 **Local Development & Testing**

### Quick Test
```bash
# Test the CLI without installation
uvx amauo version

# Setup configuration
uvx amauo setup

# Test with dry run
uvx amauo create --dry-run
```

### Local Development
```bash
# Clone the repository for development
git clone <repository-url>
cd amauo

# Install in development mode with uv
uv pip install -e .

# Run locally during development
python -m amauo version

# Run tests
uv run pytest

# Run linting
uv run ruff check .
```

### Debug Deployment
```bash
# Enable verbose logging for debugging
uvx amauo create --verbose

# Check instance status
uvx amauo list

# SSH to specific instance for debugging
# Use instance ID from the list command
ssh -i ~/.ssh/your-key ubuntu@instance-ip
```

### Test Individual Components
```bash
# Test node identity generation
INSTANCE_ID=i-test123 python3 instance/scripts/generate_node_identity.py

# Test Bacalhau config generation
python3 instance/scripts/generate_bacalhau_config.sh

# Check deployment logs on instance
ssh -i ~/.ssh/your-key ubuntu@instance-ip sudo tail -f /opt/deployment.log
```

## 🌐 **AWS Integration**

### Current Support
- **AWS**: Full native support with spot instances
- **Multi-region**: Deploy across multiple AWS regions simultaneously

### Cloud Provider Detection
```bash
# AWS: Uses IMDS for instance metadata
curl -s http://169.254.169.254/latest/meta-data/instance-id

# Node identity automatically detects cloud provider
# and generates appropriate sensor identities
```

## 📊 **Monitoring & Health**

### Built-in Health Checks
Every deployment includes comprehensive monitoring:

- **Docker service status**
- **Container health** (Bacalhau + Sensor)
- **Network connectivity** (API ports 1234, 4222)
- **File system status** (configs, data directories)
- **Resource utilization** (disk, memory)
- **Orchestrator connectivity**
- **Log analysis** (error detection)

### Status Dashboard
```bash
# View instance overview
uvx amauo list

# SSH to specific node for debugging
ssh -i ~/.ssh/your-key ubuntu@instance-ip

# Check deployment logs
ssh -i ~/.ssh/your-key ubuntu@instance-ip sudo tail -f /opt/deployment.log
```

## 🔒 **Security**

### Credential Management
- **Never committed to git** - credentials/ in .gitignore
- **Secure file transfer** via SSH to remote instances
- **Encrypted in transit** - SSH/TLS everywhere
- **Least privilege** - minimal required AWS permissions

### Instance Security
- **Official Ubuntu 24.04 LTS AMI** - automatically discovered
- **Security groups** with minimal required ports
- **SSH key-based access** - no password authentication
- **Automatic security updates** via cloud-init

## 🚀 **Performance**

### Deployment Speed
- **~3-5 minutes** for multi-region deployment
- **Parallel deployment** across regions via boto3
- **Fast startup time** - ~0.15 seconds CLI response

### Resource Efficiency
- **t3.medium instances** (2 vCPU, 4GB RAM) by default
- **30GB disk** per node
- **Spot pricing** - up to 90% cost savings
- **Efficient resource cleanup** on destroy

### Reliability
- **Immutable infrastructure** - destroy and recreate for changes
- **Health monitoring** with systemd services
- **Multi-region distribution** for availability
- **AWS retry logic** for transient API failures

## 🆘 **Troubleshooting**

### Common Issues

#### 1. AWS Credentials
```bash
# Check AWS access
aws sts get-caller-identity

# Configure if needed
aws configure
# or
aws sso login
```

#### 2. SSH Key Issues
```bash
# Ensure SSH key exists and has correct permissions
chmod 400 ~/.ssh/your-key.pem

# Test SSH access to instance
ssh -i ~/.ssh/your-key.pem ubuntu@instance-ip
```

#### 3. Configuration Issues
```bash
# Validate configuration file
uvx amauo create --dry-run

# Check current configuration
cat config.yaml
```

#### 4. Instance Connectivity
```bash
# List current instances
uvx amauo list

# Check instance logs
ssh -i ~/.ssh/your-key ubuntu@instance-ip sudo tail -f /opt/deployment.log
```

### Debug Commands
```bash
# Verbose deployment
uvx amauo create --verbose

# Check AWS resources directly
aws ec2 describe-instances --filters "Name=tag:amauo,Values=true"

# SSH to node for debugging
ssh -i ~/.ssh/your-key ubuntu@instance-ip
# Then run: sudo docker ps, sudo systemctl status bacalhau
```

## 🤝 **Contributing**

### Development Setup
```bash
git clone <repository-url>
cd amauo

# Install in development mode
uv pip install -e .

# Test the CLI
python -m amauo version
```

### Testing Changes
1. **Local testing**: Use `uvx amauo version` to test CLI
2. **Configuration test**: Modify `config.yaml` and test parsing
3. **Single node test**: Deploy to one region first with minimal config
4. **Full deployment test**: Test complete multi-region deployment

### Code Standards
- **Python-first** - native Python with boto3, no containers
- **Type safety** - full type annotations and mypy checking
- **Rich UI** - beautiful terminal output with progress indicators
- **Immutable infrastructure** - destroy and recreate for changes

## 📄 **License**

MIT License - see [LICENSE](LICENSE) for details.

## 🔗 **Links**

- **Bacalhau Documentation**: https://docs.bacalhau.org/
- **AWS Documentation**: https://docs.aws.amazon.com/
- **uvx Documentation**: https://docs.astral.sh/uv/guides/tools/

---

**Ready to deploy?** Ensure AWS credentials are configured, then: `uvx amauo create`
