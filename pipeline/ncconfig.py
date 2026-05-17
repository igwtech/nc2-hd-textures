"""
Central, env-driven config so anyone with a Replicate account + their
own Neocron 2 client install can reproduce the corpus. No machine paths
are baked in: every location falls back to a repo-relative default and
can be overridden by an environment variable.

  NC_GAME_DIR         Neocron 2 install root (has gfx/worlds, gfx/modeltextures)
                      default: ~/Neocron2
  NC_PAK_DECOMPRESS   path to pak_decompress.php
                      default: <repo>/pipeline/tools/pak_decompress.php
  NC_PBR_BUILD        scratch build dir (maps, logs) — git-ignored
                      default: <repo>/_build
  NC_INDEX            texture index json (txt sibling auto)
                      default: <repo>/texture_index.json
  REPLICATE_API_TOKEN required for any generation step (never commit it)
  NC_REPLICATE_ENV    optional file holding REPLICATE_API_TOKEN=...
                      default: ~/.config/neocron/replicate.env
"""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent          # <repo>/pipeline
REPO = HERE.parent                              # <repo>


def _env(k: str, d: str) -> str:
    return os.environ.get(k) or d


GAME_DIR = Path(_env("NC_GAME_DIR", str(Path.home() / "Neocron2")))
PAK_DECOMPRESS = _env("NC_PAK_DECOMPRESS",
                      str(HERE / "tools" / "pak_decompress.php"))
BUILD_DIR = Path(_env("NC_PBR_BUILD", str(REPO / "_build")))
OUT_DIR = BUILD_DIR / "output"
LOG_DIR = BUILD_DIR / "logs"
INDEX_JSON = Path(_env("NC_INDEX", str(REPO / "texture_index.json")))
MODEL_CLASS_TSV = BUILD_DIR / "modeltex_classes.tsv"


def replicate_token() -> str:
    t = os.environ.get("REPLICATE_API_TOKEN")
    if t:
        return t.strip()
    f = Path(_env("NC_REPLICATE_ENV",
                  str(Path.home() / ".config/neocron/replicate.env")))
    if f.exists():
        for ln in f.read_text().splitlines():
            if ln.startswith("REPLICATE_API_TOKEN="):
                return ln.split("=", 1)[1].strip()
    raise SystemExit(
        "No Replicate token. `export REPLICATE_API_TOKEN=r8_...` "
        "(get one at https://replicate.com/account/api-tokens)")
