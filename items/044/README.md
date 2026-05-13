---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [28, 29, 34, 39, 40, 43]
eips: [EIP-7594, EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 44: `PartialDataColumnSidecar` family (`verify_partial_data_column_header_inclusion_proof` + `verify_partial_data_column_sidecar_kzg_proofs` at Fulu; container reshape + `PartialDataColumnGroupID` at Gloas)

## Summary

Fulu p2p extension for distributed blob publishing — implements cell-level dissemination on top of the existing `data_column_sidecar_{subnet_id}` gossip topic via libp2p's Partial Message Extension. The spec defines two helpers (`verify_partial_data_column_header_inclusion_proof`, `verify_partial_data_column_sidecar_kzg_proofs`) and two containers (`PartialDataColumnSidecar`, `PartialDataColumnHeader`, with an auxiliary `PartialDataColumnPartsMetadata`).

**Fulu surface (carried forward from 2026-05-04 audit):**

- **1 of 6 clients implements** the on-the-wire surface: nimbus.
- prysm + lodestar carry **spec-tracking placeholders only** (`.ethspecify.yml`, `specrefs/`) with no source code.
- lighthouse + teku + grandine have **zero references** in any form.
- Production impact LOW because PartialDataColumnSidecar is an OPTIONAL gossip optimization — the full-sidecar gossip topic (item #34 covered) still satisfies all data-availability requirements. The full-sidecar `DataColumnSidecar` mesh stays the consensus-critical path regardless.

**Gloas surface (at the Glamsterdam target):** `vendor/consensus-specs/specs/gloas/partial-columns/p2p-interface.md` introduces two material spec changes (still on a work-in-progress notice):

1. **`Modified PartialDataColumnSidecar`** — the `header: List[PartialDataColumnHeader, 1]` field is REMOVED. The Gloas sidecar carries only `cells_present_bitmap + partial_column + kzg_proofs`.
2. **`New PartialDataColumnGroupID`** — replaces the Fulu group-ID-is-block-root convention with an explicit container `{slot: Slot, beacon_block_root: Root}`, prefixed by version byte `0x01` (Fulu used `0x00`).
3. **`verify_partial_data_column_header_inclusion_proof` is functionally REMOVED at Gloas** because the header is no longer carried in the sidecar; `verify_partial_data_column_sidecar_kzg_proofs` is now called with `bid.blob_kzg_commitments` rather than `header.kzg_commitments` (driven by EIP-7732 PBS — the bid replaces the header as the commitments authority).

**Gloas readiness across clients:**

- **lodestar**: only client to carry a Gloas-NEW `PartialDataColumnGroupID#gloas` placeholder (`vendor/lodestar/specrefs/containers.yml:1447-1451`), still without source implementation.
- **nimbus**: the existing nimbus Fulu container at `vendor/nimbus/beacon_chain/spec/datatypes/fulu.nim:114-117` is **already Gloas-shape** — nimbus dropped the `header` field from the start (`PartialDataColumnHeader` is a separate top-level type at `:125`, never inlined). At Gloas activation, nimbus's container is forward-compatible by accident. `assemble_partial_data_column_sidecars` at `vendor/nimbus/beacon_chain/spec/peerdas_helpers.nim:378-415` has a Gloas guard (`when signed_beacon_block is gloas.SignedBeaconBlock: debugGloasComment "kzg_commitments removed from beaconblock in gloas"; return sidecars`) — it returns an empty seq for Gloas blocks. **Nimbus has stubbed out Gloas partial-column construction**; the Fulu code path is Fulu-only.
- **prysm + teku + lighthouse + grandine**: still no source implementation; their Gloas readiness is not measurable beyond "nothing to break."

**Pattern Z (item #28 catalogue)**: optional-spec-feature implementation gap. 5-of-6 (Fulu) or 6-of-6 (Gloas, if `assemble_partial_data_column_sidecars` Gloas stub counts as "not implemented") missing. Carries forward into Glamsterdam unchanged.

**Cross-cut to item #43 (Engine API surface, Gloas-NEW V6 getPayload)**: at Gloas, the PartialDataColumnSidecar KZG verification uses `bid.blob_kzg_commitments`. The `bid` is part of the `ExecutionPayloadEnvelope` returned by `engine_getPayloadV6` (per `vendor/consensus-specs/specs/gloas/builder.md:114`). The 3-of-6 Gloas Engine API V6 wiring gap (lighthouse + nimbus + grandine missing per item #43) therefore COMPOSES with this audit's 5-of-6 partial-column gap: a Gloas-active deployment would need both Engine API V6 + partial-column verification to participate in partial-dissemination at Gloas. **None of the 6 clients have the complete Gloas partial-column surface today.**

**Impact: none** — Fulu surface gap is OPTIONAL (no consensus divergence); Gloas surface is not mainnet-reachable (`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH`). Twenty-fifth `impact: none` result in the recheck series.

## Question

Pyspec defines the surface in two locations: `vendor/consensus-specs/specs/fulu/partial-columns/p2p-interface.md` (Fulu base) and `vendor/consensus-specs/specs/gloas/partial-columns/p2p-interface.md` (Gloas modification, still flagged "work-in-progress for researchers and implementers" per file header).

Three recheck questions:

1. **Fulu surface** — does the 1-of-6 implementation status still hold? Has any client added an implementation since the 2026-05-04 audit?
2. **Glamsterdam target — Gloas container reshape + PartialDataColumnGroupID** — which clients have started Gloas readiness work (placeholder metadata, dispatch stubs, etc.)? How does the Pattern M lighthouse + grandine Gloas-ePBS readiness cohort (item #43) interact here?
3. **Pattern Z forward-fragility** — at what point would partial-column dissemination be promoted from optional to mandatory? Does the Gloas spec WIP status indicate the surface is still moving?

## Hypotheses

- **H1.** All 6 clients implement `PartialDataColumnSidecar` + verify functions at Fulu. **EXPECTED VIOLATION**: only nimbus has source implementation.
- **H2.** Spec marks the Fulu partial-column surface as OPTIONAL ("Distributed blob publishing using blobs retrieved from local execution-layer client").
- **H3.** `verify_partial_data_column_header_inclusion_proof` (Fulu) shares structure with `verify_data_column_sidecar_inclusion_proof` (item #34): same depth, same gindex, same body root.
- **H4.** `verify_partial_data_column_sidecar_kzg_proofs` filters commitments via `cells_present_bitmap` and calls `verify_cell_kzg_proof_batch` with cell_indices = `[column_index] * len(blob_indices)` (all cells in one partial sidecar come from the same column, so cell_index is repeated).
- **H5.** Header is OPTIONAL in Fulu (`List[PartialDataColumnHeader, 1]` = 0 or 1 element) — only sent on eager pushes.
- **H6.** *(Glamsterdam target — container reshape)* At Gloas the `header` field is removed from `PartialDataColumnSidecar` (EIP-7732 — bid replaces header). `PartialDataColumnHeader` and `verify_partial_data_column_header_inclusion_proof` become dead code.
- **H7.** *(Glamsterdam target — new PartialDataColumnGroupID)* Gloas introduces `PartialDataColumnGroupID(Container) {slot: Slot, beacon_block_root: Root}` prefixed with version byte `0x01`; Fulu used version byte `0x00` with a flat block-root group-ID.
- **H8.** *(Glamsterdam target — KZG verification)* At Gloas, `verify_partial_data_column_sidecar_kzg_proofs` is called with `bid.blob_kzg_commitments` (item #43 cross-cut: the bid comes from the `engine_getPayloadV6` builder bundle).
- **H9.** Pattern Z (item #28): optional-spec-feature implementation gap. 5-of-6 (Fulu) gap persists; Gloas readiness gap potentially 6-of-6 if nimbus's `assemble_partial_data_column_sidecars` Gloas stub counts as no-implementation.
- **H10.** *(Glamsterdam target — spec stability)* Gloas partial-columns spec carries the "work-in-progress for researchers and implementers" note — surface may still move pre-Glamsterdam activation.

## Findings

H1 violated (1-of-6 at Fulu, with prysm + lodestar carrying spec-tracking metadata only). H2 ✓. H3 ✓ (nimbus implementation matches item #34 pattern). H4 ⚠ (nimbus signature omits `column_index`; uses blob-index `i` for `cellIndices` instead of repeated `column_index`). H5 ✓ (spec text + nimbus container shape). H6 ✓ (spec confirms). H7 ✓ (spec confirms). H8 ✓ (spec confirms `bid.blob_kzg_commitments`). H9 ✓ (Pattern Z holds + extends). H10 ✓ (Gloas spec WIP notice).

### prysm

`vendor/prysm/.ethspecify.yml:95` lists `PartialDataColumnSidecar#fulu` as a tracked container. `vendor/prysm/specrefs/containers.yml:1489-1493`:

```yaml
- name: PartialDataColumnSidecar#fulu
  hash: 91f75478
  type: container
  spec_text: |
    <spec ssz_object="PartialDataColumnSidecar" fork="fulu" hash="91f75478">
    class PartialDataColumnSidecar(Container):
```

`vendor/prysm/specrefs/functions.yml:13192` references `verify_partial_data_column_sidecar_kzg_proofs`. **No Go source code implementation under `vendor/prysm/beacon-chain/` or `vendor/prysm/consensus-types/`** — these are `ethspecify`-tool spec-tracking metadata only, placeholder for future implementation work.

**No Gloas-tracking entry** for `PartialDataColumnGroupID#gloas`. Prysm has not yet scheduled Gloas readiness on the partial-column surface.

### lighthouse

Empty: `grep -rn "PartialDataColumnSidecar\|PartialDataColumnHeader\|verify_partial_data_column" vendor/lighthouse/beacon_node/` returns zero matches. Same for `vendor/lighthouse/consensus/`. **No tracking metadata, no source, no Gloas placeholders.** Lighthouse's Pattern M Gloas-ePBS readiness cohort (item #43) extends naturally: the missing Engine API V6 wiring is paralleled by missing partial-column infrastructure.

### teku

Empty: `grep -rn "PartialDataColumnSidecar\|verify_partial_data_column" vendor/teku/ethereum/ vendor/teku/p2p/` returns zero. The only references in the teku tree are spec-test-execution shims (`vendor/teku/eth-reference-tests/.../SszTestExecutor.java`) that route to the generic SSZ test harness. **No source-code implementation of the helpers or containers.**

### nimbus

Container (`vendor/nimbus/beacon_chain/spec/datatypes/fulu.nim:114-117`):

```nim
PartialDataColumnSidecar* = object
  cells_present_bitmap*: BitArray[int(MAX_BLOB_COMMITMENTS_PER_BLOCK)]
  partial_columns*: List[KzgCell, Limit(MAX_BLOB_COMMITMENTS_PER_BLOCK)]
  kzg_proofs*: deneb.KzgProofs
```

Two divergences vs Fulu spec:

- spec field name `partial_column` (singular) vs nimbus `partial_columns` (plural). Cosmetic.
- spec includes `header: List[PartialDataColumnHeader, 1]` — **nimbus omits this field entirely**. The Fulu spec includes it; nimbus does not. **Forward-compatibility by accident**: this is exactly the Gloas-modified shape (`vendor/consensus-specs/specs/gloas/partial-columns/p2p-interface.md:35-41` removes `header`). Nimbus's Fulu container is already Gloas-compliant.

`PartialDataColumnHeader` exists as a separate top-level type at `:125-129` rather than inlined.

Proposer-side construction (`vendor/nimbus/beacon_chain/spec/peerdas_helpers.nim:378-415`):

```nim
proc assemble_partial_data_column_sidecars*(
    signed_beacon_block: fulu.SignedBeaconBlock,
    blobs: seq[KzgBlob], cell_proofs: seq[Opt[KzgProof]]): seq[fulu.PartialDataColumnSidecar] =
  ## Returns a seq where element i corresponds to column index i.
  var sidecars = newSeqOfCap[fulu.PartialDataColumnSidecar](CELLS_PER_EXT_BLOB)

  when signed_beacon_block is gloas.SignedBeaconBlock:
    debugGloasComment "kzg_commitments removed from beaconblock in gloas"
    return sidecars
  else:
    ...
    for columnIndex in 0..<CELLS_PER_EXT_BLOB:
      ...
      sidecars.add fulu.PartialDataColumnSidecar(
        cells_present_bitmap: bitmap,
        partial_columns: DataColumn.init(partialColumn),
        kzg_proofs: deneb.KzgProofs.init(partialProofs))
```

**Nimbus has a Gloas stub** — when called on a `gloas.SignedBeaconBlock`, the function returns an empty seq with a `debugGloasComment "kzg_commitments removed from beaconblock in gloas"` annotation. At Gloas activation, nimbus would publish NO partial-column sidecars unless this stub is replaced with a real impl that reads `bid.blob_kzg_commitments` from the `ExecutionPayloadEnvelope` (item #43 cross-cut).

KZG-proof verification (`vendor/nimbus/beacon_chain/spec/peerdas_helpers.nim:417-444`):

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
```

Spec (`vendor/consensus-specs/specs/fulu/partial-columns/p2p-interface.md:125-145`):

```python
def verify_partial_data_column_sidecar_kzg_proofs(
    sidecar: PartialDataColumnSidecar,
    all_commitments: List[KZGCommitment, MAX_BLOB_COMMITMENTS_PER_BLOCK],
    column_index: ColumnIndex,
) -> bool:
    blob_indices = [i for i, b in enumerate(sidecar.cells_present_bitmap) if b]
    # The cell index is the column index for all cells in this column
    cell_indices = [CellIndex(column_index)] * len(blob_indices)
    return verify_cell_kzg_proof_batch(
        commitments_bytes=[all_commitments[i] for i in blob_indices],
        cell_indices=cell_indices,
        cells=sidecar.partial_column,
        proofs_bytes=sidecar.kzg_proofs,
    )
```

**Nimbus spec divergence (unchanged from 2026-05-04 audit)**:

1. **Missing `column_index` parameter** — nimbus's signature is `(sidecar, all_commitments)`. Without `column_index`, nimbus cannot construct the spec's `cell_indices = [column_index] * len(blob_indices)` vector.
2. **Uses blob-index `i` as the cell-index** instead — `cellIndices.add(CellIndex(i))` where `i` iterates over `all_commitments`. This treats `cell_index` as the row position (blob index), but per spec a "cell index" in a column sidecar is the COLUMN POSITION (0..127 within the extended polynomial), repeated for each cell because all cells in this partial sidecar live at the same column.

Without `column_index` plumbed through, the verification will fail KZG batch verification against any honest sender unless callers happen to construct an `all_commitments` that "luckily" has indices aligning with the column index — which is not the case in any conformant Fulu publisher.

Because no other client implements this surface, the bug is not observable on mainnet (and would only manifest if two nimbus nodes were to exchange Fulu-spec-conformant partial sidecars). Filed as a future research item — verification with the nimbus team is required to determine whether this is a deliberate API choice with caller-side fixup or a defect.

Header-inclusion-proof verification (`vendor/nimbus/beacon_chain/spec/peerdas_helpers.nim:513-527`):

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

Same dynamic-gindex pattern as nimbus's full-sidecar verify (item #34). Spec-faithful for Fulu. **At Gloas this entire function becomes dead code** because the Gloas spec removes the header from `PartialDataColumnSidecar` (EIP-7732) and removes the `verify_partial_data_column_header_inclusion_proof` REJECT rule from the gossip validation. Nimbus has not yet annotated/guarded this function for Gloas removal.

### lodestar

`vendor/lodestar/specrefs/containers.yml:1447-1451`:

```yaml
- name: PartialDataColumnGroupID#gloas
  hash: 9e8865b1
  type: container
  spec_text: |
    <spec container="PartialDataColumnGroupID" fork="gloas" hash="9e8865b1">
    class PartialDataColumnGroupID(Container):
```

Plus `vendor/lodestar/specrefs/.ethspecify.yml:66` lists `PartialDataColumnGroupID#gloas`. **Spec-tracking metadata only; no TypeScript source code under `vendor/lodestar/packages/beacon-node/`.**

**Lodestar is the only client to carry a Gloas-NEW `PartialDataColumnGroupID` tracking entry.** Even though there's no source implementation, lodestar has documented awareness of the Gloas container reshape. This is a forward-readiness signal that no other client carries.

### grandine

The only match is in `vendor/grandine/scripts/ci/consensus-spec-tests-coverage.rb` (CI coverage tracking script that counts which spec-test fixture categories exist). **No Rust source-code implementation** under `vendor/grandine/eip_7594/`, `vendor/grandine/fork_choice_control/`, `vendor/grandine/helper_functions/`, or `vendor/grandine/types/`.

## Cross-reference table

| Client | H1 Fulu impl | H3 inclusion-proof | H4 KZG-proofs verify | H5 header optional | H6 Gloas header removal | H7 Gloas GroupID placeholder | H8 Gloas bid commitments | H9 Pattern Z | Notes |
|---|---|---|---|---|---|---|---|---|---|
| **prysm** | ❌ (specrefs/.ethspecify.yml metadata only; `specrefs/containers.yml:1489`, `specrefs/functions.yml:13192`) | — | — | — | — | ❌ (no `PartialDataColumnGroupID#gloas`) | — | gap | Spec-tracking placeholder; no Go source |
| **lighthouse** | ❌ zero references | — | — | — | — | ❌ | — | gap | Pattern M cohort symptom |
| **teku** | ❌ zero references | — | — | — | — | ❌ | — | gap | No source; only generic SSZ-test shim |
| **nimbus** | ✅ partial (verify funcs + assemble) | ✅ `peerdas_helpers.nim:513-527` (dynamic gindex; spec-faithful at Fulu, dead at Gloas) | ⚠ signature omits `column_index`; uses blob-index `i` for `cellIndices` — divergent from spec | ✅ (container omits header field — already Gloas-shape by accident) | ⚠ `assemble_partial_data_column_sidecars` has Gloas stub returning empty seq (`peerdas_helpers.nim:384-386`) | ❌ no `PartialDataColumnGroupID` definition | ⚠ stub returns empty seq for `gloas.SignedBeaconBlock` — no bid-based wiring | exception | Only impl; forward-compat by accident on container shape |
| **lodestar** | ❌ specrefs metadata only | — | — | — | — | ✅ `specrefs/containers.yml:1447-1451` `PartialDataColumnGroupID#gloas` placeholder | — | gap | Only client with Gloas-NEW container tracking entry |
| **grandine** | ❌ zero references (CI coverage script only) | — | — | — | — | ❌ | — | gap | Pattern M cohort symptom |

**Counts**: Fulu source-code implementation 1/6 (nimbus). Spec-tracking placeholders 2 more (prysm + lodestar). Zero references 3 (lighthouse + teku + grandine). Gloas `PartialDataColumnGroupID` tracking 1/6 (lodestar). Gloas-shape forward-compat container 1/6 (nimbus, by accident).

## Empirical tests

- ✅ **Live Fulu mainnet operation since 2025-12-03**: 5+ months. PartialDataColumnSidecar gossip is OPTIONAL; clients that don't implement it (5 of 6) skip the topic. No correctness divergence observed because full-sidecar gossip (item #34) carries all DA traffic. **Verifies H2 (optional surface) at production scale.**
- ⏭ **Cross-client interop test**: have a nimbus node publish a partial sidecar; verify the other 5 ignore it gracefully (no gossip-score penalty, no peer disconnection). Not yet executed; would close the "wasted bandwidth" question definitively.
- ⏭ **Nimbus self-interop**: nimbus-to-nimbus partial sidecar exchange. If two nimbus nodes are connected and partial-column gossip is enabled, does KZG verification pass? Tests H4 — would expose the blob-index-vs-column-index divergence in `verify_partial_data_column_sidecar_kzg_proofs`.
- ⏭ **Spec-test fixtures**: there are no EF fixtures for `verify_partial_data_column_*` in `vendor/consensus-specs/tests/fixtures/` because the Fulu p2p surface is optional. If EF generates fixtures (e.g. when Gloas stabilises), the 5-of-6 implementation gap converts from "optional optimization missing" to "spec-test conformance failure."
- ⏭ **Gloas readiness fixture**: cross-client `PartialDataColumnGroupID` encoding/decoding test (version byte `0x01` + `{slot, beacon_block_root}` SSZ). Only lodestar carries the container tracking entry; the other 5 have no scaffolding.
- ⏭ **Spec stability watch**: the Gloas partial-columns p2p-interface.md carries a "work-in-progress for researchers and implementers" note. Track future spec PRs that may continue to modify the surface (e.g. additional REJECT rules, group-ID version bumps, bid-vs-header semantics).

## Conclusion

The Fulu PartialDataColumnSidecar surface remains a 1-of-6 implementation gap. Nimbus is the only client with source code; prysm and lodestar carry spec-tracking placeholders; lighthouse, teku, and grandine carry nothing. No mainnet-observable divergence — the surface is OPTIONAL and the full-sidecar gossip (item #34) handles all data-availability traffic.

The Glamsterdam target introduces three Gloas-NEW changes: the `header` field is removed from `PartialDataColumnSidecar`; `PartialDataColumnGroupID` is added (versioned `0x01` group-ID replacing Fulu's flat block-root + `0x00` byte); `verify_partial_data_column_header_inclusion_proof` becomes dead code and KZG verification migrates from `header.kzg_commitments` to `bid.blob_kzg_commitments`. The `bid` flows in from the `engine_getPayloadV6` builder bundle (item #43 cross-cut) — and 3 of 6 clients lack the Engine API V6 wiring entirely (Pattern M cohort = lighthouse + grandine; plus nimbus partial gap per item #43). Composing these gaps: **none of the 6 clients have the complete Gloas partial-column surface today**, but the deployment timeline is `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH`, so this is forward-fragility tracking, not present-tense divergence.

Notable items unchanged from the 2026-05-04 audit:

- Nimbus container forward-compatibility by accident: nimbus's Fulu `PartialDataColumnSidecar` (`vendor/nimbus/beacon_chain/spec/datatypes/fulu.nim:114-117`) already omits the `header` field, which is precisely the Gloas-modified shape. The container ships Gloas-ready today.
- Nimbus `verify_partial_data_column_sidecar_kzg_proofs` (`vendor/nimbus/beacon_chain/spec/peerdas_helpers.nim:417-444`) still diverges from spec by omitting the `column_index` parameter and using blob-index `i` for `cellIndices` instead of `[column_index] * len(blob_indices)`. Filed as a future research item; not mainnet-observable because no other client publishes partial sidecars for nimbus to cross-verify against.
- Nimbus `assemble_partial_data_column_sidecars` (`peerdas_helpers.nim:378-415`) now has a Gloas stub that returns an empty seq with a `debugGloasComment` annotation. This is the only Gloas-aware partial-column code path in any of the 6 clients — but it is a no-op stub, not an implementation.

Pattern Z (optional-spec-feature implementation gap) extends from Fulu to Glamsterdam unchanged. With the Gloas spec carrying a "work-in-progress" notice, the surface may still move; the 5-of-6 gap is unlikely to close before activation given the current trajectory.

**Impact: none** — Fulu OPTIONAL surface, Gloas not mainnet-reachable. Twenty-fifth `impact: none` result in the recheck series.
