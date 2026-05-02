#!/usr/bin/env bash
# lighthouse runner — uses lcli transition-blocks to run a fixture.
#
# Expects ./tools/runners/lighthouse.bin/lcli to exist (or LCLI env var).
# Outputs the post-state to /tmp and compares its sha256 against the
# fixture's post.ssz_snappy.
#
# Usage: ./tools/runners/lighthouse.sh <fixture-dir>

set -u
FIXTURE="${1:?usage: $0 <fixture-dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

LCLI="${LCLI:-$ROOT_DIR/tools/runners/lighthouse.bin/lcli}"
if [[ ! -x "$LCLI" ]]; then
    LCLI="${LCLI_ALT:-/tmp/lighthouse-target/release/lcli}"
fi
if [[ ! -x "$LCLI" ]]; then
    echo "lcli binary not found; build with: cd lighthouse && CARGO_TARGET_DIR=/tmp/lighthouse-target cargo build --release --bin lcli"
    exit 2
fi

SNAPPY="$ROOT_DIR/tools/bin/snappy_codec"
# Same fork-from-genesis config as teku/nimbus.
TESTNET_DIR="${BB_LIGHTHOUSE_TESTNET_DIR:-$ROOT_DIR/tools/test-configs/electra-from-genesis}"

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

"$SNAPPY" d "$FIXTURE/pre.ssz_snappy" "$WORK/state_in.ssz" || { echo "snappy decompress pre failed"; exit 3; }

# lcli's transition-blocks only accepts a single --block-path; chain
# invocations for multi-block fixtures.
state_out=""
i=0
while [[ -f "$FIXTURE/blocks_${i}.ssz_snappy" ]]; do
    "$SNAPPY" d "$FIXTURE/blocks_${i}.ssz_snappy" "$WORK/blocks_${i}.ssz" || { echo "snappy decompress block $i failed"; exit 3; }
    state_out="$WORK/state_${i}.ssz"
    "$LCLI" --testnet-dir "$TESTNET_DIR" transition-blocks \
        --pre-state-path "$WORK/state_in.ssz" \
        --block-path "$WORK/blocks_${i}.ssz" \
        --post-state-output-path "$state_out" \
        > "$WORK/lcli_${i}.log" 2>&1 || { echo "lcli block $i failed:"; tail -10 "$WORK/lcli_${i}.log"; exit 4; }
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
