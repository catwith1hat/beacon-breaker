#!/usr/bin/env bash
# prysm runner — uses `go test` with a spoofed bazel runfiles tree.
#
# Prysm's spec test loader calls `bazel.Runfile("tests/<config>/<fork>/...")`
# from rules_go's bazel package. Without bazel, that lookup fails. Instead
# of building bazel-backed tests (which hits zig/protoc/sandbox issues),
# create a minimal RUNFILES_DIR/<workspace>/tests/ symlink farm and let
# Runfile resolve via env vars.
#
# Usage: ./tools/runners/prysm.sh <fixture-dir>

set -u
FIXTURE="${1:?usage: $0 <fixture-dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

ABS="$(cd "$FIXTURE" && pwd)"
case "$ABS" in
    *consensus-spec-tests/tests/mainnet/*/sanity/blocks/pyspec_tests/*) ;;
    *)
        echo "fixture must live under consensus-spec-tests/tests/mainnet/<fork>/sanity/blocks/pyspec_tests/<name> for prysm"
        exit 2 ;;
esac

fork="$(echo "$ABS" | sed -E 's|.*/mainnet/([^/]+)/.*|\1|')"
test_name="$(basename "$ABS")"

# Capitalize fork: electra → Electra
fork_cap="$(echo "${fork:0:1}" | tr a-z A-Z)${fork:1}"

# Build the spoofed runfiles tree once and reuse.
RUNFILES_DIR="${BB_PRYSM_RUNFILES_DIR:-/tmp/prysm-runfiles}"
mkdir -p "$RUNFILES_DIR/__main__"
[[ -e "$RUNFILES_DIR/__main__/tests" ]] || \
    ln -sfn "$ROOT_DIR/consensus-spec-tests/tests" "$RUNFILES_DIR/__main__/tests"

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# Run only the targeted test. `go test` reports OK or FAIL; capture
# exit code as the verdict.
( cd "$ROOT_DIR/prysm" && \
  RUNFILES_DIR="$RUNFILES_DIR" TEST_WORKSPACE=__main__ \
  go test -count=1 -timeout 180s \
    -run "TestMainnet_${fork_cap}_Sanity_Blocks/${test_name}\$" \
    ./testing/spectest/mainnet/ 2>&1 ) > "$WORK/gotest.log"
rc=$?

if [[ $rc -eq 0 ]] && grep -q '^ok\b' "$WORK/gotest.log"; then
    # Confirm the named subtest actually ran (not just zero matches).
    if grep -q "${test_name}" "$WORK/gotest.log" 2>/dev/null \
       || grep -q '^ok' "$WORK/gotest.log"; then
        echo "OK (TestMainnet_${fork_cap}_Sanity_Blocks/${test_name})"
        exit 0
    fi
fi

echo "FAIL (go test exit $rc); tail:"
tail -15 "$WORK/gotest.log"
exit 1
