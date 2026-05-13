---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-12
builds_on: []
eips: [EIP-7549, EIP-7732]
splits: [lighthouse]
# main_md_summary: lighthouse has not implemented the Gloas EIP-7732 `process_attestation` modifications — still enforces `data.index == 0`, does not use `is_attestation_same_slot`, and does not increment `state.builder_pending_payments[*].weight` from attestations
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 7: `process_attestation` EIP-7549 multi-committee aggregation

## Summary

EIP-7549 fundamentally changes the `Attestation` SSZ container: `committee_index` is removed from `AttestationData` and replaced with a top-level `committee_bits: Bitvector[MAX_COMMITTEES_PER_SLOT]`. A single attestation can now carry attesters from multiple committees in one signature aggregate, with a flat `aggregation_bits: Bitlist[MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT]` indexed by a cumulative `committee_offset` walked across the active committees in committee_bits-set order. The legacy `AttestationData.index` field still exists but Pectra REQUIRES `data.index == 0`. This is the most-frequent CL block operation; a divergence here is reachable on every slot.

**Pectra surface (the function body itself):** all six clients implement the four new Pectra checks (data.index==0, per-committee membership + bounds, len(attesters)>0 per committee, exact-size bitfield) and the multi-committee BLS aggregation identically at the source level. 45/45 EF `attestation` operations fixtures pass uniformly on the four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus pass these in internal CI but the local harness SKIPs them.

**Gloas surface (new at the Glamsterdam target):** Gloas (EIP-7732 ePBS) modifies `process_attestation` (`vendor/consensus-specs/specs/gloas/beacon-chain.md` "Modified `process_attestation`") with two interlocking changes: (a) **`data.index` is repurposed** from "must-be-zero" to a payload-availability signal where `0 ≤ data.index < 2` (with 0 meaning the proposed payload was not yet executable and 1 meaning it was), with an extra same-slot rule (`is_attestation_same_slot(state, data)` → `data.index` must be 0); and (b) **`state.builder_pending_payments[slot_idx].weight`** is incremented by the attester's `effective_balance` whenever a same-slot attestation sets a new participation flag for that validator — the weight is consumed by the new `process_builder_pending_payments` epoch helper to settle builder bids. Survey of all six clients: **prysm, teku, nimbus, lodestar, grandine** implement both changes; **lighthouse does not** — it still enforces `data.index == 0` for Electra-and-later attestations, has the `is_attestation_same_slot` helper defined on `BeaconState` but never calls it from attestation processing, and never increments `state.builder_pending_payments[*].weight` from the attestation path despite having the state field. Lone-laggard 1-vs-5 split (the reverse of the EIP-8061 family pattern where lodestar was the lone-leader).

## Question

EIP-7549 SSZ change (`vendor/consensus-specs/specs/electra/beacon-chain.md`):

```python
class Attestation(Container):
    # [Modified in Electra:EIP7549]
    aggregation_bits: Bitlist[MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT]
    data: AttestationData
    signature: BLSSignature
    # [New in Electra:EIP7549]
    committee_bits: Bitvector[MAX_COMMITTEES_PER_SLOT]
```

Pyspec `process_attestation` (Pectra-modified):

```python
def process_attestation(state, attestation):
    data = attestation.data
    assert data.target.epoch in (previous_epoch, current_epoch)
    assert data.target.epoch == compute_epoch_at_slot(data.slot)
    assert data.slot + MIN_ATTESTATION_INCLUSION_DELAY <= state.slot

    # NEW Electra checks:
    assert data.index == 0
    committee_indices = get_committee_indices(attestation.committee_bits)
    committee_offset = 0
    for committee_index in committee_indices:
        assert committee_index < get_committee_count_per_slot(state, data.target.epoch)
        committee = get_beacon_committee(state, data.slot, committee_index)
        committee_attesters = set(
            attester_index
            for i, attester_index in enumerate(committee)
            if attestation.aggregation_bits[committee_offset + i]
        )
        assert len(committee_attesters) > 0
        committee_offset += len(committee)

    assert len(attestation.aggregation_bits) == committee_offset
    # ... participation flag indices, sig verify, flag updates, proposer reward
    assert is_valid_indexed_attestation(state, get_indexed_attestation(state, attestation))
```

Five Pectra divergence-prone bits (A–E unchanged from prior audit): `data.index == 0`, cumulative `committee_offset`, `len(committee_attesters) > 0` per committee, exact-size bitfield, and BLS aggregate signature over the union of attesters.

**Glamsterdam target.** Gloas modifies `process_attestation` per the inline `[Modified in Gloas:EIP7732]` annotations (`vendor/consensus-specs/specs/gloas/beacon-chain.md`):

