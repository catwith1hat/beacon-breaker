---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [2, 3, 4, 6, 8, 9]
eips: [EIP-7251, EIP-8061]
prysm_version: v3.2.2-rc.1-2535-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 16: `compute_exit_epoch_and_update_churn` + `compute_consolidation_epoch_and_update_churn` (Pectra-NEW per-block churn-budget primitives)

## Summary

Pectra introduces **churn-paced exit and consolidation** to replace Phase0's per-validator counter. Instead of "max N validators exit per epoch", Pectra meters by **balance**: "max X gwei of exit per epoch." The two primitives `compute_exit_epoch_and_update_churn` and `compute_consolidation_epoch_and_update_churn` are the per-block state-mutating chokepoint that all Track A operations (items #2 consolidation, #3 partial withdrawal, #6 voluntary exit) and slashing-induced exits (items #8 attester slashing, #9 proposer slashing via `slash_validator → initiate_validator_exit`) flow through.

**Pectra surface (the function bodies themselves):** all six clients implement the algorithm identically — `max(state.earliest_exit_epoch, compute_activation_exit_epoch(current))` for the epoch (later value), strict `<` new-epoch detection, full `per_epoch_churn` budget on new-epoch reset, ceiling-division for additional epochs (`(balance_to_process - 1) // per_epoch_churn + 1`), and the same state-mutation order. No EF fixture exists for these primitives as standalone operations, but 396 implicit fixture invocations from items #2/#3/#6/#8/#9 cross-validate (99 unique fixtures × 4 wired clients = 396 PASS results all flowing through one of the two primitives).

