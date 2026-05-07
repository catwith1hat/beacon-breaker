# Item #8 — `process_attester_slashing` (EIP-7549 + EIP-7251)

**Status:** no-divergence-pending-fuzzing — audited 2026-05-03. **Hypotheses H1–H8 satisfied. All 30 EF `attester_slashing` operations fixtures pass on all four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus SKIP per harness limit.**

**Builds on:** items #6 (`initiate_validator_exit` Pectra-modified — called by `slash_validator`) and #7 (`process_attestation` EIP-7549 — `IndexedAttestation` expanded list capacity AND BLS aggregate verification share machinery with this item's `is_valid_indexed_attestation` calls).

**Electra-active.** Track-A-adjacent (slashing operations). Two flavors of Pectra changes: (1) **EIP-7549** expanded `IndexedAttestation.attesting_indices` list capacity from `MAX_VALIDATORS_PER_COMMITTEE` to `MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT`, and `MAX_ATTESTER_SLASHINGS_ELECTRA` (smaller per-block limit); (2) **EIP-7251** changed the slashing-penalty + whistleblower-reward divisor constants. The function itself (`process_attester_slashing`) is structurally unchanged from Phase0 — but `slash_validator` is Pectra-modified, and the IndexedAttestations being processed have a new shape.

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

`slash_validator` (Pectra-modified, `consensus-specs/specs/electra/beacon-chain.md:830-867`):

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

Eight divergence-prone bits:

A. **`is_slashable_attestation_data`** — Casper FFG: `(data1 != data2 ∧ data1.target.epoch == data2.target.epoch) ∨ (data1.source.epoch < data2.source.epoch ∧ data2.target.epoch < data1.target.epoch)`. Double vote OR surround vote.

B. **`is_valid_indexed_attestation`** — BLS aggregate verify; cross-cuts item #7. Pectra IndexedAttestation has expanded list capacity.

C. **Set intersection** of `a1.attesting_indices ∩ a2.attesting_indices` — must dedupe.

D. **Sorted iteration** of the intersection — affects `state.exit_balance_to_consume` (each `slash_validator` calls Pectra-modified `initiate_validator_exit` which mutates the churn accumulator; the order matters for cumulative effects) AND `state.slashings[epoch % VECTOR]` increments.

E. **`is_slashable_validator(v, epoch)`** — `not v.slashed AND v.activation_epoch <= epoch < v.withdrawable_epoch`.

F. **`MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA`** — Pectra-changed value (must NOT be the legacy `MIN_SLASHING_PENALTY_QUOTIENT_BELLATRIX` or earlier).

G. **`WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA`** — Pectra-changed value (must NOT be the legacy `WHISTLEBLOWER_REWARD_QUOTIENT`).

H. **`slashed_any` assertion** — at least one validator must be slashable; otherwise reject the whole slashing.

The hypothesis: *all six clients implement the FFG slashing predicate, the BLS aggregate verifications, set intersection + sort, the slashability check, the Pectra-changed quotient selection, and the slashed_any rejection identically.*

**Consensus relevance**: Slashings transfer effective_balance → state.slashings vector (impacts later `process_slashings` per-epoch penalty computation), reduce slashed validator's balance by `effective_balance / Q_pectra`, and reward proposer + whistleblower by `effective_balance / W_pectra` split. A divergence in any of (a) the FFG predicate (would silently accept or reject otherwise-slashable attestations); (b) the BLS aggregate verify (would silently accept invalid sigs); (c) the quotient values (would compute different penalty/reward, splitting the state-root); (d) the sort order (cumulative state mutations differ across slashings within one block) would split the chain immediately. This is an A-tier surface: an adversary that produces conflicting attestations can trigger this code path.

## Hypotheses

