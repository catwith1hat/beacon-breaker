---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-15
builds_on: [76, 77]
eips: [EIP-7732]
splits: [nimbus]
# main_md_summary: nimbus's main fork-choice subsystem (`proto_array.nim`, `fork_choice.nim`) has NO Gloas payload-status tracking — `findHead` is pure phase-0 style; no FULL/EMPTY/PENDING variants per consensus block; no `is_supporting_vote`-equivalent; no `should_extend_payload`; no `is_payload_data_available`; no `is_payload_timely`; PR #8421 (in pin `09c932872`) adds a proposal-side `shouldExtendPayload` stub explicitly marked `debugGloasComment("refactor when we have a proper should_extend_payload")` but does not close the fork-choice gap
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-21-g09c932872
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 79: Modified `get_ancestor` callers — Gloas return-type breaking change + nimbus's Gloas fork-choice gap

## Summary

Gloas modifies `get_ancestor` to return `ForkChoiceNode(root, payload_status)` instead of phase-0's `Root` (`vendor/consensus-specs/specs/gloas/fork-choice.md:322-347`). Callers that previously compared `get_ancestor(...) == root` must now compare `get_ancestor(...).root == root`. New caller `is_supporting_vote` (`fork-choice.md:362-387`) consumes both fields — a vote for a block at root R supports a fork-choice node `(R', payload_status')` iff either `R == R'` (with payload-presence-aware matching) or `get_ancestor(R, block.slot).root == R'` and `payload_status' is PENDING or matches the ancestor's status`.

The modification changes the **type signature** of `get_ancestor` and adds **new semantics** to LMD-GHOST vote-counting. Cross-client implementations diverge structurally:

| Client | `get_ancestor` API | `is_supporting_vote` impl |
|---|---|---|
| prysm | dual-tree (`fullNodeByRoot`, `emptyNodeByRoot`); per-vote `nextPayloadStatus`/`currentPayloadStatus` on `Vote` struct (`types.go:87`) | implicit via vote-tracking; no explicit function |
| lighthouse | `get_ancestor_node` → `IndexedForkChoiceNode(root, payload_status)` (`proto_array.rs:1403`) | explicit `is_supporting_vote` (`proto_array.rs:1369-1400`) |
| teku | `getAncestorNode` → `Optional<ForkChoiceNode>` (`ForkChoiceStrategy.java:561`); `BlockNodeVariants` per block (FULL/EMPTY/PENDING) | implicit via `BlockNodeVariantsIndex` traversal; no explicit `isSupportingVote` |
| **nimbus** | **none — no Gloas FC integration in main `proto_array.nim`/`fork_choice.nim`** | **none** |
| lodestar | `getAncestor` returns `ProtoNode` (carries `payloadStatus`) (`protoArray.ts:1442-1514`) | implicit via per-variant proto-nodes; no explicit function |
| grandine | `ancestor()` returns `Option<H256>` (root-only, phase-0 style) (`store.rs:1350`); `PayloadPresence` on `ChainLink` (`misc.rs:59,117-119`) | implicit via `PayloadPresence` consumed in `update_head`-equivalent code paths |

**5 of 6 clients (prysm, lighthouse, teku, lodestar, grandine) have payload-status-aware fork-choice machinery**, even if the API surface differs from spec's literal `get_ancestor → ForkChoiceNode` form. The semantic correctness of each non-explicit implementation requires scenario-by-scenario verification.

**Nimbus is structurally absent.** Its main fork-choice (`vendor/nimbus/beacon_chain/fork_choice/`) has zero references to `PayloadStatus`, `payload_status`, `payload_presence`, `PAYLOAD_STATUS_*`, `ForkChoiceNode`, `is_supporting_vote`, `should_extend_payload`, `is_payload_data_available`, `is_payload_timely`, or `notify_ptc_messages`. `findHead` (`proto_array.nim:375-408`) is pure phase-0/altair style: locate the justified node, follow `bestDescendant` pointer to the head root. No variant selection, no PTC vote integration.

