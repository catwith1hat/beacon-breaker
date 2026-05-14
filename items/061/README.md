---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: [16]
eips: []
splits: []
# main_md_summary: TBD — drafting `compute_activation_exit_epoch` foundational primitive audit (used by every Pectra+ exit/activation/consolidation path)
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 61: `compute_activation_exit_epoch` (foundational primitive — Phase0, used by every Pectra+ exit/activation/consolidation path)

## Summary

> **DRAFT — hypotheses-pending.** Trivial formula but pivotal cross-cut: used by every Pectra+ exit/activation/consolidation/registry-update path. Mentioned as a future audit in items #2, #3, #6, #8, #16, #17. A divergence here would cascade through the entire churn machinery — every `validator.exit_epoch` and `validator.activation_epoch` assignment depends on this primitive.

`compute_activation_exit_epoch(epoch) -> Epoch` returns the **earliest epoch at which an activation or exit can take effect**, given the current epoch. Phase0 formula:

```python
def compute_activation_exit_epoch(epoch: Epoch) -> Epoch:
    return Epoch(epoch + 1 + MAX_SEED_LOOKAHEAD)
```

On mainnet preset `MAX_SEED_LOOKAHEAD = 4`, so the result is `epoch + 5`. The function is **not modified at any fork** through Gloas — it carries forward unchanged.

