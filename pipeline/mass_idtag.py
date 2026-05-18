#!/usr/bin/env python3
"""Stage 6 — DEPLOY: content-keyed embedded-ID stamping + single-file
.pbr triplet containers. This is the runtime identification scheme that
replaced the fragile content-hash (clamp / re-encode / dup-collision).

Idea #1 — we control the deployed vanilla file, so stamp a 32-bit id
(`4B 'NCID' + 4B id LE`) over mip-0 block-0. The engine reads it back via
LockRect (exact, immune to >512 clamp & re-encode). Tagged textures are
always HD-replaced at s0 -> the stomped 4x4 corner is never displayed
-> zero visual cost.

Idea #2 — id -> ONE container  HD_CORPUS/<id8hex>.pbr  =
`"NCPBR\\0"` + ver + 0 + 3×u32 LE lens + albedo.jpg + _n.png + _orme.png.
No path/stem resolution, atomic triplet.

CONTENT-KEYED: the id keys on VANILLA CONTENT (md5 of the pristine
unwrapped DDS), NOT path. All byte-identical copies (global/pak_X ≡
metal/pak_X) share ONE id + ONE canonical container -> identical HD in
every zone (per-physical-file ids made clarity-divergent dups show
different HD per zone — the bug this fixes).

Prereq: install restored to pristine ≤512
  rsync -a $NC_IDTAG_BAK/ $NC_GAME_DIR/gfx/worlds/
DDS only (BMP have no DXT block-0). Groups with no corpus triplet ->
left pristine (clean vanilla fallback). Deterministic (sorted content
keys) -> reproducible. Per-file round-trip verified. Reversible:
  rsync -a $NC_IDTAG_BAK/ $NC_GAME_DIR/gfx/worlds/ ; rm $NC_ID_INDEX
"""
import hashlib
import struct
import subprocess
import sys
import tempfile
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import ncconfig

WORLDS = ncconfig.WORLDS_DIR
CORPUS = ncconfig.OUT_DIR / "worlds"
GFXPBR = ncconfig.HD_CORPUS_DIR
BACKUP = ncconfig.IDTAG_BACKUP
IDX = ncconfig.ID_INDEX
PAKD = str(ncconfig.PAK_DECOMPRESS)
PAKC = str(ncconfig.PAK_COMPRESS)
MAGIC = b"NCID"


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True)


def unwrap_bytes(src: Path):
    with tempfile.TemporaryDirectory() as t:
        sh("php", PAKD, str(src), f"{t}/")
        fs = [p for p in Path(t).iterdir() if p.is_file()]
        return fs[0].read_bytes() if fs else None


def has_triplet(reldir: Path, stem: str):
    b = CORPUS / reldir
    a, n, o = (b / f"{stem}_albedo.jpg", b / f"{stem}_n.png",
               b / f"{stem}_orme.png")
    return (a, n, o) if (a.exists() and n.exists() and o.exists()) else None


# ---- pass A: content key per install DDS -----------------------------
def keyof(relstr: str):
    d = unwrap_bytes(WORLDS / relstr)
    if not d or d[:4] != b"DDS " or len(d) < 136:
        return (relstr, None)
    return (relstr, hashlib.md5(d).hexdigest())   # pristine = identical bytes


# ---- pass B: stamp one physical file with its group id ---------------
def stamp(job):
    relstr, tid = job
    src = WORLDS / relstr
    try:
        with tempfile.TemporaryDirectory() as t:
            wd = Path(t)
            sh("php", PAKD, str(src), f"{wd}/")
            raws = [p for p in wd.iterdir() if p.is_file()]
            if not raws:
                return ("DECFAIL", relstr)
            raw = raws[0]
            data = bytearray(raw.read_bytes())
            if data[:4] != b"DDS " or len(data) < 136:
                return ("NOTDDS", relstr)
            w = struct.unpack("<I", data[16:20])[0]
            h = struct.unpack("<I", data[12:16])[0]
            data[128:132] = MAGIC
            data[132:136] = struct.pack("<I", tid)
            raw.write_bytes(bytes(data))
            outd = wd / "out"
            outd.mkdir(parents=True, exist_ok=True)
            sh("php", PAKC, str(raw), str(outd))
            packed = outd / f"pak_{raw.name}"
            if not (packed.exists() and packed.stat().st_size):
                return ("PAKFAIL", relstr)
            bdst = BACKUP / relstr
            if not bdst.exists():
                bdst.parent.mkdir(parents=True, exist_ok=True)
                bdst.write_bytes(src.read_bytes())
            src.write_bytes(packed.read_bytes())
            sh("php", PAKD, str(src), f"{wd}/rt/")
            rts = [p for p in (wd / "rt").iterdir() if p.is_file()]
            vb = rts[0].read_bytes() if rts else b""
        if (len(vb) < 136 or vb[128:132] != MAGIC
                or struct.unpack("<I", vb[132:136])[0] != tid
                or struct.unpack("<I", vb[16:20])[0] != w
                or struct.unpack("<I", vb[12:16])[0] != h):
            return ("VERIFY", relstr)
        return ("OK", relstr)
    except Exception as exc:  # noqa: BLE001
        return (f"ERR:{str(exc)[:80]}", relstr)


