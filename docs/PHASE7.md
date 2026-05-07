# Phase 7 보고 — MCPB 번들 패키징

**기간:** 2026-05-07
**범위:** Claude Desktop 용 MCPB(.mcpb) 번들 + stdio CLI 진입점 + sync 콘솔 스크립트
**검증:** pytest **102건** 통과, ruff 클린, mypy `--strict` 클린, `mcpb validate` 통과, `mcpb pack` 으로 `ev-mcp.mcpb` 68KB 생성, stdio 진입점 boot 확인.

## 요약 (3줄)

Render 호스팅을 위한 신용카드 등록 장벽을 회피하고 사용자 프라이버시 (각자 자기 SERVICE_KEY) 까지 자연 해결하는 **MCPB 번들 배포 모드** 추가. 기존 HTTP 서버 진입점은 그대로 두고 `--stdio` 플래그로 동일 코드를 stdio MCP 트랜스포트로 띄울 수 있게 했고, sync 스크립트도 `ev-mcp-sync` 콘솔 명령으로 노출. `manifest.json` + `.mcpbignore` 로 mcpb CLI 가 인식하는 표준 번들 만들어 Claude Desktop 에서 드래그&드랍 설치.

## 핵심 결정

- **HTTP 와 stdio 한 코드베이스.** `server.py:main()` 이 `--stdio` / `--http` flag 를 argparse 로 받아 같은 `build_server()` 결과를 stdio 또는 uvicorn 으로 띄움. 트랜스포트만 다를 뿐 모든 도구 / 캐시 / store 로직 공유.
- **sync 모듈 패키지로 이전.** `scripts/sync_chargers.py` → `src/ev_mcp/sync.py` 옮겨 `ev-mcp-sync` 콘솔 스크립트 등록. 기존 `scripts/sync_chargers.py` 는 thin shim 으로 보존 (`pip install` 안 한 환경에서도 `python scripts/sync_chargers.py` 작동).
- **MCPB user_config 4 개.** SERVICE_KEY (필수, sensitive), VWORLD_KEY (선택, sensitive), DB_PATH (선택, default `${HOME}/.ev-mcp/chargers.db`), LOG_LEVEL (선택, default INFO).
- **데이터고고개알 키 = 사용자 본인 키.** 우리가 키를 호스팅 서버에 박아서 공유 운영하는 모드 (Phase 4~5) 가 약관 회색지대였는데, MCPB 모드는 **각 사용자가 자기 활용신청 + 자기 키** 라 약관 정합성 자연 해결.
- **DB 도 사용자 PC 에 영속.** 한 번 sync 한 SQLite 파일이 사용자 머신에 남아 있어 Claude Desktop 재시작이나 다른 머신 영향 없음. 각자 sync 책임.

## 추가/변경된 모듈

### 신규
| 파일 | 역할 |
|---|---|
| `manifest.json` | MCPB 메타데이터 (manifest_version 0.2). server.type=python, entry_point, mcp_config (command=python, args=`-m ev_mcp.server --stdio`, env interpolation), tools 7개, user_config 4개, compatibility (linux/darwin/win32, python>=3.12) |
| `.mcpbignore` | mcpb pack 이 제외할 디렉터리/파일 (.venv, .git, data/, docs/, tests/, *.docx 등) |
| `src/ev_mcp/sync.py` | 패키지 내부 sync 모듈. 기존 `scripts/sync_chargers.py` 의 sync 함수 + main argparse 그대로 |
| `docs/PHASE7.md` | 이 보고서 |

### 변경
| 파일 | 변경 |
|---|---|
| `src/ev_mcp/server.py` | `main()` 에 argparse `--stdio` / `--http` 플래그 추가. 인자로 transport 직접 받는 호환 경로도 유지 (테스트용) |
| `pyproject.toml` | `ev-mcp-sync = "ev_mcp.sync:main"` 콘솔 스크립트 추가 |
| `scripts/sync_chargers.py` | thin shim 으로 축소 (sys.path 조정 후 `from ev_mcp.sync import main`) |
| `tests/test_sync.py` | `import sync_chargers` (scripts/) → `from ev_mcp import sync as sync_chargers` (패키지) |
| `README.md` | "Claude Desktop 에 MCPB 로 설치 (권장)" 섹션 추가. 기존 Render 섹션은 "선택, 호스팅 필요" 로 격하 |

## MCPB 번들 구조

