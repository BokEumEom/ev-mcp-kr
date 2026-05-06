---
description: pytest + ruff + mypy 세 가지 체크 한 번에 실행. 결과 한 화면에 요약.
---

다음 명령들을 차례로 실행하고, 마지막에 한 줄 종합 요약을 출력하세요.

```bash
source .venv/bin/activate
echo "--- pytest ---"
python -m pytest -q
echo "--- ruff ---"
python -m ruff check .
echo "--- mypy ---"
python -m mypy src/
```

종합 요약 형식:
- ✅ 모두 그린 → "VERIFY OK — pytest {N}건, ruff clean, mypy strict clean"
- ❌ 하나라도 실패 → 실패한 도구와 핵심 메시지 한 줄, 그리고 어디 파일인지.

추가 작업 없이 결과만 보고합니다. 자동 수정 금지 (`ruff --fix` 등 X).
