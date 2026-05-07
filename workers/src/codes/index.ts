/**
 * Static code tables shipped at build time.
 *
 * Source of truth = ``한국환경공단_..._v1.23.docx`` (repo root). The Python and
 * TypeScript trees both import the same JSON files, so any docx-driven
 * regeneration (`scripts/extract_sigungu.py`) updates both sides in one shot.
 */

// JSON imports — esbuild (wrangler's bundler) handles these natively without
// import attributes. tsconfig has resolveJsonModule:true.
import busi_id from "./busi_id.json";
import charger_type from "./charger_type.json";
import kind from "./kind.json";
import kind_detail from "./kind_detail.json";
import sido from "./sido.json";
import sigungu from "./sigungu.json";
import stat from "./stat.json";

type Table = Record<string, string>;

export const codeTables: Record<CodeCategory, Table> = {
  busi_id: busi_id as Table,
  charger_type: charger_type as Table,
  kind: kind as Table,
  kind_detail: kind_detail as Table,
  sido: sido as Table,
  sigungu: sigungu as Table,
  stat: stat as Table,
};

export type CodeCategory =
  | "sido"
  | "sigungu"
  | "charger_type"
  | "stat"
  | "busi_id"
  | "kind"
  | "kind_detail";

export const CODE_CATEGORIES: readonly CodeCategory[] = [
  "sido",
  "sigungu",
  "charger_type",
  "stat",
  "busi_id",
  "kind",
  "kind_detail",
];

export const sidoLabel = (code: string): string => codeTables.sido[code] ?? code;
export const sigunguLabel = (code: string): string => codeTables.sigungu[code] ?? code;
export const chargerTypeLabel = (code: string): string =>
  codeTables.charger_type[code] ?? `코드 ${code}`;
export const statLabel = (code: string): string => codeTables.stat[code] ?? "알수없음";
export const busiIdLabel = (code: string): string => codeTables.busi_id[code] ?? code;
export const kindLabel = (code: string): string => codeTables.kind[code] ?? code;
export const kindDetailLabel = (code: string): string => codeTables.kind_detail[code] ?? code;

/**
 * Map ``"서울특별시" | "11" | "서울"`` to a zcode. Returns null if unresolvable.
 *
 * Mirrors :func:`ev_mcp.codes_lookup.resolve_sido`.
 */
export function resolveSido(query: string): string | null {
  if (query in codeTables.sido) return query;
  for (const [code, name] of Object.entries(codeTables.sido)) {
    if (name === query || name.startsWith(query) || name.includes(query)) {
      return code;
    }
  }
  return null;
}

/**
 * Map ``"강남구" | "11680"`` to a zscode. Returns null on ambiguity / unknown.
 */
export function resolveSigungu(query: string): string | null {
  if (query in codeTables.sigungu) return query;
  const matches = Object.entries(codeTables.sigungu)
    .filter(([_, name]) => name === query)
    .map(([code]) => code);
  return matches.length === 1 ? (matches[0] ?? null) : null;
}

/**
 * Map ``"환경부" | "ME" | "에버온"`` to a busiId.
 *
 * Mirrors :func:`ev_mcp.codes_lookup.resolve_busi_id`.
 */
export function resolveBusiId(query: string): string | null {
  if (query in codeTables.busi_id) return query;
  for (const [code, name] of Object.entries(codeTables.busi_id)) {
    if (name === query || name.includes(query)) {
      return code;
    }
  }
  return null;
}
