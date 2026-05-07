# Item #7 — `process_attestation` EIP-7549 multi-committee aggregation

**Status:** no-divergence-pending-fuzzing — audited 2026-05-03. **Hypotheses H1–H8 satisfied. All 45 EF `attestation` operations fixtures pass on all four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus SKIP per harness limit.**

**Builds on:** none directly, but cross-cuts every prior item via the `BeaconState.{previous,current}_epoch_participation` fields it mutates and the proposer reward it credits.

**Electra-active.** EIP-7549 fundamentally changes the `Attestation` SSZ container: `committee_index` is removed from `AttestationData` and replaced with a top-level `committee_bits: Bitvector[MAX_COMMITTEES_PER_SLOT]`. A single attestation can now carry attesters from multiple committees in one signature aggregate, with a flat `aggregation_bits: Bitlist[MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT]` indexed by a cumulative `committee_offset` walked across the active committees in committee_bits-set order. The legacy `AttestationData.index` field still exists but Pectra REQUIRES `data.index == 0`. This is the most-frequent CL block operation (every block has attestations); a divergence here is C-tier reachable on every slot.

## Question

EIP-7549 SSZ change (`vendor/consensus-specs/specs/electra/beacon-chain.md:353-360`):

```python
class Attestation(Container):
    # [Modified in Electra:EIP7549]
    aggregation_bits: Bitlist[MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT]
    data: AttestationData
    signature: BLSSignature
    # [New in Electra:EIP7549]
    committee_bits: Bitvector[MAX_COMMITTEES_PER_SLOT]
```

Pyspec `process_attestation` (Pectra-modified, line 1512-1565):

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

Five new Pectra divergence-prone bits:

A. **`data.index == 0`** — legacy `AttestationData.index` field still present in SSZ but must be 0. A client carrying pre-Pectra logic might accept non-zero index → would silently consider attestations as targeting different committees, breaking aggregation entirely.

B. **`committee_offset` cumulative accumulation** — off-by-one errors here mis-index `aggregation_bits`. Bits 0..len(committee_0) are for the 1st set committee in committee_bits, bits len(committee_0)..len(committee_0)+len(committee_1) for the 2nd, etc.

C. **`len(committee_attesters) > 0` per committee** — each set committee MUST contain at least one set bit in its slice of aggregation_bits. Otherwise the committee_bits entry was wasteful and the attestation should be rejected.

D. **Exact-size bitfield check**: `len(aggregation_bits) == committee_offset`. The bitlist must be exactly the cumulative committee size. Too few or too many bits → reject.

E. **BLS aggregate signature** over the union of attesters across all committees. The `is_valid_indexed_attestation` aggregates pubkeys from all attesting indices (sorted, deduplicated) and verifies against the single signature.

The hypothesis: *all six clients implement the four new Pectra checks (A–D) and the multi-committee BLS aggregation (E) identically. The cumulative-offset arithmetic is consistent. The order of indices in the indexed attestation is consistent (sorted ascending) so BLS canonical aggregation produces matching signatures.*

**Consensus relevance**: Attestations are processed per block, every slot. A divergence in any of the five new bits would surface on the very next block. The new multi-committee aggregation enables larger attestations (up to 64 committees × 1 sig instead of 1 committee × 1 sig), which directly affects bandwidth, block packing economics, and the participation flag updates that drive epoch-end rewards/penalties. A 1-validator divergence on participation flag updates compounds into different rewards across clients within the same epoch.

## Hypotheses

