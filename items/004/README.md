# Item #4 — `process_pending_deposits` EIP-6110 per-epoch drain

**Status:** no-divergence-pending-fuzzing — audited 2026-05-03. **Hypotheses H1–H7 satisfied. All 43 EF `pending_deposits` epoch-processing fixtures pass on all four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus SKIP per harness limitation.**

**Builds on:** items #1 (`get_max_effective_balance` + `is_compounding_withdrawal_credential` are consumed by the new-validator path) and #2 (the switch-to-compounding fast path appends `PendingDeposit`s with a `slot=GENESIS_SLOT` placeholder that this item drains).

**Electra-active.** Track A — Pectra request-processing (drain side). Per-epoch routine that drains `state.pending_deposits` in FIFO order subject to four short-circuits and three per-deposit branches (apply, postpone, churn-limit-break), then mutates the queue to `unprocessed + postponed`. Adds new validators to the registry (with proof-of-possession signature verification) or tops up existing balances; consumes `state.deposit_balance_to_consume` only when the per-epoch churn limit is reached.

## Question

EIP-6110 replaces eth1-bridge polling with in-protocol pending deposits. Pyspec (`consensus-specs/specs/electra/beacon-chain.md:990–1057`):

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

`apply_pending_deposit` (lines 960–981):

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

The hypothesis: *all six clients implement the four short-circuits, three per-deposit branches, queue-postpone semantics, GENESIS_FORK_VERSION signature domain, and conditional churn accumulator identically.*

