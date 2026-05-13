#!/usr/bin/env python3
"""Demonstrate item #23: nimbus's get_pending_balance_to_withdraw OR-folds
state.builder_pending_payments into the validator-side accessor at Gloas+.

This reproducer constructs a synthetic Gloas BeaconState in which:
  - state.pending_partial_withdrawals is empty (validator has no pending exits)
  - state.builder_pending_payments[0] contains a payment from builder
    with builder_index = V, amount = 1 ETH

Then it queries get_pending_balance_to_withdraw(state, validator_index=V)
through both the spec algorithm (which all 5 spec-conformant clients
implement) and the nimbus algorithm (transliterated from
vendor/nimbus/beacon_chain/spec/beaconstate.nim:1590-1607).

Expected output:
  spec    -> 0 (validator has no pending partial withdrawals)
  nimbus  -> 1_000_000_000 gwei  (1 ETH, OR-folded from builder_pending_payments)
  DIVERGENCE: state-root will differ between nimbus and the other 5 clients
              on any post-Gloas voluntary_exit / withdrawal_request /
              consolidation_request targeting validator V while builder V's
              bid is unsettled.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


# --- Minimal SSZ-shaped surrogates for the BeaconState fields we touch.
# We mirror the actual spec types but skip the Merkleization machinery.

ValidatorIndex = int
BuilderIndex = int
Gwei = int
ExecutionAddress = bytes  # 20 bytes


@dataclass
class PendingPartialWithdrawal:
    """electra/beacon-chain.md -- PendingPartialWithdrawal."""
    validator_index: ValidatorIndex
    amount: Gwei
    withdrawable_epoch: int = 0


@dataclass
class BuilderPendingWithdrawal:
    """gloas/beacon-chain.md -- BuilderPendingWithdrawal."""
    fee_recipient: ExecutionAddress = b"\x00" * 20
    amount: Gwei = 0
    builder_index: BuilderIndex = 0


@dataclass
class BuilderPendingPayment:
    """gloas/beacon-chain.md -- BuilderPendingPayment."""
    weight: Gwei = 0
    withdrawal: BuilderPendingWithdrawal = field(
        default_factory=BuilderPendingWithdrawal
    )


@dataclass
class GloasState:
    """Minimal Gloas BeaconState slice exercising the two accessors."""
    pending_partial_withdrawals: List[PendingPartialWithdrawal] = field(
        default_factory=list
    )
    builder_pending_withdrawals: List[BuilderPendingWithdrawal] = field(
        default_factory=list
    )
    builder_pending_payments: List[BuilderPendingPayment] = field(
        default_factory=list
    )


# --- Algorithm A: pyspec at v1.7.0-alpha.7-21-g0e70a492d
# (consensus-specs/specs/electra/beacon-chain.md:635-642; inherited unchanged at Gloas).
# This is what prysm, lighthouse, teku, lodestar, grandine all implement.

def get_pending_balance_to_withdraw_spec(
    state: GloasState, validator_index: ValidatorIndex
) -> Gwei:
    return sum(
        w.amount
        for w in state.pending_partial_withdrawals
        if w.validator_index == validator_index
    )


# --- Algorithm B: nimbus, transliterated from
# vendor/nimbus/beacon_chain/spec/beaconstate.nim:1590-1607.
# Doc comment at lines 1588-1589 still references the now-removed v1.6.0-beta.0
# `#modified-get_pending_balance_to_withdraw` section (removed by spec PR #4788,
# commit 601829f1a, 2026-01-05, "Make builders non-validating staked actors").
#
# The bug: the `when type(state).kind >= ConsensusFork.Gloas:` branch ALSO
# sums state.builder_pending_withdrawals and state.builder_pending_payments
# entries where builder_index numerically equals the queried validator_index.

def get_pending_balance_to_withdraw_nimbus(
    state: GloasState, validator_index: ValidatorIndex
) -> Gwei:
    pending_balance = 0
    for w in state.pending_partial_withdrawals:
        if w.validator_index == validator_index:
            pending_balance += w.amount
    # when type(state).kind >= ConsensusFork.Gloas:  [STALE OR-FOLD]
    for w in state.builder_pending_withdrawals:
        if w.builder_index == validator_index:  # numerical collision
            pending_balance += w.amount
    for p in state.builder_pending_payments:
        if p.withdrawal.builder_index == validator_index:  # numerical collision
            pending_balance += p.withdrawal.amount
    return pending_balance


# --- Demo scenario.

def demo() -> int:
    print("=" * 72)
    print("Item #23 reproducer: nimbus get_pending_balance_to_withdraw OR-fold")
    print("=" * 72)

    V: ValidatorIndex = 5  # Pick any low validator index.
    BID_AMOUNT: Gwei = 1_000_000_000  # 1 ETH bid value.

    # Construct a synthetic Gloas state in which:
    #   - state.pending_partial_withdrawals is EMPTY (validator V has no
    #     pending partial withdrawals).
    #   - state.builder_pending_payments[0] is a recent bid by builder
    #     with raw builder_index = V (numerical collision).
    state = GloasState(
        pending_partial_withdrawals=[],
        builder_pending_payments=[
            BuilderPendingPayment(
                weight=BID_AMOUNT,
                withdrawal=BuilderPendingWithdrawal(
                    amount=BID_AMOUNT,
                    builder_index=V,  # raw BuilderIndex == ValidatorIndex
                ),
            )
        ],
    )

    spec_value = get_pending_balance_to_withdraw_spec(state, V)
    nimbus_value = get_pending_balance_to_withdraw_nimbus(state, V)

    print()
    print(f"Synthetic state contents:")
    print(f"  state.pending_partial_withdrawals  = []  (validator V={V} has no pending)")
    print(f"  state.builder_pending_payments     = [BuilderPendingPayment(")
    print(f"                                            withdrawal.builder_index = {V},")
    print(f"                                            withdrawal.amount        = {BID_AMOUNT} gwei (1 ETH)")
    print(f"                                        )]")
    print()
    print(f"Query: get_pending_balance_to_withdraw(state, validator_index={V})")
    print()
    print(f"  spec / prysm / lighthouse / teku / lodestar / grandine  -> {spec_value:>13} gwei")
    print(f"  nimbus (beaconstate.nim:1590-1607)                      -> {nimbus_value:>13} gwei")
    print()

    if spec_value != nimbus_value:
        delta = nimbus_value - spec_value
        print(f"DIVERGENCE: nimbus over-counts by {delta} gwei ({delta // 10**9} ETH).")
        print()
        print("Downstream impact at Gloas:")
        print(f"  - process_voluntary_exit (state_transition_block.nim:513):")
        print(f"      spec gate `pending_balance == 0` passes -> exit accepted.")
        print(f"      nimbus gate sees {nimbus_value} > 0      -> exit REJECTED.")
        print(f"      Block containing the exit is rejected by nimbus, accepted")
        print(f"      by the other 5 clients. State-root mismatch -> chain split.")
        print()
        print(f"  - process_withdrawal_request (state_transition_block.nim:644):")
        print(f"      partial-amount path under-credits by {nimbus_value} gwei.")
        print(f"      full-exit gate (== 0) silently drops the request on nimbus;")
        print(f"      other 5 clients enqueue the exit.")
        print()
        print(f"  - process_consolidation_request (state_transition_block.nim:792):")
        print(f"      source-gate `pending_balance > 0` rejects on nimbus,")
        print(f"      proceeds on other 5 clients. Divergence on consolidation.")
        print()
        print("Trigger frequency on mainnet at Gloas activation:")
        print("  state.builder_pending_payments is a 64-slot ring buffer that")
        print("  continuously fills with raw builder_index entries during normal")
        print("  Gloas block production. Both BuilderIndex and ValidatorIndex are")
        print("  uint64 < 2**40 and both registries grow from 0. Any validator at")
        print("  index V performing voluntary_exit / withdrawal_request /")
        print("  consolidation_request while an unsettled bid by builder V exists")
        print("  in the ring buffer triggers the divergence.")
        return 1

    print("OK: spec and nimbus agree (no divergence)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(demo())
