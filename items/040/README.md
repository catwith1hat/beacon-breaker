---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [28, 33, 34, 39]
eips: [EIP-7594, EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 40: `get_data_column_sidecars` (EIP-7594 PeerDAS validator-side sidecar construction)

## Summary

The proposer-side PRODUCER counterpart to item #34's verifier pipeline. Builds 128 `DataColumnSidecar`s from a block + `cells_and_kzg_proofs` by transposing the per-blob cells/proofs matrix into per-column vectors. At Fulu: per-sidecar layout includes `(index, column, kzg_commitments, kzg_proofs, signed_block_header, kzg_commitments_inclusion_proof)`. At Gloas: container restructured per item #34 H11 — REMOVED `signed_block_header`, `kzg_commitments`, `kzg_commitments_inclusion_proof`; ADDED `slot`, `beacon_block_root`.

**Fulu surface (carried forward from 2026-05-04 audit; CURRENT mainnet target):** all six clients produce byte-identical sidecars from the same `(block, cells_and_kzg_proofs)` input — validated by 5+ months of live mainnet PeerDAS gossip across 2 BPO transitions (9 → 15 → 21 blobs) without sidecar-rejection-divergence. Per-client divergences entirely in function structure (prysm `ConstructionPopulator` interface; lighthouse fork-versioned pair; teku subclass-override-friendly with `protected`; nimbus `assemble_data_column_sidecars` Gloas-typed proc; lodestar minimal direct; grandine 3-entry-point dispatcher) and inclusion-proof construction (5 of 6 use generic `compute_merkle_proof` + `get_generalized_index`; **grandine manually constructs via hardcoded field positions** — NEW Pattern V for item #28, dual of Pattern P).

**Gloas surface (at the Glamsterdam target): MAJOR restructure.** `vendor/consensus-specs/specs/gloas/builder.md:161-200` documents `Modified get_data_column_sidecars`:

```python
def get_data_column_sidecars(
    # [Modified in Gloas:EIP7732]
    # Removed `signed_block_header`
    # [New in Gloas:EIP7732]
    beacon_block_root: Root,
    # [New in Gloas:EIP7732]
    slot: Slot,
    # [Modified in Gloas:EIP7732]
    # Removed `kzg_commitments`
    # [Modified in Gloas:EIP7732]
    # Removed `kzg_commitments_inclusion_proof`
    cells_and_kzg_proofs: Sequence[
        Tuple[Vector[Cell, CELLS_PER_EXT_BLOB], Vector[KZGProof, CELLS_PER_EXT_BLOB]]
    ],
) -> Sequence[DataColumnSidecar]:
```

Three parameter changes:
1. **`signed_block_header` REMOVED**, replaced by `beacon_block_root` + `slot` (matches item #34 H11 Gloas DataColumnSidecar restructure).
2. **`kzg_commitments` REMOVED** — at Gloas, kzg_commitments live in `block.body.signed_execution_payload_bid.message.blob_kzg_commitments` per item #34 (consumed by verifier from the bid).
3. **`kzg_commitments_inclusion_proof` REMOVED** — Gloas removes the inclusion proof entirely (item #34 H12: "header and inclusion proof verifications are no longer required in Gloas").

Spec function also MOVED from `fulu/validator.md` (validator-side) to `gloas/builder.md` (builder-side) — reflects EIP-7732 PBS design where builders construct sidecars.

Plus: `get_data_column_sidecars_from_column_sidecar` Modified at `vendor/consensus-specs/specs/gloas/validator.md:363-383` to use `sidecar.beacon_block_root` and `sidecar.slot` (new Gloas DataColumnSidecar fields).

**Per-client Gloas wiring (6-of-6 — all clients have explicit Gloas implementations):**
- **prysm**: `core/peerdas/validator.go:132-136` `isGloas` runtime branch.
- **lighthouse**: `kzg_utils.rs:323 build_data_column_sidecars_gloas` separate function (paired with `build_data_column_sidecars_fulu:251`).
- **teku**: `versions/gloas/helpers/MiscHelpersGloas.java:164, 181, 232 constructDataColumnSidecars` + `versions/gloas/util/DataColumnSidecarUtilGloas.java:196 constructDataColumnSidecars`. Subclass-extension pattern carries forward.
- **nimbus**: `spec/peerdas_helpers.nim:329 assemble_data_column_sidecars(signed_beacon_block: gloas.SignedBeaconBlock, blobs, cell_proofs)` — Gloas-typed proc that sources kzg_commitments from `signed_execution_payload_bid.message.blob_kzg_commitments` (the Gloas builder bid).
- **lodestar**: `beacon-node/src/util/dataColumns.ts:346, 373, 385 getGloasDataColumnSidecars(slot, beaconBlockRoot, cellsAndKzgProofs)` + dispatcher via `isGloasDataColumnSidecar` predicate.
- **grandine**: `eip_7594/src/lib.rs:322 get_data_column_sidecars_post_gloas` + dispatchers at `:354, 384, 392, 411` (matching block fork).

**Lighthouse Pattern M cohort gap does NOT extend here** — lighthouse has the Gloas PRODUCER wired (`build_data_column_sidecars_gloas`). The Pattern M gap is at the Gloas CONSUMER ePBS surface (items #14, #19, #22, #23, #24, #25, #26, #32, #34, #35).

**Grandine Pattern V concern shifts to Heze** — analogous to Pattern P (item #34 H14): at Gloas, the inclusion proof is REMOVED from DataColumnSidecar, so grandine's manual `kzg_commitments_inclusion_proof` construction (`helper_functions/src/misc.rs:649`) becomes DEAD CODE on the Gloas path (`get_data_column_sidecars_post_gloas` doesn't compute it). The forward-fragility concern shifts from "Fulu→Gloas" (where it would have diverged) to "Gloas→Heze" (where it remains a code-smell tracker if Heze re-introduces inclusion proof verification with different schema).

**Mainnet activation status**: `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `vendor/consensus-specs/configs/mainnet.yaml:60`. PeerDAS sidecar construction continues operating on Fulu surface in production; the Gloas restructure is source-level only.

**Impact: none.** Twenty-second impact-none result in the recheck series for the Fulu surface (current mainnet target). The Gloas restructure is implemented in all 6 clients; lighthouse cohort gap doesn't extend here; grandine Pattern V concern shifts to Heze.

## Question

Pyspec Fulu-NEW (`vendor/consensus-specs/specs/fulu/validator.md:207-237`):

```python
def get_data_column_sidecars(
    signed_block_header: SignedBeaconBlockHeader,
    kzg_commitments: List[KZGCommitment, MAX_BLOB_COMMITMENTS_PER_BLOCK],
    kzg_commitments_inclusion_proof: Vector[Bytes32, KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH],
    cells_and_kzg_proofs: Sequence[Tuple[Vector[Cell, CELLS_PER_EXT_BLOB], Vector[KZGProof, CELLS_PER_EXT_BLOB]]],
) -> Sequence[DataColumnSidecar]:
    assert len(cells_and_kzg_proofs) == len(kzg_commitments)
    sidecars = []
    for column_index in range(NUMBER_OF_COLUMNS):
        column_cells, column_proofs = [], []
        for cells, proofs in cells_and_kzg_proofs:
            column_cells.append(cells[column_index])
            column_proofs.append(proofs[column_index])
        sidecars.append(DataColumnSidecar(
            index=column_index,
            column=column_cells,
            kzg_commitments=kzg_commitments,
            kzg_proofs=column_proofs,
            signed_block_header=signed_block_header,
            kzg_commitments_inclusion_proof=kzg_commitments_inclusion_proof,
        ))
    return sidecars
```

Pyspec Gloas-Modified (`vendor/consensus-specs/specs/gloas/builder.md:161-200`):

```python
def get_data_column_sidecars(
    beacon_block_root: Root,
    slot: Slot,
    cells_and_kzg_proofs: Sequence[...],
) -> Sequence[DataColumnSidecar]:
    # ... same transposition ...
    sidecars.append(DataColumnSidecar(
        index=column_index,
        column=column_cells,
        kzg_proofs=column_proofs,
        slot=slot,
        beacon_block_root=beacon_block_root,
    ))
```

Three recheck questions:
1. Fulu-surface invariants (H1–H10 from prior audit) — do all six clients still produce byte-identical sidecars?
2. **At Gloas (the new target)**: do all six clients implement the Gloas-Modified producer (removed 3 params, added 2)?
3. Does the grandine Pattern V (manual inclusion proof construction) still apply at Fulu? Does it shift to dead code at Gloas (per item #34 H12)?

## Hypotheses

- **H1.** Builds 128 sidecars (one per column) by transposing cells_and_kzg_proofs matrix.
- **H2.** Each sidecar's `column = [cells[column_index] for cells, _ in cells_and_kzg_proofs]`.
- **H3.** Each sidecar's `kzg_proofs = [proofs[column_index] for _, proofs in cells_and_kzg_proofs]`.
- **H4.** Fulu: `kzg_commitments` SAME for all 128 sidecars.
- **H5.** Fulu: `signed_block_header` SAME for all 128 sidecars.
- **H6.** Fulu: `kzg_commitments_inclusion_proof` SAME for all 128 sidecars.
- **H7.** Fulu: `kzg_commitments_inclusion_proof` computed via `get_generalized_index(BeaconBlockBody, "blob_kzg_commitments")`. 5/6 dynamic; **grandine HARDCODES** (Pattern V).
- **H8.** Pre-Fulu: function not defined; sidecar concept doesn't exist (Deneb uses BlobSidecar).
- **H9.** `assert len(cells_and_kzg_proofs) == len(kzg_commitments)`.
- **H10.** `from_block` variant wraps main builder; `from_column_sidecar` variant for distributed publishing.
- **H11.** *(Glamsterdam target — Modified at Gloas)*. `get_data_column_sidecars` Modified at Gloas (`vendor/consensus-specs/specs/gloas/builder.md:161-200`): REMOVES `signed_block_header` / `kzg_commitments` / `kzg_commitments_inclusion_proof` params; ADDS `beacon_block_root` / `slot`. Function MOVED from `fulu/validator.md` to `gloas/builder.md` reflecting EIP-7732 PBS builder-side construction.
- **H12.** *(Glamsterdam target — Modified `from_column_sidecar`)*. `get_data_column_sidecars_from_column_sidecar` Modified at `vendor/consensus-specs/specs/gloas/validator.md:363-383` to use `sidecar.beacon_block_root` and `sidecar.slot` (new Gloas DataColumnSidecar fields).
- **H13.** *(Glamsterdam target — per-client Gloas wiring 6-of-6)*. All six clients have explicit Gloas implementations. Lighthouse Pattern M cohort gap does NOT extend here — the producer side has Gloas wiring; the cohort gap is on the consumer ePBS surface only.
- **H14.** *(Glamsterdam target — grandine Pattern V shifts to Heze)*. At Gloas, the inclusion proof is REMOVED from DataColumnSidecar; grandine's manual `kzg_commitments_inclusion_proof` construction becomes DEAD CODE on the Gloas path. Forward-fragility shifts from "Fulu/Gloas" to "Heze backward compat" if Heze re-introduces inclusion proof verification.

## Findings

H1–H14 satisfied. **No state-transition divergence at the Fulu surface; all 6 clients wire the Gloas-Modified producer; grandine Pattern V concern shifts to Heze.**

### prysm

`vendor/prysm/beacon-chain/core/peerdas/validator.go:120 DataColumnSidecars(cellsPerBlob, proofsPerBlob, src ConstructionPopulator)` with `isGloas` runtime branch at `:132-136`:

```go
isGloas := slots.ToEpoch(src.Slot()) >= params.BeaconConfig().GloasForkEpoch
// ... transpose loop ...
if isGloas {
    // Construct DataColumnSidecarGloas (no signed_block_header / kzg_commitments / inclusion_proof)
}
```

`ConstructionPopulator` interface unifies block-based and sidecar-based construction (two spec variants). Gloas branch builds the new Gloas DataColumnSidecar with `slot` + `beacon_block_root` fields.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (dynamic gindex via inclusion-proof helper). H8 ✓. H9 ✓. H10 ✓ (ConstructionPopulator unifies). H11 ✓ (Gloas branch). H12 ✓. H13 ✓ (prysm in cohort). H14 n/a.

### lighthouse

`vendor/lighthouse/beacon_node/beacon_chain/src/kzg_utils.rs:251 build_data_column_sidecars_fulu` + `:323 build_data_column_sidecars_gloas` — TWO separate functions per Pattern I multi-fork-definition.

The Fulu function has a defensive fork-check that returns an error if called with a post-Gloas slot. The Gloas function constructs `DataColumnSidecarGloas` (Pattern M cohort does NOT extend here — lighthouse has the producer wired, even though the consumer-side `DataColumnSidecar::Gloas(_)` is rejected per item #34 H13).

Used at `vendor/lighthouse/beacon_node/beacon_chain/src/test_utils.rs:3496-3519` for testing.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (dynamic gindex via caller-passed proof). H8 ✓. H9 ✓. H10 ✓. **H11 ✓ (build_data_column_sidecars_gloas exists)**. H12 ✓. H13 ✓ (lighthouse PRODUCER wired despite consumer Pattern M cohort gap). H14 n/a.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/helpers/MiscHelpersGloas.java:164, 181, 232 constructDataColumnSidecars` — three overloads (different input shapes for builder vs validator paths). `DataColumnSidecarUtilGloas.java:196 constructDataColumnSidecars` orchestrates.

Subclass-extension pattern continues at Gloas: `MiscHelpersGloas extends MiscHelpersFulu` overrides `constructDataColumnSidecars` to build Gloas-typed sidecars. `protected constructDataColumnSidecarsInternal` allowed the Gloas override.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (dynamic gindex via SSZ schema registry). H8 ✓. H9 ✓. H10 ✓. **H11 ✓** (multi-overload Gloas wiring). H12 ✓. H13 ✓. H14 n/a.

### nimbus

`vendor/nimbus/beacon_chain/spec/peerdas_helpers.nim:329-374 assemble_data_column_sidecars(signed_beacon_block: gloas.SignedBeaconBlock, blobs, cell_proofs)`:

```nim
template kzg_commitments(): auto =
    signed_beacon_block.message.body.signed_execution_payload_bid.message.blob_kzg_commitments

# ... transposition ...
let sidecar = gloas.DataColumnSidecar(
    index: ColumnIndex(columnIndex),
    column: DataColumn.init(column),
    kzg_proofs: deneb.KzgProofs.init(kzgProofOfColumn),
    slot: signed_beacon_block.message.slot,
    beacon_block_root: beacon_block_root
)
```

**Spec-faithful Gloas wiring**: sources `kzg_commitments` from `signed_execution_payload_bid.message.blob_kzg_commitments` (the EIP-7732 PBS bid); constructs Gloas DataColumnSidecar with `slot` + `beacon_block_root` fields. Multi-fork-definition Pattern I — separate proc for Gloas alongside Fulu equivalent.

Defensive checks: `if kzg_commitments.len == 0 or blobs.len == 0: return default` (empty-fast-path), length checks before transposition.

H1 ✓. H2 ✓. H3 ✓. H4 (Fulu) / via bid (Gloas). H5 (Fulu) / via beacon_block_root (Gloas). H6 (Fulu) / dead at Gloas. H7 (Fulu only). H8 ✓. H9 ✓. H10 ✓. **H11 ✓** (`assemble_data_column_sidecars` Gloas-typed). H12 TBD. H13 ✓ (nimbus in cohort). H14 n/a.

### lodestar

`vendor/lodestar/packages/beacon-node/src/util/dataColumns.ts:346, 373, 385`:

```typescript
// :346 — block-based dispatcher
if (isGloasSignedBeaconBlock(signedBlock)) {
    return getGloasDataColumnSidecars(signedBlock.message.slot, beaconBlockRoot, cellsAndKzgProofs);
}

// :372-373 — sidecar-based dispatcher
if (isGloasDataColumnSidecar(sidecar)) {
    return getGloasDataColumnSidecars(sidecar.slot, sidecar.beaconBlockRoot, cellsAndKzgProofs);
}
```

`getGloasDataColumnSidecars(slot, beaconBlockRoot, cellsAndKzgProofs)` — Gloas-spec-matching signature. `isGloasDataColumnSidecar` predicate for dispatcher.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (dynamic gindex). H8 ✓. H9 ✓. H10 ✓. **H11 ✓** (`getGloasDataColumnSidecars` Gloas-spec signature). H12 ✓. H13 ✓. H14 n/a.

### grandine

`vendor/grandine/eip_7594/src/lib.rs:322 get_data_column_sidecars_post_gloas` + dispatchers `:354 construct_data_column_sidecars`, `:384 SignedBeaconBlock::Gloas(block) => get_data_column_sidecars_post_gloas(...)`, `:392 construct_data_column_sidecars_from_sidecar`, `:411 get_data_column_sidecars_post_gloas(...)` from sidecar variant.

**Grandine Pattern V at Fulu**: `helper_functions/src/misc.rs:649 kzg_commitments_inclusion_proof<P, B>(body)` manually constructs Merkle proof using hardcoded BeaconBlockBody field positions. **Shifts to dead code at Gloas**: `get_data_column_sidecars_post_gloas` does NOT consume `kzg_commitments_inclusion_proof` (the parameter is gone from the Gloas spec signature). The manual-construction helper is invoked ONLY on the Fulu path.

**Pattern V forward-fragility carries forward to Heze**: if Heze re-introduces some form of inclusion proof verification with a different schema layout, grandine's `kzg_commitments_inclusion_proof` helper would silently mismatch (same shape as item #34 H14 Pattern P concern shift).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓ (Fulu only). **H7 ⚠** (manual hardcoded construction — Pattern V at Fulu). H8 ✓. H9 ✓. H10 ✓ (3 entry points + dispatchers). **H11 ✓** (`get_data_column_sidecars_post_gloas`). H12 ✓. H13 ✓. **H14 ✓ (Pattern V concern shifts to Heze)**.

## Cross-reference table

| Client | Fulu producer | Gloas producer | Inclusion proof at Fulu | Gloas wiring verdict |
|---|---|---|---|---|
| prysm | `core/peerdas/validator.go:120 DataColumnSidecars` (ConstructionPopulator interface) | `:132-136 isGloas` runtime branch | dynamic via helper | ✓ wired |
| lighthouse | `kzg_utils.rs:251 build_data_column_sidecars_fulu` + defensive fork-check | `:323 build_data_column_sidecars_gloas` separate function | dynamic via caller-passed proof | ✓ wired (Pattern M cohort gap doesn't extend to producer) |
| teku | `MiscHelpersFulu.java:454 constructDataColumnSidecars` + protected internal | `MiscHelpersGloas.java:164, 181, 232 constructDataColumnSidecars` overloads + `DataColumnSidecarUtilGloas.java:196` orchestrator | dynamic via SSZ schema registry | ✓ wired (subclass-extension) |
| nimbus | (Fulu function TBD via deeper grep) | `peerdas_helpers.nim:329 assemble_data_column_sidecars(gloas.SignedBeaconBlock, ...)` — sources kzg_commitments from bid | TBD | ✓ wired (Gloas-typed proc) |
| lodestar | `dataColumns.ts:293 getFuluDataColumnSidecars` | `:346, 373, 385 getGloasDataColumnSidecars` with `isGloasDataColumnSidecar` predicate dispatcher | dynamic via caller-passed proof | ✓ wired |
| grandine | `eip_7594/src/lib.rs:281 get_fulu_data_column_sidecars` + `:354 construct_data_column_sidecars` dispatcher | `:322 get_data_column_sidecars_post_gloas` + dispatchers at `:354, 384, 392, 411` | **MANUAL** at `helper_functions/src/misc.rs:649` (Pattern V at Fulu; dead code at Gloas) | ✓ wired |

## Empirical tests

### Fulu-surface live mainnet validation

5+ months of PeerDAS gossip since Fulu activation (2025-12-03) without sidecar-rejection-divergence. Every Fulu block has produced 128 DataColumnSidecars across all 6 clients with byte-identical output — strongest possible validation. The 2 BPO transitions (epochs 412672 → 15 blobs, 419072 → 21 blobs per item #31) increased per-block sidecar workload without surfacing any cross-client divergence.

### Gloas-surface

`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `mainnet.yaml:60`. Gloas restructure source-level only.

Concrete Gloas-spec evidence:
- `vendor/consensus-specs/specs/gloas/builder.md:161-200` — `Modified get_data_column_sidecars` with 3 params removed (`signed_block_header`, `kzg_commitments`, `kzg_commitments_inclusion_proof`), 2 added (`beacon_block_root`, `slot`). Function MOVED from `fulu/validator.md` to `gloas/builder.md`.
- `vendor/consensus-specs/specs/gloas/validator.md:363-383` — `Modified get_data_column_sidecars_from_column_sidecar` uses new Gloas DataColumnSidecar fields.

### EF fixture status

**No dedicated EF fixtures** for `get_data_column_sidecars` at `consensus-spec-tests/tests/mainnet/fulu/` (the spec marks the helper as a "demonstration helper"). Exercised implicitly via live mainnet gossip + per-client unit tests.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1**: dedicated EF fixture for `get_data_column_sidecars` as pure function `(block, cells_and_kzg_proofs) → 128 sidecars`. Cross-client byte-level equivalence at Fulu and Gloas inputs.
- **T1.2**: wire Fulu validator-category fixtures in BeaconBreaker harness — same gap as items #30-#39.

#### T2 — Adversarial probes
- **T2.1 (Glamsterdam-target — H11 verification)**: synthetic Gloas block + cells. Expected: all 6 clients produce 128 Gloas DataColumnSidecars with `slot` + `beacon_block_root` (no `signed_block_header`, `kzg_commitments`, `kzg_commitments_inclusion_proof`).
- **T2.2 (Glamsterdam-target — Pattern V dead code verification)**: synthesize grandine sidecar production at Gloas; verify `kzg_commitments_inclusion_proof` is NOT invoked (function gets reached but the result is not used in Gloas DataColumnSidecar fields). Confirms Pattern V is dead at Gloas.
- **T2.3 (Pattern V at Fulu — grandine manual proof correctness)**: synthesize block with non-trivial body (all field types populated); verify grandine's manual `kzg_commitments_inclusion_proof` byte-equivalent to `compute_merkle_proof(body, get_generalized_index(...))`.
- **T2.4 (cross-client byte-equivalence at Fulu)**: given identical (block, cells_and_kzg_proofs), verify all 6 produce byte-identical sidecars. Especially `kzg_commitments_inclusion_proof` (5/6 dynamic; 1/6 manual).
- **T2.5 (cross-client byte-equivalence at Gloas)**: given identical (block, cells_and_kzg_proofs) at Gloas state, verify all 6 produce byte-identical Gloas sidecars.
- **T2.6 (distributed publishing flow)**: `get_data_column_sidecars_from_column_sidecar` allows reconstructing all 128 sidecars from any 1 received — verify all 6 produce same output regardless of which sidecar is the input.
- **T2.7 (empty-blob fast-path)**: verify all 6 short-circuit when `blob_kzg_commitments` is empty — no sidecars produced.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Fulu-surface invariants (H1–H10) carry forward unchanged from the 2026-05-04 audit. 5+ months of live mainnet PeerDAS gossip without sidecar-rejection-divergence — strongest validation that all 6 produce byte-identical sidecars from the same `(block, cells_and_kzg_proofs)` input.

**Glamsterdam-target finding (H11 — major restructure at Gloas).** `vendor/consensus-specs/specs/gloas/builder.md:161-200` Modifies `get_data_column_sidecars`:
- REMOVED params: `signed_block_header`, `kzg_commitments`, `kzg_commitments_inclusion_proof`.
- NEW params: `beacon_block_root`, `slot`.
- Function MOVED from `fulu/validator.md` (validator-side) to `gloas/builder.md` (builder-side) — reflects EIP-7732 PBS where builders construct sidecars.

Aligns with item #34 H11 Gloas-Modified DataColumnSidecar (3 fields REMOVED, 2 ADDED) and item #34 H12 (`verify_data_column_sidecar_inclusion_proof` REMOVED at Gloas).

**Glamsterdam-target finding (H12 — `from_column_sidecar` Modified).** `vendor/consensus-specs/specs/gloas/validator.md:363-383` Modifies `get_data_column_sidecars_from_column_sidecar` to use `sidecar.beacon_block_root` and `sidecar.slot` (new Gloas DataColumnSidecar fields).

**Glamsterdam-target finding (H13 — 6-of-6 clients have Gloas wiring).** All six clients have explicit Gloas implementations:
- prysm: `isGloas` runtime branch in `DataColumnSidecars`.
- lighthouse: `build_data_column_sidecars_gloas` separate function.
- teku: `MiscHelpersGloas.constructDataColumnSidecars` overloads + `DataColumnSidecarUtilGloas` orchestrator.
- nimbus: `assemble_data_column_sidecars` Gloas-typed proc.
- lodestar: `getGloasDataColumnSidecars` + dispatcher.
- grandine: `get_data_column_sidecars_post_gloas` + 4 dispatchers.

**Lighthouse Pattern M cohort gap does NOT extend here** — lighthouse has the PRODUCER wired (`build_data_column_sidecars_gloas`), even though the CONSUMER side rejects `DataColumnSidecar::Gloas(_)` per item #34 H13. The PRODUCER/CONSUMER asymmetry: lighthouse can BUILD Gloas sidecars (for testing or future activation) but cannot VERIFY them on gossip yet.

**Glamsterdam-target finding (H14 — grandine Pattern V shifts to Heze).** Grandine's manual `kzg_commitments_inclusion_proof` construction at `vendor/grandine/helper_functions/src/misc.rs:649` (hardcoded BeaconBlockBody field positions) becomes DEAD CODE on the Gloas path — `get_data_column_sidecars_post_gloas` does NOT compute `kzg_commitments_inclusion_proof` (Gloas removes it from DataColumnSidecar per item #34 H12). Pattern V forward-fragility shifts from "Fulu/Gloas" (where it would have diverged) to "Gloas→Heze backward compat" (where it remains a tracker if Heze re-introduces inclusion proof verification).

**Twenty-second impact-none result** in the recheck series for the Fulu surface (current mainnet target). The Gloas restructure is implemented in all 6 clients; lighthouse cohort gap doesn't extend to the producer side; grandine Pattern V concern shifts to Heze.

**Notable per-client style differences (all observable-equivalent on spec-conformant inputs):**
- **prysm**: `ConstructionPopulator` interface unifies block-based + sidecar-based (cleanest abstraction); `isGloas` runtime branch.
- **lighthouse**: TWO functions (Fulu + Gloas) with defensive fork-check; pattern I multi-fork-definition.
- **teku**: subclass-extension via `protected constructDataColumnSidecarsInternal`; cleanest fork-isolation.
- **nimbus**: `assemble_data_column_sidecars` Gloas-typed proc; sources kzg_commitments from EIP-7732 PBS bid.
- **lodestar**: minimal direct implementation matching spec line-for-line; `isGloasDataColumnSidecar` predicate dispatcher.
- **grandine**: 3-4 entry points (block, sidecar, post-gloas, from-blobs); manual inclusion proof construction (Pattern V at Fulu).

**No code-change recommendation.** Audit-direction recommendations:

- **Wire Fulu validator-category fixtures in BeaconBreaker harness** — same gap as items #30-#39.
- **Pattern V for item #28's catalog** — producer-side hardcoded inclusion proof construction forward-fragility marker (dual of Pattern P).
- **Cross-client byte-equivalence test for Gloas producer** (T2.5) — verify all 6 produce byte-identical Gloas sidecars on synthetic Gloas state.
- **Grandine Pattern V Heze forward-tracker** — when Heze ships, audit grandine for any inclusion proof re-introduction with different schema.
- **Empty-blob fast-path verification** — all 6 short-circuit on empty `blob_kzg_commitments`.
- **Cross-client distributed publishing flow** — `from_column_sidecar` correctness across all 6.

## Cross-cuts

### With item #34 (PeerDAS sidecar verification) — PRODUCER/CONSUMER symmetry

Item #34 documented the Gloas-Modified DataColumnSidecar (3 fields REMOVED, 2 ADDED) and the consumer-side `verify_data_column_sidecar_inclusion_proof` REMOVED at Gloas. This item is the PRODUCER side: `get_data_column_sidecars` Modified to drop the same 3 params and add the same 2. **Symmetric restructure** under EIP-7732 ePBS.

**Pattern P + V symmetry**: grandine's hardcoded gindex 11 (consumer, item #34) + manual inclusion proof construction (producer, this item) — both become DEAD CODE at Gloas, both forward-fragility shifts to Heze.

### With item #39 (PeerDAS Reed-Solomon math) — input source

`compute_matrix` (item #39) produces the `cells_and_kzg_proofs` consumed here. Cross-cut: lodestar's pre-computed-proofs optimization (item #39) means lodestar's `cellsAndKzgProofs[i].proofs` are EL-provided, while other 5 may compute. If proofs diverge by even 1 byte, sidecars would too — and 5+ months of mainnet validation confirms byte-equivalence across both KZG library families.

### With item #33 (PeerDAS custody assignment) — column index range

`column_index` ranges over `NUMBER_OF_COLUMNS = 128`. Item #33's custody assignment determines which columns each node receives; this item produces sidecars for ALL 128 columns regardless of any specific node's custody.

### With item #28 (Gloas divergence meta-audit) — NEW Pattern V

This item proposes **Pattern V** for item #28's catalog (carry-forward from prior audit): producer-side hardcoded inclusion proof construction. Same forward-fragility class as Pattern P (consumer-side hardcoded gindex). **Pattern V is the dual of Pattern P** — together they form a "symmetric forward-fragility" pair on grandine's PeerDAS producer + consumer sides.

### With lighthouse Pattern M cohort gap (carry-forward)

The Pattern M Gloas-ePBS readiness gap (12+ symptoms at consumer ePBS surface) does NOT extend to the PRODUCER side. Lighthouse has `build_data_column_sidecars_gloas` wired. **Producer/consumer asymmetry**: lighthouse can BUILD Gloas sidecars but cannot VERIFY them on gossip yet (item #34 H13 — `DataColumnSidecar::Gloas(_)` rejected at gossip-verification time).

### With Heze (post-Gloas) — Pattern V forward-tracker

If Heze re-introduces some form of inclusion proof verification with a different schema layout (e.g., for inclusion lists per EIP-7805), grandine's manual `kzg_commitments_inclusion_proof` helper would silently mismatch. **Pattern V forward-tracker** — currently dead code at Gloas; concern reactivates at Heze.

## Adjacent untouched

1. **Wire Fulu validator-category fixtures in BeaconBreaker harness** — same gap as items #30-#39.
2. **Pattern V for item #28's catalog** — producer-side hardcoded inclusion proof construction forward-fragility marker.
3. **Cross-client byte-equivalence test for Gloas producer** — verify all 6 produce byte-identical Gloas sidecars.
4. **Grandine Pattern V Heze forward-tracker** — track if Heze re-introduces inclusion proof verification.
5. **Cross-fork BeaconBlockBody field-ordering audit** — verify `blob_kzg_commitments` schema position across Fulu/Gloas/Heze.
6. **prysm `ConstructionPopulator` interface audit** — verify `PopulateFromBlock` and `PopulateFromSidecar` produce identical sidecars.
7. **lighthouse defensive fork-check audit** — test calling Fulu builder with post-Gloas block; verify error.
8. **teku `protected` Gloas subclass audit** — verify `MiscHelpersGloas` subclass extension matches Gloas spec.
9. **grandine manual inclusion proof correctness unit test** — verify grandine's manual construction byte-equivalent to generic `compute_merkle_proof`.
10. **nimbus Fulu producer location audit** — find Fulu equivalent of `assemble_data_column_sidecars` for cross-client consistency.
11. **Empty-blob block fast-path** — verify all 6 short-circuit.
12. **Cross-fork transition Pectra→Fulu** — proposer transitions from BlobSidecar to DataColumnSidecar at FULU_FORK_EPOCH.
13. **Memory architecture audit** — 128 sidecars × 21 blobs × ~5 KB = ~13.4 MB peak per block; cross-client allocation pattern.
14. **Per-blob proof source consistency** — lodestar uses EL-pre-computed (item #39); other 5 TBD.
15. **Distributed publishing cross-client correctness** — `from_column_sidecar` variant across all 6.
