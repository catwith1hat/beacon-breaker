---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: []
eips: [EIP-7251]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 1: `process_effective_balance_updates` Pectra hysteresis with `MAX_EFFECTIVE_BALANCE_ELECTRA`

## Summary

Per-epoch routine that snaps each validator's stored `effective_balance` to a quantized version of its current `balance`. Pectra (EIP-7251) replaced the single `MAX_EFFECTIVE_BALANCE` (32 ETH) cap with a per-validator `get_max_effective_balance(validator)` returning 2048 ETH for `0x02` (compounding) credentials and 32 ETH for legacy `0x00`/`0x01`. A 1-gwei divergence here propagates immediately to the post-state state-root.

All six clients implement the Pectra surface identically modulo coding idioms; the cross-client fixture `effective_balance_increase_changes_lookahead` (Electra mainnet sanity) produces the same post-state SHA-256 byte-for-byte. **No divergence on the Pectra surface, which is the surface that is in force at the Glamsterdam target** — the Gloas spec (consensus-specs `v1.7.0-alpha.7`) does not modify `process_effective_balance_updates`, `get_max_effective_balance`, or `has_compounding_withdrawal_credential`. One latent Gloas-conditional source-level difference in nimbus is documented under "Adjacent" and tracked as a separate follow-up item.

## Question

Pectra (EIP-7251) replaces the constant ceiling in `process_effective_balance_updates` with a credential-dependent ceiling. Pyspec (`vendor/consensus-specs/specs/electra/beacon-chain.md`):

```python
def process_effective_balance_updates(state: BeaconState) -> None:
    for index, validator in enumerate(state.validators):
        balance = state.balances[index]
        HYSTERESIS_INCREMENT = uint64(EFFECTIVE_BALANCE_INCREMENT // HYSTERESIS_QUOTIENT)
        DOWNWARD_THRESHOLD = HYSTERESIS_INCREMENT * HYSTERESIS_DOWNWARD_MULTIPLIER
        UPWARD_THRESHOLD = HYSTERESIS_INCREMENT * HYSTERESIS_UPWARD_MULTIPLIER
        max_effective_balance = get_max_effective_balance(validator)  # 32 or 2048 ETH

        if (balance + DOWNWARD_THRESHOLD < validator.effective_balance
            or validator.effective_balance + UPWARD_THRESHOLD < balance):
            validator.effective_balance = min(
                balance - balance % EFFECTIVE_BALANCE_INCREMENT, max_effective_balance)
```

with `get_max_effective_balance` (`consensus-specs/specs/electra/beacon-chain.md`):

```python
def get_max_effective_balance(validator: Validator) -> Gwei:
    if has_compounding_withdrawal_credential(validator):
        return MAX_EFFECTIVE_BALANCE_ELECTRA  # 2048 ETH
    else:
        return MIN_ACTIVATION_BALANCE          # 32 ETH
```

and `has_compounding_withdrawal_credential(validator) ≡ validator.withdrawal_credentials[0] == 0x02`.

The hypothesis: *the six clients implement the same predicate with the same constants and the same clamp formula, modulo coding idioms.*

**Consensus relevance**: `effective_balance` participates in `hash_tree_root(state.validators)` and feeds attestation reward calculation, sync-committee selection weighting, and slashing quanta. A 1-gwei divergence on a single validator changes the state-root immediately at the next epoch boundary, which is canonical-reachable on every block.

**Glamsterdam-target note**: the Gloas chapter of `consensus-specs v1.7.0-alpha.7` defines a new `is_builder_withdrawal_credential` (matching the `0x03` `BUILDER_WITHDRAWAL_PREFIX`) but does **not** modify `has_compounding_withdrawal_credential` and does **not** wire builder credentials into `get_max_effective_balance`. Per spec, `0x03`-credentialled validators still receive `MIN_ACTIVATION_BALANCE` from the cap selector. See "Adjacent" for the one client (nimbus) that pre-emptively extends `has_compounding_withdrawal_credential` at the Gloas fork gate.

## Hypotheses