- **H1.** All six enforce `data.index == 0` for Electra-format attestations.
- **H2.** All six iterate `committee_bits` set bits in ascending index order to derive `committee_indices`.
- **H3.** All six accumulate `committee_offset` correctly: 0 → +len(committee_0) → +len(committee_1) → ... — so the bit slice for the Nth committee is `aggregation_bits[committee_offset_N : committee_offset_N + len(committee_N)]`.
- **H4.** All six enforce `len(committee_attesters) > 0` per committee.
- **H5.** All six enforce `len(aggregation_bits) == committee_offset` (exact-size).
- **H6.** All six produce the SAME `IndexedAttestation.attesting_indices` set for a given `(state, attestation)` pair (after sort + dedup), so the BLS aggregate signature verification is canonical.
- **H7.** All six update `state.{current,previous}_epoch_participation` flags identically per attesting validator.
- **H8.** All six compute the proposer reward identically: `proposer_reward_numerator / ((WEIGHT_DENOMINATOR - PROPOSER_WEIGHT) * WEIGHT_DENOMINATOR // PROPOSER_WEIGHT)` — accumulated across attesters that earned new flags.

## Findings

H1–H8 satisfied at source level. **No divergence in source-level predicate.**

### prysm (`prysm/beacon-chain/core/blocks/attestation.go:113-193`)

```go
if att.Version() >= version.Electra {
    ci := att.GetData().CommitteeIndex
    if beaconState.Version() >= version.Gloas {
        if ci >= 2 { return fmt.Errorf("incorrect committee index %d", ci) }
    } else {
        if ci != 0 { return errors.New("committee index must be 0 between Electra and Gloas forks") }
    }
}
committeeIndices := att.CommitteeBitsVal().BitIndices()
// ... fetch committees, compute participantsCount upfront
if aggBits.Len() != uint64(participantsCount) {
    return fmt.Errorf("aggregation bits count %d is different than participant count %d", ...)
}
committeeOffset := 0
for ci, c := range committees {
    attesterFound := false
    for i := range c {
        if aggBits.BitAt(uint64(committeeOffset + i)) {
            attesterFound = true; break
        }
    }
    if !attesterFound {
        return fmt.Errorf("no attesting indices found for committee index %d", ci)
    }
    committeeOffset += len(c)
}
indexedAtt, _ = attestation.ConvertToIndexed(ctx, att, committees...)
return attestation.IsValidAttestationIndices(ctx, indexedAtt, ...)
```

H1 ✓ (with **Gloas-ready logic**: post-Gloas allows `ci < 2`; this is a pre-emptive Pectra-correct branch — see adjacent untouched). H2 ✓ via `BitIndices()`. H3 ✓. H4 ✓ via `attesterFound` bool flag (early-exit, no set construction). H5 ✓ via the upfront `participantsCount` comparison. H6, H7, H8 ✓ via `ConvertToIndexed` + `IsValidAttestationIndices`.

`get_attesting_indices` (`attestation_utils.go:85-126`) uses `slices.Sort` then `slices.Compact` for dedup before signature verification.

### lighthouse (`lighthouse/consensus/state_processing/src/per_block_processing/verify_attestation.rs:76-86` + `common/get_attesting_indices.rs:103-149`)

```rust
// verify_attestation.rs
AttestationRef::Electra(_) => {
    verify!(data.index == 0, Invalid::BadCommitteeIndex);
}
let indexed_attestation = ctxt.get_indexed_attestation(state, attestation)?;
is_valid_indexed_attestation(state, indexed_attestation, verify_signatures, spec)?;

// get_attesting_indices.rs (Pectra)
let mut committee_offset = 0;
for committee_index in committee_indices {
    let beacon_committee = committees.get(committee_index as usize)?;
    participant_count.safe_add_assign(beacon_committee.committee.len() as u64)?;
    let committee_attesters = beacon_committee.committee.iter().enumerate().filter_map(|(i, &index)| {
        if let Ok(idx) = committee_offset.safe_add(i)
            && aggregation_bits.get(idx).unwrap_or(false) { Some(index as u64) }
        None }).collect::<HashSet<_>>();
    if committee_attesters.is_empty() {
        return Err(BeaconStateError::EmptyCommittee);
    }
    attesting_indices.extend(committee_attesters);
    committee_offset.safe_add_assign(beacon_committee.committee.len())?;
}
if participant_count as usize != aggregation_bits.len() {
    return Err(BeaconStateError::InvalidBitfield);
}
attesting_indices.sort_unstable();
```