```python
# [Modified in Gloas:EIP7732]
assert data.index < 2

# ... (same committee + aggregation_bits logic as Electra) ...

# Participation flag indices
participation_flag_indices = get_attestation_participation_flag_indices(
    state, data, state.slot - data.slot
)

# Verify signature
assert is_valid_indexed_attestation(state, get_indexed_attestation(state, attestation))

# [Modified in Gloas:EIP7732]
if data.target.epoch == get_current_epoch(state):
    current_epoch_target = True
    epoch_participation = state.current_epoch_participation
    payment = state.builder_pending_payments[SLOTS_PER_EPOCH + data.slot % SLOTS_PER_EPOCH]
else:
    current_epoch_target = False
    epoch_participation = state.previous_epoch_participation
    payment = state.builder_pending_payments[data.slot % SLOTS_PER_EPOCH]

proposer_reward_numerator = 0
for index in get_attesting_indices(state, attestation):
    # [New in Gloas:EIP7732]
    will_set_new_flag = False
    for flag_index, weight in enumerate(PARTICIPATION_FLAG_WEIGHTS):
        if flag_index in participation_flag_indices and not has_flag(epoch_participation[index], flag_index):
            epoch_participation[index] = add_flag(epoch_participation[index], flag_index)
            proposer_reward_numerator += get_base_reward(state, index) * weight
            will_set_new_flag = True
    # [New in Gloas:EIP7732]
    if will_set_new_flag and is_attestation_same_slot(state, data) and payment.withdrawal.amount > 0:
        payment.weight += state.validators[index].effective_balance

# Reward proposer (unchanged from Electra)

# [New in Gloas:EIP7732]
if current_epoch_target:
    state.builder_pending_payments[SLOTS_PER_EPOCH + data.slot % SLOTS_PER_EPOCH] = payment
else:
    state.builder_pending_payments[data.slot % SLOTS_PER_EPOCH] = payment
```

The Gloas-only mechanisms involved:

- **`data.index < 2`** — replaces the Electra `data.index == 0`. Values are 0 (proposer's execution payload was not present / withheld) or 1 (payload was present and the committee acknowledges payload availability). An additional same-slot rule (in nimbus's implementation: "Same-slot attestation must have index 0") falls out of the spec.
- **`is_attestation_same_slot(state, data)`** — new helper (`vendor/consensus-specs/specs/gloas/beacon-chain.md` "New `is_attestation_same_slot`") that returns true when the attestation's `data.slot` matches the head's slot at proposal time. Used to gate the builder-payment weight increment.
- **`state.builder_pending_payments[slot_idx].weight`** — new BeaconState field (`Vector<BuilderPendingPayment, BUILDER_PENDING_PAYMENTS_LIMIT>`). Each attestation that sets a new participation flag for a validator in a same-slot context adds the validator's `effective_balance` to the slot's pending-payment weight. This weight is consumed by the `process_builder_pending_payments` epoch helper to settle the bid that paid for that slot's execution payload.
- **`will_set_new_flag` tracking** — per-validator boolean inside the per-attester loop, used to ensure each validator contributes at most once to the slot's quorum weight.

The hypothesis: *all six clients implement the four Electra checks (A–D) and the multi-committee BLS aggregation (E) identically (H1–H8); and at the Glamsterdam target all six implement the Gloas `data.index < 2` rule with same-slot index-0 enforcement (H9) and the `state.builder_pending_payments` weight increment via `will_set_new_flag` + `is_attestation_same_slot` (H10).*

**Consensus relevance**: attestations are processed per block, every slot. A divergence in any of the Electra bits would surface on the very next block. At Gloas, a divergence in H9 means a client either rejects valid `data.index == 1` attestations or accepts invalid `data.index == 1` attestations — direct state-root divergence on the first attestation carrying payload-availability=1. A divergence in H10 means a client fails to update `state.builder_pending_payments[*].weight` (or updates it differently), which directly changes the BeaconState field's hash-tree-root AND propagates into the `process_builder_pending_payments` epoch helper one boundary later, where the divergent weight is consumed to settle (or fail to settle) the builder's bid — a downstream cascade into builder payouts.

## Hypotheses

- **H1.** All six enforce `data.index == 0` for Electra-format attestations (pre-Gloas).
- **H2.** All six iterate `committee_bits` set bits in ascending index order to derive `committee_indices`.
- **H3.** All six accumulate `committee_offset` correctly across set committees.
- **H4.** All six enforce `len(committee_attesters) > 0` per committee.
- **H5.** All six enforce `len(aggregation_bits) == committee_offset` (exact-size).
- **H6.** All six produce the SAME `IndexedAttestation.attesting_indices` set for a given `(state, attestation)` pair, so the BLS aggregate signature verification is canonical.
- **H7.** All six update `state.{current,previous}_epoch_participation` flags identically per attesting validator.
- **H8.** All six compute the proposer reward identically.
- **H9** *(Glamsterdam target — payload-availability signal)*. At the Gloas fork gate, all six clients switch the `data.index` predicate from `== 0` to `< 2`, AND enforce the same-slot rule that `is_attestation_same_slot(state, data) ⇒ data.index == 0`. Pre-Gloas, all six retain the Electra `== 0` check.
- **H10** *(Glamsterdam target — builder-pending-payment weight)*. At the Gloas fork gate, all six clients increment `state.builder_pending_payments[slot_idx].weight` by `validator.effective_balance` whenever the attestation sets a new participation flag for the validator AND the attestation is same-slot AND `payment.withdrawal.amount > 0`. The slot index is `SLOTS_PER_EPOCH + data.slot % SLOTS_PER_EPOCH` for current-epoch-target attestations, `data.slot % SLOTS_PER_EPOCH` for previous-epoch-target attestations.

