import { beforeEach, describe, expect, it, vi } from "vitest";

import { EvChargerClient, EvChargerError } from "./client.js";

/**
 * Build a mock fetch that returns successive responses from a queue.
 * Each call records the URL it was given so tests can assert query params.
 */
function queuedFetch(responses: Array<{ status: number; body: string }>) {
  const calls: string[] = [];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : (input as URL).toString();
    calls.push(url);
    const next = responses.shift();
    if (next == null) throw new Error("queuedFetch exhausted");
    return new Response(next.body, { status: next.status });
  });
  return { fetchImpl: fetchImpl as unknown as typeof fetch, calls };
}

const SERVICE_KEY = "abc123def456=="; // base64-ish placeholder

const flatStatusBody = (rows: object[], totalCount: number = rows.length) =>
  JSON.stringify({
    resultMsg: "NORMAL SERVICE.",
    resultCode: "00",
    pageNo: 1,
    numOfRows: rows.length,
    totalCount,
    items: { item: rows },
  });

const wrappedStatusBody = (rows: object[], totalCount: number = rows.length) =>
  JSON.stringify({
    response: {
      header: {
        resultCode: "00",
        resultMsg: "NORMAL SERVICE.",
        pageNo: 1,
        numOfRows: rows.length,
        totalCount,
      },
      body: { items: { item: rows } },
    },
  });

describe("EvChargerClient.redact", () => {
  const client = new EvChargerClient({
    serviceKey: SERVICE_KEY,
    fetchImpl: vi.fn() as unknown as typeof fetch,
  });

  it("strips the raw key", () => {
    expect(client.redact(`error at /api?serviceKey=${SERVICE_KEY}`)).toBe(
      "error at /api?serviceKey=***",
    );
  });

  it("strips the URI-encoded variant", () => {
    const enc = encodeURIComponent(SERVICE_KEY);
    expect(client.redact(`url=${enc}`)).toBe("url=***");
  });

  it("is a no-op when the key is empty", () => {
    const c2 = new EvChargerClient({
      serviceKey: "",
      fetchImpl: vi.fn() as unknown as typeof fetch,
    });
    expect(c2.redact("hello")).toBe("hello");
  });
});

describe("EvChargerClient.getChargerStatus", () => {
  const sampleRow = {
    busiId: "ME",
    statId: "ME000001",
    chgerId: "01",
    stat: "2",
    statUpdDt: "20260507143015",
    lastTsdt: "",
    lastTedt: "",
    nowTsdt: "",
  };

  it("parses the flat envelope shape", async () => {
    const { fetchImpl, calls } = queuedFetch([
      { status: 200, body: flatStatusBody([sampleRow]) },
    ]);
    const client = new EvChargerClient({ serviceKey: SERVICE_KEY, fetchImpl });
    const { header, items } = await client.getChargerStatus({ statId: "ME000001" });
    expect(header.result_code).toBe("00");
    expect(items).toHaveLength(1);
    expect(items[0]?.stat_id).toBe("ME000001");
    expect(items[0]?.stat_upd_dt).toMatch(/^2026-05-07T14:30:15/);
    expect(calls[0]).toContain("statId=ME000001");
    expect(calls[0]).toContain("dataType=JSON");
  });

  it("parses the response-wrapped envelope shape", async () => {
    const { fetchImpl } = queuedFetch([
      { status: 200, body: wrappedStatusBody([sampleRow]) },
    ]);
    const client = new EvChargerClient({ serviceKey: SERVICE_KEY, fetchImpl });
    const { items } = await client.getChargerStatus({});
    expect(items).toHaveLength(1);
    expect(items[0]?.busi_id).toBe("ME");
  });

  it("handles the single-item envelope (item is dict, not list)", async () => {
    const { fetchImpl } = queuedFetch([
      {
        status: 200,
        body: JSON.stringify({
          resultCode: "00",
          resultMsg: "NORMAL SERVICE.",
          totalCount: 1,
          items: { item: sampleRow },
        }),
      },
    ]);
    const client = new EvChargerClient({ serviceKey: SERVICE_KEY, fetchImpl });
    const { items } = await client.getChargerStatus({});
    expect(items).toHaveLength(1);
    expect(items[0]?.stat_id).toBe("ME000001");
  });

  it("retries on 503 then succeeds", async () => {
    const { fetchImpl, calls } = queuedFetch([
      { status: 503, body: "" },
      { status: 200, body: flatStatusBody([sampleRow]) },
    ]);
    const client = new EvChargerClient({
      serviceKey: SERVICE_KEY,
      fetchImpl,
      maxRetries: 3,
    });
    const { items } = await client.getChargerStatus({});
    expect(items).toHaveLength(1);
    expect(calls).toHaveLength(2);
  });

  it("throws EvChargerError when resultCode != '00'", async () => {
    const { fetchImpl } = queuedFetch([
      {
        status: 200,
        body: JSON.stringify({
          resultCode: "30",
          resultMsg: "SERVICE KEY IS NOT REGISTERED",
          items: { item: [] },
        }),
      },
    ]);
    const client = new EvChargerClient({ serviceKey: SERVICE_KEY, fetchImpl });
    await expect(client.getChargerStatus({})).rejects.toThrow(EvChargerError);
  });

  it("validates period range", async () => {
    const client = new EvChargerClient({
      serviceKey: SERVICE_KEY,
      fetchImpl: vi.fn() as unknown as typeof fetch,
    });
    await expect(client.getChargerStatus({ period: 11 })).rejects.toThrow(RangeError);
    await expect(client.getChargerStatus({ period: 0 })).rejects.toThrow(RangeError);
  });

  it("does not include empty/undefined params in the URL", async () => {
    const { fetchImpl, calls } = queuedFetch([
      { status: 200, body: flatStatusBody([]) },
    ]);
    const client = new EvChargerClient({ serviceKey: SERVICE_KEY, fetchImpl });
    await client.getChargerStatus({ statId: "X" });
    const url = calls[0]!;
    expect(url).toContain("statId=X");
    expect(url).not.toContain("zcode=");
    expect(url).not.toContain("chgerId=");
  });
});

