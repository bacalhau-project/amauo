"""
Command-line interface for amauo.

Provides a Click-based CLI for deploying and managing Bacalhau compute nodes
across multiple AWS regions using spot instances.
"""

import os
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel

from . import get_runtime_version
from .commands import (
    cmd_cleanup,
    cmd_create,
    cmd_destroy,
    cmd_generate,
    cmd_help,
    cmd_list,
    cmd_nuke,
    cmd_random_ip,
    cmd_readme,
    cmd_setup,
    cmd_validate,
    cmd_version,
)
from .core.config import SimpleConfig
from .core.state import SimpleStateManager

console = Console()


def _show_directory_status(
    config_path: str, config_obj: Optional[SimpleConfig] = None
) -> None:
    """Show status of key directories and files."""
    info_lines = []

    # Working directory
    cwd = os.getcwd()
    info_lines.append(f"Working Directory: [cyan]{cwd}[/cyan]")

    # Config file
    config_file = Path(config_path)
    if config_file.exists():
        info_lines.append(f"Config File: [green]✅ {config_file.absolute()}[/green]")
    else:
        info_lines.append(
            f"Config File: [red]❌ {config_file.absolute()} (not found)[/red]"
        )

    # Instance state file
    instances_file = Path("instances.json")
    if instances_file.exists():
        info_lines.append(
            f"Instance State: [green]✅ {instances_file.absolute()}[/green]"
        )
    else:
        info_lines.append(
            f"Instance State: [yellow]⚠️ {instances_file.absolute()} (will be created)[/yellow]"
        )

    # Files directory (from config if available)
    files_dir = None
    if config_obj:
        try:
            files_dir = Path(config_obj.files_directory())
        except Exception:
            # Default fallback
            files_dir = Path("files")
    else:
        # Default fallback
        files_dir = Path("files")

    if files_dir and files_dir.exists():
        info_lines.append(f"Files Directory: [green]✅ {files_dir.absolute()}[/green]")
    else:
        info_lines.append(
            f"Files Directory: [red]❌ {files_dir.absolute() if files_dir else 'Not configured'} (not found)[/red]"
        )

    # AWS credentials
    aws_creds_file = Path.home() / ".aws" / "credentials"
    aws_env = os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_PROFILE")
    if aws_creds_file.exists() or aws_env:
        info_lines.append("AWS Credentials: [green]✅ Configured[/green]")
    else:
        info_lines.append(
            "AWS Credentials: [red]❌ Not found (~/.aws/credentials or environment)[/red]"
        )

    # Cache directory
    cache_dir = Path(".aws_cache")
    if cache_dir.exists():
        info_lines.append(f"AMI Cache: [green]✅ {cache_dir.absolute()}[/green]")
    else:
        info_lines.append(
            f"AMI Cache: [yellow]⚠️ {cache_dir.absolute()} (will be created)[/yellow]"
        )

    panel = Panel(
        "\n".join(info_lines),
        title="[bold]📁 Directory Status[/bold]",
        border_style="blue",
        padding=(0, 1),
    )
    console.print(panel)


@click.group(invoke_without_command=True)
@click.option(
    "-c",
    "--config",
    default="config.yaml",
    help="Config file path",
    show_default=True,
)
@click.option(
    "--version",
    is_flag=True,
    help="Show version and exit",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug mode with log files",
)
@click.pass_context
def cli(
    ctx: click.Context,
    config: str,
    version: bool,
    debug: bool,
) -> None:
    """
    🌟 Amauo - Deploy Bacalhau compute nodes effortlessly across the cloud.

    Deploy Bacalhau compute nodes across multiple cloud regions using spot instances
    for cost-effective distributed computing.

    Examples:
        uvx amauo create              # Deploy nodes
        uvx amauo list                # List nodes
        uvx amauo destroy             # Clean up
        uvx amauo setup               # Initial setup
    """
    if version:
        runtime_version = get_runtime_version()
        click.echo(f"amauo version {runtime_version}")
        sys.exit(0)

    # Store common options in context
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["debug"] = debug

    # Initialize core components
    try:
        ctx.obj["config"] = SimpleConfig(config)
        ctx.obj["state"] = SimpleStateManager()

        # Show directory status for operational commands
        if ctx.invoked_subcommand in ["create", "destroy", "list", "validate"]:
            _show_directory_status(config, ctx.obj["config"])

    except Exception as e:
        if ctx.invoked_subcommand not in ["setup", "help", "version"]:
            # Show directory status even on error to help troubleshooting
            _show_directory_status(config)
            console.print(f"[red]❌ Config error: {e}[/red]")
            console.print("[yellow]💡 Try running 'amauo setup' first[/yellow]")
            sys.exit(1)

    # Show help if no command provided
    if ctx.invoked_subcommand is None:
        runtime_version = get_runtime_version()
        click.echo(f"Amauo v{runtime_version}")
        click.echo(ctx.get_help())


