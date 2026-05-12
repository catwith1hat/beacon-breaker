---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-12
builds_on: [2, 3, 4, 6, 8, 9]
eips: [EIP-7251, EIP-8061]
splits: [prysm, lighthouse, teku, nimbus, grandine]
# main_md_summary: chokepoint audit for the EIP-8061 churn rework — only lodestar fork-gates `compute_exit_epoch_and_update_churn` to `get_exit_churn_limit` and `get_consolidation_churn_limit` to the Gloas-quotient formula at the Gloas fork; the other five clients run the Electra formulas unconditionally on Gloas states (cascades into items #2 H6, #3 H8, #4 H8, #6 H8, #8 H9, #9 H10)
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.3
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.3.1
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 16: `compute_exit_epoch_and_update_churn` + `compute_consolidation_epoch_and_update_churn` (Pectra-NEW per-block churn-budget primitives)

## Summary

Pectra introduces **churn-paced exit and consolidation** to replace Phase0's per-validator counter. Instead of "max N validators exit per epoch", Pectra meters by **balance**: "max X gwei of exit per epoch." The two primitives `compute_exit_epoch_and_update_churn` and `compute_consolidation_epoch_and_update_churn` are the per-block state-mutating chokepoint that all Track A operations (items #2 consolidation, #3 partial withdrawal, #6 voluntary exit) and slashing-induced exits (items #8 attester slashing, #9 proposer slashing via `slash_validator → initiate_validator_exit`) flow through.

**Pectra surface (the function bodies themselves):** all six clients implement the algorithm identically — `max(state.earliest_exit_epoch, compute_activation_exit_epoch(current))` for the epoch (later value), strict `<` new-epoch detection, full `per_epoch_churn` budget on new-epoch reset, ceiling-division for additional epochs (`(balance_to_process - 1) // per_epoch_churn + 1`), and the same state-mutation order. No EF fixture exists for these primitives as standalone operations, but 396 implicit fixture invocations from items #2/#3/#6/#8/#9 cross-validate (99 unique fixtures × 4 wired clients = 396 PASS results all flowing through one of the two primitives).

