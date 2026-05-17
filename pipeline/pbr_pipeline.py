#!/usr/bin/env python3
"""
Neocron 2 world-texture PBR pipeline (Tier 3.5).

For each tiling world material:
  - Marigold (jasonod888/marigold-normals-intrinsics):
        task=normals               -> tangent-ish surface normals  -> <name>_n.png
        task=intrinsics albedo     -> de-lit base colour            -> <name>_albedo.png
  - pix2pix (tommoore515/pix2pix_tf_albedo2pbrmaps), on the DE-LIT albedo:
        albedo2smoothness          -> roughness = 1 - smoothness
        albedo2height -> height2ao -> ambient occlusion
  - local heuristics:
        metallic   = filename class (NC2 world is overwhelmingly non-metal)
        emissive   = HSV neon detector on de-lit albedo (cyberpunk signage)
  - pack ORME RGBA8: R=Occlusion G=Roughness B=Metallic A=Emissive -> <name>_orme.png

UV-mapped / atlas textures are NOT run through the material decomposition
(single-image svBRDF on an atlas = garbage at seams). They get Marigold
normals + de-lit albedo only, a neutral ORME, and a review flag.

Resumable: a texture whose <name>_orme.png already exists is skipped.
Every Replicate prediction's billed predict_time is logged to cost.jsonl.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import requests
from PIL import Image

# ---------------------------------------------------------------- config ---

CLARITY_VERSION = "dfad41707589d68ecdccd1dfa600d55a208f9310748e44bfe35b4a6291453d5e"
MARIGOLD_VERSION = "088703f47e2d92b7ce09b9831839aa4ed2c4f1751ab6aa6cdd174dae382a67b1"
PIX2PIX_VERSION = "21bd96b6e69f40e54502d67798f9025ab9e4a9e08f2a1b51dde5131b129a825e"

# clarity creative-regen routing (decided 2026-05-15: "reimaginado moderado")
CLARITY_ROUTE = {
    "tile": dict(pattern=True,  creativity=0.50, resemblance=0.70),
    "uv":   dict(pattern=False, creativity=0.35, resemblance=1.00),
}
SCALE_FACTOR = 2
# hard resolution cap (decided 2026-05-15: RX480 8GB VRAM / disk).
# clarity regenerates detail at high res; we downsample to RES_CAP so the
# creative detail is supersampled (crisp) while Marigold/pix2pix/runtime
# all stay sane. Source is pre-shrunk to <=CLARITY_IN so x2 ~= RES_CAP
# (also keeps Replicate predict_time — hence cost — near estimate).
RES_CAP = 1024
CLARITY_IN = 512

# path-segment -> material prompt hint (steers the regen toward the
# right surface; keeps material identity while adding detail)
CATEGORY_PROMPT = {
    "bricks": "weathered brick wall, mortar lines",
    "metal": "scratched industrial metal panel, worn paint",
    "cement&concrete": "rough concrete, hairline cracks, stains",
    "tiles": "ceramic floor tiles, grout, scuffs",
    "doors": "heavy industrial door, panel seams, rivets",
    "windows": "grimy window frame, glass, dirt",
    "lights": "neon light fixture, emissive signage",
    "global": "cyberpunk building surface, grime",
    "natural": "natural rock and dirt ground",
    "objects": "sci-fi prop surface, painted metal",
    "hacknet": "abstract digital cyberspace surface, glow",
    "transparent": "decal sheet, alpha cutout",
}

# modeltexture subject -> ORME profile (confirmed 2026-05-16). These
# are UV atlases, so metal/rough are class CONSTANTS (per-texel svBRDF
# unreliable on an unwrap); AO is still real per-pixel pix2pix; emissive
# only where it makes sense. classify_models.py writes the rel->class
# manifest; the tile/uv classifier still drives clarity (uv = UV-locked).
MODEL_ORME = {
    "skin":       dict(metal=0.0,  rough=0.45, emis=False),
    "cloth":      dict(metal=0.0,  rough=0.85, emis=False),
    "mutant":     dict(metal=0.0,  rough=0.80, emis=True),
    "powerarmor": dict(metal=0.75, rough=0.35, emis=True),
    "robot":      dict(metal=0.85, rough=0.30, emis=True),
    "object":     None,   # fall back to filename heuristic + pix2pix
}
import ncconfig
MODEL_CLASS_TSV = ncconfig.MODEL_CLASS_TSV
_model_class: dict[str, str] = {}


def load_model_classes() -> None:
    if MODEL_CLASS_TSV.exists():
        for ln in MODEL_CLASS_TSV.read_text().splitlines():
            if "\t" in ln:
                rel, c = ln.split("\t", 1)
                _model_class[rel] = c.strip()


API = "https://api.replicate.com/v1/predictions"

# Filenames hinting at metal — NC2 world art convention. Conservative: only
# obvious metal reads as metallic; everything else is dielectric (M=0).
METAL_RE = re.compile(
    r"(metal|steel|chrome|iron|grate|grati|pipe|rust|alu|tin|brass|"
    r"vent|duct|plate|panel|hangar|tank|reactor|machin|gird)",
    re.I,
)

_token: str | None = None
_cost_lock = threading.Lock()


def load_token() -> str:
    global _token
    if _token is None:
        _token = ncconfig.replicate_token()
    return _token


# ----------------------------------------------------------- image utils ---

PAK_DECOMPRESS = ncconfig.PAK_DECOMPRESS


def decode_to_rgb(src: Path) -> Image.Image:
    """
    Neocron textures are a proprietary PAK envelope (custom header +
    zlib) wrapping a real DDS/BMP. Unwrap with pak_decompress.php, then
    decode with ImageMagick. Falls back to a direct decode if the file
    is already a raw DDS/BMP/PNG.
    """
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as wd:
        unwrapped = None
        try:
            subprocess.run(["php", PAK_DECOMPRESS, str(src), f"{wd}/"],
                            capture_output=True, timeout=60, check=True)
            cands = sorted(Path(wd).glob("*.*"))
            unwrapped = cands[0] if cands else None
        except Exception:  # noqa: BLE001 — fall back to raw decode
            unwrapped = None
        raw = str(unwrapped) if unwrapped else f"{src}[0]"
        out = subprocess.run(["magick", raw, "-depth", "8", "png:-"],
                             capture_output=True)
        if out.returncode != 0:
            raise RuntimeError(
                f"magick decode failed: {out.stderr[:200]!r}")
        return Image.open(io.BytesIO(out.stdout)).convert("RGBA")


def to_data_uri(img: Image.Image, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, fmt)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/{fmt.lower()};base64,{b64}"


def is_pow2(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def classify(img: Image.Image) -> tuple[str, dict]:
    """
    'tile'  -> seamless material, safe for single-image svBRDF
    'uv'    -> atlas / UV-unwrapped, decomposition unreliable

    Heuristics: pow2 dims, alpha coverage, and wrap continuity
    (left|right column + top|bottom row mean abs diff, normalised).
    """
    rgba = np.asarray(img.convert("RGBA"), dtype=np.float32)
    h, w = rgba.shape[:2]
    rgb = rgba[..., :3] / 255.0
    a = rgba[..., 3] / 255.0

    transparent_frac = float((a < 0.5).mean())
    pow2 = is_pow2(w) and is_pow2(h)

    seam_lr = float(np.abs(rgb[:, 0, :] - rgb[:, -1, :]).mean())
    seam_tb = float(np.abs(rgb[0, :, :] - rgb[-1, :, :]).mean())
    wrap = (seam_lr + seam_tb) / 2.0  # 0 = perfectly tiling

    metrics = dict(w=w, h=h, pow2=pow2,
                   transparent_frac=round(transparent_frac, 3),
                   wrap=round(wrap, 4))

    if transparent_frac > 0.15:
        return "uv", metrics            # big cut-outs => atlas / decal sheet
    if not pow2:
        return "uv", metrics            # non-pow2 => almost never a tiler
    if wrap > 0.18:
        return "uv", metrics            # edges don't meet => not seamless
    return "tile", metrics


# -------------------------------------------------------- replicate call ---

class RateLimited(Exception):
    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"429 (retry_after={retry_after}s)")


# Global creation pacer. The account's create-prediction bucket is tight
# (observed ratelimit-reset≈10s, remaining→0 fast); 8 workers POSTing
# freely => 429 storm. One shared monotonic gate paces ALL threads and a
# 429 shoves the gate forward so every worker backs off together (no
# thundering herd). Tunable via PBR_POST_INTERVAL (default 2.0s ≈30/min).
MIN_POST_INTERVAL = float(os.environ.get("PBR_POST_INTERVAL", "2.0"))
RL_BUDGET_SEC = 1800.0          # keep riding out 429s for up to 30 min
_pace_lock = threading.Lock()
_next_post_ok = [0.0]


def _pace() -> None:
    with _pace_lock:
        now = time.monotonic()
        wait = max(0.0, _next_post_ok[0] - now)
        _next_post_ok[0] = max(now, _next_post_ok[0]) + MIN_POST_INTERVAL
    if wait:
        time.sleep(wait)


def _defer_all(seconds: float) -> None:
    """A 429 happened — push the shared gate so all workers wait."""
    with _pace_lock:
        _next_post_ok[0] = max(_next_post_ok[0],
                               time.monotonic() + seconds)


def _post_prediction(version: str, inputs: dict) -> dict:
    hdr = {"Authorization": f"Bearer {load_token()}",
           "Content-Type": "application/json"}
    _pace()
    r = requests.post(API, headers=hdr,
                       json={"version": version, "input": inputs}, timeout=60)
    if r.status_code == 429:
        ra = r.headers.get("Retry-After")
        raise RateLimited(float(ra) if ra and ra.replace(".", "").isdigit()
                          else 15.0)
    r.raise_for_status()
    return r.json()


def replicate_run(version: str, inputs: dict, cost_log: Path,
                  tag: str, max_retries: int = 5) -> list[str]:
    """
    Run a prediction to completion; return output URL list. Logs cost.
    429s do NOT consume the error budget — they're paced out for up to
    RL_BUDGET_SEC so a texture is never lost to rate limiting.
    """
    hdr = {"Authorization": f"Bearer {load_token()}"}
    last_err = None
    err_left = max_retries
    rl_deadline = time.monotonic() + RL_BUDGET_SEC
    while True:
        try:
            pred = _post_prediction(version, inputs)
            pid = pred["id"]
            get_url = pred["urls"]["get"]
            while pred["status"] not in ("succeeded", "failed", "canceled"):
                time.sleep(2.0)
                pred = requests.get(get_url, headers=hdr, timeout=60).json()
            if pred["status"] != "succeeded":
                raise RuntimeError(f"{tag} {pid} {pred['status']}: "
                                   f"{str(pred.get('error'))[:160]}")
            metrics = pred.get("metrics") or {}
            with _cost_lock:
                with cost_log.open("a") as f:
                    f.write(json.dumps({
                        "t": time.time(), "tag": tag, "id": pid,
                        "predict_time": metrics.get("predict_time"),
                        "version": version[:12],
                    }) + "\n")
            out = pred["output"]
            return out if isinstance(out, list) else [out]
        except RateLimited as e:
            last_err = e
            if time.monotonic() > rl_deadline:
                raise RuntimeError(f"{tag}: 429 budget exhausted") from e
            _defer_all(e.retry_after + MIN_POST_INTERVAL)
            time.sleep(e.retry_after)
        except Exception as e:  # noqa: BLE001 — network/model flake
            last_err = e
            err_left -= 1
            if err_left <= 0:
                raise RuntimeError(f"{tag}: exhausted retries: {last_err}")
            time.sleep(2 ** (max_retries - err_left) * 2)


def fetch_image(url: str) -> Image.Image:
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            return Image.open(io.BytesIO(r.content))
        except Exception:  # noqa: BLE001
            time.sleep(2 ** attempt)
    raise RuntimeError(f"download failed: {url}")


# ---------------------------------------------------- per-map generation ---

def marigold(task: str, img: Image.Image, cost_log: Path,
             which: str = "all") -> Image.Image:
    inp = {"task": task, "image": to_data_uri(img), "num_inference_steps": 4}
    if task == "intrinsics":
        inp["which_intrinsics"] = which
    urls = replicate_run(MARIGOLD_VERSION, inp, cost_log, f"marigold:{task}")
    return fetch_image(urls[0])


def pix2pix(model: str, img: Image.Image, cost_log: Path) -> Image.Image:
    inp = {"model": model, "imagepath": to_data_uri(img)}
    urls = replicate_run(PIX2PIX_VERSION, inp, cost_log, f"pix2pix:{model}")
    return fetch_image(urls[0])


def category_prompt(rel: Path) -> str:
    segs = {s.lower() for s in rel.parts}
    for key, hint in CATEGORY_PROMPT.items():
        if key in segs:
            return hint
    return "cyberpunk game surface, fine detail"


def clarity(img: Image.Image, kind: str, rel: Path,
            cost_log: Path) -> Image.Image:
    """
    Creative regen guided by the original. Routed by the tile/uv
    classifier so tiling materials stay seamless (pattern=True) and
    UV/atlas sheets stay structurally locked (high resemblance).
    """
    r = CLARITY_ROUTE[kind]
    hint = category_prompt(rel)
    # shrink guide so clarity x2 lands near RES_CAP (caps compute/cost)
    g = img
    if max(g.size) > CLARITY_IN:
        g = g.copy()
        g.thumbnail((CLARITY_IN, CLARITY_IN), Image.LANCZOS)
    inp = {
        "image": to_data_uri(g),
        "prompt": f"{hint}, seamless texture, high detail, "
                  f"PBR albedo, masterpiece, best quality",
        "negative_prompt": "blurry, low quality, watermark, text, "
                           "lighting, shadows, baked AO",
        "creativity": r["creativity"],
        "resemblance": r["resemblance"],
        "pattern": r["pattern"],
        "scale_factor": SCALE_FACTOR,
        "dynamic": 6,
        "num_inference_steps": 18,
        "output_format": "png",
    }
    urls = replicate_run(CLARITY_VERSION, inp, cost_log,
                         f"clarity:{kind}")
    return fetch_image(urls[0]).convert("RGB")


LIGHT_RE = re.compile(r"(light|lamp|neon|glow|lumin|fluor|bulb|led|"
                      r"emiss|signlit|backlit)", re.I)


def _smoothstep(lo: float, hi: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def emissive_mask(albedo: Image.Image, rel: "Path | None" = None
                  ) -> np.ndarray:
    """
    Category-aware self-illumination on the regen albedo. Returns
    float32 [0,1] HxW.

    - light fixtures (`lights/` folder or light/neon/lamp name): NC2
      luminaries are bright but often DESATURATED (white/pale/cyan
      panels). QA on the `lights` batch showed the saturation-gated
      detector missed 46/57. Use a luminance ramp so the lit panel
      glows and the dark housing (`_bg`/`_side`) stays 0; a saturation
      bonus still lifts coloured neon.
    - everything else: the conservative saturation×value neon detector
      (so bright walls/signs elsewhere don't all glow).
    """
    rgb = np.asarray(albedo.convert("RGB"), dtype=np.float32) / 255.0
    hsv = np.asarray(albedo.convert("HSV"), dtype=np.float32) / 255.0
    s, v = hsv[..., 1], hsv[..., 2]

    is_light = False
    if rel is not None:
        parts = {p.lower() for p in rel.parts}
        is_light = "lights" in parts or bool(LIGHT_RE.search(rel.name))

    if is_light:
        lum = (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1]
               + 0.0722 * rgb[..., 2])
        base = _smoothstep(0.55, 0.85, lum)          # bright = emissive
        sat_boost = 1.0 + 0.6 * np.clip(s, 0, 1)     # neon a bit hotter
        return np.clip(base * sat_boost, 0, 1).astype(np.float32)

    raw = np.clip((s - 0.45) / 0.55, 0, 1) * np.clip((v - 0.55) / 0.45, 0, 1)
    return (raw ** 1.5).astype(np.float32)


# surfaces that are NOT metal even inside a metal folder / metal name
NONMETAL_RE = re.compile(
    r"(glass|window|decal|sign|holo|screen|cloth|fabric|rubber|wood|"
    r"concret|cement|brick|stone|dirt|sand|paper|plastic|leather|"
    r"neon|light|grass|water|liquid|ice)",
    re.I,
)


def metallic_value(rel: "Path") -> float:
    """
    Category-aware. The `metal/` folder IS the metal-materials bucket —
    default it metallic regardless of filename (the name regex missed
    ~75%: outmet/horizo/slots/met_*). Other folders fall back to the
    filename heuristic. NONMETAL names always win (painted-over,
    glass/decal/rubber trims, etc.).
    """
    name = rel.name.lower()
    parts = {p.lower() for p in rel.parts}
    if NONMETAL_RE.search(name):
        return 0.0
    if "metal" in parts:
        return 0.80
    return 0.85 if METAL_RE.search(name) else 0.0


def pack_orme(occ: np.ndarray, rough: np.ndarray,
              metal: float, emis: np.ndarray, size: tuple[int, int]) -> Image.Image:
    w, h = size

    def fit(a: np.ndarray) -> np.ndarray:
        im = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
        return np.asarray(im.resize((w, h), Image.BILINEAR),
                          dtype=np.float32) / 255.0

    o = fit(occ) if occ.ndim == 2 else fit(occ[..., 0])
    r = fit(rough) if rough.ndim == 2 else fit(rough[..., 0])
    e = fit(emis) if emis.ndim == 2 else fit(emis[..., 0])
    m = np.full((h, w), np.clip(metal, 0, 1), np.float32)
    rgba = np.stack([o, r, m, e], axis=-1)
    return Image.fromarray((rgba * 255).astype(np.uint8), "RGBA")


def gray(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.float32) / 255.0


# ----------------------------------------------------------- driver ---

def process_one(src: Path, src_root: Path, out_root: Path,
                 cost_log: Path) -> str:
    rel = src.relative_to(src_root)
    stem = rel.with_suffix("")
    out_dir = out_root / stem.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    orme_path = out_dir / f"{stem.name}_orme.png"
    if orme_path.exists():
        return f"skip   {rel}"

    orig = decode_to_rgb(src)
    kind, metrics = classify(orig)

    # 1. creative HD regen guided by the 2004 original (the shipped
    #    albedo / s0 payload). Routed so tile stays seamless, uv locked.
    hd = clarity(orig.convert("RGB"), kind, rel, cost_log)
    if max(hd.size) > RES_CAP:           # supersample -> crisp at cap
        hd.thumbnail((RES_CAP, RES_CAP), Image.LANCZOS)
    w, h = hd.size
    # JPG q92: albedo tolerates it (negligible loss), cuts the corpus
    # ~5x so per-category release tarballs fit GitHub's 2GB/file limit.
    # normal/orme stay PNG (lossless — JPG would corrupt vectors/masks).
    hd.save(out_dir / f"{stem.name}_albedo.jpg", quality=92,
            subsampling=0)

    # 2. normals from the regenerated HD (Marigold, high quality)
    normals = marigold("normals", hd, cost_log).convert("RGB")
    normals.resize((w, h), Image.BILINEAR).save(
        out_dir / f"{stem.name}_n.png")

    emis = emissive_mask(hd, rel)
    metal = metallic_value(rel)

    mcls = _model_class.get(str(rel))
    prof = MODEL_ORME.get(mcls) if mcls else None
    if mcls and (prof is not None or mcls in MODEL_ORME):
        # subject-informed ORME for a UV model atlas. metal/rough from
        # the class; AO is real per-pixel (valid on an atlas); emissive
        # only for classes that have it.
        if prof is None:                       # "object" -> heuristic
            prof = dict(metal=metallic_value(rel), rough=0.6, emis=True)
        metal = prof["metal"]
        if not prof["emis"]:
            emis = np.zeros((h, w), np.float32)
        height = pix2pix("albedo2height", hd, cost_log)
        ao = pix2pix("height2ao", height.convert("RGB"), cost_log)
        occ = gray(ao)
        rough = np.full((h, w), prof["rough"], np.float32)
        kind = mcls                            # manifest/log clarity
    elif kind == "tile":
        smooth = pix2pix("albedo2smoothness", hd, cost_log)
        height = pix2pix("albedo2height", hd, cost_log)
        ao = pix2pix("height2ao", height.convert("RGB"), cost_log)
        rough = 1.0 - gray(smooth)
        occ = gray(ao)
    else:
        # atlas with no class -> neutral, flagged
        rough = np.full((h, w), 0.6, np.float32)
        occ = np.ones((h, w), np.float32)

    pack_orme(occ, rough, metal, emis, (w, h)).save(orme_path)

    rec = dict(rel=str(rel), kind=kind, metal=metal, **metrics)
    with _cost_lock:
        with (out_root / "manifest.jsonl").open("a") as f:
            f.write(json.dumps(rec) + "\n")
    return f"{kind:4s}  {rel}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source",
                    default=str(ncconfig.GAME_DIR / "gfx" / "worlds"),
                    help="vanilla texture dir (e.g. $NC_GAME_DIR/gfx/worlds "
                         "or .../gfx/modeltextures)")
    ap.add_argument("--out",
                    default=str(ncconfig.OUT_DIR / "worlds"))
    ap.add_argument("--cost-log",
                    default=str(ncconfig.LOG_DIR / "cost.jsonl"))
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0,
                    help="process only first N (smoke test)")
    ap.add_argument("--only", default="",
                    help="substring filter on path (e.g. brick)")
    args = ap.parse_args()
    load_model_classes()

    src_root = Path(args.source).resolve()
    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    cost_log = Path(args.cost_log).resolve()
    cost_log.parent.mkdir(parents=True, exist_ok=True)

    srcs = sorted(p for p in src_root.rglob("*")
                  if p.suffix.lower() in (".dds", ".bmp", ".png"))
    if args.only:
        srcs = [p for p in srcs if args.only.lower() in str(p).lower()]
    if args.limit:
        srcs = srcs[:args.limit]
    print(f"{len(srcs)} textures -> {out_root} (jobs={args.jobs})", flush=True)

    done = err = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(process_one, s, src_root, out_root, cost_log): s
                for s in srcs}
        for fut in as_completed(futs):
            try:
                print(fut.result(), flush=True)
                done += 1
            except Exception as e:  # noqa: BLE001
                err += 1
                print(f"ERR   {futs[fut].relative_to(src_root)}: "
                      f"{str(e)[:200]}", flush=True)
    print(f"\ndone={done} err={err}", flush=True)


if __name__ == "__main__":
    main()
