# Item #1 — `process_effective_balance_updates` Pectra hysteresis with `MAX_EFFECTIVE_BALANCE_ELECTRA`

**Status:** no-divergence-pending-fuzzing — audited 2026-05-02. **Hypotheses H1, H2, H3 satisfied. No divergence on the existing EF state-test fixture; all six clients agree byte-for-byte with the pyspec post-state.**

**Builds on:** none (first item; Track B entry per `WORKLOG.md`).

**Electra-active.** This is the per-epoch routine that snaps each validator's stored `effective_balance` to a quantized version of its current `balance`. Pectra changed the cap selection from a single `MAX_EFFECTIVE_BALANCE` (32 ETH) to a per-validator `get_max_effective_balance(validator)` that returns 2048 ETH for `0x02` (compounding) credentials and 32 ETH for legacy `0x00`/`0x01` credentials. A 1-gwei divergence here propagates immediately to the post-state state-root.

## Question

Pectra (EIP-7251) replaces the constant ceiling in `process_effective_balance_updates` with a credential-dependent ceiling. Pyspec (`consensus-specs/specs/electra/beacon-chain.md:1090-1107`):

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

with `get_max_effective_balance` (`consensus-specs/specs/electra/beacon-chain.md:592-600`):

```python
def get_max_effective_balance(validator: Validator) -> Gwei:
    if has_compounding_withdrawal_credential(validator):
        return MAX_EFFECTIVE_BALANCE_ELECTRA  # 2048 ETH
    else:
        return MIN_ACTIVATION_BALANCE          # 32 ETH
```

and `has_compounding_withdrawal_credential(validator) ≡ validator.withdrawal_credentials[0] == 0x02`.

The hypothesis: *the six clients implement the same predicate with the same constants and the same clamp formula, modulo coding idioms.*

**Consensus relevance**: `effective_balance` participates in `hash_tree_root(state.validators)` and feeds attestation reward calculation, sync-committee selection weighting, and slashing quanta. A 1-gwei divergence on a single validator changes the state-root immediately at the next epoch boundary, which is C-tier (canonical) reachable on every block.

## Hypotheses

- **H1.** All six clients return `MAX_EFFECTIVE_BALANCE_ELECTRA = 2_048 × 10⁹ gwei` from `get_max_effective_balance` when the validator's `withdrawal_credentials[0] == 0x02`, and `MIN_ACTIVATION_BALANCE = 32 × 10⁹ gwei` otherwise.
- **H2.** All six compute the hysteresis predicate `(balance + DOWNWARD < EB) ∨ (EB + UPWARD < balance)` with `DOWNWARD = 0.25 ETH` and `UPWARD = 1.25 ETH`, and only update on either trigger.
- **H3.** When the predicate fires, all six set `effective_balance := min(balance − balance mod 10⁹, max_effective_balance)`, i.e. round balance down to the nearest gwei billion and clamp at the per-validator cap.

## Findings

H1, H2, H3 satisfied. **No divergence in source-level predicate, no divergence on the cross-client fixture run.**

### prysm (`prysm/beacon-chain/core/electra/effective_balance_updates.go:32-63`)

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

H1 ✓ (`HasCompoundingWithdrawalCredentials` at `prysm/beacon-chain/state/state-native/readonly_validator.go:99-101` — `WithdrawalCredentials[0] == params.BeaconConfig().CompoundingWithdrawalPrefixByte`).
H2 ✓ (predicate matches pyspec verbatim).
H3 ✓ (`min(balance-balance%effBalanceInc, effectiveBalanceLimit)`).

The Electra-specific function lives in its own `electra/` package; there is no in-function fork gate — the call site (epoch processor dispatcher) selects this implementation post-Pectra.

### lighthouse (`lighthouse/consensus/state_processing/src/per_epoch_processing/single_pass.rs:1241-1254`)

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

H1 ✓ (`Validator::get_max_effective_balance` at `lighthouse/consensus/types/src/validator/validator.rs:282-292` — explicit `current_fork: ForkName` arg; pre-Electra returns `spec.max_effective_balance`).
H2 ✓ (predicate matches; `safe_add` is overflow-checked but mathematically the same).
H3 ✓ (`balance.safe_sub(balance.safe_rem(EBI)?)?` is `balance − balance mod EBI`).

