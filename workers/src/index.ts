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

export { ChargerInventory };

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

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const response = await handler.fetch(request, env as any, ctx);
    return response ?? new Response("Not Found", { status: 404 });
  },
};
