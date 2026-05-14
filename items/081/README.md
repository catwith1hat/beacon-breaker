---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-14
builds_on: [76, 79, 80]
eips: [EIP-7732]
splits: [prysm, grandine]
# main_md_summary: spec `get_weight` returns 0 for FULL/EMPTY variants when `block.slot + 1 == current_slot` (previous-slot block) — lighthouse/teku/lodestar implement the zeroing; prysm's `choosePayloadContent` uses raw fn.weight/en.weight comparison at previous-slot, falling back to `shouldExtendPayload` only on weight ties (spec uses tiebreaker exclusively); grandine's segment-based scoring lacks the previous-slot zeroing entirely — uses `attesting_balances.full/empty` raw at previous-slot
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 81: `get_weight` Gloas modification — previous-slot FULL/EMPTY zeroing — prysm/grandine use raw weights instead of tiebreaker

## Summary

Spec's `get_weight` (`vendor/consensus-specs/specs/gloas/fork-choice.md:494-529`) returns 0 for FULL/EMPTY variants of the immediate previous-slot block:

```python
def get_weight(store: Store, node: ForkChoiceNode) -> Gwei:
    if node.payload_status == PAYLOAD_STATUS_PENDING or store.blocks[
        node.root
    ].slot + 1 != get_current_slot(store):
        state = store.checkpoint_states[store.justified_checkpoint]
        attestation_score = get_attestation_score(store, node, state)
        # ... + proposer_boost ...
        return attestation_score + proposer_score
    else:
        return Gwei(0)
```

The "previous-slot zeroing" forces the head-selection between FULL/EMPTY of the previous-slot block to be decided **only** by `get_payload_status_tiebreaker` (which uses `should_extend_payload`). This is intentional: at slot S+1, the FULL/EMPTY decision for block-at-S has not yet stabilized via PTC votes and shouldn't be biased by partial attestation counts.

`get_head` sorts children by `(get_weight, child.root, get_payload_status_tiebreaker)`:

```python
head = max(
    children,
    key=lambda child: (
        get_weight(store, child),
        child.root,
        get_payload_status_tiebreaker(store, child),
    ),
)
```

For FULL/EMPTY of the previous-slot block: get_weight=0 for both; child.root is identical (FULL and EMPTY of the same beacon block share the consensus root); tiebreaker decides.

For NOT-previous-slot FULL/EMPTY: get_weight uses raw attestation_score+proposer_score.

Per-client implementations:

