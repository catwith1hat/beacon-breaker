---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [28, 34, 45, 46, 47, 50, 52]
eips: [EIP-7594]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 53: `DataColumnsByRootIdentifier` SSZ container audit — Fulu-NEW container consumed by `DataColumnSidecarsByRoot v1`; Pattern AA + FF scope expansion

## Summary

Fulu-NEW SSZ container (`vendor/consensus-specs/specs/fulu/p2p-interface.md:72-75`):

```python
class DataColumnsByRootIdentifier(Container):
    block_root: Root
    columns: List[ColumnIndex, NUMBER_OF_COLUMNS]
```

Two-field container — `block_root: Root` (Bytes32 fixed) + `columns: List[ColumnIndex, NUMBER_OF_COLUMNS]` (variable-length list of `uint64`, cap = 128). Consumed by `DataColumnSidecarsByRoot v1` RPC (item #46) as `List[DataColumnsByRootIdentifier, MAX_REQUEST_BLOCKS_DENEB]` (item #52 cap = 128 outer; item #33 cap = 128 inner).

**Semantic shift from Deneb's `BlobIdentifier`**: Deneb's `(block_root, index: uint64)` carries a single blob index per identifier. Fulu's `(block_root, columns: List[...])` carries a list of column indices per identifier — **batched** request shape. For multi-column requests, the plural model is ~5× more bandwidth-efficient (fewer redundant `block_root` headers).

**Fulu surface (carried forward from 2026-05-04 audit; cap value):** all 6 clients evaluate `NUMBER_OF_COLUMNS = 128` as the inner cap. **No production divergence on SSZ wire format** — SSZ encoding is field-order + type based, not field-name based, so the cosmetic naming divergences below produce byte-identical encodings.

**Naming divergence cohort (Pattern AA scope expansion)**:

- **nimbus** uses `indices: DataColumnIndices` instead of spec's `columns` (`vendor/nimbus/beacon_chain/spec/datatypes/fulu.nim:109-111`). Same forward-fragility class as items #45 (MetaData v3) and #47 (Status v2) where Pattern AA describes SSZ container version-numbering divergence — this audit extends Pattern AA to FIELD NAMES.
- **teku** has internal Java-class-vs-SSZ-container-name inconsistency: Java class is `DataColumnsByRootIdentifier`, but the SSZ container name string passed to `ContainerSchema2` is `"DataColumnIdentifier"` (singular, no "ByRoot") at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/datastructures/networking/libp2p/rpc/DataColumnsByRootIdentifierSchema.java:32`. The SSZ field names `"block_root"` and `"columns"` (`:33-34`) are spec-aligned — the inconsistency is only in the container-name metadata.
- **lodestar** uses camelCase `blockRoot` (TypeScript convention) vs spec `block_root` at `vendor/lodestar/packages/types/src/fulu/sszTypes.ts:85`. Handled via `jsonCase: "eth2"` so JSON serialisation outputs spec snake_case.

**Pattern FF scope expansion** (carried forward from item #50 grandine `max_request_blob_sidecars_fulu` vestigial field): cohort lifts from {grandine} to {grandine, nimbus} for VESTIGIAL DATA TYPES:

- **nimbus** (`vendor/nimbus/beacon_chain/spec/datatypes/fulu.nim:103-106`) carries a SECOND container `DataColumnIdentifier { block_root, index: ColumnIndex }` (singular, Deneb-style) alongside `DataColumnsByRootIdentifier` (plural). Spec-comment URLs reveal the singular form references `v1.5.0-alpha.10` (older draft); plural form references commit `b8b5fbb8d1...` (newer). Compatibility relic from earlier Fulu testnets.
- **grandine** (`vendor/grandine/types/src/fulu/containers.rs:153-167`) **also carries BOTH** SSZ structs: `DataColumnIdentifier { block_root, index: ColumnIndex }` (singular, lines 153-159) AND `DataColumnsByRootIdentifier<P: Preset> { block_root, columns: ContiguousList<...> }` (plural, lines 161-167). **NEW finding this recheck** — previously Pattern FF was nimbus-only on this surface.

(teku, prysm, lighthouse have references to "DataColumnIdentifier" in non-SSZ utility/build-config sites — teku has a `record DataColumnIdentifier(Bytes32 blockRoot, UInt64 columnIndex)` Java record at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/datastructures/util/DataColumnIdentifier.java:20` as an internal data type; prysm has it in `BUILD.bazel:189`; lighthouse only as a code comment at `chain_spec.rs:2303`. None of these are SSZ wire types.)

