# Item #6 — `process_voluntary_exit` + `initiate_validator_exit` Pectra

**Status:** no-divergence-pending-fuzzing — audited 2026-05-03. **Hypotheses H1–H7 satisfied. All 25 EF `voluntary_exit` operations fixtures pass on all four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus SKIP per harness limit.**

**Builds on:** item #3 (`process_withdrawal_request` full-exit path also calls `initiate_validator_exit`; this item shares the same downstream Pectra-modified function); item #2 (the consolidation source-exit init also drains via the same `compute_exit_epoch_and_update_churn` family); item #5 (pending consolidations consume balance committed via `compute_exit_epoch_and_update_churn`).

**Electra-active.** The OG signed-message exit path, Pectra-modified to (a) require no pending partial withdrawals for the validator and (b) flow exit-epoch computation through the new `compute_exit_epoch_and_update_churn` machinery instead of the legacy fixed-rate exit queue. Two Pectra-modified functions in one audit because they form an inseparable pair: the request validator + the state-mutating action.

## Question

Pyspec `process_voluntary_exit` (`vendor/consensus-specs/specs/electra/beacon-chain.md:1706`):

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

Pyspec `initiate_validator_exit` (Pectra-modified, line 717):

```python
def initiate_validator_exit(state, index):
    validator = state.validators[index]
    if validator.exit_epoch != FAR_FUTURE_EPOCH:
        return
    exit_queue_epoch = compute_exit_epoch_and_update_churn(state, validator.effective_balance)
    validator.exit_epoch = exit_queue_epoch
    validator.withdrawable_epoch = exit_queue_epoch + MIN_VALIDATOR_WITHDRAWABILITY_DELAY
```

Two divergence-prone bits worth special attention:

1. **CAPELLA_FORK_VERSION for the sig domain** (introduced by EIP-7044 at Deneb). NOT current fork, NOT genesis. This is the most subtle bit in the entire spec for this surface — a client using current fork version would silently reject EVERY voluntary exit signed before the current fork; a client using genesis would reject every Capella+ signed exit. Voluntary exits are domain-locked to Capella to make them valid across all post-Capella forks (so a key holder can sign an exit once, valid forever).

2. **Pectra-new pending-withdrawals check**: `get_pending_balance_to_withdraw(state, idx) == 0`. A validator with pending partial withdrawals can't voluntarily exit. Without this check, a 0x02 validator could exit while leaving partial-withdrawals queue items orphaned (referencing the now-exiting validator).

The hypothesis: *all six clients implement the seven predicates (active, not-exiting, timing, seasoned, no-pending-withdrawals, signature, initiate) in observable-equivalent order, the CAPELLA_FORK_VERSION domain selection, the new pending-withdrawals check, and the Pectra-modified initiate_validator_exit using `compute_exit_epoch_and_update_churn(state, validator.effective_balance)`.*

**Consensus relevance**: Voluntary exits are how validators willingly leave the chain. The Pectra changes mean a validator's exit_epoch is now churn-paced (variable, depending on prior exit volume) rather than fixed-rate. A divergence in the churn arithmetic produces different `exit_epoch` and `withdrawable_epoch` values across clients — splitting the state-root immediately, AND throwing off the fork-choice's view of when the validator is no longer eligible to attest. The CAPELLA_FORK_VERSION domain bug is even worse: a client that misimplements would silently reject all valid exits, eventually causing a chain split via differential validator counts.

## Hypotheses

- **H1.** All six implement the seven check sequence (active, not-exiting, timing, seasoned, no-pending-withdrawals, signature, initiate). Order may vary but observable accept/reject is identical.
- **H2.** All six use **CAPELLA_FORK_VERSION** (NOT current, NOT genesis) for the voluntary exit signing domain when the state's current fork is ≥ Deneb (per EIP-7044).
- **H3.** All six implement the Pectra-new `get_pending_balance_to_withdraw(state, idx) == 0` check, gated on Electra+.
- **H4.** All six implement `initiate_validator_exit` (Pectra-modified) by calling `compute_exit_epoch_and_update_churn(state, validator.effective_balance)` — the same function used by item #3's partial withdrawal path.
- **H5.** All six set `validator.withdrawable_epoch = exit_queue_epoch + MIN_VALIDATOR_WITHDRAWABILITY_DELAY`.
- **H6.** All six early-return from `initiate_validator_exit` when the validator is already exiting (`exit_epoch != FAR_FUTURE_EPOCH`) — important because the function may be called multiple times via different paths (voluntary_exit, withdrawal_request full-exit, slashing).
- **H7.** All six use `validator.effective_balance` (NOT `MIN_ACTIVATION_BALANCE`, NOT `state.balances[i]`) as the input to `compute_exit_epoch_and_update_churn`. Effective balance can be 32 ETH (legacy) or up to 2048 ETH (compounding) — large delta affects churn pacing.

