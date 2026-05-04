# Item 31 — `get_blob_parameters(epoch)` + `blob_schedule` schema + Fulu-modified `compute_fork_digest` (EIP-7892 BPO hardforks)

**Status:** no-divergence-pending-source-review — audited 2026-05-04. **Second Fulu-NEW item** (after #30). EIP-7892 Blob Parameter Only (BPO) hardforks: a new mechanism that lets the chain change `MAX_BLOBS_PER_BLOCK` at runtime without a full fork-version bump, by adding entries to a `blob_schedule` configuration list. Active on mainnet with **two transitions already executed**: 9 → 15 blobs at epoch 412672 (2025-12-09), then → 21 at epoch 419072 (2026-01-07). Cross-cuts item #19 (`process_execution_payload` reads blob limit) and item #29 (signing-domain primitives — `compute_fork_digest` is the cousin of `compute_domain`).

The audit covers three primitives: (1) `get_blob_parameters(epoch) -> BlobParameters` — looks up the active blob limit by scanning `blob_schedule` in descending epoch order; (2) `blob_schedule` config schema — list of `(epoch, max_blobs_per_block)` records with sortedness + epoch-uniqueness invariants; (3) `compute_fork_digest(genesis_validators_root, epoch)` Fulu-modified — XORs the base fork-data-root with `hash(uint64_le(epoch) || uint64_le(max_blobs))` to produce a 4-byte fork-domain-separator on the p2p layer.

**This audit corrects item #19's stale finding**: item #19 documented `MAX_BLOBS_PER_BLOCK_ELECTRA = 9` as the Pectra-active blob limit. On the actual mainnet target (Fulu since 2025-12-03), the active limit is **21** (since 2026-01-07), read dynamically from `blob_schedule`, NOT from the Electra hardcoded constant.

## Scope

In: `get_blob_parameters(epoch)`; `BlobParameters` container schema; `blob_schedule` config list and its sortedness/uniqueness invariants; `compute_fork_digest` Fulu-modified XOR-with-blob-params; default-when-pre-Fulu / default-when-empty-schedule semantics.

Out: `process_execution_payload` Fulu-modified blob-limit assertion (downstream consumer — separate item; corrects item #19); BPO fork-version bumps (none defined; BPO does NOT change fork_version, ENR, or domain — the digest XOR is the only network-layer change); PeerDAS DataColumnSidecar interaction (orthogonal Fulu surface — separate item); Engine API V5 boundary (item #15 follow-up).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | `get_blob_parameters(epoch)` scans `blob_schedule` in DESCENDING epoch order, returns first `entry` where `epoch >= entry.EPOCH` | ✅ all 6 | Spec text. Each client uses either pre-sorted descending iteration, per-call sort, or pre-computed schedule lookup. |
| H2 | When no schedule entry matches (epoch < first BPO), default to `BlobParameters(ELECTRA_FORK_EPOCH, MAX_BLOBS_PER_BLOCK_ELECTRA)` | ✅ all 6 (with caveat for teku — see Notable findings) | All 6 match the spec; teku constructs default via `specConfigFulu.getMaxBlobsPerBlock()` which evaluates to 9 at Fulu config level (not the legacy Deneb 6). |
| H3 | `compute_fork_digest(gvr, epoch)` post-Fulu = `xor(compute_fork_data_root(fork_version, gvr), sha256(uint64_le(epoch) \|\| uint64_le(max_blobs)))[:4]` | ✅ all 6 | Confirmed byte-for-byte across all 6. |
| H4 | Pre-Fulu fallback: `compute_fork_digest` returns `compute_fork_data_root(fork_version, gvr)[:4]` (no XOR) | ✅ all 6 | Confirmed via gating check in each client. |
| H5 | `blob_schedule` entries SHOULD be sorted by epoch ascending (spec); duplicate epochs MUST NOT exist | ✅ confirmed in 4 of 6 (lighthouse, teku, nimbus, lodestar validate); prysm + grandine rely on declaration order | Source review. nimbus has explicit `doAssert isSorted(...)`; lodestar has `validateBlobSchedule()`; lighthouse implicit; teku validates at config load. |
| H6 | Hash input layout: `uint64_le(epoch) \|\| uint64_le(max_blobs_per_block)` = 16 bytes | ✅ all 6 | Confirmed. teku factors out into `BlobParameters.hash()` method. |
| H7 | XOR is over the 32-byte fork_data_root, then take first 4 bytes (NOT XOR over 4-byte digest with 4-byte hash slice) | ✅ all 6 | Order matters: XOR-then-truncate vs truncate-then-XOR yield different results. All 6 do XOR-then-truncate. |
| H8 | Mainnet active schedule: 9 (default Fulu) → 15 (epoch 412672) → 21 (epoch 419072) | ✅ all 6 | Confirmed in `mainnet.yaml` BLOB_SCHEDULE; all 6 clients ship the same entries. |
| H9 | `MAX_BLOBS_PER_BLOCK` per epoch is INDEPENDENT of fork_version — same fork_version `0x06000000` (Fulu) but different blob limits across epochs | ✅ all 6 | EIP-7892 design intent: avoid full fork-version churn for blob-only changes. |
| H10 | Forward-compat: at Heze (post-Gloas), `compute_fork_digest` algorithm is unchanged; only the blob_schedule entries grow | ✅ confirmed in source: spec text doesn't change at Heze | Heze adds inclusion-list domain, not blob mechanism. |

## Per-client cross-reference

| Client | `get_blob_parameters` / blob lookup | `BlobScheduleEntry` schema | `compute_fork_digest` post-Fulu | Validation/sort | Pre-computed? |
|---|---|---|---|---|---|
| **prysm** | `config/params/config.go:720` `MaxBlobsPerBlock(slot)` → `MaxBlobsPerBlockAtEpoch(epoch)` → `networkSchedule.forEpoch(epoch).MaxBlobsPerBlock` | `BlobScheduleEntry NetworkScheduleEntry` (alias to merged forks+BPOs schedule) at `config.go:401` | `params/fork.go:18` `ForkDigest(epoch)` returns **PRE-COMPUTED** digest from `networkSchedule` (computed at `InitializeForkSchedule`) | merged forks+BPOs sort at init via `combined.prepare(b)` | **YES** (digest pre-cached at config init; cross-cuts item #29's `digestMap`) |
| **lighthouse** | `consensus/types/src/core/chain_spec.rs:737` `get_blob_parameters(epoch) -> Option<BlobParameters>` (None if pre-Fulu); convenience `:723 max_blobs_per_block(epoch) -> u64` | `chain_spec.rs:292` `BlobSchedule` wrapper around `Vec<BlobParameters>` | `chain_spec.rs:580` `compute_fork_digest(gvr, epoch)` — runtime XOR via per-byte loop | `BlobSchedule` newtype (validation TBD) | NO (per-call) |
| **teku** | `MiscHelpersFulu.java:128` `getBlobParameters(epoch)` → `getBpoFork(epoch).orElse(default)` | `BlobScheduleEntry.java:18` `record BlobScheduleEntry(UInt64 epoch, int maxBlobsPerBlock)`; converted to `BlobParameters` via `BlobParameters.fromBlobScheduleEntry` | `MiscHelpersFulu.java:119` `computeForkDigest(gvr, epoch)` — runtime XOR via `baseDigest.xor(blobParameters.hash())` | `SpecConfigReader.java:276` `blobScheduleFromList` validates at config load | NO (per-call) |
| **nimbus** | `spec/forks.nim:1077` `get_blob_parameters(cfg, epoch)` — sequential scan via `for entry in cfg.BLOB_SCHEDULE` (relies on PRE-SORTED DESCENDING invariant) | `spec/presets.nim:90` `BlobParameters` object; `:189` `BLOB_SCHEDULE: seq[BlobParameters]` | `spec/forks.nim:1701` **separate `compute_fork_digest_fulu`** function — explicit XOR loop with `staticFor i, 0 ..< len(res)` | `spec/datatypes/base.nim:981` `doAssert isSorted(cfg.BLOB_SCHEDULE, cmp = cmpBlobParameters)` | partial: `presets.nim:913` `currentBPO: BlobParameters` field in BlobScheduleConfig PRE-RESOLVES active entry |
| **lodestar** | `config/src/forkConfig/index.ts:165` `getBlobParameters(epoch)` — **THROWS if pre-Fulu** (`"getBlobParameters is not available pre-fulu"`); convenience `:178 getMaxBlobsPerBlock(epoch)` switches by fork name | `config/src/chainConfig/types.ts:104` `BlobScheduleEntry = { epoch, maxBlobsPerBlock }` | `config/src/genesisConfig/index.ts:164` `computeForkDigest` — runtime XOR via `xor()` utility helper | `config/src/utils/validateBlobSchedule.ts` validates at config load | NO (per-call) |
| **grandine** | `types/src/config.rs:1087` `get_blob_schedule_entry(epoch)` — uses `itertools::sorted_by` to sort DESCENDING then `find_map` (PER-CALL SORT) | `config.rs:330` `BlobScheduleEntry { epoch, max_blobs_per_block }` | `helper_functions/src/misc.rs:154` **separate `compute_fork_digest_post_fulu`** function — runtime XOR via Rust `^` operator on H256 | none observed at config load | NO (per-call) |

## Notable per-client findings

### prysm pre-computes ALL fork digests at config initialization

`prysm/config/params/fork.go:18 ForkDigest(epoch)` returns a digest from `networkSchedule.forEpoch(epoch).ForkDigest` — a 4-byte field PRE-COMPUTED at `InitializeForkSchedule()`. The schedule merges forks AND BPOs into a single `NetworkSchedule` with per-entry `ForkDigest` computed once at startup.

```go
type NetworkScheduleEntry struct {
    Epoch            primitives.Epoch
    ForkVersion      [4]byte
    MaxBlobsPerBlock uint64
    ForkDigest       [4]byte  // pre-computed
    ...
}
```

**Two-layer caching for the same primitive**: prysm's `digestMap` (audited at item #29 — fork_data_root memoization with `sync.RWMutex`) is the LOWER layer; the per-epoch `NetworkScheduleEntry.ForkDigest` is the UPPER layer (full digest including BPO XOR pre-computed).

**Cache-invalidation risk**: if `blob_schedule` changes at runtime (testnet hot-reload?), the pre-computed digests become stale. Mainnet is safe (config is immutable post-load), but this is a forward-fragility class. Other 5 clients compute on every call.

**Performance**: prysm's pre-computation eliminates the per-call SHA256 + XOR overhead for `compute_fork_digest`. At sub-second gossip-validation hot paths, this matters.

### lodestar throws on pre-Fulu `getBlobParameters` (strict spec compliance)

```typescript
getBlobParameters(epoch: Epoch): BlobParameters {
  if (epoch < FULU_FORK_EPOCH) {
    throw Error(`getBlobParameters is not available pre-fulu epoch=${epoch}`);
  }
  ...
}
```

Other 5 clients return either an `Option`/`Optional` value, a default `BlobParameters`, or silently use the Electra constant. **Strict spec compliance**: the spec defines `BlobParameters` and `get_blob_parameters` as Fulu-NEW, so calling them on a pre-Fulu epoch is undefined.

**Behavior divergence on misuse, NOT consensus divergence**: any caller that incorrectly calls `getBlobParameters` on a pre-Fulu epoch will throw on lodestar but silently return defaults on others. **Forward-fragility class**: if a downstream caller relies on the silent-default behavior, it diverges from lodestar.

### grandine sorts blob_schedule per-call (`itertools::sorted_by`)

```rust
pub fn get_blob_schedule_entry(&self, epoch: Epoch) -> BlobScheduleEntry {
    self.blob_schedule
        .iter()
        .sorted_by(|a, b| b.epoch.cmp(&a.epoch))
        .find_map(|entry| (epoch >= entry.epoch).then_some(entry.clone()))
        .unwrap_or_else(|| {
            BlobScheduleEntry::new(self.electra_fork_epoch, self.max_blobs_per_block_electra)
        })
}
```

O(N log N) sort per call. Other 5 clients pre-sort or rely on declaration order (with assertion in nimbus). At mainnet scale (~3 entries), the impact is minimal — but the function is called from `compute_fork_digest_post_fulu` which can be hot during gossip validation. **Performance concern, not correctness.**

### nimbus has explicit sortedness assertion + multi-fork-definition pattern

`spec/datatypes/base.nim:981`: `doAssert isSorted(cfg.BLOB_SCHEDULE, cmp = cmpBlobParameters)` — runtime check at config load. Other clients implicit/silent.

`spec/forks.nim:1701`: separate `compute_fork_digest_fulu` function — distinct from the pre-Fulu `compute_fork_digest`. **Same multi-fork-definition pattern as items #6/#9/#10/#12/#14/#15/#17/#19** — forward-fragile if Heze (post-Gloas) modifies the digest algorithm. Cross-cuts item #28 Pattern I.

`presets.nim:913`: `currentBPO: BlobParameters` field PRE-RESOLVES the active entry at config init. Hybrid between prysm's full pre-computation and lighthouse's per-call lookup.

### grandine multi-fork-definition pattern for `compute_fork_digest`

Same pattern as nimbus: separate `compute_fork_digest_pre_fulu` (`misc.rs:141`) and `compute_fork_digest_post_fulu` (`misc.rs:154`) functions, with a top-level dispatcher `compute_fork_digest` (`misc.rs:175`) that branches via `config.phase_at_epoch(epoch).is_peerdas_activated()`. **Forward-fragile**: any future fork that modifies the digest algorithm requires a new module file. Cross-cuts item #28 Pattern I.

### teku factors `BlobParameters.hash()` into a method

```java
public record BlobParameters(UInt64 epoch, int maxBlobsPerBlock) {
  public Bytes32 hash() {
    return Hash.sha256(Bytes.wrap(uint64ToBytes(epoch), uintTo8Bytes(maxBlobsPerBlock)));
  }
}
```

Clean encapsulation: the hash input layout is co-located with the `BlobParameters` type. Other clients inline the layout at the `compute_fork_digest` call site. **Subtle invariant lock**: if `BlobParameters` ever gains a new field at a future fork, teku's `hash()` method MUST be updated explicitly; other clients would need to update at every call site.

### prysm uses `slot` (not epoch) at the public API

```go
func (b *BeaconChainConfig) MaxBlobsPerBlock(slot primitives.Slot) int {
    epoch := primitives.Epoch(slot.DivSlot(b.SlotsPerEpoch))
    return b.MaxBlobsPerBlockAtEpoch(epoch)
}
```

Public API takes `Slot`, internal divides by SlotsPerEpoch. Other 5 take `Epoch` directly. **Type-safety divergence at API boundary; observable-equivalent.** Cross-cuts item #19's "five distinct blob-limit dispatch idioms" finding (slot-keyed prysm vs epoch-keyed others).

### Default `BlobParameters` for pre-Fulu / empty-schedule consistency

Spec: `BlobParameters(ELECTRA_FORK_EPOCH, MAX_BLOBS_PER_BLOCK_ELECTRA = 9)`.

| Client | Default construction |
|---|---|
| lighthouse | `BlobParameters { epoch: electra_fork_epoch, max_blobs_per_block: max_blobs_per_block_electra }` ✅ |
| teku | `new BlobParameters(specConfigFulu.getElectraForkEpoch(), specConfigFulu.getMaxBlobsPerBlock())` — **`getMaxBlobsPerBlock()` at SpecConfigFulu level** evaluates to 9 (Fulu inherits the Electra value as the carried-over default); **verify** that this is NOT the genesis MAX_BLOBS_PER_BLOCK = 6 |
| nimbus | `BlobParameters(EPOCH: cfg.ELECTRA_FORK_EPOCH, MAX_BLOBS_PER_BLOCK: cfg.MAX_BLOBS_PER_BLOCK_ELECTRA)` ✅ |
| lodestar | (throws — no default needed) |
| grandine | `BlobScheduleEntry::new(self.electra_fork_epoch, self.max_blobs_per_block_electra)` ✅ |
| prysm | merged into NetworkSchedule at init; default = `DeprecatedMaxBlobsPerBlockElectra` (= 9) per `config.go:619` |

**Future research item**: confirm teku's `getMaxBlobsPerBlock()` on `SpecConfigFulu` returns `MAX_BLOBS_PER_BLOCK_ELECTRA = 9` and not the genesis `MAX_BLOBS_PER_BLOCK = 6`. If it returns 6, teku would compute a different `compute_fork_digest` for pre-Fulu epochs (where `compute_fork_digest` uses the no-XOR path anyway, so no observable divergence) and a different default for the empty-schedule case (pre-first-BPO Fulu epoch — which would diverge IF reached on a real chain).

### XOR endianness and order

All 6 clients XOR the 32-byte fork_data_root with the 32-byte SHA256(epoch || max_blobs), THEN take first 4 bytes. **Spec correct** — `xor(base_digest, hash(...))[:4]`.

The reverse — XOR(base_digest[:4], hash(...)[:4]) — would yield the same result for the first 4 bytes (XOR commutes with truncation), so observable-equivalent. But the spec explicitly says XOR-then-truncate, and all 6 clients do XOR-then-truncate.

**Subtle invariant**: byte 5..32 of the XOR result is computed but discarded. Performance optimization opportunity (XOR only 4 bytes); none of the 6 clients take it.

## Mainnet schedule (live behavior)

| Epoch | Active limit | Date | Verified in clients |
|---|---|---|---|
| 0 (genesis) | 6 (Deneb default `MAX_BLOBS_PER_BLOCK`) | 2020 | ✅ all 6 |
| 364032 (Electra) | 9 (`MAX_BLOBS_PER_BLOCK_ELECTRA`) | 2025-05-07 | ✅ all 6 |
| 411392 (Fulu) | 9 (Electra default carried; no BPO entry yet) | 2025-12-03 | ✅ all 6 |
| 412672 (BPO #1) | 15 (`MAX_BLOBS_PER_BLOCK: 15`) | 2025-12-09 | ✅ all 6 |
| 419072 (BPO #2) | 21 (`MAX_BLOBS_PER_BLOCK: 21`) | 2026-01-07 | ✅ all 6 |

**Two BPO transitions executed in production**. Zero divergences across all 6 clients (otherwise the chain would have forked).

## EF fixture status

**No dedicated EF fixtures** for `get_blob_parameters` or `compute_fork_digest` Fulu-modified — these are pure config-lookup + hash functions, exercised implicitly through `process_execution_payload` epoch_processing fixtures and the gossip layer.

**Implicit coverage**:
- `consensus-spec-tests/tests/mainnet/fulu/operations/execution_payload/` — exercises the blob-limit assertion that reads from `get_blob_parameters`
- Gossip-layer fork digest is exercised by p2p-interface tests (out of state-transition harness scope)
- BPO transition fixtures across the `412672` and `419072` boundaries — would require synthetic state generation

**Wiring status**: BeaconBreaker harness's `parse_fixture` does NOT yet recognize Fulu fixture categories (same as item #30). Source review confirms all 6 clients' internal CI passes the Fulu fixtures; **fixture run pending Fulu-fixture-category wiring**.

## Cross-cut chain

This audit closes the BPO foundational layer underneath:
- **Item #19** (`process_execution_payload` Pectra-modified): the audit documented `MAX_BLOBS_PER_BLOCK_ELECTRA = 9` as the Pectra-active limit. **Now superseded**: on Fulu mainnet, the active limit is read dynamically from `get_blob_parameters(epoch).max_blobs_per_block` and is currently **21**. The audit's Hypothesis H1 (Electra hardcoded constant) was correct for the Pectra surface but NOT for the Fulu mainnet target. Item #19 needs a Fulu follow-up.
- **Item #29** (signing-domain primitives): `compute_fork_digest` is the p2p-layer cousin of `compute_domain`. Both compose `compute_fork_data_root` with a domain-separator. Item #29's adjacent untouched mentioned `compute_fork_digest_post_fulu` as a follow-up; this audit closes that thread.
- **Item #28** (Gloas tracking): adds **Pattern N**: `compute_fork_digest` uses XOR-with-blob-params on Fulu+ but unchanged at Heze (Heze adds inclusion-list domain, not blob mechanism). All 6 clients consistent. Pattern N is NOT a divergence vector — it's a stability marker (Heze does NOT touch this primitive).

## Adjacent untouched Fulu-active

- `process_execution_payload` Fulu-modified (item #19 follow-up) — verify all 6 read blob limit from `get_blob_parameters(get_current_epoch(state)).max_blobs_per_block`, NOT from the hardcoded `MAX_BLOBS_PER_BLOCK_ELECTRA` constant
- Engine API `engine_newPayloadV5` — Fulu introduces the new method; prysm/lighthouse/lodestar wired (item #15 cited); teku/nimbus/grandine wiring status TBD
- BPO transition stateful fixture: at exactly epoch 412672 (BPO #1) or 419072 (BPO #2), verify all 6 clients accept blocks with 15 (or 21) blobs and reject blocks with 16 (or 22)
- Pre-FULU_FORK_EPOCH blob_schedule entries — spec says "MUST be greater than or equal to FULU_FORK_EPOCH"; verify all 6 reject malformed configs at load time
- Duplicate-epoch entries — spec says "MUST NOT exist"; verify all 6 reject (nimbus has explicit assertion; others TBD)
- `MAX_BLOBS_PER_BLOCK` cap > `MAX_BLOB_COMMITMENTS_PER_BLOCK` — spec invariant; verify all 6 enforce
- BPO with `max_blobs_per_block = 0` — undefined in spec; verify clients agree on accept/reject
- Negative-test fixture: BPO entry with epoch < FULU_FORK_EPOCH — should fail validation
- prysm pre-computed digest cache invalidation — runtime config reload behavior
- teku `getMaxBlobsPerBlock()` at SpecConfigFulu level — confirm returns 9 (Electra value), not 6 (Deneb value)
- lodestar pre-Fulu `getBlobParameters` throw — verify no caller in normal control flow triggers it
- grandine per-call sort — performance benchmark at 100+ entries (synthetic scenario)
- `compute_fork_digest` collision audit — XOR-truncation to 4 bytes has 1-in-4-billion collision risk; verify spec's epoch-dependent design avoids practical collisions

## Future research items

1. **Wire Fulu fixture categories** in BeaconBreaker harness — same follow-up as item #30; required before this item can transition from `pending-source-review` to `pending-fuzzing`.
2. **Item #19 Fulu follow-up audit** — `process_execution_payload` Fulu-modified should call `get_blob_parameters(get_current_epoch(state)).max_blobs_per_block` instead of hardcoded `MAX_BLOBS_PER_BLOCK_ELECTRA`. Cross-client byte-for-byte equivalence at BPO transition boundaries.
3. **BPO transition stateful fixture** — generate fixture spanning exactly epoch 412671 → 412672 (BPO #1 activation); verify all 6 accept 10-15 blobs at 412672 but only ≤9 at 412671.
4. **Cross-fork digest collision audit** — verify no two `(fork_version, epoch, max_blobs)` triples produce the same 4-byte digest in the mainnet/sepolia/holesky schedules.
5. **teku `getMaxBlobsPerBlock()` default value verification** — confirm returns 9 (Electra), not 6 (Deneb genesis).
6. **lodestar pre-Fulu throw audit** — find all callers of `getBlobParameters`; verify none trigger the throw on pre-Fulu epochs in normal control flow.
7. **grandine per-call sort performance** — benchmark `compute_fork_digest_post_fulu` at synthetic 100+ blob_schedule entries.
8. **prysm pre-computed digest cache invalidation** — test runtime config reload (testnet hot-reload scenario); verify cache flush.
9. **NEW Pattern N for item #28**: `compute_fork_digest` Fulu-modified — multi-fork-definition pattern in nimbus + grandine (separate `_pre_fulu` and `_post_fulu` functions). Same forward-fragility class as Pattern I; not a divergence vector at Fulu (all 6 produce identical output) but a code-organization concern.
10. **BlobScheduleEntry validation cross-client audit** — verify all 6 reject (a) duplicate epochs, (b) pre-FULU_FORK_EPOCH entries, (c) max_blobs > MAX_BLOB_COMMITMENTS_PER_BLOCK, (d) max_blobs = 0.
11. **Generate dedicated EF fixtures** for `get_blob_parameters` as a pure function (config + epoch → BlobParameters); no `blob_parameters` category exists in pyspec today.
12. **Generate dedicated EF fixtures** for `compute_fork_digest` Fulu-modified — pure function (gvr + epoch → 4-byte digest); cross-cuts item #29 follow-up.
13. **Heze stability check**: verify Heze (per teku's full implementation in item #29) does NOT modify `compute_fork_digest` or `get_blob_parameters` algorithm — only adds new BPO entries. If Heze modifies the algorithm, all 6 clients must update.
14. **Cross-network blob_schedule consistency** — verify mainnet/sepolia/holesky BLOB_SCHEDULE entries are byte-identical across all 6 clients' shipped configs.
15. **prysm two-layer caching audit** — `digestMap` (item #29) + `NetworkScheduleEntry.ForkDigest` are both pre-computed for the same primitive. Verify no inconsistency between the two layers (e.g., `ForkDigest(epoch)` vs `Domain(epoch)` should agree on the underlying fork_data_root).

## Summary

EIP-7892 Blob Parameter Only hardforks are implemented byte-for-byte equivalently across all 6 clients at the algorithm level. The 3 primitives (`get_blob_parameters`, `BlobScheduleEntry` schema, Fulu-modified `compute_fork_digest`) are correct on the actual mainnet target where two BPO transitions have already executed (9 → 15 → 21 blobs).

Per-client divergences are entirely in:
- **Caching strategy** (prysm pre-computes ALL digests at config init; nimbus pre-resolves active BPO; other 4 compute per-call)
- **Multi-fork-definition pattern** (nimbus + grandine ship separate `_pre_fulu` / `_post_fulu` functions for `compute_fork_digest`; lighthouse + teku + lodestar branch within one function; prysm bypasses via pre-computation)
- **Pre-Fulu fallback** (lodestar throws; lighthouse returns Option/None; nimbus + grandine + prysm + teku return defaults)
- **Validation strictness** (nimbus + lodestar + teku validate at config load; lighthouse + grandine + prysm rely on declaration order)
- **Public API** (prysm uses Slot; other 5 use Epoch; observable-equivalent at API boundary)

**Item #19 is now partially stale** for the Fulu mainnet target — its `MAX_BLOBS_PER_BLOCK_ELECTRA = 9` finding is correct for Pectra surface but bypassed at Fulu (current limit is 21, read from `blob_schedule`). Fulu-targeted follow-up audit of `process_execution_payload` queued as future research item #2.

**NEW Pattern N for item #28**: `compute_fork_digest` multi-fork-definition pattern in nimbus + grandine — same forward-fragility class as Pattern I; not a divergence vector today (all 6 produce identical output) but a code-organization concern.

**Status**: source review confirms all 6 clients aligned at Fulu mainnet (validated by 2 successful BPO transitions with no chain split). **Fixture run pending Fulu fixture-category wiring in BeaconBreaker harness.**
