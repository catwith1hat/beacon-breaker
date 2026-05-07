#!/usr/bin/env bash
# prysm runner — uses `go test` with a spoofed bazel runfiles tree.
#
# Prysm's spec test loaders call `bazel.Runfile("tests/<config>/<fork>/...")`
# from rules_go's bazel package. Without bazel, that lookup fails. Instead
# of building bazel-backed tests (which hits zig/protoc/sandbox issues),
# create a minimal RUNFILES_DIR/<workspace>/tests/ symlink farm and let
# Runfile resolve via env vars.
#
# Supports fixture categories: sanity_blocks, epoch_processing.
#
# Usage: ./tools/runners/prysm.sh <fixture-dir>

set -u
FIXTURE="${1:?usage: $0 <fixture-dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/_lib.sh"

ABS="$(cd "$FIXTURE" && pwd)"
parse_fixture "$ABS" || { echo "unsupported fixture path: $ABS"; exit 2; }

# Spoofed runfiles tree (created once, reused).
RUNFILES_DIR="${BB_PRYSM_RUNFILES_DIR:-/tmp/prysm-runfiles}"
mkdir -p "$RUNFILES_DIR/__main__"
[[ -e "$RUNFILES_DIR/__main__/tests" ]] || \
    ln -sfn "$ROOT_DIR/vendor/consensus-spec-tests/tests" "$RUNFILES_DIR/__main__/tests"

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# Build the Go test name. Prysm test naming has historical inconsistencies
# (most use the capitalized fork like `Electra`, but a few use lowercase).
# Use a regex that accepts either.
fork_cap="$(capitalize "$BB_FORK")"
case "$BB_CATEGORY" in
    sanity_blocks)
        test_re="^TestMainnet_${fork_cap}_Sanity_Blocks\$/^${BB_TEST_NAME}\$"
        ;;
    epoch_processing)
        helper_camel="$(snake_to_camel "$BB_HELPER")"
        test_re="^TestMainnet_(${fork_cap}|${BB_FORK})_EpochProcessing_${helper_camel}\$/^${BB_TEST_NAME}\$"
        ;;
    operations)
        # Prysm's operation test names sometimes drop suffixes
        # (consolidation_request -> Consolidation, execution_layer_withdrawals
        # -> WithdrawalRequest). Use a per-op map; fall back to CamelCase.
        case "$BB_HELPER" in
            consolidation_request) op_camel=Consolidation ;;
            execution_layer_withdrawals|withdrawal_request) op_camel=WithdrawalRequest ;;
            deposit_request|deposit_requests) op_camel=DepositRequests ;;
            *) op_camel="$(snake_to_camel "$BB_HELPER")" ;;
        esac
        test_re="^TestMainnet_${fork_cap}_Operations_${op_camel}\$/^${BB_TEST_NAME}\$"
        ;;
    *)
        echo "prysm runner does not handle category: $BB_CATEGORY"; exit 2 ;;
esac

( cd "$ROOT_DIR/prysm" && \
  RUNFILES_DIR="$RUNFILES_DIR" TEST_WORKSPACE=__main__ \
  go test -count=1 -timeout 180s \
    -run "$test_re" \
    ./testing/spectest/mainnet/ 2>&1 ) > "$WORK/gotest.log"
rc=$?

if [[ $rc -eq 0 ]] && grep -q '^ok\b' "$WORK/gotest.log"; then
    echo "OK ($BB_CATEGORY/$BB_FORK${BB_HELPER:+/$BB_HELPER}/$BB_TEST_NAME)"
    exit 0
fi

echo "FAIL (go test exit $rc); tail:"
tail -15 "$WORK/gotest.log"
exit 1
