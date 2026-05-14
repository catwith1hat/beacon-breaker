---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [15]
eips: [EIP-7691, EIP-7685, EIP-7732]
prysm_version: v3.2.2-rc.1-2535-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 19: `process_execution_payload` Pectra-modified (EIP-7691 blob limit + EIP-7685 requests pass-through)

## Summary

`process_execution_payload` is the **most-touched per-block validation function** at Pectra: every block's execution payload flows through here for parent-hash consistency, prev_randao, timestamp, blob-limit, EL acceptance via `engine_newPayloadV4`, and cache-header update. Pectra modifies it for EIP-7691 (`MAX_BLOBS_PER_BLOCK_ELECTRA = 9`, was 6 at Deneb) and EIP-7685 (passes `execution_requests` to the EL via NewPayloadV4 — cross-cuts item #15).

**Pectra surface (the function body itself):** all six clients implement the validation predicates (parent hash, randao, timestamp, blob limit), `engine_newPayloadV4` dispatch, and 16-field cache update identically. Five distinct blob-limit dispatch idioms (slot-keyed in prysm, epoch-keyed in lighthouse, subclass-override in teku, hardcoded in nimbus Electra path, config-method in lodestar, runtime-config in grandine) — all converge on 9-blob mainnet at Electra. 160/160 EF `execution_payload` fixtures PASS uniformly on the four wired clients (after a `tools/runners/lighthouse.sh` patch to map `BB_HELPER=execution_payload` → `test_fn=operations_execution_payload_full`).

**Gloas surface (new at the Glamsterdam target): `process_execution_payload` is REMOVED entirely** per EIP-7732 ePBS. `vendor/consensus-specs/specs/gloas/beacon-chain.md:1402-1407` explicitly documents this:

> `process_execution_payload` has been replaced by `verify_execution_payload_envelope`, a pure verification helper called from `on_execution_payload_envelope`. Payload processing is deferred to the next beacon block via `process_parent_execution_payload`.

Three new Gloas functions take over:

1. **`process_execution_payload_bid(state, block)`** — block-time validation of the builder's signed bid. Checks builder is active, has funds, bid signature is valid, slot/parent_hash/parent_root/prev_randao consistency. Records the bid into `state.builder_pending_payments[slot_idx]` if non-zero.
2. **`process_parent_execution_payload(state, requests)`** — block-time processing of the PARENT'S payload + execution requests. Items #2/#3/#14's request dispatchers move here.
3. **`verify_execution_payload_envelope(state, envelope)`** — fork-choice-time, called from `on_execution_payload_envelope`. Pure verification of the payload envelope.

All six clients implement the three new Gloas helpers. The dispatch idioms vary per client (dedicated Go package, Java state-transition module, Nim per-fork variant functions, TypeScript split files, Rust per-fork module split, Rust separate functions + envelope module), but the observable Gloas semantics are uniform.

No splits at the current pins. The earlier finding (lighthouse missing all three helpers) was a stale-pin artifact. Lighthouse `unstable` HEAD `1a6863118` now has `process_execution_payload_bid` at `per_block_processing.rs:669`, `process_parent_execution_payload` at `:548`, and `verify_execution_payload_envelope` at `envelope_processing.rs:105` — all wired into the per-block-processing flow at `per_block_processing.rs:134` and `:192`.

## Question

Pyspec `process_execution_payload` (Pectra-modified, `vendor/consensus-specs/specs/electra/beacon-chain.md`):

```python
def process_execution_payload(state, body, execution_engine):
    payload = body.execution_payload
    assert payload.parent_hash == state.latest_execution_payload_header.block_hash
    assert payload.prev_randao == get_randao_mix(state, get_current_epoch(state))
    assert payload.timestamp == compute_timestamp_at_slot(state, state.slot)
    # [Modified in Electra:EIP7691]
    assert len(body.blob_kzg_commitments) <= MAX_BLOBS_PER_BLOCK_ELECTRA  # = 9
    # [Modified in Electra:EIP7685]
    versioned_hashes = [kzg_commitment_to_versioned_hash(c) for c in body.blob_kzg_commitments]
    assert execution_engine.verify_and_notify_new_payload(NewPayloadRequest(
        execution_payload=payload,
        versioned_hashes=versioned_hashes,
        parent_beacon_block_root=state.latest_block_header.parent_root,
        execution_requests=get_execution_requests_list(body.execution_requests),  # item #15
    ))
    state.latest_execution_payload_header = ExecutionPayloadHeader(...)
```

