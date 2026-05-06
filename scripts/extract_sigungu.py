"""Extract sigungu (zscode) code table from the docx into JSON.

Run once to regenerate src/ev_mcp/codes/sigungu.json from the original docx.
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

DOCX_PATH = Path(
    "/home/bokeum/ai/ev_mcp/한국환경공단_전기자동차 충전소 정보_OpenAPI활용가이드_v1.23.docx"
)
OUT_PATH = Path("/home/bokeum/ai/ev_mcp/src/ev_mcp/codes/sigungu.json")

NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_paragraphs(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as zf, zf.open("word/document.xml") as f:
        tree = ET.parse(f)
    out = []
    for p in tree.iter(f"{NS}p"):
        chunks = [t.text for t in p.iter(f"{NS}t") if t.text]
        if chunks:
            out.append("".join(chunks))
    return out


def main() -> int:
    paras = docx_paragraphs(DOCX_PATH)
    text = "\n".join(paras)

    start_marker = "zscode(지역구분상세 코드)"
    end_marker = "kind(충전소 구분 코드)"
    if start_marker not in text or end_marker not in text:
        print("could not locate sigungu section", file=sys.stderr)
        return 1
    # Use rsplit / rfind because the markers also appear in the TOC.
    start = text.rfind(start_marker)
    end = text.rfind(end_marker)
    if start == -1 or end == -1 or end <= start:
        print("markers misordered", file=sys.stderr)
        return 1
    section = text[start + len(start_marker) : end]

    code_re = re.compile(r"^\d{5}$")
    lines = [line.strip() for line in section.splitlines() if line.strip()]

    table: dict[str, str] = {}
    i = 0
    while i < len(lines) - 1:
        if code_re.match(lines[i]):
            code = lines[i]
            name = lines[i + 1]
            if not code_re.match(name):
                table[code] = name
            i += 2
        else:
            i += 1

    OUT_PATH.write_text(
        json.dumps(table, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(table)} entries to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
