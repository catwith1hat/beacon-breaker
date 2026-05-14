---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-14
builds_on: [76, 82, 83]
eips: [EIP-7732]
splits: [prysm, lodestar, grandine]
# main_md_summary: Gloas reorg-helper trio audit — `is_parent_strong` (prysm uses raw consensus-node weight not variant-specific; grandine unimplemented), `update_proposer_boost_root` canonical-proposer-index check (prysm and lodestar lack the proposer-index match gate, applying boost to any timely first-seen block regardless of whether proposer matches canonical chain), and `is_head_late` (grandine has no equivalent, missing late-head-reorg machinery entirely)
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 84: Gloas reorg-helper trio — `is_parent_strong`, `update_proposer_boost_root`, `is_head_late` — divergences in prysm, lodestar, grandine

## Summary

Three Gloas fork-choice reorg-gating helpers audited together. Each is a small surface but each has at least one client divergence.

### Finding A: `is_parent_strong` (spec `fork-choice.md:712-723`)

Gloas uses the parent's payload-status-aware variant weight:

```python
def is_parent_strong(store: Store, root: Root) -> bool:
    justified_state = store.checkpoint_states[store.justified_checkpoint]
    parent_threshold = calculate_committee_fraction(justified_state, REORG_PARENT_WEIGHT_THRESHOLD)
    block = store.blocks[root]
    parent_payload_status = get_parent_payload_status(store, block)
    parent_node = ForkChoiceNode(root=block.parent_root, payload_status=parent_payload_status)
    parent_weight = get_attestation_score(store, parent_node, justified_state)
    return parent_weight > parent_threshold
```

**Divergences**:
- **prysm**: `reorg_late_blocks.go:96,159` uses `parent.node.weight*100 < ... * ReorgParentWeightThreshold` — `parent.node.weight` is the consensus Node weight (= balance + en.weight + fn.weight per `gloas.go:89`), not the specific payload-status variant matching head's chain. ✗
- **grandine**: `reorg_parent_weight_threshold` constant defined in `types/src/config.rs:152` but NEVER consumed by any fork-choice code path. Grandine has no `is_parent_strong` implementation at all. ✗

Spec-conformant: lighthouse (`proto_array_fork_choice.rs:754-759` uses `parent_node.attestation_score(parent_payload_status)`), teku (`ForkChoiceUtilGloas.java:406-415` `getNodeAttestationWeight(parentRoot, parentPayloadStatus, justifiedState)`), lodestar (`forkChoice.ts:443` fetches `protoArray.getNode(parentBlock.blockRoot, parentBlock.payloadStatus)` — payload-status-aware variant; though spec link comment at `:438` cites phase-0).

### Finding B: `update_proposer_boost_root` canonical-proposer check (spec `fork-choice.md:601-619`)

Gloas adds a check: proposer-boost is applied only if `block.proposer_index == get_beacon_proposer_index(head_state)`:

```python
def update_proposer_boost_root(store: Store, root: Root) -> None:
    is_first_block = store.proposer_boost_root == Root()
    is_timely = store.block_timeliness[root][ATTESTATION_TIMELINESS_INDEX]
    if is_timely and is_first_block:
        head_state = copy(store.block_states[get_head(store).root])
        slot = get_current_slot(store)
        if head_state.slot < slot:
            process_slots(head_state, slot)
        block = store.blocks[root]
        # Only update if the proposer is the same as on the canonical chain
        if block.proposer_index == get_beacon_proposer_index(head_state):
            store.proposer_boost_root = root
```

**Divergences**:
- **prysm** (`store.go:182-185`): only checks `currentSlot == slot && sss < boostThreshold && isFirstBlock` — no proposer-index match check. ✗
- **lodestar** (`forkChoice.ts:668-675`): only checks `proposerBoost && isTimely && proposerBoostRoot === null` — no proposer-index check. ✗

