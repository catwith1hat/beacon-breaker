# BeaconBreaker — Work Log

## Goal

Cross-client audit of CL implementations at the **Electra/Pectra** fork
target on mainnet, finding consensus-relevant divergences and producing
fixtures suitable for upstream EF state-tests.

## Clients & Versions

| Client | Repo | Pinned commit | Tag/describe |
|---|---|---|---|
| prysm | github.com/prysmaticlabs/prysm | `d35d65625f` | v3.2.2-rc.1-2539-gd35d65625f |
| lighthouse | github.com/sigp/lighthouse | `176cce585c` | v8.1.3 (shallow) |
| teku | github.com/Consensys/teku | `c05af0eaa0` | 26.4.0-72-gc05af0eaa0 |
| nimbus | github.com/status-im/nimbus-eth2 | `102be79c06` | v26.3.1 |
| lodestar | github.com/ChainSafe/lodestar | `35940ffd61` | v1.42.0-69-g35940ffd61 |
| grandine | github.com/grandinetech/grandine | `eeb33a9228` | 2.0.4-18-geeb33a92 |
| consensus-specs | github.com/ethereum/consensus-specs | `5aa6eec83a` | v0.8.3-7631-g5aa6eec83 |
| consensus-spec-tests | github.com/ethereum/consensus-spec-tests | `bc5c1a7fb2` | v1.6.0-beta.0 (shallow) |
| beacon-APIs | github.com/ethereum/beacon-APIs | `31f7d04f86` | v2.4.1-172-g31f7d04 |

Pinned 2026-05-02. Run `git submodule status` to refresh; bump submodules in
their own commit, separate from any audit item, and re-run any affected
fixtures.

## Fork Target

**Electra/Pectra** on mainnet. Active EIPs in scope:
- EIP-6110 (in-protocol deposits)
- EIP-7002 (EL-triggered exits)
- EIP-7251 (MAX_EFFECTIVE_BALANCE = 2048 ETH, consolidations,
  `0x02` withdrawal-credentials prefix)
- EIP-7549 (move committee index outside attestation signing data)
- EIP-7685 (general execution-layer requests framework)
- EIP-7691 (blob throughput increase) — interacts via Engine API only
- EIP-7623 (calldata cost increase) — EL-side, no direct CL surface

## Areas Investigated

_(Numbered prioritization list. Each entry one line. Candidates above the
"Findings" cutover are forward-looking; candidates below have an
`itemN/README.md`.)_

1. **`process_effective_balance_updates` Pectra hysteresis with `MAX_EFFECTIVE_BALANCE_ELECTRA`** (Electra-active, per-epoch) → item #1 (no-divergence-pending-fuzzing; all six agree on `effective_balance_increase_changes_lookahead`, sha256 `aec719af…`).
2. **`process_consolidation_request` EIP-7251 switch + main path** (Electra-active, Track A entry) → item #2 (no-divergence-pending-fuzzing; 10/10 EF operations fixtures pass on prysm+lighthouse+lodestar+grandine; teku+nimbus SKIP per harness limit).
3. **`process_withdrawal_request` EIP-7002 full-exit + partial paths** (Electra-active, Track A) → item #3 (no-divergence-pending-fuzzing; 19/19 EF operations fixtures pass on prysm+lighthouse+lodestar+grandine; teku+nimbus SKIP).
4. **`process_pending_deposits` EIP-6110 per-epoch drain** (Electra-active, Track A drain side) → item #4 (no-divergence-pending-fuzzing; 43/43 EF epoch-processing fixtures pass on prysm+lighthouse+lodestar+grandine; teku+nimbus SKIP).
5. **`process_pending_consolidations` EIP-7251 drain side** (Electra-active, Track A drain side) → item #5 (no-divergence-pending-fuzzing; 13/13 EF epoch-processing fixtures pass on prysm+lighthouse+lodestar+grandine; teku+nimbus SKIP). Closes Track A's main drain side.

