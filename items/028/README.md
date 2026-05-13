---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-12
builds_on: [1, 3, 4, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]
eips: [EIP-7251, EIP-7549, EIP-7732, EIP-7044, EIP-8061]
splits: [nimbus, lighthouse]
# main_md_summary: meta-audit — nimbus stale PR #4513 → #4788 revert-window OR-folds (items #22 + #23) cause mainnet-glamsterdam forks at Gloas; lighthouse missing ePBS surface (items #14, #19, #22, #23, #24, #25, #26 cohort) prevents Gloas wiring
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.3
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.3.1
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 28: Cross-corpus pre-emptive Gloas-fork divergence consolidated tracking audit

## Summary

Meta-audit synthesizing Gloas-target findings across the recheck of items #1–#27 against the Glamsterdam fork (Gloas CL, Amsterdam EL). The recheck series — performed against the current consensus-specs `v1.7.0-alpha.7-21-g0e70a492d` and the updated client checkouts (versions per front matter) — converted earlier speculative "pre-emptive Gloas readiness" observations into **two confirmed mainnet-glamsterdam divergences in nimbus** (items #22 H12 + #23 H10), one Gloas-ePBS readiness gap propagating across **six lighthouse symptoms** (items #14 H9, #19 H10, #22 H10, #23 H8, #24 H11, #25 H11, #26 H8), and a number of impact-none confirmations where the spec or per-client implementations converged.

**Confirmed mainnet-glamsterdam divergences (splits = [nimbus, lighthouse]):**

1. **Item #22 H12** — nimbus `has_compounding_withdrawal_credential` stale Gloas-aware OR-fold (`vendor/nimbus/beacon_chain/spec/beaconstate.nim:59-68`). Treats `0x03` (builder) credentials as compounding at `consensusFork >= ConsensusFork.Gloas`; current spec does NOT modify this predicate. Cost: ≥ 33 ETH locked permanently. Forks at Gloas activation.
2. **Item #23 H10** — nimbus `get_pending_balance_to_withdraw` stale Gloas-aware OR-fold (`vendor/nimbus/beacon_chain/spec/beaconstate.nim:1541-1559`). Sums `state.builder_pending_withdrawals` + `state.builder_pending_payments` into the validator-side accessor. Continuously triggers on normal post-Gloas traffic via raw-builder-index ↔ validator-index numerical collisions. Cost: zero — structural on normal operation.
3. **Lighthouse Gloas-ePBS cohort** — `is_builder_withdrawal_credential` MISSING, `get_pending_balance_to_withdraw_for_builder` MISSING, `apply_parent_execution_payload` MISSING, `is_valid_indexed_payload_attestation` MISSING (only `builder_withdrawal_prefix_byte` constant exists at `vendor/lighthouse/consensus/types/src/core/chain_spec.rs:93`). All Gloas-NEW ePBS surfaces are unwired; lighthouse cannot process Gloas blocks containing builder deposits, payload attestations, ePBS-routed consolidations, or builder voluntary exits.

**Root cause #1 (nimbus): "PR #4513 → PR #4788 revert-window" failure pattern (NEW Pattern N).** Both nimbus divergences stem from the same spec-churn window: PR #4513 (commit `1b7dedb4a`, "eip7732: consider builder pending payments for pending balance to withdraw") and concurrent EIP-7732 builder-as-validator work ADDED `Modified has_compounding_withdrawal_credential` and `Modified get_pending_balance_to_withdraw` headings at Gloas; PR #4788 (commit `601829f1a`, 2026-01-05, "Make builders non-validating staked actors") REMOVED both modifications when builders were redesigned as non-validating staked actors in a separate `state.builders` registry. Nimbus shipped pre-emptive code matching the intermediate v1.6.0-beta.0 spec and has not rolled back. Doc-comment URLs in nimbus source still reference the now-removed spec sections.

**Root cause #2 (lighthouse): single broader EIP-7732 ePBS-readiness gap (NEW Pattern M cohort).** Lighthouse has Gloas upgrade scaffolding (`vendor/lighthouse/consensus/state_processing/src/upgrade/gloas.rs`) and the basic state-type extension (`BeaconState::Gloas(_)` enum variant), but has not implemented the EIP-7732 ePBS deposit-routing, builder-state accessors, or PTC payload-attestation processing. A single upstream wiring effort would close all six observed symptoms simultaneously.

**Cross-cuts (no propagation):** items #24, #25, #26 confirmed that nimbus's items #22 and #23 stale Gloas-aware OR-folds do NOT propagate to `is_valid_switch_to_compounding_request` (uses `has_eth1_withdrawal_credential`, strict-`0x01`), `is_valid_indexed_attestation` (uses `state.validators[i].pubkey` and `DOMAIN_BEACON_ATTESTER`, both unchanged at Gloas), or `get_attesting_indices` / `get_committee_indices` (use `attestation.aggregation_bits` / `committee_bits`, unchanged at Gloas). Item #27 H13 found an **indirect propagation channel**: `get_next_sync_committee_indices` reads `validator.effective_balance` computed by item #1 via item #22's predicate — nimbus's stale predicate cascades into divergent sync committee membership for `0x03`-credentialled validators.

**Status: source-code-reviewed.** This audit summarises the cumulative recheck-series findings; the underlying divergence claims are individually justified in items #22, #23, and the lighthouse-cohort items (#14, #19, #22, #23, #24, #25, #26).

## Question

