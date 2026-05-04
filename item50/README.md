# Item 50 — `MAX_REQUEST_BLOB_SIDECARS` formula consistency + Fulu deprecation handling for `BlobSidecarsByRange/Root v1` RPCs

**Status:** no-divergence-pending-fixture-run on cap value (1152); **forward-compat + active explicit-deprecation divergence** — audited 2026-05-04. **Twentieth Fulu-NEW-relevant item, FIRST DEPRECATED-RPC audit**. Sister to item #49 (`MAX_REQUEST_DATA_COLUMN_SIDECARS`) — `MAX_REQUEST_BLOB_SIDECARS` is the Deneb-heritage / Electra-modified cap for the SAME-FAMILY RPCs that are DEPRECATED at Fulu.

**Spec definition** (`electra/p2p-interface.md` "Modified `compute_max_request_blob_sidecars`"):
```python
def compute_max_request_blob_sidecars() -> uint64:
    """Return the maximum number of blob sidecars in a single request."""
    # [Modified in Electra:EIP7691]
    return uint64(MAX_REQUEST_BLOCKS_DENEB * MAX_BLOBS_PER_BLOCK_ELECTRA)
```

Mainnet: `128 × 9 = 1152`. Deneb baseline was `128 × 6 = 768` (pre-Electra `MAX_BLOBS_PER_BLOCK = 6`).

**Fulu deprecation** (`fulu/p2p-interface.md`):
- `BlobSidecarsByRange v1` and `BlobSidecarsByRoot v1`: **Deprecated as of `FULU_FORK_EPOCH + MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS`**
- During transition: serve pre-Fulu blob sidecars; MAY return empty for post-Fulu requests
- After cutoff: spec silent; presumably fully removable

**Mainnet timeline**:
- FULU_FORK_EPOCH = 411392 (2025-12-03)
- MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS = 4096 (~18.2 days)
- **Deprecation cutoff: epoch 415488 (~2025-12-21)**
- **Today: 2026-05-04 = ~4.5 months PAST deprecation cutoff**

