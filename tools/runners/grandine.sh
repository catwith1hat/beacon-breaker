#!/usr/bin/env bash
# grandine runner — grandine has no standalone CLI for state transitions,
# but its consensus-spec-tests runner is wired via the test_resources
# macro on `consensus-spec-tests/tests/...` paths relative to the
# grandine workspace root.
#
# This runner derives the pyspec_tests subdirectory name from the fixture
# path, then invokes `cargo test` with a filter so only that test runs.
# It assumes ./grandine/consensus-spec-tests is symlinked to the repo's
# consensus-spec-tests submodule (done by setup).
#
# A single-fixture invocation re-uses cargo's built test binary, so each
# call after the first compile is fast.
#
# Usage: ./tools/runners/grandine.sh <fixture-dir>

set -u
FIXTURE="${1:?usage: $0 <fixture-dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

ABS="$(cd "$FIXTURE" && pwd)"
case "$ABS" in
    *consensus-spec-tests/tests/mainnet/*/sanity/blocks/pyspec_tests/*) ;;
    *)
        echo "fixture must live under consensus-spec-tests/tests/mainnet/<fork>/sanity/blocks/pyspec_tests/<name> for grandine"
        exit 2 ;;
esac

# Extract <fork> and <test-name> from the absolute path.
fork="$(echo "$ABS" | sed -E 's|.*/mainnet/([^/]+)/.*|\1|')"
test_name="$(basename "$ABS")"
fn="${fork}_mainnet_sanity"

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# Locate the most recently built transition_functions test binary. Cargo
# names it transition_functions-<hash>; pick the newest non-.d file.
TEST_BIN="${GRANDINE_TEST_BIN:-}"
if [[ -z "$TEST_BIN" ]]; then
    TEST_BIN="$(ls -t /tmp/grandine-target/release/deps/transition_functions-* 2>/dev/null | grep -v '\.d$' | head -1)"
fi
if [[ -z "$TEST_BIN" || ! -x "$TEST_BIN" ]]; then
    echo "grandine test binary not found; build with:"
    echo "  cd grandine && CARGO_TARGET_DIR=/tmp/grandine-target cargo test -p transition_functions --release --features bls/blst --no-run"
    exit 2
fi

# Test names are derived from the directory path; use the test_name as a
# substring filter. Grandine's --exact flag wants the full name; substring
# match (default) is safer.
"$TEST_BIN" "${test_name}" > "$WORK/run.log" 2>&1
rc=$?

if grep -qE "_${test_name} \.\.\. ok\$" "$WORK/run.log"; then
    echo "OK (${fn}/${test_name})"
    exit 0
elif grep -qE "_${test_name} \.\.\. FAILED\$" "$WORK/run.log"; then
    echo "FAIL (${fn}/${test_name})"
    tail -20 "$WORK/run.log"
    exit 1
elif [[ $rc -ne 0 ]]; then
    echo "test binary exited $rc; tail:"
    tail -10 "$WORK/run.log"
    exit 4
else
    echo "no matching test for ${test_name}; tail:"
    tail -10 "$WORK/run.log"
    exit 5
fi
