/**
 * data.go.kr EvCharger OpenAPI v1.23 client (Workers fetch).
 *
 * Stage 3b ships only ``getChargerStatus`` — info is the Stage-4 sync worker's
 * job. Mirrors :mod:`ev_mcp.client` 1:1 in shape, with Workers-runtime
 * differences (global fetch + AbortController instead of httpx.AsyncClient).
 *
 * Security
 * --------
 * data.go.kr's gateway is known to echo the full request URL (including
 * ``serviceKey``) back in error bodies, and TypeScript's ``Error.message``
 * sometimes carries the URL through. Every code path that surfaces an
 * external string (logs, thrown errors) runs it through :func:`redact` first
 * so the SERVICE_KEY never escapes the worker.
 */

import {
  type ChargerInfo,
  type ChargerStatusRow,
  coerceStat,
  parseYyyymmddhhmmss,
  type ResultHeader,
} from "./types.js";

const API_BASE_URL = "https://apis.data.go.kr/B552584/EvCharger";
const REQUEST_TIMEOUT_MS = 90_000;
const MAX_RETRIES = 3;
const OK_RESULT_CODE = "00";
const MAX_NUM_OF_ROWS = 9999;
const MIN_STATUS_PERIOD_MIN = 1;
const MAX_STATUS_PERIOD_MIN = 10;
const RETRYABLE_STATUS_CODES = new Set<number>([408, 425, 429, 500, 502, 503, 504]);

export class EvChargerError extends Error {
  readonly resultCode?: string;
  constructor(message: string, opts?: { resultCode?: string }) {
    super(message);
    this.name = "EvChargerError";
    if (opts?.resultCode != null) this.resultCode = opts.resultCode;
  }
}

export interface EvChargerClientOptions {
  serviceKey: string;
  baseUrl?: string;
  timeoutMs?: number;
  maxRetries?: number;
  /** Injection point for tests — defaults to the runtime global. */
  fetchImpl?: typeof fetch;
}

interface UpstreamHeader {
  resultCode?: unknown;
  resultMsg?: unknown;
  pageNo?: unknown;
  numOfRows?: unknown;
  totalCount?: unknown;
}

interface UpstreamItemsObj {
  item?: unknown;
}

interface UpstreamPayload {
  response?: {
    header?: UpstreamHeader;
    body?: { items?: UpstreamItemsObj | unknown[] };
  };
  header?: UpstreamHeader;
  body?: { items?: UpstreamItemsObj | unknown[] };
  resultCode?: unknown;
  resultMsg?: unknown;
  pageNo?: unknown;
  numOfRows?: unknown;
  totalCount?: unknown;
  items?: UpstreamItemsObj | unknown[];
}

export interface GetChargerStatusArgs {
  pageNo?: number;
  numOfRows?: number;
  period?: number;
  zcode?: string;
  zscode?: string;
  statId?: string;
  chgerId?: string;
}

export interface GetChargerInfoArgs {
  pageNo?: number;
  numOfRows?: number;
  zcode?: string;
  zscode?: string;
  kind?: string;
  kindDetail?: string;
  statId?: string;
  chgerId?: string;
}

