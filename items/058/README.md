---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: [7, 19]
eips: [EIP-7732]
splits: []
# main_md_summary: TBD — drafting `process_execution_payload_bid` Gloas-new block-time bid-validation audit (predicate body, beyond item #19's dispatcher-level coverage)
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 58: `process_execution_payload_bid` (Gloas-new block-time bid validation, EIP-7732 ePBS)

## Summary

> **DRAFT — hypotheses-pending.** Item #19 audited the dispatcher (where `process_execution_payload_bid` is invoked from the per-block flow); this item audits the **function body itself** — the 6+ validation predicates that gate every Gloas-slot block's signed builder bid.

`process_execution_payload_bid(state, block)` is the per-block entry point for EIP-7732 ePBS: it validates the builder's signed bid carried in `block.body.signed_execution_payload_bid` and records the pending payment if the bid is non-zero. The function runs on every Gloas-slot block and has many predicate-rich branches:

- **Self-build special case**: `bid.builder_index == BUILDER_INDEX_SELF_BUILD` ⇒ `bid.value == 0` AND `signature == bls.G2_POINT_AT_INFINITY` (no signature verification).
- **Builder activity**: `is_active_builder(state, builder_index)`.
- **Builder funds**: `can_builder_cover_bid(state, builder_index, value)`.
- **Bid signature verification**: against `state.builders[builder_index].pubkey`.
- **Bid commitments cap**: `len(bid.blob_kzg_commitments) <= get_blob_parameters(epoch).max_blobs_per_block`.
- **Slot/parent consistency**: `bid.slot == block.slot`, `bid.parent_block_hash == state.latest_block_hash`, `bid.parent_block_root == block.parent_root`, `bid.prev_randao == get_randao_mix(...)`.
- **Pending-payment record**: if `bid.value > 0`, write to `state.builder_pending_payments[SLOTS_PER_EPOCH + slot % SLOTS_PER_EPOCH]`.
- **Bid cache**: `state.latest_execution_payload_bid = bid`.

Each predicate is a cross-client divergence axis; the order they fire in determines which error a malformed bid produces.

## Question

Pyspec `process_execution_payload_bid` (Gloas, `vendor/consensus-specs/specs/gloas/beacon-chain.md` "New `process_execution_payload_bid`", roughly `:1424-1474` per the corpus references):

```python
def process_execution_payload_bid(state: BeaconState, block: BeaconBlock) -> None:
    # TODO[drafting]: paste exact spec body at next iteration;
    # capture predicate order, self-build special case,
    # pending-payment write semantics, bid-cache update.
```

Open questions:

1. **Predicate order** — spec ordering vs per-client implementation ordering. Matters for which error is returned to the gossip-validator on malformed bids.
2. **Self-build domain check** — does any client accidentally skip the `value == 0` AND `signature == G2_POINT_AT_INFINITY` conjunction (i.e., accept a self-build with non-zero value)?
3. **`can_builder_cover_bid` formula** — exact comparison: balance ≥ value? balance > value? Inclusive of pending payments?
4. **Pending-payment slot index** — `SLOTS_PER_EPOCH + slot % SLOTS_PER_EPOCH` puts the newer half of the ring buffer. Cross-cut with item #57.
5. **Empty / sentinel bid handling** — what if `state.builders` is empty (pre-builder-deposits)? What if `builder_index` is out of range?

## Hypotheses

- **H1.** All six clients implement the self-build special case identically: `builder_index == BUILDER_INDEX_SELF_BUILD` ⇒ skip `is_active_builder` + `can_builder_cover_bid` + signature verification.
- **H2.** All six enforce `bid.value == 0` when `builder_index == BUILDER_INDEX_SELF_BUILD` (no value transfer on self-builds).
- **H3.** All six enforce `signature == G2_POINT_AT_INFINITY` when self-build.
- **H4.** All six check `is_active_builder(state, builder_index)` against `state.builders[builder_index]`.
- **H5.** All six check builder funds via `can_builder_cover_bid` (formula TBD).
- **H6.** All six verify bid signature against `state.builders[builder_index].pubkey` using the EIP-7732 bid domain.
- **H7.** All six enforce `len(bid.blob_kzg_commitments) <= get_blob_parameters(epoch).max_blobs_per_block`.
- **H8.** All six enforce slot/parent_hash/parent_root/prev_randao consistency with the containing block.
- **H9.** All six write `state.builder_pending_payments[SLOTS_PER_EPOCH + slot % SLOTS_PER_EPOCH]` when `bid.value > 0`.
- **H10.** All six write `state.latest_execution_payload_bid = bid` unconditionally (or with same condition).
- **H11** *(predicate-order observability)*. The set of accepted bids is identical, but the error returned for a malformed bid may differ per client based on predicate order.

## Findings

> **TBD — drafting.** Each client subsection below is a stub awaiting source review.

### prysm

TBD — drafting. Entry point: `vendor/prysm/beacon-chain/core/gloas/bid.go ProcessExecutionPayloadBid`.

