/**
 * ``ChargerInventory`` — MCP server (per-session McpAgent).
 *
 * The agents framework routes every MCP session to its own DO instance, so
 * this class is *not* where charger data lives — that's `InventoryStore`,
 * a single global plain DO. Tool callbacks here grab a stub for that store
 * via standard DO RPC and read through it. Stage 4's sync worker writes
 * to the same store.
 *
 * Stage 1: lookup_codes (static).
 * Stage 2: list_chargers_by_operator + find_chargers_nearby (RPC reads).
 * Stage 3+: get_charger_status, recent_status_changes, etc.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { McpAgent } from "agents/mcp";
import { z } from "zod";

import { CODE_CATEGORIES, codeTables } from "./codes/index.js";
import type { InventoryStore } from "./inventory_store.js";
import {
  findChargersNearby,
  type InventoryReader,
  listChargersByOperator,
} from "./tools/inventory.js";

export interface Env {
  SERVICE_KEY: string;
  VWORLD_KEY?: string;
  LOG_LEVEL?: string;
  INVENTORY: DurableObjectNamespace<ChargerInventory>;
  STORE: DurableObjectNamespace<InventoryStore>;
}

const STORE_NAME = "global";

export class ChargerInventory extends McpAgent<Env> {
  override server = new McpServer({
    name: "ev-mcp",
    version: "0.1.0",
  });

  override async init(): Promise<void> {
    this.registerLookupCodes();
    this.registerListChargersByOperator();
    this.registerFindChargersNearby();
  }

  /** Get an `InventoryReader` view of the global InventoryStore DO. */
  private inventory(): InventoryReader {
    const id = this.env.STORE.idFromName(STORE_NAME);
    const stub = this.env.STORE.get(id);
    return stub as unknown as InventoryReader;
  }

  // ====================================================================
  // Tool registrations
  // ====================================================================

  private registerLookupCodes(): void {
    this.server.tool(
      "lookup_codes",
      "공통 코드 테이블 (시도/시군구/충전기타입/상태/운영기관/구분) 조회. " +
        "category 한 개를 받아 코드→한국어 라벨 dict 반환.",
      {
        category: z.enum(CODE_CATEGORIES as unknown as [string, ...string[]]),
      },
      async ({ category }) => {
        const table = codeTables[category as keyof typeof codeTables];
        return {
          content: [{ type: "text", text: JSON.stringify(table, null, 2) }],
          structuredContent: table as unknown as Record<string, unknown>,
        };
      },
    );
  }

  private registerListChargersByOperator(): void {
    this.server.tool(
      "list_chargers_by_operator",
      '운영기관(busiId) 별 충전기 목록. 한국어 운영기관명("환경부","에버온" 등) ' +
        '또는 코드("ME") 입력. region 으로 시도(zcode) 추가 필터 가능.',
      {
        operator: z.string().min(1).describe("운영기관명 또는 busiId 코드"),
        region: z.string().optional().describe("시도명 또는 zcode (예: 서울특별시 / 11)"),
        limit: z.number().int().min(1).max(500).default(50),
      },
      async (args) => listChargersByOperator(this.inventory(), args),
    );
  }

  private registerFindChargersNearby(): void {
    this.server.tool(
      "find_chargers_nearby",
      "좌표(lat+lng) 기준 반경 내 충전기 검색. 결과는 거리순 정렬, " +
        "available_only=true 시 stat='2'(사용가능) 만 반환.",
      {
        lat: z.number().describe("위도 (예: 37.4979)"),
        lng: z.number().describe("경도 (예: 127.0276)"),
        radius_km: z.number().min(0.1).max(20).default(2.0),
        available_only: z.boolean().default(false),
        limit: z.number().int().min(1).max(100).default(20),
      },
      async (args) => findChargersNearby(this.inventory(), args),
    );
  }
}
