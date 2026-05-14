# Demo: empirical reproduction of lodestar's `should_extend_payload` divergence

## What this shows

`spec_vs_lodestar.py` is a standalone Python script (no spec or lodestar
imports) that implements **two** versions of Gloas's `should_extend_payload`
side-by-side:

1. **Spec semantics**, per `vendor/consensus-specs/specs/gloas/fork-choice.md:398-409`
   — first branch is `is_payload_timely(store, root) AND is_payload_data_available(store, root)`.
   The store carries two separate vote arrays (`payload_timeliness_vote`,
   `payload_data_availability_vote`) populated from the `PayloadAttestationData`'s
   two booleans (`payload_present`, `blob_data_available`).

2. **Lodestar semantics**, per `vendor/lodestar/packages/fork-choice/src/protoArray/protoArray.ts:715-749`
   and `:638` — first branch is `isPayloadTimely(blockRoot)` alone.
   The store carries a single `ptcVotes: Map<RootHex, BitArray>` populated by
   `notifyPtcMessages(blockRoot, ptcIndices, payloadPresent: boolean)`. The
   `blob_data_available` bit of the SSZ-decoded `PayloadAttestationData` is
   discarded at all three call sites in `packages/beacon-node/src`.

The script runs three scenarios:

- **T1 (timely-only + adversarial proposer boost)** — PTC votes 300 (>256)
  for payload_present, 10 (<256) for blob_data_available. Proposer-boost is
  set and points to a child of the candidate whose `parent_payload_status`
  is EMPTY.
- **T2 (both-true)** — same proposer-boost configuration, but PTC votes
  300 for BOTH bits.
- **T3 (timely-only, no proposer boost)** — same vote distribution as T1,
  but `proposer_boost_root = ZERO_ROOT`.

## Running

```bash
python3 spec_vs_lodestar.py
```

## Result

```
T1 (timely-only + adversarial proposer boost):  DIVERGE ✗
  spec.should_extend_payload     = False
  lodestar.should_extend_payload = True

T2 (both-true):                                  MATCH ✓
T3 (timely-only, no proposer boost):             MATCH ✓
```

The divergence triggers **only** when both:
- PTC reaches timeliness threshold but NOT data-availability threshold; AND
- proposer-boost is set to a block adversarial to the candidate (child of
  the candidate, parent's payload_status is EMPTY).

Both other scenarios produce identical output across spec and lodestar.

## Implications

The fork-choice tiebreaker `get_payload_status_tiebreaker`
(`fork-choice.md:411-426`) for a previous-slot FULL/EMPTY node returns:

- **2 (FULL)** when `should_extend_payload(node.root)` is True.
- **0 (EMPTY)** when False.

Under T1's configuration, lodestar's `get_payload_status_tiebreaker` returns
2 (FULL), while prysm/lighthouse/teku/grandine return 0 (EMPTY). The two
groups pick different heads — a fork-choice head-selection divergence.

This differs from item #67 (state-transition divergence producing block-import
rejection): #77's divergence does not reject blocks. Both branches import
cleanly. But LMD-GHOST votes flow to different heads, potentially preventing
finalization on contested slots.

## Mainnet reachability

Reachable scenario on Gloas-active mainnet:

1. Builder X distributes a payload to most of the network. PTC majority
   votes `payload_present=True`.
2. Blob columns / KZG samples for the same block lag the payload (network
   partition on the column-sampling layer, or a deliberate withholding
   attack by a builder trying to manipulate the FULL/EMPTY tiebreak). PTC
   majority does NOT vote `blob_data_available=True`.
3. The proposer for slot N+1 receives proposer-boost in the first 4 seconds
   of its slot. The proposer extends from block X (so `B.parent_root == X`),
   and the previous slot's parent_payload_status for the proposer's chain is
   EMPTY.
4. At the fork-choice tiebreak for the X-FULL vs X-EMPTY pair, lodestar
   prefers FULL while the other 4 clients prefer EMPTY.

Realistic on a Gloas-active network with any DA stress (which is expected
during the early Glamsterdam ramp-up).

## Mitigation possibilities

Option A (lodestar implements the missing half):
1. Widen `notifyPtcMessages` signature to
   `(blockRoot, ptcIndices, payloadPresent, blobDataAvailable)`.
2. Add a `payloadDataAvailabilityVotes: Map<RootHex, BitArray>` mirroring
   `ptcVotes`.
3. Add an `isPayloadDataAvailable(blockRoot)` predicate.
4. Update `shouldExtendPayload` condition 1 to
   `if (this.isPayloadTimely(blockRoot) && this.isPayloadDataAvailable(blockRoot)) return true;`.
5. Update the three call sites in `packages/beacon-node/src` to pass
   `payloadAttestation.data.blobDataAvailable`.

3-file fork-choice change + 3 call-site updates. Well-scoped.

Option B (spec spec-tests add a fixture exercising T1's configuration):
Force the discrepancy at fixture-gen time. Would catch lodestar's omission
on the EF CI.

Option C (devnet end-to-end test): drive PTC voters to attest
`(payload_present=True, blob_data_available=False)` and observe head selection
per-client.

The audit's recommendation (per `items/077/README.md`) is Option A as the
immediate fix, with Option B as the durable backstop.
