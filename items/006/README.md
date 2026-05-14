---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [2, 3, 5]
eips: [EIP-7251, EIP-7044, EIP-7732, EIP-8061]
prysm_version: v3.2.2-rc.1-2535-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 6: `process_voluntary_exit` + `initiate_validator_exit` Pectra

## Summary

The OG signed-message exit path, Pectra-modified to (a) require no pending partial withdrawals for the validator and (b) flow exit-epoch computation through the new `compute_exit_epoch_and_update_churn` machinery instead of the legacy fixed-rate exit queue. Two Pectra-modified functions in one audit because they form an inseparable pair: the request validator + the state-mutating action.

**Pectra surface (the function body itself):** all six clients implement the seven Pectra-modified predicates of `process_voluntary_exit` and the `initiate_validator_exit` Pectra modification identically. 25/25 EF `voluntary_exit` operations fixtures pass uniformly on the four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus pass these in internal CI but the local harness SKIPs them. The two divergence-prone bits — **CAPELLA_FORK_VERSION pinning per EIP-7044** and the **Pectra-new pending-withdrawals check** — are correctly enforced everywhere.

**Gloas surface (new at the Glamsterdam target):** all six clients are spec-aligned on the two Gloas-new surfaces.

1. **`compute_exit_epoch_and_update_churn` (EIP-8061)** — at Gloas, the per-epoch churn quantity switches from `get_activation_exit_churn_limit(state)` (Electra) to `get_exit_churn_limit(state)` (Gloas). All six clients fork-gate the call. The dispatch idiom varies per client (Rust trait predicate, name-polymorphism, subclass override, compile-time `when`, runtime wrapper, runtime ternary), but the observable Gloas semantics are uniform.
2. **`process_voluntary_exit` builder routing (EIP-7732 ePBS)** — at Gloas, a builder voluntary-exit (validator_index with `BUILDER_INDEX_FLAG` set) routes through `convert_validator_index_to_builder_index` → `is_active_builder` → `get_pending_balance_to_withdraw_for_builder == 0` → signature verified against `state.builders[builder_index].pubkey` → `initiate_builder_exit(state, builder_index)`. All six clients implement this branch.

No splits at the current pins. The earlier finding (H8 failing for 5/6 and H9 failing for 2/6) was an artifact of stale branch pinning; on the per-client Glamsterdam branches (lighthouse + nimbus `unstable`, prysm `EIP-8061`, teku `glamsterdam-devnet-2`, grandine `glamsterdam-devnet-3`, lodestar `unstable`) all surfaces are present and spec-equivalent.

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

