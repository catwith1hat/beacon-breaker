# Demo: empirical verification of the lodestar builder-sweep divergence

## What this shows

`spec_vs_lodestar.py` is a standalone Python script (no spec dependencies)
that implements **two** versions of Gloas's `get_expected_withdrawals`
side-by-side:

1. **Spec semantics**, per `vendor/consensus-specs/specs/gloas/beacon-chain.md:1218-1297`
   — `get_builders_sweep_withdrawals` reads `state.builders[idx].balance`
   directly from state.
2. **Lodestar's implementation pattern**, per
   `vendor/lodestar/packages/state-transition/src/block/processWithdrawals.ts:188-243`
   — uses a per-builder `builderBalanceAfterWithdrawals` cache that is
   decremented by `getBuilderWithdrawals` (queue drain) and **read back**
   for the sweep amount.

The script runs three scenarios:

- **T1.1 (collision)** — builder 0 has a pending queue entry of 0.2 ETH
  AND is sweep-eligible with 1000 ETH balance.
- **T1.2 (queue only)** — builder 0 has a pending queue entry but is NOT
  sweep-eligible.
- **T1.3 (sweep only)** — builder 0 is sweep-eligible with no queue
  entries.

## Running

```bash
python3 spec_vs_lodestar.py
```

## Result

```
T1.1 (collision):     DIVERGE ✗ (suspected bug confirmed)
  spec.amount     = 1,000,000,000,000  (full pre-block balance)
  lodestar.amount =   999,800,000,000  (pre_balance − 200,000,000 queue drain)
  diff            =       200,000,000  (exactly the queue-drain amount)

T1.2 (queue only):    MATCH ✓
T1.3 (sweep only):    MATCH ✓
```

The divergence triggers **only** on the queue+sweep collision (same
builder simultaneously has pending queue entries AND is sweep-eligible).
Both non-collision cases produce identical output.

## Implications

The emitted sweep `Withdrawal.amount` differs between lodestar and the
other 5 clients. This produces:

1. Different `state.payload_expected_withdrawals` → different beacon
   state root.
2. Different EL minting (1000 ETH vs 999.8 ETH to builder's execution
   address).
3. Different EL block-hash → cross-CL block import rejection.

The post-`apply_withdrawals` `state.builders[idx].balance` converges
to 0 in both semantics (via the `min(amount, balance)` saturation), so
the state-internal builder balance ends up the same. But the **emitted
Withdrawal records** differ, and those are part of consensus state.

## Mainnet reachability

Reachable scenario:

1. Builder X wins a sequence of past bids → `settle_builder_payment`
   appends entries to `state.builder_pending_withdrawals`.
2. Builder X calls `initiate_builder_exit` → sets
   `withdrawable_epoch = current_epoch + MIN_BUILDER_WITHDRAWABILITY_DELAY`.
3. After the delay elapses, builder X is sweep-eligible AND still has
   queue entries (which drain at `MAX_WITHDRAWALS_PER_PAYLOAD - 1 = 15`
   per slot, so the queue may not fully drain before sweep eligibility
   kicks in if multiple builders had queue entries).
4. The first `process_withdrawals` after sweep eligibility triggers
   the divergence on the lodestar node vs the other 5.

Natural mainnet trigger; not a crafted-state edge case.

## Mitigation possibilities

Option A (lodestar reverts): change `getBuildersSweepWithdrawals` to
read `builder.balance` directly from state (not from the cache). This
re-introduces the supply-asymmetry that the cache arguably fixes, but
preserves cross-client consensus.

Option B (spec changes): the spec could clarify that the sweep amount
should be `builder.balance − queue_drain_total_for_this_builder`. This
would require all 5 other clients to update.

Option C (test corpus): add a fixture exercising the collision case to
catch this at fixture-gen time. Pyspec already follows spec literal
semantics, so the fixture would match the 5-client behavior; lodestar
would fail it, forcing a decision.

The audit's recommendation (per items/067/README.md) is to surface this
to the lodestar team and the consensus-specs editors for resolution.