Spec-conformant: lighthouse (`fork_choice.rs:830-841` adds `is_canonical_proposer = block.proposer_index() == canonical_head_proposer_index`), teku (`ForkChoice.java:913-915` `block.getProposerIndex().intValue() == spec.getProposerIndexAtSlot(headState, currentSlot)`), grandine (`store.rs:3837-3838` `chain_link.block.message().proposer_index() == accessors::get_beacon_proposer_index(...)`).

### Finding C: `is_head_late` (spec `fork-choice.md:675-677`)

Trivial spec — reads `store.block_timeliness[head_root][ATTESTATION_TIMELINESS_INDEX]`.

**Divergence**:
- **grandine**: NO `is_head_late`, `is_block_late`, or `arrived_early` equivalent exists in `fork_choice_store/` or `fork_choice_control/`. Grandine has no late-head-reorg machinery at all. ✗

Spec-conformant (or functionally equivalent): lighthouse, teku (`BlockTimelinessTracker.java:92-94`), lodestar (`forkChoice.ts:1838` `!headBlock.timeliness`), prysm (`node.go:40-44` `arrivedEarly` computes `time_since_block_slot_start < AttestationDueBPS` from stored arrival timestamp — equivalent to spec's pre-recorded `block_timeliness_attestation`).

## Question

Spec at `vendor/consensus-specs/specs/gloas/fork-choice.md`:
- `:712-723` `is_parent_strong` (Gloas: payload-status-aware).
- `:601-619` `update_proposer_boost_root` (Gloas: + canonical-proposer-index check).
- `:675-677` `is_head_late` (Gloas: reads ATTESTATION_TIMELINESS_INDEX from 2-tuple).

Open questions:

1. Does each client's `is_parent_strong` use the specific payload-status variant matching head's chain (not the combined consensus-node weight)?
2. Does each client's `update_proposer_boost_root` check that the block's proposer matches the canonical chain's proposer at the current slot?
3. Does each client implement `is_head_late` (or equivalent late-head-detection logic) for reorg gating?

## Hypotheses

- **H1.** Each client's `is_parent_strong` uses payload-status-aware variant weight.
- **H2.** Each client's `update_proposer_boost_root` checks proposer-index against the canonical-chain proposer.
- **H3.** Each client has an `is_head_late` equivalent that gates late-head reorgs.

## Findings

### prysm

**A. `is_parent_strong`**: `reorg_late_blocks.go:96,159`:

```go
if parent.node.weight*100 < f.store.committeeWeight*params.BeaconConfig().ReorgParentWeightThreshold {
    return
}
```

`parent.node.weight` is the consensus Node weight at `gloas.go:89` (`n.weight = n.balance + childrenWeight`, where childrenWeight = en.weight + fn.weight). This is the SUM of PENDING + FULL + EMPTY variant weights, not the specific variant matching head's chain. ✗

**B. `update_proposer_boost_root`** at `store.go:182-185`:

```go
isFirstBlock := s.proposerBoostRoot == [32]byte{}
if currentSlot == slot && sss < boostThreshold && isFirstBlock {
    s.proposerBoostRoot = root
}
```

No proposer-index check. ✗

**C. `is_head_late`**: implemented via `arrivedEarly` (`node.go:40-44`) — functionally equivalent to spec for blocks processed at arrival time. ✓

### lighthouse

**A. `is_parent_strong`** at `proto_array_fork_choice.rs:754-759`:

```rust
// Spec: `is_parent_strong`. Use payload-aware weight matching the
// payload path the head node is on from its parent.
let parent_payload_status = info.head_node.get_parent_payload_status();
let parent_weight = info.parent_node.attestation_score(parent_payload_status);
```

Uses `attestation_score(parent_payload_status)` — payload-status-aware. ✓

**B. `update_proposer_boost_root`** at `fork_choice.rs:830-841`:

```rust
// Add proposer score boost if the block is the first timely block for this slot and its
// proposer matches the expected proposer on the canonical chain (per spec
// `update_proposer_boost_root`, introduced in v1.7.0-alpha.5).
let is_before_attesting_interval = block_delay < attestation_threshold;
let is_first_block = self.fc_store.proposer_boost_root().is_zero();
let is_canonical_proposer = block.proposer_index() == canonical_head_proposer_index;
if current_slot == block.slot()
    && is_before_attesting_interval
    && is_first_block
    && is_canonical_proposer
{
    self.fc_store.set_proposer_boost_root(block_root);
}
```

`is_canonical_proposer` check present. ✓

**C. `is_head_late`**: implemented via per-node `block_timeliness_attestation_threshold` field (`proto_array.rs:142, 612-614`). ✓

### teku

**A. `is_parent_strong`** at `ForkChoiceUtilGloas.java:406-415`:

```java
private boolean isParentStrong(..., final ForkChoicePayloadStatus parentPayloadStatus, ...) {
    final UInt64 attestationScore =
        getNodeAttestationWeight(store, parentRoot, parentPayloadStatus, justifiedState);
    return attestationScore.isGreaterThan(parentThreshold);
}
```

`parentPayloadStatus` passed in explicitly; uses payload-status-aware weight. ✓

**B. `update_proposer_boost_root`** at `ForkChoice.java:913-915`:

```java
return block.getProposerIndex().intValue()
    == spec.getProposerIndexAtSlot(headState, currentSlot);
```

Proposer-index check present. ✓

**C. `is_head_late`** at `BlockTimelinessTracker.java:92-94` and `ForkChoiceUtil.java:387`. ✓

### nimbus

No Gloas fork-choice integration (#79). All three reorg helpers missing.

### lodestar

**A. `is_parent_strong`** at `forkChoice.ts:438-445`:

```typescript
// https://github.com/ethereum/consensus-specs/blob/v1.6.1/specs/phase0/fork-choice.md#is_parent_strong
const parentThreshold = getCommitteeFraction(...);
const parentNode = this.protoArray.getNode(parentBlock.blockRoot, parentBlock.payloadStatus);
if (parentNode === undefined || parentNode.weight <= parentThreshold) {
    return {proposerHead, isHeadTimely, notReorgedReason: NotReorgedReason.ParentBlockNotStrong};
}
```

`parentNode` fetched via `getNode(parentBlock.blockRoot, parentBlock.payloadStatus)` — payload-status-aware. ✓ (functionally; spec-link comment is stale, citing phase-0).

**B. `update_proposer_boost_root`** at `forkChoice.ts:667-675`:

```typescript
const isTimely = this.isBlockTimely(block, blockDelaySec);
if (
    this.opts?.proposerBoost &&
    isTimely &&
    this.proposerBoostRoot === null
) {
    this.proposerBoostRoot = blockRootHex;
}
```

No proposer-index check. ✗

**C. `is_head_late`** at `forkChoice.ts:1838`:

```typescript
const isHeadLate = !headBlock.timeliness;
```

Uses `ProtoBlock.timeliness` boolean. ✓ (functionally; though same single-boolean tracking issue as #82).

### grandine

**A. `is_parent_strong`**: `reorg_parent_weight_threshold` constant in `types/src/config.rs:152` but NEVER consumed anywhere in `fork_choice_store/` or `fork_choice_control/`. No `is_parent_strong` function exists. ✗

**B. `update_proposer_boost_root`** at `store.rs:3829-3842`:

```rust
if self.slot() == chain_link.slot() && is_before_attesting_interval && is_first_block {
    let state = self.state_cache.state_at_slot(...)?;
    if chain_link.block.message().proposer_index()
        == accessors::get_beacon_proposer_index(&self.chain_config, &state)?
    {
        self.proposer_boost_root = block_root;
    }
}
```

Proposer-index check present (line 3837-3838). ✓

**C. `is_head_late`**: no `is_head_late`, `is_block_late`, or `arrived_early` equivalent in `fork_choice_store/` or `fork_choice_control/`. ✗

## Cross-reference table

| Client | A: `is_parent_strong` payload-aware | B: `update_proposer_boost_root` canonical-proposer check | C: `is_head_late` equivalent |
|---|---|---|---|
| **prysm** | ✗ raw consensus-Node weight | ✗ no check | ✓ (via `arrivedEarly`) |
| lighthouse | ✓ `proto_array_fork_choice.rs:754-759` | ✓ `fork_choice.rs:830-841` | ✓ per-node field |
| teku | ✓ `ForkChoiceUtilGloas.java:406-415` | ✓ `ForkChoice.java:913-915` | ✓ `BlockTimelinessTracker.java:92` |
| nimbus | — (no FC, #79) | — | — |
| **lodestar** | ✓ functionally (phase-0 spec link comment stale) | ✗ no proposer-index check | ✓ via `ProtoBlock.timeliness` |
| **grandine** | ✗ `reorg_parent_weight_threshold` defined but never used; no `is_parent_strong` impl | ✓ `store.rs:3837-3838` | ✗ no late-head detection |

**Per-finding splits**:
- A (`is_parent_strong`): prysm, grandine.
- B (`update_proposer_boost_root` proposer-index): prysm, lodestar.
- C (`is_head_late`): grandine.

**Combined splits** for this item: `[prysm, lodestar, grandine]`.

## Empirical tests

### Source-level confirmation per client

- A: `grep -rn "reorg_parent_weight_threshold\|REORG_PARENT_WEIGHT_THRESHOLD\|ReorgParentWeightThreshold" vendor/<client>/<src>` and verify it's referenced from a is_parent_strong-like function with payload-aware variant lookup.
- B: `grep -rn "proposerBoostRoot = \|proposer_boost_root = " vendor/<client>/<src>` and verify the proposer-index check appears in the conditional.
- C: `grep -rn "is_head_late\|isHeadLate\|isBlockLate\|arrivedEarly\|is_block_late\|block_was_timely" vendor/<client>/<src>` and verify it exists.

### Suggested empirical scenarios

**Scenario A (parent-strong)**: at slot S+1, head is at slot S with mixed FULL+EMPTY variants. Parent at slot S-1 has FULL.weight=10, EMPTY.weight=5, combined consensus-node weight=15. Head builds on FULL of parent. Spec uses parent.FULL.weight=10 for is_parent_strong. Prysm uses combined consensus-node weight=15. If threshold is between 10 and 15, prysm says strong, spec says weak — divergent reorg decision.

**Scenario B (canonical-proposer)**: a non-canonical proposer X publishes a block on time at slot S (perhaps X attempts a reorg with their block instead of the canonical proposer Y's block). Spec's `update_proposer_boost_root`: if X != Y (the canonical proposer per get_head_state), no proposer-boost. Prysm/lodestar: apply proposer-boost to X's block regardless. X gets boost where spec wouldn't.

**Scenario C (late-head)**: head block H arrives at slot S+5s (late). At slot S+1 proposing time, a validator decides whether to reorg H. Spec/lighthouse/teku/lodestar: `is_head_late(H)` = True → eligible for reorg. Grandine: no is_head_late → no late-head reorg attempted → grandine sticks with H.

These are reorg-decision divergences, manifesting only in adversarial / edge scenarios.

## Mainnet reachability

**A (prysm raw consensus weight)**: triggered when FULL and EMPTY variant weights of parent are imbalanced enough that one variant alone is below `parent_threshold` but their sum is above. Reachable on Gloas-active networks with payload-availability stress.

**B (no canonical-proposer check)**: triggered when an attacker tries to inject a non-canonical proposer's block as the proposer-boost target. The attacker's block must arrive on time. The attacker doesn't need to be the canonical proposer — any validator with a signed block claiming to be the slot-S proposer (even with wrong proposer_index) would trigger boost in prysm/lodestar.

Wait — actually a block needs to be valid per `process_block_header`, which checks `block.proposer_index == get_beacon_proposer_index(state)`. So invalid proposer-index blocks are rejected at state-transition. But the spec's check in `update_proposer_boost_root` is against `get_head(store).head_state`, which may differ from `state` (the block's parent state).

The divergence arises when get_head(store).head_state has a DIFFERENT canonical proposer at slot S than the block's parent state. This can happen during epoch transitions or after reorgs. Both states might compute differently due to RANDAO seed differences if they're on different forks.

Without the spec's check, prysm/lodestar apply boost based only on (timely, first-block) — even if the proposer doesn't match the canonical-chain proposer at the current head's view. Adversarially, this could be used to bias proposer-boost toward off-chain proposers.

**C (grandine no late-head reorg)**: every slot where the head arrives late, grandine misses the reorg opportunity that spec-conformant clients take. Grandine is more conservative — sticks with late heads where others reorg.

**Triggering actor**: any proposer/builder for A/B; honest network latency for C.

**Frequency**: A and B are rare (require specific imbalances or RANDAO-state divergence); C is every late-block scenario.

**Pre-Glamsterdam mainnet impact**: zero. Operational on Gloas-active testnets and on mainnet after Glamsterdam activation. Hence `mainnet-glamsterdam`.

## Conclusion

Three Gloas reorg-helper findings, each a small surface but each with at least one client divergence:

- **Finding A (`is_parent_strong`)**: prysm uses raw consensus-Node weight (sum of variants) instead of variant-specific weight matching head's chain. Grandine defines the threshold constant but never implements the function — never gates reorg on parent strength.
- **Finding B (`update_proposer_boost_root`)**: prysm and lodestar lack the spec's canonical-proposer-index match check. Proposer-boost applies to any timely first-seen block regardless of whether its proposer matches the canonical chain's proposer at current slot.
- **Finding C (`is_head_late`)**: grandine has no late-head detection at all — no `is_head_late`, `is_block_late`, or `arrived_early` equivalent. Grandine's `get_proposer_head` cannot evaluate late-head-eligible reorgs.

**Verdict: impact mainnet-glamsterdam.** Splits `[prysm, lodestar, grandine]`.

Resolution options:

- **Prysm**: in `is_parent_strong`-equivalent (`reorg_late_blocks.go:96,159`), use the parent's specific variant weight matching head's chain (e.g., `s.fullNodeByRoot[parent.root].weight` if head's chain declares parent FULL, else `s.emptyNodeByRoot[parent.root].weight`). In proposer-boost assignment (`store.go:183`), add the proposer-index check against canonical-chain proposer.
- **Lodestar**: in `update_proposer_boost_root`-equivalent (`forkChoice.ts:668-675`), add proposer-index check. Update spec-link comment for `is_parent_strong` to Gloas.
- **Grandine**: implement `is_parent_strong` using `parent.attesting_balances.full` or `.empty` based on this block's view of parent's payload-presence (mirror the existing `score()` parent_attestation_score logic). Implement `is_head_late` based on block arrival timestamp (track at block-insertion time, similar to prysm's `arrivedEarly`).

## Cross-cuts

### With item #76 (fork-choice surface scan)

Items #3, #4, #5 from this item's audit close adjacent untouched references in #76.

### With item #82 (`record_block_timeliness` + proposer-boost equivocation suppression)

#82 documented the PTC-timeliness branch missing in 4 clients. #84-B documents the canonical-proposer-index branch missing in 2 clients (different scope, different missing piece). Both gate proposer-boost application but on different conditions.

### With item #83 (`is_head_weak` equivocating-committee monotonicity)

#83 documented the equivocating-committee term missing in prysm and lodestar. #84-A is the corresponding "parent" check (is_parent_strong cousin). The reorg-decision pair (`is_head_weak` + `is_parent_strong`) needs both halves correct; prysm has both wrong; lodestar has the head-side wrong and the parent-side correct.

### With item #67 (lodestar builder-sweep)

Independent surface but same client family — lodestar accumulates Gloas fork-choice gaps in addition to state-transition gaps.

## Adjacent untouched

1. **Empirical simulator harness** could exercise A, B, C scenarios end-to-end against each client's actual implementation.
2. **`get_proposer_head` Gloas modification** — uses both `is_head_weak` (#83) and `is_parent_strong` (#84-A). Per-client end-to-end audit would close the proposer-reorg loop.
3. **`shouldOverrideForkChoiceUpdate` Gloas modification** — late-head FCU override; cousin to #84-C.
4. **Cross-fork transition** at `GLOAS_FORK_EPOCH`: how each client handles the boundary slot's proposer-boost, parent-strength, and head-lateness queries.
