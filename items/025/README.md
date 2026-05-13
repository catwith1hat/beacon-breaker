---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [7, 8]
eips: [EIP-7549, EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 25: `is_valid_indexed_attestation` (Pectra-MODIFIED via SSZ-type capacity expansion)

## Summary

`is_valid_indexed_attestation(state, indexed_attestation) -> bool` is the BLS-aggregate-verify chokepoint for two major operations: item #7 (`process_attestation`, every Attestation → IndexedAttestation → verified here) and item #8 (`process_attester_slashing`, both attestations in the slashing proof). **Function body unchanged from Phase0**; the Pectra change is at the SSZ TYPE LEVEL — `IndexedAttestation.attesting_indices` capacity grew from `MAX_VALIDATORS_PER_COMMITTEE = 2048` to `MAX_VALIDATORS_PER_COMMITTEE × MAX_COMMITTEES_PER_SLOT = 131,072` (64×, EIP-7549 multi-committee aggregation).

**Pectra surface:** all six clients implement the function with identical observable semantics — empty rejection + strict-ascending sort (implying both sorted AND unique) + BLS `FastAggregateVerify`. H1–H9 hold. Six distinct sort+unique check idioms, six distinct per-fork dispatch mechanisms, all observable-equivalent. Carried forward divergences from the 2026-05-02 audit (teku's Light/SSZ split, lodestar's number/BigInt variants, grandine's constructed/received split, nimbus's TrustedSig skip) are documented optimisations, all spec-conformant.

**Gloas surface (at the Glamsterdam target): function unchanged. No `Modified is_valid_indexed_attestation` heading in `vendor/consensus-specs/specs/gloas/beacon-chain.md`; the `IndexedAttestation` container is NOT redefined at Gloas (the Electra `attesting_indices` cap of 131,072 carries forward unchanged). All six clients reuse their Electra implementation at Gloas via type-polymorphism (lighthouse superstruct `IndexedAttestationElectra`, nimbus type-union covering `electra.IndexedAttestation`, lodestar `ForkSeq.electra ↔ Gloas`, grandine `PostElectraBeaconState<P>` trait bound, teku `AttestationUtilGloas extends AttestationUtilElectra` without override, prysm proto-fork `IndexedAttestationElectra` reused).

**Gloas-NEW sister function (out of scope for this item):** `is_valid_indexed_payload_attestation` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:511-531`) is a NEW function for the EIP-7732 PTC (Payload-Timeliness Committee) surface. Same structural shape — non-empty + sorted indices + `bls.FastAggregateVerify` — but with `IndexedPayloadAttestation` container (cap = `PTC_SIZE`, not 131,072), `DOMAIN_PTC_ATTESTER` domain, and a SUBTLY DIFFERENT sort check: `sorted(indices)` (allows duplicates) instead of this item's `sorted(set(indices))` (rejects duplicates). Should be a separate audit item; flagged in Adjacent untouched.

**Item #22 H12 and item #23 H10 nimbus divergences do NOT propagate** — this function does not call `has_compounding_withdrawal_credential` (item #22) nor `get_pending_balance_to_withdraw` (item #23). It uses `get_domain(state, DOMAIN_BEACON_ATTESTER, target.epoch)` and `state.validators[i].pubkey` lookups, both of which are unchanged across all six clients at Gloas.

**Impact: none.** Eighth impact-none result in the recheck series. Propagation-without-amplification.

## Question

Pyspec (`vendor/consensus-specs/specs/phase0/beacon-chain.md`, unchanged at Electra/Fulu/Gloas at the function level; container modified at Electra per EIP-7549):

```python
def is_valid_indexed_attestation(state: BeaconState, indexed_attestation: IndexedAttestation) -> bool:
    """Check if ``indexed_attestation`` is not empty, has sorted and unique indices and has a valid aggregate signature."""
    indices = indexed_attestation.attesting_indices
    if len(indices) == 0 or not indices == sorted(set(indices)):
        return False
    pubkeys = [state.validators[i].pubkey for i in indices]
    domain = get_domain(state, DOMAIN_BEACON_ATTESTER, indexed_attestation.data.target.epoch)
    signing_root = compute_signing_root(indexed_attestation.data, domain)
    return bls.FastAggregateVerify(pubkeys, signing_root, indexed_attestation.signature)
```

Container modified at Electra (cap 2048 → 131,072):

```python
# Pre-Electra:
class IndexedAttestation(Container):
    attesting_indices: List[ValidatorIndex, MAX_VALIDATORS_PER_COMMITTEE]   # = 2048
    data: AttestationData
    signature: BLSSignature

# Electra+:
class IndexedAttestation(Container):
    attesting_indices: List[ValidatorIndex, MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT]  # = 2048 * 64 = 131072
    data: AttestationData
    signature: BLSSignature
```

Called from `process_attestation` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1709` — Gloas-Modified `process_attestation` still uses this assertion) and `process_attester_slashing` (both attestations).

Two recheck questions:
1. Pectra-surface invariants (H1–H9) — do all six clients still implement identical semantics with the carried-forward style optimisations?
2. **At Gloas (the new target)**: any client modify the function body or the container cap? Any new Gloas-specific dispatch path?

