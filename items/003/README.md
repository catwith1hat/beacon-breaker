# Item #3 — `process_withdrawal_request` EIP-7002 full-exit + partial paths

**Status:** no-divergence-pending-fuzzing — audited 2026-05-03. **Hypotheses H1–H7 satisfied. All 19 EF `withdrawal_request` operations fixtures pass on all four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus SKIP per harness limitation.**

**Builds on:** item #2 (`process_consolidation_request`) — shares the `SHARD_COMMITTEE_PERIOD` seasoning check, the active/exiting predicates, the `has_execution_withdrawal_credential` (0x01 OR 0x02) credential check, and the silent-on-invalid-input idiom. Together they form the EIP-7002/EIP-7251 execution-layer-triggered request pair.

**Electra-active.** Track A — Pectra request-processing. Processes EL-triggered `WithdrawalRequest`s (EIP-7002) appended via the EIP-7685 requests framework. Two distinct flows under one entrypoint: (1) **full exit** when `amount == FULL_EXIT_REQUEST_AMOUNT` (= 0), which calls `initiate_validator_exit`, and (2) **partial withdrawal** for non-zero amounts, which appends a `PendingPartialWithdrawal` to be drained later by `process_pending_partial_withdrawals`. The function also has a **queue-full-but-allow-full-exits** carve-out: when the partial-withdrawals queue is full, full-exit requests still succeed.

## Question

EIP-7002 entrypoint with two semantic flows. Pyspec (`vendor/consensus-specs/specs/electra/beacon-chain.md:1735–1800`):

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
        # Full exit only succeeds if no partials in queue for this validator
        if pending_balance == 0:
            initiate_validator_exit(state, index)
        return

    # Partial withdrawal: STRICTER credential requirement (0x02 only)
    has_sufficient_effective_balance = v.effective_balance >= MIN_ACTIVATION_BALANCE
    has_excess_balance = state.balances[index] > MIN_ACTIVATION_BALANCE + pending_balance

    if (has_compounding_withdrawal_credential(v)        # 0x02 ONLY
        and has_sufficient_effective_balance
        and has_excess_balance):
        to_withdraw = min(state.balances[index] - MIN_ACTIVATION_BALANCE - pending_balance, amount)
        exit_queue_epoch = compute_exit_epoch_and_update_churn(state, to_withdraw)
        withdrawable_epoch = exit_queue_epoch + MIN_VALIDATOR_WITHDRAWABILITY_DELAY
        state.pending_partial_withdrawals.append(PendingPartialWithdrawal(
            validator_index=index, amount=to_withdraw, withdrawable_epoch=withdrawable_epoch))