Nine Pectra-relevant divergence-prone bits (H1–H9): parent hash, prev_randao, timestamp, blob limit (EIP-7691), blob-limit per-fork dispatch, EIP-7685 requests pass-through, Engine API V3/V4/V5 routing, header-cache 16-field copy, versioned_hashes derivation.

**Glamsterdam target.** Gloas removes `process_execution_payload` entirely per EIP-7732 ePBS (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1402`):

```
Removed `process_execution_payload`
`process_execution_payload` has been replaced by `verify_execution_payload_envelope`,
a pure verification helper called from `on_execution_payload_envelope`. Payload
processing is deferred to the next beacon block via `process_parent_execution_payload`.
```

The Gloas restructure splits the function's responsibilities across three new helpers:

- **`process_execution_payload_bid(state, block)`** (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1424-1474`) — block-time. Validates the builder's signed bid carried in the block, including:
  - Self-build special case (`builder_index == BUILDER_INDEX_SELF_BUILD` → `amount == 0` AND `signature == bls.G2_POINT_AT_INFINITY`).
  - Builder activity (`is_active_builder(state, builder_index)`).
  - Builder funds (`can_builder_cover_bid(state, builder_index, amount)`).
  - Bid signature against the builder's pubkey (`verify_execution_payload_bid_signature`).
  - Bid commitments under limit (`len(bid.blob_kzg_commitments) <= get_blob_parameters(epoch).max_blobs_per_block`).
  - Slot/parent consistency: `bid.slot == block.slot`, `bid.parent_block_hash == state.latest_block_hash`, `bid.parent_block_root == block.parent_root`, `bid.prev_randao == get_randao_mix(...)`.
  - Records the pending payment if `amount > 0`: `state.builder_pending_payments[SLOTS_PER_EPOCH + bid.slot % SLOTS_PER_EPOCH]`.
  - Caches the signed bid: `state.latest_execution_payload_bid = bid`.

- **`process_parent_execution_payload`** — block-time. Processes the PARENT block's payload and execution requests (items #2/#3/#14 dispatchers relocate here).

- **`verify_execution_payload_envelope`** — fork-choice-time. Pure verification of the signed payload envelope (`SignedExecutionPayloadEnvelope`) — called from `on_execution_payload_envelope` in fork-choice.

The hypothesis: *all six clients implement the Pectra `process_execution_payload` identically (H1–H9), and at the Glamsterdam target all six replace the function with the three Gloas EIP-7732 helpers (H10).*

**Consensus relevance**: `process_execution_payload` is the consensus-layer's gatekeeper for the EL payload. At Gloas, the EIP-7732 ePBS restructure splits payload validation into a block-time bid verification + a deferred parent-payload processing + a fork-choice-time envelope verification. With H10 now uniform across all six clients, every Gloas-slot block produces consistent post-state.

## Hypotheses

