---
status: fuzzed
impact: synthetic-state
last_update: 2026-05-14
builds_on: [22, 23, 28, 57]
eips: [EIP-7732]
splits: [lodestar]
# main_md_summary: lodestar emits Gloas builder sweep withdrawal with queue-decremented cached balance instead of pre-block builder.balance; only surfaces on a hand-built or fuzz-generated state since process_voluntary_exit precondition blocks the queue+sweep collision in honest block production
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 67: Builder withdrawal flow — `state.builder_pending_withdrawals` lifecycle + 0x03 sweep + apply_withdrawals dispatch

## Summary

Gloas introduces a separate withdrawal lane for builders (0x03 credentials). `state.builder_pending_withdrawals` queues per-bid builder payments. `get_builder_withdrawals` drains the queue head; `get_builders_sweep_withdrawals` performs the full-exit sweep over `state.builders`; `apply_withdrawals` dispatches on `is_builder_index(validator_index)` to mutate `state.builders[i].balance` or `state.balances[i]`. `process_withdrawals` orchestrates and short-circuits when the parent block was EMPTY.

**Five of six clients (prysm, lighthouse, teku, nimbus, grandine) implement the spec literally**: `get_builders_sweep_withdrawals` reads `state.builders[builder_index].balance` directly from state and emits sweep `Withdrawal.amount = builder.balance`.

**Lodestar deviates** at `vendor/lodestar/packages/state-transition/src/block/processWithdrawals.ts:188-243`: it maintains a per-builder cache `builderBalanceAfterWithdrawals: Map<BuilderIndex, number>` populated by `getBuilderWithdrawals` (with the post-queue-drain balance) and **then read by `getBuildersSweepWithdrawals`** for the sweep amount. When a builder simultaneously has (a) entries in `state.builder_pending_withdrawals` AND (b) is sweep-eligible (`withdrawable_epoch <= current_epoch AND balance > 0`), lodestar emits sweep amount = `pre_balance − sum(queue_drain_amounts)` instead of `pre_balance`.

This produces a different `state.payload_expected_withdrawals` (and therefore different state root, different EL block-hash) for the same input state. Both spec semantics and lodestar's caching converge to `balance = 0` after `apply_withdrawals`, but the **emitted Withdrawal records (and consequently the EL-minted amounts) differ**.

The spec note at `beacon-chain.md:1357-1369` acknowledges the broader supply-asymmetry concern (the immediate-deduct design choice that prevents queue-application drift) but does not address the queue+sweep collision case lodestar's caching arguably mitigates. Lodestar may have intentionally diverged to preserve a stronger supply invariant; alternatively the cache is a bug. The colliding state has been constructed empirically (see the demo runs below); however, honest block production cannot reach it (see the Reachability section), so this is impact `synthetic-state` rather than mainnet-reachable.

All other aspects of the builder withdrawal flow are spec-conformant across all 6 clients:
- `process_withdrawals` early-return on parent-EMPTY (`latest_block_hash != latest_execution_payload_bid.block_hash`).
- `get_builder_withdrawals` queue-drain semantics + `MAX_WITHDRAWALS_PER_PAYLOAD - 1` reservation.
- `apply_withdrawals` saturating subtraction (`min(amount, balance)`) on builder branch.
- `update_builder_pending_withdrawals` slice-off-processed semantics.
- `update_next_withdrawal_builder_index` modular cursor advance.
- `is_builder_index` / `convert_builder_index_to_validator_index` / `convert_validator_index_to_builder_index` BUILDER_INDEX_FLAG bit-ops.

## Question

Pyspec at `vendor/consensus-specs/specs/gloas/beacon-chain.md` (key references):

**`process_withdrawals`** (line 1372-1397):

```python
def process_withdrawals(state: BeaconState) -> None:
    # [New in Gloas:EIP7732]
    # Return early if the parent block is empty
    if state.latest_block_hash != state.latest_execution_payload_bid.block_hash:
        return

    expected = get_expected_withdrawals(state)
    apply_withdrawals(state, expected.withdrawals)

    update_next_withdrawal_index(state, expected.withdrawals)
    update_payload_expected_withdrawals(state, expected.withdrawals)        # [New Gloas]
    update_builder_pending_withdrawals(state, expected.processed_builder_withdrawals_count)  # [New Gloas]
    update_pending_partial_withdrawals(state, expected.processed_partial_withdrawals_count)
    update_next_withdrawal_builder_index(state, expected.processed_builders_sweep_count)     # [New Gloas]
    update_next_withdrawal_validator_index(state, expected.withdrawals)
```

**`get_builder_withdrawals`** (line 1184-1213): drains `state.builder_pending_withdrawals` up to `MAX_WITHDRAWALS_PER_PAYLOAD - 1`. Each entry emits `Withdrawal(amount=withdrawal.amount, address=withdrawal.fee_recipient, validator_index=convertB→V(withdrawal.builder_index))`.

**`get_builders_sweep_withdrawals`** (line 1218-1253):

```python
for _ in range(builders_limit):
    ...
    builder = state.builders[builder_index]
    if builder.withdrawable_epoch <= epoch and builder.balance > 0:
        withdrawals.append(
            Withdrawal(
                index=withdrawal_index,
                validator_index=convert_builder_index_to_validator_index(builder_index),
                address=builder.execution_address,
                amount=builder.balance,            # <-- spec reads STATE directly
            )
        )
        withdrawal_index += WithdrawalIndex(1)
    builder_index = BuilderIndex((builder_index + 1) % len(state.builders))
    processed_count += 1
```

