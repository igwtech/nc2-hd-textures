#!/usr/bin/env python3
"""Stage 4 — downscale the generated HD map corpus to <=512 (longest
side). The NC2 engine clamps >512 at runtime anyway, so 1024 maps only
waste disk (~4x). albedo stays JPG q92/4:4:4; _n/_orme stay lossless
PNG. In-place, idempotent (skips <=512), parallel, local, $0.

CRITICAL: _orme.png packs Emissive in ALPHA (a DATA channel, ~0 for
most textures). PIL premultiplies alpha on an RGBA resize -> RGB zeroed
wherever A==0. So RGBA maps are band-split (resize each channel alone).
This bug once destroyed the whole ORME corpus — do not "simplify" it.

Operates on ncconfig.OUT_DIR/worlds (env: NC_PBR_BUILD)."""
import glob
import os
import sys
from concurrent.futures import ProcessPoolExecutor

from PIL import Image

import ncconfig

OUT = str(ncconfig.OUT_DIR / "worlds")
CAP = 512


def one(p: str) -> str:
    try:
        im = Image.open(p)
        im.load()
        if max(im.size) <= CAP:
            return "skip"
        s = CAP / max(im.size)
        nw = (max(1, round(im.size[0] * s)), max(1, round(im.size[1] * s)))
        if p.endswith("_albedo.jpg"):
            im.convert("RGB").resize(nw, Image.LANCZOS).save(
                p, quality=92, subsampling=0)
        elif im.mode == "RGBA":
            bands = [b.resize(nw, Image.LANCZOS) for b in im.split()]
            Image.merge("RGBA", bands).save(p, optimize=True)
        else:
            im.resize(nw, Image.LANCZOS).save(p, optimize=True)
        return "ok"
    except Exception as e:  # noqa: BLE001
        return f"err {os.path.relpath(p, OUT)}: {str(e)[:100]}"


def main() -> None:
    files = []
    for suf in ("*_albedo.jpg", "*_n.png", "*_orme.png"):
        files += glob.glob(os.path.join(OUT, "**", suf), recursive=True)
    print(f"corpus maps: {len(files)} ({OUT})")
    ok = skip = err = 0
    with ProcessPoolExecutor(max_workers=16) as ex:
        for i, r in enumerate(ex.map(one, files, chunksize=32)):
            if r == "ok":
                ok += 1
            elif r == "skip":
                skip += 1
            else:
                err += 1
                print(" ", r)
            if i and i % 2000 == 0:
                print(f"  {i}/{len(files)} ok={ok} skip={skip} err={err}")
    print(f"done: resized={ok} already<=512={skip} err={err}")


if __name__ == "__main__":
    sys.exit(main())
