"""Logging utilities for spot deployer."""

import logging
import re
from collections import deque
from typing import Any, Optional

from .display import console


class LogBuffer:
    """In-memory buffer for log messages (max 100 messages)."""

    def __init__(self, maxlen: int = 100) -> None:
        self.buffer: deque[str] = deque(maxlen=maxlen)

    def append(self, message: str) -> None:
        """Add a message to the buffer."""
        self.buffer.append(message)

    def get_lines(self) -> list[str]:
        """Get all buffered messages as a list."""
        return list(self.buffer)

    def get_text(self) -> str:
        """Get all buffered messages as a single string."""
        return "\n".join(self.buffer)


class ConsoleLogger(logging.Handler):
    """Custom logging handler that adds instance context to console output."""

    def __init__(
        self,
        console_obj: Any = None,
        instance_ip_map: Optional[dict[str, str]] = None,
        log_buffer: Optional[LogBuffer] = None,
    ) -> None:
        super().__init__()
        self.console = console_obj or console
        self.instance_ip_map = instance_ip_map or {}
        self.log_buffer = log_buffer
        self.setLevel(logging.INFO)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)

            # Check if the message already contains instance ID and IP
            instance_pattern = re.match(
                r"^\[([i-][a-z0-9]+)\s*@\s*([\d.]+)\]\s*(.*)", msg
            )

            if instance_pattern:
                # Message already has instance ID and IP, use as-is
                pass
            else:
                # Extract instance key from thread name if available
                thread_name = record.threadName or ""
                instance_key = None
                instance_ip = None

                # Thread names are like "Setup-i-1234567890abcdef0" or "Region-us-west-2"
                if thread_name.startswith("Setup-"):
                    instance_key = thread_name.replace("Setup-", "")
                    # Look up IP address from our map
                    instance_ip = self.instance_ip_map.get(instance_key, "")
                elif "-" in thread_name and thread_name.split("-")[0] == "Region":
                    # For region threads, try to extract from the message
                    if "[" in msg and "]" in msg:
                        # Message already has instance key
                        match = re.search(r"\[([^\]]+)\]", msg)
                        if match:
                            potential_key = match.group(1)
                            if potential_key in self.instance_ip_map:
                                instance_key = potential_key
                                instance_ip = self.instance_ip_map.get(
                                    potential_key, ""
                                )
                    else:
                        # Add region context
                        region = thread_name.replace("Region-", "")
                        msg = f"[{region}] {msg}"

                # Build the prefix with instance key and IP
                prefix = ""
                if instance_key:
                    if instance_ip:
                        prefix = f"[{instance_key} @ {instance_ip}]"
                    else:
                        prefix = f"[{instance_key}]"

                # Only add prefix if it's not already in the message
                if not msg.startswith(prefix) and not msg.startswith(
                    f"[{instance_key}"
                ):
                    msg = f"{prefix} {msg}"

            # Write to log buffer if available
            if self.log_buffer:
                self.log_buffer.append(msg)

            # During instance creation, we don't want console output
            # as it interferes with the live table display
            # Messages are still logged to the file
            pass

        except Exception:
            self.handleError(record)


def setup_logger(
    name: str,
    log_filename: Optional[str] = None,
    console_handler: Optional[ConsoleLogger] = None,
) -> logging.Logger:
    """Set up a logger with optional file and console handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        # File handler (only if filename provided)
        if log_filename:
            file_handler = logging.FileHandler(log_filename)
            file_handler.setLevel(logging.INFO)
            formatter = logging.Formatter("%(asctime)s - %(threadName)s - %(message)s")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        # Console handler if provided
        if console_handler:
            console_formatter = logging.Formatter("%(message)s")
            console_handler.setFormatter(console_formatter)
            logger.addHandler(console_handler)

    return logger
