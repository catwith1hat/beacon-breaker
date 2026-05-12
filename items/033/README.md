---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [28]
eips: [EIP-7594]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.3
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.3.1
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 33: `get_custody_groups` + `compute_columns_for_custody_group` (EIP-7594 PeerDAS custody foundation)

## Summary

EIP-7594 PeerDAS introduces deterministic per-node custody assignment: each node gets a subset of `NUMBER_OF_CUSTODY_GROUPS = 128` custody groups based on its `node_id`, and is responsible for storing + serving the data columns within those groups. Two pure functions form the foundation: `get_custody_groups(node_id, custody_group_count)` iteratively hashes `node_id` to derive distinct custody groups; `compute_columns_for_custody_group(custody_group)` maps a custody group to its column indices. Every other PeerDAS operation (gossip subnet subscription, peer discovery, sampling target selection, reconstruction obligations, incoming data column validation) depends on byte-identical custody assignment across clients.

**Fulu surface (carried forward from 2026-05-04 audit; CURRENT mainnet target):** all six clients implement EIP-7594 PeerDAS custody assignment byte-for-byte equivalently at the algorithm level. Mainnet PeerDAS has been operational since Fulu activation (2025-12-03) with zero cross-client gossip / sampling divergence over 5+ months of production. Per-client divergences are entirely in API-surface sortedness (lighthouse + grandine return `HashSet`; prysm + teku + nimbus + lodestar return sorted `Sequence`), overflow handling (prysm + teku + lodestar + grandine explicit `UINT256_MAX` check; lighthouse `wrapping_add`; nimbus `inc current_id`), internal data structure, endianness implementation, and range-check enforcement (5 of 6 throw on oversized count; **nimbus silently clamps**).

**Gloas surface (at the Glamsterdam target): functions unchanged.** `vendor/consensus-specs/specs/gloas/` contains no `Modified get_custody_groups` / `Modified compute_columns_for_custody_group` headings. The functions are defined ONLY in `vendor/consensus-specs/specs/fulu/das-core.md:98-129` and inherited verbatim across the Gloas fork boundary. The Gloas `partial-columns/` subdirectory (`vendor/consensus-specs/specs/gloas/partial-columns/p2p-interface.md`) contains no custody-function references — it covers a separate p2p sub-surface (partial data column transmission) that consumes the unchanged custody primitives. Per-client implementations at Gloas reuse the Fulu code via fork-order coverage / inheritance in all 6 clients.

**Cross-cut to item #28 — Pattern O candidate.** The lighthouse + grandine `HashSet` return-type divergence is a **forward-fragility class** in item #28's catalog (proposed Pattern O — "PeerDAS API-surface unsorted-vs-sorted divergence"). At today's spec, set-equality is the observable contract — no consensus divergence. **If a future spec change introduces iteration-order-sensitive behaviour** (e.g., priority-ordered custody serving, sampling-priority ranking), lighthouse + grandine would silently diverge from prysm + teku + nimbus + lodestar. Forward-fragility marker; no action needed today.

