"""Standalone sync script: data.go.kr → SQLite charger inventory.

Run this OUT OF BAND from the MCP server. The server only reads the SQLite
store; it does not call data.go.kr's getChargerInfo on user requests.

Usage::

    .venv/bin/python scripts/sync_chargers.py
    .venv/bin/python scripts/sync_chargers.py --db /tmp/test.db --page-size 100
    .venv/bin/python scripts/sync_chargers.py --full   # ignore resume marker

The script is patient: it keeps retrying transient failures (504/timeouts)
indefinitely with backoff, since data.go.kr is known to flap. Use Ctrl+C to
stop. Resume picks up from the last completed page on the next run.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog

# Allow running from repo root without `pip install -e .`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ev_mcp.client import EvChargerClient, EvChargerError
from ev_mcp.server import configure_logging
from ev_mcp.settings import load_settings
from ev_mcp.store import open_store

logger = structlog.get_logger("sync_chargers")

DEFAULT_PAGE_SIZE = 2000
RETRY_SLEEP_S = 30.0
SETTLE_LOG_EVERY = 1  # log every page; sync is slow so this is fine


async def sync(
    db_path: Path,
    page_size: int = DEFAULT_PAGE_SIZE,
    full: bool = False,
) -> None:
    settings = load_settings()
    # Sync is a background batch; data.go.kr's getChargerInfo answers in
    # 20-60s, so the client must wait that long. Bigger than the runtime
    # default (90s) to absorb spikes.
    settings = settings.model_copy(
        update={"request_timeout_s": 180.0, "max_retries": 5}
    )
    configure_logging(settings.log_level, settings=settings)

    store = open_store(db_path)
    last_page = 0 if full else (store.last_completed_page() or 0)
    page_no = last_page + 1

    logger.info(
        "sync_start",
        db=str(db_path),
        page_size=page_size,
        resume_from_page=page_no,
        full=full,
        existing_rows=store.total_count(),
    )

    async with EvChargerClient(settings) as client:
        while True:
            try:
                header, items = await client.get_charger_info(
                    page_no=page_no, num_of_rows=page_size
                )
            except EvChargerError as e:
                logger.warning(
                    "page_failed_will_retry",
                    page=page_no,
                    sleep_s=RETRY_SLEEP_S,
                    error=client.redact(e),
                )
                await asyncio.sleep(RETRY_SLEEP_S)
                continue

            if not items:
                logger.info("empty_page_done", page=page_no)
                break

            store.upsert_many(items)
            store.set_state("last_completed_page", str(page_no))
            if header.total_count is not None:
                store.set_state("total_count_observed", str(header.total_count))

            if page_no % SETTLE_LOG_EVERY == 0:
                logger.info(
                    "page_done",
                    page=page_no,
                    rows_in_page=len(items),
                    total_in_store=store.total_count(),
                    upstream_total=header.total_count,
                )

            seen = page_no * page_size
            total = header.total_count or 0
            if total and seen >= total:
                logger.info("reached_total_count", total=total)
                break
            if len(items) < page_size:
                logger.info("partial_page_done", page=page_no, rows=len(items))
                break
            page_no += 1

    store.set_state("last_synced_at", datetime.now(UTC).isoformat())
    store.set_state("last_completed_page", "0")  # next full run starts fresh
    logger.info("sync_complete", total_rows=store.total_count())
    store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/chargers.db"),
        help="SQLite path (default: data/chargers.db)",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=(
            f"Rows per upstream call (default: {DEFAULT_PAGE_SIZE}). "
            "data.go.kr returns 504 on numOfRows=9999; 2000 has been observed safe."
        ),
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Ignore last_completed_page and start from page 1",
    )
    args = parser.parse_args()
    asyncio.run(sync(args.db, page_size=args.page_size, full=args.full))


if __name__ == "__main__":
    main()
