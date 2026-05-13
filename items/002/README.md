---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-12
builds_on: [1]
eips: [EIP-7251, EIP-8061]
splits: [prysm, lighthouse, teku, nimbus, grandine]
# main_md_summary: at Gloas activation, only lodestar implements the EIP-8061 quotient-based `get_consolidation_churn_limit`; the other five still use the Electra `balance_churn − activation_exit_churn` formula
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 2: `process_consolidation_request` EIP-7251 switch + main path

## Summary

EIP-7251 introduces two semantically distinct flows under one entrypoint: a self-targeted "switch to compounding" fast path that flips the source validator's `withdrawal_credentials[0]` from `0x01` to `0x02` and queues any excess balance, and a full cross-validator consolidation path that initiates the source's exit and appends a `PendingConsolidation` for later draining at epoch boundaries.

**Pectra surface (the function body itself):** all six clients implement both paths with identical predicate truth tables and identical state mutations. 10/10 EF `consolidation_request` operations fixtures pass on the four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus pass these in internal CI but the local harness SKIPs them per the per-operation-CLI gap.

**Gloas surface (new at the Glamsterdam target):** Gloas keeps the function body intact but (a) reschedules it from `process_operations` into the new `apply_parent_execution_payload` via EIP-7732 ePBS, and (b) modifies `get_consolidation_churn_limit` via EIP-8061 — the predicate at short-circuit #4 and the churn arithmetic in `compute_consolidation_epoch_and_update_churn` both depend on this. At the audit snapshot, **only lodestar implements the modified Gloas formula** (`total_active_balance / CONSOLIDATION_CHURN_LIMIT_QUOTIENT` rounded to EBI); the other five clients still use the Electra formula (`balance_churn − activation_exit_churn`). Spec-divergent in five clients; will materialise as a state-root split on the first Gloas-slot block that carries a consolidation request unless reconciled before activation.

## Question

EIP-7251 introduces two semantically distinct flows under one entrypoint. Pyspec (`vendor/consensus-specs/specs/electra/beacon-chain.md`, `process_consolidation_request`):

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

`is_valid_switch_to_compounding_request` requires: `source_pubkey == target_pubkey`, source pubkey exists, source `withdrawal_credentials[12:] == req.source_address` (the EL-side authorisation binding), `has_eth1_withdrawal_credential(source)` (**0x01 only — NOT 0x02**), source active, source not exiting.

**Glamsterdam target.** Gloas (EIP-7732 + EIP-8061) leaves the function body of `process_consolidation_request`, `is_valid_switch_to_compounding_request`, and `switch_to_compounding_validator` unchanged, but:

- Reschedules the consolidation pass out of `process_operations` into the new `apply_parent_execution_payload` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1130-1132`); operations are processed at the child's slot against the parent's payload requests.
- Modifies `get_consolidation_churn_limit` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:839-851`) to derive consolidation churn independently from total active balance via a new `CONSOLIDATION_CHURN_LIMIT_QUOTIENT`, rather than the Electra "balance churn minus activation/exit churn" composition. The function feeds short-circuit #4 (`churn <= MIN_ACTIVATION_BALANCE`) and the churn-consume loop in `compute_consolidation_epoch_and_update_churn`.

The hypothesis: *all six clients implement both Pectra paths with identical accept/reject behavior on every input and identical state mutations on accept (H1–H5), and at the Glamsterdam target all six also implement the Gloas-modified `get_consolidation_churn_limit` (H6).*

**Consensus relevance**: each consolidation appends to `state.pending_consolidations` and decrements `state.consolidation_balance_to_consume` / advances `state.earliest_consolidation_epoch`. A divergence in the predicate would cause one client to enqueue while another doesn't — immediately splitting the state-root. The switch path additionally writes the `0x02` prefix that downstream `get_max_effective_balance` (item #1) reads to pick 2048 vs 32 ETH; a divergence there cascades into per-validator effective-balance differences. A divergence in `get_consolidation_churn_limit` (H6) shifts both the short-circuit decision and the churn-consume arithmetic — different `earliest_consolidation_epoch` values across clients on the first Gloas-slot block carrying consolidation requests.

