import { describe, expect, it } from "vitest";

import { resolveBusiId, resolveSido, resolveSigungu } from "./index.js";

describe("resolveSido", () => {
  it("returns the input when it is already a zcode", () => {
    expect(resolveSido("11")).toBe("11");
    expect(resolveSido("41")).toBe("41");
  });

  it("matches by exact name", () => {
    expect(resolveSido("서울특별시")).toBe("11");
    expect(resolveSido("부산광역시")).toBe("26");
  });

  it("matches by prefix", () => {
    expect(resolveSido("서울")).toBe("11");
    expect(resolveSido("경기")).toBe("41");
  });

  it("returns null for unknown input", () => {
    expect(resolveSido("도쿄")).toBeNull();
    expect(resolveSido("")).toBeNull();
  });
});

describe("resolveSigungu", () => {
  it("returns the input when it is already a zscode", () => {
    expect(resolveSigungu("11680")).toBe("11680");
  });

  it("returns null on ambiguity (same name in multiple sido)", () => {
    // "중구" appears in Seoul, Busan, Daegu, Incheon, Daejeon, Ulsan...
    // The resolver returns null when more than one zscode matches.
    expect(resolveSigungu("중구")).toBeNull();
  });

  it("returns null for unknown input", () => {
    expect(resolveSigungu("없는구")).toBeNull();
  });
});

describe("resolveBusiId", () => {
  it("returns the input when it is already a busiId code", () => {
    expect(resolveBusiId("ME")).toBe("ME");
  });

  it("matches by name (exact or substring)", () => {
    // The actual label for "ME" in busi_id.json is "기후에너지환경부".
    expect(resolveBusiId("기후에너지환경부")).toBe("ME");
    expect(resolveBusiId("환경부")).toBe("ME");
  });

  it("returns null for unknown input", () => {
    expect(resolveBusiId("존재하지않는기관")).toBeNull();
  });
});
