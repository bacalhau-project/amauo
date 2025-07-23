#!/bin/bash
# Convenience wrapper for running spot-deployer in Docker

REGISTRY="${SPOT_REGISTRY:-ghcr.io}"
IMAGE_NAME="${SPOT_IMAGE:-bacalhau-project/spot-deployer}"
VERSION="${SPOT_VERSION:-latest}"
FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${VERSION}"

# Default directories
CONFIG_FILE="${SPOT_CONFIG:-./config.yaml}"
FILES_DIR="${SPOT_FILES:-./files}"
OUTPUT_DIR="${SPOT_OUTPUT:-./output}"

# Build volume mount arguments
VOLUMES=""

# Always mount AWS credentials if they exist
if [ -d "$HOME/.aws" ]; then
    VOLUMES="$VOLUMES -v $HOME/.aws:/root/.aws:ro"
elif [ -n "$AWS_ACCESS_KEY_ID" ]; then
    echo "Using AWS credentials from environment"
else
    echo "⚠️  Warning: No AWS credentials found"
fi

# Mount SSH directory for key access
if [ -d "$HOME/.ssh" ]; then
    VOLUMES="$VOLUMES -v $HOME/.ssh:/root/.ssh:ro"
fi

# Mount config file if it exists (not needed for setup/help)
if [ -f "$CONFIG_FILE" ]; then
    VOLUMES="$VOLUMES -v $(realpath $CONFIG_FILE):/app/config/config.yaml:ro"
fi

# Mount files directory if it exists
if [ -d "$FILES_DIR" ]; then
    VOLUMES="$VOLUMES -v $(realpath $FILES_DIR):/app/files:ro"
fi

# Mount output directory
mkdir -p "$OUTPUT_DIR"
VOLUMES="$VOLUMES -v $(realpath $OUTPUT_DIR):/app/output"

# Pass through environment variables
ENV_VARS=""

# Check if using AWS SSO and export credentials if available
if [ -d "$HOME/.aws/sso" ] && command -v aws >/dev/null 2>&1; then
    if aws sts get-caller-identity >/dev/null 2>&1; then
        # Export SSO credentials as environment variables
        echo "Detected AWS SSO session, exporting credentials..."
        eval $(aws configure export-credentials --format env 2>/dev/null || true)
    fi
fi

# Pass AWS environment variables if they exist
if [ -n "$AWS_ACCESS_KEY_ID" ]; then
    ENV_VARS="$ENV_VARS -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY"
fi
if [ -n "$AWS_SESSION_TOKEN" ]; then
    ENV_VARS="$ENV_VARS -e AWS_SESSION_TOKEN"
fi
if [ -n "$AWS_DEFAULT_REGION" ]; then
    ENV_VARS="$ENV_VARS -e AWS_DEFAULT_REGION"
fi
if [ -n "$AWS_REGION" ]; then
    ENV_VARS="$ENV_VARS -e AWS_REGION"
fi

# Run the container
exec docker run --rm -it \
    $VOLUMES \
    $ENV_VARS \
    -e TERM=xterm-256color \
    -e COLUMNS=$(tput cols) \
    -e LINES=$(tput lines) \
    "$FULL_IMAGE" \
    "$@"
