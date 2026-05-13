---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-12
builds_on: [2, 3, 6, 22]
eips: [EIP-7251, EIP-7732]
splits: [nimbus]
# main_md_summary: nimbus get_pending_balance_to_withdraw OR-folds builder_pending_withdrawals + builder_pending_payments at Gloas+ — rejects voluntary_exit / withdrawal_request / consolidation_request on validators whose index collides with an active builder index
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 23: `get_pending_balance_to_withdraw` (Pectra-NEW exit-gating accessor)

## Summary

`get_pending_balance_to_withdraw(state, validator_index) -> Gwei` is the Pectra-NEW exit-gating accessor. Pectra added the invariant that a `0x02` (compounding) validator with pending partial withdrawals in `state.pending_partial_withdrawals` MUST NOT exit (voluntary exit, EL withdrawal request, or consolidation source) — without the gate, exit would orphan the queued partial withdrawals.

The pyspec is 5 lines (`vendor/consensus-specs/specs/electra/beacon-chain.md:635-642`):

```python
def get_pending_balance_to_withdraw(state: BeaconState, validator_index: ValidatorIndex) -> Gwei:
    return sum(
        withdrawal.amount
        for withdrawal in state.pending_partial_withdrawals
        if withdrawal.validator_index == validator_index
    )
```