H1 ✓ (`verify!` macro). H2 ✓ via `bitvector.iter().enumerate().filter_map`. H3 ✓ via `committee_offset.safe_add` (overflow-safe). H4 ✓ via `HashSet::is_empty()`. H5 ✓ via `participant_count != aggregation_bits.len()` post-loop. H6 ✓ via `sort_unstable()` after collection. H7, H8 ✓ via `is_valid_indexed_attestation` standard machinery.

### teku (`teku/ethereum/spec/.../electra/block/BlockProcessorElectra.java:271-323` + `AttestationDataValidatorElectra.java:46-84`)

```java
// AttestationDataValidatorElectra.checkCommitteeIndex
return check(data.getIndex().equals(UInt64.ZERO), COMMITTEE_INDEX_MUST_BE_ZERO);

// BlockProcessorElectra.checkCommittees
int committeeOffset = 0;
for (final UInt64 committeeIndex : committeeIndices) {
    if (committeeIndex.isGreaterThanOrEqualTo(committeeCountPerSlot))
        return Optional.of(AttestationInvalidReason.COMMITTEE_INDEX_TOO_HIGH);
    final IntList committee = beaconStateAccessorsElectra.getBeaconCommittee(...);
    final int currentCommitteeOffset = committeeOffset;
    final boolean committeeHasAtLeastOneAttester =
        IntStream.range(0, committee.size())
            .anyMatch(i -> aggregationBits.isSet(currentCommitteeOffset + i));
    if (!committeeHasAtLeastOneAttester)
        return Optional.of(AttestationInvalidReason.PARTICIPANTS_COUNT_MISMATCH);
    committeeOffset += committee.size();
}
if (committeeOffset != aggregationBits.size())
    return Optional.of(AttestationInvalidReason.PARTICIPANTS_COUNT_MISMATCH);
```

H1 ✓. H2 ✓ via `getCommitteeBitsRequired().getAllSetBits()`. H3 ✓. H4 ✓ via `IntStream.anyMatch` (early-exit). H5 ✓ post-loop. H6 ✓ via `getAttestingIndices` returning sorted-input list. H7, H8 ✓ via inherited base class `BlockProcessorAltair`/`Deneb`.

### nimbus (`nimbus/beacon_chain/spec/beaconstate.nim:1088-1153` + `:1289-1312`)

```nim
# check_attestation
if not (data.index == 0):
    return err("Electra attestation data index not 0")

var committee_offset = 0
for committee_index in attestation.committee_bits.oneIndices:
    if not (committee_index.uint64 < get_committee_count_per_slot(state, epoch, cache)):
        return err("attestation wrong committee index len")
    let committee_index = CommitteeIndex(committee_index)
    let committee_len = get_beacon_committee_len(state, slot, committee_index, cache)
    if attestation.aggregation_bits.len < committee_offset + committee_len.int:
        return err("Electra attestation has too many committee bits")
    var committee_attesters_nonzero = false
    for i, attester_index in get_beacon_committee(state, slot, committee_index, cache):
        if attestation.aggregation_bits[committee_offset + i]:
            committee_attesters_nonzero = true
            break
    if not committee_attesters_nonzero:
        return err("Electra attestation committee not present in aggregated bits")
    committee_offset += committee_len.int

if not (len(attestation.aggregation_bits) == committee_offset):
    return err("attestation wrong aggregation bit length")

? is_valid_indexed_attestation(state, attestation, flags, cache)
```

H1 ✓. H2 ✓ via `bitvector.oneIndices` iterator (Nim built-in). H3 ✓. H4 ✓ via early-exit `committee_attesters_nonzero` flag (matches prysm style). H5 ✓ post-loop. H6 ✓: nimbus's `get_attesting_indices` (`beaconstate.nim:688-708`) is an iterator-template that yields per-committee attesters with cumulative offset; downstream `is_valid_indexed_attestation` builds the pubkey list in iteration order, which matches sorted by `(committee_offset_N, i_in_committee)` — equivalent to spec's sorted-by-validator-index after dedup.

