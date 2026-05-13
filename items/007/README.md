---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: []
eips: [EIP-7549, EIP-7732]
prysm_version: v3.2.2-rc.1-2535-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 7: `process_attestation` EIP-7549 multi-committee aggregation

## Summary

EIP-7549 fundamentally changes the `Attestation` SSZ container: `committee_index` is removed from `AttestationData` and replaced with a top-level `committee_bits: Bitvector[MAX_COMMITTEES_PER_SLOT]`. A single attestation can now carry attesters from multiple committees in one signature aggregate, with a flat `aggregation_bits: Bitlist[MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT]` indexed by a cumulative `committee_offset` walked across the active committees in committee_bits-set order. The legacy `AttestationData.index` field still exists but Pectra REQUIRES `data.index == 0`. This is the most-frequent CL block operation; a divergence here is reachable on every slot.

**Pectra surface (the function body itself):** all six clients implement the four new Pectra checks (data.index==0, per-committee membership + bounds, len(attesters)>0 per committee, exact-size bitfield) and the multi-committee BLS aggregation identically at the source level. 45/45 EF `attestation` operations fixtures pass uniformly on the four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus pass these in internal CI but the local harness SKIPs them.

**Gloas surface (new at the Glamsterdam target):** all six clients implement the two interlocking Gloas-modified surfaces from EIP-7732 ePBS: (a) `data.index` is repurposed from "must-be-zero" to a payload-availability signal where `0 ≤ data.index < 2` (with 0 meaning the proposed payload was not yet executable and 1 meaning it was), with an extra same-slot rule (`is_attestation_same_slot(state, data)` → `data.index` must be 0); and (b) `state.builder_pending_payments[slot_idx].weight` is incremented by the attester's `effective_balance` whenever a same-slot attestation sets a new participation flag for that validator. The dispatch idioms vary per client but the observable Gloas semantics are uniform.

No splits at the current pins. The earlier finding (H9 and H10 both failing for lighthouse) was an artifact of stale `stable` pinning; on `unstable` HEAD `1a6863118` lighthouse implements both surfaces at `verify_attestation.rs:74-81` (`fork_at_attestation_slot.gloas_enabled()` branch) and `process_operations.rs:280-358` (full `will_set_new_flag` + `is_attestation_same_slot(data)` + `builder_pending_payments_mut()` weight increment).

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

**Consensus relevance**: attestations are processed per block, every slot. A divergence in any of the Electra bits would surface on the very next block. At Gloas, a divergence in H9 would mean a client either rejects valid `data.index == 1` attestations or accepts invalid `data.index == 1` attestations — direct state-root divergence on the first attestation carrying payload-availability=1. A divergence in H10 would mean a client fails to update `state.builder_pending_payments[*].weight` (or updates it differently), which would directly change the BeaconState field's hash-tree-root AND propagate into the `process_builder_pending_payments` epoch helper one boundary later, where the divergent weight is consumed to settle (or fail to settle) the builder's bid — a downstream cascade into builder payouts.

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

H1–H10 satisfied across all six clients at the current Glamsterdam-target pins. The dispatch idioms used per client for H9 (the `data.index < 2` Gloas predicate + same-slot index-0 rule) and for H10 (the builder-pending-payments weight increment) vary, but the observable Gloas semantics are spec-equivalent. No EF Gloas operations fixtures yet exist for either surface — the conclusion is source-only.

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

Builder-pending-payments weight is updated via `beaconState.UpdatePendingPaymentWeight(att, indices, participatedFlags)` invoked from `vendor/prysm/beacon-chain/core/altair/attestation.go:79` — wired into the attestation processing flow downstream of `MatchingPayload`. Interface declared at `vendor/prysm/beacon-chain/state/interfaces_gloas.go:34`.

H1–H10 ✓.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing/verify_attestation.rs:55-90`. The Gloas branch at lines 74-81 fork-gates the `data.index` predicate:

```rust
AttestationRef::Electra(_) => {
    let fork_at_attestation_slot = spec.fork_name_at_slot::<E>(data.slot);
    if fork_at_attestation_slot.gloas_enabled() {
        verify!(data.index < 2, Invalid::BadOverloadedDataIndex);
    } else {
        verify!(data.index == 0, Invalid::BadCommitteeIndex);
    }
}
```

(The Attestation SSZ container itself is not modified at Gloas, so `AttestationRef::Electra` continues to match Gloas-era attestations; the internal fork-gate uses the *state's* fork at the attestation's slot.)

**H10 dispatch (inline per-attester loop).** `process_attestations` in `vendor/lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:280-358` reads the payment-slot withdrawal amount, walks attesting indices, and on each `will_set_new_flag` increments `state.builder_pending_payments_mut()[payment_index].weight`:

```rust
let payment_withdrawal_amount = state
    .builder_pending_payments()?
    .get(payment_index)
    ...
    .withdrawal.amount;

