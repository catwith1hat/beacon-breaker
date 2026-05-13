---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-12
builds_on: [6, 7]
eips: [EIP-7549, EIP-7251, EIP-8061]
splits: [prysm, lighthouse, teku, nimbus, grandine]
# main_md_summary: `slash_validator` → `initiate_validator_exit` propagates the EIP-8061 churn-helper divergence (same five lagging clients as items #3 H8 / #6 H8) into every slashed validator's `exit_epoch` / `withdrawable_epoch` at Gloas activation
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 8: `process_attester_slashing` (EIP-7549 + EIP-7251)

## Summary

Casper FFG slashing entrypoint. Two flavors of Pectra changes: (1) **EIP-7549** expanded `IndexedAttestation.attesting_indices` list capacity from `MAX_VALIDATORS_PER_COMMITTEE` to `MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT`, and `MAX_ATTESTER_SLASHINGS_ELECTRA` (smaller per-block limit); (2) **EIP-7251** changed the slashing-penalty + whistleblower-reward divisor constants (`MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` and `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA`). The function itself (`process_attester_slashing`) is structurally unchanged from Phase0 — but `slash_validator` is Pectra-modified, and the IndexedAttestations being processed have a new shape.

**Pectra surface (the function body itself):** all six clients implement the Casper FFG slashing predicate, both BLS aggregate verifications, set intersection + sort, the slashability check, and the Pectra-changed quotient selection identically. 30/30 EF `attester_slashing` operations fixtures pass uniformly on the four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus pass these in internal CI but the local harness SKIPs them.

**Gloas surface (new at the Glamsterdam target):** `process_attester_slashing` and `slash_validator` are both **unchanged** at Gloas (no Modified heading in `vendor/consensus-specs/specs/gloas/beacon-chain.md`; the slashing constants are also unchanged). The function bodies and quotient selection (H1–H8) remain aligned. **However**, `slash_validator` calls `initiate_validator_exit(state, slashed_index)`, which calls `compute_exit_epoch_and_update_churn(state, validator.effective_balance)` — and that primitive **is** Modified at Gloas (EIP-8061) to consume `get_exit_churn_limit` instead of `get_activation_exit_churn_limit`. Item #6 H8 and item #3 H8 already established the 5-vs-1 cohort split on this helper: only lodestar fork-gates it; prysm, lighthouse, teku, nimbus, grandine run the Electra accessor unconditionally on Gloas states. Each slashed validator at Gloas therefore gets a divergent `exit_epoch` and `withdrawable_epoch` written to its `state.validators[i]` record — the divergence materialises here even though the immediate call chain is correct. The five EIP-8061 laggards form the `splits` set.

## Question

`process_attester_slashing` is the canonical Casper FFG slashing entrypoint — verifies that two conflicting attestations form a slashable pair (double vote OR surround vote), then slashes every validator that signed both. Pyspec (Phase0 structurally, Electra-typed):

```python
def process_attester_slashing(state, attester_slashing):
    a1 = attester_slashing.attestation_1
    a2 = attester_slashing.attestation_2
    assert is_slashable_attestation_data(a1.data, a2.data)  # double or surround
    assert is_valid_indexed_attestation(state, a1)          # BLS aggregate verify
    assert is_valid_indexed_attestation(state, a2)
    slashed_any = False
    indices = set(a1.attesting_indices).intersection(a2.attesting_indices)
    for index in sorted(indices):
        if is_slashable_validator(state.validators[index], get_current_epoch(state)):
            slash_validator(state, index)
            slashed_any = True
    assert slashed_any
```

`slash_validator` (Pectra-modified, `vendor/consensus-specs/specs/electra/beacon-chain.md:827`):

```python
def slash_validator(state, slashed_index, whistleblower_index=None):
    epoch = get_current_epoch(state)
    initiate_validator_exit(state, slashed_index)        # Pectra: churn-paced (item #6)
    validator = state.validators[slashed_index]
    validator.slashed = True
    validator.withdrawable_epoch = max(
        validator.withdrawable_epoch, Epoch(epoch + EPOCHS_PER_SLASHINGS_VECTOR))
    state.slashings[epoch % EPOCHS_PER_SLASHINGS_VECTOR] += validator.effective_balance
    # [Modified in Electra:EIP7251] — DIFFERENT QUOTIENT
    slashing_penalty = validator.effective_balance // MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA
    decrease_balance(state, slashed_index, slashing_penalty)
    proposer_index = get_beacon_proposer_index(state)
    if whistleblower_index is None:
        whistleblower_index = proposer_index
    # [Modified in Electra:EIP7251] — DIFFERENT QUOTIENT
    whistleblower_reward = Gwei(validator.effective_balance // WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA)
    proposer_reward = Gwei(whistleblower_reward * PROPOSER_WEIGHT // WEIGHT_DENOMINATOR)
    increase_balance(state, proposer_index, proposer_reward)
    increase_balance(state, whistleblower_index, Gwei(whistleblower_reward - proposer_reward))
```

