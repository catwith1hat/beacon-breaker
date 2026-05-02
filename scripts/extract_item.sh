#!/usr/bin/env bash
# extract_item.sh — bundle an item directory as a self-contained patch /
# tarball that can be sent to a client team or pasted into a bug report.
#
# Usage:
#   scripts/extract_item.sh itemN [out-dir]
#
# Produces:
#   <out-dir>/itemN.tar.gz       — the directory contents
#   <out-dir>/itemN.diff         — git format-patch for any commit naming itemN

set -euo pipefail

ITEM="${1:?usage: $0 itemN [out-dir]}"
OUT="${2:-./out}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

ITEM_DIR="$ROOT_DIR/$ITEM"
if [[ ! -d "$ITEM_DIR" ]]; then
    echo "no such item directory: $ITEM_DIR" >&2
    exit 2
fi

mkdir -p "$OUT"

tar -czf "$OUT/$ITEM.tar.gz" -C "$ROOT_DIR" "$ITEM"
echo "wrote $OUT/$ITEM.tar.gz"

# Find any commit whose subject mentions the item; export them as a patch
# series. Best-effort — silent if no matching commits.
mapfile -t commits < <(git -C "$ROOT_DIR" log --format=%H --grep="$ITEM" 2>/dev/null || true)
if [[ ${#commits[@]} -gt 0 ]]; then
    git -C "$ROOT_DIR" format-patch --stdout "${commits[@]}" > "$OUT/$ITEM.diff"
    echo "wrote $OUT/$ITEM.diff (${#commits[@]} commit(s))"
fi