## Hypotheses

- **H1.** Switch-to-compounding fast path: all six clients require `source_pubkey == target_pubkey` AND `has_eth1_withdrawal_credential(source)` (0x01 only) AND `source.withdrawal_credentials[12:32] == req.source_address` AND source active AND `source.exit_epoch == FAR_FUTURE_EPOCH`. A 0x02 source must NOT trigger the fast path (it would be a wasteful no-op upgrade).
- **H2.** Source credential in the main path: all six accept BOTH 0x01 AND 0x02 via `has_execution_withdrawal_credential`.
- **H3.** Target credential in the main path: all six require ONLY 0x02 via `has_compounding_withdrawal_credential`.
- **H4.** All twelve short-circuits in the main path produce observable-equivalent accept/reject decisions on every input. (Per-client ordering may differ, but the Boolean-AND of the predicates is invariant.)
- **H5.** When the switch fast path fires, all six write `0x02` to `withdrawal_credentials[0]` (preserving bytes 1–31) and call `queue_excess_active_balance(state, source_index)`. When the main path completes, all six call `compute_consolidation_epoch_and_update_churn(state, source.effective_balance)`, set `source.exit_epoch` and `source.withdrawable_epoch`, and append a `PendingConsolidation(source, target)`.
- **H6** *(Glamsterdam target)*. At the Gloas fork gate, all six clients switch `get_consolidation_churn_limit` to the EIP-8061 formula: `churn = total_active_balance // CONSOLIDATION_CHURN_LIMIT_QUOTIENT; return churn - churn % EFFECTIVE_BALANCE_INCREMENT`. Pre-Gloas, all six retain the Electra formula.

## Findings

H1, H2, H3, H4, H5 satisfied for the Pectra surface. **H6 fails for 5 of 6 clients at the Glamsterdam target** — only lodestar fork-gates `get_consolidation_churn_limit` to the new EIP-8061 formula; prysm, lighthouse, teku, nimbus, and grandine continue to use the Electra formula even when the runtime spec version is Gloas. Source-level divergence; not yet covered by any EF fixture (no Gloas operations fixtures yet exist for this surface).

### prysm

`vendor/prysm/beacon-chain/core/requests/consolidations.go:103-238` — `ProcessConsolidationRequests` (note: now the renamed plural form; iterates over the request list and applies the per-request predicate sequence):

```go
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

`isValidSwitchToCompoundingRequest` at `vendor/prysm/beacon-chain/core/requests/consolidations.go:240-278` explicitly bounds-checks `len(withdrawalCreds) != 32 || len(sourceAddress) != 20` before `bytes.HasSuffix` — the only client with this defensive guard. Switch credential check uses `HasETH1WithdrawalCredentials()` (0x01 only).

`switchToCompoundingValidator` at `vendor/prysm/beacon-chain/core/requests/consolidations.go:280-294` writes `WithdrawalCredentials[0] = CompoundingWithdrawalPrefixByte` then calls `queueExcessActiveBalance`. Errors out if creds is empty (defensive — SSZ guarantees 32 bytes).

`ConsolidationChurnLimit` at `vendor/prysm/beacon-chain/core/helpers/validator_churn.go:44-54`:

```go
// def get_consolidation_churn_limit(state: BeaconState) -> Gwei:
//     return get_balance_churn_limit(state) - get_activation_exit_churn_limit(state)
func ConsolidationChurnLimit(activeBalance primitives.Gwei) primitives.Gwei {
    return BalanceChurnLimit(activeBalance) - ActivationExitChurnLimit(activeBalance)
}
```

H1 ✓ (`HasETH1WithdrawalCredentials`).
H2 ✓ (`HasExecutionWithdrawalCredentials() = HasETH1 || HasCompounding`).
H3 ✓.
H4 ✓ (predicate ordering matches pyspec 1→12).
H5 ✓.
**H6 ✗** — no fork gate on `ConsolidationChurnLimit`; the function returns the Electra formula irrespective of runtime fork. At Gloas, this is a spec divergence.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:684-789` — `process_consolidation_request<E>` (the per-request handler; outer iterator at `process_consolidation_requests` line 617). Same 1→12 sequence as pyspec; uses `Result<()>` propagation. Pubkey lookup via `state.pubkey_cache().get(&pubkey)` (cached). Missing pubkey: silent return (`Ok(())`). `is_valid_switch_to_compounding_request` at `vendor/lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:629-682` returns `Result<bool>` — can propagate state-lookup errors.

