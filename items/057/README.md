---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: [7, 12, 19]
eips: [EIP-7732]
splits: []
# main_md_summary: TBD — drafting `process_builder_pending_payments` Gloas-new epoch helper audit; closes the ePBS bid → attestation → settle → withdraw lifecycle on the settlement side
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 57: `process_builder_pending_payments` (Gloas-new epoch helper, EIP-7732 ePBS settlement)

## Summary

> **DRAFT — hypotheses-pending.** Closes the EIP-7732 ePBS lifecycle audit on the settlement side: item #7 H10 audited the producer (`process_attestation` writes `state.builder_pending_payments[slot_idx].weight`); this item audits the consumer (`process_builder_pending_payments` reads the weight at the next epoch boundary, decides whether the bid meets the quorum threshold, settles into `state.builder_pending_withdrawals`, and rolls the ring buffer).

The Gloas-new epoch helper that closes the ePBS payment lifecycle. Every epoch boundary, the helper walks `state.builder_pending_payments[0..SLOTS_PER_EPOCH]` (the older half of the ring buffer), tests each entry's `weight >= BUILDER_PAYMENT_QUORUM_THRESHOLD * total_active_balance / BASE_REWARD_FACTOR` quorum predicate, and either settles (appends a `BuilderPendingWithdrawal` to `state.builder_pending_withdrawals` for item #12 H11's Phase A to drain) or discards. Then rotates the ring buffer: `state.builder_pending_payments[0..SLOTS_PER_EPOCH] = state.builder_pending_payments[SLOTS_PER_EPOCH..2*SLOTS_PER_EPOCH]`, zero-fill the second half.

Cross-cuts items #7 (writer side), #9 (slashing-time clearer), #12 (withdrawal-time drain), and #19 (bid-time recorder).

## Question

Pyspec `process_builder_pending_payments` (Gloas, `vendor/consensus-specs/specs/gloas/beacon-chain.md` "New `process_builder_pending_payments`"):

```python
def process_builder_pending_payments(state: BeaconState) -> None:
    # TODO[drafting]: paste exact spec at next iteration; capture
    # quorum threshold formula, ring-buffer rotation semantics,
    # and the conditions under which an entry is settled vs discarded.
```

Open questions:

1. **Quorum threshold** — what fraction of `total_active_balance` does `BUILDER_PAYMENT_QUORUM_THRESHOLD` represent? Is it computed inline or read from a spec constant?
2. **Ring-buffer rotation** — exact mutation order: rotate first or settle first? Cross-client matters for `hash_tree_root(state)` mid-function.
3. **Zero-fill semantics** — does the second half rotate into the first, or do entries shift? `HashArray` vs `HashList` distinction matters for the on-disk SSZ layout.
4. **`BuilderPendingPayment` → `BuilderPendingWithdrawal` field copy** — which fields carry over, which are dropped, which are defaulted?
5. **Position in `process_epoch`** — relative to `process_slashings`, `process_registry_updates`, `process_pending_deposits`, `process_pending_consolidations`. Sequence matters because of shared state reads.

## Hypotheses

- **H1.** All six clients walk `state.builder_pending_payments[0..SLOTS_PER_EPOCH]` (the older half) and skip the newer half.
- **H2.** All six use the same quorum threshold formula (constants and operands TBD).
- **H3.** All six append to `state.builder_pending_withdrawals` (HashList) when the quorum predicate passes.
- **H4.** All six discard (skip without appending) when the quorum predicate fails.
- **H5.** All six rotate the ring buffer with the same shift direction (older → out, newer → older slot, zero-fill the newest slot).
- **H6.** All six maintain the invariant `len(state.builder_pending_payments) == 2 * SLOTS_PER_EPOCH` across the function (no inserts/deletes — only field overwrites).
- **H7.** All six run `process_builder_pending_payments` BEFORE `process_pending_deposits` in `process_epoch` (matters because deposits could affect `total_active_balance` mid-function).
- **H8.** All six copy `BuilderPendingPayment.withdrawal` (a `BuilderPendingWithdrawal` value) verbatim into the settle queue — no field rewriting.
- **H9** *(forward-fragility)*. All six use 64-bit arithmetic for the quorum comparison (no overflow risk at realistic stake levels).

## Findings

> **TBD — drafting.** Each client subsection below is a stub awaiting source review.

### prysm

TBD — drafting.

### lighthouse

TBD — drafting.

### teku

TBD — drafting.

### nimbus

TBD — drafting.

