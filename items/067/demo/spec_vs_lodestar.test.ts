/**
 * Standalone vitest test that empirically demonstrates the lodestar
 * builder-sweep divergence (item #67).
 *
 * This test is self-contained — it does NOT import from @lodestar/state-transition
 * so it can run without lodestar's full dependency tree. It reproduces the exact
 * algorithm from
 *   vendor/lodestar/packages/state-transition/src/block/processWithdrawals.ts:135-243, 411-507
 * (Gloas builder-pending + builder-sweep withdrawal construction) and asserts
 * spec semantics.
 *
 * On the queue+sweep collision scenario, lodestar's cache-read pattern emits a
 * sweep `Withdrawal.amount` that differs from spec's literal `state.builders[idx].balance`
 * read. This test reproduces the divergence and pins the expected (spec-conformant)
 * behavior.
 *
 * To run inside lodestar:
 *   cp spec_vs_lodestar.test.ts packages/state-transition/test/unit/block/
 *   pnpm vitest run --project unit test/unit/block/spec_vs_lodestar.test.ts
 *
 * Or as a stand-alone vitest run with `pnpm i -D vitest`:
 *   npx vitest run spec_vs_lodestar.test.ts
 */

import {describe, expect, it} from "vitest";

// -----------------------------------------------------------------------
// Minimal type definitions mirroring lodestar's Gloas types
// -----------------------------------------------------------------------

const NUMBER_OF_COLUMNS = 128;
const MAX_WITHDRAWALS_PER_PAYLOAD = 16;
const BUILDER_INDEX_FLAG = 1n << 63n;

function convertBuilderIndexToValidatorIndex(builderIndex: number): bigint {
  return BigInt(builderIndex) | BUILDER_INDEX_FLAG;
}

interface Builder {
  pubkey: Uint8Array;
  executionAddress: Uint8Array;
  balance: number;
  withdrawableEpoch: number;
}

interface BuilderPendingWithdrawal {
  feeRecipient: Uint8Array;
  amount: number;
  builderIndex: number;
}

interface Withdrawal {
  index: number;
  validatorIndex: bigint;
  address: Uint8Array;
  amount: bigint;
}

interface State {
  builders: Builder[];
  builderPendingWithdrawals: BuilderPendingWithdrawal[];
  nextWithdrawalBuilderIndex: number;
  nextWithdrawalIndex: number;
  currentEpoch: number;
}

// -----------------------------------------------------------------------
// Spec semantics (pyspec verbatim, gloas/beacon-chain.md:1184-1297)
// -----------------------------------------------------------------------

function specGetBuilderWithdrawals(
  state: State,
  withdrawalIndex: number
): {withdrawals: Withdrawal[]; withdrawalIndex: number} {
  const withdrawalsLimit = MAX_WITHDRAWALS_PER_PAYLOAD - 1;
  const withdrawals: Withdrawal[] = [];

  for (const w of state.builderPendingWithdrawals) {
    if (withdrawals.length >= withdrawalsLimit) break;
    withdrawals.push({
      index: withdrawalIndex,
      validatorIndex: convertBuilderIndexToValidatorIndex(w.builderIndex),
      address: w.feeRecipient,
      amount: BigInt(w.amount),
    });
    withdrawalIndex++;
  }
  return {withdrawals, withdrawalIndex};
}

function specGetBuildersSweepWithdrawals(
  state: State,
  withdrawalIndex: number,
  priorCount: number
): {withdrawals: Withdrawal[]; withdrawalIndex: number} {
  const withdrawalsLimit = MAX_WITHDRAWALS_PER_PAYLOAD - 1;
  const buildersLimit = state.builders.length;
  const withdrawals: Withdrawal[] = [];
  let builderIndex = state.nextWithdrawalBuilderIndex;

  for (let n = 0; n < buildersLimit; n++) {
    if (priorCount + withdrawals.length >= withdrawalsLimit) break;
    const builder = state.builders[builderIndex];
    // SPEC: read builder.balance DIRECTLY from state, not from a cache
    if (builder.withdrawableEpoch <= state.currentEpoch && builder.balance > 0) {
      withdrawals.push({
        index: withdrawalIndex,
        validatorIndex: convertBuilderIndexToValidatorIndex(builderIndex),
        address: builder.executionAddress,
        amount: BigInt(builder.balance),
      });
      withdrawalIndex++;
    }
    builderIndex = (builderIndex + 1) % state.builders.length;
  }
  return {withdrawals, withdrawalIndex};
}

function specGetExpectedWithdrawals(state: State): Withdrawal[] {
  let withdrawalIndex = state.nextWithdrawalIndex;
  const withdrawals: Withdrawal[] = [];

  const bw = specGetBuilderWithdrawals(state, withdrawalIndex);
  withdrawals.push(...bw.withdrawals);
  withdrawalIndex = bw.withdrawalIndex;

  const sw = specGetBuildersSweepWithdrawals(state, withdrawalIndex, withdrawals.length);
  withdrawals.push(...sw.withdrawals);

  return withdrawals;
}

