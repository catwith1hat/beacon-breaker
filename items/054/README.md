---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [28, 29, 34, 37, 40, 44, 45, 46, 52, 53]
eips: [EIP-7594, EIP-7732, EIP-7805]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.3
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.3.1
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 54: `DataColumnSidecar` SSZ container — Fulu 6-field + Gloas 5-field reshape (EIP-7732); Pattern HH depth baking; Pattern M cohort extends

## Summary

Foundational PeerDAS container. The Fulu shape (`vendor/consensus-specs/specs/fulu/das-core.md`) has 6 fields:

```python
class DataColumnSidecar(Container):
    index: ColumnIndex
    column: List[Cell, MAX_BLOB_COMMITMENTS_PER_BLOCK]
    kzg_commitments: List[KZGCommitment, MAX_BLOB_COMMITMENTS_PER_BLOCK]
    kzg_proofs: List[KZGProof, MAX_BLOB_COMMITMENTS_PER_BLOCK]
    signed_block_header: SignedBeaconBlockHeader
    kzg_commitments_inclusion_proof: Vector[Bytes32, KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH]  # depth = 4 mainnet
```

At Gloas the container is **MODIFIED** per `vendor/consensus-specs/specs/gloas/p2p-interface.md:57-81` (EIP-7732):

```python
class DataColumnSidecar(Container):
    index: ColumnIndex
    column: List[Cell, MAX_BLOB_COMMITMENTS_PER_BLOCK]
    # [Modified in Gloas:EIP7732]
    # Removed `kzg_commitments`
    kzg_proofs: List[KZGProof, MAX_BLOB_COMMITMENTS_PER_BLOCK]
    # [Modified in Gloas:EIP7732]
    # Removed `signed_block_header`
    # [Modified in Gloas:EIP7732]
    # Removed `kzg_commitments_inclusion_proof`
    # [New in Gloas:EIP7732]
    slot: Slot
    # [New in Gloas:EIP7732]
    beacon_block_root: Root
```

5 fields at Gloas — `kzg_commitments`, `signed_block_header`, and `kzg_commitments_inclusion_proof` are all REMOVED; `slot` and `beacon_block_root` are added. The KZG commitments authority moves to `block.body.signed_execution_payload_bid.message.blob_kzg_commitments`.

**Fulu surface (carried forward from 2026-05-04 audit):** all 6 clients SSZ-encode the 6-field Fulu container byte-identically. 5+ months of mainnet cross-client `DataColumnSidecar` gossip + RPC interop validates wire-format compatibility.

**Gloas surface (Glamsterdam target) — per-client variant implementation status**:

