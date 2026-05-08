/**
 * Worker entry — mounts the MCP HTTP transport and the cron-driven sync.
 *
 * Streamable HTTP at ``/mcp``. ``ChargerInventory.serve`` returns the
 * fetch-handler that routes MCP requests into per-session DurableObject
 * instances. Cron triggers (every 5 minutes — see wrangler.toml) fire
 * `scheduled()` which calls `runSyncTick` to refresh the global
 * ``InventoryStore``.
 *
 * For local dev:
 *   npm run dev
 *   curl -X POST -H "x-dev-seed-token: dev" http://localhost:8787/internal/sync
 *   curl http://localhost:8787/internal/sync-status
 */

import { ChargerInventory, type Env } from "./agent.js";
import { InventoryStore } from "./inventory_store.js";
import { getSyncStatus, runSyncTick } from "./sync.js";
import type { ChargerInfo } from "./types.js";

export { ChargerInventory, InventoryStore };

const STORE_NAME = "global";
const DEV_SEED_HEADER = "x-dev-seed-token";

const handler = ChargerInventory.serve("/mcp", {
  binding: "INVENTORY",
  corsOptions: {
    origin: "https://claude.ai,https://claude.com,http://localhost:6274",
    methods: "GET,POST,OPTIONS",
    headers: "*",
  },
});

/**
 * Gate `/internal/*` routes behind a shared admin token. Returns a Response
 * to send back when the request is denied, or `null` when it should proceed.
 *
 * - If `DEV_SEED_TOKEN` is unset (production deploy without `wrangler secret
 *   put DEV_SEED_TOKEN`), the entire admin surface returns 503. This makes
 *   the safe default for an undocumented deploy "no admin access" rather
 *   than "everyone with the string 'dev' has admin access".
 * - If set, the request must present a matching header. Mismatches → 403.
 */
function checkDevToken(request: Request, env: Env): Response | null {
  const expected = (env as Env & { DEV_SEED_TOKEN?: string }).DEV_SEED_TOKEN;
  if (!expected) {
    return new Response(
      JSON.stringify({
        error: "internal endpoints not configured",
        hint: "set DEV_SEED_TOKEN via `wrangler secret put DEV_SEED_TOKEN` " +
          "(or .dev.vars locally) to enable /internal/* routes",
      }),
      { status: 503, headers: { "content-type": "application/json" } },
    );
  }
  if (request.headers.get(DEV_SEED_HEADER) !== expected) {
    return new Response("forbidden", { status: 403 });
  }
  return null;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    // Liveness probe (not part of MCP).
    if (url.pathname === "/health") {
      return new Response(
        JSON.stringify({ ok: true, version: "0.1.0", platform: "cloudflare-workers" }),
        { headers: { "content-type": "application/json" } },
      );
    }

    // Dev-only test seed (Stage 2 verification helper).
    if (url.pathname === "/internal/seed" && request.method === "POST") {
      const blocked = checkDevToken(request, env);
      if (blocked) return blocked;
      const rows = (await request.json()) as ChargerInfo[];
      const id = env.STORE.idFromName(STORE_NAME);
      const stub = env.STORE.get(id);
      const n = await stub.seedForTesting(rows);
      return new Response(JSON.stringify({ seeded: n }), {
        headers: { "content-type": "application/json" },
      });
    }

    // Manual sync trigger — useful for local dev and one-off post-deploy
    // refreshes. Same token gate as /internal/seed.
    if (url.pathname === "/internal/sync" && request.method === "POST") {
      const blocked = checkDevToken(request, env);
      if (blocked) return blocked;
      const body = await request
        .json()
        .catch(() => ({}) as Record<string, unknown>);
      const opts = {
        pageSize: typeof (body as { pageSize?: unknown }).pageSize === "number"
          ? (body as { pageSize: number }).pageSize
          : undefined,
        pagesPerTick: typeof (body as { pagesPerTick?: unknown }).pagesPerTick === "number"
          ? (body as { pagesPerTick: number }).pagesPerTick
          : undefined,
      };
      const result = await runSyncTick(env, opts);
      return new Response(JSON.stringify(result, null, 2), {
        headers: { "content-type": "application/json" },
      });
    }

    if (url.pathname === "/internal/sync-status" && request.method === "GET") {
      const blocked = checkDevToken(request, env);
      if (blocked) return blocked;
      const status = await getSyncStatus(env);
      return new Response(JSON.stringify(status, null, 2), {
        headers: { "content-type": "application/json" },
      });
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const response = await handler.fetch(request, env as any, ctx);
    return response ?? new Response("Not Found", { status: 404 });
  },

  /**
   * Cron-driven sync. The trigger is configured in wrangler.toml. We use
   * `ctx.waitUntil` so the scheduled invocation reports completion as soon
   * as state has been kicked off; the actual fetch+upsert runs to its
   * natural conclusion in the background.
   */
  async scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(
      (async () => {
        try {
          const result = await runSyncTick(env);
          console.log(
            "[sync.tick]",
            `start=${result.startedAtPage}`,
            `pages=${result.processedPages}`,
            `rows=${result.processedRows}`,
            `lcp=${result.lastCompletedPage}/${result.totalPages}`,
            result.done ? "done" : "in-progress",
            result.errored ? `error=${result.errored}` : "",
          );
        } catch (e) {
          // EvChargerClient.redact already strips the key from its own errors;
          // unexpected throws from elsewhere are logged as-is.
          console.error("[sync.tick.error]", e instanceof Error ? e.message : String(e));
        }
      })(),
    );
  },
};
