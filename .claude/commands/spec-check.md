---
description: docx 스펙과 현재 코드(models.py + codes/*.json)의 일치성 감사.
---

`spec-auditor` 서브에이전트를 디스패치해 docx ↔ 코드 일치성을 감사합니다.

## Agent 호출

`Agent` 툴, `subagent_type=general-purpose`(spec-auditor 미정의 시) 또는
`subagent_type=spec-auditor` 로 호출. 프롬프트:

> 한국환경공단 EV 충전소 OpenAPI v1.23 스펙 감사를 수행하세요.
>
> 대상:
> - 스펙 원본: `/home/bokeum/ai/ev_mcp/한국환경공단_전기자동차 충전소 정보_OpenAPI활용가이드_v1.23.docx`
> - 현재 모델: `src/ev_mcp/models.py`
> - 코드 테이블: `src/ev_mcp/codes/{sido,sigungu,charger_type,stat,busi_id,kind,kind_detail}.json`
>
> 검사 항목:
> 1. **getChargerInfo / getChargerStatus 응답 필드 누락**: docx 표에 있는데 모델에 없는 필드.
> 2. **타입/필수 여부 불일치**: 항목구분(필수1/옵션0)과 모델의 Optional 일치.
> 3. **항목 크기**: 스펙의 "항목크기" 와 현재 모델의 max_length (지정 안 됐으면 미설정 보고).
> 4. **코드 테이블 누락 항목**: docx 의 sido/sigungu/charger_type 등 표에 있는데 JSON 에 없는 코드.
> 5. **추가된 코드 vs 코드 표**: 모델에서 enum 으로 받는 값(stat 등) 이 코드 표와 동기화됐는가.
>
> 출력: 각 발견을 `[항목] {설명} | docx: {원문} | 코드: {현재} | 권장 조치` 표로.
> 마지막에 한 줄 verdict: "동기 OK" / "사소 차이" / "스펙 갱신 필요".
>
> 응답은 한국어 300단어 이내.

## 결과 처리

verdict 가 "스펙 갱신 필요" 면:
- TaskCreate 로 변경 항목별 todo 추가
- 코드 테이블 변경은 반드시 `python scripts/extract_*.py` 또는 새 스크립트로 — 직접 편집 금지
- 모델 변경은 `.claude/rules/spec-discipline.md` 따를 것

verdict 가 "사소 차이" 면 사용자에게 표만 보여주고 의사결정 위임.