Called from THREE distinct sites on the Pectra surface: `process_voluntary_exit` (item #6 — full-equality gate), `process_withdrawal_request` (item #3 — both full-exit `== 0` gate and partial excess-balance subtractor), `process_consolidation_request` (item #2 — source `> 0` rejection).

**Pectra surface**: all six clients implement identical strict-equality semantics — linear scan over `state.pending_partial_withdrawals`, filter by `withdrawal.validator_index == validator_index`, sum the `amount` field, return 0 on no matches. H1–H7 hold.

**Gloas surface (at the Glamsterdam target): nimbus diverges from spec + 5 other clients.** The current Gloas spec (`vendor/consensus-specs/specs/gloas/beacon-chain.md`, v1.7.0-alpha.7-21-g0e70a492d) introduces a SEPARATE builder-side accessor `get_pending_balance_to_withdraw_for_builder(state, builder_index: BuilderIndex)` (`:572-587`) but **does NOT** modify the validator-side `get_pending_balance_to_withdraw`. Commit `601829f1a` (2026-01-05, "Make builders non-validating staked actors", PR #4788) REMOVED an earlier-draft `Modified get_pending_balance_to_withdraw` section when builders were redesigned as non-validating staked actors with their own `state.builders` registry.

Nimbus's `vendor/nimbus/beacon_chain/spec/beaconstate.nim:1541-1559` still implements the now-removed OR-fold: at `consensusFork >= ConsensusFork.Gloas`, the function ALSO sums `state.builder_pending_withdrawals` and `state.builder_pending_payments` entries whose `builder_index` numerically equals the queried `validator_index`. Doc comment at line 1542 points to the removed `#modified-get_pending_balance_to_withdraw` section. This is the same stale-Gloas-spec failure mode as item #22 (`has_compounding_withdrawal_credential`) — both modifications were added in PR #4513 (1b7dedb4a), then removed by PR #4788 (601829f1a), and nimbus carries the stale code from the intermediate spec window.

**Mainnet-everyone-reachable**: validator indices and raw builder indices share a numerical namespace (both `uint64` below `BUILDER_INDEX_FLAG = 2^40`; the FLAG bit is only set when a BuilderIndex is reused as a ValidatorIndex in `Withdrawal.validator_index`). `state.builder_pending_payments` is a fixed-size 64-slot ring buffer (mainnet preset: `2 * SLOTS_PER_EPOCH`) that fills during normal Gloas block production — every accepted builder bid writes a `BuilderPendingPayment.withdrawal.builder_index = <bidder's raw index>` entry, persisting for ~2 epochs until settled. Whenever a validator at index V attempts a voluntary exit (or partial withdrawal request, or consolidation source) AND there's a recent unsettled builder bid by builder with raw index V, nimbus's `get_pending_balance_to_withdraw(state, V)` returns a non-zero sum and rejects the operation — the other five clients (and spec) accept it. State-root mismatch → chain split.

splits: [nimbus] — 1-vs-5. Triggered by normal post-Gloas operation; no attacker capital required.

## Question

Pyspec Pectra-NEW (`vendor/consensus-specs/specs/electra/beacon-chain.md:635-642`):

```python
def get_pending_balance_to_withdraw(state: BeaconState, validator_index: ValidatorIndex) -> Gwei:
    return sum(
        withdrawal.amount
        for withdrawal in state.pending_partial_withdrawals
        if withdrawal.validator_index == validator_index
    )
```

Pyspec Gloas-NEW SEPARATE builder-side accessor (`vendor/consensus-specs/specs/gloas/beacon-chain.md:572-587`):

```python
def get_pending_balance_to_withdraw_for_builder(
    state: BeaconState, builder_index: BuilderIndex
) -> Gwei:
    return sum(
        withdrawal.amount
        for withdrawal in state.builder_pending_withdrawals
        if withdrawal.builder_index == builder_index
    ) + sum(
        payment.withdrawal.amount
        for payment in state.builder_pending_payments
        if payment.withdrawal.builder_index == builder_index
    )
```

Distinct functions, distinct index types (`ValidatorIndex` vs `BuilderIndex`), distinct state fields. The validator-side function is NOT modified at Gloas.

Three recheck questions:
1. Pectra-surface invariants (H1–H7) — do all six clients still implement the strict pending_partial_withdrawals-only semantics?
2. **At Gloas (the new target)**: does any client fold builder-pending state into the validator-side accessor? The earlier item #23 audit (2026-05-02) flagged nimbus's `when consensusFork >= ConsensusFork.Gloas` branch as "pre-emptive Gloas readiness — dead at Pectra". With the spec now removing that modification (commit 601829f1a, 2026-01-05), is this an observable divergence?
3. Reachability: how does the divergence manifest at Gloas activation under normal mainnet traffic?

## Hypotheses

- **H1.** Linear scan over `state.pending_partial_withdrawals`.
- **H2.** Filter by `withdrawal.validator_index == validator_index` (strict equality).
- **H3.** Sum the `amount` field across matching entries.
- **H4.** Returns 0 when no matches (NOT undefined / NOT an error).
- **H5.** Three Pectra-surface caller sites: `process_voluntary_exit` (item #6), `process_withdrawal_request` (item #3), `process_consolidation_request` (item #2).
- **H6.** Voluntary exit gate is `pending_balance == 0` (item #6 H5).
- **H7.** No caching at the function level (each call re-scans linearly).
- **H8.** *(Glamsterdam target — Gloas-NEW separate accessor)*. The Gloas-NEW `get_pending_balance_to_withdraw_for_builder(state, builder_index: BuilderIndex)` exists as a SEPARATE function with different signature, summing `state.builder_pending_withdrawals` + `state.builder_pending_payments` filtered by `builder_index`. Implemented in five clients (nimbus, lodestar, grandine, teku-Gloas TBD, prysm-Gloas TBD) and **missing in lighthouse** (propagation of items #14 H9 / #19 H10 lighthouse Gloas-readiness gap — same shape as item #22 H10).
- **H9.** *(Glamsterdam target — current spec gating of `get_pending_balance_to_withdraw`)*. `get_pending_balance_to_withdraw` is NOT modified at Gloas under the current spec. `vendor/consensus-specs/specs/gloas/beacon-chain.md` contains no `Modified get_pending_balance_to_withdraw` heading; commit `601829f1a` removed it. The validator-side function continues to return ONLY the sum of `pending_partial_withdrawals` entries matching `validator_index`.
- **H10.** *(Glamsterdam target — divergent client)*. **Nimbus diverges from spec + 5 other clients.** `vendor/nimbus/beacon_chain/spec/beaconstate.nim:1551-1557` adds a `when type(state).kind >= ConsensusFork.Gloas` branch that ALSO sums `state.builder_pending_withdrawals` and `state.builder_pending_payments` entries where `builder_index` numerically equals the queried `validator_index`. The other five clients implement strict Pectra semantics at Gloas matching the current spec. Mainnet-reachable on normal post-Gloas traffic — no capital required. Splits = [nimbus].

## Findings

H1–H9 satisfied; **H10 is the active mainnet-glamsterdam divergence.**

### prysm

`vendor/prysm/beacon-chain/state/state-native/getters_validator.go:310-336 PendingBalanceToWithdraw`:

```go
func (b *BeaconState) PendingBalanceToWithdraw(idx primitives.ValidatorIndex) (uint64, error) {
    if b.version < version.Electra {
        return 0, errNotSupported("PendingBalanceToWithdraw", b.version)
    }
    b.lock.RLock()
    defer b.lock.RUnlock()

    // TODO: Consider maintaining this value in the state, if it's a potential bottleneck.
    // This is n*m complexity, but this method can only be called
    // MAX_WITHDRAWAL_REQUESTS_PER_PAYLOAD per slot. A more optimized storage indexing such as a
    // lookup map could be used to reduce the complexity marginally.
    var sum uint64
    for _, w := range b.pendingPartialWithdrawals {
        if w.Index == idx {
            sum += w.Amount
        }
    }
    return sum, nil
}
```

Companion `:338-357 HasPendingBalanceToWithdraw` boolean early-exit variant (consumed by voluntary_exit + consolidation_request — callers that need only "is any pending?" not "how much"):

```go
func (b *BeaconState) HasPendingBalanceToWithdraw(idx primitives.ValidatorIndex) (bool, error) {
    ...
    for _, w := range b.pendingPartialWithdrawals {
        if w.Index == idx && w.Amount > 0 {
            return true, nil
        }
    }
    return false, nil
}
```

**Strict pending_partial_withdrawals-only semantics, no Gloas fold-in.** No fork-conditional branch. `b.pendingPartialWithdrawals` is the Pectra+ state field; for non-Electra+ versions, returns `errNotSupported`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (TODO comment acknowledges caching opportunity). H8 ✓ (separate builder-side path lives in `core/gloas/` for ePBS surface; not in this method). H9 ✓ (no Gloas fold-in). H10: **prysm is on the correct side** of the 1-vs-5 split.

### lighthouse

`vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2650-2663`:

```rust
pub fn get_pending_balance_to_withdraw(
    &self,
    validator_index: usize,
) -> Result<u64, BeaconStateError> {
    let mut pending_balance = 0;
    for withdrawal in self
        .pending_partial_withdrawals()?
        .iter()
        .filter(|withdrawal| withdrawal.validator_index as usize == validator_index)
    {
        pending_balance.safe_add_assign(withdrawal.amount)?;
    }
    Ok(pending_balance)
}
```

`safe_add_assign` provides overflow-checked summation (defensive — realistic overflow is impossible since `PENDING_PARTIAL_WITHDRAWALS_LIMIT × MAX_EFFECTIVE_BALANCE_ELECTRA ≪ u64::MAX`). State-method form. **No Gloas fold-in.**

Callers: `vendor/lighthouse/consensus/state_processing/src/per_block_processing/verify_exit.rs:85` (voluntary exit), `process_operations.rs:546` (withdrawal_request), `process_operations.rs:770` (consolidation_request).

**Lighthouse Gloas-readiness gap (H8 ✗):** no `get_pending_balance_to_withdraw_for_builder` function anywhere in `vendor/lighthouse/` — propagation of items #14 H9 / #19 H10 / #22 H10 lighthouse Gloas-ePBS gap. At Gloas, lighthouse cannot implement the builder-side voluntary-exit path (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1641-1653 is_builder_index(...) → ... assert get_pending_balance_to_withdraw_for_builder == 0 → initiate_builder_exit`) because the predicate `is_builder_index` and the accessor `get_pending_balance_to_withdraw_for_builder` are both absent. This is a separate (broader) Gloas readiness gap, not nimbus's predicate divergence.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. **H8 ✗** (`get_pending_balance_to_withdraw_for_builder` missing — items #14/#19/#22 propagation). H9 ✓. H10: lighthouse is on the **correct side** of nimbus's H10 split for THIS item's surface (`get_pending_balance_to_withdraw` returns pending_partial_withdrawals-only); the Gloas-readiness gap at H8 is a separate issue.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/BeaconStateAccessorsElectra.java:71-77 getPendingBalanceToWithdraw`:

```java
public UInt64 getPendingBalanceToWithdraw(
    final BeaconStateElectra state, final int validatorIndex) {
  return state.getPendingPartialWithdrawals().stream()
      .filter(withdrawal -> withdrawal.getValidatorIndex().intValue() == validatorIndex)
      .map(PendingPartialWithdrawal::getAmount)
      .reduce(UInt64.ZERO, UInt64::plus);
}
```

Companion `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/common/util/ValidatorsUtil.java:180-186` `.reduce(UInt64::plus).orElse(UInt64.ZERO)` variant — both produce identical results. Code duplication concern documented in prior audit; carried forward.

**No Gloas helper override** — `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/helpers/BeaconStateAccessorsGloas.java` (if present) doesn't override this method; the Electra implementation is inherited at Gloas. Strict pending_partial_withdrawals-only.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (teku has builder-side processing in `versions/gloas/`). H9 ✓ (no override). H10: **teku is on the correct side** of the split.

### nimbus

`vendor/nimbus/beacon_chain/spec/beaconstate.nim:1541-1559`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-beta.0/specs/electra/beacon-chain.md#new-get_pending_balance_to_withdraw
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-beta.0/specs/gloas/beacon-chain.md#modified-get_pending_balance_to_withdraw
func get_pending_balance_to_withdraw*(
    state: electra.BeaconState | fulu.BeaconState | gloas.BeaconState,
    validator_index: ValidatorIndex): Gwei =
  var pending_balance: Gwei
  for withdrawal in state.pending_partial_withdrawals:
    if withdrawal.validator_index == validator_index:
      pending_balance += withdrawal.amount

  when type(state).kind >= ConsensusFork.Gloas:
    for withdrawal in state.builder_pending_withdrawals:
      if withdrawal.builder_index == validator_index:
        pending_balance += withdrawal.amount
    for payment in state.builder_pending_payments:
      if payment.withdrawal.builder_index == validator_index:
        pending_balance += payment.withdrawal.amount

  pending_balance
```

**This is the H10 divergence.** The doc comment at line 1542 references `#modified-get_pending_balance_to_withdraw` in v1.6.0-beta.0 — added by PR #4513 (commit `1b7dedb4a`, "eip7732: consider builder pending payments for pending balance to withdraw"), then REMOVED by PR #4788 (commit `601829f1a`, 2026-01-05, "Make builders non-validating staked actors") when builders became a separate registry. The current Gloas spec at v1.7.0-alpha.7-21-g0e70a492d has no `Modified get_pending_balance_to_withdraw` heading — the function is inherited unchanged from Electra.

Critical: the `when type(state).kind >= ConsensusFork.Gloas` branch compares `withdrawal.builder_index` (type `BuilderIndex` = `uint64`, stored as a RAW builder index without the `BUILDER_INDEX_FLAG = 2^40` bit set) to `validator_index` (type `ValidatorIndex` = `uint64`). Both operands are `uint64` and the `==` comparison is purely numerical. A raw BuilderIndex value `b` (range `0..BUILDER_REGISTRY_LIMIT-1 = 0..2^40-1`) can collide numerically with a ValidatorIndex `v` whenever `b == v` — and both registries grow from index 0.

A SEPARATE Gloas-NEW function `get_pending_balance_to_withdraw_for_builder` exists at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:3085-3097` with the correct builder-side semantics:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.7.0-alpha.1/specs/gloas/beacon-chain.md#new-get_pending_balance_to_withdraw_for_builder
func get_pending_balance_to_withdraw_for_builder(
    state: gloas.BeaconState, builder_index: BuilderIndex): Gwei =
  var pending_balance: Gwei
  for withdrawal in state.builder_pending_withdrawals:
    if withdrawal.builder_index == builder_index:
      pending_balance += withdrawal.amount
  for payment in state.builder_pending_payments:
    if payment.withdrawal.builder_index == builder_index:
      pending_balance += payment.withdrawal.amount
  pending_balance
```

The builder-side function is correct (spec-conformant for H8). But the validator-side function ALSO sums the same builder fields — this is the OR-fold that the spec removed.

**Caller-site cascade.** Nimbus's `get_pending_balance_to_withdraw` is invoked at three Gloas-active sites:

- `vendor/nimbus/beacon_chain/spec/state_transition_block.nim:486-488` — voluntary exit gate (`return err("Exit: still has pending withdrawals")` if non-zero).
- `vendor/nimbus/beacon_chain/spec/state_transition_block.nim:590-611` — withdrawal_request: line 595 `if pending_balance_to_withdraw == 0.Gwei:` for full-exit gate; line 603 `static(MIN_ACTIVATION_BALANCE.Gwei) + pending_balance_to_withdraw` as subtractor for the partial excess computation; line 611 caps the partial withdrawal amount.
- `vendor/nimbus/beacon_chain/spec/state_transition_block.nim:737` — consolidation_request: `if get_pending_balance_to_withdraw(state, source_index) > 0.Gwei:` early-rejection.

For each caller, when the queried validator's index `V` numerically collides with the raw builder index of any unsettled entry in `state.builder_pending_withdrawals` or `state.builder_pending_payments`:
- nimbus over-counts → operation is rejected (or under-credited for the partial-withdrawal subtractor).
- the other 5 clients (and spec) compute the validator-only sum → operation succeeds.

H1 ✓. H2 ✓. H3 ✓ (Pectra surface). H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (separate function exists). **H9 ✗** (Gloas OR-fold is stale relative to current spec). **H10 ✗ — splits=[nimbus]**.

### lodestar

`vendor/lodestar/packages/state-transition/src/util/validator.ts:167-179 getPendingBalanceToWithdraw`:

```typescript
export function getPendingBalanceToWithdraw(
  state: CachedBeaconStateElectra | CachedBeaconStateGloas,
  validatorIndex: ValidatorIndex
): number {
  let total = 0;
  for (const item of state.pendingPartialWithdrawals.getAllReadonly()) {
    if (item.validatorIndex === validatorIndex) {
      total += Number(item.amount);
    }
  }

  return total;
}
```

Type signature `CachedBeaconStateElectra | CachedBeaconStateGloas` confirms single implementation across both forks. **No Gloas fold-in.** BigInt→Number coercion via `Number(item.amount)` (forward-fragile concern documented in prior audit; carried forward).

Separate builder-side `getPendingBalanceToWithdrawForBuilder` (Gloas-NEW) — invoked from `vendor/lodestar/packages/state-transition/src/block/processVoluntaryExit.ts:100` (`if (getPendingBalanceToWithdrawForBuilder(state, builderIndex) !== 0) { ... }`). Clean separation.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (TODO comment at `processWithdrawalRequest.ts:44` re caching). H8 ✓. H9 ✓. H10: **lodestar is on the correct side** of the split.

### grandine

`vendor/grandine/helper_functions/src/accessors.rs:982-992`:

```rust
#[must_use]
pub fn get_pending_balance_to_withdraw<P: Preset>(
    state: &impl PostElectraBeaconState<P>,
    validator_index: ValidatorIndex,
) -> Gwei {
    state
        .pending_partial_withdrawals()
        .into_iter()
        .filter(|withdrawal| withdrawal.validator_index == validator_index)
        .map(|withdrawal| withdrawal.amount)
        .sum()
}
```

Iterator chain `.filter().map().sum()` over pending_partial_withdrawals. Generic over `PostElectraBeaconState<P>` (covers Electra/Fulu/Gloas via trait bound). **No Gloas fold-in.**

Separate Gloas-NEW `get_pending_balance_to_withdraw_for_builder` at `:995-1014` with `PostGloasBeaconState<P>` trait bound, summing `builder_pending_withdrawals` + `builder_pending_payments` by `builder_index`. Clean separation.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10: **grandine is on the correct side** of the split.

## Cross-reference table

| Client | `get_pending_balance_to_withdraw` Gloas behaviour | `get_pending_balance_to_withdraw_for_builder` | H10 verdict |
|---|---|---|---|
| prysm | strict pending_partial_withdrawals only (`getters_validator.go:317-336`) | builder-side path in `core/gloas/` (separate); none in this method | ✓ spec-conformant |
| lighthouse | strict pending_partial_withdrawals only (`beacon_state.rs:2650-2663`) | **MISSING** (items #14 H9 / #19 H10 / #22 H10 propagation) | ✓ at this surface; broader H8 gap |
| teku | strict pending_partial_withdrawals only (`BeaconStateAccessorsElectra.java:71-77`); no Gloas helper override | builder-side path in `versions/gloas/` | ✓ spec-conformant |
| **nimbus** | **OR-folded with `builder_pending_withdrawals` + `builder_pending_payments` at `consensusFork >= ConsensusFork.Gloas`** (`beaconstate.nim:1541-1559`) | separate function present (`beaconstate.nim:3085-3097`); correct in isolation but the validator-side OR-fold makes the original wrong | **✗ DIVERGES from spec + 5 others** |
| lodestar | strict pending_partial_withdrawals only (`util/validator.ts:167-179`) | separate `getPendingBalanceToWithdrawForBuilder` (Gloas-NEW), used from `processVoluntaryExit.ts:100` | ✓ spec-conformant |
| grandine | strict pending_partial_withdrawals only (`accessors.rs:982-992`) | separate `:995-1014` Gloas-NEW with `PostGloasBeaconState<P>` trait bound | ✓ spec-conformant |

## Empirical tests

### Pectra-surface implicit coverage (carried forward from prior audit)

`get_pending_balance_to_withdraw` is exercised IMPLICITLY via every Pectra-surface caller's EF fixture set:

| Item | Caller | Fixtures × wired clients |
|---|---|---|
| #2 process_consolidation_request | source-gate `> 0` rejection | 10 × 4 = 40 |
| #3 process_withdrawal_request | full-exit `== 0` gate + partial subtractor | 21 × 4 = 84 |
| #6 process_voluntary_exit | full-equality `== 0` gate | 8 × 4 = 32 |

**Cumulative Pectra implicit cross-validation evidence**: ~39 unique fixtures × 4 wired clients = **~156 EF fixture PASSes** flow through this accessor. No divergence surfaced on the Pectra surface.

The full EIP-6110 `deposit_transition__*` fixture series (27/27 PASS on 3 wired clients per prior audit) continues to pass per the per-client checks — that audit closed the EIP-6110 cutover end-to-end at Pectra, and the cutover state machine is unchanged at Gloas (only the routing of `process_deposit_request` from `process_operations` to `apply_parent_execution_payload` is new, per item #14 H9).

### Gloas-surface

No Gloas fixtures wired for this accessor yet. H9 / H10 are source-only.

The consensus-specs Gloas test corpus (`vendor/consensus-specs/tests/core/pyspec/eth2spec/test/gloas/`) does not currently include a fixture that places a `BuilderPendingPayment` with a specific `builder_index` value AND tests `process_voluntary_exit` / `process_withdrawal_request` / `process_consolidation_request` on a validator with the same numerical index. This gap is exactly the implicit coverage that would surface nimbus's H10 divergence.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — dedicated EF fixture set for the validator-side accessor).** Pure-function fuzz: vary `state.pending_partial_withdrawals` contents (entries with assorted `validator_index` and `amount` values), query at each existing `validator_index`, assert the cross-client sum is identical. Crucial cross-client byte-level equivalence test. **At Gloas state**: also populate `state.builder_pending_withdrawals` and `state.builder_pending_payments` with entries whose `builder_index` collides with the queried validator index. Expected output (per spec): same as Pectra (builder fields ignored). **Nimbus would return a different value** → surfaces H10 at the predicate level.
- **T1.2 (priority — dedicated EF fixture set for `get_pending_balance_to_withdraw_for_builder`).** Independent cross-client test of the Gloas-NEW builder-side accessor. Lighthouse would fail entirely (function missing — H8).

#### T2 — Adversarial probes
- **T2.1 (Glamsterdam-target — H10 voluntary-exit fork on raw-index collision).** Gloas state. Populate `state.builder_pending_payments[i]` with `withdrawal.builder_index = V`, `withdrawal.amount = X > 0`, where `V` is a valid validator index AND `state.validators[V]` has empty `pending_partial_withdrawals`. Submit a signed `VoluntaryExit` for validator `V`. Expected:
  - spec + 5 clients: `pending_balance_to_withdraw(V) = 0` → exit succeeds → `state.validators[V].exit_epoch` set.
  - nimbus: `pending_balance_to_withdraw(V) = X > 0` → `return err("Exit: still has pending withdrawals")` → block REJECTED.
  - **State-root divergence** between nimbus and the other 5 clients on the post-block state.

- **T2.2 (Glamsterdam-target — H10 withdrawal_request full-exit fork).** Same setup; submit a `WithdrawalRequest` with `amount = FULL_EXIT_REQUEST_AMOUNT` for validator `V`. Expected: spec + 5 clients enqueue the full exit; nimbus's full-exit gate `== 0` fails, request silently DROPPED (per item #3's silent-drop semantics).

- **T2.3 (Glamsterdam-target — H10 withdrawal_request partial-amount fork).** Same setup; submit a partial `WithdrawalRequest` with `amount = 1 ETH`. The partial path computes `excess = balance - MIN_ACTIVATION_BALANCE - pending_balance_to_withdraw`. spec: `excess = balance - 32 - 0 = balance - 32`; nimbus: `excess = balance - 32 - X` (smaller). The queued partial withdrawal amount differs → state root differs.

- **T2.4 (Glamsterdam-target — H10 consolidation_request source-gate fork).** Gloas state, same collision setup. Submit a `ConsolidationRequest` with `source_pubkey = state.validators[V].pubkey`. spec + 5 clients: `pending_balance(V) = 0`, consolidation proceeds; nimbus: `pending_balance(V) = X > 0`, consolidation early-returns (silent drop). Divergence on the consolidation processing.

- **T2.5 (Glamsterdam-target — natural-traffic collision likelihood).** Run a Gloas devnet with a population of builders bidding for blocks (so `builder_pending_payments` fills with diverse `builder_index` entries). Periodically submit voluntary exits for validators at low indices (0, 1, 2, ...). Count divergent block-acceptance decisions between nimbus and other clients. Expected: divergence rate proportional to collision probability ≈ `(number of distinct unsettled-builder raw indices) / (number of validator indices being exit-targeted)`.

- **T2.6 (Glamsterdam-target — builder vs validator index disambiguation).** Verify that nimbus correctly disambiguates "is this query a validator query or a builder query?" by walking the caller types. All three Gloas-active callers (`process_voluntary_exit` validator branch, `process_withdrawal_request`, `process_consolidation_request`) pass a `ValidatorIndex` and expect validator-only semantics. nimbus's failure is exactly the loss of this disambiguation.

## Mainnet reachability

**impact: mainnet-glamsterdam.** Triggered by normal post-Gloas operation; no attacker capital required.

**Mechanism (1-vs-5 split at Gloas+, splits=[nimbus]):**

1. **Setup (continuously, post-Gloas).** During normal Gloas block production, `apply_parent_execution_payload` writes `BuilderPendingPayment` entries into `state.builder_pending_payments` (a fixed-size ring buffer of `2 * SLOTS_PER_EPOCH = 64` slots on mainnet preset; `vendor/consensus-specs/specs/gloas/beacon-chain.md:1062-1065`). Each entry records:
   ```python
   pending_payment = BuilderPendingPayment(
       weight=...,
       withdrawal=BuilderPendingWithdrawal(
           fee_recipient=...,
           amount=bid.value,
           builder_index=bid.builder_index,  # RAW BuilderIndex, no FLAG bit
       ),
   )
   ```
   (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1460-1466`)
   
   Entries are settled (reset to defaults) by `settle_builder_payment` (`:908`) and `update_builder_pending_withdrawals` (`:1062`) at the next-epoch boundary — so at any moment, up to 64 slots' worth of unsettled entries exist with `builder_index` values reflecting whichever builders bid for those slots.

2. **Index namespace overlap.** Both `BuilderIndex` and `ValidatorIndex` are `uint64` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:128`). The `BUILDER_INDEX_FLAG = uint64(2**40)` (`:137`) bit is set when a BuilderIndex is reused as a ValidatorIndex in `Withdrawal.validator_index` (per `is_builder_index` at `:464-468`), but the FLAG is NOT set on the `BuilderPendingWithdrawal.builder_index` storage form — that field stores the raw BuilderIndex (range `0..BUILDER_REGISTRY_LIMIT-1 = 0..2^40-1`). Validator indices grow from 0 sequentially. Raw builder indices grow from 0 sequentially (per `apply_deposit_for_builder` at `:1574-1582` — new builders get the next free index).
   
   **Overlap is unavoidable**: validators at indices `0, 1, 2, ...` exist (pre-Gloas, ongoing); raw builders at indices `0, 1, 2, ...` accumulate post-Gloas. Whenever a builder at raw index `V` bids for a slot AND validator at index `V` exists AND `V`'s `pending_partial_withdrawals` is empty, the divergence-trigger condition holds.

3. **Trigger window.** A builder's bid creates an unsettled `BuilderPendingPayment` entry for ~2 epochs (~12 minutes mainnet preset) until settlement. During this window, ANY validator with index matching the bidder's raw index has nimbus's `get_pending_balance_to_withdraw` returning a non-zero sum.

4. **Operation rejection.** During the trigger window, if validator `V` (matching builder raw index) attempts:
   - **`SignedVoluntaryExit`**: nimbus returns `err("Exit: still has pending withdrawals")` (`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:486-488`). The block containing the exit is REJECTED by nimbus, accepted by the other 5 clients.
   - **`WithdrawalRequest` with full-exit amount**: nimbus drops the request (`processWithdrawalRequest` returns from the full-exit gate); other 5 clients enqueue the exit.
   - **`WithdrawalRequest` with partial amount**: nimbus computes a smaller excess (`balance - MIN_ACTIVATION_BALANCE - builder_sum`); other 5 clients compute `balance - MIN_ACTIVATION_BALANCE`. The queued partial withdrawal amount differs → divergent `state.pending_partial_withdrawals` contents → state root mismatch.
   - **`ConsolidationRequest` with source = V**: nimbus early-returns from the source-gate (`if pending_balance > 0: return`); other 5 clients process the consolidation.

5. **Resulting chain split.** In all four cases, the post-block state root computed by nimbus differs from the other 5 clients. nimbus rejects (or processes-divergently) any block containing such an operation. Other clients accept the block as valid.

**Reachability characterization:**
- **Cost**: ZERO. No attacker capital. The trigger condition arises from normal Gloas operation (any validator at low index performing any of the three gated operations).
- **Trigger frequency**: continuously. As builders bid for slots, `builder_pending_payments` continuously refreshes with new `builder_index` values. Every voluntary_exit / withdrawal_request / consolidation_request on a validator at index `V` is a roll of the dice — the divergence fires iff some unsettled entry has `builder_index = V`.
- **Probability**: bounded by `(number of distinct unsettled builders' raw indices) / (max validator index targeted)`. With a healthy Gloas builder market (say ≥ 64 distinct builders bidding regularly), the unsettled-builder set covers ~64 raw indices at any moment. For voluntary exits among validators with indices in the same range (low indices = early validators), the probability is ~64 / (number of low-index validators). Even at 1% probability per operation, every ~100 voluntary exits triggers a fork. With ~thousands of voluntary exits per epoch on mainnet, **multiple divergence events per epoch are expected**.

**Mitigation:** in `vendor/nimbus/beacon_chain/spec/beaconstate.nim:1541-1559`, remove the `when type(state).kind >= ConsensusFork.Gloas` block (`:1551-1557`). The corrected function becomes the Pectra/Electra body unconditionally:

```nim
func get_pending_balance_to_withdraw*(
    state: electra.BeaconState | fulu.BeaconState | gloas.BeaconState,
    validator_index: ValidatorIndex): Gwei =
  var pending_balance: Gwei
  for withdrawal in state.pending_partial_withdrawals:
    if withdrawal.validator_index == validator_index:
      pending_balance += withdrawal.amount
  pending_balance
```

Update the doc comment URL at line 1542 to drop the stale `#modified-get_pending_balance_to_withdraw` reference (the modification was reverted in spec). The Gloas-NEW separate accessor at `:3085-3097` is already correct and remains; callers needing the builder-side query use it directly (e.g., the builder-exit branch of `process_voluntary_exit`).

**Detection (operational):** monitor cross-client state-root agreement after Gloas activation. Any block containing a voluntary_exit / withdrawal_request / consolidation_request where nimbus disagrees with the supermajority is a candidate H10 trigger. Telemetry: log `(validator_index, get_pending_balance_to_withdraw(state, validator_index))` from each client for every block that contains these operations; cross-compare.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Pectra-surface invariants (H1–H7) hold across all six. H8 (Gloas-NEW `get_pending_balance_to_withdraw_for_builder`) holds for five clients; **lighthouse lacks the function** (only the validator-side accessor exists) — propagation of items #14 H9 / #19 H10 / #22 H10 lighthouse Gloas-readiness gap, separate from this item's nimbus divergence.

**Glamsterdam-target finding (H10 — mainnet-glamsterdam divergence).** Nimbus's `get_pending_balance_to_withdraw` at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:1541-1559` is fork-gated to ALSO sum `state.builder_pending_withdrawals` and `state.builder_pending_payments` entries where `builder_index` numerically equals the queried `validator_index` at `consensusFork >= ConsensusFork.Gloas`. The current Gloas spec (v1.7.0-alpha.7-21-g0e70a492d) does NOT modify this function — commit `601829f1a` (PR #4788, 2026-01-05, "Make builders non-validating staked actors") REMOVED an earlier-draft `Modified get_pending_balance_to_withdraw` section when builders were redesigned as non-validating staked actors in a separate `state.builders` registry. Nimbus's stale code references the now-removed spec section by URL in the doc comment at line 1542.

This is the **same stale-Gloas-spec failure mode as item #22** (`has_compounding_withdrawal_credential`): both modifications were added in PR #4513 (commit `1b7dedb4a`) for the EIP-7732 ePBS draft, then removed by PR #4788 (commit `601829f1a`) when the design switched to separate-registry builders. Nimbus carries the stale OR-fold from the intermediate spec window.

The divergence is **mainnet-glamsterdam-reachable on normal post-Gloas traffic** — no attacker capital required:
- `state.builder_pending_payments` continuously fills with `builder_index` entries during normal block production (~64 unsettled entries at any moment on mainnet preset).
- `BuilderIndex` (raw, stored without the `BUILDER_INDEX_FLAG`) and `ValidatorIndex` share the `uint64 < 2^40` namespace. Both registries grow from 0. Numerical collisions are guaranteed for any low-index validator.
- The accessor is called from THREE Gloas-active sites: voluntary exit (full-equality `== 0` gate), withdrawal_request (full-exit gate + partial excess-balance subtractor), consolidation_request (source `> 0` rejection).
- For each operation, nimbus over-counts → operation rejected (or under-credited for the partial-withdrawal subtractor) → state root diverges from the other 5 clients → chain split.

Splits = [nimbus]; 1-vs-5.

**Expected divergence rate post-Gloas**: at a healthy builder market (~tens of distinct active builders bidding regularly) and typical voluntary-exit volumes (~thousands per epoch), the collision probability is sufficient to produce **multiple cross-client divergence events per epoch**. The fork is essentially structural — no specific attacker action required; normal mainnet operation continuously re-triggers it.

**Two other Glamsterdam-target observations from the recheck**:
- **lighthouse Gloas-readiness gap (H8 ✗)**: `get_pending_balance_to_withdraw_for_builder` is missing from `vendor/lighthouse/`. This is the broader Gloas ePBS gap (items #14 H9 / #19 H10 / #22 H10), not nimbus's predicate divergence. Lighthouse is on the *correct* side of nimbus's H10 split at this item's surface (validator-side accessor returns pending_partial_withdrawals-only).
- **teku two-variant code duplication**: `BeaconStateAccessorsElectra.getPendingBalanceToWithdraw` and `ValidatorsUtil.getPendingBalanceToWithdraw` are line-equivalent but slightly different idioms (`reduce(ZERO, plus)` vs `reduce(plus).orElse(ZERO)`). Carried forward from prior audit; forward-fragility hedge.

**Code-change recommendation (nimbus)**: in `vendor/nimbus/beacon_chain/spec/beaconstate.nim:1541-1559`, remove the `when type(state).kind >= ConsensusFork.Gloas` block (lines 1551-1557). The Gloas-NEW separate accessor at `:3085-3097` is already correct and is what the builder-exit branch of `process_voluntary_exit` should consult. Update the doc comment URL at line 1542 to point to the current Electra spec section only (drop the `#modified-get_pending_balance_to_withdraw` link).

**Audit-direction recommendations**:
- **Mainnet pre-Gloas monitoring**: deploy a CL beacon-state RPC poller that, post-Gloas, cross-compares `get_pending_balance_to_withdraw(state, V)` results across clients for each `V` queried in block-processing. Any disagreement is an immediate H10 trigger signal.
- **Generate dedicated EF fixture sets** for both accessors (T1.1, T1.2) — cross-client byte-level equivalence test.
- **Generate dedicated state-transition fixtures** for voluntary_exit / withdrawal_request / consolidation_request on a `0x02`-credentialled validator with builder-pending-payments under raw-index collision (T2.1-T2.4) — directly cross-validates H10.
- **Sister-item audit: lighthouse Gloas builder-exit path** — `get_pending_balance_to_withdraw_for_builder` missing, plus the broader `process_voluntary_exit` builder branch (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1641-1653`). Likely propagates from items #14 H9 / #19 H10.
- **Pattern audit: hunt for other stale Gloas-spec modifications in nimbus**. Items #22 and #23 both follow the PR #4513 → PR #4788 pattern. Other functions that were added and then removed in the same revert window may also be stale in nimbus. Candidates: `is_active_builder`, `has_builder_withdrawal_credential` (item #22 sister), the original "builders are validators" body of `process_deposit_request`.
- **Spec-clarification PR (consensus-specs)**: add a `Removed in <commit>` note at the top of `get_pending_balance_to_withdraw` (Electra) and `has_compounding_withdrawal_credential` (Electra) explicitly stating "this function is NOT modified at Gloas; an earlier-draft `Modified` section was removed in PR #4788. See `get_pending_balance_to_withdraw_for_builder` / `is_builder_withdrawal_credential` for the new builder-side predicates." Mitigates the stale-comment failure mode for any client that bookmarks intermediate spec versions.

## Cross-cuts

### With item #6 (`process_voluntary_exit`)

Item #6's audit closed the Pectra-surface H5 invariant (`assert pending_balance == 0` for voluntary exits at Electra+). The Gloas-modified `process_voluntary_exit` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1631-1668`) preserves this assert for the validator branch (line 1663) and adds a NEW builder branch (lines 1642-1653) that uses `get_pending_balance_to_withdraw_for_builder`. Nimbus's H10 divergence corrupts the validator branch; the builder branch (using the separate accessor at `:3085`) is correct.

### With item #3 (`process_withdrawal_request`)

Item #3's audit closed two Pectra-surface uses of `get_pending_balance_to_withdraw`: the full-exit equality gate (`== 0`) and the partial-amount subtractor (`MIN_ACTIVATION_BALANCE + pending_balance_to_withdraw`). Both are present at Gloas (function inherited from Electra). Nimbus's H10 divergence corrupts BOTH uses: full-exit rejected when builder collides; partial amount under-credited.

### With item #2 (`process_consolidation_request`)

Item #2's audit closed the source-gate use (`if pending_balance > 0: return`). At Gloas, `process_consolidation_request` is REMOVED from `process_operations` and re-wired via `apply_parent_execution_payload` (per items #21, #22 audits). The function body itself is unchanged — still uses `get_pending_balance_to_withdraw(state, source_index)`. Nimbus's H10 divergence corrupts this source-gate.

### With item #22 (`has_compounding_withdrawal_credential`)

Item #22 found nimbus's `has_compounding_withdrawal_credential` is stale-Gloas-aware via the same PR #4513 → PR #4788 revert window. **This is the same failure mode in a different function.** Both stem from the v1.6.0-beta.0 → v1.7.0-alpha.x spec churn around builder-as-validator semantics. Both should be fixed together.

### With Gloas `state.builder_pending_payments` lifecycle (item #7 cross-cut)

`state.builder_pending_payments` is a fixed-size 64-slot ring buffer initialized at `upgrade_to_gloas` (`vendor/consensus-specs/specs/gloas/fork.md:179`) and written by `process_execution_payload_bid` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1460`). Settled by `settle_builder_payment` (`:908`) at the next-epoch boundary. The ring-buffer semantics mean unsettled entries persist for ~64 slots = 2 epochs = ~12 minutes mainnet. Nimbus's H10 over-counts during this window for any validator whose index matches a recent bidder's raw index.

## Adjacent untouched

1. **Nimbus fix**: remove the `when type(state).kind >= ConsensusFork.Gloas` block from `vendor/nimbus/beacon_chain/spec/beaconstate.nim:1551-1557`.
2. **EF fixture set for the validator-side accessor** — pure-function fuzz with Gloas state containing builder-pending entries at collision indices (T1.1).
3. **EF fixture set for `get_pending_balance_to_withdraw_for_builder`** (T1.2) — independent cross-client test; surfaces lighthouse's H8 gap.
4. **EF state-transition fixtures: voluntary_exit / withdrawal_request / consolidation_request on raw-index-collision Gloas state** (T2.1-T2.4) — directly cross-validates H10.
5. **Pattern audit: hunt for other stale Gloas-spec modifications in nimbus** — PR #4513 → PR #4788 revert window. Candidates: builder-related predicates and accessors that were added and then removed when builders became non-validating staked actors.
6. **Sister audit: lighthouse Gloas builder-exit path** — `get_pending_balance_to_withdraw_for_builder` + builder branch of `process_voluntary_exit`.
7. **Sister audit: teku two-variant code duplication** — `BeaconStateAccessorsElectra` vs `ValidatorsUtil` `getPendingBalanceToWithdraw`.
8. **Spec-clarification PR**: add `Removed in <commit>` notes for functions that were modified-then-reverted in the v1.6.0-beta.0 → v1.7.0 churn, to prevent the stale-comment failure mode.
9. **Telemetry post-Gloas**: cross-client divergence monitor on `get_pending_balance_to_withdraw` results per validator_index per block.
10. **Caching opportunity** (carried forward from prior audit): both prysm and lodestar TODO acknowledge the O(N) scan. Maintain a `Map<ValidatorIndex, Gwei>` cache, invalidated on item #3's queue insertion and item #12's queue consumption. F-tier today (bounded caller frequency); useful when validator count grows or `PENDING_PARTIAL_WITHDRAWALS_LIMIT` increases.
11. **`amount > 0` filter divergence** (carried forward): prysm's `HasPendingBalanceToWithdraw` requires `amount > 0` for early-exit; the summing path doesn't filter. Reconcile cross-client.
12. **lighthouse lcli `pre_state.all_caches_built()` panic** (carried forward): `lcli transition-blocks` panics on deposit_transition fixtures because the test pre-state doesn't pre-build caches. Lcli runner improvement, not a real divergence.