Eight divergence-prone bits on the Pectra surface (A–H unchanged from prior audit): FFG predicate, BLS verify, set intersection, sorted iteration, slashability predicate, the Pectra quotient values, and `slashed_any` assertion.

**Glamsterdam target.** `process_attester_slashing` and `slash_validator` are **not modified** at Gloas — no `Modified process_attester_slashing` or `Modified slash_validator` heading exists in `vendor/consensus-specs/specs/gloas/beacon-chain.md`. The slashing constants (`MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA`, `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA`) are also unchanged. The function bodies, the FFG predicate, and the quotient selection therefore remain spec-aligned at Gloas across all six clients.

**However**, `slash_validator` does call `initiate_validator_exit`, and that calls `compute_exit_epoch_and_update_churn` (Pectra-modified) which at Gloas is **further Modified** (EIP-8061) to consume `get_exit_churn_limit` instead of `get_activation_exit_churn_limit`. The five-vs-one cohort split on that helper, established in items #3 H8 (partial-withdrawal pacing) and #6 H8 (voluntary-exit / EL full-exit pacing), propagates directly through `slash_validator` into the slashed validator's `exit_epoch` and `withdrawable_epoch` fields. Unlike item #5 (which had purely indirect propagation through state reads), the divergence here flows through an explicit `compute_exit_epoch_and_update_churn` call in this item's transitive call chain — so the divergent post-state is produced by code paths this audit covers.

The hypothesis: *all six clients implement the FFG slashing predicate, the BLS aggregate verifications, set intersection + sort, the slashability check, the Pectra-changed quotient selection, and the slashed_any rejection identically (H1–H8); and at the Glamsterdam target all six fork-gate the underlying `compute_exit_epoch_and_update_churn` to use `get_exit_churn_limit` so that the slashed validator's `exit_epoch` advance is paced per the Gloas spec (H9).*

**Consensus relevance**: slashings transfer effective_balance → state.slashings vector, reduce slashed validator's balance, and reward proposer + whistleblower. A divergence in any Pectra-surface bit (predicate, BLS, quotients, sort order) would split the chain immediately. A divergence in the underlying churn helper (H9) shifts the `exit_epoch` written into the slashed validator's record — same as items #3 and #6, with the slashing being one more entry-point into the divergent code path. This is an A-tier surface: an adversary that produces conflicting attestations can trigger this code path; at Gloas activation the cascade automatically applies.

## Hypotheses

