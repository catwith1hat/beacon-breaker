#!/usr/bin/env bash
# lodestar runner — invokes vitest with a per-fixture name pattern.
#
# Supports fixture categories: sanity_blocks, epoch_processing.
#
# Requires pnpm and node 24+ on PATH (or PNPM env var).
#
# Usage: ./tools/runners/lodestar.sh <fixture-dir>

set -u
FIXTURE="${1:?usage: $0 <fixture-dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/_lib.sh"

ABS="$(cd "$FIXTURE" && pwd)"
parse_fixture "$ABS" || { echo "unsupported fixture path: $ABS"; exit 2; }

# Lodestar's spec runner expects spec tests at packages/beacon-node/spec-tests/
# (per test/spec-tests-version.json's outputDirBase). Symlink whole dir.
LODESTAR_SPEC_DIR="$ROOT_DIR/vendor/lodestar/packages/beacon-node/spec-tests"
if [[ ! -e "$LODESTAR_SPEC_DIR" ]]; then
    ln -sfn "$ROOT_DIR/vendor/consensus-spec-tests" "$LODESTAR_SPEC_DIR"
fi

PNPM="${PNPM:-pnpm}"
if ! command -v "$PNPM" >/dev/null; then
    echo "pnpm not on PATH; set PNPM and PATH (node 24+)"
    exit 2
fi

case "$BB_CATEGORY" in
    sanity_blocks)
        spec_file="test/spec/presets/sanity.test.ts"
        filter="${BB_FORK}/sanity/blocks/pyspec_tests/${BB_TEST_NAME}\$"
        ;;
    epoch_processing)
        spec_file="test/spec/presets/epoch_processing.test.ts"
        filter="${BB_FORK}/epoch_processing/${BB_HELPER}/pyspec_tests/${BB_TEST_NAME}\$"
        ;;
    operations)
        spec_file="test/spec/presets/operations.test.ts"
        filter="${BB_FORK}/operations/${BB_HELPER}/pyspec_tests/${BB_TEST_NAME}\$"
        ;;
    *)
        echo "lodestar runner does not handle category: $BB_CATEGORY"; exit 2 ;;
esac

# Pick mainnet vs minimal preset.
project="spec-${BB_PRESET}"

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

( cd "$ROOT_DIR/vendor/lodestar/packages/beacon-node" && \
  "$PNPM" exec vitest run --project "$project" \
    --testNamePattern "$filter" \
    "$spec_file" 2>&1 ) > "$WORK/vitest.log"
rc=$?

# Strip ANSI color codes; extract pass count.
plain="$(sed -E 's/\x1b\[[0-9;]*m//g' "$WORK/vitest.log")"
passed=$(echo "$plain" | grep -oE 'Tests +[0-9]+ passed' | grep -oE '[0-9]+' | head -1)
if [[ $rc -eq 0 && "${passed:-0}" -gt 0 ]]; then
    echo "OK ($BB_CATEGORY/$BB_FORK${BB_HELPER:+/$BB_HELPER}/$BB_TEST_NAME — $passed passed)"
    exit 0
fi

echo "FAIL (vitest exit $rc, passed=$passed); tail:"
echo "$plain" | tail -10
exit 1
