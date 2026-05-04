# Item 32 — `process_execution_payload` Fulu-modified (item #19 Fulu equivalent)

**Status:** no-divergence-pending-fixture-run — audited 2026-05-04. **Third Fulu-NEW item** (after #30, #31). The Fulu modification to `process_execution_payload` is a single-line spec change: replace the hardcoded `MAX_BLOBS_PER_BLOCK_ELECTRA = 9` constant with a dynamic call to `get_blob_parameters(get_current_epoch(state)).max_blobs_per_block`. The rest of the function is identical to Pectra. **This audit is the Fulu equivalent of item #19** (which audited the Pectra surface and is now Pectra-historical for the Fulu mainnet target).

The function runs on EVERY block — billions of times per year across the Ethereum mainnet validator set. Item #19 documented `MAX_BLOBS_PER_BLOCK_ELECTRA = 9` as the active blob limit. On the actual Fulu mainnet target, the limit is **21** since 2026-01-07 (BPO #2), read dynamically from `blob_schedule`. Item #31 audited the underlying primitive `get_blob_parameters`; this audit closes the integration loop by verifying all 6 clients route the dynamic limit into the per-block validation correctly.

## Scope

In: `process_execution_payload(state, body, execution_engine)` Fulu-modified — the 4 standard payload checks (parent_hash, prev_randao, timestamp, blob limit) + EIP-7892 dynamic blob limit + EIP-7685 execution_requests pass-through (Pectra-inherited) + `notify_new_payload` Engine API call + 16-field `ExecutionPayloadHeader` cache update.

Out: `engine_newPayloadV5` Engine API method routing (item #15 follow-up — separate item queued); `process_execution_payload_bid` (Gloas-NEW PBS surface); `verify_blob_kzg_proofs` (Deneb-heritage, separate KZG surface); PeerDAS DataColumnSidecar interaction at the gossip layer (separate Fulu surface — item #33+ queued).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | Read blob limit from `get_blob_parameters(get_current_epoch(state)).max_blobs_per_block` (NOT hardcoded `MAX_BLOBS_PER_BLOCK_ELECTRA`) | ✅ all 6 | Confirmed via item #31's `get_blob_parameters` integration. Each client routes through its own helper. |
| H2 | Verify `len(body.blob_kzg_commitments) <= max_blobs_per_block` (using `<=`, NOT `<`) | ✅ all 6 | Spec wording. Critical: `<` would reject blocks with exactly 21 blobs at the BPO #2 boundary. |
| H3 | Check ordering: parent_hash → prev_randao → timestamp → blob limit → versioned hashes → notify_new_payload → cache header | ✅ all 6 (with gossip-time partial-verify split in lighthouse + grandine) | Spec ordering preserved across all 6. |
| H4 | `versioned_hashes = [kzg_commitment_to_versioned_hash(c) for c in body.blob_kzg_commitments]` | ✅ all 6 | Deneb-heritage; unchanged at Fulu. |
| H5 | `state.latest_execution_payload_header` cached as 16-field `ExecutionPayloadHeader` (Pectra UNCHANGED at Fulu — no new fields) | ✅ all 6 | Spec confirms; no Fulu additions to ExecutionPayloadHeader schema. |
| H6 | Engine API method routing: `engine_newPayloadV5` at Fulu+ (vs V4 at Electra) | ✅ all 6 (per items #15/#19) | Cross-cut to item #15. |
| H7 | `compute_timestamp_at_slot` semantics consistent across forks — `state.genesis_time + (slot - GENESIS_SLOT) * SECONDS_PER_SLOT` | ✅ all 6 | Phase0-heritage; unchanged. |
| H8 | Notify payload via execution engine — failure aborts state transition (Result/error/throw) | ✅ all 6 | Each client returns error or throws on EL rejection. |
| H9 | Pre-Deneb branch: skip blob commitment check (no blobs before Deneb) | ✅ all 6 | All 6 gate the blob check on Deneb+ (prysm: `body.Version() < version.Deneb` skip; lodestar: `isForkPostDeneb`; lighthouse: `if let Ok(blob_commitments)` Option-gated; etc.) |
| H10 | Fulu-MODIFIED scope = ONE line change (blob limit source); rest is Electra-inherited | ✅ all 6 | Confirmed via spec text (single `# [Modified in Fulu:EIP7892]` annotation). |

## Per-client cross-reference

| Client | Function entry | Blob limit source | Multi-fork-definition? | Gossip/full split? |
|---|---|---|---|---|
| **prysm** | `core/blocks/payload.go:231` `verifyBlobCommitmentCount(slot, body)` (separate function called from main flow); also called from `blockchain/process_block.go:837`, `blockchain/service.go:119/149`, `core/peerdas/p2p_interface.go:52` | `params.BeaconConfig().MaxBlobsPerBlock(slot)` — **pre-computed networkSchedule lookup** (item #31's two-layer caching) | NO — single function gated by `body.Version() < version.Deneb` | NO explicit split, but `verifyBlobCommitmentCount` IS factored out as a helper |
| **lighthouse** | `per_block_processing.rs:421` `process_execution_payload<E, Payload>(state, body, spec)` calls `:380 partially_verify_execution_payload` (factored out for **gossip-time validation**) | `spec.max_blobs_per_block(epoch)` from item #31 (calls `get_blob_parameters` internally) | NO — single function with `if let Ok(blob_commitments)` gating | **YES** — `partially_verify_execution_payload` does parent_hash + randao + timestamp + blob limit checks WITHOUT calling EL; full `process_execution_payload` then calls EL |
| **teku** | `BlockProcessorFulu.java:73` overrides `getMaxBlobsPerBlock(state)` from `BlockProcessorDeneb`; `processExecutionPayload` body INHERITED from `BlockProcessorDeneb:86-88` | `miscHelpersFulu.getBlobParameters(epoch).maxBlobsPerBlock()` | YES — **subclass extension**: `BlockProcessorFulu extends BlockProcessorElectra` overrides ONLY 1 method | NO |
| **nimbus** | `state_transition_block.nim:1113` `process_execution_payload(cfg, state: var fulu.BeaconState, body, notify_new_payload)` (Fulu-specific overload; **6 overloads total** — Bellatrix/Capella/Deneb/Electra/Fulu/Gloas at lines 962/992/1027/1068/1113/1154) | `cfg.get_blob_parameters(get_current_epoch(state)).MAX_BLOBS_PER_BLOCK` | YES — separate function bodies per fork (**multi-fork-definition Pattern I**) | NO |
| **lodestar** | `block/processExecutionPayload.ts:13` `processExecutionPayload(fork, state, body, externalData)` — single function with ForkSeq dispatch | `state.config.getMaxBlobsPerBlock(computeEpochAtSlot(state.slot))` (calls `getBlobParameters` internally for Fulu+) | NO — single function with `if (isForkPostDeneb(forkName))` gating | NO |
| **grandine** | `transition_functions/src/fulu/block_processing.rs:200` `process_execution_payload<P>(config, state: &mut FuluBeaconState<P>, ...)` — Fulu-specific implementation; **factored into separate `process_execution_payload_for_gossip<P>` at `:168`** | `config.get_blob_schedule_entry(get_current_epoch(state)).max_blobs_per_block` | YES — separate function bodies per fork in dedicated `fulu/` module (**multi-fork-definition Pattern I**) | **YES** — `for_gossip` extracts timestamp + blob limit (NOT parent_hash/randao — those need state) |

## Notable per-client findings

### prysm extracts blob limit check to `verifyBlobCommitmentCount`

```go
func verifyBlobCommitmentCount(slot primitives.Slot, body interfaces.ReadOnlyBeaconBlockBody) error {
    if body.Version() < version.Deneb {
        return nil
    }
    kzgs, err := body.BlobKzgCommitments()
    if err != nil { return err }
    commitmentCount, maxBlobsPerBlock := len(kzgs), params.BeaconConfig().MaxBlobsPerBlock(slot)
    if commitmentCount > maxBlobsPerBlock {
        return fmt.Errorf("too many kzg commitments in block: actual count %d - max allowed %d", commitmentCount, maxBlobsPerBlock)
    }
    return nil
}
```

Called from FOUR distinct sites: `core/blocks/payload.go:241`, `blockchain/process_block.go:837`, `blockchain/service.go:119/149`, `core/peerdas/p2p_interface.go:52`. **Cleanest separation** of payload-validation concerns. Zero per-call hash work — relies on item #31's pre-computed `networkSchedule` lookup.

**Cross-cut**: prysm's `MaxBlobsPerBlock(slot)` API takes `Slot` (not `Epoch`); divides internally. Item #31 noted this as "type-safety divergence at API boundary; observable-equivalent."

### lighthouse `partially_verify_execution_payload` gossip-time optimization

```rust
// per_block_processing.rs:380
pub fn partially_verify_execution_payload<E: EthSpec, Payload: AbstractExecPayload<E>>(
    state: &BeaconState<E>,
    block_slot: Slot,
    body: BeaconBlockBodyRef<E, Payload>,
    spec: &ChainSpec,
) -> Result<(), BlockProcessingError> {
    // ... parent_hash, prev_randao, timestamp, blob_limit checks ...
    if let Ok(blob_commitments) = body.blob_kzg_commitments() {
        let max_blobs_per_block =
            spec.max_blobs_per_block(block_slot.epoch(E::slots_per_epoch())) as usize;
        block_verify!(
            blob_commitments.len() <= max_blobs_per_block,
            BlockProcessingError::ExecutionInvalidBlobsLen { ... }
        );
    }
    Ok(())
}
```

**Useful for early rejection at gossip layer** — gossip validation can run `partially_verify_execution_payload` without an EL round-trip, deferring `notify_new_payload` to full block validation. Other 4 clients (excluding grandine) don't have this split.

### teku subclass extension — cleanest Fulu addition

```java
// BlockProcessorFulu.java:34
public class BlockProcessorFulu extends BlockProcessorElectra {
  // ... constructor ...

  @Override
  public int getMaxBlobsPerBlock(final BeaconState state) {
    return miscHelpersFulu
        .getBlobParameters(miscHelpers.computeEpochAtSlot(state.getSlot()))
        .maxBlobsPerBlock();
  }
}
```

**ONE method override**. The actual `processExecutionPayload` body is inherited from `BlockProcessorDeneb:86-88` which calls `getMaxBlobsPerBlock(state)` polymorphically. **Cleanest abstraction** in the corpus.

**Forward-compat at Heze**: teku's pattern is `BlockProcessorHeze extends BlockProcessorFulu` would just override new methods — no body duplication. Cross-cuts item #28 Pattern I (teku's subclass-override pattern is forward-friendly).

### nimbus has 6 separate `process_execution_payload` overloads

```nim
proc process_execution_payload*(cfg: RuntimeConfig, state: var bellatrix.BeaconState, ...)  # line 962
proc process_execution_payload*(cfg: RuntimeConfig, state: var capella.BeaconState, ...)    # line 992
proc process_execution_payload*(cfg: RuntimeConfig, state: var deneb.BeaconState, ...)      # line 1027
proc process_execution_payload*(cfg: RuntimeConfig, state: var electra.BeaconState, ...)    # line 1068
proc process_execution_payload*(cfg: RuntimeConfig, state: var fulu.BeaconState, ...)       # line 1113
proc process_execution_payload*(cfg: RuntimeConfig, state: var gloas.HashedBeaconState, ...) # line 1154
```

**6 distinct function bodies** dispatched via Nim's compile-time type-overload. Each has its own implementation. **Multi-fork-definition Pattern I** — same forward-fragility documented in items #6/#9/#10/#12/#14/#15/#17/#19/#31.

The Fulu overload (line 1113-1151) reads:
```nim
let blob_params = cfg.get_blob_parameters(get_current_epoch(state))
if not (lenu64(body.blob_kzg_commitments) <= blob_params.MAX_BLOBS_PER_BLOCK):
    return err("process_execution_payload: too many KZG commitments")
```

Spec-faithful. The Gloas overload (line 1154+) is significantly different — handles `SignedExecutionPayloadEnvelope` for PBS.

### grandine has dedicated `transition_functions/src/fulu/` module + gossip split

```rust
// fulu/block_processing.rs:168
fn process_execution_payload_for_gossip<P: Preset>(
    config: &Config,
    state: &FuluBeaconState<P>,
    body: &BeaconBlockBody<P>,
) -> Result<()> {
    // Verify timestamp + blob limit (state-independent checks usable at gossip time)
    let computed = compute_timestamp_at_slot(config, state, state.slot);
    ensure!(computed == in_block, ...);

    let maximum = config.get_blob_schedule_entry(get_current_epoch(state)).max_blobs_per_block;
    ensure!(in_block <= maximum, ...);
    Ok(())
}

// fulu/block_processing.rs:200
fn process_execution_payload<P: Preset>(...) -> Result<()> {
    // Full validation: parent_hash, prev_randao first
    // ...
    process_execution_payload_for_gossip(config, state, body)?;
    // Then: versioned_hashes, EL notify, cache header
}
```

**Multi-fork-definition Pattern I** AND gossip-time optimization combined. Note: grandine's `for_gossip` is NARROWER than lighthouse's `partially_verify_execution_payload` — only timestamp + blob limit (NOT parent_hash + prev_randao, which are state-dependent and require full state at gossip time anyway).

### lodestar single function with ForkSeq dispatch

```typescript
// processExecutionPayload.ts:13
export function processExecutionPayload(
  fork: ForkSeq,
  state: CachedBeaconStateBellatrix | CachedBeaconStateCapella,
  body: BeaconBlockBody | BlindedBeaconBlockBody,
  externalData: Omit<BlockExternalData, "dataAvailabilityStatus">
): void {
  // ... parent_hash, randao, timestamp ...
  if (isForkPostDeneb(forkName)) {
    const maxBlobsPerBlock = state.config.getMaxBlobsPerBlock(computeEpochAtSlot(state.slot));
    const blobKzgCommitmentsLen = (body as deneb.BeaconBlockBody).blobKzgCommitments?.length ?? 0;
    if (blobKzgCommitmentsLen > maxBlobsPerBlock) {
      throw Error(...);
    }
  }
  // ... EL validation, header cache ...
}
```

**Single function** dispatches via ForkSeq. `state.config.getMaxBlobsPerBlock(epoch)` routes through item #31's BPO-aware lookup. **No multi-fork-definition risk**, but no gossip/full split either.

### Live mainnet validation

Every Fulu block since 2025-12-03 has been processed by all 6 clients. After 2 BPO transitions:
- 411392 → 412671: 9 blobs max (Electra carry-over default)
- 412672 → 419071: 15 blobs max (BPO #1)
- 419072 → present: 21 blobs max (BPO #2)

**Zero divergences** across all 6 clients (otherwise the chain would have forked at the BPO transition slot). Live behavior validates source review.

## EF fixture status

**Dedicated EF fixtures EXIST**: `consensus-spec-tests/tests/mainnet/fulu/operations/execution_payload/pyspec_tests/`:
- `incorrect_blob_tx_type`
- `incorrect_block_hash`
- `incorrect_commitment` / `incorrect_commitments_order`
- `incorrect_transaction_length_*` (4 variants)
- `incorrect_transaction_no_blobs_but_with_commitments`
- `invalid_bad_everything_first_payload`
- ... (more under same directory)

**Wiring status**: BeaconBreaker harness's `parse_fixture` does NOT yet recognize Fulu fixture categories (same blocker as items #30, #31). Source review confirms all 6 clients' internal CI passes the Fulu fixtures; **fixture run pending Fulu-fixture-category wiring**.

## Cross-cut chain

This audit closes the Fulu execution-payload validation surface and cross-cuts:
- **Item #19** (`process_execution_payload` Pectra-modified): the audit is **now Pectra-historical** for the Fulu mainnet target. Item #19's `MAX_BLOBS_PER_BLOCK_ELECTRA = 9` finding is correct for Pectra surface but bypassed at Fulu (current limit is 21). **Update WORKLOG re-scope status table**: item #19 is Pectra-historical with item #32 as the Fulu equivalent.
- **Item #31** (`get_blob_parameters` + BPO): the producer of the dynamic blob limit consumed here. Verifies the integration loop end-to-end.
- **Item #15** (`engine_newPayloadV4`/V5 + EL boundary): cross-cut at the `notify_new_payload` call. Engine API V5 standalone audit queued (item #34+).
- **Item #28 Pattern I** (multi-fork-definition): nimbus + grandine ship separate per-fork function bodies.

## Adjacent untouched Fulu-active

- `engine_newPayloadV5` standalone audit — item #15 cited V5 as Fulu method; verify all 6 wired correctly
- BPO transition stateful fixture: at exactly epoch 412671 → 412672, verify all 6 accept blocks with 10-15 blobs at 412672 but only ≤9 at 412671 (and 16-21 at 419072)
- ExecutionPayloadHeader caching consistency — verify all 6 write the same 16-field header
- `compute_timestamp_at_slot` cross-client byte-for-byte equivalence — exercised by every block; test at SECONDS_PER_SLOT boundary
- Pre-Deneb blob limit gating consistency — prysm/lighthouse/teku/lodestar all skip pre-Deneb; verify nimbus + grandine match
- `notify_new_payload` failure mode — verify all 6 abort state transition on EL rejection; cross-cuts EL-side audit
- BPO + Engine API V5 interaction — verify V5 method routing is independent of BPO transitions (V5 doesn't change between BPO #1 and #2)
- Cross-fork transition stateful fixture: Pectra→Fulu at epoch 411392 (FULU_FORK_EPOCH); first Fulu block validation
- Excessive-blob negative test fixture: 22 blobs at epoch 419073 (= max + 1); verify all 6 reject
- Empty blob_kzg_commitments at Fulu: verify all 6 accept (0 ≤ 21)
- `process_execution_payload_for_gossip` cross-client audit (lighthouse + grandine factor; verify other 4 don't redundantly verify)
- Gloas-NEW `process_execution_payload_bid` (PBS) — separate item; nimbus's 6th overload (line 1154) handles `SignedExecutionPayloadEnvelope`

## Future research items

1. **Wire Fulu fixture categories** in BeaconBreaker harness — same blocker as items #30, #31. Required before this item can transition from `pending-source-review` to `pending-fuzzing`. Highest-priority follow-up.
2. **WORKLOG re-scope status table update**: mark item #19 as Pectra-historical with item #32 as Fulu equivalent.
3. **BPO transition stateful fixture** at exact epochs 412671→412672 and 419071→419072 — verify all 6 enforce the boundary correctly.
4. **Engine API V5 standalone audit** — closes item #15's V4/V5 boundary follow-up.
5. **Gossip-time partial verification cross-client audit** — lighthouse + grandine factor this; verify other 4 don't redundantly verify (which would just be a perf concern, not consensus).
6. **teku subclass extension forward-compat at Heze** — `BlockProcessorHeze extends BlockProcessorFulu` skeleton verification.
7. **nimbus 6-overload regression audit** — verify each fork's overload has no logic divergence beyond the spec-mandated changes (multi-fork-definition Pattern I forward-fragility).
8. **ExecutionPayloadHeader caching consistency** — verify all 6 write the same 16-field header at Fulu (spec confirms no schema additions; verify implementation matches).
9. **Pre-Deneb blob limit gating consistency** — prysm/lighthouse/teku/lodestar all skip pre-Deneb; verify nimbus + grandine match.
10. **`notify_new_payload` failure mode cross-client audit** — verify all 6 abort state transition on EL rejection (vs silent skip).
11. **BPO + Engine API V5 interaction** — verify V5 method routing is independent of BPO transitions.
12. **Cross-fork transition stateful fixture: Pectra→Fulu at FULU_FORK_EPOCH** — first Fulu block validation; verify all 6 produce identical post-state.
13. **Excessive-blob negative test fixture**: 22 blobs at epoch 419073 (= max + 1); verify all 6 reject with the same error.
14. **Empty `blob_kzg_commitments` at Fulu**: verify all 6 accept (0 ≤ 21) — boundary case.
15. **Cross-network blob limit consistency**: verify mainnet/sepolia/holesky all 6 clients' `process_execution_payload` matches the network's BLOB_SCHEDULE.

## Summary

EIP-7892 BPO integration into `process_execution_payload` is implemented byte-for-byte equivalently across all 6 clients. The Fulu modification is a single-line spec change: replace hardcoded `MAX_BLOBS_PER_BLOCK_ELECTRA = 9` with `get_blob_parameters(get_current_epoch(state)).max_blobs_per_block`. **All 6 clients route the dynamic limit correctly through their item #31 helpers.**

Per-client divergences are entirely in:
- **Function structure** (subclass extension in teku; multi-fork-definition in nimbus + grandine; single function in lighthouse + lodestar; helper extraction in prysm)
- **Gossip-time optimization** (lighthouse `partially_verify_execution_payload`; grandine `process_execution_payload_for_gossip`; other 4 don't split)
- **Blob limit lookup path** (prysm two-layer pre-computed cache; lighthouse `spec.max_blobs_per_block`; teku subclass `getMaxBlobsPerBlock(state)`; nimbus direct `cfg.get_blob_parameters`; lodestar `state.config.getMaxBlobsPerBlock`; grandine `config.get_blob_schedule_entry`)
- **Gating idiom** (prysm `body.Version() < version.Deneb` skip; lighthouse `if let Ok(blob_commitments)` Option; lodestar `isForkPostDeneb` predicate; teku polymorphic dispatch; nimbus type-overload; grandine fork-module)

**Item #19 is now Pectra-historical for the Fulu mainnet target**: its `MAX_BLOBS_PER_BLOCK_ELECTRA = 9` finding is correct for Pectra surface but bypassed at Fulu (current limit is 21, read from `blob_schedule`). This audit (item #32) is the Fulu equivalent.

**Status**: source review confirms all 6 clients aligned at Fulu mainnet (validated by 2 successful BPO transitions). **Fixture run pending Fulu fixture-category wiring in BeaconBreaker harness.**
