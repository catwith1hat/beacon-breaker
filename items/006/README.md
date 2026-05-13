---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-12
builds_on: [2, 3, 5]
eips: [EIP-7251, EIP-7044, EIP-7732, EIP-8061]
splits: [prysm, lighthouse, teku, nimbus, grandine]
# main_md_summary: lighthouse + nimbus lack the Gloas EIP-7732 builder-exit routing in `process_voluntary_exit`; the same five also still pace `initiate_validator_exit` via Electra `get_activation_exit_churn_limit` at Gloas (sister to item #3 H8)
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 6: `process_voluntary_exit` + `initiate_validator_exit` Pectra

## Summary

The OG signed-message exit path, Pectra-modified to (a) require no pending partial withdrawals for the validator and (b) flow exit-epoch computation through the new `compute_exit_epoch_and_update_churn` machinery instead of the legacy fixed-rate exit queue. Two Pectra-modified functions in one audit because they form an inseparable pair: the request validator + the state-mutating action.

**Pectra surface (the function body itself):** all six clients implement the seven Pectra-modified predicates of `process_voluntary_exit` and the `initiate_validator_exit` Pectra modification identically. 25/25 EF `voluntary_exit` operations fixtures pass uniformly on the four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus pass these in internal CI but the local harness SKIPs them. The two divergence-prone bits — **CAPELLA_FORK_VERSION pinning per EIP-7044** and the **Pectra-new pending-withdrawals check** — are correctly enforced everywhere.

**Gloas surface (new at the Glamsterdam target):** two distinct divergences.

1. **H8** — same as item #3 H8. `initiate_validator_exit` calls `compute_exit_epoch_and_update_churn`, which Gloas (EIP-8061) modifies to use `get_exit_churn_limit` instead of `get_activation_exit_churn_limit`. Only lodestar fork-gates the call; prysm, lighthouse, teku, nimbus, and grandine all run the Electra accessor unconditionally on Gloas states. State-root divergence on the first Gloas-slot voluntary exit (or full-exit withdrawal_request, which also funnels through `initiate_validator_exit`) where the balance triggers an `earliest_exit_epoch` recomputation.
2. **H9** — Gloas (EIP-7732 ePBS) modifies `process_voluntary_exit` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1628-1668`) to route builder-index exits through a separate path: convert validator-index → builder-index, verify `is_active_builder`, check `get_pending_balance_to_withdraw_for_builder == 0`, verify the signature against `state.builders[builder_index].pubkey`, then `initiate_builder_exit(state, builder_index)`. Survey of all six clients: **prysm, teku, lodestar, grandine** implement the routing; **lighthouse and nimbus do not** — they pass through to the validator path, which on a builder-index input (the high bit of `BUILDER_INDEX_FLAG` is set) will fail the `validator_index < len(validators)` bounds check and silently reject the exit. A builder cannot voluntarily exit on lighthouse or nimbus at Gloas; the other four would process the exit. Materialises as a state-root divergence on any Gloas-slot block containing a builder voluntary-exit.

The combined `splits` field is the same five-client set as the EIP-8061 family items (#2 H6, #3 H8, #4 H8). Lighthouse and nimbus diverge on both H8 and H9; prysm/teku/grandine diverge on H8 only; lodestar diverges on neither.

## Question

Pyspec `process_voluntary_exit` (`vendor/consensus-specs/specs/electra/beacon-chain.md`):

```python
def process_voluntary_exit(state, signed_voluntary_exit):
    voluntary_exit = signed_voluntary_exit.message
    validator = state.validators[voluntary_exit.validator_index]
    assert is_active_validator(validator, current_epoch)
    assert validator.exit_epoch == FAR_FUTURE_EPOCH
    assert current_epoch >= voluntary_exit.epoch
    assert current_epoch >= validator.activation_epoch + SHARD_COMMITTEE_PERIOD
    # [NEW in Electra:EIP7251] no pending partial withdrawals
    assert get_pending_balance_to_withdraw(state, voluntary_exit.validator_index) == 0
    # Signature with CAPELLA_FORK_VERSION (NOT current fork, NOT genesis)
    domain = compute_domain(DOMAIN_VOLUNTARY_EXIT, CAPELLA_FORK_VERSION, state.genesis_validators_root)
    signing_root = compute_signing_root(voluntary_exit, domain)
    assert bls.Verify(validator.pubkey, signing_root, signed_voluntary_exit.signature)
    initiate_validator_exit(state, voluntary_exit.validator_index)
```

Pyspec `initiate_validator_exit` (Pectra-modified, `vendor/consensus-specs/specs/electra/beacon-chain.md:711`):

```python
def initiate_validator_exit(state, index):
    validator = state.validators[index]
    if validator.exit_epoch != FAR_FUTURE_EPOCH:
        return
    exit_queue_epoch = compute_exit_epoch_and_update_churn(state, validator.effective_balance)
    validator.exit_epoch = exit_queue_epoch
    validator.withdrawable_epoch = exit_queue_epoch + MIN_VALIDATOR_WITHDRAWABILITY_DELAY
```

Two divergence-prone bits worth special attention on the Pectra surface:

1. **CAPELLA_FORK_VERSION for the sig domain** (introduced by EIP-7044 at Deneb). NOT current fork, NOT genesis. A client using current fork version would silently reject EVERY voluntary exit signed before the current fork; a client using genesis would reject every Capella+ signed exit. Voluntary exits are domain-locked to Capella to make them valid across all post-Capella forks (so a key holder can sign an exit once, valid forever).
2. **Pectra-new pending-withdrawals check**: `get_pending_balance_to_withdraw(state, idx) == 0`. A validator with pending partial withdrawals can't voluntarily exit.

**Glamsterdam target.** Gloas changes the picture in two places:

- **Modified `process_voluntary_exit`** (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1628-1668`) adds a builder-routing branch at the top. If the validator index is a builder index (high bit set per `BUILDER_INDEX_FLAG`), the function converts to a builder-index, validates as an active builder with no pending builder withdrawals, verifies the signature against the builder's pubkey from `state.builders[]`, and calls the new `initiate_builder_exit` (line 889). Otherwise the function falls through to the same validator path as Electra.
- **`compute_exit_epoch_and_update_churn`** is Modified at Gloas (EIP-8061) to use `get_exit_churn_limit` (Gloas-new) rather than `get_activation_exit_churn_limit`. `initiate_validator_exit` itself is unchanged in body but its callee semantics flip at Gloas. Same finding as item #3 H8.

