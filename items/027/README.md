# Item #27 — `get_next_sync_committee_indices` (Pectra-MODIFIED for EIP-7251 compounding-weighted sync committee selection)

**Status:** no-divergence-pending-source-review — audited 2026-05-02.
The Pectra-modified sync committee selection algorithm. **Three
distinct Pectra changes** required for compounding-weighted selection:
the random-value precision must scale with the 64× larger
`MAX_EFFECTIVE_BALANCE_ELECTRA` to maintain proper selection
probability granularity. Track G entry; first standalone audit of
sync committee logic.

## Why this item

The sync committee is a randomly-selected subset of `SYNC_COMMITTEE_SIZE
= 512` validators that signs the chain head every slot. Selection
is weighted by `effective_balance` so larger validators are more
likely to be chosen. With Pectra's `MAX_EFFECTIVE_BALANCE_ELECTRA =
2048 ETH` (vs Phase0's 32 ETH), the selection algorithm must use
**16-bit random values** instead of 8-bit to maintain proper
probability granularity:

```python
# Altair (pre-Pectra):
def get_next_sync_committee_indices(state) -> Sequence[ValidatorIndex]:
    epoch = Epoch(get_current_epoch(state) + 1)
    MAX_RANDOM_BYTE = 2**8 - 1                      # 8-bit precision
    active_validator_indices = get_active_validator_indices(state, epoch)
    active_validator_count = uint64(len(active_validator_indices))
    seed = get_seed(state, epoch, DOMAIN_SYNC_COMMITTEE)
    i = 0
    sync_committee_indices: List[ValidatorIndex] = []
    while len(sync_committee_indices) < SYNC_COMMITTEE_SIZE:
        shuffled_index = compute_shuffled_index(uint64(i % active_validator_count), active_validator_count, seed)
        candidate_index = active_validator_indices[shuffled_index]
        random_byte = hash(seed + uint_to_bytes(uint64(i // 32)))[i % 32]   # i // 32 + single byte
        effective_balance = state.validators[candidate_index].effective_balance
        if effective_balance * MAX_RANDOM_BYTE >= MAX_EFFECTIVE_BALANCE * random_byte:   # 32 ETH cap
            sync_committee_indices.append(candidate_index)
        i += 1
    return sync_committee_indices

# Pectra (THREE CHANGES):
def get_next_sync_committee_indices(state) -> Sequence[ValidatorIndex]:
    epoch = Epoch(get_current_epoch(state) + 1)
    # [Modified in Electra]
    MAX_RANDOM_VALUE = 2**16 - 1                                  # CHANGE 1: 16-bit (was 8-bit)
    active_validator_indices = get_active_validator_indices(state, epoch)
    active_validator_count = uint64(len(active_validator_indices))
    seed = get_seed(state, epoch, DOMAIN_SYNC_COMMITTEE)
    i = uint64(0)
    sync_committee_indices: List[ValidatorIndex] = []
    while len(sync_committee_indices) < SYNC_COMMITTEE_SIZE:
        shuffled_index = compute_shuffled_index(uint64(i % active_validator_count), active_validator_count, seed)
        candidate_index = active_validator_indices[shuffled_index]
        # [Modified in Electra]
        random_bytes = hash(seed + uint_to_bytes(i // 16))         # CHANGE 3a: i // 16 (was i // 32)
        offset = i % 16 * 2                                        # CHANGE 3b: 2-byte stride
        random_value = bytes_to_uint64(random_bytes[offset : offset + 2])  # 2 bytes (16-bit)
        effective_balance = state.validators[candidate_index].effective_balance
        # [Modified in Electra:EIP7251]
        if effective_balance * MAX_RANDOM_VALUE >= MAX_EFFECTIVE_BALANCE_ELECTRA * random_value:  # CHANGE 2: 2048 ETH
            sync_committee_indices.append(candidate_index)
        i += 1
    return sync_committee_indices
```

The math:
- Pre-Electra: a 32-ETH validator has `min(1, 32/32) = 100%` probability per iteration; smaller validators have `eff_balance/32` probability.
- Pectra: a 32-ETH validator has `32/2048 = 1/64 ≈ 1.6%` probability per iteration; a 2048-ETH compounding validator has `2048/2048 = 100%`.
- Without 16-bit precision, the minimum non-zero probability would be `1/256 ≈ 0.39%` — too coarse for the 64× larger MAX_EB. 16-bit gives `1/65535 ≈ 0.0015%` granularity.

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | `MAX_RANDOM_VALUE = 2^16 - 1 = 65535` (Pectra; was MAX_RANDOM_BYTE = 255 at Altair) | ✅ all 6 |
| H2 | `MAX_EFFECTIVE_BALANCE_ELECTRA = 2048 ETH = 2_048_000_000_000 gwei` (Pectra; was 32 ETH) | ✅ all 6 |
| H3 | Hash indexing: `i // 16` denominator (Pectra; was `i // 32`) | ✅ all 6 |
| H4 | Offset calculation: `(i % 16) * 2` for 2-byte stride (was `i % 32` for 1-byte index) | ✅ all 6 |
| H5 | `bytes_to_uint64(random_bytes[offset : offset + 2])` little-endian decode of 2 bytes | ✅ all 6 |
| H6 | Selection predicate: `effective_balance * MAX_RANDOM_VALUE >= MAX_EFFECTIVE_BALANCE_ELECTRA * random_value` | ✅ all 6 |
| H7 | While-loop terminates when `len(sync_committee_indices) == SYNC_COMMITTEE_SIZE = 512` | ✅ all 6 |
| H8 | Per-fork dispatch: pre-Electra path uses 8-bit + 32 ETH; Pectra path uses 16-bit + 2048 ETH | ✅ all 6 |
| H9 | Result list may contain duplicates (same validator selected multiple times — proportional to weight) | ✅ all 6 (preserved across forks) |

## Per-client cross-reference

| Client | Function location | Constants source | Per-fork dispatch |
|---|---|---|---|
| **prysm** | `core/altair/sync_committee.go:111-168` (single function with version branch at lines 147+157) | `MaxRandomValueElectra = (1 << 16) - 1` and `MaxRandomByte = (1 << 8) - 1` in `config/fieldparams/mainnet.go:46-47`; `MaxEffectiveBalanceElectra` in `params/mainnet_config.go` | runtime `if s.Version() >= version.Electra` branch |
| **lighthouse** | `consensus/types/src/state/beacon_state.rs:1396-1447` (with helper `:1156-1190`) | `MAX_RANDOM_BYTE` + `MAX_RANDOM_VALUE` consts at file top (`:59-60`); `max_effective_balance_for_fork()` in `chain_spec.rs:435-441` | `state.fork_name_unchecked().electra_enabled()` runtime check; **also** `gloas_enabled()` for `compute_balance_weighted_selection` (further Gloas changes!) |
| **teku** | `versions/electra/helpers/BeaconStateAccessorsElectra.java:112-152` (override) | `MAX_RANDOM_VALUE = UInt64.valueOf(65535)` in `MiscHelpersElectra.java:42`; `MAX_RANDOM_BYTE = 255` (int) in `BeaconStateAccessorsAltair.java:46` | subclass-override polymorphism (4-level inheritance: `BeaconStateAccessors → Altair → Deneb → Electra`) with two-level dispatch (public method calls protected impl with fork-specific maxEffectiveBalance) |
| **nimbus** | `spec/beaconstate.nim:1423-1464` (Electra/Fulu/Gloas variant) + Altair variant | `const MAX_RANDOM_VALUE = 65536 - 1` inline (line 1435); `MAX_EFFECTIVE_BALANCE_ELECTRA` in `presets/mainnet/electra_preset.nim:18` | type-union dispatch `state: electra.BeaconState \| fulu.BeaconState \| gloas.BeaconState` with overload resolution |
| **lodestar** | `state-transition/src/util/seed.ts:240-269` (optimized native delegate); `:178-233` (naive reference) | `MAX_RANDOM_VALUE = 2 ** 16 - 1` inline; `MAX_EFFECTIVE_BALANCE_ELECTRA` from `@lodestar/params` | `if (fork >= ForkSeq.electra)` runtime check; delegates to native WASM with `randByteCount` (1 or 2) parameter |
| **grandine** | `helper_functions/src/accessors.rs:597-607` (dispatcher) + `:609-655` (pre-Electra) + `:657-705` (Pectra) + `:707-729` (post-Gloas — pre-emptive!) | `u16::MAX = 65535`; `P::MAX_EFFECTIVE_BALANCE_ELECTRA = 2_048_000_000_000` type-associated | runtime dispatcher with `state.is_post_gloas()` / `state.is_post_electra()` checks routing to 3 fork-specific implementations |

## Notable per-client divergences (all observable-equivalent at Pectra)

### lighthouse + grandine: pre-emptive Gloas-fork code path

**Both lighthouse and grandine have a SEPARATE function for Gloas**:

```rust
// lighthouse beacon_state.rs:1405
if self.fork_name_unchecked().gloas_enabled() {
    self.compute_balance_weighted_selection(...)
} else {
    // existing logic with electra_enabled() / pre-Electra branch
}
```

```rust
// grandine accessors.rs:597-607
fn get_next_sync_committee_indices<P: Preset>(state: ...) -> Result<...> {
    if state.is_post_gloas() {
        get_next_sync_committee_indices_post_gloas(state)
    } else if state.is_post_electra() {
        get_next_sync_committee_indices_post_electra(state)
    } else {
        get_next_sync_committee_indices_pre_electra(state)
    }
}
```

This indicates **Gloas may further modify sync committee selection**
(possibly `compute_balance_weighted_selection` is a more refined
weighted algorithm). At Pectra, both clients route to their
Electra-specific code; the Gloas paths are dead code today. **Pre-emptive
Gloas readiness** — same pattern as items #1, #21, #22, #23, #26
where nimbus + grandine + lighthouse have Gloas-aware code paths
that are observable-equivalent at Pectra.

**prysm, teku, nimbus, lodestar** do NOT have separate Gloas
paths today — they would need updates at Gloas activation.

### Six distinct constant-naming conventions

All converge on `2^16 - 1 = 65535` and `2_048_000_000_000` gwei,
but with distinct symbol names + organization:

- **prysm**: `MaxRandomValueElectra` (vs `MaxRandomByte`) in fieldparams; `MaxEffectiveBalanceElectra` in params.
- **lighthouse**: `MAX_RANDOM_BYTE` + `MAX_RANDOM_VALUE` consts at file top; `max_effective_balance_for_fork()` accessor.
- **teku**: `MAX_RANDOM_VALUE` static `UInt64.valueOf(65535)` in MiscHelpersElectra; `getMaxEffectiveBalanceElectra()` method.
- **nimbus**: `const MAX_RANDOM_VALUE = 65536 - 1` declared INLINE within the function body.
- **lodestar**: `MAX_RANDOM_VALUE = 2 ** 16 - 1` declared INLINE; `MAX_EFFECTIVE_BALANCE_ELECTRA` imported from `@lodestar/params`.
- **grandine**: `u64::from(u16::MAX)` (= 65535) constructed inline; `P::MAX_EFFECTIVE_BALANCE_ELECTRA` type-associated constant.

The inline-constant idioms (nimbus, lodestar, grandine) avoid
naming-collision concerns; the named-constant idioms (prysm,
lighthouse, teku) make the cross-client cap easier to grep.

### Six distinct LE-decode idioms for the 2-byte random value

All produce identical results (little-endian 16-bit decode):

- **prysm**: `randomByte[offset] | randomByte[offset+1]<<8` (raw bitwise OR + shift).
- **lighthouse**: `u16::from_le_bytes(slice.try_into()?)` (standard library).
- **teku**: `bytesToUInt64(randomBytes.slice(offset, 2))` (helper function on Bytes type).
- **nimbus**: byte-array manipulation via `hash_buffer[offset..]` slice + `bytes_to_uint`.
- **lodestar**: `bytesToInt(randomBytes.subarray(offset, offset + 2))` (helper) — naive variant; **DataView.getUint16(..., true)** in PTC variant for performance.
- **grandine**: `u16::from_le_bytes(bytes.into())` from itertools `tuples()` chunked extraction.

Six idioms producing identical 16-bit values from 2 bytes.

### Hash optimization: teku + lodestar reuse hash across 16 iterations

```java
// teku BeaconStateAccessorsElectra.java:134-141
if (i % 16 == 0) {
    randomBytes = Bytes.wrap(sha256.digest(seed, uint64ToBytes(Math.floorDiv(i, 16L))));
}
final int offset = (i % 16) * 2;
final UInt64 randomValue = bytesToUInt64(randomBytes.slice(offset, 2));
```

teku and lodestar (in optimized variant) **re-compute the hash only
every 16 iterations** (when `i % 16 == 0`). The other 4 clients
re-compute the hash on every iteration (less efficient but simpler).
**Performance optimization**: 1 hash per 16 iterations vs 1 per
iteration. Same observable result.

The pyspec is "compute hash on every iteration"-style — the cached
optimization is correct only because the `seed + uint_to_bytes(i // 16)`
preimage is stable for 16 consecutive `i` values.

### prysm + lodestar: optimized native delegation

- **prysm**: uses `hash.CustomSHA256Hasher()` cached hasher instance.
- **lodestar**: optimized variant delegates to native WASM via
  `nativeComputeSyncCommitteeIndices()` with `randByteCount` (1 or 2)
  as parameter — same code handles both Phase0 and Pectra paths.

### grandine's functional-iterator approach

```rust
(0..u64::MAX / H128::len_bytes() as u64)
    .flat_map(|quotient| {
        hashing::hash_256_64(seed, quotient)
            .to_fixed_bytes()
            .into_iter()
            .tuples()
            .map(|bytes: (u8, u8)| u64::from(u16::from_le_bytes(bytes.into())))
    })
```

Most functional/lazy of all six. Uses itertools `tuples()` to
iterate the 32-byte hash as 16 pairs of 2 bytes, converting each
pair to u16. Avoids explicit indexing — hash boundary handled by
`flat_map` over `quotient`.

### nimbus inline constant declaration

```nim
const MAX_RANDOM_VALUE = 65536 - 1  # [Modified in Electra]
```

Nimbus declares the constant INSIDE the function body (line 1435).
Other clients (prysm, lighthouse, teku) define it at file/module
scope. **Most localized** — the constant is visible only within the
function. Spec-traceability concern: a search for `MAX_RANDOM_VALUE`
across the codebase would only find this one usage.

### teku two-level dispatch with parameter customization

```java
// teku BeaconStateAccessorsElectra.java:112-115 (public override)
@Override
public IntList getNextSyncCommitteeIndices(final BeaconState state) {
    return getNextSyncCommitteeIndices(state, configElectra.getMaxEffectiveBalanceElectra());
}
```

Public override calls protected implementation with the fork-specific
`maxEffectiveBalance` parameter. Allows the protected method to be
shared (with parameter), while the public dispatch is fork-specific.
Most-flexible architecture for fork variations.

## EF fixture status — implicit coverage via sync_committee_committee fixtures

The `consensus-spec-tests/tests/mainnet/electra/sync/` directory
contains fixtures that exercise sync committee construction:

```
sync_committee_committee_genesis__empty
sync_committee_committee_genesis__half
sync_committee_committee_genesis__full
sync_committee_committee__empty
sync_committee_committee__half
sync_committee_committee__full
optimistic
```

These exercise sync committee selection at genesis (post-fork
upgrade) and at sync committee period boundaries. **Not yet wired**
in BeaconBreaker's harness — the `sync` category isn't recognized
by `parse_fixture` in `tools/runners/_lib.sh`. Wiring this is a
follow-up infrastructure item (similar to the fork category gap
noted in item #11).

**Implicit coverage**: items #11 (upgrade) implicitly tests sync
committee construction at the Pectra activation slot via the
upgrade flow (which creates the initial sync committees). All 6
clients produce identical sync committees at Pectra activation per
their internal CI.

A dedicated fixture would consist of:
1. Pre-state with known active validators of varying effective_balance.
2. Compute next sync committee.
3. Expected output: sorted list of 512 ValidatorIndex.

**Pure function** (state → sync_committee_indices), trivially
fuzzable.

## Cross-cut chain — sync committee selection at Pectra activation

Sync committees are constructed at:
1. **Pectra activation slot** (item #11's upgrade calls `get_next_sync_committee` which calls this function).
2. **Every sync committee period boundary** (256 epochs = ~27 hours on mainnet).

```
[item #11 upgrade_to_electra]:
    state.current_sync_committee = pre.current_sync_committee  (preserved from Deneb)
    state.next_sync_committee = pre.next_sync_committee        (preserved from Deneb)
                ↓ (next sync committee period boundary)
[item #27 (this) get_next_sync_committee_indices]:
    while len < 512:
        shuffled = compute_shuffled_index(i, n, seed)
        candidate = active_indices[shuffled]
        random_value = hash(seed + i//16)[(i%16)*2 : (i%16)*2 + 2]   # 16-bit
        if effective_balance * 65535 >= 2048 ETH * random_value:
            sync_committee_indices.append(candidate)
        i += 1
                ↓
[Altair process_sync_aggregate]: validators in sync_committee sign block roots
```

The Pectra change ensures compounding 0x02 validators (with effective
balance up to 2048 ETH) have proportionally higher sync committee
selection probability than 0x01 validators capped at 32 ETH.

## Adjacent untouched

- **Wire `sync` category in BeaconBreaker harness** — would enable
  fixture verification for this audit (currently source-review only).
- **Generate dedicated EF fixture set** for `get_next_sync_committee_indices`
  — pure function (state → indices), trivially fuzzable.
- **lighthouse + grandine Gloas-aware code paths** — track the
  `compute_balance_weighted_selection` (lighthouse) and
  `get_next_sync_committee_indices_post_gloas` (grandine) functions
  for cross-client divergence at Gloas activation. Other 4 clients
  (prysm, teku, nimbus, lodestar) do NOT have Gloas-specific paths
  yet — they would need updates.
- **Hash optimization equivalence test** (teku + lodestar cache
  every 16 iterations; others compute every iteration) — verify
  identical output across all 6 clients for the same input.
- **Selection probability statistical validation** — for a known
  validator set with mixed effective_balance values, verify the
  observed selection frequencies match the theoretical
  `min(1, eb / MAX_EB_ELECTRA)`. This is more like a property test
  than a fixture.
- **Cross-fork transition stateful fixture** — at Pectra activation,
  the sync committee from Deneb (using 8-bit precision + 32 ETH cap)
  is preserved. The next committee post-activation uses the new
  algorithm. Verify cross-client.
- **`compute_shuffled_index` cross-cut** — used here and elsewhere
  in committee assignment. Pectra-unchanged but pivotal.
- **`get_seed(state, epoch, DOMAIN_SYNC_COMMITTEE)` cross-cut** —
  the seed determines the entire sync committee. Cross-client
  byte-for-byte equivalence test.
- **Overflow analysis**: `effective_balance * MAX_RANDOM_VALUE = 2048e9 * 65535 ≈ 1.3e17`
  and `MAX_EFFECTIVE_BALANCE_ELECTRA * random_value = 2048e9 * 65535 ≈ 1.3e17`.
  Both well under u64 max (~1.8e19). No overflow concern.
- **Active validator count edge cases** — `i % active_validator_count`
  could be slow if `active_validator_count` is very large (mainnet
  ~1M validators). Performance audit.
- **`SYNC_COMMITTEE_SIZE = 512` cap** — fixed across all forks.
  Worth confirming.

## Future research items

1. **Wire `sync` category in BeaconBreaker harness** — enables
   fixture verification.
2. **Generate dedicated EF fixture set** — pure function fuzzing.
3. **lighthouse + grandine Gloas-aware tracking** — at Gloas
   activation, verify cross-client agreement.
4. **Hash optimization equivalence test** (teku + lodestar caching
   vs others recomputing).
5. **Selection probability statistical validation** — property test.
6. **Cross-fork transition stateful fixture** at Pectra activation.
7. **`compute_shuffled_index` cross-cut audit**.
8. **`get_seed(state, epoch, DOMAIN_SYNC_COMMITTEE)` cross-client
   equivalence** test.
9. **Active validator count performance audit** at mainnet scale.
10. **`SYNC_COMMITTEE_SIZE = 512` cap consistency** across all forks.
11. **Pre-emptive Gloas-fork divergence consolidated audit** — items
    #1, #18, #20, #21, #22, #23, #26, #27 all have Gloas-aware code
    in subset of clients. Consolidated tracking document.
12. **`MAX_RANDOM_VALUE` naming convention** — prysm + lighthouse +
    teku use named constants; nimbus + lodestar + grandine inline.
    Cross-client style consistency consideration.