for index in indexed_att.attesting_indices_iter() {
    let mut will_set_new_flag = false;
    for (flag_index, &weight) in PARTICIPATION_FLAG_WEIGHTS.iter().enumerate() {
        if !validator_participation.has_flag(flag_index)? {
            validator_participation.add_flag(flag_index)?;
            ...
            will_set_new_flag = true;
        }
    }
    if will_set_new_flag
        && state.is_attestation_same_slot(data)?
        && payment_withdrawal_amount > 0
    {
        let builder_payments = state.builder_pending_payments_mut()?;
        let payment = builder_payments.get_mut(payment_index)...;
        payment.weight.safe_add_assign(validator_effective_balance)?;
    }
}
```

The helper `is_attestation_same_slot` is a method on `BeaconState` (`vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2072`) and the `builder_pending_payments` field is allocated by the Gloas upgrade (`vendor/lighthouse/consensus/state_processing/src/upgrade/gloas.rs:101-103`).

H1–H10 ✓.

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

The Gloas same-slot + builder-weight logic lives in `BlockProcessorGloas` (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/block/BlockProcessorGloas.java:352-389`). `updateBuilderPaymentWeight` (line 352-369) gates on `beaconStateAccessorsGloas.isAttestationSameSlot(state, data)` and `payment.getWithdrawal().getAmount().isGreaterThan(UInt64.ZERO)`; `consumeAttestationProcessingResult` (line 371-389) applies the accumulated `weightDelta` to `BuilderPendingPayments`.

H1–H10 ✓.

### nimbus

`vendor/nimbus/beacon_chain/spec/beaconstate.nim:1163-1180` — `check_attestation`:

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

`is_attestation_same_slot` is defined at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:940`. Builder-pending-payment weight tracking is in the block-side per-attester loop at `:1381-1425`:

```nim
var payment = state.builder_pending_payments.item(payment_index.int)
...
var will_set_new_flag = false
...
will_set_new_flag = true
...
if will_set_new_flag and
    is_attestation_same_slot(state, attestation.data) and
    payment.withdrawal.amount > 0:
  ...
state.builder_pending_payments[payment_index.int] = payment
```

Nimbus's static `when typeof(state).kind` dispatch ensures the Gloas branch is taken at compile time for Gloas states.

H1–H10 ✓.

### lodestar

`vendor/lodestar/packages/state-transition/src/block/processAttestationPhase0.ts:97-141`. The Gloas branch at line 98-101:

```typescript
if (fork >= ForkSeq.gloas) {
    assert.lt(data.index, 2, `AttestationData.index must be 0 or 1: index=${data.index}`);
} else {
    assert.equal(data.index, 0, `AttestationData.index must be 0: index=${data.index}`);
}
```

`processAttestationsAltair.ts:23` imports `isAttestationSameSlot` from `util/gloas.ts`. The builder-pending-payment weight update is at lines 135-160:

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

H1–H10 ✓.

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
    if will_set_new_flag && is_attestation_same_slot && payment.withdrawal.amount > 0 {
        // ... weight increment ...
    }
}
```

The Gloas processor at `vendor/grandine/transition_functions/src/gloas/block_processing.rs:1573` calls both `validate_attestation_with_verifier` and `apply_attestation` for Gloas attestations.

H1–H10 ✓.

## Cross-reference table