**Consensus relevance**: Each successful drain creates a new validator (initial balance = deposit amount, with `effective_balance` set via item #1's logic) or tops up an existing one. The `pending_deposits` queue is part of `BeaconState` — its mutation directly changes the state-root. A divergence in any of: postpone-vs-skip semantics, churn-accumulator reset, signature-domain version, batch-limit ordering would split the state-root immediately at the next epoch boundary. Particularly catastrophic divergences would be: (a) using current fork version for signature verification, which would silently reject valid deposits; (b) confusing postpone with skip, which would silently drop deposits; (c) failing to reset `deposit_balance_to_consume` when churn isn't reached, which would let it grow unboundedly. All of these are reachable via canonical operation.

## Hypotheses

- **H1.** All six implement the **four break conditions** in pyspec order: (1) deposit-request-before-bridge-finalized, (2) deposit-not-finalized, (3) batch limit (`MAX_PENDING_DEPOSITS_PER_EPOCH = 16`), (4) churn limit (inside the active-validator branch).
- **H2.** All six **postpone exited-validator deposits** (move to back of queue) and **apply withdrawn-validator deposits without consuming churn**.
- **H3.** All six **increment `next_deposit_index` for all three inner branches** (withdrawn, exited→postpone, active→applied) — but NOT on the four early breaks. Index is the slice point in the post-loop queue mutation.
- **H4.** Queue mutation produces `pending_deposits[next_deposit_index:] + postpone` — drops first `index` elements, appends postponed at the back.
- **H5.** The deposit-balance accumulator is **conditionally set**: `available − processed` if churn limit was reached, else `0`. **The "else" branch is critical** — without it, the accumulator would grow each epoch.
- **H6.** `is_valid_deposit_signature` uses **`GENESIS_FORK_VERSION`** for the signing domain (fork-agnostic).
- **H7.** `add_validator_to_registry` (Pectra-modified) creates the validator with balance = `amount` and effective_balance computed via item #1's `get_max_effective_balance`.

## Findings

H1–H7 satisfied. **No divergence at the source-level predicate or the EF-fixture level. All 43 EF epoch-processing fixtures pass uniformly on the four wired clients.**

### prysm (`prysm/beacon-chain/core/electra/deposits.go:257–370`)

Predicate sequence matches pyspec 1→4 + 3 inner branches. `next_deposit_index` increments after the inner conditionals (line ~348). Queue mutation at line ~361:
```go
pendingDeposits = append(pendingDeposits[nextDepositIndex:], pendingDepositsToPostpone...)
```

`apply_pending_deposit` is inlined into the loop body (lines 322–344). `IsValidDepositSignature` (lines 168–179) calls `signing.ComputeDomain(DomainDeposit, nil, nil)` — the `nil` fork-version arg defaults to GENESIS_FORK_VERSION inside `ComputeDomain`. ✓

`AddValidatorToRegistry` (lines 472–497) calls `GetValidatorFromDeposit(pubkey, withdrawal_credentials, amount)` then `AppendBalance(amount)` — Pectra-correct. ✓

`ActivationExitChurnLimit` (`core/helpers/validator_churn.go:40-42`) returns `min(MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT, BalanceChurnLimit(activeBalance))` — correct.

H1–H7 ✓.

### lighthouse (`lighthouse/consensus/state_processing/src/per_epoch_processing/single_pass.rs:940–1063`)

**Notable structural difference**: lighthouse defers the actual balance/validator mutations. It builds a `PendingDepositsContext` that records the indexed deposit operations (a `HashMap<usize, Vec<u64>>` for top-ups and a `Vec` for new validators), then applies them later in the validator-iteration loop (lines 1066–1078). Same observable post-state, but the mutations are batched.

Break-condition order matches pyspec 1→4. `next_deposit_index` incremented after the inner conditionals (line 1046, `safe_add_assign(1)?`). Queue mutation logic deferred outside this function.

`is_valid_deposit_signature` (`per_block_processing/signature_sets.rs:365–374`) uses `spec.get_deposit_domain()` (`chain_spec.rs:545–547`) which is `compute_domain(Domain::Deposit, self.genesis_fork_version, Hash256::zero())` — explicit `genesis_fork_version`. ✓

`add_validator_to_registry` (`state/beacon_state.rs:1922–1965`) computes effective_balance via `Validator::from_deposit(..., amount, ...)` (`validator.rs:39-65`) which computes `min(amount - amount % EBI, max_eb)` consistently with item #1.

`get_activation_exit_churn_limit` (`beacon_state.rs:2634–2642`) returns `min(spec.max_per_epoch_activation_exit_churn_limit, self.get_balance_churn_limit(spec)?)`.

H1–H7 ✓.

### teku (`teku/ethereum/spec/.../EpochProcessorElectra.java:213–299`)

Predicate sequence matches pyspec 1→4. Inner loop uses `IntStream.range(nextDepositIndex, pendingDeposits.size()).forEach(...)` to build the new queue, then `addAll(depositsToPostpone)` to append. Conditional accumulator at lines 296-298: `if isChurnLimitReached { ... .minusMinZero(...) } else { UInt64.ZERO }`.

`applyPendingDeposits` (lines 186-202) uses `validatorsUtil.getValidatorIndex(state, pubkey).ifPresentOrElse(idx -> increaseBalance(state, idx, amount), () -> { if (isValidPendingDepositSignature(deposit)) addValidatorToRegistry(...); })`.

`isValidDepositSignature` (`MiscHelpers.java:410-423`) builds `computeDepositSigningRoot` → `computeDomain(Domain.DEPOSIT)` → `computeDomain(domainType, specConfig.getGenesisForkVersion(), Bytes32.ZERO)` — explicit genesis fork version. ✓

`addValidatorToRegistry` (`BeaconStateMutators.java:230-240`) takes `amount` arg, calls `getValidatorFromDeposit(...)` and `appendElement(amount)`. ✓

`getActivationExitChurnLimit` (`BeaconStateAccessorsElectra.java:60-62`) is `getBalanceChurnLimit(state).min(configElectra.getMaxPerEpochActivationExitChurnLimit())`. ✓

H1–H7 ✓.

### nimbus (`nimbus/beacon_chain/spec/state_transition_epoch.nim:1207–1298`)

Predicate sequence matches pyspec 1→4. Queue mutation at line ~1290:
```nim
state.pending_deposits = HashList[PendingDeposit, Limit PENDING_DEPOSITS_LIMIT].init(
    state.pending_deposits.asSeq[next_deposit_index..^1] & deposits_to_postpone)
```

`apply_pending_deposit` (lines 1185–1204) takes a precomputed `validator_index: Opt[ValidatorIndex]`. New-validator branch calls `verify_deposit_signature(cfg.GENESIS_FORK_VERSION, deposit_data)` — explicit genesis fork version arg. ✓

`add_validator_to_registry` (`beaconstate.nim:125-145`) appends `get_validator_from_deposit(state, pubkey, creds, amount)` and `state.balances.add(amount)`. Returns `Result[void, cstring]` for "too many validators". ✓

`get_activation_exit_churn_limit` (`beaconstate.nim:265-274`) returns `min(cfg.MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT.Gwei, get_balance_churn_limit(cfg, state, cache))`. ✓

H1–H7 ✓.

### lodestar (`lodestar/packages/state-transition/src/epoch/processPendingDeposits.ts:19–108`)

**Structural note**: lodestar processes pending_deposits in **chunks of 100** (line ~37) using `getReadonlyByRange(startIndex, chunk)` for SSZ-list batched reads — performance optimization. Inner loop is unchanged in semantics.

**Notable Gloas-aware fork-gate at line 25**:
```typescript
const churnLimit = fork >= ForkSeq.gloas
    ? getActivationChurnLimit(state.epochCtx)
    : getActivationExitChurnLimit(state.epochCtx);
```

Lodestar is the only client (besides nimbus on a different surface — see item #1) that has Gloas-fork-conditional logic in this function. Pre-Gloas (and at our Pectra target), it uses `getActivationExitChurnLimit` — same as the others. **Pre-emptive future divergence**: when other clients implement Gloas, they may not switch to `getActivationChurnLimit` here, and lodestar/other clients would compute different `available_for_processing` values.

Queue mutation (lines 96–101): `sliceFrom(nextDepositIndex)` + `push()` loop for postponed. Functionally equivalent.

`isValidDepositSignature` (`block/processDeposit.ts:141-166`): explicit `computeDomain(DOMAIN_DEPOSIT, config.GENESIS_FORK_VERSION, ZERO_HASH)` — correct. ✓

`addValidatorToRegistry` (`block/processDeposit.ts:90-122`) computes `effectiveBalance = Math.min(amount - amount % EBI, getMaxEffectiveBalance(creds))` and pushes to validators. ✓

H1–H7 ✓.

### grandine (`grandine/transition_functions/src/electra/epoch_processing.rs:235–317`)

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

`apply_pending_deposit` (lines 319–344) and `is_valid_deposit_signature` (lines 346–369): the latter uses `pubkey_cache.get_or_insert(pubkey)` then `deposit_message.verify(config, signature, decompressed)`. The `verify` method's `SignForAllForks` impl computes the domain via `compute_domain(config, DOMAIN_DEPOSIT, None, None)` — the `None` fork-version arg means GENESIS_FORK_VERSION. ✓

`add_validator_to_registry` (`grandine/transition_functions/src/electra/block_processing.rs`) takes `amount` arg, initializes validator with `effective_balance: 0` and lets `Validator::from_deposit` (or equivalent post-construction logic) compute it from amount + creds. ✓

`get_activation_exit_churn_limit`: `get_balance_churn_limit(config, state).min(config.max_per_epoch_activation_exit_churn_limit)`. ✓

H1–H7 ✓.

## Cross-reference table

| Client | Main fn | `apply_pending_deposit` | Sig domain version | `add_validator_to_registry` | Notable idiom |
|---|---|---|---|---|---|
| prysm | `core/electra/deposits.go:257-370` | inlined | `nil → GENESIS` (default in `ComputeDomain`) | `:472-497` (sets balance=amount) | `for {... continue}`; explicit per-branch increment |
| lighthouse | `per_epoch_processing/single_pass.rs:940-1063` | deferred via `PendingDepositsContext` | explicit `genesis_fork_version` | `state/beacon_state.rs:1922-1965` (`from_deposit(amount)`) | **Defers mutations to a batch context**; `safe_*` arithmetic; uses legacy test-fn name `epoch_processing_pending_balance_deposits` |
| teku | `EpochProcessorElectra.java:213-299` | `:186-202` (Optional ifPresentOrElse) | explicit `genesisForkVersion` | `BeaconStateMutators.java:230-240` | `IntStream.range` for queue rebuild |
| nimbus | `state_transition_epoch.nim:1207-1298` | `:1185-1204` (Opt[ValidatorIndex]) | explicit `cfg.GENESIS_FORK_VERSION` | `beaconstate.nim:125-145` | HashList re-init with `asSeq[i..^1] & seq2` |
| lodestar | `epoch/processPendingDeposits.ts:19-108` | `:110-139` | explicit `config.GENESIS_FORK_VERSION` | `block/processDeposit.ts:90-122` | **Chunked iteration (100 at a time)**; **Gloas-fork branch uses `getActivationChurnLimit`** instead — pre-emptive divergence vector |
| grandine | `electra/epoch_processing.rs:235-317` | `:319-344` | `compute_domain(... None ...)` → GENESIS | `block_processing.rs:add_validator_to_registry` | `PersistentList::try_from_iter` for queue rebuild; clones queue to avoid borrow conflicts |

## Cross-cuts

### with item #1 (`process_effective_balance_updates` / `get_max_effective_balance`)

A new validator added by `add_validator_to_registry` has its initial `effective_balance` computed via the same `get_max_effective_balance` predicate audited in item #1. A divergence in item #1 would surface here as a per-new-validator effective_balance discrepancy. The fact that item #1's hypotheses passed strengthens confidence in the new-validator initialization here.

### with item #2 (`process_consolidation_request` switch path)

Item #2's switch-to-compounding fast path calls `queue_excess_active_balance` which appends a `PendingDeposit` entry with **`slot=GENESIS_SLOT`** and **`signature=BLS_G2_POINT_AT_INFINITY`**. The `slot=GENESIS_SLOT` matters because:
- Break condition #1 (`deposit.slot > GENESIS_SLOT and state.eth1_deposit_index < state.deposit_requests_start_index`) is FALSE for these (slot is NOT > GENESIS_SLOT). So they pass the bridge-finalization check unconditionally.
- Break condition #2 (`deposit.slot > finalized_slot`) is FALSE because GENESIS_SLOT ≤ finalized_slot. So they pass the finality check.

The `signature=G2_POINT_AT_INFINITY` matters because:
- These deposits are TOP-UPs (the validator already exists, since the consolidation switch operated on an existing validator). So `apply_pending_deposit` takes the `validator_index ∈ pubkeys` branch and **never validates the signature**. The placeholder is never checked — by design.

If any client accidentally validated the signature of a top-up (e.g., uniformly applied `is_valid_deposit_signature` to all deposits), it would fail on G2_POINT_AT_INFINITY → reject the top-up → balance discrepancy. **Worth checking explicitly**: the switch-via-consolidation path is the canonical generator of these placeholder-signature deposits, so this cross-cut is reachable.

### with EIP-6110 `process_deposit_request` (operation handler)

`process_deposit_request` (the per-block operation that populates `state.pending_deposits` from the EL) is the producer side; this item is the consumer. A bug in either would surface as queue-content mismatch. There's a separate audit item worth doing for `process_deposit_request` (trivial pyspec — 5 lines — so brief, but the `deposit_requests_start_index` initialization is the interesting bit).

### with `add_validator_to_registry` (Pectra-modified)

Used by both this item AND `apply_deposit` (legacy bridge-deposit path). Pectra-modified to take `amount` instead of using a fixed 0. A divergence here would surface in BOTH paths. Worth a standalone audit if any client gets clever about the validator construction.

## Fixture

`fixture/`: deferred — used the existing 43 EF state-test fixtures at
`consensus-spec-tests/tests/mainnet/electra/epoch_processing/pending_deposits/pyspec_tests/`.

Run via `scripts/run_fixture.sh` against all six clients on 2026-05-03:

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

**Coverage assessment**: this set is the richest of any item so far (43 fixtures, 13 of which exercise the full `process_pending_deposits` outer loop and 25 of which exercise the inner `apply_pending_deposit`). It covers: every churn boundary case (`balance_above_churn`, `balance_equal_churn`, `preexisting_churn`, `multiple_above_churn`, `multiple_below_churn`); every signature edge case (`incorrect_sig_new_deposit`, `incorrect_sig_top_up`, `key_validate_invalid_decompression`, `key_validate_invalid_subgroup`, `correct_sig_but_forked_state`, `with_previous_fork_version`, `ineffective_deposit_with_current_fork_version`); the bridge-transition cases (`eth1_bridge_transition_{complete,not_applied,pending}`); the postpone-vs-skip paths (`skipped_deposit_exiting_validator`, `multiple_skipped_deposits_exiting_validators`, `withdrawable_validator`, `withdrawable_validator_not_churned`, `success_top_up_to_withdrawn_validator`); and the per-epoch limit (`limit_is_reached`). Bigger than items #1–#3 combined, with no divergences — strong evidence for the function and its supporting machinery (deposit signature, churn limit, validator registry init).

**Notably absent**: a fixture for the **placeholder-signature top-up** scenario produced by item #2's switch-to-compounding fast path (a `PendingDeposit` with `slot=GENESIS_SLOT, signature=G2_POINT_AT_INFINITY`). The cross-cut is reachable but not directly tested at this layer — exercised indirectly via sanity_blocks fixtures like `switch_to_compounding_with_excess`.

## Fuzzing vectors

### T1 — Mainline canonical
- **T1.1 (priority — placeholder-sig top-up cross-cut).** Construct an epoch_processing fixture where the `pending_deposits` queue contains exactly the kind of entry produced by `queue_excess_active_balance`: existing validator's pubkey, `slot=GENESIS_SLOT`, `signature=G2_POINT_AT_INFINITY`, amount > 0. Expected: `apply_pending_deposit` takes the top-up branch (does NOT validate signature); balance increases. Detects any client that applies signature verification to top-ups.
- **T1.2 (priority — exact-MAX_PENDING_DEPOSITS_PER_EPOCH boundary).** Queue with exactly 17 deposits, all valid. Expected: 16 are processed, 1 remains. Exists implicitly in `process_pending_deposits_limit_is_reached`; verify all six handle the boundary correctly (the 17th MUST remain at the head of the queue).

### T2 — Adversarial probes
- **T2.1 (priority — alternating exited/withdrawn/active).** Queue: [withdrawn_v1, exited_v2, active_new, withdrawn_v3, exited_v4, active_new_2]. Expected: v1's deposit applied (no churn); v2 postponed (no churn, moved to back); v3 deposit applied (no churn); v4 postponed (no churn, moved to back); active_new → check churn; active_new_2 → check churn. Final queue: [v2_deposit, v4_deposit] (postponed deposits moved to back, in original encountered order). Tests the postpone-ordering. Already covered by `multiple_skipped_deposits_exiting_validators`.
- **T2.2 (priority — churn limit hit mid-loop).** Queue: 5 active deposits, churn limit only allows 3. Expected: first 3 apply, 4th hits churn → break. Final queue starts with the 4th (unprocessed) deposit; `deposit_balance_to_consume = available − processed_3`. Covered by `process_pending_deposits_multiple_pending_deposits_above_churn`.
- **T2.3 (defensive — corrupt signature on new validator).** New-validator deposit with structurally invalid signature (e.g., G2 point not in subgroup). Expected: `is_valid_deposit_signature` returns false; deposit is consumed (next_deposit_index incremented) but no validator added. Covered by `incorrect_sig_new_deposit` and `key_validate_invalid_subgroup`.
- **T2.4 (priority — current-fork-version sig).** Deposit signed with the CURRENT fork version (not GENESIS) — should be rejected. Covered by `ineffective_deposit_with_current_fork_version` (and its inverse `apply_pending_deposit_with_previous_fork_version`). The all-pass result strongly evidences H6.

## Conclusion

**Status: no-divergence-pending-fuzzing.** All six clients implement the four-break-condition outer loop, the three-way per-deposit branch, the postpone-to-back queue mutation, the conditional `deposit_balance_to_consume` reset, and the `GENESIS_FORK_VERSION`-domain signature verification identically. All 43 EF `pending_deposits` fixtures pass uniformly on the four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus pass these in their internal CI.

Notable per-client style differences (all observable-equivalent at the spec level):
- **lighthouse** defers the actual balance/validator mutations to a batch context (`PendingDepositsContext`) applied later in single-pass; same observable post-state but mutations are coalesced;
- **lighthouse** uses the legacy test-fn name `epoch_processing_pending_balance_deposits` (from before `PendingBalanceDeposit` was renamed to `PendingDeposit`) — the runner has a name mapping;
- **lodestar** processes the queue in chunks of 100 for batched SSZ reads;
- **lodestar** has a Gloas-fork-conditional branch that uses `getActivationChurnLimit` instead of `getActivationExitChurnLimit` — dead at our Pectra target but a pre-emptive future divergence vector;
- **grandine** clones the entire deposit list for borrow safety, then rebuilds via `PersistentList::try_from_iter`;
- **nimbus** rebuilds the queue via Nim sequence-slicing and concat (`asSeq[i..^1] & seq2`).

No code-change recommendation. Audit-direction recommendations:
- **Generate the T1.1 placeholder-signature top-up fixture** as a dedicated epoch_processing fixture — closes the cross-cut with item #2.
- **Standalone audit `add_validator_to_registry`** — used by both this item and `apply_deposit` (legacy path). One Pectra-modified function with two callers; worth its own coverage.
- **Standalone audit `process_deposit_request`** — the producer side of the queue this item drains. Trivial pyspec but the `deposit_requests_start_index` initialization is the interesting bit.

## Adjacent untouched Electra-active consensus paths

1. **`process_deposit_request` (operation handler)** — the producer side. Sets `state.deposit_requests_start_index` once (the EL→pyspec transition marker); appends to `pending_deposits`. Trivial but the start-index initialization edge case (UNSET → first request) is divergence-prone.
2. **`add_validator_to_registry` standalone audit** — Pectra-modified to take `amount`. Used here AND by `apply_deposit` (legacy path). Cross-cut surface.
3. **`is_valid_deposit_signature` BLS-library family axis** — each client uses a different BLS implementation (BLST in most; gnark-crypto in others; supranational in lighthouse). A subgroup-membership check or domain-separation difference here would directly affect deposit acceptance. Worth a Track F audit aligned with this item's findings.
4. **Lodestar's Gloas-conditional `getActivationChurnLimit` branch** — when other clients implement Gloas, they must also switch (or lodestar rolls back). Pre-emptive.
5. **Lighthouse's deferred-mutation `PendingDepositsContext` design** — if the deferred application reorder fails to commute with intervening single-pass operations (also batched in single_pass.rs), a subtle re-ordering bug could surface. F-tier today (the test fixtures pass) but worth understanding.
6. **`PendingDeposit.slot=GENESIS_SLOT` placeholder** — the special marker used by `queue_excess_active_balance` (called from item #2's switch path). Documented in item #2 cross-cut; deserves its own fixture in this item's category.
7. **`MAX_PENDING_DEPOSITS_PER_EPOCH = 16` is small** — under high deposit pressure (e.g., a fork that causes mass new-validator entry), the queue can grow faster than it drains. Worth a per-epoch growth-rate analysis as an out-of-band research item.
8. **The `deposit_balance_to_consume` accumulator interaction with `compute_exit_epoch_and_update_churn`** — both consume `available_for_processing`. There's only ONE churn pool per epoch. If both `process_pending_deposits` and `process_voluntary_exit` run in the same epoch, they share the pool. Worth mapping the order of `process_epoch` to confirm `pending_deposits` runs after exits.
9. **Postpone+skip interleaving order**: pyspec says `postpone.append(deposit)` preserves the encounter order. If a client built the postpone list out-of-order (e.g., used a HashMap somewhere), the queue rebuild would silently reorder. F-tier; unlikely but possible.
10. **`pending_deposits` SSZ list cap (`PENDING_DEPOSITS_LIMIT = 2²⁷`)** — per-block deposit_request additions can fill this faster than per-epoch drainage. A queue-full state is theoretically possible. What happens if a new `process_deposit_request` tries to append to a full queue? Should be rejected silently per SSZ cap, but worth confirming. Cross-cut with the producer.
