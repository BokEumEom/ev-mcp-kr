# Rule: 시크릿 위생 (SERVICE_KEY)

## 절대 금지

- 코드, 테스트, 로그, 에러 메시지, 응답 본문, 커밋 메시지, 문서 어디에도 진짜 `SERVICE_KEY` 가 들어가서는 안 됩니다.
- `.env.example` 에는 `SERVICE_KEY=` (빈 값) 만. 진짜 값은 항상 `.env` (gitignore됨)에만.
- httpx/HTTPStatusError 메시지를 그대로 로그/예외에 넣지 말 것 — URL에 쿼리 파라미터로 키가 들어가 있음.

## 의무

- `Settings.service_key` 는 `SecretStr`. `.get_secret_value()` 호출은 **요청 직전 한 곳**에서만.
- 외부 응답 본문을 메시지에 노출할 때는 `EvChargerClient._redact()` 로 마스킹 후.
- 새 외부 API 키 추가 시:
  1. `.env.example` 에 빈 값 + 한 줄 코멘트
  2. `Settings` 에 `SecretStr` 필드
  3. 클라이언트의 `_redact()` 와 동등한 마스킹 헬퍼 (재사용 권장)

## 보안 사고 대응

발견 즉시:
1. 작업 멈춤. 시크릿이 어디까지 퍼졌는지 점검 (커밋 히스토리, CI 로그, 외부 시스템).
2. 사용자에게 보고.
3. 키 폐기·재발급 후에 작업 재개.
