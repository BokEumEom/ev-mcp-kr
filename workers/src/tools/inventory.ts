/**
 * Inventory-backed tool implementations: list_chargers_by_operator and
 * find_chargers_nearby. Both depend only on a structural `InventoryReader`
 * interface (a subset of the ChargerInventory DO surface), so this file can
 * be imported by agent.ts without introducing a module cycle.
 */

import {
  busiIdLabel,
  chargerTypeLabel,
  resolveBusiId,
  resolveSido,
  sidoLabel,
  statLabel,
} from "../codes/index.js";
import type { ChargerInfo } from "../types.js";

const EARTH_RADIUS_KM = 6371.0088;

/**
 * Async because this is a view over an `InventoryStore` Durable Object stub.
 * Cloudflare DO RPC wraps every method return in a Promise on the caller side,
 * even when the underlying method is synchronous.
 */
export interface InventoryReader {
  byBusiId(busiId: string, limit?: number): Promise<ChargerInfo[]>;
  byBusiIdAndZcode(
    busiId: string,
    zcode: string,
    limit?: number,
  ): Promise<ChargerInfo[]>;
  nearLatLng(
    lat: number,
    lng: number,
    radiusKm: number,
    limit?: number,
  ): Promise<ChargerInfo[]>;
}

// Index signature is required by the MCP SDK's tool callback return type.
interface ToolResult {
  content: Array<{ type: "text"; text: string }>;
  structuredContent: Record<string, unknown>;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// list_chargers_by_operator
// ---------------------------------------------------------------------------

export interface OperatorArgs {
  operator: string;
  region?: string | undefined;
  limit?: number | undefined;
}

interface ChargerSummary {
  stat_id: string;
  chger_id: string;
  stat_nm: string;
  chger_type: string;
  chger_type_label: string;
  addr: string;
  stat: string;
  stat_label: string;
  zcode: string;
  zcode_label: string;
  busi_id: string;
  busi_label: string;
  lat: number;
  lng: number;
  output: string | null;
}

function summarize(c: ChargerInfo): ChargerSummary {
  return {
    stat_id: c.stat_id,
    chger_id: c.chger_id,
    stat_nm: c.stat_nm,
    chger_type: c.chger_type,
    chger_type_label: chargerTypeLabel(c.chger_type),
    addr: c.addr,
    stat: c.stat,
    stat_label: statLabel(c.stat),
    zcode: c.zcode,
    zcode_label: sidoLabel(c.zcode),
    busi_id: c.busi_id,
    busi_label: busiIdLabel(c.busi_id),
    lat: c.lat,
    lng: c.lng,
    output: c.output,
  };
}

export async function listChargersByOperator(
  inv: InventoryReader,
  args: OperatorArgs,
): Promise<ToolResult> {
  const limit = args.limit ?? 50;
  const busiId = resolveBusiId(args.operator);
  if (busiId == null) {
    throw new Error(
      `운영기관 '${args.operator}' 을(를) 찾을 수 없습니다. lookup_codes(busi_id) 로 코드 확인 가능.`,
    );
  }

  let zcode: string | null = null;
  if (args.region) {
    zcode = resolveSido(args.region);
    if (zcode == null) {
      throw new Error(
        `시도 '${args.region}' 을(를) 찾을 수 없습니다. lookup_codes(sido) 로 코드 확인 가능.`,
      );
    }
  }

  const rows =
    zcode == null
      ? await inv.byBusiId(busiId, limit)
      : await inv.byBusiIdAndZcode(busiId, zcode, limit);

  const summaries = rows.map(summarize);
  const payload: Record<string, unknown> = {
    operator: busiIdLabel(busiId),
    busi_id: busiId,
    region: zcode == null ? null : sidoLabel(zcode),
    zcode,
    count: summaries.length,
    chargers: summaries,
  };

  return {
    content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
    structuredContent: payload,
  };
}

// ---------------------------------------------------------------------------
// find_chargers_nearby
// ---------------------------------------------------------------------------

export interface NearbyArgs {
  lat: number;
  lng: number;
  radius_km?: number | undefined;
  available_only?: boolean | undefined;
  limit?: number | undefined;
}

interface NearbyHit extends ChargerSummary {
  distance_km: number;
}

function haversineKm(
  lat1: number,
  lng1: number,
  lat2: number,
  lng2: number,
): number {
  const toRad = (d: number): number => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  const c = 2 * Math.asin(Math.min(1, Math.sqrt(a)));
  return EARTH_RADIUS_KM * c;
}

export async function findChargersNearby(
  inv: InventoryReader,
  args: NearbyArgs,
): Promise<ToolResult> {
  const radiusKm = args.radius_km ?? 2.0;
  const limit = args.limit ?? 20;
  const availableOnly = args.available_only ?? false;

  // Pull a generous bbox candidate set, then refine with haversine.
  const candidates = await inv.nearLatLng(args.lat, args.lng, radiusKm, limit * 8);
  const hits: NearbyHit[] = [];
  for (const c of candidates) {
    if (availableOnly && c.stat !== "2") continue;
    const d = haversineKm(args.lat, args.lng, c.lat, c.lng);
    if (d > radiusKm) continue;
    hits.push({ ...summarize(c), distance_km: Number(d.toFixed(3)) });
  }
  hits.sort((a, b) => a.distance_km - b.distance_km);
  const top = hits.slice(0, limit);

  const payload: Record<string, unknown> = {
    origin: { lat: args.lat, lng: args.lng },
    radius_km: radiusKm,
    available_only: availableOnly,
    count: top.length,
    chargers: top,
  };
  return {
    content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
    structuredContent: payload,
  };
}