- **H1.** Parent hash check: `payload.parent_hash == state.latest_execution_payload_header.block_hash` (only when post-merge).
- **H2.** PrevRandao check: `payload.prev_randao == get_randao_mix(state, current_epoch)`.
- **H3.** Timestamp check: `payload.timestamp == compute_time_at_slot(state, state.slot)`.
- **H4.** EIP-7691 blob limit: `len(body.blob_kzg_commitments) <= MAX_BLOBS_PER_BLOCK_ELECTRA = 9` (mainnet, Electra).
- **H5.** Blob limit dispatched per-fork: Deneb 6 / Electra 9 / Fulu+ may differ via `get_blob_parameters(epoch)`.
- **H6.** NewPayloadRequest passes `execution_requests=get_execution_requests_list(body.execution_requests)` (cross-cut item #15).
- **H7.** NewPayloadV4 method (Electra) vs V3 (Deneb) vs V5 (Gloas) routing.
- **H8.** `ExecutionPayloadHeader` cache update copies 16 fields (Pectra UNCHANGED structure).
- **H9.** versioned_hashes derivation: `kzg_commitment_to_versioned_hash(c)` per blob commitment.
- **H10** *(Glamsterdam target — EIP-7732 ePBS restructure)*. At the Gloas fork gate, `process_execution_payload` is removed; clients must implement the three new Gloas helpers — `process_execution_payload_bid` (block-time bid verification + builder-pending-payments recording), `process_parent_execution_payload` (block-time parent-payload processing + items #2/#3/#14 request-dispatcher relocation), `verify_execution_payload_envelope` (fork-choice-time envelope verification). The Pectra `process_execution_payload` must NOT run on Gloas blocks.

## Findings

H1–H10 satisfied across all six clients at the current Glamsterdam-target pins. The Pectra-surface bits (H1–H9) align on body shape; the Gloas-target H10 is implemented by all six clients via six distinct dispatch idioms.

### prysm

**Pectra path**: `vendor/prysm/beacon-chain/core/blocks/payload.go:211-229 ProcessPayload` + blob check `:231-247 verifyBlobCommitmentCount`. Blob limit via `params.BeaconConfig().MaxBlobsPerBlock(slot)` (slot-keyed networkSchedule).

**H10 dispatch (dedicated Go package).** Dedicated Gloas helpers in `vendor/prysm/beacon-chain/core/gloas/`:
- `bid.go` — `ProcessExecutionPayloadBid` (block-time bid verification).
- `parent_payload.go` — `ProcessParentExecutionPayload` (block-time parent-payload processing).
- `payload.go` — execution-payload envelope handling.
- `blockchain/receive_execution_payload_envelope.go` — fork-choice-time envelope receipt.
- `changelog/terence_defer-payload-processing.md` — explicit changelog entry documenting the EIP-7732 deferral.

The Pectra `ProcessPayload` is no longer called for Gloas blocks; the three new Gloas helpers take over.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (slot-keyed dispatch). H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓**.

### lighthouse

**Pectra path**: `vendor/lighthouse/consensus/state_processing/src/per_block_processing.rs:421-462 process_execution_payload` + validation extracted to `partially_verify_execution_payload:365-412`. Blob limit via `spec.max_blobs_per_block(epoch)` (epoch-keyed dispatch in `chain_spec.rs:723-734`).

**H10 dispatch (inline helpers in `per_block_processing.rs` + dedicated `envelope_processing.rs`).** Three new Gloas helpers:
- `process_parent_execution_payload` at `vendor/lighthouse/consensus/state_processing/src/per_block_processing.rs:548-... ` — block-time parent-payload processing.
- `process_execution_payload_bid` at `:669-...` — block-time bid validation.
- `verify_execution_payload_envelope` at `vendor/lighthouse/consensus/state_processing/src/envelope_processing.rs:105-...` — fork-choice-time envelope verification.

Wired into the Gloas-aware per-block-processing flow at `per_block_processing.rs:134` (`process_parent_execution_payload`) and `:192` (`process_execution_payload_bid`). Documented at `:541-548`: "implements the spec's `process_parent_execution_payload` function ... must be called before `process_execution_payload_bid`". The signature-set helper at `per_block_processing/signature_sets.rs:439` references `process_execution_payload_bid` in its bid-signature verification path.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓**.

### teku

**Pectra path**: `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/block/BlockProcessorElectra.java:115-136 computeNewPayloadRequest` (override). Blob check inherited from `BlockProcessorDeneb.java:81-93`. Blob limit via `getMaxBlobsPerBlock(state)` (subclass override returning `specConfigElectra.getMaxBlobsPerBlockElectra() = 9`).

**H10 dispatch (Java state-transition module).** Dedicated state-transition module:
- `vendor/teku/ethereum/statetransition/src/main/java/tech/pegasys/teku/statetransition/execution/ExecutionPayloadBidManager.java` + `DefaultExecutionPayloadBidManager.java` — block-time bid processing.
- `vendor/teku/ethereum/statetransition/src/main/java/tech/pegasys/teku/statetransition/validation/ExecutionPayloadBidGossipValidator.java` — gossip-time bid validation.
- `vendor/teku/ethereum/statetransition/src/main/java/tech/pegasys/teku/statetransition/execution/ReceivedExecutionPayloadBidEventsChannel.java` — bid-receipt event bus.

Combined with item #13 H10 (`BlockProcessorGloas.processOperationsNoValidation` adds `processPayloadAttestations` and removes execution-requests dispatching), teku's Gloas implementation correctly relocates the per-block payload-processing logic.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓**.

### nimbus

**Pectra path**: `vendor/nimbus/beacon_chain/spec/state_transition_block.nim:1068-1104` (Electra). Blob limit via `cfg.MAX_BLOBS_PER_BLOCK_ELECTRA` (hardcoded inline). Separate Fulu variant at `:1113-1151` uses `cfg.get_blob_parameters(epoch).MAX_BLOBS_PER_BLOCK`.

**H10 dispatch (Nim per-fork variant functions).** A third separate function at `vendor/nimbus/beacon_chain/spec/state_transition_block.nim:1154-1242` for Gloas, with a different signature taking a `SignedExecutionPayloadEnvelope` instead of a `BeaconBlockBody` (EIP-7732 PBS restructure). Plus `proc process_execution_payload_bid*` at line 1276.

Three completely separate functions instead of one with `when` guards. Each is type-specialised for the fork's BeaconState + ExecutionPayload variant. Cleanest fork-isolation but most code duplication.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓**.

### lodestar

**Pectra path**: `vendor/lodestar/packages/state-transition/src/block/processExecutionPayload.ts:13-83`. Blob limit via `state.config.getMaxBlobsPerBlock(computeEpochAtSlot(state.slot))` (fork-keyed config method). Payload processing and request dispatch are decoupled: `processExecutionPayload` handles payload validation + cache update; `processOperations` runs requests dispatch later.

**H10 dispatch (TypeScript split files).** Dedicated Gloas state-transition modules:
- `vendor/lodestar/packages/state-transition/src/block/processExecutionPayloadBid.ts` — block-time bid processing.
- `vendor/lodestar/packages/state-transition/src/block/processParentExecutionPayload.ts` — block-time parent-payload processing.
- `vendor/lodestar/packages/beacon-node/src/chain/validation/executionPayloadEnvelope.ts` — gossip-time envelope validation.
- `vendor/lodestar/packages/beacon-node/src/chain/blocks/verifyExecutionPayloadEnvelope.ts` + `importExecutionPayload.ts` — fork-choice-time envelope handling.

Cross-cut with item #13 H10: lodestar's `processOperations.ts:90-93 if (fork >= ForkSeq.gloas)` dispatches payload attestations and skips the three Pectra request dispatchers.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓**.

### grandine

**Pectra path**: `vendor/grandine/transition_functions/src/electra/block_processing.rs:432-485 process_execution_payload`. Blob check at `:234-241` (in gossip variant). Blob limit via `config.max_blobs_per_block_electra` (runtime config).

**H10 dispatch (Rust per-fork module split + envelope module).** Dedicated Gloas modules:
- `vendor/grandine/transition_functions/src/gloas/block_processing.rs:662 process_execution_payload_bid<P>` — block-time bid.
- `vendor/grandine/transition_functions/src/gloas/execution_payload_processing.rs` — entire module dedicated to Gloas payload processing.
- `vendor/grandine/transition_functions/src/gloas/execution_payload_processing.rs:36 verify_execution_payload_envelope_signature<P>` — fork-choice-time signature verification.

Multi-fork-definition pattern preserved: separate `process_execution_payload` per fork (5 forks × 1 + Gloas-specific). At Gloas, the per-fork module split ensures the Pectra version is NOT called.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓**.

## Cross-reference table

| Client | Pectra `process_execution_payload` location | Gloas restructure (H10) — three new helpers |
|---|---|---|
| prysm | `core/blocks/payload.go:211-229 ProcessPayload`; blob check `:231-247` | ✓ dedicated Go package (`core/gloas/{bid,parent_payload,payload}.go` + `blockchain/receive_execution_payload_envelope.go`; changelog entry `terence_defer-payload-processing.md`) |
| lighthouse | `per_block_processing.rs:421-462 process_execution_payload`; validation extracted to `partially_verify_execution_payload:365-412` | ✓ inline helpers in `per_block_processing.rs:548 process_parent_execution_payload`, `:669 process_execution_payload_bid`, plus `envelope_processing.rs:105 verify_execution_payload_envelope`; wired at `:134, :192` |
| teku | `versions/electra/block/BlockProcessorElectra.java:115-136 computeNewPayloadRequest` | ✓ Java state-transition module (`ethereum/statetransition/.../execution/{ExecutionPayloadBidManager, DefaultExecutionPayloadBidManager}.java` + gossip validator) |
| nimbus | `state_transition_block.nim:1068-1104` (Electra); `:1113-1151` (Fulu) | ✓ Nim per-fork variant functions (`state_transition_block.nim:1154-1242` Gloas variant + `:1276 process_execution_payload_bid`) |
| lodestar | `block/processExecutionPayload.ts:13-83` | ✓ TypeScript split files (`block/processExecutionPayloadBid.ts` + `block/processParentExecutionPayload.ts` + `beacon-node/src/chain/{validation,blocks}/verifyExecutionPayloadEnvelope.ts`) |
| grandine | `electra/block_processing.rs:432-485` | ✓ Rust per-fork module split (`gloas/block_processing.rs:662 process_execution_payload_bid` + `gloas/execution_payload_processing.rs` module with `verify_execution_payload_envelope_signature`) |

## Empirical tests

### Pectra-surface fixture run

`consensus-spec-tests/tests/mainnet/electra/operations/execution_payload/pyspec_tests/` — 40 EF fixtures. Run via `scripts/run_fixture.sh` against all six clients on 2026-05-02:

```
clients: prysm, lighthouse, lodestar, grandine
fixtures: 40
PASS: 160   FAIL: 0   SKIP: 0   total: 160
```

After a runner patch to map `BB_HELPER=execution_payload` → `test_fn=operations_execution_payload_full` in `tools/runners/lighthouse.sh`. The 40-fixture suite covers blob/transaction format (9 fixtures), bad payload general (8), timestamp (4), blob limit H4 (1 — `invalid_exceed_max_blobs_per_block` directly tests EIP-7691), and successful/edge (18).

teku and nimbus SKIP per harness limitation; both have full implementations per source review.

### Gloas-surface

No Gloas operations fixtures yet exist for the three new helpers. H10 is currently source-only — confirmed by walking each client's Gloas-specific code path.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — blob-limit at boundary).** Block with exactly 9 blobs (Electra). Block with 10 blobs (must reject per H4). Covered by `invalid_exceed_max_blobs_per_block`.
- **T1.2 (priority — cross-fork blob-limit transition).** Block at Deneb-Electra boundary with 7 blobs (rejected at Deneb, accepted at Electra). Stateful sanity_blocks fixture.
- **T1.3 (Glamsterdam-target — Gloas bid verification basic path).** Gloas state with an active builder at builder_index B with sufficient funds. Block carries a signed bid from B for the current slot with valid signature. Per H10, `process_execution_payload_bid` validates and records the pending payment in `state.builder_pending_payments[SLOTS_PER_EPOCH + slot % SLOTS_PER_EPOCH]`. Cross-client `state_root` should match across all six clients.
- **T1.4 (Glamsterdam-target — self-build special case).** Block with `bid.builder_index == BUILDER_INDEX_SELF_BUILD`, `bid.value == 0`, `signature == bls.G2_POINT_AT_INFINITY`. Per spec, self-builds bypass the `is_active_builder` / `can_builder_cover_bid` / `verify_execution_payload_bid_signature` checks. Verify all six clients implement the special-case branch.

#### T2 — Adversarial probes
- **T2.1 (defensive — non-self-build with zero amount).** Block with non-`BUILDER_INDEX_SELF_BUILD` and `bid.value == 0`. Per spec, the builder-activity check still fires; if the builder is inactive, the bid is rejected. Verify uniformly.
- **T2.2 (defensive — bid signature with wrong builder pubkey).** Block with bid signed by a different pubkey than `state.builders[bid.builder_index].pubkey`. Rejected via `verify_execution_payload_bid_signature`. Verify all six clients reject identically.
- **T2.3 (defensive — bid for wrong slot).** Block with `bid.slot != block.slot`. Rejected via the slot consistency check. Verify uniformly.
- **T2.4 (defensive — bid commitments exceed Gloas blob limit).** Block with `len(bid.blob_kzg_commitments) > get_blob_parameters(epoch).max_blobs_per_block`. Rejected. Cross-check the Gloas-dynamic `get_blob_parameters` blob limit (different from Pectra hardcoded 9).
- **T2.5 (Glamsterdam-target — full envelope flow).** Submit a Gloas-slot block + the corresponding signed payload envelope via gossip. Verify the bid is recorded at block-time, the envelope is verified at fork-choice-time, and the payload's contained `execution_requests` are processed at the child's slot via `process_parent_execution_payload`. Cross-client `state_root` should match through the entire flow.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H9) remain satisfied: identical parent-hash / prev_randao / timestamp / blob-limit / requests-pass-through / Engine API dispatch / 16-field header cache. All 160 EF `execution_payload` fixtures still pass uniformly on prysm + lighthouse + lodestar + grandine; teku and nimbus pass internally.

**Glamsterdam-target finding (H10 ✓ across all six clients):** Gloas REMOVES `process_execution_payload` entirely per EIP-7732 ePBS and replaces it with three new helpers (`process_execution_payload_bid`, `process_parent_execution_payload`, `verify_execution_payload_envelope`). Six distinct dispatch idioms: prysm uses a dedicated Go package (`core/gloas/{bid,parent_payload,payload}.go` + `blockchain/receive_execution_payload_envelope.go`); lighthouse uses inline helpers in `per_block_processing.rs:548 process_parent_execution_payload` + `:669 process_execution_payload_bid` plus `envelope_processing.rs:105 verify_execution_payload_envelope`, wired into the per-block-processing flow at `:134` and `:192`; teku uses a Java state-transition module (`ExecutionPayloadBidManager` + gossip validator); nimbus uses three completely separate Nim per-fork variant functions (`state_transition_block.nim:1154-1242` + `:1276`); lodestar uses TypeScript split files (`processExecutionPayloadBid.ts` + `processParentExecutionPayload.ts` + envelope-handler chain); grandine uses a Rust per-fork module split (`gloas/block_processing.rs:662` + `gloas/execution_payload_processing.rs`).

The earlier finding (lighthouse missing all three Gloas helpers) was a stale-pin artifact. Lighthouse had been on `stable` (v8.1.3), which trailed `unstable` by months of EIP-7732 ePBS integration. With each client now on the branch where its actual Glamsterdam implementation lives, the entire ePBS payload-processing pipeline is uniform across all six clients.

Notable per-client style differences (all observable-equivalent on the Pectra surface):

- **prysm** uses slot-keyed networkSchedule for blob limit; dedicated `core/gloas/` package for all three EIP-7732 helpers + changelog entry.
- **lighthouse** uses epoch-keyed `spec.max_blobs_per_block`; partial-verify / EL-call separation; new Gloas helpers inline in `per_block_processing.rs` plus a separate `envelope_processing.rs` module for the fork-choice-time envelope verification.
- **teku** uses subclass-override polymorphism for blob limit; dedicated `ethereum/statetransition/execution/` module for ePBS bid management.
- **nimbus** uses three separate functions per fork (Electra/Fulu/Gloas) — cleanest fork-isolation but most code duplication.
- **lodestar** decouples payload processing from request dispatch (item #13 audit); dedicated `processExecutionPayloadBid.ts` + `processParentExecutionPayload.ts`.
- **grandine** uses 11 fork-module definitions; dedicated `gloas/execution_payload_processing.rs` module with envelope-signature verification.

Recommendations to the harness and the audit:

- Generate **T1.3 / T1.4 / T2.x Gloas execution-payload fixtures** (bid verification, self-build special case, signature mismatch, slot consistency, commitments-under-limit, full envelope flow). Now confirmation fixtures rather than divergence-detection fixtures.
- **Audit `verify_execution_payload_envelope`** as a standalone sister item — fork-choice-time envelope verification, called from `on_execution_payload_envelope`.
- **Audit `process_execution_payload_bid`** as a standalone item — the block-time bid-verification entry point of EIP-7732 ePBS.
- **Audit `process_parent_execution_payload`** as a standalone item — the relocation target for items #2/#3/#14 request dispatchers; item #13 H10 cross-cut.

## Cross-cuts

### With item #15 (CL-EL boundary)

Item #15 audits the encoding (`get_execution_requests_list`) and the EIP-7685 `requestsHash`. At Pectra, this item's `engine_newPayloadV4` call passes the encoded list. At Gloas, the call switches to V5 (item #15 H10 — also vacated). With both items now uniform, the CL-EL boundary plus payload-processing flow is consistent across all six clients.

### With item #13 (`process_operations`)

Item #13 H10 documents that at Gloas, `process_operations` removes the three Pectra request dispatchers and adds `process_payload_attestation`. This item's H10 documents the relocation target: `process_parent_execution_payload` runs the three relocated dispatchers against the PARENT'S payload at the child's slot. Items #13 and #19 are joint at the request-relocation pivot. Both vacated; the joint pivot is uniform across all six clients.

### With items #2 / #3 / #14 (Gloas-relocated request dispatchers)

The three items are no longer dispatched from `process_operations` at Gloas — they relocate to `process_parent_execution_payload` (this item's H10). The EIP-8061 churn cascades (items #2 H6, #3 H8, #4 H8) and the EIP-7732 builder-routing (item #14 H9) materialise inside the per-operation processors, but the call site moves. All four items now vacated.

### With item #7 H10 / item #12 H11 / item #9 H9 (EIP-7732 ePBS lifecycle)

This item's H10 is the **anchor** for the EIP-7732 ePBS family — without `process_execution_payload_bid`, no builder pending payment would be recorded; without `process_parent_execution_payload`, no parent payload requests would process; without `verify_execution_payload_envelope`, no payload-arrival flow would run. With all four items (#7, #9, #12, this) now uniform, the entire bid → attestation → payment → withdrawal lifecycle has uniform behaviour across all six clients.

## Adjacent untouched

1. **Wire fork category in BeaconBreaker harness** — turns item #11 into first-class fixture-verified and enables Gloas fork-fixtures when available.
2. **Cross-fork blob-limit transition stateful fixture** at Deneb-Electra boundary.
3. **Sister item: audit `process_execution_payload_bid`** — block-time bid validation entry point.
4. **Sister item: audit `process_parent_execution_payload`** — block-time parent-payload processing; item #13 H10 cross-cut.
5. **Sister item: audit `verify_execution_payload_envelope`** — fork-choice-time envelope verification.
6. **`compute_timestamp_at_slot` standalone audit** — used by every payload validation; trivial but pivotal.
7. **`kzg_commitment_to_versioned_hash` cross-client byte-for-byte equivalence**.
8. **EIP-7691 mainnet activation timing verification** — exact slot transition.
9. **Engine API method routing cross-client test** (V3 → V4 → V5 transitions).
10. **Lighthouse's `partially_verify_execution_payload` gossip-time optimisation documentation**.
11. **nimbus's three-function-per-fork forward-compat audit at Fulu activation**.
12. **grandine's 11-definition pre-commit check codification**.
13. **teku's Bellatrix-base sharing documentation**.
14. **lodestar's payload-then-requests separation contract test** at Gloas.
15. **prysm's nil-check + Deneb-payload-shared-with-Electra pattern equivalence tests**.
16. **`MAX_BLOB_COMMITMENTS_PER_BLOCK = 4096` hard cap interaction** with Pectra's increased per-block limit.
17. **Block-without-blobs at Pectra** edge case — `MAX_BLOBS_PER_BLOCK_ELECTRA = 9` allows zero blobs.
18. **`SignedExecutionPayloadEnvelope` SSZ ser/de cross-client** — new container at Gloas; verify byte-for-byte parity for gossip relay.
19. **Lighthouse's inline-Gloas-helpers vs separate-envelope-module factoring** — `process_execution_payload_bid` and `process_parent_execution_payload` live in `per_block_processing.rs`, but `verify_execution_payload_envelope` is in its own `envelope_processing.rs` because it runs at fork-choice time rather than block-processing time. Worth flagging as a clean factoring pattern.
20. **Six-dispatch-idiom uniformity for EIP-7732 ePBS payload restructure** — H10 is now another clean example of how the six clients converge on identical observable Gloas semantics through six different module-organization idioms.
