---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-14
builds_on: [76, 79]
eips: [EIP-7732]
splits: [prysm, teku, lodestar, grandine]
# main_md_summary: spec `record_block_timeliness` records 2 booleans per block (`[ATTESTATION_TIMELINESS_INDEX, PTC_TIMELINESS_INDEX]`) used by `should_apply_proposer_boost` to suppress boost when an early (PTC-timely) equivocation exists from the same proposer — only lighthouse implements both the 2-tuple tracking and the equivocation suppression branch; teku tracks both but skips the suppression (TODO); prysm/lodestar use single-boolean timeliness; grandine uses raw equivocation count without PTC-timeliness filter (more strict than spec)
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 82: `record_block_timeliness` 2-tuple + `should_apply_proposer_boost` equivocation suppression — only lighthouse fully implements

## Summary

Gloas modifies `record_block_timeliness` (`vendor/consensus-specs/specs/gloas/fork-choice.md:583-599`) to record **two** booleans per block instead of phase-0's one:

```python
def record_block_timeliness(store: Store, root: Root) -> None:
    block = store.blocks[root]
    seconds_since_genesis = store.time - store.genesis_time
    time_into_slot_ms = seconds_to_milliseconds(seconds_since_genesis) % SLOT_DURATION_MS
    attestation_threshold_ms = get_attestation_due_ms()
    is_current_slot = get_current_slot(store) == block.slot
    ptc_threshold_ms = get_payload_attestation_due_ms()
    store.block_timeliness[root] = [
        is_current_slot and time_into_slot_ms < threshold
        for threshold in [attestation_threshold_ms, ptc_threshold_ms]
    ]
```

The 2-tuple feeds two separate fork-choice helpers:

1. **`ATTESTATION_TIMELINESS_INDEX = 0`** — used by `update_proposer_boost_root` (`fork-choice.md:607`) to apply proposer-boost to the first attestation-timely block in the slot, and by `is_head_late` (`:676`) for late-head detection.
2. **`PTC_TIMELINESS_INDEX = 1`** — used by `should_apply_proposer_boost` (`:449-460`) to detect "early equivocations" — sibling blocks from the same proposer at the same slot that arrived before the PTC threshold. If any early equivocation exists, proposer-boost is suppressed:

```python
equivocations = [
    root
    for root, block in store.blocks.items()
    if (
        store.block_timeliness[root][PTC_TIMELINESS_INDEX]
        and block.proposer_index == parent.proposer_index
        and block.slot + 1 == slot
        and root != parent_root
    )
]
return len(equivocations) == 0
```

**Cross-client status**:

