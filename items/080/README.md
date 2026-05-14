---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-14
builds_on: [76, 79]
eips: [EIP-7732]
splits: [prysm, lodestar, grandine]
# main_md_summary: spec `is_supporting_vote` returns False for FULL/EMPTY variants when `message.slot == block.slot` (same-slot vote) — lighthouse and teku correctly route same-slot votes to PENDING bucket only; prysm asymmetrically routes same-slot FULL votes to FULL bucket (EMPTY votes to PENDING); lodestar routes same-slot votes directly to FULL/EMPTY variants per `payloadPresent`; grandine accumulates same-slot votes into FULL/EMPTY buckets via `attesting_balances.full/empty`; affects fork-choice scoring of FULL/EMPTY variants of any block from 2+ slots ago
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 80: `get_attestation_score` / `is_supporting_vote` — same-slot vote handling — prysm/lodestar/grandine route to FULL/EMPTY buckets where spec requires PENDING-only

## Summary

Spec's `is_supporting_vote` (`vendor/consensus-specs/specs/gloas/fork-choice.md:362-387`) explicitly returns `False` for `FULL/EMPTY` variants when `message.slot == block.slot`:

```python
def is_supporting_vote(store, node, message):
    block = store.blocks[node.root]
    if node.root == message.root:
        if node.payload_status == PAYLOAD_STATUS_PENDING:
            return True
        assert message.slot >= block.slot
        if message.slot == block.slot:
            return False                # <-- both FULL and EMPTY rejected at same-slot
        if message.payload_present:
            return node.payload_status == PAYLOAD_STATUS_FULL
        else:
            return node.payload_status == PAYLOAD_STATUS_EMPTY
    else:
        ancestor = get_ancestor(store, message.root, block.slot)
        return node.root == ancestor.root and (...)
```

The PENDING-only branch fires when a validator's attestation has `data.slot == store.blocks[data.beacon_block_root].slot` — i.e., the validator attests at slot S for a block that is itself at slot S. In Gloas, this is the **common case** for honest on-time attestations: the block at slot S arrives in 0-4s, attestations are due at `ATTESTATION_DUE_BPS ≈ 4s`, and an attester who saw block-S by the deadline attests with `data.slot=S` and `data.beacon_block_root = block-at-S`. So `message.slot == block.slot` is the typical case for first-slot attestations.

Spec routes these votes to the PENDING variant's score only. The vote contributes to FULL/EMPTY variants only after a later-slot attestation supersedes the same-slot vote.

`get_attestation_score(store, node, state)` at `fork-choice.md:464-491` consumes `is_supporting_vote` directly. Per-client implementations diverge structurally:

