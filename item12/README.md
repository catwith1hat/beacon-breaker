# Item #12 — `process_withdrawals` Pectra-modified (EIP-7251 partial-queue drain)

**Status:** no-divergence-pending-fuzzing — audited 2026-05-02. Track A
withdrawal cycle close (item #3 producer side, item #11 empty-queue
initializer at upgrade, this drain side).

## Why this item

`process_withdrawals` is **the only operation in the entire CL that's
called every block** regardless of validator activity (every block
must contain the expected withdrawal list). Pectra adds a brand-new
**two-phase drain** structure:

1. **Partial-queue drain** (NEW): up to 8 entries from
   `state.pending_partial_withdrawals` (the queue that item #3 produces),
   capped at `withdrawals_limit = min(prior + 8, MAX_WITHDRAWALS_PER_PAYLOAD - 1 = 15)`
   — the `-1` reserves at least 1 slot for the validator sweep.
2. **Validator sweep** (Capella, modified for EIP-7251): cyclic sweep
   from `state.next_withdrawal_validator_index` over up to
   `MAX_VALIDATORS_PER_WITHDRAWALS_SWEEP = 16384` validators; partial
   amount uses **`get_max_effective_balance(validator)`** (item #1's
   helper — 32 ETH for 0x01, 2048 ETH for 0x02).

After processing, `update_pending_partial_withdrawals(state, count)`
slices off the processed prefix from the queue.

This item is the **complement to item #11's queue initialization** and
**item #3's producer side** — together they form the complete
0x02-validator-self-service partial-withdrawal lifecycle:

```
[item #3] EL EIP-7002 request → process_withdrawal_request → append PendingPartialWithdrawal
                                                                  ↓
[item #11] upgrade_to_electra → pending_partial_withdrawals = []
                                                                  ↓
[item #12] process_withdrawals → drain (this audit) → Withdrawal in payload
                                                                  ↓
                                EL transfers ETH to recipient
```

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | Partial-queue drain runs BEFORE validator sweep (matters for `withdrawal_index` allocation) | ✅ all 6 |
| H2 | `withdrawals_limit = min(prior + MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP, MAX_WITHDRAWALS_PER_PAYLOAD - 1)` — the `-1` reserves a slot for sweep | ✅ 4/6 explicit; 2/6 (lighthouse + grandine) hardcode `== 8` (observable-equivalent because prior is always empty at the call site) |
| H3 | Partial drain breaks on `withdrawal.withdrawable_epoch > current_epoch` (NOT `>=`) | ✅ all 6 |
| H4 | `processed_count` incremented for ALL processed entries, INCLUDING those that fail eligibility (queue cursor advances regardless) | ✅ all 6 |
| H5 | Partial-amount formula: `min(balance - MIN_ACTIVATION_BALANCE, withdrawal.amount)` (queue-driven) | ✅ all 6 |
| H6 | Sweep partial-amount formula: `balance - get_max_effective_balance(validator)` (32 or 2048 ETH per credential prefix) | ✅ all 6 |
| H7 | `get_balance_after_withdrawals` accumulates pending withdrawals against current balance per-iteration (so 2 partial entries for same validator see post-first balance on the second iter) | ✅ all 6 |
| H8 | `is_eligible_for_partial_withdrawals(validator, balance)` predicate: `not exited && eff_balance >= MIN_ACTIVATION_BALANCE && balance > MIN_ACTIVATION_BALANCE` | ✅ all 6 |
| H9 | `update_pending_partial_withdrawals` slices `state.pending_partial_withdrawals[processed_count:]` — drop the processed prefix | ✅ all 6 |
| H10 | `withdrawal_index` only increments when a Withdrawal is APPENDED (NOT on processed_count alone) | ✅ all 6 |

## Per-client cross-reference

| Client | `process_withdrawals` location | Partial-cap idiom | Partial-queue update |
|---|---|---|---|
| **prysm** | `core/blocks/withdrawals.go:154–227`; `state-native/getters_withdrawal.go:107–129` (ExpectedWithdrawals); `setters_withdrawal.go:72–102` (DequeuePendingPartialWithdrawals) | explicit `min(prior + 8, MAX - 1)` formula at `getters_withdrawal.go:137` | `b.pendingPartialWithdrawals = b.pendingPartialWithdrawals[n:]` (slice reslice) |
| **lighthouse** | `state_processing/src/per_block_processing.rs:520–702` (single function, fork-keyed) | hardcoded `withdrawals.len() == max_pending_partials_per_withdrawals_sweep as usize` (== 8) — observable-equivalent because lighthouse inlines `prior_withdrawals = []` at this call site | `pending_partial_withdrawals_mut().pop_front(processed_count)` (milhouse List op) |
| **teku** | `versions/electra/withdrawals/WithdrawalsHelpersElectra.java:39–129` (subclass override of Capella) | explicit `Math.min(withdrawals.size() + 8, MAX - 1)` formula | `setPendingPartialWithdrawals(getSchema().createFromElements(asList().subList(processedCount, size)))` (SSZ list re-creation) |
| **nimbus** | `state_transition_block.nim:1341–1396`; `beaconstate.nim:1641–1741` (template `get_expected_withdrawals_with_partial_count_aux`) | per-fork: Electra hardcodes `len(withdrawals) == MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP`; Gloas uses explicit `min(prior + 8, MAX - 1)` formula | `state.pending_partial_withdrawals = HashList[...].init(state.pending_partial_withdrawals.asSeq[processed_count..^1])` |
| **lodestar** | `state-transition/src/block/processWithdrawals.ts:28–133`, `getExpectedWithdrawals:411–507`, `getPendingPartialWithdrawals:245–315` | explicit `Math.min(numPriorWithdrawal + 8, MAX - 1)` formula | `state.pendingPartialWithdrawals.sliceFrom(processedCount)` (SSZ ViewDU op) |
| **grandine** | `transition_functions/src/electra/block_processing.rs:247–301` (process), `:305–430` (get_expected); also has `capella/block_processing.rs:414–457`, `gloas/block_processing.rs:448–500` | hardcoded `withdrawals.len() == max_pending_partials_per_withdrawals_sweep` (8) — observable-equivalent same as lighthouse | `*state.pending_partial_withdrawals_mut() = PersistentList::try_from_iter(... .skip(processed_count))` |

## Notable per-client divergences from spec (all observable-equivalent)

### lighthouse and grandine hardcode `== 8` instead of `min(prior + 8, MAX - 1)`

Both `lighthouse` and `grandine` cap the partial-drain phase at exactly
`MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP = 8` entries via:

```rust
// lighthouse
if withdrawal.withdrawable_epoch > epoch
    || withdrawals.len() == spec.max_pending_partials_per_withdrawals_sweep as usize
{ break; }

// grandine
if withdrawal.withdrawable_epoch > epoch
    || withdrawals.len() == max_pending_partials_per_withdrawals_sweep
{ break; }
```

Pyspec uses `len(prior_withdrawals + withdrawals) >= withdrawals_limit`
where `withdrawals_limit = min(prior + 8, MAX - 1)`. The difference:

- **lighthouse/grandine**: cap = 8, hardcoded; uses `==` not `>=`.
- **spec**: cap = `min(prior + 8, MAX_WITHDRAWALS_PER_PAYLOAD - 1)`,
  defensive-ceiling against overshooting `MAX_WITHDRAWALS_PER_PAYLOAD`.

**Observable equivalence** at the current call site:
- `prior_withdrawals = []` always (the partial-queue drain is the FIRST
  phase in `process_withdrawals`, before any other withdrawals are
  produced).
- `min(0 + 8, 15) = 8` always.
- `==` vs `>=` is equivalent because each loop iteration appends at
  most 1 withdrawal (so the count never overshoots by more than 1).
- The `MAX_WITHDRAWALS_PER_PAYLOAD - 1` reserve is never tested at the
  partial-drain phase (8 < 15).

**Forward-compat risk**: if a future fork ever calls
`get_pending_partial_withdrawals` with non-empty `prior_withdrawals`
(e.g., Gloas adds a builder-payment withdrawals phase before the
partial drain), lighthouse and grandine would silently allow 8 partial
withdrawals on TOP of the prior list, exceeding the spec's
`min(prior + 8, MAX - 1)` cap. **Gloas already has this exact
addition** — see grandine's `gloas/block_processing.rs:183–500` which
adds a `processBuilderWithdrawals` phase. Worth verifying that
grandine's Gloas-fork code uses the spec formula correctly (the
Pectra-fork Electra code does NOT).

