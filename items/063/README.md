---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: [57, 60]
eips: [EIP-7732]
splits: []
# main_md_summary: TBD — drafting `process_ptc_window` epoch-helper audit (sibling to item #57's `process_builder_pending_payments`; rotates `state.ptc_window` at epoch boundary)
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 63: `process_ptc_window` epoch helper — Gloas-new PTC window rotation

## Summary

> **DRAFT — hypotheses-pending.** Sibling to item #57 (`process_builder_pending_payments`) and item #60 (PTC read side). `process_ptc_window` rotates `state.ptc_window` at the epoch boundary: drops the oldest epoch's window, materializes the new `MIN_SEED_LOOKAHEAD`-th-future epoch's window via `compute_ptc` (item #60). Subtle interactions with `process_effective_balance_updates` (PTC selection depends on effective balance) and with `process_randao_mixes_reset` (PTC seed depends on RANDAO). Order-of-effects audit.

The PTC window cache (`state.ptc_window: Vector[Vector[ValidatorIndex, PTC_SIZE], (1 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH]`) is read by `get_ptc` (item #60). The write side is `process_ptc_window`, invoked from `process_epoch` after effective-balance updates settle but before RANDAO reset propagates. Per-client epoch-helper ordering and the boundary `compute_ptc` call are the main divergence surfaces.

## Question

Pyspec `process_ptc_window` (Gloas, `vendor/consensus-specs/specs/gloas/beacon-chain.md`, TBD line):

```python
def process_ptc_window(state: BeaconState) -> None:
    # TODO[drafting]: paste exact spec body.
    # Captures: drop oldest slot's PTC row, compute the new tail row
    # via compute_ptc(state, slot=...).
```

Open questions:

1. **Helper position in `process_epoch`** — before/after `process_effective_balance_updates`? before/after `process_randao_mixes_reset`?
2. **Boundary `compute_ptc` invocation** — uses the post-update state, or pre-update?
3. **Window-shape constant** — `(1 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH` (33 rows on mainnet) — verify per-client.
4. **Reset on fork upgrade** — `upgrade_to_gloas` initializes `ptc_window` (item #64); does `process_ptc_window` agree on its post-upgrade shape?

## Hypotheses

- **H1.** All six clients place `process_ptc_window` at the same position in `process_epoch` (after `process_effective_balance_updates`, before `process_randao_mixes_reset`).
- **H2.** All six call `compute_ptc(state, slot)` with `slot = (state_epoch + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH + i` for `i ∈ [0, SLOTS_PER_EPOCH)`, on the post-effective-balance-update state.
- **H3.** All six use the same `state.ptc_window` shape: `(1 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH` rows, each `PTC_SIZE` (=512) wide.
- **H4.** All six drop the oldest `SLOTS_PER_EPOCH` rows (rotate left) and append the new ones.
- **H5.** `upgrade_to_gloas` (item #64) initializes `ptc_window` to the same shape, and the first `process_ptc_window` after Gloas activation rotates correctly.
- **H6** *(forward-fragility)*. Interaction with `proposer_lookahead` rotation (Fulu item #56): both rotate at the same boundary; verify no shared-state hazard.

## Findings

> **TBD — drafting.** Each client subsection below is a stub awaiting source review.

### prysm

TBD — drafting.

### lighthouse

TBD — drafting. Entry point candidate: `vendor/lighthouse/consensus/state_processing/src/per_epoch_processing/` plus `BeaconState::compute_ptc_with_cache` (used by initialization, item #60).

### teku

TBD — drafting. Entry point candidate: `vendor/teku/ethereum/spec/.../gloas/statetransition/epoch/EpochProcessorGloas.java`.

### nimbus

TBD — drafting. Entry point candidate: `vendor/nimbus/beacon_chain/spec/state_transition_epoch.nim` near the `compute_ptc` invocation at line 1425.

### lodestar

TBD — drafting.

### grandine

TBD — drafting.

## Cross-reference table

| Client | `process_ptc_window` location | Helper-order position | Window shape (H3) | Boundary `compute_ptc` invocation |
|---|---|---|---|---|
| prysm | TBD | TBD | TBD | TBD |
| lighthouse | TBD | TBD | TBD | TBD |
| teku | TBD | TBD | TBD | TBD |
| nimbus | TBD | TBD | TBD | TBD |
| lodestar | TBD | TBD | TBD | TBD |
| grandine | TBD | TBD | TBD | TBD |

## Empirical tests

> **TBD — drafting.** No dedicated EF Gloas fixture for `process_ptc_window` (TBD — verify). Implicit coverage via every Gloas epoch-boundary fixture.

### Suggested fuzzing vectors

- **T1.1 (canonical).** Run Gloas epoch boundary fixture; verify all 6 clients produce identical `state.ptc_window` post-rotation.
- **T2.1 (effective-balance edge).** Validator effective balance changes during the epoch; verify the new PTC row uses the post-update value.
- **T2.2 (RANDAO edge).** PTC seed depends on `get_seed(state, epoch, DOMAIN_PTC_ATTESTER)`. Verify the seed uses the correct RANDAO mix at the boundary.

## Conclusion

> **TBD — drafting.** Source review pending.

## Cross-cuts

### With item #57 (`process_builder_pending_payments`)

Sibling epoch helper. Both rotate Gloas-new windowed state. Ordering audit shared.

### With item #60 (PTC read side)

Item #60 is `get_ptc` / `compute_ptc` consumed by block processing. This item is the write side of the same cache. Round-trip cross-cut.

### With item #56 (Fulu `proposer_lookahead` rotation)

Both rotate at epoch boundary. Verify no shared-state hazard.

## Adjacent untouched

1. **`compute_ptc` invocation site at fork upgrade** — item #64 cross-cut.
2. **PTC duty publication API** (`getPtcDuties` VC-side) — cross-cut from item #60.
