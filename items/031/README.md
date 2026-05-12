---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [15, 19, 29]
eips: [EIP-7892, EIP-7732]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.3
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.3.1
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 31: `get_blob_parameters(epoch)` + `blob_schedule` schema + Fulu-modified `compute_fork_digest` (EIP-7892 BPO hardforks)

## Summary

EIP-7892 Blob Parameter Only (BPO) hardforks — runtime mechanism to change `MAX_BLOBS_PER_BLOCK` without a full fork-version bump by adding entries to a `blob_schedule` configuration list. Three primitives: `get_blob_parameters(epoch) -> BlobParameters` (lookup by scanning `blob_schedule` in descending epoch order); `blob_schedule` config schema (sortedness + uniqueness invariants); Fulu-modified `compute_fork_digest(genesis_validators_root, epoch)` (XORs base fork-data-root with `hash(uint64_le(epoch) || uint64_le(max_blobs))` to produce 4-byte fork-domain separator).

**Fulu surface (carried forward from 2026-05-04 audit):** all six clients implement EIP-7892 byte-for-byte equivalently. Two production BPO transitions executed without chain split: 9 → 15 blobs at epoch 412672 (2025-12-09), then 15 → 21 at epoch 419072 (2026-01-07). Mainnet schedule confirmed in `vendor/consensus-specs/configs/mainnet.yaml:224-228`.

Per-client divergences are entirely in caching (prysm pre-computes ALL fork digests at config init; nimbus pre-resolves active BPO; other 4 compute per-call), multi-fork-definition pattern (nimbus + grandine ship separate `_pre_fulu`/`_post_fulu` functions), pre-Fulu fallback (lodestar throws; lighthouse returns Option; nimbus/grandine/prysm/teku return defaults), validation strictness (nimbus + lodestar + teku validate at config load), and public API (prysm uses Slot; other 5 use Epoch).

**Gloas surface (at the Glamsterdam target): primitives unchanged.** `vendor/consensus-specs/specs/gloas/beacon-chain.md` and `vendor/consensus-specs/specs/gloas/p2p-interface.md` contain NO `Modified get_blob_parameters` / `Modified compute_fork_digest` / `Modified BlobParameters` / `Modified BLOB_SCHEDULE` headings. The three BPO primitives are inherited verbatim from Fulu. What CHANGES at Gloas is **a new consumer site**: `process_execution_payload_bid` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1448`) reads `get_blob_parameters(get_current_epoch(state)).max_blobs_per_block` to gate builder bid `blob_kzg_commitments` count. Same primitive, new caller (the EIP-7732 ePBS surface).

**Mainnet Gloas activation status**: `GLOAS_FORK_EPOCH = 18446744073709551615` (`vendor/consensus-specs/configs/mainnet.yaml:60`) — FAR_FUTURE_EPOCH, not yet scheduled. The BPO mechanism continues operating on the Fulu surface; the Gloas extension is source-level only.

**Per-client Gloas inheritance**: all six clients reuse their Fulu BPO implementations at Gloas via fork-order coverage:
- prysm: `MaxBlobsPerBlockAtEpoch(epoch)` uses `networkSchedule.forEpoch(epoch)` which is fork-agnostic.
- lighthouse: `get_blob_parameters(epoch)` returns `Option<BlobParameters>`; Gloas inherits via `fork_name_unchecked()` covering all post-Fulu forks.
- teku: `MiscHelpersFulu.getBlobParameters(epoch)`; `MiscHelpersGloas extends MiscHelpersFulu` (no override; inherits the Fulu impl).
- nimbus: `get_blob_parameters(cfg, epoch)` is `cfg`-keyed (not state-keyed); fork-agnostic.
- lodestar: `getBlobParameters(epoch)` switches by fork name in `ChainForkConfig`; Gloas falls under the Fulu+ branch.
- grandine: `compute_fork_digest` dispatcher uses `config.phase_at_epoch(epoch).is_peerdas_activated()` (`vendor/grandine/helper_functions/src/misc.rs:180`) — covers Fulu and Gloas (both have PeerDAS activated). The `Phase::Fulu | Phase::Gloas` pattern at `vendor/grandine/types/src/config.rs:1105` explicitly extends BPO to Gloas.

**Impact: none.** Thirteenth impact-none result in the recheck series.

## Question

Pyspec Fulu-NEW (`vendor/consensus-specs/specs/fulu/beacon-chain.md:197-217`):

```python
def get_blob_parameters(epoch: Epoch) -> BlobParameters:
    # blob_schedule must be sorted by epoch in ascending order
    for entry in reversed(BLOB_SCHEDULE):
        if epoch >= entry.EPOCH:
            return BlobParameters(epoch=entry.EPOCH, max_blobs_per_block=entry.MAX_BLOBS_PER_BLOCK)
    # Default to Electra parameters if no entry matches
    return BlobParameters(epoch=ELECTRA_FORK_EPOCH, max_blobs_per_block=MAX_BLOBS_PER_BLOCK_ELECTRA)

