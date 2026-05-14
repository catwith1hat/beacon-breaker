---
status: fuzzed
impact: mainnet-glamsterdam
last_update: 2026-05-14
builds_on: [56, 60, 67, 76]
eips: [EIP-7732]
splits: [lodestar]
# main_md_summary: lodestar fork-choice drops the `blob_data_available` half of the PTC vote — `notifyPtcMessages` accepts only `payloadPresent`, no `payloadDataAvailabilityVote` map exists, and `shouldExtendPayload` checks `isPayloadTimely` alone instead of spec's `is_payload_timely AND is_payload_data_available`; mainnet-reachable on Gloas-active networks when PTC majority votes payload_present=True but blob_data_available=False
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 77: Fork-choice `should_extend_payload` — lodestar drops the `is_payload_data_available` conjunct

## Summary

Gloas's `should_extend_payload` decides whether the fork-choice tiebreaker between a FULL and an EMPTY payload-status node from the previous slot prefers FULL. Spec at `vendor/consensus-specs/specs/gloas/fork-choice.md:398-409` requires the payload to be **both** timely (majority of PTC voted `payload_present=True`) **and** data-available (majority of PTC voted `blob_data_available=True`):

```python
def should_extend_payload(store: Store, root: Root) -> bool:
    if not is_payload_verified(store, root):
        return False
    proposer_root = store.proposer_boost_root
    return (
        (is_payload_timely(store, root) and is_payload_data_available(store, root))
        or proposer_root == Root()
        or store.blocks[proposer_root].parent_root != root
        or is_parent_node_full(store, store.blocks[proposer_root])
    )
```

The `PayloadAttestationData` SSZ container carries **two** booleans (`beacon-chain.md:240-244`): `payload_present` and `blob_data_available`. The store keeps **two** separate vote dictionaries (`fork-choice.md:186-190`): `payload_timeliness_vote` and `payload_data_availability_vote`. `notify_ptc_messages` populates **both** (`fork-choice.md:996-1000`).

**Four of six clients (prysm, lighthouse, teku, grandine) carry both votes through fork-choice and AND them in `should_extend_payload`.** Nimbus has not yet implemented `should_extend_payload` in its fork-choice subsystem (its `payload_attestation_pool` aggregates the `blob_data_available` bit but no consumer exists; Gloas fork-choice integration is incomplete).

**Lodestar deviates** at `vendor/lodestar/packages/fork-choice/src/forkChoice/forkChoice.ts:937` and `vendor/lodestar/packages/fork-choice/src/protoArray/protoArray.ts:72,514,638,715-749`:

- `notifyPtcMessages(blockRoot, ptcIndices, payloadPresent: boolean)` — signature accepts only `payloadPresent`. The `blob_data_available` bit decoded from the `PayloadAttestationData` SSZ container at `vendor/lodestar/packages/types/src/gloas/sszTypes.ts:91` is never threaded into fork-choice.
- `private ptcVotes = new Map<RootHex, BitArray>()` — **one** vote map, not two. No `payloadDataAvailabilityVote` analog.
- `isPayloadTimely(blockRoot)` — popcounts the single map.
- `shouldExtendPayload(blockRoot, proposerBoostRoot)` returns `true` from condition 1 as soon as `isPayloadTimely(blockRoot)` is true, with **no** `is_payload_data_available` check. The function's docstring (`protoArray.ts:702-714`) explicitly enumerates conditions 1-4 with condition 1 = "Payload is timely" (singular) — confirming the omission is by design, not a typo.

All three call sites of `notifyPtcMessages` in lodestar (`importBlock.ts:276-280`, `gossipHandlers.ts:1154-1158`, `pool/index.ts:276-280`) pass `payloadAttestation.data.payloadPresent` only, discarding `payloadAttestation.data.blobDataAvailable`.

