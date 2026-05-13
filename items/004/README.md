---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [1, 2]
eips: [EIP-6110, EIP-8061]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 4: `process_pending_deposits` EIP-6110 per-epoch drain

## Summary

EIP-6110 replaces eth1-bridge polling with in-protocol pending deposits. Per-epoch routine that drains `state.pending_deposits` in FIFO order subject to four short-circuits and three per-deposit branches (apply, postpone, churn-limit-break), then mutates the queue to `unprocessed + postponed`. Adds new validators to the registry (with proof-of-possession signature verification via `GENESIS_FORK_VERSION`) or tops up existing balances; consumes `state.deposit_balance_to_consume` only when the per-epoch churn limit is reached.

**Pectra surface (the function body itself):** all six clients implement the four short-circuits, three per-deposit branches, queue-postpone semantics, `GENESIS_FORK_VERSION` signature domain, and conditional churn accumulator identically. 43/43 EF `pending_deposits` epoch-processing fixtures pass on the four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus pass these in internal CI but the local harness SKIPs them.

**Gloas surface (Glamsterdam target):** Gloas modifies `process_pending_deposits` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:982`) — the EIP-8061 deposit-side rework — to compute `available_for_processing = deposit_balance_to_consume + get_activation_churn_limit(state)` instead of `+ get_activation_exit_churn_limit(state)`. The new `get_activation_churn_limit` (line 808-822) is balance-based with the Gloas-specific `CHURN_LIMIT_QUOTIENT_GLOAS` constant and capped at `MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT_GLOAS`. The body itself is otherwise unchanged. After re-pinning all six clients to the branches that carry their Glamsterdam work (lighthouse/nimbus/lodestar to `unstable`; prysm to `EIP-8061`; teku to `glamsterdam-devnet-2`; grandine to `glamsterdam-devnet-3`), **all six clients fork-gate the deposit-side churn helper** to produce the EIP-8061 activation-churn at Gloas — by some combination of (a) explicit function-name dispatch (`get_activation_churn_limit` is a different function from `get_activation_exit_churn_limit`), (b) version-runtime dispatch through a wrapper, (c) compile-time type dispatch, or (d) name-polymorphism (the same accessor name is kept but its body fork-gates internally, so the Gloas call computes the Gloas formula). H8 holds across the corpus.

## Question

EIP-6110 replaces eth1-bridge polling with in-protocol pending deposits. Pyspec (`vendor/consensus-specs/specs/electra/beacon-chain.md`, `process_pending_deposits`):

```python
def process_pending_deposits(state):
    next_epoch = current_epoch + 1
    available = state.deposit_balance_to_consume + get_activation_exit_churn_limit(state)
    processed = 0; index = 0; postpone = []; churn_hit = False
    finalized_slot = compute_start_slot_at_epoch(state.finalized_checkpoint.epoch)

    for d in state.pending_deposits:
        # 4 hard breaks (in order)
        if d.slot > GENESIS_SLOT and state.eth1_deposit_index < state.deposit_requests_start_index: break
        if d.slot > finalized_slot: break
        if index >= MAX_PENDING_DEPOSITS_PER_EPOCH: break
        # ... validator state lookup ...
        if validator_withdrawn:
            apply_pending_deposit(state, d)         # NO churn consumption
        elif validator_exited:
            postpone.append(d)                      # MOVE to back of queue
        else:
            if processed + d.amount > available:
                churn_hit = True; break             # 4th break
            processed += d.amount
            apply_pending_deposit(state, d)
        index += 1                                  # bumped in all 3 inner cases

    state.pending_deposits = state.pending_deposits[index:] + postpone   # drop processed, append postponed
    state.deposit_balance_to_consume = (available - processed) if churn_hit else 0
```

`apply_pending_deposit`:

```python
def apply_pending_deposit(state, d):
    if d.pubkey not in validator_pubkeys:
        if is_valid_deposit_signature(d.pubkey, d.withdrawal_credentials, d.amount, d.signature):
            add_validator_to_registry(state, d.pubkey, d.withdrawal_credentials, d.amount)
    else:
        increase_balance(state, validator_index, d.amount)
```

`is_valid_deposit_signature` uses the **deposit signing domain** computed with `GENESIS_FORK_VERSION` — fork-agnostic. **A common bug** is to use the current fork version: a deposit signed with pre-Pectra fork-version semantics would then fail to verify post-fork. All 6 clients must use `GENESIS_FORK_VERSION`.

`add_validator_to_registry` is **Pectra-modified** to take an `amount` parameter — the new validator's balance is set to the actual deposit amount (not 0 as in the legacy `apply_deposit` path). Effective balance is computed from `amount` via the get-max-effective-balance machinery audited in item #1.

**Glamsterdam target.** Gloas modifies `process_pending_deposits` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:982-1050`) per the in-spec `[Modified in Gloas:EIP8061]` annotation — the only line that changes inside the function body is the churn-helper:

```python
# Gloas
available_for_processing = state.deposit_balance_to_consume + get_activation_churn_limit(state)
```

`get_activation_churn_limit` is new at Gloas (`vendor/consensus-specs/specs/gloas/beacon-chain.md:808-822`):

```python
def get_activation_churn_limit(state: BeaconState) -> Gwei:
    churn = max(MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA, get_total_active_balance(state) // CHURN_LIMIT_QUOTIENT_GLOAS)
    churn = churn - churn % EFFECTIVE_BALANCE_INCREMENT
    return min(MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT_GLOAS, churn)
```

