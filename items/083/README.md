---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-14
builds_on: [76, 79, 82]
eips: [EIP-7732]
splits: [prysm, lodestar]
# main_md_summary: spec Gloas `is_head_weak` adds equivocating-validator weight from head-slot committees to head_weight for monotonicity ("more attestations can only change output from True to False, not vice-versa") — lighthouse/teku/grandine implement the addition; prysm and lodestar use raw consensus-node weight without the equivocating term; affects late-block reorg decisions when equivocations exist in head-slot committees
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 83: `is_head_weak` Gloas equivocating-committee monotonicity term missing in prysm and lodestar

## Summary

Gloas modifies `is_head_weak` (`vendor/consensus-specs/specs/gloas/fork-choice.md:679-709`) to add the effective balance of equivocating validators in head-slot committees to `head_weight`:

```python
def is_head_weak(store: Store, head_root: Root) -> bool:
    justified_state = store.checkpoint_states[store.justified_checkpoint]
    reorg_threshold = calculate_committee_fraction(justified_state, REORG_HEAD_WEIGHT_THRESHOLD)

    head_state = store.block_states[head_root]
    head_block = store.blocks[head_root]
    epoch = compute_epoch_at_slot(head_block.slot)
    head_node = ForkChoiceNode(root=head_root, payload_status=PAYLOAD_STATUS_PENDING)
    head_weight = get_attestation_score(store, head_node, justified_state)
    for index in range(get_committee_count_per_slot(head_state, epoch)):
        committee = get_beacon_committee(head_state, head_block.slot, CommitteeIndex(index))
        head_weight += Gwei(
            sum(
                justified_state.validators[i].effective_balance
                for i in committee
                if i in store.equivocating_indices
            )
        )

    return head_weight < reorg_threshold
```

The spec note explains the rationale: "more attestations can only change the output from `True` to `False`, not vice-versa." The equivocating-committee term ensures monotonicity — once a head is deemed strong, additional attestations from non-equivocating validators can only increase weight, never trigger a reclassification to weak.

`is_head_weak` is used by:
1. `should_apply_proposer_boost` (`:445`) — to gate proposer-boost suppression when parent is weak.
2. Late-block reorg decision logic — to decide whether to re-org against a late head.

**Cross-client status**:

