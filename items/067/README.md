---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: [22, 23, 28, 57]
eips: [EIP-7732]
splits: []
# main_md_summary: TBD — drafting builder-withdrawal flow audit (0x03 credentials + `withdraw_balance_to_builder` + builder_pending_withdrawals lifecycle; Gloas-new mutation lane separate from 0x01/0x02 withdrawals)
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 67: Builder withdrawal flow — `withdraw_balance_to_builder` + `builder_pending_withdrawals` lifecycle

## Summary

> **DRAFT — hypotheses-pending.** Gloas introduces a separate withdrawal lane for 0x03-credential builders. `state.builder_pending_withdrawals` queues builder-balance withdrawals; `withdraw_balance_to_builder` (or sibling helper) executes them; `process_withdrawal_request` Gloas-modified dispatches based on credential prefix. Items #22 + #23 fixed the credential-predicate bugs; this audit covers the withdrawal mutation path itself, which has not been per-line cross-checked.

## Question

Pyspec relevant fns at `vendor/consensus-specs/specs/gloas/beacon-chain.md`:

- `withdraw_balance_to_builder(state, builder_index, amount)` — TBD line
- `get_pending_balance_to_withdraw_for_builder(state, builder_index)` — referenced by item #22 H10
- `process_withdrawal_request` Gloas modifications — TBD line
- `process_builder_pending_withdrawals` (epoch helper, similar to item #57) — TBD line
- `process_expected_withdrawals` Gloas modifications — TBD line

Open questions:

1. **Builder withdrawal queue shape** — `state.builder_pending_withdrawals: List[BuilderPendingWithdrawal, MAX_BUILDER_PENDING_WITHDRAWALS]`. Per-client identical?
2. **Withdrawal-request dispatch** — 0x03 credentials route to builder queue; 0x01/0x02 route to validator queue. Branch coverage.
3. **Builder balance decrement** — `state.builders[idx].balance -= amount` or via a balance-mutation helper?
4. **Builder full-exit** — when builder.balance drops to MIN_DEPOSIT_AMOUNT, does it self-exit?
5. **Per-slot withdrawal cap** — `MAX_BUILDER_WITHDRAWALS_PER_PAYLOAD` (TBD constant name); enforce in `process_expected_withdrawals`.
6. **Cross-cut with `process_proposer_slashing`** (item #65) — slashing should also affect pending withdrawals? (TBD verify spec.)

## Hypotheses

- **H1.** All six clients implement `withdraw_balance_to_builder` identically (balance decrement + pending-withdrawal queue append).
- **H2.** All six dispatch `process_withdrawal_request` by credential prefix: 0x01/0x02 → existing validator queue, 0x03 → builder queue.
- **H3.** All six enforce `MAX_BUILDER_PENDING_WITHDRAWALS` cap; reject deposits exceeding the cap.
- **H4.** All six self-exit builders at MIN_DEPOSIT_AMOUNT threshold (TBD spec verify).
- **H5.** All six update `state.builder_pending_withdrawals` at the same point in `process_block` ordering.
- **H6** *(forward-fragility)*. Slashing-during-pending-withdrawal: builder slashed while a withdrawal is queued. Spec semantics + per-client handling.

## Findings

> **TBD — drafting.** Each client subsection below is a stub awaiting source review.

### prysm

TBD — drafting.

### lighthouse

TBD — drafting.

### teku

TBD — drafting.

### nimbus

TBD — drafting. PR #8440 closure history relevant.

### lodestar

TBD — drafting.

### grandine

TBD — drafting.

## Cross-reference table

| Client | `withdraw_balance_to_builder` location | `process_withdrawal_request` dispatch | Builder-queue cap (H3) | Self-exit threshold (H4) |
|---|---|---|---|---|
| prysm | TBD | TBD | TBD | TBD |
| lighthouse | TBD | TBD | TBD | TBD |
| teku | TBD | TBD | TBD | TBD |
| nimbus | TBD | TBD | TBD | TBD |
| lodestar | TBD | TBD | TBD | TBD |
| grandine | TBD | TBD | TBD | TBD |

## Empirical tests

> **TBD — drafting.** EF Gloas operations fixtures: `vendor/consensus-specs/tests/.../gloas/operations/withdrawal_request/` (TBD path).

### Suggested fuzzing vectors

- **T1.1 (canonical builder withdrawal).** Builder with 0x03 credentials issues a withdrawal request; verify queue append + balance decrement.
- **T2.1 (cap edge).** Queue at MAX_BUILDER_PENDING_WITHDRAWALS - 1; submit one more; verify rejection.
- **T2.2 (cross-prefix isolation).** 0x01 validator + 0x03 builder both withdraw. Verify queues isolated.
- **T2.3 (self-exit).** Builder balance drops to MIN_DEPOSIT_AMOUNT. Verify per-client self-exit logic.
- **T2.4 (slashing-during-pending).** Slash a builder while it has a pending withdrawal. Verify per-client handling.

## Conclusion

> **TBD — drafting.** Source review pending.

## Cross-cuts

### With items #22 + #23 (closed)

Both nimbus alpha-drift bugs in builder-credential predicates. Fixed in PR #8440. This item is the next-layer audit on the withdrawal mutation path itself.

### With item #57 (`process_builder_pending_payments`)

Both are Gloas-new windowed-state machines. Symmetry: payments-in / withdrawals-out.

### With item #65 (proposer-slashing builder-payment voidance)

Slashing semantics for builders: does slashing void pending withdrawals too?

### With item #66 (deposit → builders activation)

Round-trip: deposit (item #66) ↔ withdrawal (this item) for 0x03 credentials.

## Adjacent untouched

1. **`process_builder_pending_withdrawals` epoch helper** — sibling to item #57's payments rotation; potential separate audit.
2. **`MAX_BUILDER_PENDING_WITHDRAWALS` constant cross-client verification**.
3. **Builder self-exit threshold logic** — analog to validator MIN_ACTIVATION_BALANCE.
