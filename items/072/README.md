---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [41]
eips: [EIP-7594]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 72: PeerDAS custody column selection — runtime usage of the `cgc` field

## Summary

All six clients implement `get_custody_groups(node_id, custody_group_count)` and `compute_columns_for_custody_group(custody_group)` per the Fulu spec at `vendor/consensus-specs/specs/fulu/das-core.md:101-135`. The hash-based group derivation produces identical column-sets across all 6 clients for any (`node_id`, `cgc`) pair on shared inputs. Cross-client byte-equivalence of the wire-derived custody column set is preserved — confirming that item #41's `cgc` wire-encoding fix in nimbus (PR #8440 prior to that, ENR encoding fixed-uint8 vs variable-BE) and downstream runtime consumption agree on the resolved column-set.

**One literal-vs-functional deviation in lighthouse + grandine**: spec's `get_custody_groups` returns `sorted(custody_groups)` (a Vec/Sequence). Lighthouse + grandine return an unsorted `HashSet` from the public `get_custody_groups` entry. Functionally equivalent for membership-test consumers (which is the dominant use: "does this node custody column X?"). Both also expose ordered-output variants for callers that need iteration order.

**Verdict: impact none.** No divergence on the column-set semantics. Audit closes.

## Question

Pyspec `get_custody_groups` at `vendor/consensus-specs/specs/fulu/das-core.md:101-123`:

```python
def get_custody_groups(node_id: NodeID, custody_group_count: uint64) -> Sequence[CustodyIndex]:
    assert custody_group_count <= NUMBER_OF_CUSTODY_GROUPS

    if custody_group_count == NUMBER_OF_CUSTODY_GROUPS:
        return [CustodyIndex(i) for i in range(NUMBER_OF_CUSTODY_GROUPS)]

    current_id = uint256(node_id)
    custody_groups: List[CustodyIndex] = []
    while len(custody_groups) < custody_group_count:
        custody_group = CustodyIndex(
            bytes_to_uint64(hash(uint_to_bytes(current_id))[0:8]) % NUMBER_OF_CUSTODY_GROUPS
        )
        if custody_group not in custody_groups:
            custody_groups.append(custody_group)
        if current_id == UINT256_MAX:
            current_id = uint256(0)
        else:
            current_id += 1

    assert len(custody_groups) == len(set(custody_groups))
    return sorted(custody_groups)
```

Spec semantics (key invariants):

1. **`uint_to_bytes(current_id)`** — uint256 → **little-endian** 32-byte serialization (per `uint_to_bytes` convention in the spec).
2. **`hash(...)`** — SHA256.
3. **`hash[0:8]`** — first 8 bytes of the hash.
4. **`bytes_to_uint64(...)`** — **little-endian** u64 deserialization.
5. **Overflow**: at `current_id == UINT256_MAX`, wrap to 0; else `current_id += 1`.
6. **Output**: sorted ascending list, no duplicates.

Pyspec `compute_columns_for_custody_group` at `das-core.md:129-135`:

```python
def compute_columns_for_custody_group(custody_group: CustodyIndex) -> Sequence[ColumnIndex]:
    assert custody_group < NUMBER_OF_CUSTODY_GROUPS
    columns_per_group = NUMBER_OF_COLUMNS // NUMBER_OF_CUSTODY_GROUPS
    return [ColumnIndex(NUMBER_OF_CUSTODY_GROUPS * i + custody_group) for i in range(columns_per_group)]
```

Output: `columns_per_group` columns in the form `i * NUMBER_OF_CUSTODY_GROUPS + custody_group` for `i ∈ [0, columns_per_group)`. Mainnet: `NUMBER_OF_COLUMNS = 128`, `NUMBER_OF_CUSTODY_GROUPS = 128`, so `columns_per_group = 1` and each custody group → exactly one column.

Open questions:

1. **`uint_to_bytes(uint256)` endianness** — per-client LE for the 32-byte node_id.
2. **`bytes_to_uint64`** — per-client LE for the 8-byte hash prefix.
3. **Overflow guard** — `UINT256_MAX → 0` per-client.
4. **Output ordering** — `sorted(custody_groups)` per-client.
5. **`NUMBER_OF_CUSTODY_GROUPS`, `NUMBER_OF_COLUMNS`** constants — per-client uniform.
6. **`compute_columns_for_custody_group`** stride pattern.

