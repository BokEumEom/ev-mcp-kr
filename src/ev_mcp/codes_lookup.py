"""Lazy loaders for the static code tables shipped under codes/*.json.

Loaded once at import; subsequent calls hit dict in memory.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import cast

_CODES_DIR = Path(__file__).parent / "codes"


@cache
def _load(name: str) -> dict[str, str]:
    path = _CODES_DIR / f"{name}.json"
    return cast("dict[str, str]", json.loads(path.read_text(encoding="utf-8")))


def sido_table() -> dict[str, str]:
    return _load("sido")


def sigungu_table() -> dict[str, str]:
    return _load("sigungu")


def charger_type_table() -> dict[str, str]:
    return _load("charger_type")


def stat_table() -> dict[str, str]:
    return _load("stat")


def busi_id_table() -> dict[str, str]:
    return _load("busi_id")


def kind_table() -> dict[str, str]:
    return _load("kind")


def kind_detail_table() -> dict[str, str]:
    return _load("kind_detail")


def sido_label(code: str) -> str:
    return sido_table().get(code, code)


def sigungu_label(code: str) -> str:
    return sigungu_table().get(code, code)


def charger_type_label(code: str) -> str:
    return charger_type_table().get(code, f"코드 {code}")


def stat_label(code: str) -> str:
    return stat_table().get(code, "알수없음")


def busi_id_label(code: str) -> str:
    return busi_id_table().get(code, code)


def kind_label(code: str) -> str:
    return kind_table().get(code, code)


def kind_detail_label(code: str) -> str:
    return kind_detail_table().get(code, code)


def resolve_sido(query: str) -> str | None:
    """Map "서울특별시" or "11" or "서울" → zcode. Returns None if unresolvable."""
    if query in sido_table():
        return query
    for code, name in sido_table().items():
        if name == query or name.startswith(query) or query in name:
            return code
    return None


def resolve_sigungu(query: str) -> str | None:
    """Map "강남구" or "11680" → zscode. Returns None if unresolvable."""
    if query in sigungu_table():
        return query
    matches = [code for code, name in sigungu_table().items() if name == query]
    if len(matches) == 1:
        return matches[0]
    return None


def resolve_busi_id(query: str) -> str | None:
    """Map "환경부" / "ME" / "기후에너지환경부" / "에버온" → busiId."""
    if query in busi_id_table():
        return query
    for code, name in busi_id_table().items():
        if name == query or query in name:
            return code
    return None
