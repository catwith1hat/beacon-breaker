# Item #23 reproducer — runs the actual nimbus `get_pending_balance_to_withdraw`
# function against a synthetic Gloas BeaconState and asserts the divergence
# from the spec.
#
# HOW TO RUN
#
# This file is structured as a drop-in nimbus test. Two options:
#
# Option A — copy + nim c (recommended):
#
#   cp items/023/demo/test_item_23_repro.nim vendor/nimbus/tests/
#   cd vendor/nimbus
#   nim c -r -d:const_preset=mainnet tests/test_item_23_repro.nim
#
# (The nimbus repo's config.nims wires up the --path: flags for all the
# vendored deps automatically once you compile from the repo root.)
#
# Option B — run as a standalone test alongside the existing nimbus suite:
#
#   cp items/023/demo/test_item_23_repro.nim vendor/nimbus/tests/
#   cd vendor/nimbus
#   nim c -r tests/all_tests.nim
#   # (after adding `import test_item_23_repro` to all_tests.nim)
#
# EXPECTED OUTPUT
#
#   spec value:    0 gwei
#   nimbus value:  1000000000 gwei
#   DIVERGENCE:    nimbus over-counts by 1000000000 gwei (1 ETH).
#
# Process exit code 1 indicates the divergence was demonstrated as expected;
# exit code 0 would mean the bug has been fixed (and this test should be
# inverted into a regression guard).

{.push raises: [], gcsafe.}
{.used.}

import
  std/strutils,
  std/strformat,
  ../beacon_chain/spec/beaconstate,
  ../beacon_chain/spec/datatypes/[base, gloas]

const
  V: ValidatorIndex = 5.ValidatorIndex  # any low validator index
  BID_AMOUNT: Gwei = 1_000_000_000.Gwei # 1 ETH

proc specReference(
    pending_partial_withdrawals: openArray[PendingPartialWithdrawal],
    validator_index: ValidatorIndex): Gwei =
  ## Pyspec algorithm at v1.7.0-alpha.7-21-g0e70a492d
  ## (consensus-specs/specs/electra/beacon-chain.md:635-642, inherited
  ## unchanged at Gloas after PR #4788 — commit 601829f1a, 2026-01-05,
  ## "Make builders non-validating staked actors", removed the
  ## intermediate `Modified get_pending_balance_to_withdraw` heading).
  var balance: Gwei
  for w in pending_partial_withdrawals:
    if w.validator_index == validator_index:
      balance += w.amount
  balance

proc main() =
  # Build a synthetic Gloas state in which:
  #   - state.pending_partial_withdrawals is empty (validator V has no
  #     pending partial withdrawals).
  #   - state.builder_pending_payments[0] holds a recent unsettled bid
  #     by a builder whose RAW builder_index numerically equals V.
  #
  # The HashArray and HashList fields are zero-initialized by default;
  # we only need to overwrite slot 0 of the ring buffer.
  var state = (ref gloas.BeaconState)()
  state[].builder_pending_payments.data[0] = BuilderPendingPayment(
    weight: BID_AMOUNT,
    withdrawal: BuilderPendingWithdrawal(
      amount: BID_AMOUNT,
      builder_index: uint64(V),
    ),
  )

  let
    specValue   = specReference(state[].pending_partial_withdrawals.asSeq(), V)
    nimbusValue = get_pending_balance_to_withdraw(state[], V)

  echo "=" .repeat(72)
  echo "Item #23 reproducer: nimbus get_pending_balance_to_withdraw OR-fold"
  echo "=" .repeat(72)
  echo ""
  echo &"Synthetic Gloas state:"
  echo &"  state.pending_partial_withdrawals  = []  (validator V={V} has no pending)"
  echo &"  state.builder_pending_payments[0]  = BuilderPendingPayment("
  echo &"      withdrawal.builder_index = {V},"
  echo &"      withdrawal.amount        = {BID_AMOUNT} gwei (1 ETH)"
  echo &"  )"
  echo ""
  echo &"Query: get_pending_balance_to_withdraw(state, validator_index={V})"
  echo ""
  echo &"  spec / prysm / lighthouse / teku / lodestar / grandine  -> {specValue} gwei"
  echo &"  nimbus (beaconstate.nim:1590-1607)                      -> {nimbusValue} gwei"
  echo ""

  if uint64(specValue) != uint64(nimbusValue):
    let delta = uint64(nimbusValue) - uint64(specValue)
    echo &"DIVERGENCE: nimbus over-counts by {delta} gwei."
    echo ""
    echo "Downstream impact at Gloas:"
    echo "  - process_voluntary_exit (state_transition_block.nim:513):"
    echo &"      spec gate `pending_balance == 0` passes -> exit accepted."
    echo &"      nimbus gate sees {nimbusValue} > 0     -> exit REJECTED."
    echo "  - process_withdrawal_request (state_transition_block.nim:644):"
    echo "      partial-amount path under-credits; full-exit gate silently drops."
    echo "  - process_consolidation_request (state_transition_block.nim:792):"
    echo "      source-gate `pending_balance > 0` rejects on nimbus,"
    echo "      proceeds on other 5 clients."
    echo ""
    echo "BUG STILL PRESENT in vendor/nimbus/beacon_chain/spec/beaconstate.nim:1590-1607."
    quit(1)

  echo "OK: spec and nimbus agree (bug appears to be fixed)"
  quit(0)

main()
