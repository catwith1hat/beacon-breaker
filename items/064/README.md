---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: [22, 23, 28, 57, 60, 63]
eips: [EIP-7732, EIP-8061]
splits: []
# main_md_summary: TBD — drafting `upgrade_to_gloas` fork-upgrade migration audit (Electra → Gloas state migration; big-bang field initialization including builders registry, ptc_window, builder_pending_*; nimbus PR #4513 → #4788 revert window history suggests highest-risk area)
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 64: `upgrade_to_gloas` fork-upgrade migration

## Summary

> **DRAFT — hypotheses-pending. Highest-priority Gloas-audit candidate.** Migrates Electra state → Gloas state at the fork-boundary slot. Populates new fields: `builders: List[Builder, MAX_BUILDERS]`, `builder_pending_payments: Vector[BuilderPendingPayment, 2 * SLOTS_PER_EPOCH]`, `builder_pending_withdrawals: List[BuilderPendingWithdrawal, MAX_BUILDER_PENDING_WITHDRAWALS]`, `ptc_window`, `proposer_lookahead`, `latest_block_hash`, `latest_execution_payload_bid`, `execution_payload_availability`. Field-init order matters; iteration over existing validators to populate builders registry; nimbus's PR #4513 → #4788 revert-window history (items #22 + #23, both fixed in PR #8440) suggests this is the area where Gloas alpha drift is most likely to surface.

A divergence here is a hard fork-at-Gloas-activation: state-root mismatch on the upgrade slot's post-state, before any operations process.

## Question

Pyspec `upgrade_to_gloas` (Gloas, `vendor/consensus-specs/specs/gloas/fork.md`, TBD line):

```python
def upgrade_to_gloas(pre: electra.BeaconState) -> BeaconState:
    # TODO[drafting]: paste exact spec body.
    # Captures: validator-iteration to build builders registry,
    # ptc_window initialization (via initialize_ptc_window), 
    # builder_pending_payments/withdrawals zero-init,
    # latest_block_hash carryover, execution_payload_availability bits init.
```

Open questions:

1. **Builders-registry populator** — does it iterate `pre.validators` and pick those with 0x03 credentials? Or initialize empty and let the next deposit-drain populate?
2. **`ptc_window` initial population** — calls `initialize_ptc_window` to materialize `(1 + MIN_SEED_LOOKAHEAD)` epoch windows. Cross-cut with item #63.
3. **`builder_pending_payments` zero-init** — Vector with `default(BuilderPendingPayment)` repeated `2 * SLOTS_PER_EPOCH` times.
4. **`latest_block_hash` carryover** — from Electra's `latest_execution_payload_header.block_hash`.
5. **`execution_payload_availability` bitvector init** — `SLOTS_PER_HISTORICAL_ROOT` bits, initial values (all 0? all 1? per-bit pre-state derivation?).
6. **Fork epoch + version** — `GLOAS_FORK_VERSION = 0x07000000`, `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` (mainnet); custom configs override.
7. **`fork_data` propagation** — `pre.fork.previous_version` ← `pre.fork.current_version`; `current_version` ← `GLOAS_FORK_VERSION`.

## Hypotheses

- **H1.** All six clients implement `upgrade_to_gloas` per the same spec alpha version (currently 1.7.0-alpha.4 per recent items). nimbus PR #8440 history suggests this should be re-verified.
- **H2.** All six populate `state.builders` identically: iterate `pre.validators`, pick by 0x03 credential prefix (`BUILDER_WITHDRAWAL_PREFIX`), construct `Builder` records with `deposit_epoch = pre.finalized_checkpoint.epoch` (or similar).
- **H3.** All six initialize `ptc_window` via `initialize_ptc_window(state)` (compute `(1 + MIN_SEED_LOOKAHEAD)` epoch worth of PTC selections via `compute_ptc`).
- **H4.** All six zero-init `builder_pending_payments` and `builder_pending_withdrawals`.
- **H5.** All six carry over `latest_block_hash` from `pre.latest_execution_payload_header.block_hash`.
- **H6.** All six initialize `execution_payload_availability` per spec (TBD: all-1 since past payloads are by definition available? or all-0 then rebuilt as blocks process?).
- **H7.** All six update `state.fork` correctly: `previous_version = pre.fork.current_version`, `current_version = GLOAS_FORK_VERSION`, `epoch = current_epoch`.
- **H8** *(forward-fragility)*. Re-org through the fork boundary: replay-from-cold of a state immediately post-Gloas-upgrade must produce byte-identical state across all 6 clients.

