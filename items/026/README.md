---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [7, 8, 25]
eips: [EIP-7549, EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 26: `get_attesting_indices` + `get_committee_indices` (Pectra-MODIFIED + Pectra-NEW for EIP-7549 multi-committee aggregation)

## Summary

The two helper functions that convert Pectra's multi-committee `Attestation` into the flat attester-index set used by item #25's `is_valid_indexed_attestation` BLS aggregate verifier. `get_committee_indices(committee_bits)` returns the SET bit positions in `attestation.committee_bits` (ascending). `get_attesting_indices(state, attestation)` walks those committees with a cumulative `committee_offset` over the flat `aggregation_bits`, intersecting per-committee membership with the set bits.

**Pectra surface:** all six clients implement the multi-committee aggregation logic with identical observable behaviour on spec-conformant input. Six distinct dispatch idioms (proto `Version()` runtime, superstruct enum, subclass-override, Nim type-union, ForkSeq numeric, module-namespace). The carried-forward 3-vs-3 split on **explicit deduplication** is reaffirmed: prysm + lighthouse + grandine explicitly dedup (sort+compact, HashSet, HashSet); teku + nimbus + lodestar rely on the "unique by construction" invariant (committee shuffling guarantees each validator is in at most one committee per slot). All six produce observable-equivalent output on shuffling-conformant input; the 3-clients-skip-dedup family is forward-fragile to hypothetical future spec changes that allow cross-committee overlaps.

**Gloas surface (at the Glamsterdam target): both functions unchanged.** `vendor/consensus-specs/specs/gloas/beacon-chain.md` does not contain `Modified get_attesting_indices` nor `Modified get_committee_indices` headings; both functions are inherited verbatim from Electra. They are invoked from the Gloas-Modified `process_attestation` (`:1687 — committee_indices = get_committee_indices(attestation.committee_bits)`, `:1722 — for index in get_attesting_indices(state, attestation)`) — the call sites survive but the helpers themselves are unchanged. The `Attestation` container is NOT redefined at Gloas (Electra container reused; `committee_bits` field carries forward), `MAX_COMMITTEES_PER_SLOT = 64` unchanged, `MAX_VALIDATORS_PER_COMMITTEE` unchanged. All six clients reuse their Electra implementations at Gloas — same dispatch idioms, same dedup strategies.

**Gloas-Modified `process_attestation` impact**: the caller (item #7 surface) is modified at Gloas for EIP-7732 with new logic for `data.index < 2` constraint, `state.builder_pending_payments` weight accounting, and the "will_set_new_flag" same-slot-once tracking. None of those modifications touch THIS item's helpers. The helpers receive the unchanged Electra-shaped `Attestation` and produce the unchanged validator-index set.

**Item #22 H12 / item #23 H10 / item #24 cross-cut**: none of nimbus's stale-Gloas-spec divergences (items #22, #23) propagate to these helpers — they don't call `has_compounding_withdrawal_credential` nor `get_pending_balance_to_withdraw`. They use `get_beacon_committee` (phase0 helper, unchanged), `attestation.aggregation_bits` / `attestation.committee_bits` (Electra container fields, unchanged at Gloas), and `state.validators` (no credentials-byte access).

**Impact: none.** Ninth impact-none result in the recheck series. Propagation-without-amplification.

## Question

Pyspec Pectra-NEW + Pectra-Modified (`vendor/consensus-specs/specs/electra/beacon-chain.md:583-668`):

```python
def get_committee_indices(committee_bits: Bitvector) -> Sequence[CommitteeIndex]:
    """Return the indices for the set bits of ``committee_bits``."""
    return [CommitteeIndex(index) for index, bit in enumerate(committee_bits) if bit]


def get_attesting_indices(state: BeaconState, attestation: Attestation) -> Set[ValidatorIndex]:
    """
    Return the set of attesting indices corresponding to ``aggregation_bits`` and ``committee_bits``.
    """
    output: Set[ValidatorIndex] = set()
    committee_indices = get_committee_indices(attestation.committee_bits)
    committee_offset = 0
    for committee_index in committee_indices:
        committee = get_beacon_committee(state, attestation.data.slot, committee_index)
        committee_attesters = set(
            attester_index
            for i, attester_index in enumerate(committee)
            if attestation.aggregation_bits[committee_offset + i]
        )
        output = output.union(committee_attesters)
        committee_offset += len(committee)
    return output
```

At Gloas: same functions, called from `process_attestation` at `vendor/consensus-specs/specs/gloas/beacon-chain.md:1687` and `:1722`. No `Modified` heading.

Two recheck questions:
1. Pectra-surface invariants (H1–H8) — do all six clients still implement identical observable semantics with the carried-forward 3-vs-3 dedup divergence?
2. **At Gloas (the new target)**: any client modify the helper bodies, or introduce a Gloas-specific dispatch path?

## Hypotheses

- **H1.** `get_committee_indices` returns SET bit positions in `committee_bits` in ascending order.
- **H2.** `get_attesting_indices` iterates committees in ascending bit-position order of `committee_bits`.
- **H3.** `committee_offset` cumulative across committees (flat `aggregation_bits` indexed by `committee_offset + i`).
- **H4.** `aggregation_bits[committee_offset + i]` per-validator bit check.
- **H5.** `get_beacon_committee(state, attestation.data.slot, committee_index)` lookup per committee.
- **H6.** Result deduplication: pyspec uses `Set[ValidatorIndex]` (explicitly deduplicated). Three clients explicit (prysm, lighthouse, grandine); three rely on unique-by-construction (teku, nimbus, lodestar). All observable-equivalent on shuffling-conformant input.
- **H7.** Final result satisfies item #25's sorted+unique check (either via explicit sort or via "iterate committees in ascending order; each committee's indices are sorted in committee construction; cross-committee overlap impossible by shuffling invariant"). All six clients satisfy this in practice.
- **H8.** Per-fork dispatch: pre-Electra single-committee variant (with `attestation.data.index`) vs Electra+ multi-committee variant (with `committee_bits`).
- **H9.** *(Glamsterdam target — function bodies)*. `get_committee_indices` and `get_attesting_indices` are NOT modified at Gloas. No `Modified` heading in `vendor/consensus-specs/specs/gloas/beacon-chain.md`. The Electra implementations carry forward unchanged in all six clients.
- **H10.** *(Glamsterdam target — caller `process_attestation` modifications)*. Item #7's `process_attestation` IS Modified at Gloas (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1675-1751`) for EIP-7732 (data.index < 2 constraint, builder_pending_payments weight, will_set_new_flag tracking). But the modifications affect the caller logic, NOT this item's helpers — both `get_committee_indices` and `get_attesting_indices` are invoked unchanged from the modified caller.
- **H11.** *(Glamsterdam target — `Attestation` container)*. The `Attestation` container is NOT redefined at Gloas — Electra container reused. `committee_bits: Bitvector[MAX_COMMITTEES_PER_SLOT]` and `aggregation_bits: Bitlist[MAX_VALIDATORS_PER_COMMITTEE × MAX_COMMITTEES_PER_SLOT]` carry forward. Constants `MAX_COMMITTEES_PER_SLOT = 64` and `MAX_VALIDATORS_PER_COMMITTEE = 2048` unchanged at Gloas.
- **H12.** *(Glamsterdam target — cross-cut with nimbus items #22 / #23 / lighthouse #24)*. Neither helper invokes `has_compounding_withdrawal_credential` (item #22) nor `get_pending_balance_to_withdraw` (item #23) nor any function affected by the lighthouse Gloas-ePBS readiness gap (items #14/#19/#22/#23/#24 cohort). Nimbus's mainnet-everyone divergences and lighthouse's broader Gloas-readiness gap do NOT propagate to these helpers.

## Findings

H1–H12 satisfied. **No divergence at the function bodies or per-client implementations at either Pectra or Gloas surfaces.**

### prysm

`vendor/prysm/beacon-chain/core/helpers/beacon_committee.go:478-491 CommitteeIndices`:

```go
// CommitteeIndices return beacon committee indices corresponding to bits that are set on the argument bitfield.
func CommitteeIndices(committeeBits bitfield.Bitfield) []primitives.CommitteeIndex {
    indices := committeeBits.BitIndices()
    result := make([]primitives.CommitteeIndex, 0, len(indices))
    for _, idx := range indices {
        result = append(result, primitives.CommitteeIndex(idx))
    }
    return result
}
```

Uses `bitfield.BitIndices()` (returns set bit positions in ascending order).

`vendor/prysm/proto/prysm/v1alpha1/attestation/attestation_utils.go:85-126 AttestingIndices`:

```go
func AttestingIndices(att ethpb.Att, committees ...[]primitives.ValidatorIndex) ([]uint64, error) {
    // ... pre-Electra path at :260-284 (single committee) ...
    // Electra+ multi-committee path:
    var attesters []uint64
    committeeOffset := 0
    for cIdx, committee := range committees {
        committeeAttesters := make([]uint64, 0, len(committee))
        for i, vIdx := range committee {
            if att.GetAggregationBits().BitAt(uint64(committeeOffset + i)) {
                committeeAttesters = append(committeeAttesters, uint64(vIdx))
            }
        }
        if len(committeeAttesters) == 0 {
            return nil, fmt.Errorf("no attesters in committee %d", cIdx)
        }
        attesters = append(attesters, committeeAttesters...)
        committeeOffset += len(committee)
    }
    // Explicit dedup:
    slices.Sort(attesters)
    attesters = slices.Compact(attesters)
    return attesters, nil
}
```

Per-fork dispatch via `att.Version() < version.Electra` runtime check selecting `attestingIndicesPhase0` (single-committee, uses `attestation.data.committee_index`) vs the Electra+ multi-committee path. **Explicit deduplication** via Go 1.21+ `slices.Sort + slices.Compact` (sort then compact consecutive duplicates).

No Gloas-specific override — the Electra implementation is reused at Gloas via the `ethpb.Att` interface abstraction.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓ (explicit dedup). H7 ✓. H8 ✓. H9 ✓. H10 ✓ (`process_attestation` modified at Gloas but doesn't touch this helper). H11 ✓. H12 ✓.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/common/get_attesting_indices.rs:94-149` (Electra `get_attesting_indices`) + `:151-159` (`get_committee_indices`):

```rust
pub fn get_attesting_indices<E: EthSpec>(
    committees: &[BeaconCommittee],
    aggregation_bits: &BitList<E::MaxValidatorsPerSlot>,
    committee_bits: &BitVector<E::MaxCommitteesPerSlot>,
) -> Result<Vec<u64>, BeaconStateError> {
    let mut attesting_indices = vec![];
    let committee_indices = get_committee_indices::<E>(committee_bits);
    let mut committee_offset = 0;
    let committee_count_per_slot = committees.len() as u64;
    let mut participant_count = 0;
    for committee_index in committee_indices {
        let beacon_committee = committees.get(committee_index as usize)
            .ok_or(BeaconStateError::NoCommitteeFound(committee_index))?;
        if committee_index >= committee_count_per_slot {
            return Err(BeaconStateError::InvalidCommitteeIndex(committee_index));
        }
        participant_count.safe_add_assign(beacon_committee.committee.len() as u64)?;
        let committee_attesters = beacon_committee.committee.iter().enumerate()
            .filter_map(|(i, &index)| {
                if let Ok(aggregation_bit_index) = committee_offset.safe_add(i)
                    && aggregation_bits.get(aggregation_bit_index).unwrap_or(false)
                {
                    return Some(index as u64);
                }
                None
            })
            .collect::<HashSet<u64>>();
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
    Ok(attesting_indices)
}

pub fn get_committee_indices<E: EthSpec>(committee_bits: &BitVector<E::MaxCommitteesPerSlot>) -> Vec<CommitteeIndex> {
    committee_bits.iter().enumerate()
        .filter_map(|(index, bit)| if bit { Some(index as u64) } else { None })
        .collect()
}
```

`HashSet<u64>` per-committee + final `sort_unstable()` — explicit deduplication at two levels (per-committee inherent uniqueness + cross-committee uniqueness via HashSet, then sorted). Three Electra-process_attestation defensive checks woven in: (a) `committee_index >= committee_count_per_slot` rejection, (b) `committee_attesters.is_empty()` rejection, (c) `participant_count != aggregation_bits.len()` rejection.

Per-fork dispatch via superstruct `AttestationRef::{Base, Electra}` — no Gloas variant; Electra is reused at Gloas. No Gloas-specific helper. The lighthouse Gloas-ePBS gap (items #14/#19/#22/#23/#24) is upstream of this surface — these helpers are correct in isolation.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓ (HashSet per-committee + final sort). H7 ✓ (`sort_unstable`). H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/util/AttestationUtilElectra.java:70-92`:

```java
@Override
public List<UInt64> getAttestingIndices(final BeaconState state, final Attestation attestation) {
    final List<UInt64> committeeIndices = attestation.getCommitteeIndicesRequired();
    final IntList aggregationBits = bitSet(attestation.getAggregationBits()).toIntList();
    return streamCommitteeAttesters(state, attestation.getData().getSlot(), committeeIndices, aggregationBits).toList();
}

private Stream<UInt64> streamCommitteeAttesters(
    final BeaconState state, final UInt64 slot,
    final List<UInt64> committeeIndices, final IntList aggregationBits) {
    int committeeOffset = 0;
    final List<Stream<UInt64>> committeeAttesterStreams = new ArrayList<>();
    for (final UInt64 committeeIndex : committeeIndices) {
        final IntList committee = getBeaconCommittee(state, slot, committeeIndex);
        final int co = committeeOffset;
        committeeAttesterStreams.add(
            IntStream.range(0, committee.size())
                .filter(i -> aggregationBits.contains(co + i))
                .mapToObj(i -> UInt64.valueOf(committee.getInt(i))));
        committeeOffset += committee.size();
    }
    return committeeAttesterStreams.stream().flatMap(s -> s);
}
```

`AttestationElectra.getCommitteeIndicesRequired()` is the `getCommitteeIndices` analog (returns `List<UInt64>` of set bit positions via `committeeBits.getAllSetBits()`). Flat `aggregationBits` indexed by `co + i` per committee.

**No explicit deduplication** — `ArrayList<UInt64>` accumulator + `flatMap` join. Relies on "unique by construction" via shuffling. Same H6 stance as nimbus + lodestar.

Per-fork dispatch via subclass-override polymorphism: `AttestationUtilElectra extends AttestationUtilDeneb extends ... extends AttestationUtil`. `AttestationUtilGloas extends AttestationUtilElectra` (per item #25 audit) — does NOT override `getAttestingIndices`. The Electra impl is inherited at Gloas unchanged.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. **H6 ⚠️ unique-by-construction** (carried forward — observable-equivalent on shuffling-conformant input). H7 ✓ (insertion order; cross-committee uniqueness via shuffling). H8 ✓ (subclass-override). H9 ✓. H10 ✓ (`AttestationUtilGloas` doesn't override). H11 ✓. H12 ✓.

### nimbus

`vendor/nimbus/beacon_chain/spec/validator.nim:732-738`:

```nim
iterator get_committee_indices*(bits: AttestationCommitteeBits): CommitteeIndex =
  for index, b in bits:
    if b:
      yield CommitteeIndex.init(uint64(index))
```

`vendor/nimbus/beacon_chain/spec/beaconstate.nim:688-706` (Electra iterator):

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.5.0-alpha.3/specs/electra/beacon-chain.md#modified-get_attesting_indices
iterator get_attesting_indices*(
    state: ForkyBeaconState,
    bits: ElectraCommitteeValidatorsBits,
    committee_bits: AttestationCommitteeBits,
    slot: Slot,
    cache: var StateCache): ValidatorIndex =
  var committee_offset = 0
  for index in get_committee_indices(committee_bits):
    let committee = get_beacon_committee(state, slot, index, cache)
    for i, idx in committee:
      if bits[committee_offset + i]:
        yield idx
    committee_offset += committee.len
```

Nim `iterator` (lazy) — yields validator indices one at a time. **No explicit deduplication** — relies on unique-by-construction. Eager seq-returning wrapper at `:771-781`:

```nim
iterator get_attesting_indices*(
    state: ForkyBeaconState,
    attestation: electra.Attestation | electra.TrustedAttestation,
    cache: var StateCache): ValidatorIndex =
  ...
  for vidx in state.get_attesting_indices(
      attestation.aggregation_bits, attestation.committee_bits, attestation.data.slot, cache):
    yield vidx
```

Type-overload-based per-fork dispatch: `electra.Attestation | electra.TrustedAttestation` for Electra+, `phase0.Attestation | phase0.TrustedAttestation` for pre-Electra (`:672` and `:754`). At Gloas, `ForkyBeaconState` includes `gloas.BeaconState` and the Electra `Attestation` type is reused (no `gloas.Attestation` redefinition); the same iterator overload fires.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. **H6 ⚠️ unique-by-construction**. H7 ✓ (cross-committee uniqueness via shuffling). H8 ✓ (type-overload). H9 ✓. H10 ✓. H11 ✓. H12 ✓.

### lodestar

`vendor/lodestar/packages/state-transition/src/util/shuffling.ts:158-187`:

```typescript
export function getAttestingIndices(epochShuffling: EpochShuffling, fork: ForkSeq, attestation: Attestation): number[] {
  const slotShuffling = epochShuffling.slots[attestation.data.slot % SLOTS_PER_EPOCH];
  if (fork < ForkSeq.electra) {
    const validatorIndices = slotShuffling[Number(attestation.data.index)];
    const aggregationBits = (attestation as phase0.Attestation).aggregationBits;
    return aggregationBits.intersectValues(validatorIndices);
  }

  // Electra+ multi-committee:
  const committeeBits = (attestation as electra.Attestation).committeeBits;
  const committeeIndices = committeeBits.getTrueBitIndexes();
  const validatorsByCommittee = getBeaconCommittees(epochShuffling, attestation.data.slot, committeeIndices);

  const totalLength = validatorsByCommittee.reduce((acc, curr) => acc + curr.length, 0);
  const committeeValidators = new Uint32Array(totalLength);
  let offset = 0;
  for (const committee of validatorsByCommittee) {
    committeeValidators.set(committee, offset);
    offset += committee.length;
  }
  const aggregationBits = (attestation as electra.Attestation).aggregationBits;
  return aggregationBits.intersectValues(committeeValidators);
}
```

"Flatten + intersect" choreography (carried forward from prior audit): all committees flattened into one `Uint32Array`, then `aggregationBits.intersectValues(committeeValidators)` selects entries at SET bit positions in the flat array. **No explicit deduplication** — relies on unique-by-construction. `committeeBits.getTrueBitIndexes()` returns ascending bit positions (the `getCommitteeIndices` analog inline).

Per-fork dispatch via runtime `if (fork < ForkSeq.electra)` numeric check. `ForkSeq.electra` is the lowest fork value covered by the Electra branch — Gloas (a higher ForkSeq value) is automatically covered. No Gloas-specific override.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. **H6 ⚠️ unique-by-construction**. H7 ✓ (`intersectValues` returns elements in bit-position order; on flat array indexed by committee_offset). H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓.

### grandine

`vendor/grandine/helper_functions/src/misc.rs:808-815 get_committee_indices`:

```rust
pub fn get_committee_indices<P: Preset>(
    committee_bits: BitVector<P::MaxCommitteesPerSlot>,
) -> impl Iterator<Item = CommitteeIndex> {
    committee_bits.into_iter().zip(0..).filter_map(|(bit, index)| bit.then_some(index))
}
```

`vendor/grandine/helper_functions/src/electra.rs:82-121 get_attesting_indices`:

```rust
pub fn get_attesting_indices<P: Preset>(
    state: &impl BeaconState<P>,
    attestation: &Attestation<P>,
) -> Result<HashSet<ValidatorIndex>> {
    let mut output = HashSet::new();
    let committee_indices = get_committee_indices::<P>(attestation.committee_bits);
    let mut committee_offset = 0;

    for index in committee_indices {
        let committee = beacon_committee(state, attestation.data.slot, index)?;
        let committee_attesters = committee.into_iter().enumerate()
            .filter_map(|(i, index)| {
                (*attestation.aggregation_bits.get(committee_offset + i)?).then_some(index)
            })
            .collect::<Vec<_>>();
        ensure!(!committee_attesters.is_empty(), Error::NoCommitteeAttesters { index });
        output.extend(committee_attesters);
        committee_offset += committee.len();
    }

    ensure!(
        committee_offset == attestation.aggregation_bits.len(),
        Error::ParticipantsCountMismatch { ... },
    );

    Ok(output)
}
```

**Returns `HashSet<ValidatorIndex>` — the only client that returns a Set type literally matching pyspec.** Explicit deduplication via `HashSet`. Defensive `NoCommitteeAttesters` and `ParticipantsCountMismatch` errors (matching the Electra-`process_attestation` validation checks).

Per-fork dispatch via module-namespace: `transition_functions/src/electra/block_processing.rs` imports `electra::get_attesting_indices`; phase0/altair callers import `phase0::get_attesting_indices`. Gloas module imports the Electra helper unchanged (no `helper_functions/src/gloas.rs::get_attesting_indices` exists).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓ (HashSet). H7 ✓ (downstream re-sorts when constructing IndexedAttestation). H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓.

## Cross-reference table

| Client | Helper locations | Deduplication strategy | Per-fork dispatch | Gloas redefinition |
|---|---|---|---|---|
| prysm | `helpers/beacon_committee.go:478-491 CommitteeIndices`; `proto/prysm/v1alpha1/attestation/attestation_utils.go:85-126 AttestingIndices` + `:260-284` Phase0 | `slices.Sort + slices.Compact` (Go 1.21+) | runtime `att.Version() < version.Electra` check | none — Electra impl reused at Gloas via `ethpb.Att` interface |
| lighthouse | `state_processing/src/common/get_attesting_indices.rs:25-44` Base + `:94-149` Electra + `:151-159 get_committee_indices` | `HashSet<u64>` per-committee + `sort_unstable()` final | superstruct `AttestationRef::{Base, Electra}` | none — Electra variant reused at Gloas |
| teku | `versions/electra/util/AttestationUtilElectra.java:70-92 getAttestingIndices` + `streamCommitteeAttesters`; `AttestationElectra.getCommitteeIndicesRequired()` via `committeeBits.getAllSetBits()` | **NONE — unique-by-construction** (`ArrayList<UInt64>` + `flatMap`) | subclass-override `AttestationUtilElectra extends AttestationUtilDeneb extends ...`; `AttestationUtilGloas` doesn't override | none — `AttestationUtilGloas` inherits without override |
| nimbus | `spec/validator.nim:732-738` iterator; `spec/beaconstate.nim:688-706` Electra iterator + `:754-781` wrappers + `:672-685` Phase0 | **NONE — unique-by-construction** (`seq[ValidatorIndex]` + `result.add` / iterator lazy yield) | type-union `electra.Attestation \| electra.TrustedAttestation` vs `phase0.Attestation \| phase0.TrustedAttestation` (Nim compile-time overload); `ForkyBeaconState` covers Gloas | none — Electra `Attestation` type reused at Gloas via overload polymorphism |
| lodestar | `state-transition/src/util/shuffling.ts:158-187 getAttestingIndices`; `committeeBits.getTrueBitIndexes()` inline (no separate `getCommitteeIndices`) | **NONE — unique-by-construction** (flatten + `intersectValues`) | `if (fork < ForkSeq.electra)` runtime check; Electra branch covers Gloas | none — `ForkSeq.electra` lower bound; Gloas inherits |
| grandine | `helper_functions/src/electra.rs:82-121 get_attesting_indices`; `misc.rs:808-815 get_committee_indices` (returns iterator) | **`HashSet<ValidatorIndex>`** — only client returning a literal Set type | module-namespace dispatch: callers import `electra::get_attesting_indices` or `phase0::get_attesting_indices` | none — Gloas module imports Electra helper |

## Empirical tests

### Pectra-surface implicit coverage (carried forward)

No dedicated EF fixture set — both helpers are internal. Exercised IMPLICITLY:

| Item | Fixtures × wired clients | Calls these helpers |
|---|---|---|
| #7 process_attestation | 45 × 4 = 180 | each Attestation → `get_attesting_indices` → IndexedAttestation → item #25 |
| #8 process_attester_slashing | 30 × 4 = 120 | indirectly via item #25's `is_valid_indexed_attestation` (each slashed attestation's indices are pre-computed and verified) |

**Cumulative implicit cross-validation evidence**: 300 EF fixture PASSes across 75 unique fixtures all flow through these helpers at Pectra. No divergence between the 3-explicit-dedup and 3-unique-by-construction families because all fixture inputs satisfy the shuffling invariant.

### Gloas-surface

No Gloas-specific fixtures wired yet. H9 (function bodies unchanged) and H10 (caller modifications don't propagate) are source-only.

Concrete Gloas-spec evidence:
- `vendor/consensus-specs/specs/gloas/beacon-chain.md:1687` — `committee_indices = get_committee_indices(attestation.committee_bits)` inside Gloas-Modified `process_attestation`. Same function call as at Electra.
- `vendor/consensus-specs/specs/gloas/beacon-chain.md:1722` — `for index in get_attesting_indices(state, attestation)` inside same Gloas-Modified `process_attestation`. Same function call.
- No `Modified get_attesting_indices` nor `Modified get_committee_indices` headings anywhere in `vendor/consensus-specs/specs/gloas/`.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — dedicated EF fixture set for the helpers).** Pure `(state, Attestation) → Set[ValidatorIndex]` fuzz. Boundary cases: single-committee, multi-committee, max-cap (64 committees set), empty committee_bits (rejected upstream by item #7), max aggregation_bits length, exact-boundary aggregation_bits length. Cross-client byte-level equivalence at both Pectra and Gloas.

#### T2 — Adversarial probes
- **T2.1 (priority — cross-client dedup-strategy contract test).** Construct an Attestation with hypothetically-overlapping committees (bypassing shuffling — synthetic state). Expected:
  - prysm + lighthouse + grandine: dedup the result; cross-committee overlap silently collapsed.
  - teku + nimbus + lodestar: produce duplicates that downstream item #25's sorted+unique check would reject.
  - Cross-client byte-level test verifies BOTH families produce the SAME observable behaviour (item #25 rejects in both cases) — but via different code paths.
- **T2.2 (Glamsterdam-target — H9 / H10 verification).** Run T1.1 against Gloas state (post-`upgrade_to_gloas`). Expected: identical results to Pectra (function bodies unchanged). Confirms no Gloas-conditional fork-dispatch was added in any client.
- **T2.3 (defensive — committee_bits with `MAX_COMMITTEES_PER_SLOT` = 64 set bits).** All 64 committees aggregated into one Attestation. Verify cross-client correct iteration of all 64 committees with cumulative `committee_offset` ≤ `MAX_VALIDATORS_PER_COMMITTEE × 64 = 131,072`. Same stress test as item #25 T2.2 (full-cap aggregation).
- **T2.4 (defensive — committee_bits empty / all-zero).** `attestation.committee_bits = 0`. Pyspec: `committee_indices = []` → loop body never executes → returns empty set. Cross-client: should also return empty. Downstream item #25 rejects via `len(indices) == 0` check. Empty-set handling cross-client equivalence.
- **T2.5 (defensive — aggregation_bits length mismatch).** `committee_offset` after the loop must equal `len(attestation.aggregation_bits)`. Pyspec doesn't explicitly check this in `get_attesting_indices`, but the caller (item #7 `process_attestation`) does: `assert len(attestation.aggregation_bits) == committee_offset` (`vendor/consensus-specs/specs/electra/beacon-chain.md:1543`). Lighthouse and grandine perform the check inside `get_attesting_indices` (additional defense-in-depth); other clients defer to the caller. Verify cross-client at the caller level.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Pectra-surface invariants (H1–H8) hold across all six. The carried-forward 3-vs-3 dedup divergence is reaffirmed:
- **Explicit dedup**: prysm (`slices.Sort + slices.Compact`), lighthouse (`HashSet<u64>` + `sort_unstable`), grandine (`HashSet<ValidatorIndex>` returned directly).
- **Unique-by-construction**: teku (`ArrayList<UInt64>` + `flatMap`), nimbus (`seq[ValidatorIndex]` iterator + `add`), lodestar (flatten + `intersectValues`).

All observable-equivalent on shuffling-conformant input. 300 implicit EF fixture PASSes from items #7 + #8 cross-validate at Pectra without divergence.

**Glamsterdam-target finding (H9 + H10 — function bodies unchanged, caller modifications do not propagate).** `vendor/consensus-specs/specs/gloas/beacon-chain.md` contains no `Modified get_attesting_indices` nor `Modified get_committee_indices` headings. Both helpers are inherited verbatim from Electra at Gloas. The Gloas-Modified `process_attestation` (item #7's surface) introduces new logic for EIP-7732 (`data.index < 2` constraint, `state.builder_pending_payments` weight accounting, `will_set_new_flag` same-slot-once tracking — `vendor/consensus-specs/specs/gloas/beacon-chain.md:1685-1751`) but the calls to these helpers at `:1687` and `:1722` are unchanged. The `Attestation` container is NOT redefined at Gloas (`committee_bits`, `aggregation_bits` fields carry forward from Electra; `MAX_COMMITTEES_PER_SLOT = 64` and `MAX_VALIDATORS_PER_COMMITTEE = 2048` constants unchanged).

**Ninth impact-none result** in the recheck series (after items #5, #10, #11, #18, #20, #21, #24, #25). Same propagation-without-amplification pattern as item #25: the Gloas modifications to `process_attestation` are upstream of these helpers; the helpers themselves are unchanged.

**Cross-cut with nimbus items #22 / #23 / lighthouse #24 (H12 — no propagation).** Neither helper invokes `has_compounding_withdrawal_credential` (item #22) nor `get_pending_balance_to_withdraw` (item #23) nor any function in the lighthouse Gloas-ePBS readiness cohort (items #14/#19/#22/#23/#24). These helpers use `get_beacon_committee` (phase0 helper, unchanged across forks), `attestation.aggregation_bits` / `attestation.committee_bits` (Electra container fields, unchanged at Gloas), and `state.validators` (no credentials-byte access). **Nimbus's mainnet-everyone divergences from items #22 and #23 do NOT propagate to these helpers.**

**Notable per-client style differences (all observable-equivalent at both Pectra and Gloas):**
- **prysm**: `slices.Sort + slices.Compact` (Go 1.21+ idiom). Per-committee `noAttestersError` check.
- **lighthouse**: `HashSet<u64>` per-committee + `sort_unstable` final. Three defensive Electra-process_attestation checks woven into the helper itself.
- **teku**: `streamCommitteeAttesters` Java streams idiom. Subclass-override polymorphism via `AttestationUtilGloas extends AttestationUtilElectra` without override.
- **nimbus**: `iterator` variant (lazy) + eager `func` wrapper. Type-overload dispatch.
- **lodestar**: "flatten + intersect" choreography using `Uint32Array` and `aggregationBits.intersectValues`. Different code path from spec's per-committee iteration; observable-equivalent.
- **grandine**: returns `HashSet<ValidatorIndex>` — the only client matching pyspec's `Set[ValidatorIndex]` return type literally. Defensive `NoCommitteeAttesters` and `ParticipantsCountMismatch` errors.

**No code-change recommendation.** Audit-direction recommendations:

- **Generate dedicated EF fixture set for the helpers** (T1.1) — pure-function cross-client byte-level equivalence.
- **Cross-client dedup-strategy contract test** (T2.1) — codify the 3-vs-3 dedup divergence and verify downstream item #25 rejects duplicates uniformly.
- **Gloas-surface end-to-end test** (T2.2) — verify cross-client identical results between Pectra and Gloas state inputs.
- **64-committee maximum-aggregation cross-client stress test** (T2.3) — full-cap aggregation correctness.
- **Document the "unique by construction" invariant** for teku / nimbus / lodestar — formal code comment explaining why explicit dedup is skipped and what shuffling property it relies on. Forward-fragility hedge.
- **`get_beacon_committee` cross-cut audit** — used by these helpers and many others; phase0-heritage helper unchanged at all forks. Worth a separate audit for the cache invalidation properties at fork boundaries.
- **lodestar `intersectValues` ordering semantics audit** — verify cross-client that the bit-position order of the flat array matches what downstream consumers expect.

## Cross-cuts

### With item #7 (`process_attestation`) — Gloas-modified caller

Item #7's `process_attestation` is Modified at Gloas for EIP-7732 (proposer reward + builder_pending_payments + same-slot uniqueness). The Gloas-modified body calls these helpers UNCHANGED at lines 1687 and 1722. This item's surface is unaffected by item #7's Gloas modifications.

### With item #8 (`process_attester_slashing`) — Gloas-unchanged caller

Item #8 is inherited from Electra at Gloas. Both attestations in a slashing proof have their `attesting_indices` populated via `get_attesting_indices` upstream of `is_valid_indexed_attestation` (item #25). Unchanged at Gloas.

### With item #25 (`is_valid_indexed_attestation`) — direct downstream consumer

Item #25 takes the output of `get_attesting_indices` (wrapped into an IndexedAttestation) and verifies the sorted+unique invariant + BLS aggregate. The 3-vs-3 dedup divergence at this item is OBSERVABLE-EQUIVALENT at item #25's surface because:
- Explicit-dedup clients (prysm, lighthouse, grandine) produce a deduplicated sorted result → item #25 accepts.
- Unique-by-construction clients (teku, nimbus, lodestar) produce results that ARE unique under spec-conformant shuffling → item #25 accepts.
- Under hypothetical shuffling-bug input with cross-committee overlap, explicit-dedup clients would silently collapse duplicates while unique-by-construction clients would produce duplicates rejected by item #25's sorted+unique check. Either way: the divergence surfaces as a verification failure at item #25, not as a state-mutation divergence at item #7.

### With Gloas-NEW `is_valid_indexed_payload_attestation` (item #25 H11)

The PTC (Payload-Timeliness Committee) surface has its own indexed-attestation predicate (`vendor/consensus-specs/specs/gloas/beacon-chain.md:511-531`) operating on `IndexedPayloadAttestation` (separate from this item's `Attestation` → `IndexedAttestation` chain). These helpers are NOT used for the PTC surface — that surface has its own attesting-indices producer.

### With nimbus items #22 / #23 (no propagation)

Neither helper calls `has_compounding_withdrawal_credential` nor `get_pending_balance_to_withdraw`. The nimbus mainnet-everyone divergences at items #22 and #23 are isolated to those functions' caller chains; this item's surface is unaffected.

### With lighthouse Gloas-ePBS readiness cohort (items #14/#19/#22/#23/#24/#25)

The cohort gap is at the EIP-7732 ePBS routing surfaces (apply_parent_execution_payload, process_consolidation_request via ePBS, is_builder_withdrawal_credential, get_pending_balance_to_withdraw_for_builder, is_valid_indexed_payload_attestation). NONE of these surfaces invoke this item's helpers. Lighthouse's broader Gloas-readiness gap does NOT propagate to these helpers; they're correct in isolation on lighthouse.

## Adjacent untouched

1. **Generate dedicated EF fixture set for the helpers** — pure-function fuzz of `(state, Attestation) → Set[ValidatorIndex]` boundary cases.
2. **Cross-client dedup-strategy contract test** — feed Attestation with synthetic cross-committee overlap; verify behavioural divergence between explicit-dedup and unique-by-construction families is observable-equivalent at item #25's downstream check.
3. **Gloas-surface end-to-end test** — verify cross-client identical results on Gloas state input.
4. **64-committee maximum-aggregation stress test** at Gloas — full-cap (131,072 attesters) cross-client correctness.
5. **Document the "unique by construction" invariant** as code comments in teku / nimbus / lodestar — formal spec of the shuffling property relied upon and the forward-fragility hedge.
6. **`get_beacon_committee` cross-cut audit** — phase0-heritage helper used by these and many others; cache-invalidation properties at fork boundaries.
7. **lodestar `intersectValues` ordering semantics audit** — verify cross-client that bit-position output order matches downstream expectations.
8. **nimbus iterator vs func performance audit** — verify lazy iterator variant is used wherever caller benefits.
9. **grandine `NoCommitteeAttesters` / `ParticipantsCountMismatch` error equivalence test** — other 5 clients defer these checks to the caller (item #7 `process_attestation`); verify cross-client behaviour.
10. **Cross-fork transition stateful fixture** — first multi-committee attestation post-Electra activation. Verify cross-client correct dispatch.
11. **Bit-position iteration ordering contract test** — all 6 clients iterate `committee_bits` in ascending bit position; assert at the API level.
12. **`MAX_COMMITTEES_PER_SLOT = 64` over-the-wire SSZ cap test** — verify cross-client rejection of 65-committee `committee_bits`.
13. **Architectural: `get_committee_indices` is purely SSZ-bit-iteration** — no state access. Could be moved to bitvector / ssz utility module instead of state helpers. Code-organisation improvement.
14. **Sister-item audit: Gloas-NEW PTC attesting-indices producer** (the source for `IndexedPayloadAttestation.attesting_indices`) — likely lives in PTC committee-shuffling code, separate from these helpers.
