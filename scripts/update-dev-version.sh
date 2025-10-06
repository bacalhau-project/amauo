#!/bin/bash
# Update version to latest tag + dev timestamp

set -e

echo "🔢 Updating to dev version..."
echo ""

# Get latest tag from origin/main
git fetch origin main --tags 2>/dev/null || true
LATEST_TAG=$(git tag -l 'v*' | sort -V | tail -1 | sed 's/v//')

if [ -z "$LATEST_TAG" ]; then
    echo "❌ No tags found"
    exit 1
fi

# Get current timestamp
TIMESTAMP=$(date +%Y%m%d%H%M)

# Create dev version
DEV_VERSION="${LATEST_TAG}+dev.${TIMESTAMP}"

echo "Latest tag: v${LATEST_TAG}"
echo "Dev version: ${DEV_VERSION}"
echo ""

# Update version files using Python (sed has issues with special chars)
echo "${DEV_VERSION}" > src/amauo/__version__

python3 << EOF
import re

# Update package version
with open('pyproject.toml', 'r') as f:
    content = f.read()

# Update version field (careful to only update the package version)
content = re.sub(r'^version = "[^"]+"', f'version = "${DEV_VERSION}"', content, flags=re.MULTILINE)

# Make sure target-version stays as py39 (not the package version)
content = re.sub(r'target-version = "[^"]+"', 'target-version = "py39"', content)

# Make sure python_version stays as "3.9" in mypy section
content = re.sub(r'python_version = "[^"]+"', 'python_version = "3.9"', content)

with open('pyproject.toml', 'w') as f:
    f.write(content)
EOF

echo "✅ Updated version files:"
echo "   src/amauo/__version__: ${DEV_VERSION}"
echo "   pyproject.toml: ${DEV_VERSION}"
