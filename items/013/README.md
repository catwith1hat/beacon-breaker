---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-12
builds_on: [2, 3, 6, 7, 8, 9, 11, 12]
eips: [EIP-6110, EIP-7685, EIP-7732]
splits: [lighthouse]
# main_md_summary: lighthouse has not implemented the Gloas EIP-7732 `process_operations` restructure — still calls the three request dispatchers (gated only by `electra_enabled()` which fires at Gloas too) and lacks the new `process_payload_attestation` dispatcher
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.3
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.3.1
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 13: `process_operations` Pectra dispatcher (EIP-6110 cutover + EIP-7685 requests routing)

## Summary

`process_operations` is the **block-body fan-out** function that dispatches each operation list to its per-operation processor. Pectra adds two distinct modifications: (1) **EIP-6110 legacy-deposit cutover** at the head of the function (`eth1_deposit_index_limit = min(state.eth1_data.deposit_count, state.deposit_requests_start_index)`; legacy deposits drain to the limit then disable permanently); (2) **EIP-7685 three new request dispatchers** at the tail (`for_ops(body.execution_requests.deposits/withdrawals/consolidations, process_X_request)` in that exact order).

**Pectra surface (the function body itself):** all six clients implement the `min` cutover predicate, the conditional `len(body.deposits)` assertions, the three-new-dispatcher ordering, and the per-list SSZ caps identically. The dispatcher is exercised indirectly via the cumulative 280+ EF fixtures from items #2/#3/#4/#5/#6/#7/#8/#9/#12 — all flowing through `process_operations`. The `sanity/blocks/pyspec_tests/deposit_transition__*` fixtures (8 fixtures) directly test the EIP-6110 cutover state machine; the harness wiring is available but not yet routed at audit time.

