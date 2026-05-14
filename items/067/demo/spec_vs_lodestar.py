#!/usr/bin/env python3
"""
Empirical demonstration of the suspected lodestar divergence in item #67.

Reproduces both:
  (A) Spec semantics of `get_expected_withdrawals` at Gloas
      (vendor/consensus-specs/specs/gloas/beacon-chain.md:1218-1297).
  (B) Lodestar's implementation pattern at
      vendor/lodestar/packages/state-transition/src/block/processWithdrawals.ts:188-243
      using a per-builder `builderBalanceAfterWithdrawals` cache.

On the queue+sweep-collision scenario (single builder simultaneously has a
pending withdrawal in the queue AND is sweep-eligible), the two semantics
produce DIFFERENT `Withdrawal.amount` values for the sweep withdrawal:
  - spec: amount = pre-block builder.balance
  - lodestar: amount = pre-block balance MINUS sum of queue-drain amounts

This produces a different `state.payload_expected_withdrawals` list and
therefore a different beacon-state root, plus different EL minting amounts.

Run: python3 spec_vs_lodestar.py
"""

from dataclasses import dataclass, field
from typing import List

NUMBER_OF_COLUMNS = 128  # not used directly, but matches spec context
MAX_WITHDRAWALS_PER_PAYLOAD = 16
BUILDER_INDEX_FLAG = 1 << 63


def convert_builder_index_to_validator_index(builder_index: int) -> int:
    return builder_index | BUILDER_INDEX_FLAG


@dataclass
class Builder:
    pubkey: bytes
    execution_address: bytes
    balance: int
    withdrawable_epoch: int


@dataclass
class BuilderPendingWithdrawal:
    fee_recipient: bytes
    amount: int
    builder_index: int


@dataclass
class Withdrawal:
    index: int
    validator_index: int
    address: bytes
    amount: int


@dataclass
class State:
    builders: List[Builder]
    builder_pending_withdrawals: List[BuilderPendingWithdrawal]
    next_withdrawal_builder_index: int = 0
    next_withdrawal_index: int = 0
    current_epoch: int = 100


# ------------------------------------------------------------------------
# Spec semantics (pyspec verbatim, per consensus-specs/specs/gloas/beacon-chain.md)
# ------------------------------------------------------------------------

def spec_get_builder_withdrawals(state: State, withdrawal_index: int, prior_count: int):
    """Spec at beacon-chain.md:1184-1213."""
    withdrawals_limit = MAX_WITHDRAWALS_PER_PAYLOAD - 1
    assert prior_count <= withdrawals_limit

    withdrawals: List[Withdrawal] = []
    processed_count = 0
    for w in state.builder_pending_withdrawals:
        if prior_count + len(withdrawals) >= withdrawals_limit:
            break
        withdrawals.append(Withdrawal(
            index=withdrawal_index,
            validator_index=convert_builder_index_to_validator_index(w.builder_index),
            address=w.fee_recipient,
            amount=w.amount,  # queue entry's amount, not state balance
        ))
        withdrawal_index += 1
        processed_count += 1
    return withdrawals, withdrawal_index, processed_count


def spec_get_builders_sweep_withdrawals(state: State, withdrawal_index: int, prior_count: int):
    """Spec at beacon-chain.md:1218-1253."""
    withdrawals_limit = MAX_WITHDRAWALS_PER_PAYLOAD - 1
    builders_limit = min(len(state.builders), len(state.builders))  # MAX_BUILDERS_PER_WITHDRAWALS_SWEEP
    assert prior_count <= withdrawals_limit

    withdrawals: List[Withdrawal] = []
    processed_count = 0
    builder_index = state.next_withdrawal_builder_index
    for _ in range(builders_limit):
        if prior_count + len(withdrawals) >= withdrawals_limit:
            break
        builder = state.builders[builder_index]
        if builder.withdrawable_epoch <= state.current_epoch and builder.balance > 0:
            withdrawals.append(Withdrawal(
                index=withdrawal_index,
                validator_index=convert_builder_index_to_validator_index(builder_index),
                address=builder.execution_address,
                amount=builder.balance,  # <-- SPEC: raw state read
            ))
            withdrawal_index += 1
        builder_index = (builder_index + 1) % len(state.builders)
        processed_count += 1
    return withdrawals, withdrawal_index, processed_count


