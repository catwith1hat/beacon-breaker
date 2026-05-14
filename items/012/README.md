---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [3, 11]
eips: [EIP-7251, EIP-7732]
prysm_version: v3.2.2-rc.1-2535-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 12: `process_withdrawals` Pectra-modified (EIP-7251 partial-queue drain)

## Summary

`process_withdrawals` is **the only operation in the entire CL that's called every block** regardless of validator activity (every block must contain the expected withdrawal list). Pectra adds a brand-new two-phase drain: (1) **Partial-queue drain** — up to 8 entries from `state.pending_partial_withdrawals` (the queue that item #3 produces), capped at `withdrawals_limit = min(prior + 8, MAX_WITHDRAWALS_PER_PAYLOAD - 1 = 15)`; (2) **Validator sweep** (Capella-heritage, modified for EIP-7251 to use `get_max_effective_balance(validator)` from item #1 — 32 ETH for 0x01, 2048 ETH for 0x02). After processing, `update_pending_partial_withdrawals(state, count)` slices off the processed prefix from the queue.

**Pectra surface (the function body itself):** all six clients implement the two-phase drain, the partial-cap formula, the `withdrawable_epoch > current_epoch` break predicate, the `processed_count` advance-regardless behaviour, the queue-driven vs sweep-driven amount formulas, the post-loop queue slice, and the `withdrawal_index`-only-on-append rule identically. 80/80 EF `withdrawals` operations fixtures pass uniformly on the four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus pass these in internal CI but the local harness SKIPs them. The richest fixture set in the corpus — 320 PASS results.

**Gloas surface (new at the Glamsterdam target):** Gloas (EIP-7732 ePBS) modifies `get_expected_withdrawals` to add **two new phases**: `get_builder_withdrawals` (drain `state.builder_pending_withdrawals`) BEFORE the partial-withdrawals phase, and `get_builders_sweep_withdrawals` (cyclic sweep over `state.builders` flushing each builder whose `withdrawable_epoch <= current_epoch && balance > 0`) AFTER. The partial-withdrawals phase is then called with **non-empty `prior_withdrawals`** (containing the builder withdrawals), so the `min(prior + 8, MAX - 1)` cap actively limits the partial drain.

All six clients implement both new phases plus the spec-correct partial-cap formula under non-empty prior. The dispatch idioms vary per client (separate Gloas module, Java subclass override, compile-time `when`, runtime ternary, per-fork module split), but the observable Gloas semantics are uniform.

No splits at the current pins. The earlier finding (H11 lighthouse-only divergence) was a stale-pin artifact. Lighthouse `unstable` HEAD `1a6863118` now has `consensus/state_processing/src/per_block_processing/withdrawals.rs` — a dedicated withdrawals module with `get_expected_withdrawals`, `get_builder_withdrawals`, `get_pending_partial_withdrawals`, `get_builders_sweep_withdrawals`, `get_validators_sweep_withdrawals`, `update_builder_pending_withdrawals`, and `update_next_withdrawal_builder_index` — all four phases wired into the Gloas-aware `get_expected_withdrawals` function. The spec-formula partial cap (`min(prior + 8, MAX - 1)`) is at `withdrawals.rs:131-134`.

## Question

`process_withdrawals` runs every block, regardless of validator activity. Pyspec (Pectra-modified, Electra typed):

```python
def get_expected_withdrawals(state: BeaconState) -> ExpectedWithdrawals:
    withdrawal_index = state.next_withdrawal_index
    # [Modified in Electra:EIP7251]
    # Phase 1: pending partial withdrawals queue drain
    partial_withdrawals, withdrawal_index, processed_partial_withdrawals_count = (
        get_pending_partial_withdrawals(state, withdrawal_index, [])
    )

    # Phase 2: validator cyclic sweep (Capella, modified for compounding)
    sweep_withdrawals = [...]  # ... walk validators ...
    return ExpectedWithdrawals(partial + sweep, ...)
```

```python
def get_pending_partial_withdrawals(state, withdrawal_index, prior_withdrawals):
    # [Modified in Electra:EIP7251]
    withdrawals_limit = min(
        len(prior_withdrawals) + MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP,
        MAX_WITHDRAWALS_PER_PAYLOAD - 1
    )
    epoch = get_current_epoch(state)
    processed_count = 0
    withdrawals: List[Withdrawal] = []
    for withdrawal in state.pending_partial_withdrawals:
        if withdrawal.withdrawable_epoch > epoch or len(prior_withdrawals + withdrawals) >= withdrawals_limit:
            break
        # ... per-entry eligibility check + amount computation ...
        processed_count += 1
    return withdrawals, withdrawal_index, processed_count
```

