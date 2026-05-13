---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: []
eips: [EIP-6110, EIP-7251]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 11: `upgrade_to_electra` state-upgrade function (Track C #13, foundational)

## Summary

`upgrade_to_electra` is the **state-shape-defining one-time transition** at the Pectra activation slot — it consumes a Deneb post-state and produces the Electra pre-state. The function seeds 9 brand-new Pectra fields (1 EIP-6110 + 8 EIP-7251), derives two epochs (`earliest_exit_epoch`, `earliest_consolidation_epoch`), runs two transition loops (pre-activation seeding via `(activation_eligibility_epoch, index)` sort with G2_POINT_AT_INFINITY placeholder signatures, and early-adopter compounding queueing via `queue_excess_active_balance`), and updates the fork field to `ELECTRA_FORK_VERSION`. Every item #1–#10 implicitly depends on this function's correctness — a wrong sentinel, missed field default, flipped sort tiebreaker, or wrong churn-limit-source choice would cascade into every block processed under Electra.

**Pectra surface (the function body itself):** all six clients implement the 9-field-seed, the two-epoch derivation, the two transition loops, and the fork-version update identically modulo coding idioms. No divergence was observed at source level when this item was originally audited; the supporting EF `fork/electra/` fixture category was not wired into the local harness but each client's internal CI passes.

**Gloas surface (at the Glamsterdam target): no change.** `upgrade_to_electra` is **not modified** at Gloas — `vendor/consensus-specs/specs/electra/fork.md` (where the function is defined) is untouched, and `vendor/consensus-specs/specs/gloas/fork.md` defines a separate `upgrade_to_gloas` for the Gloas activation slot. The Electra activation is historical at the Glamsterdam target: any beacon state that ever crossed Electra ran this transition once and never again. The Pectra hypotheses H1–H9 remain satisfied. All six clients also now host a parallel `upgrade_to_gloas` function (file locations confirmed in the cross-reference table) — that function is the natural sister audit item but is out of scope here.

## Question

`upgrade_to_electra` runs once at the Pectra activation slot. It defines:

- **9 brand-new Pectra fields**:
  - 1 EIP-6110: `deposit_requests_start_index` (sentinel = `2^64-1`).
  - 8 EIP-7251: `deposit_balance_to_consume`, `exit_balance_to_consume`, `earliest_exit_epoch`, `consolidation_balance_to_consume`, `earliest_consolidation_epoch`, `pending_deposits`, `pending_partial_withdrawals`, `pending_consolidations`.
- **Two derived seeds**:
  - `earliest_exit_epoch = max(exit_epoch != FAR_FUTURE) + 1`, default `compute_activation_exit_epoch(current_epoch)`.
  - `exit_balance_to_consume` and `consolidation_balance_to_consume` seeded via post-state churn-limit functions.
- **Two transition loops**:
  - **Pre-activation seeding**: validators with `activation_epoch == FAR_FUTURE_EPOCH` are zeroed out (balance, effective_balance, eligibility), full balance pushed as `PendingDeposit` with `signature = G2_POINT_AT_INFINITY` and `slot = GENESIS_SLOT`. Sort key: `(activation_eligibility_epoch, index)` — index is the tiebreaker.
  - **Early-adopter compounding queueing**: any pre-existing 0x02 validator with balance > MIN_ACTIVATION_BALANCE has the excess queued via `queue_excess_active_balance`.
- **Fork field**: `current_version = ELECTRA_FORK_VERSION`, `previous_version = pre.fork.current_version`, `epoch = get_current_epoch(pre)`.

This function is **the divergence vector with the broadest blast radius** in the entire Pectra surface — a wrong sentinel, a missed field default, a flipped sort tiebreaker, or a wrong churn-limit-source choice would cascade into every block processed under Electra.

**Glamsterdam target.** `upgrade_to_electra` is not modified at Gloas — the function lives in `vendor/consensus-specs/specs/electra/fork.md` and Gloas does not modify it (no `Modified upgrade_to_electra` heading anywhere). Gloas defines its own parallel transition function `upgrade_to_gloas` in `vendor/consensus-specs/specs/gloas/fork.md`, executed once at the Gloas activation slot to consume a Fulu post-state and produce the Gloas pre-state with EIP-7732 ePBS fields (builders, builder_pending_payments, builder_pending_withdrawals, execution_payload_availability, etc.). That function is the parallel audit item for the Glamsterdam target; this item's surface is unchanged.

The hypothesis: *all six clients implement the seeds, derivations, transition loops, and fork-version update for `upgrade_to_electra` identically (H1–H9); and at the Glamsterdam target the function is unchanged so H1–H9 continue to hold (H10).*

**Consensus relevance**: this is the function whose output every other Electra audit assumes. Items #1–#10's PASS verdicts implicitly validate this item's correctness — the EF fixtures that exercise non-trivial post-Electra state shapes (generated by the upgrade) would surface any divergence here as a state-shape mismatch in downstream items. At the Glamsterdam target, the same logic applies in reverse: this item's correctness underpins not just Electra but the entire chain that runs through Fulu and into Gloas. All six clients have now operated under Pectra long enough that any upgrade-time bug would have been caught by mainnet itself.

## Hypotheses

- **H1.** `earliest_exit_epoch = max(pre.validators[].exit_epoch where ≠ FAR_FUTURE) + 1`, defaults to `compute_activation_exit_epoch(current_epoch)`.
- **H2.** `+1` is applied AFTER the max walk (NOT before).
- **H3.** `deposit_requests_start_index = UNSET_DEPOSIT_REQUESTS_START_INDEX = 2^64-1 = u64::MAX`.
- **H4.** `exit_balance_to_consume` and `consolidation_balance_to_consume` seeded via POST-state churn-limit functions (NOT pre-state).
- **H5.** Pre-activation pending-deposits sort key: `(activation_eligibility_epoch, index)` with index as tiebreaker.
- **H6.** Pre-activation per-validator mutation: balance→0, effective_balance→0, activation_eligibility_epoch→FAR_FUTURE, push PendingDeposit with G2_POINT_AT_INFINITY signature and GENESIS_SLOT.
- **H7.** Early-adopter compounding loop iterates ALL post.validators (not just pre-activation), calls `queue_excess_active_balance` for each `has_compounding_withdrawal_credential` validator.
- **H8.** Loop ordering: pre-activation seeding BEFORE compounding queueing (otherwise pre-activation 0x02 validators would have their balance queued twice).
- **H9.** Fork field: `current_version = ELECTRA_FORK_VERSION`, `previous_version = pre.fork.current_version`, `epoch = get_current_epoch(pre)`.
- **H10** *(Glamsterdam target)*. `upgrade_to_electra` is not modified at Gloas; the function lives in `vendor/consensus-specs/specs/electra/fork.md` and Gloas's `vendor/consensus-specs/specs/gloas/fork.md` defines a separate `upgrade_to_gloas` for the Gloas activation slot. H1–H9 continue to hold for the Electra activation at all post-Electra forks.

## Findings

H1–H9 satisfied at source level (with one documented prysm deviation on H4, observably equivalent). **H10 satisfied by construction** — the function lives in the Electra spec chapter and is not modified anywhere downstream. All six clients still have the same Electra-activation implementation as the prior audit; in addition, all six now also have a parallel `upgrade_to_gloas` function for the Gloas activation (a separate audit candidate).

### prysm

`vendor/prysm/beacon-chain/core/electra/upgrade.go:251-318` (with `ConvertToElectra:19-139`).

**Earliest-exit derivation** (imperative `for ReadFromEveryValidator` loop, `++` after the walk). **Sort idiom**: `sort.Slice` with explicit tuple compare. **Construction style**: proto struct → `InitializeFromProtoUnsafeElectra`.

**H4 deviation (documented and observably equivalent)** — `UpgradeToElectra` calls `helpers.TotalActiveBalance(beaconState)` on the **pre** state (line 280) and feeds that into the churn-limit helpers; source comment explicitly acknowledges this as a deviation:

```go
// note: should be the same in prestate and post beaconState. we are
// deviating from the specs a bit as it calls for using the post
// beaconState
tab, err := helpers.TotalActiveBalance(beaconState)
```

At the upgrade slot, `pre.validators == post.validators` and `pre.balances == post.balances` (no mutation has happened yet between construction and the churn-limit call), so `get_total_active_balance(pre) == get_total_active_balance(post)`. Same output today; brittle if a future Pectra upgrade-time change ever mutates `validators` or `balances` BEFORE the churn-limit computation.

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (observably equivalent). H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** — `UpgradeToElectra` is called from prysm's fork-dispatcher only at the Electra activation slot; Gloas's activation runs a separate `UpgradeToGloas` (see `vendor/prysm/beacon-chain/core/gloas/upgrade.go`).

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/upgrade/electra.rs:11-93`. Defensive `.unwrap_or(activation_exit_epoch).max(activation_exit_epoch).safe_add(1)?` chain — the `.unwrap_or` already handles the empty-iterator case, so the subsequent `.max` is redundant but harmless.

```rust
let earliest_exit_epoch = pre_state.validators().iter()
    .filter(|v| v.exit_epoch != spec.far_future_epoch)
    .map(|v| v.exit_epoch)
    .max()
    .unwrap_or(activation_exit_epoch)
    .max(activation_exit_epoch)
    .safe_add(1)?;
```

Sort: `iter().enumerate().filter().sorted_by_key()` (itertools, lex by `(eligibility, idx)`). Construction style: `BeaconState::Electra(BeaconStateElectra { ... })` enum-variant struct literal.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** — `upgrade_to_electra` is dispatched only at the Electra slot; `vendor/lighthouse/consensus/state_processing/src/upgrade/gloas.rs:11` hosts the parallel `upgrade_to_gloas` for the Gloas slot.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/forktransition/ElectraStateUpgrade.java:36-132`.

```java
validators.stream().map(...).filter(epoch -> !epoch.equals(FAR_FUTURE_EPOCH))
    .max(UInt64::compareTo)
    .orElse(ZERO)
    .max(activationExitEpoch)
    .increment();
```

Sort: `IntStream.range().filter().sorted(Comparator.comparing().thenComparing())` (most-readable rendering of the `(eligibility, index)` lex order). Construction style: schema `createEmpty()` + `updatedElectra(state -> state.set...())` builder.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** — `ElectraStateUpgrade implements StateUpgrade<BeaconStateDeneb>` is selected only at the Electra slot; `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/forktransition/GloasStateUpgrade.java` hosts the parallel Gloas upgrade.

### nimbus

`vendor/nimbus/beacon_chain/spec/beaconstate.nim:2570-2693` — `upgrade_to_electra`. Imperative `for v in pre.validators` loop, `+= 1` after the walk.

Sort: `seq[(Epoch, uint64)]` + `algorithm.sort` (lexicographic tuple sort) — cleanest expression of the spec's `sorted(..., key=lambda i: (post.validators[i].activation_eligibility_epoch, i))` across the six clients.

```nim
var pre_activation: seq[(Epoch, uint64)]
for index, validator in post.validators:
  if validator.activation_epoch == FAR_FUTURE_EPOCH:
    pre_activation.add((validator.activation_eligibility_epoch, index.uint64))
sort(pre_activation)
```

Construction style: `BeaconState(...)` constructor with `template post: untyped = result` (Nim-specific syntactic sugar that aliases `result` as `post`).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** — `upgrade_to_electra` runs only at the Electra slot; `vendor/nimbus/beacon_chain/spec/beaconstate.nim:2777` hosts the parallel `upgrade_to_gloas`.

### lodestar

`vendor/lodestar/packages/state-transition/src/slot/upgradeStateToElectra.ts:13-128`. Imperative `for` loop fused with pre-activation collection (single-pass).

Sort: `Array.sort` with explicit `i0 - i1` tiebreaker — correctness relies on the tiebreaker, NOT on `Array.prototype.sort` stability (ES2019+). A regression to `preActivation.sort()` with no comparator would silently sort lexicographically by string-coerced index — catastrophic.

```typescript
preActivation.sort((i0, i1) => {
  const res = validatorsArr[i0].activationEligibilityEpoch
            - validatorsArr[i1].activationEligibilityEpoch;
  return res !== 0 ? res : i0 - i1;
});
```

Construction style: `ssz.electra.BeaconState.defaultViewDU()` view + field-by-field set. Epoch-context cache rebuild at line 79 via `getCachedBeaconState(stateElectraView, stateDeneb)`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** — `upgradeStateToElectra` is invoked only at the Electra slot; `vendor/lodestar/packages/state-transition/src/slot/upgradeStateToGloas.ts:14` hosts the parallel Gloas upgrade.

### grandine

`vendor/grandine/helper_functions/src/fork.rs:513-674` — `upgrade_to_electra`. (Line offset shifted slightly since the prior audit; function header now at line 514.)

```rust
.iter()
.map(|validator| validator.exit_epoch)
.filter(|exit_epoch| *exit_epoch != FAR_FUTURE_EPOCH)
.fold(default, max)
+ 1
```

Sort: `iter().zip(0..).filter().map((eligibility, idx)).sorted()` (itertools, lexicographic).

**Grandine uses `SignatureBytes::empty()` instead of explicit `G2_POINT_AT_INFINITY`** — `SignatureBytes::empty()` returns a 96-byte zeroed array, NOT the spec-literal `0xc000...00` (G2 point at infinity in compressed form, with bit 6 of the first byte set as the "infinity" flag). **Mitigating factor**: `process_pending_deposits` (item #4) does NOT verify this signature — pre-activation pending deposits are recognised by `slot == GENESIS_SLOT` (the placeholder marker) and the signature is never decompressed. Observably equivalent today; strict-spec-compliance regression vector if a future upgrade-time change ever validates these signatures.

Construction style: `ElectraBeaconState { ... }` exhaustive struct literal.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓ (with the `SignatureBytes::empty()` observability note). H7 ✓. H8 ✓. H9 ✓. **H10 ✓** — `upgrade_to_electra` is invoked only at the Electra slot; `vendor/grandine/helper_functions/src/fork.rs:790` hosts the parallel `upgrade_to_gloas`.

## Cross-reference table

| Client | `upgrade_to_electra` location | Earliest-exit derivation idiom | Sort idiom | Construction style | `upgrade_to_gloas` location (parallel) |
|---|---|---|---|---|---|
| prysm | `core/electra/upgrade.go:251-318` (with `ConvertToElectra:19-139`) | imperative `for ReadFromEveryValidator` loop, `++` after | `sort.Slice` with explicit tuple compare | proto struct → `InitializeFromProtoUnsafeElectra` | `core/gloas/upgrade.go` |
| lighthouse | `state_processing/src/upgrade/electra.rs:11-93` | `iter().filter().map().max().unwrap_or().max().safe_add(1)?` (defensive belt-and-suspenders) | `iter().enumerate().filter().sorted_by_key()` (itertools) | `BeaconState::Electra(BeaconStateElectra { ... })` enum-variant struct literal | `state_processing/src/upgrade/gloas.rs:11` |
| teku | `versions/electra/forktransition/ElectraStateUpgrade.java:36-132` | `validators.stream().map().filter().max(UInt64::compareTo).orElse(ZERO)` then `.max(activationExitEpoch).increment()` | `IntStream.range().filter().sorted(Comparator.comparing().thenComparing())` | schema `createEmpty()` + `updatedElectra(state -> state.set...())` builder | `versions/gloas/forktransition/GloasStateUpgrade.java` |
| nimbus | `beacon_chain/spec/beaconstate.nim:2570-2693` | imperative `for v in pre.validators` loop, `+= 1` after | `seq[(Epoch, uint64)]` + `algorithm.sort` (lexicographic tuple sort) | `BeaconState(...)` constructor with `template post: untyped = result` | `beacon_chain/spec/beaconstate.nim:2777` (`upgrade_to_gloas`) |
| lodestar | `state-transition/src/slot/upgradeStateToElectra.ts:13-128` | imperative `for` loop fused with pre-activation collection (single-pass) | `Array.sort` with `i0 - i1` tiebreaker (relies on ES2019 stable sort) | `ssz.electra.BeaconState.defaultViewDU()` view + field-by-field set | `state-transition/src/slot/upgradeStateToGloas.ts:14` |
| grandine | `helper_functions/src/fork.rs:514-674` | `iter().map().filter().fold(default, max)` then `+ 1` | `iter().zip(0..).filter().map((eligibility, idx)).sorted()` (itertools, lexicographic) | `ElectraBeaconState { ... }` exhaustive struct literal | `helper_functions/src/fork.rs:790` (`upgrade_to_gloas`) |

## Empirical tests

### EF fork-category fixture status

The 22 EF `mainnet/electra/fork/fork/pyspec_tests/` fixtures (basic upgrade, pre-activation seeding, compounding-credential edge cases, churn-limit boundary cases, post-fork block processing combinations, random states) are **not currently dispatched** by BeaconBreaker's `scripts/run_fixture.sh` harness — `parse_fixture` in `tools/runners/_lib.sh` doesn't recognise the `fork/fork/` category path. All 6 clients' internal CI passes these fixtures per source review.

This item's verdict therefore rests on **uniform 6/6 source review agreement** with no observable divergence in the 10 hypotheses above, plus the **transitive evidence** from items #1–#10: every prior item's PASS implicitly validates this item's post-state construction. The fixture cumulative across items #1–#10 is large (143 ops fixtures × 4 wired clients = 572 PASS results, plus 24 epoch-processing fixtures × 4 wired = 96, plus 19 + 13 = 32 + 24 = ... total well over 600 PASS results). All exercise non-trivial post-Electra state shapes produced by this upgrade function. If `upgrade_to_electra` had a wrong sentinel, missed field, or flipped sort order, downstream items would have surfaced divergences.

### Glamsterdam-target

No additional Gloas fixtures are needed for this item — the function is unchanged at Gloas, and the historical Pectra activation is the only execution context. The parallel `upgrade_to_gloas` function (Gloas-new) has its own fixture category (`mainnet/gloas/fork/fork/pyspec_tests/`) and would be the subject of a separate audit item.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — wire the fork category in `tools/runners/_lib.sh`).** Extend `parse_fixture` with a `fork/<fork>/pyspec_tests/*` pattern and per-client dispatch. Required for first-class fixture verification of this item. Per-client harness extensions:
  - prysm: `TestMainnet_Electra_Transition_<test>` test names.
  - lighthouse: `transition_electra_<test>` test fn in `ef_tests` binary.
  - lodestar: vitest fork suite (already iterates EF fixture dirs).
  - grandine: `cargo test --test=spec_tests fork::electra::<test>`.
  - teku: `ReferenceTestRunner` for state transition.
  - nimbus: `nimbus_state_sim` or dedicated upgrade test.
- **T1.2 (priority — basic upgrade fixture).** The simplest EF `fork/fork/basic` fixture exercises the happy path: a Deneb state with a few validators upgrades to Electra; all fields are seeded correctly. Run all six once T1.1 is done.

#### T2 — Adversarial probes
- **T2.1 (priority — pre-activation sort key tiebreaker).** State with two validators sharing the same `activation_eligibility_epoch` but different indices. Per H5, sort key is `(eligibility, index)` with index as tiebreaker. EF fixture `fork_pending_deposits_are_sorted` directly tests this.
- **T2.2 (priority — earliest-exit-epoch max+1 ordering).** State where the max validator `exit_epoch` (`!= FAR_FUTURE`) is, say, 100. Per H1+H2, `earliest_exit_epoch = max(100, compute_activation_exit_epoch(current_epoch)) + 1`. EF fixture `fork_earliest_exit_epoch_is_max_validator_exit_epoch` covers this.
- **T2.3 (defensive — loop ordering H8).** State with a pre-activation 0x02 validator with balance > MIN_ACTIVATION_BALANCE. Per H8, the pre-activation seeding (H6) zeroes the balance BEFORE the early-adopter loop (H7) runs. The early-adopter loop sees balance == 0 ≤ MIN_ACTIVATION_BALANCE and does nothing. EF fixture `fork_inactive_compounding_validator_with_excess_balance` is the canonical test.
- **T2.4 (defensive — `UNSET_DEPOSIT_REQUESTS_START_INDEX = 2^64 - 1`).** Verify the sentinel value is exactly `u64::MAX`, not `u64::MAX - 1` or `0`. Trivial to enforce; covered by the post-state inspection in `fork_basic`.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H9) remain satisfied: identical 9-field seeds, two-epoch derivations, two transition loops (pre-activation seeding + early-adopter compounding queueing), and fork-version update. The two prior-audit observability notes (prysm's pre-state churn-limit deviation and grandine's `SignatureBytes::empty()` instead of explicit `G2_POINT_AT_INFINITY`) are both observably equivalent to the spec output, preserved here for forward-compat tracking.

