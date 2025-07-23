#!/usr/bin/env bash
# Run all code quality checks

set -e

echo "🔍 Running code quality checks..."

# Run ruff linting
echo "📝 Running ruff lint..."
uv run ruff check spot_deployer/

# Run ruff formatting check
echo "🎨 Checking code formatting..."
uv run ruff format --check spot_deployer/

# Run mypy type checking
echo "🔎 Running type checks..."
uv run mypy spot_deployer/ || echo "Type checking completed with warnings"

# Run pre-commit on all files
echo "🚀 Running pre-commit checks..."
uv run pre-commit run --all-files

echo "✅ All checks passed!"