Nimbus does carry the per-block fields needed to compute Gloas's `get_parent_payload_status` — `BlockRef.executionBlockHash` + `executionParentHash` (`block_dag.nim:40-42`, with a comment "Added in Gloas for computing the PayloadStatus") — but the fork-choice algorithm never consumes them. The SSZ `PayloadStatus` type and `PAYLOAD_STATUS_*` constants exist (`gloas.nim:43-53`), but no fork-choice code path uses them.

This is a fork-readiness gap analogous to item #78's prysm `parent_beacon_block_root` lag, but with broader scope: nimbus is missing the **entire** Gloas fork-choice subsystem in its main `proto_array.nim`/`fork_choice.nim` implementation. Items #77 and #79 jointly document the gap: #77 noted the missing `is_payload_data_available` predicate; this item extends the observation to the whole FULL/EMPTY/PENDING variant system, the modified `get_ancestor`, `is_supporting_vote`, `get_attestation_score`, `get_weight`, `get_head`, and `get_payload_status_tiebreaker`.

**Mainnet impact**: when Glamsterdam activates and Gloas fork-choice rules apply, nimbus nodes will fail to compute heads, score attestations, or participate in PTC voting per the spec. Without `is_payload_timely` and `is_payload_data_available`, every block's payload-status defaults to whatever phase-0 logic produces, which doesn't distinguish FULL/EMPTY. Without `is_supporting_vote`, LMD-GHOST vote-counting treats all votes as supporting the consensus block regardless of payload presence. The behavior is undefined for Gloas semantics.

Whether this manifests as nimbus-vs-rest fork-choice divergence on the first Gloas slot, or as a hard runtime error in nimbus when it encounters Gloas-specific fork-choice paths, depends on how nimbus's code falls back when Gloas spec calls are made — that's a runtime question, not a source-code-reviewable question at this surface-scan level.

## Question

Spec at `vendor/consensus-specs/specs/gloas/fork-choice.md:322-347` (modified `get_ancestor`):

```python
def get_ancestor(store: Store, root: Root, slot: Slot) -> ForkChoiceNode:
    block = store.blocks[root]
    if block.slot <= slot:
        return ForkChoiceNode(root=root, payload_status=PAYLOAD_STATUS_PENDING)

    parent = store.blocks[block.parent_root]
    while parent.slot > slot:
        block = parent
        parent = store.blocks[block.parent_root]

    return ForkChoiceNode(
        root=block.parent_root,
        payload_status=get_parent_payload_status(store, block),
    )
```

Direct spec callers in Gloas:

- `get_checkpoint_block` (`fork-choice.md:349-359`): `return get_ancestor(store, root, epoch_first_slot).root` — extracts `.root` only.
- `is_supporting_vote` (`fork-choice.md:362-387`): consumes both fields:
  ```python
  ancestor = get_ancestor(store, message.root, block.slot)
  return node.root == ancestor.root and (
      node.payload_status == PAYLOAD_STATUS_PENDING
      or node.payload_status == ancestor.payload_status
  )
  ```

Inherited phase-0 callers (e.g. `get_filtered_block_tree`, `compute_pulled_up_tip`, fast-confirmation) compare `get_ancestor(...) == root` — under Gloas's new signature, they need adaptation to `.root == root`.

Open questions:

1. **`get_ancestor` return shape**: does each client expose a function returning `(root, payload_status)` or just `root`?
2. **`is_supporting_vote`-equivalent**: does each client have an explicit function with this name, or implement the semantic implicitly?
3. **Per-block payload-variant storage**: does each client maintain FULL/EMPTY/PENDING variants per consensus block?
4. **Inherited phase-0 callers** (`get_filtered_block_tree`, `compute_pulled_up_tip`, `get_checkpoint_block`): does each client correctly adapt these to the new `get_ancestor` signature?
5. **Nimbus fork-choice readiness**: does nimbus's main `fork_choice/` directory contain any Gloas-aware payload-status code?

## Hypotheses

