"""
Command-line interface for spot-deployer.

Provides a Click-based CLI for deploying and managing SkyPilot clusters.
"""

import sys
from pathlib import Path

import click
from rich.console import Console

from . import get_runtime_version
from .manager import ClusterManager

console = Console()


@click.group(invoke_without_command=True)
@click.option(
    "-c",
    "--config",
    default="cluster.yaml",
    help="Config file path",
    show_default=True,
)
@click.option(
    "-f",
    "--console",
    is_flag=True,
    help="Show logs to console instead of log file",
)
@click.option(
    "--log-file",
    default="cluster-deploy.log",
    help="Log file path",
    show_default=True,
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable detailed debug logging",
)
@click.option(
    "--version",
    is_flag=True,
    help="Show version and exit",
)
@click.pass_context
def cli(
    ctx: click.Context,
    config: str,
    console: bool,
    log_file: str,
    debug: bool,
    version: bool,
) -> None:
    """
    🌟 Amauo - Deploy clusters effortlessly across the cloud.

    Deploy Bacalhau compute nodes across multiple cloud regions using SkyPilot
    for cloud orchestration and spot instance management.

    Examples:
        uvx amauo create              # Deploy cluster
        uvx amauo status              # Check status
        uvx amauo list                # List nodes
        uvx amauo destroy             # Clean up
    """
    if version:
        runtime_version = get_runtime_version()
        click.echo(f"amauo version {runtime_version}")
        sys.exit(0)

    # Store common options in context
    ctx.ensure_object(dict)
    ctx.obj["config"] = config
    ctx.obj["console"] = console
    ctx.obj["log_file"] = log_file
    ctx.obj["debug"] = debug
    ctx.obj["manager"] = ClusterManager(
        log_to_console=console, log_file=log_file, debug=debug
    )

    # Show help if no command provided
    if ctx.invoked_subcommand is None:
        runtime_version = get_runtime_version()
        click.echo(f"Amauo v{runtime_version}")
        click.echo(ctx.get_help())


@cli.command()
@click.option(
    "--follow",
    "-f",
    is_flag=True,
    help="Follow deployment progress with real-time monitoring",
)
@click.pass_context
def create(ctx: click.Context, follow: bool) -> None:
    """Deploy a global cluster across multiple regions."""
    manager: ClusterManager = ctx.obj["manager"]
    config_file: str = ctx.obj["config"]

    if not Path(config_file).exists():
        console.print(f"[red]❌ Config file not found: {config_file}[/red]")
        console.print(
            f"[yellow]Create {config_file} or use -c to specify a different file[/yellow]"
        )
        sys.exit(1)

    runtime_version = get_runtime_version()
    console.print(f"[blue]Amauo v{runtime_version}[/blue]")

    if not manager.check_prerequisites():
        sys.exit(1)

    if not manager.deploy_cluster(config_file, follow=follow):
        sys.exit(1)


@cli.command()
@click.pass_context
def destroy(ctx: click.Context) -> None:
    """Destroy the cluster and clean up all resources."""
    manager: ClusterManager = ctx.obj["manager"]

    runtime_version = get_runtime_version()
    console.print(f"[blue]Amauo v{runtime_version}[/blue]")

    if not manager.destroy_cluster():
        sys.exit(1)


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show cluster status and resource information."""
    manager: ClusterManager = ctx.obj["manager"]

    runtime_version = get_runtime_version()
    console.print(f"[blue]Amauo v{runtime_version}[/blue]")

    if not manager.check_prerequisites():
        sys.exit(1)

    if not manager.show_status():
        sys.exit(1)


@cli.command(name="list")
@click.pass_context
def list_nodes(ctx: click.Context) -> None:
    """List all nodes in the cluster with detailed information."""
    manager: ClusterManager = ctx.obj["manager"]

    runtime_version = get_runtime_version()
    console.print(f"[blue]Amauo v{runtime_version}[/blue]")

    if not manager.check_prerequisites():
        sys.exit(1)

    if not manager.list_nodes():
        sys.exit(1)


@cli.command()
@click.pass_context
def ssh(ctx: click.Context) -> None:
    """SSH into the cluster head node."""
    manager: ClusterManager = ctx.obj["manager"]

    runtime_version = get_runtime_version()
    console.print(f"[blue]Amauo v{runtime_version}[/blue]")

    if not manager.check_prerequisites():
        sys.exit(1)

    if not manager.ssh_cluster():
        sys.exit(1)


@cli.command()
@click.pass_context
def logs(ctx: click.Context) -> None:
    """Show cluster deployment and runtime logs."""
    manager: ClusterManager = ctx.obj["manager"]

    runtime_version = get_runtime_version()
    console.print(f"[blue]Amauo v{runtime_version}[/blue]")

    if not manager.check_prerequisites():
        sys.exit(1)

    if not manager.show_logs():
        sys.exit(1)


@cli.command()
@click.pass_context
def cleanup(ctx: click.Context) -> None:
    """Clean up Docker containers and local resources."""
    manager: ClusterManager = ctx.obj["manager"]

    runtime_version = get_runtime_version()
    console.print(f"[blue]Amauo v{runtime_version}[/blue]")
    manager.cleanup_docker()


@cli.command()
@click.pass_context
def check(ctx: click.Context) -> None:
    """Check prerequisites and system configuration."""
    manager: ClusterManager = ctx.obj["manager"]

    runtime_version = get_runtime_version()
    console.print(f"[blue]Amauo v{runtime_version}[/blue]")

    if not manager.check_prerequisites():
        sys.exit(1)

    console.print("[green]✅ All prerequisites satisfied![/green]")


@cli.command()
@click.pass_context
def debug(ctx: click.Context) -> None:
    """Debug AWS credentials and Docker container state."""
    manager: ClusterManager = ctx.obj["manager"]

    runtime_version = get_runtime_version()
    console.print(f"[blue]Amauo v{runtime_version}[/blue]")

    console.print("\n[blue]🔍 Container Debug Information[/blue]")
    manager.debug_container_credentials()


@cli.command()
@click.pass_context
def version(ctx: click.Context) -> None:
    """Show detailed version information."""
    runtime_version = get_runtime_version()

    # Determine if this is a development or PyPI installation
    is_dev = "dev" in runtime_version or "+" in runtime_version

    console.print(f"[bold cyan]Amauo v{runtime_version}[/bold cyan]")

    if is_dev:
        console.print("[yellow]📦 Local development version[/yellow]")
        if "+" in runtime_version:
            # Extract commit hash
            commit_part = runtime_version.split("+")[-1]
            console.print(f"[dim]   Commit: {commit_part}[/dim]")
    else:
        console.print("[green]📦 PyPI release version[/green]")

    console.print(f"[dim]   Installation: {Path(__file__).parent}[/dim]")

    # Show Python version
    python_version = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    console.print(f"[dim]   Python: {python_version}[/dim]")


@cli.command()
@click.option(
    "--follow", "-f", is_flag=True, help="Follow deployment progress continuously"
)
@click.pass_context
def monitor(ctx: click.Context, follow: bool) -> None:
    """Monitor active deployments and cluster health."""
    manager: ClusterManager = ctx.obj["manager"]

    runtime_version = get_runtime_version()
    console.print(f"[blue]Amauo v{runtime_version}[/blue]")

    if not manager.check_prerequisites():
        sys.exit(1)

    if not manager.monitor_deployments(follow=follow):
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