- **H1.** All six clients return `MAX_EFFECTIVE_BALANCE_ELECTRA = 2_048 × 10⁹ gwei` from `get_max_effective_balance` when the validator's `withdrawal_credentials[0] == 0x02`, and `MIN_ACTIVATION_BALANCE = 32 × 10⁹ gwei` otherwise.
- **H2.** All six compute the hysteresis predicate `(balance + DOWNWARD < EB) ∨ (EB + UPWARD < balance)` with `DOWNWARD = 0.25 ETH` and `UPWARD = 1.25 ETH`, and only update on either trigger.
- **H3.** When the predicate fires, all six set `effective_balance := min(balance − balance mod 10⁹, max_effective_balance)`, i.e. round balance down to the nearest gwei billion and clamp at the per-validator cap.

## Findings

H1, H2, H3 satisfied. **No divergence in source-level predicate, no divergence on the cross-client fixture run.**

### prysm

`vendor/prysm/beacon-chain/core/electra/effective_balance_updates.go:32-63`:

```go
func ProcessEffectiveBalanceUpdates(st state.BeaconState) error {
    effBalanceInc := params.BeaconConfig().EffectiveBalanceIncrement
    hysteresisInc := effBalanceInc / params.BeaconConfig().HysteresisQuotient
    downwardThreshold := hysteresisInc * params.BeaconConfig().HysteresisDownwardMultiplier
    upwardThreshold := hysteresisInc * params.BeaconConfig().HysteresisUpwardMultiplier
    // ... per-validator:
    effectiveBalanceLimit := params.BeaconConfig().MinActivationBalance
    if val.HasCompoundingWithdrawalCredentials() {
        effectiveBalanceLimit = params.BeaconConfig().MaxEffectiveBalanceElectra
    }
    if balance+downwardThreshold < val.EffectiveBalance() || val.EffectiveBalance()+upwardThreshold < balance {
        effectiveBal := min(balance-balance%effBalanceInc, effectiveBalanceLimit)
```

H1 ✓ — `HasCompoundingWithdrawalCredentials` at `vendor/prysm/beacon-chain/state/state-native/readonly_validator.go:99-101` (`WithdrawalCredentials[0] == params.BeaconConfig().CompoundingWithdrawalPrefixByte`).
H2 ✓ — predicate matches pyspec verbatim.
H3 ✓ — `min(balance-balance%effBalanceInc, effectiveBalanceLimit)`.

The Electra-specific function lives in its own `electra/` package; there is no in-function fork gate — the call site (epoch processor dispatcher) selects this implementation post-Pectra.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_epoch_processing/single_pass.rs:1241-1254`:

```rust
let effective_balance_limit = validator.get_max_effective_balance(spec, state_ctxt.fork_name);
let new_effective_balance = if balance.safe_add(eb_ctxt.downward_threshold)?
    < validator.effective_balance
    || validator.effective_balance.safe_add(eb_ctxt.upward_threshold)? < balance
{
    min(
        balance.safe_sub(balance.safe_rem(spec.effective_balance_increment)?)?,
        effective_balance_limit,
    )
} else {
    validator.effective_balance
};
```

H1 ✓ — `Validator::get_max_effective_balance` at `vendor/lighthouse/consensus/types/src/validator/validator.rs:282-294` takes an explicit `current_fork: ForkName` and branches `if current_fork >= ForkName::Electra` (pre-Electra returns `spec.max_effective_balance`).
H2 ✓ — `safe_add` is overflow-checked but mathematically the same.
H3 ✓ — `balance.safe_sub(balance.safe_rem(EBI)?)?` is `balance − balance mod EBI`.

`is_compounding_withdrawal_credential` at `vendor/lighthouse/consensus/types/src/validator/validator.rs:311-320` uses `.first().map(...).unwrap_or(false)` — the only client that defends against a zero-length credentials slice.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/statetransition/epoch/EpochProcessorElectra.java:148-183`:

```java
public void processEffectiveBalanceUpdates(...) {
    final UInt64 hysteresisIncrement = effectiveBalanceIncrement.dividedBy(hysteresisQuotient);
    for (int index = 0; index < statuses.size(); index++) {
        final UInt64 balance = balances.getElement(index);
        final Validator validator = validators.get(index);
        final UInt64 maxEffectiveBalance = getEffectiveBalanceLimitForValidator(validator);
        if (shouldDecreaseEffectiveBalance(...) || shouldIncreaseEffectiveBalance(...)) {
            final UInt64 newEffectiveBalance =
                effectiveBalanceLimit.min(balance.minus(balance.mod(effectiveBalanceIncrement)).min(maxEffectiveBalance));
            validators.set(index, validator.withEffectiveBalance(newEffectiveBalance));
        }
    }
}
```

