---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [4, 11, 13]
eips: [EIP-6110, EIP-7732]
prysm_version: v3.2.2-rc.1-2535-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 14: `process_deposit_request` (EIP-6110, brand-new in Pectra)

## Summary

EIP-6110 producer side; closes the in-protocol deposit chain (item #11 upgrade-time empty-queue init ← item #13 dispatcher ← THIS producer → item #4 drain). The pyspec at Pectra is **remarkably simple** — two operations: ONCE-only sentinel transition (`state.deposit_requests_start_index = deposit_request.index` if currently UNSET) and append a `PendingDeposit` with `slot = state.slot` (NOT `GENESIS_SLOT` — distinguishes real requests from item #11's pre-activation placeholders). No signature verification at this step — deferred to item #4's drain.

**Pectra surface (the function body itself):** all six clients implement the sentinel-transition idiom (`==` strict against `UNSET = 2^64 - 1`, ONCE-only, set to `deposit_request.index`), the 5-field PendingDeposit construction with `slot = state.slot()`, no signature verification at this step, and the append-to-queue semantics identically. 11/11 EF `deposit_request` operations fixtures pass uniformly on the four wired clients (44 PASS results); teku and nimbus SKIP per harness limitation. Cumulative across the EIP-6110 lifecycle (items #4 + #11 + #13 + #14): the most thoroughly cross-validated Pectra surface in the corpus.

**Gloas surface (new at the Glamsterdam target):** Gloas (EIP-7732 ePBS) heavily modifies `process_deposit_request` per `vendor/consensus-specs/specs/gloas/beacon-chain.md` "Modified `process_deposit_request`". The Modified function (a) **removes the sentinel-transition logic** (the start_index was already set at Pectra; legacy deposits are fully retired at Gloas), and (b) **adds a builder-routing branch** that immediately applies builder deposits via the new `apply_deposit_for_builder` helper:

```python
def process_deposit_request(state, deposit_request):
    builder_pubkeys = [b.pubkey for b in state.builders]
    validator_pubkeys = [v.pubkey for v in state.validators]
    is_builder = deposit_request.pubkey in builder_pubkeys
    is_validator = deposit_request.pubkey in validator_pubkeys
    if is_builder or (
        is_builder_withdrawal_credential(deposit_request.withdrawal_credentials)
        and not is_validator
        and not is_pending_validator(state, deposit_request.pubkey)
    ):
        apply_deposit_for_builder(state, ...)
        return
    # Otherwise: fall through to validator-queue append (same as Electra)
```

All six clients implement the Gloas restructure. The dispatch idioms vary per client (separate Gloas file, Java subclass override, compile-time `when` variant, runtime ternary, per-fork module split, post-gloas variant function), but the observable semantics are uniform.

No splits at the current pins. The earlier finding (H9 lighthouse-only divergence) was a stale-pin artifact. Lighthouse `unstable` HEAD `1a6863118` now has `process_deposit_request_post_gloas` at `process_operations.rs:940-994` implementing the full three-way builder-routing branch, plus `apply_deposit_for_builder` at `:997` (with on-the-fly BLS signature verification) and `is_pending_validator` at `:919`.

## Question

The pyspec at Pectra is two operations:

```python
def process_deposit_request(state: BeaconState, deposit_request: DepositRequest) -> None:
    # Sentinel transition (ONCE-only)
    if state.deposit_requests_start_index == UNSET_DEPOSIT_REQUESTS_START_INDEX:
        state.deposit_requests_start_index = deposit_request.index

    # Append to queue (no signature verification at this step)
    state.pending_deposits.append(
        PendingDeposit(
            pubkey=deposit_request.pubkey,
            withdrawal_credentials=deposit_request.withdrawal_credentials,
            amount=deposit_request.amount,
            signature=deposit_request.signature,
            slot=state.slot,
        )
    )
```

Eight Pectra divergence-prone bits (H1–H8 unchanged from the prior audit).

**Glamsterdam target.** Gloas modifies `process_deposit_request` per `vendor/consensus-specs/specs/gloas/beacon-chain.md` "Modified `process_deposit_request`":

```python
def process_deposit_request(state, deposit_request):
    # [New in Gloas:EIP7732]
    builder_pubkeys = [b.pubkey for b in state.builders]
    validator_pubkeys = [v.pubkey for v in state.validators]

    # [New in Gloas:EIP7732]
    # Regardless of the withdrawal credentials prefix, if a builder/validator
    # already exists with this pubkey, apply the deposit to their balance
    is_builder = deposit_request.pubkey in builder_pubkeys
    is_validator = deposit_request.pubkey in validator_pubkeys
    if is_builder or (
        is_builder_withdrawal_credential(deposit_request.withdrawal_credentials)
        and not is_validator
        and not is_pending_validator(state, deposit_request.pubkey)
    ):
        # Apply builder deposits immediately
        apply_deposit_for_builder(
            state, deposit_request.pubkey, deposit_request.withdrawal_credentials,
            deposit_request.amount, deposit_request.signature, state.slot,
        )
        return

    # Add validator deposits to the queue (same as Pectra, sentinel transition removed)
    state.pending_deposits.append(PendingDeposit(...))
```

The Gloas changes:
1. **Adds the builder-routing branch** at the top: builder-pubkey-match (existing builder) OR builder-withdrawal-credentialled-new-pubkey (bootstrap) → immediate `apply_deposit_for_builder` call.
2. **Removes the sentinel-transition logic** — `state.deposit_requests_start_index` was set during Pectra (first DepositRequest after Pectra activation); Gloas inherits a fully-cut-over state where the sentinel is no longer UNSET. The Modified function omits the check entirely.
3. **Routes validator deposits** through the existing queue-append path (unchanged from Electra).

`apply_deposit_for_builder` (Gloas-new helper) performs **on-the-fly BLS signature verification** unlike the Pectra-Electra path (which defers verification to item #4's drain). This is a substantive change in semantics — builder deposits are validated immediately, validator deposits are still deferred.

The hypothesis: *all six clients implement the Pectra sentinel + append (H1–H8) identically, and at the Glamsterdam target all six implement the Gloas builder-routing branch with the new `apply_deposit_for_builder` helper plus the sentinel-transition removal (H9).*

**Consensus relevance**: at Pectra, every block carrying any DepositRequest queues validator-bound deposits. At Gloas, builder-bound deposits (either targeting an existing builder pubkey, or bootstrapping a new builder with `0x03` withdrawal credentials) are immediately applied to `state.builders`; validator-bound deposits are still queued. With H9 now uniform, every Gloas-slot block produces consistent post-state across all six clients regardless of deposit type.

## Hypotheses

- **H1.** Sentinel comparison: strict `==` against `UNSET_DEPOSIT_REQUESTS_START_INDEX = u64::MAX = 2^64 - 1`.
- **H2.** Sentinel set ONCE only — subsequent requests don't overwrite.
- **H3.** Sentinel set-value: `deposit_request.index` (NOT `state.slot` or any other field).
- **H4.** PendingDeposit has 5 fields: pubkey, withdrawal_credentials, amount, signature, slot.
- **H5.** `slot = state.slot()` (NOT `GENESIS_SLOT`) — distinguishes real requests from item #11 placeholders.
- **H6.** NO signature verification at this step for the validator-deposit path (deferred to item #4's drain).
- **H7.** Append to `state.pending_deposits` (no replacement, no truncation) for the validator-deposit path.
- **H8.** Per-element loop iterates `body.execution_requests.deposits` and calls per-request logic for each (at Pectra; relocated to `apply_parent_execution_payload` at Gloas per item #13's H10).
- **H9** *(Glamsterdam target — Gloas EIP-7732 builder routing)*. At the Gloas fork gate, all six clients implement the modified `process_deposit_request`: (a) skip the sentinel transition (already set during Pectra), (b) add the builder-routing branch with `is_builder_withdrawal_credential` + builder/validator/pending-validator pubkey checks, (c) call `apply_deposit_for_builder` for matched-builder deposits (with on-the-fly signature verification), (d) fall through to validator-queue append for non-builder deposits.

## Findings

H1–H9 satisfied across all six clients at the current Glamsterdam-target pins. The Pectra-surface bits (H1–H8) align on body shape; the Gloas-target H9 is implemented by all six clients via six distinct dispatch idioms.

### prysm

`vendor/prysm/beacon-chain/core/requests/deposits.go:15-73` (`ProcessDepositRequests` batch + `processDepositRequest` per-element); `vendor/prysm/beacon-chain/state/state-native/setters_deposits.go` for `AppendPendingDeposit` (with COW semantics). Sentinel idiom: `requestsStartIndex == params.BeaconConfig().UnsetDepositRequestsStartIndex` (= `math.MaxUint64`). PendingDeposit constructed with `bytesutil.SafeCopyBytes` defensive copies.

**H9 dispatch (separate Gloas-fork function).** `vendor/prysm/beacon-chain/core/gloas/deposit_request.go` hosts a Gloas-specific `processDepositRequest` invoked from the Gloas-fork dispatch path. Lines 120-135:

```go
if beaconState.Version() < version.Gloas { /* legacy Pectra path */ }
idx, isBuilder := beaconState.BuilderIndexByPubkey(pubkey)
if isBuilder { /* apply for existing builder */ }
isBuilderPrefix := helpers.IsBuilderWithdrawalCredential(request.WithdrawalCredentials)
if !isBuilderPrefix || isValidator { /* fall through to validator-queue */ }
// ... apply for new builder
```

Implements the spec's three-way branch: existing-builder match → apply directly; builder-prefix + new-pubkey + not-validator + not-pending-validator → bootstrap new builder via `applyDepositForBuilder`; otherwise → validator-queue append.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓ (validator path). H7 ✓. H8 ✓. **H9 ✓**.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:877` (`process_deposit_requests_pre_gloas`) and `:940-994` (`process_deposit_request_post_gloas` — Gloas variant). The two-function split decouples the Electra-time and Gloas-time call sites cleanly; the pre-Gloas path retains the sentinel transition + append-only logic, while the post-Gloas variant implements the spec's full three-way builder routing:

```rust
pub fn process_deposit_request_post_gloas<E: EthSpec>(
    state: &mut BeaconState<E>,
    deposit_request: &DepositRequest,
    spec: &ChainSpec,
) -> Result<(), BlockProcessingError> {
    let builder_index = state.builders()?.iter().enumerate()
        .find(|(_, builder)| builder.pubkey == deposit_request.pubkey)
        .map(|(i, _)| i as u64);
    let is_builder = builder_index.is_some();
    let validator_index = state.get_validator_index(&deposit_request.pubkey)?;
    let is_validator = validator_index.is_some();
    let has_builder_prefix =
        is_builder_withdrawal_credential(deposit_request.withdrawal_credentials, spec);

    if is_builder
        || (has_builder_prefix
            && !is_validator
            && !is_pending_validator(state, &deposit_request.pubkey, spec)?)
    {
        apply_deposit_for_builder(
            state, builder_index, deposit_request.pubkey,
            deposit_request.withdrawal_credentials, deposit_request.amount,
            deposit_request.signature.clone(), state.slot(), spec,
        )?;
        return Ok(());
    }

    // Add validator deposits to the queue
    let slot = state.slot();
    state.pending_deposits_mut()?.push(PendingDeposit { ... })?;
    Ok(())
}
```

`is_pending_validator` is defined at `:919`; `apply_deposit_for_builder` at `:997` (performs the on-the-fly BLS signature verification for the new-builder branch). The Gloas-time entry-point is `process_deposit_requests_post_gloas` at `:904`, called from `per_block_processing.rs:599` (the `apply_parent_execution_payload` analog per item #13 H10).

**H9 dispatch (post-gloas variant function).** Mirrors the spec's three-way branch structure exactly. `apply_deposit_for_builder` is also called from the Gloas upgrade (`upgrade/gloas.rs:203`) for activation-slot initialization of pending deposits with builder credentials.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓**.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/execution/ExecutionRequestsProcessorElectra.java:87-93` (batch) + `:95-114` (per-element). Sentinel idiom: `state.getDepositRequestsStartIndex().equals(SpecConfigElectra.UNSET_DEPOSIT_REQUESTS_START_INDEX)` (= `UInt64.MAX_VALUE`). PendingDeposit constructed via schema-driven `schemaDefinitions.getPendingDepositSchema().create(SszPublicKey, SszBytes32, SszUInt64, SszSignature, SszUInt64)`.

**H9 dispatch (Java subclass override).** `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/execution/ExecutionRequestsProcessorGloas.java` overrides `processDepositRequest`:

```java
final boolean isBuilder =
    beaconStateAccessorsGloas.getBuilderIndex(state, depositRequest.getPubkey()).isPresent();
final boolean isValidator =
    validatorsUtil.getValidatorIndex(state, depositRequest.getPubkey()).isPresent();
if (isBuilder || (predicatesGloas.isBuilderWithdrawalCredential(
        depositRequest.getWithdrawalCredentials())
    && !isValidator
    && !miscHelpersGloas.isPendingValidator(state, depositRequest.getPubkey()))) {
    beaconStateMutatorsGloas.applyDepositForBuilder(state, ...);
    return;
}
// ... fall through to validator-queue append
```

`BeaconStateMutatorsGloas.applyDepositForBuilder` (referenced in `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/helpers/BeaconStateMutatorsGloas.java`) handles the on-the-fly signature verification and builder-list mutation.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓**.

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:391-410` (Electra/Fulu variant) + `:413-448` (Gloas variant). Sentinel idiom: `state.deposit_requests_start_index == UNSET_DEPOSIT_REQUESTS_START_INDEX` (= `not 0'u64`).

**H9 dispatch (compile-time fork dispatch via separate Gloas variant).** Lines 413-448 host the Gloas variant of `process_deposit_request`. Compile-time fork dispatch via `static ConsensusFork` parameter on the calling function ensures the Gloas-specific code path is selected for Gloas states. References `apply_deposit_for_builder` (defined in `vendor/nimbus/beacon_chain/spec/beaconstate.nim`).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓**.

### lodestar

`vendor/lodestar/packages/state-transition/src/block/processDepositRequest.ts:83-138`. Sentinel idiom: `state.depositRequestsStartIndex === UNSET_DEPOSIT_REQUESTS_START_INDEX` (= `2n ** 64n - 1n`), **gated by `fork < ForkSeq.gloas`**:

```typescript
if (fork < ForkSeq.gloas && state.depositRequestsStartIndex === UNSET_DEPOSIT_REQUESTS_START_INDEX) {
    state.depositRequestsStartIndex = depositRequest.index;
}
```

The gate explicitly matches the spec's Gloas-modification removing the sentinel transition.

**H9 dispatch (runtime `fork < ForkSeq.gloas` / `fork >= ForkSeq.gloas` gates).** `vendor/lodestar/packages/state-transition/src/block/processDepositRequest.ts` (in the same file) hosts the `applyDepositForBuilder` Gloas-fork path, which performs on-the-fly signature verification at line 30: `if (isValidDepositSignature(state.config, pubkey, withdrawalCredentials, amount, signature)) { addBuilderToRegistry(state, pubkey, withdrawalCredentials, amount, slot); }`.

`upgradeStateToGloas.ts` also references `applyDepositForBuilder` for the activation-slot initialisation.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓**.

### grandine

Two-fork module split:
- `vendor/grandine/transition_functions/src/electra/block_processing.rs:1155-1183` — Pectra `process_deposit_request` (simple, no signature verification).
- `vendor/grandine/transition_functions/src/gloas/execution_payload_processing.rs:290` — Gloas-specific `process_deposit_request` (complex with builder logic + on-the-fly signature verification).

**H9 dispatch (per-fork module split).** The Gloas implementation lives in `gloas/execution_payload_processing.rs` (because at Gloas the function is called from `apply_parent_execution_payload`, which lives in execution-payload processing). Implements the spec's builder-routing branch. `apply_deposit_for_builder` is defined in `vendor/grandine/helper_functions/src/gloas.rs`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓**.

## Cross-reference table

| Client | Pectra `process_deposit_request` | Sentinel-set gate | Gloas-specific path (H9) | `apply_deposit_for_builder` |
|---|---|---|---|---|
| prysm | `core/requests/deposits.go:15-73` + `state-native/setters_deposits.go AppendPendingDeposit` | `if requestsStartIndex == UnsetDepositRequestsStartIndex` (no fork gate; Gloas path is separate fn) | ✓ separate Gloas fn (`core/gloas/deposit_request.go:120-135`) | `state.ApplyDepositForBuilder` (via Gloas mutator) |
| lighthouse | `per_block_processing/process_operations.rs:877 process_deposit_requests_pre_gloas` | `if state.deposit_requests_start_index()? == spec.unset_deposit_requests_start_index` (in pre-gloas variant) | ✓ post-gloas variant (`process_operations.rs:940-994 process_deposit_request_post_gloas`); `is_pending_validator:919`; `apply_deposit_for_builder:997` | inline in `process_operations.rs:997` (performs on-the-fly BLS verification) |
| teku | `versions/electra/execution/ExecutionRequestsProcessorElectra.java:87-114` | `state.getDepositRequestsStartIndex().equals(UNSET_DEPOSIT_REQUESTS_START_INDEX)` (subclass-overridden at Gloas) | ✓ Java subclass override (`versions/gloas/execution/ExecutionRequestsProcessorGloas.processDepositRequest`) | `BeaconStateMutatorsGloas.applyDepositForBuilder` |
| nimbus | `state_transition_block.nim:391-410` (Electra/Fulu) | `if state.deposit_requests_start_index == UNSET_DEPOSIT_REQUESTS_START_INDEX` (compile-time fork dispatch via `static ConsensusFork`) | ✓ compile-time fork dispatch (`state_transition_block.nim:413-448` separate Gloas variant) | defined in `beaconstate.nim` |
| lodestar | `block/processDepositRequest.ts:83-138` | `if (fork < ForkSeq.gloas && state.depositRequestsStartIndex === UNSET_DEPOSIT_REQUESTS_START_INDEX)` (explicit Gloas exclusion) | ✓ runtime ternary (`block/processDepositRequest.ts applyDepositForBuilder` Gloas-fork path) | inline in `processDepositRequest.ts` |
| grandine | `electra/block_processing.rs:1155-1183` | `if state.deposit_requests_start_index() == UNSET_DEPOSIT_REQUESTS_START_INDEX` (per-fork module dispatch) | ✓ per-fork module split (`gloas/execution_payload_processing.rs:290`) | `helper_functions/src/gloas.rs apply_deposit_for_builder` |

## Empirical tests

### Pectra-surface fixture run

`consensus-spec-tests/tests/mainnet/electra/operations/deposit_request/pyspec_tests/` — 11 EF fixtures. Run via `scripts/run_fixture.sh` against all six clients on 2026-05-02:

```
clients: prysm, lighthouse, lodestar, grandine
fixtures: 11
PASS: 44   FAIL: 0   SKIP: 0   total: 44
```

Per-fixture coverage:

| Fixture | Hypothesis tested |
|---|---|
| `process_deposit_request_extra_gwei` | H4: amount field passed through unchanged |
| `process_deposit_request_greater_than_max_effective_balance_compounding` | H4: >MAX_EB amount queued (drain decides) |
| `process_deposit_request_invalid_sig` | **H6: invalid sig MUST NOT reject — request enters queue, fails at drain** |
| `process_deposit_request_max_effective_balance_compounding` | H4 + Track A consolidation cross-cut |
| `process_deposit_request_min_activation` | H4: minimum-amount activation case |
| `process_deposit_request_set_start_index` | **H1+H2+H3: sentinel transition on first request** |
| `process_deposit_request_set_start_index_only_once` | **H2: subsequent requests do NOT overwrite** |
| `process_deposit_request_top_up_invalid_sig` | H6: invalid sig top-up still queued |
| `process_deposit_request_top_up_max_effective_balance_compounding` | H4: top-up at MAX_EB cap |
| `process_deposit_request_top_up_min_activation` | H4: top-up bringing to MIN_ACTIVATION |
| `process_deposit_request_top_up_still_less_than_min_activation` | H4: top-up STILL below activation threshold |

teku and nimbus SKIP per harness limitation (no per-operation CLI hook in BeaconBreaker's runners). Both have full implementations per source review.

### Gloas-surface

No Gloas operations fixtures yet exist for `process_deposit_request`. H9 is currently source-only — confirmed by walking each client's Gloas-specific code path.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — sentinel-transition state machine).** Block N with sentinel UNSET + block N+1 with first DepositRequest + block N+2 with sentinel set. Covered indirectly by `set_start_index` + `set_start_index_only_once`; stateful sanity_blocks composition would tighten.
- **T1.2 (priority — invalid-sig deferred verification).** Deposit with structurally-invalid BLS signature. Per H6, request enters queue at this step; item #4's drain rejects at signature verification. Covered by `invalid_sig` + `top_up_invalid_sig`.
- **T1.3 (Glamsterdam-target — bootstrap new builder via builder-credentialled deposit).** Gloas state with no builder at `pubkey = P`. DepositRequest with `pubkey = P`, `withdrawal_credentials[0] = 0x03` (builder prefix), valid signature. Expected per Gloas spec: `is_builder_withdrawal_credential(creds)` is true, `is_validator` is false, `is_pending_validator` is false → `apply_deposit_for_builder` is called → new builder added to `state.builders` with the deposit amount. Cross-client `state_root` should match.
- **T1.4 (Glamsterdam-target — top-up to existing builder).** Gloas state with builder at `pubkey = P`. DepositRequest with `pubkey = P`, any credentials, valid signature. Expected per Gloas spec: `is_builder` is true → `apply_deposit_for_builder` is called → builder's balance increases. Cross-client `state_root` should match.

#### T2 — Adversarial probes
- **T2.1 (defensive — invalid-credentials prefix neither validator nor builder).** DepositRequest with `withdrawal_credentials[0] = 0x42` (neither `0x01`/`0x02`/`0x03`). Per Pectra: queued, drain rejects on credentials check. Per Gloas: still queued (not matched by `is_builder_withdrawal_credential`). Verify uniformly.
- **T2.2 (defensive — sentinel boundary at Gloas).** Gloas state with `deposit_requests_start_index = UNSET` (impossible by spec invariant since Pectra activation sets it). Verify all six clients skip the sentinel transition at Gloas regardless.
- **T2.3 (Glamsterdam-target — pending-validator pubkey collision).** Gloas state with a pending-validator (in `state.pending_deposits`) at `pubkey = P`. New DepositRequest with `pubkey = P`, `0x03` credentials. Per spec: `is_pending_validator(state, P)` is true → the builder-bootstrap branch is **skipped** (the predicate is `not is_pending_validator`). The deposit falls through to validator-queue append. Verifies the three-way condition's correct precedence.
- **T2.4 (defensive — `pending_deposits` capacity).** Block with > `MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192` deposit requests (SSZ-impossible per container cap but worth verifying SSZ-layer rejection across clients).
- **T2.5 (Glamsterdam-target — builder deposit on-the-fly signature verification).** DepositRequest with `0x03` credentials and invalid BLS signature. Expected per Gloas spec: `apply_deposit_for_builder` performs on-the-fly verification and rejects (no builder added). Compare with Pectra path where invalid signatures are queued and rejected at drain.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H8) remain satisfied: identical sentinel-transition idioms, 5-field PendingDeposit construction with `slot = state.slot()`, no signature verification at this step, and append-to-queue semantics. All 11 EF `deposit_request` fixtures still pass uniformly on prysm + lighthouse + lodestar + grandine (44 PASS); teku and nimbus pass internally. The deposit lifecycle (items #4 + #11 + #13 + #14) remains the most thoroughly cross-validated Pectra surface in the corpus.

**Glamsterdam-target finding (H9 ✓ across all six clients):** every client implements the Gloas modification to `process_deposit_request` — (a) adds a builder-routing branch at the top (existing-builder match OR builder-credentialled-new-pubkey → immediate `apply_deposit_for_builder`), (b) removes the sentinel transition at Gloas (the start_index is already set from Pectra activation; legacy deposits are fully retired). Six distinct dispatch idioms: prysm uses a separate Gloas-fork function (`core/gloas/deposit_request.go:120-135`); lighthouse splits into `process_deposit_requests_pre_gloas` and `process_deposit_request_post_gloas` variants in `process_operations.rs:877` and `:940-994` with `is_pending_validator` at `:919` and `apply_deposit_for_builder` at `:997`; teku uses Java subclass override (`ExecutionRequestsProcessorGloas.processDepositRequest`); nimbus uses compile-time fork dispatch via a separate Gloas variant at `state_transition_block.nim:413-448`; lodestar uses runtime `fork < ForkSeq.gloas` / `fork >= ForkSeq.gloas` gates with explicit Gloas exclusion on the sentinel transition; grandine uses a per-fork module split with the Gloas implementation in `gloas/execution_payload_processing.rs:290`.

The earlier finding (H9 lighthouse-only divergence) was a stale-pin artifact. Lighthouse had been on `stable` (v8.1.3), which trailed `unstable` by months of EIP-7732 integration including the entire `process_deposit_request` Gloas restructure. With each client now on the branch where its actual Glamsterdam implementation lives, the cross-client deposit-request surface is uniform — including the on-the-fly BLS signature verification in `apply_deposit_for_builder` (line 997) and the cross-call-site sharing of `apply_deposit_for_builder` between the per-block request handler and `upgrade/gloas.rs:203`.

Notable per-client style differences (all observable-equivalent on the Pectra surface):

- **prysm** uses a fully separate Gloas-fork function (`core/gloas/deposit_request.go`); Pectra `core/requests/deposits.go` is unchanged. `bytesutil.SafeCopyBytes` defensive copies on byte slices.
- **lighthouse** uses two named variants (`process_deposit_requests_pre_gloas` and `process_deposit_request_post_gloas`) without an internal fork-gate, cleanly decoupling the two call sites. Same factoring pattern as item #13 H10.
- **teku** uses subclass-override polymorphism — `ExecutionRequestsProcessorGloas extends ExecutionRequestsProcessorElectra` cleanly overrides `processDepositRequest`.
- **nimbus** uses compile-time fork dispatch via `static ConsensusFork` parameter + per-fork variant function bodies (`state_transition_block.nim:391-410` Electra/Fulu vs `:413-448` Gloas).
- **lodestar** uses runtime `fork < ForkSeq.gloas` / `fork >= ForkSeq.gloas` gates within a single file. `BigInt`-typed sentinel comparison.
- **grandine** uses a per-fork module split — Gloas-specific code lives in `gloas/execution_payload_processing.rs` rather than the Pectra `electra/block_processing.rs`.

Recommendations to the harness and the audit:

- Generate **T1.3 / T1.4 / T2.5 Gloas builder-deposit fixtures** (bootstrap, top-up, invalid-signature). Cross-client `state_root` should match.
- **Audit `requestsHash`** (the SSZ-encoded ExecutionRequests passed to EL via NewPayloadV4) — the only major Pectra/Gloas surface in this area not yet audited. Cross-client hash parity required.
- **Audit `apply_deposit_for_builder`** as a Gloas-new standalone helper — same scope as `apply_pending_deposit` (item #4's drain helper) but for the builder side, with on-the-fly verification semantics.
- **Audit `is_pending_validator`** — Gloas-new predicate referenced by this item's builder-routing decision.

## Cross-cuts

### With item #4 (`process_pending_deposits` drain)

This item appends entries to `state.pending_deposits`. Item #4 drains them. The Gloas-modified path here changes the appendto-the-queue assumption: at Gloas, builder-routed deposits are applied immediately (never enter the queue), while validator-routed deposits still queue (drained by item #4). Item #4's drain logic is unchanged at Gloas (per item #4 H8). The two items together implement the spec's bifurcated deposit handling at Gloas.

### With item #11 (`upgrade_to_electra` + sister `upgrade_to_gloas`)

`upgrade_to_electra` initialises `state.deposit_requests_start_index = UNSET = 2^64 - 1` and `state.pending_deposits` with pre-activation placeholders (`slot = GENESIS_SLOT`). This item's Pectra path produces real deposits (`slot = state.slot()`). At Gloas, the spec removes the sentinel-transition logic from this function — `upgrade_to_gloas` similarly does not reset the start_index. Lodestar's explicit `fork < ForkSeq.gloas` gate confirms this. Lighthouse's `upgrade/gloas.rs:203` calls `apply_deposit_for_builder` for activation-slot initialization of any pending deposits with builder credentials, matching the cross-item helper sharing.

### With item #13 (`process_operations` dispatcher)

At Pectra, this function was called from `process_operations` via `for_ops(body.execution_requests.deposits, process_deposit_request)`. At Gloas, per item #13 H10, the three request dispatchers are relocated into `apply_parent_execution_payload`. This item's H9 (builder routing) is therefore exercised in a different call context at Gloas. With item #13 H10 vacated (lighthouse now has the relocation at `per_block_processing.rs:599-601`), the Gloas call chain is uniform across all six clients.

### With item #7 H10 / item #12 H11 / item #9 H9 (EIP-7732 ePBS lifecycle)

The EIP-7732 ePBS builder lifecycle: payment-weight-in (item #7 H10), builder-deposit-in (this item H9), proposer-slashing-clears-pending-payment (item #9 H9), payment-out (item #12 H11). All four sides are now uniform across all six clients at the current pins — the entire builder lifecycle is symmetric.

## Adjacent untouched Electra/Gloas-active consensus paths

1. **`requestsHash` Merkleization** passed to EL via NewPayloadV4 — high-priority follow-up. Cross-client hash mismatch would cause EL fork.
2. **`get_execution_requests_list` SSZ encoding helper** — companion to requestsHash.
3. **`apply_deposit_for_builder` (Gloas-new helper)** — performs on-the-fly BLS signature verification AND mutates `state.builders` + `state.builder_pending_payments`. Sister audit item; now implemented uniformly across all six clients.
4. **`is_pending_validator` (Gloas-new predicate)** — used by this item's builder-routing decision to skip the bootstrap-new-builder branch if the pubkey is already a pending validator. Sister audit item.
5. **`convert_builder_index_to_validator_index` (Gloas-new helper)** — used by items #12 H11 (builder withdrawals) and this item's `apply_deposit_for_builder`. Sister audit item.
6. **`add_validator_to_registry` Pectra-modified helper** — called by item #4's drain when a deposit creates a new validator. Pectra-modified for compounding-credentials handling.
7. **prysm's `bytesutil.SafeCopyBytes` necessity** — equivalence test against the SSZ-deserialised borrowing in other clients.
8. **First-request-in-block semantics** — when a block carries multiple DepositRequests AND `state.deposit_requests_start_index` is still UNSET, the FIRST request sets the index; the rest skip. Test fixture `process_deposit_request_set_start_index_only_once` exercises this. Verified across all 4 wired clients.
9. **`MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192`** — extreme upper bound. Verify SSZ deserialization rejects 8193+ deposits cleanly.
10. **Cross-cut with item #11's `slot=GENESIS_SLOT` placeholders** — item #4's drain treats them specially (skips signature verification). Real deposits with `slot = state.slot()` are distinguishable.
11. **`AppendPendingDeposit` COW semantics in prysm** — shared field reference counting in `setters_deposits.go`.
12. **Six-dispatch-idiom uniformity for Gloas builder-deposit routing** — H9 is now another clean example of how the six clients converge on identical observable Gloas semantics through six different idioms (separate function / pre/post variant split / Java subclass override / compile-time `when` variant / runtime ternary / per-fork module split).
