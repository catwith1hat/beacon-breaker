# Item #10 — `process_slashings` per-epoch + `process_slashings_reset` (EIP-7251 algorithm restructure)

**Status:** no-divergence-pending-fuzzing — audited 2026-05-02. Per-epoch
slashings drain; **closes the slashings-vector cycle** started by item
#8 (`process_attester_slashing`) and item #9 (`process_proposer_slashing`)
which write into `state.slashings[epoch % EPOCHS_PER_SLASHINGS_VECTOR]`.

## Why this item

EIP-7251 modified `process_slashings` to **restructure the per-validator
penalty algorithm to reduce floor-division precision loss**. The
constants are unchanged (`PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX = 3`
is still used at Electra; the legacy `PROPORTIONAL_SLASHING_MULTIPLIER`
is for Phase0 and `_ALTAIR` for Altair only). The change is purely
algorithmic and subtle:

```
# Pre-Electra (Bellatrix–Deneb):
penalty_numerator = (effective_balance // increment) * adjusted_total_slashing_balance
penalty           = (penalty_numerator // total_balance) * increment

# Electra (NEW):
penalty_per_increment = adjusted_total_slashing_balance // (total_balance // increment)
penalty               = penalty_per_increment * (effective_balance // increment)
```

These are NOT equivalent under integer division. The Pectra ordering:
1. Computes `total_balance // increment` first (smaller numerator, less
   precision loss in the next divide).
2. Divides `adjusted_total_slashing_balance` by that — **this is the
   per-increment penalty rate, computed once per epoch** (loop-invariant).
3. Multiplies by per-validator increments inside the loop.

The legacy ordering computed a per-validator numerator
(`effective_balance/inc * adjusted_total_slashing_balance`) and divided
by `total_balance` per validator — same answer in real-number math, but
floor-divided differently. The Pectra version also factors out the
loop-invariant rate, which is a measurable optimization for the
slashings drain.

A client that forgot the algorithm restructure and kept the legacy
formula would silently produce **different per-validator penalties** —
typically 0 or off-by-1-gwei differences, depending on the
balance/total ratio. This is a textbook subtle divergence vector.

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | Electra uses the new formula (per-increment rate computed once, then multiplied) | ✅ all 6 |
| H2 | The per-increment rate is computed as `adjusted_total_slashing_balance / (total_balance / increment)` (NOT `adjusted / total * increment`) | ✅ all 6 |
| H3 | Pre-Electra forks retain the legacy formula (`(eff/inc * adjusted) / total * inc`) | ✅ all 6 |
| H4 | `PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX = 3` selected for Electra (same as Bellatrix–Deneb) | ✅ all 6 |
| H5 | `adjusted_total_slashing_balance = min(sum(state.slashings) * MULTIPLIER, total_balance)` clamping | ✅ all 6 |
| H6 | Predicate `slashed && (current_epoch + EPOCHS_PER_SLASHINGS_VECTOR/2 == withdrawable_epoch)` exact-equality (NOT `<=` or `>=`) | ✅ all 6 |
| H7 | `process_slashings_reset` zeroes `state.slashings[(epoch+1) % EPOCHS_PER_SLASHINGS_VECTOR]` | ✅ all 6 |
| H8 | `decrease_balance` is underflow-safe (`if delta > balance { 0 } else { balance - delta }`) | ✅ all 6 |

## Per-client cross-reference