- **H1.** All six implement the same Casper FFG predicate: double vote (different data, same target epoch) OR surround vote (a1.source < a2.source ∧ a2.target < a1.target).
- **H2.** All six validate both attestations' BLS aggregate signatures via `is_valid_indexed_attestation`.
- **H3.** All six compute `set(a1.attesting_indices) ∩ set(a2.attesting_indices)` correctly (dedupe).
- **H4.** All six iterate the intersection in sorted (ascending) order.
- **H5.** All six implement `is_slashable_validator(v, epoch)` as `!v.slashed ∧ v.activation_epoch <= epoch < v.withdrawable_epoch`.
- **H6.** All six use `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` for the penalty divisor at the Pectra fork (NOT the Bellatrix legacy value).
- **H7.** All six use `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA` for the whistleblower reward divisor at the Pectra fork (NOT the legacy value).
- **H8.** All six reject the slashing when no validator was slashable (`slashed_any` assertion).

## Findings

H1–H8 satisfied. **No divergence at the source-level predicate.**

### prysm (`prysm/beacon-chain/core/blocks/attester_slashing.go:111-195` + `core/validators/validator.go:235-305`)

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

H1 ✓ (`IsSlashableAttestationData` at `attester_slashing.go:171-195`). H2 ✓ (`VerifyIndexedAttestation` × 2). H3 ✓ (`slice.IntersectionUint64`). H4 ✓ (`sort.SliceStable`). H5 ✓ (`IsSlashableValidator(activationEpoch, withdrawableEpoch, slashed, currentEpoch)`). H6 ✓. H7 ✓. H8 ✓.

**Notable**: prysm has a **central version-router** `SlashingParamsPerVersion(v)` (line 272) that returns the correct quotient triplet for each fork (`if v >= version.Electra { ... }`). All slashing call sites route through this, ensuring the Pectra constants are used uniformly post-Electra.

### lighthouse (`lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:254-277` + `verify_attester_slashing.rs:19-94` + `common/slash_validator.rs:16-79`)

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
// state.get_min_slashing_penalty_quotient: if fork.electra_enabled() { spec.min_slashing_penalty_quotient_electra }
// state.get_whistleblower_reward_quotient: if fork.electra_enabled() { spec.whistleblower_reward_quotient_electra }
```

H1 ✓ (`is_double_vote()` || `is_surround_vote()` on AttestationData). H2 ✓ (`is_valid_indexed_attestation` × 2 — same machinery as item #7). H3 ✓ (BTreeSet intersection — naturally sorted). H4 ✓ (BTreeSet iteration order is ascending). H5 ✓ (`validator.is_slashable_at(epoch)`). H6 ✓ via `state.get_min_slashing_penalty_quotient(spec)`. H7 ✓ via `state.get_whistleblower_reward_quotient(spec)`. H8 ✓.

**Notable**: lighthouse uses `BTreeSet` for the intersection — implicitly produces sorted output, so no separate sort step is needed. This is the most elegant implementation of the intersection-sort pair.

### teku (`teku/ethereum/spec/.../AbstractBlockProcessor.java:546-568` + `BeaconStateMutators.java:249` + `BeaconStateMutatorsElectra.java:253,258`)

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
// BeaconStateMutators.slashValidator(...) calls getMinSlashingPenaltyQuotient() and getWhistleblowerRewardQuotient()
// BeaconStateMutatorsElectra.java overrides:
@Override
protected int getWhistleblowerRewardQuotient() { return specConfigElectra.getWhistleblowerRewardQuotientElectra(); }
@Override
protected int getMinSlashingPenaltyQuotient() { return specConfigElectra.getMinSlashingPenaltyQuotientElectra(); }
```

H1 ✓ (`AttestationUtil.isSlashableAttestationData` at `:81`). H2 ✓ (delegated to `operationValidator`). H3 ✓ (intersection inside `validateAttesterSlashing`). H4 ✓ (sorted via the validation chain). H5 ✓ (`Predicates.isSlashableValidator` at `:82`). H6 ✓ (override). H7 ✓ (override). H8 ✓ (validation rejects non-slashable cases upfront).

