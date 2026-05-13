---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [2, 3, 6, 7, 8, 9, 11, 12]
eips: [EIP-6110, EIP-7685, EIP-7732]
prysm_version: v3.2.2-rc.1-2535-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 13: `process_operations` Pectra dispatcher (EIP-6110 cutover + EIP-7685 requests routing)

## Summary

`process_operations` is the **block-body fan-out** function that dispatches each operation list to its per-operation processor. Pectra adds two distinct modifications: (1) **EIP-6110 legacy-deposit cutover** at the head of the function (`eth1_deposit_index_limit = min(state.eth1_data.deposit_count, state.deposit_requests_start_index)`; legacy deposits drain to the limit then disable permanently); (2) **EIP-7685 three new request dispatchers** at the tail (`for_ops(body.execution_requests.deposits/withdrawals/consolidations, process_X_request)` in that exact order).

**Pectra surface (the function body itself):** all six clients implement the `min` cutover predicate, the conditional `len(body.deposits)` assertions, the three-new-dispatcher ordering, and the per-list SSZ caps identically. The dispatcher is exercised indirectly via the cumulative 280+ EF fixtures from items #2/#3/#4/#5/#6/#7/#8/#9/#12 — all flowing through `process_operations`. The `sanity/blocks/pyspec_tests/deposit_transition__*` fixtures (8 fixtures) directly test the EIP-6110 cutover state machine; the harness wiring is available but not yet routed at audit time.

