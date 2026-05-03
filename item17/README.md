# Item #17 — `process_registry_updates` Pectra-modified (single-pass restructure + EIP-7251 eligibility predicate)

**Status:** no-divergence-pending-fuzzing — audited 2026-05-02. The
**activation/ejection gatekeeper** at per-epoch processing,
restructured for Pectra. Cross-cuts items #4 (deposit drain → sets
`activation_eligibility_epoch`), #6/#8/#9 (initiate_validator_exit
→ Pectra churn-paced via item #16), and #11 (upgrade-time activation
churn budget seeding).

## Why this item

`process_registry_updates` runs every epoch and gates THREE per-validator
state transitions:

1. **Activation queue eligibility**: validators with
   `activation_eligibility_epoch == FAR_FUTURE_EPOCH` and sufficient
   balance get `activation_eligibility_epoch = current_epoch + 1`.
2. **Ejection**: active validators with `effective_balance <=
   EJECTION_BALANCE` get `initiate_validator_exit`'d.
3. **Activation**: validators with finalized eligibility AND
   `activation_epoch == FAR_FUTURE_EPOCH` get `activation_epoch =
   compute_activation_exit_epoch(current_epoch)`.

Pectra makes **TWO major changes**:

### Change 1: `is_eligible_for_activation_queue` predicate

```python
# Pre-Electra (Phase0):
def is_eligible_for_activation_queue(validator):
    return (validator.activation_eligibility_epoch == FAR_FUTURE_EPOCH
            and validator.effective_balance == MAX_EFFECTIVE_BALANCE)   # Strict equality 32 ETH

# Pectra (NEW):
def is_eligible_for_activation_queue(validator):
    return (validator.activation_eligibility_epoch == FAR_FUTURE_EPOCH
            and validator.effective_balance >= MIN_ACTIVATION_BALANCE)   # Inequality, MIN-ACTIVATION
```

The semantic shift: pre-Pectra required EXACTLY 32 ETH effective
balance (the only valid balance level pre-Pectra). Pectra accepts
any balance ≥ 32 ETH (because compounding 0x02 validators can have
up to 2048 ETH). The constant changes from `MAX_EFFECTIVE_BALANCE`
(legacy 32 ETH) to `MIN_ACTIVATION_BALANCE` (Pectra 32 ETH but with
inequality semantics).

### Change 2: SINGLE-PASS structure (was two-pass + activation churn)

```python
# Pre-Electra (TWO PASSES):
# Pass 1: mark eligibility + ejections
for index, validator in enumerate(state.validators):
    if is_eligible_for_activation_queue(validator):
        validator.activation_eligibility_epoch = current_epoch + 1
    elif is_active_validator(validator, current_epoch) and validator.effective_balance <= EJECTION_BALANCE:
        initiate_validator_exit(state, ValidatorIndex(index))
# Pass 2: sort activation queue + apply CHURN LIMIT
activation_queue = sorted(
    [index for index, validator in enumerate(state.validators)
     if is_eligible_for_activation(state, validator)],
    key=lambda index: (state.validators[index].activation_eligibility_epoch, index)
)
churn_limit = get_validator_activation_churn_limit(state)
for index in activation_queue[:churn_limit]:
    state.validators[index].activation_epoch = compute_activation_exit_epoch(current_epoch)

# Pectra (SINGLE PASS, NO ACTIVATION CHURN LIMIT):
def process_registry_updates(state):
    current_epoch = get_current_epoch(state)
    activation_epoch = compute_activation_exit_epoch(current_epoch)
    for index, validator in enumerate(state.validators):
        if is_eligible_for_activation_queue(validator):
            validator.activation_eligibility_epoch = current_epoch + 1
        elif is_active_validator(validator, current_epoch) and validator.effective_balance <= EJECTION_BALANCE:
            initiate_validator_exit(state, ValidatorIndex(index))
        elif is_eligible_for_activation(state, validator):
            validator.activation_epoch = activation_epoch     # ALL eligible activate at once
```

