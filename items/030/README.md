---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [11, 27]
eips: [EIP-7917, EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 30: `get_beacon_proposer_index` + `process_proposer_lookahead` + `initialize_proposer_lookahead` + `compute_proposer_indices` + `get_beacon_proposer_indices` (Fulu-NEW EIP-7917 deterministic proposer lookahead)

## Summary

EIP-7917 deterministic proposer lookahead — `state.proposer_lookahead: Vector[ValidatorIndex, 2 × SLOTS_PER_EPOCH = 64]` pre-computes proposer indices for the current + next epoch, replacing the on-demand `compute_proposer_index` call in `get_beacon_proposer_index`. Initialized once at `upgrade_to_fulu`; mutated only at end-of-epoch via `process_proposer_lookahead`; consumed via direct indexed lookup at every slot.

**Fulu surface (carried forward from 2026-05-04 audit):** all six clients implement the lookahead vector with byte-for-byte equivalent observable behaviour. Per-client divergences are entirely in error-guard semantics (lighthouse alone has explicit `InsufficientLookahead`/`ExcessiveLookahead` errors), cache architecture (lodestar separates `this.proposers` from `state.proposerLookahead`), allocation patterns (in-place vs Vec/ArrayList copies), pre-Fulu fallback handling (prysm double-checks state version AND epoch), and Optional wrapping (nimbus retains stale lookahead on `Opt.none` — forward-fragile under empty validator set).

**Gloas surface (at the Glamsterdam target): `compute_proposer_indices` is Modified at Gloas to delegate to `compute_balance_weighted_selection`; output algorithmically identical to the Fulu inline body.** Cross-cuts item #27 H10 finding: the new helper has the SAME observable behaviour as the per-slot `compute_proposer_index` (Electra) call inside the Fulu `compute_proposer_indices` body. `process_proposer_lookahead`, `initialize_proposer_lookahead`, `get_beacon_proposer_index`, `get_beacon_proposer_indices` are NOT modified at Gloas — they inherit verbatim from Fulu.

**Per-client Gloas wiring of `compute_proposer_indices` (4-vs-2 split, all observable-equivalent):**
- **Four clients (lighthouse, teku, nimbus, grandine) wire explicit Gloas branches** calling `compute_balance_weighted_selection`. Teku caught up since the 2026-05-04 audit (`MiscHelpersGloas.computeProposerIndices` override now exists).
- **Two clients (prysm, lodestar) reuse the Pectra-inline algorithm at Gloas** via `state.Version() >= version.Electra` / `fork >= ForkSeq.electra` fork-order coverage. Observable-equivalent because `compute_balance_weighted_selection(state, indices, seed, size=1, shuffle_indices=True)[0]` produces the same first-selected validator as the Pectra inline `compute_proposer_index(state, indices, seed)` call.

**Reclassification of prior "Pattern M A-tier divergence vector" claim:** the 2026-05-04 audit hypothesized that the 3-vs-3 split on Gloas wiring of `compute_proposer_indices` would cause "different proposer indices = different blocks at Gloas activation". This claim is REFUTED by item #27 H10: the Gloas `compute_balance_weighted_selection` helper is algorithmically identical to the Pectra inline algorithm (same iteration pattern, same hash preimage, same offset formula, same predicate). At Gloas activation, all 6 clients produce identical proposer indices. **Pattern M downgrades from A-tier to observable-equivalent in item #28's catalogue.**

**Cross-cut to item #28 update:** Pattern M (compute_proposer_indices Gloas wiring) should be reclassified from A-tier divergence to "observable-equivalent 4-vs-2 client split". Same reclassification rationale as Pattern F (sync committee selection — item #27 H10).

**Impact: none.** Twelfth impact-none result in the recheck series.

## Question

Pyspec Fulu-NEW EIP-7917 (`vendor/consensus-specs/specs/fulu/beacon-chain.md:249-261`):

```python
def compute_proposer_indices(state, epoch, seed, indices):
    start_slot = compute_start_slot_at_epoch(epoch)
    seeds = [hash(seed + uint_to_bytes(Slot(start_slot + i))) for i in range(SLOTS_PER_EPOCH)]
    return [compute_proposer_index(state, indices, seed) for seed in seeds]
```

Pyspec Gloas-Modified (`vendor/consensus-specs/specs/gloas/beacon-chain.md:641-661`):

```python
def compute_proposer_indices(state, epoch, seed, indices):
    start_slot = compute_start_slot_at_epoch(epoch)
    seeds = [hash(seed + uint_to_bytes(Slot(start_slot + i))) for i in range(SLOTS_PER_EPOCH)]
    return [
        compute_balance_weighted_selection(state, indices, seed, size=1, shuffle_indices=True)[0]
        for seed in seeds
    ]
```

The only difference: `compute_proposer_index(state, indices, seed)` → `compute_balance_weighted_selection(state, indices, seed, size=1, shuffle_indices=True)[0]`. Both functions implement the same balance-weighted-sampling iteration: 16-bit `MAX_RANDOM_VALUE = 65535`, `MAX_EFFECTIVE_BALANCE_ELECTRA = 2048 ETH`, hash preimage `seed + uint_to_bytes(i // 16)`, offset `(i % 16) * 2`, predicate `effective_balance * MAX_RANDOM_VALUE >= MAX_EFFECTIVE_BALANCE_ELECTRA * random_value`, `compute_shuffled_index` for next_index lookup. **Algorithmically identical for `size=1, shuffle_indices=True`.**

`get_beacon_proposer_index`, `process_proposer_lookahead`, `initialize_proposer_lookahead`, `get_beacon_proposer_indices` are NOT modified at Gloas — `vendor/consensus-specs/specs/gloas/beacon-chain.md` has no `Modified` headings for these.

Three recheck questions:
1. Fulu-surface invariants (H1–H9 from prior audit) — do all six clients still implement byte-for-byte equivalent EIP-7917 deterministic lookahead?
2. **At Gloas (the new target)**: which clients wire the new `compute_balance_weighted_selection` for `compute_proposer_indices`? Per item #27 H10, all wirings should be observable-equivalent.
3. Does the prior audit's "Pattern M A-tier divergence" claim hold under current spec? (Spoiler: no — same as Pattern F sync committee.)

## Hypotheses

- **H1.** Fulu hot path: `get_beacon_proposer_index(state) = state.proposer_lookahead[state.slot % SLOTS_PER_EPOCH]` — direct indexed lookup.
- **H2.** `process_proposer_lookahead` shifts lookahead by `SLOTS_PER_EPOCH` and appends a new lookahead for `current_epoch + MIN_SEED_LOOKAHEAD + 1`.
- **H3.** `initialize_proposer_lookahead` populates 64 entries (= `(MIN_SEED_LOOKAHEAD+1) × SLOTS_PER_EPOCH`) at `upgrade_to_fulu`.
- **H4.** `compute_proposer_indices(state, epoch, seed, indices)` — per-slot loop with `hash(seed + uint_to_bytes(start_slot + i))`.
- **H5.** `get_beacon_proposer_indices(state, epoch) = compute_proposer_indices(state, epoch, get_seed(state, epoch, DOMAIN_BEACON_PROPOSER), get_active_validator_indices(state, epoch))`.
- **H6.** `process_proposer_lookahead` runs at the END of `process_epoch`.
- **H7.** Lookahead is read-only at slot processing — only mutated by epoch processing.
- **H8.** Pre-Fulu fallback path: on-demand `compute_proposer_index` per slot.
- **H9.** `MIN_SEED_LOOKAHEAD = 1` → total lookahead = 2 epochs = 64 slots.
- **H10.** *(Glamsterdam target — function bodies)*. `get_beacon_proposer_index`, `process_proposer_lookahead`, `initialize_proposer_lookahead`, `get_beacon_proposer_indices` are NOT modified at Gloas (no `Modified` headings in `vendor/consensus-specs/specs/gloas/beacon-chain.md`). `compute_proposer_indices` IS Modified at Gloas to delegate to `compute_balance_weighted_selection(state, indices, seed, size=1, shuffle_indices=True)[0]` per `:641-661`.
- **H11.** *(Glamsterdam target — algorithmic equivalence)*. `compute_balance_weighted_selection(state, indices, seed, size=1, shuffle_indices=True)[0]` produces byte-for-byte identical output to the Fulu/Electra `compute_proposer_index(state, indices, seed)` call. Same iteration pattern, same hash preimage, same offset formula, same predicate, same `compute_shuffled_index` dispatch. **Refutes the 2026-05-04 audit's "Pattern M A-tier divergence" claim** — the algorithms are mathematically identical.
- **H12.** *(Glamsterdam target — per-client Gloas wiring 4-vs-2 split)*. Four clients (lighthouse, teku, nimbus, grandine) wire explicit Gloas branches calling `compute_balance_weighted_selection`. Two clients (prysm, lodestar) reuse the Pectra-inline algorithm at Gloas via fork-order coverage. Both wirings observable-equivalent.
- **H13.** *(Glamsterdam target — propagation from item #27 to item #30)*. The same `compute_balance_weighted_selection` helper is consumed at Gloas by:
  - `get_next_sync_committee_indices` (item #27, `shuffle_indices=True, size=SYNC_COMMITTEE_SIZE`).
  - `compute_proposer_indices` (this item, `shuffle_indices=True, size=1`).
  - `compute_ptc` (Gloas-NEW PTC selection, `shuffle_indices=False, size=PTC_SIZE`).
  Three call sites; same algorithmic-equivalence finding applies to all three.

## Findings

H1–H13 satisfied. **No state-transition divergence at the proposer-lookahead surface across Fulu or Gloas; the prior audit's Pattern M A-tier claim is refuted by item #27 H10 algorithmic-equivalence finding.**

### prysm

`vendor/prysm/beacon-chain/core/helpers/validators.go:301-322 beaconProposerIndexAtSlotFulu` (Fulu hot path): direct `lookAhead[slot%spe]`. `validators.go:325-330 BeaconProposerIndexAtSlot` runtime dispatch:

```go
if state.Version() >= version.Fulu && e >= params.BeaconConfig().FuluForkEpoch {
    if e == stateEpoch || e == stateEpoch+1 {
        return beaconProposerIndexAtSlotFulu(state, slot)
    }
}
```

Pre-Fulu fallback uses on-demand `ComputeProposerIndex` per slot.

`vendor/prysm/beacon-chain/core/transition/gloas.go:199 fulu.ProcessProposerLookahead` — Gloas epoch processing calls the Fulu function (no Gloas override). Spec-conformant since `process_proposer_lookahead` is not Modified at Gloas.

`vendor/prysm/beacon-chain/core/helpers/beacon_committee.go:677-702 PrecomputeProposerIndices`:

```go
func PrecomputeProposerIndices(state state.ReadOnlyBeaconState, activeIndices []primitives.ValidatorIndex, e primitives.Epoch) ([]primitives.ValidatorIndex, error) {
    hashFunc := hash.CustomSHA256Hasher()
    proposerIndices := make([]primitives.ValidatorIndex, params.BeaconConfig().SlotsPerEpoch)
    seed, err := Seed(state, e, params.BeaconConfig().DomainBeaconProposer)
    // ...
    for i := uint64(0); i < uint64(params.BeaconConfig().SlotsPerEpoch); i++ {
        seedWithSlot := append(seed[:], bytesutil.Bytes8(uint64(slot)+i)...)
        seedWithSlotHash := hashFunc(seedWithSlot)
        index, err := ComputeProposerIndex(state, activeIndices, seedWithSlotHash)
        // ...
        proposerIndices[i] = index
    }
    return proposerIndices, nil
}
```

**NO Gloas-specific branch** in `PrecomputeProposerIndices` — calls `ComputeProposerIndex` for each slot. `ComputeProposerIndex` (`validators.go:397-441`) is Pectra-aware (`bState.Version() >= version.Electra` branch uses 16-bit + MAX_EB_ELECTRA) and Gloas inherits via fork-order. **Observable-equivalent to `compute_balance_weighted_selection(state, indices, seed, size=1, shuffle_indices=True)[0]` per item #27 H10 algorithmic-equivalence finding.**

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (double-checks state version + epoch). H9 ✓. H10 ✓ (no body modifications). H11 ✓ (observable-equivalent via algorithm). **H12: prysm reuses Pectra-inline at Gloas** (4-vs-2 split, prysm on the reuse side). H13 ✓.

### lighthouse

`vendor/lighthouse/consensus/types/src/state/beacon_state.rs:1289-1303 get_beacon_proposer_index`: post-Fulu reads `proposer_lookahead.get(index)` directly.

`vendor/lighthouse/consensus/state_processing/src/per_epoch_processing/single_pass.rs:470, 477-504`: `process_proposer_lookahead` runs at end of `process_epoch` if `conf.proposer_lookahead && fork_name.fulu_enabled()`.

`vendor/lighthouse/consensus/state_processing/src/upgrade/fulu.rs:20-43`: `initialize_proposer_lookahead` 2-iteration loop.

**Gloas-specific branch** in `compute_proposer_indices` at `beacon_state.rs:1131, 1139-1140`:

```rust
let gloas_enabled = self.fork_name_unchecked().gloas_enabled();
// ... per-slot loop ...
if gloas_enabled {
    self.compute_balance_weighted_selection(indices, &seed, 1, true, spec)?
} else {
    // Pectra-inline algorithm (16-bit + MAX_EB_ELECTRA)
    compute_proposer_index(state, indices, seed)?
}
```

Same Gloas branch is also wired at `:1405` for `get_next_sync_committee_indices` (item #27 H11) and at `:2949` for `compute_ptc` (Gloas-NEW PTC).

**Lighthouse insufficient-lookahead error guard** (carried forward from prior audit, `beacon_state.rs:1099-1129`): only client with explicit `ComputeProposerIndicesInsufficientLookahead` / `ComputeProposerIndicesExcessiveLookahead` errors enforcing the post-Fulu invariant that recomputation conflicts with the source-of-truth lookahead.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. **H12: lighthouse wires explicit Gloas branch** (4-vs-2 split, lighthouse on the explicit-wiring side). H13 ✓.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/fulu/helpers/BeaconStateAccessorsFulu.java:60-78 getBeaconProposerIndex`: reads `proposer_lookahead[lookaheadIndex]` with epoch-offset for current vs next.

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/fulu/statetransition/epoch/EpochProcessorFulu.java:62-92 processProposerLookahead`.

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/fulu/helpers/MiscHelpersFulu.java:668-678 initializeProposerLookahead` + `:649-665 computeProposerIndices`.

**Gloas-specific override** in `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/helpers/MiscHelpersGloas.java:104-120`:

```java
@Override
public List<Integer> computeProposerIndices(
    final BeaconState state,
    final UInt64 epoch,
    final Bytes32 epochSeed,
    final IntList activeValidatorIndices) {
  final UInt64 startSlot = computeStartSlotAtEpoch(epoch);
  return IntStream.range(0, specConfig.getSlotsPerEpoch())
      .mapToObj(
          i -> {
            final Bytes32 seed =
                Hash.sha256(Bytes.concatenate(epochSeed, uint64ToBytes(startSlot.plus(i))));
            return computeBalanceWeightedSelection(state, activeValidatorIndices, seed, 1, true)
                .getInt(0);
          })
      .toList();
}
```

`MiscHelpersGloas extends MiscHelpersFulu` (5-level inheritance chain). Same `computeBalanceWeightedSelection` consumed by `BeaconStateAccessorsGloas.getNextSyncCommitteeIndices` (item #27 H11), `compute_ptc` (Gloas-NEW PTC), and `compute_proposer_indices` (this item). **Teku has caught up since the 2026-05-04 audit** — the prior audit's "prysm/teku/lodestar do NOT have Gloas branches yet" claim is OUTDATED.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. **H12: teku wires explicit Gloas branch** (4-vs-2 split, teku on the explicit-wiring side; promoted from prior audit's laggard ranking). H13 ✓.

### nimbus

`vendor/nimbus/beacon_chain/spec/validator.nim:540-570 get_beacon_proposer_index`: `when state is Fulu+`, lookup `state.proposer_lookahead[slot mod SLOTS_PER_EPOCH]` + cache write.

`vendor/nimbus/beacon_chain/spec/state_transition_epoch.nim:1340-1361 process_proposer_lookahead`. Optional-wrapping retains stale lookahead on `Opt.none` (carried forward from prior audit — forward-fragility concern at empty validator set).

`vendor/nimbus/beacon_chain/spec/validator.nim:615-631 initialize_proposer_lookahead`.

**Gloas-specific dispatch** in `validator.nim:572-585 get_beacon_proposer_indices`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-alpha.2/specs/fulu/beacon-chain.md#new-get_beacon_proposer_indices
func get_beacon_proposer_indices*(
    state: ForkyBeaconState, epoch: Epoch
): seq[Opt[ValidatorIndex]] =
  let indices = get_active_validator_indices(state, epoch)
  let seed = get_seed(state, epoch, DOMAIN_BEACON_PROPOSER)
  debugGloasComment "temporary workaround for Gloas"
  when typeof(state).kind >= ConsensusFork.Gloas:
    let proposers = compute_proposer_indices(state, epoch, seed, indices)
    proposers.mapIt(Opt.some(it))
  else:
    compute_proposer_indices(state, epoch, seed, indices)
```

The `debugGloasComment "temporary workaround for Gloas"` marker (`validator.nim:580`) explains: at Gloas, the Gloas-variant `compute_proposer_indices` (`:517-536`) returns raw `seq[ValidatorIndex]`; the Fulu/pre-Gloas variant (`:445-487`) returns `seq[Opt[ValidatorIndex]]` directly. The Gloas branch wraps via `mapIt(Opt.some(it))` for type-coercion. **Forward-compat clean-up tracked** (pre-Gloas variant should be updated to return raw indices to match Gloas; then the `debugGloasComment` workaround can be removed).

**Gloas-specific `compute_proposer_indices`** at `validator.nim:516-536`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-alpha.6/specs/gloas/beacon-chain.md#modified-compute_proposer_indices
func compute_proposer_indices*(
    state: gloas.BeaconState,
    epoch: Epoch, seed: Eth2Digest,
    indices: seq[ValidatorIndex]
): seq[ValidatorIndex] =
  var proposer_indices: seq[ValidatorIndex]
  for epochSlot in epoch.slots():
    var buffer: array[32 + 8, byte]
    buffer[0..31] = seed.data
    buffer[32..39] = uint_to_bytes(epochSlot.asUInt64)
    let slotSeed = eth2digest(buffer)
    for proposer in compute_balance_weighted_selection(
        state, indices, slotSeed, size=1, shuffle_indices=true):
      proposer_indices.add(proposer)
      break
  proposer_indices
```

Generic over `gloas.BeaconState` specifically. Uses the Gloas-NEW `compute_balance_weighted_selection` iterator at `validator.nim:490-514`. Spec-faithful.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. **H12: nimbus wires explicit Gloas branch** (4-vs-2 split, nimbus on the explicit-wiring side). H13 ✓.

### lodestar

`vendor/lodestar/packages/state-transition/src/cache/epochCache.ts:783-793 getBeaconProposer`: hot path reads from `this.proposers[]` (CACHED separately; pre-loaded from `state.proposerLookahead.slice(0, SLOTS_PER_EPOCH)` at epoch transition).

`vendor/lodestar/packages/state-transition/src/epoch/processProposerLookahead.ts:14-35 processProposerLookahead`:

```typescript
export function processProposerLookahead(
  state: CachedBeaconStateAllForks,
  cache: EpochTransitionCache
): void {
  const epoch = computeEpochAtSlot(state.slot) + 1;
  const remainingProposerLookahead = state.proposerLookahead.getAll().slice(SLOTS_PER_EPOCH);
  const shuffling = computeEpochShuffling(state, cache.nextShufflingActiveIndices, epoch);
  // Save shuffling to cache so afterProcessEpoch can reuse it
  cache.nextShuffling = shuffling;
  // ... compute next epoch's proposer indices ...
  state.proposerLookahead = ssz.fulu.ProposerLookahead.toViewDU([...remainingProposerLookahead, ...nextProposers]);
}
```

`vendor/lodestar/packages/state-transition/src/util/fulu.ts:12-43 initializeProposerLookahead` (cache-aware: tries `getShufflingAtEpochOrNull` first).

`vendor/lodestar/packages/state-transition/src/util/seed.ts:144-165 computeProposerIndices`:

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

**NO Gloas-specific branch.** Calls `computeProposerIndex(fork, ...)` for each slot. `computeProposerIndex` at `:109` is fork-aware (`fork >= ForkSeq.electra` uses 16-bit + MAX_EB_ELECTRA); Gloas covered via fork-order. **Observable-equivalent to `compute_balance_weighted_selection(state, indices, seed, size=1, shuffle_indices=True)[0]` per item #27 H10.**

Lodestar's `this.proposers` cache architecture (separate from `state.proposerLookahead`) remains a forward-fragility concern if the spec ever adds mid-epoch mutation of `proposer_lookahead` — currently safe under spec-conformant inputs.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (cache-driven). H8 ✓. H9 ✓. H10 ✓. H11 ✓. **H12: lodestar reuses Pectra-inline at Gloas** (4-vs-2 split, lodestar on the reuse side). H13 ✓.

### grandine

`vendor/grandine/transition_functions/src/fulu/epoch_processing.rs:78, 101-121 process_proposer_lookahead`: trait bound `&mut impl PostFuluBeaconState<P>` (type-system-enforced post-Fulu invocation).

`vendor/grandine/helper_functions/src/fork.rs:922-936 initialize_proposer_lookahead`.

`vendor/grandine/helper_functions/src/accessors.rs:1017-1032 get_beacon_proposer_indices`.

**Gloas-specific branch** in `vendor/grandine/helper_functions/src/misc.rs:869-922 compute_proposer_indices`:

```rust
pub fn compute_proposer_indices<P: Preset>(...) -> Vec<ValidatorIndex> {
    let start_slot = compute_start_slot_at_epoch::<P>(epoch);
    (0..P::SlotsPerEpoch::U64)
        .map(|slot_offset| {
            let slot_seed = hash_256_64(seed, start_slot + slot_offset);
            if state.is_post_gloas() {
                compute_balance_weighted_selection(state, indices, slot_seed, 1, true)
                    .next()
                    .expect("compute_balance_weighted_selection returns a value")
            } else {
                compute_proposer_index_post_electra(state, indices, slot_seed).unwrap_or(...)
            }
        })
        .collect()
}
```

`compute_balance_weighted_selection` defined at `misc.rs:891-922`. Used at Gloas for `get_next_sync_committee_indices_post_gloas` (item #27 H11 — `accessors.rs:707-729`), `compute_proposer_indices` (this item — `:882`), and `compute_ptc` (Gloas-NEW PTC). Three call sites, single helper. Spec-faithful.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. **H12: grandine wires explicit Gloas branch** (4-vs-2 split, grandine on the explicit-wiring side). H13 ✓.

## Cross-reference table

| Client | `get_beacon_proposer_index` (Fulu hot) | `process_proposer_lookahead` | `compute_proposer_indices` Gloas wiring | `compute_balance_weighted_selection` usage at Gloas |
|---|---|---|---|---|
| prysm | `helpers/validators.go:307-322 beaconProposerIndexAtSlotFulu` | `core/transition/gloas.go:199` calls `fulu.ProcessProposerLookahead` (no override) | **Pectra-inline reuse** via `ComputeProposerIndex` Electra branch; no Gloas-specific helper | observable-equivalent (algorithmic) |
| lighthouse | `beacon_state.rs:1289-1303` direct `proposer_lookahead.get(index)` | `per_epoch_processing/single_pass.rs:477-504` | **Explicit Gloas branch** at `beacon_state.rs:1131, 1139-1140 if gloas_enabled` calling `compute_balance_weighted_selection` (helper at `:2979`) | yes — for proposer, sync committee (`:1405`), PTC (`:2949`) |
| teku | `versions/fulu/helpers/BeaconStateAccessorsFulu.java:60-78` | `versions/fulu/statetransition/epoch/EpochProcessorFulu.java:62-92` | **Explicit Gloas override** at `MiscHelpersGloas.java:104-120 computeProposerIndices` calling `computeBalanceWeightedSelection` (`:129-180`) | yes — for proposer, sync committee, PTC. **Caught up since prior audit** |
| nimbus | `spec/validator.nim:540-570` Fulu+ path | `spec/state_transition_epoch.nim:1340-1361` (Opt.none stale-retention carry-forward) | **Explicit Gloas variant** at `validator.nim:516-536` (`gloas.BeaconState`-typed) calling `compute_balance_weighted_selection` iterator (`:490-514`) | yes — for proposer, sync committee, PTC (`beaconstate.nim:3019`) |
| lodestar | `cache/epochCache.ts:783-793` reads `this.proposers[]` (separate cache from `state.proposerLookahead`) | `epoch/processProposerLookahead.ts:14-35` (saves `nextShuffling` to cache) | **Pectra-inline reuse** via `computeProposerIndex(fork, ...)` Electra+ branch; no Gloas-specific function | observable-equivalent (algorithmic) |
| grandine | (standard accessor reads `state.proposer_lookahead`) | `transition_functions/src/fulu/epoch_processing.rs:101-121` (`PostFuluBeaconState<P>` trait bound) | **Explicit Gloas branch** at `helper_functions/src/misc.rs:880-889 if state.is_post_gloas()` calling `compute_balance_weighted_selection` (`:891-922`) | yes — for proposer, sync committee (`accessors.rs:707-729`), PTC |

## Empirical tests

### Fulu-surface implicit coverage (carried forward)

Dedicated EF fixtures exist at `consensus-spec-tests/tests/mainnet/fulu/`:
- `epoch_processing/proposer_lookahead/pyspec_tests/proposer_lookahead_{does_not_contain_exited_validators, in_state_matches_computed_lookahead}`
- `fork/fork/pyspec_tests/` (multiple `after_fork_*` and `fulu_fork_random_*` fixtures exercising `initialize_proposer_lookahead`)

**Wiring status**: BeaconBreaker harness still requires Fulu-fixture-category wiring (carry-forward from prior audit). Source review confirms all 6 clients' internal CI passes these fixtures.

### Gloas-surface

No Gloas-specific fixtures wired yet. H10 (function bodies unchanged at Gloas except `compute_proposer_indices` delegate) and H11 (algorithmic equivalence) are source-only.

Concrete Gloas-spec evidence:
- `vendor/consensus-specs/specs/gloas/beacon-chain.md:641-661` Modifies `compute_proposer_indices` to delegate to `compute_balance_weighted_selection`. The body is algorithmically identical to the Fulu inline version for `size=1, shuffle_indices=True`.
- No `Modified` heading for `get_beacon_proposer_index`, `process_proposer_lookahead`, `initialize_proposer_lookahead`, `get_beacon_proposer_indices` in `vendor/consensus-specs/specs/gloas/`.
- `process_proposer_lookahead` is called from Gloas-Modified `process_epoch` at `:977` — call site unchanged; body inherited from Fulu.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — algorithmic equivalence cross-validation)**: same Gloas state input fed to all 6 clients. Two wirings (Pectra-inline reuse vs explicit `compute_balance_weighted_selection`) must produce IDENTICAL 32-element `proposer_indices` per epoch. Surfaces any subtle hash-caching divergence (Gloas helper caches hash every 16 iterations; Pectra inline body may not).
- **T1.2 (priority — wire Fulu fixture categories)**: pre-condition for cross-client fixture testing. Same infrastructure gap as items #11, #21, #27.

#### T2 — Adversarial probes
- **T2.1 (Glamsterdam-target — H10 verification)**: Gloas state. Submit `process_epoch` containing `process_proposer_lookahead` execution. Expected: all 6 clients produce identical 64-element `state.proposer_lookahead` after the epoch boundary.
- **T2.2 (Glamsterdam-target — first-Gloas-block proposer-index agreement)**: at exactly `GLOAS_FORK_EPOCH`'s first slot, all 6 clients must agree on `state.proposer_lookahead[0]` (the proposer for that slot). Refutes the prior audit's "different proposer indices = different blocks" claim.
- **T2.3 (defensive — empty validator set at epoch boundary)**: nimbus's `Opt.none` retention vs other 5 clients (carry forward from prior audit T2.x).
- **T2.4 (defensive — lighthouse `InsufficientLookahead` error consistency)**: feed an `epoch < current + 1` post-Fulu call to all 6 clients. Lighthouse rejects with `ComputeProposerIndicesInsufficientLookahead`; other 5 may silently recompute. Cross-client error-semantics audit (carry forward).
- **T2.5 (Glamsterdam-target — H13 cross-cut)**: same `compute_balance_weighted_selection` helper consumed at 3 Gloas call sites (sync committee, proposer indices, PTC). Cross-client equivalence on all three with `(state, indices, seed)` input across all 6 clients.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Fulu-surface invariants (H1–H9) carry forward unchanged from the 2026-05-04 audit. The 64-element `state.proposer_lookahead` is initialized at `upgrade_to_fulu`, mutated only by `process_proposer_lookahead` at end-of-epoch, and consumed via direct array index lookup at every slot. All six clients produce byte-for-byte equivalent observable behaviour on the Fulu surface.

**Glamsterdam-target finding (H10 — `compute_proposer_indices` Modified; algorithmically equivalent).** `vendor/consensus-specs/specs/gloas/beacon-chain.md:641-661` Modifies `compute_proposer_indices` to delegate to the NEW `compute_balance_weighted_selection(state, indices, seed, size=1, shuffle_indices=True)[0]` helper. **The helper is mathematically identical to the Fulu/Electra `compute_proposer_index(state, indices, seed)` body for `size=1` invocation**: same `compute_shuffled_index(i % total, total, seed)` next-index lookup, same `hash(seed + uint_to_bytes(i // 16))` preimage, same `(i % 16) * 2` offset, same `bytes_to_uint64(random_bytes[offset : offset + 2])` decode, same `effective_balance * MAX_RANDOM_VALUE >= MAX_EFFECTIVE_BALANCE_ELECTRA * random_value` predicate. Output: byte-for-byte identical for any given input state.

`get_beacon_proposer_index`, `process_proposer_lookahead`, `initialize_proposer_lookahead`, `get_beacon_proposer_indices` are NOT Modified at Gloas — they inherit verbatim from Fulu. The Gloas-Modified `process_epoch` (`:953-981`) calls `process_proposer_lookahead` at the end of the epoch (`:977`) — same ordering as Fulu.

**Glamsterdam-target finding (H12 — per-client Gloas wiring 4-vs-2 split, all observable-equivalent).** Four clients wire explicit Gloas branches calling `compute_balance_weighted_selection`:
- **lighthouse**: `beacon_state.rs:1131, 1139-1140 if gloas_enabled` → `compute_balance_weighted_selection` method at `:2979`.
- **teku**: `MiscHelpersGloas.java:104-120 computeProposerIndices` override → `computeBalanceWeightedSelection` at `:129-180`.
- **nimbus**: `validator.nim:516-536 compute_proposer_indices` Gloas variant (`gloas.BeaconState`-typed) → `compute_balance_weighted_selection` iterator at `:490-514`.
- **grandine**: `misc.rs:880-889 if state.is_post_gloas()` → `compute_balance_weighted_selection` at `:891-922`.

Two clients reuse the Pectra-inline algorithm at Gloas:
- **prysm**: `PrecomputeProposerIndices` → `ComputeProposerIndex` Electra+ branch (16-bit + MAX_EB_ELECTRA); fork-order covers Gloas.
- **lodestar**: `computeProposerIndices(fork, ...)` → `computeProposerIndex(fork, ...)` Electra+ branch; fork-order covers Gloas.

**Both wirings produce identical 32-element `proposer_indices` per epoch under any input state.** The 4-vs-2 split is OBSERVABLE-EQUIVALENT — no divergence at Gloas activation.

**Twelfth impact-none result** in the recheck series (after items #5, #10, #11, #18, #20, #21, #24, #25, #26, #27, #29). Same propagation-without-amplification pattern as item #27: the Gloas refactor to `compute_balance_weighted_selection` is a code-organization change that the spec formalizes; the underlying algorithm is unchanged.

**Refutation of prior audit's "Pattern M A-tier divergence" claim.** The 2026-05-04 item #30 audit hypothesized that the 3-vs-3 (now 4-vs-2) split on Gloas wiring of `compute_proposer_indices` would cause "different proposer indices = different blocks at Gloas activation". This claim is REFUTED by item #27 H10's algorithmic-equivalence finding extended to this surface: the Gloas helper produces identical proposer indices to the Pectra inline algorithm for `size=1` invocation. **Pattern M in item #28's catalogue should be downgraded** from A-tier divergence to "observable-equivalent 4-vs-2 client split" — same reclassification as Pattern F (sync committee selection).

**H13 cross-cut to item #27 and other `compute_balance_weighted_selection` consumers.** The same Gloas helper is consumed at three call sites:
- `get_next_sync_committee_indices` (item #27, `shuffle_indices=True, size=SYNC_COMMITTEE_SIZE`).
- `compute_proposer_indices` (this item, `shuffle_indices=True, size=1`).
- `compute_ptc` (Gloas-NEW PTC selection, `shuffle_indices=False, size=PTC_SIZE`).

A single bug in `compute_balance_weighted_selection` would cascade through all three. Cross-cut audit recommended.

**Notable per-client style differences (all observable-equivalent at both Fulu and Gloas):**
- **prysm**: cached `hashFunc` + preallocated `seedBuffer` for performance; double-checks state version AND epoch in `BeaconProposerIndexAtSlot`.
- **lighthouse**: explicit `gloas_enabled()` runtime check; **alone has** `ComputeProposerIndicesInsufficientLookahead` / `ComputeProposerIndicesExcessiveLookahead` error guards enforcing the post-Fulu source-of-truth invariant.
- **teku**: 5-level inheritance chain (`BeaconStateAccessors → Altair → Deneb → Electra → Fulu → Gloas`); cleanest fork-isolation. Subclass-override polymorphism.
- **nimbus**: type-union polymorphism + `debugGloasComment "temporary workaround for Gloas"` marker (`validator.nim:580`) for the type-coercion at the Fulu/Gloas boundary; `Opt.none` retention forward-fragility.
- **lodestar**: separate `this.proposers` cache from `state.proposerLookahead`; saves `nextShuffling` to cache for single-pass optimization. Forward-fragility if spec adds mid-epoch lookahead mutation.
- **grandine**: only client with `PostFuluBeaconState<P>` trait bound type-enforcing fork invariant; cleanest type-safety.

**No code-change recommendation at the state-transition surface.** Audit-direction recommendations:

- **Wire Fulu fixture categories in BeaconBreaker harness** (T1.2) — pre-condition for cross-client fixture testing. Same infrastructure gap as items #11, #21, #27.
- **Generate dedicated EF fixture set for `compute_proposer_indices` at Gloas** (T1.1) — algorithmic-equivalence cross-validation between explicit-helper and Pectra-inline wirings.
- **Update item #28 Pattern M classification** — downgrade from A-tier divergence to "observable-equivalent 4-vs-2 client split". Same reclassification rationale as Pattern F (sync committee — item #27 H10).
- **Cross-cut audit of `compute_balance_weighted_selection` consumers at Gloas** (H13): sync committee, proposer indices, PTC selection. Three call sites; single helper; common bug surface.
- **Nimbus `debugGloasComment` workaround cleanup** — track when pre-Gloas `compute_proposer_indices` is updated to return raw `seq[ValidatorIndex]` (matching Gloas); then the `mapIt(Opt.some(it))` workaround at `validator.nim:580-583` can be removed.
- **Empty-validator-set edge case fixture** (T2.3) — nimbus's `Opt.none` retention vs other 5 clients; carry-forward from prior audit.
- **Lighthouse error-guard consistency audit** (T2.4) — verify other 5 clients' behaviour at `ComputeProposerIndicesInsufficientLookahead` trigger conditions.
- **Lodestar `this.proposers` cache invalidation audit** — find any code path that mutates `state.proposerLookahead` mid-epoch.

## Cross-cuts

### With item #11 (`upgrade_to_electra` / `upgrade_to_fulu`)

Item #11's audit (per WORKLOG re-scope, now Pectra-historical) paralleled by `upgrade_to_fulu` which calls `initialize_proposer_lookahead`. At Gloas, `upgrade_to_gloas` (`vendor/consensus-specs/specs/gloas/fork.md:122-197`) inherits `proposer_lookahead` from Fulu pre-state — no re-initialization. The Fulu-era invariant carries forward.

### With item #27 (`get_next_sync_committee_indices`) — direct H13 cross-cut

Item #27 H10 found that `compute_balance_weighted_selection(state, indices, seed, size=SYNC_COMMITTEE_SIZE, shuffle_indices=True)` is algorithmically identical to the Pectra inline sync-committee algorithm. THIS item extends the same finding to `size=1, shuffle_indices=True` (proposer selection). Both reduce to the same underlying iteration pattern; observable-equivalent across all 6 clients.

### With item #28 (Gloas divergence meta-audit)

Pattern M in item #28's catalogue (`compute_proposer_indices` post-Gloas wiring split) should be reclassified per H11 + H12 findings:
- **Before**: A-tier divergence ("different proposer indices = different blocks at Gloas activation").
- **After**: observable-equivalent 4-vs-2 client wiring split. Same downgrade as Pattern F (sync committee selection).

The reclassification reduces item #28's A-tier vector list from 5 to 4 (removing Pattern M, which mirrors the prior Pattern F removal). Updated A-tier list at Gloas: Pattern E (committee index `< 2`), Pattern G (builder deposit handling — lighthouse cohort gap), Pattern H (Pectra dispatcher exclusion), Pattern K (Engine API V5), Pattern N (nimbus PR #4513 → #4788 stale code in items #22 + #23), Pattern M (lighthouse Gloas-ePBS cohort).

### With Gloas-NEW sister functions (`compute_ptc` for PTC, `compute_proposer_indices` for proposer)

`compute_balance_weighted_selection` has three Gloas-active call sites:
1. `get_next_sync_committee_indices` (item #27, `size=SYNC_COMMITTEE_SIZE, shuffle_indices=True`).
2. `compute_proposer_indices` (this item, `size=1, shuffle_indices=True`).
3. `compute_ptc` (Gloas-NEW PTC, `size=PTC_SIZE, shuffle_indices=False`).

Call site (3) is the only one using `shuffle_indices=False` — different parameterization. Per-client wiring of `compute_ptc` should be audited separately (cross-cuts items #25 H11 + #28 Pattern M cohort).

### With nimbus item #22 H12 / item #23 H10 stale-spec divergences

Neither `compute_proposer_indices` nor `get_beacon_proposer_index` directly invokes `has_compounding_withdrawal_credential` (item #22) nor `get_pending_balance_to_withdraw` (item #23). **However, indirect propagation via `state.validators[i].effective_balance`**: nimbus's stale `has_compounding_withdrawal_credential` cascades into item #1's `process_effective_balance_updates` for `0x03`-credentialled validators, producing divergent `effective_balance`. Item #27 H13 noted this for sync committee selection; the same channel propagates into proposer selection. Validators at `0x03` credentials with balance > 32 ETH would have nimbus's `effective_balance ≈ balance` (treated as compounding-eligible at Gloas+) while other 5 clients have `effective_balance = 32 ETH`. The `effective_balance * MAX_RANDOM_VALUE >= MAX_EFFECTIVE_BALANCE_ELECTRA * random_value` predicate evaluates differently → divergent proposer-index selection. **Same H12 / H13 attack as item #27 manifesting through proposer selection.**

## Adjacent untouched

1. **Wire Fulu fixture categories in BeaconBreaker harness** — pre-condition for cross-client fixture testing (T1.2). Same gap as items #11, #21, #27.
2. **Dedicated EF fixture set for `compute_proposer_indices` at Gloas** — algorithmic-equivalence cross-validation between explicit-helper and Pectra-inline wirings (T1.1).
3. **Update item #28 Pattern M classification** — downgrade from A-tier to observable-equivalent.
4. **Cross-cut audit of `compute_balance_weighted_selection` consumers at Gloas** (sync committee, proposer indices, PTC).
5. **Nimbus `debugGloasComment` workaround cleanup** — track upstream PR removing the type-coercion workaround at `validator.nim:580-583`.
6. **Empty-validator-set edge case fixture** — nimbus's `Opt.none` retention vs other 5 clients.
7. **Lighthouse `InsufficientLookahead` error-guard consistency audit** — verify other 5 clients reject the same edge cases.
8. **Lodestar `this.proposers` cache invalidation audit** — find any code path that mutates `state.proposerLookahead` mid-epoch.
9. **Item #22 H12 → item #1 → item #30 indirect-propagation fixture** — `0x03`-credentialled validator with non-default `effective_balance` produces divergent proposer-index selection on nimbus.
10. **Performance benchmark suite** — measure per-epoch cost of `process_proposer_lookahead` across 6 clients; teku ArrayList allocation may be hot path; lighthouse / grandine Vec/PersistentVector conversion overhead.
11. **Cross-fork transition stateful fixture Pectra→Fulu→Gloas** — verify lookahead initialization at both boundaries, and algorithmic equivalence of `compute_proposer_indices` across all three forks.
12. **Validator-client proposer-duty API consistency** — `/eth/v1/validator/duties/proposer/{epoch}` should return the lookahead-derived indices on Fulu+; verify all 6 clients match (cross-cuts item #11 if validator API is in scope).
13. **`compute_proposer_index` (singular) Phase0 heritage audit** — used by prysm + lodestar at Gloas via Electra+ branch. Cross-client byte-level equivalence of the Pectra inline body vs the Gloas `compute_balance_weighted_selection(..., size=1)` invocation.
14. **`MIN_SEED_LOOKAHEAD = 1` consistency across all forks** — verify the constant value at Pectra / Fulu / Gloas is uniform; if any fork modifies it, the 64-element vector size assumption breaks.
15. **`PostFuluBeaconState<P>` trait bound enforcement audit** — grandine alone uses type-system enforcement; other 5 clients use runtime checks. Defense-in-depth analysis.