## Hypotheses

- **H1.** Function body unchanged from Phase0 (no Pectra-modified or Gloas-modified semantics in the spec).
- **H2.** Non-empty check: `len(indices) == 0` → return false.
- **H3.** Sort+unique check: strict ascending order (implies sorted AND unique).
- **H4.** SSZ list capacity at Electra+: `MAX_VALIDATORS_PER_COMMITTEE × MAX_COMMITTEES_PER_SLOT = 131,072` (mainnet preset). Unchanged at Gloas.
- **H5.** Pubkey lookup from `state.validators[i].pubkey` (cached per client).
- **H6.** Domain construction: `DOMAIN_BEACON_ATTESTER` + CURRENT fork (NOT pinned) + `target.epoch`.
- **H7.** `compute_signing_root(indexed_attestation.data, domain)` — signs `AttestationData` (NOT full `IndexedAttestation`).
- **H8.** BLS `FastAggregateVerify(pubkeys, signing_root, signature)` (NOT `Verify` or `AggregateVerify`).
- **H9.** Per-fork dispatch: pre-Electra (2048) vs Electra+ (131,072); six distinct dispatch idioms across clients.
- **H10.** *(Glamsterdam target — function body)*. `is_valid_indexed_attestation` is NOT modified at Gloas. No `Modified` heading in `vendor/consensus-specs/specs/gloas/beacon-chain.md`. The `IndexedAttestation` container is NOT redefined at Gloas (Electra type carries forward). All six clients reuse the Electra implementation at Gloas.
- **H11.** *(Glamsterdam target — Gloas-NEW sister function)*. `is_valid_indexed_payload_attestation` is a separate Gloas-NEW function (`vendor/consensus-specs/specs/gloas/beacon-chain.md:511-531`) for the EIP-7732 PTC surface. It operates on a distinct `IndexedPayloadAttestation` container, uses `DOMAIN_PTC_ATTESTER`, and applies a SLIGHTLY WEAKER check (`sorted(indices)` vs this item's `sorted(set(indices))`). Implemented in five clients (prysm, teku, nimbus, lodestar, grandine — Gloas-side); **missing in lighthouse** per items #14 H9 / #19 H10 / #22 H10 / #23 H8 / #24 propagation. Out of scope for THIS item.
- **H12.** *(Glamsterdam target — cross-cut with nimbus item #22 / #23 divergences)*. Neither item #22's stale `has_compounding_withdrawal_credential` nor item #23's stale `get_pending_balance_to_withdraw` is invoked from this function. The Gloas-target nimbus divergences do NOT propagate here.

## Findings

H1–H12 satisfied. **No divergence at the function body or per-client definition at either Pectra or Gloas surfaces.**

### prysm

`vendor/prysm/beacon-chain/core/blocks/attestation.go:236-280 VerifyIndexedAttestation`:

```go
func VerifyIndexedAttestation(ctx context.Context, beaconState state.ReadOnlyBeaconState, indexedAtt ethpb.IndexedAtt) error {
    ctx, span := trace.StartSpan(ctx, "core.VerifyIndexedAttestation")
    defer span.End()

    if err := attestation.IsValidAttestationIndices(ctx, indexedAtt, params.BeaconConfig().MaxValidatorsPerCommittee, params.BeaconConfig().MaxCommitteesPerSlot); err != nil {
        return err
    }
    // ... (pubkey lookup + domain + signing root + bls.FastAggregateVerify)
    return attestation.VerifyIndexedAttestationSig(ctx, indexedAtt, pubkeys, domain)
}
```

`IsValidAttestationIndices` at `vendor/prysm/beacon-chain/core/blocks/attestation.go:192`:

```go
return attestation.IsValidAttestationIndices(ctx, indexedAtt, params.BeaconConfig().MaxValidatorsPerCommittee, params.BeaconConfig().MaxCommitteesPerSlot)
```

`VerifyIndexedAttestationSig` at `vendor/prysm/proto/prysm/v1alpha1/attestation/attestation_utils.go:147-167` performs `bls.AggregatePubkeys` + `FastAggregateVerify`. `IsValidAttestationIndices` at `:192-221` implements the sort+unique check via pair-wise loop (`for i := 1; i < len; i++ { if indices[i-1] >= indices[i] error }`).

Per-fork dispatch at the proto type level: separate message types `IndexedAttestation` (cap 2048) vs `IndexedAttestationElectra` (cap 131,072) — both consumed via the `ethpb.IndexedAtt` interface, with cap selection at runtime via `len() vs MaxValidatorsPerCommittee * MaxCommitteesPerSlot`. **No Gloas-specific extension** — the Electra type carries forward.

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (131,072 unchanged at Gloas via the interface). H5 ✓ (state-cached pubkey lookup). H6 ✓ (`DOMAIN_BEACON_ATTESTER` from current fork). H7 ✓. H8 ✓ (`bls.FastAggregateVerify`). H9 ✓. H10 ✓. H11 ✓ (separate `core/gloas/payload_attestation.go` for the PTC sister). H12 ✓.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing/is_valid_indexed_attestation.rs:14-56`:

```rust
pub fn is_valid_indexed_attestation<E: EthSpec>(
    state: &BeaconState<E>,
    indexed_attestation: IndexedAttestationRef<E>,
    verify_signatures: VerifySignatures,
    spec: &ChainSpec,
) -> Result<()> {
    let indices = indexed_attestation.attesting_indices_to_vec();

    verify!(!indices.is_empty(), Invalid::IndicesEmpty);

    let check_sorted = |list: &[u64]| -> Result<()> {
        list.iter()
            .tuple_windows()
            .enumerate()
            .try_for_each(|(i, (x, y))| {
                if x < y { Ok(()) } else { Err(error(Invalid::BadValidatorIndicesOrdering(i))) }
            })?;
        Ok(())
    };
    check_sorted(&indices)?;

    if verify_signatures.is_true() {
        verify!(
            indexed_attestation_signature_set(state, |i| get_pubkey_from_state(state, i),
                indexed_attestation.signature(), indexed_attestation, spec)?
                .verify(),
            Invalid::BadSignature
        );
    }
    Ok(())
}
```

Generic over `BeaconState<E>` and `IndexedAttestationRef<E>` (a superstruct-derived ref). `itertools::tuple_windows()` + `try_for_each` strict-ascending check.

Per-fork dispatch via `superstruct` at `vendor/lighthouse/consensus/types/src/attestation/indexed_attestation.rs:24-66`:

```rust
#[superstruct(variants(Base, Electra), ...)]
pub struct IndexedAttestation<E: EthSpec> {
    #[superstruct(only(Base), partial_getter(rename = "attesting_indices_base"))]
    pub attesting_indices: VariableList<u64, E::MaxValidatorsPerCommittee>,
    #[superstruct(only(Electra), partial_getter(rename = "attesting_indices_electra"))]
    pub attesting_indices: VariableList<u64, E::MaxValidatorsPerSlot>,
    ...
}
```

Variants are `Base` and `Electra` ONLY — **no `Gloas` variant**. At Gloas, the `Electra` variant (cap = `MaxValidatorsPerSlot = MaxValidatorsPerCommittee × MaxCommitteesPerSlot = 131,072`) is used unchanged. `IndexedAttestation::to_electra(self)` (`:123-141`) safely up-converts a `Base` to `Electra` at fork-transition boundaries.

H1 ✓. H2 ✓. H3 ✓ (`tuple_windows().try_for_each(|(x, y)| x < y)`). H4 ✓ (`MaxValidatorsPerSlot` typenum, unchanged at Gloas). H5 ✓ (`get_pubkey_from_state` reads `state.validators[i].pubkey`). H6 ✓. H7 ✓. H8 ✓ (via `indexed_attestation_signature_set` → `bls::Signature::fast_aggregate_verify`). H9 ✓. H10 ✓ (Electra variant reused). **H11**: lighthouse Gloas-readiness gap propagation — no `is_valid_indexed_payload_attestation` function present (items #14 H9 / #19 H10 / #22 H10 / #23 H8 / #24 H11 cohort). Out of scope here. H12 ✓.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/common/util/AttestationUtil.java:196-217` (`checkSortedAndUnique`) + `:242-277` (`isValidIndexedAttestation`):

```java
final AttestationProcessingResult sortedCheck = checkSortedAndUnique(light.attestingIndices());
if (!sortedCheck.isSuccessful()) return sortedCheck;
return isValidIndexedAttestation(fork, state, light, signatureVerifier);
```

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/util/AttestationUtilElectra.java:127-180` provides the Electra-specific async wrapper that selects the 131,072 cap at schema-construction time.

**`AttestationUtilGloas extends AttestationUtilElectra`** at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/util/AttestationUtilGloas.java:36-110` — adds:
- `isValidIndexedPayloadAttestation` (`:52`) — Gloas-NEW PTC sister function (H11 scope, not this item).
- Three overrides: `validateCommitteeIndexValue`, `validatePayloadStatus`, `getGenericAttestationData` (committee-validity at Gloas with the `assert data.index < 2` Modified `process_attestation` rule).

**No override of `isValidIndexedAttestation`** — the Electra impl carries forward unchanged. The Light/SSZ split (sorted+unique enforced only at SSZ boundary; internally-constructed `IndexedAttestationLight` skips it as an optimisation) carries forward unchanged.

H1 ✓. H2 ✓. H3 ✓ (`checkSortedAndUnique` at SSZ boundary). H4 ✓ (`getMaxValidatorsPerAttestationElectra = 2048 × 64`). H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓ (no override in `AttestationUtilGloas`). H11 ✓ (separate `isValidIndexedPayloadAttestation`). H12 ✓.

### nimbus

`vendor/nimbus/beacon_chain/spec/beaconstate.nim:628-669`:

```nim
proc is_valid_indexed_attestation*(
    state: ForkyBeaconState,
    # phase0.SomeIndexedAttestation | electra.SomeIndexedAttestation:
    indexed_attestation:
      phase0.IndexedAttestation | phase0.TrustedIndexedAttestation |
      electra.IndexedAttestation | electra.TrustedIndexedAttestation,
    flags: UpdateFlags): Result[void, cstring] =
  template is_sorted_and_unique(s: untyped): bool =
    var res = true
    for i in 1 ..< s.len:
      if s[i - 1].uint64 >= s[i].uint64:
        res = false; break
    res

  if len(indexed_attestation.attesting_indices) == 0:
    return err("indexed_attestation: no attesting indices")

  # Not from spec, but this function gets used in front-line roles, not just behind firewall.
  let num_validators = state.validators.lenu64
  if anyIt(indexed_attestation.attesting_indices, it >= num_validators):
    return err("indexed attestation: not all indices valid validators")

  if not is_sorted_and_unique(indexed_attestation.attesting_indices):
    return err("indexed attestation: indices not sorted and unique")

  if not (skipBlsValidation in flags or indexed_attestation.signature is TrustedSig):
    let pubkeys = mapIt(
      indexed_attestation.attesting_indices, state.validators[it].pubkey)
    if not verify_attestation_signature(
        state.fork, state.genesis_validators_root, indexed_attestation.data,
        pubkeys, indexed_attestation.signature):
      return err("indexed attestation: signature verification failure")

  ok()
```

`state: ForkyBeaconState` covers Gloas (`vendor/nimbus/beacon_chain/spec/forks.nim:60-68` — `ForkyBeaconState = phase0.BeaconState | ... | electra.BeaconState | fulu.BeaconState | gloas.BeaconState`). `indexed_attestation` type-union covers `phase0` and `electra` variants — **no `gloas.IndexedAttestation` exists** because nimbus reuses `electra.IndexedAttestation` at Gloas (`vendor/nimbus/beacon_chain/spec/datatypes/gloas.nim` references `IndexedAttestation` from the electra namespace).

Extra defensive check: `anyIt(indices, it >= num_validators)` — rejects out-of-range indices BEFORE BLS verify. Defensive against malformed gossip input ("not from spec, but this function gets used in front-line roles"). All other clients also bounds-check pubkey lookup, but nimbus's check is earlier in the function flow.

`TrustedSig` skip via type discrimination (`indexed_attestation.signature is TrustedSig`) — performance optimisation for pre-verified upstream paths.

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (Electra type reused). H5 ✓. H6 ✓ (`state.fork` for domain). H7 ✓. H8 ✓ (`verify_attestation_signature` → BLS aggregate verify). H9 ✓. H10 ✓ (no Gloas redefinition). H11 ✓ — `is_valid_indexed_payload_attestation` defined separately and consumed at `state_transition_block.nim:767`. H12 ✓ (does not call `has_compounding_withdrawal_credential` nor `get_pending_balance_to_withdraw`).

### lodestar

`vendor/lodestar/packages/state-transition/src/block/isValidIndexedAttestation.ts:11-83`:

```typescript
export function isValidIndexedAttestation(
  config: BeaconConfig,
  pubkeyCache: PubkeyCache,
  stateSlot: Slot,
  validatorsLen: number,
  indexedAttestation: IndexedAttestation,
  verifySignature: boolean
): boolean {
  if (!isValidIndexedAttestationIndices(config, stateSlot, validatorsLen, indexedAttestation.attestingIndices)) {
    return false;
  }
  if (verifySignature) {
    return verifySignatureSet(getIndexedAttestationSignatureSet(config, stateSlot, indexedAttestation), pubkeyCache);
  }
  return true;
}

export function isValidIndexedAttestationIndices(
  config: BeaconConfig, stateSlot: Slot, validatorsLen: number, indices: number[]
): boolean {
  const maxIndices =
    config.getForkSeq(stateSlot) >= ForkSeq.electra
      ? MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT
      : MAX_VALIDATORS_PER_COMMITTEE;
  if (!(indices.length > 0 && indices.length <= maxIndices)) return false;

  let prev = -1;
  for (const index of indices) {
    if (index <= prev) return false;
    prev = index;
  }
  if (prev >= validatorsLen) return false;
  return true;
}
```

`config.getForkSeq(stateSlot) >= ForkSeq.electra` covers both Electra+ AND Gloas (forks are ordered `phase0 < altair < bellatrix < capella < deneb < electra < fulu < gloas`). Strict-ascending check via `prev`-tracking loop. Out-of-range check via the last-index test.

Companion `isValidIndexedAttestationBigint` variant at `:29-48` for `AttesterSlashing` where epochs/slots are unbounded.

**No Gloas-specific dispatch** — `ForkSeq.electra ↔ Gloas` covers both forks with the same 131,072 cap.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (`pubkeyCache.getPubkeyFromValidator(i)`). H6 ✓ (`config.getDomainAtSlot(stateSlot, DOMAIN_BEACON_ATTESTER, indexed.data.target.epoch)`). H7 ✓. H8 ✓ (`bls.verifyMultiple` underneath). H9 ✓. H10 ✓. H11 ✓ (separate `isValidIndexedPayloadAttestation` for the PTC surface). H12 ✓.

### grandine

`vendor/grandine/helper_functions/src/predicates.rs:91-165`:

```rust
pub fn validate_constructed_indexed_attestation<P: Preset>(
    config: &Config,
    state: &impl BeaconState<P>,
    indexed_attestation: &IndexedAttestation<P>,
    pubkey_cache: &PubkeyCache,
) -> Result<()> {
    validate_indexed_attestation(config, state, indexed_attestation, pubkey_cache, false)
}

pub fn validate_received_indexed_attestation<P: Preset>(...) -> Result<()> {
    validate_indexed_attestation(.., validate_indices_sorted_and_unique=true, ..)
}

fn validate_indexed_attestation<P: Preset>(
    config: &Config,
    state: &impl BeaconState<P>,
    indexed_attestation: &IndexedAttestation<P>,
    pubkey_cache: &PubkeyCache,
    validate_indices_sorted_and_unique: bool,
) -> Result<()> {
    let indices = indexed_attestation.attesting_indices;
    ensure!(!indices.is_empty(), AnyhowError::msg("indexed attestation has no attesting indices"));
    if validate_indices_sorted_and_unique {
        ensure!(
            indices.iter().tuple_windows().all(|(a, b)| a < b),
            AnyhowError::msg("indexed attestation indices not sorted and unique")
        );
    }
    // ... pubkey lookup via pubkey_cache.get_or_insert + bls fast_aggregate_verify ...
}
```

Two-public-entry-point design (`validate_constructed_*` vs `validate_received_*`) for the optimisation: constructed-internally attestations skip the sort+unique check. Same approach as teku's Light/SSZ split.

Per-fork capacity via `P::MaxValidatorsPerCommittee` (Phase0 = 2048) vs `P::MaxAttestersPerSlot = Prod<MaxValidatorsPerCommittee, MaxCommitteesPerSlot>` (Electra+ = 131,072) — typenum product types. **No Gloas-specific Preset extension** — Electra typenum carries forward.

Gloas-NEW sister function `is_valid_indexed_payload_attestation` (referenced at `vendor/grandine/helper_functions/src/signing.rs:457`) lives in a separate Gloas-only module.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (`bls::fast_aggregate_verify`). H9 ✓. H10 ✓. H11 ✓. H12 ✓.

## Cross-reference table

| Client | Function location | Sort+unique idiom | Per-fork dispatch | Gloas redefinition |
|---|---|---|---|---|
| prysm | `core/blocks/attestation.go:236-280 VerifyIndexedAttestation` + `attestation_utils.go:147-167 VerifyIndexedAttestationSig` + `:192-221 IsValidAttestationIndices` | imperative pair-wise loop `if indices[i-1] >= indices[i]` | proto fork-versioned types `IndexedAttestation` (2048) vs `IndexedAttestationElectra` (131,072), `ethpb.IndexedAtt` interface | none — Electra type reused at Gloas |
| lighthouse | `state_processing/src/per_block_processing/is_valid_indexed_attestation.rs:14-56` | `itertools::tuple_windows().try_for_each(|(x, y)| x < y)` | superstruct variants `Base` (2048) vs `Electra` (131,072 = `MaxValidatorsPerSlot`); no `Gloas` variant | none — Electra variant reused at Gloas |
| teku | `common/util/AttestationUtil.java:196-217 checkSortedAndUnique` + `:242-277 isValidIndexedAttestation` + `versions/electra/util/AttestationUtilElectra.java:127-180` async wrapper | imperative loop `index.isLessThanOrEqualTo(lastIndex)` (SSZ boundary only — `IndexedAttestationLight` skips); same in Electra | schema registry: `getMaxValidatorsPerAttestationPhase0(2048)` vs `getMaxValidatorsPerAttestationElectra(2048 × 64)` | `AttestationUtilGloas extends AttestationUtilElectra` adds PTC sister, does NOT override this function |
| nimbus | `spec/beaconstate.nim:628-669` (with `spec/signatures.nim:149-176 verify_attestation_signature` + `spec/crypto.nim` BLS) | `template is_sorted_and_unique` linear loop `s[i-1].uint64 >= s[i].uint64` | type-union `phase0.IndexedAttestation \| phase0.TrustedIndexedAttestation \| electra.IndexedAttestation \| electra.TrustedIndexedAttestation` (Nim compile-time overload resolution); `ForkyBeaconState` covers Gloas | none — `gloas.BeaconState` reuses `electra.IndexedAttestation` via type-union polymorphism |
| lodestar | `block/isValidIndexedAttestation.ts:11-83` (3 functions) + `signatureSets/indexedAttestation.ts:15-19` | monotonic loop `prev`-tracking | `config.getForkSeq(stateSlot) >= ForkSeq.electra ? MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT : MAX_VALIDATORS_PER_COMMITTEE` | none — `>= electra` covers both Electra and Gloas with the same 131,072 cap |
| grandine | `helper_functions/src/predicates.rs:91-123` (two public entry points) + `:125-165` (`validate_indexed_attestation`) | `itertools::tuple_windows().all(\|(a, b)\| a < b)` (controlled by `validate_indices_sorted_and_unique: bool` flag) | typenum `P::MaxValidatorsPerCommittee` (Phase0) vs `P::MaxAttestersPerSlot = Prod<MaxValidatorsPerCommittee, MaxCommitteesPerSlot>` (Electra+) | none — Electra typenum reused at Gloas |

## Empirical tests

### Pectra-surface implicit coverage (carried forward from prior audit)

No dedicated EF fixture set — `is_valid_indexed_attestation` is an internal helper. Exercised IMPLICITLY:

| Item | Fixtures × wired clients | Calls this function |
|---|---|---|
| #7 process_attestation | 45 × 4 = 180 | each Attestation → `get_attesting_indices` → IndexedAttestation → verified here |
| #8 process_attester_slashing | 30 × 4 = 120 | both attestations in slashing proof verified here |

**Cumulative Pectra implicit cross-validation evidence**: 300 EF fixture PASSes across 75 unique fixtures all flow through this function. The 6 distinct sort+unique idioms, 6 distinct per-fork dispatch mechanisms, and (for nimbus/grandine/teku) optimisation paths (TrustedSig/constructed/Light) are observable-equivalent at the implicit-fixture level.

### Gloas-surface

No Gloas-specific fixtures wired yet. H10 (function unchanged) and H12 (no nimbus item #22/#23 propagation) are source-only.

Concrete Gloas-spec evidence:
- `vendor/consensus-specs/specs/gloas/beacon-chain.md:1709` — `assert is_valid_indexed_attestation(state, get_indexed_attestation(state, attestation))` inside the Gloas-Modified `process_attestation`. The function name and signature are inherited from Electra unchanged.
- No `Modified is_valid_indexed_attestation` heading anywhere in `vendor/consensus-specs/specs/gloas/`.
- `vendor/consensus-specs/specs/gloas/beacon-chain.md:511-531` — Gloas-NEW `is_valid_indexed_payload_attestation` (separate function for the EIP-7732 PTC surface, H11 scope).

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — dedicated EF fixture set for the function).** Pure `(state, IndexedAttestation) → bool` fuzz. Boundary cases: empty indices, single-element, sorted unique, sorted with duplicate (sort+unique check fails), out-of-order, max-cap (131,072 indices), max-cap + 1 (SSZ deserialisation rejects). Cross-client byte-level equivalence.
- **T1.2 (Gloas-target — function unchanged).** Same fixtures from T1.1 but on Gloas state. Expected: identical results to Pectra (function inherited unchanged).

#### T2 — Adversarial probes
- **T2.1 (Glamsterdam-target — H10 verification).** Inject IndexedAttestation with 131,073 indices at Gloas. Expected: rejected at SSZ deserialisation (cap exceeded). All 6 clients. Confirms that no client widened the cap at Gloas.
- **T2.2 (Glamsterdam-target — 64-committee aggregation at Gloas).** Single IndexedAttestation spanning all 64 committees of a single slot (full multi-committee aggregation). Up to `MAX_VALIDATORS_PER_COMMITTEE × MAX_COMMITTEES_PER_SLOT = 131,072` validators. BLS `FastAggregateVerify` correctness under maximum-aggregation load. Cross-client byte-level equivalence on the aggregated signing root.
- **T2.3 (defensive — `bls.FastAggregateVerify` zero-pubkey edge).** Empty `indices` should be rejected at H2 (`len == 0`) BEFORE reaching BLS. But if a client erroneously skipped H2, the BLS call would be `bls.FastAggregateVerify([], msg, sig)` which the BLST library returns `false` for (per BLS spec for empty pubkey set). Cross-client defensive verification.
- **T2.4 (Glamsterdam-target — Gloas-NEW sister `is_valid_indexed_payload_attestation`).** Out of THIS item's scope; flagged as a separate audit. Same shape (non-empty + sorted indices + `FastAggregateVerify`) but DIFFERENT semantics: `sorted(indices)` (allows duplicates) vs this item's `sorted(set(indices))` (rejects duplicates). Audit the sister function for cross-client equivalence on the sort-only check.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Pectra-surface invariants (H1–H9) hold across all six. The 6 distinct sort+unique idioms (prysm imperative loop, lighthouse/grandine `tuple_windows`, teku Light/SSZ split, nimbus template, lodestar monotonic `prev`-track) and the 6 distinct per-fork dispatch mechanisms (prysm proto-type, lighthouse superstruct, teku schema registry, nimbus type-union, lodestar ForkSeq, grandine typenum) are all observable-equivalent. Optimisation paths (nimbus TrustedSig, grandine constructed/received, teku Light/SSZ, lodestar number/BigInt) are spec-conformant. 300 implicit EF fixture PASSes from items #7 + #8 cross-validate at Pectra without divergence.

**Glamsterdam-target finding (H10 — function unchanged).** `is_valid_indexed_attestation` is NOT modified at Gloas. No `Modified` heading in `vendor/consensus-specs/specs/gloas/beacon-chain.md`. The `IndexedAttestation` container is NOT redefined at Gloas — the Electra type (with `attesting_indices` cap of `MAX_VALIDATORS_PER_COMMITTEE × MAX_COMMITTEES_PER_SLOT = 131,072`) carries forward unchanged. All six clients reuse their Electra implementation at Gloas via type-polymorphism:
- prysm: `IndexedAttestationElectra` proto type reused via `ethpb.IndexedAtt` interface.
- lighthouse: `superstruct` variants are `Base` and `Electra` only; Electra is used at Gloas.
- teku: `AttestationUtilGloas extends AttestationUtilElectra` does NOT override `isValidIndexedAttestation`.
- nimbus: `ForkyBeaconState` covers `gloas.BeaconState`; `electra.IndexedAttestation` reused via type-union polymorphism.
- lodestar: `ForkSeq.electra` ↔ Gloas inclusive in the cap selector.
- grandine: `P::MaxAttestersPerSlot` typenum unchanged at Gloas.

**Eighth impact-none result** in the recheck series (after items #5, #10, #11, #18, #20, #21, #24). Propagation-without-amplification: the Gloas changes elsewhere (EIP-7732 ePBS routing, EIP-8061 churn rework) leave this function's body and container cap untouched.

**Cross-cut with item #22 / #23 nimbus divergences (H12 — no propagation).** This function does not call `has_compounding_withdrawal_credential` (item #22's stale Gloas-aware predicate) nor `get_pending_balance_to_withdraw` (item #23's stale Gloas-aware accessor). It uses `state.validators[i].pubkey` (cached pubkey lookup, unchanged across all forks) and `get_domain(state, DOMAIN_BEACON_ATTESTER, target.epoch)` (current-fork domain construction, unchanged across all forks). **Nimbus's mainnet-everyone divergences from items #22 and #23 do NOT propagate to this function.**

**Gloas-NEW sister function (H11 — out of scope, separate audit item).** `is_valid_indexed_payload_attestation` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:511-531`) is a NEW function for the EIP-7732 PTC (Payload-Timeliness Committee) surface. It is the structural sister of THIS item's function but operates on a different container (`IndexedPayloadAttestation` with `attesting_indices: List[ValidatorIndex, PTC_SIZE]`), uses a different domain (`DOMAIN_PTC_ATTESTER`), and applies a SUBTLY WEAKER sort check: `sorted(indices)` (allows duplicates) vs this item's `sorted(set(indices))` (rejects duplicates). The new function is implemented in five clients (prysm at `core/gloas/payload_attestation.go`, teku at `AttestationUtilGloas.java:52 isValidIndexedPayloadAttestation`, nimbus at `state_transition_block.nim:767`, lodestar at PTC modules, grandine at `signing.rs:457` and Gloas-specific predicates) and **missing in lighthouse** (propagation of items #14 H9 / #19 H10 / #22 H10 / #23 H8 / #24 H11 cohort — the broader Gloas-ePBS readiness gap). Should be a dedicated audit item targeting:
- The subtly weaker sort check (`sorted` vs `sorted(set(...))`) and whether `PTC_SIZE` makes duplicates safe in practice.
- The `DOMAIN_PTC_ATTESTER` domain (new `0x0C000000` per `vendor/consensus-specs/specs/gloas/beacon-chain.md:144`).
- The interaction with `state.builder_pending_payments` (PTC attestations gate builder payment settlement at item #7's Gloas-modified `process_attestation`).

**Notable per-client style differences (all observable-equivalent at both Pectra and Gloas):**
- **prysm**: split into 3 functions (`VerifyIndexedAttestation` orchestrator + `IsValidAttestationIndices` sort/unique + `VerifyIndexedAttestationSig` BLS). Most modular.
- **lighthouse**: `itertools::tuple_windows().try_for_each` — most Rust-idiomatic; safe `.get()` chaining throughout.
- **teku**: Light/SSZ split — sorted+unique enforced only at the SSZ boundary; internal Light attestations skip as an optimisation.
- **nimbus**: type-union polymorphism + template-based `is_sorted_and_unique`. Defensive out-of-range check before BLS.
- **lodestar**: monotonic `prev`-tracking loop. Companion `Bigint` variant for adversarial slashing input.
- **grandine**: two public entry points (`validate_constructed_*` vs `validate_received_*`) with a private flag-driven impl.

**No code-change recommendation.** Audit-direction recommendations:

- **Generate dedicated EF fixture set** for the function (T1.1 + T1.2) — cross-client byte-level equivalence at both Pectra and Gloas surfaces.
- **Generate dedicated EF fixture set for Gloas-NEW `is_valid_indexed_payload_attestation`** (T2.4) — separate sister audit. Highest priority for the PTC surface.
- **Cross-client BLS-library version-pinning audit** — items #20 and #25 both confirmed BLST family alignment (BLST direct, blst supranational, blst-jni, blscurve, @chainsafe/blst, bls-blst). Consolidate into a single Track F BLS-library audit covering version-pinning and ABI compatibility.
- **64-committee maximum-aggregation stress test** (T2.2) — verify cross-client correctness on full-cap aggregation at Gloas.
- **131,073-index SSZ-rejection test** (T2.1) — confirm no client widened the cap at Gloas.
- **Sister-item audit: lighthouse Gloas ePBS routing** — `is_valid_indexed_payload_attestation` missing in lighthouse is the fifth-or-sixth symptom of the items #14 H9 / #19 H10 / #22 H10 / #23 H8 / #24 H11 cohort.
- **`is_valid_indexed_payload_attestation` sort-check semantic divergence audit** — the spec's `sorted(indices)` (allows duplicates) vs this item's `sorted(set(indices))` (rejects). Document whether this is intentional given PTC_SIZE bounds and the gossip-validation upstream.

## Cross-cuts

### With item #7 (`process_attestation`) — Gloas-modified caller

Item #7's `process_attestation` is Modified at Gloas (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1685-1751`):
- `assert data.index < 2` (EIP-7732 PTC restriction on the committee_index encoding).
- New proposer-reward weighting tied to `state.builder_pending_payments` (EIP-7732 builder-payment settlement).
- New "will_set_new_flag" logic to ensure each validator contributes exactly once per slot.

But the call to `is_valid_indexed_attestation(state, get_indexed_attestation(state, attestation))` at `:1709` is UNCHANGED — the same predicate signature, same input transformation. This item's surface is unaffected by item #7's Gloas modifications.

### With item #8 (`process_attester_slashing`) — Gloas-unchanged caller

Item #8 is inherited from Electra at Gloas (no `Modified process_attester_slashing` heading). Both `attestation_1` and `attestation_2` are verified by this function. Unchanged at Gloas.

### With items #22 / #23 nimbus divergences

Per H12 finding: neither `has_compounding_withdrawal_credential` (item #22) nor `get_pending_balance_to_withdraw` (item #23) is invoked from this function. The pubkey lookup uses `state.validators[i].pubkey` (item #22's strict-`0x01` predicate is irrelevant here); the domain uses `DOMAIN_BEACON_ATTESTER` (no validator credentials involved); the BLS verify is purely cryptographic. Nimbus's mainnet-everyone divergences at items #22 and #23 do NOT propagate to this function.

### With Gloas-NEW `is_valid_indexed_payload_attestation` sister (H11)

Out of scope for this item. The PTC (Payload-Timeliness Committee) attestation surface introduced by EIP-7732 has its own indexed-attestation predicate at `vendor/consensus-specs/specs/gloas/beacon-chain.md:511-531`. Lighthouse Gloas-readiness gap propagates here — no `is_valid_indexed_payload_attestation` in lighthouse. Same five-vs-one cohort as items #14 H9 / #19 H10 / #22 H10 / #23 H8 / #24 H11.

### With item #14 H9 / item #19 H10 / item #22 H10 / item #23 H8 / item #24 H11 cohort

The cumulative lighthouse Gloas-ePBS-readiness gap propagates into this item's H11 (Gloas-NEW sister function missing in lighthouse). Single-cause fix upstream (lighthouse wires the EIP-7732 ePBS surface) closes all six symptoms.

## Adjacent untouched

1. **Generate dedicated EF fixture set for the function** — `(state, IndexedAttestation) → bool` boundary cases (empty/sorted/unique/sig/max-cap). Pure-function cross-client byte-level equivalence.
2. **Generate dedicated EF fixture set for Gloas-NEW `is_valid_indexed_payload_attestation`** — separate sister audit. Covers the `sorted(indices)` vs `sorted(set(indices))` semantic difference at the PTC surface.
3. **Cross-client BLS-library version-pinning audit** — consolidate items #20 + #25 findings; verify all 6 BLST/wrapper libraries are at compatible versions with no ABI drift.
4. **64-committee maximum-aggregation stress test** at Gloas — full-cap (131,072 indices) BLS aggregate verify cross-client.
5. **131,073-index SSZ-rejection test** at Gloas — confirm no client widened the cap.
6. **Sister-item audit: lighthouse Gloas ePBS routing** for `is_valid_indexed_payload_attestation` and the broader PTC surface (items #14/#19/#22/#23/#24 cohort).
7. **teku Light/SSZ contract test** — assert any code path producing a `IndexedAttestationLight` maintains sorted+unique by construction. Forward-fragility hedge.
8. **lodestar `isValidIndexedAttestationBigint` usage audit** — verify it's used wherever epoch/slot fields could exceed 2^53 (slashing paths only).
9. **grandine constructed-vs-received contract test** — assert any caller using the constructed variant has indices that are sorted+unique by construction.
10. **nimbus `TrustedSig` skip audit** — verify `TrustedSig` is only produced after upstream verification; no untrusted construction paths.
11. **`compute_signing_root` cross-client byte-for-byte equivalence test** — same `(AttestationData, domain)` input across all 6 clients; assert identical signing roots. Cross-cut with item #20's deposit signing-root audit.
12. **`FastAggregateVerify` zero-pubkey defensive cross-client test** — H2 should reject empty before BLS, but if bypassed, all 6 BLST libraries should return false for empty pubkey set.
13. **Pubkey-cache invalidation across blocks** — lighthouse/grandine/nimbus cache decompressed pubkeys; after a deposit drain (item #4), new validators' pubkeys must be added. Cross-client audit.
14. **`is_valid_indexed_payload_attestation` sort-check semantic divergence audit** — the spec's `sorted(indices)` (allows duplicates) vs this item's `sorted(set(indices))` (rejects). Document the intent and cross-cut with PTC gossip-validation upstream.
15. **EIP-7732 PTC committee size (PTC_SIZE) confirmation** — verify all 6 clients agree on the PTC_SIZE constant at Gloas, since it gates the new sister function's input.