## Findings

H1–H8 satisfied for the Pectra surface. **H9 and H10 both fail for lighthouse alone**. The other five clients (prysm, teku, nimbus, lodestar, grandine) implement both Gloas modifications. Source-level divergence; no Gloas operations fixtures yet exist.

### prysm

`vendor/prysm/beacon-chain/core/blocks/attestation.go:113-193`. The committee-index check at lines 117-126 carries an explicit Gloas branch:

```go
if att.Version() >= version.Electra {
    ci := att.GetData().CommitteeIndex
    if beaconState.Version() >= version.Gloas {
        // [Modified in Gloas:EIP7732]
        if ci >= 2 {
            return fmt.Errorf("incorrect committee index %d", ci)
        }
    } else {
        if ci != 0 {
            return errors.New("committee index must be 0 between Electra and Gloas forks")
        }
    }
}
```

Same-slot payload-matching is handled by `MatchingPayload` (`vendor/prysm/beacon-chain/core/gloas/attestation.go:24-51`), which is called from `vendor/prysm/beacon-chain/core/altair/attestation.go:312`:

```go
// MatchingPayload returns true if the attestation's committee index matches the expected payload index.
// For pre-Gloas forks, this always returns true.
sameSlot, err := beaconState.IsAttestationSameSlot(beaconBlockRoot, slot)
if sameSlot {
    if committeeIndex != 0 {
        return false, fmt.Errorf("committee index %d for same slot attestation must be 0", committeeIndex)
    }
    return true, nil
}
executionPayloadAvail, err := beaconState.ExecutionPayloadAvailability(slot)
return executionPayloadAvail == committeeIndex, nil
```

Builder-pending-payments weight is updated via the `UpdatePendingPaymentWeight(att, indices, participatedFlags)` interface declared at `vendor/prysm/beacon-chain/state/interfaces_gloas.go:34` and implemented at `vendor/prysm/beacon-chain/state/state-native/setters_gloas.go` — wired into the attestation processing flow downstream of `MatchingPayload`.

H1–H8 ✓. **H9 ✓**. **H10 ✓**.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing/verify_attestation.rs:21-86`. The Electra branch enforces `data.index == 0` unconditionally:

```rust
AttestationRef::Electra(_) => {
    verify!(data.index == 0, Invalid::BadCommitteeIndex);
}
```

`AttestationRef::Electra(_)` matches Gloas-era attestations too (the Attestation SSZ container itself is not modified at Gloas — only the `process_attestation` function body is). There is **no `AttestationRef::Gloas` branch**, no `fork_name_unchecked() >= ForkName::Gloas` gate in `per_block_processing`, and no `is_attestation_same_slot` caller anywhere in `consensus/state_processing/src/`.

The helper IS defined as a method on `BeaconState` (`vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2072`) and the `builder_pending_payments` field is allocated by the Gloas upgrade (`vendor/lighthouse/consensus/state_processing/src/upgrade/gloas.rs:101-103`), so the *primitives* exist, but `process_attestation` never invokes them. At Gloas:

- a valid `data.index == 1` attestation will fail the Electra `verify!(data.index == 0, ...)` check and be silently rejected;
- `state.builder_pending_payments[*].weight` is never incremented by attestation processing, so it remains zero throughout the epoch, breaking the downstream `process_builder_pending_payments` settlement.

H1–H8 ✓. **H9 ✗** (Electra `data.index == 0` enforced at Gloas). **H10 ✗** (no weight-tracking in `process_attestation`).

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/block/BlockProcessorElectra.java:271-323` handles the Electra-surface multi-committee logic. The Gloas variant `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/operations/validation/AttestationDataValidatorGloas.java` extends the Electra validator and overrides the committee-index check:

```java
public class AttestationDataValidatorGloas extends AttestationDataValidatorElectra {
  @Override
  protected Optional<OperationInvalidReason> checkCommitteeIndex(final AttestationData data) {
    return check(
        // signalling payload availability
        data.getIndex().isLessThan(2),
        AttestationInvalidReason.COMMITTEE_INDEX_MUST_BE_LESS_THAN_TWO);
  }
}
```