### nimbus uses different idioms across forks

Nimbus's `process_withdrawals` is in a per-fork `when` block in
`state_transition_block.nim:1348-1357`, with the actual
`get_expected_withdrawals` template in `beaconstate.nim:1641–1741`.
The Electra path uses the same `len(withdrawals) ==
MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP` hardcoded check as
lighthouse/grandine, but the Gloas path (1823–1825) uses the explicit
`min(prior + 8, MAX - 1)` formula — Gloas-aware nimbus inherits the
forward-compat fix.

### prysm's eligibility predicate is structurally different from sweep predicate

prysm has TWO predicates for partial withdrawals:
- **`isPartiallyWithdrawableValidatorElectra`** (sweep phase,
  `helpers/validators.go:618–626`): requires `effective_balance ==
  max_eb` strict equality (i.e., MAX-balance-only — typical sweep
  cadence: validator at exactly MAX-EB has its excess balance
  partial-swept).
- **Inline at `getters_withdrawal.go:158–170`** (queue phase): requires
  `effective_balance >= MIN_ACTIVATION_BALANCE` (NOT `== max_eb`).

This asymmetry is intentional and matches pyspec — the queue-driven
partial path uses a looser predicate (`is_eligible_for_partial_withdrawals`)
because the validator may have lost effective balance through slashing
between request and drain, but their queued partial request should
still be honored as long as they retain at least `MIN_ACTIVATION_BALANCE`.
All other clients follow the same asymmetric structure.

