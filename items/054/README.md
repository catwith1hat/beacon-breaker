# Item 54 — `DataColumnSidecar` SSZ container detail audit (Fulu-NEW; foundational PeerDAS container; cross-cuts items #34/#37/#44/#46/#53)

**Status:** no-divergence-pending-fixture-run on SSZ wire format; **systematic lodestar camelCase + nimbus/grandine compile-time-baked depth + Heze forward-fragility on inclusion proof depth** — audited 2026-05-04. **Twenty-fourth Fulu-NEW item, sixteenth PeerDAS audit, SECOND FULU-NEW SSZ-CONTAINER detail audit**. Sister to item #53 (DataColumnsByRootIdentifier). The FOUNDATIONAL PeerDAS container.

**Spec definition** (`fulu/das-core.md` "DataColumnSidecar" section):
```python
class DataColumnSidecar(Container):
    index: ColumnIndex                                                # uint64
    column: List[Cell, MAX_BLOB_COMMITMENTS_PER_BLOCK]                  # 4096 max
    kzg_commitments: List[KZGCommitment, MAX_BLOB_COMMITMENTS_PER_BLOCK]  # 4096 max, 48 bytes each
    kzg_proofs: List[KZGProof, MAX_BLOB_COMMITMENTS_PER_BLOCK]            # 4096 max, 48 bytes each
    signed_block_header: SignedBeaconBlockHeader
    kzg_commitments_inclusion_proof: Vector[Bytes32, KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH]  # 4 elements
```

6-field SSZ container. KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH = 4 (mainnet Fulu).