| Client | `process_slashings` location | Algorithm dispatch | Multiplier source | Reset location |
|---|---|---|---|---|
| **prysm** | `core/epoch/epoch_processing.go:209–271` (unified, version-gated) | `if st.Version() >= version.Electra` inline (line 240, 250) | `st.ProportionalSlashingMultiplier()` state method → returns Bellatrix value (3) for Bellatrix+ | `core/epoch/epoch_processing.go:356–376` |
| **lighthouse** | `per_epoch_processing/single_pass.rs:881–938` (single-pass `SlashingsContext`) | `if state_ctxt.fork_name.electra_enabled()` (line 921) | `state.get_proportional_slashing_multiplier(spec)` (returns Bellatrix value at Bellatrix+) | `per_epoch_processing/resets.rs:22–28` |
| **teku** | `versions/electra/.../EpochProcessorElectra.java:351–383` (subclass override) | Subclass override of `processSlashings` | `getProportionalSlashingMultiplier()` from `EpochProcessorBellatrix:74–76` (Bellatrix value, no Electra override) | `AbstractEpochProcessor.java:555–560` (no Electra override) |
| **nimbus** | `state_transition_epoch.nim:998–1010` (with `get_slashing_penalty:976–996`) | `static when consensusFork in [Electra, Fulu, Gloas]` compile-time | `get_adjusted_total_slashing_balance:947–962` `when state is bellatrix.\| capella.\| deneb.\| electra.\| fulu.\| gloas.BeaconState` | `state_transition_epoch.nim:1037–1041` |
| **lodestar** | `epoch/processSlashings.ts:27–82` (single function, fork-keyed) | `if (fork < ForkSeq.electra)` (line 63) | Inline ternary for multiplier (line 39–44) — Electra falls through to `_BELLATRIX = 3` | `epoch/processSlashingsReset.ts:9–20` |
| **grandine** | `electra/epoch_processing.rs:469–527` (per-fork module) | Direct call from `electra::process_epoch:87` | `P::PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX` type-associated const (= 3) | `unphased/epoch_processing.rs:182–187` |

## EF fixture results — 24/24 PASS

Ran 5 EF mainnet/electra/epoch_processing/slashings + 1 slashings_reset
fixtures across the 4 wired clients via `scripts/run_fixture.sh`:

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
| `slashings/slashings_with_random_state` | randomized state with multiple slashed validators at the right `withdrawable_epoch` — covers H6 predicate matching across many validators |
| `slashings_reset/flush_slashings` | confirms `state.slashings[(epoch+1) % EPOCHS_PER_SLASHINGS_VECTOR] = 0` (H7) |