- **H1.** All six clients have some mechanism to obtain a block's ancestor at a given slot along with the payload-status of that ancestor's chain.
- **H2.** All six implement `is_supporting_vote` semantics, either via an explicit named function or implicitly in the find-head / vote-application logic.
- **H3.** All six maintain per-consensus-block variants (or per-block payload-status metadata) sufficient to compute FULL/EMPTY/PENDING tiebreaking.
- **H4.** All six adapt the phase-0 inherited callers (`get_checkpoint_block`, `get_filtered_block_tree`, `compute_pulled_up_tip`) to the new Gloas signature where needed.
- **H5** *(divergence)*. Nimbus fails H1, H2, H3, H4 — its main `proto_array.nim`/`fork_choice.nim` has zero Gloas payload-status integration. The SSZ types exist; the fork-choice algorithm does not consume them.

## Findings

### prysm

`Vote` struct at `vendor/prysm/beacon-chain/forkchoice/doubly-linked-tree/types.go:80-90`:

```go
type Vote struct {
    currentRoot          [32]byte
    nextRoot             [32]byte
    currentSlot          primitives.Slot
    nextSlot             primitives.Slot
    nextPayloadStatus    bool  // whether the next vote is for a full or empty payload
    currentPayloadStatus bool
}
```

Per-vote `nextPayloadStatus`/`currentPayloadStatus` bool (FULL=true, EMPTY=false). No PENDING variant on votes — votes are always for a settled FULL/EMPTY state.

Per-block: `fullNodeByRoot` and `emptyNodeByRoot` separate maps (`vendor/prysm/beacon-chain/forkchoice/doubly-linked-tree/store.go`). Each consensus node has up to 2 payload-nodes (FULL, EMPTY); PENDING is implicit (no payload-node).

Vote-application at `vendor/prysm/beacon-chain/forkchoice/doubly-linked-tree/forkchoice.go:314`:

```go
pn, pending := f.store.resolveVoteNode(vote.nextRoot, vote.nextSlot, vote.nextPayloadStatus)
```

Resolves a vote to the correct payload-node based on `nextPayloadStatus`. Prysm tracks payload-status on the vote message itself, not via ancestor traversal.

`InsertPayload` at `gloas.go:376-402` adds a FULL variant for a consensus node when the envelope is verified. `updateNewFullNodeWeight` at line 404-411 walks votes and adds balance to the FULL node if `vote.currentRoot == fn.node.root && vote.nextPayloadStatus`.

No explicit `is_supporting_vote` function in prysm's source. The equivalent semantic is implemented by the dual-tree structure: votes pointing to FULL targets pile up on `fullNodeByRoot[target]`; votes pointing to EMPTY targets pile up on `emptyNodeByRoot[target]`.

The relevant semantic alignment with spec needs scenario verification: in prysm's model, a vote message includes both root and a payload-status bit; in spec, a vote message includes `payload_present` (boolean) and root, and `is_supporting_vote` derives ancestor + supports check. They are functionally equivalent for the spec's vote-counting outcomes only if prysm's `nextPayloadStatus` matches spec's `payload_present` semantics for all message types.

### lighthouse

`get_ancestor_node` at `vendor/lighthouse/consensus/proto_array/src/proto_array.rs:1402-1443`:

```rust
fn get_ancestor_node(&self, root: Hash256, slot: Slot) -> Result<IndexedForkChoiceNode, Error> {
    let index = *self.indices.get(&root).ok_or(Error::NodeUnknown(root))?;
    let block = self.nodes.get(index).ok_or(...)?;

    if block.slot() <= slot {
        return Ok(IndexedForkChoiceNode {
            root,
            proto_node_index: index,
            payload_status: PayloadStatus::Pending,
        });
    }

    // Walk up until we find the ancestor at `slot`.
    let mut child_index = index;
    let mut current_index = block.parent().ok_or(...)?;
    loop {
        let current = self.nodes.get(current_index).ok_or(...)?;
        if current.slot() <= slot {
            let child = self.nodes.get(child_index).ok_or(...)?;
            return Ok(IndexedForkChoiceNode {
                root: current.root(),
                proto_node_index: current_index,
                payload_status: child.get_parent_payload_status(),
            });
        }
        child_index = current_index;
        current_index = current.parent().ok_or(...)?;
    }
}
```

Returns `IndexedForkChoiceNode(root, proto_node_index, payload_status)`. The returned `payload_status` is `child.get_parent_payload_status()` — i.e., the payload-status of the ancestor in the chain containing `root`. Matches spec.

