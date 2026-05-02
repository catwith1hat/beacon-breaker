#!/usr/bin/env bash
# lodestar runner — lodestar has no standalone state-transition CLI; the
# spec test runner lives in packages/beacon-node/test/spec/. This invokes
# vitest with a filter scoped to the fixture's path.
#
# Requires PNPM and node 24+. Caller must export PNPM and PATH so that
# `pnpm` and a node 24 binary are on PATH.
#
# Usage: ./tools/runners/lodestar.sh <fixture-dir>

set -u
FIXTURE="${1:?usage: $0 <fixture-dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

ABS="$(cd "$FIXTURE" && pwd)"
case "$ABS" in
    *consensus-spec-tests/tests/mainnet/*/sanity/blocks/pyspec_tests/*) ;;
    *)
        echo "fixture must live under consensus-spec-tests/tests/mainnet/<fork>/sanity/blocks/pyspec_tests/<name> for lodestar"
        exit 2 ;;
esac

# Lodestar's spec runner expects spec tests at packages/beacon-node/spec-tests/
# (per test/spec-tests-version.json's outputDirBase). Symlink whole dir.
LODESTAR_SPEC_DIR="$ROOT_DIR/lodestar/packages/beacon-node/spec-tests"
if [[ ! -e "$LODESTAR_SPEC_DIR" ]]; then
    ln -sfn "$ROOT_DIR/consensus-spec-tests" "$LODESTAR_SPEC_DIR"
fi

PNPM="${PNPM:-pnpm}"
if ! command -v "$PNPM" >/dev/null; then
    echo "pnpm not on PATH; set PNPM and PATH (node 24+)"
    exit 2
fi

fork="$(echo "$ABS" | sed -E 's|.*/mainnet/([^/]+)/.*|\1|')"
test_name="$(basename "$ABS")"

# Vitest test names are like "<fork>/sanity/blocks/pyspec_tests/<test_name>".
# Use both --project (mainnet vs minimal preset) and --testNamePattern.
filter="${fork}/sanity/blocks/pyspec_tests/${test_name}\$"

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

( cd "$ROOT_DIR/lodestar/packages/beacon-node" && \
  "$PNPM" exec vitest run --project spec-mainnet \
    --testNamePattern "$filter" \
    test/spec/presets/sanity.test.ts 2>&1 ) > "$WORK/vitest.log"
rc=$?

# vitest output has ANSI color codes; strip before grepping. A run with
# 0 passing and N skipped means the filter didn't match anything.
plain="$(sed -E 's/\x1b\[[0-9;]*m//g' "$WORK/vitest.log")"
passed=$(echo "$plain" | grep -oE 'Tests +[0-9]+ passed' | grep -oE '[0-9]+' | head -1)
if [[ $rc -eq 0 && "${passed:-0}" -gt 0 ]]; then
    echo "OK (vitest: $passed passed for $filter)"
    exit 0
fi
echo "FAIL (vitest exit $rc, passed=$passed); tail:"
echo "$plain" | tail -10
exit 1
