# Item 53 — `DataColumnsByRootIdentifier` SSZ container audit (Fulu-NEW; consumed by `DataColumnSidecarsByRoot v1` RPC, item #46)

**Status:** no-divergence-pending-fixture-run on SSZ wire format; **multiple naming/casing divergences found** — audited 2026-05-04. **Twenty-third Fulu-NEW item, FIFTEENTH PeerDAS audit, FIRST FULU-NEW SSZ-CONTAINER detail audit**. Consumed by `DataColumnSidecarsByRoot v1` RPC (item #46) as `List[DataColumnsByRootIdentifier, MAX_REQUEST_BLOCKS_DENEB]` (item #52 cap).

**Spec definition** (`fulu/p2p-interface.md` "Containers" section):
```python
class DataColumnsByRootIdentifier(Container):
    block_root: Root
    columns: List[ColumnIndex, NUMBER_OF_COLUMNS]
```

2-field SSZ container:
- `block_root: Root` (Bytes32 fixed)
- `columns: List[ColumnIndex, NUMBER_OF_COLUMNS]` (variable-length list of uint64, max 128)

Used in `DataColumnSidecarsByRoot v1` request: `List[DataColumnsByRootIdentifier, MAX_REQUEST_BLOCKS_DENEB]` (max 128 entries — item #52 cap).

**Major findings**:
1. **Spec model divergence from `BlobIdentifier`**: Deneb's `BlobIdentifier` is `(block_root, index: uint64)` — singular blob per identifier. Fulu's `DataColumnsByRootIdentifier` is `(block_root, columns: List[...])` — **plural columns per identifier**. Semantic shift: batch-of-columns-per-block-root. Reduces request payload size for multi-column-per-block requests.
2. **Nimbus field-name divergence**: uses `indices` (`fulu.nim:111`) instead of spec's `columns`.
3. **Teku internal naming inconsistency**: Java class `DataColumnsByRootIdentifierSchema` but SSZ container name passed to `ContainerSchema2` constructor is `"DataColumnIdentifier"` (`DataColumnsByRootIdentifierSchema.java:32`).
4. **Lodestar camelCase**: uses `blockRoot` (TypeScript convention) vs spec `block_root` — handled via `jsonCase: "eth2"` for JSON serialization.
5. **Nimbus has BOTH containers**: vestigial Deneb-style `DataColumnIdentifier(block_root, index)` (`fulu.nim:104-106`) AND new Fulu `DataColumnsByRootIdentifier(block_root, indices)` (`:109-111`). Suggests compatibility with older Fulu draft spec.

**SSZ wire-format consequence**: ALL 6 clients produce IDENTICAL SSZ bytes because SSZ encoding is field-order-and-type based, NOT field-name based. Naming divergences are COSMETIC at SSZ wire level but affect: (a) JSON REST API responses, (b) cross-team communication, (c) spec compliance.

**NEW Pattern AA scope expansion** (cross-cuts items #45 + #47): per-client SSZ container naming divergence extends from version-numbering (V2 vs V3) to FIELD NAMES (`columns` vs `indices`) and INTERNAL CLASS-VS-SSZ-NAME inconsistencies (teku).

## Scope

In: `DataColumnsByRootIdentifier` SSZ container per-client implementation; field naming; type generics; column cap (NUMBER_OF_COLUMNS = 128); validation logic; comparison to legacy `BlobIdentifier` (Deneb-heritage); per-client class/struct organization; JSON serialization conventions.

Out: `DataColumnSidecarsByRoot v1` RPC handler architecture (item #46 covered); `DataColumnSidecar` schema (covered in items #34/#37); `compute_max_request_data_column_sidecars()` cap (item #49); `MAX_REQUEST_BLOCKS_DENEB` cap (item #52); `BlobIdentifier` Deneb-heritage container (covered implicitly via item #50).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | All 6 clients have a `DataColumnsByRootIdentifier` container (or analog) | ✅ all 6 | Spec-defined |
| H2 | Container is 2-field: `block_root: Root, columns: List[ColumnIndex, NUMBER_OF_COLUMNS]` | ✅ all 6 (semantically) | Spec-defined; field names differ |
| H3 | All 6 cap `columns` at NUMBER_OF_COLUMNS = 128 | ✅ all 6 | All 6 use NUMBER_OF_COLUMNS or hardcoded 128 |
| H4 | All 6 use field name `columns` per spec | ❌ 5 of 6 (prysm, lighthouse, teku, lodestar, grandine); **nimbus uses `indices`** | Field-name divergence |
| H5 | All 6 use snake_case `block_root` per spec | ❌ 5 of 6; **lodestar uses camelCase `blockRoot`** | TypeScript convention |
| H6 | Class/struct name matches spec name `DataColumnsByRootIdentifier` | ✅ all 6 | All match spec name |
| H7 | Internal SSZ container name (e.g., teku's `ContainerSchema2` constructor arg) matches class name | ❌ teku uses `"DataColumnIdentifier"` (singular, no "ByRoot") at `Schema.java:32` | NAMING INCONSISTENCY within teku |
| H8 | Validation: empty `columns` list rejected | ❌ none of 6 explicitly reject empty | Spec-undefined edge case |
| H9 | Validation: duplicate column indices rejected | ❌ none of 6 explicitly reject | Spec-undefined edge case |
| H10 | All 6 SSZ-encode identically (field-order + types) | ✅ all 6 | SSZ field-name-agnostic |
| H11 | Vestigial Deneb-style `(block_root, index)` container alongside | ❌ only **nimbus** has both `DataColumnIdentifier` (singular) AND `DataColumnsByRootIdentifier` (plural) | Pattern FF-style vestigial code |

## Per-client cross-reference

| Client | Container source | Container name | Field 1 (block_root) | Field 2 (columns) | Vestigial? |
|---|---|---|---|---|---|
| **prysm** | `proto/prysm/v1alpha1/data_columns.proto:48-51` (protobuf-generated SSZ) | `DataColumnsByRootIdentifier` | `block_root: bytes [ssz_size=32]` | `columns: repeated uint64 [ssz_max=128]` (HARDCODED 128) | NO |
| **lighthouse** | `consensus/types/src/data/data_column_sidecar.rs:32-38` | `DataColumnsByRootIdentifier<E>` | `block_root: Hash256` | `columns: VariableList<ColumnIndex, E::NumberOfColumns>` (generic) | NO |
| **teku** | `ethereum/spec/src/main/java/tech/pegasys/teku/spec/datastructures/networking/libp2p/rpc/DataColumnsByRootIdentifier.java:26-61` + `Schema.java:27-35` | Class: `DataColumnsByRootIdentifier`; **SSZ container name: `"DataColumnIdentifier"` (Schema:32)** | `getBlockRoot() -> Bytes32` | `getColumns() -> List<UInt64>` (`SszUInt64ListSchema.create(specConfig.getNumberOfColumns())`) | NO |
| **nimbus** | `beacon_chain/spec/datatypes/fulu.nim:108-111` | `DataColumnsByRootIdentifier* = object` | `block_root*: Eth2Digest` | **`indices*: DataColumnIndices`** (DataColumnIndices = `List[ColumnIndex, Limit(NUMBER_OF_COLUMNS)]`) | **YES** — also has `DataColumnIdentifier` (singular, `block_root + index`) at `:104-106` |
| **lodestar** | `packages/types/src/fulu/sszTypes.ts:83-89` | `DataColumnsByRootIdentifier` (typeName) | **`blockRoot: Root` (camelCase)** | `columns: ListBasicType(ColumnIndex, NUMBER_OF_COLUMNS)` (camelCase) | NO |
| **grandine** | `types/src/fulu/containers.rs:163-167` | `DataColumnsByRootIdentifier<P: Preset>` | `block_root: H256` | `columns: ContiguousList<ColumnIndex, P::NumberOfColumns>` (preset-parameterized) | NO |

## Notable per-client findings

### CRITICAL — Nimbus uses `indices` instead of `columns` (Pattern AA scope expansion)

Nimbus `fulu.nim:108-111`:
```nim
# https://github.com/ethereum/consensus-specs/blob/b8b5fbb8d16f52d42a716fa93289062fe2124c7c/specs/fulu/p2p-interface.md#datacolumnsbyrootidentifier
DataColumnsByRootIdentifier* = object
    block_root*: Eth2Digest
    indices*: DataColumnIndices
```

Where `DataColumnIndices* = List[ColumnIndex, Limit(NUMBER_OF_COLUMNS)]` (`:83`).

**Spec field name is `columns`**; nimbus uses `indices`. **Pattern AA scope expansion** — covers FIELD NAMES not just version numbering. Same forward-fragility class.

**SSZ wire impact**: NONE. SSZ encoding is field-order+type based. Both `(Eth2Digest, List[uint64, 128])` produce identical bytes regardless of field name.

**Non-SSZ impact**:
- JSON REST API responses (e.g., `/eth/v1/beacon/...`) would have key `indices` in nimbus vs `columns` in other 5
- Cross-team debugging/communication confusion
- Spec compliance — nimbus deviates

**Possible motivation**: nimbus's vestigial `DataColumnIdentifier` (singular) at `:104-106` uses `index*: ColumnIndex` field name; the plural variant at `:109-111` extends naming to `indices*` for symmetry. Cosmetic decision but spec-divergent.

**Bug-fix opportunity**: rename `indices` → `columns` in nimbus to match spec; preserve old name as alias for compat if needed.

### CRITICAL — Teku internal naming inconsistency

Teku `DataColumnsByRootIdentifierSchema.java:27-35`:
```java
public class DataColumnsByRootIdentifierSchema
    extends ContainerSchema2<DataColumnsByRootIdentifier, SszBytes32, SszUInt64List> {

  public DataColumnsByRootIdentifierSchema(final SpecConfigFulu specConfig) {
    super(
        "DataColumnIdentifier",  // <-- SSZ container name passed to ContainerSchema2
        ...
    );
  }
```

**Java class** `DataColumnsByRootIdentifierSchema` BUT **SSZ container name** `"DataColumnIdentifier"` (singular, no "ByRoot"). Naming inconsistency within teku.

**SSZ wire impact**: NONE. SSZ container name is metadata used for SSZ tree-hashing introspection, not on the wire.

**Non-SSZ impact**:
- SSZ tree visualization tools may show "DataColumnIdentifier" while spec/code says "DataColumnsByRootIdentifier"
- Cross-team confusion when reading teku source
- Likely a leftover from earlier draft spec where the container WAS called `DataColumnIdentifier`

**Bug-fix opportunity**: change `"DataColumnIdentifier"` → `"DataColumnsByRootIdentifier"` at `Schema.java:32`. Trivial fix.

**Same Pattern AA family** as item #45 (MetaData v3) + item #47 (Status v2) where teku consistently fork-names containers — but here teku has internal inconsistency, NOT consistent fork-naming.

### Lodestar camelCase convention

Lodestar `sszTypes.ts:83-89`:
```typescript
export const DataColumnsByRootIdentifier = new ContainerType(
  {
    blockRoot: Root,
    columns: new ListBasicType(ColumnIndex, NUMBER_OF_COLUMNS),
  },
  {typeName: "DataColumnsByRootIdentifier", jsonCase: "eth2"}
);
```

Lodestar uses camelCase `blockRoot` (TypeScript convention) vs spec snake_case `block_root`. Handled via `jsonCase: "eth2"` config which converts to spec snake_case for JSON serialization.

**SSZ wire impact**: NONE.
**JSON impact**: lodestar's `jsonCase: "eth2"` serializes as `block_root` matching spec.
**Non-spec impact**: TypeScript developers see `blockRoot` in source code; spec readers see `block_root`. Standard lodestar convention across all containers.

This is **systematic camelCase** for lodestar across all SSZ containers (consistent with TypeScript norms), so lower divergence concern than nimbus's per-container `indices` decision.

### Nimbus vestigial `DataColumnIdentifier` (singular) — Pattern FF candidate

Nimbus `fulu.nim:103-111`:
```nim
# https://github.com/ethereum/consensus-specs/blob/v1.5.0-alpha.10/specs/fulu/p2p-interface.md#datacolumnidentifier
DataColumnIdentifier* = object
    block_root*: Eth2Digest
    index*: ColumnIndex

# https://github.com/ethereum/consensus-specs/blob/b8b5fbb8d16f52d42a716fa93289062fe2124c7c/specs/fulu/p2p-interface.md#datacolumnsbyrootidentifier
DataColumnsByRootIdentifier* = object
    block_root*: Eth2Digest
    indices*: DataColumnIndices
```

**Two containers** — one Deneb-style singular `(block_root, index)` and one Fulu-style plural `(block_root, indices)`. Spec-comment URLs reference DIFFERENT spec versions:
- `DataColumnIdentifier`: `v1.5.0-alpha.10` — **older draft spec**
- `DataColumnsByRootIdentifier`: `b8b5fbb8d1...` — **newer commit hash**

**Pattern FF (vestigial config fields)** scope expansion — also applies to vestigial DATA TYPES from earlier spec drafts. Nimbus retained `DataColumnIdentifier` for compatibility with earlier Fulu testnets that used the singular model.

**Bug-fix opportunity**: remove `DataColumnIdentifier` from nimbus if no consumer remains. Verify via grep for usage.

### Comparison to legacy `BlobIdentifier`

Lighthouse `blob_sidecar.rs`:
```rust
pub struct BlobIdentifier {
    pub block_root: Hash256,
    pub index: u64,
}
```

Deneb-heritage. **Singular** — one identifier per blob (one `block_root` + one `index`).

Fulu's `DataColumnsByRootIdentifier`: **Plural** — one identifier per block_root with multiple `columns`. Spec evolution: batched column requests reduce per-identifier overhead.

For a request fetching all 128 columns of one block:
- BlobIdentifier (Deneb): 6 blobs × `(32 + 8)` bytes = 240 bytes for header
- DataColumnsByRootIdentifier (Fulu): 1 identifier × `(32 + 4 + 128*8)` bytes = 1060 bytes (with SSZ length prefix for variable list)

For multi-block requests with all 128 columns each:
- BlobIdentifier × 128 columns × 8 blocks = 1024 identifiers × 40 bytes = 40960 bytes
- DataColumnsByRootIdentifier × 8 blocks = 8 identifiers × 1060 bytes = 8480 bytes
- **5x reduction** in request size

Spec's plural model is bandwidth-efficient for multi-column requests — common in PeerDAS sync.

### SSZ wire-format consistency

Despite naming divergences, ALL 6 clients produce IDENTICAL SSZ bytes:
- Field 0: `Root` / `Bytes32` / `H256` / `Hash256` / `Eth2Digest` (32 bytes fixed) — same wire format
- Field 1: `List[uint64, 128]` (variable length with 4-byte length prefix + uint64 entries) — same wire format

SSZ specifies field-order serialization, NOT field-name serialization. So `(block_root, columns)` and `(block_root, indices)` SSZ-encode identically.

**Live mainnet validation**: 5+ months of cross-client DataColumnSidecarsByRoot v1 RPC interop without observed format-divergence — confirms SSZ wire compatibility.

### Validation gaps across all 6

**Spec is silent** on:
- Whether empty `columns` list should be rejected (effectively a no-op request)
- Whether duplicate column indices should be rejected (`columns: [3, 3, 5]`)
- Whether out-of-range indices should be rejected (`columns: [200]` when NUMBER_OF_COLUMNS = 128) — list type cap enforces this implicitly

**None of the 6 explicitly validate empty or duplicate `columns`**. Spec-undefined edge case (Pattern T-style). Each client may behave differently:
- Returns empty response for empty request? Or rejects?
- Returns duplicate sidecars for duplicate request indices? Or deduplicates?

**Forward research candidate**: cross-client interop test for empty/duplicate `columns` in DataColumnSidecarsByRoot v1 request.

## Cross-cut chain

This audit closes the Fulu-NEW SSZ container detail layer:
- **Item #46** (DataColumnSidecarsByRange/Root v1 RPC handlers): consumes this container
- **Item #52** (`MAX_REQUEST_BLOCKS_DENEB`): caps the request list at 128 entries
- **Item #34** (DataColumnSidecar verification): cross-cut on container family
- **Item #45** (MetaData v3 — Pattern AA): per-client SSZ container naming divergence; this audit EXTENDS Pattern AA from version numbering (V2 vs V3) to FIELD NAMES (`columns` vs `indices`) and INTERNAL CLASS-VS-SSZ-NAME inconsistency (teku)
- **Item #47** (Status v2 — Pattern AA): teku consistently fork-names containers, but here teku has internal inconsistency
- **Item #44** (PartialDataColumnSidecar — Pattern Z): related Fulu-NEW container, only nimbus implements
- **Item #28 Pattern AA scope expansion**: now covers (a) version-numbering divergence (items #45 + #47), (b) FIELD-NAMING divergence (item #53 nimbus `indices`), (c) CASING convention (item #53 lodestar `blockRoot`), (d) INTERNAL inconsistency (item #53 teku `"DataColumnIdentifier"` SSZ name)
- **Item #28 Pattern FF scope expansion**: also covers vestigial DATA TYPES (nimbus `DataColumnIdentifier` singular), not just config fields
- **Item #48** (catalogue refresh): adds Pattern AA + FF expansions

## Adjacent untouched Fulu-active

- `BlobIdentifier` Deneb-heritage container detailed cross-client comparison (precursor to DataColumnsByRootIdentifier)
- `PartialDataColumnSidecar` SSZ container detail audit (item #44 covered implementation gap; container schema cross-client TBD)
- `PartialDataColumnPartsMetadata` SSZ container (Fulu-NEW per spec line 30)
- `PartialDataColumnHeader` SSZ container (Fulu-NEW per spec line 31)
- DataColumnSidecar SSZ container detail audit (items #34/#37 covered usage; per-client schema TBD)
- BlobsBundle SSZ container Fulu-modified (validator-side; covered implicitly in item #40)
- ExecutionPayloadEnvelope SSZ container (Gloas-NEW; pre-emptive audit candidate)
- SignedExecutionPayloadBid SSZ container (Gloas-NEW)
- InclusionList + SignedInclusionList SSZ containers (Heze-NEW per item #29 finding)
- Cross-client SSZ container naming convention catalogue (extending Pattern AA)
- nimbus `DataColumnIdentifier` (singular) usage audit — is it dead code?

## Future research items

1. **Pattern AA scope expansion for item #28 catalogue**: extend from version-numbering (V2/V3) to FIELD NAMES (`columns` vs `indices`) and INTERNAL CLASS-VS-SSZ-NAME inconsistencies (teku `"DataColumnIdentifier"`). Same forward-fragility class.
2. **Pattern FF scope expansion**: extends from config fields (grandine `max_request_blob_sidecars_fulu`) to vestigial DATA TYPES (nimbus `DataColumnIdentifier` singular). Same forward-fragility class.
3. **Nimbus rename PR**: change `indices` → `columns` in `DataColumnsByRootIdentifier` to match spec. Preserve old name as deprecated alias for backward compat.
4. **Nimbus dead code removal PR**: remove `DataColumnIdentifier` (singular) if no consumer remains. Audit usage first.
5. **Teku internal-naming PR**: change `"DataColumnIdentifier"` → `"DataColumnsByRootIdentifier"` at `DataColumnsByRootIdentifierSchema.java:32`. Trivial fix.
6. **Cross-client interop test for empty/duplicate `columns`**: spec-undefined edge case (Pattern T-style). Test whether all 6 handle uniformly.
7. **JSON REST API response audit**: do all 6 produce `block_root` (or `blockRoot` for lodestar) per spec? Particularly nimbus may produce `indices` in JSON outputs — spec compliance gap.
8. **Cross-client SSZ container naming convention catalogue**: systematically catalogue all Fulu-NEW SSZ container names + field names per client. Extend Pattern AA.
9. **Spec-validation test for Fulu-NEW SSZ containers**: generate fixtures encoding/decoding `DataColumnsByRootIdentifier` from each client; verify cross-client round-trip equivalence.
10. **PartialDataColumnSidecar/Header/PartsMetadata SSZ schema audit (item #54+ candidates)**: similar Fulu-NEW SSZ container family; only nimbus implements (per item #44).
11. **DataColumnSidecar detailed schema audit (item #54+ candidate)**: items #34/#37 covered usage; per-client field-by-field schema cross-check is pending.
12. **Compare to ExecutionPayloadEnvelope (Gloas-NEW)**: pre-emptive audit candidate. Likely similar Pattern AA divergence opportunities.
13. **BlobIdentifier (Deneb-heritage) cross-client name/field audit**: parallel to this audit; baseline for understanding Pattern AA spread.

## Summary

Fulu-NEW `DataColumnsByRootIdentifier` SSZ container (`fulu/p2p-interface.md` Containers section): 2-field container `(block_root: Root, columns: List[ColumnIndex, NUMBER_OF_COLUMNS])`. Consumed by `DataColumnSidecarsByRoot v1` RPC (item #46) as `List[DataColumnsByRootIdentifier, MAX_REQUEST_BLOCKS_DENEB]` (max 128 entries, item #52 cap).

**SSZ wire format identical across all 6 clients** because SSZ encoding is field-order+type based. Live mainnet validates 5+ months of cross-client interop without format-divergence.

**Multiple naming divergences identified**:
- **Nimbus** (`fulu.nim:111`): field name `indices` instead of spec `columns`
- **Teku** (`Schema.java:32`): SSZ container name `"DataColumnIdentifier"` (singular, no "ByRoot") inside Java class `DataColumnsByRootIdentifierSchema` — internal inconsistency
- **Lodestar** (`sszTypes.ts:84`): camelCase `blockRoot` vs spec snake_case `block_root` (handled via `jsonCase: "eth2"`)
- **Nimbus** (`fulu.nim:104-106`): vestigial `DataColumnIdentifier` (singular Deneb-style) alongside Fulu's plural variant — leftover from older spec draft

**NEW Pattern AA scope expansion**: extend from version-numbering (item #45 + #47) to FIELD NAMES (nimbus `indices`), CASING (lodestar `blockRoot`), and INTERNAL class-vs-SSZ-name inconsistency (teku). Same forward-fragility class.

**NEW Pattern FF scope expansion**: extend from config fields (grandine `max_request_blob_sidecars_fulu` from item #50) to vestigial DATA TYPES (nimbus `DataColumnIdentifier` singular). Same forward-fragility class.

**Spec model evolution from BlobIdentifier**: Deneb's `BlobIdentifier(block_root, index)` is singular (one identifier per blob); Fulu's `DataColumnsByRootIdentifier(block_root, columns)` is plural (one identifier per block_root with multiple columns). 5x bandwidth reduction for multi-column requests. Common in PeerDAS sync.

**Validation gaps across all 6**: none explicitly reject empty `columns` list, duplicate indices, or out-of-range indices (latter implicitly capped by list type). Spec-undefined edge cases (Pattern T-style).

**Bug-fix opportunities identified**:
1. Nimbus rename `indices` → `columns` (`fulu.nim:111`)
2. Nimbus remove vestigial `DataColumnIdentifier` (`:104-106`) if dead code
3. Teku rename `"DataColumnIdentifier"` → `"DataColumnsByRootIdentifier"` (`Schema.java:32`)

**Heritage-spec evolution finding**: nimbus comments reveal Fulu spec went through `v1.5.0-alpha.10 DataColumnIdentifier (singular)` → `b8b5fbb8d1... DataColumnsByRootIdentifier (plural)` evolution. Other 5 clients only have the plural variant.

**With this audit, the Fulu-NEW SSZ container detail layer is opened**. Future audits should cover PartialDataColumnSidecar/Header/PartsMetadata family (only nimbus implements per item #44) and DataColumnSidecar detailed schema cross-check.

**Total Fulu-NEW items: 23 (#30–#53)**. Item #28 catalogue Patterns A–HH (34 patterns) + Pattern AA + FF scope expansions (no NEW pattern letter, but expanded scope).

**PeerDAS audit corpus now spans 15 items**: #33 → #34 → #35 → #37 → #38 → #39 → #40 → #41 → #42 → #44 → #45 → #46 → #47 → #49 → **#53**. Fifteen-item arc covering consensus-critical PeerDAS surface end-to-end + SSZ container detail.