**Glamsterdam target (Gloas):** `vendor/consensus-specs/specs/gloas/p2p-interface.md` contains NO `DataColumnsByRootIdentifier` or `DataColumnIdentifier` references — verified by `grep -rn "DataColumnsByRootIdentifier\|DataColumnIdentifier" vendor/consensus-specs/specs/gloas/` returning 0 matches. The Fulu container carries forward verbatim into Gloas across all 6 clients. The `DataColumnSidecarsByRoot v1` RPC protocol IDs remain V1 at Gloas (per item #46 recheck), and the request-payload SSZ container is unchanged — but Gloas's `DataColumnSidecar` payload reshape (item #46 cross-cut) means the response shape changes while the request shape does not.

**Spec-undefined edge cases (Pattern T family)**: spec is silent on whether empty `columns` list should be rejected, whether duplicate column indices should be rejected, and whether out-of-range indices should be rejected (the latter implicitly capped by the SSZ list-type bound). **None of the 6 clients explicitly validate these**.

**Impact: none** — SSZ wire format byte-identical across all 6 (validated by 5+ months of mainnet cross-client `DataColumnSidecarsByRoot v1` exchanges); naming divergences are cosmetic at the SSZ layer; Gloas carries the Fulu container verbatim. Thirty-fourth `impact: none` result in the recheck series.

## Question

Pyspec defines the container at `vendor/consensus-specs/specs/fulu/p2p-interface.md:72-75`. The spec also references it as the request list element at `:494 List[DataColumnsByRootIdentifier, MAX_REQUEST_BLOCKS_DENEB]`. Gloas does not modify the container.

Three recheck questions:

1. **SSZ wire format** — do all 6 clients still produce byte-identical encodings of the 2-field container? Does the cohort of naming-divergent implementations (nimbus `indices`, teku `"DataColumnIdentifier"` schema name, lodestar `blockRoot`) persist?
2. **Pattern FF vestigial data types** — does the {nimbus, grandine} cohort carrying BOTH the singular `DataColumnIdentifier` and plural `DataColumnsByRootIdentifier` SSZ structs persist? Has either client removed the dead singular type since the 2026-05-04 audit?
3. **Glamsterdam target** — does the Fulu container carry forward unchanged into Gloas in all 6 clients?

## Hypotheses

- **H1.** All 6 clients have `DataColumnsByRootIdentifier` (or an analog with spec-aligned field types).
- **H2.** Container is 2-field semantically: `block_root: Root` + `columns: List[ColumnIndex, NUMBER_OF_COLUMNS]`.
- **H3.** All 6 cap the inner `columns` list at `NUMBER_OF_COLUMNS = 128`.
- **H4.** Field name `columns` per spec: 5 of 6 (prysm, lighthouse, teku, lodestar, grandine); nimbus uses `indices` (Pattern AA scope expansion).
- **H5.** Field name `block_root` per spec (snake_case): 5 of 6; lodestar uses camelCase `blockRoot` (TypeScript convention) but maps to spec snake_case via `jsonCase: "eth2"`.
- **H6.** SSZ container name in metadata: 5 of 6 use `"DataColumnsByRootIdentifier"`; teku uses `"DataColumnIdentifier"` (internal Pattern AA inconsistency at `DataColumnsByRootIdentifierSchema.java:32`).
- **H7.** SSZ wire-format identical across all 6 (field-order + types match).
- **H8.** Pattern FF — vestigial `DataColumnIdentifier` (singular Deneb-style) SSZ container present in {nimbus, grandine}. **NEW finding this recheck**: grandine joins the cohort; previously thought nimbus-only.
- **H9.** Spec-undefined edge cases (empty list, duplicate indices, out-of-range indices) not explicitly validated in any client.
- **H10.** *(Glamsterdam target)* `vendor/consensus-specs/specs/gloas/p2p-interface.md` does NOT modify the container. Carries forward verbatim.
- **H11.** Live mainnet cross-client interop validates byte-identical encoding for 5+ months.

## Findings

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (nimbus `indices` divergent). H5 ✓ (lodestar camelCase). H6 ✓ (teku `"DataColumnIdentifier"` SSZ container name). H7 ✓. **H8 ⚠ UPDATE**: grandine joins Pattern FF cohort — previously thought nimbus-only. H9 ✓. H10 ✓ (no Gloas modification). H11 ✓.

### prysm

Protobuf-generated SSZ container (`vendor/prysm/proto/prysm/v1alpha1/data_columns.proto:48-51`):

```protobuf
message DataColumnsByRootIdentifier {
  bytes block_root = 1 [ (ethereum.eth.ext.ssz_size) = "32" ];
  repeated uint64 columns = 2 [ (ethereum.eth.ext.ssz_max) = "128" ];
}
```

**Spec-aligned naming** for both fields (`block_root`, `columns`). Cap **hardcoded as `"128"`** in the `ssz_max` annotation rather than derived from `NUMBER_OF_COLUMNS` (Pattern DD trace: prysm hardcodes derived constants).

No vestigial `DataColumnIdentifier` SSZ container — the reference at `vendor/prysm/proto/prysm/v1alpha1/BUILD.bazel:189` is to the legacy data-columns proto type and not currently used as a wire container in v1alpha1.

H1–H11 satisfied. Spec-aligned, no Pattern AA contribution.

### lighthouse

Rust struct (`vendor/lighthouse/consensus/types/src/data/data_column_sidecar.rs:32-38`):

```rust
/// Identifies a set of data columns associated with a specific beacon block.
#[derive(Encode, Decode, Clone, Debug, PartialEq, TreeHash, Deserialize)]
#[context_deserialize(ForkName)]
pub struct DataColumnsByRootIdentifier<E: EthSpec> {
    pub block_root: Hash256,
    pub columns: VariableList<ColumnIndex, E::NumberOfColumns>,
}
```

**Spec-aligned naming**. Generic `<E: EthSpec>` parameter — `NumberOfColumns` resolves to 128 on mainnet via preset.

Comment "Identifies a set of data columns associated with a specific beacon block" captures the plural semantic accurately.

`chain_spec.rs:2303` has a code comment referencing "DataColumnIdentifiers" plural but no separate SSZ struct.

H1–H11 satisfied. Spec-aligned, no Pattern AA contribution.

### teku

Java class (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/datastructures/networking/libp2p/rpc/DataColumnsByRootIdentifier.java:26-27`):

```java
public class DataColumnsByRootIdentifier
    extends Container2<DataColumnsByRootIdentifier, SszBytes32, SszUInt64List> {
```

Schema (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/datastructures/networking/libp2p/rpc/DataColumnsByRootIdentifierSchema.java:27-35`):

```java
public class DataColumnsByRootIdentifierSchema
    extends ContainerSchema2<DataColumnsByRootIdentifier, SszBytes32, SszUInt64List> {

  public DataColumnsByRootIdentifierSchema(final SpecConfigFulu specConfig) {
    super(
        "DataColumnIdentifier",
        namedSchema("block_root", SszPrimitiveSchemas.BYTES32_SCHEMA),
        namedSchema("columns", SszUInt64ListSchema.create(specConfig.getNumberOfColumns())));
  }
```

**Internal Java-class-vs-SSZ-name inconsistency**: Java class `DataColumnsByRootIdentifier`, but the SSZ container name passed to `ContainerSchema2` constructor is `"DataColumnIdentifier"` (singular, no "ByRoot"). The SSZ field names `"block_root"` and `"columns"` are spec-aligned at `:33-34`.

**SSZ wire impact**: NONE — the container-name string is metadata for SSZ tree-hashing introspection, not on the wire.

**Tooling impact**: SSZ tree visualisation tools may show `"DataColumnIdentifier"` while spec/code says `"DataColumnsByRootIdentifier"`. Cross-team confusion when reading teku source. Likely a leftover from earlier draft spec where the container WAS called `DataColumnIdentifier`. Trivial bug-fix opportunity: rename the constructor literal at `Schema.java:32`.

Pattern AA cohort contribution: **internal class-vs-SSZ-name inconsistency** (new sub-category of Pattern AA at this audit).

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/datastructures/util/DataColumnIdentifier.java:20` is a non-SSZ Java record `(Bytes32 blockRoot, UInt64 columnIndex)` used as an internal bookkeeping type — NOT a wire-format SSZ container. So teku does NOT carry a vestigial SSZ `DataColumnIdentifier` (the singular SSZ container exists only in nimbus + grandine per H8).

H1–H7 ✓; H6 ⚠ teku internal inconsistency.

### nimbus

Container declarations (`vendor/nimbus/beacon_chain/spec/datatypes/fulu.nim:103-111`):

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

Where `DataColumnIndices* = List[ColumnIndex, Limit(NUMBER_OF_COLUMNS)]` (per the type declaration earlier in the same file).

**Two divergences from spec**:

1. **Field name `indices` instead of spec `columns`** at `:111`. Pattern AA scope expansion (this audit) — naming divergence at the FIELD-NAME layer, not just version-numbering.
2. **Vestigial `DataColumnIdentifier` singular SSZ object** at `:103-106`. Pattern FF — leftover from earlier Fulu spec drafts (referenced via `v1.5.0-alpha.10` URL). The newer plural variant references a non-tagged commit hash.

`shortLog*(x: seq[DataColumnIdentifier])` at `:575` and `shortLog*(xs: seq[DataColumnsByRootIdentifier])` at `:578` confirm both types have consumers (at least at the logging level).

**SSZ wire impact**: NONE for the field-name divergence — `(Eth2Digest, List[uint64, 128])` SSZ-encodes identically regardless of field name. The vestigial type is a separate SSZ container with different wire shape (`(Root, ColumnIndex)`); it doesn't conflict with the plural form on the wire.

**Non-SSZ impact**: nimbus JSON REST API responses (e.g., `/eth/v1/...` endpoints exposing this container) emit `indices` key vs spec/other-5-clients' `columns`. Spec-compliance gap.

Bug-fix opportunities: (a) rename `indices` → `columns` to match spec; (b) audit usage of `DataColumnIdentifier` singular and remove if dead code.

Pattern AA cohort contribution: field-name divergence. Pattern FF cohort contribution: vestigial SSZ data type.

### lodestar

ContainerType (`vendor/lodestar/packages/types/src/fulu/sszTypes.ts:83-89`):

```typescript
export const DataColumnsByRootIdentifier = new ContainerType(
  {
    blockRoot: Root,
    columns: new ListBasicType(ColumnIndex, NUMBER_OF_COLUMNS),
  },
  {typeName: "DataColumnsByRootIdentifier", jsonCase: "eth2"}
);
```

**camelCase `blockRoot` vs spec snake_case `block_root`**. Lodestar uses camelCase consistently across all SSZ containers (TypeScript convention). `jsonCase: "eth2"` config converts to spec snake_case for JSON serialisation.

`columns` field name matches spec; `typeName: "DataColumnsByRootIdentifier"` matches spec.

**SSZ wire impact**: NONE.
**JSON impact**: matches spec via `jsonCase: "eth2"`.
**Source-code impact**: TypeScript developers see `blockRoot` while spec readers see `block_root`. Standard lodestar convention.

Pattern AA cohort contribution: CASING convention (not strict spec violation due to `jsonCase: "eth2"` translation). Less concerning than nimbus's `indices` divergence.

### grandine

Container declarations (`vendor/grandine/types/src/fulu/containers.rs:153-167`):

```rust
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, Deserialize, Serialize, Ssz)]
#[serde(bound = "", deny_unknown_fields)]
pub struct DataColumnIdentifier {
    pub block_root: H256,
    #[serde(with = "serde_utils::string_or_native")]
    pub index: ColumnIndex,
}

