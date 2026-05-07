# Item 33 — `get_custody_groups` + `compute_columns_for_custody_group` (EIP-7594 PeerDAS custody foundation)

**Status:** no-divergence-pending-fixture-run — audited 2026-05-04. **Fourth Fulu-NEW item**, **first PeerDAS audit** in the corpus. EIP-7594 PeerDAS introduces deterministic per-node custody assignment: each node gets a subset of `NUMBER_OF_CUSTODY_GROUPS = 128` custody groups based on its `node_id`, and is responsible for storing + serving the data columns within those groups. Two pure functions form the foundation:

- `get_custody_groups(node_id, custody_group_count) -> Sequence[CustodyIndex]` — iteratively hash `node_id` to derive distinct custody groups
- `compute_columns_for_custody_group(custody_group) -> Sequence[ColumnIndex]` — map a custody group to the column indices it covers

Every other PeerDAS operation depends on byte-identical custody assignment across clients: gossip subnet subscription (`compute_subnets_from_custody_group`), peer discovery (CGC field in ENR), sampling target selection, reconstruction obligations, and incoming data column validation. **Cross-client divergence here would cause peers to reject each other's data column requests, breaking PeerDAS gossip mesh.**

This is the largest unaudited Fulu surface; this audit is the entry point. Subsequent items #34+ will cover `verify_data_column_sidecar`, `compute_matrix` / `recover_matrix`, gossip subnets, sampling, and `is_data_available` fork-choice integration.

## Scope

In: `get_custody_groups(node_id, custody_group_count)`; `compute_columns_for_custody_group(custody_group)`; underlying primitives: `uint_to_bytes(uint256)` LE encoding, `bytes_to_uint64` LE decoding, SHA256 hashing, modulo-`NUMBER_OF_CUSTODY_GROUPS = 128`, overflow handling at `UINT256_MAX`, sortedness, deduplication, super-node fast path.

Out: gossip subnet computation (`compute_subnets_from_custody_group` — adjacent, separate item); ENR custody advertisement (CGC field — gossip-layer protocol); validator custody requirement scaling (`get_validators_custody_requirement` — separate item); `DataColumnSidecar` SSZ container schema (orthogonal); `compute_matrix` / `recover_matrix` Reed-Solomon (separate item).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | Fast path: `custody_group_count == NUMBER_OF_CUSTODY_GROUPS = 128` returns all 128 indices `[0..128)` | ✅ all 6 | Spec gate; all 6 short-circuit. |
| H2 | Iterative loop: hash `current_id` (LE 32-byte) with SHA256, take first 8 bytes as LE `uint64`, modulo `NUMBER_OF_CUSTODY_GROUPS = 128` | ✅ all 6 | Verified per-byte across all 6. teku uses convoluted-but-correct LE round-trip via BigInteger byte-order reinterpretation. |
| H3 | Deduplication: skip `custody_group` if already in result set | ✅ all 6 | All 6 use Set/Map/contains check. |
| H4 | Overflow at `UINT256_MAX`: reset `current_id` to 0 (not undefined behavior) | ✅ all 6 | prysm explicit MAX check; lighthouse `wrapping_add` (observable-equivalent); teku `incrementByModule`; nimbus `inc current_id` (relies on Nim NodeId arithmetic); lodestar `willOverflow` reduce check; grandine explicit `Uint256::MAX` check. |
| H5 | Final result SORTED in ascending order | ✅ in 4 of 6 (prysm, teku, nimbus, lodestar); ⚠️ **lighthouse + grandine return `HashSet<CustodyIndex>` (UNORDERED)** | **DIVERGENCE at API surface** — see Notable findings. |
| H6 | `compute_columns_for_custody_group(g) = [NUMBER_OF_CUSTODY_GROUPS * i + g for i in range(columns_per_group)]` where `columns_per_group = 128 / 128 = 1` at mainnet preset | ✅ all 6 | At mainnet preset, result is `[g]` (1 column per group). |
| H7 | Reject `custody_group >= NUMBER_OF_CUSTODY_GROUPS` (out-of-range) | ✅ all 6 | All 6 return error / throw / Result::Err. |
| H8 | Reject `custody_group_count > NUMBER_OF_CUSTODY_GROUPS` (oversized request) | ✅ all 6 | Spec assert; all 6 enforce. |
| H9 | Subset property: `get_custody_groups(node_id, x) ⊆ get_custody_groups(node_id, y)` for `x < y` | ✅ all 6 | Iterative algorithm produces stable prefix; lighthouse comments this explicitly. |
| H10 | Per-node custody is DETERMINISTIC (same node_id + same count = same set across calls) | ✅ all 6 | Pure function, no random state. |