**Consequence**: when the PTC reaches majority on `payload_present=True` but **does not** reach majority on `blob_data_available=True`, lodestar's `shouldExtendPayload` returns true on the first branch (treats the payload as extendable / FULL-preferring), while the other 4 spec-conformant clients fall through to the proposer-boost branches. If proposer-boost is set, points to a block whose parent is the candidate root, and the parent is not FULL, the other 4 clients return false. Lodestar returns true. The fork-choice tiebreaker `get_payload_status_tiebreaker` returns 2 (FULL) on lodestar vs 0 (EMPTY) on the others — different head.

## Question

Spec at `vendor/consensus-specs/specs/gloas/fork-choice.md`:

**`PayloadAttestationData`** (`beacon-chain.md:237-245`):

```python
class PayloadAttestationData(Container):
    beacon_block_root: Root
    slot: Slot
    payload_present: boolean
    blob_data_available: boolean
```

**Store fields** (`fork-choice.md:163-191`):

```python
payload_timeliness_vote: Dict[Root, list[Optional[boolean]]] = field(default_factory=dict)
payload_data_availability_vote: Dict[Root, list[Optional[boolean]]] = field(default_factory=dict)
```

**Thresholds** (`fork-choice.md:72-73`):

```
PAYLOAD_TIMELY_THRESHOLD            = PTC_SIZE // 2 = 256
DATA_AVAILABILITY_TIMELY_THRESHOLD  = PTC_SIZE // 2 = 256
```

**`on_payload_attestation_message`** (`fork-choice.md:953-1003`):

```python
payload_timeliness_vote = store.payload_timeliness_vote[data.beacon_block_root]
payload_data_availability_vote = store.payload_data_availability_vote[data.beacon_block_root]
if payload_timeliness_vote[ptc_index] is None:
    payload_timeliness_vote[ptc_index] = data.payload_present
    payload_data_availability_vote[ptc_index] = data.blob_data_available
```

**`is_payload_data_available`** (`fork-choice.md:285-302`):

```python
def is_payload_data_available(store: Store, root: Root) -> bool:
    assert root in store.payload_data_availability_vote
    if not is_payload_verified(store, root):
        return False
    votes = store.payload_data_availability_vote[root]
    return sum(vote is True for vote in votes) > DATA_AVAILABILITY_TIMELY_THRESHOLD
```

**`should_extend_payload`** (`fork-choice.md:398-409`): the conjunction quoted above.

Open questions:

1. **Two votes or one?** Does each client maintain a separate `payload_data_availability_vote` (mirroring `payload_timeliness_vote`)?
2. **Threading.** Does the wire-decoded `PayloadAttestationData.blob_data_available` reach fork-choice in each client?
3. **`should_extend_payload` first branch.** Is the AND-conjunct present per-client?
4. **Threshold strictness.** Both thresholds use `>` (strict greater); per-client?
5. **Constant value.** `DATA_AVAILABILITY_TIMELY_THRESHOLD = PTC_SIZE // 2 = 256` per-client?

## Hypotheses

- **H1.** Each client decodes `PayloadAttestationData.blob_data_available` from the wire (SSZ + JSON paths).
- **H2.** Each client maintains a `payload_data_availability_vote` (or equivalent BitVector) in fork-choice store / proto-array.
- **H3.** Each client's `on_payload_attestation_message` / `notify_ptc_messages` writes both `payload_present` and `blob_data_available` into the respective vote arrays.
- **H4.** Each client's `should_extend_payload` first branch is `is_payload_timely AND is_payload_data_available`.
- **H5.** Each client uses `DATA_AVAILABILITY_TIMELY_THRESHOLD = PTC_SIZE // 2 = 256` and strict `>` comparison.
- **H6** *(divergence)*. Lodestar implements H1 (decodes `blobDataAvailable` from SSZ) but fails H2, H3, H4 — drops the bit at fork-choice ingestion and omits the AND-conjunct in `shouldExtendPayload`.

## Findings

### prysm

Fork-choice in `vendor/prysm/beacon-chain/forkchoice/doubly-linked-tree/`. Notable:

