/**
 * Tool: ``lookup_codes`` — 정적 코드 테이블 조회.
 *
 * 1:1 port of :mod:`ev_mcp.tools.codes`. Static — never hits the DO or
 * data.go.kr.
 */

import { z } from "zod";

import { CODE_CATEGORIES, type CodeCategory, codeTables } from "../codes/index.js";

export const lookupCodesInputSchema = z.object({
  category: z.enum(CODE_CATEGORIES as unknown as [CodeCategory, ...CodeCategory[]]),
});

export type LookupCodesInput = z.infer<typeof lookupCodesInputSchema>;

export function lookupCodes({ category }: LookupCodesInput): Record<string, string> {
  return codeTables[category];
}

export const lookupCodesDescription =
  "공통 코드 테이블 (시도/시군구/충전기타입/상태/운영기관/구분) 조회. " +
  "category 한 개를 받아 코드→한국어 라벨 dict 반환.";