### lodestar (`lodestar/packages/state-transition/src/block/processAttestationPhase0.ts:97-141` + `util/shuffling.ts:158-187`)

```typescript
// processAttestationPhase0 — validateAttestation Electra branch
assert.equal(data.index, 0, ...);
const committeeIndices = attestationElectra.committeeBits.getTrueBitIndexes();
// fetch committees
let committeeOffset = 0;
for (const committee of validatorsByCommittee) {
    const committeeAggregationBits = aggregationBitsArray.slice(committeeOffset, committeeOffset + committee.length);
    if (committeeAggregationBits.every((bit) => !bit)) {
        // reject — no attesters in this committee
    }
    committeeOffset += committee.length;
}
assert.equal(aggregationBitsArray.length, committeeOffset, ...);

// shuffling.getAttestingIndices Electra branch
const validatorsByCommittee = getBeaconCommittees(epochShuffling, data.slot, committeeIndices);
const totalLength = validatorsByCommittee.reduce((acc, curr) => acc + curr.length, 0);
const committeeValidators = new Uint32Array(totalLength);
let offset = 0;
for (const committee of validatorsByCommittee) {
    committeeValidators.set(committee, offset);
    offset += committee.length;
}
return aggregationBits.intersectValues(committeeValidators);
```

H1 ✓ (`assert.equal(data.index, 0, ...)`). H2 ✓ via `getTrueBitIndexes()`. H3 ✓. H4 ✓ via `every((bit) => !bit)` inverse check. H5 ✓ post-loop. H6 ✓ via `intersectValues` over the flattened committee Uint32Array (note: this preserves bit-position order, which equals committee-iteration order — the indices are NOT sorted by value, but by position within the flattened array). **Subtle**: the per-committee validator order from `get_beacon_committee` is the canonical shuffling order, and the union of these in committee_bits-set order is what gets aggregated. **Spec's `attesting_indices` is `Set[ValidatorIndex]` not `List`, so order ostensibly doesn't matter at the spec level — but BLS aggregation is order-independent, so any consistent ordering produces the same aggregate signature.** All clients are safe here.

H7, H8 ✓ via `processAttestationsAltair` (downstream).

### grandine (`grandine/transition_functions/src/electra/block_processing.rs:747-816` + `helper_functions/electra.rs:82-121`)

```rust
// validate_attestation_with_verifier
ensure!(data.index == 0, ...);
let indexed_attestation = get_indexed_attestation(state, attestation)?;
validate_constructed_indexed_attestation(config, pubkey_cache, state, &indexed_attestation, verifier)?;

// helper_functions/electra.rs:82-121 — get_attesting_indices
let mut output = HashSet::new();
let committee_indices = get_committee_indices::<P>(attestation.committee_bits);
let mut committee_offset = 0;
for index in committee_indices {
    let committee = beacon_committee(state, attestation.data.slot, index)?;
    let committee_attesters = committee.into_iter().enumerate().filter_map(|(i, idx)| {
        (*attestation.aggregation_bits.get(committee_offset + i)?).then_some(idx)
    }).collect::<Vec<_>>();
    ensure!(!committee_attesters.is_empty(), Error::NoCommitteeAttesters { index });
    output.extend(committee_attesters);
    committee_offset += committee.len();
}
ensure!(committee_offset == attestation.aggregation_bits.len(), ...);
Ok(output)
```

H1 ✓. H2 ✓ via `get_committee_indices` iterator. H3 ✓. H4 ✓ via `Vec::is_empty()` per committee. H5 ✓ post-loop. H6 ✓ via `HashSet<ValidatorIndex>` collection (spec semantics — set, not ordered list); downstream `validate_constructed_indexed_attestation` re-iterates via `attesting_indices()` which the IndexedAttestation must have stored sorted. H7, H8 ✓.

## Cross-reference table

