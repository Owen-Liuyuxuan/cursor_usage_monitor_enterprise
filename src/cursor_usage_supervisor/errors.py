"""Safe-to-display failures with no credential material."""


class CursorUsageError(RuntimeError):
    """A collection failure that may be shown on the panel or CLI."""
