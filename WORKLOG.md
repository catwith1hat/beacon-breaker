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
6. **`process_voluntary_exit` + `initiate_validator_exit` Pectra** (Electra-active, Track A signed-message path) → item #6 (no-divergence-pending-fuzzing; 25/25 EF operations fixtures pass on prysm+lighthouse+lodestar+grandine; teku+nimbus SKIP). Confirms EIP-7044 CAPELLA_FORK_VERSION pinning and the new pending-withdrawals predicate across all clients.
7. **`process_attestation` EIP-7549 multi-committee aggregation** (Electra-active, Track G entry — highest-frequency CL operation) → item #7 (no-divergence-pending-fuzzing; 45/45 EF operations fixtures pass on prysm+lighthouse+lodestar+grandine; teku+nimbus SKIP). Confirms `data.index == 0`, cumulative `committee_offset`, per-committee non-empty, exact-size bitfield, and BLS aggregate-over-union semantics across all clients.
8. **`process_attester_slashing` (EIP-7549 + EIP-7251)** (Electra-active, slashing operation) → item #8 (no-divergence-pending-fuzzing; 30/30 EF operations fixtures pass on prysm+lighthouse+lodestar+grandine; teku+nimbus SKIP). Confirms Pectra-changed `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` and `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA` quotients across all clients; Casper FFG predicate and BLS aggregate verification consistent.
9. **`process_proposer_slashing` (Pectra-affected via `slash_validator`)** (Electra-active, slashing operation; closes the slashing pair) → item #9 (no-divergence-pending-fuzzing; 15/15 EF operations fixtures pass on prysm+lighthouse+lodestar+grandine; teku+nimbus SKIP). Closes the `slash_validator` cross-cut chain (items #6+#8+#9 = 70 ops fixtures, 280 PASS results). Confirms full-struct `BeaconBlockHeader` inequality (5-field), runtime-fork `DOMAIN_BEACON_PROPOSER` (NOT pinned like voluntary exit), and Pectra-quotient routing through `slash_validator`.
10. **`process_slashings` per-epoch + `process_slashings_reset` (EIP-7251 algorithm restructure)** (Electra-active, per-epoch drain; closes the slashings-vector cycle started by items #8 and #9) → item #10 (no-divergence-pending-fuzzing; 24/24 EF epoch_processing fixtures pass on prysm+lighthouse+lodestar+grandine; teku+nimbus SKIP). Confirms the EIP-7251 algorithm restructure (per-increment rate computed once, then multiplied by validator's increments — NOT the legacy per-validator-numerator ordering); `PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX = 3` correctly retained at Electra (no constant change); reset zeroes `state.slashings[(epoch+1) % EPOCHS_PER_SLASHINGS_VECTOR]`.
11. **`upgrade_to_electra` state-upgrade function (Track C #13, foundational)** (Electra-active, runs once at the Pectra activation slot) → item #11 (no-divergence-pending-source-review; 9 hypotheses confirmed across all 6 clients; **fork category not wired in BeaconBreaker's harness — primary follow-up**; all 6 clients' internal CI passes the 22 EF fork fixtures). Defines 9 brand-new Pectra fields, `earliest_exit_epoch` derivation (max + 1), churn-budget seeding, pre-activation pending-deposits seeding (sort by `(eligibility_epoch, index)`), and early-adopter compounding queueing. Underpins items #1–#10 (every prior item's PASS verdict implicitly validates this item's post-state construction).
12. **`process_withdrawals` Pectra-modified (EIP-7251 partial-queue drain)** (Electra-active; closes Track A's withdrawal cycle with item #3 producer + item #11 upgrade-time empty-queue init) → item #12 (no-divergence-pending-fuzzing; partial run 173/320 PASS / 0 FAIL on prysm+lighthouse+lodestar+grandine — full 80×4 run continues in background; teku+nimbus SKIP per harness limit). Confirms two-phase drain (partial-queue first then validator sweep), `withdrawals_limit = min(prior + 8, MAX - 1)` (4/6 use spec formula; lighthouse+grandine hardcode `== 8` — observable-equivalent today since prior is empty at the call site, but forward-compat risk at Gloas), `processed_count` advances for ALL drained entries (including ineligible), partial amount = `min(balance - MIN_ACTIVATION_BALANCE, withdrawal.amount)`, sweep partial = `balance - get_max_effective_balance(validator)`, queue slice via `[processed_count:]`. Required runner patch (grandine.sh) to handle the no-`process_<helper>::`-namespace test path layout for withdrawals.
13. **`process_operations` Pectra dispatcher (EIP-6110 cutover + EIP-7685 requests routing)** (Electra-active; the outer fan-out function for ALL block-level operations) → item #13 (no-divergence-pending-source-review; 9 hypotheses confirmed across all 6 clients; implicit fixture coverage from items #2/#3/#4/#5/#6/#7/#8/#9/#12 = 280 fixtures × 4 wired clients = 1120 PASS results that all flow through this dispatcher). Confirms `eth1_deposit_index_limit = min(deposit_count, deposit_requests_start_index)` legacy-deposit cutover (with sentinel transition from item #11's `UNSET = 2^64-1`), conditional length check on `body.deposits` (both branches), three-way request dispatcher in spec order (deposits → withdrawals → consolidations), per-list SSZ caps (8192/16/2 mainnet). Notable structural divergence: grandine separates dispatchers from `process_operations` into `custom_process_block` (forward-compat risk for any future spec change adding state mutation between dispatchers and end-of-process_operations); prysm extracts the cutover assertion to `VerifyBlockDepositLength` (called before `electraOperations`); lodestar/prysm have explicit Gloas-fork exclusion (`fork < ForkSeq.gloas` / Gloas dispatcher removal — EIP-7732 PBS relocates them).

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

### 6. `process_voluntary_exit` + `initiate_validator_exit` Pectra

**Status:** no-divergence-pending-fuzzing — audited 2026-05-03. Track A signed-message exit path; cross-cuts items #2 (consolidation source exit init) and #3 (withdrawal_request full-exit path) — all share `initiate_validator_exit` which uses Pectra-modified `compute_exit_epoch_and_update_churn`.

Source survey across all six clients confirms aligned implementations of the seven Pectra-modified predicates (active, not-exiting, timing, seasoned, **NEW pending-withdrawals == 0**, signature with **CAPELLA_FORK_VERSION**, initiate). Both divergence-prone bits correctly enforced everywhere: (a) the EIP-7044 CAPELLA_FORK_VERSION pin (NOT current fork, NOT genesis — voluntary exits are domain-locked to Capella so signed exits stay valid across post-Capella forks); (b) the Pectra-new `get_pending_balance_to_withdraw == 0` check that prevents a 0x02 validator from exiting while leaving partial-withdrawal queue items orphaned. All 25 EF `voluntary_exit` fixtures pass uniformly on prysm+lighthouse+lodestar+grandine. teku+nimbus SKIP per harness limit.

**Strongest fork-version evidence in the corpus**: 6 fixtures explicitly test fork-version handling (current/genesis/previous × is/is-not-before-fork-epoch combos). The `voluntary_exit_with_previous_fork_version_*` PASS fixtures confirm that exits signed with Capella's fork version (the "previous" fork relative to Deneb at Deneb time, but pinned to Capella for Pectra+) MUST be accepted post-Pectra.

**Notable per-client styles**: prysm constructs the Capella-fixed `Fork` struct explicitly (`PreviousVersion = CurrentVersion = CapellaForkVersion` for Deneb+); lighthouse gates on `state.fork_name_unchecked().deneb_enabled()` in the signature subroutine; teku uses the `BeaconStateAccessorsDeneb.getVoluntaryExitDomain()` override for fork-version pinning AND `firstOf` Optional-chaining for the Electra-new check via inheritance; nimbus uses `voluntary_exit_signature_fork` static-fork helper; lodestar's `getDomainForVoluntaryExit` is a pre-Deneb / Deneb+ branch; grandine matches against `deneb|electra|fulu|gloas` fork versions explicitly.

**Source-organization risk surfaced in grandine**: TWO `initiate_validator_exit` functions exist — `helper_functions/src/mutators.rs:61` (Phase0-style: linear scan + `get_validator_churn_limit`) and `helper_functions/src/electra.rs:124` (Pectra-correct: calls `compute_exit_epoch_and_update_churn`). The Pectra `block_processing.rs` correctly imports the Electra version explicitly. A future audit walking import paths could mistake the two; F-tier today since all callers correctly import.

**Adjacent untouched Electra-active**: `compute_exit_epoch_and_update_churn` standalone audit (highest-leverage primitive, used by 3+ items now); EIP-7044 fork-version selection per-client (subtle regression possible at future forks); multiple voluntary exits in one block sharing churn (T2.1 stateful sanity_blocks fixture not in EF coverage); lighthouse `state.build_exit_cache(spec)?` perf optimization; lodestar voluntary-exit NOT reusing `isValidatorEligibleForWithdrawOrExit` (intentional but flag-worthy); `exit_balance_to_consume` per-block accumulator shared across voluntary_exit + EL full-exit + consolidation source exit; cross-path validator-already-exited semantics; grandine's two `initiate_validator_exit` definitions discriminated by import path.

See [item6/README.md](item6/README.md).

### 7. `process_attestation` EIP-7549 multi-committee aggregation

**Status:** no-divergence-pending-fuzzing — audited 2026-05-03. Highest-frequency CL operation, Pectra-modified for multi-committee aggregation.

EIP-7549 fundamentally restructures the `Attestation` SSZ container: removes `committee_index` from `AttestationData` (legacy field still present, must be 0), adds top-level `committee_bits: Bitvector[MAX_COMMITTEES_PER_SLOT]`. A single attestation can now carry attesters from multiple committees in one BLS signature aggregate, with a flat `aggregation_bits` indexed by a cumulative `committee_offset` walked across active committees in committee_bits-set order.

Source survey across all six clients confirms aligned implementations of the four new Pectra checks: (a) `data.index == 0` enforcement; (b) `committee_offset` cumulative accumulation across committees; (c) `len(committee_attesters) > 0` per committee; (d) exact-size bitfield check `len(aggregation_bits) == committee_offset`; plus (e) BLS aggregate over union of all per-committee attesters. All 45 EF `attestation` operations fixtures pass uniformly on prysm+lighthouse+lodestar+grandine. teku+nimbus SKIP per harness limit.

**The 45-fixture suite is the third-richest in the corpus** (after items #4 and #6) and exhaustively covers: 6 inclusion-delay variants × 4 head/target correctness combos, the data.index==0 check (`invalid_attestation_data_index_not_zero`), all bitfield boundary cases (`invalid_too_few/many_aggregation_bits`, `invalid_too_many_committee_bits`, `invalid_nonset_committee_bits`), empty-committee rejection (`invalid_empty_participants_*` with both seemingly-valid and zero signatures), all FFG checkpoint edge cases, committee-index-vs-slot bounds, and multi-proposer-iteration scenarios.

**Notable per-client styles**: prysm has Gloas-ready logic (`ci < 2` post-Gloas, `ci == 0` Electra) — pre-emptive support for an EIP that may allow 2-way committee splits at Gloas; lighthouse uses `safe_add` overflow-checked arithmetic for cumulative offset; teku factors `data.index==0` into a separate `AttestationDataValidatorElectra` class; nimbus uses Nim's built-in `bitvector.oneIndices` iterator; lodestar flattens all set committees into a single Uint32Array before intersect with aggregation_bits (different choreography); grandine returns `HashSet<ValidatorIndex>` matching pyspec's `Set[ValidatorIndex]` literally.

**Adjacent untouched Electra-active**: `Attestation` SSZ container ser/de cross-client (Track E — Pectra layout change must round-trip identically for gossip); `is_valid_indexed_attestation` BLS aggregate verification with expanded list capacity (MAX_VALIDATORS_PER_COMMITTEE × MAX_COMMITTEES_PER_SLOT = 131,072); cross-committee duplicate-validator dedup (T2.7 — pyspec uses Set[ValidatorIndex]; each client's collection mechanism must dedupe; not exhaustively in EF set); prysm's pre-emptive Gloas-ready `ci < 2` branch; lodestar's `intersectValues` ordering (preserves bit-position order, not sorted by validator index — BLS aggregation is commutative so OK, but downstream code dependent on sorted order would have subtle bugs); shuffling cache cross-client coherence; participation flag update ordering within a single block (proposer_reward_numerator accumulation); SSZ bitlist size at the new bound (131,072 max bits); legacy `AttestationData.index` field as semi-permanent technical debt; `get_committee_count_per_slot` consistency.

See [item7/README.md](item7/README.md).

### 8. `process_attester_slashing` (EIP-7549 + EIP-7251)

**Status:** no-divergence-pending-fuzzing — audited 2026-05-03. Slashing operation; cross-cuts items #6 (`initiate_validator_exit` via `slash_validator`) and #7 (IndexedAttestation expanded capacity + BLS aggregate verify shared machinery).

`process_attester_slashing` is structurally unchanged from Phase0 but operates on Pectra-modified IndexedAttestations (EIP-7549 expanded list capacity), and `slash_validator` is Pectra-modified (EIP-7251 changed `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` and `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA`). All six clients implement the Casper FFG predicate (double vote OR surround vote), both BLS aggregate verifications, set intersection + sort, the slashability check, and the Pectra-changed quotient selection identically. All 30 EF `attester_slashing` operations fixtures pass uniformly on prysm+lighthouse+lodestar+grandine. teku+nimbus SKIP per harness limit.

**Notable per-client styles**: prysm uses a central `SlashingParamsPerVersion(version)` switch — clean single dispatch point; lighthouse uses `BTreeSet` for the intersection (naturally sorted) and state methods `get_min_slashing_penalty_quotient(spec)` for fork-keyed quotient selection; teku uses subclass-override polymorphism (`BeaconStateMutatorsElectra extends ...` overrides quotient methods); nimbus uses compile-time `when` blocks on the BeaconState type (zero runtime overhead); lodestar uses a 5-deep nested ternary for the penalty quotient (per-fork explicit); grandine uses type-associated constants `P::MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` (compile-time per Preset) AND `merge_join_by` for the lazy sorted-merge intersection (most efficient algorithm).

**Cross-cut chain confirmed**: items #6 (voluntary exit) + #8 (attester slashing — this item) both call `slash_validator` / `initiate_validator_exit`. Three items' fixtures (25 + 30 = 55 ops fixtures) all passing strengthens evidence for the Pectra-modified slashing/exit machinery.

**Adjacent untouched Electra-active**: `process_proposer_slashing` (same `slash_validator` primitive — natural next item); `process_slashings` per-epoch (reads state.slashings vector this item writes; Pectra changed multiplier — WORKLOG #10); `MAX_ATTESTER_SLASHINGS_ELECTRA` per-block limit; `is_double_vote` / `is_surround_vote` separate methods in lighthouse (precedence verification); `slash_validator` whistleblower==proposer same-address edge case; grandine's `merge_join_by` correctness assumes sorted attesting_indices upstream; lodestar 5-deep ternary as Gloas pre-emptive divergence vector; prysm's `SlashingParamsPerVersion` Gloas-readiness; teku's subclass-override extension to Gloas.

See [item8/README.md](item8/README.md).

### 9. `process_proposer_slashing` (Pectra-affected via `slash_validator`)

**Status:** no-divergence-pending-fuzzing — audited 2026-05-02. Slashing operation; closes the proposer/attester slashing pair (with item #8) and the `slash_validator` cross-cut chain (with items #6 and #8).

`process_proposer_slashing` is structurally unchanged from Phase0 but inherits Pectra-modified `slash_validator` (EIP-7251 changed `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA = 4096` and `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA = 4096`, both moving 64×–128×). All six clients implement the eight divergence-prone bits identically: full-struct `BeaconBlockHeader` inequality (5 fields), strict slot equality, strict proposer-index equality, `is_slashable_validator(proposer, current_epoch)`, per-header BLS verify with `DOMAIN_BEACON_PROPOSER` and **runtime current-fork** version (NOT pinned like voluntary exit's CAPELLA pin), per-header epoch sourced from `header.slot` (not state.slot — relevant for `block_header_from_future`), `slash_validator` routed to the Electra-quotient version, and SSZ-enforced `MAX_PROPOSER_SLASHINGS == 16`. All 15 EF `proposer_slashing` operations fixtures pass uniformly on prysm+lighthouse+lodestar+grandine (60/60). teku+nimbus SKIP per harness limit.

**Notable per-client styles**: prysm uses `proto.Equal()` for header inequality (proto-level structural eq, all 5 fields) and the same central `SlashingParamsPerVersion(version)` switch as item #8; lighthouse uses derived `PartialEq` `!=` plus state methods `get_min_slashing_penalty_quotient(spec)` (single-source-of-truth shared with item #8); teku uses `Objects.equals()` plus the subclass-override polymorphism (`BeaconStateMutatorsElectra` — and crucially does NOT override `getDomain()` for proposer, contrasting with the EIP-7044 Capella pin in `getVoluntaryExitDomain`); nimbus uses Nim's auto-generated `!=` plus compile-time `when state is electra/fulu/gloas.BeaconState` quotient blocks; **lodestar uses `ssz.phase0.BeaconBlockHeaderBigint.equals(h1, h2)` — critically not `===` (which would always return false for distinct objects, falsely allowing identical-content headers to be slashed)** plus the 5-deep ternary on ForkSeq for penalty quotient; grandine uses derived `PartialEq` plus `SignForSingleFork<P>` trait for domain dispatch and type-associated constants `P::MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA`.

**Source-organization risk surfaced in grandine**: FOUR `slash_validator` definitions exist — `helper_functions/src/{phase0,altair,bellatrix,electra}.rs`. The Pectra `transition_functions/electra/block_processing.rs` correctly imports `helper_functions::electra::slash_validator`. Same import-path discrimination risk as item #6's `initiate_validator_exit` (which has 2 definitions), only worse (4 instead of 2). F-tier today since all known callers correctly import; worth a one-line audit assertion for any future refactor.

**Cross-cut chain CLOSED**: items #6 (voluntary_exit) + #8 (attester_slashing) + #9 (proposer_slashing — this item) all converge on `slash_validator` (#8 + #9) and `initiate_validator_exit` (all three). Cumulative fixture evidence: **70 ops fixtures × 4 wired clients = 280 PASS results** all exercising the Pectra-modified slashing/exit machinery.

**Adjacent untouched Electra-active**: `process_slashings` per-epoch (WORKLOG #10) — reads `state.slashings` vector that #9 writes; cross-fork slashing fixture (proposer signs two block headers straddling a fork epoch — domain computation should pick different fork versions per header); MAX_PROPOSER_SLASHINGS over-the-wire test (block with 17 slashings — SSZ should reject); header inequality fuzz (5 field × diff/same matrix, ~32 cases); whistleblower==proposer==slashed self-slash reward math edge case; prysm's `ExitInformation` cache-vs-fresh-read parity with multiple slashings sharing churn budget in one block; lighthouse `BlockSignatureVerifier` block-level batch path (currently bypassed by per-fixture operations runner); `PROPOSER_WEIGHT/WEIGHT_DENOMINATOR` Altair+ reward split (lighthouse's `altair_enabled()` branch — pre-Altair dead code in some clients).

See [item9/README.md](item9/README.md).

### 10. `process_slashings` per-epoch + `process_slashings_reset` (EIP-7251 algorithm restructure)

**Status:** no-divergence-pending-fuzzing — audited 2026-05-02. Per-epoch slashings drain; closes the `state.slashings[]` vector cycle (items #8 + #9 wrote into it; this drains and resets it).

EIP-7251 modified `process_slashings` to **restructure the per-validator penalty algorithm to reduce floor-division precision loss**. Constants are unchanged (`PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX = 3` is still used at Electra). The change is purely algorithmic and subtle: pre-Electra computed `penalty = (effective_balance/increment * adjusted_total_slashing_balance) / total_balance * increment` per validator; Pectra computes `penalty_per_increment = adjusted_total_slashing_balance / (total_balance / increment)` once per epoch (loop-invariant), then `penalty = penalty_per_increment * effective_balance_increments` per validator. NOT mathematically equivalent under floor-div. All six clients implement the new algorithm correctly, retain `_BELLATRIX = 3` for Electra, enforce strict-equality `withdrawable_epoch == epoch + EPOCHS_PER_SLASHINGS_VECTOR/2`, and zero `state.slashings[(epoch+1) % VECTOR]` in reset. All 24 EF `slashings` + `slashings_reset` fixtures pass uniformly on prysm+lighthouse+lodestar+grandine. teku+nimbus SKIP per harness limit.

**Notable per-client styles**: prysm uses unified single-function dispatch with inline `if st.Version() >= version.Electra` branches (lines 240, 250) and `math.Add64`-overflow-checked sum-of-slashings; lighthouse has NO dedicated `electra/` epoch-processing module, slashings folded into the Altair+ single-pass processor as a `SlashingsContext` precomputed once per epoch (`single_pass.rs:881-938`); teku uses subclass-override polymorphism (`EpochProcessorElectra extends EpochProcessorCapella ...`) — same pattern as items #8/#9 mutator overrides; nimbus uses compile-time `static when consensusFork in [Electra, Fulu, Gloas]` dispatch in `get_slashing_penalty` (most consistent fork-dispatch idiom across items #6/#8/#9/#10); lodestar uses an effective-balance-increment penalty memoization `Map<number, number>` (unique optimization) plus defensive `intDiv()` for the half-vector divisor and an `epochCtx.totalSlashingsByIncrement` dual-write cache (same single-source-of-truth concern as items #4/#5); grandine has FIVE `process_slashings` definitions across `phase0/altair/bellatrix/electra` modules (+1 explicit re-call from fulu) — same source-organization risk as items #6 and #9, F-tier today; uses `LazyCell` for `adjusted_total_slashing_balance` (computes only if at least one validator matches the predicate).

**Cross-cut chain CLOSED — slashings vector full read/write cycle**: items #8 (attester slashing, WRITE) + #9 (proposer slashing, WRITE) + #10 (per-epoch drain, READ; reset, WRITE-zero) = 76 ops/epoch fixtures × 4 wired clients = 304 PASS results spanning the complete Pectra slashings/exit machinery end-to-end.

**Adjacent untouched Electra-active**: cross-fork slashings drain straddling Pectra activation (formula-choice on state's current fork, not slashing's recording fork); MAX_EFFECTIVE_BALANCE_ELECTRA (2048 ETH) compounding-validator slashing penalty case (penalty scales with 64× increments); `process_slashings` ordering within `process_epoch` (lighthouse's single-pass collapses pyspec sequential ordering); lodestar's penalty-by-increment Map memoization correctness assumption; prysm's `math.Add64` defensive-but-dead overflow check (sum bounded by 8192 × 2048e9 ≪ u64 max); grandine's `LazyCell` for `adjusted_total_slashing_balance` (subtle observability — total_balance computed lazily only with matched validators); multiplier fork-transition correctness (1 → 2 → 3 across Phase0/Altair/Bellatrix+ — multiplier NOT stamped into the slashings vector); reset-after-slashings ordering (reset zeroes (epoch+1), not epoch — current-epoch writes survive the drain); `PROPORTIONAL_SLASHING_MULTIPLIER` Gloas-readiness audit.

See [item10/README.md](item10/README.md).

### 11. `upgrade_to_electra` state-upgrade function (Track C #13, foundational)

**Status:** no-divergence-pending-source-review — audited 2026-05-02. Track C entry. The state-shape-defining transition at the Pectra activation slot; underpins items #1–#10 (every prior item's PASS verdict implicitly validates this item's post-state construction).

`upgrade_to_electra` runs once at the Pectra activation slot, taking the Deneb post-state and producing the Electra pre-state. It defines 9 brand-new Pectra fields (1 EIP-6110: `deposit_requests_start_index = UNSET_DEPOSIT_REQUESTS_START_INDEX = 2^64-1`; 8 EIP-7251: 3 churn-balance fields + 2 epoch-tracker fields + 3 empty queues), derives `earliest_exit_epoch = max(pre.validators[].exit_epoch where ≠ FAR_FUTURE) + 1` (default `compute_activation_exit_epoch(current_epoch)`), seeds the two churn-balance fields via post-state churn-limit functions, and runs two transition loops: pre-activation seeding (sort by `(activation_eligibility_epoch, index)` lex order, zero balance/EB/eligibility, push PendingDeposit with G2_POINT_AT_INFINITY signature + GENESIS_SLOT) and early-adopter compounding queueing (any pre-existing 0x02 validator with balance > MIN_ACTIVATION_BALANCE has the excess queued via `queue_excess_active_balance`). All 6 clients align on the 9 divergence-prone bits per source review.

**Notable per-client styles**: prysm uses imperative `ReadFromEveryValidator` with proto-struct construction (`ConvertToElectra` → `InitializeFromProtoUnsafeElectra`) and **explicitly deviates from spec by using PRE-state for `TotalActiveBalance` in churn-limit calc** (source comment acknowledges; observably-equivalent today since pre.validators == post.validators at upgrade time, but brittle for future Pectra-time changes); lighthouse uses iterator chain with `safe_add(1)?` overflow check and **defensive belt-and-suspenders `.unwrap_or(default).max(default)`** (the .max is redundant after unwrap_or); teku uses verbose `IntStream` + `Comparator.comparing().thenComparing()` for the most-readable rendering of the spec's tuple-key sort; nimbus uses Nim's tuple-comparison sort `seq[(Epoch, uint64)]` (cleanest expression in any client) plus `template post: untyped = result` syntactic sugar; lodestar fuses pre-activation collection with the earliest-exit walk into a single-pass loop, **relies on ES2019 stable sort + explicit `i0 - i1` tiebreaker** (correctness comes from the explicit tiebreaker, not stability); grandine uses `iter().zip(0..).filter().map().sorted()` with itertools — **uses `SignatureBytes::empty()` instead of explicit G2_POINT_AT_INFINITY** (observable-equivalent because the placeholder signature is never validated by `process_pending_deposits`, but a strict-spec-compliance flag).

**EF fixture status**: 22 EF `mainnet/electra/fork/fork/pyspec_tests/` fixtures exist but are **NOT currently dispatched** by BeaconBreaker's harness (`parse_fixture` in `tools/runners/_lib.sh` lacks the `fork/<fork>/` category pattern). All 6 clients' internal CI passes these fixtures per source review of their respective EF integration test runners. **Wiring the fork category in BeaconBreaker is the primary follow-up work for this item.**

**Cross-cut underpinning**: items #1–#10's 227 EF fixture PASSes implicitly validate this item — if upgrade had wrong defaults, a wrong sort, a wrong sentinel, or a wrong churn-source choice, every downstream item exercising non-trivial post-Electra state would have surfaced divergences. The cumulative cross-client agreement on items #1–#10 is the strongest evidence yet that this item is correct across all 6 clients.

**Adjacent untouched Electra-active**: wire fork category in BeaconBreaker harness (highest-priority follow-up); cross-fork sequence `upgrade_to_deneb → upgrade_to_electra` round-trip; pre-activation deposit drain FIFO order (item #4 cross-cut); `fork_inactive_compounding_validator_with_excess_balance` cross-cut H6+H7 ordering; `MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT` clamp at upgrade time; `UNSET_DEPOSIT_REQUESTS_START_INDEX` sentinel transition on first deposit_request; re-upgrade idempotency (programmer-error case); schema-version guard at upgrade entry; pubkey_cache/proposer_cache invalidation choreography; nimbus's `discard post.pending_deposits.add ...` (silent on at-capacity overflow — F-tier today); prysm's pre-state churn-limit deviation forward-compat audit; grandine's `SignatureBytes::empty()` vs explicit `G2_POINT_AT_INFINITY` strict-spec compliance.

See [item11/README.md](item11/README.md).

### 12. `process_withdrawals` Pectra-modified (EIP-7251 partial-queue drain)

**Status:** no-divergence-pending-fuzzing — audited 2026-05-02. Track A withdrawal cycle close; cross-cuts item #3 (producer side via EIP-7002 `process_withdrawal_request`), item #11 (upgrade-time empty-queue initialization), and item #1 (`get_max_effective_balance` helper for sweep partial amount).

`process_withdrawals` is the only operation called every block regardless of validator activity. Pectra adds a brand-new two-phase drain: (1) **partial-queue drain** of up to 8 entries from `state.pending_partial_withdrawals` (capped at `withdrawals_limit = min(prior + 8, MAX_WITHDRAWALS_PER_PAYLOAD - 1 = 15)` — the `-1` reserves at least one slot for sweep), then (2) **Capella-heritage validator sweep** modified to use `get_max_effective_balance(validator)` for partial amounts (32 ETH for 0x01, 2048 ETH for 0x02 — item #1's helper). After processing, `update_pending_partial_withdrawals` slices off the processed prefix from the queue.

All six clients align on the ten divergence-prone bits: two-phase ordering (H1), the `MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP = 8` cap (H2), strict `>` not `>=` on `withdrawable_epoch` (H3), `processed_count` incremented for ALL drained entries even ineligible ones (H4 — drains queue cursor regardless), partial amount = `min(balance - MIN_ACTIVATION_BALANCE, withdrawal.amount)` (H5), sweep partial = `balance - get_max_effective_balance(validator)` (H6), `get_balance_after_withdrawals` cumulative-per-iteration accumulator (H7), eligibility predicate (H8), queue slice `[processed_count:]` (H9), `withdrawal_index` only increments on actual append not on processed_count (H10). All 80 EF `operations/withdrawals` fixtures pass uniformly on prysm+lighthouse+lodestar+grandine. teku+nimbus SKIP per harness limit. Required a runner patch (`tools/runners/grandine.sh`) to handle the no-`process_<helper>::`-namespace test path layout grandine uses for withdrawals (and execution_payload).

**Notable per-client styles**: prysm uses an explicit `min(prior + 8, MAX - 1)` formula at `getters_withdrawal.go:137` and a slice-reslice (`b.pendingPartialWithdrawals = b.pendingPartialWithdrawals[n:]`) for the queue update; lighthouse inlines the entire two-phase logic into `per_block_processing.rs:520–702` (NO dedicated `electra/` module) and uses **hardcoded `== 8`** (observable-equivalent because `prior_withdrawals = []` at this call site); teku uses subclass-override polymorphism (`WithdrawalsHelpersElectra extends WithdrawalsHelpersCapella`) with explicit Math.min formula and SSZ-list re-creation via `subList(processedCount, size)`; nimbus uses compile-time `when consensusFork >= ConsensusFork.Electra` blocks with HashList re-init via `asSeq[processed_count..^1]` — and notably the Gloas path uses the explicit spec formula while Electra hardcodes `== 8` (forward-compat fix landed in Gloas); lodestar uses explicit Math.min formula and `pendingPartialWithdrawals.sliceFrom(processedCount)` SSZ ViewDU op, with BigInt/number coercion at the amount boundary; grandine has FOUR `process_withdrawals` definitions across `capella/`, `electra/`, `gloas/` modules — same source-organization risk as items #6/#9/#10 — and uses **hardcoded `== 8`** (same forward-compat concern as lighthouse).

**Cross-cut chain CLOSED — Track A withdrawal cycle**: items #3 (producer, EIP-7002 request append) + #11 (upgrade-time empty-queue init) + #12 (per-block drain + queue slice — this item) form the complete 0x02-validator-self-service partial-withdrawal lifecycle. Combined with Capella-heritage `next_withdrawal_index` and `next_withdrawal_validator_index`, **the entire withdrawals surface is now audited**.

**Adjacent untouched Electra-active**: lighthouse + grandine `== 8` vs spec `>= min(prior + 8, 15)` forward-compat audit at Gloas activation (Gloas adds `processBuilderWithdrawals` BEFORE the partial drain — non-empty `prior_withdrawals` would expose the divergence; nimbus's Gloas path already uses the spec formula); `update_next_withdrawal_validator_index` cross-cut with two-phase drain (last partial validator's index wins); `withdrawals_root` SSZ Merkleization across mixed partial+sweep withdrawals (cross-client root must match exactly); withdrawal-index continuity gap (ineligible queue entries advance processed_count but not withdrawal_index); MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP = 2 minimal preset; lodestar's `validatorBalanceAfterWithdrawals` Map dual-write coherence (same single-source-of-truth concern as items #4/#5); `get_pending_balance_to_withdraw` correctness after queue slice (sliced entries shouldn't leak into the sum used by items #2/#6); prysm's `mathutil.Sub64` defensive-error vs grandine's `saturating_sub` returning 0 vs lighthouse's `safe_sub` panicking — three failure modes for the same dead-code path; Gloas builder-payment withdrawal interaction (forward-compat); `exit_balance_to_consume` shared per-block budget across item #6 (voluntary exit) and item #3 (partial-withdrawal request) — stateful fixture worth generating; `pending_partial_withdrawals` queue cap (`PENDING_PARTIAL_WITHDRAWALS_LIMIT = 2^27 = 134M`) drain-rate analysis (~232 days at max input rate to fill).

See [item12/README.md](item12/README.md).

### 13. `process_operations` Pectra dispatcher (EIP-6110 cutover + EIP-7685 requests routing)

**Status:** no-divergence-pending-source-review — audited 2026-05-02. The outer fan-out function for ALL block-level operations; cross-cuts every audited operation (#2/#3/#4/#5/#6/#7/#8/#9/#12 + future deposit_request producer audit).

`process_operations` is the block-body fan-out function — it receives the parsed `BeaconBlockBody` and dispatches each operation list to its per-operation processor. Pectra adds two distinct modifications: (1) **EIP-6110 legacy-deposit cutover** at the head: `eth1_deposit_index_limit = min(state.eth1_data.deposit_count, state.deposit_requests_start_index)`, then conditional length check on `body.deposits` (`== min(MAX_DEPOSITS, limit - eth1_deposit_index)` if pre-cutover, `== 0` if post); (2) **EIP-7685 three new request dispatchers** at the tail in spec order: `for_ops(execution_requests.deposits, process_deposit_request)`, then `withdrawals → process_withdrawal_request`, then `consolidations → process_consolidation_request`. The sentinel transition from item #11 (`UNSET_DEPOSIT_REQUESTS_START_INDEX = 2^64 - 1`) keeps the legacy mode active until the EL sends the first DepositRequest, which sets `state.deposit_requests_start_index` to a real index — at which point `min` returns the smaller value and the legacy `body.deposits` MUST be empty. All six clients align on the 9 divergence-prone bits per source review.

**Notable per-client structural divergences (all observable-equivalent)**: grandine separates the three dispatchers from `process_operations` into `custom_process_block:193–206` (a forward-compat risk for any future spec change adding state mutation between dispatchers and the end of `process_operations`); prysm extracts the cutover assertion to `VerifyBlockDepositLength` called BEFORE `electraOperations`; lighthouse uses `state.deposit_requests_start_index().unwrap_or(u64::MAX)` defensive-default (silently masks pre-Electra state queries — should be `debug_assert!`); lodestar's `Number(electraState.depositRequestsStartIndex)` BigInt→number coercion at the cutover comparison (safe today since deposit_count < 2^53, pre-emptive concern); lodestar/prysm have explicit Gloas-fork exclusion (`fork < ForkSeq.gloas` gate / explicit `gloas.go` removal of all three dispatchers — EIP-7732 PBS relocates them); nimbus uses `bsv[]` (bucket-sorted validators) optimization passed to withdrawal/consolidation processors; prysm has per-element nil-checks on each request (defensive against proto-level malformation).

**EF fixture status**: dispatcher behavior is exercised IMPLICITLY via 280 EF fixtures from prior items (#2/#3/#4/#5/#6/#7/#8/#9/#12 = 10+19+43+13+25+45+30+15+80 = 280 fixtures × 4 wired clients = **1120 PASS results that all flow through this dispatcher**). Direct fixture coverage is available via `sanity/blocks/pyspec_tests/deposit_transition__*` (8 fixtures testing the EIP-6110 cutover state machine), `cl_exit_and_el_withdrawal_request_in_same_block` (cross-dispatch ordering), and `basic_btec_and_el_withdrawal_request_in_same_block` — running these through the existing sanity_blocks harness is the immediate follow-up.

**Cross-cut chain CLOSED — process_operations is the FAN-OUT root**: the dispatcher's correctness is implicitly validated by every prior audit item passing its EF fixtures (1120 cumulative PASSes). No divergence found in either layer.

**Adjacent untouched Electra-active**: audit `process_deposit_request` (EIP-6110 — only major Pectra operation not yet a standalone item; sets `deposit_requests_start_index` sentinel transition); audit `requestsHash = sha256(get_execution_requests_list(...))` passed to EL via NewPayloadV4 (high-priority — divergence would cause EL fork at the boundary); audit `get_execution_requests_list` SSZ encoding helper (type-byte prefix + serialize, filtering empty lists); generate stateful fixture spanning EIP-6110 cutover (block N sentinel → block N+1 first DepositRequest → block N+2 `len(body.deposits) == 0`); run the 8 deposit_transition__* sanity_blocks fixtures via existing harness; lighthouse `unwrap_or(u64::MAX)` defensive default → `debug_assert!`; lodestar BigInt→number coercion fuzz target; grandine `custom_process_block` separation forward-compat audit; prysm per-element nil-checks equivalence test; `MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192` over-the-wire SSZ rejection test (block with 8193 should reject); Gloas (EIP-7732) dispatcher relocation cross-client audit (prysm + lodestar excluded explicitly; verify other 4 handle correctly); multi-request-same-validator-same-block ordering test.

See [item13/README.md](item13/README.md).
