#!/usr/bin/env python3
"""
Merge per-corpus PBR indexes (worlds, modeltextures, ...) into the single
texture_index.{txt,json} the engine loads. Cross-corpus hash collisions
(a world texture and a model texture sharing a hash but differing in
content) are POISONED — dropped from both — so the engine never swaps
the wrong HD set in. Within-corpus collisions were already poisoned by
build_pbr_index.py.

Usage:  merge_index.py a.json b.json [c.json ...]
        (writes ncconfig.INDEX_JSON + .txt)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ncconfig


def main() -> None:
    srcs = [Path(p) for p in sys.argv[1:]]
    if not srcs:
        sys.exit("usage: merge_index.py <index1.json> <index2.json> ...")

    merged: dict[str, dict] = {}
    poisoned: set[str] = set()
    for sp in srcs:
        idx = json.loads(sp.read_text())
        for h, v in idx.items():
            if h in poisoned:
                continue
            if h in merged:
                if merged[h]["albedo"] != v["albedo"]:
                    poisoned.add(h)        # cross-corpus collision
                    merged.pop(h, None)
                # else identical -> keep one
                continue
            merged[h] = v

    out_json = ncconfig.INDEX_JSON
    out_txt = out_json.with_suffix(".txt")
    out_json.write_text(json.dumps(merged, indent=1))
    with out_txt.open("w") as f:
        for h, v in sorted(merged.items()):
            f.write(f"{h} {v['albedo']} {v['normal']} {v['orme']}\n")

    by_prefix: dict[str, int] = {}
    for v in merged.values():
        p = v["albedo"].split("/", 1)[0]
        by_prefix[p] = by_prefix.get(p, 0) + 1
    print(f"merged {len(merged)} entries from {len(srcs)} indexes "
          f"(cross-corpus poisoned={len(poisoned)})")
    for p, n in sorted(by_prefix.items()):
        print(f"  {p:16s} {n}")
    print(f"-> {out_txt}")
    print(f"-> {out_json}")


if __name__ == "__main__":
    main()