// -----------------------------------------------------------------------
// Lodestar semantics
// (vendor/lodestar/packages/state-transition/src/block/processWithdrawals.ts:135-243, 411-507)
// -----------------------------------------------------------------------

function lodestarGetBuilderWithdrawals(
  state: State,
  withdrawalIndex: number,
  builderBalanceAfterWithdrawals: Map<number, number>
): {withdrawals: Withdrawal[]; withdrawalIndex: number} {
  const withdrawalsLimit = MAX_WITHDRAWALS_PER_PAYLOAD - 1;
  const withdrawals: Withdrawal[] = [];

  for (const w of state.builderPendingWithdrawals) {
    if (withdrawals.length >= withdrawalsLimit) break;

    // Initialize cache from state if not present
    let balance = builderBalanceAfterWithdrawals.get(w.builderIndex);
    if (balance === undefined) {
      balance = state.builders[w.builderIndex].balance;
      builderBalanceAfterWithdrawals.set(w.builderIndex, balance);
    }

    // Push withdrawal with the queue entry's amount (spec-correct here)
    withdrawals.push({
      index: withdrawalIndex,
      validatorIndex: convertBuilderIndexToValidatorIndex(w.builderIndex),
      address: w.feeRecipient,
      amount: BigInt(w.amount),
    });
    withdrawalIndex++;

    // DECREMENT THE CACHE (this is what triggers the divergence below)
    builderBalanceAfterWithdrawals.set(w.builderIndex, balance - w.amount);
  }
  return {withdrawals, withdrawalIndex};
}

function lodestarGetBuildersSweepWithdrawals(
  state: State,
  withdrawalIndex: number,
  priorCount: number,
  builderBalanceAfterWithdrawals: Map<number, number>
): {withdrawals: Withdrawal[]; withdrawalIndex: number} {
  const withdrawalsLimit = MAX_WITHDRAWALS_PER_PAYLOAD - 1;
  const buildersLimit = state.builders.length;
  const withdrawals: Withdrawal[] = [];

  for (let n = 0; n < buildersLimit; n++) {
    if (priorCount + withdrawals.length >= withdrawalsLimit) break;

    const builderIndex = (state.nextWithdrawalBuilderIndex + n) % state.builders.length;
    const builder = state.builders[builderIndex];

    // LODESTAR: read balance from CACHE (which has been decremented by queue drains)
    let balance = builderBalanceAfterWithdrawals.get(builderIndex);
    if (balance === undefined) {
      balance = builder.balance;
      builderBalanceAfterWithdrawals.set(builderIndex, balance);
    }

    if (builder.withdrawableEpoch <= state.currentEpoch && balance > 0) {
      withdrawals.push({
        index: withdrawalIndex,
        validatorIndex: convertBuilderIndexToValidatorIndex(builderIndex),
        address: builder.executionAddress,
        amount: BigInt(balance), // <-- CACHED, not pre-block builder.balance
      });
      withdrawalIndex++;
      builderBalanceAfterWithdrawals.set(builderIndex, 0);
    }
  }
  return {withdrawals, withdrawalIndex};
}

function lodestarGetExpectedWithdrawals(state: State): Withdrawal[] {
  let withdrawalIndex = state.nextWithdrawalIndex;
  const withdrawals: Withdrawal[] = [];
  const builderBalanceAfterWithdrawals = new Map<number, number>();

  const bw = lodestarGetBuilderWithdrawals(state, withdrawalIndex, builderBalanceAfterWithdrawals);
  withdrawals.push(...bw.withdrawals);
  withdrawalIndex = bw.withdrawalIndex;

  const sw = lodestarGetBuildersSweepWithdrawals(
    state,
    withdrawalIndex,
    withdrawals.length,
    builderBalanceAfterWithdrawals
  );
  withdrawals.push(...sw.withdrawals);

  return withdrawals;
}

// -----------------------------------------------------------------------
// Test fixtures
// -----------------------------------------------------------------------

function makeCollisionState(): State {
  return {
    builders: [
      {
        pubkey: new Uint8Array(48).fill(0xaa),
        executionAddress: new Uint8Array(20).fill(0xbb),
        balance: 1_000_000_000_000, // 1000 ETH
        withdrawableEpoch: 50, // <= currentEpoch=100, sweep-eligible
      },
    ],
    builderPendingWithdrawals: [
      {
        feeRecipient: new Uint8Array(20).fill(0xcc),
        amount: 200_000_000, // 0.2 ETH queue drain
        builderIndex: 0,
      },
    ],
    nextWithdrawalBuilderIndex: 0,
    nextWithdrawalIndex: 42,
    currentEpoch: 100,
  };
}

function makeQueueOnlyState(): State {
  return {
    builders: [
      {
        pubkey: new Uint8Array(48).fill(0xaa),
        executionAddress: new Uint8Array(20).fill(0xbb),
        balance: 1_000_000_000_000,
        withdrawableEpoch: 200, // > currentEpoch=100, NOT sweep-eligible
      },
    ],
    builderPendingWithdrawals: [
      {
        feeRecipient: new Uint8Array(20).fill(0xcc),
        amount: 200_000_000,
        builderIndex: 0,
      },
    ],
    nextWithdrawalBuilderIndex: 0,
    nextWithdrawalIndex: 42,
    currentEpoch: 100,
  };
}

