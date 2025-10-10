"""Unified UI Manager for all Rich display operations."""

from typing import Any, Callable, Optional, cast

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table


class UIManager:
    """Centralized manager for all Rich UI operations."""

    def __init__(self, console: Optional[Console] = None):
        """Initialize UI Manager with console."""
        self.console = console or self._get_default_console()
        self._live_display: Optional[Live] = None

    def _get_default_console(self) -> Console:
        """Get default console configuration."""
        from .display import console

        return console

    def create_instance_table(
        self,
        title: str = "Instances",
        show_header: bool = True,
        show_lines: bool = False,
        header_style: Optional[str] = None,
    ) -> Table:
        """Create a standardized instance table."""
        table = Table(
            title=title,
            show_header=show_header,
            expand=False,
            show_lines=show_lines,
            padding=(0, 1),
            header_style=header_style,
            width=134,  # Fixed width for consistency
        )

        # Standard columns with consistent widths
        table.add_column("Region", style="magenta", width=16, no_wrap=True)
        table.add_column("Instance ID", style="cyan", width=22, no_wrap=True)
        table.add_column("Status", style="yellow", width=22, no_wrap=True)
        table.add_column("Upload", style="blue", width=12, no_wrap=True)
        table.add_column("Type", style="green", width=10, no_wrap=True)
        table.add_column("Public IP", style="blue", width=16, no_wrap=True)
        table.add_column("Created", style="white", width=20, no_wrap=True)

        return table

    def add_instance_row(
        self,
        table: Table,
        region: str,
        instance_id: str,
        status: str,
        instance_type: str,
        public_ip: str,
        created: str,
        upload_status: str = "-",
    ) -> None:
        """Add a row to an instance table."""
        table.add_row(
            str(region),
            str(instance_id),
            str(status),
            str(upload_status),
            str(instance_type),
            str(public_ip),
            str(created),
        )

    def format_status(self, status: str, detail: str = "") -> str:
        """Format status with color coding."""
        # Success statuses
        if any(marker in status.upper() for marker in ["SUCCESS", "COMPLETE", "✓"]):
            status_display = f"[green]{status}[/green]"
        # Error statuses
        elif any(marker in status.upper() for marker in ["ERROR", "FAILED", "✗"]):
            status_display = f"[red]{status}[/red]"
        # In-progress statuses
        elif any(marker in status for marker in ["⏳", "...", "WAIT"]):
            status_display = f"[yellow]{status}[/yellow]"
        # Skipped/special statuses
        elif "SKIPPED" in status.upper():
            status_display = f"[dim]{status}[/dim]"
        else:
            status_display = status

        # Add detail if provided
        if detail:
            if len(detail) > 47:
                detail = detail[:44] + "..."
            status_display = f"{status_display} {detail}"

        return status_display

    def create_progress_panel(
        self, title: str, content: dict[str, Any], border_style: str = "blue"
    ) -> Panel:
        """Create a progress panel with formatted content."""
        lines = []

        # Add title if different from panel title
        if "title" in content:
            lines.append(f"[bold]{content['title']}[/bold]\n")

        # Format key-value pairs
        for key, value in content.items():
            if key == "title":
                continue

            # Apply color based on key
            if "completed" in key.lower() or "success" in key.lower():
                lines.append(f"[green]{key}: {value}[/green]")
            elif "failed" in key.lower() or "error" in key.lower():
                lines.append(f"[red]{key}: {value}[/red]")
            elif "progress" in key.lower() or "pending" in key.lower():
                lines.append(f"[yellow]{key}: {value}[/yellow]")
            else:
                lines.append(f"{key}: {value}")

        return Panel("\n".join(lines), title=title, border_style=border_style)

    def start_live_display(
        self,
        renderable: Any,
        refresh_per_second: int = 4,
        screen: bool = True,
        redirect_stdout: bool = False,
    ) -> Live:
        """Start a live display that can be updated."""
        self._live_display = Live(
            renderable,
            refresh_per_second=refresh_per_second,
            console=self.console,
            screen=screen,
            redirect_stdout=redirect_stdout,
        )
        return self._live_display

    def create_layout(self, *sections: Any) -> Layout:
        """Create a layout with multiple sections."""
        layout = Layout()

        if len(sections) == 1:
            return cast(Layout, sections[0])
        elif len(sections) == 2:
            # Default split for table + summary
            layout.split_column(
                Layout(sections[0], ratio=4),
                Layout(sections[1], size=8),
            )
        else:
            # Custom layout for multiple sections
            layout.split_column(*[Layout(section) for section in sections])

        return layout

    def print_header(self, text: str, style: str = "bold") -> None:
        """Print a formatted header."""
        self.console.print(f"\n[{style}]{text}[/{style}]\n")

    def print_success(self, message: str) -> None:
        """Print a success message."""
        self.console.print(f"[green]✅ {message}[/green]")

    def print_error(self, message: str) -> None:
        """Print an error message."""
        self.console.print(f"[red]❌ {message}[/red]")

    def print_warning(self, message: str) -> None:
        """Print a warning message."""
        self.console.print(f"[yellow]⚠️  {message}[/yellow]")

    def print_info(self, message: str) -> None:
        """Print an info message."""
        self.console.print(f"[blue]ℹ️  {message}[/blue]")

    def create_instance_progress_tracker(
        self, instances: dict[str, dict[str, Any]], title: str = "Instance Progress"
    ) -> Callable:
        """Create a progress tracking function for instances."""

        def update_progress() -> Any:
            table = self.create_instance_table(title=title)

            # Sort instances for consistent display
            sorted_instances = sorted(
                instances.items(), key=lambda x: (x[1].get("region", ""), x[0])
            )

            for instance_key, info in sorted_instances:
                status = self.format_status(
                    info.get("status", "Unknown"), info.get("detail", "")
                )

                self.add_instance_row(
                    table,
                    info.get("region", "unknown"),
                    info.get("instance_id", instance_key),
                    status,
                    info.get("type", "unknown"),
                    info.get("public_ip", "pending..."),
                    info.get("created", "pending..."),
                )

            return table

        return update_progress

    def show_summary(
        self,
        title: str,
        total: int,
        completed: int,
        failed: int,
        additional_info: Optional[dict[str, Any]] = None,
    ) -> None:
        """Show a summary of operations."""
        lines = [f"\n[bold]{title}:[/bold]"]

        if completed == total:
            lines.append(
                f"[green]✅ All {total} operations completed successfully[/green]"
            )
        else:
            lines.append(
                f"[yellow]⚠️  {completed}/{total} operations completed[/yellow]"
            )
            if failed > 0:
                lines.append(f"[red]❌ {failed} operations failed[/red]")

        if additional_info:
            for key, value in additional_info.items():
                lines.append(f"[dim]{key}: {value}[/dim]")

        self.console.print("\n".join(lines))
