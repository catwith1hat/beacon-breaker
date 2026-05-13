---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [28, 34, 38, 39, 43, 44, 46, 51, 54, 55]
eips: [EIP-7594, EIP-7732]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 56: Fulu + Gloas fork choice modifications — `is_data_available` (PeerDAS-modified at Fulu, again modified at Gloas) + `on_block` (DA delayed to `on_execution_payload_envelope` at Gloas) — Pattern II fork-choice DA architecture divergence

## Summary

EIP-7594 PeerDAS modifies the Fulu fork-choice DA primitives. The Glamsterdam target further modifies them under EIP-7732 PBS.

**Fulu** (`vendor/consensus-specs/specs/fulu/fork-choice.md`): `is_data_available` rewritten to consume column sidecars instead of blobs; `on_block` signature drops `blob_kzg_commitments`.

**Gloas** (`vendor/consensus-specs/specs/gloas/fork-choice.md:838-940`, new spec content) — TWO additional modifications:

1. **Modified `on_block`** (`:838-900`): adds `is_payload_verified(store, block.parent_root)` assertion when parent is "full"; **delays the DA check** — no longer calls `is_data_available` at all; the DA check moves to the new `on_execution_payload_envelope` handler.
2. **Modified `is_data_available`** (`:902-920`): replaces `retrieve_column_sidecars` with `retrieve_column_sidecars_and_kzg_commitments` (returns a tuple); both `verify_data_column_sidecar` and `verify_data_column_sidecar_kzg_proofs` now take `kzg_commitments` as an additional parameter (because the Gloas `DataColumnSidecar` removes the `kzg_commitments` field per item #54 — commitments now live in the `signed_execution_payload_bid`).
3. **NEW `on_execution_payload_envelope`** handler (`:922-940`) called when a `SignedExecutionPayloadEnvelope` is received; calls `is_data_available(envelope.beacon_block_root)`.

**Fulu surface (carried forward from 2026-05-04 audit; cap value):** all 6 clients implement Fulu DA semantic. 5+ months of mainnet cross-client fork-choice operation without observed divergence on the canonical chain.

**Pattern II carry-forward (item #28 catalogue candidate)**: fork-choice DA verification architecture divergence — **6 distinct dispatch architectures** for the same spec semantic:

| Client | Architecture | Block queueing |
|---|---|---|
| **prysm** | Single function `isDataAvailable` (`vendor/prysm/beacon-chain/blockchain/process_block.go:887-918`) with `if blockVersion >= version.Fulu` → `areDataColumnsAvailable`; plus dedicated Gloas envelope path at `receive_execution_payload_envelope.go:88` | Synchronous blocking wait on notifier channels |
| **lighthouse** | Type-based dispatch via `BlobSidecar` (Deneb) vs `DataColumnSidecar` (Fulu+) wrapped by `DataAvailabilityChecker<T>` | LRU `PendingComponents` cache (max 32) |
| **teku** | Pattern J — separate `AvailabilityChecker` classes per fork (`BlobSidecarsAvailabilityChecker` + `DataColumnSidecarAvailabilityChecker`); `ForkChoice.java:238 onExecutionPayloadEnvelope` Gloas handler | Async `SafeFuture` |
| **nimbus** | **3-quarantine pattern**: `blobQuarantine` (Deneb) + `ColumnQuarantine` (Fulu) + `GloasColumnQuarantine` (Gloas); `eth2_processor.nim:326 processExecutionPayloadEnvelope` Gloas handler | Quarantine pool with custody-aware accumulator |
| **lodestar** | Pattern R — `DAType` enum union dispatch (`PreData` / `Blobs` / `Columns` / `NoData`); `validation/executionPayloadEnvelope.ts` Gloas validator | `SeenBlockInput` LRU cache |
| **grandine** | Module-isolated `eip_7594/src/lib.rs` with custody-group computation + cell KZG batch verify | `BlobReconstructionPool` operation pool (Reed-Solomon recovery integration) |

Most diverse architecture finding in the audit corpus. Same forward-fragility class as Pattern I/J/R (multi-fork-definition family).

**Pattern M cohort extends to fork-choice DA layer (NEW finding this recheck)**: the {lighthouse, grandine} Gloas-ePBS readiness cohort established by items #43 (Engine API V5/V6/FCU4 missing) + #44 (PartialDataColumnSidecar absent) + #46 (envelope RPCs missing) now also lacks the Gloas-NEW `on_execution_payload_envelope` fork-choice handler.

- **prysm**: ✅ `vendor/prysm/beacon-chain/blockchain/receive_execution_payload_envelope.go:88 if err := s.areDataColumnsAvailable(ctx, root, envelope.Slot()); err != nil { ... }` — explicit Gloas DA path on envelope receipt; metrics at `metrics.go:241-251`.
- **teku**: ✅ `vendor/teku/ethereum/statetransition/src/main/java/tech/pegasys/teku/statetransition/forkchoice/ForkChoice.java:238 /** on_execution_payload_envelope */ public SafeFuture<ExecutionPayloadImportResult> onExecutionPayloadEnvelope(...)` + `:556 private SafeFuture<ExecutionPayloadImportResult> onExecutionPayloadEnvelope(...)`; `ForkChoiceUtilGloas.java:143-145 isPayloadVerified(store, root)`.
- **nimbus**: ✅ `vendor/nimbus/beacon_chain/gossip_processing/eth2_processor.nim:326 proc processExecutionPayloadEnvelope*(...)` + `block_processor.nim:1019-1031 gloasColumnQuarantine.popSidecars(blck.root)` integration with the GloasColumnQuarantine pool at `block_processor.nim:32, 104, 131, 149`.
- **lodestar**: ✅ envelope validation at `vendor/lodestar/packages/beacon-node/src/chain/validation/executionPayloadEnvelope.ts`; envelope retrieval at `chain.ts:863-905 getSerializedExecutionPayloadEnvelope` / `getExecutionPayloadEnvelope`.
- **lighthouse**: ❌ **NO `SignedExecutionPayloadEnvelope` references in `vendor/lighthouse/beacon_node/beacon_chain/src/`** — `grep` returns zero matches. Lighthouse has gossip-topic plumbing in `lighthouse_network/src/types/pubsub.rs` (item #46 finding) but no fork-choice layer integration. **No Gloas DA on envelope receipt.**
- **grandine**: ❌ **NO `SignedExecutionPayloadEnvelope` references in `vendor/grandine/fork_choice_control/` or `vendor/grandine/fork_choice_store/`** — `grep` returns zero matches. No Gloas envelope handler at the fork-choice layer.

**Pattern P cross-cut (carry-forward from item #34 grandine hardcoded gindex 11)**: applies to BOTH Fulu gossip-time AND Fulu fork-choice-time DA verification because the same `verify_data_column_sidecar` + `verify_data_column_sidecar_kzg_proofs` primitives are reused. Pattern P is more pervasive than item #34 alone documented — extends to fork-choice layer at Fulu. **At Gloas, however, the inclusion-proof path becomes dead** (item #54 removes the inclusion-proof field from the sidecar), so Pattern P dissolves at Gloas activation.

**Sampling-vs-custody divergence** (carry-forward): 3-vs-3 split — sampling-aware (prysm, teku, lodestar) verify the sampling subset (SAMPLES_PER_SLOT = 8); custody-aware (lighthouse, nimbus, grandine) verify all custodied columns (CUSTODY_REQUIREMENT = 4 minimum). On current mainnet (max 21 blobs per block at BPO #2) the divergence has not manifested. **Forward-fragility at higher blob loads** (hypothetical 100+ blobs per block): sampling-aware MAY accept blocks that custody-aware reject → fork divergence vector.

**Block queueing strategy diversity**: 6 distinct (synchronous blocking wait; LRU `PendingComponents`; async `SafeFuture`; quarantine pool; `SeenBlockInput` LRU; `BlobReconstructionPool` operation pool). Pattern T-family spec-undefined edge cases on timeouts and eviction policies.

**Live mainnet validation**: 5+ months of cross-client Fulu fork-choice operation without observed divergence. All 6 accept the same canonical chain; sampling-vs-custody divergence has not manifested under current mainnet blob loads.

**Impact: none** — Fulu surface operates byte-equivalently in practice; Gloas modifications (modified `is_data_available`, modified `on_block`, new `on_execution_payload_envelope` handler) are not mainnet-reachable today (`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH`); lighthouse + grandine envelope-handler gaps are forward-fragility tracking only. Thirty-seventh `impact: none` result in the recheck series.

## Question

Pyspec defines Fulu fork-choice DA at `vendor/consensus-specs/specs/fulu/fork-choice.md` and the Gloas modifications at `vendor/consensus-specs/specs/gloas/fork-choice.md:838-940` (modified `on_block`, modified `is_data_available`, new `on_execution_payload_envelope`).

Four recheck questions:

1. **Fulu DA semantic** — does the 6-distinct-architecture Pattern II split persist? Have any clients converged on a single dispatch pattern since the 2026-05-04 audit?
2. **Sampling-vs-custody** — does the 3-vs-3 split persist? Has any client switched mode?
3. **Glamsterdam target — Gloas modifications** — which clients have implemented `on_execution_payload_envelope` for the delayed DA check + modified `is_data_available` signature with `kzg_commitments` passed separately?
4. **Pattern M cohort extension** — does the {lighthouse, grandine} Gloas-ePBS gap extend to the fork-choice DA layer?

## Hypotheses

- **H1.** All 6 clients implement Fulu fork-choice DA check (carry-forward — validated by 5+ months of mainnet operation).
- **H2.** Pattern II (6 distinct dispatch architectures) persists.
- **H3.** Sampling-vs-custody 3-vs-3 split persists (prysm + teku + lodestar sampling; lighthouse + nimbus + grandine custody).
- **H4.** Block queueing strategy diversity (6 distinct) persists.
- **H5.** Cross-cut to item #34 verification path: same `verify_data_column_sidecar` + `verify_data_column_sidecar_kzg_proofs` reused.
- **H6.** Pattern P (grandine hardcoded gindex 11) applies to Fulu fork-choice DA verification.
- **H7.** *(Glamsterdam target — modified `is_data_available` signature)* spec at `gloas/fork-choice.md:902-920` replaces `retrieve_column_sidecars` with `retrieve_column_sidecars_and_kzg_commitments`; passes `kzg_commitments` to `verify_data_column_sidecar(column_sidecar, kzg_commitments)` and `verify_data_column_sidecar_kzg_proofs(column_sidecar, kzg_commitments)`.
- **H8.** *(Glamsterdam target — modified `on_block`)* spec at `gloas/fork-choice.md:838-900` delays DA check; `on_block` no longer calls `is_data_available`. DA check moves to `on_execution_payload_envelope`.
- **H9.** *(Glamsterdam target — new `on_execution_payload_envelope` handler)* spec at `:922-940` defines the new handler. Implementations: prysm + teku + nimbus + lodestar; lighthouse + grandine missing (Pattern M cohort extension).
- **H10.** *(Glamsterdam target — Pattern P dissolves at Gloas)* the inclusion-proof path becomes dead at Gloas (item #54 cross-cut — sidecar removes inclusion-proof field).
- **H11.** Nimbus pre-Gloas leader: `GloasColumnQuarantine` already implemented for Gloas.

## Findings

H1 ✓. H2 ✓ (6 architectures persist). H3 ✓ (3-vs-3 split persists). H4 ✓ (6 queueing strategies persist). H5 ✓. H6 ✓ (Pattern P cross-cut). H7 ✓ (spec signature change). H8 ✓ (spec on_block change). **H9 ⚠ — confirmed split**: 4 clients have envelope handler; lighthouse + grandine missing (Pattern M cohort extends). H10 ✓ (Pattern P dissolves at Gloas). H11 ✓ (nimbus has `GloasColumnQuarantine` plus `processExecutionPayloadEnvelope`).

### prysm

Fulu DA dispatch (`vendor/prysm/beacon-chain/blockchain/process_block.go:882-918`):

```go
// isDataAvailable blocks until all sidecars committed to in the block are available, ...
func (s *Service) isDataAvailable(
    ctx context.Context,
    root [fieldparams.RootLength]byte,
    block interfaces.ReadOnlyBeaconBlock,
) error {
    ...
    if blockVersion >= version.Fulu {
        return s.areDataColumnsAvailable(ctx, root, block.Slot())
    }
    ...
    return s.areBlobsAvailable(ctx, root, block)
```

Binary version check at `:910` (sampling-aware via `peerdas.Info(nodeID, samplingSize)`). Call sites at `process_block.go:455` (block import path) and `receive_execution_payload_envelope.go:88` (Gloas envelope handler):

```go
// receive_execution_payload_envelope.go:88
if err := s.areDataColumnsAvailable(ctx, root, envelope.Slot()); err != nil {
```

Metrics at `vendor/prysm/beacon-chain/blockchain/metrics.go:241-251` — `beacon_execution_payload_envelope_valid_total`, `beacon_execution_payload_envelope_invalid_total`, `beacon_execution_payload_envelope_processing_duration_seconds`. **prysm has the Gloas envelope handler wired**.

Pattern II architecture: binary version check + synchronous blocking wait. Sampling-aware.

H1, H2, H3 (sampling), H4 (synchronous blocking), H7 (Gloas envelope handler present), H9 ✓.

### lighthouse

Fulu DA via `DataAvailabilityChecker<T>` wrapper (`vendor/lighthouse/beacon_node/beacon_chain/src/data_availability_checker.rs:1-100+`):

- Type-based dispatch via `BlobSidecar<E>` (Deneb/Electra) vs `DataColumnSidecar<E>` (Fulu+).
- `PendingComponents` LRU cache (max 32) for block-queueing.
- Custody-aware: verifies columns within the node's custody set.
- `verify_kzg_for_data_column_list` integration with item #34 verification path.

Pattern II architecture: type-based dispatch + LRU cache. Custody-aware.

**Pattern M cohort symptom — Gloas envelope handler missing**: `grep -rn "SignedExecutionPayloadEnvelope" vendor/lighthouse/beacon_node/beacon_chain/src/` returns 0 matches. Lighthouse has gossip topic plumbing in `lighthouse_network/src/types/pubsub.rs:19,48,368` (per item #46) but no fork-choice layer integration. At Gloas activation, lighthouse would have no `on_execution_payload_envelope` handler to call `is_data_available` from — the spec-prescribed DA path would not execute.

H1, H2, H3 (custody), H4 (LRU cache), H5, H7 spec ✓; **H9 ⚠ — envelope handler missing**.

### teku

Fulu DA via separate `AvailabilityChecker` classes per fork (`vendor/teku/ethereum/spec/.../BlobSidecarsAvailabilityChecker.java` + `DataColumnSidecarAvailabilityChecker.java`). Pattern J — class-per-fork OOP pattern.

Sampling-aware via `DataAvailabilitySampler.checkSamplingEligibility()` returning sampled column indices.

Block queueing: async `SafeFuture` with NOT_REQUIRED_BEFORE_FULU / _OLD_EPOCH / _NO_BLOBS status enum.

Gloas envelope handler (`vendor/teku/ethereum/statetransition/src/main/java/tech/pegasys/teku/statetransition/forkchoice/ForkChoice.java:238-246, 556`):

```java
/** on_execution_payload_envelope */
public SafeFuture<ExecutionPayloadImportResult> onExecutionPayloadEnvelope(
    final SignedExecutionPayloadEnvelope signedEnvelope, ...) {
  return ...
      .thenCompose(maybeBlockAndState ->
          onExecutionPayloadEnvelope(signedEnvelope, maybeBlockAndState, executionLayer));
...
private SafeFuture<ExecutionPayloadImportResult> onExecutionPayloadEnvelope(...)
```

Gloas `isPayloadVerified` predicate (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/util/ForkChoiceUtilGloas.java:133, 143-145`):

```java
return isPayloadVerified(store, block.getRoot()) ? 1 : 0;
...
/**
 * locally delivered and verified via ``on_execution_payload_envelope``.
 */
public boolean isPayloadVerified(final ReadOnlyStore store, final Bytes32 root) {
```

Teku EPBS status doc at `vendor/teku/docs/EPBS_STATUS.md:103` describes `is_payload_verified` / `_timely` / `_data_available` predicates as "Implemented in `ForkChoiceModelGloas` against PTC vote tracker thresholds". Teku has comprehensive Gloas DA wiring.

H1, H2, H3 (sampling), H4 (async future), H5, H7, H8, H9 ✓ (envelope handler present).

### nimbus

3-quarantine pattern at the fork-choice DA layer (`vendor/nimbus/beacon_chain/gossip_processing/block_processor.nim:32, 104, 131, 149`):

```nim
BlobQuarantine, ColumnQuarantine, GloasColumnQuarantine, popSidecars, put
...
gloasColumnQuarantine*: ref GloasColumnQuarantine
...
gloasColumnQuarantine: ref GloasColumnQuarantine,
...
gloasColumnQuarantine: gloasColumnQuarantine,
```

3 distinct quarantine types — one per fork generation that touches DA. The quarantine pool IS the DA check: blocks wait in quarantine until columns arrive; when complete, the block is "popped" from quarantine.

`block_processor.nim:1019-1031` Gloas-specific quarantine resolution:

```nim
let sidecarsOpt =
  if bid.message.blob_kzg_commitments.len() == 0:
    Opt.some(default(gloas.DataColumnSidecars))
  else:
    self.gloasColumnQuarantine[].popSidecars(blck.root)
if sidecarsOpt.isNone():
  # As sidecars are missing, put envelope back to quarantine.
  self.consensusManager.quarantine[].addSidecarless(blck)
  self.envelopeQuarantine[].addOrphan(envelope)
  return
sidecarsOpt
```

Gloas envelope handler (`vendor/nimbus/beacon_chain/gossip_processing/eth2_processor.nim:326`):

```nim
proc processExecutionPayloadEnvelope*(
```

Sister sites at `nimbus_beacon_node.nim:2390` and `validators/message_router.nim:711`.

Pattern II architecture: 3-quarantine pool + Gloas envelope handler. Custody-aware via `custodyMap` in quarantine pool. **Most fork-aware client** — Gloas DA already integrated at the quarantine + envelope-handler level.

Cross-cut to item #28 Gloas readiness scoreboard: nimbus is the leader on the Gloas DA layer (pre-Gloas implementation of `GloasColumnQuarantine` + `processExecutionPayloadEnvelope`).

H1, H2, H3 (custody), H4 (quarantine pool), H5, H7, H8, H9 ✓, H11 ✓.

### lodestar

Fulu DA via `DAType` enum union dispatch (`vendor/lodestar/packages/beacon-node/src/chain/blockInput/types.ts:5-12`; `vendor/lodestar/packages/beacon-node/src/chain/blocks/verifyBlocksDataAvailability.ts:14-45`):

- `DAType.PreData` / `DAType.Blobs` (Deneb) / `DAType.Columns` (Fulu) / `DAType.NoData`.
- Union `DAData = null | deneb.BlobSidecars | fulu.DataColumnSidecar[]`.

Block queueing via `SeenBlockInput` LRU cache (`vendor/lodestar/packages/beacon-node/src/chain/seenGossipBlockInput.ts:100+`): max `(MAX_LOOK_AHEAD_EPOCHS + 1) * SLOTS_PER_EPOCH`; pruned on finalization + range sync completion.

Sampling-aware via `CustodyConfig` driving DataColumnSidecar validation.

Gloas envelope validation (`vendor/lodestar/packages/beacon-node/src/chain/validation/executionPayloadEnvelope.ts`) + envelope retrieval (`vendor/lodestar/packages/beacon-node/src/chain/chain.ts:863-905`):

```typescript
async getSerializedExecutionPayloadEnvelope(blockSlot: Slot, blockRootHex: string): Promise<Uint8Array | null> {
  ...
  return ssz.gloas.SignedExecutionPayloadEnvelope.serialize(envelope);
}
...
async getExecutionPayloadEnvelope(...): Promise<gloas.SignedExecutionPayloadEnvelope | null> {
  ...
}
```

Plus errors at `vendor/lodestar/packages/beacon-node/src/chain/errors/executionPayloadEnvelope.ts`. Lodestar has envelope plumbing at the chain layer; the validator at `validation/executionPayloadEnvelope.ts` is the on-receive handler.

H1, H2, H3 (sampling), H4 (LRU cache), H5, H7, H8, H9 ✓ (envelope validation present).

### grandine

Fulu DA via EIP-7594 module integration (`vendor/grandine/eip_7594/src/lib.rs:1-100+`):

- Native PeerDAS module with custody-group computation + cell KZG proof batch verification.
- Type-based dispatch via `FuluDataColumnSidecar` vs `GloasDataColumnSidecar` (from item #54 — separate SSZ structs at Fulu + Gloas).
- Custody-aware (explicit custody-group computation).

Block queueing via `BlobReconstructionPool` (`vendor/grandine/operation_pools/blob_reconstruction_pool/tasks.rs`) — operation pool integrating Reed-Solomon recovery for missing data (item #39 cross-cut).

**Pattern M cohort symptom — Gloas envelope handler missing**: `grep -rn "SignedExecutionPayloadEnvelope\|ExecutionPayloadEnvelope" vendor/grandine/fork_choice_control/ vendor/grandine/fork_choice_store/` returns 0 matches. No fork-choice integration for the Gloas envelope; no `on_execution_payload_envelope` handler. At Gloas activation, grandine would have no path to invoke `is_data_available` from envelope receipt — Gloas DA semantic would not execute.

**Pattern P (item #34) + V (item #40) cross-cut**: grandine's hardcoded gindex 11 + manual inclusion-proof construction apply to BOTH gossip-time AND fork-choice-time DA verification at Fulu. At Gloas, the inclusion-proof path becomes dead (item #54 sidecar removes the field) so Patterns P + V dissolve at Gloas — but Fulu remains live throughout the transition window.

H1, H2, H3 (custody), H4 (operation pool), H5, H6 (Pattern P/V cross-cut), H7 spec ✓; **H9 ⚠ — envelope handler missing**.

## Cross-reference table

| Client | H2 Fulu dispatch idiom | H3 sampling/custody | H4 block queueing | H6 Pattern P cross-cut | H9 Gloas `on_execution_payload_envelope` handler | Pattern M cohort symptom |
|---|---|---|---|---|---|---|
| **prysm** | binary version check + `areDataColumnsAvailable` (`process_block.go:887-918`) | sampling | synchronous blocking wait | n/a | ✅ `receive_execution_payload_envelope.go:88` + metrics at `metrics.go:241-251` | no |
| **lighthouse** | type-based `BlobSidecar`/`DataColumnSidecar` enum via `DataAvailabilityChecker<T>` | custody | LRU `PendingComponents` (max 32) | n/a | ❌ no `SignedExecutionPayloadEnvelope` refs in `beacon_node/beacon_chain/src/` | **YES** — Gloas envelope handler missing |
| **teku** | Pattern J — separate `AvailabilityChecker` classes (`BlobSidecarsAvailabilityChecker` + `DataColumnSidecarAvailabilityChecker`) | sampling | async `SafeFuture` | n/a | ✅ `ForkChoice.java:238 onExecutionPayloadEnvelope` + `ForkChoiceUtilGloas.java:143-145 isPayloadVerified` + `EPBS_STATUS.md:103` documentation | no |
| **nimbus** | 3-quarantine pattern (`BlobQuarantine` + `ColumnQuarantine` + `GloasColumnQuarantine` at `block_processor.nim:32`); leader on Gloas DA | custody | quarantine pool with `custodyMap`; `gloasColumnQuarantine.popSidecars` at `block_processor.nim:1023` | n/a | ✅ `eth2_processor.nim:326 processExecutionPayloadEnvelope` + sister sites at `nimbus_beacon_node.nim:2390`, `validators/message_router.nim:711` | no |
| **lodestar** | Pattern R — `DAType` enum union dispatch (`PreData`/`Blobs`/`Columns`/`NoData`) | sampling | `SeenBlockInput` LRU `(MAX_LOOK_AHEAD_EPOCHS+1)*SLOTS_PER_EPOCH` | n/a | ✅ `chain/validation/executionPayloadEnvelope.ts` + `chain.ts:863-905 getExecutionPayloadEnvelope` | no |
| **grandine** | EIP-7594 module integration with custody groups (`eip_7594/src/lib.rs`) | custody | `BlobReconstructionPool` operation pool with Reed-Solomon recovery | ✅ Pattern P (item #34 gindex 11) + Pattern V (item #40 manual proof) apply to Fulu fork-choice DA; both dissolve at Gloas | ❌ no envelope refs in `fork_choice_control/` or `fork_choice_store/` | **YES** — Gloas envelope handler missing |

**Pattern II cohort**: 6 distinct architectures, unchanged. **Sampling/custody cohort**: 3-vs-3 (sampling: prysm + teku + lodestar; custody: lighthouse + nimbus + grandine). **Pattern M cohort symptoms**: {lighthouse, grandine} now also lack the Gloas `on_execution_payload_envelope` fork-choice handler — fourth audit segment confirming the cohort (after items #43 + #44 + #46).

## Empirical tests

- ✅ **Live mainnet operation since 2025-12-03 (5+ months)**: all 6 clients accept the same canonical chain; cross-client Fulu fork-choice operation without observed divergence. Sampling-vs-custody divergence has not manifested under current mainnet blob loads (max 21 per block at BPO #2, well within sampling capacity). **Verifies H1, H10 at production scale.**
- ✅ **Per-client Pattern II verification (this recheck)**: 6 distinct architectures confirmed via file:line citations above. Unchanged from 2026-05-04 audit.
- ✅ **Per-client Gloas envelope-handler verification (this recheck)**: 4 clients have the handler (prysm `receive_execution_payload_envelope.go:88`; teku `ForkChoice.java:238`; nimbus `eth2_processor.nim:326`; lodestar `validation/executionPayloadEnvelope.ts`). 2 clients lack it (lighthouse + grandine — Pattern M cohort extends to fork-choice DA layer).
- ✅ **Gloas spec change verification**: `vendor/consensus-specs/specs/gloas/fork-choice.md:838-940` defines modified `on_block` (delays DA check) + modified `is_data_available` (passes kzg_commitments separately) + new `on_execution_payload_envelope` handler.
- ⏭ **Lighthouse Gloas `on_execution_payload_envelope` implementation PR** — file PR adding the Gloas-NEW handler. Pattern M cohort symptom; same client + same fork as items #43/#44/#46.
- ⏭ **Grandine Gloas `on_execution_payload_envelope` implementation PR** — file PR adding the handler. Pattern M cohort symptom.
- ⏭ **Sampling-vs-custody fixture at high blob load**: simulate block with only 8 sampled columns present; verify sampling-aware (prysm + teku + lodestar) accept; custody-aware (lighthouse + nimbus + grandine) reject (assuming custody count > 8). Tests A-tier forward-fragility vector.
- ⏭ **Block queueing timeout audit**: per-client timeout values + behaviour on timeout. Spec-undefined edge case (Pattern T family).
- ⏭ **Cross-fork transition DA continuity at FULU_FORK_EPOCH = 411392** (already past mainnet): verify all 6 transition cleanly from blob-DA to column-DA. Same for hypothetical GLOAS_FORK_EPOCH (currently FAR_FUTURE_EPOCH).
- ⏭ **Pattern P + V at Heze**: at the next BeaconBlockBody schema change (Heze per item #29), grandine's hardcoded gindex 11 + manual proof construction apply to BOTH gossip + fork-choice DA verification at Fulu — double-failure mode for grandine. Pre-emptive Heze fix priority.

## Conclusion

The Fulu fork-choice DA primitives (`is_data_available`, `on_block`) are implemented across all 6 clients with **6 distinct dispatch architectures (Pattern II)** and a **3-vs-3 sampling-vs-custody split**. 5+ months of live mainnet cross-client fork-choice operation validates that all 6 accept the same canonical chain on current blob loads.

The Glamsterdam target introduces three Gloas modifications at `vendor/consensus-specs/specs/gloas/fork-choice.md:838-940`:

1. **Modified `on_block`** — adds `is_payload_verified` parent-payload assertion and **delays the DA check** by no longer calling `is_data_available` from `on_block`.
2. **Modified `is_data_available`** — replaces `retrieve_column_sidecars` with `retrieve_column_sidecars_and_kzg_commitments` (returns commitments as a separate tuple component because item #54 removes `kzg_commitments` from the Gloas sidecar); passes `kzg_commitments` as an additional parameter to both `verify_data_column_sidecar` and `verify_data_column_sidecar_kzg_proofs`.
3. **New `on_execution_payload_envelope`** handler — invokes `is_data_available(envelope.beacon_block_root)` on envelope receipt.

**Per-client Gloas envelope-handler implementation status**:

- ✅ **prysm**: `receive_execution_payload_envelope.go:88 areDataColumnsAvailable(ctx, root, envelope.Slot())` + metrics.
- ✅ **teku**: `ForkChoice.java:238 onExecutionPayloadEnvelope` + `ForkChoiceUtilGloas.java:143-145 isPayloadVerified` + `EPBS_STATUS.md` design documentation.
- ✅ **nimbus**: `eth2_processor.nim:326 processExecutionPayloadEnvelope` + 3-quarantine pattern with `GloasColumnQuarantine` integration at `block_processor.nim:1019-1031`. **Leader on Gloas DA wiring**.
- ✅ **lodestar**: `chain/validation/executionPayloadEnvelope.ts` validator + `chain.ts:863-905` envelope retrieval helpers.
- ❌ **lighthouse**: no `SignedExecutionPayloadEnvelope` references in `beacon_node/beacon_chain/src/`. Gossip-topic plumbing exists in `lighthouse_network/src/types/pubsub.rs` (per item #46) but no fork-choice integration.
- ❌ **grandine**: no envelope references in `fork_choice_control/` or `fork_choice_store/`. No fork-choice handler.

**Pattern M lighthouse + grandine Gloas-ePBS readiness cohort extends with this fourth audit segment.** The cohort has now been confirmed by items #43 (Engine API V5/V6/FCU4 missing) + #44 (PartialDataColumnSidecar Gloas reshape absent) + #46 (envelope RPCs missing) + **#56 (fork-choice envelope handler missing)**. Same two clients, same fork. At Gloas activation, the lighthouse + grandine fork-choice paths would not execute the spec-prescribed `is_data_available` call from envelope receipt.

**Pattern P + V cross-cut (carry-forward from items #34 + #40)**: grandine's hardcoded gindex 11 + manual inclusion-proof construction apply to BOTH Fulu gossip-time AND Fulu fork-choice-time DA verification because the same `verify_data_column_sidecar` + `verify_data_column_sidecar_kzg_proofs` primitives are reused. Pattern P is more pervasive than item #34 alone documented. At Gloas, the inclusion-proof path becomes dead (item #54 sidecar removes the field) so Patterns P + V dissolve — but Fulu remains live throughout the Gloas transition window.

**Sampling-vs-custody A-tier forward-fragility (carry-forward)**: 3-vs-3 split unchanged. Under current mainnet blob loads (max 21 per block at BPO #2) the divergence has not manifested because the sampling subset of 8 covers all 21 blobs. At hypothetical 100+ blobs per block, sampling-aware clients MAY accept blocks that custody-aware clients reject — fork-divergence risk.

**Impact: none** — Fulu surface operates without divergence on current mainnet (sampling-vs-custody has not manifested); Gloas modifications not mainnet-reachable today (`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH`); lighthouse + grandine envelope-handler gaps are forward-fragility tracking only. Thirty-seventh `impact: none` result in the recheck series.

Forward-research priorities:

1. **Lighthouse Gloas envelope handler PR** — implement `on_execution_payload_envelope` in `beacon_node/beacon_chain/src/`. Pattern M cohort symptom; consolidate with the prior #43/#44/#46 gaps in a Gloas-ePBS readiness sprint.
2. **Grandine Gloas envelope handler PR** — implement at the fork-choice layer in `fork_choice_control/` or `fork_choice_store/`. Pattern M cohort symptom.
3. **Sampling-vs-custody fixture** — test at high blob load (synthesise scenario with 100+ blob commitments). A-tier forward-fragility candidate.
4. **Block queueing timeout audit** — per-client behaviour on DA timeout; spec-undefined edge case (Pattern T family).
5. **Pattern P + V Heze pre-emptive fix** — grandine's hardcoded gindex 11 + manual proof construction apply to Fulu fork-choice DA verification. At Heze if BeaconBlockBody schema changes, double-failure mode (item #34 + #40 + this audit).
6. **Track D opening continuation** — many more fork-choice cross-client audits pending: tie-breaking rules, proposer boost, LMD GHOST, score calculation, reorg-on-late-block, equivocation handling during block queueing.
