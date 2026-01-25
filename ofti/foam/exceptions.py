from __future__ import annotations


class QuitAppError(RuntimeError):
    """Raised to request a full application exit from anywhere."""
