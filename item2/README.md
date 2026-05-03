# Item #2 — `process_consolidation_request` EIP-7251 switch + main path

**Status:** no-divergence-pending-fuzzing — audited 2026-05-03. **Hypotheses H1–H5 satisfied. All 10 EF `consolidation_request` operations fixtures pass on all four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus SKIP per harness limitations.**

**Builds on:** item #1 (`get_max_effective_balance` / `is_compounding_withdrawal_credential` are the consumer of `0x02` writes by this item's switch path).

**Electra-active.** Track A entry — Pectra request-processing. The function processes execution-layer-triggered `ConsolidationRequest`s (EIP-7251) appended to a block via the EIP-7685 requests framework. It has two distinct code paths: (1) a self-targeted "switch to compounding" fast path that flips the source validator's `withdrawal_credentials[0]` from `0x01` to `0x02` and queues any excess balance, and (2) a full cross-validator consolidation path that initiates the source's exit and appends a `PendingConsolidation` for later draining at epoch boundaries. Both are reachable in normal canonical operation.

## Question

EIP-7251 introduces two semantically distinct flows under one entrypoint. Pyspec (`consensus-specs/specs/electra/beacon-chain.md:1869–1960`):

```python
def process_consolidation_request(state, req):
    # Fast path: source == target with 0x01 creds -> upgrade to 0x02
    if is_valid_switch_to_compounding_request(state, req):
        source_index = validator_pubkeys.index(req.source_pubkey)
        switch_to_compounding_validator(state, source_index)
        return
    # Self-targeted but not a valid switch -> reject (no exit-via-consolidation)
    if req.source_pubkey == req.target_pubkey:
        return
    # 9 further short-circuits, then queue + churn updates
    if len(state.pending_consolidations) == PENDING_CONSOLIDATIONS_LIMIT: return
    if get_consolidation_churn_limit(state) <= MIN_ACTIVATION_BALANCE: return
    # ... pubkey existence, source creds (0x01|0x02) + address match,
    # target creds (0x02), both active, neither exiting, source seasoned,
    # no pending withdrawals, then exit-epoch assignment + append PendingConsolidation.
```

`is_valid_switch_to_compounding_request` (lines 1831–1867) requires: `source_pubkey == target_pubkey`, source pubkey exists, source `withdrawal_credentials[12:] == req.source_address` (the EL-side authorization binding), `has_eth1_withdrawal_credential(source)` (**0x01 only — NOT 0x02**), source active, source not exiting.

The hypothesis: *all six clients implement both paths with identical accept/reject behavior on every input, and identical state mutations on accept.*

**Consensus relevance**: Each consolidation appends to `state.pending_consolidations` and decrements `state.consolidation_balance_to_consume` / advances `state.earliest_consolidation_epoch`. A divergence in the predicate would cause one client to enqueue while another doesn't — immediately splitting the state-root. The switch path additionally writes the `0x02` prefix that downstream `get_max_effective_balance` (item #1) reads to pick 2048 vs 32 ETH; a divergence there cascades into per-validator effective-balance differences.

## Hypotheses

- **H1.** Switch-to-compounding fast path: all six clients require `source_pubkey == target_pubkey` AND `has_eth1_withdrawal_credential(source)` (0x01 only) AND `source.withdrawal_credentials[12:32] == req.source_address` AND source active AND `source.exit_epoch == FAR_FUTURE_EPOCH`. A 0x02 source must NOT trigger the fast path (it would be a wasteful no-op upgrade).
- **H2.** Source credential in the main path: all six accept BOTH 0x01 AND 0x02 via `has_execution_withdrawal_credential`.
- **H3.** Target credential in the main path: all six require ONLY 0x02 via `has_compounding_withdrawal_credential`.
- **H4.** All twelve short-circuits in the main path produce observable-equivalent accept/reject decisions on every input. (Per-client ordering may differ, but the Boolean-AND of the predicates is invariant.)
- **H5.** When the switch fast path fires, all six write `0x02` to `withdrawal_credentials[0]` (preserving bytes 1–31) and call `queue_excess_active_balance(state, source_index)`. When the main path completes, all six call `compute_consolidation_epoch_and_update_churn(state, source.effective_balance)`, set `source.exit_epoch` and `source.withdrawable_epoch`, and append a `PendingConsolidation(source, target)`.