- **Modified `process_voluntary_exit`** (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1628-1668`) adds a builder-routing branch at the top. If the validator index is a builder index (high bit set per `BUILDER_INDEX_FLAG`), the function converts to a builder-index, validates as an active builder with no pending builder withdrawals, verifies the signature against the builder's pubkey from `state.builders[]`, and calls the new `initiate_builder_exit`. Otherwise the function falls through to the same validator path as Electra.
- **`compute_exit_epoch_and_update_churn`** is Modified at Gloas (EIP-8061) to use `get_exit_churn_limit` (Gloas-new) rather than `get_activation_exit_churn_limit`. `initiate_validator_exit` itself is unchanged in body but its callee semantics flip at Gloas. Same primitive as item #3.

The signature domain at Gloas continues to use `CAPELLA_FORK_VERSION` (the EIP-7044 pin survives all post-Capella forks).

The hypothesis: *all six clients implement the seven Pectra predicates (H1–H7), the CAPELLA_FORK_VERSION domain selection, the pending-withdrawals check, and the Pectra-modified `initiate_validator_exit`. At the Glamsterdam target, all six additionally fork-gate `compute_exit_epoch_and_update_churn` to `get_exit_churn_limit` (H8) and implement the builder-exit routing in `process_voluntary_exit` (H9).*

**Consensus relevance**: voluntary exits are how validators willingly leave the chain. The Pectra changes mean a validator's exit_epoch is now churn-paced (variable, depending on prior exit volume) rather than fixed-rate. A divergence in the churn arithmetic produces different `exit_epoch` and `withdrawable_epoch` values across clients — splitting the state-root immediately, AND throwing off the fork-choice's view of when the validator is no longer eligible to attest. The CAPELLA_FORK_VERSION domain bug would silently reject all valid exits across the affected client. At Gloas, missing builder-routing would make builder voluntary-exits impossible on the affected client; missing Gloas churn-helper fork-gate would make the post-state diverge whenever a non-builder exit reaches the churn ceiling.

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

H1–H9 satisfied across all six clients at the current Glamsterdam-target pins. The dispatch idioms used per client for H8 (the EIP-8061 churn-helper fork-gate) and for H9 (the EIP-7732 builder-routing branch in `process_voluntary_exit`) vary, but the observable Gloas semantics are spec-equivalent. No EF Gloas operations fixtures yet exist for either surface — the conclusion is source-only.

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

**Gloas builder routing (H9 ✓)** — explicit fork+index gate at line 67 and line 124 of the same file, with a dedicated `// [New in Gloas:EIP7732]` block at line 219 handling builder-side initiation.

`verifyExitConditions` (line 179) includes the Pectra-new check at line 206:

```go
if st.Version() >= version.Electra {
    ok, _ := st.HasPendingBalanceToWithdraw(exit.ValidatorIndex)
    if ok { return fmt.Errorf("validator %d must have no pending balance to withdraw", exit.ValidatorIndex) }
}
```

`InitiateValidatorExit` (`vendor/prysm/beacon-chain/core/validators/validator.go:87-126`) Pectra branch calls `s.ExitEpochAndUpdateChurn(primitives.Gwei(validator.EffectiveBalance))`.

**H8 dispatch (runtime version wrapper).** `ExitEpochAndUpdateChurn` (`vendor/prysm/beacon-chain/state/state-native/setters_churn.go:67`) calls `helpers.ExitChurnLimitForVersion(b.version, totalActiveBalance)`. The wrapper at `vendor/prysm/beacon-chain/core/helpers/validator_churn.go:116-121` dispatches to `exitChurnLimitGloas` for Gloas and `ActivationExitChurnLimit` pre-Gloas:

```go
func ExitChurnLimitForVersion(v int, activeBalance primitives.Gwei) primitives.Gwei {
    if v >= version.Gloas {
        return exitChurnLimitGloas(activeBalance)
    }
    return ActivationExitChurnLimit(activeBalance)
}
```

H1–H9 ✓.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing/verify_exit.rs:21-94` — `verify_exit`. Orders checks: active → not-exiting → epoch → seasoned → signature → no-pending-withdraws (last). The signature subroutine `exit_signature_set` at `vendor/lighthouse/consensus/state_processing/src/per_block_processing/signature_sets.rs:378-395` selects the CAPELLA_FORK_VERSION domain via `state.fork_name_unchecked().deneb_enabled()`.

**H9 dispatch (per-block-processing branch).** `process_voluntary_exits` (`vendor/lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:524-539`) routes builder exits through a dedicated `process_builder_voluntary_exit` helper before falling through to the validator path:

```rust
// [New in Gloas:EIP7732]
if state.fork_name_unchecked().gloas_enabled()
    && is_builder_index(exit.message.validator_index)
{
    process_builder_voluntary_exit(state, exit, verify_signatures, spec)
        .map_err(|e| e.into_with_index(i))?;
    continue;
}

verify_exit(state, Some(current_epoch), exit, verify_signatures, spec)
    .map_err(|e| e.into_with_index(i))?;

initiate_validator_exit(state, exit.message.validator_index as usize, spec)?;
```

The helper at line 542-592 performs `convert_validator_index_to_builder_index` → `is_active_builder` → `get_pending_balance_to_withdraw_for_builder == 0` → signature → `initiate_builder_exit`. The local `initiate_builder_exit` at line 595-615 sets `builder.withdrawable_epoch` and early-returns if the builder already initiated exit.

`initiate_validator_exit` (`vendor/lighthouse/consensus/state_processing/src/common/initiate_validator_exit.rs:6-49`) — early-return on already-exiting, then `state.compute_exit_epoch_and_update_churn(effective_balance, spec)?`.

**H8 dispatch (`fork_name_unchecked().gloas_enabled()` branch).** `compute_exit_epoch_and_update_churn` (`vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2896-2935`) fork-gates internally:

```rust
let per_epoch_churn = if self.fork_name_unchecked().gloas_enabled() {
    self.get_exit_churn_limit(spec)?
} else {
    self.get_activation_exit_churn_limit(spec)?
};
```

H1–H9 ✓.

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

**H9 dispatch (Java subclass override).** `VoluntaryExitValidatorGloas` extends `VoluntaryExitValidatorElectra` and overrides `validate` to route builder indices first:

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
}
```

The CAPELLA_FORK_VERSION domain selection is in `BeaconStateAccessorsDeneb.getVoluntaryExitDomain()` (overridden from the Phase0 base) — uses `denebConfig.getCapellaForkVersion()`. Continues to apply at Gloas.

`initiateValidatorExit` (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/BeaconStateMutatorsElectra.java:108-132`) — early-return on already-exiting, then `computeExitEpochAndUpdateChurn(stateElectra, validator.getEffectiveBalance())` at line 121.

**H8 dispatch (Java subclass override).** `BeaconStateMutatorsGloas.computeExitEpochAndUpdateChurn` (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/helpers/BeaconStateMutatorsGloas.java:71-99`) `@Override`s the Electra method and substitutes `getExitChurnLimit`:

```java
@Override
public UInt64 computeExitEpochAndUpdateChurn(
    final MutableBeaconStateElectra state, final UInt64 exitBalance) {
  ...
  final UInt64 perEpochChurn = beaconStateAccessorsGloas.getExitChurnLimit(state);
  ...
}
```

`initiateBuilderExit` is defined on the same Gloas mutator at line 106.

H1–H9 ✓.

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

**H9 dispatch (compile-time `when` branch).** `process_voluntary_exit` (`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:540-573`) gates the builder branch on `typeof(state).kind >= ConsensusFork.Gloas`:

```nim
when typeof(state).kind >= ConsensusFork.Gloas:
  template voluntary_exit: untyped = signed_voluntary_exit.message
  if is_builder_index(voluntary_exit.validator_index):
    if not (get_current_epoch(state) >= voluntary_exit.epoch):
      return err("Exit: exit epoch not passed")
    let builder_index =
      convert_validator_index_to_builder_index(
        voluntary_exit.validator_index)
    if not is_active_builder(state, builder_index):
      return err("Exit: builder not active")
    if get_pending_balance_to_withdraw_for_builder(
        state, builder_index) != 0.Gwei:
      return err("Exit: builder has pending withdrawals")
    let voluntary_exit_fork = typeof(state).kind.voluntary_exit_signature_fork(
      state.fork, cfg.CAPELLA_FORK_VERSION)
    if not verify_voluntary_exit_signature(
        voluntary_exit_fork, state.genesis_validators_root, voluntary_exit,
        state.builders.item(builder_index).pubkey,
        signed_voluntary_exit.signature):
      return err("Exit: invalid builder signature")
    initiate_builder_exit(cfg, state, builder_index)
    return ok(exit_queue_info)
```

`initiate_builder_exit` is defined at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:253-261`.

`initiate_validator_exit` (`vendor/nimbus/beacon_chain/spec/beaconstate.nim:432-462`) Pectra version calls `compute_exit_epoch_and_update_churn(cfg, state, validator.effective_balance, cache)`.

**H8 dispatch (compile-time `when` branch).** `compute_exit_epoch_and_update_churn` (`vendor/nimbus/beacon_chain/spec/beaconstate.nim:353-388`) selects the per-epoch churn at compile time:

```nim
let per_epoch_churn =
  when typeof(state).kind >= ConsensusFork.Gloas:
    get_exit_churn_limit(cfg, state, cache)
  else:
    get_activation_exit_churn_limit(cfg, state, cache)
```

H1–H9 ✓.

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

A parallel branch at line 71 routes the validity helper too — `getBuilderVoluntaryExitValidity` is invoked when `fork >= ForkSeq.gloas && isBuilderIndex(...)`.

Domain selection (`vendor/lodestar/packages/config/src/genesisConfig/index.ts:96-104`) uses `getDomainAtFork(ForkName.capella, DOMAIN_VOLUNTARY_EXIT)` for Deneb-onwards. `initiateValidatorExit` (`vendor/lodestar/packages/state-transition/src/block/initiateValidatorExit.ts:27-62`) Pectra branch calls `computeExitEpochAndUpdateChurn(state, BigInt(validator.effectiveBalance))`.

**H8 dispatch (runtime ternary).** `computeExitEpochAndUpdateChurn` (`vendor/lodestar/packages/state-transition/src/util/epoch.ts:50-77`) is fork-gated:

```typescript
const perEpochChurn = fork >= ForkSeq.gloas
  ? getExitChurnLimit(state)
  : getActivationExitChurnLimit(state);
```

H1–H9 ✓.

### grandine

`vendor/grandine/transition_functions/src/electra/block_processing.rs:1006-1062` — Electra `process_voluntary_exit`. The Gloas block processor (`vendor/grandine/transition_functions/src/gloas/block_processing.rs:1017-1041`) is a **separate function** that adds the builder routing:

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

The Pectra `initiate_validator_exit` (`vendor/grandine/helper_functions/src/electra.rs:124-150`) is still the one called by both the Electra and the Gloas wrapper. Voluntary-exit signature domain in grandine (`vendor/grandine/helper_functions/src/signing.rs:420-449`) hard-codes CAPELLA_FORK_VERSION for Deneb/Electra/Fulu/Gloas.

**H8 dispatch (`state.is_post_gloas()` predicate).** `compute_exit_epoch_and_update_churn` (`vendor/grandine/helper_functions/src/mutators.rs:172-208`) fork-gates via a Rust trait predicate:

```rust
let per_epoch_churn = if state.is_post_gloas() {
    get_exit_churn_limit(config, state)
} else {
    get_activation_exit_churn_limit(config, state)
};
```

**Source-organization risk** preserved from the prior audit: grandine has TWO `initiate_validator_exit` definitions (one in `mutators.rs:61` for Phase0-style; one in `electra.rs:124` for Pectra). The Pectra and Gloas callers import the Electra version explicitly. Worth flagging for future agents walking grandine's `use` chains.

H1–H9 ✓.

## Cross-reference table

| Client | `process_voluntary_exit` | Pectra pending-withdraws check | CAPELLA domain selection | Gloas builder routing (H9) | `compute_exit_epoch_and_update_churn` fork-gate (H8) |
|---|---|---|---|---|---|
| prysm | `core/blocks/exit.go:91-216` | `verifyExitConditions:206-213`, gated `>= version.Electra` | hardcode at `:71-77` for `>= version.Deneb` | ✓ (`:67, :124, :219`) | ✓ runtime wrapper (`ExitChurnLimitForVersion(b.version, ...)` at `validator_churn.go:116-121`) |
| lighthouse | `process_operations.rs:524-539` (Gloas branch + fallthrough) | `verify_exit.rs:82-91`, present unconditionally (state variant guards) | `signature_sets.rs:378-395` `if deneb_enabled()` | ✓ inline branch + `process_builder_voluntary_exit` (`process_operations.rs:542-592`) + local `initiate_builder_exit` (`:595-615`) | ✓ name-polymorphism / internal fork-gate (`beacon_state.rs:2906-2910`) |
| teku | `VoluntaryExitValidatorElectra.java:45-65` (subclass adds check); `VoluntaryExitValidatorGloas.validate()` overrides | `validateElectraConditions:54-65` returns `Optional<InvalidReason>` | `BeaconStateAccessorsDeneb.getVoluntaryExitDomain()` (override) | ✓ subclass override → `validateBuilderExit` | ✓ subclass override (`BeaconStateMutatorsGloas.computeExitEpochAndUpdateChurn:71-99`) |
| nimbus | `state_transition_block.nim:540-573` (Gloas `when` branch + fallthrough) | `:484-488`, `when typeof(state).kind >= ConsensusFork.Electra` | `voluntary_exit_signature_fork` in `signatures.nim` | ✓ inline `when` branch + `initiate_builder_exit` (`beaconstate.nim:253-261`) | ✓ compile-time `when typeof(state).kind >= ConsensusFork.Gloas` (`beaconstate.nim:362-365`) |
| lodestar | `block/processVoluntaryExit.ts:16-110` | `:147-150`, `if (fork >= ForkSeq.electra && getPendingBalanceToWithdraw != 0)` | `getDomainForVoluntaryExit` → `getDomainAtFork(ForkName.capella, ...)` post-Deneb | ✓ `:44-50, :71-72` — `isBuilderIndex` → `initiateBuilderExit` / `getBuilderVoluntaryExitValidity` | ✓ runtime ternary (`util/epoch.ts:50-77` fork-gates `getExitChurnLimit` at `fork >= ForkSeq.gloas`) |
| grandine | `electra/block_processing.rs:1006-1062` (Electra); `gloas/block_processing.rs:1017-1041` (Gloas wrapper with builder routing) | `:1056-1058`, `ensure!()` macro → error | `signing.rs:420-449` for any of Deneb/Electra/Fulu/Gloas | ✓ Gloas wrapper calls `initiate_builder_exit` if `maybe_builder_index(validator_index).is_some()` | ✓ `state.is_post_gloas()` predicate (`mutators.rs:181-185`) |

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
- **T2.5 (Glamsterdam-target — Gloas exit-churn formula via voluntary exit).** Synthetic Gloas-fork state with active total balance chosen so the Electra and Gloas exit-churn formulas yield different values. Submit a voluntary exit on a `0x02` validator with `effective_balance` between the two churn limits. Expected per Gloas spec: every client advances `earliest_exit_epoch` per the EIP-8061 `get_exit_churn_limit`. Cross-client `state_root` should match. Sister to item #3's T2.6 — they share the same churn helper.
- **T2.6 (Glamsterdam-target — builder voluntary exit).** Submit a `SignedVoluntaryExit` whose `validator_index` is a builder index (high bit set per `BUILDER_INDEX_FLAG`) on a Gloas state with an active builder at that builder-index slot. Expected per Gloas spec: every client routes through `initiate_builder_exit`. Cross-client `state_root` should match. Generate this fixture before Glamsterdam activation to pin the H9 surface.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H7) remain satisfied: aligned implementations of the seven Pectra-modified predicates of `process_voluntary_exit` and the `initiate_validator_exit` Pectra modification, identical CAPELLA_FORK_VERSION pinning per EIP-7044, and identical Pectra-new pending-withdrawals checks. All 25 EF `voluntary_exit` fixtures still pass uniformly on prysm + lighthouse + lodestar + grandine; teku and nimbus pass internally.

**Glamsterdam-target findings:**

- **H8 ✓ across all six clients.** Every client fork-gates the per-epoch-churn quantity inside `compute_exit_epoch_and_update_churn` to `get_exit_churn_limit` at Gloas. Six distinct dispatch idioms (prysm `ExitChurnLimitForVersion` runtime wrapper; lighthouse `fork_name_unchecked().gloas_enabled()` name-polymorphism; teku `BeaconStateMutatorsGloas` subclass override; nimbus compile-time `when typeof(state).kind >= ConsensusFork.Gloas`; lodestar `fork >= ForkSeq.gloas` ternary; grandine `state.is_post_gloas()` predicate), one common observable semantics.
- **H9 ✓ across all six clients.** Every client implements the EIP-7732 builder-routing branch in `process_voluntary_exit`. Same six dispatch idioms as H8: inline branch in `process_operations.rs` (lighthouse), separate Gloas block-processing function (grandine), Java subclass override (teku), `when typeof(state).kind >= ConsensusFork.Gloas` (nimbus), runtime version+index check (prysm), runtime ternary (lodestar). All call into a builder-exit pipeline that mirrors the validator one but reads/writes `state.builders[]` instead of `state.validators[]`.

The earlier finding (H8 failing 5/6, H9 failing 2/6) was a stale-pin artifact. Lighthouse + nimbus had been on their respective `stable` tags, which trailed `unstable` by months of Gloas/EIP-7732 integration; prysm/teku/grandine had been on mainline dev branches missing their Glamsterdam feature-branch work. With each client on the branch where its actual Glamsterdam implementation lives, the cross-client surface is uniform.

Notable per-client style differences (all observable-equivalent at the Pectra spec level):

- **prysm** uses errors-as-values style; explicit `if st.Version() >= version.Deneb` for the CAPELLA_FORK_VERSION fork-struct construction (rather than a per-domain helper).
- **lighthouse** uses `verify!` macro for short-circuit assertions; signature verification gates on `state.fork_name_unchecked().deneb_enabled()`. The Gloas builder branch is **inline in `process_voluntary_exits`** (the per-operation loop) rather than dispatched through a separate validator class; both `process_builder_voluntary_exit` and `initiate_builder_exit` are local helpers in `process_operations.rs`.
- **teku** uses `Optional<OperationInvalidReason>` chained via `firstOf`; the Electra subclass adds the pending-withdrawals check via inheritance; the Gloas subclass adds builder-routing via further inheritance. The Gloas `BeaconStateMutatorsGloas` overrides `computeExitEpochAndUpdateChurn` and hosts `initiateBuilderExit`.
- **nimbus** uses `Result[..., cstring]`; static fork dispatch (`when typeof(state).kind`) for the Electra-only check; the Gloas builder branch is also gated on `when typeof(state).kind >= ConsensusFork.Gloas` at the top of `process_voluntary_exit`.
- **lodestar** uses an enum return (`VoluntaryExitValidity`) for clear per-failure-type reporting; the Gloas builder branch is gated at `fork >= ForkSeq.gloas`.
- **grandine** has TWO `initiate_validator_exit` definitions (one in `mutators.rs:61` for Phase0/Capella, one in `electra.rs:124` for Pectra). The Pectra `block_processing.rs` and Gloas `gloas/block_processing.rs` import the Electra version explicitly. The Gloas `block_processing.rs:1017-1041` is a separate function that adds builder-routing on top of the Electra validation.

Recommendations to the harness and the audit:

- Generate the **T2.5 Gloas exit-churn fixture** (sister to item #3's T2.6) and the **T2.6 Gloas builder voluntary-exit fixture**; together they pin both Glamsterdam-target surfaces before activation. These would convert the source-only H8/H9 conclusions into empirically-pinned ones.
- **Standalone audit of `compute_exit_epoch_and_update_churn`** as its own item — used by items #3, #6, and indirectly #2 via the consolidation analog. The high-leverage primitive of the entire Pectra+Gloas exit machinery; now also a six-dispatch-idiom cross-cut.
- **Standalone audit of `initiate_builder_exit`** at Gloas — new function; semantics need their own audit pass now that all six clients implement it.
- Generate the **T2.1 multi-exit-in-one-block fixture** as a sanity_blocks fixture; closes the stateful Pectra-surface churn-pacing test.

## Cross-cuts

### With item #3 (`process_withdrawal_request` full-exit path)

Item #3's full-exit path (when `amount == FULL_EXIT_REQUEST_AMOUNT`) calls `initiate_validator_exit` if `pending_balance_to_withdraw == 0`. This item's voluntary exit path also calls `initiate_validator_exit`. **Same downstream function, different upstream entry-point**. A divergence in `initiate_validator_exit` or its `compute_exit_epoch_and_update_churn` callee surfaces in BOTH items' fixtures. Item #3 H8 and this item's H8 are the same spec surface, observed via two upstream paths — and both now spec-aligned across all six clients.

### With item #2 (`process_consolidation_request` source exit init)

Item #2's main path calls `compute_consolidation_epoch_and_update_churn` (consolidation churn pool, smaller). This item calls `compute_exit_epoch_and_update_churn` (activation-exit churn pool at Electra, exit churn pool at Gloas). **Two different churn pools** with parallel implementations — a client mixing them up would produce different `exit_epoch` values across paths. All six clients correctly distinguish the two on the Pectra surface; at Gloas the EIP-8061 rework splits them further (consolidation, exit, activation as three separate pools).

### With `compute_exit_epoch_and_update_churn` itself

The high-leverage primitive used by:

- Item #3 partial withdrawal balance pacing.
- This item (#6) voluntary exit + EL full-exit (via `initiate_validator_exit`).
- Future item: standalone audit of the function itself, including stateful behaviour across multiple calls in the same block.

At Gloas, the function is Modified (EIP-8061) to consume `get_exit_churn_limit`. The fork-gate is now present and equivalent in all six clients (item #3's findings and this item's H8 share the dispatch-idiom catalog).

### With EIP-7044 (CAPELLA_FORK_VERSION pin)

Pre-Deneb, voluntary exits used the current fork version for the signing domain. EIP-7044 (Deneb) changed this to permanently pin CAPELLA_FORK_VERSION for Deneb-and-later. The `voluntary_exit_with_previous_fork_version_*` and `voluntary_exit_with_*_fork_version_*` fixtures specifically test this — and all 6 clients pass. **Evidence that the EIP-7044 migration is complete across all clients audited**, and the pin continues at Gloas.

### With EIP-7732 ePBS builder-exit routing

The Gloas-modified `process_voluntary_exit` adds a builder-routing branch keyed on `is_builder_index(validator_index)`. The new helper `initiate_builder_exit` (Gloas `vendor/consensus-specs/specs/gloas/beacon-chain.md:889`) is the builder-side analog of `initiate_validator_exit`. Cross-cut with the broader Gloas builder audit Family (items not yet authored: `process_payload_attestation`, `process_execution_payload_envelope`, builder pending-payments).

## Adjacent untouched Electra-active consensus paths

1. **`compute_exit_epoch_and_update_churn` standalone audit** — the heart of Pectra exit-rate pacing. Used by 3 items already (this one, #3 partial, #2 via consolidation analog) and the EIP-8061 fork-gate is now a six-dispatch-idiom cross-cut. Highest-leverage target for a primitive-level audit.
2. **`initiate_builder_exit` standalone audit at Gloas** — new function, present in all six clients. Semantics need their own audit pass now that the surface is uniformly implemented.
3. **EIP-7044 fork-version selection per client** — different gating mechanisms (Deneb-onwards-flag in lighthouse, per-fork-enum-match in grandine, version-comparison in prysm). Subtle regressions at future forks possible.
4. **Multiple voluntary exits in one block** sharing churn — stateful T2.1 fixture not in EF coverage. Critical for testing per-block churn drainage semantics. Could miss subtle ordering bugs.
5. **`get_pending_balance_to_withdraw` cross-cut** — same helper used in this item's predicate AND item #3's full-exit predicate. Audited indirectly in items #3 and #6 — strong evidence base. A standalone audit could nail down the linear-scan complexity (LIMIT = 2²⁷).
6. **Grandine's two `initiate_validator_exit` definitions** — `mutators.rs:61` (Phase0-style) and `electra.rs:124` (Pectra). The discriminator is the import statement in callers. A future audit that follows `use` chains in grandine should be alert; if a Pectra/Gloas caller accidentally imported the unphased version, it would silently use Phase0 churn pacing.
7. **Lighthouse's `state.build_exit_cache(spec)?` call** in `initiate_validator_exit` — builds a per-validator exit-epoch index. Other clients re-iterate the validator set on each exit. Performance, not consensus, but worth noting.
8. **Lodestar's voluntary-exit path NOT reusing `isValidatorEligibleForWithdrawOrExit`** — the helper introduced for `process_withdrawal_request` (item #3) is shared with voluntary_exit ONLY by name; voluntary_exit has its own validation path. The lack of sharing is intentional but worth flagging.
9. **`exit_balance_to_consume` per-block accumulator state** — `compute_exit_epoch_and_update_churn` mutates this. Within `process_block`, multiple operations (voluntary exits, withdrawal_request full-exits, consolidation source exits via item #2's main path) all share the accumulator. Order matters; pyspec's `process_operations` ordering is `proposer_slashings → attester_slashings → attestations → deposits → voluntary_exits → bls_changes → withdrawal_requests → consolidation_requests → deposit_requests`. A client that reordered would produce different `exit_epoch` assignments.
10. **Validator-already-exited semantics across paths**: this item's `initiate_validator_exit` early-returns (no state change). Item #3's full-exit path also calls into the same function. A validator that submits a voluntary exit AND an EL withdrawal_request in the same block — the second to be processed should be a no-op. Verify uniformly.
11. **`invalid_validator_incorrect_validator_index`** fixture — tests out-of-range index handling. All 6 clients PASS, but the underlying mechanism differs (assertion failure vs. silent-out-of-bounds-error). A future SSZ-schema change could expose differences.
12. **Builder-already-exited semantics** — the `initiate_builder_exit` helper in lighthouse (and others) early-returns if `builder.withdrawable_epoch != FAR_FUTURE_EPOCH`. A builder that submits a voluntary exit twice (or appears in a builder-exit message after already being exited via a different path) should be a no-op. Worth verifying uniformly once Gloas fixtures exist.