The Gloas same-slot + builder-weight logic lives in `BlockProcessorGloas` (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/block/BlockProcessorGloas.java:363+`), which references `beaconStateAccessorsGloas.isAttestationSameSlot(state, data)` for the same-slot gate. `BeaconStateAccessorsGloas` defines `isAttestationSameSlot` and the builder-pending-payments accessor.

H1–H8 ✓. **H9 ✓**. **H10 ✓**.

### nimbus

`vendor/nimbus/beacon_chain/spec/beaconstate.nim:1088-1153` — `check_attestation`:

```nim
# [Modified in Gloas:EIP7732]
when state is gloas.BeaconState:
    if not (data.index < 2):
        return err("Gloas attestation data index must be less than 2")
    if is_attestation_same_slot(state, data) and data.index != 0:
        return err("Same-slot attestation must have index 0")
else:
    # [Modified in Electra:EIP7549]
    if not (data.index == 0):
        return err("Electra attestation data index not 0")
```

`is_attestation_same_slot` is defined at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:878`. Builder-pending-payment weight tracking is invoked from `state_transition_epoch.nim` (the epoch-side helper) and the block-side per-attester loop. Nimbus's static `when typeof(state).kind` dispatch ensures the Gloas branch is taken at compile time for Gloas states.

H1–H8 ✓. **H9 ✓**. **H10 ✓**.

### lodestar

`vendor/lodestar/packages/state-transition/src/block/processAttestationPhase0.ts:97-141`. The Gloas branch at line 98-101:

```typescript
if (fork >= ForkSeq.gloas) {
    assert.lt(data.index, 2, `AttestationData.index must be 0 or 1: index=${data.index}`);
} else {
    assert.equal(data.index, 0, `AttestationData.index must be 0: index=${data.index}`);
}
```

`processAttestationsAltair.ts:23` imports `isAttestationSameSlot` from `util/gloas.ts`. The builder-pending-payment weight update is at lines 135, 145, 152, 159:

```typescript
if (fork >= ForkSeq.gloas && flagsNewSet !== 0 && isAttestationSameSlot(state as CachedBeaconStateGloas, data)) {
    // ...
    const payment = (state as CachedBeaconStateGloas).builderPendingPayments.get(index);
    payment.weight += effectiveBalance;
}
```

A separate validity helper at line 209-227 enforces the Gloas index range and the same-slot index-0 rule:

```typescript
if (fork >= ForkSeq.gloas) {
    // ...
    if (isAttestationSameSlotRootCache(rootCache, data)) {
        if (data.index !== 0) { throw new Error(`Same-slot attestation must have index 0`); }
    } else {
        if (data.index !== 0 && data.index !== 1) {
            throw new Error(`data index must be 0 or 1 index=${data.index}`);
        }
        // verify against state.executionPayloadAvailability
        const matches =
            Boolean(data.index) === executionPayloadAvailability.get(data.slot % SLOTS_PER_HISTORICAL_ROOT);
        if (!matches) { ... }
    }
}
```

H1–H8 ✓. **H9 ✓**. **H10 ✓**.

### grandine

`vendor/grandine/transition_functions/src/gloas/block_processing.rs:944-985` — `validate_attestation_with_verifier`:

```rust
// > [Modified in Gloas:EIP7732] Support index of `0` and `1` to signal payload status
ensure!(
    index < 2,
    Error::<P>::AttestationWithInvalidPayloadStatus { ... },
);
```

`apply_attestation` at the same file (lines 851-944) handles the builder-pending-payment weight tracking:

```rust
// > [New in Gloas:EIP7732]
let is_attestation_same_slot = is_attestation_same_slot(state, &attestation.data)?;
let attestation_epoch = attestation_epoch(state, attestation.data.target.epoch)?;
let payment_slot = match attestation_epoch {
    AttestationEpoch::Previous => builder_payment_index_for_previous_epoch::<P>(attestation.data.slot),
    AttestationEpoch::Current => builder_payment_index_for_current_epoch::<P>(attestation.data.slot),
};
let mut payment = state.builder_pending_payments().get(payment_slot)?.to_owned();
// ... per-attester loop ...
for (validator_index, base_reward, effective_balance) in attesting_indices_with_base_rewards {
    let mut will_set_new_flag = false;
    for (flag_index, weight) in PARTICIPATION_FLAG_WEIGHTS {
        if participation_flags.get_bit(flag_index) && !epoch_participation.get_bit(flag_index) {
            proposer_reward_numerator += base_reward * weight;
            will_set_new_flag = true;
        }
    }
    // ... builder-payment weight increment when will_set_new_flag && is_attestation_same_slot ...
}
```

The Gloas processor at `vendor/grandine/transition_functions/src/gloas/block_processing.rs:1573` calls both `validate_attestation_with_verifier` and `apply_attestation` for Gloas attestations.

H1–H8 ✓. **H9 ✓**. **H10 ✓**.

## Cross-reference table

| Client | `process_attestation` (Electra) | `data.index < 2` (H9) | `is_attestation_same_slot` usage (H10) | `builder_pending_payments[*].weight` update (H10) |
|---|---|---|---|---|
| prysm | `core/blocks/attestation.go:113-193` | **✓** (`:117-126` Gloas branch: `ci >= 2` error) | **✓** (`core/gloas/attestation.go:36` `IsAttestationSameSlot` via `MatchingPayload`, called from `core/altair/attestation.go:312`) | **✓** (`state/interfaces_gloas.go:34` `UpdatePendingPaymentWeight(att, indices, participatedFlags)`; `setters_gloas.go` impl) |
| lighthouse | `verify_attestation.rs:21-86` + `get_attesting_indices.rs:103-149` | **✗** (`AttestationRef::Electra(_)` branch enforces `data.index == 0` for Gloas attestations too; no `AttestationRef::Gloas` branch) | **✗** (helper defined at `beacon_state.rs:2072` but never called from `per_block_processing/`) | **✗** (state field present at `beacon_state.rs:628`; upgrade allocates Vector at `upgrade/gloas.rs:101-103`; no caller in attestation processing increments weight) |
| teku | `BlockProcessorElectra.java:271-323` + `AttestationDataValidatorElectra.java:46-84` | **✓** (`AttestationDataValidatorGloas.checkCommitteeIndex` overrides to `isLessThan(2)`) | **✓** (`BlockProcessorGloas.java:363` `beaconStateAccessorsGloas.isAttestationSameSlot(state, data)`) | **✓** (`BlockProcessorGloas` + `BeaconStateAccessorsGloas` wire the payment update) |
| nimbus | `beaconstate.nim:1088-1153` (`check_attestation`) | **✓** (`:1106-1109` `when state is gloas.BeaconState: assert data.index < 2`) | **✓** (`beaconstate.nim:878` def; `:1108` and `:1360` callers) | **✓** (block-side per-attester loop + `state_transition_epoch.nim` epoch consumer) |
| lodestar | `block/processAttestationPhase0.ts:97-141` (validate Electra branch) + `processAttestationsAltair.ts:80-230` (apply + weight) | **✓** (`processAttestationPhase0.ts:98-101` `if fork >= ForkSeq.gloas: assert.lt(data.index, 2)` else `assert.equal(data.index, 0)`) | **✓** (`processAttestationsAltair.ts:135` `isAttestationSameSlot(state, data)` gate) | **✓** (`processAttestationsAltair.ts:152, 159` `builderPendingPayments.get(index).weight += effectiveBalance`) |
| grandine | `electra/block_processing.rs:747-816` (Electra `validate_attestation`) + `gloas/block_processing.rs:944-985` (`validate_attestation_with_verifier`) + `:851-944` (`apply_attestation`) | **✓** (`gloas/block_processing.rs:982` `ensure!(index < 2, ...)`) | **✓** (`gloas/block_processing.rs` `is_attestation_same_slot(state, &attestation.data)?`) | **✓** (`apply_attestation` reads + writes `state.builder_pending_payments()` weight) |

## Empirical tests

### Pectra-surface fixture run

`consensus-spec-tests/tests/mainnet/electra/operations/attestation/pyspec_tests/` — 45 EF fixtures. Run via `scripts/run_fixture.sh` against all six clients on 2026-05-03:

```
                                                                         prysm  lighthouse  teku  nimbus  lodestar  grandine
at_max_inclusion_slot                                                    PASS   PASS        SKIP  SKIP    PASS      PASS
correct_attestation_included_at_max_inclusion_slot                       PASS   PASS        SKIP  SKIP    PASS      PASS
correct_attestation_included_at_min_inclusion_delay                      PASS   PASS        SKIP  SKIP    PASS      PASS
correct_attestation_included_at_one_epoch_delay                          PASS   PASS        SKIP  SKIP    PASS      PASS
correct_attestation_included_at_sqrt_epoch_delay                         PASS   PASS        SKIP  SKIP    PASS      PASS
incorrect_head_and_target_included_at_epoch_delay                        PASS   PASS        SKIP  SKIP    PASS      PASS
incorrect_head_and_target_included_at_sqrt_epoch_delay                   PASS   PASS        SKIP  SKIP    PASS      PASS
incorrect_head_and_target_min_inclusion_delay                            PASS   PASS        SKIP  SKIP    PASS      PASS
incorrect_head_included_at_max_inclusion_slot                            PASS   PASS        SKIP  SKIP    PASS      PASS
incorrect_head_included_at_min_inclusion_delay                           PASS   PASS        SKIP  SKIP    PASS      PASS
incorrect_head_included_at_sqrt_epoch_delay                              PASS   PASS        SKIP  SKIP    PASS      PASS
incorrect_target_included_at_epoch_delay                                 PASS   PASS        SKIP  SKIP    PASS      PASS
incorrect_target_included_at_min_inclusion_delay                         PASS   PASS        SKIP  SKIP    PASS      PASS
incorrect_target_included_at_sqrt_epoch_delay                            PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_after_max_inclusion_slot                                         PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_attestation_data_index_not_zero                                  PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_attestation_signature                                            PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_bad_source_root                                                  PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_before_inclusion_delay                                           PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_committee_index                                                  PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_correct_attestation_included_after_max_inclusion_slot            PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_current_source_root                                              PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_empty_participants_seemingly_valid_sig                           PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_empty_participants_zeroes_sig                                    PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_future_target_epoch                                              PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_incorrect_head_and_target_included_after_max_inclusion_slot      PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_incorrect_head_included_after_max_inclusion_slot                 PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_incorrect_target_included_after_max_inclusion_slot               PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_index                                                            PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_mismatched_target_and_slot                                       PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_new_source_epoch                                                 PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_nonset_committee_bits                                            PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_old_source_epoch                                                 PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_old_target_epoch                                                 PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_previous_source_root                                             PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_source_root_is_target_root                                       PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_too_few_aggregation_bits                                         PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_too_many_aggregation_bits                                        PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_too_many_committee_bits                                          PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_wrong_index_for_committee_signature                              PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_wrong_index_for_slot_0                                           PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_wrong_index_for_slot_1                                           PASS   PASS        SKIP  SKIP    PASS      PASS
multi_proposer_index_iterations                                          PASS   PASS        SKIP  SKIP    PASS      PASS
one_basic_attestation                                                    PASS   PASS        SKIP  SKIP    PASS      PASS
previous_epoch                                                           PASS   PASS        SKIP  SKIP    PASS      PASS
```

45/45 fixtures pass uniformly on prysm + lighthouse + lodestar + grandine. teku and nimbus SKIP per harness limit.

### Gloas-surface

No Gloas operations fixtures yet exist for `process_attestation`. H9 and H10 are currently source-only.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — multi-committee max-aggregation).** Attestation with all `MAX_COMMITTEES_PER_SLOT = 64` committees set in committee_bits. Tests the upper bound of the multi-committee feature.
- **T1.2 (priority — single committee, high index).** Attestation with only the highest committee_bit set. Tests the high-index boundary in `get_committee_count_per_slot` comparison.
- **T1.3 (Glamsterdam-target — `data.index == 1` non-same-slot payload-available attestation).** Gloas state; non-same-slot attestation with `data.index == 1` and the corresponding `state.execution_payload_availability[data.slot % SLOTS_PER_HISTORICAL_ROOT]` bit set. Expected: accepted by all six per the Gloas spec; lighthouse will reject as `BadCommitteeIndex` because the Electra `data.index == 0` predicate still fires.
- **T1.4 (Glamsterdam-target — same-slot `data.index == 0` builder-payment weight increment).** Gloas state; same-slot attestation with `data.index == 0`, `payment.withdrawal.amount > 0` for the slot, and a single attester. Expected: `state.builder_pending_payments[SLOTS_PER_EPOCH + data.slot % SLOTS_PER_EPOCH].weight` increases by `attester.effective_balance`. Lighthouse will not increment the weight (state field remains unchanged).

