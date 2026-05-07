# ev-mcp on Cloudflare Workers

Phase 9 — TypeScript port of the Python `ev_mcp` (see repo root).

## 빠른 시작

```bash
cd workers
npm install

# 시크릿 설정 (Cloudflare 계정 필요)
npx wrangler secret put SERVICE_KEY
# (선택) npx wrangler secret put VWORLD_KEY

# 로컬 dev
npm run dev   # http://localhost:8787/mcp 에서 streamable HTTP

# 테스트
npm test

# 배포
npm run deploy
# → https://ev-mcp.<account>.workers.dev/mcp
```

## 아키텍처 / Stage 진행

상세는 `docs/PHASE9.md` (레포 루트의 `docs/`).

- **Worker** (`src/index.ts`): MCP fetch handler + agents-mcp 라우팅
- **Durable Object** (`src/inventory.ts`): `ChargerInventory` — SQLite 영속 인벤토리
- **Tools** (`src/tools/`): MCP 도구 1:1 포팅
- **Codes** (`src/codes/`): 정적 코드 테이블 (Python `src/ev_mcp/codes/*.json` 와 동일 데이터)

## Python 과의 관계

루트의 Python 구현 (`src/ev_mcp/`) 은 그대로 유지 — MCPB 모드, 로컬 stdio, Render HTTP 호스팅 모두 계속 작동. 이 디렉터리는 **Cloudflare Workers 전용 변형**.

코드 테이블 (`codes/*`) 은 docx 스펙으로부터 동일하게 추출된 데이터를 양쪽이 각자 임포트.