### lighthouse

TBD — drafting. Entry point: `vendor/lighthouse/consensus/state_processing/src/per_block_processing.rs:669 process_execution_payload_bid` (per item #19's verification).

### teku

TBD — drafting. Entry point: `vendor/teku/ethereum/statetransition/.../execution/{ExecutionPayloadBidManager, DefaultExecutionPayloadBidManager}.java`.

### nimbus

TBD — drafting. Entry point: `vendor/nimbus/beacon_chain/spec/state_transition_block.nim:1276 process_execution_payload_bid*`.

### lodestar

TBD — drafting. Entry point: `vendor/lodestar/packages/state-transition/src/block/processExecutionPayloadBid.ts`.

### grandine

TBD — drafting. Entry point: `vendor/grandine/transition_functions/src/gloas/block_processing.rs:662 process_execution_payload_bid<P>`.

## Cross-reference table

| Client | `process_execution_payload_bid` location | Self-build branch (H1-H3) | `is_active_builder` (H4) | `can_builder_cover_bid` (H5) | Bid signature verify (H6) | `state.builder_pending_payments` write (H9) |
|---|---|---|---|---|---|---|
| prysm | TBD | TBD | TBD | TBD | TBD | TBD |
| lighthouse | TBD | TBD | TBD | TBD | TBD | TBD |
| teku | TBD | TBD | TBD | TBD | TBD | TBD |
| nimbus | TBD | TBD | TBD | TBD | TBD | TBD |
| lodestar | TBD | TBD | TBD | TBD | TBD | TBD |
| grandine | TBD | TBD | TBD | TBD | TBD | TBD |

## Empirical tests

> **TBD — drafting.** No Gloas EF operations fixtures yet exist for `process_execution_payload_bid`. Suggested fixture set:

### Suggested fuzzing vectors

- **T1.1 (canonical bid).** Active builder, sufficient funds, valid signature, all slot/parent consistency checks pass. Expected: bid accepted, `state.builder_pending_payments` updated, `state.latest_execution_payload_bid` cached. Cross-client `state_root` should match.
- **T1.2 (self-build canonical).** `builder_index == BUILDER_INDEX_SELF_BUILD`, `value == 0`, `signature == G2_POINT_AT_INFINITY`. Expected: accepted, no pending-payment write.
- **T2.1 (self-build with non-zero value).** Self-build but `value > 0`. Expected: rejected by all six.
- **T2.2 (self-build with invalid signature flag).** Self-build but `signature != G2_POINT_AT_INFINITY`. Expected: rejected.
- **T2.3 (inactive builder).** Builder exists but `withdrawable_epoch <= current_epoch`. Expected: rejected.
- **T2.4 (insufficient funds).** Builder exists, active, but balance < value. Expected: rejected.
- **T2.5 (signature mismatch).** Bid signed by wrong key. Expected: rejected.
- **T2.6 (blob limit exceeded).** `len(bid.blob_kzg_commitments) = get_blob_parameters(epoch).max_blobs_per_block + 1`. Expected: rejected.
- **T2.7 (slot mismatch).** `bid.slot != block.slot`. Expected: rejected.
- **T2.8 (parent_block_hash mismatch).** Expected: rejected.
- **T2.9 (predicate-order probe).** Bid that fails multiple predicates; verify all six clients return the same error type (or document the divergence as a forward-fragility risk).

## Conclusion

> **TBD — drafting.** Source review pending across all six clients.

## Cross-cuts

### With item #19 (`process_execution_payload` removal + ePBS restructure)

Item #19 closed at the dispatcher level: every client now calls `process_execution_payload_bid` instead of the removed `process_execution_payload`. This item is the body audit.

### With item #57 (`process_builder_pending_payments`)

This item writes the `BuilderPendingPayment` entries that item #57 consumes at epoch boundary. Producer/consumer pair.

### With item #7 H10 (`process_attestation` builder-payment weight)

Item #7 H10 increments `state.builder_pending_payments[slot_idx].weight` from same-slot attestations. This item's write to `state.builder_pending_payments[slot_idx]` happens FIRST (block-time, on bid acceptance); item #7's weight increment happens AFTER (per-attestation in the same block + later blocks). The two operations interleave on shared state.

### With item #15 H9 (CL local `requestsHash`)

The bid's blob_kzg_commitments are passed to the EL via `engine_newPayloadV5`. Cross-cut with the V5 schema.

## Adjacent untouched

1. **`is_active_builder` standalone audit** — small but used by this item, the builder-exit branch of item #6, and item #14's builder-routing.
2. **`can_builder_cover_bid` standalone audit** — exact formula matters for the dust attack surface.
3. **EIP-7732 bid signature domain** — verify domain constant + signing-root construction cross-client.
4. **`BUILDER_INDEX_SELF_BUILD` constant value** — verify all six configs agree.
5. **Bid replay protection** — what prevents the same signed bid from being included in two blocks?
6. **Predicate-order error contract** — cross-client test verifying error-type compatibility for the gossip layer.
