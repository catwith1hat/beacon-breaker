#!/usr/bin/env python3
"""
Gloas fork-choice simulator harness.

Compares spec semantics against each client's source-level semantics for
the divergence scenarios documented in items #77, #80, #81, #82, #83, #84.

Each scenario constructs a minimal fork-choice store fragment and computes
the relevant predicate or score across multiple implementations. The
harness prints MATCH/DIVERGE per (scenario, client) pair.

This is a *semantic* simulator, not a fork-choice replay engine — each
function is implemented inline to match either spec text or each client's
source code (with line citations in the docstrings). The point is to make
the divergences executable rather than to run end-to-end fork-choice.

Run:
    python3 forkchoice_simulator.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

# ============================================================================
# Spec constants
# ============================================================================

PAYLOAD_STATUS_EMPTY = 0
PAYLOAD_STATUS_FULL = 1
PAYLOAD_STATUS_PENDING = 2  # Note: in spec, values are EMPTY=0, FULL=1, PENDING=2 per beacon-chain.md

PTC_SIZE = 512
PAYLOAD_TIMELY_THRESHOLD = PTC_SIZE // 2          # 256
DATA_AVAILABILITY_TIMELY_THRESHOLD = PTC_SIZE // 2  # 256

ATTESTATION_TIMELINESS_INDEX = 0
PTC_TIMELINESS_INDEX = 1

REORG_HEAD_WEIGHT_THRESHOLD_PCT = 20    # 20% of committee
REORG_PARENT_WEIGHT_THRESHOLD_PCT = 160  # 160% of committee

ZERO_ROOT = b"\x00" * 32
EFFECTIVE_BALANCE = 32_000_000_000  # 32 ETH


# ============================================================================
# Minimal types
# ============================================================================


@dataclass
class Block:
    root: bytes
    parent_root: bytes
    slot: int
    proposer_index: int = 0


@dataclass
class LatestMessage:
    slot: int
    root: bytes
    payload_present: bool


@dataclass(frozen=True)
class ForkChoiceNode:
    root: bytes
    payload_status: int


@dataclass
class Store:
    """Minimal fork-choice store fragment for harness scenarios."""
    blocks: Dict[bytes, Block] = field(default_factory=dict)
    payloads: Set[bytes] = field(default_factory=set)
    payload_timeliness_vote: Dict[bytes, List[Optional[bool]]] = field(default_factory=dict)
    payload_data_availability_vote: Dict[bytes, List[Optional[bool]]] = field(default_factory=dict)
    block_timeliness: Dict[bytes, List[bool]] = field(default_factory=dict)
    latest_messages: Dict[int, LatestMessage] = field(default_factory=dict)
    equivocating_indices: Set[int] = field(default_factory=set)
    proposer_boost_root: bytes = ZERO_ROOT
    current_slot: int = 0
    # parent_payload_status per block (which variant of parent this block extends)
    parent_payload_status: Dict[bytes, int] = field(default_factory=dict)
    # Per-slot beacon committee (validator indices)
    committees: Dict[int, List[int]] = field(default_factory=dict)
    # Canonical proposer for slot (used by update_proposer_boost_root)
    canonical_proposer_per_slot: Dict[int, int] = field(default_factory=dict)
    # Per-block payload-attestation-arrival flag (for is_head_weak monotonicity)
    payload_received: Set[bytes] = field(default_factory=set)

    # Active validator count drives committee_weight computations
    active_validator_count: int = 0


def root(label: str) -> bytes:
    """Pretty-print-friendly synthetic block root."""
    return label.encode().ljust(32, b"\x00")[:32]


def committee_weight(store: Store) -> int:
    """Committee weight = active_validator_balance / SLOTS_PER_EPOCH (we'll use a fixed value)."""
    # Spec: total_active_balance / SLOTS_PER_EPOCH. For demo, use active_validator_count.
    return store.active_validator_count * EFFECTIVE_BALANCE // 32  # SLOTS_PER_EPOCH=32


def proposer_score(store: Store) -> int:
    """Spec get_proposer_score: PROPOSER_SCORE_BOOST/100 * committee_weight."""
    return committee_weight(store) * 40 // 100  # PROPOSER_SCORE_BOOST=40


# ============================================================================
# Spec helpers (per vendor/consensus-specs/specs/gloas/fork-choice.md)
# ============================================================================


def spec_is_payload_verified(store: Store, r: bytes) -> bool:
    return r in store.payloads


def spec_is_payload_timely(store: Store, r: bytes) -> bool:
    """fork-choice.md:265-283"""
    if r not in store.payload_timeliness_vote:
        return False
    if not spec_is_payload_verified(store, r):
        return False
    votes = store.payload_timeliness_vote[r]
    return sum(1 for v in votes if v is True) > PAYLOAD_TIMELY_THRESHOLD


def spec_is_payload_data_available(store: Store, r: bytes) -> bool:
    """fork-choice.md:285-302"""
    if r not in store.payload_data_availability_vote:
        return False
    if not spec_is_payload_verified(store, r):
        return False
    votes = store.payload_data_availability_vote[r]
    return sum(1 for v in votes if v is True) > DATA_AVAILABILITY_TIMELY_THRESHOLD


def spec_get_parent_payload_status(store: Store, block: Block) -> int:
    """Returns child's view of parent's payload-status — recorded at block insertion."""
    return store.parent_payload_status.get(block.root, PAYLOAD_STATUS_EMPTY)


def spec_is_parent_node_full(store: Store, block: Block) -> bool:
    return spec_get_parent_payload_status(store, block) == PAYLOAD_STATUS_FULL


def spec_should_extend_payload(store: Store, r: bytes) -> bool:
    """fork-choice.md:398-409"""
    if not spec_is_payload_verified(store, r):
        return False
    if spec_is_payload_timely(store, r) and spec_is_payload_data_available(store, r):
        return True
    proposer_root = store.proposer_boost_root
    if proposer_root == ZERO_ROOT:
        return True
    if proposer_root not in store.blocks:
        return True
    if store.blocks[proposer_root].parent_root != r:
        return True
    if spec_is_parent_node_full(store, store.blocks[proposer_root]):
        return True
    return False


def spec_get_ancestor(store: Store, r: bytes, slot: int) -> ForkChoiceNode:
    """fork-choice.md:328-346 (Gloas signature)"""
    block = store.blocks[r]
    if block.slot <= slot:
        return ForkChoiceNode(root=r, payload_status=PAYLOAD_STATUS_PENDING)
    parent = store.blocks[block.parent_root]
    child = block
    while parent.slot > slot:
        child = parent
        parent = store.blocks[child.parent_root]
    # ancestor.payload_status = how `child` views its parent (whose root we return)
    return ForkChoiceNode(
        root=child.parent_root,
        payload_status=spec_get_parent_payload_status(store, child),
    )


def spec_is_supporting_vote(store: Store, node: ForkChoiceNode, message: LatestMessage) -> bool:
    """fork-choice.md:362-387"""
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
        ancestor = spec_get_ancestor(store, message.root, block.slot)
        return node.root == ancestor.root and (
            node.payload_status == PAYLOAD_STATUS_PENDING
            or node.payload_status == ancestor.payload_status
        )


def spec_get_attestation_score(store: Store, node: ForkChoiceNode) -> int:
    """fork-choice.md:464-491"""
    total = 0
    for validator_index, message in store.latest_messages.items():
        if validator_index in store.equivocating_indices:
            continue
        if spec_is_supporting_vote(store, node, message):
            total += EFFECTIVE_BALANCE
    return total


def spec_should_apply_proposer_boost(store: Store) -> bool:
    """fork-choice.md:428-461"""
    if store.proposer_boost_root == ZERO_ROOT:
        return False
    block = store.blocks[store.proposer_boost_root]
    parent_root = block.parent_root
    if parent_root not in store.blocks:
        return False
    parent = store.blocks[parent_root]
    slot = block.slot
    # Apply proposer boost if parent is not from the previous slot
    if parent.slot + 1 < slot:
        return True
    # Apply proposer boost if parent is not weak
    if not spec_is_head_weak(store, parent_root):
        return True
    # Parent is weak. Check PTC-timely equivocations
    equivocations = [
        r for r, b in store.blocks.items()
        if (
            store.block_timeliness.get(r, [False, False])[PTC_TIMELINESS_INDEX]
            and b.proposer_index == parent.proposer_index
            and b.slot + 1 == slot
            and r != parent_root
        )
    ]
    return len(equivocations) == 0


def spec_get_weight(store: Store, node: ForkChoiceNode) -> int:
    """fork-choice.md:494-529"""
    if node.payload_status == PAYLOAD_STATUS_PENDING or (
        store.blocks[node.root].slot + 1 != store.current_slot
    ):
        attestation_score = spec_get_attestation_score(store, node)
        if not spec_should_apply_proposer_boost(store):
            return attestation_score
        # Synthetic boost message: payload_present=False, slot=current_slot
        message = LatestMessage(
            slot=store.current_slot,
            root=store.proposer_boost_root,
            payload_present=False,
        )
        ps = proposer_score(store) if spec_is_supporting_vote(store, node, message) else 0
        return attestation_score + ps
    else:
        return 0


def spec_is_head_weak(store: Store, head_root: bytes) -> bool:
    """fork-choice.md:679-709 (Gloas: adds equivocating-committee term)"""
    reorg_threshold = committee_weight(store) * REORG_HEAD_WEIGHT_THRESHOLD_PCT // 100
    head_block = store.blocks[head_root]
    head_node = ForkChoiceNode(root=head_root, payload_status=PAYLOAD_STATUS_PENDING)
    head_weight = spec_get_attestation_score(store, head_node)
    # Add equivocating-committee weight (Gloas monotonicity term)
    committee = store.committees.get(head_block.slot, [])
    for i in committee:
        if i in store.equivocating_indices:
            head_weight += EFFECTIVE_BALANCE
    return head_weight < reorg_threshold


def spec_is_parent_strong(store: Store, r: bytes) -> bool:
    """fork-choice.md:712-723"""
    parent_threshold = committee_weight(store) * REORG_PARENT_WEIGHT_THRESHOLD_PCT // 100
    block = store.blocks[r]
    parent_payload_status = spec_get_parent_payload_status(store, block)
    parent_node = ForkChoiceNode(root=block.parent_root, payload_status=parent_payload_status)
    parent_weight = spec_get_attestation_score(store, parent_node)
    return parent_weight > parent_threshold


def spec_is_head_late(store: Store, head_root: bytes) -> bool:
    """fork-choice.md:675-677"""
    return not store.block_timeliness.get(head_root, [False, False])[ATTESTATION_TIMELINESS_INDEX]


def spec_update_proposer_boost_root_check(
    store: Store, candidate_root: bytes
) -> bool:
    """fork-choice.md:601-619 — returns whether boost would be applied (spec semantics)."""
    is_first_block = store.proposer_boost_root == ZERO_ROOT
    is_timely = store.block_timeliness.get(candidate_root, [False, False])[ATTESTATION_TIMELINESS_INDEX]
    if not (is_timely and is_first_block):
        return False
    block = store.blocks[candidate_root]
    canonical_proposer = store.canonical_proposer_per_slot.get(block.slot)
    # Only update if the proposer is the same as on the canonical chain
    return block.proposer_index == canonical_proposer


# ============================================================================
# Client variants — only the divergent parts; everything else inherits spec.
# ============================================================================


# --- Lodestar `shouldExtendPayload` (item #77) ---
def lodestar_should_extend_payload(store: Store, r: bytes) -> bool:
    """protoArray.ts:715-749 — drops `is_payload_data_available` conjunct."""
    if not spec_is_payload_verified(store, r):
        return False
    if spec_is_payload_timely(store, r):  # ← spec also AND's is_payload_data_available; lodestar doesn't
        return True
    proposer_root = store.proposer_boost_root
    if proposer_root == ZERO_ROOT or proposer_root not in store.blocks:
        return True
    if store.blocks[proposer_root].parent_root != r:
        return True
    if spec_is_parent_node_full(store, store.blocks[proposer_root]):
        return True
    return False


# --- Same-slot vote routing (item #80) ---
def lodestar_is_supporting_vote(store: Store, node: ForkChoiceNode, message: LatestMessage) -> bool:
    """Lodestar routes same-slot votes to FULL/EMPTY variants directly per payload_present.

    Implementation note: lodestar pre-routes via `addLatestMessage` (forkChoice.ts:1735) —
    no slot check; the vote index points to the (root, payload_status) variant matching
    the message's payload_present bit, regardless of message.slot vs block.slot.
    """
    block = store.blocks[node.root]
    if node.root == message.root:
        if node.payload_status == PAYLOAD_STATUS_PENDING:
            return True
        # NO same-slot check — vote always routes by payload_present
        if message.payload_present:
            return node.payload_status == PAYLOAD_STATUS_FULL
        else:
            return node.payload_status == PAYLOAD_STATUS_EMPTY
    else:
        ancestor = spec_get_ancestor(store, message.root, block.slot)
        return node.root == ancestor.root and (
            node.payload_status == PAYLOAD_STATUS_PENDING
            or node.payload_status == ancestor.payload_status
        )


def grandine_is_supporting_vote(store: Store, node: ForkChoiceNode, message: LatestMessage) -> bool:
    """Grandine accumulates same-slot votes into FULL/EMPTY buckets unconditionally
    (store.rs:4090-4099). Same behavior as lodestar for the same-slot edge."""
    return lodestar_is_supporting_vote(store, node, message)


def prysm_is_supporting_vote(store: Store, node: ForkChoiceNode, message: LatestMessage) -> bool:
    """Prysm asymmetric: same-slot EMPTY votes route to PENDING (correctly);
    same-slot FULL votes route to FULL bucket (gloas.go:451-454)."""
    block = store.blocks[node.root]
    if node.root == message.root:
        if node.payload_status == PAYLOAD_STATUS_PENDING:
            return True
        # Asymmetric handling
        if message.slot == block.slot and not message.payload_present:
            return False  # Same-slot EMPTY → PENDING-only (correct)
        # FULL same-slot: prysm routes to FULL anyway
        if message.payload_present:
            return node.payload_status == PAYLOAD_STATUS_FULL
        else:
            return node.payload_status == PAYLOAD_STATUS_EMPTY
    else:
        ancestor = spec_get_ancestor(store, message.root, block.slot)
        return node.root == ancestor.root and (
            node.payload_status == PAYLOAD_STATUS_PENDING
            or node.payload_status == ancestor.payload_status
        )


# Wrap to compute attestation_score with each client's variant
def attestation_score_with(store: Store, node: ForkChoiceNode, is_supporting_vote_fn) -> int:
    total = 0
    for validator_index, message in store.latest_messages.items():
        if validator_index in store.equivocating_indices:
            continue
        if is_supporting_vote_fn(store, node, message):
            total += EFFECTIVE_BALANCE
    return total


# --- get_weight previous-slot zeroing (item #81) ---
def prysm_get_weight(store: Store, node: ForkChoiceNode) -> int:
    """Prysm's choosePayloadContent compares raw fn.weight/en.weight at previous-slot,
    no spec-style zeroing. We model this as: get_weight returns raw attestation_score
    regardless of (previous-slot, FULL/EMPTY) condition."""
    return spec_get_attestation_score(store, node)


def grandine_get_weight(store: Store, node: ForkChoiceNode) -> int:
    """Grandine's segment-based score() lacks previous-slot zeroing (store.rs:1269+)."""
    return spec_get_attestation_score(store, node)


# --- is_head_weak equivocating-committee term (item #83) ---
def prysm_is_head_weak(store: Store, head_root: bytes) -> bool:
    """Prysm uses raw weight, no equivocating-committee term."""
    reorg_threshold = committee_weight(store) * REORG_HEAD_WEIGHT_THRESHOLD_PCT // 100
    head_node = ForkChoiceNode(root=head_root, payload_status=PAYLOAD_STATUS_PENDING)
    head_weight = spec_get_attestation_score(store, head_node)
    return head_weight < reorg_threshold


def lodestar_is_head_weak(store: Store, head_root: bytes) -> bool:
    """Lodestar uses raw headNode.weight (forkChoice.ts:433); no equivocating term."""
    return prysm_is_head_weak(store, head_root)


# --- is_parent_strong payload-aware variant (item #84-A) ---
def prysm_is_parent_strong(store: Store, r: bytes) -> bool:
    """Prysm uses combined consensus-node weight (sum of variants), not specific variant."""
    parent_threshold = committee_weight(store) * REORG_PARENT_WEIGHT_THRESHOLD_PCT // 100
    block = store.blocks[r]
    # Sum all 3 variants of parent
    parent_root = block.parent_root
    combined_weight = (
        spec_get_attestation_score(store, ForkChoiceNode(parent_root, PAYLOAD_STATUS_PENDING))
        + spec_get_attestation_score(store, ForkChoiceNode(parent_root, PAYLOAD_STATUS_FULL))
        + spec_get_attestation_score(store, ForkChoiceNode(parent_root, PAYLOAD_STATUS_EMPTY))
    )
    return combined_weight > parent_threshold


def grandine_is_parent_strong(store: Store, r: bytes) -> Optional[bool]:
    """Grandine has NO is_parent_strong implementation; threshold constant defined but unused."""
    return None  # Not implemented


# --- update_proposer_boost_root canonical-proposer check (item #84-B) ---
def prysm_update_proposer_boost_root_check(store: Store, candidate_root: bytes) -> bool:
    """Prysm (store.go:182-185): no proposer-index check."""
    is_first_block = store.proposer_boost_root == ZERO_ROOT
    is_timely = store.block_timeliness.get(candidate_root, [False, False])[ATTESTATION_TIMELINESS_INDEX]
    return is_timely and is_first_block


def lodestar_update_proposer_boost_root_check(store: Store, candidate_root: bytes) -> bool:
    """Lodestar (forkChoice.ts:668-675): no proposer-index check."""
    return prysm_update_proposer_boost_root_check(store, candidate_root)


# --- is_head_late (item #84-C) ---
def grandine_is_head_late(store: Store, head_root: bytes) -> Optional[bool]:
    """Grandine has NO is_head_late equivalent — no late-head detection at all."""
    return None  # Not implemented; treated as "never late" effectively


# --- should_apply_proposer_boost equivocation suppression (item #82) ---
def prysm_should_apply_proposer_boost(store: Store) -> bool:
    """Prysm (gloas.go:487-508): gates on `parent.weight*100 >= committeeWeight * 20%`
    (equivalent to "parent NOT weak"). No equivocation check at all."""
    if store.proposer_boost_root == ZERO_ROOT:
        return False
    block = store.blocks[store.proposer_boost_root]
    parent = store.blocks.get(block.parent_root)
    if parent is None:
        return True
    if parent.slot + 1 != block.slot:
        return True
    # parent.node.weight is the consensus-Node weight (sum of all variants)
    combined_weight = (
        spec_get_attestation_score(store, ForkChoiceNode(parent.root, PAYLOAD_STATUS_PENDING))
        + spec_get_attestation_score(store, ForkChoiceNode(parent.root, PAYLOAD_STATUS_FULL))
        + spec_get_attestation_score(store, ForkChoiceNode(parent.root, PAYLOAD_STATUS_EMPTY))
    )
    threshold = committee_weight(store) * REORG_HEAD_WEIGHT_THRESHOLD_PCT // 100
    return combined_weight >= threshold


def lodestar_should_apply_proposer_boost(store: Store) -> bool:
    """Lodestar (forkChoice.ts:668-675): no should_apply_proposer_boost function;
    boost is always applied to timely-first-seen block. Approximated as True."""
    return store.proposer_boost_root != ZERO_ROOT


def grandine_should_apply_proposer_boost(store: Store) -> bool:
    """Grandine: implements suppression but counts ALL siblings, not PTC-timely-only
    (store.rs:618-636)."""
    if store.proposer_boost_root == ZERO_ROOT:
        return False
    block = store.blocks[store.proposer_boost_root]
    parent = store.blocks.get(block.parent_root)
    if parent is None:
        return True
    if parent.slot + 1 < block.slot:
        return True
    if not spec_is_head_weak(store, block.parent_root):  # grandine's is_head_weak has equivocating term
        return True
    # Count ALL equivocations (no PTC-timeliness filter)
    has_equivocation = any(
        b.slot == block.slot - 1
        and b.proposer_index == parent.proposer_index
        and r != block.parent_root
        for r, b in store.blocks.items()
    )
    return not has_equivocation


def teku_should_apply_proposer_boost(store: Store) -> bool:
    """Teku (ForkChoiceUtilGloas.java:176-207): the equivocation suppression branch is
    explicitly TODO. After the parent-slot check, returns True unconditionally."""
    if store.proposer_boost_root == ZERO_ROOT:
        return False
    block = store.blocks[store.proposer_boost_root]
    parent = store.blocks.get(block.parent_root)
    if parent is None:
        return True
    if parent.slot + 1 < block.slot:
        return True
    # TODO branch — returns True unconditionally
    return True


# ============================================================================
# Scenarios
# ============================================================================


def section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def report(label: str, spec_val, **client_vals) -> None:
    print(f"  {label}")
    print(f"    spec       = {spec_val}")
    for client, val in client_vals.items():
        if val is None:
            verdict = "✗ NOT IMPLEMENTED"
        elif val == spec_val:
            verdict = "✓"
        else:
            verdict = "✗ DIVERGE"
        print(f"    {client:10s} = {val}  {verdict}")


def scenario_77_should_extend_payload() -> None:
    """Item #77: lodestar drops is_payload_data_available from should_extend_payload.

    Setup: PTC majority votes payload_present=True (timely), but blob_data_available
    below threshold. Proposer-boost adversarial (set to child of candidate whose
    parent is EMPTY).

    Spec: returns False (no AND in first branch; proposer-boost branches all False).
    Lodestar: returns True (timely is enough).
    """
    section("Scenario #77 — should_extend_payload: lodestar drops is_payload_data_available")

    store = Store()
    candidate = root("CANDIDATE")
    boost_child = root("BOOST_CHILD")
    parent = root("PARENT")
    store.blocks[candidate] = Block(root=candidate, parent_root=parent, slot=10)
    store.blocks[boost_child] = Block(root=boost_child, parent_root=candidate, slot=11)
    store.blocks[parent] = Block(root=parent, parent_root=ZERO_ROOT, slot=9)
    store.payloads.add(candidate)
    # Parent of boost_child (= candidate) is EMPTY per chain
    store.parent_payload_status[boost_child] = PAYLOAD_STATUS_EMPTY
    # PTC: timely YES (300 > 256), available NO (10 < 256)
    store.payload_timeliness_vote[candidate] = [i < 300 for i in range(PTC_SIZE)]
    store.payload_data_availability_vote[candidate] = [i < 10 for i in range(PTC_SIZE)]
    store.proposer_boost_root = boost_child

    spec_v = spec_should_extend_payload(store, candidate)
    lodestar_v = lodestar_should_extend_payload(store, candidate)
    report("PTC: timely=300 (>256), available=10 (<256); proposer-boost adversarial",
           spec_v, lodestar=lodestar_v)


def scenario_80_same_slot_vote() -> None:
    """Item #80: same-slot vote routing.

    Setup: block B at slot S. A validator attests at slot S+1 for B with
    payload_present=True (a NORMAL post-slot attestation). And another validator
    has a stale same-slot attestation (slot S, index=0, payload_present=False).

    The same-slot validator's vote SHOULD support PENDING(B) only (spec).
    Lodestar/grandine route it to EMPTY(B).
    Prysm routes EMPTY same-slot to PENDING (correct), but FULL same-slot to FULL.
    """
    section("Scenario #80 — same-slot vote routing: lodestar/grandine/prysm divergence")

    # Setup
    store = Store()
    b_root = root("B")
    store.blocks[b_root] = Block(root=b_root, parent_root=ZERO_ROOT, slot=10)
    store.payloads.add(b_root)

    # Case A: same-slot vote with payload_present=False (spec-permitted by validate_on_attestation)
    print("  Case A: same-slot vote with payload_present=False (data.index=0)")
    store.latest_messages = {0: LatestMessage(slot=10, root=b_root, payload_present=False)}
    spec_empty = spec_get_attestation_score(store, ForkChoiceNode(b_root, PAYLOAD_STATUS_EMPTY))
    spec_pending = spec_get_attestation_score(store, ForkChoiceNode(b_root, PAYLOAD_STATUS_PENDING))
    lodestar_empty = attestation_score_with(store, ForkChoiceNode(b_root, PAYLOAD_STATUS_EMPTY),
                                            lodestar_is_supporting_vote)
    prysm_empty = attestation_score_with(store, ForkChoiceNode(b_root, PAYLOAD_STATUS_EMPTY),
                                         prysm_is_supporting_vote)
    print(f"    spec.score(EMPTY)     = {spec_empty:>15}  (correct: same-slot routes to PENDING only)")
    print(f"    spec.score(PENDING)   = {spec_pending:>15}")
    print(f"    lodestar.score(EMPTY) = {lodestar_empty:>15}  {'✗ DIVERGE' if lodestar_empty != spec_empty else '✓'}")
    print(f"    grandine.score(EMPTY) = {lodestar_empty:>15}  {'✗ DIVERGE' if lodestar_empty != spec_empty else '✓'}  (same as lodestar)")
    print(f"    prysm.score(EMPTY)    = {prysm_empty:>15}  {'✗ DIVERGE' if prysm_empty != spec_empty else '✓'}")

    # Case B: same-slot vote with payload_present=True
    # (validate_on_attestation would REJECT this per spec :650-651, but if it slipped through:)
    print()
    print("  Case B: same-slot vote with payload_present=True (data.index=1)")
    print("  (NOTE: validate_on_attestation rejects this per spec; tests routing if it leaks)")
    store.latest_messages = {0: LatestMessage(slot=10, root=b_root, payload_present=True)}
    spec_full = spec_get_attestation_score(store, ForkChoiceNode(b_root, PAYLOAD_STATUS_FULL))
    lodestar_full = attestation_score_with(store, ForkChoiceNode(b_root, PAYLOAD_STATUS_FULL),
                                           lodestar_is_supporting_vote)
    prysm_full = attestation_score_with(store, ForkChoiceNode(b_root, PAYLOAD_STATUS_FULL),
                                        prysm_is_supporting_vote)
    print(f"    spec.score(FULL)      = {spec_full:>15}  (correct: same-slot returns False for FULL)")
    print(f"    lodestar.score(FULL)  = {lodestar_full:>15}  {'✗ DIVERGE' if lodestar_full != spec_full else '✓'}")
    print(f"    prysm.score(FULL)     = {prysm_full:>15}  {'✗ DIVERGE' if prysm_full != spec_full else '✓'}")


def scenario_81_previous_slot_zeroing() -> None:
    """Item #81: get_weight returns 0 for FULL/EMPTY at previous-slot.

    Setup: block B at slot S, current_slot = S+1 (so B is previous-slot).
    Votes pile up on FULL(B). Spec zeros FULL.weight at previous-slot.
    Prysm/grandine use raw weight.
    """
    section("Scenario #81 — get_weight previous-slot zeroing: prysm/grandine use raw weight")

    store = Store()
    b_root = root("B")
    store.blocks[b_root] = Block(root=b_root, parent_root=ZERO_ROOT, slot=10)
    store.payloads.add(b_root)
    store.current_slot = 11  # previous-slot: B.slot + 1 == 11
    # 100 validators voted FULL (payload_present=True) at slot 11 (post-slot, allowed)
    store.latest_messages = {
        i: LatestMessage(slot=11, root=b_root, payload_present=True) for i in range(100)
    }
    store.active_validator_count = 1000

    spec_full_weight = spec_get_weight(store, ForkChoiceNode(b_root, PAYLOAD_STATUS_FULL))
    spec_empty_weight = spec_get_weight(store, ForkChoiceNode(b_root, PAYLOAD_STATUS_EMPTY))
    prysm_full_weight = prysm_get_weight(store, ForkChoiceNode(b_root, PAYLOAD_STATUS_FULL))

    print(f"  Setup: B at slot 10, current_slot=11 (previous-slot relative to current)")
    print(f"         100 validators voted FULL via post-slot attestations")
    print(f"    spec.get_weight(FULL(B))     = {spec_full_weight:>20}  (zeroed at previous-slot)")
    print(f"    spec.get_weight(EMPTY(B))    = {spec_empty_weight:>20}  (zeroed at previous-slot)")
    print(f"    prysm.get_weight(FULL(B))    = {prysm_full_weight:>20}  {'✗ DIVERGE' if prysm_full_weight != spec_full_weight else '✓'}")
    print(f"    grandine.get_weight(FULL(B)) = {prysm_full_weight:>20}  {'✗ DIVERGE' if prysm_full_weight != spec_full_weight else '✓'}  (same as prysm)")


def scenario_82_proposer_boost_equivocation_suppression() -> None:
    """Item #82: should_apply_proposer_boost with PTC-timely equivocation.

    Setup: proposer X equivocates at slot S, publishing both B1 and B2.
    Both are PTC-timely. Block at slot S+1 builds on B1 with parent-weak.
    Spec/lighthouse: suppress boost (early equivocation exists).
    Teku: applies boost (TODO).
    Prysm: applies boost (no equivocation check).
    Lodestar: applies boost (no should_apply_proposer_boost).
    Grandine: suppresses boost (counts ALL equivocations).
    """
    section("Scenario #82 — proposer-boost equivocation suppression: 4-client divergence")

    store = Store()
    b1 = root("B1")
    b2 = root("B2")
    parent_block = root("P")
    s1_child = root("S1")  # block at slot S+1 building on B1
    store.blocks[parent_block] = Block(root=parent_block, parent_root=ZERO_ROOT, slot=9, proposer_index=99)
    store.blocks[b1] = Block(root=b1, parent_root=parent_block, slot=10, proposer_index=42)
    store.blocks[b2] = Block(root=b2, parent_root=parent_block, slot=10, proposer_index=42)
    store.blocks[s1_child] = Block(root=s1_child, parent_root=b1, slot=11, proposer_index=99)
    # Both B1 and B2 are PTC-timely
    store.block_timeliness[b1] = [True, True]
    store.block_timeliness[b2] = [True, True]
    store.block_timeliness[s1_child] = [True, True]
    store.current_slot = 11
    store.proposer_boost_root = s1_child
    # B1 must be WEAK so spec's branch-3 equivocation suppression fires.
    # No votes for B1 → parent.weight=0 → is_head_weak=True. PTC-timely
    # equivocation (B2) exists → spec suppresses boost.
    store.active_validator_count = 1000
    store.latest_messages = {}  # No votes for B1 → parent weak
    store.committees[10] = []  # no equivocating-committee weight

    spec_v = spec_should_apply_proposer_boost(store)
    prysm_v = prysm_should_apply_proposer_boost(store)
    lodestar_v = lodestar_should_apply_proposer_boost(store)
    grandine_v = grandine_should_apply_proposer_boost(store)
    teku_v = teku_should_apply_proposer_boost(store)

    print(f"  Setup: proposer 42 published B1 and B2 at slot 10 (both PTC-timely)")
    print(f"         Block S1 (proposer 99) at slot 11 builds on B1; parent (B1) is weak")
    print(f"    spec.should_apply_proposer_boost     = {spec_v}  (suppress: early equivocation exists)")
    print(f"    prysm.should_apply_proposer_boost    = {prysm_v}  {'✓' if prysm_v == spec_v else '✗ DIVERGE'}  (matches: prysm rejects because parent weak — wrong reason)")
    print(f"    lodestar.should_apply_proposer_boost = {lodestar_v}  {'✗ DIVERGE' if lodestar_v != spec_v else '✓'}")
    print(f"    teku.should_apply_proposer_boost     = {teku_v}  {'✗ DIVERGE' if teku_v != spec_v else '✓'}")
    print(f"    grandine.should_apply_proposer_boost = {grandine_v}  {'✓' if grandine_v == spec_v else '✗ DIVERGE'}  (matches: counts ALL equivocations, not just PTC-timely)")


def scenario_83_is_head_weak_equivocating_term() -> None:
    """Item #83: is_head_weak adds equivocating-committee weight for monotonicity.

    Setup: head block has some attestation weight just below threshold.
    Head-slot committee includes equivocating validators whose effective
    balance would push above threshold.

    Spec/lighthouse/teku/grandine: head_weight + equivocating term >= threshold → NOT weak.
    Prysm/lodestar: head_weight < threshold → weak.
    """
    section("Scenario #83 — is_head_weak equivocating-committee monotonicity term")

    store = Store()
    h_root = root("H")
    store.blocks[h_root] = Block(root=h_root, parent_root=ZERO_ROOT, slot=10)
    store.active_validator_count = 1000
    # committee_weight = 1000 * 32e9 / 32 = 1e12
    # threshold = 1e12 * 20/100 = 2e11
    # 5 non-equivocating votes for head: 5 * 32e9 = 1.6e11 < threshold
    # +2 equivocating committee members: +6.4e10 → total 2.24e11 > threshold

    for i in range(5):
        store.latest_messages[i] = LatestMessage(slot=11, root=h_root, payload_present=False)
    # 2 equivocating validators in slot-10 committee
    store.committees[10] = [100, 101]
    store.equivocating_indices = {100, 101}

    spec_v = spec_is_head_weak(store, h_root)
    prysm_v = prysm_is_head_weak(store, h_root)
    lodestar_v = lodestar_is_head_weak(store, h_root)

    head_weight_raw = spec_get_attestation_score(store, ForkChoiceNode(h_root, PAYLOAD_STATUS_PENDING))
    equiv_term = 2 * EFFECTIVE_BALANCE
    threshold = committee_weight(store) * REORG_HEAD_WEIGHT_THRESHOLD_PCT // 100

    print(f"  Setup: head H, 5 non-equivocating votes, 2 equivocating committee members")
    print(f"    raw head_weight       = {head_weight_raw:>15}")
    print(f"    equivocating term     = {equiv_term:>15}")
    print(f"    head_weight + term    = {head_weight_raw + equiv_term:>15}")
    print(f"    reorg threshold       = {threshold:>15}")
    print(f"    spec.is_head_weak     = {spec_v}  (NOT weak: head+equiv > threshold)")
    print(f"    prysm.is_head_weak    = {prysm_v}  {'✗ DIVERGE' if prysm_v != spec_v else '✓'}")
    print(f"    lodestar.is_head_weak = {lodestar_v}  {'✗ DIVERGE' if lodestar_v != spec_v else '✓'}")


def scenario_84a_is_parent_strong() -> None:
    """Item #84-A: is_parent_strong uses payload-status-aware variant weight.

    Setup: parent P has FULL.weight=10 (variant matching head's chain) and
    EMPTY.weight=200 (other variant). PENDING.weight=0.
    Combined consensus-node weight = 10 + 200 + 0 = 210.
    Threshold = 100 (1% of 1000 validator committee).

    Spec: uses parent.FULL.weight=10 < 100 → NOT strong.
    Prysm: uses combined 210 > 100 → strong (DIVERGENT).
    Grandine: doesn't implement is_parent_strong (returns None).
    """
    section("Scenario #84-A — is_parent_strong payload-aware: prysm uses combined weight")

    store = Store()
    p_root = root("P")
    h_root = root("H")
    store.blocks[p_root] = Block(root=p_root, parent_root=ZERO_ROOT, slot=9)
    store.blocks[h_root] = Block(root=h_root, parent_root=p_root, slot=10)
    # H declares parent FULL
    store.parent_payload_status[h_root] = PAYLOAD_STATUS_FULL

    # Setup votes
    # 5 validators voted at slot 9 with payload_present=False → spec credits PENDING(P) + EMPTY(P)
    #   but EMPTY's slot==block.slot per spec returns False — wait, slot=9 == P.slot=9
    # Use post-slot votes to credit FULL/EMPTY without same-slot trickiness
    # 1 validator at slot 10 for P with payload_present=True (FULL)
    # 25 validators at slot 10 for P with payload_present=False (EMPTY)
    store.latest_messages[0] = LatestMessage(slot=10, root=p_root, payload_present=True)
    for i in range(1, 26):
        store.latest_messages[i] = LatestMessage(slot=10, root=p_root, payload_present=False)
    store.active_validator_count = 100  # smaller for visible threshold

    # threshold = 100 * 32e9 / 32 * 160 / 100 = 100 * 1e9 * 1.6 = 1.6e11
    # FULL(P).weight = 1 * 32e9 = 3.2e10 < 1.6e11 → NOT strong
    # Combined: PENDING(P) gets all 26 = 8.32e11; FULL gets 1 = 3.2e10; EMPTY gets 25 = 8.0e11
    #   sum = ~1.66e12 ≫ 1.6e11 → strong
    spec_v = spec_is_parent_strong(store, h_root)
    prysm_v = prysm_is_parent_strong(store, h_root)
    grandine_v = grandine_is_parent_strong(store, h_root)

    threshold = committee_weight(store) * REORG_PARENT_WEIGHT_THRESHOLD_PCT // 100
    full_w = spec_get_attestation_score(store, ForkChoiceNode(p_root, PAYLOAD_STATUS_FULL))
    print(f"  Setup: H declares parent FULL; 1 FULL vote, 25 EMPTY votes for parent")
    print(f"    parent.FULL.weight   = {full_w:>15}")
    print(f"    parent_threshold     = {threshold:>15}")
    print(f"    spec.is_parent_strong     = {spec_v}  (NOT strong: parent.FULL.weight ≤ threshold)")
    print(f"    prysm.is_parent_strong    = {prysm_v}  {'✗ DIVERGE' if prysm_v != spec_v else '✓'}  (uses combined consensus-Node weight)")
    print(f"    grandine.is_parent_strong = {grandine_v}  ✗ NOT IMPLEMENTED")


def scenario_84b_canonical_proposer_check() -> None:
    """Item #84-B: update_proposer_boost_root checks proposer matches canonical chain.

    Setup: at slot 10, canonical proposer is validator 99. A block at slot 10
    arrives timely with proposer_index = 42 (not canonical).

    Spec/lighthouse/teku/grandine: do NOT apply boost (proposer mismatch).
    Prysm/lodestar: apply boost (no canonical-proposer check).
    """
    section("Scenario #84-B — canonical-proposer check in update_proposer_boost_root")

    store = Store()
    b_root = root("B")
    store.blocks[b_root] = Block(root=b_root, parent_root=ZERO_ROOT, slot=10, proposer_index=42)
    store.block_timeliness[b_root] = [True, True]
    store.canonical_proposer_per_slot[10] = 99

    spec_v = spec_update_proposer_boost_root_check(store, b_root)
    prysm_v = prysm_update_proposer_boost_root_check(store, b_root)
    lodestar_v = lodestar_update_proposer_boost_root_check(store, b_root)

    print(f"  Setup: block B at slot 10 with proposer 42; canonical proposer is 99")
    print(f"    spec.would_apply_boost     = {spec_v}  (do NOT apply: proposer mismatch)")
    print(f"    prysm.would_apply_boost    = {prysm_v}  {'✗ DIVERGE' if prysm_v != spec_v else '✓'}")
    print(f"    lodestar.would_apply_boost = {lodestar_v}  {'✗ DIVERGE' if lodestar_v != spec_v else '✓'}")


def scenario_84c_is_head_late() -> None:
    """Item #84-C: is_head_late detects late-arriving head for reorg eligibility.

    Setup: head H arrived late (attestation_timeliness bit = False).

    Spec/lighthouse/teku/lodestar/prysm: return True (late) → reorg eligible.
    Grandine: no is_head_late → can't evaluate late-head reorgs.
    """
    section("Scenario #84-C — is_head_late: grandine missing")

    store = Store()
    h_root = root("H")
    store.blocks[h_root] = Block(root=h_root, parent_root=ZERO_ROOT, slot=10)
    store.block_timeliness[h_root] = [False, False]  # attestation-timeliness=False → late

    spec_v = spec_is_head_late(store, h_root)
    grandine_v = grandine_is_head_late(store, h_root)

    print(f"  Setup: head H at slot 10, attestation_timeliness=False (arrived late)")
    print(f"    spec.is_head_late     = {spec_v}  (late → reorg eligible)")
    print(f"    grandine.is_head_late = {grandine_v}  ✗ NOT IMPLEMENTED  (no late-head detection)")


def main() -> None:
    print("=" * 72)
    print("Gloas fork-choice simulator harness")
    print("Items: #77, #80, #81, #82, #83, #84-A, #84-B, #84-C")
    print("Date:  2026-05-14")
    print("=" * 72)

    scenario_77_should_extend_payload()
    scenario_80_same_slot_vote()
    scenario_81_previous_slot_zeroing()
    scenario_82_proposer_boost_equivocation_suppression()
    scenario_83_is_head_weak_equivocating_term()
    scenario_84a_is_parent_strong()
    scenario_84b_canonical_proposer_check()
    scenario_84c_is_head_late()

    print()
    print("=" * 72)
    print("All scenarios complete.")
    print("=" * 72)


if __name__ == "__main__":
    main()