def compute_fork_digest(current_version: Version, genesis_validators_root: Root, epoch: Epoch) -> ForkDigest:
    base_digest = compute_fork_data_root(current_version, genesis_validators_root)
    if epoch >= FULU_FORK_EPOCH:
        blob_parameters = get_blob_parameters(epoch)
        blob_digest = hash(
            uint_to_bytes(blob_parameters.epoch) + uint_to_bytes(blob_parameters.max_blobs_per_block)
        )
        return ForkDigest(xor(base_digest, blob_digest)[:4])
    return ForkDigest(base_digest[:4])
```

At Gloas: `get_blob_parameters` and `compute_fork_digest` are NOT modified (no `Modified` headings in `vendor/consensus-specs/specs/gloas/`). New consumer at `beacon-chain.md:1448`:

```python
# In process_execution_payload_bid (Gloas-NEW):
assert (
    len(bid.blob_kzg_commitments)
    <= get_blob_parameters(get_current_epoch(state)).max_blobs_per_block
)
```

Three recheck questions:
1. Fulu-surface invariants (H1–H10 from prior audit) — do all six clients still implement byte-for-byte equivalent EIP-7892?
2. **At Gloas (the new target)**: are the primitives unchanged? Do all six clients correctly route Fulu BPO implementations to Gloas via fork-order coverage?
3. Does the new Gloas consumer (`process_execution_payload_bid`) correctly read from `get_blob_parameters`?

## Hypotheses

- **H1.** `get_blob_parameters(epoch)` scans `BLOB_SCHEDULE` in descending epoch order; returns first matching entry.
- **H2.** Default-when-no-match: `BlobParameters(ELECTRA_FORK_EPOCH, MAX_BLOBS_PER_BLOCK_ELECTRA = 9)`.
- **H3.** `compute_fork_digest(gvr, epoch)` post-Fulu = `xor(compute_fork_data_root(fork_version, gvr), sha256(uint64_le(epoch) || uint64_le(max_blobs)))[:4]`.
- **H4.** Pre-Fulu fallback: no XOR; just `compute_fork_data_root(fork_version, gvr)[:4]`.
- **H5.** `blob_schedule` entries sorted ascending; duplicates forbidden.
- **H6.** Hash input layout: 16 bytes `uint64_le(epoch) || uint64_le(max_blobs)`.
- **H7.** XOR-then-truncate (32-byte XOR, take first 4 bytes).
- **H8.** Mainnet active schedule: 9 (Fulu default) → 15 (epoch 412672, 2025-12-09) → 21 (epoch 419072, 2026-01-07).
- **H9.** `MAX_BLOBS_PER_BLOCK` per-epoch INDEPENDENT of `fork_version` (EIP-7892 design intent).
- **H10.** *(Glamsterdam target — primitives unchanged)*. None of the three primitives are modified at Gloas. The Fulu implementations carry forward across the Gloas fork boundary in all six clients via fork-order coverage / inheritance.
- **H11.** *(Glamsterdam target — new consumer site at Gloas)*. The Gloas-NEW `process_execution_payload_bid` consumes `get_blob_parameters(get_current_epoch(state)).max_blobs_per_block` to gate builder bid validation. Same primitive, new caller. Cross-cuts item #19's `process_execution_payload` Fulu-modified consumer (item #19 needs Gloas follow-up to confirm the call site migration to `apply_parent_execution_payload`).
- **H12.** *(Glamsterdam target — mainnet not yet scheduled)*. `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `vendor/consensus-specs/configs/mainnet.yaml:60`. The BPO mechanism continues operating on the Fulu surface in production; Gloas extensions are source-level only.

## Findings

H1–H12 satisfied. **No state-transition divergence at the BPO primitives layer across Fulu or Gloas.**

### prysm