describe("EvChargerClient.getChargerInfo", () => {
  const apiRow = {
    statNm: "테스트 충전소",
    statId: "ME000001",
    chgerId: "01",
    chgerType: "04",
    addr: "서울특별시 강남구",
    addrDetail: "",
    location: "1층",
    lat: 37.5,
    lng: 127.0,
    useTime: "24시간",
    busiId: "ME",
    bnm: "한국환경공단",
    busiNm: "한국환경공단",
    busiCall: "",
    stat: "2",
    statUpdDt: "20260507143015",
    lastTsdt: "",
    lastTedt: "",
    nowTsdt: "",
    powerType: "",
    output: "50",
    method: "단독",
    zcode: "11",
    zscode: "11680",
    kind: "",
    kindDetail: "",
    parkingFree: "Y",
    note: "",
    limitYn: "N",
    limitDetail: "",
    delYn: "N",
    delDetail: "",
    trafficYn: "",
    year: "2024",
    floorNum: "",
    floorType: "",
  };

  it("maps camelCase upstream rows to snake_case ChargerInfo", async () => {
    const { fetchImpl } = queuedFetch([
      {
        status: 200,
        body: JSON.stringify({
          resultCode: "00",
          resultMsg: "NORMAL SERVICE.",
          totalCount: 1,
          pageNo: 1,
          numOfRows: 1,
          items: { item: [apiRow] },
        }),
      },
    ]);
    const client = new EvChargerClient({ serviceKey: SERVICE_KEY, fetchImpl });
    const { items } = await client.getChargerInfo({ pageNo: 1, numOfRows: 100 });
    expect(items).toHaveLength(1);
    const c = items[0]!;
    expect(c.stat_id).toBe("ME000001");
    expect(c.stat_nm).toBe("테스트 충전소");
    expect(c.lat).toBe(37.5);
    expect(c.parking_free).toBe("Y");
    // Empty strings should normalize to null on optional fields.
    expect(c.addr_detail).toBeNull();
    expect(c.busi_call).toBeNull();
    // Y/N flags default to "N" when stored empty (limit_yn was "N" here).
    expect(c.limit_yn).toBe("N");
  });

  it("rejects numOfRows > 9999", async () => {
    const client = new EvChargerClient({
      serviceKey: SERVICE_KEY,
      fetchImpl: vi.fn() as unknown as typeof fetch,
    });
    await expect(client.getChargerInfo({ numOfRows: 10000 })).rejects.toThrow(
      RangeError,
    );
  });
});
