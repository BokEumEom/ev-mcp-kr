"""Pydantic models for the data.go.kr EvCharger OpenAPI v1.23.

Field names mirror the spec exactly so debugging against the upstream payload
is easy. Korean labels are derived from the code tables in `src/ev_mcp/codes/`.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

DT_STRING_LEN = 14
MIN_PLAUSIBLE_YEAR = 2000  # upstream uses "00000000000000" or pre-2000 epochs as sentinels


def _empty_to_none(v: Any) -> Any:
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


def _yn_default_n(v: Any) -> Any:
    """Coerce empty/whitespace into 'N' for limitYn / delYn flag fields."""
    if isinstance(v, str) and v.strip() == "":
        return "N"
    return v


def _parse_yyyymmddhhmmss(v: Any) -> Any:
    if isinstance(v, datetime):
        return v
    if not isinstance(v, str):
        return v
    s = v.strip()
    if not s or len(s) != DT_STRING_LEN or not s.isdigit():
        return None if not s else v
    try:
        dt = datetime.strptime(s, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return None if dt.year < MIN_PLAUSIBLE_YEAR else dt


class ChargerStatusCode(StrEnum):
    UNKNOWN = "0"
    COMM_ERROR = "1"
    AVAILABLE = "2"
    CHARGING = "3"
    OUT_OF_SERVICE = "4"
    UNDER_MAINTENANCE = "5"
    RESERVED = "6"
    UNVERIFIED = "9"


_KNOWN_STAT_CODES = frozenset(member.value for member in ChargerStatusCode)


def _coerce_stat(v: Any) -> Any:
    """Tolerate undocumented stat codes (e.g., '7', '8') by demoting to UNKNOWN.

    The spec defines 0,1,2,3,4,5,6,9. In practice operators occasionally emit
    other strings; we never want a single bad row to fail an entire page.
    """
    if isinstance(v, ChargerStatusCode):
        return v
    if isinstance(v, str) and v not in _KNOWN_STAT_CODES:
        return ChargerStatusCode.UNKNOWN
    return v


OptStr = Annotated[str | None, BeforeValidator(_empty_to_none)]
OptDt = Annotated[datetime | None, BeforeValidator(_parse_yyyymmddhhmmss)]
YnStr = Annotated[str, BeforeValidator(_yn_default_n)]
StatField = Annotated[ChargerStatusCode, BeforeValidator(_coerce_stat)]


class ResultHeader(BaseModel):
    """Common header on every JSON response."""

    model_config = ConfigDict(populate_by_name=True)

    result_code: str = Field(..., alias="resultCode")
    result_msg: str = Field(..., alias="resultMsg")
    page_no: int | None = Field(None, alias="pageNo")
    num_of_rows: int | None = Field(None, alias="numOfRows")
    total_count: int | None = Field(None, alias="totalCount")


class ChargerInfo(BaseModel):
    """One charger row from getChargerInfo. ~30 fields, all per v1.23 spec."""

    model_config = ConfigDict(populate_by_name=True)

    stat_nm: str = Field(..., alias="statNm", description="충전소명")
    stat_id: str = Field(..., alias="statId", description="충전소 ID (8 chars)")
    chger_id: str = Field(..., alias="chgerId", description="충전기 ID (2 chars)")
    chger_type: str = Field(..., alias="chgerType", description="충전기 타입 코드")
    addr: str = Field(..., alias="addr", description="주소")
    addr_detail: OptStr = Field(None, alias="addrDetail", description="주소상세")
    location: OptStr = Field(None, alias="location", description="상세위치")
    lat: float = Field(..., alias="lat")
    lng: float = Field(..., alias="lng")
    use_time: str = Field(..., alias="useTime", description="이용가능시간")
    busi_id: str = Field(..., alias="busiId", description="기관 아이디")
    bnm: str = Field(..., alias="bnm", description="기관명")
    busi_nm: str = Field(..., alias="busiNm", description="운영기관명")
    busi_call: OptStr = Field(None, alias="busiCall", description="운영기관 연락처")
    stat: StatField = Field(..., alias="stat", description="충전기 상태")
    stat_upd_dt: OptDt = Field(None, alias="statUpdDt", description="상태갱신일시")
    last_tsdt: OptDt = Field(None, alias="lastTsdt", description="마지막 충전시작일시")
    last_tedt: OptDt = Field(None, alias="lastTedt", description="마지막 충전종료일시")
    now_tsdt: OptDt = Field(None, alias="nowTsdt", description="충전중 시작일시")
    power_type: OptStr = Field(None, alias="powerType", description="충전 방식 라벨")
    output: OptStr = Field(None, alias="output", description="충전용량 kW")
    method: OptStr = Field(None, alias="method", description="충전방식 단독/동시")
    zcode: str = Field(..., alias="zcode", description="시도 코드")
    zscode: OptStr = Field(None, alias="zscode", description="시군구 코드")
    kind: OptStr = Field(None, alias="kind", description="충전소 구분 코드")
    kind_detail: OptStr = Field(None, alias="kindDetail", description="충전소 구분 상세 코드")
    parking_free: OptStr = Field(None, alias="parkingFree", description="주차료 무료 Y/N")
    note: OptStr = Field(None, alias="note", description="충전소 안내")
    limit_yn: YnStr = Field("N", alias="limitYn", description="이용자 제한 Y/N")
    limit_detail: OptStr = Field(None, alias="limitDetail", description="이용제한 사유")
    del_yn: YnStr = Field("N", alias="delYn", description="삭제 여부")
    del_detail: OptStr = Field(None, alias="delDetail", description="삭제 사유")
    traffic_yn: OptStr = Field(None, alias="trafficYn", description="편의제공 여부")
    year: OptStr = Field(None, alias="year", description="설치년도")
    floor_num: OptStr = Field(None, alias="floorNum", description="지상/지하 층수")
    floor_type: OptStr = Field(None, alias="floorType", description="지상/지하 구분 F/B")


class ChargerStatusRow(BaseModel):
    """One row from getChargerStatus."""

    model_config = ConfigDict(populate_by_name=True)

    busi_id: str = Field(..., alias="busiId")
    stat_id: str = Field(..., alias="statId")
    chger_id: str = Field(..., alias="chgerId")
    stat: StatField = Field(..., alias="stat")
    stat_upd_dt: OptDt = Field(None, alias="statUpdDt")
    last_tsdt: OptDt = Field(None, alias="lastTsdt")
    last_tedt: OptDt = Field(None, alias="lastTedt")
    now_tsdt: OptDt = Field(None, alias="nowTsdt")


class InfoResponse(BaseModel):
    """getChargerInfo full response (after unwrapping the JSON envelope)."""

    header: ResultHeader
    items: list[ChargerInfo]


class StatusResponse(BaseModel):
    header: ResultHeader
    items: list[ChargerStatusRow]
