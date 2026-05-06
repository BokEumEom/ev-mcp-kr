"""Unit tests for ChargerStore (SQLite persistent inventory)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ev_mcp.models import ChargerInfo
from ev_mcp.store import ChargerStore, open_store


def _row(
    *,
    stat_id: str,
    chger_id: str = "01",
    busi_id: str = "ME",
    busi_nm: str = "환경부",
    zcode: str = "11",
    zscode: str | None = "11680",
    lat: float = 37.5,
    lng: float = 127.0,
    chger_type: str = "04",
    stat: str = "2",
) -> ChargerInfo:
    payload: dict[str, Any] = {
        "statNm": f"station-{stat_id}",
        "statId": stat_id,
        "chgerId": chger_id,
        "chgerType": chger_type,
        "addr": "테스트 주소",
        "addrDetail": "",
        "lat": str(lat),
        "lng": str(lng),
        "useTime": "24시간 이용가능",
        "busiId": busi_id,
        "bnm": busi_nm,
        "busiNm": busi_nm,
        "busiCall": "",
        "stat": stat,
        "statUpdDt": "",
        "lastTsdt": "",
        "lastTedt": "",
        "nowTsdt": "",
        "powerType": "",
        "output": "50",
        "method": "단독",
        "zcode": zcode,
        "zscode": zscode,
        "kind": "",
        "kindDetail": "",
        "parkingFree": "",
        "note": "",
        "limitYn": "N",
        "limitDetail": "",
        "delYn": "N",
        "delDetail": "",
        "trafficYn": "",
        "year": "2024",
        "floorNum": "",
        "floorType": "",
    }
    return ChargerInfo.model_validate(payload)


def test_open_store_creates_schema_in_memory() -> None:
    store = ChargerStore(":memory:")
    assert store.total_count() == 0
    assert store.last_synced_at() is None
    assert store.last_completed_page() is None
    store.close()


def test_open_store_creates_schema_on_disk(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    store = open_store(db)
    assert db.exists()
    assert store.total_count() == 0
    store.close()
    # Re-open: schema persists, no re-init explosion.
    store2 = open_store(db)
    assert store2.total_count() == 0
    store2.close()


def test_upsert_many_inserts_rows() -> None:
    store = ChargerStore(":memory:")
    rows = [
        _row(stat_id="ME0001", busi_id="ME"),
        _row(stat_id="EV0001", busi_id="EV", busi_nm="에버온"),
        _row(stat_id="CV0001", busi_id="CV", busi_nm="채비"),
    ]
    n = store.upsert_many(rows)
    assert n == 3
    assert store.total_count() == 3


def test_upsert_idempotent_same_pk() -> None:
    """Re-upserting the same (stat_id, chger_id) overwrites, not duplicates."""
    store = ChargerStore(":memory:")
    r1 = _row(stat_id="ME0001", chger_id="01", busi_nm="환경부")
    r2 = _row(stat_id="ME0001", chger_id="01", busi_nm="환경부 V2")
    store.upsert_many([r1])
    store.upsert_many([r2])
    assert store.total_count() == 1
    found = store.by_stat_id("ME0001")
    assert len(found) == 1
    assert found[0].busi_nm == "환경부 V2"


def test_by_busi_id_lookup() -> None:
    store = ChargerStore(":memory:")
    store.upsert_many([
        _row(stat_id=f"ME{i:04d}", busi_id="ME") for i in range(5)
    ] + [
        _row(stat_id=f"CV{i:04d}", busi_id="CV", busi_nm="채비") for i in range(3)
    ])
    me = store.by_busi_id("ME")
    cv = store.by_busi_id("CV")
    assert len(me) == 5
    assert len(cv) == 3
    assert all(r.busi_id == "ME" for r in me)
    assert all(r.busi_id == "CV" for r in cv)


def test_by_busi_id_respects_limit() -> None:
    store = ChargerStore(":memory:")
    store.upsert_many([
        _row(stat_id=f"ME{i:06d}", busi_id="ME") for i in range(50)
    ])
    out = store.by_busi_id("ME", limit=10)
    assert len(out) == 10


def test_by_busi_id_unknown_returns_empty() -> None:
    store = ChargerStore(":memory:")
    store.upsert_many([_row(stat_id="ME0001")])
    assert store.by_busi_id("ZZ") == []


def test_by_zcode_and_zscode() -> None:
    store = ChargerStore(":memory:")
    store.upsert_many([
        _row(stat_id="A1", zcode="11", zscode="11680"),
        _row(stat_id="A2", zcode="11", zscode="11200"),
        _row(stat_id="B1", zcode="26", zscode="26110"),
    ])
    assert len(store.by_zcode("11")) == 2
    assert len(store.by_zcode("26")) == 1
    assert len(store.by_zscode("11680")) == 1


def test_near_lat_lng_bbox_filter() -> None:
    store = ChargerStore(":memory:")
    store.upsert_many([
        _row(stat_id="A1", lat=37.5, lng=127.0),   # 강남 근처
        _row(stat_id="A2", lat=37.51, lng=127.01),  # 매우 근처
        _row(stat_id="B1", lat=35.18, lng=129.07),  # 부산
        _row(stat_id="C1", lat=33.45, lng=126.55),  # 제주
    ])
    near_seoul = store.near_lat_lng(37.5, 127.0, radius_km=2.0)
    near_busan = store.near_lat_lng(35.18, 129.07, radius_km=2.0)
    assert {r.stat_id for r in near_seoul} == {"A1", "A2"}
    assert {r.stat_id for r in near_busan} == {"B1"}


def test_by_busi_id_and_zcode_combined() -> None:
    store = ChargerStore(":memory:")
    store.upsert_many([
        _row(stat_id="ME0001", busi_id="ME", zcode="11"),
        _row(stat_id="ME0002", busi_id="ME", zcode="26"),
        _row(stat_id="EV0001", busi_id="EV", zcode="11", busi_nm="에버온"),
    ])
    seoul_me = store.by_busi_id_and_zcode("ME", "11")
    assert len(seoul_me) == 1
    assert seoul_me[0].stat_id == "ME0001"


def test_sync_state_round_trip() -> None:
    store = ChargerStore(":memory:")
    assert store.get_state("foo") is None
    store.set_state("foo", "bar")
    assert store.get_state("foo") == "bar"
    store.set_state("foo", "baz")  # overwrite
    assert store.get_state("foo") == "baz"


def test_last_completed_page_typed() -> None:
    store = ChargerStore(":memory:")
    assert store.last_completed_page() is None
    store.set_state("last_completed_page", "42")
    assert store.last_completed_page() == 42
    # Garbage gracefully → None
    store.set_state("last_completed_page", "not-a-number")
    assert store.last_completed_page() is None


def test_last_synced_at_iso_round_trip() -> None:
    store = ChargerStore(":memory:")
    assert store.last_synced_at() is None
    now = datetime.now(UTC)
    store.set_state("last_synced_at", now.isoformat())
    got = store.last_synced_at()
    assert got is not None
    assert got.tzinfo is not None
    assert got == now


def test_is_fresh_with_recent_sync() -> None:
    store = ChargerStore(":memory:")
    store.upsert_many([_row(stat_id="A1")])
    store.set_state("last_synced_at", datetime.now(UTC).isoformat())
    assert store.is_fresh(max_age_s=3600) is True


def test_is_fresh_with_no_sync_but_data_present() -> None:
    """No last_synced_at marker but rows exist → still fresh (be permissive)."""
    store = ChargerStore(":memory:")
    store.upsert_many([_row(stat_id="A1")])
    assert store.last_synced_at() is None
    assert store.is_fresh(max_age_s=3600) is True


def test_is_fresh_empty_db() -> None:
    store = ChargerStore(":memory:")
    assert store.is_fresh(max_age_s=3600) is False


def test_seed_for_testing_marks_fresh() -> None:
    """Compatibility helper for tests migrating from StationInfoCache."""
    store = ChargerStore(":memory:")
    store.seed_for_testing([_row(stat_id="A1")])
    assert store.total_count() == 1
    assert store.is_fresh(max_age_s=3600) is True
    assert store.last_synced_at() is not None


def test_context_manager_closes() -> None:
    with ChargerStore(":memory:") as store:
        store.upsert_many([_row(stat_id="A1")])
        assert store.total_count() == 1
    # After exit, the store is closed; further operations raise.
    with pytest.raises(Exception):  # noqa: B017 — sqlite3.ProgrammingError or similar
        store.total_count()
