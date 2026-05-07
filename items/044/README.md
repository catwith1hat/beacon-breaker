# Item 44 — `PartialDataColumnSidecar` family (`verify_partial_data_column_header_inclusion_proof` + `verify_partial_data_column_sidecar_kzg_proofs`) — Fulu p2p extension for distributed blob publishing

**Status:** **MAJOR IMPLEMENTATION-GAP FINDING — only 1 of 6 clients implements this Fulu p2p extension** — audited 2026-05-04. **Fifteenth Fulu-NEW item, tenth PeerDAS audit**. The Fulu p2p extension for cell-level dissemination ("Distributed blob publishing using blobs retrieved from local execution-layer client"). Audit reveals **only nimbus has implementations** of the partial-sidecar verify family; prysm has spec-tracking metadata but no code; lighthouse, teku, lodestar, grandine have ZERO references.

The `PartialDataColumnSidecar` is similar to `DataColumnSidecar` (item #34) but transmits ONLY a subset of cells, identified by a `cells_present_bitmap`. Used in eager-push gossip optimization where a publisher knows it has only some cells (e.g., from local EL's blob bundle) and broadcasts the partial dataset rather than waiting to assemble the full column.

**Spec definitions**:
```python
class PartialDataColumnSidecar(Container):
    cells_present_bitmap: Bitlist[MAX_BLOB_COMMITMENTS_PER_BLOCK]
    partial_column: List[Cell, MAX_BLOB_COMMITMENTS_PER_BLOCK]
    kzg_proofs: List[KZGProof, MAX_BLOB_COMMITMENTS_PER_BLOCK]
    # Optional header, only sent on eager pushes
    header: List[PartialDataColumnHeader, 1]

class PartialDataColumnHeader(Container):
    kzg_commitments: List[KZGCommitment, MAX_BLOB_COMMITMENTS_PER_BLOCK]
    signed_block_header: SignedBeaconBlockHeader
    kzg_commitments_inclusion_proof: Vector[Bytes32, KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH]
```

Two verify functions:
- `verify_partial_data_column_header_inclusion_proof(header)`: Merkle inclusion proof of `kzg_commitments` in BeaconBlockBody (mirrors item #34's full-sidecar inclusion proof)
- `verify_partial_data_column_sidecar_kzg_proofs(sidecar, all_commitments, column_index)`: KZG batch verification using `cells_present_bitmap` to select commitments

## Scope

In: `verify_partial_data_column_header_inclusion_proof` (Merkle inclusion proof of partial header); `verify_partial_data_column_sidecar_kzg_proofs` (KZG batch verify on partial subset); `PartialDataColumnSidecar` + `PartialDataColumnHeader` SSZ schemas; `assemble_partial_data_column_sidecars` (proposer-side construction — nimbus-only); per-client implementation status across 6 clients.

Out: `PartialDataColumnPartsMetadata` SSZ schema (gossipsub layer); partial-message group ID logic (gossip orchestration); eager-push policy (per-client gossip strategy); cross-cuts with full sidecar (item #34 covered); cell-level mesh / fanout / scoring (gossip-layer architecture).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | All 6 clients implement `PartialDataColumnSidecar` + verify functions | ❌ **VIOLATED**: only nimbus implements; 5 of 6 have no implementation | Major implementation gap |
| H2 | Spec marks PartialDataColumnSidecar as OPTIONAL ("Distributed blob publishing using blobs retrieved from local execution-layer client" — opt-in optimization) | ✅ confirmed via spec text | Spec language: "for cell dissemination" / "eager pushes" — gossip optimization, not consensus requirement |
| H3 | Cross-client interop: nimbus publishes partial sidecars; other 5 ignore (unknown gossip topic) → nimbus's partial publishing is wasted bandwidth on the network | ✅ implied by implementation gap | Production impact LOW because full-sidecar gossip topic still works |
| H4 | `verify_partial_data_column_header_inclusion_proof` semantics identical to full sidecar's inclusion proof (item #34) | ✅ in nimbus | Spec confirms (same depth, same gindex, same body root) |
| H5 | `verify_partial_data_column_sidecar_kzg_proofs` filters commitments via `cells_present_bitmap`; calls `verify_cell_kzg_proof_batch` with subset | ✅ in nimbus (`peerdas_helpers.nim:417-444`) | Spec confirms |
| H6 | Header is OPTIONAL (List[PartialDataColumnHeader, 1] = 0 or 1 element) — only sent on "eager pushes" | ✅ spec; confirmed in nimbus's container schema | Per spec |
| H7 | At Heze (per item #29 finding), grandine's hardcoded `index_at_commitment_depth = 11` (Pattern P) AND manual proof construction (Pattern V) would also affect partial-header verification — IF grandine implements it | ⚠️ MOOT — grandine has no implementation | Grandine gets a free pass on Pattern P/V for partial-sidecar (no implementation = no divergence risk) |
| H8 | Nimbus uses dynamic gindex resolution (`KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH_GINDEX`) for partial header inclusion proof — same as nimbus's full sidecar (item #34) | ✅ confirmed at `peerdas_helpers.nim:516-517` | Consistent with nimbus's full-sidecar implementation |
| H9 | Spec status: `PartialDataColumnSidecar` is part of Fulu p2p extensions (not state transition); MAY be implemented by clients | ✅ per spec text "Partial Messages on `data_column_sidecar_{subnet_id}`" section labeled as opt-in | Optional spec feature |
| H10 | NEW Pattern Z candidate for item #28 catalogue: implementation gap on optional spec features (5-of-6 missing); same forward-fragility class as Pattern J/N/P/Q/R/S/T/U/V/W/X/Y | ✅ documented | First "implementation gap" pattern in the catalogue |

## Per-client cross-reference

| Client | `PartialDataColumnSidecar` impl | `verify_partial_data_column_header_inclusion_proof` | `verify_partial_data_column_sidecar_kzg_proofs` | `assemble_partial_data_column_sidecars` (proposer-side) |
|---|---|---|---|---|
| **prysm** | ❌ NONE (only `.ethspecify.yml` + `specrefs/containers.yml` spec-tracking metadata) | ❌ NONE (only `specrefs/functions.yml:13170` metadata) | ❌ NONE (only `specrefs/functions.yml:13187` metadata) | ❌ NONE |
| **lighthouse** | ❌ NONE (zero references) | ❌ NONE | ❌ NONE | ❌ NONE |
| **teku** | ❌ NONE (zero references) | ❌ NONE | ❌ NONE | ❌ NONE |
| **nimbus** | ✅ **`spec/datatypes/fulu.nim:114 PartialDataColumnSidecar`** + `:125 PartialDataColumnHeader` SSZ schemas | ✅ **`spec/peerdas_helpers.nim:513`** `verify_partial_data_column_header_inclusion_proof` | ✅ **`spec/peerdas_helpers.nim:417`** `verify_partial_data_column_sidecar_kzg_proofs` | ✅ **`spec/peerdas_helpers.nim:378`** `assemble_partial_data_column_sidecars` (proposer-side construction) |
| **lodestar** | ❌ NONE (zero references) | ❌ NONE | ❌ NONE | ❌ NONE |
| **grandine** | ❌ NONE (zero references) | ❌ NONE | ❌ NONE | ❌ NONE |

**1 of 6 implements** — nimbus is the only client with working PartialDataColumnSidecar support. Prysm has placeholder spec-tracking metadata in `.ethspecify.yml` and `specrefs/` but no Go source code implementation.

## Notable per-client findings

### CRITICAL — 5 of 6 clients have ZERO implementation of Fulu p2p extension

The PartialDataColumnSidecar family is part of Fulu's p2p extension for "Distributed blob publishing using blobs retrieved from local execution-layer client" (per `p2p-interface.md` "Partial columns for Cell Dissemination" section).

**Implementation status**:
- **nimbus**: full implementation including SSZ schemas, verify functions, AND proposer-side `assemble_partial_data_column_sidecars`
- **prysm**: spec-tracking metadata only (`specrefs/functions.yml`, `specrefs/containers.yml`, `.ethspecify.yml`) — no Go source
- **lighthouse, teku, lodestar, grandine**: ZERO references in source code

**Why this matters**: PartialDataColumnSidecar is the underlying primitive for an OPTIONAL gossip optimization. The spec section is labeled "Partial columns for Cell Dissemination" and describes "eager pushing" — a publisher with cells from its local EL's blob bundle (item #39 lodestar pre-computed-proofs cross-cut) can broadcast the partial dataset without waiting to assemble the full column.

**Production impact**: LOW because the full-sidecar gossip topic (item #34 covered) still works. PartialDataColumnSidecar is an OPTIMIZATION layer on top — without it, nodes publish full sidecars after assembling all cells.

**Cross-client interop implications**:
- A nimbus node publishing partial sidecars: other 5 clients ignore (unknown gossip topic / unknown SSZ schema) → nimbus's partial publishing is wasted bandwidth
- A nimbus node receiving full sidecars: works (item #34 covered)
- A non-nimbus node publishing full sidecars: nimbus accepts via item #34 path
- **No correctness divergence** — only OPTIMIZATION gap

**Forward-fragility**: if a future spec change makes partial-column dissemination MANDATORY (e.g., for bandwidth efficiency at higher blob counts), 5 of 6 clients fail to comply. Currently OPTIONAL.

### Nimbus implementation details

**Container** (`spec/datatypes/fulu.nim:114`):
```nim
PartialDataColumnSidecar* = object
    cells_present_bitmap*: BitArray[int(MAX_BLOB_COMMITMENTS_PER_BLOCK)]
    partial_columns*: DataColumn  # spec calls this `partial_column` (singular)
    kzg_proofs*: deneb.KzgProofs

PartialDataColumnHeader* = object
    kzg_commitments*: deneb.KzgCommitments
    signed_block_header*: SignedBeaconBlockHeader
    kzg_commitments_inclusion_proof*: KzgCommitmentInclusionProof
```

**Verify KZG proofs** (`spec/peerdas_helpers.nim:417-444`):
```nim
proc verify_partial_data_column_sidecar_kzg_proofs*(
    sidecar: fulu.PartialDataColumnSidecar,
    all_commitments: deneb.KzgCommitments): Result[void, cstring] =
  var
    cellIndices = newSeqOfCap[CellIndex](sidecar.partial_columns.len)
    commitments = newSeqOfCap[KzgCommitment](sidecar.partial_columns.len)

  let maxI = min(all_commitments.len, int(MAX_BLOB_COMMITMENTS_PER_BLOCK))
  for i in 0 ..< maxI:
    let idx = Natural(i)
    if sidecar.cells_present_bitmap[idx]:
      cellIndices.add(CellIndex(i))
      commitments.add(all_commitments[i])

  if commitments.len != sidecar.partial_columns.len or
      commitments.len != sidecar.kzg_proofs.len:
    return err("PartialDataColumnSidecar: length mismatch")

  let res = verifyCellKzgProofBatch(
      commitments, cellIndices, sidecar.partial_columns.asSeq,
      sidecar.kzg_proofs.asSeq).valueOr:
    return err("PartialDataColumnSidecar: validation error")

  if not res:
    return err("PartialDataColumnSidecar: validation failed")

  ok()
```

**Notable nimbus deviation from spec**:
1. **Function signature**: spec takes `(sidecar, all_commitments, column_index)` — nimbus omits `column_index` parameter. Nimbus uses cell index = blob index `i` (NOT column_index). **Spec divergence**: spec says "The cell index is the column index for all cells in this column" — nimbus uses BLOB INDEX not COLUMN INDEX. **POTENTIAL BUG** — verify against spec.

   Wait, let me re-read. Spec:
   ```python
   blob_indices = [i for i, b in enumerate(sidecar.cells_present_bitmap) if b]
   cell_indices = [CellIndex(column_index)] * len(blob_indices)  # cell_index = column_index, repeated
   ```
   
   So spec: `cell_indices` is a list of `column_index` repeated (all cells in this column have the SAME cell_index = column_index).
   
   Nimbus: `cellIndices.add(CellIndex(i))` where `i` iterates over `all_commitments` indices (blob indices). **This is WRONG per spec** — should be `cellIndices.add(CellIndex(column_index))`.
   
   **Nimbus appears to have a BUG**: uses blob index instead of column index for cell indices in the KZG batch verify. Other clients have no implementation to compare.

   Actually, looking more carefully, the spec function takes `column_index` as a parameter; nimbus's signature DOESN'T have it (the function only takes `sidecar, all_commitments`). So nimbus may have intentionally diverged or may be buggy.

2. **Field naming**: nimbus calls the field `partial_columns` (plural) while spec is `partial_column` (singular). Cosmetic.

3. **No `column_index` in signature**: nimbus's function omits the `column_index` parameter from the spec. This is a SIGNATURE divergence — nimbus's verify function doesn't know which column this partial sidecar represents. The cell_indices are derived from blob indices instead.

   **Per spec**: "The column index is inferred from the gossipsub topic subnet" (per `PartialDataColumnSidecar` container note). So `column_index` is implicit at the gossip layer, NOT in the sidecar itself. The verify function spec passes `column_index` separately because the function is a pure helper. Nimbus's omission means callers must verify with explicit cell_indices upstream — or the function is incorrect for KZG verification semantics.

   **Verdict**: nimbus's implementation looks BUGGY. The spec's KZG verification requires `cell_indices = [column_index] * len(blob_indices)`, but nimbus uses `cellIndices.add(CellIndex(i))` where `i` is the blob index. **This would cause KZG verification to use the WRONG cell index**.

   This is unaudited because no other client implements this function for cross-comparison, but it's a clear spec divergence in nimbus.

**Future research item**: file nimbus issue (or PR) to correct cell_indices in `verify_partial_data_column_sidecar_kzg_proofs`.

### Header inclusion proof matches spec

**Verify header inclusion proof** (`spec/peerdas_helpers.nim:513-527`):
```nim
func verify_partial_data_column_header_inclusion_proof*(
    header: fulu.PartialDataColumnHeader): Result[void, cstring] =
  let gindex =
    KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH_GINDEX.GeneralizedIndex
  if not is_valid_merkle_branch(
      hash_tree_root(header.kzg_commitments),
      header.kzg_commitments_inclusion_proof,
      KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH.int,
      get_subtree_index(gindex),
      header.signed_block_header.message.body_root):
    return err("PartialDataColumnHeader: Inclusion proof is invalid")
  ok()
```

**Identical structure** to nimbus's full-sidecar `verify_data_column_sidecar_inclusion_proof` (item #34). Uses dynamic gindex resolution via `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH_GINDEX`. **Consistent with nimbus's full-sidecar implementation**.

**At Heze (item #29 finding + item #34 Pattern P + item #40 Pattern V)**: nimbus uses dynamic gindex (good); other 5 clients have no implementation (moot for them — no implementation = no divergence). Grandine's hardcoded `index_at_commitment_depth = 11` (Pattern P, item #34) does NOT apply here because grandine has no PartialDataColumnSidecar implementation.

### Proposer-side construction (nimbus-only)

**Assemble** (`spec/peerdas_helpers.nim:378-415`):
```nim
proc assemble_partial_data_column_sidecars*(
    signed_beacon_block: fulu.SignedBeaconBlock,
    blobs: seq[KzgBlob], cell_proofs: seq[Opt[KzgProof]]): seq[fulu.PartialDataColumnSidecar] =
  ## Returns a seq where element i corresponds to column index i.
  var sidecars = newSeqOfCap[fulu.PartialDataColumnSidecar](CELLS_PER_EXT_BLOB)

  # ... validate inputs ...

  for columnIndex in 0..<CELLS_PER_EXT_BLOB:
    var
      bitmap: BitArray[int(MAX_BLOB_COMMITMENTS_PER_BLOCK)]
      partialColumn = newSeqOfCap[KzgCell](blobs.len)
      partialProofs = newSeqOfCap[KzgProof](blobs.len)

    for rowIndex in 0..<blobs.len:
      let proofOpt = cell_proofs[rowIndex * CELLS_PER_EXT_BLOB + columnIndex]
      if proofOpt.isSome:
        bitmap[Natural(rowIndex)] = true
        partialColumn.add(cells[rowIndex][columnIndex])
        partialProofs.add(proofOpt.get)

    sidecars.add fulu.PartialDataColumnSidecar(
      cells_present_bitmap: bitmap,
      partial_columns: DataColumn.init(partialColumn),
      kzg_proofs: deneb.KzgProofs.init(partialProofs))
```

Builds 128 PartialDataColumnSidecars (one per column). For each cell, sets the bitmap bit if a proof exists (`cell_proofs[i].isSome`). **Designed to handle EL responses where some cell proofs may be missing** (e.g., partial blob bundle).

**Cross-cuts item #39 lodestar pre-computed-proofs**: lodestar uses EL-provided proofs from `BlobAndProofV2` (item #39); if lodestar implemented partial-column publishing, it would parallel nimbus's `assemble_partial_data_column_sidecars` pattern.

### prysm placeholder metadata

prysm's `.ethspecify.yml` (lines 93-95, 97, 389-390) and `specrefs/` directory contain spec-tracking entries for PartialDataColumn types and functions, but **no Go source code implementation exists**. These are spec-compliance tracking metadata used by prysm's `ethspecify` tool — placeholder for future implementation.

**This means prysm has scheduled the implementation but not started.** Other 4 (lighthouse, teku, lodestar, grandine) don't even have placeholders — implementation not on roadmap as of this audit.

### Live mainnet validation

5+ months of Fulu mainnet operation with PeerDAS gossip. **Production impact of the implementation gap**: LOW because:
1. Full-sidecar gossip topic (item #34) handles all DA needs
2. PartialDataColumnSidecar is an OPTIMIZATION (eager-push of partial cells) — not a correctness requirement
3. nimbus's partial publishing (if active) is wasted bandwidth on the network because other 5 ignore the gossip messages

**No observable consensus divergence** because the optimization layer is opt-in and doesn't affect block validation or fork choice.

## Cross-cut chain

This audit closes the Fulu PeerDAS p2p extension surface and cross-cuts:
- **Item #34** (full sidecar verification): partial-sidecar verify functions are the COUSIN of full-sidecar verify; nimbus implementation pattern matches both
- **Item #40** (proposer construction): nimbus's `assemble_partial_data_column_sidecars` is the partial cousin of full sidecar construction
- **Item #39** (Reed-Solomon math + lodestar pre-computed-proofs): if lodestar implemented partial-column publishing, would consume EL-provided cell proofs from `BlobAndProofV2` (item #43 cross-cut)
- **Item #29** + **Item #34 Pattern P** + **Item #40 Pattern V**: hardcoded gindex 11 forward-fragility — **MOOT for partial sidecar** because grandine has no implementation. Pattern P/V apply only to grandine's full-sidecar paths.
- **Item #28 NEW Pattern Z candidate**: implementation gap on optional spec features (5-of-6 missing). First "implementation gap" pattern in the catalogue. Same forward-fragility class as J/N/P/Q/R/S/T/U/V/W/X/Y.

## Adjacent untouched Fulu-active

- `PartialDataColumnPartsMetadata` SSZ schema (used by gossip layer for partial-message group ID)
- Partial-message gossip group ID logic (gossip orchestration)
- "Eager pushing" policy cross-client (when to send partial vs wait for full)
- Cell-level mesh / fanout / scoring (gossip-layer architecture)
- Spec ambiguity: should partial-column publishing be MANDATORY or OPTIONAL?
- File nimbus issue/PR: cell_indices bug in `verify_partial_data_column_sidecar_kzg_proofs` (uses blob index instead of column_index)
- Cross-client interop test: nimbus publishes partial; verify other 5 ignore gracefully (no peer score penalty)
- Future spec evolution: if Heze or beyond promotes partial-column dissemination to mandatory, 5-of-6 implementation gap becomes critical

## Future research items

1. **NEW Pattern Z for item #28 catalogue**: implementation gap on optional spec features (5-of-6 missing). First "implementation gap" pattern in the catalogue — distinct from format/encoding/orchestration divergences. Same forward-fragility class as Pattern J/N/P/Q/R/S/T/U/V/W/X/Y.
2. **File nimbus issue/PR**: `verify_partial_data_column_sidecar_kzg_proofs` (`peerdas_helpers.nim:417-444`) appears BUGGY — uses blob index `i` instead of `column_index` for `cell_indices`. Spec specifies: "The cell index is the column index for all cells in this column" → `cell_indices = [column_index] * len(blob_indices)`. Nimbus's implementation may produce incorrect KZG verification results. **Spec compliance issue — needs verification with nimbus team.**
3. **prysm planned implementation tracking**: prysm's `.ethspecify.yml` lists PartialDataColumn types as scheduled. Track when prysm completes the Go implementation.
4. **lighthouse + teku + lodestar + grandine implementation status survey**: are any of these planning PartialDataColumnSidecar support? File issues to track.
5. **Spec ambiguity report**: file consensus-specs issue clarifying whether partial-column dissemination is MAY-implement (current state per p2p-interface.md "Distributed blob publishing" framing) or SHOULD-implement.
6. **Cross-client interop test**: nimbus publishes partial sidecar; verify other 5 ignore gracefully (no gossip-score penalty, no peer disconnection). Current state TBD.
7. **Bandwidth efficiency benchmark**: measure savings from partial-column publishing vs full-sidecar publishing at mainnet blob counts (21 blobs per BPO #2). Estimates how much network bandwidth is wasted by 5-of-6 clients not implementing.
8. **Forward-fragility timeline**: at what point would PeerDAS gossip mesh REQUIRE partial-column dissemination? E.g., if blob count reaches 100+ per block, full-sidecar gossip becomes too bandwidth-heavy.
9. **Heze PartialDataColumn changes audit**: per item #29, teku has full Heze implementation. Verify teku's Heze codebase doesn't add PartialDataColumn implementations (would diverge from current Fulu state).
10. **Generate dedicated EF fixtures** for `verify_partial_data_column_*` functions; would force 5-of-6 implementation requirement.

## Summary

EIP-7594 PeerDAS partial-column dissemination is implemented in **only 1 of 6 clients (nimbus)**. Other 5 (prysm with placeholder metadata; lighthouse, teku, lodestar, grandine with zero references) have no implementation. **Major implementation-gap finding** — first such finding in the audit corpus.

**Production impact**: LOW because PartialDataColumnSidecar is an OPTIONAL gossip optimization (eager-push of partial cells); the full-sidecar gossip topic (item #34 covered) handles all data-availability needs. nimbus's partial publishing (if active) is wasted bandwidth.

**NEW Pattern Z candidate for item #28 catalogue**: implementation gap on optional spec features. Distinct from format/encoding/orchestration divergences (Patterns A–Y); first "implementation gap" pattern in the catalogue.

**Nimbus-specific concerns**:
1. **Apparent bug** in `verify_partial_data_column_sidecar_kzg_proofs`: uses blob index `i` instead of `column_index` for `cell_indices`. Spec says: "The cell index is the column index for all cells in this column" → should be `[column_index] * len(blob_indices)`. **Spec compliance issue requiring verification with nimbus team.**
2. **Function signature divergence**: nimbus omits `column_index` parameter from spec function signature.
3. **Field naming**: `partial_columns` (plural) vs spec `partial_column` (singular).

**With this audit, the Fulu PeerDAS p2p extension surface is closed**. PeerDAS audit corpus now spans 10 items: #33 custody → #34 verify → #35 DA → #37 subnet → #38 validator custody → #39 math → #40 proposer construction → #41 cgc → #42 nfd → **#44 partial-sidecar**. Ten-item arc covering the consensus-critical PeerDAS surface end-to-end + complete peer-discovery layer + p2p extension implementation gap analysis.

**Total Fulu-NEW items: 15 (#30–#44)**. Item #28 catalogue Patterns A–Z (26 patterns).

**Forward-research priority**: nimbus bug verification + file consensus-specs ambiguity report on partial-column mandatory/optional status.
