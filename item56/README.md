# Item 56 — Fulu fork choice modifications: `is_data_available` (PeerDAS-modified) + `on_block` (signature change) — FIRST TRACK D AUDIT

**Status:** no-divergence on observable behavior; **6 distinct dispatch architectures + NEW Pattern II candidate (fork choice DA architecture divergence)** — audited 2026-05-04. **Twenty-sixth Fulu-NEW item, eighteenth PeerDAS audit, FIRST FORK CHOICE (Track D) audit**. Consensus-critical — different fork choice = different head selection.

**Spec definition** (`fulu/fork-choice.md`):

**Modified `is_data_available`** (Fulu):
```python
def is_data_available(beacon_block_root: Root) -> bool:
    # `retrieve_column_sidecars` is implementation and context dependent, replacing
    # `retrieve_blobs_and_proofs`. For the given block root, it returns all column
    # sidecars to sample, or raises an exception if they are not available.
    column_sidecars = retrieve_column_sidecars(beacon_block_root)
    return all(
        verify_data_column_sidecar(column_sidecar)
        and verify_data_column_sidecar_kzg_proofs(column_sidecar)
        for column_sidecar in column_sidecars
    )
```

**Modified `on_block`** (Fulu):
> The only modification is that `is_data_available` does not take `blob_kzg_commitments` as input.

Pre-Fulu (Deneb):
```python
def is_data_available(slot, beacon_block_root, blob_kzg_commitments) -> bool:
    blobs, proofs = retrieve_blobs_and_proofs(beacon_block_root)
    return verify_blob_kzg_proof_batch(blobs, blob_kzg_commitments, proofs)
```

**Major findings**:
1. **All 6 clients implement Fulu DA semantic** (5+ months of cross-client mainnet operation confirms)
2. **6 distinct dispatch architectures** for fork choice DA verification — most diverse architecture finding so far
3. **NEW Pattern II candidate for item #28 catalogue**: Fork choice DA verification architecture divergence
4. **Cross-cuts item #34 (verification path)** — same `verify_data_column_sidecar` + `verify_data_column_sidecar_kzg_proofs` used in gossip + fork choice
5. **Block queueing diversity** — 6 distinct strategies for "block arrived but data not yet available"
6. **First Track D audit** — opens a previously unaudited surface

## Scope

In: `is_data_available` Fulu implementation per-client; `on_block` Fulu signature change handling; multi-fork-definition pattern (Pattern I/J/R/II family); block queueing for unavailable data; integration with item #34 verification path; custody-aware vs sampling-aware verification; cross-cut to item #46 (RPC retrieval), #55 (retention period).

