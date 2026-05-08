import { describe, expect, it, vi } from "vitest";

import { EvChargerClient } from "../client.js";
import {
  getChargerStatus,
  RecentChangesCache,
  recentStatusChanges,
} from "./status.js";

function clientReturning(items: object[], totalCount?: number): EvChargerClient {
  const fetchImpl = vi.fn(async () =>
    new Response(
      JSON.stringify({
        resultCode: "00",
        resultMsg: "ok",
        totalCount: totalCount ?? items.length,
        items: { item: items },
      }),
      { status: 200 },
    ),
  ) as unknown as typeof fetch;
  return new EvChargerClient({ serviceKey: "k", fetchImpl });
}

const sampleRow = (overrides: Record<string, string> = {}) => ({
  busiId: "ME",
  statId: "ME000001",
  chgerId: "01",
  stat: "2",
  statUpdDt: "20260507143015",
  lastTsdt: "",
  lastTedt: "",
  nowTsdt: "",
  ...overrides,
});

describe("getChargerStatus tool", () => {
  it("returns the exact-match row when upstream returns it", async () => {
    const client = clientReturning([
      sampleRow({ statId: "ME000001", chgerId: "01" }),
    ]);
    const r = await getChargerStatus(client, {
      stat_id: "ME000001",
      chger_id: "01",
    });
    const data = r.structuredContent as { found: boolean; stat_label: string };
    expect(data.found).toBe(true);
    expect(data.stat_label).toBe("충전대기");
  });

  it("returns found:false when upstream is empty", async () => {
    const client = clientReturning([]);
    const r = await getChargerStatus(client, {
      stat_id: "MISSING",
      chger_id: "99",
    });
    expect((r.structuredContent as { found: boolean }).found).toBe(false);
    expect(r.content[0]?.text).toContain("MISSING");
  });

  it("prefers the exact match when upstream returns multiple rows", async () => {
    const client = clientReturning([
      sampleRow({ statId: "OTHER", chgerId: "01" }),
      sampleRow({ statId: "WANT", chgerId: "02" }),
    ]);
    const r = await getChargerStatus(client, { stat_id: "WANT", chger_id: "02" });
    expect((r.structuredContent as { stat_id: string }).stat_id).toBe("WANT");
  });
});

describe("recentStatusChanges tool", () => {
  it("sorts by stat_upd_dt desc and slices to limit", async () => {
    const client = clientReturning([
      sampleRow({ statId: "OLD", statUpdDt: "20260507120000" }),
      sampleRow({ statId: "NEW", statUpdDt: "20260507150000" }),
      sampleRow({ statId: "MID", statUpdDt: "20260507130000" }),
    ]);
    const cache = new RecentChangesCache();
    const r = await recentStatusChanges(client, cache, { period: 5, limit: 2 });
    const data = r.structuredContent as {
      count: number;
      chargers: Array<{ stat_id: string }>;
    };
    expect(data.count).toBe(2);
    expect(data.chargers[0]?.stat_id).toBe("NEW");
    expect(data.chargers[1]?.stat_id).toBe("MID");
  });

  it("serves second call from cache (same args)", async () => {
    const fetchImpl = vi.fn(async () =>
      new Response(
        JSON.stringify({
          resultCode: "00",
          resultMsg: "ok",
          totalCount: 1,
          items: { item: [sampleRow()] },
        }),
        { status: 200 },
      ),
    ) as unknown as typeof fetch;
    const client = new EvChargerClient({ serviceKey: "k", fetchImpl });
    const cache = new RecentChangesCache();
    await recentStatusChanges(client, cache, { period: 5, limit: 1 });
    await recentStatusChanges(client, cache, { period: 5, limit: 1 });
    // Cache hit on the second call → fetch invoked exactly once.
    expect((fetchImpl as unknown as { mock: { calls: unknown[] } }).mock.calls).toHaveLength(1);
  });

  it("misses cache when args differ", async () => {
    const fetchImpl = vi.fn(async () =>
      new Response(
        JSON.stringify({
          resultCode: "00",
          resultMsg: "ok",
          totalCount: 1,
          items: { item: [sampleRow()] },
        }),
        { status: 200 },
      ),
    ) as unknown as typeof fetch;
    const client = new EvChargerClient({ serviceKey: "k", fetchImpl });
    const cache = new RecentChangesCache();
    await recentStatusChanges(client, cache, { period: 5, limit: 10 });
    await recentStatusChanges(client, cache, { period: 5, limit: 20 }); // different limit → different key
    expect((fetchImpl as unknown as { mock: { calls: unknown[] } }).mock.calls).toHaveLength(2);
  });
});

describe("RecentChangesCache", () => {
  it("expires entries after TTL", () => {
    const cache = new RecentChangesCache();
    cache.set("k", { hello: "world" });
    expect(cache.get("k")).toEqual({ hello: "world" });

    // Advance time past the 60-second TTL.
    vi.useFakeTimers();
    vi.setSystemTime(Date.now() + 61_000);
    expect(cache.get("k")).toBeNull();
    vi.useRealTimers();
  });
});
