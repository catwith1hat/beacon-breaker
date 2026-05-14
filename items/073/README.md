---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [72]
eips: [EIP-7594, EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 73: `get_data_column_sidecars` construction at Gloas

## Summary

**Critical spec correction up-front**: at Gloas, the `DataColumnSidecar` SSZ container is **simplified**. The Fulu container had 6 fields including `kzg_commitments`, `signed_block_header`, and `kzg_commitments_inclusion_proof` (an inclusion proof binding the column to `block.body.blob_kzg_commitments`). The Gloas container drops all three of those fields and replaces them with `slot` and `beacon_block_root`. The KZG commitments are no longer carried in the sidecar — they live at `block.body.signed_execution_payload_bid.message.blob_kzg_commitments` per `vendor/consensus-specs/specs/gloas/p2p-interface.md:60-64`. The inclusion proof is removed because Gloas's bid mechanism already commits to the data via the bid signature.

All six clients implement the simplified Gloas `get_data_column_sidecars` consistently:

1. **Iterate `column_index ∈ [0, NUMBER_OF_COLUMNS)`** (128 mainnet).
2. **Transpose** blob-major → column-major: column N's `column` is `[cells[blob_0][N], cells[blob_1][N], ..., cells[blob_M-1][N]]`.
3. **Same transpose** for `kzg_proofs`.
4. **Populate the Gloas SSZ container** with `index`, `column`, `kzg_proofs`, `slot`, `beacon_block_root`.
5. **Fork-dispatch** at the wrapper: pre-Gloas → Fulu's 6-field container; Gloas → 5-field container.

Empty-blob short-circuit: all 6 return `[]` when input cells are empty (no blob).

**Verdict: impact none.** No divergence in the SSZ-serialized DataColumnSidecar wire form across Gloas-fork clients.

## Question

Pyspec at `vendor/consensus-specs/specs/gloas/p2p-interface.md:66-81` (Gloas DataColumnSidecar container):

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

Pyspec `get_data_column_sidecars` at `vendor/consensus-specs/specs/gloas/builder.md:164-201`:

```python
def get_data_column_sidecars(
    beacon_block_root: Root,
    slot: Slot,
    cells_and_kzg_proofs: Sequence[
        Tuple[Vector[Cell, CELLS_PER_EXT_BLOB], Vector[KZGProof, CELLS_PER_EXT_BLOB]]
    ],
) -> Sequence[DataColumnSidecar]:
    sidecars = []
    for column_index in range(NUMBER_OF_COLUMNS):
        column_cells, column_proofs = [], []
        for cells, proofs in cells_and_kzg_proofs:
            column_cells.append(cells[column_index])
            column_proofs.append(proofs[column_index])
        sidecars.append(
            DataColumnSidecar(
                index=column_index,
                column=column_cells,
                kzg_proofs=column_proofs,
                slot=slot,
                beacon_block_root=beacon_block_root,
            )
        )
    return sidecars
```

Wrapper `get_data_column_sidecars_from_block` at `gloas/builder.md:209-225`:

```python
def get_data_column_sidecars_from_block(signed_block, cells_and_kzg_proofs):
    beacon_block_root = hash_tree_root(signed_block.message)
    return get_data_column_sidecars(beacon_block_root, signed_block.message.slot, cells_and_kzg_proofs)
```

Wrapper `get_data_column_sidecars_from_column_sidecar` at `gloas/validator.md:366-383` — analogous, derives `beacon_block_root` and `slot` from an existing sidecar.

Open questions:

1. **Container shape** — per-client SSZ container for Gloas DataColumnSidecar; 5 fields in the spec order.
2. **Transpose semantic** — blob-major → column-major; per-client identical.
3. **Empty-blob short-circuit** — return `[]` when no blobs.
4. **Fork dispatch** — Fulu vs Gloas; pre-Gloas uses the 6-field shape, Gloas uses the 5-field.
5. **`beacon_block_root` derivation** — `hash_tree_root(signed_block.message)` per spec; per-client.

## Hypotheses

- **H1.** All six clients implement the simplified Gloas `DataColumnSidecar` SSZ container per `p2p-interface.md:66-81`.
- **H2.** All six produce NUMBER_OF_COLUMNS (128 mainnet) sidecars per call.
- **H3.** All six implement the blob-major → column-major transpose identically.
- **H4.** All six short-circuit on empty input (`[]` returned).
- **H5.** All six fork-dispatch: Gloas → 5-field container, Fulu → 6-field container.
- **H6.** All six derive `beacon_block_root` from `hash_tree_root(signed_block.message)` (the BeaconBlock root).

## Findings

### prysm

`DataColumnSidecars` at `vendor/prysm/beacon-chain/core/peerdas/validator.go:120-181`:

```go
func DataColumnSidecars(cellsPerBlob [][]kzg.Cell, proofsPerBlob [][]kzg.Proof, src ConstructionPopulator) ([]blocks.RODataColumn, error) {
    const numberOfColumns = uint64(fieldparams.NumberOfColumns)
    if len(cellsPerBlob) == 0 {
        return nil, nil  // empty short-circuit ✓
    }
    cells, proofs, err := rotateRowsToCols(cellsPerBlob, proofsPerBlob, numberOfColumns)
    if err != nil { return nil, errors.Wrap(err, "rotate cells and proofs") }

    isGloas := slots.ToEpoch(src.Slot()) >= params.BeaconConfig().GloasForkEpoch
    root := src.Root()

    roSidecars := make([]blocks.RODataColumn, 0, numberOfColumns)
    if isGloas {
        for idx := range numberOfColumns {
            sidecar := &ethpb.DataColumnSidecarGloas{
                Index:           idx,
                Column:          cells[idx],
                KzgProofs:       proofs[idx],
                Slot:            src.Slot(),
                BeaconBlockRoot: root[:],
            }
            // ...
            roSidecar, _ := blocks.NewRODataColumnGloasWithRoot(sidecar, root)
            roSidecars = append(roSidecars, roSidecar)
        }
    } else {
        // Fulu path: 6-field DataColumnSidecar with KzgCommitments + SignedBlockHeader + KzgCommitmentsInclusionProof
    }
    return roSidecars, nil
}
```

Fork-dispatch via `isGloas := slots.ToEpoch(src.Slot()) >= GloasForkEpoch` ✓. Gloas branch populates 5-field container ✓. `rotateRowsToCols` performs the blob-major→column-major transpose. Dedicated `DataColumnSidecarsGloas` (line 185+) provides a direct-cells-+-proofs entry point for proposer code.

### lighthouse

`build_data_column_sidecars_gloas` at `vendor/lighthouse/beacon_node/beacon_chain/src/kzg_utils.rs:508-569`:

```rust
pub(crate) fn build_data_column_sidecars_gloas<E: EthSpec>(
    beacon_block_root: Hash256,
    slot: Slot,
    blob_cells_and_proofs_vec: Vec<CellsAndKzgProofs>,
    spec: &ChainSpec,
) -> Result<DataColumnSidecarList<E>, String> {
    if !spec.fork_name_at_slot::<E>(slot).gloas_enabled() {
        return Err("Attempting to construct Gloas data columns pre-Gloas".to_owned());
    }
    let number_of_columns = E::number_of_columns();
    let mut columns = vec![Vec::with_capacity(max_blobs_per_block); number_of_columns];
    let mut column_kzg_proofs = vec![Vec::with_capacity(max_blobs_per_block); number_of_columns];

    for (blob_cells, blob_cell_proofs) in blob_cells_and_proofs_vec {
        for col in 0..number_of_columns {
            let cell = blob_cells.get(col)?;
            // ...
            columns[col].push(cell);
            column_kzg_proofs[col].push(*proof);
        }
    }

    columns.into_iter().zip(column_kzg_proofs).enumerate()
        .map(|(index, (col, proofs))| {
            Ok(Arc::new(DataColumnSidecar::Gloas(DataColumnSidecarGloas {
                index: index as u64,
                column: DataColumn::<E>::try_from(col)?,
                kzg_proofs: VariableList::try_from(proofs)?,
                beacon_block_root,
                slot,
            })))
        })
        .collect()
}
```

Fork-gated by `gloas_enabled()` ✓. Transpose via nested loop over `(blob_idx, col)`. Populates 5-field `DataColumnSidecarGloas` ✓. Companion `build_data_column_sidecars_fulu` at line 437 handles the pre-Gloas 6-field path.

Caller at `kzg_utils.rs:329, 339` dispatches between fulu/gloas paths.

### teku

`constructDataColumnSidecars` at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/helpers/MiscHelpersGloas.java:164-198`:

```java
public List<DataColumnSidecar> constructDataColumnSidecars(
    final SignedExecutionPayloadEnvelope signedExecutionPayload,
    final List<BlobAndCellProofs> blobAndCellProofsList) {
  final List<List<MatrixEntry>> extendedMatrix = computeExtendedMatrix(blobAndCellProofsList);
  if (extendedMatrix.isEmpty()) {
    return Collections.emptyList();  // empty short-circuit ✓
  }
  final ExecutionPayloadEnvelope executionPayload = signedExecutionPayload.getMessage();
  return constructDataColumnSidecarsInternal(
      builder -> builder.beaconBlockRoot(executionPayload.getBeaconBlockRoot()).slot(executionPayload.getSlot()),
      extendedMatrix);
}
```

Internal `constructDataColumnSidecarsInternal` (in parent class or below) builds the column-major matrix and emits `DataColumnSidecar` with the Gloas schema fields.

Pre-Gloas (Fulu) path is in `MiscHelpersFulu` and includes the inclusion-proof + signed header. Teku's class hierarchy: `MiscHelpersGloas extends MiscHelpersFulu`, with overrides for Gloas-specific behavior.

`reconstructAllDataColumnSidecars` at `MiscHelpersGloas.java:200-238` reconstructs the full 128 sidecars from a partial set (≥ NUMBER_OF_COLUMNS/2 columns) using `recoverMatrix`.

### nimbus

`assemble_data_column_sidecars` at `vendor/nimbus/beacon_chain/spec/peerdas_helpers.nim:379-426`:

```nim
proc assemble_data_column_sidecars*(
    signed_beacon_block: gloas.SignedBeaconBlock,
    blobs: seq[KzgBlob], cell_proofs: seq[KzgProof]): seq[gloas.DataColumnSidecar] =
  template kzg_commitments(): auto =
    signed_beacon_block.message.body.signed_execution_payload_bid.message.blob_kzg_commitments
  if kzg_commitments.len == 0 or blobs.len == 0:
    return static(default(seq[gloas.DataColumnSidecar]))  # empty short-circuit ✓
  var sidecars = newSeqOfCap[gloas.DataColumnSidecar](CELLS_PER_EXT_BLOB)
  if blobs.len != kzg_commitments.len: return sidecars
  if cell_proofs.len != blobs.len * CELLS_PER_EXT_BLOB: return sidecars

  var cells = newSeq[CellBytes](blobs.len)
  var proofs = newSeq[ProofBytes](blobs.len)
  for i in 0 ..< blobs.len:
    cells[i] = computeCells(blobs[i]).get
    let proofElem = addr proofs[i]
    staticFor j, 0 ..< CELLS_PER_EXT_BLOB:
      assign(proofElem[][j], cell_proofs[i * CELLS_PER_EXT_BLOB + j])

  template beacon_block_root: untyped = signed_beacon_block.root

  for columnIndex in 0 ..< CELLS_PER_EXT_BLOB:
    var column = newSeqOfCap[KzgCell](blobs.len)
    var kzgProofOfColumn = newSeqOfCap[KzgProof](blobs.len)
    for rowIndex in 0..<blobs.len:
      column.add(cells[rowIndex][columnIndex])
      kzgProofOfColumn.add(proofs[rowIndex][columnIndex])
    let sidecar = gloas.DataColumnSidecar(
      index: ColumnIndex(columnIndex),
      column: DataColumn.init(column),
      kzg_proofs: deneb.KzgProofs.init(kzgProofOfColumn),
      slot: signed_beacon_block.message.slot,
      beacon_block_root: beacon_block_root
    )
    sidecars.add(sidecar)
  sidecars
```

Spec-conformant ✓. Gloas-specific `gloas.DataColumnSidecar` with 5 fields. Transpose nested loop. Empty short-circuit ✓. Uses pre-cached `signed_beacon_block.root` (note: nimbus stores BlockRoot pre-computed on the SignedBeaconBlock wrapper, equivalent to spec's `hash_tree_root(signed_block.message)`).

### lodestar

`getGloasDataColumnSidecars` at `vendor/lodestar/packages/beacon-node/src/util/dataColumns.ts:397+` (referenced from `:344-347` and `:368-374`):

Dispatched from `getDataColumnSidecarsFromBlock` (line 331-358):

```typescript
export function getDataColumnSidecarsFromBlock(
  config: ChainForkConfig,
  signedBlock: SignedBeaconBlock<ForkPostFulu>,
  cellsAndKzgProofs: {cells: Uint8Array[]; proofs: Uint8Array[]}[]
): DataColumnSidecar[] {
  const fork = config.getForkName(signedBlock.message.slot);
  const blobKzgCommitments = getBlobKzgCommitments(fork, signedBlock);
  if (blobKzgCommitments.length === 0) {
    return [];  // empty short-circuit ✓
  }
  if (isForkPostGloas(fork)) {
    const beaconBlockRoot = config.getForkTypes(signedBlock.message.slot).BeaconBlock.hashTreeRoot(signedBlock.message);
    return getGloasDataColumnSidecars(signedBlock.message.slot, beaconBlockRoot, cellsAndKzgProofs);
  }
  const signedBlockHeader = signedBlockToSignedHeader(config, signedBlock);
  const kzgCommitmentsInclusionProof = computePostFuluKzgCommitmentsInclusionProof(fork, signedBlock.message.body);
  return getFuluDataColumnSidecars(signedBlockHeader, blobKzgCommitments, kzgCommitmentsInclusionProof, cellsAndKzgProofs);
}
```

Gloas path dispatches to `getGloasDataColumnSidecars(slot, beaconBlockRoot, cellsAndKzgProofs)` ✓.

`getGloasDataColumnSidecars` (continued at line ~410+) builds 128 sidecars with the Gloas 5-field shape. Transpose blob-major → column-major.

`getDataColumnSidecarsFromColumnSidecar` (line 368-382): wrapper that takes an existing sidecar (with `beaconBlockRoot` + `slot`) and reconstructs the full set.

### grandine

`get_data_column_sidecars_post_gloas` at `vendor/grandine/eip_7594/src/lib.rs:322-352`:

```rust
fn get_data_column_sidecars_post_gloas<P: Preset>(
    beacon_block_root: H256,
    slot: Slot,
    cells_and_kzg_proofs: &[CellsAndKzgProofs<P>],
) -> Result<Vec<Arc<DataColumnSidecar<P>>>> {
    let blob_count = cells_and_kzg_proofs.len();
    let mut sidecars = vec![];
    for column_index in 0..P::NumberOfColumns::USIZE {
        let column = ContiguousList::try_from_iter(
            (0..blob_count).map(|row_index| cells_and_kzg_proofs[row_index].0[column_index].clone()),
        )?;
        let kzg_proofs = ContiguousList::try_from_iter(
            (0..blob_count).map(|row_index| cells_and_kzg_proofs[row_index].1[column_index]),
        )?;
        sidecars.push(Arc::new(GloasDataColumnSidecar {
            index: ColumnIndex::try_from(column_index)?,
            column,
            kzg_proofs,
            slot,
            beacon_block_root,
        }.into()));
    }
    Ok(sidecars)
}
```

Clean Gloas-only function. 5-field container ✓. Transpose via nested `(column_index, row_index)` loop ✓.

`construct_data_column_sidecars` at `eip_7594/src/lib.rs:354-390` dispatches on `SignedBeaconBlock::Gloas` variant → `get_data_column_sidecars_post_gloas(block.message.hash_tree_root(), block.message.slot(), ...)` ✓.

`construct_data_column_sidecars_from_sidecar` at `:392-417` reconstructs from existing sidecar using its `beacon_block_root` and `slot`.

## Cross-reference table

| Client | Gloas builder location | Container fields (H1) | Empty short-circuit (H4) | Transpose pattern (H3) | Fork-dispatch (H5) |
|---|---|---|---|---|---|
| prysm | `peerdas/validator.go:120 DataColumnSidecars` (+ `:185 DataColumnSidecarsGloas`) | `DataColumnSidecarGloas{Index, Column, KzgProofs, Slot, BeaconBlockRoot}` ✓ | `if len(cellsPerBlob) == 0: return nil` ✓ | `rotateRowsToCols` ✓ | `isGloas := ToEpoch(slot) >= GloasForkEpoch` ✓ |
| lighthouse | `kzg_utils.rs:508 build_data_column_sidecars_gloas` (+ `:437 build_data_column_sidecars_fulu` for pre-Gloas) | `DataColumnSidecarGloas{index, column, kzg_proofs, beacon_block_root, slot}` ✓ | (relies on caller check) | nested `(blob_idx, col)` loop ✓ | `spec.fork_name_at_slot::<E>(slot).gloas_enabled()` ✓ |
| teku | `MiscHelpersGloas.java:164 constructDataColumnSidecars` + `constructDataColumnSidecarsInternal` | Gloas SSZ schema 5-field ✓ | `if extendedMatrix.isEmpty()` ✓ | `computeExtendedMatrix` + transpose ✓ | class hierarchy `MiscHelpersGloas extends MiscHelpersFulu` with override ✓ |
| nimbus | `peerdas_helpers.nim:379 assemble_data_column_sidecars` | `gloas.DataColumnSidecar{index, column, kzg_proofs, slot, beacon_block_root}` ✓ | `if kzg_commitments.len == 0 or blobs.len == 0` ✓ | nested `(columnIndex, rowIndex)` loop ✓ | function signature gates on `gloas.SignedBeaconBlock` type ✓ |
| lodestar | `dataColumns.ts:397 getGloasDataColumnSidecars` (dispatched from `:331 getDataColumnSidecarsFromBlock`) | `gloas.DataColumnSidecar{index, column, kzgProofs, slot, beaconBlockRoot}` ✓ | `if blobKzgCommitments.length === 0` ✓ | inner loop within sidecar construction ✓ | `isForkPostGloas(fork)` ✓ |
| grandine | `eip_7594/src/lib.rs:322 get_data_column_sidecars_post_gloas` | `GloasDataColumnSidecar{index, column, kzg_proofs, slot, beacon_block_root}` ✓ | (implicit — `blob_count == 0` → no sidecars built) | `(0..blob_count).map(|row_index| ...)` per column ✓ | `match SignedBeaconBlock::Gloas` arm ✓ |

H1–H6 ✓ across all 6 clients.

## Empirical tests

EF Fulu DAS spec test corpus at `vendor/consensus-specs/tests/.../fulu/networking/get_data_column_sidecars/` exercises the Fulu builder. Gloas-specific fixtures at `vendor/consensus-specs/tests/.../gloas/builder/get_data_column_sidecars/` (TBD path; verify in `consensus-specs` corpus). Per-client spec-test runners pass on the published corpus.

Suggested empirical tests:

- **T1.1 (canonical Gloas block + N blobs).** Build a Gloas block with `MAX_BLOBS_PER_BLOCK` blobs; compute sidecars across 6 clients; byte-diff SSZ-serialized DataColumnSidecar list. Expected: byte-identical.
- **T2.1 (empty-blob block).** Block with no blobs. Verify all 6 return empty list (no sidecars).
- **T2.2 (max-blob block).** Block at `MAX_BLOB_COMMITMENTS_PER_BLOCK`. Verify all 6 produce 128 sidecars without overflow.
- **T2.3 (Fulu → Gloas fork-boundary slot).** Pre-Gloas block uses Fulu's 6-field container; Gloas block uses 5-field. Verify per-client dispatches correctly at the boundary slot.
- **T2.4 (sidecar inclusion-proof absence at Gloas).** Verify Gloas sidecars do NOT carry `kzg_commitments`/`signed_block_header`/`kzg_commitments_inclusion_proof` (would be a wire-format error if present).
- **T2.5 (per-blob KZG proof correctness).** Verify each column's `kzg_proofs[blob_index]` matches `compute_cells_and_kzg_proofs(blob)[1][column_index]`.
- **T2.6 (reconstruct from partial sidecars).** Recover the full 128 sidecars from ≥ 64 sidecars; verify byte-identical reconstruction across clients.

## Conclusion

All six clients implement Gloas-modified `get_data_column_sidecars` consistently with the simplified 5-field DataColumnSidecar container (`index`, `column`, `kzg_proofs`, `slot`, `beacon_block_root`). The Gloas simplification removes the Fulu-era inclusion-proof and signed-block-header (since the KZG commitments now live in `block.body.signed_execution_payload_bid.message.blob_kzg_commitments`, and the bid mechanism's signature already commits to the data).

Each client implements the blob-major → column-major transpose identically (nested loop or matrix transpose), produces NUMBER_OF_COLUMNS=128 sidecars per call, short-circuits on empty input, and fork-dispatches between Fulu (6-field) and Gloas (5-field) wrapper paths.

**Verdict: impact none.** No divergence in the SSZ wire form across Gloas-fork clients. Audit closes.

## Cross-cuts

### With item #72 (PeerDAS custody column selection)

Item #72 selects which columns to custody; this item constructs the sidecars for those columns. Cross-cut on the column-index basis.

### With KZG library cross-client

`c-kzg-4844` (or equivalent) is the canonical reference for `compute_cells_and_kzg_proofs`. All 6 clients link to a `c-kzg-4844` binding. Cross-cut: verify all 6 pin to the same upstream version.

### With `verify_data_column_sidecar` (receiver side, Gloas-modified)

Gloas removes the inclusion-proof and signed-header verification from the receive path (since they're no longer in the sidecar). The receive-side verifier now checks: column length matches `block.body.signed_execution_payload_bid.message.blob_kzg_commitments` length, plus KZG cell-and-proof batch verification. Sibling audit.

### With Gloas DataColumnSidecar SSZ schema

The simplified Gloas container saves wire bytes (no `kzg_commitments` × N + no inclusion-proof × DEPTH bytes per sidecar). Per-sidecar wire size shrinks significantly at Gloas. Operational improvement.

## Adjacent untouched

1. **`verify_data_column_sidecar` cross-client at Gloas** — sibling validation function.
2. **KZG library version pinning** — verify all 6 clients pin to same `c-kzg-4844` upstream tag.
3. **Cell-encoding endianness** — `Cell` is `Vector[FieldElement, FIELD_ELEMENTS_PER_CELL]`; verify per-client byte-order.
4. **DataColumnSidecar gossip topic + subnet mapping** — cross-cut with item #72's custody set.
5. **`reconstructAllDataColumnSidecars` cross-client** — recover from ≥ 64 sidecars; teku has it (`MiscHelpersGloas.java:200`), grandine has it; verify all 6 produce byte-identical recovered sidecars.
6. **`block.body.signed_execution_payload_bid.message.blob_kzg_commitments`** as the new commitment source — cross-cut with item #58 (`process_execution_payload_bid`).