| Client | Previous-slot FULL/EMPTY zeroing | Verdict |
|---|---|---|
| **prysm** | `choosePayloadContent` (`gloas.go:275-294`) compares `fn.weight` vs `en.weight` directly; only on ties falls back to `shouldExtendPayload` | **✗ raw weight wins at previous-slot when weights differ** |
| lighthouse | `get_weight` (`proto_array.rs:1341-1364`) explicit zero return | ✓ |
| teku | `effectiveWeight` (`ForkChoiceModelGloas.java:377-383`) returns `UInt64.ZERO` at previous-slot | ✓ |
| nimbus | no Gloas fork-choice (#79) | — |
| lodestar | `updateBestChildAndDescendant` (`protoArray.ts:1288-1299`) explicit `childEffectiveWeight = 0` at previous-slot | ✓ |
| **grandine** | `score()` (`store.rs:1269-1334`) uses raw `attesting_balances.full/empty` segment-based scoring; no previous-slot zeroing | **✗ structurally divergent (segment-based, no zeroing)** |

Three clients (lighthouse, teku, lodestar) correctly implement spec's previous-slot zeroing. Two (prysm, grandine) compare raw FULL/EMPTY weights at previous-slot — using `should_extend_payload` only on ties (prysm) or not at all in the same code path (grandine).

The divergence manifests when the FULL/EMPTY weights at previous-slot are unequal AND `should_extend_payload` returns False (a stress scenario where the payload was widely seen by attesters but the PTC failed to confirm data-availability). In such cases:
- Spec: zeros weights → tiebreaker → EMPTY (since `should_extend_payload=False` → FULL's tiebreaker=0 < EMPTY's tiebreaker=1).
- Prysm: FULL.weight > EMPTY.weight → picks FULL.
- Grandine: parent's full bucket > empty bucket → picks FULL.

This is a head-selection divergence at the FULL/EMPTY boundary, analogous to item #77's lodestar `should_extend_payload` issue but reached from a different angle.

## Question

Spec at `vendor/consensus-specs/specs/gloas/fork-choice.md:494-529`:

```python
def get_weight(store: Store, node: ForkChoiceNode) -> Gwei:
    if node.payload_status == PAYLOAD_STATUS_PENDING or store.blocks[
        node.root
    ].slot + 1 != get_current_slot(store):
        # compute attestation_score + proposer_score
        ...
    else:
        return Gwei(0)
```

`get_head` sort key (`fork-choice.md:558-581`):

```python
head = max(
    children,
    key=lambda child: (
        get_weight(store, child),
        child.root,
        get_payload_status_tiebreaker(store, child),
    ),
)
```

`get_payload_status_tiebreaker` (`fork-choice.md:411-426`):

```python
def get_payload_status_tiebreaker(store: Store, node: ForkChoiceNode) -> uint8:
    if node.payload_status == PAYLOAD_STATUS_PENDING or store.blocks[
        node.root
    ].slot + 1 != get_current_slot(store):
        return node.payload_status
    else:
        if node.payload_status == PAYLOAD_STATUS_EMPTY:
            return 1
        else:
            return 2 if should_extend_payload(store, node.root) else 0
```

At previous-slot:
- EMPTY tiebreaker = 1 (always).
- FULL tiebreaker = 2 if `should_extend_payload` else 0.
- get_weight = 0 for both.
- Decision: tiebreaker. EMPTY (1) beats FULL when `should_extend_payload=False` (FULL=0); FULL (2) beats EMPTY when `should_extend_payload=True`.

Open questions:

1. **Previous-slot zeroing**: does each client's get_weight-equivalent return 0 for FULL/EMPTY when `block.slot + 1 == current_slot`?
2. **Tiebreaker integration**: when zeroing applies, does each client correctly use `get_payload_status_tiebreaker` (or equivalent) to decide FULL vs EMPTY?
3. **Proposer-boost in get_weight**: spec uses `is_supporting_vote(node, synthetic_message_with_payload_present=False)` to gate proposer-boost addition. Does each client correctly exclude proposer-boost from FULL/EMPTY variants of the boosted block itself?

## Hypotheses

- **H1.** Each client returns 0 weight for FULL/EMPTY variants when `block.slot + 1 == current_slot`.
- **H2.** Each client decides FULL vs EMPTY at previous-slot using only `should_extend_payload` (via tiebreaker), not raw vote weights.
- **H3** *(divergence)*. Prysm uses raw FULL/EMPTY weight comparison at previous-slot, falling back to `should_extend_payload` only on weight ties.
- **H4** *(divergence)*. Grandine's segment-based scoring lacks an equivalent zeroing — uses raw `attesting_balances.full/empty` at previous-slot.

## Findings

### prysm

`choosePayloadContent` at `vendor/prysm/beacon-chain/forkchoice/doubly-linked-tree/gloas.go:274-294`:

```go
func (s *Store) choosePayloadContent(n *Node) *PayloadNode {
    if n == nil { return nil }
    fn := s.fullNodeByRoot[n.root]
    en := s.emptyNodeByRoot[n.root]
    if fn == nil { return en }
    if fn.weight > en.weight { return fn }
    if fn.weight < en.weight { return en }
    previousSlot := n.slot+1 == s.currentSlot()
    if !previousSlot || s.shouldExtendPayload(fn) {
        return fn
    }
    return en
}
```

Decision logic:
- If FULL doesn't exist → EMPTY.
- If `fn.weight > en.weight` → FULL.
- If `fn.weight < en.weight` → EMPTY.
- If `fn.weight == en.weight`:
  - If not previous-slot → FULL (default).
  - If previous-slot AND `shouldExtendPayload` → FULL.
  - If previous-slot AND NOT `shouldExtendPayload` → EMPTY.

`shouldExtendPayload` is consulted **only** when weights are equal. Spec consults the tiebreaker (which wraps `should_extend_payload`) when weights are zeroed at previous-slot — and the zeroing makes weights equal regardless of raw vote counts.

**Divergence scenario**: at slot S+1 (previous-slot relative to block-S):
- `fn.weight > en.weight` (more validators saw payload than not).
- `shouldExtendPayload(fn) = False` (e.g., blob_data_available threshold not met per PTC).
- Prysm: picks FULL (raw weight wins, line 281).
- Spec: get_weight(FULL)=0, get_weight(EMPTY)=0 → tiebreaker → EMPTY (FULL tiebreaker=0 < EMPTY tiebreaker=1 when shouldExtendPayload=False).

✗ H2.

`applyWeightChangesConsensusNode` (`gloas.go:72-91`) and `applyWeightChangesPayloadNode` (`:95-109`) accumulate `weight = balance + sum(children.weight)` per payload-node. Prysm does NOT zero weights at previous-slot.

### lighthouse

`get_weight` at `vendor/lighthouse/consensus/proto_array/src/proto_array.rs:1331-1366`:

```rust
fn get_weight<E: EthSpec>(
    &self,
    fc_node: &IndexedForkChoiceNode,
    proto_node: &ProtoNode,
    apply_proposer_boost: bool,
    proposer_boost_root: Hash256,
    current_slot: Slot,
    justified_balances: &JustifiedBalances,
    spec: &ChainSpec,
) -> Result<u64, Error> {
    if fc_node.payload_status == PayloadStatus::Pending
        || proto_node.slot().saturating_add(1_u64) != current_slot
    {
        let attestation_score = proto_node.attestation_score(fc_node.payload_status);
        if !apply_proposer_boost {
            return Ok(attestation_score);
        }
        let message = LatestMessage {
            slot: current_slot,
            root: proposer_boost_root,
            payload_present: false,
        };
        let proposer_score = if self.is_supporting_vote(fc_node, &message)? {
            get_proposer_score::<E>(justified_balances, spec)?
        } else {
            0
        };
        Ok(attestation_score.saturating_add(proposer_score))
    } else {
        Ok(0)  // <-- previous-slot FULL/EMPTY → 0
    }
}
```

Direct spec match. ✓ H1, H2.

### teku

`effectiveWeight` at `vendor/teku/storage/src/main/java/tech/pegasys/teku/storage/protoarray/ForkChoiceModelGloas.java:377-383`:

```java
private UInt64 effectiveWeight(final ProtoNode node, final UInt64 currentSlot) {
    if (node.getPayloadStatus() == ForkChoicePayloadStatus.PAYLOAD_STATUS_PENDING
        || !node.getBlockSlot().plus(1).equals(currentSlot)) {
        return node.getWeight();
    }
    return UInt64.ZERO;   // <-- previous-slot FULL/EMPTY → 0
}
```

Used in `compareViableChildren` (`:348-375`): compares effective weights first, then `computePayloadStatusTiebreaker`. ✓ H1, H2.

### nimbus

No Gloas fork-choice integration (#79).

### lodestar

`updateBestChildAndDescendant` at `vendor/lodestar/packages/fork-choice/src/protoArray/protoArray.ts:1286-1299`:

```typescript
// Gloas: nodes from previous slot (n-1) with EMPTY/FULL variant have weight hardcoded to 0.
const childEffectiveWeight =
    !isGloasBlock(childNode) ||
    childNode.payloadStatus === PayloadStatus.PENDING ||
    childNode.slot + 1 !== currentSlot
        ? childNode.weight
        : 0;
const bestChildEffectiveWeight =
    !isGloasBlock(bestChildNode) ||
    bestChildNode.payloadStatus === PayloadStatus.PENDING ||
    bestChildNode.slot + 1 !== currentSlot
        ? bestChildNode.weight
        : 0;

if (childEffectiveWeight !== bestChildEffectiveWeight) {
    newChildAndDescendant = childEffectiveWeight >= bestChildEffectiveWeight ? changeToChild : noChange;
    break outer;
}
// ... tiebreaker via getPayloadStatusTiebreaker
```

Spec-conformant zeroing. ✓ H1, H2.

### grandine

`score()` at `vendor/grandine/fork_choice_store/src/store.rs:1269-1334`:

```rust
fn score(
    &self,
    unfinalized_block: &UnfinalizedBlock<P>,
    parent: Option<&UnfinalizedBlock<P>>,
    apply_proposer_boost: bool,
) -> Score {
    let parent_attestation_score = if let Some(parent) = parent
        && parent.slot() + 1 != self.slot()
    {
        let parent_payload_verified = self.is_payload_verified(parent.block_root());
        match unfinalized_block.parent_payload_presence() {
            PayloadPresence::Empty => parent.attesting_balances.empty,
            PayloadPresence::Full if parent_payload_verified => parent.attesting_balances.full,
            PayloadPresence::Full | PayloadPresence::Pending => 0,
        }
    } else {
        0
    };

    let attesting_balances = unfinalized_block.attesting_balances;
    let attestation_score = attesting_balances.pending;
    // ... + proposer_score + tiebreaker
    (parent_attestation_score, attestation_score + proposer_score, tiebreaker)
}
```

Grandine's algorithm is **segment-based**, not variant-based. Each block has `attesting_balances: AttestingBalances { pending, full, empty }`. The `score()` returns a tuple comparing siblings at branch points.

Notable: the only "zeroing" condition is `parent.slot() + 1 == self.slot()` — i.e., when parent is the immediate predecessor of this block. This zeroes `parent_attestation_score`. But spec's zeroing is about `block.slot + 1 == current_slot` — i.e., when the BLOCK is at the previous slot relative to current. Different concept.

For previous-slot FULL/EMPTY tiebreak: grandine compares `parent.attesting_balances.full` vs `parent.attesting_balances.empty` based on which child declares parent FULL vs EMPTY. No zeroing applies.

If `parent.attesting_balances.full > parent.attesting_balances.empty` AND `should_extend_payload=False`:
- Spec: zero weights, tiebreaker → EMPTY.
- Grandine: raw full > empty → picks the child declaring parent FULL.
- → Divergent.

✗ H1, H2 in the segment-comparison surface.

**Caveat**: grandine's segment-based algorithm computes head differently. It may produce the same end result as spec in many scenarios (the variant winner cascades down the chain). Empirical verification on a wide scenario set is needed to characterize the divergence's impact.

## Cross-reference table

| Client | Previous-slot FULL/EMPTY weight (H1) | Decision uses tiebreaker only at previous-slot (H2) |
|---|---|---|
| **prysm** | ✗ raw `fn.weight`/`en.weight` (no zeroing) — `gloas.go:281` | ✗ tiebreaker (`shouldExtendPayload`) only consulted on weight ties — `:289-290` |
| lighthouse | ✓ explicit `Ok(0)` — `proto_array.rs:1364` | ✓ get_head uses `get_weight + tiebreaker` |
| teku | ✓ `UInt64.ZERO` — `ForkChoiceModelGloas.java:382` | ✓ `compareViableChildren` uses effective weight + tiebreaker — `:362-374` |
| nimbus | — (no FC, #79) | — |
| lodestar | ✓ `childEffectiveWeight = 0` — `protoArray.ts:1293` | ✓ tiebreaker on weight tie — `:1315-1323` |
| **grandine** | ✗ `parent.attesting_balances.full/empty` raw at previous-slot | ✗ no tiebreaker-based override of weight comparison at previous-slot |

**3 of 6 spec-conformant (lighthouse, teku, lodestar).**
**2 of 6 divergent (prysm, grandine).**
**1 of 6 gapped (nimbus, per #79).**

## Empirical tests

### Source-level confirmation

```bash
# Look for the spec's previous-slot zeroing pattern across clients
grep -rn "slot + 1.*currentSlot\|slot+1 ==.*currentSlot\|blockSlot.*plus(1)\|saturating_add(1_u64).*current_slot" \
    vendor/{prysm,lighthouse,teku,lodestar,grandine}/<fork-choice paths>
```

Returns:
- lighthouse: `proto_array.rs:1341-1342` ✓
- teku: `ForkChoiceModelGloas.java:378-379` ✓
- lodestar: `protoArray.ts:1289-1291`, `:1295-1297` ✓
- prysm: `gloas.go:289` (only as the `previousSlot := n.slot+1 == s.currentSlot()` flag, used only on weight ties)
- grandine: not present in `score()` function

### Suggested scenario test

Construct a fork-choice scenario at slot S+1 where:
- Block B at slot S has FULL and EMPTY variants.
- PTC majority voted `payload_present=True` but NOT `blob_data_available=True` → `should_extend_payload(FULL)=False`.
- All attesters at slot S who voted for B had `payload_present=True` → `fn.weight > en.weight` in prysm/grandine.

Expected head selection:
- Spec: get_weight(FULL)=0, get_weight(EMPTY)=0, tiebreaker → EMPTY (since shouldExtendPayload=False → FULL=0 < EMPTY=1).
- Lighthouse/teku/lodestar: matches spec → EMPTY.
- Prysm: fn.weight > en.weight → FULL. Divergent.
- Grandine: parent.attesting_balances.full > .empty → child declaring FULL → divergent.

Empirical follow-up: scenario simulator harness running spec vs each client implementation with constructed states.

## Mainnet reachability

Scenario reachability: at slot S+1, deciding between FULL/EMPTY variants of block-at-S:
- Attesters at slot S who saw the payload contribute to FULL.weight (in prysm/grandine).
- PTC at slot S votes timely + available. If blob data is partially available (some nodes saw blobs, some didn't), the PTC may reach `payload_timely` threshold but NOT `blob_data_available` threshold.
- `should_extend_payload` returns False (per item #77's spec) for this case.
- Prysm/grandine pick FULL on raw weight; spec/lighthouse/teku/lodestar pick EMPTY via tiebreaker.

**Triggering actor**: a builder or DA-stress condition. Normal Gloas operation under blob-availability stress can produce this state.

**Frequency**: every Gloas slot where blob propagation lags payload propagation.

**Consequence**: prysm+grandine select FULL chain; lighthouse+teku+lodestar select EMPTY chain. Same divergence shape as item #77 but reached from a different angle (raw weight vs zeroed-weight + tiebreaker).

**Pre-Glamsterdam mainnet impact**: zero. Gloas is `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH`. Operational on Gloas-active testnets and on mainnet after Glamsterdam activation. Hence `mainnet-glamsterdam`.

## Conclusion

T7 from item #76 (`get_weight` Gloas modification — payload-status affects fork-choice weights) closes with a 2-vs-3 divergence on previous-slot zeroing. Spec zeros FULL/EMPTY weights at `block.slot + 1 == current_slot`; lighthouse, teku, lodestar implement the zeroing; prysm uses raw weight comparison with `shouldExtendPayload` as tiebreaker only; grandine's segment-based scoring lacks the zeroing entirely.

**Verdict: impact mainnet-glamsterdam.** Splits `[prysm, grandine]`.

The divergence manifests in DA-stress scenarios where `should_extend_payload` returns False but FULL.weight > EMPTY.weight in the variant accounting. Spec picks EMPTY (tiebreaker); prysm/grandine pick FULL (raw weight).

Resolution options:
1. **Prysm**: rewrite `choosePayloadContent` to zero out fn/en weights at previous-slot before comparison, then apply tiebreaker. Concretely:
   ```go
   func (s *Store) choosePayloadContent(n *Node) *PayloadNode {
       fn := s.fullNodeByRoot[n.root]
       en := s.emptyNodeByRoot[n.root]
       if fn == nil { return en }
       previousSlot := n.slot+1 == s.currentSlot()
       if previousSlot {
           return ternary(s.shouldExtendPayload(fn), fn, en)
       }
       if fn.weight > en.weight { return fn }
       if fn.weight < en.weight { return en }
       return fn  // default on tie
   }
   ```
2. **Grandine**: in `score()`, conditionalize `parent.attesting_balances.full/empty` on whether `self.slot() != parent.slot() + 1` (i.e., zero parent's full/empty when this block is at the immediate-next slot but spec considers parent the "previous slot" relative to current_slot). The mapping from segment-based to spec semantics requires deeper algorithm-level alignment.
3. **EF spec-test corpus**: add fixtures exercising the previous-slot zeroing scenarios. Verify whether `vendor/consensus-specs/tests/.../gloas/fork_choice/` covers this.

## Cross-cuts

### With item #76 (fork-choice surface scan)

Item #76's T7 entry now closes.

### With item #77 (lodestar `is_payload_data_available`)

Same head-selection divergence (FULL-vs-EMPTY at previous-slot under DA stress) is reached from different bugs in different clients. #77 (lodestar) reaches it via missing `is_payload_data_available` predicate in `shouldExtendPayload`. #81 (prysm, grandine) reaches it via missing previous-slot weight zeroing.

### With item #80 (same-slot vote routing)

#80 documents same-slot vote routing divergences in prysm/lodestar/grandine. #81 documents previous-slot weight zeroing divergences in prysm/grandine. Both cascade: same-slot votes incorrectly credit FULL/EMPTY (#80) → those FULL/EMPTY weights then incorrectly affect previous-slot tiebreaks in prysm/grandine (#81). The two divergences amplify each other.

### With item #79 (nimbus complete fork-choice gap)

Nimbus is excluded.

## Adjacent untouched

1. **Empirical simulator harness**: build a deterministic Gloas fork-choice scenario test that exercises previous-slot FULL/EMPTY tiebreaks under DA stress. Compare spec vs each client.
2. **EF spec-test corpus coverage**: verify whether `consensus-spec-tests/tests/.../gloas/fork_choice/` exercises the previous-slot zeroing scenarios.
3. **Proposer-boost integration**: spec gates proposer-boost addition on `is_supporting_vote(node, synthetic_message_with_payload_present=False)`. Each client's proposer-boost handling for FULL/EMPTY variants of the boosted block needs separate verification.
4. **`get_payload_status_tiebreaker` correctness per-client**: verify each client correctly implements the 3-way tiebreaker (PENDING / EMPTY=1 / FULL via `shouldExtendPayload`).
5. **Cross-fork transition behavior**: at Gloas activation, the previous-slot block may be pre-Gloas (no FULL/EMPTY variants). Each client's handling of the boundary slot needs verification.
