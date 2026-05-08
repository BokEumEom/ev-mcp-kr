import { describe, expect, it, vi } from "vitest";

import { runSyncTick, type SyncEnv } from "./sync.js";
import type { ChargerInfo } from "./types.js";

/**
 * Build a fake STORE binding that exposes only the methods runSyncTick uses.
 * State is held in a plain Map. The InventoryStore RPC interface is sync at
 * the DO side and async at the stub side — we use async here to match the
 * stub-side shape that runSyncTick consumes.
 */
function fakeEnv(opts: {
  /**
   * Sequenced upstream responses. Each call to client.getChargerInfo dequeues
   * the next entry. `count` defaults to numOfRows so cycle never ends from a
   * short page; pass an explicit short count to trigger cycle completion.
   */
  pages: Array<{ totalCount: number; count?: number }>;
  serviceKey?: string;
}): { env: SyncEnv; state: Map<string, string>; rowsUpserted: ChargerInfo[][] } {
  const state = new Map<string, string>();
  const rowsUpserted: ChargerInfo[][] = [];

  const fakeStore = {
    upsertMany: vi.fn(async (rows: readonly ChargerInfo[]) => {
      rowsUpserted.push([...rows]);
      return rows.length;
    }),
    setSyncState: vi.fn(async (key: string, value: string) => {
      state.set(key, value);
    }),
    getSyncState: vi.fn(async (key: string) => state.get(key) ?? null),
    totalCount: vi.fn(async () =>
      rowsUpserted.reduce((acc, batch) => acc + batch.length, 0),
    ),
  };

  const STORE = {
    idFromName: vi.fn(() => ({ name: "global" })),
    get: vi.fn(() => fakeStore),
  };

  const upstreamPages = [...opts.pages];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : (input as URL).toString();
    const numOfRows = Number(new URL(url).searchParams.get("numOfRows") ?? "0");
    const next = upstreamPages.shift();
    if (next == null) throw new Error("upstream queue exhausted");
    const rowCount = next.count ?? numOfRows;
    const rows = Array.from({ length: rowCount }, (_, i) => ({
      statNm: `Station ${i}`,
      statId: `S${i}`,
      chgerId: "01",
      chgerType: "04",
      addr: "addr",
      lat: 37.5,
      lng: 127.0,
      useTime: "24h",
      busiId: "ME",
      bnm: "ME",
      busiNm: "ME",
      stat: "2",
      zcode: "11",
    }));
    return new Response(
      JSON.stringify({
        resultCode: "00",
        resultMsg: "ok",
        totalCount: next.totalCount,
        items: { item: rows },
      }),
      { status: 200 },
    );
  });
  // EvChargerClient ignores opts.fetchImpl by default in production but
  // accepts it in tests; we rely on that here.
  // Stash the fetchImpl on globalThis so the client picks it up — actually
  // EvChargerClient binds `fetch` from globalThis when no fetchImpl is given.
  (globalThis as unknown as { fetch: typeof fetch }).fetch =
    fetchImpl as unknown as typeof fetch;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const env: SyncEnv = { SERVICE_KEY: opts.serviceKey ?? "test-key", STORE: STORE as any };
  return { env, state, rowsUpserted };
}

describe("runSyncTick — fresh cycle", () => {
  it("first tick locks pageSize and stores total_pages + cycle_started_at", async () => {
    const { env, state } = fakeEnv({
      pages: [{ totalCount: 10000 }], // 10000 / 2000 = 5 pages
    });
    const r = await runSyncTick(env, { pageSize: 2000, pagesPerTick: 1 });

    expect(r.startedAtPage).toBe(1);
    expect(r.lastCompletedPage).toBe(1);
    expect(r.pageSizeUsed).toBe(2000);
    expect(r.pageSizeOverridden).toBe(false);
    expect(r.totalPages).toBe(5);
    expect(r.done).toBe(false);

    expect(state.get("page_size")).toBe("2000");
    expect(state.get("total_pages")).toBe("5");
    expect(state.get("last_completed_page")).toBe("1");
    expect(state.get("cycle_started_at")).toBeTruthy();
  });

  it("reports correct counts when upstream returns processedRows = numOfRows", async () => {
    const { env, rowsUpserted } = fakeEnv({
      pages: [{ totalCount: 10000 }],
    });
    const r = await runSyncTick(env, { pageSize: 500, pagesPerTick: 1 });
    expect(r.processedRows).toBe(500);
    expect(rowsUpserted[0]).toHaveLength(500);
  });
});

describe("runSyncTick — pageSize lock", () => {
  it("overrides caller's pageSize when locked value differs", async () => {
    const { env, state } = fakeEnv({
      pages: [
        { totalCount: 10000 },
        { totalCount: 10000 },
      ],
    });
    // First tick: lock at 2000.
    await runSyncTick(env, { pageSize: 2000, pagesPerTick: 1 });
    expect(state.get("page_size")).toBe("2000");

    // Second tick: caller asks for 500, but lock takes precedence.
    const r = await runSyncTick(env, { pageSize: 500, pagesPerTick: 1 });
    expect(r.pageSizeUsed).toBe(2000);
    expect(r.pageSizeOverridden).toBe(true);
    expect(r.processedRows).toBe(2000); // not 500
    expect(state.get("page_size")).toBe("2000"); // still locked
  });

  it("does not override when caller's pageSize matches the lock", async () => {
    const { env } = fakeEnv({
      pages: [
        { totalCount: 10000 },
        { totalCount: 10000 },
      ],
    });
    await runSyncTick(env, { pageSize: 2000, pagesPerTick: 1 });
    const r = await runSyncTick(env, { pageSize: 2000, pagesPerTick: 1 });
    expect(r.pageSizeOverridden).toBe(false);
  });
});

describe("runSyncTick — cycle completion", () => {
  it("releases the lock and writes last_synced_at on a short page", async () => {
    const { env, state } = fakeEnv({
      pages: [{ totalCount: 1500, count: 1500 }], // less than numOfRows=2000 → EOF
    });
    const r = await runSyncTick(env, { pageSize: 2000, pagesPerTick: 1 });

    expect(r.done).toBe(true);
    expect(r.lastCompletedPage).toBe(0); // reset
    expect(state.get("page_size")).toBe("0");
    expect(state.get("total_pages")).toBe("0");
    expect(state.get("last_completed_page")).toBe("0");
    expect(state.get("last_synced_at")).toBeTruthy();
  });

  it("marks done when reaching computed total_pages even with full pages", async () => {
    // totalCount=1000, pageSize=500 → totalPages=2. Two ticks of 500-row pages.
    const { env, state } = fakeEnv({
      pages: [
        { totalCount: 1000, count: 500 },
        { totalCount: 1000, count: 500 },
      ],
    });
    const r1 = await runSyncTick(env, { pageSize: 500, pagesPerTick: 1 });
    expect(r1.done).toBe(false);
    expect(state.get("last_completed_page")).toBe("1");

    const r2 = await runSyncTick(env, { pageSize: 500, pagesPerTick: 1 });
    expect(r2.done).toBe(true);
    expect(state.get("page_size")).toBe("0"); // lock released
  });
});

describe("runSyncTick — error handling", () => {
  it("does not advance state on upstream error", async () => {
    const { env, state } = fakeEnv({ pages: [] }); // queue empty → throws
    const r = await runSyncTick(env, { pageSize: 500, pagesPerTick: 1 });
    expect(r.errored).toBeTruthy();
    expect(r.processedPages).toBe(0);
    // last_completed_page never written.
    expect(state.has("last_completed_page")).toBe(false);
  });
});
