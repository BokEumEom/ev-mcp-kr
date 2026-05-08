/**
 * Sync state machine — paginates `data.go.kr getChargerInfo` and upserts
 * rows into `InventoryStore`. Driven by the cron-triggered `scheduled`
 * handler in `index.ts` and the manual `/internal/sync` endpoint.
 *
 * Design
 * ------
 * Each tick processes a small batch of pages and persists progress in the
 * `sync_state` table. If a tick is killed mid-flight (CPU budget, network
 * flake), the next tick resumes from the persisted ``last_completed_page``.
 *
 * State keys (TEXT in `sync_state`):
 *   - ``last_completed_page``  — highest page successfully upserted
 *   - ``total_pages``          — derived from ``header.totalCount`` on
 *                                the first tick of a fresh cycle
 *   - ``last_synced_at``       — ISO timestamp of the last full-cycle finish
 *   - ``cycle_started_at``     — ISO timestamp when ``last_completed_page``
 *                                last transitioned from 0 to 1
 *
 * Cycle: cron fires → run a tick → advance state. When a tick lands on the
 * final page (rows returned < pageSize OR pageNo >= total_pages):
 *   - write ``last_synced_at``
 *   - reset ``last_completed_page`` and ``total_pages`` to 0
 * Subsequent ticks begin a fresh cycle.
 */

import { EvChargerClient } from "./client.js";
import type { InventoryStore } from "./inventory_store.js";
import type { ChargerInfo } from "./types.js";

export const SYNC_STORE_NAME = "global";
export const SYNC_DEFAULT_PAGE_SIZE = 2000;
export const SYNC_DEFAULT_PAGES_PER_TICK = 1;

export interface SyncEnv {
  SERVICE_KEY: string;
  STORE: DurableObjectNamespace<InventoryStore>;
}

export interface SyncTickOptions {
  /** data.go.kr page size. Stays at 2000 by default (Phase 6: 9999 → 504). */
  pageSize?: number;
  /** Maximum pages to process in one tick (CPU/wall budget guard). */
  pagesPerTick?: number;
}

export interface SyncTickResult {
  startedAtPage: number;
  processedPages: number;
  processedRows: number;
  lastCompletedPage: number;
  totalPages: number;
  /** The pageSize actually used for this tick (may differ from caller's). */
  pageSizeUsed: number;
  /** True when the caller's pageSize was overridden by the locked cycle pageSize. */
  pageSizeOverridden: boolean;
  done: boolean;
  errored?: string;
}

/**
 * Reusable handle for the global InventoryStore stub. Importers normally
 * grab one of these once per scheduled invocation rather than per page.
 */
export interface InventoryWriter {
  upsertMany(rows: readonly ChargerInfo[]): Promise<number>;
  setSyncState(key: string, value: string): Promise<void>;
  getSyncState(key: string): Promise<string | null>;
  totalCount(): Promise<number>;
}

export function inventoryWriter(env: SyncEnv): InventoryWriter {
  const id = env.STORE.idFromName(SYNC_STORE_NAME);
  return env.STORE.get(id) as unknown as InventoryWriter;
}

function parseIntOrZero(v: string | null): number {
  if (v == null) return 0;
  const n = Number(v);
  return Number.isFinite(n) ? Math.max(0, Math.trunc(n)) : 0;
}

/**
 * Run one tick of the sync. Returns a structured summary so the caller
 * (scheduled handler / manual endpoint) can log progress.
 *
 * pageSize lock
 * -------------
 * `pageSize` is locked for the duration of a cycle. The first tick of a
 * fresh cycle records its `pageSize` in `sync_state.page_size`; subsequent
 * ticks read that value and ignore the caller's `opts.pageSize` if they
 * differ (the result reports `pageSizeOverridden: true` in that case).
 *
 * Why: data.go.kr uses page-based pagination (`pageNo` × `numOfRows`).
 * Mixing different `numOfRows` mid-cycle decouples the persisted
 * `last_completed_page` from `total_pages` and from the actual rows seen,
 * which can either skip rows (pageSize larger than the locked one) or
 * end the cycle early (smaller). The lock is released when the cycle
 * completes, so the next cycle is free to choose a different size.
 */