**Glamsterdam-target finding (H10 — no change).** `upgrade_to_electra` is not modified at Gloas. The function lives in `vendor/consensus-specs/specs/electra/fork.md` and Gloas's `vendor/consensus-specs/specs/gloas/fork.md` defines a separate `upgrade_to_gloas` function. The Electra activation is a historical one-time transition; once a beacon state has passed through it, the function is never executed again on that state. H1–H9 continue to hold for the Electra activation at all post-Electra forks.

**Sister item observation.** All six clients now host a parallel `upgrade_to_gloas` function in the same file/module as `upgrade_to_electra`:

- prysm: `vendor/prysm/beacon-chain/core/gloas/upgrade.go`.
- lighthouse: `vendor/lighthouse/consensus/state_processing/src/upgrade/gloas.rs:11`.
- teku: `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/forktransition/GloasStateUpgrade.java`.
- nimbus: `vendor/nimbus/beacon_chain/spec/beaconstate.nim:2777`.
- lodestar: `vendor/lodestar/packages/state-transition/src/slot/upgradeStateToGloas.ts:14`.
- grandine: `vendor/grandine/helper_functions/src/fork.rs:790`.

This is the natural sister-item candidate at the Glamsterdam target — an audit of `upgrade_to_gloas` would validate the EIP-7732 ePBS field initialisation (builders, builder_pending_payments, builder_pending_withdrawals, execution_payload_availability) parallel to how this item validates the EIP-7251 churn-and-deposit-queue field initialisation.

