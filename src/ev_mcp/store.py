"""SQLite-backed persistent store for charger inventory.

Replaces the in-memory StationInfoCache (Phase 1~5). The full ~500k charger
inventory lives in ``data/chargers.db`` and is populated by an out-of-band
sync script (``scripts/sync_chargers.py``). The MCP server reads from this
store via indexed SQL queries — no upstream getChargerInfo calls during
user requests.

The status (60s TTL) cache stays in-memory; it's small, short-lived, and
hits the live getChargerStatus endpoint anyway.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from math import cos, radians
from pathlib import Path
from typing import Any

from .models import ChargerInfo

# Bounding-box prefilter for near_lat_lng. 1° lat ≈ 111 km, 1° lng ≈ 111*cos(lat).
KM_PER_DEGREE_LAT = 111.0
MIN_COS_GUARD = 0.01  # avoid division blow-up near the poles

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chargers (
    stat_id      TEXT NOT NULL,
    chger_id     TEXT NOT NULL,
    stat_nm      TEXT NOT NULL,
    chger_type   TEXT NOT NULL,
    addr         TEXT NOT NULL,
    addr_detail  TEXT,
    location     TEXT,
    lat          REAL NOT NULL,
    lng          REAL NOT NULL,
    use_time     TEXT NOT NULL,
    busi_id      TEXT NOT NULL,
    bnm          TEXT NOT NULL,
    busi_nm      TEXT NOT NULL,
    busi_call    TEXT,
    stat         TEXT NOT NULL,
    stat_upd_dt  TEXT,
    last_tsdt    TEXT,
    last_tedt    TEXT,
    now_tsdt     TEXT,
    power_type   TEXT,
    output       TEXT,
    method       TEXT,
    zcode        TEXT NOT NULL,
    zscode       TEXT,
    kind         TEXT,
    kind_detail  TEXT,
    parking_free TEXT,
    note         TEXT,
    limit_yn     TEXT NOT NULL DEFAULT 'N',
    limit_detail TEXT,
    del_yn       TEXT NOT NULL DEFAULT 'N',
    del_detail   TEXT,
    traffic_yn   TEXT,
    year         TEXT,
    floor_num    TEXT,
    floor_type   TEXT,
    upserted_at  TEXT NOT NULL,
    PRIMARY KEY (stat_id, chger_id)
);

CREATE INDEX IF NOT EXISTS idx_busi_id ON chargers(busi_id);
CREATE INDEX IF NOT EXISTS idx_zcode   ON chargers(zcode);
CREATE INDEX IF NOT EXISTS idx_zscode  ON chargers(zscode);
CREATE INDEX IF NOT EXISTS idx_lat_lng ON chargers(lat, lng);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_INSERT_SQL = """
INSERT OR REPLACE INTO chargers (
    stat_id, chger_id, stat_nm, chger_type, addr, addr_detail, location,
    lat, lng, use_time, busi_id, bnm, busi_nm, busi_call, stat,
    stat_upd_dt, last_tsdt, last_tedt, now_tsdt, power_type, output, method,
    zcode, zscode, kind, kind_detail, parking_free, note,
    limit_yn, limit_detail, del_yn, del_detail, traffic_yn, year,
    floor_num, floor_type, upserted_at
) VALUES (
    ?, ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?, ?, ?,
    ?, ?, ?
)
"""

_COLUMNS = (
    "stat_id, chger_id, stat_nm, chger_type, addr, addr_detail, location, "
    "lat, lng, use_time, busi_id, bnm, busi_nm, busi_call, stat, "
    "stat_upd_dt, last_tsdt, last_tedt, now_tsdt, power_type, output, method, "
    "zcode, zscode, kind, kind_detail, parking_free, note, "
    "limit_yn, limit_detail, del_yn, del_detail, traffic_yn, year, "
    "floor_num, floor_type"
)


def _dt_to_iso(v: datetime | None) -> str | None:
    return v.isoformat() if v is not None else None


def _iso_to_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def _row_to_params(c: ChargerInfo, upserted_at: str) -> tuple[Any, ...]:
    return (
        c.stat_id,
        c.chger_id,
        c.stat_nm,
        c.chger_type,
        c.addr,
        c.addr_detail,
        c.location,
        c.lat,
        c.lng,
        c.use_time,
        c.busi_id,
        c.bnm,
        c.busi_nm,
        c.busi_call,
        c.stat.value,
        _dt_to_iso(c.stat_upd_dt),
        _dt_to_iso(c.last_tsdt),
        _dt_to_iso(c.last_tedt),
        _dt_to_iso(c.now_tsdt),
        c.power_type,
        c.output,
        c.method,
        c.zcode,
        c.zscode,
        c.kind,
        c.kind_detail,
        c.parking_free,
        c.note,
        c.limit_yn,
        c.limit_detail,
        c.del_yn,
        c.del_detail,
        c.traffic_yn,
        c.year,
        c.floor_num,
        c.floor_type,
        upserted_at,
    )


def _record_to_charger(row: sqlite3.Row) -> ChargerInfo:
    # Use the upstream JSON aliases (camelCase) so Pydantic's strict-typed
    # constructor stays the same path used everywhere else (model_validate).
    payload: dict[str, Any] = {
        "statNm": row["stat_nm"],
        "statId": row["stat_id"],
        "chgerId": row["chger_id"],
        "chgerType": row["chger_type"],
        "addr": row["addr"],
        "addrDetail": row["addr_detail"],
        "location": row["location"],
        "lat": row["lat"],
        "lng": row["lng"],
        "useTime": row["use_time"],
        "busiId": row["busi_id"],
        "bnm": row["bnm"],
        "busiNm": row["busi_nm"],
        "busiCall": row["busi_call"],
        "stat": row["stat"],
        # Datetimes were ISO-serialized; ChargerInfo's _parse_yyyymmddhhmmss
        # only handles the upstream YYYYMMDDhhmmss shape, so feed parsed dt.
        "statUpdDt": _iso_to_dt(row["stat_upd_dt"]),
        "lastTsdt": _iso_to_dt(row["last_tsdt"]),
        "lastTedt": _iso_to_dt(row["last_tedt"]),
        "nowTsdt": _iso_to_dt(row["now_tsdt"]),
        "powerType": row["power_type"],
        "output": row["output"],
        "method": row["method"],
        "zcode": row["zcode"],
        "zscode": row["zscode"],
        "kind": row["kind"],
        "kindDetail": row["kind_detail"],
        "parkingFree": row["parking_free"],
        "note": row["note"],
        "limitYn": row["limit_yn"],
        "limitDetail": row["limit_detail"],
        "delYn": row["del_yn"],
        "delDetail": row["del_detail"],
        "trafficYn": row["traffic_yn"],
        "year": row["year"],
        "floorNum": row["floor_num"],
        "floorType": row["floor_type"],
    }
    return ChargerInfo.model_validate(payload)


class ChargerStore:
    """SQLite-backed charger inventory.

    Thread-safe via SQLite's own locking. Uses a single connection per
    instance — for the MCP server (single async event loop) one is enough;
    the sync script also uses one.
    """

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self._db_path = str(db_path)
        # check_same_thread=False is safe here: the MCP server has one event
        # loop, and sync has one process. No cross-thread sharing in our use.
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        # WAL gives concurrent readers (server) while one writer (sync) commits.
        # Memory DBs don't support WAL — skip silently.
        if self._db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ChargerStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Any:
        """Run a block in a single transaction; rollback on exception."""
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ---- writes ----

    def upsert_many(self, chargers: Iterable[ChargerInfo]) -> int:
        upserted_at = datetime.now(UTC).isoformat()
        rows = [_row_to_params(c, upserted_at) for c in chargers]
        with self._tx() as conn:
            conn.executemany(_INSERT_SQL, rows)
        return len(rows)

    def set_state(self, key: str, value: str) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?, ?)",
                (key, value),
            )

    # ---- reads ----

    def by_stat_id(self, stat_id: str) -> list[ChargerInfo]:
        cur = self._conn.execute(
            f"SELECT {_COLUMNS} FROM chargers WHERE stat_id = ? ORDER BY chger_id",
            (stat_id,),
        )
        return [_record_to_charger(r) for r in cur.fetchall()]

    def by_busi_id(self, busi_id: str, limit: int = 100) -> list[ChargerInfo]:
        cur = self._conn.execute(
            f"SELECT {_COLUMNS} FROM chargers WHERE busi_id = ? "
            "ORDER BY stat_id, chger_id LIMIT ?",
            (busi_id, limit),
        )
        return [_record_to_charger(r) for r in cur.fetchall()]

    def by_zcode(self, zcode: str, limit: int = 100) -> list[ChargerInfo]:
        cur = self._conn.execute(
            f"SELECT {_COLUMNS} FROM chargers WHERE zcode = ? "
            "ORDER BY stat_id, chger_id LIMIT ?",
            (zcode, limit),
        )
        return [_record_to_charger(r) for r in cur.fetchall()]

    def by_zscode(self, zscode: str, limit: int = 100) -> list[ChargerInfo]:
        cur = self._conn.execute(
            f"SELECT {_COLUMNS} FROM chargers WHERE zscode = ? "
            "ORDER BY stat_id, chger_id LIMIT ?",
            (zscode, limit),
        )
        return [_record_to_charger(r) for r in cur.fetchall()]

    def near_lat_lng(
        self,
        lat: float,
        lng: float,
        radius_km: float,
        limit: int = 200,
    ) -> list[ChargerInfo]:
        """Return chargers within a bounding box around (lat, lng).

        The caller is responsible for the precise haversine filter — this
        only does the cheap rectangular prefilter via the (lat, lng) index.
        """
        lat_delta = radius_km / KM_PER_DEGREE_LAT
        lng_delta = radius_km / (KM_PER_DEGREE_LAT * max(cos(radians(lat)), MIN_COS_GUARD))
        cur = self._conn.execute(
            f"SELECT {_COLUMNS} FROM chargers "
            "WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ? "
            "LIMIT ?",
            (
                lat - lat_delta,
                lat + lat_delta,
                lng - lng_delta,
                lng + lng_delta,
                limit,
            ),
        )
        return [_record_to_charger(r) for r in cur.fetchall()]

    def by_busi_id_and_zcode(
        self, busi_id: str, zcode: str, limit: int = 100
    ) -> list[ChargerInfo]:
        cur = self._conn.execute(
            f"SELECT {_COLUMNS} FROM chargers "
            "WHERE busi_id = ? AND zcode = ? "
            "ORDER BY stat_id, chger_id LIMIT ?",
            (busi_id, zcode, limit),
        )
        return [_record_to_charger(r) for r in cur.fetchall()]

    # ---- meta ----

    def total_count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM chargers")
        return int(cur.fetchone()[0])

    def get_state(self, key: str) -> str | None:
        cur = self._conn.execute(
            "SELECT value FROM sync_state WHERE key = ?", (key,)
        )
        row = cur.fetchone()
        return None if row is None else str(row[0])

    def last_synced_at(self) -> datetime | None:
        return _iso_to_dt(self.get_state("last_synced_at"))

    def last_completed_page(self) -> int | None:
        v = self.get_state("last_completed_page")
        if v is None:
            return None
        try:
            return int(v)
        except ValueError:
            return None

    def is_fresh(self, max_age_s: int) -> bool:
        last = self.last_synced_at()
        if last is None:
            return self.total_count() > 0  # something is better than nothing
        age = (datetime.now(UTC) - last).total_seconds()
        return age < max_age_s

    # ---- test convenience ----

    def seed_for_testing(self, rows: Sequence[ChargerInfo]) -> None:
        """Populate without going through the sync flow. Mirrors the old
        StationInfoCache.seed_for_testing for easy test migration."""
        self.upsert_many(rows)
        # Mark as fresh so is_fresh() returns True in tests.
        self.set_state("last_synced_at", datetime.now(UTC).isoformat())


def open_store(db_path: Path | str = ":memory:") -> ChargerStore:
    """Convenience constructor used by server lifespan + sync script."""
    if isinstance(db_path, Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
    return ChargerStore(db_path)


__all__ = ["ChargerStore", "open_store"]
