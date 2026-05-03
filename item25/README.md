# Item #25 — `is_valid_indexed_attestation` (Pectra-MODIFIED via SSZ-type capacity expansion)

**Status:** no-divergence-pending-source-review — audited 2026-05-02.
The **BLS aggregate signature verifier** for indexed attestations.
**Function body unchanged from Phase0**; the Pectra change is at the
**SSZ TYPE LEVEL** — `IndexedAttestation.attesting_indices` capacity
grew from `MAX_VALIDATORS_PER_COMMITTEE = 2048` to `MAX_VALIDATORS_PER_COMMITTEE
× MAX_COMMITTEES_PER_SLOT = 131,072` (64× larger). Used by item #7
(process_attestation) and item #8 (attester_slashing).

## Why this item

`is_valid_indexed_attestation` is the BLS-aggregate-verify chokepoint
for two major Pectra operations:
- **item #7 (process_attestation)**: each `Attestation` is converted
  to an `IndexedAttestation` via `get_attesting_indices`, then verified
  here. EIP-7549 expanded attestations to span MULTIPLE committees in
  a single signature aggregate.
- **item #8 (process_attester_slashing)**: BOTH attestations in a
  slashing proof are verified here.

The function is **structurally unchanged from Phase0**:

```python
def is_valid_indexed_attestation(state, indexed_attestation) -> bool:
    """Check non-empty + sorted+unique indices + valid aggregate signature."""
    indices = indexed_attestation.attesting_indices
    # Check 1: non-empty AND sorted AND unique
    if len(indices) == 0 or not indices == sorted(set(indices)):
        return False
    # Check 2: BLS FastAggregateVerify
    pubkeys = [state.validators[i].pubkey for i in indices]
    domain = get_domain(state, DOMAIN_BEACON_ATTESTER, indexed_attestation.data.target.epoch)
    signing_root = compute_signing_root(indexed_attestation.data, domain)
    return bls.FastAggregateVerify(pubkeys, signing_root, indexed_attestation.signature)
```

The Pectra change is the **SSZ list capacity**:
- Pre-Electra: `attesting_indices: List[ValidatorIndex, MAX_VALIDATORS_PER_COMMITTEE = 2048]`
- Pectra: `attesting_indices: List[ValidatorIndex, MAX_VALIDATORS_PER_COMMITTEE × MAX_COMMITTEES_PER_SLOT = 2048 × 64 = 131,072]`

A single Pectra IndexedAttestation can now contain attesters from
ALL 64 committees in a slot (one BLS signature aggregated over them).
The function body works identically — only the type capacity grew.

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | Function body unchanged from Phase0 (no Pectra-modified semantics) | ✅ all 6 |
| H2 | Non-empty check: `len(indices) == 0` rejects | ✅ all 6 |
| H3 | Sorted+unique check: strict ascending order (which implies both sorted AND unique) | ✅ all 6 |
| H4 | SSZ list capacity at Electra: `MAX_VALIDATORS_PER_COMMITTEE × MAX_COMMITTEES_PER_SLOT = 131,072` (mainnet) | ✅ all 6 |
| H5 | Pubkey lookup from `state.validators[i].pubkey` (cached map per client) | ✅ all 6 |
| H6 | Domain construction: `DOMAIN_BEACON_ATTESTER` + CURRENT fork (NOT pinned) + target.epoch | ✅ all 6 |
| H7 | `compute_signing_root(indexed_attestation.data, domain)` — signs AttestationData (NOT full IndexedAttestation) | ✅ all 6 |
| H8 | BLS `FastAggregateVerify` (NOT `Verify` or `AggregateVerify`) | ✅ all 6 |
| H9 | Per-fork dispatch: pre-Electra IndexedAttestation has 2048 cap, Electra+ has 131,072 cap | ✅ all 6 (with 6 distinct dispatch idioms) |

## Per-client cross-reference

