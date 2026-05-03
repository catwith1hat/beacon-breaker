# Item 28 — Cross-corpus pre-emptive Gloas-fork divergence consolidated tracking audit

**Status:** consolidation-meta-audit — audited 2026-05-03. Synthesis of pre-emptive Gloas-fork findings across items #1, #3, #4, #6, #7, #8, #9, #10, #12, #13, #14, #15, #16, #18, #19, #20, #21, #22, #23, #25, #26, #27 (22 of 27 prior items contained Gloas-aware findings). **NOT a new function audit** — this document consolidates forward-compat divergence vectors that surface at the Pectra → Gloas boundary.

The Pectra audit corpus repeatedly surfaced code paths that are dead at Pectra but active at Gloas. These pre-emptive patches across 5 of 6 clients (teku is the laggard) constitute a leading indicator of the cross-client divergence surface that will activate at Gloas. This audit catalogs them by pattern, scores per-client Gloas-readiness, and lists the forward-compat audit items that should fire at Gloas activation.

## Scope

In: every Gloas-aware code path observed during items #1–#27, grouped by semantic pattern and ranked by divergence risk at Gloas activation. Per-client readiness scorecard. Forward-compat audit roadmap.

Out: any new function-level audit (Pectra surface is exhaustively covered through item #27); Gloas-fork code that's still UNIMPLEMENTED across all 6 clients (no observable divergence yet); detailed body of the Gloas EIPs (deferred to dedicated Gloas-fork audit phase).

## Why this matters

Pre-emptive Gloas-aware code that exists in **only a subset of clients today** is a high-confidence predictor of cross-client divergence at Gloas activation. Three failure modes:

1. **Lead-then-rollback**: client A ships pre-emptive code matching the spec; spec changes before Gloas activates; client A retains the now-wrong code → divergence at Gloas.
2. **Lead-then-others-don't-follow**: client A ships pre-emptive code; clients B/C/D never add equivalent code; client A diverges at Gloas activation.
3. **Lead-with-different-shape**: clients A and B both ship pre-emptive Gloas code but with different observable semantics (e.g., lodestar's independent `CONSOLIDATION_CHURN_LIMIT_QUOTIENT` vs nimbus's residual model) → divergence at Gloas activation between leaders.

Pattern (3) is the most insidious because two leaders can independently ship Gloas-aware code that **looks** correct but diverges from each other. This audit's per-pattern catalog is the input to the Gloas divergence detection roadmap.

## Per-client Gloas-readiness scorecard

Ranked from most pre-emptive Gloas code observed to least.

| Rank | Client | Gloas-aware surfaces | Patterns observed | Style |
|---|---|---|---|---|
| 1 | **nimbus** | 11+ surfaces (items #1, #3, #8, #9, #10, #12, #14, #19, #21, #22, #23, #27) | type-union (`electra \| fulu \| gloas`), compile-time `when consensusFork >= ConsensusFork.Gloas`, separate function bodies for builder withdrawals | Compile-time fork dispatch via Nim's static typing; Gloas inclusion is the cheapest pattern to extend (just add `gloas` to the union) |
| 2 | **grandine** | 9+ surfaces (items #6, #12, #14, #16, #19, #21, #23, #25, #27) | dedicated `transition_functions/src/gloas/` module, separate `process_deposit_request`/`process_withdrawals`/`process_execution_payload` Gloas variants, post-Gloas sync committee selection function | Module-level fork dispatch via Rust's namespace; Gloas inclusion is a new file/module per fork |
| 3 | **lighthouse** | 6+ surfaces (items #15, #16, #19, #21, #25, #27) | `BeaconState::Gloas(_)` enum match arms, `gloas_enabled()` runtime check, `compute_balance_weighted_selection` post-Gloas, `new_payload_v4_gloas` engine method, `CachedBeaconStateGloas` type | Superstruct enum dispatch via Rust's pattern matching; Gloas inclusion is enum variant + match arm everywhere |
| 4 | **prysm** | 5+ surfaces (items #7, #8, #9, #13, #15, #22) | `version >= version.Gloas` runtime checks, pre-emptive `BuilderWithdrawalPrefixByte = 0x03` constant, `NewPayloadMethodV5`, explicit `gloas.go` dispatcher removal | Runtime version check via Go's switch/if; Gloas inclusion is `if v >= version.Gloas` branches |
| 5 | **lodestar** | 6+ surfaces (items #4, #13, #14, #15, #16, #19) | `getActivationChurnLimit` Gloas branch, `getConsolidationChurnLimit` independent quotient, `applyDepositForBuilder` Gloas-fork path, V5 engine method, `fork < ForkSeq.gloas` exclusion gates | Numeric `ForkSeq` runtime check; Gloas inclusion is `if (fork >= ForkSeq.gloas)` branches |
| 6 | **teku** | minimal — no Gloas-specific code observed in 27 items | (none observed; subclass-extension implicit pattern) | Subclass-override pattern; Gloas inclusion would require new `BeaconStateMutatorsGloas extends BeaconStateMutatorsElectra` etc. classes |

**Headline**: nimbus and grandine are the Gloas-readiness leaders. **teku is the strongest laggard** — its subclass-extension pattern means Gloas activation requires the most code surface change.

## Per-pattern Gloas divergence catalog

The following 11 patterns surfaced during items #1–#27. Each is a forward-compat divergence vector that should fire a dedicated audit at Gloas activation.

### Pattern A — `0x03` BUILDER withdrawal credential prefix (EIP-7732 PBS)

**Surface:** `has_compounding_withdrawal_credential`, `is_builder_withdrawal_credential`, `has_execution_withdrawal_credential`, constant `BuilderWithdrawalPrefixByte = 0x03`.

| Client | Gloas-aware? | Source |
|---|---|---|
| nimbus | ✅ `when consensusFork >= ConsensusFork.Gloas: 0x02 OR 0x03` | item #1, #22 (`beaconstate.nim`) |
| prysm | ✅ defines constant pre-emptively (no active code path uses it at Pectra) | item #22 (`core/electra/validator.go`) |
| lighthouse | ❌ no `0x03` predicate observed | item #22 audit |
| teku | ❌ no `0x03` predicate observed | item #22 audit |
| lodestar | ❌ no `0x03` predicate observed | item #22 audit |
| grandine | ❌ no `0x03` predicate observed | item #22 audit |

**Divergence vector at Gloas:** if other 4 clients silently treat `0x03` as compounding (or as eth1) at Gloas, they diverge from nimbus. If the spec settles on `0x03 == compounding` (likely), nimbus/prysm are correct and the other 4 must update.

**Audit at Gloas:** cross-client `has_compounding_withdrawal_credential` byte-for-byte equivalence on `0x03` credentials.

### Pattern B — Builder pending-withdrawals accumulator (`get_pending_balance_to_withdraw_for_builder`)

**Surface:** `get_pending_balance_to_withdraw` (Gloas branch), separate `get_pending_balance_to_withdraw_for_builder` function.

| Client | Gloas-aware? | Source |
|---|---|---|
| nimbus | ✅ `when type(state).kind >= ConsensusFork.Gloas` block sums builder withdrawals + payments | item #3, #23 (`beaconstate.nim:1541-1559`) |
| grandine | ✅ separate `get_pending_balance_to_withdraw_for_builder` at `accessors.rs:995` | item #23 |
| lighthouse | ❌ | item #23 audit |
| teku | ❌ | item #23 audit |
| lodestar | ❌ | item #23 audit |
| prysm | ❌ | item #23 audit |

**Divergence vector at Gloas:** nimbus/grandine sum builder pending withdrawals + payments; other 4 don't. If a Gloas validator has both compounding pending withdrawals AND builder pending payments, nimbus/grandine reject voluntary exits/withdrawal requests/consolidation requests sooner than other 4. **Direct C-tier divergence: different exit-eligibility verdicts on the same state.**

**Audit at Gloas:** standalone `get_pending_balance_to_withdraw_for_builder` cross-client equivalence + the `process_voluntary_exit` / `process_withdrawal_request` / `process_consolidation_request` end-to-end behavior on Gloas builder states.

### Pattern C — Activation/exit churn limit (`getActivationChurnLimit` vs `getActivationExitChurnLimit`)

**Surface:** `process_pending_deposits` churn limit selection at Gloas.

| Client | Gloas-aware? | Source |
|---|---|---|
| lodestar | ✅ Gloas branch uses `getActivationChurnLimit` (NOT `getActivationExitChurnLimit`) | item #4 (`epoch/processPendingDeposits.ts:25-32`) |
| nimbus | ❌ uses `getActivationExitChurnLimit` (does not branch) | item #4 |
| prysm | ❌ | item #4 |
| lighthouse | ❌ | item #4 |
| teku | ❌ | item #4 |
| grandine | ❌ | item #4 |

**Divergence vector at Gloas:** lodestar's `available_for_processing` differs from other 5 clients at Gloas. **Direct C-tier divergence: different deposit-drain throughput per epoch.**

**Audit at Gloas:** confirm the spec text (whether Gloas changes the churn-limit selection); if lodestar matches spec, other 5 must follow; if not, lodestar must roll back.

### Pattern D — Consolidation churn limit independent quotient (`CONSOLIDATION_CHURN_LIMIT_QUOTIENT`)

**Surface:** `get_consolidation_churn_limit` at Gloas.

| Client | Gloas-aware? | Source |
|---|---|---|
| lodestar | ✅ Gloas branch uses INDEPENDENT `CONSOLIDATION_CHURN_LIMIT_QUOTIENT` quotient (NOT residual model) | item #16 (`packages/state-transition/src/util/`) |
| nimbus | ❌ uses residual model `balance_churn - activation_exit_churn` | item #16 |
| prysm | ❌ | item #16 |
| lighthouse | ❌ | item #16 |
| teku | ❌ | item #16 |
| grandine | ❌ | item #16 |

**Divergence vector at Gloas:** lodestar's `consolidation_churn_limit` differs from other 5 clients at Gloas. **Direct C-tier divergence: different consolidation-drain throughput per block.**

**Audit at Gloas:** same as Pattern C — confirm spec text; if lodestar matches, others follow; if not, lodestar rolls back.

### Pattern E — Committee index `< 2` post-Gloas

**Surface:** `process_attestation` `data.index` validation at Gloas.

| Client | Gloas-aware? | Source |
|---|---|---|
| prysm | ✅ post-Gloas: `data.index < 2` (vs `== 0` pre-Gloas) | item #7 (`core/blocks/attestation.go:113-128`) |
| lighthouse | ❌ | item #7 |
| teku | ❌ | item #7 |
| nimbus | ❌ | item #7 |
| lodestar | ❌ | item #7 |
| grandine | ❌ | item #7 |

**Divergence vector at Gloas:** prysm accepts `data.index ∈ {0, 1}` at Gloas; other 5 still reject `data.index == 1`. **Direct A-tier divergence: prysm includes attestations the other 5 reject as invalid → fork at first such attestation.**

**Audit at Gloas:** confirm whether Gloas EIP introduces a 2-way committee split; if so, other 5 must follow. **High priority** — A-tier divergence on the highest-frequency CL operation.

### Pattern F — Sync committee selection (`compute_balance_weighted_selection` / `get_next_sync_committee_indices_post_gloas`)

**Surface:** `get_next_sync_committee_indices` at Gloas.

| Client | Gloas-aware? | Source |
|---|---|---|
| lighthouse | ✅ `compute_balance_weighted_selection` (helper at `:1156-1190`) used post-Gloas | item #27 (`beacon_state.rs:1396-1447`) |
| grandine | ✅ separate `get_next_sync_committee_indices_post_gloas` at `accessors.rs:707-729` | item #27 |
| prysm | ❌ | item #27 |
| teku | ❌ | item #27 |
| nimbus | ❌ | item #27 |
| lodestar | ❌ | item #27 |

**Divergence vector at Gloas:** lighthouse + grandine select different sync committees than the other 4 clients at Gloas activation. **Direct A-tier divergence: different sync committee membership = different sync aggregate signers = different finality.**

**Audit at Gloas:** confirm whether Gloas EIP modifies sync committee selection (likely yes, since lighthouse + grandine independently pre-emptive); cross-client byte-for-byte equivalence on the post-Gloas selection function.

### Pattern G — Builder deposit-request handling (`applyDepositForBuilder`)

**Surface:** `process_deposit_request` at Gloas (PBS adds builder-deposit branch).

| Client | Gloas-aware? | Source |
|---|---|---|
| lodestar | ✅ separate `applyDepositForBuilder` Gloas-fork path with on-the-fly BLS verification | item #14 (`processDepositRequest.ts`) |
| grandine | ✅ separate `gloas/execution_payload_processing.rs:290` `process_deposit_request` with builder logic + signature verification | item #14 |
| nimbus | ✅ separate `:413-448` Gloas variant of `apply_pending_deposit` | item #14 (`state_transition_block.nim`) |
| prysm | partially — has `gloas.go` dispatcher exclusion but no builder-deposit code observed | item #13 |
| lighthouse | ❌ | item #14 |
| teku | ❌ | item #14 |

**Divergence vector at Gloas:** Gloas restructures deposit handling significantly (PBS adds builder-payment deposits). 3 of 6 clients have non-trivial code; 3 don't. **A-tier divergence: different validator set after first Gloas builder deposit.**

**Audit at Gloas:** standalone `process_deposit_request` Gloas-fork audit; cross-client builder-deposit fixture set; verify BLS-verification timing (on-the-fly vs deferred).

### Pattern H — Dispatcher-level Gloas exclusion gates (`fork < ForkSeq.gloas`)

**Surface:** `process_operations` execution requests dispatcher; `process_deposit_request` sentinel-set logic.

| Client | Gloas-aware? | Source |
|---|---|---|
| lodestar | ✅ `fork >= ForkSeq.electra && fork < ForkSeq.gloas` for execution requests dispatch; `fork < ForkSeq.gloas` for sentinel-set | item #13, #14 |
| prysm | ✅ explicit `gloas.go:20-58` removal of dispatcher (Gloas relocates via PBS) | item #13 |
| nimbus | ❌ | item #13 |
| lighthouse | ❌ | item #13 |
| teku | ❌ | item #13 |
| grandine | ❌ | item #13 |

**Divergence vector at Gloas:** at Gloas activation, lodestar + prysm DON'T run the Pectra-style execution-requests dispatcher — they expect the Gloas-fork code path (PBS) to handle it. The other 4 clients still run the Pectra dispatcher → **double-process** of execution requests, or **incorrectly process** execution requests at Gloas. **A-tier divergence: post-state mismatch on the first Gloas block with execution requests.**

**Audit at Gloas:** verify all 6 clients gate the Pectra-style dispatcher off at Gloas; cross-client `process_operations` Gloas-fork end-to-end fixture.

### Pattern I — Multi-fork-definition pattern (separate Gloas function bodies)

**Surface:** `process_execution_payload`, `process_withdrawals`, `apply_pending_deposit`, `process_deposit_request`.

| Client | Pattern | Source |
|---|---|---|
| nimbus | separate `process_execution_payload` for Electra (1068)/Fulu (1113)/Gloas (1154) — 3 distinct function bodies | item #19 |
| grandine | dedicated `gloas/execution_payload_processing.rs`, `gloas/block_processing.rs:448-500`, `gloas/` module per surface | items #12, #14, #19 |
| lighthouse | superstruct enum variants force per-fork bodies | item #19 |
| teku | subclass-override polymorphism — Gloas needs new subclass | item #19 |
| nimbus | `apply_pending_deposit` Electra/Fulu (391-410) vs Gloas (413-448) — separate function bodies | item #14 |
| nimbus + grandine | partial-withdrawals `min(prior + 8, MAX - 1)` formula at Gloas (vs Pectra hardcoded `== 8`) | item #12 |

**Divergence vector at Gloas:** the multi-fork-definition pattern is forward-fragile — when the Gloas spec changes, only the Gloas-specific body must update. But if a client also updates the Electra body (via accidental refactor), historical Electra blocks may fail to verify. This is the SAME risk pattern flagged in items #6, #9, #10, #12, #14, #15, #17, #19.

**Audit at Gloas:** byte-for-byte equivalence test that historical Electra blocks still verify after Gloas-fork code is added (regression test against the multi-fork-definition pattern).

### Pattern J — Type-union Gloas inclusion (compile-time fork dispatch already includes Gloas)

**Surface:** every nimbus state-mutation function uses `state: var (electra.BeaconState | fulu.BeaconState | gloas.BeaconState)`; lighthouse uses `BeaconState::Electra(_) | BeaconState::Fulu(_) | BeaconState::Gloas(_)`.

This is **the cheapest Gloas inclusion pattern** — adding `gloas` to a union or match arm requires only a single line per surface. nimbus and lighthouse have this pattern across 11+ and 6+ surfaces respectively.

**Divergence vector at Gloas:** none — observable-equivalent if the function body is correct for both Electra and Gloas at the same time. But if a Gloas-specific tweak is needed and the developer forgets to add a `when consensusFork >= Gloas` branch, the union silently makes the Pectra body run for Gloas blocks → silent divergence.

**Audit at Gloas:** code-review-driven — verify each type-union function checks for fork-specific behavior before applying the body.

### Pattern K — Engine API Gloas methods (`engine_newPayloadV5`)

**Surface:** Engine API method routing at Gloas.

| Client | Gloas-aware? | Source |
|---|---|---|
| prysm | ✅ `NewPayloadMethodV5` constant defined | item #15 |
| lighthouse | ✅ `new_payload_v4_gloas` (also `_electra`, `_fulu`) HTTP method | item #15 |
| lodestar | ✅ V5 wired per source | item #15 |
| teku | unknown — likely subclass-pattern | item #15 |
| nimbus | unknown — likely separate function per fork | item #15 |
| grandine | unknown | item #15 |

**Divergence vector at Gloas:** if 1 of 6 clients sends V4 to the EL at Gloas (or V5 at Pectra), the EL rejects the payload → CL fork. **A-tier divergence at the EL boundary.**

**Audit at Gloas:** cross-client Engine API method routing audit; spec-test fixture for V4-vs-V5 boundary at the Gloas activation slot.

### Pattern L — Voluntary-exit signing-domain extension (CAPELLA pin extends to Gloas)

**Surface:** `process_voluntary_exit` signature domain.

| Client | Gloas-aware? | Source |
|---|---|---|
| grandine | ✅ `current_fork_version == config.gloas_fork_version` extends EIP-7044 CAPELLA pin to Gloas | item #6 (`signing.rs:420-449`) |
| others | ❌ — but EIP-7044 already pins to CAPELLA, so Gloas is implicitly handled | item #6 |

**Divergence vector at Gloas:** EIP-7044 says "use CAPELLA_FORK_VERSION for voluntary-exit signing domain regardless of current fork." All 6 clients already implement this. grandine's explicit Gloas branch is a no-op (already covered by the CAPELLA pin). **No divergence vector — Pattern L is already correct across all 6 clients.**

## Forward-compat divergence vectors at Gloas activation (consolidated risk roadmap)

Ranked by tier (A = block-validation / state-divergence; B = sub-block protocol; C = throughput/limit math; F = forward-fragile patterns).

### A-tier (immediate fork on first Gloas block matching the trigger)

1. **Pattern E** (committee index `< 2`) — prysm vs other 5 → fork on first attestation with `data.index == 1` at Gloas.
2. **Pattern F** (sync committee selection) — lighthouse + grandine vs other 4 → different sync committee = different finality.
3. **Pattern G** (builder deposit handling) — lodestar/grandine/nimbus vs other 3 → different validator set after first Gloas builder deposit.
4. **Pattern H** (dispatcher exclusion gates) — lodestar + prysm vs other 4 → double-process of execution requests at Gloas.
5. **Pattern K** (Engine API V5) — any client that doesn't switch to V5 at Gloas → EL rejection.

### B-tier (sub-block protocol; affects gossip/aggregation)

(none unique to Gloas-pre-emptive code observed in items #1–#27)

### C-tier (throughput/limit math; eventually causes divergence)

6. **Pattern C** (lodestar `getActivationChurnLimit`) — lodestar vs other 5 → different deposit-drain throughput at Gloas.
7. **Pattern D** (lodestar `CONSOLIDATION_CHURN_LIMIT_QUOTIENT`) — lodestar vs other 5 → different consolidation throughput at Gloas.
8. **Pattern A** (`0x03` builder credential) — nimbus/prysm vs other 4 → different `effective_balance` for builder validators at Gloas.
9. **Pattern B** (builder pending withdrawals) — nimbus/grandine vs other 4 → different exit-eligibility verdicts at Gloas.

### F-tier (forward-fragile patterns; not divergence today, but a known risk class)

10. **Pattern I** (multi-fork-definition) — historical Electra blocks may fail to verify after Gloas-fork code added if developers refactor the Electra body.
11. **Pattern J** (type-union silent inclusion) — Gloas-specific tweaks may be missed if developers forget to add a `when` / match-arm branch.

## Cross-cut chain (which prior items contributed)

The 22 prior items that produced Gloas-aware findings (items #1, #3, #4, #6, #7, #8, #9, #10, #12, #13, #14, #15, #16, #18, #19, #20, #21, #22, #23, #25, #26, #27) collectively account for the 11 patterns and 9 divergence vectors above. The 5 items that did NOT produce Gloas findings (items #2, #5, #11, #17, #24) are pure-Pectra surfaces with no Gloas activity in any of the 6 clients today — likely candidates for a Gloas audit when Gloas spec details solidify.

| Item | Pattern(s) contributed |
|---|---|
| #1 | A (`0x03` BUILDER credential) |
| #3 | B (builder pending withdrawals) |
| #4 | C (lodestar `getActivationChurnLimit`) |
| #6 | L (CAPELLA pin extension) |
| #7 | E (committee index `< 2`) |
| #8 | I (slashing quotient nimbus type-union) |
| #9 | I, J (slashing nimbus type-union) |
| #10 | I (slashing-multiplier nimbus type-union) |
| #12 | I (`min(prior + 8, MAX - 1)` Gloas formula) |
| #13 | H (dispatcher exclusion gates) |
| #14 | G (builder deposit handling), H (sentinel-set gate) |
| #15 | K (Engine API V5) |
| #16 | D (lodestar consolidation churn quotient) |
| #18 | I, J |
| #19 | I (multi-fork-definition pattern), K |
| #20 | G (lodestar `applyDepositForBuilder`) |
| #21 | (no new pattern — single-definition consistency check) |
| #22 | A (prysm + nimbus pre-emptive) |
| #23 | B (nimbus + grandine builder withdrawals) |
| #25 | (no new pattern — IndexedAttestation capacity at Gloas) |
| #26 | (no new pattern — attestation structure at Gloas) |
| #27 | F (sync committee selection) |

## EF fixture status

**No EF fixtures exist for Gloas yet** — the spec is in development. The Gloas-readiness above is purely source-code-level. This audit's value is precisely that it surfaces the divergence surface BEFORE fixtures exist, allowing pre-emptive cross-client code review at the Pectra → Gloas transition planning phase.

## Adjacent untouched

- **Track G — sync committee** beyond item #27: `process_sync_committee_updates`, `process_sync_aggregate`, `compute_sync_committee_period`, `get_sync_committee` — these are Phase0/Altair-heritage but interact with item #27's selection at the period boundary. Items contributed pattern F.
- **Track D — fork choice**: no Gloas-aware fork choice code observed in items #1–#27; Gloas EIP-7732 PBS may add new fork-choice rules.
- **Track E — SSZ**: `Attestation`, `IndexedAttestation`, `ExecutionPayload`, `ExecutionRequests` SSZ schema changes at Gloas not yet audited.
- **Track F — BLS**: items #20 + #25 confirmed all 6 clients use BLST; Gloas may add new BLS surfaces (e.g., builder-payment signatures with PROOF_OF_POSSESSION).
- Per-network `gloas_fork_version` constant verification (mainnet/sepolia/holesky) once configs ship.
- Cross-client `engine_newPayloadV5` request/response schema audit when EIP-7732 PBS lands.
- `process_builder_withdrawals` standalone audit at Gloas activation (cross-cuts items #12 + #23).
- `process_builder_payment` cross-client audit (Gloas-NEW per EIP-7732).
- Compile-time vs runtime fork dispatch performance audit at Gloas (nimbus's compile-time dispatch may have a measurable advantage at deep fork stacks).

## Future research items

1. **A-tier divergence pre-emptive fixture set**: construct EF fixtures for Patterns E, F, G, H, K that exercise the divergence trigger at the Gloas activation slot. Even without a Gloas spec, fixture construction can use placeholder Gloas constants — the test is whether the 6 clients agree on a synthetic "Gloas" state.
2. **Pattern I regression test suite**: byte-for-byte verify that historical Electra blocks still verify after Gloas-fork code is added — applied to nimbus, grandine, lighthouse, lodestar, prysm separately at every Gloas-related PR.
3. **Cross-client Pattern A audit**: contact each client team to confirm their `0x03` BUILDER credential treatment plan; if 4 of 6 plan to silently treat as compounding (matching nimbus), update the pattern catalog.
4. **Lodestar Pattern C/D resolution**: confirm with the spec team whether lodestar's Gloas-specific churn-limit selection is correct; if so, contact the other 5 client teams to follow; if not, contact lodestar to roll back.
5. **Prysm Pattern E audit**: confirm with the spec team whether `data.index < 2` at Gloas is canonical; if so, contact the other 5 client teams to follow.
6. **Engine API V5 wire-format cross-client audit** (Pattern K) — when EIP-7732 PBS lands, fixture set for V4-vs-V5 transition at Gloas activation slot.
7. **Builder-deposit on-the-fly BLS verification audit** (Pattern G) — lodestar `applyDepositForBuilder` and grandine `gloas/execution_payload_processing.rs:290` both verify BLS at deposit time; nimbus's `:413-448` Gloas variant should be checked for the same; cross-client equivalence test on builder-deposit signatures.
8. **Type-union silent inclusion audit** (Pattern J) — for each nimbus type-union function and lighthouse match-arm function that includes Gloas, code-review-driven check that the body is correct for Gloas semantics; if not, file an issue.
9. **`process_builder_withdrawals` cross-client audit at Gloas** — already noted as adjacent in items #12 + #23.
10. **`process_builder_payment` cross-client audit at Gloas** — Gloas-NEW per EIP-7732 PBS.
11. **Per-client Gloas implementation tracking dashboard** — quarterly source-tree scan of `grep -r "[Gg]loas"` per client to track Gloas implementation progress; build into BeaconBreaker as `tools/runners/gloas_readiness.sh`.
12. **`gloas_fork_version` per-network constant verification** when configs ship (mainnet/sepolia/holesky).
13. **EIP-7732 PBS spec-text cross-reference audit** when spec stabilizes — cross-check each pattern A–K above against the canonical Gloas spec text; update pattern catalog with spec deltas.
14. **teku Gloas-readiness audit** — teku is the laggard; contact the teku team to confirm their Gloas implementation timeline; identify the subclass extension points (`BeaconStateMutatorsGloas`, `BeaconStateAccessorsGloas`, `PredicatesGloas`) that need to be created.
15. **Pre-emptive Gloas test-vector generation** — once Gloas EIPs stabilize, generate test vectors that exercise each of the 11 patterns above; ship to EF for inclusion in `consensus-spec-tests`.

## Summary

The Pectra audit corpus surfaced 11 distinct pre-emptive Gloas patterns across 22 of 27 prior items. **5 of 6 clients have non-trivial pre-emptive Gloas code**; teku is the laggard. **9 forward-compat divergence vectors** are catalogued, ranked A-tier (5 vectors causing immediate fork) through F-tier (forward-fragile patterns). This document is the input to the post-Pectra Gloas audit phase: it provides a **roadmap of where to look first** at Gloas activation rather than starting from zero.

**Key insight:** divergence at Gloas activation is HIGHLY predictable from Pectra-corpus pre-emptive code. The 5 A-tier vectors above (Patterns E, F, G, H, K) account for the highest-risk divergence trigger surface and should be the first targets of Gloas audit fixtures.