`switch_to_compounding_validator` lives on `BeaconState` (`vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2692-2709`); writes the prefix byte via `AsMut::<[u8;32]>` then calls `queue_excess_active_balance`.

`get_consolidation_churn_limit` at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2644-2648`:

```rust
pub fn get_consolidation_churn_limit(&self, spec: &ChainSpec) -> Result<u64, BeaconStateError> {
    self.get_balance_churn_limit(spec)?
        .safe_sub(self.get_activation_exit_churn_limit(spec)?)
        .map_err(Into::into)
}
```

No fork-gate; same Electra formula at Gloas.

`compute_consolidation_epoch_and_update_churn` at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2753-2798` uses `safe_add` / `safe_sub` / `safe_div` / `safe_mul` everywhere (overflow-checked) AND a `match` on state variant — pre-Electra variants return `Err(IncorrectStateVariant)` rather than silently mutating wrong fields.

H1, H2, H3, H4, H5 ✓. **H6 ✗** (Electra formula at Gloas).

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/execution/ExecutionRequestsProcessorElectra.java` — `processConsolidationRequest` and `isValidSwitchToCompoundingRequest`. (Note: teku moved this class from `electra/block/` to `electra/execution/` since the last audit.) Predicate sequence identical to pyspec 1→12; uses `Optional<Integer>` for pubkey lookup via `validatorsUtil.getValidatorIndex(state, pubkey)`.

`switchToCompoundingValidator` lives on `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/BeaconStateMutatorsElectra.java:176-187`. Builds a fresh `byte[]` from the existing creds, mutates `[0] = COMPOUNDING_WITHDRAWAL_BYTE` (=0x02), wraps as `Bytes32`, replaces via the immutable validator setter pattern (`validator.withWithdrawalCredentials(...)`).

`computeConsolidationEpochAndUpdateChurn` (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/BeaconStateMutatorsElectra.java:135-168`) uses `UInt64` wrapper arithmetic with explicit `.minusMinZero()` saturating subtraction.

`ExecutionRequestsProcessorGloas` at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/execution/ExecutionRequestsProcessorGloas.java` extends `ExecutionRequestsProcessorElectra` but overrides **only `processDepositRequest`** (to route `0x03` builder deposits to the builder list). The consolidation handler and `getConsolidationChurnLimit` are inherited unmodified — Electra formula applies at Gloas.

H1, H2, H3, H4, H5 ✓. **H6 ✗** (Gloas processor inherits Electra churn limit).

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:658-746` — `process_consolidation_request*`. Predicate ordering differs from pyspec: source pubkey lookup is hoisted to **before** the switch fast path (lines 666-669). Target pubkey lookup happens after the switch/queue/churn checks (lines 694-697). Pyspec does both lookups inside their respective sub-functions, which works out to the same thing observable-wise — for an unknown source pubkey, both implementations return without mutation.

`switch_to_compounding_validator` (`vendor/nimbus/beacon_chain/spec/beaconstate.nim:1534-1539`) does direct in-place mutation: `validator.withdrawal_credentials.data[0] = COMPOUNDING_WITHDRAWAL_PREFIX` + `queue_excess_active_balance(state, index)`. Returns nothing; no error path.

