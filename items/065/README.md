---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: [57]
eips: [EIP-7732]
splits: []
# main_md_summary: TBD — drafting `process_proposer_slashing` Gloas modification audit (Gloas-new side-effect: remove BuilderPendingPayment for the slashed proposal if in 2-epoch window)
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 65: `process_proposer_slashing` Gloas modification — `BuilderPendingPayment` voidance

## Summary

> **DRAFT — hypotheses-pending.** Gloas grafts a new side effect onto a Phase0 operation: when a proposer is slashed, the `BuilderPendingPayment` corresponding to the slashed proposal must be removed if it is still in the 2-epoch window. Order-of-effects audit: slashing churn (Pectra) interacts with builder-payment voidance (Gloas-new). Witness in grandine `block_processing.rs:1293-1308` (item #58 review).

```python
# Gloas-modified
def process_proposer_slashing(state: BeaconState, proposer_slashing: ProposerSlashing) -> None:
    # ... Phase0 slashing logic ...
    # Gloas-new:
    # > Remove the BuilderPendingPayment corresponding to this proposal if it is still
    # > in the 2-epoch window.
    slot = proposer_slashing.signed_header_1.message.slot
    proposal_epoch = compute_epoch_at_slot(slot)
    if proposal_epoch == get_current_epoch(state):
        state.builder_pending_payments[builder_payment_index_for_current_epoch(slot)] = BuilderPendingPayment()
    elif proposal_epoch == get_previous_epoch(state):
        state.builder_pending_payments[builder_payment_index_for_previous_epoch(slot)] = BuilderPendingPayment()
```

A divergence here is a state-root mismatch on any slashed-block-with-builder-payment scenario.

## Question

Pyspec `process_proposer_slashing` Gloas modification (`vendor/consensus-specs/specs/gloas/beacon-chain.md`, TBD line):

```python
def process_proposer_slashing(state: BeaconState, proposer_slashing: ProposerSlashing) -> None:
    # TODO[drafting]: paste exact Gloas-modified spec body.
```

Open questions:

1. **`builder_payment_index_for_*_epoch` helper** — modulo arithmetic on `slot % (2 * SLOTS_PER_EPOCH)` or similar? Per-client identical?
2. **Default-vs-clear** — zero-out the slot, or remove from a list?
3. **Order of effects** — does the Pectra slashing-churn write to `validator.slashed`, `validator.exit_epoch`, `validator.withdrawable_epoch` happen before or after the builder-payment voidance? Same per-client?
4. **No-builder-payment-for-this-slot case** — what if `state.builder_pending_payments[idx]` is already default? Verify idempotency.
5. **Old slot (>2 epochs ago) — no voidance.** Worth confirming the comparison logic.

## Hypotheses

- **H1.** All six clients implement the Gloas-new voidance branch identically.
- **H2.** All six use the same `builder_payment_index_for_current_epoch` / `_for_previous_epoch` arithmetic.
- **H3.** All six use `BuilderPendingPayment()` (default value) to clear the slot, not a list-remove.
- **H4.** All six preserve the original Pectra slashing churn semantics (no changes to `validator.slashed`/`exit_epoch`/`withdrawable_epoch` logic).
- **H5.** Order of effects: voidance after churn write (or unordered if they commute). Verify per-client.
- **H6.** Slashing for a proposal older than 2 epochs is a no-op on `builder_pending_payments`.

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

TBD — drafting. Entry point: `vendor/grandine/transition_functions/src/gloas/block_processing.rs:1277 process_proposer_slashing` (already read for item #58 cross-cut).

## Cross-reference table

| Client | `process_proposer_slashing` Gloas location | Voidance branch logic | Helper-fn name (`builder_payment_index_for_*`) | Old-proposal no-op (H6) |
|---|---|---|---|---|
| prysm | TBD | TBD | TBD | TBD |
| lighthouse | TBD | TBD | TBD | TBD |
| teku | TBD | TBD | TBD | TBD |
| nimbus | TBD | TBD | TBD | TBD |
| lodestar | TBD | TBD | TBD | TBD |
| grandine | TBD | TBD | TBD | TBD |

## Empirical tests

> **TBD — drafting.** EF Gloas operations fixture: `vendor/consensus-specs/tests/.../gloas/operations/proposer_slashing/` (TBD path).

### Suggested fuzzing vectors

- **T1.1 (canonical voidance, current epoch).** Slash a proposer who has a `BuilderPendingPayment` from the current epoch. Verify the slot is cleared post-processing.
- **T1.2 (canonical voidance, previous epoch).** Same, but proposal in previous epoch.
- **T2.1 (no-voidance, old).** Slash a proposer for a proposal > 2 epochs ago. Verify `builder_pending_payments` unchanged.
- **T2.2 (idempotency).** Slash a proposer whose slot is already default. Verify no error.
- **T2.3 (interleaved with churn).** Slashing emits a churn-write AND a voidance. Verify both happen and ordering is consistent.

## Conclusion

> **TBD — drafting.** Source review pending.

## Cross-cuts

### With item #57 (`process_builder_pending_payments`)

Item #57 is the rotation/drain side of `builder_pending_payments`. This item is the voidance side. Round-trip.

### With item #16 (EIP-8061 churn chokepoint)

Slashing-churn writes `validator.exit_epoch` via the chokepoint. Verify the Gloas-new voidance doesn't perturb the Electra churn semantics.

### With `process_attester_slashing` Gloas modification

Similar pattern? Worth checking spec — attester slashing might also void builder payments. (TBD; potential sibling audit item.)

## Adjacent untouched

1. **`process_attester_slashing` Gloas modifications** — sibling audit; same Gloas voidance pattern?
2. **`builder_payment_index_for_*` arithmetic** — verify modulo + offset matches across clients.
3. **Slashing during the fork-upgrade boundary slot** — does `upgrade_to_gloas` (item #64) interact?
