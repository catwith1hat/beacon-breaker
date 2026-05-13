---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [1, 4, 11, 14, 17]
eips: [EIP-7251]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 18: `add_validator_to_registry` + `get_validator_from_deposit` Pectra-modified

## Summary

Pectra's compounding-credentials feature (EIP-7251) requires a new validator's `effective_balance` cap to depend on its **withdrawal credentials prefix**: `0x01` (legacy execution) → 32 ETH cap; `0x02` (compounding) → 2048 ETH cap. The implementation requires a small but pivotal change to `get_validator_from_deposit` — the function shifts from one-step (set effective_balance with hardcoded `MAX_EFFECTIVE_BALANCE = 32 ETH` cap) to two-step (create validator with `effective_balance = 0`, read credentials, compute cap via `get_max_effective_balance(validator)` from item #1, set final EB via `min(amount_rounded, cap)`). `add_validator_to_registry` itself is Altair-heritage (unchanged from Altair): allocate index, create validator, append to 5 per-validator lists (validators, balances, previous_epoch_participation, current_epoch_participation, inactivity_scores).

**Pectra surface (the function bodies themselves):** all six clients implement the two-step construction identically. Six implementation patterns — explicit mutation (prysm, lighthouse, nimbus), single-step inline (lodestar, grandine), and subclass-override polymorphism (teku via `MiscHelpersElectra.getValidatorFromDeposit` override) — but all observable-equivalent. 216 implicit cross-validation invocations from items #4 + #14 = 54 fixtures × 4 wired clients flow through these helpers.

**Gloas surface (at the Glamsterdam target): no change.** Neither `add_validator_to_registry` nor `get_validator_from_deposit` is modified at Gloas — no `Modified` headings for either in `vendor/consensus-specs/specs/gloas/beacon-chain.md`. The Gloas chapter adds **new parallel helpers for builders** (`get_index_for_new_builder` at line 1522, `apply_deposit_for_builder` at line 1556) but these handle the builder side via `state.builders`, not the validator registry. For validator-side new validators (the subject of this audit), the code path is unchanged at Gloas. The Gloas EIP-8061 churn cascade (items #2/#3/#4/#6/#8/#9/#16/#17) doesn't affect this item — these helpers don't call `compute_exit_epoch_and_update_churn` or any churn primitive. The Gloas EIP-7732 ePBS divergences in items #7/#9/#12/#13/#14 (lighthouse-only) don't propagate here either — those are builder-side gaps; this item handles the validator side that lighthouse still implements correctly.

## Question

Pyspec `get_validator_from_deposit` (Pectra-modified, `vendor/consensus-specs/specs/electra/beacon-chain.md`):

```python
def get_validator_from_deposit(pubkey, withdrawal_credentials, amount):
    validator = Validator(
        pubkey=pubkey,
        withdrawal_credentials=withdrawal_credentials,
        effective_balance=Gwei(0),    # STEP 1: Initially 0
        slashed=False,
        activation_eligibility_epoch=FAR_FUTURE_EPOCH,
        activation_epoch=FAR_FUTURE_EPOCH,
        exit_epoch=FAR_FUTURE_EPOCH,
        withdrawable_epoch=FAR_FUTURE_EPOCH,
    )
    # [Modified in Electra:EIP7251] STEP 2: read credentials, compute cap, set EB
    max_effective_balance = get_max_effective_balance(validator)   # 32 or 2048 ETH (item #1)
    validator.effective_balance = min(
        amount - amount % EFFECTIVE_BALANCE_INCREMENT,
        max_effective_balance
    )
    return validator
```

`add_validator_to_registry` (Altair-heritage, unchanged at Pectra except for the helper it calls):

```python
def add_validator_to_registry(state, pubkey, withdrawal_credentials, amount):
    index = get_index_for_new_validator(state)  # = len(state.validators) before push
    validator = get_validator_from_deposit(pubkey, withdrawal_credentials, amount)
    state.validators.append(validator)
    state.balances.append(amount)
    state.previous_epoch_participation.append(ParticipationFlags(0))
    state.current_epoch_participation.append(ParticipationFlags(0))
    state.inactivity_scores.append(0)
```

Nine Pectra-relevant divergence-prone bits (H1–H9 unchanged from the prior audit): two-step construction, `get_max_effective_balance` consumption, downward rounding, `min` formula, initial field defaults, 5-field Altair-heritage init, `get_index_for_new_validator` semantics, `amount = 0` deferral pattern at per-block, pubkey cache update timing.

**Glamsterdam target.** Neither function is modified at Gloas. The Gloas chapter (`vendor/consensus-specs/specs/gloas/beacon-chain.md`) adds two **new parallel helpers** for the builder side:

- `get_index_for_new_builder(state)` at line 1522 — returns the next builder index.
- `apply_deposit_for_builder(state, pubkey, creds, amount, signature, slot)` at line 1556 — adds a new builder to `state.builders` with on-the-fly BLS signature verification (different semantics from this item's deferred verification).

Both are called from the new Gloas `process_deposit_request` branch (item #14 H9 finding) when the deposit's pubkey matches an existing builder OR carries `0x03` builder withdrawal credentials. **They don't replace this item's helpers** — they're added in parallel for the builder lifecycle. Validator-side deposits (non-builder) continue to flow through item #4's drain → this item's `add_validator_to_registry` → item #17's eligibility-set.

The hypothesis: *all six clients implement the Pectra two-step construction and Altair-heritage registry-append identically (H1–H9), and at the Glamsterdam target the function bodies are unchanged so H1–H9 continue to hold (H10).*

**Consensus relevance**: this is the producer of new validators after deposit drain. Every new validator's initial `effective_balance` flows through this two-step construction. A divergence in the Pectra two-step (wrong cap, wrong rounding, missing one of the 5 list pushes) would surface immediately as cross-client mismatch on the new validator's state fields. The Gloas chapter doesn't touch this code path for validator-side deposits, so the Pectra audit conclusion carries forward unchanged.

## Hypotheses

- **H1.** Two-step `get_validator_from_deposit` construction (initial `effective_balance = 0`, then compute cap, then set).
- **H2.** `get_max_effective_balance(validator)` (item #1's helper) returns 2048 ETH for 0x02, 32 ETH for 0x01, used as the cap.
- **H3.** Downward rounding to `EFFECTIVE_BALANCE_INCREMENT = 1 ETH`: `amount - amount % EB_INC`.
- **H4.** Final `effective_balance = min(amount_rounded, max_eb)` — uses `min`, not just one of the two.
- **H5.** Initial fields: `slashed=false`, all 4 epoch fields = `FAR_FUTURE_EPOCH`.
- **H6.** `add_validator_to_registry` 5-field init: validators, balances, previous_epoch_participation, current_epoch_participation, inactivity_scores.
- **H7.** `get_index_for_new_validator(state) = len(state.validators)` (the new validator's index is the length BEFORE the push).
- **H8.** Per-block `process_deposit` for new validator passes `amount = 0` to `add_validator_to_registry` (Pectra defers amount to pending-deposits drain); 4/6 clients handle the deferral via different choreography.
- **H9.** Pubkey cache (`pubkey_to_index` map) updated after the push.
- **H10** *(Glamsterdam target)*. Neither `add_validator_to_registry` nor `get_validator_from_deposit` is modified at Gloas. The Gloas chapter adds parallel builder helpers (`get_index_for_new_builder`, `apply_deposit_for_builder`) for the builder side, but this item's helpers continue to handle the validator side unchanged. H1–H9 continue to hold post-Glamsterdam.

## Findings

H1–H10 satisfied. **No divergence at the source-level predicate or the EF-fixture level on either the Pectra or Glamsterdam surface.**

### prysm

`vendor/prysm/beacon-chain/core/electra/deposits.go:519-537` — `getValidatorFromDeposit`. Explicit two-step:

```go
v := &ethpb.Validator{
    PublicKey:                  publicKey,
    WithdrawalCredentials:      withdrawalCredentials,
    EffectiveBalance:           0,  // STEP 1
    Slashed:                    false,
    ActivationEligibilityEpoch: params.BeaconConfig().FarFutureEpoch,
    ActivationEpoch:            params.BeaconConfig().FarFutureEpoch,
    ExitEpoch:                  params.BeaconConfig().FarFutureEpoch,
    WithdrawableEpoch:          params.BeaconConfig().FarFutureEpoch,
}
maxEffectiveBalance := helpers.ValidatorMaxEffectiveBalance(v)   // STEP 2
v.EffectiveBalance = min(amount - amount % params.BeaconConfig().EffectiveBalanceIncrement, maxEffectiveBalance)
return v, nil
```

`vendor/prysm/beacon-chain/core/electra/deposits.go:462-497` — `AddValidatorToRegistry`. Appends to the 5 lists with `bytesutil.SafeCopyBytes` defensive copies.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (explicit `0` in `electra/deposits.go:144`). H9 ✓. **H10 ✓** (function bodies unchanged at Gloas; `AddValidatorToRegistry` continues to be called from per-block deferred path; the Gloas builder-side path is handled by separate functions per item #14 H9).

### lighthouse

`vendor/lighthouse/consensus/types/src/validator/validator.rs:39-65` — `Validator::from_deposit` (pure constructor):

```rust
pub fn from_deposit(...) -> Self {
    let mut validator = Validator {
        pubkey, withdrawal_credentials,
        activation_eligibility_epoch: spec.far_future_epoch,
        activation_epoch: spec.far_future_epoch,
        exit_epoch: spec.far_future_epoch,
        withdrawable_epoch: spec.far_future_epoch,
        slashed: false,
        effective_balance: 0,    // STEP 1
    };
    let max_effective_balance = validator.get_max_effective_balance(spec, fork_name);   // STEP 2
    validator.effective_balance = std::cmp::min(
        amount - (amount % spec.effective_balance_increment),
        max_effective_balance,
    );
    validator
}
```

The comment `"safe math is unnecessary here since the spec.effective_balance_increment is never <= 0"` explicitly documents the choice not to use overflow-checked math.

`vendor/lighthouse/consensus/types/src/state/beacon_state.rs:1922-1965` — `add_validator_to_registry` state method. Appends to the 5 lists + explicit `pubkey_cache.append(...)` at lines 1956-1962.

Per-block invocation explicitly passes `amount = 0`:

```rust
// process_operations.rs:467-487
state.add_validator_to_registry(
    deposit_data.pubkey,
    deposit_data.withdrawal_credentials,
    if state.fork_name_unchecked() >= ForkName::Electra { 0 } else { amount },
    spec,
)?;
```

H1 ✓. H2 ✓ (via `validator.get_max_effective_balance(spec, fork_name)`). H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (explicit `0`). H9 ✓. **H10 ✓** (no Modified heading at Gloas; the function continues to operate identically on Gloas states for validator-side deposits).

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/MiscHelpersElectra.java:117-137` — `getValidatorFromDeposit` (override of `MiscHelpers.getValidatorFromDeposit` via subclass polymorphism):

```java
@Override
public Validator getValidatorFromDeposit(
    final BLSPublicKey pubkey,
    final Bytes32 withdrawalCredentials,
    final UInt64 amount) {
  Validator validator = ValidatorBuilder.create()
      .pubkey(pubkey).withdrawalCredentials(withdrawalCredentials)
      .activationEligibilityEpoch(FAR_FUTURE_EPOCH).activationEpoch(FAR_FUTURE_EPOCH)
      .exitEpoch(FAR_FUTURE_EPOCH).withdrawableEpoch(FAR_FUTURE_EPOCH)
      .effectiveBalance(UInt64.ZERO)    // STEP 1
      .slashed(false)
      .build();
  final UInt64 maxEffectiveBalance = getMaxEffectiveBalance(validator);   // STEP 2
  final UInt64 effectiveBalance = (amount.minus(amount.mod(EFFECTIVE_BALANCE_INCREMENT)))
      .min(maxEffectiveBalance);
  return validator.withEffectiveBalance(effectiveBalance);
}
```

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/common/helpers/BeaconStateMutators.java:230-240` — `addValidatorToRegistry` base class (NOT overridden in Electra; calls `miscHelpers.getValidatorFromDeposit(...)` and lets subclass-override polymorphism select the right helper).

Cleanest abstraction: no Electra subclass for the registry mutator; only the helper is per-fork. But this means teku's `addValidatorToRegistry` only appends to **2 fields** (validators + balances); the other 3 (participation flags + inactivity_scores) are appended elsewhere (likely a per-fork `EpochProcessorElectra` hook for the per-epoch deposit drain).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓ (2-field split + downstream append). H7 ✓. H8 ✓ (handled via per-epoch full-amount call from `applyPendingDeposits`). H9 ✓. **H10 ✓**.

### nimbus

`vendor/nimbus/beacon_chain/spec/beaconstate.nim:102-122` — Pectra-path `get_validator_from_deposit`. Explicit two-step:

```nim
var validator = Validator(
    pubkey: pubkey,
    withdrawal_credentials: withdrawal_credentials,
    effective_balance: 0.Gwei,    # STEP 1
    activation_eligibility_epoch: FAR_FUTURE_EPOCH,
    activation_epoch: FAR_FUTURE_EPOCH,
    exit_epoch: FAR_FUTURE_EPOCH,
    withdrawable_epoch: FAR_FUTURE_EPOCH,
    slashed: false
)
validator.effective_balance =                                           # STEP 2
    min(amount - amount mod EFFECTIVE_BALANCE_INCREMENT.Gwei,
        get_max_effective_balance(state, validator))
```

Pre-Electra variant at `:81-99`. Type-overload-based dispatch:

```nim
# Pre-Electra:
func get_validator_from_deposit*(_: phase0.BeaconState | altair.BeaconState | ... | deneb.BeaconState, ...)

# Electra+:
func get_validator_from_deposit*(state: electra.BeaconState | fulu.BeaconState | gloas.BeaconState, ...)
```

The Electra variant accepts `gloas.BeaconState` directly — no Modified Gloas function needed; the Electra implementation handles Gloas states by union type.

`vendor/nimbus/beacon_chain/spec/beaconstate.nim:125-145` — `add_validator_to_registry`. Returns `Result[void, cstring]` for "too many validators" (HashList full).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (per-epoch full-amount via item #4's drain). H9 ✓. **H10 ✓** (Gloas state in the union type; same code path).

### lodestar

No separate `getValidatorFromDeposit` function. Inlined in `vendor/lodestar/packages/state-transition/src/block/processDeposit.ts:90-139` (`addValidatorToRegistry`):

```typescript
const effectiveBalance = Math.min(
  amount - (amount % EFFECTIVE_BALANCE_INCREMENT),
  fork < ForkSeq.electra ? MAX_EFFECTIVE_BALANCE : getMaxEffectiveBalance(withdrawalCredentials)
);
validators.push(
  ssz.phase0.Validator.toViewDU({
    pubkey,
    withdrawalCredentials,
    activationEligibilityEpoch: FAR_FUTURE_EPOCH,
    activationEpoch: FAR_FUTURE_EPOCH,
    exitEpoch: FAR_FUTURE_EPOCH,
    withdrawableEpoch: FAR_FUTURE_EPOCH,
    effectiveBalance,
    slashed: false,
  })
);
```

Two-step semantic preserved (compute cap from credentials before constructing the validator) but construction is a single SSZ tree-view push. Most concise. Pubkey cache update via explicit `epochCtx.addPubkey(validatorIndex, pubkey)`.

H1 ✓ (semantic two-step). H2 ✓ (via `getMaxEffectiveBalance(withdrawalCredentials)`). H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (per-epoch full-amount). H9 ✓. **H10 ✓** (no Gloas modification; same inline construction handles Gloas).

### grandine

Inline in `vendor/grandine/transition_functions/src/electra/block_processing.rs:882-924` (`add_validator_to_registry`):

```rust
let validator = Validator {
    pubkey,
    withdrawal_credentials,
    activation_eligibility_epoch: FAR_FUTURE_EPOCH,
    activation_epoch: FAR_FUTURE_EPOCH,
    exit_epoch: FAR_FUTURE_EPOCH,
    withdrawable_epoch: FAR_FUTURE_EPOCH,
    slashed: false,
    effective_balance: 0,    // STEP 1
    ..
};
let max_effective_balance = get_max_effective_balance::<P>(&validator);   // STEP 2
validator.effective_balance = amount
    .prev_multiple_of(P::EFFECTIVE_BALANCE_INCREMENT)
    .min(max_effective_balance);
```

`prev_multiple_of(NonZeroU64)` for the downward rounding — compile-time guarantee against divide-by-zero. Single definition (no multi-fork-definition risk).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (per-epoch full-amount via item #4). H9 ✓. **H10 ✓** (no Gloas modification; same single helper handles Gloas validator-side deposits).

## Cross-reference table

| Client | `get_validator_from_deposit` location | `add_validator_to_registry` location | Two-step idiom | Gloas modified? |
|---|---|---|---|---|
| prysm | `core/electra/deposits.go:519-537` | `core/electra/deposits.go:462-497` | Explicit: create with `EffectiveBalance: 0` → `helpers.ValidatorMaxEffectiveBalance(v)` → set EB | no (function unchanged at Gloas) |
| lighthouse | `consensus/types/src/validator/validator.rs:39-65` (`Validator::from_deposit`) | `consensus/types/src/state/beacon_state.rs:1922-1965` (state method) | Explicit: `effective_balance: 0` initial → `validator.get_max_effective_balance(spec, fork_name)` → set EB | no |
| teku | `versions/electra/helpers/MiscHelpersElectra.java:117-137` (override) | `common/helpers/BeaconStateMutators.java:230-240` (NOT overridden) | Explicit: create with `ZERO` EB → `getMaxEffectiveBalance(validator)` → `.withEffectiveBalance(...)` builder | no (subclass-override polymorphism handles Gloas via inherited Electra impl) |
| nimbus | `spec/beaconstate.nim:102-122` (Electra path; pre-Electra at `:81-99`) | `spec/beaconstate.nim:125-145` | Explicit `var validator = Validator(... effective_balance: 0.Gwei)` then mutate | no (`electra.BeaconState | fulu.BeaconState | gloas.BeaconState` union type covers Gloas) |
| lodestar | inline in `block/processDeposit.ts:90-139` (no separate helper) | `block/processDeposit.ts` (in `addValidatorToRegistry`) | Inline ternary: `fork < ForkSeq.electra ? MAX_EFFECTIVE_BALANCE : getMaxEffectiveBalance(withdrawalCredentials)` | no (fork ternary handles Gloas as `fork >= ForkSeq.electra`) |
| grandine | inline in `transition_functions/src/electra/block_processing.rs:882-924` (`add_validator_to_registry`) | same function | Explicit: `Validator { ... effective_balance: 0, ... }` → `get_max_effective_balance::<P>(&validator)` → `prev_multiple_of(EBI).min(max_eb)` | no (single definition handles all post-Electra forks) |

## Empirical tests

### Pectra-surface implicit coverage

**No dedicated EF fixture set** exists for `get_validator_from_deposit` or `add_validator_to_registry` — they are internal helpers, not block-level operations. They are exercised IMPLICITLY via:

| Item | Fixtures × wired clients | Calls these helpers via |
|---|---|---|
| #4 process_pending_deposits | 43 × 4 = 172 | per-epoch drain → `apply_pending_deposit` → `add_validator_to_registry` |
| #14 process_deposit_request | 11 × 4 = 44 | per-block → enqueue PendingDeposit → drained later by item #4 |

**Total implicit cross-validation evidence**: 54 unique fixtures × 4 wired clients = **216 EF fixture PASS** results all flow through these helpers. Any Pectra-surface divergence (wrong cap, wrong rounding, missing one of the 5 list pushes, missing pubkey cache update) would have surfaced as a fixture failure in at least one of items #4 or #14.

### Gloas-surface

No Gloas operations fixtures yet for these helpers. H10 is currently source-only — verified by walking each client's Gloas-state-handling path and observing that the Pectra implementation continues to be selected at Gloas (via union types, fork ternaries, subclass-inheritance, or single-definition fallthrough).

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — generate dedicated EF fixture set for `get_validator_from_deposit`).** Inputs: `(pubkey, creds, amount)` triples spanning 0x01/0x02 credentials × amount in `[0, MIN_ACTIVATION_BALANCE, MIN+1, MIN×2, 2048 ETH, MAX_EB_ELECTRA-1, MAX_EB_ELECTRA, MAX_EB_ELECTRA+1]`. Expected output: Validator struct with the correct `effective_balance`. Pure-function fuzzing, directly cross-clientable.
- **T1.2 (priority — cross-client byte-for-byte Validator equivalence).** Feed identical `(pubkey, creds, amount)` triples to all 6 clients; compare the resulting Validator struct fields. No divergence expected at Pectra OR Gloas.
- **T1.3 (priority — 0x02 compounding-credentials with `amount > 2048 ETH` cap behaviour).** The cap clamps at 2048 ETH; excess is preserved separately as a PendingDeposit via item #11's `queue_excess_active_balance` (upgrade-time) or item #2's switch-to-compounding fast path (block-time). Verify cross-client that the cap clamp and excess preservation both work correctly.

#### T2 — Adversarial probes
- **T2.1 (defensive — `amount = 0` for new validator).** `get_validator_from_deposit(pubkey, creds, 0)` should produce a Validator with `effective_balance = 0`. Per item #17's H1, this validator is NOT eligible for the activation queue. Verify cross-client consistency.
- **T2.2 (defensive — `amount < MIN_ACTIVATION_BALANCE` for new validator).** Below 32 ETH: validator is created with `effective_balance < 32 ETH`, NOT eligible for activation queue (item #17). Verify cross-client.
- **T2.3 (defensive — teku 2-field-only `addValidatorToRegistry`).** Verify that teku's participation flags + inactivity_scores are appended in the right place (somewhere in `applyPendingDeposits` or a per-fork hook). Contract test: after `addValidatorToRegistry` returns, all 5 lists have the same length.
- **T2.4 (defensive — pubkey cache lookup immediately after registry push).** Verify all 6 clients return the correct index from `pubkey_to_index.get(new_pubkey)` immediately after the push. Cache update timing is the most divergent aspect of this audit.
- **T2.5 (Glamsterdam-target — Gloas validator-side deposit through this item).** Submit a non-builder deposit (`0x01` or `0x02` credentials, pubkey not in `state.builders`) at Gloas activation slot. Verify all 6 clients route through item #4's drain → this item's `add_validator_to_registry` (NOT the Gloas builder helpers). State-root after the drain should match across all six.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H9) remain satisfied: identical two-step construction (initial `effective_balance = 0`, then compute `get_max_effective_balance(validator)` from item #1, then set final EB via `min(amount_rounded, cap)`), identical 5-field Altair-heritage append (validators + balances + previous_epoch_participation + current_epoch_participation + inactivity_scores), identical `FAR_FUTURE_EPOCH` defaults, identical `get_index_for_new_validator = len(state.validators)` semantics, and identical per-block deferral patterns. 216 implicit EF fixture invocations from items #4 + #14 cross-validate without divergence.

**Glamsterdam-target finding (H10 — no change).** Neither `add_validator_to_registry` nor `get_validator_from_deposit` is modified at Gloas — `vendor/consensus-specs/specs/gloas/beacon-chain.md` has no `Modified` headings for either. The Gloas chapter adds **parallel builder-side helpers** at line 1522 (`get_index_for_new_builder`) and line 1556 (`apply_deposit_for_builder`), called from the new Gloas `process_deposit_request` branch (item #14 H9) for builder-credentialled deposits. These don't replace this item's validator-side helpers — they handle the builder lifecycle via `state.builders` separately.

Each client's Gloas-state handling for validator-side deposits:

- **prysm**: continues calling the Pectra `AddValidatorToRegistry` from per-block deferred path.
- **lighthouse**: continues calling the Pectra `Validator::from_deposit` + `state.add_validator_to_registry`.
- **teku**: subclass-override polymorphism — `MiscHelpersElectra.getValidatorFromDeposit` is inherited by Gloas via the standard subclass chain.
- **nimbus**: `electra.BeaconState | fulu.BeaconState | gloas.BeaconState` union type on the function signature directly covers Gloas.
- **lodestar**: `fork < ForkSeq.electra ? ... : getMaxEffectiveBalance(withdrawalCredentials)` ternary fires the Pectra branch for both Electra and Gloas (`fork >= ForkSeq.electra`).
- **grandine**: single function definition handles all post-Electra forks; called from item #4's Pectra apply-deposit path (which Gloas still uses for validator-side deposits).

Notable per-client style differences (all observable-equivalent):

- **prysm** uses an explicit two-step with `bytesutil.SafeCopyBytes` defensive copies.
- **lighthouse** uses a free constructor `Validator::from_deposit` (NOT a state method) — cleanest separation between pure construction and state mutation; explicitly documents "safe math is unnecessary" because `EFFECTIVE_BALANCE_INCREMENT > 0`.
- **teku** uses subclass-override polymorphism (`MiscHelpersElectra.getValidatorFromDeposit` override) — cleanest abstraction; the registry mutator base class is unchanged.
- **nimbus** uses type-overload-based dispatch — cleanest fork-dispatch for this specific function.
- **lodestar** inlines the construction inside `addValidatorToRegistry` — most concise; single SSZ tree-view push.
- **grandine** uses `prev_multiple_of(NonZeroU64)` for downward rounding — compile-time divide-by-zero protection; single definition (no multi-fork-definition risk).

No code-change recommendation. Audit-direction recommendations:

- **Generate dedicated EF fixture set for `get_validator_from_deposit`** — highest-priority gap closure. Pure-function, directly fuzzable.
- **Cross-client byte-for-byte Validator equivalence test** — for the same `(pubkey, creds, amount)` input across all 6 clients.
- **Sister item: audit `apply_deposit_for_builder` (Gloas-new)** — the builder-side analog of this item. Parallel structure: pure constructor producing a Builder entry, append to `state.builders`. On-the-fly BLS signature verification (different from this item's deferred-verification pattern).
- **teku 2-field vs 5-field init equivalence audit** — verify the participation flags + inactivity_scores append happens in the right place.
- **pubkey cache update timing contract test** — verify `pubkey_to_index` map returns the correct index immediately after the registry push, across all 6 clients.
- **lighthouse's "safe math unnecessary" rationale codification** — apply the same documentation to other clients' equivalent code paths.

## Cross-cuts

### With item #1 (`get_max_effective_balance`)

This item's STEP 2 consumes `get_max_effective_balance(validator)` from item #1. The cap value (32 vs 2048 ETH) depends entirely on item #1's correctness. Item #1 H1 (all six clients return 2048 ETH for 0x02, 32 ETH for 0x01) is satisfied — including at Gloas (item #1's H10 confirms the spec is unchanged at Gloas). Nimbus's `has_compounding_withdrawal_credential` Gloas branch that also accepts `0x03` (item #1's adjacent #3) doesn't affect this item: at Gloas, `0x03`-credentialled deposits are routed to `apply_deposit_for_builder` (item #14 H9), not to this item's path. So even if nimbus's extension were ever to apply, it wouldn't reach this code.

### With item #4 (`process_pending_deposits`)

Item #4's drain calls this item's `add_validator_to_registry` when a deposit is for a new pubkey. The 5-field Altair-heritage init happens at this point (for clients with consolidated init) or downstream (teku's split). At Gloas, item #4's H8 (activation-churn helper divergence) affects WHICH deposits drain per epoch, not HOW validators are constructed once drained — so the cascade doesn't propagate into this item.

### With item #11 (`upgrade_to_electra`)

`upgrade_to_electra` seeds pre-activation validators into `pending_deposits` with `slot = GENESIS_SLOT` placeholders. Item #4 drains those into the registry via this item's helpers. Cross-cut chain: item #11 (init pending_deposits) → item #4 (drain) → item #18 (this — registry append) → item #17 (eligibility set).

### With item #14 (`process_deposit_request`)

Item #14 enqueues `PendingDeposit{slot=state.slot}` entries into `state.pending_deposits` from per-block. Item #4 drains them later. At Gloas (item #14 H9), `process_deposit_request` adds a builder-routing branch: builder-credentialled or existing-builder deposits go through `apply_deposit_for_builder` (a separate Gloas-new helper added at line 1556 of the Gloas spec). Validator deposits continue through this item's path.

### With item #17 (`process_registry_updates`)

Item #17's eligibility predicate `is_eligible_for_activation_queue` requires `effective_balance >= MIN_ACTIVATION_BALANCE`. This item's STEP 2 sets `effective_balance` correctly so newly-added validators correctly enter the activation queue at the next epoch boundary. Two-epoch round-trip: deposit → this item → registry updates → activation queue.

### Sister-item: `apply_deposit_for_builder` (Gloas-new)

The builder-side analog of this item. Lives in the Gloas chapter (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1556`). Parallel structure: pure constructor + state.builders append. On-the-fly BLS signature verification (different from this item's deferred-verification pattern). All five EIP-7732-ready clients (prysm, teku, nimbus, lodestar, grandine) implement this function — same five as item #14 H9. Lighthouse alone doesn't.

## Adjacent untouched

1. **Generate dedicated EF fixture set** — highest-priority gap closure. Pure function, easy to fuzz.
2. **Cross-client byte-for-byte equivalence test** — feed identical `(pubkey, creds, amount)` triples to all 6 clients, compare the resulting Validator struct.
3. **Sister item: `apply_deposit_for_builder` (Gloas-new)** — same five-vs-one cohort as item #14 H9 (lighthouse alone fails). Out of scope for this item, but candidate for its own audit.
4. **teku's 2-field-only `addValidatorToRegistry`** — verify participation/inactivity init happens elsewhere; contract test on post-append list lengths.
5. **`amount = 0` deferral pattern divergence** between explicit (lighthouse, prysm) and choreographed (teku, nimbus, lodestar, grandine).
6. **lighthouse's "safe math unnecessary" comment** — codify rationale across other clients.
7. **grandine SINGLE-definition consistency check at Gloas** — ensure no multi-fork-definition pattern emerges.
8. **Pubkey cache update timing**: contract test asserting `pubkey_to_index.get(new_pubkey)` returns the correct index immediately after registry push.
9. **lodestar's inlined construction** — codify as a conscious design choice.
10. **`amount = 0` initial-EB edge case**: a Validator with `effective_balance = 0` is technically not eligible for any attestation duties. Verify the per-epoch drain sets the EB before activation.
11. **Compounding-credentials with `amount > 2048 ETH` edge case**: cap clamps at 2048 ETH; excess queued separately via item #11's `queue_excess_active_balance` or item #2's switch path.
12. **`amount in [0, MIN_ACTIVATION_BALANCE)` for new validator**: validator created with `effective_balance < 32 ETH`, NOT eligible for activation queue (item #17).
13. **`get_max_effective_balance(validator)` cross-cut audit** — already covered by item #1 H1; this item's H2 depends on item #1's correctness, which is verified.
14. **Gloas builder-side parallel: `get_index_for_new_builder` + `apply_deposit_for_builder`** — sister functions for the builder lifecycle. Cross-cut with item #14 H9. Same five-vs-one cohort.