`CHURN_LIMIT_QUOTIENT_GLOAS` and `MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT_GLOAS` are Gloas-specific constants (e.g. lodestar config has `CHURN_LIMIT_QUOTIENT_GLOAS = 32768`, `MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT_GLOAS = 256000000000`). The composition `get_activation_exit_churn_limit` (Electra: `min(get_balance_churn_limit, MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT)`) — which fed both deposit-side and exit-side activation throttling at Electra — is replaced by **three separate quantities at Gloas**: `get_activation_churn_limit` (deposits), `get_exit_churn_limit` (exits — item #3), `get_consolidation_churn_limit` (consolidations — item #2). All three are derived from `total_active_balance / CHURN_LIMIT_QUOTIENT_GLOAS` but with different caps and floors.

Gloas additionally reschedules `process_operations`'s `process_pending_deposits` call: per EIP-7732 ePBS, the deposit-request producer side `process_deposit_request` is moved into `apply_parent_execution_payload`, but the per-epoch *drain* (`process_pending_deposits`) continues to run in `process_epoch` as before. Only the churn helper changes.

The hypothesis: *all six clients implement the four short-circuits, three per-deposit branches, queue-postpone semantics, GENESIS_FORK_VERSION signature domain, and conditional churn accumulator identically (H1–H7), and at the Glamsterdam target all six fork-gate the churn helper to `get_activation_churn_limit` (H8).*

**Consensus relevance**: each successful drain creates a new validator (initial balance = deposit amount, with `effective_balance` set via item #1's logic) or tops up an existing one. The `pending_deposits` queue is part of `BeaconState` — its mutation directly changes the state-root. A divergence in any of: postpone-vs-skip semantics, churn-accumulator reset, signature-domain version, batch-limit ordering would split the state-root immediately at the next epoch boundary. **A divergence on the per-epoch churn quantity** (Electra activation-exit vs Gloas activation) shifts both the per-deposit churn-limit-reached predicate AND the post-loop `deposit_balance_to_consume` decrement value, materialising as different `state.pending_deposits` queue contents AND different `state.deposit_balance_to_consume` on the first Gloas-slot epoch boundary where the drain hits the churn ceiling.

## Hypotheses

- **H1.** All six implement the **four break conditions** in pyspec order: (1) deposit-request-before-bridge-finalized, (2) deposit-not-finalized, (3) batch limit (`MAX_PENDING_DEPOSITS_PER_EPOCH = 16`), (4) churn limit (inside the active-validator branch).
- **H2.** All six **postpone exited-validator deposits** (move to back of queue) and **apply withdrawn-validator deposits without consuming churn**.
- **H3.** All six **increment `next_deposit_index` for all three inner branches** (withdrawn, exited→postpone, active→applied) — but NOT on the four early breaks. Index is the slice point in the post-loop queue mutation.
- **H4.** Queue mutation produces `pending_deposits[next_deposit_index:] + postpone` — drops first `index` elements, appends postponed at the back.
- **H5.** The deposit-balance accumulator is **conditionally set**: `available − processed` if churn limit was reached, else `0`. **The "else" branch is critical** — without it, the accumulator would grow each epoch.
- **H6.** `is_valid_deposit_signature` uses **`GENESIS_FORK_VERSION`** for the signing domain (fork-agnostic).
- **H7.** `add_validator_to_registry` (Pectra-modified) creates the validator with balance = `amount` and effective_balance computed via item #1's `get_max_effective_balance`.
- **H8** *(Glamsterdam target)*. At the Gloas fork gate, all six clients switch the `available_for_processing` churn term from `get_activation_exit_churn_limit(state)` (Electra) to `get_activation_churn_limit(state)` (Gloas, EIP-8061). Pre-Gloas, all six retain the Electra formula.

## Findings

H1–H7 satisfied for the Pectra surface. **H8 also satisfied at the Glamsterdam target across all six clients** — every client produces the EIP-8061 activation-churn formula for `process_pending_deposits`' `available_for_processing` at Gloas, using one of four dispatch idioms (function-name dispatch, version-runtime wrapper, compile-time type dispatch, or name-polymorphism via an internally fork-gated accessor). Source-level convergence; no Gloas epoch-processing fixtures yet exist.

### prysm

`vendor/prysm/beacon-chain/core/electra/deposits.go:257-370` — `ProcessPendingDeposits`. Predicate sequence matches pyspec 1→4 + 3 inner branches. `next_deposit_index` increments after the inner conditionals (line 348). Queue mutation at line 361:

```go
availableForProcessing := depBalToConsume + helpers.ActivationExitChurnLimit(activeBalance)  // line 278
...
pendingDeposits = append(pendingDeposits[nextDepositIndex:], pendingDepositsToPostpone...)   // line 361
```

`apply_pending_deposit` is inlined into the loop body (lines 322-344). `IsValidDepositSignature` (lines 168-179) calls `signing.ComputeDomain(DomainDeposit, nil, nil)` — the `nil` fork-version arg defaults to `GENESIS_FORK_VERSION` inside `ComputeDomain`. ✓

`AddValidatorToRegistry` (lines 472-497) calls `GetValidatorFromDeposit(pubkey, withdrawal_credentials, amount)` then `AppendBalance(amount)` — Pectra-correct. ✓

On the re-pinned `EIP-8061` branch, `deposits.go:278` now reads:

```go
availableForProcessing := depBalToConsume + helpers.ActivationChurnLimitForVersion(st.Version(), activeBalance)
```

`ActivationChurnLimitForVersion` at `vendor/prysm/beacon-chain/core/helpers/validator_churn.go:107-113` dispatches on runtime fork:

```go
func ActivationChurnLimitForVersion(v int, activeBalance primitives.Gwei) primitives.Gwei {
    if v >= version.Gloas {
        return activationChurnLimitGloas(activeBalance)
    }
    return ActivationExitChurnLimit(activeBalance)
}
```

`activationChurnLimitGloas` at `:68-73` implements the EIP-8061 capped form: `min(MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT_GLOAS, max(MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA, total_active_balance // CHURN_LIMIT_QUOTIENT_GLOAS) − mod EBI)`. Pre-Gloas falls back to `ActivationExitChurnLimit` (Electra).

H1–H7 ✓. **H8 ✓** — version-dispatched at the deposit-side call site.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_epoch_processing/single_pass.rs:1083-1110` — `PendingDepositsContext::new` (re-pinned `unstable`). The structural pattern is unchanged: lighthouse defers the actual balance/validator mutations into a `PendingDepositsContext` that records indexed deposit operations (`HashMap` for top-ups, `Vec` for new validators), applied later in the validator-iteration loop.

Break-condition order matches pyspec 1→4. The churn term at lines 1090-1091:

```rust
let available_for_processing = state
    .deposit_balance_to_consume()?
    .safe_add(state.get_activation_exit_churn_limit(spec)?)?;
```

The function-name in the call (`get_activation_exit_churn_limit`) is the same at Electra and Gloas, but the callee at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2780-2793` is **itself fork-gated on `gloas_enabled()`**:

```rust
pub fn get_activation_exit_churn_limit(
    &self,
    spec: &ChainSpec,
) -> Result<u64, BeaconStateError> {
    let max_limit = if self.fork_name_unchecked().gloas_enabled() {
        spec.max_per_epoch_activation_churn_limit_gloas
    } else {
        spec.max_per_epoch_activation_exit_churn_limit
    };
    Ok(std::cmp::min(max_limit, self.get_balance_churn_limit(spec)?))
}
```

…and `get_balance_churn_limit` at `:2761-2774` is also internally fork-gated to use `churn_limit_quotient_gloas` at Gloas. Composed, the Gloas branch evaluates to:

```
min(max_per_epoch_activation_churn_limit_gloas,
    max(min_per_epoch_churn_limit_electra, total_active_balance / churn_limit_quotient_gloas) - mod EBI)
```

— precisely the Gloas spec's `get_activation_churn_limit`. The function-name lag is misleading: lighthouse keeps the Electra-era name `get_activation_exit_churn_limit` for the deposit-side helper while updating its body to produce the Gloas-spec activation-churn output at Gloas. Pre-Gloas the same accessor returns the Electra formula.

(Lighthouse's separate `BeaconState::get_activation_churn_limit` at `:2167-2181` is the Deneb-era count-based formula — `min(spec.max_per_epoch_activation_churn_limit, get_validator_churn_limit)` — used only by the activation-queue path, NOT by `PendingDepositsContext`. The naming overlap with the Gloas spec function is unfortunate; the spec-correct deposit-side helper lives at `:2780` under the historically Electra name.)

`is_valid_deposit_signature` continues to use `spec.get_deposit_domain()` → `compute_domain(Domain::Deposit, self.genesis_fork_version, ...)`. ✓

`add_validator_to_registry` continues to compute effective_balance via `Validator::from_deposit(..., amount, ...)` consistent with item #1. ✓

H1–H7 ✓. **H8 ✓** — via name-polymorphism: the accessor named `get_activation_exit_churn_limit` is fork-gated internally to produce the Gloas activation-churn formula at Gloas. Confusing but correct.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/statetransition/epoch/EpochProcessorElectra.java:214-299` — `processPendingDeposits`. Predicate sequence matches pyspec 1→4. Inner loop uses `IntStream.range(nextDepositIndex, pendingDeposits.size()).forEach(...)` to build the new queue, then `addAll(depositsToPostpone)` to append. Conditional accumulator at lines 295-298: `if isChurnLimitReached { ... .minusMinZero(...) } else { UInt64.ZERO }`.

The churn term in `EpochProcessorElectra.java:218-221` reads `getActivationExitChurnLimit(stateElectra)` (Electra). At Gloas (`glamsterdam-devnet-2`), `EpochProcessorGloas` extends `EpochProcessorElectra` and overrides the deposit-churn-limit accessor at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/statetransition/epoch/EpochProcessorGloas.java:74`:

```java
/**
 * EIP-8061: deposits consume the activation-only churn budget; consolidation churn is now tracked
 * independently via CONSOLIDATION_CHURN_LIMIT_QUOTIENT.
 */
@Override
protected UInt64 getPendingDepositsChurnLimit(final MutableBeaconStateElectra state) {
  return beaconStateAccessorsGloas.getActivationChurnLimit(state);
}
```

`BeaconStateAccessorsGloas.getActivationChurnLimit:101-104` implements the Gloas EIP-8061 capped form via the shared `computeBalanceChurnLimit(state, ChurnLimitQuotientGloas)` helper, then `.min(MaxPerEpochActivationChurnLimitGloas)`.

`applyPendingDeposits` and the `isValidDepositSignature` / `addValidatorToRegistry` helpers are unchanged from the prior audit.

H1–H7 ✓. **H8 ✓** — `EpochProcessorGloas.getPendingDepositsChurnLimit @Override` at `:72-75` calls `beaconStateAccessorsGloas.getActivationChurnLimit(state)`.

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_epoch.nim:1213-1298` — `process_pending_deposits*` (re-pinned `unstable`). Predicate sequence matches pyspec 1→4. Queue mutation idiom unchanged (`asSeq[next_deposit_index..^1] & deposits_to_postpone`).

Churn term at lines 1218-1224 — **now fork-gated** via Nim's compile-time `when`:

```nim
let
  next_epoch = get_current_epoch(state) + 1
  available_for_processing = state.deposit_balance_to_consume +
    (when typeof(state).kind >= ConsensusFork.Gloas:
      get_activation_churn_limit(cfg, state, cache)
    else:
      get_activation_exit_churn_limit(cfg, state, cache))
```

Signature now also accepts `heze.BeaconState`. The new Gloas/Heze `get_activation_churn_limit*` overload at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:305-317` implements the EIP-8061 formula precisely:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.7.0-alpha.7/specs/gloas/beacon-chain.md#new-get_activation_churn_limit
func get_activation_churn_limit*(
    cfg: RuntimeConfig,
    state: gloas.BeaconState | heze.BeaconState,
    cache: var StateCache): Gwei =
  var churn = max(
    cfg.MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA.Gwei,
    get_total_active_balance(state, cache) div cfg.CHURN_LIMIT_QUOTIENT_GLOAS
  )
  churn = churn - churn mod EFFECTIVE_BALANCE_INCREMENT.Gwei
  min(cfg.MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT_GLOAS.Gwei, churn)
```

The `MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA` floor, `CHURN_LIMIT_QUOTIENT_GLOAS` divisor, and `MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT_GLOAS` cap all match the spec. Sister overload `get_exit_churn_limit*` at `:319+` confirmed for item #3.

`apply_pending_deposit` still calls `verify_deposit_signature(cfg.GENESIS_FORK_VERSION, deposit_data)`. ✓
`add_validator_to_registry` still takes `amount`. ✓

H1–H7 ✓. **H8 ✓** — nimbus now joins lodestar in fork-gating the deposit-side churn helper to EIP-8061.

### lodestar

`vendor/lodestar/packages/state-transition/src/epoch/processPendingDeposits.ts:19-108` — `processPendingDeposits`. **Structural note**: lodestar processes pending_deposits in **chunks of 100** (line ~37) using `getReadonlyByRange(startIndex, chunk)` for SSZ-list batched reads — performance optimisation. Inner loop is unchanged in semantics.

Churn term at lines 22-23 — **fork-gated**:

```typescript
const churnLimit =
  fork >= ForkSeq.gloas ? getActivationChurnLimit(state.epochCtx) : getActivationExitChurnLimit(state.epochCtx);
const availableForProcessing = state.depositBalanceToConsume + BigInt(churnLimit);
```

`getActivationChurnLimit` at `vendor/lodestar/packages/state-transition/src/util/validator.ts:95-103` implements the Gloas spec:

```typescript
export function getActivationChurnLimit(epochCtx: EpochCache): number {
  const churn = getBalanceChurnLimit(
    epochCtx.totalActiveBalanceIncrements,
    epochCtx.config.CHURN_LIMIT_QUOTIENT_GLOAS,
    epochCtx.config.MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA
  );
  return Math.min(epochCtx.config.MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT_GLOAS, churn);
}
```

Mainnet config (`vendor/lodestar/packages/config/src/chainConfig/configs/mainnet.ts:174,178`): `CHURN_LIMIT_QUOTIENT_GLOAS = 32768`, `MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT_GLOAS = 256_000_000_000`.

Queue mutation (lines 96-101): `sliceFrom(nextDepositIndex)` + `push()` loop for postponed. Functionally equivalent.

`isValidDepositSignature` (`vendor/lodestar/packages/state-transition/src/block/processDeposit.ts:141-166`): explicit `computeDomain(DOMAIN_DEPOSIT, config.GENESIS_FORK_VERSION, ZERO_HASH)` — correct. ✓

`addValidatorToRegistry` (`vendor/lodestar/packages/state-transition/src/block/processDeposit.ts:90-122`) computes `effectiveBalance = Math.min(amount - amount % EBI, getMaxEffectiveBalance(creds))` and pushes to validators. ✓

H1–H7 ✓. **H8 ✓** — the only client matching Gloas spec.

### grandine

`vendor/grandine/transition_functions/src/electra/epoch_processing.rs:235-317` — `process_pending_deposits<P>`:

```rust
for deposit in &state.pending_deposits().clone() {  // clone for borrow safety
    if deposit.slot > GENESIS_SLOT && state.eth1_deposit_index() < state.deposit_requests_start_index() { break; }
    if deposit.slot > finalized_slot { break; }
    if next_deposit_index >= P::MAX_PENDING_DEPOSITS_PER_EPOCH { break; }
    // ... 3-way branch ...
    next_deposit_index += 1;
}
*state.pending_deposits_mut() = PersistentList::try_from_iter(
    state.pending_deposits().into_iter().copied().skip(next_deposit_index.try_into()?)
        .chain(deposits_to_postpone))?;
```

On the re-pinned `glamsterdam-devnet-3` branch, grandine has split the deposit-side path into a dedicated Gloas module: `vendor/grandine/transition_functions/src/gloas/epoch_processing.rs:103-110 process_pending_deposits<P>` overrides the Electra version with:

```rust
let available_for_processing =
    state.deposit_balance_to_consume() + get_activation_churn_limit(config, state);
```

`get_activation_churn_limit` at `vendor/grandine/helper_functions/src/accessors.rs:991-998` implements the EIP-8061 capped form:

```rust
pub fn get_activation_churn_limit<P: Preset>(config: &Config, state: &impl BeaconState<P>) -> Gwei {
    let churn = total_active_balance(state)
        .div(config.churn_limit_quotient_gloas)
        .max(config.min_per_epoch_churn_limit_electra)
        .prev_multiple_of(P::EFFECTIVE_BALANCE_INCREMENT);
    churn.min(config.max_per_epoch_activation_churn_limit_gloas)
}
```

The Electra path at `transition_functions/src/electra/epoch_processing.rs:242` continues to call `get_activation_exit_churn_limit(config, state)` unconditionally — pre-Gloas behaviour preserved. Fulu inherits the Electra path via `transition_functions/src/fulu/epoch_processing.rs:65 electra::process_pending_deposits(config, pubkey_cache, state)?`. The Gloas override at `transition_functions/src/gloas/epoch_processing.rs:75` is what fires on Gloas state-transitions.

`apply_pending_deposit` and `is_valid_deposit_signature` continue to behave as before.

H1–H7 ✓. **H8 ✓** — Gloas-specific `process_pending_deposits` override calling `get_activation_churn_limit`.

## Cross-reference table

| Client | Main fn | `available_for_processing` churn term | Gloas fork-gate (H8) | Sig domain version | `add_validator_to_registry` |
|---|---|---|---|---|---|
| prysm | `core/electra/deposits.go:257-370` | `helpers.ActivationChurnLimitForVersion(st.Version(), activeBalance)` at `:278`; dispatches to `activationChurnLimitGloas` at `validator_churn.go:68-73` | **✓** | `nil → GENESIS` (default in `ComputeDomain`) | `:472-497` (sets balance=amount) |
| lighthouse | `per_epoch_processing/single_pass.rs:1083-1110` (`PendingDepositsContext::new`) | `state.get_activation_exit_churn_limit(spec)?` at `:1091`; the accessor at `beacon_state.rs:2780-2793` is **internally fork-gated** on `gloas_enabled()` → at Gloas evaluates to the EIP-8061 activation-churn formula via `get_balance_churn_limit` (also internally fork-gated at `:2761-2774`) | **✓** | explicit `genesis_fork_version` | `state/beacon_state.rs` (`from_deposit(amount)`) |
| teku | `EpochProcessorElectra.java:214-299` (Electra) + `EpochProcessorGloas.java:72-75 @Override getPendingDepositsChurnLimit` returning `beaconStateAccessorsGloas.getActivationChurnLimit(state)` | **✓** | explicit `genesisForkVersion` | `BeaconStateMutators.java:230-240` |
| nimbus | `state_transition_epoch.nim:1213-1298` | `when typeof(state).kind >= ConsensusFork.Gloas: get_activation_churn_limit ... else: get_activation_exit_churn_limit` at `:1218-1224` — **fork-gated**; Gloas overload at `beaconstate.nim:305-317` | **✓** | explicit `cfg.GENESIS_FORK_VERSION` | `beaconstate.nim:125-145` |
| lodestar | `epoch/processPendingDeposits.ts:19-108` | `fork >= ForkSeq.gloas ? getActivationChurnLimit : getActivationExitChurnLimit` (line 22-23) — **fork-gated** | **✓** | explicit `config.GENESIS_FORK_VERSION` | `block/processDeposit.ts:90-122` |
| grandine | `electra/epoch_processing.rs:235-317` (Electra; Fulu inherits) + `gloas/epoch_processing.rs:103-110 process_pending_deposits` override using `get_activation_churn_limit(config, state)` (`accessors.rs:991-998`) | **✓** | `compute_domain(... None ...)` → GENESIS | `block_processing.rs:add_validator_to_registry` |

## Empirical tests

### Pectra-surface fixture run

`consensus-spec-tests/tests/mainnet/electra/epoch_processing/pending_deposits/pyspec_tests/` — 43 EF fixtures. Run via `scripts/run_fixture.sh` against all six clients on 2026-05-03:

```
                                                                              prysm  lighthouse  teku  nimbus  lodestar  grandine
apply_pending_deposit_compounding_withdrawal_credentials_max                  PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_compounding_withdrawal_credentials_over_max             PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_compounding_withdrawal_credentials_over_max_next_inc.   PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_compounding_withdrawal_credentials_under_max            PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_correct_sig_but_forked_state                            PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_effective_deposit_with_genesis_fork_version             PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_eth1_withdrawal_credentials                             PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_incorrect_sig_new_deposit                               PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_incorrect_sig_top_up                                    PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_incorrect_withdrawal_credentials_top_up                 PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_ineffective_deposit_with_bad_fork_version               PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_key_validate_invalid_decompression                      PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_key_validate_invalid_subgroup                           PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_min_activation                                          PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_non_versioned_withdrawal_credentials                    PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_non_versioned_withdrawal_credentials_over_min_act.      PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_over_min_activation                                     PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_over_min_activation_next_increment                      PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_success_top_up_to_withdrawn_validator                   PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_top_up__less_effective_balance                          PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_top_up__max_effective_balance_compounding               PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_top_up__min_activation_balance                          PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_top_up__min_activation_balance_compounding              PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_under_min_activation                                    PASS   PASS        SKIP  SKIP    PASS      PASS
apply_pending_deposit_with_previous_fork_version                              PASS   PASS        SKIP  SKIP    PASS      PASS
ineffective_deposit_with_current_fork_version                                 PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_balance_above_churn                                  PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_balance_equal_churn                                  PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_eth1_bridge_transition_complete                      PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_eth1_bridge_transition_not_applied                   PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_eth1_bridge_transition_pending                       PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_limit_is_reached                                     PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_mixture_of_skipped_and_above_churn                   PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_multiple_for_new_validator                           PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_multiple_pending_deposits_above_churn                PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_multiple_pending_deposits_below_churn                PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_multiple_pending_one_skipped                         PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_multiple_skipped_deposits_exiting_validators         PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_not_finalized                                        PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_preexisting_churn                                    PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_skipped_deposit_exiting_validator                    PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_withdrawable_validator                               PASS   PASS        SKIP  SKIP    PASS      PASS
process_pending_deposits_withdrawable_validator_not_churned                   PASS   PASS        SKIP  SKIP    PASS      PASS
```

43/43 fixtures pass uniformly on prysm + lighthouse + lodestar + grandine. teku and nimbus SKIP. Lighthouse's verdict is per-helper-test-fn (`epoch_processing_pending_balance_deposits` — note the legacy name from before EIP-6110 renamed `PendingBalanceDeposit` → `PendingDeposit`); PASS implies all 43 are among the passing set.

**Coverage assessment:** the richest fixture set among items #1–#4. 43 fixtures cover every churn boundary case (`balance_above_churn`, `balance_equal_churn`, `preexisting_churn`, `multiple_above_churn`, `multiple_below_churn`); every signature edge case (`incorrect_sig_new_deposit`, `incorrect_sig_top_up`, `key_validate_invalid_decompression`, `key_validate_invalid_subgroup`, `correct_sig_but_forked_state`, `with_previous_fork_version`, `ineffective_deposit_with_current_fork_version`); the bridge-transition cases (`eth1_bridge_transition_{complete,not_applied,pending}`); the postpone-vs-skip paths (`skipped_deposit_exiting_validator`, `multiple_skipped_deposits_exiting_validators`, `withdrawable_validator`, `withdrawable_validator_not_churned`, `success_top_up_to_withdrawn_validator`); and the per-epoch limit (`limit_is_reached`). No divergences — strong evidence for the function and its supporting machinery on the Electra surface.

**Notably absent**: a fixture for the **placeholder-signature top-up** scenario produced by item #2's switch-to-compounding fast path (a `PendingDeposit` with `slot=GENESIS_SLOT, signature=G2_POINT_AT_INFINITY`). The cross-cut is reachable but not directly tested at this layer.

### Gloas-surface

No Gloas epoch-processing fixtures exist yet in the EF set. H8 is currently source-only.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — placeholder-sig top-up cross-cut).** Construct an epoch_processing fixture where the `pending_deposits` queue contains exactly the kind of entry produced by `queue_excess_active_balance`: existing validator's pubkey, `slot=GENESIS_SLOT`, `signature=G2_POINT_AT_INFINITY`, amount > 0. Expected: `apply_pending_deposit` takes the top-up branch (does NOT validate signature); balance increases. Detects any client that applies signature verification to top-ups.
- **T1.2 (priority — exact-MAX_PENDING_DEPOSITS_PER_EPOCH boundary).** Queue with exactly 17 deposits, all valid. Expected: 16 are processed, 1 remains. Exists implicitly in `process_pending_deposits_limit_is_reached`; verify all six handle the boundary correctly (the 17th MUST remain at the head of the queue).

#### T2 — Adversarial probes
- **T2.1 (priority — alternating exited/withdrawn/active).** Queue: [withdrawn_v1, exited_v2, active_new, withdrawn_v3, exited_v4, active_new_2]. Expected: v1's deposit applied (no churn); v2 postponed (no churn, moved to back); v3 deposit applied (no churn); v4 postponed (no churn, moved to back); active_new → check churn; active_new_2 → check churn. Final queue: [v2_deposit, v4_deposit] (postponed deposits moved to back, in original encountered order). Already covered by `multiple_skipped_deposits_exiting_validators`.
- **T2.2 (priority — churn limit hit mid-loop).** Queue: 5 active deposits, churn limit only allows 3. Expected: first 3 apply, 4th hits churn → break. Final queue starts with the 4th (unprocessed) deposit; `deposit_balance_to_consume = available − processed_3`. Covered by `process_pending_deposits_multiple_pending_deposits_above_churn`.
- **T2.3 (defensive — corrupt signature on new validator).** New-validator deposit with structurally invalid signature (e.g., G2 point not in subgroup). Expected: `is_valid_deposit_signature` returns false; deposit is consumed (next_deposit_index incremented) but no validator added. Covered by `incorrect_sig_new_deposit` and `key_validate_invalid_subgroup`.
- **T2.4 (priority — current-fork-version sig).** Deposit signed with the CURRENT fork version (not GENESIS) — should be rejected. Covered by `ineffective_deposit_with_current_fork_version` (and its inverse `apply_pending_deposit_with_previous_fork_version`). The all-pass result strongly evidences H6.
- **T2.5 (Glamsterdam-target — Gloas activation-churn formula).** Synthetic Gloas-fork state at the first Gloas epoch with active total balance chosen so the Electra formula `get_activation_exit_churn_limit` and the Gloas formula `get_activation_churn_limit` yield different values. Queue several active-validator deposits with amounts that straddle both churn limits. Expected per Gloas spec: lodestar advances through the queue using the Gloas churn ceiling; the other five use the Electra ceiling and either accept fewer/more deposits or compute a different `deposit_balance_to_consume` decrement. Post-state `pending_deposits` queue contents and `deposit_balance_to_consume` differ. Sister to item #2's T2.5 (consolidation-churn) and item #3's T2.6 (exit-churn) — together they pin the three-way EIP-8061 split.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H7) remain satisfied: aligned implementations of the four-break-condition outer loop, the three-way per-deposit branch, the postpone-to-back queue mutation, the conditional `deposit_balance_to_consume` reset, and the `GENESIS_FORK_VERSION`-domain signature verification. All 43 EF `pending_deposits` fixtures still pass uniformly on prysm, lighthouse, lodestar, grandine; teku and nimbus pass internally. Notable per-client style differences are unchanged from the prior audit (lighthouse defers mutations via `PendingDepositsContext`; lodestar chunks reads at 100; grandine clones the queue for borrow safety; nimbus uses `asSeq[i..^1] & seq2`; lighthouse uses the legacy `epoch_processing_pending_balance_deposits` test-fn name).

**Glamsterdam-target finding (refreshed after the full re-pin sweep):** H8 now holds across all six clients. Gloas (EIP-8061) modifies `process_pending_deposits` to call `get_activation_churn_limit` rather than `get_activation_exit_churn_limit`. Every client correctly produces the EIP-8061 activation-churn formula at Gloas, via one of four dispatch idioms:

- **prysm** (`EIP-8061` branch): runtime version-dispatch via `helpers.ActivationChurnLimitForVersion(st.Version(), …)` at `deposits.go:278`.
- **lighthouse** (`unstable`): name-polymorphism — the call site `state.get_activation_exit_churn_limit(spec)?` at `single_pass.rs:1091` invokes an accessor whose body at `beacon_state.rs:2780-2793` fork-gates internally on `gloas_enabled()` to produce the Gloas activation-churn formula. The accessor name is misleading (still says `get_activation_exit_churn_limit`) but the body composes the spec-correct EIP-8061 formula at Gloas.
- **teku** (`glamsterdam-devnet-2` branch): subclass override — `EpochProcessorGloas.getPendingDepositsChurnLimit:72-75 @Override` returns `beaconStateAccessorsGloas.getActivationChurnLimit(state)`.
- **nimbus** (`unstable`): compile-time `when` dispatch at `state_transition_epoch.nim:1218-1224` calling a new `get_activation_churn_limit*` overload at `beaconstate.nim:305-317`.
- **lodestar** (`unstable`): runtime `fork >= ForkSeq.gloas` branch at `processPendingDeposits.ts:22-23`.
- **grandine** (`glamsterdam-devnet-3` branch): module-level override at `gloas/epoch_processing.rs:103-110 process_pending_deposits` calling `get_activation_churn_limit` from `accessors.rs:991-998`.

The earlier 5-vs-1 and 4-vs-2 framings of this finding were artifacts of (a) auditing lighthouse/nimbus's `stable` pin which lacked the EIP-8061 work, and (b) auditing prysm/teku/grandine's mainline `develop`/`master` pin which lacks the Glamsterdam feature-branch work. The asymmetric 4-vs-2 framing in particular came from the lighthouse-`stable` blind spot: with `unstable` pinned, lighthouse's `get_activation_exit_churn_limit` accessor body is fork-gated internally, even though the function name still reads as the Electra one. With each client on its actual Glamsterdam branch, H8 is uniformly satisfied.

Recommendations to the harness and the audit:
- Generate the **T2.5 Gloas activation-churn formula fixture** when EF spec-test infrastructure for Gloas epoch-processing lands. Sister to item #2's T2.5 and item #3's T2.6.
- File a documentation-cleanup PR to lighthouse to either rename `BeaconState::get_activation_exit_churn_limit` to something less misleading at Gloas (e.g. `get_admit_churn_limit`) or add a doc note explaining that the Electra-era name now serves as the deposit-side helper at Gloas via internal fork-gating. The unrelated `BeaconState::get_activation_churn_limit` at `:2167-2181` (Deneb count-based, used by the activation-queue path) makes the naming overlap especially confusing.
- Generate the **T1.1 placeholder-signature top-up fixture** as a dedicated epoch_processing fixture — closes the cross-cut with item #2.
- Standalone audit `add_validator_to_registry` — used by both this item and `apply_deposit` (legacy path). One Pectra-modified function with two callers; worth its own coverage.
- Standalone audit `process_deposit_request` — the producer side of the queue this item drains. Now part of Gloas's `apply_parent_execution_payload` (rescheduled by EIP-7732); the start-index initialization is the interesting bit.

## Cross-cuts

### With item #1 (`process_effective_balance_updates` / `get_max_effective_balance`)

A new validator added by `add_validator_to_registry` has its initial `effective_balance` computed via the same `get_max_effective_balance` predicate audited in item #1. A divergence in item #1 would surface here as a per-new-validator effective_balance discrepancy. The fact that item #1's hypotheses passed strengthens confidence in the new-validator initialization here.

### With item #2 (`process_consolidation_request` switch path)

Item #2's switch-to-compounding fast path calls `queue_excess_active_balance` which appends a `PendingDeposit` entry with **`slot=GENESIS_SLOT`** and **`signature=BLS_G2_POINT_AT_INFINITY`**. The `slot=GENESIS_SLOT` matters because:
- Break condition #1 (`deposit.slot > GENESIS_SLOT and state.eth1_deposit_index < state.deposit_requests_start_index`) is FALSE for these (slot is NOT > GENESIS_SLOT). So they pass the bridge-finalization check unconditionally.
- Break condition #2 (`deposit.slot > finalized_slot`) is FALSE because GENESIS_SLOT ≤ finalized_slot. So they pass the finality check.

The `signature=G2_POINT_AT_INFINITY` matters because:
- These deposits are TOP-UPs (the validator already exists, since the consolidation switch operated on an existing validator). So `apply_pending_deposit` takes the `validator_index ∈ pubkeys` branch and **never validates the signature**. The placeholder is never checked — by design.

If any client accidentally validated the signature of a top-up (e.g., uniformly applied `is_valid_deposit_signature` to all deposits), it would fail on G2_POINT_AT_INFINITY → reject the top-up → balance discrepancy. **Worth checking explicitly**: the switch-via-consolidation path is the canonical generator of these placeholder-signature deposits, so this cross-cut is reachable.

Additionally: item #2's H6 (Gloas `get_consolidation_churn_limit`) and this item's H8 (Gloas `get_activation_churn_limit`) and item #3's H8 (Gloas `get_exit_churn_limit`) are the three facets of the EIP-8061 churn rework. Same five clients lag on all three; lodestar is ahead on all three. A single coordinated fix-PR per client closes the entire family.

### With EIP-6110 `process_deposit_request` (operation handler)

`process_deposit_request` (the per-block operation that populates `state.pending_deposits` from the EL) is the producer side; this item is the consumer. A bug in either would surface as queue-content mismatch. At Gloas, `process_deposit_request` is rescheduled into `apply_parent_execution_payload` (EIP-7732); the body itself is also Gloas-modified to route `0x03` builder-credentialled deposits into a separate `builders` field rather than into `state.validators` (see teku's `ExecutionRequestsProcessorGloas.processDepositRequest`). A separate audit for `process_deposit_request` is warranted; the deposit-routing change makes it a higher-priority Track-A item at the Glamsterdam target than at the Pectra target.

### With `add_validator_to_registry` (Pectra-modified)

Used by both this item AND `apply_deposit` (legacy bridge-deposit path). Pectra-modified to take `amount` instead of using a fixed 0. A divergence here would surface in BOTH paths. Worth a standalone audit if any client gets clever about the validator construction.

## Adjacent untouched Electra-active consensus paths

1. **`process_deposit_request` (operation handler)** — the producer side. Sets `state.deposit_requests_start_index` once (the EL→pyspec transition marker); appends to `pending_deposits`. At Gloas, also routes `0x03` deposits to the builders list. Worth a dedicated Glamsterdam-target item.
2. **`add_validator_to_registry` standalone audit** — Pectra-modified to take `amount`. Used here AND by `apply_deposit` (legacy path). Cross-cut surface.
3. **`is_valid_deposit_signature` BLS-library family axis** — each client uses a different BLS implementation (BLST in most; gnark-crypto in others; supranational in lighthouse). A subgroup-membership check or domain-separation difference here would directly affect deposit acceptance. Worth a Track F audit aligned with this item's findings.
4. **Lighthouse's stale `get_activation_churn_limit`** — Deneb-era count-based formula, never called by `process_pending_deposits`. The presence of this function under the Gloas-spec name is a footgun: a careless future patch could replace `get_activation_exit_churn_limit` with this `get_activation_churn_limit` thinking it was Gloas-correct, when it's actually the Deneb formula. Recommend renaming to disambiguate.
5. **Lighthouse's deferred-mutation `PendingDepositsContext` design** — if the deferred application reorder fails to commute with intervening single-pass operations (also batched in single_pass.rs), a subtle re-ordering bug could surface. F-tier today (the test fixtures pass) but worth understanding.
6. **`PendingDeposit.slot=GENESIS_SLOT` placeholder** — the special marker used by `queue_excess_active_balance` (called from item #2's switch path). Documented in item #2 cross-cut; deserves its own fixture in this item's category.
7. **`MAX_PENDING_DEPOSITS_PER_EPOCH = 16` is small** — under high deposit pressure (e.g., a fork that causes mass new-validator entry), the queue can grow faster than it drains. Worth a per-epoch growth-rate analysis as an out-of-band research item.
8. **The `deposit_balance_to_consume` accumulator interaction with `compute_exit_epoch_and_update_churn`** — at Electra, both consumed `available_for_processing` derived from the unified `get_activation_exit_churn_limit`. At Gloas (EIP-8061), the two consume different pools (`get_activation_churn_limit` for deposits, `get_exit_churn_limit` for exits) — the unification is explicitly broken. Worth a sweep to confirm no client still couples the two pools incorrectly at Gloas.
9. **Postpone+skip interleaving order**: pyspec says `postpone.append(deposit)` preserves the encounter order. If a client built the postpone list out-of-order (e.g., used a HashMap somewhere), the queue rebuild would silently reorder. F-tier; unlikely but possible.
10. **`pending_deposits` SSZ list cap (`PENDING_DEPOSITS_LIMIT = 2²⁷`)** — per-block deposit_request additions can fill this faster than per-epoch drainage. A queue-full state is theoretically possible. What happens if a new `process_deposit_request` tries to append to a full queue? Should be rejected silently per SSZ cap, but worth confirming. Cross-cut with the producer.