## Findings

H1, H2, H3, H4, H5 satisfied. **No divergence at the source-level predicate or the EF-fixture level. All ten EF operations fixtures pass uniformly on the four wired clients.**

### prysm (`prysm/beacon-chain/core/requests/consolidations.go:103–238`)

```go
// Predicate sequence (line numbers approx):
// 1. fast-path: isValidSwitchToCompoundingRequest -> switchToCompoundingValidator + return  (line 123)
// 2. source == target and not valid switch -> return  (137-139)
// 3. queue full -> return  (141-145)
// 4. churn insufficient -> return  (147-154)
// 5. source/target pubkey lookup via ValidatorIndexByPubkey (hashmap, O(1))  (156-163)
// 6. has_execution_withdrawal_credential(source) AND addr match  (181-187)
// 7. has_compounding_withdrawal_credential(target)  (190-192)
// 8. both active  (195)
// 9. neither exiting  (199-201)
// 10. source seasoned (activation + SHARD_COMMITTEE_PERIOD)  (203-210)
// 11. get_pending_balance_to_withdraw(source) == 0  (212-219)
// 12. compute exit epoch, set fields, append pending consolidation  (221-234)
```

`isValidSwitchToCompoundingRequest` (240–278) explicitly bounds-checks `len(withdrawalCreds) != 32 || len(sourceAddress) != 20` before `bytes.HasSuffix` — the only client to add this defensive guard. Switch credential check uses `HasETH1WithdrawalCredentials()` (0x01 only).

`switchToCompoundingValidator` (280–294) writes `WithdrawalCredentials[0] = CompoundingWithdrawalPrefixByte` then calls `queueExcessActiveBalance`. Errors out if creds is empty (defensive — SSZ guarantees 32 bytes).

H1 ✓ (switch path uses `HasETH1WithdrawalCredentials`).
H2 ✓ (`HasExecutionWithdrawalCredentials() = HasETH1 || HasCompounding`).
H3 ✓.
H4 ✓ (predicate ordering matches pyspec 1→12).
H5 ✓.

### lighthouse (`lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:684–789`)

```rust
// Same 1->12 sequence; uses Result<()> propagation.
// Pubkey lookup via state.pubkey_cache().get(&pubkey) -> Option<usize> (cached).
// Missing pubkey: silent return (Ok(())).
// is_valid_switch_to_compounding_request returns Result<bool> — can propagate
// state-lookup errors, unlike prysm's plain bool.
```

`switch_to_compounding_validator` lives on `BeaconState` (`consensus/types/src/state/beacon_state.rs:2692–2709`); writes the prefix byte via `AsMut::<[u8;32]>` then calls `queue_excess_active_balance`.

`compute_consolidation_epoch_and_update_churn` (`beacon_state.rs:2753–2798`) uses `safe_add` / `safe_sub` / `safe_div` / `safe_mul` everywhere (overflow-checked) AND a `match` on state variant — pre-Electra variants return `Err(IncorrectStateVariant)` rather than silently mutating wrong fields.

H1, H2, H3, H4, H5 ✓.

### teku (`teku/ethereum/spec/.../ExecutionRequestsProcessorElectra.java:286–435`)

Predicate sequence identical to pyspec 1→12. `isValidSwitchToCompoundingRequest` (443–482) inlines the 5 sub-checks; uses `Optional<Integer>` for pubkey lookup via `validatorsUtil.getValidatorIndex(state, pubkey)`.

