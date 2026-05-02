#!/usr/bin/env bash
# teku runner — uses `teku transition blocks` on a fixture.
#
# Expects teku CLI on PATH or at $TEKU.
# Compares sha256 of the SSZ-encoded post-state.
#
# Usage: ./tools/runners/teku.sh <fixture-dir>

set -u
FIXTURE="${1:?usage: $0 <fixture-dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/_lib.sh"

ABS="$(cd "$FIXTURE" && pwd)"
parse_fixture "$ABS" || { echo "unsupported fixture path: $ABS"; exit 2; }

case "$BB_CATEGORY" in
    sanity_blocks) ;;
    epoch_processing)
        # `teku transition` only supports `blocks` and `slots`; there is
        # no per-helper subcommand. Running the gradle reference-test
        # suite with a filter is possible but slow (~30s per invocation).
        # For now, SKIP and let the harness aggregate from the other 5.
        echo "SKIP teku does not support per-helper epoch_processing without gradle"
        exit 77
        ;;
    *)
        echo "teku runner does not handle category: $BB_CATEGORY"; exit 2 ;;
esac

TEKU="${TEKU:-$ROOT_DIR/teku/build/install/teku/bin/teku}"
if [[ ! -x "$TEKU" ]]; then
    echo "teku binary not found; build with: cd teku && ./gradlew installDist"
    exit 2
fi

SNAPPY="$ROOT_DIR/tools/bin/snappy_codec"

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

"$SNAPPY" d "$FIXTURE/pre.ssz_snappy" "$WORK/pre.ssz" || exit 3

block_paths=()
i=0
while [[ -f "$FIXTURE/blocks_${i}.ssz_snappy" ]]; do
    "$SNAPPY" d "$FIXTURE/blocks_${i}.ssz_snappy" "$WORK/blocks_${i}.ssz" || exit 3
    block_paths+=("$WORK/blocks_${i}.ssz")
    i=$((i + 1))
done

# pyspec EF state-transition fixtures are generated as if the named fork
# is active at slot 0. Mainnet's real fork epochs would put a slot-32
# pre-state in Phase0; we feed teku a custom config with all forks up to
# the target activated at epoch 0.
NETWORK_CONFIG="${BB_NETWORK_CONFIG:-$ROOT_DIR/tools/test-configs/mainnet-electra-from-genesis.yaml}"

"$TEKU" transition blocks \
    --network "$NETWORK_CONFIG" \
    --pre "$WORK/pre.ssz" \
    --post "$WORK/post.ssz" \
    "${block_paths[@]}" \
    > "$WORK/teku.log" 2>&1 || { echo "teku failed:"; tail -10 "$WORK/teku.log"; exit 4; }

expected="$("$SNAPPY" sha256 "$FIXTURE/post.ssz_snappy")"
actual="$(sha256sum "$WORK/post.ssz" | cut -d' ' -f1)"

if [[ "$expected" == "$actual" ]]; then
    echo "OK $actual"
    exit 0
fi
echo "FAIL expected=$expected got=$actual"
exit 1
