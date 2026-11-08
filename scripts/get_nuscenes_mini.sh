#!/usr/bin/env bash
# Install nuScenes v1.0-mini and map expansion v1.3 into DEST (default /data/nuscenes).
#
# nuScenes downloads sit behind a login, so this script never logs in. The
# operator pastes the signed download links when asked, or sets NUSC_MINI_URL
# and NUSC_MAP_URL. Links are never echoed or written to disk.
#
# Usage:
#   scripts/get_nuscenes_mini.sh [DEST]
#   scripts/get_nuscenes_mini.sh --verify-only DEST   (exit 0 complete, 1 otherwise)
set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }

VERIFY_ONLY=0
if [[ "${1:-}" == "--verify-only" ]]; then
  VERIFY_ONLY=1
  shift
fi
[[ $# -le 1 ]] || die "usage: $0 [--verify-only] [DEST]"
DEST="${1:-/data/nuscenes}"

MINI_JSON=(scene sample sample_data ego_pose calibrated_sensor log map)

verify() {
  local root="$1" t d
  for t in "${MINI_JSON[@]}"; do
    [[ -s "$root/v1.0-mini/$t.json" ]] || return 1
  done
  for d in samples/LIDAR_TOP sweeps/LIDAR_TOP; do
    [[ -d "$root/$d" && -n "$(ls -A "$root/$d")" ]] || return 1
  done
  [[ -s "$root/maps/expansion/boston-seaport.json" ]] || return 1
}

if (( VERIFY_ONLY )); then
  verify "$DEST" && exit 0
  echo "nuScenes mini incomplete at $DEST" >&2
  exit 1
fi

if verify "$DEST"; then
  echo "already installed at $DEST"
  exit 0
fi

# Prompt for a link (or read it from env). Input is hidden; the value is never printed.
get_link() {
  local var="$1" label="$2" value="${!1:-}"
  if [[ -z "$value" ]]; then
    echo "Paste the signed download link for $label (input hidden), then press Enter:" >&2
    read -r -s value || { echo >&2; die "no link given for $label"; }
    echo >&2
  fi
  [[ "$value" == https://* ]] || die "$label link must start with https://"
  printf '%s' "$value"
}

MINI_URL="$(get_link NUSC_MINI_URL 'v1.0-mini.tgz')"
MAP_URL="$(get_link NUSC_MAP_URL 'map expansion v1.3 zip')"

# URL goes through curl's stdin config so it stays out of the process list.
download() {
  printf 'url = "%s"\n' "$1" | curl --fail --location --retry 3 --progress-bar --config - -o "$2" \
    || die "download failed: $3"
}

mkdir -p "$DEST"
TMP="$(mktemp -d "$DEST/.download.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

echo "Downloading v1.0-mini ..." >&2
download "$MINI_URL" "$TMP/mini.tgz" "v1.0-mini"
tar -xzf "$TMP/mini.tgz" -C "$DEST"
rm -f "$TMP/mini.tgz"

echo "Downloading map expansion v1.3 ..." >&2
download "$MAP_URL" "$TMP/map.zip" "map expansion"
mkdir -p "$DEST/maps"
unzip -q -o "$TMP/map.zip" -d "$DEST/maps"
rm -f "$TMP/map.zip"

verify "$DEST" || die "extracted files do not match the expected nuScenes mini layout under $DEST"
echo "installed nuScenes mini at $DEST"