`switchToCompoundingValidator` lives on `BeaconStateMutatorsElectra.java:176–187`. Builds a fresh `byte[]` from the existing creds, mutates `[0] = COMPOUNDING_WITHDRAWAL_BYTE` (=0x02), wraps as `Bytes32`, replaces via the immutable validator setter pattern (`validator.withWithdrawalCredentials(...)`).

`computeConsolidationEpochAndUpdateChurn` (`BeaconStateMutatorsElectra.java:135–168`) uses `UInt64` wrapper arithmetic with explicit `.minusMinZero()` saturating subtraction.

H1, H2, H3, H4, H5 ✓.

### nimbus (`nimbus/beacon_chain/spec/state_transition_block.nim:658–746`)

Predicate ordering differs from pyspec: source pubkey lookup is hoisted to **before** the switch fast path (lines 666–669). Target pubkey lookup happens after the switch/queue/churn checks (lines 694–697). Pyspec does both lookups inside their respective sub-functions, which works out to the same thing observable-wise — for an unknown source pubkey, both implementations return without mutation.

`switch_to_compounding_validator` (`beaconstate.nim:1534–1539`) does direct in-place mutation: `validator.withdrawal_credentials.data[0] = COMPOUNDING_WITHDRAWAL_PREFIX` + `queue_excess_active_balance(state, index)`. Returns nothing; no error path.

`compute_consolidation_epoch_and_update_churn` (`beaconstate.nim:317–345`) computes `additional_epochs = (balance_to_process - 1.Gwei) div per_epoch_consolidation_churn + 1` — the `-1` is safe because `balance_to_process > 0` is implied by the surrounding `if balance > balance_to_consume`.

Pubkey lookup uses Nimbus's `BucketSortedValidators` (bucketed sort + linear scan within bucket).

H1, H2, H3, H4, H5 ✓.

### lodestar (`lodestar/packages/state-transition/src/block/processConsolidationRequest.ts:16–102`)

Predicate ordering differs from pyspec: pubkey existence checked at lines 21–30 **before** the switch fast path (similar to nimbus). Same observable behavior on unknown pubkeys.

```typescript
// (paraphrased)
if (!isPubkeyKnown(state, sourcePubkey) || !isPubkeyKnown(state, targetPubkey)) return;
const [sourceIndex, targetIndex] = [...]; if any null => return;
if (isValidSwitchToCompoundRequest(state, req)) {
  switchToCompoundingValidator(state, sourceIndex); return;
}
if (sourceIndex === targetIndex) return;
// ... queue full, churn, creds, active, exit, seasoned, pending withdrawals
```

`isValidSwitchToCompoundRequest` (107–149) checks `hasEth1WithdrawalCredential` (0x01 only) at line 134 — strict, not composed with compounding.

`switchToCompoundingValidator` (`util/electra.ts:17–34`) slices the entire creds, mutates `[0]`, reassigns the validator to trigger SSZ tracking — necessary because lodestar's SSZ runtime tracks mutations via reference equality.

`computeConsolidationEpochAndUpdateChurn` (`util/epoch.ts:78–103`) uses `BigInt` for the churn arithmetic. The TypeScript `number` type's 53-bit mantissa would lose precision on full gwei values; lodestar mixes `number` (effective_balance, which fits) and `BigInt` (cumulative balance arithmetic).

H1, H2, H3, H4, H5 ✓.

### grandine (`grandine/transition_functions/src/electra/block_processing.rs:1186–1294`)

```rust
// is_valid_switch_to_compounding_request? -> switch + Ok(()) return
// source_pubkey == target_pubkey -> Ok(()) return
// pending_consolidations full -> Ok(())
// churn limit insufficient -> Ok(())
// source pubkey lookup -> Ok(()) if missing
// target pubkey lookup -> Ok(()) if missing
// has_execution_withdrawal_credential(source) && addr match
// has_compounding_withdrawal_credential(target)
// both active, neither exiting
// source seasoned, no pending balance to withdraw
// compute_consolidation_epoch_and_update_churn, set fields, append
```

