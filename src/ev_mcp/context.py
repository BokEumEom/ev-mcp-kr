"""Single shared dependency object that every MCP tool receives.

Created once at server startup, held by FastMCP, and passed (or closed-over)
into each tool. This avoids carrying client/store/caches/settings as four
separate parameters through every signature.
"""

from __future__ import annotations

from dataclasses import dataclass

from .analytics import AnalyticsClient
from .cache import Caches
from .client import EvChargerClient
from .settings import Settings
from .store import ChargerStore


@dataclass
class ToolContext:
    settings: Settings
    client: EvChargerClient
    store: ChargerStore  # persistent charger inventory
    caches: Caches  # in-memory short-lived cache for getChargerStatus (60s)
    analytics: AnalyticsClient  # Phase 10 — DuckDB sidecar (read_parquet)