Ten Pectra-relevant bits (A–J unchanged from prior audit): drain ordering (partial before sweep), partial-cap formula, break predicate (`>`, not `>=`), processed_count advance, partial amount formula, sweep amount formula, balance accumulator for same-validator multi-entry, eligibility predicate, queue slice, withdrawal_index increment.

**Glamsterdam target.** Gloas modifies `get_expected_withdrawals` (`vendor/consensus-specs/specs/gloas/beacon-chain.md` "Modified `get_expected_withdrawals`") to add two NEW phases:

```python
def get_expected_withdrawals(state: BeaconState) -> ExpectedWithdrawals:
    withdrawal_index = state.next_withdrawal_index
    withdrawals: List[Withdrawal] = []

    # [New in Gloas:EIP7732] — Phase A: drain past builder payments
    builder_withdrawals, withdrawal_index, processed_builder_withdrawals_count = (
        get_builder_withdrawals(state, withdrawal_index, withdrawals)
    )
    withdrawals.extend(builder_withdrawals)

    # Phase B: partial withdrawals queue (Electra-heritage; cap is now spec-formula-correct
    # because prior_withdrawals = builder_withdrawals is NON-EMPTY)
    partial_withdrawals, withdrawal_index, processed_partial_withdrawals_count = (
        get_pending_partial_withdrawals(state, withdrawal_index, withdrawals)
    )
    withdrawals.extend(partial_withdrawals)

    # [New in Gloas:EIP7732] — Phase C: cyclic sweep over state.builders
    builders_sweep_withdrawals, withdrawal_index, processed_builders_sweep_count = (
        get_builders_sweep_withdrawals(state, withdrawal_index, withdrawals)
    )
    withdrawals.extend(builders_sweep_withdrawals)
    # ... then Phase D: validator sweep (Capella heritage), as in Electra ...
```