## Audit tracks (2026-05-02)

The 30 candidates below are grouped into 7 tracks. Each track shares a
mental model and a code-location pattern, so a session can stay loaded
on one track. Tracks are designed to be **independent**: two parallel
sessions on different tracks should not collide.

### Track A — Pectra request-processing (EIP-7251 / EIP-7002 / EIP-6110)
Items: **1, 2, 3, 12, 30**. Entry: **#1 (`process_consolidation_request`)**.
Why: freshest Pectra surface; three new operations introduced together;
highest divergence likelihood.

### Track B — Validator-state arithmetic (balance, churn, lifecycle)
Items: **4, 5, 7, 11, 29**. Entry: **#5 (`MAX_EFFECTIVE_BALANCE_ELECTRA`
hysteresis)**. Why: most likely class to surface a quiet 1-gwei C-tier
divergence — gwei math + the new 2048-ETH cap is a classic boundary
trap.

### Track C — Per-epoch processing & registry
Items: **8, 9, 10, 13**. Entry: **#13 (state upgrade function at
activation slot)**. Why: the upgrade function defines the post-Electra
state shape every other item assumes; needed-as-baseline for fixtures
in Tracks A and B.

### Track D — Fork choice
Items: **14, 15**. Entry: **#14 (`proposer_score_boost` at slot
boundary)**. Why: fully independent of all state-transition tracks;
ideal parallel-session candidate; timing predicates are notorious for
cross-client drift.

### Track E — SSZ & Merkleization
Items: **16, 17, 18, 19**. Entry: **#17 (list cap exact-N / N+1 / empty)**.
Why: high F-tier yield, low fixture cost. #17's empty-list root is one
hash to compare across six clients — minimal harness shakedown.

### Track F — BLS & cryptographic primitives
Items: **20, 21, 22**. Entry: **#22 (`fast_aggregate_verify` with zero
pubkeys)**. Why: library-family axis (BLST vs gnark vs custom) is
completely independent from state transition; classic A-tier surface.

### Track G — Engine API & sync committee (lower-priority pair)
Items: **6, 23, 24, 25, 26, 27, 28**. Entry: **#6 (EIP-7549 attestation
layout)**. Why: lowest-priority track; defer until A-C have produced
findings.

### Recommended starting item — #5 (Track B entry)

`MAX_EFFECTIVE_BALANCE_ELECTRA` hysteresis is C-tier reachable (every
block can trigger it via deposit/reward/penalty paths), the predicate
is razor-clear (one inequality at the hysteresis quantum, with two
caps: 32 ETH legacy `0x01`, 2048 ETH Pectra `0x02`), and the fixture
is the cheapest non-trivial state-test possible. Ideal harness
shakedown.

## Missing surfaces to add (next pass)

Five candidates not represented in the seed 30 — worth adding before
Phase 2:

- **#31. Pyspec-vs-clients oracle sweep.** Run `consensus-spec-tests/tests/mainnet/electra/random/` against all six clients + pyspec; flag any unanimous-clients-vs-pyspec divergence as a finding type.
- **#32. `process_execution_payload` requests-list parsing (EIP-7685).** Pectra's unified requests framework; cross-cuts Track A.
- **#33. Sync-committee period rotation _at_ the Electra activation slot.** §11 weird-corner; #23 covers selection but not this specific boundary.
- **#34. `process_historical_summaries_update` under Pectra state shape.** Touches state-roots accumulator; tiny divergence cost is huge.
- **#35. Blob/KZG commitment count caps (EIP-7691) propagation through Engine API.** Count predicate lives in the CL even though the data is EL-side.

## Speculative Unexplored Areas (2026-05-02)

Initial backlog drawn from §6 of `BEACONBREAKER.md`. Items further down the
list are lower-priority candidates for later iterations.

### Prioritization

1. **`process_consolidation_request` source/target validation** (Pectra,
   EIP-7251) — withdrawal-credentials prefix check, source-not-slashed,
   target-active predicates; balance transfer math.
