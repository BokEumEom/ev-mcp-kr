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

import { EvChargerClient } from "./client.js";
import { CODE_CATEGORIES, codeTables } from "./codes/index.js";
import type { InventoryStore } from "./inventory_store.js";
import {
  findChargersNearby,
  getStationDetails,
  type InventoryReader,
  listChargersByOperator,
  searchChargersByRegion,
} from "./tools/inventory.js";
import {
  getChargerStatus,
  RecentChangesCache,
  recentStatusChanges,
} from "./tools/status.js";

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

  // Per-DO instance state — not durable, recreated on every wake. Acceptable
  // because the cache is a soft optimization on a 60s window.
  private liveClient: EvChargerClient | null = null;
  private readonly recentCache = new RecentChangesCache();

  override async init(): Promise<void> {
    this.registerLookupCodes();
    this.registerListChargersByOperator();
    this.registerFindChargersNearby();
    this.registerSearchChargersByRegion();
    this.registerGetStationDetails();
    this.registerGetChargerStatus();
    this.registerRecentStatusChanges();
  }

  /** Get an `InventoryReader` view of the global InventoryStore DO. */
  private inventory(): InventoryReader {
    const id = this.env.STORE.idFromName(STORE_NAME);
    const stub = this.env.STORE.get(id);
    return stub as unknown as InventoryReader;
  }

  /** Lazy live-fetch client — instantiated on first use. */
  private client(): EvChargerClient {
    if (this.liveClient == null) {
      const key = this.env.SERVICE_KEY;
      if (!key) {
        throw new Error(
          "SERVICE_KEY 가 설정되지 않았습니다. wrangler secret put SERVICE_KEY 또는 .dev.vars 파일에 추가하세요.",
        );
      }
      this.liveClient = new EvChargerClient({ serviceKey: key });
    }
    return this.liveClient;
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

  private registerSearchChargersByRegion(): void {
    this.server.tool(
      "search_chargers_by_region",
      "시도(필수) + 시군구(선택) 로 충전기 검색. 시도/시군구는 한국어 이름 또는 " +
        "코드 모두 입력 가능. 동명의 시군구가 여러 시도에 있는 경우 district 코드를 " +
        "직접 입력해야 합니다 (lookup_codes(sigungu) 참고).",
      {
        region: z.string().min(1).describe("시도명 또는 zcode (예: 서울특별시 / 11)"),
        district: z
          .string()
          .optional()
          .describe("시군구명 또는 zscode (예: 강남구 / 11680)"),
        limit: z.number().int().min(1).max(500).default(50),
      },
      async (args) => searchChargersByRegion(this.inventory(), args),
    );
  }

  private registerGetStationDetails(): void {
    this.server.tool(
      "get_station_details",
      "충전소 ID(stat_id) 로 충전소 상세 + 소속 충전기(chger) 전체 조회. " +
        "stat_id 는 find_chargers_nearby / search_chargers_by_region / " +
        "list_chargers_by_operator 응답에서 확인 가능.",
      {
        stat_id: z.string().min(1).describe("충전소 ID (예: ME000001)"),
      },
      async (args) => getStationDetails(this.inventory(), args),
    );
  }

  private registerGetChargerStatus(): void {
    this.server.tool(
      "get_charger_status",
      "특정 충전기의 실시간 상태(stat). data.go.kr 의 getChargerStatus 를 직접 호출해 " +
        "최신 값을 가져오므로 일 1회 sync 보다 신선한 값. stat_id+chger_id 둘 다 필요.",
      {
        stat_id: z.string().min(1).describe("충전소 ID"),
        chger_id: z.string().min(1).describe("충전기 ID (예: 01)"),
      },
      async (args) => getChargerStatus(this.client(), args),
    );
  }

  private registerRecentStatusChanges(): void {
    this.server.tool(
      "recent_status_changes",
      "최근 N분(period, 1~10) 안에 상태가 바뀐 충전기를 stat_upd_dt 내림차순으로 조회. " +
        "응답은 60초 메모리 캐시. zcode 로 시도 필터 가능.",
      {
        period: z
          .number()
          .int()
          .min(1)
          .max(10)
          .default(10)
          .describe("최근 몇 분 (1~10, 기본 10)"),
        limit: z.number().int().min(1).max(200).default(20),
        zcode: z.string().optional().describe("시도 코드 (예: 11=서울)"),
      },
      async (args) => recentStatusChanges(this.client(), this.recentCache, args),
    );
  }
}