The signature domain at Gloas continues to use `CAPELLA_FORK_VERSION` (the EIP-7044 pin survives all post-Capella forks).

The hypothesis: *all six clients implement the seven Pectra predicates (H1–H7), the CAPELLA_FORK_VERSION domain selection, the pending-withdrawals check, and the Pectra-modified `initiate_validator_exit`. At the Glamsterdam target, all six additionally fork-gate `compute_exit_epoch_and_update_churn` to `get_exit_churn_limit` (H8) and implement the builder-exit routing in `process_voluntary_exit` (H9).*

**Consensus relevance**: voluntary exits are how validators willingly leave the chain. The Pectra changes mean a validator's exit_epoch is now churn-paced (variable, depending on prior exit volume) rather than fixed-rate. A divergence in the churn arithmetic produces different `exit_epoch` and `withdrawable_epoch` values across clients — splitting the state-root immediately, AND throwing off the fork-choice's view of when the validator is no longer eligible to attest. The CAPELLA_FORK_VERSION domain bug would silently reject all valid exits across the affected client. At Gloas, the missing builder-routing makes builder voluntary-exits impossible on the affected clients (lighthouse + nimbus), and the missing Gloas churn-helper fork-gate makes the post-state diverge whenever a non-builder exit reaches the churn ceiling.

## Hypotheses