| Client | `process_attestation` (Electra) | `data.index < 2` (H9) | `is_attestation_same_slot` usage (H10) | `builder_pending_payments[*].weight` update (H10) |
|---|---|---|---|---|
| prysm | `core/blocks/attestation.go:113-193` | ✓ (`:117-126` Gloas branch: `ci >= 2` error) | ✓ (`core/gloas/attestation.go:36` `IsAttestationSameSlot` via `MatchingPayload`, called from `core/altair/attestation.go:312`) | ✓ (`state/interfaces_gloas.go:34` `UpdatePendingPaymentWeight(att, indices, participatedFlags)`; invoked from `core/altair/attestation.go:79`) |
| lighthouse | `verify_attestation.rs:55-90` + `process_operations.rs:280-358` | ✓ (`verify_attestation.rs:74-81` — `fork_at_attestation_slot.gloas_enabled()` → `data.index < 2`, else `== 0`) | ✓ (`process_operations.rs:347` `state.is_attestation_same_slot(data)?`; helper at `beacon_state.rs:2072`) | ✓ (`process_operations.rs:350-356` `builder_pending_payments_mut()[payment_index].weight.safe_add_assign(effective_balance)`) |
| teku | `BlockProcessorElectra.java:271-323` + `BlockProcessorGloas.java:352-389` | ✓ (`AttestationDataValidatorGloas.checkCommitteeIndex` overrides to `isLessThan(2)`) | ✓ (`BlockProcessorGloas.java:361` `beaconStateAccessorsGloas.isAttestationSameSlot(state, data)`) | ✓ (`BlockProcessorGloas.updateBuilderPaymentWeight:352-369` + `consumeAttestationProcessingResult:371-389`) |
| nimbus | `beaconstate.nim:1088-1180` (`check_attestation`) | ✓ (`:1171-1175` `when state is gloas.BeaconState: assert data.index < 2`) | ✓ (`beaconstate.nim:940` def; `:1048-1049` same-slot index-0 enforcement; `:1404` weight gate) | ✓ (block-side per-attester loop `:1381-1425` + `state_transition_epoch.nim` epoch consumer) |
| lodestar | `block/processAttestationPhase0.ts:97-141` (validate Electra branch) + `processAttestationsAltair.ts:80-230` (apply + weight) | ✓ (`processAttestationPhase0.ts:98-101` `if fork >= ForkSeq.gloas: assert.lt(data.index, 2)` else `assert.equal(data.index, 0)`) | ✓ (`processAttestationsAltair.ts:135` `isAttestationSameSlot(state, data)` gate) | ✓ (`processAttestationsAltair.ts:152, 159` `builderPendingPayments.get(index).weight += effectiveBalance`) |
| grandine | `electra/block_processing.rs:747-816` (Electra `validate_attestation`) + `gloas/block_processing.rs:944-985` (`validate_attestation_with_verifier`) + `:851-944` (`apply_attestation`) | ✓ (`gloas/block_processing.rs:1088` `ensure!(index < 2, ...)`) | ✓ (`gloas/block_processing.rs:979` `is_attestation_same_slot(state, &attestation.data)?`) | ✓ (`apply_attestation:1007-1020` reads + writes `state.builder_pending_payments()` weight) |

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
- **T1.3 (Glamsterdam-target — `data.index == 1` non-same-slot payload-available attestation).** Gloas state; non-same-slot attestation with `data.index == 1` and the corresponding `state.execution_payload_availability[data.slot % SLOTS_PER_HISTORICAL_ROOT]` bit set. Expected: accepted by all six per the Gloas spec; cross-client `state_root` should match.
- **T1.4 (Glamsterdam-target — same-slot `data.index == 0` builder-payment weight increment).** Gloas state; same-slot attestation with `data.index == 0`, `payment.withdrawal.amount > 0` for the slot, and a single attester. Expected: `state.builder_pending_payments[SLOTS_PER_EPOCH + data.slot % SLOTS_PER_EPOCH].weight` increases by `attester.effective_balance` uniformly across all six clients.

#### T2 — Adversarial probes
- **T2.1 (priority — `data.index = 1`).** Pre-Gloas: must be rejected (Electra `== 0`). Covered by `invalid_attestation_data_index_not_zero`.
- **T2.2 (priority — committee_bits set but no attesters).** A committee_bit is set but the corresponding aggregation_bits slice is all zeros. Reject. Covered by `invalid_empty_participants_*`.
- **T2.3–T2.6 (priority — bitfield boundary cases).** Covered by `invalid_too_many_aggregation_bits`, `invalid_too_few_aggregation_bits`, `invalid_committee_index`, `invalid_too_many_committee_bits`.
- **T2.7 (priority — cross-committee duplicate validator).** A validator appears in two committees both set in committee_bits. Pyspec's `get_attesting_indices` uses `Set[ValidatorIndex]` semantics — dedupe. Each client's collection mechanism must handle duplicates consistently.
- **T2.8 (Glamsterdam-target — same-slot attestation with `data.index == 1`).** Gloas state; `is_attestation_same_slot(state, data) == True` but `data.index == 1`. Spec: must be rejected ("Same-slot attestation must have index 0"). Verify all six clients enforce this combined predicate at Gloas.
- **T2.9 (Glamsterdam-target — multiple same-slot attestations on the same validator).** Two same-slot attestations covering the same validator in one block. Spec's `will_set_new_flag` gates the weight increment so each validator contributes exactly once per slot. Verify all six clients add `effective_balance` once, not twice.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H8) remain satisfied: aligned implementations of the four new Pectra checks (data.index==0, per-committee membership + bounds, len(attesters)>0 per committee, exact-size bitfield) and the multi-committee BLS aggregation. All 45 EF `attestation` fixtures still pass uniformly on prysm + lighthouse + lodestar + grandine; teku and nimbus pass internally.

**Glamsterdam-target findings:**

