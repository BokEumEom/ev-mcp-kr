from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from ev_mcp.cache import build_caches
from ev_mcp.client import EvChargerClient
from ev_mcp.context import ToolContext
from ev_mcp.settings import Settings
from ev_mcp.store import ChargerStore


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Isolated Settings instance — never reads a developer's real .env / shell key.

    db_path is forced to :memory: so build_server() in tests doesn't touch the
    developer's data/chargers.db.
    """
    monkeypatch.setenv("SERVICE_KEY", "TEST_KEY_NOT_REAL")
    monkeypatch.delenv("VWORLD_KEY", raising=False)
    monkeypatch.setenv("DB_PATH", ":memory:")
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture
async def ctx(settings: Settings) -> AsyncIterator[ToolContext]:
    """ToolContext fixture used by tool-level tests.

    Each test gets a fresh in-memory SQLite store so tests don't bleed state.
    """
    store = ChargerStore(":memory:")
    try:
        async with EvChargerClient(settings) as client:
            yield ToolContext(
                settings=settings,
                client=client,
                store=store,
                caches=build_caches(settings),
            )
    finally:
        store.close()