**Gloas surface (new at the Glamsterdam target):** EIP-8061 modifies the churn helpers comprehensively. `compute_exit_epoch_and_update_churn` is **Modified** (`vendor/consensus-specs/specs/gloas/beacon-chain.md:855`) to call the new `get_exit_churn_limit` instead of `get_activation_exit_churn_limit`. `get_consolidation_churn_limit` is **Modified** (`vendor/consensus-specs/specs/gloas/beacon-chain.md:839`) to a quotient-based formula (`total_active_balance // CONSOLIDATION_CHURN_LIMIT_QUOTIENT`). Two new helpers are added: `get_activation_churn_limit` (line 808) and `get_exit_churn_limit` (line 824). The unified Electra activation-and-exit budget is split into **three independent budgets** at Gloas: activation (deposits, used by item #4), exit (voluntary exits + partial withdrawals + slashings, used by items #3/#6/#8/#9), consolidation (used by item #2).

All six clients implement the EIP-8061 family at Gloas. The dispatch idioms vary per client (runtime version wrapper, Java subclass override, compile-time when dispatch, name-polymorphism, `state.is_post_gloas()` predicate, runtime ternary), but the observable Gloas semantics are uniform.

No splits at the current pins. The earlier finding (chokepoint failing 5/6 across H12–H15) was a stale-pin artifact downstream of items #2/#3/#4/#6/#8/#9. Each of those items' H6/H8/H9/H10 has vacated under the per-client Glamsterdam branches; this audit's H12–H15 vacate by composition. The EIP-8061 family is now fully uniform.

## Question

Pyspec `compute_exit_epoch_and_update_churn` (Pectra-modified, `vendor/consensus-specs/specs/electra/beacon-chain.md`):

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

`compute_consolidation_epoch_and_update_churn` is **structurally identical** with `_consolidation_*` field substitutions and a different churn-limit selector. The Pectra-era three-layer churn helpers:

```python
def get_balance_churn_limit(state) -> Gwei:
    churn = max(MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA, total_active_balance(state) // CHURN_LIMIT_QUOTIENT)
    return churn - churn % EFFECTIVE_BALANCE_INCREMENT      # Round DOWN to 1-ETH increment

def get_activation_exit_churn_limit(state) -> Gwei:
    return min(MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT, get_balance_churn_limit(state))

def get_consolidation_churn_limit(state) -> Gwei:
    return get_balance_churn_limit(state) - get_activation_exit_churn_limit(state)  # Residual budget
```

**Glamsterdam target.** Gloas (EIP-8061) overhauls the entire churn family. `vendor/consensus-specs/specs/gloas/beacon-chain.md`:

- **Modified `compute_exit_epoch_and_update_churn`** (line 855-883):
  ```python
  # [Modified in Gloas:EIP8061]
  per_epoch_churn = get_exit_churn_limit(state)  # Gloas-new (was get_activation_exit_churn_limit)
  ```

- **Modified `get_consolidation_churn_limit`** (line 839-851):
  ```python
  # [Modified in Gloas:EIP8061]
  churn = get_total_active_balance(state) // CONSOLIDATION_CHURN_LIMIT_QUOTIENT
  return churn - churn % EFFECTIVE_BALANCE_INCREMENT  # No subtraction; independent quotient
  ```

- **New `get_activation_churn_limit`** (line 808-822): activation-only budget, balance-based with `CHURN_LIMIT_QUOTIENT_GLOAS` quotient and `MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT_GLOAS` ceiling. Consumed by item #4 (`process_pending_deposits`).

- **New `get_exit_churn_limit`** (line 824-834): exit-only budget, balance-based with `CHURN_LIMIT_QUOTIENT_GLOAS` quotient, floored at `MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA`. Consumed by `compute_exit_epoch_and_update_churn`.

The unified Electra `activation_exit` budget is **split into three independent budgets** at Gloas: activation, exit, consolidation. Each has its own quotient and its own caller. The same per-epoch state field (`state.exit_balance_to_consume` / `state.consolidation_balance_to_consume`) is reused, but the helper that initialises and tops it up changes.

The hypothesis: *all six clients implement the Pectra primitives identically (H1–H11), and at the Glamsterdam target all six fork-gate the helper calls to consume the EIP-8061 helpers: `get_exit_churn_limit` in `compute_exit_epoch_and_update_churn` (H12), the new Gloas formula in `get_consolidation_churn_limit` (H13), the new `get_activation_churn_limit` (H14), and the new `get_exit_churn_limit` itself (H15).*

**Consensus relevance**: these primitives are at the centre of the Pectra Track A + slashings call graph. They mutate `state.{earliest_exit_epoch, exit_balance_to_consume, earliest_consolidation_epoch, consolidation_balance_to_consume}` — fields included in `hash_tree_root(state)`. With H12–H15 now uniform across all six clients, every entry-point that flows through the two primitives produces consistent post-state at Gloas activation.

## Hypotheses

- **H1.** `get_balance_churn_limit` formula: `max(MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA = 128 ETH, total_balance / CHURN_LIMIT_QUOTIENT = 65536)`, then DOWNWARD-rounded to `EFFECTIVE_BALANCE_INCREMENT = 1 ETH`.
- **H2.** `get_activation_exit_churn_limit = min(MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT = 256 ETH, balance_churn)`.
- **H3.** `get_consolidation_churn_limit = balance_churn - activation_exit_churn` (residual budget model — Pectra; modified at Gloas — see H13).
- **H4.** `compute_exit_epoch_and_update_churn` picks `max(state.earliest_exit_epoch, compute_activation_exit_epoch(current))` for the epoch.
- **H5.** New-epoch detection uses STRICT `<` inequality: `state.earliest_exit_epoch < earliest_exit_epoch` (NOT `<=` or `!=`).
- **H6.** New-epoch reset assigns the FULL `per_epoch_churn` budget; same-epoch carries over `state.exit_balance_to_consume`.
- **H7.** Ceiling-division formula: `(balance_to_process - 1) // per_epoch_churn + 1`.
- **H8.** `balance_to_process > 0` precondition guaranteed by the `if exit_balance > exit_balance_to_consume` guard.
- **H9.** State mutation order: write `exit_balance_to_consume = (consumed - exit_balance)` then `earliest_exit_epoch = earliest_exit_epoch`, then return.
- **H10.** Subtraction `consumed - exit_balance` cannot underflow because `consumed >= exit_balance` is invariant after the if-block.
- **H11.** `compute_consolidation_*` is structurally identical with `_consolidation_*` substitutions and `get_consolidation_churn_limit` selector.
- **H12** *(Glamsterdam target — modified exit-churn helper)*. At the Gloas fork gate, `compute_exit_epoch_and_update_churn` consumes `get_exit_churn_limit(state)` (Gloas-new helper) instead of `get_activation_exit_churn_limit(state)` (Electra). Pre-Gloas, all six retain the Electra helper.
- **H13** *(Glamsterdam target — modified consolidation churn limit)*. At the Gloas fork gate, `get_consolidation_churn_limit` switches from the Electra residual model (`balance_churn − activation_exit_churn`) to the quotient-based formula (`total_active_balance // CONSOLIDATION_CHURN_LIMIT_QUOTIENT`, rounded to EBI).
- **H14** *(Glamsterdam target — new activation-churn helper)*. At Gloas, a new helper `get_activation_churn_limit` exists with the Gloas quotient and ceiling; consumed by item #4 (`process_pending_deposits`).
- **H15** *(Glamsterdam target — new exit-churn helper)*. At Gloas, a new helper `get_exit_churn_limit` exists with the Gloas quotient and Electra MIN floor; consumed by `compute_exit_epoch_and_update_churn`.

## Findings

H1–H15 satisfied across all six clients at the current Glamsterdam-target pins. The Pectra-surface bits (H1–H11) align on body shape; the four Gloas-target hypotheses (H12 modified exit-churn helper, H13 modified consolidation churn limit, H14 new activation-churn helper, H15 new exit-churn helper) are implemented by all six clients via six distinct dispatch idioms catalogued in item #6.

### prysm

`vendor/prysm/beacon-chain/core/helpers/validator_churn.go` — central churn-helper module. Defines:
- `BalanceChurnLimit` — `get_balance_churn_limit` equivalent.
- `ActivationExitChurnLimit` (line 41-42) — Electra `min(MAX, balance_churn)`.
- `ConsolidationChurnLimit` (line 52-53) — Electra residual formula.
- `activationChurnLimitGloas` (line 70-72) — Gloas-new: `min(MaxPerEpochActivationChurnLimitGloas, balance_churn_gloas)`.
- `exitChurnLimitGloas` (line 86-88) — Gloas-new.
- `consolidationChurnLimitGloas` (line 101-104) — Gloas-new quotient formula.
- **`ActivationChurnLimitForVersion`** (line 108-114) — runtime wrapper: `if v >= version.Gloas → activationChurnLimitGloas; else → ActivationExitChurnLimit`.
- **`ExitChurnLimitForVersion`** (line 116-121) — runtime wrapper: `if v >= version.Gloas → exitChurnLimitGloas; else → ActivationExitChurnLimit`.
- **`ConsolidationChurnLimitForVersion`** (line 124-128) — runtime wrapper: `if v >= version.Gloas → consolidationChurnLimitGloas; else → ConsolidationChurnLimit`.

`vendor/prysm/beacon-chain/state/state-native/setters_churn.go:62-67` — `exitEpochAndUpdateChurn` uses `helpers.ExitChurnLimitForVersion(b.version, totalActiveBalance)` for the per-epoch churn.

**H12 dispatch (runtime version wrapper).** `ExitChurnLimitForVersion`.
**H13 dispatch (runtime version wrapper).** `ConsolidationChurnLimitForVersion` selects the Gloas quotient formula at Gloas.
**H14 dispatch (runtime version wrapper).** `ActivationChurnLimitForVersion` selects `activationChurnLimitGloas` at Gloas.
**H15 ✓** — `exitChurnLimitGloas` defined.

H1–H11 ✓. **H12 ✓**. **H13 ✓**. **H14 ✓**. **H15 ✓**.

### lighthouse

`vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2623-2631` — `get_balance_churn_limit` (fork-gated quotient inside via `single_pass.rs:1009-1019`).

**H14 dispatch (name-polymorphism).** `:2780-2793 get_activation_exit_churn_limit` — name-polymorphic, body fork-gates internally:

```rust
let max_limit = if self.fork_name_unchecked().gloas_enabled() {
    spec.max_per_epoch_activation_churn_limit_gloas
} else {
    spec.max_per_epoch_activation_exit_churn_limit
};
Ok(std::cmp::min(max_limit, self.get_balance_churn_limit(spec)?))
```

At Gloas, this function implements the Gloas spec's `get_activation_churn_limit` semantics (Gloas-new MAX + Gloas-new quotient via `get_balance_churn_limit`'s internal fork-gate).

