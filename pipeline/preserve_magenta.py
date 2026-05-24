#!/usr/bin/env python3
"""Stage 5c — re-imprint NC2's pure-magenta keyed transparency into the
HD albedo (v0.12).

NC2 vanilla uses pure magenta (255,0,255) as a Doom-style binary alpha
key on textures without real alpha (notably BMPs). The clarity creative
regen does NOT preserve those magenta pixels (the upscaler recolors).
This stage scans the pristine ≤512 vanilla (from $NC_IDTAG_BAK) for the
magenta key and paints it back into the corresponding HD `_albedo.jpg`
at full strength so the engine's shader `clip()` test fires.

Strict detection (R>=250 ∧ G<=5 ∧ B>=250) in vanilla — false-positive
risk on legitimate art is essentially zero (pure-magenta isn't a normal
photographic colour). Mask is upsampled NEAREST to HD dims to keep the
binary edge. Operates only on _albedo.jpg that has a vanilla source in
the backup (the tagged set). Idempotent."""
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

import ncconfig

CORPUS = ncconfig.OUT_DIR / "worlds"
VANILLA = ncconfig.IDTAG_BACKUP                       # pristine ≤512
PAKD = str(ncconfig.PAK_DECOMPRESS)

# strict vanilla magenta test (no JPG bleed here — vanilla is DXT/BMP)
R_HI, G_LO, B_HI = 250, 5, 250


def vanilla_rgb(rel: Path) -> "np.ndarray | None":
    """Decode the pristine vanilla DDS/BMP to an HxWx3 uint8 array."""
    for ext in (".dds", ".bmp"):
        src = VANILLA / rel.with_suffix(ext)
        if not src.exists():
            continue
        with tempfile.TemporaryDirectory() as t:
            subprocess.run(["php", PAKD, str(src), f"{t}/"],
                           capture_output=True)
            fs = [p for p in Path(t).iterdir() if p.is_file()]
            if not fs:
                continue
            # magick handles both DDS and BMP -> raw PNG bytes
            r = subprocess.run(
                ["magick", str(fs[0]), "-depth", "8", "png:-"],
                capture_output=True)
            if r.returncode != 0 or not r.stdout:
                continue
            try:
                im = Image.open(__import__("io").BytesIO(r.stdout)) \
                    .convert("RGB")
                return np.asarray(im, np.uint8)
            except Exception:
                continue
    return None


def one(albedo_path: str) -> str:
    try:
        ap = Path(albedo_path)
        stem = ap.name[:-len("_albedo.jpg")]                    # pak_xxx
        rel = ap.parent.relative_to(CORPUS) / stem              # dir/pak_xxx
        van = vanilla_rgb(rel)
        if van is None:
            return "no-vanilla"
        # vanilla magenta mask
        mk = ((van[..., 0] >= R_HI) & (van[..., 1] <= G_LO)
              & (van[..., 2] >= B_HI))
        if not mk.any():
            return "no-key"

        hd = np.array(Image.open(albedo_path).convert("RGB"), np.uint8)
        # upsample/match mask to HD dims
        if mk.shape != hd.shape[:2]:
            mk = np.array(Image.fromarray(mk.astype(np.uint8) * 255)
                          .resize((hd.shape[1], hd.shape[0]),
                                  Image.NEAREST), np.uint8) > 127
        # already keyed?
        already = ((hd[..., 0] >= R_HI) & (hd[..., 1] <= G_LO)
                   & (hd[..., 2] >= B_HI))
        if (already & mk).sum() == mk.sum():
            return "already-keyed"

        hd[mk] = (255, 0, 255)
        Image.fromarray(hd, "RGB").save(albedo_path, "JPEG",
                                        quality=92, subsampling=0)
        return f"keyed {int(mk.sum())}"
    except Exception as exc:  # noqa: BLE001
        return f"ERR {Path(albedo_path).name}: {str(exc)[:120]}"


def main() -> int:
    fs = sorted(str(p) for p in CORPUS.rglob("*_albedo.jpg"))
    print(f"scanning {len(fs)} HD albedos against vanilla in {VANILLA}")
    n = {"no-vanilla": 0, "no-key": 0, "already-keyed": 0,
         "keyed": 0, "ERR": 0}
    with ProcessPoolExecutor(max_workers=14) as ex:
        for i, r in enumerate(ex.map(one, fs, chunksize=8)):
            k = ("keyed" if r.startswith("keyed")
                 else ("ERR" if r.startswith("ERR") else r))
            n[k] += 1
            if k == "ERR" and n["ERR"] <= 8:
                print("  ", r)
            if i and i % 600 == 0:
                print(f"  {i}/{len(fs)} {n}")
    print(f"done: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