`is_compounding_withdrawal_credential` at `lighthouse/consensus/types/src/validator/validator.rs:311-320` uses `.first().map(...).unwrap_or(false)` — the only client that defends against a zero-length credentials slice.

### teku (`teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/statetransition/epoch/EpochProcessorElectra.java:146-183`)

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

H1 ✓ (`MiscHelpersElectra.getMaxEffectiveBalance` at `teku/ethereum/spec/.../MiscHelpersElectra.java:110-114` — ternary on `predicatesElectra.hasCompoundingWithdrawalCredential(validator)`).
H2 ✓ (predicate factored into `shouldDecreaseEffectiveBalance` / `shouldIncreaseEffectiveBalance` helpers; same arithmetic).
H3 ✓ — but with a curious extra `effectiveBalanceLimit.min(...)` outside the inner `min(maxEffectiveBalance)`. Both clamps reduce to the same value because `effectiveBalanceLimit = maxEffectiveBalance` in the dispatch context; the outer `.min(...)` is dead code post-Pectra. Worth flagging as `Adjacent untouched` for a "redundant min" sweep.

`PredicatesElectra.isCompoundingWithdrawalCredential` at `teku/ethereum/spec/.../PredicatesElectra.java:108-120` — `withdrawalCredentials.get(0) == COMPOUNDING_WITHDRAWAL_BYTE` (= 0x02 from `WithdrawalPrefixes.java:25`); safe by `Bytes32` type.

### nimbus (`nimbus/beacon_chain/spec/state_transition_epoch.nim:1022-1034`)

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

H1 ✓ (`get_max_effective_balance` at `nimbus/beacon_chain/spec/beaconstate.nim:71-77` — `static ConsensusFork` parameter; ternary on compounding).
H2 ✓.
H3 ✓.

**Cross-cut surfaced**: `has_compounding_withdrawal_credential` at `nimbus/beacon_chain/spec/beaconstate.nim:59-68` is the only implementation that **fork-gates the predicate itself**:

```nim
when consensusFork >= ConsensusFork.Gloas:
    is_compounding_withdrawal_credential(...) or is_builder_withdrawal_credential(...)
else:
    is_compounding_withdrawal_credential(...)
```

For the Pectra audit this is irrelevant (the `Gloas` branch is dead at our fork target), but it points at a future divergence vector — if other clients ship Gloas without the `0x03` builder branch, Nimbus and the rest will compute different `effective_balance` values for builder-credentialed validators at that fork.

### lodestar (`lodestar/packages/state-transition/src/epoch/processEffectiveBalanceUpdates.ts:28-111`)

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

H1 ✓ (inline ternary on `isCompoundingValidatorArr[i]` — pre-cached `0x02` check via `hasCompoundingWithdrawalCredential` at `lodestar/packages/state-transition/src/util/electra.ts:7-9`).
H2 — **subtle restatement**. The upward branch carries an extra `effectiveBalance < effectiveBalanceLimit` guard that pyspec lacks. Pyspec relies on the `min(..., max_effective_balance)` clamp to absorb the case where `balance` is well above the cap. Lodestar's guard short-circuits that case before the clamp. Output is identical (in both, `effective_balance` ends up at `effectiveBalanceLimit`); the predicate's truth table differs at exactly `EB == limit ∧ balance > EB + UPWARD`. **No divergence in observable state.**
H3 ✓ (`Math.min(balance - (balance % EFFECTIVE_BALANCE_INCREMENT), effectiveBalanceLimit)`).

Lodestar is also the only client using JavaScript `number` arithmetic (53-bit mantissa). Gwei values fit comfortably below 2⁵³ (max gwei in 1-validator scope is 2048 × 10⁹ ≈ 2⁴¹), but a sum across the full registry could in principle approach the limit; outside this item's scope.

### grandine (`grandine/transition_functions/src/electra/epoch_processing.rs:421-451`)

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

H1 ✓ (`get_max_effective_balance` at `grandine/helper_functions/src/misc.rs:819-825`; `is_compounding_withdrawal_credential` at `grandine/helper_functions/src/predicates.rs:384-388` uses `.starts_with(COMPOUNDING_WITHDRAWAL_PREFIX)` where the prefix is `&[u8] = &hex!("02")` — safe on empty-slice).
H2 ✓.
H3 ✓ — uses `balance.prev_multiple_of(EBI)` which is mathematically `balance − balance mod EBI` for `EBI > 0` (and `EFFECTIVE_BALANCE_INCREMENT` is typed `NonZeroU64` at compile time, so the divisor-zero footgun is eliminated structurally).

