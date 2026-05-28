"""분석 툴 공유 상수 — 여러 툴이 동일하게 쓰는 코드 집합."""

from __future__ import annotations

# 급속 충전기로 분류하는 chger_type 코드 (DC 차데모/콤보 계열 + NACS).
# "02" AC완속·"07" AC3상 은 완속이라 제외. 상세는 regional_density docstring 참고.
DC_CODES: tuple[str, ...] = ("01", "03", "04", "05", "06", "08", "09", "10")