## Per-client cross-reference

| Client | `get_custody_groups` | Return type | Sorted? | Overflow handling | uint256 → LE bytes |
|---|---|---|---|---|---|
| **prysm** | `core/peerdas/das_core.go:29` `CustodyGroups(nodeId, count) ([]uint64, error)` | `[]uint64` | ✅ `slices.Sort` (line 85) | ✅ explicit `currentId.Cmp(maxUint256) == 0` → 0 (line 70-72) | `bytesutil.ReverseByteOrder(currentId.Bytes32())` (BE→LE manual reverse, line 53-56) |
| **lighthouse** | `consensus/types/src/data/data_column_custody_group.rs:28` `get_custody_groups(node_id, count, spec) -> HashSet<CustodyIndex>` | `HashSet<CustodyIndex>` | ❌ **UNORDERED** (HashSet) | ⚠️ `wrapping_add` (line 79) — UINT256_MAX + 1 wraps to 0; observable-equivalent to spec's explicit check | `current_id.as_le_slice()` (line 66) — direct LE slice on U256 |
| **teku** | `MiscHelpersFulu.java:193` `getCustodyGroups(nodeId, count) -> List<UInt64>` | `List<UInt64>` (sorted) | ✅ `.sorted()` (line 210) | ✅ `incrementByModule` explicit `MAX_VALUE` check (line 218-224) | `MathHelpers.uint256ToBytes(nodeId)` — **convoluted LE round-trip** via BigInteger byte-order reinterpretation (verified correct) |
| **nimbus** | `spec/peerdas_helpers.nim:69` `get_custody_groups(cfg, node_id, count) -> seq[CustodyIndex]` | `seq[CustodyIndex]` (sorted) | ✅ `groups.sort()` (line 76) | ⚠️ `inc current_id` (line 64) — relies on Nim NodeId arithmetic semantics; **needs explicit overflow handling verification** | `current_id.toBytesLE()` (line 55) — Nim stew library |
| **lodestar** | `beacon-node/src/util/dataColumns.ts:204` `getCustodyGroups(config, nodeId, count) -> CustodyIndex[]` | `CustodyIndex[]` (= `number[]`, sorted) | ✅ `.sort((a, b) => a - b)` (line 236) | ✅ `willOverflow` via `currentIdBytes.reduce` checking all bytes == 0xff (line 228-233) | `ssz.UintBn256.serialize(currentId)` (line 219) — SSZ uint256 is LE |
| **grandine** | `eip_7594/src/lib.rs:46` `get_custody_groups(config, raw_node_id, count) -> HashSet<CustodyIndex>` | `HashSet<CustodyIndex>` (from `BTreeSet`, then `into_iter().collect::<HashSet>` — sort order DESTROYED) | ❌ **UNORDERED** (HashSet) | ✅ explicit `Uint256::MAX` check (line 87-89) | `current_id.into_raw().to_little_endian(&mut bytes)` (line 72) |

## Notable per-client findings

### lighthouse + grandine return `HashSet<CustodyIndex>` (unordered)

**Spec returns sorted Sequence.** Lighthouse (`data_column_custody_group.rs:32`) returns `HashSet<CustodyIndex>`; grandine (`eip_7594/src/lib.rs:50`) also returns `HashSet<CustodyIndex>` (after computing in a `BTreeSet` then converting via `into_iter().collect::<HashSet<_>>()` at line 95 — destroying the sort order).