| Client | 2-tuple tracking | PTC timeliness used in equivocation suppression | Verdict |
|---|---|---|---|
| lighthouse | ✓ `proto_array.rs:142-145` separate `attestation_threshold` and `ptc_threshold` fields | ✓ `proto_array.rs:731-743` walks nodes checking `block_timeliness_ptc_threshold` | spec-conformant |
| **teku** | ✓ `BlockTimeliness(isTimelyAttestation, isTimelyPtc)` | **✗ TODO comment at `ForkChoiceUtilGloas.java:163-167`: "the proposer-equivocation branch is intentionally not implemented yet"** | tracks but doesn't consume |
| **prysm** | ✗ no `block_timeliness` map; uses pre-Gloas single timeliness via `BlockReceived` time | **✗ `shouldApplyProposerBoost` has no equivocation check (`gloas.go:487-508`)** | structural gap |
| nimbus | — (no Gloas fork-choice integration, #79) | — | covered by #79 |
| **lodestar** | ✗ single boolean `timeliness` on `ProtoBlock` (`forkChoice.ts:755`); only attestation timeliness | **✗ no `should_apply_proposer_boost`; proposer-boost applied unconditionally when first-timely** | structural gap |
| **grandine** | ✗ no `block_timeliness` tracking; uses raw equivocation count | **partial — `exhibits_equivocation_on_blocks` (`store.rs:618-636`) counts ALL siblings without PTC-timeliness filter** | more strict than spec |

**Only lighthouse fully implements both the 2-tuple tracking and the equivocation suppression branch.** Teku tracks but doesn't consume. Prysm, lodestar have no equivocation suppression. Grandine has equivocation suppression but counts ALL siblings, not just PTC-timely ones — more restrictive than spec.

**Splits** include both "wrong direction" gaps (4 clients are too permissive — don't suppress boost on early equivocation) AND one "wrong direction" gap (grandine is too strict — suppresses boost on late equivocations too). Both are divergences from spec.

## Question

Spec at `vendor/consensus-specs/specs/gloas/fork-choice.md:583-599` (`record_block_timeliness`), `:411-426` (constants `ATTESTATION_TIMELINESS_INDEX=0`, `PTC_TIMELINESS_INDEX=1`), `:601-619` (`update_proposer_boost_root` uses ATTESTATION index), `:428-461` (`should_apply_proposer_boost` uses PTC index).

Open questions:

1. Does each client record a 2-tuple `[is_attestation_timely, is_ptc_timely]` per block?
2. Does each client's `should_apply_proposer_boost` consume the PTC-timeliness bit to suppress boost when an early equivocation exists?
3. Does each client's equivocation suppression filter by PTC-timeliness (spec) or count all siblings (more strict)?

## Hypotheses

- **H1.** Each client records 2-tuple `[attestation_timeliness, ptc_timeliness]` per block.
- **H2.** Each client's `should_apply_proposer_boost` checks for PTC-timely equivocations.
- **H3** *(divergence)*. Some clients have single-boolean timeliness, skip the equivocation suppression entirely, or count all siblings instead of PTC-timely ones.

## Findings

### prysm

No `block_timeliness` map exists in prysm's fork-choice. `shouldApplyProposerBoost` at `vendor/prysm/beacon-chain/forkchoice/doubly-linked-tree/gloas.go:487-508`:

```go
func (s *Store) shouldApplyProposerBoost() bool {
    if s.proposerBoostRoot == [32]byte{} { return false }
    if slots.ToEpoch(s.currentSlot()) < params.BeaconConfig().GloasForkEpoch { return true }
    en := s.emptyNodeByRoot[s.proposerBoostRoot]
    if en == nil { return false }
    n := en.node
    p := n.parent
    if p == nil { return true }
    if p.node.slot+1 != n.slot { return true }
    return p.weight*100 >= s.committeeWeight*params.BeaconConfig().ReorgHeadWeightThreshold
}
```

Step-by-step:
- Line 491-493: pre-Gloas → True.
- Line 494-497: missing empty node → False.
- Line 504-506: parent NOT in previous slot → True (matches spec).
- Line 507: weak-parent check via raw weight comparison.

**Missing**: spec's PTC-timely equivocation suppression branch. Prysm applies boost when parent is strong; suppresses when parent is weak; never checks for proposer equivocations.

✗ H1 (no block_timeliness map). ✗ H2 (no equivocation check).

### lighthouse

`ProtoNodeV29` at `vendor/lighthouse/consensus/proto_array/src/proto_array.rs:142-145`:

```rust
pub block_timeliness_attestation_threshold: bool,
pub block_timeliness_ptc_threshold: bool,
```

Initialization at `proto_array.rs:610-616`:

```rust
// Anchor gets [True, True]. Others computed from time_into_slot.
block_timeliness_attestation_threshold: is_anchor
    || (is_current_slot && time_into_slot < spec.get_attestation_due::<E>(current_slot)),
block_timeliness_ptc_threshold: is_anchor
    || (is_current_slot && time_into_slot < spec.get_payload_attestation_due()),
```

`should_apply_proposer_boost` at `proto_array.rs:688-746` implements all three spec branches:

```rust
// Apply proposer boost if `parent` is not from the previous slot
if parent.slot().saturating_add(1_u64) < slot {
    return Ok(true);
}
// Apply proposer boost if `parent` is not weak
if !self.is_head_weak::<E>(parent, justified_balances, spec) {
    return Ok(true);
}
// Parent is weak. Apply boost unless there's an equivocating block at
// the parent's slot from the same proposer.
let has_equivocation = self.nodes.iter().any(|node| {
    if let Ok(timeliness) = node.block_timeliness_ptc_threshold()
        && let Ok(proposer_index) = node.proposer_index() {
        timeliness
            && Ok(proposer_index) == parent_proposer
            && node.slot() == parent_slot
            && node.root() != parent_root
    } else { false }
});

Ok(!has_equivocation)
```

Filters by `timeliness` (PTC-timeliness bit) per spec. ✓ H1, H2.

### teku

`BlockTimelinessTracker` at `vendor/teku/storage/src/main/java/tech/pegasys/teku/storage/client/BlockTimelinessTracker.java:54-86` records `BlockTimeliness(isTimelyAttestation, isTimelyPtc)` — 2-tuple. ✓ H1.

But `shouldApplyProposerBoost` at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/util/ForkChoiceUtilGloas.java:176-207`:

```java
@Override
public boolean shouldApplyProposerBoost(...) {
    // ...
    // Apply proposer boost if parent is not from the previous slot
    if (maybeParentSlot.get().increment().isLessThan(blockSlot)) {
        return true;
    }
    // TODO-GLOAS: implement the Gloas equivocation suppression branch from
    // should_apply_proposer_boost
    // using recorded PTC timeliness instead of routing a predicate through ForkChoice.
    // ...
    return true;
}
```

After the parent-slot check, teku unconditionally returns `true`. The TODO comment explicitly acknowledges that the equivocation suppression branch is "intentionally not implemented yet" (lines 163-167). Teku also doesn't implement the `is_head_weak` check in this code path.

✓ H1 (tracks 2-tuple). ✗ H2 (doesn't consume PTC timeliness for equivocation suppression).

### nimbus

No Gloas fork-choice integration (#79). No block_timeliness tracking. No proposer-boost equivocation suppression.

### lodestar

`ProtoBlock.timeliness` at `vendor/lodestar/packages/fork-choice/src/forkChoice/forkChoice.ts:755`:

```typescript
timeliness: isTimely,
```

Single boolean. `isBlockTimely` at `forkChoice.ts:1431-1435`:

```typescript
protected isBlockTimely(block: BeaconBlock, blockDelaySec: number): boolean {
    const fork = this.config.getForkName(block.slot);
    const isBeforeLateBlockCutoff = blockDelaySec * 1000 < this.config.getAttestationDueMs(fork);
    return this.fcStore.currentSlot === block.slot && isBeforeLateBlockCutoff;
}
```

Only attestation timeliness; PTC timeliness not tracked.

Proposer-boost is applied unconditionally when the block is timely (`forkChoice.ts:667-675`):

```typescript
const isTimely = this.isBlockTimely(block, blockDelaySec);
if (
    this.opts?.proposerBoost &&
    isTimely &&
    // only boost the first block we see
    this.proposerBoostRoot === null
) {
    this.proposerBoostRoot = blockRootHex;
}
```

No `should_apply_proposer_boost` function exists. No equivocation suppression.

✗ H1 (single boolean). ✗ H2 (no equivocation check).

### grandine

No `block_timeliness` map exists. `should_apply_proposer_boost` at `vendor/grandine/fork_choice_store/src/store.rs:1216-1248`:

```rust
fn should_apply_proposer_boost(&self) -> bool {
    let Some(chain_link) = self.chain_link(self.proposer_boost_root) else { return false; };
    let parent_root = chain_link.parent_root();
    let Some(parent) = self.chain_link(parent_root) else { return false; };

    if parent.slot() + 1 < chain_link.slot() {
        return true;
    }

    let is_head_weak = match self.is_head_weak(parent_root) { ... };
    if !is_head_weak { return true; }

    !self.exhibits_equivocation_on_blocks(
        chain_link.slot().saturating_sub(1),
        parent.block.message().proposer_index(),
        parent_root,
    )
}
```

`exhibits_equivocation_on_blocks` at `store.rs:618-636`:

```rust
pub fn exhibits_equivocation_on_blocks(
    &self,
    slot: Slot,
    proposer_index: ValidatorIndex,
    block_root: H256,
) -> bool {
    self.unfinalized_locations.values().any(|location| {
        let chain_link = &self.unfinalized[segment_id][*position].chain_link;
        chain_link.block.message().slot() == slot
            && chain_link.block.message().proposer_index() == proposer_index
            && chain_link.block_root != block_root
    })
}
```

Walks all unfinalized blocks. Counts any sibling at the same slot from the same proposer — **without** the PTC-timeliness filter.

Spec: counts only `block_timeliness[root][PTC_TIMELINESS_INDEX] == True` equivocations.
Grandine: counts ALL equivocations (timely or late).

Grandine is **more strict** than spec — it suppresses proposer-boost when late equivocations exist; spec only suppresses when early equivocations exist.

✗ H1 (no block_timeliness). Partial H2 (has equivocation check but lacks PTC-timeliness filter — more strict than spec).

## Cross-reference table

| Client | 2-tuple `block_timeliness` (H1) | `should_apply_proposer_boost` consumes PTC-timeliness (H2) | Verdict |
|---|---|---|---|
| **prysm** | ✗ no tracking | ✗ no equivocation check | structural gap; too permissive |
| lighthouse | ✓ separate fields `proto_array.rs:142-145` | ✓ `proto_array.rs:731-743` filters by `block_timeliness_ptc_threshold` | ✓ spec-conformant |
| **teku** | ✓ `BlockTimeliness` 2-tuple | ✗ TODO at `ForkChoiceUtilGloas.java:163-167`; returns True unconditionally after parent-slot check | tracks but doesn't consume |
| nimbus | — (no FC, #79) | — | covered by #79 |
| **lodestar** | ✗ single `timeliness` boolean (`forkChoice.ts:755`) | ✗ no `should_apply_proposer_boost`; boost applied unconditionally on timely | structural gap; too permissive |
| **grandine** | ✗ no tracking | partial — `exhibits_equivocation_on_blocks` (`store.rs:618`) counts all siblings | more strict than spec; suppresses boost on late equivocations too |

**1 of 6 spec-conformant (lighthouse).**
**5 of 6 divergent (prysm, teku, lodestar, grandine, nimbus).**

## Empirical tests

### Source-level confirmation per client

```bash
# Look for 2-tuple block timeliness tracking
grep -rn "block_timeliness_ptc\|isTimelyPtc\|PTC_TIMELINESS_INDEX\|payload_attestation_due_ms" \
    vendor/{prysm,lighthouse,teku,lodestar,grandine}/<fork-choice paths>
```

Returns:
- lighthouse: `proto_array.rs:145, 615-616, 732`
- teku: `BlockTimelinessTracker.java:74`
- prysm: not present
- lodestar: not present
- grandine: not present

### Suggested empirical scenario

Construct a scenario where a proposer P proposes two blocks B1 and B2 in slot S. Both are PTC-timely (arrived before PTC threshold). At slot S+1, fork-choice decides whether to apply proposer-boost to the block built on B1 vs B2.

Spec:
- `should_apply_proposer_boost`: parent is from previous slot, parent IS weak (typical), and there ARE early equivocations (B1 vs B2). → Suppress boost.

Lighthouse: matches spec (suppress).
Teku: returns True (apply boost) — doesn't check equivocation.
Prysm: returns True if parent is strong; returns False if parent is weak. Doesn't check equivocation specifically.
Lodestar: returns True (apply boost) — no `should_apply_proposer_boost` check.
Grandine: returns False (suppress boost). Matches spec for this case but for the wrong reason — it suppresses for ANY equivocation, not just early ones.

If only one equivocation exists and it's LATE (arrived after PTC threshold):
- Spec: no PTC-timely equivocation → apply boost.
- Lighthouse: matches spec.
- Grandine: suppresses (late equivocation counted). DIVERGENT from spec.

This is the scenario where grandine's "too strict" divergence matters.

## Mainnet reachability

The divergence has two reachability modes:

**Mode A (under-suppression in prysm/teku/lodestar)**: a malicious proposer publishes two blocks in slot S. Both are early (PTC-timely). At slot S+1, the next proposer builds on one of them. Spec says proposer-boost should be suppressed (early equivocation exists). Prysm/teku/lodestar apply the boost anyway, biasing fork-choice toward the next-proposer's chain.

**Mode B (over-suppression in grandine)**: a proposer publishes block B1 on-time and a duplicate B2 late (after PTC threshold). Spec says no early equivocation → apply proposer-boost. Grandine suppresses boost.

Both modes affect head selection in equivocation scenarios. Probability is low (requires proposer equivocation, which is slashable), but reachable.

**Triggering actor**: equivocating proposer.

**Frequency**: rare — proposers don't equivocate honestly.

**Consequence**: head-selection divergence between spec-conformant clients (lighthouse) and the 4 non-conformant clients.

**Pre-Glamsterdam mainnet impact**: zero. Operational on Gloas-active testnets and on mainnet after Glamsterdam activation. Hence `mainnet-glamsterdam`.

## Conclusion

T8 from item #76 (`record_block_timeliness` Gloas modification) closes with a 1-vs-5 divergence: only lighthouse fully implements both the 2-tuple tracking and the PTC-timeliness-aware equivocation suppression. Prysm, lodestar lack 2-tuple tracking and have no equivocation suppression. Teku tracks the 2-tuple but explicitly defers the suppression branch (TODO). Grandine has equivocation suppression but lacks the PTC-timeliness filter, making it more strict than spec. Nimbus has no Gloas FC integration at all (#79).

**Verdict: impact mainnet-glamsterdam.** Splits `[prysm, teku, lodestar, grandine]` (4 clients with mismatched proposer-boost equivocation handling).

Resolution options:

1. **Teku**: complete the TODO — wire the existing `BlockTimeliness.isTimelyPtc` into `shouldApplyProposerBoost` per the spec's equivocation suppression branch.
2. **Lodestar**: extend `ProtoBlock` to carry both attestation and PTC timeliness; implement `should_apply_proposer_boost` per spec.
3. **Prysm**: add `block_timeliness` 2-tuple tracking; implement spec's `should_apply_proposer_boost` with PTC-timeliness-filtered equivocation check.
4. **Grandine**: add `block_timeliness` 2-tuple tracking; filter `exhibits_equivocation_on_blocks` by PTC-timeliness instead of raw sibling count.

The split is interesting: 3 clients under-implement (don't suppress when they should), 1 over-implements (suppresses when it shouldn't). All four diverge from spec, but in opposite directions.

## Cross-cuts

### With item #76 (fork-choice surface scan)

Item #76's T8 entry closes.

### With item #79 (nimbus complete fork-choice gap)

Nimbus is covered by #79; T8 is one of many missing pieces.

### With items #77, #80, #81

T8 is the 4th audit finding involving prysm/lodestar/grandine fork-choice divergences. Together they document a substantial gap in Gloas fork-choice implementation across the audit's 6 CL clients.

### With proposer-boost / equivocation slashing

Spec's PTC-timeliness-filtered equivocation suppression assumes early equivocations are evidence of proposer malice — late equivocations may be benign (e.g., gossip propagation delay). Grandine's over-suppression would penalize benign-but-slow proposers.

## Adjacent untouched

1. **`update_proposer_boost_root` (`fork-choice.md:601-619`)**: uses `block_timeliness[root][ATTESTATION_TIMELINESS_INDEX]` to apply boost to the first attestation-timely block. Verify each client's implementation correctly uses attestation-timeliness (not PTC-timeliness or other variant).
2. **`is_head_late` (`:676`)**: uses `ATTESTATION_TIMELINESS_INDEX`. Verify each client.
3. **Pre-Glamsterdam phase-0-style block timeliness**: how does each client handle the cross-fork transition for block_timeliness?
4. **Spec text clarification**: the comment in teku's `ForkChoiceUtilGloas.java:200` says "Spec should probably be updated" — there's apparent ambiguity about whether the PTC-timeliness equivocation check should consult gossip-layer data structures vs proto-array. Raise with consensus-specs editors.
