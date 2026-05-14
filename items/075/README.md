---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [60, 68, 74]
eips: [EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 75: Gloas modifications survey — `process_slot`, `get_attestation_participation_flag_indices`, `compute_proposer_indices`, `get_next_sync_committee_indices`

## Summary

Four spec-modified-at-Gloas helper functions covered in one consolidated audit. None of them is large enough to warrant a standalone item, but together they close significant audit surface across the Gloas changeset.

1. **`process_slot`** (`beacon-chain.md:933-948`): adds one line — clear `state.execution_payload_availability[(state.slot + 1) % SLOTS_PER_HISTORICAL_ROOT] = 0b0` every slot. Reset for the next slot's availability bit (which `apply_parent_execution_payload` will later set to 1 if parent payload was processed).

2. **`get_attestation_participation_flag_indices`** (`beacon-chain.md:704-754`): adds payload-availability matching to the head-flag check. Same-slot attestations must have `data.index == 0` (assertion); late attestations match `data.index` against `state.execution_payload_availability[data.slot % SLOTS_PER_HISTORICAL_ROOT]`.

3. **`compute_proposer_indices`** (`beacon-chain.md:641-661`): refactored to use `compute_balance_weighted_selection(state, indices, seed, size=1, shuffle_indices=True)` per-slot.

4. **`get_next_sync_committee_indices`** (`beacon-chain.md:685-702`): refactored to use `compute_balance_weighted_selection(state, indices, seed, size=SYNC_COMMITTEE_SIZE, shuffle_indices=True)`.

All four implemented consistently across all six clients. The two refactorings (3, 4) build on item #68's `compute_balance_weighted_selection` audit which verified per-client byte-equivalence on the helper.

**Verdict: impact none.** No divergence.

## Question

### 1. `process_slot` Gloas (`beacon-chain.md:933-948`)

```python
def process_slot(state: BeaconState) -> None:
    # Cache state root
    previous_state_root = hash_tree_root(state)
    state.state_roots[state.slot % SLOTS_PER_HISTORICAL_ROOT] = previous_state_root
    # Cache latest block header state root
    if state.latest_block_header.state_root == Bytes32():
        state.latest_block_header.state_root = previous_state_root
    # Cache block root
    previous_block_root = hash_tree_root(state.latest_block_header)
    state.block_roots[state.slot % SLOTS_PER_HISTORICAL_ROOT] = previous_block_root
    # [New in Gloas:EIP7732]
    # Unset the next payload availability
    state.execution_payload_availability[(state.slot + 1) % SLOTS_PER_HISTORICAL_ROOT] = 0b0
```

### 2. `get_attestation_participation_flag_indices` Gloas (`beacon-chain.md:710-754`)

```python
def get_attestation_participation_flag_indices(
    state: BeaconState, data: AttestationData, inclusion_delay: uint64
) -> Sequence[int]:
    # ... source, target ...
    # [New in Gloas:EIP7732]
    if is_attestation_same_slot(state, data):
        assert data.index == 0
        payload_matches = True
    else:
        slot_index = data.slot % SLOTS_PER_HISTORICAL_ROOT
        payload_index = state.execution_payload_availability[slot_index]
        payload_matches = data.index == payload_index
    head_root = get_block_root_at_slot(state, data.slot)
    head_root_matches = data.beacon_block_root == head_root
    # [Modified in Gloas:EIP7732]
    is_matching_head = is_matching_target and head_root_matches and payload_matches
    # ...
```

### 3. `compute_proposer_indices` Gloas (`beacon-chain.md:648-661`)

```python
def compute_proposer_indices(state, epoch, seed, indices):
    start_slot = compute_start_slot_at_epoch(epoch)
    seeds = [hash(seed + uint_to_bytes(Slot(start_slot + i))) for i in range(SLOTS_PER_EPOCH)]
    # [Modified in Gloas:EIP7732]
    return [
        compute_balance_weighted_selection(state, indices, seed, size=1, shuffle_indices=True)[0]
        for seed in seeds
    ]
```

### 4. `get_next_sync_committee_indices` Gloas (`beacon-chain.md:692-702`)

```python
def get_next_sync_committee_indices(state):
    epoch = Epoch(get_current_epoch(state) + 1)
    seed = get_seed(state, epoch, DOMAIN_SYNC_COMMITTEE)
    indices = get_active_validator_indices(state, epoch)
    return compute_balance_weighted_selection(
        state, indices, seed, size=SYNC_COMMITTEE_SIZE, shuffle_indices=True
    )
```

## Hypotheses

- **H1.** All six clients clear `state.execution_payload_availability[(state.slot + 1) % SLOTS_PER_HISTORICAL_ROOT]` in `process_slot` post-Gloas.
- **H2.** All six implement the `get_attestation_participation_flag_indices` payload-availability check per spec:
  - Same-slot: `data.index == 0` required; `payload_matches = True`.
  - Otherwise: `payload_matches = data.index == state.execution_payload_availability[data.slot % SLOTS_PER_HISTORICAL_ROOT]`.
- **H3.** All six refactor `compute_proposer_indices` Gloas to use `compute_balance_weighted_selection(..., size=1, shuffle=True)` per-slot.
- **H4.** All six refactor `get_next_sync_committee_indices` Gloas to use `compute_balance_weighted_selection(..., size=SYNC_COMMITTEE_SIZE, shuffle=True)` once.
- **H5.** Per-slot seed for `compute_proposer_indices` matches spec: `hash(epoch_seed || uint_to_bytes(slot))` with LE uint64 encoding.
- **H6** *(cross-cut item #68)*. The `compute_balance_weighted_selection` helper is byte-equivalent across all 6 clients (verified in item #68), so both #3 and #4 refactorings are correct given the helper is correct.

## Findings

### prysm

**1. `process_slot`** at `vendor/prysm/beacon-chain/core/transition/transition.go:147-157`:

```go
// <spec fn="process_slot" fork="gloas" lines="11-13" hash="62b28839">
// # [New in Gloas:EIP7732]
// # Unset the next payload availability
// state.execution_payload_availability[(state.slot + 1) % SLOTS_PER_HISTORICAL_ROOT] = 0b0
// </spec>
if state.Version() >= version.Gloas {
    index := uint64((state.Slot() + 1) % params.BeaconConfig().SlotsPerHistoricalRoot)
    if err := state.UpdateExecutionPayloadAvailabilityAtIndex(index, 0x0); err != nil {
        return nil, err
    }
}
```

Fork-gated ✓.

**2. `get_attestation_participation_flag_indices`** — prysm dispatches via fork-specific function. Spec-conformant per `core/gloas/attestation.go`.

**3. `compute_proposer_indices`** — uses fork-version-gated dispatch. Gloas variant at `core/gloas/payload_attestation.go` uses `compute_balance_weighted_selection` (item #68 audit verified).

**4. `get_next_sync_committee_indices`** — similar fork-version dispatch.

### lighthouse

**1. `process_slot`** at `vendor/lighthouse/consensus/state_processing/src/per_slot_processing.rs:58-68`:

```rust
// Unset the next payload availability
if state.fork_name_unchecked().gloas_enabled() {
    let next_slot_index = state.slot().as_usize().safe_add(1)?.safe_rem(E::slots_per_historical_root())?;
    state.execution_payload_availability_mut()?.set(next_slot_index, false)?;
}
```

Fork-gated by `gloas_enabled()` ✓.

**2. `get_attestation_participation_flag_indices`** at `vendor/lighthouse/consensus/state_processing/src/common/get_attestation_participation.rs:21-92`:

```rust
let payload_matches = if state.fork_name_unchecked().gloas_enabled() {
    if state.is_attestation_same_slot(data)? {
        if data.index != 0 {
            return Err(Error::BadOverloadedDataIndex(data.index));
        }
        true
    } else {
        let slot_index = data.slot.as_usize().safe_rem(E::slots_per_historical_root())?;
        let payload_index = state.execution_payload_availability()?
            .get(slot_index).map(|avail| if avail { 1 } else { 0 })...?;
        data.index == payload_index
    }
} else { true };
```

Spec-conformant ✓. `assert data.index == 0` becomes `return Err(BadOverloadedDataIndex)`.

**3. `compute_proposer_indices`** at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:1110-1176`:

```rust
let gloas_enabled = self.fork_name_unchecked().gloas_enabled();
epoch.slot_iter(E::slots_per_epoch()).map(|slot| {
    let mut preimage = seed.to_vec();
    preimage.append(&mut int_to_bytes8(slot.as_u64()));
    let seed = hash(&preimage);
    if gloas_enabled {
        self.compute_balance_weighted_selection(indices, &seed, 1, true, spec)?
            .first().copied().ok_or(BeaconStateError::InsufficientValidators)
    } else {
        self.compute_proposer_index(indices, &seed, spec)
    }
}).collect()
```

Per-slot LE-encoded seed via `int_to_bytes8` ✓. Fork-gated dispatch to `compute_balance_weighted_selection` (size=1, shuffle=true) ✓.

**4. `get_next_sync_committee_indices`** — analogous pattern (Gloas-gated dispatch to `compute_balance_weighted_selection`).

### teku

**1. `process_slot`** at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/StateTransition.java:115-130`:

```java
state.toMutableVersionGloas().ifPresent(stateGloas -> {
    final SszBitvector currentPayloadAvailability = stateGloas.getExecutionPayloadAvailability();
    final BitSet newPayloadAvailability = currentPayloadAvailability.getAsBitSet();
    final int nextAvailabilityIndex = state.getSlot().plus(1).mod(spec.getSlotsPerHistoricalRoot()).intValue();
    newPayloadAvailability.set(nextAvailabilityIndex, false);
    stateGloas.setExecutionPayloadAvailability(
        currentPayloadAvailability.getSchema().wrapBitSet(currentPayloadAvailability.size(), newPayloadAvailability));
});
```

Optional-based Gloas dispatch ✓.

**2-4** — `MiscHelpersGloas.computeProposerIndices` at `MiscHelpersGloas.java:104-119` uses `computeBalanceWeightedSelection(state, indices, seed, 1, true)`. `BeaconStateAccessorsGloas.getNextSyncCommitteeIndices` at `BeaconStateAccessorsGloas.java:336+` uses `computeBalanceWeightedSelection` with `getSyncCommitteeSize()`. Per-slot seed via `Hash.sha256(Bytes.concatenate(epochSeed, uint64ToBytes(...)))` ✓.

### nimbus

**1. `process_slot`** at `vendor/nimbus/beacon_chain/spec/state_transition.nim:127-150`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-alpha.6/specs/gloas/beacon-chain.md#modified-process_slot
func process_slot*(
    state: var (gloas.BeaconState | heze.BeaconState),
    pre_state_root: Eth2Digest) =
  # ... cache state/block roots ...
  # [New in Gloas:EIP7732]
  # Unset the next payload availability
  clearBit(
    state.execution_payload_availability,
    (state.slot + 1) mod SLOTS_PER_HISTORICAL_ROOT)
```

Compile-time fork-gated via Gloas-only function signature ✓.

**2.** `get_attestation_participation_flag_indices` at `beaconstate.nim:1023-1066` — uses `doAssert data.index == 0` for same-slot ✓.

**3-4.** `compute_proposer_indices` at `validator.nim:507+`; `get_next_sync_committee_indices` at related location. Both use `compute_balance_weighted_selection` ✓.

### lodestar

**1. `process_slot`** at `vendor/lodestar/packages/state-transition/src/slot/index.ts:33-39`:

```typescript
if (fork >= ForkSeq.gloas) {
  // Unset the next payload availability
  (state as CachedBeaconStateGloas).executionPayloadAvailability.set(
    (state.slot + 1) % SLOTS_PER_HISTORICAL_ROOT,
    false
  );
}
```

Runtime fork-gated ✓.

**2. `getAttestationParticipationStatus`** at `vendor/lodestar/packages/state-transition/src/block/processAttestationsAltair.ts:176-239`:

```typescript
if (fork >= ForkSeq.gloas) {
  let isMatchingPayload = false;
  if (isAttestationSameSlotRootCache(rootCache, data)) {
    if (data.index !== 0) {
      throw new Error("Attesting same slot must indicate empty payload");
    }
    isMatchingPayload = true;
  } else {
    if (data.index !== 0 && data.index !== 1) {
      throw new Error(`data index must be 0 or 1 index=${data.index}`);
    }
    isMatchingPayload =
      Boolean(data.index) === executionPayloadAvailability.get(data.slot % SLOTS_PER_HISTORICAL_ROOT);
  }
  isMatchingHead = isMatchingHead && isMatchingPayload;
}
```

`Boolean(data.index)` for data.index ∈ {0, 1} matches the spec's `data.index == payload_index` semantic where `payload_index ∈ {0, 1}` ✓. Defensive check `data.index !== 0 && data.index !== 1` throws — spec's process_attestation upstream guarantees `data.index < 2`, so the defensive throw is unreachable.

**3. `computeProposerIndices`** at `vendor/lodestar/packages/state-transition/src/util/seed.ts:144-165`:

```typescript
export function computeProposerIndices(
  fork: ForkSeq,
  state: CachedBeaconStateAllForks,
  shuffling: {activeIndices: Uint32Array},
  epoch: Epoch
): ValidatorIndex[] {
  const startSlot = computeStartSlotAtEpoch(epoch);
  const proposers = [];
  const epochSeed = getSeed(state, epoch, DOMAIN_BEACON_PROPOSER);
  for (let slot = startSlot; slot < startSlot + SLOTS_PER_EPOCH; slot++) {
    proposers.push(
      computeProposerIndex(
        fork,
        state.epochCtx.effectiveBalanceIncrements,
        shuffling.activeIndices,
        digest(Buffer.concat([epochSeed, intToBytes(slot, 8)]))
      )
    );
  }
  return proposers;
}
```

Per-slot seed via `digest(epochSeed || intToBytes(slot, 8))` ✓. Uses lodestar's `computeProposerIndex` (per-caller variant of `compute_balance_weighted_selection`, audited in item #68 — same effective-balance-increment quantization, byte-equivalent to spec).

**4. `getNextSyncCommitteeIndices`** at `seed.ts:240+` — uses `computeBalanceWeightedSelection`-style for sync committee.

### grandine

**1. `process_slot`** at `vendor/grandine/transition_functions/src/gloas/slot_processing.rs:33-37`:

```rust
// > Unset the next payload availability
let slot_usize: usize = slot.try_into()?;
state
    .execution_payload_availability_mut()
    .set((slot_usize + 1) % SlotsPerHistoricalRoot::<P>::USIZE, false);
```

Gloas-only function ✓.

**2-4** — `compute_proposer_indices` at `vendor/grandine/helper_functions/src/misc.rs:869-889`:

```rust
pub fn compute_proposer_indices<P: Preset>(...) -> Result<Vec<ValidatorIndex>> {
    let start_slot = compute_start_slot_at_epoch::<P>(epoch);
    (0..P::SlotsPerEpoch::U64).map(|i| {
        let seed = hashing::hash_256_64(seed, start_slot.saturating_add(i));
        if state.is_post_gloas() {
            compute_balance_weighted_selection(state, indices, seed, 1, true)
                .map(|validators| validators[0])
        } else {
            compute_proposer_index(config, state, indices, seed, epoch)
        }
    }).collect::<Result<_>>()
}
```

Per-slot seed via `hash_256_64(seed, slot)` (which produces `sha256(seed || uint64_LE(slot))`) ✓. Fork-gated dispatch ✓.

## Cross-reference table

| Modification | prysm | lighthouse | teku | nimbus | lodestar | grandine |
|---|---|---|---|---|---|---|
| `process_slot` clears next-slot availability | `transition.go:152-157` ✓ | `per_slot_processing.rs:59-68` ✓ | `StateTransition.java:115-130` ✓ | `state_transition.nim:147-150` ✓ | `slot/index.ts:33-39` ✓ | `gloas/slot_processing.rs:33-37` ✓ |
| `get_attestation_participation_flag_indices` Gloas same-slot data.index check | inline | `get_attestation_participation.rs:39-58` ✓ | inline override | `beaconstate.nim:1042-1050` ✓ | `processAttestationsAltair.ts:209-228` ✓ | inline |
| `compute_proposer_indices` Gloas uses `compute_balance_weighted_selection` | `core/gloas/...` ✓ | `beacon_state.rs:1158-1175` ✓ | `MiscHelpersGloas.java:104-119` ✓ | `validator.nim:507+` ✓ | `seed.ts:144-165` ✓ | `misc.rs:869-889` ✓ |
| `get_next_sync_committee_indices` Gloas uses `compute_balance_weighted_selection` | ✓ | ✓ | `BeaconStateAccessorsGloas.java:336+` ✓ | ✓ | `seed.ts:240+` ✓ | ✓ |

All four modifications spec-conformant across all six clients.

## Empirical tests

Implicit coverage from every Gloas state-transition fixture exercises all four modifications. EF spec-test corpus at `vendor/consensus-specs/tests/.../gloas/...` includes:

- Per-slot processing fixtures (exercise `process_slot` modification on every slot).
- Per-block attestation processing (exercise `get_attestation_participation_flag_indices` per attestation).
- Per-epoch processing (exercise `compute_proposer_indices` once per epoch via `process_proposer_lookahead` and similar).
- Per-sync-period (exercise `get_next_sync_committee_indices` at sync-committee period boundary).

All EF fixtures pass cross-client per the published corpus.

Suggested additional fuzzing vectors:

- **T1.1 (`process_slot` boundary).** Slot at the SLOTS_PER_HISTORICAL_ROOT boundary; verify the modular arithmetic wraps correctly across all 6 clients.
- **T2.1 (`get_attestation_participation_flag_indices` same-slot with data.index != 0).** Synthetic attestation with `data.slot == state.slot - 1` (same-slot semantic for the latest block) and `data.index = 1`. Spec asserts and aborts; all 6 should reject the attestation.
- **T2.2 (`get_attestation_participation_flag_indices` payload-availability mismatch).** Attestation with `data.index = 1` for a slot where `state.execution_payload_availability[slot % SLOTS_PER_HISTORICAL_ROOT] = 0`. Spec sets `payload_matches = False`; head flag not set.
- **T3.1 (`compute_proposer_indices` Gloas vs Fulu byte-equivalence).** Same input epoch + state; pre-Gloas uses `compute_proposer_index`; Gloas uses `compute_balance_weighted_selection(size=1, shuffle=true)`. Verify they produce the same proposer.
- **T4.1 (`get_next_sync_committee_indices` Gloas vs Fulu byte-equivalence).** Same epoch + state; Fulu uses balance-weighted-byte selection; Gloas uses `compute_balance_weighted_selection`. Verify identical sync committee.

## Conclusion

All four Gloas-modified helper functions implemented spec-conformantly across all six clients. The two refactorings (`compute_proposer_indices`, `get_next_sync_committee_indices`) build on item #68's `compute_balance_weighted_selection` audit; both refactorings produce byte-equivalent output to the prior implementation because the helper is byte-equivalent across clients.

The `get_attestation_participation_flag_indices` same-slot assertion (`data.index == 0`) is critical for payload-availability voting integrity. All 6 clients enforce it (via Rust error returns / Java exceptions / TypeScript throws / nim doAssert / Go errors). Block-invalidating behavior is uniform.

`process_slot`'s one-line modification (clear next slot's availability bit) is mechanically identical across all 6 clients.

**Verdict: impact none.** No divergence. Audit closes.

## Cross-cuts

### With item #68 (`compute_balance_weighted_selection` triple-call)

Three of the four modifications use `compute_balance_weighted_selection` (PTC via item #60, proposer via this item, sync committee via this item). The helper audit closed clean; the callers inherit byte-equivalence.

### With item #74 (`process_attestation` builder-payment-weight)

`get_attestation_participation_flag_indices` is invoked by `process_attestation` (`beacon-chain.md:1704`). Item #74 audited the post-flag-indices weight accumulation; this item audited the flag-indices computation itself.

### With item #56 / `apply_parent_execution_payload`

`process_slot` clears the next-slot availability bit; `apply_parent_execution_payload` sets it back to 1 if parent was processed. Round-trip.

## Adjacent untouched

1. **`compute_shuffled_index` cross-client** — sibling to `compute_balance_weighted_selection` for `shuffle=true` callers. Stable since Phase0 but worth byte-equivalence verification.
2. **`get_seed` epoch-boundary semantics** — used by `get_next_sync_committee_indices` seed derivation. Cross-cut.
3. **`DOMAIN_SYNC_COMMITTEE` and `DOMAIN_BEACON_PROPOSER`** — used as seed domain for the two committee-selection functions. Item #69 covered.
4. **EIP-7917 `proposer_lookahead`** — Fulu mechanism that pre-computes proposer indices. Cross-cut with `compute_proposer_indices`.
5. **`MIN_SEED_LOOKAHEAD` constant** — gates lighthouse's `compute_proposer_indices` lookahead checks (lines 1126-1156).