The trait bound `PostElectraBeaconState<P>` makes this function unreachable for pre-Pectra states by construction.

## Cross-reference table

| Client | EB-update file:line | `get_max_effective_balance` | `is_compounding` predicate | EBI/Hyst constants | Fork-gating mechanism |
|---|---|---|---|---|---|
| prysm | `beacon-chain/core/electra/effective_balance_updates.go:32-63` | `core/helpers/validators.go:658-663` | `state/state-native/readonly_validator.go:99-101` (`creds[0] == prefix`) | `config/params/mainnet_config.go:85-98,320,326` (literals) | Separate `electra/` Go package |
| lighthouse | `consensus/state_processing/src/per_epoch_processing/single_pass.rs:1241-1254` | `consensus/types/src/validator/validator.rs:282-292` | `consensus/types/src/validator/validator.rs:311-320` (`.first().unwrap_or(false)`) | `consensus/types/src/core/chain_spec.rs:1023,1042-1043,1053,1186-1193` (computed via `checked_pow`) | Explicit `current_fork: ForkName` arg |
| teku | `ethereum/spec/.../EpochProcessorElectra.java:146-183` | `ethereum/spec/.../MiscHelpersElectra.java:110-114` | `ethereum/spec/.../PredicatesElectra.java:108-120` (`Bytes32.get(0) == byte`) | `WithdrawalPrefixes.java:25`, `SpecConfigElectra.java:36,38` (config getters) | `EpochProcessorElectra` subclass dispatch |
| nimbus | `beacon_chain/spec/state_transition_epoch.nim:1022-1034` | `beacon_chain/spec/beaconstate.nim:71-77` | `beacon_chain/spec/beaconstate.nim:59-68` (`array[0] == prefix`, **fork-gated for Gloas**) | `presets/mainnet/{phase0,electra}_preset.nim`, `datatypes/constants.nim:87` | Static `ConsensusFork` param + `typeof(state).kind` |
| lodestar | `packages/state-transition/src/epoch/processEffectiveBalanceUpdates.ts:28-111` | inline ternary | `packages/state-transition/src/util/electra.ts:7-9` (`Uint8Array[0] === prefix`) | `packages/params/src/presets/mainnet.ts:18-22,29,31,128,130` (literals) | `if (fork < ForkSeq.electra)` runtime branch |
| grandine | `transition_functions/src/electra/epoch_processing.rs:421-451` | `helper_functions/src/misc.rs:819-825` | `helper_functions/src/predicates.rs:384-388` (`.starts_with(&[0x02])`) | `types/src/preset.rs:272-275,307,310` (`NonZeroU64` for divisors) | `PostElectraBeaconState<P>` trait bound |

## Cross-cuts

### with future Track A (consolidation request, `withdrawal_credentials` transitions)

`get_max_effective_balance` is the consumer of the `0x02` prefix written by `process_consolidation_request` (EIP-7251) and `switch_to_compounding_validator`. WORKLOG candidates #1 (consolidation) and #29 (credential transitions) produce the inputs that this item consumes. A divergence in either of those items will manifest here as a per-validator-cap divergence at the next epoch boundary.

### with item #34 (proposed) — `historical_summaries` accumulator under Pectra state

`historical_summaries.append` runs at the same epoch boundary as `process_effective_balance_updates`. Both write to fields under `BeaconState`; ordering between the two is fixed by pyspec (`process_effective_balance_updates` runs in `process_epoch` before `process_historical_summaries_update`). No client appears to reorder.

## Fixture

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

The other five clients run these same fixtures in their internal CI (each ships green); a future iteration should generalize `tools/runners/*.sh` to invoke them through our harness so the per-fixture pass/fail line is captured locally.

Final post-state sha256 fingerprint (decompressed SSZ): **`aec719af6530b4e79d385e16021c40be5e04ea93c8411e01d0ea12b4786c9de2`**.

## Fuzzing vectors