- `gloas.go:253-262` — `shouldExtendPayload`:
  ```go
  func (s *Store) shouldExtendPayload(fn *PayloadNode) bool {
      // ...
      if n.payloadAvailabilityVote.Count() > fieldparams.PTCSize/2 && n.payloadDataAvailabilityVote.Count() > fieldparams.PTCSize/2 {
          return true
      }
      // ... proposer-boost branches ...
  }
  ```
  Both vote bitvectors are AND-ed at line 258 ✓.
- `gloas.go:414-425` — `SetPTCVote(root, ptcIdx, payloadPresent, blobDataAvailable bool)`:
  ```go
  func (f *ForkChoice) SetPTCVote(root [32]byte, ptcIdx uint64, payloadPresent, blobDataAvailable bool) {
      // ...
      if payloadPresent {
          n.node.setPayloadAvailabilityVote(ptcIdx)
      }
      if blobDataAvailable {
          n.node.setPayloadDataAvailabilityVote(ptcIdx)
      }
  }
  ```
  Both bits threaded through ✓.
- `gloas.go:428-433` — `setPayloadAvailabilityVote` / `setPayloadDataAvailabilityVote` — separate BitVectors per node ✓.

Threshold check uses strict `>` against `fieldparams.PTCSize/2 = 256` ✓.

### lighthouse

Fork-choice in `vendor/lighthouse/consensus/proto_array/src/proto_array.rs`. Notable:

- `proto_array.rs:146-157` — per-node fields:
  ```rust
  pub payload_timeliness_votes: BitVector<U512>,
  pub payload_data_availability_votes: BitVector<U512>,
  ```
  Separate bitvectors ✓.
- `proto_array.rs:209-220` — `is_payload_data_available`:
  ```rust
  pub fn is_payload_data_available<E: EthSpec>(&self) -> bool {
      // ...
      node.payload_data_availability_votes.num_set_bits()
          > E::data_availability_timely_threshold()
  }
  ```
  Strict `>` threshold ✓.
- `proto_array.rs:1534-1538` — `should_extend_payload` first branch:
  ```rust
  Ok(
      (proto_node.is_payload_timely::<E>() && proto_node.is_payload_data_available::<E>())
          || proposer_boost_parent_root != fc_node.root
          || proposer_boost_node.is_parent_node_full(),
  )
  ```
  AND-conjunct present ✓ (the `proposer_root == Root()` spec branch is folded into the prior `proposer_boost_node` lookup path).

### teku

Fork-choice in `vendor/teku/storage/src/main/java/tech/pegasys/teku/storage/protoarray/`. Notable:

- `PtcVoteTracker.java:46-67` — `recordVote(blockRoot, validatorIndex, payloadPresent, blobDataAvailable)` — both bits threaded ✓.
- `ForkChoiceModelGloas.java:403-428` — `shouldExtendPayload`:
  ```java
  private boolean shouldExtendPayload(
      final long blockNodeIndex, final Bytes32 blockRoot, ...) {
    // ...
    if (isPayloadTimely(blockNodeIndex, blockRoot)
        && isPayloadDataAvailable(blockNodeIndex, blockRoot)) {
      return true;
    }
    // proposer-boost branches
  }
  ```
  AND-conjunct present at line 422 ✓.
- `ForkChoiceModelGloas.java:453-470` — `isPayloadDataAvailable` exists as a separate predicate ✓.
- `ForkChoiceModelGloas.java:608-610` — `notifyPtcMessage` calls `ptcVoteTracker.recordVote(blockRoot, validatorIndex, payloadPresent, blobDataAvailable)` ✓.

### nimbus

Fork-choice in `vendor/nimbus/beacon_chain/fork_choice/`. Grep for `shouldExtendPayload`, `isPayloadTimely`, `isPayloadDataAvailable`, `payload_data_availability`, `blob_data_available` in `proto_array.nim`, `fork_choice.nim`, `fork_choice_types.nim` returns no hits — **Gloas fork-choice integration is incomplete in nimbus**.

The `PayloadAttestationData.blob_data_available` field is decoded at `vendor/nimbus/beacon_chain/spec/datatypes/gloas.nim:153` and reaches `vendor/nimbus/beacon_chain/consensus_object_pools/payload_attestation_pool.nim:59,77` (for pool dedup/aggregation), but no fork-choice consumer exists.