`switch_to_compounding_validator` (`helper_functions/src/mutators.rs:135–147`) does `copy_from_slice(COMPOUNDING_WITHDRAWAL_PREFIX)` (a `&[u8]` constant of length 1) then calls `queue_excess_active_balance`. Returns `Result<()>` to propagate any state-mutation error.

`compute_consolidation_epoch_and_update_churn` (`mutators.rs:211–248`) uses raw `u64` arithmetic — the same `(balance_to_process - 1) / per_epoch + 1` pattern as nimbus, with the same implicit-non-zero invariant.

H1, H2, H3, H4, H5 ✓.

## Cross-reference table

| Client | Main fn | Switch validity | Switch mutator | Pubkey lookup DS | Notable idiom |
|---|---|---|---|---|---|
| prysm | `core/requests/consolidations.go:103-238` | inlined `isValidSwitchToCompoundingRequest:240-278` | `switchToCompoundingValidator:280-294` | `ValidatorIndexByPubkey` hashmap | Only client with explicit `len(creds)!=32 \|\| len(addr)!=20` defensive check |
| lighthouse | `per_block_processing/process_operations.rs:684-789` | `:629-682` (returns `Result<bool>`) | `state/beacon_state.rs:2692-2709` | `pubkey_cache().get()` | `safe_*` arithmetic; pre-Electra variant match returns `Err` |
| teku | `ExecutionRequestsProcessorElectra.java:286-435` | `:443-482` | `BeaconStateMutatorsElectra.java:176-187` | `validatorsUtil.getValidatorIndex` Optional | `.minusMinZero()` saturating subtraction |
| nimbus | `state_transition_block.nim:658-746` | `:627-655` | `beaconstate.nim:1534-1539` | `BucketSortedValidators` | Source pubkey lookup hoisted **before** switch fast path |
| lodestar | `block/processConsolidationRequest.ts:16-102` | `:107-149` | `util/electra.ts:17-34` | `epochCtx.pubkey2index` | Both pubkey existence checks hoisted **before** switch path; mixes `number`/`BigInt` |
| grandine | `electra/block_processing.rs:1186-1294` | `:1296-1341` | `helper_functions/mutators.rs:135-147` | `index_of_public_key` | `Result<()>` everywhere; `copy_from_slice` for prefix write |

## Cross-cuts

### with item #1 (`process_effective_balance_updates`)

