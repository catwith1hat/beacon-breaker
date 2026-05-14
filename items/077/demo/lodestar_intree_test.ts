/**
 * Drop-in vitest test for the lodestar repo demonstrating the
 * `shouldExtendPayload` divergence (item #77). Exercises the REAL lodestar
 * `protoArray.shouldExtendPayload` (not a re-implementation) and asserts
 * the spec-conformant outcome.
 *
 * This test is expected to FAIL on current lodestar master because
 * `protoArray.ts:715-749` implements `shouldExtendPayload` with only the
 * `isPayloadTimely` check in condition 1; the spec requires
 * `is_payload_timely AND is_payload_data_available`. Lodestar's
 * `notifyPtcMessages(blockRoot, ptcIndices, payloadPresent)` signature
 * accepts only the timeliness bit; `payloadAttestation.data.blobDataAvailable`
 * is discarded at the three call sites in `packages/beacon-node/src`.
 *
 * Install:
 *   cp lodestar_intree_test.ts \
 *     vendor/lodestar/packages/fork-choice/test/unit/protoArray/shouldExtendPayloadDivergence.test.ts
 *
 * Run:
 *   cd vendor/lodestar
 *   pnpm vitest run --project unit \
 *     test/unit/protoArray/shouldExtendPayloadDivergence.test.ts
 *
 * Expected output: the divergence test fails with the spec-conformant
 * `expect(shouldExtend).toBe(false)` because lodestar returns `true`,
 * confirming the missing `is_payload_data_available` conjunct.
 */

import {describe, expect, it} from "vitest";
import {DataAvailabilityStatus, computeStartSlotAtEpoch} from "@lodestar/state-transition";
import {RootHex} from "@lodestar/types";
import {ExecutionStatus, PayloadStatus, ProtoArray, ProtoBlock} from "../../../src/index.js";

