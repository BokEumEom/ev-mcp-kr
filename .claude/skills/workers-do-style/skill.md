---
name: workers-do-style
description: ev-mcp 의 Cloudflare Workers + Durable Objects SQL 작성 스타일. rows-written cap(무료 ~1M/월) 회피를 위한 smart upsert, 인덱스 설계, 배치 처리, fetch 모킹 패턴까지. workers/ 디렉토리의 .ts 파일을 작성·수정할 때, 특히 inventory_store.ts / sync.ts / agent.ts 를 만질 때 반드시 트리거. workers-builder 가 사용.
---

# Workers + DO SQL 스타일 가이드

ev-mcp 의 `workers/` 는 Cloudflare Workers + Durable Objects SQL 백엔드. 무료 플랜의 **rows-written cap (~1M/월)** 이 가장 큰 제약. 모든 코드는 이 제약을 의식해야 한다.

## Smart Upsert 패턴 (핵심)

전국 ~506k row 를 매일 full-sync 하면 무료 캡을 즉시 위반. 해결책: **변경된 row 만 쓰기.**

`workers/src/inventory_store.ts` 의 실제 패턴 — 세 단계로 분리:

**1단계. 기존 row 의 stat_upd_dt 만 빠르게 조회**

```ts
const existing = sql
  .prepare("SELECT stat_upd_dt FROM chargers WHERE stat_id = ?")
  .bind(row.stat_id)
  .first<{ stat_upd_dt: string }>();
```

**2단계. upd_dt 동일하면 write 발생 안 시키고 skip**

```ts
if (existing?.stat_upd_dt === row.stat_upd_dt) {
  return { written: false };
}
```

**3단계. 다를 때만 INSERT OR REPLACE**

```ts
sql
  .prepare("INSERT OR REPLACE INTO chargers (...) VALUES (...)")
  .bind(/* ... */)
  .run();
return { written: true };
```

**규칙:**
- 모든 upsert 는 변경 감지 게이트 (timestamp/hash) 통과 후에만
- `processedRows` (스캔한 row 수) 와 `writtenRows` (실제 write 한 row 수) 를 분리 계측
- sync 결과 로그에 둘 다 노출: `[sync.tick] processed=506234 written=1842`

## 인덱스 설계

DO SQL 은 SQLite 기반. 인덱스 규칙:
- 외래키처럼 자주 join 되는 칼럼 (stat_id, busi_id, zcode)
- 필터링 핫패스 (예: `stat = '2'` for "사용가능") — 인덱스 + cardinality 검토
- `CREATE INDEX IF NOT EXISTS` 항상 사용 (migration 안전)

## fetch 모킹 패턴

테스트에서 외부 호출은 vitest mock 으로 가로채기:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";

beforeEach(() => {
  global.fetch = vi.fn(async (url: string) => {
    if (url.includes("apis.data.go.kr")) {
      return new Response(JSON.stringify({ /* fixture */ }), { status: 200 });
    }
    throw new Error(`unexpected fetch: ${url}`);
  }) as typeof fetch;
});
```

**규칙:**
- SERVICE_KEY 가 URL 쿼리에 들어가므로 URL 검증 시 마스킹된 fixture URL 만 비교
- 503/429 시뮬레이션 테스트 필수 (retry 동작 검증)

## 환경변수 / 시크릿

`wrangler.toml` 의 vars/secrets:
- `SERVICE_KEY` — Cloudflare secret (커밋 금지)
- `VWORLD_KEY` — secret (선택)
- 기타 비-시크릿은 `vars` 섹션

규칙:
- 새 secret 추가 시 `wrangler.toml` 수정하지 말고 사용자에게 안내: `wrangler secret put NEW_KEY`
- `env.SERVICE_KEY` 를 직접 로그 출력 X — `client.ts` 의 마스킹 헬퍼 사용

## 에러 처리

```ts
async function fetchUpstream(url: string): Promise<unknown> {
  try {
    const res = await fetch(url);
    if (!res.ok) {
      throw new UpstreamError(`status=${res.status}`); // URL 절대 포함 X
    }
    return await res.json();
  } catch (e) {
    if (e instanceof UpstreamError) throw e;
    throw new UpstreamError(`network: ${(e as Error).message}`);
  }
}
```

**규칙:**
- 5xx → exponential backoff (예: 500ms, 1s, 2s, max 3 retries)
- 429 → `Retry-After` 헤더 존중
- SERVICE_KEY 가 들어간 URL 은 절대 예외 메시지/로그에 그대로 노출 X

## 타입 / 불변성

- `tsconfig.json` strict 모드. `any` 금지 (불가피하면 `unknown` 후 좁히기)
- 객체 변경은 spread: `{ ...obj, x: y }`. mutation 금지.
- `as const` 적극 사용 (코드 테이블 같은 정적 데이터)

## DO 라이프사이클

- DO 인스턴스는 region-pinned. 일반적으로 1개 인스턴스 (전국 데이터)
- `alarm()` 으로 sync 트리거 — `setAlarm(Date.now() + 24 * 60 * 60 * 1000)` 같은 패턴
- WAL 모드는 DO SQL 에서 자동 — 별도 PRAGMA 불필요

## sync.ts 작성 시 체크리스트

- [ ] processedRows / writtenRows 분리
- [ ] 페이지네이션 (numOfRows=1000 권장, 9999 는 timeout 위험)
- [ ] 페이지 간 progress 저장 (alarm 재시작 대비)
- [ ] 503/429 retry
- [ ] 최종 보고 log 한 줄

## 절대 금지

- DO SQL 에 unconditional `INSERT OR REPLACE` (rows cap 위반)
- `npm install` 직접 실행 — 사용자 컨펌
- `wrangler deploy` 직접 실행 — 사용자만
- fetch 응답 본문을 그대로 console.log (SERVICE_KEY 가 echo 됐을 수 있음)
- `any` 타입 (정말 불가피하면 `unknown` + 좁히기)