**Why audit it now?** It's consumed by:
- `compute_exit_epoch_and_update_churn` (item #16 chokepoint) — the `max(state.earliest_exit_epoch, compute_activation_exit_epoch(current))` clamp.
- `compute_consolidation_epoch_and_update_churn` — same clamp on the consolidation side.
- `process_registry_updates` (item #17) — `validator.activation_epoch = compute_activation_exit_epoch(current)` for newly-eligible validators.
- `apply_pending_deposit` (item #4 transitively) — for the activation_epoch assignment.

A regression here (off-by-one in the `+ 1`, wrong constant lookup) would silently shift every validator's activation/exit timing by 1 epoch. Subtle but mainnet-reachable on every block carrying any of the gated operations.

## Question

Pyspec `compute_activation_exit_epoch` (Phase0, `vendor/consensus-specs/specs/phase0/beacon-chain.md`):

```python
def compute_activation_exit_epoch(epoch: Epoch) -> Epoch:
    """
    Return the epoch during which validator activations and exits initiated
    in ``epoch`` take effect.
    """
    return Epoch(epoch + 1 + MAX_SEED_LOOKAHEAD)
```

Pre-Pectra constant: `MAX_SEED_LOOKAHEAD = 4`. Not modified at Bellatrix / Capella / Deneb / Electra / Fulu / Gloas / Heze per the corpus.

Open questions:

1. **Constant source** — runtime config (`ChainSpec` / `RuntimeConfig` / `SpecConfig`) or compile-time constant? Per-client.
2. **Per-fork override** — does any client gate the constant on fork? (Spec says no.)
3. **Overflow** — at `epoch ≈ u64::MAX - 5`, the addition would overflow. Each client's safe-arithmetic policy?
4. **Caller-site casts** — `Epoch` is `uint64` in some clients; `Epoch::new(u64)` newtype wrapper in others. Verify cast safety.

## Hypotheses

- **H1.** All six clients implement `compute_activation_exit_epoch(epoch) = epoch + 1 + MAX_SEED_LOOKAHEAD`.
- **H2.** All six read `MAX_SEED_LOOKAHEAD` from the runtime spec config (not a compile-time constant), to support custom presets (minimal, mainnet).
- **H3.** All six produce identical values for any input epoch ≤ u64::MAX - 5 (no overflow region).
- **H4.** All six callers (item #16 chokepoint, item #17 registry updates, item #4 pending-deposit drain) consume the same return value.
- **H5.** No client fork-gates the function or the constant (Gloas does not modify it).
- **H6** *(forward-fragility)*. Overflow handling at `epoch ≈ u64::MAX - 5` — verify saturating vs panicking vs wrapping behaviour cross-client. Practically unreachable on mainnet (slot wraparound is ~10^11 years out) but worth documenting.

## Findings

> **TBD — drafting.** Each client subsection below is a stub awaiting source review.

### prysm

TBD — drafting. Entry point candidates: `vendor/prysm/beacon-chain/core/helpers/validators.go ActivationExitEpoch` (probably) or `core/time/slot_epoch.go`.

### lighthouse

TBD — drafting. Entry point candidates: `vendor/lighthouse/consensus/types/src/state/beacon_state.rs compute_activation_exit_epoch` or `consensus/types/src/chain_spec.rs`.

### teku

TBD — drafting. Entry point candidates: `vendor/teku/ethereum/spec/.../helpers/MiscHelpers*.java computeActivationExitEpoch`.

### nimbus

TBD — drafting. Entry point candidates: `vendor/nimbus/beacon_chain/spec/beaconstate.nim compute_activation_exit_epoch` or `helpers.nim`.

### lodestar

TBD — drafting. Entry point candidates: `vendor/lodestar/packages/state-transition/src/util/epoch.ts computeActivationExitEpoch`.

### grandine

TBD — drafting. Entry point candidates: `vendor/grandine/helper_functions/src/misc.rs compute_activation_exit_epoch`.

## Cross-reference table

| Client | `compute_activation_exit_epoch` location | `MAX_SEED_LOOKAHEAD` source | Overflow policy (H6) | Caller-site cast idiom |
|---|---|---|---|---|
| prysm | TBD | TBD | TBD | TBD |
| lighthouse | TBD | TBD | TBD | TBD |
| teku | TBD | TBD | TBD | TBD |
| nimbus | TBD | TBD | TBD | TBD |
| lodestar | TBD | TBD | TBD | TBD |
| grandine | TBD | TBD | TBD | TBD |

## Empirical tests

> **TBD — drafting.** No dedicated EF fixture for this primitive (it's a pure function with no state dependency beyond the input epoch). Implicit coverage via every Pectra+ EF fixture that exercises `process_voluntary_exit`, `process_withdrawal_request`, `process_consolidation_request`, `process_registry_updates`, or `compute_exit_epoch_and_update_churn`. All such fixtures PASS cross-client per items #2/#3/#6/#8/#9/#16/#17 — strong implicit evidence that H1–H5 hold.

### Suggested fuzzing vectors

- **T1.1 (canonical).** `compute_activation_exit_epoch(100) = 105` (mainnet). Pure-function cross-client byte-equivalence over a range of epoch values.
- **T1.2 (minimal preset).** `compute_activation_exit_epoch(100)` under minimal preset (if `MAX_SEED_LOOKAHEAD` differs).
- **T2.1 (overflow boundary).** `compute_activation_exit_epoch(u64::MAX - 4)` — does it overflow, saturate, or panic? Document the per-client behaviour even though unreachable on mainnet.
- **T2.2 (epoch = 0).** Genesis edge case: `compute_activation_exit_epoch(0) = 5`.

## Conclusion

> **TBD — drafting.** Source review pending across all six clients. Strong prior: implicit coverage from ~300+ EF fixtures already passing suggests H1–H5 will hold uniformly; the audit is primarily a documentation pass on per-client implementation idioms + overflow policy.

## Cross-cuts

### With item #16 (EIP-8061 churn chokepoint)

Item #16's `compute_exit_epoch_and_update_churn` uses `max(state.earliest_exit_epoch, compute_activation_exit_epoch(current_epoch))` to clamp the earliest exit epoch. A divergence in `compute_activation_exit_epoch` would shift the clamp value, propagating into every Pectra+ exit's `exit_epoch` assignment.

### With item #17 (`process_registry_updates`)

Item #17's activation branch writes `validator.activation_epoch = compute_activation_exit_epoch(current_epoch)`. A divergence here shifts the activation timing.

### With item #4 (`process_pending_deposits`)

Item #4's drain calls `compute_activation_exit_epoch` for the activation-epoch assignment of newly-created validators. Same cross-cut as item #17.

### With `MAX_SEED_LOOKAHEAD` constant

The constant itself is a separate cross-cut: every client's spec config must agree on the mainnet value (4). A constant-value mismatch would shift every activation/exit by an integer epoch. Worth verifying as part of this audit.

## Adjacent untouched

1. **`MAX_SEED_LOOKAHEAD` constant verification cross-client** — read out mainnet preset, compare across all 6 client configs. Trivial but pivotal.
2. **`compute_balance_weighted_selection` standalone** (cross-cut with item #60's PTC selection and item #27's sync-committee selection and proposer-index computation). Three-caller cross-cut.
3. **Overflow policy documentation** — formalize per-client behaviour on edge inputs.
4. **`Epoch` newtype safety** — Rust clients (`lighthouse`, `grandine`) use newtype wrappers; verify the addition doesn't lose the type-distinction at the call site.
