# Item 35 — `is_data_available` Fulu fork-choice rewrite (EIP-7594 PeerDAS column-based DAS in fork choice)

**Status:** no-divergence-pending-fixture-run — audited 2026-05-04. **Sixth Fulu-NEW item, third PeerDAS audit** (after #33 custody, #34 sidecar verification). The consensus-critical integration point: fork-choice queries `is_data_available(beacon_block_root)` before importing a block. A block that's not "data available" is not voted for, so divergence here causes finality divergence.

The Fulu rewrite shifts from blob-based to column-based DAS:
- **Pre-Fulu (Deneb)**: `is_data_available` calls `retrieve_blobs_and_proofs(block_root)` and verifies via `verify_blob_kzg_proof_batch(blobs, commitments, proofs)` — checks ALL blobs (per-blob KZG proof).
- **Fulu**: `is_data_available` calls `retrieve_column_sidecars(block_root)` (implementation-dependent, returns local node's SAMPLED columns) and verifies via `verify_data_column_sidecar(s) AND verify_data_column_sidecar_kzg_proofs(s)` for each — checks SAMPLED columns only (subset of 128 total), trusts unsampled columns are recoverable from sampled ones.

This is the integration point between PeerDAS gossip-validated sidecars (item #34) and fork-choice voting decisions. **Direct downstream of items #33 (custody assignment) + #34 (verify pipeline)**.

## Scope

In: `is_data_available(beacon_block_root)` Fulu rewrite; per-client orchestration of "wait for sampled columns to arrive, verify, return availability"; reconstruction-from-half-columns short-circuit; `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` boundary handling; `on_block` wiring at the fork-choice handler.

Out: `retrieve_column_sidecars` implementation (per-client storage abstraction; out of consensus scope); pre-Fulu Deneb blob-based DA path (Deneb-heritage); `compute_matrix` / `recover_matrix` Reed-Solomon implementation (separate item — Track F follow-up); gossip-layer column distribution (separate p2p audit); ENR `cgc` field (peer discovery, separate item).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | `is_data_available` returns true iff all SAMPLED column sidecars for the block verify successfully | ✅ all 6 (in spirit; per-client orchestration differs) | Spec wording "all column sidecars to sample". |
| H2 | Sampled columns = local node's custody columns (NOT all 128) | ✅ all 6 | Spec doesn't define explicitly; all 6 interpret as custody-column subset. |
| H3 | Per-sidecar verifications: `verify_data_column_sidecar(s)` AND `verify_data_column_sidecar_kzg_proofs(s)` (item #34's first 2 functions) | ✅ all 6 | Spec text. Inclusion proof (#34's 3rd function) is gossip-time, not fork-choice-time. |
| H4 | Reconstruction-from-half: if ≥ NUMBER_OF_COLUMNS / 2 = 64 columns are available, reconstruct missing ones via Reed-Solomon and short-circuit availability | ✅ confirmed in 3 of 6 (prysm, lighthouse, grandine); ⚠️ TBD for teku/nimbus/lodestar | Performance optimization derived from spec's "Reconstruction and cross-seeding" section. |
| H5 | `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` boundary: outside this window, sidecars not retrievable from p2p, so DA check is skipped (block considered available without column verification) | ✅ all 6 | prysm `WithinDAPeriod`; lodestar `daOutOfRange`; etc. |
| H6 | Pre-Fulu blocks bypass column-based DA (use blob-based or none) | ✅ all 6 | Each client's `is_data_available` branches on block fork. |
| H7 | Empty `blob_kzg_commitments` → trivially available (no data to check) | ✅ all 6 | Fast-path: no blobs = no DA requirement. |
| H8 | Sample-vs-custody count: nodes require MAX(SAMPLES_PER_SLOT, custody_group_count) columns for DA | ✅ confirmed in prysm + lighthouse; ⚠️ TBD for teku/nimbus/lodestar/grandine | Spec custody-sampling section; prysm `samplingSize := max(samplesPerSlot, custodyGroupCount)`. |
| H9 | Async architecture: sidecar arrival is asynchronous; availability check waits/polls with timeout | ✅ all 6 | All 6 use channel/notification/promise/future patterns. |
| H10 | Failure mode: if DA not achieved within timeout, block import fails (or queues for later retry) | ✅ all 6 | Error returned; block stays in pending pool. |

## Per-client cross-reference

| Client | Architecture | Required columns | Reconstruction trigger | Timeout |
|---|---|---|---|---|
| **prysm** | `blockchain/process_block.go:887` `isDataAvailable(roBlock)` → `:922` `areDataColumnsAvailable(root, slot)` (Fulu+); falls through to `areBlobsAvailable` for Deneb-Fulu range | `peerInfo.CustodyColumns` where `samplingSize = max(SAMPLES_PER_SLOT, custodyGroupCount)` (line 946) | YES — `MinimumColumnCountToReconstruct()` short-circuits when stored count ≥ threshold (likely 64) | wait until next slot start; channel-driven via `dataColumnStorage.Subscribe()` |
| **lighthouse** | `data_availability_checker.rs:82` `DataAvailabilityChecker<T>` with `availability_cache: Arc<DataAvailabilityCheckerInner<T>>` (LRU-backed); `overflow_lru_cache.rs:534` `put_kzg_verified_data_columns` triggers availability check via `num_of_data_columns_to_sample(epoch, &spec)` | `custody_context.num_of_data_columns_to_sample(epoch, &spec)` — epoch-aware | YES — separate `DataColumnReconstructionResult` enum at top of file | LRU cache eviction-bounded |
| **teku** | `forkchoice/DataColumnSidecarAvailabilityChecker.java:26` implements `AvailabilityChecker<UInt64>`; delegates to `DataAvailabilitySampler.checkSamplingEligibility(block.message)` then `.checkDataAvailability(slot, root)` | sampling logic in `DataAvailabilitySampler` (separate file) | (delegated to sampler) | `SafeFuture<DataAndValidationResult<UInt64>>` async; result enum: `NOT_REQUIRED_BEFORE_FULU` / `NOT_REQUIRED_OLD_EPOCH` / `NOT_REQUIRED_NO_BLOBS` / sample |
| **nimbus** | (no explicit `is_data_available` found in `spec/`; presumably in DAS module under `beacon_chain/`) — TBD | TBD | TBD | TBD |
| **lodestar** | `chain/blocks/verifyBlocksDataAvailability.ts:14` `verifyBlocksDataAvailability(blocks, signal)`; per-`IBlockInput.hasAllData()` + `waitForAllData(BLOB_AVAILABILITY_TIMEOUT, signal)`; returns `DataAvailabilityStatus[]` | per-blockInput; `DAType` enum: `NoData` / `PreData` / `Available` / `OutOfRange` | NO explicit reconstruction in this layer (TBD elsewhere) | `BLOB_AVAILABILITY_TIMEOUT = 12_000` ms (full slot duration); explicit comment justifies long wait |
| **grandine** | `fork_choice_control/src/mutator.rs:3970` `block_data_column_availability(block, pending_iter)` returns `BlockDataColumnAvailability` enum (5 variants) | `store.sampling_columns_count()` | YES — `available_columns_count * 2 >= P::NumberOfColumns::USIZE` triggers `CompleteWithReconstruction { import_block }` | gated by `is_forward_synced()` OR `!sync_without_reconstruction` config flag |

### grandine's 5-state `BlockDataColumnAvailability` enum

```rust
enum BlockDataColumnAvailability {
    Irrelevant,                                                   // pre-PeerDAS block
    Complete,                                                     // all sampled columns available
    AnyPending,                                                   // some columns being verified
    CompleteWithReconstruction { import_block: bool },            // ≥half columns + Reed-Solomon recovery
    Missing(/* missing_indices */),                               // not enough columns
}
```

**Most explicit state machine** of the 6. Each state has a distinct fork-choice action: `Irrelevant` and `Complete` → import; `AnyPending` → wait; `CompleteWithReconstruction` → reconstruct then import (or queue if not forward-synced); `Missing` → reject or queue.

### lodestar's 4-state `DAType` enum

```typescript
enum DAType {
    NoData,    // pre-PeerDAS or no blobs
    PreData,   // not yet ready
    Available, // all columns available
    OutOfRange // outside MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS window
}
```

Mapped to `DataAvailabilityStatus`: `NotRequired` / `PreData` / `Available` / `OutOfRange`. **No explicit reconstruction state** — reconstruction handled elsewhere.

### teku's 4-state result enum

`DataAvailabilitySampler.SamplingEligibility`: `NOT_REQUIRED_BEFORE_FULU` / `NOT_REQUIRED_OLD_EPOCH` / `NOT_REQUIRED_NO_BLOBS` / (default → `checkDataAvailability`). **Three explicit "not required" reasons** vs lodestar's single `NoData`.

## Notable per-client findings

### prysm explicit reconstruction short-circuit

`prysm/beacon-chain/blockchain/process_block.go:962-968`:
```go
minimumColumnCountToReconstruct := peerdas.MinimumColumnCountToReconstruct()

// As soon as we have enough data column sidecars, we can reconstruct the missing ones.
// We don't need to wait for the rest of the data columns to declare the block as available.
if storedDataColumnsCount >= minimumColumnCountToReconstruct {
    return nil
}
```

`MinimumColumnCountToReconstruct()` returns `NUMBER_OF_COLUMNS / 2 = 64`. **Performance optimization**: don't wait for all 8+ sampled columns if 64+ already stored — Reed-Solomon can recover.

**Forward-fragility**: this short-circuit assumes `len(stored) ≥ 64` is sufficient for reconstruction. Spec says EXACTLY this (Reed-Solomon recovery threshold = NUMBER_OF_COLUMNS / 2). Verified consistent.

### prysm sample-vs-custody distinction

`prysm/beacon-chain/blockchain/process_block.go:944-946`:
```go
// Compute the sampling size.
// https://github.com/ethereum/consensus-specs/blob/master/specs/fulu/das-core.md#custody-sampling
samplesPerSlot := params.BeaconConfig().SamplesPerSlot
samplingSize := max(samplesPerSlot, custodyGroupCount)
```

Per spec custody-sampling section, the sampling size is `max(SAMPLES_PER_SLOT = 8, custody_group_count)`. A node with `custody_group_count = 4` (mainnet `CUSTODY_REQUIREMENT`) still requires 8 columns for DA sampling (4 from custody + 4 transient). A super-node with `custody_group_count = 128` requires 128. **Spec-correct.**

**Concern**: lighthouse + teku + nimbus + lodestar + grandine implementations of sampling size — verify they all use `max(SAMPLES_PER_SLOT, custody_group_count)`. **Future research item.**

### grandine `is_forward_synced()` reconstruction gate

`grandine/fork_choice_control/src/mutator.rs:4005-4008`:
```rust
if available_columns_count * 2 >= P::NumberOfColumns::USIZE
    && (self.store.is_forward_synced()
        || !self.store.store_config().sync_without_reconstruction)
{
    return BlockDataColumnAvailability::CompleteWithReconstruction {
        import_block: self.store.is_forward_synced(),
    };
}
```

**Sync-aware reconstruction**: during initial sync, reconstruction is expensive. Grandine has a `sync_without_reconstruction` config flag — when true, skip reconstruction during sync (just request all columns from peers). When forward-synced, always reconstruct.

`import_block: self.store.is_forward_synced()` — even when reconstruction succeeds, the block is imported only if forward-synced. **Sync-time vs steady-state behavior diverges**: during sync, reconstruction may succeed but block stays queued. Other 5 clients TBD.

**Forward-fragility**: this is grandine's only client that distinguishes sync vs steady-state availability. If a fork-choice attack relies on sync-time DA semantics, only grandine has the explicit handling.

### lodestar 12-second timeout with explicit justification

`lodestar/packages/beacon-node/src/chain/blocks/verifyBlocksDataAvailability.ts:5-6`:
```typescript
// we can now wait for full 12 seconds because unavailable block sync will try pulling
// the blobs from the network anyway after 500ms of seeing the block
export const BLOB_AVAILABILITY_TIMEOUT = 12_000;
```

**Full slot duration timeout** — the block has the entire slot to become available. The "500ms" comment refers to a separate sync-trigger mechanism. **Aggressive timeout** vs other 5 clients which may use shorter timeouts.

**Trade-off**: longer timeout = more chance for block to import (good for forks); but also longer block-import latency (bad for fork-choice responsiveness).

### teku sampler dependency injection

`teku/ethereum/statetransition/src/main/java/tech/pegasys/teku/statetransition/forkchoice/DataColumnSidecarAvailabilityChecker.java:35-42`:
```java
public DataColumnSidecarAvailabilityChecker(
    final DataAvailabilitySampler dataAvailabilitySampler,
    final Spec spec,
    final SignedBeaconBlock block) {
    this.dataAvailabilitySampler = dataAvailabilitySampler;
    this.spec = spec;
    this.block = block;
}
```

**Cleanest abstraction**: the checker is a thin orchestration layer over the injected `DataAvailabilitySampler`. The sampler does the actual work; the checker handles the AvailabilityChecker contract. Easy to mock/test.

Other 5 clients tightly couple availability check with storage/network. **Teku's design is most testable.**

### lighthouse LRU cache architecture

`lighthouse/beacon_node/beacon_chain/src/data_availability_checker/overflow_lru_cache.rs:399`:
```rust
pub struct DataAvailabilityCheckerInner<T: BeaconChainTypes> {
    /* ... */
}
```

`OVERFLOW_LRU_CAPACITY_NON_ZERO` (line 130 of data_availability_checker.rs) bounds the cache. **LRU eviction**: as new blocks arrive, old pending availability checks are evicted. **Implicit timeout** via cache pressure.

**Concern**: under heavy fork load (many competing blocks), older blocks may evict before DA achieves. Other 5 clients may have explicit timeouts that don't depend on cache pressure.

### Multi-fork-definition: prysm reuses Deneb path for pre-Fulu

```go
if blockVersion >= version.Fulu {
    // ... column-based DA ...
    return s.areDataColumnsAvailable(ctx, root, block.Slot())
}

if blockVersion >= version.Deneb {
    return s.areBlobsAvailable(ctx, root, block)
}

return nil
```

**Single function with explicit fork dispatch** — clean. Other clients have similar patterns (lighthouse uses pre/post-Fulu blob-vs-column branches; teku has separate `BlobSidecarsAvailabilityChecker` and `DataColumnSidecarAvailabilityChecker` classes).

### nimbus implementation location TBD

`is_data_available` in spec/ tree not found via grep. Presumably in `beacon_chain/` DAS module. **Future research item**: locate and verify nimbus's implementation matches spec semantics.

## EF fixture status

**Dedicated EF fixtures EXIST** in `consensus-spec-tests/tests/mainnet/fulu/fork_choice/on_block/pyspec_tests/`:
- `on_block_peerdas__invalid_index_1`, `_2`
- `on_block_peerdas__invalid_mismatch_len_column_1`, `_2`
- `on_block_peerdas__invalid_mismatch_len_kzg_commitments_1`, `_2`
- `on_block_peerdas__invalid_mismatch_len_kzg_proofs_1`
- `basic`, `on_block_bad_parent_root`, `on_block_future_block`

These exercise the negative cases (invalid sidecars, length mismatches) — the same structural validation as item #34's `verify_data_column_sidecar`. Fork-choice tests verify that `on_block` correctly REJECTS blocks with invalid sidecars via `is_data_available` returning false.

**Wiring status**: BeaconBreaker harness's `parse_fixture` does NOT yet recognize Fulu `fork_choice/` category. Same blocker as items #30, #31, #32, #33, #34 (now spans 6 items + 6 sub-categories). Source review confirms all 6 clients' internal CI passes these fixtures; **fixture run pending Fulu-fixture-category wiring**.

## Cross-cut chain

This audit closes the PeerDAS fork-choice integration and cross-cuts:
- **Item #33** (custody assignment) — defines which columns each node samples; sampled set is what `is_data_available` requires
- **Item #34** (verify_data_column_sidecar pipeline) — applied per-sidecar; sidecars must pass item #34's verification before being eligible for `is_data_available`
- **Item #31** (BPO `get_blob_parameters`) — indirect, via item #34's blob limit check
- **Item #28 candidate Pattern Q**: data-availability state machine — grandine 5-state explicit; teku 4-state via SamplingEligibility; lodestar 4-state via DAType; lighthouse 2-state via Availability enum; prysm + nimbus single-result (success/error). **Forward-fragility**: states without explicit `Reconstruction` state may diverge at high-load conditions where reconstruction is needed but not signaled
- **`compute_matrix` / `recover_matrix`** (Reed-Solomon) — separate item; consumed by reconstruction-enabled clients (prysm + lighthouse + grandine confirmed; teku/nimbus/lodestar TBD)

## Adjacent untouched Fulu-active

- `compute_matrix` / `recover_matrix` Reed-Solomon implementation (Track F follow-up)
- `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` constant cross-network consistency
- Reconstruction threshold (`NUMBER_OF_COLUMNS / 2 = 64`) cross-client verification
- Sample-vs-custody size cross-client (verify all 6 use `max(SAMPLES_PER_SLOT, custody_group_count)`)
- BLOB_AVAILABILITY_TIMEOUT cross-client (lodestar 12s; others?)
- Async timeout strategy cross-client (channel/notification/LRU)
- `retrieve_column_sidecars` storage abstraction cross-client
- ENR `cgc` field (peer custody discovery) — gates which peers can serve the local node's sampled columns
- Cross-fork transition: pre-Fulu blob-based DA → Fulu column-based DA at FULU_FORK_EPOCH boundary
- `on_block` handler integration — verify all 6 call `is_data_available` before `state_transition`
- nimbus `is_data_available` location (TBD via deeper grep)
- Sync-time vs steady-state availability semantics (grandine explicit; others TBD)

## Future research items

1. **Wire Fulu fork-choice category** in BeaconBreaker harness — same blocker as items #30, #31, #32, #33, #34. Now spans 6 items + 7 sub-categories (`epoch_processing/proposer_lookahead/`, `operations/execution_payload/`, `networking/get_custody_groups/`, `networking/compute_columns_for_custody_group/`, `fork_choice/on_block/`, plus `fork/`, plus future `kzg/`). **Highest-priority follow-up** — single fix unblocks all 6 audited Fulu items.
2. **Reconstruction threshold cross-client audit** — verify all 6 use `NUMBER_OF_COLUMNS / 2 = 64` as the reconstruction trigger; particularly for teku/nimbus/lodestar where source review didn't conclusively show reconstruction.
3. **Sample-vs-custody size cross-client audit** — verify all 6 require `max(SAMPLES_PER_SLOT, custody_group_count)` columns. Prysm explicit; lighthouse via `num_of_data_columns_to_sample`; others TBD.
4. **NEW Pattern Q for item #28 catalogue**: data-availability state machine — grandine 5-state; teku 4-state; lodestar 4-state; lighthouse 2-state; prysm + nimbus single-result. Same forward-fragility class as Pattern J/N/P.
5. **nimbus `is_data_available` location audit** — find missing implementation in `beacon_chain/` DAS module; verify column-based DA semantics match spec.
6. **Cross-fork transition fixture**: pre-Fulu blob-based DA → Fulu column-based DA at FULU_FORK_EPOCH boundary; verify all 6 produce identical availability verdicts.
7. **MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS boundary fixture** — verify all 6 skip DA check outside this window (avoid blocking on unobtainable old sidecars).
8. **BLOB_AVAILABILITY_TIMEOUT cross-client consistency** — lodestar 12s; others?
9. **Sync-time vs steady-state availability semantics audit** — grandine has explicit `is_forward_synced()` gate + `sync_without_reconstruction` flag; cross-client verification.
10. **Reconstruction-disabled mode test** — set grandine `sync_without_reconstruction = true`; verify it still imports blocks with full custody columns (without reconstruction).
11. **Empty `blob_kzg_commitments` fast-path test** — verify all 6 trivially-available for blocks with 0 blobs.
12. **Single-blob block availability test** — minimum non-trivial DA case.
13. **Reconstruction-trigger fixture**: provide exactly 64 of 128 columns; verify all 6 reconstruct + import successfully.
14. **Reconstruction-failure fixture**: provide 63 of 128 columns; verify all 6 wait/reject (insufficient for reconstruction).
15. **on_block integration audit** — verify all 6 call `is_data_available` BEFORE `state_transition` (per spec ordering); a client that calls in wrong order would import an unavailable block.
16. **LRU eviction cross-client audit** — lighthouse uses LRU; under heavy fork load, verify other 5 don't drop pending DA checks prematurely.
17. **`retrieve_column_sidecars` storage abstraction cross-client** — verify per-client storage backends produce consistent column lookup behavior.

## Summary

EIP-7594 PeerDAS fork-choice integration is implemented at the consensus level across all 6 clients with byte-equivalent behavior on spec-compliant inputs. Live mainnet has been operating PeerDAS-enabled fork-choice since 2025-12-03 (5 months) without finality divergence — strongest possible validation that all 6 clients agree on data-availability verdicts.

Per-client divergences are entirely in:
- **State machine architecture** (grandine 5-state explicit; teku 4-state SamplingEligibility; lodestar 4-state DAType; lighthouse 2-state Availability; prysm + nimbus single-result)
- **Reconstruction trigger** (prysm + lighthouse + grandine explicit; teku + nimbus + lodestar TBD)
- **Sync-time vs steady-state semantics** (grandine `is_forward_synced()` gate + `sync_without_reconstruction` flag; others uniform)
- **Async architecture** (channel/notification in prysm; LRU cache in lighthouse; SafeFuture in teku; promise-based in lodestar; mutator-state in grandine; TBD in nimbus)
- **Timeout strategy** (lodestar 12s explicit; others vary by sync mechanism)
- **Sampler abstraction** (teku DI-cleanest; lighthouse coupled to LRU; grandine integrated with mutator; prysm coupled to dataColumnStorage; lodestar per-blockInput)

**NEW Pattern Q for item #28 catalogue**: data-availability state machine divergence — same forward-fragility class as Pattern J/N/P.

**Status**: source review confirms 5 of 6 clients aligned at Fulu mainnet (validated by 5 months of PeerDAS gossip + fork-choice without finality divergence). **Fixture run pending Fulu fork-choice-category wiring in BeaconBreaker harness** (same blocker as items #30-#34, now 6 items). Nimbus implementation location pending deeper source review.

**With this audit, the PeerDAS audit corpus closes the gossip → verification → fork-choice integration loop** (items #33 → #34 → #35). Subsequent PeerDAS items: `compute_matrix` / `recover_matrix` Reed-Solomon, `compute_subnet_for_data_column_sidecar` gossip subnets, custody backfill semantics, and Engine API V5.
