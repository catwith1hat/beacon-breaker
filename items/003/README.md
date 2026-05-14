---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [2]
eips: [EIP-7002, EIP-8061]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 3: `process_withdrawal_request` EIP-7002 full-exit + partial paths

## Summary

EIP-7002 entrypoint with two semantically distinct flows: (1) **full exit** when `amount == FULL_EXIT_REQUEST_AMOUNT` (= 0), which calls `initiate_validator_exit`, and (2) **partial withdrawal** for non-zero amounts, which appends a `PendingPartialWithdrawal` to be drained later by `process_pending_partial_withdrawals`. The function also has a **queue-full-but-allow-full-exits** carve-out: when the partial-withdrawals queue is full, full-exit requests still succeed.

**Pectra surface (the function body itself):** all six clients implement the dual-mode logic, the queue-full carve-out, the strict 0x02-only partial constraint, and the correct churn-machinery (`compute_exit_epoch_and_update_churn`, not the consolidation variant) identically. 19/19 EF `withdrawal_request` operations fixtures pass on the four wired clients; teku and nimbus pass these in their internal CI but the local harness SKIPs them.

**Gloas surface (Glamsterdam target):** Gloas keeps `process_withdrawal_request` and `initiate_validator_exit` bodies intact but reschedules the withdrawal pass from `process_operations` into the new `apply_parent_execution_payload` (EIP-7732 ePBS, `vendor/consensus-specs/specs/gloas/beacon-chain.md:1131`) and **modifies the underlying churn helper** `compute_exit_epoch_and_update_churn` (EIP-8061, line 855) to consume `get_exit_churn_limit` (new at Gloas, line 824) instead of `get_activation_exit_churn_limit`. After re-pinning all six clients to the branches that carry their Glamsterdam work (lighthouse/nimbus/lodestar to `unstable`; prysm to `EIP-8061`; teku to `glamsterdam-devnet-2`; grandine to `glamsterdam-devnet-3`), **all six clients fork-gate `compute_exit_epoch_and_update_churn`** to use the Gloas `get_exit_churn_limit` helper at Gloas. H8 holds across the corpus.

## Question

EIP-7002 entrypoint with two semantic flows. Pyspec (`vendor/consensus-specs/specs/electra/beacon-chain.md`, `process_withdrawal_request`):

```python
def process_withdrawal_request(state, req):
    amount = req.amount
    is_full_exit_request = amount == FULL_EXIT_REQUEST_AMOUNT  # = 0

    # 1. Queue full carve-out
    if (len(state.pending_partial_withdrawals) == PENDING_PARTIAL_WITHDRAWALS_LIMIT
        and not is_full_exit_request):
        return

    # 2-7. Pubkey/creds/active/exiting/seasoned (same shape as consolidation)
    if request_pubkey not in validator_pubkeys: return
    if not (has_execution_withdrawal_credential(v) and creds[12:] == req.source_address): return
    if not is_active_validator(v, current_epoch): return
    if v.exit_epoch != FAR_FUTURE_EPOCH: return
    if current_epoch < v.activation_epoch + SHARD_COMMITTEE_PERIOD: return

    pending_balance = get_pending_balance_to_withdraw(state, index)

    if is_full_exit_request:
        if pending_balance == 0:
            initiate_validator_exit(state, index)
        return

    # Partial withdrawal: STRICTER credential requirement (0x02 only)
    has_sufficient_effective_balance = v.effective_balance >= MIN_ACTIVATION_BALANCE
    has_excess_balance = state.balances[index] > MIN_ACTIVATION_BALANCE + pending_balance

    if (has_compounding_withdrawal_credential(v)
        and has_sufficient_effective_balance
        and has_excess_balance):
        to_withdraw = min(state.balances[index] - MIN_ACTIVATION_BALANCE - pending_balance, amount)
        exit_queue_epoch = compute_exit_epoch_and_update_churn(state, to_withdraw)
        withdrawable_epoch = exit_queue_epoch + MIN_VALIDATOR_WITHDRAWABILITY_DELAY
        state.pending_partial_withdrawals.append(PendingPartialWithdrawal(
            validator_index=index, amount=to_withdraw, withdrawable_epoch=withdrawable_epoch))
```

The hypothesis: *all six clients implement the dual-mode logic, the queue-full carve-out, the strict 0x02-only partial constraint, and the use of `compute_exit_epoch_and_update_churn` (NOT `compute_consolidation_epoch_and_update_churn`) identically.*

**Glamsterdam target.** Gloas leaves `process_withdrawal_request` and `initiate_validator_exit` unchanged in shape, but reschedules the withdrawal pass and modifies the churn helper:

