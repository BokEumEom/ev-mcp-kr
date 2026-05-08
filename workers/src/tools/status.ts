/**
 * Live-fetch status tools — read directly from data.go.kr's getChargerStatus
 * endpoint. Bypass the InventoryStore intentionally: the SQLite store is a
 * daily snapshot via cron sync, while these tools answer "what is happening
 * right now?" questions that demand sub-minute freshness.
 *
 * Tools:
 *   - get_charger_status: single charger live query
 *   - recent_status_changes: top-N rows ordered by stat_upd_dt desc, with
 *     a 60-second in-memory cache so repeated calls in a short window don't
 *     thrash the upstream (which is slow and rate-limited).
 */

import { busiIdLabel, statLabel } from "../codes/index.js";
import type { EvChargerClient } from "../client.js";
import type { ChargerStatusRow } from "../types.js";

interface ToolResult {
  content: Array<{ type: "text"; text: string }>;
  structuredContent: Record<string, unknown>;
  [key: string]: unknown;
}

const RECENT_CACHE_TTL_MS = 60_000;

interface RecentChangesCacheEntry {
  expiresAt: number;
  payload: Record<string, unknown>;
}

/** In-memory cache shared by recentStatusChanges. Keyed by query shape. */
export class RecentChangesCache {
  private readonly entries = new Map<string, RecentChangesCacheEntry>();

  get(key: string): Record<string, unknown> | null {
    const e = this.entries.get(key);
    if (e == null) return null;
    if (Date.now() >= e.expiresAt) {
      this.entries.delete(key);
      return null;
    }
    return e.payload;
  }

  set(key: string, payload: Record<string, unknown>): void {
    this.entries.set(key, { expiresAt: Date.now() + RECENT_CACHE_TTL_MS, payload });
  }
}

// ---------------------------------------------------------------------------
// get_charger_status
// ---------------------------------------------------------------------------

export interface ChargerStatusArgs {
  stat_id: string;
  chger_id: string;
}

function summarizeRow(r: ChargerStatusRow): Record<string, unknown> {
  return {
    busi_id: r.busi_id,
    busi_label: busiIdLabel(r.busi_id),
    stat_id: r.stat_id,
    chger_id: r.chger_id,
    stat: r.stat,
    stat_label: statLabel(r.stat),
    stat_upd_dt: r.stat_upd_dt,
    last_tsdt: r.last_tsdt,
    last_tedt: r.last_tedt,
    now_tsdt: r.now_tsdt,
  };
}

export async function getChargerStatus(
  client: EvChargerClient,
  args: ChargerStatusArgs,
): Promise<ToolResult> {
  // The endpoint requires zcode for some queries — but stat_id+chger_id
  // alone is enough for a precise single-charger pull, and the response
  // filters server-side.
  const { items } = await client.getChargerStatus({
    statId: args.stat_id,
    chgerId: args.chger_id,
    numOfRows: 10,
  });
  if (items.length === 0) {
    const payload: Record<string, unknown> = {
      stat_id: args.stat_id,
      chger_id: args.chger_id,
      found: false,
    };
    return {
      content: [
        {
          type: "text",
          text:
            `충전기 ${args.stat_id}-${args.chger_id} 의 실시간 상태를 찾을 수 없습니다. ` +
            `stat_id 와 chger_id 를 get_station_details 로 확인 후 호출하세요.`,
        },
      ],
      structuredContent: payload,
    };
  }
  // Pick the exact match (server filter may be loose).
  const exact = items.find(
    (r) => r.stat_id === args.stat_id && r.chger_id === args.chger_id,
  );
  const row = exact ?? items[0]!;
  const payload: Record<string, unknown> = { ...summarizeRow(row), found: true };
  return {
    content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
    structuredContent: payload,
  };
}

// ---------------------------------------------------------------------------
// recent_status_changes
// ---------------------------------------------------------------------------

export interface RecentChangesArgs {
  period?: number | undefined;
  limit?: number | undefined;
  zcode?: string | undefined;
}

export async function recentStatusChanges(
  client: EvChargerClient,
  cache: RecentChangesCache,
  args: RecentChangesArgs,
): Promise<ToolResult> {
  const period = args.period ?? 10;
  const limit = args.limit ?? 20;
  const zcode = args.zcode;

  const cacheKey = `p=${period}|z=${zcode ?? ""}|l=${limit}`;
  const hit = cache.get(cacheKey);
  if (hit != null) {
    return {
      content: [{ type: "text", text: JSON.stringify(hit, null, 2) }],
      structuredContent: hit,
    };
  }

  // Pull a generous page so we can sort+slice in-memory. period=10 is the
  // spec hard maximum; numOfRows=9999 is also the spec max.
  const { header, items } = await client.getChargerStatus({
    period,
    numOfRows: 9999,
    zcode,
  });

  // Sort by stat_upd_dt desc, nulls last.
  const sorted = [...items].sort((a, b) => {
    if (a.stat_upd_dt == null && b.stat_upd_dt == null) return 0;
    if (a.stat_upd_dt == null) return 1;
    if (b.stat_upd_dt == null) return -1;
    return b.stat_upd_dt.localeCompare(a.stat_upd_dt);
  });
  const top = sorted.slice(0, limit);

  const payload: Record<string, unknown> = {
    period_minutes: period,
    zcode: zcode ?? null,
    total_returned: items.length,
    total_count: header.total_count,
    count: top.length,
    chargers: top.map(summarizeRow),
    cached_until: new Date(Date.now() + RECENT_CACHE_TTL_MS).toISOString(),
  };
  cache.set(cacheKey, payload);
  return {
    content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
    structuredContent: payload,
  };
}
