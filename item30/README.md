# Item 30 — `get_beacon_proposer_index` (Fulu-modified) + `process_proposer_lookahead` + `initialize_proposer_lookahead` + `compute_proposer_indices` + `get_beacon_proposer_indices` audit

**Status:** no-divergence-pending-fixture-run — audited 2026-05-04. **First Fulu-NEW item** of the corpus (prior items #1–#29 audited the Pectra surface). EIP-7917 deterministic proposer lookahead — replaces the on-demand proposer-index computation with a pre-computed `proposer_lookahead` vector in `BeaconState`. Hot-path consumed every slot at block proposal/validation; cold-path mutated once per epoch via `process_proposer_lookahead` at the end of `process_epoch`. Cross-cuts item #11 (paralleled by `upgrade_to_fulu` which calls `initialize_proposer_lookahead`) and item #27 (`get_next_sync_committee_indices` uses similar `compute_proposer_index` primitive; both proposer + sync-committee selection get parallel Gloas modifications).

The migration from on-demand to pre-computed proposer indices opens a new class of divergence risk: state-cache staleness, lookahead-vs-recomputed conflicts, and migration-time alignment at exactly `FULU_FORK_EPOCH`. Source review confirms all 6 clients implement the spec faithfully; the divergence surface is entirely in error-guard semantics, in-place vs allocation patterns, and pre-Fulu fallback handling.

## Scope

In: `get_beacon_proposer_index(state)` Fulu-modified hot path; `process_proposer_lookahead(state)` per-epoch update; `initialize_proposer_lookahead(state)` called once at `upgrade_to_fulu`; `compute_proposer_indices(state, epoch, seed, indices)` pure function; `get_beacon_proposer_indices(state, epoch)` accessor; the `proposer_lookahead: Vector[ValidatorIndex, 64]` field in BeaconState (MIN_SEED_LOOKAHEAD=1 × 2 × SLOTS_PER_EPOCH=32).

Out: `compute_proposer_index` (Phase0-heritage, audited at item #27 cross-cut); fork-choice integration of proposer indices (Track D); validator-client proposer-duty API (out-of-scope per OUT_OF_SCOPE.md); pre-Fulu on-demand path (still present in all 6 as fallback but not the audit target).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | Fulu hot path: `get_beacon_proposer_index(state) = state.proposer_lookahead[state.slot % SLOTS_PER_EPOCH]` — direct indexed lookup | ✅ all 6 | Single array index; no recomputation. |
| H2 | `process_proposer_lookahead` shifts lookahead by SLOTS_PER_EPOCH and appends new lookahead for `current_epoch + MIN_SEED_LOOKAHEAD + 1` | ✅ all 6 | Confirmed via spec text and per-client source. |
| H3 | `initialize_proposer_lookahead` populates 64 entries (= (MIN_SEED_LOOKAHEAD+1) × SLOTS_PER_EPOCH) at `upgrade_to_fulu` time | ✅ all 6 | All 6 use 2-iteration loop covering current + current+1. |
| H4 | `compute_proposer_indices(state, epoch, seed, indices)` — per-slot loop with `hash(seed + uint_to_bytes(start_slot + i))` | ✅ all 6 | Identical hash-input layout. |
| H5 | `get_beacon_proposer_indices(state, epoch) = compute_proposer_indices(state, epoch, get_seed(state, epoch, DOMAIN_BEACON_PROPOSER), get_active_validator_indices(state, epoch))` | ✅ all 6 | Standard spec composition. |
| H6 | `process_proposer_lookahead` runs at the END of `process_epoch` (after `process_sync_committee_updates`) | ✅ all 6 | Spec ordering preserved. |
| H7 | Lookahead is read-only at slot processing — only mutated by epoch processing | ✅ all 6 | No mid-epoch mutation observed. |
| H8 | Pre-Fulu fallback: when state is pre-Fulu, fall back to on-demand computation via `compute_proposer_index` | ✅ all 6 | Each client implements explicit Fulu/pre-Fulu split. |
| H9 | `MIN_SEED_LOOKAHEAD = 1` => total lookahead = 2 epochs = 64 slots | ✅ all 6 | Mainnet preset value. |
| H10 | Forward-compat at Gloas: `compute_proposer_indices` switches to `compute_balance_weighted_selection` (parallel to item #27 sync committee modification) | ✅ confirmed in 3 of 6 (lighthouse, nimbus, grandine — pre-emptive Gloas pattern); prysm/teku/lodestar do NOT have Gloas branches yet | NEW Pattern M for item #28 catalogue. |

## Per-client cross-reference

| Client | Hot path: `get_beacon_proposer_index` | `process_proposer_lookahead` | `initialize_proposer_lookahead` (upgrade) | `compute_proposer_indices` | `get_beacon_proposer_indices` |
|---|---|---|---|---|---|
| **prysm** | `helpers/validators.go:307-322` (`beaconProposerIndexAtSlotFulu`) — direct `lookAhead[slot%spe]`; pre-Fulu seed-compute fallback | `core/transition/gloas.go:199` `fulu.ProcessProposerLookahead` | `helpers/beacon_committee.go:660-675` (Go for-range) | `helpers/beacon_committee.go:679-702` (`PrecomputeProposerIndices`) | (folded into `BeaconProposerIndexAtSlot`) |
| **lighthouse** | `types/src/state/beacon_state.rs:1289-1303` direct `proposer_lookahead.get(index)` post-Fulu | `state_processing/src/per_epoch_processing/single_pass.rs:477-504` (run if `conf.proposer_lookahead && fork_name.fulu_enabled()`) | `state_processing/src/upgrade/fulu.rs:20-36` | `types/src/state/beacon_state.rs:1083-1149` (with **insufficient-lookahead error guard #1099-1129**) | `types/src/state/beacon_state.rs:1308-1337` |
| **teku** | `versions/fulu/helpers/BeaconStateAccessorsFulu.java:60-78` reads `proposer_lookahead[lookaheadIndex]` (with epoch offset for current vs next) | `versions/fulu/statetransition/epoch/EpochProcessorFulu.java:62-92` | `versions/fulu/helpers/MiscHelpersFulu.java:668-678` (Java IntStream) | `versions/fulu/helpers/MiscHelpersFulu.java:649-665` | `versions/fulu/helpers/BeaconStateAccessorsFulu.java:80-84` |
| **nimbus** | `spec/validator.nim:540-570` — `when state is Fulu+`, lookup `state.proposer_lookahead[slot mod SLOTS_PER_EPOCH]` + cache write | `spec/state_transition_epoch.nim:1340-1361` | `spec/validator.nim:615-631` | `spec/validator.nim:444-456` | **TWO overloads**: `:572-585` (epoch-only Fulu+) and `:588-613` (shuffled-indices pre-Fulu fallback) |
| **lodestar** | `cache/epochCache.ts:783-793` `getBeaconProposer` reads from `this.proposers[]` (CACHED separately from `state.proposerLookahead`); pre-loaded at epoch transition | `epoch/processProposerLookahead.ts:14-35` (also saves `nextShuffling` to cache) | `util/fulu.ts:12-43` (cache-aware: tries `getShufflingAtEpochOrNull` first) | `util/seed.ts:144-165` | (no separate function — uses `computeProposerIndices` directly) |
| **grandine** | (uses standard accessor; reads `state.proposer_lookahead`) | `transition_functions/src/fulu/epoch_processing.rs:101-121` (uses `PostFuluBeaconState<P>` trait bound; `copy_within` Rust idiom) | `helper_functions/src/fork.rs:922-936` | `helper_functions/src/misc.rs:869-889` | `helper_functions/src/accessors.rs:1017-1032` |

## Notable per-client findings

### Lighthouse insufficient-lookahead error guard (defensive — others don't have it)

Lighthouse's `compute_proposer_indices` has an explicit error guard at `beacon_state.rs:1099-1129`:

```rust
if spec.fork_name_at_epoch(epoch).fulu_enabled() {
    // Post-Fulu we must never compute proposer indices using insufficient lookahead.
    // This would be very dangerous as it would lead to conflicts between the *true* proposer
    // as defined by `self.proposer_lookahead` and the output of this function.
    if self.fork_name_unchecked().fulu_enabled()
        && epoch < current_epoch.safe_add(spec.min_seed_lookahead)? {
        return Err(BeaconStateError::ComputeProposerIndicesInsufficientLookahead { ... });
    }
} else {
    // Pre-Fulu the situation is reversed, we *should not* compute proposer indices using
    // too much lookahead. To do so would make us vulnerable to changes in the proposer
    // indices caused by effective balance changes.
    if epoch >= current_epoch.safe_add(spec.min_seed_lookahead)? {
        return Err(BeaconStateError::ComputeProposerIndicesExcessiveLookahead { ... });
    }
}
```

**Subtle invariant flip**: pre-Fulu the dangerous direction was "too far forward" (effective balances might change). Post-Fulu the dangerous direction is "not far enough forward" (the lookahead is the source of truth and recomputation would diverge). **Other 5 clients don't have this explicit guard** — they rely on caller discipline. Lighthouse comment makes the contract explicit: "this would be very dangerous as it would lead to conflicts between the *true* proposer as defined by `self.proposer_lookahead` and the output of this function."

**Forward-compat consequence**: at the Fulu→Gloas transition, this guard logic must extend to handle Gloas's `compute_balance_weighted_selection` correctly — no other client needs the same care because they don't enforce the contract.

### Lodestar caches `proposers` separately from `state.proposerLookahead`

Lodestar's hot-path `getBeaconProposer` (`epochCache.ts:783-793`) does NOT read directly from `state.proposerLookahead` — it reads from `this.proposers[]`, populated at epoch transition from `state.proposerLookahead.slice(0, SLOTS_PER_EPOCH)` (`epochCache.ts:415-416`, `714-715`).

```typescript
getBeaconProposer(slot: Slot): ValidatorIndex {
  const epoch = computeEpochAtSlot(slot);
  if (epoch !== this.currentShuffling.epoch) {
    throw new EpochCacheError({ code: PROPOSER_EPOCH_MISMATCH, ... });
  }
  return this.proposers[slot % SLOTS_PER_EPOCH];
}
```

**Cache invalidation risk**: if `state.proposerLookahead` is mutated mid-epoch, `this.proposers` becomes stale. The spec only mutates `proposer_lookahead` at end of epoch (in `process_proposer_lookahead`), so this is safe for spec-compliant inputs. **But this is a forward-fragility class**: any future spec change that mutates `proposer_lookahead` mid-epoch would silently diverge lodestar from the other 5.

The comment at `epochCache.ts:780-781` explicitly notes this design rationale: "Read from proposers instead of state.proposer_lookahead because we set it in `finalProcessEpoch()`".

### Nimbus has TWO `get_beacon_proposer_indices` overloads (pre-Fulu artifact)

Nimbus's `validator.nim` defines two overloads:
- **Line 572-585**: `(state, epoch)` — Fulu+ path, returns `seq[Opt[ValidatorIndex]]`
- **Line 588-613**: `(state, shuffled_indices, epoch)` — pre-Fulu path, uses `compute_inverted_shuffled_index` to map shuffled indices back

At Fulu+, the second overload dispatches to the first via `get_beacon_proposer_indices(state, epoch)` (line 612-613). **Migration artifact**: pre-Fulu used shuffled indices for proposer selection; Fulu uses sorted active indices. Nimbus retained both code paths.

**Future research**: verify no caller bypasses the Fulu+ dispatch and accidentally uses the pre-Fulu shuffled path on a Fulu state.

### Nimbus Optional-wrapping retains stale lookahead on empty validator set

Nimbus's `process_proposer_lookahead` (`state_transition_epoch.nim:1357-1359`):

```nim
for i in 0 ..< SLOTS_PER_EPOCH:
  if new_proposers[i].isSome():
    mitem(state.proposer_lookahead, last_epoch_start + i) = new_proposers[i].get.uint64
```

If `new_proposers[i]` is `Opt.none` (empty validator set or compute failure), nimbus **retains the stale lookahead value** from the previous epoch. Other 5 clients don't have this Optional wrapping — they would either error or write a default.

**Forward-fragility class**: at empty validator set, nimbus's behavior diverges silently from the other 5. This is dead code today (mainnet has > 1M validators) but a forward-compat divergence vector.

### Grandine uses `PostFuluBeaconState<P>` trait bound

Grandine's `process_proposer_lookahead` (`transition_functions/src/fulu/epoch_processing.rs:101-121`) takes `&mut impl PostFuluBeaconState<P>` — the type system enforces that the function can only be called on a post-Fulu state. Other clients use runtime checks (prysm `state.Version() >= version.Fulu`, lighthouse `fork_name.fulu_enabled()`, etc.).

Module organization: dedicated `transition_functions/src/fulu/` directory mirrors items #12, #14, #19's "module-namespace dispatch" finding. Same pattern documented in item #28 Pattern I.

### Teku constructs new `ArrayList` (not in-place; allocation per epoch)

Teku's `processProposerLookahead` (`EpochProcessorFulu.java:62-92`) constructs a new `ArrayList<>` from `subList(slotsPerEpoch, size())` then concatenates `lastEpochProposerIndices`. This is **not in-place**: O(N) memory allocation per epoch.

Other clients:
- prysm: in-place via Go slice manipulation
- lighthouse: copies to Vec, copy_within, converts back to Vector — temporary allocation
- nimbus: in-place via `mitem(state.proposer_lookahead, i)` mutation
- lodestar: constructs new Uint8 SSZ view via `ssz.fulu.ProposerLookahead.toViewDU([...])` — also allocates
- grandine: copies to Vec, copy_within, converts back to PersistentVector — temporary allocation

**Performance trade-off, no consensus impact.** Equivalent output.

### Prysm double-checks BOTH state version AND epoch in `BeaconProposerIndexAtSlot`

Prysm's `BeaconProposerIndexAtSlot` (`validators.go:328-330`):

```go
if state.Version() >= version.Fulu && e >= params.BeaconConfig().FuluForkEpoch {
    if e == stateEpoch || e == stateEpoch+1 {
        return beaconProposerIndexAtSlotFulu(state, slot)
    }
}
```

Other 5 clients check fork on state alone OR on epoch alone — not both. Prysm's double-check protects against the (theoretically impossible) state at Fulu but slot in pre-Fulu epoch. **Defensive programming, no consensus impact.**

### Initialize_proposer_lookahead loop boundary syntax differs across 6 clients

All 6 produce the same 2-iteration loop (current + current+1) but use different syntactic boundaries:

| Client | Loop syntax | Iterations |
|---|---|---|
| prysm | `for i := range params.BeaconConfig().MinSeedLookahead + 1` | 0..=1 |
| lighthouse | `for i in 0..(spec.min_seed_lookahead.safe_add(1)?.as_u64())` | 0..=1 (exclusive upper) |
| teku | `IntStream.rangeClosed(0, specConfigFulu.getMinSeedLookahead())` | 0..=1 (inclusive upper) |
| nimbus | `for i in 0 ..< (MIN_SEED_LOOKAHEAD + 1)` | 0..=1 (exclusive upper) |
| lodestar | `for (let i = 0; i <= MIN_SEED_LOOKAHEAD; i++)` | 0..=1 (inclusive upper) |
| grandine | `for i in 0..=P::MinSeedLookahead::U64` | 0..=1 (inclusive upper) |

**All produce identical 2-iteration output.** Off-by-one risk is purely cosmetic — the spec's `range(MIN_SEED_LOOKAHEAD + 1)` is unambiguous.

### Lodestar `processProposerLookahead` saves shuffling to cache (single-pass optimization)

Lodestar's `processProposerLookahead.ts:25-27`:

```typescript
const shuffling = computeEpochShuffling(state, cache.nextShufflingActiveIndices, epoch);
// Save shuffling to cache so afterProcessEpoch can reuse it instead of recomputing
cache.nextShuffling = shuffling;
```

Other 5 clients recompute on next `process_epoch` invocation. **Lodestar-unique optimization** that integrates with its single-pass epoch architecture; observable-equivalent.

## EF fixture status

**Dedicated EF fixtures exist**:
- `consensus-spec-tests/tests/mainnet/fulu/epoch_processing/proposer_lookahead/pyspec_tests/`:
  - `proposer_lookahead_does_not_contain_exited_validators`
  - `proposer_lookahead_in_state_matches_computed_lookahead`
- `consensus-spec-tests/tests/mainnet/fulu/fork/fork/pyspec_tests/` (Fulu state-upgrade fixtures including `initialize_proposer_lookahead`):
  - `after_fork_deactivate_validators_from_electra_to_fulu`
  - `after_fork_deactivate_validators_wo_block_from_electra_to_fulu`
  - `after_fork_new_validator_active_from_electra_to_fulu`
  - `fork_base_state`, `fork_many_next_epoch`, `fork_next_epoch`, `fork_next_epoch_with_block`
  - `fork_random_low_balances`, `fork_random_misc_balances`
  - `fulu_fork_random_0` …

**Wiring status**: BeaconBreaker harness's `parse_fixture` in `tools/runners/_lib.sh` does NOT yet recognize Fulu's `proposer_lookahead` epoch_processing helper or the `fork` category for Fulu. This is the first item that requires Fulu-fixture wiring (analogous to item #11's "fork category not wired" status). Source review confirms all 6 clients' internal CI passes these fixtures; **fixture run pending harness wiring**.

## Cross-cut chain

This audit closes the Fulu-NEW state-transition entry point and cross-cuts:
- **Item #11** (`upgrade_to_electra`) — paralleled by `upgrade_to_fulu` which calls `initialize_proposer_lookahead` (lighthouse `upgrade/fulu.rs:43`, grandine `fork.rs:683`, teku `FuluStateUpgrade.java:89`, lodestar `slot/upgradeStateToFulu.ts:23`, etc.). **Item #11 is now Pectra-historical** per the WORKLOG re-scope; this item is the Fulu equivalent.
- **Item #27** (`get_next_sync_committee_indices`) — uses similar `compute_proposer_index` primitive in pre-Gloas; sync committee uses `compute_balance_weighted_selection` post-Gloas. Proposer-index computation gets the SAME Gloas-modification: `compute_proposer_indices` switches to `compute_balance_weighted_selection`. **Pattern M for item #28 catalogue (see below).**
- **Item #28** Gloas tracking — adds **new Pattern M**: `compute_proposer_indices` post-Gloas uses `compute_balance_weighted_selection` (lighthouse `:1131`, nimbus `validator.nim:580`, grandine `misc.rs:881`); prysm/teku/lodestar do NOT have Gloas branches today. **Same 3 leaders / 3 laggards split as Pattern F (sync committee selection).** Vector at Gloas: A-tier divergence — different proposer indices = different proposer signatures = different blocks.

## Adjacent untouched Fulu-active

- `initialize_proposer_lookahead` at exactly `FULU_FORK_EPOCH` boundary — verify all 6 clients use the same pre-Fulu seed for this initialization (the lookahead uses `compute_proposer_index`, NOT yet `state.proposer_lookahead` which doesn't exist pre-Fulu)
- Cross-fork transition stateful fixture: Pectra→Fulu with non-trivial `pending_deposits` / churn budget; verify all 6 produce identical lookahead at upgrade slot
- `process_proposer_lookahead` ordering within `process_epoch` — last step after `process_sync_committee_updates`; verify exact placement (no off-by-one with sync committee mutation)
- Empty-validator-set edge case: nimbus's `Opt.none` retention vs other 5 clients' behavior
- Lighthouse `ComputeProposerIndicesInsufficientLookahead` / `ComputeProposerIndicesExcessiveLookahead` error consistency: do prysm/teku/nimbus/lodestar/grandine reject the same edge cases at the API layer?
- Lodestar `this.proposers` cache invalidation: verify no code path mutates `state.proposerLookahead` mid-epoch (any setter writeable from outside `processProposerLookahead`?)
- Pre-Fulu fallback consistency at exactly `FULU_FORK_EPOCH`: prysm checks BOTH state version AND epoch; verify no off-by-one
- Performance benchmark: in-place vs allocation-per-epoch (lighthouse/grandine Vec→PersistentVector conversion overhead, teku ArrayList allocation)
- Teku `canCalculateProposerIndexAtSlot` 2-epoch window matches the Fulu lookahead size — extends to next epoch only
- Validator-client proposer-duty API: how each CL reports lookahead via `/eth/v1/validator/duties/proposer/{epoch}` (out of state-transition scope but cross-cuts)
- The `temporary workaround for Gloas` `debugGloasComment` in nimbus `validator.nim:580` — track what the workaround is and whether it should be cleaned up
- `PROPOSER_REWARD_QUOTIENT` denominator: not affected by EIP-7917 but should sanity-check at Fulu (cross-cut to item #8/#9 slashing reward calculation)

## Future research items

1. **Wire Fulu fixture categories** in BeaconBreaker harness: `proposer_lookahead` epoch_processing + `fork` (already cited as adjacent untouched in item #11). Required before this item can transition from `pending-fixture-run` to `pending-fuzzing`.
2. **Cross-fork transition stateful fixture: Pectra→Fulu** with non-trivial state — verify all 6 produce identical 64-element `proposer_lookahead` at upgrade slot. Highest-value test for migration correctness.
3. **Empty-validator-set edge case test** — nimbus's `Opt.none` retention vs other 5; construct fixture with all validators exited at epoch boundary.
4. **Lighthouse `InsufficientLookahead` error consistency** — verify prysm/teku/nimbus/lodestar/grandine reject the same edge cases (epoch < current + 1 post-Fulu).
5. **Lodestar `this.proposers` cache invalidation audit** — find any code path that mutates `state.proposerLookahead` mid-epoch; if any, lodestar diverges.
6. **Pre-Fulu fallback consistency at FULU_FORK_EPOCH** — fixture with state version exactly Electra but slot exactly at FULU_FORK_EPOCH; verify all 6 either fall through to Fulu path or all fall through to pre-Fulu path (no per-client divergence at exact boundary).
7. **Item #28 ADDENDUM — Pattern M (`compute_proposer_indices` post-Gloas)**: add to the Gloas-divergence catalogue. Same 3-leader / 3-laggard split as Pattern F (sync committee). At Gloas: lighthouse + nimbus + grandine have `compute_balance_weighted_selection` branches; prysm + teku + lodestar do not. **A-tier vector — different proposer indices = different blocks.**
8. **Generate dedicated EF fixture for `initialize_proposer_lookahead`** as a pure function (state, epoch → 64-element vector); currently only exercised through `fork` category fixtures.
9. **Performance benchmark suite** — measure per-epoch cost of `process_proposer_lookahead` across 6 clients; teku ArrayList allocation may be hot path.
10. **`debugGloasComment "temporary workaround for Gloas"`** in nimbus — investigate what the workaround is and whether it should be removed before Gloas activates.
11. **Forward-fragility audit of nimbus Optional retention** — every Fulu-NEW function that uses `seq[Opt[T]]` retains stale state on `Opt.none`; catalog all such call sites.
12. **Lodestar `nextShuffling` cache reuse audit** — verify the single-pass optimization (`cache.nextShuffling = shuffling`) doesn't introduce stale-cache divergence on subsequent epochs.
13. **Two-overload `get_beacon_proposer_indices` in nimbus** — verify no Fulu-state caller invokes the shuffled-indices overload (line 588) directly.
14. **Cross-fork transition fixture spanning Pectra→Fulu→(synthetic Gloas)** — verify Pattern M + lookahead initialization at both boundaries.
15. **Validator-client proposer-duty API consistency** — `/eth/v1/validator/duties/proposer/{epoch}` should return the lookahead-derived indices on Fulu+; verify all 6 clients match.

## Summary

EIP-7917 deterministic proposer lookahead is implemented byte-for-byte equivalently across all 6 clients at the algorithm level. The 64-element `proposer_lookahead` vector is initialized at `upgrade_to_fulu`, mutated only by `process_proposer_lookahead` at the end of `process_epoch`, and consumed via direct array index lookup at every slot.

Per-client divergences are entirely in:
- **Error-guard semantics** (lighthouse alone has explicit `InsufficientLookahead`/`ExcessiveLookahead` errors)
- **Cache architecture** (lodestar caches `proposers` separately; risk of stale-cache divergence if spec adds mid-epoch mutation)
- **Allocation pattern** (in-place vs Vec/ArrayList copy — performance, not correctness)
- **Pre-Fulu fallback** (prysm double-checks state version AND epoch; others check one or the other)
- **Optional wrapping** (nimbus retains stale lookahead on `Opt.none`; forward-fragile)

**New Pattern M for item #28**: `compute_proposer_indices` post-Gloas switches to `compute_balance_weighted_selection`. Same 3-leader / 3-laggard split as Pattern F (sync committee selection): lighthouse + nimbus + grandine have Gloas branches; prysm + teku + lodestar do not. **A-tier divergence vector at Gloas activation.**

**Status**: source-review confirms all 6 clients aligned at Fulu mainnet. **Fixture run pending Fulu fixture-category wiring in BeaconBreaker harness** (the `proposer_lookahead` epoch_processing and `fork` categories).
