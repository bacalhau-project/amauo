#!/bin/bash
# Build and test amauo locally

set -e

echo "🔨 Building and testing amauo..."
echo ""

# Update to dev version
echo "📝 Updating version..."
./scripts/update-dev-version.sh
echo ""

# Build package
echo "📦 Building package..."
uv build
echo ""

# Install locally
echo "🔧 Installing locally..."
uv tool install --force .
echo ""

# Verify installation
echo "✅ Verifying installation..."
VERSION=$(amauo --version 2>&1 || echo "ERROR")
if [[ "$VERSION" == *"ERROR"* ]]; then
    echo "❌ Installation failed"
    exit 1
fi
echo "   Version: $VERSION"
echo ""

# Run basic checks
echo "🧪 Running basic checks..."
echo "   • Help command..."
amauo help > /dev/null 2>&1 && echo "     ✓ Help works" || echo "     ✗ Help failed"
echo "   • Version command..."
amauo version > /dev/null 2>&1 && echo "     ✓ Version works" || echo "     ✗ Version failed"
echo ""

echo "✅ Build complete!"
echo ""
echo "Next steps:"
echo "  - Test deployment: amauo -c test-config.yaml create"
echo "  - Test debug mode: amauo --debug -c test-config.yaml create"
echo "  - Run pre-commit: SKIP=pytest-tests uv run pre-commit run --all-files"
echo "  - Commit: SKIP=pytest-tests git commit -m 'your message'"