| Client | Same-slot routing | Verdict |
|---|---|---|
| **prysm** | `resolveVoteNode(root, slot, payloadStatus)` routes EMPTY votes to PENDING (`slot == en.node.slot` branch); routes FULL votes to FULL payload-node **regardless of slot** | **✗ asymmetric: FULL same-slot votes diverge** |
| lighthouse | `is_supporting_vote(node, message)` returns False for `message.slot <= block.slot()` | ✓ spec-conformant |
| teku | `resolveVoteNode(voteRoot, voteSlot, payloadPresent)` returns base (PENDING) node when `voteSlot <= blockSlot` | ✓ spec-conformant |
| nimbus | no Gloas fork-choice integration | — (covered by #79) |
| **lodestar** | `addLatestMessage(...)` routes vote to FULL/EMPTY variant node directly via `getNodeIndexByRootAndStatus(nextRoot, nextPayloadStatus)` — no slot check | **✗ all same-slot votes routed to FULL/EMPTY** |
| **grandine** | `attestation_balance_differences` always subtracts from `differences_entry.pending` AND from `differences_entry.full` (if payload_present) or `differences_entry.empty` (if not) — no slot check; `score()` consumes parent.attesting_balances.full/empty | **✗ all same-slot votes counted in FULL/EMPTY buckets** |

Three clients (prysm, lodestar, grandine) diverge from spec on this point. Two clients (lighthouse, teku) correctly route same-slot votes to PENDING only. The sixth client (nimbus) has no Gloas fork-choice at all (item #79).

This affects `get_attestation_score(FULL_variant)` and `get_attestation_score(EMPTY_variant)` whenever there are unrotated same-slot votes for the block. In typical operation, validators attest once per epoch; their `latest_message` persists for ~32 slots. So same-slot votes recorded at slot S continue to influence FULL/EMPTY scoring at slots S+2 through S+32 (after the immediate previous-slot special-case zeroing in `get_weight` no longer applies).

**Spec interpretation question**: it is plausible the spec's `if message.slot == block.slot: return False` was intended only for the proposer-boost case (where the boost message has `payload_present=False` and `slot=current_slot=block.slot`). The lighthouse comment at `proto_array.rs:1383-1385` frames it this way: "For the proposer boost case: message.slot == current_slot == block.slot, so this returns false — boost does not support EMPTY/FULL of the boosted block itself, only its ancestors." If that interpretation is correct, then prysm/lodestar/grandine are right and lighthouse/teku have unnecessary code that special-cases regular attestations. Either way, the spec text and 4-of-5 client implementations disagree — that's audit-worthy.

## Question

Spec at `vendor/consensus-specs/specs/gloas/fork-choice.md:362-387` (`is_supporting_vote`):

```python
def is_supporting_vote(store: Store, node: ForkChoiceNode, message: LatestMessage) -> bool:
    block = store.blocks[node.root]
    if node.root == message.root:
        if node.payload_status == PAYLOAD_STATUS_PENDING:
            return True
        assert message.slot >= block.slot
        if message.slot == block.slot:
            return False
        if message.payload_present:
            return node.payload_status == PAYLOAD_STATUS_FULL
        else:
            return node.payload_status == PAYLOAD_STATUS_EMPTY
    else:
        ancestor = get_ancestor(store, message.root, block.slot)
        return node.root == ancestor.root and (
            node.payload_status == PAYLOAD_STATUS_PENDING
            or node.payload_status == ancestor.payload_status
        )
```

The branch `if message.slot == block.slot: return False` rejects FULL/EMPTY same-slot voting. Combined with the preceding `if node.payload_status == PAYLOAD_STATUS_PENDING: return True`, the net behavior is:

- For PENDING(R) variant: same-slot votes for R are counted.
- For FULL(R) variant: same-slot votes for R are NOT counted; only votes from slot > block.slot AND payload_present=True.
- For EMPTY(R) variant: same-slot votes for R are NOT counted; only votes from slot > block.slot AND payload_present=False.

`get_attestation_score(store, node: ForkChoiceNode, state)` at `fork-choice.md:464-491` directly applies `is_supporting_vote` filter:

```python
return Gwei(
    sum(
        state.validators[i].effective_balance
        for i in unslashed_and_active_indices
        if (
            i in store.latest_messages
            and i not in store.equivocating_indices
            and is_supporting_vote(store, node, store.latest_messages[i])
        )
    )
)
```

Open questions:

1. **Same-slot regular attestation**: when an attester at slot S attests for block at slot S with payload_present=True, does each client's fork-choice route the vote to PENDING(R) only (spec) or to FULL(R)?
2. **Same-slot regular attestation with payload_present=False**: does each client route to PENDING(R) only or to EMPTY(R)?
3. **Proposer-boost specifically**: at slot S, proposer-boost message has `slot=S, root=proposer_block_at_S, payload_present=False`. Where does this route? (For PENDING(S) it should support; for FULL/EMPTY(S) it should not.)

## Hypotheses

- **H1.** Each client's fork-choice-scoring path correctly routes same-slot votes to PENDING-only per spec.
- **H2.** Each client's `is_supporting_vote`-equivalent function returns False for FULL/EMPTY when `message.slot == block.slot`.
- **H3** *(divergence)*. Some clients route same-slot votes to FULL/EMPTY buckets directly per `payload_present`, ignoring the spec's same-slot-PENDING-only constraint.

## Findings

### prysm

`resolveVoteNode` at `vendor/prysm/beacon-chain/forkchoice/doubly-linked-tree/gloas.go:444-455`:

```go
func (s *Store) resolveVoteNode(r [32]byte, slot primitives.Slot, payloadStatus bool) (*PayloadNode, bool) {
    en := s.emptyNodeByRoot[r]
    if en == nil {
        return nil, true
    }
    if payloadStatus {
        return s.fullNodeByRoot[r], false   // <-- FULL vote → fullNode regardless of slot
    }
    return en, slot == en.node.slot         // <-- EMPTY vote → pending if slot == block.slot, else EMPTY node
}
```

**Asymmetric**: same-slot EMPTY votes correctly route to PENDING (`pending=true` when `slot == en.node.slot`). Same-slot FULL votes **always** route to the FULL payload-node — the slot check is missing from the FULL branch.

Test coverage at `gloas_test.go:1519-1527` validates the EMPTY-pending case but does not test same-slot FULL votes. Confirmed asymmetric handling.

✗ H1 partially; ✗ H2 for FULL-same-slot.

Vote tracking via `Vote.nextPayloadStatus` / `currentPayloadStatus` (`types.go:87-89`) — derived from `attestation.data.index == 1`. When a validator's `latest_message` at slot S for block-S has `nextPayloadStatus=true`, prysm credits FULL(block-S).balance immediately. Spec says credit PENDING(block-S).balance only.

### lighthouse

Explicit `is_supporting_vote` at `vendor/lighthouse/consensus/proto_array/src/proto_array.rs:1369-1400`:

```rust
fn is_supporting_vote(&self, node: &IndexedForkChoiceNode, message: &LatestMessage) -> Result<bool, Error> {
    let block = self.nodes.get(node.proto_node_index)?;
    if node.root == message.root {
        if node.payload_status == PayloadStatus::Pending {
            return Ok(true);
        }
        // For the proposer boost case: message.slot == current_slot == block.slot,
        // so this returns false — boost does not support EMPTY/FULL of the
        // boosted block itself, only its ancestors.
        if message.slot <= block.slot() {
            return Ok(false);
        }
        if message.payload_present {
            Ok(node.payload_status == PayloadStatus::Full)
        } else {
            Ok(node.payload_status == PayloadStatus::Empty)
        }
    } else {
        let ancestor = self.get_ancestor_node(message.root, block.slot())?;
        Ok(node.root == ancestor.root && (
            node.payload_status == PayloadStatus::Pending
            || node.payload_status == ancestor.payload_status))
    }
}
```

`message.slot <= block.slot()` returns False uniformly for FULL/EMPTY at same-slot or earlier. Matches spec semantics with slight tightening (`<=` instead of `==`; the `<` case would violate the `message.slot >= block.slot` assert but lighthouse just returns False instead of panicking).

✓ H1, H2.

### teku

`ForkChoiceModelGloas.resolveVoteNode` at `vendor/teku/storage/src/main/java/tech/pegasys/teku/storage/protoarray/ForkChoiceModelGloas.java:324-345`:

```java
public Optional<ForkChoiceNode> resolveVoteNode(
    final Bytes32 voteRoot,
    final UInt64 voteSlot,
    final boolean payloadPresent,
    final ProtoArray protoArray,
    final BlockNodeVariantsIndex blockNodeIndex) {
  final Optional<ForkChoiceNode> maybeBaseNode = blockNodeIndex.getBaseNode(voteRoot);
  if (maybeBaseNode.isEmpty()) return Optional.empty();

  final Optional<UInt64> blockSlot =
      protoArray.getNode(maybeBaseNode.get()).map(ProtoNode::getBlockSlot);
  if (blockSlot.isPresent() && voteSlot.isLessThanOrEqualTo(blockSlot.get())) {
    return maybeBaseNode;   // <-- voteSlot <= blockSlot → base (PENDING) node
  }
  if (payloadPresent) {
    return blockNodeIndex.getFullNode(voteRoot).or(() -> maybeBaseNode);
  }
  return blockNodeIndex.getEmptyNode(voteRoot).or(() -> maybeBaseNode);
}
```

Same-slot votes correctly route to the base (PENDING) node. Uses `<=` (mirroring lighthouse's tightening from spec's `==`).

✓ H1, H2.

### nimbus

No Gloas fork-choice integration (covered in item #79). The `proto_array.nim` find-head is pure phase-0 style with no payload-status awareness.

### lodestar

`addLatestMessage` at `vendor/lodestar/packages/fork-choice/src/forkChoice/forkChoice.ts:1727-1755`:

```typescript
private addLatestMessage(
    validatorIndex: ValidatorIndex,
    nextSlot: Slot,
    nextRoot: RootHex,
    nextPayloadStatus: PayloadStatus
): void {
    const nextIndex = this.protoArray.getNodeIndexByRootAndStatus(nextRoot, nextPayloadStatus);
    if (nextIndex === undefined) {
        throw new Error(`Could not find proto index for nextRoot ${nextRoot} with payloadStatus ${nextPayloadStatus}`);
    }
    // ... (validator-bounds extension)
    if (existingNextSlot === INIT_VOTE_SLOT || computeEpochAtSlot(nextSlot) > computeEpochAtSlot(existingNextSlot)) {
        this.voteNextIndices[validatorIndex] = nextIndex;
        this.voteNextSlots[validatorIndex] = nextSlot;
    }
}
```

The vote routes directly to `getNodeIndexByRootAndStatus(nextRoot, nextPayloadStatus)` — i.e., to the FULL variant if `nextPayloadStatus=FULL`, EMPTY variant if `nextPayloadStatus=EMPTY`, PENDING variant if `nextPayloadStatus=PENDING`. **No slot check.**

`computeDeltas` at `vendor/lodestar/packages/fork-choice/src/protoArray/computeDeltas.ts:30-159` consumes `voteNextIndices` directly — the variant decision was made at vote-ingestion time, not at delta-computation time.

For a same-slot vote with payloadPresent=True → routes to FULL variant. Spec says route to PENDING only.

✗ H1, H2 for the same-slot case.

### grandine

`attestation_balance_differences` at `vendor/grandine/fork_choice_store/src/store.rs:4080-4101`:

```rust
let differences_entry = differences.entry(latest_message.root).or_default();

differences_entry.pending.sub_assign(balance);

if latest_message.post_gloas::<P>(&self.chain_config) {
    if latest_message.payload_present {
        differences_entry.full.sub_assign(balance);
    } else {
        differences_entry.empty.sub_assign(balance);
    }
}
```

For ANY latest_message (regardless of slot), grandine:
- Subtracts balance from the pending bucket.
- For Gloas messages: subtracts balance from the full bucket (if payload_present) or empty bucket (if not).

**No slot check.** Same-slot votes contribute to FULL/EMPTY buckets along with later-slot votes.

`score()` at `store.rs:1269-1334` consumes these buckets:

```rust
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
```

When comparing siblings, `parent.attesting_balances.full` (and `.empty`) include same-slot votes that spec excludes. Spec's `get_attestation_score(FULL_parent_node)` would return a smaller value than grandine's `parent.attesting_balances.full` in scenarios with same-slot votes for the parent.

✗ H1, H2.

## Cross-reference table

| Client | Same-slot FULL vote routes to | Same-slot EMPTY vote routes to | Spec-conformant for `is_supporting_vote` |
|---|---|---|---|
| **prysm** | **FULL payload-node** (`gloas.go:451-453`) | PENDING consensus-node (`gloas.go:454`) | ✗ asymmetric — FULL case diverges |
| lighthouse | PENDING (returns False; vote not counted for FULL) (`proto_array.rs:1386-1388`) | PENDING (returns False; vote not counted for EMPTY) (`:1386-1388`) | ✓ |
| teku | PENDING (base node) (`ForkChoiceModelGloas.java:338-340`) | PENDING (base node) (`:338-340`) | ✓ |
| nimbus | no Gloas FC (#79) | no Gloas FC (#79) | — |
| **lodestar** | **FULL variant** (`forkChoice.ts:1735, addLatestMessage`) | **EMPTY variant** (`:1735`) | ✗ both directions |
| **grandine** | **FULL bucket** of pending+full (`store.rs:4096`) | **EMPTY bucket** of pending+empty (`:4098`) | ✗ both directions |

Spec-conformant: 2 of 6 (lighthouse, teku).
Divergent: 3 of 6 (prysm asymmetric, lodestar, grandine).
Gapped: 1 of 6 (nimbus, per #79).

## Empirical tests

### Source-level grep confirmation

```bash
# Check each client's same-slot vote routing
grep -rn "message.slot.*block.slot\|messageSlot.*blockSlot\|voteSlot.*blockSlot" vendor/{lighthouse,teku}/<fork-choice-path>
# Returns matches in lighthouse (proto_array.rs:1386) and teku (ForkChoiceModelGloas.java:338)
# Returns no matches in prysm, lodestar, grandine
```

### Suggested empirical scenario test

Construct a fork-choice scenario where same-slot votes alone could change the FULL vs EMPTY tiebreak result for a block. For two children of the same parent — one declaring parent FULL, one declaring parent EMPTY — at slot block.slot + 2 or later (so the previous-slot zeroing doesn't apply):

- All 200 attesters at slot block.slot attest for parent with payload_present=True.
- No later-slot attestations exist (validators in different committees).

Spec: parent FULL weight = 0; parent EMPTY weight = 0; tiebreaker decides.
Prysm: parent FULL weight = 200 × effective_balance; parent EMPTY weight = 0.
Lodestar: same as prysm.
Grandine: parent attesting_balances.full = 200 × effective_balance; .empty = 0.
Lighthouse: 0 / 0; tiebreaker decides.
Teku: 0 / 0; tiebreaker decides.

When the child-declaring-FULL needs to win via weight: prysm/lodestar/grandine pick the FULL child; lighthouse/teku tiebreak (typically picks based on payload-status-tiebreaker → FULL via `should_extend_payload`).

The tiebreaker often produces the same outcome as a direct weight comparison, masking the divergence in many scenarios. A scenario that specifically exposes the difference: contention where weight matters but `should_extend_payload` returns False on one branch (e.g., proposer-boost set adversarially).

Recommended follow-up: full fork-choice simulator harness running spec vs each client's actual implementation. Compare head selection across thousands of random scenarios.

## Mainnet reachability

Same-slot voting is the **common** attestation pattern in Gloas: validators in slot-S committees attest at slot S for the slot-S block when they see it by the attestation deadline (~4s).

Scenario class for fork-choice divergence:
- A block at slot S receives same-slot attestations with payload_present=True from a meaningful fraction of slot-S committees.
- These validators' next attestation isn't until slot S+N (typically S+32, but could be S+1 for some committee members).
- At slot S+2, the FULL/EMPTY variants of block-S are scored (since `block.slot + 1 != current_slot`).
- Spec: FULL(block-S) weight = 0 from same-slot voters; EMPTY(block-S) weight = 0 from same-slot voters.
- Prysm/lodestar/grandine: FULL(block-S) weight = sum of same-slot payload_present=True votes; EMPTY similarly.

When this affects head selection: fork-choice between FULL/EMPTY variants of a 2+ slot old block, where the same-slot vote contribution is the swing factor.

**Triggering actor**: built-in to honest attestation behavior. No adversary needed. The divergence is between spec semantics and 3 client implementations on the common case.

**Frequency**: every Gloas slot.

**Consequence**: prysm/lodestar/grandine credit FULL/EMPTY variants of recent-but-not-immediate-previous blocks more aggressively than spec/lighthouse/teku. This biases head selection toward whichever variant has more same-slot votes. The effect is small per-slot (typically a few hundred validators' effective_balance) but cumulative across slots within an epoch.

**Pre-Glamsterdam mainnet impact**: zero. Gloas is `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` on mainnet. Operational on Gloas-active testnets and on mainnet after Glamsterdam activation. Hence the impact classification `mainnet-glamsterdam`.

## Conclusion

T6 from item #76 ("`get_attestation_score` Gloas modification") closes with a 3-vs-2 divergence on same-slot vote handling. Spec's `is_supporting_vote` returns False for FULL/EMPTY when `message.slot == block.slot`; lighthouse and teku implement this faithfully; prysm (asymmetrically), lodestar, and grandine route same-slot FULL/EMPTY votes to their respective variants.

**Verdict: impact mainnet-glamsterdam.** Splits `[prysm, lodestar, grandine]`. The divergence biases fork-choice scoring of FULL/EMPTY variants but the effect on head selection is scenario-dependent and may be partially masked by the `get_payload_status_tiebreaker` for previous-slot blocks (where weights are zeroed) or for adversarial-proposer-boost scenarios (where tiebreaker dominates).

Resolution options:

1. **Spec clarification**: if the `message.slot == block.slot: return False` rule was intended only for proposer-boost, the spec should be amended to special-case proposer-boost rather than all same-slot messages. Lighthouse's comment frames it as the proposer-boost case.
2. **Client conformance**: if the spec rule is intentional for regular attestations, prysm/lodestar/grandine need to add slot checks to their vote-routing logic. Concretely:
   - prysm: add `slot == en.node.slot` check to the FULL branch of `resolveVoteNode`.
   - lodestar: in `addLatestMessage`, fall back to PENDING variant when `nextSlot == nextBlock.slot`.
   - grandine: in `attestation_balance_differences`, conditionalize the full/empty bucket updates on `latest_message.slot > store.blocks[latest_message.root].slot`.
3. **EF spec-test corpus**: add fixtures exercising same-slot vote handling to force client conformance.

Comparison with prior audit items:
- #67, #77, #78, #79 are each one-client divergences. #80 is a three-client divergence indicating ambiguous spec semantics.
- The spec text is unambiguous but the client implementations suggest spec authors and client teams may not have aligned on the same-slot semantics. Worth raising with the consensus-specs editors.

## Cross-cuts

### With item #76 (fork-choice surface scan)

Item #76's T6 entry now closes. Updates item #76's table.

### With item #77 (lodestar `is_payload_data_available`)

Both this and #77 are lodestar fork-choice divergences. #77's missing `is_payload_data_available` and #80's missing slot-check in `addLatestMessage` are independent; #80 is broader (affects 3 clients), #77 is lodestar-specific.

### With item #79 (nimbus complete fork-choice gap)

Nimbus is excluded from this audit because its fork-choice has no Gloas integration at all. Once nimbus implements Gloas fork-choice, the question of same-slot vote routing needs to be re-asked.

### Cross-spec consultation

The same-slot rule in `is_supporting_vote` may benefit from a clarification request to the consensus-specs editors. If the rule was intended for proposer-boost only, the spec text should be more explicit. If it was intentional for regular attestations, 3 client teams need to update.

## Adjacent untouched

1. **Empirical scenario testing** as outlined above. Fork-choice simulator harness comparing spec vs each client implementation.
2. **EF spec-test corpus coverage** of same-slot vote scenarios at `vendor/consensus-specs/tests/.../gloas/fork_choice/...`. Verify whether any test case exercises the `message.slot == block.slot` branch.
3. **`get_proposer_score` interaction**: proposer-boost adds to PENDING variant only (lodestar's `applyScoreChanges:367-369`). Verify other clients also exclude proposer-boost from FULL/EMPTY variants.
4. **`get_weight` semantic divergence**: even if `get_attestation_score` were corrected, `get_weight` itself special-cases previous-slot FULL/EMPTY to return 0. This special case is implementation-dependent — verify each client implements it identically.
5. **Cross-fork transition**: at Gloas activation slot, votes from pre-Gloas attestations have undefined `payload_present` semantics. Each client's handling of the boundary slot needs verification.
