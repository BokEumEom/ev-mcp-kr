import { describe, expect, it, vi } from "vitest";

import type { ChargerInfo } from "../types.js";
import {
  findChargersNearby,
  getStationDetails,
  type InventoryReader,
  listChargersByOperator,
  searchChargersByRegion,
} from "./inventory.js";

function makeCharger(overrides: Partial<ChargerInfo> = {}): ChargerInfo {
  return {
    stat_nm: "테스트 충전소",
    stat_id: "ME000001",
    chger_id: "01",
    chger_type: "04",
    addr: "서울특별시 강남구",
    addr_detail: null,
    location: null,
    lat: 37.4979,
    lng: 127.0276,
    use_time: "24시간",
    busi_id: "ME",
    bnm: "한국환경공단",
    busi_nm: "한국환경공단",
    busi_call: null,
    stat: "2",
    stat_upd_dt: null,
    last_tsdt: null,
    last_tedt: null,
    now_tsdt: null,
    power_type: null,
    output: "50",
    method: "단독",
    zcode: "11",
    zscode: "11680",
    kind: null,
    kind_detail: null,
    parking_free: "Y",
    note: null,
    limit_yn: "N",
    limit_detail: null,
    del_yn: "N",
    del_detail: null,
    traffic_yn: null,
    year: "2024",
    floor_num: null,
    floor_type: null,
    ...overrides,
  };
}

function stubInventory(rows: ChargerInfo[]): InventoryReader {
  return {
    byStatId: vi.fn(async (statId) => rows.filter((r) => r.stat_id === statId)),
    byBusiId: vi.fn(async (busiId, limit = 100) =>
      rows.filter((r) => r.busi_id === busiId).slice(0, limit),
    ),
    byBusiIdAndZcode: vi.fn(async (busiId, zcode, limit = 100) =>
      rows.filter((r) => r.busi_id === busiId && r.zcode === zcode).slice(0, limit),
    ),
    byZcode: vi.fn(async (zcode, limit = 100) =>
      rows.filter((r) => r.zcode === zcode).slice(0, limit),
    ),
    byZscode: vi.fn(async (zscode, limit = 100) =>
      rows.filter((r) => r.zscode === zscode).slice(0, limit),
    ),
    nearLatLng: vi.fn(async (_lat, _lng, _radius, limit = 200) => rows.slice(0, limit)),
  };
}

describe("listChargersByOperator", () => {
  it("resolves operator name to busiId and queries", async () => {
    const inv = stubInventory([
      makeCharger({ stat_id: "A", busi_id: "ME" }),
      makeCharger({ stat_id: "B", busi_id: "EV" }),
    ]);
    const r = await listChargersByOperator(inv, { operator: "환경부" });
    expect(inv.byBusiId).toHaveBeenCalledWith("ME", 50);
    expect((r.structuredContent as { count: number }).count).toBe(1);
  });

  it("uses byBusiIdAndZcode when region is given", async () => {
    const inv = stubInventory([makeCharger({ busi_id: "ME", zcode: "11" })]);
    const r = await listChargersByOperator(inv, {
      operator: "ME",
      region: "서울특별시",
      limit: 10,
    });
    expect(inv.byBusiIdAndZcode).toHaveBeenCalledWith("ME", "11", 10);
    expect((r.structuredContent as { region: string }).region).toBe("서울특별시");
  });

  it("throws on unresolvable operator", async () => {
    const inv = stubInventory([]);
    await expect(
      listChargersByOperator(inv, { operator: "존재하지않는기관" }),
    ).rejects.toThrow(/운영기관/);
  });

  it("throws on unresolvable region", async () => {
    const inv = stubInventory([]);
    await expect(
      listChargersByOperator(inv, { operator: "ME", region: "도쿄" }),
    ).rejects.toThrow(/시도/);
  });
});

describe("findChargersNearby", () => {
  it("filters by haversine distance and sorts ascending", async () => {
    // Three points at distinct distances from (37.4979, 127.0276):
    const close = makeCharger({ stat_id: "CLOSE", lat: 37.4979, lng: 127.0276 });
    const mid = makeCharger({ stat_id: "MID", lat: 37.5009, lng: 127.0364 });
    // Far point > radius_km should be filtered out by the post-haversine check.
    const far = makeCharger({ stat_id: "FAR", lat: 35.0, lng: 129.0 });

    const inv = stubInventory([far, close, mid]); // unordered on purpose

    const r = await findChargersNearby(inv, {
      lat: 37.4979,
      lng: 127.0276,
      radius_km: 5,
      limit: 10,
    });
    const data = r.structuredContent as {
      count: number;
      chargers: Array<{ stat_id: string; distance_km: number }>;
    };
    expect(data.count).toBe(2);
    expect(data.chargers[0]?.stat_id).toBe("CLOSE");
    expect(data.chargers[1]?.stat_id).toBe("MID");
    expect(data.chargers[0]!.distance_km).toBeLessThan(data.chargers[1]!.distance_km);
  });

  it("respects available_only by filtering on stat='2'", async () => {
    const inv = stubInventory([
      makeCharger({ stat_id: "A", stat: "2" }),
      makeCharger({ stat_id: "B", stat: "3" }), // 충전중
      makeCharger({ stat_id: "C", stat: "4" }),
    ]);
    const r = await findChargersNearby(inv, {
      lat: 37.4979,
      lng: 127.0276,
      radius_km: 5,
      available_only: true,
    });
    const data = r.structuredContent as { count: number };
    expect(data.count).toBe(1);
  });
});

describe("getStationDetails", () => {
  it("groups multiple chargers under one station meta", async () => {
    const inv = stubInventory([
      makeCharger({ stat_id: "S1", chger_id: "01", chger_type: "04" }),
      makeCharger({ stat_id: "S1", chger_id: "02", chger_type: "06" }),
    ]);
    const r = await getStationDetails(inv, { stat_id: "S1" });
    const data = r.structuredContent as { found: boolean; charger_count: number };
    expect(data.found).toBe(true);
    expect(data.charger_count).toBe(2);
  });

  it("returns found:false with helpful message on miss", async () => {
    const inv = stubInventory([]);
    const r = await getStationDetails(inv, { stat_id: "MISSING" });
    expect((r.structuredContent as { found: boolean }).found).toBe(false);
    expect(r.content[0]?.text).toContain("MISSING");
  });
});

describe("searchChargersByRegion", () => {
  it("uses byZcode when only region is given", async () => {
    const inv = stubInventory([makeCharger({ zcode: "11" })]);
    const r = await searchChargersByRegion(inv, { region: "서울특별시" });
    expect(inv.byZcode).toHaveBeenCalledWith("11", 50);
    expect((r.structuredContent as { count: number }).count).toBe(1);
  });

  it("uses byZscode when district is provided", async () => {
    const inv = stubInventory([makeCharger({ zcode: "11", zscode: "11680" })]);
    const r = await searchChargersByRegion(inv, {
      region: "서울특별시",
      district: "11680",
    });
    expect(inv.byZscode).toHaveBeenCalledWith("11680", 50);
    expect((r.structuredContent as { count: number }).count).toBe(1);
  });

  it("rejects ambiguous district names", async () => {
    const inv = stubInventory([]);
    // "중구" is ambiguous (multiple sido) → resolveSigungu returns null
    await expect(
      searchChargersByRegion(inv, { region: "서울특별시", district: "중구" }),
    ).rejects.toThrow(/시군구/);
  });
});