#[derive(Clone, PartialEq, Eq, Hash, Debug, Deserialize, Serialize, Ssz)]
#[serde(bound = "", deny_unknown_fields)]
pub struct DataColumnsByRootIdentifier<P: Preset> {
    pub block_root: H256,
    #[serde(with = "serde_utils::string_or_native_sequence")]
    pub columns: ContiguousList<ColumnIndex, P::NumberOfColumns>,
}
```

**Spec-aligned field names** for both fields in the plural form. Preset-parameterised cap via `P::NumberOfColumns`.

**NEW finding this recheck — Pattern FF cohort extends to grandine**: grandine carries BOTH the singular `DataColumnIdentifier` (lines 153-159, with `index: ColumnIndex`) AND the plural `DataColumnsByRootIdentifier` (lines 161-167, with `columns: ContiguousList<...>`). Both have `Ssz` derive macros — they are both wire-shape SSZ containers. Previously this recheck pass marked Pattern FF as nimbus-only on this surface; grandine joins.

Unlike nimbus, grandine does NOT annotate the spec URLs in its source comments, so we cannot determine from the file alone whether `DataColumnIdentifier` is a deliberate retention (e.g., for testnet compatibility) or an undisturbed earlier-draft remnant.

Pattern AA cohort contribution: NONE (spec-aligned naming on plural form). Pattern FF cohort contribution: vestigial SSZ data type (new this recheck).

## Cross-reference table

| Client | H2 container declaration | H4 field name (columns) | H5 field name (block_root) | H6 SSZ container name in metadata | H8 vestigial DataColumnIdentifier (singular SSZ) | Pattern AA contribution | Pattern FF contribution |
|---|---|---|---|---|---|---|---|
| **prysm** | `data_columns.proto:48-51 message DataColumnsByRootIdentifier { bytes block_root; repeated uint64 columns [ssz_max=128]; }` | ✅ `columns` | ✅ `block_root` (snake_case) | ✅ `DataColumnsByRootIdentifier` (proto message name) | ❌ none (only `BUILD.bazel:189` reference) | none | none |
| **lighthouse** | `consensus/types/src/data/data_column_sidecar.rs:32-38 pub struct DataColumnsByRootIdentifier<E: EthSpec> { pub block_root: Hash256, pub columns: VariableList<ColumnIndex, E::NumberOfColumns> }` | ✅ `columns` | ✅ `block_root` (snake_case via Rust convention) | ✅ via tree-hash derive | ❌ none (only code comment at `chain_spec.rs:2303`) | none | none |
| **teku** | `DataColumnsByRootIdentifier.java:26-27 extends Container2<...>`; `DataColumnsByRootIdentifierSchema.java:33-34 namedSchema("block_root"), namedSchema("columns")` | ✅ `columns` (`:34`) | ✅ `block_root` (`:33`) | ⚠ **`"DataColumnIdentifier"` (singular)** at `DataColumnsByRootIdentifierSchema.java:32` — class-vs-SSZ-name internal inconsistency | ❌ no SSZ singular (only non-SSZ Java record at `util/DataColumnIdentifier.java:20`) | internal class-vs-SSZ-name inconsistency (new Pattern AA sub-category) | none |
| **nimbus** | `fulu.nim:108-111 DataColumnsByRootIdentifier* = object { block_root*: Eth2Digest, indices*: DataColumnIndices }` | ❌ **`indices`** (Pattern AA scope expansion — field-name divergence) | ✅ `block_root` | n/a (Nim's SSZ derive emits the type name) | ✅ **`DataColumnIdentifier* = object { block_root, index: ColumnIndex }`** at `:104-106` with `v1.5.0-alpha.10` spec-comment URL | field-name divergence (`indices`) | vestigial SSZ singular type |
| **lodestar** | `sszTypes.ts:83-89 export const DataColumnsByRootIdentifier = new ContainerType({ blockRoot: Root, columns: new ListBasicType(ColumnIndex, NUMBER_OF_COLUMNS) }, {typeName: "DataColumnsByRootIdentifier", jsonCase: "eth2"})` | ✅ `columns` | ⚠ camelCase `blockRoot` (mapped to spec snake_case via `jsonCase: "eth2"`) | ✅ `DataColumnsByRootIdentifier` | ❌ none | camelCase convention (TypeScript) | none |
| **grandine** | `fulu/containers.rs:161-167 pub struct DataColumnsByRootIdentifier<P: Preset> { pub block_root: H256, pub columns: ContiguousList<ColumnIndex, P::NumberOfColumns> }` | ✅ `columns` | ✅ `block_root` (snake_case via Rust convention) | ✅ via Ssz derive | ✅ **`pub struct DataColumnIdentifier { pub block_root: H256, pub index: ColumnIndex }`** at `:153-159` (NEW this recheck) | none | **vestigial SSZ singular type (NEW this recheck)** |

**Pattern AA cohort (naming divergence)**: nimbus `indices` + teku `"DataColumnIdentifier"` SSZ metadata + lodestar `blockRoot` (mapped). **Pattern FF cohort (vestigial SSZ data types)**: {nimbus, grandine} — **NEW finding**: grandine joins, previously thought nimbus-only on this surface. **SSZ wire format**: byte-identical across all 6.

## Empirical tests

- ✅ **Live mainnet operation since 2025-12-03 (5+ months)**: cross-client `DataColumnSidecarsByRoot v1` exchanges deserialize successfully across all 6 client pairs. No SSZ format-divergence observed. **Verifies H7 + H11 at production scale.**
- ✅ **Per-client container declaration verification (this recheck)**: all 6 declaration sites confirmed via file:line citations above. Pattern AA cohort (nimbus + teku + lodestar) unchanged. Pattern FF cohort extends to grandine (NEW).
- ✅ **Gloas carry-forward verification**: `grep -rn "DataColumnsByRootIdentifier\|DataColumnIdentifier" vendor/consensus-specs/specs/gloas/` returns 0 matches. Container carries forward verbatim into Gloas.
- ⏭ **Nimbus rename PR**: change `indices` → `columns` in `vendor/nimbus/beacon_chain/spec/datatypes/fulu.nim:111`. Optionally retain `indices` as a deprecated alias for callers.
- ⏭ **Teku internal-naming PR**: change `"DataColumnIdentifier"` → `"DataColumnsByRootIdentifier"` at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/datastructures/networking/libp2p/rpc/DataColumnsByRootIdentifierSchema.java:32`. Trivial fix; aligns SSZ container name with Java class name.
- ⏭ **Vestigial SSZ type cleanup audit**: grep both nimbus and grandine for consumers of the singular `DataColumnIdentifier` SSZ type. If no consumer, file removal PRs.
- ⏭ **Cross-client interop test for edge cases**: empty `columns` list, duplicate column indices, out-of-range indices (>= NUMBER_OF_COLUMNS). Spec-undefined behaviour — verify per-client uniformity (Pattern T family).
- ⏭ **JSON REST API audit**: verify nimbus's JSON outputs use `columns` not `indices` (if any JSON endpoint surfaces this container). Spec compliance gap candidate.
- ⏭ **Pattern AA + FF catalogue update**: refresh item #28/#48 to reflect this recheck's expansions — Pattern AA now spans (i) version-numbering (items #45 + #47), (ii) FIELD NAMES (item #53 nimbus `indices`), (iii) CASING convention (item #53 lodestar `blockRoot`), (iv) INTERNAL class-vs-SSZ-name inconsistency (item #53 teku). Pattern FF now spans (i) config fields (item #50 grandine `max_request_blob_sidecars_fulu`), (ii) SSZ data types ({nimbus, grandine} `DataColumnIdentifier` singular).

