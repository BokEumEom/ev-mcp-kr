---
name: secret-hygiene
description: ev-mcp 의 SERVICE_KEY / VWORLD_KEY 시크릿 위생 점검과 누출 정적 검사. 새 로그 / 예외 / 응답 본문 / 테스트 fixture 작성 시 반드시 트리거. quality-gate 가 ⑤ review 에서 자동 호출. python-builder / workers-builder 도 작성 직후 자기 검사용으로 사용.
---

# Secret Hygiene — SERVICE_KEY 누출 방지

`.claude/rules/secrets.md` 의 운영판. 실제 grep 명령과 안전 패턴 포함.

## 보호 대상

- `SERVICE_KEY` (data.go.kr) — **운영 핵심 시크릿**
- `VWORLD_KEY` (지오코딩) — 선택, 그러나 무료 쿼터 보호 필요
- 향후 추가될 `Bearer` / `OAuth` 토큰 (현재 v1 에는 없음)

## 위험 지점 (체크리스트)

| 위치 | 위험 |
|---|---|
| `httpx`/`fetch` 예외 메시지 | URL 쿼리에 키가 들어감 — 그대로 `str(e)` 하면 누출 |
| 로그 (`console.log`, `print`, `logging.error`) | 응답 본문 / URL 전체 echo |
| 테스트 fixture | 실제 응답 마스킹 안 한 채 commit |
| 도크스트링 / 주석 | 예시에 실제 키 |
| 커밋 메시지 | `.env` 의 값을 우연히 인용 |
| 응답 본문 (사용자에게 반환) | 디버깅 필드에 echo |

## 정적 검사 (quality-gate ⑤ review 자동 수행)

변경 파일에 대해:

```bash
# 1) 직접 키 패턴 (data.go.kr 키는 보통 100+자 base64)
git diff main --unified=0 -- '*.py' '*.ts' '*.json' '*.md' \
  | grep -E 'serviceKey=[A-Za-z0-9%+/=]{40,}|SERVICE_KEY\s*=\s*["\047][A-Za-z0-9%]{40,}'

# 2) URL 전체를 로그/예외에 넣는 패턴
git diff main -- '*.py' \
  | grep -E '(logger|logging|print|raise)\.(error|warning|info|exception).*\.url|e\.request\.url'

git diff main -- '*.ts' \
  | grep -E 'console\.(log|error|warn).*url|new Error.*\$\{.*url'

# 3) httpx/fetch 예외 직접 노출
git diff main -- '*.py' \
  | grep -E 'raise.*str\(e\)|raise.*\{e\}'
```

위 셋 중 하나라도 매치하면 **CRITICAL 발견** — review verdict "지금 멈춤".

## 안전 패턴

### Python — Settings + SecretStr

```python
from pydantic import SecretStr

class Settings(BaseSettings):
    service_key: SecretStr

# 사용 직전 한 곳에서만 .get_secret_value()
async def call_api(settings: Settings):
    params = {"serviceKey": settings.service_key.get_secret_value(), ...}
```

### Python — client._redact()

응답 본문이나 URL 을 메시지에 넣어야 할 때:

```python
class EvChargerClient:
    @staticmethod
    def _redact(text: str) -> str:
        # SERVICE_KEY 패턴을 마스킹
        return re.sub(r'serviceKey=[^&\s]+', 'serviceKey=REDACTED', text)

    async def get(self, ...):
        try:
            r = await self._http.get(url, params=params)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise EvChargerError(
                f"data.go.kr 응답 오류: status={e.response.status_code} "
                f"body={self._redact(e.response.text)[:200]}"
            )
```

### TypeScript — 마스킹 헬퍼

```ts
function redact(text: string): string {
  return text.replace(/serviceKey=[^&\s]+/g, "serviceKey=REDACTED");
}

throw new UpstreamError(`status=${res.status} body=${redact(await res.text())}`);
```

## 새 시크릿 추가 시 (체크리스트)

1. `.env.example` 에 `NEW_KEY=` (빈 값) + 한 줄 코멘트 추가
2. `Settings` (Python) 에 `SecretStr` 필드 추가
3. `workers/wrangler.toml` 에 추가하지 말고 사용자에게 `wrangler secret put NEW_KEY` 안내
4. 클라이언트 redact 헬퍼에 새 패턴 추가
5. 테스트 fixture URL/응답에 마스킹 확인

## 사고 대응 (누출 의심 시)

1. **작업 즉시 멈춤.**
2. 누출 범위 점검:
   ```bash
   git log -p --all -S 'serviceKey=' | head -50  # 커밋 히스토리
   # CI 로그도 점검 (GitHub Actions, Render 등)
   ```
3. 사용자에게 보고 (구체적인 파일/라인 + 추정 누출 경로)
4. 사용자가 키 폐기·재발급 완료한 뒤에만 작업 재개
5. 회귀 테스트 추가 (해당 경로에서 SERVICE_KEY 가 나오면 fail)

## 회귀 테스트 패턴

```python
# tests/test_client.py
def test_redact_in_error():
    e = httpx.HTTPStatusError(...)
    e.request.url = httpx.URL("https://api/?serviceKey=SECRET&page=1")
    try:
        client._handle_error(e)
    except EvChargerError as err:
        assert "SECRET" not in str(err)
        assert "REDACTED" in str(err)
```

이 패턴의 테스트가 `tests/` 와 `workers/test/` 양쪽에 최소 1개씩 있어야 한다.

## 절대 금지

- `.env` 파일 commit (gitignore 확인)
- 실제 SERVICE_KEY 를 도크스트링/주석/PR 본문에 인용
- `httpx.HTTPStatusError` 또는 `Response` 객체를 그대로 raise 또는 log
- 테스트에서 실제 data.go.kr 호출 (CI 에는 키 없음 + 누출 위험)