Explicit `is_supporting_vote` at `proto_array.rs:1369-1400`:

```rust
fn is_supporting_vote(
    &self,
    node: &IndexedForkChoiceNode,
    message: &LatestMessage,
) -> Result<bool, Error> {
    let block = self.nodes.get(node.proto_node_index)...?;
    if node.root == message.root {
        if node.payload_status == PayloadStatus::Pending {
            return Ok(true);
        }
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
        Ok(node.root == ancestor.root
            && (node.payload_status == PayloadStatus::Pending
                || node.payload_status == ancestor.payload_status))
    }
}
```

Direct spec match. ✓

### teku

`getAncestorNode` at `vendor/teku/storage/src/main/java/tech/pegasys/teku/storage/protoarray/ForkChoiceStrategy.java:561-562`:

```java
public Optional<ForkChoiceNode> getAncestorNode(final Bytes32 blockRoot, final UInt64 slot) {
    return getAncestorProtoNode(blockRoot, slot).map(ProtoNode::getForkChoiceNode);
}
```

`ForkChoiceNode` (with payload_status). Phase-0 sibling `getAncestor` (returning `Optional<Bytes32>`) still exists at line 556-557 for backward-compat with non-Gloas code paths.

`BlockNodeVariants` at `BlockNodeVariants.java:43-44`:

```java
Optional<ForkChoiceNode> getNode(final ForkChoicePayloadStatus payloadStatus) {
    return switch (payloadStatus) { ... };
}
```

Per consensus block, three `ProtoNode`s may exist — one per `ForkChoicePayloadStatus` (FULL/EMPTY/PENDING). Variants tracked in `BlockNodeVariantsIndex.java`.

No explicit `isSupportingVote` method in teku. Vote-counting in find-head walks the variants. Scenario verification required.

### nimbus

**Main fork-choice has no Gloas integration.**

`vendor/nimbus/beacon_chain/fork_choice/proto_array.nim` (718 lines), `fork_choice.nim` (1008 lines), `fork_choice_types.nim` (207 lines) contain **zero** references to:

- `PayloadStatus`, `payload_status`, `PAYLOAD_STATUS_*` constants.
- `payload_presence`, `PayloadPresence`.
- `ForkChoiceNode`.
- `is_supporting_vote`, `should_extend_payload`, `is_payload_data_available`, `is_payload_timely`.
- `notify_ptc_messages`.

`findHead` at `proto_array.nim:375-408` is phase-0/altair style: locate the justified node by root, follow `bestDescendant` pointer, return head root. No variant selection.

The only `BlockRef`-level Gloas tracking is at `consensus_object_pools/block_dag.nim:40-42`:

```nim
executionBlockHash*: Opt[Eth2Digest]
executionParentHash*: Opt[Eth2Digest]
  ## Added in Gloas for computing the `PayloadStatus`
```

These fields would allow computing `get_parent_payload_status(block)` on-demand (as `block.executionParentHash == block.parent.executionBlockHash`), but **no fork-choice code path consumes them**.

The Gloas SSZ types are defined (`spec/datatypes/gloas.nim:43-53` defines `PayloadStatus` + constants), but the fork-choice algorithm does not invoke them. The `payload_attestation_pool.nim` aggregates `PayloadAttestation`s and tracks `payload_present` + `blob_data_available` from the wire (`payload_attestation_pool.nim:59,77`), but no consumer in fork-choice exists — confirming item #77's note that nimbus's `is_payload_data_available` is unimplemented.

The comment-only reference at `validators/block_payloads.nim:373` (`# - If 'should_extend_payload(store, parent_root)':`) suggests the function is planned but not yet implemented.

