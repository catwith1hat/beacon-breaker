---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: [19, 58]
eips: [EIP-7732]
splits: []
# main_md_summary: TBD — drafting `verify_execution_payload_envelope` + `on_execution_payload_envelope` Gloas-new fork-choice-time envelope verification audit
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 59: `verify_execution_payload_envelope` + `on_execution_payload_envelope` (Gloas fork-choice envelope verification)

## Summary

> **DRAFT — hypotheses-pending.** Item #19 audited the wiring (every client now has `verify_execution_payload_envelope`); this item audits the **verification predicates** and the fork-choice integration via `on_execution_payload_envelope`.

`SignedExecutionPayloadEnvelope` is the Gloas-new gossip container that delivers the actual execution payload AFTER the beacon block has been processed (EIP-7732 ePBS deferred payload model). The fork-choice handler `on_execution_payload_envelope` is invoked when an envelope arrives (gossip or RPC), and it calls `verify_execution_payload_envelope` to validate:

- The envelope's signature against the builder's pubkey (bound to the bid from item #58).
- The envelope's `payload.parent_hash == bid.parent_block_hash` (binds to the corresponding bid).
- The envelope's blob KZG commitments match the bid's commitments.
- The execution payload's slot, timestamp, prev_randao, etc.

This is the gossip-time / fork-choice-time half of the ePBS lifecycle (item #58 was block-time bid validation). A divergence here changes which envelopes a node accepts as the canonical payload for a given block.

## Question

Pyspec `verify_execution_payload_envelope` and `on_execution_payload_envelope` (Gloas, `vendor/consensus-specs/specs/gloas/beacon-chain.md` and `fork-choice.md`):

```python
def verify_execution_payload_envelope(
    state: BeaconState, signed_envelope: SignedExecutionPayloadEnvelope
) -> bool:
    # TODO[drafting]: paste exact spec body at next iteration.
    # Captures: builder signature verify, parent_hash binding to
    # state.latest_execution_payload_bid, blob commitment match,
    # payload-vs-block consistency.

def on_execution_payload_envelope(
    store: Store, signed_envelope: SignedExecutionPayloadEnvelope
) -> None:
    # TODO[drafting]: paste exact spec body. Captures store-side
    # state lookup, verify_execution_payload_envelope call,
    # state.execution_payload_availability bitvector update,
    # forkchoice store mutation.
```

Open questions:

1. **Builder signature domain** — what domain is used for the envelope signature? Same as the bid (item #58)? Same as a block?
2. **Bid → envelope binding** — exact mechanism. `bid.parent_block_hash == envelope.payload.parent_hash`? Or via `state.latest_execution_payload_bid`?
3. **Blob commitment match** — `bid.blob_kzg_commitments == envelope.blob_kzg_commitments` (deep equality of `List[KZGCommitment, ...]`)?
4. **`state.execution_payload_availability` bitvector update** — when does this fire? On envelope arrival or on the next block? Cross-cut with item #7 H9's `data.index < 2` semantics.
5. **Gossip validation vs fork-choice validation** — separate code paths or shared?
6. **Late-arriving envelope policy** — if the envelope arrives after the next block is already imported, is it accepted (for retrospective execution) or rejected?

## Hypotheses

- **H1.** All six clients implement `verify_execution_payload_envelope` as a pure verification function (no state mutation).
- **H2.** All six verify the envelope signature against `state.builders[bid.builder_index].pubkey` from the corresponding bid.
- **H3.** All six bind envelope ↔ bid via `envelope.payload.parent_hash == state.latest_execution_payload_bid.parent_block_hash`.
- **H4.** All six verify the blob KZG commitments deep-equal the bid's commitments.
- **H5.** All six update `state.execution_payload_availability[slot % SLOTS_PER_HISTORICAL_ROOT]` somewhere in the envelope-arrival flow (not necessarily inside `verify_execution_payload_envelope` itself).
- **H6.** `on_execution_payload_envelope` is wired into the gossip-arrival path AND the RPC-arrival path consistently.
- **H7.** All six handle the "envelope arrives before the corresponding block" case (queue/quarantine) consistently.
- **H8.** All six handle the "envelope arrives after the next block" case (late delivery) consistently — either accepted retrospectively or rejected.
- **H9** *(forward-fragility)*. Per-client envelope-quarantine architecture (cross-cut with item #56 fork-choice DA architecture).

## Findings

> **TBD — drafting.** Each client subsection below is a stub awaiting source review.

### prysm

TBD — drafting. Entry point: `vendor/prysm/beacon-chain/core/gloas/payload.go` + `vendor/prysm/beacon-chain/blockchain/receive_execution_payload_envelope.go`.

### lighthouse

TBD — drafting. Entry points: `vendor/lighthouse/consensus/state_processing/src/envelope_processing.rs:105 verify_execution_payload_envelope` + the fork-choice integration (TBD).

### teku

TBD — drafting. Entry point: `vendor/teku/ethereum/statetransition/.../execution/ExecutionPayloadBidManager` + `vendor/teku/ethereum/statetransition/.../validation/ExecutionPayloadBidGossipValidator.java`.

### nimbus

TBD — drafting. Entry point: `vendor/nimbus/beacon_chain/spec/state_transition_block.nim:1154-1242` (Gloas variant signature takes a `SignedExecutionPayloadEnvelope`).

### lodestar

TBD — drafting. Entry points: `vendor/lodestar/packages/beacon-node/src/chain/{validation,blocks}/verifyExecutionPayloadEnvelope.ts` + `importExecutionPayload.ts`.

### grandine

TBD — drafting. Entry point: `vendor/grandine/transition_functions/src/gloas/execution_payload_processing.rs:36 verify_execution_payload_envelope_signature<P>`.

## Cross-reference table

| Client | `verify_execution_payload_envelope` location | `on_execution_payload_envelope` location | Bid↔envelope binding (H3) | Commitment match (H4) | Availability bitvector update (H5) |
|---|---|---|---|---|---|
| prysm | TBD | TBD | TBD | TBD | TBD |
| lighthouse | TBD | TBD | TBD | TBD | TBD |
| teku | TBD | TBD | TBD | TBD | TBD |
| nimbus | TBD | TBD | TBD | TBD | TBD |
| lodestar | TBD | TBD | TBD | TBD | TBD |
| grandine | TBD | TBD | TBD | TBD | TBD |

## Empirical tests

> **TBD — drafting.** No Gloas EF fork-choice fixtures yet for envelope arrival.

### Suggested fuzzing vectors

- **T1.1 (canonical envelope).** Envelope matching the prior bid (correct signature, parent_hash, commitments). Expected: accepted; `state.execution_payload_availability` bit set.
- **T2.1 (wrong builder signature).** Envelope signed by a different pubkey than the bid's builder. Rejected.
- **T2.2 (parent_hash mismatch).** Envelope's payload.parent_hash differs from bid.parent_block_hash. Rejected.
- **T2.3 (blob commitment mismatch).** Envelope carries different commitments than the bid. Rejected.
- **T2.4 (late envelope).** Envelope arrives after the next block. Verify all six clients agree on whether it's accepted retrospectively.
- **T2.5 (early envelope).** Envelope arrives before the corresponding block. Verify quarantine/buffer behaviour.
- **T2.6 (gossip vs RPC parity).** Same envelope delivered via gossip and via RPC; verify both paths produce identical post-state.

## Conclusion

> **TBD — drafting.** Source review pending across all six clients.

## Cross-cuts

### With item #58 (`process_execution_payload_bid`)

Item #58 produces the bid that this item's envelope must match. Cross-cut on the `parent_block_hash`, `builder_index`, `blob_kzg_commitments` fields.

### With item #19 (process_execution_payload removal)

Item #19 closed the dispatcher wiring. This item is the predicate-level audit.

### With item #7 H9/H10 (`process_attestation` Gloas)

Item #7 H9's `data.index < 2` payload-availability signal depends on `state.execution_payload_availability` — set by this item's envelope-arrival flow. Cross-cut on the bit-set timing.

### With item #56 (Track D fork choice)

Per-client envelope-quarantine architectures parallel item #56's fork-choice DA architecture diversity (Pattern II). High likelihood of distinct per-client architectures here.

## Adjacent untouched

1. **`SignedExecutionPayloadEnvelope` SSZ ser/de cross-client** — new container at Gloas; byte-equivalence for gossip relay.
2. **Envelope gossip topic** — verify topic name + subscription policy cross-client.
3. **Envelope RPC handler** — `executionPayloadEnvelope` by-root / by-range request types.
4. **PTC attestation cross-cut** — payload-availability attestations (item #60) consume `state.execution_payload_availability` bits set by this item.
5. **Late-envelope retrospective execution** — does any client allow envelope arrival N+1 to retroactively execute block N's payload?
6. **Builder slashing** — if a builder publishes two envelopes for the same bid (conflicting commitments?), is it slashable?