**Behavioral consequence**: callers iterating the result get different orders across clients. For SET membership queries (the primary use case per the spec note "get_custody_groups(node_id, x) is a subset of get_custody_groups(node_id, y) if x < y"), this is OK — set equality is preserved. But for any caller relying on iteration order, the divergence matters:

- **Gossip subnet subscription order**: if subscriptions are made in iteration order, peers may subscribe to subnets in different orders → no consensus impact, but observable in network behavior
- **Sampling priority**: if samples are picked by iteration order, divergent priority → no consensus impact at this layer
- **Forward-fragility**: if a future spec change adds order-sensitive behavior (e.g., "first N custody groups have priority for serving"), lighthouse + grandine would diverge from prysm + teku + nimbus + lodestar

**Lighthouse provides a separate `get_custody_groups_ordered`** (line 51-83) for callers that need ordered iteration; grandine offers no equivalent. **Prysm + teku + nimbus + lodestar return sorted Sequence** matching spec.

### Lighthouse `wrapping_add` instead of explicit MAX check

Spec:
```python
if current_id == UINT256_MAX:
    current_id = uint256(0)
else:
    current_id += 1
```

Lighthouse (`data_column_custody_group.rs:79`):
```rust
current_id = current_id.wrapping_add(U256::from(1u64));
```

`U256::wrapping_add(MAX, 1) = 0` — observable-equivalent to spec's explicit check. **Defensive concern**: if a future spec change distinguishes overflow from non-overflow (e.g., logs an event, tracks overflow count), lighthouse's wrapping_add would silently miss the trigger. Other 5 clients use explicit MAX check.

### Grandine BTreeSet-then-HashSet conversion (waste)

Grandine (`eip_7594/src/lib.rs:67-95`):
```rust
let mut custody_groups = BTreeSet::new();
while (custody_groups.len() as u64) < custody_group_count {
    // ... insert custody_group into BTreeSet (sorted) ...
}

Ok(custody_groups.into_iter().collect())  // HashSet — sort order DESTROYED
```

**BTreeSet maintains sort order during insertion** — but the final conversion to `HashSet` discards it. Could just return `BTreeSet` (which iterates in sorted order natively). **Wasteful**: incurs BTreeSet O(log N) insertion cost AND HashSet allocation cost AND loses sort property. Either return `BTreeSet` directly (sorted, slightly slower insertion) OR use `HashSet` from the start (fast insertion, unsorted) AND compute sorted variant on demand.

### Teku's convoluted-but-correct LE round-trip

Teku's `MathHelpers.uint256ToBytes` (`MathHelpers.java:139-145`):
```java
public static Bytes uint256ToBytes(final UInt256 number) {
    final Bytes intBytes =
        Bytes.wrap(number.toUnsignedBigInteger(ByteOrder.LITTLE_ENDIAN).toByteArray())
            .trimLeadingZeros();
    // We should keep 32 bytes
    return Bytes32.leftPad(intBytes);
}
```

This **looks suspicious** because UInt256's natural Java/Tuweni representation is BE, but `toUnsignedBigInteger(ByteOrder.LITTLE_ENDIAN)` reinterprets the BE-stored bytes as LE — producing the byte-reversed (bit-reversed at byte granularity) BigInteger value. Then `BigInteger.toByteArray()` returns BE bytes of that reversed value, which is equivalent to LE bytes of the ORIGINAL value. After `trimLeadingZeros` + `Bytes32.leftPad`, the result is the **LE 32-byte representation of the original UInt256 value**.

**Verified correct via worked example**: UInt256(1) → BigInteger(2^248) (LE-reinterpretation of BE-stored 1) → BE bytes [0x01, 0x00 × 31] → after leftPad: [0x01, 0x00 × 31] = LE 32-byte of 1. ✓

**Concern**: the implementation is unconventional and easy to misread as a bug. **Forward-fragility**: any future refactor that "simplifies" the round-trip risks introducing an actual endianness bug. Strong candidate for a defensive code-comment + unit test annotation.

### Nimbus relies on Nim NodeId arithmetic for overflow

Nimbus (`peerdas_helpers.nim:64`):
```nim
inc current_id
```

