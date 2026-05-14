---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: [7, 13, 19, 59]
eips: [EIP-7732]
splits: []
# main_md_summary: TBD — drafting Payload Timeliness Committee (PTC) selection + `is_valid_indexed_payload_attestation` Gloas-new audit
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 60: Payload Timeliness Committee (PTC) selection + `is_valid_indexed_payload_attestation`

## Summary

> **DRAFT — hypotheses-pending.** PTC is brand-new at Gloas: a per-slot committee that votes on whether the builder's execution payload arrived in time. PTC attestations flow through the new `process_payload_attestation` dispatcher (item #13 H10 wiring) and are validated by `is_valid_indexed_payload_attestation`. Lighthouse had a Pattern M gap here in the prior recheck (now closed); this audit covers the predicate body, the PTC selection algorithm, and the attestation aggregation semantics across all six clients.

The Payload Timeliness Committee (PTC) is selected per slot from the same beacon committee pool used for regular attestations, but with a separate weighting (`compute_ptc` — sibling of `compute_proposer_indices` and `compute_balance_weighted_selection`). PTC members produce `PayloadAttestation` messages with a 3-valued payload-status enum, aggregated into `IndexedPayloadAttestation` containers. Validation includes:

- PTC membership check (validator index in `state.ptc_window[...]`).
- Status enum value `∈ {ABSENT, PRESENT, WITHHELD}` (or equivalent).
- BLS aggregate signature against PTC pubkeys.
- Slot binding.

## Question

Pyspec PTC and `is_valid_indexed_payload_attestation` (Gloas, `vendor/consensus-specs/specs/gloas/beacon-chain.md`):

```python
# PTC selection
def get_ptc(state: BeaconState, slot: Slot) -> Sequence[ValidatorIndex]:
    # TODO[drafting]: paste exact spec body.
    # Captures: committee sampling, weighting (compute_ptc /
    # compute_balance_weighted_selection), seed derivation,
    # PTC_SIZE constant (or formula).

# Indexed-attestation validation
def is_valid_indexed_payload_attestation(
    state: BeaconState, indexed_attestation: IndexedPayloadAttestation
) -> bool:
    # TODO[drafting]: paste exact spec body.
    # Captures: indices sorted + unique, BLS aggregate signature
    # against state.validators[i].pubkey for i in indices,
    # PayloadAttestationData fields validation.
```

Open questions:

1. **`compute_ptc` algorithm** — uses `compute_balance_weighted_selection`? Different weighting from proposer indices?
2. **PTC size** — constant or formula? Per-fork value?
3. **PTC window storage** — `state.ptc_window: HashArray[..., List[ValidatorIndex]]`? Same shape as proposer lookahead?
4. **PTC seed** — derived from `state.randao_mixes[...]` like committees? Or different?
5. **Status enum values** — exact integers for ABSENT/PRESENT/WITHHELD; cross-client mapping.
6. **Signature domain** — `DOMAIN_PTC_ATTESTER`? Separate from `DOMAIN_BEACON_ATTESTER`?
7. **PTC attestation aggregation** — multiple status values per attestation, or one per validator?

## Hypotheses

- **H1.** All six clients implement `compute_ptc` using `compute_balance_weighted_selection` (same primitive as proposer-indices computation).
- **H2.** All six derive the PTC seed from `state.randao_mixes` consistently.
- **H3.** All six store the PTC window in `state.ptc_window: HashArray[Limit (MIN_SEED_LOOKAHEAD + 1) * SLOTS_PER_EPOCH, ...]` (or equivalent).
- **H4.** All six update `state.ptc_window` at epoch boundary via `process_ptc_window` (Gloas-new epoch helper).
- **H5.** All six implement `is_valid_indexed_payload_attestation`:
  - sorted + unique indices check
  - BLS aggregate over `state.validators[i].pubkey for i in indices`
  - signature domain `DOMAIN_PTC_ATTESTER` (TBD)
  - data slot/parent_block_root validation
- **H6.** All six implement the PayloadStatus enum with values matching the spec (TBD: ABSENT=0, PRESENT=1, WITHHELD=2? — verify).
- **H7.** All six handle PTC attestations from validators NOT in the current PTC by rejecting at the indices-validity check.
- **H8** *(forward-fragility)*. Per-client status enum representation (Go iota, Rust enum, Java enum, Nim enum, TS const, Rust enum) — verify consistent integer mapping.

## Findings

> **TBD — drafting.** Each client subsection below is a stub awaiting source review.

### prysm

TBD — drafting. Entry points: `vendor/prysm/beacon-chain/core/gloas/payload_attestation.go`.

### lighthouse

TBD — drafting. Entry points: `vendor/lighthouse/consensus/state_processing/src/per_block_processing/is_valid_indexed_payload_attestation.rs:6` + `verify_payload_attestation.rs`.