def main() -> int:
    BACKUP.mkdir(parents=True, exist_ok=True)
    GFXPBR.mkdir(parents=True, exist_ok=True)
    # clean slate: stale .pbr from a prior run would orphan (nc!=gid) and
    # could serve outdated maps. ids are deterministic so a full rebuild
    # reproduces them exactly.
    old = list(GFXPBR.glob("*.pbr"))
    for p in old:
        p.unlink()
    print(f"cleared {len(old)} old containers")
    rels = sorted(p.relative_to(WORLDS).as_posix()
                  for p in WORLDS.rglob("pak_*.*")
                  if p.suffix.lower() in (".dds", ".bmp"))
    print(f"install textures: {len(rels)}  — pass A: content keys ...")

    groups = defaultdict(list)              # content_md5 -> [relstr,...]
    with ProcessPoolExecutor(max_workers=14) as ex:
        for rel, k in ex.map(keyof, rels, chunksize=8):
            if k:
                groups[k].append(rel)
    nonddss = len(rels) - sum(len(v) for v in groups.values())
    print(f"  DDS content groups: {len(groups)}  (skipped non-DDS/BMP: "
          f"{nonddss})")

    # one id per content group that has ≥1 corpus triplet; canonical =
    # lexicographically-smallest member with a triplet.
    jobs, index, gid = [], [], 0
    multi = sum(1 for v in groups.values() if len(v) > 1)
    for ck in sorted(groups):
        members = sorted(groups[ck])
        canon = None
        for m in members:
            mp = Path(m)
            if has_triplet(mp.parent, mp.stem):
                canon = m
                break
        if canon is None:
            continue                        # no HD anywhere -> leave pristine
        gid += 1
        a, n, o = has_triplet(Path(canon).parent, Path(canon).stem)
        ab, nb, ob = a.read_bytes(), n.read_bytes(), o.read_bytes()
        (GFXPBR / f"{gid:08x}.pbr").write_bytes(
            b"NCPBR\0" + bytes([1, 0])
            + struct.pack("<III", len(ab), len(nb), len(ob)) + ab + nb + ob)
        index.append(f"{gid:08x} {gid:08x}.pbr")
        for m in members:                   # stamp EVERY copy with group id
            jobs.append((m, gid))
    IDX.write_text("\n".join(index) + "\n")
    print(f"  content groups: {len(groups)} ({multi} multi-copy)  "
          f"-> tagged groups w/ HD: {gid}  files to stamp: {len(jobs)}")

    res = {}
    with ProcessPoolExecutor(max_workers=14) as ex:
        for i, (st, rel) in enumerate(ex.map(stamp, jobs, chunksize=8)):
            res[st] = res.get(st, 0) + 1
            if st != "OK" and res[st] <= 5:
                print(f"  {st}: {rel}")
            if i and i % 800 == 0:
                print(f"  stamp {i}/{len(jobs)} {res}")
    ok = res.get("OK", 0)
    nc = len(list(GFXPBR.glob("*.pbr")))
    print(f"\ndone: stamped OK={ok}/{len(jobs)} detail={res}")
    print(f"containers={nc}  index_groups={gid}  "
          f"{'CONSISTENT' if nc == gid else 'MISMATCH'}")
    print(f"restore: rsync -a {BACKUP}/ {WORLDS}/ ; rm {IDX}")
    return 0 if ok == len(jobs) else 1


if __name__ == "__main__":
    sys.exit(main())