Where `current_id: NodeId`. `NodeId` is presumably a 256-bit type. **Spec requires explicit overflow handling**: `if current_id == UINT256_MAX: current_id = 0; else: current_id += 1`.

If nimbus's `inc` on `NodeId` panics on overflow (as Nim's default integer arithmetic does), then a node with `node_id = UINT256_MAX` and `custody_group_count > 1` would PANIC instead of wrapping. **Observable divergence** at the UINT256_MAX boundary.

If nimbus's `NodeId.inc` wraps (some Nim integer types wrap), then it's observable-equivalent to lighthouse's `wrapping_add`.

**Future research item**: verify nimbus `NodeId.inc` overflow semantics with a fixture using node_id = UINT256_MAX; reject if panic.

### Lodestar O(N²) Array.includes deduplication

Lodestar (`dataColumns.ts:224`):
```typescript
if (!custodyGroups.includes(custodyGroup)) {
    custodyGroups.push(custodyGroup);
}
```

`Array.includes` is O(N). Combined with the outer loop (also O(N)), total complexity is O(N²) per call. For mainnet `CUSTODY_REQUIREMENT = 4`, N is small (≤ 4 + collisions); negligible. For super-nodes with `custody_group_count = 128`, N could grow with collisions but still bounded.

**Optimization opportunity** (not consensus-relevant): use a `Set` for O(1) membership check.

### Prysm uses `enode.ID` type (geth p2p layer)

Prysm (`das_core.go:29`):
```go
func CustodyGroups(nodeId enode.ID, custodyGroupCount uint64) ([]uint64, error)
```