Validator-side code at `vendor/nimbus/beacon_chain/validators/block_payloads.nim:380` comments `# - If \`should_extend_payload(store, parent_root)\`:` but the implementation appears to be a stub. Not directly comparable to lodestar's divergence; this is incompleteness, not divergence.

Once nimbus implements Gloas fork-choice fully, this audit should be re-run.

### lodestar

**Confirmed divergent on H2, H3, H4** at `vendor/lodestar/packages/fork-choice/src/protoArray/protoArray.ts`. Notable:

- `protoArray.ts:23` — `const PAYLOAD_TIMELY_THRESHOLD = Math.floor(PTC_SIZE / 2);` (256). No `DATA_AVAILABILITY_TIMELY_THRESHOLD` defined — there is nothing to threshold-check.
- `protoArray.ts:72` — single vote map:
  ```typescript
  private ptcVotes = new Map<RootHex, BitArray>();
  ```
  Only one BitArray per block root. No `payloadDataAvailabilityVotes` analog.
- `protoArray.ts:514` — initialization on block insertion:
  ```typescript
  this.ptcVotes.set(block.blockRoot, BitArray.fromBitLen(PTC_SIZE));
  ```
  Single BitArray.
- `protoArray.ts:636-650` — `notifyPtcMessages`:
  ```typescript
  notifyPtcMessages(blockRoot: RootHex, ptcIndices: number[], payloadPresent: boolean): void {
      const votes = this.ptcVotes.get(blockRoot);
      // ...
      for (const ptcIndex of ptcIndices) {
          votes.set(ptcIndex, payloadPresent);
      }
  }
  ```
  Signature carries `payloadPresent: boolean` only — no `blobDataAvailable` parameter ✗.
- `protoArray.ts:675-684` — `isPayloadTimely`:
  ```typescript
  isPayloadTimely(blockRoot: RootHex): boolean {
      const votes = this.ptcVotes.get(blockRoot);
      if (votes === undefined) return false;
      if (!this.hasPayload(blockRoot)) return false;
      const yesVotes = bitCount(votes.uint8Array);
      return yesVotes > PAYLOAD_TIMELY_THRESHOLD;
  }
  ```
  Counts the single vote map ✓ for the timely half — but no `isPayloadDataAvailable` companion.
- `protoArray.ts:702-749` — `shouldExtendPayload`:
  ```typescript
  /**
   * Returns true if payload is verified (FULL variant exists) AND:
   * 1. Payload is timely, OR
   * 2. No proposer boost root (empty/zero hash), OR
   * 3. Proposer boost root's parent is not this block, OR
   * 4. Proposer boost root extends FULL parent
   */
  shouldExtendPayload(blockRoot: RootHex, proposerBoostRoot: RootHex | null): boolean {
      if (!this.hasPayload(blockRoot)) return false;
      // Condition 1: Payload is timely
      if (this.isPayloadTimely(blockRoot)) return true;       // <-- missing AND data-available
      // Condition 2: No proposer boost root
      if (proposerBoostRoot === null || proposerBoostRoot === HEX_ZERO_HASH) return true;
      // ...
  }
  ```
  Condition 1 is `isPayloadTimely` alone. Docstring at lines 706-711 confirms the developer's mental model is 4 conditions, not 4 conditions where condition 1 is itself a 2-way AND. Spec requires `is_payload_timely AND is_payload_data_available` ✗.

All three call sites of `notifyPtcMessages`:

- `vendor/lodestar/packages/beacon-node/src/chain/blocks/importBlock.ts:276-280`:
  ```typescript
  this.forkChoice.notifyPtcMessages(
      toRootHex(payloadAttestation.data.beaconBlockRoot),
      ptcIndices,
      payloadAttestation.data.payloadPresent
  );
  ```