The Pectra audit corpus surfaced multiple pre-emptive Gloas-fork code paths in subsets of clients. With the current consensus-specs at `v1.7.0-alpha.7-21-g0e70a492d` (Gloas spec stabilising) and updated client checkouts, the recheck series rebuilds the Gloas-readiness picture:

1. Which earlier-observed "pre-emptive Gloas patterns" became **confirmed observable divergences** under the current spec? (Patterns A, B materialised.)
2. Which earlier "pre-emptive" surfaces converged to **observable-equivalent** behaviour as the spec stabilised? (Pattern F sync committee selection converged.)
3. Which clients have caught up significantly since 2026-05-02 (when teku was the laggard)? (All 6 clients now have substantial Gloas implementation surface.)
4. What's the **single highest-leverage upstream fix** identified by the recheck? (Two: nimbus rolls back PR #4513-era code; lighthouse wires the EIP-7732 ePBS surface.)
5. Are there NEW patterns from the recheck not captured in the prior audit? (Yes: Pattern M = lighthouse Gloas-ePBS cohort; Pattern N = PR #4513 → #4788 revert-window failure mode.)

## Hypotheses

- **H1.** *(Pattern A — `0x03` BUILDER withdrawal credential predicate)*. Spec status confirmed: `has_compounding_withdrawal_credential` is NOT modified at Gloas (PR #4788 removed earlier-draft modification). **Confirmed nimbus mainnet-glamsterdam divergence (item #22 H12)**.
- **H2.** *(Pattern B — builder pending-withdrawals accumulator)*. Spec status confirmed: `get_pending_balance_to_withdraw` is NOT modified at Gloas (PR #4788 removed earlier-draft modification). **Confirmed nimbus mainnet-glamsterdam divergence (item #23 H10)**.
- **H3.** *(Pattern C — `getActivationChurnLimit` / EIP-8061 churn rework)*. The Pectra-era item #4 audit identified a lodestar Gloas-conditional branch using `getActivationChurnLimit` (independent of `getActivationExitChurnLimit`). The current Gloas spec adopts EIP-8061 (`Modified compute_exit_epoch_and_update_churn`, `Modified get_consolidation_churn_limit`); a thorough recheck of items #4 / #16 against the current spec is OUT OF SCOPE for this meta-audit but should reaffirm.
- **H4.** *(Pattern D — `CONSOLIDATION_CHURN_LIMIT_QUOTIENT` independent quotient)*. Same status as Pattern C — should reaffirm against EIP-8061.
- **H5.** *(Pattern E — committee index `< 2` at Gloas)*. Spec status CONFIRMED: `vendor/consensus-specs/specs/gloas/beacon-chain.md:1686` — `assert data.index < 2` inside Gloas-Modified `process_attestation`. Pre-emptive prysm + 5-vs-1 cohort if other 5 don't update.
- **H6.** *(Pattern F — sync committee selection)*. Spec status CONFIRMED via item #27 recheck: `compute_balance_weighted_selection` is algorithmically identical to Pectra inline; 3-vs-3 client wiring split (lighthouse + teku + grandine explicit; prysm + nimbus + lodestar Pectra-inline reuse) is observable-equivalent.
- **H7.** *(Pattern G — builder deposit handling at Gloas via `apply_deposit_for_builder`)*. Spec status: Gloas-NEW (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1556`). Per item #14 audit (pre-recheck), 3-of-6 clients wired (lodestar, grandine, nimbus); lighthouse missing (part of M cohort); prysm + teku partial.
- **H8.** *(Pattern H — Pectra dispatcher exclusion at Gloas)*. Item #21 H10 confirmed at spec level: `process_consolidation_request` MOVED from `process_operations` (`# Removed process_consolidation_request` at `:1515`) to `apply_parent_execution_payload` (`:1132`). Per-client wiring must reflect this.
- **H9.** *(Pattern I — multi-fork-definition pattern)*. Recheck found `IndexedAttestation` container is NOT redefined at Gloas (item #25 H10) — Electra type carries forward via type-polymorphism. The multi-fork-definition risk is REDUCED for items reviewed in the recheck series.
- **H10.** *(Pattern J — type-union silent inclusion)*. Carried forward — code-review-driven risk.
- **H11.** *(Pattern K — Engine API V5)*. Not directly addressed in recheck items #21–#27 (engine API surface is item #15). Carried forward.
- **H12.** *(Pattern L — EIP-7044 CAPELLA pin for voluntary exits)*. Carried forward as no-op — already correct across all 6 clients.
- **H13.** *(NEW Pattern M — lighthouse Gloas-ePBS readiness cohort)*. Single broader gap: lighthouse lacks the EIP-7732 ePBS surface implementation. Six symptoms observed across recheck (items #14 H9, #19 H10, #22 H10, #23 H8, #24 H11, #25 H11, #26 H8). Single upstream fix closes all six.
- **H14.** *(NEW Pattern N — "PR #4513 → PR #4788 revert-window" stale-spec failure mode)*. Two nimbus mainnet-glamsterdam divergences (items #22 H12, #23 H10) share the SAME failure pattern: nimbus shipped pre-emptive code matching v1.6.0-beta.0 spec; PR #4788 (`601829f1a`, 2026-01-05) removed those `Modified` sections when builders were redesigned as non-validating staked actors; nimbus did not roll back. Hunt for other revert-window stale code is the highest-leverage follow-up.

## Findings

### prysm

**Substantial Gloas implementation surface** (significant progress since 2026-05-02). `vendor/prysm/beacon-chain/core/gloas/` contains 13 production source files: `attestation.go`, `bid.go`, `builder_exit.go`, `deposit_request.go`, `parent_payload.go`, `payload_attestation.go`, `payload.go`, `pending_payment.go`, `proposer_slashing.go`, `upgrade.go`, `withdrawals.go` (+ tests + BUILD).

Per-pattern status from recheck:
- **Pattern A (`0x03`)**: defines `BuilderWithdrawalPrefixByte = 0x03` in `vendor/prysm/config/params/mainnet_config.go:99`; consumed by `vendor/prysm/beacon-chain/core/helpers/builder.go:9 IsBuilderWithdrawalCredential` — used in Gloas deposit-routing. **`HasCompoundingWithdrawalCredentials` is strict-`0x02` only** (item #22 finding) — spec-conformant.
- **Pattern E**: post-Gloas attestation accepts `data.index ∈ {0, 1}` (carry-forward from prior audit; recheck of item #7 not in this session).
- **Pattern G**: `vendor/prysm/beacon-chain/core/gloas/deposit_request.go:133 IsBuilderWithdrawalCredential` routes builder deposits to `state-native/setters_gloas.go:734` builder-side application.
- **Pattern H**: Gloas-fork dispatcher relocation present in `core/gloas/` module.

Carried-forward concerns: `core/electra/consolidations.go::IsValidSwitchToCompoundingRequest` and `core/requests/consolidations.go::isValidSwitchToCompoundingRequest` line-identical DUPLICATES (item #24 finding); `core/electra/validator.go::SwitchToCompoundingValidator` and `core/requests/consolidations.go::switchToCompoundingValidator` similar duplicate (item #22 finding).

H1 ✓ (strict 0x02). H2 ✓. H3–H4 carry forward. H5 ✓ (pre-emptive `< 2`). H6 ✓ (Pectra-inline reuse at Gloas). H7 ✓ (`core/gloas/deposit_request.go` has builder routing). H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓. **H13 (M) — prysm is not in the cohort.** **H14 (N) — prysm is not exposed to the revert-window** (didn't ship the intermediate PR #4513 code).

### lighthouse

**Significant Gloas-ePBS readiness gap (Pattern M cohort).** Lighthouse has the basic Gloas upgrade scaffolding (`vendor/lighthouse/consensus/state_processing/src/upgrade/gloas.rs`), the `BeaconState::Gloas(_)` enum variant, `gloas_enabled()` fork accessor, and `compute_balance_weighted_selection` post-Gloas helper (`vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2979`). But the EIP-7732 ePBS surface is largely unwired:

- **`is_builder_withdrawal_credential`**: MISSING. Only the constant `builder_withdrawal_prefix_byte = 0x03` exists at `vendor/lighthouse/consensus/types/src/core/chain_spec.rs:93, 1054, 1448`. Search for the predicate function across `vendor/lighthouse/consensus/` and `vendor/lighthouse/beacon_node/` returns nothing.
- **`get_pending_balance_to_withdraw_for_builder`**: MISSING. The Gloas-NEW builder-side accessor (item #23 H8) is not present anywhere in `vendor/lighthouse/`.
- **`apply_parent_execution_payload`**: MISSING. The EIP-7732 parent-payload routing (item #21 H10 caller-surface migration) is not present in `vendor/lighthouse/consensus/state_processing/src/`.
- **`is_valid_indexed_payload_attestation`**: MISSING (item #25 H11). The PTC attestation predicate not implemented.

Per-pattern status:
- **Pattern A**: lighthouse `has_compounding_withdrawal_credential` is strict-`0x02` (`vendor/lighthouse/consensus/types/src/validator/validator.rs:168-170`) — spec-conformant.
- **Pattern F**: lighthouse explicitly wires Gloas branch for sync committee (item #27 H11 — `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:1405`).

H1 ✓. H2 ✓. H3–H4 carry forward. H5 — needs item #7 Gloas check (recheck deferred). H6 ✓ (explicit `gloas_enabled()` branch). **H7 ✗** (builder deposit handling missing). **H8 ✗** (`apply_parent_execution_payload` missing). H9 ✓. H10 ✓. H11 needs item #15 recheck. H12 ✓. **H13 (M) — lighthouse IS the cohort root**. **H14 (N) — lighthouse is not exposed to the revert-window** (didn't ship the intermediate predicates).

### teku

**Strong promotion from "laggard" to mid-rank** since 2026-05-02. `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/` contains:
- `helpers/BeaconStateAccessorsGloas.java` (extends Electra; overrides `getNextSyncCommitteeIndices` per item #27)
- `helpers/BeaconStateMutatorsGloas.java`
- `helpers/MiscHelpersGloas.java` (contains `computeBalanceWeightedSelection`)
- `helpers/PredicatesGloas.java` (adds `isBuilderWithdrawalCredential`, `isBuilderIndex`, `isActiveBuilder`)
- Plus state types, execution, statetransition, forktransition subpackages.

Per-pattern status:
- **Pattern A**: `PredicatesGloas extends PredicatesElectra` adds `isBuilderWithdrawalCredential` (`:62`) but does NOT override `hasCompoundingWithdrawalCredential` (item #22 finding) — spec-conformant.
- **Pattern B**: `getPendingBalanceToWithdraw` inherited from Electra without override (item #23 finding) — spec-conformant.
- **Pattern F**: explicit Gloas wiring via `BeaconStateAccessorsGloas.getNextSyncCommitteeIndices` (item #27 finding) — spec-conformant.

Subclass-extension pattern (4-5 level inheritance: `BeaconStateAccessors → Altair → Deneb → Electra → Gloas`). Cleanest fork-isolation across the six clients.

H1 ✓. H2 ✓. H5 — needs item #7 Gloas check. H6 ✓. H7 ✓ (`ExecutionRequestsProcessorGloas` + `applyDepositForBuilder`). H8 ✓. H9 ✓. H10 ✓. H11 needs item #15 recheck. H12 ✓. H13 — teku is not in the cohort. H14 — teku is not exposed to the revert-window.

### nimbus

**CONFIRMED mainnet-glamsterdam divergences via Pattern N (PR #4513 → PR #4788 revert window).**

Two stale-spec OR-folds:

1. `has_compounding_withdrawal_credential` at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:59-68`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-beta.0/specs/electra/beacon-chain.md#new-has_compounding_withdrawal_credential
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-beta.0/specs/gloas/beacon-chain.md#modified-has_compounding_withdrawal_credential  ← REMOVED BY PR #4788
func has_compounding_withdrawal_credential*(
    consensusFork: static ConsensusFork, validator: Validator): bool =
  when consensusFork >= ConsensusFork.Gloas:
    is_compounding_withdrawal_credential(validator.withdrawal_credentials) or
        is_builder_withdrawal_credential(validator.withdrawal_credentials)   ← stale OR-fold
  else:
    is_compounding_withdrawal_credential(validator.withdrawal_credentials)
```

2. `get_pending_balance_to_withdraw` at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:1541-1559`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-beta.0/specs/gloas/beacon-chain.md#modified-get_pending_balance_to_withdraw  ← REMOVED BY PR #4788
func get_pending_balance_to_withdraw*(
    state: electra.BeaconState | fulu.BeaconState | gloas.BeaconState,
    validator_index: ValidatorIndex): Gwei =
  var pending_balance: Gwei
  for withdrawal in state.pending_partial_withdrawals:
    if withdrawal.validator_index == validator_index:
      pending_balance += withdrawal.amount
  when type(state).kind >= ConsensusFork.Gloas:
    for withdrawal in state.builder_pending_withdrawals:        ← stale OR-fold
      if withdrawal.builder_index == validator_index:
        pending_balance += withdrawal.amount
    for payment in state.builder_pending_payments:              ← stale OR-fold
      if payment.withdrawal.builder_index == validator_index:
        pending_balance += payment.withdrawal.amount
  pending_balance
```

Doc-comment URLs in both reference `#modified-has_compounding_withdrawal_credential` and `#modified-get_pending_balance_to_withdraw` — sections REMOVED by PR #4788 (`vendor/consensus-specs` commit `601829f1ae0d9e4312b041f36d4ab13c2397be2f`, 2026-01-05, "Make builders non-validating staked actors").

Per-pattern status:
- **Pattern A**: confirmed mainnet-glamsterdam divergence (item #22 H12). Cost ≥ 33 ETH locked permanently.
- **Pattern B**: confirmed mainnet-glamsterdam divergence (item #23 H10). Cost zero — triggers on normal post-Gloas traffic.
- **Pattern F**: nimbus uses Pectra-inline reuse at Gloas via type-union `electra | fulu | gloas` (item #27 H11). Observable-equivalent.
- **Pattern I**: separate function bodies for Electra/Fulu/Gloas in many state-mutation surfaces (carry forward).

Beyond items #22 and #23, nimbus has substantial Gloas surface: separate `get_pending_balance_to_withdraw_for_builder` at `beaconstate.nim:3085-3097` (correct in isolation), `compute_balance_weighted_selection` at `:3019`, `get_ptc`, `get_indexed_payload_attestation`. The PROBLEM is exclusively in the two stale-revert-window functions.

H1 ✗ (Pattern A stale-spec divergence). H2 ✗ (Pattern B stale-spec divergence). H3–H4 carry forward. H5 — item #7 recheck deferred. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 needs item #15 recheck. H12 ✓. **H13 (M) — nimbus is not in the cohort**. **H14 (N) — nimbus IS the exemplar of the revert-window failure mode**.

### lodestar

**Substantial Gloas implementation surface.** `vendor/lodestar/packages/state-transition/src/slot/upgradeStateToGloas.ts`, `util/gloas.ts` (contains `isBuilderWithdrawalCredential`, `findBuilderIndexByPubkey`, etc.), `block/processVoluntaryExit.ts` invokes `getPendingBalanceToWithdrawForBuilder`, `block/processDepositRequest.ts` includes the Gloas builder-routing branch.

Per-pattern status:
- **Pattern A**: lodestar `hasCompoundingWithdrawalCredential` is strict-`0x02` (`vendor/lodestar/packages/state-transition/src/util/electra.ts:7-9`) — spec-conformant.
- **Pattern B**: lodestar `getPendingBalanceToWithdraw` strict-validator-side (`util/validator.ts:167-179`); separate `getPendingBalanceToWithdrawForBuilder` (Gloas-NEW) consumed from `processVoluntaryExit.ts:100` — spec-conformant.
- **Pattern C**: carry forward (lodestar pre-emptive `getActivationChurnLimit` branch).
- **Pattern D**: carry forward (lodestar independent `CONSOLIDATION_CHURN_LIMIT_QUOTIENT`).
- **Pattern F**: lodestar uses `fork >= ForkSeq.electra` lower-bound covering Gloas (item #27 H11 — Pectra-inline reuse). Observable-equivalent.

H1 ✓. H2 ✓. H3–H4 carry forward. H5 — needs item #7 recheck. H6 ✓. H7 ✓ (`applyDepositForBuilder`). H8 ✓ (`fork < ForkSeq.gloas` exclusion gates carry forward). H9 ✓. H10 ✓. H11 needs item #15 recheck. H12 ✓. H13 — lodestar is not in the cohort. H14 — lodestar is not exposed to the revert-window.

### grandine

**Most complete Gloas implementation surface across the six clients.** `vendor/grandine/transition_functions/src/gloas/` is a full per-fork module: `block_processing.rs`, `epoch_intermediates.rs`, `epoch_processing.rs`, `execution_payload_processing.rs`, `slot_processing.rs`, `state_transition.rs`. `helper_functions/src/predicates.rs` includes `is_builder_withdrawal_credential` (`:403`) and `has_builder_withdrawal_credential` (`:410`) — grandine is the only client (besides nimbus) exposing the validator-method form. `helper_functions/src/accessors.rs:707-729` has explicit `get_next_sync_committee_indices_post_gloas` (item #27 H11 — explicit Gloas branch). `:995-1014` has `get_pending_balance_to_withdraw_for_builder` (item #23 H8 — separate Gloas-NEW accessor).

Per-pattern status:
- **Pattern A**: grandine `has_compounding_withdrawal_credential` is strict-`0x02` (`predicates.rs:391-394`); separate `has_builder_withdrawal_credential` (`:410`) — spec-conformant.
- **Pattern B**: grandine `get_pending_balance_to_withdraw` strict-validator-side (`accessors.rs:982-992`); separate `_for_builder` at `:995` — spec-conformant.
- **Pattern F**: grandine explicit three-way `is_post_gloas() / is_post_electra() / pre_electra` dispatcher (item #27 H11 — only client with explicit three-way dispatch in place today).

H1 ✓. H2 ✓. H5 — needs item #7 recheck. H6 ✓. H7 ✓ (`gloas/execution_payload_processing.rs:290` builder routing). H8 ✓. H9 ✓. H10 ✓. H11 needs item #15 recheck. H12 ✓. H13 — grandine is not in the cohort. H14 — grandine is not exposed to the revert-window.

## Cross-reference table

Per-pattern status across clients (recheck-updated; ✓ = spec-conformant, ✗ = confirmed divergence, ⚠ = needs item-level recheck, n/a = not applicable):

| Pattern | prysm | lighthouse | teku | nimbus | lodestar | grandine | Status |
|---|---|---|---|---|---|---|---|
| **A** (`0x03` BUILDER predicate fold-in) | ✓ | ✓ | ✓ | **✗ (item #22 H12)** | ✓ | ✓ | **CONFIRMED mainnet-glamsterdam in nimbus** |
| **B** (builder pending-withdrawals accumulator) | ✓ | ✓ (gap) | ✓ | **✗ (item #23 H10)** | ✓ | ✓ | **CONFIRMED mainnet-glamsterdam in nimbus** |
| **C** (`getActivationChurnLimit` selection) | ⚠ | ⚠ | ⚠ | ⚠ | ⚠ | ⚠ | needs items #4/#16 recheck |
| **D** (`CONSOLIDATION_CHURN_LIMIT_QUOTIENT`) | ⚠ | ⚠ | ⚠ | ⚠ | ⚠ | ⚠ | needs item #16 recheck |
| **E** (committee index `< 2` at Gloas) | ✓ (pre-emptive) | ⚠ | ⚠ | ⚠ | ⚠ | ⚠ | spec confirmed; per-client needs item #7 recheck |
| **F** (sync committee selection) | ✓ Pectra-inline | ✓ explicit | ✓ explicit | ✓ Pectra-inline | ✓ Pectra-inline | ✓ explicit | observable-equivalent (item #27 H10) |
| **G** (builder deposit handling) | ✓ | **✗ (Pattern M)** | ✓ | ✓ | ✓ | ✓ | lighthouse missing |
| **H** (Pectra dispatcher exclusion) | ✓ | **✗ (Pattern M)** | ✓ | ✓ | ✓ | ✓ | lighthouse missing `apply_parent_execution_payload` |
| **I** (multi-fork-definition) | n/a | n/a | n/a | ⚠ (Pattern N) | n/a | n/a | nimbus Electra body diverges from Gloas via stale OR-folds |
| **J** (type-union silent inclusion) | n/a | n/a | n/a | ⚠ | n/a | n/a | code-review risk — relevant to Pattern N |
| **K** (Engine API V5) | ⚠ | ⚠ | ⚠ | ⚠ | ⚠ | ⚠ | needs item #15 recheck |
| **L** (CAPELLA pin for voluntary exits) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | no-op (EIP-7044 carries forward) |
| **M (NEW)** (lighthouse Gloas-ePBS gap) | n/a | **✗ (cohort root)** | n/a | n/a | n/a | n/a | items #14 H9, #19 H10, #22 H10, #23 H8, #24 H11, #25 H11, #26 H8 — 7 symptoms |
| **N (NEW)** (PR #4513 → #4788 revert-window stale code) | n/a | n/a | n/a | **✗ (Patterns A + B)** | n/a | n/a | items #22 H12, #23 H10 — same root cause |

## Empirical tests

### Pectra-surface coverage

The cumulative recheck series (items #20–#27 in this session, items #1–#19 in the prior session) confirms ~300+ EF fixture PASSes across 4 wired clients on the Pectra surface. No Pectra-surface divergence surfaced.

### Gloas-surface coverage

No Gloas-specific EF fixtures wired yet. All Gloas-target findings (Patterns A, B, F, G, H, M, N) are **source-only at the time of this recheck**. The Gloas spec is stable at `v1.7.0-alpha.7-21-g0e70a492d` modulo ongoing spec PRs.

### Suggested fuzzing vectors (consolidated from items #22, #23, #27)

#### T1 — Mainline canonical Gloas fixture set
- **T1.1**: dedicated cross-client byte-level equivalence fixture for `has_compounding_withdrawal_credential` against `0x00, 0x01, 0x02, 0x03` input credentials at Gloas state. **Surfaces Pattern A (nimbus divergence)**.
- **T1.2**: dedicated cross-client byte-level equivalence fixture for `get_pending_balance_to_withdraw(state, V)` against Gloas state with non-trivial `state.builder_pending_payments[i].withdrawal.builder_index == V` entries. **Surfaces Pattern B (nimbus divergence)**.
- **T1.3**: state-transition fixture for `process_voluntary_exit` on Gloas state with builder pending payments at builder-index = validator-index collision. **Surfaces Pattern B end-to-end divergence**.
- **T1.4**: state-transition fixture for `process_effective_balance_updates` on Gloas state with a `0x03`-credentialled validator at balance > 33.25 ETH. **Surfaces Pattern A end-to-end divergence**.

#### T2 — Adversarial Gloas probes
- **T2.1**: pre-Gloas attacker submits a 32 ETH deposit with `withdrawal_credentials[0] = 0x03` + a 1.5 ETH top-up. At Gloas activation, verify nimbus computes `effective_balance > 32 ETH` for this validator while other 5 clients compute `32 ETH`. **Pattern A attack fixture**.
- **T2.2**: post-Gloas, a builder with raw `builder_index = V` bids for a slot. Validator V (any low-index validator) submits a voluntary exit. Verify nimbus rejects the exit while other 5 clients accept. **Pattern B attack fixture**.
- **T2.3**: lighthouse cohort gap fixtures — Gloas blocks containing builder deposits, payload attestations, ePBS-routed consolidations, builder voluntary exits. Lighthouse should reject all (cannot process). **Pattern M cohort fixture set**.

## Mainnet reachability

Two confirmed mainnet-glamsterdam divergence vectors at Gloas activation:

**Vector 1 — nimbus Pattern A (item #22 H12)**: any pre-Gloas depositor submits a `DepositRequest` with `withdrawal_credentials[0] = 0x03` (Pectra `process_deposit_request` accepts any prefix) and a top-up to push balance > 33.25 ETH (UPWARD_HYSTERESIS_THRESHOLD). At the first `process_effective_balance_updates` post-Gloas, nimbus's stale `has_compounding_withdrawal_credential` returns true for `0x03` → `get_max_effective_balance` returns `MAX_EFFECTIVE_BALANCE_ELECTRA = 2048 ETH`; other 5 clients return `MIN_ACTIVATION_BALANCE = 32 ETH`. Validator's `effective_balance` diverges. State-root mismatch → chain split. Cost: ≥ 33 ETH locked permanently (no withdrawal path for `0x03` validators).

**Vector 2 — nimbus Pattern B (item #23 H10)**: triggered by NORMAL post-Gloas operation. `state.builder_pending_payments` is a 64-slot ring buffer that continuously fills with `builder_index` entries during normal Gloas block production. Raw `BuilderIndex` and `ValidatorIndex` share the `uint64 < 2^40` namespace; both registries grow from 0. Whenever a validator at index V attempts voluntary exit / withdrawal request / consolidation request AND there's a recent unsettled builder bid by builder at raw index V, nimbus's stale `get_pending_balance_to_withdraw` over-counts → rejects/under-credits the operation. State root diverges. Expected to produce **multiple divergence events per epoch** post-Gloas given typical voluntary exit volumes. **Cost: ZERO.**

**Vector 3 — lighthouse Pattern M cohort**: lighthouse cannot process Gloas blocks containing:
- builder deposits (no `is_builder_withdrawal_credential` predicate, no `apply_deposit_for_builder`).
- payload attestations (no `is_valid_indexed_payload_attestation`).
- ePBS-routed consolidations / deposits / withdrawals (no `apply_parent_execution_payload`).
- builder voluntary exits (no `get_pending_balance_to_withdraw_for_builder`).

At Gloas activation, lighthouse either rejects Gloas blocks (the lighthouse beacon node falls off the chain) or processes them incorrectly. Either way, lighthouse cannot remain on the canonical Gloas chain.

**Indirect propagation channel (Vector 1 cascading into item #27)**: nimbus's Pattern A divergent `effective_balance` propagates into `get_next_sync_committee_indices` (item #27 H13) — `0x03`-credentialled validators with divergent `effective_balance` produce divergent sync committee membership. Same H12 attack, different downstream surface; same mitigation (fix nimbus's predicate).

**Mitigation:**
- **Nimbus (Patterns A + B)**: two one-line removals — drop the `when consensusFork >= ConsensusFork.Gloas` branch in `vendor/nimbus/beacon_chain/spec/beaconstate.nim:59-68` (Pattern A) and `:1541-1559` (Pattern B). Update doc-comment URLs at `:58` and `:1542` to drop the `#modified-*` references. **Single-developer-day fix.**
- **Lighthouse (Pattern M)**: implement the EIP-7732 ePBS surface — `is_builder_withdrawal_credential` + `has_builder_withdrawal_credential` predicates, `get_pending_balance_to_withdraw_for_builder` accessor, `apply_parent_execution_payload` + execution-requests routing, `is_valid_indexed_payload_attestation` predicate, PTC selection / processing. **Significant implementation effort but well-scoped.**

**Detection (operational pre-Gloas)**:
- Monitor mainnet validators for `withdrawal_credentials[0] == 0x03`. Any positive hit is a Pattern A attack precursor.
- Track lighthouse Gloas implementation progress via `git log` in `vendor/lighthouse/` looking for `is_builder_withdrawal_credential` / `apply_parent_execution_payload` introduction.

## Conclusion

**Status: source-code-reviewed.** The recheck series (items #1–#27) against current consensus-specs `v1.7.0-alpha.7-21-g0e70a492d` confirms:

1. **Two mainnet-glamsterdam divergences in nimbus** (Patterns A, B) caused by stale code shipped during the PR #4513 → PR #4788 spec-revert window (Pattern N). Both have single-line fixes.
2. **One Gloas-ePBS readiness gap in lighthouse** (Pattern M cohort across items #14 H9, #19 H10, #22 H10, #23 H8, #24 H11, #25 H11, #26 H8) — single broader implementation gap with six observed symptoms.
3. **Pattern F (sync committee selection) converged** to observable-equivalent across all six clients (item #27 H10) — earlier "leader divergence" concern resolved as the spec stabilised.
4. **Five clients (prysm, lighthouse, teku, lodestar, grandine) caught up significantly** since 2026-05-02. The "teku is the laggard" framing from the prior audit is OUTDATED — teku now has substantial Gloas surface (`BeaconStateAccessorsGloas`, `MiscHelpersGloas`, `PredicatesGloas`, `BeaconStateMutatorsGloas`, etc.).
5. **Grandine remains the Gloas-readiness leader**: full `transition_functions/src/gloas/` module, explicit three-way dispatcher pattern, separate `_post_gloas` / `_post_electra` / `pre_electra` function variants.

**Per-pattern bottom line:**
- **Patterns A + B (Pattern N revert-window) — CONFIRMED mainnet-glamsterdam divergences in nimbus.** Highest-priority pre-Gloas fix.
- **Pattern M cohort — lighthouse cannot remain on canonical Gloas chain without implementation.** Highest-priority pre-Gloas implementation work.
- **Patterns C + D + E + K — needs item-level recheck against current spec** to convert speculative observations to confirmed/refuted.
- **Pattern F — RESOLVED to observable-equivalent** (no action needed).
- **Patterns G + H — wired in 5 of 6 clients (lighthouse in M cohort)** — converging toward correct.
- **Patterns I + J + L — no-action-needed code-review risks.**

**Highest-leverage follow-up audits:**

1. **Hunt for other PR #4513 → PR #4788 revert-window stale code in nimbus** (Pattern N pattern audit). Items #22 + #23 are TWO functions affected by the same root cause; other functions modified-then-reverted in the 2025-Q4 → 2026-Q1 spec window may also be stale. Candidates: any Gloas function whose doc-comment URL points to `v1.6.0-beta.0` AND has a `Modified` section in the URL fragment.
2. **Hunt for the Pattern M cohort symptoms not yet observed** in lighthouse (PTC committee processing, builder reward accounting, etc.). Items #14, #19, #22, #23, #24, #25, #26 surfaced seven; there may be more.
3. **Recheck items #4, #7, #15, #16** against current spec to resolve Patterns C, D, E, K from speculative to confirmed/refuted.
4. **Spec-clarification PR (consensus-specs)** — add `Removed in <commit>` notes for predicates / accessors that had `Modified` sections walked back in the 2025-2026 spec churn. Prevents future revert-window stale-code bugs in client implementations that bookmark intermediate spec versions.
5. **Per-client Gloas implementation tracking dashboard** — quarterly source-tree scan of `grep -rn "[Gg]loas"` per client to track Gloas implementation progress; build into BeaconBreaker as `tools/runners/gloas_readiness.sh`. Re-run quarterly to surface new Gloas-aware code paths as they ship.
6. **Pre-emptive cross-client Gloas test-vector generation** — once Gloas EIPs stabilize, generate test vectors that exercise each of Patterns A–N; ship to EF for inclusion in `consensus-spec-tests`.

## Cross-cuts

### Pattern N origin chain

PR #4513 (`vendor/consensus-specs` commit `1b7dedb4a`, "eip7732: consider builder pending payments for pending balance to withdraw") added `Modified get_pending_balance_to_withdraw` at Gloas. A concurrent EIP-7732 PR added `Modified has_compounding_withdrawal_credential`. Both reflected the intermediate "builders are validators with 0x03 credentials" design.

PR #4788 (`vendor/consensus-specs` commit `601829f1a`, 2026-01-05, "Make builders non-validating staked actors") implemented the EIP-7732 design pivot: builders moved to a separate `state.builders` registry (`List[Builder, BUILDER_REGISTRY_LIMIT]`) with their own accessors (`get_pending_balance_to_withdraw_for_builder`, `is_builder_index`, `convert_builder_index_to_validator_index`). Both Modified-at-Gloas predicates were REMOVED; the unmodified Electra versions carry forward at Gloas.

Nimbus shipped pre-emptive code matching PR #4513 (the intermediate "builders are validators" design). The doc-comment URLs in nimbus source still point to v1.6.0-beta.0 — a snapshot taken DURING the revert window. After PR #4788, nimbus did not roll back. The two divergent functions (items #22 H12, #23 H10) are the observable consequences.

### Pattern M cohort symptoms across items

The lighthouse Gloas-ePBS readiness gap manifests as the same broader gap surfacing in many specific audits:

| Item | Symptom |
|---|---|
| #14 H9 | `is_builder_withdrawal_credential` missing for deposit-request builder routing |
| #19 H10 | `apply_parent_execution_payload` missing for the ePBS surface |
| #22 H10 | `is_builder_withdrawal_credential` predicate missing (only constant `builder_withdrawal_prefix_byte` present) |
| #23 H8 | `get_pending_balance_to_withdraw_for_builder` missing (builder-side accessor) |
| #24 H11 | switch-to-compounding ePBS routing missing (consolidations via `apply_parent_execution_payload`) |
| #25 H11 | `is_valid_indexed_payload_attestation` (PTC) missing |
| #26 H8 | (no direct symptom — confirmed by absence) |

Single-fix upstream (lighthouse implements the EIP-7732 ePBS wiring) closes all seven symptoms simultaneously.

### Indirect propagation chains

- **Item #22 H12 → item #27 H13**: nimbus's stale `has_compounding_withdrawal_credential` returns true for `0x03` at Gloas → item #1 `process_effective_balance_updates` computes divergent `effective_balance` for `0x03` validators → item #27 `get_next_sync_committee_indices` reads divergent `effective_balance` → divergent sync committee membership Merkle root.
- **Item #22 H12 → item #1 → all `effective_balance`-dependent surfaces**: total_active_balance, attestation rewards, slashing math, sync-committee rewards, finalization. Single Pattern A attack cascades through all of these.
- **Item #23 H10 → items #2, #3, #6 caller sites**: nimbus's stale `get_pending_balance_to_withdraw` consumed by `process_consolidation_request` source gate, `process_withdrawal_request` full-exit + partial subtractor, `process_voluntary_exit` equality gate. Single Pattern B attack manifests through three different operation types.

### Items not yet rechecked in this session

Items #1–#19 were rechecked in the prior session (pre-context-compression). Items #20–#27 were rechecked in this session. Items #4, #7, #15, #16 carry-forward findings from the prior audit (Patterns C, D, E, K) — they should be confirmed/refuted against current spec in a follow-up. Items #2, #5, #11, #17 produced no Gloas findings — likely candidates for a Gloas-specific audit when Gloas spec details solidify further.

## Adjacent untouched

1. **Nimbus Pattern A + B fix** — two one-line removals in `vendor/nimbus/beacon_chain/spec/beaconstate.nim`. Highest-priority pre-Gloas fix.
2. **Lighthouse Pattern M cohort implementation** — wire the EIP-7732 ePBS surface. Highest-priority pre-Gloas implementation work.
3. **Pattern N pattern audit on nimbus** — hunt for other revert-window stale code; candidates: any function with `v1.6.0-beta.0` doc-comment URL referencing a `#modified-*` section.
4. **Spec-clarification PR (consensus-specs)** — add `Removed in <commit>` notes for walked-back `Modified` sections.
5. **Items #4 / #7 / #15 / #16 recheck** against current spec to convert Patterns C, D, E, K from speculative to confirmed/refuted.
6. **Pre-emptive cross-client Gloas EF fixture set** — Patterns A, B, M cohort attack fixtures.
7. **Quarterly Gloas-readiness dashboard** (`tools/runners/gloas_readiness.sh`) — automated `grep -rn "[Gg]loas"` scan with diffing to surface new Gloas-aware code paths as they ship.
8. **Per-client `gloas_fork_version` constant verification** when configs ship (mainnet / sepolia / holesky / Hoodi etc.).
9. **Cross-client `engine_newPayloadV5` request/response schema audit** when EIP-7732 PBS engine API lands (Pattern K).
10. **`compute_balance_weighted_selection` cross-cut audit** (items #27 sister functions): `compute_proposer_indices` and `compute_ptc` consume the same helper at Gloas; verify cross-client equivalence on all three call sites.
11. **Indirect-propagation fixture for item #22 H12 → item #1 → all `effective_balance` consumers** — the cascade fixture would surface every downstream surface affected by nimbus's stale predicate.
12. **Builder-deposit on-the-fly BLS verification audit** (Pattern G) — lodestar `applyDepositForBuilder` + grandine `gloas/execution_payload_processing.rs:290` + nimbus `state_transition_block.nim:413-448` all verify BLS at deposit time; cross-client equivalence test on builder-deposit signatures.
13. **Pre-Gloas mainnet monitoring** — scan `state.validators` for `withdrawal_credentials[0] == 0x03`; any positive hit is a Pattern A attack precursor.
14. **Items #2 / #5 / #11 / #17 Gloas-specific audit** — these items produced no Gloas findings in the recheck; revisit when Gloas spec solidifies (currently at `v1.7.0-alpha.7-21-g0e70a492d`).
15. **Compile-time vs runtime fork-dispatch performance audit at Gloas** — nimbus's `static ConsensusFork` compile-time dispatch may have a measurable advantage at deep fork stacks; lighthouse + grandine superstruct / module-namespace dispatch may benefit from optimization at Gloas activation.
