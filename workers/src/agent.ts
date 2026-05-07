/**
 * ``ChargerInventory`` — combined MCP server + Durable Object.
 *
 * Cloudflare's `agents` package wraps `@modelcontextprotocol/sdk`'s `McpServer`
 * inside a `DurableObject`, giving us a single class that:
 *   - exposes the streamable HTTP `/mcp` endpoint via `mount()`
 *   - holds per-instance SQLite (this.sql) — same role as Phase 6 ChargerStore
 *   - registers all tools through `this.server.tool(...)`
 *
 * Stage 1 ships only `lookup_codes` (static data, no SQLite). Stage 2~3 will
 * add the inventory-backed tools.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { McpAgent } from "agents/mcp";
import { z } from "zod";

import { CODE_CATEGORIES, codeTables } from "./codes/index.js";

export interface Env {
  SERVICE_KEY: string;
  VWORLD_KEY?: string;
  LOG_LEVEL?: string;
  INVENTORY: DurableObjectNamespace<ChargerInventory>;
}

const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS chargers (
    stat_id      TEXT NOT NULL,
    chger_id     TEXT NOT NULL,
    stat_nm      TEXT NOT NULL,
    chger_type   TEXT NOT NULL,
    addr         TEXT NOT NULL,
    addr_detail  TEXT,
    location     TEXT,
    lat          REAL NOT NULL,
    lng          REAL NOT NULL,
    use_time     TEXT NOT NULL,
    busi_id      TEXT NOT NULL,
    bnm          TEXT NOT NULL,
    busi_nm      TEXT NOT NULL,
    busi_call    TEXT,
    stat         TEXT NOT NULL,
    stat_upd_dt  TEXT,
    last_tsdt    TEXT,
    last_tedt    TEXT,
    now_tsdt     TEXT,
    power_type   TEXT,
    output       TEXT,
    method       TEXT,
    zcode        TEXT NOT NULL,
    zscode       TEXT,
    kind         TEXT,
    kind_detail  TEXT,
    parking_free TEXT,
    note         TEXT,
    limit_yn     TEXT NOT NULL DEFAULT 'N',
    limit_detail TEXT,
    del_yn       TEXT NOT NULL DEFAULT 'N',
    del_detail   TEXT,
    traffic_yn   TEXT,
    year         TEXT,
    floor_num    TEXT,
    floor_type   TEXT,
    upserted_at  TEXT NOT NULL,
    PRIMARY KEY (stat_id, chger_id)
);

CREATE INDEX IF NOT EXISTS idx_busi_id ON chargers(busi_id);
CREATE INDEX IF NOT EXISTS idx_zcode   ON chargers(zcode);
CREATE INDEX IF NOT EXISTS idx_zscode  ON chargers(zscode);
CREATE INDEX IF NOT EXISTS idx_lat_lng ON chargers(lat, lng);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
`;

export class ChargerInventory extends McpAgent<Env> {
  override server = new McpServer({
    name: "ev-mcp",
    version: "0.1.0",
  });

  override async init(): Promise<void> {
    // Stage 1 ships only `lookup_codes` (static data). Stage 2 will introduce
    // SQLite-backed tools and run SCHEMA_SQL via ctx.storage.sql.exec at that
    // point. Keeping init() lean for now to avoid agents-mcp/SQLite friction.

    // ---- Stage 1: lookup_codes -------------------------------------------
    this.server.tool(
      "lookup_codes",
      "공통 코드 테이블 (시도/시군구/충전기타입/상태/운영기관/구분) 조회. " +
        "category 한 개를 받아 코드→한국어 라벨 dict 반환.",
      {
        category: z.enum(
          CODE_CATEGORIES as unknown as [string, ...string[]],
        ),
      },
      async ({ category }) => {
        const table = codeTables[category as keyof typeof codeTables];
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(table, null, 2),
            },
          ],
          structuredContent: table as unknown as Record<string, unknown>,
        };
      },
    );

    // Stage 2~3 tools (find_chargers_nearby, list_chargers_by_operator, etc.)
    // are registered here in subsequent stages.
  }
}
