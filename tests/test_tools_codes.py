from __future__ import annotations

from ev_mcp.tools.codes import lookup_codes


def test_lookup_codes_returns_full_sido_table() -> None:
    table = lookup_codes(category="sido")
    assert table["11"] == "서울특별시"
    assert table["50"] == "제주특별자치도"
    assert len(table) == 17


def test_lookup_codes_charger_type() -> None:
    table = lookup_codes(category="charger_type")
    assert table["04"] == "DC콤보"
    assert table["11"] == "DC콤보2(버스전용)"


def test_lookup_codes_stat_includes_v1_21_codes() -> None:
    table = lookup_codes(category="stat")
    assert table["2"] == "충전대기"
    assert table["6"] == "예약중"
    assert table["9"] == "상태미확인"


def test_lookup_codes_busi_id_known_operators() -> None:
    table = lookup_codes(category="busi_id")
    assert table["ME"] == "기후에너지환경부"
    assert table["EV"] == "에버온"
    assert table["KM"] == "카카오모빌리티"
    assert len(table) >= 180


def test_lookup_codes_sigungu_size() -> None:
    table = lookup_codes(category="sigungu")
    assert len(table) == 230
    assert table["11680"] == "강남구"
    assert table["28260"] == "서구"
