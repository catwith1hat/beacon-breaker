---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [1, 11]
eips: [EIP-7251, EIP-7732]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 27: `get_next_sync_committee_indices` (Pectra-MODIFIED + Gloas-MODIFIED for balance-weighted sync committee selection)

## Summary

`get_next_sync_committee_indices` selects 512 validators (with duplicates) for the next sync committee via balance-weighted random sampling. Pectra modified the inline algorithm to use 16-bit random precision and `MAX_EFFECTIVE_BALANCE_ELECTRA = 2048 ETH` for the 64×-larger ceiling vs Phase0's 8-bit + 32 ETH. **Gloas modifies the function again** — but only to delegate to a NEW helper `compute_balance_weighted_selection(state, indices, seed, size, shuffle_indices)` that is **algorithmically identical** to the Pectra inline body (`vendor/consensus-specs/specs/gloas/beacon-chain.md:603-639` for the helper; `:685-702` for the modified call site).

**Pectra surface:** all six clients implement the 16-bit + 2048 ETH algorithm with identical observable behaviour. H1–H9 hold. Six distinct constant-naming conventions, six distinct LE-decode idioms, and three clients (teku, lodestar, grandine) already use the "hash recompute only every 16 iterations" optimization that Gloas formalizes.

**Gloas surface (at the Glamsterdam target): observable-equivalent across all six clients.** The Gloas spec's `compute_balance_weighted_selection` helper is mathematically the same algorithm as the Pectra inline body — same iteration pattern, same hash preimage `seed + uint_to_bytes(i // 16)`, same offset formula `(i % 16) * 2`, same `MAX_RANDOM_VALUE = 65535`, same `MAX_EFFECTIVE_BALANCE_ELECTRA` ceiling, same predicate `effective_balance * MAX_RANDOM_VALUE >= MAX_EFFECTIVE_BALANCE_ELECTRA * random_value`. The Gloas formulation adds two formal optimizations (hash caching across 16 iterations, pre-fetched `effective_balances` list) and a `shuffle_indices: bool` parameter to enable reuse by `compute_ptc` (PTC selection without shuffling) and `compute_proposer_indices` (single-validator selection with shuffling). For sync committee selection (`shuffle_indices=True, size=SYNC_COMMITTEE_SIZE`), the output is byte-for-byte identical to the Pectra inline body.

**3-vs-3 client split on Gloas wiring (all observable-equivalent):**
- **Three clients (lighthouse, teku, grandine) introduce a separate Gloas code path** that calls `compute_balance_weighted_selection` explicitly — spec-faithful at the source level.
- **Three clients (prysm, nimbus, lodestar) reuse their Pectra inline algorithm at Gloas** — observable-equivalent because the algorithms produce identical output; forward-fragility concern if the spec ever introduces a subtle behavioral difference in `compute_balance_weighted_selection`.

**Cross-cut sister functions Gloas-modified via the same helper** (`compute_proposer_indices`, `compute_ptc`) — separate audit items. Items #22 / #23 nimbus divergences do NOT propagate here (this function does not call `has_compounding_withdrawal_credential` nor `get_pending_balance_to_withdraw`).

**Impact: none.** Tenth impact-none result in the recheck series. All six clients produce identical sync committees at Gloas under the current spec.

## Question

Pyspec Pectra-Modified body (`vendor/consensus-specs/specs/electra/beacon-chain.md:646-668`, expanded inline before the Gloas re-factoring):

```python
def get_next_sync_committee_indices(state: BeaconState) -> Sequence[ValidatorIndex]:
    epoch = Epoch(get_current_epoch(state) + 1)
    MAX_RANDOM_VALUE = 2**16 - 1                                  # 16-bit
    active_validator_indices = get_active_validator_indices(state, epoch)
    active_validator_count = uint64(len(active_validator_indices))
    seed = get_seed(state, epoch, DOMAIN_SYNC_COMMITTEE)
    i = uint64(0)
    sync_committee_indices: List[ValidatorIndex] = []
    while len(sync_committee_indices) < SYNC_COMMITTEE_SIZE:
        shuffled_index = compute_shuffled_index(uint64(i % active_validator_count), active_validator_count, seed)
        candidate_index = active_validator_indices[shuffled_index]
        random_bytes = hash(seed + uint_to_bytes(i // 16))
        offset = i % 16 * 2
        random_value = bytes_to_uint64(random_bytes[offset : offset + 2])
        effective_balance = state.validators[candidate_index].effective_balance
        if effective_balance * MAX_RANDOM_VALUE >= MAX_EFFECTIVE_BALANCE_ELECTRA * random_value:
            sync_committee_indices.append(candidate_index)
        i += 1
    return sync_committee_indices
```

Pyspec Gloas-Modified (`vendor/consensus-specs/specs/gloas/beacon-chain.md:685-702`):

```python
def get_next_sync_committee_indices(state: BeaconState) -> Sequence[ValidatorIndex]:
    epoch = Epoch(get_current_epoch(state) + 1)
    seed = get_seed(state, epoch, DOMAIN_SYNC_COMMITTEE)
    indices = get_active_validator_indices(state, epoch)
    return compute_balance_weighted_selection(
        state, indices, seed, size=SYNC_COMMITTEE_SIZE, shuffle_indices=True
    )
```

Pyspec Gloas-NEW helper (`vendor/consensus-specs/specs/gloas/beacon-chain.md:603-639`):