export class EvChargerClient {
  private readonly serviceKey: string;
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: EvChargerClientOptions) {
    this.serviceKey = opts.serviceKey;
    this.baseUrl = opts.baseUrl ?? API_BASE_URL;
    this.timeoutMs = opts.timeoutMs ?? REQUEST_TIMEOUT_MS;
    this.maxRetries = opts.maxRetries ?? MAX_RETRIES;
    // The Workers runtime's global `fetch` must be invoked with its original
    // `this` binding — calling it through a class field strips the binding
    // and surfaces as "Illegal invocation". Bind once at construction.
    const raw = opts.fetchImpl ?? fetch;
    this.fetchImpl = raw.bind(globalThis);
  }

  /**
   * Strip the SERVICE_KEY from arbitrary text (error messages, response bodies).
   * data.go.kr keys are base64-ish and may appear raw, percent-encoded, or
   * plus-encoded depending on which serializer touched them.
   */
  redact(text: unknown): string {
    let s = String(text);
    if (!this.serviceKey) return s;
    const variants = new Set<string>([
      this.serviceKey,
      encodeURIComponent(this.serviceKey),
      encodeURIComponent(this.serviceKey).replace(/%20/g, "+"),
    ]);
    for (const v of variants) {
      if (v) s = s.split(v).join("***");
    }
    return s;
  }

  async getChargerStatus(
    args: GetChargerStatusArgs = {},
  ): Promise<{ header: ResultHeader; items: ChargerStatusRow[] }> {
    const { period, numOfRows = 100 } = args;
    if (period != null && (period < MIN_STATUS_PERIOD_MIN || period > MAX_STATUS_PERIOD_MIN)) {
      throw new RangeError(
        `period must be between ${MIN_STATUS_PERIOD_MIN} and ${MAX_STATUS_PERIOD_MIN} minutes`,
      );
    }
    if (numOfRows > MAX_NUM_OF_ROWS) {
      throw new RangeError(`numOfRows must be <= ${MAX_NUM_OF_ROWS}`);
    }

    const payload = await this.request("getChargerStatus", {
      pageNo: args.pageNo ?? 1,
      numOfRows,
      period: args.period,
      zcode: args.zcode,
      zscode: args.zscode,
      statId: args.statId,
      chgerId: args.chgerId,
    });
    const { header, items } = unwrapItems(payload);
    if (header.result_code !== OK_RESULT_CODE) {
      throw new EvChargerError(`getChargerStatus error: ${header.result_msg}`, {
        resultCode: header.result_code,
      });
    }
    return { header, items: items.map(toStatusRow) };
  }

  /**
   * Fetch one page of getChargerInfo. Used by the Stage-4 sync worker.
   * Phase 6 lesson: numOfRows=9999 trips data.go.kr's 504 gateway timeout,
   * so the default is 2000. Caller paginates explicitly via pageNo.
   */
  async getChargerInfo(
    args: GetChargerInfoArgs = {},
  ): Promise<{ header: ResultHeader; items: ChargerInfo[] }> {
    const { numOfRows = 2000 } = args;
    if (numOfRows > MAX_NUM_OF_ROWS) {
      throw new RangeError(`numOfRows must be <= ${MAX_NUM_OF_ROWS}`);
    }
    const payload = await this.request("getChargerInfo", {
      pageNo: args.pageNo ?? 1,
      numOfRows,
      zcode: args.zcode,
      zscode: args.zscode,
      kind: args.kind,
      kindDetail: args.kindDetail,
      statId: args.statId,
      chgerId: args.chgerId,
    });
    const { header, items } = unwrapItems(payload);
    if (header.result_code !== OK_RESULT_CODE) {
      throw new EvChargerError(`getChargerInfo error: ${header.result_msg}`, {
        resultCode: header.result_code,
      });
    }
    return { header, items: items.map(apiToChargerInfo) };
  }

  // --------------------------------------------------------------------
  // HTTP plumbing
  // --------------------------------------------------------------------

  private async request(
    op: string,
    rawParams: Record<string, string | number | undefined>,
  ): Promise<UpstreamPayload> {
    const params = new URLSearchParams();
    params.set("serviceKey", this.serviceKey);
    params.set("dataType", "JSON");
    for (const [k, v] of Object.entries(rawParams)) {
      if (v != null && v !== "") params.set(k, String(v));
    }
    const url = `${this.baseUrl}/${op}?${params.toString()}`;

    let lastErr: unknown = null;
    for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      try {
        const resp = await this.fetchImpl(url, {
          method: "GET",
          headers: { Accept: "application/json" },
          signal: controller.signal,
        });
        if (!resp.ok) {
          if (RETRYABLE_STATUS_CODES.has(resp.status)) {
            lastErr = new EvChargerError(`${op} HTTP ${resp.status}`, {
              resultCode: String(resp.status),
            });
          } else {
            throw new EvChargerError(`${op} HTTP ${resp.status}`, {
              resultCode: String(resp.status),
            });
          }
        } else {
          // Trust the body even if content-type lies (gateway sometimes
          // returns text/xml under JSON throttling).
          const text = await resp.text();
          try {
            return JSON.parse(text) as UpstreamPayload;
          } catch {
            const safe = this.redact(text.slice(0, 200));
            throw new EvChargerError(
              `non-JSON response from ${op} (status=${resp.status}, body[:200]=${JSON.stringify(safe)})`,
            );
          }
        }
      } catch (e) {
        if (e instanceof EvChargerError && e.resultCode != null && !RETRYABLE_STATUS_CODES.has(Number(e.resultCode))) {
          throw e;
        }
        lastErr = e;
      } finally {
        clearTimeout(timer);
      }

      if (attempt >= this.maxRetries) break;
      const base = 0.5 * 2 ** (attempt - 1);
      const backoffMs = (base + Math.random() * base * 0.3) * 1000;
      await sleep(backoffMs);
    }
    throw new EvChargerError(`${op} failed after retries: ${this.redact(lastErr)}`);
  }
}