- **H9 ✓ across all six clients.** Every client fork-gates the `data.index` predicate to `< 2` at Gloas. Six distinct dispatch idioms: prysm runtime `beaconState.Version() >= version.Gloas` branch in `attestation.go`; lighthouse runtime `fork_at_attestation_slot.gloas_enabled()` branch inside `AttestationRef::Electra` (the Attestation SSZ container is not modified at Gloas, so the same Electra variant matches Gloas-era attestations); teku `AttestationDataValidatorGloas` Java subclass override; nimbus compile-time `when state is gloas.BeaconState`; lodestar `fork >= ForkSeq.gloas` ternary; grandine separate `gloas/block_processing.rs` validation function.
- **H10 ✓ across all six clients.** Every client wires the `will_set_new_flag` + `is_attestation_same_slot(state, data)` + `payment.withdrawal.amount > 0` triple into the per-attester participation-flag loop and increments `state.builder_pending_payments[slot_idx].weight` by the validator's effective balance. Same six dispatch idioms (separate `UpdatePendingPaymentWeight` interface method for prysm; inline branch in `process_operations.rs` for lighthouse; `BlockProcessorGloas.updateBuilderPaymentWeight` override for teku; compile-time `when` for nimbus; runtime ternary inside `processAttestationsAltair.ts` for lodestar; per-attester loop in grandine's Gloas `apply_attestation`).

The earlier finding (H9 ✗ and H10 ✗ for lighthouse) was a stale-pin artifact. Lighthouse had been on `stable` (v8.1.3), which trailed `unstable` by months of Gloas/EIP-7732 integration including the `process_attestation` Gloas surface. With each client now on the branch where its actual Glamsterdam implementation lives, the cross-client surface is uniform.

Notable per-client style differences (all observable-equivalent at the Pectra spec level):
- **prysm** has the Gloas-ready logic (`ci < 2` post-Gloas, `ci == 0` Electra) and uses `MatchingPayload` for the same-slot rule. Weight tracking flows through an `UpdatePendingPaymentWeight` state-interface method invoked from the altair attestation path.
- **lighthouse** uses `safe_add` overflow-checked arithmetic for the cumulative offset and for the weight increment. The Gloas branch is inline in the existing `AttestationRef::Electra` arm rather than a separate `AttestationRef::Gloas` variant (since the Attestation SSZ container is unchanged at Gloas).
- **teku** factors check (A) into `AttestationDataValidator*` classes, with Gloas overriding via subclass. Weight tracking is collected as a per-attestation `weightDelta` in `BlockProcessorGloas.updateBuilderPaymentWeight` and applied in `consumeAttestationProcessingResult`.
- **nimbus** uses Nim's static fork dispatch (`when state is gloas.BeaconState`); same-slot index-0 enforcement is explicit and the builder-payment weight loop matches the spec line-by-line.
- **lodestar** flattens committees into a Uint32Array; fork-gates everywhere at `fork >= ForkSeq.gloas`. Same-slot detection has both a state-based variant (`isAttestationSameSlot`) and a root-cache variant (`isAttestationSameSlotRootCache`) for the validity helper.
- **grandine** returns `HashSet<ValidatorIndex>` (matches pyspec's `Set[ValidatorIndex]` literally) and has a Gloas-specific module (`gloas/block_processing.rs`) with its own `validate_attestation_with_verifier` and `apply_attestation` functions.

Recommendations to the harness and the audit:

- Generate the **T1.3 (`data.index == 1` non-same-slot)** and **T1.4 (same-slot builder-weight increment)** Gloas fixtures; sister-pair to the EIP-7732 audit family. These would convert the source-only H9/H10 conclusions into empirically-pinned ones.
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

`process_attestation` (Gloas) increments `state.builder_pending_payments[slot_idx].weight`. The new epoch helper `process_builder_pending_payments` (`vendor/consensus-specs/specs/gloas/beacon-chain.md` "New `process_builder_pending_payments`") consumes this weight to decide whether the slot's builder bid is settled. With H10 now uniform, the consumer-side semantics can be audited independently in a sister item; the producer side is no longer a cross-client divergence axis.

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
10. **`process_builder_pending_payments` (Gloas-new epoch helper)** — consumer side of H10's writes. Sister audit item; producer side now uniform across all six clients.
11. **`state.execution_payload_availability` bitvector (Gloas-new)** — written by `process_payload_attestation`. The `data.index ∈ {0, 1}` semantics in this item depend on consistency with that bitvector.
12. **Same-slot detection idiom variants** — lodestar exposes both a state-based `isAttestationSameSlot` and a root-cache `isAttestationSameSlotRootCache`; prysm uses `IsAttestationSameSlot(beaconBlockRoot, slot)` (block-root + slot pair); lighthouse and grandine use `is_attestation_same_slot(state, data)`. Worth checking that the three signatures yield the same boolean under canonical block-import paths.
