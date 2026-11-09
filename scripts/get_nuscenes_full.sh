#!/usr/bin/env bash
# Download the full nuScenes release into NUSC_ROOT (default /data/nuscenes),
# one archive at a time: download (resumable) -> extract -> delete archive ->
# mark done. Re-running skips archives already marked done.
#
# Usage:
#   scripts/get_nuscenes_full.sh URL_LIST
#
# URL_LIST is a text file with one signed download URL per line. Keep it out of
# git. URLs are never echoed or written to disk by this script; only archive
# file names (query strings removed) appear in the log.
#
# Environment:
#   NUSC_ROOT          extraction root (default /data/nuscenes)
#   NUSC_ARCHIVES      staging dir for archives and done markers (default /data/nuscenes-archives)
#   NUSC_MIN_FREE_GB   stop when free space on the root drive drops below this (default 120)
#
# Extraction uses only the Python standard library (zipfile, tarfile) and tar,
# because the box has no unzip or bzip2.
set -uo pipefail

die() { echo "error: $*" >&2; exit 1; }

[[ $# -eq 1 ]] || die "usage: $0 URL_LIST"
LIST="$1"
[[ -f "$LIST" && -r "$LIST" ]] || die "URL list not found or not readable: $LIST"

ROOT="${NUSC_ROOT:-/data/nuscenes}"
ARC="${NUSC_ARCHIVES:-/data/nuscenes-archives}"
MIN_FREE_GB="${NUSC_MIN_FREE_GB:-120}"
mkdir -p "$ROOT" "$ARC/done"

# Panoptic archives unpack into nuScenes-panoptic-v1.0-<set>/. Move the parts
# into the standard layout: panoptic/<version>/ and <version>/panoptic.json.
merge_panoptic() {
  local src vdir ver v name
  for src in "$ROOT"/nuScenes-panoptic-v1.0-*/; do
    [[ -d "$src" ]] || continue
    for v in "$src"/panoptic/*/; do
      [[ -d "$v" ]] || continue
      name=$(basename "$v")
      mkdir -p "$ROOT/panoptic/$name"
      find "$v" -mindepth 1 -maxdepth 1 -exec mv -f {} "$ROOT/panoptic/$name/" \;
    done
    for vdir in "$src"/v1.0-*/; do
      [[ -d "$vdir" ]] || continue
      ver=$(basename "$vdir")
      if [[ -f "$vdir/panoptic.json" ]]; then
        mkdir -p "$ROOT/$ver"
        mv -f "$vdir/panoptic.json" "$ROOT/$ver/panoptic.json"
      fi
      # The leftover category.json must match the lidarseg copy. Do not discard a different file.
      if [[ -f "$vdir/category.json" && -f "$ROOT/$ver/category.json" ]]; then
        cmp -s "$vdir/category.json" "$ROOT/$ver/category.json" \
          || die "leftover $ver/category.json differs from lidarseg copy; kept $src"
      fi
    done
    rm -rf "$src"
    echo "merged panoptic archive into $ROOT"
  done
}

extract() { # extract ARCHIVE_PATH FILE_NAME
  local path="$1" f="$2"
  case "$f" in
    *.zip)
      if [[ "$f" == *map-expansion* ]]; then
        python3 -I -m zipfile -e "$path" "$ROOT/maps"
      else
        python3 -I -m zipfile -e "$path" "$ROOT"
      fi ;;
    *.tar.bz2)
      python3 -I -c "import sys, tarfile; tarfile.open(sys.argv[1], 'r:bz2').extractall(sys.argv[2], filter='data')" \
        "$path" "$ROOT" ;;
    *.tgz|*.tar.gz)
      tar -xzf "$path" -C "$ROOT" ;;
    *)
      echo "unknown archive type: $f" >&2
      return 1 ;;
  esac
}

while IFS= read -r url || [[ -n "$url" ]]; do
  [[ -z "$url" || "$url" == \#* ]] && continue
  # Drop the query string (it holds the signature) before taking the file name.
  f=$(basename "${url%%\?*}")
  [[ -e "$ARC/done/$f" ]] && { echo "skip $f (done)"; continue; }

  free=$(df --output=avail -BG "$ROOT" | tail -1 | tr -dc 0-9)
  [[ "$free" -lt "$MIN_FREE_GB" ]] && { echo "STOP: only ${free}G free on $ROOT"; exit 2; }

  echo "$(date '+%F %T') download $f"
  # The URL goes to curl through a config on stdin, so it stays out of the process list.
  until printf 'url = "%s"\n' "$url" \
      | curl -fL -sS -C - --retry 20 --retry-delay 15 --retry-all-errors --config - -o "$ARC/$f"; do
    echo "retry $f"; sleep 30
  done

  echo "$(date '+%F %T') extract $f ($(du -h "$ARC/$f" | cut -f1))"
  extract "$ARC/$f" "$f" || { echo "EXTRACT FAILED $f"; exit 3; }
  merge_panoptic || { echo "MERGE FAILED $f"; exit 3; }

  rm -f "$ARC/$f"
  touch "$ARC/done/$f"
  echo "$(date '+%F %T') done $f"
done < "$LIST"

echo "ALL DONE"
du -sh "$ROOT"
