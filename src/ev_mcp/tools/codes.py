"""Tool: lookup_codes — 코드 테이블(시도/시군구/충전기타입 등) 조회."""

from __future__ import annotations

from typing import Literal

from ..codes_lookup import (
    busi_id_table,
    charger_type_table,
    kind_detail_table,
    kind_table,
    sido_table,
    sigungu_table,
    stat_table,
)

CodeCategory = Literal[
    "sido",
    "sigungu",
    "charger_type",
    "stat",
    "busi_id",
    "kind",
    "kind_detail",
]

_TABLES = {
    "sido": sido_table,
    "sigungu": sigungu_table,
    "charger_type": charger_type_table,
    "stat": stat_table,
    "busi_id": busi_id_table,
    "kind": kind_table,
    "kind_detail": kind_detail_table,
}


def lookup_codes(*, category: CodeCategory) -> dict[str, str]:
    """공통 코드 테이블을 조회합니다.

    한국환경공단 OpenAPI v1.23 의 공통 코드 7종을 반환합니다. 코드 → 한국어 설명
    의 평면 dict. 시군구는 230개, busi_id 는 180개로 응답이 크지만 전부 한 번에
    반환합니다 (필요 시 호출자가 필터링).

    Parameters
    ----------
    category:
        - ``"sido"`` 시도 (17개, 예: 11=서울특별시)
        - ``"sigungu"`` 시군구 zscode (230개, 예: 11680=강남구)
        - ``"charger_type"`` 충전기 타입 (11개, 예: 04=DC콤보)
        - ``"stat"`` 충전기 상태 (8개, 예: 2=충전대기, 3=충전중)
        - ``"busi_id"`` 운영기관 (180개, 예: ME=기후에너지환경부)
        - ``"kind"`` 충전소 구분 대분류 (10개)
        - ``"kind_detail"`` 충전소 구분 상세 (56개)

    예시
    ----
    "충전기 상태 코드 의미가 뭐야?"
        → category="stat"
    "강남구 zscode 가 뭐였더라?"
        → category="sigungu" 후 호출자가 "강남구"로 필터
    """
    return _TABLES[category]()