**H15 ✓.** `:2798-2800 get_exit_churn_limit` is the Gloas-new helper (uncapped variant).

**H13 dispatch (internal fork-gate).** `:2802-2812 get_consolidation_churn_limit`:

```rust
if self.fork_name_unchecked().gloas_enabled() {
    let total_active_balance = self.get_total_active_balance()?;
    let churn = total_active_balance.safe_div(spec.consolidation_churn_limit_quotient)?;
    Ok(churn.safe_sub(churn.safe_rem(spec.effective_balance_increment)?)?)
} else {
    self.get_balance_churn_limit(spec)?
        .safe_sub(self.get_activation_exit_churn_limit(spec)?)
        .map_err(Into::into)
}
```

**H12 dispatch (internal fork-gate).** `:2896-2935 compute_exit_epoch_and_update_churn` at lines 2906-2910:

```rust
let per_epoch_churn = if self.fork_name_unchecked().gloas_enabled() {
    self.get_exit_churn_limit(spec)?
} else {
    self.get_activation_exit_churn_limit(spec)?
};
```

The local function name-polymorphism extends into `per_epoch_processing/single_pass.rs:994-1007` (`get_activation_exit_churn_limit` local fn) and `:1009-1019` (`get_balance_churn_limit` local fn) — both fork-gate the MAX/QUOTIENT internally for the in-pass deposit-processing path.

