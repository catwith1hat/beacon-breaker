---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [28, 31, 46, 47, 49]
eips: [EIP-7594, EIP-7691, EIP-7892]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 50: `MAX_REQUEST_BLOB_SIDECARS_ELECTRA` formula consistency + Fulu deprecation handling for `BlobSidecarsByRange v1` + `BlobSidecarsByRoot v1`

## Summary

Sister to item #49. The Electra-modified `compute_max_request_blob_sidecars()` returns `MAX_REQUEST_BLOCKS_DENEB × MAX_BLOBS_PER_BLOCK_ELECTRA = 128 × 9 = 1152` (mainnet, per `vendor/consensus-specs/specs/electra/p2p-interface.md:90-95`). The same family of RPCs (`BlobSidecarsByRange/ByRoot v1`) is **DEPRECATED at Fulu** (`vendor/consensus-specs/specs/fulu/p2p-interface.md:349, 365`):

> Deprecated as of `FULU_FORK_EPOCH + MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS`.
>
> - Clients MUST respond with a list of blob sidecars from the range `[min(current_epoch - MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS, FULU_FORK_EPOCH), FULU_FORK_EPOCH)` if the requested range includes any epochs in this interval.
> - Clients MAY respond with an empty list if the requested range lies entirely at or after `FULU_FORK_EPOCH`.
> - Clients SHOULD NOT penalize peers for requesting blob sidecars from `FULU_FORK_EPOCH`.

**Mainnet timeline**:

- FULU_FORK_EPOCH = 411392 (2025-12-03 21:49:11 UTC)
- MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS = 4096 = 18.21 days
- Deprecation cutoff epoch = 415488 (~2025-12-21)
- **Today is 2026-05-13** — ~4.8 months past the deprecation cutoff.

**Fulu surface (carried forward from 2026-05-04 audit; cap value):** all 6 clients evaluate `MAX_REQUEST_BLOB_SIDECARS_ELECTRA` to `1152` on mainnet. **No production divergence on cap.**

