from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from ev_mcp.cache import build_caches
from ev_mcp.client import EvChargerClient
from ev_mcp.context import ToolContext
from ev_mcp.settings import Settings


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Isolated Settings instance — never reads a developer's real .env / shell key."""
    monkeypatch.setenv("SERVICE_KEY", "TEST_KEY_NOT_REAL")
    monkeypatch.delenv("VWORLD_KEY", raising=False)
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture
async def ctx(settings: Settings) -> AsyncIterator[ToolContext]:
    """ToolContext fixture used by tool-level tests."""
    async with EvChargerClient(settings) as client:
        yield ToolContext(
            settings=settings,
            client=client,
            caches=build_caches(settings),
        )