describe("item #77: lodestar shouldExtendPayload missing is_payload_data_available", () => {
  const genesisEpoch = 0;
  const gloasForkEpoch = 0; // Gloas active from genesis for this test
  const gloasForkSlot = computeStartSlotAtEpoch(gloasForkEpoch);

  const stateRoot = "0x00";
  const genesisRoot = "0x01";
  const candidateRoot = "0x02";
  const adversarialChildRoot = "0x03";
  // Candidate's bid commits to this execution block-hash (PENDING/EMPTY get this hash).
  const candidateBidHash = "0xbb";
  // The actual envelope brings a different exec hash; FULL gets this.
  const candidateFullHash = "0xff";

  /** Pre-Gloas test block: parentBlockHash=null, payloadStatus=FULL, exec hash = blockRoot. */
  function createPreGloasBlock(slot: number, blockRoot: RootHex, parentRoot: RootHex): ProtoBlock {
    return {
      slot,
      blockRoot,
      parentRoot,
      stateRoot,
      targetRoot: genesisRoot,
      justifiedEpoch: genesisEpoch,
      justifiedRoot: genesisRoot,
      finalizedEpoch: genesisEpoch,
      finalizedRoot: genesisRoot,
      unrealizedJustifiedEpoch: genesisEpoch,
      unrealizedJustifiedRoot: genesisRoot,
      unrealizedFinalizedEpoch: genesisEpoch,
      unrealizedFinalizedRoot: genesisRoot,
      timeliness: true,
      executionPayloadBlockHash: blockRoot,
      executionPayloadNumber: slot,
      executionStatus: ExecutionStatus.Valid,
      dataAvailabilityStatus: DataAvailabilityStatus.Available,
      parentBlockHash: null,
      payloadStatus: PayloadStatus.FULL,
    };
  }

  /** Gloas test block: parentBlockHash set, payloadStatus=PENDING initially. */
  function createGloasBlock(
    slot: number,
    blockRoot: RootHex,
    parentRoot: RootHex,
    parentBlockHash: RootHex,
    bidBlockHash: RootHex
  ): ProtoBlock {
    return {
      slot,
      blockRoot,
      parentRoot,
      stateRoot,
      targetRoot: genesisRoot,
      justifiedEpoch: genesisEpoch,
      justifiedRoot: genesisRoot,
      finalizedEpoch: genesisEpoch,
      finalizedRoot: genesisRoot,
      unrealizedJustifiedEpoch: genesisEpoch,
      unrealizedJustifiedRoot: genesisRoot,
      unrealizedFinalizedEpoch: genesisEpoch,
      unrealizedFinalizedRoot: genesisRoot,
      timeliness: true,
      // PENDING/EMPTY variants inherit this; FULL is overwritten by onExecutionPayload.
      executionPayloadBlockHash: bidBlockHash,
      executionPayloadNumber: slot,
      executionStatus: ExecutionStatus.Valid,
      dataAvailabilityStatus: DataAvailabilityStatus.Available,
      parentBlockHash,
      payloadStatus: PayloadStatus.PENDING,
    };
  }

  function setupAdversarialBoostScenario(): {
    protoArray: ProtoArray;
    candidateRoot: RootHex;
    adversarialChildRoot: RootHex;
  } {
    const protoArray = new ProtoArray({
      pruneThreshold: 0,
      justifiedEpoch: genesisEpoch,
      justifiedRoot: genesisRoot,
      finalizedEpoch: genesisEpoch,
      finalizedRoot: genesisRoot,
    });

    // Genesis: pre-Gloas anchor, exec hash = genesisRoot
    protoArray.onBlock(createPreGloasBlock(0, genesisRoot, "0x00"), 0, null);

    // Candidate: Gloas, declares parent (genesis) FULL via parentBlockHash=genesisRoot.
    // Bid block-hash differs from blockRoot so we can later distinguish EMPTY from FULL.
    const candidate = createGloasBlock(
      gloasForkSlot + 1,
      candidateRoot,
      genesisRoot,
      genesisRoot, // parent_block_hash = genesis's exec hash = genesisRoot
      candidateBidHash // candidate's own bid commits to this exec hash
    );
    protoArray.onBlock(candidate, gloasForkSlot + 1, null);

    // Deliver candidate's payload envelope with a DIFFERENT exec hash than the bid.
    // FULL variant gets candidateFullHash; PENDING/EMPTY retain candidateBidHash.
    protoArray.onExecutionPayload(
      candidateRoot,
      gloasForkSlot + 1,
      candidateFullHash,
      gloasForkSlot + 1,
      null,
      ExecutionStatus.Valid,
      DataAvailabilityStatus.Available
    );

    // Adversarial child: declares parent_block_hash = candidateBidHash → matches
    // candidate's EMPTY variant (executionPayloadBlockHash = candidateBidHash) but
    // NOT candidate's FULL variant (executionPayloadBlockHash = candidateFullHash).
    // Per lodestar's `getNodeIndexByRootAndBlockHash` (protoArray.ts:258-284),
    // FULL is preferred; if no match, falls back to EMPTY. Here FULL doesn't match
    // (hash differs), EMPTY does → adversarial sees candidate as PAYLOAD_STATUS_EMPTY.
    //
    // This makes `isParentNodeFull(adversarial)` = false, which is the condition the
    // spec's `should_extend_payload` checks in its proposer-boost branches (line 407).
    const adversarial = createGloasBlock(
      gloasForkSlot + 2,
      adversarialChildRoot,
      candidateRoot,
      candidateBidHash, // matches candidate's EMPTY, not FULL
      adversarialChildRoot
    );
    protoArray.onBlock(adversarial, gloasForkSlot + 2, null);

    // Cast PTC votes for the candidate: 300 payloadPresent=true (timely).
    // Spec semantics: this populates `payload_timeliness_vote[candidate]` with
    // 300 True bits (> PAYLOAD_TIMELY_THRESHOLD = 256). Spec ALSO requires
    // `payload_data_availability_vote[candidate]` to populate; here that array
    // should be empty (PTC didn't vote blob_data_available).
    //
    // Lodestar: notifyPtcMessages signature is
    //   (blockRoot, ptcIndices, payloadPresent: boolean)
    // — single bool, no blob_data_available channel. The `payloadDataAvailabilityVote`
    // map does not exist in lodestar at all. So this single call models a "300 PTC
    // members saw the payload" attestation; nothing models the orthogonal
    // "but blob data was unavailable" channel that spec keeps separately.
    const ptcIndices = Array.from({length: 300}, (_, i) => i);
    protoArray.notifyPtcMessages(candidateRoot, ptcIndices, true);

    return {protoArray, candidateRoot, adversarialChildRoot};
  }

  it("T1 (adversarial proposer-boost, no data-availability tracking): shouldExtendPayload MUST be false per spec — FAILS on current lodestar", () => {
    const {protoArray, candidateRoot, adversarialChildRoot} = setupAdversarialBoostScenario();

    // Spec semantics breakdown (vendor/consensus-specs/specs/gloas/fork-choice.md:398-409):
    //
    //   if not is_payload_verified(store, root): return False
    //     → False: payload was delivered via onExecutionPayload.
    //
    //   if (is_payload_timely(store, root) AND is_payload_data_available(store, root)): return True
    //     → is_payload_timely  = True  (300 > 256)
    //     → is_payload_data_available = False (no blob_data_available votes)
    //     → conjunction = False  ← spec exits this branch
    //
    //   if proposer_root == Root(): return True
    //     → False: proposer-boost is set to adversarialChild.
    //
    //   if store.blocks[proposer_root].parent_root != root: return True
    //     → False: adversarialChild.parent_root == candidateRoot.
    //
    //   if is_parent_node_full(store, store.blocks[proposer_root]): return True
    //     → False: adversarial's parent_block_hash = candidateBidHash matches
    //       candidate's EMPTY variant, NOT FULL. So get_parent_payload_status
    //       returns EMPTY → is_parent_node_full = False.
    //
    //   return False
    //
    // Lodestar's protoArray.ts:715-749 takes the FIRST branch (condition 1)
    // on isPayloadTimely alone — without the AND with isPayloadDataAvailable —
    // so it returns True.
    const shouldExtend = protoArray.shouldExtendPayload(candidateRoot, adversarialChildRoot);

    // Spec says false. Current lodestar returns true.
    // This assertion FAILS on current lodestar master, confirming item #77:
    expect(shouldExtend).toBe(false);
  });

  it("T2 (no proposer-boost): shouldExtendPayload must be true (condition 2 in spec)", () => {
    const {protoArray, candidateRoot} = setupAdversarialBoostScenario();

    // proposerBoostRoot = null → spec condition 2 (proposer_root == Root()) fires.
    // Lodestar condition 1 (isPayloadTimely) also fires. Both return true.
    const shouldExtend = protoArray.shouldExtendPayload(candidateRoot, null);
    expect(shouldExtend).toBe(true);
  });
});