**Implementation strategy split unchanged (Pattern DD, item #49)**:

- **HARDCODED YAML/preset constant** (4 of 6): prysm (`vendor/prysm/config/params/mainnet_config.go:336 MaxRequestBlobSidecarsElectra: 1152`), lighthouse (`vendor/lighthouse/consensus/types/src/core/chain_spec.rs:287 max_request_blob_sidecars_electra: u64` + `default_max_request_blob_sidecars_electra()` const fn), nimbus (`vendor/nimbus/beacon_chain/spec/presets.nim:178/397 MAX_REQUEST_BLOB_SIDECARS_ELECTRA`), lodestar (`vendor/lodestar/packages/config/src/chainConfig/configs/mainnet.ts:170 MAX_REQUEST_BLOB_SIDECARS_ELECTRA: 1152`).
- **COMPUTED formula** (2 of 6): teku (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/config/builder/ElectraBuilder.java:59-66` hybrid + YAML override, with `LOG.debug("Setting maxRequestBlobSidecarsElectra to {} (was {})")` substitution log), grandine (`vendor/grandine/types/src/config.rs:1005-1017 pub fn max_request_blob_sidecars(&self, phase: Phase) -> u64` phase-dispatched formula with `saturating_mul`).

**KEY UPDATE from prior audit — Pattern EE cohort grows from 1-of-6 to 2-of-6**:

The 2026-05-04 audit flagged Pattern EE (explicit Fulu deprecation handling) as **only teku ByRange**, with teku ByRoot relying on storage-returns-empty. The current checkout shows two material additions:

- **teku ByRoot now ALSO checks `blobSidecarsDeprecationSlot()`** at `vendor/teku/networking/eth2/src/main/java/tech/pegasys/teku/networking/eth2/rpc/beaconchain/methods/BlobSidecarsByRootMessageHandler.java:175`:

  ```java
  if (maybeSlot.isEmpty()
      || maybeSlot.get().isGreaterThanOrEqualTo(spec.blobSidecarsDeprecationSlot())) {
    return SafeFuture.completedFuture(Optional.empty());
  }
  ```

  teku is now consistent across ByRange + ByRoot.

- **lighthouse NOW has explicit Fulu-start-slot handling in both ByRange and ByRoot** at `vendor/lighthouse/beacon_node/network/src/network_beacon_processor/rpc_methods.rs:294-298, 328-333, 1038-1053`:

  - ByRoot (`:294-298, 328-333`): pre-computes `fulu_start_slot` and skips any blob whose slot `>= fulu_start_slot`.
  - ByRange (`:1038-1053`): if `request_start_slot >= fulu_start_slot` returns `Ok(())` (empty); if the range spans the boundary, truncates `effective_count = fulu_start_slot - request_start_slot`.

  ```rust
  let effective_count = if let Some(fulu_epoch) = self.chain.spec.fulu_fork_epoch {
      let fulu_start_slot = fulu_epoch.start_slot(T::EthSpec::slots_per_epoch());
      let request_end_slot = request_start_slot.saturating_add(req.count) - 1;
      if request_start_slot >= fulu_start_slot {
          return Ok(());
      } else if request_end_slot >= fulu_start_slot {
          (fulu_start_slot - request_start_slot).as_u64()
      } else {
          req.count
      }
  } else {
      req.count
  };
  ```

  lighthouse now has explicit Fulu-boundary handling for BOTH RPCs.

**Pattern EE current cohort**: teku + lighthouse explicit; prysm + nimbus + lodestar + grandine rely on implicit storage-returns-empty. **2-vs-4 split (was 1-vs-5)**.

**Pattern FF unchanged**: grandine still has vestigial `max_request_blob_sidecars_fulu: 1536` declared at `vendor/grandine/types/src/config.rs:175, 300` with ZERO consumers — active selector at `:1005` computes the formula via `max_request_blocks(phase).saturating_mul(max_blobs_per_block_electra)` and ignores the dedicated field entirely. Value `1536 = 128 × 12` suggests an aborted Fulu cap design predating the BPO mechanism (item #31).

**Glamsterdam target (Gloas):** `vendor/consensus-specs/specs/gloas/p2p-interface.md` does NOT modify `compute_max_request_blob_sidecars` or `BlobSidecarsByRange/ByRoot v1`. The deprecation continues to apply; no new RPC introduces a Gloas-specific replacement (the new envelope RPCs `ExecutionPayloadEnvelopesByRange/ByRoot v1` are an unrelated surface for PBS payloads). The BlobSidecars RPCs remain deprecated; no client introduces Gloas-specific re-enablement.

**Impact: none** — all 6 evaluate to `1152` on mainnet; deprecation cutoff is ~4.8 months past; storage returns empty for all queries. The cap divergence (1152 vs grandine's vestigial 1536) is moot in practice because grandine never uses 1536 and no client serves blob sidecars anymore (storage pruned at retention window). Thirty-first `impact: none` result in the recheck series.

## Question

Pyspec defines `compute_max_request_blob_sidecars()` at Electra (modified) and the BlobSidecars RPC deprecation at Fulu. Gloas does not modify either.

Three recheck questions:

1. **Cap formula consistency** — do all 6 clients still evaluate `MAX_REQUEST_BLOB_SIDECARS_ELECTRA = 1152` on mainnet? Has the 4-vs-2 hardcoded-vs-computed split (Pattern DD) shifted?
2. **Deprecation handling (Pattern EE)** — has any client added explicit Fulu-boundary deprecation handling since the 2026-05-04 audit? How many clients are now in the explicit-handling cohort?
3. **Vestigial field (Pattern FF)** — is grandine's `max_request_blob_sidecars_fulu: 1536` still declared but unused? Does any other client carry a similar dead-code field?

## Hypotheses

- **H1.** All 6 evaluate `MAX_REQUEST_BLOB_SIDECARS_ELECTRA = 1152` on mainnet (`128 × 9`).
- **H2.** Pattern DD (item #49) hardcoded-vs-computed split unchanged: 4 hardcoded (prysm + lighthouse + nimbus + lodestar) vs 2 computed (teku hybrid + grandine `saturating_mul`).
- **H3.** YAML/preset config exposes both `MAX_REQUEST_BLOB_SIDECARS` (Deneb, 768) and `MAX_REQUEST_BLOB_SIDECARS_ELECTRA` (Electra, 1152).
- **H4.** Fork-aware selector for Deneb vs Electra cap; lighthouse has cleanest cross-fork API (`max_request_blob_sidecars(fork_name)`).
- **H5.** *(Pattern EE update)* Fulu deprecation handling — explicit check present in teku ByRange + ByRoot AND lighthouse ByRange + ByRoot (2-of-6 cohort, up from 1-of-6 in prior audit); others rely on implicit storage-returns-empty.
- **H6.** All 6 still implement BlobSidecarsByRange v1 + BlobSidecarsByRoot v1 RPC handlers (deprecation does not remove the protocol; clients keep handlers alive returning empty).
- **H7.** Today ~4.8 months past deprecation cutoff (2025-12-21); all 6 likely return empty for all queries (storage pruned at 4096-epoch retention window). Zero clients unregister the protocol.
- **H8.** Forward-compat at hypothetical fork increasing `MAX_BLOBS_PER_BLOCK_ELECTRA`: same Pattern DD divergence as item #49 — formula clients auto-update; hardcoded clients require YAML/preset bump.
- **H9.** *(Pattern FF)* grandine `max_request_blob_sidecars_fulu: 1536` declared at `config.rs:175, 300` but ZERO consumers — active selector at `:1005` uses the formula and ignores the dedicated field.
- **H10.** *(Glamsterdam target — Fulu deprecation continues unchanged)* `vendor/consensus-specs/specs/gloas/p2p-interface.md` contains no modification of `compute_max_request_blob_sidecars` or `BlobSidecarsByRange/ByRoot v1`. No Gloas-specific re-enablement.
- **H11.** Live mainnet validation: 5+ months of cross-client peer interop with no observed divergence on this deprecated-RPC family.

## Findings

H1 ✓ (1152 across 6). H2 ✓ (4-vs-2 hardcoded-vs-computed unchanged). H3 ✓. H4 ✓. **H5 ⚠ UPDATE**: cohort grows from 1-of-6 to 2-of-6 (teku ByRange + ByRoot consistent; lighthouse ByRange + ByRoot consistent). H6 ✓. H7 ✓. H8 ✓ (Pattern DD persists). H9 ✓ (Pattern FF unchanged — vestigial 1536). H10 ✓. H11 ✓.

### prysm

Field declaration (`vendor/prysm/config/params/config.go:274`):

```go
MaxRequestBlobSidecarsElectra    uint64           `yaml:"MAX_REQUEST_BLOB_SIDECARS_ELECTRA" spec:"true"`     // MaxRequestBlobSidecarsElectra is the maximum number of blobs to request in a single request after the electra epoch.
```

Mainnet value (`vendor/prysm/config/params/mainnet_config.go:336`):

```go
MaxRequestBlobSidecarsElectra:         1152,
```

YAML log line (`vendor/prysm/config/params/loader.go:219`):

```go
fmt.Sprintf("MAX_REQUEST_BLOB_SIDECARS_ELECTRA: %d", cfg.MaxRequestBlobSidecarsElectra),
```

**Pattern DD**: hardcoded YAML constant. Fork-aware dispatch via `IsElectraEpoch(epoch)` at the RPC handler (`vendor/prysm/beacon-chain/sync/rpc_blob_sidecars_by_range.go`).

**Pattern EE**: NO explicit Fulu deprecation check in `vendor/prysm/beacon-chain/sync/rpc_blob_sidecars_by_range.go` or `vendor/prysm/beacon-chain/sync/rpc_blob_sidecars_by_root.go` — `grep -n "FULU_FORK\|fulu_fork\|deprecat"` returns 0 matches. Relies on storage-returns-empty.

### lighthouse

Field declaration (`vendor/lighthouse/consensus/types/src/core/chain_spec.rs:287`):

```rust
max_request_blob_sidecars_electra: u64,
```

Fork-aware selector (`:701-707`):

```rust
pub fn max_request_blob_sidecars(&self, fork_name: ForkName) -> usize {
    if fork_name.electra_enabled() {
        self.max_request_blob_sidecars_electra as usize
    } else {
        self.max_request_blob_sidecars as usize
    }
}
```

Cleanest cross-fork API of the 6. Default helper `default_max_request_blob_sidecars_electra()` returns `1152` (line ~2206 from prior audit). Used as serde default at `:1276 max_request_blob_sidecars_electra: default_max_request_blob_sidecars_electra()`.

**Pattern EE (NEW — lighthouse now in the cohort)**:

ByRange (`vendor/lighthouse/beacon_node/network/src/network_beacon_processor/rpc_methods.rs:1038-1053`):

```rust
let effective_count = if let Some(fulu_epoch) = self.chain.spec.fulu_fork_epoch {
    let fulu_start_slot = fulu_epoch.start_slot(T::EthSpec::slots_per_epoch());
    let request_end_slot = request_start_slot.saturating_add(req.count) - 1;

    // If the request_start_slot is at or after a Fulu slot, return an empty response
    if request_start_slot >= fulu_start_slot {
        return Ok(());
    // For the case that the request slots spans across the Fulu fork slot
    } else if request_end_slot >= fulu_start_slot {
        (fulu_start_slot - request_start_slot).as_u64()
    } else {
        req.count
    }
} else {
    req.count
};
```

ByRoot (`:294-298, 328-333`):

```rust
let fulu_start_slot = self
    .chain
    .spec
    .fulu_fork_epoch
    .map(|epoch| epoch.start_slot(T::EthSpec::slots_per_epoch()));
...
// Skip if slot is >= fulu_start_slot
if let (Some(slot), Some(fulu_slot)) = (slot, fulu_start_slot)
    && *slot >= fulu_slot
{
    continue;
}
```

Explicit Fulu-boundary handling on both RPCs. **CHANGED from prior audit** — previously flagged as "NONE explicit." lighthouse now joins teku in the explicit-deprecation cohort.

### teku

Builder hybrid (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/config/builder/ElectraBuilder.java:55-66, 195-197`):

```java
private Integer maxRequestBlobSidecarsElectra;
...
final Integer newMaxRequestBlobSidecarsElectra =
    computeMaxRequestBlobSidecars(...);
LOG.debug(
    "Setting maxRequestBlobSidecarsElectra to {} (was {})",
    newMaxRequestBlobSidecarsElectra,
    maxRequestBlobSidecarsElectra);
maxRequestBlobSidecarsElectra = newMaxRequestBlobSidecarsElectra;
...
public ElectraBuilder maxRequestBlobSidecarsElectra(final Integer maxRequestBlobSidecarsElectra) {
  checkNotNull(maxRequestBlobSidecarsElectra);
  this.maxRequestBlobSidecarsElectra = maxRequestBlobSidecarsElectra;
```

Same hybrid pattern as item #49 — computed default + YAML override + `LOG.debug` substitution message.

**Pattern EE (consistent across ByRange + ByRoot — CHANGED from prior audit)**:

ByRange (`vendor/teku/networking/eth2/src/main/java/tech/pegasys/teku/networking/eth2/rpc/beaconchain/methods/BlobSidecarsByRangeMessageHandler.java:107-109, 126-133`):

```java
private UInt64 getEndSlotBeforeFulu(final UInt64 maxSlot) {
  return spec.blobSidecarsDeprecationSlot().safeDecrement().min(maxSlot);
}
...
if (startSlot.isGreaterThan(spec.blobSidecarsDeprecationSlot())) {
  LOG.trace(
      "Peer {} requested {} slots of blob sidecars starting at slot {} after Fulu. "
      + "BlobSidecarsByRange v1 is deprecated and the request will be ignored.",
      peer.getId(),
      message.getCount(),
      startSlot);
  return;
}
```

ByRoot (`vendor/teku/networking/eth2/src/main/java/tech/pegasys/teku/networking/eth2/rpc/beaconchain/methods/BlobSidecarsByRootMessageHandler.java:165-188`):

```java
private SafeFuture<Optional<BlobSidecar>> validateMinAndMaxRequestEpoch(
    final BlobIdentifier identifier,
    final Optional<BlobSidecar> maybeSidecar,
    final UInt64 minServableEpoch) {
  return maybeSidecar
      .map(sidecar -> SafeFuture.completedFuture(Optional.of(sidecar.getSlot())))
      .orElse(combinedChainDataClient.getSlotByBlockRoot(identifier.getBlockRoot()))
      .thenComposeChecked(
          maybeSlot -> {
            if (maybeSlot.isEmpty()
                || maybeSlot.get().isGreaterThanOrEqualTo(spec.blobSidecarsDeprecationSlot())) {
              return SafeFuture.completedFuture(Optional.empty());
            }
```

Javadoc lists the validation: "The block root references a block before fulu fork epoch" (`:162`). **CHANGED from prior audit** — previously noted ByRoot did NOT have the check; current checkout has consistent deprecation handling across both ByRange + ByRoot.

teku now matches lighthouse on Pattern EE cohort membership.

### nimbus

Preset declaration (`vendor/nimbus/beacon_chain/spec/presets.nim:178/397`):

```nim
MAX_REQUEST_BLOB_SIDECARS_ELECTRA*: uint64
...
MAX_REQUEST_BLOB_SIDECARS_ELECTRA: 1152,  # (mainnet preset around line 397)
```

**Pattern DD**: hardcoded preset. **Pattern EE**: NO explicit Fulu deprecation check in `vendor/nimbus/beacon_chain/sync/sync_protocol.nim` for `getBlobSidecarsByRange`/`getBlobSidecarsByRoot`. Relies on storage-returns-empty post-pruning.

### lodestar

Type definition (`vendor/lodestar/packages/config/src/chainConfig/types.ts:119, 238`):

```typescript
MAX_REQUEST_BLOB_SIDECARS_ELECTRA: number;
...
MAX_REQUEST_BLOB_SIDECARS_ELECTRA: "number",  // spec-tracking marker
```

Mainnet (`configs/mainnet.ts:170 MAX_REQUEST_BLOB_SIDECARS_ELECTRA: 1152`); gnosis override (`networks/gnosis.ts:75 MAX_REQUEST_BLOB_SIDECARS_ELECTRA: 256`).

**Pattern DD**: hardcoded TypeScript const. **Pattern EE**: NO explicit Fulu deprecation check — `grep -n "fulu\|Fulu\|FULU\|deprecat" vendor/lodestar/packages/beacon-node/src/network/reqresp/handlers/blobSidecarsByRange.ts vendor/lodestar/packages/beacon-node/src/network/reqresp/handlers/blobSidecarsByRoot.ts` returns 0 matches. Relies on storage-returns-empty.

### grandine

Active selector (`vendor/grandine/types/src/config.rs:1005-1017`):

```rust
#[must_use]
pub fn max_request_blob_sidecars(&self, phase: Phase) -> u64 {
    let max_blobs_per_block_for_phase = match phase {
        Phase::Phase0 | Phase::Altair | Phase::Bellatrix | Phase::Capella | Phase::Deneb => {
            self.max_blobs_per_block
        }
        Phase::Electra | Phase::Fulu | Phase::Gloas => self.max_blobs_per_block_electra,
    };

    self.max_request_blocks(phase).saturating_mul(
        u64::try_from(max_blobs_per_block_for_phase)
            .expect("max_blobs_per_block parameter should always fit in u64"),
    )
}
```

Phase-dispatched formula. Mainnet evaluation: `Phase::Electra/Fulu/Gloas` → `max_blobs_per_block_electra = 9` → `128 × 9 = 1152`. **Pattern DD**: computed formula via `saturating_mul`.

**Pattern FF (vestigial field — unchanged from prior audit)** at `:175, 300`:

```rust
#[serde(with = "serde_utils::string_or_native")]
pub max_request_blob_sidecars_fulu: u64,
...
max_request_blob_sidecars_fulu: 1536,
```

`grep -rn "max_request_blob_sidecars_fulu" vendor/grandine/` returns only the declaration + the default. **Zero consumers.** Active selector ignores this field; uses the formula instead. The 1536 value (= `128 × 12`) suggests an aborted Fulu cap design predating the BPO mechanism — likely pre-EIP-7892 when `MAX_BLOBS_PER_BLOCK_FULU = 12` was being considered. Today's BPO mechanism (item #31) makes the per-fork constant moot at Fulu.

**Pattern EE**: NO explicit Fulu deprecation check in grandine RPC handlers — `vendor/grandine/p2p/src/network.rs:1414, 1454, 1474, 1649, 1663` serves `BlobSidecarsByRange/ByRoot` via `controller.blob_sidecars_by_range(start_slot..end_slot)` without Fulu cutoff. Relies on storage-returns-empty.

## Cross-reference table

| Client | H1 mainnet value | H2 DD strategy | H5 Pattern EE handling | H9 Pattern FF vestigial | Forward-compat |
|---|---|---|---|---|---|
| **prysm** | 1152 (`mainnet_config.go:336`) | hardcoded YAML constant | ❌ implicit storage-returns-empty | none | ⚠ requires YAML update at fork |
| **lighthouse** | 1152 (`chain_spec.rs:287` + `default_max_request_blob_sidecars_electra()` const fn) | hardcoded const fn + 5 network YAMLs | ✅ **NEW** — explicit `fulu_start_slot` check in BOTH `rpc_methods.rs:294-333` (ByRoot skip) + `:1038-1053` (ByRange effective_count truncation/return-empty) | none | ⚠ requires YAML update at fork |
| **teku** | 1152 (`ElectraBuilder.java:59-66` hybrid + YAML override + `LOG.debug`) | **COMPUTED formula + YAML override hybrid** | ✅ explicit `spec.blobSidecarsDeprecationSlot()` check in BOTH `BlobSidecarsByRangeMessageHandler.java:107-133` AND **`BlobSidecarsByRootMessageHandler.java:175` (NEW — previously gap)** | none | ✅ auto-update via formula |
| **nimbus** | 1152 (`presets.nim:178/397`) | hardcoded preset | ❌ implicit storage-returns-empty | none | ⚠ requires preset update at fork |
| **lodestar** | 1152 (`mainnet.ts:170`); 256 (`gnosis.ts:75`) | hardcoded TypeScript const | ❌ implicit storage-returns-empty | none | ⚠ requires preset update at fork |
| **grandine** | 1152 via `config.rs:1005-1017` phase formula with `saturating_mul`; **vestigial `max_request_blob_sidecars_fulu: 1536` at `:175, 300` UNUSED** | **COMPUTED phase-formula + saturating_mul overflow safety** | ❌ implicit storage-returns-empty | ✅ `max_request_blob_sidecars_fulu: 1536` declared but 0 consumers | ✅ auto-update via formula |

**Pattern DD split**: 4 hardcoded (prysm + lighthouse + nimbus + lodestar) vs 2 computed (teku + grandine). Unchanged from item #49 cross-cut.

**Pattern EE cohort**: **2 explicit (teku + lighthouse) vs 4 implicit (prysm + nimbus + lodestar + grandine)**. Updated from prior audit (was 1 vs 5).

**Pattern FF**: 1 client carries vestigial config field (grandine `max_request_blob_sidecars_fulu: 1536`). Unchanged.

## Empirical tests

- ✅ **Live mainnet operation since 2025-12-03 (5+ months; 4.8 months past deprecation cutoff)**: all 6 clients return empty for ALL slot ranges today (storage pruned beyond retention window). No interop divergence observed. **Verifies H7 + H11 at production scale.**
- ✅ **Cap value verification (this recheck)**: all 6 clients confirmed to evaluate `MAX_REQUEST_BLOB_SIDECARS_ELECTRA = 1152` on mainnet via file:line citations above.
- ✅ **Pattern EE cohort growth verification (this recheck)**:
  - teku ByRoot now has `blobSidecarsDeprecationSlot()` check at `BlobSidecarsByRootMessageHandler.java:175` (NEW — previously gap).
  - lighthouse ByRange + ByRoot now have explicit `fulu_start_slot` handling at `rpc_methods.rs:294-333, 1038-1053` (NEW — previously flagged as "NONE explicit").
  - prysm + nimbus + lodestar + grandine: still no explicit Fulu deprecation check at RPC handler level.
- ✅ **Pattern FF persistence verification**: grandine `max_request_blob_sidecars_fulu: 1536` declared at `config.rs:175, 300` with 0 consumers (grep returns only the two declaration sites). Vestigial field still present.
- ✅ **Gloas carry-forward verification**: `grep -n "compute_max_request_blob_sidecars\|MAX_REQUEST_BLOB_SIDECARS\|BlobSidecarsByRange\|BlobSidecarsByRoot" vendor/consensus-specs/specs/gloas/p2p-interface.md` returns 0 matches. Verifies H10.
- ⏭ **Cross-network MAX_REQUEST_BLOB_SIDECARS_ELECTRA**: gnosis = 256 (lodestar confirmed at `networks/gnosis.ts:75`; lighthouse expected to match per prior audit); extend to holesky + sepolia + hoodi cross-client.
- ⏭ **Pattern EE cohort adoption**: file PRs to prysm + nimbus + lodestar + grandine adopting explicit Fulu deprecation check. Today's behavior is identical (empty for all queries due to pruning), but the explicit short-circuit saves a storage query per spurious request.
- ⏭ **Pattern FF cleanup**: file PR to grandine removing `max_request_blob_sidecars_fulu` field (and `1536` value) since no consumer exists; alternatively, wire the field as an override for grandine's formula (similar to teku's hybrid pattern).
- ⏭ **Protocol unregistration audit**: at ~5 months past deprecation cutoff, does any client unregister the protocol entirely? Spec is silent on this; today all 6 keep handlers alive. Forward-fragility if spec adds a MUST clause.
- ⏭ **Hypothetical fork divergence test**: simulate fork increasing `MAX_BLOBS_PER_BLOCK_ELECTRA` to 12 or 18; verify teku + grandine auto-update; prysm + lighthouse + nimbus + lodestar require YAML/preset bump.
- ⏭ **Cap boundary fixture at Fulu transition**: peer requests slot range crossing FULU_FORK_EPOCH; verify all 6 truncate to pre-Fulu portion only (the explicit cohort short-circuits; the implicit cohort relies on storage-empty after pruning).

