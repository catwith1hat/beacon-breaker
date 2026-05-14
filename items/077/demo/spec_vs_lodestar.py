#!/usr/bin/env python3
"""Demo: empirical reproduction of the lodestar `should_extend_payload`
divergence.

This script implements `should_extend_payload` in two ways inline (no spec
or lodestar imports — fully self-contained) and runs three scenarios:

  T1 (timely-only + adversarial proposer boost):
     PTC majority on payload_present=True, NOT majority on blob_data_available.
     Proposer-boost set, B.parent_root == root, parent(B) is EMPTY.
     Spec returns False; lodestar returns True → divergence.

  T2 (both-true):
     PTC majority on both bits. Both implementations return True.

  T3 (timely-only, no proposer boost):
     PTC majority on payload_present only, proposer_boost_root = zero.
     Both implementations return True (different branches, same outcome).

References:
  - spec: vendor/consensus-specs/specs/gloas/fork-choice.md:398-409
  - lodestar: vendor/lodestar/packages/fork-choice/src/protoArray/protoArray.ts:715-749
  - lodestar notifyPtcMessages signature: protoArray.ts:638
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

PTC_SIZE = 512
PAYLOAD_TIMELY_THRESHOLD = PTC_SIZE // 2  # 256
DATA_AVAILABILITY_TIMELY_THRESHOLD = PTC_SIZE // 2  # 256

ZERO_ROOT = b"\x00" * 32

PAYLOAD_STATUS_FULL = 2
PAYLOAD_STATUS_EMPTY = 0
PAYLOAD_STATUS_PENDING = 1


@dataclass
class Block:
    root: bytes
    parent_root: bytes
    # parent_payload_status from is_parent_node_full's perspective.
    # PAYLOAD_STATUS_FULL means the parent payload was honored; EMPTY means
    # the bid was inserted but the payload was not produced.
    parent_payload_status: int


@dataclass
class SpecStore:
    """Spec store fragment. Carries TWO vote arrays per spec/fork-choice.md:163-191."""
    blocks: Dict[bytes, Block] = field(default_factory=dict)
    payloads: set = field(default_factory=set)
    payload_timeliness_vote: Dict[bytes, list] = field(default_factory=dict)
    payload_data_availability_vote: Dict[bytes, list] = field(default_factory=dict)
    proposer_boost_root: bytes = ZERO_ROOT

    def add_block(self, block: Block, payload_verified: bool = True):
        self.blocks[block.root] = block
        if payload_verified:
            self.payloads.add(block.root)
        self.payload_timeliness_vote[block.root] = [None] * PTC_SIZE
        self.payload_data_availability_vote[block.root] = [None] * PTC_SIZE

    def cast_ptc_votes(self, root: bytes, payload_present_count: int,
                       blob_data_available_count: int):
        """Cast PTC votes. The first `payload_present_count` PTC indices vote
        True for payload_present; the first `blob_data_available_count` vote
        True for blob_data_available. The rest vote False."""
        for i in range(PTC_SIZE):
            self.payload_timeliness_vote[root][i] = (i < payload_present_count)
            self.payload_data_availability_vote[root][i] = (i < blob_data_available_count)

    def is_payload_verified(self, root: bytes) -> bool:
        return root in self.payloads

    def is_payload_timely(self, root: bytes) -> bool:
        if not self.is_payload_verified(root):
            return False
        votes = self.payload_timeliness_vote[root]
        return sum(1 for v in votes if v is True) > PAYLOAD_TIMELY_THRESHOLD

    def is_payload_data_available(self, root: bytes) -> bool:
        if not self.is_payload_verified(root):
            return False
        votes = self.payload_data_availability_vote[root]
        return sum(1 for v in votes if v is True) > DATA_AVAILABILITY_TIMELY_THRESHOLD

    def is_parent_node_full(self, block: Block) -> bool:
        return block.parent_payload_status == PAYLOAD_STATUS_FULL

    def should_extend_payload(self, root: bytes) -> bool:
        """Per spec fork-choice.md:398-409."""
        if not self.is_payload_verified(root):
            return False
        proposer_root = self.proposer_boost_root
        if (self.is_payload_timely(root) and self.is_payload_data_available(root)):
            return True
        if proposer_root == ZERO_ROOT:
            return True
        if self.blocks[proposer_root].parent_root != root:
            return True
        if self.is_parent_node_full(self.blocks[proposer_root]):
            return True
        return False


@dataclass
class LodestarStore:
    """Lodestar store fragment. Carries ONE vote array (the payloadPresent
    bits), per protoArray.ts:72.

    notifyPtcMessages accepts only `payloadPresent: boolean` (protoArray.ts:638).
    The wire-decoded `blob_data_available` bit is silently discarded by the
    three call sites in `packages/beacon-node/src`.
    """
    blocks: Dict[bytes, Block] = field(default_factory=dict)
    payloads: set = field(default_factory=set)
    ptc_votes: Dict[bytes, list] = field(default_factory=dict)  # bool list, no None
    proposer_boost_root: bytes = ZERO_ROOT

    def add_block(self, block: Block, payload_verified: bool = True):
        self.blocks[block.root] = block
        if payload_verified:
            self.payloads.add(block.root)
        self.ptc_votes[block.root] = [False] * PTC_SIZE  # BitArray.fromBitLen

    def cast_ptc_votes(self, root: bytes, payload_present_count: int,
                       blob_data_available_count: int):
        """Cast PTC votes. Lodestar receives payloadPresent only — the
        blob_data_available count is silently discarded at the ingestion
        boundary."""
        del blob_data_available_count  # not threaded into fork-choice
        for i in range(PTC_SIZE):
            self.ptc_votes[root][i] = (i < payload_present_count)

    def has_payload(self, root: bytes) -> bool:
        return root in self.payloads

    def is_payload_timely(self, root: bytes) -> bool:
        """protoArray.ts:675-684 — popcount the single vote map."""
        if root not in self.ptc_votes:
            return False
        if not self.has_payload(root):
            return False
        yes_votes = sum(1 for v in self.ptc_votes[root] if v)
        return yes_votes > PAYLOAD_TIMELY_THRESHOLD

    def is_parent_node_full(self, block: Block) -> bool:
        return block.parent_payload_status == PAYLOAD_STATUS_FULL

    def should_extend_payload(self, root: bytes) -> bool:
        """protoArray.ts:715-749 — condition 1 is `isPayloadTimely` alone."""
        if not self.has_payload(root):
            return False
        # Condition 1: Payload is timely (MISSING the data-available AND)
        if self.is_payload_timely(root):
            return True
        # Condition 2: No proposer boost root
        if self.proposer_boost_root == ZERO_ROOT:
            return True
        proposer_boost_block = self.blocks.get(self.proposer_boost_root)
        if proposer_boost_block is None:
            return True
        # Condition 3: Proposer boost root's parent is not this block
        if proposer_boost_block.parent_root != root:
            return True
        # Condition 4: Proposer boost root extends FULL parent
        if self.is_parent_node_full(proposer_boost_block):
            return True
        return False


def _root(label: str) -> bytes:
    return label.encode().ljust(32, b"\x00")


def run_scenario(name: str, payload_present_count: int,
                 blob_data_available_count: int, proposer_boost_set: bool,
                 parent_status: int) -> None:
    root = _root("CANDIDATE")
    boost_root = _root("BOOST_BLOCK")

    candidate = Block(root=root, parent_root=_root("PARENT"),
                      parent_payload_status=PAYLOAD_STATUS_FULL)
    boost = Block(root=boost_root, parent_root=root,
                  parent_payload_status=parent_status)

    spec = SpecStore()
    spec.add_block(candidate)
    spec.add_block(boost)
    spec.cast_ptc_votes(root, payload_present_count, blob_data_available_count)
    spec.proposer_boost_root = boost_root if proposer_boost_set else ZERO_ROOT

    lodestar = LodestarStore()
    lodestar.add_block(candidate)
    lodestar.add_block(boost)
    lodestar.cast_ptc_votes(root, payload_present_count, blob_data_available_count)
    lodestar.proposer_boost_root = boost_root if proposer_boost_set else ZERO_ROOT

    s = spec.should_extend_payload(root)
    l = lodestar.should_extend_payload(root)
    verdict = "MATCH ✓" if s == l else "DIVERGE ✗"
    print(f"{name}:")
    print(f"  payload_present votes:        {payload_present_count} (threshold > {PAYLOAD_TIMELY_THRESHOLD})")
    print(f"  blob_data_available votes:    {blob_data_available_count} (threshold > {DATA_AVAILABILITY_TIMELY_THRESHOLD})")
    print(f"  proposer_boost set:           {proposer_boost_set}")
    print(f"  parent(boost).payload_status: {('FULL' if parent_status == PAYLOAD_STATUS_FULL else 'EMPTY')}")
    print(f"  spec.should_extend_payload     = {s}")
    print(f"  lodestar.should_extend_payload = {l}")
    print(f"  → {verdict}")
    print()


def main() -> None:
    # T1: timely-yes (300 > 256), data-no (10 < 256), adversarial boost.
    #     Spec: timely AND data-available → False; boost branches all False → False.
    #     Lodestar: timely → True.
    run_scenario("T1 (timely-only + adversarial proposer boost)",
                 payload_present_count=300,
                 blob_data_available_count=10,
                 proposer_boost_set=True,
                 parent_status=PAYLOAD_STATUS_EMPTY)

    # T2: both true. Both implementations return True.
    run_scenario("T2 (both-true)",
                 payload_present_count=300,
                 blob_data_available_count=300,
                 proposer_boost_set=True,
                 parent_status=PAYLOAD_STATUS_EMPTY)

    # T3: timely-only, no proposer boost. Both return True (different branches).
    run_scenario("T3 (timely-only, no proposer boost)",
                 payload_present_count=300,
                 blob_data_available_count=10,
                 proposer_boost_set=False,
                 parent_status=PAYLOAD_STATUS_FULL)


if __name__ == "__main__":
    main()