`get_consolidation_churn_limit*` at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:276-284`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.5.0-alpha.0/specs/electra/beacon-chain.md#new-get_consolidation_churn_limit
func get_consolidation_churn_limit*(
    cfg: RuntimeConfig,
    state: electra.BeaconState | fulu.BeaconState | gloas.BeaconState,
    cache: var StateCache):
    Gwei =
  get_balance_churn_limit(cfg, state, cache) -
    get_activation_exit_churn_limit(cfg, state, cache)
```

The function signature accepts a Gloas BeaconState but the body unconditionally uses the Electra formula. Source comment cites the Electra spec ref (`v1.5.0-alpha.0`); no Gloas-version comment present.

`compute_consolidation_epoch_and_update_churn` (`vendor/nimbus/beacon_chain/spec/beaconstate.nim:317-345`) computes `additional_epochs = (balance_to_process - 1.Gwei) div per_epoch_consolidation_churn + 1` — the `-1` is safe because `balance_to_process > 0` is implied by the surrounding `if balance > balance_to_consume`.

Pubkey lookup uses Nimbus's `BucketSortedValidators` (bucketed sort + linear scan within bucket).

H1, H2, H3, H4, H5 ✓. **H6 ✗** (Electra formula on Gloas state).

### lodestar

`vendor/lodestar/packages/state-transition/src/block/processConsolidationRequest.ts:16-102` — `processConsolidationRequest`. Predicate ordering differs from pyspec: pubkey existence checked at lines 21-30 **before** the switch fast path (similar to nimbus). Same observable behavior on unknown pubkeys.

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

`isValidSwitchToCompoundRequest` at `vendor/lodestar/packages/state-transition/src/block/processConsolidationRequest.ts:107-149` checks `hasEth1WithdrawalCredential` (0x01 only) at line 134.

`switchToCompoundingValidator` (`vendor/lodestar/packages/state-transition/src/util/electra.ts:17-34`) slices the entire creds, mutates `[0]`, reassigns the validator to trigger SSZ tracking — necessary because lodestar's SSZ runtime tracks mutations via reference equality.

`getConsolidationChurnLimit` at `vendor/lodestar/packages/state-transition/src/util/validator.ts:115-130` is the **only fork-gated implementation** across the six clients:

```typescript
/**
 * Spec (electra): get_consolidation_churn_limit (uses combined balance churn minus activation+exit churn)
 * Spec (gloas): get_consolidation_churn_limit (independent quotient, no MIN floor)
 */
export function getConsolidationChurnLimit(fork: ForkSeq, epochCtx: EpochCache): number {
  if (fork >= ForkSeq.gloas) {
    return getBalanceChurnLimit(
      epochCtx.totalActiveBalanceIncrements,
      epochCtx.config.CONSOLIDATION_CHURN_LIMIT_QUOTIENT,
      0  // no MIN floor
    );
  }
  return getBalanceChurnLimitFromCache(epochCtx) - getActivationExitChurnLimit(epochCtx);
}
```