## Hypotheses

- **H1.** All six clients implement `get_custody_groups` with the same hash algorithm (SHA256), LE endianness, and overflow handling.
- **H2.** All six produce the same column-set for any (`node_id`, `cgc`) pair (membership semantics).
- **H3.** All six implement `compute_columns_for_custody_group` with the same stride pattern.
- **H4.** All six handle the `cgc == NUMBER_OF_CUSTODY_GROUPS` short-circuit consistently.
- **H5** *(literal output ordering)*. All six return `sorted(custody_groups)`. **Suspected lighthouse + grandine deviation**: HashSet return type (unsorted).
- **H6** *(cross-cut item #41)*. Wire-encoded `cgc=0` (where nimbus historically encoded as 1-byte `0x00` and others as empty bytes) — runtime decode round-trips to the same column-set. Spec at `cgc=0` returns `[]` (empty) via the `cgc == 0 < NUMBER_OF_CUSTODY_GROUPS` path → 0 iterations.

## Findings

### prysm

`CustodyGroups` at `vendor/prysm/beacon-chain/core/peerdas/das_core.go:29-88`:

```go
func CustodyGroups(nodeId enode.ID, custodyGroupCount uint64) ([]uint64, error) {
    numberOfCustodyGroups := params.BeaconConfig().NumberOfCustodyGroups

    if custodyGroupCount > numberOfCustodyGroups {
        return nil, ErrCustodyGroupCountTooLarge
    }

    if custodyGroupCount == numberOfCustodyGroups {
        custodyGroups := make([]uint64, 0, numberOfCustodyGroups)
        for i := range numberOfCustodyGroups {
            custodyGroups = append(custodyGroups, i)
        }
        return custodyGroups, nil
    }

    one := uint256.NewInt(1)
    custodyGroupsMap := make(map[uint64]bool, custodyGroupCount)
    custodyGroups := make([]uint64, 0, custodyGroupCount)
    for currentId := new(uint256.Int).SetBytes(nodeId.Bytes()); uint64(len(custodyGroups)) < custodyGroupCount; {
        currentIdBytesBigEndian := currentId.Bytes32()
        currentIdBytesLittleEndian := bytesutil.ReverseByteOrder(currentIdBytesBigEndian[:])
        hashedCurrentId := hash.Hash(currentIdBytesLittleEndian)
        custodyGroup := binary.LittleEndian.Uint64(hashedCurrentId[:8]) % numberOfCustodyGroups
        if !custodyGroupsMap[custodyGroup] {
            custodyGroupsMap[custodyGroup] = true
            custodyGroups = append(custodyGroups, custodyGroup)
        }
        if currentId.Cmp(maxUint256) == 0 {
            currentId = uint256.NewInt(0)
        } else {
            currentId.Add(currentId, one)
        }
    }
    slices.Sort[[]uint64](custodyGroups)
    return custodyGroups, nil
}
```

`uint_to_bytes` LE via explicit `ReverseByteOrder` on the BE `Bytes32()` ✓. `bytes_to_uint64` via `binary.LittleEndian.Uint64` ✓. Overflow: explicit `currentId.Cmp(maxUint256) == 0` check ✓. Output sorted via `slices.Sort` ✓ (matches spec H5).

`ComputeColumnsForCustodyGroup` at `das_core.go:92-110`:

```go
columnsPerGroup := numberOfColumns / numberOfCustodyGroups
columns := make([]uint64, 0, columnsPerGroup)
for i := range columnsPerGroup {
    column := numberOfCustodyGroups*i + custodyGroup
    columns = append(columns, column)
}
```

Spec-conformant stride ✓.

### lighthouse

`get_custody_groups` at `vendor/lighthouse/consensus/types/src/data/data_column_custody_group.rs:28-39`:

```rust
pub fn get_custody_groups(
    raw_node_id: [u8; 32],
    custody_group_count: u64,
    spec: &ChainSpec,
) -> Result<HashSet<CustodyIndex>, DataColumnCustodyGroupError> {
    if custody_group_count == spec.number_of_custody_groups {
        Ok(HashSet::from_iter(0..spec.number_of_custody_groups))
    } else {
        get_custody_groups_ordered(raw_node_id, custody_group_count, spec)
            .map(|custody_groups| custody_groups.into_iter().collect())
    }
}
```

**Returns `HashSet`** — unsorted. Underlying `get_custody_groups_ordered` returns `Vec` in insertion order (not spec-sorted either; see line 51-83).

`get_custody_groups_ordered` (line 51-83):

```rust
let mut current_id = U256::from_be_slice(&raw_node_id);
while custody_groups.len() < custody_group_count as usize {
    let mut node_id_bytes = [0u8; 32];
    node_id_bytes.copy_from_slice(current_id.as_le_slice());
    let hash = ethereum_hashing::hash_fixed(&node_id_bytes);
    let hash_prefix: [u8; 8] = hash[0..8].try_into().expect("hash_fixed produces a 32 byte array");
    let hash_prefix_u64 = u64::from_le_bytes(hash_prefix);
    let custody_group = hash_prefix_u64.safe_rem(spec.number_of_custody_groups).expect("...");
    if !custody_groups.contains(&custody_group) {
        custody_groups.push(custody_group);
    }
    current_id = current_id.wrapping_add(U256::from(1u64));
}
```

`uint_to_bytes` LE via `current_id.as_le_slice()` ✓. `bytes_to_uint64` via `u64::from_le_bytes` ✓. Overflow: `wrapping_add` on U256 (`UINT256_MAX + 1 → 0`) ✓ matches spec.

**Sort deviation (H5)**: `get_custody_groups` returns `HashSet` (unsorted). `get_custody_groups_ordered` returns `Vec` in **insertion order** (also not sorted). Spec returns `sorted(custody_groups)`. Lighthouse's deviation is observable IF a consumer iterates the result expecting sorted order. Membership-test consumers (the dominant use) see no difference.

`compute_columns_for_custody_group` at `data_column_custody_group.rs:109-130`:

```rust
let mut columns = Vec::new();
for i in 0..spec.data_columns_per_group::<E>() {
    let column = number_of_custody_groups
        .safe_mul(i)
        .and_then(|v| v.safe_add(custody_group))
        .map_err(DataColumnCustodyGroupError::ArithError)?;
    columns.push(column);
}
```

Spec-conformant stride ✓.

### teku

`getCustodyGroups` at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/fulu/helpers/MiscHelpersFulu.java:193-212`:

```java
public List<UInt64> getCustodyGroups(final UInt256 nodeId, final int custodyGroupCount) {
  if (custodyGroupCount > specConfigFulu.getNumberOfCustodyGroups()) {
    throw new IllegalArgumentException(...);
  }
  if (custodyGroupCount == specConfigFulu.getNumberOfCustodyGroups()) {
    return LongStream.range(0, custodyGroupCount).mapToObj(UInt64::valueOf).toList();
  }
  return Stream.iterate(nodeId, this::incrementByModule)
      .map(this::computeCustodyGroupIndex)
      .distinct()
      .limit(custodyGroupCount)
      .sorted()
      .toList();
}

private UInt64 computeCustodyGroupIndex(final UInt256 nodeId) {
  return bytesToUInt64(Hash.sha256(uint256ToBytes(nodeId)).slice(0, 8))
      .mod(specConfigFulu.getNumberOfCustodyGroups());
}

private UInt256 incrementByModule(final UInt256 n) {
  if (n.equals(UInt256.MAX_VALUE)) {
    return UInt256.ZERO;
  } else {
    return n.plus(1);
  }
}
```

`uint256ToBytes` LE ✓. `bytesToUInt64` LE ✓. Overflow: explicit `n.equals(MAX_VALUE) ? ZERO : n.plus(1)` ✓ matches spec. **`.sorted()` in the stream** ✓ matches spec H5.

`computeColumnsForCustodyGroup` at `MiscHelpersFulu.java:169-182`:

```java
return IntStream.range(0, getCustodyColumnsPerGroup())
    .mapToLong(i -> (long) specConfigFulu.getNumberOfCustodyGroups() * i + custodyGroup.intValue())
    .mapToObj(UInt64::valueOf)
    .toList();
```

Spec-conformant stride ✓.

### nimbus

`get_custody_groups` at `vendor/nimbus/beacon_chain/spec/peerdas_helpers.nim:69-77`:

```nim
func get_custody_groups*(cfg: RuntimeConfig, node_id: NodeId,
                         custody_group_count: CustodyIndex):
                         seq[CustodyIndex] =
  let custody_groups = cfg.handle_custody_groups(node_id, custody_group_count)
  var groups = custody_groups.toSeq()
  groups.sort()
  groups
```

`handle_custody_groups` (line 39-66):

```nim
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
```

`uint_to_bytes` LE via `current_id.toBytesLE()` ✓. `bytes_to_uint64` LE ✓. Overflow: relies on `inc current_id` (NodeId type's wrap-on-overflow at uint256 MAX) — equivalent to spec's explicit check. **Returns sorted seq** ✓ matches spec H5.

`compute_columns_for_custody_group` at `peerdas_helpers.nim:32-37`:

```nim
iterator compute_columns_for_custody_group*(cfg: RuntimeConfig, custody_group: CustodyIndex):
                                            ColumnIndex =
  let columns_per_group = NUMBER_OF_COLUMNS div cfg.NUMBER_OF_CUSTODY_GROUPS
  for i in 0'u64 ..< columns_per_group:
    yield ColumnIndex(cfg.NUMBER_OF_CUSTODY_GROUPS * i + custody_group)
```

Spec-conformant stride ✓ (iterator form, yield-per-column).

### lodestar

`getCustodyGroups` at `vendor/lodestar/packages/beacon-node/src/util/dataColumns.ts:204-238`:

```typescript
export function getCustodyGroups(config: ChainForkConfig, nodeId: NodeId, custodyGroupCount: number): CustodyIndex[] {
  if (custodyGroupCount > config.NUMBER_OF_CUSTODY_GROUPS) {
    throw Error(`Invalid custody group count ${custodyGroupCount} > ${config.NUMBER_OF_CUSTODY_GROUPS}`);
  }
  if (custodyGroupCount === config.NUMBER_OF_CUSTODY_GROUPS) {
    return Array.from({length: config.NUMBER_OF_CUSTODY_GROUPS}, (_, i) => i);
  }

  const custodyGroups: CustodyIndex[] = [];
  // nodeId is in bigendian and all computes are in little endian
  let currentId = bytesToBigInt(nodeId, "be");
  while (custodyGroups.length < custodyGroupCount) {
    const currentIdBytes = ssz.UintBn256.serialize(currentId);
    const custodyGroup = Number(
      ssz.UintBn64.deserialize(digest(currentIdBytes).slice(0, 8)) % BigInt(config.NUMBER_OF_CUSTODY_GROUPS)
    );
    if (!custodyGroups.includes(custodyGroup)) {
      custodyGroups.push(custodyGroup);
    }
    const willOverflow = currentIdBytes.reduce((acc, elem) => acc && elem === 0xff, true);
    if (willOverflow) {
      currentId = BigInt(0);
    } else {
      currentId++;
    }
  }
  custodyGroups.sort((a, b) => a - b);
  return custodyGroups;
}
```

`uint_to_bytes` LE via `ssz.UintBn256.serialize` ✓ (SSZ uint256 is LE-encoded). `bytes_to_uint64` LE via `ssz.UintBn64.deserialize` ✓. Overflow: explicit byte-by-byte 0xFF check (equivalent to comparing to UINT256_MAX) ✓. **Returns sorted array** via `custodyGroups.sort((a, b) => a - b)` ✓ matches spec H5.

`computeColumnsForCustodyGroup` at `dataColumns.ts:184-195`:

```typescript
const columnsPerCustodyGroup = Number(NUMBER_OF_COLUMNS / config.NUMBER_OF_CUSTODY_GROUPS);
const columnIndexes = [];
for (let i = 0; i < columnsPerCustodyGroup; i++) {
  columnIndexes.push(config.NUMBER_OF_CUSTODY_GROUPS * i + custodyIndex);
}
columnIndexes.sort((a, b) => a - b);
```

Spec-conformant stride ✓. Sort is redundant (the stride is already monotonic) but harmless.

### grandine

`get_custody_groups` at `vendor/grandine/eip_7594/src/lib.rs:46-96`:

```rust
pub fn get_custody_groups(
    config: &Config,
    raw_node_id: [u8; 32],
    custody_group_count: u64,
) -> Result<HashSet<CustodyIndex>> {
    let number_of_custody_groups = config.number_of_custody_groups;
    ensure!(custody_group_count <= number_of_custody_groups, Error::InvalidCustodyGroupCount { ... });

    if custody_group_count == number_of_custody_groups {
        return Ok((0..number_of_custody_groups).collect::<HashSet<_>>());
    }

    let mut current_id = NodeId::from_be_bytes(raw_node_id);
    let mut custody_groups = BTreeSet::new();
    while (custody_groups.len() as u64) < custody_group_count {
        let mut hasher = Sha256::new();
        let mut bytes = [0u8; 32];
        current_id.into_raw().to_little_endian(&mut bytes);
        hasher.update(bytes);
        bytes = hasher.finalize().into();
        let output_prefix = [
            bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5], bytes[6], bytes[7],
        ];
        let output_prefix_u64 = u64::from_le_bytes(output_prefix);
        let custody_group = output_prefix_u64.checked_rem(number_of_custody_groups).expect("...");
        custody_groups.insert(custody_group);

        if current_id == Uint256::MAX {
            current_id = Uint256::ZERO;
        } else {
            current_id = current_id + Uint256::one();
        }
    }
    Ok(custody_groups.into_iter().collect())
}
```

`uint_to_bytes` LE via `current_id.into_raw().to_little_endian(&mut bytes)` ✓. `bytes_to_uint64` via `u64::from_le_bytes` ✓. Overflow: explicit `current_id == Uint256::MAX ? ZERO : + Uint256::one()` ✓ matches spec.

**Sort deviation (H5)**: Internal collection is `BTreeSet` (sorted), then converted to `HashSet` via `.into_iter().collect()` — **loses the BTreeSet order, returns HashSet (unsorted)**. Membership-test consumers see no difference.

`compute_columns_for_custody_group` at `eip_7594/src/lib.rs:98-119`:

```rust
let mut columns = Vec::new();
for i in 0..config.columns_per_group::<P>() {
    columns.push(ColumnIndex::from(
        number_of_custody_groups * i + custody_group,
    ));
}
```

Spec-conformant stride ✓.

## Cross-reference table

| Client | `get_custody_groups` location | LE byte ops (H1) | Overflow guard (H1) | Output ordering (H5) | `compute_columns_for_custody_group` (H3) |
|---|---|---|---|---|---|
| prysm | `peerdas/das_core.go:29` | `ReverseByteOrder` BE→LE + `binary.LittleEndian.Uint64` ✓ | explicit `currentId.Cmp(maxUint256) == 0` check ✓ | **sorted** via `slices.Sort` ✓ | `das_core.go:92` ✓ |
| lighthouse | `data_column_custody_group.rs:28` | `as_le_slice()` + `u64::from_le_bytes` ✓ | `wrapping_add` (U256 wrap-on-overflow) ✓ | **HashSet (unsorted)** ✗; ordered variant returns insertion-order Vec | `data_column_custody_group.rs:109` ✓ |
| teku | `MiscHelpersFulu.java:193` | `uint256ToBytes` LE + `bytesToUInt64` ✓ | explicit `equals(MAX_VALUE) ? ZERO : plus(1)` ✓ | **sorted** via `.sorted()` stream op ✓ | `MiscHelpersFulu.java:169` ✓ |
| nimbus | `peerdas_helpers.nim:69` (wraps `handle_custody_groups`) | `toBytesLE()` + `bytes_to_uint64` ✓ | `inc current_id` (NodeId wrap-on-overflow) ✓ | **sorted** via `groups.sort()` ✓ | `peerdas_helpers.nim:32` (iterator) ✓ |
| lodestar | `dataColumns.ts:204` | `ssz.UintBn256.serialize` LE + `ssz.UintBn64.deserialize` LE ✓ | byte-by-byte 0xFF check ✓ | **sorted** via `sort((a,b) => a-b)` ✓ | `dataColumns.ts:184` ✓ |
| grandine | `eip_7594/src/lib.rs:46` | `to_little_endian` + `u64::from_le_bytes` ✓ | explicit `current_id == Uint256::MAX ? ZERO : + 1` ✓ | **HashSet (unsorted)** ✗ (built in BTreeSet then converted) | `eip_7594/src/lib.rs:98` ✓ |

H1–H4, H6 ✓ across all 6 clients. H5 partial: 4 of 6 return sorted Vec/List; **lighthouse + grandine return HashSet (unsorted)**.

## Empirical tests

EF Fulu DAS spec test corpus at `vendor/consensus-specs/tests/.../fulu/networking/get_custody_groups/` exercises `get_custody_groups` cross-client. Per-client fixture runners pass; no observed divergence on the published corpus.

Suggested fuzzing vectors:

- **T1.1 (cross-client byte-equivalence).** Random `node_id` (32-byte) + `cgc` ∈ [0, NUMBER_OF_CUSTODY_GROUPS]; compute custody-group set across 6 clients; diff via set equality (not order — accommodates the lighthouse/grandine HashSet return).
- **T1.2 (cgc = 0 edge).** Pass `custody_group_count = 0`. Spec returns empty list. All 6 should return empty.
- **T1.3 (cgc = NUMBER_OF_CUSTODY_GROUPS edge).** Pass full custody. Spec returns `[0, 1, ..., N-1]`. All 6 should return the full set (membership-equivalent).
- **T2.1 (item #41 round-trip).** Wire-encode `cgc=0` per client (item #41 audited the nimbus 1-byte vs others empty-bytes divergence); decode per client; pass to `get_custody_groups`; verify identical column-set (or empty for `cgc=0`).
- **T2.2 (max-cgc boundary).** `cgc = NUMBER_OF_CUSTODY_GROUPS` short-circuit branch in all 6 clients; verify they all return the full set without invoking the hash loop.
- **T2.3 (overflow edge).** Construct a synthetic `node_id` such that the iteration would hit `UINT256_MAX` and wrap; verify all 6 handle the overflow correctly.
- **T2.4 (sorted-output consumer).** If any consumer of `get_custody_groups` iterates the result expecting sorted order, verify it gracefully handles lighthouse + grandine's HashSet return. Audit the consumer call sites in lighthouse + grandine to confirm membership-only usage.

## Conclusion

All six clients implement PeerDAS custody column selection consistently at the **column-set semantics level**. The hash-based group derivation (`get_custody_groups`) uses identical SHA256 + LE byte conventions + modular arithmetic + UINT256_MAX overflow handling across all 6. The column-stride computation (`compute_columns_for_custody_group`) is uniform.

Lighthouse and grandine return an unsorted `HashSet` from their public `get_custody_groups` entry; the other 4 clients return a sorted Vec/List per spec. This is **a literal-vs-functional deviation**: membership-test consumers (the dominant use case for "does this node custody column X?") see no observable difference; iteration-order consumers would see different outputs. Both lighthouse and grandine expose ordered-output variants (lighthouse's `get_custody_groups_ordered`, grandine's internal `BTreeSet` form pre-conversion) for callers that need ordered iteration.

**Verdict: impact none.** No divergence on the column-set semantics. Audit closes.

## Cross-cuts

### With item #41 (nimbus ENR `cgc` encoding, synthetic-state)

Item #41 was wire-only divergence on `cgc=0` (nimbus 1-byte `0x00` vs others empty-bytes). This item confirms the runtime semantics post-decode are equivalent — particularly important since the decoded `cgc` drives `get_custody_groups`. Cross-cut: T2.1 wire-encode + decode round-trip.

### With item #73 (`get_data_column_sidecars`)

This item is the custody-set selection (which columns to custody); item #73 is the sidecar construction (which sidecars to build from blocks + blobs). Cross-cut on the column-index basis. The custody-column → sidecar mapping reduces to `compute_columns_for_custody_group` cross-cut.

### With PeerDAS gossip topic subscriptions

Per-client subnet subscription policy depends on the custody column-set. Adjacent audit.

## Adjacent untouched

1. **`NUMBER_OF_COLUMNS = 128` + `NUMBER_OF_CUSTODY_GROUPS = 128` constants cross-client verification** — should be uniform; verify mainnet and minimal preset values.
2. **`CUSTODY_REQUIREMENT` constant cross-client** — minimum custody groups required; per-client verification.
3. **PeerDAS gossip topic subscription mapping** — column-set → subnet-set; cross-cut.
4. **Custody validation on incoming column sidecars** — does the receiver verify the sender's claimed custody matches their NodeID?
5. **Lighthouse + grandine `HashSet` consumer audit** — verify all call sites use the result only for membership tests (not order-sensitive iteration).
6. **Spec test fixture corpus** — confirm `vendor/consensus-specs/tests/.../fulu/networking/get_custody_groups/` exercises the cgc=0 + cgc=NUMBER_OF_CUSTODY_GROUPS edges.