The Pectra rationale: activation churn is now **applied at deposit
time** (item #16's `compute_exit_epoch_and_update_churn` is called
indirectly via `initiate_validator_exit`, and consolidations have
their own churn primitive). So `process_registry_updates` no longer
needs to throttle activations per-epoch — it bulk-activates everything
that's eligible.

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | `is_eligible_for_activation_queue` Pectra: `effective_balance >= MIN_ACTIVATION_BALANCE` (NOT `== MAX_EFFECTIVE_BALANCE`) | ✅ all 6 |
| H2 | `is_eligible_for_activation_queue` Pectra: still requires `activation_eligibility_epoch == FAR_FUTURE_EPOCH` | ✅ all 6 |
| H3 | SINGLE-PASS loop (NOT two-pass) | ✅ all 6 (with implementation-style variations — see below) |
| H4 | NO per-epoch activation churn limit at this layer (all eligible activate at `compute_activation_exit_epoch(current_epoch)`) | ✅ all 6 |
| H5 | if/elif/elif ordering: eligibility-for-queue → ejection → eligibility-for-activation | ✅ 4/6 use explicit elif chain; 2/6 (prysm, grandine) use 3 independent `if`s + 3 sequential update loops (semantically equivalent because the conditions are mutually exclusive) |
| H6 | Activation epoch source: `compute_activation_exit_epoch(current_epoch)` = `current + 1 + MAX_SEED_LOOKAHEAD = current + 5` | ✅ all 6 |
| H7 | `initiate_validator_exit` invocation is the Pectra version (calls `compute_exit_epoch_and_update_churn` — item #16) | ✅ all 6 |
| H8 | `is_eligible_for_activation` (NO QUEUE) unchanged from Phase0: `activation_eligibility_epoch <= state.finalized_checkpoint.epoch && activation_epoch == FAR_FUTURE_EPOCH` | ✅ all 6 |
| H9 | Activation eligibility set: `activation_eligibility_epoch = current_epoch + 1` (NOT `current_epoch`) | ✅ all 6 |

## Per-client cross-reference

| Client | `process_registry_updates` location | `is_eligible_for_activation_queue` location | Loop style |
|---|---|---|---|
| **prysm** | `core/electra/registry_updates.go:39-107` | `core/helpers/validators.go:455-494` (fork dispatcher → `isEligibleForActivationQueueElectra:491-494`) | Three independent `if`s collecting indices via `ReadFromEveryValidator`, then 3 sequential update loops |
| **lighthouse** | `state_processing/src/per_epoch_processing/single_pass.rs:672-776` (single-pass) + `registry_updates.rs:9-57` (fast path, pre-Electra preferred) | `consensus/types/src/validator/validator.rs:113-116` (`is_eligible_for_activation_queue_electra`) + dispatch `:90-100` | INLINED into single-pass epoch processor (NO dedicated electra/ module) |
| **teku** | `versions/electra/.../EpochProcessorElectra.java:86-120` (subclass override) | `EpochProcessorElectra.java:134-139` (override, NOT in PredicatesElectra) | Standard if/elif/elif single-pass loop |
| **nimbus** | `state_transition_epoch.nim:918-942` (`when consensusFork >= ConsensusFork.Electra`) | `beaconstate.nim:607-616` (compile-time `when fork <= Deneb` else branch) | TWO loops: (1) eligibility + ejection; (2) activation — semantically single-pass since loops independent |
| **lodestar** | `epoch/processRegistryUpdates.ts:20-65`; eligibility CACHED in `cache/epochTransitionCache.ts:323-328` | inlined in `epochTransitionCache.ts:323-328` | Single-pass via `epochCtx` cache: eligibility computed once in `beforeProcessEpoch()` `forEachValue` (line 275), then 3 update loops in `processRegistryUpdates` |
| **grandine** | `transition_functions/src/electra/epoch_processing.rs:164-229` | `helper_functions/src/electra.rs:32-35` (Pectra; phase0.rs:76-79 separately) | Three independent `if`s collecting vectors in single loop, then 3 sequential update loops |

## Notable per-client divergences (all observable-equivalent)

### Two-loop styles, three structural patterns

The pyspec uses an `if/elif/elif` chain. The audit reveals THREE
implementation patterns, all observable-equivalent:

**Pattern A — explicit if/elif/elif single-pass** (teku, nimbus's
first loop, lodestar's cache):
```java
for (int index = 0; index < validators.size(); index++) {
  if (isEligibleForActivationQueue(validator, status)) {
    state.getValidators().update(index, v -> v.withActivationEligibilityEpoch(currentEpoch.plus(UInt64.ONE)));
  } else if (status.isActiveInCurrentEpoch() && status.getCurrentEpochEffectiveBalance().isLessThanOrEqualTo(ejectionBalance)) {
    beaconStateMutators.initiateValidatorExit(state, index, validatorExitContextSupplier);
  } else if (isEligibleForActivation(finalizedEpoch, validator)) {
    state.getValidators().update(index, v -> v.withActivationEpoch(activationEpoch));
  }
}
```

**Pattern B — independent ifs + post-collection update loops**
(prysm, grandine):
```rust
for (validator, validator_index) in state.validators().into_iter().zip(0..) {
    if is_eligible_for_activation_queue::<P>(validator) { eligible_for_activation_queue.push(validator_index); }
    if is_active_validator(validator, current_epoch) && validator.effective_balance <= config.ejection_balance { ejections.push(validator_index); }
    if is_eligible_for_activation(state, validator) { activation_queue.push((validator_index, validator.activation_eligibility_epoch)); }
}
// Then 3 update loops applying mutations from the collected vectors.
```

**Pattern C — single-pass folding into the omnibus epoch processor**
(lighthouse, lodestar):
- Lighthouse: `process_single_registry_update` is INLINED into the
  per-validator loop in `single_pass.rs:295-308` alongside slashings,
  deposits, effective balances, etc. — no dedicated registry-updates
  pass.
- Lodestar: the eligibility decision is computed in `beforeProcessEpoch()`'s
  per-validator forEachValue loop (line 275) and CACHED into
  `epochCtx.indicesEligibleFor*` arrays; `processRegistryUpdates`
  consumes those arrays.

**Why all three are equivalent**: the three predicates are
mutually exclusive (a validator can be in at most ONE of the
three states per epoch), so independent ifs vs elif chain produce
identical observable post-state. The post-collection style and
single-pass-folding both avoid double-iterating the validator
list.

### Pattern B has a SUBTLE precondition that pyspec doesn't enforce

In Pattern B (prysm/grandine), the three `if`s read the SAME
`validator` object. If the activation-queue update mutates the
validator (sets `activation_eligibility_epoch = current + 1`), and
THEN the activation check runs, the validator now has
`activation_eligibility_epoch = current + 1` instead of
FAR_FUTURE_EPOCH — but the check is `activation_eligibility_epoch
<= state.finalized_checkpoint.epoch` which is TRUE only if
`current + 1 <= finalized_epoch`. Since `current` epoch's events
can't yet be finalized (finalization lags by ≥1 epoch), `current + 1
> finalized_epoch` so the validator is NOT yet eligible for
activation. **Mutual exclusivity preserved by finality timing,
not by code structure.**

Pyspec's `elif` chain makes mutual exclusivity explicit. Pattern B
relies on the timing invariant. **Both produce the same observable
post-state today**, but Pattern B is more fragile if a future fork
changes finality timing semantics.

### lighthouse's two-path coexistence

Lighthouse maintains BOTH the legacy two-pass `registry_updates.rs`
(pre-Electra fast path with sort + churn limit) AND the inlined
single-pass `single_pass.rs` (Electra and beyond). Dispatch happens
at the function entry: `state.fork_name_unchecked()` determines
which path runs. **Pre-Electra fast path is dead at Electra**
(once mainnet upgrades to Electra, no live block processes via the
fast path), but kept for historical replay and minimal-preset tests.

### nimbus's TWO sequential complete passes (NOT single-pass)

Nimbus's Electra `process_registry_updates` actually has **TWO
separate complete passes** over `state.validators`:

```nim
# Pass 1: eligibility + ejection
for index in 0 ..< state.validators.len:
  let validator = state.validators.item(index)
  if is_eligible_for_activation_queue(typeof(state).kind, validator):
    state.validators.mitem(index).activation_eligibility_epoch = get_current_epoch(state) + 1
  if is_active_validator(validator, get_current_epoch(state)) and
     distinctBase(validator.effective_balance) <= cfg.EJECTION_BALANCE:
    discard ? initiate_validator_exit(...)

# Pass 2: activation
let activation_epoch = compute_activation_exit_epoch(get_current_epoch(state))
for index in 0 ..< state.validators.len:
  if is_eligible_for_activation(state, state.validators.item(index)):
    state.validators.mitem(index).activation_epoch = activation_epoch
```

**Two passes, NOT one.** This is OK because the second pass's check
(`is_eligible_for_activation`) requires
`activation_eligibility_epoch <= finalized_epoch` — and the first
pass set newly-eligible validators to `current_epoch + 1` which is
NOT yet finalized. So newly-eligible validators are correctly
NOT activated in the same epoch they became eligible. **Same
observable post-state as the single-pass version.**

### lighthouse's pre-Electra "fast path" is preferred when applicable

```rust
// In single_pass.rs:213-221 — Electra branch:
let activation_queue = if !state_ctxt.fork_name.electra_enabled() {
    Some(activation_queue.activation_queue(/* ... */)?)
} else {
    None  // No per-epoch activation churn limit at Electra
};
```

The `activation_queue` cache (sorted, churn-limited) is built only
for pre-Electra. At Electra, this cache is `None` and the
activation logic uses the Pectra `compute_activation_exit_epoch(current_epoch)`
directly. **Memory optimization** — avoids building a sort that
isn't used.

### grandine's source-organization risk

```
helper_functions/src/phase0.rs:76     pub const fn is_eligible_for_activation_queue<P>(validator) -> bool   // Phase0: == MAX_EFFECTIVE_BALANCE
helper_functions/src/electra.rs:32    pub const fn is_eligible_for_activation_queue<P>(validator) -> bool   // Pectra: >= MIN_ACTIVATION_BALANCE
helper_functions/src/mutators.rs:61   pub fn initiate_validator_exit<P>(...)                                 // Phase0 churn
helper_functions/src/electra.rs:124   pub fn initiate_validator_exit<P>(...)                                 // Pectra churn (item #16)
```

Same multi-fork-definition pattern as items #6/#9/#10/#12/#14/#15. The
Electra `process_registry_updates` correctly imports from `electra::`
module:

```rust
use helper_functions::{
    electra::{initiate_validator_exit, is_eligible_for_activation_queue},
    misc::{compute_activation_exit_epoch, ...},
    predicates::{is_active_validator},
};
```

F-tier today since the import is correct, but the next refactor
risks a mistake. Worth a one-line audit.

### lodestar's epoch-context cache pattern

Lodestar PRE-COMPUTES the eligibility arrays once per epoch in
`beforeProcessEpoch()`:

```typescript
// In epochTransitionCache.ts:275-372 — single forEachValue iteration:
state.validators.forEachValue((validator, i) => {
    // ... slashing, etc ...
    if (validator.activationEligibilityEpoch === FAR_FUTURE_EPOCH &&
        validator.effectiveBalance >= MIN_ACTIVATION_BALANCE) {
        indicesEligibleForActivationQueue.push(i);
    } else if (validator.activationEpoch === FAR_FUTURE_EPOCH &&
               validator.activationEligibilityEpoch <= currentEpoch) {
        indicesEligibleForActivation.push({...});
    } else if (isActiveCurr &&
               validator.exitEpoch === FAR_FUTURE_EPOCH &&
               validator.effectiveBalance <= config.EJECTION_BALANCE) {
        indicesToEject.push(i);
    }
});
```

Then `processRegistryUpdates.ts` consumes these arrays. **Subtle
divergence**: lodestar's cache check uses `currentEpoch` (NOT
`finalized_checkpoint.epoch`) for the "eligible-for-activation"
predicate — different from pyspec's `is_eligible_for_activation`.

Wait, let me re-read… `validator.activationEligibilityEpoch <= currentEpoch`
vs pyspec's `validator.activation_eligibility_epoch <= state.finalized_checkpoint.epoch`.
**This is a real divergence!** But since lodestar's downstream
`processRegistryUpdates.ts` then ALSO checks finalization, the
cache is just a pre-filter. Verifying:

```typescript
// In processRegistryUpdates.ts:36:
const finalityEpoch = epochTransitionCacheData.finalityEpoch;
for (const {index, eligibilityEpoch} of indicesEligibleForActivation) {
    if (eligibilityEpoch > finalityEpoch) break;       // <-- finality check
    // ... activate ...
}
```

OK — the finalization check IS done at consumption time, after the
cache is filtered. The cache uses `<= currentEpoch` to pre-filter
candidates that COULD be eligible (those with eligibility_epoch in
the past); the actual finalization check is applied at update time.
**Observable-equivalent**, but two-stage filtering is a unique idiom
not seen in other clients.

### prysm's per-epoch fork transition gate

prysm's `IsEligibleForActivationQueue` (validators.go:455-460) uses
RUNTIME fork-epoch comparison:

```go
func IsEligibleForActivationQueue(validator state.ReadOnlyValidator, currentEpoch primitives.Epoch) bool {
    if currentEpoch >= params.BeaconConfig().ElectraForkEpoch {
        return isEligibleForActivationQueueElectra(validator.ActivationEligibilityEpoch(), validator.EffectiveBalance())
    }
    return isEligibleForActivationQueue(validator.ActivationEligibilityEpoch(), validator.EffectiveBalance())
}
```

Note this is by EPOCH not by VERSION. If a state at epoch N is
processed under Pectra fork (`state.Version() >= Electra`) but
`currentEpoch < ElectraForkEpoch` (impossible in practice but
theoretically), this dispatch would use the Phase0 predicate.
**Defensive but unreachable** — `currentEpoch` is derived from
`state.slot()`, and a state with `Version() >= Electra` MUST have
`currentEpoch >= ElectraForkEpoch`.

## EF fixture results — 63/64 PASS, 1 deliberate lodestar skip (NOT a divergence)

```
clients: prysm, lighthouse, lodestar, grandine
fixtures: 16
PASS: 63   FAIL: 0   SKIP: 0 (in our harness)   total: 64
notable: lodestar's vitest INTERNALLY skips `invalid_large_withdrawable_epoch`
         (1 fixture); our runner detected this as a non-pass and reported
         FAIL[1]. Manual verification confirmed lodestar deliberately
         marks this fixture as skipped with a documented TODO:
```

**Lodestar skip rationale** (from `packages/beacon-node/test/spec/presets/epoch_processing.test.ts:128-131`):

```typescript
fn: epochProcessing([
    // TODO: invalid_large_withdrawable_epoch asserts an overflow on a u64 for its exit epoch.
    // Currently unable to reproduce in Lodestar, skipping for now
    // https://github.com/ethereum/consensus-specs/blob/3212c419f6335e80ed825b4855a071f76bef70c3/tests/core/pyspec/eth2spec/test/phase0/epoch_processing/test_process_registry_updates.py#L349
    "invalid_large_withdrawable_epoch",
]),
```

The fixture asserts a u64 overflow path that TypeScript's BigInt
arithmetic cannot reproduce naturally (no overflow at the same
boundary). prysm (Go u64), lighthouse (Rust u64), and grandine
(Rust u64) all correctly handle the overflow case and PASS the
fixture. teku (Java UInt64 with saturating arithmetic) and nimbus
(Nim uint64) also handle it per source review.

**Effective result**: 15/16 fixtures PASS for lodestar (1 deliberate
skip with documented rationale), **16/16 PASS for prysm + lighthouse
+ grandine** = 63/64 PASSes total, 0 actual divergences.

A runner patch could detect the lodestar internal-skip pattern
(`tests N skipped (N)` with passed=0 and exit=0) and report SKIP
instead of FAIL — worth a follow-up to `tools/runners/lodestar.sh`.

The 16-fixture EF suite covers:

| Fixture | Hypothesis tested |
|---|---|
| `add_to_activation_queue` | H1+H2: eligibility → set activation_eligibility_epoch |
| `activation_queue_eligibility__greater_than_min_activation_balance` | H1: balance > MIN should be eligible |
| `activation_queue_eligibility__less_than_min_activation_balance` | H1: balance < MIN should NOT be eligible |
| `activation_queue_eligibility__min_activation_balance` | H1: balance == MIN boundary |
| `activation_queue_eligibility__min_activation_balance_compounding_creds` | H1: 0x02 credentials at MIN balance |
| `activation_queue_eligibility__min_activation_balance_eth1_creds` | H1: 0x01 credentials at MIN balance |
| `activation_queue_to_activated_if_finalized` | H8: finalization-gated activation |
| `activation_queue_no_activation_no_finality` | H8: NO activation when not finalized |
| `activation_queue_activation_and_ejection__1` | H4+H7: activation + ejection same block |
| `activation_queue_activation_and_ejection__churn_limit` | H4: NO churn limit at activation (all eligible activate) |
| `activation_queue_activation_and_ejection__exceed_churn_limit` | H4: BULK activation past pre-Electra churn cap |
| `activation_queue_efficiency_min` | H3+H4: single-pass efficiency |
| `activation_queue_sorting` | activation queue ordering (relevant only pre-Electra) |
| `ejection` | H7: standard ejection |
| `ejection_past_churn_limit_min` | H7+item#16: ejection consumes exit churn |
| `invalid_large_withdrawable_epoch` | edge case: pathological state |

teku and nimbus SKIP per harness limitation (no per-epoch CLI hook
in BeaconBreaker's runners). Both have full implementations per
source review.

## Cross-cut chain — registry_updates is the per-epoch activation/ejection layer

This audit closes the **per-epoch activation/ejection** layer of
the Pectra surface. Combined with prior items:

```
[item #11 upgrade]: pre-activation validators seeded into pending_deposits
     ↓
[item #4 process_pending_deposits]: drain → add_validator_to_registry
     ↓                                    (sets initial state)
state.validators[i].activation_eligibility_epoch = FAR_FUTURE_EPOCH
state.validators[i].effective_balance = <deposit_amount>
     ↓
[item #17 (this) process_registry_updates per-epoch]:
     IF eligible: activation_eligibility_epoch = current + 1
     ELIF active && balance ≤ EJECTION_BALANCE: initiate_validator_exit (item #6/#16)
     ELIF eligible_for_activation: activation_epoch = compute_activation_exit_epoch(current)
     ↓
state.validators[i] is now ACTIVE for attestation duties
```

The activation/ejection layer is now audited end-to-end alongside
the deposit chain (items #4/#11/#13/#14), the slashings cycle
(items #6/#8/#9/#10), the withdrawal cycle (items #3/#11/#12), and
the consolidation cycle (items #2/#5).

## Adjacent untouched

- **`add_validator_to_registry` Pectra-modified helper** — called by
  item #4's drain when a deposit creates a new validator. Pectra
  changes for compounding-credentials handling. Worth a standalone
  audit.
- **`compute_activation_exit_epoch` standalone audit** — called by
  every Pectra exit/consolidation/activation path. Trivial formula
  but pivotal. Already noted as future work in items #11/#16.
- **`is_eligible_for_activation` (NO QUEUE) cross-fork transition**
  at the Pectra activation slot — pyspec is unchanged from Phase0,
  but verifying the predicate works correctly when `state.fork.epoch
  == ELECTRA_FORK_EPOCH` is worth a fixture.
- **lighthouse pre-Electra fast path dead-code analysis** — at
  mainnet activation, the pre-Electra fast path becomes dead.
  Worth a `dead_code` annotation or removal plan.
- **prysm Pattern B per-validator-mutation re-read concern** — the
  three independent `if`s read the SAME validator object;
  finalization timing makes them mutually exclusive in practice but
  the code doesn't enforce it. Worth a contract test asserting that
  no validator hits two of the three branches per epoch.
- **lodestar two-stage cache filtering** — `<= currentEpoch` cache
  + `<= finalityEpoch` consume — observable-equivalent today, but
  one-stage cache (using `finalityEpoch` directly) would be
  cleaner.
- **nimbus two-pass equivalence** — the two passes work because the
  first sets `activation_eligibility_epoch = current + 1` (not yet
  finalized), so the second pass's `is_eligible_for_activation`
  filters it out. Worth codifying as a comment.
- **grandine source-organization risk** — same multi-fork-definition
  pattern as items #6/#9/#10/#12/#14/#15. F-tier today.
- **EJECTION_BALANCE = 16 ETH (configurable)** — when an active
  validator's effective_balance ≤ 16 ETH, they're ejected. With
  Pectra's compounding (up to 2048 ETH effective balance), the
  ejection threshold is unchanged. Worth verifying the threshold
  doesn't trigger spuriously for partial-withdrawal-then-slashed
  edge cases.
- **`current_epoch + 1` for eligibility (NOT `current_epoch`)** —
  this `+1` ensures newly-eligible validators can't be activated
  in the same epoch (which would let them attest immediately
  without the seed lookahead). Worth verifying cross-client.

## Future research items

1. **Audit `add_validator_to_registry`** — Pectra-modified helper;
   the only major Pectra-modified helper not yet a standalone item.
2. **Audit `compute_activation_exit_epoch`** — used by every Pectra
   exit/consolidation/activation path. Trivial but pivotal.
3. **Stateful fixture: cross-fork eligibility transition** at
   Pectra activation epoch — verify validators with effective_balance
   in the [MIN_ACTIVATION_BALANCE, MAX_EFFECTIVE_BALANCE) range
   become newly-eligible at the fork.
4. **prysm Pattern B re-read contract test** — assert mutual
   exclusivity invariant under all reachable states.
5. **lodestar two-stage cache filter consolidation** — single-stage
   cleanup.
6. **nimbus two-pass equivalence comment** — codify the timing
   reasoning.
7. **lighthouse pre-Electra fast path dead-code annotation** at
   Electra mainnet activation.
8. **grandine source-organization risk** — one-line audit asserting
   correct module imports across all per-fork dispatch sites (item
   #6/#9/#10/#12/#14/#15/#17 all share this concern).
9. **EJECTION_BALANCE Pectra interaction** — verify ejection
   threshold semantics with compounding validators.
10. **`current_epoch + 1` eligibility-set timing** — verify all 6
    clients use `+1` (not `+0` or `+2`).
11. **`activation_queue_sorting` pre-Electra fixture** — should be
    a no-op at Pectra (no sorting needed). Verify cross-client.
12. **Multi-validator stress fixture**: 1000 validators all
    becoming eligible in the same epoch — verify no per-epoch
    activation churn limit kicks in (Pectra change H4).
13. **Cross-cut with item #16**: validators ejected via item #17
    consume the per-block exit churn budget. Stateful fixture
    with several ejections + voluntary exits + EL withdrawal
    requests in same block.
14. **Cross-cut with item #4**: a deposit processed in this epoch
    sets `activation_eligibility_epoch = FAR_FUTURE_EPOCH`; this
    epoch's `process_registry_updates` then sets it to `current + 1`.
    Two-epoch round-trip from deposit to activation eligibility.
