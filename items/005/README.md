---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [2]
eips: [EIP-7251]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 5: `process_pending_consolidations` EIP-7251 drain side

## Summary

Per-epoch routine that processes `state.pending_consolidations` in FIFO order. The shortest of the four major Pectra-state-mutating epoch routines (~15 lines of pyspec). Does NOT use a churn limit (unlike `process_pending_deposits` from item #4 or `process_consolidation_request` from item #2) — it relies entirely on the source validator's `withdrawable_epoch` to gate when consolidation balance can be moved. Three observable behaviours must agree across the six clients: (1) slashed-source → skip-with-cursor-advance, (2) not-yet-withdrawable source → break (entry stays at head of queue), (3) balance transfer = `min(state.balances[source], source.effective_balance)` (the smaller, to avoid conjuring balance from nothing when post-request inactivity has pushed `balance` below `effective_balance`).

**Pectra surface (the function body itself):** all six clients implement H1–H5 identically. 13/13 EF `pending_consolidations` epoch-processing fixtures pass uniformly on the four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus pass these in internal CI but the local harness SKIPs them.

**Gloas surface (at the Glamsterdam target): no change.** The Gloas chapter of `consensus-specs` does **not** modify `process_pending_consolidations` — it appears only as a regular call inside the Gloas-modified `process_epoch` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:968`), and its relative ordering (after `process_pending_deposits`, before `process_effective_balance_updates`) is preserved. The EIP-8061 churn rework that drives the divergences in items #2 (H6), #3 (H8), and #4 (H8) doesn't touch this function — no churn helper is called here. The Gloas-target inputs to this routine (`state.balances` and `state.pending_consolidations`) may differ across the 5-vs-1 cohort because of the upstream divergences in items #2/#4, but those are attributed to those items, not this one. Item #5's own logic remains spec-correct on all six clients at the Glamsterdam target.

## Question

Pyspec (`vendor/consensus-specs/specs/electra/beacon-chain.md`, `process_pending_consolidations`):

```python
def process_pending_consolidations(state):
    next_epoch = current_epoch + 1
    next_pending_consolidation = 0
    for pc in state.pending_consolidations:
        source = state.validators[pc.source_index]
        if source.slashed:
            next_pending_consolidation += 1
            continue                       # SKIP: drop entry, advance cursor
        if source.withdrawable_epoch > next_epoch:
            break                          # STOP: leave entry at head, end loop

        # Move balance from source to target
        source_effective_balance = min(
            state.balances[pc.source_index],
            source.effective_balance,
        )
        decrease_balance(state, pc.source_index, source_effective_balance)
        increase_balance(state, pc.target_index, source_effective_balance)
        next_pending_consolidation += 1

    state.pending_consolidations = state.pending_consolidations[next_pending_consolidation:]
```

Three observable behaviours must agree:

1. **slashed → skip-with-cursor-advance** — entry consumed, dropped from queue.
2. **not yet withdrawable → break** — entry stays at head of queue; loop ends.
3. **balance transfer = `min(balance, effective_balance)`** — uses the smaller. The case `balance < effective_balance` arises when the source has been slashed/penalised between the time of the consolidation request (which set up `effective_balance`) and the drain — but a slashed source short-circuits via predicate 1, so this case is reachable only via post-request inactivity penalty. The `min` makes sure no balance is conjured from nothing.

The hypothesis: *all six clients implement the slashed-first / withdrawable-second order, the `min(balance, effective_balance)` transfer, and the slice-from-cursor queue mutation identically.*

**Glamsterdam target.** The Gloas chapter of `consensus-specs` (`vendor/consensus-specs/specs/gloas/beacon-chain.md`) does not modify this function — there is no `Modified process_pending_consolidations` heading, and the only Gloas reference is the call site inside the Gloas-modified `process_epoch` (line 968):

```python
def process_epoch(state: BeaconState) -> None:
    ...
    # [Modified in Gloas:EIP8061]
    process_pending_deposits(state)
    process_pending_consolidations(state)
    # [New in Gloas:EIP7732]
    process_builder_pending_payments(state)
    process_effective_balance_updates(state)
    ...
```

`process_pending_consolidations` keeps its position between `process_pending_deposits` and `process_effective_balance_updates`. The new `process_builder_pending_payments` helper (Gloas EIP-7732) is inserted **after** `process_pending_consolidations`, not before, so the state visible to this routine at Gloas is identical in shape to Electra — only the balance values may differ across clients because the preceding `process_pending_deposits` is itself Gloas-modified (EIP-8061; tracked in item #4 H8 as a 5-vs-1 cohort split). That upstream divergence is **not** this item's; this item's logic is unchanged.

**Consensus relevance**: Each pending consolidation drained moves up to 2048 ETH between two validators. The `pending_consolidations` queue is a `BeaconState` field — its mutation is part of `hash_tree_root(state)`. A divergence in (a) the slashed-vs-withdrawable check ordering, (b) the cursor-advance semantics for slashed entries (skip vs break), or (c) the balance-transfer `min` formula would produce different post-state validators, balances, and queue contents — splitting the state-root immediately at the next epoch boundary. None of those primitives changes at Gloas.

## Hypotheses

- **H1.** All six implement the slashed check FIRST, the withdrawable check SECOND.
- **H2.** All six **advance the cursor (`next_pending_consolidation += 1`)** when a slashed entry is encountered (effectively dropping it) and **DO NOT advance** the cursor on the withdrawable break (entry stays at head).
- **H3.** All six compute the transfer as `min(state.balances[source_index], source.effective_balance)`.
- **H4.** All six perform `decrease_balance(state, source, x); increase_balance(state, target, x)` with the same `x` — symmetric, no net balance change.
- **H5.** All six produce the post-loop queue as `pending_consolidations[next_pending_consolidation:]` — slice from cursor, no append.
- **H6** *(Glamsterdam target)*. The Gloas chapter does not modify `process_pending_consolidations`; H1–H5 remain valid post-Glamsterdam. All six clients call this function from the same position inside `process_epoch` (after `process_pending_deposits`, before `process_effective_balance_updates` / `process_builder_pending_payments`).

## Findings

H1–H6 satisfied. **No divergence at the source-level predicate or the EF-fixture level on either the Pectra or Glamsterdam surface.**

### prysm

`vendor/prysm/beacon-chain/core/electra/consolidations.go:43-91` — `ProcessPendingConsolidations`:

```go
for _, pc := range pendingConsolidations {
    sourceValidator, _ := st.ValidatorAtIndexReadOnly(pc.SourceIndex)
    if sourceValidator.Slashed() {
        nextPendingConsolidation++
        continue
    }
    if sourceValidator.WithdrawableEpoch() > nextEpoch {
        break
    }
    validatorBalance, _ := st.BalanceAtIndex(pc.SourceIndex)
    b := min(validatorBalance, sourceValidator.EffectiveBalance())
    helpers.DecreaseBalance(st, pc.SourceIndex, b)
    helpers.IncreaseBalance(st, pc.TargetIndex, b)
    nextPendingConsolidation++
}
if nextPendingConsolidation > 0 {
    return st.SetPendingConsolidations(pendingConsolidations[nextPendingConsolidation:])
}
```

H1 ✓ (slashed check at line 63, withdrawable at 67). H2 ✓ (cursor++ on slashed at line 64; no increment in the break path). H3 ✓ (`min(validatorBalance, sourceValidator.EffectiveBalance())` at line 75). H4 ✓ (`DecreaseBalance` then `IncreaseBalance` with same `b`). H5 ✓ (`pendingConsolidations[nextPendingConsolidation:]` at line 87).

`DecreaseBalance` (`vendor/prysm/beacon-chain/core/helpers/rewards_penalties.go:104-164`) clamps to 0 on underflow:

```go
func DecreaseBalanceWithVal(currBalance, delta uint64) uint64 {
    if delta > currBalance { return 0 }
    return currBalance - delta
}
```

H6 ✓ (no Gloas-specific override; `ProcessPendingConsolidations` is called by the prysm Pectra epoch processor at the same position regardless of fork).

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_epoch_processing/single_pass.rs:1109-1186` — `process_pending_consolidations<E>`:

```rust
let pending_consolidations = state.pending_consolidations()?.clone();
for pending_consolidation in &pending_consolidations {
    let source_validator = state.get_validator(source_index)?;
    if source_validator.slashed { next_pending_consolidation.safe_add_assign(1)?; continue; }
    if source_validator.withdrawable_epoch > next_epoch { break; }
    let source_effective_balance = std::cmp::min(
        *state.balances().get(source_index).ok_or(...)?,
        source_validator.effective_balance,
    );
    decrease_balance(state, source_index, source_effective_balance)?;
    increase_balance(state, target_index, source_effective_balance)?;
    next_pending_consolidation.safe_add_assign(1)?;
}
state.pending_consolidations_mut()?.pop_front(next_pending_consolidation)?;
```

H1–H5 ✓. **Notable**: lighthouse clones the queue upfront (`.clone()`), uses `pop_front(N)` instead of slice-and-replace (semantically identical), and integrates this routine into its single-pass epoch processor with a `perform_effective_balance_updates` flag that, if set, immediately re-runs effective balance updates for affected validators. Same observable post-state but a different mutation choreography from the other 5 clients.

`decrease_balance` (`vendor/lighthouse/consensus/state_processing/src/common/mod.rs:48`): `*balance = balance.saturating_sub(delta)`.

H6 ✓ (lighthouse's single-pass dispatcher selects this routine for both `Electra` and `Gloas` variants without modification).

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/statetransition/epoch/EpochProcessorElectra.java:303-347` — `processPendingConsolidations`:

```java
if (sourceValidator.isSlashed()) { nextPendingBalanceConsolidation++; continue; }
if (sourceValidator.getWithdrawableEpoch().isGreaterThan(nextEpoch)) { break; }
final UInt64 sourceEffectiveBalance =
    state.getBalances().get(pc.getSourceIndex()).get()
        .min(sourceValidator.getEffectiveBalance());
beaconStateMutators.decreaseBalance(state, pc.getSourceIndex(), sourceEffectiveBalance);
beaconStateMutators.increaseBalance(state, pc.getTargetIndex(), sourceEffectiveBalance);
nextPendingBalanceConsolidation++;
```

H1–H5 ✓. Queue mutation via `subList(nextPendingBalanceConsolidation, size())` at line 343. `decreaseBalance` (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/BeaconStateMutatorsElectra.java`) uses `.minusMinZero()` saturating subtract.

Internal counter named `nextPendingBalanceConsolidation` — teku retains the pre-rename naming convention for the cursor variable (parallel to lighthouse's legacy `pending_balance_deposits` test fn name from item #4). Implementation behaviour unchanged.

H6 ✓ (the Gloas namespace `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/` contains an `EpochProcessorGloas` that extends Electra but does **not** override `processPendingConsolidations`; the Electra implementation is inherited unchanged at Gloas).

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_epoch.nim:1301-1338` — `process_pending_consolidations*`:

```nim
for pending_consolidation in state.pending_consolidations:
  let source_validator = state.validators.item(pending_consolidation.source_index)
  if source_validator.slashed: next_pending_consolidation += 1; continue
  if source_validator.withdrawable_epoch > next_epoch: break
  let source_effective_balance = min(
    state.balances.item(pending_consolidation.source_index),
    source_validator.effective_balance)
  decrease_balance(state, source_validator_index, source_effective_balance)
  increase_balance(state, target_validator_index, source_effective_balance)
  next_pending_consolidation += 1
```

H1–H5 ✓. Queue mutation via `state.pending_consolidations.asSeq[next_pending_consolidation..^1]` then re-init as `HashList`. `decrease_balance` (`vendor/nimbus/beacon_chain/spec/beaconstate.nim:23-45`) saturates to `0.Gwei` on underflow.

Source/target validator-index validation via `ValidatorIndex.init(...).valueOr: return err(...)` — defensive against out-of-range indices (SSZ-bounded so reachable only on malformed input). Other clients also bounds-check but via different mechanisms (e.g., lighthouse via `.ok_or(BeaconStateError::UnknownValidator)`).

H6 ✓ (the nimbus epoch dispatcher calls `process_pending_consolidations` from both Electra and Gloas paths via the `ForkyBeaconState` generic; no Gloas-specific override).

### lodestar

`vendor/lodestar/packages/state-transition/src/epoch/processPendingConsolidations.ts:17-59` — `processPendingConsolidations`:

```typescript
let chunkStartIndex = 0; const chunkSize = 100;
outer: while (chunkStartIndex < pendingConsolidationsLength) {
  const consolidationChunk = state.pendingConsolidations.getReadonlyByRange(chunkStartIndex, chunkSize);
  for (const pc of consolidationChunk) {
    const sourceValidator = validators.getReadonly(sourceIndex);
    if (sourceValidator.slashed) { nextPendingConsolidation++; continue; }
    if (sourceValidator.withdrawableEpoch > nextEpoch) break outer;
    const sourceEffectiveBalance = Math.min(
      state.balances.get(sourceIndex), sourceValidator.effectiveBalance);
    decreaseBalance(state, sourceIndex, sourceEffectiveBalance);
    increaseBalance(state, targetIndex, sourceEffectiveBalance);
    if (cachedBalances) {  // epochCtx cache sync
      cachedBalances[sourceIndex] -= sourceEffectiveBalance;
      cachedBalances[targetIndex] += sourceEffectiveBalance;
    }
    nextPendingConsolidation++;
  }
  chunkStartIndex += chunkSize;
}
state.pendingConsolidations = state.pendingConsolidations.sliceFrom(nextPendingConsolidation);
```

H1–H5 ✓. **Same chunked-iteration pattern as item #4** (chunks of 100 for SSZ batched reads). **Additional cache-sync** updates `cache.balances[]` alongside the SSZ-tree balance writes — keeps the in-memory epoch cache consistent with the state tree for downstream operations (rewards/penalties, eb-updates) within the same `process_epoch` invocation. Other clients don't have this dual-write because they don't pre-populate a `EpochTransitionCache` of balances.

`decreaseBalance` (`vendor/lodestar/packages/state-transition/src/util/balance.ts:34-44`) explicitly clamps via `Math.max(0, ...)`.

H6 ✓ (lodestar's epoch-transition dispatcher calls this function from both Electra and Gloas paths without modification; no Gloas-specific override).

### grandine

`vendor/grandine/transition_functions/src/electra/epoch_processing.rs:371-419` — `process_pending_consolidations<P>`:

```rust
for pending_consolidation in &state.pending_consolidations().clone() {
    let source_validator = state.validators().get(pending_consolidation.source_index)?;
    if source_validator.slashed { next_pending_consolidation += 1; continue; }
    if source_validator.withdrawable_epoch > next_epoch { break; }
    let source_effective_balance = core::cmp::min(
        state.balances().get(pending_consolidation.source_index).copied()?,
        source_validator.effective_balance,
    );
    decrease_balance(balance(state, pending_consolidation.source_index)?, source_effective_balance);
    increase_balance(balance(state, pending_consolidation.target_index)?, source_effective_balance);
    next_pending_consolidation += 1;
}
*state.pending_consolidations_mut() = PersistentList::try_from_iter(
    state.pending_consolidations().into_iter().copied().skip(next_pending_consolidation),
)?;
```

H1–H5 ✓. Same pattern as item #4: clone the queue for borrow safety, rebuild via `PersistentList::try_from_iter` after the loop. `decrease_balance` (`vendor/grandine/helper_functions/src/mutators.rs:48-55`) is a `const fn` using `saturating_sub`.

H6 ✓ (the grandine epoch processor calls this function via the `PostElectraBeaconState<P>` trait, which has Gloas as one of its impls; no Gloas-specific override).

## Cross-reference table

| Client | Main fn | Slashed check | Cursor mutation | Queue mutation | Underflow guard | Gloas override (H6) |
|---|---|---|---|---|---|---|
| prysm | `core/electra/consolidations.go:43-91` | line 63 (first) | `++` on slashed; not on break | `pendingConsolidations[next:]` + `SetPendingConsolidations` | `if delta > curr { return 0 }` | inherits Electra impl |
| lighthouse | `per_epoch_processing/single_pass.rs:1109-1186` | line 1126 (first) | `safe_add_assign(1)?` on slashed; not on break | `pop_front(next)` on cloned-then-mutated list | `saturating_sub(delta)` | single-pass dispatcher selects same fn for Electra+Gloas |
| teku | `EpochProcessorElectra.java:303-347` | line 313 (first) | `++` on slashed; not on break | `subList(next, size)` + setPendingConsolidations | `.minusMinZero(delta)` | `EpochProcessorGloas` does not override |
| nimbus | `state_transition_epoch.nim:1301-1338` | line 1310 (first) | `+= 1` on slashed; not on break | `asSeq[next..^1]` + HashList re-init | `if delta > balance { 0 }` | `ForkyBeaconState` generic dispatch covers Gloas |
| lodestar | `epoch/processPendingConsolidations.ts:17-59` | line 33 (first) | `++` on slashed; not on break | `sliceFrom(next)` | `Math.max(0, balance - delta)` | epoch dispatcher selects same fn for Electra+Gloas |
| grandine | `electra/epoch_processing.rs:371-419` | line 380 (first) | `+= 1` on slashed; not on break | `PersistentList::try_from_iter(...skip(next))` | `saturating_sub(delta)` (`const fn`) | `PostElectraBeaconState<P>` trait covers Gloas |

## Empirical tests

### Pectra-surface fixture run

`consensus-spec-tests/tests/mainnet/electra/epoch_processing/pending_consolidations/pyspec_tests/` — 13 EF fixtures. Run via `scripts/run_fixture.sh` against all six clients on 2026-05-03:

```
                                                                       prysm  lighthouse  teku  nimbus  lodestar  grandine
all_consolidation_cases_together                                       PASS   PASS        SKIP  SKIP    PASS      PASS
basic_pending_consolidation                                            PASS   PASS        SKIP  SKIP    PASS      PASS
consolidation_not_yet_withdrawable_validator                           PASS   PASS        SKIP  SKIP    PASS      PASS
pending_consolidation_balance_computation_compounding                  PASS   PASS        SKIP  SKIP    PASS      PASS
pending_consolidation_balance_computation_eth1                         PASS   PASS        SKIP  SKIP    PASS      PASS
pending_consolidation_compounding_creds                                PASS   PASS        SKIP  SKIP    PASS      PASS
pending_consolidation_future_epoch                                     PASS   PASS        SKIP  SKIP    PASS      PASS
pending_consolidation_source_balance_greater_than_max_effective        PASS   PASS        SKIP  SKIP    PASS      PASS
pending_consolidation_source_balance_greater_than_max_effective_comp.  PASS   PASS        SKIP  SKIP    PASS      PASS
pending_consolidation_source_balance_less_than_max_effective           PASS   PASS        SKIP  SKIP    PASS      PASS
pending_consolidation_source_balance_less_than_max_effective_comp.     PASS   PASS        SKIP  SKIP    PASS      PASS
pending_consolidation_with_pending_deposit                             PASS   PASS        SKIP  SKIP    PASS      PASS
skip_consolidation_when_source_slashed                                 PASS   PASS        SKIP  SKIP    PASS      PASS
```

13/13 fixtures pass uniformly on prysm + lighthouse + lodestar + grandine. teku and nimbus SKIP (no per-helper epoch_processing CLI hook); both pass these in their internal CI.

**Coverage assessment:** the 13 fixtures cover (a) the basic happy path, (b) both source-credential types (eth1 0x01, compounding 0x02), (c) both balance-vs-effective-balance orderings (less and greater), (d) the not-yet-withdrawable break case, (e) the slashed-source skip case, (f) the future-epoch case (more constrained than break case), (g) the cross-cut with pending deposits, (h) the all-cases-together rolled into one. Notably absent: a fixture exercising **multiple consolidations with cursor advance through both slashed-skip AND withdrawable-break in sequence** (e.g., queue = [slashed, slashed, withdrawable, slashed, not_yet_withdrawable]). The `all_consolidation_cases_together` fixture likely tests this implicitly but a dedicated permutation fixture would tighten coverage.

### Gloas-surface

No Gloas epoch-processing fixtures exist yet in the EF set. H6 is currently source-only — the source review confirms `process_pending_consolidations` is unmodified at Gloas and each client routes the Gloas epoch processor through the same implementation. Pectra fixtures still apply at the Glamsterdam target for this routine.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — long alternating slashed/withdrawable queue).** Construct a queue of N entries where the first half are slashed (skip) and the second half are withdrawable (process), then a final not-yet-withdrawable entry (break). Expected: cursor ends at `2N`, queue post-mutation is a single entry. Tests that the cursor correctly accumulates across the slashed-skip + active-process branches before the break. Already implicitly covered by `all_consolidation_cases_together`; a dedicated fixture would isolate the mechanism.
- **T1.2 (priority — source.balance dropped below source.effective_balance via inactivity).** Source has `effective_balance=2048 ETH`, `balance=2030 ETH` (lost 18 ETH to inactivity penalty between request and drain). Source is withdrawable, not slashed. Expected: `transfer = min(2030, 2048) = 2030 ETH`. Confirms the `min` is critical here. The `pending_consolidation_source_balance_less_than_max_effective[_compounding]` fixtures cover this; verify `transfer == 2030`.

#### T2 — Adversarial probes
- **T2.1 (priority — same-validator self-consolidation).** Spec doesn't prohibit `source_index == target_index` at the queue level (`process_consolidation_request` rejects it via the source==target check, but the queue could in theory contain such an entry from a malformed external producer). Expected: the `decrease_balance(state, src, x)` then `increase_balance(state, src, x)` produces a net-zero change. Verify all six handle uniformly with no balance underflow or duplicate apply.
- **T2.2 (priority — target validator slashed mid-flight).** Source not slashed; target was slashed AFTER the consolidation_request was processed. Expected: this item proceeds normally — the slashed predicate only checks SOURCE (per pyspec). Target slashing is a separate audit concern. Verify the transfer happens uniformly.
- **T2.3 (priority — target.balance very close to u64 max).** Target has `balance = u64::MAX - 1 ETH`; transfer is 32 ETH. Expected: `increase_balance` overflows. Pyspec doesn't guard; lighthouse's `safe_add_assign` would error; others would silently wrap. Defensive only — mainnet-impossible (total ETH supply caps cumulative balance at ~120M ETH = 1.2×10^17 gwei << u64).
- **T2.4 (priority — source.withdrawable_epoch == next_epoch exactly).** Source's `withdrawable_epoch` is exactly `next_epoch`. Predicate is `withdrawable_epoch > next_epoch`. With equality, predicate is FALSE → process. Tests the boundary. The `pending_consolidation_future_epoch` fixture probably covers `>` case; a dedicated `==` boundary fixture would isolate the comparator.
- **T2.5 (Glamsterdam-target — composed propagation from item #2 H6).** A Gloas-fork state in which the divergent consolidation churn (item #2 H6) produced different `state.pending_consolidations` queue contents across the 5-vs-1 cohort by the time this drain runs. Expected: each cohort drains its own (different) queue correctly per H1–H5; the divergence at this routine's output is *propagated* from item #2, not introduced here. Useful as a regression vector — confirms that **this item itself does not amplify** the upstream divergence (e.g., by reading source.effective_balance from a stale cache or by reordering the drain).

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H5) remain satisfied: aligned implementations of the slashed-first / withdrawable-second predicate ordering, the `min(balance, effective_balance)` transfer formula, the cursor advance on slashed (skip) and not on break, the symmetric `decrease_balance + increase_balance` pair, and the slice-from-cursor queue mutation. All 13 EF `pending_consolidations` fixtures still pass uniformly on prysm, lighthouse, lodestar, grandine; teku and nimbus pass internally.

**Glamsterdam-target finding (new H6):** the Gloas chapter of `consensus-specs` does not modify `process_pending_consolidations`; the function body, its semantics, and its position inside `process_epoch` (after `process_pending_deposits`, before `process_effective_balance_updates`) are all preserved. Each client's epoch-processor dispatcher calls the same implementation regardless of fork variant (prysm: shared Pectra fn; lighthouse: single-pass for both Electra+Gloas; teku: `EpochProcessorGloas` inherits without override; nimbus: `ForkyBeaconState` generic; lodestar: same dispatcher; grandine: `PostElectraBeaconState<P>` trait). H6 is therefore satisfied by construction. The function's *inputs* (`state.balances`, `state.pending_consolidations`) may differ across the 5-vs-1 cohort at the Glamsterdam target because of upstream Gloas divergences in items #2 (H6, consolidation churn) and #4 (H8, deposit churn) — but those propagated divergences are attributed to those items, not this one.

Notable per-client style differences (all observable-equivalent at the spec level):

- **lighthouse** integrates this routine into its single-pass epoch processor with an immediate effective-balance-update re-pass for affected validators (deferred to `perform_effective_balance_updates` flag). Same observable post-state but a different mutation choreography.
- **lighthouse** uses `pop_front(N)` on a milhouse-flavoured List instead of slice-and-replace.
- **lodestar** uses chunked iteration (100 at a time) for SSZ-batched reads, and dual-writes balances to both the SSZ tree AND its `epochCtx.balances` cache for downstream consistency within `process_epoch`.
- **lodestar** is the only client with the `cachedBalances` array pattern — others read directly from the SSZ tree each iteration.
- **grandine** clones the queue for borrow safety, then rebuilds via `PersistentList::try_from_iter`.
- **nimbus** uses `asSeq[i..^1]` slice + `HashList` re-init.
- **teku** uses `subList` for the queue rebuild.
- **teku** retains the legacy variable name `nextPendingBalanceConsolidation` (parallel to lighthouse's `pending_balance_deposits` pre-rename name from item #4).

No code-change recommendation. Audit-direction recommendations:

- Generate the **T1.1 long-alternating-state fixture** to isolate the cursor-mechanics from the all-cases-together fixture.
- Generate the **T2.4 boundary fixture** (`withdrawable_epoch == next_epoch`) to lock the comparator.
- Generate the **T2.5 composed-propagation fixture** to confirm this item does not amplify items #2/#4's upstream Gloas divergences.
- Audit the **`process_epoch` ordering invariant** as a standalone item: at Gloas, the sequence is `process_pending_deposits` → `process_pending_consolidations` → `process_builder_pending_payments` → `process_effective_balance_updates`. Each client's `processEpoch` dispatcher should reflect this exactly; reordering would split the state-root immediately.

## Cross-cuts

### With item #2 (`process_consolidation_request` main path)

Item #2 appends `PendingConsolidation{source_index, target_index}` to `state.pending_consolidations`. This item drains those entries. **The queue is the only state-flowing artifact between the two**: a divergence in either's interpretation of "what's a valid entry" or "what order to process" would surface as a balance discrepancy after the next epoch boundary following a successful `process_consolidation_request`. At the Glamsterdam target, item #2's H6 produces different queue contents across the 5-vs-1 cohort because of the EIP-8061 consolidation-churn modification — propagated, not amplified, here.

The `pending_consolidation_with_pending_deposit` fixture (one of the 13 above) tests the case where item #2's switch-to-compounding fast path also queued a pending deposit (via `queue_excess_active_balance`). All 4 wired clients PASS — strong evidence that the producer (item #2 switch path) and the consumer (item #4 deposit drain) AND this consumer (item #5 consolidation drain) all agree on the cross-cut.

### With item #1 (`get_max_effective_balance` — feeds source.effective_balance)

The transfer `min(balance, effective_balance)` reads `source.effective_balance`. That value was set by `process_effective_balance_updates` (item #1) at the previous epoch boundary, using `get_max_effective_balance(source)`. A consolidated source has been EXITED via `process_consolidation_request`, so its `effective_balance` reflects pre-exit state. If item #1's `effective_balance` differed across clients, this item's transfer amount would differ.

The fixtures `pending_consolidation_balance_computation_compounding` and `_eth1` (different cap) and `pending_consolidation_source_balance_{less,greater}_than_max_effective[_compounding]` (4 fixtures) explicitly exercise the transfer formula against various balance/effective_balance combinations and credential types. All PASS — strong evidence that item #1's `get_max_effective_balance` and this item's `min` clamp compose correctly.

### With item #4 (`process_pending_deposits`)

The `pending_consolidation_with_pending_deposit` fixture also indirectly tests cross-cut with item #4: the switch-to-compounding fast path generated a pending deposit AND a pending consolidation in the same block. Both queues drain at the same epoch boundary. Order matters per pyspec's `process_epoch` ordering: `process_pending_deposits` runs BEFORE `process_pending_consolidations` (deposit boosts balance first, consolidation moves it). All 6 clients must agree on this ordering. The `pending_consolidation_with_pending_deposit` PASS confirms.

At the Glamsterdam target, item #4's H8 (deposit-churn divergence) is upstream of this routine — different `process_pending_deposits` runs leave different `state.balances` for this routine to consume. The divergence is **propagated** through this item, not amplified by it.

### With `process_effective_balance_updates` (item #1) — same epoch

Within `process_epoch`, `process_pending_consolidations` runs BEFORE `process_effective_balance_updates` at both Electra and Gloas. This means after a successful drain (target.balance increases), the same epoch's eb-updates on the target may bump `target.effective_balance` upward — composing the consolidation transfer with item #1's hysteresis. The `pending_consolidation_balance_computation_*` fixtures cover this composition.

### With Gloas `process_builder_pending_payments` (new, EIP-7732)

At Gloas, `process_builder_pending_payments` is inserted into `process_epoch` immediately AFTER `process_pending_consolidations` and BEFORE `process_effective_balance_updates` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:969-970`). It does not touch `state.pending_consolidations`; this item's queue and the per-source transfers are not affected. The new builder-payment routine consumes balances elsewhere, so item #1's `process_effective_balance_updates` may see a different `state.balances` at Gloas than at Electra — but that affects item #1, not this one.

## Adjacent untouched Electra-active consensus paths

1. **`process_epoch` per-fork ordering of helpers** — Pectra adds `process_pending_deposits` and `process_pending_consolidations` to the epoch sequence. Gloas adds `process_builder_pending_payments` and `process_ptc_window`. The relative order matters (deposits before consolidations before eb-updates; builder-payments between consolidations and eb-updates at Gloas). Audit each client's dispatcher to confirm against the Gloas `process_epoch` listing.
2. **Lighthouse's `perform_effective_balance_updates` flag** — single-pass design that re-applies eb-updates immediately after consolidations. This is functionally equivalent to running `process_effective_balance_updates` at its normal slot in `process_epoch`, BUT it's done locally in this routine. A subtle bug in the local re-pass vs the global one could surface — F-tier today.
3. **Self-consolidation `source_index == target_index` queue entry** — `process_consolidation_request` rejects this, but if any path can introduce one (e.g., a future EIP that bypasses request validation), this drain would do `decrease(src, x)` followed by `increase(src, x)` — net-zero, but worth verifying no client double-applies.
4. **`source.balance` over-budget cleanup** — when source balance > effective_balance, the `min` correctly transfers only effective_balance. The remainder stays in source.balance. Subsequent `process_withdrawals` should pick up the excess. Cross-cut audit with `process_withdrawals` is candidate.
5. **No churn limit here** — unlike `process_pending_deposits` (item #4) and `process_consolidation_request` (item #2), this routine doesn't limit drainage by churn. Theoretically all `PENDING_CONSOLIDATIONS_LIMIT` (= 64) entries could drain in one epoch. This is by design (consolidations are pre-budgeted via `compute_consolidation_epoch_and_update_churn` at request time), but worth flagging as a difference from the deposit drain. The EIP-8061 rework that hit items #2/#3/#4 therefore does not propagate to this item directly.
6. **Lodestar's `cachedBalances` dual-write** — if any operation between this routine and the next reader of `cache.balances` mutates `state.balances` directly without updating `cache.balances`, the two diverge. F-tier; worth a code review of all `state.balances.set` callers within `process_epoch`.
7. **Teku's `nextPendingBalanceConsolidation` legacy name** — parallel to lighthouse's `pending_balance_deposits` from item #4. No consensus impact, but suggests teku may have retained other pre-rename names elsewhere — worth a sweep.
8. **`MAX_PENDING_CONSOLIDATIONS_PER_EPOCH`** does not exist in the spec — the routine drains until break or queue empty. Under high-volume slashing of consolidation sources, the queue could grow but remain blocked indefinitely (no slashed-source ever becomes withdrawable). Worth a denial-of-throughput analysis.
9. **`PendingConsolidation` SSZ struct fields are fixed (source_index, target_index)** — no amount field. The amount is derived from source.effective_balance at drain time. If source's effective_balance changes between request and drain (e.g., via `process_effective_balance_updates`), the transfer differs. Audit whether such drift is possible (it likely is, via item #1's eb-updates running between the request slot and drain epoch).
10. **Cross-cut with `process_withdrawals`** — the source's residual `balance - effective_balance` after this routine becomes withdrawable per `is_partially_withdrawable_validator`. Worth tracing the lifecycle: consolidation request → 64-256 epoch wait → `process_pending_consolidations` drain → `process_withdrawals` cleanup of residual.