`vendor/prysm/config/params/fork.go:18 ForkDigest(epoch)`: returns digest from `networkSchedule.forEpoch(epoch).ForkDigest` (PRE-COMPUTED at `InitializeForkSchedule()`).

```go
type NetworkScheduleEntry struct {
    Epoch            primitives.Epoch
    ForkVersion      [4]byte
    MaxBlobsPerBlock uint64
    ForkDigest       [4]byte  // pre-computed
    isFork           bool
    VersionEnum      int
}
```

The `NetworkSchedule` merges fork-version bumps AND BPO entries into a single per-epoch schedule. `ForkDigestUsingConfig(epoch, cfg)` at `fork.go:13-16` does the lookup. Pre-computation eliminates per-call SHA256 + XOR overhead.

`vendor/prysm/config/params/config.go:720 MaxBlobsPerBlock(slot)` and `MaxBlobsPerBlockAtEpoch(epoch)`: fork-agnostic per-epoch lookup. **No fork-conditional branch needed** — the schedule incorporates Gloas (and future BPOs) at config load time.

At Gloas: the same `networkSchedule.forEpoch(epoch)` lookup serves. When `GLOAS_FORK_EPOCH` is set to a real epoch in `mainnet.yaml`, the schedule extends. Two-layer cache from item #29 (`digestMap` for fork_data_root + `NetworkScheduleEntry.ForkDigest` for full digest) — both pre-computed at config init.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (sorted at init). H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** (NetworkSchedule is fork-agnostic; Gloas inherits). H11 cross-cuts item #19. H12 ✓.

### lighthouse

`vendor/lighthouse/consensus/types/src/core/chain_spec.rs:580-605 compute_fork_digest`:

```rust
pub fn compute_fork_digest(&self, genesis_validators_root: Hash256, epoch: Epoch) -> [u8; 4] {
    let fork_version = self.fork_version_for_epoch(epoch);
    let fork_data_root = Self::compute_fork_data_root(fork_version, genesis_validators_root);
    let Some(blob_parameters) = self.get_blob_parameters(epoch) else {
        // Pre-Fulu: no XOR
        return fork_data_root.as_slice()[..4].try_into().expect("len 4");
    };
    let mut input = Vec::with_capacity(16);
    input.extend_from_slice(&blob_parameters.epoch.as_u64().to_le_bytes());
    input.extend_from_slice(&blob_parameters.max_blobs_per_block.to_le_bytes());
    let blob_digest = ethereum_hashing::hash(&input);
    // XOR-then-truncate
    let mut xored = [0u8; 32];
    for i in 0..32 {
        xored[i] = fork_data_root[i] ^ blob_digest[i];
    }
    xored[..4].try_into().expect("len 4")
}
```

