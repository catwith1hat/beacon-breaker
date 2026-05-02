#!/usr/bin/env bash
# grandine runner — invokes the compiled `transition_functions` test
# binary directly with a substring filter that matches the fixture's
# directory path.
#
# Supports fixture categories: sanity_blocks, epoch_processing.
#
# Usage: ./tools/runners/grandine.sh <fixture-dir>

set -u
FIXTURE="${1:?usage: $0 <fixture-dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/_lib.sh"

ABS="$(cd "$FIXTURE" && pwd)"
parse_fixture "$ABS" || { echo "unsupported fixture path: $ABS"; exit 2; }

# Locate the most recently built transition_functions test binary.
TEST_BIN="${GRANDINE_TEST_BIN:-}"
if [[ -z "$TEST_BIN" ]]; then
    TEST_BIN="$(ls -t /tmp/grandine-target/release/deps/transition_functions-* 2>/dev/null | grep -v '\.d$' | head -1)"
fi
if [[ -z "$TEST_BIN" || ! -x "$TEST_BIN" ]]; then
    echo "grandine test binary not found; build with:"
    echo "  cd grandine && CARGO_TARGET_DIR=/tmp/grandine-target cargo test -p transition_functions --release --features bls/blst --no-run"
    exit 2
fi

# Grandine's test names embed the full fixture path. The unique tail is
# the test_name, so we filter on a unique substring.
case "$BB_CATEGORY" in
    sanity_blocks)
        # e.g. electra::block_processing::spec_tests::electra_mainnet_sanity_..._<test_name>
        # The test_name suffix is unique enough.
        filter="_${BB_FORK}_${BB_PRESET}_sanity_.*_${BB_TEST_NAME}\$"
        ;;
    epoch_processing)
        # e.g. electra::epoch_processing::spec_tests::mainnet_<helper>_..._<test_name>
        filter="${BB_PRESET}_${BB_HELPER}_.*_${BB_TEST_NAME}\$"
        ;;
    *)
        echo "grandine runner does not handle category: $BB_CATEGORY"; exit 2 ;;
esac

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# Cargo's test binary takes a substring filter as positional arg; the
# regex flavor isn't supported, so collapse to a literal substring. The
# `${BB_TEST_NAME}` alone is usually unique enough across the fork.
"$TEST_BIN" "${BB_TEST_NAME}" > "$WORK/run.log" 2>&1
rc=$?

# Look for the specific test that matched our category + fork.
case "$BB_CATEGORY" in
    sanity_blocks)
        match_re="${BB_FORK}::block_processing::.*_${BB_TEST_NAME} \.\.\. ok\$"
        fail_re="${BB_FORK}::block_processing::.*_${BB_TEST_NAME} \.\.\. FAILED\$"
        ;;
    epoch_processing)
        match_re="${BB_FORK}::epoch_processing::.*_${BB_TEST_NAME} \.\.\. ok\$"
        fail_re="${BB_FORK}::epoch_processing::.*_${BB_TEST_NAME} \.\.\. FAILED\$"
        ;;
esac

if grep -qE "$match_re" "$WORK/run.log"; then
    echo "OK ($BB_CATEGORY/$BB_FORK${BB_HELPER:+/$BB_HELPER}/$BB_TEST_NAME)"
    exit 0
elif grep -qE "$fail_re" "$WORK/run.log"; then
    echo "FAIL ($BB_FORK::$BB_CATEGORY/$BB_TEST_NAME)"
    tail -20 "$WORK/run.log"
    exit 1
elif [[ $rc -ne 0 ]]; then
    echo "test binary exited $rc; tail:"
    tail -10 "$WORK/run.log"
    exit 4
else
    echo "no matching test for $BB_TEST_NAME in $BB_CATEGORY/$BB_FORK; tail:"
    tail -10 "$WORK/run.log"
    exit 5
fi
