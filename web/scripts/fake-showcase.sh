#!/usr/bin/env bash
# Build the synthetic showcase bundle and copy it into web/public/showcase/.
# The bundle is generated, never committed (web/public/showcase is in .gitignore).
set -euo pipefail

WEB_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="$(cd "$WEB_DIR/.." && pwd)"
OUT="$(mktemp -d "${TMPDIR:-/tmp}/twin-fake-run.XXXXXX")"

(cd "$REPO_DIR" && uv run twin fake-run --out "$OUT")

rm -rf "$WEB_DIR/public/showcase"
mkdir -p "$WEB_DIR/public"
cp -R "$OUT/showcase" "$WEB_DIR/public/showcase"
echo "Showcase copied to $WEB_DIR/public/showcase (from $OUT)"