| Client | Adds equivocating-committee weight to `head_weight` | Verdict |
|---|---|---|
| **prysm** | ✗ `reorg_late_blocks.go:82,154` and `gloas.go:507` use raw `weight*100 > committeeWeight * ReorgHeadWeightThreshold` | structural gap; no monotonicity term |
| lighthouse | ✓ `proto_array.rs:677-678` (per node `equivocating_attestation_score` field, added in `is_head_weak` walk) | spec-conformant |
| teku | ✓ `ForkChoiceUtilGloas.java:339-342` (`computeEquivocatingCommitteeWeight` added to `headWeight`) | spec-conformant |
| nimbus | — (no Gloas fork-choice integration, #79) | covered by #79 |
| **lodestar** | ✗ `forkChoice.ts:433` uses raw `headNode.weight >= reorgThreshold`; spec link at `:426` cites phase-0 not Gloas | structural gap; no monotonicity term |
| grandine | ✓ `store.rs:1192-1211` (walks committees, adds equivocating-validator balance) | spec-conformant |

**3 of 5 active clients (lighthouse, teku, grandine) implement the Gloas equivocating-committee term.**
**2 (prysm, lodestar) use raw weight comparison without the monotonicity term.**

The lodestar code at `forkChoice.ts:425-426` even links to phase-0 spec (`v1.4.0-beta.4/specs/phase0/fork-choice.md#is_head_weak`), confirming the Gloas modification has not been picked up.

## Question

Spec at `vendor/consensus-specs/specs/gloas/fork-choice.md:679-709` adds:

```python
for index in range(get_committee_count_per_slot(head_state, epoch)):
    committee = get_beacon_committee(head_state, head_block.slot, CommitteeIndex(index))
    head_weight += Gwei(
        sum(
            justified_state.validators[i].effective_balance
            for i in committee
            if i in store.equivocating_indices
        )
    )
```

Open questions:

1. Does each client's `is_head_weak` add equivocating-validator weight from head-slot committees?
2. Are equivocating validators tracked per-node (lighthouse) or queried via global `equivocating_indices` (others)?
3. Does the missing term cause head-weakness misclassification in scenarios with equivocations?

## Hypotheses

- **H1.** Each client's `is_head_weak` includes the Gloas equivocating-committee term.
- **H2.** Without the term, late-block reorg decisions may differ from spec when equivocations exist.

## Findings

### prysm

`shouldApplyProposerBoost` at `vendor/prysm/beacon-chain/forkchoice/doubly-linked-tree/gloas.go:487-508`:

```go
return p.weight*100 >= s.committeeWeight*params.BeaconConfig().ReorgHeadWeightThreshold
```

Raw `p.weight` (the parent's accumulated weight) compared against threshold. **No equivocating-committee term added.**

Also in `reorg_late_blocks.go:82,154`:

```go
if consensusHead.weight*100 > f.store.committeeWeight*params.BeaconConfig().ReorgHeadWeightThreshold {
    return ...
}
```

Same raw weight comparison.

✗ H1.

### lighthouse

`ProtoNodeV29` carries `equivocating_attestation_score` field (`proto_array.rs:170`). The comment at `:166-168`:

> Weight from equivocating validators that voted for this block.
> Used by `is_head_weak` to match the spec's monotonicity guarantee:
> more attestations can only increase head weight, never decrease it.

`is_head_weak` at `proto_array.rs:664-682`:

```rust
fn is_head_weak<E: EthSpec>(
    &self,
    head_node: &ProtoNode,
    justified_balances: &JustifiedBalances,
    spec: &ChainSpec,
) -> bool {
    let reorg_threshold = calculate_committee_fraction(
        justified_balances.total_effective_balance,
        spec.reorg_head_weight_threshold,
    );
    let head_weight = head_node
        .attestation_score(PayloadStatus::Pending)
        .saturating_add(head_node.equivocating_attestation_score().unwrap_or(0));
    head_weight < reorg_threshold
}
```

Adds `equivocating_attestation_score` (computed via per-node tracking when equivocations are recorded) to attestation_score. ✓ H1.

Lighthouse's approach: track equivocating weight per node at the moment equivocations are inserted, rather than re-walking committees on every `is_head_weak` call. Algorithmically equivalent.

### teku

`isHeadWeak` at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/util/ForkChoiceUtilGloas.java:326-345`:

```java
private boolean isHeadWeak(
    final ReadOnlyStore store,
    final Bytes32 root,
    final UInt64 reorgThreshold,
    final BeaconState headState,
    final BeaconState justifiedState) {
  UInt64 headWeight =
      getNodeAttestationWeight(store, root, PAYLOAD_STATUS_PENDING, justifiedState);

  // Add weight from equivocating validators in head slot committees
  final ReadOnlyForkChoiceStrategy forkChoiceStrategy = store.getForkChoiceStrategy();
  final Optional<UInt64> maybeHeadSlot = forkChoiceStrategy.blockSlot(root);
  if (maybeHeadSlot.isPresent()) {
    final UInt64 equivocatingWeight =
        computeEquivocatingCommitteeWeight(maybeHeadSlot.get(), store, headState, justifiedState);
    headWeight = headWeight.plus(equivocatingWeight);
  }

  return headWeight.isLessThan(reorgThreshold);
}
```

`computeEquivocatingCommitteeWeight` (`:283-309`) walks head-slot committees and sums effective balances of equivocating validators. ✓ H1.

### nimbus

No Gloas fork-choice integration (#79).

### lodestar

`forkChoice.ts:425-435` (in `getPreliminaryProposerHead`):

```typescript
// No reorg if headBlock is "not weak" ie. headBlock's weight exceeds (REORG_HEAD_WEIGHT_THRESHOLD = 20)% of total attester weight
// https://github.com/ethereum/consensus-specs/blob/v1.4.0-beta.4/specs/phase0/fork-choice.md#is_head_weak
const reorgThreshold = getCommitteeFraction(this.fcStore.justified.totalBalance, {
    slotsPerEpoch: SLOTS_PER_EPOCH,
    committeePercent: this.config.REORG_HEAD_WEIGHT_THRESHOLD,
});
const headNode = this.protoArray.getNode(headBlock.blockRoot, headBlock.payloadStatus);
if (headNode === undefined || headNode.weight >= reorgThreshold) {
    return {proposerHead, isHeadTimely, notReorgedReason: NotReorgedReason.HeadBlockNotWeak};
}
```

Uses raw `headNode.weight`. **No equivocating-committee term added.** The spec link at line 426 points to **phase-0** (`v1.4.0-beta.4/specs/phase0/fork-choice.md`), confirming the Gloas modification has not been picked up.

✗ H1.

### grandine

`is_head_weak` at `vendor/grandine/fork_choice_store/src/store.rs:1164-1214`:

```rust
let (head, mut head_weight) = ...(&head.chain_link, head.attesting_balances.pending);

if !self.equivocating_indices.is_empty() {
    let head_state = head.state(self);
    for committee in accessors::beacon_committees(&head_state, head.slot())? {
        head_weight += committee
            .into_iter()
            .filter(|validator_index| self.equivocating_indices.contains(validator_index))
            .map(|validator_index| {
                let index: usize = validator_index.try_into()...;
                self.justified_active_balances.get(index).copied().unwrap_or_default()
            })
            .sum::<Gwei>();
    }
}

Ok(head_weight < reorg_threshold)
```

Walks beacon committees of the head slot, sums effective balances of equivocating validators, adds to head_weight. ✓ H1.

## Cross-reference table

| Client | `is_head_weak` adds equivocating-committee weight (H1) |
|---|---|
| **prysm** | ✗ `gloas.go:507`, `reorg_late_blocks.go:82,154` use raw `weight*100 > committeeWeight*threshold` |
| lighthouse | ✓ `proto_array.rs:677-678` per-node `equivocating_attestation_score` |
| teku | ✓ `ForkChoiceUtilGloas.java:339-342` `computeEquivocatingCommitteeWeight` |
| nimbus | — (no FC, #79) |
| **lodestar** | ✗ `forkChoice.ts:433` raw `headNode.weight`; spec link points to phase-0 |
| grandine | ✓ `store.rs:1192-1211` walks committees, sums equivocating balances |

**3 of 5 active clients spec-conformant (lighthouse, teku, grandine).**
**2 (prysm, lodestar) lack the equivocating-committee monotonicity term.**

## Empirical tests

### Source-level grep

```bash
grep -rn "equivocating_indices\|equivocatingIndices\|equivocating_attestation_score\|computeEquivocatingCommitteeWeight" \
    vendor/{prysm,lighthouse,teku,lodestar,grandine}/<fork-choice paths>
```

Returns matches in lighthouse, teku, grandine. Empty in prysm's `is_head_weak`-equivalent and in lodestar's `getPreliminaryProposerHead`.

### Suggested empirical scenario

Construct a scenario where:
- Head block H is at slot S.
- H's slot-S committee includes one or more equivocating validators (already in `store.equivocating_indices` from prior slashings).
- `H.weight` (without equivocating-committee term) is just below `reorg_threshold` (= `REORG_HEAD_WEIGHT_THRESHOLD / 100 * committee_weight`).
- Equivocating-committee weight, if added, would push above threshold.

Expected:
- Spec / lighthouse / teku / grandine: `is_head_weak` = False (head_weight + equivocating-committee >= threshold). No reorg.
- Prysm / lodestar: `is_head_weak` = True (raw head_weight < threshold). Apply reorg / suppress proposer-boost.

Divergent reorg decisions.

## Mainnet reachability

**Triggering scenario**: equivocating validators exist on the network (from prior slashings) and happen to be members of the head-slot's committee.

**Frequency**: depends on equivocation rate (rare, but realistic on a long-lived chain).

**Consequence**: at the head-weakness boundary, prysm and lodestar would reorg or suppress proposer-boost where lighthouse/teku/grandine would not. The fork-choice diverges between the two groups.

The monotonicity invariant is important for fork-choice stability: spec ensures that adding more attestations doesn't flip a strong head back to weak. Without the equivocating-committee term, prysm/lodestar may exhibit non-monotonic behavior — a head that was previously "strong" can become "weak" after equivocations are recorded, even if no new attestations changed the underlying weight.

**Pre-Glamsterdam mainnet impact**: zero. The Gloas-specific equivocating-committee term applies only on Gloas-active networks. Pre-Gloas, the phase-0 `is_head_weak` (no equivocating term) is the correct semantic, which is what prysm/lodestar currently implement.

After Glamsterdam activation, the divergence is operational. Hence `mainnet-glamsterdam`.

## Conclusion

T9 from item #76 (re-org timing — ePBS introduces new re-org scenarios) closes with a 3-vs-2 divergence: lighthouse, teku, grandine add the equivocating-committee weight to `head_weight` per Gloas spec; prysm and lodestar use raw consensus-node weight (phase-0 semantics).

**Verdict: impact mainnet-glamsterdam.** Splits `[prysm, lodestar]`.

The divergence affects late-block reorg decisions and `should_apply_proposer_boost` parent-weakness checks at the head-weakness boundary. Without the equivocating-committee term, prysm and lodestar can mis-classify a head as weak (when spec considers it strong due to the added equivocating term), triggering reorgs or suppressing proposer-boost where spec wouldn't.

Resolution options:

1. **Prysm**: extend `isHeadWeak` (and `applyLateBlockReorg`) to add equivocating-validator weight from head-slot committees. Track equivocating validators per-node (lighthouse style) or query global `equivocating_indices` (teku/grandine style).
2. **Lodestar**: extend `getPreliminaryProposerHead` (and any other `is_head_weak`-equivalent code paths) to add the equivocating-committee weight. Update the spec link comment to point to Gloas instead of phase-0.

## Cross-cuts

### With item #76 (fork-choice surface scan)

Item #76's T9 entry closes.

### With item #79 (nimbus complete fork-choice gap)

Nimbus is excluded.

### With item #82 (`record_block_timeliness` 2-tuple + proposer-boost equivocation suppression)

#82 documents the PTC-timeliness equivocation filter in `should_apply_proposer_boost`. #83 documents the equivocating-committee term in `is_head_weak`. Both involve equivocations but in different spec functions:
- #82: spec filters equivocations BY PTC-timeliness.
- #83: spec ADDS equivocating-committee weight to head_weight.

A complete spec-conformant Gloas fork-choice needs both. Lighthouse implements both; teku implements #83 but defers #82; grandine implements #83 but over-strictly handles #82; prysm and lodestar are missing both.

## Adjacent untouched

1. **`is_parent_strong` Gloas modification** (`fork-choice.md:712-723`): uses `get_attestation_score` on `ForkChoiceNode(parent_root, parent_payload_status)`. Payload-status-aware. Each client's implementation needs verification — but largely cousin to `is_head_weak`.
2. **Late-block reorg machinery**: prysm has `reorg_late_blocks.go` with two raw-weight comparison sites. Each could be a divergence relative to spec.
3. **Cross-fork transition for equivocating_indices**: how does each client handle equivocations recorded pre-Gloas affecting Gloas-slot head weakness?
4. **Empirical simulator**: scenario S2 above could be turned into an executable test exercising the head-weakness boundary with equivocations.