// ---------------------------------------------------------------------------
// JSON envelope normalization (mirrors `_unwrap_items` in client.py)
// ---------------------------------------------------------------------------

interface RawItem {
  // ChargerStatusRow fields
  busiId?: unknown;
  statId?: unknown;
  chgerId?: unknown;
  stat?: unknown;
  statUpdDt?: unknown;
  lastTsdt?: unknown;
  lastTedt?: unknown;
  nowTsdt?: unknown;
  // Additional ChargerInfo fields
  statNm?: unknown;
  chgerType?: unknown;
  addr?: unknown;
  addrDetail?: unknown;
  location?: unknown;
  lat?: unknown;
  lng?: unknown;
  useTime?: unknown;
  bnm?: unknown;
  busiNm?: unknown;
  busiCall?: unknown;
  powerType?: unknown;
  output?: unknown;
  method?: unknown;
  zcode?: unknown;
  zscode?: unknown;
  kind?: unknown;
  kindDetail?: unknown;
  parkingFree?: unknown;
  note?: unknown;
  limitYn?: unknown;
  limitDetail?: unknown;
  delYn?: unknown;
  delDetail?: unknown;
  trafficYn?: unknown;
  year?: unknown;
  floorNum?: unknown;
  floorType?: unknown;
}

function unwrapItems(payload: UpstreamPayload): {
  header: ResultHeader;
  items: RawItem[];
} {
  // Either the spec-wrapped form ({response: {header, body}}) or the flat
  // form ({resultCode, items}) — widen the discriminated narrowing so both
  // sets of properties stay reachable.
  const wrapped: Partial<UpstreamPayload> = payload.response ?? payload;
  let headerRaw: UpstreamHeader;
  let itemsObj: UpstreamItemsObj | unknown[] | undefined;
  if (wrapped.header) {
    headerRaw = wrapped.header;
    const body = wrapped.body ?? {};
    itemsObj = (body as { items?: UpstreamItemsObj | unknown[] }).items;
  } else {
    headerRaw = {
      resultCode: wrapped.resultCode,
      resultMsg: wrapped.resultMsg,
      pageNo: wrapped.pageNo,
      numOfRows: wrapped.numOfRows,
      totalCount: wrapped.totalCount,
    };
    itemsObj = wrapped.items;
  }

  let raw: RawItem[] = [];
  if (Array.isArray(itemsObj)) {
    raw = itemsObj as RawItem[];
  } else if (itemsObj && typeof itemsObj === "object") {
    const inner = (itemsObj as UpstreamItemsObj).item;
    if (Array.isArray(inner)) raw = inner as RawItem[];
    else if (inner && typeof inner === "object") raw = [inner as RawItem];
  }

  const header: ResultHeader = {
    result_code: typeof headerRaw.resultCode === "string" ? headerRaw.resultCode : "",
    result_msg: typeof headerRaw.resultMsg === "string" ? headerRaw.resultMsg : "",
    page_no: numOrNull(headerRaw.pageNo),
    num_of_rows: numOrNull(headerRaw.numOfRows),
    total_count: numOrNull(headerRaw.totalCount),
  };
  return { header, items: raw };
}