- **H1.** All six implement the same Casper FFG predicate: double vote (different data, same target epoch) OR surround vote (a1.source < a2.source ∧ a2.target < a1.target).
- **H2.** All six validate both attestations' BLS aggregate signatures via `is_valid_indexed_attestation`.
- **H3.** All six compute `set(a1.attesting_indices) ∩ set(a2.attesting_indices)` correctly (dedupe).
- **H4.** All six iterate the intersection in sorted (ascending) order.
- **H5.** All six implement `is_slashable_validator(v, epoch)` as `!v.slashed ∧ v.activation_epoch <= epoch < v.withdrawable_epoch`.
- **H6.** All six use `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` for the penalty divisor at the Pectra fork (NOT the Bellatrix legacy value). Continues at Gloas (no quotient change).
- **H7.** All six use `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA` for the whistleblower reward divisor at the Pectra fork (NOT the legacy value). Continues at Gloas (no quotient change).
- **H8.** All six reject the slashing when no validator was slashable (`slashed_any` assertion).
- **H9** *(Glamsterdam target — inherited from item #6 H8 via `slash_validator`)*. At the Gloas fork gate, every `slash_validator(state, slashed_index)` call paces the slashed validator's `exit_epoch` via `compute_exit_epoch_and_update_churn` consuming `get_exit_churn_limit(state)` (Gloas, EIP-8061) rather than `get_activation_exit_churn_limit(state)` (Electra). Pre-Gloas, all six retain the Electra formula.

## Findings

H1–H8 satisfied for the Pectra surface — function bodies, BLS aggregate, intersection algorithms, sort, slashability, quotients, and the `slashed_any` assertion all aligned. **H9 fails for 5 of 6 clients** — same finding as items #3 H8 and #6 H8 since this item's `slash_validator` funnels through the same `compute_exit_epoch_and_update_churn` primitive. Only lodestar fork-gates the churn helper to `get_exit_churn_limit` at Gloas; prysm, lighthouse, teku, nimbus, and grandine retain the Electra `get_activation_exit_churn_limit` even when slashing on Gloas states.

### prysm

`vendor/prysm/beacon-chain/core/blocks/attester_slashing.go:111-195` + `vendor/prysm/beacon-chain/core/validators/validator.go:235-305`:

```go
// process — sort, then per-validator slashability + slash
slashableIndices := SlashableAttesterIndices(slashing)            // intersection
sort.SliceStable(slashableIndices, func(i, j int) bool { return slashableIndices[i] < slashableIndices[j] })
for _, validatorIndex := range slashableIndices {
    if helpers.IsSlashableValidator(...) {
        beaconState, err = validators.SlashValidator(ctx, beaconState, validatorIndex, exitInfo)
        slashedAny = true
    }
}
if !slashedAny { return errors.New("unable to slash any validator despite confirmed attester slashing") }

// slash — Pectra quotient selection via SlashingParamsPerVersion
slashingQuotient, proposerRewardQuotient, whistleblowerRewardQuotient, _ := SlashingParamsPerVersion(s.Version())
// SlashingParamsPerVersion: if v >= version.Electra { slashingQuotient = MinSlashingPenaltyQuotientElectra; whistleblowerRewardQuotient = WhistleBlowerRewardQuotientElectra }
slashingPenalty, _ := math.Div64(validator.EffectiveBalance, slashingQuotient)
helpers.DecreaseBalance(s, slashedIdx, slashingPenalty)
```

`SlashValidator` (`vendor/prysm/beacon-chain/core/validators/validator.go:235-305`) calls `InitiateValidatorExit(ctx, s, slashedIdx, exitInfo)` near the top — same function audited in item #6. That delegates to `state.ExitEpochAndUpdateChurn(EffectiveBalance)`, which at Gloas runs the Electra `ActivationExitChurnLimit` formula unconditionally.

H1 ✓ (`IsSlashableAttestationData` at `attester_slashing.go:171-195`). H2 ✓ (`VerifyIndexedAttestation` × 2). H3 ✓ (`slice.IntersectionUint64`). H4 ✓ (`sort.SliceStable`). H5 ✓ (`IsSlashableValidator(activationEpoch, withdrawableEpoch, slashed, currentEpoch)`). H6 ✓. H7 ✓. H8 ✓. **H9 ✗** (inherited from item #6's prysm finding: `ExitEpochAndUpdateChurn` unconditionally uses `ActivationExitChurnLimit`).

`SlashingParamsPerVersion` (`vendor/prysm/beacon-chain/core/validators/validator.go:272`) keeps the Electra quotient triplet for `version >= Electra` — no Gloas branch, but no Gloas branch is needed either since the spec doesn't modify the constants.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:254-277` + `vendor/lighthouse/consensus/state_processing/src/per_block_processing/verify_attester_slashing.rs:19-94` + `vendor/lighthouse/consensus/state_processing/src/common/slash_validator.rs:16-79`:

```rust
// process
state.build_slashings_cache()?;
let slashable_indices = verify_attester_slashing(state, attester_slashing, verify_signatures, spec)?;
for i in slashable_indices {
    slash_validator(state, i as usize, None, ctxt, spec)?;
}

// verify (intersection via BTreeSet — naturally sorted)
let attesting_indices_1 = attestation_1.attesting_indices_iter().cloned().collect::<BTreeSet<_>>();
let attesting_indices_2 = attestation_2.attesting_indices_iter().cloned().collect::<BTreeSet<_>>();
for index in &attesting_indices_1 & &attesting_indices_2 {
    if validator.is_slashable_at(state.current_epoch()) { slashable_indices.push(index); }
}
verify!(!slashable_indices.is_empty(), Invalid::NoSlashableIndices);

// slash — Pectra quotient via state methods
decrease_balance(state, slashed_index,
    validator_effective_balance.safe_div(state.get_min_slashing_penalty_quotient(spec))?)?;
let whistleblower_reward = validator_effective_balance.safe_div(state.get_whistleblower_reward_quotient(spec))?;
```

`slash_validator` (in `common/slash_validator.rs`) calls `state.initiate_validator_exit(slashed_index, spec)?` near the top — the same Pectra-modified function audited in item #6. That delegates to `compute_exit_epoch_and_update_churn(effective_balance, spec)?` at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2708-2752`, which uses `self.get_activation_exit_churn_limit(spec)?` unconditionally even when the BeaconState variant is Gloas.

H1 ✓ (`is_double_vote()` || `is_surround_vote()`). H2 ✓. H3 ✓ (BTreeSet intersection — naturally sorted). H4 ✓ (BTreeSet ascending). H5 ✓ (`validator.is_slashable_at(epoch)`). H6 ✓ via `state.get_min_slashing_penalty_quotient(spec)`. H7 ✓ via `state.get_whistleblower_reward_quotient(spec)`. H8 ✓. **H9 ✗** (inherited from item #6's lighthouse finding).

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/common/block/AbstractBlockProcessor.java:546-568` + `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/common/helpers/BeaconStateMutators.java:249` + `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/BeaconStateMutatorsElectra.java:253,258`:

```java
// process — delegated to operation validator + per-validator slashing
for (AttesterSlashing attesterSlashing : attesterSlashings) {
    List<UInt64> indicesToSlash = new ArrayList<>();
    final Optional<OperationInvalidReason> invalidReason =
        operationValidator.validateAttesterSlashing(state.getFork(), state, attesterSlashing, indicesToSlash::add);
    checkArgument(invalidReason.isEmpty(), "process_attester_slashings: %s", ...);
    indicesToSlash.forEach(idx -> beaconStateMutators.slashValidator(state, idx.intValue(), validatorExitContextSupplier));
}

// slash — Pectra quotient via subclass override
@Override
protected int getWhistleblowerRewardQuotient() { return specConfigElectra.getWhistleblowerRewardQuotientElectra(); }
@Override
protected int getMinSlashingPenaltyQuotient() { return specConfigElectra.getMinSlashingPenaltyQuotientElectra(); }
```

`slashValidator` (`BeaconStateMutators.java`) calls `initiateValidatorExit(state, index, validatorExitContextSupplier)` near the top — same function audited in item #6. The Electra subclass override at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/BeaconStateMutatorsElectra.java:108-132` calls `computeExitEpochAndUpdateChurn(stateElectra, validator.getEffectiveBalance())` at line 121, which at lines 77-104 of the same file uses `stateAccessorsElectra.getActivationExitChurnLimit(state)` unconditionally. `BeaconStateMutatorsGloas` does not override `computeExitEpochAndUpdateChurn` (per item #6).

H1 ✓ (`AttestationUtil.isSlashableAttestationData`). H2 ✓ (delegated to `operationValidator`). H3 ✓. H4 ✓. H5 ✓ (`Predicates.isSlashableValidator`). H6 ✓ (override). H7 ✓ (override). H8 ✓. **H9 ✗** (inherited from item #6's teku finding).

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:284-301` + `vendor/nimbus/beacon_chain/spec/beaconstate.nim:426` + `vendor/nimbus/beacon_chain/spec/beaconstate.nim:379-407`:

```nim
# process — check returns indices, then iterate
let slashed_attesters = ? check_attester_slashing(state, attester_slashing, flags)
for index in slashed_attesters:
    let (new_proposer_reward, new_exit_queue_info) = ? slash_validator(cfg, state, index, cur_exit_queue_info, cache)
    ...

# slash — Pectra quotient via static fork dispatch
decrease_balance(state, slashed_index, get_slashing_penalty(state, validator.effective_balance))
# get_slashing_penalty:
when state is electra.BeaconState | fulu.BeaconState | gloas.BeaconState:
    validator_effective_balance div MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA
# get_whistleblower_reward (Electra+):
validator_effective_balance div WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA
```

`slash_validator` (`vendor/nimbus/beacon_chain/spec/beaconstate.nim:379-407`) calls `initiate_validator_exit(cfg, state, slashed_index, exit_queue_info, cache)` at the start — same function audited in item #6. That at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:348-373` calls `compute_exit_epoch_and_update_churn(cfg, state, validator.effective_balance, cache)`, whose body at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:286-314` uses `get_activation_exit_churn_limit(cfg, state, cache)` even on a `gloas.BeaconState`.

H1 ✓ (`is_slashable_attestation_data`). H2 ✓. H3 ✓. H4 ✓. H5 ✓ (`is_slashable_validator`). H6 ✓ (compile-time `when` block on state type). H7 ✓ (compile-time `when` block). H8 ✓. **H9 ✗** (inherited from item #6's nimbus finding).

### lodestar

`vendor/lodestar/packages/state-transition/src/block/processAttesterSlashing.ts:16-47` + `vendor/lodestar/packages/state-transition/src/block/slashValidator.ts:24-59`:

```typescript
// process — sort intersection, then per-validator slashability + slash
const intersectingIndices = getAttesterSlashableIndices(attesterSlashing);
let slashedAny = false;
for (const index of intersectingIndices.sort((a, b) => a - b)) {
    if (isSlashableValidator(validators.getReadonly(index), epochCtx.epoch)) {
        slashValidator(fork, state, index);
        slashedAny = true;
    }
}
if (!slashedAny) throw new Error("AttesterSlashing did not result in any slashings");

// slash — Pectra quotient via nested ternary fork branch
const minSlashingPenaltyQuotient =
    fork === ForkSeq.phase0     ? MIN_SLASHING_PENALTY_QUOTIENT
  : fork === ForkSeq.altair     ? MIN_SLASHING_PENALTY_QUOTIENT_ALTAIR
  : fork  <  ForkSeq.electra    ? MIN_SLASHING_PENALTY_QUOTIENT_BELLATRIX
                                : MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA;
decreaseBalance(state, slashedIndex, Math.floor(effectiveBalance / minSlashingPenaltyQuotient));
const whistleblowerReward =
    fork < ForkSeq.electra ? Math.floor(effectiveBalance / WHISTLEBLOWER_REWARD_QUOTIENT)
                           : Math.floor(effectiveBalance / WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA);
```

`slashValidator` (`vendor/lodestar/packages/state-transition/src/block/slashValidator.ts:24-59`) calls `initiateValidatorExit(fork, state, slashedIndex)` near the top — same function audited in item #6. That at `vendor/lodestar/packages/state-transition/src/block/initiateValidatorExit.ts:27-62` calls `computeExitEpochAndUpdateChurn(state, BigInt(validator.effectiveBalance))`, whose body at `vendor/lodestar/packages/state-transition/src/util/epoch.ts:50-77` is the **fork-gated** implementation:

```typescript
const perEpochChurn =
  fork >= ForkSeq.gloas ? getExitChurnLimit(state.epochCtx) : getActivationExitChurnLimit(state.epochCtx);
```

H1 ✓ (`isSlashableAttestationData`). H2 ✓. H3 ✓ (Set-based traversal). H4 ✓ (explicit `.sort((a, b) => a - b)`). H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓** — the only client where `slash_validator` correctly paces the slashed validator's exit at Gloas.

### grandine

`vendor/grandine/transition_functions/src/electra/block_processing.rs:656-684` + `vendor/grandine/helper_functions/src/electra.rs:153-192` + `vendor/grandine/helper_functions/src/accessors.rs:871-883`:

```rust
// process — validate returns slashable_indices, then slash each
let slashable_indices = unphased::validate_attester_slashing_with_verifier(
    config, pubkey_cache, state, attester_slashing, verifier)?;
for validator_index in slashable_indices {
    slash_validator(config, state, validator_index, None, SlashingKind::Attester, &mut slot_report)?;
}

// slashable_indices — sorted via merge_join_by
attesting_indices_1.merge_join_by(attesting_indices_2, Ord::cmp)
    .filter_map(|either_or_both| match either_or_both {
        EitherOrBoth::Both(validator_index, _) => Some(validator_index),
        _ => None,
    })

// slash — Pectra quotient via type-associated constant
let slashing_penalty = effective_balance / P::MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA;
let whistleblower_reward = effective_balance / P::WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA;
```

`slash_validator` (`vendor/grandine/helper_functions/src/electra.rs`) calls `initiate_validator_exit(config, state, slashed_index)` near the top — same Pectra version audited in item #6 at `vendor/grandine/helper_functions/src/electra.rs:124-150`. That calls `compute_exit_epoch_and_update_churn(config, state, validator.effective_balance)`, whose body at `vendor/grandine/helper_functions/src/mutators.rs:177-208` uses `get_activation_exit_churn_limit(config, state)` unconditionally.

H1 ✓ (`is_slashable_attestation_data`). H2 ✓. H3 ✓ (`merge_join_by` lazy sorted-merge). H4 ✓ (output sorted). H5 ✓ (`is_slashable_validator` — `const fn`). H6 ✓ (`P::MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA`). H7 ✓ (`P::WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA`). H8 ✓. **H9 ✗** (inherited from item #6's grandine finding).

## Cross-reference table

| Client | `process_attester_slashing` | Intersection algo | Sort | Penalty quotient | Whistleblower quotient | `slash_validator` → `initiate_validator_exit` churn fork-gate (H9) |
|---|---|---|---|---|---|---|
| prysm | `core/blocks/attester_slashing.go:111-142` | `slice.IntersectionUint64()` | `sort.SliceStable` | `MinSlashingPenaltyQuotientElectra` | `WhistleBlowerRewardQuotientElectra` | ✗ (`state-native/setters_churn.go:67` calls `helpers.ActivationExitChurnLimit` unconditionally) |
| lighthouse | `per_block_processing/process_operations.rs:254-277` | `BTreeSet` set algebra `&s1 & &s2` | implicit (BTreeSet ascending) | `spec.min_slashing_penalty_quotient_electra` | `spec.whistleblower_reward_quotient_electra` | ✗ (`beacon_state.rs:2708-2752` calls `get_activation_exit_churn_limit` unconditionally) |
| teku | `AbstractBlockProcessor.java:546` + `BeaconStateMutatorsElectra.java:253,258` | inside `operationValidator.validateAttesterSlashing` | implicit | `getMinSlashingPenaltyQuotientElectra()` | `getWhistleblowerRewardQuotientElectra()` | ✗ (`BeaconStateMutatorsElectra.java:77-104` calls `getActivationExitChurnLimit`; `BeaconStateMutatorsGloas` doesn't override) |
| nimbus | `state_transition_block.nim:284-301` + `beaconstate.nim:426` | inside `check_attester_slashing` | sorted | `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` | `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA` | ✗ (`beaconstate.nim:286-314` body uses `get_activation_exit_churn_limit` even with `gloas.BeaconState` signature) |
| lodestar | `block/processAttesterSlashing.ts:16-47` + `block/slashValidator.ts:24-59` | `getIntersectingIndices` Set-based traversal | explicit `.sort((a, b) => a - b)` | `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` | `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA` | **✓** (`util/epoch.ts:50-77` fork-gates `getExitChurnLimit` at `fork >= ForkSeq.gloas`) |
| grandine | `electra/block_processing.rs:656-684` + `helper_functions/electra.rs:153-192` | `merge_join_by(Ord::cmp)` lazy sorted-merge | implicit (output sorted) | `P::MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` | `P::WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA` | ✗ (`mutators.rs:177-208` calls `get_activation_exit_churn_limit` unconditionally) |

## Empirical tests

### Pectra-surface fixture run

`consensus-spec-tests/tests/mainnet/electra/operations/attester_slashing/pyspec_tests/` — 30 EF fixtures. Run via `scripts/run_fixture.sh` against all six clients on 2026-05-03:

```
                                                                         prysm  lighthouse  teku  nimbus  lodestar  grandine
already_exited_long_ago                                                  PASS   PASS        SKIP  SKIP    PASS      PASS
already_exited_recent                                                    PASS   PASS        SKIP  SKIP    PASS      PASS
attestation_from_future                                                  PASS   PASS        SKIP  SKIP    PASS      PASS
basic_double                                                             PASS   PASS        SKIP  SKIP    PASS      PASS
basic_surround                                                           PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_all_empty_indices                                                PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_att1_bad_extra_index                                             PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_att1_bad_replaced_index                                          PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_att1_duplicate_index_double_signed                               PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_att1_duplicate_index_normal_signed                               PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_att1_empty_indices                                               PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_att1_high_index                                                  PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_att2_bad_extra_index                                             PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_att2_bad_replaced_index                                          PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_att2_duplicate_index_double_signed                               PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_att2_duplicate_index_normal_signed                               PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_att2_empty_indices                                               PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_att2_high_index                                                  PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_incorrect_sig_1                                                  PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_incorrect_sig_1_and_2                                            PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_incorrect_sig_2                                                  PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_no_double_or_surround                                            PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_participants_already_slashed                                     PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_same_data                                                        PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_unsorted_att_1                                                   PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_unsorted_att_2                                                   PASS   PASS        SKIP  SKIP    PASS      PASS
low_balances                                                             PASS   PASS        SKIP  SKIP    PASS      PASS
misc_balances                                                            PASS   PASS        SKIP  SKIP    PASS      PASS
proposer_index_slashed                                                   PASS   PASS        SKIP  SKIP    PASS      PASS
with_effective_balance_disparity                                         PASS   PASS        SKIP  SKIP    PASS      PASS
```

30/30 fixtures pass uniformly on prysm + lighthouse + lodestar + grandine. teku and nimbus SKIP per harness limit.

### Gloas-surface

No Gloas operations fixtures yet exist for `process_attester_slashing` (and none would change the function body — the Gloas modification is upstream in `compute_exit_epoch_and_update_churn`). H9 is currently source-only; sister to item #6's T2.5 (which covers the upstream divergence directly).

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — slashing of a high-balance compounding validator).** Slashed validator has `effective_balance = 2048 ETH`. Penalty = 2048 ETH / `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA`. Whistleblower reward = 2048 ETH / `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA`. Tests both Pectra quotients at the upper boundary.
- **T1.2 (priority — slashing of a previously-consolidation-source-exited validator).** A validator already in the exit queue is slashed. `is_slashable_validator` returns false if `validator.slashed` is true OR `epoch >= withdrawable_epoch`. Worth a custom composed fixture.

#### T2 — Adversarial probes
- **T2.1 (priority — multi-slashing in one block with churn drain).** Block contains 2 attester slashings, each affecting 8 high-balance validators. Each `slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn` mutates shared `state.exit_balance_to_consume`. At Gloas, the per_epoch_churn quantity differs across the 5-vs-1 cohort, so the cumulative drain produces different `exit_balance_to_consume` and per-validator `exit_epoch` assignments. Highest-value Glamsterdam-target fixture for this item.
- **T2.2 (priority — proposer-as-whistleblower edge).** Covered partially by `proposer_index_slashed`.
- **T2.3 (defensive — slashing already-slashed validator).** Covered by `invalid_participants_already_slashed`.
- **T2.4 (defensive — IndexedAttestation with unsorted attesting_indices).** Covered by `invalid_unsorted_att_{1,2}`.
- **T2.5 (defensive — IndexedAttestation with duplicate indices).** Covered by `invalid_att{1,2}_duplicate_index_*`.
- **T2.6 (Glamsterdam-target — Gloas churn cascade).** Synthetic Gloas-fork state where `state.exit_balance_to_consume` is depleted to a non-zero value. Submit a single attester slashing that affects one high-balance validator (`effective_balance` chosen to straddle the Electra/Gloas churn-limit divergence). Expected per Gloas spec: lodestar computes `additional_epochs` via `get_exit_churn_limit`; the other five via `get_activation_exit_churn_limit`. The slashed validator's `validator.exit_epoch` and `validator.withdrawable_epoch` (then `max`'d against the slashings-vector constant) differ across the cohort. State-root divergence. Pin alongside item #6's T2.5.

## Mainnet reachability

**Reachable on canonical traffic at Glamsterdam activation, on every block that includes an attester slashing whose slashed validator has a non-trivial `effective_balance` and where the per-block `exit_balance_to_consume` is depleted past the divergent-formula threshold.**

**Trigger.** The first Gloas-slot block carrying an attester slashing fires `slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn(state, validator.effective_balance)`. Inside that primitive, the five Electra-formula clients compute `per_epoch_churn = get_activation_exit_churn_limit(state)`; lodestar computes `per_epoch_churn = get_exit_churn_limit(state)`. With ~30M ETH staked and the Gloas-specific `CHURN_LIMIT_QUOTIENT_GLOAS = 32768`, the two formulas yield different numeric churn ceilings. The `additional_epochs = (balance_to_process − 1) / per_epoch_churn + 1` arithmetic that advances `earliest_exit_epoch` and the slashed validator's `exit_epoch` therefore diverges per the 5-vs-1 cohort. The resulting `state.validators[slashed_index].exit_epoch` is written into state directly — the divergence is on observable post-state, not on a queue or accumulator that can be reconciled later.

**Severity.** State-root divergence on every Gloas-slot block carrying an attester slashing. Attester slashings are rare on mainnet but not impossible — and post-Pectra the slashable-pair search runs over more attestations (because EIP-7549 aggregates multiple committees, so each attestation covers more attesters). A single slashing block is enough to fork the chain between lodestar and the rest. Sister items: items #3 H8 (partial withdrawals), #6 H8 (voluntary exits and EL full-exits), #4 H8 (deposit activation churn — separate pool), and #2 H6 (consolidation churn — separate pool). All five share the same Gloas-laggard cohort.

**Mitigation window.** Source-only at audit time; no Gloas EF operations fixtures yet for this routine. Closing requires the five Electra-formula clients to fork-gate `compute_exit_epoch_and_update_churn` to consume `get_exit_churn_limit` at Gloas (same fix as items #3 / #6 H8 — one coordinated PR per client covers the entire EIP-8061 family across items #2, #3, #4, #6, #8). Without the fix, mainnet at Glamsterdam activation splits on the first slashing block, regardless of attestation traffic volume.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H8) remain satisfied: aligned implementations of the Casper FFG slashing predicate, both BLS aggregate verifications, set intersection + sort, the slashability check, the Pectra-changed quotient selection, and the `slashed_any` rejection. All 30 EF `attester_slashing` fixtures still pass uniformly on prysm + lighthouse + lodestar + grandine; teku and nimbus pass internally. The slashing constants (`MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA`, `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA`) are not modified at Gloas, so H6 and H7 continue to hold by spec.

**Glamsterdam-target finding (H9):** the function `process_attester_slashing` and the function `slash_validator` are both **unchanged** at Gloas (no Modified heading in the Gloas chapter; spec inherits Electra). But `slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn` cascades into the EIP-8061-Modified churn helper, which 5 of 6 clients (prysm, lighthouse, teku, nimbus, grandine) still pace via `get_activation_exit_churn_limit` instead of the spec-correct `get_exit_churn_limit`. Each slashed validator's `exit_epoch` and `withdrawable_epoch` therefore differ across the 5-vs-1 cohort at Gloas. Only lodestar fork-gates the call.

This is **the same divergence pattern** observed in items #3 H8 (partial withdrawals) and #6 H8 (voluntary exits + EL full-exits). The EIP-8061 churn family now spans 5 items: #2 H6 (consolidation), #3 H8 (partial withdrawals), #4 H8 (deposit activation), #6 H8 (voluntary exits + full-exits), #8 H9 (attester slashings via slash_validator). A single coordinated fix-PR per lagging client closes the entire family.

Notable per-client style differences (all observable-equivalent on the Pectra surface):

- **prysm** uses a central `SlashingParamsPerVersion(version)` switch — clean single dispatch point.
- **lighthouse** uses `BTreeSet` for the intersection (naturally sorted) and `state.get_min_slashing_penalty_quotient(spec)` for fork-keyed quotient selection.
- **teku** uses subclass-override polymorphism — `BeaconStateMutatorsElectra` overrides quotient getters.
- **nimbus** uses compile-time `when` blocks on the BeaconState type.
- **lodestar** uses a 5-deep nested ternary for the penalty quotient and a binary branch for the whistleblower reward; is also the only client whose underlying `compute_exit_epoch_and_update_churn` is fork-gated to use `get_exit_churn_limit` at Gloas.
- **grandine** uses type-associated constants `P::MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` (compile-time per `Preset`) AND `merge_join_by` for the lazy sorted-merge intersection.

Recommendations to the harness and the audit:

- Generate the **T2.6 Gloas churn-cascade fixture** for attester slashings; sister to items #3 T2.6 / #6 T2.5.
- Coordinate the **EIP-8061 churn-helper fork-gate** PR per lagging client to close items #2 H6, #3 H8, #4 H8, #6 H8, and this item's H9 together — they all touch the same family of churn accessors.
- Generate the **T2.1 multi-slashing-in-one-block fixture** as a sanity_blocks composition to lock the per-block stateful churn drain across multiple slashings.
- **Audit `process_proposer_slashing` next** — same `slash_validator` primitive, different upstream entry-point. Three items would converge on `slash_validator` (this, voluntary_exit via item #6, proposer_slashing).
- **Audit `process_slashings`** (per-epoch slashings application) — reads from `state.slashings` vector this item writes to; Pectra changed the multiplier.

## Cross-cuts

### With item #6 (`initiate_validator_exit` + `compute_exit_epoch_and_update_churn`)

`slash_validator` calls `initiate_validator_exit(state, slashed_index)` first thing — the Pectra-modified version audited in item #6. Each slashed validator's `exit_epoch` and `withdrawable_epoch` are set via the same churn-paced mechanism. The Glamsterdam-target H8/H9 divergence is **identical** to item #6's H8 — only the upstream entry-point differs (voluntary exit vs slashing). Multiple slashings within a single block share `state.exit_balance_to_consume`. The sort order of slashable indices matters for cumulative churn pacing.

### With item #7 (`process_attestation` EIP-7549)

`is_valid_indexed_attestation` is called twice here (once per attestation in the slashing pair). The IndexedAttestation has expanded list capacity in Pectra (MAX_VALIDATORS_PER_COMMITTEE × MAX_COMMITTEES_PER_SLOT = 131,072). A client with stale capacity would fail to deserialize attestations large enough to span multiple committees. At Gloas, the BLS aggregate machinery is shared — but item #7's Gloas divergences (lighthouse-only on `data.index < 2` + builder_pending_payments) do not directly propagate here because attester slashings carry pre-existing IndexedAttestations rather than processing live attestations.

### With `process_proposer_slashing` (next item candidate)

`process_proposer_slashing` ALSO calls `slash_validator` with the slashed validator's index. Both sources of slashing converge on the same Pectra-modified `slash_validator` machinery. The penalty/reward quotients audited here apply identically to proposer slashings. The Gloas H9 divergence also applies identically — proposer slashings at Gloas will produce divergent slashed-validator `exit_epoch` across the same 5-vs-1 cohort.

### With `process_slashings` (per-epoch slashings application)

`slash_validator` writes `state.slashings[epoch % EPOCHS_PER_SLASHINGS_VECTOR] += effective_balance`. The per-epoch `process_slashings` then reads this vector and applies a proportional slashing penalty across all validators. Pectra changed the slashing factor multiplier. A divergence in either side would produce different per-epoch penalty outcomes. WORKLOG candidate #10.

## Adjacent untouched Electra-active consensus paths

1. **`process_proposer_slashing`** — same `slash_validator` primitive. Cross-cut.
2. **`process_slashings`** (per-epoch) — reads `state.slashings` vector this item writes; Pectra changed the multiplier. WORKLOG #10.
3. **`MAX_ATTESTER_SLASHINGS_ELECTRA` per-block limit** — Pectra reduced this. A client with stale limit would accept too many slashings per block → state-root divergence at the next block.
4. **`is_double_vote` / `is_surround_vote` separate methods in lighthouse** — pyspec defines `is_slashable_attestation_data` as one combined predicate; lighthouse splits into two.
5. **`slash_validator` whistleblower != proposer cross-cut** — in pyspec, `whistleblower_index` defaults to `proposer_index`. If proposer == whistleblower, both increases land on the same balance (correct).
6. **`merge_join_by` correctness in grandine assumes sorted attesting_indices** — if any IndexedAttestation slips through with unsorted indices, grandine would silently miss validators in the intersection.
7. **lodestar's 5-deep nested ternary** for penalty quotient — at a future fork that changes the quotient, this would need another branch.
8. **prysm's `SlashingParamsPerVersion` central dispatch** — at a future fork, would need extension.
9. **teku's subclass-override pattern** — extending to a future fork requires `BeaconStateMutatorsGloas extends BeaconStateMutatorsElectra` with overridden methods if quotients change.
10. **`state.slashings[epoch % EPOCHS_PER_SLASHINGS_VECTOR]` vector indexing** — `EPOCHS_PER_SLASHINGS_VECTOR` is 8192 for mainnet. The modular indexing is straightforward; all 6 clients use it.
11. **EIP-8061 churn-family standalone audit** — item #2 H6, item #3 H8, item #4 H8, item #6 H8, item #8 H9 all share the same five-vs-one cohort. A single coordinated audit item on `compute_exit_epoch_and_update_churn` / `get_exit_churn_limit` / `get_activation_churn_limit` / `get_consolidation_churn_limit` as a family would be the highest-leverage Glamsterdam-readiness item.
