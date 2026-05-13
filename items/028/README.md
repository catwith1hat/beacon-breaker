---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-13
builds_on: [1, 3, 4, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]
eips: [EIP-7251, EIP-7549, EIP-7732, EIP-7044, EIP-8061]
splits: [nimbus]
# main_md_summary: meta-audit — two nimbus stale PR #4513 → #4788 revert-window OR-folds (items #22 + #23) cause mainnet-glamsterdam forks at Gloas; the prior lighthouse Pattern M cohort (items #14, #19, #22 H10, #23 H8, #24, #25, #26) has fully closed under the unstable HEAD pin
prysm_version: v3.2.2-rc.1-2535-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 28: Cross-corpus pre-emptive Gloas-fork divergence consolidated tracking audit

## Summary

Meta-audit synthesizing Gloas-target findings across items #1–#27 against the Glamsterdam fork (Gloas CL, Amsterdam EL). Under the per-client Glamsterdam branches — prysm `EIP-8061`, teku `glamsterdam-devnet-2`, grandine `glamsterdam-devnet-3`, lighthouse + nimbus + lodestar `unstable` — the recheck-2 series collapses the prior multi-divergence picture into **two confirmed mainnet-glamsterdam divergences in nimbus alone** (items #22 H12 + #23 H10), with the entire lighthouse Pattern M ePBS cohort and the EIP-8061 family closed.

**Confirmed mainnet-glamsterdam divergences (splits = [nimbus]):**

1. **Item #22 H12** — nimbus `has_compounding_withdrawal_credential` stale Gloas-aware OR-fold (`vendor/nimbus/beacon_chain/spec/beaconstate.nim:59-68`). Treats `0x03` (builder) credentials as compounding at `consensusFork >= ConsensusFork.Gloas`; current spec does NOT modify this predicate. Cost: ≥ 33 ETH locked permanently. Forks at Gloas activation.
2. **Item #23 H10** — nimbus `get_pending_balance_to_withdraw` stale Gloas-aware OR-fold (`vendor/nimbus/beacon_chain/spec/beaconstate.nim:1588-1607`). Sums `state.builder_pending_withdrawals` + `state.builder_pending_payments` into the validator-side accessor. Continuously triggers on normal post-Gloas traffic via raw-builder-index ↔ validator-index numerical collisions. Cost: zero — structural on normal operation.

**Closed under the per-client Glamsterdam branches:**

1. **Lighthouse Pattern M ePBS cohort fully vacated.** `is_builder_withdrawal_credential` (`vendor/lighthouse/consensus/types/src/validator/validator.rs:318`), `get_pending_balance_to_withdraw_for_builder` (`beacon_state.rs:2829`), `apply_parent_execution_payload` (`per_block_processing.rs:589`), `is_valid_indexed_payload_attestation` (`per_block_processing/is_valid_indexed_payload_attestation.rs:6`) — all four ePBS surfaces are now wired. Items #14 H9, #19 H10, #22 H10 (lighthouse missing predicate), #23 H8 (lighthouse missing builder accessor), #24 H11, #25 H11, #26 H8 — all closed.
2. **EIP-8061 churn family closed.** Items #2 H6, #3 H8, #4 H8, #6 H8, #8 H9, #9 H10, #17 H10 (seven cascade entry-points) plus #16 H12-H15 (chokepoint) all vacated. All six clients fork-gate `compute_exit_epoch_and_update_churn` to consume `get_exit_churn_limit` at Gloas via six distinct dispatch idioms.
3. **EIP-7732 ePBS lifecycle closed across all six clients.** Items #7 H9/H10 (process_attestation `data.index < 2` + builder-payment weight), #9 H9 (proposer slashing BuilderPendingPayment clearing), #12 H11 (Gloas withdrawal phases), #13 H10 (process_operations restructure), #14 H9 (deposit builder routing), #19 H10 (process_execution_payload removal + three new helpers), #15 H10 (Engine API V5) — all vacated.