- `vendor/lodestar/packages/beacon-node/src/network/processor/gossipHandlers.ts:1154-1158`:
  ```typescript
  chain.forkChoice.notifyPtcMessages(
      toRootHex(payloadAttestationMessage.data.beaconBlockRoot),
      [validationResult.validatorCommitteeIndex],
      payloadAttestationMessage.data.payloadPresent
  );
  ```
- `vendor/lodestar/packages/beacon-node/src/api/impl/beacon/pool/index.ts:276-280`:
  ```typescript
  chain.forkChoice.notifyPtcMessages(
      toRootHex(payloadAttestationMessage.data.beaconBlockRoot),
      [validatorCommitteeIndex],
      payloadAttestationMessage.data.payloadPresent
  );
  ```

All three drop `payloadAttestation.data.blobDataAvailable` on the floor. The SSZ container is decoded faithfully (`packages/types/src/gloas/sszTypes.ts:86-93` defines both fields), so this is not a wire-decoding issue — it is a fork-choice ingestion / storage issue.

### grandine

Fork-choice in `vendor/grandine/fork_choice_store/src/store.rs`. Notable:

- `store.rs:884-889` — `should_extend_payload`:
  ```rust
  if proposer_root.is_zero()
      || (self.is_payload_timely(block_root) && self.is_payload_data_available(block_root))
  {
      return true;
  }
  ```
  AND-conjunct present at line 886 ✓.
- `store.rs:934-949` — `is_payload_data_available`:
  ```rust
  fn is_payload_data_available(&self, block_root: H256) -> bool {
      let Some(payload_data_availability_vote) = self.payload_data_availability_vote.get(&block_root) else {
          return false;
      };
      if !self.is_payload_verified(block_root) { return false; }
      let vote_count: u64 = payload_data_availability_vote.count_ones().try_into()...;
      vote_count > PayloadTimelyThreshold::<P>::U64
  }
  ```
  Separate vote dict; strict `>` ✓.

Grandine uses `PayloadTimelyThreshold::<P>::U64` as the threshold constant for the data-availability check as well. Spec lists both thresholds as `PTC_SIZE // 2 = 256` (`fork-choice.md:72-73`), so the constants are numerically equal — grandine's reuse is spec-conformant in value, though formally the spec defines two named constants. Note for potential follow-up if either threshold is ever changed independently.

## Cross-reference table

| Client | `blob_data_available` reaches FC ingestion (H1+H3) | Separate `payload_data_availability_vote` storage (H2) | `should_extend_payload` first branch is `timely AND data_available` (H4) | Threshold strict `>` against 256 (H5) |
|---|---|---|---|---|
| prysm | ✓ `SetPTCVote(.., payloadPresent, blobDataAvailable)` (`gloas.go:414`) | ✓ separate `payloadDataAvailabilityVote` BitVector per Node (`gloas.go:433`) | ✓ `n.payloadAvailabilityVote.Count() > T/2 && n.payloadDataAvailabilityVote.Count() > T/2` (`gloas.go:258`) | ✓ strict `>` against `fieldparams.PTCSize/2` |
| lighthouse | ✓ both votes recorded per-node (`proto_array.rs:146-157`) | ✓ `payload_data_availability_votes: BitVector<U512>` (`proto_array.rs:157`) | ✓ `is_payload_timely::<E>() && is_payload_data_available::<E>()` (`proto_array.rs:1535`) | ✓ `> E::data_availability_timely_threshold()` (`proto_array.rs:219-220`) |
| teku | ✓ `recordVote(.., payloadPresent, blobDataAvailable)` (`PtcVoteTracker.java:46-67`) | ✓ tracker carries both bits | ✓ `isPayloadTimely(..) && isPayloadDataAvailable(..)` (`ForkChoiceModelGloas.java:422`) | ✓ strict `>` |
| nimbus | partial — pool only (`payload_attestation_pool.nim:59,77`); no FC consumer | ✗ **not implemented in fork-choice** (Gloas FC integration incomplete) | ✗ **not implemented** | n/a |
| **lodestar** | **✗ dropped at FC boundary** — `notifyPtcMessages(.., payloadPresent: boolean)` only (`forkChoice.ts:937`, `protoArray.ts:638`) | **✗ single `ptcVotes` map only** (`protoArray.ts:72`); no DA-vote storage | **✗ first branch is `isPayloadTimely(..)` alone** (`protoArray.ts:721`); docstring confirms intentional 4-condition model | n/a (no DA threshold defined) |
| grandine | ✓ both votes tracked per-block (`store.rs:934`) | ✓ `payload_data_availability_vote: HashMap<..>` | ✓ `is_payload_timely(..) && is_payload_data_available(..)` (`store.rs:886`) | ✓ strict `>` against `PayloadTimelyThreshold::U64` (256) |

