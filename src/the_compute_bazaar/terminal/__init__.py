"""Native Terminal shell and workspace adapters."""

from typing import Any


def create_terminal_app(*args: Any, **kwargs: Any) -> Any:
    """Create the Terminal app without importing its optional stack eagerly."""
    from .server import create_terminal_app as create

    return create(*args, **kwargs)


__all__ = ["create_terminal_app"]
