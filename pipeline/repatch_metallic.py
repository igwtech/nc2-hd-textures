#!/usr/bin/env python3
"""Free, local: rewrite ONLY the B (metallic) channel of existing
_orme.png files using the category-aware metallic_value rule. No
Replicate calls. Idempotent."""
import sys, glob, numpy as np
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ncconfig
from pbr_pipeline import metallic_value

OUT = ncconfig.OUT_DIR / "worlds"
changed = same = 0
for p in glob.glob(str(OUT / "**" / "*_orme.png"), recursive=True):
    p = Path(p)
    rel_dir = p.parent.relative_to(OUT)            # e.g. metal
    stem = p.name[:-len("_orme.png")]              # pak_outmet_11a
    rel = rel_dir / f"{stem}.dds"                  # for metallic_value
    m = metallic_value(rel)
    im = Image.open(p).convert("RGBA")
    a = np.asarray(im)
    cur = float(a[..., 2].mean()) / 255.0
    if abs(cur - m) < 0.01:
        same += 1
        continue
    a = a.copy()
    a[..., 2] = np.uint8(round(m * 255))
    Image.fromarray(a, "RGBA").save(p)
    changed += 1
print(f"repatched B-channel: changed={changed} unchanged={same}")