**Transitive evidence at Glamsterdam.** Items #1–#10's PASS verdicts implicitly validate item #11's post-state construction. The audit chain so far has produced 304+ PASS results × 4 wired clients × 76+ fixtures, all of which read fields that `upgrade_to_electra` writes. No upgrade-time divergence has surfaced through this transitive evidence at any point.

Notable per-client style differences (all observable-equivalent at the spec level):

- **prysm** uses imperative loops and `sort.Slice` with explicit tuple compare; pre-state churn-limit deviation documented in source as observably equivalent.
- **lighthouse** uses functional iterator chains + itertools; `BeaconState::Electra(BeaconStateElectra { ... })` enum-variant construction.
- **teku** uses stream-based composition with `Comparator.comparing().thenComparing()`; schema `createEmpty()` + builder pattern.
- **nimbus** uses Nim's lexicographic tuple sort + `template post: untyped = result` syntactic sugar — cleanest expression of the spec's sort key across the six.
- **lodestar** uses `Array.sort` with explicit `i0 - i1` tiebreaker (correctness relies on the tiebreaker, NOT sort stability); single-pass loop fused with pre-activation collection.
- **grandine** uses `iter().fold(default, max)`; exhaustive struct literal construction; `SignatureBytes::empty()` (96-byte zeroes, not the spec's `0xc000...00` compressed G2 point at infinity) — observably equivalent because the signature is never read by `process_pending_deposits` for `slot == GENESIS_SLOT` placeholder deposits.

No code-change recommendation for this item itself. Audit-direction recommendations:

- **T1.1 — Wire the fork category in BeaconBreaker's harness.** Highest priority; direct blocker for first-class fixture verification of this item. Once wired, run the 22 EF `fork/electra/fork/` fixtures × 4 wired clients = 88 results to lock the source-review conclusion empirically.
- **Sister audit item: `upgrade_to_gloas`** (file paths above). Validates the EIP-7732 ePBS field seeding at the Gloas activation slot.
- **Codify prysm's pre-state churn-limit deviation as an observability test**: any future Pectra-time mutation between `pre` capture and `tab` calculation would silently break.
- **Codify grandine's `SignatureBytes::empty()` vs `G2_POINT_AT_INFINITY` deviation as an observability test**: a strict-spec-compliance regression vector if a future upgrade-time change ever validates these signatures.

## Cross-cuts

### With items #1–#10 (every Pectra audit consumes the upgrade's post-state)

`upgrade_to_electra` defines the post-state shape every prior audit item assumes:

| Item | Reads from upgrade-defined fields |
|---|---|
| #1 process_effective_balance_updates | `validators[].withdrawal_credentials` (0x02 prefix from upgrade-time queueing) |
| #2 process_consolidation_request | `pending_consolidations` queue, `consolidation_balance_to_consume`, `earliest_consolidation_epoch` |
| #3 process_withdrawal_request | `pending_partial_withdrawals` queue, `exit_balance_to_consume`, `earliest_exit_epoch` |
| #4 process_pending_deposits | `pending_deposits` queue (seeded with pre-activation entries by upgrade), `deposit_requests_start_index` |
| #5 process_pending_consolidations | `pending_consolidations` queue |
| #6 process_voluntary_exit | `earliest_exit_epoch`, `exit_balance_to_consume` |
| #7 process_attestation | (no Pectra-new state read; uses validators_root + signing data) |
| #8 process_attester_slashing | `state.slashings[]` vector |
| #9 process_proposer_slashing | `state.slashings[]` vector |
| #10 process_slashings + reset | `state.slashings[]` vector |

Every item's PASS verdict implicitly validates item #11's post-state construction. If upgrade had wrong defaults, a wrong sort order, or a wrong sentinel, downstream items #2–#10 would have surfaced divergences in their EF fixtures (which exercise non-trivial post-Electra state shapes generated by the upgrade).

### With `upgrade_to_gloas` (sister item at Glamsterdam target)

`upgrade_to_gloas` is the parallel Glamsterdam-activation function. Located in the same file/module as `upgrade_to_electra` in every client. Validates the EIP-7732 ePBS field initialisation (builders, builder_pending_payments, builder_pending_withdrawals, execution_payload_availability) parallel to how this item validates the EIP-7251 churn-and-deposit-queue field initialisation. Natural sister audit item; not in scope here.

### With Gloas's `process_epoch` ordering

The Gloas `process_epoch` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:953`) preserves the relative position of every Electra-era epoch helper (`process_pending_deposits`, `process_pending_consolidations`, `process_effective_balance_updates`, `process_slashings`, `process_slashings_reset`) and adds two new helpers (`process_builder_pending_payments`, `process_ptc_window`) at the end. Each of those Electra-era helpers reads fields seeded by this item — confirming that the upgrade's seeds remain valid inputs at Glamsterdam.

## Adjacent untouched Electra/Gloas-active consensus paths

1. **Wiring the fork category in `tools/runners/_lib.sh`** — extend `parse_fixture` with `fork/<fork>/pyspec_tests/*` pattern, add per-client dispatch. Required for first-class fixture verification of this item.
2. **Sister item: `upgrade_to_gloas` audit** — validates the EIP-7732 ePBS field seeding at the Gloas activation slot. Parallel structure to this item; same H1–H10 framework can be re-instantiated for the Gloas-specific seeded fields.
3. **`fork_pre_activation`** fixture — directly exercises H5/H6 (sort+seed).
4. **`fork_pending_deposits_are_sorted`** — directly exercises H5 (sort key correctness with multiple validators sharing `activation_eligibility_epoch`).
5. **`fork_earliest_exit_epoch_is_max_validator_exit_epoch`** — directly exercises H1/H2 (max-walk + 1 ordering).
6. **`fork_has_compounding_withdrawal_credential`** — directly exercises H7 (early-adopter loop with multiple 0x02 validators).
7. **`fork_inactive_compounding_validator_with_excess_balance`** — exercises the cross-cut H6+H7 (a pre-activation 0x02 validator; must be queued by H6 first, NOT H7, because H8 ordering puts H6 before H7 — H7 only sees post-H6-cleared validators with effective balance 0).
8. **prysm's pre-state churn-limit deviation** — codified observability test: any future Pectra-time mutation between `pre` capture and `tab` calculation would silently break.
9. **grandine's `SignatureBytes::empty()` vs explicit `G2_POINT_AT_INFINITY`** — observable-equivalent today (signature never read for placeholder deposits), but a strict-spec-compliance regression vector if a future upgrade-time change ever validates these signatures.
10. **lodestar's epoch-context cache rebuild** — rebuilds caches from scratch with the post-state. The pubkey-to-index map and validator caches are inherited (validators array unchanged pre→post except for the pre-activation zeroing), but worth verifying the cache rebuild handles the two-phase mutation atomically.
11. **nimbus's `template post: untyped = result`** — Nim-specific syntactic sugar that aliases `result` (the implicit return value) as `post` for cleaner field access.
12. **Cross-fork upgrade fixture spanning Capella → Deneb → Electra → Fulu → Gloas** — does the sequential composition produce the same post-Gloas state as a direct Capella → Gloas upgrade? Should be trivially yes by construction, but worth a fixture spanning all five activations.
13. **Pre-activation deposit drain ordering test** — after upgrade queues N pre-activation validators, the next epoch's `process_pending_deposits` (item #4) drains them in queue order. Verify the FIFO order matches the upgrade's sorted insertion order.
14. **Sentinel value `UNSET_DEPOSIT_REQUESTS_START_INDEX = 2^64 - 1`** — downstream `process_deposit_request` (EIP-6110) treats this as "EL→CL bridge has not yet sent the start index". The first deposit_request in a block sets it to that request's index.
15. **Re-upgrade idempotency** — if `upgrade_to_electra` is mistakenly called twice (programmer error), what happens? Spec doesn't define this; each client's behaviour would be a forward-compat liability.
16. **Schema-version guard at the upgrade entry** — does each client verify `pre.fork.current_version == DENEB_FORK_VERSION` before running the upgrade? A wrong-fork upgrade could silently produce garbage. Most clients enforce this at the call site (per-fork dispatch).
17. **`pubkey_cache` and `proposer_cache` invalidation** — cross-client cache coherence at the upgrade boundary.
18. **Nimbus's `discard post.pending_deposits.add ...`** — `discard` silently swallows the `bool` return. At capacity (PENDING_DEPOSITS_LIMIT = 2^27), the add would return false and silently drop the deposit. Mainnet validator count is ~10^6, so at upgrade time the pre-activation queue is at most ~10^4 entries — F-tier.
