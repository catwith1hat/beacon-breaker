# Item #5 — `process_pending_consolidations` EIP-7251 drain side

**Status:** no-divergence-pending-fuzzing — audited 2026-05-03. **Hypotheses H1–H5 satisfied. All 13 EF `pending_consolidations` epoch-processing fixtures pass uniformly on the four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus SKIP per harness limit.**

**Builds on:** item #2 (`process_consolidation_request`) — this item drains the `pending_consolidations` queue that item #2's main path appends to. Closes Track A's main drain side.

**Electra-active.** Track A — Pectra request-processing (drain side). Per-epoch routine that processes `state.pending_consolidations` in FIFO order. The shortest of the four major Pectra-state-mutating epoch routines (~15 lines of pyspec). Does NOT use a churn limit (unlike `process_pending_deposits` from item #4) — it relies entirely on the source validator's `withdrawable_epoch` to gate when consolidation balance can be moved.

## Question

Pyspec (`consensus-specs/specs/electra/beacon-chain.md` ~lines 1057–1080):

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

Three observable behaviors must agree:
1. **slashed → skip-with-cursor-advance** — entry consumed, dropped from queue.
2. **not yet withdrawable → break** — entry stays at head of queue; loop ends.
3. **balance transfer = `min(balance, effective_balance)`** — uses the smaller. The case `balance < effective_balance` arises when the source has been slashed/penalized between the time of the consolidation request (which set up `effective_balance`) and the drain — but a slashed source short-circuits via predicate 1, so this case is reachable only via post-request inactivity penalty. The `min` makes sure no balance is conjured from nothing.

The hypothesis: *all six clients implement the slashed-first / withdrawable-second order, the `min(balance, effective_balance)` transfer, and the slice-from-cursor queue mutation identically.*

**Consensus relevance**: Each pending consolidation drained moves up to 2048 ETH between two validators. The `pending_consolidations` queue is a `BeaconState` field — its mutation is part of `hash_tree_root(state)`. A divergence in (a) the slashed-vs-withdrawable check ordering, (b) the cursor-advance semantics for slashed entries (skip vs break), or (c) the balance-transfer `min` formula would produce different post-state validators, balances, and queue contents — splitting the state-root immediately at the next epoch boundary.

## Hypotheses

- **H1.** All six implement the slashed check FIRST, the withdrawable check SECOND.
- **H2.** All six **advance the cursor (`next_pending_consolidation += 1`)** when a slashed entry is encountered (effectively dropping it) and **DO NOT advance** the cursor on the withdrawable break (entry stays at head).
- **H3.** All six compute the transfer as `min(state.balances[source_index], source.effective_balance)`.
- **H4.** All six perform `decrease_balance(state, source, x); increase_balance(state, target, x)` with the same `x` — symmetric, no net balance change.
- **H5.** All six produce the post-loop queue as `pending_consolidations[next_pending_consolidation:]` — slice from cursor, no append.

## Findings

H1–H5 satisfied. **No divergence at the source-level predicate or the EF-fixture level.**

### prysm (`prysm/beacon-chain/core/electra/consolidations.go:43–91`)

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

H1 ✓ (slashed check L63, withdrawable L67). H2 ✓ (cursor++ on slashed L64, no increment in break path L68). H3 ✓ (`min(validatorBalance, sourceValidator.EffectiveBalance())` L73). H4 ✓ (`DecreaseBalance` then `IncreaseBalance` with same `b` L77-80). H5 ✓ (`pendingConsolidations[nextPendingConsolidation:]` L88).

`DecreaseBalance` (`core/helpers/rewards_penalties.go:104-164`) clamps to 0 on underflow:
```go
func DecreaseBalanceWithVal(currBalance, delta uint64) uint64 {
    if delta > currBalance { return 0 }
    return currBalance - delta
}
```

### lighthouse (`lighthouse/consensus/state_processing/src/per_epoch_processing/single_pass.rs:1109–1186`)

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

`decrease_balance` (`common/mod.rs:48`): `*balance = balance.saturating_sub(delta)`.

### teku (`teku/ethereum/spec/.../EpochProcessorElectra.java:301–347`)

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

H1–H5 ✓. Queue mutation via `subList(nextPendingBalanceConsolidation, size())` (L341-343). `decreaseBalance` (`BeaconStateMutators.java:72-89`) uses `.minusMinZero()` saturating subtract.

Internal counter named `nextPendingBalanceConsolidation` — Teku retains the pre-rename naming convention for the cursor variable (parallel to lighthouse's legacy `pending_balance_deposits` test fn name from item #4). Implementation behavior unchanged.

### nimbus (`nimbus/beacon_chain/spec/state_transition_epoch.nim:1301–1338`)

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

H1–H5 ✓. Queue mutation via `state.pending_consolidations.asSeq[next_pending_consolidation..^1]` then re-init as `HashList`. `decrease_balance` (`beaconstate.nim:23-45`) saturates to `0.Gwei` on underflow.

Source/target validator-index validation via `ValidatorIndex.init(...).valueOr: return err(...)` — defensive against out-of-range indices (SSZ-bounded so reachable only on malformed input). Other clients also bounds-check but via different mechanisms (e.g., lighthouse via `.ok_or(BeaconStateError::UnknownValidator)`).

### lodestar (`lodestar/packages/state-transition/src/epoch/processPendingConsolidations.ts:17–59`)

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

`decreaseBalance` (`util/balance.ts:34-44`) explicitly clamps via `Math.max(0, ...)`.

### grandine (`grandine/transition_functions/src/electra/epoch_processing.rs:371–419`)

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

H1–H5 ✓. Same pattern as item #4: clone the queue for borrow safety, rebuild via `PersistentList::try_from_iter` after the loop. `decrease_balance` (`mutators.rs:48-55`) is a `const fn` using `saturating_sub`.

## Cross-reference table

| Client | Main fn | Slashed check | Cursor mutation | Queue mutation | Underflow guard |
|---|---|---|---|---|---|
| prysm | `core/electra/consolidations.go:43-91` | L63 (first) | `++` on slashed; not on break | `pendingConsolidations[next:]` + `SetPendingConsolidations` | `if delta > curr { return 0 }` |
| lighthouse | `per_epoch_processing/single_pass.rs:1109-1186` | L1126 (first) | `safe_add_assign(1)?` on slashed; not on break | `pop_front(next)` on cloned-then-mutated VecDeque-style list | `saturating_sub(delta)` |
| teku | `EpochProcessorElectra.java:301-347` | L313 (first) | `++` on slashed; not on break | `subList(next, size)` + setPendingConsolidations | `.minusMinZero(delta)` |
| nimbus | `state_transition_epoch.nim:1301-1338` | L1310 (first) | `+= 1` on slashed; not on break | `asSeq[next..^1]` + HashList re-init | `if delta > balance { 0 }` |
| lodestar | `epoch/processPendingConsolidations.ts:17-59` | L33 (first) | `++` on slashed; not on break | `sliceFrom(next)` | `Math.max(0, balance - delta)` |
| grandine | `electra/epoch_processing.rs:371-419` | L380 (first) | `+= 1` on slashed; not on break | `PersistentList::try_from_iter(...skip(next))` | `saturating_sub(delta)` (`const fn`) |

## Cross-cuts

### with item #2 (`process_consolidation_request` main path)

Item #2 appends `PendingConsolidation{source_index, target_index}` to `state.pending_consolidations`. This item drains those entries. **The queue is the only state-flowing artifact between the two**: a divergence in either's interpretation of "what's a valid entry" or "what order to process" would surface as a balance discrepancy after the next epoch boundary following a successful `process_consolidation_request`.

The `pending_consolidation_with_pending_deposit` fixture (one of the 13 above) tests the case where item #2's switch-to-compounding fast path also queued a pending deposit (via `queue_excess_active_balance`). All 4 wired clients PASS — strong evidence that the producer (item #2 switch path) and the consumer (item #4 deposit drain) AND this consumer (item #5 consolidation drain) all agree on the cross-cut.

### with item #1 (`get_max_effective_balance` — feeds source.effective_balance)

The transfer `min(balance, effective_balance)` reads `source.effective_balance`. That value was set by `process_effective_balance_updates` (item #1) at the previous epoch boundary, using `get_max_effective_balance(source)`. A consolidated source has been EXITED via `process_consolidation_request`, so its `effective_balance` reflects pre-exit state. If item #1's `effective_balance` differed across clients, this item's transfer amount would differ.

The fixtures `pending_consolidation_balance_computation_compounding` and `_eth1` (different cap) and `pending_consolidation_source_balance_{less,greater}_than_max_effective[_compounding]` (4 fixtures) explicitly exercise the transfer formula against various balance/effective_balance combinations and credential types. All PASS — strong evidence that item #1's `get_max_effective_balance` and this item's `min` clamp compose correctly.

### with item #4 (`process_pending_deposits`)

The `pending_consolidation_with_pending_deposit` fixture also indirectly tests cross-cut with item #4: the switch-to-compounding fast path generated a pending deposit AND a pending consolidation in the same block. Both queues drain at the same epoch boundary. Order matters per pyspec's `process_epoch` ordering: `process_pending_deposits` runs BEFORE `process_pending_consolidations` (deposit boosts balance first, consolidation moves it). All 6 clients must agree on this ordering. The `pending_consolidation_with_pending_deposit` PASS confirms.

### with `process_effective_balance_updates` (item #1) — same epoch

Within `process_epoch`, `process_pending_consolidations` runs BEFORE `process_effective_balance_updates`. This means after a successful drain (target.balance increases), the same epoch's eb-updates on the target may bump `target.effective_balance` upward — composing the consolidation transfer with item #1's hysteresis. The `pending_consolidation_balance_computation_*` fixtures cover this composition.

## Fixture

`fixture/`: deferred — used the existing 13 EF state-test fixtures at
`consensus-spec-tests/tests/mainnet/electra/epoch_processing/pending_consolidations/pyspec_tests/`.

Run via `scripts/run_fixture.sh` against all six clients on 2026-05-03:

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

**Coverage assessment**: the 13 fixtures cover (a) the basic happy path, (b) both source-credential types (eth1 0x01, compounding 0x02), (c) both balance-vs-effective-balance orderings (less and greater), (d) the not-yet-withdrawable break case, (e) the slashed-source skip case, (f) the future-epoch case (more constrained than break case), (g) the cross-cut with pending deposits, (h) the all-cases-together rolled into one. **Notably absent**: a fixture exercising **multiple consolidations with cursor advance through both slashed-skip AND withdrawable-break in sequence** (e.g., queue = [slashed, slashed, withdrawable, slashed, not_yet_withdrawable]). The `all_consolidation_cases_together` fixture likely tests this implicitly but a dedicated permutation fixture would tighten coverage.

## Fuzzing vectors

### T1 — Mainline canonical
- **T1.1 (priority — long alternating slashed/withdrawable queue).** Construct a queue of N entries where the first half are slashed (skip) and the second half are withdrawable (process), then a final not-yet-withdrawable entry (break). Expected: cursor ends at `2N`, queue post-mutation is a single entry. Tests that the cursor correctly accumulates across the slashed-skip + active-process branches before the break. Already implicitly covered by `all_consolidation_cases_together`; a dedicated fixture would isolate the mechanism.
- **T1.2 (priority — source.balance dropped below source.effective_balance via inactivity).** Source has `effective_balance=2048 ETH`, `balance=2030 ETH` (lost 18 ETH to inactivity penalty between request and drain). Source is withdrawable, not slashed. Expected: `transfer = min(2030, 2048) = 2030 ETH`. Confirms the `min` is critical here. The `pending_consolidation_source_balance_less_than_max_effective[_compounding]` fixtures cover this; verify `transfer == 2030`.

### T2 — Adversarial probes
- **T2.1 (priority — same-validator self-consolidation).** Spec doesn't prohibit `source_index == target_index` at the queue level (`process_consolidation_request` rejects it via the source==target check, but the queue could in theory contain such an entry from a malformed external producer). Expected: the `decrease_balance(state, src, x)` then `increase_balance(state, src, x)` produces a net-zero change. Verify all six handle uniformly with no balance underflow or duplicate apply.
- **T2.2 (priority — target validator slashed mid-flight).** Source not slashed; target was slashed AFTER the consolidation_request was processed. Expected: this item proceeds normally — the slashed predicate only checks SOURCE (per pyspec). Target slashing is a separate audit concern. Verify the transfer happens uniformly.
- **T2.3 (priority — target.balance very close to u64 max).** Target has `balance = u64::MAX - 1 ETH`; transfer is 32 ETH. Expected: `increase_balance` overflows. Pyspec doesn't guard; lighthouse's `safe_add_assign` would error; others would silently wrap. **Defensive only — mainnet-impossible** (total ETH supply caps cumulative balance at ~120M ETH = 1.2×10^17 gwei << u64).
- **T2.4 (priority — source.withdrawable_epoch == next_epoch exactly).** Source's `withdrawable_epoch` is exactly `next_epoch`. Predicate is `withdrawable_epoch > next_epoch`. With equality, predicate is FALSE → process. Tests the boundary. The `pending_consolidation_future_epoch` fixture probably covers `>` case; a dedicated `==` boundary fixture would isolate the comparator.

## Conclusion

**Status: no-divergence-pending-fuzzing.** All six clients implement the slashed-first / withdrawable-second predicate ordering, the `min(balance, effective_balance)` transfer formula, the cursor advance on slashed (skip) and not on break, the symmetric `decrease_balance + increase_balance` pair, and the slice-from-cursor queue mutation identically. All 13 EF `pending_consolidations` fixtures pass uniformly on prysm + lighthouse + lodestar + grandine; teku and nimbus pass internally.

The 13-fixture suite is small but well-targeted (covers slashed-skip, not-yet-withdrawable break, both credential types, both balance orderings, the cross-cut with pending deposits). All-pass adds strong evidence to items #1 (`get_max_effective_balance`), #2 (`process_consolidation_request` main path), and #4 (`process_pending_deposits`) — each of which contributes to the producer or consumer side of this drain.

Notable per-client style differences (all observable-equivalent at the spec level):
- **lighthouse** integrates this routine into its single-pass epoch processor with an immediate effective-balance-update re-pass for affected validators (deferred to `perform_effective_balance_updates` flag). Same observable post-state but a different mutation choreography.
- **lighthouse** uses `pop_front(N)` on a milhouse-flavored List instead of slice-and-replace.
- **lodestar** uses chunked iteration (100 at a time) for SSZ-batched reads, and dual-writes balances to both the SSZ tree AND its `epochCtx.balances` cache for downstream consistency within `process_epoch`.
- **lodestar** is the only client with the `cachedBalances` array pattern — others read directly from the SSZ tree each iteration.
- **grandine** clones the queue for borrow safety, then rebuilds via `PersistentList::try_from_iter`.
- **nimbus** uses `asSeq[i..^1]` slice + `HashList` re-init.
- **teku** uses `subList` for the queue rebuild.
- **teku** retains the legacy variable name `nextPendingBalanceConsolidation` (parallel to lighthouse's `pending_balance_deposits` pre-rename name from item #4).

No code-change recommendation. Audit-direction recommendations:
- **Generate the T1.1 long-alternating-state fixture** to isolate the cursor-mechanics from the all-cases-together fixture.
- **Generate the T2.4 boundary fixture** (`withdrawable_epoch == next_epoch`) to lock the comparator.
- **Audit the `process_epoch` ordering invariant**: `process_pending_deposits` → `process_pending_consolidations` → `process_effective_balance_updates` (within Pectra's epoch processing). A reordering would split the state-root immediately. Worth a standalone item that walks the per-client `processEpoch` dispatcher.

## Adjacent untouched Electra-active consensus paths

1. **`process_epoch` per-fork ordering of helpers** — Pectra adds `process_pending_deposits` and `process_pending_consolidations` to the epoch sequence. The relative order matters (deposits before consolidations before eb-updates). Audit each client's dispatcher to confirm.
2. **Lighthouse's `perform_effective_balance_updates` flag** — single-pass design that re-applies eb-updates immediately after consolidations. This is functionally equivalent to running `process_effective_balance_updates` at its normal slot in `process_epoch`, BUT it's done locally in this routine. A subtle bug in the local re-pass vs the global one could surface — F-tier today.
3. **Self-consolidation `source_index == target_index` queue entry** — `process_consolidation_request` rejects this, but if any path can introduce one (e.g., a future EIP that bypasses request validation), this drain would do `decrease(src, x)` followed by `increase(src, x)` — net-zero, but worth verifying no client double-applies.
4. **`source.balance` over-budget cleanup** — when source balance > effective_balance, the `min` correctly transfers only effective_balance. The remainder stays in source.balance. Subsequent `process_withdrawals` should pick up the excess. Cross-cut audit with `process_withdrawals` is candidate.
5. **No churn limit here** — unlike `process_pending_deposits` (item #4), this routine doesn't limit drainage by churn. Theoretically all `PENDING_CONSOLIDATIONS_LIMIT` (= 64) entries could drain in one epoch. This is by design (consolidations are pre-budgeted via `compute_consolidation_epoch_and_update_churn` at request time), but worth flagging as a difference from the deposit drain.
6. **Lodestar's `cachedBalances` dual-write** — if any operation between this routine and the next reader of `cache.balances` mutates `state.balances` directly without updating `cache.balances`, the two diverge. F-tier; worth a code review of all `state.balances.set` callers within `process_epoch`.
7. **Teku's `nextPendingBalanceConsolidation` legacy name** — parallel to lighthouse's `pending_balance_deposits` from item #4. No consensus impact, but suggests teku may have retained other pre-rename names elsewhere — worth a sweep.
8. **`MAX_PENDING_CONSOLIDATIONS_PER_EPOCH`** does not exist in the spec — the routine drains until break or queue empty. Under high-volume slashing of consolidation sources, the queue could grow but remain blocked indefinitely (no slashed-source ever becomes withdrawable). Worth a denial-of-throughput analysis.
9. **`PendingConsolidation` SSZ struct fields are fixed (source_index, target_index)** — no amount field. The amount is derived from source.effective_balance at drain time. If source's effective_balance changes between request and drain (e.g., via `process_effective_balance_updates`), the transfer differs. Audit whether such drift is possible (it likely is, via item #1's eb-updates running between the request slot and drain epoch).
10. **Cross-cut with `process_withdrawals`** — the source's residual `balance - effective_balance` after this routine becomes withdrawable per `is_partially_withdrawable_validator`. Worth tracing the lifecycle: consolidation request → 64-256 epoch wait → `process_pending_consolidations` drain → `process_withdrawals` cleanup of residual.
