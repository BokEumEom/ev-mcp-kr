"""Smoke tests for ev_mcp.sync (CLI: ``ev-mcp-sync``)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from ev_mcp import sync as sync_chargers
from ev_mcp.store import ChargerStore

from .fixtures.sample_responses import make_info_page


@pytest.mark.asyncio
async def test_sync_two_pages_persists_to_store(
    settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """End-to-end: 2 pages of upstream data → SQLite store."""
    monkeypatch.setattr(sync_chargers, "load_settings", lambda: settings)
    monkeypatch.setattr(
        sync_chargers, "configure_logging", lambda *a, **k: None
    )
    db = tmp_path / "test.db"

    page1 = make_info_page(total_count=15, page_no=1, num_of_rows=10)
    page2 = make_info_page(total_count=15, page_no=2, num_of_rows=10)
    pages = {1: page1, 2: page2}

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages[int(request.url.params["pageNo"])])

    async with respx.mock(base_url=settings.api_base_url) as router:
        router.get("/getChargerInfo").mock(side_effect=respond)
        await sync_chargers.sync(db, page_size=10)

    # Verify the DB picked up both pages.
    store = ChargerStore(str(db))
    try:
        assert store.total_count() == 15
        assert store.last_synced_at() is not None
        # last_completed_page reset to 0 after a complete run.
        assert store.last_completed_page() == 0
    finally:
        store.close()


@pytest.mark.asyncio
async def test_sync_resume_from_last_completed_page(
    settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Run-2 should pick up at last_completed_page+1, not page 1."""
    monkeypatch.setattr(sync_chargers, "load_settings", lambda: settings)
    monkeypatch.setattr(
        sync_chargers, "configure_logging", lambda *a, **k: None
    )
    db = tmp_path / "test.db"

    # Pre-populate sync_state to simulate a previous run that finished page 5.
    pre = ChargerStore(str(db))
    pre.set_state("last_completed_page", "5")
    pre.close()

    # Mock upstream so page 6 returns 0 rows (signals end). Track the requested
    # pageNo to assert no page < 6 got fetched.
    fetched_pages: list[int] = []

    def respond(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["pageNo"])
        fetched_pages.append(page)
        # 0 rows → loop exits.
        return httpx.Response(
            200, json=make_info_page(total_count=0, page_no=page, num_of_rows=10)
        )

    async with respx.mock(base_url=settings.api_base_url) as router:
        router.get("/getChargerInfo").mock(side_effect=respond)
        await sync_chargers.sync(db, page_size=10)

    assert fetched_pages == [6], f"expected resume at page 6, got {fetched_pages}"
