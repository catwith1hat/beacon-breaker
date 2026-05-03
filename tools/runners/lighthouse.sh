#!/usr/bin/env bash
# lighthouse runner.
#
# - sanity_blocks: uses `lcli transition-blocks` chained per block,
#   compares sha256 of the SSZ-encoded post-state.
# - epoch_processing: uses the compiled `ef_tests` test binary (built
#   with `--features ef_tests`). Lighthouse's ef_tests groups all
#   fixtures of a helper into a single Rust test function, so the
#   verdict here is "the whole helper's tests passed", not per-fixture.
#   PASS implies our specific fixture is among them.
#
# Usage: ./tools/runners/lighthouse.sh <fixture-dir>

set -u
FIXTURE="${1:?usage: $0 <fixture-dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/_lib.sh"

ABS="$(cd "$FIXTURE" && pwd)"
parse_fixture "$ABS" || { echo "unsupported fixture path: $ABS"; exit 2; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

case "$BB_CATEGORY" in
    sanity_blocks)
        LCLI="${LCLI:-$ROOT_DIR/tools/runners/lighthouse.bin/lcli}"
        if [[ ! -x "$LCLI" ]]; then
            LCLI="${LCLI_ALT:-/tmp/lighthouse-target/release/lcli}"
        fi
        if [[ ! -x "$LCLI" ]]; then
            echo "lcli binary not found; build with: cd lighthouse && PATH=tools/cc-shim:\$PATH CARGO_TARGET_DIR=/tmp/lighthouse-target cargo build --release --bin lcli"
            exit 2
        fi

        SNAPPY="$ROOT_DIR/tools/bin/snappy_codec"
        TESTNET_DIR="${BB_LIGHTHOUSE_TESTNET_DIR:-$ROOT_DIR/tools/test-configs/electra-from-genesis}"

        "$SNAPPY" d "$FIXTURE/pre.ssz_snappy" "$WORK/state_in.ssz" || { echo "snappy decompress pre failed"; exit 3; }

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
        ;;

    epoch_processing|operations)
        TEST_BIN="${LIGHTHOUSE_EF_TESTS_BIN:-}"
        if [[ -z "$TEST_BIN" ]]; then
            # The integration-test binary lives at deps/tests-<hash>, not
            # ef_tests-<hash> (that's the lib unittest binary; empty).
            TEST_BIN="$(ls -t /tmp/lighthouse-target/release/deps/tests-* 2>/dev/null | grep -v '\.d$' | head -1)"
        fi
        if [[ -z "$TEST_BIN" || ! -x "$TEST_BIN" ]]; then
            echo "lighthouse ef_tests binary not found; build with:"
            echo "  cd lighthouse && PATH=tools/cc-shim:\$PATH CARGO_TARGET_DIR=/tmp/lighthouse-target cargo test -p ef_tests --release --features ef_tests --no-run"
            exit 2
        fi

        # Lighthouse groups all fixtures of a helper under one test fn;
        # we can't filter to a single fixture. Run the whole helper and
        # treat PASS as "our fixture is among the passing ones".
        case "$BB_CATEGORY" in
            epoch_processing)
                # Lighthouse retains the pre-rename name `pending_balance_deposits`
                # for what the spec / EF dirs now call `pending_deposits`.
                case "$BB_HELPER" in
                    pending_deposits) test_fn=epoch_processing_pending_balance_deposits ;;
                    *) test_fn="epoch_processing_${BB_HELPER}" ;;
                esac
                ;;
            operations)
                # Lighthouse operations test names diverge from EF dir names.
                case "$BB_HELPER" in
                    consolidation_request)       test_fn=operations_consolidations ;;
                    withdrawal_request|execution_layer_withdrawals) test_fn=operations_withdrawal_reqeusts ;;
                    deposit_request|deposit_requests)               test_fn=operations_deposit_requests ;;
                    bls_to_execution_change)     test_fn=operations_bls_to_execution_change ;;
                    voluntary_exit)              test_fn=operations_exit ;;
                    # execution_payload tests split into _full (non-blinded) and _blinded
                    # variants in lighthouse; the EF fixture corpus is the _full variant.
                    execution_payload)           test_fn=operations_execution_payload_full ;;
                    *)                           test_fn="operations_${BB_HELPER}" ;;
                esac
                ;;
        esac

        "$TEST_BIN" --exact "$test_fn" --test-threads=4 > "$WORK/run.log" 2>&1
        rc=$?

        if [[ $rc -eq 0 ]] && grep -qE "test ${test_fn} \.\.\. ok\$" "$WORK/run.log"; then
            echo "OK (lighthouse ef_tests::${test_fn} — covers all fixtures incl. ${BB_TEST_NAME})"
            exit 0
        fi

        echo "FAIL (ef_tests exit $rc); tail:"
        tail -20 "$WORK/run.log"
        exit 1
        ;;

    *)
        echo "lighthouse runner does not handle category: $BB_CATEGORY"; exit 2 ;;
esac