**Notable**: teku uses **Java subclass-override polymorphism** to switch quotients at the fork boundary — `BeaconStateMutatorsElectra extends BeaconStateMutatorsBellatrix` (or similar). The base class's `slashValidator` calls abstract methods `getMinSlashingPenaltyQuotient()` / `getWhistleblowerRewardQuotient()` that the subclass overrides. Clean fork dispatch via OOP.

### nimbus (`nimbus/beacon_chain/spec/state_transition_block.nim:284-301` + `beaconstate.nim:426` + `beaconstate.nim:379-407`)

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

H1 ✓ (`is_slashable_attestation_data` at `state_transition_block.nim:222`). H2 ✓ (`is_valid_indexed_attestation` × 2 inside `check_attester_slashing`). H3 ✓ (set intersection inside `check_attester_slashing`). H4 ✓ (sorted iteration). H5 ✓ (`is_slashable_validator` at `state_transition_block.nim:138`). H6 ✓ (compile-time `when` block on state type). H7 ✓ (compile-time `when` block). H8 ✓ (`if slashed_indices.len == 0: return err(...)`).

**Notable**: nimbus uses **compile-time fork dispatch** via `when state is electra.BeaconState | fulu.BeaconState | gloas.BeaconState:` — the quotient is fixed at compile time per `BeaconState` type. Zero runtime overhead.

### lodestar (`lodestar/packages/state-transition/src/block/processAttesterSlashing.ts:16-47` + `block/slashValidator.ts:24-59`)

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

H1 ✓ (`isSlashableAttestationData` at `util/attestation.ts:15-25`). H2 ✓ (BLS via `assertValidAttesterSlashing`). H3 ✓ (`getIntersectingIndices` via Set-based traversal at `util/attestation.ts:37-47`). H4 ✓ (explicit `.sort((a, b) => a - b)` after intersection). H5 ✓ (`isSlashableValidator` at `util/validator.ts:25-27`). H6 ✓ (nested ternary). H7 ✓ (binary fork branch). H8 ✓ (`if (!slashedAny) throw`).

**Notable**: lodestar's **5-deep nested ternary** for the penalty quotient is the most explicit fork-dispatch pattern — clear at the call site but verbose. The whistleblower-reward uses a simpler binary branch (Pectra changed only one quotient there).

### grandine (`grandine/transition_functions/src/electra/block_processing.rs:656-684` + `helper_functions/src/electra.rs:153-192` + `helper_functions/src/accessors.rs:871-883`)

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

H1 ✓ (`is_slashable_attestation_data` at `helper_functions/predicates.rs:84-87`). H2 ✓ (BLS in `validate_attester_slashing_with_verifier`). H3 ✓ (`merge_join_by` is the **lazy sorted-merge intersection** — most efficient algorithm if both inputs are sorted; spec requires sorted attesting_indices). H4 ✓ (output of `merge_join_by` is sorted). H5 ✓ (`is_slashable_validator` at `predicates.rs:75-79` — `const fn`). H6 ✓ via `P::MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` (compile-time per Preset). H7 ✓ via `P::WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA`. H8 ✓ (validation rejects non-slashable cases).

**Notable**: grandine uses **`merge_join_by` from `itertools`** for the intersection — `O(n+m)` lazy iterator. This relies on `attesting_indices` being sorted (which the spec requires for `is_valid_indexed_attestation`). The output preserves sort order — no separate sort step needed.

## Cross-reference table

