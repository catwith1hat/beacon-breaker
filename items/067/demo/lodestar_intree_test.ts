/**
 * Drop-in vitest test for the lodestar repo demonstrating the builder-sweep
 * divergence (item #67). Exercises the REAL lodestar `getExpectedWithdrawals`
 * function (not a re-implementation) and asserts the spec-conformant amount.
 *
 * This test is expected to FAIL on current lodestar master because
 * `getBuildersSweepWithdrawals` reads from the per-builder
 * `builderBalanceAfterWithdrawals` cache (which has been decremented by the
 * preceding queue drain) instead of `state.builders[idx].balance`.
 *
 * Install:
 *   cp lodestar_intree_test.ts \
 *     vendor/lodestar/packages/state-transition/test/unit/block/buildersWeepDivergence.test.ts
 *
 * Run:
 *   cd vendor/lodestar
 *   pnpm vitest run --project unit test/unit/block/buildersWeepDivergence.test.ts
 *
 * Expected output: the T1.1 test fails with
 *   AssertionError: expected 999800000000n to be 1000000000000n
 * confirming the cache-read divergence.
 */

import {describe, expect, it} from "vitest";
import {config} from "@lodestar/config/default";
import {ForkSeq, SLOTS_PER_EPOCH, SLOTS_PER_HISTORICAL_ROOT} from "@lodestar/params";
import {ssz} from "@lodestar/types";
import {CachedBeaconStateGloas} from "../../../src/types.js";
import {createCachedBeaconStateTest} from "../../../src/testUtils/state.js";
import {getExpectedWithdrawals} from "../../../src/block/processWithdrawals.js";

// Minimum slot at/after which the state will dispatch through the Gloas branch
const GLOAS_SLOT = 1; // Tests use the default config where GLOAS_FORK_EPOCH = 0

function setupGloasStateWithBuilder({
  builderBalance,
  withdrawableEpoch,
  pendingWithdrawalAmount,
}: {
  builderBalance: number;
  withdrawableEpoch: number;
  pendingWithdrawalAmount: number | null;
}): CachedBeaconStateGloas {
  const stateView = ssz.gloas.BeaconState.defaultViewDU();

  // Slot at/after Gloas fork epoch so fork dispatch routes through Gloas paths
  stateView.slot = GLOAS_SLOT;

  // Genesis-style fields
  for (let i = 0; i < SLOTS_PER_HISTORICAL_ROOT; i++) {
    stateView.blockRoots.set(i, new Uint8Array(32));
  }

  // Critical for process_withdrawals to NOT short-circuit on "parent block empty":
  //   process_withdrawals returns early if latest_block_hash != latest_execution_payload_bid.block_hash
  const PARENT_HASH = new Uint8Array(32).fill(0x11);
  stateView.latestBlockHash = PARENT_HASH;
  stateView.latestExecutionPayloadBid.blockHash = PARENT_HASH;

  // Set up a single builder at index 0
  const builderView = ssz.gloas.Builder.toViewDU({
    pubkey: new Uint8Array(48).fill(0xaa),
    version: 0x03, // BUILDER_WITHDRAWAL_PREFIX
    executionAddress: new Uint8Array(20).fill(0xbb),
    balance: builderBalance,
    depositEpoch: 0,
    withdrawableEpoch,
  });
  stateView.builders.push(builderView);

  // Set up the pending withdrawal queue (if requested)
  if (pendingWithdrawalAmount !== null) {
    const pending = ssz.gloas.BuilderPendingWithdrawal.toViewDU({
      feeRecipient: new Uint8Array(20).fill(0xcc),
      amount: pendingWithdrawalAmount,
      builderIndex: 0,
    });
    stateView.builderPendingWithdrawals.push(pending);
  }

  // Withdrawal-index bookkeeping
  stateView.nextWithdrawalIndex = 42;
  stateView.nextWithdrawalBuilderIndex = 0;

  stateView.commit();

  return createCachedBeaconStateTest(stateView, config, {skipSyncPubkeys: true}) as CachedBeaconStateGloas;
}

describe("item #67: lodestar Gloas builder-sweep cache divergence", () => {
  it("T1.1 (collision) — sweep amount MUST equal pre-block builder.balance (FAILS on current lodestar)", () => {
    const builderBalance = 1_000_000_000_000; // 1000 ETH
    const queueAmount = 200_000_000; // 0.2 ETH

    const state = setupGloasStateWithBuilder({
      builderBalance,
      withdrawableEpoch: 0, // sweep-eligible
      pendingWithdrawalAmount: queueAmount,
    });

    const {expectedWithdrawals} = getExpectedWithdrawals(ForkSeq.gloas, state);

    // Expect 2 withdrawals: 1 queue drain + 1 sweep
    expect(expectedWithdrawals.length).toBe(2);

    // Queue withdrawal: amount = withdrawal.amount (200M Gwei) — matches spec ✓
    expect(expectedWithdrawals[0].amount).toBe(BigInt(queueAmount));

    // Sweep withdrawal: spec emits `amount = builder.balance` (pre-block, 1000 ETH).
    // Lodestar emits `amount = cached_balance` (pre-block - queue drain, 999.8 ETH).
    //
    // This assertion FAILS on current lodestar master, confirming the divergence:
    expect(expectedWithdrawals[1].amount).toBe(BigInt(builderBalance));
  });

  it("T1.2 (queue only — no sweep) — no divergence; lodestar matches spec", () => {
    const builderBalance = 1_000_000_000_000;
    const queueAmount = 200_000_000;

    const state = setupGloasStateWithBuilder({
      builderBalance,
      withdrawableEpoch: 999, // NOT sweep-eligible
      pendingWithdrawalAmount: queueAmount,
    });

    const {expectedWithdrawals} = getExpectedWithdrawals(ForkSeq.gloas, state);

    // Only 1 withdrawal: queue drain. No sweep.
    expect(expectedWithdrawals.length).toBe(1);
    expect(expectedWithdrawals[0].amount).toBe(BigInt(queueAmount));
  });

  it("T1.3 (sweep only — no queue) — no divergence; lodestar matches spec", () => {
    const builderBalance = 1_000_000_000_000;

    const state = setupGloasStateWithBuilder({
      builderBalance,
      withdrawableEpoch: 0,
      pendingWithdrawalAmount: null, // empty queue
    });

    const {expectedWithdrawals} = getExpectedWithdrawals(ForkSeq.gloas, state);

    // Only 1 withdrawal: sweep. No queue.
    expect(expectedWithdrawals.length).toBe(1);
    expect(expectedWithdrawals[0].amount).toBe(BigInt(builderBalance));
  });
});