- **prysm** (`vendor/prysm/proto/prysm/v1alpha1/gloas.proto:464-479`): separate `DataColumnSidecarGloas` proto message. **5 fields** per spec — `index, column, kzg_proofs, slot, beacon_block_root`. Spec-compliant. Proto field numbers go 1,2,4,5,6 (gap at 3 traces removed `kzg_commitments`).
- **teku** (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/datastructures/blobs/versions/gloas/DataColumnSidecarGloas.java:30-94`): `Container5<DataColumnSidecarGloas, SszUInt64, DataColumn, SszList<SszKZGProof>, SszUInt64, SszBytes32>`. **5 fields** per spec. Schema returns `Optional.empty()` for `getMaybeKzgCommitments` (`:72`) and `getMaybeSignedBlockHeader` (`:91-93`), explicitly documenting removal.
- **nimbus** (`vendor/nimbus/beacon_chain/spec/datatypes/gloas.nim:53-68`): `DataColumnSidecar* = object` with explicit `# Removed kzg_commitments`, `# Removed signed_block_header`, `# Removed kzg_commitments_inclusion_proof` annotation comments tracking the spec EIP-7732 modifications. **5 fields** per spec.
- **lodestar** (`vendor/lodestar/packages/types/src/gloas/sszTypes.ts:301-313`): `ContainerType {index, column, kzgProofs, slot, beaconBlockRoot}` with inline comments documenting the removed fields. **5 fields** per spec (camelCase per lodestar convention).
- **grandine** (`vendor/grandine/types/src/gloas/containers.rs:97-105`): `pub struct DataColumnSidecar<P: Preset> {index, column, kzg_proofs, slot, beacon_block_root}`. **5 fields** per spec.
- **lighthouse** (`vendor/lighthouse/consensus/types/src/data/data_column_sidecar.rs:79-96`): superstruct with `variants(Fulu, Gloas)` BUT **`kzg_commitments` is in the common base struct** (line 85 with no `#[superstruct(only(Fulu))]` annotation). The Gloas variant therefore carries 6 fields `(index, column, kzg_commitments, kzg_proofs, slot, beacon_block_root)`. Confirmed at `:207-220 DataColumnSidecarGloas::min_size()` which constructs the struct with `kzg_commitments: VariableList::new(vec![KzgCommitment::empty_for_testing()])`. **DIVERGES FROM SPEC** — retains the field that EIP-7732 removes.

**Pattern M Gloas-ePBS readiness cohort extends with another lighthouse symptom**: at Gloas activation, lighthouse would produce 6-field DataColumnSidecar SSZ bytes while the other 5 produce 5-field bytes. **Cross-client SSZ wire incompatibility at Gloas activation.** Lighthouse's Gloas DataColumnSidecar tree-hash root would also diverge from the spec's expected value — `ssz_static` spec-test fixtures would catch this.

**Pattern HH (compile-time-baked constants, item #52 carry-forward)**: `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` (depth = 4 mainnet) is baked compile-time in 2 clients:

- **nimbus** (`vendor/nimbus/beacon_chain/spec/presets/mainnet/fulu_preset.nim:16 KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH*: uint64 = 4`; gnosis + minimal presets identical).
- **grandine** (`vendor/grandine/types/src/preset.rs:382 type KzgCommitmentsInclusionProofDepth = U4`) — type-level associated type via typenum.

Other 4 derive from runtime config (prysm protobuf annotation; lighthouse generic `E::KzgCommitmentsInclusionProofDepth` trait; teku `SpecConfigFulu.getKzgCommitmentsInclusionProofDepth()`; lodestar import from `@lodestar/params`).

**At Gloas this constant becomes dead** — the Gloas sidecar omits `kzg_commitments_inclusion_proof`. Pattern HH applies only to the Fulu surface (since the Fulu container persists in code until callers stop using it; Gloas-modified container uses the new shape). This makes Pattern HH on this constant a Fulu-only concern.

**Pattern HH cross-cut with Pattern P + V (grandine hardcoded gindex 11, items #34 + #40)**: at Fulu, grandine's hardcoded gindex 11 + nimbus + grandine compile-time-baked depth 4 are forward-fragile if a future spec change (e.g. Heze per item #29) modifies BeaconBlockBody schema in a way that shifts the `blob_kzg_commitments` gindex. At Gloas the entire inclusion-proof verification path is dead, so this concern disappears at Gloas — but the Fulu code path remains live during the Gloas transition.

**Pattern AA scope expansion (item #53 carry-forward)**: lodestar camelCase applies at both Fulu and Gloas variants (`kzgCommitments`, `kzgProofs`, `signedBlockHeader`, `kzgCommitmentsInclusionProof` at Fulu; `kzgProofs`, `beaconBlockRoot` at Gloas) — mapped to spec snake_case via `jsonCase: "eth2"`. Teku uses fork-named class names consistently (`DataColumnSidecarFulu`, `DataColumnSidecarGloas`) — Pattern AA fork-naming consistency.

**Impact: none** — Fulu surface byte-identical across all 6 (validated by 5+ months of mainnet); Gloas reshape is not mainnet-reachable (`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH`). The lighthouse Gloas variant divergence is forward-fragility tracking only, not present-tense divergence. Thirty-fifth `impact: none` result in the recheck series.

## Question

Pyspec defines the Fulu container at `vendor/consensus-specs/specs/fulu/das-core.md` and the Gloas modification at `vendor/consensus-specs/specs/gloas/p2p-interface.md:57-81` (EIP-7732 — removes `kzg_commitments`, `signed_block_header`, `kzg_commitments_inclusion_proof`; adds `slot`, `beacon_block_root`).

Three recheck questions:

1. **Fulu surface stability** — do all 6 clients still SSZ-encode the 6-field Fulu container byte-identically? Has any client introduced a regression since the 2026-05-04 audit?
2. **Glamsterdam target — Gloas variant implementation** — which clients implement the spec-compliant 5-field Gloas variant? Which clients retain pre-EIP-7732 fields?
3. **Pattern HH + AA scope** — does compile-time depth baking persist in nimbus + grandine? Does Pattern AA fork-naming consistency hold for teku?

## Hypotheses

- **H1.** Fulu DataColumnSidecar is a 6-field container across all 6 clients.
- **H2.** All 6 SSZ-encode the Fulu container byte-identically.
- **H3.** Pattern HH (compile-time-baked `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH`) persists in nimbus + grandine.
- **H4.** Pattern AA (lodestar camelCase) applies systematically at Fulu and Gloas variants.
- **H5.** Pattern AA fork-naming (teku `DataColumnSidecarFulu`, `DataColumnSidecarGloas`) consistent.
- **H6.** *(Glamsterdam target — Gloas modification)* spec removes `kzg_commitments`, `signed_block_header`, `kzg_commitments_inclusion_proof` and adds `slot`, `beacon_block_root`. Net: 5 fields.
- **H7.** *(Glamsterdam target — implementation)* prysm, teku, nimbus, lodestar, grandine implement spec-compliant 5-field Gloas variant.
- **H8.** *(Glamsterdam target — lighthouse outlier)* lighthouse Gloas variant retains `kzg_commitments` (6 fields). Pattern M cohort symptom.
- **H9.** Live mainnet validation: 5+ months without Fulu format-divergence.
- **H10.** Pattern HH constant becomes dead at Gloas (no inclusion proof in Gloas sidecar).
- **H11.** Pattern P + V (grandine gindex 11) applies only to Fulu code path; dead at Gloas.

## Findings

H1 ✓. H2 ✓. H3 ✓ (nimbus + grandine). H4 ✓. H5 ✓ (teku fork-named). H6 ✓ (spec). H7 ✓ (5-of-6 spec-compliant Gloas variants). **H8 ⚠ — confirmed**: lighthouse Gloas variant retains `kzg_commitments`. H9 ✓. H10 ✓ (Gloas container has no inclusion proof). H11 ✓ (dead at Gloas; Fulu code path remains live during transition).

### prysm

Fulu container (`vendor/prysm/proto/prysm/v1alpha1/data_columns.proto:28-46`):

```protobuf
message DataColumnSidecar {
  uint64 index = 1;
  repeated bytes column = 2 [ ... ];
  repeated bytes kzg_commitments = 3 [ ... ];
  repeated bytes kzg_proofs = 4 [ ... ];
  SignedBeaconBlockHeader signed_block_header = 5;
  repeated bytes kzg_commitments_inclusion_proof = 6
      [ (ethereum.eth.ext.ssz_size) =
            "kzg_commitments_inclusion_proof_depth.size,32" ];
}
```

Gloas variant (`vendor/prysm/proto/prysm/v1alpha1/gloas.proto:453-479`):

```protobuf
// DataColumnSidecarGloas represents a data column sidecar in the Gloas fork.
// Note: signed_block_header and kzg_commitments_inclusion_proof fields have
// been removed in Gloas.
message DataColumnSidecarGloas {
  uint64 index = 1;
  repeated bytes column = 2 [ ... ];
  repeated bytes kzg_proofs = 4 [ ... ];
  uint64 slot = 5 [ ... ];
  bytes beacon_block_root = 6 [ (ethereum.eth.ext.ssz_size) = "32" ];
}
```

Field number gap at 3 traces removed `kzg_commitments`. **Spec-compliant 5-field Gloas variant.**

Consumer wiring at `vendor/prysm/consensus-types/blocks/rodatacolumn.go:21 gloas *ethpb.DataColumnSidecarGloas` + `:47 NewRODataColumnGloas(dc *ethpb.DataColumnSidecarGloas)`.

Pattern HH category: protobuf-annotation-driven for the depth constant (not compile-time-baked). Pattern AA: spec-aligned snake_case naming.

### lighthouse

Superstruct (`vendor/lighthouse/consensus/types/src/data/data_column_sidecar.rs:42-96`):

```rust
#[superstruct(
    variants(Fulu, Gloas),
    ...
)]
pub struct DataColumnSidecar<E: EthSpec> {
    #[serde(with = "serde_utils::quoted_u64")]
    pub index: ColumnIndex,
    #[serde(with = "ssz_types::serde_utils::list_of_hex_fixed_vec")]
    pub column: DataColumn<E>,
    /// All the KZG commitments and proofs associated with the block, used for verifying sample cells.
    pub kzg_commitments: KzgCommitments<E>,
    pub kzg_proofs: VariableList<KzgProof, E::MaxBlobCommitmentsPerBlock>,
    #[superstruct(only(Fulu))]
    pub signed_block_header: SignedBeaconBlockHeader,
    #[superstruct(only(Fulu))]
    pub kzg_commitments_inclusion_proof: FixedVector<Hash256, E::KzgCommitmentsInclusionProofDepth>,
    #[superstruct(only(Gloas), partial_getter(rename = "slot_gloas"))]
    pub slot: Slot,
    #[superstruct(only(Gloas))]
    pub beacon_block_root: Hash256,
}
```

`kzg_commitments` (line 85) is in the common base — no `#[superstruct(only(Fulu))]` annotation. **The Gloas variant therefore retains `kzg_commitments`.** Confirmed at `:207-220 DataColumnSidecarGloas::min_size()` which constructs the struct with `kzg_commitments: VariableList::new(vec![KzgCommitment::empty_for_testing()])` — the field is explicitly populated for the Gloas variant in code.

**Lighthouse Gloas variant fields**: `(index, column, kzg_commitments, kzg_proofs, slot, beacon_block_root)` — **6 fields**. Spec Gloas: 5 fields (no `kzg_commitments`). **SSZ wire format diverges from spec.**

**Pattern M cohort extends**: lighthouse's pre-existing Gloas-ePBS readiness gaps (items #43 Engine API V5/V6/FCU4 + #44 PartialDataColumnSidecar missing + #46 envelope RPCs missing) now compound with a **container-schema divergence at Gloas activation**. Pre-emptive fix: change line 85 to `#[superstruct(only(Fulu))] pub kzg_commitments: KzgCommitments<E>` (or move to a new `(only(Fulu))` block) to match spec.

Pattern HH category: generic `E::KzgCommitmentsInclusionProofDepth` (compile-time via trait bound) — not baked-in-binary in the Pattern HH sense, but still trait-bound at compile time.

### teku

Fulu container (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/datastructures/blobs/versions/fulu/DataColumnSidecarFulu.java`): `Container6<...>` — 6 fields per spec.

Gloas container (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/datastructures/blobs/versions/gloas/DataColumnSidecarGloas.java:30-94`):

```java
public class DataColumnSidecarGloas
    extends Container5<
        DataColumnSidecarGloas, SszUInt64, DataColumn, SszList<SszKZGProof>, SszUInt64, SszBytes32>
    implements DataColumnSidecar {

  ...

  @Override
  public Optional<SszList<SszKZGCommitment>> getMaybeKzgCommitments() {
    return Optional.empty();
  }

  ...

  @Override
  public Optional<SignedBeaconBlockHeader> getMaybeSignedBlockHeader() {
    return Optional.empty();
  }
}
```

`Container5<...>` — **5 fields** per spec (`index, column, kzgProofs, slot, beaconBlockRoot`). Explicit `Optional.empty()` returns from `getMaybeKzgCommitments` (`:72`) and `getMaybeSignedBlockHeader` (`:91-93`) document the removal at the API level. Spec-compliant.

Pattern AA: teku consistent fork-naming (`DataColumnSidecarFulu` + `DataColumnSidecarGloas`).

Pattern HH category: runtime `SpecConfigFulu.getKzgCommitmentsInclusionProofDepth()` — most config-flexible.

### nimbus

Fulu container (`vendor/nimbus/beacon_chain/spec/datatypes/fulu.nim:86-93`):

```nim
DataColumnSidecar* = object
    index*: ColumnIndex
    column*: DataColumn
    kzg_commitments*: KzgCommitments
    kzg_proofs*: deneb.KzgProofs
    signed_block_header*: SignedBeaconBlockHeader
    kzg_commitments_inclusion_proof*:
      array[KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH, Eth2Digest]
```

6 fields. `array[N, T]` maps to SSZ Vector; `N = KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH = 4` from preset constant.

Gloas container (`vendor/nimbus/beacon_chain/spec/datatypes/gloas.nim:53-68`):

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.7.0-alpha.2/specs/gloas/p2p-interface.md#modified-datacolumnsidecar
DataColumnSidecar* = object
    index*: ColumnIndex
    column*: DataColumn
    # [Modified in Gloas:EIP7732]
    # Removed `kzg_commitments`
    kzg_proofs*: deneb.KzgProofs
    # [Modified in Gloas:EIP7732]
    # Removed `signed_block_header`
    # [Modified in Gloas:EIP7732]
    # Removed `kzg_commitments_inclusion_proof`
    # [New in Gloas:EIP7732]
    slot*: Slot
    # [New in Gloas:EIP7732]
    beacon_block_root*: Eth2Digest
```

**5 fields** per spec. Annotation comments mirror the spec's EIP-7732 modification markers — most documented of the 6 client Gloas variants.

Pattern HH category: ✅ compile-time-baked depth at preset (`fulu_preset.nim:16`, `gnosis/fulu_preset.nim:16`, `minimal/fulu_preset.nim:16`).

### lodestar

Fulu container (`vendor/lodestar/packages/types/src/fulu/sszTypes.ts:56-66`):

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

6 fields. Pattern AA camelCase for the 4 multi-word fields; spec snake_case via `jsonCase: "eth2"`.

Gloas container (`vendor/lodestar/packages/types/src/gloas/sszTypes.ts:301-313`):

```typescript
export const DataColumnSidecar = new ContainerType(
  {
    index: fuluSsz.DataColumnSidecar.fields.index,
    column: fuluSsz.DataColumnSidecar.fields.column,
    // kzgCommitments: denebSsz.BlobKzgCommitments, // Removed in GLOAS:EIP7732
    kzgProofs: fuluSsz.DataColumnSidecar.fields.kzgProofs,
    // signedBlockHeader: phase0Ssz.SignedBeaconBlockHeader, // Removed in GLOAS:EIP7732
    // kzgCommitmentsInclusionProof: KzgCommitmentsInclusionProof, // Removed in GLOAS:EIP7732
    slot: Slot, // New in GLOAS:EIP7732
    beaconBlockRoot: Root, // New in GLOAS:EIP7732
  },
  {typeName: "DataColumnSidecar", jsonCase: "eth2"}
);
```

**5 fields** per spec. Inline `// Removed in GLOAS:EIP7732` and `// New in GLOAS:EIP7732` comments document the modifications. Most explicitly documented Gloas variant.

Pattern HH category: imported constant from `@lodestar/params`.

### grandine

Fulu container (`vendor/grandine/types/src/fulu/containers.rs:171-179`): `pub struct DataColumnSidecar<P: Preset>` — 6 fields per spec, preset-parameterised via `P::MaxBlobCommitmentsPerBlock` and `P::KzgCommitmentsInclusionProofDepth`.

Gloas container (`vendor/grandine/types/src/gloas/containers.rs:95-105`):

```rust
#[derive(Clone, PartialEq, Eq, Default, Deserialize, Serialize, Ssz)]
#[serde(bound = "", deny_unknown_fields)]
pub struct DataColumnSidecar<P: Preset> {
    #[serde(with = "serde_utils::string_or_native")]
    pub index: ColumnIndex,
    pub column: ContiguousList<Cell<P>, P::MaxBlobCommitmentsPerBlock>,
    pub kzg_proofs: ContiguousList<KzgProof, P::MaxBlobCommitmentsPerBlock>,
    #[serde(with = "serde_utils::string_or_native")]
    pub slot: Slot,
    pub beacon_block_root: H256,
}
```

**5 fields** per spec. Container_impls at `vendor/grandine/types/src/gloas/container_impls.rs:58-70` provides `impl<P: Preset> DataColumnSidecar<P>` and `Debug` impl with `f.debug_struct("DataColumnSidecar")`. Spec_tests at `vendor/grandine/types/src/gloas/spec_tests.rs:169-171` reference `"consensus-spec-tests/tests/mainnet/gloas/ssz_static/DataColumnSidecar/*/*"` fixtures.

Pattern HH category: ✅ compile-time-baked depth via type-level associated type (`vendor/grandine/types/src/preset.rs:382 type KzgCommitmentsInclusionProofDepth = U4`).

## Cross-reference table

| Client | Fulu container | Gloas container | Gloas field count | Spec-compliant Gloas? | Pattern HH (depth) | Pattern AA |
|---|---|---|---|---|---|---|
| **prysm** | `data_columns.proto:28-46 message DataColumnSidecar` (6 fields) | `gloas.proto:464-479 DataColumnSidecarGloas` (proto field gap at 3 for removed kzg_commitments) | **5** ✅ | ✅ | protobuf annotation | spec-aligned snake_case |
| **lighthouse** | superstruct base `data_column_sidecar.rs:79-96 pub struct DataColumnSidecar<E: EthSpec>` (6 fields) | `DataColumnSidecarGloas` superstruct variant; **`kzg_commitments` retained in common base at `:85`** (no `#[superstruct(only(Fulu))]`); confirmed by `:207-220 min_size()` constructing with kzg_commitments | **6** ❌ (extra `kzg_commitments`) | ❌ **DIVERGES FROM SPEC** | generic `E::KzgCommitmentsInclusionProofDepth` trait | spec-aligned snake_case |
| **teku** | `versions/fulu/DataColumnSidecarFulu.java` (`Container6<...>`) | `versions/gloas/DataColumnSidecarGloas.java:30-94 extends Container5<DataColumnSidecarGloas, SszUInt64, DataColumn, SszList<SszKZGProof>, SszUInt64, SszBytes32>`; `getMaybeKzgCommitments() -> Optional.empty()` (`:72`); `getMaybeSignedBlockHeader() -> Optional.empty()` (`:91-93`) | **5** ✅ | ✅ | runtime `SpecConfigFulu.getKzgCommitmentsInclusionProofDepth()` | fork-named (`DataColumnSidecarFulu`, `DataColumnSidecarGloas`) — consistent |
| **nimbus** | `fulu.nim:86-93 DataColumnSidecar* = object` (6 fields, array-typed inclusion proof) | `gloas.nim:53-68 DataColumnSidecar* = object` with explicit `# Removed kzg_commitments`, `# Removed signed_block_header`, `# Removed kzg_commitments_inclusion_proof`, `# [New in Gloas:EIP7732]` annotations | **5** ✅ | ✅ (most documented) | ✅ **compile-time preset constant** `fulu_preset.nim:16 KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH*: uint64 = 4` (mainnet/gnosis/minimal) | spec-aligned snake_case |
| **lodestar** | `fulu/sszTypes.ts:56-66 DataColumnSidecar` (6 fields, camelCase) | `gloas/sszTypes.ts:301-313 DataColumnSidecar` (5 fields) with `// Removed in GLOAS:EIP7732` and `// New in GLOAS:EIP7732` inline comments | **5** ✅ | ✅ | imported constant `@lodestar/params` | camelCase in source; spec snake_case via `jsonCase: "eth2"` |
| **grandine** | `fulu/containers.rs:171-179 pub struct DataColumnSidecar<P: Preset>` (6 fields) | `gloas/containers.rs:95-105 pub struct DataColumnSidecar<P: Preset>` (5 fields per spec); container_impls at `gloas/container_impls.rs:58-70`; spec_tests fixture path at `gloas/spec_tests.rs:169-171` | **5** ✅ | ✅ | ✅ **type-level associated type** `preset.rs:382 type KzgCommitmentsInclusionProofDepth = U4` | spec-aligned snake_case |

**Pattern M cohort symptoms** (lighthouse only on this surface; grandine + nimbus are not Gloas-divergent here): lighthouse 6-field Gloas container instead of spec's 5. **Cross-client SSZ wire incompatibility at Gloas activation.** Other 5 clients spec-compliant.

**Pattern HH cohort (KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH baking)**: 2 of 6 — nimbus (preset constant) + grandine (type-level `U4`). Applies only to Fulu code path since Gloas container removes the inclusion proof.

**Pattern AA fork-naming consistency (teku scoreboard, carried forward)**: items #45 + #47 + #54 = 3 consistent (`MetadataMessageFulu`, `StatusMessageFulu`, `DataColumnSidecarFulu`/`Gloas`); item #53 = 1 inconsistent (`"DataColumnIdentifier"` SSZ container name vs Java class `DataColumnsByRootIdentifier`).

## Empirical tests

- ✅ **Live mainnet operation since 2025-12-03 (5+ months)**: cross-client `DataColumnSidecar` gossip + RPC interop validated. No Fulu format-divergence observed. **Verifies H1, H2, H9 at production scale.**
- ✅ **Gloas variant verification (this recheck)**: 5 of 6 clients implement spec-compliant 5-field Gloas variant; **lighthouse retains `kzg_commitments` (6 fields)** at `data_column_sidecar.rs:85` — confirmed via the absence of `#[superstruct(only(Fulu))]` annotation on the field. Pattern M cohort symptom for lighthouse.
- ✅ **Pattern HH verification**: nimbus `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH*: uint64 = 4` confirmed across mainnet/gnosis/minimal presets at `presets/{mainnet,gnosis,minimal}/fulu_preset.nim:16`. Grandine `type KzgCommitmentsInclusionProofDepth = U4` confirmed at `preset.rs:382`.
- ⏭ **Lighthouse Gloas variant fix PR**: file PR adding `#[superstruct(only(Fulu))]` annotation to `data_column_sidecar.rs:85 pub kzg_commitments: KzgCommitments<E>` (or moving it to a new `(only(Fulu))` block). Aligns lighthouse with the other 5. Closes the Pattern M cohort symptom for Gloas container.
- ⏭ **ssz_static spec-test verification**: lighthouse should run `consensus-spec-tests/tests/mainnet/gloas/ssz_static/DataColumnSidecar/*` fixtures. With the current 6-field Gloas variant, tree-hash roots will diverge from spec — CI should fail. Verify whether the spec-test harness already catches this (most likely yes, but lighthouse CI may not exercise Gloas ssz_static fixtures yet).
- ⏭ **Cross-client SSZ-encoding fixture at Gloas activation**: simulated Gloas-activation scenario; have lighthouse encode a `DataColumnSidecarGloas` and try to deserialize on prysm/teku/nimbus/lodestar/grandine. With lighthouse's current 6-field variant, the other 5 would reject the message (extra field). Confirms the Gloas-activation interop failure mode.
- ⏭ **Pattern HH catalogue audit**: extend the {`MAX_REQUEST_BLOCKS_DENEB` (nimbus, item #52), `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` (nimbus + grandine, item #54)} list. Which other compile-time-baked constants exist per-client?
- ⏭ **Cross-cut: lighthouse Gloas-ePBS readiness scorecard**: combine the symptoms from item #43 (Engine API V5/V6/FCU4 missing) + #44 (PartialDataColumnSidecar missing) + #46 (envelope RPCs missing) + #51 (gossip topic outlier — teku, not lighthouse; lighthouse is fine on that surface) + this item's DataColumnSidecar Gloas divergence. Item #48 catalogue refresh should reflect.

## Conclusion

The Fulu `DataColumnSidecar` SSZ container (6 fields: `index, column, kzg_commitments, kzg_proofs, signed_block_header, kzg_commitments_inclusion_proof`) is implemented byte-identically across all 6 clients. 5+ months of mainnet cross-client gossip + RPC interop validates wire-format compatibility.

At the Glamsterdam target, `vendor/consensus-specs/specs/gloas/p2p-interface.md:57-81` MODIFIES the container per EIP-7732 — removes `kzg_commitments`, `signed_block_header`, and `kzg_commitments_inclusion_proof`; adds `slot` and `beacon_block_root`. Net: 5 fields. The KZG commitments authority moves to `block.body.signed_execution_payload_bid.message.blob_kzg_commitments`.

**Per-client Gloas variant implementation status**:

- ✅ **prysm** (`gloas.proto:464-479`): 5-field `DataColumnSidecarGloas` proto message with field-number gap at 3 (removed `kzg_commitments`).
- ❌ **lighthouse** (`data_column_sidecar.rs:79-96, 207-220`): superstruct retains `kzg_commitments` in the common base struct at `:85` — no `#[superstruct(only(Fulu))]` annotation. The Gloas variant therefore carries 6 fields. **DIVERGES FROM SPEC.** Confirmed by `DataColumnSidecarGloas::min_size()` explicitly constructing the struct with `kzg_commitments`. At Gloas activation this produces SSZ wire bytes incompatible with the other 5 clients.
- ✅ **teku** (`DataColumnSidecarGloas.java:30-94`): `Container5<...>` 5-field variant; `getMaybeKzgCommitments() -> Optional.empty()` and `getMaybeSignedBlockHeader() -> Optional.empty()` explicit empty-Optional returns document the removal.
- ✅ **nimbus** (`gloas.nim:53-68`): 5-field container with explicit `# Removed kzg_commitments`, `# Removed signed_block_header`, `# Removed kzg_commitments_inclusion_proof`, `# [New in Gloas:EIP7732]` annotation comments — most documented variant.
- ✅ **lodestar** (`gloas/sszTypes.ts:301-313`): 5-field ContainerType with inline `// Removed in GLOAS:EIP7732` and `// New in GLOAS:EIP7732` comments documenting the modifications.
- ✅ **grandine** (`gloas/containers.rs:95-105`): 5-field struct with spec-test fixture path explicitly referencing `consensus-spec-tests/tests/mainnet/gloas/ssz_static/DataColumnSidecar/*` at `gloas/spec_tests.rs:169-171`.

**Pattern M lighthouse Gloas-ePBS readiness cohort extends with another symptom**: lighthouse's pre-existing gaps (item #43 Engine API V5/V6/FCU4 + item #44 PartialDataColumnSidecar absent + item #46 envelope RPCs absent) now compound with this container-schema divergence at Gloas activation. Pre-emptive fix is trivial: add `#[superstruct(only(Fulu))]` to `data_column_sidecar.rs:85`.

**Pattern HH (compile-time-baked constants)** persists in nimbus (`fulu_preset.nim:16 KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH*: uint64 = 4` across mainnet/gnosis/minimal presets) and grandine (`preset.rs:382 type KzgCommitmentsInclusionProofDepth = U4` type-level). Applies only to the Fulu code path since the Gloas container removes the inclusion proof entirely. Pattern HH on this constant becomes dead at Gloas.

**Pattern AA fork-naming consistency** (teku scoreboard): items #45 + #47 + #54 = 3 consistent (`MetadataMessageFulu`, `StatusMessageFulu`, `DataColumnSidecarFulu`/`Gloas`); item #53 = 1 inconsistent (`"DataColumnIdentifier"` SSZ container metadata).

**Pattern AA camelCase** (lodestar): persists at both Fulu and Gloas variants (`kzgCommitments`, `kzgProofs`, `signedBlockHeader`, `kzgCommitmentsInclusionProof` at Fulu; `kzgProofs`, `beaconBlockRoot` at Gloas) — mapped to spec snake_case via `jsonCase: "eth2"`.

**Impact: none** — Fulu surface byte-identical across all 6 (validated by 5+ months of mainnet); Gloas reshape is not mainnet-reachable today (`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH`). lighthouse's Gloas variant divergence is forward-fragility tracking only. Thirty-fifth `impact: none` result in the recheck series.

Forward-research priorities:

1. **Lighthouse Gloas DataColumnSidecar fix PR** — add `#[superstruct(only(Fulu))]` to `data_column_sidecar.rs:85 pub kzg_commitments: KzgCommitments<E>`. Aligns with the other 5 clients and closes the Gloas-activation interop failure mode.
2. **Lighthouse ssz_static spec-test verification** — confirm whether lighthouse CI exercises Gloas ssz_static fixtures. If yes, the 6-field variant should fail tree-hash root comparison; if no, the divergence remains silent until enabled.
3. **Item #48 catalogue refresh** — lighthouse Gloas-ePBS readiness cohort grows with this symptom. Now spans Engine API + Partial column + envelope RPCs + DataColumnSidecar container.
4. **Pattern HH catalogue audit** — extend from `MAX_REQUEST_BLOCKS_DENEB` (item #52) and `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` (this audit) to a spec-wide compile-time-baked-constant inventory per client.
5. **MatrixEntry SSZ container audit** — Fulu-NEW related container; pre-emptive item #55+ candidate.
6. **`MAX_BLOB_COMMITMENTS_PER_BLOCK = 4096` cross-client baseline** — Deneb-heritage constant; same Pattern DD/HH analysis.