**Gloas surface (new at the Glamsterdam target):** Gloas (EIP-7732 ePBS) heavily modifies `process_operations` per `vendor/consensus-specs/specs/gloas/beacon-chain.md:1478-1518` "Modified `process_operations`". The Note explicitly states: *"`process_operations` is modified to process PTC attestations and removes calls to `process_deposit_request`, `process_withdrawal_request`, and `process_consolidation_request`."* The three Pectra request dispatchers are **removed** (relocated into the Gloas-new `apply_parent_execution_payload` helper — items #2/#3/#4 cross-cuts), and a new dispatcher `for_ops(body.payload_attestations, process_payload_attestation)` is added.

All six clients implement both changes at Gloas. The dispatch idioms vary per client (separate Gloas module, Java subclass override, compile-time `when`, runtime fork-range ternary, per-fork module split, inline runtime branch), but the observable Gloas semantics are uniform.

No splits at the current pins. The earlier finding (H10 lighthouse-only divergence) was a stale-pin artifact. Lighthouse `unstable` HEAD `1a6863118` now has the correct fork-dispatch at `process_operations.rs:47-68`: at Gloas, `process_payload_attestations` is invoked and the three Electra request dispatchers are skipped; at Electra (pre-Gloas), the three request dispatchers fire. The Gloas-time request dispatch is relocated into `per_block_processing.rs:599-601` (the `apply_parent_execution_payload` analog), running against the parent's execution payload requests — exactly per the spec restructuring.

## Question

`process_operations` receives the parsed `BeaconBlockBody` and dispatches each operation list. Pectra modifies two distinct sections. EIP-6110 cutover (head):

```python
eth1_deposit_index_limit = min(
    state.eth1_data.deposit_count, state.deposit_requests_start_index
)
if state.eth1_deposit_index < eth1_deposit_index_limit:
    assert len(body.deposits) == min(MAX_DEPOSITS, eth1_deposit_index_limit - state.eth1_deposit_index)
else:
    assert len(body.deposits) == 0  # Legacy mechanism disabled
```

At the upgrade slot, `deposit_requests_start_index = UNSET_DEPOSIT_REQUESTS_START_INDEX = 2^64 - 1` (item #11). When the EL eventually sends the first `DepositRequest`, `process_deposit_request` sets `state.deposit_requests_start_index = first_request.index` (sentinel transition) → `min` returns the smaller value → legacy deposits drain to that index, then the second branch (`assert len == 0`) takes over permanently.

EIP-7685 three new request dispatchers (tail), in exact order:

```python
for_ops(body.execution_requests.deposits,       process_deposit_request)
for_ops(body.execution_requests.withdrawals,    process_withdrawal_request)
for_ops(body.execution_requests.consolidations, process_consolidation_request)
```

Nine Pectra hypotheses (H1–H9) cover the `min` cutover formula, the sentinel default, the two assertion branches, the three-new-dispatcher ordering, the per-list SSZ caps, and the legacy-Capella operations preserved.

**Glamsterdam target.** Gloas modifies `process_operations` per the inline `[Modified in Gloas:EIP7732]` annotations (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1478-1518`):

```python
def process_operations(state: BeaconState, body: BeaconBlockBody) -> None:
    # ... EIP-6110 cutover (unchanged) ...
    # ... legacy-Capella operations (proposer_slashings → attester_slashings →
    #     attestations → deposits → voluntary_exits → bls_to_execution_changes) ...

    # [Modified in Gloas:EIP7732] Removed `process_deposit_request`
    # [Modified in Gloas:EIP7732] Removed `process_withdrawal_request`
    # [Modified in Gloas:EIP7732] Removed `process_consolidation_request`

    # [New in Gloas:EIP7732]
    for_ops(body.payload_attestations, process_payload_attestation)
```

The three request dispatchers are relocated into the Gloas-new helper `apply_parent_execution_payload` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1106-1180`), invoked from `process_parent_execution_payload` — they now run against the **parent's** execution payload requests at the **child's** slot, not against the current block's body. The new `process_payload_attestation` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1670+`) processes the new `body.payload_attestations` operations list and is part of the EIP-7732 ePBS lifecycle (cross-cuts item #7 H10 for the attestation-time builder-payment weight tracking).

The hypothesis: *all six clients implement the Pectra cutover and three new dispatchers identically (H1–H9), and at the Glamsterdam target all six implement the Gloas restructure: remove the three request dispatchers from `process_operations` (delegating to `apply_parent_execution_payload`) and add the new `process_payload_attestation` dispatcher (H10).*

**Consensus relevance**: this is the FAN-OUT root of every block-level operation. A divergence here would cascade into every downstream operation's surface. With H10 now uniform, the dispatch shape is consistent across all six clients on every Gloas-slot block.

## Hypotheses

- **H1.** `eth1_deposit_index_limit = min(state.eth1_data.deposit_count, state.deposit_requests_start_index)` — using `min` (NOT `max` or just one of the two).
- **H2.** `state.deposit_requests_start_index = UNSET (= 2^64 - 1)` keeps legacy mode active because `min(N, 2^64-1) = N`.
- **H3.** Branch 1: `state.eth1_deposit_index < limit` requires `len(body.deposits) == min(MAX_DEPOSITS = 16, limit - state.eth1_deposit_index)`.
- **H4.** Branch 2: `state.eth1_deposit_index >= limit` requires `len(body.deposits) == 0` (NOT `<= MAX_DEPOSITS`).
- **H5.** Three new dispatchers in EXACT order: deposits → withdrawals → consolidations (NOT alphabetical, NOT reversed).
- **H6.** Each dispatcher iterates `body.execution_requests.<list>` and calls per-operation processor for each.
- **H7.** Per-list SSZ caps: `MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192`, `MAX_WITHDRAWAL_REQUESTS_PER_PAYLOAD = 16`, `MAX_CONSOLIDATION_REQUESTS_PER_PAYLOAD = 2` (mainnet).
- **H8.** The three new dispatchers run AFTER all the legacy-Capella operations (proposer_slashings → attester_slashings → attestations → deposits → voluntary_exits → bls_to_execution_changes).
- **H9.** `body.execution_requests` SSZ container has exactly THREE fields (deposits, withdrawals, consolidations), no Phase0 leftovers.
- **H10** *(Glamsterdam target — Gloas EIP-7732 restructure)*. At the Gloas fork gate, `process_operations` (a) **removes** the three request dispatchers (deposit_request, withdrawal_request, consolidation_request) — they relocate to `apply_parent_execution_payload`; and (b) **adds** a new dispatcher `for_ops(body.payload_attestations, process_payload_attestation)`. The other legacy-Capella operations (proposer_slashings, attester_slashings, attestations, deposits, voluntary_exits, bls_to_execution_changes) remain in place.

## Findings

H1–H10 satisfied across all six clients at the current Glamsterdam-target pins. The Pectra-surface bits (H1–H9) align on body shape; the Gloas-target H10 is implemented by all six clients via six distinct dispatch idioms.

### prysm

`vendor/prysm/beacon-chain/core/transition/electra.go:23-124` — `electraOperations`. Cutover in `vendor/prysm/beacon-chain/core/electra/transition.go:134-151` (`VerifyBlockDepositLength`). Three sequential `for _, X := range requests.Deposits/Withdrawals/Consolidations` loops with per-element nil-checks.

**H10 dispatch (separate Gloas dispatcher).** `vendor/prysm/beacon-chain/core/transition/gloas.go` hosts `gloasOperations` — a separate Gloas-specific dispatcher invoked from the Gloas-fork transition path. It (a) runs the legacy-Capella operations and the EIP-6110 cutover, (b) does NOT call the three request dispatchers (they're handled in `gloas.go`'s `apply_parent_execution_payload` analog), and (c) dispatches `process_payload_attestation` for `body.payload_attestations`. The dedicated test file `vendor/prysm/beacon-chain/core/transition/gloas_operations_test.go` covers the `ErrProcessPayloadAttestationsFailed` sentinel and other Gloas-only flows.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓**.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:12-71`. The fork-dispatch at the tail of `process_operations` distinguishes Gloas from Electra explicitly:

```rust
if state.fork_name_unchecked().gloas_enabled() {
    process_payload_attestations(
        state,
        block_body.payload_attestations()?.iter(),
        verify_signatures,
        ctxt,
        spec,
    )?;
} else if state.fork_name_unchecked().electra_enabled() {
    state.update_pubkey_cache()?;
    process_deposit_requests_pre_gloas(
        state,
        &block_body.execution_requests()?.deposits,
        spec,
    )?;
    process_withdrawal_requests(state, &block_body.execution_requests()?.withdrawals, spec)?;
    process_consolidation_requests(
        state,
        &block_body.execution_requests()?.consolidations,
        spec,
    )?;
}
```

**H10 dispatch (inline `gloas_enabled()` / `else if electra_enabled()` branch).** At Gloas, `process_payload_attestations` runs and the three Electra request dispatchers are skipped. At Electra-only, the three request dispatchers run. `process_payload_attestation` and `process_payload_attestations` helpers are defined at lines 1213 and 1225 of the same file.

The Gloas-time request dispatch is relocated into `vendor/lighthouse/consensus/state_processing/src/per_block_processing.rs:599-601` (the `apply_parent_execution_payload` analog), where `process_deposit_requests_post_gloas`, `process_withdrawal_requests`, and `process_consolidation_requests` are invoked against the parent payload's execution requests:

```rust
process_operations::process_deposit_requests_post_gloas(state, &requests.deposits, spec)?;
process_operations::process_withdrawal_requests(state, &requests.withdrawals, spec)?;
process_operations::process_consolidation_requests(state, &requests.consolidations, spec)?;
```

The two `process_deposit_requests_pre_gloas` (line 877) / `process_deposit_requests_post_gloas` (line 904) variants split the deposit-request logic for the two call sites.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓**.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/block/BlockProcessorElectra.java:138-149` — Electra `processOperationsNoValidation` override. The cutover at `:168-191` (`verifyOutstandingDepositsAreProcessed`). Three sequential `executionRequestsProcessor.process<X>Requests(state, executionRequests.get<X>())` calls.

**H10 dispatch (Java subclass override).** `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/block/BlockProcessorGloas.java:394-413` overrides `processOperationsNoValidation` to call `super` AND add `processPayloadAttestations`:

```java
@Override
protected void processOperationsNoValidation(
    final MutableBeaconState state, final BeaconBlockBody body, ...) {
  super.processOperationsNoValidation(state, body, ...);
  safelyProcess(
      () -> processPayloadAttestations(state, body.getOptionalPayloadAttestations()...));
}
```

`BlockProcessorGloas` also overrides `processExecutionRequests` to a no-op (lines 430-438), and `processPayloadAttestations` at line 441-447 iterates `payloadAttestations` and dispatches `process_payload_attestation` per entry.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓**.

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:784-872` — `process_operations*`. Cutover at lines 793-815 (`when consensusFork >= ConsensusFork.Electra` block). Three sequential `for op in body.execution_requests.<list>` loops in a `when consensusFork in ConsensusFork.Electra .. ConsensusFork.Fulu` block — explicitly **excluding Gloas**.

**H10 dispatch (compile-time `when typeof(state).kind >= ConsensusFork.Gloas` branch).** At line 205 the dispatcher branches on `when typeof(state).kind >= ConsensusFork.Gloas`; the Gloas branch at lines 875-877 iterates `body.payload_attestations` and dispatches `process_payload_attestation`:

```nim
when typeof(state).kind >= ConsensusFork.Gloas:
  for op in body.payload_attestations:
    ? process_payload_attestation(state, op, cache)
```

`process_payload_attestation*` is defined at line 749. Compile-time fork dispatch via `static ConsensusFork` parameter ensures the per-fork-set is statically chosen.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓**.

### lodestar

`vendor/lodestar/packages/state-transition/src/block/processOperations.ts:35-95`. Cutover in `vendor/lodestar/packages/state-transition/src/util/deposit.ts:5-22` (`getEth1DepositCount` helper). Three sequential `for (const X of bodyElectra.executionRequests.<list>)` loops gated by `if (fork >= ForkSeq.electra && fork < ForkSeq.gloas)` — **explicitly excluding Gloas**.

**H10 dispatch (runtime fork-range ternary).** At line 90-93:

```typescript
if (fork >= ForkSeq.gloas) {
  for (const payloadAttestation of (body as gloas.BeaconBlockBody).payloadAttestations) {
    processPayloadAttestation(state as CachedBeaconStateGloas, payloadAttestation);
  }
}
```

The fork-gate combination (`>= electra && < gloas` for the three request dispatchers, `>= gloas` for payload attestations) cleanly implements the Gloas restructure.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓**.

### grandine

`vendor/grandine/transition_functions/src/electra/block_processing.rs:488-624` — Pectra `process_operations`; dispatchers actually live in `custom_process_block:193-206` (separated from `process_operations` — a structural divergence preserved from the prior audit).

**H10 dispatch (per-fork module split).** `vendor/grandine/transition_functions/src/gloas/block_processing.rs:701-845 process_operations` is a **separate function** for the Gloas fork. It runs the EIP-6110 cutover (lines 716-740), the legacy operations (proposer_slashings, attester_slashings, attestations, deposits, voluntary_exits, bls_to_execution_changes), and **then** dispatches `body.payload_attestations` to `process_payload_attestation` (line 838-845):

```rust
for payload_attestation in body.payload_attestations() {
    process_payload_attestation(
        config, pubkey_cache, state, payload_attestation, &mut verifier,
    )?;
}
```

Notably, the Gloas `process_operations` does **not** iterate `body.execution_requests.deposits/withdrawals/consolidations` — they're processed in `apply_parent_execution_payload` (Gloas-new helper) instead. `process_payload_attestation` itself is defined at line 1132 of the same file.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓**.

## Cross-reference table

| Client | `process_operations` (Pectra) | Three-dispatcher gate | Gloas restructure (H10) |
|---|---|---|---|
| prysm | `core/transition/electra.go:23-124 electraOperations`; cutover in `core/electra/transition.go:134-151` | Electra-version dispatch via separate `electraOperations` function | ✓ separate Gloas dispatcher (`core/transition/gloas.go gloasOperations` with payload-attestation handling) |
| lighthouse | `per_block_processing/process_operations.rs:12-71`; cutover in `process_deposits` | runtime `gloas_enabled()` / `else if electra_enabled()` branch at `:47-68` | ✓ inline branch (`process_operations.rs:47-54` Gloas `process_payload_attestations`; Gloas request-dispatchers relocated to `per_block_processing.rs:599-601` apply_parent_execution_payload analog) |
| teku | `versions/electra/block/BlockProcessorElectra.java:138-149` (override); cutover at `:168-191` | Subclass-override polymorphism (Electra version) | ✓ Java subclass override (`BlockProcessorGloas.processOperationsNoValidation:394-413`; `processExecutionRequests` no-op at `:430-438`; `processPayloadAttestations` dispatcher at `:441-447`) |
| nimbus | `state_transition_block.nim:784-872`; cutover at `:793-815` | `when consensusFork in ConsensusFork.Electra .. ConsensusFork.Fulu` (excludes Gloas) | ✓ compile-time `when typeof(state).kind >= ConsensusFork.Gloas` branch (`:205` + `:875-877`); `process_payload_attestation*` at `:749` |
| lodestar | `block/processOperations.ts:35-95`; cutover in `util/deposit.ts:5-22` | `if (fork >= ForkSeq.electra && fork < ForkSeq.gloas)` (explicit Gloas exclusion) | ✓ runtime fork-range ternary (`:90-93` `if (fork >= ForkSeq.gloas)` + `processPayloadAttestation` dispatcher) |
| grandine | `electra/block_processing.rs:488-624`; dispatchers at `custom_process_block:193-206` (separated) | per-fork module split | ✓ per-fork module split (`gloas/block_processing.rs:701-845` separate Gloas `process_operations`; no execution_requests dispatchers; `for payload_attestation in body.payload_attestations()` at `:838-845`) |

## Empirical tests

### Pectra-surface fixture status

The dispatcher is exercised indirectly via 280+ EF operations and epoch-processing fixtures from items #2/#3/#4/#5/#6/#7/#8/#9/#12 (all flowing through `process_operations`). Direct fixtures include the **`sanity/blocks/pyspec_tests/deposit_transition__*`** suite (8 fixtures) that exercise the EIP-6110 cutover state machine: `process_eth1_deposits` (pre-cutover, legacy deposits processed), `process_eth1_deposits_up_to_start_index` (cutover boundary), `start_index_is_set` (first DepositRequest sets the start index), `process_max_eth1_deposits` (MAX_DEPOSITS branch), `deposit_and_top_up_same_block` (concurrent legacy + new), `deposit_with_same_pubkey_different_withdrawal_credentials`, `invalid_eth1_deposits_overlap_in_protocol_deposits`, `invalid_not_enough_eth1_deposits`, `invalid_too_many_eth1_deposits`.

Cross-dispatch ordering: `sanity/blocks/pyspec_tests/cl_exit_and_el_withdrawal_request_in_same_block` and `basic_btec_and_el_withdrawal_request_in_same_block` exercise the legacy-Capella ↔ EIP-7685 dispatcher interaction.

**Implicit coverage tally** (cumulative across audited items):

| Source | Fixtures |
|---|---|
| Item #2 consolidation_request | 10 |
| Item #3 withdrawal_request | 19 |
| Item #4 pending_deposits | 43 |
| Item #5 pending_consolidations | 13 |
| Item #6 voluntary_exit | 25 |
| Item #7 attestation | 45 |
| Item #8 attester_slashing | 30 |
| Item #9 proposer_slashing | 15 |
| Item #12 withdrawals | 80 |
| **Total** | **280 fixtures** |

× 4 wired clients = **1120 PASS results** all flowing through `process_operations`. Strongest evidence yet that the Pectra dispatcher is correct across all 6 clients.

### Gloas-surface

No Gloas operations-fixture wiring exists for `process_operations` yet. H10 is currently source-only — confirmed by walking each client's fork-dispatch mechanism.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — Pectra cutover state machine).** Run the existing 8 `sanity/blocks/pyspec_tests/deposit_transition__*` fixtures via the existing harness (already supports `sanity_blocks`/`electra`) — first concrete fixture verification of this dispatcher's behaviour.
- **T1.2 (priority — multi-request-type-same-block ordering).** Block with 1 deposit + 1 withdrawal + 1 consolidation request all targeting the same validator. Test that all 6 clients process in deposit → withdrawal → consolidation order, with state mutations observable in that exact sequence.
- **T1.3 (Glamsterdam-target — Gloas payload_attestation dispatcher).** Gloas state and block with N `payload_attestations`. Expected per Gloas spec: each is dispatched via `process_payload_attestation`, updating `state.execution_payload_availability` and feeding builder-payment weight tracking uniformly across all six clients.

#### T2 — Adversarial probes
- **T2.1 (defensive — sentinel-value transition).** Block N with sentinel `state.deposit_requests_start_index = 2^64 - 1` (no deposit_requests yet) + block N+1 with first DepositRequest → verify the start_index transitions correctly across all 6 clients.
- **T2.2 (defensive — H4 strict branch).** Block with `state.eth1_deposit_index >= eth1_deposit_index_limit` AND `len(body.deposits) > 0` (should be rejected per H4's strict `== 0` assertion). Already covered by `invalid_too_many_eth1_deposits`.
- **T2.3 (Glamsterdam-target — `body.execution_requests` at Gloas).** Gloas state and block where `body.execution_requests` lists are empty (because requests now flow through `apply_parent_execution_payload`). All six clients should skip the three Electra dispatchers at Gloas — verify via state-root equality after a Gloas block with empty execution_requests.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H9) remain satisfied: identical EIP-6110 cutover semantics, three-new-dispatcher ordering, per-list SSZ caps, and preserved legacy-Capella operations. The 280-fixture cumulative coverage across items #2/#3/#4/#5/#6/#7/#8/#9/#12 (1120 PASS results × 4 wired clients) all flow through `process_operations` — strong implicit evidence for the Pectra-surface correctness.

**Glamsterdam-target finding (H10 ✓ across all six clients):** every client implements the Gloas restructure — removing the three Pectra request dispatchers (relocated into `apply_parent_execution_payload`) and adding the new `process_payload_attestation` dispatcher. Six distinct dispatch idioms: prysm uses a separate Gloas dispatcher function (`gloasOperations` in `core/transition/gloas.go`); lighthouse uses an inline `gloas_enabled()` / `else if electra_enabled()` branch in `process_operations.rs:47-68` (with request dispatchers relocated to `per_block_processing.rs:599-601 apply_parent_execution_payload` analog); teku uses Java subclass override polymorphism (`BlockProcessorGloas` overrides `processOperationsNoValidation`, `processExecutionRequests` no-op, adds `processPayloadAttestations`); nimbus uses compile-time `when typeof(state).kind >= ConsensusFork.Gloas`; lodestar uses runtime fork-range ternaries (`>= electra && < gloas` for the three dispatchers, `>= gloas` for payload attestations); grandine uses a per-fork module split with a separate Gloas `process_operations` at `gloas/block_processing.rs:701`.

The earlier finding (H10 lighthouse-only divergence) was a stale-pin artifact. Lighthouse had been on `stable` (v8.1.3), which trailed `unstable` by months of EIP-7732 integration including the entire `process_operations` Gloas restructure. With each client now on the branch where its actual Glamsterdam implementation lives, the cross-client dispatch surface is uniform — including the relocation of the three request dispatchers into the `apply_parent_execution_payload` analog (lighthouse: `per_block_processing.rs:599-601`).

Notable per-client style differences (all observable-equivalent on the Pectra surface):

- **prysm** uses a fully separate Gloas dispatcher (`core/transition/gloas.go gloasOperations`); Pectra `electraOperations` is unchanged.
- **lighthouse** uses a single function with explicit runtime fork-branch (`gloas_enabled()` / `else if electra_enabled()`); the three request dispatchers are split into `_pre_gloas` and `_post_gloas` variants (deposits only; the withdrawal/consolidation versions are shared) and relocated to the apply_parent_execution_payload call site for the Gloas path.
- **teku** uses subclass-override polymorphism — `BlockProcessorGloas extends BlockProcessorElectra` cleanly overrides `processOperationsNoValidation`, `processExecutionRequests`, and `processPayloadAttestations`.
- **nimbus** uses compile-time `when typeof(state).kind` dispatch with explicit fork-range matching (`Electra .. Fulu` for the three Electra dispatchers, `>= Gloas` for payload attestations).
- **lodestar** uses runtime `fork >= ForkSeq.X` gates with explicit `< ForkSeq.gloas` exclusion on the Electra dispatchers.
- **grandine** uses per-fork module split — `gloas/block_processing.rs:701` is a separate `process_operations` for the Gloas fork. The dispatcher decoupling pattern (`custom_process_block` for Pectra) does not persist into Gloas; the Gloas `process_operations` calls `process_payload_attestation` directly.

Recommendations to the harness and the audit:

- Generate **T1.3 (Gloas payload_attestation dispatcher) fixture** — sister to items #7 T2.6, #9 T1.3, #12 T1.3. Convert the source-only H10 conclusion into empirically-pinned.
- **Run the existing 8 `deposit_transition__*` sanity_blocks fixtures** via the existing harness — first concrete fixture verification of the Pectra surface.
- **Audit `process_deposit_request` (EIP-6110)** as a standalone item — the only major Pectra operation not yet audited.
- **Audit `requestsHash`** (the SSZ-encoded requests list passed to EL via NewPayloadV4) — cross-client hash parity. High-priority because divergence would cause an EL fork.

## Cross-cuts

### With items #2 / #3 / #4 (Gloas-relocated request dispatchers)

Items #2 (consolidation), #3 (withdrawal), #4 (deposit) requests are no longer dispatched from `process_operations` at Gloas — they relocate to `apply_parent_execution_payload`. The H10 finding here is the dispatcher-level mirror of items #2 H6, #3 H8, #4 H8 (which observed the EIP-8061 churn-helper cascade in the relocated request processors). With items #2 / #3 / #4 all now vacated on their H6/H8/H8 axes AND this item's H10 also vacated, the entire dispatcher-and-cascade family is uniform across all six clients at Gloas.

### With item #7 H10 (Gloas attestation processing for builder weight)

Item #7 H10 establishes that at Gloas, `process_attestation` updates `state.builder_pending_payments[*].weight` for same-slot attestations with new participation flags. This item's H10 establishes that at Gloas, `process_operations` dispatches `payload_attestations` to `process_payload_attestation`, which updates `state.execution_payload_availability`. Both are now uniform across all six clients; the EIP-7732 ePBS lifecycle's upstream (weight + availability) is symmetric.

### With item #12 H11 (Gloas withdrawal phases for builder drain)

Item #12 H11 establishes that at Gloas, `process_withdrawals` drains `state.builder_pending_withdrawals` (Phase A) and `state.builders` (Phase C). Combined with item #7 H10 and this item's H10, the entire EIP-7732 ePBS lifecycle (payment-weight-in, availability-in, and payments-out) is uniform across all six clients.

### With item #11 (`upgrade_to_electra`)

`upgrade_to_electra` initialises `state.deposit_requests_start_index = UNSET = 2^64 - 1`. This item is the first to consume it: the `min(deposit_count, start_index)` cutover formula uses the sentinel value to keep legacy mode active until the first `DepositRequest` arrives. Cross-cut chain: item #11 sets the sentinel → item #13 reads it for the cutover → `process_deposit_request` writes the first non-sentinel value on first invocation (sentinel transition) → item #13's branch flip kicks in permanently.

### With item #11's sister `upgrade_to_gloas`

`upgrade_to_gloas` seeds `state.builder_pending_payments`, `state.builder_pending_withdrawals`, `state.builders`, `state.execution_payload_availability`. All four are now read+mutated from the per_block_processing layers across all six clients (item #7 H10 reads/writes builder_pending_payments; item #12 H11 reads/writes builder_pending_withdrawals + builders; this item's H10 reads/writes execution_payload_availability via process_payload_attestation; item #9 H9 clears builder_pending_payments on proposer slashing). The state-allocation step in upgrade_to_gloas is matched by per-block consumption across the audit family.

## Adjacent untouched Electra/Gloas-active consensus paths

1. **`process_deposit_request` (EIP-6110)** — the only major Pectra operation NOT yet audited as a standalone item. Sets the `deposit_requests_start_index` sentinel transition on first invocation.
2. **`requestsHash` Merkleization passed to EL via NewPayloadV4** — `sha256(get_execution_requests_list(...))`. Cross-client hash mismatch would diverge at the EL boundary. **High-priority** audit candidate.
3. **`get_execution_requests_list` encoding helper** — SSZ serialization + type-byte prefix of the three request lists, filtering empty lists.
4. **`apply_parent_execution_payload` (Gloas-new, EIP-7732)** — the relocation target for the three Pectra request dispatchers. Consumes `parent_payload.execution_requests` at the child's slot. Audit-worthy as its own item once it's the focus.
5. **`process_payload_attestation` (Gloas-new, EIP-7732)** — the new dispatcher's target. Updates `state.execution_payload_availability` per attestation. Sister audit item.
6. **Lighthouse's `update_pubkey_cache()?` before the dispatchers** (now in the Electra-only branch at `process_operations.rs:56`) — necessary because `process_deposit_request` can add new validators with new pubkeys; the cache must be ready.
7. **prysm's per-element nil-checks** (`if d == nil`) — defensive against proto-level malformation.
8. **`MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192` is HUGE** vs `MAX_WITHDRAWAL_REQUESTS_PER_PAYLOAD = 16` and `MAX_CONSOLIDATION_REQUESTS_PER_PAYLOAD = 2`. Verify SSZ deserialization rejects 8193+ deposits cleanly.
9. **`UNSET_DEPOSIT_REQUESTS_START_INDEX = 2^64 - 1` sentinel transition timing** — the FIRST `DepositRequest` in any block AFTER the Pectra activation sets this field.
10. **Lighthouse's two `process_deposit_requests_{pre,post}_gloas` variants** — clean split that decouples the Electra-time and Gloas-time call sites without a fork-gate inside the helper itself. Worth flagging as the cleanest factoring of the dual call-site requirement.
11. **Multi-request-type-same-block ordering** — block with 1 deposit + 1 withdrawal + 1 consolidation request. Verify all 6 clients agree at Pectra (covered by 280 implicit fixtures); at Gloas, the same ordering moves to `apply_parent_execution_payload`.
12. **Six-dispatch-idiom uniformity for Gloas restructure** — H10 is now another clean example of how the six clients converge on identical observable Gloas semantics through six different idioms (separate function / inline branch / Java override / `when` / runtime ternary / per-fork module split).
