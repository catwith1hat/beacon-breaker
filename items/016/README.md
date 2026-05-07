# Item #16 — `compute_exit_epoch_and_update_churn` + `compute_consolidation_epoch_and_update_churn` (Pectra-NEW per-block churn-budget primitives)

**Status:** no-divergence-pending-fuzzing — audited 2026-05-02. The
**chokepoint Pectra primitives** that all three Track A operations
(items #2/#3/#6) plus slashing-induced exits (items #8/#9) flow
through. Item #6 explicitly flagged as "highest-leverage primitive,
used by 3+ items now."

## Why this item

Pectra introduces **churn-paced exit and consolidation** to replace
Phase0's per-validator counter (`get_validator_churn_limit`). Instead
of "max N validators exit per epoch," Pectra meters by **balance**:
"max X gwei of exit per epoch." The implementing primitives are:

```python
def compute_exit_epoch_and_update_churn(state, exit_balance) -> Epoch:
    earliest_exit_epoch = max(state.earliest_exit_epoch, compute_activation_exit_epoch(current_epoch))
    per_epoch_churn = get_activation_exit_churn_limit(state)

    if state.earliest_exit_epoch < earliest_exit_epoch:        # NEW EPOCH
        exit_balance_to_consume = per_epoch_churn              # Reset full budget
    else:                                                       # SAME EPOCH (carry over)
        exit_balance_to_consume = state.exit_balance_to_consume

    if exit_balance > exit_balance_to_consume:                  # Doesn't fit this epoch
        balance_to_process = exit_balance - exit_balance_to_consume
        additional_epochs = (balance_to_process - 1) // per_epoch_churn + 1   # CEIL DIV
        earliest_exit_epoch += additional_epochs
        exit_balance_to_consume += additional_epochs * per_epoch_churn

    state.exit_balance_to_consume = exit_balance_to_consume - exit_balance
    state.earliest_exit_epoch = earliest_exit_epoch
    return state.earliest_exit_epoch
```

`compute_consolidation_epoch_and_update_churn` is **structurally
identical** with `_consolidation_*` field substitutions and a
different churn-limit selector.

The three layers of churn-limit helpers:

```python
def get_balance_churn_limit(state) -> Gwei:
    churn = max(MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA = 128 ETH,
                get_total_active_balance(state) // CHURN_LIMIT_QUOTIENT = 65536)
    return churn - churn % EFFECTIVE_BALANCE_INCREMENT      # Round DOWN to 1-ETH increment

def get_activation_exit_churn_limit(state) -> Gwei:
    return min(MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT = 256 ETH, get_balance_churn_limit(state))

def get_consolidation_churn_limit(state) -> Gwei:
    return get_balance_churn_limit(state) - get_activation_exit_churn_limit(state)
```

These primitives are called from:
- **item #2** `process_consolidation_request` → `compute_consolidation_epoch_and_update_churn`
- **item #3** `process_withdrawal_request` (partial) → `compute_exit_epoch_and_update_churn`
- **item #6** `initiate_validator_exit` (called by `process_voluntary_exit`) → `compute_exit_epoch_and_update_churn`
- **item #8** `slash_validator` → `initiate_validator_exit` → `compute_exit_epoch_and_update_churn`
- **item #9** `slash_validator` → `initiate_validator_exit` → `compute_exit_epoch_and_update_churn`

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | `get_balance_churn_limit` formula: `max(MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA = 128 ETH, total_balance / CHURN_LIMIT_QUOTIENT = 65536)`, then DOWNWARD-rounded to `EFFECTIVE_BALANCE_INCREMENT = 1 ETH` | ✅ all 6 |
| H2 | `get_activation_exit_churn_limit = min(MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT = 256 ETH, balance_churn)` | ✅ all 6 |
| H3 | `get_consolidation_churn_limit = balance_churn - activation_exit_churn` (residual budget model) | ✅ all 6 (Electra path); ⚠️ lodestar Gloas uses **independent quotient** `CONSOLIDATION_CHURN_LIMIT_QUOTIENT` — Gloas-fork divergence, not Pectra |
| H4 | `compute_exit_epoch_and_update_churn` picks `max(state.earliest_exit_epoch, compute_activation_exit_epoch(current))` for the epoch (LATER value) | ✅ all 6 |
| H5 | New-epoch detection uses STRICT `<` inequality: `state.earliest_exit_epoch < earliest_exit_epoch` (NOT `<=` or `!=`) | ✅ all 6 |
| H6 | New-epoch reset assigns the FULL `per_epoch_churn` budget; same-epoch carries over `state.exit_balance_to_consume` | ✅ all 6 |
| H7 | Ceiling-division formula: `(balance_to_process - 1) // per_epoch_churn + 1` (NOT just `balance / churn` which truncates) | ✅ all 6 |
| H8 | `balance_to_process > 0` precondition guaranteed by the `if exit_balance > exit_balance_to_consume` guard (prevents subtraction underflow) | ✅ all 6 |
| H9 | State mutation order: write `exit_balance_to_consume = (consumed - exit_balance)` then `earliest_exit_epoch = earliest_exit_epoch`, then return | ✅ all 6 |
| H10 | Subtraction `consumed - exit_balance` cannot underflow because `consumed >= exit_balance` is invariant after the if-block | ✅ all 6 (verified by construction) |
| H11 | `compute_consolidation_*` is structurally identical with `_consolidation_*` substitutions and `get_consolidation_churn_limit` selector | ✅ all 6 |

## Per-client cross-reference

| Client | get_balance_churn_limit | compute_exit_*_churn | compute_consolidation_*_churn | Co-location |
|---|---|---|---|---|
| **prysm** | `core/helpers/validator_churn.go:22-28` | `state-native/setters_churn.go:62-93` (with locking) | `core/electra/churn.go:40-85` (DIFFERENT file) | **Asymmetric**: exit in state-setter file, consolidation in core/electra |
| **lighthouse** | `types/src/state/beacon_state.rs:2623-2631` | `:2708-2751` | `:2753-2798` | Co-located in beacon_state.rs |
| **teku** | `versions/electra/helpers/BeaconStateAccessorsElectra.java:85-91` | `BeaconStateMutatorsElectra.java:77-104` | `:135-168` | Co-located in MutatorsElectra |
| **nimbus** | `spec/beaconstate.nim:253-262` | `:286-314` | `:317-345` | Co-located in beaconstate.nim |
| **lodestar** | `state-transition/src/util/validator.ts:66-78` | `state-transition/src/util/epoch.ts:50-76` | `:78-108` | Co-located in epoch.ts |
| **grandine** | `helper_functions/src/accessors.rs:954-960` | `helper_functions/src/mutators.rs:177-209` | `:211-248` | Co-located in mutators.rs |

## Notable per-client divergences (all observable-equivalent at Pectra)

### prysm: asymmetric file placement (exit vs consolidation)

The exit version lives in `state-native/setters_churn.go:62-93` —
acquires a lock, mutates state directly, marks fields dirty. The
consolidation version lives in `core/electra/churn.go:40-85` — uses
public setter methods (`SetEarliestConsolidationEpoch`,
`SetConsolidationBalanceToConsume`) which internally lock. **Same
algorithm, different code paths**.

Additionally, the consolidation version uses explicit `math.Div64`
with division-by-zero check; the exit version uses inline Go integer
division relying on the `perEpochChurn > 0` precondition (commented
inline). Two distinct defensiveness levels for the same operation.

```go
// EXIT (inline):
additionalEpochs := primitives.Epoch((balanceToProcess-1)/perEpochChurn + 1)

// CONSOLIDATION (math.Div64 with overflow check):
additionalEpochs, err := math.Div64(uint64(balanceToProcess-1), uint64(perEpochConsolidationChurn))
if err != nil { return 0, err }
additionalEpochs++
```

Both produce identical results for valid inputs; the consolidation
form has stricter overflow handling.

### lighthouse: explicit fork-name guards in BOTH compute functions

```rust
match self {
    BeaconState::Base(_) | BeaconState::Altair(_) | BeaconState::Bellatrix(_)
    | BeaconState::Capella(_) | BeaconState::Deneb(_) => {
        Err(BeaconStateError::IncorrectStateVariant)
    }
    BeaconState::Electra(_) | BeaconState::Fulu(_) | BeaconState::Gloas(_) => {
        // ... actual mutation ...
    }
}
```

Lighthouse explicitly REJECTS pre-Electra state variants in BOTH
functions. Other clients use type-level dispatch (Rust trait bounds,
Nim union types, TypeScript fork conditionals) — but lighthouse's
explicit match is the most defensive against any caller bypassing
the type system.

### teku: `minusMinZero` saturating subtraction throughout

```java
state.setExitBalanceToConsume(
    exitBalanceToConsume.plus(additionalEpochs.times(perEpochChurn))
        .minusMinZero(exitBalance));
```

teku's `minusMinZero` returns 0 instead of underflowing. **Per H10,
the subtraction `consumed - exit_balance` cannot underflow** by
algorithm invariant — but teku's saturating semantics would mask any
bug that violated this invariant by silently producing 0. Other
clients (lighthouse `safe_sub`, grandine raw `-` with type-system
guarantees, prysm raw `-`, nimbus raw `-`, lodestar Number arithmetic)
would either error or panic on underflow. Worth flagging as a
defensive-but-bug-masking pattern.

### nimbus: union-type direct dispatch, no fork conditionals

```nim
func compute_exit_epoch_and_update_churn*(
    cfg: RuntimeConfig,
    state: var (electra.BeaconState | fulu.BeaconState | gloas.BeaconState),
    exit_balance: Gwei,
    cache: var StateCache): Epoch =
```

Nimbus accepts a Nim union type `electra | fulu | gloas`
directly — no `when consensusFork` blocks needed because the type
itself enforces the precondition. **Cleanest fork-dispatch idiom of
the six** for these primitives.

### lodestar: Gloas-fork divergence in `getConsolidationChurnLimit`

```typescript
export function getConsolidationChurnLimit(fork: ForkSeq, epochCtx: EpochCache): number {
  if (fork >= ForkSeq.gloas) {
    // Gloas: independent quotient, NO MIN floor
    return getBalanceChurnLimit(
      epochCtx.totalActiveBalanceIncrements,
      epochCtx.config.CONSOLIDATION_CHURN_LIMIT_QUOTIENT,    // DIFFERENT QUOTIENT
      0                                                       // NO MIN floor
    );
  }
  // Pectra: residual model
  return getBalanceChurnLimitFromCache(epochCtx) - getActivationExitChurnLimit(epochCtx);
}
```

At **Pectra/Electra**, lodestar correctly uses the residual model
(`balance_churn - activation_exit_churn`).

At **Gloas**, lodestar switches to an INDEPENDENT
`CONSOLIDATION_CHURN_LIMIT_QUOTIENT` quotient with NO MIN floor.
This matches a Gloas-fork-only spec change (consolidation budget
becomes independent of activation/exit budget). **Forward-compat
note**: other clients may NOT have this Gloas-aware divergence yet;
worth a Gloas audit.

### lodestar: BigInt-Number coercion in compute functions

```typescript
let exitBalanceToConsume =
    state.earliestExitEpoch < earliestExitEpoch ? perEpochChurn : Number(state.exitBalanceToConsume);
if (exitBalance > exitBalanceToConsume) {
    const balanceToProcess = Number(exitBalance) - exitBalanceToConsume;
    const additionalEpochs = Math.floor((balanceToProcess - 1) / perEpochChurn) + 1;
    // ...
}
state.exitBalanceToConsume = BigInt(exitBalanceToConsume) - exitBalance;
```

`exitBalance` is `Gwei` (BigInt); `perEpochChurn` is `number`. The
intermediate arithmetic uses `Number` conversion, then re-converts to
`BigInt` for state mutation. **Safe today** because all gwei values
in flight here are <2^53 (max active balance × MAX_VALIDATORS), but
the type-system mismatch is forward-fragile. Same concern as items
#15 (requestsHash) and #14 (deposit_request).

### grandine: `prev_multiple_of` is the cleanest downward-rounding idiom

```rust
churn.prev_multiple_of(P::EFFECTIVE_BALANCE_INCREMENT)
```

vs. other clients' explicit `churn - churn % increment` formulation.
Same result, more concise and self-documenting. Uses Rust's
`NonZeroU64` for the divisor (compile-time guarantee against
divide-by-zero panic).

### grandine: SINGLE definition of each function

Confirmed: grandine has ONE `compute_exit_epoch_and_update_churn`
(line 177) and ONE `compute_consolidation_epoch_and_update_churn`
(line 211) in `mutators.rs`. **NO multi-fork-definition risk** like
items #6/#9/#10/#12/#14. Notable consistency for high-leverage
primitives.

### grandine: `total_active_balance` extraction from cache

```rust
pub fn get_balance_churn_limit<P: Preset>(config: &Config, state: &impl BeaconState<P>) -> Gwei {
    let churn = total_active_balance(state)
        .div(config.churn_limit_quotient)
        .max(config.min_per_epoch_churn_limit_electra);
    churn.prev_multiple_of(P::EFFECTIVE_BALANCE_INCREMENT)
}
```

Grandine's `total_active_balance(state)` reads from a cache. Other
clients call `get_total_active_balance(state)` which iterates
validators. Performance optimization — the cache is invalidated
appropriately (per item #11's audit), so no correctness concern.

## EF fixture status — implicit coverage via Track A items + slashings

**No dedicated EF fixture exists** for `compute_exit_epoch_and_update_churn`
or `compute_consolidation_epoch_and_update_churn` as standalone
operations. They are exercised IMPLICITLY via:

| Item | Fixtures × clients | Calls primitive |
|---|---|---|
| **#2** consolidation_request | 10 × 4 = 40 | `compute_consolidation_epoch_and_update_churn` |
| **#3** withdrawal_request | 19 × 4 = 76 | `compute_exit_epoch_and_update_churn` (partial path) |
| **#6** voluntary_exit | 25 × 4 = 100 | `compute_exit_epoch_and_update_churn` (via initiate_validator_exit) |
| **#8** attester_slashing | 30 × 4 = 120 | `compute_exit_epoch_and_update_churn` (via slash_validator → initiate_validator_exit) |
| **#9** proposer_slashing | 15 × 4 = 60 | same as #8 |

**Total implicit cross-validation evidence**: **396 EF fixture
PASSes** across 99 unique fixtures all flow through one of the two
primitives. Any algorithm divergence (wrong inequality, wrong
ceiling-division, wrong state mutation order, wrong helper selector)
would have surfaced as a fixture failure in at least one of these
items. None did.

A dedicated fixture set for the primitives would consist of:
1. Pre-state with known `earliest_exit_epoch` /
   `exit_balance_to_consume` values.
2. Single call with known `exit_balance` argument.
3. Expected post-state values + return value (epoch).

This is **directly fuzzable** — the algorithm is purely state +
input → state + output, no signatures, no BLS, no SSZ. Worth
generating as a follow-up.

## Cross-cut chain — chokepoint primitive for 5 audit items

These two primitives sit at the **center** of the Pectra Track A +
slashings call graph:

```
  [#6 voluntary_exit]                [#3 withdrawal_request (partial)]
         ↓                                       ↓
  initiate_validator_exit ────────────┐    [#2 consolidation_request (main)]
         ↑                            ↓                  ↓
  [#8 attester_slashing]    compute_exit_epoch_      compute_consolidation_
  [#9 proposer_slashing]      and_update_churn       epoch_and_update_churn
         ↓                            ↓                  ↓
  slash_validator              state.earliest_         state.earliest_
                              exit_epoch              consolidation_epoch
                              state.exit_             state.consolidation_
                              balance_to_consume      balance_to_consume
```

This audit closes the **per-block churn-budget primitive** layer.
Item #11 (upgrade_to_electra) initialized these state fields; items
#2/#3/#6/#8/#9 produce the requests; THIS audit verifies the
primitives that meter them; the resulting `earliest_*_epoch` values
become the validator's exit_epoch (item #6) or consolidation epoch
(item #2's PendingConsolidation entry, drained by item #5).

## Adjacent untouched

- **Generate dedicated EF fixture set** for the two primitives —
  highest-priority gap closure. Pure function, easy to fuzz.
- **Cross-client byte-for-byte equivalence test** — feed identical
  pre-state + exit_balance to all 6 clients, compare post-state
  fields + return value.
- **Edge case: `exit_balance == exit_balance_to_consume`** — H8 says
  "if exit_balance > exit_balance_to_consume" (STRICT), so equal
  values DON'T trigger the additional-epochs path. The post-state
  becomes `exit_balance_to_consume = 0`, `earliest_exit_epoch`
  unchanged. Verify all clients handle this boundary uniformly.
- **Edge case: `exit_balance == 0`** — what happens? The if-guard
  doesn't fire (0 > anything is false), so post-state becomes
  `exit_balance_to_consume = consumed - 0 = consumed`, `earliest_exit_epoch`
  unchanged, return same epoch. Effectively a no-op. Worth a fixture.
- **Edge case: `exit_balance` extreme (e.g., 2048 ETH × 1000 validators
  = 2.048e15 gwei)** — would consume ~10000 epochs at 256 ETH/epoch
  churn. Verify `additional_epochs` math doesn't overflow.
- **lodestar Gloas-fork `getConsolidationChurnLimit` divergence** —
  uses INDEPENDENT `CONSOLIDATION_CHURN_LIMIT_QUOTIENT` instead of
  the residual model. Other clients may not yet have the Gloas-aware
  fix; worth a Gloas-fork audit.
- **teku's `minusMinZero` saturating subtraction** — masks
  underflow bugs by silently returning 0. Per H10 the subtraction
  cannot underflow by algorithm invariant, but teku's defensive
  semantics would hide any bug that violated the invariant. Worth
  a contract test asserting underflow scenarios are unreachable.
- **prysm's asymmetric file placement** (exit in setters_churn.go,
  consolidation in core/electra/churn.go) — codify the structural
  differences as documentation; future refactor risk if file naming
  conventions shift.
- **lodestar's BigInt-Number coercion** — pre-emptive concern (same
  as items #14 #15) for any future amount-unit change beyond 2^53
  gwei.
- **`MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA = 128 ETH` minimum floor** —
  floors the churn limit to ~128 validators-equivalent per epoch
  even if total active balance is small. Verify this floor is never
  triggered on mainnet (it shouldn't be — mainnet's TAB / 65536
  >> 128 ETH).
- **`MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT = 256 ETH` ceiling
  on activation/exit only** — caps churn at 256 ETH (~8 validators)
  for activations and exits. Consolidations have NO ceiling
  (consolidation_churn = balance_churn - activation_exit_churn).
  Worth verifying the implications for max-throughput consolidation
  scenarios.
- **`compute_activation_exit_epoch(current_epoch)` formula** —
  returns `current_epoch + 1 + MAX_SEED_LOOKAHEAD = current + 5`.
  Cross-cuts EVERY caller of these primitives. Worth standalone
  verification.
- **`get_total_active_balance(state)` cache coherence** — grandine
  reads from a cache; other clients iterate. Cache invalidation at
  the right slot boundary is critical. Item #11 (upgrade) audit
  noted prysm uses pre-state TAB for churn-limit init (documented
  deviation). Worth checking if any caller of these primitives
  hits a stale cache.
- **State field ordering at upgrade**: item #11 initializes
  `earliest_exit_epoch`, `exit_balance_to_consume`,
  `earliest_consolidation_epoch`, `consolidation_balance_to_consume`
  — this audit consumes them. Cross-cut verified by all 396 implicit
  fixture passes.

## Future research items

1. **Generate dedicated EF fixture set** for both primitives —
   highest-priority gap closure. Pure-function, directly fuzzable.
2. **Cross-client byte-for-byte equivalence test** for the post-state
   computation, including all edge cases (boundary, zero, extreme
   exit_balance).
3. **`exit_balance == 0` no-op case** — verify all 6 clients handle
   identically.
4. **`exit_balance == exit_balance_to_consume` boundary case** —
   strict `>` vs `>=` cross-validation.
5. **Extreme exit_balance overflow test** — `exit_balance` up to
   max validator-set total (potentially > 2^53 wei).
6. **lodestar Gloas-fork `getConsolidationChurnLimit` cross-client
   audit** — independent quotient vs residual model at Gloas.
7. **teku's `minusMinZero` underflow-masking contract test** —
   assert algorithm invariants unreachable.
8. **prysm asymmetric file placement** — documentation cleanup.
9. **lodestar BigInt-Number coercion** fuzz target.
10. **`MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA` floor never triggered on
    mainnet** — formal verification.
11. **`MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT` consolidation
    asymmetry** — implications for max-throughput consolidation.
12. **`compute_activation_exit_epoch` standalone audit** — used by
    every Pectra exit/consolidation/activation path.
13. **`get_total_active_balance(state)` cache coherence audit
    across all 6 clients** — invalidation timing at slot boundaries.
14. **Multi-call-same-block stateful fixture**: 3 voluntary exits +
    1 consolidation + 1 partial withdrawal in the same block, all
    consuming the same exit_balance_to_consume budget. Verify
    cross-client churn-state evolution matches exactly.
15. **Cross-cut with item #11**: verify the upgrade-time seeding
    of `exit_balance_to_consume = get_activation_exit_churn_limit(post)`
    interacts correctly with the FIRST call to this primitive
    post-fork.