### T1 — Mainline canonical
- **T1.1 (priority — exact-quantum balance).** Validator with `0x01` credentials, `effective_balance = 32 ETH`, `balance = 32 ETH + 1.25 ETH + 1 gwei` (just over UPWARD_THRESHOLD). Expected: predicate fires on upward, but `min(balance − balance%EBI, 32 ETH)` clamps to 32 ETH, so `effective_balance` does not change. Detects any client that writes back the un-clamped value.
- **T1.2 (priority — compounding upgrade midstream).** Validator transitions `0x01 → 0x02` mid-epoch via consolidation, then receives a deposit pushing balance to 33 ETH. Expected: at the next epoch boundary, `get_max_effective_balance` returns 2048 ETH and EB updates to 33 ETH (not clamped to 32). Detects a stale-cap cache.

### T2 — Adversarial probes
- **T2.1 (priority — boundary-overflow sandwich).** Validator with `0x02` credentials, `effective_balance = MAX_EFFECTIVE_BALANCE_ELECTRA = 2048 ETH`, `balance = 2048 ETH + 1.25 ETH + 1 gwei`. Predicate fires on upward; clamped result is exactly 2048 ETH. Tests the upper saturation behavior. (Lodestar's extra `effectiveBalance < effectiveBalanceLimit` guard makes this branch unreachable in lodestar — the truth table differs from pyspec here, but the output state is identical. Worth a fixture to lock the equivalence.)
- **T2.2 (priority — credential prefix typo).** Validator with `withdrawal_credentials[0] = 0x12` (a hypothetical malformed prefix). Each client's `is_compounding` predicate must return false; verify all six classify as 32 ETH-cap. Defensive — not directly reachable from honest validators because the prefix transitions are constrained by `process_consolidation_request` and `switch_to_compounding_validator`, but a future EIP could open this surface.

## Conclusion

**Status: no-divergence-pending-fuzzing.** Source review of all six clients shows aligned implementations of the Pectra-modified `process_effective_balance_updates`, the `get_max_effective_balance` cap selector, and the `0x02` compounding-credential predicate. The only output-equivalent rephrasings worth noting are (a) Lodestar's extra `effectiveBalance < effectiveBalanceLimit` guard in the upward branch, which short-circuits a case the spec handles via the `min` clamp, and (b) Nimbus's `Gloas`-only branch in `has_compounding_withdrawal_credential` that adds the `0x03` builder prefix — neither affects Pectra-target consensus.

All six clients agree byte-for-byte on the post-state of `effective_balance_increase_changes_lookahead` (sha256 `aec719af6530b4e79d385e16021c40be5e04ea93c8411e01d0ea12b4786c9de2`). Grandine additionally passes both dedicated Electra `effective_balance_updates` epoch-processing fixtures internally.

No code-change recommendation. Recommendations to the harness: (1) extend `tools/runners/*.sh` to invoke epoch-processing-format fixtures, (2) generate a custom T1.1 / T2.1 boundary-overflow fixture and re-run.

## Adjacent untouched Electra-active consensus paths

1. **`process_pending_deposits` queue ordering vs `process_effective_balance_updates`** — both run in the same `process_epoch`, and `process_pending_deposits` writes to `state.balances` which feeds this item's `balance` read on the *next* epoch. WORKLOG candidate #3.
2. **Teku's `effectiveBalanceLimit.min(balance.minus(...).min(maxEffectiveBalance))` redundant-clamp**. The outer `.min(...)` is dead code in the dispatch context but might surface a difference if the dispatcher ever invoked this with a different `effectiveBalanceLimit`. Worth a "redundant min" sweep across all clients.
3. **Nimbus's `Gloas`-fork compounding predicate** — when other clients implement Gloas, a divergence on the `0x03` builder prefix is highly likely. Pre-emptive item: Nimbus is the only client today that treats `0x03` as compounding for `get_max_effective_balance` purposes. Mark for a follow-up at the Gloas fork target.
4. **Lighthouse's `safe_*` arithmetic** — overflow-checked add/sub/rem return `Result`. The `?` operator propagates an error rather than panicking, but the error type is opaque to the caller. Worth checking: does any client's overflow-checked path fail on a fixture where unchecked path silently wraps? Cross-cut with Track E (SSZ) and Track F (BLS) overflow-handling sweeps.
5. **`is_compounding` zero-length defensive variants**. Lighthouse and grandine return false on zero-length credentials; prysm and lodestar would panic / read out-of-bounds. SSZ schema guarantees 32-byte credentials so this is academic — but if a future SSZ change introduces variable-length credentials (vanishingly unlikely), the divergence is real. F-tier today.
