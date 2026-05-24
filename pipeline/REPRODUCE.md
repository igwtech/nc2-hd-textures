# Reproducing the Neocron 2 PBR texture remaster

Everything that turns the stock 2004 textures into the creative-remaster
+ PBR corpus and the **embedded-ID deployment** consumed by
**neocron-renodx-engine**. With your own Neocron 2 client install (and a
Replicate account *only if you want to regenerate the AI corpus*) you
can reproduce the whole thing from scratch.

No secrets, no machine paths — every location is an environment variable
with a repo-relative default (`ncconfig.py`). These scripts are
**tools to reproduce the result**, not part of the launcher (the
launcher only installs & runs the shipped addon).

---

## What it produces

1. A per-texture **triplet** under `$NC_PBR_BUILD/output/...`:

   | file | what |
   |---|---|
   | `*_albedo.jpg` | clarity-upscaler creative regen, guided by the original |
   | `*_n.png` | Marigold surface normals |
   | `*_orme.png` | RGBA: **R**=occlusion **G**=roughness **B**=metallic **A**=non-emissive (**inverted** v0.12 — A=0 means 100% emissive; most surfaces are non-emis so A=1 keeps PNGs visually opaque) |

2. The **deployment** the engine actually reads (in the game install):
   - every vanilla `pak_*.dds` that has a triplet is stamped with a
     32-bit **id** in mip-0 block-0 (`NCID` + id LE);
   - one **container** per id: `$NC_HD_CORPUS/<id8hex>.pbr` =
     `"NCPBR\0"` + ver + 3×u32 LE lengths + albedo + normal + orme;
   - `$NC_ID_INDEX` (`<id8hex> <relpath>` per line) the engine loads.

   The id is keyed on **vanilla content** (not path): all byte-identical
   copies of a texture across zones share one id → one container → the
   same HD everywhere.

---

## Prerequisites

- **Neocron 2 client install** — the loose `gfx/worlds` &
  `gfx/modeltextures` `pak_*` envelopes. Not redistributed here.
- `php` (PAK unwrap/repack), `imagemagick` (`magick`), `python3`.
- **Replicate** account + token — *only for step 1/2* (regenerating the
  AI corpus). The shipped corpus is a release artifact; to just redeploy
  it, skip to step 3. Models used: `philz1337x/clarity-upscaler`,
  `jasonod888/marigold-normals-intrinsics`,
  `tommoore515/pix2pix_tf_albedo2pbrmaps`.

## Setup

```bash
cd pipeline
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

export NC_GAME_DIR=/path/to/Neocron2          # default: ~/Neocron2
export REPLICATE_API_TOKEN=r8_xxxx            # only for step 1/2
# optional: export NC_PBR_BUILD=/big/disk/_build   (default: <repo>/_build)
```

`ncconfig.py` env overrides: `NC_GAME_DIR`, `NC_PAK_DECOMPRESS`,
`NC_PAK_COMPRESS`, `NC_PBR_BUILD`, `NC_INDEX`, `NC_HD_CORPUS`,
`NC_ID_INDEX`, `NC_VANILLA512_BAK`, `NC_IDTAG_BAK`,
`REPLICATE_API_TOKEN`, `NC_REPLICATE_ENV`.

---

## Pipeline

### 1. Generate the world corpus  *(Replicate, resumable)*
```bash
python pbr_pipeline.py --source "$NC_GAME_DIR/gfx/worlds" --jobs 5
```
Routing is automatic: tiling/seamless materials regen with
`pattern=True` (stay seamless); UV atlases regen structure-locked. A
texture whose `_orme.png` already exists is skipped.

### 2. Generate the model corpus  *(Replicate)*
```bash
python classify_models.py     # -> _build/modeltex_classes.tsv (subject)
python pbr_pipeline.py --source "$NC_GAME_DIR/gfx/modeltextures" \
                       --out "$NC_PBR_BUILD/output/modeltextures" --jobs 5
```

### 3. Pre-shrink vanilla to ≤512  *(local, reversible)*
```bash
bash rescale512.sh --all
```
The NC2 engine clamps >512 textures at load. Shrinking the vanilla so
the engine loads it AS-IS makes the offline view == the runtime view,
which the embedded-ID stamp depends on (block-0 must not be
clamp-resampled). Backs originals up to `$NC_VANILLA512_BAK`.
Restore: `rsync -a "$NC_VANILLA512_BAK/" "$NC_GAME_DIR/gfx/worlds/"`.