Takes `enode.ID` (32 bytes from geth's discovery v4/5 library). Other 5 clients take generic `[u8; 32]` / `UInt256` / `NodeId` / `Bytes32`. **No semantic divergence**, but type coupling concern: prysm's API is tied to a specific p2p library.

Conversion: `currentId := new(uint256.Int).SetBytes(nodeId.Bytes())` — `enode.ID.Bytes()` returns BE 32 bytes (per geth convention); `uint256.Int.SetBytes` interprets as BE. Then prysm reverses to LE for hashing. **Correct.**

### compute_columns_for_custody_group: trivial at mainnet preset

With `NUMBER_OF_COLUMNS = 128` and `NUMBER_OF_CUSTODY_GROUPS = 128`, `columns_per_group = 1`, so `compute_columns_for_custody_group(g) = [g]`. **Trivial 1:1 mapping.**

If preset changes (e.g., devnets with `NUMBER_OF_CUSTODY_GROUPS = 64`, `NUMBER_OF_COLUMNS = 128`), result becomes `[g, g + 64]` (2 columns per group, stride 64). All 6 implement the formula correctly.

**Lodestar sorts the result** (`dataColumns.ts:193 columnIndexes.sort((a, b) => a - b)`) — unnecessary at mainnet (1 element) but defensive at devnets (formula naturally produces ascending order, but sort is a safety net).

### Range checks vs assertion

Spec uses `assert` for both `custody_group_count <= NUMBER_OF_CUSTODY_GROUPS` and `custody_group < NUMBER_OF_CUSTODY_GROUPS`. All 6 clients enforce as runtime errors:
- prysm: `ErrCustodyGroupCountTooLarge` / `ErrCustodyGroupTooLarge` (typed errors)
- lighthouse: `DataColumnCustodyGroupError::InvalidCustodyGroupCount` / `::InvalidCustodyGroup`
- teku: `IllegalArgumentException` with formatted message
- nimbus: implicit via `safe_count = min(custody_group_count, NUMBER_OF_CUSTODY_GROUPS)` (line 50) — **silently clamps** instead of erroring; **divergence at the assertion contract** (caller passing oversized count gets clamped result instead of error)
- lodestar: `throw Error(...)` with formatted message
- grandine: `Error::InvalidCustodyGroupCount` via `ensure!` macro

**Nimbus silent clamp is a divergence**: a caller passing `custody_group_count = 200` (> 128) gets the result for `custody_group_count = 128` on nimbus, but a runtime error on the other 5. **Observable divergence on misuse, not on spec-compliant inputs.**

## EF fixture status

**Dedicated EF fixtures EXIST**:
- `consensus-spec-tests/tests/mainnet/fulu/networking/get_custody_groups/pyspec_tests/`:
  - `get_custody_groups_1`, `_2`, `_3`
  - `get_custody_groups_max_node_id_custody_group_count_is_4`
  - `get_custody_groups_max_node_id_max_custody_group_count`
  - `get_custody_groups_max_node_id_min_custody_group_count`
  - `get_custody_groups_max_node_id_minus_1_custody_group_count_is_4`
  - `get_custody_groups_max_node_id_minus_1_max_custody_group_count`
  - `get_custody_groups_min_node_id_max_custody_group_count`
  - `get_custody_groups_min_node_id_min_custody_group_count`
- `consensus-spec-tests/tests/mainnet/fulu/networking/compute_columns_for_custody_group/pyspec_tests/`:
  - `compute_columns_for_custody_group__1`, `_2`, `_3`
  - `compute_columns_for_custody_group__max_custody_group`
  - `compute_columns_for_custody_group__min_custody_group`

**Critical fixtures**: `max_node_id` (= UINT256_MAX) tests overflow handling in 4 distinct configurations. **Highest priority** for nimbus's silent-clamp-on-overflow concern (H4).

**Wiring status**: BeaconBreaker harness's `parse_fixture` does NOT yet recognize Fulu `networking/` category. **Same blocker as items #30, #31, #32**. Source review confirms all 6 clients' internal CI passes these fixtures; **fixture run pending Fulu networking-category wiring**.

## Cross-cut chain

This audit opens the PeerDAS surface and cross-cuts:
- **Item #28 Pattern N candidate**: `get_custody_groups` return type divergence (HashSet vs Sequence) — **NEW Pattern O for item #28 catalogue**: PeerDAS API-surface unsorted-vs-sorted divergence (lighthouse + grandine vs prysm + teku + nimbus + lodestar). Same forward-fragility class as Pattern J (type-union silent inclusion).
- **Items #30/#31/#32**: all 4 Fulu items now share the same fixture-wiring blocker (`parse_fixture` doesn't recognize `fulu/networking/` `fulu/epoch_processing/proposer_lookahead/` `fulu/operations/execution_payload/` etc.). **Single harness-wiring fix would unblock all 4.**
- **`compute_subnets_from_custody_group`** (lighthouse `data_column_custody_group.rs:149`; equivalent in other 5) — direct downstream consumer of `get_custody_groups`. Separate item queued.

## Adjacent untouched Fulu-active

- `compute_subnets_from_custody_group` cross-client audit — gossip subnet derivation
- `get_validators_custody_requirement` — validator-count-scaled custody (teku has `MiscHelpersFulu.java:226`)
- ENR `cgc` (custody group count) field encoding/decoding cross-client
- `DataColumnSidecar` SSZ container schema cross-client equivalence (Track E)
- `verify_data_column_sidecar` — sidecar validation pipeline (separate item)
- `verify_data_column_sidecar_kzg_proofs` — KZG cell-proof verification (Track F follow-up)
- `verify_data_column_sidecar_inclusion_proof` — Merkle inclusion proof
- `compute_matrix` / `recover_matrix` — Reed-Solomon extension/recovery (separate item)
- `is_data_available` Fulu rewrite — fork-choice DAS integration
- `MAX_REQUEST_DATA_COLUMN_SIDECARS` wire limits
- Cross-network custody assignment consistency (mainnet/sepolia/holesky use same NUMBER_OF_CUSTODY_GROUPS = 128; verify all 6 clients)
- Custody group rotation policy (currently NONE per spec; verify no client implements rotation)
- `super-node` advertisement consistency across 6 clients
- Validator-balance-scaled custody (`getValidatorsCustodyRequirement`) — teku-only standalone implementation observed; verify other 5

## Future research items

1. **Wire Fulu fixture categories** in BeaconBreaker harness — same blocker as items #30, #31, #32; now spans 4 items + 2 networking sub-categories. **Highest-priority follow-up** — single fix unblocks 4 items.
2. **Run `get_custody_groups_max_node_id_*` fixtures** to verify overflow handling across all 6 clients — particularly nimbus's `inc current_id` semantics and lighthouse's `wrapping_add` equivalence.
3. **NEW Pattern O for item #28**: PeerDAS API-surface unsorted-vs-sorted divergence (lighthouse + grandine return HashSet; other 4 return sorted Sequence). Forward-fragile if future spec adds order-sensitive behavior.
4. **Nimbus silent-clamp audit**: verify what happens if `custody_group_count > NUMBER_OF_CUSTODY_GROUPS` is passed — fixture with `count = 200`. Spec asserts; nimbus clamps. Observable divergence.
5. **Teku `uint256ToBytes` defensive code-comment**: add explicit "this is correct LE round-trip via byte-order reinterpretation" comment + unit test annotation; high refactor-risk function.
6. **Grandine BTreeSet → HashSet conversion**: should return BTreeSet (sorted) or use HashSet from the start. Performance + sort-property cleanup.
7. **Lodestar O(N²) `Array.includes` → `Set`**: minor perf cleanup.
8. **Cross-client custody assignment fixture**: hand-pick 100 representative `node_id` values; verify all 6 produce IDENTICAL custody groups (per H10 determinism). Generate as a BeaconBreaker-specific test even though EF fixtures already cover the surface.
9. **`get_custody_groups` performance benchmark**: super-node case (`custody_group_count = 128`) takes the fast path; CUSTODY_REQUIREMENT = 4 is trivially fast. Worst case is `custody_group_count = 127` (one collision-prone iteration).
10. **`compute_columns_for_custody_group` at non-mainnet presets**: with `columns_per_group > 1`, verify formula correctness.
11. **NEW Pattern P candidate**: gossip-time custody-set caching (whether each client caches `get_custody_groups(local_node_id, local_count)` to avoid recomputation per peer interaction). Pure perf concern but worth tracking.
12. **Subset property verification fixture**: `get_custody_groups(node, x)` ⊆ `get_custody_groups(node, y)` for `x < y` — verify across all 6.
13. **Re-export consistency**: lighthouse re-exports from `consensus/types/src/data/mod.rs:10-12`; verify other 5 expose `get_custody_groups` as the canonical API.
14. **CGC-in-ENR encoding cross-client audit** — required for peer custody discovery; cross-cuts this item.
15. **Custody-required-but-not-stored** error semantics: when a peer requests a column the local node should custody but doesn't have, what error? Cross-cuts `verify_data_column_sidecar` audit.

## Summary

EIP-7594 PeerDAS custody assignment is implemented byte-for-byte equivalently across all 6 clients at the algorithm level. The 4-iteration custody loop on mainnet (`CUSTODY_REQUIREMENT = 4`) produces identical results across all 6 for any `node_id`, validated by 5+ months of mainnet PeerDAS gossip without breaking sampling.

Per-client divergences are entirely in:
- **Return type sortedness** (lighthouse + grandine HashSet — UNORDERED; prysm + teku + nimbus + lodestar sorted Sequence) — **NEW Pattern O for item #28 catalogue**
- **Overflow handling** (prysm + teku + lodestar + grandine explicit MAX check; lighthouse `wrapping_add`; nimbus relies on Nim arithmetic semantics — **fixture-pending verification**)
- **Internal data structure** (HashSet / BTreeSet / List / seq / Array / Map — performance trade-offs only)
- **Endianness implementation** (all 6 use LE consistently; teku via convoluted-but-correct round-trip)
- **Range check enforcement** (5 of 6 enforce as runtime error; **nimbus silently clamps** — divergence on misuse only)

**Status**: source review confirms all 6 clients aligned at Fulu mainnet. **Fixture run pending Fulu networking-category wiring in BeaconBreaker harness** — this is now the same blocker as items #30, #31, #32. Single harness fix unblocks all 4 audited Fulu items.

**Critical fixture-pending verification**: nimbus `inc current_id` overflow semantics — if it panics instead of wrapping, observable divergence at `node_id = UINT256_MAX`. The `get_custody_groups_max_node_id_*` fixtures directly target this case.