**Major findings**:
1. **Pattern DD (item #49) extends here**: same hardcoded-vs-formula split as item #49. Teku consistently uses HYBRID pattern across both `MAX_REQUEST_DATA_COLUMN_SIDECARS` AND `MAX_REQUEST_BLOB_SIDECARS_ELECTRA`.
2. **NEW Pattern EE candidate**: deprecated-RPC handling at fork transition. Only teku has explicit `blobSidecarsDeprecationSlot()` check; other 5 rely on implicit storage-returns-empty.
3. **NEW Pattern FF candidate**: vestigial config fields. grandine has `max_request_blob_sidecars_fulu: 1536` declared at `config.rs:175/300` but **NOT USED** anywhere in the codebase (active selector at `:1005` computes the formula).
4. **lighthouse fork-aware selector** at `chain_spec.rs:701`: cleanest cross-fork API.

## Scope

In: `compute_max_request_blob_sidecars()` formula `MAX_REQUEST_BLOCKS_DENEB × MAX_BLOBS_PER_BLOCK_ELECTRA`; per-client implementation strategy (formula vs hardcoded); Deneb → Electra cap migration (768 → 1152); BlobSidecarsByRange/Root v1 RPC handler architecture; Fulu deprecation transition handling; post-deprecation-cutoff behavior; cross-client interop during deprecation period.

Out: BlobSidecarsByRange/Root v1 detailed protocol semantics (Deneb-heritage); MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS constant cross-client (Deneb-heritage); blob sidecar storage pruning behavior; ENR-based blob serving advertisements (covered by Status v2 item #47); DataColumnSidecarsByRange/Root v1 (item #46 covered).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | All 6 clients evaluate `MAX_REQUEST_BLOB_SIDECARS_ELECTRA` to `1152` on mainnet | ✅ all 6 | `128 × 9 = 1152` |
| H2 | Spec defines as a FUNCTION (computed) — `MAX_REQUEST_BLOCKS_DENEB × MAX_BLOBS_PER_BLOCK_ELECTRA` | ✅ implemented as function in 2 of 6 (teku, grandine); ❌ hardcoded constant in 4 of 6 (prysm, lighthouse, nimbus, lodestar) | Same Pattern DD as item #49 |
| H3 | YAML config exposes both `MAX_REQUEST_BLOB_SIDECARS` (768) and `MAX_REQUEST_BLOB_SIDECARS_ELECTRA` (1152) | ✅ all 6 | Pre-Electra and Electra+ caps both surfaced |
| H4 | Fork-aware selector for Deneb (768) vs Electra (1152) | ✅ all 6 | All 6 dispatch on fork |
| H5 | Fulu deprecation: explicit `if startSlot >= FULU_FORK_EPOCH return empty` logic | ⚠️ **only teku** (`BlobSidecarsByRangeMessageHandler.java:126-133`) | NEW Pattern EE candidate |
| H6 | All 6 implement BlobSidecarsByRange v1 + BlobSidecarsByRoot v1 RPC methods | ✅ all 6 | Inherited from Deneb |
| H7 | Post-deprecation-cutoff behavior (today, 4.5 months past) | ⚠️ all 6 likely return empty (storage pruned at 4096 epochs); ZERO clients unregister protocol | Spec-silent edge case |
| H8 | Forward-compat: at hypothetical fork increasing `MAX_BLOBS_PER_BLOCK_ELECTRA` | ⚠️ DIVERGENCE — formula clients (teku) auto-update; hardcoded clients require YAML config bump | Same forward-fragility as item #49 |
| H9 | grandine has Fulu-specific cap field/value | ✅ DEAD CODE — `max_request_blob_sidecars_fulu: 1536` declared but UNUSED (active selector computes formula) | NEW Pattern FF candidate |
| H10 | Live mainnet validation: 5+ months without divergence | ✅ all 6 | Most requests now satisfied by storage-returns-empty; cap divergence not observable |

## Per-client cross-reference

| Client | `MAX_REQUEST_BLOB_SIDECARS_ELECTRA` source | Active selector | Fulu deprecation handling |
|---|---|---|---|
| **prysm** | hardcoded YAML `MaxRequestBlobSidecarsElectra: 1152` (`mainnet_config.go:336`) + `MaxRequestBlobSidecars: 768` | `blobSidecarsByRangeRPCHandler` (`rpc_blob_sidecars_by_range.go:63`) selects via epoch (`:103-106`) | **NONE explicit** — relies on storage-returns-empty |
| **lighthouse** | hardcoded `default_max_request_blob_sidecars_electra() -> u64 { 1152 }` (`chain_spec.rs:2206`) + `default_max_request_blob_sidecars() -> u64 { 768 }` (`:2180`) + YAML serde defaults | **fork-aware selector** `max_request_blob_sidecars(fork_name)` (`:701-707`) — cleanest API | **NONE explicit** — `BlobsByRangeRequestItems` no Fulu check |
| **teku** | YAML config `MAX_REQUEST_BLOB_SIDECARS_ELECTRA: 1152` (gnosis: 256) + **COMPUTES formula** in `ElectraBuilder.java:60 computeMaxRequestBlobSidecars` (HYBRID — same as item #49) | `BlobSidecarsByRangeMessageHandler.validateRequest` (`:82-105`) | **EXPLICIT `blobSidecarsDeprecationSlot()` check** at `:107-109` (`getEndSlotBeforeFulu`) and `:126-133` (return empty if `startSlot > deprecationSlot`) — UNIQUE |
| **nimbus** | hardcoded YAML preset `MAX_REQUEST_BLOB_SIDECARS_ELECTRA*: uint64` at `presets.nim:178/397` | `getBlobSidecarsByRange()` template (`sync_protocol.nim:177-227`) | **NONE explicit** — implicit empty for post-Fulu slots |
| **lodestar** | hardcoded TS const `MAX_REQUEST_BLOB_SIDECARS_ELECTRA: 1152` (`mainnet.ts:170`) + `MAX_REQUEST_BLOB_SIDECARS: 768` (`:160`) | `onBlobSidecarsByRange` (`blobSidecarsByRange.ts:11-132`) + rate limiting (`rateLimit.ts:43-50`) | **NONE explicit** — bounded by pre-Deneb-epoch check (`:117-120`) only |
| **grandine** | **active**: `max_request_blob_sidecars(phase)` selector at `config.rs:1005` COMPUTES formula `max_request_blocks(phase).saturating_mul(max_blobs_per_block_electra)`. **vestigial**: `max_request_blob_sidecars_fulu: 1536` field declared at `:175` with default at `:300` — UNUSED elsewhere | grep confirms ZERO consumers of `max_request_blob_sidecars_fulu` field outside declaration | **NONE explicit** — same fall-back to storage-empty |

## Notable per-client findings

### CRITICAL — Only teku implements explicit Fulu deprecation logic

Teku `BlobSidecarsByRangeMessageHandler.java`:
```java
// Line 107-109
private UInt64 getEndSlotBeforeFulu(final UInt64 maxSlot) {
  return spec.blobSidecarsDeprecationSlot().safeDecrement().min(maxSlot);
}

// Line 126-133 (in onIncomingMessage)
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

**Spec compliance interpretation**: spec says clients MAY return empty for post-Fulu ranges. Teku is most defensive — doesn't even query storage; short-circuits at receive time. Other 5 clients query storage, get empty (post-Fulu blocks have no blob sidecars), return empty. **Same observable result, different implementation cost** — teku saves one storage query per spurious request.

**NEW Pattern EE candidate for item #28 catalogue**: deprecated-RPC handling at fork transition. Only teku surfaces explicit deprecation; other 5 implicit. Same forward-fragility class as Pattern Z (implementation gap on optional spec features) but for the inverse direction (spec deprecates a feature, clients differ on whether to short-circuit).

**Important**: `BlobSidecarsByRootMessageHandler.java` (sister handler) does NOT have the same `blobSidecarsDeprecationSlot()` check. Uses `validateMinAndMaxRequestEpoch` (`:117-149`) for min-epoch retention bound only. **Inconsistency within teku**: ByRange has explicit deprecation check; ByRoot relies on storage-returns-empty. Possible follow-up bug-fix opportunity.

### Deprecation timeline analysis

- FULU_FORK_EPOCH = 411392 (2025-12-03 21:49:11 UTC)
- MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS = 4096
- 4096 epochs × 32 slots × 12s = 1572864s = 18.21 days
- **Deprecation cutoff epoch: 415488 (~2025-12-21)**
- **Today: 2026-05-04 (epoch ~437432) — 4.5 months PAST deprecation cutoff**

After cutoff, the spec is silent. None of the 6 clients **unregister the protocol**. All 6 keep handlers alive but return empty due to storage pruning. **Forward-compat question**: at what point should clients remove the protocol entirely? No spec guidance.

### Pattern DD (item #49) extends here — same 4-2 split

Same hardcoded-vs-computed split as item #49:

- **HARDCODED YAML constant** (4 of 6): prysm, lighthouse, nimbus, lodestar
- **COMPUTED formula** (2 of 6): teku (HYBRID — formula + YAML override) + grandine (formula via `saturating_mul`)

Teku's hybrid pattern is **consistent across both** `MAX_REQUEST_DATA_COLUMN_SIDECARS` (item #49) AND `MAX_REQUEST_BLOB_SIDECARS_ELECTRA` (item #50). Same `ElectraBuilder.java:60-66` style, with `LOG.debug("Setting maxRequestBlobSidecarsElectra to {} (was {})")` log message. Most spec-faithful + most config-friendly.

### Lighthouse fork-aware selector

```rust
// chain_spec.rs:701
pub fn max_request_blob_sidecars(&self, fork_name: ForkName) -> usize {
    if fork_name.electra_enabled() {
        self.max_request_blob_sidecars_electra as usize
    } else {
        self.max_request_blob_sidecars as usize
    }
}
```

Cleanest cross-fork API of the 6. Single getter, fork-name parameter, branches on `electra_enabled()`. Other clients dispatch via different mechanisms (epoch comparison, separate functions).

`max_request_blobs_upper_bound()` (`:712-718`) for testing — returns Electra cap if Electra is scheduled, else Deneb cap. Defensive testing utility.

### Grandine vestigial `max_request_blob_sidecars_fulu: 1536` (NEW Pattern FF candidate)

```rust
// config.rs:175
#[serde(with = "serde_utils::string_or_native")]
pub max_request_blob_sidecars_fulu: u64,

// config.rs:300 (default for mainnet config)
max_request_blob_sidecars_fulu: 1536,
```

Only references in entire codebase: declaration + default. **Dead config field**. Active selector `max_request_blob_sidecars(phase)` at `:1005` IGNORES this field and computes the formula:

```rust
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

`max_request_blob_sidecars(Fulu) = max_request_blocks_deneb × max_blobs_per_block_electra = 128 × 9 = 1152` (matches other 5).

**The 1536 value** = `128 × 12`. Suggests an aborted Fulu cap design (perhaps `MAX_BLOBS_PER_BLOCK_FULU = 12` was considered before BPO design landed; 12 = midpoint of the eventual BPO range 9→15→21).

**NEW Pattern FF candidate for item #28 catalogue**: vestigial config fields — declared but unused, suggesting in-progress refactor or aborted design. Forward-fragility class: future spec changes might re-introduce a Fulu cap field; YAML config files may include `max_request_blob_sidecars_fulu` causing parse failures in other 5 clients.

### Prysm dual-cap pattern

`MaxRequestBlobSidecars` (768) AND `MaxRequestBlobSidecarsElectra` (1152) BOTH declared in `config.go:273-274`. Per-fork dispatch in `rpc_blob_sidecars_by_range.go:103-106`:
```go
// (paraphrased from Explore findings)
if helpers.IsElectraEpoch(epoch, ...) {
    cap = MaxRequestBlobSidecarsElectra
} else {
    cap = MaxRequestBlobSidecars
}
```

Same dual-cap dispatch in lighthouse, nimbus, lodestar. teku uses YAML-driven; grandine uses phase-parameterized formula.

### Live mainnet validation (post-deprecation)

5+ months of cross-client peer-discovery and Status v2 advertisement (item #47) have shown that:
- Pre-Fulu blob sidecars are now beyond the 4096-epoch retention window — storage returns empty
- Post-Fulu requests for blob sidecars get empty (no blob sidecars exist for post-Fulu blocks; only column sidecars)
- **Net effect**: BlobSidecarsByRange v1 returns empty for ALL slot ranges today

**No interop divergence observed** because all 6 return empty regardless of cap value. The cap distinction (1152 vs 1536) is **moot in practice** because grandine never USES the 1536 value, and no client serves blob sidecars anymore (storage pruned).

**Forward-fragility potential**: if a peer requests a slot range crossing FULU_FORK_EPOCH (still in 4096-epoch retention window briefly after Fulu), the cap divergence could manifest. But that window has long passed.

## Cross-cut chain

This audit closes the deprecated-RPC family and cross-cuts:
- **Item #49** (`MAX_REQUEST_DATA_COLUMN_SIDECARS`): identical Pattern DD analysis applied to the **post-Fulu** RPC (column sidecars) vs this audit's **pre-Fulu-heritage** RPC (blob sidecars)
- **Item #46** (`DataColumnSidecarsByRange/Root v1`): the active replacement RPC for the deprecated BlobSidecarsByRange/Root v1
- **Item #47** (Status v2 RPC): introduces `earliest_available_slot` partly to address blob-sidecar retention boundary that motivates the deprecation
- **Item #31** (`get_blob_parameters`): blob count went from 9 (Electra) to 21 (Fulu BPO #2) — `MAX_REQUEST_BLOB_SIDECARS = 1152` based on 9 is now further obsolete
- **Item #28 NEW Pattern EE candidate**: deprecated-RPC handling at fork transition (only teku explicit)
- **Item #28 NEW Pattern FF candidate**: vestigial config fields (grandine `max_request_blob_sidecars_fulu`)
- **Item #48** (catalogue refresh): adds Patterns EE + FF to the catalogue

## Adjacent untouched Fulu-active

- BlobSidecarsByRoot v1 deprecation handling (teku does NOT have explicit check there — inconsistency with ByRange handler)
- Protocol-deregistration semantics post-deprecation-cutoff (no spec guidance; all 6 keep handler alive)
- gnosis network divergence (`MAX_REQUEST_BLOB_SIDECARS_ELECTRA: 256` per teku/lighthouse YAML)
- Cross-network retention boundary (sepolia/holesky/gnosis/hoodi `MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS`)
- Blob sidecar storage pruning behavior cross-client (spec-undefined for post-deprecation)
- Backward compatibility with peers running pre-Fulu binaries (Status v2 fork_digest gating)
- gossip topic deprecation (`blob_sidecar_{subnet_id}` vs `data_column_sidecar_{subnet_id}`)
- Validator-side deprecation: do validators still construct BlobSidecars at Fulu (no — only DataColumnSidecars)
- prysm dual-error pattern: does prysm have separate `errMaxRequestBlobSidecarsExceeded` vs `ErrMaxBlobReqExceeded` (analog to item #49 finding)?
- BlobSidecarsByRange v1 vs BlobSidecarsByRoot v1 — does deprecation cutoff also apply to ByRoot? (Spec says yes; teku only enforces on ByRange.)

## Future research items

1. **NEW Pattern EE for item #28 catalogue**: deprecated-RPC handling at fork transition. Only teku has explicit `blobSidecarsDeprecationSlot()` check; other 5 implicit. Same forward-fragility class as Pattern Z (optional-feature implementation gap) but for **deprecation-direction**. Forward-fragility: spec may add MUST clause requiring explicit deprecation behavior.
2. **NEW Pattern FF for item #28 catalogue**: vestigial config fields (grandine `max_request_blob_sidecars_fulu: 1536`). Forward-fragility: future spec may re-introduce a Fulu cap field; YAML configs from one client may have unknown fields parsed by another.
3. **Teku ByRoot inconsistency**: `BlobSidecarsByRootMessageHandler.java` does NOT have the deprecation check that ByRange does. Spec applies deprecation to BOTH. **Possible bug** — file PR to teku.
4. **Cross-network MAX_REQUEST_BLOB_SIDECARS_ELECTRA**: gnosis = 256 (teku/lighthouse confirmed); audit holesky/sepolia/hoodi for divergence.
5. **Hypothetical fork divergence test**: simulate fork increasing `MAX_BLOBS_PER_BLOCK_ELECTRA` to 18; verify teku + grandine auto-update; prysm + lighthouse + nimbus + lodestar require YAML bump.
6. **Pattern DD scope expansion**: scan spec for `def compute_*` in p2p-interface.md per fork; check if Pattern DD applies broadly.
7. **Protocol-deregistration audit**: does any client UNREGISTER `/eth2/beacon_chain/req/blob_sidecars_by_range/1/` post-deprecation-cutoff? Spec is silent. Today is 4.5 months past cutoff.
8. **Cross-client interop test at deprecation boundary**: peer requests slot range crossing FULU_FORK_EPOCH; verify all 6 return identical (empty + serve pre-Fulu portion).
9. **Grandine 1536 origin investigation**: why 1536 (= 128 × 12)? Likely earlier `MAX_BLOBS_PER_BLOCK_FULU = 12` design before BPO landed. Verify via grandine git history.
10. **Heritage-RPC catalogue**: which other RPCs are deprecated at Fulu? Status v1, MetaData v2, BeaconBlocksByRange v2, BeaconBlocksByRoot v2 may all be deprecated incrementally — audit at item #51+ candidate.
11. **gossip topic deprecation parallel**: `blob_sidecar_{subnet_id}` topic should be similarly deprecated at Fulu; cross-client deprecation handling for gossip topics may diverge similarly.

## Summary

Spec Electra-modified `compute_max_request_blob_sidecars()` returns `MAX_REQUEST_BLOCKS_DENEB × MAX_BLOBS_PER_BLOCK_ELECTRA = 128 × 9 = 1152` mainnet. Sister to item #49's `MAX_REQUEST_DATA_COLUMN_SIDECARS`. **All 6 clients evaluate to identical 1152**.

**Pattern DD (item #49) extends here** — same 4-2 split: HARDCODED YAML (prysm, lighthouse, nimbus, lodestar) vs COMPUTED formula (teku, grandine). Teku consistently uses HYBRID pattern (computed default + YAML override) across both `MAX_REQUEST_DATA_COLUMN_SIDECARS` AND `MAX_REQUEST_BLOB_SIDECARS_ELECTRA`. Grandine consistently uses phase-parameterized formula via `saturating_mul`.

**NEW Pattern EE candidate for item #28**: deprecated-RPC handling at fork transition. **Only teku** has explicit `blobSidecarsDeprecationSlot()` check at `BlobSidecarsByRangeMessageHandler.java:107-109/126-133`. Other 5 rely on implicit storage-returns-empty. Same observable result today, different implementation defensive-ness. Spec MAY clause makes this currently spec-compliant either way.

**NEW Pattern FF candidate for item #28**: vestigial config fields. **Grandine** has `max_request_blob_sidecars_fulu: 1536` declared at `config.rs:175/300` but **NOT USED** anywhere — active selector at `:1005` computes formula instead. Suggests aborted Fulu cap design (1536 = 128 × 12, midpoint of BPO range).

**Teku internal inconsistency**: `BlobSidecarsByRootMessageHandler.java` does NOT have the same deprecation check that ByRange does. Spec applies deprecation to BOTH RPCs equally. Possible bug-fix opportunity for teku.

**Mainnet timeline**:
- Fulu activated 2025-12-03 (FULU_FORK_EPOCH = 411392)
- Deprecation cutoff was epoch 415488 (~2025-12-21, 18.21 days post-Fulu)
- **Today is 4.5 months past cutoff** — RPC effectively dead
- ZERO clients unregister the protocol post-cutoff
- All 6 return empty for all queries (storage pruned at retention window)

**Live mainnet validation**: 5+ months of cross-client peer interop with no observed divergence on this RPC family. Cap divergence (1152 vs 1536) is moot in practice because grandine never uses 1536 and no client serves blob sidecars anymore.

**With this audit, the BlobSidecars deprecated-RPC family is closed**. Heritage-RPC deprecation tracking begins here — future audits should cover other Fulu-deprecated RPCs (Status v1, MetaData v2, etc.).

**Total Fulu-NEW-relevant items: 20 (#30–#50)**. Item #28 catalogue **Patterns A–FF (32 patterns)**.