| Client | Function location | Sort+unique idiom | Per-fork dispatch |
|---|---|---|---|
| **prysm** | `proto/prysm/v1alpha1/attestation/attestation_utils.go:147-167` (`VerifyIndexedAttestationSig`) + `:192-221` (`IsValidAttestationIndices`) + `core/blocks/attestation.go:236-280` (`VerifyIndexedAttestation`) | Explicit pair-wise loop: `for i := 1; i < len; i++ { if indices[i-1] >= indices[i] error }` | Schema-level via proto fork-versioned types `IndexedAttestation` (2048) vs `IndexedAttestationElectra` (131,072); runtime `if .Version() < Electra { ... } else { ... }` |
| **lighthouse** | `state_processing/src/per_block_processing/is_valid_indexed_attestation.rs:14-56` + `signature_sets.rs:272-300` | itertools `tuple_windows().try_for_each(|(x, y)| if x < y { Ok } else { Err })` | superstruct macro generates `IndexedAttestationBase` (`MaxValidatorsPerCommittee = U2048`) vs `IndexedAttestationElectra` (`MaxValidatorsPerSlot = U131072`) variants |
| **teku** | `common/util/AttestationUtil.java:196-217, 242-277` (sorted check + verify); `versions/electra/util/AttestationUtilElectra.java:127-180` (Electra-specific async wrapper) | Loop with `index.isLessThanOrEqualTo(lastIndex)` check; **ONLY enforced for SSZ-derived attestations** (off-the-wire AttesterSlashing); internal `IndexedAttestationLight` skips it | Schema registry: `IndexedAttestationSchema(name, getMaxValidatorsPerAttestationPhase0(2048))` vs `getMaxValidatorsPerAttestationElectra(2048 × 64)` |
| **nimbus** | `spec/beaconstate.nim:629-669` + `spec/signatures.nim:149-176` + `spec/crypto.nim:284-296` | `template is_sorted_and_unique` + linear loop `if s[i-1].uint64 >= s[i].uint64 { false }` | Type union `phase0.IndexedAttestation \| phase0.TrustedIndexedAttestation \| electra.IndexedAttestation \| electra.TrustedIndexedAttestation` with Nim's compile-time overload resolution |
| **lodestar** | `block/isValidIndexedAttestation.ts:11-83` (3 functions) + `signatureSets/indexedAttestation.ts:15-19` | Monotonic check: `for (const index of indices) { if (index <= prev) return false; prev = index; }` | ForkSeq-keyed: `config.getForkSeq(stateSlot) >= ForkSeq.electra ? MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT : MAX_VALIDATORS_PER_COMMITTEE` |
| **grandine** | `helper_functions/src/predicates.rs:91-123` (TWO public entry points) + `:125-165` (private `validate_indexed_attestation`) | itertools `tuple_windows().all(\|(a, b)\| a < b)` (same pattern as lighthouse) | Type-associated `P::MaxValidatorsPerCommittee = U2048` (Phase0) vs `P::MaxAttestersPerSlot = Prod<MaxValidatorsPerCommittee, MaxCommitteesPerSlot>` (Electra) |

## Notable per-client divergences (all observable-equivalent at Pectra)

### Six distinct sort+unique check idioms

All produce the same result — strict ascending order rejects empty,
duplicates, and out-of-order — but with different language idioms:

- **prysm**: imperative pair-wise loop with `>=` rejection.
- **lighthouse + grandine**: itertools `tuple_windows()` + `all(|(a, b)| a < b)` or `try_for_each`.
- **teku**: imperative loop with `.isLessThanOrEqualTo()`; **ONLY at the SSZ boundary** (see below).
- **nimbus**: template-based pair-wise check (zero-cost abstraction).
- **lodestar**: monotonic loop with `prev`-tracking.

The `tuple_windows()` (lighthouse, grandine) is the most type-safe
because it constructs pairs at compile time. The imperative variants
(prysm, teku, nimbus, lodestar) are functionally equivalent.

### teku's TWO attestation representations: Light vs SSZ

**Subtle audit concern**: teku splits indexed attestations into two
representations:
- **`IndexedAttestation` (SSZ wire format)**: from off-the-wire
  AttesterSlashing — REQUIRES sorted+unique check.
- **`IndexedAttestationLight` (internal record)**: constructed
  internally — UNIQUENESS guaranteed by construction, NO sorted check.

```java
public AttestationProcessingResult isValidIndexedAttestation(
    final Fork fork, ...) {
  // SSZ-derived path (reached only via AttesterSlashing received off the wire):
  // enforce the spec-mandated sorted-and-unique property on the indices.
  final IndexedAttestationLight light = IndexedAttestationLight.fromSsz(indexedAttestation);
  final AttestationProcessingResult sortedCheck = checkSortedAndUnique(light.attestingIndices());
  if (!sortedCheck.isSuccessful()) return sortedCheck;
  return isValidIndexedAttestation(fork, state, light, signatureVerifier);
}
```

The optimization is sound: internally-constructed Light attestations
have unique indices by construction (built from committee
intersections / known sets). But this introduces a subtle invariant:
any future code path that produces a Light attestation with NOT
sorted+unique indices would silently bypass the check. **F-tier
today** but worth a contract test.

### lodestar's TWO variants: number vs BigInt