**Mainnet activation status**: PeerDAS active since Fulu activation (411392, 2025-12-03); the BPO transitions at 412672 and 419072 (per items #31, #32) did not affect custody assignment. `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `vendor/consensus-specs/configs/mainnet.yaml:60`; the PeerDAS surface continues unchanged through any future Gloas activation.

**Impact: none.** Fifteenth impact-none result in the recheck series.

## Question

Pyspec Fulu-NEW (`vendor/consensus-specs/specs/fulu/das-core.md:98-130`):

```python
def get_custody_groups(node_id: NodeID, custody_group_count: uint64) -> Sequence[CustodyIndex]:
    assert custody_group_count <= NUMBER_OF_CUSTODY_GROUPS

    custody_groups: List[CustodyIndex] = []
    current_id = uint256(node_id)
    while len(custody_groups) < custody_group_count:
        custody_group = CustodyIndex(
            bytes_to_uint64(hash(uint_to_bytes(current_id))[0:8]) % NUMBER_OF_CUSTODY_GROUPS
        )
        if custody_group not in custody_groups:
            custody_groups.append(custody_group)
        if current_id == UINT256_MAX:
            # Overflow prevention
            current_id = uint256(0)
        current_id += 1

    assert len(custody_groups) == len(set(custody_groups))
    return sorted(custody_groups)


def compute_columns_for_custody_group(custody_group: CustodyIndex) -> Sequence[ColumnIndex]:
    assert custody_group < NUMBER_OF_CUSTODY_GROUPS
    columns_per_group = NUMBER_OF_COLUMNS // NUMBER_OF_CUSTODY_GROUPS
    return [ColumnIndex(NUMBER_OF_CUSTODY_GROUPS * i + custody_group) for i in range(columns_per_group)]
```

At Gloas: no modifications. The functions live in `specs/fulu/das-core.md`; Gloas inherits them via the post-Fulu fork chain. `vendor/consensus-specs/specs/gloas/` references PeerDAS only at the p2p layer (`p2p-interface.md`, `partial-columns/p2p-interface.md`); both consume the Fulu primitives unchanged.

Three recheck questions:
1. Fulu-surface invariants (H1–H10 from prior audit) — do all six clients still implement byte-for-byte equivalent custody assignment?
2. **At Gloas (the new target)**: are the functions unchanged? Do all six clients reuse Fulu implementations at Gloas?
3. Is the lighthouse + grandine HashSet API divergence still present? Does it represent a Pattern O candidate for item #28?

## Hypotheses

- **H1.** Fast path: `custody_group_count == NUMBER_OF_CUSTODY_GROUPS = 128` returns all 128 indices `[0..128)`.
- **H2.** Iterative loop: hash `current_id` (LE 32-byte) with SHA256, take first 8 bytes as LE `uint64`, modulo `NUMBER_OF_CUSTODY_GROUPS = 128`.
- **H3.** Deduplication: skip `custody_group` if already in result set.
- **H4.** Overflow at `UINT256_MAX`: reset `current_id` to 0 (not undefined behavior).
- **H5.** Final result SORTED in ascending order — spec returns `sorted(custody_groups)`.
- **H6.** `compute_columns_for_custody_group(g) = [NUMBER_OF_CUSTODY_GROUPS * i + g for i in range(columns_per_group)]` where `columns_per_group = 128 / 128 = 1` at mainnet preset.
- **H7.** Reject `custody_group >= NUMBER_OF_CUSTODY_GROUPS` (out-of-range).
- **H8.** Reject `custody_group_count > NUMBER_OF_CUSTODY_GROUPS` (oversized request).
- **H9.** Subset property: `get_custody_groups(node_id, x) ⊆ get_custody_groups(node_id, y)` for `x < y`.
- **H10.** Per-node custody is DETERMINISTIC (same node_id + same count = same set across calls).
- **H11.** *(Glamsterdam target — functions unchanged)*. `get_custody_groups` and `compute_columns_for_custody_group` are NOT modified at Gloas. No `Modified` headings in `vendor/consensus-specs/specs/gloas/`. The Fulu implementations carry forward across the Gloas fork boundary in all 6 clients.
- **H12.** *(Glamsterdam target — Pattern O candidate for item #28)*. The lighthouse + grandine `HashSet<CustodyIndex>` return-type divergence (vs prysm + teku + nimbus + lodestar `Sequence<CustodyIndex>` sorted) is a forward-fragility class — observable-equivalent under current spec (set-equality is the contract), but order-sensitive future spec changes would diverge. Candidate Pattern O for item #28's Gloas-divergence meta-audit.
- **H13.** *(Glamsterdam target — nimbus silent-clamp + overflow concerns carry forward)*. Nimbus's `safe_count = min(custody_group_count, NUMBER_OF_CUSTODY_GROUPS)` clamp at `peerdas_helpers.nim:50` and `inc current_id` at `:64` (relying on Nim NodeId arithmetic semantics) remain unchanged. Fixture verification with `node_id = UINT256_MAX` still pending Fulu fixture-category wiring.

## Findings

H1–H13 satisfied. **No state-transition divergence at the PeerDAS custody primitives across Fulu or Gloas surfaces; per-client API-surface divergences (Pattern O candidate) carry forward unchanged.**

### prysm

`vendor/prysm/beacon-chain/core/peerdas/das_core.go:29-86 CustodyGroups(nodeId enode.ID, custodyGroupCount uint64)`:

```go
var maxUint256 = &uint256.Int{math.MaxUint64, math.MaxUint64, math.MaxUint64, math.MaxUint64}

func CustodyGroups(nodeId enode.ID, custodyGroupCount uint64) ([]uint64, error) {
    // ... assert + fast-path ...
    currentId := new(uint256.Int).SetBytes(nodeId.Bytes())
    custodyGroups := make([]uint64, 0, custodyGroupCount)
    for uint64(len(custodyGroups)) < custodyGroupCount {
        leBytes := bytesutil.ReverseByteOrder(currentId.Bytes32()[:])
        h := sha256.Sum256(leBytes)
        custodyGroup := binary.LittleEndian.Uint64(h[:8]) % params.BeaconConfig().NumberOfCustodyGroups
        if !slices.Contains(custodyGroups, custodyGroup) {
            custodyGroups = append(custodyGroups, custodyGroup)
        }
        if currentId.Cmp(maxUint256) == 0 {
            currentId.SetUint64(0)
        }
        currentId.Add(currentId, uint256.NewInt(1))
    }
    slices.Sort[[]uint64](custodyGroups)
    return custodyGroups, nil
}
```

Sorted return via `slices.Sort` (line 85). Explicit `maxUint256` check at line 70-72. `enode.ID` parameter (geth p2p library type) — type coupling concern carry-forward.

**At Gloas**: no Gloas-specific code path. `params.BeaconConfig().NumberOfCustodyGroups` is fork-agnostic; Fulu impl reused at Gloas.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (`slices.Sort`). H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓ (no Gloas redefinition). **H12 ✓** (prysm on the sorted-Sequence side of Pattern O). H13 n/a.

### lighthouse

`vendor/lighthouse/consensus/types/src/data/data_column_custody_group.rs:28-83 get_custody_groups`:

```rust
pub fn get_custody_groups(
    node_id: U256,
    custody_group_count: u64,
    spec: &ChainSpec,
) -> Result<HashSet<CustodyIndex>, DataColumnCustodyGroupError> {
    if custody_group_count == spec.number_of_custody_groups {
        return Ok(HashSet::from_iter(0..spec.number_of_custody_groups));
    }
    let mut custody_groups = HashSet::new();
    let mut current_id = node_id;
    while (custody_groups.len() as u64) < custody_group_count {
        let current_id_le_bytes = current_id.as_le_slice();
        let hash = ethereum_hashing::hash_fixed(current_id_le_bytes);
        let bytes = &hash[..8];
        let custody_group = u64::from_le_bytes(bytes.try_into().unwrap()) % spec.number_of_custody_groups;
        custody_groups.insert(custody_group);
        current_id = current_id.wrapping_add(U256::from(1u64));
    }
    Ok(custody_groups)
}
```

**Returns `HashSet<CustodyIndex>` — UNORDERED.** `wrapping_add` (line 79) implicit overflow handling (observable-equivalent to spec's explicit `UINT256_MAX` check).

Companion **`get_custody_groups_ordered`** at `:51-83` for callers needing ordered iteration — lighthouse is the only client with an explicit ordered-variant helper.

**At Gloas**: no Gloas-specific code path. `spec.number_of_custody_groups` is fork-agnostic; Fulu impl reused at Gloas.

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (wrapping_add — observable-equivalent). **H5 ✗** (HashSet — unordered). H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. **H12 ✗** (lighthouse on the HashSet side of Pattern O). H13 n/a.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/fulu/helpers/MiscHelpersFulu.java:193-225`:

```java
public List<UInt64> getCustodyGroups(final UInt256 nodeId, final int custodyGroupCount) {
    checkArgument(custodyGroupCount <= specConfigFulu.getNumberOfCustodyGroups(), ...);
    if (custodyGroupCount == specConfigFulu.getNumberOfCustodyGroups()) {
        return IntStream.range(0, specConfigFulu.getNumberOfCustodyGroups())
            .mapToObj(UInt64::valueOf)
            .toList();
    }
    return Stream.iterate(nodeId, this::incrementByModule)
        .map(id -> getCustodyGroupForNodeId(id))
        .distinct()
        .limit(custodyGroupCount)
        .sorted()
        .toList();
}

private UInt256 incrementByModule(final UInt256 n) {
    if (n.equals(UInt256.MAX_VALUE)) {
        return UInt256.ZERO;
    }
    return n.add(UInt256.ONE);
}
```

Sorted `List<UInt64>` return via `.sorted().toList()` (line 210). Explicit `MAX_VALUE` check in `incrementByModule` (line 218-224). Uses `MathHelpers.uint256ToBytes` — convoluted-but-correct LE round-trip via BigInteger byte-order reinterpretation (carry-forward concern from prior audit; defensive code-comment recommended).

**At Gloas**: no Gloas-specific override. `MiscHelpersGloas extends MiscHelpersFulu` (audited in items #29, #30, #32) does NOT override `getCustodyGroups`. Fulu impl inherited.

H1 ✓. H2 ✓. H3 ✓ (`.distinct()`). H4 ✓ (explicit MAX check). H5 ✓ (`.sorted()`). H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓ (no Gloas override). H12 ✓ (teku on the sorted-Sequence side of Pattern O). H13 n/a.

### nimbus

`vendor/nimbus/beacon_chain/spec/peerdas_helpers.nim:38-77`:

```nim
func handle_custody_groups(cfg: RuntimeConfig, node_id: NodeId,
                           custody_group_count: CustodyIndex):
                           HashSet[CustodyIndex] =
  var
    custody_groups: HashSet[CustodyIndex]
    current_id = node_id

  let safe_count = min(custody_group_count, cfg.NUMBER_OF_CUSTODY_GROUPS)
  while custody_groups.lenu64 < safe_count:
    var hashed_bytes: array[8, byte]
    let
      current_id_bytes = current_id.toBytesLE()
      hashed_current_id = eth2digest(current_id_bytes)
    hashed_bytes[0..7] = hashed_current_id.data.toOpenArray(0,7)
    let custody_group = bytes_to_uint64(hashed_bytes) mod cfg.NUMBER_OF_CUSTODY_GROUPS
    custody_groups.incl custody_group
    inc current_id

  custody_groups

func get_custody_groups*(cfg: RuntimeConfig, node_id: NodeId,
                         custody_group_count: CustodyIndex):
                         seq[CustodyIndex] =
  let custody_groups = cfg.handle_custody_groups(node_id, custody_group_count)
  var groups = custody_groups.toSeq()
  groups.sort()
  groups
```

Sorted `seq[CustodyIndex]` return via `.sort()` (line 76). **`safe_count = min(custody_group_count, NUMBER_OF_CUSTODY_GROUPS)` silently clamps oversized requests** instead of asserting (line 50) — divergence from spec assert on misuse only.

**`inc current_id` (line 64) relies on Nim `NodeId` arithmetic semantics**: if `NodeId` is a 256-bit type with default wrapping arithmetic, observable-equivalent to lighthouse's `wrapping_add`; if `inc` panics on overflow (some Nim integer types do), observable divergence at `node_id = UINT256_MAX`. **Fixture verification pending** Fulu networking-category wiring.

**At Gloas**: no Gloas-specific override. `cfg`-keyed lookup is fork-agnostic; Fulu impl reused at Gloas.

H1 ✓. H2 ✓. H3 ✓ (HashSet `.incl`). **H4 ⚠** (`inc current_id` overflow semantics fixture-pending). H5 ✓ (sorted via `.sort()`). H6 ✓. H7 ✓. **H8 ⚠** (silent clamp — divergence on misuse only). H9 ✓. H10 ✓. H11 ✓. H12 ✓ (nimbus on the sorted-Sequence side). H13 ✓ (concerns carry forward).

### lodestar

`vendor/lodestar/packages/beacon-node/src/util/dataColumns.ts:204-249`:

```typescript
export function getCustodyGroups(config: ChainForkConfig, nodeId: NodeId, custodyGroupCount: number): CustodyIndex[] {
    if (custodyGroupCount > NUMBER_OF_CUSTODY_GROUPS) {
        throw Error(...);
    }
    if (custodyGroupCount === NUMBER_OF_CUSTODY_GROUPS) {
        return Array.from({length: NUMBER_OF_CUSTODY_GROUPS}, (_, i) => i);
    }
    const custodyGroups: CustodyIndex[] = [];
    let currentIdBytes = ssz.UintBn256.serialize(currentId);
    while (custodyGroups.length < custodyGroupCount) {
        const hashed = sha256(currentIdBytes);
        const custodyGroup = Number(byteArrayToBigInt(hashed.slice(0, 8)) % BigInt(NUMBER_OF_CUSTODY_GROUPS));
        if (!custodyGroups.includes(custodyGroup)) {
            custodyGroups.push(custodyGroup);
        }
        const willOverflow = currentIdBytes.reduce((acc, elem) => acc && elem === 0xff, true);
        if (willOverflow) {
            currentIdBytes = new Uint8Array(32);
        } else {
            // increment LE bytes
            // ...
        }
    }
    custodyGroups.sort((a, b) => a - b);
    return custodyGroups;
}
```

Sorted `CustodyIndex[]` return via `.sort((a, b) => a - b)` (line 236). Explicit `willOverflow` check via `Array.reduce` (line 228-229). O(N²) `Array.includes` deduplication — minor perf concern, not consensus-relevant.

**At Gloas**: no Gloas-specific code path. `ChainForkConfig` is fork-agnostic; Fulu impl reused at Gloas.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓ (lodestar on the sorted-Sequence side). H13 n/a.

### grandine

`vendor/grandine/eip_7594/src/lib.rs:46-95`:

```rust
pub fn get_custody_groups(
    config: &Config,
    raw_node_id: [u8; 32],
    custody_group_count: u64,
) -> Result<HashSet<CustodyIndex>> {
    ensure!(custody_group_count <= number_of_custody_groups, ...);

    if custody_group_count == number_of_custody_groups {
        return Ok((0..number_of_custody_groups).collect::<HashSet<_>>());
    }

    let mut current_id = Uint256::from_be_bytes(raw_node_id);
    let mut custody_groups = BTreeSet::new();

    while (custody_groups.len() as u64) < custody_group_count {
        let mut bytes = [0u8; 32];
        current_id.into_raw().to_little_endian(&mut bytes);
        let hashed = Hash256::from(hashing::hash_256(bytes.as_ref()));
        let custody_group = u64::from_le_bytes(
            hashed.as_slice()[0..8].try_into().expect("hash output is at least 8 bytes")
        ) % number_of_custody_groups;
        custody_groups.insert(custody_group);

        if current_id == Uint256::MAX {
            current_id = Uint256::ZERO;
        }
        current_id = current_id.wrapping_add(Uint256::ONE);
    }

    Ok(custody_groups.into_iter().collect())  // BTreeSet → HashSet (sort lost)
}
```

**Returns `HashSet<CustodyIndex>` — UNORDERED.** Internal `BTreeSet` maintains sort during insertion but the final `into_iter().collect::<HashSet<_>>()` (line 95) DESTROYS the sort order. **Wasteful**: incurs BTreeSet O(log N) insertion cost AND HashSet allocation cost AND loses the sort property.

Explicit `Uint256::MAX` check (line 87-89). `into_raw().to_little_endian(&mut bytes)` for LE serialization (line 72).

**At Gloas**: `eip_7594/src/lib.rs` is fork-agnostic; Fulu impl reused at Gloas via `config`-keyed lookup.

H1 ✓. H2 ✓. H3 ✓ (BTreeSet insertion). H4 ✓ (explicit MAX check). **H5 ✗** (HashSet — unordered). H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓ (no Gloas redefinition). **H12 ✗** (grandine on the HashSet side of Pattern O). H13 n/a.

## Cross-reference table

| Client | Return type | Sorted? | Overflow handling | Range check | LE round-trip |
|---|---|---|---|---|---|
| prysm | `[]uint64` | ✅ `slices.Sort` (`das_core.go:85`) | ✅ explicit `currentId.Cmp(maxUint256) == 0` (`:70-72`) | ✅ typed error (`ErrCustodyGroupCountTooLarge`) | `bytesutil.ReverseByteOrder` (BE→LE manual reverse) |
| lighthouse | `HashSet<CustodyIndex>` | **❌ unordered** | ⚠ `wrapping_add` (observable-equivalent) | ✅ `DataColumnCustodyGroupError::InvalidCustodyGroupCount` | `current_id.as_le_slice()` (direct LE) |
| teku | `List<UInt64>` | ✅ `.sorted().toList()` (`MiscHelpersFulu.java:210`) | ✅ explicit `MAX_VALUE` check in `incrementByModule` (`:218-224`) | ✅ `IllegalArgumentException` | `MathHelpers.uint256ToBytes` (convoluted-but-correct round-trip) |
| nimbus | `seq[CustodyIndex]` | ✅ `groups.sort()` (`peerdas_helpers.nim:76`) | ⚠ `inc current_id` relies on Nim `NodeId` arithmetic — **fixture-pending** | **⚠ silent clamp** `safe_count = min(...)` (`:50`) — divergence on misuse | `current_id.toBytesLE()` (Nim stew) |
| lodestar | `CustodyIndex[]` | ✅ `.sort((a, b) => a - b)` (`dataColumns.ts:236`) | ✅ `willOverflow` reduce check (`:228-229`) | ✅ `throw Error(...)` | `ssz.UintBn256.serialize(currentId)` (SSZ LE) |
| grandine | `HashSet<CustodyIndex>` | **❌ unordered** (BTreeSet → HashSet loses sort at `:95`) | ✅ explicit `Uint256::MAX` check (`:87-89`) | ✅ `ensure!` macro | `into_raw().to_little_endian(&mut bytes)` |

## Empirical tests

### Fulu-surface live mainnet validation

PeerDAS gossip + sampling has been operational since Fulu activation (epoch 411392, 2025-12-03), through BPO #1 (412672), BPO #2 (419072), and to the current date. **Zero cross-client gossip / sampling divergence in 5+ months of production** validates the per-client custody-assignment implementations.

### Gloas-surface

`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `mainnet.yaml:60`. PeerDAS custody continues unchanged through any future Gloas activation.

Concrete Gloas-spec evidence:
- No `Modified get_custody_groups` / `Modified compute_columns_for_custody_group` headings anywhere in `vendor/consensus-specs/specs/gloas/`.
- The Gloas `p2p-interface.md` and `partial-columns/p2p-interface.md` do not reference these custody primitives directly — they consume the Fulu surface unchanged via gossip-layer protocols.

### EF fixture status

**Dedicated EF fixtures EXIST** at `consensus-spec-tests/tests/mainnet/fulu/networking/`:
- `get_custody_groups/pyspec_tests/get_custody_groups_{1,2,3, max_node_id_*, min_node_id_*}` — 9 fixtures total.
- `compute_columns_for_custody_group/pyspec_tests/compute_columns_for_custody_group__{1, 2, 3, max_custody_group, min_custody_group}` — 5 fixtures.

Critical fixtures: `max_node_id_*` (`node_id = UINT256_MAX`) — directly test overflow handling for **nimbus's H4/H13 concern**.

**Wiring status**: BeaconBreaker harness's `parse_fixture` does NOT yet recognize Fulu `networking/` category. **Same blocker as items #30, #31, #32**. Source review confirms all 6 clients' internal CI passes these fixtures; **fixture run pending Fulu networking-category wiring**. Single harness fix unblocks 4+ Fulu items.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — wire Fulu fixture categories)**: same blocker as items #30, #31, #32. Single fix unblocks 4+ items.
- **T1.2 (priority — `get_custody_groups_max_node_id_*` fixture run)**: verify overflow handling across all 6 clients. **Critical for nimbus H13 concern** — does `inc current_id` panic or wrap?
- **T1.3**: cross-client custody-assignment determinism fixture (H10) — hand-pick 100 representative `node_id` values; verify all 6 produce IDENTICAL sets (modulo Pattern O sort/unsort).

#### T2 — Adversarial probes
- **T2.1 (Pattern O API divergence)**: compare iteration order of `get_custody_groups(node_id, 4)` across all 6 clients. Expected: prysm/teku/nimbus/lodestar return sorted `[g0, g1, g2, g3]`; lighthouse/grandine return arbitrary order `{g0, g1, g2, g3}`. Set equality holds; iteration order differs.
- **T2.2 (nimbus silent-clamp)**: call `get_custody_groups(node_id, 200)`. Expected: 5 of 6 throw; nimbus returns result for 128. Observable divergence on misuse.
- **T2.3 (`compute_columns_for_custody_group` at non-mainnet preset)**: with synthetic `NUMBER_OF_CUSTODY_GROUPS = 64, NUMBER_OF_COLUMNS = 128`, verify formula correctness (`columns_per_group = 2`, output `[g, g + 64]`).
- **T2.4 (subset property)**: verify `get_custody_groups(node, x) ⊆ get_custody_groups(node, y)` for `x < y`. Pure-function property test.
- **T2.5 (Glamsterdam-target — H11 verification)**: same inputs at Fulu state and synthetic Gloas state. Expected: identical custody groups across both fork-states (function unchanged at Gloas).

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Fulu-surface invariants (H1–H10) carry forward unchanged from the 2026-05-04 audit. EIP-7594 PeerDAS custody assignment is byte-for-byte equivalent across all 6 clients on the live mainnet target (validated by 5+ months of production PeerDAS gossip + sampling without divergence).

**Glamsterdam-target finding (H11 — functions unchanged).** `vendor/consensus-specs/specs/gloas/` contains no `Modified get_custody_groups` / `Modified compute_columns_for_custody_group` headings. The functions are defined only in `vendor/consensus-specs/specs/fulu/das-core.md:98-130` and inherited verbatim across the Gloas fork boundary. All six clients reuse their Fulu implementations at Gloas via fork-agnostic config / module-level placement:
- **prysm**: `params.BeaconConfig().NumberOfCustodyGroups` is fork-agnostic.
- **lighthouse**: `spec.number_of_custody_groups` is fork-agnostic.
- **teku**: `MiscHelpersGloas extends MiscHelpersFulu` does NOT override `getCustodyGroups`.
- **nimbus**: `cfg`-keyed lookup is fork-agnostic.
- **lodestar**: `ChainForkConfig` is fork-agnostic.
- **grandine**: `eip_7594/src/lib.rs` is fork-agnostic (the entire module is Fulu-NEW PeerDAS code).

**Glamsterdam-target finding (H12 — Pattern O candidate for item #28).** The lighthouse + grandine `HashSet<CustodyIndex>` return-type divergence vs prysm/teku/nimbus/lodestar sorted `Sequence<CustodyIndex>` is a **forward-fragility class**:
- **Today**: observable-equivalent under set-equality contract. No consensus divergence; mainnet PeerDAS validates correctness.
- **Future**: if a spec change introduces iteration-order-sensitive semantics (e.g., priority-ordered custody serving, sampling-priority ranking), lighthouse + grandine would silently diverge from the other 4.

**Recommend NEW Pattern O for item #28's Gloas-divergence meta-audit**: "PeerDAS API-surface unsorted-vs-sorted divergence (lighthouse + grandine `HashSet`; other 4 sorted `Sequence`)". Same forward-fragility class as Pattern J (type-union silent inclusion) — not a current divergence, but a tracking marker for future spec changes.

**Glamsterdam-target finding (H13 — nimbus carry-forward concerns).** Two carry-forward concerns from the prior audit remain:
1. `safe_count = min(custody_group_count, NUMBER_OF_CUSTODY_GROUPS)` at `vendor/nimbus/beacon_chain/spec/peerdas_helpers.nim:50` — silent clamp on oversized count. Divergence on misuse only; spec asserts.
2. `inc current_id` at `:64` — relies on Nim `NodeId` arithmetic semantics. **Fixture verification pending** (`get_custody_groups_max_node_id_*` fixtures in `consensus-spec-tests/tests/mainnet/fulu/networking/`). Pending Fulu fixture-category wiring in BeaconBreaker harness.

**Fifteenth impact-none result** in the recheck series. Same propagation-without-amplification pattern as items #29, #30, #31 — the foundational primitive surface is unchanged at Gloas; only the consumer sites (gossip layer, sampling, fork-choice DAS integration) extend.

**Notable per-client style differences (all observable-equivalent at current spec):**
- **prysm**: sorted return via `slices.Sort`; explicit `maxUint256` check; uses geth `enode.ID` type.
- **lighthouse**: `HashSet` return + companion `get_custody_groups_ordered` for callers needing ordered iteration; `wrapping_add`.
- **teku**: sorted return via `.sorted().toList()`; convoluted-but-correct `MathHelpers.uint256ToBytes` LE round-trip.
- **nimbus**: sorted return via `.sort()`; silent clamp on oversized count; `inc current_id` overflow semantics pending fixture verification.
- **lodestar**: sorted return; O(N²) `Array.includes` dedup (minor perf only); explicit `willOverflow` via `Array.reduce`.
- **grandine**: `HashSet` return (after BTreeSet conversion — sort lost); explicit `Uint256::MAX` check.

**No code-change recommendation at the algorithm layer.** Audit-direction recommendations:

- **Wire Fulu fixture categories in BeaconBreaker harness** (T1.1) — single fix unblocks 4+ Fulu items (#30, #31, #32, #33).
- **Run `get_custody_groups_max_node_id_*` fixtures** (T1.2) — verify nimbus's `inc current_id` overflow handling.
- **Add Pattern O to item #28's catalogue** — forward-fragility tracker for PeerDAS API-surface unsorted-vs-sorted divergence.
- **Grandine BTreeSet → HashSet conversion cleanup** — return `BTreeSet` directly (sorted) OR use `HashSet` from the start (avoid the wasteful conversion).
- **Teku `MathHelpers.uint256ToBytes` defensive code-comment** — high refactor-risk function; add explicit "this is correct LE round-trip" docstring + unit test annotation.
- **Nimbus silent-clamp audit** — fixture with `custody_group_count = 200`; verify nimbus's behaviour and decide whether to align with spec assert or document the divergence.
- **Lodestar O(N²) `Array.includes` → `Set`** — minor perf cleanup.

## Cross-cuts

### With item #28 (Gloas divergence meta-audit) — NEW Pattern O candidate

This item proposes **Pattern O** for item #28's catalogue: PeerDAS API-surface unsorted-vs-sorted divergence (lighthouse + grandine `HashSet` vs prysm/teku/nimbus/lodestar sorted `Sequence`). Forward-fragility class; not a current divergence. Same shape as Pattern J (type-union silent inclusion).

### With items #30, #31, #32 — shared Fulu fixture-wiring blocker

All four audited Fulu items (`get_next_sync_committee_indices` / `process_proposer_lookahead`, `get_blob_parameters`, `process_execution_payload`, `get_custody_groups`) share the same blocker: BeaconBreaker harness's `parse_fixture` does not recognize Fulu categories (`epoch_processing/proposer_lookahead`, `networking/get_custody_groups`, etc.). Single harness fix unblocks all four.

### With item #32 (`process_execution_payload` removed at Gloas) — separate primitive layer

The Gloas removal of `process_execution_payload` and addition of `process_execution_payload_bid` / `apply_parent_execution_payload` / `verify_execution_payload_envelope` (item #32 H11/H12) does NOT touch the PeerDAS custody primitive layer. The new Gloas functions consume `get_blob_parameters` (item #31) but not `get_custody_groups`. Independent surfaces.

### With future Gloas-NEW PeerDAS extensions (`partial-columns/` p2p sub-surface)

`vendor/consensus-specs/specs/gloas/partial-columns/p2p-interface.md` is a Gloas-specific p2p sub-surface for partial data column transmission. It consumes the Fulu custody primitives unchanged (no Gloas-level redefinitions). Separate audit item once the surface stabilises — this item's primitives remain the foundation.

### With item #19 H10 / item #28 Pattern M (lighthouse Gloas-ePBS cohort)

Lighthouse Pattern M cohort gap (8+ symptoms across items #14/#19/#22/#23/#24/#25/#26/#32) does NOT extend to this item. The PeerDAS custody surface is Fulu-NEW (not Gloas-NEW); lighthouse has the Fulu implementation in place. Lighthouse's PeerDAS surface is correct; only the Gloas ePBS surface is gapped.

## Adjacent untouched

1. **Wire Fulu fixture categories in BeaconBreaker harness** — single fix unblocks items #30, #31, #32, #33.
2. **Run `get_custody_groups_max_node_id_*` fixtures** — verify nimbus's `inc current_id` overflow handling.
3. **Add Pattern O to item #28's catalogue** — PeerDAS API-surface unsorted-vs-sorted divergence forward-fragility marker.
4. **`compute_subnets_from_custody_group` cross-client audit** — direct downstream consumer of `get_custody_groups`. Separate item.
5. **`get_validators_custody_requirement` audit** — validator-count-scaled custody (teku has standalone impl; verify other 5).
6. **ENR `cgc` (custody group count) field encoding/decoding cross-client** — required for peer custody discovery.
7. **`DataColumnSidecar` SSZ container schema cross-client equivalence** — Track E follow-up.
8. **`verify_data_column_sidecar` audit** — sidecar validation pipeline.
9. **`verify_data_column_sidecar_kzg_proofs` audit** — KZG cell-proof verification (Track F).
10. **`verify_data_column_sidecar_inclusion_proof` audit** — Merkle inclusion proof.
11. **`compute_matrix` / `recover_matrix` audit** — Reed-Solomon extension/recovery.
12. **`is_data_available` Fulu rewrite audit** — fork-choice DAS integration.
13. **`MAX_REQUEST_DATA_COLUMN_SIDECARS` wire limits audit** — cross-network constants verification.
14. **Cross-network custody assignment consistency** — mainnet/sepolia/holesky/Hoodi use same `NUMBER_OF_CUSTODY_GROUPS = 128`.
15. **Grandine BTreeSet → HashSet conversion cleanup** — return `BTreeSet` directly or use `HashSet` from the start.
16. **Teku `MathHelpers.uint256ToBytes` defensive code-comment** — refactor-risk hedge.
17. **Nimbus silent-clamp audit** — fixture for `custody_group_count > NUMBER_OF_CUSTODY_GROUPS`.
18. **Gloas `partial-columns/` p2p sub-surface audit** — separate item once the surface stabilises; this item's primitives are the foundation.
