#!/usr/bin/env python3
"""Stage 5b — ORME occlusion policy: NEUTRAL (flat O=1.0) for the whole
world corpus.

WHY (hard-won, 2026-05-17): NC2 floor / walls / ceiling — the bulk of
the world — are TILING textures, NOT UV-mapped. A per-tile baked AO is
conceptually wrong: the small AO map repeats across the surface and
SLIDES with the camera ("ORME jumping"), no matter how smooth. Smoothing
/ shallow-clamping does not fix it (it still tiles). The real ambient
occlusion for tiling geometry is ALREADY baked into the game's
LIGHTMAPS, which the substituted world.ps consumes as irradiance.

So O is neutralised to 1.0 for EVERY world `_orme.png` (the recovered
set AND the original pix2pix maps, which were also per-tile/blotchy).
The normal map is kept (tiled relief = desirable micro-detail, not
position-dependent like AO). G/B/A (roughness, exact metallic, exact
emissive) kept verbatim. Idempotent (skips already-flat).

DO NOT reintroduce baked AO for tiling world textures. Per-tile AO only
makes sense for genuinely UV-mapped / atlas props.

Operates on ncconfig.OUT_DIR/worlds. Local, $0."""
import argparse
import glob
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

import ncconfig

OUT = str(ncconfig.OUT_DIR / "worlds")


def one(orme_path: str) -> str:
    try:
        arr = np.array(Image.open(orme_path).convert("RGBA"), np.uint8)
        if int(arr[..., 0].min()) == 255 and int(arr[..., 0].max()) == 255:
            return "already-flat"
        arr[..., 0] = 255                       # O = 1.0 flat; G/B/A kept
        Image.fromarray(arr, "RGBA").save(orme_path, optimize=True)
        return "neutralised"
    except Exception as exc:  # noqa: BLE001
        return f"ERR {Path(orme_path).name}: {str(exc)[:100]}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    fs = sorted(glob.glob(f"{OUT}/**/*_orme.png", recursive=True))
    if a.limit:
        fs = fs[:a.limit]
    print(f"processing {len(fs)} orme ({OUT})")
    n = {}
    with ProcessPoolExecutor(max_workers=14) as ex:
        for i, r in enumerate(ex.map(one, fs, chunksize=16)):
            k = r if r in ("neutralised", "already-flat") else "ERR"
            n[k] = n.get(k, 0) + 1
            if k == "ERR" and n["ERR"] <= 8:
                print("  ", r)
            if i and i % 1500 == 0:
                print(f"  {i}/{len(fs)} {n}")
    print(f"done: {n}")


if __name__ == "__main__":
    main()
