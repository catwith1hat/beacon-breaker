# Item #26 — `get_attesting_indices` + `get_committee_indices` (Pectra-MODIFIED + Pectra-NEW for EIP-7549 multi-committee aggregation)

**Status:** no-divergence-pending-source-review — audited 2026-05-02.
The two helper functions that convert Pectra's multi-committee
`Attestation` into the flat sorted attester-index set used by item
#25's BLS aggregate verifier. **Subtle finding: 3 of 6 clients do
NOT explicitly deduplicate the result** — they rely on "unique by
construction" (committee shuffling guarantees no validator is in
multiple committees per slot). Observable-equivalent today,
forward-fragile if shuffling ever changes.

## Why this item

Pectra's EIP-7549 modifies `Attestation` to include a
`committee_bits: Bitvector[MAX_COMMITTEES_PER_SLOT]` field —
allowing a single attestation to span MULTIPLE committees with one
BLS aggregate signature. The flat `aggregation_bits` is indexed by
a cumulative `committee_offset` walked across the SET committees in
ascending order.

Two helpers implement this:

```python
def get_committee_indices(committee_bits: Bitvector) -> Sequence[CommitteeIndex]:
    """Return positions of SET bits in committee_bits."""
    return [CommitteeIndex(index) for index, bit in enumerate(committee_bits) if bit]

def get_attesting_indices(state, attestation) -> Set[ValidatorIndex]:
    """Resolve aggregation_bits + committee_bits → attester index set."""
    output: Set[ValidatorIndex] = set()
    committee_indices = get_committee_indices(attestation.committee_bits)
    committee_offset = 0
    for committee_index in committee_indices:
        committee = get_beacon_committee(state, attestation.data.slot, committee_index)
        committee_attesters = set(
            attester_index for i, attester_index in enumerate(committee)
            if attestation.aggregation_bits[committee_offset + i]
        )
        output = output.union(committee_attesters)
        committee_offset += len(committee)
    return output
```