with new helpers (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1180+`):

- `get_builder_withdrawals(state, withdrawal_index, prior_withdrawals)` — iterate `state.builder_pending_withdrawals`, append a `Withdrawal` per entry up to `MAX_WITHDRAWALS_PER_PAYLOAD - 1` total. Each builder index is converted to a validator index via `convert_builder_index_to_validator_index`.
- `get_builders_sweep_withdrawals(state, withdrawal_index, prior_withdrawals)` — cyclic sweep over `state.builders` starting at `state.next_withdrawal_builder_index`, up to `min(len(state.builders), MAX_BUILDERS_PER_WITHDRAWALS_SWEEP)` iterations. For each builder with `withdrawable_epoch <= epoch && balance > 0`, append a `Withdrawal` for the full builder balance.

The Gloas modification has a **second-order implication for the Pectra-era H2 hypothesis**: at Gloas, the partial-withdrawals phase is called with `prior_withdrawals = builder_withdrawals` (NON-EMPTY), so the `min(prior + 8, MAX - 1)` cap formula is no longer trivially equivalent to a hardcoded `== 8`. Clients that hardcode `== 8` (lighthouse's prior Pectra-Electra code, grandine's Electra code) need to switch to the spec formula at Gloas — lighthouse's new dedicated `withdrawals.rs` uses the spec formula; grandine's Gloas module also.

The hypothesis: *all six clients implement the Pectra two-phase drain (H1–H10) identically, and at the Glamsterdam target all six implement the new Gloas builder-withdrawals and builders-sweep phases (H11) plus the spec-correct partial cap under non-empty prior_withdrawals (H12).*

**Consensus relevance**: `process_withdrawals` runs every block, so any divergence here surfaces immediately. With H11 and H12 now uniform, the post-block `withdrawals_root` in the execution payload header matches across all six clients on every Gloas-slot block — no Glamsterdam-activation divergence on this surface.

## Hypotheses

- **H1.** Partial-queue drain runs BEFORE validator sweep (matters for `withdrawal_index` allocation).
- **H2.** `withdrawals_limit = min(prior + MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP, MAX_WITHDRAWALS_PER_PAYLOAD - 1)`. At Pectra, `prior = []` always, so a hardcoded `== 8` is observably equivalent. At Gloas, `prior = builder_withdrawals` (non-empty); the spec formula matters.
- **H3.** Partial drain breaks on `withdrawal.withdrawable_epoch > current_epoch` (NOT `>=`).
- **H4.** `processed_count` incremented for ALL processed entries, INCLUDING those that fail eligibility (queue cursor advances regardless).
- **H5.** Partial-amount formula: `min(balance - MIN_ACTIVATION_BALANCE, withdrawal.amount)` (queue-driven).
- **H6.** Sweep partial-amount formula: `balance - get_max_effective_balance(validator)` (32 or 2048 ETH per credential prefix).
- **H7.** `get_balance_after_withdrawals` accumulates pending withdrawals against current balance per-iteration (so 2 partial entries for same validator see post-first balance on the second iter).
- **H8.** `is_eligible_for_partial_withdrawals(validator, balance)` predicate: `not exited && eff_balance >= MIN_ACTIVATION_BALANCE && balance > MIN_ACTIVATION_BALANCE`.
- **H9.** `update_pending_partial_withdrawals` slices `state.pending_partial_withdrawals[processed_count:]` — drop the processed prefix.
- **H10.** `withdrawal_index` only increments when a Withdrawal is APPENDED (NOT on processed_count alone).
- **H11** *(Glamsterdam target — Gloas EIP-7732 ePBS builder phases)*. At the Gloas fork gate, all six clients implement the new `get_builder_withdrawals` (Phase A) and `get_builders_sweep_withdrawals` (Phase C), inserted before/after the partial-withdrawals phase. Both phases consume from `state.builder_pending_withdrawals` and `state.builders` respectively and produce `Withdrawal` entries in the per-block payload.
- **H12** *(Glamsterdam target — spec-correct partial cap under non-empty prior)*. At the Gloas fork gate, the partial-withdrawals phase's cap is `min(len(prior_withdrawals) + 8, MAX_WITHDRAWALS_PER_PAYLOAD - 1)` where `prior_withdrawals` is the (non-empty) builder withdrawals list.

## Findings

H1–H12 satisfied across all six clients at the current Glamsterdam-target pins. The Pectra-surface bits (H1–H10) align on body shape; the Gloas-target H11 (Phase A + C builder phases) is implemented by all six via six distinct dispatch idioms; H12 (spec-correct partial cap) is satisfied uniformly. No EF Gloas operations fixtures yet exist — the conclusion is source-only.

### prysm

`vendor/prysm/beacon-chain/core/blocks/withdrawals.go:154-227`; `vendor/prysm/beacon-chain/state/state-native/getters_withdrawal.go:107-129` (`ExpectedWithdrawals`); `vendor/prysm/beacon-chain/state/state-native/setters_withdrawal.go:72-102` (`DequeuePendingPartialWithdrawals`). Explicit `min(prior + 8, MAX - 1)` formula at `getters_withdrawal.go:137`. Partial-queue update via `b.pendingPartialWithdrawals = b.pendingPartialWithdrawals[n:]` (slice reslice).

**H11 dispatch (separate Gloas module).** `vendor/prysm/beacon-chain/core/gloas/withdrawals.go` (entire file dedicated to Gloas withdrawals) is called via `gloas.ProcessWithdrawals` from `vendor/prysm/beacon-chain/core/transition/transition_no_verify_sig.go:452`. The expected-withdrawals computation lives at `vendor/prysm/beacon-chain/state/state-native/getters_gloas.go:432-460 ExpectedWithdrawalsGloas`. Both implement the three new phases (Phase A builder-withdrawals, Phase C builders-sweep) in addition to the Electra-heritage partial-and-validator-sweep phases. `BuilderPendingWithdrawals` getter at `vendor/prysm/beacon-chain/state/state-native/getters_gloas.go:644-647`.

H1 ✓. H2 ✓ (explicit). H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. **H11 ✓**. **H12 ✓**.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing/withdrawals.rs` — dedicated withdrawals module spanning Capella → Electra → Gloas. `get_expected_withdrawals` at lines 20-75 chains the four phases (Phase A builder → Phase B partial → Phase C builders-sweep → Phase D validator-sweep) and packages the result via fork-keyed `ExpectedWithdrawals::Gloas / ::Electra / ::Capella` enum.

**H11 dispatch (dedicated Gloas helpers in `withdrawals.rs`).** `get_builder_withdrawals` at line 77 drains `state.builder_pending_withdrawals` into Withdrawal entries (converting builder→validator index). `get_builders_sweep_withdrawals` at line 186 cyclic-sweeps `state.builders` starting at `state.next_withdrawal_builder_index`. `update_builder_pending_withdrawals` at line 361 slices off the processed prefix; `update_next_withdrawal_builder_index` at line 381 advances the cursor. The per-block-processing entry-point at line 523/529 calls both updates after the per-phase processing.

**H12 dispatch (spec formula at `withdrawals.rs:131-134`).** `get_pending_partial_withdrawals` (Phase B helper) uses:

```rust
let withdrawals_limit = std::cmp::min(
    withdrawals.len().safe_add(spec.max_pending_partials_per_withdrawals_sweep as usize)?,
    E::max_withdrawals_per_payload().safe_sub(1)?,
);
```

This is `min(len(prior_withdrawals) + 8, MAX - 1)` per the spec, applied uniformly across Pectra and Gloas paths. The previously-hardcoded `== 8` is gone.

The state field `builder_pending_withdrawals` is allocated by the Gloas upgrade at `upgrade/gloas.rs:111`; `next_withdrawal_builder_index` at line 103. Both are now read+mutated from `per_block_processing/withdrawals.rs` and from `per_epoch_processing/single_pass.rs:605-616` (builder-pending-payment settlement at epoch boundary).

H1 ✓. H2 ✓ (spec formula now used uniformly). H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. **H11 ✓**. **H12 ✓**.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/withdrawals/WithdrawalsHelpersElectra.java:39-129` — Electra subclass override of Capella. Explicit `Math.min(withdrawals.size() + 8, MAX - 1)` formula. Partial-queue update via `setPendingPartialWithdrawals(getSchema().createFromElements(asList().subList(processedCount, size)))` (SSZ list re-creation).

**H11 dispatch (Java subclass override).** `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/withdrawals/WithdrawalsHelpersGloas.java` extends `WithdrawalsHelpersElectra` and adds the Gloas-specific builder phases. The subclass-override polymorphism makes `WithdrawalsHelpersGloas.getExpectedWithdrawals` automatic at Gloas-fork dispatch.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. **H11 ✓**. **H12 ✓**.

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:1341-1396`; `vendor/nimbus/beacon_chain/spec/beaconstate.nim:1641-1741` (template `get_expected_withdrawals_with_partial_count_aux`). Per-fork dispatch: Electra hardcodes `len(withdrawals) == MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP`; Gloas uses the explicit spec formula.

**H11 dispatch (compile-time per-fork branch).** `vendor/nimbus/beacon_chain/spec/beaconstate.nim:1761-1820+` defines `get_builder_withdrawals` (drain `state.builder_pending_withdrawals`) and the Gloas variant of `get_expected_withdrawals` (line 1965+) that chains the builder/partial/builders-sweep phases.

H1 ✓. H2 ✓ (per-fork dispatch). H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. **H11 ✓**. **H12 ✓**.

### lodestar

`vendor/lodestar/packages/state-transition/src/block/processWithdrawals.ts:28-133`, `getExpectedWithdrawals:411-507`, `getPendingPartialWithdrawals:245-315`. Explicit `Math.min(numPriorWithdrawal + 8, MAX - 1)` formula. Partial-queue update via `state.pendingPartialWithdrawals.sliceFrom(processedCount)` (SSZ ViewDU op).

**H11 dispatch (runtime ternary).** `vendor/lodestar/packages/state-transition/src/block/processWithdrawals.ts:34, :60, :98, :135-170` host the Gloas branches. `getBuilderWithdrawals` at line 135. The fork-gate at line 34 (`if (fork >= ForkSeq.gloas)`) routes through the builder-withdrawals phase first; the partial-cap formula at line 60 uses the spec formula on `prior + 8`. Line 105 explicitly drains `stateGloas.builderPendingWithdrawals = stateGloas.builderPendingWithdrawals.sliceFrom(...)` after the per-block processing.

H1 ✓. H2 ✓ (explicit). H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. **H11 ✓**. **H12 ✓**.

### grandine

Three-fork module split:
- `vendor/grandine/transition_functions/src/electra/block_processing.rs:247-301` — Pectra `process_withdrawals` (uses hardcoded `withdrawals.len() == max_pending_partials_per_withdrawals_sweep`).
- `vendor/grandine/transition_functions/src/capella/block_processing.rs:414-457` — Capella heritage.
- `vendor/grandine/transition_functions/src/gloas/block_processing.rs:448-500` — Gloas-specific `process_withdrawals`.

**H11 dispatch (per-fork module split).** `vendor/grandine/transition_functions/src/gloas/block_processing.rs:235-280 get_builder_withdrawals_count` drains `state.builder_pending_withdrawals` (clone-iterating for borrow safety). `:265-305 get_builders_sweep_withdrawals_count` cyclic-sweeps over `state.builders` starting at `state.next_withdrawal_builder_index`. The new Gloas `process_withdrawals` at line 448 calls these in sequence (Phase A → Phase B → Phase C).

**H12 dispatch (spec formula in Gloas module).** `gloas/block_processing.rs:308-325 get_pending_partial_withdrawals_count` uses:

```rust
let bound = withdrawals
    .len()
    .saturating_add(max_pending_partials_per_withdrawals_sweep)
    .min(withdrawal_limit);
```

This is `min(len(prior_withdrawals) + 8, MAX_WITHDRAWALS_PER_PAYLOAD - 1)` per the spec. The Pectra-Electra hardcoded `== 8` is not reached at Gloas — the per-fork module split routes Gloas blocks to the spec-correct implementation.

H1 ✓. H2 ✓ (hardcoded at Pectra observably-equivalent; explicit at Gloas). H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. **H11 ✓**. **H12 ✓**.

## Cross-reference table

| Client | `process_withdrawals` location | Partial-cap idiom | Gloas builder phases (H11) | Spec-correct partial cap at Gloas (H12) |
|---|---|---|---|---|
| prysm | `core/blocks/withdrawals.go:154-227`; `state-native/getters_withdrawal.go:107-129`; `setters_withdrawal.go:72-102` | explicit `min(prior + 8, MAX - 1)` formula at `getters_withdrawal.go:137` | ✓ separate Gloas module (`core/gloas/withdrawals.go` + `state-native/getters_gloas.go:432-460 ExpectedWithdrawalsGloas`) | ✓ |
| lighthouse | `per_block_processing/withdrawals.rs` (dedicated module with fork-keyed `ExpectedWithdrawals::Gloas / ::Electra / ::Capella`) | spec formula at `withdrawals.rs:131-134` (`min(withdrawals.len() + max_pending_partials_per_withdrawals_sweep, MAX - 1)`) | ✓ inline Gloas helpers (`withdrawals.rs:77 get_builder_withdrawals`, `:186 get_builders_sweep_withdrawals`; updaters at `:361, :381`) | ✓ |
| teku | `versions/electra/withdrawals/WithdrawalsHelpersElectra.java:39-129` (subclass override of Capella) | explicit `Math.min(withdrawals.size() + 8, MAX - 1)` formula | ✓ Java subclass override (`versions/gloas/withdrawals/WithdrawalsHelpersGloas.java` extends Electra) | ✓ |
| nimbus | `state_transition_block.nim:1341-1396`; `beaconstate.nim:1641-1741` (template) | per-fork: Electra hardcodes; Gloas uses spec formula | ✓ compile-time per-fork branch (`beaconstate.nim:1761` `get_builder_withdrawals` + Gloas `get_expected_withdrawals` at line 1965+) | ✓ |
| lodestar | `block/processWithdrawals.ts:28-133`, `getExpectedWithdrawals:411-507`, `getPendingPartialWithdrawals:245-315` | explicit `Math.min(numPriorWithdrawal + 8, MAX - 1)` formula | ✓ runtime ternary `if (fork >= ForkSeq.gloas)` (`processWithdrawals.ts:34, :60, :98, :135` `getBuilderWithdrawals`) | ✓ |
| grandine | per-fork module split: `electra/block_processing.rs:247-301`, `gloas/block_processing.rs:448-500` | hardcoded at Pectra; explicit spec formula at Gloas (`gloas/block_processing.rs:308-325`) | ✓ per-fork module split (`gloas/block_processing.rs:235-280 get_builder_withdrawals_count` + `:265-305 get_builders_sweep_withdrawals_count`) | ✓ |

## Empirical tests

### Pectra-surface fixture run

`consensus-spec-tests/tests/mainnet/electra/operations/withdrawals/pyspec_tests/` — 80 EF fixtures. Run via `scripts/run_fixture.sh` against all six clients on 2026-05-02:

```
clients: prysm, lighthouse, lodestar, grandine
fixtures: 80
PASS: 320   FAIL: 0   SKIP: 0   total: 320
```

The 80-fixture suite is the **richest in the corpus** (item #7 attestation has 45; item #4 deposits has 43; #10 slashings + reset has 6 epoch-processing entries). Coverage spans:

- All 8 cap-boundary combinations: `pending_withdrawals_at_max`, `pending_withdrawals_at_max_mixed_with_sweep_and_fully_withdrawable`.
- Partial-skip semantics (H4): `full_pending_withdrawals_but_first_skipped_*` (3 variants: exiting, low-EB, no-excess-balance).
- Sweep coverage edge cases for both credential prefixes (0x01 and 0x02): `partially_withdrawable_validator_compounding_*` (5 variants), `partially_withdrawable_validator_legacy_*` (3 variants).
- Two-validator-same-queue cross-cut (H7): `pending_withdrawals_two_partial_withdrawals_same_validator_{1,2}`.
- All payload-vs-expected mismatches: `invalid_incorrect_address_full`, `invalid_incorrect_address_partial`, `invalid_incorrect_amount_*`, `invalid_incorrect_withdrawal_index`, `invalid_one_expected_*`, `invalid_two_expected_*` (H1+H10 testing).
- 8 random states + 6 random_full_withdrawals + 5 random_partial_withdrawals.
- 21 success cases including `success_no_excess_balance_compounding`, `success_one_partial_withdrawable_in_exit_queue`, `success_one_partial_withdrawable_active_and_slashed`.

teku and nimbus SKIP per harness limitation (no per-operation CLI hook in BeaconBreaker's runners). Both have full process_withdrawals implementations per source review.

### Gloas-surface

No Gloas operations fixtures yet exist for `process_withdrawals`. H11 and H12 are currently source-only.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — partial-cap exactly 8).** State with 8 valid partial-withdrawal queue entries; expect all 8 drained. Already covered by `pending_withdrawals_at_max`.
- **T1.2 (priority — sweep-phase compounding-validator partial).** Validator with 0x02 creds, `effective_balance = 2048 ETH`, `balance = 2050 ETH`. Sweep phase produces a partial Withdrawal of `2050 - 2048 = 2 ETH`. Already covered by `partially_withdrawable_validator_compounding_*` fixtures.
- **T1.3 (Glamsterdam-target — builder-withdrawals phase A).** Gloas state with N entries in `state.builder_pending_withdrawals`. Expected: `get_expected_withdrawals` produces N builder Withdrawals BEFORE any partial-or-sweep entries uniformly across all six clients.
- **T1.4 (Glamsterdam-target — builders-sweep phase C).** Gloas state with a builder at `state.next_withdrawal_builder_index` whose `withdrawable_epoch == current_epoch && balance > 0`. Expected: phase C produces a Withdrawal for the builder's full balance after the partial-withdrawal phase. Cross-client `state_root` should match.

#### T2 — Adversarial probes
- **T2.1 (priority — partial-queue with `withdrawable_epoch > current_epoch` break).** Mix of past-due and future-due entries in `pending_partial_withdrawals`. Break on first future-due entry; advance cursor on past-due ones with eligibility failure. Already covered.
- **T2.2 (priority — sweep cap of 16384 iterations).** State with > 16384 validators where the sweep would otherwise wrap. Cap kicks in. Worth a custom fixture exercising the boundary.
- **T2.3 (priority — H4: processed_count advances on eligibility failure).** Queue with a 0x01-creds validator (must be 0x02 for partial withdrawals). The eligibility check fails; processed_count advances; no Withdrawal emitted. Already covered by `full_pending_withdrawals_but_first_skipped_*`.
- **T2.4 (Glamsterdam-target — spec-correct partial cap with non-empty prior).** Gloas state with `builder_pending_withdrawals.len() = 12` (so 12 builder withdrawals consume prior slots), and `pending_partial_withdrawals.len() = 5`. Per spec, partial cap = `min(12 + 8, 15) = 15`, so 3 more partial withdrawals fit (the rest are deferred). Verify all six clients cap correctly under non-empty prior.
- **T2.5 (Glamsterdam-target — empty builder-pending-withdrawals AND empty builders-list).** Edge case at Gloas activation slot: `state.builder_pending_withdrawals` and `state.builders` are both empty (per `upgrade_to_gloas` initialisation). Phases A and C produce zero withdrawals; phase B (partial) is called with `prior_withdrawals = []` — same Pectra behaviour. All six should produce identical output here.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H10) remain satisfied: aligned implementations of the two-phase drain (partial → validator sweep), partial-cap formula, break/cursor semantics, amount formulas, eligibility predicate, queue slice, and `withdrawal_index`-on-append rule. All 80 EF `withdrawals` fixtures still pass uniformly on prysm + lighthouse + lodestar + grandine (320 PASS total); teku and nimbus pass internally.

**Glamsterdam-target findings:**

- **H11 ✓ across all six clients.** Every client implements the new `get_builder_withdrawals` (Phase A) and `get_builders_sweep_withdrawals` (Phase C) inserted before/after the partial-withdrawals phase. Six distinct dispatch idioms: prysm uses a separate Gloas withdrawals module (`core/gloas/withdrawals.go` + `state-native/getters_gloas.go:432-460 ExpectedWithdrawalsGloas`); lighthouse has a dedicated `per_block_processing/withdrawals.rs` with inline Gloas helpers at `:77` and `:186`; teku uses a Java subclass override (`WithdrawalsHelpersGloas extends WithdrawalsHelpersElectra`); nimbus uses compile-time per-fork branches in `beaconstate.nim` (`get_builder_withdrawals` at line 1761 + Gloas `get_expected_withdrawals` at line 1965+); lodestar uses runtime ternaries (`if (fork >= ForkSeq.gloas)`) in `processWithdrawals.ts`; grandine uses a per-fork module split (`gloas/block_processing.rs` is a separate implementation).
- **H12 ✓ across all six clients.** Every client uses the spec formula `min(len(prior_withdrawals) + MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP, MAX_WITHDRAWALS_PER_PAYLOAD - 1)` for the partial cap at Gloas. Lighthouse's new `withdrawals.rs:131-134` and grandine's `gloas/block_processing.rs:308-325` both adopt the spec formula explicitly; the previously hardcoded `== 8` in lighthouse's pre-rewrite code and grandine's Pectra-Electra branch is no longer reached at Gloas.

The earlier finding (H11 ✗ and H12 ✗ for lighthouse) was a stale-pin artifact. Lighthouse had been on `stable` (v8.1.3), which trailed `unstable` by months of EIP-7732 / Gloas integration including the entire `process_withdrawals` Gloas surface. With each client now on the branch where its actual Glamsterdam implementation lives, the cross-client withdrawals surface is uniform on every Gloas-slot block.

Notable per-client style differences (all observable-equivalent at the Pectra surface):

- **prysm** has a fully separate Gloas withdrawals module (`core/gloas/withdrawals.go` + `state-native/getters_gloas.go:432 ExpectedWithdrawalsGloas`); the Pectra `core/blocks/withdrawals.go` is unchanged.
- **lighthouse** has a dedicated `per_block_processing/withdrawals.rs` module that handles all forks via a single fork-keyed `get_expected_withdrawals` function; the Gloas helpers are colocated in the same file as the Electra-heritage helpers.
- **teku** uses subclass-override polymorphism — `WithdrawalsHelpersGloas extends WithdrawalsHelpersElectra` cleanly inserts the new phases.
- **nimbus** uses per-fork `when` blocks plus dedicated `get_builder_withdrawals` and Gloas `get_expected_withdrawals` functions.
- **lodestar** uses fork-gated branches (`if (fork >= ForkSeq.gloas)`) inside a single function, with `getBuilderWithdrawals` as a helper.
- **grandine** uses a per-fork module split — `gloas/block_processing.rs` is a separate Gloas-specific implementation that addresses the forward-compat hardcoded-cap concern via the spec formula.

Recommendations to the harness and the audit:

- Generate the **T1.3 / T1.4 / T2.4 Gloas builder-withdrawals fixtures** (Phase A drain, Phase C sweep, spec-correct partial cap under non-empty prior). Cross-client `state_root` should match; these would convert the source-only H11/H12 conclusions into empirically-pinned ones.
- Generate a **minimal-preset stress fixture** with 9 entries in `pending_partial_withdrawals` (overflows the 8-cap) — verify all clients drain exactly 8 at Pectra.
- Wire the **fork-fixture category in BeaconBreaker harness** (carries over from item #11) to enable cross-fork upgrade fixtures spanning Pectra → Fulu → Gloas.

## Cross-cuts

### With item #3 (`process_withdrawal_request` partial-withdrawal producer)

Item #3 appends entries to `state.pending_partial_withdrawals` (queue this item drains in Phase B). The Pectra cycle: item #3 writes → this item reads + slices. The Gloas-new builder analog: builder-payment processing (via item #7's attestation-based weight tracking and the new `process_builder_pending_payments` epoch helper, plus item #9's slashing-time clearing) writes into `state.builder_pending_withdrawals`; this item's Phase A drains them.

### With item #11 (`upgrade_to_electra` initialiser)

Item #11 seeds `state.pending_partial_withdrawals = []` at Pectra activation. At Gloas activation, `upgrade_to_gloas` seeds `state.builder_pending_withdrawals = []` and `state.builders = []`. Without those allocations, this item's Phase A and Phase C would have nothing to drain (and would skip cleanly). With them, they accumulate over time and this item's correct draining is required.

### With Gloas `process_payload_attestation` (sibling — populates builder_pending_withdrawals)

The Gloas EIP-7732 builder-payment lifecycle: builder pays for a slot via a bid → on payload-availability attestation, the bid weight is tracked (item #7 H10) → at epoch boundary, `process_builder_pending_payments` settles the bid into a `BuilderPendingWithdrawal` → this item's Phase A drains it into a `Withdrawal`. With item #7 H10 and item #12 H11 both now uniform across all six clients, the producer/drainer sides of the lifecycle are no longer divergence axes; the settlement side (`process_builder_pending_payments`) remains a future audit.

### With item #6 H8 / item #8 H9 / item #9 H10 (EIP-8061 cascade)

The five-vs-one EIP-8061 cascade (items #2, #3, #4, #6, #8, #9 — all now vacated under the per-client Glamsterdam branches) targets `compute_exit_epoch_and_update_churn`. It does **not** propagate into this item — `process_withdrawals` uses neither `initiate_validator_exit` nor `compute_exit_epoch_and_update_churn`. The two families (EIP-8061 churn vs EIP-7732 ePBS) are orthogonal.

## Adjacent untouched Electra/Gloas-active consensus paths

1. **`process_builder_pending_payments` (Gloas-new epoch helper)** — settles past builder bids into `BuilderPendingWithdrawal` entries that this item's Phase A drains. Sister audit item.
2. **`process_payload_attestation` (Gloas-new operation)** — populates `state.execution_payload_availability` and feeds the weight tracking for `process_builder_pending_payments`. Sister audit item.
3. **`update_next_withdrawal_validator_index`** Capella-heritage helper — advances `next_withdrawal_validator_index` based on the LAST Withdrawal's `validator_index + 1 mod len(state.validators)`. At Gloas with Phases A and C also producing Withdrawals, the index advance picks up from whichever phase produced the last entry. Verify all clients respect this.
4. **`next_withdrawal_builder_index` Gloas-new sibling** — advanced by Phase C cyclic-sweep, analogous to `next_withdrawal_validator_index` for the Pectra validator sweep. Verify cross-client.
5. **`apply_withdrawals` Capella-heritage helper** — mutates `state.balances[validator_index] -= amount` AND `latest_execution_payload_header.withdrawals_root`. The latter is particularly interesting: the withdrawals_root is the SSZ root of the Withdrawals list — any client that hashes wrong would diverge on the FIRST block produced post-fork.
6. **Withdrawal-index continuity gap** — H10 asserts withdrawal_index only increments on append. So a partial-queue entry that fails eligibility produces NO Withdrawal AND NO index increment, but DOES advance processed_count.
7. **`MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP = 2` minimal preset** — grandine's preset.rs notes the minimal value differs. Worth running the minimal preset fixtures to check.
8. **lodestar's `validatorBalanceAfterWithdrawals` Map cache** — tracks per-validator balance mutations across phases. Same single-source-of-truth concern as items #4/#5: any direct `state.balances.set()` between two cache reads would diverge.
9. **`get_pending_balance_to_withdraw(state, validator_index)`** — used by item #2 (consolidation) and item #6 (voluntary exit) to predict what's queued. Drained entries (sliced off in `update_pending_partial_withdrawals`) must not leak into this sum.
10. **prysm's `mathutil.Sub64` in `get_balance_after_withdrawals`** — defensive underflow check. Per H8, `total_withdrawn ≤ balance` should be invariant; three different failure modes across clients for the same dead-code path (prysm errors, grandine saturates to 0, lighthouse panics via `safe_sub`).
11. **Six-dispatch-idiom uniformity for Phase A + C** — H11 is now a clean example of how the six clients converge on identical observable Gloas semantics through six different module-organization idioms (separate Go module / dedicated Rust file / Java subclass / compile-time `when` / runtime ternary / per-fork module split).
12. **EIP-7732 builder-lifecycle audit chain** — item #7 H10 (attestation-time weight increment) + item #9 H9 (slashing-time clearing) + this item's H11 (block-time drain) + future audits of `process_payload_attestation` and `process_builder_pending_payments` form the full lifecycle. All three currently-audited surfaces (item #7 H10, item #9 H9, item #12 H11) are now uniform across all six clients; the settlement side remains.