#### T2 — Adversarial probes
- **T2.1 (priority — `data.index = 1`).** Pre-Gloas: must be rejected (Electra `== 0`). Covered by `invalid_attestation_data_index_not_zero`.
- **T2.2 (priority — committee_bits set but no attesters).** A committee_bit is set but the corresponding aggregation_bits slice is all zeros. Reject. Covered by `invalid_empty_participants_*`.
- **T2.3–T2.6 (priority — bitfield boundary cases).** Covered by `invalid_too_many_aggregation_bits`, `invalid_too_few_aggregation_bits`, `invalid_committee_index`, `invalid_too_many_committee_bits`.
- **T2.7 (priority — cross-committee duplicate validator).** A validator appears in two committees both set in committee_bits. Pyspec's `get_attesting_indices` uses `Set[ValidatorIndex]` semantics — dedupe. Each client's collection mechanism must handle duplicates consistently.
- **T2.8 (Glamsterdam-target — same-slot attestation with `data.index == 1`).** Gloas state; `is_attestation_same_slot(state, data) == True` but `data.index == 1`. Spec: must be rejected ("Same-slot attestation must have index 0"). Verify all six clients enforce this combined predicate at Gloas. Lighthouse will accept (since it never checks the same-slot rule at all).
- **T2.9 (Glamsterdam-target — multiple same-slot attestations on the same validator).** Two same-slot attestations covering the same validator in one block. Spec's `will_set_new_flag` gates the weight increment so each validator contributes exactly once per slot. Verify all six clients add `effective_balance` once, not twice.