```
ev-mcp.mcpb (68KB zip)
├── manifest.json              ← 메타 + 실행 명령
├── pyproject.toml             ← deps 명시 (런타임에 user 가 pip install 필요)
├── README.md
├── CLAUDE.md, AGENTS.md
├── .env.example
├── src/ev_mcp/                ← 패키지 본체
│   ├── server.py, store.py, sync.py
│   ├── client.py, models.py, settings.py, geocode.py, ...
│   ├── codes/*.json
│   └── tools/*.py
└── (.gitignore 와 .mcpbignore 가 .venv, data/*.db, tests, docs 등 제외)
```

## 의존성 정책 — 첫 사용자 경험

`.mcpb` 자체에는 **Python 패키지 의존성을 번들링하지 않음** (~200MB 부담 + 플랫폼 호환성). 대신:

- 사용자가 `git clone + uv pip install -e .` 로 venv 에 의존성 설치 → 그 venv 의 `python` 을 manifest 의 `command` 로 지목
- 또는 `uv tool install ev-mcp` 같은 글로벌 설치 (향후 PyPI 배포 시)

향후 Phase 8 에서 self-contained 옵션 (uv 기반 zipapp 또는 venv 번들) 검토 가능.

## 검증

```bash
$ mcpb validate manifest.json
Manifest schema validation passes!

$ mcpb pack . /tmp/ev-mcp.mcpb
package size: 68.0kB
unpacked size: 145.2kB
total files: 48
ignored (.mcpbignore) files: 82

$ python -m pytest -q
102 passed in 0.84s

$ python -m ruff check .
All checks passed!

$ python -m mypy src/
Success: no issues found in 19 source files

$ ev-mcp --stdio < /dev/null   # FastMCP banner 출력 후 EOF 처리 — boot 확인
$ ev-mcp-sync --help            # CLI 등록 확인
```

## 사용자 액션 — 처음 설치

1. `git clone https://github.com/BokEumEom/ev-mcp-kr.git && cd ev-mcp-kr`
2. `uv venv .venv && source .venv/bin/activate && uv pip install -e .`
3. `cp .env.example .env` → `SERVICE_KEY`, (선택) `VWORLD_KEY` 입력
4. `ev-mcp-sync` — 첫 sync (~1 시간, 영속됨, 끊어도 OK)
5. `mcpb pack . ev-mcp.mcpb` (또는 GitHub Releases 다운로드)
6. Claude Desktop → Settings → Extensions → Install from File → `ev-mcp.mcpb`
7. user_config 입력 (SERVICE_KEY, DB_PATH=절대경로, Python path=venv python)
8. Claude 새 대화 → "에버온 충전기 알려줘" / "강남역 근처 DC콤보" 등

## Render 호스팅 모드 (Phase 4~5) 와의 비교

| 항목 | Render 모드 | MCPB 모드 |
|---|---|---|
| 호스팅 비용 | $7~25/월 (CC 필수) | 0 |
| Claude 클라이언트 | claude.ai (웹) + Desktop | Desktop 전용 |
| SERVICE_KEY | 운영자 1 명이 공유 | 각 사용자 본인 |
| DB | 컨테이너 / 영속 디스크 운영 | 사용자 PC 에 영속 |
| 첫 sync | 운영자가 cron | 각 사용자 1 회 |
| 약관 리스크 | data.go.kr 키 공유 우회 회색지대 | 정합 (각자 자기 키) |
| 다중 동시 사용자 | 한 인스턴스가 다 처리 | 각자 자기 인스턴스 |

두 모드 모두 같은 코드베이스에서 작동 (`--stdio` vs `--http` 플래그만 차이). Claude 디렉터리 제출은 Render 모드를 유지하면서, 개인 사용/배포는 MCPB 가 자연스러움.

## 다음 단계 (Phase 8 후보)

1. **Self-contained MCPB.** `uv` zipapp 또는 venv 번들링으로 사용자가 `pip install` 단계 없이 .mcpb 만 받아 설치 가능하게.
2. **PyPI 배포.** `pip install ev-mcp` / `uv tool install ev-mcp` 로 global 설치 가능.
3. **GitHub Releases 자동화.** main 푸시 시 .mcpb 자동 빌드 + Release 생성 (GitHub Actions).
4. **incremental sync.** 풀 sync 대신 `statUpdDt > 마지막_polled` 인 행만 받아 빠르게 갱신.
5. **icon.png** 추가 (manifest 의 icon 필드 복원).