teku and nimbus SKIP per harness limitation (no per-epoch CLI hook in
BeaconBreaker's runners). Both have `process_slashings` handling in
their internal CI per source review.

## Notable per-client styles

### prysm
**Unified single-function dispatch** in `ProcessSlashings` with inline
`if st.Version() >= version.Electra` branches at lines 240 and 250 —
both forks share the same outer iteration scaffold. The Electra branch
computes `penaltyPerEffectiveBalanceIncrement` once before the loop
(line 241), the legacy branch keeps the per-validator numerator inside
the loop. Defensive: uses `math.Add64` (line 227) to overflow-check the
sum-of-slashings; `DecreaseBalanceWithVal` (line 257) for
underflow-safe balance decrease. Batched balance writes (`changed`
flag → single `SetBalances` call) — slight asymmetry vs other clients
that mutate per-validator. Multiplier dispatch via state method
`ProportionalSlashingMultiplier()` (`state-native/spec_parameters.go`),
correctly returns Bellatrix value at Bellatrix+ — **prysm is also the
only client that explicitly returns an `error` from this getter**
(no-error in practice but visible in the type signature).

### lighthouse
**Single-pass epoch processor** — slashings are computed inside the
unified Altair+ epoch loop in `single_pass.rs`, NOT in a dedicated
`process_slashings` function (Phase0's `slashings.rs:11–49` is the
reference implementation, kept for the pre-Altair path only). The
Pectra rate is precomputed into a `SlashingsContext` struct (line
882–908) that's threaded through the validator loop. Uses `safe_*`
arithmetic everywhere (`safe_div`, `safe_mul`) — overflow-checked via
the `SafeArith` trait. Fork dispatch via
`state_ctxt.fork_name.electra_enabled()` (line 921) — same idiom as
items #8/#9 (`get_min_slashing_penalty_quotient` etc). Multiplier via
state method `state.get_proportional_slashing_multiplier(spec)`
(`beacon_state.rs:2585–2594`) — returns Bellatrix value for Bellatrix+
(no separate Electra entry, by design). **Crucially: lighthouse has
NO dedicated `electra/` epoch-processing module** — it dispatches all
Altair+ work via the single-pass processor with fork guards.

### teku
**Subclass-override polymorphism** — `EpochProcessorElectra extends
EpochProcessorCapella extends EpochProcessorBellatrix extends
EpochProcessorAltair extends AbstractEpochProcessor`. Electra overrides
`processSlashings()` at line 351 with the new formula. The pre-Electra
formula stays in `AbstractEpochProcessor.java:446–475` (used by Phase0
through Capella/Deneb). Same idiom as item #8/#9's
`BeaconStateMutatorsElectra` for the slashing quotients. Penalty rate
computed outside the loop (line 368–369) — same loop-invariant
hoisting as the spec's optimization. UInt64 saturating math via
`.times()`, `.dividedBy()`. Validator-status cache pattern: iterates
over a pre-computed `validatorStatusList` (with `getCurrentEpochEffectiveBalance()`
read-only access) instead of raw state, decoupling the slashing apply
from validator-state mutations.

### nimbus
**Compile-time `when` dispatch on `static ConsensusFork` parameter** —
`get_slashing_penalty` is a `func` taking `consensusFork: static
ConsensusFork`, allowing the compiler to specialize the formula per
fork. The actual dispatch at line 1008:
```nim
let penalty = get_slashing_penalty(
    typeof(state).kind, validator[], adjusted_total_slashing_balance, total_balance)
```
where `typeof(state).kind` is a compile-time constant — zero runtime
overhead. The Pectra branch matches `[ConsensusFork.Electra,
ConsensusFork.Fulu, ConsensusFork.Gloas]` (line 987–988), the legacy
branch covers `<= ConsensusFork.Deneb`. `process_slashings_reset` is
fork-agnostic (`var ForkyBeaconState`). All `func` (`raises: []`) — no
error path. **Same compile-time idiom as items #6/#8/#9 for fork
dispatch** — nimbus is the most consistent client on this axis.

### lodestar
**Single function `processSlashings.ts`** with `if (fork <
ForkSeq.electra)` branch at line 63 routing to legacy vs Pectra
formula. The Pectra rate `penaltyPerEffectiveBalanceIncrement`
precomputed once (lines 53–55). **Defensive `intDiv()` instead of raw
`/`** for the `EPOCHS_PER_SLASHINGS_VECTOR / 2` half-vector divisor
(`epochTransitionCache.ts:233`) — protects against JS float division.
**Effective-balance-increment penalty memoization** (lines 58–69) —
validators with identical `effectiveBalanceIncrements` share one
penalty computation via a `Map<number, number>`. Unique optimization
not seen in any other client. **`epochCtx.totalSlashingsByIncrement`
dual-write cache** updated by both `slashValidator` (block-level write,
+= effective_balance) and `processSlashingsReset` (-= reset slot's
old value). Same dual-write pattern as items #4/#5 — single-source-of-truth
risk if `state.slashings.set()` is called outside these two paths.
Slashings stored as JS `number` (UintNum64), not BigInt — safe up to
`281474 * 32_000_000_000` per slot (mainnet upper bound), but worth
flagging for any future Gwei-amount expansion.

### grandine
**Per-fork module split** — `transition_functions/src/electra/epoch_processing.rs:469–527`
hosts the Electra `process_slashings`. Imports
`P::PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX` (= 3, type-associated
const per `Preset`). `process_slashings_reset` is in
`unphased/epoch_processing.rs:182–187` (single fork-agnostic
implementation). **Same source-organization risk** as items #6 and #9:
FIVE `process_slashings` definitions exist
(`phase0`, `altair`, `bellatrix`, `electra`, plus `fulu` calling
`electra::process_slashings` explicitly at `fulu/epoch_processing.rs:63`
— so 4 unique impls + 1 explicit re-call). The pre-Bellatrix versions
are `private fn`, the Bellatrix/Electra versions are `pub fn` —
compile-error if a wrong import slips through. F-tier today since
imports are correct. Uses `LazyCell` for
`adjusted_total_slashing_balance` (line 479) — only computes if at
least one validator's `withdrawable_epoch` predicate matches. Subtle
optimization for the common-case of "no slashings to drain this epoch."
**In-place balance mutation via `balances.update(|balance| {...})`**
closure — different choreography from prysm's batched
`SetBalances(bals)` and similar to lighthouse's milhouse Cow pattern.

## Cross-cut chain — slashings vector cycle CLOSED

Items #8 + #9 + #10 form the complete `state.slashings[]` vector
read/write cycle:

| Item | Operation | `state.slashings[idx]` access |
|---|---|---|
| #8 attester_slashing (block) | WRITE: `+= effective_balance` for each slashed validator | `state.slashings[current_epoch % EPOCHS_PER_SLASHINGS_VECTOR]` |
| #9 proposer_slashing (block) | WRITE: `+= effective_balance` (same path) | same |
| #10 process_slashings (epoch) | READ: `sum(state.slashings)` for adjusted_total | full vector |
| #10 process_slashings_reset (epoch) | WRITE: `state.slashings[(epoch+1) % VECTOR] = 0` | next epoch's slot |

**Cumulative fixture evidence**:
| Item | Fixtures | Cumulative |
|---|---|---|
| #6 voluntary_exit | 25/25 | 25 |
| #8 attester_slashing | 30/30 | 55 |
| #9 proposer_slashing | 15/15 | 70 |
| #10 slashings + reset | 6/6 | 76 |

**76 ops/epoch fixtures × 4 wired clients = 304 PASS results**
exercising the Pectra-modified slashings/exit machinery end-to-end —
from the block-level slash through the per-epoch drain through the
reset-for-next-epoch.

## Adjacent untouched Electra-active

- **Slashings vector index off-by-one** — the write-side uses `epoch %
  EPOCHS_PER_SLASHINGS_VECTOR`, the reset uses `(epoch+1) %
  EPOCHS_PER_SLASHINGS_VECTOR`. The drain reads ALL entries
  (`sum(state.slashings)`) so this index choreography matters only for
  what gets reset when. Worth a stateful fixture: slash at epoch N,
  advance to epoch N+1 with no new slashings, verify the slot-N entry
  is intact and slot-(N+1) is zero post-reset.
- **`slashings_with_random_state` precision** — the only fixture
  exercising multiple slashed validators with disparate effective
  balances. The Pectra precision improvement is most visible here
  (low-rate × validator with high effective balance = larger penalty
  due to less truncation). Worth measuring the actual numeric delta
  between legacy and Pectra formulas for the random fixture.
- **`adjusted_total_slashing_balance` clamp predicate** — `min(sum *
  3, total_balance)` clamps at `total_balance` when 33%+ of validators
  have been slashed within `EPOCHS_PER_SLASHINGS_VECTOR` epochs.
  `max_penalties` exercises this — but the boundary case `sum * 3 ==
  total_balance + 1` (just over the clamp threshold) is not directly
  tested.
- **lodestar's `epochCtx.totalSlashingsByIncrement` dual-write
  consistency** — depends on `slashValidator` (block) and
  `processSlashingsReset` (epoch) being the ONLY two writers. Any
  direct `state.slashings.set()` would diverge from the cache. Audit
  closure: grep for direct writes outside these two functions.
- **Floor-div precision delta** — for given (`effective_balance`,
  `total_balance`, `adjusted`), the legacy vs Pectra formula can
  differ by up to `(EFFECTIVE_BALANCE_INCREMENT - 1) gwei` per
  validator. Exact numeric proof + a fixture exercising the maximum
  delta would be a strong addition.
- **Multiple slashings in same epoch hitting the rate together** — if
  validators A and B are both slashed at epoch N (so both
  `withdrawable_epoch == N + EPOCHS_PER_SLASHINGS_VECTOR/2 + 4` after
  `MIN_SLASHING_DELAY`), they drain together at epoch N + 4096 + 4.
  The shared `penalty_per_increment` rate is computed ONCE per epoch
  — same rate for both — but Pectra's optimization is only
  measurable with ≥2 slashed validators. The 4 fixtures with ≥2
  slashed validators (`max_penalties`, `scaled_penalties`,
  `slashings_with_random_state`) all PASS — strong evidence.
- **Lighthouse's single-pass dispatch puts slashings INSIDE the
  validator loop** (not as a separate sequential pass). This means
  effective_balance read for slashings is the same `validator` object
  that's also being read for reward/penalty computation — natural
  coherence. Other clients separate slashings from rewards by
  function call boundary, requiring explicit ordering documentation.
- **Pre-Altair fork (Phase0) uses different processor entirely** —
  lighthouse's `base::process_epoch` calls a separate
  `process_slashings()` from `slashings.rs:11`. Confirms the
  pre-Altair path is dead code at Electra (no live mainnet upgrade
  from Phase0 directly to Electra), but worth a `dead_code` annotation
  for clarity.
- **EPOCHS_PER_SLASHINGS_VECTOR == 8192 mainnet, 64 minimal** — the
  divisor `/2` (= 4096 mainnet) is hard-coded as `intDiv` in
  lodestar, `safe_div` in lighthouse, raw `/` in nimbus/prysm/grandine
  (Nim/Go/Rust integer division is floor-div by spec for positive
  operands — safe).

## Future research items

1. **Cross-fork slashings drain straddling Pectra activation** — a
   validator slashed at epoch (Pectra-1), withdrawable at (Pectra-1) +
   4096 + 4 (well into Pectra). At the drain epoch, which formula
   applies? All clients use the **state's current fork** for the
   formula choice (the slashing was recorded in the state, not the
   formula). Worth a stateful fixture spanning the activation slot.
2. **MAX_EFFECTIVE_BALANCE_ELECTRA (2048 ETH) interaction** — a
   compounding (0x02) validator with effective_balance = 2048 ETH
   slashed: penalty becomes `penalty_per_increment * 2048/32 = 64 *
   penalty_per_increment` instead of `eff_balance/inc * rate` — same
   per-increment rate, but 64× more validator increments. Worth
   verifying the all-2048-validators slashed extreme case.
3. **`process_slashings` ordering within `process_epoch`** — pyspec
   ordering: `process_rewards_and_penalties` → `process_registry_updates`
   → `process_slashings` → `process_eth1_data_reset` →
   `process_effective_balance_updates` → `process_slashings_reset`.
   Each client's `process_epoch` should match. Lighthouse's
   single-pass collapses some of these — verify the observable
   post-state matches the sequential ordering exactly.
4. **lodestar's penalty-by-increment Map<number, number>
   memoization** — assumes identical `effectiveBalanceIncrements`
   produce identical penalties. Mathematically correct (penalty is
   purely a function of `effective_balance_increments` after the
   per-epoch rate is fixed), but a pre-emptive fuzz target if the
   formula ever changes to also depend on validator-specific state.
5. **prysm's `math.Add64` overflow check on sum-of-slashings** — the
   sum can reach `EPOCHS_PER_SLASHINGS_VECTOR * MAX_EFFECTIVE_BALANCE_ELECTRA
   = 8192 * 2048e9 = 1.7e16 gwei`, well under u64 max (1.8e19).
   Defensive but theoretically dead. Worth a `// theoretically
   unreachable` comment.
6. **grandine's `LazyCell` for `adjusted_total_slashing_balance`** —
   only computes if at least one validator matches the
   `withdrawable_epoch` predicate. **Subtle observability issue**:
   if ALL clients compute `total_balance` eagerly but grandine
   doesn't, a divergent `total_balance` cache could go unnoticed.
   Audit: confirm `total_balance` is computed identically with or
   without the lazy gate.
7. **Multiplier for Phase0 (= 1) vs Altair (= 2) vs Bellatrix+ (= 3)
   — fork transition correctness** — at the genesis-from-mainnet
   fork-history sweep, the multiplier changes twice. Each transition
   epoch's `process_slashings` should pick the new fork's multiplier
   even if the slashings vector contains entries written under the
   old multiplier — i.e., **the multiplier is not stamped into the
   vector**. Verify cross-client.
8. **`process_slashings_reset` order vs `process_slashings`** —
   pyspec puts `process_slashings_reset` AFTER `process_effective_balance_updates`
   in `process_epoch`. The reset zeroes the (epoch+1) slot, NOT the
   epoch slot. So slashings written this epoch persist through the
   drain (correct — they're for FUTURE epochs' drains). Verify
   choreography across clients.
9. **`PROPORTIONAL_SLASHING_MULTIPLIER` Gloas-readiness** — none of
   the clients have a Gloas-specific multiplier, but if EIP-7732 or
   similar adds one, the fork-keyed multiplier dispatch in each
   client should be ready. Worth a forward-compat audit.
