#!/usr/bin/env bash
# nimbus runner — uses ncli transition for one block at a time, chaining
# the output post-state into the next invocation when there are multiple
# blocks.
#
# Expects $NCLI or ./tools/runners/nimbus.bin/ncli.
#
# Usage: ./tools/runners/nimbus.sh <fixture-dir>

set -u
FIXTURE="${1:?usage: $0 <fixture-dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/_lib.sh"

ABS="$(cd "$FIXTURE" && pwd)"
parse_fixture "$ABS" || { echo "unsupported fixture path: $ABS"; exit 2; }

case "$BB_CATEGORY" in
    sanity_blocks) ;;
    epoch_processing|operations)
        # ncli transition applies a whole block; it has no per-helper /
        # per-operation hook. The relevant nim spec-test files exist
        # (tests/consensus_spec/test_fixture_state_transition_epoch.nim,
        # test_fixture_operations.nim) but no standalone binary ships.
        echo "SKIP nimbus ncli has no per-$BB_CATEGORY entrypoint"
        exit 77
        ;;
    *)
        echo "nimbus runner does not handle category: $BB_CATEGORY"; exit 2 ;;
esac

NCLI="${NCLI:-$ROOT_DIR/tools/runners/nimbus.bin/ncli}"
if [[ ! -x "$NCLI" ]]; then
    NCLI="$ROOT_DIR/vendor/nimbus/build/ncli"
fi
if [[ ! -x "$NCLI" ]]; then
    echo "ncli binary not found; build with: cd vendor/nimbus && make ncli"
    exit 2
fi

SNAPPY="$ROOT_DIR/tools/bin/snappy_codec"
NETWORK_DIR="${BB_NIMBUS_NETWORK_DIR:-$ROOT_DIR/tools/test-configs/electra-from-genesis}"

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# ncli's --verifyStateRoot uses the network's RuntimeConfig to pick the
# fork; mainnet's real Electra epoch is too large for slot-32 fixtures.
# Use the from-genesis-electra config instead.
"$SNAPPY" d "$FIXTURE/pre.ssz_snappy" "$WORK/state_in.ssz" || exit 3

state_out=""
i=0
while [[ -f "$FIXTURE/blocks_${i}.ssz_snappy" ]]; do
    "$SNAPPY" d "$FIXTURE/blocks_${i}.ssz_snappy" "$WORK/blocks_${i}.ssz" || exit 3
    state_out="$WORK/state_${i}.ssz"
    "$NCLI" transition \
        --network="$NETWORK_DIR" \
        --verifyStateRoot=true \
        "$WORK/state_in.ssz" "$WORK/blocks_${i}.ssz" "$state_out" \
        > "$WORK/ncli_${i}.log" 2>&1 || { echo "ncli block $i failed:"; tail -10 "$WORK/ncli_${i}.log"; exit 4; }
    cp "$state_out" "$WORK/state_in.ssz"
    i=$((i + 1))
done

if [[ -z "$state_out" ]]; then
    echo "no blocks found in fixture"
    exit 3
fi

expected="$("$SNAPPY" sha256 "$FIXTURE/post.ssz_snappy")"
actual="$(sha256sum "$state_out" | cut -d' ' -f1)"

if [[ "$expected" == "$actual" ]]; then
    echo "OK $actual"
    exit 0
fi
echo "FAIL expected=$expected got=$actual"
exit 1
