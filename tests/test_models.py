from __future__ import annotations

from datetime import datetime

from ev_mcp.models import ChargerInfo, ChargerStatusCode, ChargerStatusRow

from .fixtures.sample_responses import GET_CHARGER_INFO_OK, GET_CHARGER_STATUS_OK


def test_charger_info_full_row_parses() -> None:
    raw = GET_CHARGER_INFO_OK["response"]["body"]["items"]["item"][0]
    info = ChargerInfo.model_validate(raw)
    assert info.stat_id == "28260005"
    assert info.chger_type == "03"
    assert info.lat == 37.569620
    assert info.lng == 126.641973
    assert info.stat == ChargerStatusCode.AVAILABLE
    assert info.stat_upd_dt == datetime(2019, 8, 29, 12, 10, 20)
    assert info.parking_free == "Y"
    assert info.year == "2025"
    assert info.floor_type == "F"
    assert info.del_yn == "N"


def test_charger_info_optional_fields_become_none_on_empty_string() -> None:
    raw = GET_CHARGER_INFO_OK["response"]["body"]["items"]["item"][1]
    info = ChargerInfo.model_validate(raw)
    assert info.busi_call is None
    assert info.last_tsdt is None
    assert info.last_tedt is None
    assert info.kind is None
    assert info.kind_detail is None
    assert info.note is None


def test_charger_status_row_parses() -> None:
    raw = GET_CHARGER_STATUS_OK["response"]["body"]["items"]["item"][0]
    row = ChargerStatusRow.model_validate(raw)
    assert row.stat_id == "28260005"
    assert row.stat == ChargerStatusCode.AVAILABLE
    assert row.stat_upd_dt == datetime(2019, 8, 29, 12, 10, 20)


def test_undefined_stat_code_falls_back_to_unknown() -> None:
    """Spec defines 0,1,2,3,4,5,6,9. '7' or '8' or '99' must not crash a whole page."""
    base = dict(GET_CHARGER_STATUS_OK["response"]["body"]["items"]["item"][0])
    for bogus in ("7", "8", "99", "X"):
        row = ChargerStatusRow.model_validate({**base, "stat": bogus})
        assert row.stat == ChargerStatusCode.UNKNOWN


def test_yn_fields_normalize_empty_to_n() -> None:
    """limitYn/delYn arriving as '' should resolve to 'N', not raise."""
    raw = dict(GET_CHARGER_INFO_OK["response"]["body"]["items"]["item"][0])
    raw["limitYn"] = ""
    raw["delYn"] = ""
    info = ChargerInfo.model_validate(raw)
    assert info.limit_yn == "N"
    assert info.del_yn == "N"


def test_zero_sentinel_datetime_becomes_none() -> None:
    raw = dict(GET_CHARGER_INFO_OK["response"]["body"]["items"]["item"][0])
    raw["statUpdDt"] = "00000000000000"
    info = ChargerInfo.model_validate(raw)
    assert info.stat_upd_dt is None