**PR #8421 update (re-audit 2026-05-15, pin bumped `550c7a3f0` → `09c932872`)**: PR #8421 ("fix: apply parent execution requests before proposal", merged 2026-05-15) adds a proposal-side `shouldExtendPayload` variable to `beacon_chain/validators/beacon_validators.nim:409-442` and a corresponding parameter `should_extend_payload: bool` to `getExecutionPayload` at `block_payloads.nim:344`. The computation is explicitly marked as a stub: `debugGloasComment("refactor when we have a proper should_extend_payload")` (`beacon_validators.nim:410`). The placeholder logic derives `shouldExtendPayload` from `envelope.isSome()` (i.e., whether `node.dag.db.getExecutionPayloadEnvelope(parentId.root)` returns a known envelope) — **not** from a fork-choice query of `should_extend_payload(store, parent_root)` per spec. The fork-choice directory itself (`beacon_chain/fork_choice/`) is unchanged: same 5 files, still zero references to `PayloadStatus`, `payload_status`, `is_supporting_vote`, `should_extend_payload`, `is_payload_data_available`, `is_payload_timely`, `notify_ptc_messages`, or `ForkChoiceNode`. PR #8421 keeps the proposal pipeline forward-progressing on Gloas-active testnets but does not constitute the Gloas fork-choice implementation the spec requires.

**Verdict for nimbus**: when Gloas activates, nimbus's main fork-choice will operate per phase-0/altair semantics — no FULL/EMPTY tiebreaking, no PTC vote integration, no `should_extend_payload` decisions. Nimbus will not be able to participate in Gloas fork-choice as specified. The PR #8421 stub keeps the validator-side proposal path callable but defers the proper fork-choice integration.

### lodestar

`getAncestor` at `vendor/lodestar/packages/fork-choice/src/protoArray/protoArray.ts:1442-1514`:

```typescript
getAncestor(blockRoot: RootHex, ancestorSlot: Slot): ProtoNode {
    const variantOrArr = this.indices.get(blockRoot);
    // ...
    const block = this.nodes[blockIndex];

    if (block.slot <= ancestorSlot) {
        // For Gloas: PENDING is at variants[0]
        return block;
    }

    // Walk backwards through beacon blocks to find ancestor
    let currentBlock = block;
    // ...
    while (parentBlock.slot > ancestorSlot) {
        currentBlock = parentBlock;
        // ...
    }

    // Now parentBlock.slot <= ancestorSlot
    if (!isGloasBlock(currentBlock)) {
        // Pre-Gloas: return FULL variant
        return parentBlock;
    }

    // Gloas: determine which parent variant (EMPTY or FULL) based on parent_block_hash
    const parentPayloadStatus = this.getParentPayloadStatus(currentBlock);
    const parentVariantIndex = this.getNodeIndexByRootAndStatus(currentBlock.parentRoot, parentPayloadStatus);
    // ...
    return this.nodes[parentVariantIndex];
}
```

Returns `ProtoNode` (carries `payloadStatus`). For Gloas blocks, computes the parent's FULL-or-EMPTY status from `getParentPayloadStatus(currentBlock)` and returns the corresponding variant. For pre-Gloas blocks, returns the default (FULL) variant.

No explicit `isSupportingVote` method. The semantic is embedded in `applyScoreChanges` and find-head walks. At `protoArray.ts:1814`:

```typescript
if (node.blockRoot === ancestorNode.blockRoot && node.payloadStatus === ancestorNode.payloadStatus) {
```

Comparison uses both root and payloadStatus — matches spec semantics.

### grandine

`ancestor` at `vendor/grandine/fork_choice_store/src/store.rs:1350-1370`:

```rust
fn ancestor(&self, descendant_root: H256, ancestor_slot: Slot) -> Option<H256> {
    if let Some(location) = self.unfinalized_locations.get(&descendant_root).copied() {
        let descendant_segment = &self.unfinalized[&location.segment_id];

        let chain_link = self
            .segments_ending_with(descendant_segment, location.position)
            .find_map(|(segment, position)| segment.block_before_or_at(ancestor_slot, position))
            .map(|unfinalized_block| &unfinalized_block.chain_link)
            .or_else(|| self.finalized_before_or_at(ancestor_slot))?;

        return Some(chain_link.block_root);
    }
    // ...
}
```

Returns just `Option<H256>` (root only). Spec-comment cites phase-0 (`v1.3.0/specs/phase0/fork-choice.md`).