### teku

TBD — drafting. Entry points: `vendor/teku/ethereum/spec/.../gloas/helpers/BeaconStateAccessorsGloas.java` + PayloadAttestation classes (TBD).

### nimbus

TBD — drafting. Entry points: `vendor/nimbus/beacon_chain/spec/beaconstate.nim` `get_ptc` + `get_indexed_payload_attestation` + `state_transition_block.nim:749 process_payload_attestation*`.

### lodestar

TBD — drafting. Entry points: `vendor/lodestar/packages/state-transition/src/block/processPayloadAttestation.ts` (TBD path).

### grandine

TBD — drafting. Entry point: `vendor/grandine/transition_functions/src/gloas/block_processing.rs:1132 process_payload_attestation` + PTC selection in `helper_functions/`.

## Cross-reference table

| Client | `compute_ptc` location | `is_valid_indexed_payload_attestation` location | `state.ptc_window` access (H3) | Status enum representation (H6) | Sig domain (H5) |
|---|---|---|---|---|---|
| prysm | TBD | TBD | TBD | TBD | TBD |
| lighthouse | TBD | TBD | TBD | TBD | TBD |
| teku | TBD | TBD | TBD | TBD | TBD |
| nimbus | TBD | TBD | TBD | TBD | TBD |
| lodestar | TBD | TBD | TBD | TBD | TBD |
| grandine | TBD | TBD | TBD | TBD | TBD |

## Empirical tests

> **TBD — drafting.** No Gloas EF operations fixtures yet for PTC. Suggested fixture set:

### Suggested fuzzing vectors

- **T1.1 (canonical PTC attestation).** Validators selected for the current slot's PTC sign a PayloadAttestation with `status = PRESENT` and the correct block-root binding. Expected: `is_valid_indexed_payload_attestation` returns true; `state.execution_payload_availability` bit set (cross-cut item #59).
- **T1.2 (WITHHELD status).** Same setup, `status = WITHHELD`. Expected: accepted; availability bit cleared/unchanged per spec semantics.
- **T2.1 (non-PTC member attests).** Validator not in `state.ptc_window[slot_offset]` signs a PTC attestation. Expected: rejected at indices-validity check.
- **T2.2 (signature mismatch).** Aggregate signature doesn't match the indices' pubkeys. Expected: rejected.
- **T2.3 (out-of-order indices).** Indices not sorted ascending. Expected: rejected per spec invariant.
- **T2.4 (duplicate indices).** Same index twice. Expected: rejected.
- **T2.5 (status enum out of range).** `status = 3` (invalid). Expected: rejected (or normalized — verify cross-client).
- **T2.6 (PTC size boundary).** Empty PTC (no validators selected — spec edge case). All six clients handle identically?

## Conclusion

> **TBD — drafting.** Source review pending across all six clients.

## Cross-cuts

### With item #13 H10 (`process_operations` Gloas dispatcher)

Item #13 H10 closed the dispatcher: `process_operations` at Gloas dispatches `for_ops(body.payload_attestations, process_payload_attestation)`. This item is the predicate-level audit of `process_payload_attestation` (the per-element handler).

### With item #59 (envelope verification)

Both update `state.execution_payload_availability`. PTC attestations set bits; envelope verification reads bits. Sequencing: bid → envelope arrives → availability bit set → PTC attestations from members vote on what they observed. Cross-cut on the bit-set ordering.

### With item #7 H9 (`process_attestation` `data.index < 2`)

Item #7 H9's `data.index < 2` payload-availability signal in regular attestations is parallel to (but distinct from) PTC attestations. PTC is the dedicated committee; regular attestations also vote indirectly via the `data.index` field. Two-channel availability voting.

### With `process_ptc_window` (Gloas-new epoch helper)

Sibling epoch helper that rotates `state.ptc_window` (analog to `process_builder_pending_payments` rotating `state.builder_pending_payments`). Audit-worthy as its own item; cross-cut here on the read side.

## Adjacent untouched

1. **`process_ptc_window`** (Gloas-new epoch helper) — sister audit.
2. **`PayloadAttestationData` SSZ container** — fields TBD.
3. **`IndexedPayloadAttestation` SSZ container** — aggregation shape.
4. **PTC attestation gossip topic** — `payload_attestation` topic; subscription policy.
5. **PTC duty publication** — when does the BN tell its VC "you are in PTC for slot N"? VC-side cross-client audit.
6. **PTC vs regular attestation aggregation** — single-validator-in-both case (same validator selected for both regular committee and PTC for the same slot).
7. **`compute_balance_weighted_selection` triple-call cross-cut** — `compute_proposer_indices`, `compute_ptc`, and item #27's sync-committee selection all use this primitive. Cross-cut audit on the helper.