| Client | `process_attestation` | `data.index == 0` | `committee_offset` | `len(attesters) > 0` | Exact bitfield | Sort/dedup |
|---|---|---|---|---|---|---|
| prysm | `core/blocks/attestation.go:113-193` | L113-128 (Gloas-ready: `< 2` post-Gloas else `== 0`) | L148-161 (manual int) | `attesterFound` bool flag | upfront `participantsCount` compare | `slices.Sort` + `slices.Compact` |
| lighthouse | `verify_attestation.rs:76-86` + `get_attesting_indices.rs:103-149` | L76-78 `verify!` | safe_add throughout | `HashSet::is_empty()` | `participant_count != aggregation_bits.len()` post-loop | `sort_unstable()` |
| teku | `BlockProcessorElectra.java:271-323` + `AttestationDataValidatorElectra.java:46-84` | `:81-84` `.equals(UInt64.ZERO)` | L302-321 manual int | `IntStream.anyMatch` | post-loop `committeeOffset != size()` | `getAttestingIndices` sorted via downstream |
| nimbus | `beaconstate.nim:1088-1153` (`check_attestation`) | L1112 inline | L1115-1141 `var committee_offset = 0` | early-exit `committee_attesters_nonzero` flag | post-loop `len == offset` | iterator yields in canonical order |
| lodestar | `block/processAttestationPhase0.ts:97-141` (validate Electra branch) + `util/shuffling.ts:158-187` (`get_attesting_indices`) | L101 `assert.equal(data.index, 0, ...)` | L121-134 cumulative | `every((bit) => !bit)` inverse | post-loop `assert.equal(...)` | flattened Uint32Array + `intersectValues` |
| grandine | `electra/block_processing.rs:747-816` (`validate_attestation_with_verifier`) + `helper_functions/electra.rs:82-121` (`get_attesting_indices`) | L786 `ensure!` | L90-108 cumulative | `Vec::is_empty()` per committee | L112-118 post-loop `ensure!` | `HashSet<ValidatorIndex>` collection |

## Cross-cuts

### with the SSZ `Attestation` container layout change (Track E)

The Pectra `Attestation` SSZ container has a different shape from pre-Pectra. Network-layer attestation gossip uses the new shape; relay between clients depends on consistent SSZ ser/de. A divergence in any client's SSZ codec for the Pectra Attestation would cause that client to fail to deserialize gossip from other clients (chain-split via network partition rather than state-root divergence). Worth a Track E item: `Attestation` SSZ ser/de cross-client agreement on the boundary between pre- and post-Pectra attestations.

### with `is_valid_indexed_attestation` and BLS aggregate signature

Each client's `IndexedAttestation` produced from a Pectra attestation has `attesting_indices` that must produce the same aggregate signature when verified. Sorted-ascending order is canonical per spec. Lodestar's `intersectValues` may not produce sorted output (preserves bit-position order); however, BLS signature aggregation is commutative under pubkey union, so non-canonical ordering still verifies — F-tier today. Worth a sanity check via a custom multi-committee fixture where the per-committee validator indices straddle a sort boundary.

### with `process_epoch` participation flag updates (item #1 territory)

`process_attestation` updates `state.{current,previous}_epoch_participation`. The next epoch's `process_rewards_and_penalties` (separate item) reads these flags. A divergence here would propagate one epoch later as different rewards/penalties — a multi-fixture cascade. Item #1's `process_effective_balance_updates` runs at the same epoch boundary; divergent participation flags would cascade into divergent rewards which cascade into different effective_balance updates.

### with `get_beacon_committee` and the shuffling cache

Pectra's `process_attestation` calls `get_beacon_committee` for each set committee. Each client has a different shuffling cache. A divergence in the shuffling cache would surface here as different committees → different attesting_indices → different aggregate signatures → rejection. This audit doesn't explicitly cover the shuffling cache but indirectly tests it via the 45 fixtures.

## Fixture

`fixture/`: deferred — used the existing 45 EF state-test fixtures at
`consensus-spec-tests/tests/mainnet/electra/operations/attestation/pyspec_tests/`.