function makeSweepOnlyState(): State {
  return {
    builders: [
      {
        pubkey: new Uint8Array(48).fill(0xaa),
        executionAddress: new Uint8Array(20).fill(0xbb),
        balance: 1_000_000_000_000,
        withdrawableEpoch: 50,
      },
    ],
    builderPendingWithdrawals: [],
    nextWithdrawalBuilderIndex: 0,
    nextWithdrawalIndex: 42,
    currentEpoch: 100,
  };
}

function makeMultiEntryCollisionState(): State {
  // Three queue entries for the same builder + sweep eligibility
  const state = makeCollisionState();
  state.builderPendingWithdrawals = [
    {feeRecipient: new Uint8Array(20).fill(0xc1), amount: 100_000_000, builderIndex: 0},
    {feeRecipient: new Uint8Array(20).fill(0xc2), amount: 200_000_000, builderIndex: 0},
    {feeRecipient: new Uint8Array(20).fill(0xc3), amount: 300_000_000, builderIndex: 0},
  ];
  return state;
}

// -----------------------------------------------------------------------
// Tests
// -----------------------------------------------------------------------

describe("item #67: lodestar builder-sweep cache divergence", () => {
  it("T1.1: collision case — lodestar diverges from spec by exactly the queue drain", () => {
    const state = makeCollisionState();
    const specOut = specGetExpectedWithdrawals(state);
    const lodestarOut = lodestarGetExpectedWithdrawals(state);

    // Both produce 2 withdrawals (queue + sweep)
    expect(specOut.length).toBe(2);
    expect(lodestarOut.length).toBe(2);

    // The first withdrawal (queue drain) matches: amount = withdrawal.amount
    expect(specOut[0].amount).toBe(200_000_000n);
    expect(lodestarOut[0].amount).toBe(200_000_000n);

    // The second withdrawal (sweep) DIVERGES:
    //   spec: amount = pre-block builder.balance = 1_000_000_000_000
    //   lodestar: amount = pre_balance - queue_drain = 999_800_000_000
    expect(specOut[1].amount).toBe(1_000_000_000_000n);
    expect(lodestarOut[1].amount).toBe(999_800_000_000n);

    // The divergence equals exactly the queue-drain amount
    const diff = specOut[1].amount - lodestarOut[1].amount;
    expect(diff).toBe(200_000_000n);
  });

  it("T1.2: queue-only — lodestar matches spec (no sweep, no divergence)", () => {
    const state = makeQueueOnlyState();
    const specOut = specGetExpectedWithdrawals(state);
    const lodestarOut = lodestarGetExpectedWithdrawals(state);

    expect(specOut.length).toBe(1);
    expect(lodestarOut.length).toBe(1);
    expect(specOut).toEqual(lodestarOut);
  });

  it("T1.3: sweep-only — lodestar matches spec (no queue, no divergence)", () => {
    const state = makeSweepOnlyState();
    const specOut = specGetExpectedWithdrawals(state);
    const lodestarOut = lodestarGetExpectedWithdrawals(state);

    expect(specOut.length).toBe(1);
    expect(lodestarOut.length).toBe(1);
    expect(specOut[0].amount).toBe(1_000_000_000_000n);
    expect(specOut).toEqual(lodestarOut);
  });

  it("T1.4: multi-entry collision — lodestar diverges by sum of queue drains", () => {
    const state = makeMultiEntryCollisionState();
    const specOut = specGetExpectedWithdrawals(state);
    const lodestarOut = lodestarGetExpectedWithdrawals(state);

    // 3 queue + 1 sweep = 4 withdrawals
    expect(specOut.length).toBe(4);
    expect(lodestarOut.length).toBe(4);

    // Queue drains match
    for (let i = 0; i < 3; i++) {
      expect(specOut[i].amount).toBe(lodestarOut[i].amount);
    }

    // Sweep diverges by SUM of queue drains = 100M + 200M + 300M = 600M
    expect(specOut[3].amount).toBe(1_000_000_000_000n);
    expect(lodestarOut[3].amount).toBe(999_400_000_000n);
    expect(specOut[3].amount - lodestarOut[3].amount).toBe(600_000_000n);
  });

  it("T1.5: pin spec-conformant sweep amount — would FAIL on current lodestar", () => {
    // This is the assertion that would fail if run against lodestar's actual
    // getBuildersSweepWithdrawals function. It pins the correct (spec) behavior
    // and is the canonical assertion to drop into a lodestar in-tree PR.
    const state = makeCollisionState();
    const specOut = specGetExpectedWithdrawals(state);

    expect(specOut[1].amount).toBe(BigInt(state.builders[0].balance));
    // ^^^ lodestar would emit BigInt(state.builders[0].balance) - 200_000_000 = 999_800_000_000
  });
});