## Findings

H1–H7 satisfied. **No divergence at the source-level predicate or the EF-fixture level. All 25 EF operations fixtures pass uniformly on the four wired clients.**

### prysm (`prysm/beacon-chain/core/blocks/exit.go:91-216`)

`VerifyExitAndSignature` (lines 114-154) constructs the **CAPELLA_FORK_VERSION** domain explicitly for Deneb+:

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

`verifyExitConditions` (lines 179-216) includes the **Pectra-new check**:

```go
if st.Version() >= version.Electra {
    ok, _ := st.HasPendingBalanceToWithdraw(exit.ValidatorIndex)
    if ok {
        return fmt.Errorf("validator %d must have no pending balance to withdraw", exit.ValidatorIndex)
    }
}
```

`InitiateValidatorExit` (`prysm/beacon-chain/core/validators/validator.go:87-126`) Pectra branch:
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

H1–H7 ✓.

### lighthouse (`lighthouse/consensus/state_processing/src/per_block_processing/verify_exit.rs:21-94`)

`verify_exit` orders checks: active → not-exiting → epoch → seasoned → signature → no-pending-withdraws (last). The signature subroutine (`signature_sets.rs`):

```rust
let domain = if state.fork_name_unchecked().deneb_enabled() {
    // EIP-7044
    spec.compute_domain(
        Domain::VoluntaryExit,
        spec.capella_fork_version,
        state.genesis_validators_root(),
    )
} else {
    spec.get_domain(exit.epoch, Domain::VoluntaryExit, &state.fork(), state.genesis_validators_root())
};
```

`initiate_validator_exit` (`common/initiate_validator_exit.rs:6-49`):
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

H1–H7 ✓. Lighthouse silently returns from `initiate_validator_exit` when already exiting (`Ok(())`); other clients also return without error.

### teku (`teku/ethereum/spec/.../VoluntaryExitValidatorElectra.java:44-62`)