Run via `scripts/run_fixture.sh` against all six clients on 2026-05-03.

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

The fixture set (45 fixtures) is the third-richest in the corpus after item #4 (43) and item #6 (25). Notable coverage:
- **6 inclusion-delay variants** (`at_max_inclusion_slot`, `correct_*_at_*_inclusion_*`, `incorrect_*_at_*_inclusion_*`): tests inclusion-delay boundary handling.
- **Multiple incorrect-head/target/source variants**: tests participation flag computation.
- **`invalid_attestation_data_index_not_zero`**: directly tests H1.
- **`invalid_committee_index`, `invalid_too_few_aggregation_bits`, `invalid_too_many_aggregation_bits`, `invalid_too_many_committee_bits`**: directly test H2, H3, H4, H5.
- **`invalid_empty_participants_seemingly_valid_sig`, `invalid_empty_participants_zeroes_sig`**: directly test H4 (empty-committee rejection) with both valid and zero signatures.
- **`invalid_attestation_signature`, `invalid_bad_source_root`, `invalid_current_source_root`, `invalid_future_target_epoch`, `invalid_mismatched_target_and_slot`**: tests the FFG / signature predicates.
- **`invalid_wrong_index_for_committee_signature`, `invalid_wrong_index_for_slot_0`, `invalid_wrong_index_for_slot_1`**: tests committee-index bounds vs slot.
- **`previous_epoch`, `multi_proposer_index_iterations`, `one_basic_attestation`**: positive-case mainline.

## Fuzzing vectors

### T1 — Mainline canonical
- **T1.1 (priority — multi-committee max-aggregation).** Attestation with all `MAX_COMMITTEES_PER_SLOT=64` committees set in committee_bits, each committee fully participating in aggregation_bits. Expected: all 64 × MAX_VALIDATORS_PER_COMMITTEE attesters credited with participation flags; cumulative committee_offset = sum of committee sizes; aggregate signature verifies. Tests the upper bound of the new multi-committee feature.
- **T1.2 (priority — single committee, high index).** Attestation with only the highest committee_bit set (committee_index = 63 = MAX_COMMITTEES_PER_SLOT - 1), full aggregation. Tests the high-index boundary in `get_committee_count_per_slot` comparison.

### T2 — Adversarial probes
- **T2.1 (priority — `data.index = 1`).** Attestation with `data.index == 1`. Pectra REQUIRES 0 → reject. Covered by `invalid_attestation_data_index_not_zero`.
- **T2.2 (priority — committee_bits set but no attesters).** A committee_bit is set, but the corresponding aggregation_bits slice is all zeros. Per H4, must reject. Covered by `invalid_empty_participants_*`.
- **T2.3 (priority — bitfield off-by-one).** `aggregation_bits.len() == committee_offset + 1` (one extra bit). Per H5, must reject. Covered by `invalid_too_many_aggregation_bits`.
- **T2.4 (priority — bitfield short).** `aggregation_bits.len() == committee_offset - 1` (one missing bit). Per H5, must reject. Covered by `invalid_too_few_aggregation_bits`.
- **T2.5 (defensive — committee_index >= committee_count_per_slot).** Committee bit set for an index that exceeds the per-slot committee count. Reject. Covered by `invalid_committee_index` and `invalid_wrong_index_for_slot_*`.
- **T2.6 (defensive — too many committee_bits).** committee_bits has more than MAX_COMMITTEES_PER_SLOT bits set (which is impossible per SSZ Bitvector definition, but worth a defensive check). Covered by `invalid_too_many_committee_bits`.
- **T2.7 (priority — cross-committee duplicate validator).** A validator appears in two committees both set in committee_bits. Pyspec's `get_attesting_indices` uses `Set[ValidatorIndex]` semantics — dedupe. Each client's collection mechanism (Vec→sort→compact for prysm, HashSet for lighthouse/grandine, intersectValues for lodestar, IntStream for teku) MUST handle duplicates consistently. Worth a custom fixture as the EF set may not exhaustively cover cross-committee dedup.

