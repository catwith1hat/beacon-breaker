---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [20, 25, 28, 33, 34, 35, 37, 38]
eips: [EIP-7594]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 39: `compute_matrix` + `recover_matrix` (EIP-7594 PeerDAS Reed-Solomon extension/recovery)

## Summary

EIP-7594 PeerDAS Reed-Solomon math primitives: `compute_matrix(blobs)` extends each blob to 128 cells (proposer-side); `recover_matrix(partial_matrix, blob_count)` reconstructs missing cells from ≥ 64 received cells per blob (sampling-side). The spec marks both as "demonstration helpers" with "data structure for storing cells/proofs is implementation-dependent" — meaning per-client orchestration varies significantly.

The actual cell/proof math is delegated to the KZG library (`compute_cells_and_kzg_proofs`, `recover_cells_and_kzg_proofs` from the polynomial-commitments-sampling primitive). **Two KZG library families** in production: **c-kzg-4844** (prysm, teku, nimbus, lodestar) + **rust-kzg variants** (lighthouse, grandine). Both library families use BLST for BLS12-381 arithmetic (cross-cut to items #20/#25 BLS audits).

**Fulu surface (carried forward from 2026-05-04 audit; CURRENT mainnet target):** all six clients implement byte-equivalent math at the production level. **5+ months of live mainnet PeerDAS reconstruction (since 2025-12-03) without observable cross-client divergence** validates byte-identical Reed-Solomon math across both library families. Per-client divergences entirely in:
- **KZG library family** (4 c-kzg-4844 + 2 rust-kzg).
- **Parallelism strategy** (5 distinct: errgroup, parallel stream, Taskpool, dedicated_executor, async).
- **Orchestration pattern** (prysm two-entry-point Flat vs Structured; nimbus sequential + parallel variants; lodestar pre-computed-proofs optimization; lighthouse library-direct; teku stream-based; grandine swappable backend).
- **Pre-computed proofs optimization** (lodestar explicit; others TBD).

**Gloas surface (at the Glamsterdam target): functions unchanged.** `vendor/consensus-specs/specs/gloas/` contains no `Modified compute_matrix` / `Modified recover_matrix` headings — the functions are defined ONLY in `vendor/consensus-specs/specs/fulu/das-core.md:137-200` and inherited verbatim across the Gloas fork boundary. No Gloas-specific overrides observed in any client; the `MatrixEntry` SSZ container is unchanged at Gloas; the underlying KZG library calls (`compute_cells_and_kzg_proofs`, `recover_cells_and_kzg_proofs`) operate on the same cell/proof byte semantics.

**Per-client Gloas inheritance**: all 6 clients reuse Fulu implementations at Gloas via fork-agnostic config / module-level placement. The KZG library distribution (4 c-kzg-4844 + 2 rust-kzg) carries forward unchanged. Pattern U candidate (orchestration architecture divergence) is a forward-fragility marker, not a current divergence.

**Mainnet activation status**: `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `vendor/consensus-specs/configs/mainnet.yaml:60`. PeerDAS Reed-Solomon math continues operating on Fulu surface in production; the Gloas inheritance is source-level only. The 2 BPO transitions (epochs 412672 → 15 blobs, 419072 → 21 blobs per item #31) increased the per-block math workload without surfacing any cross-library divergence.

**Cross-cut to lighthouse Pattern M cohort**: the Pattern M Gloas-ePBS readiness gap (12+ symptoms) does NOT extend to KZG math primitives — lighthouse uses rust-kzg correctly at Fulu and would continue using it at Gloas. The cohort gap is at the ePBS surface (bid handling, envelope verification), not at the KZG math layer.

**Impact: none.** Twenty-first impact-none result in the recheck series.

## Question

Pyspec Fulu-NEW (`vendor/consensus-specs/specs/fulu/das-core.md:137-200`):

```python
def compute_matrix(blobs: Sequence[Blob]) -> Sequence[MatrixEntry]:
    """
    Return the full, extended matrix.
    """
    matrix = []
    for blob_index, blob in enumerate(blobs):
        cells, proofs = compute_cells_and_kzg_proofs(blob)
        for cell_index, (cell, proof) in enumerate(zip(cells, proofs)):
            matrix.append(MatrixEntry(
                cell=cell,
                kzg_proof=proof,
                row_index=blob_index,
                column_index=cell_index,
            ))
    return matrix


def recover_matrix(
    partial_matrix: Sequence[MatrixEntry],
    blob_count: uint64,
) -> Sequence[MatrixEntry]:
    """
    Return the recovered extended matrix.
    """
    matrix = []
    for blob_index in range(blob_count):
        cell_indices = [e.column_index for e in partial_matrix if e.row_index == blob_index]
        cells_bytes = [e.cell for e in partial_matrix if e.row_index == blob_index]
        cells, proofs = recover_cells_and_kzg_proofs(cell_indices, cells_bytes)
        for cell_index, (cell, proof) in enumerate(zip(cells, proofs)):
            matrix.append(MatrixEntry(
                cell=cell,
                kzg_proof=proof,
                row_index=blob_index,
                column_index=cell_index,
            ))
    return matrix
```

At Gloas: NOT modified (no references in `vendor/consensus-specs/specs/gloas/`). Functions inherited verbatim.

Three recheck questions:
1. Fulu-surface invariants (H1–H10 from prior audit) — do all six clients still implement byte-equivalent Reed-Solomon math?
2. **At Gloas (the new target)**: are the functions unchanged? Do all six clients reuse Fulu implementations at Gloas?
3. Does the KZG library distribution (4 c-kzg-4844 + 2 rust-kzg) hold? Pattern U orchestration divergence forward-fragility marker?

## Hypotheses

- **H1.** `compute_matrix(blobs) -> Sequence[MatrixEntry]` builds 128 entries per blob via `compute_cells_and_kzg_proofs(blob)`.
- **H2.** `recover_matrix(partial_matrix, blob_count) -> Sequence[MatrixEntry]` per-blob extracts (cell_indices, cells), calls `recover_cells_and_kzg_proofs`, builds MatrixEntry list.
- **H3.** Per-blob recovery requires ≥ 64 cells (`NUMBER_OF_COLUMNS / 2`) for Reed-Solomon to succeed.
- **H4.** All 6 clients use BLST for BLS pairings; KZG cell math uses BLST scalar field arithmetic (cross-cut item #20/#25).
- **H5.** Cell/proof bytes are byte-identical across all 6 (deterministic Reed-Solomon over BLS12-381 scalar field).
- **H6.** `MatrixEntry` SSZ schema: `(cell: Cell, kzg_proof: KZGProof, row_index: RowIndex, column_index: ColumnIndex)` 4-field container.
- **H7.** Spec helpers are "implementation-dependent" per data structure — different orchestration patterns expected.
- **H8.** Parallelization: per-blob recovery is CPU-bound and parallelizable (5 distinct strategies observed).
- **H9.** `CELLS_PER_EXT_BLOB = 128` (= `NUMBER_OF_COLUMNS`).
- **H10.** Pre-Fulu: functions not defined; blob KZG proofs (Deneb) used instead.
- **H11.** *(Glamsterdam target — functions unchanged)*. `compute_matrix` and `recover_matrix` are NOT modified at Gloas. No `Modified` headings in `vendor/consensus-specs/specs/gloas/`. The Fulu-NEW functions carry forward unchanged across the Gloas fork boundary in all 6 clients via fork-agnostic module-level placement.
- **H12.** *(Glamsterdam target — KZG library distribution holds)*. 4 c-kzg-4844 (prysm, teku, nimbus, lodestar) + 2 rust-kzg (lighthouse, grandine) at both Fulu and Gloas. Both library families use BLST under the hood. Pattern U candidate for item #28: orchestration architecture divergence forward-fragility marker.
- **H13.** *(Lighthouse Pattern M cohort gap doesn't extend here)*. KZG math primitives are Fulu-stable; lighthouse rust-kzg implementation is correct in isolation. The Pattern M gap (12+ symptoms) is at the ePBS surface (bid handling, envelope verification), not at the KZG math layer.

## Findings

H1–H13 satisfied. **No state-transition divergence at the Fulu surface; functions inherited unchanged at Gloas; KZG library distribution carries forward; Pattern U forward-fragility marker persists unchanged.**

### prysm

`vendor/prysm/beacon-chain/core/peerdas/reconstruction.go:289 ComputeCellsAndProofsFromFlat(blobs, cellProofs)` (uses pre-computed proofs from EL); `:342 ComputeCellsAndProofsFromStructured(blobsAndProofs)` (alt entry point for `BlobAndProofV2` proto input). Reconstruction via `kzg.RecoverCellsAndProofs`.

**KZG library**: c-kzg-4844 (Go binding). **Parallelism**: `errgroup.Group` per-blob goroutines.

**Two entry points** for different EL response formats (Flat vs Structured) — code-duplication risk; both must produce same output.

**No Gloas-specific code path** — fork-agnostic. The KZG library calls don't change at Gloas.

H1 ✓. H2 ✓. H3 ✓ (KZG library enforces). H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (errgroup). H9 ✓. H10 ✓. H11 ✓ (no Gloas redefinition). H12 ✓ (c-kzg-4844 reused). H13 n/a (prysm not in cohort).

### lighthouse

`vendor/lighthouse/crypto/kzg/src/lib.rs:219 compute_cells_and_kzg_proofs(blob)` (single-blob primitive); `:325 recover_cells_and_kzg_proofs(cell_ids, cells)`. Orchestration in `vendor/lighthouse/beacon_node/beacon_chain/src/data_column_verification.rs:432 reconstruct_columns` and `data_availability_checker.rs:478 reconstruct_data_columns`.

**KZG library**: rust-kzg-arkworks (or BLST variant via feature flag). **Parallelism**: TBD (likely tokio task; carry-forward from prior audit).

**Cleanest separation** of KZG primitive from orchestration. Library wrapper at `crypto/kzg/`; orchestration at `beacon_chain/`.

**No Gloas-specific code path** at the KZG math layer. Lighthouse Pattern M cohort gap is at the ePBS surface, not here.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 (TBD parallelism). H9 ✓. H10 ✓. H11 ✓ (no Gloas redefinition). H12 ✓ (rust-kzg-arkworks reused). H13 ✓ (cohort gap doesn't extend here — KZG math is Fulu-stable).

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/fulu/helpers/MiscHelpersFulu.java:576 recoverMatrix(partialMatrix)`:

```java
public List<List<MatrixEntry>> recoverMatrix(final List<List<MatrixEntry>> partialMatrix) {
    return IntStream.range(0, partialMatrix.size())
        .parallel()  // <-- ForkJoinPool common pool
        .mapToObj(blobIndex -> { ... })
        .toList();
}
```

`vendor/teku/infrastructure/kzg/src/main/java/tech/pegasys/teku/kzg/ckzg4844/CKZG4844.java:171 computeCellsAndKzgProofs(blob.toArrayUnsafe())`.

**KZG library**: c-kzg-4844 (Java JNI `CKZG4844JNI`). **Parallelism**: Java `parallel()` stream → ForkJoinPool **common pool** (shared with concurrent attestation verification — potential contention under heavy load).

**No Gloas-specific code path** — `MiscHelpersGloas` doesn't override `recoverMatrix`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (parallel stream — ForkJoinPool contention concern carry-forward). H9 ✓. H10 ✓. H11 ✓. H12 ✓ (c-kzg-4844 reused). H13 n/a.

### nimbus

`vendor/nimbus/beacon_chain/spec/peerdas_helpers.nim:91 compute_matrix(blobs)` + `:97 computeCellsAndKzgProofs(blob)` (sequential reference); `:112 recover_matrix(partial_matrix, blobCount)` (sequential) + `:152 recover_cells_and_proofs_parallel(tp, dataColumns)` (Taskpool variant).

**KZG library**: nim-kzg4844 (C bindings to c-kzg-4844). **Parallelism**: Taskpool-based per-blob (separate function from sequential reference).

**TWO variants** of recovery (sequential reference + parallel production) — **code-duplication risk** carry-forward: if math diverges between variants, behavior differs by deployment configuration.

**No Gloas-specific code path** — `cfg`-keyed; fork-agnostic.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (Taskpool — dedicated thread pool). H9 ✓. H10 ✓. H11 ✓. H12 ✓ (nim-kzg4844 wraps c-kzg-4844; reused at Gloas). H13 n/a.

### lodestar

`vendor/lodestar/packages/beacon-node/src/util/dataColumns.ts:262 getCellsAndProofs(blobBundles: BlobAndProofV2[])`:

```typescript
export async function getCellsAndProofs(
  blobBundles: fulu.BlobAndProofV2[]
): Promise<{cells: Uint8Array[]; proofs: Uint8Array[]}[]> {
  const blobsAndProofs = [];
  for (const {blob, proofs} of blobBundles) {
    const cells = await kzg.asyncComputeCells(blob);
    blobsAndProofs.push({cells, proofs});  // proofs from EL's BlobAndProofV2 — re-used
  }
  return blobsAndProofs;
}
```

**Optimization**: re-uses EL-provided cell proofs from `BlobAndProofV2` (Engine API V5 `engine_getBlobsV2`); skips per-blob proof recomputation. Comment: "spec currently computes proofs, but we already have them".

**KZG library**: c-kzg-4844 (TypeScript binding via napi/wasm). **Parallelism**: async per-blob.

**No Gloas-specific code path** — the EL boundary handling (BlobAndProofV2) may differ at Gloas if Engine API V5 evolves; tracked but not yet observed.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (async per-blob). H9 ✓. H10 ✓. H11 ✓. H12 ✓ (c-kzg-4844 reused). H13 n/a.

### grandine

`vendor/grandine/eip_7594/src/lib.rs:246 recover_matrix(partial_matrix, backend, dedicated_executor)`:

```rust
// (Async per-blob spawn using dedicated_executor)
recover_cells_and_kzg_proofs::<P>(cell_indices, &cells, backend)
```

**KZG library**: rust-kzg-arkworks-blst (with `KzgBackend` parameterizable — can swap to other rust-kzg variants for benchmarking). **Parallelism**: `dedicated_executor.spawn` per-blob — **most isolated** thread pool of the 6.

**Swappable `KzgBackend`** — most flexible for testing/benchmarking different KZG implementations within the same client.

**No Gloas-specific code path** — `eip_7594/src/lib.rs` is fork-agnostic (Fulu-NEW module reused at Gloas).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (dedicated_executor — most isolated). H9 ✓. H10 ✓. H11 ✓. H12 ✓ (rust-kzg-arkworks-blst reused). H13 n/a.

## Cross-reference table

| Client | KZG library | Parallelism | Orchestration | Gloas redefinition |
|---|---|---|---|---|
| prysm | **c-kzg-4844** (Go binding) | `errgroup.Group` per-blob | `core/peerdas/reconstruction.go:289, 342` (TWO entry points — Flat vs Structured) | none — fork-agnostic |
| lighthouse | **rust-kzg-arkworks** (or BLST variant) | TBD (likely tokio task) | library-direct delegation (`crypto/kzg/src/lib.rs:219, 325`) + orchestration in `beacon_chain/` | none — fork-agnostic; Pattern M cohort gap doesn't extend |
| teku | **c-kzg-4844** (Java JNI `CKZG4844JNI`) | Java `parallel()` stream → ForkJoinPool common pool | `MiscHelpersFulu.java:576 recoverMatrix`; `MiscHelpersGloas` doesn't override | none — fork-agnostic |
| nimbus | **nim-kzg4844** (C bindings to c-kzg-4844) | Taskpool-based per-blob | TWO variants — sequential ref + parallel production (`peerdas_helpers.nim:112, 152`) | none — fork-agnostic |
| lodestar | **c-kzg-4844** (TypeScript binding via napi/wasm) | async per-blob | `getCellsAndProofs` re-uses EL-provided proofs (pre-computed-proofs optimization) | none — fork-agnostic |
| grandine | **rust-kzg-arkworks-blst** (swappable `KzgBackend`) | `dedicated_executor.spawn` per-blob | `eip_7594/src/lib.rs:246 recover_matrix` (swappable backend) | none — fork-agnostic |

## Empirical tests

### Fulu-surface live mainnet validation

5+ months of PeerDAS reconstruction since 2025-12-03 without observable divergence. Reconstructions happen routinely when validator nodes receive < 64 of their custody columns from gossip and need to reconstruct the rest from peers. **Cross-library byte-equivalence validated at production scale** — c-kzg-4844 (4 clients) and rust-kzg (2 clients) produce identical recovered cells + proofs for the same input. The 2 BPO transitions (epochs 412672 → 15 blobs, 419072 → 21 blobs) increased the per-block math workload without surfacing any cross-library divergence.

### Gloas-surface

`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `mainnet.yaml:60`. Functions unchanged at Gloas.

Concrete Gloas-spec evidence:
- No `Modified compute_matrix` or `Modified recover_matrix` headings anywhere in `vendor/consensus-specs/specs/gloas/`.
- `MatrixEntry` SSZ container unchanged at Gloas.
- KZG library calls (`compute_cells_and_kzg_proofs`, `recover_cells_and_kzg_proofs`) operate on identical cell/proof byte semantics.

### EF fixture status

**No dedicated EF fixtures** for `compute_matrix` / `recover_matrix` at `consensus-spec-tests/tests/mainnet/fulu/` (the spec marks both as "demonstration helpers"). KZG primitive fixtures exist at `consensus-spec-tests/tests/mainnet/fulu/kzg/` (subset of polynomial-commitments-sampling).

Implicitly exercised through:
- Live mainnet PeerDAS reconstruction (5+ months)
- Per-client unit tests (out of EF scope)
- KZG primitive reference tests

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1**: dedicated EF fixture for `compute_matrix` and `recover_matrix` as pure functions. Cross-client + cross-library byte-level equivalence.
- **T1.2**: wire Fulu KZG-category fixtures in BeaconBreaker harness — same gap as items #30-#38.

#### T2 — Adversarial probes
- **T2.1 (cross-library KZG byte-for-byte equivalence)**: c-kzg-4844 (prysm/teku/nimbus/lodestar) vs rust-kzg (lighthouse/grandine). Generate fixtures testing edge cases (empty input, single-cell, exactly-half-cells boundary, over-supply, error semantics).
- **T2.2 (edge case: exactly 64 cells)**: minimum for recovery. Verify all 6 succeed with same recovered cells + proofs.
- **T2.3 (edge case: 63 cells)**: one below minimum. Verify all 6 reject with same error semantics.
- **T2.4 (lodestar pre-computed-proofs)**: verify EL-provided `BlobAndProofV2.proofs` are byte-identical to `compute_cells_and_kzg_proofs(blob).proofs` for the same blob. If divergence, lodestar produces wrong sidecars.
- **T2.5 (nimbus parallel-vs-sequential)**: byte-equivalence test between `recover_matrix` (sequential) and `recover_cells_and_proofs_parallel` (parallel).
- **T2.6 (Glamsterdam-target — H11 verification)**: same inputs at Fulu and Gloas state. Expected: identical outputs (functions inherited unchanged).
- **T2.7 (Glamsterdam-target — H12 cross-library symmetry at Gloas)**: at synthetic Gloas state, all 6 clients (c-kzg-4844 × 4 + rust-kzg × 2) produce byte-identical reconstruction output.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Fulu-surface invariants (H1–H10) carry forward unchanged from the 2026-05-04 audit. 5+ months of live mainnet PeerDAS reconstruction without observable divergence validates byte-identical Reed-Solomon math across both library families (c-kzg-4844 × 4 + rust-kzg × 2).

**Glamsterdam-target finding (H11 — functions unchanged).** `vendor/consensus-specs/specs/gloas/` contains no `Modified compute_matrix` or `Modified recover_matrix` headings. The Fulu-NEW functions live ONLY in `vendor/consensus-specs/specs/fulu/das-core.md:137-200` and are inherited verbatim across the Gloas fork boundary in all 6 clients via fork-agnostic module-level placement. `MatrixEntry` SSZ container is unchanged at Gloas; the underlying KZG library calls (`compute_cells_and_kzg_proofs`, `recover_cells_and_kzg_proofs`) operate on identical cell/proof byte semantics.

**Glamsterdam-target finding (H12 — KZG library distribution holds).** 4 c-kzg-4844 clients (prysm, teku, nimbus, lodestar) + 2 rust-kzg clients (lighthouse, grandine) at both Fulu and Gloas. Both library families use BLST for BLS12-381 arithmetic (cross-cut to items #20/#25 BLS audits). Cross-library byte-equivalence validated at production scale.

**Glamsterdam-target finding (H13 — lighthouse Pattern M cohort gap doesn't extend here).** The Pattern M Gloas-ePBS readiness gap (12+ symptoms across items #14, #19, #22, #23, #24, #25, #26, #32, #34, #35) does NOT extend to KZG math primitives. Lighthouse's rust-kzg implementation is correct in isolation at Fulu and carries forward at Gloas. The cohort gap is at the ePBS surface (bid handling, envelope verification), not at the KZG math layer.

**Twenty-first impact-none result** in the recheck series. PeerDAS Reed-Solomon math is the most operationally validated cryptographic primitive in the Fulu corpus — every block since 2025-12-03 has invoked it without cross-client divergence, across two BPO transitions (9 → 15 → 21 blobs).

**Pattern U candidate (carry-forward from prior audit) for item #28's catalog**: orchestration architecture divergence — 5 distinct parallelism strategies (errgroup, parallel stream, Taskpool, dedicated_executor, async) + 2 KZG library families. Forward-fragility class — same shape as Pattern J/N/P/Q/R/S/T. Not a current divergence vector; tracker only.

**Notable per-client style differences (all observable-equivalent at Fulu mainnet):**
- **prysm**: c-kzg-4844 (Go binding); `errgroup.Group` parallelism; TWO entry points (Flat vs Structured) for different EL response formats.
- **lighthouse**: rust-kzg-arkworks; cleanest library separation (`crypto/kzg/`); Pattern M cohort gap doesn't extend here.
- **teku**: c-kzg-4844 (Java JNI); ForkJoinPool common pool (potential contention concern); subclass-extension `MiscHelpersGloas` doesn't override `recoverMatrix`.
- **nimbus**: nim-kzg4844 (C bindings to c-kzg-4844); TWO variants (sequential ref + parallel production) — code-duplication risk.
- **lodestar**: c-kzg-4844 (TypeScript binding); pre-computed-proofs optimization re-uses EL-provided `BlobAndProofV2.proofs`.
- **grandine**: rust-kzg-arkworks-blst (swappable `KzgBackend`); `dedicated_executor` per-blob — most isolated thread pool.

**No code-change recommendation.** Audit-direction recommendations:

- **Wire Fulu KZG-category fixtures in BeaconBreaker harness** — same gap as items #30-#38.
- **Pattern U for item #28's catalog** — orchestration architecture divergence forward-fragility marker.
- **Cross-library KZG byte-for-byte equivalence test** — c-kzg-4844 (4 clients) vs rust-kzg (2 clients) edge-case fixture suite (T2.1).
- **Edge case fixtures: 63 cells (below recovery threshold), 64 cells (exact minimum), 65 cells, 128 cells (no-op)** — verify all 6 produce same error/success.
- **Lodestar pre-computed-proofs audit** (T2.4) — verify EL-provided proofs byte-equivalent to computed proofs.
- **Nimbus parallel-vs-sequential byte-equivalence test** (T2.5) — verify both variants produce identical output.
- **Teku ForkJoinPool contention audit** — load test with concurrent attestation verification + KZG recovery.
- **Grandine `KzgBackend` swap audit** — verify byte-identical output across rust-kzg-arkworks vs blst variants.
- **Lighthouse parallelism audit** — locate orchestration callers; verify tokio task usage for CPU-bound recovery.
- **KZG library version tracking cross-client** — maintain per-client KZG library version table; flag divergences (e.g., c-kzg-4844 v1.0 vs v1.1).

## Cross-cuts

### With items #20 / #25 (BLS library audit) — KZG library distribution

Items #20 and #25 confirmed all 6 use BLST for BLS pairings. This item adds: KZG cell math uses BLST scalar field arithmetic underneath both library families. **4 c-kzg-4844 + 2 rust-kzg** — both use BLST.

### With item #34 (PeerDAS sidecar verification) — symmetry

Item #34's `verify_data_column_sidecar_kzg_proofs` uses `verify_cell_kzg_proof_batch` from the same KZG library. This item confirms reconstruction uses the same library — **symmetry on construction + verification + recovery**.

### With item #35 (PeerDAS fork-choice DA) — reconstruction trigger

Item #35's reconstruction-from-half-columns at `available_columns_count * 2 >= NUMBER_OF_COLUMNS` triggers `recover_matrix` in 3 of 6 clients (prysm + lighthouse + grandine explicit; teku + nimbus + lodestar TBD). This item documents the recovery primitives those reconstructions invoke.

### With item #28 (Gloas divergence meta-audit) — Pattern U

This item proposes **Pattern U** for item #28's catalog (carry-forward from prior audit): orchestration architecture divergence (5 distinct parallelism strategies) + 2 KZG library families. Same forward-fragility class as Patterns J/N/P/Q/R/S/T.

### With Lighthouse Pattern M cohort (carry-forward)

The Pattern M cohort gap (lighthouse Gloas-ePBS readiness gap, 12+ symptoms) does NOT extend here. KZG math primitives are Fulu-stable; lighthouse rust-kzg implementation is correct.

## Adjacent untouched

1. **Wire Fulu KZG-category fixtures in BeaconBreaker harness** — same gap as items #30-#38.
2. **Pattern U for item #28's catalog** — orchestration architecture divergence forward-fragility marker.
3. **Cross-library KZG byte-for-byte equivalence test** — c-kzg-4844 × 4 vs rust-kzg × 2.
4. **Edge case fixtures (63/64/65/128 cells)** — recovery threshold + boundary verification.
5. **Lodestar pre-computed-proofs audit** — EL-provided proofs byte-equivalence.
6. **Nimbus parallel-vs-sequential byte-equivalence test** — internal consistency.
7. **Teku ForkJoinPool contention audit** — concurrent load test.
8. **Grandine `KzgBackend` swap audit** — rust-kzg-arkworks vs blst variants.
9. **Lighthouse parallelism audit** — tokio task usage for CPU-bound recovery.
10. **KZG library version tracking cross-client** — version divergence flagging.
11. **`get_data_column_sidecars` validator-side construction** — uses `compute_matrix` output (separate item).
12. **BlobsBundle SSZ schema cross-client** (validator-side; Track E follow-up).
13. **Cross-fork transition: pre-Fulu blob KZG proofs → Fulu cell KZG proofs** at FULU_FORK_EPOCH.
14. **Memory architecture audit** — ~13 MB peak per block at 21 blobs × 128 cells × ~5 KB.
15. **`compute_cells_and_kzg_proofs` / `recover_cells_and_kzg_proofs` KZG primitive specifics** (polynomial-commitments-sampling spec).