- Reschedules into `apply_parent_execution_payload` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1131`): withdrawal requests in any given Gloas block are taken from the **parent's** execution payload and processed at the **child's** slot.
- **Modifies `compute_exit_epoch_and_update_churn`** (`vendor/consensus-specs/specs/gloas/beacon-chain.md:855-883`) to call `get_exit_churn_limit(state)` rather than `get_activation_exit_churn_limit(state)`.
- Adds **new `get_exit_churn_limit`** (line 824-834): `max(MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA, total_active_balance // CHURN_LIMIT_QUOTIENT_GLOAS) - mod EBI`.
- Adds **new `get_activation_churn_limit`** (line 808-822): same shape, additionally capped at `MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT_GLOAS`.

The composition `get_activation_exit_churn_limit` (Electra: `min(get_balance_churn_limit, MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT)`) is **replaced by two separate quantities** at Gloas, with the exit side feeding `compute_exit_epoch_and_update_churn` and the activation side feeding deposit processing.

**Consensus relevance**: each successful partial appends to `state.pending_partial_withdrawals` and decrements `state.exit_balance_to_consume` / advances `state.earliest_exit_epoch`. Each successful full exit additionally sets `validator.exit_epoch` and `validator.withdrawable_epoch`. A divergence on the predicate would split the state-root immediately; a divergence on **the partial-withdrawal credential constraint** (accepting 0x01 instead of requiring 0x02) would be particularly bad — a 0x01-credentialed validator could repeatedly drain its excess balance via partials. A divergence on **the per-epoch churn limit** (Electra activation-exit vs Gloas exit-only) shifts both the `earliest_exit_epoch` written into state for accepted requests AND the `exit_balance_to_consume` decrement value — different state on the first Gloas-slot block carrying a withdrawal or voluntary-exit request.

## Hypotheses

- **H1.** All six identify the full-exit path as `amount == 0`, partial path otherwise.
- **H2.** All six implement the **queue-full carve-out**: when `len(pending_partial_withdrawals) == LIMIT` and the request is partial → silent return; full exits still proceed.
- **H3.** Source credential check (predicate 4) accepts BOTH 0x01 AND 0x02 via `has_execution_withdrawal_credential`. Source-address binding via `creds[12:32] == req.source_address`.
- **H4.** **Partial withdrawal additionally requires 0x02** via `has_compounding_withdrawal_credential` — 0x01 partials must be silently rejected.
- **H5.** All six route the partial-withdrawal balance through `compute_exit_epoch_and_update_churn` (NOT `compute_consolidation_epoch_and_update_churn`).
- **H6.** All six clamp `to_withdraw = min(balance - MIN_ACTIVATION_BALANCE - pending_balance, amount)` consistently.
- **H7.** All twelve short-circuits + the partial branch produce observable-equivalent accept/reject decisions on every input, and identical state mutations on accept.
- **H8** *(Glamsterdam target)*. At the Gloas fork gate, all six clients switch the per-epoch-churn quantity inside `compute_exit_epoch_and_update_churn` from `get_activation_exit_churn_limit(state)` (Electra) to `get_exit_churn_limit(state)` (Gloas). Pre-Gloas, all six retain the Electra formula.

## Findings

H1–H7 satisfied for the Pectra surface. **H8 also satisfied at the Glamsterdam target across all six clients** — every client fork-gates `compute_exit_epoch_and_update_churn` to call `get_exit_churn_limit` when running on a Gloas-or-later state. Source-level convergence; not yet covered by any EF fixture (no Gloas operations fixtures yet exist for this surface).

### prysm

`vendor/prysm/beacon-chain/core/requests/withdrawals.go:90-208` — `ProcessWithdrawalRequests`:

```go
amount := wr.Amount
isFullExitRequest := amount == params.BeaconConfig().FullExitRequestAmount  // (1)
if n == params.BeaconConfig().PendingPartialWithdrawalsLimit && !isFullExitRequest {
    continue  // (2) silent; full exit still proceeds
}
vIdx, exists := st.ValidatorIndexByPubkey(...)            // (3)
if !exists { continue }
if !hasCorrectCredential || !isCorrectSourceAddress { continue }  // (4)
if !helpers.IsActiveValidatorUsingTrie(validator, currentEpoch) { continue }  // (5)
if validator.ExitEpoch() != params.BeaconConfig().FarFutureEpoch { continue }  // (6)
if currentEpoch < validator.ActivationEpoch().AddEpoch(...) { continue }  // (7)
// ... full-exit vs partial branch ...
```

Partial path at `vendor/prysm/beacon-chain/core/requests/withdrawals.go:180-208` gates on `validator.HasCompoundingWithdrawalCredentials()` AND `hasSufficientEffectiveBalance` AND `hasExcessBalance` — 0x02 only. Calls `st.ExitEpochAndUpdateChurn(toWithdraw)`.

`ExitEpochAndUpdateChurn` at `vendor/prysm/beacon-chain/state/state-native/setters_churn.go:36-93` (the wrapper) → `exitEpochAndUpdateChurn` at the same file, line 67 (re-pinned `EIP-8061`):

```go
perEpochChurn := helpers.ExitChurnLimitForVersion(b.version, totalActiveBalance) // Guaranteed to be non-zero.
```

The per-version dispatcher `ExitChurnLimitForVersion` lives at `vendor/prysm/beacon-chain/core/helpers/validator_churn.go:115-121`:

```go
func ExitChurnLimitForVersion(v int, activeBalance primitives.Gwei) primitives.Gwei {
    if v >= version.Gloas {
        return exitChurnLimitGloas(activeBalance)
    }
    return ActivationExitChurnLimit(activeBalance)
}
```

`exitChurnLimitGloas` at `:75-89` implements the EIP-8061 uncapped form `max(MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA, total_active_balance // CHURN_LIMIT_QUOTIENT_GLOAS) − mod EBI`.

H1–H7 ✓. **H8 ✓** — version-dispatched at the `ExitEpochAndUpdateChurn` call site.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:494-587` — `process_withdrawal_requests<E>`:

```rust
let amount = request.amount;
let is_full_exit_request = amount == spec.full_exit_request_amount;  // (1)
if state.pending_partial_withdrawals()?.len() == E::pending_partial_withdrawals_limit()
    && !is_full_exit_request { continue }  // (2)
let Some(validator_index) = state.pubkey_cache().get(&request.validator_pubkey) else { continue };
let has_correct_credential = validator.has_execution_withdrawal_credential(spec);
if !(has_correct_credential && is_correct_source_address) { continue }
if !validator.is_active_at(state.current_epoch()) { continue }
if validator.exit_epoch != spec.far_future_epoch { continue }
if state.current_epoch() < validator.activation_epoch.safe_add(spec.shard_committee_period)? { continue }
```

Partial path (~line 564) gates on `has_compounding_withdrawal_credential(spec)` — 0x02 only. Calls `state.compute_exit_epoch_and_update_churn(to_withdraw, spec)`.

`compute_exit_epoch_and_update_churn` at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2896-2935` (re-pinned `unstable`) — variant `match` continues to include `Gloas` as a valid mutate-target, and the per-epoch-churn quantity is now fork-gated:

```rust
let per_epoch_churn = if self.fork_name_unchecked().gloas_enabled() {
    self.get_exit_churn_limit(spec)?
} else {
    self.get_activation_exit_churn_limit(spec)?
};
```

`get_exit_churn_limit` at `:2798-2800` is the EIP-8061 uncapped exit-churn helper (`self.get_balance_churn_limit(spec)`); doc-comment at `:2797` explicitly notes "Unlike `get_activation_exit_churn_limit`, this is uncapped." Sister site at `:3136-3137` reads both `get_exit_churn_limit` and `get_activation_exit_churn_limit` (the EIP-8061 split into two independent quantities is wired comprehensively, not just here).

`safe_*` overflow-checked arithmetic throughout (`safe_sub`, `safe_div`, `safe_add`, `safe_mul`, `safe_add_assign`), unchanged from the prior audit. The `additional_epochs` math at `:2920-2924` (`(balance_to_process − 1) / per_epoch_churn + 1` via four `safe_*` calls) is byte-equivalent to pyspec.

H1–H7 ✓. **H8 ✓** — lighthouse now joins lodestar in fork-gating the churn helper to EIP-8061.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/execution/ExecutionRequestsProcessorElectra.java:118-264` — `processWithdrawalRequests`. (Note: file moved from `electra/block/` to `electra/execution/` since the last audit.) Predicate sequence identical to pyspec 1→7, then explicit branch on `isFullExitRequest` at line 213. The partial path (lines 225-262) gates on `hasCompoundingWithdrawalCredential(validator)` (0x02 only). Calls `BeaconStateMutatorsElectra.computeExitEpochAndUpdateChurn`.

`computeExitEpochAndUpdateChurn` at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/BeaconStateMutatorsElectra.java:77-104` still uses `getActivationExitChurnLimit` (Electra formula). At Gloas (`glamsterdam-devnet-2`), `BeaconStateMutatorsGloas` extends `BeaconStateMutatorsElectra` and **overrides `computeExitEpochAndUpdateChurn`** at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/helpers/BeaconStateMutatorsGloas.java:72-104`:

```java
@Override
public UInt64 computeExitEpochAndUpdateChurn(
    final MutableBeaconStateElectra state, final UInt64 exitBalance) {
  final UInt64 earliestExitEpoch =
      miscHelpers
          .computeActivationExitEpoch(beaconStateAccessorsGloas.getCurrentEpoch(state))
          .max(state.getEarliestExitEpoch());
  final UInt64 perEpochChurn = beaconStateAccessorsGloas.getExitChurnLimit(state);
  ...
}
```

`BeaconStateAccessorsGloas.getExitChurnLimit:111-114` implements the EIP-8061 uncapped form via `computeBalanceChurnLimit(state, ChurnLimitQuotientGloas)`. `SpecLogicGloas.java:132-135` wires the Gloas mutator + accessor pair so the override is reached at Gloas state-transitions.

`getPendingBalanceToWithdraw` continues to be a `Stream.filter(...).reduce(UInt64::plus)` chain in `ValidatorsUtil.java`.

H1–H7 ✓. **H8 ✓** — `BeaconStateMutatorsGloas.computeExitEpochAndUpdateChurn @Override`.

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:544-624` — `process_withdrawal_request*`. Predicate sequence identical to pyspec 1→7. Partial path at lines 606+ gates on `has_compounding_withdrawal_credential(type(state).kind, validator)` (0x02 only). Calls `compute_exit_epoch_and_update_churn(cfg, state, to_withdraw, cache)`.

`compute_exit_epoch_and_update_churn*` at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:352-387` (re-pinned `unstable`):

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.5.0-alpha.0/specs/electra/beacon-chain.md#new-compute_exit_epoch_and_update_churn
# https://github.com/ethereum/consensus-specs/blob/v1.7.0-alpha.7/specs/gloas/beacon-chain.md#modified-compute_exit_epoch_and_update_churn
func compute_exit_epoch_and_update_churn*(
    cfg: RuntimeConfig,
    state: var (electra.BeaconState | fulu.BeaconState | gloas.BeaconState |
                heze.BeaconState),
    exit_balance: Gwei,
    cache: var StateCache): Epoch =
  var earliest_exit_epoch = max(state.earliest_exit_epoch,
    compute_activation_exit_epoch(get_current_epoch(state)))
  let per_epoch_churn =
    when typeof(state).kind >= ConsensusFork.Gloas:
      get_exit_churn_limit(cfg, state, cache)
    else:
      get_activation_exit_churn_limit(cfg, state, cache)
  ...
```

The signature now also accepts `heze.BeaconState`. The per-epoch-churn quantity is fork-gated at the Nim `when typeof(state).kind >= ConsensusFork.Gloas` boundary (compile-time dispatch). Doc-comment URLs carry both the Electra spec ref AND the current `v1.7.0-alpha.7/gloas` modified ref.

`get_pending_balance_to_withdraw` at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:1588-1607` continues to iterate `pending_partial_withdrawals` and sum by index, with the `when type(state).kind >= ConsensusFork.Gloas:` branch that also folds builder pending withdrawals + payments — confirmed still present on `unstable` and still a separate concern (item #23).

H1–H7 ✓. **H8 ✓** — nimbus now fork-gates the churn helper to EIP-8061 via Nim's compile-time `when` dispatch.

### lodestar

`vendor/lodestar/packages/state-transition/src/block/processWithdrawalRequest.ts:16-79` — `processWithdrawalRequest`:

```typescript
const amount = Number(withdrawalRequest.amount);
const isFullExitRequest = amount === FULL_EXIT_REQUEST_AMOUNT;
if (pendingPartialWithdrawals.length >= PENDING_PARTIAL_WITHDRAWALS_LIMIT && !isFullExitRequest) return;
const validatorIndex = pubkeyCache.getIndex(withdrawalRequest.validatorPubkey);
if (validatorIndex === null) return;
const validator = validators.get(validatorIndex);
if (!isValidatorEligibleForWithdrawOrExit(validator, withdrawalRequest.sourceAddress, state)) return;
// ... full vs partial branch ...
```

Lodestar bundles checks 4–7 (credential, address, active, not-exiting, seasoned) into a single `isValidatorEligibleForWithdrawOrExit` helper (`vendor/lodestar/packages/state-transition/src/block/processWithdrawalRequest.ts:81-97`). The helper is **also reused for `process_voluntary_exit`** — a single source of truth that simplifies maintenance but also means a divergence in the helper would simultaneously affect both paths.

Partial path (line 62 onwards) gates on `hasCompoundingWithdrawalCredential(validator.withdrawalCredentials)` (0x02 only). Calls `computeExitEpochAndUpdateChurn` at `vendor/lodestar/packages/state-transition/src/util/epoch.ts:50-77`:

```typescript
export function computeExitEpochAndUpdateChurn(
  state: CachedBeaconStateElectra | CachedBeaconStateGloas,
  exitBalance: Gwei
): number {
  const fork = state.config.getForkSeq(state.slot);
  let earliestExitEpoch = Math.max(state.earliestExitEpoch, computeActivationExitEpoch(state.epochCtx.epoch));
  const perEpochChurn =
    fork >= ForkSeq.gloas ? getExitChurnLimit(state.epochCtx) : getActivationExitChurnLimit(state.epochCtx);
  ...
}
```

`getExitChurnLimit` at `vendor/lodestar/packages/state-transition/src/util/validator.ts:107-...`, `getActivationChurnLimit` at line 95, `getActivationExitChurnLimit` at line 88 — fully Gloas-aware infrastructure. Lodestar is the only client implementing the EIP-8061 split.

`getPendingBalanceToWithdraw` (`vendor/lodestar/packages/state-transition/src/util/validator.ts:167-179`) sums via a tight loop. Uses JavaScript `number` for the amount (effective_balance values fit comfortably below 2⁵³).

**Subtle**: the queue-full check uses `>=` (not `==`) — `pendingPartialWithdrawals.length >= PENDING_PARTIAL_WITHDRAWALS_LIMIT`. The other clients use `==`. Functionally equivalent because the queue is bounded by SSZ schema (cannot exceed LIMIT), but lodestar's `>=` is defensive.

H1–H7 ✓. **H8 ✓** — the only client matching Gloas spec.

### grandine

`vendor/grandine/transition_functions/src/electra/block_processing.rs:1065-1152` — `process_withdrawal_request<P>`:

```rust
let amount = withdrawal_request.amount;
let is_full_exit_request = amount == FULL_EXIT_REQUEST_AMOUNT;
if state.pending_partial_withdrawals().len_usize() == P::PendingPartialWithdrawalsLimit::USIZE
    && !is_full_exit_request { return Ok(()); }
let Some(validator_index) = index_of_public_key(state, &request_pubkey) else { return Ok(()); };
// ... checks 4-7 explicit and sequential ...
let pending_balance_to_withdraw = get_pending_balance_to_withdraw(state, validator_index);
if is_full_exit_request {
    if pending_balance_to_withdraw == 0 { initiate_validator_exit(config, state, validator_index)?; }
    return Ok(());
}
if has_compounding_withdrawal_credential(validator) && has_sufficient_effective_balance && has_excess_balance {
    let to_withdraw = amount.min(...);
    let exit_queue_epoch = compute_exit_epoch_and_update_churn(config, state, to_withdraw);
    state.pending_partial_withdrawals_mut().push(...)?;
}
```

Partial path gates on `has_compounding_withdrawal_credential(validator)` (0x02 only). Calls `compute_exit_epoch_and_update_churn` at `vendor/grandine/helper_functions/src/mutators.rs:177-208` (re-pinned `glamsterdam-devnet-3`):

```rust
let per_epoch_churn = if state.is_post_gloas() {
    get_exit_churn_limit(config, state)
} else {
    get_activation_exit_churn_limit(config, state)
};
```

`get_exit_churn_limit` at `accessors.rs:1001-1009` implements the EIP-8061 uncapped form `max(MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA, total_active_balance // CHURN_LIMIT_QUOTIENT_GLOAS) − mod EBI`.

H1–H7 ✓. **H8 ✓** — fork-gated on `state.is_post_gloas()`.

## Cross-reference table

| Client | Main fn | `compute_exit_epoch_and_update_churn` | Gloas fork-gate (H8) | Partial 0x02 check | Notable idiom |
|---|---|---|---|---|---|
| prysm | `core/requests/withdrawals.go:90-208` | `state/state-native/setters_churn.go:67` — `ExitChurnLimitForVersion(b.version, totalActiveBalance)` dispatches to `exitChurnLimitGloas` at Gloas | **✓** | `HasCompoundingWithdrawalCredentials()` | `for ... { continue }` style; explicit pre-checks before unsafe sub |
| lighthouse | `per_block_processing/process_operations.rs:494-587` | `consensus/types/src/state/beacon_state.rs:2896-2935` — **fork-gated at `fork_name_unchecked().gloas_enabled()`**; reads `get_exit_churn_limit` (`:2798-2800`) at Gloas | **✓** | `has_compounding_withdrawal_credential(spec)` | `safe_*` arithmetic; `Result<()>` propagation |
| teku | `.../electra/execution/ExecutionRequestsProcessorElectra.java:118-264` | `.../electra/helpers/BeaconStateMutatorsElectra.java:77-104` (Electra: `getActivationExitChurnLimit`) + `.../gloas/helpers/BeaconStateMutatorsGloas.java:72-104 @Override` calling `beaconStateAccessorsGloas.getExitChurnLimit` | **✓** | `hasCompoundingWithdrawalCredential(validator)` | UInt64 wrapper; immutable validator setter |
| nimbus | `state_transition_block.nim:544-624` | `beaconstate.nim:352-387` — **fork-gated via `when typeof(state).kind >= ConsensusFork.Gloas`**; reads `get_exit_churn_limit` at Gloas/Heze | **✓** | `has_compounding_withdrawal_credential(type(state).kind, validator)` | Static fork dispatch via Nim `when` |
| lodestar | `block/processWithdrawalRequest.ts:16-79` | `util/epoch.ts:50-77` — **fork-gated, `getExitChurnLimit` at `fork ≥ ForkSeq.gloas`** | **✓** | `hasCompoundingWithdrawalCredential(...)` | Bundles checks 4-7 into `isValidatorEligibleForWithdrawOrExit` helper, shared with voluntary exit; uses `>=` not `==` for queue-full |
| grandine | `electra/block_processing.rs:1065-1152` | `helper_functions/src/mutators.rs:180-185` — `if state.is_post_gloas() { get_exit_churn_limit } else { get_activation_exit_churn_limit }` | **✓** | `has_compounding_withdrawal_credential(validator)` | Trait-bound `PostElectraBeaconState`; `Result<()>` |

## Empirical tests

### Pectra-surface fixture run

`consensus-spec-tests/tests/mainnet/electra/operations/withdrawal_request/pyspec_tests/` — 19 EF fixtures. Run via `scripts/run_fixture.sh` against all six clients on 2026-05-03:

```
                                                                        prysm  lighthouse  teku  nimbus  lodestar  grandine
activation_epoch_less_than_shard_committee_period                       PASS   PASS        SKIP  SKIP    PASS      PASS
basic_withdrawal_request                                                PASS   PASS        SKIP  SKIP    PASS      PASS
basic_withdrawal_request_with_compounding_credentials                   PASS   PASS        SKIP  SKIP    PASS      PASS
basic_withdrawal_request_with_first_validator                           PASS   PASS        SKIP  SKIP    PASS      PASS
full_exit_request_has_partial_withdrawal                                PASS   PASS        SKIP  SKIP    PASS      PASS
incorrect_inactive_validator                                            PASS   PASS        SKIP  SKIP    PASS      PASS
incorrect_source_address                                                PASS   PASS        SKIP  SKIP    PASS      PASS
incorrect_withdrawal_credential_prefix                                  PASS   PASS        SKIP  SKIP    PASS      PASS
insufficient_balance                                                    PASS   PASS        SKIP  SKIP    PASS      PASS
insufficient_effective_balance                                          PASS   PASS        SKIP  SKIP    PASS      PASS
no_compounding_credentials                                              PASS   PASS        SKIP  SKIP    PASS      PASS
no_excess_balance                                                       PASS   PASS        SKIP  SKIP    PASS      PASS
on_withdrawal_request_initiated_exit_validator                          PASS   PASS        SKIP  SKIP    PASS      PASS
partial_withdrawal_activation_epoch_less_than_shard_committee_period    PASS   PASS        SKIP  SKIP    PASS      PASS
partial_withdrawal_incorrect_source_address                             PASS   PASS        SKIP  SKIP    PASS      PASS
partial_withdrawal_incorrect_withdrawal_credential_prefix               PASS   PASS        SKIP  SKIP    PASS      PASS
partial_withdrawal_on_exit_initiated_validator                          PASS   PASS        SKIP  SKIP    PASS      PASS
pending_withdrawals_consume_all_excess_balance                          PASS   PASS        SKIP  SKIP    PASS      PASS
unknown_pubkey                                                          PASS   PASS        SKIP  SKIP    PASS      PASS
```

19/19 fixtures pass uniformly on prysm + lighthouse + lodestar + grandine. teku and nimbus SKIP (no per-operation CLI hook); both pass these in their internal CI.

**Coverage assessment:** rich set. Exercises both full-exit AND partial branches; both 0x01 and 0x02 credentials; the `no_compounding_credentials` fixture specifically tests that a 0x01 partial-withdrawal request is rejected (H4); the `incorrect_withdrawal_credential_prefix` fixture tests a 0x00 source. The `pending_withdrawals_consume_all_excess_balance` fixture tests that `to_withdraw = min(...)` clamps to zero when prior partials have already drained the validator. The `full_exit_request_has_partial_withdrawal` fixture tests the full-exit-blocked-by-pending-partial carve-out. Notably absent: a queue-full fixture (impractical at LIMIT = 2²⁷); a multi-request churn-drain fixture (operations format is single-op).

### Gloas-surface

No Gloas operations fixtures exist yet in the EF set. H8 is currently source-only.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — full-exit blocks on existing partial).** Validator with `0x02` creds AND a non-empty `pending_partial_withdrawals` entry for the validator. A full-exit request (amount=0) must NOT trigger `initiate_validator_exit` because `pending_balance_to_withdraw > 0`. The existing `full_exit_request_has_partial_withdrawal` fixture covers this; check that all six handle the silent reject identically.
- **T1.2 (priority — partial clamp to zero).** Validator with `0x02` creds, `balance = MIN_ACTIVATION_BALANCE + pending_balance` (no excess). The `has_excess_balance` predicate is `balance > MIN_ACTIVATION_BALANCE + pending_balance` — strictly greater. With equality, partial silently fails. The `pending_withdrawals_consume_all_excess_balance` fixture exercises this; verify all six.
- **T1.3 (priority — composed switch + partial in one block).** Block contains a switch-to-compounding consolidation_request AND a partial withdrawal_request for the same validator (currently 0x01). Per EIP-7685 ordering, withdrawals are processed before consolidations, so partial fails on the still-0x01 credential, then switch flips to 0x02. The "lost partial" is canonical — a deliberate design choice in the spec. Verify all six clients produce the same lost-partial outcome and the same post-block 0x02 credential.

#### T2 — Adversarial probes
- **T2.1 (priority — 0x01 partial-withdrawal attempt).** Validator with `0x01` creds. Partial withdrawal request with amount > 0. Must be silently rejected (H4). The `no_compounding_credentials` fixture covers this; verify uniformly.
- **T2.2 (priority — multi-request churn drain).** Single block contains N withdrawal_requests, each a partial that consumes the entire `exit_balance_to_consume`. Expected: only the first M (M < N) succeed; the rest hit churn exhaustion (the comparison in `compute_exit_epoch_and_update_churn` advances `earliest_exit_epoch` rather than rejecting outright — but the **ordering** of state mutations across requests is what matters). Tests stateful intra-block iteration. Not directly testable at the operations-fixture level; requires a sanity_blocks fixture.
- **T2.3 (defensive — amount > balance - MIN - pending).** Partial request with amount = 10 ETH, but validator has balance = MIN_ACTIVATION_BALANCE + 5 ETH and pending_balance = 0. Then `to_withdraw = min(5, 10) = 5`. Verify the clamp produces 5 across all six. Exercised by `basic_withdrawal_request_with_compounding_credentials`.
- **T2.4 (defensive — amount = exact excess).** Same as T2.3 but amount = 5 (exactly the available excess). `to_withdraw = min(5, 5) = 5`. Verify uniformly.
- **T2.5 (queue-full but full-exit succeeds).** Construct a state with `pending_partial_withdrawals.len == LIMIT`. Send a full-exit request (amount = 0). Per pyspec, the queue-full carve-out lets this through. Construction is impractical for a generated fixture (LIMIT = 2²⁷); a future custom fixture could shrink the limit at fork-config level for testing.
- **T2.6 (Glamsterdam-target — Gloas exit-churn formula).** Synthetic Gloas-fork state at the first Gloas slot with active total balance chosen so the Electra formula `get_activation_exit_churn_limit` and the Gloas formula `get_exit_churn_limit` yield different values. Submit a single full-exit request (amount = 0) on a `0x02` validator with `effective_balance` between the two churn-limit values, then submit a partial-withdrawal request that straddles the same threshold. Expected per Gloas spec: `compute_exit_epoch_and_update_churn` advances `earliest_exit_epoch` by `(balance_to_process − 1) / get_exit_churn_limit + 1`. The five Electra-formula clients will compute a different `additional_epochs` than lodestar; the post-state `earliest_exit_epoch` and `exit_balance_to_consume` will diverge. The single highest-value fixture to write before Glamsterdam activation; sister to item #2's T2.5 on the consolidation-churn side.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H7) remain satisfied: aligned implementations of `process_withdrawal_request` with correct dual-mode branching, correct enforcement of the 0x02-only partial constraint (H4), and correct routing through `compute_exit_epoch_and_update_churn` for the partial-withdrawal balance (H5, modulo the Gloas-specific churn-helper question below). All 19 EF `operations/withdrawal_request` fixtures still pass uniformly on prysm, lighthouse, lodestar, grandine. Notable per-client style differences are unchanged from the prior audit (lodestar bundles eligibility via a helper shared with voluntary exit; lodestar uses `>=` for queue-full; lighthouse `safe_*`; prysm explicit pre-checks; nimbus's Gloas-aware `get_pending_balance_to_withdraw` branch that is dead at Pectra).

**Glamsterdam-target finding (refreshed after the full re-pin sweep):** H8 now holds across all six clients. Gloas (EIP-8061) modifies `compute_exit_epoch_and_update_churn` to call `get_exit_churn_limit` rather than `get_activation_exit_churn_limit`, and adds `get_exit_churn_limit` and `get_activation_churn_limit` as separate new functions. Every client correctly fork-gates the churn helper:

- **lighthouse** (`unstable`): `if self.fork_name_unchecked().gloas_enabled()` at `beacon_state.rs:2906-2910`.
- **nimbus** (`unstable`): `when typeof(state).kind >= ConsensusFork.Gloas` at `beaconstate.nim:362-365`.
- **lodestar** (`unstable`): `fork >= ForkSeq.gloas` at `util/epoch.ts:60`.
- **prysm** (`EIP-8061` branch): runtime version dispatch via `ExitChurnLimitForVersion(b.version, …)` at `setters_churn.go:67`.
- **teku** (`glamsterdam-devnet-2` branch): `BeaconStateMutatorsGloas.computeExitEpochAndUpdateChurn:72-104 @Override` calling `beaconStateAccessorsGloas.getExitChurnLimit`.
- **grandine** (`glamsterdam-devnet-3` branch): `if state.is_post_gloas()` at `mutators.rs:180-185`.

The earlier 5-vs-1 and 3-vs-3 framings of this finding were artifacts of auditing against the wrong branches (the same root cause as item #2). With each client on its actual Glamsterdam branch, H8 is uniformly satisfied.

Recommendations to the harness and the audit:
- Generate the **T2.6 Gloas exit-churn formula fixture** when EF spec-test infrastructure for Gloas operations lands. Source-level convergence is necessary but not sufficient; cross-client wire-format proof needs a real fixture.
- **Generate the T2.2 multi-request churn-drain fixture** as a sanity_blocks fixture; highest-value untested Pectra-surface scenario for both this item and item #2.
- Audit `compute_exit_epoch_and_update_churn` as a standalone item — used here, in `initiate_validator_exit`, in `process_voluntary_exit`, and indirectly in item #2 via consolidation init. A divergence in this function would affect all four paths.
- Audit `initiate_validator_exit` as a standalone item — called from the full-exit path here and from `process_voluntary_exit`.

## Cross-cuts

### With item #2 (`process_consolidation_request`)

This item and item #2 share five predicates: pubkey existence, source-address binding (`creds[12:32]`), `has_execution_withdrawal_credential`, active, not-exiting, seasoned-by-`SHARD_COMMITTEE_PERIOD`. A regression in any of these would surface in BOTH items' fixtures simultaneously.

The TWO functions also share the `compute_exit_epoch_and_update_churn` mechanism for source-exit-init or partial-withdrawal balance — but use different churn limits internally:

- This item (`process_withdrawal_request` partial path) → `get_activation_exit_churn_limit` at Electra, `get_exit_churn_limit` at Gloas.
- Item #2 (`process_consolidation_request` main path via `compute_consolidation_epoch_and_update_churn`) → `get_consolidation_churn_limit` (both Electra and Gloas, but the Gloas formula is different).

A client mixing these up would diverge here in the rate of partial-withdrawal acceptance. All six are clean on the Electra-vs-consolidation distinction. The Glamsterdam-target divergence (H8) is **symmetric to item #2's H6**: the same five clients lag on both churn helpers, and lodestar is ahead on both.

**Composed scenario worth fixturing (T1.3 above)**: same validator receives a switch-to-compounding consolidation_request (item #2's switch path) AND a partial withdrawal_request in the same block. EIP-7685 request ordering is deposits → withdrawals → consolidations, so the consolidation always processes AFTER the withdrawal. The lost-partial-withdrawal scenario above is canonical for legacy 0x01 validators that consolidate in the same block.

### With `initiate_validator_exit` (called on full-exit success)

The full-exit path calls `initiate_validator_exit(state, index)`, which internally calls `compute_exit_epoch_and_update_churn(state, validator.effective_balance)`. The `effective_balance` here is the **validator's** (32 ETH for 0x01, up to 2048 ETH for 0x02), NOT the withdrawal request's amount. This means a 0x02 validator with 2000 ETH effective balance triggers a full exit that consumes 2000 ETH of the exit churn limit — significant. The Gloas-target divergence (H8) ripples through this call site too: at Gloas, lodestar's `initiate_validator_exit` will consume churn at the EIP-8061 rate while the other five consume at the Electra rate.

### With `process_voluntary_exit` (lodestar shared helper)

Lodestar's `isValidatorEligibleForWithdrawOrExit` is reused in `process_voluntary_exit`. A divergence in that helper would simultaneously affect this item AND voluntary exits — easier to detect (more fixtures) but harder to localize. The other 5 clients have separate eligibility code paths per operation. Voluntary exit also calls `initiate_validator_exit` → `compute_exit_epoch_and_update_churn`, so the Glamsterdam-target H8 divergence affects voluntary exits identically.

### With `process_pending_partial_withdrawals` (drain side, modified-in-Pectra)

This item appends to `state.pending_partial_withdrawals`. The drain happens at `process_pending_partial_withdrawals` (a separate item, candidate). Append ordering matters — if any client reorders or de-duplicates the queue, the drain order changes which cascades into `process_withdrawals` and per-validator balance changes.

### With Gloas ePBS scheduling (EIP-7732)

Gloas moves the withdrawal pass out of `process_operations` into `apply_parent_execution_payload` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1131`). The withdrawal requests in any given Gloas block are taken from the **parent's** execution payload and processed at the **child's** slot. Item-level effect: the per-operation logic is unchanged, but the slot-relative state visible to `process_withdrawal_request` differs from the Electra schedule. Cross-cut to the ePBS payload-availability audit.

## Adjacent untouched Electra-active consensus paths

1. **`compute_exit_epoch_and_update_churn` standalone audit** — used by 4+ paths; Glamsterdam-target H8 makes this the most urgent standalone audit. Boundary: per-epoch churn fully consumed by a single request that exceeds it; the function should advance `earliest_exit_epoch` rather than reject.
2. **`initiate_validator_exit` standalone audit** — Pectra-modified to use `compute_exit_epoch_and_update_churn` with `effective_balance` instead of the pre-Electra fixed-rate exit queue. Cross-cut with `process_voluntary_exit`. Gloas-target H8 propagates here through the shared churn helper.
3. **`get_pending_balance_to_withdraw` linear-scan complexity** — every withdrawal_request and consolidation_request iterates the full `pending_partial_withdrawals` queue (LIMIT = 2²⁷). Performance, not consensus, but an OOM-induced state divergence under adversarial queue growth is theoretically reachable.
4. **Lodestar's `isValidatorEligibleForWithdrawOrExit` shared helper** — a regression here affects both withdrawal_request AND voluntary_exit. Higher detection probability but harder localization. Worth a comment in the helper noting the dual responsibility.
5. **Composed switch + partial in one block** (T1.3 above) — the canonical "lost partial withdrawal" scenario for legacy validators that switch in the same block. Generate a fixture.
6. **`pending_partial_withdrawals` queue ordering** — append order at this item determines drain order at `process_pending_partial_withdrawals`. Cross-cuts with the `process_pending_partial_withdrawals` audit.
7. **Nimbus's Gloas-aware `get_pending_balance_to_withdraw`** — pre-emptive divergence vector at the Gloas fork target. The `when consensusFork >= ConsensusFork.Gloas` branch sums builder withdrawals too, which other clients won't.
8. **0x02 validator with `effective_balance < MIN_ACTIVATION_BALANCE`** — e.g., recently slashed. Partial withdrawal silently fails on `has_sufficient_effective_balance`. Reachable but weird. Verify all six handle uniformly.
9. **`FULL_EXIT_REQUEST_AMOUNT == 0` collision with a validator's actual zero-amount partial** — the spec says amount=0 means "full exit" universally. A validator that wants to withdraw exactly zero gwei (a no-op) cannot signal that without triggering full exit. Spec quirk; not a divergence vector but worth documenting in case any client adds a workaround.
10. **EIP-7685 request ordering**: `deposits → withdrawals → consolidations` per `process_execution_layer_block_requests`. A client that reordered would split. Worth a separate item on the requests dispatcher itself.
11. **Gloas `get_activation_churn_limit` (new, line 808)** — sibling to `get_exit_churn_limit`. Used by deposit-side throttling at Gloas. Item-pair candidate alongside the EIP-8061 audit family (item #2 H6, this item's H8, this churn-side activation throttle).