H1 ✓ — `MiscHelpersElectra.getMaxEffectiveBalance` at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/MiscHelpersElectra.java:110-114` (ternary on `predicatesElectra.hasCompoundingWithdrawalCredential(validator)`).
H2 ✓ — predicate factored into `shouldDecreaseEffectiveBalance` / `shouldIncreaseEffectiveBalance` helpers; same arithmetic.
H3 ✓ — but with a curious extra `effectiveBalanceLimit.min(...)` outside the inner `min(maxEffectiveBalance)`. Both clamps reduce to the same value because `effectiveBalanceLimit = maxEffectiveBalance` in the dispatch context; the outer `.min(...)` is dead code post-Pectra. Worth flagging as `Adjacent untouched` for a "redundant min" sweep.

`PredicatesElectra.isCompoundingWithdrawalCredential` at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/PredicatesElectra.java:108-120` (`withdrawalCredentials.get(0) == COMPOUNDING_WITHDRAWAL_BYTE`, `= 0x02` per `WithdrawalPrefixes.java:25`); safe by `Bytes32` type. `PredicatesGloas` at `.../versions/gloas/helpers/PredicatesGloas.java` extends `PredicatesElectra` but does **not** override `hasCompoundingWithdrawalCredential` — at Gloas, the Pectra predicate is inherited unchanged.

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_epoch.nim:1022-1034`:

```nim
func process_effective_balance_updates*(state: var ForkyBeaconState) =
  for vidx in state.validators.vindices:
    let balance = state.balances.item(vidx)
        effective_balance = state.validators.item(vidx).effective_balance
    if effective_balance_might_update(balance, effective_balance):
      let new_effective_balance = get_effective_balance_update(
        typeof(state).kind, balance, effective_balance, vidx.distinctBase)
      if new_effective_balance != effective_balance:
        state.validators.mitem(vidx).effective_balance = new_effective_balance
```

Generic over `ForkyBeaconState`; the hysteresis predicate and clamp live in `effective_balance_might_update` / `get_effective_balance_update` templates. Static fork dispatch via `typeof(state).kind`.

H1 ✓ — `get_max_effective_balance` at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:71-77` (`static ConsensusFork` parameter; ternary on compounding).
H2 ✓.
H3 ✓.

**Gloas-conditional source-level difference.** `has_compounding_withdrawal_credential` at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:59-68` is the only implementation that fork-gates the predicate itself:

```nim
when consensusFork >= ConsensusFork.Gloas:
    ## Check if ``validator`` has an 0x02 or 0x03 prefixed withdrawal credential.
    is_compounding_withdrawal_credential(validator.withdrawal_credentials) or
        is_builder_withdrawal_credential(validator.withdrawal_credentials)
else:
    is_compounding_withdrawal_credential(validator.withdrawal_credentials)
```

The Nimbus source comment cites `gloas/beacon-chain.md#modified-has_compounding_withdrawal_credential` against `v1.6.0-beta.0`, but no such "Modified" section exists in the spec checkout (`v1.7.0-alpha.7`): Gloas only adds the *new* `is_builder_withdrawal_credential` predicate (`vendor/consensus-specs/specs/gloas/beacon-chain.md:487-492`) and does not rewire `get_max_effective_balance`. For the Pectra surface this branch is dead (`consensusFork < Gloas`); at Gloas activation it becomes a unilateral interpretation. Whether it materialises as a state-root divergence depends on whether `0x03`-credentialled entries ever appear in `state.validators` (Gloas keeps builders in a separate `builders` field gated by `BUILDER_INDEX_FLAG`, suggesting normally they do not). Out of scope for this item; tracked under "Adjacent" as a Gloas-specific follow-up.

### lodestar

`vendor/lodestar/packages/state-transition/src/epoch/processEffectiveBalanceUpdates.ts:28-111`:

```typescript
const HYSTERESIS_INCREMENT = EFFECTIVE_BALANCE_INCREMENT / HYSTERESIS_QUOTIENT;
const DOWNWARD_THRESHOLD = HYSTERESIS_INCREMENT * HYSTERESIS_DOWNWARD_MULTIPLIER;
const UPWARD_THRESHOLD = HYSTERESIS_INCREMENT * HYSTERESIS_UPWARD_MULTIPLIER;
// ...
let effectiveBalanceLimit: number;
if (fork < ForkSeq.electra) {
    effectiveBalanceLimit = MAX_EFFECTIVE_BALANCE;
} else {
    effectiveBalanceLimit = isCompoundingValidatorArr[i] ? MAX_EFFECTIVE_BALANCE_ELECTRA : MIN_ACTIVATION_BALANCE;
}
if (effectiveBalance > balance + DOWNWARD_THRESHOLD ||
    (effectiveBalance < effectiveBalanceLimit && effectiveBalance + UPWARD_THRESHOLD < balance)) {
    effectiveBalance = Math.min(balance - (balance % EFFECTIVE_BALANCE_INCREMENT), effectiveBalanceLimit);
```

H1 ✓ — `isCompoundingValidatorArr[i]` is a pre-cached `0x02` check populated from `hasCompoundingWithdrawalCredential` at `vendor/lodestar/packages/state-transition/src/util/electra.ts:7-9` (write-sites at `vendor/lodestar/packages/state-transition/src/cache/epochTransitionCache.ts:306` and `vendor/lodestar/packages/state-transition/src/block/processPendingDeposits.ts:124`). No Gloas-specific override of `hasCompoundingWithdrawalCredential`; `isBuilderWithdrawalCredential` exists in `vendor/lodestar/packages/state-transition/src/util/gloas.ts:24` but is not consulted by the EB cap.
H2 — **subtle restatement**. The upward branch carries an extra `effectiveBalance < effectiveBalanceLimit` guard that pyspec lacks. Pyspec relies on the `min(..., max_effective_balance)` clamp to absorb the case where `balance` is well above the cap. Lodestar's guard short-circuits that case before the clamp. Output is identical (in both, `effective_balance` ends up at `effectiveBalanceLimit`); the predicate's truth table differs at exactly `EB == limit ∧ balance > EB + UPWARD`. **No divergence in observable state.**
H3 ✓ — `Math.min(balance - (balance % EFFECTIVE_BALANCE_INCREMENT), effectiveBalanceLimit)`.

Lodestar is also the only client using JavaScript `number` arithmetic (53-bit mantissa). Gwei values fit comfortably below 2⁵³ (max gwei in 1-validator scope is 2048 × 10⁹ ≈ 2⁴¹), but a sum across the full registry could in principle approach the limit; outside this item's scope.

### grandine

`vendor/grandine/transition_functions/src/electra/epoch_processing.rs:421-451`:

```rust
pub fn process_effective_balance_updates<P: Preset>(state: &mut impl PostElectraBeaconState<P>) {
    let hysteresis_increment = P::EFFECTIVE_BALANCE_INCREMENT.get() / P::HYSTERESIS_QUOTIENT;
    let downward_threshold = hysteresis_increment * P::HYSTERESIS_DOWNWARD_MULTIPLIER;
    let upward_threshold = hysteresis_increment * P::HYSTERESIS_UPWARD_MULTIPLIER;
    let (validators, balances) = state.validators_mut_with_balances();
    let mut balances = balances.into_iter().copied();
    validators.update(|validator| {
        let max_effective_balance = get_max_effective_balance::<P>(validator);
        let balance = balances.next().expect(...);
        let below = balance + downward_threshold < validator.effective_balance;
        let above = validator.effective_balance + upward_threshold < balance;
        if below || above {
            validator.effective_balance = balance
                .prev_multiple_of(P::EFFECTIVE_BALANCE_INCREMENT)
                .min(max_effective_balance);
        }
    });
}
```

H1 ✓ — `get_max_effective_balance` at `vendor/grandine/helper_functions/src/misc.rs:819-825` (calls `predicates::has_compounding_withdrawal_credential`). `has_compounding_withdrawal_credential` at `vendor/grandine/helper_functions/src/predicates.rs:392-394` is *not* Gloas-aware; the separate `has_builder_withdrawal_credential` at `vendor/grandine/helper_functions/src/predicates.rs:410-414` exists for the builder predicate but is not consulted by the EB cap selector. `is_compounding_withdrawal_credential` at `predicates.rs:384-389` uses `.starts_with(COMPOUNDING_WITHDRAWAL_PREFIX)` (`&[u8] = &hex!("02")`), safe on empty-slice.
H2 ✓.
H3 ✓ — `balance.prev_multiple_of(EBI)` is mathematically `balance − balance mod EBI` for `EBI > 0` (and `EFFECTIVE_BALANCE_INCREMENT` is typed `NonZeroU64` at compile time, so the divisor-zero footgun is eliminated structurally).