function toStatusRow(raw: RawItem): ChargerStatusRow {
  return {
    busi_id: typeof raw.busiId === "string" ? raw.busiId : "",
    stat_id: typeof raw.statId === "string" ? raw.statId : "",
    chger_id: typeof raw.chgerId === "string" ? raw.chgerId : "",
    stat: coerceStat(raw.stat),
    stat_upd_dt: parseYyyymmddhhmmss(raw.statUpdDt),
    last_tsdt: parseYyyymmddhhmmss(raw.lastTsdt),
    last_tedt: parseYyyymmddhhmmss(raw.lastTedt),
    now_tsdt: parseYyyymmddhhmmss(raw.nowTsdt),
  };
}

const STR = (v: unknown): string => (typeof v === "string" ? v : "");
const OPT_STR = (v: unknown): string | null =>
  typeof v === "string" && v.trim() !== "" ? v : null;
const NUM = (v: unknown): number => {
  if (typeof v === "number") return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
};
const YN = (v: unknown): string => {
  if (typeof v !== "string" || v.trim() === "") return "N";
  return v;
};

/**
 * Map a single raw item from getChargerInfo (camelCase) to ChargerInfo
 * (snake_case, the canonical worker shape). Mirrors the alias-driven
 * Pydantic conversion in `ev_mcp.models.ChargerInfo`.
 */
function apiToChargerInfo(raw: RawItem): ChargerInfo {
  return {
    stat_nm: STR(raw.statNm),
    stat_id: STR(raw.statId),
    chger_id: STR(raw.chgerId),
    chger_type: STR(raw.chgerType),
    addr: STR(raw.addr),
    addr_detail: OPT_STR(raw.addrDetail),
    location: OPT_STR(raw.location),
    lat: NUM(raw.lat),
    lng: NUM(raw.lng),
    use_time: STR(raw.useTime),
    busi_id: STR(raw.busiId),
    bnm: STR(raw.bnm),
    busi_nm: STR(raw.busiNm),
    busi_call: OPT_STR(raw.busiCall),
    stat: coerceStat(raw.stat),
    stat_upd_dt: parseYyyymmddhhmmss(raw.statUpdDt),
    last_tsdt: parseYyyymmddhhmmss(raw.lastTsdt),
    last_tedt: parseYyyymmddhhmmss(raw.lastTedt),
    now_tsdt: parseYyyymmddhhmmss(raw.nowTsdt),
    power_type: OPT_STR(raw.powerType),
    output: OPT_STR(raw.output),
    method: OPT_STR(raw.method),
    zcode: STR(raw.zcode),
    zscode: OPT_STR(raw.zscode),
    kind: OPT_STR(raw.kind),
    kind_detail: OPT_STR(raw.kindDetail),
    parking_free: OPT_STR(raw.parkingFree),
    note: OPT_STR(raw.note),
    limit_yn: YN(raw.limitYn),
    limit_detail: OPT_STR(raw.limitDetail),
    del_yn: YN(raw.delYn),
    del_detail: OPT_STR(raw.delDetail),
    traffic_yn: OPT_STR(raw.trafficYn),
    year: OPT_STR(raw.year),
    floor_num: OPT_STR(raw.floorNum),
    floor_type: OPT_STR(raw.floorType),
  };
}

function numOrNull(v: unknown): number | null {
  if (typeof v === "number") return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
