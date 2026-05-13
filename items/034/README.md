---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [28, 31, 32, 33]
eips: [EIP-7594, EIP-7732]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 34: `verify_data_column_sidecar` + `verify_data_column_sidecar_kzg_proofs` + `verify_data_column_sidecar_inclusion_proof` (EIP-7594 PeerDAS sidecar validation pipeline)

## Summary

EIP-7594 PeerDAS sidecar validation pipeline — three functions that gate every PeerDAS gossip message: structural validation (`verify_data_column_sidecar`), KZG cell-proof verification (`verify_data_column_sidecar_kzg_proofs`), and Merkle inclusion proof against block body (`verify_data_column_sidecar_inclusion_proof`). Sidecars passing all three checks enter the local data store and are served to peers.

**Fulu surface (carried forward from 2026-05-04 audit; CURRENT mainnet target):** all six clients implement the sidecar validation pipeline byte-for-byte equivalently. Live mainnet PeerDAS gossip has been operational since Fulu activation (2025-12-03) without breaking the gossip mesh — validates that all 6 clients accept/reject the same sidecars.

Per-client divergences entirely in: function signature (grandine takes external `kzg_commitments` parameter — prescient Gloas forward-compat); multi-fork-definition (nimbus has separate Fulu/Gloas overloads — Pattern I); batch KZG verification (prysm + teku batch across multiple sidecars; spec verifies one-at-a-time); gindex resolution (5 of 6 dynamically resolve; **grandine hardcodes `index_at_commitment_depth = 11`** — Pattern P candidate); encapsulation (lighthouse type method; teku factored helper; lodestar bundles into gossip orchestration; others standalone).

**Gloas surface (at the Glamsterdam target): MAJOR restructure.** `vendor/consensus-specs/specs/gloas/p2p-interface.md:57-184` documents the Gloas changes:

1. **`DataColumnSidecar` Modified** (`:57-81`) — **3 fields REMOVED**: `signed_block_header`, `kzg_commitments`, `kzg_commitments_inclusion_proof`. **2 fields ADDED**: `slot: Slot`, `beacon_block_root: Root`. The KZG commitments are now obtained externally from `block.body.signed_execution_payload_bid.message.blob_kzg_commitments` per `:62-64`.
2. **`verify_data_column_sidecar` Modified** (`:156-184`) — takes external `kzg_commitments` parameter. Spec-modified body removes the Fulu blob-limit check (now gated upstream at `process_execution_payload_bid` per item #32 / item #31).
3. **`verify_data_column_sidecar_kzg_proofs` Modified** (`:132-153`) — takes external `kzg_commitments` parameter (sourced from the bid).
4. **`verify_data_column_sidecar_inclusion_proof` REMOVED at Gloas** — per the spec note at `:60-62`: "header and inclusion proof verifications are no longer required in Gloas." The bid signature gates the commitments instead.

**Per-client Gloas wiring (5-vs-1 split):**
- **prysm**: Gloas variant wired; `TestVerifyDataColumnSidecarInclusionProof_SkipsGloas` (`vendor/prysm/beacon-chain/core/peerdas/p2p_interface_test.go:218`) confirms inclusion proof is SKIPPED at Gloas matching spec.
- **lighthouse**: **MISSING.** `vendor/lighthouse/beacon_node/beacon_chain/src/data_column_verification.rs:243-244`:
  ```rust
  // TODO(gloas) support gloas data column variant
  DataColumnSidecar::Gloas(_) => Err(GossipDataColumnError::InvalidVariant),
  ```
  Explicit `TODO(gloas)` marker. Lighthouse REJECTS the Gloas variant at gossip-verification time. **Pattern M cohort gap extends here.**
- **teku**: `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/util/DataColumnSidecarUtilGloas.java` + `helpers/MiscHelpersGloas.java:269 verifyDataColumnSidecarWithCommitments` — full Gloas implementation matching spec.
- **nimbus**: separate Fulu (`peerdas_helpers.nim:447`) and Gloas (`:473`) overloads of `verify_data_column_sidecar`; Fulu-only `verify_data_column_sidecar_inclusion_proof` (`:496`); Fulu (`:530`) + Gloas (`:550`) overloads of `verify_data_column_sidecar_kzg_proofs`. Multi-fork-definition Pattern I.
- **lodestar**: separate `verifyFuluDataColumnSidecar` (`vendor/lodestar/packages/beacon-node/src/chain/validation/dataColumnSidecar.ts:276`) + `verifyGloasDataColumnSidecar` (`:323`); inclusion proof Fulu-only (`:380`).
- **grandine**: type-polymorphic via `FuluDataColumnSidecar` / `GloasDataColumnSidecar` containers (`vendor/grandine/eip_7594/src/lib.rs:27-30`). `verify_data_column_sidecar` (`:149`) already takes external `kzg_commitments` parameter (prescient design). `verify_sidecar_inclusion_proof` (`:217`) restricted to `FuluDataColumnSidecar` only — dead code at Gloas.

**Mainnet activation status**: `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `vendor/consensus-specs/configs/mainnet.yaml:60`. PeerDAS continues operating on Fulu surface in production; the Gloas restructure is source-level only. Lighthouse cohort gap is not yet a mainnet-reachable divergence — pending Gloas activation.

**Cross-cuts to item #28 catalogue:**
- **Pattern M (lighthouse Gloas-ePBS cohort)**: NEW symptoms added (3 more — `verify_data_column_sidecar` for Gloas variant, `verify_data_column_sidecar_kzg_proofs` for Gloas variant, plus removed-but-still-skipped inclusion proof). **Cohort gap symptom count grows to 11+** (items #14, #19, #22, #23, #24, #25, #26 — 7 prior + item #32's 3 (process_execution_payload_bid + apply_parent_execution_payload + verify_execution_payload_envelope) + this item's 3 = 13 symptoms with overlap). Single upstream fix (lighthouse EIP-7732 ePBS implementation) closes all.
- **Pattern P (grandine hardcoded gindex `11`)**: still present at Fulu surface; dead code at Gloas (inclusion proof removed). Forward-fragility class for Heze where teku has full EIP-7805 implementation per item #29.

**Impact: none** at this item's Fulu surface (the current mainnet target). Sixteenth impact-none result in the recheck series for the Fulu surface. The Gloas surface restructure is source-level only at this time; lighthouse cohort gap is a tracked future divergence (Pattern M).

## Question

Pyspec Fulu-NEW (`vendor/consensus-specs/specs/fulu/p2p-interface.md:114-184`):

```python
def verify_data_column_sidecar(sidecar: DataColumnSidecar) -> bool:
    # The sidecar index must be within the valid range
    if sidecar.index >= NUMBER_OF_COLUMNS:
        return False
    # A sidecar for zero blobs is invalid
    if len(sidecar.kzg_commitments) == 0:
        return False
    # Validate against the BPO blob limit (cross-cuts item #31)
    epoch = compute_epoch_at_slot(sidecar.signed_block_header.message.slot)
    if len(sidecar.kzg_commitments) > get_blob_parameters(epoch).max_blobs_per_block:
        return False
    # Column / commitments / proofs length consistency
    if len(sidecar.column) != len(sidecar.kzg_commitments):
        return False
    if len(sidecar.column) != len(sidecar.kzg_proofs):
        return False
    return True

def verify_data_column_sidecar_kzg_proofs(sidecar: DataColumnSidecar) -> bool:
    cell_indices = [CellIndex(sidecar.index)] * len(sidecar.column)
    return verify_cell_kzg_proof_batch(
        commitments_bytes=sidecar.kzg_commitments,
        cell_indices=cell_indices,
        cells=sidecar.column,
        proofs_bytes=sidecar.kzg_proofs,
    )

def verify_data_column_sidecar_inclusion_proof(sidecar: DataColumnSidecar) -> bool:
    return is_valid_merkle_branch(
        leaf=hash_tree_root(sidecar.kzg_commitments),
        branch=sidecar.kzg_commitments_inclusion_proof,
        depth=KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH,
        index=get_subtree_index(get_generalized_index(BeaconBlockBody, "blob_kzg_commitments")),
        root=sidecar.signed_block_header.message.body_root,
    )
```

Pyspec Gloas-Modified (`vendor/consensus-specs/specs/gloas/p2p-interface.md:132-184`):

```python
def verify_data_column_sidecar_kzg_proofs(
    sidecar: DataColumnSidecar,
    # [New in Gloas:EIP7732]
    kzg_commitments: List[KZGCommitment, MAX_BLOB_COMMITMENTS_PER_BLOCK],
) -> bool:
    cell_indices = [CellIndex(sidecar.index)] * len(sidecar.column)
    return verify_cell_kzg_proof_batch(
        commitments_bytes=kzg_commitments,
        cell_indices=cell_indices,
        cells=sidecar.column,
        proofs_bytes=sidecar.kzg_proofs,
    )

def verify_data_column_sidecar(
    sidecar: DataColumnSidecar,
    # [New in Gloas:EIP7732]
    kzg_commitments: List[KZGCommitment, MAX_BLOB_COMMITMENTS_PER_BLOCK],
) -> bool:
    if sidecar.index >= NUMBER_OF_COLUMNS:
        return False
    if len(sidecar.column) == 0:
        return False
    # Note: blob-limit check REMOVED at Gloas (gated upstream at process_execution_payload_bid).
    if len(sidecar.column) != len(kzg_commitments) or len(sidecar.column) != len(sidecar.kzg_proofs):
        return False
    return True
```

`verify_data_column_sidecar_inclusion_proof` is REMOVED at Gloas (`vendor/consensus-specs/specs/gloas/p2p-interface.md:60-62`).

Three recheck questions:
1. Fulu-surface invariants (H1–H10 from prior audit) — do all six clients still implement byte-for-byte equivalent sidecar validation?
2. **At Gloas (the new target)**: which clients wire the Modified verify functions + handle the Removed inclusion proof? Lighthouse Pattern M cohort gap extension count?
3. Does grandine's hardcoded `index_at_commitment_depth = 11` still apply at Gloas? (No — inclusion proof is REMOVED at Gloas; dead code there. Concern shifts to Heze backward compat.)

## Hypotheses

- **H1.** `verify_data_column_sidecar` rejects `sidecar.index >= NUMBER_OF_COLUMNS = 128`.
- **H2.** Rejects sidecar with empty column / commitments (no blobs).
- **H3.** *(Fulu only)* Rejects when `len(kzg_commitments) > get_blob_parameters(epoch).max_blobs_per_block` (cross-cuts item #31).
- **H4.** Length consistency: `len(column) == len(kzg_commitments) == len(kzg_proofs)`.
- **H5.** `verify_data_column_sidecar_kzg_proofs` builds `cell_indices = [sidecar.index] * len(column)`.
- **H6.** Calls `verify_cell_kzg_proof_batch(commitments, cell_indices, cells, proofs)`.
- **H7.** `verify_data_column_sidecar_inclusion_proof` (Fulu only) computes `leaf = hash_tree_root(sidecar.kzg_commitments)`.
- **H8.** Uses `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` constant (Deneb-heritage).
- **H9.** Gindex resolves to `BeaconBlockBody.blob_kzg_commitments` field; 5/6 clients dynamic; **grandine HARDCODES `11`** (Pattern P).
- **H10.** Returns `bool` / `Result<(), Error>` — short-circuit on first failure.
- **H11.** *(Glamsterdam target — verify functions Modified)*. `verify_data_column_sidecar` and `verify_data_column_sidecar_kzg_proofs` are MODIFIED at Gloas to take external `kzg_commitments` parameter. The blob-limit check in `verify_data_column_sidecar` is REMOVED at Gloas (gated upstream at `process_execution_payload_bid` per item #32).
- **H12.** *(Glamsterdam target — inclusion proof REMOVED)*. `verify_data_column_sidecar_inclusion_proof` is REMOVED at Gloas. The DataColumnSidecar container loses `signed_block_header`, `kzg_commitments`, `kzg_commitments_inclusion_proof`; gains `slot`, `beacon_block_root`. Inclusion proof is replaced by the bid signature in `process_execution_payload_bid` gating the commitments.
- **H13.** *(Glamsterdam target — per-client Gloas wiring 5-vs-1)*. Five clients (prysm, teku, nimbus, lodestar, grandine) wire the Gloas modifications. **Lighthouse is MISSING** with explicit `TODO(gloas)` marker at `data_column_verification.rs:243-244`. Pattern M cohort gap extends here.
- **H14.** *(Glamsterdam target — grandine Pattern P forward-fragility shifts to Heze)*. Grandine's hardcoded `index_at_commitment_depth = 11` (`eip_7594/src/lib.rs:217`) becomes DEAD CODE at Gloas (inclusion proof REMOVED). Concern shifts to Heze where teku has full EIP-7805 implementation potentially adding new BeaconBlockBody fields — if Heze re-introduces inclusion proof verification with a different schema layout, grandine's hardcoded `11` would silently mismatch.

## Findings

H1–H14 satisfied. **No state-transition divergence at the Fulu surface; lighthouse Pattern M cohort gap extends here at Gloas; grandine Pattern P concern shifts from Fulu→Gloas (now dead) to Gloas→Heze (forward-fragility).**

### prysm

`vendor/prysm/beacon-chain/core/peerdas/p2p_interface.go:34 VerifyDataColumnSidecar(sidecar) error` (Fulu). Batch KZG verification at `:67 VerifyDataColumnsSidecarKZGProofs(sidecars []) error` with explicit "deviation from spec" comment for performance.

**Gloas wiring**: `TestVerifyDataColumnSidecarInclusionProof_SkipsGloas` test at `vendor/prysm/beacon-chain/core/peerdas/p2p_interface_test.go:218-222` confirms prysm SKIPS inclusion proof verification at Gloas, matching the spec REMOVAL:

```go
func TestVerifyDataColumnSidecarInclusionProof_SkipsGloas(t *testing.T) {
    // ... construct Gloas data column ...
    require.NoError(t, peerdas.VerifyDataColumnSidecarInclusionProof(roCol))
}
```

The wrapper function returns NoError without performing the proof verification when fork ≥ Gloas. Spec-conformant.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (Fulu only). H8 ✓. H9 ✓ (dynamic). H10 ✓. H11 ✓ (Gloas modifications wired). H12 ✓ (inclusion proof skipped at Gloas). H13 ✓ (prysm in the 5-of-6 cohort with full Gloas wiring). H14 n/a.

### lighthouse

`vendor/lighthouse/beacon_node/beacon_chain/src/data_column_verification.rs:567 verify_data_column_sidecar(data_column, spec)` (Fulu). `:631 verify_column_inclusion_proof` calls `data_column.verify_inclusion_proof()` method on the type.

**Gloas wiring: MISSING.** At `:243-244`:

```rust
// TODO(gloas) support gloas data column variant
DataColumnSidecar::Gloas(_) => Err(GossipDataColumnError::InvalidVariant),
```

**Lighthouse cannot process Gloas DataColumnSidecar at gossip-verification time.** Returns `InvalidVariant` error on any Gloas-variant sidecar. Adds to Pattern M cohort (lighthouse Gloas-ePBS readiness gap).

**Lighthouse Pattern M cohort symptom count goes to 11+** (item #28 catalogue):
1. Item #14 H9 — `is_builder_withdrawal_credential` predicate missing.
2. Item #19 H10 — `apply_parent_execution_payload` missing.
3. Item #22 H10 — `is_builder_withdrawal_credential` predicate missing.
4. Item #23 H8 — `get_pending_balance_to_withdraw_for_builder` missing.
5. Item #24 H11 — switch-to-compounding ePBS routing missing.
6. Item #25 H11 — `is_valid_indexed_payload_attestation` missing.
7. Item #26 H8 — `get_attesting_indices` Gloas-surface (absence confirmation).
8-10. Item #32 — `process_execution_payload_bid`, `apply_parent_execution_payload`, `verify_execution_payload_envelope` missing.
11. **NEW this item — `DataColumnSidecar::Gloas` variant explicitly rejected (3 symptoms in one: verify, kzg_proofs, and the absent inclusion-proof-removal logic).**

Single upstream fix (lighthouse EIP-7732 ePBS implementation) closes all cohort symptoms.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓ (dynamic). H10 ✓. **H11 ✗** (no Gloas variant handling). **H12 ✗** (Gloas variant rejected; inclusion-proof-removal logic absent). **H13 ✗** (lighthouse IS the cohort gap). H14 n/a.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/fulu/helpers/MiscHelpersFulu.java:243 verifyDataColumnSidecar(sidecar) -> bool` (Fulu). `:333 verifyDataColumnSidecarInclusionProof` calls `predicates.isValidMerkleBranch`. Batch KZG at `:304 verifyDataColumnSidecarKzgProofsBatch(List)`.

**Gloas wiring**: `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/util/DataColumnSidecarUtilGloas.java`:
- `:174 verifyDataColumnSidecarStructure(dataColumnSidecar)` delegates to `miscHelpersGloas.verifyDataColumnSidecar(dataColumnSidecar)`.
- `:261-263` orchestrates `verifyDataColumnSidecar` + `verifyDataColumnSidecarKzgProofs`.
- `:295-301` calls `miscHelpersGloas.verifyDataColumnSidecarWithCommitments(...)` — the Gloas-Modified variant taking external commitments.
- `:310-316` calls `miscHelpersGloas.verifyDataColumnSidecarKzgProofs(dataColumnSidecar, bidKzgCommitments)`.

`MiscHelpersGloas.java:269 verifyDataColumnSidecarWithCommitments(...)` + `:285 verifyDataColumnSidecar(dataColumnSidecar)` — Gloas-specific overrides matching spec modifications.

Subclass-extension pattern: `DataColumnSidecarUtilGloas` extends `DataColumnSidecarUtilFulu`; `MiscHelpersGloas` extends `MiscHelpersFulu`. Cleanest fork-isolation across the 6 clients.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓ (dynamic via `getBlockBodyKzgCommitmentsGeneralizedIndex()`). H10 ✓. H11 ✓ (Gloas Modified wired). H12 ✓ (Gloas inclusion proof not invoked). **H13 ✓** (teku in the 5-of-6 cohort; reaffirms outdated "teku is the laggard" framing). H14 n/a.

### nimbus

`vendor/nimbus/beacon_chain/spec/peerdas_helpers.nim`:
- `:447 verify_data_column_sidecar*(cfg, sidecar: fulu.DataColumnSidecar)` (Fulu).
- `:473 verify_data_column_sidecar*(cfg, sidecar: gloas.DataColumnSidecar, kzg_commitments)` — Gloas Modified overload taking external commitments.
- `:496 verify_data_column_sidecar_inclusion_proof*(sidecar: fulu.DataColumnSidecar)` — **Fulu only** (no Gloas variant — matches spec REMOVAL at Gloas).
- `:530 verify_data_column_sidecar_kzg_proofs*` (Fulu) + `:550` (Gloas overload).

Multi-fork-definition Pattern I (carry forward). Type-overload dispatch via Nim's compile-time overload resolution on `sidecar: fulu.DataColumnSidecar` vs `sidecar: gloas.DataColumnSidecar`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (Fulu only). H8 ✓. H9 ✓ (dynamic). H10 ✓. H11 ✓ (Gloas Modified overload at `:473`). H12 ✓ (Fulu-only inclusion proof). **H13 ✓** (nimbus in the 5-of-6 cohort; Pattern I separate definitions). H14 n/a.

### lodestar

`vendor/lodestar/packages/beacon-node/src/chain/validation/dataColumnSidecar.ts`:
- `:276 verifyFuluDataColumnSidecar(config, dataColumnSidecar)` (Fulu).
- `:323 verifyGloasDataColumnSidecar(dataColumnSidecar, kzgCommitments)` — Gloas Modified, takes external commitments.
- `:380 verifyDataColumnSidecarInclusionProof(dataColumnSidecar: fulu.DataColumnSidecar)` — **Fulu only** (parameter type restricts to Fulu).
- `:358 verifyDataColumnSidecarKzgProofs` (shared between Fulu + Gloas paths).

Orchestration at `:41` (Fulu) + `:241` (Gloas) dispatches the right `verify*DataColumnSidecar` based on the sidecar's fork.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓ (dynamic). H10 ✓. H11 ✓ (Gloas Modified wired). H12 ✓ (Fulu-only inclusion proof). **H13 ✓** (lodestar in the 5-of-6 cohort). H14 n/a.

### grandine

`vendor/grandine/eip_7594/src/lib.rs`:
- `:27 use ... FuluDataColumnSidecar`; `:30 use ... GloasDataColumnSidecar`.
- `:149 pub fn verify_data_column_sidecar<P: Preset>(config, data_column_sidecar, kzg_commitments)` — **already takes external commitments parameter** (prescient Gloas forward-compat from the prior audit).
- `:185 pub fn verify_kzg_proofs<P: Preset>(...)`.
- `:217 pub fn verify_sidecar_inclusion_proof<P: Preset>(data_column_sidecar: &FuluDataColumnSidecar<P>, ...)` — **type-restricted to FuluDataColumnSidecar only**; dead code at Gloas (the Gloas variant doesn't have the fields the inclusion proof would consume).

The pre-Gloas blob-limit check is gated via `data_column_sidecar.pre_gloas()` check (`:163-170`):

```rust
if let Some(data_column_sidecar) = data_column_sidecar.pre_gloas() {
    let epoch = misc::compute_epoch_at_slot::<P>(data_column_sidecar.slot());
    if kzg_commitments.len() > config.get_blob_schedule_entry(epoch).max_blobs_per_block {
        return false;
    }
}
```

Spec-conformant at Gloas (blob-limit check skipped, matching spec REMOVAL of the check from `verify_data_column_sidecar`).

**Grandine Pattern P concern shifts** (carry-forward from prior audit): the hardcoded `index_at_commitment_depth = 11` at `:217-244` is now DEAD CODE at Gloas (inclusion proof not invoked on `GloasDataColumnSidecar`). The forward-fragility concern shifts from Fulu→Gloas to potential Gloas→Heze backward compat — if Heze re-introduces some form of inclusion proof verification with a different schema layout, the dead code could be revived with a stale `11` magic number. Forward-tracker only; no current divergence.

H1 ✓. H2 ✓. H3 ✓ (gated to pre-Gloas). H4 ✓. H5 ✓. H6 ✓. H7 ✓ (Fulu only via type restriction). H8 ✓. **H9 ⚠** (hardcoded `11` — Pattern P, dead at Gloas). H10 ✓. H11 ✓ (Gloas Modified wired via external commitments parameter — already correct from prior audit). H12 ✓ (Fulu-only inclusion proof via type restriction). **H13 ✓** (grandine in the 5-of-6 cohort). H14 ✓ (Pattern P concern shifts to Heze).

## Cross-reference table

| Client | Fulu `verify_data_column_sidecar` | Gloas Modified handling | `verify_data_column_sidecar_inclusion_proof` at Gloas | gindex resolution | H13 |
|---|---|---|---|---|---|
| prysm | `core/peerdas/p2p_interface.go:34 VerifyDataColumnSidecar` + batch KZG at `:67` | wired (variant dispatch) | **SKIPPED** (matches REMOVAL; test at `p2p_interface_test.go:218`) | dynamic | ✓ in cohort |
| lighthouse | `beacon_chain/src/data_column_verification.rs:567 verify_data_column_sidecar` | **MISSING** — `TODO(gloas) ... InvalidVariant` (`:243-244`) | **MISSING** — Gloas variant rejected | dynamic via type method | **✗ cohort gap (Pattern M)** |
| teku | `MiscHelpersFulu.java:243 verifyDataColumnSidecar` + batch `:304` | wired via `MiscHelpersGloas extends MiscHelpersFulu` (subclass override at `:269 verifyDataColumnSidecarWithCommitments`); orchestrated in `DataColumnSidecarUtilGloas` | spec-removed; teku follows | dynamic via `getBlockBodyKzgCommitmentsGeneralizedIndex()` | ✓ in cohort |
| nimbus | `peerdas_helpers.nim:447 verify_data_column_sidecar` (Fulu) + `:473` (Gloas overload) | separate Fulu/Gloas type-overload (Pattern I) | **Fulu only** at `:496` (matches REMOVAL) | dynamic | ✓ in cohort |
| lodestar | `dataColumnSidecar.ts:276 verifyFuluDataColumnSidecar` | separate `:323 verifyGloasDataColumnSidecar` (external commitments) | **Fulu-only** via parameter type restriction at `:380` | dynamic | ✓ in cohort |
| grandine | `eip_7594/src/lib.rs:149 verify_data_column_sidecar` (already external commitments — prescient) | wired via `pre_gloas()` gate | **Fulu-only** via `FuluDataColumnSidecar`-typed parameter at `:217` (dead code at Gloas; Pattern P shifts to Heze) | **HARDCODED `11`** (Pattern P) | ✓ in cohort |

## Empirical tests

### Fulu-surface live mainnet validation

Live mainnet PeerDAS gossip has been operational since Fulu activation (epoch 411392, 2025-12-03) — 5+ months. Across 2 BPO transitions (epochs 412672 and 419072), zero cross-client gossip / data-column-validation divergence. All 6 clients accept/reject the same sidecars per the Fulu-NEW pipeline.

### Gloas-surface

`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `mainnet.yaml:60`. Gloas modifications source-level only.

Concrete Gloas-spec evidence:
- `vendor/consensus-specs/specs/gloas/p2p-interface.md:57-81` — `DataColumnSidecar` Modified (3 fields REMOVED, 2 ADDED).
- `vendor/consensus-specs/specs/gloas/p2p-interface.md:132-153` — `verify_data_column_sidecar_kzg_proofs` Modified (external kzg_commitments parameter).
- `vendor/consensus-specs/specs/gloas/p2p-interface.md:156-184` — `verify_data_column_sidecar` Modified (external parameter; blob-limit check removed).
- No `Modified verify_data_column_sidecar_inclusion_proof` heading — function REMOVED at Gloas per the spec note at `:60-62`.

### EF fixture status (no change from prior audit)

**Dedicated EF fixtures do NOT exist** for the verify_data_column_sidecar family. Live mainnet gossip + per-client unit tests are the only coverage today.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1**: dedicated EF fixture set for `verify_data_column_sidecar` family (pure functions `sidecar → bool`). Cross-client byte-level equivalence at Fulu and Gloas state inputs.
- **T1.2**: wire Fulu fixture categories in BeaconBreaker harness (carry-forward from items #30, #31, #32, #33).

#### T2 — Adversarial probes
- **T2.1 (Glamsterdam-target — H13 cohort fixture)**: synthetic Gloas DataColumnSidecar fed to all 6 clients. Expected: prysm, teku, nimbus, lodestar, grandine accept/reject per the Gloas Modified body; **lighthouse rejects with `InvalidVariant`**. Documents the cohort gap.
- **T2.2 (Glamsterdam-target — inclusion proof REMOVED)**: synthetic Gloas DataColumnSidecar with arbitrary `kzg_commitments_inclusion_proof`-equivalent bytes (no such field exists at Gloas). Expected: all 6 clients (except lighthouse) accept regardless of any inclusion-proof bytes — verify NO client reuses the Fulu inclusion-proof validation on Gloas-variant sidecars.
- **T2.3 (Glamsterdam-target — H14 Heze forward-tracker)**: grandine's `index_at_commitment_depth = 11` hardcoded value. Verify it remains DEAD CODE at Gloas (`GloasDataColumnSidecar` doesn't have the fields). Track Heze schema additions explicitly — if Heze re-introduces inclusion proof verification, audit grandine for the stale magic number.
- **T2.4 (batch KZG verification correctness)**: prysm + teku batch optimization vs spec one-at-a-time. Generate fixture with 1 valid + 1 invalid sidecar; verify batch reports ALL-FAIL while per-sidecar identifies the specific bad one. Forward-fragility verification.
- **T2.5 (BPO transition correctness — Fulu only)**: at the BPO #2 transition (epoch 419072), sidecar with `column.length = 22` (= max + 1) should fail at all 6 clients. Sidecar with `column.length = 21` should pass. Already validated by live mainnet but worth a dedicated fixture.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Fulu-surface invariants (H1–H10) carry forward unchanged from the 2026-05-04 audit. Live mainnet PeerDAS gossip has been operational without divergence for 5+ months.

**Glamsterdam-target finding (H11 + H12 — major restructure at Gloas).** `vendor/consensus-specs/specs/gloas/p2p-interface.md:57-184` documents:
- **DataColumnSidecar Modified** (`:57-81`): 3 fields REMOVED (`signed_block_header`, `kzg_commitments`, `kzg_commitments_inclusion_proof`); 2 fields ADDED (`slot`, `beacon_block_root`).
- **`verify_data_column_sidecar` Modified** (`:156-184`): external `kzg_commitments` parameter; blob-limit check REMOVED (gated upstream at `process_execution_payload_bid` per item #32).
- **`verify_data_column_sidecar_kzg_proofs` Modified** (`:132-153`): external `kzg_commitments` parameter.
- **`verify_data_column_sidecar_inclusion_proof` REMOVED**: per spec note at `:60-62`, "header and inclusion proof verifications are no longer required in Gloas. The KZG commitments are now located at `block.body.signed_execution_payload_bid.message.blob_kzg_commitments`."

The bid signature in `process_execution_payload_bid` (item #32 / item #19 H10 cohort) gates the commitments at Gloas — replaces the per-sidecar inclusion proof.

**Glamsterdam-target finding (H13 — lighthouse Pattern M cohort gap extends here).** Five of six clients (prysm, teku, nimbus, lodestar, grandine) wire the Gloas Modified functions correctly. **Lighthouse is missing**, with explicit `TODO(gloas)` marker at `vendor/lighthouse/beacon_node/beacon_chain/src/data_column_verification.rs:243-244`:

```rust
// TODO(gloas) support gloas data column variant
DataColumnSidecar::Gloas(_) => Err(GossipDataColumnError::InvalidVariant),
```

Lighthouse rejects Gloas-variant DataColumnSidecar at gossip-verification time. **Pattern M cohort symptom count goes to 11+** (items #14, #19, #22, #23, #24, #25, #26, #32, #34 — with overlap in counting). Single upstream fix (lighthouse EIP-7732 ePBS implementation) closes all cohort symptoms.

**Glamsterdam-target finding (H14 — grandine Pattern P concern shifts from Fulu to Heze).** Grandine's hardcoded `index_at_commitment_depth = 11` at `vendor/grandine/eip_7594/src/lib.rs:217-244` is now DEAD CODE at Gloas — the inclusion proof verification function is type-restricted to `FuluDataColumnSidecar` only, and Gloas spec removes the inclusion proof entirely. **Pattern P forward-fragility shifts** from "Fulu→Gloas" (where it would have been a divergence vector) to "Gloas→Heze" (where it remains a code-smell tracker for any future re-introduction of inclusion proof verification).

**Sixteenth impact-none result** in the recheck series for the Fulu surface (the current mainnet target). The Gloas surface modifications + removals are source-level only at this time (`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH`); lighthouse cohort gap is a tracked future divergence, not yet mainnet-reachable.

**Notable per-client style differences (all observable-equivalent at Fulu mainnet):**
- **prysm**: batch KZG verification with explicit "deviation from spec" comment; SKIP test at `p2p_interface_test.go:218` confirms Gloas-aware inclusion proof handling.
- **lighthouse**: type-method `data_column.verify_inclusion_proof()` encapsulation; explicit `TODO(gloas)` marker — cleanest gap tracking.
- **teku**: subclass-extension pattern (`MiscHelpersGloas extends MiscHelpersFulu` + `DataColumnSidecarUtilGloas` extends `DataColumnSidecarUtilFulu`). Reaffirms "teku is the Heze leader" finding from item #29.
- **nimbus**: separate Fulu/Gloas overloads (Pattern I); Fulu-only inclusion proof matches spec REMOVAL.
- **lodestar**: separate `verifyFuluDataColumnSidecar` / `verifyGloasDataColumnSidecar` functions; parameter-type restriction for Fulu-only inclusion proof.
- **grandine**: type-polymorphic via `FuluDataColumnSidecar` / `GloasDataColumnSidecar` containers; prescient external `kzg_commitments` parameter (already matched Gloas modification from the Fulu source); Pattern P hardcoded gindex tracked.

**No code-change recommendation at the Fulu surface.** Audit-direction recommendations:

- **Lighthouse EIP-7732 ePBS surface implementation** — closes the Pattern M cohort including this item's 3+ new symptoms. Highest-priority pre-Gloas implementation work.
- **Update item #28 Pattern M cohort symptom count** — this item adds 3 new symptoms (verify, kzg_proofs, inclusion-proof-removal); total at 11+ depending on overlap.
- **Grandine Pattern P Heze forward-tracker** — when Heze ships, audit grandine for stale hardcoded `11` if any inclusion-proof verification is re-introduced.
- **Dedicated EF fixture set for verify family** (T1.1) — pure-function cross-client byte-level equivalence at Fulu and Gloas state inputs.
- **Wire Fulu fixture categories in BeaconBreaker harness** (T1.2) — same gap as items #30, #31, #32, #33.

## Cross-cuts

### With item #28 (Gloas divergence meta-audit) — Pattern M cohort expansion

This item adds **3 new lighthouse cohort symptoms**:
1. `verify_data_column_sidecar` Gloas variant rejected.
2. `verify_data_column_sidecar_kzg_proofs` Gloas variant rejected.
3. `verify_data_column_sidecar_inclusion_proof` Gloas-removal logic absent.

Combined with prior items' symptoms (items #14, #19, #22, #23, #24, #25, #26 — 7 prior + item #32's 3 + this item's 3 = 13 with overlap counting). Item #28's Pattern M cohort symptom count reaffirmed at 11+. Single upstream fix closes all.

### With item #31 (`get_blob_parameters` BPO) — blob-limit check relocation

The blob-limit check in `verify_data_column_sidecar` at Fulu (H3) is REMOVED at Gloas. The check moves UPSTREAM to `process_execution_payload_bid` per item #32 (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1448` — `len(bid.blob_kzg_commitments) <= get_blob_parameters(...)`). Same primitive, different caller.

### With item #32 (`process_execution_payload` removed at Gloas)

Item #32 documented the Gloas REMOVAL of `process_execution_payload` and the addition of `process_execution_payload_bid` / `apply_parent_execution_payload` / `verify_execution_payload_envelope`. This item's `verify_data_column_sidecar` REMOVAL (the inclusion proof) is part of the same EIP-7732 ePBS restructure: the per-sidecar inclusion proof is replaced by the bid signature gate at `process_execution_payload_bid`.

### With item #33 (PeerDAS custody)

Item #33 audited custody assignment. This item validates sidecars after they're received. `sidecar.index` (H1) is cross-checked against custody groups upstream of gossip-validation. Cross-cut: out-of-range sidecar.index would fail both this item's H1 check AND custody validation.

### With item #29 (signing-domain primitives + Heze finding)

Item #29 found teku has full Heze (EIP-7805) implementation. This item's Pattern P concern (grandine hardcoded `11`) is forward-fragile at Heze: if Heze re-introduces some form of inclusion proof verification with a different schema layout, grandine's dead-code `11` would silently mismatch when revived. Tracker only — no current divergence.

### With Heze (post-Gloas) — Pattern P forward-tracker

Heze adds inclusion-list functionality (EIP-7805). If Heze re-introduces per-sidecar inclusion proof verification (e.g., for a new sidecar type related to inclusion lists), the schema position of `blob_kzg_commitments` or equivalent fields may differ. Grandine's `index_at_commitment_depth = 11` would silently mismatch — Pattern P forward-fragility class.

## Adjacent untouched

1. **Lighthouse EIP-7732 ePBS surface implementation** — closes 11+ Pattern M cohort symptoms (highest-priority pre-Gloas work).
2. **Update item #28 Pattern M cohort symptom count** — this item adds 3 new symptoms.
3. **Update item #28 Pattern P (NEW)** — grandine hardcoded gindex magic number; track Heze forward-fragility.
4. **Dedicated EF fixture set for verify_data_column_sidecar family** — pure-function cross-client byte-level equivalence (T1.1).
5. **Wire Fulu fixture categories in BeaconBreaker harness** — same gap as items #30, #31, #32, #33 (T1.2).
6. **Batch KZG verification correctness audit** — prysm + teku batch vs spec one-at-a-time; identify-the-bad-sidecar granularity (T2.4).
7. **`verify_partial_data_column_*` audit** — Fulu p2p partial-message variants (separate item).
8. **`compute_subnet_for_data_column_sidecar` audit** — gossip subnet derivation cross-cut with item #33.
9. **`verify_cell_kzg_proof_batch` audit** — KZG cell-proof primitive (Track F follow-up).
10. **`is_data_available` Fulu fork-choice integration audit** — consumes these verifications upstream.
11. **`MAX_REQUEST_DATA_COLUMN_SIDECARS` wire limits audit** — cross-network constants.
12. **DataColumnSidecar SSZ container schema** (Track E follow-up) — verify cross-client byte-level equivalence of the Fulu and Gloas variants.
13. **DataColumnSidecarsByRange / ByRoot RPC handler cross-client audit**.
14. **Per-client gossip rate-limiting / scoring on sidecar validation failures**.
15. **Cross-fork transition fixture Fulu→Gloas** — DataColumnSidecar variant handover at the fork boundary.
16. **Heze forward-tracker — grandine Pattern P revival concern** — track if Heze re-introduces inclusion proof verification with different schema.