```python
def compute_balance_weighted_selection(
    state: BeaconState,
    indices: Sequence[ValidatorIndex],
    seed: Bytes32,
    size: uint64,
    shuffle_indices: bool,
) -> Sequence[ValidatorIndex]:
    MAX_RANDOM_VALUE = 2**16 - 1
    total = uint64(len(indices))
    assert total > 0
    effective_balances = [state.validators[index].effective_balance for index in indices]
    selected: List[ValidatorIndex] = []
    i = uint64(0)
    while len(selected) < size:
        offset = i % 16 * 2
        if offset == 0:
            random_bytes = hash(seed + uint_to_bytes(i // 16))
        next_index = i % total
        if shuffle_indices:
            next_index = compute_shuffled_index(next_index, total, seed)
        weight = effective_balances[next_index] * MAX_RANDOM_VALUE
        random_value = bytes_to_uint64(random_bytes[offset : offset + 2])
        threshold = MAX_EFFECTIVE_BALANCE_ELECTRA * random_value
        if weight >= threshold:
            selected.append(indices[next_index])
        i += 1
    return selected
```

**Algorithmic equivalence (for `shuffle_indices=True, size=SYNC_COMMITTEE_SIZE`):**
- Same iteration pattern (i = 0, 1, 2, ...).
- Same `random_bytes = hash(seed + uint_to_bytes(i // 16))` preimage (Gloas caches by only recomputing when `offset == 0`, but the preimage values are identical for any given i).
- Same `offset = (i % 16) * 2` and `random_value = bytes_to_uint64(random_bytes[offset : offset + 2])`.
- Same `compute_shuffled_index(i % total, total, seed)` for the next_index lookup (Gloas computes `next_index = i % total` first, then conditionally shuffles — equivalent to Pectra's direct call).
- Same predicate `effective_balance * MAX_RANDOM_VALUE >= MAX_EFFECTIVE_BALANCE_ELECTRA * random_value` (Gloas spells it as `weight >= threshold` with `weight = eb * MAX_RV`, `threshold = MAX_EB * rv`).
- Same `append(indices[next_index])` (Pectra uses `candidate_index = active_validator_indices[shuffled_index]` which expands to the same thing).

**Output is byte-for-byte identical to the Pectra inline body for any given input state.**

Three recheck questions:
1. Pectra-surface invariants (H1–H9) — do all six clients still implement the 16-bit + 2048 ETH algorithm?
2. **At Gloas (the new target)**: which clients wire the new `compute_balance_weighted_selection` helper, vs which reuse the Pectra inline body? Both options observable-equivalent under current spec.
3. Is `compute_balance_weighted_selection` introducing any subtle behavioral difference that the equivalence claim missed?

## Hypotheses

- **H1.** `MAX_RANDOM_VALUE = 2^16 - 1 = 65535` (Pectra and Gloas; was `MAX_RANDOM_BYTE = 255` at Altair).
- **H2.** `MAX_EFFECTIVE_BALANCE_ELECTRA = 2_048_000_000_000 Gwei = 2048 ETH` (Pectra and Gloas; was 32 ETH).
- **H3.** Hash indexing: `i // 16` denominator (Pectra and Gloas; was `i // 32` at Altair).
- **H4.** Offset calculation: `(i % 16) * 2` for 2-byte stride (Pectra and Gloas).
- **H5.** `bytes_to_uint64(random_bytes[offset : offset + 2])` little-endian 2-byte decode.
- **H6.** Selection predicate: `effective_balance * MAX_RANDOM_VALUE >= MAX_EFFECTIVE_BALANCE_ELECTRA * random_value` (Pectra and Gloas).
- **H7.** While-loop terminates when `len(sync_committee_indices) == SYNC_COMMITTEE_SIZE = 512`.
- **H8.** Per-fork dispatch: pre-Electra (8-bit + 32 ETH); Electra+ (16-bit + 2048 ETH); Gloas (same 16-bit + 2048 ETH via `compute_balance_weighted_selection`).
- **H9.** Result list may contain duplicates (same validator selected multiple times — proportional to weight); preserved across forks.
- **H10.** *(Glamsterdam target — function shape)*. `get_next_sync_committee_indices` IS modified at Gloas (`vendor/consensus-specs/specs/gloas/beacon-chain.md:685-702` "Modified `get_next_sync_committee_indices`") — the body now delegates to the NEW helper `compute_balance_weighted_selection(state, indices, seed, size=SYNC_COMMITTEE_SIZE, shuffle_indices=True)` (`:603-639`). **Algorithmically equivalent to the Pectra inline body**: same iteration, same hash preimage, same offset, same predicate, same MAX_RANDOM_VALUE, same MAX_EFFECTIVE_BALANCE_ELECTRA. Output byte-for-byte identical for any given input state.
- **H11.** *(Glamsterdam target — per-client Gloas wiring)*. Three clients (lighthouse, teku, grandine) wire a separate Gloas code path calling `compute_balance_weighted_selection`. Three clients (prysm, nimbus, lodestar) reuse the Pectra inline algorithm at Gloas via type-polymorphism (`fork >= ForkSeq.electra`, generic `electra | fulu | gloas` state types). Both wirings are observable-equivalent.
- **H12.** *(Glamsterdam target — cross-cut sister Gloas-modified functions)*. The same `compute_balance_weighted_selection` helper is consumed at Gloas by `compute_proposer_indices` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:647-661`) and `compute_ptc` (`:663-680`). Each is a separate Gloas-modified or Gloas-NEW function meriting its own audit item. For THIS item's surface (sync committee), only the validator-side selection logic is in scope.
- **H13.** *(Glamsterdam target — cross-cut with item #22 / #23 nimbus divergences)*. This function does not invoke `has_compounding_withdrawal_credential` (item #22) nor `get_pending_balance_to_withdraw` (item #23). The Pectra-target nimbus mainnet-everyone divergences do NOT propagate to sync committee selection. The function uses `effective_balance` field directly, which is set by item #1's `process_effective_balance_updates` — and item #1's nimbus H12 divergence (mainnet-everyone via 0x03 validators) DOES potentially propagate INDIRECTLY: if nimbus computes a different `effective_balance` for a 0x03-credentialled validator (per item #22 H12), the sync committee selection probability would differ. **Indirect propagation through `effective_balance`**.

## Findings

H1–H13 satisfied. **No direct divergence at this function's surface across Pectra or Gloas; indirect propagation from item #22 H12 / item #1's effective_balance computation is the only Gloas-target concern.**

### prysm

`vendor/prysm/beacon-chain/core/altair/sync_committee.go:111-168 NextSyncCommitteeIndices`:

```go
func NextSyncCommitteeIndices(ctx context.Context, s state.BeaconState) ([]primitives.ValidatorIndex, error) {
    epoch := coreTime.NextEpoch(s)
    indices, err := helpers.ActiveValidatorIndices(ctx, s, epoch)
    // ... seed setup ...
    seedBuffer := make([]byte, len(seed)+8)
    copy(seedBuffer, seed[:])

    for i := primitives.ValidatorIndex(0); uint64(len(cIndices)) < syncCommitteeSize; i++ {
        sIndex, err := helpers.ComputeShuffledIndex(i.Mod(count), count, seed, true)
        // ...
        cIndex := indices[sIndex]
        v, err := s.ValidatorAtIndexReadOnly(cIndex)
        effectiveBal := v.EffectiveBalance()

        if s.Version() >= version.Electra {
            binary.LittleEndian.PutUint64(seedBuffer[len(seed):], uint64(i/16))
            randomByte := hashFunc(seedBuffer)
            offset := (i % 16) * 2
            randomValue := uint64(randomByte[offset]) | uint64(randomByte[offset+1])<<8

            if effectiveBal*fieldparams.MaxRandomValueElectra >= cfg.MaxEffectiveBalanceElectra*randomValue {
                cIndices = append(cIndices, cIndex)
            }
        } else {
            // Phase0/Altair path (8-bit + 32 ETH)
            binary.LittleEndian.PutUint64(seedBuffer[len(seed):], uint64(i/32))
            randomByte := hashFunc(seedBuffer)[i%32]
            if effectiveBal*fieldparams.MaxRandomByte >= cfg.MaxEffectiveBalance*uint64(randomByte) {
                cIndices = append(cIndices, cIndex)
            }
        }
    }
    return cIndices, nil
}
```

**Single function with `s.Version() >= version.Electra` runtime branch** — no separate Gloas code path. At Gloas, the Electra branch fires (since `version.Gloas > version.Electra`), producing the same output as the Gloas spec's `compute_balance_weighted_selection(shuffle_indices=True)`.

A `compute_balance_weighted_selection` reference exists in prysm at `vendor/prysm/beacon-chain/core/gloas/payload_attestation.go:119, 193` (within comments and spec-references) — used for the Gloas-NEW `compute_ptc` (item #12 sister). Not consumed from THIS function. Algorithmic equivalence is the basis for observable-equivalence at Gloas.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (bitwise OR + shift LE decode). H6 ✓ (`MaxRandomValueElectra` constant). H7 ✓. H8 ✓. H9 ✓ (duplicates preserved). H10 ✓ (observable-equivalent). H11: **reuses Pectra inline algorithm at Gloas** (3-vs-3 split, prysm on the reuse side). H12 ✓ (sister functions in `core/gloas/`). H13 ✓ at this function level; **indirect propagation from item #22 H12** through `v.EffectiveBalance()` if validator's effective_balance is divergent.

### lighthouse

`vendor/lighthouse/consensus/types/src/state/beacon_state.rs:1396-1447 get_next_sync_committee_indices` (with helper at `:2979`):

```rust
pub fn get_next_sync_committee_indices(
    &self,
    spec: &ChainSpec,
) -> Result<Vec<ValidatorIndex>, Error> {
    // ...
    if self.fork_name_unchecked().gloas_enabled() {
        self.compute_balance_weighted_selection(
            &active_validator_indices,
            &seed,
            E::SyncCommitteeSize::to_u64() as usize,
            true,  // shuffle_indices
            spec,
        )
    } else {
        // Pectra-inline path (with electra_enabled() / pre-Electra branch below)
        // ... [existing 16-bit + 2048 ETH algorithm or 8-bit + 32 ETH for pre-Electra] ...
    }
}

fn compute_balance_weighted_selection(
    &self,
    indices: &[u64],
    seed: &Hash256,
    size: usize,
    shuffle_indices: bool,
    spec: &ChainSpec,
) -> Result<Vec<u64>, Error> {
    // Direct port of spec function:
    // - MAX_RANDOM_VALUE = u16::MAX
    // - Cache hash when offset == 0
    // - Pre-fetch effective_balances
    // - shuffle_indices branch via if shuffle_indices { compute_shuffled_index(...) } else { ... }
    // ...
}
```

**Explicit Gloas branch** via `self.fork_name_unchecked().gloas_enabled()` runtime check (`:1405`). Calls the new `compute_balance_weighted_selection` method (`:2979`) which is a direct port of the Gloas spec function. Also used at `:1140` for `compute_proposer_indices` (Gloas-modified) and at `:2949` for `compute_ptc` (Gloas-NEW PTC selection).

Spec-faithful Gloas wiring. At Pectra, falls through to the existing 16-bit + 2048 ETH inline algorithm (or 8-bit + 32 ETH pre-Electra).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11: **explicit Gloas branch** (3-vs-3 split, lighthouse on the explicit-wiring side). H12 ✓. H13 ✓.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/helpers/BeaconStateAccessorsGloas.java:286-295`:

```java
@Override
public IntList getNextSyncCommitteeIndices(final BeaconState state) {
    final UInt64 epoch = getCurrentEpoch(state).plus(1);
    final IntList activeValidatorIndices = getActiveValidatorIndices(state, epoch);
    final int activeValidatorCount = activeValidatorIndices.size();
    checkArgument(activeValidatorCount > 0, "Provided state has no active validators");
    final Bytes32 seed = getSeed(state, epoch, Domain.SYNC_COMMITTEE);
    return miscHelpersGloas.computeBalanceWeightedSelection(
        state, activeValidatorIndices, seed, configElectra.getSyncCommitteeSize(), true);
}
```

The Gloas-specific helper `BeaconStateAccessorsGloas extends BeaconStateAccessorsElectra` overrides `getNextSyncCommitteeIndices` to delegate to `miscHelpersGloas.computeBalanceWeightedSelection` (defined at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/helpers/MiscHelpersGloas.java:129`).

The same `computeBalanceWeightedSelection` is also invoked from `MiscHelpersGloas.java:116` for `compute_proposer_indices` (Gloas-modified) and from `BeaconStateAccessorsGloas.java:165` for `compute_ptc` (Gloas-NEW PTC, line 165 — `configGloas.getPtcSize(), false`). All three Gloas-spec call sites are correctly wired.

**Spec-faithful Gloas wiring.** Subclass-override polymorphism (5-level inheritance chain: `BeaconStateAccessors → Altair → Deneb → Electra → Gloas`).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11: **explicit Gloas branch** (subclass override). H12 ✓ (sister functions wired). H13 ✓.

### nimbus

`vendor/nimbus/beacon_chain/spec/beaconstate.nim:1423-1464 get_next_sync_committee_keys`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-alpha.0/specs/electra/beacon-chain.md#modified-get_next_sync_committee_indices
func get_next_sync_committee_keys(
    state: electra.BeaconState | fulu.BeaconState | gloas.BeaconState):
    array[SYNC_COMMITTEE_SIZE, ValidatorPubKey] =
  let epoch = get_current_epoch(state) + 1
  const MAX_RANDOM_VALUE = 65536 - 1  # [Modified in Electra]
  let
    active_validator_indices = get_active_validator_indices(state, epoch)
    active_validator_count = uint64(len(active_validator_indices))
    seed = get_seed(state, epoch, DOMAIN_SYNC_COMMITTEE)
  var
    i = 0'u64
    index = 0
    res: array[SYNC_COMMITTEE_SIZE, ValidatorPubKey]
    hash_buffer: array[40, byte]
    rv_buf: array[8, byte]
  hash_buffer[0..31] = seed.data
  while index < SYNC_COMMITTEE_SIZE:
    hash_buffer[32..39] = uint_to_bytes(uint64(i div 16))
    let
      shuffled_index = compute_shuffled_index(
        uint64(i mod active_validator_count), active_validator_count, seed)
      candidate_index = active_validator_indices[shuffled_index]
      random_bytes = eth2digest(hash_buffer).data
      offset = (i mod 16) * 2
      effective_balance = state.validators[candidate_index].effective_balance
    rv_buf[0 .. 1] = random_bytes.toOpenArray(offset, offset + 1)
    let random_value = bytes_to_uint64(rv_buf)
    if effective_balance * MAX_RANDOM_VALUE >=
        MAX_EFFECTIVE_BALANCE_ELECTRA.Gwei * random_value:
      res[index] = state.validators[candidate_index].pubkey
      inc index
    i += 1'u64
  res
```

Generic over `electra.BeaconState | fulu.BeaconState | gloas.BeaconState` — single body covers all three forks. **Uses the Pectra inline algorithm at Gloas** (no separate Gloas branch, no call to a separate `compute_balance_weighted_selection`).

Nimbus's `compute_balance_weighted_selection` does exist at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:3019` but is used by `get_ptc` (Gloas-NEW PTC selection) — NOT consumed by `get_next_sync_committee_keys`.

Note: nimbus returns the SYNC_COMMITTEE pubkeys directly (`array[SYNC_COMMITTEE_SIZE, ValidatorPubKey]`) rather than indices. Equivalent output once mapped through `state.validators[idx].pubkey`. The Pectra inline algorithm produces the same indices, then pubkeys, as the Gloas helper would.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (toOpenArray slice + bytes_to_uint64). H6 ✓. H7 ✓. H8 ✓. H9 ✓ (duplicates preserved via `res[index]` accumulation, same as spec). H10 ✓ (observable-equivalent). H11: **reuses Pectra inline algorithm at Gloas** (3-vs-3 split, nimbus on the reuse side). H12 ✓ (`compute_balance_weighted_selection` available, used by `get_ptc` but not this function). H13 ✓ at this function level; **indirect propagation from item #22 H12** through `state.validators[idx].effective_balance` if the validator's effective_balance is divergent at Gloas.

### lodestar

`vendor/lodestar/packages/state-transition/src/util/seed.ts:240-269 getNextSyncCommitteeIndices`:

```typescript
export function getNextSyncCommitteeIndices(
  fork: ForkSeq,
  state: BeaconStateAllForks,
  activeValidatorIndices: Uint32Array,
  effectiveBalanceIncrements: EffectiveBalanceIncrements
): Uint32Array {
  let maxEffectiveBalance: number;
  let randByteCount: number;

  if (fork >= ForkSeq.electra) {
    maxEffectiveBalance = MAX_EFFECTIVE_BALANCE_ELECTRA;
    randByteCount = 2;
  } else {
    maxEffectiveBalance = MAX_EFFECTIVE_BALANCE;
    randByteCount = 1;
  }

  const epoch = computeEpochAtSlot(state.slot) + 1;
  const seed = getSeed(state, epoch, DOMAIN_SYNC_COMMITTEE);
  return nativeComputeSyncCommitteeIndices(
    seed, activeValidatorIndices, effectiveBalanceIncrements,
    randByteCount, SYNC_COMMITTEE_SIZE, maxEffectiveBalance,
    EFFECTIVE_BALANCE_INCREMENT, SHUFFLE_ROUND_COUNT
  );
}
```

**`fork >= ForkSeq.electra` lower-bound check covers both Electra and Gloas** with the same Pectra inline algorithm (16-bit + 2048 ETH). Delegates to native WASM `nativeComputeSyncCommitteeIndices` with `randByteCount = 2` for the 16-bit decode. No separate Gloas branch.

Search for a separate `getNextSyncCommitteeIndicesGloas` returns nothing in `vendor/lodestar/`. Lodestar's `computeBalanceWeightedSelection` analog (if any) would live in PTC-specific files for `compute_ptc`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (handled in native code). H5 ✓ (handled in native code). H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓ (observable-equivalent). H11: **reuses Pectra inline algorithm at Gloas** (3-vs-3 split, lodestar on the reuse side). H12: sister `compute_ptc` would have its own wiring (out of scope). H13 ✓ at this function level; **indirect propagation from item #22 H12** through `effectiveBalanceIncrements` cache.

### grandine

`vendor/grandine/helper_functions/src/accessors.rs:597-607` (dispatcher) + `:609-655` (pre-Electra) + `:657-705` (post-Electra) + `:707-729` (**post-Gloas**):

```rust
fn get_next_sync_committee_indices<P: Preset>(state: ...) -> Result<...> {
    if state.is_post_gloas() {
        get_next_sync_committee_indices_post_gloas(state)
    } else if state.is_post_electra() {
        get_next_sync_committee_indices_post_electra(state)
    } else {
        get_next_sync_committee_indices_pre_electra(state)
    }
}

fn get_next_sync_committee_indices_post_gloas<P: Preset>(
    state: &(impl BeaconState<P> + ?Sized),
) -> Result<ContiguousVector<ValidatorIndex, P::SyncCommitteeSize>> {
    let next_epoch = get_next_epoch(state);
    let seed = get_seed_by_epoch(state, next_epoch, DOMAIN_SYNC_COMMITTEE);
    let indices = PackedIndices::U64(
        get_active_validator_indices_by_epoch(state, next_epoch).collect_vec().into(),
    );
    misc::compute_balance_weighted_selection::<P>(
        state, &indices, seed, P::SyncCommitteeSize::USIZE, true,
    )?
    .into_iter()
    .take(P::SyncCommitteeSize::USIZE)
    .pipe(ContiguousVector::try_from_iter)
    .map_err(Into::into)
}
```

**Three-way runtime dispatcher** routes to `_post_gloas` / `_post_electra` / `_pre_electra` based on the state's fork. The post-Gloas implementation calls `misc::compute_balance_weighted_selection` directly with `shuffle_indices=true` and `size=SYNC_COMMITTEE_SIZE` — spec-faithful wiring.

The same `compute_balance_weighted_selection` is used at `:1085` for proposer-indices and (likely) at a Gloas PTC site.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11: **explicit Gloas branch** (3-vs-3 split, grandine on the explicit-wiring side; the only client with a three-way dispatcher already in place). H12 ✓. H13 ✓.

## Cross-reference table

| Client | Function location | Gloas wiring | Per-fork dispatch | Gloas redefinition |
|---|---|---|---|---|
| prysm | `core/altair/sync_committee.go:111-168 NextSyncCommitteeIndices` | **reuses Pectra inline algorithm** (observable-equivalent) | runtime `s.Version() >= version.Electra` branch | none — single function covers Pectra and Gloas |
| lighthouse | `consensus/types/src/state/beacon_state.rs:1396-1447 get_next_sync_committee_indices` + `:2979 compute_balance_weighted_selection` | **explicit Gloas branch** via `fork_name_unchecked().gloas_enabled()` (`:1405`) | runtime `gloas_enabled()` check then `electra_enabled()` then pre-Electra | spec-faithful helper method `compute_balance_weighted_selection` |
| teku | `versions/gloas/helpers/BeaconStateAccessorsGloas.java:286-295 getNextSyncCommitteeIndices` (override) + `MiscHelpersGloas.java:129 computeBalanceWeightedSelection` | **explicit Gloas branch** via subclass override | subclass-override polymorphism (5-level chain) | spec-faithful `BeaconStateAccessorsGloas extends BeaconStateAccessorsElectra` |
| nimbus | `spec/beaconstate.nim:1423-1464 get_next_sync_committee_keys` (generic over electra/fulu/gloas) | **reuses Pectra inline algorithm** (observable-equivalent) | type-union compile-time overload | `compute_balance_weighted_selection` exists at `:3019` but used only by `get_ptc` |
| lodestar | `state-transition/src/util/seed.ts:240-269 getNextSyncCommitteeIndices` (with native WASM `nativeComputeSyncCommitteeIndices`) | **reuses Pectra inline algorithm** (observable-equivalent) | `fork >= ForkSeq.electra` (covers Gloas via fork-order) | none — single function covers Pectra and Gloas |
| grandine | `helper_functions/src/accessors.rs:597-607` dispatcher + `:657-705` post-electra + `:707-729` **post-gloas** | **explicit Gloas branch** via `is_post_gloas()` dispatcher | runtime three-way dispatcher | spec-faithful `compute_balance_weighted_selection` in `misc` module |

## Empirical tests

### Pectra-surface implicit coverage

The `consensus-spec-tests/tests/mainnet/electra/sync/` directory contains fixtures that exercise sync committee construction at fork-transition and at sync-committee-period boundaries:

```
sync_committee_committee_genesis__{empty, half, full}
sync_committee_committee__{empty, half, full}
optimistic
```

**Not wired in BeaconBreaker's harness** (the `sync` category isn't recognized by `parse_fixture` in `tools/runners/_lib.sh`). Carried forward from prior audit. Implicit coverage at Pectra via item #11's upgrade fixtures (which call `get_next_sync_committee` at Pectra activation).

### Gloas-surface

`consensus-spec-tests/tests/mainnet/gloas/sync/` (if generated) would contain analogous fixtures. Not wired either. H10 (algorithmic equivalence) and H11 (per-client wiring) are source-only.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — wire `sync` category in BeaconBreaker harness).** Pre-condition for cross-client fixture testing of this audit. Same gap as items #11, #21.
- **T1.2 (priority — dedicated EF fixture set).** Pure-function `(state, seed) → Sequence[ValidatorIndex]` fuzz. Boundary cases: varying validator counts (1 active, exactly 512 active, 1M active), varying effective_balance distributions (all-32 ETH, all-2048 ETH, mixed). Cross-client byte-level equivalence at both Pectra and Gloas state inputs.
- **T1.3 (Gloas-target — algorithmic equivalence between Pectra inline and Gloas helper).** Same input state; one client running Pectra inline algorithm; another client running `compute_balance_weighted_selection`. Assert identical 512-index output. Surfaces any subtle hash-caching or shuffle-dispatch divergence.