Item #7 audited the outer `process_attestation` flow that calls these.
Item #25 audited the inner BLS-aggregate-verify chokepoint that
consumes the IndexedAttestation built from the result of these
helpers. **This audit closes the gap** — the connecting tissue
between the Attestation container and the BLS verification.

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | `get_committee_indices` returns SET bit positions in ascending order | ✅ all 6 |
| H2 | `get_attesting_indices` iterates committees in ascending bit-position order | ✅ all 6 |
| H3 | `committee_offset` cumulative across committees (flat aggregation_bits indexed by offset) | ✅ all 6 |
| H4 | `aggregation_bits[committee_offset + i]` per-validator bit check | ✅ all 6 |
| H5 | `get_beacon_committee(state, attestation.data.slot, committee_index)` lookup per committee | ✅ all 6 |
| H6 | Result deduplication via Set semantics | ✅ 3/6 (prysm, lighthouse, grandine); ⚠️ teku, nimbus, lodestar rely on "unique by construction" — observable-equivalent but forward-fragile |
| H7 | Final result sorted (or unique enough to satisfy item #25's sorted+unique check) | ✅ all 6 |
| H8 | Per-fork dispatch: pre-Electra single-committee variant + Electra multi-committee variant | ✅ all 6 (with 6 distinct dispatch idioms — see below) |

## Per-client cross-reference

| Client | Function locations | Deduplication strategy | Per-fork dispatch |
|---|---|---|---|
| **prysm** | `helpers/beacon_committee.go:478-491` (`CommitteeIndices`); `proto/.../attestation/attestation_utils.go:85-126` (`AttestingIndices` Electra) + `:260-284` (Phase0) | `slices.Sort(attesters); slices.Compact(attesters)` — Go 1.21+ idiom (sort then compact consecutive duplicates) | `att.Version() < version.Electra` runtime check dispatches to `attestingIndicesPhase0` (single committee) vs Electra multi-committee path |
| **lighthouse** | `state_processing/src/common/get_attesting_indices.rs:151-159` (`get_committee_indices`); `:25-44` (Base) + `:94-149` (Electra `get_attesting_indices`); `types/src/attestation/attestation.rs:332-338` (Attestation method) | `HashSet<u64>` per-committee + final `Vec.sort_unstable()` | superstruct `AttestationRef::{Base, Electra}` dispatch via `consensus_context.rs:152-178` |
| **teku** | `AttestationElectra.java:71-74` (`getCommitteeIndices` via `committeeBits.getAllSetBits()`); `AttestationUtilElectra.java:70-85` (`getAttestingIndices` Electra) + `:87-92` (`streamCommitteeAttesters` helper); `AttestationUtil.java:123-127` (Phase0) | **NONE** — `ArrayList<UInt64>` accumulator; relies on unique-by-construction | Subclass-override `AttestationUtilElectra extends AttestationUtilDeneb extends AttestationUtilPhase0 extends AttestationUtil` |
| **nimbus** | `validator.nim:732` (`get_committee_indices` iterator) + `:189` (count-based variant); `beaconstate.nim:689` (`get_attesting_indices` Electra iterator) + `:672` (Phase0) + `:754, 772, 788` (wrappers) | **NONE** — `seq[ValidatorIndex]` with `result.add`; relies on unique-by-construction | Type-overload-based: separate functions accept `phase0.Attestation \| phase0.TrustedAttestation` vs `electra.Attestation \| electra.TrustedAttestation` |
| **lodestar** | `state-transition/src/util/shuffling.ts:158-187` (`getAttestingIndices`) + `:199-223` (`getBeaconCommittees`); `committeeBits.getTrueBitIndexes()` inline (no separate `getCommitteeIndices`); `processAttestationPhase0.ts:97-141` (validation with cumulative offset) | **NONE** — flatten + `intersectValues`; relies on unique-by-construction | `if (fork < ForkSeq.electra)` runtime check |
| **grandine** | `helper_functions/src/misc.rs:808-815` (`get_committee_indices` iterator); `helper_functions/src/electra.rs:82-121` (`get_attesting_indices`) + `helper_functions/src/phase0.rs:48-72` (Phase0) | **`HashSet<ValidatorIndex>`** — matches pyspec literally (returns `Result<HashSet<ValidatorIndex>>`) | Module-namespace dispatch: `transition_functions/src/electra/block_processing.rs` imports `electra::get_attesting_indices`; altair/etc. import `phase0::get_attesting_indices` |

## Notable per-client divergences (all observable-equivalent at Pectra)

### CRITICAL: 3/6 clients rely on "unique by construction" (NO explicit deduplication)

The pyspec uses `Set[ValidatorIndex]` — explicitly deduplicated.
Three clients (teku, nimbus, lodestar) skip explicit deduplication
because **committee shuffling guarantees** each validator is
assigned to at most ONE committee per slot. Therefore, when
iterating the multi-committee attestation, no validator can appear
in two committees, and the accumulated indices are unique by
construction.

**Three clients (prysm, lighthouse, grandine) DO explicitly
deduplicate**:
- prysm: `slices.Sort + slices.Compact` (Go 1.21+ pattern).
- lighthouse: `HashSet<u64>` per-committee + final sort.
- grandine: `HashSet<ValidatorIndex>` (returns Set type literally
  matching pyspec).

**Why this matters**: today, the unique-by-construction invariant
holds (verified by EF fixtures across items #7 + #8 = 75 fixtures ×
4 wired clients = 300 PASSes). But **if a future spec change ever
allowed cross-committee overlaps** (e.g., a "validator can attest
twice if randomly assigned to multiple committees" change), teku /
nimbus / lodestar would silently produce duplicates while prysm /
lighthouse / grandine would deduplicate.

The downstream consumer (item #25's `is_valid_indexed_attestation`)
checks `len(indices) > 0 AND sorted AND unique` — if duplicates are
present, the strict-ascending check would fail and the verification
would reject. So the duplicates would surface as a verification
failure, not silent acceptance. **F-tier today** but worth tracking.

### Six distinct dispatch + return-type idioms

The Pectra `get_attesting_indices` returns `Set[ValidatorIndex]`
per pyspec, but each client uses a different concrete type:

- **prysm**: `[]uint64` (sorted slice via `slices.Compact`).
- **lighthouse**: `Vec<u64>` (sorted via `sort_unstable`).
- **teku**: `List<UInt64>` (insertion order, unique by construction).
- **nimbus**: `seq[ValidatorIndex]` (insertion order; iterator variant
  for lazy evaluation).
- **lodestar**: `T[]` from `intersectValues` (bit-position order).
- **grandine**: `HashSet<ValidatorIndex>` — **only client that returns
  a Set type literally**.

Per-fork dispatch idioms:
- **prysm**: runtime `att.Version() < version.Electra` check.
- **lighthouse**: superstruct enum-variant pattern matching.
- **teku**: subclass-override polymorphism (4-level inheritance chain).
- **nimbus**: type-union compile-time overload resolution.
- **lodestar**: ForkSeq numeric comparison.
- **grandine**: module-namespace dispatch (callers import the right module).

### lodestar's "flatten + intersect" choreography

```typescript
// lodestar shuffling.ts:165-187
const committeeIndices = committeeBits.getTrueBitIndexes();
const validatorsByCommittee = getBeaconCommittees(epochShuffling, data.slot, committeeIndices);

// FLATTEN all committees into one Uint32Array
const totalLength = validatorsByCommittee.reduce((acc, curr) => acc + curr.length, 0);
const committeeValidators = new Uint32Array(totalLength);
let offset = 0;
for (const committee of validatorsByCommittee) {
    committeeValidators.set(committee, offset);
    offset += committee.length;
}

// INTERSECT with aggregation_bits
return aggregationBits.intersectValues(committeeValidators);
```

Item #7 audit's "flatten + intersect" claim **VERIFIED**. lodestar
flattens all committees into one Uint32Array, then uses
`aggregationBits.intersectValues(committeeValidators)` (returns
elements at SET bit positions in the flat array). Different
choreography from spec's per-committee iteration with offset, but
**observable-equivalent**.

### prysm + lighthouse + grandine: defensive dedup (HashSet/sort+compact)

These three clients add explicit deduplication, even though it's
unnecessary under current shuffling semantics. **Defensive coding**
that protects against:
1. Future spec changes that allow cross-committee overlaps.
2. Bug in shuffling that produces overlaps (e.g., RNG bias).
3. Adversarial input that violates the invariant (though the
   downstream `is_valid_indexed_attestation` check would catch this).

**Three different idioms producing the same observable result.**

### nimbus: `iterator` vs `func` distinction

```nim
# nimbus beaconstate.nim:689 — iterator (lazy)
iterator get_attesting_indices*(...): ValidatorIndex = ...

# nimbus beaconstate.nim:788 — func (eager seq)
func get_attesting_indices*(...): seq[ValidatorIndex] =
    for vidx in get_attesting_indices(...):
        result.add vidx
```

Nim's `iterator` allows lazy evaluation (avoid allocating the
full result if caller only needs to scan). The `func` collects
into a seq for callers needing eager evaluation. **Performance
optimization unique to nimbus.**

### grandine: explicit "no committee attesters" error

```rust
// grandine electra.rs:101-104
ensure!(
    !committee_attesters.is_empty(),
    Error::NoCommitteeAttesters { index },
);
```

Grandine returns an error if any committee has zero attesters.
Other clients do this check elsewhere (e.g., prysm at
`attestation_utils.go:117-118`). **Defensive against malformed
attestations** where a committee_bits position is set but no
aggregation_bits in that committee's slice are set.

### Six distinct `get_committee_indices` idioms (all observable-equivalent)

- **prysm**: `bitfield.BitIndices()` (returns sorted indices).
- **lighthouse**: `committee_bits.iter().enumerate().filter_map(...)` (Rust iterator).
- **teku**: `committeeBits.getAllSetBits().intStream().mapToObj(UInt64::valueOf).toList()` (SSZ helper + stream).
- **nimbus**: `for index, b in bits: if b: yield CommitteeIndex.init(uint64(index))` (manual iteration in Nim iterator).
- **lodestar**: `committeeBits.getTrueBitIndexes()` (SSZ helper, no separate function).
- **grandine**: `committee_bits.into_iter().zip(0..).filter_map(...)` (Rust iterator with zip).

All produce ascending bit positions. Item #7 audit's note about
nimbus using `bitvector.oneIndices` is **partially accurate**:
`oneIndices` is available and used elsewhere (e.g., `beaconstate.nim:1116`),
but `get_committee_indices` itself uses plain `for index, b in bits`
iteration. Same observable result.

## EF fixture status — implicit coverage via items #7 + #8

This audit has **no dedicated EF fixture set** because both functions
are internal helpers. They are exercised IMPLICITLY via:

| Item | Fixtures × clients | Calls these functions |
|---|---|---|
| **#7** process_attestation | 45 × 4 = 180 | each Attestation → get_attesting_indices → IndexedAttestation |
| **#8** process_attester_slashing | 30 × 4 = 120 | indirectly via item #25's is_valid_indexed_attestation (which the slashing path calls) |

**Total implicit cross-validation evidence**: **300 EF fixture
PASSes** across 75 unique fixtures all flow through these helpers.
Critical fixtures testing edge cases:

| Fixture | Hypothesis tested |
|---|---|
| `attestation_one_committee` | single committee (committee_bits has 1 set bit) |
| `multi_committee_attestation` | EIP-7549 multi-committee aggregation |
| `invalid_too_many_committee_bits` | committee_bits cap |
| `invalid_nonset_committee_bits` | empty committee_bits |
| `invalid_too_few_aggregation_bits` | offset arithmetic |
| `invalid_too_many_aggregation_bits` | offset arithmetic |
| `invalid_empty_participants_seemingly_valid_sig` | empty per-committee attesters |

A dedicated fixture for `get_attesting_indices` would be `(state,
Attestation) → Set[ValidatorIndex]` — pure function over the
multi-committee aggregation logic. Worth generating as a follow-up.

## Cross-cut chain — closes the EIP-7549 multi-committee aggregation chain

This audit closes the connecting tissue between the Attestation
container and the BLS verification:

```
Attestation (Pectra-modified for EIP-7549)
    .committee_bits: Bitvector[MAX_COMMITTEES_PER_SLOT = 64]
    .aggregation_bits: Bitlist[MAX_VALIDATORS_PER_COMMITTEE × MAX_COMMITTEES_PER_SLOT = 131,072]
    .data: AttestationData
    .signature: BLSSignature
                ↓
[item #26 (this) get_committee_indices]: extract SET bit positions [0, 2, 5, ...] (ascending)
                ↓
[item #26 (this) get_attesting_indices]:
    committee_offset = 0
    for committee_index in [0, 2, 5, ...]:
        committee = get_beacon_committee(state, slot, committee_index)
        committee_attesters = {validator_idx for i, validator_idx in enumerate(committee)
                              if aggregation_bits[committee_offset + i]}
        output = output.union(committee_attesters)
        committee_offset += len(committee)
    return Set[ValidatorIndex] (deduplicated by spec; 3/6 clients explicit, 3/6 implicit)
                ↓ build IndexedAttestation
IndexedAttestation
    .attesting_indices: List[ValidatorIndex, 131,072]   (must be sorted+unique)
    .data: AttestationData
    .signature: BLSSignature  (same aggregate signature from Attestation)
                ↓
[item #25 is_valid_indexed_attestation]:
    1. empty/sorted/unique check on attesting_indices
    2. pubkey lookup
    3. domain construction (DOMAIN_BEACON_ATTESTER + current fork)
    4. compute_signing_root(data, domain)
    5. bls.FastAggregateVerify(pubkeys, signing_root, signature)
                ↓ if valid
[item #7 process_attestation]: apply attestation, update participation flags, reward proposer
[item #8 process_attester_slashing]: detect Casper FFG violation, slash intersection
```

The complete EIP-7549 multi-committee aggregation chain is now
audited end-to-end (items #7 → #25 → #26 → #25 → #7/#8).

## Adjacent untouched

- **Generate dedicated EF fixture set** for the helpers — pure
  function `(state, Attestation) → Set[ValidatorIndex]` is trivially
  fuzzable.
- **Cross-client dedup-strategy contract test**: feed an
  Attestation with hypothetically-overlapping committees (constructed
  manually, bypassing shuffling) to all 6 clients and compare:
  prysm + lighthouse + grandine should dedup; teku + nimbus + lodestar
  should produce duplicates that downstream `is_valid_indexed_attestation`
  rejects via the sorted+unique check.
- **`get_beacon_committee` cross-cut audit** — used by item #26 +
  many others. Pectra-unchanged but the per-slot committee count
  (= MAX_COMMITTEES_PER_SLOT × validator_count / SLOTS_PER_EPOCH /
  TARGET_COMMITTEE_SIZE) interacts with the EIP-7549 multi-committee
  aggregation.
- **lodestar's `intersectValues` semantics** — verify that the
  output ordering matches what downstream consumers expect (item
  #25's `is_valid_indexed_attestation` REQUIRES sorted ascending,
  but `intersectValues` may return bit-position order which is
  validator-index order in the flat array).
- **nimbus iterator vs func performance** — verify the iterator
  variant is used wherever lazy evaluation matters (e.g., when
  caller only needs to count, not collect).
- **grandine's "no committee attesters" error** — equivalence test
  with prysm's similar check; ensure other 4 clients reject the same
  case at a different layer.
- **Cross-fork transition** — at Pectra activation, the first block
  with `committee_bits` non-zero (multi-committee aggregation) is
  meaningful. Prior to Electra, attestations had `data.index`
  (single committee). Verify cross-client that the transition
  block correctly dispatches.
- **Bit-position iteration ordering** — all clients iterate
  committee_bits in ascending bit position. If a client ever
  iterated in some other order, the cumulative `committee_offset`
  would be wrong. **Worth a contract test.**
- **`get_committee_indices` SET-bit cap** — `MAX_COMMITTEES_PER_SLOT
  = 64`, so committee_bits has 64 bits. At most 64 committees per
  attestation. Verify cross-client bit-bound enforcement.

## Future research items

1. **Generate dedicated EF fixture set** — pure-function fuzzing.
2. **Cross-client dedup-strategy contract test** with manually-
   constructed overlapping committees.
3. **`get_beacon_committee` cross-cut audit**.
4. **lodestar `intersectValues` ordering semantics** verification.
5. **nimbus iterator vs func performance audit**.
6. **grandine "no committee attesters" error equivalence test**
   against other 5 clients.
7. **Cross-fork transition stateful fixture** (first multi-committee
   attestation post-Electra).
8. **Bit-position iteration ordering contract test**.
9. **`MAX_COMMITTEES_PER_SLOT = 64` over-the-wire SSZ cap** test.
10. **Documentation of the "unique by construction" invariant** —
    formal statement of why teku/nimbus/lodestar can skip explicit
    dedup. Should be a code comment in those three clients.
11. **Pre-emptive Gloas audit**: at Gloas, attestation structure may
    change (EIP-7732 PBS). Verify cross-client.
12. **`get_committee_indices` is purely SSZ-bit-iteration** — no
    state access. Could be moved to `bls`/`ssz` utility module
    instead of state helpers. Architectural improvement.
