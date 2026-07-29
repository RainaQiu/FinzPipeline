"""Compatibility import for application settings.

The actual settings implementation lives in ``app.core.config`` and performs
no environment-file loading during import.
"""

from app.core.config import Settings

__all__ = ["Settings"]
