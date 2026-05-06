---
description: docx 에서 코드 테이블(sigungu 등)을 다시 추출해 src/ev_mcp/codes/ 갱신.
---

코드 테이블 자동 갱신.

```bash
source .venv/bin/activate
python scripts/extract_sigungu.py
# 향후 다른 추출 스크립트도 여기에 추가
```

실행 후 `git diff src/ev_mcp/codes/` 로 변경 확인. 변경이 있으면 사용자에게 보고하고
docs/PHASE{현재}.md 또는 별도 메모에 변경 항목 기록.

직접 JSON 편집 금지 — 항상 이 명령으로만.