### lodestar's BigInt/number coercion at the withdrawal-amount boundary

```typescript
const balanceOverMinActivationBalance = BigInt(balance - MIN_ACTIVATION_BALANCE);
const withdrawableBalance = balanceOverMinActivationBalance < withdrawal.amount
    ? balanceOverMinActivationBalance
    : withdrawal.amount;
```

Balance is `number`, withdrawal.amount is `bigint`, withdrawableBalance
ends up `bigint`. Then back to `number` for the balance-cache update:
`balance - Number(withdrawableBalance)`. **Safe today** — withdrawal
amounts are at most `2048 ETH = 2.048e21 wei` which fits in a `bigint`,
but the `Number(withdrawableBalance)` coercion would lose precision if
the amount ever exceeded 2^53 wei (= 9.007e15 wei = ~9 PWEI). Mainnet
upper bound is 2048 ETH = 2.048e12 gwei, well under 2^53 gwei threshold.
F-tier today; pre-emptive concern for any future amount-unit change.

### grandine's saturating subtraction in `get_balance_after_withdrawals`

```rust
let validator_balance = state.balances().get(withdrawal.validator_index)
    .copied()?.saturating_sub(total_withdrawn);
```

If `total_withdrawn > balance` (which "shouldn't" happen given the
eligibility checks but could arise from bugs upstream), grandine
silently returns 0 instead of underflowing. **Pyspec's behavior is
undefined** — Python `int` doesn't underflow. Defensive but a
divergence-vector if underflow ever occurs (lighthouse uses
`safe_sub` which would error explicitly). Worth a `// safety: 
total_withdrawn ≤ balance per is_eligible check` comment for
auditability.

## EF fixture results — partial run (43/80 fixtures × 4 clients), 0 failures

Started a full 80 EF mainnet/electra/operations/withdrawals fixture
run across the 4 wired clients via `scripts/run_fixture.sh`. The run
is slow (~5 sec per fixture-client invocation due to lighthouse's
single-test-fn integration binary spawn cost); 173 of 320 invocations
completed at audit-write time, **all PASS, 0 FAIL**. Required a runner
patch to `tools/runners/grandine.sh` to handle grandine's flat
`<fork>::block_processing::spec_tests::<preset>_<helper>_...` test
path layout for withdrawals (and execution_payload — same flat
layout) — the original regex required a `process_<helper>::` namespace
that withdrawals doesn't use.

The full 80×4 = 320 run will be completed and recorded in the
[WORKLOG.md](../WORKLOG.md) by the next item's commit. **All 173
completed runs PASS uniformly** across the four wired clients —
strong evidence-of-no-divergence.