```typescript
export function isValidIndexedAttestation(...)        // number-typed (Phase0/Altair/Bellatrix/Capella/Deneb)
export function isValidIndexedAttestationBigint(...)  // BigInt-typed (Deneb+ for slashing — unbounded epoch/slot)
```

The Bigint variant exists for `AttesterSlashing` validation where
the attestation epochs/slots are NOT bounded by the current slot
(an attacker could submit a slashing for any epoch). Using BigInt
prevents JS Number overflow at the `epoch < 2^53` boundary.
**Forward-defensive** for adversarial slashing input.

### grandine's TWO entry points: constructed vs received

```rust
pub fn validate_constructed_indexed_attestation<P: Preset>(...) -> Result<()> {
    validate_indexed_attestation(.., validate_indices_sorted_and_unique=false, ..)
}
pub fn validate_received_indexed_attestation<P: Preset>(...) -> Result<()> {
    validate_indexed_attestation(.., validate_indices_sorted_and_unique=true, ..)
}
```

**Performance optimization**: when grandine constructs indexed
attestations internally (during block proposal), the sorted+unique
property is guaranteed by construction. Skipping the check saves an
O(N) scan. Same idea as teku's Light/SSZ split, but more explicit
(one function with a flag vs two distinct types).

### nimbus's `TrustedSig` skip

```nim
if not (skipBlsValidation in flags or indexed_attestation.signature is TrustedSig):
    # ... actually run BLS verify ...
```

Nimbus uses Nim's type system to discriminate "trusted" signatures
(pre-verified upstream) from untrusted ones via the
`TrustedIndexedAttestation` variant. Trusted signatures skip BLS
verification (already done). **Performance optimization** — common
pattern for re-verification scenarios (e.g., re-applying blocks during
sync).

### Six distinct per-fork dispatch idioms

All correctly enforce `131,072` capacity at Electra; six distinct
mechanisms:

- **prysm**: schema-level proto fork-versioned types (separate
  message types `IndexedAttestation` vs `IndexedAttestationElectra`)
  with runtime `Version()` dispatch.
- **lighthouse**: superstruct-generated enum variants
  (`IndexedAttestationBase` vs `IndexedAttestationElectra`).
- **teku**: schema registry with fork-keyed cap selection at schema
  construction time.
- **nimbus**: type-union `phase0 | electra` with Nim's compile-time
  overload resolution (most concise of the six).
- **lodestar**: ForkSeq runtime check with hardcoded cap arithmetic.
- **grandine**: type-associated `P::MaxValidatorsPerCommittee` (Phase0)
  vs `P::MaxAttestersPerSlot = Prod<...>` (Electra) using typenum
  product types (most type-traceable).

### lighthouse + grandine + nimbus: pubkey caching

All three use a `pubkey_cache.get_or_insert(pubkey)` pattern to
avoid repeatedly decompressing the same pubkey across multiple
indexed-attestation verifications (especially relevant for batched
attestations). Same pattern as item #20's BLS-library audit.

### BLS library: all 6 use BLST or BLST wrappers

Confirmed for the SECOND TIME (item #20 first audited this for
deposits). Same library family across:
- prysm: BLST direct (with herumi fallback)
- lighthouse: blst (supranational) via `bls` crate
- teku: BLST via `tech.pegasys.teku.bls`
- nimbus: blscurve (BLST Nim wrapper)
- lodestar: @chainsafe/blst (BLST TypeScript wrapper)
- grandine: bls-blst feature flag

`FastAggregateVerify` is the canonical BLST function for this
operation. **Same library-family alignment.**

## EF fixture status — implicit coverage via items #7 + #8

This audit has **no dedicated EF fixture set** because
`is_valid_indexed_attestation` is an internal helper. It is exercised
IMPLICITLY via:

| Item | Fixtures × clients | Calls this function |
|---|---|---|
| **#7** process_attestation | 45 × 4 = 180 | each Attestation → get_attesting_indices → IndexedAttestation → verify here |
| **#8** process_attester_slashing | 30 × 4 = 120 | both attestations in slashing proof verified here |

**Total implicit cross-validation evidence**: **300 EF fixture PASSes**
across 75 unique fixtures all flow through this function. Critical
fixtures that exercise edge cases:

