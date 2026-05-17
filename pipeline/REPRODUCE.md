# Reproducing the Neocron 2 PBR texture corpus

Everything that turns the stock 2004 textures into the
creative-remaster + ORME corpus consumed by **neocron-renodx-engine**.
With a Replicate account and your own Neocron 2 client install you can
regenerate the entire thing from scratch.

Nothing here contains secrets or machine-specific paths — every
location is an environment variable with a sensible default
(`ncconfig.py`).

## What it produces

For every world / model texture, three sibling files keyed by a hash of
the *vanilla* texture the engine sees at runtime:

| file            | what                                                   |
|-----------------|--------------------------------------------------------|
| `*_albedo.jpg`  | clarity-upscaler creative regen, guided by the original|
| `*_n.png`       | Marigold surface normals                               |
| `*_orme.png`    | RGBA: **R**=occlusion **G**=roughness **B**=metallic **A**=emissive |

plus `texture_index.txt` (`<hash> albedo normal orme` per line).

## Prerequisites

- A **Replicate** account + API token (https://replicate.com/account/api-tokens).
  The pipeline calls three public models:
  `philz1337x/clarity-upscaler`, `jasonod888/marigold-normals-intrinsics`,
  `tommoore515/pix2pix_tf_albedo2pbrmaps`.
- Your **Neocron 2 client install** (the loose `gfx/` tree with the
  `pak_*.dds` / `pak_*.bmp` envelopes). Not redistributed here.
- `php` (PAK unwrap), `imagemagick` (`magick`), `python3`.

## Setup

```bash
cd pipeline
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

export REPLICATE_API_TOKEN=r8_xxxxxxxx          # required
export NC_GAME_DIR=/path/to/Neocron2            # default: ~/Neocron2
# optional: export NC_PBR_BUILD=/big/disk/_build  (default: <repo>/_build)
```

`ncconfig.py` env overrides: `NC_GAME_DIR`, `NC_PAK_DECOMPRESS`,
`NC_PBR_BUILD`, `NC_INDEX`, `REPLICATE_API_TOKEN`, `NC_REPLICATE_ENV`.

## Run

**1. World materials** — process per category (resumable; a texture whose
`_orme.png` exists is skipped):

```bash
python pbr_pipeline.py --source "$NC_GAME_DIR/gfx/worlds" --only "worlds/global/" --jobs 5
python pbr_pipeline.py --source "$NC_GAME_DIR/gfx/worlds" --only "worlds/metal/"  --jobs 5
# ... or no --only for the whole tree
```

Routing is automatic: a tile/seamless material is regenerated with
`pattern=True` (stays seamless); a UV atlas is regenerated
structure-locked (UV survives) and gets a neutral ORME.

**2. Model textures** (NPCs / mutants / power armor — UV atlases). First
classify them by subject, then run; the pipeline reads the manifest and
applies the per-class ORME profile (skin/cloth/mutant/powerarmor/robot):

```bash
python classify_models.py            # -> _build/modeltex_classes.tsv (100% cov)
python pbr_pipeline.py --source "$NC_GAME_DIR/gfx/modeltextures" \
                       --out "$NC_PBR_BUILD/output/modeltextures" --jobs 5
```

**3. Build the index** (key = hash of the vanilla install texture; only
complete triplets are emitted):

```bash
python build_pbr_index.py            # -> ../texture_index.{txt,json}
```

**4. (optional) Free in-place tweaks** — no Replicate cost; rewrite just
one ORME channel from the existing maps:

```bash
python repatch_metallic.py           # category-aware metallic (metal/ folder -> M0.80)
python repatch_emissive.py           # luminance emissive for lights/, recompute A
```

**5. Package** for the launcher (per-category tarballs < 2 GB):

```bash
bash make_release.sh                 # -> _build/release/pbr-*.tar.gz
# then: gh release create ... ; ship texture_index.txt as
#       neocron_texture_index.txt ; add a fetch entry to ../addon.json
```

## Cost

clarity (~$0.013) + Marigold normals (~$0.013) + pix2pix AO/rough
(~$0.003) ≈ **~$0.03 / texture**, JPG-q92 albedo. Full world (~3.5k) +
modeltextures (~1k) ≈ **$120–150**. Resumable, so a crash/reboot only
re-costs in-flight textures.

## Why these choices (so a fork can reason about changes)

- **Hash = crc32(first 64 KiB of the raw DXT bytes) | w<<16 | h.** The
  engine LockRect-hashes the vanilla texture the game binds; DXT is
  stored as linear block-rows with no row padding, so the offline-tight
  bytes equal the runtime pitch and the hashes match. Genuine
  collisions (different textures, same hash) are *poisoned* (dropped →
  stay vanilla, never get the wrong HD swap).
- **Albedo is JPG q92**, normal/orme are PNG. Albedo tolerates it
  (negligible loss) and it shrinks the corpus ~5× so per-category
  release tarballs fit GitHub's 2 GB/asset limit. `stbi_load` in the
  engine reads JPG transparently — no engine change.
- **UV atlases are not pixel-decomposed.** Single-image svBRDF on an
  unwrap produces garbage at seams, so model-texture metal/roughness are
  *class constants* (subject-classified) while AO stays real per-pixel.
- The engine binds HD albedo at **s0** (bypasses the native 512 px
  clamp — only the addon path can), normals **s2**, ORME **s3**, and
  applies PBR-lite on the game's baked lightmap.
