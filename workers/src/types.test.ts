import { describe, expect, it } from "vitest";

import {
  CHARGER_STATUS_CODES,
  type ChargerInfo,
  type ChargerRow,
  coerceStat,
  emptyToNone,
  parseYyyymmddhhmmss,
  rowToChargerInfo,
  ynDefaultN,
} from "./types.js";

describe("coerceStat", () => {
  it("preserves all known status codes", () => {
    for (const code of CHARGER_STATUS_CODES) {
      expect(coerceStat(code)).toBe(code);
    }
  });

  it("demotes undocumented codes to '0' (UNKNOWN)", () => {
    expect(coerceStat("7")).toBe("0");
    expect(coerceStat("8")).toBe("0");
    expect(coerceStat("XYZ")).toBe("0");
  });

  it("demotes non-strings to '0'", () => {
    expect(coerceStat(null)).toBe("0");
    expect(coerceStat(undefined)).toBe("0");
    expect(coerceStat(2)).toBe("0");
  });
});

describe("parseYyyymmddhhmmss", () => {
  it("parses a valid 14-digit string to ISO", () => {
    const iso = parseYyyymmddhhmmss("20260507143015");
    expect(iso).not.toBeNull();
    expect(iso).toMatch(/^2026-05-07T14:30:15/);
  });

  it("rejects sentinels and out-of-range years", () => {
    expect(parseYyyymmddhhmmss("00000000000000")).toBeNull();
    expect(parseYyyymmddhhmmss("19990101120000")).toBeNull(); // year < 2000
  });

  it("rejects malformed input", () => {
    expect(parseYyyymmddhhmmss("")).toBeNull();
    expect(parseYyyymmddhhmmss("not a date")).toBeNull();
    expect(parseYyyymmddhhmmss("2026050714301")).toBeNull(); // 13 digits
    expect(parseYyyymmddhhmmss(null)).toBeNull();
    expect(parseYyyymmddhhmmss(20260507143015)).toBeNull(); // numeric, not string
  });
});

describe("emptyToNone", () => {
  it("returns null for empty/whitespace strings", () => {
    expect(emptyToNone("")).toBeNull();
    expect(emptyToNone("   ")).toBeNull();
  });

  it("returns the original string when non-empty", () => {
    expect(emptyToNone("hello")).toBe("hello");
  });
});

describe("ynDefaultN", () => {
  it("returns 'N' for empty/whitespace/non-string input", () => {
    expect(ynDefaultN("")).toBe("N");
    expect(ynDefaultN("   ")).toBe("N");
    expect(ynDefaultN(null)).toBe("N");
    expect(ynDefaultN(undefined)).toBe("N");
  });

  it("preserves non-empty strings", () => {
    expect(ynDefaultN("Y")).toBe("Y");
    expect(ynDefaultN("N")).toBe("N");
  });
});

describe("rowToChargerInfo", () => {
  const row: ChargerRow = {
    stat_id: "ME000001",
    chger_id: "01",
    stat_nm: "테스트 충전소",
    chger_type: "04",
    addr: "서울특별시 강남구",
    addr_detail: "",
    location: "1층",
    lat: 37.5,
    lng: 127.0,
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
    upserted_at: "2026-05-08T00:00:00Z",
  };

  it("maps a SQLite row to a ChargerInfo", () => {
    const info: ChargerInfo = rowToChargerInfo(row);
    expect(info.stat_id).toBe("ME000001");
    expect(info.lat).toBe(37.5);
    expect(info.stat).toBe("2");
    expect(info.parking_free).toBe("Y");
  });

  it("normalizes empty strings to null on optional fields", () => {
    const info = rowToChargerInfo(row);
    expect(info.addr_detail).toBeNull();
  });

  it("defaults limit_yn / del_yn to 'N' when stored as empty", () => {
    const empty: ChargerRow = { ...row, limit_yn: "", del_yn: "" };
    const info = rowToChargerInfo(empty);
    expect(info.limit_yn).toBe("N");
    expect(info.del_yn).toBe("N");
  });

  it("coerces unknown stat to '0'", () => {
    const bad: ChargerRow = { ...row, stat: "7" };
    expect(rowToChargerInfo(bad).stat).toBe("0");
  });
});