@cli.command()
@click.pass_context
def create(ctx: click.Context) -> None:
    """Deploy Bacalhau compute nodes across multiple regions."""
    config: SimpleConfig = ctx.obj["config"]
    state: SimpleStateManager = ctx.obj["state"]
    debug: bool = ctx.obj.get("debug", False)

    try:
        cmd_create(config, state, debug=debug)
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Deployment interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]❌ Deployment failed: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.pass_context
def destroy(ctx: click.Context) -> None:
    """Destroy all instances and clean up resources."""
    config: SimpleConfig = ctx.obj["config"]
    state: SimpleStateManager = ctx.obj["state"]
    debug: bool = ctx.obj.get("debug", False)

    try:
        cmd_destroy(config=config, state=state, debug=debug)
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Destruction interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]❌ Destruction failed: {e}[/red]")
        sys.exit(1)


@cli.command(name="list")
@click.pass_context
def list_nodes(ctx: click.Context) -> None:
    """List all running instances with detailed information."""
    state: SimpleStateManager = ctx.obj["state"]

    try:
        cmd_list(state)
    except Exception as e:
        console.print(f"[red]❌ List failed: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.pass_context
def setup(ctx: click.Context) -> None:
    """Set up initial configuration."""
    config_path: str = ctx.obj["config_path"]

    try:
        # Create config if it doesn't exist, then initialize it
        config_file = Path(config_path)
        if not config_file.exists():
            # Create minimal config
            config_file.write_text("""# Amauo Configuration
aws:
  total_instances: 3
  username: ubuntu
  ssh_key_name: ""
  public_ssh_key_path: ""
  private_ssh_key_path: ""

regions:
  - us-west-2:
      machine_type: t3.medium
      image: auto
""")

        config = SimpleConfig(config_path)
        cmd_setup(config)
    except Exception as e:
        console.print(f"[red]❌ Setup failed: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.pass_context
def nuke(ctx: click.Context) -> None:
    """Emergency cleanup - destroy ALL instances across ALL regions."""
    config: SimpleConfig = ctx.obj["config"]
    state: SimpleStateManager = ctx.obj["state"]

    try:
        cmd_nuke(config=config, state=state)
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Nuke interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]❌ Nuke failed: {e}[/red]")
        sys.exit(1)


@cli.command()
def generate() -> None:
    """Generate deployment structure and templates."""
    try:
        cmd_generate()
    except Exception as e:
        console.print(f"[red]❌ Generate failed: {e}[/red]")
        sys.exit(1)


@cli.command()
def version() -> None:
    """Show detailed version information."""
    try:
        cmd_version()
    except Exception as e:
        console.print(f"[red]❌ Version failed: {e}[/red]")
        sys.exit(1)


@cli.command()
def help() -> None:
    """Show detailed help information."""
    try:
        cmd_help()
    except Exception as e:
        console.print(f"[red]❌ Help failed: {e}[/red]")
        sys.exit(1)


@cli.command(name="random-ip")
@click.pass_context
def random_ip(ctx: click.Context) -> None:
    """Get random instance IP for SSH access."""
    state: SimpleStateManager = ctx.obj["state"]

    try:
        cmd_random_ip(state)
    except Exception as e:
        console.print(f"[red]❌ Random IP failed: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.pass_context
def readme(ctx: click.Context) -> None:
    """Show deployment information and status."""
    # state: SimpleStateManager = ctx.obj["state"]  # Unused for readme command

    try:
        cmd_readme()
    except Exception as e:
        console.print(f"[red]❌ Readme failed: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.pass_context
def validate(ctx: click.Context) -> None:
    """Validate deployment configuration before deployment."""
    config: SimpleConfig = ctx.obj["config"]
    state: SimpleStateManager = ctx.obj["state"]

    try:
        cmd_validate(config, state)
    except Exception as e:
        console.print(f"[red]❌ Validate failed: {e}[/red]")
        sys.exit(1)


@cli.command()
def cleanup() -> None:
    """Clean up temporary files and prevent conflicts."""
    try:
        cmd_cleanup()
    except Exception as e:
        console.print(f"[red]❌ Cleanup failed: {e}[/red]")
        sys.exit(1)


def main() -> None:
    """Entry point for the CLI."""
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]❌ Unexpected error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