H1–H11 ✓. **H12 ✓**. **H13 ✓**. **H14 ✓** (via name-polymorphism — `get_activation_exit_churn_limit` returns Gloas semantics at Gloas). **H15 ✓**.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/BeaconStateAccessorsElectra.java:85-91` — `getActivationExitChurnLimit` (Electra formula).
`BeaconStateMutatorsElectra.java:77-104` — `computeExitEpochAndUpdateChurn` (calls `getActivationExitChurnLimit`).
`:135-168` — `computeConsolidationEpochAndUpdateChurn`.

**H12 dispatch (Java subclass override).** `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/helpers/BeaconStateMutatorsGloas.java:71-99` overrides `computeExitEpochAndUpdateChurn` and substitutes `beaconStateAccessorsGloas.getExitChurnLimit(state)` at line 78.

**H14 dispatch (Java subclass override).** `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/helpers/BeaconStateAccessorsGloas.java:101-103`:

```java
public UInt64 getActivationChurnLimit(final BeaconStateElectra state) {
    return getBalanceChurnLimit(state)
        .min(configGloas.getMaxPerEpochActivationChurnLimitGloas());
}
```

`getExitChurnLimit` (H15 ✓) is defined in the same file at line 111.

**H13 dispatch (Java subclass override).** `BeaconStateAccessorsGloas.java:124-127`:

```java
public UInt64 getConsolidationChurnLimit(final BeaconStateElectra state) {
    return getTotalActiveBalance(state).dividedBy(configGloas.getConsolidationChurnLimitQuotient());
}
```

`EpochProcessorGloas.java:73-75` overrides `getPendingDepositsChurnLimit` to call `beaconStateAccessorsGloas.getActivationChurnLimit(state)` — wiring the Gloas activation helper into item #4's deposit-drain path.

H1–H11 ✓. **H12 ✓**. **H13 ✓**. **H14 ✓**. **H15 ✓**.

### nimbus

`vendor/nimbus/beacon_chain/spec/beaconstate.nim:253-262` — `get_balance_churn_limit`. `:265-274` — `get_activation_exit_churn_limit` (Electra).

**H14 dispatch (compile-time `when` variant function).** `:305 get_activation_churn_limit*` — Gloas-new helper with explicit spec reference at `:304`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.7.0-alpha.7/specs/gloas/beacon-chain.md#new-get_activation_churn_limit
func get_activation_churn_limit*(...)
```

**H15 ✓.** `get_exit_churn_limit*` defined at line 319.

**H13 dispatch (compile-time `when` variant function).** `:332-339` defines the Electra `get_consolidation_churn_limit*` (residual model); `:341-349` defines the Gloas variant:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.7.0-alpha.7/specs/gloas/beacon-chain.md#modified-get_consolidation_churn_limit
func get_consolidation_churn_limit*(...) =
  total_active_balance(state, cache) div cfg.CONSOLIDATION_CHURN_LIMIT_QUOTIENT
```

Compile-time dispatch via the union-type / per-fork signature.

**H12 dispatch (compile-time `when` branch).** `compute_exit_epoch_and_update_churn*` at `:353-388` selects the per-epoch churn at compile time:

```nim
let per_epoch_churn =
  when typeof(state).kind >= ConsensusFork.Gloas:
    get_exit_churn_limit(cfg, state, cache)
  else:
    get_activation_exit_churn_limit(cfg, state, cache)
```

Similarly `:397 get_consolidation_churn_limit(cfg, state, cache)` is dispatched per-fork via the union-type signature.

H1–H11 ✓. **H12 ✓**. **H13 ✓**. **H14 ✓**. **H15 ✓**.

### lodestar

`vendor/lodestar/packages/state-transition/src/util/validator.ts:66-78` — `getBalanceChurnLimit`. `:88-93` — `getActivationExitChurnLimit` (Electra). `:95-103` — **`getActivationChurnLimit` (Gloas-new)** with explicit JSDoc spec reference. `:107-114` — **`getExitChurnLimit` (Gloas-new)**.

```typescript
// Gloas spec ref: gloas/beacon-chain.md#new-get_activation_churn_limit
export function getActivationChurnLimit(epochCtx: EpochCache): number {
  const churn = getBalanceChurnLimit(
    epochCtx.totalActiveBalanceIncrements,
    epochCtx.config.CHURN_LIMIT_QUOTIENT_GLOAS,
    epochCtx.config.MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA
  );
  return Math.min(epochCtx.config.MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT_GLOAS, churn);
}

// Gloas spec ref: gloas/beacon-chain.md#new-get_exit_churn_limit
export function getExitChurnLimit(epochCtx: EpochCache): number { ... }
```

**H13 dispatch (runtime ternary).** `:115-130 getConsolidationChurnLimit`: `if (fork >= ForkSeq.gloas) { return getBalanceChurnLimit(..., CONSOLIDATION_CHURN_LIMIT_QUOTIENT, 0); }` else residual.

**H12 dispatch (runtime ternary).** `vendor/lodestar/packages/state-transition/src/util/epoch.ts:50-77 computeExitEpochAndUpdateChurn`:

```typescript
const perEpochChurn =
  fork >= ForkSeq.gloas ? getExitChurnLimit(state.epochCtx) : getActivationExitChurnLimit(state.epochCtx);