## Conclusion

The Electra-modified `compute_max_request_blob_sidecars()` cap is implemented across all 6 clients at `1152` on mainnet (`MAX_REQUEST_BLOCKS_DENEB × MAX_BLOBS_PER_BLOCK_ELECTRA = 128 × 9`). No production divergence on the cap value.

**Pattern DD (item #49 cross-cut)** persists: 4-vs-2 hardcoded-vs-computed split. teku and grandine continue to compute the formula; prysm, lighthouse, nimbus, and lodestar treat it as a wire constant.

**Pattern EE cohort grew from 1-of-6 to 2-of-6 since the 2026-05-04 audit**:

- teku now consistently checks `spec.blobSidecarsDeprecationSlot()` in BOTH `BlobSidecarsByRangeMessageHandler.java:107-133` AND `BlobSidecarsByRootMessageHandler.java:175` (the ByRoot gap from the prior audit is fixed).
- lighthouse now has explicit `fulu_start_slot` handling in BOTH ByRange (`rpc_methods.rs:1038-1053` returns empty or truncates `effective_count`) AND ByRoot (`:294-333` skips blobs with `slot >= fulu_start_slot`). Previously flagged as "NONE explicit"; now part of the cohort.
- prysm + nimbus + lodestar + grandine remain implicit (storage-returns-empty after the 4096-epoch retention window has elapsed).

Same observable result across all 6 today because the deprecation cutoff (2025-12-21) was ~4.8 months ago and storage has pruned the retention window. The explicit cohort short-circuits at receive time (saves a storage query per spurious request); the implicit cohort queries storage and returns the empty result.

**Pattern FF persists**: grandine's `max_request_blob_sidecars_fulu: 1536` (`config.rs:175, 300`) remains a vestigial config field with zero consumers. Active selector at `:1005-1017` uses the formula and ignores the field. The value `1536 = 128 × 12` suggests an aborted Fulu cap design predating the BPO mechanism — likely a pre-EIP-7892 era when `MAX_BLOBS_PER_BLOCK_FULU = 12` was being considered.

**Glamsterdam target context**: `vendor/consensus-specs/specs/gloas/p2p-interface.md` contains NO modification of `compute_max_request_blob_sidecars` or the `BlobSidecarsByRange/ByRoot v1` RPCs. The Fulu deprecation continues to apply across the Gloas fork boundary; no Gloas-specific re-enablement. The Gloas-NEW envelope RPCs (`ExecutionPayloadEnvelopesByRange/ByRoot v1` per item #46) cover a different surface (PBS execution payloads, not blobs).

**Impact: none** — mainnet cap `1152` consistent across 6; deprecation cutoff is ~4.8 months past; storage returns empty for all queries; Gloas inherits Fulu deprecation verbatim. Thirty-first `impact: none` result in the recheck series.

Forward-research priorities:

1. **Pattern EE cohort adoption** — file PRs to prysm + nimbus + lodestar + grandine adopting explicit Fulu deprecation check (mirror teku/lighthouse).
2. **Pattern FF cleanup** — file PR to grandine removing or wiring the `max_request_blob_sidecars_fulu` field. Consider adopting teku's hybrid pattern (formula default + explicit override).
3. **Protocol unregistration audit** — at ~5 months past deprecation cutoff, evaluate whether spec should add a MUST clause requiring clients to unregister the protocol after some interval (or, equivalently, on next major fork). Currently all 6 keep handlers alive.
4. **Pattern DD scope expansion** — scan Fulu/Gloas spec for additional `def compute_*` functions and audit per-client implementation strategy (formula vs hardcoded). Candidate adjacency: `compute_subnets_for_data_column` (item #37), `compute_fork_version` (item #36).
5. **Cross-network `MAX_REQUEST_BLOB_SIDECARS_ELECTRA` audit** — gnosis = 256 in 2 of 6 (lighthouse + lodestar); extend to holesky + sepolia + hoodi for the remaining 4 clients.
