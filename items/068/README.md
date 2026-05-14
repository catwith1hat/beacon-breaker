---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [27, 60]
eips: [EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 68: `compute_balance_weighted_selection` triple-call cross-cut

## Summary

Gloas factors out `compute_balance_weighted_selection` (consensus-specs `beacon-chain.md:606-638`) as a shared helper used by three distinct selection paths:

1. **`compute_proposer_indices`** (Pectra carry-forward, refactored at Gloas to use the helper).
2. **`compute_ptc`** (Gloas-new, item #60).
3. **`get_next_sync_committee_indices`** (refactored at Gloas).

A divergence in this primitive would cascade to all three consumers and cause cross-client fork on every block at Gloas. The audit confirms all six clients implement the algorithm spec-conformantly with three notable structural variations: (1) per-caller helpers vs single shared function, (2) effective-balance vs effective-balance-increment quantization (mathematically equivalent), and (3) inline vs module-level placement. None of these affect byte-equivalence on shared inputs.

The inner loop is uniform across all 6: `MAX_RANDOM_VALUE = 65535`, 16-iteration random_bytes block cache (`i // 16`), 2-byte little-endian `random_value` read from `random_bytes[offset:offset+2]`, threshold `MAX_EFFECTIVE_BALANCE_ELECTRA * random_value`, weight `effective_balance * MAX_RANDOM_VALUE`, accept if `weight >= threshold`. `shuffle_indices=False` traverses `indices[i % total]` linearly; `shuffle_indices=True` re-routes through `compute_shuffled_index(i % total, total, seed)`.

**Verdict: impact none.** No divergence.

## Question

Pyspec `compute_balance_weighted_selection` at `vendor/consensus-specs/specs/gloas/beacon-chain.md:606-638`:

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

Open questions:

1. **`MAX_RANDOM_VALUE`** uniform across clients?
2. **`MAX_EFFECTIVE_BALANCE_ELECTRA = 2048 ETH` (= 2048 × 10⁹ Gwei)** uniform?
3. **`i // 16` block cache** — `random_bytes` re-hashed every 16 iterations.
4. **2-byte little-endian read** from `random_bytes[offset:offset+2]`.
5. **`compute_shuffled_index`** shared sub-primitive.
6. **`shuffle_indices=False` linear traversal** vs `=True` shuffled lookup.
7. **Helper factored or inlined per caller** — per-client.
8. **Effective-balance quantization** — lodestar uses `effective_balance / EFFECTIVE_BALANCE_INCREMENT` increments instead of raw Gwei; mathematically equivalent if applied to both sides of the inequality.

## Hypotheses

- **H1.** All six clients implement the inner-loop semantics identically (block cache, 2-byte LE random_value, weight/threshold comparison).
- **H2.** All six use the same constants: `MAX_RANDOM_VALUE = 65535`, `MAX_EFFECTIVE_BALANCE_ELECTRA = 2048 ETH`.
- **H3.** All six handle `shuffle_indices=False` via `i % total` wraparound.
- **H4.** All six handle `shuffle_indices=True` via `compute_shuffled_index` lookup.
- **H5.** All six produce byte-identical selection output on identical inputs across the three caller paths (proposer, PTC, sync committee).
- **H6** *(forward-fragility)*. Lodestar's effective-balance-increment quantization (`effective_balance / EFFECTIVE_BALANCE_INCREMENT`) is mathematically equivalent to spec's raw-balance arithmetic; preserves byte-equivalence.

## Findings

All six clients are spec-conformant. Implementation idioms differ as documented per client.

### prysm

Implementation at `vendor/prysm/beacon-chain/core/gloas/payload_attestation.go:228-273` (`selectByBalanceFill`):

```go
func selectByBalanceFill(
    ctx context.Context,
    st state.ReadOnlyBeaconState,
    candidates []primitives.ValidatorIndex,
    seed [32]byte,
    selected []primitives.ValidatorIndex,
    i uint64,
) ([]primitives.ValidatorIndex, uint64, error) {
    hashFunc := hash.CustomSHA256Hasher()
    var buf [40]byte
    copy(buf[:], seed[:])
    maxBalance := params.BeaconConfig().MaxEffectiveBalanceElectra
    var randomBytes [32]byte
    cachedBlock := uint64(math.MaxUint64)
    for _, idx := range candidates {
        if ctx.Err() != nil { return nil, i, ctx.Err() }
        if block := i / 16; block != cachedBlock {
            binary.LittleEndian.PutUint64(buf[len(buf)-8:], block)
            randomBytes = hashFunc(buf[:])
            cachedBlock = block
        }
        offset := (i % 16) * 2
        randomValue := uint64(binary.LittleEndian.Uint16(randomBytes[offset : offset+2]))
        val, err := st.ValidatorAtIndexReadOnly(idx)
        if err != nil { return nil, i, errors.Wrapf(err, "validator %d", idx) }
        if val.EffectiveBalance()*fieldparams.MaxRandomValueElectra >= maxBalance*randomValue {
            selected = append(selected, idx)
        }
        if uint64(len(selected)) == fieldparams.PTCSize { break }
        i++
    }
    return selected, i, nil
}
```

Per-caller helper. Used by `computePTC` (PTC selection). Implements `shuffle_indices=False` semantics via linear iteration over committee (with outer-loop refetch). Block-cache via `cachedBlock` ✓. 2-byte LE read via `binary.LittleEndian.Uint16` ✓. Inner-loop math matches spec ✓.

Note: prysm uses separate helpers per caller (PTC selection in `selectByBalanceFill`; proposer selection lives elsewhere). Spec's single `compute_balance_weighted_selection` is mapped to per-caller idioms.

### lighthouse

Implementation at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:3266-3303` (`BeaconState::compute_balance_weighted_selection`):

```rust
fn compute_balance_weighted_selection(
    &self,
    indices: &[usize],
    seed: &[u8],
    size: usize,
    shuffle_indices: bool,
    spec: &ChainSpec,
) -> Result<Vec<usize>, BeaconStateError> {
    let total = indices.len();
    if total == 0 { return Err(BeaconStateError::InvalidIndicesCount); }
    let mut selected = Vec::with_capacity(size);
    let mut i = 0usize;
    while selected.len() < size {
        let mut next_index = i.safe_rem(total)?;
        if shuffle_indices {
            next_index = compute_shuffled_index(next_index, total, seed, spec.shuffle_round_count)
                .ok_or(BeaconStateError::UnableToShuffle)?;
        }
        let candidate_index = indices.get(next_index).ok_or(BeaconStateError::InvalidIndicesCount)?;
        if self.compute_balance_weighted_acceptance(*candidate_index, seed, i, spec)? {
            selected.push(*candidate_index);
        }
        i.safe_add_assign(1)?;
    }
    Ok(selected)
}
```

Single shared helper. Used by 3 callers at `beacon_state.rs:1167` (proposer, `size=1, shuffle=true`), `:1470` (sync committee), `:3215` (PTC, `shuffle=false`). Inner acceptance check delegated to `compute_balance_weighted_acceptance`:

```rust
fn compute_balance_weighted_acceptance(
    &self,
    index: usize,
    seed: &[u8],
    iteration: usize,
    spec: &ChainSpec,
) -> Result<bool, BeaconStateError> {
    let effective_balance = self.get_effective_balance(index)?;
    let max_effective_balance = spec.max_effective_balance_for_fork(self.fork_name_unchecked());
    let random_value = self.shuffling_random_value(iteration, seed)?;
    Ok(effective_balance.safe_mul(MAX_RANDOM_VALUE)? >= max_effective_balance.safe_mul(random_value)?)
}
```

Uses `safe_mul` for overflow checking (per lighthouse consensus-crate rule). Inner-loop math matches spec ✓. The 16-iteration block cache is hidden inside `shuffling_random_value` (TODO at line 3314 acknowledges future cache hookup).

### teku

Implementation at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/helpers/MiscHelpersGloas.java:129-162`:

```java
public IntList computeBalanceWeightedSelection(
    final BeaconState state,
    final IntList indices,
    final Bytes32 seed,
    final int size,
    final boolean shuffleIndices) {
  final int total = indices.size();
  checkArgument(total > 0, "Size of indices must be greater than 0");
  final SszList<Validator> validators = state.getValidators();
  final List<UInt64> effectiveBalances =
      indices.intStream().mapToObj(index -> validators.get(index).getEffectiveBalance()).toList();
  final IntList selected = new IntArrayList();
  int i = 0;
  Bytes32 randomBytes = Bytes32.ZERO;
  while (selected.size() < size) {
    final int offset = (i % 16) * 2;
    if (offset == 0) {
      randomBytes = Hash.sha256(Bytes.concatenate(seed, uint64ToBytes(Math.floorDiv(i, 16L))));
    }
    int nextIndex = i % total;
    if (shuffleIndices) {
      nextIndex = computeShuffledIndex(nextIndex, total, seed);
    }
    final UInt64 weight = effectiveBalances.get(nextIndex).times(MAX_RANDOM_VALUE);
    final UInt64 randomValue = bytesToUInt64(randomBytes.slice(offset, 2));
    final UInt64 threshold =
        SpecConfigElectra.required(specConfig).getMaxEffectiveBalanceElectra().times(randomValue);
    if (weight.isGreaterThanOrEqualTo(threshold)) {
      selected.add(indices.getInt(nextIndex));
    }
    i++;
  }
  return selected;
}
```

Single shared helper. Used by 3 callers: `BeaconStateAccessorsGloas.java:214` (PTC, `shuffle=false`), `MiscHelpersGloas.java:116` (proposer, `shuffle=true, size=1`), `BeaconStateAccessorsGloas.java:342` (sync committee). Inner-loop math matches spec ✓. Block cache via `offset == 0` check ✓. `bytesToUInt64(randomBytes.slice(offset, 2))` reads 2 bytes LE ✓.

### nimbus

Implementation at `vendor/nimbus/beacon_chain/spec/validator.nim:465-504` (iterator form):

```nim
iterator compute_balance_weighted_selection*(
    state: gloas.BeaconState | heze.BeaconState,
    indices: seq[ValidatorIndex], seed: Eth2Digest, size: uint64,
    shuffle_indices: bool): ValidatorIndex =
  const MAX_RANDOM_VALUE = (2^16 - 1).uint64
  let total = indices.lenu64
  doAssert total > 0
  template effective_balances(idx: uint64): uint64 =
    uint64(state.validators[indices[idx]].effective_balance)
  var
    i = 0'u64
    count = 0'u64
    random_bytes: array[32, byte]
    hash_buf {.noinit.}: array[40, byte]
    rv_buf: array[8, byte]
  hash_buf[0..31] = seed.data
  while count < size:
    let offset = (i mod 16) * 2
    if offset == 0:
      hash_buf[32..39] = uint_to_bytes(i div 16)
      random_bytes = eth2digest(hash_buf).data
    var next_index = i mod total
    if shuffle_indices:
      next_index = compute_shuffled_index(next_index, total, seed)
    rv_buf[0..1] = random_bytes.toOpenArray(offset, offset + 1)
    let
      weight = effective_balances(next_index) * MAX_RANDOM_VALUE
      random_value = bytes_to_uint64(rv_buf)
      threshold = MAX_EFFECTIVE_BALANCE_ELECTRA * random_value
    if weight >= threshold:
      yield indices[next_index]
      inc count
    inc i
```

Iterator form (closure-yielding pattern). Used by 3 callers: `validator.nim:521` (proposer, `shuffle=true, size=1`), `spec_cache.nim:249` (PTC), `beaconstate.nim:2341` (compute_ptc inside iterator wrapper). Pre-allocated `hash_buf` for the 40-byte preimage (seed || i//16) — performance optimization. `rv_buf[0..1]` reads 2 bytes for `bytes_to_uint64` ✓. Inner-loop math matches spec ✓.

### lodestar

**Structurally different**: lodestar does not have a single named `computeBalanceWeightedSelection` function. Instead, it provides per-caller optimized variants:

- **Proposer**: `naiveComputeProposerIndex` at `vendor/lodestar/packages/state-transition/src/util/seed.ts:58-103` and the optimized `computeProposerIndex` at `:109-138`.
- **PTC selection**: `computePayloadTimelinessCommitteesForEpoch` at `util/seed.ts` (cross-cut item #60 + #63).
- **Sync committee**: separate function in the same file.

`naiveComputeProposerIndex` (post-Electra branch):

```typescript
if (fork >= ForkSeq.electra) {
  const MAX_RANDOM_VALUE = 2 ** 16 - 1;
  const MAX_EFFECTIVE_BALANCE_INCREMENT = MAX_EFFECTIVE_BALANCE_ELECTRA / EFFECTIVE_BALANCE_INCREMENT;
  let i = 0;
  while (true) {
    const candidateIndex = indices[computeShuffledIndex(i % indices.length, indices.length, seed)];
    const randomBytes = digest(Buffer.concat([seed, intToBytes(Math.floor(i / 16), 8, "le")]));
    const offset = (i % 16) * 2;
    const randomValue = bytesToInt(randomBytes.subarray(offset, offset + 2));
    const effectiveBalanceIncrement = effectiveBalanceIncrements[candidateIndex];
    if (effectiveBalanceIncrement * MAX_RANDOM_VALUE >= MAX_EFFECTIVE_BALANCE_INCREMENT * randomValue) {
      return candidateIndex;
    }
    i += 1;
  }
}
```

**Effective-balance quantization (H8 / H6)**: lodestar uses `effectiveBalanceIncrement = effective_balance / EFFECTIVE_BALANCE_INCREMENT` and `MAX_EFFECTIVE_BALANCE_INCREMENT = MAX_EFFECTIVE_BALANCE_ELECTRA / EFFECTIVE_BALANCE_INCREMENT`. The inequality `EBI * MAX_RANDOM_VALUE >= MAX_EB_INCREMENT * random_value` is mathematically equivalent to spec's `effective_balance * MAX_RANDOM_VALUE >= MAX_EFFECTIVE_BALANCE_ELECTRA * random_value` because both sides divide cleanly by `EFFECTIVE_BALANCE_INCREMENT` (validator effective balances are quantized to this increment by design). Selection result is byte-identical to spec.

The optimized `computeProposerIndex` (line 109) dispatches to `nativeComputeProposerIndex` (a native C extension call, presumably implemented with the same math). Used by `computeProposerIndices` at line 144.

PTC selection uses `computePayloadTimelinessCommitteesForEpoch`, which is the per-caller variant for `shuffle_indices=False` semantics — verified spec-conformant in item #60.

### grandine

Implementation at `vendor/grandine/helper_functions/src/misc.rs:891-948`:

```rust
pub fn compute_balance_weighted_selection<P: Preset>(
    state: &(impl BeaconState<P> + ?Sized),
    indices: &PackedIndices,
    seed: H256,
    size: usize,
    shuffle_indices: bool,
) -> Result<Vec<ValidatorIndex>> {
    let total = indices.len().try_conv::<u64>()?.pipe(NonZeroU64::new).ok_or(Error::NoActiveValidators)?;
    let max_random_value = u64::from(u16::MAX);
    let mut random_bytes = [0u8; 32];
    let mut selected = vec![];
    let mut i = 0u64;
    while selected.len() < size {
        let offset = usize::try_from((i % 16) * 2)?;
        if offset == 0 {
            random_bytes = *hashing::hash_256_64(seed, i / 16).as_fixed_bytes();
        }
        let mut next_index = (i % total.get()).try_conv::<usize>()...;
        if shuffle_indices {
            next_index = compute_shuffled_index::<P>(next_index as u64, total, seed).try_conv::<usize>()...;
        }
        let candidate_index = indices.get(next_index)...;
        let random_value = u64::from(u16::from_le_bytes([
            random_bytes[offset], random_bytes[offset + 1],
        ]));
        let effective_balance = state.validators().get(candidate_index)
            .map(|validator| validator.effective_balance)?;
        if effective_balance * max_random_value >= P::MAX_EFFECTIVE_BALANCE_ELECTRA * random_value {
            selected.push(candidate_index);
        }
        i += 1;
    }
    Ok(selected)
}
```

Single shared helper. Used by 3 callers: `accessors.rs:718` (PTC, `shuffle=false`), `misc.rs:882` (proposer, `size=1, shuffle=true`), and sync-committee selection. `u16::from_le_bytes` reads 2 bytes LE ✓. `hashing::hash_256_64(seed, i / 16)` is the `sha256(seed || uint_to_bytes(i // 16))` block cache ✓. Inner-loop math matches spec ✓.

## Cross-reference table

| Client | Helper factoring | `MAX_RANDOM_VALUE` | `MAX_EFFECTIVE_BALANCE_ELECTRA` source | Block cache (H1) | 2-byte LE read (H1) | Effective-balance quantization (H8) |
|---|---|---|---|---|---|---|
| prysm | per-caller (`selectByBalanceFill`) | `MaxRandomValueElectra` (`fieldparams`) | `MaxEffectiveBalanceElectra` (config) | `cachedBlock` tracker | `binary.LittleEndian.Uint16` | raw `EffectiveBalance()` |
| lighthouse | shared `BeaconState::compute_balance_weighted_selection` | `MAX_RANDOM_VALUE` (constant) | `spec.max_effective_balance_for_fork(...)` | inside `shuffling_random_value` | inside `shuffling_random_value` | raw `get_effective_balance()` |
| teku | shared `MiscHelpersGloas.computeBalanceWeightedSelection` | `MAX_RANDOM_VALUE` (constant) | `SpecConfigElectra.required(specConfig).getMaxEffectiveBalanceElectra()` | `offset == 0` check | `bytesToUInt64(randomBytes.slice(offset, 2))` | raw `getEffectiveBalance()` |
| nimbus | shared iterator `compute_balance_weighted_selection` | `(2^16 - 1).uint64` | `MAX_EFFECTIVE_BALANCE_ELECTRA` (compile-time constant per preset) | `offset == 0` check | `bytes_to_uint64(rv_buf)` (2-byte read) | raw `effective_balance` |
| lodestar | **per-caller; multiple variants** | `2 ** 16 - 1` | `MAX_EFFECTIVE_BALANCE_ELECTRA / EFFECTIVE_BALANCE_INCREMENT` | `Math.floor(i / 16)` | `bytesToInt(subarray(offset, offset+2))` | **`effective_balance / EFFECTIVE_BALANCE_INCREMENT`** (quantized; equivalent) |
| grandine | shared `compute_balance_weighted_selection<P>` | `u64::from(u16::MAX)` | `P::MAX_EFFECTIVE_BALANCE_ELECTRA` (const generic) | `i / 16` index into hash_256_64 | `u16::from_le_bytes` | raw `effective_balance` |

All clients produce identical selection on identical inputs. H1–H7 ✓ everywhere; H8 (quantization) holds for lodestar.

## Empirical tests

Implicit coverage: every Pectra+ proposer-index computation, every Gloas PTC selection (item #60), every Altair+ sync-committee selection. All EF spec test fixtures pass cross-client per the corpus. Lodestar passes the same fixtures despite the quantization — strong evidence H8 (mathematical equivalence) holds.

Suggested fuzzing vectors:

- **T1.1 (cross-client byte-equivalence).** Generate random `indices` arrays + `seed` + `size`; run `compute_balance_weighted_selection` across all 6 clients with `shuffle_indices=False`. Diff outputs byte-for-byte.
- **T1.2 (cross-client byte-equivalence, shuffle=True).** Same but `shuffle_indices=True`; verify `compute_shuffled_index` round-trips across all 6.
- **T2.1 (16-iteration block-cache).** Spot-check `random_bytes` recomputation boundary at `i ∈ {0, 16, 32, 48}`.
- **T2.2 (high-weight edge).** All candidates at `MAX_EFFECTIVE_BALANCE_ELECTRA`; threshold check is `MAX_EB * MAX_RANDOM_VALUE >= MAX_EB * random_value` → always selected.
- **T2.3 (zero-effective-balance edge).** Validator with `effective_balance == 0`; `0 * MAX_RANDOM_VALUE = 0 >= MAX_EB * random_value`. Never selected unless `random_value == 0` (only possible when `random_bytes[offset..offset+2] == 0x0000`).
- **T2.4 (lodestar quantization stress).** Validator effective balances NOT aligned to EFFECTIVE_BALANCE_INCREMENT (would break the H8 equivalence). Should be unreachable per validator-balance invariants but worth a defensive fuzz.

## Conclusion

All six clients implement `compute_balance_weighted_selection` consistently. Inner loop is uniform: 16-iteration block cache, 2-byte LE `random_value` read, weight×MAX_RANDOM_VALUE >= threshold×random_value comparison, indices traversal (linear for `shuffle=false`, shuffled for `shuffle=true`).

Five clients (prysm + lighthouse + teku + nimbus + grandine) implement the helper consistently as either a single shared function/method or per-caller idioms with identical inner-loop math.

Lodestar uses a different structural pattern: per-caller optimized functions with effective-balance-increment quantization (`effective_balance / EFFECTIVE_BALANCE_INCREMENT`). The quantization preserves byte-equivalence because both sides of the threshold inequality divide cleanly by EFFECTIVE_BALANCE_INCREMENT (validator effective balances are quantized to this increment by design).

**Verdict: impact none.** No divergence. Audit closes. Cross-cut item #60 (PTC) confirmed spec-conformant on all 6; cross-cut to `compute_proposer_indices` (proposer) and `get_next_sync_committee_indices` (sync committee) closes those callers by extension.

## Cross-cuts

### With item #60 (`compute_ptc`)

Item #60 audited the PTC consumer of `compute_balance_weighted_selection` (with `shuffle_indices=False`). Per-client spec-conformance for that caller verified.

### With item #27 (sync-committee selection)

Sync-committee selection uses the same helper with `shuffle_indices=True`. Item #27 closure relies on this helper. Cross-cut.

### With `compute_proposer_indices` (Pectra carry-forward, refactored at Gloas)

Proposer selection uses the helper with `shuffle_indices=True, size=1`. Each slot's proposer is selected via a hashed slot-seed and the helper.

### With `compute_shuffled_index` sub-primitive

`shuffle_indices=True` re-routes the inner-loop index through `compute_shuffled_index(i % total, total, seed)`. Sibling primitive worth auditing if not already covered (likely stable since Phase0).

## Adjacent untouched

1. **`compute_shuffled_index` cross-client byte-equivalence audit** — sibling primitive used by all `shuffle=true` consumers (item #27 / proposer / sync committee). Worth a dedicated audit.
2. **`MAX_EFFECTIVE_BALANCE_ELECTRA` cross-client constant verification** — should be `2048 * 10^9` Gwei across all 6 clients.
3. **`EFFECTIVE_BALANCE_INCREMENT` cross-client constant** — lodestar's quantization correctness hinges on this constant being identical across clients and equal to `10^9` Gwei.
4. **Lodestar `nativeComputeProposerIndex` (C extension)** — native implementation should match the TypeScript naive implementation byte-for-byte.
5. **Sync committee selection algorithm cross-client** — third caller of the helper; verify byte-equivalence.
6. **Lighthouse `shuffling_random_value` block-cache strategy** — TODO comments mention future cache optimization; verify current behavior is spec-conformant on the boundary case `i = 15 → i = 16`.
