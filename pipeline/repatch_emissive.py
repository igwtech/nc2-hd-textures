#!/usr/bin/env python3
"""Free, local: recompute the A (emissive) channel of existing
_orme.png from _albedo.png using the category-aware emissive_mask.
No Replicate calls. Idempotent. Optional path substring filter."""
import sys, glob, numpy as np
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ncconfig
from pbr_pipeline import emissive_mask

OUT = ncconfig.OUT_DIR / "worlds"
filt = sys.argv[1] if len(sys.argv) > 1 else ""
chg = skip = 0
for p in glob.glob(str(OUT / "**" / "*_orme.png"), recursive=True):
    p = Path(p)
    if filt and filt not in str(p):
        continue
    stem = p.name[:-len("_orme.png")]
    ap = p.parent / f"{stem}_albedo.jpg"
    if not ap.exists():
        ap = p.parent / f"{stem}_albedo.png"   # pre-v0.8 fallback
    if not ap.exists():
        skip += 1
        continue
    rel = p.parent.relative_to(OUT) / f"{stem}.dds"
    alb = Image.open(ap).convert("RGB")
    e = emissive_mask(alb, rel)
    im = Image.open(p).convert("RGBA")
    a = np.asarray(im).copy()
    eh, ew = e.shape
    if (a.shape[0], a.shape[1]) != (eh, ew):
        e = np.asarray(Image.fromarray((np.clip(e, 0, 1) * 255)
                       .astype(np.uint8)).resize((a.shape[1], a.shape[0]),
                       Image.BILINEAR), np.float32) / 255.0
    # A inverted (v0.12): 1=non-emis, 0=full emis (shader does 1-a).
    new_a = np.uint8((1.0 - np.clip(e, 0, 1)) * 255)
    if np.array_equal(a[..., 3], new_a):
        skip += 1
        continue
    a[..., 3] = new_a
    Image.fromarray(a, "RGBA").save(p)
    chg += 1
print(f"emissive repatch ({filt or 'ALL'}): changed={chg} skipped={skip}")