## Findings

> **TBD — drafting.** Each client subsection below is a stub awaiting source review.

### prysm

TBD — drafting. Entry point candidate: `vendor/prysm/beacon-chain/core/transition/gloas/` (fork-upgrade dir).

### lighthouse

TBD — drafting. Entry point candidate: `vendor/lighthouse/consensus/state_processing/src/upgrade/` `gloas.rs` (probable).

### teku

TBD — drafting. Entry point candidate: `vendor/teku/ethereum/spec/.../gloas/forktransition/GloasStateUpgrade.java`.

### nimbus

TBD — drafting. Entry point candidate: `vendor/nimbus/beacon_chain/spec/beaconstate.nim upgrade_to_gloas`.

### lodestar

TBD — drafting. Entry point candidate: `vendor/lodestar/packages/state-transition/src/slot/upgradeStateToGloas.ts`.

### grandine

TBD — drafting. Entry point candidate: `vendor/grandine/transition_functions/src/gloas/fork.rs`.

## Cross-reference table

| Client | `upgrade_to_gloas` location | Builders-registry populator (H2) | `ptc_window` init (H3) | `execution_payload_availability` init (H6) |
|---|---|---|---|---|
| prysm | TBD | TBD | TBD | TBD |
| lighthouse | TBD | TBD | TBD | TBD |
| teku | TBD | TBD | TBD | TBD |
| nimbus | TBD | TBD | TBD | TBD |
| lodestar | TBD | TBD | TBD | TBD |
| grandine | TBD | TBD | TBD | TBD |

## Empirical tests

> **TBD — drafting.** EF Gloas fork-upgrade fixtures: `vendor/consensus-specs/tests/.../gloas/fork/upgrade_to_gloas/` (TBD path). Run cross-client and diff post-state byte-by-byte.

### Suggested fuzzing vectors

- **T1.1 (canonical).** Standard Electra → Gloas upgrade fixture. All 6 clients produce byte-identical post-state.
- **T2.1 (builders-registry populator).** Pre-state with mix of 0x01, 0x02, 0x03 credentials. Verify only 0x03 are picked up into `state.builders`.
- **T2.2 (zero-builders edge).** Pre-state with no 0x03 validators. Verify `state.builders` is empty list.
- **T2.3 (max-builders cap).** Pre-state with > MAX_BUILDERS 0x03 validators. Verify cap behaviour.
- **T2.4 (`ptc_window` boundary).** First `process_ptc_window` call post-upgrade — verify identical rotation across clients.
- **T2.5 (`execution_payload_availability` semantics).** Spot-check the bitvector initial values across clients.
- **T2.6 (re-org across boundary).** Re-org from slot post-Gloas-upgrade back to Electra; replay forward. State must converge.

## Conclusion

> **TBD — drafting.** Source review pending. Expected outcome: nimbus's PR #8440 closed the worst gaps; this is the audit to verify nothing else slipped through.

## Cross-cuts

### With items #22 + #23 + #28 (nimbus Gloas alpha drift)

Both root-caused in the nimbus Pattern N (PR #4513 → PR #4788 revert window). Fixed in PR #8440. Verify the upgrade path doesn't ship the alpha-drift form.

### With item #57 (`process_builder_pending_payments`)

Item #57 covers the write side of `builder_pending_payments`. This item covers the initial-state population.

### With item #63 (`process_ptc_window`)

`upgrade_to_gloas` calls `initialize_ptc_window`; `process_ptc_window` rotates it thereafter. Round-trip cross-cut.

### With item #60 (`compute_ptc`)

`initialize_ptc_window` (called from `upgrade_to_gloas`) calls `compute_ptc`. Cross-cut on the consumer.

## Adjacent untouched

1. **Test fixture coverage** — EF `gloas/fork/upgrade_to_gloas/` test vector cross-client run.
2. **State-pruning at fork boundary** — does any client special-case pruning across the upgrade?
3. **Custom-config fork epochs** — devnets activate Gloas at non-FAR_FUTURE epochs; verify the fork-schedule loader handles all 6 clients identically.
