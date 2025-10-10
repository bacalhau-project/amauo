"""Shared table utilities for spot deployer commands."""

from typing import Optional

from rich.table import Table

from .ui_manager import UIManager

# Create a module-level UI manager instance
_ui_manager = UIManager()


def create_instance_table(
    title: str,
    show_header: bool = True,
    show_lines: bool = False,
    padding: tuple = (0, 1),
    header_style: Optional[str] = None,
) -> Table:
    """Create a standardized instance table with common columns."""
    return _ui_manager.create_instance_table(
        title=title,
        show_header=show_header,
        show_lines=show_lines,
        header_style=header_style,
    )


def add_instance_row(
    table: Table,
    region: str,
    instance_id: str,
    status: str,
    instance_type: str,
    public_ip: str,
    created: str,
    upload_status: str = "-",
) -> None:
    """Add a row to an instance table with proper string conversion."""
    _ui_manager.add_instance_row(
        table,
        region,
        instance_id,
        status,
        instance_type,
        public_ip,
        created,
        upload_status,
    )


def add_destroy_row(
    table: Table,
    region: str,
    instance_id: str,
    status: str,
    details: str,
) -> None:
    """Add a row to a destroy table with proper string conversion."""
    table.add_row(
        str(region),
        str(instance_id),
        str(status),
        "",  # Type column (empty for destroy)
        "",  # Public IP column (empty for destroy)
        "",  # Created column (empty for destroy)
    )