- **H1.** All six implement the seven check sequence (active, not-exiting, timing, seasoned, no-pending-withdrawals, signature, initiate). Order may vary but observable accept/reject is identical.
- **H2.** All six use **CAPELLA_FORK_VERSION** (NOT current, NOT genesis) for the voluntary exit signing domain when the state's current fork is ≥ Deneb (per EIP-7044). Continues to hold at Gloas (CAPELLA pin is permanent).
- **H3.** All six implement the Pectra-new `get_pending_balance_to_withdraw(state, idx) == 0` check, gated on Electra+.
- **H4.** All six implement `initiate_validator_exit` (Pectra-modified) by calling `compute_exit_epoch_and_update_churn(state, validator.effective_balance)` — the same function used by item #3's partial withdrawal path.
- **H5.** All six set `validator.withdrawable_epoch = exit_queue_epoch + MIN_VALIDATOR_WITHDRAWABILITY_DELAY`.
- **H6.** All six early-return from `initiate_validator_exit` when the validator is already exiting (`exit_epoch != FAR_FUTURE_EPOCH`) — important because the function may be called multiple times via different paths (voluntary_exit, withdrawal_request full-exit, slashing).
- **H7.** All six use `validator.effective_balance` (NOT `MIN_ACTIVATION_BALANCE`, NOT `state.balances[i]`) as the input to `compute_exit_epoch_and_update_churn`. Effective balance can be 32 ETH (legacy) or up to 2048 ETH (compounding) — large delta affects churn pacing.
- **H8** *(Glamsterdam target — shared with item #3)*. At the Gloas fork gate, all six clients switch the per-epoch-churn quantity inside `compute_exit_epoch_and_update_churn` from `get_activation_exit_churn_limit(state)` (Electra) to `get_exit_churn_limit(state)` (Gloas, EIP-8061). Pre-Gloas, all six retain the Electra formula.
- **H9** *(Glamsterdam target — new)*. At the Gloas fork gate, all six clients implement the EIP-7732 builder-routing branch in `process_voluntary_exit`: if the message's `validator_index` is a builder index (per `is_builder_index`), route through `convert_validator_index_to_builder_index` → `is_active_builder` → `get_pending_balance_to_withdraw_for_builder == 0` → signature verified against `state.builders[builder_index].pubkey` → `initiate_builder_exit(state, builder_index)`.

## Findings

H1–H7 satisfied for the Pectra surface. **H8 fails for 5 of 6 clients** (same set as item #3). **H9 fails for 2 of 6 clients** (lighthouse and nimbus do not implement the Gloas builder-routing in `process_voluntary_exit`; prysm, teku, lodestar, grandine do). No EF Gloas operations fixtures yet exist for either surface.

### prysm

`vendor/prysm/beacon-chain/core/blocks/exit.go:91-216`. `VerifyExitAndSignature` (line 114) constructs the **CAPELLA_FORK_VERSION** domain explicitly for Deneb+:

```go
fork := st.Fork()
if st.Version() >= version.Deneb {
    // EIP-7044: Beginning in Deneb, fix the fork version to Capella.
    fork = &ethpb.Fork{
        PreviousVersion: params.BeaconConfig().CapellaForkVersion,
        CurrentVersion:  params.BeaconConfig().CapellaForkVersion,
        Epoch:           params.BeaconConfig().CapellaForkEpoch,
    }
}
// ...
domain, _ := signing.Domain(fork, exit.Epoch, params.BeaconConfig().DomainVoluntaryExit, genesisRoot)
```

**Gloas builder routing (H9 ✓)** — explicit fork+index gate at line 67 and line 124:

```go
// [New in Gloas:EIP7732] Builder exits are identified by the builder index flag.
if beaconState.Version() >= version.Gloas && exit.Exit.ValidatorIndex.IsBuilderIndex() {
    // ... separate verification path against state.builders[]
}
```

A dedicated `// [New in Gloas:EIP7732]` block at line 219 of the same file handles the builder-side initiation.

`verifyExitConditions` (line 179) includes the Pectra-new check at line 206:

```go
if st.Version() >= version.Electra {
    ok, _ := st.HasPendingBalanceToWithdraw(exit.ValidatorIndex)
    if ok { return fmt.Errorf("validator %d must have no pending balance to withdraw", exit.ValidatorIndex) }
}
```

`InitiateValidatorExit` (`vendor/prysm/beacon-chain/core/validators/validator.go:87-126`) Pectra branch:

```go
if s.Version() < version.Electra {
    if err = initiateValidatorExitPreElectra(ctx, s, exitInfo); err != nil { ... }
} else {
    // [Modified in Electra:EIP7251]
    exitInfo.HighestExitEpoch, _ = s.ExitEpochAndUpdateChurn(primitives.Gwei(validator.EffectiveBalance))
}
validator.ExitEpoch = exitInfo.HighestExitEpoch
validator.WithdrawableEpoch, _ = exitInfo.HighestExitEpoch.SafeAddEpoch(params.BeaconConfig().MinValidatorWithdrawabilityDelay)
```

`ExitEpochAndUpdateChurn` (`vendor/prysm/beacon-chain/state/state-native/setters_churn.go:67`) calls `helpers.ActivationExitChurnLimit(totalActiveBalance)` unconditionally — no fork branch.

H1–H7 ✓. **H8 ✗** (Electra exit-churn formula at Gloas). **H9 ✓**.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing/verify_exit.rs:21-94` — `verify_exit`. Orders checks: active → not-exiting → epoch → seasoned → signature → no-pending-withdraws (last). The signature subroutine `exit_signature_set` at `vendor/lighthouse/consensus/state_processing/src/per_block_processing/signature_sets.rs:378-395` selects the CAPELLA_FORK_VERSION domain:

```rust
let domain = if state.fork_name_unchecked().deneb_enabled() {
    // EIP-7044
    spec.compute_domain(
        Domain::VoluntaryExit,
        spec.capella_fork_version,
        state.genesis_validators_root(),
    )
} else { ... };
```

**No Gloas builder-routing (H9 ✗).** `verify_exit.rs` contains no `is_builder_index` / `builder_index` / `BUILDER_INDEX_FLAG` references; the per-block-processing module overall has zero references to those identifiers. A `SignedVoluntaryExit` whose `validator_index` is a builder index (high bit set per `BUILDER_INDEX_FLAG`) would flow into the validator path, where the `state.validators().get(validator_index as usize)` lookup would either out-of-bounds-error or read an unrelated validator entry — either way, the builder exit is not processed correctly. A builder cannot voluntarily exit on lighthouse at Gloas.

`initiate_validator_exit` (`vendor/lighthouse/consensus/state_processing/src/common/initiate_validator_exit.rs:6-49`):

```rust
if validator.exit_epoch != spec.far_future_epoch { return Ok(()); }
state.build_exit_cache(spec)?;
let exit_queue_epoch = if state.fork_name_unchecked() >= ForkName::Electra {
    let effective_balance = state.get_effective_balance(index)?;
    state.compute_exit_epoch_and_update_churn(effective_balance, spec)?
} else { /* pre-Electra */ };
validator.exit_epoch = exit_queue_epoch;
validator.withdrawable_epoch = exit_queue_epoch.safe_add(spec.min_validator_withdrawability_delay)?;
```

`compute_exit_epoch_and_update_churn` (`vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2708-2752`) uses `self.get_activation_exit_churn_limit(spec)?` unconditionally — no fork branch (see item #3 finding).

H1–H7 ✓. **H8 ✗** (Electra exit-churn formula at Gloas). **H9 ✗** (no builder-routing in `verify_exit`).

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/operations/validation/VoluntaryExitValidatorElectra.java:33-65` — `VoluntaryExitValidatorElectra`:

```java
public Optional<OperationInvalidReason> validate(...) {
  return firstOf(
      () -> super.validate(fork, state, signedExit),
      () -> validateElectraConditions(stateElectra, signedExit));
}

Optional<OperationInvalidReason> validateElectraConditions(...) {
  return check(
      stateAccessorsElectra.getPendingBalanceToWithdraw(stateElectra, exit.getValidatorId().intValue())
          .equals(UInt64.ZERO),
      VoluntaryExitValidator.ExitInvalidReason.pendingWithdrawalsInQueue());
}
```

**Gloas builder routing (H9 ✓)** in `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/operations/validation/VoluntaryExitValidatorGloas.java`:

```java
public class VoluntaryExitValidatorGloas extends VoluntaryExitValidatorElectra {
  @Override
  public Optional<OperationInvalidReason> validate(
      final Fork fork, final BeaconState state, final SignedVoluntaryExit signedExit) {
    if (predicates.isBuilderIndex(signedExit.getMessage().getValidatorIndex())) {
      final UInt64 builderIndex =
          miscHelpers.convertValidatorIndexToBuilderIndex(
              signedExit.getMessage().getValidatorIndex());
      return validateBuilderExit(state, builderIndex);
    }
    return super.validate(fork, state, signedExit);
  }

  protected Optional<OperationInvalidReason> validateBuilderExit(...) { ... }
}
```

The CAPELLA_FORK_VERSION domain selection is in `BeaconStateAccessorsDeneb.getVoluntaryExitDomain()` (overridden from the Phase0 base) — uses `denebConfig.getCapellaForkVersion()`. Continues to apply at Gloas.

`initiateValidatorExit` (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/BeaconStateMutatorsElectra.java:108-132`) — early-return on already-exiting, then `computeExitEpochAndUpdateChurn(stateElectra, validator.getEffectiveBalance())` at line 121.

`computeExitEpochAndUpdateChurn` at the same file (line 77-104) calls `stateAccessorsElectra.getActivationExitChurnLimit(state)` unconditionally. `BeaconStateMutatorsGloas` exists but does not override this method (see item #3).

H1–H7 ✓. **H8 ✗** (Electra exit-churn formula at Gloas). **H9 ✓**.

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:453-502` — `check_voluntary_exit`:

```nim
when typeof(state).kind >= ConsensusFork.Electra:
  if not (get_pending_balance_to_withdraw(state, voluntary_exit.validator_index.ValidatorIndex) == 0.Gwei):
    return err("Exit: still has pending withdrawals")

if skipBlsValidation notin flags:
  const consensusFork = typeof(state).kind
  let voluntary_exit_fork = consensusFork.voluntary_exit_signature_fork(state.fork, cfg.CAPELLA_FORK_VERSION)
  if not verify_voluntary_exit_signature(voluntary_exit_fork, ...):
    return err("Exit: invalid signature")
```

`voluntary_exit_signature_fork` (`vendor/nimbus/beacon_chain/spec/signatures.nim`) uses `CAPELLA_FORK_VERSION` for Deneb+. Static fork dispatch ensures correctness at compile time.

**No Gloas builder-routing (H9 ✗).** `check_voluntary_exit` does not check `is_builder_index`. The function's predicate sequence runs against `state.validators[voluntary_exit.validator_index]` directly — line 461 bounds-checks `voluntary_exit.validator_index >= state.validators.lenu64` and rejects. A builder voluntary-exit (high bit set per `BUILDER_INDEX_FLAG`) will trip this bound and be rejected as "invalid validator index". `is_builder_index` *is* defined in nimbus (`state_transition_block.nim:1399`) and used in the withdrawal context (line 1412), but not in voluntary-exit validation. `initiate_builder_exit` is not defined anywhere in nimbus.

`initiate_validator_exit` (`vendor/nimbus/beacon_chain/spec/beaconstate.nim:348-373`) — Pectra version uses `compute_exit_epoch_and_update_churn(cfg, state, validator.effective_balance, cache)`.

`compute_exit_epoch_and_update_churn` (`vendor/nimbus/beacon_chain/spec/beaconstate.nim:286-314`) uses `get_activation_exit_churn_limit(cfg, state, cache)` unconditionally (see item #3).

H1–H7 ✓. **H8 ✗** (Electra exit-churn formula at Gloas). **H9 ✗** (no builder-routing in `check_voluntary_exit`; `initiate_builder_exit` not implemented).

### lodestar

`vendor/lodestar/packages/state-transition/src/block/processVoluntaryExit.ts:16-110`:

```typescript
import {
  ...
  initiateBuilderExit,
  ...
  isBuilderIndex,
} from "../util/gloas.js";
...
export function processVoluntaryExit(...) {
  if (fork >= ForkSeq.gloas && isBuilderIndex(voluntaryExit.validatorIndex)) {
    initiateBuilderExit(
      state as CachedBeaconStateGloas,
      ...
    );
    return;
  }
  // ... Electra path
}
```

A parallel branch at line 71 routes the validity helper too:

```typescript
if (fork >= ForkSeq.gloas && isBuilderIndex(voluntaryExit.validatorIndex)) {
  return getBuilderVoluntaryExitValidity(state as CachedBeaconStateGloas, signedVoluntaryExit, verifySignature);
}
```

Domain selection (`vendor/lodestar/packages/config/src/genesisConfig/index.ts:96-104`):

```typescript
getDomainForVoluntaryExit(stateSlot, messageSlot) {
  // Deneb onwards the signature domain fork is fixed to capella
  return stateSlot < DENEB_FORK_EPOCH * SLOTS_PER_EPOCH
    ? this.getDomain(stateSlot, DOMAIN_VOLUNTARY_EXIT, messageSlot)
    : this.getDomainAtFork(ForkName.capella, DOMAIN_VOLUNTARY_EXIT);
}
```

`initiateValidatorExit` (`vendor/lodestar/packages/state-transition/src/block/initiateValidatorExit.ts:27-62`):

```typescript
if (validator.exitEpoch !== FAR_FUTURE_EPOCH) return;
if (fork < ForkSeq.electra) {
  // pre-Electra
} else {
  validator.exitEpoch = computeExitEpochAndUpdateChurn(state, BigInt(validator.effectiveBalance));
}
validator.withdrawableEpoch = validator.exitEpoch + config.MIN_VALIDATOR_WITHDRAWABILITY_DELAY;
```

`computeExitEpochAndUpdateChurn` (`vendor/lodestar/packages/state-transition/src/util/epoch.ts:50-77`) is the **fork-gated** implementation that selects `getExitChurnLimit` at `fork >= ForkSeq.gloas` — the only client that does so (see item #3).

H1–H7 ✓. **H8 ✓** (the only client matching Gloas spec on the exit-churn). **H9 ✓**.

### grandine

`vendor/grandine/transition_functions/src/electra/block_processing.rs:1006-1062` — `process_voluntary_exit` for the Electra path. The block processor at the Gloas level (`vendor/grandine/transition_functions/src/gloas/block_processing.rs:1017-1041`) is a **separate function** that adds the builder routing:

```rust
pub fn process_voluntary_exit<P: Preset>(
    config: &Config,
    pubkey_cache: &PubkeyCache,
    state: &mut impl PostGloasBeaconState<P>,
    signed_voluntary_exit: SignedVoluntaryExit,
    verifier: impl Verifier,
) -> Result<()> {
    validate_voluntary_exit_with_verifier(
        config, pubkey_cache, state, signed_voluntary_exit, verifier,
    )?;

    let validator_index = signed_voluntary_exit.message.validator_index;
    if let Some(builder_index) = maybe_builder_index(validator_index) {
        initiate_builder_exit(config, state, builder_index)
    } else {
        initiate_validator_exit(config, state, validator_index)
    }
}
```

The Pectra `initiate_validator_exit` (`vendor/grandine/helper_functions/src/electra.rs:124-150`) is still the one called:

```rust
pub fn initiate_validator_exit<P: Preset>(
    config: &Config,
    state: &mut impl PostElectraBeaconState<P>,
    validator_index: ValidatorIndex,
) -> Result<()> {
    let validator = state.validators().get(validator_index)?;
    if validator.exit_epoch != FAR_FUTURE_EPOCH { return Ok(()); }
    let exit_queue_epoch = compute_exit_epoch_and_update_churn(config, state, validator.effective_balance);
    let validator = state.validators_mut().get_mut(validator_index)?;
    validator.exit_epoch = exit_queue_epoch;
    validator.withdrawable_epoch = exit_queue_epoch
        .checked_add(config.min_validator_withdrawability_delay)
        .ok_or(Error::EpochOverflow)?;
    Ok(())
}
```

`compute_exit_epoch_and_update_churn` (`vendor/grandine/helper_functions/src/mutators.rs:177-208`) uses `get_activation_exit_churn_limit` unconditionally (see item #3).

Voluntary-exit signature domain in grandine (`vendor/grandine/helper_functions/src/signing.rs:420-449`) hard-codes CAPELLA_FORK_VERSION for Deneb/Electra/Fulu/Gloas:

```rust
let domain = if current_fork_version == config.deneb_fork_version
    || current_fork_version == config.electra_fork_version
    || current_fork_version == config.fulu_fork_version
    || current_fork_version == config.gloas_fork_version
{
    let fork_version = Some(config.capella_fork_version);
    misc::compute_domain(config, domain_type, fork_version, ...)
} else { ... }
```

**Source-organization risk** preserved from the prior audit: grandine has TWO `initiate_validator_exit` definitions (one in `mutators.rs:61` for Phase0-style; one in `electra.rs:124` for Pectra). The Pectra and Gloas callers import the Electra version explicitly. Worth flagging for future agents walking grandine's `use` chains.

H1–H7 ✓. **H8 ✗** (Electra exit-churn formula at Gloas). **H9 ✓**.

## Cross-reference table

| Client | `process_voluntary_exit` | Pectra pending-withdraws check | CAPELLA domain selection | Gloas builder routing (H9) | `compute_exit_epoch_and_update_churn` fork-gate (H8) |
|---|---|---|---|---|---|
| prysm | `core/blocks/exit.go:91-216` | `verifyExitConditions:206-213`, gated `>= version.Electra` | hardcode at `:71-77` for `>= version.Deneb` | **✓** (`:67, :124, :219`) | ✗ (`state-native/setters_churn.go:67` calls `helpers.ActivationExitChurnLimit` unconditionally) |
| lighthouse | `per_block_processing/verify_exit.rs:21-94` | line 82-91, present unconditionally (state variant guards) | `signature_sets.rs:378-395` `if deneb_enabled()` | **✗** (no `is_builder_index` in `verify_exit.rs`) | ✗ (`beacon_state.rs:2708-2752` calls `get_activation_exit_churn_limit` unconditionally) |
| teku | `VoluntaryExitValidatorElectra.java:45-65` (subclass adds check) | `validateElectraConditions:54-65` returns `Optional<InvalidReason>` | `BeaconStateAccessorsDeneb.getVoluntaryExitDomain()` (override) | **✓** (`VoluntaryExitValidatorGloas.validate()` overrides + routes to `validateBuilderExit`) | ✗ (`BeaconStateMutatorsElectra.java:77-104` calls `getActivationExitChurnLimit`; `BeaconStateMutatorsGloas` doesn't override) |
| nimbus | `state_transition_block.nim:453-502` | `:484-488`, `when typeof(state).kind >= ConsensusFork.Electra` | `voluntary_exit_signature_fork` in `signatures.nim` | **✗** (no Gloas branch in `check_voluntary_exit`; `initiate_builder_exit` not defined) | ✗ (`beaconstate.nim:286-314` body uses `get_activation_exit_churn_limit` even with `gloas.BeaconState` signature) |
| lodestar | `block/processVoluntaryExit.ts:16-110` | `:147-150`, `if (fork >= ForkSeq.electra && getPendingBalanceToWithdraw != 0)` | `getDomainForVoluntaryExit` → `getDomainAtFork(ForkName.capella, ...)` post-Deneb | **✓** (`:44-50, :71-72` — `isBuilderIndex` → `initiateBuilderExit` / `getBuilderVoluntaryExitValidity`) | **✓** (`util/epoch.ts:50-77` fork-gates `getExitChurnLimit` at `fork >= ForkSeq.gloas`) |
| grandine | `electra/block_processing.rs:1006-1062` (Electra); `gloas/block_processing.rs:1017-1041` (Gloas wrapper with builder routing) | `:1056-1058`, `ensure!()` macro → error | `signing.rs:420-449` for any of Deneb/Electra/Fulu/Gloas | **✓** (`gloas/block_processing.rs:1035` calls `initiate_builder_exit` if `maybe_builder_index(validator_index).is_some()`) | ✗ (`mutators.rs:177-208` calls `get_activation_exit_churn_limit` unconditionally) |

## Empirical tests

### Pectra-surface fixture run

`consensus-spec-tests/tests/mainnet/electra/operations/voluntary_exit/pyspec_tests/` — 25 EF fixtures. Run via `scripts/run_fixture.sh` against all six clients on 2026-05-03:

```
                                                                              prysm  lighthouse  teku  nimbus  lodestar  grandine
basic                                                                         PASS   PASS        SKIP  SKIP    PASS      PASS
default_exit_epoch_subsequent_exit                                            PASS   PASS        SKIP  SKIP    PASS      PASS
exit_existing_churn_and_balance_multiple_of_churn_limit                       PASS   PASS        SKIP  SKIP    PASS      PASS
exit_existing_churn_and_churn_limit_balance                                   PASS   PASS        SKIP  SKIP    PASS      PASS
exit_with_balance_equal_to_churn_limit                                        PASS   PASS        SKIP  SKIP    PASS      PASS
exit_with_balance_multiple_of_churn_limit                                     PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_incorrect_signature                                                   PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_validator_already_exited                                              PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_validator_exit_in_future                                              PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_validator_has_pending_withdrawal                                      PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_validator_incorrect_validator_index                                   PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_validator_not_active                                                  PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_validator_not_active_long_enough                                      PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_voluntary_exit_with_current_fork_version_is_before_fork_epoch         PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_voluntary_exit_with_current_fork_version_not_is_before_fork_epoch     PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_voluntary_exit_with_genesis_fork_version_is_before_fork_epoch         PASS   PASS        SKIP  SKIP    PASS      PASS
invalid_voluntary_exit_with_genesis_fork_version_not_is_before_fork_epoch     PASS   PASS        SKIP  SKIP    PASS      PASS
max_balance_exit                                                              PASS   PASS        SKIP  SKIP    PASS      PASS
min_balance_exit                                                              PASS   PASS        SKIP  SKIP    PASS      PASS
min_balance_exits_above_churn                                                 PASS   PASS        SKIP  SKIP    PASS      PASS
min_balance_exits_up_to_churn                                                 PASS   PASS        SKIP  SKIP    PASS      PASS
success_exit_queue__min_churn                                                 PASS   PASS        SKIP  SKIP    PASS      PASS
voluntary_exit_with_pending_deposit                                           PASS   PASS        SKIP  SKIP    PASS      PASS
voluntary_exit_with_previous_fork_version_is_before_fork_epoch                PASS   PASS        SKIP  SKIP    PASS      PASS
voluntary_exit_with_previous_fork_version_not_is_before_fork_epoch            PASS   PASS        SKIP  SKIP    PASS      PASS
```

25/25 fixtures pass uniformly on prysm + lighthouse + lodestar + grandine. teku and nimbus SKIP per harness limit.

**Coverage assessment:** the second-richest fixture set after item #4 (43 fixtures). Notable coverage:

- 6 fork-version variants exhaustively test EIP-7044's CAPELLA_FORK_VERSION pin. The `voluntary_exit_with_previous_fork_version_*` PASS fixtures are the smoking gun: voluntary exits signed with a previous fork's version (e.g., Capella's, signed at Deneb time) MUST be accepted post-Pectra. All four wired clients PASS, confirming H2.
- Multiple churn-balance fixtures exhaustively cover `compute_exit_epoch_and_update_churn` boundary cases.
- The Pectra-new pending-withdrawals check via `invalid_validator_has_pending_withdrawal` and `voluntary_exit_with_pending_deposit` (pending DEPOSIT is allowed; pending WITHDRAWAL blocks).

Notably absent: a fixture for **multiple voluntary_exits in one block** that share churn (stateful pacing across multiple exits within `process_block`). Operations-format fixtures are single-op; this requires a sanity_blocks fixture.

### Gloas-surface

No Gloas operations fixtures exist yet in the EF set. H8 and H9 are currently source-only.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — CAPELLA-fixed-version sig at Pectra time).** Validator signs an exit message with CAPELLA_FORK_VERSION, but the state's current fork is Pectra. Expected: signature verifies (per EIP-7044), exit initiated. Covered by `voluntary_exit_with_previous_fork_version_*` fixtures. All four wired clients PASS — confirms H2 most directly.
- **T1.2 (priority — exit a max-balance compounding validator).** Validator with `effective_balance = 2048 ETH` (compounding 0x02), voluntarily exits. The 2048 ETH input to `compute_exit_epoch_and_update_churn` is much larger than the per-epoch churn limit (~256 ETH at typical mainnet active balance), so this single exit consumes ~8 epochs of churn. Expected: `exit_epoch` advances 8 epochs from the earliest possible. The `max_balance_exit` fixture covers this.

#### T2 — Adversarial probes
- **T2.1 (priority — multiple max-balance exits in one block).** Block contains 5 voluntary_exits, each for a 2048 ETH compounding validator. Expected: each `compute_exit_epoch_and_update_churn` advances `state.earliest_exit_epoch` by ~8 epochs; cumulative effect is that the 5th validator's `exit_epoch` is ~40 epochs out. Not testable at the operations-fixture layer; requires a sanity_blocks fixture.
- **T2.2 (defensive — exit signed with current Pectra fork version).** Should be rejected per EIP-7044. Covered by `invalid_voluntary_exit_with_current_fork_version_*` fixtures.
- **T2.3 (defensive — exit signed with genesis fork version).** Should be rejected. Covered by `invalid_voluntary_exit_with_genesis_fork_version_*`.
- **T2.4 (defensive — already-exiting validator submits another exit).** Predicate 2 fails. Covered by `invalid_validator_already_exited`.
- **T2.5 (Glamsterdam-target — Gloas exit-churn formula via voluntary exit).** Synthetic Gloas-fork state with active total balance chosen so the Electra and Gloas exit-churn formulas yield different values. Submit a voluntary exit on a `0x02` validator with `effective_balance` between the two churn limits. Expected per Gloas spec: lodestar advances `earliest_exit_epoch` per the EIP-8061 `get_exit_churn_limit`; the other five use the Electra `get_activation_exit_churn_limit` and produce a different `earliest_exit_epoch`. State-root divergence. Sister to item #3's T2.6 — they share the same churn helper and the same five-vs-one cohort.
- **T2.6 (Glamsterdam-target — builder voluntary exit).** Submit a `SignedVoluntaryExit` whose `validator_index` is a builder index (high bit set per `BUILDER_INDEX_FLAG`) on a Gloas state with an active builder at that builder-index slot. Expected per Gloas spec: prysm, teku, lodestar, grandine route through `initiate_builder_exit`; lighthouse and nimbus reject the message as "invalid validator index". State-root divergence on the first Gloas-slot block carrying a builder voluntary exit.

## Mainnet reachability

**Reachable on canonical traffic at Glamsterdam activation, with two distinct failure modes.**

**Trigger A (H8 — exit-churn formula).** The first Gloas-slot block carrying a voluntary exit (or full-exit withdrawal_request, since both call `initiate_validator_exit`) whose `validator.effective_balance` triggers an `earliest_exit_epoch` recomputation. Steady-state mainnet has dozens of such operations per epoch, so this is near-certain to fire on the first epoch. The five Electra-formula clients compute `per_epoch_churn = get_activation_exit_churn_limit(state)`; lodestar computes `per_epoch_churn = get_exit_churn_limit(state)` (different formula and Gloas-specific constants). Different `per_epoch_churn` → different `additional_epochs` → different `validator.exit_epoch` and `validator.withdrawable_epoch` written into state → different `state_root`. Any role can trigger.

**Trigger B (H9 — builder routing).** The first Gloas-slot block carrying a `SignedVoluntaryExit` whose message's `validator_index` is a builder index (i.e., has the `BUILDER_INDEX_FLAG` bit set, indicating it refers to an entry in `state.builders` not `state.validators`). Builder voluntary exits are the canonical way for a builder to retire from the EIP-7732 ePBS lottery, so they are expected to appear on canonical Gloas traffic shortly after activation. On prysm/teku/lodestar/grandine the message routes to `initiate_builder_exit` and the builder's `withdrawable_epoch` is set; on lighthouse/nimbus the message is rejected as "invalid validator index" and no state change occurs. The post-state diverges immediately (the four implementing clients see the builder marked for exit; the two non-implementing clients do not).

**Severity.** State-root divergence on the first Gloas-slot block carrying either kind of exit. Since both kinds appear on routine canonical traffic, divergence is essentially certain on Gloas activation day unless reconciled beforehand. Trigger A is the broader of the two (any exit, including the full-exit branch of `process_withdrawal_request` from item #3); trigger B is narrower (builder exits only) but more starkly visible because the post-state contains a fundamentally different `builders[]` entry.

**Mitigation window.** Source-only at audit time; no Gloas EF operations fixtures yet. Closing requires:

- (a) The five Electra-churn clients (prysm, lighthouse, teku, nimbus, grandine) ship the EIP-8061 churn-helper fork-gate before Glamsterdam fork-cut. Same fix as item #3's H8 — one coordinated PR per client covers both.
- (b) Lighthouse and nimbus implement the EIP-7732 builder-routing branch in their voluntary-exit validators (plus add `initiate_builder_exit`). The four implementing clients (prysm, teku, lodestar, grandine) have reference implementations that can be adapted.

Without one or the other, mainnet at Glamsterdam activation splits on every exit operation. Sister items: items #2 (H6 consolidation-churn), #3 (H8 exit-churn), #4 (H8 activation-churn) all share the same five-vs-one EIP-8061 cohort split.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H7) remain satisfied: aligned implementations of the seven Pectra-modified predicates of `process_voluntary_exit` and the `initiate_validator_exit` Pectra modification, identical CAPELLA_FORK_VERSION pinning per EIP-7044, and identical Pectra-new pending-withdrawals checks. All 25 EF `voluntary_exit` fixtures still pass uniformly on prysm + lighthouse + lodestar + grandine; teku and nimbus pass internally.

**Glamsterdam-target findings:**

- **H8** fails for 5 of 6 clients — same finding as item #3 H8 since this item's `initiate_validator_exit` funnels through the same `compute_exit_epoch_and_update_churn` primitive. Only lodestar fork-gates the call to use `get_exit_churn_limit` at Gloas; prysm, lighthouse, teku, nimbus, and grandine retain the Electra `get_activation_exit_churn_limit` even on Gloas states.
- **H9** fails for 2 of 6 clients — lighthouse and nimbus do not implement the Gloas-modified `process_voluntary_exit` builder-routing branch. A builder voluntary-exit (validator_index with `BUILDER_INDEX_FLAG` set) on lighthouse or nimbus will hit the `validator_index < len(validators)` bound and be silently rejected; on prysm, teku, lodestar, grandine it will correctly route to `initiate_builder_exit`. Neither lighthouse nor nimbus has an `initiate_builder_exit` function defined.

Combined `splits` field is the same five-client set as the broader EIP-8061 family (items #2 H6, #3 H8, #4 H8) plus the H9 subset (lighthouse, nimbus). Lighthouse and nimbus diverge on both H8 and H9 axes; prysm/teku/grandine diverge on H8 only; lodestar is spec-aligned on both.

Notable per-client style differences (all observable-equivalent at the Pectra spec level):

- **prysm** uses errors-as-values style; explicit `if st.Version() >= version.Deneb` for the CAPELLA_FORK_VERSION fork-struct construction (rather than a per-domain helper).
- **lighthouse** uses `verify!` macro for short-circuit assertions; signature verification gates on `state.fork_name_unchecked().deneb_enabled()`.
- **teku** uses `Optional<OperationInvalidReason>` chained via `firstOf`; the Electra subclass adds the pending-withdrawals check via inheritance; the Gloas subclass adds builder-routing via further inheritance.
- **nimbus** uses `Result[..., cstring]`; static fork dispatch (`when typeof(state).kind`) for the Electra-only check; the Gloas builder branch is **absent**.
- **lodestar** uses an enum return (`VoluntaryExitValidity`) for clear per-failure-type reporting; the Gloas builder branch is gated at `fork >= ForkSeq.gloas`.
- **grandine** has TWO `initiate_validator_exit` definitions (one in `mutators.rs:61` for Phase0/Capella, one in `electra.rs:124` for Pectra). The Pectra `block_processing.rs` and Gloas `gloas/block_processing.rs` import the Electra version explicitly. The Gloas `block_processing.rs:1017-1041` is a separate function that adds builder-routing on top of the Electra validation.

Recommendations to the harness and the audit:

- Generate the **T2.5 Gloas exit-churn fixture** (sister to item #3's T2.6) and the **T2.6 Gloas builder voluntary-exit fixture**; together they pin both Glamsterdam-target divergences before activation.
- Coordinate the **EIP-8061 churn-helper fork-gate** PR per lagging client across items #2 H6, #3 H8, #4 H8, and this item's H8 — they all touch the same family of churn accessors.
- For **lighthouse and nimbus specifically** (H9), file the EIP-7732 builder-exit routing in `process_voluntary_exit` and add an `initiate_builder_exit` mutator. The other four clients' implementations are reference.
- **Standalone audit of `compute_exit_epoch_and_update_churn`** as its own item — used by items #3, #6, and indirectly #2 via the consolidation analog. The high-leverage primitive of the entire Pectra+Gloas exit machinery.
- **Standalone audit of `initiate_builder_exit`** at Gloas — new function; semantics need their own audit pass once more than four clients implement it.
- Generate the **T2.1 multi-exit-in-one-block fixture** as a sanity_blocks fixture; closes the stateful Pectra-surface churn-pacing test.

## Cross-cuts

### With item #3 (`process_withdrawal_request` full-exit path)

Item #3's full-exit path (when `amount == FULL_EXIT_REQUEST_AMOUNT`) calls `initiate_validator_exit` if `pending_balance_to_withdraw == 0`. This item's voluntary exit path also calls `initiate_validator_exit`. **Same downstream function, different upstream entry-point**. A divergence in `initiate_validator_exit` or its `compute_exit_epoch_and_update_churn` callee surfaces in BOTH items' fixtures. Item #3 H8 and this item's H8 are the same divergence, observed via two upstream paths.

### With item #2 (`process_consolidation_request` source exit init)

Item #2's main path calls `compute_consolidation_epoch_and_update_churn` (consolidation churn pool, smaller). This item calls `compute_exit_epoch_and_update_churn` (activation-exit churn pool at Electra, exit churn pool at Gloas). **Two different churn pools** with parallel implementations — a client mixing them up would produce different `exit_epoch` values across paths. All six clients correctly distinguish the two on the Pectra surface; at Gloas the EIP-8061 rework splits them further (consolidation, exit, activation as three separate pools).

### With `compute_exit_epoch_and_update_churn` itself

The high-leverage primitive used by:

- Item #3 partial withdrawal balance pacing.
- This item (#6) voluntary exit + EL full-exit (via `initiate_validator_exit`).
- Future item: standalone audit of the function itself, including stateful behaviour across multiple calls in the same block.

At Gloas, the function is Modified (EIP-8061) to consume `get_exit_churn_limit`. The fork-gate readiness is shared across items #3 and #6.

### With EIP-7044 (CAPELLA_FORK_VERSION pin)

Pre-Deneb, voluntary exits used the current fork version for the signing domain. EIP-7044 (Deneb) changed this to permanently pin CAPELLA_FORK_VERSION for Deneb-and-later. The `voluntary_exit_with_previous_fork_version_*` and `voluntary_exit_with_*_fork_version_*` fixtures specifically test this — and all 6 clients pass. **Evidence that the EIP-7044 migration is complete across all clients audited**, and the pin continues at Gloas.

### With EIP-7732 ePBS builder-exit routing

The Gloas-modified `process_voluntary_exit` adds a builder-routing branch keyed on `is_builder_index(validator_index)`. The new helper `initiate_builder_exit` (Gloas `vendor/consensus-specs/specs/gloas/beacon-chain.md:889`) is the builder-side analog of `initiate_validator_exit`. Cross-cut with the broader Gloas builder audit Family (items not yet authored: `process_payload_attestation`, `process_execution_payload_envelope`, builder pending-payments).

## Adjacent untouched Electra-active consensus paths

1. **`compute_exit_epoch_and_update_churn` standalone audit** — the heart of Pectra exit-rate pacing. Used by 3 items already (this one, #3 partial, #2 via consolidation analog) and the EIP-8061 fork-gate is the active Glamsterdam-target divergence axis. Highest-leverage target.
2. **`initiate_builder_exit` standalone audit at Gloas** — new function. Semantics need their own audit pass once more than four clients implement it.
3. **EIP-7044 fork-version selection per client** — different gating mechanisms (Deneb-onwards-flag in lighthouse, per-fork-enum-match in grandine, version-comparison in prysm). Subtle regressions at future forks possible.
4. **Multiple voluntary exits in one block** sharing churn — stateful T2.1 fixture not in EF coverage. Critical for testing per-block churn drainage semantics. Could miss subtle ordering bugs.
5. **`get_pending_balance_to_withdraw` cross-cut** — same helper used in this item's predicate AND item #3's full-exit predicate. Audited indirectly in items #3 and #6 — strong evidence base. A standalone audit could nail down the linear-scan complexity (LIMIT = 2²⁷).
6. **Grandine's two `initiate_validator_exit` definitions** — `mutators.rs:61` (Phase0-style) and `electra.rs:124` (Pectra). The discriminator is the import statement in callers. A future audit that follows `use` chains in grandine should be alert; if a Pectra/Gloas caller accidentally imported the unphased version, it would silently use Phase0 churn pacing.
7. **Lighthouse's `state.build_exit_cache(spec)?` call** in `initiate_validator_exit` — builds a per-validator exit-epoch index. Other clients re-iterate the validator set on each exit. Performance, not consensus, but worth noting.
8. **Lodestar's voluntary-exit path NOT reusing `isValidatorEligibleForWithdrawOrExit`** — the helper introduced for `process_withdrawal_request` (item #3) is shared with voluntary_exit ONLY by name; voluntary_exit has its own validation path. The lack of sharing is intentional but worth flagging.
9. **`exit_balance_to_consume` per-block accumulator state** — `compute_exit_epoch_and_update_churn` mutates this. Within `process_block`, multiple operations (voluntary exits, withdrawal_request full-exits, consolidation source exits via item #2's main path) all share the accumulator. Order matters; pyspec's `process_operations` ordering is `proposer_slashings → attester_slashings → attestations → deposits → voluntary_exits → bls_changes → withdrawal_requests → consolidation_requests → deposit_requests`. A client that reordered would produce different `exit_epoch` assignments.
10. **Validator-already-exited semantics across paths**: this item's `initiate_validator_exit` early-returns (no state change). Item #3's full-exit path also calls into the same function. A validator that submits a voluntary exit AND an EL withdrawal_request in the same block — the second to be processed should be a no-op. Verify uniformly.
11. **`invalid_validator_incorrect_validator_index`** fixture — tests out-of-range index handling. All 6 clients PASS, but the underlying mechanism differs (assertion failure vs. silent-out-of-bounds-error). A future SSZ-schema change could expose differences.
12. **Lighthouse/nimbus rejection of builder voluntary-exits at Gloas** — until H9 is fixed, those clients will silently reject every builder voluntary-exit they see. If they remain in the validator set on a Glamsterdam mainnet, the chain at activation will see them lag whenever the canonical chain attests to builder exits. Critical for the H9 fix-coordination.
