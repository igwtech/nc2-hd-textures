#!/usr/bin/env bash
# Stage 3 — pre-shrink vanilla world textures to <=512 so the NC2 engine
# loads them AS-IS (no >512 runtime clamp). This makes the offline view
# of a texture == what the engine sees at runtime, which the embedded-ID
# scheme (mass_idtag.py) also depends on (block-0 must not be resampled
# by the clamp). Only files whose decoded mip-0 max dim is >512 are
# touched; <=512 left byte-identical. Reversible:
#     rsync -a "$BACKUP/" "$WORLDS/"
#
# Round-trip is deterministic: pak_<stem> -unwrap-> <stem> -resize512->
# <stem> -repack-> pak_<stem>. FourCC preserved (DXT1->DXT1 else DXT5;
# BMP stays BMP). Local, parallel, idempotent. Needs ImageMagick + php.
#
# Env (same defaults as ncconfig.py):
#   NC_GAME_DIR        default ~/Neocron2
#   NC_VANILLA512_BAK  default $NC_GAME_DIR/_vanilla512_backup
#   NC_PAK_DECOMPRESS  default <pipeline>/tools/pak_decompress.php
#   NC_PAK_COMPRESS    default <pipeline>/tools/pak_compress.php
#   NC_PBR_BUILD       default <repo>/_build   (log dir)
#
# Usage:
#   rescale512.sh DIR [DIR...]     # only these worlds/ subdirs (pilot)
#   rescale512.sh --all            # every worlds/ subdir (mass)
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # <repo>/pipeline
REPO="$(dirname "$HERE")"
GAME_DIR="${NC_GAME_DIR:-$HOME/Neocron2}"
WORLDS="$GAME_DIR/gfx/worlds"
BACKUP="${NC_VANILLA512_BAK:-$GAME_DIR/_vanilla512_backup}"
PAKD="${NC_PAK_DECOMPRESS:-$HERE/tools/pak_decompress.php}"
PAKC="${NC_PAK_COMPRESS:-$HERE/tools/pak_compress.php}"
BUILD="${NC_PBR_BUILD:-$REPO/_build}"
JOBS="${NC_JOBS:-16}"
LOG="$BUILD/rescale512.log"
mkdir -p "$BUILD"

if [ "${1:-}" = "--all" ]; then
  mapfile -t TARGETS < <(find "$WORLDS" -mindepth 1 -maxdepth 1 -type d)
else
  [ $# -ge 1 ] || { echo "usage: $0 DIR... | --all"; exit 2; }
  TARGETS=(); for d in "$@"; do TARGETS+=("$WORLDS/$d"); done
fi
mkdir -p "$BACKUP"

# one-texture worker; arg: <abs path to loose pak_*.{dds,bmp}>
shrink_one() {
  local src="$1"
  local rel="${src#$WORLDS/}"
  local wd; wd="$(mktemp -d)"
  trap 'rm -rf "$wd"' RETURN

  php "$PAKD" "$src" "$wd/" >/dev/null 2>&1 || { echo "DECFAIL $rel"; return; }
  local raw; raw="$(find "$wd" -maxdepth 1 -type f | head -1)"
  [ -n "$raw" ] || { echo "DECFAIL $rel"; return; }

  read -r W H FCC < <(python3 - "$raw" <<'PY'
import sys,struct
d=open(sys.argv[1],'rb').read(128)
if d[:4]==b'DDS ':
    h=struct.unpack('<I',d[12:16])[0]; w=struct.unpack('<I',d[16:20])[0]
    fl=struct.unpack('<I',d[80:84])[0]; fc=d[84:88] if fl&4 else b''
    print(w,h,fc.decode('latin1').strip() or 'RAW')
elif d[:2]==b'BM':
    w=struct.unpack('<I',d[18:22])[0]
    h=abs(struct.unpack('<i',d[22:26])[0]); print(w,h,'BMP')
else: print(0,0,'?')
PY
)
  [ "${W:-0}" -gt 0 ] 2>/dev/null || { echo "PARSEFAIL $rel"; return; }
  if [ "$W" -le 512 ] && [ "$H" -le 512 ]; then echo "SKIP<=512 $rel"; return; fi

  local tw th
  if [ "$W" -ge "$H" ]; then tw=512; th=$(( (H*512/W +2)/4*4 ));
  else th=512; tw=$(( (W*512/H +2)/4*4 )); fi
  [ "$tw" -lt 4 ] && tw=4; [ "$th" -lt 4 ] && th=4

  local stem ext out enc
  stem="$(basename "$raw")"; ext="${stem##*.}"
  out="$wd/out"; mkdir -p "$out"
  if [ "$ext" = "bmp" ]; then
    magick "$raw" -filter Lanczos -resize "${tw}x${th}!" "$wd/$stem" 2>/dev/null \
      || { echo "MAGICKFAIL $rel"; return; }
  else
    case "$FCC" in DXT1) enc=dxt1;; *) enc=dxt5;; esac
    magick "$raw" -filter Lanczos -resize "${tw}x${th}!" \
      -define dds:compression=$enc -define dds:mipmaps=0 "$wd/$stem" 2>/dev/null \
      || { echo "MAGICKFAIL $rel"; return; }
  fi

  php "$PAKC" "$wd/$stem" "$out" >/dev/null 2>&1 || { echo "PAKFAIL $rel"; return; }
  local packed="$out/pak_$stem"
  [ -s "$packed" ] || { echo "PAKFAIL $rel"; return; }

  local bdst="$BACKUP/$rel"
  if [ ! -f "$bdst" ]; then mkdir -p "$(dirname "$bdst")"; /bin/cp -f "$src" "$bdst"; fi
  /bin/cp -f "$packed" "$src"
  echo "OK ${W}x${H}->${tw}x${th} $enc $rel"
}
export -f shrink_one
export WORLDS BACKUP PAKD PAKC

echo "scanning ${#TARGETS[@]} dir(s) ..."
find "${TARGETS[@]}" -type f \( -name 'pak_*.dds' -o -name 'pak_*.bmp' \) -print0 \
 | xargs -0 -P "$JOBS" -n 1 bash -c 'shrink_one "$0"' \
 | tee "$LOG" \
 | awk '{c[$1]++} END{for(k in c)printf "  %-12s %d\n",k,c[k]}'
echo "log: $LOG"
echo "restore (if needed): rsync -a \"$BACKUP/\" \"$WORLDS/\""
