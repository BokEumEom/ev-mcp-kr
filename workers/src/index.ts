/**
 * Worker entry — mounts the MCP HTTP transport.
 *
 * Streamable HTTP at ``/mcp``. ``ChargerInventory.mount`` returns the
 * fetch-handler that routes MCP requests into the Durable Object instance.
 *
 * For local dev: ``npm run dev`` then point MCP Inspector at
 * ``http://localhost:8787/mcp``.
 */

import { ChargerInventory, type Env } from "./agent.js";
import { InventoryStore } from "./inventory_store.js";
import type { ChargerInfo } from "./types.js";

export { ChargerInventory, InventoryStore };

const STORE_NAME = "global";
// Header gate for the dev-only seed endpoint. Production deploys MUST set a
// real value via `wrangler secret put DEV_SEED_TOKEN` (or remove the route).
const DEV_SEED_HEADER = "x-dev-seed-token";

const handler = ChargerInventory.serve("/mcp", {
  binding: "INVENTORY",
  corsOptions: {
    origin: "https://claude.ai,https://claude.com,http://localhost:6274",
    methods: "GET,POST,OPTIONS",
    headers: "*",
  },
});

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

    // Dev seed endpoint — POST /internal/seed with a JSON body of
    // ChargerInfo[]. Gated by a token header so it's safe to keep around
    // in dev; production should set DEV_SEED_TOKEN to a real secret or
    // strip this branch entirely.
    if (url.pathname === "/internal/seed" && request.method === "POST") {
      const expected = (env as Env & { DEV_SEED_TOKEN?: string }).DEV_SEED_TOKEN ?? "dev";
      if (request.headers.get(DEV_SEED_HEADER) !== expected) {
        return new Response("forbidden", { status: 403 });
      }
      const rows = (await request.json()) as ChargerInfo[];
      const id = env.STORE.idFromName(STORE_NAME);
      const stub = env.STORE.get(id);
      const n = await stub.seedForTesting(rows);
      return new Response(JSON.stringify({ seeded: n }), {
        headers: { "content-type": "application/json" },
      });
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const response = await handler.fetch(request, env as any, ctx);
    return response ?? new Response("Not Found", { status: 404 });
  },
};
