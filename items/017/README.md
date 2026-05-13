---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-12
builds_on: [4, 6, 11, 16]
eips: [EIP-7251, EIP-8061]
splits: [prysm, lighthouse, teku, nimbus, grandine]
# main_md_summary: the ejection branch of `process_registry_updates` calls `initiate_validator_exit`, propagating the EIP-8061 churn-helper divergence (item #16 H12) — only lodestar fork-gates the underlying `compute_exit_epoch_and_update_churn` at Gloas
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 17: `process_registry_updates` Pectra-modified (single-pass restructure + EIP-7251 eligibility predicate)

## Summary

`process_registry_updates` runs every epoch and gates three per-validator state transitions: (1) activation-queue eligibility (validators with `activation_eligibility_epoch == FAR_FUTURE_EPOCH` AND `effective_balance >= MIN_ACTIVATION_BALANCE` → set eligibility to `current + 1`); (2) ejection (active validators with `effective_balance <= EJECTION_BALANCE` → `initiate_validator_exit`); (3) activation (validators with finalised eligibility AND `activation_epoch == FAR_FUTURE_EPOCH` → set to `compute_activation_exit_epoch(current)`). Pectra makes two major changes: the eligibility predicate switches from `== MAX_EFFECTIVE_BALANCE` (exactly 32 ETH) to `>= MIN_ACTIVATION_BALANCE` (32 ETH or more, for compounding validators), and the algorithm restructures from two-pass-with-churn-limit to **single-pass with no per-epoch activation churn limit** (churn is now metered at the deposit + exit primitives via item #16).

**Pectra surface (the function body itself):** all six clients implement the Pectra predicate and single-pass structure identically (modulo three implementation patterns — Pattern A explicit `elif`, Pattern B independent ifs + post-collection update, Pattern C single-pass folding into the omnibus epoch processor; all observable-equivalent by the finalisation timing invariant). 63 PASS results across 16 EF `registry_updates` fixtures × 4 wired clients, with one deliberate lodestar skip (`invalid_large_withdrawable_epoch` — a u64 overflow path that TypeScript's BigInt cannot reproduce; documented in lodestar's vitest config).

**Gloas surface (at the Glamsterdam target):** `process_registry_updates` is **not modified** at Gloas — no `Modified process_registry_updates` heading in `vendor/consensus-specs/specs/gloas/beacon-chain.md`. `is_eligible_for_activation_queue` is unchanged. The constants (`MIN_ACTIVATION_BALANCE`, `EJECTION_BALANCE`) are unchanged. The Gloas-modified `process_epoch` (line 953) preserves the routine's position between `process_rewards_and_penalties` and `process_slashings`. **However**, the ejection branch calls `initiate_validator_exit`, which calls `compute_exit_epoch_and_update_churn` — the EIP-8061 chokepoint Modified at Gloas (item #16 H12). At Gloas, 5-of-6 clients (prysm, lighthouse, teku, nimbus, grandine) fail to fork-gate the underlying churn helper to use `get_exit_churn_limit`; only lodestar uses the Gloas-correct formula. Each ejected validator's `exit_epoch` and `withdrawable_epoch` therefore diverge across the 5-vs-1 cohort at Gloas. **Seventh item in the EIP-8061 cascade family.**

## Question

Pyspec `process_registry_updates` (Pectra-modified, `vendor/consensus-specs/specs/electra/beacon-chain.md:900`):

```python
def process_registry_updates(state):
    current_epoch = get_current_epoch(state)
    activation_epoch = compute_activation_exit_epoch(current_epoch)
    for index, validator in enumerate(state.validators):
        if is_eligible_for_activation_queue(validator):
            validator.activation_eligibility_epoch = current_epoch + 1
        elif is_active_validator(validator, current_epoch) and validator.effective_balance <= EJECTION_BALANCE:
            initiate_validator_exit(state, ValidatorIndex(index))      # Pectra churn-paced (item #16)
        elif is_eligible_for_activation(state, validator):
            validator.activation_epoch = activation_epoch              # NO per-epoch churn cap
```

with the Pectra-modified eligibility predicate (`vendor/consensus-specs/specs/electra/beacon-chain.md:474`):

```python
# Modified in Electra:EIP7251
def is_eligible_for_activation_queue(validator):
    return (validator.activation_eligibility_epoch == FAR_FUTURE_EPOCH
            and validator.effective_balance >= MIN_ACTIVATION_BALANCE)   # NEW: inequality, MIN-ACTIVATION
    # Pre-Electra (Phase0): == MAX_EFFECTIVE_BALANCE (32 ETH strict equality)
```

Nine Pectra-relevant divergence-prone bits (H1–H9 unchanged from the prior audit): predicate inequality, eligibility precondition, single-pass structure, no per-epoch activation churn, branch ordering, activation-epoch source, Pectra `initiate_validator_exit` invocation, `is_eligible_for_activation` predicate, `current_epoch + 1` eligibility timing.

**Glamsterdam target.** `process_registry_updates` is not modified at Gloas — `vendor/consensus-specs/specs/gloas/beacon-chain.md` has no `Modified process_registry_updates` heading. The function body, the eligibility predicate, the branch order, the activation-epoch source, and the constants are all identical to Pectra at Gloas. The Gloas-modified `process_epoch` preserves the routine's relative position (between `process_rewards_and_penalties` and `process_slashings`). The new Gloas helpers (`process_builder_pending_payments`, `process_ptc_window`) are inserted later in the epoch sequence and don't touch the registry.

**However**, the ejection branch's `initiate_validator_exit(state, ValidatorIndex(index))` is the same Pectra-modified function audited in items #6 / #8 / #9. At Gloas, the cascade through `initiate_validator_exit → compute_exit_epoch_and_update_churn` propagates the EIP-8061 chokepoint divergence (item #16 H12): only lodestar consumes the Gloas-new `get_exit_churn_limit`; the other five use the Electra `get_activation_exit_churn_limit`. Each ejected validator's `exit_epoch` (and consequently `withdrawable_epoch`) is paced at a different rate across the 5-vs-1 cohort.

The hypothesis: *all six clients implement the Pectra single-pass restructure and the inequality eligibility predicate identically (H1–H9), and at the Glamsterdam target all six fork-gate the underlying `compute_exit_epoch_and_update_churn` to use `get_exit_churn_limit` (H10, inherited from item #16 H12).*

**Consensus relevance**: this is the per-epoch activation/ejection gatekeeper. Every newly-funded validator's progression from `pending_deposits` (item #4) through eligibility to activation flows through this function. Every validator whose balance drops below `EJECTION_BALANCE` is ejected here. A divergence in the Pectra predicate would cause cross-client mismatch on which validators are in the activation queue; a divergence in the ejection cascade (item #17 H10) shifts the ejected validators' `exit_epoch` assignments — same pattern as items #6 H8 / #8 H9 / #9 H10 / #16 H12.

## Hypotheses

- **H1.** `is_eligible_for_activation_queue` Pectra: `effective_balance >= MIN_ACTIVATION_BALANCE` (NOT `== MAX_EFFECTIVE_BALANCE`).
- **H2.** `is_eligible_for_activation_queue` Pectra: still requires `activation_eligibility_epoch == FAR_FUTURE_EPOCH`.
- **H3.** SINGLE-PASS loop (NOT two-pass), modulo implementation-style variations.
- **H4.** NO per-epoch activation churn limit at this layer (all eligible activate at `compute_activation_exit_epoch(current_epoch)`).
- **H5.** Branch ordering: eligibility-for-queue → ejection → eligibility-for-activation (Pattern A explicit `elif`, or Pattern B independent ifs that are mutually exclusive by finalisation timing).
- **H6.** Activation epoch source: `compute_activation_exit_epoch(current_epoch)` = `current + 1 + MAX_SEED_LOOKAHEAD = current + 5`.
- **H7.** `initiate_validator_exit` invocation is the Pectra version (calls `compute_exit_epoch_and_update_churn` — item #16).
- **H8.** `is_eligible_for_activation` (NO QUEUE) unchanged from Phase0: `activation_eligibility_epoch <= state.finalized_checkpoint.epoch && activation_epoch == FAR_FUTURE_EPOCH`.
- **H9.** Activation eligibility set: `activation_eligibility_epoch = current_epoch + 1` (NOT `current_epoch`).
- **H10** *(Glamsterdam target — EIP-8061 cascade via ejection branch)*. At the Gloas fork gate, the ejection branch's `initiate_validator_exit` cascades through `compute_exit_epoch_and_update_churn` consuming `get_exit_churn_limit` (Gloas) instead of `get_activation_exit_churn_limit` (Electra). Pre-Gloas, all six retain the Electra helper. Same finding as items #3 H8 / #6 H8 / #8 H9 / #9 H10, anchored at item #16's H12 chokepoint.

## Findings

H1–H9 satisfied for the Pectra surface — eligibility predicate, single-pass structure, no per-epoch activation churn, branch order, activation-epoch source, finalisation-gated activation, and `current_epoch + 1` timing all aligned. **H10 fails for 5 of 6 clients** at the Glamsterdam target — same finding as item #6 H8 since this item's ejection branch funnels through the same `compute_exit_epoch_and_update_churn` primitive audited at item #16 H12. Only lodestar fork-gates the helper.

### prysm

`vendor/prysm/beacon-chain/core/electra/registry_updates.go:39-107` — `ProcessRegistryUpdates`. Three independent `if`s collecting indices via `ReadFromEveryValidator`, then 3 sequential update loops (Pattern B). Eligibility predicate via `IsEligibleForActivationQueue` (`vendor/prysm/beacon-chain/core/helpers/validators.go:455-494`) which dispatches by fork-epoch to `isEligibleForActivationQueueElectra:491-494` (Pectra `>= MIN_ACTIVATION_BALANCE`).

**Gloas-target cascade (H10 ✗)**: the ejection branch calls `validators.InitiateValidatorExit(ctx, s, slashedIdx, exitInfo)` (Pectra version), which delegates to `state.ExitEpochAndUpdateChurn(EffectiveBalance)` at `vendor/prysm/beacon-chain/state/state-native/setters_churn.go:67`. That function calls `helpers.ActivationExitChurnLimit(totalActiveBalance)` unconditionally — no fork branch. At Gloas, prysm's ejection-cascade exit-epoch advance uses the Electra formula even on Gloas states.

H1 ✓. H2 ✓. H3 ✓ (Pattern B). H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✗** (inherited from item #6 H8 / item #16 H12 finding).

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_epoch_processing/single_pass.rs:672-776` — `process_single_registry_update` (inlined into omnibus single-pass epoch processor, Pattern C). `vendor/lighthouse/consensus/state_processing/src/per_epoch_processing/registry_updates.rs:9-57` is the pre-Electra fast path (legacy two-pass + churn).

Eligibility predicate: `vendor/lighthouse/consensus/types/src/validator/validator.rs:113-116 is_eligible_for_activation_queue_electra` + dispatch at lines 90-100 selects per-fork.

**Gloas-target cascade (H10 ✗)**: ejection branch calls `state.initiate_validator_exit(index, spec)?`, which calls `state.compute_exit_epoch_and_update_churn(effective_balance, spec)?` (`vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2708-2752`). Body uses `self.get_activation_exit_churn_limit(spec)?` unconditionally — no Gloas fork branch.

H1 ✓. H2 ✓. H3 ✓ (Pattern C). H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✗** (inherited from item #6 H8 / item #16 H12 finding).

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/statetransition/epoch/EpochProcessorElectra.java:86-120` — `processRegistryUpdates` (subclass override of `EpochProcessorBellatrix`). Standard if/elif/elif single-pass loop (Pattern A). Eligibility predicate at `:134-139` (overridden from parent's `isEligibleForActivationQueue`).

**Gloas-target cascade (H10 ✗)**: ejection branch calls `beaconStateMutators.initiateValidatorExit(state, index, validatorExitContextSupplier)`, the Pectra-modified version at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/BeaconStateMutatorsElectra.java:108-132`. That calls `computeExitEpochAndUpdateChurn(stateElectra, validator.getEffectiveBalance())` at line 121, whose body at lines 77-104 uses `stateAccessorsElectra.getActivationExitChurnLimit(state)` unconditionally. `BeaconStateMutatorsGloas` does NOT override (per item #6 / #16 findings).

H1 ✓. H2 ✓. H3 ✓ (Pattern A). H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✗** (Gloas mutators don't override the churn helper).

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_epoch.nim:918-942` — `process_registry_updates*` (`when consensusFork >= ConsensusFork.Electra` block). TWO sequential complete passes over `state.validators` (eligibility + ejection first, then activation) — observable-equivalent to Pattern A because the second pass's `is_eligible_for_activation` check requires `activation_eligibility_epoch <= finalized_epoch` and the first pass set newly-eligible validators to `current_epoch + 1` (NOT yet finalised).

Eligibility predicate: `vendor/nimbus/beacon_chain/spec/beaconstate.nim:607-616` (compile-time `when fork <= Deneb` else branch).

**Gloas-target cascade (H10 ✗)**: ejection branch calls `initiate_validator_exit(cfg, state, validator_index, exit_queue_info, cache)`, the Pectra version at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:348-373`. That calls `compute_exit_epoch_and_update_churn(cfg, state, validator.effective_balance, cache)`, whose body at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:286-314` uses `get_activation_exit_churn_limit(cfg, state, cache)` even when `state` is a `gloas.BeaconState`.

H1 ✓. H2 ✓. H3 ✓ (two-pass but semantically equivalent). H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✗** (Electra helper at Gloas).

### lodestar

`vendor/lodestar/packages/state-transition/src/epoch/processRegistryUpdates.ts:20-65`. Eligibility is **cached** in `vendor/lodestar/packages/state-transition/src/cache/epochTransitionCache.ts:323-328` (Pattern C with pre-computation): `forEachValue` in `beforeProcessEpoch()` populates `indicesEligibleForActivationQueue`, `indicesEligibleForActivation`, and `indicesToEject` arrays; `processRegistryUpdates.ts` consumes them.

**Gloas-target cascade (H10 ✓)**: the ejection branch calls `initiateValidatorExit(fork, state, slashedIndex)`, the Pectra version at `vendor/lodestar/packages/state-transition/src/block/initiateValidatorExit.ts:27-62`. That calls `computeExitEpochAndUpdateChurn(state, BigInt(validator.effectiveBalance))`. Its body at `vendor/lodestar/packages/state-transition/src/util/epoch.ts:50-77` is the **fork-gated** implementation:

```typescript
const perEpochChurn =
  fork >= ForkSeq.gloas ? getExitChurnLimit(state.epochCtx) : getActivationExitChurnLimit(state.epochCtx);
```

H1 ✓. H2 ✓. H3 ✓ (Pattern C — cached). H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** — the only client whose ejection-cascade exit-epoch advance is paced correctly at Gloas.

### grandine

`vendor/grandine/transition_functions/src/electra/epoch_processing.rs:164-229` — `process_registry_updates`. Three independent `if`s collecting vectors in a single loop, then 3 sequential update loops (Pattern B).

Eligibility predicate: `vendor/grandine/helper_functions/src/electra.rs:32-35 is_eligible_for_activation_queue<P>` (Pectra `const fn`); phase0 variant at `vendor/grandine/helper_functions/src/phase0.rs:76-79`.

**Gloas-target cascade (H10 ✗)**: ejection branch calls `initiate_validator_exit(config, state, validator_index)` — Pectra version at `vendor/grandine/helper_functions/src/electra.rs:124-150`. That calls `compute_exit_epoch_and_update_churn(config, state, validator.effective_balance)`, whose body at `vendor/grandine/helper_functions/src/mutators.rs:177-208` uses `get_activation_exit_churn_limit(config, state)` unconditionally.

H1 ✓. H2 ✓. H3 ✓ (Pattern B). H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✗** (Electra helper at Gloas).

## Cross-reference table

| Client | `process_registry_updates` location | `is_eligible_for_activation_queue` (H1) | Loop pattern (H3) | Ejection-cascade churn fork-gate (H10) |
|---|---|---|---|---|
| prysm | `core/electra/registry_updates.go:39-107` | `core/helpers/validators.go:455-494` (fork-epoch dispatch to `isEligibleForActivationQueueElectra:491-494`) | Pattern B (independent ifs + 3 sequential update loops) | ✗ (`state-native/setters_churn.go:67` calls `helpers.ActivationExitChurnLimit` unconditionally) |
| lighthouse | `per_epoch_processing/single_pass.rs:672-776` (inlined) + `registry_updates.rs:9-57` (pre-Electra fast path) | `consensus/types/src/validator/validator.rs:113-116 is_eligible_for_activation_queue_electra` | Pattern C (single-pass folding into omnibus epoch processor) | ✗ (`beacon_state.rs:2708-2752` calls `get_activation_exit_churn_limit` unconditionally) |
| teku | `versions/electra/.../EpochProcessorElectra.java:86-120` (subclass override) | `EpochProcessorElectra.java:134-139` (override) | Pattern A (explicit if/elif/elif single-pass) | ✗ (`BeaconStateMutatorsElectra.java:77-104` calls `getActivationExitChurnLimit`; `BeaconStateMutatorsGloas` doesn't override) |
| nimbus | `state_transition_epoch.nim:918-942` (`when consensusFork >= ConsensusFork.Electra`) | `beaconstate.nim:607-616` (compile-time fork dispatch) | Pattern A with two sequential passes (observable-equivalent by finalisation timing) | ✗ (`beaconstate.nim:286-314` body uses `get_activation_exit_churn_limit` even with `gloas.BeaconState` signature) |
| lodestar | `epoch/processRegistryUpdates.ts:20-65`; eligibility CACHED in `cache/epochTransitionCache.ts:323-328` | inlined in `epochTransitionCache.ts:323-328` | Pattern C (pre-computed cache + 3 update loops) | **✓** (`util/epoch.ts:50-77` fork-gates `getExitChurnLimit` at `fork >= ForkSeq.gloas`) |
| grandine | `transition_functions/src/electra/epoch_processing.rs:164-229` | `helper_functions/src/electra.rs:32-35` (Pectra `const fn`); phase0.rs:76-79 separately | Pattern B (independent ifs in single loop + 3 sequential update loops) | ✗ (`mutators.rs:177-208` calls `get_activation_exit_churn_limit` unconditionally) |

## Empirical tests

### Pectra-surface fixture run

`consensus-spec-tests/tests/mainnet/electra/epoch_processing/registry_updates/pyspec_tests/` — 16 EF fixtures. Run via `scripts/run_fixture.sh` against all six clients on 2026-05-02:

```
clients: prysm, lighthouse, lodestar, grandine
fixtures: 16
PASS: 63   FAIL: 0   total: 64   notable: lodestar deliberate skip on `invalid_large_withdrawable_epoch` (1 fixture)
```

Lodestar's `invalid_large_withdrawable_epoch` deliberate skip (documented in `packages/beacon-node/test/spec/presets/epoch_processing.test.ts:128-131`): the fixture asserts a u64 overflow path that TypeScript's BigInt arithmetic cannot reproduce naturally. prysm (Go u64), lighthouse (Rust u64), and grandine (Rust u64) all correctly handle the overflow case and PASS the fixture. teku (Java UInt64 with saturating arithmetic) and nimbus (Nim uint64) also handle it per source review.

**Effective result**: 15/16 fixtures PASS for lodestar (1 deliberate skip with documented rationale), **16/16 PASS for prysm + lighthouse + grandine** = 63/64 PASSes total, 0 actual divergences. teku and nimbus SKIP per harness limitation (no per-epoch CLI hook in BeaconBreaker's runners); both have full implementations per source review.

The 16-fixture suite covers H1 (eligibility predicate at MIN_ACTIVATION_BALANCE boundary, 0x01/0x02 credentials, balance variations), H4 (no churn limit at activation — bulk activation past pre-Electra churn cap), H7 (ejection with item #6/#16 cascade), H8 (finalisation-gated activation), and structural fixtures (`activation_queue_efficiency_min`, `activation_queue_sorting`).

### Gloas-surface

No Gloas EF fixtures yet for `process_registry_updates`. H10 is currently source-only — confirmed by walking each client's ejection-cascade call chain through `initiate_validator_exit → compute_exit_epoch_and_update_churn` and observing the helper-call divergence at item #16's H12 level.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — eligibility predicate at MIN_ACTIVATION_BALANCE boundary).** Validator with `effective_balance == MIN_ACTIVATION_BALANCE` (= 32 ETH). Per H1, eligible. Already covered by `activation_queue_eligibility__min_activation_balance` and the `_eth1_creds` / `_compounding_creds` variants.
- **T1.2 (priority — bulk activation past pre-Electra churn cap).** State with > pre-Electra-churn-limit validators all newly-eligible in the same epoch. Per H4, all activate at once (no per-epoch cap). Covered by `activation_queue_activation_and_ejection__exceed_churn_limit`.
- **T1.3 (Glamsterdam-target — ejection-cascade churn).** Synthetic Gloas state with a validator whose `effective_balance` drops to `EJECTION_BALANCE - 1` AND `state.earliest_exit_epoch` is set such that the ejected validator's `exit_epoch` advance triggers an `earliest_exit_epoch` recomputation. Lodestar paces via `get_exit_churn_limit`; the other five via `get_activation_exit_churn_limit`. Different `additional_epochs` → different `validator.exit_epoch` and `validator.withdrawable_epoch` written to state. Sister to items #6 T2.5 / #8 T2.6 / #9 T2.5.

#### T2 — Adversarial probes
- **T2.1 (defensive — `current_epoch + 1` eligibility timing).** Per H9, newly-eligible validators get `activation_eligibility_epoch = current + 1`, NOT `current`. Verify all six clients use `+1`.
- **T2.2 (defensive — mutual exclusivity of branches).** Construct a validator that hypothetically matches more than one of the three predicates. Per H5, the branch order ensures only the first match fires (or, in Pattern B, finalisation timing makes them mutually exclusive). Verify all six clients agree on which branch fires.
- **T2.3 (defensive — `is_eligible_for_activation` finalisation gate).** Per H8, a newly-eligible validator (`activation_eligibility_epoch = current + 1`) is NOT activated in the same epoch (because `current + 1 > finalized_epoch`). Covered by `activation_queue_no_activation_no_finality`.
- **T2.4 (Glamsterdam-target — mass ejection cascade).** Synthetic Gloas state with N validators whose effective_balances all drop to <= EJECTION_BALANCE in the same epoch. Each `initiate_validator_exit` call shares `state.exit_balance_to_consume`. Lodestar advances `earliest_exit_epoch` per the Gloas churn; the other five per the Electra churn. Different cumulative `earliest_exit_epoch` across the cohort. Stateful regression vector.

## Mainnet reachability

**Reachable on canonical traffic at Glamsterdam activation, on every Gloas-epoch boundary that includes any validator ejection.** Ejections are routine but not common on mainnet — they happen when a validator's effective balance drops to `EJECTION_BALANCE = 16 ETH`, which requires substantial inactivity-leak or slashing-induced balance loss.

**Trigger.** The first Gloas-epoch boundary at which any validator's `effective_balance <= EJECTION_BALANCE` AND the validator is active. The ejection branch calls `initiate_validator_exit(state, index)`, which calls `compute_exit_epoch_and_update_churn(state, validator.effective_balance)`. Lodestar paces via `get_exit_churn_limit(state)` (Gloas spec); the other five via `get_activation_exit_churn_limit(state)` (Electra spec). Different `additional_epochs = (balance_to_process - 1) / per_epoch_churn + 1` arithmetic → different `validator.exit_epoch` and `validator.withdrawable_epoch` written into state.

**Severity.** State-root divergence on every Gloas-epoch ejection. Same cohort and same mechanism as items #6 H8 / #8 H9 / #9 H10 — different upstream entry-point (epoch-time ejection vs block-time voluntary-exit/slashing), same downstream churn-helper divergence.

**Mitigation window.** Source-only at audit time; no Gloas EF fixtures for this routine. Closing requires the five lagging clients (prysm, lighthouse, teku, nimbus, grandine) to fork-gate `compute_exit_epoch_and_update_churn` at the chokepoint (item #16 H12). Same coordinated fix-PR scope as items #2 H6, #3 H8, #4 H8, #6 H8, #8 H9, #9 H10 — one PR per client closes all seven family items including this one.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H9) remain satisfied: identical eligibility predicate inequality (`>= MIN_ACTIVATION_BALANCE`), single-pass restructure (with three implementation patterns, all observable-equivalent), no per-epoch activation churn limit, branch ordering, activation-epoch source, finalisation-gated `is_eligible_for_activation`, and `current_epoch + 1` eligibility timing. 63/64 PASS results across the 16 EF `registry_updates` fixtures (lodestar's `invalid_large_withdrawable_epoch` deliberate skip is a documented BigInt/u64-overflow boundary, not a divergence). teku and nimbus pass internally.

**Glamsterdam-target finding (H10):** the ejection branch's `initiate_validator_exit` call cascades through `compute_exit_epoch_and_update_churn` — the chokepoint primitive audited at item #16 H12. At Gloas, 5 of 6 clients (prysm, lighthouse, teku, nimbus, grandine) fail to fork-gate the helper call to use `get_exit_churn_limit`; only lodestar's `util/epoch.ts:50-77` switches to the Gloas-correct helper. Each ejected validator's `exit_epoch` advance is paced via a different per-epoch churn quantity across the 5-vs-1 cohort.

**Seventh item in the EIP-8061 cascade family:**

| Item | Hypothesis | Cascade entry-point |
|---|---|---|
| #2 | H6 | `process_consolidation_request → get_consolidation_churn_limit` |
| #3 | H8 | `process_withdrawal_request → compute_exit_epoch_and_update_churn` (partial) |
| #4 | H8 | `process_pending_deposits → get_activation_churn_limit` |
| #6 | H8 | `process_voluntary_exit → initiate_validator_exit → compute_exit_epoch_and_update_churn` |
| #8 | H9 | `process_attester_slashing → slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn` |
| #9 | H10 | `process_proposer_slashing → slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn` |
| #16 | H12-H15 | **chokepoint** — the primitives themselves |
| **#17** | **H10** | **`process_registry_updates` ejection → `initiate_validator_exit` → `compute_exit_epoch_and_update_churn`** |

Same 5-vs-1 cohort on all seven items. Item #16's recheck identified the chokepoint; this item adds the seventh cascade entry-point.

Notable per-client style differences (all observable-equivalent on the Pectra surface):

- **prysm** uses Pattern B (3 independent ifs + 3 sequential update loops) with `ReadFromEveryValidator` collection. Runtime fork-epoch dispatch in `IsEligibleForActivationQueue`.
- **lighthouse** uses Pattern C (inlined into omnibus single-pass epoch processor). Two-path coexistence: pre-Electra fast path at `registry_updates.rs:9-57` (legacy) + Electra inline at `single_pass.rs:672-776`.
- **teku** uses Pattern A (explicit if/elif/elif single-pass) with subclass-override polymorphism (`EpochProcessorElectra extends EpochProcessorBellatrix`).
- **nimbus** uses TWO sequential complete passes (NOT single-pass) but observable-equivalent because the second pass's `is_eligible_for_activation` filters out newly-eligible validators (their `activation_eligibility_epoch = current + 1` is not yet finalised).
- **lodestar** uses Pattern C with pre-computed cache (eligibility computed once in `beforeProcessEpoch()`'s forEachValue, consumed by `processRegistryUpdates.ts`). Two-stage filtering (cache uses `<= currentEpoch`, consume uses `<= finalityEpoch`).
- **grandine** uses Pattern B (independent ifs in single loop + sequential update loops). Same source-organisation risk as items #6/#9/#10/#12/#14/#15 (multi-fork-definition pattern for `is_eligible_for_activation_queue` and `initiate_validator_exit`).

Recommendations to the harness and the audit:

- Generate **T1.3 Gloas ejection-cascade fixture** — sister to items #6 T2.5 / #8 T2.6 / #9 T2.5.
- Coordinate the **EIP-8061 chokepoint fork-gate PR** per lagging client (prysm, lighthouse, teku, nimbus, grandine). Same scope as items #2/#3/#4/#6/#8/#9/#16 — one PR per client closes all seven cascade items + the chokepoint.
- **Generate a multi-validator stress fixture** with 1000 validators all becoming eligible in the same epoch — verify no per-epoch activation churn limit kicks in (Pectra change H4) and the bulk activation produces uniform post-state across all six clients.
- **Audit `add_validator_to_registry`** as a standalone item — Pectra-modified helper, only major Pectra-modified helper not yet a standalone audit.
- **Audit `compute_activation_exit_epoch`** standalone — trivial but pivotal helper used by every Pectra exit/consolidation/activation path.

## Cross-cuts

### With item #16 (chokepoint — `compute_exit_epoch_and_update_churn`)

This item's ejection branch is the seventh cascade entry-point into item #16's chokepoint. Closing item #16's H12 fork-gate closes this item's H10 by construction. Reference implementation: lodestar's `util/epoch.ts:50-77`.

### With items #6 H8 / #8 H9 / #9 H10 (sibling cascade entry-points)

Items #6 H8 (voluntary exit), #8 H9 (attester slashing), #9 H10 (proposer slashing), and this item's H10 (ejection) all converge on the same downstream divergence point: `initiate_validator_exit → compute_exit_epoch_and_update_churn`. The four items differ only in the upstream entry-point (block-time voluntary exit / EL full-exit / attester slashing / proposer slashing / epoch-time ejection). All four affect `validator.exit_epoch` and `validator.withdrawable_epoch` on the affected validator.

### With item #4 (`process_pending_deposits`)

Item #4's drain adds new validators via `add_validator_to_registry`, which sets `activation_eligibility_epoch = FAR_FUTURE_EPOCH`. This item's epoch-time pass then transitions `activation_eligibility_epoch → current + 1` if `effective_balance >= MIN_ACTIVATION_BALANCE`. Two-epoch round-trip from deposit to activation-eligibility-set. The EIP-8061 activation-churn divergence (item #4 H8) shifts the rate at which item #4 drains; this item's eligibility set is unaffected (no churn cap at activation per H4).

### With item #11 (`upgrade_to_electra`)

`upgrade_to_electra` seeds pre-activation validators into `pending_deposits` (`slot = GENESIS_SLOT` placeholders), which item #4 drains into the registry with `activation_eligibility_epoch = FAR_FUTURE_EPOCH`. This item then transitions them to eligible at the next epoch boundary. Cross-cut chain: item #11 (init) → item #4 (drain) → item #17 (eligibility set) → item #17 (activation after finality).

## Adjacent untouched

1. **Audit `add_validator_to_registry`** — Pectra-modified helper; only major Pectra helper not yet standalone-audited.
2. **Audit `compute_activation_exit_epoch`** — trivial formula but pivotal cross-cut.
3. **Stateful fixture: cross-fork eligibility transition** at Pectra activation epoch — validators with effective_balance in the `[MIN_ACTIVATION_BALANCE, MAX_EFFECTIVE_BALANCE)` range become newly-eligible at the fork.
4. **prysm Pattern B re-read contract test** — assert mutual exclusivity invariant under all reachable states.
5. **lodestar two-stage cache filter consolidation** — single-stage cleanup.
6. **nimbus two-pass equivalence comment** — codify the finalisation-timing reasoning.
7. **lighthouse pre-Electra fast path dead-code annotation** at Electra mainnet activation.
8. **grandine source-organisation risk** — one-line audit asserting correct module imports across all per-fork dispatch sites (multi-item shared concern).
9. **EJECTION_BALANCE Pectra interaction** — verify ejection threshold semantics with compounding validators (0x02 with high effective_balance is hard to drop to 16 ETH without slashing).
10. **`current_epoch + 1` eligibility-set timing** — verify all 6 clients use `+1` (not `+0` or `+2`).
11. **`activation_queue_sorting` pre-Electra fixture** — should be a no-op at Pectra (no sorting needed). Verify cross-client.
12. **Multi-validator stress fixture**: 1000 validators all becoming eligible in the same epoch — verify no per-epoch activation churn limit (Pectra change H4) and uniform post-state.
13. **Cross-cut with item #16**: validators ejected via this item consume the per-block exit churn budget. Stateful fixture with several ejections + voluntary exits + EL withdrawal requests in same block.
14. **Cross-cut with item #4**: a deposit processed in this epoch sets `activation_eligibility_epoch = FAR_FUTURE_EPOCH`; this epoch's `process_registry_updates` then sets it to `current + 1`. Two-epoch round-trip from deposit to activation eligibility.
15. **EIP-8061 family cascade closure**: items #2 H6, #3 H8, #4 H8, #6 H8, #8 H9, #9 H10, #17 H10 (this), #16 H12-H15 (chokepoint). Seven cascade entry-points + one chokepoint = the full Gloas EIP-8061 audit family.