`CONSOLIDATION_CHURN_LIMIT_QUOTIENT = 65536` per `vendor/lodestar/packages/config/src/chainConfig/configs/mainnet.ts:176`. The fork branch is reached from `processConsolidationRequest:50` (short-circuit #4) and `computeConsolidationEpochAndUpdateChurn` (`vendor/lodestar/packages/state-transition/src/util/epoch.ts:87`).

H1, H2, H3, H4, H5 ✓. **H6 ✓** — the only client matching Gloas spec.

### grandine

`vendor/grandine/transition_functions/src/electra/block_processing.rs:1186-1294` — `process_consolidation_request<P>`:

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

`is_valid_switch_to_compounding_request` at `vendor/grandine/transition_functions/src/electra/block_processing.rs:1296-1341`.

`switch_to_compounding_validator` (`vendor/grandine/helper_functions/src/mutators.rs:135-147`) does `copy_from_slice(COMPOUNDING_WITHDRAWAL_PREFIX)` (a `&[u8]` constant of length 1) then calls `queue_excess_active_balance`. Returns `Result<()>` to propagate any state-mutation error.

`get_consolidation_churn_limit` at `vendor/grandine/helper_functions/src/accessors.rs:974-979`:

```rust
pub fn get_consolidation_churn_limit<P: Preset>(
    config: &Config,
    state: &impl BeaconState<P>,
) -> Gwei {
    get_balance_churn_limit(config, state) - get_activation_exit_churn_limit(config, state)
}
```

No fork-gate; Electra formula applies at Gloas.

`compute_consolidation_epoch_and_update_churn` (`vendor/grandine/helper_functions/src/mutators.rs:211-248`) uses raw `u64` arithmetic — the same `(balance_to_process - 1) / per_epoch + 1` pattern as nimbus, with the same implicit-non-zero invariant.

H1, H2, H3, H4, H5 ✓. **H6 ✗** (Electra formula at Gloas).

## Cross-reference table

| Client | Main fn | Switch validity | Switch mutator | `get_consolidation_churn_limit` | Gloas fork-gate (H6) |
|---|---|---|---|---|---|
| prysm | `beacon-chain/core/requests/consolidations.go:103-238` | `consolidations.go:240-278` (defensive `len(creds)!=32 \|\| len(addr)!=20`) | `consolidations.go:280-294` | `core/helpers/validator_churn.go:44-54` (Electra: `BalanceChurnLimit − ActivationExitChurnLimit`) | ✗ |
| lighthouse | `state_processing/src/per_block_processing/process_operations.rs:684-789` | `process_operations.rs:629-682` (returns `Result<bool>`) | `consensus/types/src/state/beacon_state.rs:2692-2709` | `beacon_state.rs:2644-2648` (Electra; `safe_sub`) | ✗ |
| teku | `.../electra/execution/ExecutionRequestsProcessorElectra.java` | inlined in same file | `.../electra/helpers/BeaconStateMutatorsElectra.java:176-187` | `BeaconStateAccessorsElectra` (Electra); `ExecutionRequestsProcessorGloas` overrides only `processDepositRequest` | ✗ |
| nimbus | `beacon_chain/spec/state_transition_block.nim:658-746` (source pubkey lookup hoisted **before** switch path) | `state_transition_block.nim:627-655` | `beaconstate.nim:1534-1539` | `beaconstate.nim:276-284` (Electra; signature accepts `gloas.BeaconState` but body is Electra formula) | ✗ |
| lodestar | `state-transition/src/block/processConsolidationRequest.ts:16-102` (both pubkey checks hoisted **before** switch path) | `processConsolidationRequest.ts:107-149` | `state-transition/src/util/electra.ts:17-34` | `state-transition/src/util/validator.ts:115-130` — **fork-gated, EIP-8061 quotient at `fork ≥ ForkSeq.gloas`** | **✓** |
| grandine | `transition_functions/src/electra/block_processing.rs:1186-1294` | `block_processing.rs:1296-1341` | `helper_functions/src/mutators.rs:135-147` | `helper_functions/src/accessors.rs:974-979` (Electra) | ✗ |

## Empirical tests

### Pectra-surface fixture run

`consensus-spec-tests/tests/mainnet/electra/operations/consolidation_request/pyspec_tests/` — 10 EF fixtures. Run via `scripts/run_fixture.sh` against all six clients on 2026-05-03:

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

**Coverage gap:** 9 of 10 EF fixtures exercise the switch-to-compounding fast path; only `incorrect_not_enough_consolidation_churn_available` reaches the main consolidation path, and it terminates early at the churn-limit short-circuit. The end-to-end main path (source != target, both compounding-credentialed, full success ending in `PendingConsolidation` append) is not directly fixture-tested at this layer.

### Gloas-surface

No Gloas operations fixtures exist yet in the EF set. H6 is currently source-only.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — full main-path success).** Source has 0x02 creds, target has 0x02 creds, source != target, both active, neither exiting, source seasoned, no pending withdrawals, churn available. Expected: `pending_consolidations` grows by 1, source's `exit_epoch` set, `consolidation_balance_to_consume` decremented. The single highest-value missing Pectra-surface fixture.
- **T1.2 (priority — switch with excess balance triggers pending deposit).** Source has 0x01 creds, balance = 33 ETH, source == target, otherwise valid switch. Expected: source's creds[0] = 0x02 AND a pending deposit for 1 ETH appended via `queue_excess_active_balance`. The existing `switch_to_compounding_with_excess` covers this; check that all six clients add identical `(source_index, slot=GENESIS_SLOT, signature=G2_POINT_AT_INFINITY)` markers.