def spec_get_expected_withdrawals(state: State):
    """Spec at beacon-chain.md:1259-1297."""
    withdrawal_index = state.next_withdrawal_index
    withdrawals: List[Withdrawal] = []

    bw, withdrawal_index, _ = spec_get_builder_withdrawals(state, withdrawal_index, 0)
    withdrawals.extend(bw)

    # (skip pending_partial — not relevant here)

    sw, withdrawal_index, _ = spec_get_builders_sweep_withdrawals(
        state, withdrawal_index, len(withdrawals))
    withdrawals.extend(sw)

    return withdrawals


# ------------------------------------------------------------------------
# Lodestar semantics (per processWithdrawals.ts:411-507 + 135-243)
# ------------------------------------------------------------------------

def lodestar_get_builder_withdrawals(state: State, withdrawal_index: int, prior_count: int,
                                     builder_balance_cache: dict):
    """Lodestar processWithdrawals.ts:135-186."""
    withdrawals_limit = MAX_WITHDRAWALS_PER_PAYLOAD - 1
    withdrawals: List[Withdrawal] = []
    processed_count = 0

    for w in state.builder_pending_withdrawals:
        if prior_count + len(withdrawals) >= withdrawals_limit:
            break
        # Read or initialize cache
        if w.builder_index not in builder_balance_cache:
            builder_balance_cache[w.builder_index] = state.builders[w.builder_index].balance
        balance = builder_balance_cache[w.builder_index]

        # Spec-correct: emit withdrawal.amount (NOT cached balance)
        withdrawals.append(Withdrawal(
            index=withdrawal_index,
            validator_index=convert_builder_index_to_validator_index(w.builder_index),
            address=w.fee_recipient,
            amount=w.amount,
        ))
        withdrawal_index += 1

        # DECREMENT THE CACHE — this is the key step
        builder_balance_cache[w.builder_index] = balance - w.amount
        processed_count += 1

    return withdrawals, withdrawal_index, processed_count


def lodestar_get_builders_sweep_withdrawals(state: State, withdrawal_index: int, prior_count: int,
                                            builder_balance_cache: dict):
    """Lodestar processWithdrawals.ts:188-243."""
    withdrawals_limit = MAX_WITHDRAWALS_PER_PAYLOAD - 1
    builders_limit = len(state.builders)
    withdrawals: List[Withdrawal] = []
    processed_count = 0

    for n in range(builders_limit):
        if prior_count + len(withdrawals) >= withdrawals_limit:
            break
        builder_index = (state.next_withdrawal_builder_index + n) % len(state.builders)
        builder = state.builders[builder_index]

        # Get balance from cache (or initialize from state)
        if builder_index not in builder_balance_cache:
            builder_balance_cache[builder_index] = builder.balance
        balance = builder_balance_cache[builder_index]

        if builder.withdrawable_epoch <= state.current_epoch and balance > 0:
            withdrawals.append(Withdrawal(
                index=withdrawal_index,
                validator_index=convert_builder_index_to_validator_index(builder_index),
                address=builder.execution_address,
                amount=balance,  # <-- LODESTAR: cached balance!
            ))
            withdrawal_index += 1
            builder_balance_cache[builder_index] = 0
        processed_count += 1

    return withdrawals, withdrawal_index, processed_count


def lodestar_get_expected_withdrawals(state: State):
    """Lodestar processWithdrawals.ts:411-507."""
    withdrawal_index = state.next_withdrawal_index
    withdrawals: List[Withdrawal] = []
    builder_balance_cache: dict = {}

    bw, withdrawal_index, _ = lodestar_get_builder_withdrawals(
        state, withdrawal_index, 0, builder_balance_cache)
    withdrawals.extend(bw)

    # (skip pending_partial)

    sw, withdrawal_index, _ = lodestar_get_builders_sweep_withdrawals(
        state, withdrawal_index, len(withdrawals), builder_balance_cache)
    withdrawals.extend(sw)

    return withdrawals


# ------------------------------------------------------------------------
# Test cases
# ------------------------------------------------------------------------