```

`:78-108 computeConsolidationEpochAndUpdateChurn` also fork-gated via `getConsolidationChurnLimit(fork, ...)`.

Mainnet config (`vendor/lodestar/packages/config/src/chainConfig/configs/mainnet.ts`): `CHURN_LIMIT_QUOTIENT_GLOAS = 32768`, `MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT_GLOAS = 256_000_000_000`, `CONSOLIDATION_CHURN_LIMIT_QUOTIENT = 65536`.

H1–H11 ✓. **H12 ✓**. **H13 ✓**. **H14 ✓**. **H15 ✓**.

### grandine

`vendor/grandine/helper_functions/src/accessors.rs:954-960` — `get_balance_churn_limit`.

**H14 dispatch (`state.is_post_gloas()` predicate).** `:991 get_activation_churn_limit` — Gloas-new helper, called at the activation-churn site in `process_pending_deposits` (item #4).

**H15 ✓.** `get_exit_churn_limit` is defined alongside (per item #6 finding).

**H13 dispatch (`state.is_post_gloas()` predicate).** `:977-989 get_consolidation_churn_limit`:

```rust
pub fn get_consolidation_churn_limit<P: Preset>(
    config: &Config,
    state: &impl BeaconState<P>,
) -> Gwei {
    if state.is_post_gloas() {
        // Gloas: quotient formula
        ...
            .div(config.consolidation_churn_limit_quotient)
        ...
    } else {
        // Electra: residual
    }
}
```

**H12 dispatch (`state.is_post_gloas()` predicate).** `vendor/grandine/helper_functions/src/mutators.rs:172-208 compute_exit_epoch_and_update_churn`:

```rust
let per_epoch_churn = if state.is_post_gloas() {
    get_exit_churn_limit(config, state)
} else {
    get_activation_exit_churn_limit(config, state)
};
```

H1–H11 ✓. **H12 ✓**. **H13 ✓**. **H14 ✓**. **H15 ✓**.

## Cross-reference table

| Client | `get_balance_churn_limit` | `compute_exit_epoch_and_update_churn` (H12) | `get_consolidation_churn_limit` (H13) | New `get_activation_churn_limit` (H14) | New `get_exit_churn_limit` (H15) |
|---|---|---|---|---|---|
| prysm | `core/helpers/validator_churn.go:22-28` | ✓ runtime wrapper (`ExitChurnLimitForVersion(b.version, ...)` at `validator_churn.go:116-121`) | ✓ runtime wrapper (`ConsolidationChurnLimitForVersion(b.version, ...)` at `:124-128`; `consolidationChurnLimitGloas` at `:101-104`) | ✓ runtime wrapper (`ActivationChurnLimitForVersion` at `:108-114`; `activationChurnLimitGloas` at `:70-72`) | ✓ `exitChurnLimitGloas` at `:86-88` |
| lighthouse | `consensus/types/src/state/beacon_state.rs:2623-2631` | ✓ internal fork-gate (`:2906-2910` uses `gloas_enabled()` to choose between `get_exit_churn_limit` and `get_activation_exit_churn_limit`) | ✓ internal fork-gate (`:2802-2812` Gloas quotient formula vs Electra residual) | ✓ name-polymorphism (`:2780-2793 get_activation_exit_churn_limit` internally fork-gates MAX + QUOTIENT to produce Gloas-spec semantics at Gloas) | ✓ `:2798-2800 get_exit_churn_limit` |
| teku | `versions/electra/helpers/BeaconStateAccessorsElectra.java:85-91` | ✓ subclass override (`BeaconStateMutatorsGloas.computeExitEpochAndUpdateChurn:71-99` substitutes `getExitChurnLimit`) | ✓ subclass override (`BeaconStateAccessorsGloas.getConsolidationChurnLimit:124-127` quotient formula) | ✓ subclass override (`BeaconStateAccessorsGloas.getActivationChurnLimit:101-103`; wired via `EpochProcessorGloas.getPendingDepositsChurnLimit:73-75`) | ✓ `BeaconStateAccessorsGloas.getExitChurnLimit:111` |
| nimbus | `spec/beaconstate.nim:253-262` | ✓ compile-time `when typeof(state).kind >= ConsensusFork.Gloas` (`beaconstate.nim:362-365`) | ✓ compile-time per-fork variant function (`:341-349` Gloas variant with quotient formula) | ✓ compile-time per-fork variant function (`:305 get_activation_churn_limit*` with Gloas spec reference) | ✓ `get_exit_churn_limit*` at `:319` |
| lodestar | `util/validator.ts:66-78` | ✓ runtime ternary (`util/epoch.ts:50-77` fork-gates `getExitChurnLimit` at `fork >= ForkSeq.gloas`) | ✓ runtime ternary (`util/validator.ts:115-130` fork-gates Gloas quotient at `fork >= ForkSeq.gloas`) | ✓ runtime ternary (`util/validator.ts:95-103` Gloas-new helper with spec reference) | ✓ `util/validator.ts:107-114` Gloas-new helper with spec reference |
| grandine | `helper_functions/src/accessors.rs:954-960` | ✓ `state.is_post_gloas()` predicate (`mutators.rs:181-185`) | ✓ `state.is_post_gloas()` predicate (`accessors.rs:977-989` Gloas quotient vs Electra residual) | ✓ `state.is_post_gloas()` predicate (`accessors.rs:991 get_activation_churn_limit`) | ✓ `accessors.rs get_exit_churn_limit` |

## Empirical tests

### Pectra-surface implicit coverage

**No dedicated EF fixture** exists for `compute_exit_epoch_and_update_churn` or `compute_consolidation_epoch_and_update_churn` as standalone operations. They are exercised IMPLICITLY via:

| Item | Fixtures × wired clients | Primitive consumed |
|---|---|---|
| #2 consolidation_request | 10 × 4 = 40 | `compute_consolidation_epoch_and_update_churn` |
| #3 withdrawal_request | 19 × 4 = 76 | `compute_exit_epoch_and_update_churn` (partial path) |
| #6 voluntary_exit | 25 × 4 = 100 | `compute_exit_epoch_and_update_churn` (via `initiate_validator_exit`) |
| #8 attester_slashing | 30 × 4 = 120 | `compute_exit_epoch_and_update_churn` (via `slash_validator → initiate_validator_exit`) |
| #9 proposer_slashing | 15 × 4 = 60 | same as #8 |

**Total implicit cross-validation evidence**: 99 unique fixtures × 4 wired clients = **396 EF fixture PASS** results all flow through one of the two primitives. Any Pectra-surface algorithm divergence (wrong inequality, wrong ceiling-division, wrong state mutation order, wrong helper selector) would have surfaced as a fixture failure in at least one of these items.

### Gloas-surface

No Gloas EF fixtures yet for the churn primitives. H12–H15 are currently source-only. The family findings (items #2 H6, #3 H8, #4 H8, #6 H8, #8 H9, #9 H10) have all vacated under the per-client Glamsterdam branches, providing strong corroboration that the chokepoint is uniform.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — generate dedicated EF fixture set for the primitives).** Pre-state with known `earliest_exit_epoch` + `exit_balance_to_consume` + total active balance + Pectra fork epoch; call with known `exit_balance`; verify expected post-state. Pure-function fuzzing, directly cross-clientable.
- **T1.2 (priority — Pectra residual-budget verification).** State with known `get_balance_churn_limit` = X, `get_activation_exit_churn_limit` = min(MAX, X). Verify `get_consolidation_churn_limit = X - min(MAX, X)`.
- **T1.3 (Glamsterdam-target — Gloas independent-budget verification).** Gloas state. Verify `get_activation_churn_limit = min(MAX_GLOAS, max(MIN_E, TAB/QUOTIENT_GLOAS))`, `get_exit_churn_limit = max(MIN_E, TAB/QUOTIENT_GLOAS)`, `get_consolidation_churn_limit = TAB/CONSOLIDATION_QUOTIENT - mod`. All six clients should produce identical values.
- **T1.4 (Glamsterdam-target — `compute_exit_epoch_and_update_churn` fork-gate).** Synthetic Gloas state. Call the primitive with known `exit_balance`. All six clients advance `earliest_exit_epoch` per the Gloas `get_exit_churn_limit` ceiling. Cross-client `state_root` should match.

#### T2 — Adversarial probes
- **T2.1 (priority — `exit_balance == 0` no-op).** The if-guard doesn't fire; post-state becomes `exit_balance_to_consume = consumed - 0 = consumed`. Verify all 6 clients handle identically.
- **T2.2 (priority — `exit_balance == exit_balance_to_consume` boundary).** Strict `>` vs `>=` cross-validation. Per H8, equal values DON'T trigger the additional-epochs path.
- **T2.3 (priority — extreme `exit_balance` overflow).** `exit_balance = 2048 ETH × 1000 validators = 2.048e15 gwei`. Verify `additional_epochs` math doesn't overflow.
- **T2.4 (Glamsterdam-target — multi-call same block).** 3 voluntary exits + 1 partial withdrawal + 1 consolidation in same block. Each calls a different primitive but all share the same `state.exit_balance_to_consume` for the exit-side. All six clients consume the Gloas-formula budget; cross-client `state_root` should match.
- **T2.5 (defensive — `MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA` floor never triggered on mainnet).** Verify `total_active_balance / quotient >> 128 ETH` at mainnet stake levels.
- **T2.6 (defensive — teku's `minusMinZero` underflow-masking).** Assert H10's invariant `consumed >= exit_balance` is unreachable to violate; teku's saturating subtraction would silently mask any future bug that did violate it.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H11) remain satisfied: identical `get_balance_churn_limit` / `get_activation_exit_churn_limit` / `get_consolidation_churn_limit` formulas, identical `compute_*_and_update_churn` algorithms (max-epoch, strict `<` new-epoch detection, full-budget reset, ceiling-division, state-mutation order, underflow-safe subtraction). 396 implicit fixture invocations from items #2/#3/#6/#8/#9 cross-validate the Pectra surface — no divergence observed.

**Glamsterdam-target findings (chokepoint).** All four EIP-8061 hypotheses (H12–H15) are satisfied across all six clients:

- **H12 ✓** (compute_exit_epoch fork-gate) — every client fork-gates `compute_exit_epoch_and_update_churn` to consume `get_exit_churn_limit` at Gloas.
- **H13 ✓** (consolidation-churn modified formula) — every client fork-gates `get_consolidation_churn_limit` to the Gloas quotient formula at Gloas.
- **H14 ✓** (new `get_activation_churn_limit`) — every client defines and uses the Gloas-new activation-churn helper (lighthouse via name-polymorphism on `get_activation_exit_churn_limit`).
- **H15 ✓** (new `get_exit_churn_limit`) — every client defines the Gloas-new exit-churn helper.

Six distinct dispatch idioms catalogued across the EIP-8061 family:
- **prysm** uses runtime version wrappers (`ActivationChurnLimitForVersion`, `ExitChurnLimitForVersion`, `ConsolidationChurnLimitForVersion`).
- **lighthouse** uses name-polymorphism for the activation-churn function (`get_activation_exit_churn_limit` body fork-gates MAX + QUOTIENT internally) plus internal fork-gate inside `compute_exit_epoch_and_update_churn` and `get_consolidation_churn_limit`.
- **teku** uses Java subclass override polymorphism (`BeaconStateAccessorsGloas`, `BeaconStateMutatorsGloas` override the four helpers).
- **nimbus** uses compile-time per-fork variant functions and `when typeof(state).kind >= ConsensusFork.Gloas` dispatch.
- **lodestar** uses runtime `fork >= ForkSeq.gloas` ternaries throughout.
- **grandine** uses the `state.is_post_gloas()` predicate at every fork-gated call site.

**This chokepoint was the source of the EIP-8061 family findings.** Six other items (#2 H6, #3 H8, #4 H8, #6 H8, #8 H9, #9 H10) all cascaded from these primitive failures. With each lagging client now on its Glamsterdam branch — prysm `EIP-8061`, teku `glamsterdam-devnet-2`, grandine `glamsterdam-devnet-3`, lighthouse and nimbus `unstable` — the entire family has vacated. The fix was already shipped across the five branches before this audit re-pinned.

Notable per-client style differences:

- **prysm** has a clean three-`*ForVersion` wrapper pattern (`ActivationChurnLimitForVersion`, `ExitChurnLimitForVersion`, `ConsolidationChurnLimitForVersion`) — narrowest dispatch surface.
- **lighthouse** uses name-polymorphism (`get_activation_exit_churn_limit` is the Gloas-meaning activation-churn function via internal fork-gate). Documented at `:2778-2779`: "From Gloas onwards this is the activation-only churn limit (EIP-8061); exits use [`Self::get_exit_churn_limit`]."
- **teku** uses subclass-override polymorphism — `BeaconStateAccessorsGloas` overrides four helpers cleanly.
- **nimbus** uses compile-time per-fork variant functions with explicit spec references (`# https://.../gloas/beacon-chain.md#new-get_activation_churn_limit`).
- **lodestar** has the full EIP-8061 plumbing with explicit spec references in JSDoc comments and uniform runtime fork-ternary dispatch.
- **grandine** uses the `state.is_post_gloas()` Rust trait predicate uniformly across all four hypotheses.