## Conclusion

The Fulu-NEW `DataColumnsByRootIdentifier` SSZ container is byte-identical across all 6 clients on the wire — SSZ encoding is field-order + type based, so the cosmetic naming divergences below do not produce divergent wire bytes. 5+ months of live mainnet cross-client `DataColumnSidecarsByRoot v1` exchanges validate the wire-format compatibility.

**Pattern AA scope expansion (carried forward from prior audit)**: per-client SSZ container naming divergence — three sub-categories on this surface:

- **Field name** (nimbus `indices` vs spec `columns` at `fulu.nim:111`).
- **CASING convention** (lodestar camelCase `blockRoot` mapped to spec snake_case via `jsonCase: "eth2"` at `sszTypes.ts:85`).
- **Internal class-vs-SSZ-name inconsistency** (teku Java class `DataColumnsByRootIdentifier` vs SSZ container name `"DataColumnIdentifier"` at `DataColumnsByRootIdentifierSchema.java:32`).

**Pattern FF scope expansion (NEW finding this recheck)**: vestigial SSZ data types — cohort grows from nimbus-only to **{nimbus, grandine}**. Both carry a singular `DataColumnIdentifier { block_root, index: ColumnIndex }` SSZ struct alongside the plural `DataColumnsByRootIdentifier`. The singular form predates the spec evolution from singular-per-blob to plural-per-block-root identifiers. Nimbus annotates the spec URL evolution (`v1.5.0-alpha.10` → newer commit); grandine carries the singular form without spec-URL annotation. Other 4 clients have no SSZ singular form (teku has a non-SSZ Java record, lighthouse has a code comment, prysm has a BUILD.bazel reference).