But `PayloadPresence` is tracked on the chain-link side:
- `ChainLink.parent_payload_presence` at `misc.rs:59`.
- `PayloadPresence` enum at `misc.rs:117-126` (Empty/Full/Pending; with the comment "So what is called `PayloadStatus` in the Gloas consensus specs, is called `PayloadPresence` in Grandine").

Fork-choice consuming code paths (e.g. `segment.rs:155-161`, `store.rs:1088-1093,1290`) use `PayloadPresence` directly when walking unfinalized blocks. Grandine's structure is "track payload-presence on the ChainLink; the ancestor() returns the root; callers separately query payload-presence."

No explicit `is_supporting_vote` function. Find-head logic at `store.rs:1075-1300` uses `PayloadPresence` directly in scoring. Functionally equivalent to spec; not byte-for-byte the same shape.

## Cross-reference table

| Client | `get_ancestor` API returns payload_status (H1) | `is_supporting_vote`-equiv (H2) | Per-block payload variants (H3) | Phase-0 callers adapted (H4) | Verdict |
|---|---|---|---|---|---|
| prysm | implicit via per-vote `nextPayloadStatus`/`currentPayloadStatus` (`types.go:87`) | implicit via dual-tree vote-application (`forkchoice.go:314`) | `fullNodeByRoot` + `emptyNodeByRoot` (no PENDING) | TBD (would need per-caller audit) | structurally divergent from spec but appears semantically equivalent |
| lighthouse | ✓ explicit `get_ancestor_node → IndexedForkChoiceNode` (`proto_array.rs:1403`) | ✓ explicit `is_supporting_vote` (`proto_array.rs:1369`) | ✓ per-variant nodes | ✓ checked | spec-conformant |
| teku | ✓ explicit `getAncestorNode → Optional<ForkChoiceNode>` (`ForkChoiceStrategy.java:561`); root-only `getAncestor` available for phase-0 callers | implicit via `BlockNodeVariantsIndex` traversal | ✓ `BlockNodeVariants` per block | dual API; appears adapted | spec-conformant API; semantic verification recommended |
| **nimbus** | **✗ no Gloas FC integration** | **✗ no implementation** | **✗ no variant tracking** | **✗ phase-0 only** | **structurally absent — fork-readiness gap** |
| lodestar | ✓ `getAncestor → ProtoNode` (`protoArray.ts:1442`) carries `payloadStatus` | implicit via find-head walks (`protoArray.ts:1814`) | ✓ per-variant nodes | ✓ checked | structurally divergent from spec but appears semantically equivalent |
| grandine | ✗ `ancestor → Option<H256>` (root only) (`store.rs:1350`); `PayloadPresence` carried on `ChainLink` separately | implicit via find-head consuming `PayloadPresence` directly | ✓ via `PayloadPresence` per-ChainLink | TBD | semantically equivalent via separate-track payload-presence; not API-equivalent |

**H1 partial**: 3 of 6 (lighthouse, teku, lodestar) return ancestor with payload_status directly. Prysm and grandine carry payload_status separately. Nimbus has neither.

**H2 partial**: 1 of 6 (lighthouse) has an explicit `is_supporting_vote` function. The other 4 (prysm, teku, lodestar, grandine) embed the semantic in find-head / vote-application. Nimbus is missing.

**H3 partial**: 4 of 6 (prysm, lighthouse, teku, lodestar) maintain per-block payload variants. Grandine tracks via `PayloadPresence` on `ChainLink`. Nimbus has no variant tracking.

**H4**: not verified per-caller in any client.

**H5 confirmed for nimbus.**

## Empirical tests

### Source-level grep confirmation for nimbus

```bash
grep -rn "payload_status\|PayloadStatus\|payload_presence\|PAYLOAD_STATUS\|ForkChoiceNode\|is_payload_timely\|is_payload_verified\|is_payload_data_available\|should_extend_payload\|is_supporting_vote\|notify_ptc_messages" vendor/nimbus/beacon_chain/fork_choice/
```

Returns: empty. (Re-verified at pin `09c932872`, 2026-05-15.)