| Client | `process_attester_slashing` | Intersection algo | Sort | Penalty quotient | Whistleblower quotient | Quotient selection mechanism |
|---|---|---|---|---|---|---|
| prysm | `core/blocks/attester_slashing.go:111-142` | `slice.IntersectionUint64()` | `sort.SliceStable` | `MinSlashingPenaltyQuotientElectra` | `WhistleBlowerRewardQuotientElectra` | Central `SlashingParamsPerVersion(v)` switch on Version |
| lighthouse | `per_block_processing/process_operations.rs:254-277` | `BTreeSet` set algebra `&s1 & &s2` | implicit (BTreeSet ascending) | `spec.min_slashing_penalty_quotient_electra` | `spec.whistleblower_reward_quotient_electra` | `state.get_min_slashing_penalty_quotient(spec)` fork-name keyed |
| teku | `AbstractBlockProcessor.java:546` + `BeaconStateMutatorsElectra.java:253,258` | inside `operationValidator.validateAttesterSlashing` | implicit | `getMinSlashingPenaltyQuotientElectra()` | `getWhistleblowerRewardQuotientElectra()` | Subclass override (`BeaconStateMutatorsElectra extends ...`) |
| nimbus | `state_transition_block.nim:284-301` + `beaconstate.nim:426` | inside `check_attester_slashing` | sorted | `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` | `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA` | Compile-time `when state is electra.BeaconState \| ...` |
| lodestar | `block/processAttesterSlashing.ts:16-47` + `block/slashValidator.ts:24-59` | `getIntersectingIndices` Set-based traversal | explicit `.sort((a, b) => a - b)` | `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` | `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA` | 5-deep nested ternary on `ForkSeq` |
| grandine | `electra/block_processing.rs:656-684` + `helper_functions/electra.rs:153-192` | `merge_join_by(Ord::cmp)` lazy sorted-merge | implicit (output sorted) | `P::MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` | `P::WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA` | Type-associated const per `Preset` (compile-time) |

## Cross-cuts

### with item #6 (`initiate_validator_exit` + `compute_exit_epoch_and_update_churn`)

`slash_validator` calls `initiate_validator_exit(state, slashed_index)` first thing — the Pectra-modified version that uses `compute_exit_epoch_and_update_churn(state, validator.effective_balance)`. Each slashed validator's `exit_epoch` and `withdrawable_epoch` are set via the same churn-paced mechanism audited in item #6. Multiple slashings within a single block share `state.exit_balance_to_consume`. **The sort order of slashable indices matters** for cumulative churn pacing: if any client iterates in non-sorted order, the per-validator `exit_epoch` assignments shift differently across slashings.

### with item #7 (`process_attestation` EIP-7549)

`is_valid_indexed_attestation` is called twice here (once per attestation in the slashing pair). The IndexedAttestation has expanded list capacity in Pectra (MAX_VALIDATORS_PER_COMMITTEE × MAX_COMMITTEES_PER_SLOT = 131,072). A client with stale capacity would fail to deserialize attestations large enough to span multiple committees. The `BLS aggregate signature` machinery is also shared — same audit path as item #7 Section E.

### with `process_proposer_slashing` (next item candidate)

`process_proposer_slashing` ALSO calls `slash_validator` with the slashed validator's index. Both sources of slashing converge on the same Pectra-modified `slash_validator` machinery. The penalty/reward quotients audited here apply identically to proposer slashings. The `slash_validator` is the high-leverage primitive of all slashing types.

### with `process_slashings` (per-epoch slashings application)

`slash_validator` writes `state.slashings[epoch % EPOCHS_PER_SLASHINGS_VECTOR] += effective_balance`. The per-epoch `process_slashings` then reads this vector and applies a proportional slashing penalty across all validators. **Pectra changed the slashing factor multiplier**. A divergence in either side would produce different per-epoch penalty outcomes. WORKLOG candidate #10.

## Fixture

`fixture/`: deferred — used the existing 30 EF state-test fixtures at
`consensus-spec-tests/tests/mainnet/electra/operations/attester_slashing/pyspec_tests/`.

Run via `scripts/run_fixture.sh` against all six clients on 2026-05-03:

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

