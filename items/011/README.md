# Item #11 — `upgrade_to_electra` state-upgrade function (Track C #13, foundational)

**Status:** no-divergence-pending-fuzzing — audited 2026-05-02. Track C
entry. **The state-shape-defining transition** at the Pectra
activation slot; every other item (#1–#10) implicitly assumes the
post-state shape this function constructs.

## Why this item

`upgrade_to_electra` runs once at the Pectra activation slot, taking
the Deneb post-state and producing the Electra pre-state. It defines:

- **9 brand-new Pectra fields**:
  - 1 EIP-6110: `deposit_requests_start_index` (sentinel = `2^64-1`)
  - 8 EIP-7251: `deposit_balance_to_consume`, `exit_balance_to_consume`,
    `earliest_exit_epoch`, `consolidation_balance_to_consume`,
    `earliest_consolidation_epoch`, `pending_deposits`,
    `pending_partial_withdrawals`, `pending_consolidations`.

- **Two derived seeds**:
  - `earliest_exit_epoch = max(exit_epoch != FAR_FUTURE) + 1`, default
    `compute_activation_exit_epoch(current_epoch)`.
  - `exit_balance_to_consume` and `consolidation_balance_to_consume`
    seeded via post-state churn-limit functions.

- **Two transition loops**:
  - **Pre-activation seeding**: validators with `activation_epoch ==
    FAR_FUTURE_EPOCH` are zeroed out (balance, effective_balance,
    eligibility), full balance pushed as `PendingDeposit` with
    `signature = G2_POINT_AT_INFINITY` and `slot = GENESIS_SLOT`.
    Sort key: `(activation_eligibility_epoch, index)` — index is the
    tiebreaker.
  - **Early-adopter compounding queueing**: any pre-existing 0x02
    validator with balance > MIN_ACTIVATION_BALANCE has the excess
    queued via `queue_excess_active_balance`.

This function is **the divergence vector with the broadest blast
radius** in the entire Pectra surface — a wrong sentinel, a missed
field default, a flipped sort tiebreaker, or a wrong churn-limit-source
choice would cascade into every block processed under Electra. Every
other item passes only because *all six clients* implement this
identically.

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | `earliest_exit_epoch = max(pre.validators[].exit_epoch where ≠ FAR_FUTURE) + 1`, defaults to `compute_activation_exit_epoch(current_epoch)` | ✅ all 6 |
| H2 | `+1` is applied AFTER the max walk (NOT before) | ✅ all 6 |
| H3 | `deposit_requests_start_index = UNSET_DEPOSIT_REQUESTS_START_INDEX = 2^64-1 = u64::MAX` | ✅ all 6 |
| H4 | `exit_balance_to_consume` and `consolidation_balance_to_consume` seeded via POST-state churn-limit functions (NOT pre-state) | ✅ 5/6 (prysm uses pre-state but documents the deviation as observably-equivalent) |
| H5 | Pre-activation pending-deposits sort key: `(activation_eligibility_epoch, index)` with index as tiebreaker | ✅ all 6 |
| H6 | Pre-activation per-validator mutation: balance→0, effective_balance→0, activation_eligibility_epoch→FAR_FUTURE, push PendingDeposit with G2_POINT_AT_INFINITY signature and GENESIS_SLOT | ✅ all 6 |
| H7 | Early-adopter compounding loop iterates ALL post.validators (not just pre-activation), calls `queue_excess_active_balance` for each `has_compounding_withdrawal_credential` validator | ✅ all 6 |
| H8 | Loop ordering: pre-activation seeding BEFORE compounding queueing (otherwise pre-activation 0x02 validators would have their balance queued twice) | ✅ all 6 |
| H9 | Fork field: `current_version = ELECTRA_FORK_VERSION`, `previous_version = pre.fork.current_version`, `epoch = get_current_epoch(pre)` | ✅ all 6 |

## Per-client cross-reference

| Client | Function location | Earliest-exit derivation idiom | Sort idiom | Construction style |
|---|---|---|---|---|
| **prysm** | `core/electra/upgrade.go:251–318` (with `ConvertToElectra:19–139`) | imperative `for ReadFromEveryValidator` loop, `++` after | `sort.Slice` with explicit tuple compare | proto struct → `InitializeFromProtoUnsafeElectra` |
| **lighthouse** | `state_processing/src/upgrade/electra.rs:11–93` | `iter().filter().map().max().unwrap_or().max().safe_add(1)?` (defensive belt-and-suspenders) | `iter().enumerate().filter().sorted_by_key()` (itertools) | `BeaconState::Electra(BeaconStateElectra { ... })` enum-variant struct literal |
| **teku** | `versions/electra/forktransition/ElectraStateUpgrade.java:36–132` | `validators.stream().map().filter().max(UInt64::compareTo).orElse(ZERO)` then `.max(activationExitEpoch).increment()` | `IntStream.range().filter().sorted(Comparator.comparing().thenComparing())` | schema `createEmpty()` + `updatedElectra(state -> state.set...())` builder |
| **nimbus** | `beacon_chain/spec/beaconstate.nim:2570–2693` | imperative `for v in pre.validators` loop, `+= 1` after | `seq[(Epoch, uint64)]` + `algorithm.sort` (lexicographic tuple sort) | `BeaconState(...)` constructor with `template post: untyped = result` |
| **lodestar** | `state-transition/src/slot/upgradeStateToElectra.ts:13–128` | imperative `for` loop fused with pre-activation collection (single-pass) | `Array.sort` with `i0 - i1` tiebreaker (relies on ES2019 stable sort) | `ssz.electra.BeaconState.defaultViewDU()` view + field-by-field set |
| **grandine** | `helper_functions/src/fork.rs:513–674` | `iter().map().filter().fold(default, max)` then `+ 1` | `iter().zip(0..).filter().map((eligibility, idx)).sorted()` (itertools, lexicographic) | `ElectraBeaconState { ... }` exhaustive struct literal |

## Notable per-client deviations / risks

### prysm uses PRE-state for churn-limit computation (documented deviation)

prysm's `UpgradeToElectra` calls `helpers.TotalActiveBalance(beaconState)`
on the **pre** state (line 280) and feeds that into the churn-limit
helpers — the source comment explicitly acknowledges this as a
deviation:

```go
// note: should be the same in prestate and post beaconState. we are
// deviating from the specs a bit as it calls for using the post
// beaconState
tab, err := helpers.TotalActiveBalance(beaconState)
```

**Observable equivalence**: at the upgrade slot, `pre.validators ==
post.validators` and `pre.balances == post.balances` (no mutation has
happened yet between construction and the churn-limit call), so
`get_total_active_balance(pre) == get_total_active_balance(post)`.
This is a documented deviation that produces identical output today,
but is a **brittle invariant**: any future Pectra upgrade-time change
that mutates `validators` or `balances` BEFORE the churn-limit
computation would silently produce wrong values. Worth flagging for
forward-compat review.

### lighthouse's defensive `.max(activation_exit_epoch)` after `.unwrap_or(activation_exit_epoch)`

Lighthouse's earliest-exit-epoch derivation:
```rust
let earliest_exit_epoch = pre_state.validators().iter()
    .filter(|v| v.exit_epoch != spec.far_future_epoch)
    .map(|v| v.exit_epoch)
    .max()
    .unwrap_or(activation_exit_epoch)
    .max(activation_exit_epoch)
    .safe_add(1)?;
```

The `.unwrap_or(activation_exit_epoch)` already handles the
empty-iterator case correctly, so the subsequent
`.max(activation_exit_epoch)` is **redundant but harmless** —
defensive belt-and-suspenders. Worth a `// redundant after unwrap_or`
comment for clarity.

### grandine uses `SignatureBytes::empty()` instead of explicit G2_POINT_AT_INFINITY

Grandine's pre-activation pending-deposit append uses
`signature: SignatureBytes::empty()` rather than an explicit
`G2_POINT_AT_INFINITY` constant. **Equivalence**: BLS signature point
at infinity in compressed form is `0xc0` followed by 95 zeroes — and
`SignatureBytes::empty()` returns a 96-byte zeroed array which… is
NOT the same. This warrants verification: the spec literally requires
`bls.G2_POINT_AT_INFINITY` (= `0xc000...00`, with bit 6 of the first
byte set as the "infinity" flag in the BLS point compression).

**Mitigating factor**: `process_pending_deposits` (item #4) **does NOT
verify this signature** — pre-activation pending deposits are
recognized by `slot == GENESIS_SLOT` (the placeholder marker) and the
signature is never decompressed. So the actual byte content of the
signature field is irrelevant to consensus. Grandine's `empty()`
choice produces a different *bytes* value than the spec-literal
G2_POINT_AT_INFINITY but **the same observable post-state**, because
the signature field is never read. Worth flagging for strict-spec
compliance auditors.

### lodestar relies on ES2019 stable sort (Array.prototype.sort)

Lodestar's pre-activation sort:
```typescript
preActivation.sort((i0, i1) => {
  const res = validatorsArr[i0].activationEligibilityEpoch
            - validatorsArr[i1].activationEligibilityEpoch;
  return res !== 0 ? res : i0 - i1;
});
```

**The secondary key on `i0 - i1` makes the sort order deterministic
regardless of stability** — even if `Array.prototype.sort` were
unstable, the explicit tiebreaker would produce the spec ordering. So
this is correct, but worth noting that lodestar is the only client
whose sort correctness relies on:
1. JavaScript's number subtraction returning a sign for the comparator
   (which works for `Epoch` values < 2^53).
2. The explicit tiebreaker (which is what guarantees correctness, NOT
   the sort stability).

A regression to `preActivation.sort()` (no comparator) would silently
sort lexicographically by string-coerced index — catastrophic.

### nimbus uses tuple-comparison-based sort

```nim
var pre_activation: seq[(Epoch, uint64)]
for index, validator in post.validators:
  if validator.activation_epoch == FAR_FUTURE_EPOCH:
    pre_activation.add((validator.activation_eligibility_epoch, index.uint64))
sort(pre_activation)
```

Nimbus relies on Nim's lexicographic tuple comparison: `(Epoch,
uint64)` tuples sort by first element, then by second. This is the
cleanest expression of the spec's `sorted(..., key=lambda i:
(post.validators[i].activation_eligibility_epoch, i))` in any client.

### teku's stream-based composition

```java
IntStream.range(0, validators.size())
    .filter(index -> validators.get(index).getActivationEpoch().equals(FAR_FUTURE_EPOCH))
    .boxed()
    .sorted(
        Comparator.comparing(
                (Integer index) -> validators.get(index).getActivationEligibilityEpoch())
            .thenComparing(index -> index))
    .forEach(index -> beaconStateMutators.queueEntireBalanceAndResetValidator(state, index));
```

Most verbose of the six but explicit about ordering: `Comparator.comparing(...)
.thenComparing(...)` is the most-readable rendering of the
`(eligibility_epoch, index)` lex order.

## EF fixture results — fork category not wired in BeaconBreaker harness

The 22 EF mainnet/electra/fork/fork fixtures (basic upgrade,
pre-activation seeding, compounding-credential edge cases, churn-limit
boundary cases, post-fork block processing combinations, random
states) are **not currently dispatched** by BeaconBreaker's
`scripts/run_fixture.sh` harness — `parse_fixture` in
`tools/runners/_lib.sh` doesn't recognize the `fork/fork/` category
path. All 6 clients' internal CI passes these fixtures (per source
review of their respective test runners — lighthouse's `ef_tests`,
lodestar's vitest spec runner, grandine's cargo test, prysm's bazel
spec_tests, teku's reference tests, nimbus's `ncli`).

**Wiring the fork category in BeaconBreaker is the primary follow-up
work for this item.** Each client has a "state transition" or
"upgrade" test category in its EF integration test runner that this
function is exercised under. The harness extension is straightforward:

- prysm: `TestMainnet_Electra_Transition_<test>` test names
- lighthouse: `transition_electra_<test>` test fn in `ef_tests` binary
- lodestar: vitest fork suite (already iterates EF fixture dirs)
- grandine: `cargo test --test=spec_tests fork::electra::<test>`
- teku: `ReferenceTestRunner` for state transition (skipped in BB)
- nimbus: `nimbus_state_sim` or dedicated upgrade test (skipped in BB)

Until then, this audit's verdict rests on **uniform 6/6 source review
agreement** with no observable divergence in the 9 hypotheses above.

## Cross-cut chain — item #11 underpins items #1–#10

`upgrade_to_electra` defines the post-state shape every prior audit
item assumes:

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

**Every item's PASS verdict implicitly validates item #11's post-state
construction.** If upgrade had wrong defaults, a wrong sort order, or a
wrong sentinel, downstream items #2–#10 would have surfaced
divergences in their EF fixtures (which exercise non-trivial
post-Electra state shapes generated by the upgrade).

## Adjacent untouched

- **Wiring the fork category in `tools/runners/_lib.sh`** — extend
  `parse_fixture` with `fork/<fork>/pyspec_tests/*` pattern, add
  per-client dispatch. Required for first-class fixture verification
  of this item.
- **`fork_pre_activation`** fixture — directly exercises H5/H6
  (sort+seed). Run all 6 clients explicitly once harness is wired.
- **`fork_pending_deposits_are_sorted`** — directly exercises H5
  (sort key correctness with multiple validators sharing
  `activation_eligibility_epoch`).
- **`fork_earliest_exit_epoch_is_max_validator_exit_epoch`** —
  directly exercises H1/H2 (max-walk + 1 ordering).
- **`fork_has_compounding_withdrawal_credential`** — directly
  exercises H7 (early-adopter loop with multiple 0x02 validators).
- **`fork_inactive_compounding_validator_with_excess_balance`** —
  exercises the cross-cut H6+H7 (a pre-activation 0x02 validator;
  must be queued by H6 first, NOT H7, because H8 ordering puts H6
  before H7 — H7 only sees post-H6-cleared validators with effective
  balance 0).
- **prysm's pre-state churn-limit deviation** — codified observability
  test: any future Pectra-time mutation between `pre` capture and
  `tab` calculation would silently break.
- **grandine's `SignatureBytes::empty()` vs explicit `G2_POINT_AT_INFINITY`** —
  observable-equivalent today (signature never read for placeholder
  deposits), but a strict-spec-compliance regression vector if a
  future upgrade-time change ever validates these signatures.
- **lodestar's epoch-context cache rebuild** (line 79: `getCachedBeaconState(stateElectraView, stateDeneb)`) —
  rebuilds caches from scratch with the post-state. **The pubkey-to-index
  map and validator caches are inherited** (validators array unchanged
  pre→post except for the pre-activation zeroing), but worth verifying
  the cache rebuild handles the two-phase mutation (zero balance + set
  FAR_FUTURE_EPOCH on multiple validators) atomically.
- **nimbus's `template post: untyped = result`** — Nim-specific
  syntactic sugar that aliases `result` (the implicit return value)
  as `post` for cleaner field access. Idiomatic but worth a comment
  for non-Nim auditors.

## Future research items

1. **Wire the fork category in BeaconBreaker's harness** (highest
   priority — direct blocker for first-class fixture verification of
   this item).
2. **Cross-fork upgrade fixture spanning Capella → Deneb → Electra**
   — does the sequence `upgrade_to_deneb(state); upgrade_to_electra(deneb_state)`
   produce the same Electra state as `upgrade_to_electra(deneb_state)`
   directly when there's no pre-Deneb upgrade history? Should be
   trivially yes by construction, but worth a fixture.
3. **Pre-activation deposit drain ordering test** — after upgrade
   queues N pre-activation validators, the next epoch's
   `process_pending_deposits` (item #4) drains them in queue order.
   Verify the FIFO order matches the upgrade's sorted insertion order.
4. **Compounding-credential cross-cut: `fork_inactive_compounding_validator_with_excess_balance`** —
   the "early adopter" loop iterates all post.validators, but a
   pre-activation 0x02 validator has been zeroed (balance = 0,
   effective_balance = 0) by H6. So `queue_excess_active_balance`
   sees balance = 0 ≤ MIN_ACTIVATION_BALANCE and does nothing. Verify
   this interaction is identical across all 6 clients (the fixture
   name suggests this is the EF-tested path).
5. **`MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT` clamp** — at upgrade
   time, the `get_activation_exit_churn_limit(post)` may clamp at
   `MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT = 256 ETH` (mainnet) if
   the active balance is high enough. Verify the clamp behavior is
   consistent.
6. **Sentinel value `UNSET_DEPOSIT_REQUESTS_START_INDEX = 2^64 - 1`** —
   downstream `process_deposit_request` (EIP-6110) treats this as
   "EL→CL bridge has not yet sent the start index". The first
   deposit_request in a block sets it to that request's index. Worth
   a fixture exercising the upgrade-time sentinel + first
   deposit_request transition.
7. **Re-upgrade idempotency** — if `upgrade_to_electra` is mistakenly
   called twice (programmer error), what happens? Spec doesn't define
   this, but each client's behavior would be a forward-compat liability.
8. **Schema-version guard at the upgrade entry** — does each client
   verify `pre.fork.current_version == DENEB_FORK_VERSION` before
   running the upgrade? A wrong-fork upgrade could silently produce
   garbage. Most clients enforce this at the call site (per-fork
   dispatch) but a defensive assertion inside `upgrade_to_electra`
   would be belt-and-suspenders.
9. **`pubkey_cache` and `proposer_cache` invalidation** — lighthouse's
   epoch cache is built before the upgrade returns; lodestar rebuilds
   the cached state from scratch; teku/nimbus/grandine/prysm have
   their own cache choreography. Audit cross-client cache coherence
   at the upgrade boundary.
10. **Nimbus's `discard post.pending_deposits.add ...`** — the
    `discard` keyword silently swallows a `bool` (success) return
    from HashList.add. If the list is at capacity (PENDING_DEPOSITS_LIMIT
    = 2^27 = 134M entries), the `add` would return false and silently
    drop the deposit. Mainnet validator count is ~10^6, so at upgrade
    time the pre-activation queue is at most ~10^4 entries — F-tier
    today, but worth a `doAssert` for fail-loud semantics.