def make_collision_state():
    """Builder X has both pending withdrawals AND is sweep-eligible."""
    return State(
        builders=[
            Builder(
                pubkey=b"\xaa" * 48,
                execution_address=b"\xbb" * 20,
                balance=1_000_000_000_000,  # 1000 ETH
                withdrawable_epoch=50,       # <= current_epoch=100, sweep-eligible
            ),
        ],
        builder_pending_withdrawals=[
            BuilderPendingWithdrawal(
                fee_recipient=b"\xcc" * 20,
                amount=200_000_000,  # 0.2 ETH queue drain
                builder_index=0,
            ),
        ],
        next_withdrawal_builder_index=0,
        next_withdrawal_index=42,
        current_epoch=100,
    )


def make_no_collision_state():
    """Builder X has pending withdrawals but is NOT sweep-eligible."""
    return State(
        builders=[
            Builder(
                pubkey=b"\xaa" * 48,
                execution_address=b"\xbb" * 20,
                balance=1_000_000_000_000,
                withdrawable_epoch=200,  # > current_epoch=100, NOT sweep-eligible
            ),
        ],
        builder_pending_withdrawals=[
            BuilderPendingWithdrawal(
                fee_recipient=b"\xcc" * 20,
                amount=200_000_000,
                builder_index=0,
            ),
        ],
        next_withdrawal_builder_index=0,
        next_withdrawal_index=42,
        current_epoch=100,
    )


def make_sweep_only_state():
    """Builder X is sweep-eligible, no queue entries."""
    return State(
        builders=[
            Builder(
                pubkey=b"\xaa" * 48,
                execution_address=b"\xbb" * 20,
                balance=1_000_000_000_000,
                withdrawable_epoch=50,
            ),
        ],
        builder_pending_withdrawals=[],
        next_withdrawal_builder_index=0,
        next_withdrawal_index=42,
        current_epoch=100,
    )


def diff(label, a, b):
    print(f"\n=== {label} ===")
    print(f"  spec output     ({len(a)} withdrawal(s)):")
    for w in a:
        print(f"    idx={w.index} vidx={w.validator_index:#x} addr={w.address.hex()[:8]}... amount={w.amount}")
    print(f"  lodestar output ({len(b)} withdrawal(s)):")
    for w in b:
        print(f"    idx={w.index} vidx={w.validator_index:#x} addr={w.address.hex()[:8]}... amount={w.amount}")
    if a == b:
        print("  → outputs IDENTICAL ✓")
        return True
    print("  → OUTPUTS DIFFER ✗")
    for i, (sa, sb) in enumerate(zip(a, b)):
        if sa != sb:
            print(f"    diff at [{i}]: spec.amount={sa.amount}, lodestar.amount={sb.amount}, "
                  f"diff={sa.amount - sb.amount}")
    return False


if __name__ == "__main__":
    print("=" * 70)
    print("Empirical verification of item #67 lodestar divergence")
    print("=" * 70)

    # T1.1: collision scenario
    state_a = make_collision_state()
    spec_out = spec_get_expected_withdrawals(state_a)
    lodestar_out = lodestar_get_expected_withdrawals(state_a)
    t1_match = diff(
        "T1.1: queue+sweep COLLISION (builder 0 has pending + is sweep-eligible)",
        spec_out, lodestar_out)

    # T1.2: no collision (queue only, builder not sweep-eligible)
    state_b = make_no_collision_state()
    spec_out = spec_get_expected_withdrawals(state_b)
    lodestar_out = lodestar_get_expected_withdrawals(state_b)
    t2_match = diff(
        "T1.2: queue only (builder NOT sweep-eligible)",
        spec_out, lodestar_out)

    # T1.3: sweep only
    state_c = make_sweep_only_state()
    spec_out = spec_get_expected_withdrawals(state_c)
    lodestar_out = lodestar_get_expected_withdrawals(state_c)
    t3_match = diff(
        "T1.3: sweep only (no queue entries)",
        spec_out, lodestar_out)

    print("\n" + "=" * 70)
    print("Summary:")
    print(f"  T1.1 (collision):     {'MATCH ✓' if t1_match else 'DIVERGE ✗ (suspected bug confirmed)'}")
    print(f"  T1.2 (queue only):    {'MATCH ✓' if t2_match else 'DIVERGE ✗'}")
    print(f"  T1.3 (sweep only):    {'MATCH ✓' if t3_match else 'DIVERGE ✗'}")
    print("=" * 70)

    if not t1_match and t2_match and t3_match:
        print("\nConclusion: divergence triggers ONLY on the queue+sweep collision.")
        print("Both non-collision cases produce identical output.")
        print("This confirms the source-review hypothesis in items/067/README.md.")