**`apply_withdrawals`** (line 1303-1311):

```python
def apply_withdrawals(state: BeaconState, withdrawals: Sequence[Withdrawal]) -> None:
    for withdrawal in withdrawals:
        if is_builder_index(withdrawal.validator_index):
            builder_index = convert_validator_index_to_builder_index(withdrawal.validator_index)
            builder_balance = state.builders[builder_index].balance
            state.builders[builder_index].balance -= min(withdrawal.amount, builder_balance)
        else:
            decrease_balance(state, withdrawal.validator_index, withdrawal.amount)
```

Helpers: `is_builder_index(idx) = (idx & BUILDER_INDEX_FLAG) != 0`; `BUILDER_INDEX_FLAG` is the high bit of u64.

Sources of `state.builder_pending_withdrawals` appends:

1. `process_builder_pending_payments` (epoch boundary, payment.weight >= quorum) — `beacon-chain.md:908`.
2. `apply_parent_execution_payload` (parent older than previous epoch + value > 0) — `beacon-chain.md:1144`.
3. `settle_builder_payment` (per-bid settlement) — `beacon-chain.md:908`.

Open questions:

1. **Sweep amount semantic** — spec reads `state.builders[idx].balance`; per-client?
2. **Queue+sweep collision** — same builder has queue entries AND sweep eligibility; per-client emitted amount?
3. **Apply-withdrawals saturation** — `min(amount, balance)` on builder branch; per-client?
4. **Early-return semantics** — parent-EMPTY skip; per-client.
5. **`BUILDER_INDEX_FLAG` bit position** — high bit of u64; per-client constant.

## Hypotheses

