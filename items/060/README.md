---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [7, 13, 19, 59]
eips: [EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 60: Payload Timeliness Committee (PTC) selection + `process_payload_attestation` + `is_valid_indexed_payload_attestation`

## Summary

All six clients are spec-conformant on the Gloas Payload Timeliness Committee (PTC) selection (`compute_ptc` / `get_ptc`), `get_indexed_payload_attestation`, `process_payload_attestation`, and `is_valid_indexed_payload_attestation`. Each client uses `compute_balance_weighted_selection` with `shuffle_indices=False` over the per-slot concatenated beacon committees, seeded by `hash(get_seed(state, epoch, DOMAIN_PTC_ATTESTER) ++ uint_to_bytes(slot))`. Each client sorts `attesting_indices` in `get_indexed_payload_attestation` (matching the v1.7.0-alpha.4+ spec line 790 `sorted(attesting_indices)`), and each accepts duplicate indices in the sortedness check (matching the spec's `indices == sorted(indices)` semantics over a list whose source committee may contain duplicates per `compute_ptc`'s "with possible duplicates" annotation).

One literal-vs-functional deviation observed: **grandine's `process_payload_attestation` block-processing path skips the sortedness re-check** by calling `validate_constructed_indexed_payload_attestation` (which passes `validate_indices_sorted: false`) rather than `validate_received_indexed_payload_attestation`. This is a redundancy elimination — `get_indexed_payload_attestation` always sorts before constructing the indexed attestation, so the spec's re-check is mathematically always true on the block-processing path. Cannot diverge under any reachable input.

The PTC window cache shape is identical across all clients that materialize it (lighthouse, teku, nimbus, grandine, lodestar) — `(MIN_SEED_LOOKAHEAD + 1) * SLOTS_PER_EPOCH` rows of `Vector[ValidatorIndex, PTC_SIZE]`, indexed by `(epoch - state_epoch + 1) * SLOTS_PER_EPOCH + slot_in_epoch`. Prysm computes PTC on-demand rather than caching a `ptc_window` field.

## Question

Pyspec `compute_ptc` (Gloas, `vendor/consensus-specs/specs/gloas/beacon-chain.md:666-680`):

```python
def compute_ptc(state: BeaconState, slot: Slot) -> Vector[ValidatorIndex, PTC_SIZE]:
    """
    Get the payload timeliness committee, with possible duplicates, for the given ``slot``.
    """
    epoch = compute_epoch_at_slot(slot)
    seed = hash(get_seed(state, epoch, DOMAIN_PTC_ATTESTER) + uint_to_bytes(slot))
    indices: List[ValidatorIndex] = []
    # Concatenate all committees for this slot in order
    committees_per_slot = get_committee_count_per_slot(state, epoch)
    for i in range(committees_per_slot):
        committee = get_beacon_committee(state, slot, CommitteeIndex(i))
        indices.extend(committee)
    return compute_balance_weighted_selection(
        state, indices, seed, size=PTC_SIZE, shuffle_indices=False
    )
```

`get_indexed_payload_attestation` (`beacon-chain.md:778-794`):

```python
def get_indexed_payload_attestation(
    state: BeaconState, payload_attestation: PayloadAttestation
) -> IndexedPayloadAttestation:
    slot = payload_attestation.data.slot
    ptc = get_ptc(state, slot)
    bits = payload_attestation.aggregation_bits
    attesting_indices = [index for i, index in enumerate(ptc) if bits[i]]

    return IndexedPayloadAttestation(
        attesting_indices=sorted(attesting_indices),
        data=payload_attestation.data,
        signature=payload_attestation.signature,
    )
```

`is_valid_indexed_payload_attestation` (`beacon-chain.md:514-530`):

```python
def is_valid_indexed_payload_attestation(
    state: BeaconState, attestation: IndexedPayloadAttestation
) -> bool:
    # Verify indices are non-empty and sorted
    indices = attestation.attesting_indices
    if len(indices) == 0 or not indices == sorted(indices):
        return False
    # Verify aggregate signature
    pubkeys = [state.validators[i].pubkey for i in indices]
    domain = get_domain(state, DOMAIN_PTC_ATTESTER, compute_epoch_at_slot(attestation.data.slot))
    signing_root = compute_signing_root(attestation.data, domain)
    return bls.FastAggregateVerify(pubkeys, signing_root, attestation.signature)
```

`process_payload_attestation` (`beacon-chain.md:1767-1779`):

```python
def process_payload_attestation(
    state: BeaconState, payload_attestation: PayloadAttestation
) -> None:
    data = payload_attestation.data
    assert data.beacon_block_root == state.latest_block_header.parent_root
    assert data.slot + 1 == state.slot
    indexed_payload_attestation = get_indexed_payload_attestation(state, payload_attestation)
    assert is_valid_indexed_payload_attestation(state, indexed_payload_attestation)
```

Key semantic subtleties:

1. **Duplicates allowed.** `compute_ptc` docstring says "with possible duplicates" (because `compute_balance_weighted_selection(shuffle_indices=False)` traverses concatenated committees with `i % total` wraparound). So `attesting_indices` may have duplicates, and `indices == sorted(indices)` is satisfied by `<=`-monotone lists (not strict `<`).
2. **Sortedness check is redundant with construction.** `get_indexed_payload_attestation` sorts before returning; `is_valid_indexed_payload_attestation` immediately re-checks. Optimization-safe to skip the re-check on the construction path; required only on the gossip-receive path where an attacker provides the `attesting_indices` directly.
3. **Domain.** `DOMAIN_PTC_ATTESTER = 0x0C000000` (Gloas-new); distinct from `DOMAIN_BEACON_ATTESTER`.
4. **Slot binding.** `data.slot + 1 == state.slot` — PTC attests the **previous** slot's payload.
5. **Block-root binding.** `data.beacon_block_root == state.latest_block_header.parent_root` — attestation references the parent of the block currently being processed.

## Hypotheses

- **H1.** All six clients implement `compute_ptc` using `compute_balance_weighted_selection` with `shuffle_indices=false`, seeded by `hash(get_seed(state, epoch, DOMAIN_PTC_ATTESTER) ++ uint_to_bytes(slot))` (40-byte preimage).
- **H2.** All six clients implement `get_ptc` via a cached `state.ptc_window` indexed by `(epoch+1-state_epoch)*SLOTS_PER_EPOCH + slot_in_epoch`, with the same out-of-range guard (`epoch ∈ [state_epoch-1, state_epoch+MIN_SEED_LOOKAHEAD]`).
- **H3.** All six clients sort `attesting_indices` in `get_indexed_payload_attestation` (matching the alpha.4 spec change that added `sorted()`).
- **H4.** All six clients implement `is_valid_indexed_payload_attestation` to accept duplicate indices (i.e., use `<=`-monotone, not strict `<`).
- **H5.** All six clients implement `process_payload_attestation` with `beacon_block_root == parent_root` + `slot+1 == state.slot` predicates in the same order, and dispatch the indexed-attestation construction + validation in that order.
- **H6.** All six clients use `DOMAIN_PTC_ATTESTER` (0x0C000000) for the BLS aggregate, with epoch derived from `attestation.data.slot`.
- **H7** *(optimization-allowed deviation)*. Some clients may skip the redundant sortedness re-check in the block-processing path (`get_indexed_payload_attestation` just sorted). This is functionally equivalent to the spec; the only behavior change is on the gossip-receive path where an externally-constructed `IndexedPayloadAttestation` arrives. Verify which clients distinguish these paths.

## Findings

All six clients are spec-conformant. Findings below capture file references, sortedness semantics, and one literal-vs-functional deviation (grandine, H7).

### prysm

**`process_payload_attestation`** at `vendor/prysm/beacon-chain/core/gloas/payload_attestation.go:47-81`:

```go
func ProcessPayloadAttestations(ctx context.Context, st state.BeaconState, body interfaces.ReadOnlyBeaconBlockBody) error {
    atts, err := body.PayloadAttestations()
    if err != nil { return errors.Wrap(err, "...") }
    if len(atts) == 0 { return nil }
    header := st.LatestBlockHeader()
    for i, att := range atts {
        data := att.Data
        if !bytes.Equal(data.BeaconBlockRoot, header.ParentRoot) {
            return fmt.Errorf("payload attestation %d has wrong parent: ...", i)
        }
        dataSlot, err := data.Slot.SafeAdd(1)
        if err != nil { ... }
        if dataSlot != st.Slot() {
            return fmt.Errorf("payload attestation %d has wrong slot: ...", i)
        }
        indexed, err := indexedPayloadAttestation(ctx, st, att)
        if err != nil { ... }
        if err := validIndexedPayloadAttestation(st, indexed); err != nil { ... }
    }
    return nil
}
```

Spec-conformant: parent-root check, `Slot.SafeAdd(1)` slot check, indexed construction, validity check.

**`indexedPayloadAttestation`** at `payload_attestation.go:84-102`:

```go
func indexedPayloadAttestation(...) (*consensus_types.IndexedPayloadAttestation, error) {
    committee, err := st.PayloadCommitteeReadOnly(att.Data.Slot)
    ...
    indices := make([]primitives.ValidatorIndex, 0, len(committee))
    for i, idx := range committee {
        if att.AggregationBits.BitAt(uint64(i)) {
            indices = append(indices, idx)
        }
    }
    slices.Sort(indices)
    return &consensus_types.IndexedPayloadAttestation{
        AttestingIndices: indices,
        Data:             att.Data,
        Signature:        att.Signature,
    }, nil
}
```

Spec-conformant: iterates PTC in committee order, picks indices where aggregation_bits set, then sorts via `slices.Sort` (matches `sorted()`).

**`validIndexedPayloadAttestation`** at `payload_attestation.go:296-300`:

```go
func validIndexedPayloadAttestation(st state.ReadOnlyBeaconState, att *consensus_types.IndexedPayloadAttestation) error {
    indices := att.AttestingIndices
    if len(indices) == 0 || !slices.IsSorted(indices) {
        return errors.New("attesting indices empty or unsorted")
    }
    ...
}
```

Spec-conformant: `slices.IsSorted` uses `<=` (allows duplicates per spec's `indices == sorted(indices)` semantics over a list with possible duplicates).

**`computePTC`** at `payload_attestation.go:123-162`: traverses `committeesPerSlot` committees, then calls `selectByBalanceFill` per committee. Outer `for len(selected) < PTC_SIZE` loops back to committee 0 if not full. The counter `i` is preserved across committee fetches, so the random-bytes block + offset computation (`i / 16` and `(i % 16) * 2`) matches spec semantics. Equivalent to spec's `i % total` wraparound. **Note: prysm computes PTC on-demand via `PayloadCommitteeReadOnly`; it does not materialize a `state.ptc_window` field per-slot like lighthouse/teku/nimbus/grandine.** Acceptable: spec defines `state.ptc_window` as a cache, not a consensus-relevant field for `compute_ptc`.

**`ptcSeed`** at `payload_attestation.go:183-189`: matches spec — `hash(seed || bytesutil.Bytes8(slot))`.

### lighthouse

**`verify_payload_attestation`** at `vendor/lighthouse/consensus/state_processing/src/per_block_processing/verify_payload_attestation.rs:8-46`:

```rust
pub fn verify_payload_attestation<'ctxt, E: EthSpec>(...) -> Result<(), BlockOperationError<Invalid>> {
    let data = &payload_attestation.data;
    verify!(
        data.beacon_block_root == state.latest_block_header().parent_root,
        Invalid::BlockRootMismatch { ... }
    );
    verify!(
        data.slot.safe_add(1)? == state.slot(),
        Invalid::SlotMismatch { ... }
    );
    let indexed_payload_attestation =
        ctxt.get_indexed_payload_attestation(state, payload_attestation, spec)?;
    is_valid_indexed_payload_attestation(state, indexed_payload_attestation, verify_signatures, spec)?;
    Ok(())
}
```

Spec-conformant. `process_payload_attestation` at `process_operations.rs:1213` is a thin wrapper that adds the `att_index` for error reporting.

**`get_indexed_payload_attestation`** + helper at `vendor/lighthouse/consensus/state_processing/src/common/get_payload_attesting_indices.rs:10-42`:

```rust
pub fn get_payload_attesting_indices<E: EthSpec>(...) -> Result<Vec<u64>, BeaconStateError> {
    let slot = payload_attestation.data.slot;
    let ptc = state.get_ptc(slot, spec)?;
    let bits = &payload_attestation.aggregation_bits;
    let mut attesting_indices = vec![];
    for (i, index) in ptc.into_iter().enumerate() {
        if let Ok(true) = bits.get(i) {
            attesting_indices.push(index as u64);
        }
    }
    attesting_indices.sort_unstable();
    Ok(attesting_indices)
}
```

Spec-conformant: sort via `sort_unstable()` matches `sorted()`.

**`is_valid_indexed_payload_attestation`** at `vendor/lighthouse/consensus/state_processing/src/per_block_processing/is_valid_indexed_payload_attestation.rs:6-32`:

```rust
pub fn is_valid_indexed_payload_attestation<E: EthSpec>(...) -> Result<(), BlockOperationError<Invalid>> {
    // Verify indices are non-empty and sorted (duplicates allowed)
    let indices = &indexed_payload_attestation.attesting_indices;
    verify!(!indices.is_empty(), Invalid::IndicesEmpty);
    verify!(indices.is_sorted(), Invalid::BadValidatorIndicesOrdering);
    if verify_signatures.is_true() {
        verify!(
            indexed_payload_attestation_signature_set(...)?.verify(),
            Invalid::BadSignature
        );
    }
    Ok(())
}
```

Spec-conformant: Rust's `slice::is_sorted()` uses `<=`-monotone semantics (allows duplicates). Comment confirms: "duplicates allowed".

**`BeaconState::get_ptc`** at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:3159`: looks up the cached `ptc_window` field with index `(epoch - state_epoch + 1) * SLOTS_PER_EPOCH + slot_in_epoch`. Out-of-range guard matches spec.

**`BeaconState::compute_ptc`** at `beacon_state.rs:3195-3224`: collects concatenated committee indices, calls `compute_balance_weighted_selection(..., shuffle_indices=false)`. Spec-conformant.

**`get_ptc_attester_seed`** at `beacon_state.rs:3227-3239`: `hash(get_seed(state, epoch, Domain::PTCAttester) ++ int_to_bytes8(slot))`. Spec-conformant.

### teku

**`processPayloadAttestations`** at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/block/BlockProcessorGloas.java:439-462`:

```java
public void processPayloadAttestations(
    final MutableBeaconState state, final SszList<PayloadAttestation> payloadAttestations)
    throws BlockProcessingException {
  for (final PayloadAttestation payloadAttestation : payloadAttestations) {
    final PayloadAttestationData data = payloadAttestation.getData();
    if (!data.getBeaconBlockRoot().equals(state.getLatestBlockHeader().getParentRoot())) {
      throw new BlockProcessingException("Attestation is NOT for the parent beacon block");
    }
    if (!data.getSlot().increment().equals(state.getSlot())) {
      throw new BlockProcessingException("Attestation is NOT for the previous slot");
    }
    final IndexedPayloadAttestation indexedPayloadAttestation =
        beaconStateAccessorsGloas.getIndexedPayloadAttestation(state, payloadAttestation);
    if (!attestationUtilGloas.isValidIndexedPayloadAttestation(
        state, indexedPayloadAttestation)) {
      throw new BlockProcessingException("Indexed payload attestation is NOT valid");
    }
  }
}
```

Spec-conformant: parent-root, slot, indexed, validity in same order as spec.

**`getIndexedPayloadAttestation`** at `BeaconStateAccessorsGloas.java:165-191`: iterates `ptc` indices, filters by `aggregationBits.isSet(i)`, then sorts the resulting `IntStream`:

```java
final SszUInt64List sszAttestingIndices =
    attestingIndices
        .intStream()
        .sorted()
        .mapToObj(idx -> SszUInt64.of(UInt64.valueOf(idx)))
        .collect(...);
```

Spec-conformant: `IntStream.sorted()` matches `sorted()`.

**`isValidIndexedPayloadAttestation`** at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/util/AttestationUtilGloas.java:52-73`:

```java
public boolean isValidIndexedPayloadAttestation(
    final BeaconState state, final IndexedPayloadAttestation attestation) {
  final List<UInt64> indices = attestation.getAttestingIndices().asListUnboxed();
  if (indices.isEmpty() || !Comparators.isInOrder(indices, UInt64::compareTo)) {
    return false;
  }
  final List<BLSPublicKey> pubKeys =
      indices.stream()
          .map(index -> state.getValidators().get(index.intValue()).getPublicKey())
          .toList();
  final Bytes32 domain =
      beaconStateAccessors.getDomain(
          state.getForkInfo(),
          Domain.PTC_ATTESTER,
          miscHelpers.computeEpochAtSlot(attestation.getData().getSlot()));
  final Bytes signingRoot = miscHelpers.computeSigningRoot(attestation.getData(), domain);
  return specConfig.getBLSSignatureVerifier().verify(pubKeys, signingRoot, attestation.getSignature());
}
```

Spec-conformant: `Comparators.isInOrder` (Guava) uses `<=`-monotone semantics (returns true for `[1, 1, 2]`). Allows duplicates.

**`computePtc`** at `BeaconStateAccessorsGloas.java:198-218`: spec-conformant. Concatenates `getCommitteeCountPerSlot` committees, hashes seed + slot via `Hash.sha256(Bytes.concatenate(getSeed(...), uint64ToBytes(slot)))`, calls `computeBalanceWeightedSelection(..., false)`.

**`getPtc`** at `BeaconStateAccessorsGloas.java:225-252`: looks up `state.toVersionGloas().get().getPtcWindow().get(cacheIndex).toIntList()` with cacheIndex matching spec. Falls back to `computePtc` at the fork boundary (where `state` is pre-Gloas).

### nimbus

**`process_payload_attestation`** at `vendor/nimbus/beacon_chain/spec/state_transition_block.nim:804-825`:

```nim
proc process_payload_attestation*(
    state: var (gloas.BeaconState | heze.BeaconState),
    payload_attestation: PayloadAttestation): Result[void, cstring] =
  template data: untyped = payload_attestation.data
  if data.beacon_block_root != state.latest_block_header.parent_root:
    return err("process_payload_attestation: beacon block root mismatch")
  if data.slot + 1 != state.slot:
    return err("process_payload_attestation: slot mismatch")
  let indexed_payload_attestation = get_indexed_payload_attestation(
    state, data.slot, payload_attestation)
  if not is_valid_indexed_payload_attestation(state, indexed_payload_attestation):
    return err("process_payload_attestation: invalid signature")
  ok()
```

Spec-conformant.

**`get_indexed_payload_attestation`** at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:3214-3233`:

```nim
func get_indexed_payload_attestation*(
    state: gloas.BeaconState | heze.BeaconState, slot: Slot,
    payload_attestation: PayloadAttestation): IndexedPayloadAttestation =
  var attesting_indices = newSeqOfCap[uint64](PTC_SIZE)
  var i = 0
  for index in get_ptc(state, slot):
    if payload_attestation.aggregation_bits[i]:
      attesting_indices.add(index.uint64)
    inc i
  attesting_indices.sort()
  IndexedPayloadAttestation(
    attesting_indices: List[uint64, Limit PTC_SIZE].init(attesting_indices),
    data: payload_attestation.data,
    signature: payload_attestation.signature
  )
```

Spec-conformant: `attesting_indices.sort()` (nim std/algorithm) matches `sorted()`.

**`is_valid_indexed_payload_attestation`** at `beaconstate.nim:3236-3262`:

```nim
proc is_valid_indexed_payload_attestation*(
    state: gloas.BeaconState | heze.BeaconState,
    indexed_payload_attestation: IndexedPayloadAttestation): bool =
  if indexed_payload_attestation.attesting_indices.len == 0:
    return false
  if not toSeq(indexed_payload_attestation.attesting_indices).isSorted:
    return false
  let
    pubkeys = mapIt(indexed_payload_attestation.attesting_indices, state.validators[it].pubkey)
    domain = get_domain(state.fork, DOMAIN_PTC_ATTESTER,
      indexed_payload_attestation.data.slot.epoch, state.genesis_validators_root)
    signing_root = compute_signing_root(indexed_payload_attestation.data, domain)
  blsFastAggregateVerify(pubkeys, signing_root.data, indexed_payload_attestation.signature)
```

Spec-conformant: nim's `algorithm.isSorted` with default `cmp` allows `<=`-monotone (duplicates).

**Note on docstring drift.** Nimbus's docstring (line 3239) says "has sorted *and unique* indices" but the code (line 3246 `isSorted`) only checks sortedness, not uniqueness. The code matches the spec ("sorted indices", duplicates allowed per `compute_ptc` "with possible duplicates"); the docstring is stale. Cosmetic only — no behavior change. Worth a one-line nimbus PR but not a divergence.

**`compute_ptc`** at `beaconstate.nim:2323-2343`: spec-conformant. Builds 40-byte buffer `get_seed(...).data ++ uint_to_bytes(slot.distinctBase)`, hashes, calls `compute_balance_weighted_selection(state, indices, seed, size=PTC_SIZE, shuffle_indices=false)`.

**`get_ptc`** at `beaconstate.nim:2348-2365`: cached lookup via `state.ptc_window[index]` with index = `(epoch + 1 - state_epoch).Epoch.start_slot.uint64 + slot_in_epoch`. Range check matches spec.

### lodestar

**`processPayloadAttestation`** at `vendor/lodestar/packages/state-transition/src/block/processPayloadAttestation.ts:6-25`:

```typescript
export function processPayloadAttestation(
  state: CachedBeaconStateGloas,
  payloadAttestation: gloas.PayloadAttestation
): void {
  const data = payloadAttestation.data;
  if (!byteArrayEquals(data.beaconBlockRoot, state.latestBlockHeader.parentRoot)) {
    throw Error("Payload attestation is referring to the wrong block");
  }
  if (data.slot + 1 !== state.slot) {
    throw Error("Payload attestation is not from previous slot");
  }
  const indexedPayloadAttestation = state.epochCtx.getIndexedPayloadAttestation(data.slot, payloadAttestation);
  if (!isValidIndexedPayloadAttestation(state, indexedPayloadAttestation, true)) {
    throw Error("Invalid payload attestation");
  }
}
```

Spec-conformant.

**`isValidIndexedPayloadAttestation`** at `vendor/lodestar/packages/state-transition/src/block/isValidIndexedPayloadAttestation.ts:6-26`:

```typescript
export function isValidIndexedPayloadAttestation(
  state: CachedBeaconStateGloas,
  indexedPayloadAttestation: gloas.IndexedPayloadAttestation,
  verifySignature: boolean
): boolean {
  const indices = indexedPayloadAttestation.attestingIndices;
  const isSorted = indices.every((val, i, arr) => i === 0 || arr[i - 1] <= val);
  if (indices.length === 0 || !isSorted) {
    return false;
  }
  if (verifySignature) {
    return verifySignatureSet(
      getIndexedPayloadAttestationSignatureSet(state.config, indexedPayloadAttestation),
      state.epochCtx.pubkeyCache
    );
  }
  return true;
}
```

Spec-conformant: `arr[i - 1] <= val` allows duplicates.

**`getIndexedPayloadAttestation`** lives on the epoch context (`vendor/lodestar/packages/state-transition/src/cache/epochCache.ts:1050`); per the alpha.4 spec it sorts the indices after filtering by aggregation bits. The PTC window cache lives in the epoch context (`getPtcWindowEpochCacheData` at `src/util/gloas.ts:198`).

### grandine

**`process_payload_attestation`** at `vendor/grandine/transition_functions/src/gloas/block_processing.rs:1236-1275`:

```rust
pub fn process_payload_attestation<P: Preset>(
    config: &Config,
    pubkey_cache: &PubkeyCache,
    state: &impl PostGloasBeaconState<P>,
    payload_attestation: &PayloadAttestation<P>,
    verifier: impl Verifier,
) -> Result<()> {
    let data = payload_attestation.data;
    let in_attestation = data.beacon_block_root;
    let in_header = state.latest_block_header().parent_root;
    ensure!(in_attestation == in_header, Error::<P>::PayloadAttestationBlockRootMismatch { ... });
    let state_slot = state.slot();
    ensure!(data.slot + 1 == state_slot, Error::<P>::PayloadAttestationNotForPreviousSlot { ... });
    let indexed_payload_attestation = get_indexed_payload_attestation(state, payload_attestation)?;
    validate_constructed_indexed_payload_attestation(
        config, pubkey_cache, state, &indexed_payload_attestation, verifier,
    )
}
```

Spec-conformant on the parent-root and slot predicates.

**`get_indexed_payload_attestation`** at `vendor/grandine/helper_functions/src/accessors.rs:1144-1165`:

```rust
pub fn get_indexed_payload_attestation<P: Preset>(...) -> Result<IndexedPayloadAttestation<P>> {
    let ptc = get_ptc(state, payload_attestation.data.slot)?;
    let mut attesting_indices =
        ContiguousList::try_from_iter(ptc.into_iter().zip(0..).filter_map(|(index, i)| {
            payload_attestation.aggregation_bits.get(i)
                .and_then(|is_true| is_true.then_some(index))
        }))?;
    // Sorting a slice is faster than building a `BTreeMap`.
    attesting_indices.sort_unstable();
    ...
}
```

Spec-conformant.

**`validate_constructed_indexed_payload_attestation`** + helper at `vendor/grandine/helper_functions/src/predicates.rs:459-521`:

```rust
pub fn validate_constructed_indexed_payload_attestation<P: Preset>(...) -> Result<()> {
    validate_indexed_payload_attestation(config, pubkey_cache, state, attestation, verifier, false)
    //                                                                                       ^^^^^
    //                                                                          validate_indices_sorted
}

pub fn validate_received_indexed_payload_attestation<P: Preset>(...) -> Result<()> {
    validate_indexed_payload_attestation(config, pubkey_cache, state, attestation, verifier, true)
}

fn validate_indexed_payload_attestation<P: Preset>(...) -> Result<()> {
    ensure!(!attestation.attesting_indices.is_empty(), Error::AttestationHasNoAttestingIndices);
    if validate_indices_sorted {
        ensure!(attestation.attesting_indices.is_sorted(), Error::AttestingIndicesNotSortedAndUnique);
    }
    // > Verify aggregate signature
    ...
}
```

**Literal-vs-functional deviation (H7).** The block-processing path takes the `constructed` branch and **skips the sortedness re-check**. The spec literally re-checks sortedness in `is_valid_indexed_payload_attestation`. Grandine's design recognizes that:

1. `get_indexed_payload_attestation` always sorts before constructing the indexed attestation (line 1158 `sort_unstable`).
2. Therefore the sortedness re-check is redundant on the block-processing path (one cannot construct an unsorted indexed attestation via `get_indexed_payload_attestation`).
3. The `received` path (gossip-pool input where the indexed attestation arrives externally) does perform the re-check.

This is **functionally equivalent to the spec** on all reachable block-processing inputs. The only behavior difference would be if some other call site bypassed `get_indexed_payload_attestation` and constructed an `IndexedPayloadAttestation` with unsorted indices, then routed it through `validate_constructed_*`. No such bypass exists in the codebase (verified by grep — only two call sites of `validate_constructed_indexed_payload_attestation`: `block_processing.rs:1268` and `state_transition.rs:201`, both downstream of `get_indexed_payload_attestation`). Cannot diverge.

**`get_ptc`** at `accessors.rs:1123-1142`: cached lookup via `state.ptc_window().get(index)` with index matching spec. Out-of-range guard.

**`compute_balance_weighted_selection`** + the `compute_ptc` helper that wraps it: at `accessors.rs:1093+` (preceding `get_ptc`). Spec-conformant: builds concatenated committees, hashes seed + slot via `hashing::hash_256_64(seed, slot)`, calls `compute_balance_weighted_selection(..., shuffle_indices=false)`.

## Cross-reference table

| Client | `process_payload_attestation` | `get_indexed_payload_attestation` | `is_valid_indexed_payload_attestation` | Sortedness re-check on block path | `state.ptc_window` cache |
|---|---|---|---|---|---|
| prysm | `payload_attestation.go:47` | `payload_attestation.go:84` (`slices.Sort`) | `payload_attestation.go:296` (`slices.IsSorted`, allows dups) | YES | NO (on-demand `PayloadCommitteeReadOnly`) |
| lighthouse | `verify_payload_attestation.rs:8` | `get_payload_attesting_indices.rs:10` (`sort_unstable`) | `is_valid_indexed_payload_attestation.rs:6` (`is_sorted()`, allows dups) | YES | YES (`beacon_state.rs:3159`) |
| teku | `BlockProcessorGloas.java:439` | `BeaconStateAccessorsGloas.java:165` (`IntStream.sorted()`) | `AttestationUtilGloas.java:52` (`Comparators.isInOrder`, allows dups) | YES | YES (`getPtcWindow()`) |
| nimbus | `state_transition_block.nim:804` | `beaconstate.nim:3214` (`.sort()`) | `beaconstate.nim:3236` (`isSorted`, allows dups) | YES (docstring says "unique" — code does not enforce; cosmetic drift) | YES (`state.ptc_window`) |
| lodestar | `processPayloadAttestation.ts:6` | `epochCache.ts:1050` (sorted post-filter) | `isValidIndexedPayloadAttestation.ts:6` (`arr[i-1] <= val`, allows dups) | YES | YES (epoch cache `getPtcWindowEpochCacheData`) |
| grandine | `block_processing.rs:1236` | `accessors.rs:1144` (`sort_unstable`) | `predicates.rs:481` (`is_sorted()`, allows dups — but **skipped** on block path) | **NO** (constructed-path optimization) | YES (`state.ptc_window()`) |

All clients use `DOMAIN_PTC_ATTESTER = 0x0C000000` and BLS `FastAggregateVerify`. All clients derive the seed identically: `hash(get_seed(state, epoch, DOMAIN_PTC_ATTESTER) ++ uint_to_bytes(slot))` (40-byte preimage).

## Empirical tests

No dedicated EF Gloas spec fixtures exercise `process_payload_attestation` in isolation (only via block processing). Source review is the primary evidence; suggested empirical fixtures below for future cross-corpus runs.

### Suggested fuzzing vectors

- **T1.1 (canonical PTC attestation).** Validators selected for the current slot's PTC sign a `PayloadAttestation` with the correct parent-root and slot binding. Expected: `is_valid_indexed_payload_attestation` returns true; block processes without error across all 6 clients.
- **T1.2 (duplicate indices, valid signature).** Aggregation bits select a validator that appears twice in the PTC (possible per `compute_ptc` "with possible duplicates"). Expected: sortedness check accepts `[5, 5, 7]`; signature aggregates `[pubkey_5, pubkey_5, pubkey_7]` correctly. **Cross-client agreement key check.**
- **T2.1 (unsorted indices, gossip-receive path).** Externally-constructed `IndexedPayloadAttestation` with indices `[7, 5, 5]`. Expected: rejected. **Tests grandine's `validate_received_indexed_payload_attestation` path explicitly.**
- **T2.2 (unsorted indices, block-processing path).** Cannot reach via legitimate construction; would require bypassing `get_indexed_payload_attestation`. **Confirms grandine's literal-vs-functional deviation has no reachable input.**
- **T2.3 (wrong parent-root).** `data.beacon_block_root != state.latest_block_header.parent_root`. Expected: rejected.
- **T2.4 (wrong slot binding).** `data.slot + 1 != state.slot`. Expected: rejected.
- **T2.5 (empty indices).** `attesting_indices = []`. Expected: rejected.
- **T2.6 (PTC-membership boundary).** Validator not in `state.ptc_window[slot_offset]` but somehow appears in `attesting_indices`. Cannot happen via `get_indexed_payload_attestation` (which filters by PTC); requires gossip-receive path bypass.

## Conclusion

All six clients implement `compute_ptc`, `get_ptc`, `get_indexed_payload_attestation`, `is_valid_indexed_payload_attestation`, and `process_payload_attestation` consistently and spec-conformantly. H1–H6 all verified. H7 (sortedness re-check optimization) holds: grandine's block-processing path skips the redundant check; functionally equivalent to spec under all reachable inputs.

**Verdict: impact none.** No divergence. The only finding worth surfacing upstream is the **nimbus docstring drift** (says "unique" but code only enforces sortedness; spec allows duplicates per `compute_ptc` "with possible duplicates"); cosmetic, not behavioral. Item closed.

## Cross-cuts

### With item #13 H10 (`process_operations` Gloas dispatcher)

Item #13 H10 closed the dispatcher: `process_operations` at Gloas dispatches `for_ops(body.payload_attestations, process_payload_attestation)`. This item is the predicate-level audit of `process_payload_attestation` (the per-element handler). Confirmed: the dispatcher → predicate chain is uniform across all 6 clients.

### With item #59 (envelope verification)

Item #59 audited `verify_execution_payload_envelope`. Both predicates feed `state.execution_payload_availability` semantics indirectly (PTC votes drive availability; envelope arrival drives availability). No direct ordering coupling at the predicate level.

### With item #7 H9 (`process_attestation` `data.index < 2`)

Item #7's `data.index < 2` payload-availability signal in regular attestations is parallel to (but distinct from) PTC attestations. PTC is the dedicated committee; regular attestations also vote indirectly via the `data.index` field. Two-channel availability voting confirmed uniform across all 6 clients.

### With `process_ptc_window` (Gloas-new epoch helper) — adjacent untouched

Sibling epoch helper that rotates `state.ptc_window` (analog to `process_builder_pending_payments` rotating `state.builder_pending_payments`). Audit-worthy as its own item; this item closed at the read side.

### With `compute_balance_weighted_selection` (triple-call helper) — adjacent untouched

`compute_proposer_indices`, `compute_ptc`, and item #27's sync-committee selection all use `compute_balance_weighted_selection`. Cross-cut audit candidate on the helper.

## Adjacent untouched

1. **`process_ptc_window`** (Gloas-new epoch helper) — sister audit.
2. **`compute_balance_weighted_selection` consistency across 3 call sites** — proposer, PTC, sync-committee.
3. **PTC duty publication path** — when does the BN tell its VC "you are in PTC for slot N"? VC-side cross-client audit.
4. **PTC vs regular attestation aggregation overlap** — single-validator-in-both case (same validator selected for both regular committee and PTC for the same slot).
5. **Gossip-pool `payload_attestation` topic** — subscription policy + signature-validation routing (which `validate_*` variant is invoked from gossip vs from block processing).
6. **Grandine `validate_received_indexed_payload_attestation` call sites** — confirmed used only by gossip-pool paths (no block-processing reach). Cross-corpus check on the routing.