The trait bound `PostElectraBeaconState<P>` makes this function unreachable for pre-Pectra states by construction.

## Cross-reference table

| Client | EB-update file:line | `get_max_effective_balance` | `is_compounding` predicate | EBI/Hyst constants | Fork-gating mechanism |
|---|---|---|---|---|---|
| prysm | `beacon-chain/core/electra/effective_balance_updates.go:32-63` | `core/helpers/validators.go:658-663` | `state/state-native/readonly_validator.go:99-101` (`creds[0] == prefix`) | `config/params/mainnet_config.go` (literals) | Separate `electra/` Go package |
| lighthouse | `consensus/state_processing/src/per_epoch_processing/single_pass.rs:1241-1254` | `consensus/types/src/validator/validator.rs:282-294` | `consensus/types/src/validator/validator.rs:311-320` (`.first().unwrap_or(false)`) | `consensus/types/src/chain_spec.rs` (computed via `checked_pow`) | Explicit `current_fork: ForkName` arg |
| teku | `.../electra/statetransition/epoch/EpochProcessorElectra.java:148-183` | `.../electra/helpers/MiscHelpersElectra.java:110-114` | `.../electra/helpers/PredicatesElectra.java:108-120` (`Bytes32.get(0) == byte`); `PredicatesGloas` does not override | `WithdrawalPrefixes.java:25`, `SpecConfigElectra.java` (config getters) | `EpochProcessorElectra` subclass dispatch |
| nimbus | `beacon_chain/spec/state_transition_epoch.nim:1022-1034` | `beacon_chain/spec/beaconstate.nim:71-77` | `beacon_chain/spec/beaconstate.nim:59-68` (`array[0] == prefix`, **fork-gated for Gloas — see Adjacent**) | `presets/mainnet/{phase0,electra}_preset.nim`, `datatypes/constants.nim` | Static `ConsensusFork` param + `typeof(state).kind` |
| lodestar | `packages/state-transition/src/epoch/processEffectiveBalanceUpdates.ts:28-111` | inline ternary | `packages/state-transition/src/util/electra.ts:7-9` (`Uint8Array[0] === prefix`); `util/gloas.ts:24` defines `isBuilderWithdrawalCredential` separately (not used by EB cap) | `packages/params/src/presets/mainnet.ts` (literals) | `if (fork < ForkSeq.electra)` runtime branch |
| grandine | `transition_functions/src/electra/epoch_processing.rs:421-451` | `helper_functions/src/misc.rs:819-825` | `helper_functions/src/predicates.rs:392-394` (calls `is_compounding_withdrawal_credential` at 384-389, `.starts_with(&[0x02])`); `has_builder_withdrawal_credential` at 410-414 is separate (not used by EB cap) | `types/src/preset.rs` (`NonZeroU64` for divisors) | `PostElectraBeaconState<P>` trait bound |

## Empirical tests

### Fixture run