**H1 ✓ for prysm/lighthouse/teku/grandine, partial for nimbus, ✗ for lodestar at FC ingestion (decoded but not threaded).**
**H2, H3, H4 ✗ for lodestar.**
**Nimbus is incomplete (not divergent — Gloas FC unimplemented).**

## Empirical tests

### Standalone Python harness — DIVERGENCE REPRODUCED

`items/077/demo/spec_vs_lodestar.py` implements `should_extend_payload` in two ways inline (no spec deps):

1. **Spec semantics**, per `fork-choice.md:398-409`: stores both `payload_timeliness_vote` and `payload_data_availability_vote`; first branch is `is_payload_timely AND is_payload_data_available`.
2. **Lodestar semantics**, per `protoArray.ts:715-749` + `notifyPtcMessages(.., payloadPresent)`: stores a single `ptc_votes` array (the `payloadPresent` bits only); first branch is `is_payload_timely` alone.

Three scenarios are constructed:

- **T1 (timely-only).** PTC majority votes `payload_present=True`, `blob_data_available=False`. Proposer-boost is set, points to a child whose `parent_root == root`, and the parent of that child is `PAYLOAD_STATUS_EMPTY`. Spec returns `False` (data not available, and no proposer-boost branch saves it). Lodestar returns `True` (timely alone is enough).
- **T2 (both-true).** Same proposer-boost configuration but PTC majority votes `payload_present=True` AND `blob_data_available=True`. Spec returns `True`. Lodestar returns `True`. No divergence.
- **T3 (timely-only, no proposer boost).** PTC majority votes only `payload_present=True`, `blob_data_available=False`, but `proposer_boost_root` is zero. Spec returns `True` (condition 2: `proposer_root == Root()`). Lodestar returns `True` (condition 1). Result matches but for different reasons — no observable divergence.

Run 2026-05-14:

```
T1 (timely-only + adversarial proposer boost):  DIVERGE ✗
  spec.should_extend_payload     = False
  lodestar.should_extend_payload = True
  → divergence on first branch (AND vs OR)

T2 (both-true):                                  MATCH ✓
T3 (timely-only, no proposer boost):             MATCH ✓
```

The divergence triggers only when (a) PTC reaches timeliness threshold but not data-availability threshold AND (b) proposer-boost is set such that all three proposer-boost branches return False. Both non-collision cases agree.

### Cross-cuts with EF spec-test corpus

The pyspec test corpus at `vendor/consensus-specs/tests/.../gloas/fork_choice/` includes tests for `should_extend_payload`. Whether any fixture exercises the specific (timely-yes, available-no, adversarial-proposer-boost) configuration that triggers the lodestar divergence is an open follow-up. If lodestar passes the EF spec tests, the configuration is not covered, and a fixture extension is warranted.

### Suggested additional tests

- **T1.4** (in-tree vitest against real lodestar). Sibling to `items/067/demo/lodestar_intree_test.ts`. Construct a ProtoArray, insert a block, call `notifyPtcMessages` with payloadPresent=True at threshold+1 PTC indices, never set blob-availability (lodestar has no API for it), set proposer-boost adversarially, then call `shouldExtendPayload`. Expected: lodestar returns True; spec returns False. This bypasses the SSZ layer and exercises the fork-choice layer directly.
- **T1.5** (devnet end-to-end). On a Gloas-active devnet, drive PTC voters to attest `(payload_present=True, blob_data_available=False)` for a candidate block. Observe head selection per-client.
- **T1.6** (PR sketch). Two-line fix: (a) widen `notifyPtcMessages` signature to `(blockRoot, ptcIndices, payloadPresent, blobDataAvailable)`; (b) add a `payloadDataAvailabilityVotes` Map<RootHex, BitArray> mirroring `ptcVotes`; (c) gate `shouldExtendPayload` first branch on `isPayloadTimely && isPayloadDataAvailable`. Update the three call sites to pass `payloadAttestation.data.blobDataAvailable`.