#### T2 — Adversarial probes
- **T2.1 (priority — multi-request churn drain).** A single block contains N consolidation requests, each consuming the entire `consolidation_balance_to_consume`. Expected: only the first M (M < N) succeed before churn is exhausted; the rest hit the `churn <= MIN_ACTIVATION_BALANCE` short-circuit. Tests stateful churn-decrement consistency across requests within the same block. Not covered by any existing fixture.
- **T2.2 (priority — already-compounding self-target).** Source == target, source has 0x02 creds. Switch validity fails on the `has_eth1_withdrawal_credential` check (0x01 only). Falls into main path; `source == target` short-circuit fires; request silently ignored. Verify all six clients ignore identically (no spurious `0x02 → 0x02` "self-upgrade").
- **T2.3 (priority — 0x00 BLS source).** Source has 0x00 creds (BLS-only, never executed a 0x01 transition). Switch validity fails (no eth1 credential). Main path's `has_execution_withdrawal_credential` fails (0x00 is neither 0x01 nor 0x02). Request silently ignored.
- **T2.4 (defensive — short or oversize creds).** Pyspec assumes 32-byte creds. SSZ enforces this. Prysm explicitly checks `len != 32`; others rely on type safety. If any future SSZ schema change introduces variable-length creds, prysm vs others would diverge.
- **T2.5 (Glamsterdam-target — Gloas churn-limit formula).** Synthetic Gloas-fork state at the first Gloas slot with active total balance chosen so the Electra formula `(balance_churn − activation_exit_churn)` and the Gloas formula `(total_active_balance // CONSOLIDATION_CHURN_LIMIT_QUOTIENT − mod EBI)` yield different values. Submit a single consolidation request with `source.effective_balance` between the two churn-limit values. Expected per spec: the request is accepted under the Gloas formula. The five Electra-formula clients will reject at short-circuit #4 (or accept with a different `earliest_consolidation_epoch`); lodestar will accept per spec. The single highest-value fixture to write before Glamsterdam activation.

## Mainnet reachability

**Reachable on canonical traffic at Glamsterdam activation, by any validator able to submit a consolidation request** (i.e. any validator with a `0x01` or `0x02` withdrawal credential and execution-layer access to authorise the request). The divergence does not require a proposer role, special tx-pool placement, or a custom chain.

**Trigger.** The first Gloas-slot block whose parent's execution payload carries a consolidation request hits the spec-divergent code path:

1. `apply_parent_execution_payload` calls `process_consolidation_request` for each parent-payload consolidation (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1132`).
2. Short-circuit #4 reads `get_consolidation_churn_limit(state) <= MIN_ACTIVATION_BALANCE`. The five Electra-formula clients compute `(balance_churn − activation_exit_churn)`; lodestar computes `(total_active_balance // 65536) − mod EBI`. With ~30M ETH staked, the two formulas yield different numeric values, so requests with `effective_balance` between the two limits short-circuit on one cohort and proceed on the other.
3. For requests that do proceed past #4, `compute_consolidation_epoch_and_update_churn` consumes from `consolidation_balance_to_consume` and advances `earliest_consolidation_epoch` by `additional_epochs = (balance_to_process − 1) / per_epoch_consolidation_churn + 1`. Different `per_epoch_consolidation_churn` → different `earliest_consolidation_epoch` written into state → different `state_root` at the post-state.

**Severity.** State-root divergence on every Gloas slot that carries a consolidation request whose source `effective_balance` straddles the two churn-limit values. Below `MIN_ACTIVATION_BALANCE`-effective stake the divergence does not materialise (#4 short-circuits identically on both sides only when the limit is `<= MIN_ACTIVATION_BALANCE`, which neither formula reaches near steady state). Above the divergent range, both formulas accept; the divergence is in the consumed amount and the resulting `earliest_consolidation_epoch`. Either way, the post-state hashes differ.

**Mitigation window.** Source-only at audit time; not yet covered by an EF fixture. Closing requires either (a) the five Electra-formula clients to ship EIP-8061 before Glamsterdam fork-cut, or (b) the spec to revert to the Electra formula. Without one or the other, mainnet at Glamsterdam activation splits into a 5-client cohort (Electra formula) and 1-client cohort (lodestar, Gloas formula). The 5-client cohort is the larger and will become the canonical chain unless coordinated re-alignment happens first; lodestar would be the divergent client until re-aligned. T2.5 above is the concrete fixture that pins down the divergence numerically.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H5) remain satisfied: aligned implementations of `process_consolidation_request`, `is_valid_switch_to_compounding_request`, `switch_to_compounding_validator`, and `compute_consolidation_epoch_and_update_churn`, with the same observable-equivalent rephrasings noted in the prior audit (prysm's defensive length checks; lighthouse's `safe_*` math + state-variant `match`; teku's `.minusMinZero()` saturating arithmetic; nimbus's hoisted source-pubkey lookup; lodestar's hoisted both-pubkey checks; grandine's `copy_from_slice` write). All 10 EF `operations/consolidation_request` fixtures still pass uniformly on prysm, lighthouse, lodestar, grandine.

**Glamsterdam-target finding (new):** H6 fails for 5 of 6 clients. Gloas (EIP-7732 + EIP-8061) reschedules the consolidation pass into `apply_parent_execution_payload` and modifies `get_consolidation_churn_limit` to the quotient-based formula. Only lodestar fork-gates the function; prysm, lighthouse, teku, nimbus, and grandine inherit the Electra formula unchanged into their Gloas paths (teku's `ExecutionRequestsProcessorGloas` overrides `processDepositRequest` only; nimbus's `get_consolidation_churn_limit` signature accepts a Gloas state but the body is Electra-formula; lighthouse and prysm have no fork-aware impl; grandine's accessor is not fork-aware). This will materialise as a state-root divergence on the first Gloas-slot block carrying a consolidation request whose source `effective_balance` straddles the two formulas' values.

Recommendations to the harness and the audit:
- Generate the **T1.1 main-path-success fixture** for the Pectra surface; the most important untested-by-EF surface there.
- Generate **T2.5 Gloas churn-limit formula fixture**; required to numerically pin the H6 divergence before Glamsterdam activation.
- File / coordinate upstream fork-gating of `get_consolidation_churn_limit` to EIP-8061 in prysm, lighthouse, teku, nimbus, grandine.
- Cross-cut audit (item-pair) with item #1 on the `0x02` write → `get_max_effective_balance` chain.

## Cross-cuts

### With item #1 (`process_effective_balance_updates`)

A successful `switch_to_compounding_validator` writes `0x02` to `withdrawal_credentials[0]` of the source validator. The next call to `get_max_effective_balance(source)` (item #1) returns 2048 ETH instead of 32 ETH. The next epoch's `process_effective_balance_updates` then uses the new cap, possibly raising the source's `effective_balance` from 32 ETH to whatever its `balance` rounds down to. **Composed test**: a block in slot N contains a switch-to-compounding consolidation request, and the epoch boundary at slot N+M (next epoch) produces a different `effective_balance` than it would have without the switch. All six clients should agree on the Pectra surface; the Gloas churn-limit divergence does not affect the switch fast path.

### With the pending-consolidations queue (WORKLOG #12 — `process_pending_consolidations`)

This item appends to `state.pending_consolidations` in main-path completion. The drain happens at epoch boundary in `process_pending_consolidations` (a separate item). Append ordering matters — if any client reorders or de-duplicates the queue, the drain order changes which cascades into per-validator balance changes.

### With `process_pending_deposits` queue (WORKLOG #3)

`switch_to_compounding_validator` calls `queue_excess_active_balance` which appends a pending **deposit** (with `bls.G2_POINT_AT_INFINITY` placeholder + `GENESIS_SLOT` marker) for any balance above `MIN_ACTIVATION_BALANCE`. So the switch path interacts with the pending-deposits queue too. A divergence in `queue_excess_active_balance` (separate sub-function) would surface here as a per-validator balance discrepancy at the next epoch.

### With Gloas ePBS scheduling (EIP-7732)

Gloas moves the consolidation pass out of `process_operations` into `apply_parent_execution_payload` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1130-1132`). The consolidation requests in any given block are taken from the **parent's** execution payload and processed at the **child's** slot. Item-level effect: the per-operation logic is unchanged, but the slot-relative state visible to `process_consolidation_request` differs from the Electra schedule. Cross-cut to the ePBS payload-availability audit.

## Adjacent untouched Electra-active consensus paths

1. **`queue_excess_active_balance`** — called by `switch_to_compounding_validator` when source balance > `MIN_ACTIVATION_BALANCE`. Writes a pending deposit with placeholder signature. Cross-cuts with WORKLOG #3 (`process_pending_deposits` queue ordering).
2. **`get_pending_balance_to_withdraw`** — short-circuit #11 in the main path. A separate function used here and in `process_withdrawal_request`. A divergence there would surface here as either spurious rejection or spurious acceptance. Worth a dedicated audit.
3. **`compute_activation_exit_epoch`** — input to `compute_consolidation_epoch_and_update_churn`. Same function used in `process_voluntary_exit`. A reordering or off-by-one in epoch math here cascades into different `exit_epoch` values; worth a dedicated boundary fixture at the `MAX_SEED_LOOKAHEAD` boundary.
4. **Pubkey-lookup data-structure consistency under churn** — prysm uses hashmap, lighthouse cache, teku Optional, nimbus BucketSortedValidators, lodestar `pubkey2index` Map, grandine `index_of_public_key`. Race conditions between activation/exit and consolidation could cause stale lookups.
5. **`is_valid_switch_to_compounding_request`'s tolerance for short creds** — only prysm bounds-checks. SSZ guarantees 32 bytes today; flag for future-proofing.
6. **`PendingConsolidation` queue append ordering** — main-path completion appends; if any client reorders by an internal sort key, the drain order at `process_pending_consolidations` differs and balances diverge. Cross-cuts with WORKLOG #12.
7. **Coarse-grained lighthouse harness verdict** — our runner reports PASS only at the `operations_consolidations` test-fn level (covers all 10 fixtures plus minimal-preset variants in one go). A failure on one fixture would FAIL the whole helper. Future runner extension: filter cargo-test by fixture-name regex so per-fixture verdicts are surfaced.
8. **EF coverage gap (Pectra)** — only 1 of 10 fixtures reaches the main path. Generating T1.1 would close the most important hole. T2.1 (multi-request stateful churn) is not testable via the operations format (single-op); requires a sanity_blocks fixture with multiple requests in one block.
9. **Gloas `compute_exit_epoch_and_update_churn` modification (EIP-8061)** — sibling to the `get_consolidation_churn_limit` modification. The exit path now uses `get_exit_churn_limit(state)` (separately defined in Gloas, line 824) rather than the Electra `get_activation_exit_churn_limit`. Sister audit item to this one's H6: re-survey the six clients for Gloas-aware exit churn at activation time. Same five clients likely also retain the Electra formula there.