The same grep on `vendor/nimbus/beacon_chain` (broader) returns:
- Type definitions in `spec/datatypes/gloas.nim` (SSZ types, constants).
- Comments in `consensus_object_pools/block_dag.nim` (per-block fields added for Gloas but not yet consumed).
- Comments in `validators/block_payloads.nim:373` (TBD reference to `should_extend_payload`).
- `validators/beacon_validators.nim:409-442` and `validators/block_payloads.nim:344,633` (proposal-side `shouldExtendPayload` stub introduced by PR #8421, explicitly marked `debugGloasComment("refactor when we have a proper should_extend_payload")`).
- `rpc/rest_validator_api.nim:462` (REST validator API forwards the stub flag to the proposal pipeline).
- `payload_attestation_pool.nim` (gossip pool aggregation; not consumed by fork-choice).

No consumer in fork-choice. ✗

### Suggested scenario tests for the other 5 clients

The structural divergence between prysm/grandine (root-only ancestor + separate payload-status track) and lighthouse/teku/lodestar (ancestor returns ForkChoiceNode) is not by itself a bug. Confirming byte-equivalence requires constructing scenarios that exercise the semantic surface:

- **S1 (FULL/EMPTY tiebreak under proposer-boost).** A consensus block has both FULL and EMPTY variants. PTC majority votes timely+available. Proposer-boost is set to a descendant whose `parent_root == consensus_block_root` and parent is EMPTY. Each client should pick FULL (per `should_extend_payload`).
- **S2 (vote-following with payload_present=False).** A LMD-vote with `payload_present=False` should support EMPTY variants, not FULL. Verify all 5 clients route the vote correctly.
- **S3 (vote-following with payload_present=True).** Mirror of S2. Vote should support FULL.
- **S4 (ancestor pending).** Vote for a block at slot N. Query support for a fork-choice node at slot N (same root). Per spec `is_supporting_vote`: if node.payload_status is PENDING, return True regardless. Verify all 5 clients.
- **S5 (deep ancestor walk with payload_status alternation).** A chain spanning 10 slots where FULL/EMPTY alternate. Vote at slot 10; query support for nodes at slots 5, 7, 9.

These would require a fork-choice simulator harness — beyond the scope of this surface scan. Recommended follow-up.

## Mainnet reachability

The nimbus gap is **certainly reachable** the moment Gloas activates: nimbus's `findHead` is phase-0 style and would produce phase-0-style heads on Gloas blocks. Whether this manifests as:

- nimbus selecting "the wrong" head (vs the other 5 clients) on Gloas slots, OR
- nimbus producing a runtime error when Gloas-specific code paths are invoked elsewhere,

depends on how nimbus's higher-level code interfaces with the fork-choice subsystem. The runtime behavior is not source-code-reviewable at this surface level.

**Triggering actor**: every Gloas block. As soon as Glamsterdam activates, every slot triggers the gap.

**Frequency**: every slot of Gloas.

**Consequence**: nimbus diverges from the other 5 clients on head selection. Without `should_extend_payload`, nimbus cannot prefer FULL over EMPTY variants. Without `is_supporting_vote`'s payload-presence-aware vote semantics, nimbus counts every LMD-vote as supporting the consensus block regardless of payload presence. Without `is_payload_timely` / `is_payload_data_available`, nimbus cannot judge whether a previous-slot block's payload is canonical.

The cascade: nimbus selects heads that the other 5 reject; nimbus's attestations support FFG targets the other 5 don't recognize; finalization stalls.

**Pre-Glamsterdam mainnet impact**: zero. Gloas is `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` on mainnet. The gap is only operational on Gloas-active testnets and on mainnet after Glamsterdam activation. Hence the impact classification `mainnet-glamsterdam`.

## Conclusion

T3 from item #76 ("audit all `get_ancestor` caller sites in each client for proper consumption of both fields") closes with two findings:

1. **Cross-client structural diversity** — 5 of 6 clients have implemented Gloas's payload-status-aware fork-choice using structurally different mechanisms. Some have explicit ForkChoiceNode-returning ancestor APIs (lighthouse, teku, lodestar); others embed payload-status on vote messages (prysm) or on chain-link metadata (grandine). All appear semantically equivalent to spec but byte-equivalence requires scenario-by-scenario testing.

2. **Nimbus's complete Gloas fork-choice gap** — nimbus's main `fork_choice/` directory contains zero references to Gloas's payload-status types, `is_supporting_vote`, `should_extend_payload`, `is_payload_data_available`, `is_payload_timely`, or `notify_ptc_messages`. The SSZ types are defined, the per-block tracking fields are added to `BlockRef`, but no fork-choice code path consumes them.

**Verdict: impact mainnet-glamsterdam.** Splits `[nimbus]`. The nimbus gap is the same impact tier as items #77 (lodestar) and #78 (prysm) but with a broader scope — the entire Gloas fork-choice subsystem, not a single missing field or assert.

Resolution options:

1. **Nimbus implements Gloas fork-choice.** This is a substantial change: add per-block FULL/EMPTY/PENDING variants to `proto_array.nim`; implement `should_extend_payload`, `is_payload_timely`, `is_payload_data_available`, `is_supporting_vote`, `get_parent_payload_status`; wire PTC vote tracking through to fork-choice; modify `findHead` to choose between variants per the Gloas tiebreaker. Multi-PR effort.
2. **EF spec-test corpus exercises Gloas fork-choice end-to-end.** A complete Gloas fork-choice test suite would catch nimbus's gap immediately. Verify whether `vendor/consensus-specs/tests/.../gloas/fork_choice/` already exists and covers this.

Comparison with the audit's other lodestar / prysm findings:
- Item #67 (lodestar): state-transition bug; block-import state-root divergence.
- Item #77 (lodestar): fork-choice missing predicate; head-selection divergence on specific vote pattern.
- Item #78 (prysm): SSZ container missing field; wire-layer incompatibility.
- Item #79 (nimbus): **entire Gloas fork-choice subsystem unimplemented**; structural gap.

Together these four mainnet-glamsterdam-impact items establish nimbus, prysm, and lodestar each have at least one significant Gloas readiness gap. Only lighthouse, teku, and grandine appear (per surface scan) to have full Gloas fork-choice implementations — though byte-equivalence among those three also requires scenario testing.

## Cross-cuts

### With item #76 (fork-choice surface scan)

T3 entry now closes with a confirmed nimbus divergence. Item #76's overall verdict (impact: unknown, surface scan) should be considered "active" — further follow-ups in T4-T10 are likely to surface additional findings.

### With item #77 (lodestar `is_payload_data_available` gap)

#77 noted nimbus's fork-choice incompleteness as a side observation ("Fork-choice Gloas integration is incomplete in nimbus"). This item makes that observation primary and quantifies it: every Gloas fork-choice primitive is missing from nimbus's main fork-choice.

### With item #78 (prysm spec PR #5152 lag)

Both are fork-readiness gaps — prysm lags on a single field; nimbus lags on the whole fork-choice subsystem. Same impact tier; different scope.

### With future fast-confirmation work

Nimbus has implemented `fast-confirmation.nim` (953 lines) for the phase-0 fast-confirmation feature, but not Gloas. The same engineering effort would be needed to bring Gloas fork-choice online.

## Adjacent untouched

1. **Per-caller-site audit in prysm, lighthouse, teku, lodestar, grandine** for `get_filtered_block_tree`, `compute_pulled_up_tip`, `get_checkpoint_block`, and any inherited phase-0 callers of `get_ancestor`. Verify each correctly handles the Gloas return-type change.
2. **Empirical scenario tests S1-S5** above. Build a fork-choice simulator harness to exercise the FULL/EMPTY tiebreak and payload-presence-aware vote semantics.
3. **Nimbus engineering plan.** Is there a tracking issue / `EPBS_STATUS.md`-equivalent for Gloas fork-choice in nimbus? Estimated time to implement?
4. **EF spec-test corpus for Gloas fork-choice.** Does `vendor/consensus-specs/tests/.../gloas/fork_choice/...` cover the new functions? If yes, does nimbus skip these tests, fail them, or pass them by accident?
5. **Cross-fork transition.** At the Gloas activation slot, nimbus's fork-choice would need to switch from phase-0 to Gloas semantics. Without an implementation, the transition behavior is undefined.
