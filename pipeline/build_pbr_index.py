#!/usr/bin/env python3
"""
Build the PBR triplet index for neocron-renodx-engine.

Key = hash of the *vanilla game texture the engine binds at runtime*
(LockRect of the loose pak_*.dds the game loads). Value = the three
sibling maps produced by the _pbr_pipeline:

    <hex_hash> <albedo_rel> <normal_rel> <orme_rel>

Hash scheme is byte-identical to the one in engine_injector.cpp and the
original build-hash-index.py (proven to match runtime LockRect for the
2193-normal corpus, per the m4_per_texture_normals finding):

    pak_decompress -> raw DDS/BMP
    DDS:  pixels = bytes[128:]                  ; w@16 h@12 (LE u32)
    BMP:  pixels = bytes[<offset@10>:]          ; w@18 h@22
    crc  = crc32(pixels[:4096])
    hash = (crc << 32) | (w & 0xFFFF) << 16 | (h & 0xFFFF)

Source = the GAME INSTALL loose tree (authoritative; complete 3568 set,
byte-identical to the nc2-hd-textures copies where both exist). Only
textures whose full _albedo/_n/_orme triplet exists are emitted, so a
partially-processed corpus still yields a valid index.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

import ncconfig
PAK_DECOMPRESS = ncconfig.PAK_DECOMPRESS
# 64 KiB: NC2 world textures are DXT (linear block-rows, no row padding)
# so offline-tight == runtime LockRect pitch — the proven match holds —
# while genuine hash collisions drop 69 -> 21 vs the old 4 KiB. MUST
# stay in lockstep with HASH_SAMPLE_BYTES in engine_injector.cpp.
HASH_BYTES = 65536


def hash_raw(pixels: bytes, w: int, h: int) -> int:
    crc = zlib.crc32(pixels[:HASH_BYTES]) & 0xFFFFFFFF
    return (crc << 32) | ((w & 0xFFFF) << 16) | (h & 0xFFFF)


def parse_raw(data: bytes) -> tuple[bytes, int, int] | None:
    if data[:4] == b"DDS ":
        h = int.from_bytes(data[12:16], "little")
        w = int.from_bytes(data[16:20], "little")
        return (data[128:], w, h)
    if data[:2] == b"BM":
        off = int.from_bytes(data[10:14], "little")
        w = int.from_bytes(data[18:22], "little")
        h = abs(int.from_bytes(data[22:26], "little", signed=True))
        return (data[off:], w, h)
    return None


def unwrap(src: Path, wd: Path) -> Path | None:
    r = subprocess.run(["php", PAK_DECOMPRESS, str(src), f"{wd}/"],
                        capture_output=True, text=True)
    if r.returncode != 0:
        return None
    fs = list(wd.iterdir())
    return fs[0] if fs else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source",
                    default=str(ncconfig.GAME_DIR / "gfx" / "worlds"))
    ap.add_argument("--maps", default=str(ncconfig.OUT_DIR / "worlds"))
    ap.add_argument("--out", default=str(ncconfig.INDEX_JSON))
    # path prefix the engine prepends (corpus root). Maps are deployed
    # under <corpus>/worlds/... so the index stores worlds-relative paths.
    ap.add_argument("--prefix", default="worlds")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    src_root = Path(args.source).resolve()
    maps_root = Path(args.maps).resolve()
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    srcs = sorted(p for p in src_root.rglob("*")
                  if p.is_file() and p.suffix.lower() in (".dds", ".bmp"))
    if args.limit:
        srcs = srcs[:args.limit]
    print(f"hashing {len(srcs)} vanilla textures from {src_root}")

    import hashlib
    index: dict[str, dict] = {}
    key_md5: dict[str, str] = {}     # hash -> raw-DDS md5 of stored entry
    poisoned: set[str] = set()       # genuine collisions -> drop entirely
    ok = no_maps = decode_fail = dup = 0
    with tempfile.TemporaryDirectory() as tmp:
        wd = Path(tmp)
        for i, src in enumerate(srcs):
            if i and i % 300 == 0:
                print(f"  {i}/{len(srcs)} ok={ok} no_maps={no_maps} "
                      f"dup={dup} poisoned={len(poisoned)}")
            for f in wd.iterdir():
                f.unlink()
            raw = unwrap(src, wd)
            if not raw:
                decode_fail += 1
                continue
            raw_bytes = raw.read_bytes()
            parsed = parse_raw(raw_bytes)
            if not parsed:
                decode_fail += 1
                continue
            pixels, w, h = parsed
            key = f"{hash_raw(pixels, w, h):016x}"
            md5 = hashlib.md5(raw_bytes).hexdigest()

            rel_dir = src.parent.relative_to(src_root)   # e.g. global / .
            stem = src.stem                              # pak_xxx
            rd = "" if str(rel_dir) == "." else f"{rel_dir}/"
            trip = {}
            for kind, suf in (("albedo", "_albedo.jpg"),
                              ("normal", "_n.png"),
                              ("orme", "_orme.png")):
                fp = maps_root / rel_dir / f"{stem}{suf}"
                if not fp.exists():
                    break
                trip[kind] = f"{args.prefix}/{rd}{stem}{suf}".replace(
                    "//", "/")
            if len(trip) != 3:
                no_maps += 1
                continue

            if key in poisoned:
                continue
            if key in index:
                if key_md5[key] == md5:
                    dup += 1            # byte-identical dupe — harmless
                else:
                    # genuine collision: different textures, same hash.
                    # Poison so NEITHER gets a (wrong) HD swap in-game;
                    # both fall back to vanilla (graceful, not corrupt).
                    poisoned.add(key)
                    index.pop(key, None)
                    key_md5.pop(key, None)
                continue
            index[key] = {**trip, "source": src.name, "w": w, "h": h}
            key_md5[key] = md5
            ok += 1

    print(f"\ndone entries={len(index)} ok={ok} dup={dup} "
          f"no_maps={no_maps} decode_fail={decode_fail} "
          f"poisoned_collisions={len(poisoned)}")

    out_path.write_text(json.dumps(index, indent=1))
    txt = out_path.with_suffix(".txt")
    with txt.open("w") as f:
        for hx, v in sorted(index.items()):
            f.write(f"{hx} {v['albedo']} {v['normal']} {v['orme']}\n")
    print(f"json: {out_path} ({out_path.stat().st_size}B)")
    print(f"txt : {txt} ({txt.stat().st_size}B)  <- ship as "
          f"neocron_texture_index.txt")


if __name__ == "__main__":
    main()