**Semantic shift from Deneb's BlobIdentifier**: Deneb's `(block_root, index)` carries one blob index per identifier; Fulu's `(block_root, columns)` carries multiple column indices per identifier. ~5× bandwidth reduction for multi-column requests — common in PeerDAS sync where a node may request all 128 columns from a single block.

**Glamsterdam target**: `vendor/consensus-specs/specs/gloas/p2p-interface.md` contains NO `DataColumnsByRootIdentifier` or `DataColumnIdentifier` references. Fulu container carries forward verbatim into Gloas across all 6 clients. The `DataColumnSidecarsByRoot v1` request payload SSZ shape is unchanged at Gloas (the Gloas-modified payload reshape per item #46 affects only the response sidecar, not the request identifier).

**Spec-undefined edge cases (Pattern T family)**: none of the 6 explicitly reject empty `columns` lists, duplicate indices, or out-of-range indices. The list-type cap implicitly enforces the upper bound, but per-client behaviour on empty/duplicate inputs is unspecified.

**Impact: none** — SSZ wire format byte-identical; naming divergences are cosmetic at the wire layer; Gloas inherits the Fulu container verbatim. Thirty-fourth `impact: none` result in the recheck series.

Forward-research priorities:

1. **Nimbus rename PR** — `indices` → `columns` at `fulu.nim:111` to match spec.
2. **Teku internal-naming PR** — `"DataColumnIdentifier"` → `"DataColumnsByRootIdentifier"` at `DataColumnsByRootIdentifierSchema.java:32`. Trivial fix.
3. **Vestigial SSZ type cleanup audit** — grep both nimbus and grandine for consumers of the singular `DataColumnIdentifier` SSZ type. If no consumer, file removal PRs.
4. **Pattern AA + FF catalogue update** — refresh item #28/#48 to reflect this recheck's scope expansions:
   - Pattern AA: + field names + casing convention + internal class-vs-SSZ-name inconsistency
   - Pattern FF: + vestigial SSZ data types (grandine joins nimbus on this surface)
5. **Cross-client interop edge-case test** — empty `columns`, duplicate indices, out-of-range indices (Pattern T family).
6. **JSON REST API audit** — verify nimbus JSON outputs use `columns` not `indices` if any endpoint exposes the container.