`fixture/`: deferred — used the existing EF state-test fixture
`consensus-spec-tests/tests/mainnet/electra/sanity/blocks/pyspec_tests/effective_balance_increase_changes_lookahead/` (32 blocks; pre-state has validators near the hysteresis boundary; post-state's `effective_balance` field reflects the hysteresis transitions).

Run via `scripts/run_fixture.sh` against all six clients on 2026-05-02:

```
prysm:       PASS  OK (TestMainnet_Electra_Sanity_Blocks/effective_balance_increase_changes_lookahead)
lighthouse:  PASS  OK aec719af6530b4e79d385e16021c40be5e04ea93c8411e01d0ea12b4786c9de2
teku:        PASS  OK aec719af6530b4e79d385e16021c40be5e04ea93c8411e01d0ea12b4786c9de2
nimbus:      PASS  OK aec719af6530b4e79d385e16021c40be5e04ea93c8411e01d0ea12b4786c9de2
lodestar:    PASS  OK (vitest: 1 passed for electra/sanity/blocks/pyspec_tests/effective_balance_increase_changes_lookahead$)
grandine:    PASS  OK (electra_mainnet_sanity/effective_balance_increase_changes_lookahead)
```

Additionally, grandine's spec-test binary passes both Electra dedicated `effective_balance_updates` epoch-processing fixtures:
- `electra/epoch_processing/effective_balance_updates/pyspec_tests/effective_balance_hysteresis` ✓
- `electra/epoch_processing/effective_balance_updates/pyspec_tests/effective_balance_hysteresis_with_compounding_credentials` ✓

The other five clients run these same fixtures in their internal CI (each ships green); a future iteration should generalise `tools/runners/*.sh` to invoke them through our harness so the per-fixture pass/fail line is captured locally.

Final post-state SHA-256 fingerprint (decompressed SSZ): **`aec719af6530b4e79d385e16021c40be5e04ea93c8411e01d0ea12b4786c9de2`**.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — exact-quantum balance).** Validator with `0x01` credentials, `effective_balance = 32 ETH`, `balance = 32 ETH + 1.25 ETH + 1 gwei` (just over UPWARD_THRESHOLD). Expected: predicate fires on upward, but `min(balance − balance%EBI, 32 ETH)` clamps to 32 ETH, so `effective_balance` does not change. Detects any client that writes back the un-clamped value.
- **T1.2 (priority — compounding upgrade midstream).** Validator transitions `0x01 → 0x02` mid-epoch via consolidation, then receives a deposit pushing balance to 33 ETH. Expected: at the next epoch boundary, `get_max_effective_balance` returns 2048 ETH and EB updates to 33 ETH (not clamped to 32). Detects a stale-cap cache.