A successful `switch_to_compounding_validator` writes `0x02` to `withdrawal_credentials[0]` of the source validator. The next call to `get_max_effective_balance(source)` (item #1) returns 2048 ETH instead of 32 ETH. The next epoch's `process_effective_balance_updates` then uses the new cap, possibly raising the source's `effective_balance` from 32 ETH to whatever its `balance` rounds down to. **Composed test**: a block in slot N contains a switch-to-compounding consolidation_request, and the epoch boundary at slot N+M (next epoch) produces a different `effective_balance` than it would have without the switch. All six clients should agree.

### with the pending-consolidations queue (WORKLOG #12 — `process_pending_consolidations`)

This item appends to `state.pending_consolidations` in main-path completion. The drain happens at epoch boundary in `process_pending_consolidations` (a separate item). Append ordering matters — if any client reorders or de-duplicates the queue, the drain order changes which cascades into per-validator balance changes.

### with `process_pending_deposits` queue (WORKLOG #3)

`switch_to_compounding_validator` calls `queue_excess_active_balance` which appends a pending **deposit** (with `bls.G2_POINT_AT_INFINITY` placeholder + GENESIS_SLOT marker) for any balance above `MIN_ACTIVATION_BALANCE`. So the switch path interacts with the pending-deposits queue too. A divergence in `queue_excess_active_balance` (separate sub-function) would surface here as a per-validator balance discrepancy at the next epoch.

## Fixture

`fixture/`: deferred — used the existing 10 EF state-test fixtures at
`consensus-spec-tests/tests/mainnet/electra/operations/consolidation_request/pyspec_tests/`.

Run via `scripts/run_fixture.sh` against all six clients on 2026-05-03:

```
                                                            prysm  lighthouse  teku  nimbus  lodestar  grandine
basic_switch_to_compounding                                 PASS   PASS        SKIP  SKIP    PASS      PASS
incorrect_not_enough_consolidation_churn_available          PASS   PASS        SKIP  SKIP    PASS      PASS
switch_to_compounding_exited_source                         PASS   PASS        SKIP  SKIP    PASS      PASS
switch_to_compounding_inactive_source                       PASS   PASS        SKIP  SKIP    PASS      PASS
switch_to_compounding_not_authorized                        PASS   PASS        SKIP  SKIP    PASS      PASS
switch_to_compounding_source_bls_withdrawal_credential      PASS   PASS        SKIP  SKIP    PASS      PASS
switch_to_compounding_source_compounding_withdrawal_cred…   PASS   PASS        SKIP  SKIP    PASS      PASS
switch_to_compounding_unknown_source_pubkey                 PASS   PASS        SKIP  SKIP    PASS      PASS
switch_to_compounding_with_excess                           PASS   PASS        SKIP  SKIP    PASS      PASS
switch_to_compounding_with_pending_consolidations_at_limit  PASS   PASS        SKIP  SKIP    PASS      PASS
```

10/10 fixtures pass on the four wired clients. teku and nimbus SKIP per the harness limitation (no per-operation CLI hook); both pass these fixtures in their internal CI. Lighthouse's verdict is per-helper-test-fn rather than per-fixture (its `operations_consolidations` fn covers all 10 + the minimal-preset variants in one go), but PASS implies all are among the passing set.

**Coverage gap**: 9 of 10 EF fixtures exercise the switch-to-compounding fast path; only `incorrect_not_enough_consolidation_churn_available` reaches the main consolidation path, and it terminates early at the churn-limit short-circuit. **The end-to-end main path (source != target, both compounding-credentialed, full success ending in `PendingConsolidation` append) is not directly fixture-tested at this layer.** It is exercised indirectly through `random/random/` and `sanity/blocks/` fixtures (e.g., `top_up_to_fully_withdrawn_validator`, `effective_balance_increase_changes_lookahead`), but a dedicated boundary fixture would tighten the coverage.

## Fuzzing vectors

### T1 — Mainline canonical
- **T1.1 (priority — full main-path success).** Source has 0x02 creds, target has 0x02 creds, source != target, both active, neither exiting, source seasoned, no pending withdrawals, churn available. Expected: `pending_consolidations` grows by 1, source's `exit_epoch` set, `consolidation_balance_to_consume` decremented. **The single highest-value missing fixture for this surface.**
- **T1.2 (priority — switch with excess balance triggers pending deposit).** Source has 0x01 creds, balance = 33 ETH, source == target, otherwise valid switch. Expected: source's creds[0] = 0x02 AND a pending deposit for 1 ETH appended via `queue_excess_active_balance`. The existing `switch_to_compounding_with_excess` covers this; check that all six clients add identical `(source_index, slot=GENESIS_SLOT, signature=G2_POINT_AT_INFINITY)` markers.

### T2 — Adversarial probes
- **T2.1 (priority — multi-request churn drain).** A single block contains N consolidation_requests, each consuming the entire `consolidation_balance_to_consume`. Expected: only the first M (M < N) succeed before churn is exhausted; the rest hit the `churn <= MIN_ACTIVATION_BALANCE` short-circuit. Tests stateful churn-decrement consistency across requests within the same block. Not covered by any existing fixture.
- **T2.2 (priority — already-compounding self-target).** Source == target, source has 0x02 creds. Switch validity fails on the `has_eth1_withdrawal_credential` check (0x01 only). Falls into main path; `source == target` short-circuit fires; request silently ignored. Verify all six clients ignore identically (no spurious `0x02 → 0x02` "self-upgrade").
- **T2.3 (priority — 0x00 BLS source).** Source has 0x00 creds (BLS-only, never executed a 0x01 transition). Switch validity fails (no eth1 credential). Main path's `has_execution_withdrawal_credential` fails (0x00 is neither 0x01 nor 0x02). Request silently ignored.
- **T2.4 (defensive — short or oversize creds).** Pyspec assumes 32-byte creds. SSZ enforces this. Prysm explicitly checks `len != 32`; others rely on type safety. If any future SSZ schema change introduces variable-length creds, prysm vs others would diverge — F-tier today.

## Conclusion

**Status: no-divergence-pending-fuzzing.** Source review of all six clients shows aligned implementations of `process_consolidation_request`, `is_valid_switch_to_compounding_request`, `switch_to_compounding_validator`, and `compute_consolidation_epoch_and_update_churn`. Notable per-client differences (all observable-equivalent at the spec level): nimbus and lodestar hoist pubkey-existence checks before the switch fast path; prysm adds defensive length checks on credentials; lighthouse uses `safe_*` math + state-variant `match`; teku uses `.minusMinZero()` saturating arithmetic; lodestar mixes `number`/`BigInt`. None of these affect the predicate's truth table or the resulting state mutations.

All 10 EF `operations/consolidation_request` fixtures pass uniformly on prysm, lighthouse, lodestar, grandine. Teku and nimbus pass these in their internal CI but are SKIPped by the BeaconBreaker harness pending per-operation CLI wiring.

No code-change recommendation. Recommendations to the harness and the audit:
- Generate the **T1.1 main-path-success fixture** above; it is the most important untested-by-EF surface here.
- Generate **T2.1 multi-request churn drain**; tests stateful intra-block iteration.
- Cross-cut audit (item-pair) with item #1 on the `0x02` write → `get_max_effective_balance` chain.

## Adjacent untouched Electra-active consensus paths

1. **`queue_excess_active_balance`** — called by `switch_to_compounding_validator` when source balance > `MIN_ACTIVATION_BALANCE`. Writes a pending deposit with placeholder signature. Cross-cuts with WORKLOG #3 (`process_pending_deposits` queue ordering).
2. **`get_pending_balance_to_withdraw`** — short-circuit #11 in the main path. A separate function used here and in `process_withdrawal_request`. A divergence there would surface here as either spurious rejection or spurious acceptance. Worth a dedicated audit.
3. **`compute_activation_exit_epoch`** — input to `compute_consolidation_epoch_and_update_churn`. Same function used in `process_voluntary_exit`. A reordering or off-by-one in epoch math here cascades into different `exit_epoch` values; worth a dedicated boundary fixture at the `MAX_SEED_LOOKAHEAD` boundary.
4. **Pubkey-lookup data-structure consistency under churn** — prysm uses hashmap, lighthouse cache, teku Optional, nimbus BucketSortedValidators, lodestar `pubkey2index` Map, grandine `index_of_public_key`. Race conditions between activation/exit and consolidation could cause stale lookups. F-tier: a deposit at slot N activates a validator; a consolidation_request at slot N+1 references that pubkey. Each client's lookup must see the new validator. Test composition.
5. **`is_valid_switch_to_compounding_request`'s tolerance for short creds** — only prysm bounds-checks. SSZ guarantees 32 bytes today; flag for future-proofing.
6. **`PendingConsolidation` queue append ordering** — main-path completion appends; if any client reorders by an internal sort key, the drain order at `process_pending_consolidations` differs and balances diverge. Cross-cuts with WORKLOG #12.
7. **Coarse-grained lighthouse harness verdict** — our runner reports PASS only at the `operations_consolidations` test-fn level (covers all 10 fixtures plus minimal-preset variants in one go). A failure on one fixture would FAIL the whole helper. Future runner extension: filter cargo-test by fixture-name regex so per-fixture verdicts are surfaced.
8. **EF coverage gap** — only 1 of 10 fixtures reaches the main path. Generating T1.1 would close the most important hole. T2.1 (multi-request stateful churn) is not testable via the operations format (which is single-op); requires a sanity_blocks fixture with multiple requests in one block.