### 4. Shrink the map corpus to ≤512  *(local)*
```bash
python maps_to_512.py
```
1024 maps are wasted (engine ceiling is 512). RGBA `_orme.png` is
**band-split** before resize — PIL premultiplies alpha otherwise and
zeroes RGB where emissive(A)==0. Do not "simplify" that.

### 5. ORME occlusion policy  *(local, $0)*
```bash
python recover_orme.py        # only if some O came out ~0: recompute
                              # exact M/A from albedo, neutral O/R
python recover_ao_local.py    # O = 1.0 flat for ALL world ORME
python preserve_magenta.py    # re-imprint vanilla's magenta key into HD
```
**Why flat O:** NC2 floor/walls/ceiling are *tiling*, not UV-mapped. A
per-tile baked AO repeats and slides with the camera ("ORME jumping").
The real AO for tiling geometry is in the game **lightmaps**, which the
substituted `world.ps` already consumes as irradiance. So O is
neutralised; the normal map supplies relief, roughness/metallic/emissive
are kept. Per-tile AO only makes sense for genuine UV/atlas props.

**Magenta-key transparency:** NC2 vanilla (esp. BMPs without real alpha)
uses pure magenta `(255,0,255)` as Doom-style binary transparency. The
shader `clip()`s magenta pixels (with JPG-q92 tolerance). Because
clarity doesn't preserve magenta, `preserve_magenta.py` scans the
pristine ≤512 vanilla (`$NC_IDTAG_BAK`) for the key and re-paints it
into the HD albedo. Idempotent; only touches textures that had a key.

### 6. Deploy: embedded-ID stamp + containers  *(local, reversible)*
```bash
# prereq: install must be pristine ≤512
rsync -a "$NC_IDTAG_BAK/" "$NC_GAME_DIR/gfx/worlds/" 2>/dev/null || true
python mass_idtag.py
```
Content-keyed: one id per unique vanilla content, all copies stamped
with it, one canonical container from the corpus triplet. Writes
`$NC_ID_INDEX`, verifies every file's pak round-trip. Deterministic
(sorted content keys) → reproducible. Restore:
`rsync -a "$NC_IDTAG_BAK/" "$NC_GAME_DIR/gfx/worlds/" ; rm "$NC_ID_INDEX"`.

> `build_pbr_index.py` / `merge_index.py` build the **legacy
> content-hash** index (`texture_index.txt`). Superseded by the
> embedded-ID scheme (immune to clamp / re-encode / dup-collision) but
> kept as a documented fallback for the pre-ID engine path.
> `repatch_metallic.py` / `repatch_emissive.py` rewrite a single ORME
> channel in place from the existing maps (free, no Replicate).

---

## Cost

clarity (~$0.013) + Marigold (~$0.013) + pix2pix (~$0.003) ≈
**~$0.03 / texture**. World (~3.5k) + models (~1k) ≈ **$120–150**.
Steps 3–6 are **free and local**. Steps 1–2 are resumable, so a crash
only re-costs in-flight textures.

## Design rationale (so a fork can reason about changes)

- **Embedded ID, not a content hash.** We control the deployed vanilla
  file, so we stamp a unique id and read it back exactly via LockRect —
  immune to the >512 clamp, DXT re-encode nondeterminism, and the
  byte-identical-duplicate hash collisions that plagued the hash scheme.
- **Content-keyed id.** A per-physical-file id made clarity-divergent
  duplicates (`global/pak_X` vs `metal/pak_X`) show different HD per
  zone. Keying on vanilla content collapses all copies to one container.
- **Zero visual cost.** A tagged texture is always HD-replaced at s0, so
  the stomped 4×4 corner is never displayed.
- **Flat O for tiling world.** See step 5 — the lightmap is the AO.
- **Albedo JPG q92**, normal/orme PNG: ~5× smaller corpus, fits
  release-asset limits; `stbi_load` reads JPG with no engine change.
- **UV atlases not pixel-decomposed**: class-constant metal/roughness,
  real per-pixel AO (valid on an unwrap).
- The engine binds HD albedo **s0** (bypasses the native clamp — only
  the addon can), normals **s2**, ORME **s3**, PBR-lite over the baked
  lightmap.

*(Architecture validated in-game 2026-05-17. The one-off prototype that
proved id-survival + container load before the mass rollout is not
vendored — it served its purpose; `mass_idtag.py` is the reproduction
step.)*