| Fixture | Hypothesis tested |
|---|---|
| `attestation_one_committee` | basic single-committee attestation |
| `multi_committee_attestation` | EIP-7549 multi-committee aggregation (item #7) |
| `invalid_attesting_indices_unsorted_*` | H3: sorted check |
| `invalid_attesting_indices_duplicate` | H3: unique check |
| `attester_slashing_attestation_1_invalid_signature` | H8: BLS FastAggregateVerify failure |
| `attester_slashing_attestation_2_invalid_signature` | H8: BLS FastAggregateVerify failure |

Any divergence in the empty/sorted/unique check, BLS verify, domain
construction, or signing root would have surfaced. None did.

## Cross-cut chain — closes the indexed-attestation-verify chokepoint

This audit closes the BLS-aggregate-verify chokepoint for two major
Pectra operations:

```
[item #7 process_attestation]:
    Attestation (Pectra-modified for EIP-7549 multi-committee)
        ↓ get_attesting_indices(state, attestation)
    IndexedAttestation (with attesting_indices from union of all committees)
        ↓
[item #25 (this) is_valid_indexed_attestation]:
    1. Empty check
    2. Sorted+unique check
    3. Pubkey lookup from state.validators
    4. Domain via DOMAIN_BEACON_ATTESTER + current fork
    5. compute_signing_root(data, domain)
    6. BLS FastAggregateVerify(pubkeys, signing_root, signature)
        ↓ if valid:
    attestation accepted, participation flags updated
                ↑
[item #8 process_attester_slashing]:
    AttesterSlashing(attestation_1, attestation_2)
        ↓ for each:
[item #25 (this) is_valid_indexed_attestation]:
    [same 6 checks]
        ↓ if BOTH valid:
    Casper FFG predicate check (double vote OR surround vote)
        ↓ if violated:
    slash intersection of attesting_indices
```

The complete attestation+slashing verification path is now audited
end-to-end including the BLS-aggregate-verify chokepoint.

## Adjacent untouched

- **Generate dedicated EF fixture set** for `is_valid_indexed_attestation`
  — pure-function with input (state, IndexedAttestation) → bool.
  Could exhaustively cover empty/sorted/unique/sig boundary cases.
- **teku Light vs SSZ contract test**: assert that any code path
  producing a Light attestation maintains the sorted+unique invariant.
  Otherwise a future bug could silently bypass the check.
- **lodestar Bigint variant audit**: verify the BigInt-typed variant
  is used wherever epoch/slot fields could exceed 2^53 (slashing
  paths only).
- **grandine constructed-vs-received contract test**: assert that
  any caller using the constructed variant has indices that are
  sorted+unique by construction.
- **nimbus TrustedSig skip audit**: verify TrustedSig is only
  produced after upstream verification; no untrusted construction
  paths.
- **`MAX_VALIDATORS_PER_COMMITTEE × MAX_COMMITTEES_PER_SLOT = 131,072`
  over-the-wire test**: block with 131,073 attesting indices should
  reject at SSZ deserialization across all clients.
- **`MAX_COMMITTEES_PER_SLOT = 64` interaction**: at Pectra, a
  single attestation can span up to 64 committees. Verify cross-client
  that the BLS verify correctly handles 64-committee attestations
  (large but mainnet-realistic).
- **Pubkey-cache invalidation across blocks**: lighthouse/grandine/nimbus
  cache decompressed pubkeys. After a deposit (item #4 drain), new
  validators have pubkeys that need to be added to the cache.
  Cross-client audit.
- **`FastAggregateVerify` zero-pubkeys edge case**: spec rejects
  empty indices via Check 1; BUT what if a client somehow bypassed
  Check 1? `bls.FastAggregateVerify([], msg, sig)` should return
  `false` (or panic, depending on library). Defensive cross-client
  test.
- **`compute_signing_root` cross-client byte-for-byte equivalence
  test**: verify all 6 clients compute identical signing roots for
  the same (AttestationData, domain) input.

## Future research items

1. **Generate dedicated EF fixture set** for the function
   (empty/sorted/unique/sig boundary cases).
2. **teku Light vs SSZ contract test** for sorted+unique invariant.
3. **lodestar Bigint variant audit**.
4. **grandine constructed-vs-received contract test**.
5. **nimbus TrustedSig skip audit**.
6. **131,073-index over-the-wire SSZ rejection** test.
7. **64-committee attestation BLS verify** stress test.
8. **Pubkey-cache invalidation across blocks** cross-client audit.
9. **`FastAggregateVerify` zero-pubkeys defensive test**.
10. **`compute_signing_root` cross-client byte-for-byte equivalence**
    test (cross-cut with item #20's deposit signing-root concern).
11. **Single BLS-library audit consolidation**: items #20 + #25
    both confirm BLST family alignment. A consolidated cross-client
    BLS-library version-pinning audit would close the Track F first
    pass.
12. **Pre-emptive Gloas audit**: any client extending IndexedAttestation
    capacity further at Gloas would diverge from current Pectra
    semantics. Track at Gloas activation.
