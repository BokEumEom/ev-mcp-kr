import { defineConfig } from "vitest/config";

/**
 * vitest config for the Workers TypeScript port.
 *
 * Plain node environment for now — covers all pure logic (codes resolvers,
 * type helpers, EvChargerClient with mock fetchImpl, runSyncTick with
 * stubbed InventoryWriter, tool functions with InventoryReader stub).
 *
 * Durable Object integration tests via @cloudflare/vitest-pool-workers are
 * deferred — they require miniflare config + cloudflare:workers runtime
 * imports that don't run in plain Node. The DO surface (`InventoryStore`)
 * is currently exercised only via wrangler dev smoke tests; adding the
 * pool-workers config is a follow-up.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    exclude: ["node_modules", "dist"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      // Files that require a Workers runtime (`cloudflare:workers` import,
      // DurableObjectState, agents-mcp's McpAgent base) are excluded from
      // the coverage gate until the pool-workers config lands.
      exclude: [
        "src/agent.ts",
        "src/inventory_store.ts",
        "src/index.ts",
        "**/*.test.ts",
        "**/*.config.ts",
      ],
      thresholds: {
        lines: 70,
        functions: 70,
        branches: 70,
        statements: 70,
      },
    },
  },
});
