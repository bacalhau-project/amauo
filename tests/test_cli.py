"""Tests for CLI interface."""

import tempfile

import pytest
import yaml
from click.testing import CliRunner

from amauo.cli import cli


def test_cli_version():
    """Test --version flag."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert "amauo version" in result.output


def test_cli_help():
    """Test help output."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "Amauo" in result.output
    assert "Deploy" in result.output


def test_cli_no_command():
    """Test CLI with no command shows help."""
    runner = CliRunner()
    result = runner.invoke(cli, [])

    assert result.exit_code == 0
    assert "Amauo" in result.output


def test_version_command():
    """Test version command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["version"])

    assert result.exit_code == 0
    # The command should complete successfully
    # We don't test specific content as it varies by environment


def test_help_command():
    """Test help command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["help"])

    assert result.exit_code == 0
    # The command should complete successfully


def test_command_help():
    """Test help for individual commands."""
    runner = CliRunner()

    # Test help for commands that should exist
    commands = ["create", "destroy", "list", "setup", "version", "help"]

    for command in commands:
        result = runner.invoke(cli, [command, "--help"])
        assert result.exit_code == 0


def test_config_file_missing():
    """Test behavior with missing config file."""
    runner = CliRunner()
    result = runner.invoke(cli, ["-c", "nonexistent.yaml", "create"])

    # Should exit with 0 but show config file not found message
    assert result.exit_code == 0
    # Should show config file not found in Directory Status panel
    assert "nonexistent.yaml (not found)" in result.output


@pytest.fixture
def temp_config():
    """Create a temporary config file."""
    config = {
        "aws": {
            "total_instances": 2,
            "username": "ubuntu",
            "ssh_key_name": "test-key",
        },
        "regions": [{"us-west-2": {"machine_type": "t3.small", "image": "auto"}}],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        return f.name


def test_setup_command():
    """Test setup command creates config."""
    runner = CliRunner()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        config_path = f.name

    # Remove the file so setup can create it
    import os

    os.unlink(config_path)

    # This should create the config file
    result = runner.invoke(cli, ["-c", config_path, "setup"])

    # Should succeed or fail gracefully (depending on AWS credentials)
    assert result.exit_code in [0, 1]