#### T2 — Adversarial probes
- **T2.1 (Glamsterdam-target — H10 verification).** Inject the same state into all 6 clients post-Gloas. Expected: identical 512 sync committee indices, regardless of whether the client uses the Pectra inline algorithm (prysm, nimbus, lodestar) or the explicit `compute_balance_weighted_selection` wiring (lighthouse, teku, grandine).
- **T2.2 (Glamsterdam-target — indirect item #22 H12 propagation).** State with a `0x03`-credentialled validator (per item #22's H12 attack scenario). Nimbus's `effective_balance` for this validator is 2048 ETH (due to its stale Gloas-aware `has_compounding_withdrawal_credential`); other 5 clients have 32 ETH. The sync committee selection probability differs:
  - nimbus: this validator selected with probability `2048/2048 = 100%` per iteration.
  - other 5 clients: probability `32/2048 = ~1.6%` per iteration.
  Over `i` iterations to fill the 512-slot committee, nimbus would have this validator in many slots; other clients would have it rarely. **Indirect propagation of item #22 H12 into sync committee membership divergence.** Same state-root mismatch root cause.
- **T2.3 (defensive — selection probability statistical validation).** For a known validator set with mixed effective_balance values, run the algorithm to convergence. Verify observed selection frequencies match the theoretical `min(1, eb / MAX_EB_ELECTRA)`. Cross-client equivalence.
- **T2.4 (defensive — duplicate validators in result).** Spec note: "with possible duplicates" — same validator can be selected multiple times in proportion to weight. Verify cross-client that all 6 clients preserve duplicates (don't dedup).
- **T2.5 (defensive — empty active validator set).** `active_validator_count == 0`. Spec at Gloas asserts `total > 0` (`compute_balance_weighted_selection` line 621). Pectra inline relies on the modulus-undefined-behavior never reachable on mainnet. Cross-client behavior on empty input (should panic / error consistently).
- **T2.6 (defensive — `SYNC_COMMITTEE_SIZE = 512` cap).** Confirm cross-client that the loop terminates at exactly 512 selected indices, never one less or more.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Pectra-surface invariants (H1–H9) hold across all six. The 16-bit precision and 2048 ETH ceiling are uniformly implemented.

**Glamsterdam-target finding (H10 + H11 — function-shape change is algorithmically equivalent; 3-vs-3 client wiring split is observable-equivalent).** `vendor/consensus-specs/specs/gloas/beacon-chain.md:685-702` Modifies `get_next_sync_committee_indices` to delegate to the NEW `compute_balance_weighted_selection` helper (`:603-639`). The helper is **mathematically identical** to the Pectra inline body for the sync-committee parameters (`shuffle_indices=True, size=SYNC_COMMITTEE_SIZE`): same iteration pattern, same hash preimage, same offset formula, same `MAX_RANDOM_VALUE`, same `MAX_EFFECTIVE_BALANCE_ELECTRA` ceiling, same selection predicate. The Gloas refactor adds two formal optimizations (hash caching across 16 iterations; pre-fetched `effective_balances` list) that 3/6 clients (teku, lodestar, grandine) already had in their Pectra implementations.

**Per-client Gloas wiring (3-vs-3 split, all observable-equivalent):**
- **Explicit Gloas wiring (spec-faithful)**: lighthouse (`fork_name_unchecked().gloas_enabled()` runtime check + `compute_balance_weighted_selection` method), teku (`BeaconStateAccessorsGloas extends BeaconStateAccessorsElectra` subclass override), grandine (three-way `is_post_gloas()` / `is_post_electra()` / `pre_electra` dispatcher with separate `get_next_sync_committee_indices_post_gloas` function).
- **Pectra-inline reuse (observable-equivalent via algorithmic equivalence)**: prysm (single function with `s.Version() >= version.Electra` branch covering Gloas), nimbus (generic over `electra | fulu | gloas` state type-union), lodestar (`fork >= ForkSeq.electra` lower-bound covers Gloas).

Both wirings produce identical sync committees on the same input state. **No mainnet-reachable divergence at this function's surface.**

**Tenth impact-none result** in the recheck series (after items #5, #10, #11, #18, #20, #21, #24, #25, #26). Same propagation-without-amplification pattern: the Gloas refactor is a code-organization change that the spec formalizes; the underlying algorithm is unchanged.

**Indirect propagation from item #22 H12 (H13 finding).** This function does NOT call `has_compounding_withdrawal_credential` (item #22) or `get_pending_balance_to_withdraw` (item #23) directly. But it reads `validator.effective_balance`, which is computed by `process_effective_balance_updates` via `get_max_effective_balance` (item #1). For a `0x03`-credentialled validator, nimbus's stale `has_compounding_withdrawal_credential` (item #22 H12) returns true at Gloas+ → nimbus computes `effective_balance` up to 2048 ETH; other 5 clients compute 32 ETH. The sync committee selection probability for this validator differs:
- nimbus: probability `min(1, 2048/2048) = 100%` per iteration → validator appears MANY times in the 512-slot sync committee.
- other 5 clients: probability `min(1, 32/2048) ≈ 1.6%` per iteration → validator appears RARELY.

So while this function's CODE is correct on all six clients, its OUTPUT diverges between nimbus and others as a downstream consequence of item #22 H12. The sync committee Merkle root therefore mismatches → state-root fork. This is the SAME H12 attack as item #22 manifesting through a DIFFERENT downstream surface. Same mitigation (fix nimbus's `has_compounding_withdrawal_credential`); no additional code change in THIS item.

**Cross-cut sister functions (H12 — out of scope for this item).** `compute_balance_weighted_selection` is consumed at Gloas by:
- `compute_proposer_indices` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:647-661`): single-validator selection per slot, `shuffle_indices=True, size=1`. Each block's proposer is now balance-weighted.
- `compute_ptc` (`:663-680`): PTC selection for `PayloadAttestation`, `shuffle_indices=False, size=PTC_SIZE`. Different shuffle parameter.

These are separate Gloas-MODIFIED / Gloas-NEW functions meriting their own audit items. Same `compute_balance_weighted_selection` helper across all three call sites in each client.

**Notable per-client style differences (all observable-equivalent at both Pectra and Gloas):**
- **prysm**: cached `hashFunc` + preallocated `seedBuffer` for performance. Single function for all forks; no separate Gloas method.
- **lighthouse**: explicit `gloas_enabled()` runtime check; cached `compute_balance_weighted_selection` method available for sister functions.
- **teku**: 5-level inheritance chain `BeaconStateAccessors → Altair → Deneb → Electra → Gloas` via subclass override; cleanest fork-isolation.
- **nimbus**: returns `array[SYNC_COMMITTEE_SIZE, ValidatorPubKey]` directly (skips intermediate index list). Inline `const MAX_RANDOM_VALUE` declaration. `compute_balance_weighted_selection` exists separately but consumed only by `get_ptc`.
- **lodestar**: delegates to native WASM `nativeComputeSyncCommitteeIndices` with `randByteCount` parameter (1 or 2). Optimized variant ~1000× faster than naive reference at `:178`.
- **grandine**: only client with explicit three-way `is_post_gloas() / is_post_electra() / pre_electra` dispatcher in place today. Most spec-faithful Gloas wiring.

**No code-change recommendation.** Audit-direction recommendations:

- **Wire `sync` category in BeaconBreaker harness** (T1.1) — pre-condition for cross-client fixture testing. Same gap as items #11, #21.
- **Generate dedicated EF fixture set for this function** (T1.2) — pure-function cross-client byte-level equivalence at both Pectra and Gloas.
- **Wire algorithmic-equivalence cross-validation** between explicit-helper and Pectra-inline wirings (T1.3) — surfaces any subtle hash-caching divergence.
- **Generate the indirect-propagation H13 fixture** (T2.2) — a Gloas state with a `0x03`-credentialled validator + non-default `effective_balance`. Confirms item #22 H12 propagates here via the sync committee membership Merkle root.
- **Track sister-item audits**: `compute_proposer_indices` (Gloas-modified, item-like surface), `compute_ptc` (Gloas-NEW PTC selection). Same `compute_balance_weighted_selection` helper at all three call sites.
- **Selection probability statistical validation** (T2.3) — property test for cross-client agreement on observed selection frequencies.
- **Pre-emptive Gloas-fork divergence consolidated audit** — items #1, #18, #20, #21, #22, #23, #26, #27 all have Gloas-aware code paths in subsets of clients. Worth consolidating into a tracking document.

## Cross-cuts

### With item #1 (`process_effective_balance_updates`) — upstream effective_balance source

Item #1 computes `validator.effective_balance` at every epoch boundary via `get_max_effective_balance(validator)` → `has_compounding_withdrawal_credential` dispatch. At Gloas, item #22 H12 found nimbus's stale Gloas-aware `has_compounding_withdrawal_credential` over-counts `0x03` validators as compounding-eligible (max 2048 ETH instead of 32 ETH). This divergent `effective_balance` is then consumed by THIS item's selection predicate → divergent sync committee membership. **Indirect H13 propagation channel.**

### With item #22 (`has_compounding_withdrawal_credential`) — direct H13 propagation source

Item #22 H12 is the mainnet-everyone divergence in nimbus (stale OR-fold of `0x03` builder credentials as compounding at Gloas+). Propagates into THIS function's `state.validators[i].effective_balance` value for any `0x03`-credentialled validator. **Same attack vector, different downstream surface.**

### With item #25 (`is_valid_indexed_attestation`) — sync committee participation gating

Sync committee members sign each slot via `process_sync_aggregate` (Altair surface, not Pectra-modified). Their participation gates rewards/penalties. If the sync committee MEMBERSHIP differs between nimbus and the other 5 clients (per H13 indirect propagation), the post-block state diverges on:
- `state.current_sync_committee` / `state.next_sync_committee` Merkle root.
- `current_epoch_participation` flags for the sync subcommittees.
- Sync-committee reward calculations.

State-root mismatch → fork. Same H12 attack manifesting through a different state field.

### With Gloas-NEW `compute_balance_weighted_selection` — direct sister surface

The same helper is used at Gloas by `compute_proposer_indices` and `compute_ptc`. Cross-cut audits would verify cross-client equivalence on all three call sites simultaneously. If a client's `compute_balance_weighted_selection` has a bug, it cascades into proposer selection AND PTC selection AND sync committee selection.

### With items #14 H9 / #19 H10 / #22 H10 / #23 H8 / #24 H11 / #25 H11 / #26 (lighthouse Gloas-ePBS cohort)

Lighthouse's broader Gloas-ePBS readiness gap (no `is_builder_withdrawal_credential`, no `get_pending_balance_to_withdraw_for_builder`, no `apply_parent_execution_payload` routing, no `is_valid_indexed_payload_attestation`) does NOT affect THIS function's surface. Lighthouse's `compute_balance_weighted_selection` and `get_next_sync_committee_indices` are correctly wired for Gloas. The Gloas-ePBS gap is in attestation/payload surfaces, not the validator-selection surface.

## Adjacent untouched

1. **Wire `sync` category in BeaconBreaker harness** — pre-condition for fixture testing this audit (T1.1). Same infrastructure gap as items #11, #21.
2. **Generate dedicated EF fixture set for `get_next_sync_committee_indices`** — pure-function fuzz at both Pectra and Gloas state inputs (T1.2).
3. **Algorithmic-equivalence cross-validation between explicit-helper and Pectra-inline wirings** (T1.3) — confirm no hash-caching divergence under the 3-vs-3 client split.
4. **H13 indirect-propagation fixture: `0x03`-credentialled validator + nimbus stale effective_balance** (T2.2) — surfaces item #22 H12 manifesting through sync committee membership.
5. **Sister-item audit: `compute_proposer_indices`** Gloas-modified — single-validator balance-weighted selection per slot.
6. **Sister-item audit: `compute_ptc`** Gloas-NEW PTC selection — `shuffle_indices=False, size=PTC_SIZE` variant of `compute_balance_weighted_selection`.
7. **Selection probability statistical validation** (T2.3) — property test for observed frequencies matching `min(1, eb / MAX_EB_ELECTRA)`.
8. **Hash optimization equivalence test** (teku + lodestar + grandine cache every 16 iterations; prysm + nimbus + lighthouse-Pectra-path recompute every iteration). Verify cross-client identical output.
9. **`compute_shuffled_index` cross-cut audit** — used here and elsewhere in committee assignment. Pectra-unchanged but pivotal.
10. **`get_seed(state, epoch, DOMAIN_SYNC_COMMITTEE)` cross-client byte-for-byte equivalence test**.
11. **Overflow analysis**: `effective_balance * MAX_RANDOM_VALUE = 2048e9 * 65535 ≈ 1.3e17` and `MAX_EFFECTIVE_BALANCE_ELECTRA * random_value` both well under u64 max (~1.8e19). No overflow concern.
12. **Active validator count performance audit** at mainnet scale (~1M validators) — `i % active_validator_count` and `compute_shuffled_index` performance.
13. **`SYNC_COMMITTEE_SIZE = 512` cap consistency** across all forks confirmed.
14. **Pre-emptive Gloas-fork divergence consolidated audit** — items #1, #18, #20, #21, #22, #23, #26, #27 all have Gloas-aware code in subsets of clients. Worth a consolidated tracking document.
15. **`MAX_RANDOM_VALUE` naming convention** — prysm + lighthouse + teku use named constants; nimbus + lodestar + grandine inline (or type-associated for grandine). Cross-client style consistency consideration.
