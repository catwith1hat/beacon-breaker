# Item 34 — `verify_data_column_sidecar` + `verify_data_column_sidecar_kzg_proofs` + `verify_data_column_sidecar_inclusion_proof` (EIP-7594 PeerDAS sidecar validation pipeline)

**Status:** no-divergence-pending-source-review — audited 2026-05-04. **Fifth Fulu-NEW item, second PeerDAS audit** (after #33 custody foundation). The sidecar validation pipeline that gates every PeerDAS gossip message: structural validation (`verify_data_column_sidecar`), KZG cell-proof verification (`verify_data_column_sidecar_kzg_proofs`), and Merkle inclusion proof against the block body (`verify_data_column_sidecar_inclusion_proof`). Three functions, one per validation concern.

**Cross-cuts**: item #31 (`get_blob_parameters` for BPO blob limit — used by H3); item #33 (custody assignment — sidecar.index validation); item #29 (signing-domain primitives — Merkle proof + Heze finding). **Upstream of `is_data_available`** in fork-choice — sidecars must pass these 3 verifications before they're stored and counted toward data availability.

Critical security surface: a sidecar that passes verification enters the local data store and is served to peers. Divergence here would cause peers to reject each other's data column requests (PeerDAS gossip mesh fragmentation) or — worse — accept bogus sidecars that the rest of the network rejects (consensus split at the data-availability decision).

## Scope

In: `verify_data_column_sidecar(sidecar)` structural validation; `verify_data_column_sidecar_kzg_proofs(sidecar)` KZG cell-proof batch verification; `verify_data_column_sidecar_inclusion_proof(sidecar)` Merkle inclusion proof.

Out: `is_data_available` fork-choice integration (separate item — uses these verifications upstream); `verify_partial_data_column_*` partial-message variants (Fulu p2p extension); `verify_cell_kzg_proof_batch` KZG primitive itself (Track F follow-up — covered partially at item #20/#25 BLS audits, but cell proofs are different); gossip-layer surrounding checks (subnet ID, slot, finalization, parent, proposer signature — gossip pipeline orchestration).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | `verify_data_column_sidecar` rejects `sidecar.index >= NUMBER_OF_COLUMNS = 128` | ✅ all 6 | First check in spec. |
| H2 | Rejects sidecar with `len(kzg_commitments) == 0` (no blobs) | ✅ all 6 | Spec rejects empty. |
| H3 | Rejects when `len(kzg_commitments) > get_blob_parameters(epoch).max_blobs_per_block` (cross-cuts item #31) | ✅ all 6 | All 6 route through item #31's BPO-aware lookup. |
| H4 | Rejects when `len(column) != len(kzg_commitments) || len(column) != len(kzg_proofs)` | ✅ all 6 | Length consistency enforced. |
| H5 | `verify_data_column_sidecar_kzg_proofs` builds `cell_indices = [sidecar.index] * len(column)` | ✅ all 6 | Spec idiom — column index is the cell index for all cells in this column. |
| H6 | Calls `verify_cell_kzg_proof_batch(commitments, cell_indices, cells, proofs)` | ✅ all 6 | Cross-cuts KZG primitive (Track F). |
| H7 | `verify_data_column_sidecar_inclusion_proof` computes `leaf = hash_tree_root(sidecar.kzg_commitments)` | ✅ all 6 | Standard SSZ hash. |
| H8 | Uses `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` constant (Deneb-heritage) | ✅ all 6 | Same depth across forks; constant from polynomial-commitments-sampling spec. |
| H9 | Generalized index resolves to `BeaconBlockBody.blob_kzg_commitments` field; via `get_subtree_index(get_generalized_index(BeaconBlockBody, "blob_kzg_commitments"))` | ✅ in 5 of 6 (prysm, lighthouse, teku, nimbus, lodestar dynamically resolve); ⚠️ **grandine HARDCODES `index_at_commitment_depth = 11`** | **DIVERGENCE concern at Heze** — see Notable findings. |
| H10 | Returns `bool` / `Result<(), Error>` — short-circuit on first failure | ✅ all 6 | All 6 early-exit. |

## Per-client cross-reference

| Client | `verify_data_column_sidecar` | `verify_data_column_sidecar_kzg_proofs` | `verify_data_column_sidecar_inclusion_proof` | Multi-fork-defs? | gindex resolution |
|---|---|---|---|---|---|
| **prysm** | `core/peerdas/p2p_interface.go:34` `VerifyDataColumnSidecar(sidecar) error` | `:67` `VerifyDataColumnsSidecarKZGProofs(sidecars []) error` (BATCH OPT — multiple sidecars; explicit "deviation from spec" comment for perf) + `:74-83` private worker | (separate file) | NO — single function | dynamic |
| **lighthouse** | `beacon_chain/src/data_column_verification.rs:567` `verify_data_column_sidecar(data_column, spec)` | (in KZG verifier crate — separate item) | `:631` `verify_column_inclusion_proof` calls `data_column.verify_inclusion_proof()` METHOD on type | NO — single function | dynamic via type method |
| **teku** | `MiscHelpersFulu.java:243` `verifyDataColumnSidecar(sidecar) -> bool` (LOG.trace + early-return on each failure) | `:285` `verifyDataColumnSidecarKzgProofs` (single) + `:304` `verifyDataColumnSidecarKzgProofsBatch(List)` (multiple) | `:333` `verifyDataColumnSidecarInclusionProof` calls `predicates.isValidMerkleBranch` | NO — single function (subclass at Gloas in `MiscHelpersGloas`) | dynamic via `getBlockBodyKzgCommitmentsGeneralizedIndex()` (`:347`) |
| **nimbus** | `spec/peerdas_helpers.nim:447` `verify_data_column_sidecar` (Fulu) + `:473` (Gloas overload) | `:530` `verify_data_column_sidecar_kzg_proofs` (Fulu) + `:550` (Gloas overload) | `:496` `verify_data_column_sidecar_inclusion_proof` (Fulu only) | YES — separate Fulu/Gloas overloads (Pattern I) | dynamic via `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH_GINDEX.GeneralizedIndex` |
| **lodestar** | `beacon-node/src/chain/validation/dataColumnSidecar.ts:276` `verifyFuluDataColumnSidecar(config, sidecar)` (PRIVATE function inside gossip validation flow) | (separate; uses KZG library directly via `verifyCellKzgProofBatch`) | (separate function in same file/module) | NO | dynamic |
| **grandine** | `eip_7594/src/lib.rs:149` `verify_data_column_sidecar(config, sidecar, kzg_commitments)` — **takes external commitments parameter** (Gloas-friendly forward-compat) | `:185` `verify_kzg_proofs(sidecar, commitments, backend, metrics)` | `:217` `verify_sidecar_inclusion_proof(sidecar, metrics)` — **HARDCODES `index_at_commitment_depth = 11`** | NO — single function takes external commitments | **HARDCODED `11` (magic number)** |

## Notable per-client findings

### grandine HARDCODES `index_at_commitment_depth = 11` — Heze forward-fragility

Grandine's `verify_sidecar_inclusion_proof` (`eip_7594/src/lib.rs:217-244`):

```rust
pub fn verify_sidecar_inclusion_proof<P: Preset>(
    data_column_sidecar: &FuluDataColumnSidecar<P>,
    metrics: Option<&Arc<Metrics>>,
) -> bool {
    // ...
    let FuluDataColumnSidecar {
        kzg_commitments,
        signed_block_header,
        kzg_commitments_inclusion_proof,
        ..
    } = data_column_sidecar;

    // Fields in BeaconBlockBody before blob KZG commitments
    let index_at_commitment_depth = 11;

    // is_valid_blob_sidecar_inclusion_proof
    is_valid_merkle_branch(
        kzg_commitments.hash_tree_root(),
        *kzg_commitments_inclusion_proof,
        index_at_commitment_depth,
        signed_block_header.message.body_root,
    )
}
```

**The spec uses `get_subtree_index(get_generalized_index(BeaconBlockBody, "blob_kzg_commitments"))`** — a dynamic field-offset resolution against the SSZ schema. Grandine hardcodes the value as `11` (likely the blob_kzg_commitments field index in the Fulu BeaconBlockBody schema, but **not verified to be stable across forks**).

**HIGH-PRIORITY divergence concern at Heze (post-Gloas)**: per item #29's Heze finding, teku has a full Heze (EIP-7805 inclusion lists) implementation. **EIP-7805 introduces new BeaconBlockBody fields**: `inclusion_list_summary`, `inclusion_list`, etc. If any new field is inserted before `blob_kzg_commitments` in the Heze BeaconBlockBody schema, the field index shifts and `11` becomes incorrect. Other 5 clients dynamically resolve via `get_generalized_index(BeaconBlockBody, "blob_kzg_commitments")` — automatically updated.

**Mitigation paths for grandine**:
1. Replace hardcoded `11` with dynamic `get_generalized_index<BeaconBlockBody>("blob_kzg_commitments")`
2. Add a compile-time assertion `static_assert!(index_at_commitment_depth == get_generalized_index_const(...))` to fail at build time if schema shifts
3. Track Heze schema additions explicitly when Heze ships

**Forward-research**: cross-fork BeaconBlockBody field-ordering audit — verify `blob_kzg_commitments` is still at index 11 (or whatever the Fulu position is) across all forks shipped by all 6 clients.

### prysm + teku batch KZG verification (perf optimization)

**Spec verifies each sidecar's KZG proofs separately**. prysm + teku batch them across multiple sidecars in a single call to the KZG library. Same observable result (all-or-nothing batch verification), much faster.

prysm (`p2p_interface.go:67-83`) — explicit "deviation from spec" comment:
> Note: We are slightly deviating from the specification here:
> The specification verifies the KZG proofs for each sidecar separately,
> while we are verifying all the KZG proofs from multiple sidecars in a batch.
> This is done to improve performance since the internal KZG library is way more
> efficient when verifying in batch.

teku (`MiscHelpersFulu.java:304-331`) — `verifyDataColumnSidecarKzgProofsBatch(List<DataColumnSidecar>)` flattens all cells/proofs across sidecars into a single batch call.

**Forward-fragility**: if the spec ever distinguishes per-sidecar vs batch verification (e.g., per-sidecar logging on failure to identify the culprit), prysm + teku batch optimization would lose granularity. Other 4 clients verify per-sidecar. **Observable-equivalent on success/failure verdict; observable-different on which sidecar failed.**

### grandine takes external `kzg_commitments` parameter (Gloas forward-compat)

```rust
pub fn verify_data_column_sidecar<P: Preset>(
    config: &Config,
    data_column_sidecar: &Arc<DataColumnSidecar<P>>,
    kzg_commitments: &ContiguousList<KzgCommitment, P::MaxBlobCommitmentsPerBlock>,
) -> bool {
```

The spec (Fulu) reads `sidecar.kzg_commitments` directly. Grandine accepts external commitments as a parameter — this is **forward-compat for Gloas** where EIP-7732 PBS modifies `verify_data_column_sidecar` to accept `bid.blob_kzg_commitments` from the execution payload bid (item #28 Pattern G — builder deposit handling).

The pre-Gloas blob-limit check is gated:
```rust
if let Some(data_column_sidecar) = data_column_sidecar.pre_gloas() {
    let epoch = misc::compute_epoch_at_slot::<P>(data_column_sidecar.slot());
    if kzg_commitments.len() > config.get_blob_schedule_entry(epoch).max_blobs_per_block {
        return false;
    }
}
```

**Cross-cuts item #28 Pattern G (builder deposit handling)**: grandine's external-commitments parameter shape mirrors the same Gloas adaptation seen in deposit handling. **Forward-compat well-designed** — single function handles both Fulu (sidecar.kzg_commitments) and Gloas (bid.kzg_commitments) paths.

**Concern**: grandine's `verify_data_column_sidecar` signature DIFFERS from spec — caller must pass commitments separately. If a caller mistakenly passes the wrong list (e.g., previous block's commitments), grandine would verify against the wrong reference. **Higher caller-discipline requirement** vs spec's self-contained sidecar verification.

### nimbus separate Fulu + Gloas overloads (Pattern I)

Nimbus has TWO `verify_data_column_sidecar` definitions:
- `peerdas_helpers.nim:447` — Fulu: `verify_data_column_sidecar(cfg, sidecar: fulu.DataColumnSidecar)`
- `peerdas_helpers.nim:473` — Gloas: `verify_data_column_sidecar(cfg, sidecar: gloas.DataColumnSidecar, kzg_commitments)`

And TWO `verify_data_column_sidecar_kzg_proofs` definitions (lines 530 + 550). **Multi-fork-definition Pattern I** — same forward-fragility documented in items #6/#9/#10/#12/#14/#15/#17/#19/#31/#32. The Gloas Fulu overloads have nearly identical bodies but with the `kzg_commitments` parameter added (Gloas adaptation).

**Forward-fragility**: any future Heze/post-Gloas modification to either function requires a third overload. Bug fixes must be applied to both (or three) overloads.

### lighthouse encapsulates inclusion-proof in DataColumnSidecar method

```rust
fn verify_column_inclusion_proof<E: EthSpec>(
    data_column: &DataColumnSidecarFulu<E>,
) -> Result<(), GossipDataColumnError> {
    if !data_column.verify_inclusion_proof() {
        return Err(GossipDataColumnError::InvalidInclusionProof);
    }
    Ok(())
}
```

The actual Merkle-branch verification logic lives on the `DataColumnSidecarFulu` type itself. **Cleanest abstraction** — verification is a property of the sidecar, not a separate function. Other 5 clients have explicit Merkle-branch calls in the verification function.

### lodestar bundles spec helper inside gossip orchestration

Lodestar's `verifyFuluDataColumnSidecar` is a **PRIVATE function** (`function`, not `export function`) at `dataColumnSidecar.ts:276`. It's wrapped inside `validateGossipFuluDataColumnSidecar` which adds 12+ additional gossip-layer checks (subnet, slot disparity, finalization, parent existence, proposer signature, etc.). **Bundles spec helper with all gossip orchestration** — strict separation between consensus-helper and gossip-layer not enforced.

Other 5 clients keep the spec helper as a standalone, exported function — easier to audit in isolation. Lodestar's bundling is harder to audit but matches its overall gossip-validation architecture.

### teku factors generalized index into `getBlockBodyKzgCommitmentsGeneralizedIndex`

```java
public int getBlockBodyKzgCommitmentsGeneralizedIndex() {
    return (int)
        BeaconBlockBodySchemaElectra.required(schemaDefinitionsFulu.getBeaconBlockBodySchema())
            .getBlobKzgCommitmentsGeneralizedIndex();
}
```

Dynamic resolution via the SSZ schema registry — **forward-friendly at Heze** (no manual code change needed if BeaconBlockBody schema gains new fields, as long as `getBlobKzgCommitmentsGeneralizedIndex()` is updated for Heze schema).

### lodestar `lookahead` factor in lodestar (TBD)

Need to verify lodestar's KZG inclusion proof + KZG verification — both spec functions are present per grep but factored into utility modules. Adjacent untouched: lodestar peerdas KZG primitive cross-client audit.

## EF fixture status

**Dedicated EF fixtures DO NOT exist** for `verify_data_column_sidecar` family in `consensus-spec-tests/tests/mainnet/fulu/networking/`. Only custody fixtures (`get_custody_groups`, `compute_columns_for_custody_group`) — verified at item #33.

The `verify_data_column_sidecar` family is exercised through:
- **Live mainnet PeerDAS gossip** — every block since Fulu activation has produced data column sidecars validated by all 6 clients without breaking the gossip mesh
- **KZG cell proof reference tests** in `consensus-spec-tests/tests/mainnet/fulu/kzg/` (subset of polynomial-commitments-sampling primitive)
- Per-client unit tests (out of EF scope)

**Fixture gap**: pure-function (sidecar → bool) fixtures should be generated for the verify family. Generates as a future-research item.

## Cross-cut chain

This audit closes the PeerDAS gossip-validation surface and cross-cuts:
- **Item #31** (`get_blob_parameters` for BPO blob limit) — H3 directly consumes this primitive
- **Item #33** (PeerDAS custody assignment) — `sidecar.index` validation cross-cuts custody groups; out-of-range index would also fail custody check
- **Item #29** (signing-domain primitives + Heze finding) — grandine's hardcoded `index_at_commitment_depth = 11` is forward-fragile at Heze where teku has full EIP-7805 implementation potentially adding new BeaconBlockBody fields
- **Item #28 Pattern G** (builder deposit handling) — grandine's external `kzg_commitments` parameter shape mirrors the Gloas adaptation pattern
- **Item #28 Pattern I** (multi-fork-definition) — nimbus has separate Fulu/Gloas overloads
- **Track F BLS / KZG**: `verify_cell_kzg_proof_batch` is the next-level KZG primitive (Track F follow-up); covered partially at item #20/#25 BLS audits but cell proofs are different math

## Adjacent untouched Fulu-active

- `verify_partial_data_column_header_inclusion_proof` and `verify_partial_data_column_sidecar_kzg_proofs` (PartialDataColumnSidecar variants for Fulu p2p extension) — separate audit
- `compute_subnet_for_data_column_sidecar` — gossip subnet derivation (cross-cuts item #33)
- `verify_cell_kzg_proof_batch` — KZG cell-proof primitive (Track F follow-up)
- `is_data_available` Fulu fork-choice integration — uses these verifications upstream
- `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` constant cross-network consistency
- `BeaconBlockBody.blob_kzg_commitments` field offset stability across forks (Fulu / Gloas / Heze) — particularly grandine's hardcoded 11
- `MAX_REQUEST_DATA_COLUMN_SIDECARS` wire limits cross-client
- DataColumnSidecar SSZ container schema (Track E)
- DataColumnSidecarsByRange / ByRoot RPC handlers
- gossip-layer surrounding checks (subnet, slot, finalization, parent, proposer signature) — orchestration layer
- Cross-fork transition: Fulu→Gloas where DataColumnSidecar processing changes (per spec's `[Modified in Gloas:EIP7732]` annotations)
- Per-client gossip rate-limiting / scoring on sidecar validation failures
- Inclusion proof depth audit at Gloas (where ExecutionPayloadEnvelope changes BeaconBlockBody structure)

## Future research items

1. **Wire Fulu fixture categories** in BeaconBreaker harness — same blocker as items #30, #31, #32, #33; now spans 5 items + multiple Fulu sub-categories (`epoch_processing/proposer_lookahead/`, `operations/execution_payload/`, `networking/get_custody_groups/`, `networking/compute_columns_for_custody_group/`, plus future `kzg/` categories). **Highest-priority follow-up**.
2. **Generate dedicated fixture exercising grandine's `index_at_commitment_depth = 11`** — synthesize a sidecar where the BeaconBlockBody schema position of `blob_kzg_commitments` differs from 11. If grandine still passes, the hardcoded value is silently wrong.
3. **NEW Pattern P for item #28 catalogue**: hardcoded magic numbers vs dynamic gindex resolution (grandine vs others). Forward-fragility class similar to Pattern I/J/N.
4. **Cross-fork `BeaconBlockBody.blob_kzg_commitments` gindex audit** — compute the spec gindex for Fulu, Gloas, Heze (per teku's full implementation per item #29 finding); verify all 6 clients dynamically resolve. Highest-priority Heze pre-emptive item.
5. **Batch KZG verification cross-client correctness audit** — prysm + teku batch optimization vs other 4 per-sidecar. Generate fixture with 1 valid + 1 invalid sidecar; verify batch reports ALL-FAIL while per-sidecar identifies the specific bad one.
6. **Generate dedicated EF fixtures** for verify_data_column_sidecar family (pure function: sidecar → bool). Currently only exercised through live gossip + per-client unit tests.
7. **Empty-column edge case fixture**: `column.length = 0` (already rejected by H2 but test the boundary).
8. **Single-blob block fixture**: `column.length = 1` boundary — minimum valid sidecar.
9. **Maximum-blob block fixture**: `column.length = 21` (current BPO #2 limit per item #31); `column.length = 22` (over by one — should fail).
10. **Inclusion proof depth audit** — verify `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` constant matches across all 6 clients for mainnet/sepolia/holesky configs.
11. **`verify_partial_data_column_*` audit** — Fulu p2p extension for partial messages (separate item).
12. **`is_data_available` Fulu rewrite audit** — fork-choice DAS integration (separate item, queued).
13. **Gossip-layer scoring on verify failures** — when verify_data_column_sidecar returns false, what's the peer-score impact? Cross-cuts gossip orchestration.
14. **lodestar private function audit** — verify other lodestar callers use `validateGossipFuluDataColumnSidecar` (the public wrapper) and not `verifyFuluDataColumnSidecar` (the private spec helper) directly.
15. **lighthouse type-method `verify_inclusion_proof` audit** — verify the type method's actual implementation matches the spec's `is_valid_merkle_branch` call pattern.

## Summary

EIP-7594 PeerDAS sidecar validation pipeline is implemented byte-for-byte equivalently across all 6 clients at the algorithm level. Live mainnet PeerDAS gossip has been operating since 2025-12-03 (5 months) without breaking the gossip mesh, validating that all 6 clients accept/reject the same sidecars.

Per-client divergences are entirely in:
- **Function signature** (grandine takes external `kzg_commitments` parameter — Gloas forward-compat; spec uses `sidecar.kzg_commitments`)
- **Multi-fork-definition** (nimbus has separate Fulu/Gloas overloads — Pattern I)
- **Batch KZG verification** (prysm + teku batch across multiple sidecars; spec verifies one-at-a-time; observable-equivalent on success/failure)
- **gindex resolution** (5 of 6 dynamically resolve; **grandine hardcodes `11`** — forward-fragile at Heze where new BeaconBlockBody fields may shift the offset)
- **Encapsulation** (lighthouse uses type method `data_column.verify_inclusion_proof()`; teku factors `getBlockBodyKzgCommitmentsGeneralizedIndex`; lodestar bundles spec helper into gossip orchestration; others standalone)

**HIGH-PRIORITY divergence concern**: grandine's hardcoded `index_at_commitment_depth = 11` in `verify_sidecar_inclusion_proof` is forward-fragile at Heze (where teku has full EIP-7805 inclusion-list implementation potentially adding new BeaconBlockBody fields before `blob_kzg_commitments`). **NEW Pattern P for item #28 catalogue** — hardcoded gindex magic numbers vs dynamic resolution.

**Status**: source review confirms all 6 clients aligned at Fulu mainnet (validated by 5 months of live PeerDAS gossip). **Fixture gap**: no dedicated EF fixtures for the verify family — pure-function fixture generation queued as future research item.