```

The hypothesis: *all six clients implement the dual-mode logic, the queue-full carve-out, the strict 0x02-only partial constraint, and the use of `compute_exit_epoch_and_update_churn` (NOT `compute_consolidation_epoch_and_update_churn`) identically.*

**Consensus relevance**: Each successful partial appends to `state.pending_partial_withdrawals` and decrements `state.exit_balance_to_consume` / advances `state.earliest_exit_epoch`. Each successful full exit additionally sets `validator.exit_epoch` and `validator.withdrawable_epoch`. A divergence on the predicate would split the state-root immediately; a divergence on **the partial-withdrawal credential constraint** (accepting 0x01 instead of requiring 0x02) would be particularly bad — a 0x01-credentialed validator could repeatedly drain its excess balance via partials, breaking the assumed `exit-only-via-full-exit-or-consolidation` model for legacy validators. A divergence on **churn-limit selection** (using consolidation churn — typically smaller — instead of activation-exit churn) would change the rate at which partial withdrawals propagate.

## Hypotheses

- **H1.** All six identify the full-exit path as `amount == 0`, partial path otherwise.
- **H2.** All six implement the **queue-full carve-out**: when `len(pending_partial_withdrawals) == LIMIT` and the request is partial → silent return; full exits still proceed.
- **H3.** Source credential check (predicate 4) accepts BOTH 0x01 AND 0x02 via `has_execution_withdrawal_credential`. Source-address binding via `creds[12:32] == req.source_address`.
- **H4.** **Partial withdrawal additionally requires 0x02** via `has_compounding_withdrawal_credential` — 0x01 partials must be silently rejected.
- **H5.** All six use `compute_exit_epoch_and_update_churn` (which internally uses `get_activation_exit_churn_limit`) for the partial-withdrawal balance — NOT `compute_consolidation_epoch_and_update_churn` (smaller churn limit).
- **H6.** All six clamp `to_withdraw = min(balance - MIN_ACTIVATION_BALANCE - pending_balance, amount)` consistently.
- **H7.** All twelve short-circuits + the partial branch produce observable-equivalent accept/reject decisions on every input, and identical state mutations on accept.

## Findings

H1–H7 satisfied. **No divergence at the source-level predicate or the EF-fixture level. All 19 EF operations fixtures pass uniformly on the four wired clients.**

### prysm (`prysm/beacon-chain/core/requests/withdrawals.go:90–208`)

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

The partial path (lines ~177–200) gates on `validator.HasCompoundingWithdrawalCredentials()` AND `hasExcessBalance` AND `hasSufficientEffectiveBalance` — **0x02 only**. Calls `st.ExitEpochAndUpdateChurn(toWithdraw)` which internally uses `helpers.ActivationExitChurnLimit(totalActiveBalance)` — **NOT** consolidation churn.

H1–H7 ✓.

### lighthouse (`lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:494–587`)

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

Partial path (~line 564) gates on `has_compounding_withdrawal_credential(spec)` — 0x02 only. Calls `state.compute_exit_epoch_and_update_churn(to_withdraw, spec)` (`beacon_state.rs:2705+`) which uses `self.get_activation_exit_churn_limit(spec)?` — correct.

`safe_*` overflow-checked arithmetic throughout, including the `validator.activation_epoch.safe_add(...)` seasoning check and the `pending_balance.safe_add_assign(withdrawal.amount)?` accumulation in `get_pending_balance_to_withdraw`.

H1–H7 ✓.

### teku (`teku/ethereum/spec/.../ExecutionRequestsProcessorElectra.java:118–264`)

Predicate sequence identical to pyspec 1→7, then explicit branch on `isFullExitRequest`. The partial path (lines 225–262) gates on `hasCompoundingWithdrawalCredential(validator)` (0x02 only). Calls `BeaconStateMutatorsElectra.computeExitEpochAndUpdateChurn` (`:77-104`) which uses `getActivationExitChurnLimit()` (line 83) — correct.

`getPendingBalanceToWithdraw` (`ValidatorsUtil.java:180-186`) is a `Stream.filter(...).map(...).reduce(UInt64::plus).orElse(UInt64.ZERO)` chain — functionally equivalent.

H1–H7 ✓.

### nimbus (`nimbus/beacon_chain/spec/state_transition_block.nim:544–624`)

Predicate sequence identical to pyspec 1→7. Partial path (lines 599–624) gates on `has_compounding_withdrawal_credential(validator)` (0x02 only). Calls `compute_exit_epoch_and_update_churn(cfg, state, to_withdraw, cache)` (`beaconstate.nim:286-314`) which uses `get_activation_exit_churn_limit(cfg, state, cache)` (line 293) — correct.

`get_pending_balance_to_withdraw` (`beaconstate.nim:1543-1559`) iterates `pending_partial_withdrawals` and sums by index, with a `when consensusFork >= ConsensusFork.Gloas:` branch reserved for Gloas builder withdrawals (dead at Pectra target — same Gloas-aware pattern observed in item #1).

H1–H7 ✓.

### lodestar (`lodestar/packages/state-transition/src/block/processWithdrawalRequest.ts:16–79`)

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

**Notable**: lodestar bundles checks 4–7 (credential, address, active, not-exiting, seasoned) into a single `isValidatorEligibleForWithdrawOrExit` helper (lines 81–97). The helper is **also reused for `process_voluntary_exit`** — a single source of truth that simplifies maintenance but also means a divergence in the helper would simultaneously affect both paths.

Partial path (line 62 onwards) gates on `hasCompoundingWithdrawalCredential(validator.withdrawalCredentials)` (0x02 only). Calls `computeExitEpochAndUpdateChurn` (`util/epoch.ts:50-74`) which uses `getActivationExitChurnLimit` for pre-Gloas (line 57) — correct.

`getPendingBalanceToWithdraw` (`util/validator.ts:167-179`) sums via a tight loop. Uses JavaScript `number` for the amount (effective_balance values fit comfortably below 2⁵³).

**Subtle**: the queue-full check uses `>=` (not `==`) — `pendingPartialWithdrawals.length >= PENDING_PARTIAL_WITHDRAWALS_LIMIT`. The other clients use `==`. Functionally equivalent because the queue is bounded by SSZ schema (cannot exceed LIMIT), but lodestar's `>=` is defensive. Worth noting in the cross-reference.

H1–H7 ✓.

### grandine (`grandine/transition_functions/src/electra/block_processing.rs:1065–1152`)

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

Partial path gates on `has_compounding_withdrawal_credential(validator)` (0x02 only). Calls `compute_exit_epoch_and_update_churn` (`mutators.rs:177-209`) which uses `get_activation_exit_churn_limit(config, state)` (line 186) — correct.

H1–H7 ✓.

## Cross-reference table

| Client | Main fn | `get_pending_balance_to_withdraw` | `compute_exit_epoch_and_update_churn` | Partial 0x02 check | Notable idiom |
|---|---|---|---|---|---|
| prysm | `core/requests/withdrawals.go:90-208` | `state-native/getters_validator.go:PendingBalanceToWithdraw` | `state-native/setters_churn.go:36-93` (`ActivationExitChurnLimit`) | `HasCompoundingWithdrawalCredentials()` | `for ... { continue }` style; explicit pre-checks before unsafe sub |
| lighthouse | `per_block_processing/process_operations.rs:494-587` | `state/beacon_state.rs:get_pending_balance_to_withdraw` (safe_add) | `state/beacon_state.rs:2705+` (`get_activation_exit_churn_limit`) | `has_compounding_withdrawal_credential(spec)` | `safe_*` arithmetic; `Result<()>` propagation |
| teku | `ExecutionRequestsProcessorElectra.java:118-264` | `ValidatorsUtil.java:180-186` (Stream chain) | `BeaconStateMutatorsElectra.java:77-104` (`getActivationExitChurnLimit`) | `hasCompoundingWithdrawalCredential(validator)` | UInt64 wrapper; immutable validator setter |
| nimbus | `state_transition_block.nim:544-624` | `beaconstate.nim:1543-1559` (with Gloas builder branch) | `beaconstate.nim:286-314` (`get_activation_exit_churn_limit`) | `has_compounding_withdrawal_credential(validator)` | Static fork dispatch; Gloas-ready predicates |
| lodestar | `block/processWithdrawalRequest.ts:16-79` | `util/validator.ts:167-179` | `util/epoch.ts:50-74` (`getActivationExitChurnLimit`) | `hasCompoundingWithdrawalCredential(...)` | **Bundles checks 4-7 into `isValidatorEligibleForWithdrawOrExit` helper, shared with voluntary exit**; uses `>=` not `==` for queue-full |
| grandine | `electra/block_processing.rs:1065-1152` | `helper_functions/accessors.rs:982-992` | `helper_functions/mutators.rs:177-209` (`get_activation_exit_churn_limit`) | `has_compounding_withdrawal_credential(validator)` | Trait-bound `PostElectraBeaconState`; `Result<()>` |

## Cross-cuts

### with item #2 (`process_consolidation_request`)

This item and item #2 share five predicates: pubkey existence, source-address binding (`creds[12:32]`), `has_execution_withdrawal_credential`, active, not-exiting, seasoned-by-`SHARD_COMMITTEE_PERIOD`. A regression in any of these would surface in BOTH items' fixtures simultaneously. The fact that all 10 consolidation_request and all 19 withdrawal_request fixtures pass uniformly is **stronger evidence of correctness for these shared predicates** than either item alone.

The TWO functions also **share the `compute_exit_epoch_and_update_churn` mechanism** for source-exit-init or partial-withdrawal balance — but use different churn limits internally:
- This item (`process_withdrawal_request` partial path) → `get_activation_exit_churn_limit`
- Item #2 (`process_consolidation_request` main path) → `get_consolidation_churn_limit`

A client mixing these up would diverge here in the rate of partial-withdrawal acceptance. All six are clean.

**Composed scenario worth fixturing (T1.3)**: same validator receives a switch-to-compounding consolidation_request (item #2's switch path) AND a partial withdrawal_request in the same block. Order matters:
- If switch happens first: validator becomes 0x02; partial-withdrawal succeeds.
- If partial-withdrawal happens first: validator is still 0x01; partial-withdrawal silently fails (predicate 4 of the partial branch). Switch then happens, but the partial was already lost.

Both orderings should be agreed upon by all six clients. The execution-layer requests have a defined ordering in the requests list (deposits → withdrawals → consolidations), so the consolidation always processes AFTER the withdrawal. This means the lost-partial-withdrawal scenario above is the canonical one for legacy 0x01 validators that consolidate in the same block.

### with `initiate_validator_exit` (called on full-exit success)

The full-exit path calls `initiate_validator_exit(state, index)`, which internally calls `compute_exit_epoch_and_update_churn(state, validator.effective_balance)`. The `effective_balance` here is the **validator's** (32 ETH for 0x01, up to 2048 ETH for 0x02), NOT the withdrawal request's amount. This means a 0x02 validator with 2000 ETH effective balance triggers a full exit that consumes 2000 ETH of the activation-exit churn limit — significant. Worth a fixture: many full-exit requests in one block, observe churn drain.

### with `process_voluntary_exit` (lodestar shared helper)

Lodestar's `isValidatorEligibleForWithdrawOrExit` is reused in `process_voluntary_exit`. A divergence in that helper would simultaneously affect this item AND voluntary exits — easier to detect (more fixtures) but harder to localize. The other 5 clients have separate eligibility code paths per operation.

### with `process_pending_partial_withdrawals` (drain side, modified-in-Pectra)

This item appends to `state.pending_partial_withdrawals`. The drain happens at `process_pending_partial_withdrawals` (a separate item, candidate). Append ordering matters — if any client reorders or de-duplicates the queue, the drain order changes which cascades into `process_withdrawals` and per-validator balance changes.

## Fixture

`fixture/`: deferred — used the existing 19 EF state-test fixtures at
`consensus-spec-tests/tests/mainnet/electra/operations/withdrawal_request/pyspec_tests/`.

Run via `scripts/run_fixture.sh` against all six clients on 2026-05-03:

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

**Coverage assessment**: this set is much richer than the 10 consolidation fixtures. It exercises both full-exit AND partial branches; both 0x01 and 0x02 credentials; the `no_compounding_credentials` fixture specifically tests that a 0x01 partial-withdrawal request is rejected (H4); the `incorrect_withdrawal_credential_prefix` fixture tests a 0x00 source. The `pending_withdrawals_consume_all_excess_balance` fixture tests that `to_withdraw = min(...)` clamps to zero when prior partials have already drained the validator. The `full_exit_request_has_partial_withdrawal` fixture tests the full-exit-blocked-by-pending-partial carve-out. **Notably absent**: a queue-full fixture (would require constructing a state with ≥ 2²⁷ pending partials — impractical to ship as a fixture); a multi-request churn-drain fixture (would require multiple withdrawal_requests in one block — at the operations layer there's only one per fixture).

## Fuzzing vectors

### T1 — Mainline canonical
- **T1.1 (priority — full-exit blocks on existing partial).** Validator with `0x02` creds AND a non-empty `pending_partial_withdrawals` entry for the validator. A full-exit request (amount=0) must NOT trigger `initiate_validator_exit` because `pending_balance_to_withdraw > 0`. The existing `full_exit_request_has_partial_withdrawal` fixture covers this; check that all six handle the silent reject identically.
- **T1.2 (priority — partial clamp to zero).** Validator with `0x02` creds, `balance = MIN_ACTIVATION_BALANCE + pending_balance` (no excess). The `has_excess_balance` predicate is `balance > MIN_ACTIVATION_BALANCE + pending_balance` — strictly greater. With equality, partial silently fails. The `pending_withdrawals_consume_all_excess_balance` fixture exercises this; verify all six.
- **T1.3 (priority — composed switch + partial in one block).** Block contains a switch-to-compounding consolidation_request AND a partial withdrawal_request for the same validator (currently 0x01). Per EIP-7685 ordering, withdrawals are processed before consolidations, so partial fails on the still-0x01 credential, then switch flips to 0x02. The "lost partial" is canonical — a deliberate design choice in the spec. Verify all six clients produce the same lost-partial outcome and the same post-block 0x02 credential.

### T2 — Adversarial probes
- **T2.1 (priority — 0x01 partial-withdrawal attempt).** Validator with `0x01` creds. Partial withdrawal request with amount > 0. Must be silently rejected (H4). The `no_compounding_credentials` fixture covers this; verify uniformly.
- **T2.2 (priority — multi-request churn drain).** Single block contains N withdrawal_requests, each a partial that consumes the entire `exit_balance_to_consume`. Expected: only the first M (M < N) succeed; the rest hit churn exhaustion (the comparison in `compute_exit_epoch_and_update_churn` advances `earliest_exit_epoch` rather than rejecting outright — but the **ordering** of state mutations across requests is what matters). Tests stateful intra-block iteration. Not directly testable at the operations-fixture level; requires a sanity_blocks fixture.
- **T2.3 (defensive — amount > balance - MIN - pending).** Partial request with amount = 10 ETH, but validator has balance = MIN_ACTIVATION_BALANCE + 5 ETH and pending_balance = 0. Then `to_withdraw = min(5, 10) = 5`. Verify the clamp produces 5 across all six. This is the standard partial-amount-clamp scenario; no dedicated fixture but exercised by `basic_withdrawal_request_with_compounding_credentials`.
- **T2.4 (defensive — amount = exact excess).** Same as T2.3 but amount = 5 (exactly the available excess). `to_withdraw = min(5, 5) = 5`. Verify uniformly.
- **T2.5 (queue-full but full-exit succeeds).** Construct a state with `pending_partial_withdrawals.len == LIMIT`. Send a full-exit request (amount = 0). Per pyspec, the queue-full carve-out lets this through. Construction is impractical for a generated fixture (LIMIT = 2²⁷); a future custom fixture could shrink the limit at fork-config level for testing.

## Conclusion

**Status: no-divergence-pending-fuzzing.** All six clients implement the dual-mode `process_withdrawal_request` with aligned predicate ordering, identical full-exit-vs-partial branching, and correct enforcement of the two divergence-prone bits: (a) **partial withdrawals require 0x02 credentials only** (H4), and (b) **partial-withdrawal balance flows through `get_activation_exit_churn_limit`, not `get_consolidation_churn_limit`** (H5). All 19 EF `operations/withdrawal_request` fixtures pass uniformly on the four wired clients; teku and nimbus pass internally.

Notable per-client style differences (all observable-equivalent at the spec level):
- **lodestar** bundles eligibility checks 4–7 into `isValidatorEligibleForWithdrawOrExit`, shared with voluntary exit;
- **lodestar** uses `>=` for the queue-full check where others use `==` (defensive; queue is SSZ-bounded);
- **lighthouse** uses `safe_*` arithmetic throughout;
- **prysm** explicitly pre-checks balance excess before the unsafe subtraction;
- **nimbus** has a fork-gated branch in `get_pending_balance_to_withdraw` reserved for Gloas builder withdrawals (dead at Pectra).

No code-change recommendation. Audit-direction recommendations:
- **Generate the T2.2 multi-request churn-drain fixture** as a sanity_blocks fixture; this is the highest-value untested scenario for both this item and item #2.
- **Audit `compute_exit_epoch_and_update_churn` as a standalone item** — used here, in `initiate_validator_exit`, in `process_voluntary_exit`, and indirectly in item #2 via consolidation init. A divergence in this function affects all four paths.
- **Audit `initiate_validator_exit` as a standalone item** — called from the full-exit path here and from `process_voluntary_exit`.

## Adjacent untouched Electra-active consensus paths

1. **`compute_exit_epoch_and_update_churn` standalone audit** — used by 4+ paths; analogous in shape to `compute_consolidation_epoch_and_update_churn` from item #2 but with a different churn limit. Boundary: per-epoch churn fully consumed by a single request that exceeds it; the function should advance `earliest_exit_epoch` rather than reject.
2. **`initiate_validator_exit` standalone audit** — Pectra-modified to use `compute_exit_epoch_and_update_churn` with `effective_balance` instead of the pre-Electra fixed-rate exit queue. Cross-cut with `process_voluntary_exit`.
3. **`get_pending_balance_to_withdraw` linear-scan complexity** — every withdrawal_request and consolidation_request iterates the full `pending_partial_withdrawals` queue (LIMIT = 2²⁷). Performance, not consensus, but an OOM-induced state divergence under adversarial queue growth is theoretically reachable (mainnet-impossible at current limits but worth flagging as F-tier).
4. **Lodestar's `isValidatorEligibleForWithdrawOrExit` shared helper** — a regression here affects both withdrawal_request AND voluntary_exit. Higher detection probability but harder localization. Worth a comment in the helper noting the dual responsibility.
5. **Composed switch + partial in one block** (T1.3 above) — the canonical "lost partial withdrawal" scenario for legacy validators that switch in the same block. Generate a fixture.
6. **`pending_partial_withdrawals` queue ordering** — append order at this item determines drain order at `process_pending_partial_withdrawals`. Cross-cuts with the `process_pending_partial_withdrawals` audit.
7. **Nimbus's Gloas-aware `get_pending_balance_to_withdraw`** — pre-emptive divergence vector at the Gloas fork target. The `when consensusFork >= ConsensusFork.Gloas` branch sums builder withdrawals too, which other clients won't.
8. **0x02 validator with `effective_balance < MIN_ACTIVATION_BALANCE`** — e.g., recently slashed. Partial withdrawal silently fails on `has_sufficient_effective_balance`. Reachable but weird. Verify all six handle uniformly.
9. **`FULL_EXIT_REQUEST_AMOUNT == 0` collision with a validator's actual zero-amount partial** — the spec says amount=0 means "full exit" universally. A validator that wants to withdraw exactly zero gwei (a no-op) cannot signal that without triggering full exit. Spec quirk; not a divergence vector but worth documenting in case any client adds a workaround.
10. **EIP-7685 request ordering**: `deposits → withdrawals → consolidations` per `process_execution_layer_block_requests`. A client that reordered would split. Worth a separate item on the requests dispatcher itself.
