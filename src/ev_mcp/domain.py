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