**Gloas surface (new at the Glamsterdam target):** EIP-8061 modifies the churn helpers comprehensively. `compute_exit_epoch_and_update_churn` is **Modified** (`vendor/consensus-specs/specs/gloas/beacon-chain.md:855`) to call the new `get_exit_churn_limit` instead of `get_activation_exit_churn_limit`. `get_consolidation_churn_limit` is **Modified** (`vendor/consensus-specs/specs/gloas/beacon-chain.md:839`) to a quotient-based formula (`total_active_balance // CONSOLIDATION_CHURN_LIMIT_QUOTIENT`). Two new helpers are added: `get_activation_churn_limit` (line 808) and `get_exit_churn_limit` (line 824). The unified Electra activation-and-exit budget is split into **three independent budgets** at Gloas: activation (deposits, used by item #4), exit (voluntary exits + partial withdrawals + slashings, used by items #3/#6/#8/#9), consolidation (used by item #2).

Survey of all six clients: **only lodestar fork-gates** the helper calls at the Gloas fork; **prysm, lighthouse, teku, nimbus, grandine all retain the Electra formulas unconditionally on Gloas states**. This is the **chokepoint** observation that the family of recheck findings (items #2 H6, #3 H8, #4 H8, #6 H8, #8 H9, #9 H10) all cascade from. Closing this item via a single coordinated PR per lagging client (fork-gate the helper calls) would simultaneously close all six family items.

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

**Consensus relevance**: these primitives are at the centre of the Pectra Track A + slashings call graph. They mutate `state.{earliest_exit_epoch, exit_balance_to_consume, earliest_consolidation_epoch, consolidation_balance_to_consume}` — fields included in `hash_tree_root(state)`. A divergence in any helper (wrong formula, wrong quotient, wrong ceiling) produces different `earliest_*_epoch` values and different per-epoch budget mutations — splitting the state-root immediately, and cascading into different `validator.exit_epoch` assignments and different consolidation drain rates. At Gloas activation, this cascades into six audit items simultaneously via the helper-call divergence.

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

H1–H11 satisfied for the Pectra surface. **H12 fails for 5 of 6 clients** at the Glamsterdam target — same 5-vs-1 cohort as items #3 H8 / #6 H8 / #8 H9 / #9 H10. **H13 fails for 5 of 6** — same finding as item #2 H6. **H14 fails for 5 of 6** — same as item #4 H8. **H15 satisfied only by lodestar** — the new helper isn't defined elsewhere. Only lodestar fork-gates the entire EIP-8061 family; the other five run Electra helpers unconditionally at Gloas.

### prysm

`vendor/prysm/beacon-chain/core/helpers/validator_churn.go:22-28` — `get_balance_churn_limit` equivalent.

`vendor/prysm/beacon-chain/state/state-native/setters_churn.go:62-93` — `ExitEpochAndUpdateChurn` (locks state, mutates directly). Calls `helpers.ActivationExitChurnLimit(activeBalance)` unconditionally (no fork branch).

`vendor/prysm/beacon-chain/core/electra/churn.go:40-85` — `ConsolidationEpochAndUpdateChurn`. Calls `helpers.ConsolidationChurnLimit(activeBalance)` (= Electra residual formula) unconditionally.

`ActivationExitChurnLimit` (line 40-42 of `validator_churn.go`) returns `min(MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT, BalanceChurnLimit(activeBalance))` — Electra formula. `ConsolidationChurnLimit` (line 50-52) returns `BalanceChurnLimit - ActivationExitChurnLimit` — Electra residual.

**No Gloas-aware fork-gate** anywhere in `validator_churn.go`, `setters_churn.go`, or `core/electra/churn.go`. No `ActivationChurnLimit` Gloas helper (the existing `ValidatorActivationChurnLimit` at line 239 is a Deneb count-based helper for validator-count-driven activation, not the Gloas balance-based one).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. **H12 ✗** (uses `ActivationExitChurnLimit` at Gloas). **H13 ✗** (uses Electra residual at Gloas). **H14 ✗** (no Gloas activation-churn helper). **H15 ✗** (no Gloas exit-churn helper).

### lighthouse

`vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2623-2631` — `get_balance_churn_limit`. `:2634-2642` — `get_activation_exit_churn_limit`. `:2644-2648` — `get_consolidation_churn_limit` (Electra residual).

`:2708-2752` — `compute_exit_epoch_and_update_churn`. The variant `match` at the end explicitly accepts `BeaconState::Electra(_) | BeaconState::Fulu(_) | BeaconState::Gloas(_)` (lines 2744-2748), but **the churn-limit call at line 2716 is `self.get_activation_exit_churn_limit(spec)?` unconditionally** — no Gloas branch.

`:2753-2798` — `compute_consolidation_epoch_and_update_churn`. Same pattern: `get_consolidation_churn_limit(spec)` unconditionally.

Lighthouse has a separate `get_activation_churn_limit` at `beacon_state.rs:2036-2050` — but it's the **Deneb-era count-based formula** (`min(spec.max_per_epoch_activation_churn_limit, get_validator_churn_limit)`) using `get_validator_churn_limit` (validator-count-based), NOT the Gloas balance-based formula with `CHURN_LIMIT_QUOTIENT_GLOAS`. And it's never called from `process_pending_deposits` (per item #4 H8 finding). The presence of a Deneb-named helper under a Gloas-spec name is a footgun.

H1–H11 ✓. **H12 ✗**. **H13 ✗**. **H14 ✗** (Deneb-flavour function exists but doesn't match Gloas spec). **H15 ✗**.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/BeaconStateAccessorsElectra.java:85-91` — `getActivationExitChurnLimit`. Co-located in the Electra helpers.

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/BeaconStateMutatorsElectra.java:77-104` — `computeExitEpochAndUpdateChurn`. Calls `stateAccessorsElectra.getActivationExitChurnLimit(state)` at line 91 unconditionally.

`:135-168` — `computeConsolidationEpochAndUpdateChurn`. Calls `getConsolidationChurnLimit` (= residual model).

The Gloas namespace at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/helpers/` contains `BeaconStateAccessorsGloas`, `BeaconStateMutatorsGloas`, `MiscHelpersGloas`, `PredicatesGloas` — but **none of them override `getActivationExitChurnLimit`, `getConsolidationChurnLimit`, `computeExitEpochAndUpdateChurn`, or `computeConsolidationEpochAndUpdateChurn`**. The Electra implementations are inherited unchanged at Gloas.

H1–H11 ✓. **H12 ✗**. **H13 ✗**. **H14 ✗** (no Gloas activation-churn helper override). **H15 ✗**.

### nimbus

`vendor/nimbus/beacon_chain/spec/beaconstate.nim:253-262` — `get_balance_churn_limit`. `:265-274` — `get_activation_exit_churn_limit`. `:276-284` — `get_consolidation_churn_limit*` (Electra residual; signature accepts `electra.BeaconState | fulu.BeaconState | gloas.BeaconState` but body is Electra formula).

`:286-314` — `compute_exit_epoch_and_update_churn*`. Signature accepts the same union type. Body line 293: `let per_epoch_churn = get_activation_exit_churn_limit(cfg, state, cache)` — unconditional Electra helper call.

`:317-345` — `compute_consolidation_epoch_and_update_churn*`. Same pattern.

The compile-time fork-dispatch (union type on the function signature) allows the Gloas variant to be dispatched, but the **body itself does not branch on fork version** — the Electra helper is called regardless of whether the state is `electra`, `fulu`, or `gloas`.

H1–H11 ✓. **H12 ✗** (Electra helper at Gloas). **H13 ✗** (Electra residual at Gloas). **H14 ✗**. **H15 ✗**.

### lodestar

`vendor/lodestar/packages/state-transition/src/util/validator.ts:66-78` — `getBalanceChurnLimit`. `:88-93` — `getActivationExitChurnLimit` (Electra). `:95-103` — **`getActivationChurnLimit` (Gloas-new)** with explicit JSDoc reference to the Gloas spec. `:107-114` — **`getExitChurnLimit` (Gloas-new)**.

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
export function getExitChurnLimit(epochCtx: EpochCache): number {
  return getBalanceChurnLimit(
    epochCtx.totalActiveBalanceIncrements,
    epochCtx.config.CHURN_LIMIT_QUOTIENT_GLOAS,
    epochCtx.config.MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA
  );
}
```

`:115-130` — `getConsolidationChurnLimit` (**fork-gated** — `if (fork >= ForkSeq.gloas) { return getBalanceChurnLimit(..., CONSOLIDATION_CHURN_LIMIT_QUOTIENT, 0); }` else residual).

`vendor/lodestar/packages/state-transition/src/util/epoch.ts:50-77` — `computeExitEpochAndUpdateChurn` (**fork-gated**):

```typescript
const perEpochChurn =
  fork >= ForkSeq.gloas ? getExitChurnLimit(state.epochCtx) : getActivationExitChurnLimit(state.epochCtx);
```

`:78-108` — `computeConsolidationEpochAndUpdateChurn` (also fork-gated via `getConsolidationChurnLimit(fork, ...)`).

Mainnet config (`vendor/lodestar/packages/config/src/chainConfig/configs/mainnet.ts`): `CHURN_LIMIT_QUOTIENT_GLOAS = 32768`, `MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT_GLOAS = 256_000_000_000`, `CONSOLIDATION_CHURN_LIMIT_QUOTIENT = 65536`.

H1–H11 ✓. **H12 ✓**. **H13 ✓**. **H14 ✓**. **H15 ✓** — the only client with the full EIP-8061 helper family wired and fork-gated.

### grandine

`vendor/grandine/helper_functions/src/accessors.rs:954-960` — `get_balance_churn_limit`. The helpers `get_activation_exit_churn_limit` (~line 970) and `get_consolidation_churn_limit` (line 974-979) are in the same file with Electra formulas.

`vendor/grandine/helper_functions/src/mutators.rs:177-209` — `compute_exit_epoch_and_update_churn`. Body uses `get_activation_exit_churn_limit(config, state)` unconditionally — no fork branch.

`:211-248` — `compute_consolidation_epoch_and_update_churn`. Uses `get_consolidation_churn_limit(config, state)` (Electra residual) unconditionally.

Grandine has a **single definition** of each primitive (notable consistency vs items #6/#9/#10/#12/#14 where it has multiple per-fork variants). The single definition is **not fork-aware** — at Gloas, the Electra formulas continue to fire.

H1–H11 ✓. **H12 ✗** (Electra helper at Gloas). **H13 ✗** (Electra residual at Gloas). **H14 ✗** (no Gloas activation-churn helper). **H15 ✗** (no Gloas exit-churn helper).

## Cross-reference table

| Client | `get_balance_churn_limit` | `compute_exit_epoch_and_update_churn` (H12) | `get_consolidation_churn_limit` (H13) | New `get_activation_churn_limit` (H14) | New `get_exit_churn_limit` (H15) |
|---|---|---|---|---|---|
| prysm | `core/helpers/validator_churn.go:22-28` | ✗ (`state-native/setters_churn.go:62-93` calls `ActivationExitChurnLimit` unconditionally) | ✗ (`validator_churn.go:50-52` returns Electra residual; `core/electra/churn.go:40-85` uses it) | ✗ (no Gloas balance-based helper; `ValidatorActivationChurnLimit` exists but is Deneb count-based) | ✗ |
| lighthouse | `consensus/types/src/state/beacon_state.rs:2623-2631` | ✗ (`:2708-2752` calls `self.get_activation_exit_churn_limit(spec)?` unconditionally; variant `match` accepts Gloas but doesn't override) | ✗ (`:2644-2648` Electra residual) | ✗ (`:2036-2050 get_activation_churn_limit` is Deneb count-based — footgun name) | ✗ |
| teku | `versions/electra/helpers/BeaconStateAccessorsElectra.java:85-91` | ✗ (`BeaconStateMutatorsElectra.java:77-104` calls `getActivationExitChurnLimit`; `BeaconStateMutatorsGloas` doesn't override) | ✗ (`BeaconStateAccessorsElectra` Electra residual; `BeaconStateAccessorsGloas` doesn't override) | ✗ | ✗ |
| nimbus | `spec/beaconstate.nim:253-262` | ✗ (`:286-314` body uses `get_activation_exit_churn_limit` even with `gloas.BeaconState` signature) | ✗ (`:276-284` Electra residual) | ✗ | ✗ |
| lodestar | `util/validator.ts:66-78` | **✓** (`util/epoch.ts:50-77` fork-gates `getExitChurnLimit` at `fork >= ForkSeq.gloas`) | **✓** (`util/validator.ts:115-130` fork-gates Gloas quotient at `fork >= ForkSeq.gloas`) | **✓** (`util/validator.ts:95-103` Gloas-new helper with spec reference) | **✓** (`util/validator.ts:107-114` Gloas-new helper with spec reference) |
| grandine | `helper_functions/src/accessors.rs:954-960` | ✗ (`helper_functions/src/mutators.rs:177-209` calls `get_activation_exit_churn_limit` unconditionally) | ✗ (`accessors.rs:974-979` Electra residual) | ✗ | ✗ |

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

No Gloas EF fixtures yet for the churn primitives. H12–H15 are currently source-only. The family findings (items #2 H6, #3 H8, #4 H8, #6 H8, #8 H9, #9 H10) are the corroborating evidence — each of those Gloas-target divergences cascades from this audit's H12/H13/H14 failures.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — generate dedicated EF fixture set for the primitives).** Pre-state with known `earliest_exit_epoch` + `exit_balance_to_consume` + total active balance + Pectra fork epoch; call with known `exit_balance`; verify expected post-state. Pure-function fuzzing, directly cross-clientable.
- **T1.2 (priority — Pectra residual-budget verification).** State with known `get_balance_churn_limit` = X, `get_activation_exit_churn_limit` = min(MAX, X). Verify `get_consolidation_churn_limit = X - min(MAX, X)`.
- **T1.3 (Glamsterdam-target — Gloas independent-budget verification).** Gloas state. Verify `get_activation_churn_limit = min(MAX_GLOAS, max(MIN_E, TAB/QUOTIENT_GLOAS))`, `get_exit_churn_limit = max(MIN_E, TAB/QUOTIENT_GLOAS)`, `get_consolidation_churn_limit = TAB/CONSOLIDATION_QUOTIENT - mod`. Lodestar would produce three distinct values; the other five would produce the Electra residual model values.
- **T1.4 (Glamsterdam-target — `compute_exit_epoch_and_update_churn` fork-gate).** Synthetic Gloas state. Call the primitive with known `exit_balance`. Lodestar advances `earliest_exit_epoch` per the Gloas `get_exit_churn_limit` ceiling; the other five per the Electra `get_activation_exit_churn_limit` ceiling. Different `earliest_exit_epoch` written into state — pin the divergence numerically.

#### T2 — Adversarial probes
- **T2.1 (priority — `exit_balance == 0` no-op).** The if-guard doesn't fire; post-state becomes `exit_balance_to_consume = consumed - 0 = consumed`. Verify all 6 clients handle identically.
- **T2.2 (priority — `exit_balance == exit_balance_to_consume` boundary).** Strict `>` vs `>=` cross-validation. Per H8, equal values DON'T trigger the additional-epochs path.
- **T2.3 (priority — extreme `exit_balance` overflow).** `exit_balance = 2048 ETH × 1000 validators = 2.048e15 gwei`. Verify `additional_epochs` math doesn't overflow.
- **T2.4 (Glamsterdam-target — multi-call same block).** 3 voluntary exits + 1 partial withdrawal + 1 consolidation in same block. Each calls a different primitive but all share the same `state.exit_balance_to_consume` for the exit-side. Lodestar consumes the Gloas-formula budget; the other five consume the Electra-formula budget. Different per-validator `exit_epoch` assignments across the cohort.
- **T2.5 (defensive — `MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA` floor never triggered on mainnet).** Verify `total_active_balance / quotient >> 128 ETH` at mainnet stake levels.
- **T2.6 (defensive — teku's `minusMinZero` underflow-masking).** Assert H10's invariant `consumed >= exit_balance` is unreachable to violate; teku's saturating subtraction would silently mask any future bug that did violate it.

## Mainnet reachability

**Reachable on canonical traffic at Glamsterdam activation, on every block carrying any Track A operation (voluntary exit, partial withdrawal request, consolidation request) or any slashing operation** — i.e., essentially every Gloas-slot block, since slashings + exits + partial withdrawals are routine canonical traffic.

**Trigger.** The first Gloas-slot block that invokes `compute_exit_epoch_and_update_churn` or `compute_consolidation_epoch_and_update_churn`. Lodestar dispatches the spec-correct `get_exit_churn_limit` / `get_consolidation_churn_limit` (Gloas-modified). The other five dispatch the Electra `get_activation_exit_churn_limit` / residual `get_consolidation_churn_limit`. Different `per_epoch_churn` values → different `additional_epochs` → different `earliest_exit_epoch` / `earliest_consolidation_epoch` written into state → different `validator.exit_epoch` assignments via `initiate_validator_exit` (item #6) and `slash_validator` (items #8, #9) → divergent state roots.

**Severity.** This is the **chokepoint** divergence. A single coordinated PR per lagging client (fork-gate the helper calls inside the two primitive functions) closes:

- Item #2 H6 (consolidation-churn modified formula)
- Item #3 H8 (`compute_exit_epoch_and_update_churn` → `get_exit_churn_limit`)
- Item #4 H8 (`process_pending_deposits` → `get_activation_churn_limit`)
- Item #6 H8 (voluntary-exit cascade)
- Item #8 H9 (attester-slashing cascade)
- Item #9 H10 (proposer-slashing cascade)
- This item's H12–H15 directly

Six items in the EIP-8061 family. The fix scope is narrow: each lagging client needs to add the two Gloas-new helpers (`get_activation_churn_limit`, `get_exit_churn_limit`), fork-gate `compute_exit_epoch_and_update_churn` to use `get_exit_churn_limit` at Gloas, fork-gate `process_pending_deposits` to use `get_activation_churn_limit` at Gloas, and fork-gate `get_consolidation_churn_limit` to the Gloas quotient formula. Lodestar's implementation at `util/validator.ts:88-130` + `util/epoch.ts:50-108` is the reference.

**Mitigation window.** Source-only at audit time; no Gloas EF fixtures for the primitives. Closing requires the five lagging clients (prysm, lighthouse, teku, nimbus, grandine) to ship the EIP-8061 fork-gate before Glamsterdam fork-cut. Without it, mainnet at Glamsterdam activation forks the lodestar cohort from the rest on every block carrying any churn-paced operation.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H11) remain satisfied: identical `get_balance_churn_limit` / `get_activation_exit_churn_limit` / `get_consolidation_churn_limit` formulas, identical `compute_*_and_update_churn` algorithms (max-epoch, strict `<` new-epoch detection, full-budget reset, ceiling-division, state-mutation order, underflow-safe subtraction). 396 implicit fixture invocations from items #2/#3/#6/#8/#9 cross-validate the Pectra surface — no divergence observed.

**Glamsterdam-target findings (chokepoint).** Four new hypotheses (H12–H15) capture the EIP-8061 fork-gate requirements:

- **H12** (compute_exit_epoch fork-gate) — only lodestar uses `get_exit_churn_limit` at Gloas; five fail.
- **H13** (consolidation-churn modified formula) — only lodestar uses the quotient-based formula at Gloas; five fail.
- **H14** (new `get_activation_churn_limit`) — only lodestar defines and uses it; five fail.
- **H15** (new `get_exit_churn_limit`) — only lodestar defines and uses it; five fail.

**This is the chokepoint of the EIP-8061 family.** Six other items (#2 H6, #3 H8, #4 H8, #6 H8, #8 H9, #9 H10) cascade from these primitive failures. Closing them requires a single coordinated fix-PR scope per lagging client: add the two Gloas-new helpers (`get_activation_churn_limit`, `get_exit_churn_limit`), fork-gate the two compute primitives, fork-gate `get_consolidation_churn_limit`.

Notable per-client style differences:

- **prysm** has asymmetric file placement (exit in `state-native/setters_churn.go`, consolidation in `core/electra/churn.go`). Multiple defensive math layers (`math.Div64` for consolidation, raw division for exit). At Gloas, no fork-gate anywhere.
- **lighthouse** uses explicit `BeaconState::Electra(_) | Fulu(_) | Gloas(_)` match in the compute primitives — but the churn-limit call inside is unconditional. The `get_activation_churn_limit` function defined at `beacon_state.rs:2036-2050` is the Deneb count-based formula, not the Gloas balance-based one — a footgun under the Gloas spec name.
- **teku** uses subclass-override polymorphism throughout; `BeaconStateAccessorsGloas` / `BeaconStateMutatorsGloas` exist but neither overrides the four functions in question.
- **nimbus** uses compile-time union-type dispatch (`electra | fulu | gloas BeaconState`) but the function body is fork-agnostic.
- **lodestar** has the full EIP-8061 plumbing with explicit spec references in JSDoc comments — the only spec-aligned client at Gloas across all four primitives.
- **grandine** has a single definition of each primitive (cleaner than items #6/#9/#10/#12/#14 which had multiple per-fork variants) but no fork-gate in the body.

Recommendations to the harness and the audit:

- **Generate dedicated EF fixture set for the primitives** — pure-function, directly fuzzable; closes the gap to source-only verification.
- **Cross-client byte-for-byte equivalence test** — feed identical pre-state + exit_balance to all 6 clients; compare post-state fields + return value. Lodestar will differ from the others on Gloas inputs.
- **Coordinate the EIP-8061 fork-gate fix** across the five lagging clients (prysm, lighthouse, teku, nimbus, grandine). Single PR per client with narrow scope (add 2 helpers + fork-gate 2 compute primitives + fork-gate 1 churn-limit accessor). Closes 6 family items simultaneously.
- **lighthouse's `get_activation_churn_limit` Deneb-name vs Gloas-spec footgun** — rename the Deneb-era helper to `get_validator_activation_churn_limit` (or similar) to disambiguate from the Gloas-spec function with the same name. A careless future patch could replace `get_activation_exit_churn_limit` with this `get_activation_churn_limit` thinking it was Gloas-correct.
- **Codify nimbus's union-type fork-dispatch** — currently the union type allows the function to be called for Gloas states, but the body is fork-agnostic. Add an explicit `when state is gloas.BeaconState` branch at the body level.

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

All cascading from this item's H12/H13/H14/H15. Closing this item closes the family.

### With item #11 (`upgrade_to_electra`) + sister `upgrade_to_gloas`

Item #11 initialises `state.exit_balance_to_consume = get_activation_exit_churn_limit(post)` at Pectra activation. Sister item `upgrade_to_gloas` should similarly initialise per the Gloas helpers (`exit_balance_to_consume = get_exit_churn_limit(post)`, `consolidation_balance_to_consume = get_consolidation_churn_limit(post)`). Whether each client's `upgrade_to_gloas` uses the Gloas-correct helpers is a sister audit gap.

### With item #5 (`process_pending_consolidations`)

Item #5 reads `consolidation_balance_to_consume` set by this item's `compute_consolidation_epoch_and_update_churn`. At Gloas, lodestar writes a different value than the other five clients via H13's divergence — but item #5 itself is impact: none because the function body is unchanged. The propagation through state reads doesn't amplify the divergence at item #5.

### With item #10 (`process_slashings`)

Item #10 reads `state.slashings[]` set by this item's caller chain (items #8 H9 / #9 H10 via `slash_validator`). At Gloas, the cascade through this item affects `validator.exit_epoch` and `validator.withdrawable_epoch` but NOT the `state.slashings[]` vector values (which are set to `validator.effective_balance` — unchanged by the churn helpers). Item #10 is impact: none because the slashings-vector entries themselves are not divergent.

## Adjacent untouched

1. **Generate dedicated EF fixture set** — highest-priority gap closure.
2. **Cross-client byte-for-byte equivalence test** — pre-state + exit_balance → post-state + return value across all 6 clients.
3. **Edge case fixtures**: `exit_balance == 0`, `exit_balance == exit_balance_to_consume`, extreme `exit_balance`.
4. **lighthouse's `get_activation_churn_limit` Deneb-name vs Gloas-spec footgun** — codify the disambiguation.
5. **teku's `minusMinZero` saturating subtraction underflow-masking contract test** — assert algorithm invariants unreachable.
6. **prysm's asymmetric file placement** — codify the structural differences for documentation.
7. **lodestar BigInt-Number coercion** — pre-emptive fuzz target for any future amount-unit change.
8. **`MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA` floor never triggered on mainnet** — formal verification.
9. **`MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT` consolidation asymmetry** — Pectra-only (Gloas splits the budgets).
10. **`compute_activation_exit_epoch` standalone audit** — used by every Pectra exit/consolidation/activation path.
11. **`get_total_active_balance(state)` cache coherence audit across all 6 clients** — invalidation timing at slot boundaries.
12. **Multi-call-same-block stateful fixture** — 3 voluntary exits + 1 consolidation + 1 partial withdrawal in same block all consuming shared budgets.
13. **Cross-cut with item #11 / sister `upgrade_to_gloas`** — verify the upgrade-time seeding of `exit_balance_to_consume` / `consolidation_balance_to_consume` interacts correctly with the FIRST call to these primitives post-fork.
14. **Coordinated EIP-8061 fork-gate PR scope** — single PR per lagging client (prysm, lighthouse, teku, nimbus, grandine) closes items #2 H6, #3 H8, #4 H8, #6 H8, #8 H9, #9 H10, and this item's H12-H15. Reference implementation: lodestar's `util/validator.ts:88-130` + `util/epoch.ts:50-108`.
15. **nimbus union-type fork-dispatch** — currently fork-agnostic body; add explicit `when state is gloas.BeaconState` branch for spec-traceability.
16. **Gloas `CONSOLIDATION_CHURN_LIMIT_QUOTIENT = 65536` vs `CHURN_LIMIT_QUOTIENT_GLOAS = 32768` value verification** — the two quotients have different mainnet values (per lodestar's `chainConfig/configs/mainnet.ts`). Verify all client configs match at Glamsterdam activation.
