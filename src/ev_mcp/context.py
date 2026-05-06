"""Single shared dependency object that every MCP tool receives.

Created once at server startup, held by FastMCP, and passed (or closed-over)
into each tool. This avoids carrying client/caches/settings as three separate
parameters through every signature.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cache import Caches
from .client import EvChargerClient
from .settings import Settings


@dataclass
class ToolContext:
    settings: Settings
    client: EvChargerClient
    caches: Caches