#### T2 — Adversarial probes
- **T2.1 (priority — boundary-overflow sandwich).** Validator with `0x02` credentials, `effective_balance = MAX_EFFECTIVE_BALANCE_ELECTRA = 2048 ETH`, `balance = 2048 ETH + 1.25 ETH + 1 gwei`. Predicate fires on upward; clamped result is exactly 2048 ETH. Tests the upper saturation behaviour. (Lodestar's extra `effectiveBalance < effectiveBalanceLimit` guard makes this branch unreachable in lodestar — the truth table differs from pyspec here, but the output state is identical. Worth a fixture to lock the equivalence.)
- **T2.2 (priority — credential prefix typo).** Validator with `withdrawal_credentials[0] = 0x12` (a hypothetical malformed prefix). Each client's `is_compounding` predicate must return false; verify all six classify as 32 ETH-cap. Defensive — not directly reachable from honest validators because the prefix transitions are constrained by `process_consolidation_request` and `switch_to_compounding_validator`, but a future EIP could open this surface.
- **T2.3 (Glamsterdam-target — `0x03` builder prefix in `state.validators`).** Synthetic state with a validator carrying `withdrawal_credentials[0] = 0x03` and `balance > MIN_ACTIVATION_BALANCE`. Per spec, all six clients should clamp to 32 ETH (since `has_compounding_withdrawal_credential` per spec checks only `0x02`). Nimbus's Gloas branch would clamp to 2048 ETH and diverge. Currently academic — Gloas appears to keep builders in a separate `builders` field rather than mixing `0x03` entries into `state.validators` — but a fixture would lock the equivalence regardless and protect against future churn in the deposit-routing surface.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) shows aligned implementations of the Pectra-modified `process_effective_balance_updates`, the `get_max_effective_balance` cap selector, and the `0x02` compounding-credential predicate. The two output-equivalent rephrasings worth noting are unchanged from the prior audit: (a) Lodestar's extra `effectiveBalance < effectiveBalanceLimit` guard in the upward branch, which short-circuits a case the spec handles via the `min` clamp, and (b) Nimbus's Gloas-only branch in `has_compounding_withdrawal_credential` that also accepts the `0x03` builder prefix — neither affects the Pectra-target consensus output.

All six clients agree byte-for-byte on the post-state of `effective_balance_increase_changes_lookahead` (SHA-256 `aec719af6530b4e79d385e16021c40be5e04ea93c8411e01d0ea12b4786c9de2`). Grandine additionally passes both dedicated Electra `effective_balance_updates` epoch-processing fixtures internally.

**Glamsterdam-target recheck:** the Gloas chapter of `consensus-specs v1.7.0-alpha.7` does not modify `process_effective_balance_updates`, `get_max_effective_balance`, or `has_compounding_withdrawal_credential` — only adds a new, unrelated `is_builder_withdrawal_credential` predicate (`vendor/consensus-specs/specs/gloas/beacon-chain.md:487-492`). All six clients still implement the canonical Pectra cap selector at the Glamsterdam target. The Nimbus Gloas extension noted above is the only source-level divergence at the Glamsterdam target; whether it produces a state-root divergence at activation depends on whether `0x03`-credentialled entries ever land in `state.validators`, which the Gloas modifications to deposit handling (`gloas/beacon-chain.md:982` and the new `builders` field gated by `BUILDER_INDEX_FLAG`) appear to prevent. Tracked as a Gloas-specific follow-up under "Adjacent" rather than reopening this item.

No code-change recommendation. Recommendations to the harness: (1) extend `tools/runners/*.sh` to invoke epoch-processing-format fixtures, (2) generate a custom T1.1 / T2.1 boundary-overflow fixture and re-run, (3) once Gloas state-shape stabilises, run T2.3 against all six clients to lock the `0x03` cap-selector behaviour.

## Cross-cuts

### With future Track A (consolidation request, `withdrawal_credentials` transitions)

`get_max_effective_balance` is the consumer of the `0x02` prefix written by `process_consolidation_request` (EIP-7251) and `switch_to_compounding_validator`. WORKLOG candidates #1 (consolidation) and #29 (credential transitions) produce the inputs that this item consumes. A divergence in either of those items will manifest here as a per-validator-cap divergence at the next epoch boundary.

### With item #34 (proposed) — `historical_summaries` accumulator under Pectra state

`historical_summaries.append` runs at the same epoch boundary as `process_effective_balance_updates`. Both write to fields under `BeaconState`; ordering between the two is fixed by pyspec (`process_effective_balance_updates` runs in `process_epoch` before `process_historical_summaries_update`). No client appears to reorder.

## Adjacent untouched Electra-active consensus paths

1. **`process_pending_deposits` queue ordering vs `process_effective_balance_updates`** — both run in the same `process_epoch`, and `process_pending_deposits` writes to `state.balances` which feeds this item's `balance` read on the *next* epoch. WORKLOG candidate #3. Note: Gloas modifies `process_pending_deposits` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:982`) — the modification routes deposits carrying `0x03` credentials into the new `builders` field rather than into `state.validators`, and is the structural reason T2.3 above is "academic" at present. Reaudit when that item lands.
2. **Teku's `effectiveBalanceLimit.min(balance.minus(...).min(maxEffectiveBalance))` redundant-clamp.** The outer `.min(...)` is dead code in the dispatch context but might surface a difference if the dispatcher ever invoked this with a different `effectiveBalanceLimit`. Worth a "redundant min" sweep across all clients.
3. **Nimbus's Gloas-fork compounding predicate.** Nimbus is currently the only client that extends `has_compounding_withdrawal_credential` to also accept `0x03` at the Gloas fork gate (`vendor/nimbus/beacon_chain/spec/beaconstate.nim:59-68`). The source comment references a `v1.6.0-beta.0` spec section that no longer exists in `v1.7.0-alpha.7`; the predicate is per-spec unchanged at Gloas. Open as a separate item once the Gloas validator-vs-builder list semantics stabilise: confirm whether `0x03` ever enters `state.validators` (currently routed elsewhere by the Gloas deposit modifications) and, if so, fixture all six clients.
4. **Lighthouse's `safe_*` arithmetic.** Overflow-checked add/sub/rem return `Result`. The `?` operator propagates an error rather than panicking, but the error type is opaque to the caller. Worth checking: does any client's overflow-checked path fail on a fixture where unchecked path silently wraps? Cross-cut with Track E (SSZ) and Track F (BLS) overflow-handling sweeps.
5. **`is_compounding` zero-length defensive variants.** Lighthouse and grandine return false on zero-length credentials; prysm and lodestar would panic / read out-of-bounds. SSZ schema guarantees 32-byte credentials so this is academic — but if a future SSZ change introduces variable-length credentials (vanishingly unlikely), the divergence is real.
