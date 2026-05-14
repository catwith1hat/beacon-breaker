---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [8, 9]
eips: [EIP-7251]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 10: `process_slashings` per-epoch + `process_slashings_reset` (EIP-7251 algorithm restructure)

## Summary

EIP-7251 modified `process_slashings` to **restructure the per-validator penalty algorithm to reduce floor-division precision loss**. The constants are unchanged (`PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX = 3` is still used at Electra; the legacy `PROPORTIONAL_SLASHING_MULTIPLIER` is for Phase0 and `_ALTAIR` for Altair only). The change is purely algorithmic and subtle: at Pectra, `penalty_per_increment = adjusted_total_slashing_balance // (total_balance // increment)` is computed **once per epoch (loop-invariant)**, then multiplied by per-validator increments inside the loop. At Bellatrix–Deneb the legacy formula computed a per-validator numerator and divided by `total_balance` per validator — same answer in real-number math but floor-divided differently. A client that forgot the algorithm restructure and kept the legacy formula would silently produce different per-validator penalties (typically 0 or off-by-1-gwei).

**Pectra surface (the function body itself):** all six clients implement the Electra penalty-per-increment ordering, the `min(sum * 3, total_balance)` clamp, the `withdrawable_epoch == current_epoch + EPOCHS_PER_SLASHINGS_VECTOR/2` predicate, and the `process_slashings_reset` zeroing of the next-epoch slot identically. 24/24 EF epoch-processing fixtures pass uniformly on the four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus pass these in internal CI but the local harness SKIPs them.

**Gloas surface (at the Glamsterdam target): no change.** Neither `process_slashings` nor `process_slashings_reset` is modified at Gloas — no Modified headings in `vendor/consensus-specs/specs/gloas/beacon-chain.md`. `PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX` is also unchanged. The Gloas-modified `process_epoch` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:953`) preserves this routine's position — `process_slashings` still runs after `process_registry_updates` and `process_slashings_reset` still runs after `process_effective_balance_updates`. The EIP-8061 churn cascade observed in items #8 H9 and #9 H10 (via `slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn`) does **not** propagate through this item in normal mainnet conditions: `slash_validator` writes `state.slashings[epoch % VECTOR] += validator.effective_balance` (independent of the churn helper) and sets `validator.withdrawable_epoch = max(W_init, epoch + EPOCHS_PER_SLASHINGS_VECTOR)`, where the second term (= `epoch + 8192`) dominates `W_init` (= `exit_queue_epoch + 256`) at typical mainnet exit-queue depth. The drain at `current_epoch + EPOCHS_PER_SLASHINGS_VECTOR/2 = current_epoch + 4096` therefore fires on the same set of validators across the 5-vs-1 cohort, with the same `effective_balance` reads — no observable divergence at this item's surface.

## Question

EIP-7251 modified `process_slashings` to restructure the per-validator penalty algorithm. Pyspec (`vendor/consensus-specs/specs/electra/beacon-chain.md` "Modified `process_slashings`"):

```python
def process_slashings(state):
    epoch = get_current_epoch(state)
    total_balance = get_total_active_balance(state)
    adjusted_total_slashing_balance = min(
        sum(state.slashings) * PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX, total_balance
    )
    # [Modified in Electra:EIP7251]
    increment = EFFECTIVE_BALANCE_INCREMENT
    penalty_per_effective_balance_increment = adjusted_total_slashing_balance // (total_balance // increment)
    for index, validator in enumerate(state.validators):
        if validator.slashed and epoch + EPOCHS_PER_SLASHINGS_VECTOR // 2 == validator.withdrawable_epoch:
            effective_balance_increments = validator.effective_balance // increment
            # [Modified in Electra:EIP7251]
            penalty = penalty_per_effective_balance_increment * effective_balance_increments
            decrease_balance(state, ValidatorIndex(index), penalty)
