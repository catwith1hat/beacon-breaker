---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [57, 60]
eips: [EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 63: `process_ptc_window` epoch helper

## Summary

All six clients implement Gloas's `process_ptc_window` (consensus-specs `beacon-chain.md:1069-1083`) consistently and spec-conformantly. Each client (i) places the helper LAST in `process_epoch` after `process_proposer_lookahead`, (ii) shifts `state.ptc_window` left by `SLOTS_PER_EPOCH` rows (drops the oldest epoch), (iii) computes new PTC entries for `next_epoch = get_current_epoch(state) + MIN_SEED_LOOKAHEAD + 1` using `compute_ptc` (item #60), and (iv) writes them into the tail. The window-length constant is uniform: `(2 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH` (96 rows on mainnet with MIN_SEED_LOOKAHEAD=1).

Implementation idioms differ — prysm uses a state-mutator method `RotatePTCWindow`, lighthouse uses persistent-tree `pop_front`/`push` on a `milhouse::List` for tree-efficient updates, teku uses `subList` + `ArrayList` + `setAll`, nimbus does index-by-index in-place copy, lodestar reads from cached `epochCtx.payloadTimelinessCommittees` (rather than re-reading `state.ptc_window`), and grandine uses `copy_within` on a `Vec`. All produce identical post-rotation state for any reachable input.

**Verdict: impact none.** No divergence.

## Question

Pyspec `process_ptc_window` at `vendor/consensus-specs/specs/gloas/beacon-chain.md:1069-1083`:

```python
def process_ptc_window(state: BeaconState) -> None:
    """
    Update the cached PTC window.
    """
    # Shift all epochs forward by one
    state.ptc_window[: len(state.ptc_window) - SLOTS_PER_EPOCH] = state.ptc_window[SLOTS_PER_EPOCH:]
    # Fill in the last epoch
    next_epoch = Epoch(get_current_epoch(state) + MIN_SEED_LOOKAHEAD + 1)
    start_slot = compute_start_slot_at_epoch(next_epoch)
    state.ptc_window[len(state.ptc_window) - SLOTS_PER_EPOCH :] = [
        compute_ptc(state, Slot(slot)) for slot in range(start_slot, start_slot + SLOTS_PER_EPOCH)
    ]
```

Container shape at `beacon-chain.md:412`: `ptc_window: Vector[Vector[ValidatorIndex, PTC_SIZE], (2 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH]`. Mainnet: 96 rows × 512 wide.

Position in `process_epoch` (`beacon-chain.md:958-980`): LAST, after `process_proposer_lookahead`:

```python
def process_epoch(state: BeaconState) -> None:
    process_justification_and_finalization(state)
    process_inactivity_updates(state)
    process_rewards_and_penalties(state)
    process_registry_updates(state)
    process_slashings(state)
    process_eth1_data_reset(state)
    process_pending_deposits(state)            # [Modified Gloas:EIP8061]
    process_pending_consolidations(state)
    process_builder_pending_payments(state)    # [New Gloas:EIP7732] — item #57
    process_effective_balance_updates(state)
    process_slashings_reset(state)
    process_randao_mixes_reset(state)
    process_historical_summaries_update(state)
    process_participation_flag_updates(state)
    process_sync_committee_updates(state)
    process_proposer_lookahead(state)
    process_ptc_window(state)                  # [New Gloas:EIP7732] — THIS ITEM
```

Open questions before source review:

1. **Window-length constant** — `(2 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH` per-client identical?
2. **`next_epoch` formula** — `MIN_SEED_LOOKAHEAD + 1` ahead?
3. **Helper position in `process_epoch`** — LAST per spec; per-client?
4. **`compute_ptc` invocation state-snapshot** — runs after `process_effective_balance_updates` + `process_randao_mixes_reset`, so the seed (item #60: `hash(get_seed(state, epoch, DOMAIN_PTC_ATTESTER) + uint_to_bytes(slot))`) and balance-weighting reflect the post-update state.
5. **Cache pre-population vs on-demand recompute** — lighthouse hints at `initialize_committee_cache_for_lookahead` optimization; per-client.

## Hypotheses

- **H1.** All six clients place `process_ptc_window` LAST in `process_epoch` (after `process_proposer_lookahead`).
- **H2.** All six use `next_epoch = current_epoch + MIN_SEED_LOOKAHEAD + 1`.
- **H3.** All six use window-length `(2 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH`.
- **H4.** All six shift left by exactly `SLOTS_PER_EPOCH` rows (drop the oldest epoch).
- **H5.** All six fill the tail (`SLOTS_PER_EPOCH` rows) via `compute_ptc(state, slot)` for `slot ∈ [next_epoch_start, next_epoch_start + SLOTS_PER_EPOCH)`.
- **H6.** `compute_ptc` invocation reads the *post*-effective-balance-update, *post*-randao-reset state (since `process_ptc_window` is last). All six agree.
- **H7** *(forward-fragility)*. Interaction with `process_proposer_lookahead` (Fulu item) — both rotate analogous windowed-state at the epoch boundary, both use `MIN_SEED_LOOKAHEAD + 1` ahead semantics. Verify no shared-state hazard.

## Findings

### prysm

`ProcessPTCWindow` at `vendor/prysm/beacon-chain/core/gloas/payload_attestation.go:352-373`:

```go
func ProcessPTCWindow(ctx context.Context, st state.BeaconState) error {
    _, span := trace.StartSpan(ctx, "gloas.ProcessPTCWindow")
    defer span.End()

    slotsPerEpoch := params.BeaconConfig().SlotsPerEpoch
    lastEpoch := slots.ToEpoch(st.Slot()) + params.BeaconConfig().MinSeedLookahead + 1
    startSlot, err := slots.EpochStart(lastEpoch)
    if err != nil { return err }

    newSlots := make([]*eth.PTCs, slotsPerEpoch)
    for i := range slotsPerEpoch {
        ptc, err := computePTC(ctx, st, startSlot+primitives.Slot(i))
        if err != nil { return err }
        newSlots[i] = &eth.PTCs{ValidatorIndices: ptc}
    }
    return st.RotatePTCWindow(newSlots)
}
```

`next_epoch = ToEpoch(state.slot) + MIN_SEED_LOOKAHEAD + 1` — equivalent to `get_current_epoch(state) + MIN_SEED_LOOKAHEAD + 1` since `ToEpoch(slot) = slot / SLOTS_PER_EPOCH`. Computes SLOTS_PER_EPOCH new PTCs, delegates to state-mutator `RotatePTCWindow`.

State-mutator at `vendor/prysm/beacon-chain/state/state-native/setters_gloas.go:805-839`:

```go
func (b *BeaconState) RotatePTCWindow(newEpochSlots []*ethpb.PTCs) error {
    if b.version < version.Gloas { return errNotSupported("RotatePTCWindow", b.version) }
    slotsPerEpoch := params.BeaconConfig().SlotsPerEpoch
    if uint64(len(newEpochSlots)) != uint64(slotsPerEpoch) { return ... }

    b.lock.Lock(); defer b.lock.Unlock()

    expected := expectedPTCWindowSize()
    if uint64(len(b.ptcWindow)) != uint64(expected) { return ... }

    newWindow := make([]*ethpb.PTCs, expected)
    // Shift left by one epoch.
    lastEpochStart := expected - slotsPerEpoch
    copy(newWindow[:lastEpochStart], b.ptcWindow[slotsPerEpoch:])
    // Fill the last epoch with copied new slots.
    copy(newWindow[lastEpochStart:], ethpb.CopyPTCWindow(newEpochSlots))

    b.ptcWindow = newWindow
    b.markFieldAsDirty(types.PTCWindow)
    return nil
}
```

`expectedPTCWindowSize()` is `(2 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH`. Shift-left + tail-fill match spec.

Caller at `vendor/prysm/beacon-chain/core/transition/gloas.go:202` — last call in `processEpochGloas`, after `fulu.ProcessProposerLookahead`. Order matches spec.

### lighthouse

`process_ptc_window` at `vendor/lighthouse/consensus/state_processing/src/per_epoch_processing/single_pass.rs:540-580`:

```rust
pub fn process_ptc_window<E: EthSpec>(
    state: &mut BeaconState<E>,
    spec: &ChainSpec,
) -> Result<Arc<CommitteeCache>, Error> {
    let slots_per_epoch = E::slots_per_epoch() as usize;

    // Convert Vector -> List to use tree-efficient pop_front.
    let ptc_window = state.ptc_window()?.clone();
    let mut window: List<_, E::PtcWindowLength> = List::from(ptc_window);

    // Drop the oldest epoch from the front (reuses shared tree nodes).
    window.pop_front(slots_per_epoch)...?;

    // Compute PTC for the new lookahead epoch
    let next_epoch = state
        .current_epoch()
        .safe_add(spec.min_seed_lookahead.as_u64())?
        .safe_add(1)?;
    let start_slot = next_epoch.start_slot(E::slots_per_epoch());

    // Build a committee cache for the lookahead epoch (beyond the normal Next bound)
    let committee_cache = state.initialize_committee_cache_for_lookahead(next_epoch, spec)?;

    for i in 0..slots_per_epoch {
        let slot = start_slot.safe_add(i as u64)?;
        let ptc = state.compute_ptc_with_cache(slot, &committee_cache, spec)?;
        ...
        window.push(entry)...?;
    }
    ...
}
```

`next_epoch = current_epoch + min_seed_lookahead + 1` matches spec. Uses `milhouse::List`'s `pop_front` to shift (tree-efficient persistent-data-structure update) + `push` to append. Optimization: builds the committee cache once for the lookahead epoch and re-uses across all SLOTS_PER_EPOCH `compute_ptc` calls.

Caller at `single_pass.rs:494-498`:

```rust
let lookahead_committee_cache = if conf.ptc_window && fork_name.gloas_enabled() {
    Some(process_ptc_window(state, spec)?)
} else { None };
```

Fork-gated; called last in the Gloas-enabled single-pass epoch processor (after `process_proposer_lookahead` at line 491). Order matches spec.

### teku

`processPtcWindow` at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/statetransition/epoch/EpochProcessorGloas.java:113-135`:

```java
@Override
public void processPtcWindow(final MutableBeaconState state) {
  final MutableBeaconStateGloas stateGloas = MutableBeaconStateGloas.required(state);
  // Shift all epochs forward by one
  final List<SszUInt64Vector> ptcToShiftOut =
      stateGloas
          .getPtcWindow()
          .asList()
          .subList(specConfig.getSlotsPerEpoch(), stateGloas.getPtcWindow().size());
  // Fill in the last epoch
  final UInt64 nextEpoch =
      beaconStateAccessors.getCurrentEpoch(state).plus(specConfig.getMinSeedLookahead()).plus(1);
  final UInt64 startSlot = miscHelpers.computeStartSlotAtEpoch(nextEpoch);
  final List<SszUInt64Vector> lastEpochPtcWindow =
      UInt64.range(startSlot, startSlot.plus(specConfig.getSlotsPerEpoch()))
          .map(slot -> beaconStateAccessorsGloas.computePtc(state, slot))
          .toList();
  final List<SszUInt64Vector> ptcWindow = new ArrayList<>(ptcToShiftOut);
  ptcWindow.addAll(lastEpochPtcWindow);

  stateGloas.setPtcWindow(
      schemaDefinitionsGloas.getPtcWindowSchema().createFromElements(ptcWindow));
}
```

Note the variable name `ptcToShiftOut` is misleading — `subList(SLOTS_PER_EPOCH, size)` is the **survivors** (the entries that remain after the shift), not the dropped ones. Behavior matches spec: shift left + append. `next_epoch = current + MIN_SEED_LOOKAHEAD + 1`. Window-length constant uniform via `specConfig.getSlotsPerEpoch() * (2 + getMinSeedLookahead())` (implicit via `PtcWindowSchema`).

Pre-Gloas no-ops at `EpochProcessorPhase0.java:115` and `EpochProcessorAltair.java:162` — base-interface default; only Gloas overrides.

Caller at `AbstractEpochProcessor.java:146 processPtcWindow(state)` — last call in the abstract `processEpoch` (after `processProposerLookahead`). Order matches spec.

### nimbus

`process_ptc_window` at `vendor/nimbus/beacon_chain/spec/state_transition_epoch.nim:1406-1427`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.7.0-alpha.4/specs/gloas/beacon-chain.md#new-process_ptc_window
proc process_ptc_window*(
    state: var (gloas.BeaconState | heze.BeaconState),
    cache: var StateCache) =
  ## Update the cached PTC window.
  let
    current_epoch = state.get_current_epoch()
    new_epoch = current_epoch + MIN_SEED_LOOKAHEAD + 1

  # Shift all epochs forward by one
  for i in 0 ..< (1 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH:
    state.ptc_window[i] = state.ptc_window.item(i + SLOTS_PER_EPOCH)

  # Fill in the last epoch
  const base_index = (1 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH
  for slot_offset in 0 ..< SLOTS_PER_EPOCH:
    let slot = new_epoch.start_slot() + slot_offset
    clearCaches(state.ptc_window, (base_index + slot_offset).Limit)
    var i = 0
    for idx in compute_ptc(state, slot, cache):
      state.ptc_window.data[base_index + slot_offset][i] = uint64(idx)
      inc i
```

Loop bound `(1 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH` is the count of *surviving* rows = `total_length - SLOTS_PER_EPOCH` = `(2 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH - SLOTS_PER_EPOCH`. ✓ Matches spec.

`base_index` = start of the tail-fill region = `(1 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH`. ✓

Caller at `state_transition_epoch.nim:1683 process_ptc_window(state, cache) # [New in Gloas:EIP7732]` — last call in `process_epoch` for the Gloas branch. Order matches spec.

### lodestar

`processPtcWindow` at `vendor/lodestar/packages/state-transition/src/epoch/processPtcWindow.ts:15-38`:

```typescript
export function processPtcWindow(state: CachedBeaconStateGloas, cache: EpochTransitionCache): void {
  const nextEpoch = state.epochCtx.epoch + MIN_SEED_LOOKAHEAD + 1;
  const nextEpochShuffling =
    cache.nextShuffling ?? computeEpochShuffling(state, cache.nextShufflingActiveIndices, nextEpoch);
  cache.nextShuffling = nextEpochShuffling;

  const newNextPayloadTimelinessCommittees = computePayloadTimelinessCommitteesForEpoch(
    state,
    nextEpoch,
    nextEpochShuffling.committees,
    state.epochCtx.effectiveBalanceIncrements
  );

  // Stash for finalProcessEpoch to shift into epoch cache
  cache.nextEpochPayloadTimelinessCommittees = newNextPayloadTimelinessCommittees;

  // Write shifted window to state: current(N) + next(N+1) + newlyComputed(N+2)
  // From the perspective of upcoming epoch N+1, this is previous + current + next
  state.ptcWindow = ssz.gloas.PtcWindow.toViewDU([
    ...state.epochCtx.payloadTimelinessCommittees,
    ...state.epochCtx.nextPayloadTimelinessCommittees,
    ...newNextPayloadTimelinessCommittees,
  ]);
}
```

**Different implementation pattern** but functionally equivalent. Instead of mutating `state.ptcWindow` via shift+append on the existing array, lodestar **rebuilds** the entire 96-row window from three cached PTC lists in the epoch context:

- `epochCtx.payloadTimelinessCommittees` — the current epoch's PTCs (which become the *previous* epoch's after slot-advance).
- `epochCtx.nextPayloadTimelinessCommittees` — the next epoch's PTCs (which become the *current* after slot-advance).
- `newNextPayloadTimelinessCommittees` — just-computed PTCs for `current + MIN_SEED_LOOKAHEAD + 1`.

This is the same set of three epochs the spec semantic produces; the cache rotation happens at the epoch transition. `computePayloadTimelinessCommitteesForEpoch` (in `util/seed.ts`) is the lodestar equivalent of `compute_ptc` (item #60); produces byte-identical PTCs.

`next_epoch = epochCtx.epoch + MIN_SEED_LOOKAHEAD + 1` matches spec.

Caller at `vendor/lodestar/packages/state-transition/src/epoch/index.ts:31` import + `:59 processPtcWindow,` in the ordered epoch-processing list. Position: last (after `processProposerLookahead`).

### grandine

`process_ptc_window` at `vendor/grandine/transition_functions/src/gloas/epoch_processing.rs:185-204`:

```rust
fn process_ptc_window<P: Preset>(state: &mut impl PostGloasBeaconState<P>) -> Result<()> {
    let mut ptc_window = state.ptc_window().into_iter().collect::<Vec<_>>();
    let last_epoch_start = ptc_window.len().saturating_sub(P::SlotsPerEpoch::USIZE);

    ptc_window.copy_within(P::SlotsPerEpoch::USIZE.., 0);

    let target_epoch = get_current_epoch(state).saturating_add(P::MinSeedLookahead::U64 + 1);
    let start_slot = misc::compute_start_slot_at_epoch::<P>(target_epoch);

    let ptcs = (start_slot..start_slot + P::SlotsPerEpoch::U64)
        .map(|slot| ptc_for_slot_for_epoch_processing(state, slot))
        .collect::<Result<Vec<_>>>()?;

    let refs = ptcs.iter().collect::<Vec<_>>();
    ptc_window[last_epoch_start..].copy_from_slice(&refs);

    *state.ptc_window_mut() = PtcWindow::<P>::try_from_iter(ptc_window.into_iter().cloned())?;

    Ok(())
}
```

`copy_within(SlotsPerEpoch.., 0)` shifts left by SLOTS_PER_EPOCH. `target_epoch = current + MIN_SEED_LOOKAHEAD + 1`. Tail-fill via `copy_from_slice`. Spec-conformant.

Note: `saturating_add` on the `target_epoch` computation is the same overflow-policy pattern audited in item #61 — mainnet-unreachable.

Caller at `vendor/grandine/transition_functions/src/gloas/epoch_processing.rs:92 process_ptc_window(state)?;` — last call in `process_epoch`'s Gloas branch (after `fulu::process_proposer_lookahead` at line 89). Order matches spec.

## Cross-reference table

| Client | `process_ptc_window` location | Position in `process_epoch` (H1) | `next_epoch` formula (H2) | Window length (H3) | Shift idiom (H4) | Tail-fill idiom (H5) |
|---|---|---|---|---|---|---|
| prysm | `payload_attestation.go:352` + state-mutator `setters_gloas.go:805` | LAST (after `ProcessProposerLookahead`) | `ToEpoch(slot) + MinSeedLookahead + 1` | `(2 + MinSeedLookahead) * SLOTS_PER_EPOCH` via `expectedPTCWindowSize()` | new buffer + `copy(...[slotsPerEpoch:])` | `copy` with `CopyPTCWindow(newEpochSlots)` |
| lighthouse | `single_pass.rs:540` | LAST (after `process_proposer_lookahead` at :491) | `current_epoch.safe_add(min_seed_lookahead).safe_add(1)` | `E::PtcWindowLength` (compile-time per-spec preset) | `milhouse::List::pop_front(slots_per_epoch)` (tree-efficient) | `compute_ptc_with_cache` + `push` (pre-built committee cache) |
| teku | `EpochProcessorGloas.java:114` | LAST (`AbstractEpochProcessor.java:146`) | `getCurrentEpoch(state).plus(getMinSeedLookahead()).plus(1)` | implicit via `PtcWindowSchema` | `subList(SLOTS_PER_EPOCH, size)` | `UInt64.range(...).map(computePtc).toList()` + `addAll` |
| nimbus | `state_transition_epoch.nim:1407` | LAST (`:1683`) | `current_epoch + MIN_SEED_LOOKAHEAD + 1` | compile-time constant per preset | in-place index loop `for i in 0 ..< (1+MSL)*SE` | `for idx in compute_ptc(...) yield` per-slot |
| lodestar | `processPtcWindow.ts:15` | LAST (in `epoch/index.ts:59`) | `epochCtx.epoch + MIN_SEED_LOOKAHEAD + 1` | implicit via `ssz.gloas.PtcWindow` schema | **rebuild from 3 cached PTC lists** (current + next + newly-computed) | `computePayloadTimelinessCommitteesForEpoch` |
| grandine | `epoch_processing.rs:185` | LAST (`:92`, after `fulu::process_proposer_lookahead`) | `current_epoch.saturating_add(MinSeedLookahead::U64 + 1)` | `PtcWindow::<P>` const generic | `Vec::copy_within(SLOTS_PER_EPOCH.., 0)` | `copy_from_slice` |

All 6 clients match spec on H1 (LAST position), H2 (`+ MIN_SEED_LOOKAHEAD + 1`), H3 (`(2 + MSL) * SE` shape), H4 (shift by SLOTS_PER_EPOCH), and H5 (per-slot `compute_ptc` over the new tail). H6 holds since `process_ptc_window` runs after `process_effective_balance_updates` + `process_randao_mixes_reset` in all clients. H7: `process_proposer_lookahead` runs immediately before in every client; both use `+ MIN_SEED_LOOKAHEAD + 1` semantics; no shared-state hazard observed (the lookahead uses proposer indices; PTC uses balance-weighted selection — distinct state slices).

## Empirical tests

Implicit coverage: every Gloas epoch-boundary fixture exercises `process_ptc_window`. Both nimbus and grandine ship dedicated EF spec-test wrappers for this helper:

- nimbus: `vendor/nimbus/ConsensusSpecPreset-mainnet.md:5584 process_ptc_window__shifts_all_epochs [Preset: mainnet] OK`, `ConsensusSpecPreset-minimal.md:6009 process_ptc_window__shifts_all_epochs [Preset: minimal] OK` — passes both presets.
- grandine: `vendor/grandine/transition_functions/src/gloas/epoch_processing.rs:495-503` `mainnet_process_ptc_window` + `minimal_process_ptc_window` test-runner cases.

Cross-client run via EF fixtures pending (driver/runners would benefit from a dedicated Gloas-epoch-process-ptc-window runner).

Suggested fuzzing vectors:

- **T1.1 (canonical rotation).** Run a Gloas epoch-boundary block import across all 6 clients; diff post-state `ptc_window` byte-by-byte. Expected: identical.
- **T1.2 (preset coverage).** Mainnet + minimal preset; verify the window-length constant differs as expected (`(2 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH`).
- **T2.1 (effective-balance edge).** Validator effective balance changes during the epoch; verify the new PTC row uses the post-update value (since `process_ptc_window` runs after `process_effective_balance_updates`).
- **T2.2 (RANDAO edge).** PTC seed depends on `get_seed(state, epoch, DOMAIN_PTC_ATTESTER)`; verify the post-`process_randao_mixes_reset` seed is consistent across clients.
- **T2.3 (fork-boundary first rotation).** First `process_ptc_window` invocation immediately after `upgrade_to_gloas` (item #64). The window was populated by `initialize_ptc_window`; verify the first rotation produces the same delta across all clients.

## Conclusion

All six clients implement `process_ptc_window` consistently and spec-conformantly. Window-length constant uniform (`(2 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH`); position in `process_epoch` uniform (LAST, after `process_proposer_lookahead`); shift-and-fill semantics uniform. Implementation idioms differ — prysm uses a state-mutator method, lighthouse uses persistent-tree updates, teku uses `subList`+`addAll`, nimbus does in-place index loops, lodestar rebuilds from a three-epoch cache, grandine uses `Vec::copy_within` — but all produce byte-identical post-rotation state on every reachable input.

**Verdict: impact none.** No divergence. Audit closes.

## Cross-cuts

### With item #57 (`process_builder_pending_payments`)

Sibling epoch helper that rotates `state.builder_pending_payments` (2-epoch window vs PTC's `(2+MSL)`-epoch window). Both placed in the Gloas-modified `process_epoch` ladder (item #57 is between `process_pending_consolidations` and `process_effective_balance_updates`; `process_ptc_window` is last). Same ordering audit pattern; both spec-conformant cross-client.

### With item #60 (PTC read side: `get_ptc` / `compute_ptc`)

Item #60 audited the read side; this item is the write side of the same cache. Together they close the PTC-window round-trip. Lodestar's cache-rebuild pattern in `processPtcWindow` consumes `epochCtx.payloadTimelinessCommittees` which is the same data that `get_ptc` reads.

### With `process_proposer_lookahead` (Fulu item #56-adjacent)

Both rotate windowed-state at the epoch boundary with `+ MIN_SEED_LOOKAHEAD + 1` semantics. `process_proposer_lookahead` runs immediately before `process_ptc_window` in `process_epoch`. Spec-conformant ordering across all 6 clients.

### With item #64 (`upgrade_to_gloas`)

`upgrade_to_gloas` initializes `ptc_window` via `initialize_ptc_window` (spec `fork.md:33-72`); the first `process_ptc_window` post-upgrade rotates that initial population. Cross-cut on the round-trip.

## Adjacent untouched

1. **`compute_balance_weighted_selection` triple-call cross-cut (item #68)** — `process_ptc_window` invokes `compute_ptc` SLOTS_PER_EPOCH times per epoch boundary; each call goes through `compute_balance_weighted_selection`. Pending audit.
2. **Lighthouse's `initialize_committee_cache_for_lookahead` optimization** — used only by lighthouse on the lookahead epoch (beyond the normal Next bound). Verify the cache invariants don't drift if epoch processing is interrupted/re-run.
3. **Lodestar's `epochCtx.payloadTimelinessCommittees` lifecycle** — the cache rotation at slot-advance is critical; if the cache desyncs, lodestar's `ptcWindow` would carry stale entries. Worth a separate audit on the cache invariant.
4. **Performance: PTC computation is `SLOTS_PER_EPOCH * PTC_SIZE = 32 * 512 = 16,384` validator selections per epoch** — the prysm changelog entry `satushh_perf-ptc-balance-weighted-hash-cache.md` notes caching `random_bytes` across 16 rounds (mirrors consensus-specs PR #5079). Cross-cut with item #68's `compute_balance_weighted_selection` audit.
