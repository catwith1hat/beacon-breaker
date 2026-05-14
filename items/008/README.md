---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [6, 7]
eips: [EIP-7549, EIP-7251, EIP-8061]
prysm_version: v3.2.2-rc.1-2535-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 8: `process_attester_slashing` (EIP-7549 + EIP-7251)

## Summary

Casper FFG slashing entrypoint. Two flavors of Pectra changes: (1) **EIP-7549** expanded `IndexedAttestation.attesting_indices` list capacity from `MAX_VALIDATORS_PER_COMMITTEE` to `MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT`, and `MAX_ATTESTER_SLASHINGS_ELECTRA` (smaller per-block limit); (2) **EIP-7251** changed the slashing-penalty + whistleblower-reward divisor constants (`MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` and `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA`). The function itself (`process_attester_slashing`) is structurally unchanged from Phase0 — but `slash_validator` is Pectra-modified, and the IndexedAttestations being processed have a new shape.

**Pectra surface (the function body itself):** all six clients implement the Casper FFG slashing predicate, both BLS aggregate verifications, set intersection + sort, the slashability check, and the Pectra-changed quotient selection identically. 30/30 EF `attester_slashing` operations fixtures pass uniformly on the four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus pass these in internal CI but the local harness SKIPs them.

**Gloas surface (new at the Glamsterdam target):** `process_attester_slashing` and `slash_validator` are both **unchanged** at Gloas (no Modified heading in `vendor/consensus-specs/specs/gloas/beacon-chain.md`; the slashing constants are also unchanged). The function bodies and quotient selection (H1–H8) remain aligned. `slash_validator` calls `initiate_validator_exit(state, slashed_index)` → `compute_exit_epoch_and_update_churn(state, validator.effective_balance)` — the latter **is** Modified at Gloas (EIP-8061) to consume `get_exit_churn_limit`. With items #3 H8 / #6 H8 now vacated at the current pins (all six clients fork-gate the churn helper), the inherited H9 here vacates too: every slashed validator at Gloas gets the spec-correct `exit_epoch` advance via `get_exit_churn_limit` regardless of which client processed the slashing.

No splits at the current pins. The earlier finding (H9 failing for prysm + lighthouse + teku + nimbus + grandine) was a stale-pin artifact downstream of items #3 / #6 — once those vacated under the per-client Glamsterdam branches, every slashing entry-point inherits the spec-correct churn pacing automatically.

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

`slash_validator` does call `initiate_validator_exit`, which calls `compute_exit_epoch_and_update_churn` (Pectra-modified) which at Gloas is **further Modified** (EIP-8061) to consume `get_exit_churn_limit` instead of `get_activation_exit_churn_limit`. Items #3 H8 / #6 H8 now confirm that all six clients fork-gate that helper (via six distinct dispatch idioms; see item #6's catalog). So the slashed validator's `exit_epoch` advance is paced per the Gloas spec automatically — this item's H9 is satisfied by-construction.

The hypothesis: *all six clients implement the FFG slashing predicate, the BLS aggregate verifications, set intersection + sort, the slashability check, the Pectra-changed quotient selection, and the slashed_any rejection identically (H1–H8); and at the Glamsterdam target all six fork-gate the underlying `compute_exit_epoch_and_update_churn` to use `get_exit_churn_limit` so that the slashed validator's `exit_epoch` advance is paced per the Gloas spec (H9).*

