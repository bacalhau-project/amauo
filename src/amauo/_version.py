"""Version management for amauo package."""

try:
    from importlib.metadata import version as get_version

    __version__ = get_version("amauo")
except Exception:
    # Fallback for development
    __version__ = "0.0.0+dev"

version = __version__

# Create version tuple (handle dev versions)
version_clean = __version__.split("+")[0]  # Remove +dev suffix
version_parts = version_clean.split(".")
__version_tuple__ = tuple(int(p) for p in version_parts[:3] if p.isdigit())
version_tuple = __version_tuple__

# Git commit info (not used but kept for compatibility)
__commit_id__ = None
commit_id = None

# Export all expected attributes
__all__ = [
    "__version__",
    "__version_tuple__",
    "version",
    "version_tuple",
    "__commit_id__",
    "commit_id",
]