### lodestar

TBD — drafting.

### grandine

TBD — drafting.

## Cross-reference table

| Client | `process_builder_pending_payments` location | Quorum-threshold idiom (H2) | Ring-buffer rotation idiom (H5) | Settle/discard branch (H3, H4) |
|---|---|---|---|---|
| prysm | TBD | TBD | TBD | TBD |
| lighthouse | TBD | TBD | TBD | TBD |
| teku | TBD | TBD | TBD | TBD |
| nimbus | TBD | TBD | TBD | TBD |
| lodestar | TBD | TBD | TBD | TBD |
| grandine | TBD | TBD | TBD | TBD |

## Empirical tests

> **TBD — drafting.** No Gloas EF epoch-processing fixtures yet for this helper (the consensus-specs Gloas test corpus is sparse). Plan to identify fixtures or generate dedicated cross-client byte-equivalence tests during the source-review pass.

### Suggested fuzzing vectors

- **T1.1 (canonical settle).** Gloas state with one entry at `state.builder_pending_payments[0]` whose `weight` satisfies the quorum threshold. Expected: append to `builder_pending_withdrawals`, then rotate. Cross-client `state_root` should match.
- **T1.2 (canonical discard).** Same state but `weight` below quorum threshold. Expected: skip, then rotate. Cross-client `state_root` should match.
- **T1.3 (boundary — weight exactly at threshold).** Probe `weight == threshold` and `weight == threshold - 1` to identify off-by-one in any client's comparison operator (`>=` vs `>`).
- **T1.4 (multi-slot mixed).** All 32 entries in the older half, half passing quorum, half failing. Verifies the per-entry independence of the decision.
- **T2.1 (overflow probe).** Synthetic state with `total_active_balance` near `u64::MAX / BASE_REWARD_FACTOR` to probe overflow handling in the threshold formula.

## Conclusion

> **TBD — drafting.** Source review pending across all six clients.

## Cross-cuts

### With item #7 (`process_attestation` Gloas H10)

Item #7 H10 writes `state.builder_pending_payments[slot_idx].weight` from same-slot attestations setting new participation flags. This item consumes those weight values. Same primitive on the producer side; this item is the consumer. With item #7 H10 closed (uniform across all six clients), the input to this helper is uniform — the output divergence (if any) lies in this helper's logic.

### With item #12 (`process_withdrawals` Phase A)

Item #12 H11's Phase A drains `state.builder_pending_withdrawals` (the HashList this helper appends to). Sequence: this item settles into the HashList at epoch boundary N; item #12 Phase A drains it at block N+1. Round-trip from bid → settlement → withdrawal.

### With item #9 (`process_proposer_slashing` H9)

Item #9 H9 clears a `BuilderPendingPayment` entry when its proposer is slashed within the 2-epoch window. Race condition: if the slashing happens in the same epoch as the settlement, this helper sees a zeroed entry and discards (since `weight = 0 < threshold`). Cross-cut with the within-block operation ordering.

### With item #19 (`process_execution_payload_bid`)

Item #19's `process_execution_payload_bid` writes the bid into `state.builder_pending_payments[SLOTS_PER_EPOCH + slot % SLOTS_PER_EPOCH]` (the newer half). Two epochs later, this helper consumes it from the older half (after one rotation). Lifecycle: bid (item #19) → weight accumulation (item #7 H10) → settlement (this item) → withdrawal (item #12).

## Adjacent untouched

1. **`BUILDER_PAYMENT_QUORUM_THRESHOLD` constant value across clients** — verify all six configs agree on the mainnet value.
2. **Ring-buffer overflow at validator-set growth** — `state.builder_pending_payments` is fixed-size `HashArray`; `state.builder_pending_withdrawals` is `HashList[Limit BUILDER_PENDING_WITHDRAWALS_LIMIT]`. Verify cap behaviour when settlement would push the HashList over the limit.
3. **Position in `process_epoch` sequence** — relative to `process_slashings`, `process_pending_deposits`. Cross-client ordering check.
4. **`BuilderPendingPayment.withdrawal` field copy semantics** — when settling, is the entire `BuilderPendingWithdrawal` struct copied verbatim or are fields rewritten?
5. **Interaction with `settle_builder_payment`** — does this helper call `settle_builder_payment` per entry, or does it inline the logic?
6. **Pattern N follow-up** — verify the per-client doc-comment URLs in this function reference the current spec version (`v1.7.0-alpha.7+`), not an intermediate revert-window version.