Out: Fulu fork choice tie-breaking rules (Phase0-heritage); proposer boost (Capella-heritage); fork choice score calculation; LMD GHOST algorithm details; Reed-Solomon recovery integration (item #39 covered); detailed gossip validation (item #34 covered).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | All 6 clients implement Fulu fork choice DA check | ✅ all 6 | 5+ months of mainnet operation |
| H2 | All 6 use `verify_data_column_sidecar` + `verify_data_column_sidecar_kzg_proofs` (item #34) | ✅ all 6 (architecture differs but verification path same) | Spec mandate |
| H3 | All 6 dispatch on fork (pre-Fulu blob check vs Fulu column check) | ✅ all 6 | Necessary for fork transition |
| H4 | All 6 implement block queueing for unavailable data | ✅ all 6 (6 distinct strategies) | Spec MAY clause |
| H5 | All 6 use `is_data_available` literal function name | ❌ only prysm + lighthouse + teku name it that way; nimbus uses quarantine pool API; lodestar uses DAType enum; grandine uses EIP-7594 module | Architecture divergence |
| H6 | Multi-fork-definition pattern (Pattern I/J/R) applies to fork choice | ✅ teku Pattern J (separate `AvailabilityChecker` classes); nimbus 3-quarantine pattern (separate per-fork pools); lodestar Pattern R (DAType union); others type-based | NEW Pattern II candidate |
| H7 | Cross-cut to item #34 verification path | ✅ all 6 | Same verify_* functions |
| H8 | Custody-aware verification (CUSTODY_REQUIREMENT = 4 columns) | ⚠️ all 6 use SAMPLES_PER_SLOT (= 8) sampling per spec; some clients use higher custody count | Cross-cut item #38 |
| H9 | Block queueing strategy | ⚠️ 6 distinct strategies — synchronous blocking, LRU cache, async future, quarantine pool, union-type, operation pool | Pattern II divergence |
| H10 | Live mainnet validation: 5+ months without observed fork choice divergence | ✅ all 6 | Production validation |

## Per-client cross-reference

| Client | Function/architecture | File:line | Fork dispatch | Block queueing |
|---|---|---|---|---|
| **prysm** | `areDataColumnsAvailable` (Fulu) vs `areBlobsAvailable` (Deneb) | `process_block.go:887-918` (`if blockVersion >= version.Fulu`) | Binary version check | **Synchronous blocking wait** on notifier channels (lines 954-1002); custody-aware via `peerdas.Info()` |
| **lighthouse** | `DataAvailabilityChecker<T>` wrapper with type-based dispatch | `data_availability_checker.rs:1-100+` | Type-based via `BlobSidecar` (Deneb) vs `DataColumnSidecar` (Fulu+) types | **LRU cache** (`PendingComponents`, max 32); `verify_kzg_for_data_column_list` integration |
| **teku** | **Pattern J — separate `AvailabilityChecker` classes per fork**: `BlobSidecarsAvailabilityChecker` (Deneb) + `DataColumnSidecarAvailabilityChecker` (Fulu) | `BlobSidecarsAvailabilityChecker.java:36+` + `DataColumnSidecarAvailabilityChecker.java:26+` | Class instantiation via `BlobSidecarManagerImpl.java:66` + `DasSamplerManager.java:37` | **Async `SafeFuture`** (`initiateDataAvailabilityCheck`); status enum NOT_REQUIRED_BEFORE_FULU/_OLD_EPOCH/_NO_BLOBS |
| **nimbus** | **3-QUARANTINE PATTERN**: `blobQuarantine` (Deneb) + `dataColumnQuarantine` (Fulu) + `gloasColumnQuarantine` (Gloas) — 3 separate quarantines per fork | `nimbus_beacon_node.nim:570/611/811`; `consensus_object_pools/blob_quarantine.nim` | Quarantine pool dispatch via `popSidecars(forkyBlck.root, forkyBlck)` (`:662`) | **Quarantine pool with `custodyMap`** — block waits for column sidecars to populate quarantine; pruned at finalization |
| **lodestar** | **Pattern R — `DAType` union type dispatch**: `PreData` / `Blobs` (Deneb) / `Columns` (Fulu) / `NoData`; union type `DAData = null \| deneb.BlobSidecars \| fulu.DataColumnSidecar[]` | `verifyBlocksDataAvailability.ts:14-45` + `blockInput/types.ts:5-12` | Runtime DAType enum discrimination | **`SeenBlockInput` LRU cache** (`seenGossipBlockInput.ts:100+`); max `(MAX_LOOK_AHEAD_EPOCHS + 1) * SLOTS_PER_EPOCH`; pruned on finalization + range sync completion |
| **grandine** | **EIP-7594 module integration**: `eip_7594/src/lib.rs` — heavy PeerDAS native integration with custody group computation + cell KZG proof batch verification | `eip_7594/src/lib.rs:1-100+` (Fulu + Gloas variants) | Type-based via `FuluDataColumnSidecar` vs `GloasDataColumnSidecar` | **`BlobReconstructionPool`** (`operation_pools/blob_reconstruction_pool/tasks.rs`) — async recovery for missing data |

## Notable per-client findings

### NEW Pattern II candidate — Fork choice DA architecture divergence (most diverse so far)

**6 distinct dispatch architectures** for the same spec semantic:

1. **prysm** — Single function `process_block.go:898 if blockVersion >= version.Fulu` with binary version check. Synchronous blocking wait via channels. Most procedural.

2. **lighthouse** — Type-based dispatch via `BlobSidecar` vs `DataColumnSidecar` enum. Single `DataAvailabilityChecker<T>` wrapper. Type system enforces fork dispatch.

3. **teku** — **Pattern J** — separate `AvailabilityChecker<T>` classes per fork (`BlobSidecarsAvailabilityChecker` + `DataColumnSidecarAvailabilityChecker`). Most enterprise-Java OOP. Each fork has its own class with own status enum.

4. **nimbus** — **3-QUARANTINE PATTERN** — separate quarantine pools per fork (`blobQuarantine` + `dataColumnQuarantine` + `gloasColumnQuarantine`). The quarantine IS the DA check — block waits in quarantine until columns arrive. Most data-structure-driven.

5. **lodestar** — **Pattern R** — `DAType` enum union type dispatch with runtime type discrimination + `DAData` union type for sidecar storage. Most TypeScript-idiomatic.

6. **grandine** — Module-based integration via `eip_7594/src/lib.rs` with custody group computation + cell KZG proof batch verification. Native PeerDAS focus. Most module-isolated.

**Same forward-fragility class as Pattern I/J/R** (multi-fork-definition family). At Heze + Gloas, each client must extend its dispatch pattern. Different patterns have different extension complexity:
- prysm binary check: easy to add `if blockVersion >= version.Heze` (linear)
- teku class-per-fork: needs new `AvailabilityChecker` class per fork (linear but verbose)
- nimbus 3-quarantine pattern: each fork needs a NEW quarantine type (linear; gloasColumnQuarantine already exists)
- lodestar DAType enum: needs new variant per fork (linear)

### Nimbus 3-quarantine architecture (MOST FORK-AWARE)

Nimbus has **already implemented Gloas column quarantine** (`gloasColumnQuarantine` at `nimbus_beacon_node.nim:611`) — pre-Gloas readiness. This is the FOURTH distinct quarantine (blobQuarantine for Deneb/Electra + dataColumnQuarantine for Fulu + gloasColumnQuarantine for Gloas). Nimbus is most prepared for Gloas at the fork choice DA layer.

Cross-cut to **item #28 Gloas readiness scoreboard**: nimbus is the leader (was previously: nimbus > grandine > lighthouse > prysm > lodestar > teku). This audit confirms nimbus's Gloas readiness on the DA layer.

### Cross-cut to item #34 verification path

All 6 clients use the SAME `verify_data_column_sidecar` + `verify_data_column_sidecar_kzg_proofs` functions for fork choice DA AND gossip validation. This is consistent with the spec's spirit — the same verification primitives apply at multiple layers.

**Pattern P risk** (item #34): grandine's hardcoded gindex 11 affects BOTH gossip-time inclusion proof verification AND fork-choice-time DA verification. **Pattern P is more pervasive than item #34 alone documented** — extends to fork choice layer.

### Custody-aware vs sampling-aware divergence

| Client | Approach |
|---|---|
| prysm | **Sampling-aware** via `peerdas.Info(nodeID, samplingSize)` — checks SAMPLES_PER_SLOT = 8 sampled columns |
| lighthouse | **Custody-aware** — verifies columns within node's custody set (CUSTODY_REQUIREMENT or higher per node config) |
| teku | **Sampling-aware** via `DataAvailabilitySampler.checkSamplingEligibility()` returns sampled column indices |
| nimbus | **Custody-aware** via `custodyMap` in quarantine pool |
| lodestar | **Sampling-aware** via `CustodyConfig` driving DataColumnSidecar validation |
| grandine | **Custody-aware** via explicit custody group computation in EIP-7594 module |

**3 vs 3 split**: 3 sampling-aware (prysm, teku, lodestar); 3 custody-aware (lighthouse, nimbus, grandine).

**Important nuance**: spec says "all column sidecars to sample" — meaning the SAMPLING SUBSET (SAMPLES_PER_SLOT = 8 columns by default), NOT the full custody set (CUSTODY_REQUIREMENT = 4 minimum, but most nodes custody more). The sampling-aware approach is more spec-faithful; custody-aware is more conservative (verifies more than required → safer but slower).

**Cross-client divergence**: a sampling-aware client MAY accept a block where only 8 sampled columns are present; a custody-aware client REQUIRES all custodied columns (which could be 8+) to be present. **Forward-fragility**: at high blob loads, custody-aware nodes MAY reject blocks that sampling-aware nodes accept → fork divergence.

**Pattern II refinement**: the architecture choice (sampling vs custody) directly affects spec compliance and forward-fragility. Same pattern as Pattern E/F/M (Gloas A-tier divergences from item #28).

### Block queueing strategy (6 distinct)

Spec says "this payload MAY be queued and subsequently considered when blob data becomes available". Each client implements differently:

1. **prysm — Synchronous blocking wait** (`process_block.go:954-1002`): goroutine waits on notifier channels until data arrives or timeout. Simplest; blocks the import flow.
2. **lighthouse — LRU cache** (`PendingComponents`, max 32): non-blocking; blocks held in cache; processed when data arrives. Bounded memory.
3. **teku — Async SafeFuture**: non-blocking; future resolved when data available. JVM-idiomatic.
4. **nimbus — Quarantine pool with custodyMap**: data-structure-driven; columns added to pool as they arrive; block "popped" from quarantine when complete.
5. **lodestar — SeenBlockInput LRU**: similar to lighthouse but with `(MAX_LOOK_AHEAD_EPOCHS + 1) * SLOTS_PER_EPOCH` cap; pruned on finalization + range sync completion.
6. **grandine — BlobReconstructionPool**: operation pool with async recovery for missing data; integrates Reed-Solomon recovery (item #39).

**Cross-client divergence on edge cases**:
- What if data arrives 5 minutes after block? prysm times out; others may still process.
- What if block + data arrive simultaneously? lighthouse/lodestar may bypass cache; others process via cache.
- What if cache fills? lighthouse/lodestar evict oldest; nimbus/grandine TBD.

**Pattern T-style spec-undefined edge case**: timeout values, eviction policies, recovery integration all client-specific.

### Live mainnet validation

5+ months of cross-client Fulu fork choice operation without observed divergence. All 6 clients accept the same canonical chain. Sampling-vs-custody divergence has not manifested because mainnet blob loads are well below worst-case (max 21 blobs per block at BPO #2, well within sampling capacity).

**Forward-fragility at higher blob loads**: at hypothetical 100+ blobs per block, sampling-aware vs custody-aware divergence could manifest. Currently no observable divergence.

### `on_block` signature change handling

All 6 correctly drop `blob_kzg_commitments` parameter from `is_data_available` call at Fulu. Pre-Fulu fork dispatch passes 3 args; Fulu dispatch passes 1 arg (block_root only).

**Architecture divergence**:
- prysm: same function, version-gated argument list
- lighthouse: separate type variants (BlobSidecar passes commitments; DataColumnSidecar doesn't)
- teku: separate AvailabilityChecker classes (different signatures per class)
- nimbus: separate quarantine types (different APIs per quarantine)
- lodestar: DAType enum dispatches to different code paths
- grandine: type-based dispatch via DataColumnSidecar variants

All 6 produce identical observable behavior (block accepted when all sampled/custodied columns verified).

## Cross-cut chain

This audit OPENS Track D (fork choice) and cross-cuts:
- **Item #34** (DataColumnSidecar verification): same `verify_data_column_sidecar` + `verify_data_column_sidecar_kzg_proofs` used for fork choice DA — Pattern P risk extends to fork choice layer
- **Item #38** (validator custody): determines columns to verify (custody-aware path)
- **Item #39** (Reed-Solomon math): grandine's BlobReconstructionPool integrates recovery
- **Item #46** (DataColumnSidecarsByRange/Root v1): RPC retrieval for missing columns
- **Item #51** (gossip subscription): columns received via gossip populate quarantine pool
- **Item #54** (DataColumnSidecar SSZ): container being verified at fork choice
- **Item #55** (retention period): defines window for which DA must be checked
- **Item #28 NEW Pattern II candidate**: Fork choice DA architecture divergence — 6 distinct architectures + sampling-vs-custody A-tier risk
- **Item #28 Pattern J extension**: teku separate AvailabilityChecker classes per fork; nimbus separate quarantines per fork; new variant of Pattern J at fork choice layer
- **Item #28 Gloas readiness refinement**: nimbus's `gloasColumnQuarantine` confirms nimbus is leader on Gloas DA layer
- **Item #48** (catalogue refresh): adds Pattern II + sampling-vs-custody finding

## Adjacent untouched Fulu-active

- Fork choice tie-breaking rules per-client (Phase0-heritage)
- Proposer boost handling at Fulu (Capella-heritage)
- LMD GHOST algorithm cross-client implementation
- Fork choice score calculation cross-client
- Reorg-on-late-block behavior at Fulu
- Block import flow per-client (cross-cut to this audit)
- Equivocation slashing detection during fork choice
- Justified-finalized checkpoint advancement
- Pre-Fulu transition fork choice handling (block at slot N has Deneb format, slot N+1 has Fulu format)
- Cross-fork DA continuity at FULU_FORK_EPOCH boundary
- DA timeout values per-client (spec-undefined)
- DA cache eviction policies per-client
- Equivocation handling during block queueing
- Fork choice integration with gossip layer (cross-cut item #51)

## Future research items

1. **NEW Pattern II for item #28 catalogue**: Fork choice DA verification architecture divergence — 6 distinct architectures; sampling-vs-custody divergence is A-tier forward-fragility risk at high blob loads.
2. **Pattern J extension for item #28 catalogue**: teku separate AvailabilityChecker classes + nimbus separate quarantines per fork. Multi-fork-definition family extends to fork choice layer.
3. **Sampling-vs-custody cross-client interop test**: simulate block with only 8 sampled columns present; verify sampling-aware clients (prysm, teku, lodestar) accept; custody-aware clients (lighthouse, nimbus, grandine) reject.
4. **Block queueing timeout audit**: per-client timeout values + behavior on timeout. Spec-undefined edge case (Pattern T-style).
5. **DA cache eviction policy audit**: per-client cache size limits + eviction strategy.
6. **Reorg-on-late-data behavior**: what happens when block accepted with N columns, then more columns arrive later? Per-client behavior may differ.
7. **Cross-fork transition DA continuity audit (Track D + Fulu boundary)**: at FULU_FORK_EPOCH (slot 13164544), block N is Deneb format (blob check); block N+1 is Fulu format (column check). Per-client transition handling.
8. **Equivocation handling during block queueing**: if equivocating block arrives while DA pending, per-client behavior may differ.
9. **Pre-emptive Gloas DA layer audit**: nimbus has gloasColumnQuarantine; other 5 client status TBD. Cross-cut to item #28 Gloas readiness scoreboard.
10. **Track D opening — fork choice tie-breaking, proposer boost, LMD GHOST cross-client audits**: this is the FIRST Track D audit; many more pending.
11. **Pattern II refinement for catalogue**: catalogue all 6 distinct architectures + their forward-fragility profiles at Heze + Gloas + future forks.
12. **DA verification + Reed-Solomon recovery integration**: grandine's BlobReconstructionPool integrates recovery into DA check. Other 5 may have separate recovery paths.
13. **Live network DA timeout statistics**: instrument all 6 clients to log DA timeout events; estimate cross-client divergence frequency.

## Summary

EIP-7594 PeerDAS Fulu fork choice modifications: `is_data_available` rewritten to use column sidecars instead of blobs; `on_block` drops `blob_kzg_commitments` parameter. Track D (fork choice) is OPENED with this audit — first of many fork choice cross-client audits.

**All 6 clients implement Fulu DA semantic** with **6 distinct dispatch architectures**:

| Client | Architecture | Block queueing |
|---|---|---|
| **prysm** | Binary version check + `areDataColumnsAvailable` | Synchronous blocking wait |
| **lighthouse** | Type-based via `BlobSidecar`/`DataColumnSidecar` enum | LRU cache (`PendingComponents`, 32) |
| **teku** | **Pattern J** — separate `AvailabilityChecker` classes per fork | Async `SafeFuture` |
| **nimbus** | **3-QUARANTINE PATTERN** — `blobQuarantine` + `dataColumnQuarantine` + `gloasColumnQuarantine` | Quarantine pool with `custodyMap` |
| **lodestar** | **Pattern R** — `DAType` enum union type dispatch | `SeenBlockInput` LRU |
| **grandine** | EIP-7594 module integration with custody groups | `BlobReconstructionPool` |

**NEW Pattern II candidate for item #28 catalogue**: Fork choice DA verification architecture divergence — most diverse architecture finding so far. Same forward-fragility class as Pattern I/J/R (multi-fork-definition family).

**A-tier forward-fragility — sampling-vs-custody divergence**:
- **Sampling-aware** (prysm, teku, lodestar): verify SAMPLES_PER_SLOT = 8 sampled columns
- **Custody-aware** (lighthouse, nimbus, grandine): verify all custodied columns
- At high blob loads (hypothetical 100+ blobs per block), sampling-aware MAY accept blocks that custody-aware reject → potential fork divergence

**Nimbus pre-Gloas leader**: `gloasColumnQuarantine` already implemented (`nimbus_beacon_node.nim:611`); confirms item #28 Gloas readiness scoreboard ranking (nimbus > grandine > lighthouse > prysm > lodestar > teku).

**Cross-cut to item #34 Pattern P**: grandine's hardcoded gindex 11 (item #34) affects BOTH gossip-time AND fork-choice-time DA verification. Pattern P is more pervasive than item #34 alone documented.

**Block queueing diversity**: 6 distinct strategies (synchronous blocking, LRU cache, async future, quarantine pool, union-type dispatch, operation pool). Pattern T-style spec-undefined edge cases (timeout values, eviction policies, recovery integration) all client-specific.

**Live mainnet validation**: 5+ months of cross-client Fulu fork choice operation without observed divergence. All 6 accept same canonical chain. Sampling-vs-custody divergence not manifested because mainnet blob loads (max 21 per block at BPO #2) are within sampling capacity.

**With this audit, Track D (fork choice) is OPENED**. Many more fork choice cross-client audits pending: tie-breaking rules, proposer boost, LMD GHOST, score calculation, reorg-on-late-block, etc.

**PeerDAS audit corpus now spans 18 items**: #33 → #34 → #35 → #37 → #38 → #39 → #40 → #41 → #42 → #44 → #45 → #46 → #47 → #49 → #53 → #54 → #55 → **#56**.

**Total Fulu-NEW items: 26 (#30–#56)**. Item #28 catalogue **Patterns A–II (35 patterns)** with NEW Pattern II (Fork choice DA architecture divergence) + Pattern J extension to fork choice layer + Pattern P extension to fork choice layer + Gloas readiness scoreboard refinement.