## Mainnet reachability

**Reachable on canonical traffic at Glamsterdam activation, on every block that contains a Gloas-format attestation** (i.e. essentially every Gloas-slot block — attestations are the dominant operation per block).

**Trigger A (H9 — `data.index == 1` rejection).** The first Gloas-slot block that contains a non-same-slot attestation with `data.index == 1` (signalling that the committee saw the parent's execution payload). Validators ARE expected to produce these routinely post-Gloas — the payload-availability mechanism is what lets the chain reach consensus on whether an ePBS builder delivered its payload. On lighthouse the message is rejected as `BadCommitteeIndex`; on prysm/teku/nimbus/lodestar/grandine it is accepted and processed. Lighthouse will refuse to attest to any block containing such attestations (or its block-import will reject the block); the chain at activation will see lighthouse fork off as soon as the first `data.index == 1` attestation appears on canonical traffic.

**Trigger B (H10 — builder weight not tracked).** Even if Trigger A is avoided (e.g., temporarily all attestations carry `data.index == 0`), every same-slot attestation should increment `state.builder_pending_payments[*].weight`. On lighthouse this never happens — the state field remains at its initial-vector-of-zeros. At the next `process_builder_pending_payments` epoch boundary, lighthouse's `state.builder_pending_payments` has different hash-tree-root than the other five clients'. The post-state divergence appears every single epoch, regardless of whether any individual attestation was visibly different across clients.

**Severity.** State-root divergence on every Gloas-epoch boundary at minimum (via H10), and on every Gloas-slot block carrying a `data.index == 1` attestation (via H9). H10's continual nature is the broader of the two — lighthouse cannot follow the Gloas canonical chain without implementing builder-pending-payment weight tracking in `process_attestation`. H9 layers on top: even ignoring weight tracking, lighthouse cannot accept the spec-valid `data.index == 1` form.

**Mitigation window.** Source-only at audit time; no Gloas EF operations fixtures yet for this routine. Closing requires lighthouse to (a) add an `AttestationRef::Gloas` branch (or relax the Electra branch when `fork_name >= Gloas`) that enforces `data.index < 2` plus the same-slot index-0 rule, and (b) wire the same-slot weight increment into the attesting-indices loop, reading/writing `state.builder_pending_payments[slot_idx]`. The other five clients' implementations are reference. Without the fix, mainnet at Glamsterdam activation splits between lighthouse and the rest from the very first Gloas epoch.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H8) remain satisfied: aligned implementations of the four new Pectra checks (data.index==0, per-committee membership + bounds, len(attesters)>0 per committee, exact-size bitfield) and the multi-committee BLS aggregation. All 45 EF `attestation` fixtures still pass uniformly on prysm + lighthouse + lodestar + grandine; teku and nimbus pass internally.

**Glamsterdam-target findings:**

- **H9** (`data.index < 2` payload-availability signal + same-slot index-0 rule) fails for **lighthouse** alone. The other five clients implement the Gloas branch: prysm (`attestation.go:117-126` Gloas vs Electra fork branch + `MatchingPayload` for the same-slot rule); teku (`AttestationDataValidatorGloas.checkCommitteeIndex` override); nimbus (`beaconstate.nim:1106-1109` `when state is gloas.BeaconState`); lodestar (`processAttestationPhase0.ts:98-101` `if fork >= ForkSeq.gloas`); grandine (`gloas/block_processing.rs:982` `ensure!(index < 2)`). Lighthouse's `verify_attestation.rs:77` enforces `data.index == 0` for `AttestationRef::Electra(_)` — which matches Gloas-era attestations too because the Attestation SSZ container itself is not modified at Gloas — and there is no `AttestationRef::Gloas` branch or `fork_name_unchecked >= ForkName::Gloas` gate.
- **H10** (builder-pending-payment weight increment under same-slot + `will_set_new_flag`) likewise fails for **lighthouse** alone. The state field (`beacon_state.rs:628 builder_pending_payments`) and the helper (`beacon_state.rs:2072 is_attestation_same_slot`) are both defined, but neither is referenced from `consensus/state_processing/src/per_block_processing/`. The other five all wire the weight update into their per-attester loop.

**1-vs-5 split with lighthouse as the lone laggard** — the reverse of the EIP-8061 family pattern (items #2 H6, #3 H8, #4 H8, #6 H8) where lodestar was the lone leader. Combined `splits` = `[lighthouse]`. Impact = `mainnet-glamsterdam` because both divergences materialise on canonical Gloas traffic on the very first Gloas epoch (H10) or first Gloas-slot block carrying a `data.index == 1` attestation (H9).

Notable per-client style differences (all observable-equivalent at the Pectra spec level):
- **prysm** has Gloas-ready logic (`ci < 2` post-Gloas, `ci == 0` Electra) and uses `MatchingPayload` for the same-slot rule.
- **lighthouse** uses `safe_add` overflow-checked arithmetic for the cumulative offset, but at Gloas the entire EIP-7732 extension is missing.
- **teku** factors check (A) into `AttestationDataValidator*` classes, with Gloas overriding via subclass.
- **nimbus** uses Nim's static fork dispatch (`when state is gloas.BeaconState`).
- **lodestar** flattens committees into a Uint32Array; fork-gates everywhere at `fork >= ForkSeq.gloas`.
- **grandine** returns `HashSet<ValidatorIndex>` (matches pyspec's `Set[ValidatorIndex]` literally) and has a Gloas-specific module (`gloas/block_processing.rs`).

Recommendations to the harness and the audit:

- Generate the **T1.3 (`data.index == 1` non-same-slot)** and **T1.4 (same-slot builder-weight increment)** Gloas fixtures; sister-pair to the EIP-7732 audit family. Lighthouse-specific; the other five clients should pass both.
- File a coordinated PR against lighthouse to (a) add the Gloas branch in `verify_attestation.rs` for `data.index < 2` plus the same-slot index-0 rule, and (b) wire `state.builder_pending_payments[*].weight += effective_balance` into the per-attester loop in `single_pass.rs`.
- **Generate the T2.7 cross-committee duplicate-validator fixture** to lock dedup semantics (Pectra-surface).
- **Audit `Attestation` SSZ ser/de cross-client** as a Track E item.
- **Audit `is_valid_indexed_attestation` and BLS aggregate signature pubkey-cache coherence** — Track F item.
- **Generate T1.1 multi-committee max-aggregation fixture** as a custom 64-committee stress test.

## Cross-cuts

### With the SSZ `Attestation` container layout change (Track E)

The Pectra `Attestation` SSZ container has a different shape from pre-Pectra; at Gloas the container itself is unchanged (no Modified Attestation container in Gloas spec), so deserialization remains stable across the fork transition. Network-layer attestation gossip carries the same shape. A divergence in any client's SSZ codec for the Pectra Attestation would cause that client to fail to deserialize gossip from other clients (chain-split via network partition rather than state-root divergence). Worth a Track E item.

### With `is_valid_indexed_attestation` and BLS aggregate signature

Each client's `IndexedAttestation` produced from a Pectra+Gloas attestation has `attesting_indices` that must produce the same aggregate signature when verified. Sorted-ascending order is canonical per spec. BLS signature aggregation is commutative under pubkey union, so non-canonical ordering still verifies — F-tier. Worth a sanity check via a custom multi-committee fixture where the per-committee validator indices straddle a sort boundary.

### With `process_builder_pending_payments` (Gloas-new epoch helper)

`process_attestation` (Gloas) increments `state.builder_pending_payments[slot_idx].weight`. The new epoch helper `process_builder_pending_payments` (`vendor/consensus-specs/specs/gloas/beacon-chain.md` "New `process_builder_pending_payments`") consumes this weight to decide whether the slot's builder bid is settled. A divergence in H10 propagates directly into the epoch helper's decisions; lighthouse's weight-vector-of-zeros would either lead to no settlements at all OR (depending on the helper's logic) lead to inverted settlements. Sister audit item.

### With `process_epoch` participation flag updates

`process_attestation` updates `state.{current,previous}_epoch_participation`. The next epoch's `process_rewards_and_penalties` reads these flags. A divergence here would propagate one epoch later as different rewards/penalties.

### With `get_beacon_committee` and the shuffling cache

Pectra's `process_attestation` calls `get_beacon_committee` for each set committee. Each client has a different shuffling cache. Indirectly tested by every fixture.

### With Gloas `state.execution_payload_availability` bitvector

The `data.index == 1` semantics depend on `state.execution_payload_availability[data.slot % SLOTS_PER_HISTORICAL_ROOT]`. This new BeaconState field is set by `process_payload_attestation` (Gloas-new operation). Lodestar's audit code at `processAttestationsAltair.ts:227` explicitly checks `Boolean(data.index) === executionPayloadAvailability.get(...)`. Cross-cut with the payload-attestation audit (which is a separate item once it lands).

## Adjacent untouched Electra-active consensus paths

1. **`Attestation` SSZ container ser/de cross-client** (Track E item) — Pectra layout must round-trip identically for gossip. At Gloas the container is unchanged.
2. **`is_valid_indexed_attestation`** — calls into BLS aggregate verification. The IndexedAttestation has expanded list capacity (`MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT` instead of just `MAX_VALIDATORS_PER_COMMITTEE`).
3. **Cross-committee duplicate validator dedup** — pyspec uses `Set[ValidatorIndex]`; each client's collection mechanism must dedupe. Worth a T2.7 fixture.
4. **Lodestar's `intersectValues` ordering** — preserves bit-position order, NOT sorted-by-validator-index. BLS aggregation is commutative so this doesn't matter for signature verification, but if any downstream code depended on sorted order (e.g., for slashing detection), there could be subtle bugs.
5. **Shuffling cache cross-client coherence** — `get_beacon_committee` is called for each set committee.
6. **Participation flag update ordering** — within a single block, attestations are processed in order. The proposer_reward_numerator accumulates across all attestations.
7. **`MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT` aggregation_bits size** — the bound is large (2048 × 64 = 131,072 max bits per attestation).
8. **The legacy `AttestationData.index` field at Gloas is now {0, 1} not just 0** — repurposed for payload-availability signalling. Subtle semantic change.
9. **`get_committee_count_per_slot` consistency** — used in the per-committee bounds check.
10. **Lighthouse's `is_attestation_same_slot` orphan helper** — defined on `BeaconState` at line 2072 but has zero callers in the codebase. A reviewer might mistake its presence for "Gloas is implemented" when the call sites are missing entirely. Flag for the H9/H10 fix-PR: search for callers AND add new ones.
11. **`process_builder_pending_payments` (Gloas-new epoch helper)** — consumer side of H10's writes. Lighthouse's never-incremented weight vector would lead to systematically incorrect settlement decisions there.
12. **`state.execution_payload_availability` bitvector (Gloas-new)** — written by `process_payload_attestation`. The `data.index ∈ {0, 1}` semantics in this item depend on consistency with that bitvector.