**Consensus relevance**: slashings transfer effective_balance → state.slashings vector, reduce slashed validator's balance, and reward proposer + whistleblower. A divergence in any Pectra-surface bit (predicate, BLS, quotients, sort order) would split the chain immediately. A divergence in the underlying churn helper (H9) would shift the `exit_epoch` written into the slashed validator's record — but with the EIP-8061 family closed across all six clients (items #2 H6, #3 H8, #4 H8, #6 H8), every slashing entry-point at Gloas now produces the same post-state. This is an A-tier surface — an adversary that produces conflicting attestations can trigger this code path — but it is no longer a Gloas-activation divergence axis.

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

H1–H9 satisfied across all six clients at the current Glamsterdam-target pins. The Pectra-surface bits (H1–H8) align on body shape; the Gloas-target H9 inherits from item #6 H8 via the `slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn` chain, and item #6's six dispatch idioms for the churn fork-gate apply here unchanged.

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

`SlashValidator` (`vendor/prysm/beacon-chain/core/validators/validator.go:235-305`) calls `InitiateValidatorExitForTotalBal(ctx, s, slashedIdx, exitInfo, totalActiveBalance)` near the top — same function audited in item #6. That delegates to `state.ExitEpochAndUpdateChurnForTotalBal(...)`, whose inner `exitEpochAndUpdateChurn` at `vendor/prysm/beacon-chain/state/state-native/setters_churn.go:62-67` now uses `helpers.ExitChurnLimitForVersion(b.version, totalActiveBalance)` — the runtime version wrapper that dispatches to `exitChurnLimitGloas` for Gloas (per item #6's H8 dispatch).

H1 ✓ (`IsSlashableAttestationData` at `attester_slashing.go:171-195`). H2 ✓ (`VerifyIndexedAttestation` × 2). H3 ✓ (`slice.IntersectionUint64`). H4 ✓ (`sort.SliceStable`). H5 ✓ (`IsSlashableValidator(activationEpoch, withdrawableEpoch, slashed, currentEpoch)`). H6 ✓. H7 ✓. H8 ✓. **H9 ✓** (via the now-fork-gated `ExitChurnLimitForVersion` wrapper inherited from item #6).

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

`slash_validator` (in `common/slash_validator.rs`) calls `state.initiate_validator_exit(slashed_index, spec)?` near the top — the same Pectra-modified function audited in item #6. That delegates to `compute_exit_epoch_and_update_churn(effective_balance, spec)?` at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2896-2935`, which now internally fork-gates the per-epoch churn via `if self.fork_name_unchecked().gloas_enabled() { self.get_exit_churn_limit(spec)? } else { self.get_activation_exit_churn_limit(spec)? }` (name-polymorphism dispatch per item #6's H8 catalog).

H1 ✓ (`is_double_vote()` || `is_surround_vote()`). H2 ✓. H3 ✓ (BTreeSet intersection — naturally sorted). H4 ✓ (BTreeSet ascending). H5 ✓ (`validator.is_slashable_at(epoch)`). H6 ✓ via `state.get_min_slashing_penalty_quotient(spec)`. H7 ✓ via `state.get_whistleblower_reward_quotient(spec)`. H8 ✓. **H9 ✓**.

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

`slashValidator` (`BeaconStateMutators.java`) calls `initiateValidatorExit(state, index, validatorExitContextSupplier)` near the top — same function audited in item #6. The Electra subclass `BeaconStateMutatorsElectra` (`:108-132`) calls `computeExitEpochAndUpdateChurn(stateElectra, validator.getEffectiveBalance())` at line 121, but at Gloas the Java virtual dispatch resolves to `BeaconStateMutatorsGloas.computeExitEpochAndUpdateChurn` (`:71-99` in the Gloas mutator), which `@Override`s the Electra method and substitutes `getExitChurnLimit(state)` (per item #6's H8 dispatch).

H1 ✓ (`AttestationUtil.isSlashableAttestationData`). H2 ✓ (delegated to `operationValidator`). H3 ✓. H4 ✓. H5 ✓ (`Predicates.isSlashableValidator`). H6 ✓ (override). H7 ✓ (override). H8 ✓. **H9 ✓**.

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

`slash_validator` calls `initiate_validator_exit(cfg, state, slashed_index, exit_queue_info, cache)` at the start — same function audited in item #6. That calls `compute_exit_epoch_and_update_churn`, whose body at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:353-388` now selects the per-epoch churn at compile time via `when typeof(state).kind >= ConsensusFork.Gloas: get_exit_churn_limit(cfg, state, cache) else: get_activation_exit_churn_limit(...)` (per item #6's H8 dispatch).

H1 ✓ (`is_slashable_attestation_data`). H2 ✓. H3 ✓. H4 ✓. H5 ✓ (`is_slashable_validator`). H6 ✓ (compile-time `when` block on state type). H7 ✓ (compile-time `when` block). H8 ✓. **H9 ✓**.

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

`slashValidator` (`vendor/lodestar/packages/state-transition/src/block/slashValidator.ts:24-59`) calls `initiateValidatorExit(fork, state, slashedIndex)` near the top — same function audited in item #6. That at `vendor/lodestar/packages/state-transition/src/block/initiateValidatorExit.ts:27-62` calls `computeExitEpochAndUpdateChurn(state, BigInt(validator.effectiveBalance))`, whose body at `vendor/lodestar/packages/state-transition/src/util/epoch.ts:50-77` is the fork-gated runtime ternary (per item #6's H8 dispatch).

H1 ✓ (`isSlashableAttestationData`). H2 ✓. H3 ✓ (Set-based traversal). H4 ✓ (explicit `.sort((a, b) => a - b)`). H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓**.

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

`slash_validator` (`vendor/grandine/helper_functions/src/electra.rs`) calls `initiate_validator_exit(config, state, slashed_index)` near the top — same Pectra version audited in item #6 at `vendor/grandine/helper_functions/src/electra.rs:124-150`. That calls `compute_exit_epoch_and_update_churn`, whose body at `vendor/grandine/helper_functions/src/mutators.rs:172-208` now fork-gates via `if state.is_post_gloas() { get_exit_churn_limit(config, state) } else { get_activation_exit_churn_limit(config, state) }` (per item #6's H8 dispatch).

H1 ✓ (`is_slashable_attestation_data`). H2 ✓. H3 ✓ (`merge_join_by` lazy sorted-merge). H4 ✓ (output sorted). H5 ✓ (`is_slashable_validator` — `const fn`). H6 ✓ (`P::MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA`). H7 ✓ (`P::WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA`). H8 ✓. **H9 ✓**.

## Cross-reference table

| Client | `process_attester_slashing` | Intersection algo | Sort | Penalty quotient | Whistleblower quotient | `slash_validator` → `initiate_validator_exit` churn fork-gate (H9) |
|---|---|---|---|---|---|---|
| prysm | `core/blocks/attester_slashing.go:111-142` | `slice.IntersectionUint64()` | `sort.SliceStable` | `MinSlashingPenaltyQuotientElectra` | `WhistleBlowerRewardQuotientElectra` | ✓ runtime wrapper (`setters_churn.go:67` `helpers.ExitChurnLimitForVersion(b.version, ...)`) |
| lighthouse | `per_block_processing/process_operations.rs:254-277` | `BTreeSet` set algebra `&s1 & &s2` | implicit (BTreeSet ascending) | `spec.min_slashing_penalty_quotient_electra` | `spec.whistleblower_reward_quotient_electra` | ✓ name-polymorphism (`beacon_state.rs:2906-2910` internal `gloas_enabled()` branch) |
| teku | `AbstractBlockProcessor.java:546` + `BeaconStateMutatorsElectra.java:253,258` | inside `operationValidator.validateAttesterSlashing` | implicit | `getMinSlashingPenaltyQuotientElectra()` | `getWhistleblowerRewardQuotientElectra()` | ✓ subclass override (`BeaconStateMutatorsGloas.computeExitEpochAndUpdateChurn:71-99`) |
| nimbus | `state_transition_block.nim:284-301` + `beaconstate.nim:426` | inside `check_attester_slashing` | sorted | `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` | `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA` | ✓ compile-time `when typeof(state).kind >= ConsensusFork.Gloas` (`beaconstate.nim:362-365`) |
| lodestar | `block/processAttesterSlashing.ts:16-47` + `block/slashValidator.ts:24-59` | `getIntersectingIndices` Set-based traversal | explicit `.sort((a, b) => a - b)` | `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` | `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA` | ✓ runtime ternary (`util/epoch.ts:50-77` fork-gates `getExitChurnLimit` at `fork >= ForkSeq.gloas`) |
| grandine | `electra/block_processing.rs:656-684` + `helper_functions/electra.rs:153-192` | `merge_join_by(Ord::cmp)` lazy sorted-merge | implicit (output sorted) | `P::MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` | `P::WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA` | ✓ `state.is_post_gloas()` predicate (`mutators.rs:181-185`) |

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

No Gloas operations fixtures yet exist for `process_attester_slashing` (and none would change the function body — the Gloas modification is upstream in `compute_exit_epoch_and_update_churn`, where all six clients now fork-gate). H9 is currently source-only; sister to item #6's T2.5 (which covers the upstream churn-helper directly).

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — slashing of a high-balance compounding validator).** Slashed validator has `effective_balance = 2048 ETH`. Penalty = 2048 ETH / `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA`. Whistleblower reward = 2048 ETH / `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA`. Tests both Pectra quotients at the upper boundary.
- **T1.2 (priority — slashing of a previously-consolidation-source-exited validator).** A validator already in the exit queue is slashed. `is_slashable_validator` returns false if `validator.slashed` is true OR `epoch >= withdrawable_epoch`. Worth a custom composed fixture.

#### T2 — Adversarial probes
- **T2.1 (priority — multi-slashing in one block with churn drain).** Block contains 2 attester slashings, each affecting 8 high-balance validators. Each `slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn` mutates shared `state.exit_balance_to_consume`. At Gloas, the per_epoch_churn quantity is `get_exit_churn_limit(state)` (uniformly across all six clients post-fork-gate), so cumulative drain converges. Generate as a sanity_blocks fixture once Gloas fixtures land.
- **T2.2 (priority — proposer-as-whistleblower edge).** Covered partially by `proposer_index_slashed`.
- **T2.3 (defensive — slashing already-slashed validator).** Covered by `invalid_participants_already_slashed`.
- **T2.4 (defensive — IndexedAttestation with unsorted attesting_indices).** Covered by `invalid_unsorted_att_{1,2}`.
- **T2.5 (defensive — IndexedAttestation with duplicate indices).** Covered by `invalid_att{1,2}_duplicate_index_*`.
- **T2.6 (Glamsterdam-target — Gloas churn cascade).** Synthetic Gloas-fork state where `state.exit_balance_to_consume` is depleted to a non-zero value. Submit a single attester slashing that affects one high-balance validator (`effective_balance` chosen to straddle the Electra/Gloas churn-limit divergence). Expected per Gloas spec: every client computes `additional_epochs` via `get_exit_churn_limit`. Cross-client `state_root` should match. Pin alongside item #6's T2.5.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H8) remain satisfied: aligned implementations of the Casper FFG slashing predicate, both BLS aggregate verifications, set intersection + sort, the slashability check, the Pectra-changed quotient selection, and the `slashed_any` rejection. All 30 EF `attester_slashing` fixtures still pass uniformly on prysm + lighthouse + lodestar + grandine; teku and nimbus pass internally. The slashing constants (`MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA`, `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA`) are not modified at Gloas, so H6 and H7 continue to hold by spec.

**Glamsterdam-target finding (H9):** the function `process_attester_slashing` and the function `slash_validator` are both **unchanged** at Gloas (no Modified heading in the Gloas chapter; spec inherits Electra). `slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn` cascades into the EIP-8061-Modified churn helper, which all six clients now fork-gate per the six distinct dispatch idioms catalogued in item #6 (prysm `ExitChurnLimitForVersion` runtime wrapper, lighthouse `fork_name_unchecked().gloas_enabled()` name-polymorphism, teku `BeaconStateMutatorsGloas` subclass override, nimbus compile-time `when`, lodestar runtime ternary, grandine `state.is_post_gloas()` predicate). Each slashed validator's `exit_epoch` and `withdrawable_epoch` therefore advance per the spec-correct Gloas pacing on every client.

The earlier finding (H9 failing for prysm + lighthouse + teku + nimbus + grandine) was a stale-pin artifact downstream of items #3 H8 / #6 H8. With those vacated under the per-client Glamsterdam branches, every entry-point that funnels into `compute_exit_epoch_and_update_churn` — voluntary exits (item #6), EL full-exits (item #3), and slashings (this item) — inherits the spec-correct churn pacing automatically.

Notable per-client style differences (all observable-equivalent on the Pectra surface):

- **prysm** uses a central `SlashingParamsPerVersion(version)` switch — clean single dispatch point.
- **lighthouse** uses `BTreeSet` for the intersection (naturally sorted) and `state.get_min_slashing_penalty_quotient(spec)` for fork-keyed quotient selection.
- **teku** uses subclass-override polymorphism — `BeaconStateMutatorsElectra` overrides quotient getters; `BeaconStateMutatorsGloas` further overrides `computeExitEpochAndUpdateChurn`.
- **nimbus** uses compile-time `when` blocks on the BeaconState type.
- **lodestar** uses a 5-deep nested ternary for the penalty quotient and a binary branch for the whistleblower reward.
- **grandine** uses type-associated constants `P::MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` (compile-time per `Preset`) AND `merge_join_by` for the lazy sorted-merge intersection.

Recommendations to the harness and the audit:

- Generate the **T2.6 Gloas churn-cascade fixture** for attester slashings; sister to items #3 T2.6 / #6 T2.5. Now a confirmation fixture rather than a divergence-detection fixture.
- Generate the **T2.1 multi-slashing-in-one-block fixture** as a sanity_blocks composition to lock the per-block stateful churn drain across multiple slashings.
- **Audit `process_proposer_slashing` next** — same `slash_validator` primitive, different upstream entry-point. Three items would converge on `slash_validator` (this, voluntary_exit via item #6, proposer_slashing).
- **Audit `process_slashings`** (per-epoch slashings application) — reads from `state.slashings` vector this item writes to; Pectra changed the multiplier.

## Cross-cuts

### With item #6 (`initiate_validator_exit` + `compute_exit_epoch_and_update_churn`)

`slash_validator` calls `initiate_validator_exit(state, slashed_index)` first thing — the Pectra-modified version audited in item #6. Each slashed validator's `exit_epoch` and `withdrawable_epoch` are set via the same churn-paced mechanism. The Glamsterdam-target H9 inherits from item #6 H8, and with item #6 H8 vacated, this item's H9 vacates too. Multiple slashings within a single block share `state.exit_balance_to_consume`. The sort order of slashable indices matters for cumulative churn pacing.

### With item #7 (`process_attestation` EIP-7549)

`is_valid_indexed_attestation` is called twice here (once per attestation in the slashing pair). The IndexedAttestation has expanded list capacity in Pectra (MAX_VALIDATORS_PER_COMMITTEE × MAX_COMMITTEES_PER_SLOT = 131,072). A client with stale capacity would fail to deserialize attestations large enough to span multiple committees. At Gloas, the BLS aggregate machinery is shared; item #7's Gloas hypotheses (H9, H10) are also now uniform across all six clients, so neither side of this cross-cut introduces a divergence.

### With `process_proposer_slashing` (next item candidate)

`process_proposer_slashing` ALSO calls `slash_validator` with the slashed validator's index. Both sources of slashing converge on the same Pectra-modified `slash_validator` machinery. The penalty/reward quotients audited here apply identically to proposer slashings. The Gloas H9 path (via `slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn`) also applies identically — proposer slashings at Gloas produce the spec-correct slashed-validator `exit_epoch` across all six clients.

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
11. **EIP-8061 churn-family standalone audit** — items #2 H6, #3 H8, #4 H8, #6 H8, this item's H9 all shared the same dispatch-idiom catalog. A single coordinated audit item on `compute_exit_epoch_and_update_churn` / `get_exit_churn_limit` / `get_activation_churn_limit` / `get_consolidation_churn_limit` as a family is now a uniform-implementation cross-cut rather than a divergence axis.
