---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [7, 12, 19]
eips: [EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 57: `process_builder_pending_payments` (Gloas-new epoch helper, EIP-7732 ePBS settlement)

## Summary

Closes the EIP-7732 ePBS lifecycle audit on the settlement side: item #7 H10 audited the producer (`process_attestation` writes `state.builder_pending_payments[slot_idx].weight`); this item audits the consumer (`process_builder_pending_payments` reads the weight at each epoch boundary, tests the quorum predicate, settles into `state.builder_pending_withdrawals`, and rotates the ring buffer).

**All six clients implement the function and its quorum-threshold helper identically at the spec level.** The function body is 3 operations (filter by quorum → append to withdrawals → rotate ring buffer), the quorum formula is `(total_active_balance / SLOTS_PER_EPOCH) * 6 / 10`, and the position in `process_epoch` is uniform across all six (after `process_pending_consolidations`, before `process_effective_balance_updates`). No Pectra-surface; the function does not exist pre-Gloas. No EF fixtures wired for this audit yet, but the spec-test corpus has `epoch_processing/process_builder_pending_payments/` fixtures (used by prysm + grandine internally) — those should be wired into BeaconBreaker.

**Impact: none.** Six distinct rotation idioms (Go `copy`+zero-fill, Rust `Vector::new` rebuild, Java `subList`+`nCopies`+`setAll`, Nim compile-time `staticFor`, TypeScript in-place `for`+ViewDU clone, Rust `PersistentVector::try_from_iter`) and six distinct filtering idioms — all observably equivalent.

## Question

Pyspec `process_builder_pending_payments` (Gloas, `vendor/consensus-specs/specs/gloas/beacon-chain.md:1055-1067`):

```python
def process_builder_pending_payments(state: BeaconState) -> None:
    """
    Processes the builder pending payments from the previous epoch.
    """
    quorum = get_builder_payment_quorum_threshold(state)
    for payment in state.builder_pending_payments[:SLOTS_PER_EPOCH]:
        if payment.weight >= quorum:
            state.builder_pending_withdrawals.append(payment.withdrawal)

    old_payments = state.builder_pending_payments[SLOTS_PER_EPOCH:]
    new_payments = [BuilderPendingPayment() for _ in range(SLOTS_PER_EPOCH)]
    state.builder_pending_payments = old_payments + new_payments
```

Pyspec `get_builder_payment_quorum_threshold` (`:799-805`):

```python
def get_builder_payment_quorum_threshold(state: BeaconState) -> uint64:
    """
    Calculate the quorum threshold for builder payments.
    """
    per_slot_balance = get_total_active_balance(state) // SLOTS_PER_EPOCH
    quorum = per_slot_balance * BUILDER_PAYMENT_THRESHOLD_NUMERATOR
    return uint64(quorum // BUILDER_PAYMENT_THRESHOLD_DENOMINATOR)
```

Constants (`:152-153`): `BUILDER_PAYMENT_THRESHOLD_NUMERATOR = 6`, `BUILDER_PAYMENT_THRESHOLD_DENOMINATOR = 10` (60 % quorum).

Position in `process_epoch` (`:959-979`):

```python
def process_epoch(state: BeaconState) -> None:
    # ... (justification, inactivity, rewards, registry, slashings,
    #      eth1_data_reset, pending_deposits, pending_consolidations) ...
    # [New in Gloas:EIP7732]
    process_builder_pending_payments(state)
    process_effective_balance_updates(state)
    # ... (slashings_reset, randao_mixes_reset, historical_summaries,
    #      participation, sync_committee, proposer_lookahead) ...
    # [New in Gloas:EIP7732]
    process_ptc_window(state)
```

Cross-cuts items #7 (writer side), #9 (slashing-time clearer), #12 (withdrawal-time drain), #19 (bid-time recorder).

## Hypotheses

- **H1.** All six clients walk `state.builder_pending_payments[0..SLOTS_PER_EPOCH]` (the older half) and skip the newer half.
- **H2.** All six compute the quorum threshold via `(total_active_balance / SLOTS_PER_EPOCH) * 6 / 10` with the same constant values (`6`, `10`).
- **H3.** All six use `payment.weight >= quorum` (inclusive ≥) for the qualification predicate.
- **H4.** All six append `payment.withdrawal` (the `BuilderPendingWithdrawal` value, not the whole `BuilderPendingPayment`) to `state.builder_pending_withdrawals`.
- **H5.** All six rotate the ring buffer: slots `[0..SLOTS_PER_EPOCH)` ← slots `[SLOTS_PER_EPOCH..2*SLOTS_PER_EPOCH)`; slots `[SLOTS_PER_EPOCH..2*SLOTS_PER_EPOCH)` ← default `BuilderPendingPayment` (zero `weight`, default `withdrawal`).
- **H6.** All six maintain `len(state.builder_pending_payments) == 2 * SLOTS_PER_EPOCH` across the function (no inserts/deletes — only field overwrites).
- **H7.** All six call `process_builder_pending_payments` AFTER `process_pending_consolidations` and BEFORE `process_effective_balance_updates` in their `process_epoch` sequence.
- **H8.** All six agree on `BUILDER_PAYMENT_THRESHOLD_NUMERATOR = 6` and `BUILDER_PAYMENT_THRESHOLD_DENOMINATOR = 10` in their mainnet config.
- **H9** *(forward-fragility)*. Arithmetic safety at the quorum-threshold computation: prysm/nimbus use raw u64; lighthouse uses `safe_mul`/`safe_div`; grandine uses `saturating_*`; lodestar uses IEEE 754 doubles via `Math.floor`. At current mainnet stake levels all produce identical output, but the lodestar path is the least precise (the intermediate `totalActiveBalanceIncrements * EFFECTIVE_BALANCE_INCREMENT = ~3e16` value exceeds `Number.MAX_SAFE_INTEGER = 2^53 - 1 ≈ 9e15`, so subsequent floors may lose precision at extreme stake levels — currently invisible).

## Findings

H1–H9 satisfied across all six clients. No divergence at the spec-conformance level. Per-client style differences are catalogued below; none are observable.

### prysm

`vendor/prysm/beacon-chain/core/gloas/pending_payment.go:28-58` — `ProcessBuilderPendingPayments`:

```go
func ProcessBuilderPendingPayments(state state.BeaconState) error {
    quorum, err := builderQuorumThreshold(state)
    // ...
    payments, err := state.BuilderPendingPayments()
    slotsPerEpoch := uint64(params.BeaconConfig().SlotsPerEpoch)
    var withdrawals []*ethpb.BuilderPendingWithdrawal
    for _, payment := range payments[:slotsPerEpoch] {
        if quorum > payment.Weight {
            continue
        }
        withdrawals = append(withdrawals, payment.Withdrawal)
    }
    if err := state.AppendBuilderPendingWithdrawals(withdrawals); err != nil { ... }
    if err := state.RotateBuilderPendingPayments(); err != nil { ... }
    builderPendingPaymentsProcessedTotal.Add(float64(len(withdrawals)))
    return nil
}
```

`builderQuorumThreshold` at `:72-86` matches spec:

```go
activeBalance, _ := helpers.TotalActiveBalance(state)
slotsPerEpoch := uint64(cfg.SlotsPerEpoch)
numerator := cfg.BuilderPaymentThresholdNumerator
denominator := cfg.BuilderPaymentThresholdDenominator
activeBalancePerSlot := activeBalance / slotsPerEpoch
quorum := (activeBalancePerSlot * numerator) / denominator
```

`RotateBuilderPendingPayments` at `vendor/prysm/beacon-chain/state/state-native/setters_gloas.go:25-43`:

```go
slotsPerEpoch := params.BeaconConfig().SlotsPerEpoch
copy(b.builderPendingPayments[:slotsPerEpoch], b.builderPendingPayments[slotsPerEpoch:2*slotsPerEpoch])
for i := slotsPerEpoch; i < primitives.Slot(len(b.builderPendingPayments)); i++ {
    b.builderPendingPayments[i] = emptyBuilderPendingPayment
}
```

In-place rotation via `copy` + zero-fill loop with a shared `emptyBuilderPendingPayment` reference. Filter predicate inverted (`if quorum > payment.Weight { continue }`) for the same observable behaviour as `weight >= quorum`. Call site at `core/transition/gloas.go:173`.

H1 ✓. H2 ✓. H3 ✓ (inverted but equivalent). H4 ✓. H5 ✓. H6 ✓. H7 ✓ (`gloas.go:167-176`). H8 ✓ (`mainnet_config.go:349-350`). H9 ✓ (raw u64).

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_epoch_processing/single_pass.rs:598-633` — `process_builder_pending_payments`:

```rust
fn process_builder_pending_payments<E: EthSpec>(
    state: &mut BeaconState<E>,
    state_ctxt: &StateContext,
    spec: &ChainSpec,
) -> Result<(), Error> {
    let quorum = get_builder_payment_quorum_threshold::<E>(state_ctxt, spec)?;

    let new_pending_builder_withdrawals = state
        .builder_pending_payments()?
        .iter()
        .take(E::SlotsPerEpoch::to_usize())
        .filter(|payment| payment.weight >= quorum)
        .map(|payment| payment.withdrawal.clone())
        .collect::<Vec<_>>();
    for payment_withdrawal in new_pending_builder_withdrawals {
        state.builder_pending_withdrawals_mut()?.push(payment_withdrawal)?;
    }

    let updated_payments = state
        .builder_pending_payments()?
        .iter()
        .skip(E::SlotsPerEpoch::to_usize())
        .cloned()
        .chain((0..E::SlotsPerEpoch::to_usize()).map(|_| BuilderPendingPayment::default()))
        .collect::<Vec<_>>();
    *state.builder_pending_payments_mut()? = Vector::new(updated_payments)?;

    Ok(())
}
```

`get_builder_payment_quorum_threshold` at `:584-595` uses overflow-checked `safe_*` arithmetic:

```rust
let per_slot_balance = state_ctxt.total_active_balance.safe_div(E::slots_per_epoch())?;
let quorum = per_slot_balance.safe_mul(spec.builder_payment_threshold_numerator)?;
quorum.safe_div(spec.builder_payment_threshold_denominator).map_err(Error::from)
```

Two-borrow workaround pattern: collect qualifying withdrawals into a `Vec` first (to release the `builder_pending_payments` immutable borrow), then push each one. Rotation rebuilds the entire `Vector` with `skip(SLOTS_PER_EPOCH).chain(default × SLOTS_PER_EPOCH)`.

Call site at `:476` — `process_builder_pending_payments` is called inside the omnibus single-pass epoch processor, gated on `fork_name.gloas_enabled() && conf.builder_pending_payments`.

H1 ✓ (`.take(SlotsPerEpoch)`). H2 ✓. H3 ✓. H4 ✓ (`.map(|payment| payment.withdrawal.clone())`). H5 ✓ (`.skip` + `.chain(default)`). H6 ✓ (`Vector::new` enforces the type-level length). H7 ✓. H8 ✓ (`chain_spec.rs:1271, 1694`). H9 ✓ (overflow-checked).

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/statetransition/epoch/EpochProcessorGloas.java:83-106` — `processBuilderPendingPayments`:

```java
@Override
public void processBuilderPendingPayments(final MutableBeaconState state) {
  final UInt64 quorum = beaconStateAccessorsGloas.getBuilderPaymentQuorumThreshold(state);
  final MutableBeaconStateGloas stateGloas = MutableBeaconStateGloas.required(state);
  final SszMutableVector<BuilderPendingPayment> builderPendingPayments =
      stateGloas.getBuilderPendingPayments();
  IntStream.range(0, specConfig.getSlotsPerEpoch())
      .forEach(
          i -> {
            final BuilderPendingPayment payment = builderPendingPayments.get(i);
            if (payment.getWeight().isGreaterThanOrEqualTo(quorum)) {
              stateGloas.getBuilderPendingWithdrawals().append(payment.getWithdrawal());
            }
          });
  final List<BuilderPendingPayment> oldPayments =
      new ArrayList<>(
          builderPendingPayments
              .asList()
              .subList(specConfig.getSlotsPerEpoch(), builderPendingPayments.size()));
  final List<BuilderPendingPayment> newPayments =
      Collections.nCopies(
          specConfig.getSlotsPerEpoch(),
          builderPendingPayments.getSchema().getElementSchema().getDefault());
  builderPendingPayments.setAll(Iterables.concat(oldPayments, newPayments));
}
```

`getBuilderPaymentQuorumThreshold` at `BeaconStateAccessorsGloas.java:289-293`:

```java
final UInt64 perSlotBalance = getTotalActiveBalance(state).dividedBy(config.getSlotsPerEpoch());
final UInt64 quorum = perSlotBalance.times(SpecConfigGloas.BUILDER_PAYMENT_THRESHOLD_NUMERATOR);
return quorum.dividedBy(SpecConfigGloas.BUILDER_PAYMENT_THRESHOLD_DENOMINATOR);
```

Uses `UInt64.dividedBy/times` (saturating semantics on overflow). Subclass override polymorphism: `EpochProcessorGloas extends EpochProcessorFulu` with `@Override`. Call site at `AbstractEpochProcessor.java:137`. Rotation idiom: build `oldPayments` from `subList(SLOTS_PER_EPOCH, size)`, build `newPayments` from `Collections.nCopies(SLOTS_PER_EPOCH, default)`, then `setAll(Iterables.concat(...))`.

H1 ✓. H2 ✓. H3 ✓ (`isGreaterThanOrEqualTo`). H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (`SpecConfigGloas.java:24-25`). H9 ✓ (UInt64 saturating).

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_epoch.nim:1384-1404` — `process_builder_pending_payments*`:

```nim
func process_builder_pending_payments*(
    cfg: RuntimeConfig,
    state: var (gloas.BeaconState | heze.BeaconState),
    cache: var StateCache): Result[void, cstring] =
  ## Processes the builder pending payments from the previous epoch.
  let quorum = get_builder_payment_quorum_threshold(state, cache)

  for index in 0 ..< min(
      state.builder_pending_payments.len, SLOTS_PER_EPOCH.int):
    var payment = state.builder_pending_payments.mitem(index)
    if payment.weight.distinctBase >= quorum:
      if not state.builder_pending_withdrawals.add(payment.withdrawal):
        return err("process_builder_pending_payments: couldn't add to builder_pending_withdrawals")

  staticFor i, 0 ..< SLOTS_PER_EPOCH.int:
    assign(
      state.builder_pending_payments.mitem(i),
      state.builder_pending_payments.item(i + SLOTS_PER_EPOCH))
    state.builder_pending_payments.mitem(i + SLOTS_PER_EPOCH).reset()

  ok()
```

`get_builder_payment_quorum_threshold` at `:1375-1381`:

```nim
let quorum = (
  get_total_active_balance(state, cache) div SLOTS_PER_EPOCH * BUILDER_PAYMENT_THRESHOLD_NUMERATOR)
uint64(quorum div BUILDER_PAYMENT_THRESHOLD_DENOMINATOR)
```

Compile-time `staticFor` unrolls the rotation loop (32 iterations on mainnet). `payment.weight.distinctBase >= quorum` strips the `Gwei` newtype wrapper for comparison. `state.builder_pending_withdrawals.add(...)` returns `bool` (false on capacity-exceeded → propagated as `Result.err`). Call site at `state_transition_epoch.nim:1675` — after `process_pending_consolidations`, before `process_effective_balance_updates`.

H1 ✓ (`min(.len, SLOTS_PER_EPOCH.int)` defensive cap). H2 ✓. H3 ✓. H4 ✓. H5 ✓ (`assign` + `reset`). H6 ✓ (defensive `min`). H7 ✓. H8 ✓ (`constants.nim:102`). H9 ✓ (raw u64).

### lodestar

`vendor/lodestar/packages/state-transition/src/epoch/processBuilderPendingPayments.ts` — `processBuilderPendingPayments`:

```typescript
export function processBuilderPendingPayments(state: CachedBeaconStateGloas): void {
  const quorum = getBuilderPaymentQuorumThreshold(state);

  for (let i = 0; i < SLOTS_PER_EPOCH; i++) {
    const payment = state.builderPendingPayments.get(i);
    if (payment.weight >= quorum) {
      state.builderPendingWithdrawals.push(payment.withdrawal);
    }
  }

  // TODO GLOAS: Optimize this
  for (let i = 0; i < state.builderPendingPayments.length; i++) {
    if (i < SLOTS_PER_EPOCH) {
      state.builderPendingPayments.set(i, state.builderPendingPayments.get(i + SLOTS_PER_EPOCH).clone());
    } else {
      state.builderPendingPayments.set(i, ssz.gloas.BuilderPendingPayment.defaultViewDU());
    }
  }
}
```

`getBuilderPaymentQuorumThreshold` at `util/gloas.ts:28-34`:

```typescript
const quorum =
  Math.floor((state.epochCtx.totalActiveBalanceIncrements * EFFECTIVE_BALANCE_INCREMENT) / SLOTS_PER_EPOCH) *
  BUILDER_PAYMENT_THRESHOLD_NUMERATOR;
return Math.floor(quorum / BUILDER_PAYMENT_THRESHOLD_DENOMINATOR);
```

Uses cached `totalActiveBalanceIncrements * EFFECTIVE_BALANCE_INCREMENT` to reconstitute the gwei balance from the cached increment-count. **JS `number` (IEEE 754 double) at this magnitude (~3e16 gwei at mainnet 30M ETH stake) sits above `Number.MAX_SAFE_INTEGER = 2^53 - 1 ≈ 9.007e15`** — precision granularity is 4 at this range. In practice, `total_active_balance` is always a multiple of `EFFECTIVE_BALANCE_INCREMENT = 1e9`, and the multiplication is exactly representable at current mainnet stake (no observable loss). Forward-fragility at higher stake levels (Pattern HH cousin). Rotation idiom: in-place `for`-loop covering all `state.builderPendingPayments.length` slots, splitting on `i < SLOTS_PER_EPOCH` to shift or default. Call site at `epoch/index.ts:168`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (`push(payment.withdrawal)`). H5 ✓. H6 ✓ (relies on `state.builderPendingPayments.length == 2*SLOTS_PER_EPOCH` invariant). H7 ✓. H8 ✓ (`params/src/index.ts:321-322`). **H9 partial** (IEEE 754 forward-fragility at extreme stake levels; mainnet-OK today).

### grandine

`vendor/grandine/transition_functions/src/gloas/epoch_processing.rs:206-236` — `process_builder_pending_payments`:

```rust
fn process_builder_pending_payments<P: Preset>(
    state: &mut impl PostGloasBeaconState<P>,
) -> Result<()> {
    let quorum = get_builder_payment_quorum_threshold(state);
    let payments = state
        .builder_pending_payments()
        .into_iter()
        .copied()
        .collect_vec();

    for payment in payments.iter().take(P::SlotsPerEpoch::USIZE) {
        if payment.weight >= quorum {
            state.builder_pending_withdrawals_mut().push(payment.withdrawal)?;
        }
    }

    *state.builder_pending_payments_mut() = PersistentVector::try_from_iter(
        payments
            .into_iter()
            .skip(P::SlotsPerEpoch::USIZE)
            .chain(core::iter::repeat_n(
                BuilderPendingPayment::default(),
                P::SlotsPerEpoch::USIZE,
            ))
            .take(BuilderPendingPaymentsLength::<P>::USIZE),
    )?;

    Ok(())
}
```

`get_builder_payment_quorum_threshold` at `helper_functions/src/accessors.rs:1167-1176`:

```rust
let active_balances = total_active_balance(state);
let quorum = active_balances
    .saturating_div(P::SlotsPerEpoch::U64)
    .saturating_mul(BUILDER_PAYMENT_THRESHOLD_NUMERATOR);
quorum.saturating_div(BUILDER_PAYMENT_THRESHOLD_DENOMINATOR)
```

`saturating_*` arithmetic (overflow ⇒ `u64::MAX`, never panics). Rotation: rebuild the `PersistentVector` from `iter.skip(SLOTS_PER_EPOCH).chain(default × SLOTS_PER_EPOCH).take(2*SLOTS_PER_EPOCH)`. Filtering reads `payment.weight` from the cloned `Vec` to avoid borrow conflict with `state.builder_pending_withdrawals_mut()`. Call site at `gloas/epoch_processing.rs:78`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (`push(payment.withdrawal)`). H5 ✓ (`skip + chain(default).take`). H6 ✓ (`.take(BuilderPendingPaymentsLength::<P>::USIZE)`). H7 ✓. H8 ✓ (`types/src/gloas/consts.rs:72`). H9 ✓ (saturating).

## Cross-reference table

| Client | `process_builder_pending_payments` location | Quorum threshold idiom | Filter idiom | Rotation idiom | Arithmetic safety |
|---|---|---|---|---|---|
| prysm | `core/gloas/pending_payment.go:28-58` | raw `(active/SLOTS_PER_EPOCH) * 6 / 10` | inverted `if quorum > weight: continue` | `copy()` first half ← second half, then zero-fill loop (`setters_gloas.go:25-43`) | unchecked u64 |
| lighthouse | `per_epoch_processing/single_pass.rs:598-633` | `safe_div`/`safe_mul`/`safe_div` | iter.take.filter.map.collect → push loop | `iter.skip(SPE).chain(default × SPE).collect` → `Vector::new` | overflow-checked |
| teku | `EpochProcessorGloas.java:83-106` | `UInt64.dividedBy/times` | `IntStream.range.forEach` with `isGreaterThanOrEqualTo` | `subList(SPE, size) + nCopies(SPE, default)` → `setAll(Iterables.concat)` | UInt64 saturating |
| nimbus | `state_transition_epoch.nim:1384-1404` | raw `div`/`*`/`div` with `.distinctBase` | `for index in 0..<min(.len, SPE)` with `if .. >= ..` | compile-time `staticFor i, 0..<SPE` with `assign + reset` | raw u64 |
| lodestar | `state-transition/src/epoch/processBuilderPendingPayments.ts` | `Math.floor((tab_inc * EBI) / SPE) * 6 → Math.floor(/10)` | `for i in 0..SPE` with `if >= ` | full-length `for` with split on `i < SPE` (set+clone vs default) | IEEE 754 double (forward-fragile) |
| grandine | `transition_functions/src/gloas/epoch_processing.rs:206-236` | `saturating_div/_mul/_div` | iter.take.filter then `push` | `iter.skip(SPE).chain(default × SPE).take(2*SPE)` → `PersistentVector::try_from_iter` | saturating u64 |

## Empirical tests

The EF spec-test corpus has dedicated fixtures at `vendor/consensus-spec-tests/tests/mainnet/gloas/epoch_processing/builder_pending_payments/pyspec_tests/` (verified by `grandine/transition_functions/src/gloas/epoch_processing.rs:484` `mainnet_process_builder_pending_payments` test wrapper and `prysm/testing/spectest/mainnet/gloas__epoch_processing__process_builder_pending_payments_test.go`). These fixtures are **NOT wired** into BeaconBreaker's runner harness today — wiring them would convert this audit's source-only conclusion into an empirical cross-client equivalence test.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (canonical settle).** Gloas state with one entry at `state.builder_pending_payments[0]` whose `weight` satisfies the quorum threshold. Expected: append to `builder_pending_withdrawals`, then rotate. Cross-client `state_root` should match.
- **T1.2 (canonical discard).** Same state but `weight` below threshold. Expected: skip, then rotate.
- **T1.3 (boundary — weight exactly at threshold).** Probe `weight == threshold` (should settle per `>=`) and `weight == threshold - 1` (should discard). Identifies any off-by-one in the comparison operator.
- **T1.4 (multi-slot mixed).** All 32 older-half slots populated; half above quorum, half below. Verifies per-entry independence and the resulting `builder_pending_withdrawals` order matches iteration order.

#### T2 — Adversarial probes
- **T2.1 (extreme stake overflow probe).** Synthetic state with `total_active_balance` near `u64::MAX / BUILDER_PAYMENT_THRESHOLD_NUMERATOR`. Probes the multiplication-overflow path. Pattern HH cousin: lighthouse propagates an error (`safe_mul` returns `Err`); teku saturates to `UInt64.MAX`; prysm wraps; nimbus wraps; lodestar reaches IEEE 754 precision-loss territory; grandine saturates to `u64::MAX`. Currently unreachable on mainnet (would need ~120 M ETH staked × 1e10 to overflow), but document the divergent failure modes.
- **T2.2 (capacity-exceeded on `builder_pending_withdrawals`).** `state.builder_pending_withdrawals` near `BUILDER_PENDING_WITHDRAWALS_LIMIT`, plus 32 qualifying payments in the older half. Verify all six clients handle the `.push()` capacity-exceeded case identically (return error vs silent-truncate vs panic).
- **T2.3 (default `BuilderPendingPayment` byte-equivalence).** Compare the default value used in the rotation across clients. SSZ-level byte-equivalence of `BuilderPendingPayment::default()` / `getDefault()` / `defaultViewDU()` / `reset()` / `emptyBuilderPendingPayment`. Verify Merkle root matches across all six.
- **T2.4 (lodestar IEEE 754 quorum precision).** At 30 M ETH stake, `totalActiveBalanceIncrements * EFFECTIVE_BALANCE_INCREMENT = 3e16` is above `Number.MAX_SAFE_INTEGER`. Verify the quorum value computed in lodestar is byte-identical to the other 5 clients' u64-arithmetic output. (Currently passes because `(N*1e9)` for typical N happens to be exactly representable, but document the safety margin.)

## Conclusion

**Status: source-code-reviewed.** All six clients implement `process_builder_pending_payments` and the supporting `get_builder_payment_quorum_threshold` identically at the spec-conformance level. The function body decomposes to (1) compute quorum, (2) filter older-half by `weight >= quorum` and append qualifying `payment.withdrawal` to `state.builder_pending_withdrawals`, (3) rotate the ring buffer (older half ← newer half; newer half ← default). The position in `process_epoch` is uniform: after `process_pending_consolidations`, before `process_effective_balance_updates`. The quorum threshold constants `BUILDER_PAYMENT_THRESHOLD_NUMERATOR = 6` and `BUILDER_PAYMENT_THRESHOLD_DENOMINATOR = 10` are correctly present in every client config.

**Impact: none.** No observable cross-client divergence on canonical Gloas state. The audit catalogues six distinct rotation idioms (Go `copy`+zero-fill, Rust `Vector::new` rebuild, Java `subList`+`nCopies`+`setAll`, Nim compile-time `staticFor`, TypeScript in-place `for` with ViewDU clone, Rust `PersistentVector::try_from_iter`) and six distinct filtering idioms — all observably equivalent.

**Forward-fragility observations:**

1. **Lodestar IEEE 754 path** — `totalActiveBalanceIncrements * EFFECTIVE_BALANCE_INCREMENT` produces a value above `Number.MAX_SAFE_INTEGER` at typical mainnet stake. Currently observable-equivalent because `total_active_balance` is always a multiple of `EFFECTIVE_BALANCE_INCREMENT` and the products land on exactly-representable doubles, but precision degrades at higher stake levels. Pattern HH-adjacent.
2. **Divergent overflow policies** in `get_builder_payment_quorum_threshold`: prysm/nimbus wrap on u64 overflow, lighthouse errors (`safe_mul` → `Err`), grandine/teku saturate. Practically irrelevant at mainnet stake (overflow would require ~120 M ETH × 1e10), but the divergent error-vs-saturate-vs-wrap modes are a forward-fragility class worth documenting.
3. **Capacity-exceeded handling** on `state.builder_pending_withdrawals.push()`: prysm's `append` is unbounded slice append; lighthouse returns `Err` on `push`-into-`List`; teku's `append` on SSZ list may throw; nimbus returns `false` (caught into Result.err); lodestar's ViewDU push is unbounded; grandine returns `Err`. At `BUILDER_PENDING_WITHDRAWALS_LIMIT` capacity (TBD value), behaviour diverges.

Recommendations:

- **Wire `epoch_processing/builder_pending_payments` EF fixtures** into BeaconBreaker. The fixtures exist (verified via prysm's spectest at `testing/spectest/mainnet/gloas__epoch_processing__process_builder_pending_payments_test.go` and grandine's `mainnet_process_builder_pending_payments` test wrapper). Wiring them would convert this source-only audit to an empirical cross-client equivalence test.
- **Generate T2.1 overflow-probe fixture** to document the divergent failure modes pre-emptively (forward-fragility hedge).
- **Generate T2.2 capacity-exceeded fixture** as a sister test on `BUILDER_PENDING_WITHDRAWALS_LIMIT`.

## Cross-cuts

### With item #7 H10 (`process_attestation` builder-payment weight writer)

Item #7 H10 increments `state.builder_pending_payments[slot_idx].weight` from same-slot attestations that set new participation flags. This item consumes those weight values at the next epoch boundary. With item #7 H10 closed (uniform across all six clients), the input to this helper is uniform. The two items together form the producer/consumer pair for the same `state.builder_pending_payments` field.

### With item #12 H11 (`process_withdrawals` Phase A drain)

Item #12 H11's Phase A drains `state.builder_pending_withdrawals` — the HashList this helper appends to. Sequence: this item settles into the HashList at epoch boundary N; item #12 Phase A drains it at block N+1. Round-trip from bid → weight → settlement → withdrawal.

### With item #9 H9 (`process_proposer_slashing` BuilderPendingPayment clearing)

Item #9 H9 clears a `BuilderPendingPayment` entry (zeroing `weight` and `withdrawal`) when its proposer is slashed within the 2-epoch window. Race: if the slashing happens in the same epoch as the settlement, this helper sees a zeroed entry (`weight = 0 < quorum`) and discards. Cross-cut on the within-block operation ordering — the slashing happens block-time, this helper runs epoch-time, so the slash always wins.

### With item #19 (`process_execution_payload_bid`)

Item #19's `process_execution_payload_bid` writes the bid into `state.builder_pending_payments[SLOTS_PER_EPOCH + slot % SLOTS_PER_EPOCH]` (the newer half). Two epochs later, this helper consumes it from the older half (after one rotation). Lifecycle: bid (item #19, block-time) → weight accumulation (item #7 H10, attestation-time) → settlement (this item, epoch boundary) → withdrawal (item #12 H11, block-time).

### With `settle_builder_payment` (Gloas-new state mutator)

Spec defines `settle_builder_payment` as a state mutator separately, but this helper inlines the equivalent logic (`state.builder_pending_withdrawals.append(payment.withdrawal)`). None of the six clients call a distinct `settle_builder_payment` function — they all inline. Audit sister item: standalone `settle_builder_payment` audit.

### With `process_ptc_window` (Gloas-new epoch helper)

Sibling Gloas-new epoch helper at the end of `process_epoch`. Both rotate ring buffers (`builder_pending_payments` here; `ptc_window` there). Item #60 audits `process_ptc_window`.

## Adjacent untouched

1. **Wire `epoch_processing/builder_pending_payments` EF fixtures** into BeaconBreaker's runner harness.
2. **`BUILDER_PENDING_WITHDRAWALS_LIMIT` capacity-exceeded behaviour** — cross-client divergent failure modes (T2.2).
3. **`BuilderPendingPayment::default()` byte-equivalence** across clients (T2.3) — Pattern AA cousin (SSZ container default values).
4. **`get_builder_payment_quorum_threshold` overflow policy divergence** (T2.1) — Pattern HH cousin (numeric overflow at extreme inputs).
5. **`settle_builder_payment` standalone audit** — spec defines it as a state mutator, but all six clients inline. Verify the inline-vs-spec semantic match.
6. **Position-in-`process_epoch` invariant test** — a sanity_blocks fixture that includes a slashing in epoch N (item #9 H9), an attestation setting weight in epoch N (item #7 H10), and verifies the epoch-boundary processing order: slashing clears → attestation accumulates → epoch boundary settles or discards based on the post-slashing weight.
7. **Lodestar `totalActiveBalanceIncrements` cache invalidation** — verify the cache is current at the moment this helper reads it.
8. **Pattern HH: lodestar IEEE 754 forward-fragility at >9M ETH staked** — formal verification at synthetic stake levels.
