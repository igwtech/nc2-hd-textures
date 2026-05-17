#!/usr/bin/env bash
# Build per-category PBR corpus tarballs from $NC_PBR_BUILD/output.
# Tar roots are `worlds/<cat>/...` (or `modeltextures/<sub>/...`) so the
# launcher, extracting into `gfx_pbr/`, yields the exact path the engine
# resolves. Albedo is JPG so each tarball stays < 2 GB (GitHub limit);
# normal/orme are lossless PNG. Local + safe — the `gh release` upload
# is printed, not run (it is large + outward + on your repo).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${NC_PBR_BUILD:-$(cd "$HERE/.." && pwd)/_build}/output"
REL="${NC_PBR_BUILD:-$(cd "$HERE/.." && pwd)/_build}/release"
mkdir -p "$REL"

[ -d "$OUT" ] || { echo "no output dir: $OUT (run pbr_pipeline.py first)"; exit 1; }

for top in "$OUT"/*/; do
  top="${top%/}"; tname="$(basename "$top")"   # worlds | modeltextures
  for cat in "$top"/*/; do
    cat="${cat%/}"; c="$(basename "$cat")"
    ls "$cat"/*_orme.png >/dev/null 2>&1 || continue
    t="$REL/pbr-$tname-$c.tar.gz"
    tar czf "$t" -C "$OUT" "$tname/$c"
    printf "  %-32s %6s  (%d tex)\n" "$(basename "$t")" \
      "$(du -h "$t" | cut -f1)" \
      "$(find "$cat" -name '*_orme.png' | wc -l)"
    sz=$(stat -c%s "$t")
    [ "$sz" -ge 2147483648 ] && echo "  !! $(basename "$t") >= 2GB — split needed"
  done
done

echo
echo "artefacts -> $REL"
echo "upload (needs gh auth; large/outward — run when ready):"
echo "  gh release create vX.Y.Z -R <owner>/nc2-hd-textures \\"
echo "    --title '...' --notes '...' $REL/pbr-*.tar.gz"
echo "  # commit texture_index.{txt,json} + addon.json (add a fetch entry per new category)"