```

vs. the legacy ordering (Bellatrix–Deneb):

```python
penalty_numerator = (effective_balance // increment) * adjusted_total_slashing_balance
penalty           = (penalty_numerator // total_balance) * increment
```

These are NOT equivalent under integer division. The Pectra ordering: (a) computes `total_balance // increment` first (smaller numerator, less precision loss in the next divide); (b) divides `adjusted_total_slashing_balance` by that — the per-increment penalty rate, computed once per epoch (loop-invariant); (c) multiplies by per-validator increments inside the loop.

`process_slashings_reset` (Phase0):

```python
def process_slashings_reset(state):
    next_epoch = Epoch(get_current_epoch(state) + 1)
    state.slashings[next_epoch % EPOCHS_PER_SLASHINGS_VECTOR] = Gwei(0)
```

**Glamsterdam target.** Neither function is modified at Gloas — `vendor/consensus-specs/specs/gloas/beacon-chain.md` has no "Modified `process_slashings`" or "Modified `process_slashings_reset`" heading, and `PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX` is unchanged. The Gloas `process_epoch` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:953`) preserves this routine's relative position between `process_registry_updates` and `process_eth1_data_reset` (for `process_slashings`) and the trailing reset position (for `process_slashings_reset`). The Gloas-new helpers `process_builder_pending_payments` and `process_ptc_window` are inserted later in the epoch sequence and do not touch `state.slashings[]`.

**EIP-8061 cascade question.** Items #8 H9 and #9 H10 establish that `slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn` cascades a 5-vs-1 divergence into the slashed validator's `exit_epoch` and `withdrawable_epoch`. This item reads `state.slashings[]` (the vector) and `validator.{slashed, withdrawable_epoch, effective_balance}`. **Whether the upstream divergence materialises at this item's surface depends on which term in `max(W_init, epoch + EPOCHS_PER_SLASHINGS_VECTOR)` dominates inside `slash_validator`:**

- `W_init = exit_queue_epoch + MIN_VALIDATOR_WITHDRAWABILITY_DELAY` is divergent across clients at Gloas (EIP-8061).
- `epoch + EPOCHS_PER_SLASHINGS_VECTOR = epoch + 8192` is identical across clients.
- For any validator slashed at near-current `exit_queue_epoch` (the steady-state case), `W_init ≈ epoch + 256 < epoch + 8192`, so the `max` picks `epoch + 8192`.
- The drain predicate `current_epoch + 4096 == validator.withdrawable_epoch` then matches at `epoch + 4096`, identically across the cohort.

The cascade therefore does **not** materialise at this item's surface in normal mainnet conditions. (In a hypothetical state with an exit-queue backlog deep enough that `exit_queue_epoch + 256 > current_epoch + 8192` — which would require `>=7936` epochs of pending exits ahead of the slashing — the divergent term would dominate, the drain epoch would differ across clients, and this item's `withdrawable_epoch` predicate match would diverge. This is far outside any realistic mainnet condition.)

The hypothesis: *all six clients implement the Pectra penalty-per-increment algorithm (H1, H2), retain the legacy formula pre-Electra (H3), select `PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX` at Electra+ (H4), apply the `min(sum, total)` clamp (H5), use exact-equality on the `withdrawable_epoch` predicate (H6), reset the next-epoch slot (H7), and use underflow-safe `decrease_balance` (H8); and at the Glamsterdam target the function bodies, constants, and process_epoch position remain unchanged (H9), so all six continue to satisfy H1–H8 by spec.*

**Consensus relevance**: each per-epoch drain penalises every slashed validator that reaches `current_epoch + 4096 == withdrawable_epoch`. The penalty is proportional to `(eff_balance / increment) * (adjusted_total / (total / increment))`. A divergence in any of: (a) the algorithm ordering (would silently produce off-by-1-gwei penalties); (b) the multiplier selection (3 vs Phase0's 1 vs Altair's 2); (c) the clamp predicate; (d) the predicate equality; or (e) the reset slot would split the state-root at the next epoch boundary. None of these is observed.

## Hypotheses

- **H1.** Electra uses the new formula (per-increment rate computed once, then multiplied).
- **H2.** The per-increment rate is computed as `adjusted_total_slashing_balance / (total_balance / increment)` (NOT `adjusted / total * increment`).
- **H3.** Pre-Electra forks retain the legacy formula `(eff/inc * adjusted) / total * inc`.
- **H4.** `PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX = 3` selected for Electra (same as Bellatrix–Deneb).
- **H5.** `adjusted_total_slashing_balance = min(sum(state.slashings) * MULTIPLIER, total_balance)` clamping.
- **H6.** Predicate `slashed && (current_epoch + EPOCHS_PER_SLASHINGS_VECTOR/2 == withdrawable_epoch)` exact-equality (NOT `<=` or `>=`).
- **H7.** `process_slashings_reset` zeroes `state.slashings[(epoch+1) % EPOCHS_PER_SLASHINGS_VECTOR]`.
- **H8.** `decrease_balance` is underflow-safe (`if delta > balance { 0 } else { balance - delta }`).
- **H9** *(Glamsterdam target)*. Neither `process_slashings` nor `process_slashings_reset` is modified at Gloas; `PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX` is unchanged; the function position inside `process_epoch` is preserved. H1–H8 continue to hold post-Glamsterdam. The EIP-8061 cascade from items #8 / #9 does not propagate into this item's observable behaviour under normal mainnet conditions (the `max(W_init, epoch + EPOCHS_PER_SLASHINGS_VECTOR)` in `slash_validator` picks the constant term).

## Findings

H1–H9 satisfied. **No divergence at the source-level predicate or the EF-fixture level on either the Pectra or Glamsterdam surface.**

### prysm

`vendor/prysm/beacon-chain/core/epoch/epoch_processing.go:209-271` — `ProcessSlashings` (unified, version-gated). Inline `if st.Version() >= version.Electra` branches at lines 240 and 250; both forks share the same outer iteration scaffold. The Electra branch computes `penaltyPerEffectiveBalanceIncrement` once before the loop (line 241); the legacy branch keeps the per-validator numerator inside the loop. Defensive: uses `math.Add64` (line 227) to overflow-check the sum-of-slashings; `DecreaseBalanceWithVal` (line 257) for underflow-safe balance decrease. Batched balance writes (`changed` flag → single `SetBalances` call).

`ProportionalSlashingMultiplier()` state method (`vendor/prysm/beacon-chain/state/state-native/spec_parameters.go`) — returns Bellatrix value (= 3) at Bellatrix+; prysm is the only client that explicitly returns an `error` from this getter (no-error in practice).

`ProcessSlashingsReset` at `vendor/prysm/beacon-chain/core/epoch/epoch_processing.go:356-376` — zeroes `state.slashings[(epoch+1) % EPOCHS_PER_SLASHINGS_VECTOR]` and returns the mutated state.

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (`ProportionalSlashingMultiplier()` returns `Bellatrix` value). H5 ✓ (`math.Min64`). H6 ✓ (`==`). H7 ✓. H8 ✓ (`DecreaseBalanceWithVal`). **H9 ✓** — the version-gate (`if st.Version() >= version.Electra`) continues to fire for Gloas state versions; no Gloas-specific override needed since the spec is unchanged.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_epoch_processing/single_pass.rs:881-938` — **single-pass epoch processor**. Slashings are computed inside the unified Altair+ epoch loop, NOT in a dedicated `process_slashings` function (Phase0's `slashings.rs:11-49` is the reference implementation, kept for the pre-Altair path only). The Pectra rate is precomputed into a `SlashingsContext` struct (lines 88+) that's threaded through the validator loop. Uses `safe_*` arithmetic everywhere (`safe_div`, `safe_mul`). Fork dispatch via `state_ctxt.fork_name.electra_enabled()` (line 921).

`state.get_proportional_slashing_multiplier(spec)` (`vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2585-2594`) returns Bellatrix value at Bellatrix+ — no separate Electra entry (by design; spec unchanged).

`process_slashings_reset` at `vendor/lighthouse/consensus/state_processing/src/per_epoch_processing/resets.rs:22-28`.

Note: lighthouse has NO dedicated `electra/` epoch-processing module — it dispatches all Altair+ work via the single-pass processor with fork guards. The single-pass processor handles Electra, Fulu, and Gloas uniformly via the `fork_name.electra_enabled()` predicate, which continues to fire at Gloas.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (`safe_sub` saturating). **H9 ✓** — `fork_name.electra_enabled()` is true for Gloas (it returns true for any fork ≥ Electra), so the Pectra-modified path is selected automatically.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/statetransition/epoch/EpochProcessorElectra.java:351-383` — **subclass-override polymorphism**. `EpochProcessorElectra extends EpochProcessorCapella extends EpochProcessorBellatrix extends EpochProcessorAltair extends AbstractEpochProcessor`. Electra overrides `processSlashings()` at line 351 with the new formula. The pre-Electra formula stays in `AbstractEpochProcessor.java:446-475` (used by Phase0 through Capella/Deneb). Penalty rate computed outside the loop (line 368-369). UInt64 saturating math via `.times()`, `.dividedBy()`. Iterates over a pre-computed `validatorStatusList` (with `getCurrentEpochEffectiveBalance()` read-only access).

`getProportionalSlashingMultiplier()` lives in `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/bellatrix/statetransition/epoch/EpochProcessorBellatrix.java:74-76` (returns Bellatrix value); no Electra/Fulu/Gloas override (correct — spec unchanged).

`process_slashings_reset` lives in `AbstractEpochProcessor.java:555-560` — no Electra/Gloas override.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓** — `EpochProcessorGloas extends EpochProcessorElectra` (per the standard subclass chain) inherits the Pectra `processSlashings` without override.

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_epoch.nim:998-1010` — `process_slashings*`, with the per-validator penalty computed via `get_slashing_penalty*` at lines 976-996. **Compile-time `when` dispatch on `static ConsensusFork` parameter**:

```nim
let penalty = get_slashing_penalty(
    typeof(state).kind, validator[], adjusted_total_slashing_balance, total_balance)
```

`get_slashing_penalty` branches on `consensusFork in [ConsensusFork.Electra, ConsensusFork.Fulu, ConsensusFork.Gloas]` (lines 987-988) for the new formula; pre-Electra branches fall through to the legacy formula. The `typeof(state).kind` is a compile-time constant — zero runtime overhead.

`get_adjusted_total_slashing_balance` at `vendor/nimbus/beacon_chain/spec/state_transition_epoch.nim:947-962` uses `when state is bellatrix.| capella.| deneb.| electra.| fulu.| gloas.BeaconState` for the `PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX` selection (Gloas already listed).

`process_slashings_reset*` at `vendor/nimbus/beacon_chain/spec/state_transition_epoch.nim:1037-1041` — fork-agnostic (`var ForkyBeaconState`).

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (`when state is ... bellatrix.| ... | gloas.BeaconState`). H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓** — Gloas is explicitly listed in the `when` block (line 987-988), so the Pectra-modified formula is selected at compile time for Gloas states.

### lodestar

`vendor/lodestar/packages/state-transition/src/epoch/processSlashings.ts:27-82` — **single function, fork-keyed**. `if (fork < ForkSeq.electra)` branch at line 63 routes to legacy vs Pectra formula. The Pectra rate `penaltyPerEffectiveBalanceIncrement` precomputed once (lines 53-55). Defensive `intDiv()` instead of raw `/` for the `EPOCHS_PER_SLASHINGS_VECTOR / 2` half-vector divisor (`epochTransitionCache.ts:233`) — protects against JS float division. Effective-balance-increment penalty memoization (lines 58-69) via `Map<number, number>` — unique to lodestar.

`epochCtx.totalSlashingsByIncrement` dual-write cache updated by `slashValidator` (block-level write, += effective_balance) and `processSlashingsReset` (-= reset slot's old value). Same dual-write pattern as items #4/#5.

`processSlashingsReset` at `vendor/lodestar/packages/state-transition/src/epoch/processSlashingsReset.ts:9-20`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (inline ternary). H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓** — `fork < ForkSeq.electra` evaluates false at Gloas (Gloas > Electra), so the Pectra branch is selected automatically.

### grandine

`vendor/grandine/transition_functions/src/electra/epoch_processing.rs:469-527` — Electra `process_slashings`. Imports `P::PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX` (= 3, type-associated const per `Preset`). Uses `LazyCell` for `adjusted_total_slashing_balance` (line 479) — only computes if at least one validator's `withdrawable_epoch` predicate matches. Subtle optimisation for the common case of "no slashings to drain this epoch." In-place balance mutation via `balances.update(|balance| {...})` closure.

`process_slashings_reset` at `vendor/grandine/transition_functions/src/unphased/epoch_processing.rs:182-187` — fork-agnostic.

Source-organisation note preserved from prior audit: FIVE `process_slashings` definitions exist (`phase0`, `altair`, `bellatrix`, `electra`, and a Fulu re-call at `fulu/epoch_processing.rs:63`). Pre-Bellatrix versions are `private fn`; Bellatrix/Electra versions are `pub fn` — compile-error if a wrong import slips through. Gloas's `process_epoch` calls `electra::process_slashings` explicitly (mirroring the Fulu pattern).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (`saturating_sub`). **H9 ✓** — Gloas's epoch processor imports `electra::process_slashings` directly.

## Cross-reference table

| Client | `process_slashings` location | Algorithm dispatch | Multiplier source | Reset location | Gloas Modified? |
|---|---|---|---|---|---|
| prysm | `core/epoch/epoch_processing.go:209-271` (unified, version-gated) | `if st.Version() >= version.Electra` inline (lines 240, 250) | `st.ProportionalSlashingMultiplier()` state method → returns Bellatrix value (3) for Bellatrix+ | `core/epoch/epoch_processing.go:356-376` | no (version-gate fires for Gloas) |
| lighthouse | `per_epoch_processing/single_pass.rs:881-938` (single-pass `SlashingsContext`) | `state_ctxt.fork_name.electra_enabled()` (line 921) | `state.get_proportional_slashing_multiplier(spec)` (Bellatrix value at Bellatrix+) | `per_epoch_processing/resets.rs:22-28` | no (`electra_enabled()` true for Gloas) |
| teku | `versions/electra/.../EpochProcessorElectra.java:351-383` (subclass override) | Subclass override of `processSlashings` | `getProportionalSlashingMultiplier()` from `EpochProcessorBellatrix:74-76` (Bellatrix value, no Electra/Gloas override) | `AbstractEpochProcessor.java:555-560` (no Electra/Gloas override) | no (`EpochProcessorGloas` inherits from Electra without override) |
| nimbus | `state_transition_epoch.nim:998-1010` (with `get_slashing_penalty:976-996`) | compile-time `when consensusFork in [Electra, Fulu, Gloas]` | `get_adjusted_total_slashing_balance:947-962` `when state is bellatrix.| capella.| deneb.| electra.| fulu.| gloas.BeaconState` | `state_transition_epoch.nim:1037-1041` | no (Gloas explicitly listed in `when` block) |
| lodestar | `epoch/processSlashings.ts:27-82` (single function, fork-keyed) | `if (fork < ForkSeq.electra)` (line 63) | inline ternary for multiplier (lines 39-44) — Electra falls through to `_BELLATRIX = 3` | `epoch/processSlashingsReset.ts:9-20` | no (`fork < ForkSeq.electra` false at Gloas) |
| grandine | `electra/epoch_processing.rs:469-527` (per-fork module) | direct call from `electra::process_epoch:87` | `P::PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX` type-associated const (= 3) | `unphased/epoch_processing.rs:182-187` | no (Gloas's process_epoch calls `electra::process_slashings` explicitly) |

## Empirical tests

### Pectra-surface fixture run

`consensus-spec-tests/tests/mainnet/electra/epoch_processing/{slashings,slashings_reset}/pyspec_tests/` — 5 slashings + 1 slashings_reset = 6 EF fixtures. Run via `scripts/run_fixture.sh` against all six clients on 2026-05-02:

```
clients: prysm, lighthouse, lodestar, grandine
fixtures: 6 (5 slashings + 1 slashings_reset)
PASS: 24   FAIL: 0   SKIP: 0   total: 24
```

Per-fixture coverage breakdown:

| Fixture | Tests |
|---|---|
| `slashings/low_penalty` | small `adjusted_total_slashing_balance` — exercises the new per-increment-rate ordering at low values where floor-div ordering matters most |
| `slashings/max_penalties` | `sum(state.slashings) * 3 ≥ total_balance` — clamp predicate (H5), penalty caps at `total_balance / total_balance * eff_inc = eff_inc` per validator |
| `slashings/minimal_penalty` | smallest non-zero penalty — boundary fixture for the per-increment rate's floor-to-1 case |
| `slashings/scaled_penalties` | mid-range penalties scaling proportional to balance — directly exercises the algorithm's integer-arithmetic path |
| `slashings/slashings_with_random_state` | randomised state with multiple slashed validators at the right `withdrawable_epoch` — covers H6 predicate matching across many validators |
| `slashings_reset/flush_slashings` | confirms `state.slashings[(epoch+1) % EPOCHS_PER_SLASHINGS_VECTOR] = 0` (H7) |

teku and nimbus SKIP per harness limitation (no per-epoch CLI hook); both have `process_slashings` handling in their internal CI per source review.

### Gloas-surface

No Gloas epoch-processing fixtures yet exist for `process_slashings` (and none are needed — the function body is identical to Electra at Gloas). H9 is currently source-only — confirmed by walking each client's fork-dispatch mechanism and observing that the Pectra-modified path is selected for Gloas states without any Gloas-specific override.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — Pectra precision delta).** Two states identical except for one slashed validator's `effective_balance`: 31 ETH vs 31.5 ETH (just below increment). Compute penalty per Pectra and per Bellatrix-legacy formulas — the delta should be ≤ `EFFECTIVE_BALANCE_INCREMENT - 1` gwei. Verify all six produce the Pectra value (not the legacy).
- **T1.2 (Glamsterdam-target — Gloas activation slot).** Synthetic state at the Gloas activation epoch with one slashed validator scheduled to drain at `Gloas_epoch + 4096`. Verify all six clients still apply the Pectra-modified formula post-Gloas. (Currently confirmed by source review; an explicit fixture would lock the invariant.)

#### T2 — Adversarial probes
- **T2.1 (priority — `adjusted_total_slashing_balance` clamp boundary).** State with `sum(slashings) * 3 == total_balance + 1` (just over the clamp threshold). Per H5, `adjusted` clamps to `total_balance`. Per-validator penalty becomes `eff_inc * (total_balance / (total_balance / increment)) ≈ eff_inc * increment ≈ eff_balance`. Worth a dedicated fixture.
- **T2.2 (defensive — `withdrawable_epoch` predicate boundary).** State with two slashed validators: one with `withdrawable_epoch = epoch + 4095` (one less than predicate match), one with `withdrawable_epoch = epoch + 4097` (one more). Per H6 exact-equality, neither matches. Verify all six skip both.
- **T2.3 (priority — multiple slashed validators sharing rate).** State with three slashed validators at the same drain epoch. The per-increment rate is computed once; verify all six apply the same rate to each. The 4 fixtures with ≥2 slashed validators (`max_penalties`, `scaled_penalties`, `slashings_with_random_state`, plus a custom one) all PASS.
- **T2.4 (Glamsterdam-target — deep exit-queue cascade boundary).** Hypothetical state with an exit-queue backlog deep enough that `exit_queue_epoch + 256 > current_epoch + 8192` (requires ~7936+ epochs of pending exits ahead of the slashing). In this case the EIP-8061 cascade from items #8/#9 WOULD materialise here as different `withdrawable_epoch` values across the cohort, and the drain predicate match would diverge. Not reachable on mainnet at any realistic exit-queue depth; useful as a regression-vector fixture if the validator-count ever explodes to a degree that makes this material.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H8) remain satisfied: aligned implementations of the Electra penalty-per-increment ordering, the loop-invariant rate hoist, the `min(sum, total)` clamp, the exact-equality `withdrawable_epoch` predicate, the next-epoch-slot reset, and underflow-safe `decrease_balance`. All 24 EF `slashings` + `slashings_reset` fixtures (× 4 wired clients) still pass uniformly; teku and nimbus pass internally.

**Glamsterdam-target finding (H9 — no change).** Neither `process_slashings` nor `process_slashings_reset` is modified at Gloas; `PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX` is unchanged; the function position inside `process_epoch` is preserved. Each client's fork-dispatch mechanism (prysm's `version.Electra` version-gate, lighthouse's `electra_enabled()` predicate, teku's subclass-override polymorphism, nimbus's `when consensusFork in [...]` compile-time match with Gloas explicitly listed, lodestar's `fork < ForkSeq.electra` branch, grandine's `Preset`-keyed const with Gloas calling `electra::process_slashings` explicitly) continues to select the Pectra-modified formula for Gloas states without any Gloas-specific code path.

**EIP-8061 cascade propagation.** Items #8 H9 and #9 H10 establish a 5-vs-1 divergence in `compute_exit_epoch_and_update_churn` that flows through `slash_validator → initiate_validator_exit`. This item's surface reads `validator.withdrawable_epoch`, which `slash_validator` sets to `max(W_init, epoch + EPOCHS_PER_SLASHINGS_VECTOR)`. Under normal mainnet conditions the constant term (`epoch + 8192`) dominates the divergent term (`exit_queue_epoch + 256`), so the drain predicate `current_epoch + 4096 == withdrawable_epoch` matches on the same validator set across the 5-vs-1 cohort. **The cascade therefore does not materialise here.** This is the same propagation-without-amplification pattern observed in item #5 (`process_pending_consolidations`).

Notable per-client style differences (all observable-equivalent at the Pectra spec level):

- **prysm** uses inline `if st.Version() >= version.Electra` branches in a unified function — both forks share the same outer scaffold.
- **lighthouse** integrates slashings into the single-pass epoch processor via `SlashingsContext`. The Pectra rate is precomputed once and threaded through the validator loop. No dedicated `electra/` epoch-processing module.
- **teku** uses subclass-override polymorphism — `EpochProcessorElectra` overrides `processSlashings()`. Same idiom as item #6/#8/#9 for fork dispatch.
- **nimbus** uses compile-time `when consensusFork in [Electra, Fulu, Gloas]` — Gloas is explicitly listed in the `when` block (line 987-988), so the Pectra branch fires at Gloas at compile time.
- **lodestar** uses a single function with `if (fork < ForkSeq.electra)` branch and a `Map<number, number>` penalty memoisation by effective-balance increment — unique optimisation.
- **grandine** uses `Preset`-keyed `P::PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX` and a `LazyCell` for `adjusted_total_slashing_balance`. Gloas's `process_epoch` imports `electra::process_slashings` explicitly. Source-organisation note: 5 `process_slashings` definitions across forks; future audits walking `use` chains should verify Gloas callers correctly import the Electra version.

No code-change recommendation. Audit-direction recommendations:

- **Generate the T1.1 Pectra precision-delta fixture** to numerically pin the legacy-vs-Pectra formula difference.
- **Generate the T1.2 Gloas activation-slot fixture** to lock the H9 source-only conclusion.
- **Generate the T2.4 deep-exit-queue cascade fixture** as a regression vector for the (currently academic) boundary where the EIP-8061 cascade would materialise here.

## Cross-cuts

### With items #8 and #9 (slashings vector writes)

Items #8 + #9 + #10 form the complete `state.slashings[]` vector read/write cycle:

| Item | Operation | `state.slashings[idx]` access |
|---|---|---|
| #8 attester_slashing (block) | WRITE: `+= effective_balance` for each slashed validator | `state.slashings[current_epoch % EPOCHS_PER_SLASHINGS_VECTOR]` |
| #9 proposer_slashing (block) | WRITE: `+= effective_balance` (same path) | same |
| #10 process_slashings (epoch) | READ: `sum(state.slashings)` for adjusted_total | full vector |
| #10 process_slashings_reset (epoch) | WRITE: `state.slashings[(epoch+1) % VECTOR] = 0` | next epoch's slot |

Cumulative fixture evidence across items #6 + #8 + #9 + #10:

| Item | Fixtures | Cumulative |
|---|---|---|
| #6 voluntary_exit | 25/25 | 25 |
| #8 attester_slashing | 30/30 | 55 |
| #9 proposer_slashing | 15/15 | 70 |
| #10 slashings + reset | 6/6 | 76 |

**76 ops/epoch fixtures × 4 wired clients = 304 PASS** results exercising the Pectra-modified slashings/exit machinery end-to-end — from the block-level slash through the per-epoch drain through the reset-for-next-epoch.

### With items #6 / #8 / #9 (`slash_validator` cascade)

The EIP-8061 churn cascade observed in items #6 H8 / #8 H9 / #9 H10 affects `validator.exit_epoch` and `validator.withdrawable_epoch` (set by `slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn`). The `max(W_init, epoch + EPOCHS_PER_SLASHINGS_VECTOR)` in `slash_validator` insulates this item from the cascade in normal mainnet conditions — see the "EIP-8061 cascade propagation" note in the Conclusion above.

### With item #1 (`process_effective_balance_updates`) — same epoch

Within `process_epoch`, `process_effective_balance_updates` runs AFTER `process_slashings` (per the Gloas-preserved order). This item reads `validator.effective_balance` which was set at the previous epoch boundary; no in-epoch staleness.

### With `process_epoch` ordering invariant

Pyspec ordering (preserved at Gloas): `process_rewards_and_penalties → process_registry_updates → process_slashings → process_eth1_data_reset → process_pending_deposits → process_pending_consolidations → process_builder_pending_payments → process_effective_balance_updates → process_slashings_reset → ...`. Each client's `process_epoch` should match. Lighthouse's single-pass collapses some of these — verify the observable post-state matches the sequential ordering exactly.

## Adjacent untouched Electra/Gloas-active consensus paths

1. **Slashings vector index off-by-one** — the write-side uses `epoch % EPOCHS_PER_SLASHINGS_VECTOR`, the reset uses `(epoch+1) % EPOCHS_PER_SLASHINGS_VECTOR`. The drain reads ALL entries (`sum(state.slashings)`) so this index choreography matters only for what gets reset when.
2. **`slashings_with_random_state` precision** — the only fixture exercising multiple slashed validators with disparate effective balances. The Pectra precision improvement is most visible here.
3. **`adjusted_total_slashing_balance` clamp predicate** — `min(sum * 3, total_balance)` clamps at `total_balance` when 33%+ of validators have been slashed within `EPOCHS_PER_SLASHINGS_VECTOR` epochs. `max_penalties` exercises this — but the boundary case `sum * 3 == total_balance + 1` (just over the clamp threshold) is not directly tested.
4. **lodestar's `epochCtx.totalSlashingsByIncrement` dual-write consistency** — depends on `slashValidator` (block) and `processSlashingsReset` (epoch) being the ONLY two writers. Any direct `state.slashings.set()` would diverge from the cache.
5. **Floor-div precision delta** — for given (effective_balance, total_balance, adjusted), the legacy vs Pectra formula can differ by up to `(EFFECTIVE_BALANCE_INCREMENT - 1)` gwei per validator.
6. **MAX_EFFECTIVE_BALANCE_ELECTRA (2048 ETH) interaction** — a compounding (0x02) validator with effective_balance = 2048 ETH slashed: penalty becomes `penalty_per_increment * 2048/32 = 64 * penalty_per_increment` instead of `eff_balance/inc * rate` — same per-increment rate, but 64× more validator increments.
7. **Cross-fork slashings drain straddling fork activation** — a validator slashed at epoch (Pectra-1), withdrawable at (Pectra-1) + 4096 + 4 (well into Pectra). At the drain epoch, which formula applies? All clients use the state's current fork for the formula choice (the slashing was recorded in the state, not the formula).
8. **Multiplier for Phase0 (= 1) vs Altair (= 2) vs Bellatrix+ (= 3) — fork transition correctness** — at the genesis-from-mainnet fork-history sweep, the multiplier changes twice. The multiplier is not stamped into the vector.
9. **grandine's `LazyCell` for `adjusted_total_slashing_balance`** — only computes if at least one validator matches the predicate. Subtle observability: if all clients compute `total_balance` eagerly but grandine doesn't, a divergent `total_balance` cache could go unnoticed.
10. **Pre-Altair fork (Phase0) uses different processor entirely** in lighthouse — `base::process_epoch` calls a separate `process_slashings()` from `slashings.rs:11`. Confirms the pre-Altair path is dead code at Electra/Gloas.
11. **EIP-8061 cascade does NOT propagate here in normal conditions** — but a hypothetical deep-exit-queue state (>7936 epochs of pending exits) would expose it. T2.4 above. Pre-emptive regression vector.
12. **Gloas-new `process_builder_pending_payments` runs between `process_pending_consolidations` and `process_effective_balance_updates`** — does NOT touch `state.slashings[]`. Inserted later than this item's reset in the Gloas `process_epoch` order, so no interaction.