export async function runSyncTick(
  env: SyncEnv,
  opts: SyncTickOptions = {},
): Promise<SyncTickResult> {
  const requestedPageSize = opts.pageSize ?? SYNC_DEFAULT_PAGE_SIZE;
  const pagesPerTick = opts.pagesPerTick ?? SYNC_DEFAULT_PAGES_PER_TICK;

  const store = inventoryWriter(env);
  const client = new EvChargerClient({ serviceKey: env.SERVICE_KEY });

  let lastCompleted = parseIntOrZero(await store.getSyncState("last_completed_page"));
  let totalPages = parseIntOrZero(await store.getSyncState("total_pages"));
  const lockedPageSize = parseIntOrZero(await store.getSyncState("page_size"));

  // Reconcile caller's pageSize against the cycle's locked value. A non-zero
  // lockedPageSize means we're mid-cycle and must keep using it.
  let pageSize = requestedPageSize;
  let pageSizeOverridden = false;
  if (lockedPageSize > 0 && lockedPageSize !== requestedPageSize) {
    console.log(
      "[sync.tick] pageSize override",
      `requested=${requestedPageSize}`,
      `locked=${lockedPageSize}`,
      `(cycle in progress, last_completed_page=${lastCompleted})`,
    );
    pageSize = lockedPageSize;
    pageSizeOverridden = true;
  }

  const startedAtPage = lastCompleted + 1;
  const result: SyncTickResult = {
    startedAtPage,
    processedPages: 0,
    processedRows: 0,
    lastCompletedPage: lastCompleted,
    totalPages,
    pageSizeUsed: pageSize,
    pageSizeOverridden,
    done: false,
  };

  for (let i = 0; i < pagesPerTick; i++) {
    const pageNo = lastCompleted + 1;
    let header;
    let items: ChargerInfo[];
    try {
      const resp = await client.getChargerInfo({ pageNo, numOfRows: pageSize });
      header = resp.header;
      items = resp.items;
    } catch (e) {
      // Surface the redacted message without poisoning state — next tick retries.
      result.errored = client.redact(e instanceof Error ? e.message : String(e));
      break;
    }

    // First tick of a fresh cycle: lock pageSize, derive total_pages, and
    // stamp cycle start.
    if (lockedPageSize === 0 && i === 0 && lastCompleted === 0) {
      await store.setSyncState("page_size", String(pageSize));
    }
    if (totalPages === 0) {
      const total = header.total_count ?? 0;
      if (total > 0) {
        totalPages = Math.ceil(total / pageSize);
        await store.setSyncState("total_pages", String(totalPages));
      }
      if (pageNo === 1) {
        await store.setSyncState("cycle_started_at", new Date().toISOString());
      }
      result.totalPages = totalPages;
    }

    if (items.length > 0) {
      await store.upsertMany(items);
      result.processedRows += items.length;
    }
    result.processedPages += 1;
    lastCompleted = pageNo;
    await store.setSyncState("last_completed_page", String(lastCompleted));
    result.lastCompletedPage = lastCompleted;

    // Cycle-complete conditions: short page (real EOF signal from upstream)
    // or hit the computed end (predicted EOF — guards against bugs).
    const reachedEnd = totalPages > 0 && lastCompleted >= totalPages;
    if (items.length < pageSize || reachedEnd) {
      await store.setSyncState("last_synced_at", new Date().toISOString());
      // Release the lock so the next cycle can choose a different pageSize.
      await store.setSyncState("last_completed_page", "0");
      await store.setSyncState("total_pages", "0");
      await store.setSyncState("page_size", "0");
      result.done = true;
      result.lastCompletedPage = 0;
      break;
    }
  }

  return result;
}

/**
 * Reset cycle state without touching the inventory rows. Useful when the
 * persisted state has been desynchronized from reality (e.g., stored
 * `page_size` mismatched the active cycle in older deploys). The next tick
 * starts a fresh cycle from page 1; existing rows are upserted in place
 * with new `upserted_at` timestamps as the new pages overwrite them.
 */
export async function resetSyncCycle(env: SyncEnv): Promise<void> {
  const store = inventoryWriter(env);
  await store.setSyncState("last_completed_page", "0");
  await store.setSyncState("total_pages", "0");
  await store.setSyncState("page_size", "0");
  await store.setSyncState("cycle_started_at", "");
}

/**
 * Read-only snapshot of sync progress for diagnostics endpoints.
 */
export interface SyncStatus {
  last_completed_page: number;
  total_pages: number;
  /** pageSize locked for the current cycle; 0 between cycles. */
  page_size: number;
  cycle_started_at: string | null;
  last_synced_at: string | null;
  total_rows_in_store: number;
}

export async function getSyncStatus(env: SyncEnv): Promise<SyncStatus> {
  const store = inventoryWriter(env);
  const [lcp, tp, ps, csa, lsa, total] = await Promise.all([
    store.getSyncState("last_completed_page"),
    store.getSyncState("total_pages"),
    store.getSyncState("page_size"),
    store.getSyncState("cycle_started_at"),
    store.getSyncState("last_synced_at"),
    store.totalCount(),
  ]);
  return {
    last_completed_page: parseIntOrZero(lcp),
    total_pages: parseIntOrZero(tp),
    page_size: parseIntOrZero(ps),
    cycle_started_at: csa == null || csa === "" ? null : csa,
    last_synced_at: lsa == null || lsa === "" ? null : lsa,
    total_rows_in_store: total,
  };
}