## Mainnet reachability

The divergence triggers when, for a candidate block `root` and a proposer-boost block `B`:

1. PTC reaches the `> PAYLOAD_TIMELY_THRESHOLD = 256` threshold on `payload_present=True` votes for `root` (a majority of PTC members saw the execution payload).
2. PTC does NOT reach the `> DATA_AVAILABILITY_TIMELY_THRESHOLD = 256` threshold on `blob_data_available=True` votes for `root` (the data columns / blobs were not seen by a majority — typical of a payload-only DoS, a column-withholding attack, or a node with degraded data-availability sampling).
3. `proposer_boost_root` is set (the wall-clock is in the first 4 seconds of the slot) and points to a block `B` such that `B.parent_root == root`.
4. The parent of `B` (which is the block whose payload is the candidate) is `PAYLOAD_STATUS_EMPTY` (the previous-slot proposer extended the bid as EMPTY because their EL didn't see the payload either, OR the bid simply wasn't honored).

Under these conditions:

- **Spec / prysm / lighthouse / teku / grandine**: condition 1 is False (timely AND data-available is False because data is not available). Condition 2 is False (proposer_root != Root()). Condition 3 is False (B.parent_root == root). Condition 4 is False (parent of B is EMPTY, not FULL). Returns **False**. `get_payload_status_tiebreaker` for the previous-slot FULL/EMPTY node returns 0 (EMPTY).
- **Lodestar**: condition 1 is True (isPayloadTimely is True regardless of data availability). Returns **True**. Tiebreaker returns 2 (FULL).

