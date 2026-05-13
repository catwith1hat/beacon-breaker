---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [15, 19, 28, 31]
eips: [EIP-7892, EIP-7732]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 32: `process_execution_payload` Fulu-modified (item #19 Fulu equivalent; REMOVED at Gloas)

## Summary

`process_execution_payload(state, body, execution_engine)` Fulu-modified replaces the hardcoded `MAX_BLOBS_PER_BLOCK_ELECTRA = 9` with `get_blob_parameters(get_current_epoch(state)).max_blobs_per_block`. The rest of the function is Electra-inherited (parent_hash + prev_randao + timestamp + blob-limit + versioned-hashes + `notify_new_payload` + 16-field `ExecutionPayloadHeader` cache).

**Fulu surface (carried forward from 2026-05-04 audit; CURRENT mainnet target):** all six clients implement EIP-7892 BPO integration byte-for-byte equivalently. Mainnet Fulu has executed two BPO transitions in production (9 → 15 at epoch 412672, 2025-12-09; → 21 at epoch 419072, 2026-01-07) without chain split — live validation of the per-client implementations.

Per-client divergences entirely in: function structure (subclass extension in teku; multi-fork-definition in nimbus + grandine; single function in lighthouse + lodestar; helper extraction in prysm); gossip-time optimisation (lighthouse `partially_verify_execution_payload`; grandine `process_execution_payload_for_gossip`); blob-limit lookup path (prysm pre-computed `networkSchedule`; lighthouse `spec.max_blobs_per_block`; teku polymorphic `getMaxBlobsPerBlock`; nimbus direct `cfg.get_blob_parameters`; lodestar `state.config.getMaxBlobsPerBlock`; grandine `config.get_blob_schedule_entry`); fork-gating idiom.

**Gloas surface (at the Glamsterdam target): function REMOVED.** `vendor/consensus-specs/specs/gloas/beacon-chain.md:92, 1402-1407` — `process_execution_payload` is **REMOVED at Gloas under EIP-7732 ePBS**. Replaced by THREE Gloas-NEW functions:
- `process_execution_payload_bid` (`:1424-1474`) — validates the SignedExecutionPayloadBid at block-processing time. Consumes `get_blob_parameters(...).max_blobs_per_block` at `:1448` (the blob-limit check moves from `process_execution_payload` here).
- `verify_execution_payload_envelope` (`vendor/consensus-specs/specs/gloas/beacon-chain.md` referenced from `:1404-1407`) — pure verification helper called from `on_execution_payload_envelope`. Validates the envelope signature, parent-block-root, blob commitments, etc.
- `apply_parent_execution_payload` (`:1108, 1116`) — processes parent payload's execution requests (deposits, withdrawals, consolidations) at the CURRENT block (deferred payload processing).

**Per-client Gloas-cohort status (item #28 Pattern M reaffirmation):** 5 of 6 clients have wired the Gloas ePBS surface; **lighthouse is missing all three replacement functions**. Reaffirms item #28 Pattern M cohort gap (item #19 H10 symptom).

| Client | `process_execution_payload_bid` | `apply_parent_execution_payload` | `verify_execution_payload_envelope` |
|---|---|---|---|
| prysm | `core/gloas/bid.go` ✓ | `core/gloas/parent_payload.go` ✓ | `core/gloas/payload.go` ✓ |
| lighthouse | **MISSING** ✗ | **MISSING** ✗ | **MISSING** ✗ |
| teku | `versions/gloas/execution/ExecutionPayloadVerifierGloas` + bid validator ✓ | `versions/gloas/...` ✓ | `versions/gloas/execution/` ✓ |
| nimbus | `state_transition_block.nim:1276 process_execution_payload_bid` ✓ | (in same Gloas surface) ✓ | `:1165-1175 verify_execution_payload_envelope_signature` ✓ |
| lodestar | `block/processExecutionPayloadBid.ts` ✓ | `block/processParentExecutionPayload.ts` ✓ | (in same Gloas surface) ✓ |
| grandine | `transition_functions/src/gloas/block_processing.rs:662 process_execution_payload_bid` ✓ | (in same Gloas module) ✓ | `transition_functions/src/gloas/execution_payload_processing.rs:36 verify_execution_payload_envelope_signature` ✓ |

**Mainnet activation status**: `GLOAS_FORK_EPOCH = 18446744073709551615` (FAR_FUTURE_EPOCH) per `vendor/consensus-specs/configs/mainnet.yaml:60`. Gloas not yet scheduled. The Fulu-modified `process_execution_payload` continues operating on mainnet; the Gloas removal/replacement is source-level only.

**Impact: none** at THIS item's Fulu surface (the audit target is the Fulu-modified function). The Gloas-side removal/replacement maps to:
- Item #19 H10 (lighthouse Gloas-ePBS readiness gap) — separate item.
- Item #28 Pattern M (lighthouse cohort: 7 → 8 symptoms when item #32 adds `process_execution_payload_bid` / `apply_parent_execution_payload` / `verify_execution_payload_envelope` to the missing set) — meta-tracking item.

Fourteenth impact-none result in the recheck series for this item's audit target (the Fulu-modified function).

## Question

Pyspec Fulu-Modified (`vendor/consensus-specs/specs/fulu/beacon-chain.md`, single-line change from Electra):

```python
def process_execution_payload(state: BeaconState, body: BeaconBlockBody, execution_engine: ExecutionEngine) -> None:
    payload = body.execution_payload
    # Verify consistency of the parent hash with respect to the previous execution payload header
    assert payload.parent_hash == state.latest_execution_payload_header.block_hash
    # Verify prev_randao
    assert payload.prev_randao == get_randao_mix(state, get_current_epoch(state))
    # Verify timestamp
    assert payload.timestamp == compute_timestamp_at_slot(state, state.slot)
    # [Modified in Fulu:EIP7892] — dynamic blob limit
    assert len(body.blob_kzg_commitments) <= get_blob_parameters(get_current_epoch(state)).max_blobs_per_block
    # ... versioned_hashes, notify_new_payload, header cache ...
```

At Gloas: function REMOVED. Replaced by:

```python
# vendor/consensus-specs/specs/gloas/beacon-chain.md:1424-1474
def process_execution_payload_bid(state: BeaconState, block: BeaconBlock) -> None:
    signed_bid = block.body.signed_execution_payload_bid
    bid = signed_bid.message
    # ... builder validity + bid signature ...
    # Verify commitments are under limit (BPO check moved here from process_execution_payload)
    assert len(bid.blob_kzg_commitments) <= get_blob_parameters(get_current_epoch(state)).max_blobs_per_block
    # ... parent_block_hash, prev_randao, slot, BuilderPendingPayment record, cache latest_execution_payload_bid ...
```

Plus `verify_execution_payload_envelope` (envelope-time validation) and `apply_parent_execution_payload` (parent-payload execution-requests routing).

Three recheck questions:
1. Fulu-surface invariants (H1–H10 from prior audit) — do all six clients still implement the dynamic blob limit correctly?
2. **At Gloas (the new target)**: is `process_execution_payload` REMOVED from the state-transition path in all six clients? Which Gloas-NEW replacement functions are wired?
3. Does the lighthouse Gloas-ePBS cohort gap (item #28 Pattern M) extend to the three replacement functions audited here?

## Hypotheses

- **H1.** Read blob limit from `get_blob_parameters(get_current_epoch(state)).max_blobs_per_block` (NOT hardcoded `MAX_BLOBS_PER_BLOCK_ELECTRA`).
- **H2.** `len(body.blob_kzg_commitments) <= max_blobs_per_block` (using `<=`, NOT `<`).
- **H3.** Check ordering: parent_hash → prev_randao → timestamp → blob limit → versioned hashes → notify_new_payload → cache header.
- **H4.** `versioned_hashes = [kzg_commitment_to_versioned_hash(c) for c in body.blob_kzg_commitments]`.
- **H5.** `state.latest_execution_payload_header` cached as 16-field `ExecutionPayloadHeader` (Pectra UNCHANGED at Fulu).
- **H6.** Engine API method routing: `engine_newPayloadV5` at Fulu+ (vs V4 at Electra). Cross-cut to item #15.
- **H7.** `compute_timestamp_at_slot` semantics consistent across forks.
- **H8.** Notify payload via execution engine — failure aborts state transition.
- **H9.** Pre-Deneb branch: skip blob commitment check.
- **H10.** Fulu-MODIFIED scope = ONE line change (blob limit source); rest is Electra-inherited.
- **H11.** *(Glamsterdam target — function REMOVED at Gloas)*. `process_execution_payload` is REMOVED at Gloas per `vendor/consensus-specs/specs/gloas/beacon-chain.md:92, 1402-1407`. No Fulu-Modified body survives at Gloas. The Fulu-surface audit target ceases to exist as a stand-alone function at Gloas.
- **H12.** *(Glamsterdam target — three Gloas-NEW replacement functions)*. Spec replaces with `process_execution_payload_bid` (bid-time validation including the BPO blob-limit check), `verify_execution_payload_envelope` (envelope-time validation), and `apply_parent_execution_payload` (parent-payload execution-requests routing). All three are GLOAS-NEW (no Fulu equivalent).
- **H13.** *(Glamsterdam target — lighthouse Gloas-ePBS cohort gap reaffirmation)*. Five of six clients (prysm, teku, nimbus, lodestar, grandine) wire the three Gloas-NEW replacement functions. **Lighthouse is MISSING all three** — reaffirms item #28 Pattern M cohort. Lighthouse cannot process Gloas blocks without the replacements.
- **H14.** *(Glamsterdam target — mainnet activation not yet scheduled)*. `GLOAS_FORK_EPOCH = 18446744073709551615` (FAR_FUTURE_EPOCH) per `mainnet.yaml:60`. The Fulu-modified function continues operating on mainnet; the Gloas removal/replacement is source-level only.

## Findings

H1–H14 satisfied. **No state-transition divergence at the Fulu surface across all six clients; Gloas removal documented; lighthouse Pattern M cohort gap reaffirmed.**

### prysm

`vendor/prysm/beacon-chain/core/blocks/payload.go` consumes `verifyBlobCommitmentCount(slot, body)` at item #31's two-layer cached lookup (`params.BeaconConfig().MaxBlobsPerBlock(slot)`). Called from four sites: `core/blocks/payload.go:241`, `blockchain/process_block.go:837`, `blockchain/service.go:119/149`, `core/peerdas/p2p_interface.go:52`.

**Gloas replacement implementations:**
- `vendor/prysm/beacon-chain/core/gloas/bid.go` — `process_execution_payload_bid` (spec at `:21-22`). Implements the bid-time validation including the BPO blob-limit check per `vendor/consensus-specs/specs/gloas/beacon-chain.md:1448`.
- `vendor/prysm/beacon-chain/core/gloas/parent_payload.go` — `apply_parent_execution_payload` (spec at `:62`). Implements the parent-payload execution-requests routing per `:1108, 1116`.
- `vendor/prysm/beacon-chain/core/gloas/payload.go` — `verify_execution_payload_envelope` + `verify_execution_payload_envelope_signature` (spec at `:24, 229`). Implements envelope-time validation.

Plus `bid_test.go`, `payload_test.go`, `parent_payload_test.go` for cross-client validation.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓ (V5 wired per item #15). H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓ (Gloas removal acknowledged). H12 ✓ (all three replacements wired). **H13 ✓** (prysm in the 5-of-6 cohort with full Gloas wiring). H14 ✓.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing.rs:380 partially_verify_execution_payload` (gossip-time optimisation, parent_hash + randao + timestamp + blob limit without EL round-trip) + `:421 process_execution_payload` (full validation including `notify_new_payload`). Blob limit via `spec.max_blobs_per_block(block_slot.epoch(E::slots_per_epoch())) as usize`.

**Gloas replacement implementations: ALL MISSING.** Search for `process_execution_payload_bid`, `apply_parent_execution_payload`, `verify_execution_payload_envelope` across `vendor/lighthouse/consensus/state_processing/src/` returns NOTHING. Lighthouse has only the Fulu-modified `process_execution_payload` and the basic Gloas upgrade scaffolding (`upgrade/gloas.rs`).

**Lighthouse cannot process Gloas blocks containing**: builder bid validation (`process_execution_payload_bid`), parent-payload execution requests (`apply_parent_execution_payload`), or payload envelopes (`verify_execution_payload_envelope`). Lighthouse falls off the canonical Gloas chain at activation.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓ (Fulu surface correct). **H11 ✗** (Gloas removal not acknowledged in source — Fulu function persists but Gloas replacement absent). **H12 ✗** (all three replacements MISSING). **H13 ✗** (lighthouse IS the cohort gap — item #28 Pattern M reaffirmation). H14 ✓.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/fulu/block/BlockProcessorFulu.java:73 getMaxBlobsPerBlock(state)` override (calls `miscHelpersFulu.getBlobParameters(epoch).maxBlobsPerBlock()`). `processExecutionPayload` body INHERITED from `BlockProcessorDeneb` polymorphic dispatch.

**Gloas replacement implementations** in `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/`:
- `execution/ExecutionPayloadVerifierGloas.java` — envelope verification.
- `execution/ExecutionRequestsProcessorGloas.java` — parent payload execution requests.
- `operations/ProcessExecutionPayloadBidValidator.java` — bid validation.
- Plus `block/`, `forktransition/`, `helpers/`, `statetransition/`, `util/`, `withdrawals/` subpackages.

Teku has the FULL Gloas ePBS surface wired. Subclass-extension pattern from Fulu's `BlockProcessorFulu extends BlockProcessorElectra` continues at Gloas (presumably `BlockProcessorGloas extends BlockProcessorFulu` or analogous).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓. **H13 ✓** (teku in the 5-of-6 cohort with full Gloas wiring; further reaffirms that "teku is the laggard" framing is OUTDATED per items #28 + #29 + #30 findings). H14 ✓.

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:1113 process_execution_payload(cfg, state: var fulu.BeaconState, body, notify_new_payload)` — Fulu-specific overload (line 1113-1151). One of 6 overloads total (Bellatrix/Capella/Deneb/Electra/Fulu/Gloas at lines 962/992/1027/1068/1113/1154). Blob limit via `cfg.get_blob_parameters(get_current_epoch(state)).MAX_BLOBS_PER_BLOCK`.

**Gloas replacement implementations:**
- `vendor/nimbus/beacon_chain/spec/state_transition_block.nim:1276 process_execution_payload_bid*(cfg, state: var gloas.BeaconState, blck: ...)` (spec at `:1275`). Wired in main block-processing flow at `:1770`.
- `vendor/nimbus/beacon_chain/spec/state_transition_block.nim:1165-1175 verify_execution_payload_envelope_signature` (spec at `:1165`).
- `apply_parent_execution_payload` — in the Gloas-specific block-processing flow (line 1154+).

The nimbus 6th overload of `process_execution_payload` at line 1154 (for `gloas.HashedBeaconState`) handles the Gloas-specific signed envelope path — multi-fork-definition Pattern I.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓ (all three replacements wired, plus the 6th overload). **H13 ✓** (nimbus in the 5-of-6 cohort). H14 ✓.

### lodestar

`vendor/lodestar/packages/state-transition/src/block/processExecutionPayload.ts:13 processExecutionPayload(fork, state, body, externalData)` — single function with ForkSeq dispatch. Blob limit via `state.config.getMaxBlobsPerBlock(computeEpochAtSlot(state.slot))`.

**Gloas replacement implementations:**
- `vendor/lodestar/packages/state-transition/src/block/processExecutionPayloadBid.ts` — `process_execution_payload_bid` for Gloas.
- `vendor/lodestar/packages/state-transition/src/block/processParentExecutionPayload.ts` — `apply_parent_execution_payload` per spec reference at `:45` (`v1.7.0-alpha.6/specs/gloas/beacon-chain.md#new-apply_parent_execution_payload`).

`verify_execution_payload_envelope` integrated in the same Gloas-surface processing.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓. **H13 ✓** (lodestar in the 5-of-6 cohort). H14 ✓.

### grandine

`vendor/grandine/transition_functions/src/fulu/block_processing.rs:200 process_execution_payload<P>(config, state: &mut FuluBeaconState<P>, ...)`. Plus `:168 process_execution_payload_for_gossip<P>` (gossip-time optimisation; narrower than lighthouse's — only timestamp + blob limit, not parent_hash + prev_randao).

**Gloas replacement implementations:**
- `vendor/grandine/transition_functions/src/gloas/block_processing.rs:157, 662 process_execution_payload_bid` — wired in main Gloas block-processing flow.
- `vendor/grandine/transition_functions/src/gloas/execution_payload_processing.rs:36 verify_execution_payload_envelope_signature` + `:183` (call site).
- `apply_parent_execution_payload` in the same Gloas module.

Full Gloas ePBS surface in dedicated `transition_functions/src/gloas/` module (multi-fork-definition Pattern I — same forward-fragility class as nimbus).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓. **H13 ✓** (grandine in the 5-of-6 cohort; most complete Gloas surface across the six). H14 ✓.

## Cross-reference table

| Client | Fulu `process_execution_payload` | Gloas `process_execution_payload_bid` | Gloas `apply_parent_execution_payload` | Gloas `verify_execution_payload_envelope` | H13 verdict |
|---|---|---|---|---|---|
| prysm | `core/blocks/payload.go` + `verifyBlobCommitmentCount(slot, body)` | `core/gloas/bid.go` ✓ | `core/gloas/parent_payload.go` ✓ | `core/gloas/payload.go` ✓ | ✓ in cohort with full Gloas wiring |
| lighthouse | `per_block_processing.rs:380, 421` (gossip-time + full split) | **MISSING** ✗ | **MISSING** ✗ | **MISSING** ✗ | **✗ cohort root (item #28 Pattern M)** |
| teku | `BlockProcessorFulu.java:73 getMaxBlobsPerBlock(state)` override | `versions/gloas/operations/ProcessExecutionPayloadBidValidator.java` ✓ | `versions/gloas/execution/ExecutionRequestsProcessorGloas.java` ✓ | `versions/gloas/execution/ExecutionPayloadVerifierGloas.java` ✓ | ✓ in cohort; further refutes "teku is the laggard" |
| nimbus | `state_transition_block.nim:1113` Fulu overload (6 total) | `:1276 process_execution_payload_bid*` ✓ | (Gloas-surface flow) ✓ | `:1165-1175 verify_execution_payload_envelope_signature` ✓ | ✓ in cohort; multi-fork-definition Pattern I |
| lodestar | `block/processExecutionPayload.ts:13` ForkSeq dispatch | `block/processExecutionPayloadBid.ts` ✓ | `block/processParentExecutionPayload.ts` ✓ | (Gloas-surface) ✓ | ✓ in cohort |
| grandine | `transition_functions/src/fulu/block_processing.rs:200` + `:168` for_gossip | `transition_functions/src/gloas/block_processing.rs:662` ✓ | (Gloas module) ✓ | `transition_functions/src/gloas/execution_payload_processing.rs:36` ✓ | ✓ in cohort; multi-fork-definition Pattern I |

## Empirical tests

### Fulu-surface live mainnet validation

Live behaviour reaffirms the prior audit's finding. Every Fulu block since 2025-12-03 has been processed by all 6 clients across **two BPO transitions**:

| Window | Active limit | Validated |
|---|---|---|
| 411392 (Fulu activation) → 412671 | 9 (Electra carry) | All 6 clients ✓ |
| 412672 (BPO #1) → 419071 | 15 | All 6 clients ✓ |
| 419072 (BPO #2) → present | 21 | All 6 clients ✓ |

Zero divergences in production — confirms the per-client item #31 + #32 integration.

### Gloas-surface

`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `vendor/consensus-specs/configs/mainnet.yaml:60`. The Gloas removal of `process_execution_payload` is source-level only. Lighthouse cohort gap (item #28 Pattern M) means lighthouse cannot process Gloas blocks when activated — pending pre-activation implementation.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1**: wire Fulu fixture categories in BeaconBreaker harness (same gap as items #11, #21, #27, #30, #31). Pre-condition for cross-client fixture testing.
- **T1.2**: dedicated EF fixture set for the three Gloas-NEW replacement functions (`process_execution_payload_bid`, `verify_execution_payload_envelope`, `apply_parent_execution_payload`). Cross-cuts item #19 H10 / item #28 Pattern M cohort.

#### T2 — Adversarial probes
- **T2.1 (Glamsterdam-target — H13 cohort fixture)**: Gloas state with valid SignedExecutionPayloadBid. Expected: 5 of 6 clients (prysm, teku, nimbus, lodestar, grandine) accept and process; lighthouse rejects with "Gloas not yet implemented" or analogous error.
- **T2.2 (Glamsterdam-target — H11 H12 spec evidence)**: confirm `vendor/consensus-specs/specs/gloas/beacon-chain.md:1402-1407` removes `process_execution_payload`. Verify the spec table-of-contents and section markers.
- **T2.3 (BPO transition stateful fixture at Fulu)**: at exactly epoch 412671 → 412672 (BPO #1), verify all 6 clients accept 10-15 blobs at 412672 but only ≤9 at 412671 (and 16-21 at 419072).
- **T2.4 (excessive-blob negative test)**: 22 blobs at epoch 419073 (= max + 1); verify all 6 reject with the same error message.
- **T2.5 (`notify_new_payload` failure mode cross-client audit)**: EL rejects the payload. Verify all 6 abort state transition with consistent error semantics (not silent skip).
- **T2.6 (lighthouse Gloas-ePBS readiness signal)**: monitor `vendor/lighthouse/consensus/state_processing/src/` for the introduction of any `process_execution_payload_bid` / `apply_parent_execution_payload` / `verify_execution_payload_envelope` function. Pre-activation status check.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Fulu-surface invariants (H1–H10) carry forward unchanged from the 2026-05-04 audit. EIP-7892 BPO integration into the Fulu-modified `process_execution_payload` is byte-for-byte equivalent across all 6 clients on the live mainnet target (validated by 2 successful BPO transitions).

**Glamsterdam-target finding (H11 — function REMOVED at Gloas).** `vendor/consensus-specs/specs/gloas/beacon-chain.md:92, 1402-1407` REMOVES `process_execution_payload` under EIP-7732 ePBS:

```
##### Removed `process_execution_payload`

`process_execution_payload` has been replaced by `verify_execution_payload_envelope`, a pure
verification helper called from `on_execution_payload_envelope`. Payload processing is deferred
to the next beacon block via `process_parent_execution_payload`.
```

The Fulu-Modified body that this item audits CEASES TO EXIST as a standalone state-transition function at Gloas. The replacement is a three-way decomposition:
1. **`process_execution_payload_bid`** (`:1424-1474`) — block-processing time. Validates SignedExecutionPayloadBid (builder active + bid signature + blob limit per item #31 BPO + parent_hash + prev_randao + slot). The blob-limit check moves here from Fulu's `process_execution_payload`. **This is the primary surface that continues item #31's `get_blob_parameters` consumption at Gloas.**
2. **`verify_execution_payload_envelope`** — envelope-processing time. Validates the actual ExecutionPayloadEnvelope when it arrives later (deferred payload processing).
3. **`apply_parent_execution_payload`** (`:1108, 1116`) — block-processing time. Processes parent payload's execution requests (deposits, withdrawals, consolidations) at the CURRENT block. Implements the EIP-7732 deferred-payload semantics.

**Glamsterdam-target finding (H13 — lighthouse Gloas-ePBS cohort gap reaffirmation).** Five of six clients have wired all three Gloas-NEW replacement functions:
- **prysm**: `core/gloas/bid.go` + `parent_payload.go` + `payload.go` (full Gloas ePBS surface).
- **teku**: `versions/gloas/operations/ProcessExecutionPayloadBidValidator` + `execution/ExecutionRequestsProcessorGloas` + `execution/ExecutionPayloadVerifierGloas`. **Reaffirms that "teku is the laggard" framing from older audits is OUTDATED** (items #28 + #29 + #30 + #31 + #32 all confirm teku's substantial Gloas surface).
- **nimbus**: `state_transition_block.nim:1276 process_execution_payload_bid*` + `:1165-1175 verify_execution_payload_envelope_signature` + 6-overload `process_execution_payload` (Gloas overload at `:1154`).
- **lodestar**: `block/processExecutionPayloadBid.ts` + `processParentExecutionPayload.ts`.
- **grandine**: `transition_functions/src/gloas/block_processing.rs:662 process_execution_payload_bid` + `execution_payload_processing.rs:36 verify_execution_payload_envelope_signature` + full Gloas module.

**Lighthouse is missing all three** — `grep -rn "process_execution_payload_bid|apply_parent_execution_payload|verify_execution_payload_envelope" vendor/lighthouse/consensus/state_processing/src/` returns NOTHING. Lighthouse has the basic Gloas upgrade scaffolding (`upgrade/gloas.rs`) and the `BeaconState::Gloas(_)` enum variant, but the EIP-7732 ePBS surface is unwired.

**Lighthouse cohort gap symptom count goes up to EIGHT** (per item #28 Pattern M):
1. Item #14 H9 — `is_builder_withdrawal_credential` predicate missing.
2. Item #19 H10 — `apply_parent_execution_payload` missing.
3. Item #22 H10 — `is_builder_withdrawal_credential` predicate missing (constant present).
4. Item #23 H8 — `get_pending_balance_to_withdraw_for_builder` missing.
5. Item #24 H11 — switch-to-compounding ePBS routing missing (consolidations via `apply_parent_execution_payload`).
6. Item #25 H11 — `is_valid_indexed_payload_attestation` missing.
7. Item #26 H8 — `get_attesting_indices` Gloas-surface (no direct symptom; confirmed by absence).
8. **NEW: this item — `process_execution_payload_bid` + `apply_parent_execution_payload` + `verify_execution_payload_envelope` all missing**. Three more symptoms from a single upstream gap.

Total lighthouse Pattern M symptoms: at least 8 (likely more once items #4/#7/#15/#16 are rechecked). Single-fix upstream (lighthouse implements the EIP-7732 ePBS surface) closes all eight.

**Glamsterdam-target finding (H14 — mainnet activation not yet scheduled).** `GLOAS_FORK_EPOCH = 18446744073709551615` (FAR_FUTURE_EPOCH) per `vendor/consensus-specs/configs/mainnet.yaml:60`. The Fulu-modified `process_execution_payload` continues operating in production; the Gloas removal/replacement is source-level only. Lighthouse cohort gap is not yet a mainnet-reachable divergence — pending Gloas activation.

**Fourteenth impact-none result for this item's audit target** (the Fulu-modified function on its native fork). The Gloas surface is item #19 H10 / item #28 Pattern M territory; this item's recheck flags the cross-cut but does not directly claim divergence at the Fulu surface.

**Notable per-client style differences (all observable-equivalent at Fulu):**
- **prysm**: extracts blob-limit check to `verifyBlobCommitmentCount` helper called from 4 sites; two-layer cached blob-limit lookup via `networkSchedule`.
- **lighthouse**: `partially_verify_execution_payload` gossip-time optimisation; full split between gossip + EL validation paths. **Pattern M cohort gap on Gloas surface.**
- **teku**: subclass-extension `BlockProcessorFulu extends BlockProcessorElectra` with single-method override (`getMaxBlobsPerBlock`); cleanest abstraction.
- **nimbus**: 6 separate `process_execution_payload` overloads (multi-fork-definition Pattern I); 6th overload handles Gloas signed envelope.
- **lodestar**: single function with ForkSeq dispatch; no multi-fork-definition.
- **grandine**: dedicated `transition_functions/src/fulu/` and `gloas/` modules (multi-fork-definition Pattern I); `process_execution_payload_for_gossip` narrower than lighthouse's gossip split.

**No code-change recommendation at the Fulu surface.** Audit-direction recommendations:

- **Wire Fulu fixture categories in BeaconBreaker harness** (T1.1) — pre-condition for cross-client fixture testing.
- **Dedicated EF fixture set for the three Gloas-NEW replacement functions** (T1.2) — cross-cuts item #19 H10 / item #28 Pattern M cohort.
- **Lighthouse Gloas-ePBS surface implementation** — single upstream fix closes 8+ Pattern M cohort symptoms. Highest-priority pre-Gloas implementation work.
- **Update item #28 Pattern M cohort symptom count** — this item adds 3 new symptoms (8 total or more).
- **Update WORKLOG re-scope status table**: item #19 is Pectra-historical; item #32 is the Fulu equivalent; the Gloas replacement (3 new functions) is a separate item or cohort.
- **BPO transition stateful fixture at Fulu** (T2.3) — verify all 6 enforce the boundary correctly across the 412672 and 419072 transitions.

## Cross-cuts

### With item #19 (`process_execution_payload` Pectra-modified) — Pectra-historical predecessor

Item #19 is the Pectra audit of this function. At Fulu, the only change is the dynamic blob limit (single-line spec change). At Gloas, the function is REMOVED. Item #19's audit is Pectra-historical; this item (#32) is the Fulu equivalent; the Gloas-NEW replacements are a separate cohort.

### With item #31 (`get_blob_parameters` BPO) — the producer of the dynamic blob limit

Item #31 audited `get_blob_parameters` consumed here. The Fulu integration (`process_execution_payload` reads blob limit from BPO) is the consumer side. At Gloas, the same primitive moves to `process_execution_payload_bid` (per `vendor/consensus-specs/specs/gloas/beacon-chain.md:1448`).

### With item #15 (Engine API V4/V5) — Engine boundary

Item #15 audited the V4/V5 boundary at Fulu. This item's `notify_new_payload` call routes through V5 at Fulu+. Engine API V5 standalone audit queued.

### With item #28 (Gloas divergence meta-audit) — Pattern M cohort

This item adds **three new symptoms** to lighthouse's Pattern M cohort (process_execution_payload_bid, apply_parent_execution_payload, verify_execution_payload_envelope all missing). Single upstream fix (lighthouse EIP-7732 ePBS implementation) closes all cohort symptoms. **Highest-priority pre-Gloas implementation work for lighthouse.**

### With item #19 H10 (Gloas ePBS deferred-payload semantics) — direct continuation

Item #19 H10 documented the ePBS routing change at Gloas (`process_consolidation_request` etc. moving from `process_operations` to `apply_parent_execution_payload`). This item's `apply_parent_execution_payload` is the exact same function. Single cross-cut.

## Adjacent untouched

1. **Lighthouse EIP-7732 ePBS surface implementation** — `is_builder_withdrawal_credential`, `apply_parent_execution_payload`, `process_execution_payload_bid`, `verify_execution_payload_envelope`, `is_valid_indexed_payload_attestation`, `get_pending_balance_to_withdraw_for_builder`. Single-fix-closes-8+-cohort-symptoms.
2. **Wire Fulu fixture categories in BeaconBreaker harness** — pre-condition for fixture testing.
3. **Dedicated EF fixture set for the three Gloas-NEW replacement functions** — cross-client byte-level equivalence.
4. **BPO transition stateful fixture at Fulu** — at exactly epochs 412672 and 419072.
5. **Excessive-blob negative test** — 22 blobs at 419073 = max + 1.
6. **Engine API V5 standalone audit** — closes item #15 follow-up.
7. **ExecutionPayloadHeader caching consistency cross-client audit**.
8. **`compute_timestamp_at_slot` cross-client byte-for-byte equivalence**.
9. **Pre-Deneb blob limit gating consistency** — prysm/lighthouse/teku/lodestar skip pre-Deneb; verify nimbus + grandine match.
10. **`notify_new_payload` failure mode cross-client audit** — verify all 6 abort state transition consistently.
11. **BPO + Engine API V5 interaction audit** — verify V5 routing is independent of BPO transitions.
12. **Cross-fork transition stateful fixture Pectra→Fulu→Gloas** — verify the function path migration.
13. **Cross-network blob limit consistency** — verify mainnet/sepolia/holesky `process_execution_payload` matches each network's BLOB_SCHEDULE.
14. **teku Heze readiness check** — `BlockProcessorHeze extends BlockProcessorFulu` skeleton; track teku's continued post-Gloas leadership.
15. **nimbus 6-overload regression audit** — verify each fork's overload has no logic divergence beyond spec-mandated changes (multi-fork-definition Pattern I forward-fragility).
16. **grandine `for_gossip` vs lighthouse `partially_verify_execution_payload` semantic-equivalence test** — both split gossip-time validation; verify identical decisions on the same input.
17. **WORKLOG re-scope status table update**: mark item #19 as Pectra-historical; item #32 as Fulu equivalent; the three Gloas-NEW functions as cohort-tracked under item #28 Pattern M.