The 30-fixture suite covers:
- **Slashing types**: `basic_double`, `basic_surround`.
- **Negative FFG**: `invalid_no_double_or_surround`, `invalid_same_data` (data must differ).
- **Sig validity**: `invalid_incorrect_sig_1`, `invalid_incorrect_sig_2`, `invalid_incorrect_sig_1_and_2`.
- **Indexed-attestation invariants**: `invalid_unsorted_att_1`, `invalid_unsorted_att_2` (must be sorted), `invalid_att{1,2}_duplicate_index_*` (no dupes), `invalid_att{1,2}_empty_indices`, `invalid_all_empty_indices`, `invalid_att{1,2}_high_index` (out-of-range), `invalid_att{1,2}_bad_extra_index`, `invalid_att{1,2}_bad_replaced_index`.
- **Validator state**: `already_exited_long_ago`, `already_exited_recent`, `attestation_from_future`, `invalid_participants_already_slashed`, `proposer_index_slashed` (whistleblower==proposer edge case), `with_effective_balance_disparity`.
- **Balance variations**: `low_balances`, `misc_balances`.

## Fuzzing vectors

### T1 — Mainline canonical
- **T1.1 (priority — slashing of a high-balance compounding validator).** The slashed validator has `effective_balance = 2048 ETH` (max for compounding). Penalty = 2048 ETH / `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA`. Whistleblower reward = 2048 ETH / `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA`. Tests both Pectra quotients at the upper boundary. The `low_balances` and `misc_balances` fixtures probably touch this implicitly.
- **T1.2 (priority — slashing of a previously-consolidation-source-exited validator).** A validator that was exited via `process_consolidation_request` (item #2) is later slashed via attester slashing. The validator is already in the exit queue but `exit_epoch != FAR_FUTURE_EPOCH`. Per `is_slashable_validator`, this validator is NOT slashable (`epoch < withdrawable_epoch` may still hold but `validator.slashed` becomes true, and `withdrawable_epoch` gets `max`'d — could push the exit out further). Worth a custom composed fixture.

### T2 — Adversarial probes
- **T2.1 (priority — multi-slashing in one block with churn drain).** Block contains 2 attester slashings, each affecting 8 high-balance validators. Each validator's slashing calls `slash_validator` → `initiate_validator_exit` → `compute_exit_epoch_and_update_churn` mutating shared state. Verify all 6 produce the same final `exit_balance_to_consume` and per-validator `exit_epoch`. Not covered by single-op fixtures; requires sanity_blocks composition.
- **T2.2 (priority — proposer-as-whistleblower edge).** A slashing where the proposer is also a validator slashed by another slashing in the same block. The proposer earns the whistleblower reward + proposer reward, then becomes slashed — the rewards may need to be processed before the slashing or vice versa. Covered partially by `proposer_index_slashed`.
- **T2.3 (defensive — slashing already-slashed validator).** A second attester slashing in the same block targets a validator already slashed earlier in the block. `is_slashable_validator` returns false (`v.slashed == true`). Per H8, `slashed_any` only fires if at least one validator was slashable — so a slashing where ALL targets were already slashed must reject the whole slashing. Covered by `invalid_participants_already_slashed`.
- **T2.4 (defensive — IndexedAttestation with unsorted attesting_indices).** Spec says attesting_indices must be strictly increasing. A client that accepts unsorted indices would compute a different intersection. Covered by `invalid_unsorted_att_{1,2}`.
- **T2.5 (defensive — IndexedAttestation with duplicate indices).** Spec says no duplicates. Covered by `invalid_att{1,2}_duplicate_index_*`.

## Conclusion

**Status: no-divergence-pending-fuzzing.** All six clients implement the Casper FFG slashing predicate, both BLS aggregate verifications, set intersection + sort, the slashability check, and the Pectra-changed quotient selection identically.

Notable per-client style differences (all observable-equivalent):
- **prysm** uses a central `SlashingParamsPerVersion(version)` switch — clean single dispatch point.
- **lighthouse** uses `BTreeSet` for the intersection (naturally sorted) and `state.get_min_slashing_penalty_quotient(spec)` for fork-keyed quotient selection.
- **teku** uses **subclass-override polymorphism** — `BeaconStateMutatorsElectra extends ...` overrides `getMinSlashingPenaltyQuotient()` / `getWhistleblowerRewardQuotient()`.
- **nimbus** uses **compile-time `when` blocks** on the BeaconState type — zero runtime overhead.
- **lodestar** uses a **5-deep nested ternary** for the penalty quotient (per-fork explicit) and a binary branch for the whistleblower reward.
- **grandine** uses **type-associated constants** `P::MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` (compile-time per `Preset`) AND **`merge_join_by`** for the lazy sorted-merge intersection (most efficient algorithm).

No code-change recommendation. Audit-direction recommendations:
- **Generate the T2.1 multi-slashing-in-one-block fixture** as a sanity_blocks composition; would test the per-block stateful churn drain across multiple slashings.
- **Audit `process_proposer_slashing` next** — same `slash_validator` primitive, different upstream entry-point. Three items would converge on `slash_validator` (this, proposer_slashing, attester_slashing) — a strong cross-cut chain.
- **Audit `process_slashings`** (per-epoch slashings application) — Pectra changed the slashing-multiplier; reads from `state.slashings` vector this item writes to.

## Adjacent untouched Electra-active consensus paths

1. **`process_proposer_slashing`** — same `slash_validator` primitive. Cross-cut.
2. **`process_slashings`** (per-epoch) — reads `state.slashings` vector this item writes; Pectra changed the multiplier. WORKLOG #10.
3. **`MAX_ATTESTER_SLASHINGS_ELECTRA` per-block limit** — Pectra reduced this. A client with stale limit would accept too many slashings per block → state-root divergence at the next block. Worth a defensive sanity_blocks fixture exceeding the limit.
4. **`is_double_vote` / `is_surround_vote` separate methods in lighthouse** — pyspec defines `is_slashable_attestation_data` as one combined predicate; lighthouse splits into two. Worth verifying the boolean OR is preserved (a precedence bug could change semantics).
5. **`slash_validator` whistleblower != proposer cross-cut**: in pyspec, `whistleblower_index` defaults to `proposer_index`. A client that mishandles the `Optional` could double-credit if proposer == whistleblower (the rewards should still split correctly because `proposer_reward = whistleblower_reward * PROPOSER_WEIGHT // WEIGHT_DENOMINATOR` and the rest goes to whistleblower; if same address, both increases land on the same balance — correct).
6. **`merge_join_by` correctness in grandine assumes sorted attesting_indices** — if any IndexedAttestation slips through with unsorted indices (invariant should be enforced upstream), grandine would silently miss validators in the intersection. The `invalid_unsorted_att_*` fixtures guard against this; verify the upstream rejection happens BEFORE `merge_join_by` is called.
7. **lodestar's 5-deep nested ternary** for penalty quotient — at Gloas (next fork), this would need a new branch. Pre-emptive divergence vector if other clients silently default to Electra at Gloas.
8. **prysm's `SlashingParamsPerVersion` central dispatch** — `if v >= version.Electra` is the gate. At Gloas (version > Electra), prysm continues using Electra quotients unless extended; same pre-emptive concern.
9. **teku's subclass-override pattern** — extending to Gloas requires `BeaconStateMutatorsGloas extends BeaconStateMutatorsElectra` with overridden methods if quotients change.
10. **`state.slashings[epoch % EPOCHS_PER_SLASHINGS_VECTOR]` vector indexing** — `EPOCHS_PER_SLASHINGS_VECTOR` is 8192 for mainnet. The `% VECTOR` arithmetic is straightforward but subtle on integer underflow (which can't happen for `Epoch` u64). All 6 clients use modular indexing — no observed concern.
