"""User-facing domain models surfaced through MCP tools.

These wrap the raw upstream models in a more conversation-friendly shape:
- Korean labels for codes (status, charger type, region) joined in.
- Distances, derived counts, etc.

Kept separate from `models.py` so the upstream/raw layer stays a 1:1 mirror of
the data.go.kr spec.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict

from .codes_lookup import (
    busi_id_label,
    charger_type_label,
    kind_detail_label,
    kind_label,
    sido_label,
    sigungu_label,
    stat_label,
)
from .models import ChargerInfo, ChargerStatusCode, ChargerStatusRow


class ChargerSummary(BaseModel):
    """Compact view of one charger for list-style results."""

    model_config = ConfigDict(populate_by_name=True)

    stat_id: str
    chger_id: str
    stat_nm: str
    addr: str
    addr_detail: str | None = None
    lat: float
    lng: float
    chger_type_code: str
    chger_type_label: str
    busi_id: str
    busi_nm: str
    operator_label: str
    sido_code: str
    sido_label: str
    sigungu_code: str | None = None
    sigungu_label: str | None = None
    status_code: ChargerStatusCode
    status_label: str
    stat_upd_dt: datetime | None = None
    output_kw: str | None = None
    use_time: str
    parking_free: str | None = None
    limit_yn: str = "N"
    limit_detail: str | None = None
    traffic_yn: str | None = None

    @classmethod
    def from_info(cls, info: ChargerInfo) -> Self:
        return cls(
            stat_id=info.stat_id,
            chger_id=info.chger_id,
            stat_nm=info.stat_nm,
            addr=info.addr,
            addr_detail=info.addr_detail,
            lat=info.lat,
            lng=info.lng,
            chger_type_code=info.chger_type,
            chger_type_label=charger_type_label(info.chger_type),
            busi_id=info.busi_id,
            busi_nm=info.busi_nm,
            operator_label=busi_id_label(info.busi_id),
            sido_code=info.zcode,
            sido_label=sido_label(info.zcode),
            sigungu_code=info.zscode,
            sigungu_label=sigungu_label(info.zscode) if info.zscode else None,
            status_code=info.stat,
            status_label=stat_label(info.stat),
            stat_upd_dt=info.stat_upd_dt,
            output_kw=info.output,
            use_time=info.use_time,
            parking_free=info.parking_free,
            limit_yn=info.limit_yn,
            limit_detail=info.limit_detail,
            traffic_yn=info.traffic_yn,
        )


class ChargerNearby(ChargerSummary):
    """ChargerSummary + distance from query point in km."""

    distance_km: float


class StationDetails(BaseModel):
    """All chargers at one station, plus station-level metadata."""

    model_config = ConfigDict(populate_by_name=True)

    stat_id: str
    stat_nm: str
    addr: str
    addr_detail: str | None = None
    location: str | None = None
    lat: float
    lng: float
    sido_code: str
    sido_label: str
    sigungu_code: str | None = None
    sigungu_label: str | None = None
    kind_code: str | None = None
    kind_label: str | None = None
    kind_detail_code: str | None = None
    kind_detail_label: str | None = None
    operator_id: str
    operator_label: str
    operator_nm: str
    busi_call: str | None = None
    use_time: str
    parking_free: str | None = None
    note: str | None = None
    year: str | None = None
    floor_num: str | None = None
    floor_type: str | None = None
    chargers: list[ChargerSummary]

    @classmethod
    def from_chargers(cls, chargers: list[ChargerInfo]) -> Self:
        if not chargers:
            raise ValueError("StationDetails requires at least one ChargerInfo")
        head = chargers[0]
        return cls(
            stat_id=head.stat_id,
            stat_nm=head.stat_nm,
            addr=head.addr,
            addr_detail=head.addr_detail,
            location=head.location,
            lat=head.lat,
            lng=head.lng,
            sido_code=head.zcode,
            sido_label=sido_label(head.zcode),
            sigungu_code=head.zscode,
            sigungu_label=sigungu_label(head.zscode) if head.zscode else None,
            kind_code=head.kind,
            kind_label=kind_label(head.kind) if head.kind else None,
            kind_detail_code=head.kind_detail,
            kind_detail_label=kind_detail_label(head.kind_detail) if head.kind_detail else None,
            operator_id=head.busi_id,
            operator_label=busi_id_label(head.busi_id),
            operator_nm=head.busi_nm,
            busi_call=head.busi_call,
            use_time=head.use_time,
            parking_free=head.parking_free,
            note=head.note,
            year=head.year,
            floor_num=head.floor_num,
            floor_type=head.floor_type,
            chargers=[ChargerSummary.from_info(c) for c in chargers],
        )


class OperatorHealthRow(BaseModel):
    """analyze_operator_health 의 한 행.

    Phase 10 — Parquet 스냅샷에서 GROUP BY busi_id 로 집계.

    스펙(``stat`` 코드)상 의미:
    - ``"1"`` 통신이상 / ``"4"`` 운영중지 / ``"5"`` 점검중 → **실제 비가동** (``downtime_*``)
    - ``"2"`` 충전대기 → 즉시 사용 가능 (``available_now``)
    - ``"3"`` 충전중 → 가동 중이지만 다른 사람이 사용 중
    - ``"9"`` 상태미확인 → **모니터링 부재** (운영자가 실시간 상태 보고 안 함)
      → 충전기 자체의 가동 여부와 별개. ``unmonitored_*`` 로 분리 집계.

    비가동률(``downtime_ratio``) 해석 시 반드시 ``unmonitored_ratio`` 와 함께 봐야 함.
    어떤 운영자는 ``downtime_ratio=2%`` 인데 ``unmonitored_ratio=90%`` 일 수 있음
    (= 데이터 부재일 뿐 실제 운영 상태는 알 수 없음).
    """

    model_config = ConfigDict(populate_by_name=True)

    busi_id: str
    busi_nm: str
    operator_label: str
    total_chargers: int
    available_now: int  # stat='2'
    downtime_count: int  # stat IN ('1','4','5') — 실제 사용 불가
    downtime_ratio: float  # 0.0~1.0
    unmonitored_count: int  # stat='9' — 실시간 상태 미보고
    unmonitored_ratio: float  # 0.0~1.0


class RegionalDensityRow(BaseModel):
    """regional_density 의 한 행. 시군구 단위 집계."""

    model_config = ConfigDict(populate_by_name=True)

    zcode: str
    sido_label: str
    zscode: str | None = None
    sigungu_label: str | None = None
    total_chargers: int
    distinct_operators: int
    dc_charger_count: int  # 급속 (DC 차데모/콤보/NACS) 수
    dc_ratio: float  # 0.0~1.0


class StatusChange(BaseModel):
    """One row from recent_status_changes."""

    model_config = ConfigDict(populate_by_name=True)

    stat_id: str
    chger_id: str
    operator_id: str
    operator_label: str
    status_code: ChargerStatusCode
    status_label: str
    stat_upd_dt: datetime | None = None
    last_tsdt: datetime | None = None
    last_tedt: datetime | None = None
    now_tsdt: datetime | None = None

    @classmethod
    def from_row(cls, row: ChargerStatusRow) -> Self:
        return cls(
            stat_id=row.stat_id,
            chger_id=row.chger_id,
            operator_id=row.busi_id,
            operator_label=busi_id_label(row.busi_id),
            status_code=row.stat,
            status_label=stat_label(row.stat),
            stat_upd_dt=row.stat_upd_dt,
            last_tsdt=row.last_tsdt,
            last_tedt=row.last_tedt,
            now_tsdt=row.now_tsdt,
        )


class SnapshotDiff(BaseModel):
    """snapshot_diff 의 결과 — 두 스냅샷 사이 변화 집계.

    스칼라 집계만 담는다 (508k 행 나열 금지 — 토큰 예산). from=이전 관측,
    to=이후 관측. synced_at 을 함께 노출해 "두 관측이 실은 동일 데이터" 인
    상황을 숨기지 않는다.
    """

    model_config = ConfigDict(populate_by_name=True)

    from_date: str
    to_date: str
    from_synced_at: str
    to_synced_at: str
    appeared: int  # to 에만 있는 충전기 (신규)
    disappeared: int  # from 에만 있는 충전기 (제거)
    stat_changed: int  # 양쪽에 있으나 stat 코드가 바뀐 충전기
    net_change: int  # appeared - disappeared


class InventoryTrendRow(BaseModel):
    """inventory_trend 의 한 행 — 관측일별 인벤토리 스냅샷."""

    model_config = ConfigDict(populate_by_name=True)

    snapshot_date: str
    synced_at: str
    total_chargers: int
    dc_count: int  # 급속 (DC 차데모/콤보/NACS) 수
    available_count: int  # stat='2' 충전대기
    distinct_operators: int
    delta_total: int | None = None  # 직전 관측 대비 총 충전기 증감. 첫 행은 None