- **H1.** All six clients implement `process_withdrawals` orchestration identically (early-return + expected → apply → 6 state updates).
- **H2.** All six implement `get_builder_withdrawals` to emit `Withdrawal.amount = withdrawal.amount` (queue entry's amount).
- **H3.** All six implement `get_builders_sweep_withdrawals` to emit `Withdrawal.amount = state.builders[idx].balance` (pre-block builder balance).
- **H4.** All six implement `apply_withdrawals` with `min(amount, balance)` saturation on the builder branch.
- **H5.** All six implement `update_builder_pending_withdrawals` to slice off `processed_builder_withdrawals_count` head entries.
- **H6.** All six implement `update_next_withdrawal_builder_index` with modular cursor advance.
- **H7.** All six agree on `is_builder_index`, `convert_builder_index_to_validator_index`, `convert_validator_index_to_builder_index`, `BUILDER_INDEX_FLAG`.
- **H8** *(queue+sweep collision)*. When a builder has both pending queue entries and is sweep-eligible, all six clients emit sweep `Withdrawal.amount = pre-block builder.balance` (per spec H3). **Lodestar suspected divergent**: emits `pre_balance - sum(queue_drain_amounts)` via `builderBalanceAfterWithdrawals` cache.

## Findings

### prysm

`ProcessWithdrawals` at `vendor/prysm/beacon-chain/core/gloas/withdrawals.go:46-107`:

```go
func ProcessWithdrawals(st state.BeaconState) error {
    full, err := st.LatestBlockHashMatchesBidBlockHash()
    if err != nil { return errors.Wrap(err, "could not get parent block full status") }
    if !full { return nil }

    expected, err := st.ExpectedWithdrawalsGloas()
    if err != nil { return ... }

    if err := st.DecreaseWithdrawalBalances(expected.Withdrawals); err != nil { return ... }
    if len(expected.Withdrawals) > 0 {
        if err := st.SetNextWithdrawalIndex(expected.Withdrawals[len(expected.Withdrawals)-1].Index + 1); err != nil { return ... }
    }
    if err := st.SetPayloadExpectedWithdrawals(expected.Withdrawals); err != nil { return ... }
    if err := st.DequeueBuilderPendingWithdrawals(expected.ProcessedBuilderWithdrawalsCount); err != nil { return ... }
    if err := st.DequeuePendingPartialWithdrawals(expected.ProcessedPartialWithdrawalsCount); err != nil { return ... }
    err = st.SetNextWithdrawalBuilderIndex(expected.NextWithdrawalBuilderIndex)
    if err != nil { return ... }
    // ... next_withdrawal_validator_index update ...
    return nil
}
```

Early-return matches spec ✓.

The spec docstring quoted in prysm's comment at `withdrawals.go:23-26` references an older spec version that also checked `is_genesis_block = state.latest_block_hash == Hash32()`. The actual prysm code (lines 48-54) only checks the single `LatestBlockHashMatchesBidBlockHash` condition — matches the **current** spec (`beacon-chain.md:1378-1380`). The stale comment is a documentation drift but not a code divergence.

`appendBuildersSweepWithdrawals` at `vendor/prysm/beacon-chain/state/state-native/getters_gloas.go:580-618`:

```go
for range buildersLimit {
    if len(ws) >= withdrawalsLimit { break }
    builder := b.builders[builderIndex]
    if builder == nil { return ... }
    if builder.WithdrawableEpoch <= epoch && builder.Balance > 0 {
        ws = append(ws, &enginev1.Withdrawal{
            Index:          withdrawalIndex,
            ValidatorIndex: builderIndex.ToValidatorIndex(),
            Address:        builder.ExecutionAddress,
            Amount:         uint64(builder.Balance),    // <-- reads builder.Balance from state
        })
        withdrawalIndex++
    }
    builderIndex = primitives.BuilderIndex((uint64(builderIndex) + 1) % uint64(buildersCount))
}
```

Reads `builder.Balance` **directly from state** ✓ matches spec H3.

### lighthouse

`gloas::process_withdrawals` at `vendor/lighthouse/consensus/state_processing/src/per_block_processing/withdrawals.rs:489-532`:

```rust
pub mod gloas {
    pub fn process_withdrawals<E: EthSpec>(
        state: &mut BeaconState<E>,
        spec: &ChainSpec,
    ) -> Result<(), BlockProcessingError> {
        // Return early if the parent block is empty.
        if *state.latest_block_hash()? != state.latest_execution_payload_bid()?.block_hash {
            return Ok(());
        }
        let ExpectedWithdrawals::Gloas(ExpectedWithdrawalsGloas { ... }) = get_expected_withdrawals(state, spec)? else { ... };
        apply_withdrawals(state, &withdrawals)?;
        update_next_withdrawal_index(state, &withdrawals)?;
        update_payload_expected_withdrawals(state, &withdrawals)?;
        update_builder_pending_withdrawals(state, processed_builder_withdrawals_count)?;
        update_pending_partial_withdrawals(state, processed_partial_withdrawals_count)?;
        update_next_withdrawal_builder_index(state, processed_builders_sweep_count)?;
        update_next_withdrawal_validator_index(state, &withdrawals, spec)?;
        ...
    }
}
```

Spec-conformant ordering ✓.

`get_builders_sweep_withdrawals` at `withdrawals.rs:186-240`:

```rust
let builder = builders
    .get(builder_index as usize)
    .ok_or(BeaconStateError::UnknownBuilder(builder_index))?;
if builder.withdrawable_epoch <= epoch && builder.balance > 0 {
    withdrawals.push(Withdrawal {
        index: *withdrawal_index,
        validator_index: convert_builder_index_to_validator_index(builder_index),
        address: builder.execution_address,
        amount: builder.balance,    // <-- reads builder.balance from state
    });
    withdrawal_index.safe_add_assign(1)?;
}
builder_index = builder_index.safe_add(1)?.safe_rem(builders.len() as u64)?;
```

Reads `builder.balance` **directly from state** ✓ matches spec H3.

`apply_withdrawals` at `withdrawals.rs:423-447`:

```rust
for withdrawal in withdrawals {
    if state.fork_name_unchecked().gloas_enabled() && is_builder_index(withdrawal.validator_index) {
        let builder_index = convert_validator_index_to_builder_index(withdrawal.validator_index);
        let builder = state.builders_mut()?.get_mut(builder_index as usize)
            .ok_or(BeaconStateError::UnknownBuilder(builder_index))?;
        builder.balance = builder.balance.saturating_sub(withdrawal.amount);
    } else {
        decrease_balance(state, withdrawal.validator_index as usize, withdrawal.amount)?;
    }
}
```

Uses `saturating_sub` ✓ matches spec H4 (`min(amount, balance)` = `balance - min(amount, balance)` = `balance.saturating_sub(amount)`).

`is_builder_index` / `convert_*` at `vendor/lighthouse/consensus/state_processing/src/per_block_processing/builder.rs`:

```rust
use types::{builder::BuilderIndex, consts::gloas::BUILDER_INDEX_FLAG};

pub fn is_builder_index(validator_index: u64) -> bool {
    validator_index & BUILDER_INDEX_FLAG != 0
}
pub fn convert_builder_index_to_validator_index(builder_index: BuilderIndex) -> u64 {
    builder_index | BUILDER_INDEX_FLAG
}
pub fn convert_validator_index_to_builder_index(validator_index: u64) -> BuilderIndex {
    validator_index & !BUILDER_INDEX_FLAG
}
```

Spec-conformant bit-ops ✓ matches H7.

### teku

`WithdrawalsHelpersGloas` at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/withdrawals/WithdrawalsHelpersGloas.java:37-203`. Class hierarchy: extends `WithdrawalsHelpersElectra` and overrides 6 virtual methods.

`processWithdrawals` (line 57-67):

```java
@Override
public void processWithdrawals(final MutableBeaconState state) {
  final MutableBeaconStateGloas stateGloas = MutableBeaconStateGloas.required(state);
  if (!stateGloas.getLatestBlockHash().equals(stateGloas.getLatestExecutionPayloadBid().getBlockHash())) {
    return;
  }
  super.processWithdrawals(state);
}
```

Early-return matches spec ✓. Then delegates to Electra superclass for orchestration.

`processBuildersSweepWithdrawals` (line 101-143):

```java
@Override
protected int processBuildersSweepWithdrawals(final BeaconState state, final List<Withdrawal> withdrawals) {
    ...
    final Builder builder = builders.get(builderIndex.intValue());
    if (builder.getWithdrawableEpoch().isLessThanOrEqualTo(epoch)
        && builder.getBalance().isGreaterThan(UInt64.ZERO)) {
      withdrawals.add(
          withdrawalSchema.create(
              withdrawalIndex,
              miscHelpersGloas.convertBuilderIndexToValidatorIndex(builderIndex),
              builder.getExecutionAddress(),
              builder.getBalance()));    // <-- reads builder.getBalance() from state
      withdrawalIndex = withdrawalIndex.increment();
    }
    builderIndex = builderIndex.plus(1).mod(buildersCount);
    processedBuildersSweepCount++;
}
```

Reads `builder.getBalance()` **directly from state** ✓ matches spec H3.

`applyWithdrawals` (line 146-165) dispatches on `predicatesGloas.isBuilderIndex(validatorIndex)`; uses `builderBalance.minusMinZero(withdrawal.getAmount())` for the saturating subtract ✓.

### nimbus

`process_withdrawals` at `vendor/nimbus/beacon_chain/spec/state_transition_block.nim:1561-1584`:

```nim
func process_withdrawals*(state: var (gloas.BeaconState | heze.BeaconState)):
    Result[void, cstring] =
  if state.latest_block_hash != state.latest_execution_payload_bid.block_hash:
    return ok()
  let expected = get_expected_withdrawals(state)
  ? apply_withdrawals(state, expected.withdrawals)
  update_next_withdrawal_index(state, expected.withdrawals)
  update_payload_expected_withdrawals(state, expected.withdrawals)
  update_builder_pending_withdrawals(state, expected.processed_builder_withdrawals_count)
  update_pending_partial_withdrawals(state, expected.processed_partial_withdrawals_count)
  update_next_withdrawal_builder_index(state, expected.processed_builders_sweep_count)
  update_next_withdrawal_validator_index(state, expected.withdrawals)
```

Spec-conformant ✓.

`get_builders_sweep_withdrawals` at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:1905-1943`:

```nim
let builder = state.builders.item(builder_index)
if builder.withdrawable_epoch <= epoch and builder.balance > 0.Gwei:
  withdrawals.add(Withdrawal(
      index: withdrawal_index,
      validator_index: convert_builder_index_to_validator_index(builder_index),
      address: builder.execution_address,
      amount: builder.balance))    # <-- reads builder.balance from state
  withdrawal_index += WithdrawalIndex(1)
builder_index = BuilderIndex((builder_index + 1) mod state.builders.lenu64)
```

Reads `builder.balance` **directly from state** ✓ matches spec H3.

`apply_withdrawals` at `state_transition_block.nim:1477-1496`:

```nim
if is_builder_index(withdrawal.validator_index):
  let
    builder_index = convert_validator_index_to_builder_index(withdrawal.validator_index)
    builder_balance = addr state.builders.mitem(builder_index).balance
  builder_balance[] = builder_balance[] - min(withdrawal.amount, builder_balance[])
else:
  let validator_index = ValidatorIndex.init(withdrawal.validator_index).valueOr:
    return err("apply_withdrawals: invalid validator index")
  decrease_balance(state, validator_index, withdrawal.amount)
```

Uses `min(withdrawal.amount, builder_balance)` saturating subtract ✓ matches spec H4.

### lodestar

**Suspected divergence on H8** at `vendor/lodestar/packages/state-transition/src/block/processWithdrawals.ts:411-507`.

Orchestrator `getExpectedWithdrawals`:

```typescript
const builderBalanceAfterWithdrawals = new Map<BuilderIndex, number>();
const validatorBalanceAfterWithdrawals = new Map<ValidatorIndex, number>();
// ...
if (fork >= ForkSeq.gloas) {
  const { builderWithdrawals, ...processedCount } = getBuilderWithdrawals(
    state as CachedBeaconStateGloas,
    withdrawalIndex,
    expectedWithdrawals,
    builderBalanceAfterWithdrawals     // <-- map passed in, populated
  );
  expectedWithdrawals.push(...builderWithdrawals);
  ...
}
// ...
if (fork >= ForkSeq.gloas) {
  const { buildersSweepWithdrawals, ...processedCount } = getBuildersSweepWithdrawals(
    state as CachedBeaconStateGloas,
    withdrawalIndex,
    expectedWithdrawals.length,
    builderBalanceAfterWithdrawals     // <-- SAME map, populated by getBuilderWithdrawals
  );
  expectedWithdrawals.push(...buildersSweepWithdrawals);
  ...
}
```

`getBuilderWithdrawals` (line 135-186):

```typescript
let balance = builderBalanceAfterWithdrawals.get(builderIndex);
if (balance === undefined) {
  balance = state.builders.getReadonly(builderIndex).balance;
  builderBalanceAfterWithdrawals.set(builderIndex, balance);
}
// Use the withdrawal amount directly as specified in the spec
builderWithdrawals.push({
  ...,
  amount: BigInt(withdrawal.amount),    // <-- spec-correct (queue entry's amount)
});
withdrawalIndex++;
builderBalanceAfterWithdrawals.set(builderIndex, balance - withdrawal.amount);    // <-- DECREMENTS map
processedCount++;
```

Queue-drain emits spec-correct `amount` (matches H2). But **decrements the cache** by `withdrawal.amount` per entry.

`getBuildersSweepWithdrawals` (line 188-243):

```typescript
let balance = builderBalanceAfterWithdrawals.get(builderIndex);
if (balance === undefined) {
  balance = builder.balance;
  builderBalanceAfterWithdrawals.set(builderIndex, balance);
}
if (builder.withdrawableEpoch <= epoch && balance > 0) {
  buildersSweepWithdrawals.push({
    index: withdrawalIndex,
    validatorIndex: convertBuilderIndexToValidatorIndex(builderIndex),
    address: builder.executionAddress,
    amount: BigInt(balance),       // <-- READS CACHED balance, NOT builder.balance
  });
  withdrawalIndex++;
  builderBalanceAfterWithdrawals.set(builderIndex, 0);
}
processedCount++;
```

**Reads `balance` from cache** (which was decremented by queue drains for this builder, if any). Spec reads `builder.balance` directly. **Divergence.**

Concrete example. Pre-block state:
- `state.builders = [Builder(balance=1000, withdrawable_epoch=current_epoch, execution_address=E)]`.
- `state.builder_pending_withdrawals = [BPW(builder_index=0, fee_recipient=A, amount=200)]`.
- `state.next_withdrawal_builder_index = 0`.

Spec output:
- `get_builder_withdrawals` → `[W(amount=200, address=A, validator_index=0|FLAG)]`.
- `get_builders_sweep_withdrawals` reads `state.builders[0].balance = 1000` → `[W(amount=1000, address=E, validator_index=0|FLAG)]`.
- `expected.withdrawals` = `[W(200, A, ...), W(1000, E, ...)]`.

Lodestar output:
- `getBuilderWithdrawals` → `[W(amount=200, address=A, ...)]`. Cache: `map[0] = 800`.
- `getBuildersSweepWithdrawals` reads `map[0] = 800` → `[W(amount=800, address=E, ...)]`.
- `expected.withdrawals` = `[W(200, A, ...), W(800, E, ...)]`.

These differ at the second withdrawal's `amount` (1000 vs 800). `state.payload_expected_withdrawals` consequently differs → state-root mismatch.

In `apply_withdrawals` both converge to `state.builders[0].balance = 0` (via the `min(amount, balance)` saturation):
- Spec: queue applies (balance=800), sweep applies `min(1000, 800)=800` → 0.
- Lodestar: queue applies (balance=800), sweep applies `min(800, 800)=800` → 0.

But the EL receives different withdrawal-amount lists:
- Spec: mints `200 + 1000 = 1200` (creates `200` supply inflation vs the CL's 1000-decrement).
- Lodestar: mints `200 + 800 = 1000` (supply preserved).

So lodestar's caching **fixes the supply asymmetry** that the spec's literal semantics introduce — at the cost of consensus divergence from spec-conformant clients.

The spec note at `beacon-chain.md:1357-1369` acknowledges supply asymmetry from immediate-deduct vs deferred-deduct semantics, but does not address this queue+sweep collision case. Whether the spec's literal semantics or lodestar's mitigation is "correct" is a spec-discussion question; cross-client consensus is what matters, and **5 of 6 clients follow spec literally**.

**Reachability**: see the dedicated "Reachability" section below. Short version: the colliding state cannot arise from honest block production because `process_voluntary_exit:1647` requires both `builder_pending_withdrawals` and `builder_pending_payments` to be empty for X at exit time, and no post-exit path can add entries for X.

### grandine

`get_builders_sweep_withdrawals_count` at `vendor/grandine/transition_functions/src/gloas/block_processing.rs:271-312`:

```rust
let builder = state.builders().get(builder_index)?;
if builder.withdrawable_epoch <= current_epoch && builder.balance > 0 {
    withdrawals.push(Withdrawal {
        index: *withdrawal_index,
        validator_index: convert_builder_index_to_validator_index(builder_index),
        address: builder.execution_address,
        amount: builder.balance,    // <-- reads builder.balance from state
    });
    *withdrawal_index = withdrawal_index.checked_add(1).ok_or(Error::<P>::WithdrawalIndexOverflow)?;
}
builder_index = builder_index.checked_add(1)?.checked_rem(total_builders)
    .expect("total_builders being 0 should prevent the loop from being executed");
processed_count += 1;
```

Reads `builder.balance` **directly from state** ✓ matches spec H3.

`apply_withdrawals` called from `process_withdrawals` (`block_processing.rs:467`) — saturating subtraction on builder branch matches spec ✓.

## Cross-reference table

| Client | `get_builders_sweep_withdrawals` reads `builder.balance` from (H3) | `apply_withdrawals` saturating-sub (H4) | Early-return on parent-EMPTY (H1) | Queue+sweep collision behavior (H8) |
|---|---|---|---|---|
| prysm | state directly (`b.builders[builderIndex].Balance`) ✓ | `min` via state-mutator path ✓ | `LatestBlockHashMatchesBidBlockHash` ✓ | spec-conformant — emits `pre-block balance` |
| lighthouse | state directly (`builders.get(idx).balance`) ✓ | `builder.balance.saturating_sub(amount)` ✓ | `*state.latest_block_hash()? != ...block_hash` ✓ | spec-conformant — emits `pre-block balance` |
| teku | state directly (`builders.get(idx).getBalance()`) ✓ | `minusMinZero` ✓ | `getLatestBlockHash().equals(...)` ✓ | spec-conformant — emits `pre-block balance` |
| nimbus | state directly (`state.builders.item(idx).balance`) ✓ | `min(amount, balance)` ✓ | `state.latest_block_hash != ...block_hash` ✓ | spec-conformant — emits `pre-block balance` |
| **lodestar** | **per-builder cache `builderBalanceAfterWithdrawals` (decremented by queue drains)** | `builder.balance -= amount` via `applyWithdrawals` ✓ | `state.latestBlockHash !== ...blockHash` ✓ | **SUSPECTED DIVERGENT** — emits `pre_balance − queue_drain_total` |
| grandine | state directly (`state.builders().get(idx).balance`) ✓ | per-spec `apply_withdrawals(...)` ✓ | `state.latest_block_hash != ...block_hash` ✓ | spec-conformant — emits `pre-block balance` |

All H1, H2, H4, H5, H6, H7 ✓ for all 6 clients. H3 ✓ for 5 of 6 (lodestar reads from cache when populated). **H8 likely fails for lodestar** under queue+sweep collision.

## Empirical tests

### Verification against real lodestar code — CONFIRMED DIVERGENT

`items/067/demo/lodestar_intree_test.ts` is a vitest test that exercises the real lodestar `getExpectedWithdrawals` function (imports from `state-transition/src/block/processWithdrawals.js`). Copied into `vendor/lodestar/packages/state-transition/test/unit/block/buildersWeepDivergence.test.ts` and run with `pnpm vitest`:

```
✓ T1.2 (queue only — no sweep) — no divergence; lodestar matches spec
✓ T1.3 (sweep only — no queue) — no divergence; lodestar matches spec
✗ T1.1 (collision) — sweep amount MUST equal pre-block builder.balance

AssertionError: expected 999800000000n to be 1000000000000n
  test/unit/block/buildersWeepDivergence.test.ts:113
  expect(expectedWithdrawals[1].amount).toBe(BigInt(builderBalance));

Tests: 1 failed | 2 passed (3)
```

Real-lodestar verification 2026-05-14. The bug is confirmed in the actual lodestar codebase (not just in a faithful re-implementation): when a builder simultaneously has a queue entry AND is sweep-eligible, the sweep `Withdrawal.amount` emitted by lodestar's `getExpectedWithdrawals` is `pre_balance − queue_drain_total = 999,800,000,000` Gwei instead of spec's `pre_balance = 1,000,000,000,000` Gwei. The diff equals exactly the queue drain. T1.2 (queue-only) and T1.3 (sweep-only) pass — confirming the bug is isolated to the cache-read path in `getBuildersSweepWithdrawals` at `processWithdrawals.ts:220`.

The test is a drop-in for a lodestar upstream PR.

### Standalone Python harness — same result

Earlier (independent of lodestar's TypeScript runtime), `items/067/demo/spec_vs_lodestar.py` reproduced both spec and lodestar semantics inline and produced the same divergence:

**Result (2026-05-14)**:

```
=== T1.1: queue+sweep COLLISION (builder 0 has pending + is sweep-eligible) ===
  spec output     (2 withdrawal(s)):
    idx=42 vidx=0x8000000000000000 addr=cccccccc... amount=200000000
    idx=43 vidx=0x8000000000000000 addr=bbbbbbbb... amount=1000000000000
  lodestar output (2 withdrawal(s)):
    idx=42 vidx=0x8000000000000000 addr=cccccccc... amount=200000000
    idx=43 vidx=0x8000000000000000 addr=bbbbbbbb... amount=999800000000
  → OUTPUTS DIFFER ✗
    diff at [1]: spec.amount=1000000000000, lodestar.amount=999800000000, diff=200000000
```

The sweep withdrawal amount differs by exactly the queue drain (200,000,000 Gwei = 0.2 ETH on the test setup):

- **Spec / prysm / lighthouse / teku / nimbus / grandine**: `amount = pre_balance = 1,000,000,000,000` Gwei.
- **Lodestar**: `amount = pre_balance - queue_drain_total = 999,800,000,000` Gwei.

State-internal `state.builders[0].balance` converges to 0 in both semantics (via the `min(amount, balance)` saturation in `apply_withdrawals`). But `state.payload_expected_withdrawals[1].amount` differs → different beacon state root → different EL minting → different EL block hash → cross-CL block import rejection.

### T1.2 (queue only) — MATCH ✓

Same setup as T1.1 but builder has `withdrawable_epoch > current_epoch` (not sweep-eligible). Only queue drain fires. Both spec and lodestar emit identical `Withdrawal(amount=200,000,000)`.

### T1.3 (sweep only) — MATCH ✓

Same setup as T1.1 but `builder_pending_withdrawals = []`. Only sweep fires. Both spec and lodestar emit identical `Withdrawal(amount=pre_balance)`.

**Conclusion**: divergence triggers **only** on the queue+sweep collision. Both non-collision cases produce identical output, isolating the bug to the lodestar cache-read in `getBuildersSweepWithdrawals` (line 220 of `processWithdrawals.ts`).

### Additional suggested tests

- **T1.4 (multi-entry queue).** 3 queue entries for builder 0; lodestar's cache should subtract all 3 amounts.
- **T2.1 (EL effect on devnet).** End-to-end devnet test: lodestar proposes a block triggering the divergence; observe whether EL accepts and what amount is minted. Cross-CL block import.
- **T2.2 (EF fixture corpus).** Grep `vendor/consensus-specs/tests/.../gloas/.../withdrawals/...` for fixtures that exercise the collision case. The pyspec test file `vendor/consensus-specs/tests/core/pyspec/eth_consensus_specs/test/gloas/block_processing/test_process_withdrawals.py` (reviewed 2026-05-14) does **not** cover the queue+sweep collision — none of the 25+ test cases construct a single builder that simultaneously has pending queue entries AND is sweep-eligible.

## Reachability

The divergence triggers when a single builder X simultaneously has (a) entries in `state.builder_pending_withdrawals` AND (b) is sweep-eligible (`builder.withdrawable_epoch <= current_epoch AND builder.balance > 0`).

Condition (b) requires X to have called `initiate_builder_exit` at least `MIN_BUILDER_WITHDRAWABILITY_DELAY = 64` epochs ago. `initiate_builder_exit` (`beacon-chain.md:892`) is the only path that sets `withdrawable_epoch` to a non-`FAR_FUTURE_EPOCH` value, and it is called from exactly one site: `process_voluntary_exit` (`beacon-chain.md:1652`). There is no builder-slashing path.

### `process_voluntary_exit` clears both lists for X at exit time

```python
# beacon-chain.md:1641-1652
if is_builder_index(voluntary_exit.validator_index):
    builder_index = convert_validator_index_to_builder_index(voluntary_exit.validator_index)
    assert is_active_builder(state, builder_index)
    # Only exit builder if it has no pending withdrawals in the queue
    assert get_pending_balance_to_withdraw_for_builder(state, builder_index) == 0
    ...
    initiate_builder_exit(state, builder_index)
```

`get_pending_balance_to_withdraw_for_builder` (`beacon-chain.md:578-586`) sums across **both** `state.builder_pending_withdrawals` **and** `state.builder_pending_payments` for X. So at the moment X exits, both lists are empty for X.

### No post-exit path can add entries for X

All writes to `state.builder_pending_withdrawals` in the spec:

1. **`settle_builder_payment`** (`beacon-chain.md:908`) — copies a `BuilderPendingPayment.withdrawal` from `state.builder_pending_payments`. Source: payment was added via `process_execution_payload_bid`, which asserts `is_active_builder(state, builder_index)` at line 1439. After exit, X is not active → no new payments for X enter the buffer → no settle deposits a withdrawal for X.
2. **`process_builder_pending_payments`** (`beacon-chain.md:1062`) at epoch boundary — same source as (1).
3. **`apply_parent_execution_payload`** late-append (`beacon-chain.md:1141-1144`) — fires when `parent_bid.value > 0 AND parent_epoch < get_previous_epoch(state)`. Appends `BuilderPendingWithdrawal(builder_index=parent_bid.builder_index)`. For this to fire with X, `state.latest_execution_payload_bid.builder_index` must still be X when block N+1's `apply_parent_execution_payload` runs, AND that bid must be more than one epoch old.

`process_execution_payload_bid:1473` writes `state.latest_execution_payload_bid = bid` **unconditionally** every block (including for `BUILDER_INDEX_SELF_BUILD`). So any block after X's exit overwrites X's bid in `latest_execution_payload_bid`. After exit, no further `process_execution_payload_bid` can write X's bid (assert at line 1439). Therefore the only way (3) fires for X post-exit is if **zero blocks have been produced since X's last pre-exit bid**, i.e., a 32+-slot stall.

The exit block itself cannot carry X's own bid: `process_execution_payload_bid` runs before `process_voluntary_exit` in `process_block` ordering. If X's bid is processed in the exit block, line 1459 writes a `BuilderPendingPayment` for X into `state.builder_pending_payments`, immediately making `get_pending_balance_to_withdraw_for_builder(state, X) > 0` and failing the exit assertion at line 1647.

Likewise, if X's bid was in block E-1 (any slot in the current or previous epoch), the exit block's `process_parent_execution_payload` calls `settle_builder_payment` for X's entry, appending X's withdrawal to `state.builder_pending_withdrawals` *before* `process_voluntary_exit` runs — again failing the assertion.

### The 32+-slot stall edge case is self-blocking

The only remaining way for `state.latest_execution_payload_bid.builder_index == X` to persist into the post-exit window is if 32+ consecutive empty slots pass between X's last bid and the next block. In that case, the late-append at line 1144 **itself fires for X** in that next block (because parent_epoch < previous_epoch and parent_bid.value > 0), placing X's withdrawal in `state.builder_pending_withdrawals`. That entry must then drain before X can exit, by which time `state.latest_execution_payload_bid` has been overwritten in every block since. A 64-epoch stall (the full sweep-eligibility countdown) would lose finality long before sweep eligibility arrives.

### Verdict: synthetic-state

Honest block production cannot construct the queue+sweep collision for a single builder. The colliding state can be hand-built or fuzz-generated and a state-transition fixture against it would surface the lodestar divergence — that is the `synthetic-state` impact tier. The precondition at `process_voluntary_exit:1647` is the upstream guard that prevents the collision from arising during normal operation.

The lodestar cache-read remains a real cross-client conformance issue against any constructed fixture exercising the collision, and a lodestar maintainer may still wish to revert it to spec-literal semantics to avoid future fuzz-corpus failures. But it does not represent a reachable mainnet consensus split.

## Conclusion

All six clients implement the Gloas builder withdrawal lifecycle (`process_withdrawals`, `get_builder_withdrawals`, `get_builders_sweep_withdrawals`, `apply_withdrawals`, `update_*` helpers, and the `is_builder_index` / `convert_*` predicates) spec-conformantly with one confirmed exception.

**Confirmed divergence in lodestar (H8)**: `getBuildersSweepWithdrawals` reads the sweep amount from a per-builder cache (`builderBalanceAfterWithdrawals`) populated and decremented by the preceding `getBuilderWithdrawals` queue drain. Spec semantics at `beacon-chain.md:1239` read `state.builders[builder_index].balance` directly from the pre-block state. When a single builder simultaneously has (a) entries in `state.builder_pending_withdrawals` AND (b) is sweep-eligible, lodestar emits a sweep `Withdrawal.amount` smaller than spec by exactly `sum(queue_drain_amounts)`. Different `state.payload_expected_withdrawals` → different state root → different EL block-hash → cross-CL block import rejection.

**Empirical verification** at `items/067/demo/spec_vs_lodestar.py` (run 2026-05-14): T1.1 collision case produces `spec.amount = 1_000_000_000_000` vs `lodestar.amount = 999_800_000_000`, divergence exactly equal to the queue-drain total. T1.2 (queue-only) and T1.3 (sweep-only) produce identical output across spec and lodestar — confirming the bug is isolated to the cache-read in the sweep path.

The post-`apply_withdrawals` state converges to `builder.balance = 0` in both semantics (via the `min(amount, balance)` saturation in `apply_withdrawals`). The divergence is in the *emitted* `Withdrawal` records — these are part of `state.payload_expected_withdrawals` and reach the EL via the block payload.

Lodestar's caching arguably **fixes a supply-asymmetry bug** in the spec's literal semantics: spec mints `pre_balance + queue_drain_total` to the EL (via the queue + sweep withdrawal emissions) while only decrementing `pre_balance` on the CL — a net `+queue_drain_total` supply inflation. Lodestar's behavior preserves the supply invariant. However, lodestar diverges from 5 spec-conformant clients, which is a worse outcome for consensus stability.

**Verdict: impact synthetic-state.** Confirmed divergence on a constructed colliding state; honest block production cannot reach the collision because `process_voluntary_exit:1647` requires `get_pending_balance_to_withdraw_for_builder == 0` (sums both queue + payments) at exit time and no post-exit path can add entries for the exiting builder. See the **Reachability** section for the full trace-through.

Resolution options:
1. **Lodestar reverts** to spec-literal semantics: change `getBuildersSweepWithdrawals` to read `builder.balance` directly from state (not from the cache). This re-introduces the supply-asymmetry but preserves cross-client consensus. Recommended as the immediate fix.
2. **Spec corrects** the queue+sweep semantics by introducing a balance-cache or saturating the sweep amount. This would require all 5 other clients to update. Not recommended without broader spec discussion.
3. **EF spec-test corpus extension**: add a queue+sweep collision fixture (the pyspec test corpus at `vendor/consensus-specs/tests/core/pyspec/eth_consensus_specs/test/gloas/block_processing/test_process_withdrawals.py` does NOT currently cover this case — verified 2026-05-14). This would catch the discrepancy at fixture-gen time and force a decision.

## Cross-cuts

### With items #22 + #23 + #28 (nimbus Gloas alpha-drift, closed)

PR #8440 fixed nimbus credential-prefix predicates. This audit verifies the surrounding withdrawal machinery has no parallel issue. Confirmed clean for nimbus on H1–H8.

### With item #57 (`process_builder_pending_payments`)

Item #57 rotates `state.builder_pending_payments` at epoch boundary; appends payments-met-quorum to `state.builder_pending_withdrawals`. This item drains the resulting queue. Round-trip cross-cut.

### With item #58 (`process_execution_payload_bid`)

Item #58 inserts bid entries into `state.builder_pending_payments`; eventually reaches the withdrawal queue via item #57. Pipeline cross-cut.

### With item #64 (`upgrade_to_gloas`)

`upgrade_to_gloas` initializes `state.builder_pending_withdrawals = []` and `state.next_withdrawal_builder_index = 0`. First `process_withdrawals` post-upgrade hits the no-collision case.

### With item #65 (proposer-slashing builder-payment voidance)

Slashing voids pending payments before they reach the withdrawal queue. Reduces the queue+sweep collision probability for slashed proposers but does not affect the lodestar deviation for non-slashed builders.

### With evm-breaker's EL withdrawal-handling audit

EL clients mint withdrawal amounts from the `Withdrawal.amount` field. If lodestar emits a different amount than the EL block-header `withdrawals_root` requires (via Merkleization), the block hash will differ. Cross-corpus implication.

## Adjacent untouched

1. **EF spec-test corpus coverage of queue+sweep collision** — grep `vendor/consensus-specs/tests/.../gloas/.../withdrawals/...` for fixtures that exercise this case.
2. **Spec text clarification needed** — `beacon-chain.md:1239` literal reads `builder.balance` but the supply-asymmetry note (lines 1357-1369) acknowledges related concerns. Whether queue+sweep collision was intended is a spec-discussion question.
3. **`MIN_BUILDER_WITHDRAWABILITY_DELAY` and `MAX_BUILDERS_PER_WITHDRAWALS_SWEEP` constants cross-client** — verify uniform.
4. **`BUILDER_INDEX_FLAG` constant value cross-client** — should be `1 << 63` (high bit of u64). Verify per-client.
5. **Lodestar EF spec-test pass status on Gloas withdrawal fixtures** — if lodestar passes, the fixtures don't cover the collision case (audit-worthy).
6. **`update_next_withdrawal_validator_index` edge case** when only builder withdrawals fire (no validators) — verify per-client.
