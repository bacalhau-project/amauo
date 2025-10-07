"""State management for tracking deployed instances."""

import json
import logging
import os
from datetime import datetime
from typing import Any, cast

logger = logging.getLogger(__name__)


class SimpleStateManager:
    """Simple JSON-based state management - replaces SQLite complexity."""

    def __init__(self, state_file: str = "instances.json"):
        self.state_file = state_file

    def load_instances(self) -> list[dict[Any, Any]]:
        """Load instances from JSON file."""
        try:
            with open(self.state_file) as f:
                data = json.load(f)
                return cast(list[dict[Any, Any]], data.get("instances", []))
        except FileNotFoundError:
            return []
        except Exception as e:
            logger.error(f"Error loading state: {e}")
            return []

    def save_instances(self, instances: list[dict]) -> None:
        """Save instances to JSON file."""
        try:
            # Ensure directory exists
            state_dir = os.path.dirname(self.state_file)
            if state_dir and not os.path.exists(state_dir):
                os.makedirs(state_dir, exist_ok=True)

            data = {"instances": instances, "last_updated": datetime.now().isoformat()}
            with open(self.state_file, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def add_instance(self, instance: dict) -> None:
        """Add instance to state."""
        instances = self.load_instances()
        instances.append(instance)
        self.save_instances(instances)

    def remove_instances_by_region(self, region: str) -> int:
        """Remove instances from specific region."""
        instances = self.load_instances()
        original_count = len(instances)
        instances = [i for i in instances if i.get("region") != region]
        self.save_instances(instances)
        return original_count - len(instances)

    def remove_instance(self, instance_id: str) -> bool:
        """Remove a specific instance by ID."""
        instances = self.load_instances()
        original_count = len(instances)
        instances = [i for i in instances if i.get("id") != instance_id]
        if len(instances) < original_count:
            self.save_instances(instances)
            return True
        return False