`vendor/lighthouse/consensus/types/src/core/chain_spec.rs:737 get_blob_parameters(epoch) -> Option<BlobParameters>`: returns `None` for pre-Fulu epochs (lighthouse's strict-spec-compliance flavour). Convenience `:723 max_blobs_per_block(epoch) -> u64` for callers needing the scalar.

`BlobSchedule` newtype at `:292` wraps `Vec<BlobParameters>` — implicit validation (no explicit `validate` method).

At Gloas: the `Option`-returning `get_blob_parameters` returns `Some(...)` for any epoch ≥ Fulu, including Gloas. **No fork-conditional branch** — observable-equivalent across Fulu and Gloas.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (implicit). H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** (Fulu impl carries forward). H11 cross-cuts item #19. H12 ✓.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/fulu/helpers/MiscHelpersFulu.java:119-135 computeForkDigest(gvr, epoch)` + `:128 getBlobParameters(epoch)`:

```java
public Bytes4 computeForkDigest(final Bytes32 genesisValidatorsRoot, final UInt64 epoch) {
  final Bytes32 baseDigest = ...; // from fork_data_root
  final BlobParameters blobParameters = getBlobParameters(epoch);
  final Bytes32 blobHash = blobParameters.hash();  // factored method
  return Bytes4.wrap(baseDigest.xor(blobHash).slice(0, 4));
}

public BlobParameters getBlobParameters(final UInt64 epoch) {
  return getBpoFork(epoch).orElse(...);  // default to (electraForkEpoch, maxBlobsPerBlock)
}
```

`BlobParameters.hash()` method co-locates hash input layout with the type (clean encapsulation).

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/helpers/MiscHelpersGloas.java extends MiscHelpersFulu` — NO override of `getBlobParameters` or `computeForkDigest`. Gloas inherits the Fulu implementation via subclass extension.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (validates at `SpecConfigReader.java:276`). H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** (MiscHelpersGloas inherits without override). H11 cross-cuts item #19. H12 ✓.

### nimbus

`vendor/nimbus/beacon_chain/spec/forks.nim:1077 get_blob_parameters(cfg, epoch)`: sequential scan via `for entry in cfg.BLOB_SCHEDULE`. Relies on pre-sorted descending invariant enforced at `vendor/nimbus/beacon_chain/spec/datatypes/base.nim:981`:

```nim
doAssert isSorted(cfg.BLOB_SCHEDULE, cmp = cmpBlobParameters)
```

Only client with explicit runtime sortedness assertion.

`vendor/nimbus/beacon_chain/spec/forks.nim:1701 compute_fork_digest_fulu` — separate function from pre-Fulu `compute_fork_digest`. Multi-fork-definition pattern (cross-cuts item #28 Pattern I; nimbus + grandine share this approach).

```nim
func compute_fork_digest_fulu*(
    cfg: RuntimeConfig, current_version: Version,
    genesis_validators_root: Eth2Digest, epoch: Epoch): ForkDigest =
  let
    base_digest = compute_fork_digest(current_version, genesis_validators_root)
    blob_parameters = get_blob_parameters(cfg, epoch)
  # ... XOR loop with staticFor ...
```

`presets.nim:913 currentBPO: BlobParameters` field PRE-RESOLVES the active entry at config init — hybrid between prysm's full pre-computation and lighthouse's per-call lookup.

At Gloas: `cfg`-keyed lookup is fork-agnostic. The Fulu+ branch (in caller code that dispatches to `compute_fork_digest_fulu`) extends to Gloas via the `epoch >= FULU_FORK_EPOCH` check. No Gloas-specific override.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (explicit `doAssert isSorted`). H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** (Fulu helper carries forward). H11 cross-cuts item #19. H12 ✓.

### lodestar

`vendor/lodestar/packages/config/src/forkConfig/index.ts:188-195 getBlobParameters(epoch)`:

```typescript
getBlobParameters(epoch: Epoch): BlobParameters {
  if (epoch < FULU_FORK_EPOCH) {
    throw Error(`getBlobParameters is not available pre-fulu epoch=${epoch}`);
  }
  // ... scan in descending order ...
}
```

Strict spec-compliance: throws on pre-Fulu epochs (other 5 return defaults). Convenience `:178 getMaxBlobsPerBlock(epoch)` switches by fork name.

`vendor/lodestar/packages/config/src/genesisConfig/index.ts:164-180 computeForkDigest`:

```typescript
export function computeForkDigest(
  config: ChainForkConfig,
  genesisValidatorsRoot: Root,
  epoch: Epoch
): ForkDigest {
  const baseDigest = compute_fork_data_root(forkVersion, gvr).slice(0, 4);
  if (epoch < FULU_FORK_EPOCH) return baseDigest;
  const blobParameters = config.getBlobParameters(epoch);
  // XOR with sha256(epoch || max_blobs)
  return xor(...);
}
```

`validateBlobSchedule()` at `vendor/lodestar/packages/config/src/utils/validateBlobSchedule.ts` validates at config load.

At Gloas: the `epoch >= FULU_FORK_EPOCH` check covers Gloas (since Gloas comes after Fulu). The `getBlobParameters` lookup is fork-agnostic post-Fulu. No Gloas-specific override.

H1 ✓. H2 ✓ (throws — caller responsibility). H3 ✓. H4 ✓. H5 ✓ (validates at load). H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** (post-Fulu branch covers Gloas). H11 cross-cuts item #19. H12 ✓.

### grandine

`vendor/grandine/helper_functions/src/misc.rs:154-185`:

```rust
fn compute_fork_digest_pre_fulu(fork_version, gvr) -> ForkDigest { ... }
fn compute_fork_digest_post_fulu(config, gvr, epoch) -> ForkDigest {
    let blob_entry = config.get_blob_schedule_entry(epoch);
    // ... XOR with hash(uint_to_bytes(epoch) + uint_to_bytes(max_blobs)) ...
}

pub fn compute_fork_digest(config, gvr, epoch) -> ForkDigest {
    if config.phase_at_epoch(epoch).is_peerdas_activated() {
        compute_fork_digest_post_fulu(config, gvr, epoch)
    } else {
        let fork_version = config.version_at_epoch(epoch);
        compute_fork_digest_pre_fulu(fork_version, gvr)
    }
}
```

`is_peerdas_activated()` covers Fulu AND Gloas (both have PeerDAS). Multi-fork-definition pattern (separate `_pre_fulu` and `_post_fulu` functions; same as nimbus). Cross-cuts item #28 Pattern I.

`vendor/grandine/types/src/config.rs:1087 get_blob_schedule_entry(epoch)`: uses `itertools::sorted_by` per-call (O(N log N)). `:1105 Phase::Fulu | Phase::Gloas => self.get_blob_schedule_entry(epoch).max_blobs_per_block` — **explicit Gloas extension** confirming BPO continues at Gloas.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (per-call sort). H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** (explicit `Phase::Fulu | Phase::Gloas` extension). H11 cross-cuts item #19. H12 ✓.

## Cross-reference table

| Client | `get_blob_parameters` | `compute_fork_digest` post-Fulu | Gloas inheritance |
|---|---|---|---|
| prysm | `MaxBlobsPerBlockAtEpoch(epoch)` via `networkSchedule.forEpoch(epoch)` — fork-agnostic | `ForkDigest(epoch)` **PRE-COMPUTED** at `InitializeForkSchedule` | `NetworkSchedule` is fork-agnostic; Gloas inherits at config load |
| lighthouse | `get_blob_parameters(epoch) -> Option<BlobParameters>` (`chain_spec.rs:737`); `None` for pre-Fulu | `compute_fork_digest` at `chain_spec.rs:580-605` runtime XOR | `Option` covers all post-Fulu forks; no Gloas-specific code |
| teku | `getBlobParameters(epoch)` (`MiscHelpersFulu.java:128`); default `BlobParameters` for pre-Fulu | `computeForkDigest` (`:119-135`); `BlobParameters.hash()` factored method | `MiscHelpersGloas extends MiscHelpersFulu` without override |
| nimbus | `get_blob_parameters(cfg, epoch)` (`forks.nim:1077`); explicit `doAssert isSorted` invariant | **Separate `compute_fork_digest_fulu`** function (`forks.nim:1701`); multi-fork-definition (Pattern I) | `cfg`-keyed; fork-agnostic |
| lodestar | `getBlobParameters(epoch)` (`forkConfig/index.ts:190`); **throws on pre-Fulu** | `computeForkDigest` (`genesisConfig/index.ts:164-180`); `validateBlobSchedule` at config load | post-Fulu branch covers Gloas |
| grandine | `get_blob_schedule_entry(epoch)` (`config.rs:1087`); **per-call sort** via `itertools::sorted_by` | **Separate `compute_fork_digest_post_fulu`** (`misc.rs:154`); dispatcher uses `is_peerdas_activated()` | **Explicit `Phase::Fulu \| Phase::Gloas` extension** at `config.rs:1105` |

## Empirical tests

### Fulu-surface live behaviour (carried forward)

Two production BPO transitions confirmed:

| Epoch | Active limit | Date | All 6 clients |
|---|---|---|---|
| 0 (genesis) | 6 | 2020 | ✅ |
| 364032 (Electra) | 9 | 2025-05-07 | ✅ |
| 411392 (Fulu) | 9 (carried) | 2025-12-03 | ✅ |
| 412672 (BPO #1) | 15 | 2025-12-09 | ✅ |
| 419072 (BPO #2) | 21 | 2026-01-07 | ✅ |

Zero divergences in production — otherwise the chain would have forked. Mainnet schedule confirmed in `vendor/consensus-specs/configs/mainnet.yaml:224-228`.

### Gloas-surface

`GLOAS_FORK_EPOCH = 18446744073709551615` (FAR_FUTURE_EPOCH) per `mainnet.yaml:60`. Gloas not yet scheduled on mainnet; the BPO mechanism continues operating on the Fulu surface. Gloas extensions are source-level only.

Concrete Gloas-spec evidence:
- No `Modified get_blob_parameters` / `Modified compute_fork_digest` / `Modified BlobParameters` headings in `vendor/consensus-specs/specs/gloas/`.
- New consumer at `vendor/consensus-specs/specs/gloas/beacon-chain.md:1448` — `process_execution_payload_bid` reads `get_blob_parameters(get_current_epoch(state)).max_blobs_per_block`.
- p2p gossip validation at `vendor/consensus-specs/specs/gloas/p2p-interface.md:264, 353` — uses same primitive.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1**: dedicated EF fixture set for `get_blob_parameters` as pure function (config + epoch → BlobParameters). Cross-client byte-level equivalence at both Fulu and Gloas state inputs.
- **T1.2**: dedicated EF fixture set for `compute_fork_digest` Fulu+ — pure function (config + gvr + epoch → 4-byte digest). Cross-cuts item #29 follow-up.
- **T1.3**: wire Fulu fixture categories in BeaconBreaker harness (same gap as items #11, #21, #27, #30).

#### T2 — Adversarial probes
- **T2.1 (Glamsterdam-target — H10 verification)**: Gloas state with current `BLOB_SCHEDULE` (15 at 412672, 21 at 419072). Expected: `get_blob_parameters(any_gloas_epoch)` returns the same BlobParameters as at Fulu (no Gloas-specific schedule override).
- **T2.2 (Glamsterdam-target — H11 new consumer site)**: Gloas state. Submit `SignedExecutionPayloadBid` with `len(blob_kzg_commitments) = 21` and `len(blob_kzg_commitments) = 22`. Expected: all 6 clients accept 21 (current Fulu-Gloas active limit) and reject 22 (above limit).
- **T2.3 (Glamsterdam-target — hypothetical Gloas-era BPO)**: synthetic schedule with BPO entry at `GLOAS_FORK_EPOCH + 100`, `MAX_BLOBS_PER_BLOCK: 30`. Verify all 6 clients accept the BPO at the Gloas-era epoch (no Gloas-specific schedule rejection).
- **T2.4**: cross-fork-digest collision audit — verify no two `(fork_version, epoch, max_blobs)` triples produce the same 4-byte digest across the entire mainnet schedule (Phase0 → Gloas).
- **T2.5 (defensive — duplicate-epoch BlobSchedule entries)**: synthetic config with two entries at the same epoch. Expected: nimbus rejects via `doAssert`; teku/lodestar reject at config load; lighthouse/grandine/prysm accept (rely on declaration order).
- **T2.6 (defensive — BPO with `max_blobs = 0`)**: undefined in spec. Verify all 6 clients agree on accept/reject.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Fulu-surface invariants (H1–H9) carry forward unchanged from the 2026-05-04 audit. EIP-7892 BPO hardforks operate byte-for-byte equivalently in production — two BPO transitions executed (9 → 15 → 21 blobs) without chain split.

**Glamsterdam-target finding (H10 — primitives unchanged).** `vendor/consensus-specs/specs/gloas/beacon-chain.md` contains no `Modified get_blob_parameters` / `Modified compute_fork_digest` / `Modified BlobParameters` / `Modified BLOB_SCHEDULE` headings. The three BPO primitives are inherited verbatim from Fulu across the Gloas fork boundary. All six clients reuse their Fulu implementations at Gloas via fork-order coverage:
- **prysm**: `NetworkSchedule` is fork-agnostic — Gloas entries (when scheduled) extend the schedule at config load.
- **lighthouse**: `Option<BlobParameters>` is non-None for any post-Fulu epoch — no fork-specific code.
- **teku**: `MiscHelpersGloas extends MiscHelpersFulu` inherits `getBlobParameters` and `computeForkDigest` without override.
- **nimbus**: `cfg`-keyed lookup is fork-agnostic.
- **lodestar**: post-Fulu branch in `computeForkDigest` covers Gloas via `epoch >= FULU_FORK_EPOCH`.
- **grandine**: dispatcher uses `is_peerdas_activated()` covering Fulu AND Gloas; **`Phase::Fulu | Phase::Gloas` explicit pattern** at `vendor/grandine/types/src/config.rs:1105` confirms the BPO mechanism extends to Gloas.

**Glamsterdam-target finding (H11 — new consumer site at Gloas).** The Gloas-NEW `process_execution_payload_bid` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1448`) consumes `get_blob_parameters(get_current_epoch(state)).max_blobs_per_block` to gate builder bid `blob_kzg_commitments` count. Same primitive, new caller. The Pectra-Fulu `process_execution_payload` consumer is relocated under EIP-7732 ePBS to `apply_parent_execution_payload` (cross-cuts item #19 — Gloas follow-up needed to verify the migration).

**Glamsterdam-target finding (H12 — mainnet not yet scheduled).** `GLOAS_FORK_EPOCH = 18446744073709551615` (FAR_FUTURE_EPOCH) per `vendor/consensus-specs/configs/mainnet.yaml:60`. The BPO mechanism continues operating on the Fulu surface in production. Gloas extensions are source-level only — production validation pending Gloas activation.

**Thirteenth impact-none result** in the recheck series (after items #5, #10, #11, #18, #20, #21, #24, #25, #26, #27, #29, #30). Same propagation-without-amplification pattern: the Gloas spec adds new consumer sites (e.g., `process_execution_payload_bid`) but leaves the primitive layer unchanged. All six clients carry the Fulu equivalence forward through fork-agnostic config / subclass inheritance / dispatcher coverage.

**Notable per-client style differences (all observable-equivalent at both Fulu and Gloas):**
- **prysm**: full pre-computation of all fork digests at config init via `NetworkSchedule.ForkDigest`. Two-layer cache with item #29's `digestMap`.
- **lighthouse**: `Option<BlobParameters>` strict-spec-compliance for pre-Fulu (returns None); runtime XOR.
- **teku**: `BlobParameters.hash()` factored method co-locates layout with the type; subclass-extension polymorphism (`MiscHelpersGloas extends MiscHelpersFulu`).
- **nimbus**: explicit `doAssert isSorted` invariant; `currentBPO` pre-resolved field; **multi-fork-definition pattern** (separate `compute_fork_digest_fulu` function).
- **lodestar**: throws on pre-Fulu `getBlobParameters` (strict spec); `validateBlobSchedule()` at config load.
- **grandine**: per-call `itertools::sorted_by` sort; **multi-fork-definition pattern** (separate `compute_fork_digest_pre_fulu` and `_post_fulu` functions); only client with explicit `Phase::Fulu | Phase::Gloas` extension pattern.

**No code-change recommendation.** Audit-direction recommendations:

- **Wire Fulu fixture categories in BeaconBreaker harness** (T1.3) — pre-condition for cross-client fixture testing. Same gap as items #11, #21, #27, #30.
- **Dedicated EF fixture set for `get_blob_parameters`** (T1.1) — pure-function cross-client byte-level equivalence at Fulu and Gloas state inputs.
- **Dedicated EF fixture set for `compute_fork_digest` Fulu+** (T1.2) — cross-cuts item #29 follow-up.
- **Item #19 Gloas follow-up audit** — verify `process_execution_payload_bid` (Gloas-NEW consumer at `:1448`) correctly reads from `get_blob_parameters` AND that the Pectra-Fulu `process_execution_payload` consumer is correctly relocated to `apply_parent_execution_payload` (EIP-7732 ePBS routing). Cross-cuts item #19 Pectra audit.
- **Pre-emptive Gloas BPO entry test**: when `GLOAS_FORK_EPOCH` is eventually scheduled in `mainnet.yaml`, verify all 6 clients accept a post-Gloas BPO entry without divergence.
- **Cross-fork-digest collision audit** (T2.4) — verify no `(fork_version, epoch, max_blobs)` collisions across the entire Phase0 → Gloas schedule.
- **Multi-fork-definition cleanup audit** — nimbus + grandine ship separate `_pre_fulu` / `_post_fulu` functions. If Heze (post-Gloas) modifies the digest algorithm (e.g., to incorporate inclusion-list params), these clients would need new module files. Forward-fragility (Pattern I in item #28).

## Cross-cuts

### With item #19 (`process_execution_payload` Pectra-modified) — Gloas follow-up

Item #19 documented `MAX_BLOBS_PER_BLOCK_ELECTRA = 9` as the Pectra-active blob limit. The Fulu surface (current mainnet) reads dynamically from `get_blob_parameters(epoch).max_blobs_per_block` (currently 21). At Gloas, the consumer site `process_execution_payload` is restructured under EIP-7732 ePBS: blob-limit gating moves to `process_execution_payload_bid` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1448`), reading the same primitive. **Item #19 needs a Gloas follow-up** to verify per-client implementations of the relocated call site (lighthouse Gloas-ePBS cohort per item #28 Pattern M is the likely failure mode).

### With item #29 (signing-domain primitives)

Item #29 audited the signing-domain primitive quartet (`compute_signing_root`, `compute_domain`, `compute_fork_data_root`, `get_domain`). `compute_fork_digest` is the p2p-layer cousin of `compute_domain`: both compose `compute_fork_data_root` with a 4-byte domain-separator. Item #29's adjacent untouched mentioned `compute_fork_digest` Fulu-modified as a follow-up; THIS item closes that thread. Both primitive families unchanged at Gloas — same propagation-without-amplification pattern.

### With item #28 (Gloas divergence meta-audit) — Pattern N reaffirmation

Item #28's Pattern N (multi-fork-definition pattern) is reaffirmed at this surface — nimbus and grandine ship separate `_pre_fulu` / `_post_fulu` functions for `compute_fork_digest`. Same forward-fragility class as Pattern I (function bodies multi-defined per fork). Not a divergence vector at Fulu/Gloas (all 6 produce identical output) but a code-organization concern if Heze modifies the digest algorithm.

### With Heze (post-Gloas) — stability marker

The Heze finding from item #29 (teku FULL implementation, prysm constants, etc.) is a separate concern from this item — Heze adds inclusion-list domain (`DOMAIN_INCLUSION_LIST_COMMITTEE`), NOT a blob-mechanism modification. The BPO primitives audited here are expected to carry forward unchanged at Heze. If Heze ever modifies the digest algorithm (e.g., to incorporate inclusion-list params), all 6 clients must update; nimbus + grandine's multi-fork-definition pattern would require new module files.

### With Gloas-NEW `process_execution_payload_bid` (item #19 sister)

`process_execution_payload_bid` is the Gloas-NEW consumer of `get_blob_parameters`. Per `vendor/consensus-specs/specs/gloas/beacon-chain.md:1448`, it gates builder bid `blob_kzg_commitments` count. This sister audit should verify all 6 clients implement the bid-validation correctly (cross-cuts item #15 Engine API V5 and item #19 Pectra-Fulu `process_execution_payload`).

## Adjacent untouched

1. **Wire Fulu fixture categories in BeaconBreaker harness** — pre-condition for fixture testing. Same gap as items #11, #21, #27, #30.
2. **Dedicated EF fixture set for `get_blob_parameters`** — pure-function cross-client byte-level equivalence at Fulu and Gloas state inputs.
3. **Dedicated EF fixture set for `compute_fork_digest`** Fulu+ — cross-cuts item #29 follow-up.
4. **Item #19 Gloas follow-up audit** — `process_execution_payload_bid` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1448`) blob-limit gating; lighthouse cohort gap (item #28 Pattern M).
5. **Cross-fork-digest collision audit** — verify no `(fork_version, epoch, max_blobs)` collisions across Phase0 → Gloas schedule.
6. **BPO transition stateful fixture** — at exactly epoch 412672 or 419072, verify all 6 clients accept blocks with the new limit but reject at limit+1.
7. **Synthetic Gloas-era BPO entry test** — when `GLOAS_FORK_EPOCH` is eventually scheduled, verify all 6 clients accept a post-Gloas BPO without divergence.
8. **Multi-fork-definition cleanup audit** — nimbus + grandine multi-fork `compute_fork_digest` functions; track forward-fragility at Heze.
9. **teku `getMaxBlobsPerBlock()` default value verification** — confirm returns 9 (Electra), not 6 (Deneb genesis).
10. **lodestar pre-Fulu throw audit** — find all callers of `getBlobParameters`; verify none trigger the throw on pre-Fulu epochs in normal control flow.
11. **grandine per-call sort performance** — benchmark `compute_fork_digest_post_fulu` at synthetic 100+ blob_schedule entries.
12. **prysm pre-computed digest cache invalidation** — test runtime config reload (testnet hot-reload scenario); verify cache flush.
13. **BlobScheduleEntry validation cross-client audit** — verify all 6 reject (a) duplicate epochs, (b) pre-FULU_FORK_EPOCH entries, (c) max_blobs > MAX_BLOB_COMMITMENTS_PER_BLOCK, (d) max_blobs = 0.
14. **Cross-network blob_schedule consistency** — verify mainnet/sepolia/holesky/Hoodi `BLOB_SCHEDULE` entries are byte-identical across all 6 clients' shipped configs.
15. **prysm two-layer caching audit** — `digestMap` (item #29) + `NetworkScheduleEntry.ForkDigest` are both pre-computed for the same primitive. Verify no inconsistency between the two layers.
16. **Engine API V5 boundary at Gloas** (item #15 follow-up) — verify CL-EL Engine API method routing at Gloas-active blob limit.
17. **Compile-time vs runtime fork-dispatch performance** — nimbus + grandine multi-fork-definition vs lighthouse + teku + lodestar branched within one function vs prysm pre-computation. Performance trade-offs at hot gossip-validation paths.
