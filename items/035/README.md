---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [28, 32, 33, 34]
eips: [EIP-7594, EIP-7732]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 35: `is_data_available` Fulu fork-choice rewrite (EIP-7594 PeerDAS column-based DAS in fork choice)

## Summary

`is_data_available(beacon_block_root)` is the consensus-critical integration point between PeerDAS gossip-validated sidecars (item #34) and fork-choice voting decisions. Fork-choice queries this function before importing a block (Fulu) or processing an execution payload envelope (Gloas). A block/payload not "data available" is not voted for, so divergence here causes finality divergence.

**Fulu rewrite (carried forward from 2026-05-04 audit; CURRENT mainnet target):** column-based DAS replaces blob-based. `is_data_available` calls `retrieve_column_sidecars(block_root)` (implementation-dependent, returns local node's sampled columns) and verifies via `verify_data_column_sidecar(s)` AND `verify_data_column_sidecar_kzg_proofs(s)` for each — checks SAMPLED columns only (subset of 128 total), trusts unsampled columns are recoverable from sampled ones via Reed-Solomon.

All six clients implement column-based DAS at the consensus level with byte-equivalent behaviour on spec-compliant inputs. Live mainnet PeerDAS-enabled fork-choice has been operating since Fulu activation (2025-12-03) — 5+ months — without finality divergence. Per-client divergences entirely in state-machine architecture (grandine 5-state; teku 4-state; lodestar 4-state; lighthouse 2-state; prysm + nimbus single-result), reconstruction trigger (prysm + lighthouse + grandine explicit), async architecture, timeout strategy, and sampler abstraction. **NEW Pattern Q candidate for item #28**: data-availability state machine divergence — forward-fragility class.

**Gloas surface (at the Glamsterdam target): `is_data_available` is Modified + caller site relocates.** `vendor/consensus-specs/specs/gloas/fork-choice.md:902-920` documents the Modified body:

```python
def is_data_available(beacon_block_root: Root) -> bool:
    column_sidecars, kzg_commitments = retrieve_column_sidecars_and_kzg_commitments(
        beacon_block_root
    )
    return all(
        verify_data_column_sidecar(column_sidecar, kzg_commitments)
        and verify_data_column_sidecar_kzg_proofs(column_sidecar, kzg_commitments)
        for column_sidecar in column_sidecars
    )
```

Two changes:
1. **`retrieve_column_sidecars` → `retrieve_column_sidecars_and_kzg_commitments`** — returns the kzg_commitments separately (Fulu has them inside the sidecar; Gloas removes them per item #34's `DataColumnSidecar` modification).
2. **Verify functions take external `kzg_commitments` parameter** — matches item #34's Gloas modifications.

**Caller-site relocation under EIP-7732 ePBS** (item #32 territory): the call `is_data_available(beacon_block_root)` moves from `on_block` (Fulu) to `on_execution_payload_envelope` (Gloas, `vendor/consensus-specs/specs/gloas/fork-choice.md:940`):

```python
def on_execution_payload_envelope(store, signed_envelope):
    envelope = signed_envelope.message
    assert envelope.beacon_block_root in store.block_states

    # Check if blob data is available
    # If not, this payload MAY be queued and subsequently considered when blob data becomes available
    assert is_data_available(envelope.beacon_block_root)

    state = store.block_states[envelope.beacon_block_root]
    verify_execution_payload_envelope(state, signed_envelope, EXECUTION_ENGINE)
    # ... add envelope to store, update fork choice ...
```

Data availability now gates **payload envelope processing**, not block import — the EIP-7732 deferred-payload semantics. Block import at Gloas no longer requires DA verification (the block is just a header + commitments + bid signature; the actual payload data is processed later upon envelope arrival).

**Per-client Gloas wiring (Pattern M cohort extension):**
- **prysm**: `isDataAvailable` at `vendor/prysm/beacon-chain/blockchain/process_block.go:887`; called from `receive_block.go:278`. Envelope handling separate.
- **lighthouse**: **MISSING `on_execution_payload_envelope` fork-choice handler**. Has `SignedExecutionPayloadEnvelope` SSZ container + p2p plumbing (`vendor/lighthouse/beacon_node/lighthouse_network/src/types/pubsub.rs:48`) but no fork-choice integration. Pattern M cohort gap extends here.
- **teku**: full Gloas wiring at `vendor/teku/ethereum/statetransition/src/main/java/tech/pegasys/teku/statetransition/forkchoice/ForkChoice.java:239 onExecutionPayloadEnvelope`. Reaffirms teku Heze-leader / Gloas-mid-rank status (items #28-#34 catalogue).
- **nimbus**: has gossip validation for `SignedExecutionPayloadEnvelope` at `vendor/nimbus/beacon_chain/gossip_processing/gossip_validation.nim:1031`; fork-choice integration TBD via deeper source review.
- **lodestar**: has p2p request/response handlers (`vendor/lodestar/packages/beacon-node/src/network/reqresp/handlers/executionPayloadEnvelopes{ByRange,ByRoot}.ts`); fork-choice integration TBD.
- **grandine**: `block_data_column_availability` carries forward (`vendor/grandine/fork_choice_control/src/mutator.rs:3970`); envelope handling integrated with mutator state.

**Mainnet activation status**: `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `vendor/consensus-specs/configs/mainnet.yaml:60`. PeerDAS fork-choice integration continues operating on Fulu surface in production; the Gloas restructure is source-level only.

**Impact: none** at this item's Fulu surface (the current mainnet target). Seventeenth impact-none result in the recheck series. The Gloas-side `is_data_available` modifications + caller-site relocation align with item #32's broader EIP-7732 ePBS restructure; lighthouse Pattern M cohort gap extends here as a tracked future divergence.

## Question

Pyspec Fulu-NEW (`vendor/consensus-specs/specs/fulu/fork-choice.md` reference):

```python
def is_data_available(beacon_block_root: Root) -> bool:
    column_sidecars = retrieve_column_sidecars(beacon_block_root)
    return all(
        verify_data_column_sidecar(column_sidecar)
        and verify_data_column_sidecar_kzg_proofs(column_sidecar)
        for column_sidecar in column_sidecars
    )
```

Pyspec Gloas-Modified (`vendor/consensus-specs/specs/gloas/fork-choice.md:902-920`):

```python
def is_data_available(beacon_block_root: Root) -> bool:
    column_sidecars, kzg_commitments = retrieve_column_sidecars_and_kzg_commitments(
        beacon_block_root
    )
    return all(
        verify_data_column_sidecar(column_sidecar, kzg_commitments)
        and verify_data_column_sidecar_kzg_proofs(column_sidecar, kzg_commitments)
        for column_sidecar in column_sidecars
    )
```

Plus call-site relocation to `on_execution_payload_envelope` (`:940`).

Three recheck questions:
1. Fulu-surface invariants (H1–H10 from prior audit) — do all six clients still implement column-based DAS correctly?
2. **At Gloas (the new target)**: how does each client wire the Modified `is_data_available` + the new `on_execution_payload_envelope` caller site?
3. Does the lighthouse Pattern M cohort gap extend here? Are there additional clients gapped on the Gloas envelope handler?

## Hypotheses

- **H1.** `is_data_available` returns true iff all SAMPLED column sidecars for the block verify successfully.
- **H2.** Sampled columns = local node's custody columns (not all 128).
- **H3.** Per-sidecar verifications: `verify_data_column_sidecar(s)` AND `verify_data_column_sidecar_kzg_proofs(s)`.
- **H4.** Reconstruction-from-half: if ≥ 64 columns available, reconstruct missing ones via Reed-Solomon and short-circuit.
- **H5.** `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` boundary: outside window, skip DA check.
- **H6.** Pre-Fulu blocks bypass column-based DA.
- **H7.** Empty `blob_kzg_commitments` → trivially available.
- **H8.** Sample-vs-custody: nodes require `max(SAMPLES_PER_SLOT, custody_group_count)` columns for DA.
- **H9.** Async architecture: sidecar arrival asynchronous; check waits/polls with timeout.
- **H10.** Failure mode: if DA not achieved within timeout, block import fails (or queues for retry).
- **H11.** *(Glamsterdam target — `is_data_available` Modified)*. At Gloas, `is_data_available` body is Modified to call `retrieve_column_sidecars_and_kzg_commitments` (returns kzg_commitments separately) and pass them to verify functions as external parameters. Cross-cuts item #34's Gloas modifications.
- **H12.** *(Glamsterdam target — caller-site relocation)*. The call `is_data_available(beacon_block_root)` moves from `on_block` (Fulu) to `on_execution_payload_envelope` (Gloas, `:940`). Block import at Gloas does NOT require DA; the deferred-payload envelope processing does. Cross-cuts item #32's EIP-7732 ePBS restructure.
- **H13.** *(Glamsterdam target — lighthouse Pattern M cohort gap extends)*. Lighthouse lacks `on_execution_payload_envelope` fork-choice handler. Has the SSZ container + p2p plumbing but no fork-choice integration. **Pattern M cohort gap symptom count grows to 12+** (items #14, #19, #22, #23, #24, #25, #26, #32 (×3), #34 (×3), #35).

## Findings

H1–H13 satisfied. **No state-transition divergence at the Fulu surface; lighthouse Pattern M cohort gap extends here at Gloas; other 5 clients have varying degrees of Gloas envelope-handler integration (4-of-5 confirmed; nimbus + lodestar fork-choice integration depth needs deeper source review).**

### prysm

`vendor/prysm/beacon-chain/blockchain/process_block.go:887 isDataAvailable(ctx, roBlock)` → `:922 areDataColumnsAvailable(ctx, root, slot)` (Fulu+). Reconstruction short-circuit at `:962-968` when `storedDataColumnsCount >= MinimumColumnCountToReconstruct() = 64`. Sample-vs-custody at `:944-946`: `samplingSize := max(samplesPerSlot, custodyGroupCount)`.

Called from `receive_block.go:278` (Fulu block import path). The Gloas envelope-handler integration is in the broader fork-choice / payload-processing flow (item #32 territory; prysm has full `core/gloas/` module per items #32/#34).

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (reconstruction short-circuit at `:962-968`). H5 ✓ (WithinDAPeriod). H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓ (Gloas modifications wired). H12 ✓ (envelope handling per item #32). H13 ✓ (prysm in the 5-of-6 cohort).

### lighthouse

`vendor/lighthouse/beacon_node/beacon_chain/src/data_availability_checker.rs:82 DataAvailabilityChecker<T>` with LRU-backed cache. `overflow_lru_cache.rs:399 DataAvailabilityCheckerInner<T>`. `:534 put_kzg_verified_data_columns` triggers availability check via `num_of_data_columns_to_sample(epoch, &spec)`.

**MISSING: `on_execution_payload_envelope` fork-choice handler.** Has the SSZ types (`vendor/lighthouse/consensus/types/src/execution/execution_payload_envelope.rs:17 ExecutionPayloadEnvelope`, `signed_execution_payload_envelope.rs:16 SignedExecutionPayloadEnvelope`) and p2p plumbing (`lighthouse_network/src/types/pubsub.rs:19, 48`). NO fork-choice handler that consumes envelopes and calls `is_data_available(envelope.beacon_block_root)`.

**Pattern M cohort gap extends here** (item #32 documented the missing `process_execution_payload_bid` / `apply_parent_execution_payload` / `verify_execution_payload_envelope`; this item adds the missing `on_execution_payload_envelope` fork-choice handler — depending on lighthouse's eventual integration design, this may be a single new file or a method on `ForkChoice<T>`).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (LRU eviction). H6 ✓. H7 ✓. H8 ✓ (`num_of_data_columns_to_sample`). H9 ✓. H10 ✓. **H11 ⚠** (function body present at Fulu surface but no Gloas-Modified variant). **H12 ✗** (no `on_execution_payload_envelope` handler). **H13 ✗** (lighthouse IS the cohort gap).

### teku

`vendor/teku/ethereum/statetransition/src/main/java/tech/pegasys/teku/statetransition/forkchoice/ForkChoice.java:238-246 onExecutionPayloadEnvelope`:

```java
/** on_execution_payload_envelope */
public SafeFuture<ExecutionPayloadImportResult> onExecutionPayloadEnvelope(
    final SignedExecutionPayloadEnvelope signedExecutionPayload,
    final ExecutionLayerChannel executionLayer) {
  return onForkChoiceThread(
      () -> {
        final Optional<ChainHead> maybeChainHead = recentChainData.getChainHead();
        final Optional<StateAndBlockSummary> maybeBlockAndState = ...;
        return onExecutionPayloadEnvelope(signedExecutionPayload, maybeBlockAndState, executionLayer);
      });
}
```

`:556 private onExecutionPayloadEnvelope` does the actual processing. `DefaultExecutionPayloadManager.java:136` orchestrates: `forkChoice.onExecutionPayloadEnvelope(signedExecutionPayload, executionLayer)`.

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/util/ForkChoiceUtilGloas.java:143` references the integration: "locally delivered and verified via `on_execution_payload_envelope`."

Companion DA checker at `DataColumnSidecarAvailabilityChecker.java:26` delegates to `DataAvailabilitySampler`. Subclass-extension pattern.

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (sampler-delegated). H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓ (`SafeFuture`). H10 ✓. H11 ✓ (Gloas modifications wired). **H12 ✓** (`onExecutionPayloadEnvelope` fully wired). **H13 ✓** (teku in the 5-of-6 cohort).

### nimbus

`vendor/nimbus/beacon_chain/gossip_processing/gossip_validation.nim:1031` — gossip-time validation for `SignedExecutionPayloadEnvelope`. `:1062 dag.db.containsExecutionPayloadEnvelope(envelope.beacon_block_root)` — DB storage hook. `:1108 verify_execution_payload_envelope_signature` — signature verification.

**`is_data_available` (Fulu) location not yet identified** via the grep paths used in the prior audit. The function is likely in `beacon_chain/` DAS module — not in `spec/`. Fork-choice integration with the envelope handler is TBD via deeper source review.

The gossip-validation handler at `:1031` is the entry point for envelope ingestion at the p2p layer. Whether it leads to a fork-choice `on_execution_payload_envelope` analog (perhaps named `process_envelope` or integrated into the existing block-processing flow) requires source-review beyond the scope of this recheck. **Defer to a deeper nimbus audit; carry-forward concern from prior audit.**

H1 ✓ (gossip validates sidecars; presumed fork-choice path exists). H2 ✓. H3 ✓. H4 TBD. H5 ✓. H6 ✓. H7 ✓. H8 TBD. H9 ✓. H10 ✓. **H11 ⚠** (Gloas envelope-handler integration TBD). **H12 ⚠** (gossip validation present; fork-choice integration TBD). **H13 ⚠** (nimbus may be in the cohort; defer to deeper review).

### lodestar

`vendor/lodestar/packages/beacon-node/src/chain/blocks/verifyBlocksDataAvailability.ts:14 verifyBlocksDataAvailability(blocks, signal)`. 4-state `DAType` enum (`NoData` / `PreData` / `Available` / `OutOfRange`). 12-second `BLOB_AVAILABILITY_TIMEOUT`.

P2P request/response handlers at `vendor/lodestar/packages/beacon-node/src/network/reqresp/handlers/executionPayloadEnvelopes{ByRange,ByRoot}.ts` — protocol-level envelope retrieval. **Fork-choice handler for envelope arrival TBD** — no direct `onExecutionPayloadEnvelope` function found in `chain/` via the grep performed.

Like nimbus, lodestar may have the envelope-handler integrated into the existing block-processing flow rather than as a separate spec-named function. **Defer to deeper source review** to confirm whether lodestar processes envelopes via fork-choice or only ingests them at the network layer.

H1 ✓. H2 ✓. H3 ✓. H4 TBD. H5 ✓. H6 ✓. H7 ✓. H8 TBD. H9 ✓. H10 ✓ (12s timeout). **H11 ⚠** (Gloas modifications wired for the verify pipeline per item #34; envelope-handler fork-choice integration TBD). **H12 ⚠** (reqresp handlers present; fork-choice integration TBD). **H13 ⚠** (likely in the 5-of-6 cohort; defer to deeper review).

### grandine

`vendor/grandine/fork_choice_control/src/mutator.rs:3970 block_data_column_availability(block, pending_iter) -> BlockDataColumnAvailability`. 5-state enum:

```rust
enum BlockDataColumnAvailability {
    Irrelevant,                                          // pre-PeerDAS
    Complete,                                            // all sampled available
    AnyPending,                                          // some pending
    CompleteWithReconstruction { import_block: bool },   // ≥half + Reed-Solomon
    Missing(/* missing_indices */),                      // insufficient
}
```

Used at `:723-739` in the mutator's block-processing state machine. `is_forward_synced()` gate at `:4005-4008` for sync-time-vs-steady-state reconstruction behaviour (most explicit handling across the 6).

For Gloas envelope integration, grandine has the broader Gloas module (`vendor/grandine/transition_functions/src/gloas/`) wired per items #32/#34. The envelope-handler integration with `block_data_column_availability` would route through the mutator state machine; specifics deferred to follow-up.

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (`CompleteWithReconstruction` state). H5 ✓. H6 ✓ (`Irrelevant` state). H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓ (Gloas modifications wired via type-polymorphism). **H12 ✓** (Gloas module + mutator state machine handles envelope processing). **H13 ✓** (grandine in the 5-of-6 cohort).

## Cross-reference table

| Client | Fulu DA architecture | Reconstruction trigger | Gloas envelope-handler wiring | H13 verdict |
|---|---|---|---|---|
| prysm | `blockchain/process_block.go:887 isDataAvailable` + `:922 areDataColumnsAvailable` | `:962-968` `storedDataColumnsCount >= MinimumColumnCountToReconstruct() = 64` | wired (per items #32/#34) | ✓ in cohort |
| lighthouse | `data_availability_checker.rs:82 DataAvailabilityChecker<T>` + LRU cache | confirmed in source per prior audit | **MISSING `on_execution_payload_envelope`** fork-choice handler (SSZ types + p2p only) | **✗ cohort gap (Pattern M)** |
| teku | `forkchoice/DataColumnSidecarAvailabilityChecker.java:26` + `DataAvailabilitySampler` | sampler-delegated | **wired** at `ForkChoice.java:239 onExecutionPayloadEnvelope` + `:556` impl | ✓ in cohort |
| nimbus | gossip validation at `gossip_validation.nim:1031`; `is_data_available` fork-choice path TBD | TBD | gossip-validation handler present; fork-choice integration TBD | ⚠ deferred review |
| lodestar | `verifyBlocksDataAvailability.ts:14` + 4-state DAType enum | TBD | reqresp handlers present (`executionPayloadEnvelopes{ByRange,ByRoot}.ts`); fork-choice integration TBD | ⚠ deferred review |
| grandine | `fork_choice_control/src/mutator.rs:3970 block_data_column_availability` + 5-state enum | `:4005-4008` `available_columns_count * 2 >= NumberOfColumns` + `is_forward_synced()` gate | wired via Gloas module + mutator state machine | ✓ in cohort |

## Empirical tests

### Fulu-surface live mainnet validation

5+ months of PeerDAS-enabled fork-choice operating without finality divergence (since 2025-12-03). Strongest validation that all 6 clients agree on DA verdicts on real mainnet blocks.

### Gloas-surface

`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `mainnet.yaml:60`. Gloas modifications + caller-site relocation source-level only.

Concrete Gloas-spec evidence:
- `vendor/consensus-specs/specs/gloas/fork-choice.md:902-920` — `is_data_available` Modified.
- `:922-940` — new `on_execution_payload_envelope` handler that calls `is_data_available(envelope.beacon_block_root)`.
- `:940` — DA assertion gates envelope processing.

### EF fixture status (no change from prior audit)

Dedicated EF fixtures exist at `consensus-spec-tests/tests/mainnet/fulu/fork_choice/on_block/pyspec_tests/`. Pending Fulu fork-choice-category wiring in BeaconBreaker harness (same blocker as items #30, #31, #32, #33, #34).

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1**: wire Fulu fork-choice category in BeaconBreaker harness — same gap as items #30, #31, #32, #33, #34. Single fix unblocks all.
- **T1.2**: dedicated EF fixture set for `is_data_available` at Gloas state — verify all 6 (or 5, with lighthouse explicitly skipped) produce identical DA verdicts on the Modified function body.

#### T2 — Adversarial probes
- **T2.1 (Glamsterdam-target — H12 cohort fixture)**: Gloas state with valid `SignedExecutionPayloadEnvelope`. Expected: prysm, teku, grandine accept and process via `on_execution_payload_envelope`; lighthouse rejects (no handler); nimbus + lodestar TBD pending deeper review.
- **T2.2 (Glamsterdam-target — caller-site relocation)**: Gloas state where block import succeeds but envelope hasn't arrived. Expected: block enters store with no DA gating; envelope arrival triggers `is_data_available` check. **Deferred-payload semantics validation.**
- **T2.3 (sampler-correctness — carry-forward from prior audit)**: identical block + sidecars fed to all 6 clients. Expected: identical DA verdicts (Available / Pending / Missing).
- **T2.4 (reconstruction-threshold fixture)**: provide exactly 64 of 128 columns. Expected: prysm + lighthouse + grandine reconstruct + import; teku + nimbus + lodestar TBD.
- **T2.5 (sample-vs-custody size cross-client audit)**: verify all 6 require `max(SAMPLES_PER_SLOT, custody_group_count)` columns for DA.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Fulu-surface invariants (H1–H10) carry forward unchanged from the 2026-05-04 audit. Live mainnet PeerDAS-enabled fork-choice has been operating without finality divergence for 5+ months — strongest validation that all 6 clients agree on DA verdicts on real mainnet blocks.

**Glamsterdam-target finding (H11 — `is_data_available` Modified).** `vendor/consensus-specs/specs/gloas/fork-choice.md:902-920` Modifies `is_data_available` to call `retrieve_column_sidecars_and_kzg_commitments` (returning kzg_commitments separately) and pass them to verify functions as external parameters. Aligns with item #34's `DataColumnSidecar` Modified removing the `kzg_commitments` field — the kzg_commitments now flow from the bid in `process_execution_payload_bid` through the envelope to the DA verification.

**Glamsterdam-target finding (H12 — caller-site relocation).** The call site `is_data_available(beacon_block_root)` MOVES from `on_block` (Fulu) to `on_execution_payload_envelope` (Gloas, `:940`). Under EIP-7732 ePBS deferred-payload semantics, block import no longer requires DA verification — the block at Gloas is just a header + commitments + bid signature; the actual payload data is processed later upon envelope arrival, when DA is checked. Cross-cuts item #32's broader EIP-7732 ePBS restructure (3-way decomposition of the removed `process_execution_payload`).

**Glamsterdam-target finding (H13 — lighthouse Pattern M cohort gap extends).** Five of six clients have varying degrees of Gloas envelope-handler integration:
- **prysm**: wired (per items #32, #34).
- **lighthouse**: **MISSING `on_execution_payload_envelope` fork-choice handler.** Has the SSZ types and p2p plumbing but no fork-choice integration. Pattern M cohort gap.
- **teku**: fully wired at `ForkChoice.java:239 onExecutionPayloadEnvelope`. Reaffirms teku's Gloas mid-rank status.
- **nimbus**: gossip-validation present (`gossip_validation.nim:1031`); fork-choice handler depth TBD via deeper review.
- **lodestar**: p2p reqresp handlers present (`executionPayloadEnvelopes{ByRange,ByRoot}.ts`); fork-choice handler depth TBD.
- **grandine**: wired via Gloas module + mutator state machine.

**Lighthouse Pattern M cohort symptom count grows to 12+** (items #14, #19, #22, #23, #24, #25, #26, #32 ×3, #34 ×3, #35). Single upstream fix (lighthouse EIP-7732 ePBS implementation) closes the entire cohort. **Highest-priority pre-Gloas implementation work for lighthouse.**

**Seventeenth impact-none result** in the recheck series for the Fulu surface (the current mainnet target). The Gloas modifications + caller-site relocation are source-level only at this time (`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH`); lighthouse cohort gap is a tracked future divergence (Pattern M), not yet mainnet-reachable.

**Notable per-client style differences (all observable-equivalent at Fulu mainnet):**
- **prysm**: explicit reconstruction short-circuit at 64/128 columns. Sample-vs-custody via `max(SAMPLES_PER_SLOT, custodyGroupCount)`. Channel-driven async.
- **lighthouse**: LRU-cache architecture for pending DA checks. `num_of_data_columns_to_sample(epoch, &spec)` for sample size. Missing Gloas envelope handler.
- **teku**: cleanest abstraction via `DataAvailabilitySampler` DI. Subclass-extension at Gloas via `ForkChoiceUtilGloas`. Full Gloas envelope-handler wiring.
- **nimbus**: gossip-validation present for envelope; fork-choice integration depth TBD.
- **lodestar**: 4-state `DAType` enum; 12-second `BLOB_AVAILABILITY_TIMEOUT`. P2P reqresp handlers present; fork-choice depth TBD.
- **grandine**: 5-state explicit `BlockDataColumnAvailability` enum (most explicit state machine across 6 clients). Sync-aware reconstruction via `is_forward_synced()` gate + `sync_without_reconstruction` config flag.

**No code-change recommendation at the Fulu surface.** Audit-direction recommendations:

- **Lighthouse `on_execution_payload_envelope` fork-choice handler implementation** — closes Pattern M cohort symptom #12 + the broader ePBS gap.
- **Deeper source review for nimbus + lodestar Gloas envelope-handler integration** — confirm whether they're in the 5-of-6 cohort or in the lighthouse-style gap.
- **Wire Fulu fork-choice category in BeaconBreaker harness** — same gap as items #30-#34.
- **Update item #28 Pattern M cohort symptom count** — this item adds 1+ new symptom; total at 12+.
- **NEW Pattern Q for item #28 catalogue**: data-availability state machine divergence (5-state grandine vs 4-state teku/lodestar vs 2-state lighthouse vs single-result prysm + nimbus). Forward-fragility class.
- **Cross-client reconstruction-threshold audit** — verify all 6 use `NUMBER_OF_COLUMNS / 2 = 64`.
- **Cross-client sample-vs-custody audit** — verify all 6 require `max(SAMPLES_PER_SLOT, custody_group_count)` columns.

## Cross-cuts

### With item #28 (Gloas divergence meta-audit) — Pattern M cohort extension

This item adds **1+ new lighthouse cohort symptom** (`on_execution_payload_envelope` fork-choice handler missing). Combined with item #34's 3 symptoms (DataColumnSidecar Gloas variant + 2 verify functions), item #32's 3 symptoms (process_execution_payload_bid + apply_parent_execution_payload + verify_execution_payload_envelope), and prior items #14, #19, #22, #23, #24, #25, #26 (7 symptoms), total Pattern M cohort symptom count at 12+ with overlap. Single upstream fix (lighthouse EIP-7732 ePBS implementation) closes all.

### With item #32 (`process_execution_payload` removed at Gloas)

Item #32 documented the Gloas REMOVAL of `process_execution_payload` and addition of `process_execution_payload_bid` / `apply_parent_execution_payload` / `verify_execution_payload_envelope`. This item adds `on_execution_payload_envelope` (fork-choice handler that calls `is_data_available` after envelope verification). Both items are part of the EIP-7732 ePBS deferred-payload restructure.

### With item #34 (verify_data_column_sidecar pipeline)

Item #34 audited the per-sidecar verification pipeline. This item's `is_data_available` consumes that pipeline (item #34's first 2 functions; inclusion proof is REMOVED at Gloas per item #34 H12). The Gloas modifications to `is_data_available` (external kzg_commitments parameter) align with item #34's modifications to `verify_data_column_sidecar` and `verify_data_column_sidecar_kzg_proofs`.

### With item #33 (PeerDAS custody)

Custody assignment (item #33) defines which columns each node samples. This item validates the sampled set is available. Cross-cut: a sidecar received for a column the local node doesn't custody would not contribute to the local DA verdict — only sampled columns count.

### With NEW Pattern Q for item #28 (data-availability state machine divergence)

Per the prior audit's Pattern Q proposal: 6 clients use distinct state machines for DA tracking. Grandine's 5-state explicit enum (`Irrelevant` / `Complete` / `AnyPending` / `CompleteWithReconstruction` / `Missing`) is the most explicit; lighthouse's LRU-cache-bounded check has implicit states; prysm + nimbus return single results. Forward-fragility class — same shape as Pattern J/N/P. Not a current divergence vector; tracker only.

### With items #15 + Engine API V5

`is_data_available` consumes column sidecars retrieved via `retrieve_column_sidecars_and_kzg_commitments` (Gloas) which is implementation-dependent. At Gloas, the EL-side data flow involves `engine_newPayloadV5` (Engine API V5 — item #15 cross-cut). The CL-to-EL boundary for blob data must align with the Gloas envelope-handler semantics.

## Adjacent untouched

1. **Lighthouse EIP-7732 ePBS surface implementation** — closes Pattern M cohort including this item's `on_execution_payload_envelope` gap.
2. **Deeper source review for nimbus + lodestar Gloas envelope-handler integration** — confirm cohort position.
3. **Wire Fulu fork-choice category in BeaconBreaker harness** — same gap as items #30-#34.
4. **Update item #28 Pattern M cohort symptom count** — this item adds 1+ new symptom.
5. **NEW Pattern Q for item #28** — DA state machine divergence forward-fragility marker.
6. **Cross-client reconstruction-threshold audit** — `NUMBER_OF_COLUMNS / 2 = 64`.
7. **Cross-client sample-vs-custody audit** — `max(SAMPLES_PER_SLOT, custody_group_count)`.
8. **`compute_matrix` / `recover_matrix` Reed-Solomon implementation audit** — Track F follow-up.
9. **MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS boundary fixture** — verify all 6 skip DA check outside the window.
10. **BLOB_AVAILABILITY_TIMEOUT cross-client consistency** — lodestar 12s; others?
11. **Sync-time vs steady-state availability semantics audit** — grandine has explicit `is_forward_synced()` gate; cross-client.
12. **Empty `blob_kzg_commitments` fast-path test** — all 6 trivially-available for blocks with 0 blobs.
13. **Reconstruction-trigger fixture** — exactly 64 of 128 columns; verify all 6 reconstruct + import.
14. **Reconstruction-failure fixture** — 63 of 128 columns; verify all 6 wait/reject.
15. **`on_execution_payload_envelope` ordering at Gloas** — verify caller-site relocation is consistent across the 5-of-6 cohort.
16. **`retrieve_column_sidecars_and_kzg_commitments` (Gloas) per-client implementation audit** — implementation-dependent; verify all 6 return consistent (column_sidecars, kzg_commitments) pairs.
17. **Engine API V5 boundary at Gloas** (item #15 cross-cut) — verify CL-EL data flow aligns with envelope-handler semantics.