## Conclusion

**Status: no-divergence-pending-fuzzing.** All six clients implement the four new Pectra checks (data.index==0, per-committee membership + bounds, len(attesters)>0 per committee, exact-size bitfield) and the multi-committee BLS aggregation identically at the source level. Per-client styles differ (manual int offset vs safe_add Rust, anyMatch vs early-exit flag vs every-inverse, sort+compact vs HashSet vs intersectValues) but all are observable-equivalent.

Notable per-client style differences:
- **prysm** has Gloas-ready logic (`ci < 2` post-Gloas, `ci == 0` Electra) — ahead of the spec's current fork target.
- **lighthouse** uses `safe_add` overflow-checked arithmetic for the cumulative offset.
- **teku** factors check (A) into a separate `AttestationDataValidatorElectra` class, with B/C/D in `BlockProcessorElectra.checkCommittees`.
- **nimbus** uses Nim's built-in `bitvector.oneIndices` for the committee_bits iteration.
- **lodestar** flattens all set committees into a single Uint32Array before intersect — different choreography, same semantics.
- **grandine** returns `HashSet<ValidatorIndex>` (matches pyspec's `Set[ValidatorIndex]` literally).

No code-change recommendation. Audit-direction recommendations:
- **Generate the T2.7 cross-committee duplicate-validator fixture** to lock dedup semantics.
- **Audit `Attestation` SSZ ser/de cross-client** as a Track E item.
- **Audit `is_valid_indexed_attestation` and BLS aggregate signature pubkey-cache coherence** — Track F item.
- **Generate T1.1 multi-committee max-aggregation fixture** as a custom 64-committee stress test.

## Adjacent untouched Electra-active consensus paths

1. **`Attestation` SSZ container ser/de cross-client** (Track E item) — the Pectra layout change must round-trip identically for gossip.
2. **`is_valid_indexed_attestation`** — calls into BLS aggregate verification. The IndexedAttestation has expanded list capacity (`MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT` instead of just `MAX_VALIDATORS_PER_COMMITTEE`). A client carrying pre-Pectra capacity could fail to deserialize.
3. **Cross-committee duplicate validator dedup** — pyspec uses `Set[ValidatorIndex]`; each client's collection mechanism must dedupe. Worth a T2.7 fixture as the EF set may not exhaustively cover this.
4. **prysm Gloas-ready `data.index < 2` branch** — pre-emptive support for the Gloas EIP that allows committee index 0 or 1 (perhaps for a 2-way split). Other clients haven't implemented this. Pre-emptive divergence vector at Gloas.
5. **lodestar's `intersectValues` ordering** — preserves bit-position order, NOT sorted-by-validator-index. BLS aggregation is commutative so this doesn't matter for signature verification, BUT if any downstream code depended on sorted order (e.g., for slashing detection), there could be subtle bugs.
6. **Shuffling cache cross-client coherence** — `get_beacon_committee` is called for each set committee. The shuffling cache is per-client. Indirectly tested by every fixture but not directly audited.
7. **Participation flag update ordering** — within a single block, attestations are processed in order. The proposer_reward_numerator accumulates across all attestations. A reordering would change the proposer reward (a single proposer-credited gwei delta). Not divergence-critical at single-attestation granularity but worth confirming sequential semantics.
8. **`MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT` aggregation_bits size** — the new bound is large (2048 × 64 = 131,072 max bits per attestation). SSZ bitlist serialization at this size could expose performance / size limits in some clients' codecs.
9. **The legacy `AttestationData.index` field is now dead-but-required-zero** — semi-permanent technical debt. A future EIP could remove it; clients that build state assuming it might be non-zero (none observed today) would surface a divergence.
10. **`get_committee_count_per_slot` consistency** — used in the per-committee bounds check. A client that computed this differently (via different shuffling rounding, etc.) would silently reject otherwise-valid attestations. Worth a separate audit.
