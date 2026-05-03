# Item #19 — `process_execution_payload` Pectra-modified (EIP-7691 blob limit + EIP-7685 requests pass-through)

**Status:** no-divergence-pending-fuzzing — audited 2026-05-02. The
**most-touched per-block validation function**: every block's
execution payload flows through here. Pectra-modified for EIP-7691
(`MAX_BLOBS_PER_BLOCK_ELECTRA = 9`, was 6 at Deneb) and EIP-7685
(passes `execution_requests` to the EL via NewPayloadV4).

## Why this item

`process_execution_payload` is the consensus-layer's verification
of the execution payload received from the EL. It runs **once per
block** and gates several invariants:

1. **Parent-hash chain consistency**: `payload.parent_hash ==
   state.latest_execution_payload_header.block_hash` (continuity of
   the EL block chain across CL block processing).
2. **PrevRandao**: `payload.prev_randao == get_randao_mix(state,
   current_epoch)` — beacon-chain-mixed entropy seeded into the EL.
3. **Timestamp**: `payload.timestamp == compute_time_at_slot(state,
   state.slot)` — block timing.
4. **Blob count**: `len(body.blob_kzg_commitments) <=
   MAX_BLOBS_PER_BLOCK_ELECTRA` (Pectra's increased blob throughput).
5. **EL acceptance**: `verify_and_notify_new_payload(NewPayloadRequest)`
   — the EL accepts the payload as valid, including the
   `execution_requests` (EIP-7685, item #15).
6. **Cache update**: `state.latest_execution_payload_header =
   ExecutionPayloadHeader.from(payload)` — copies 16 fields from
   payload into the cached header.

Pectra changes:
- **EIP-7691** (`MAX_BLOBS_PER_BLOCK_ELECTRA = 9`, was 6): consensus-
  critical limit increase. Off-by-one or wrong constant would let
  invalid blocks pass.
- **EIP-7685** (pass `execution_requests` to EL via NewPayloadV4):
  cross-cuts item #15. Detailed there.
- **`ExecutionPayloadHeader` struct UNCHANGED** at Pectra (still 16
  fields). The EIP-7685 requests are stored separately in
  `body.execution_requests`, not in the payload header. Pectra does
  NOT add fields to the header.

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | Parent hash check: `payload.parent_hash == state.latest_execution_payload_header.block_hash` (only when post-merge) | ✅ all 6 |
| H2 | PrevRandao check: `payload.prev_randao == get_randao_mix(state, current_epoch)` | ✅ all 6 |
| H3 | Timestamp check: `payload.timestamp == compute_time_at_slot(state, state.slot)` | ✅ all 6 |
| H4 | EIP-7691 blob limit: `len(body.blob_kzg_commitments) <= MAX_BLOBS_PER_BLOCK_ELECTRA = 9` (mainnet, Electra) | ✅ all 6 |
| H5 | Blob limit dispatched per-fork: Deneb 6 / Electra 9 / Fulu+ may differ via `get_blob_parameters(epoch)` | ✅ all 6 (with 5 dispatch styles — see below) |
| H6 | NewPayloadRequest passes `execution_requests=body.execution_requests` (cross-cut item #15) | ✅ all 6 |
| H7 | NewPayloadV4 method (Electra) vs V3 (Deneb) vs V5 (Gloas) routing | ✅ all 6 |
| H8 | `ExecutionPayloadHeader` cache update copies 16 fields (Pectra UNCHANGED structure) | ✅ all 6 |
| H9 | versioned_hashes derivation: `kzg_commitment_to_versioned_hash(c)` per blob commitment | ✅ all 6 |

## Per-client cross-reference

| Client | Function location | Blob limit dispatch |
|---|---|---|
| **prysm** | `core/blocks/payload.go:211-229` (`ProcessPayload`); blob check `:231-247` (`verifyBlobCommitmentCount`) | `params.BeaconConfig().MaxBlobsPerBlock(slot)` — slot-keyed dynamic lookup via networkSchedule |
| **lighthouse** | `state_processing/src/per_block_processing.rs:421-462` (`process_execution_payload`); blob check `:398-409` | `spec.max_blobs_per_block(epoch)` — epoch-keyed dispatch in chain_spec.rs:723-734 |
| **teku** | `versions/electra/block/BlockProcessorElectra.java:115-136` (`computeNewPayloadRequest` override); blob check in `BlockProcessorDeneb.java:81-93` (parent class) | `getMaxBlobsPerBlock(state)` — subclass override returning `specConfigElectra.getMaxBlobsPerBlockElectra() = 9` |
| **nimbus** | `state_transition_block.nim:1068-1104` (Electra); `:1113-1151` (Fulu); `:1154-1242` (Gloas) | Electra hardcodes `cfg.MAX_BLOBS_PER_BLOCK_ELECTRA`; Fulu uses `cfg.get_blob_parameters(epoch).MAX_BLOBS_PER_BLOCK` (epoch-relative) |
| **lodestar** | `block/processExecutionPayload.ts:13-83` | `state.config.getMaxBlobsPerBlock(computeEpochAtSlot(state.slot))` — fork-keyed via config method |
| **grandine** | `transition_functions/src/electra/block_processing.rs:432-485` (`process_execution_payload`); blob check `:234-241` (in gossip variant) | `config.max_blobs_per_block_electra` — runtime config (not type-associated) |

## Notable per-client divergences (all observable-equivalent)

### Five distinct blob-limit dispatch idioms

The blob limit must scale per fork (Deneb 6 → Electra 9 → potentially
different at Fulu via `get_blob_parameters(epoch)`). Each client uses a
distinct dispatch style:

- **prysm**: `MaxBlobsPerBlock(slot)` — slot-keyed lookup via a
  `networkSchedule` table that maps slots to fork-active limits.
- **lighthouse**: `spec.max_blobs_per_block(epoch)` — epoch-keyed
  match in `chain_spec.rs`.
- **teku**: subclass-override (`BlockProcessorElectra` inherits from
  `BlockProcessorDeneb` which inherits `getMaxBlobsPerBlock` —
  Electra returns `getMaxBlobsPerBlockElectra() = 9`).
- **nimbus**: Electra hardcodes `cfg.MAX_BLOBS_PER_BLOCK_ELECTRA`
  inline; Fulu switches to `cfg.get_blob_parameters(epoch)` for
  EIP-7732 dynamic blob params.
- **lodestar**: `state.config.getMaxBlobsPerBlock(epoch)` — config
  method dispatches.
- **grandine**: `config.max_blobs_per_block_electra` — runtime config
  field (NOT type-associated like `P::MaxBlobsPerBlockElectra` would be).

**All converge on 9 mainnet** for Electra. Forward-compat at Fulu
(EIP-7732 introduces dynamic blob parameters per epoch) is handled
asymmetrically — nimbus already has the Fulu code path; other
clients have it via slot/epoch-keyed dispatchers; teku has it via
`get_blob_parameters` future override.

### lighthouse: validation extracted to `partially_verify_execution_payload`

Lighthouse splits the function: `process_execution_payload` (lines
421-462) calls `partially_verify_execution_payload` (lines 365-412)
for the validation predicates (parent hash, randao, timestamp, blob
limit). The "partial" naming reflects that the full validation
includes the EL boundary call (`notify_new_payload`) which is
deferred. Useful for gossip-time validation (skip the EL call,
re-do later when block is fully received).

### nimbus: separate functions for Electra / Fulu / Gloas

```nim
# Electra: lines 1068-1104
# Fulu:    lines 1113-1151 (uses get_blob_parameters)
# Gloas:   lines 1154-1242 (different signature, takes envelope)
```

**Three completely separate functions** instead of one with `when`
guards. Each is type-specialized for the fork's BeaconState +
ExecutionPayload variant. Cleanest fork-isolation but most code
duplication. The Gloas signature is fundamentally different (takes
`SignedExecutionPayloadEnvelope` instead of `BeaconBlockBody` —
EIP-7732 PBS restructure).

### grandine: 6 fork-module definitions + blinded variants

```
transition_functions/src/{bellatrix,capella,deneb,electra,fulu}/block_processing.rs    # 5 forks × 1
transition_functions/src/{bellatrix,capella,deneb,electra,fulu}/blinded_block_processing.rs  # 5 forks × 1
transition_functions/src/gloas/execution_payload_processing.rs                          # Gloas, dedicated module
```

**11 definitions** for `process_execution_payload` across grandine
(5 forks × 2 + 1 Gloas-special). Same multi-fork-definition pattern
as items #6/#9/#10/#12/#14/#15/#17 (but NOT items #16/#18). Fork
isolation is type-driven (each fork has its own
`ElectraBeaconState`, `DenebBeaconState`, etc.) — F-tier risk
because incorrect imports would fail to compile.

### teku: validation extracted to `validateExecutionPayload` parent class

teku's `BlockProcessorBellatrix.processExecutionPayload` (lines
123-135) calls `validateExecutionPayload` which is overridden by
`BlockProcessorDeneb` (lines 81-93) to add the blob limit check.
Electra inherits Deneb's validation (no override). The validation
chain is purely additive: Bellatrix base → Deneb adds blob check →
Electra inherits.

The cache update (`state.setLatestExecutionPayloadHeader(...)`) is
done at the Bellatrix base. **Electra adds NO new fields to the
header** (correct per spec — EIP-7685 requests are separate from
the header).

### lodestar: post-payload-processing for execution_requests

Lodestar's `processExecutionPayload` does NOT directly call the
engine API or pass `executionRequests`. Instead, the payload is
processed first (validation + cache update), and `executionRequests`
are processed AFTER in `processOperations` (lines 73-88, item #13's
audit). This is a unique architectural choice: payload processing
and request dispatch are decoupled. Other clients combine them in
`process_execution_payload` directly.

**Functionally equivalent** because `processOperations` runs after
`processExecutionPayload` in the standard CL block-processing flow.

### prysm: defensive nil-check on requests for Electra

```go
if blk.Version() >= version.Electra {
    requests, err = blk.Block().Body().ExecutionRequests()
    if err != nil { ... }
    if requests == nil {
        return false, errors.New("nil execution requests")  // HARD requirement at Electra
    }
}
```

Prysm explicitly REJECTS nil `executionRequests` at Electra+. Other
clients' SSZ deserialization layer would catch nil requests at the
container-construction level (the field is REQUIRED in the
ExecutionRequests SSZ schema). prysm's extra check is defensive
against proto-level nil pointers — F-tier today since SSZ enforces.

### prysm: graceful Deneb→Electra fallback in engine API

```go
case *pb.ExecutionPayloadDeneb:
    if executionRequests == nil {
        // Deneb: use V3 (no requests)
        s.rpcClient.CallContext(ctx, result, NewPayloadMethodV3, ...)
    } else {
        // Electra: use V4 (with requests)
        s.rpcClient.CallContext(ctx, result, NewPayloadMethodV4, ...)
    }
```

prysm uses the SAME `ExecutionPayloadDeneb` proto type for BOTH
Deneb and Electra blocks (Pectra didn't add new payload fields).
The fork distinction is determined by whether `executionRequests`
is nil (Deneb) or non-nil (Electra). Other clients have separate
typed payload variants per fork. **prysm's pattern is more
forward-compatible** but relies on the optional-field convention.

## EF fixture results — 160/160 PASS

```
clients: prysm, lighthouse, lodestar, grandine
fixtures: 40
PASS: 160   FAIL: 0   SKIP: 0   total: 160
```

The first run had 21 lighthouse FAILs due to a runner test-name
mapping issue: lighthouse exposes `operations_execution_payload_full`
(NOT bare `operations_execution_payload`) for this category. **Patched
`tools/runners/lighthouse.sh`** to map `BB_HELPER=execution_payload`
→ `test_fn=operations_execution_payload_full`. Post-patch run shows
0 failures across all 160 invocations.

(See `tools/runners/lighthouse.sh` diff in the parent commit for
the runner patch.)

The 40-fixture suite covers:

| Category | Count | Tests |
|---|---|---|
| Blob/transaction format | 9 | `incorrect_blob_tx_type`, `incorrect_block_hash`, `incorrect_commitment`, `incorrect_commitments_order`, 4× `incorrect_transaction_length_*`, `incorrect_transaction_no_blobs_but_with_commitments` |
| Bad payload (general) | 8 | 2× `invalid_bad_everything_{first,regular}`, 2× `invalid_bad_execution_*`, 2× `invalid_bad_parent_hash_*`, 2× `invalid_bad_pre_randao_*`/`invalid_bad_prev_randao_*` |
| Timestamp | 4 | 2× `invalid_future_timestamp_*`, 2× `invalid_past_timestamp_*` |
| Blob limit (H4) | 1 | **`invalid_exceed_max_blobs_per_block`** — directly tests EIP-7691 |
| Successful + edge | 18 | `success_first_payload`, `success_first_payload_with_gap_slot`, 4× `success_*_*_payload`, 8× successful variants, 4× `non_empty_*` for bytes/extra_data |

teku and nimbus SKIP per harness limitation (no per-operation CLI
hook in BeaconBreaker's runners). Both have full implementations
per source review.

## Cross-cut chain — closes the per-block payload-validation layer

Combined with item #15 (CL-EL boundary encoding), item #19 (this)
forms the complete per-block EL-interaction layer:

```
[item #19 (this)] process_execution_payload validates payload locally:
                  - parent hash, randao, timestamp
                  - blob count <= MAX_BLOBS_PER_BLOCK_ELECTRA = 9
                  - cache header (16-field copy)
                              ↓
[item #15] get_execution_requests_list encodes for EL:
           - filter empty lists
           - type_byte || ssz_serialize(list) per non-empty
                              ↓
                  engine_newPayloadV4(payload, vh, pbr, requests_list)
                              ↓
                  EL validates payload + computes requestsHash
                              ↓
[item #13] process_operations dispatcher (called LATER in block processing)
                  routes execution_requests.{deposits,withdrawals,consolidations}
                  to per-operation processors (items #2/#3/#14)
```

This audit closes the per-block payload-validation layer. Items #1–#19
now cover:
- **Block-level state transitions**: items #2/#3/#5/#6/#7/#8/#9/#12/#14
- **Per-epoch processing**: items #1/#4/#10/#17
- **State upgrade**: item #11
- **Block-level dispatchers + payload**: items #13/#15/**#19 (this)**
- **Per-block primitives**: items #16/#18

## Adjacent untouched

- **Wire fork category in BeaconBreaker harness** — turns item #11
  into first-class fixture-verified.
- **Cross-fork blob-limit transition stateful fixture**: block at
  Deneb-Electra boundary with 7 blobs (rejected at Deneb, accepted
  at Electra).
- **lighthouse's `partially_verify_execution_payload` reuse** —
  documents the partial-validation-then-EL-call separation as a
  valid gossip-time optimization.
- **nimbus's three separate Electra/Fulu/Gloas functions** —
  forward-compat: when Fulu activates, ensure the Electra function
  isn't accidentally called for Fulu blocks.
- **grandine's 11 fork-module definitions** — codify a pre-commit
  check that each fork's `process_execution_payload` correctly
  matches the spec's per-fork modifications.
- **teku's `BlockProcessorBellatrix.processExecutionPayload` base**
  — Bellatrix-Capella-Deneb-Electra all share the same processor
  body; only `validateExecutionPayload` differs per fork. Worth
  documenting.
- **lodestar's payload-then-requests separation** — verify cross-
  client that the observable post-state is identical when
  `processOperations` runs after `processExecutionPayload`.
- **prysm's nil-check on Electra requests** — equivalence test
  against SSZ-level enforcement in other clients.
- **prysm's Deneb-payload-shared-with-Electra pattern** — verify
  that the `nil executionRequests` distinction doesn't cause
  surprises at fork boundaries.
- **`compute_timestamp_at_slot` standalone audit** — used by every
  client's payload validation. Trivial formula but pivotal.
- **`kzg_commitment_to_versioned_hash` cross-client equivalence** —
  `sha256(commitment) with first byte = 0x01`. Verify byte-for-byte
  across all 6 clients.
- **EIP-7691 mainnet activation timing** — at the Electra fork
  epoch, the blob limit jumps from 6 to 9. Verify cross-client
  that the transition happens at the EXACT slot boundary, not
  at the epoch boundary or some other point.
- **`MAX_BLOB_COMMITMENTS_PER_BLOCK = 4096` upper bound** —
  unchanged at Pectra, but worth noting that
  MAX_BLOBS_PER_BLOCK_ELECTRA = 9 is well under this hard cap.
- **Engine API method routing**: V3 (Deneb), V4 (Electra), V5
  (Gloas). prysm's pattern of using the same payload type with
  optional executionRequests is one approach; lighthouse uses
  per-method type variants. Codify.

## Future research items

1. **Wire fork category in BeaconBreaker harness** (highest priority
   for closing item #11 fixture gap).
2. **Cross-fork blob-limit transition fixture** (Deneb→Electra
   boundary stateful test).
3. **`compute_timestamp_at_slot` standalone audit** — pivotal
   per-block helper.
4. **`kzg_commitment_to_versioned_hash` cross-client byte-for-byte
   equivalence test**.
5. **EIP-7691 mainnet activation timing verification** — exact slot
   transition.
6. **Engine API method routing cross-client cross-test** (V3 →
   V4 → V5 transitions).
7. **lighthouse `partially_verify_execution_payload` gossip-time
   optimization documentation**.
8. **nimbus's three-function-per-fork forward-compat audit at Fulu
   activation**.
9. **grandine's 11-definition pre-commit check codification**.
10. **teku Bellatrix-base sharing documentation**.
11. **lodestar payload-then-requests separation contract test**.
12. **prysm nil-check + Deneb-payload-shared-with-Electra pattern
    equivalence tests**.
13. **`MAX_BLOB_COMMITMENTS_PER_BLOCK = 4096` hard cap interaction**
    with Pectra's increased per-block limit.
14. **Block-without-blobs at Pectra** edge case — verify
    `MAX_BLOBS_PER_BLOCK_ELECTRA` allows zero blobs.