2. **`process_withdrawal_request` fee escalation** (Pectra, EIP-7002) —
   exponential fee formula, queue caps, source validation.
3. **`process_pending_deposits` queue ordering** (Pectra, EIP-6110) —
   max-deposits-per-slot cap, prioritization vs activation eligibility.
4. **Churn limit calculation at validator-set step boundaries** (Pectra) —
   formula changed; likely divergence vector.
5. **`MAX_EFFECTIVE_BALANCE_ELECTRA` hysteresis** — credit/debit asymmetry
   at the 2048-ETH cap and at the 32-ETH boundary for legacy `0x01` creds.
6. **`process_attestation` with EIP-7549 layout change** — committee index
   moved out of signing data; signature domain implications.
7. **`process_proposer_slashing` `withdrawable_epoch` update** post-Pectra
   churn changes.
8. **`process_attester_slashing` intersection of attesting indices** —
   ordering and dedup semantics across clients.
9. **Per-epoch `process_registry_updates`** — activation queue ordering
   when several validators share `activation_eligibility_epoch`.
10. **`process_slashings`** proportional factor (3x) at the
    `MAX_SLASHABLE_BALANCE_INCREMENT` boundary.
11. **`process_effective_balance_updates`** hysteresis quanta at the
    Pectra `EFFECTIVE_BALANCE_INCREMENT` × hysteresis combination.
12. **`process_pending_consolidations`** — drainage rate, source/target
    coupling, interaction with exits.
13. **State upgrade function at the Pectra activation slot** — new field
    initialization defaults; pending-deposits seeding from EL.
14. **LMD-GHOST `proposer_score_boost`** at slot boundary; behavior under
    equivocation.
15. **`filter_block_tree`** viability under unrealized justification.
16. **SSZ container variable-offset**: overlapping ranges, non-monotonic
    offsets, offset past end.
17. **SSZ list cap**: exactly-N, N+1 rejection, empty-list root.
18. **Bitlist last-bit-set sentinel** — off-by-one on the trailing bit.
19. **Merkleization padding** for non-power-of-2 lists; `mix_in_length`
    correctness across clients.
20. **BLS subgroup membership** for G1 (pubkey) and G2 (signature).
21. **BLS identity / point-at-infinity** handling in pubkey and signature.
22. **`fast_aggregate_verify` with zero pubkeys** — must reject.
23. **Sync committee selection at fork-boundary period rotation**.
24. **Sync committee message verification** — slot-N attests slot-(N-1)
    head; signature aggregation order.
25. **`engine_newPayloadV*` payload-vs-header consistency checks**.
26. **`engine_forkchoiceUpdatedV*` head/safe/finalized validation**.
27. **EL `INVALID` vs `INVALID_BLOCK_HASH` vs `SYNCING`** interpretation.
28. **`requestsHash` propagation** through the Engine API at Pectra.
29. **Validator credential transitions `0x00` → `0x01` → `0x02`** —
    one-way; clients must reject regressions.
30. **Cross-cut: EIP-7251 × EIP-7002** — consolidation pending + EL exit
    in the same block; precedence?

These are candidates for items #1 onward, not findings.

## Findings (per-item bodies)

### 1. `process_effective_balance_updates` Pectra hysteresis with `MAX_EFFECTIVE_BALANCE_ELECTRA`

**Status:** no-divergence-pending-fuzzing — audited 2026-05-02. Track B entry.