Lodestar and the other 4 clients pick **different heads**: lodestar prefers the FULL chain, the others prefer the EMPTY chain. This is a fork-choice head-divergence — not a block-import state-root mismatch (#67-style), but a head-selection mismatch.

**Triggering actor**: a payload-withholding builder, or a slot in which a builder's payload was distributed but blob data was not (network partition on the column-sampling layer). On Gloas-active mainnet, blob-availability network issues are expected, and the timely-yes/available-no condition is realistic — not a corner case requiring adversarial construction.

**Frequency**: any slot where blob distribution lags behind payload distribution and the wall-clock is within the proposer-boost window. Plausibly multiple times per epoch on a network under any DA stress.

**Consequence**: lodestar nodes vote (via LMD-GHOST) for one head, the other 4 clients vote for another. With ~16-20% of mainnet validators running lodestar, this can prevent finalization on contested slots. Long-term: a lodestar-majority subgraph could finalize a divergent chain, requiring social-layer recovery.

**Pre-Glamsterdam mainnet impact**: zero. Gloas (the CL half of Glamsterdam) is currently `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` on mainnet. The divergence is only triggerable on Gloas-active testnets and on mainnet after Glamsterdam activation. Hence the impact classification `mainnet-glamsterdam`: matches the pattern used for items #22, #23, #28, and #67.

## Conclusion

Lodestar's fork-choice subsystem implements `should_extend_payload` with only the `is_payload_timely` half of spec's `is_payload_timely AND is_payload_data_available` first-branch conjunction. The cause is structural: lodestar's `notifyPtcMessages(blockRoot, ptcIndices, payloadPresent: boolean)` accepts only the timeliness bit; no `payloadDataAvailabilityVote` storage exists; no `isPayloadDataAvailable` predicate exists. The SSZ decoder correctly extracts `PayloadAttestationData.blobDataAvailable` from the wire (`packages/types/src/gloas/sszTypes.ts:91`), but the bit is dropped at all three call sites of `notifyPtcMessages`.

This is a fork-choice **head-selection** divergence (not a block-import state-root divergence). When PTC majority votes `payload_present=True` but `blob_data_available=False` AND proposer-boost is set adversarially, lodestar prefers the FULL chain while the 4 spec-conformant clients prefer the EMPTY chain.

**Verdict: impact mainnet-glamsterdam.** Confirmed divergence in source code; reproduced in a standalone Python harness simulating both semantics. Reachable on Gloas-active mainnet under realistic blob-DA-lag conditions.

Resolution options:

1. **Lodestar adds the missing half**: widen `notifyPtcMessages` signature; add a `payloadDataAvailabilityVotes` Map; add an `isPayloadDataAvailable` predicate; gate `shouldExtendPayload` condition 1 on both. Three-file change in `vendor/lodestar/packages/fork-choice/src` plus three call-site updates in `packages/beacon-node/src`. **Recommended as the immediate fix.**
2. **Spec spec-tests add a (timely-yes, available-no, adversarial-boost) fixture**. Would force the issue at fixture-gen time. Verify whether `vendor/consensus-specs/tests/.../gloas/fork_choice/` covers this configuration — open follow-up.

Comparison with item #67 (lodestar builder-sweep cache): both are mainnet-glamsterdam-impact lodestar fork-choice / state-transition divergences confirmed empirically. #67 is a block-import state-root divergence (CL state mismatch + EL block-hash mismatch). #77 is a fork-choice head-selection divergence (no state mismatch — both branches are valid imports — but different LMD-GHOST winners). Together they motivate a third lodestar follow-up audit covering the remaining T1, T3-T10 items in #76's deferred list.

## Cross-cuts

### With item #67 (lodestar builder-sweep)

Both items are mainnet-glamsterdam-impact lodestar divergences confirmed empirically in the same audit session. #67 is in the state-transition layer (`processWithdrawals.ts`); #77 is in the fork-choice layer (`protoArray.ts`). #67 produces block-import rejection; #77 produces head-selection divergence. Together they establish lodestar as the highest-divergence-density client in this audit. Audit-driven recommendation: prioritize lodestar deep-dive for the remaining #76 follow-ups (T1, T3-T10).

### With item #76 (fork-choice surface scan)

Item #76 deferred T2 (`is_payload_timely` PTC-vote-counting cross-client) to a standalone follow-up. This item closes T2 with a divergence finding broader than the original T2 scope: the issue is not in the `bitCount` semantic but in the missing `is_payload_data_available` predicate and its storage. T2 is now **closed via #77 with divergence: confirmed**.

### With item #56 (Fulu fork choice)

Fulu's fork-choice does not yet have the PTC vote concept (introduced in Gloas). #56 audited the Fulu primitives; this item extends to the Gloas additions. No cross-fork divergence.

### With item #60 (PTC selection)

The PTC composition computed via `compute_ptc` (item #60) determines which validators vote in the timeliness/availability scheme. A bug in PTC selection would affect both votes uniformly. #77's divergence is downstream of #60 — assumes PTC selection is correct (it is, per #60).

## Adjacent untouched

1. **Lodestar EF spec-test pass status on Gloas fork-choice fixtures involving `should_extend_payload`.** If lodestar passes, the spec-test corpus does NOT cover the timely-yes/available-no configuration. Open follow-up.
2. **In-tree vitest against real lodestar `shouldExtendPayload`.** Sibling to `items/067/demo/lodestar_intree_test.ts`. Would close the empirical loop the same way #67 did.
3. **Nimbus Gloas fork-choice completion.** Nimbus has not yet implemented `should_extend_payload`; once it does, re-run this audit to confirm correctness.
4. **Whether `is_payload_data_available` is referenced outside `should_extend_payload`.** Grep confirms only one usage; if future spec versions add another usage (e.g. as a gating condition in `get_attestation_score`), lodestar's missing predicate would surface there too.
5. **PR to lodestar with the 3-step fix.** The fix is small and well-scoped; an audit-driven PR is reasonable.
