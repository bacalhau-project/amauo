#!/bin/bash
# For local dev builds - hatch-vcs automatically creates dev versions from git state

set -e

echo "🔢 Local dev build..."
echo ""

# hatch-vcs will automatically create a dev version based on:
# - Latest git tag
# - Number of commits since tag
# - Current commit hash

# Just show what version will be built
echo "Version will be determined by hatch-vcs from git state"
echo "Format: <tag>+<commits-since-tag>.g<commit-hash>"
echo ""

# Get latest tag
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "none")
echo "Latest tag: ${LATEST_TAG}"

# Get current commit
CURRENT_COMMIT=$(git rev-parse --short HEAD)
echo "Current commit: ${CURRENT_COMMIT}"

# Get commits since tag
if [ "$LATEST_TAG" != "none" ]; then
    COMMITS_SINCE=$(git rev-list "${LATEST_TAG}..HEAD" --count)
    echo "Commits since tag: ${COMMITS_SINCE}"

    if [ "$COMMITS_SINCE" -eq 0 ]; then
        echo "Expected version: ${LATEST_TAG#v} (exact tag)"
    else
        echo "Expected version: ${LATEST_TAG#v}+${COMMITS_SINCE}.g${CURRENT_COMMIT} (dev)"
    fi
else
    echo "Expected version: 0.0.0+dev.g${CURRENT_COMMIT}"
fi

echo ""
echo "✅ Ready to build with hatch-vcs"