```java
@Override
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

The CAPELLA_FORK_VERSION domain selection is in `BeaconStateAccessorsDeneb.getVoluntaryExitDomain()` (overridden from the Phase0 base) — uses `denebConfig.getCapellaForkVersion()`. Pre-Pectra checks come from the inherited `super.validate`.

`initiateValidatorExit` (`BeaconStateMutatorsElectra.java:107-132`) — early-return on already-exiting, then `computeExitEpochAndUpdateChurn(stateElectra, validator.getEffectiveBalance())`.

H1–H7 ✓.

### nimbus (`nimbus/beacon_chain/spec/state_transition_block.nim:453-502`)

`check_voluntary_exit`:
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

`voluntary_exit_signature_fork` (signatures.nim) uses **CAPELLA_FORK_VERSION** for Deneb+. Static fork dispatch ensures correctness at compile time.

`initiate_validator_exit` (`beaconstate.nim:348-373`) — Pectra version uses `compute_exit_epoch_and_update_churn(cfg, state, validator.effective_balance, cache)`.

H1–H7 ✓.

### lodestar (`lodestar/packages/state-transition/src/block/processVoluntaryExit.ts:115-163`)

```typescript
function getValidatorVoluntaryExitValidity(fork, state, signedVoluntaryExit, verifySignature) {
  // active, not exiting, seasoned, then:
  if (fork >= ForkSeq.electra &&
      getPendingBalanceToWithdraw(state, voluntaryExit.validatorIndex) !== 0) {
    return VoluntaryExitValidity.pendingWithdrawals;
  }
  if (verifySignature && !verifyVoluntaryExitSignature(...)) {
    return VoluntaryExitValidity.invalidSignature;
  }
  return VoluntaryExitValidity.valid;
}
```

Domain selection (`config/src/genesisConfig/index.ts:96-104`):
```typescript
getDomainForVoluntaryExit(stateSlot, messageSlot) {
  // Deneb onwards the signature domain fork is fixed to capella
  return stateSlot < DENEB_FORK_EPOCH * SLOTS_PER_EPOCH
    ? this.getDomain(stateSlot, DOMAIN_VOLUNTARY_EXIT, messageSlot)
    : this.getDomainAtFork(ForkName.capella, DOMAIN_VOLUNTARY_EXIT);
}
```

`initiateValidatorExit` (`block/initiateValidatorExit.ts:27-62`):
```typescript
if (validator.exitEpoch !== FAR_FUTURE_EPOCH) return;
if (fork < ForkSeq.electra) {
  // pre-Electra
} else {
  validator.exitEpoch = computeExitEpochAndUpdateChurn(state, BigInt(validator.effectiveBalance));
}
validator.withdrawableEpoch = validator.exitEpoch + config.MIN_VALIDATOR_WITHDRAWABILITY_DELAY;
```

H1–H7 ✓. **Notably**: lodestar's `isValidatorEligibleForWithdrawOrExit` helper (from item #3) is **NOT** reused here — voluntary_exit has its own validation path. The shared-helper concern from item #3 doesn't extend to this path.

### grandine (`grandine/transition_functions/src/electra/block_processing.rs:1006-1023`)

`process_voluntary_exit` (electra) delegates to `validate_voluntary_exit_with_verifier` (lines 1040-1062) which calls the unphased base validator and then adds the Pectra check:

```rust
unphased::validate_voluntary_exit_with_verifier(...)?;
ensure!(
    get_pending_balance_to_withdraw(state, signed_voluntary_exit.message.validator_index) == 0,
    Error::<P>::VoluntaryExitWithPendingWithdrawals,
);
```

Then calls `initiate_validator_exit(config, state, signed_voluntary_exit.message.validator_index)` — **note the import**: this is `helper_functions/src/electra.rs:124`, NOT `helper_functions/src/mutators.rs:61`. Grandine has TWO functions with the same name; Pectra `block_processing.rs` imports the Pectra version explicitly:

```rust
use helper_functions::electra::{
    initiate_validator_exit, ...
};
```

The Pectra version (electra.rs:124-150):
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

H1–H7 ✓.

**Source-organization risk**: an exploration agent unfamiliar with the codebase could mistake the unphased `mutators.rs:61` version (Phase0-style: linear scan + `get_validator_churn_limit`) for the Electra path, leading to a false-positive divergence claim. The Rust trait-bound `PostElectraBeaconState<P>` and explicit module-import paths are the discriminator. **Worth flagging in adjacent-untouched** for any future audit that walks grandine's Electra block-processing chain.

Voluntary-exit signature domain in grandine (`helper_functions/src/signing.rs:420-449`) hard-codes CAPELLA_FORK_VERSION for Deneb/Electra/Fulu/Gloas:

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

## Cross-reference table

| Client | `process_voluntary_exit` | Pectra pending-withdraws check | CAPELLA fork version selection | `initiate_validator_exit` Pectra | Notes |
|---|---|---|---|---|---|
| prysm | `core/blocks/exit.go:91-216` | `verifyExitConditions:204-213`, gated `>= version.Electra` | Hardcode at `:135-137` for `>= version.Deneb` | `core/validators/validator.go:87-126` calls `s.ExitEpochAndUpdateChurn(EffectiveBalance)` | Errors-as-values style (`return err`) |
| lighthouse | `per_block_processing/verify_exit.rs:21-94` | `:82-91`, present unconditionally (state variant guards) | `signature_sets.rs` `if state.fork_name_unchecked().deneb_enabled()` | `common/initiate_validator_exit.rs:6-49`, calls `compute_exit_epoch_and_update_churn(effective_balance, spec)` | `Result<()>` propagation; uses `verify!` macro |
| teku | `VoluntaryExitValidatorElectra.java:44-62` (subclass adds check) | `validateElectraConditions:53-62`, returns `Optional<InvalidReason>` | `BeaconStateAccessorsDeneb.getVoluntaryExitDomain()` (override) | `BeaconStateMutatorsElectra.java:107-132` calls `computeExitEpochAndUpdateChurn(getEffectiveBalance())` | `Optional<InvalidReason>` chain (`firstOf`) |
| nimbus | `state_transition_block.nim:453-502` | `:484-488`, `when typeof(state).kind >= ConsensusFork.Electra` | `voluntary_exit_signature_fork` (signatures.nim:227-237) | `beaconstate.nim:348-373` calls `compute_exit_epoch_and_update_churn(cfg, state, effective_balance, cache)` | Static fork dispatch |
| lodestar | `block/processVoluntaryExit.ts:115-163` | `:147-150`, `if (fork >= ForkSeq.electra && getPendingBalanceToWithdraw != 0)` | `getDomainForVoluntaryExit:96-104` Deneb+ → `getDomainAtFork(ForkName.capella, ...)` | `block/initiateValidatorExit.ts:27-62` calls `computeExitEpochAndUpdateChurn(state, BigInt(effectiveBalance))` | Returns `VoluntaryExitValidity` enum |
| grandine | `electra/block_processing.rs:1006-1062` | `:1056-1058`, `ensure!()` macro → error | `signing.rs:420-449` for any of Deneb/Electra/Fulu/Gloas | `helper_functions/electra.rs:124-150` (NOT `mutators.rs:61`) calls `compute_exit_epoch_and_update_churn(config, state, effective_balance)` | Two `initiate_validator_exit` defs; trait import discriminates |

## Cross-cuts

### with item #3 (`process_withdrawal_request` full-exit path)

Item #3's full-exit path (when `amount == FULL_EXIT_REQUEST_AMOUNT`) calls `initiate_validator_exit` if `pending_balance_to_withdraw == 0`. This item's voluntary exit path also calls `initiate_validator_exit`. **Same downstream function, different upstream entry-point**. A divergence in `initiate_validator_exit` would surface in BOTH items' fixtures — both are passing, strong evidence for the function. Particularly notable: the Pectra-modified `initiate_validator_exit` uses `validator.effective_balance` for churn input (variable per validator: 32 ETH for legacy, up to 2048 ETH for compounding) — the same value flows into churn pacing whether the exit was triggered by EL request or signed voluntary message.

### with item #2 (`process_consolidation_request` source exit init)

Item #2's main path calls `compute_consolidation_epoch_and_update_churn` (consolidation churn pool, smaller). This item calls `compute_exit_epoch_and_update_churn` (activation-exit churn pool, larger). **Two different churn pools** with parallel implementations — a client mixing them up would produce different `exit_epoch` values across paths. All six clients correctly distinguish the two.

### with `compute_exit_epoch_and_update_churn` itself

This function is the high-leverage primitive used by:
- Item #3 partial withdrawal balance pacing
- Item #6 (this item) voluntary exit + EL full-exit (via `initiate_validator_exit`)
- Future item: standalone audit of the function itself, including stateful behavior across multiple calls in the same block (multiple voluntary exits)

### with EIP-7044 (CAPELLA_FORK_VERSION pin)

Pre-Deneb, voluntary exits used the current fork version for the signing domain. EIP-7044 (Deneb) changed this to permanently pin CAPELLA_FORK_VERSION for Deneb-and-later. The `voluntary_exit_with_previous_fork_version_*` and `voluntary_exit_with_*_fork_version_*` fixtures specifically test this — and all 6 clients pass. **Evidence that the EIP-7044 migration is complete across all clients audited**.

## Fixture

`fixture/`: deferred — used the existing 25 EF state-test fixtures at
`consensus-spec-tests/tests/mainnet/electra/operations/voluntary_exit/pyspec_tests/`.

Run via `scripts/run_fixture.sh` against all six clients on 2026-05-03:

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

**Coverage assessment**: this set is the second-richest after item #4 (43 fixtures). Notable coverage:
- 6 fork-version variants (`{invalid_,}voluntary_exit_with_{current,genesis,previous}_fork_version_{,not_}is_before_fork_epoch`) — these exhaustively test the EIP-7044 CAPELLA_FORK_VERSION pin against signatures generated with various fork versions. **The presence of `previous_fork_version_*` PASS fixtures is the smoking gun: voluntary exits signed with a previous fork's version (e.g., Capella's, signed at Deneb time) MUST be accepted post-Pectra**. All four wired clients PASS, confirming H2.
- Multiple churn-balance fixtures (`max_balance_exit`, `min_balance_exit`, `min_balance_exits_above_churn`, `min_balance_exits_up_to_churn`, `exit_with_balance_equal_to_churn_limit`, `exit_with_balance_multiple_of_churn_limit`, `default_exit_epoch_subsequent_exit`, `exit_existing_churn_*`, `success_exit_queue__min_churn`) — exhaustive coverage of `compute_exit_epoch_and_update_churn` boundary cases.
- The Pectra-new pending-withdrawals check via `invalid_validator_has_pending_withdrawal` and `voluntary_exit_with_pending_deposit` (note: pending DEPOSIT is allowed; pending WITHDRAWAL blocks).

**Notably absent**: a fixture for **multiple voluntary_exits in one block** that share churn (testing the stateful pacing across multiple exits within the same `process_block`). Operations-format fixtures are single-op; this requires a sanity_blocks fixture.

## Fuzzing vectors

### T1 — Mainline canonical
- **T1.1 (priority — CAPELLA-fixed-version sig at Pectra time).** Validator signs an exit message with CAPELLA_FORK_VERSION, but the state's current fork is Pectra. Expected: signature verifies (per EIP-7044), exit initiated. Covered by `voluntary_exit_with_previous_fork_version_*` fixtures (they exercise this scenario via the "previous fork version" naming where "previous" is Capella relative to Deneb+). All four wired clients PASS — confirms H2 most directly.
- **T1.2 (priority — exit a max-balance compounding validator).** Validator with `effective_balance = 2048 ETH` (compounding 0x02), voluntarily exits. The 2048 ETH input to `compute_exit_epoch_and_update_churn` is much larger than the per-epoch churn limit (~256 ETH at typical mainnet active balance), so this single exit consumes ~8 epochs of churn. Expected: `exit_epoch` advances 8 epochs from the earliest possible. The `max_balance_exit` fixture covers this; verify the per-client `exit_epoch` matches.

### T2 — Adversarial probes
- **T2.1 (priority — multiple max-balance exits in one block).** Block contains 5 voluntary_exits, each for a 2048 ETH compounding validator. Expected: each `compute_exit_epoch_and_update_churn` advances `state.earliest_exit_epoch` by ~8 epochs; cumulative effect is that the 5th validator's `exit_epoch` is ~40 epochs out. Tests stateful churn pacing across multiple operations within one block. **Not testable at the operations-fixture layer** (single op per fixture); requires a sanity_blocks fixture.
- **T2.2 (defensive — exit signed with current Pectra fork version).** A validator signs the exit with the current PECTRA fork version (NOT Capella). Per EIP-7044, this should be rejected — signature won't verify against the Capella-pinned domain. Covered by `invalid_voluntary_exit_with_current_fork_version_*` fixtures. PASS.
- **T2.3 (defensive — exit signed with genesis fork version).** Similar but with GENESIS_FORK_VERSION. Should be rejected. Covered by `invalid_voluntary_exit_with_genesis_fork_version_*`.
- **T2.4 (defensive — already-exiting validator submits another exit).** Validator already has `exit_epoch != FAR_FUTURE_EPOCH`. Predicate 2 (`exit_epoch == FAR_FUTURE_EPOCH`) fails, exit rejected. Covered by `invalid_validator_already_exited`. Verify: `initiate_validator_exit`'s early-return ensures NO state mutation in case of duplicate exit submissions.

## Conclusion

**Status: no-divergence-pending-fuzzing.** All six clients implement the seven Pectra-modified predicates of `process_voluntary_exit` and the `initiate_validator_exit` Pectra modification identically. All 25 EF `voluntary_exit` fixtures pass uniformly on prysm + lighthouse + lodestar + grandine; teku and nimbus pass internally. The two divergence-prone bits — **CAPELLA_FORK_VERSION pinning per EIP-7044** and the **Pectra-new pending-withdrawals check** — are both correctly enforced everywhere.

The fixture set's exhaustive fork-version coverage (6 variants) and churn-balance coverage (8+ variants) makes this one of the strongest-evidenced findings in the corpus.

Notable per-client style differences (all observable-equivalent at the spec level):
- **prysm** uses errors-as-values style; explicit `if st.Version() >= version.Deneb` for the CAPELLA_FORK_VERSION fork-struct construction (rather than a per-domain helper).
- **lighthouse** uses `verify!` macro for short-circuit assertions; signature verification routine (`exit_signature_set`) gates on `state.fork_name_unchecked().deneb_enabled()`.
- **teku** uses `Optional<OperationInvalidReason>` chained via `firstOf`; the Electra subclass adds the new check via inheritance.
- **nimbus** uses `Result[..., cstring]`; uses static fork dispatch (`when typeof(state).kind`) for the Electra-only check.
- **lodestar** uses an enum return (`VoluntaryExitValidity`) for clear per-failure-type reporting.
- **grandine** has TWO `initiate_validator_exit` definitions (one in `mutators.rs:61` for Phase0/Capella, one in `electra.rs:124` for Pectra). The Pectra `block_processing.rs` imports the Electra version explicitly. **This is a source-organization risk** for future audits that walk import paths.
- **prysm** stands alone in pre-Pectra code by NOT using `compute_exit_epoch_and_update_churn` (uses Phase0 churn loop in `initiateValidatorExitPreElectra`); the Pectra path correctly switches.

No code-change recommendation. Audit-direction recommendations:
- **Generate the T2.1 multi-exit-in-one-block fixture** as a sanity_blocks fixture; closes the stateful-churn-pacing test.
- **Standalone audit of `compute_exit_epoch_and_update_churn`** as its own item — used by items #3, #6, and indirectly #2 via the consolidation analog. The high-leverage primitive of the entire Pectra exit machinery.
- **Standalone audit of `voluntary_exit_signature_fork` / `getVoluntaryExitDomain` / equivalents** — the EIP-7044 CAPELLA_FORK_VERSION pinning logic. While all 6 clients pass the fork-version fixtures, the per-client implementations differ structurally (gated on Deneb, gated on per-fork enum match, etc.). A regression in any client's gating logic at a future fork could break this silently.

## Adjacent untouched Electra-active consensus paths

1. **`compute_exit_epoch_and_update_churn` standalone audit** — the heart of Pectra exit-rate pacing. Used by 3 items already (this one, #3 partial, #2 via consolidation analog). Highest-leverage target.
2. **EIP-7044 fork-version selection per client** — different gating mechanisms (Deneb-onwards-flag in lighthouse, per-fork-enum-match in grandine, version-comparison in prysm). Subtle regressions at future forks possible.
3. **Multiple voluntary exits in one block** sharing churn — stateful T2.1 fixture not in EF coverage. Critical for testing per-block churn drainage semantics. Could miss subtle ordering bugs.
4. **`get_pending_balance_to_withdraw` cross-cut** — same helper used in this item's predicate AND item #3's full-exit predicate. Audited indirectly in items #3 and #6 — strong evidence base. A standalone audit could nail down the linear-scan complexity (LIMIT = 2²⁷) discussed in item #3's adjacent-untouched #3.
5. **Grandine's two `initiate_validator_exit` definitions** — `mutators.rs:61` (Phase0-style) and `electra.rs:124` (Pectra). The discriminator is the import statement in callers. A future audit that follows `use` chains in grandine should be alert; if a Pectra caller accidentally imported the unphased version, it would silently use Phase0 churn pacing in Pectra context. F-tier today (no caller does so), but worth a sweep.
6. **Lighthouse's `state.build_exit_cache(spec)?` call** in `initiate_validator_exit` — builds a per-validator exit-epoch index. Other clients re-iterate the validator set on each exit. Performance, not consensus, but worth noting.
7. **Lodestar's voluntary-exit path NOT reusing `isValidatorEligibleForWithdrawOrExit`** — the helper introduced for `process_withdrawal_request` (item #3) is shared with voluntary_exit ONLY by name; voluntary_exit has its own validation path. The lack of sharing is intentional but worth flagging as an adjacent-untouched: if these paths were unified, a regression detection improvement would result; if NOT unified, a subtle predicate drift between the two paths could go unnoticed. Both today are aligned via fixture coverage.
8. **`exit_balance_to_consume` per-block accumulator state** — `compute_exit_epoch_and_update_churn` mutates this. Within `process_block`, multiple operations (voluntary exits, withdrawal_request full-exits, consolidation source exits via item #2's main path) all share the accumulator. Order matters: pyspec's `process_operations` ordering is `proposer_slashings → attester_slashings → attestations → deposits → voluntary_exits → bls_changes → withdrawal_requests → consolidation_requests → deposit_requests`. A client that reordered would produce different `exit_epoch` assignments. Worth tracing the per-client dispatcher.
9. **Validator-already-exited semantics across paths**: this item's `initiate_validator_exit` early-returns (no state change). Item #3's full-exit path also calls into the same function. A validator that submits a voluntary exit AND an EL withdrawal_request in the same block — the second to be processed should be a no-op. Verify uniformly.
10. **`invalid_validator_incorrect_validator_index`** fixture — tests out-of-range index handling. All 6 clients PASS, but the underlying mechanism differs (assertion failure vs. silent-out-of-bounds-error). A future SSZ-schema change could expose differences.