**Gloas surface (new at the Glamsterdam target):** Gloas (EIP-7732 ePBS) heavily modifies `process_operations` per `vendor/consensus-specs/specs/gloas/beacon-chain.md:1478-1518` "Modified `process_operations`". The Note explicitly states: *"`process_operations` is modified to process PTC attestations and removes calls to `process_deposit_request`, `process_withdrawal_request`, and `process_consolidation_request`."* The three Pectra request dispatchers are **removed** (relocated into the Gloas-new `apply_parent_execution_payload` helper — items #2/#3/#4 cross-cuts), and a new dispatcher `for_ops(body.payload_attestations, process_payload_attestation)` is added.

Survey of all six clients: prysm, teku, nimbus, lodestar, grandine all implement both changes at Gloas; **lighthouse does not** — its `consensus/state_processing/src/per_block_processing/process_operations.rs:40-53` gates the three request dispatchers behind `state.fork_name_unchecked().electra_enabled()`, which returns true for Gloas (it's true for any fork ≥ Electra), so the Electra dispatchers continue to fire at Gloas. Additionally, lighthouse has no `process_payload_attestation` caller anywhere in `consensus/state_processing/src/`. Same lone-laggard 1-vs-5 pattern as items #7 (`process_attestation`) and #12 (`process_withdrawals`) — lighthouse is the laggard on all three EIP-7732 ePBS-related items.

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

The three request dispatchers are relocated into the Gloas-new helper `apply_parent_execution_payload` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1106-1180`), invoked from `process_parent_execution_payload` — they now run against the **parent's** execution payload requests at the **child's** slot, not against the current block's body. This is the same restructuring observed by items #2 (consolidation requests), #3 (withdrawal requests), and #4 (deposit requests) in their respective Gloas-cross-cut sections. The new `process_payload_attestation` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1670+`) processes the new `body.payload_attestations` operations list and is part of the EIP-7732 ePBS lifecycle (cross-cuts item #7 H10 for the attestation-time builder-payment weight tracking).

The hypothesis: *all six clients implement the Pectra cutover and three new dispatchers identically (H1–H9), and at the Glamsterdam target all six implement the Gloas restructure: remove the three request dispatchers from `process_operations` (delegating to `apply_parent_execution_payload`) and add the new `process_payload_attestation` dispatcher (H10).*

**Consensus relevance**: this is the FAN-OUT root of every block-level operation. A divergence here cascades into every downstream operation's surface. At Gloas, a client that fails to remove the three request dispatchers from `process_operations` would either (a) double-process requests (if `apply_parent_execution_payload` ALSO ran, but it doesn't on a non-Gloas-aware client), (b) silently no-op on empty `body.execution_requests` at Gloas (if the SSZ container is empty at Gloas), or (c) silently process the wrong requests (if `body.execution_requests` carries old-format data). A client that fails to add the `process_payload_attestation` dispatcher misses every payload attestation in every Gloas-slot block, breaking the EIP-7732 builder-payment lifecycle alongside item #7 H10.

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

H1–H9 satisfied for the Pectra surface. **H10 fails for lighthouse alone**. Five clients (prysm, teku, nimbus, lodestar, grandine) implement both the removal and the new dispatcher at Gloas.

### prysm

`vendor/prysm/beacon-chain/core/transition/electra.go:23-124` — `electraOperations`. Cutover in `vendor/prysm/beacon-chain/core/electra/transition.go:134-151` (`VerifyBlockDepositLength`). Three sequential `for _, X := range requests.Deposits/Withdrawals/Consolidations` loops with per-element nil-checks.

**Gloas-specific path (H10 ✓)**: `vendor/prysm/beacon-chain/core/transition/gloas.go` hosts `gloasOperations` — a separate Gloas-specific dispatcher invoked from the Gloas-fork transition path. It (a) runs the legacy-Capella operations and the EIP-6110 cutover, (b) does NOT call the three request dispatchers (they're handled in `gloas.go`'s `apply_parent_execution_payload` analog), and (c) dispatches `process_payload_attestation` for `body.payload_attestations`. The dedicated test file `vendor/prysm/beacon-chain/core/transition/gloas_operations_test.go` covers the `ErrProcessPayloadAttestationsFailed` sentinel and other Gloas-only flows.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓**.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:12-53`. The three new dispatchers are gated by `state.fork_name_unchecked().electra_enabled()`:

```rust
if state.fork_name_unchecked().electra_enabled() {
    state.update_pubkey_cache()?;
    process_deposit_requests(state, &block_body.execution_requests()?.deposits, spec)?;
    process_withdrawal_requests(state, &block_body.execution_requests()?.withdrawals, spec)?;
    process_consolidation_requests(
        state,
        &block_body.execution_requests()?.consolidations,
        spec,
    )?;
}
```

**`electra_enabled()` returns true for ANY fork ≥ Electra**, including Gloas. So at Gloas, lighthouse continues to invoke the three request dispatchers from `body.execution_requests` (Electra path). There is no Gloas-fork gate that removes them.

**No `process_payload_attestation` dispatcher anywhere in `consensus/state_processing/src/`**: zero references to `process_payload_attestation` / `payload_attestations` outside the `consensus/types/src/` SSZ container definitions. At Gloas, lighthouse never processes the new `body.payload_attestations` list.

Cross-cut implications:
- Item #7 H10 (builder-payment weight tracking from attestations) — already broken on lighthouse.
- This item H10 (payload-attestation dispatcher) — also broken on lighthouse.
- Item #12 H11 (Gloas withdrawal phases) — also broken on lighthouse.

All three are EIP-7732 ePBS lifecycle gaps in lighthouse's per_block_processing.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✗** (Electra gate fires at Gloas; no payload_attestation dispatcher).

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/block/BlockProcessorElectra.java:138-149` — Electra `processOperationsNoValidation` override. The cutover at `:168-191` (`verifyOutstandingDepositsAreProcessed`). Three sequential `executionRequestsProcessor.process<X>Requests(state, executionRequests.get<X>())` calls.

**Gloas-specific path (H10 ✓)**: `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/block/BlockProcessorGloas.java:394-413` overrides `processOperationsNoValidation` to call `super` AND add `processPayloadAttestations`:

```java
@Override
protected void processOperationsNoValidation(
    final MutableBeaconState state, final BeaconBlockBody body, ...) {
  super.processOperationsNoValidation(state, body, ...);
  safelyProcess(
      () -> processPayloadAttestations(state, body.getOptionalPayloadAttestations()...));
}
```

`BlockProcessorGloas` also overrides `processExecutionRequests` to a no-op (lines 430-438):

```java
@Override
public void processExecutionRequests(...) {
    // Execution requests are removed from the BeaconBlockBody in Gloas and are instead processed as
    // part of process_execution_payload
}
```

`processPayloadAttestations` at line 441-447 iterates `payloadAttestations` and dispatches `process_payload_attestation` per entry.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** (clean override: `processExecutionRequests` no-op + `processPayloadAttestations` dispatcher).

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:784-872` — `process_operations*`. Cutover at lines 793-815 (`when consensusFork >= ConsensusFork.Electra` block). Three sequential `for op in body.execution_requests.<list>` loops in a `when consensusFork in ConsensusFork.Electra .. ConsensusFork.Fulu` block — explicitly **excluding Gloas**.

**Gloas-specific path (H10 ✓)**: at line 205 the dispatcher branches on `when typeof(state).kind >= ConsensusFork.Gloas`; the Gloas branch at lines 875-877 iterates `body.payload_attestations` and dispatches `process_payload_attestation`:

```nim
when typeof(state).kind >= ConsensusFork.Gloas:
  for op in body.payload_attestations:
    ? process_payload_attestation(state, op, cache)
```

`process_payload_attestation*` is defined at line 749. Compile-time fork dispatch via `static ConsensusFork` parameter ensures the per-fork-set is statically chosen.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓**.

### lodestar

`vendor/lodestar/packages/state-transition/src/block/processOperations.ts:35-95`. Cutover in `vendor/lodestar/packages/state-transition/src/util/deposit.ts:5-22` (`getEth1DepositCount` helper). Three sequential `for (const X of bodyElectra.executionRequests.<list>)` loops gated by `if (fork >= ForkSeq.electra && fork < ForkSeq.gloas)` — **explicitly excluding Gloas**.

**Gloas-specific path (H10 ✓)**: at line 90-93:

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

**Gloas-specific path (H10 ✓)**: `vendor/grandine/transition_functions/src/gloas/block_processing.rs:701-845 process_operations` is a **separate function** for the Gloas fork. It runs the EIP-6110 cutover (lines 716-740), the legacy operations (proposer_slashings, attester_slashings, attestations, deposits, voluntary_exits, bls_to_execution_changes), and **then** dispatches `body.payload_attestations` to `process_payload_attestation` (line 838-845):

```rust
for payload_attestation in body.payload_attestations() {
    process_payload_attestation(
        config, pubkey_cache, state, payload_attestation, &mut verifier,
    )?;
}
```

Notably, the Gloas `process_operations` does **not** iterate `body.execution_requests.deposits/withdrawals/consolidations` — they're processed in `apply_parent_execution_payload` (Gloas-new helper) instead. `process_payload_attestation` itself is defined at line 1132 of the same file.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** (per-fork module split with Gloas-specific `process_operations`).

## Cross-reference table

| Client | `process_operations` (Pectra) | Three-dispatcher gate | Gloas restructure (H10) |
|---|---|---|---|
| prysm | `core/transition/electra.go:23-124 electraOperations`; cutover in `core/electra/transition.go:134-151` | Electra-version dispatch via separate `electraOperations` function | **✓** (`core/transition/gloas.go gloasOperations` — separate Gloas-specific dispatcher with payload-attestation handling) |
| lighthouse | `per_block_processing/process_operations.rs:12-53`; cutover in `process_deposits():363-391` | `state.fork_name_unchecked().electra_enabled()` (line 40) | **✗** (`electra_enabled()` returns true for Gloas; the three dispatchers continue to fire; no `process_payload_attestation` caller anywhere in `consensus/state_processing/src/`) |
| teku | `versions/electra/block/BlockProcessorElectra.java:138-149` (override); cutover at `:168-191` | Subclass-override polymorphism (Electra version) | **✓** (`BlockProcessorGloas.processOperationsNoValidation:394-413` overrides; `processExecutionRequests` no-op at line 430-438; `processPayloadAttestations` dispatcher at line 441-447) |
| nimbus | `state_transition_block.nim:784-872`; cutover at `:793-815` | `when consensusFork in ConsensusFork.Electra .. ConsensusFork.Fulu` (excludes Gloas) | **✓** (line 205 `when typeof(state).kind >= ConsensusFork.Gloas`; line 875-877 `for op in body.payload_attestations: process_payload_attestation`) |
| lodestar | `block/processOperations.ts:35-95`; cutover in `util/deposit.ts:5-22` | `if (fork >= ForkSeq.electra && fork < ForkSeq.gloas)` (explicit Gloas exclusion) | **✓** (line 90-93 `if (fork >= ForkSeq.gloas)` + `processPayloadAttestation` dispatcher) |
| grandine | `electra/block_processing.rs:488-624`; dispatchers at `custom_process_block:193-206` (separated) | per-fork module split | **✓** (`gloas/block_processing.rs:701-845` separate Gloas `process_operations`; no execution_requests dispatchers; `for payload_attestation in body.payload_attestations()` at line 838-845) |

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

No Gloas operations-fixture wiring exists for `process_operations` yet. H10 is currently source-only — confirmed by walking each client's fork-dispatch mechanism. The cross-cut chain for the EIP-7732 ePBS lifecycle (item #7 H10 builder-payment weight + item #12 H11 builder-withdrawals + this item H10 payload-attestation dispatcher) all converge on lighthouse as the lone laggard.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — Pectra cutover state machine).** Run the existing 8 `sanity/blocks/pyspec_tests/deposit_transition__*` fixtures via the existing harness (already supports `sanity_blocks`/`electra`) — first concrete fixture verification of this dispatcher's behaviour.
- **T1.2 (priority — multi-request-type-same-block ordering).** Block with 1 deposit + 1 withdrawal + 1 consolidation request all targeting the same validator. Test that all 6 clients process in deposit → withdrawal → consolidation order, with state mutations observable in that exact sequence.
- **T1.3 (Glamsterdam-target — Gloas payload_attestation dispatcher).** Gloas state and block with N `payload_attestations`. Expected per Gloas spec: each is dispatched via `process_payload_attestation`, updating `state.execution_payload_availability` and feeding builder-payment weight tracking. Lighthouse will process zero payload attestations; the other five will process all N. State-root divergence on every Gloas-slot block containing any payload attestations.

#### T2 — Adversarial probes
- **T2.1 (defensive — sentinel-value transition).** Block N with sentinel `state.deposit_requests_start_index = 2^64 - 1` (no deposit_requests yet) + block N+1 with first DepositRequest → verify the start_index transitions correctly across all 6 clients.
- **T2.2 (defensive — H4 strict branch).** Block with `state.eth1_deposit_index >= eth1_deposit_index_limit` AND `len(body.deposits) > 0` (should be rejected per H4's strict `== 0` assertion). Already covered by `invalid_too_many_eth1_deposits`.
- **T2.3 (Glamsterdam-target — `body.execution_requests` at Gloas).** Gloas state and block where `body.execution_requests` lists are empty (because requests now flow through `apply_parent_execution_payload`). On lighthouse the Electra dispatchers fire on empty lists (no-op). On the other five, the dispatchers are explicitly skipped at Gloas. Both produce equivalent state mutation **on empty input**, BUT the lighthouse path also fails to process `body.payload_attestations`. Useful as the minimal regression vector that isolates the H10 absence on lighthouse.
- **T2.4 (Glamsterdam-target — `body.execution_requests` non-empty at Gloas).** Hypothetical (probably impossible if SSZ container is empty by construction at Gloas): if `body.execution_requests` were populated at Gloas, lighthouse would double-process them once apply_parent_execution_payload is properly implemented. Currently academic; pre-emptive regression vector.

## Mainnet reachability

**Reachable on canonical traffic at Glamsterdam activation, on every Gloas-slot block that contains any payload attestations** (which is essentially every Gloas block — payload attestations are how the chain reaches consensus on whether the parent slot's builder delivered its payload, so they appear on every canonical slot).

**Trigger.** The first Gloas-slot block carrying any `payload_attestations` in `body.payload_attestations`. Per the Gloas spec (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1517`), the new dispatcher `for_ops(body.payload_attestations, process_payload_attestation)` is the last operation in `process_operations`. On lighthouse, the dispatcher is never invoked — the Electra `process_operations` returns after the three (Electra-gate-fires-at-Gloas) request dispatchers and the legacy-Capella operations. On prysm, teku, nimbus, lodestar, grandine, the dispatcher iterates the list and calls `process_payload_attestation` per entry, which mutates `state.execution_payload_availability` and feeds builder-payment weight tracking (item #7 H10).

**Severity.** State-root divergence on every Gloas-slot block. Compounds with item #7 H10 and item #12 H11 — lighthouse has three independent EIP-7732 ePBS lifecycle gaps that all materialise immediately at Gloas activation:

1. **item #7 H10**: builder-pending-payment weight not incremented from attestations.
2. **item #12 H11**: builder-pending-withdrawals and builders not drained into Withdrawal entries.
3. **this item H10**: payload_attestations not dispatched (state.execution_payload_availability not updated).

All three together break the entire EIP-7732 ePBS pipeline on lighthouse. Mainnet at Glamsterdam activation forks lighthouse off from block 1.

**Mitigation window.** Source-only at audit time; no Gloas EF operations fixtures yet for this routine. Closing requires lighthouse to:

1. Change the gate at `process_operations.rs:40` from `electra_enabled()` to a tighter `electra_enabled() && !gloas_enabled()` predicate (or add an `else if gloas_enabled()` branch that skips the three request dispatchers and adds the payload_attestation dispatcher).
2. Add a `process_payload_attestation` helper in `consensus/state_processing/src/per_block_processing/` that mutates `state.execution_payload_availability` per the Gloas spec.
3. Wire `process_payload_attestation` into the Gloas branch.

Reference implementations: prysm's `core/gloas/payload_attestation.go` (Go), teku's `BlockProcessorGloas.processPayloadAttestations` + `processExecutionRequests` no-op override (Java), nimbus's `state_transition_block.nim:749 process_payload_attestation*` + `:875-877` dispatcher (Nim), lodestar's `processPayloadAttestation.ts` + the `fork >= ForkSeq.gloas` branch in `processOperations.ts:90` (TypeScript), grandine's `gloas/block_processing.rs:701-845 process_operations` + `:1132 process_payload_attestation` (Rust).

Same coordinated fix-PR scope as items #7 H10 and #12 H11 — all three lighthouse-only EIP-7732 gaps could close together.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H9) remain satisfied: identical EIP-6110 cutover semantics, three-new-dispatcher ordering, per-list SSZ caps, and preserved legacy-Capella operations. The 280-fixture cumulative coverage across items #2/#3/#4/#5/#6/#7/#8/#9/#12 (1120 PASS results × 4 wired clients) all flow through `process_operations` — strong implicit evidence for the Pectra-surface correctness.

**Glamsterdam-target finding (H10):** the Gloas-modified `process_operations` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1478-1518`) removes the three Pectra request dispatchers (relocated into `apply_parent_execution_payload`) and adds the new `process_payload_attestation` dispatcher. Five clients implement both changes: prysm (`gloasOperations` in a separate `core/transition/gloas.go`), teku (`BlockProcessorGloas.processOperationsNoValidation` override + `processExecutionRequests` no-op + `processPayloadAttestations` added), nimbus (`when typeof(state).kind >= ConsensusFork.Gloas` block + `process_payload_attestation*`), lodestar (`fork >= ForkSeq.electra && fork < ForkSeq.gloas` gate on the three dispatchers + `fork >= ForkSeq.gloas` branch for payload attestations), grandine (per-fork module split with a separate Gloas `process_operations` at `gloas/block_processing.rs:701`). **Lighthouse fails on both axes** — `process_operations.rs:40` gates the three dispatchers behind `electra_enabled()` which fires at Gloas too; and `consensus/state_processing/src/` contains zero `process_payload_attestation` callers.

**Third lighthouse-only 1-vs-5 split** in the EIP-7732 ePBS lifecycle:

| Item | Hypothesis | Surface |
|---|---|---|
| #7 | H10 | Gloas `process_attestation` builder-payment weight increment |
| #12 | H11 | Gloas `process_withdrawals` builder phases (drain + sweep) |
| **#13** | **H10** | Gloas `process_operations` payload-attestation dispatcher + request-dispatcher removal |

Plus the cross-cut item #9 H9 (Gloas `process_proposer_slashing` BuilderPendingPayment clearing — also lighthouse-only). The complete EIP-7732 builder-lifecycle is broken on lighthouse at four points; a single coordinated PR scope could close all four.

Notable per-client style differences (all observable-equivalent on the Pectra surface):

- **prysm** uses a fully separate Gloas dispatcher (`core/transition/gloas.go gloasOperations`); Pectra `electraOperations` is unchanged.
- **lighthouse** uses a single fork-keyed function with `electra_enabled()` predicates that fail to distinguish Electra from Gloas; no Gloas-specific code path at all in `per_block_processing/`.
- **teku** uses subclass-override polymorphism — `BlockProcessorGloas extends BlockProcessorElectra` cleanly overrides `processOperationsNoValidation`, `processExecutionRequests`, and `processPayloadAttestations`.
- **nimbus** uses compile-time `when typeof(state).kind` dispatch with explicit fork-range matching (`Electra .. Fulu` for the three Electra dispatchers, `>= Gloas` for payload attestations).
- **lodestar** uses runtime `fork >= ForkSeq.X` gates with explicit `< ForkSeq.gloas` exclusion on the Electra dispatchers.
- **grandine** uses per-fork module split — `gloas/block_processing.rs:701` is a separate `process_operations` for the Gloas fork. The dispatcher decoupling pattern (`custom_process_block` for Pectra) does not persist into Gloas; the Gloas `process_operations` calls `process_payload_attestation` directly.

Recommendations to the harness and the audit:

- Generate **T1.3 (Gloas payload_attestation dispatcher) fixture** — sister to items #7 T2.6, #9 T1.3, #12 T1.3. Lighthouse-specific; the other five clients should pass.
- File a coordinated PR against lighthouse to (a) tighten the `electra_enabled()` gate at `process_operations.rs:40` to exclude Gloas, (b) add a `process_payload_attestation` helper in `consensus/state_processing/src/per_block_processing/`, (c) wire it into a new Gloas-fork branch. The fix has natural shared scope with items #7 H10, #9 H9, and #12 H11.
- **Run the existing 8 `deposit_transition__*` sanity_blocks fixtures** via the existing harness — first concrete fixture verification of the Pectra surface.
- **Audit `process_deposit_request` (EIP-6110)** as a standalone item — the only major Pectra operation not yet audited.
- **Audit `requestsHash`** (the SSZ-encoded requests list passed to EL via NewPayloadV4) — cross-client hash parity. High-priority because divergence would cause an EL fork.

## Cross-cuts

### With items #2 / #3 / #4 (Gloas-relocated request dispatchers)

Items #2 (consolidation), #3 (withdrawal), #4 (deposit) requests are no longer dispatched from `process_operations` at Gloas — they relocate to `apply_parent_execution_payload`. The H10 finding here is the dispatcher-level mirror of items #2 H6, #3 H8, #4 H8 (which observed the EIP-8061 churn-helper cascade in the relocated request processors). Removing the dispatchers from `process_operations` at Gloas is a precondition for those Gloas-target findings to materialise correctly. Lighthouse's failure to remove the dispatchers means that at Gloas, lighthouse runs the request processors twice in some configurations (or zero times if `body.execution_requests` is empty at Gloas — which appears to be the case per SSZ container shape).

### With item #7 H10 (Gloas attestation processing for builder weight)

Item #7 H10 establishes that at Gloas, `process_attestation` updates `state.builder_pending_payments[*].weight` for same-slot attestations with new participation flags. Lighthouse fails to wire this. This item's H10 establishes that at Gloas, `process_operations` dispatches `payload_attestations` to `process_payload_attestation`, which updates `state.execution_payload_availability`. Lighthouse fails to wire this too. Combined: both builder-payment inputs (weight from attestations + availability from payload attestations) are broken on lighthouse, breaking the upstream side of the EIP-7732 ePBS lifecycle.

### With item #12 H11 (Gloas withdrawal phases for builder drain)

Item #12 H11 establishes that at Gloas, `process_withdrawals` drains `state.builder_pending_withdrawals` (Phase A) and `state.builders` (Phase C). Lighthouse fails to wire these. Together with item #7 H10 and this item's H10, lighthouse breaks all three sides of the EIP-7732 ePBS lifecycle: payment-weight-in (item #7), availability-in (item #13), and payments-out (item #12).

### With item #11 (`upgrade_to_electra`)

`upgrade_to_electra` initialises `state.deposit_requests_start_index = UNSET = 2^64 - 1`. This item is the first to consume it: the `min(deposit_count, start_index)` cutover formula uses the sentinel value to keep legacy mode active until the first `DepositRequest` arrives. Cross-cut chain: item #11 sets the sentinel → item #13 reads it for the cutover → `process_deposit_request` writes the first non-sentinel value on first invocation (sentinel transition) → item #13's branch flip kicks in permanently.

### With item #11's sister `upgrade_to_gloas`

Lighthouse's failure to implement the Gloas-modified `process_operations` is one of several Gloas-readiness gaps. The sister item `upgrade_to_gloas` (flagged in item #11's recheck) seeds `state.builder_pending_payments`, `state.builder_pending_withdrawals`, `state.builders`, `state.execution_payload_availability` — but lighthouse's per_block_processing never reads or mutates the first three (item #7 H10, item #12 H11) and never reads or mutates the fourth (this item H10 + the consumer at item #7's `process_attestation`).

## Adjacent untouched Electra/Gloas-active consensus paths

1. **`process_deposit_request` (EIP-6110)** — the only major Pectra operation NOT yet audited as a standalone item. Sets the `deposit_requests_start_index` sentinel transition on first invocation.
2. **`requestsHash` Merkleization passed to EL via NewPayloadV4** — `sha256(get_execution_requests_list(...))`. Cross-client hash mismatch would diverge at the EL boundary. **High-priority** audit candidate.
3. **`get_execution_requests_list` encoding helper** — SSZ serialization + type-byte prefix of the three request lists, filtering empty lists.
4. **`apply_parent_execution_payload` (Gloas-new, EIP-7732)** — the relocation target for the three Pectra request dispatchers. Consumes `parent_payload.execution_requests` at the child's slot. Audit-worthy as its own item once it's the focus.
5. **`process_payload_attestation` (Gloas-new, EIP-7732)** — the new dispatcher's target. Updates `state.execution_payload_availability` per attestation. Sister audit item.
6. **Lighthouse's `update_pubkey_cache()?` before the dispatchers** (line 42) — necessary because `process_deposit_request` can add new validators with new pubkeys; the cache must be ready.
7. **prysm's per-element nil-checks** (`if d == nil`) — defensive against proto-level malformation.
8. **`MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192` is HUGE** vs `MAX_WITHDRAWAL_REQUESTS_PER_PAYLOAD = 16` and `MAX_CONSOLIDATION_REQUESTS_PER_PAYLOAD = 2`. Verify SSZ deserialization rejects 8193+ deposits cleanly.
9. **`UNSET_DEPOSIT_REQUESTS_START_INDEX = 2^64 - 1` sentinel transition timing** — the FIRST `DepositRequest` in any block AFTER the Pectra activation sets this field.
10. **Lighthouse's `state.deposit_requests_start_index().unwrap_or(u64::MAX)` defensive default** — masks a programming error silently. Same anti-pattern as the orphan `is_attestation_same_slot` (item #7) and orphan `builder_pending_payments` (item #12) — state primitives exist but per_block_processing doesn't use them.
11. **Multi-request-type-same-block ordering** — block with 1 deposit + 1 withdrawal + 1 consolidation request. Verify all 6 clients agree at Pectra (covered by 280 implicit fixtures); at Gloas, the same ordering moves to `apply_parent_execution_payload`.
12. **Lighthouse's three Gloas-readiness gaps in one place** — items #7 H10, #12 H11, #13 H10. All three would benefit from a coordinated PR that touches per_block_processing/{process_operations,process_attestation,process_withdrawals}.rs together. Plus item #9 H9 (BuilderPendingPayment clearing on proposer slash) — four lighthouse-only EIP-7732 gaps in total.