Recommendations to the harness and the audit:

- **Generate dedicated EF fixture set for the primitives** — pure-function, directly fuzzable; closes the gap to source-only verification.
- **Cross-client byte-for-byte equivalence test** — feed identical pre-state + exit_balance to all 6 clients; compare post-state fields + return value. Should match uniformly across all six clients at both Pectra and Gloas inputs.
- **Standalone audit of `compute_activation_exit_epoch`** — used by every Pectra exit/consolidation/activation path; downstream of this item.
- **Document the six-dispatch-idiom catalog** as a reference for future fork-gating audits — H12–H15 illustrate that observable Gloas semantics can be achieved through structurally distinct mechanisms.

## Cross-cuts

### With items #2 / #3 / #4 / #6 / #8 / #9 (EIP-8061 family)

This item is the **chokepoint** of the family. Each family item observed the divergence at its own call site:

| Item | Hypothesis | Helper consumed |
|---|---|---|
| #2 | H6 | `get_consolidation_churn_limit` (H13 here) |
| #3 | H8 | `get_exit_churn_limit` via `compute_exit_epoch_and_update_churn` (H12+H15 here) |
| #4 | H8 | `get_activation_churn_limit` (H14 here) |
| #6 | H8 | same as #3 (via `initiate_validator_exit`) |
| #8 | H9 | same as #6 (via `slash_validator → initiate_validator_exit`) |
| #9 | H10 | same as #8 |