**Root cause (nimbus): "PR #4513 → PR #4788 revert-window" failure pattern (Pattern N).** Both remaining nimbus divergences stem from the same spec-churn window: PR #4513 (commit `1b7dedb4a`, "eip7732: consider builder pending payments for pending balance to withdraw") and concurrent EIP-7732 builder-as-validator work ADDED `Modified has_compounding_withdrawal_credential` and `Modified get_pending_balance_to_withdraw` headings at Gloas; PR #4788 (commit `601829f1a`, 2026-01-05, "Make builders non-validating staked actors") REMOVED both modifications when builders were redesigned as non-validating staked actors in a separate `state.builders` registry. Nimbus shipped pre-emptive code matching the intermediate v1.6.0-beta.0 spec and has not rolled back. Doc-comment URLs in nimbus source still reference the now-removed spec sections at `beaconstate.nim:57-58` and `:1588-1589`.

**Status: source-code-reviewed.** This meta-audit synthesises the recheck-2 series; the underlying divergence claims are individually justified in items #22 and #23.

## Question

The recheck-2 series rebuilds the Gloas-readiness picture under the now-branch-symmetric pins (each client on the branch where its actual Glamsterdam implementation lives):

1. Which earlier-observed "pre-emptive Gloas patterns" became **confirmed observable divergences** under the current spec? (Patterns A + B materialised in nimbus only.)
2. Which earlier "pre-emptive" surfaces converged to **observable-equivalent** behaviour as the spec stabilised? (Pattern F sync committee selection converged; Pattern M ePBS cohort closed.)
3. Which clients have caught up significantly since the prior recheck? (Lighthouse closed its entire ePBS Pattern M cohort under `unstable`. The five Glamsterdam-feature-branch pins for prysm/teku/grandine plus `unstable` for lighthouse/nimbus/lodestar give branch-symmetric coverage.)
4. What's the **single highest-leverage upstream fix** identified by the recheck? (Nimbus rolls back PR #4513-era code at `beaconstate.nim:59-68` and `:1588-1607`.)
5. Are there NEW patterns from the recheck not captured in the prior audit? (Pattern N — PR #4513 → #4788 revert-window failure mode — remains. Pattern M cohort has closed.)

## Hypotheses

- **H1.** *(Pattern A — `0x03` BUILDER withdrawal credential predicate)*. Spec status confirmed: `has_compounding_withdrawal_credential` is NOT modified at Gloas (PR #4788 removed earlier-draft modification). **Confirmed nimbus mainnet-glamsterdam divergence (item #22 H12)**.
- **H2.** *(Pattern B — builder pending-withdrawals accumulator)*. Spec status confirmed: `get_pending_balance_to_withdraw` is NOT modified at Gloas (PR #4788 removed earlier-draft modification). **Confirmed nimbus mainnet-glamsterdam divergence (item #23 H10)**.
- **H3.** *(Pattern C — `getActivationChurnLimit` / EIP-8061 churn rework)*. **CLOSED** by items #4 H8 + #16 H14 vacation. All six clients fork-gate the activation-churn helper at Gloas.
- **H4.** *(Pattern D — `CONSOLIDATION_CHURN_LIMIT_QUOTIENT` independent quotient)*. **CLOSED** by items #2 H6 + #16 H13 vacation. All six clients fork-gate the consolidation-churn helper to the Gloas quotient formula.
- **H5.** *(Pattern E — committee index `< 2` at Gloas)*. **CLOSED** by item #7 H9 vacation. All six clients fork-gate `data.index < 2` at Gloas.
- **H6.** *(Pattern F — sync committee selection)*. **CLOSED** by item #27 H10 (carry-forward from prior session) — algorithmically identical via Pectra-inline reuse vs explicit Gloas branch.
- **H7.** *(Pattern G — builder deposit handling at Gloas via `apply_deposit_for_builder`)*. **CLOSED** by item #14 H9 vacation. All six clients implement builder-routing branch + `apply_deposit_for_builder`.
- **H8.** *(Pattern H — Pectra dispatcher exclusion at Gloas)*. **CLOSED** by item #13 H10 vacation. All six clients route requests through `apply_parent_execution_payload` at Gloas.
- **H9.** *(Pattern I — multi-fork-definition pattern)*. Carry forward — code-review risk; reduced exposure post-recheck (most multi-fork-definition risks reviewed).
- **H10.** *(Pattern J — type-union silent inclusion)*. Carry forward — code-review risk; Pattern N is the materialised exemplar (nimbus's `electra | fulu | gloas` union type with stale body).
- **H11.** *(Pattern K — Engine API V5)*. **CLOSED** by item #15 H10 vacation. Lighthouse and grandine both now wire V5 dispatch.
- **H12.** *(Pattern L — EIP-7044 CAPELLA pin for voluntary exits)*. **CLOSED** — no-op; correct across all 6 clients.
- **H13.** *(Pattern M — lighthouse Gloas-ePBS readiness cohort)*. **CLOSED** — all four ePBS surfaces (`is_builder_withdrawal_credential`, `get_pending_balance_to_withdraw_for_builder`, `apply_parent_execution_payload`, `is_valid_indexed_payload_attestation`) now wired in lighthouse. Items #14 H9, #19 H10, #24 H11, #25 H11, #26 H8 all vacated; items #22 H10 / #23 H8 lighthouse-side claims vacated (nimbus side stands).
- **H14.** *(Pattern N — "PR #4513 → PR #4788 revert-window" stale-spec failure mode)*. Two nimbus mainnet-glamsterdam divergences (items #22 H12, #23 H10) share the SAME failure pattern. **STILL ACTIVE.** Hunt for other revert-window stale code is the highest-leverage follow-up.

## Findings

### prysm

**Full Gloas implementation surface on the EIP-8061 branch.** Per-pattern status from recheck-2:
- **Pattern A**: `BuilderWithdrawalPrefixByte = 0x03` consumed by `helpers/builder.go:9 IsBuilderWithdrawalCredential` in Gloas deposit-routing; `HasCompoundingWithdrawalCredentials` is strict-`0x02` — spec-conformant.
- **Patterns C, D, E, G, H, K**: all wired (items #4 H8, #16 H14, #2 H6, #16 H13, #7 H9, #14 H9, #13 H10, #15 H10).
- **Pattern F**: observable-equivalent.

H1 ✓. H2 ✓. H3 ✓ (item #4 H8 fix). H4 ✓ (item #2 H6 fix). H5 ✓ (item #7 H9 fix). H6 ✓. H7 ✓ (item #14 H9 fix). H8 ✓ (item #13 H10 fix). H9 ✓. H10 ✓. H11 ✓ (item #15 H10 fix). H12 ✓. **H13 (M) — prysm is not in the cohort.** **H14 (N) — prysm is not exposed to the revert-window.**

### lighthouse

**Full Gloas-ePBS surface wired on the `unstable` HEAD `1a6863118` pin.** The recheck-2 confirmed all Pattern M cohort symptoms have closed:

- `is_builder_withdrawal_credential` at `vendor/lighthouse/consensus/types/src/validator/validator.rs:318` — predicate wired.
- `get_pending_balance_to_withdraw_for_builder` at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2829` — builder-side accessor wired.
- `apply_parent_execution_payload` at `vendor/lighthouse/consensus/state_processing/src/per_block_processing.rs:589` — EIP-7732 parent-payload routing wired.
- `is_valid_indexed_payload_attestation` at `vendor/lighthouse/consensus/state_processing/src/per_block_processing/is_valid_indexed_payload_attestation.rs:6` — PTC attestation predicate wired.

Plus the three Gloas helpers from item #19 (`process_execution_payload_bid`, `process_parent_execution_payload`, `verify_execution_payload_envelope`) and the EIP-8061 chokepoint fork-gate at `beacon_state.rs:2906-2910`. The state-allocation step in `upgrade/gloas.rs` is matched by per-block consumption across the audit family.

Per-pattern status:
- **Pattern A**: `has_compounding_withdrawal_credential` is strict-`0x02` (`validator.rs:168-170`) — spec-conformant.
- **Pattern F**: explicit `gloas_enabled()` branch at `beacon_state.rs:1405` — spec-conformant.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (item #14 H9 fix at `process_operations.rs:940-994`). H8 ✓ (item #13 H10 fix at `process_operations.rs:47-68`). H9 ✓. H10 ✓. H11 ✓ (item #15 H10 fix at `engine_api/http.rs:38`). H12 ✓. **H13 (M) — lighthouse vacated the cohort.** **H14 (N) — lighthouse is not exposed to the revert-window.**

### teku

**Full Gloas-ePBS surface wired on the `glamsterdam-devnet-2` pin.** Per-pattern status:
- **Pattern A**: `PredicatesGloas extends PredicatesElectra` adds `isBuilderWithdrawalCredential` but does NOT override `hasCompoundingWithdrawalCredential` — spec-conformant.
- **Pattern B**: `getPendingBalanceToWithdraw` inherited from Electra without override — spec-conformant.
- **Pattern F**: explicit Gloas wiring via `BeaconStateAccessorsGloas.getNextSyncCommitteeIndices` — spec-conformant.
- **Patterns C, D, E, G, H, K**: all wired (subclass-override polymorphism across `BeaconStateAccessorsGloas`, `BeaconStateMutatorsGloas`, `MiscHelpersGloas`, `PredicatesGloas`).

Subclass-extension pattern (4-5 level inheritance: `BeaconStateAccessors → Altair → Deneb → Electra → Gloas`). Cleanest fork-isolation across the six clients.

H1 ✓. H2 ✓. H3–H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓. H13 — teku is not in the cohort. H14 — teku is not exposed to the revert-window.

### nimbus

**CONFIRMED mainnet-glamsterdam divergences via Pattern N (PR #4513 → PR #4788 revert window).** This is the ONLY client carrying active mainnet-glamsterdam divergences at the current pins.

Two stale-spec OR-folds at `unstable` HEAD `3802d96291`:

1. `has_compounding_withdrawal_credential` at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:59-68`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-beta.0/specs/electra/beacon-chain.md#new-has_compounding_withdrawal_credential
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-beta.0/specs/gloas/beacon-chain.md#modified-has_compounding_withdrawal_credential  ← REMOVED BY PR #4788
func has_compounding_withdrawal_credential*(
    consensusFork: static ConsensusFork, validator: Validator): bool =
  when consensusFork >= ConsensusFork.Gloas:
    ## Check if ``validator`` has an 0x02 or 0x03 prefixed withdrawal credential.
    is_compounding_withdrawal_credential(validator.withdrawal_credentials) or
        is_builder_withdrawal_credential(validator.withdrawal_credentials)   ← stale OR-fold
  else:
    ## Check if ``validator`` has an 0x02 prefixed "compounding" withdrawal credential.
    is_compounding_withdrawal_credential(validator.withdrawal_credentials)
```

2. `get_pending_balance_to_withdraw` at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:1588-1607`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-beta.0/specs/electra/beacon-chain.md#new-get_pending_balance_to_withdraw
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-beta.0/specs/gloas/beacon-chain.md#modified-get_pending_balance_to_withdraw  ← REMOVED BY PR #4788
func get_pending_balance_to_withdraw*(
    state: electra.BeaconState | fulu.BeaconState | gloas.BeaconState | heze.BeaconState,
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

Doc-comment URLs at lines 57-58 and 1588-1589 still reference the v1.6.0-beta.0 `#modified-*` sections REMOVED by PR #4788. Nimbus did not roll back.

Beyond items #22 and #23, nimbus has substantial Gloas surface: separate `get_pending_balance_to_withdraw_for_builder`, `compute_balance_weighted_selection`, `get_ptc`, `get_indexed_payload_attestation`, plus all the EIP-8061 churn helpers fork-gated via compile-time `when typeof(state).kind >= ConsensusFork.Gloas`. The PROBLEM is exclusively in the two stale-revert-window functions.

H1 ✗ (Pattern A stale-spec divergence). H2 ✗ (Pattern B stale-spec divergence). H3–H4 ✓ (items #2 H6, #4 H8 vacated). H5 ✓. H6 ✓. H7 ✓ (item #14 H9 fix). H8 ✓ (item #13 H10 fix). H9 ✓. H10 ✓. H11 ✓ (item #15 H10 fix). H12 ✓. **H13 (M) — nimbus is not in the cohort.** **H14 (N) — nimbus IS the exemplar of the revert-window failure mode.**

### lodestar

**Full Gloas-ePBS surface wired on `unstable`.** Per-pattern status:
- **Pattern A**: `hasCompoundingWithdrawalCredential` is strict-`0x02` — spec-conformant.
- **Pattern B**: `getPendingBalanceToWithdraw` strict-validator-side; separate `getPendingBalanceToWithdrawForBuilder` (Gloas-NEW) — spec-conformant.
- **Patterns C, D, E, G, H, K**: all wired (runtime `fork >= ForkSeq.gloas` ternaries throughout).
- **Pattern F**: Pectra-inline reuse via `fork >= ForkSeq.electra` lower-bound — observable-equivalent.

H1–H12 ✓. H13 — lodestar is not in the cohort. H14 — lodestar is not exposed to the revert-window.

### grandine

**Most complete Gloas implementation surface on the `glamsterdam-devnet-3` pin.** `vendor/grandine/transition_functions/src/gloas/` is a full per-fork module. Per-pattern status:
- **Pattern A**: `has_compounding_withdrawal_credential` is strict-`0x02`; separate `has_builder_withdrawal_credential` — spec-conformant.
- **Pattern B**: `get_pending_balance_to_withdraw` strict-validator-side; separate `_for_builder` — spec-conformant.
- **Patterns C, D, E, G, H, K**: all wired via `state.is_post_gloas()` Rust trait predicate.
- **Pattern F**: explicit three-way `is_post_gloas() / is_post_electra() / pre_electra` dispatcher.

H1–H12 ✓. H13 — grandine is not in the cohort. H14 — grandine is not exposed to the revert-window.

## Cross-reference table

Per-pattern status across clients (recheck-2 updated; ✓ = spec-conformant, ✗ = confirmed divergence, n/a = not applicable):

| Pattern | prysm | lighthouse | teku | nimbus | lodestar | grandine | Status |
|---|---|---|---|---|---|---|---|
| **A** (`0x03` BUILDER predicate fold-in) | ✓ | ✓ | ✓ | **✗ (item #22 H12)** | ✓ | ✓ | **CONFIRMED mainnet-glamsterdam in nimbus** |
| **B** (builder pending-withdrawals accumulator) | ✓ | ✓ | ✓ | **✗ (item #23 H10)** | ✓ | ✓ | **CONFIRMED mainnet-glamsterdam in nimbus** |
| **C** (EIP-8061 activation-churn) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | CLOSED (item #4 H8 + #16 H14) |
| **D** (EIP-8061 consolidation-churn) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | CLOSED (item #2 H6 + #16 H13) |
| **E** (committee index `< 2` at Gloas) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | CLOSED (item #7 H9) |
| **F** (sync committee selection) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | observable-equivalent (item #27 H10) |
| **G** (builder deposit handling) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | CLOSED (item #14 H9) |
| **H** (Pectra dispatcher exclusion at Gloas) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | CLOSED (item #13 H10) |
| **I** (multi-fork-definition) | n/a | n/a | n/a | ⚠ (Pattern N exemplar) | n/a | n/a | nimbus Electra body diverges from Gloas via stale OR-folds |
| **J** (type-union silent inclusion) | n/a | n/a | n/a | ⚠ (Pattern N exemplar) | n/a | n/a | nimbus's `electra \| fulu \| gloas` union type with stale body |
| **K** (Engine API V5) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | CLOSED (item #15 H10) |
| **L** (CAPELLA pin for voluntary exits) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | no-op (EIP-7044 carries forward) |
| **M** (lighthouse Gloas-ePBS gap) | n/a | ✓ (CLOSED) | n/a | n/a | n/a | n/a | **CLOSED** — all four ePBS surfaces wired in lighthouse `unstable` |
| **N** (PR #4513 → #4788 revert-window stale code) | n/a | n/a | n/a | **✗ (Patterns A + B)** | n/a | n/a | items #22 H12, #23 H10 — same root cause |

## Empirical tests

### Pectra-surface coverage

The cumulative recheck-2 series confirms ~300+ EF fixture PASSes across 4 wired clients on the Pectra surface. No Pectra-surface divergence surfaced.

### Gloas-surface coverage

No Gloas-specific EF fixtures wired yet. Patterns A + B are source-only at the time of this recheck (the rest have closed). The Gloas spec is stable at `v1.7.0-alpha.7-21-g0e70a492d` modulo ongoing spec PRs.

### Suggested fuzzing vectors

#### T1 — Mainline canonical Gloas fixture set
- **T1.1**: dedicated cross-client byte-level equivalence fixture for `has_compounding_withdrawal_credential` against `0x00, 0x01, 0x02, 0x03` input credentials at Gloas state. **Surfaces Pattern A (nimbus divergence)**.
- **T1.2**: dedicated cross-client byte-level equivalence fixture for `get_pending_balance_to_withdraw(state, V)` against Gloas state with non-trivial `state.builder_pending_payments[i].withdrawal.builder_index == V` entries. **Surfaces Pattern B (nimbus divergence)**.
- **T1.3**: state-transition fixture for `process_voluntary_exit` on Gloas state with builder pending payments at builder-index = validator-index collision. **Surfaces Pattern B end-to-end divergence**.
- **T1.4**: state-transition fixture for `process_effective_balance_updates` on Gloas state with a `0x03`-credentialled validator at balance > 33.25 ETH. **Surfaces Pattern A end-to-end divergence**.

#### T2 — Adversarial Gloas probes
- **T2.1**: pre-Gloas attacker submits a 32 ETH deposit with `withdrawal_credentials[0] = 0x03` + a 1.5 ETH top-up. At Gloas activation, verify nimbus computes `effective_balance > 32 ETH` for this validator while other 5 clients compute `32 ETH`. **Pattern A attack fixture**.
- **T2.2**: post-Gloas, a builder with raw `builder_index = V` bids for a slot. Validator V (any low-index validator) submits a voluntary exit. Verify nimbus rejects the exit while other 5 clients accept. **Pattern B attack fixture**.

## Mainnet reachability

Two confirmed mainnet-glamsterdam divergence vectors at Gloas activation:

**Vector 1 — nimbus Pattern A (item #22 H12)**: any pre-Gloas depositor submits a `DepositRequest` with `withdrawal_credentials[0] = 0x03` (Pectra `process_deposit_request` accepts any prefix) and a top-up to push balance > 33.25 ETH (UPWARD_HYSTERESIS_THRESHOLD). At the first `process_effective_balance_updates` post-Gloas, nimbus's stale `has_compounding_withdrawal_credential` returns true for `0x03` → `get_max_effective_balance` returns `MAX_EFFECTIVE_BALANCE_ELECTRA = 2048 ETH`; other 5 clients return `MIN_ACTIVATION_BALANCE = 32 ETH`. Validator's `effective_balance` diverges. State-root mismatch → chain split. Cost: ≥ 33 ETH locked permanently (no withdrawal path for `0x03` validators).

**Vector 2 — nimbus Pattern B (item #23 H10)**: triggered by NORMAL post-Gloas operation. `state.builder_pending_payments` is a 64-slot ring buffer that continuously fills with `builder_index` entries during normal Gloas block production. Raw `BuilderIndex` and `ValidatorIndex` share the `uint64 < 2^40` namespace; both registries grow from 0. Whenever a validator at index V attempts voluntary exit / withdrawal request / consolidation request AND there's a recent unsettled builder bid by builder at raw index V, nimbus's stale `get_pending_balance_to_withdraw` over-counts → rejects/under-credits the operation. State root diverges. Expected to produce **multiple divergence events per epoch** post-Gloas given typical voluntary exit volumes. **Cost: ZERO.**

**Indirect propagation channel (Vector 1 cascading into item #27)**: nimbus's Pattern A divergent `effective_balance` propagates into `get_next_sync_committee_indices` (item #27 H13) — `0x03`-credentialled validators with divergent `effective_balance` produce divergent sync committee membership. Same H12 attack, different downstream surface; same mitigation (fix nimbus's predicate).

**Mitigation:**
- **Nimbus (Patterns A + B)**: two one-line removals — drop the `when consensusFork >= ConsensusFork.Gloas` branch in `vendor/nimbus/beacon_chain/spec/beaconstate.nim:59-68` (Pattern A) and `:1588-1607` (Pattern B). Update doc-comment URLs at `:57-58` and `:1588-1589` to drop the `#modified-*` references. **Single-developer-day fix.**

**Detection (operational pre-Gloas)**:
- Monitor mainnet validators for `withdrawal_credentials[0] == 0x03`. Any positive hit is a Pattern A attack precursor.

## Conclusion

**Status: source-code-reviewed.** The recheck-2 series against the per-client Glamsterdam-branch pins confirms:

1. **Two mainnet-glamsterdam divergences in nimbus** (Patterns A, B) caused by stale code shipped during the PR #4513 → PR #4788 spec-revert window (Pattern N). Both have single-line fixes. **The only active mainnet-glamsterdam divergences in the corpus.**
2. **Lighthouse Pattern M ePBS cohort fully closed.** All four ePBS surfaces are now wired in `unstable` HEAD `1a6863118`: `is_builder_withdrawal_credential` at `validator.rs:318`, `get_pending_balance_to_withdraw_for_builder` at `beacon_state.rs:2829`, `apply_parent_execution_payload` at `per_block_processing.rs:589`, `is_valid_indexed_payload_attestation` at `is_valid_indexed_payload_attestation.rs:6`.
3. **EIP-8061 churn family fully closed.** Seven cascade entry-points (items #2, #3, #4, #6, #8, #9, #17) + one chokepoint (item #16) all vacated. Six distinct dispatch idioms catalogued: prysm `*ForVersion` runtime wrappers, lighthouse name-polymorphism + internal fork-gates, teku Java subclass overrides, nimbus compile-time per-fork variants, lodestar runtime ternaries, grandine `state.is_post_gloas()` predicate.
4. **EIP-7732 ePBS lifecycle fully closed.** Items #7, #9, #12, #13, #14, #15, #19 all vacated across all six clients.
5. **Pattern F (sync committee selection) remains observable-equivalent** (item #27 H10 from prior session).

**Per-pattern bottom line:**
- **Patterns A + B (Pattern N revert-window) — CONFIRMED mainnet-glamsterdam divergences in nimbus.** Highest-priority pre-Gloas fix; single-developer-day work.
- **Patterns C + D + E + G + H + K + M — all CLOSED** under the per-client Glamsterdam branches.
- **Pattern F — RESOLVED to observable-equivalent** (no action needed).
- **Patterns I + J + L — code-review risks; Pattern N is the active exemplar in nimbus.**

**Highest-leverage follow-up audits:**

1. **Hunt for other PR #4513 → PR #4788 revert-window stale code in nimbus** (Pattern N pattern audit). Items #22 + #23 are TWO functions affected by the same root cause; other functions modified-then-reverted in the 2025-Q4 → 2026-Q1 spec window may also be stale. Candidates: any Gloas function whose doc-comment URL points to `v1.6.0-beta.0` AND has a `Modified` section in the URL fragment.
2. **Spec-clarification PR (consensus-specs)** — add `Removed in <commit>` notes for predicates / accessors that had `Modified` sections walked back in the 2025-2026 spec churn. Prevents future revert-window stale-code bugs in client implementations that bookmark intermediate spec versions.
3. **Per-client Gloas implementation tracking dashboard** — quarterly source-tree scan of `grep -rn "[Gg]loas"` per client to track Gloas implementation progress; build into BeaconBreaker as `tools/runners/gloas_readiness.sh`. Re-run quarterly to surface new Gloas-aware code paths as they ship.
4. **Pre-emptive cross-client Gloas test-vector generation for Patterns A + B** — generate dedicated EF fixtures that exercise the nimbus divergences; ship to EF for inclusion in `consensus-spec-tests` so the divergence is detected at fixture-run time rather than chain-split time.

## Cross-cuts

### Pattern N origin chain

PR #4513 (`vendor/consensus-specs` commit `1b7dedb4a`, "eip7732: consider builder pending payments for pending balance to withdraw") added `Modified get_pending_balance_to_withdraw` at Gloas. A concurrent EIP-7732 PR added `Modified has_compounding_withdrawal_credential`. Both reflected the intermediate "builders are validators with 0x03 credentials" design.

PR #4788 (`vendor/consensus-specs` commit `601829f1a`, 2026-01-05, "Make builders non-validating staked actors") implemented the EIP-7732 design pivot: builders moved to a separate `state.builders` registry (`List[Builder, BUILDER_REGISTRY_LIMIT]`) with their own accessors (`get_pending_balance_to_withdraw_for_builder`, `is_builder_index`, `convert_builder_index_to_validator_index`). Both Modified-at-Gloas predicates were REMOVED; the unmodified Electra versions carry forward at Gloas.

Nimbus shipped pre-emptive code matching PR #4513 (the intermediate "builders are validators" design). The doc-comment URLs in nimbus source still point to v1.6.0-beta.0 — a snapshot taken DURING the revert window. After PR #4788, nimbus did not roll back. The two divergent functions (items #22 H12, #23 H10) are the observable consequences.

### Indirect propagation chains

- **Item #22 H12 → item #27 H13**: nimbus's stale `has_compounding_withdrawal_credential` returns true for `0x03` at Gloas → item #1 `process_effective_balance_updates` computes divergent `effective_balance` for `0x03` validators → item #27 `get_next_sync_committee_indices` reads divergent `effective_balance` → divergent sync committee membership Merkle root.
- **Item #22 H12 → item #1 → all `effective_balance`-dependent surfaces**: total_active_balance, attestation rewards, slashing math, sync-committee rewards, finalization. Single Pattern A attack cascades through all of these.
- **Item #23 H10 → items #2, #3, #6 caller sites**: nimbus's stale `get_pending_balance_to_withdraw` consumed by `process_consolidation_request` source gate, `process_withdrawal_request` full-exit + partial subtractor, `process_voluntary_exit` equality gate. Single Pattern B attack manifests through three different operation types.

### Patterns closed under the per-client Glamsterdam branches

The branch-symmetric re-pinning (lighthouse + nimbus `unstable`, prysm `EIP-8061`, teku `glamsterdam-devnet-2`, grandine `glamsterdam-devnet-3`, lodestar `unstable`) collapsed the prior multi-divergence picture:

| Closed pattern / family | Cascade items now vacated |
|---|---|
| EIP-8061 churn | #2 H6, #3 H8, #4 H8, #6 H8, #8 H9, #9 H10, #17 H10, #16 H12-H15 |
| EIP-7732 ePBS lifecycle | #7 H9/H10, #9 H9 (BPP clearing), #12 H11/H12, #13 H10, #14 H9, #19 H10 |
| Engine API V5 | #15 H10 (lighthouse + grandine both wired) |
| Lighthouse Pattern M cohort | #22 H10 (predicate), #23 H8 (builder accessor), #24 H11, #25 H11, #26 H8 |

The remaining active divergences are confined to nimbus items #22 H12 and #23 H10 — both rooted in Pattern N.

## Adjacent untouched

1. **Nimbus Pattern A + B fix** — two one-line removals in `vendor/nimbus/beacon_chain/spec/beaconstate.nim`. Highest-priority pre-Gloas fix.
2. **Pattern N pattern audit on nimbus** — hunt for other revert-window stale code; candidates: any function with `v1.6.0-beta.0` doc-comment URL referencing a `#modified-*` section.
3. **Spec-clarification PR (consensus-specs)** — add `Removed in <commit>` notes for walked-back `Modified` sections.
4. **Pre-emptive cross-client Gloas EF fixture set** — Patterns A + B attack fixtures only (rest of the patterns are now confirmation rather than divergence-detection).
5. **Quarterly Gloas-readiness dashboard** (`tools/runners/gloas_readiness.sh`) — automated `grep -rn "[Gg]loas"` scan with diffing to surface new Gloas-aware code paths as they ship.
6. **Per-client `gloas_fork_version` constant verification** when configs ship (mainnet / sepolia / holesky / Hoodi etc.).
7. **Cross-client `engine_newPayloadV5` request/response schema audit** when EIP-7732 PBS engine API lands (now uniform across all six clients per item #15 H10 vacation, but field-level schema parity needs its own audit).
8. **`compute_balance_weighted_selection` cross-cut audit** (items #27 sister functions): `compute_proposer_indices` and `compute_ptc` consume the same helper at Gloas; verify cross-client equivalence on all three call sites.
9. **Indirect-propagation fixture for item #22 H12 → item #1 → all `effective_balance` consumers** — the cascade fixture would surface every downstream surface affected by nimbus's stale predicate.
10. **Pre-Gloas mainnet monitoring** — scan `state.validators` for `withdrawal_credentials[0] == 0x03`; any positive hit is a Pattern A attack precursor.
11. **Compile-time vs runtime fork-dispatch performance audit at Gloas** — nimbus's `static ConsensusFork` compile-time dispatch may have a measurable advantage at deep fork stacks; lighthouse + grandine superstruct / module-namespace dispatch may benefit from optimization at Gloas activation.
12. **Six-dispatch-idiom catalog documentation** — recheck-2 surfaced six structurally distinct mechanisms (Go runtime wrapper, Rust name-polymorphism, Java subclass override, Nim compile-time `when`, TypeScript runtime ternary, Rust trait predicate) that achieve identical observable Gloas semantics. Useful reference for future fork-gating audits.
