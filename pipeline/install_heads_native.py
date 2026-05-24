#!/usr/bin/env python3
"""Install HD model albedos by NATIVE replacement — re-encode the HD
albedo as a DDS, repack into the loose pak_<stem>.dds envelope and
overwrite the vanilla in $NC_GAME_DIR/gfx/modeltextures/. The game then
loads it through its normal path (mesh.ps via the native fixed renderer)
— no engine involvement, no ID, no container.

Why this path for meshes: NC2 NPCs/items/heads draw through mesh.ps,
which we cannot safely substitute (DXVK descriptor-isolation crash —
see [[mesh_ps_substitution_inviable]]). The engine's ID/container
delivery is world.ps-only. For meshes the only viable HD path is to
hand the better DDS to the GAME's own loader.

  - HD source : ncconfig.OUT_DIR/modeltextures/pak_<stem>_albedo.jpg
  - target    : ncconfig.MODELTEX_DIR/pak_<stem>.dds (or .bmp; .bmp
                kept as BMP)
  - encoding  : DXT5 (universal, alpha-safe), Lanczos resize to ≤512
                (the engine clamps >512 anyway), full mip chain for
                distance LOD.
  - backup    : ncconfig.NATIVE_BACKUP (only first time per file)
  - filter    : `--only <substr>` (default "head"). Idempotent.

Restore: `rsync -a "$NC_NATIVE_BAK/" "$NC_GAME_DIR/gfx/modeltextures/"`
"""
import argparse
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

import ncconfig

OUT = ncconfig.OUT_DIR / "modeltextures"
DST = ncconfig.MODELTEX_DIR
BACKUP = ncconfig.NATIVE_BACKUP
PAKC = str(ncconfig.PAK_COMPRESS)
CAP = 512


def find_vanilla(stem: str) -> "Path | None":
    """Vanilla modeltexture is flat under MODELTEX_DIR. Try .dds then .bmp."""
    for ext in (".dds", ".bmp"):
        p = DST / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def one(albedo_path: str) -> str:
    try:
        ap = Path(albedo_path)
        stem = ap.name[:-len("_albedo.jpg")]                # pak_xxx
        vanilla = find_vanilla(stem)
        if vanilla is None:
            return "no-vanilla"
        is_bmp = vanilla.suffix.lower() == ".bmp"

        im = Image.open(ap).convert("RGB")
        if max(im.size) > CAP:
            s = CAP / max(im.size)
            nw = (max(4, round(im.size[0] * s)),
                  max(4, round(im.size[1] * s)))
            im = im.resize(nw, Image.LANCZOS)
        # snap to mult-of-4 for DXT
        if not is_bmp:
            im = im.resize(((im.size[0] + 3) & ~3, (im.size[1] + 3) & ~3),
                           Image.LANCZOS)

        with tempfile.TemporaryDirectory() as t:
            wd = Path(t)
            raw_name = vanilla.stem.replace("pak_", "", 1)   # strip prefix
            ext = ".bmp" if is_bmp else ".dds"
            raw_path = wd / f"{raw_name}{ext}"
            if is_bmp:
                im.save(raw_path, "BMP")
            else:
                # DXT5 universal + full mip chain for distance LOD
                src_tmp = wd / "src.png"
                im.save(src_tmp, "PNG")
                r = subprocess.run([
                    "magick", str(src_tmp),
                    "-define", "dds:compression=dxt5",
                    "-define", "dds:mipmaps=10",
                    str(raw_path)], capture_output=True)
                if r.returncode != 0 or not raw_path.exists():
                    return f"MAGICKFAIL {stem}: {r.stderr.decode()[:100]}"
            outd = wd / "out"; outd.mkdir()
            subprocess.run(["php", PAKC, str(raw_path), str(outd)],
                           capture_output=True)
            packed = outd / f"pak_{raw_name}{ext}"
            if not (packed.exists() and packed.stat().st_size):
                return f"PAKFAIL {stem}"
            bdst = BACKUP / vanilla.name
            if not bdst.exists():
                bdst.parent.mkdir(parents=True, exist_ok=True)
                bdst.write_bytes(vanilla.read_bytes())
            vanilla.write_bytes(packed.read_bytes())
        return f"OK {im.size[0]}x{im.size[1]} {ext} {stem}"
    except Exception as exc:  # noqa: BLE001
        return f"ERR {Path(albedo_path).name}: {str(exc)[:120]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="head",
                    help="filename substring filter (default: head)")
    a = ap.parse_args()
    BACKUP.mkdir(parents=True, exist_ok=True)
    fs = sorted(str(p) for p in OUT.glob("*_albedo.jpg")
                if a.only.lower() in p.name.lower())
    print(f"HD model albedos matching {a.only!r}: {len(fs)} "
          f"(source={OUT}, target={DST}, backup={BACKUP})")
    n = {}
    with ProcessPoolExecutor(max_workers=14) as ex:
        for i, r in enumerate(ex.map(one, fs, chunksize=8)):
            k = "OK" if r.startswith("OK") else r.split(":")[0]
            n[k] = n.get(k, 0) + 1
            if not r.startswith("OK") and n.get(k, 0) <= 5:
                print("  ", r)
            if i and i % 100 == 0:
                print(f"  {i}/{len(fs)} {n}")
    print(f"done: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