All vacated under the per-client Glamsterdam branches. The chokepoint closes by composition.

### With item #11 (`upgrade_to_electra`) + sister `upgrade_to_gloas`

Item #11 initialises `state.exit_balance_to_consume = get_activation_exit_churn_limit(post)` at Pectra activation. Sister item `upgrade_to_gloas` similarly initialises per the Gloas helpers (`exit_balance_to_consume = get_exit_churn_limit(post)`, `consolidation_balance_to_consume = get_consolidation_churn_limit(post)`). Whether each client's `upgrade_to_gloas` uses the Gloas-correct helpers is a sister audit gap — but given the now-uniform helper implementations at the Glamsterdam branches, the upgrade-time seeding should be consistent across all six clients.

### With item #5 (`process_pending_consolidations`)

Item #5 reads `consolidation_balance_to_consume` set by this item's `compute_consolidation_epoch_and_update_churn`. With this item now uniform across all six clients, the propagation through state reads also produces uniform post-state.

### With item #10 (`process_slashings`)

Item #10 reads `state.slashings[]` set by this item's caller chain (items #8 H9 / #9 H10 via `slash_validator`). The cascade through this item affects `validator.exit_epoch` and `validator.withdrawable_epoch` but NOT the `state.slashings[]` vector values (which are set to `validator.effective_balance` — unchanged by the churn helpers). Item #10 was always impact: none on this axis.