Source survey across all six clients confirms aligned implementations of the Pectra-modified `process_effective_balance_updates`, the `get_max_effective_balance` cap selector (32 ETH for `0x01` legacy, 2048 ETH for `0x02` compounding), and the `0x02` compounding-credential predicate. Notable per-client idioms: Lodestar adds an `effectiveBalance < effectiveBalanceLimit` short-circuit in the upward branch (output-equivalent to pyspec's `min` clamp); Nimbus is the only client whose `has_compounding_withdrawal_credential` is fork-gated to also accept `0x03` (builder) credentials at Gloas+. Teku has a redundant outer `.min(...)` in its clamp expression, dead code today. Lighthouse and Grandine defend against zero-length credentials slices; Prysm and Lodestar do not (academic — SSZ schema fixes the length at 32 bytes).

All six pass `effective_balance_increase_changes_lookahead` (sha256 `aec719af6530b4e79d385e16021c40be5e04ea93c8411e01d0ea12b4786c9de2`). Grandine additionally passes the two dedicated Electra `effective_balance_updates` epoch-processing fixtures (`effective_balance_hysteresis` and `_with_compounding_credentials`); the other five clients run those in their internal CI.

**Adjacent untouched Electra-active**: `process_pending_deposits` ordering vs eb-updates (WORKLOG #3); Teku redundant-clamp sweep; Nimbus Gloas `0x03` divergence (pre-emptive, future fork); Lighthouse `safe_*` overflow-checked arithmetic in vs unchecked clients; zero-length-credentials defensive variants (F-tier today).

See [item1/README.md](item1/README.md).

### 2. `process_consolidation_request` EIP-7251 switch + main path

**Status:** no-divergence-pending-fuzzing — audited 2026-05-03. Track A entry.

Source survey across all six clients confirms aligned implementations of the switch-to-compounding fast path and the cross-validator main path. Notable per-client idioms (all observable-equivalent at the spec level): nimbus and lodestar hoist pubkey-existence checks before the switch fast path (pyspec does them inside `is_valid_switch_to_compounding_request`); prysm adds defensive `len(creds)!=32` and `len(addr)!=20` checks; lighthouse uses `safe_*` math everywhere plus a `match` on state variant that returns `Err(IncorrectStateVariant)` for pre-Electra; teku uses `.minusMinZero()` saturating subtraction; lodestar mixes `number` and `BigInt` for churn arithmetic; grandine uses `Result<()>` propagation throughout.

All 10 EF `operations/consolidation_request` fixtures pass uniformly on prysm + lighthouse + lodestar + grandine. teku and nimbus SKIP per harness limitation (no per-operation CLI hook); both pass these in their internal CI.

**Coverage gap surfaced**: 9 of 10 EF fixtures exercise the switch-to-compounding fast path; only `incorrect_not_enough_consolidation_churn_available` reaches the main path, and it terminates early at the churn short-circuit. **The end-to-end main-path success scenario (source != target, both compounding, full success ending in `PendingConsolidation` append) is not directly fixture-tested at this layer.**

**Adjacent untouched Electra-active**: `queue_excess_active_balance` (called by switch path); `get_pending_balance_to_withdraw` (cross-cuts withdrawal_request); `compute_activation_exit_epoch` (cross-cuts voluntary_exit); pubkey-lookup data-structure consistency under churn (6 different DSes); `PendingConsolidation` queue append ordering (cross-cuts WORKLOG #12); coarse-grained lighthouse harness verdict (per-helper rather than per-fixture); EF coverage gap (T1.1 fixture missing).

See [item2/README.md](item2/README.md).

### 3. `process_withdrawal_request` EIP-7002 full-exit + partial paths

**Status:** no-divergence-pending-fuzzing — audited 2026-05-03. Track A.

Source survey across all six clients confirms aligned implementations of the dual-mode (full-exit vs partial) entrypoint. Two divergence-prone bits both correctly enforced everywhere: (a) **partial withdrawals strictly require `has_compounding_withdrawal_credential` (0x02 only)** — a 0x01 validator can only do full exits via this path; (b) **partial-withdrawal balance flows through `compute_exit_epoch_and_update_churn` (which uses `get_activation_exit_churn_limit`), NOT `compute_consolidation_epoch_and_update_churn`** (smaller). All 19 EF `operations/withdrawal_request` fixtures pass uniformly on prysm+lighthouse+lodestar+grandine. teku+nimbus SKIP. Notable per-client styles: lodestar bundles eligibility checks 4-7 into a `isValidatorEligibleForWithdrawOrExit` helper shared with voluntary exit (single source of truth, but a regression there affects both paths); lodestar uses `>=` for the queue-full check where others use `==` (defensive); nimbus has a Gloas-ready branch in `get_pending_balance_to_withdraw` for builder withdrawals (dead at Pectra).

This item shares 5 predicates with item #2 (consolidation_request); both passing strengthens evidence for the shared core (pubkey/creds/active/exiting/seasoned). Both items use `compute_exit_epoch_and_update_churn` infrastructure but with different churn-limit selectors.

**Adjacent untouched Electra-active**: `compute_exit_epoch_and_update_churn` standalone audit (used by 4+ paths); `initiate_validator_exit` standalone audit (cross-cuts voluntary_exit); `get_pending_balance_to_withdraw` linear-scan complexity (F-tier OOM under adversarial queue growth); lodestar shared helper as single regression vector for two ops; canonical "lost partial" composed scenario (switch + partial in one block — fixture worth generating); `pending_partial_withdrawals` queue append ordering (cross-cuts drain side); nimbus Gloas-aware predicates (pre-emptive); 0x02 validator with effective_balance below MIN_ACTIVATION_BALANCE; FULL_EXIT_REQUEST_AMOUNT==0 spec quirk; EIP-7685 request ordering at the dispatcher.

See [item3/README.md](item3/README.md).

### 4. `process_pending_deposits` EIP-6110 per-epoch drain

**Status:** no-divergence-pending-fuzzing — audited 2026-05-03. Track A drain side; consumes the queue produced by `process_deposit_request` and by item #2's `queue_excess_active_balance` (switch-to-compounding excess deposits).

Source survey across all six clients confirms aligned implementations of the four-break-condition outer loop, the three-way per-deposit branch (withdrawn → apply-no-churn / exited → postpone-to-back / active → check-churn-then-apply), the queue mutation `pending_deposits[next_deposit_index:] + postponed`, the conditional `deposit_balance_to_consume` accumulator (`available − processed` if churn hit; `0` otherwise), and most importantly the **`GENESIS_FORK_VERSION` deposit-signature domain** (a common bug vector — using current fork version would silently reject every valid pre-Pectra-signed deposit). All 43 EF `pending_deposits` fixtures pass uniformly on prysm+lighthouse+lodestar+grandine. teku+nimbus SKIP per harness limit.

The richness of this fixture set (43 tests including every churn boundary, every signature edge case, every postpone path, and the Eth1-bridge-transition cases) is the strongest evidence yet for cross-client agreement on this surface.

**Notable per-client styles**: lighthouse defers actual balance/validator mutations to a `PendingDepositsContext` (batched application later in single-pass) — same observable post-state but a different mutation choreography; lighthouse uses the **legacy test-fn name `epoch_processing_pending_balance_deposits`** (from before `PendingBalanceDeposit` was renamed to `PendingDeposit`) — runner mapping added; lodestar processes the queue in chunks of 100 for SSZ batched reads, AND has a Gloas-fork-conditional branch using `getActivationChurnLimit` (vs `getActivationExitChurnLimit` pre-Gloas) — pre-emptive divergence vector at the next fork target; grandine clones the queue for borrow safety.

**Cross-cut with item #2**: the switch-to-compounding fast path appends `PendingDeposit{slot=GENESIS_SLOT, signature=G2_POINT_AT_INFINITY}` placeholders. These are top-ups (validator already exists) so signature is never validated. Worth generating a dedicated T1.1 fixture exercising this placeholder.

**Adjacent untouched Electra-active**: `process_deposit_request` (producer side, trivial pyspec but `deposit_requests_start_index` init quirk); `add_validator_to_registry` standalone (Pectra-modified, two callers); `is_valid_deposit_signature` BLS library-family audit (Track F alignment); lodestar Gloas-fork branch as pre-emptive divergence; lighthouse `PendingDepositsContext` batched-mutation choreography; placeholder-signature top-up fixture (T1.1); `MAX_PENDING_DEPOSITS_PER_EPOCH=16` queue growth analysis under fork-driven mass entry; `deposit_balance_to_consume` shared churn pool with `process_voluntary_exit`; postpone-list ordering preservation; SSZ list cap (`PENDING_DEPOSITS_LIMIT=2^27`) and what happens when full.

See [item4/README.md](item4/README.md).

### 5. `process_pending_consolidations` EIP-7251 drain side

**Status:** no-divergence-pending-fuzzing — audited 2026-05-03. Track A drain side; consumes the queue produced by item #2's main path. Closes Track A's main drain coverage.

Source survey across all six clients confirms aligned implementations of the slashed-first / withdrawable-second predicate ordering, the `min(balance, effective_balance)` transfer formula, the cursor advance on slashed (skip) and not on break, the symmetric `decrease_balance + increase_balance` pair, and the slice-from-cursor queue mutation. All 13 EF `pending_consolidations` fixtures pass uniformly on prysm+lighthouse+lodestar+grandine. teku+nimbus SKIP per harness limit.

The 13-fixture suite covers slashed-source skip, not-yet-withdrawable break, both source credential types (eth1 0x01 / compounding 0x02), both balance-vs-effective-balance orderings (less / greater than max), the cross-cut with pending deposits, and an "all cases together" rolled scenario. All-pass adds strong evidence to items #1 (`get_max_effective_balance` feeds `source.effective_balance` here), #2 (this drain consumes #2's queue), and #4 (`pending_consolidation_with_pending_deposit` exercises both drain functions in one epoch).

**Notable per-client styles**: lighthouse integrates this into its single-pass epoch processor with an immediate effective-balance-update re-pass for affected validators (`perform_effective_balance_updates` flag) — same observable post-state but different mutation choreography; lighthouse uses `pop_front(N)` on a milhouse List instead of slice-and-replace; lodestar uses chunked iteration (100 at a time) AND dual-writes balances to both the SSZ tree AND `epochCtx.balances` cache for downstream consistency; lodestar is the only client with the `cachedBalances` array sync pattern; grandine clones the queue + `PersistentList::try_from_iter`; nimbus uses `asSeq[i..^1]` slice + HashList re-init; teku uses `subList`; teku retains the legacy variable name `nextPendingBalanceConsolidation` (parallel to lighthouse's pre-rename `pending_balance_deposits` test fn from item #4).

**Cross-cut surfaced**: there is **no churn limit** on consolidations drainage (unlike `process_pending_deposits` from item #4) — drainage is pre-budgeted via `compute_consolidation_epoch_and_update_churn` at request time (item #2). Up to `PENDING_CONSOLIDATIONS_LIMIT = 64` entries could drain in one epoch in principle. Also, source's `effective_balance` may have drifted between request and drain (via item #1's eb-updates running in earlier epochs) — the `min(balance, effective_balance)` formula handles this drift implicitly.

**Adjacent untouched Electra-active**: `process_epoch` per-fork ordering of helpers (deposits → consolidations → eb-updates — order matters); lighthouse `perform_effective_balance_updates` flag local-vs-global re-pass equivalence; self-consolidation `source_index == target_index` queue entry (defensive — not reachable from request validation today); `source.balance` over-budget residual cleanup via `process_withdrawals`; no per-epoch consolidation drainage limit (denial-of-throughput analysis under high source-slashing rates); lodestar `cachedBalances` dual-write coherence (any direct `state.balances.set` between two cache reads would diverge); teku legacy `nextPendingBalanceConsolidation` naming sweep; `PendingConsolidation` SSZ struct has no amount field — derived at drain time from `source.effective_balance`, susceptible to drift.

See [item5/README.md](item5/README.md).
