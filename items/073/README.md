---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: [72]
eips: [EIP-7594]
splits: []
# main_md_summary: TBD — drafting `get_data_column_sidecars` construction audit (column-from-block construction; KZG inclusion proofs; cross-client byte-equivalence on the constructed sidecar SSZ bytes)
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 73: `get_data_column_sidecars` construction — column-from-block + KZG inclusion proofs

## Summary

> **DRAFT — hypotheses-pending.** Given a block + blobs, each node constructs `DataColumnSidecar` objects for the columns it custodies (item #72). The construction involves:
> 1. **Column extraction**: take the `i`-th column from each blob's cell array.
> 2. **KZG cell-and-proof computation**: for each cell, the corresponding KZG proof.
> 3. **Inclusion proof**: SSZ Merkle proof binding the column to `block_body.blob_kzg_commitments`.
> 4. **SSZ serialization**: cross-client byte-equivalence on the wire.
>
> A divergence in any step produces incompatible column sidecars across clients — broken DAS reconstruction.

## Question

Pyspec `get_data_column_sidecars` (Fulu, `vendor/consensus-specs/specs/fulu/das-core.md`, TBD line):

```python
def get_data_column_sidecars(
    signed_block: SignedBeaconBlock,
    blobs: Sequence[Blob],
) -> Sequence[DataColumnSidecar]:
    # TODO[drafting]: paste exact spec body.
    # Captures: cell-and-proof computation (compute_cells_and_kzg_proofs),
    # column transpose (blob-major → column-major), inclusion-proof computation,
    # sidecar struct fill-in.
```

`DataColumnSidecar` SSZ container (TBD field order):

```
DataColumnSidecar:
  index: ColumnIndex
  column: List[Cell, MAX_BLOB_COMMITMENTS_PER_BLOCK]
  kzg_commitments: List[KZGCommitment, MAX_BLOB_COMMITMENTS_PER_BLOCK]
  kzg_proofs: List[KZGProof, MAX_BLOB_COMMITMENTS_PER_BLOCK]
  signed_block_header: SignedBeaconBlockHeader
  kzg_commitments_inclusion_proof: Vector[Bytes32, KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH]
```

Open questions:

1. **Cell-and-proof helper** — `compute_cells_and_kzg_proofs(blob)` returns `(cells, proofs)` for each blob. Cross-client equivalence (c-kzg-4844 library version?).
2. **Column transpose** — `cells[blob_idx][col_idx]` → `column[col_idx][blob_idx]`. Verify orientation per-client.
3. **Inclusion-proof Merkle path** — `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` constant; depth derived from BeaconBlockBody field path.
4. **SSZ field order** — `index`, then `column`, then `kzg_commitments`, then `kzg_proofs`, then `signed_block_header`, then `kzg_commitments_inclusion_proof`. Per-client identical?

## Hypotheses

- **H1.** All six clients implement `get_data_column_sidecars` byte-equivalently for any (block, blobs) input.
- **H2.** All six use the same c-kzg-4844 (or equivalent) library for `compute_cells_and_kzg_proofs`.
- **H3.** All six compute identical inclusion proofs (same Merkle path, same depth).
- **H4.** All six produce byte-identical SSZ-serialized sidecars.
- **H5** *(forward-fragility)*. Empty-blob case (block with no blobs) — verify per-client returns empty list, not malformed sidecars.
- **H6** *(cross-cut item #72)*. Per-node custody filtering — verify only columns in the node's custody set are constructed (not all 128 columns).

## Findings

> **TBD — drafting.** Each client subsection below is a stub awaiting source review.

### prysm

TBD — drafting.

### lighthouse

TBD — drafting.

### teku

TBD — drafting.

### nimbus

TBD — drafting.

### lodestar

TBD — drafting.

### grandine

TBD — drafting.

## Cross-reference table

| Client | `get_data_column_sidecars` location | KZG library + version | Inclusion-proof depth | SSZ field-order | Empty-blob edge (H5) |
|---|---|---|---|---|---|
| prysm | TBD | TBD | TBD | TBD | TBD |
| lighthouse | TBD | TBD | TBD | TBD | TBD |
| teku | TBD | TBD | TBD | TBD | TBD |
| nimbus | TBD | TBD | TBD | TBD | TBD |
| lodestar | TBD | TBD | TBD | TBD | TBD |
| grandine | TBD | TBD | TBD | TBD | TBD |

## Empirical tests

> **TBD — drafting.** EF Fulu DAS fixtures (TBD path); cross-client SSZ byte-diff.

### Suggested fuzzing vectors

- **T1.1 (canonical block + 6 blobs).** Compute sidecars across 6 clients; diff SSZ bytes.
- **T2.1 (empty-blob block).** Block with no blobs. Verify per-client returns empty list.
- **T2.2 (max-blob block).** Block at `MAX_BLOB_COMMITMENTS_PER_BLOCK`. Verify no overflow; all columns produced.
- **T2.3 (custody-filtered).** Node with `cgc < NUMBER_OF_COLUMNS`. Verify only custodied columns appear.
- **T2.4 (inclusion-proof verification).** Each sidecar's `kzg_commitments_inclusion_proof` must verify against `block.body.hash_tree_root()`.

## Conclusion

> **TBD — drafting.** Source review pending.

## Cross-cuts

### With item #72 (PeerDAS custody column selection)

This item constructs the sidecars for the custodied columns; item #72 selects which columns to custody.

### With KZG library cross-client

`c-kzg-4844` is the canonical reference; per-client wrappers (Go, Rust, Java, Nim, TS bindings). Cross-cut: verify all 6 bindings to the same upstream version.

### With `verify_data_column_sidecar` (receiver side)

Sibling validation function — verifies received sidecars. Adjacent audit.

## Adjacent untouched

1. **`verify_data_column_sidecar` cross-client** — sibling validation function.
2. **KZG library version pinning** — verify all 6 clients pin to same `c-kzg-4844` upstream tag.
3. **Cell-encoding endianness** — `Cell` is `Vector[FieldElement, FIELD_ELEMENTS_PER_CELL]`; verify per-client byte-order.
4. **DataColumnSidecar gossip topic + subnet mapping** — cross-cut with item #72's custody set.