## Adjacent untouched

1. **Generate dedicated EF fixture set** — highest-priority gap closure.
2. **Cross-client byte-for-byte equivalence test** — pre-state + exit_balance → post-state + return value across all 6 clients.
3. **Edge case fixtures**: `exit_balance == 0`, `exit_balance == exit_balance_to_consume`, extreme `exit_balance`.
4. **lighthouse's name-polymorphism documentation** — `get_activation_exit_churn_limit` doubles as the Gloas-meaning activation-churn function; the docstring at `:2778-2779` explicitly notes this. Worth tracking as a reference example for future fork-gating audits.
5. **teku's `minusMinZero` saturating subtraction underflow-masking contract test** — assert algorithm invariants unreachable.
6. **prysm's `*ForVersion` wrapper pattern documentation** — narrowest dispatch surface; reference for future fork-gating.
7. **lodestar BigInt-Number coercion** — pre-emptive fuzz target for any future amount-unit change.
8. **`MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA` floor never triggered on mainnet** — formal verification.
9. **`MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT` consolidation asymmetry** — Pectra-only (Gloas splits the budgets).
10. **`compute_activation_exit_epoch` standalone audit** — used by every Pectra exit/consolidation/activation path.
11. **`get_total_active_balance(state)` cache coherence audit across all 6 clients** — invalidation timing at slot boundaries.
12. **Multi-call-same-block stateful fixture** — 3 voluntary exits + 1 consolidation + 1 partial withdrawal in same block all consuming shared budgets.
13. **Cross-cut with item #11 / sister `upgrade_to_gloas`** — verify the upgrade-time seeding of `exit_balance_to_consume` / `consolidation_balance_to_consume` interacts correctly with the FIRST call to these primitives post-fork.
14. **Six-dispatch-idiom uniformity catalog** — H12–H15 across the six clients showcase six structurally distinct mechanisms achieving the same observable Gloas semantics. Useful reference for future fork-gating audits.
15. **nimbus per-fork variant functions** — explicit spec references in code comments (e.g. `# https://.../gloas/beacon-chain.md#new-get_activation_churn_limit`) are the strongest spec-traceability pattern.
16. **Gloas `CONSOLIDATION_CHURN_LIMIT_QUOTIENT = 65536` vs `CHURN_LIMIT_QUOTIENT_GLOAS = 32768` value verification** — the two quotients have different mainnet values. Verify all client configs match at Glamsterdam activation.
