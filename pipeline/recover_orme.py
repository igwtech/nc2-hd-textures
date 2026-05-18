#!/usr/bin/env python3
"""Stage 5a — rebuild the ORME RGB for any map whose occlusion came out
~0 (e.g. a corrupted regen). M (metallic) and A (emissive) are
DETERMINISTIC functions of path + the intact _albedo.jpg (reused from
pbr_pipeline), so they're recomputed EXACTLY — no Replicate. O/R that
can't be trusted -> neutral constants (O=1.0, R=0.80); recover_ao_local
then sets the final O policy. Idempotent: only touches maps whose O
mean < 0.15. Real pix2pix maps are left untouched.

Operates on ncconfig.OUT_DIR/worlds. Local, $0."""
import glob
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

import ncconfig
from pbr_pipeline import emissive_mask, metallic_value  # deterministic

OUT = str(ncconfig.OUT_DIR / "worlds")
NEUTRAL_O = 1.0
NEUTRAL_R = 0.80


def one(orme_path: str) -> str:
    try:
        cur = np.asarray(Image.open(orme_path).convert("RGBA"),
                         np.float32) / 255.0
        if cur[..., 0].mean() >= 0.15:        # genuine pix2pix map — keep
            return "keep"
        stem_dir = Path(orme_path).parent
        base = Path(orme_path).name[:-len("_orme.png")]
        alb_p = stem_dir / f"{base}_albedo.jpg"
        if not alb_p.exists():
            return f"no-albedo {Path(orme_path).relative_to(OUT)}"
        alb = Image.open(alb_p).convert("RGB")
        w, h = alb.size
        rel = Path(orme_path).parent.relative_to(OUT) / f"{base}.dds"

        e = emissive_mask(alb, rel)
        e = np.asarray(e, np.float32)
        if e.ndim == 3:
            e = e[..., 0]
        if e.max() > 1.0:
            e = e / 255.0
        if e.shape != (h, w):
            e = np.asarray(Image.fromarray((np.clip(e, 0, 1) * 255)
                           .astype(np.uint8)).resize((w, h), Image.BILINEAR),
                           np.float32) / 255.0
        m = float(np.clip(metallic_value(rel), 0, 1))

        o = np.full((h, w), NEUTRAL_O, np.float32)
        r = np.full((h, w), NEUTRAL_R, np.float32)
        mch = np.full((h, w), m, np.float32)
        rgba = np.stack([o, r, mch, np.clip(e, 0, 1)], -1)
        Image.fromarray((rgba * 255).astype(np.uint8), "RGBA").save(
            orme_path, optimize=True)
        return "rebuilt"
    except Exception as exc:  # noqa: BLE001
        return f"ERR {Path(orme_path).name}: {str(exc)[:120]}"


def main() -> None:
    fs = sorted(glob.glob(f"{OUT}/**/*_orme.png", recursive=True))
    print(f"orme maps: {len(fs)} ({OUT})")
    n = {"rebuilt": 0, "keep": 0}
    errs = []
    with ProcessPoolExecutor(max_workers=16) as ex:
        for i, r in enumerate(ex.map(one, fs, chunksize=16)):
            if r in n:
                n[r] += 1
            else:
                errs.append(r)
            if i and i % 2000 == 0:
                print(f"  {i}/{len(fs)} {n}")
    print(f"done: rebuilt={n['rebuilt']} kept(good)={n['keep']} "
          f"errors={len(errs)}")
    for e in errs[:15]:
        print("  ", e)


if __name__ == "__main__":
    main()