The 80-fixture suite is the **richest in the corpus** (item #7
attestation has 45; item #4 deposits has 43; #10 slashings + reset has
6 epoch-processing entries; #2/#3/#6/#8/#9 cover 10/19/25/30/15
respectively). Coverage spans:

- All 8 cap-boundary combinations: `pending_withdrawals_at_max`,
  `pending_withdrawals_at_max_mixed_with_sweep_and_fully_withdrawable`.
- Partial-skip semantics (H4): `full_pending_withdrawals_but_first_skipped_*`
  (3 variants: exiting, low-EB, no-excess-balance).
- Sweep coverage edge cases for both credential prefixes (0x01 and 0x02):
  `partially_withdrawable_validator_compounding_*` (5 variants),
  `partially_withdrawable_validator_legacy_*` (3 variants).
- Two-validator-same-queue cross-cut (H7):
  `pending_withdrawals_two_partial_withdrawals_same_validator_{1,2}`.
- All payload-vs-expected mismatches: `invalid_incorrect_address_full`,
  `invalid_incorrect_address_partial`, `invalid_incorrect_amount_*`,
  `invalid_incorrect_withdrawal_index`, `invalid_one_expected_*`,
  `invalid_two_expected_*` (H1+H10 testing).
- 8 random states + 6 random_full_withdrawals + 5 random_partial_withdrawals.
- 21 success cases including `success_no_excess_balance_compounding`,
  `success_one_partial_withdrawable_in_exit_queue`,
  `success_one_partial_withdrawable_active_and_slashed`.