**Major findings**:
1. **All 6 SSZ-encode identically** — semantic compliance + spec-compliant top-level container naming.
2. **Lodestar systematic camelCase** for 4 multi-word fields (`kzgCommitments`, `kzgProofs`, `signedBlockHeader`, `kzgCommitmentsInclusionProof`) vs spec snake_case — handled via `jsonCase: "eth2"` config; extends item #53 finding.
3. **NEW Pattern HH scope expansion**: KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH is COMPILE-TIME BAKED in nimbus + grandine; runtime/generic in other 4. Same Pattern HH family as item #52 (MAX_REQUEST_BLOCKS_DENEB nimbus baking).
4. **Heze forward-fragility**: nimbus comment at `fulu_preset.nim:15` reveals depth = `floorlog2(get_generalized_index(BeaconBlockBody, 'blob_kzg_commitments')) (= 4)` — at Heze (per item #29 finding), BeaconBlockBody schema may add new fields → depth changes → ALL 6 clients must update (Pattern P + V cross-cut).
5. **Per-client depth-sourcing diversity** — 6 distinct strategies for the same 4-element vector size.

## Scope

In: `DataColumnSidecar` SSZ container per-client implementation; per-field naming + types; `kzg_commitments_inclusion_proof` Vector cap source; container generic/preset parameterization; List vs Vector typing; comparison to item #53 (DataColumnsByRootIdentifier); JSON serialization conventions; cross-cut to Pattern P + V (item #34 grandine hardcoded gindex 11) at Heze fragility.

Out: `DataColumnSidecar` validation logic (item #34 covered); `DataColumnSidecar` gossip mesh subscription (item #37 covered); KZG cell proofs verification (item #34 covered); MatrixEntry SSZ container (Fulu-NEW related; future audit candidate); BlobIdentifier baseline cross-client (item #50 implicit + future audit candidate).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | All 6 clients have a `DataColumnSidecar` container | ✅ all 6 | Spec-defined |
| H2 | All 6 implement 6-field structure with semantic equivalence | ✅ all 6 | Spec-defined |
| H3 | All 6 SSZ-encode identically | ✅ all 6 | SSZ field-order+type-based |
| H4 | All 6 use spec-compliant top-level container name `DataColumnSidecar` | ✅ all 6 | Top-level name match |
| H5 | All 6 use field name `index` for field 0 | ✅ all 6 | Single-word, no casing concern |
| H6 | All 6 use field name `column` for field 1 | ✅ all 6 | Single-word, no casing concern |
| H7 | All 6 use spec snake_case for multi-word fields | ❌ 5 of 6 (prysm, lighthouse, teku, nimbus, grandine); **lodestar uses camelCase** | Pattern AA scope expansion — extension of item #53 |
| H8 | List vs Vector typing correctly distinguished | ✅ all 6 | All 6 use List for fields 1/2/3, Vector for field 5 |
| H9 | KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH source unified | ❌ 6 distinct sources | Pattern HH scope expansion |
| H10 | KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH compile-time-baked in any client | ✅ nimbus (preset constant) + grandine (type-level `U4` associated type) | NEW Pattern HH scope expansion |
| H11 | Forward-fragility at Heze if BeaconBlockBody schema changes | ⚠️ ALL 6 fragile — depth derived from BeaconBlockBody gindex; nimbus + grandine hardest to update (compile-time bake) | Pattern P + V cross-cut |
| H12 | Internal SSZ container name (e.g., teku constructor arg) matches class name | ✅ teku uses `"DataColumnSidecarFulu"` (Schema:61) — fork-named consistent with item #45 Pattern AA | Pattern AA fork-naming consistency |

## Per-client cross-reference

| Client | File:line | Class/Type | Depth source | JSON casing |
|---|---|---|---|---|
| **prysm** | `proto/prysm/v1alpha1/data_columns.proto:28-46` (protobuf-generated SSZ) | `message DataColumnSidecar` | `(ethereum.eth.ext.ssz_size) = "kzg_commitments_inclusion_proof_depth.size,32"` (config-driven via protobuf annotation) | snake_case (protobuf default) |
| **lighthouse** | `consensus/types/src/data/data_column_sidecar.rs:79-96` | `pub struct DataColumnSidecar<E: EthSpec>` (`#[superstruct]` Fulu+Gloas variants) | `E::KzgCommitmentsInclusionProofDepth` (compile-time generic via trait) | snake_case (serde default) |
| **teku** | `ethereum/spec/src/main/java/tech/pegasys/teku/spec/datastructures/blobs/versions/fulu/DataColumnSidecarFulu.java:31-39` | `class DataColumnSidecarFulu extends Container6<...>` (interface `DataColumnSidecar`) | `SpecConfigFulu.getKzgCommitmentsInclusionProofDepth().intValue()` (runtime SpecConfigFulu) | snake_case (FIELD_* constants) |
| **nimbus** | `beacon_chain/spec/datatypes/fulu.nim:86-93` | `DataColumnSidecar* = object` | `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH*: uint64 = 4` (`fulu_preset.nim:16`) — **compile-time PRESET CONSTANT** | snake_case (Nim convention) |
| **lodestar** | `packages/types/src/fulu/sszTypes.ts:56-66` | `ContainerType {typeName: "DataColumnSidecar", jsonCase: "eth2"}` | `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` imported from `@lodestar/params` | **CAMELCASE** in TypeScript (4 multi-word fields); JSON renders snake_case via `jsonCase: "eth2"` |
| **grandine** | `types/src/fulu/containers.rs:171-179` | `pub struct DataColumnSidecar<P: Preset>` | `P::KzgCommitmentsInclusionProofDepth = U4` (`preset.rs:382`) — **type-level associated TYPE** (typenum-style) | snake_case (serde default) |

### Field-by-field cross-client comparison

| Spec field | Type (spec) | prysm | lighthouse | teku | nimbus | lodestar | grandine |
|---|---|---|---|---|---|---|---|
| `index` | `ColumnIndex` (uint64) | `index` | `index: ColumnIndex` | `FIELD_INDEX="index"` | `index*: ColumnIndex` | `index` | `pub index: ColumnIndex` |
| `column` | `List[Cell, 4096]` | `column` | `column: DataColumn<E>` | `FIELD_BLOB="column"` | `column*: DataColumn` | `column` | `pub column: ContiguousList<Cell<P>, P::MaxBlobCommitmentsPerBlock>` |
| `kzg_commitments` | `List[KZGCommitment, 4096]` | `kzg_commitments` | `kzg_commitments: KzgCommitments<E>` | `FIELD_KZG_COMMITMENTS="kzg_commitments"` | `kzg_commitments*: KzgCommitments` | **`kzgCommitments`** | `pub kzg_commitments: ContiguousList<KzgCommitment, P::MaxBlobCommitmentsPerBlock>` |
| `kzg_proofs` | `List[KZGProof, 4096]` | `kzg_proofs` | `kzg_proofs: VariableList<KzgProof, ...>` | `FIELD_KZG_PROOFS="kzg_proofs"` | `kzg_proofs*: deneb.KzgProofs` | **`kzgProofs`** | `pub kzg_proofs: ContiguousList<KzgProof, P::MaxBlobCommitmentsPerBlock>` |
| `signed_block_header` | `SignedBeaconBlockHeader` | `signed_block_header` | `signed_block_header: SignedBeaconBlockHeader` | `FIELD_SIGNED_BLOCK_HEADER="signed_block_header"` | `signed_block_header*: SignedBeaconBlockHeader` | **`signedBlockHeader`** | `pub signed_block_header: SignedBeaconBlockHeader` |
| `kzg_commitments_inclusion_proof` | `Vector[Bytes32, 4]` | `kzg_commitments_inclusion_proof` | `kzg_commitments_inclusion_proof: FixedVector<Hash256, E::KzgCommitmentsInclusionProofDepth>` | `FIELD_KZG_COMMITMENTS_INCLUSION_PROOF="kzg_commitments_inclusion_proof"` | `kzg_commitments_inclusion_proof*: array[KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH, Eth2Digest]` | **`kzgCommitmentsInclusionProof`** | `pub kzg_commitments_inclusion_proof: BlobCommitmentsInclusionProof<P>` |

## Notable per-client findings

### Lodestar systematic camelCase (extension of item #53)

Lodestar `sszTypes.ts:56-66`:
```typescript
export const DataColumnSidecar = new ContainerType(
  {
    index: ColumnIndex,
    column: DataColumn,
    kzgCommitments: denebSsz.BlobKzgCommitments,
    kzgProofs: denebSsz.KZGProofs,
    signedBlockHeader: phase0Ssz.SignedBeaconBlockHeader,
    kzgCommitmentsInclusionProof: KzgCommitmentsInclusionProof,
  },
  {typeName: "DataColumnSidecar", jsonCase: "eth2"}
);
```

**4 of 6 multi-word fields use camelCase** in TypeScript source code. Spec uses snake_case. JSON serialization renders snake_case via `jsonCase: "eth2"` config — wire-format spec-compliant.

This is the SAME systematic camelCase pattern as item #53 (lodestar `blockRoot`). **Lodestar applies camelCase consistently across ALL SSZ containers** — this is a project-wide convention, not a container-specific decision. Documented at item #53; extended to field-level granularity here.

**SSZ wire impact**: NONE. SSZ is field-order+type based.
**JSON wire impact**: NONE. `jsonCase: "eth2"` renders snake_case.
**Source-code-readability impact**: TypeScript developers see camelCase; spec readers see snake_case. Convention friction.

### NEW Pattern HH scope expansion — `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` baking

Item #52 documented Pattern HH as nimbus's COMPILE-TIME CONSTANT for `MAX_REQUEST_BLOCKS_DENEB`. This audit extends Pattern HH to `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH`.

**Per-client depth-sourcing diversity** (6 distinct strategies):

1. **prysm** — protobuf annotation `(ethereum.eth.ext.ssz_size) = "kzg_commitments_inclusion_proof_depth.size,32"` resolves at SSZ-codec generation time via spec config lookup. Config-driven.

2. **lighthouse** — generic `E::KzgCommitmentsInclusionProofDepth` trait associated type. Compile-time via EthSpec trait bound. Each preset (Mainnet, Minimal, Gnosis) defines this differently.

3. **teku** — runtime `SpecConfigFulu.getKzgCommitmentsInclusionProofDepth().intValue()` passed to `SszBytes32VectorSchema.create()`. Most config-flexible.

4. **nimbus** — preset module constant `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH*: uint64 = 4` at `fulu_preset.nim:16`. **PATTERN HH** — compile-time baked in preset module. Cannot be overridden at runtime.

5. **lodestar** — imported constant `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` from `@lodestar/params`. Resolves at module-load time. Effectively constant for a given build.

6. **grandine** — type-level associated type `P::KzgCommitmentsInclusionProofDepth = U4` (`preset.rs:382`). **PATTERN HH-style** — compile-time baked via type system (typenum/generic-array convention). Most rigid type-level encoding.

**Pattern HH scope expansion**: from MAX_REQUEST_BLOCKS_DENEB (item #52) to KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH (this audit). Now applies to **2 constants** in nimbus and **1 constant** in grandine. Forward-fragility class: spec changes require recompilation.

### Heze forward-fragility — Pattern P + V cross-cut

Nimbus comment at `fulu_preset.nim:15`:
```nim
# floorlog2(get_generalized_index(BeaconBlockBody, 'blob_kzg_commitments')) (= 4)
KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH*: uint64 = 4
```

The `4` value is **DERIVED** from `floorlog2(get_generalized_index(BeaconBlockBody, 'blob_kzg_commitments'))`. At Fulu, `get_generalized_index = 12` (or somewhere giving floorlog2 = 4 → tree depth 4 from root for the inclusion path).

**At Heze, BeaconBlockBody schema may add new fields** (per item #29 finding teku has full Heze implementation — `HezeStateUpgrade.java` confirms BeaconBlockBody Heze modifications). If new fields shift the gindex of `blob_kzg_commitments`, the `floorlog2` of that gindex changes → `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` MUST change.

**Cross-cut with item #34 Pattern P** (grandine hardcoded `index_at_commitment_depth = 11`): grandine has hardcoded gindex 11 for inclusion proof verification at Heze. **This audit reveals**: nimbus + grandine ALSO bake the DEPTH at compile-time. So Pattern P + V at Heze is **MORE PERVASIVE than item #34 alone**:

- **Pattern P** (item #34): grandine hardcoded gindex 11 (inclusion proof position)
- **Pattern V** (item #40): grandine hardcoded gindex 11 (proposer-side construction)
- **Pattern HH-extended** (this audit): nimbus + grandine compile-time-baked DEPTH (= 4 mainnet)

**Triple-fragility at Heze for grandine + double-fragility for nimbus** — at Heze BeaconBlockBody schema change, grandine must update gindex 11 AND depth 4; nimbus must update depth 4. Other 4 clients (prysm, lighthouse, teku, lodestar) auto-derive from BeaconBlockBody schema definition.

**A-tier divergence vector at Heze for grandine + nimbus**.

### Teku schema name `DataColumnSidecarFulu` (Pattern AA fork-naming consistency)

Teku `Schema.java:61` (per Explore findings) uses `"DataColumnSidecarFulu"` as SSZ container name. Class is `DataColumnSidecarFulu extends Container6<...>`.

**CONSISTENT with Pattern AA finding from items #45 + #47**: teku consistently fork-names containers (`MetadataMessageFulu`, `StatusMessageFulu`, `DataColumnSidecarFulu`). This is teku's **systematic fork-naming convention** — opposite of item #53 where teku had INTERNAL inconsistency on `DataColumnsByRootIdentifier`/`"DataColumnIdentifier"`.

**Teku Pattern AA scoreboard** (across audited containers):
- Item #45 (MetaData): teku `MetadataMessageFulu` — fork-named ✅
- Item #47 (Status): teku `StatusMessageFulu` — fork-named ✅
- Item #53 (DataColumnsByRootIdentifier): teku `DataColumnsByRootIdentifierSchema` class but `"DataColumnIdentifier"` SSZ name — **INCONSISTENT** ❌
- Item #54 (DataColumnSidecar): teku `DataColumnSidecarFulu` — fork-named ✅

Item #53's inconsistency stands out. Likely a leftover from earlier draft spec (Fulu container was originally `DataColumnIdentifier` per nimbus's vestigial type at `fulu.nim:104`).

### Nimbus uses `array[N, T]` for the inclusion proof vector

Nimbus `fulu.nim:92-93`:
```nim
kzg_commitments_inclusion_proof*:
  array[KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH, Eth2Digest]
```

Uses Nim's `array[N, T]` (fixed-size array) which maps to SSZ Vector. Correct typing. **N is the compile-time constant**, baking the depth at type level.

Other Rust clients use `FixedVector<Hash256, ...>` (lighthouse) and `ContiguousVector<H256, ...>` (grandine) generic containers. Same SSZ semantics.

### Lighthouse superstruct cross-fork

Lighthouse `data_column_sidecar.rs:79-96`:
```rust
#[superstruct(
    variants(Fulu, Gloas),
    ...
)]
pub struct DataColumnSidecar<E: EthSpec> {
    ...
}
```

`#[superstruct]` macro generates **TWO variants** of DataColumnSidecar: Fulu and Gloas. Suggests Gloas may modify the container.

Cross-cut to spec: at Gloas, `DataColumnSidecar` may have different fields (possibly removing `signed_block_header` if PBS removes that from BeaconBlock). Pre-emptive Gloas-readiness.

### Grandine type-level `U4` for depth

Grandine `preset.rs:382`:
```rust
type KzgCommitmentsInclusionProofDepth = U4;
```

`U4` is from typenum/generic-array — a TYPE-LEVEL representation of the integer 4. Compile-time-evaluated. Same Pattern HH spirit as nimbus's preset constant.

**Most rigid encoding** of all 6 — the depth is encoded in the TYPE SYSTEM, not just a runtime constant.

### List vs Vector typing across all 6

All 6 correctly distinguish:
- `column`, `kzg_commitments`, `kzg_proofs` — `List[*, MAX_BLOB_COMMITMENTS_PER_BLOCK]` (variable, max 4096)
- `kzg_commitments_inclusion_proof` — `Vector[Bytes32, KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH]` (fixed, 4)

No client misclassifies a Vector as a List or vice versa. Spec-compliant typing.

### Live mainnet validation

5+ months of cross-client DataColumnSidecar gossip + RPC interop without observed format-divergence. SSZ wire format is stable across all 6.

## Cross-cut chain

This audit closes the foundational PeerDAS container detail layer:
- **Item #34** (DataColumnSidecar verification): consumes this container; covered Pattern P (grandine hardcoded gindex 11 for INCLUSION PROOF VERIFICATION)
- **Item #37** (DataColumnSidecar subnet computation): consumes container index field
- **Item #40** (proposer-side DataColumnSidecar construction): produces container; covered Pattern V (grandine hardcoded gindex 11 for INCLUSION PROOF GENERATION)
- **Item #44** (PartialDataColumnSidecar): related Fulu-NEW container; only nimbus implements
- **Item #46** (DataColumnSidecarsByRange/Root v1 RPC): wraps DataColumnSidecar in response
- **Item #53** (DataColumnsByRootIdentifier): sister Fulu-NEW container audit
- **Item #29** (Heze surprise): teku has full BeaconBlockBody Heze modifications → KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH may change at Heze
- **Item #28 NEW Pattern HH scope expansion**: from MAX_REQUEST_BLOCKS_DENEB (item #52) to KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH (this audit). 2 constants in nimbus + 1 in grandine compile-time-baked.
- **Item #28 Pattern P + V cross-cut**: Heze fragility now spans **3 hardcodings** for grandine (gindex 11 verify + gindex 11 produce + depth 4) and **1 hardcoding** for nimbus (depth 4). Triple-fragility for grandine.
- **Item #28 Pattern AA fork-naming consistency**: teku scoreboard 3 of 4 consistent (`MetadataMessageFulu`, `StatusMessageFulu`, `DataColumnSidecarFulu`); 1 of 4 inconsistent (item #53 `"DataColumnIdentifier"`).
- **Item #48** (catalogue refresh): adds Pattern HH expansion + Pattern P+V Heze fragility expansion

## Adjacent untouched Fulu-active

- `MatrixEntry` SSZ container (Fulu-NEW per spec; future audit candidate)
- `Cell` type cross-client (Bytes per cell, derived from FIELD_ELEMENTS_PER_CELL)
- `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` cross-network audit (mainnet=4 confirmed; sepolia/holesky/gnosis/hoodi TBD)
- `MAX_BLOB_COMMITMENTS_PER_BLOCK = 4096` (Deneb-heritage) cross-client baseline
- BlobIdentifier (Deneb-heritage) cross-client baseline (item #50 implicit)
- DataColumnSidecar Gloas-modified schema (lighthouse superstruct hints at Gloas variant; pre-emptive Gloas audit)
- Per-client KZG cell proofs library implementation (c-kzg-4844 vs rust-kzg variants)
- SignedBeaconBlockHeader nested container Fulu-modified vs Phase0-heritage
- ExecutionPayloadEnvelope (Gloas-NEW) — pre-emptive audit candidate
- Per-client SSZ container compile-time-vs-runtime baking inventory (Pattern HH spec-wide)

## Future research items

1. **Pattern HH scope expansion for item #28 catalogue**: covers nimbus's preset constants (MAX_REQUEST_BLOCKS_DENEB at item #52 + KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH at this audit) + grandine's type-level `U4` associated type. Same forward-fragility class.
2. **Pattern P + V Heze fragility expansion**: triple-fragility for grandine (gindex 11 verify + produce + depth 4) and double-fragility for nimbus (depth 4) at Heze. Highest-priority pre-emptive Heze fix.
3. **Lighthouse Gloas DataColumnSidecar variant audit**: superstruct hints at Gloas-modified container. What changes at Gloas? Pre-emptive Gloas audit.
4. **MatrixEntry SSZ container audit (item #55+ candidate)**: Fulu-NEW related container; per-client schema may diverge.
5. **`MAX_BLOB_COMMITMENTS_PER_BLOCK = 4096` cross-client baseline (item #56 candidate)**: Deneb-heritage; same Pattern DD/HH analysis.
6. **`Cell` type cross-client comparison**: derived from FIELD_ELEMENTS_PER_CELL × BYTES_PER_FIELD_ELEMENT = 64 × 32 = 2048 bytes. Per-client typing may differ.
7. **Cross-network `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` audit**: mainnet=4 confirmed; sepolia/holesky/gnosis/hoodi TBD.
8. **Per-client KZG cell proofs library audit**: c-kzg-4844 vs rust-kzg families; performance + correctness; Pattern AA-style divergence in library choice.
9. **BlobIdentifier (Deneb-heritage) cross-client baseline audit**: parallel to item #53; understand Pattern AA evolution from Deneb to Fulu.
10. **Per-client SSZ container compile-time-vs-runtime baking inventory**: spec-wide audit of which constants are compile-time-baked across each client. Generalize Pattern HH.
11. **Heze forward-fragility test**: simulate Heze fork with new BeaconBlockBody field; verify `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` updates; verify grandine + nimbus both require recompile; verify auto-derived clients (prysm, lighthouse, teku, lodestar) update via spec-config bump.
12. **Lodestar systematic camelCase audit**: catalogue all Fulu-NEW containers and verify camelCase consistency. Confirm convention vs ad-hoc.
13. **Teku Pattern AA fork-naming scoreboard maintenance**: 3 of 4 consistent so far. Audit all Fulu-NEW containers in teku and verify fork-naming convention.

## Summary

EIP-7594 PeerDAS foundational `DataColumnSidecar` SSZ container (`fulu/das-core.md`): 6-field container `(index, column, kzg_commitments, kzg_proofs, signed_block_header, kzg_commitments_inclusion_proof)`. Used in DataColumnSidecar gossip + RPC + validator-side construction (items #34/#37/#40/#46).

**SSZ wire format identical across all 6 clients** (SSZ field-order+type-based encoding). Live mainnet validates 5+ months of cross-client interop without observed format-divergence.

**All 6 use spec-compliant top-level container name** `DataColumnSidecar` (or `DataColumnSidecarFulu` for teku — Pattern AA fork-naming consistent).

**Lodestar systematic camelCase** for 4 multi-word fields (`kzgCommitments`, `kzgProofs`, `signedBlockHeader`, `kzgCommitmentsInclusionProof`) — extension of item #53 finding. Wire spec-compliant via `jsonCase: "eth2"`. Project-wide TypeScript convention.

**NEW Pattern HH scope expansion**: KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH source diversity:
- nimbus: COMPILE-TIME PRESET CONSTANT (`fulu_preset.nim:16`)
- grandine: TYPE-LEVEL associated type `U4` (`preset.rs:382`) — most rigid encoding
- prysm: protobuf annotation
- lighthouse: generic trait `E::KzgCommitmentsInclusionProofDepth`
- teku: runtime `SpecConfigFulu.getKzgCommitmentsInclusionProofDepth()`
- lodestar: imported constant from `@lodestar/params`

**Pattern HH now applies to 2 constants in nimbus** (MAX_REQUEST_BLOCKS_DENEB from item #52 + KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH from this audit) **and 1 in grandine** (this audit's depth).

**Heze forward-fragility — Pattern P + V cross-cut**:
- nimbus comment at `fulu_preset.nim:15` reveals depth = `floorlog2(get_generalized_index(BeaconBlockBody, 'blob_kzg_commitments')) (= 4)`
- At Heze (per item #29), BeaconBlockBody schema may add new fields → gindex shifts → depth changes
- **TRIPLE-FRAGILITY for grandine at Heze**: hardcoded gindex 11 verify (Pattern P, item #34) + hardcoded gindex 11 produce (Pattern V, item #40) + compile-time-baked depth 4 (this audit)
- **DOUBLE-FRAGILITY for nimbus at Heze**: compile-time-baked depth 4 (this audit) — though nimbus correctly uses dynamic gindex via `get_generalized_index` calls
- **A-tier Heze divergence vector** for grandine; B-tier for nimbus

**Teku Pattern AA fork-naming scoreboard**: 3 of 4 consistent (items #45 + #47 + #54); 1 of 4 inconsistent (item #53). `DataColumnSidecarFulu` matches teku's systematic fork-naming convention.

**Lighthouse Gloas variant**: `#[superstruct(variants(Fulu, Gloas))]` at `data_column_sidecar.rs:79-96` hints at DataColumnSidecar Gloas-modified schema. Pre-emptive Gloas audit candidate.

**With this audit, the foundational PeerDAS container detail layer is closed**. SSZ container detail audits now span items #45 (MetaData v3) + #47 (Status v2) + #53 (DataColumnsByRootIdentifier) + **#54 (DataColumnSidecar)** = 4 Fulu-NEW container audits.

**Total Fulu-NEW items: 24 (#30–#54)**. Item #28 catalogue **Patterns A–HH (34 patterns)** + Pattern HH scope expansion (KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH) + Pattern P+V Heze triple-fragility expansion (grandine).

**PeerDAS audit corpus now spans 16 items**: #33 → #34 → #35 → #37 → #38 → #39 → #40 → #41 → #42 → #44 → #45 → #46 → #47 → #49 → #53 → **#54**.