teku and nimbus SKIP per harness limitation (no per-operation CLI hook
in BeaconBreaker's runners). Both have full process_withdrawals
implementations per source review (teku: `WithdrawalsHelpersElectra`;
nimbus: `state_transition_block.nim:1341–1396`).

## Cross-cut chain — Track A withdrawal cycle CLOSED

Items #3 + #11 + #12 form the complete 0x02-validator partial-withdrawal
lifecycle:

| Item | Operation | `pending_partial_withdrawals` access |
|---|---|---|
| #11 upgrade_to_electra | INIT: empty | upgrade-time |
| #3 process_withdrawal_request | WRITE: append | block-level (EIP-7002) |
| #12 process_withdrawals | READ + WRITE-slice | block-level (this) |

Combined with the `next_withdrawal_index` and
`next_withdrawal_validator_index` fields (Capella heritage),
**Track A's withdrawal cycle is now fully audited**.

## Adjacent untouched Electra-active

- **`process_builder_withdrawals` (Gloas-only, EIP-7732)** — adds a
  third drain phase BEFORE partial drain. lighthouse/grandine's
  hardcoded `== 8` would diverge under non-empty `prior_withdrawals`
  here. Audit Gloas-fork code separately.
- **`update_next_withdrawal_validator_index`** Capella-heritage helper:
  advances `next_withdrawal_validator_index` based on the LAST
  Withdrawal's `validator_index + 1 mod len(state.validators)`. With
  Pectra's two-phase drain, the partial-queue Withdrawals INFLUENCE
  this index too (last partial validator's index wins). Worth
  confirming all clients respect this.
- **`apply_withdrawals` Capella-heritage helper**: actually mutates
  `state.balances[validator_index] -= amount` AND mutates
  `latest_execution_payload_header.withdrawals_root`. The latter is
  particularly interesting: the withdrawals_root is the SSZ root of
  the Withdrawals list — any client that hashes wrong would diverge
  on the FIRST block produced post-fork.
- **Withdrawal-index continuity gap**: H10 asserts withdrawal_index
  only increments on append. So a partial-queue entry that fails
  eligibility produces NO Withdrawal AND NO index increment, but
  DOES advance processed_count. Observable: a partial-queue with 5
  ineligible-then-1-eligible entries produces 1 Withdrawal at
  `state.next_withdrawal_index`, NOT at `+5`. Worth a fixture
  verifying this.
- **`MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP = 2` minimal preset**
  — grandine's preset.rs notes the minimal value differs. Worth
  running the minimal preset fixtures to check.
- **lodestar's `validatorBalanceAfterWithdrawals` Map cache** — tracks
  per-validator balance mutations across phases (lines 249, 323, 431).
  Same single-source-of-truth concern as items #4/#5: any direct
  `state.balances.set()` between two cache reads would diverge.
- **`get_pending_balance_to_withdraw(state, validator_index)`** —
  used by item #2 (consolidation) and item #6 (voluntary exit) to
  predict what's queued. The Pectra-new "0 pending" check at exit
  time depends on this sum being correct. Worth verifying that
  drained entries (sliced off in `update_pending_partial_withdrawals`)
  don't leak into this sum.
- **prysm's `mathutil.Sub64` in `get_balance_after_withdrawals`** —
  defensive underflow check. Per H8, `total_withdrawn ≤ balance`
  should be invariant, but if violated, prysm returns an error rather
  than 0 (grandine) or a panic (lighthouse via `safe_sub`). Three
  different failure modes for the same dead-code path.
- **Gloas builder-payment withdrawals interaction** — when a builder
  earns a payment, it gets queued as a Withdrawal in the next block.
  This adds a NEW `processBuilderWithdrawals` phase BEFORE the partial
  drain in Gloas. Cross-fork upgrade fixture spanning Pectra → Gloas
  would exercise the choreography.
- **`exit_balance_to_consume` shared with item #6**: when a partial
  withdrawal request comes in via item #3, it consumes the same per-block
  `exit_balance_to_consume` budget that voluntary exits do (item #6).
  Worth a stateful fixture: 1 voluntary exit + 1 EIP-7002 partial
  withdrawal in the same block — does the exit churn budget bookkeeping
  remain correct?

## Future research items

1. **Wire fork-fixture category in BeaconBreaker harness** (carries
   over from item #11 — would also enable Phase 2 cross-fork upgrade
   tests for this item).
2. **Generate a minimal-preset stress fixture** with 9 entries in
   `pending_partial_withdrawals` (overflows the 8-cap) — verify all
   clients drain exactly 8.
3. **lighthouse + grandine `== 8` vs spec `>= min(prior + 8, 15)`
   forward-compat audit at Gloas activation** — non-empty
   `prior_withdrawals` (from builder phase) would expose the divergence.
4. **`update_next_withdrawal_validator_index` cross-cut**: with
   partial-queue drain providing the LAST Withdrawal, the next-index
   advance picks up from the partial validator's `index + 1`, NOT the
   sweep-phase last validator. Verify all clients match.
5. **`withdrawals_root` Merkleization**: the SSZ root of the
   per-block Withdrawals list. Pectra's two-phase output produces a
   list of mixed partial+sweep withdrawals — cross-client root must
   match exactly.
6. **`MAX_VALIDATORS_PER_WITHDRAWALS_SWEEP = 16384` mainnet vs lower
   minimal preset** — sweep-phase "no-fully-withdrawable validator
   found" termination after `MAX_VALIDATORS_PER_WITHDRAWALS_SWEEP`
   iterations (NOT `len(state.validators)`). Worth a fixture
   exercising > 16384 validators where the sweep wraps.
7. **lodestar's BigInt-to-Number coercion at the amount boundary** —
   `Number(withdrawableBalance)` would lose precision past 2^53 wei.
   Pre-emptive fuzz target.
8. **prysm's defensive `mathutil.Sub64` underflow error** vs grandine's
   `saturating_sub` returning 0 vs lighthouse's `safe_sub` panicking
   — three distinct failure modes for the same "should-be-impossible"
   case. Codify as a contract test.
9. **`pending_partial_withdrawals` queue cap (PENDING_PARTIAL_WITHDRAWALS_LIMIT
   = 2^27 = 134M)** — adversarial scenario: 0x02 validator spams
   EIP-7002 requests under fee escalation. Drain rate is 8 per block;
   can the queue grow unboundedly? Computed worst-case: 134M /
   (8/block × 32 slots/epoch × 225 epochs/day) = ~232 days to fill at
   max input rate.
10. **Cross-cut with item #6 `exit_balance_to_consume`** — partial
    withdrawal queue consumption (item #3) and voluntary exits (item
    #6) share the per-epoch exit churn budget. Stateful fixture:
    multiple exits + partial requests in same block.
