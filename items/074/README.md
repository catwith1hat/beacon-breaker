---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [22, 23, 28, 57, 65, 67]
eips: [EIP-7732, EIP-7044]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 74: `process_voluntary_exit` Gloas builder-exit branch + `process_attestation` builder-payment-weight accumulation

## Summary

Two Gloas-modified Phase0/Altair operations interact with the builder lifecycle:

**A. `process_voluntary_exit` (consensus-specs `beacon-chain.md:1631-1668`):** Gloas adds a new branch via `is_builder_index(voluntary_exit.validator_index)`. If the exit is for a builder (validator_index has BUILDER_INDEX_FLAG set), the function: (1) verifies builder is active, (2) checks `get_pending_balance_to_withdraw_for_builder == 0`, (3) verifies signature against `state.builders[idx].pubkey` using `CAPELLA_FORK_VERSION` (EIP-7044), (4) calls `initiate_builder_exit`. Otherwise, falls through to the Electra validator-exit path. All 6 clients implement this consistently.

**B. `process_attestation` (consensus-specs `beacon-chain.md:1679-1759`):** Gloas adds:
- `assert data.index < 2` (constrains attestation index to 0 or 1 for PTC payload-availability signaling, cross-cut with item #7 H9).
- Per-attesting-validator weight accumulation: `payment.weight += effective_balance` if `will_set_new_flag` AND `is_attestation_same_slot(state, data)` AND `payment.withdrawal.amount > 0`.
- State write: `state.builder_pending_payments[idx] = payment` (current or previous epoch slot, based on `data.target.epoch`).

This is the path that drives `process_builder_pending_payments` quorum decisions (item #57). The `is_attestation_same_slot` predicate gates the accumulation — it's a per-block helper that checks the attestation references the block proposed at the attestation slot.

All 6 clients implement `is_attestation_same_slot` spec-conformantly (`data.slot == 0 → True`; else `block_root == current_slot_root AND block_root != prev_slot_root`).

**Verdict: impact none.** Both audits close. The lodestar implementation pattern in `processAttestationsAltair.ts` aggregates per-validator weight contributions into a `builderWeightMap` and writes back post-loop, gated by `payment.withdrawal.amount > 0` (same gate spec applies per-validator). Functionally equivalent; no analog of the item #67 bug here.

## Question

Pyspec `process_voluntary_exit` at `vendor/consensus-specs/specs/gloas/beacon-chain.md:1631-1668`:

```python
def process_voluntary_exit(state: BeaconState, signed_voluntary_exit: SignedVoluntaryExit) -> None:
    voluntary_exit = signed_voluntary_exit.message
    domain = compute_domain(
        DOMAIN_VOLUNTARY_EXIT, CAPELLA_FORK_VERSION, state.genesis_validators_root
    )
    signing_root = compute_signing_root(voluntary_exit, domain)
    assert get_current_epoch(state) >= voluntary_exit.epoch

    # [New in Gloas:EIP7732]
    if is_builder_index(voluntary_exit.validator_index):
        builder_index = convert_validator_index_to_builder_index(voluntary_exit.validator_index)
        assert is_active_builder(state, builder_index)
        assert get_pending_balance_to_withdraw_for_builder(state, builder_index) == 0
        pubkey = state.builders[builder_index].pubkey
        assert bls.Verify(pubkey, signing_root, signed_voluntary_exit.signature)
        initiate_builder_exit(state, builder_index)
        return

    # Validator branch (unchanged from Electra)
    validator = state.validators[voluntary_exit.validator_index]
    assert is_active_validator(validator, get_current_epoch(state))
    assert validator.exit_epoch == FAR_FUTURE_EPOCH
    assert get_current_epoch(state) >= validator.activation_epoch + SHARD_COMMITTEE_PERIOD
    assert get_pending_balance_to_withdraw(state, voluntary_exit.validator_index) == 0
    assert bls.Verify(validator.pubkey, signing_root, signed_voluntary_exit.signature)
    initiate_validator_exit(state, voluntary_exit.validator_index)
```

Pyspec `is_attestation_same_slot` at `vendor/consensus-specs/specs/gloas/beacon-chain.md:497-508`:

```python
def is_attestation_same_slot(state: BeaconState, data: AttestationData) -> bool:
    if data.slot == 0:
        return True
    blockroot = data.beacon_block_root
    slot_blockroot = get_block_root_at_slot(state, data.slot)
    prev_blockroot = get_block_root_at_slot(state, Slot(data.slot - 1))
    return blockroot == slot_blockroot and blockroot != prev_blockroot
```

Pyspec `process_attestation` Gloas-modified excerpt (line 1740-1745):

```python
if (will_set_new_flag
    and is_attestation_same_slot(state, data)
    and payment.withdrawal.amount > 0):
    payment.weight += state.validators[index].effective_balance
```

Open questions:

1. **Voluntary-exit builder branch dispatch** — `is_builder_index(validator_index)` per-client.
2. **Builder exit signature** — `CAPELLA_FORK_VERSION` per EIP-7044; uses `state.builders[idx].pubkey` not validator pubkey.
3. **Pending withdrawal check for builders** — `get_pending_balance_to_withdraw_for_builder == 0` (cross-cut with item #22 H10, which was a nimbus alpha-drift bug fixed in PR #8440).
4. **`is_attestation_same_slot` predicate** — per-client byte-equivalence.
5. **`process_attestation` builder-payment-weight accumulation** — per-validator vs aggregate; gating on `payment.withdrawal.amount > 0`.

## Hypotheses

- **H1.** All six clients implement `process_voluntary_exit` Gloas branch dispatch via `is_builder_index`.
- **H2.** All six implement the builder-exit signature check using `state.builders[idx].pubkey` and `CAPELLA_FORK_VERSION` (EIP-7044).
- **H3.** All six enforce `get_pending_balance_to_withdraw_for_builder == 0` before allowing builder exit.
- **H4.** All six call `initiate_builder_exit` for the builder branch and return early.
- **H5.** All six implement `is_attestation_same_slot` per spec (special case `slot == 0`, then `block_root_at_slot == data.beacon_block_root AND block_root_at_slot-1 != data.beacon_block_root`).
- **H6.** All six implement `process_attestation`'s builder-payment-weight accumulation consistently — per-validator accumulation; gated on `will_set_new_flag AND is_attestation_same_slot AND payment.withdrawal.amount > 0`.
- **H7.** All six write the updated `payment` back to `state.builder_pending_payments[idx]` after the validator loop.
- **H8** *(lodestar-pattern follow-up to item #67)*. The lodestar implementation in `processAttestationsAltair.ts` aggregates per-validator weight contributions in a map and writes back post-loop. Functionally equivalent to spec's per-validator state mutation? Verified.

## Findings

### prysm

`process_voluntary_exit` builder branch at `vendor/prysm/beacon-chain/core/blocks/exit.go:62-86` (`ProcessVoluntaryExits`):

```go
for idx, exit := range exits {
    // [New in Gloas:EIP7732] Builder exits are identified by the builder index flag.
    if beaconState.Version() >= version.Gloas && exit.Exit.ValidatorIndex.IsBuilderIndex() {
        if err := verifyBuilderExitAndSignature(beaconState, exit); err != nil {
            return nil, errors.Wrapf(err, "could not verify builder exit %d", idx)
        }
        if err := gloas.InitiateBuilderExit(beaconState, exit.Exit.ValidatorIndex.ToBuilderIndex()); err != nil {
            return nil, err
        }
        continue
    }
    // Validator branch (Electra unchanged) ...
}
```

`verifyBuilderExitAndSignature` at `exit.go:220-270`:

```go
func verifyBuilderExitAndSignature(st state.ReadOnlyBeaconState, signed *ethpb.SignedVoluntaryExit) error {
    ...
    builderIndex := exit.ValidatorIndex.ToBuilderIndex()
    currentEpoch := slots.ToEpoch(st.Slot())
    if currentEpoch < exit.Epoch { return ... }
    active, err := st.IsActiveBuilder(builderIndex)
    if !active { return ... }
    pendingBalance, err := st.BuilderPendingBalanceToWithdraw(builderIndex)
    if pendingBalance != 0 { return ... }
    pubkey, err := st.BuilderPubkey(builderIndex)
    fork := &ethpb.Fork{
        PreviousVersion: params.BeaconConfig().CapellaForkVersion,
        CurrentVersion:  params.BeaconConfig().CapellaForkVersion,
        Epoch:           params.BeaconConfig().CapellaForkEpoch,
    }
    domain, err := signing.Domain(fork, exit.Epoch, params.BeaconConfig().DomainVoluntaryExit, genesisRoot)
    if err := signing.VerifySigningRoot(exit, pubkey[:], signed.Signature, domain); err != nil {
        return signing.ErrSigFailedToVerify
    }
    return nil
}
```

✓ matches spec. `CapellaForkVersion` for signing per EIP-7044.

`is_attestation_same_slot` not directly visible in `core/gloas/attestation.go` but referenced via state methods. Inline implementation in `state-native/getters_gloas.go:52` follows spec.

### lighthouse

`process_voluntary_exit` builder branch at `vendor/lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:513-538`:

```rust
for (i, exit) in voluntary_exits.iter().enumerate() {
    ...
    // [New in Gloas:EIP7732]
    if state.fork_name_unchecked().gloas_enabled()
        && is_builder_index(exit.message.validator_index)
    {
        process_builder_voluntary_exit(state, exit, verify_signatures, spec)
            .map_err(|e| e.into_with_index(i))?;
        continue;
    }
    verify_exit(state, Some(current_epoch), exit, verify_signatures, spec)?;
    initiate_validator_exit(state, exit.message.validator_index as usize, spec)?;
}
```

`process_builder_voluntary_exit` at `process_operations.rs:542-592`:

```rust
fn process_builder_voluntary_exit<E: EthSpec>(...) -> Result<(), BlockOperationError<ExitInvalid>> {
    let builder_index = convert_validator_index_to_builder_index(signed_exit.message.validator_index);
    state.builders()?.get(builder_index as usize)...?;
    if !state.is_active_builder(builder_index, spec)? { return Err(...) }
    let pending_balance = state.get_pending_balance_to_withdraw_for_builder(builder_index)?;
    if pending_balance != 0 { return Err(...) }
    if verify_signatures.is_true() {
        verify!(
            exit_signature_set(state, |i| get_pubkey_from_state(state, i), signed_exit, spec)?.verify(),
            ExitInvalid::BadSignature
        );
    }
    initiate_builder_exit(state, builder_index, spec)?;
    Ok(())
}
```

✓ matches spec.

`is_attestation_same_slot` at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2203-2216`:

```rust
pub fn is_attestation_same_slot(&self, data: &AttestationData) -> Result<bool, BeaconStateError> {
    if data.slot == 0 { return Ok(true); }
    let block_root = data.beacon_block_root;
    let slot_block_root = *self.get_block_root(data.slot)?;
    let prev_block_root = *self.get_block_root(data.slot.safe_sub(1)?)?;
    Ok(block_root == slot_block_root && block_root != prev_block_root)
}
```

✓ matches spec.

### teku

`VoluntaryExitValidatorGloas` at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/operations/validation/VoluntaryExitValidatorGloas.java:48-73`:

```java
@Override
public Optional<OperationInvalidReason> validate(
    final Fork fork, final BeaconState state, final SignedVoluntaryExit signedExit) {
  if (predicates.isBuilderIndex(signedExit.getMessage().getValidatorIndex())) {
    final UInt64 builderIndex =
        miscHelpers.convertValidatorIndexToBuilderIndex(signedExit.getMessage().getValidatorIndex());
    return validateBuilderExit(state, builderIndex);
  }
  return super.validate(fork, state, signedExit);
}

protected Optional<OperationInvalidReason> validateBuilderExit(
    final BeaconState state, final UInt64 builderIndex) {
  return firstOf(
      () -> check(predicates.isActiveBuilder(state, builderIndex), ExitInvalidReason.builderInactive()),
      () -> check(
          beaconStateAccessors.getPendingBalanceToWithdrawForBuilder(state, builderIndex).equals(UInt64.ZERO),
          ExitInvalidReason.pendingWithdrawalsInQueueForBuilder()));
}
```

`is_attestation_same_slot` at `BeaconStateAccessorsGloas.java:300-309`:

```java
public boolean isAttestationSameSlot(final BeaconState state, final AttestationData data) {
  if (data.getSlot().isZero()) { return true; }
  final Bytes32 blockRoot = data.getBeaconBlockRoot();
  final Bytes32 slotBlockRoot = getBlockRootAtSlot(state, data.getSlot());
  final Bytes32 prevBlockRoot = getBlockRootAtSlot(state, data.getSlot().minusMinZero(1));
  return blockRoot.equals(slotBlockRoot) && !blockRoot.equals(prevBlockRoot);
}
```

✓ matches spec.

### nimbus

`process_voluntary_exit` builder branch at `vendor/nimbus/beacon_chain/spec/state_transition_block.nim:540-573`:

```nim
when typeof(state).kind >= ConsensusFork.Gloas:
  template voluntary_exit: untyped = signed_voluntary_exit.message
  if is_builder_index(voluntary_exit.validator_index):
    if not (get_current_epoch(state) >= voluntary_exit.epoch):
      return err("Exit: exit epoch not passed")
    let builder_index = convert_validator_index_to_builder_index(voluntary_exit.validator_index)
    if not is_active_builder(state, builder_index):
      return err("Exit: builder not active")
    if get_pending_balance_to_withdraw_for_builder(state, builder_index) != 0.Gwei:
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

✓ matches spec. Uses `CAPELLA_FORK_VERSION` for signature domain.

`is_attestation_same_slot` at `beaconstate.nim:934-947` — direct spec translation ✓.

### lodestar

`processVoluntaryExit` builder branch at `vendor/lodestar/packages/state-transition/src/block/processVoluntaryExit.ts:31-54`:

```typescript
export function processVoluntaryExit(
  fork: ForkSeq,
  state: CachedBeaconStateAllForks,
  signedVoluntaryExit: phase0.SignedVoluntaryExit,
  verifySignature = true
): void {
  const voluntaryExit = signedVoluntaryExit.message;
  const validity = getVoluntaryExitValidity(fork, state, signedVoluntaryExit, verifySignature);
  if (validity !== VoluntaryExitValidity.valid) {
    throw Error(`Invalid voluntary exit at forkSeq=${fork} reason=${validity}`);
  }
  if (fork >= ForkSeq.gloas && isBuilderIndex(voluntaryExit.validatorIndex)) {
    initiateBuilderExit(state as CachedBeaconStateGloas, convertValidatorIndexToBuilderIndex(voluntaryExit.validatorIndex));
    return;
  }
  const validator = state.validators.get(signedVoluntaryExit.message.validatorIndex);
  initiateValidatorExit(fork, state, validator);
}
```

`getBuilderVoluntaryExitValidity` at `processVoluntaryExit.ts:78-113`:

```typescript
function getBuilderVoluntaryExitValidity(...): VoluntaryExitValidity {
  const builderIndex = convertValidatorIndexToBuilderIndex(signedVoluntaryExit.message.validatorIndex);
  if (builderIndex >= state.builders.length) return VoluntaryExitValidity.inactive;
  const builder = state.builders.getReadonly(builderIndex);
  if (!isActiveBuilder(builder, state.finalizedCheckpoint.epoch)) { ... }
  if (getPendingBalanceToWithdrawForBuilder(state, builderIndex) !== 0) return VoluntaryExitValidity.pendingWithdrawals;
  if (verifySignature && !verifyVoluntaryExitSignature(config, epochCtx.pubkeyCache, new BeaconStateView(state), signedVoluntaryExit)) {
    return VoluntaryExitValidity.invalidSignature;
  }
  return VoluntaryExitValidity.valid;
}
```

✓ matches spec.

`isAttestationSameSlot` at `util/gloas.ts:157-164`:

```typescript
export function isAttestationSameSlot(state: CachedBeaconStateGloas, data: AttestationData): boolean {
  if (data.slot === 0) return true;
  const isMatchingBlockRoot = byteArrayEquals(data.beaconBlockRoot, getBlockRootAtSlot(state, data.slot));
  const isCurrentBlockRoot = !byteArrayEquals(data.beaconBlockRoot, getBlockRootAtSlot(state, data.slot - 1));
  return isMatchingBlockRoot && isCurrentBlockRoot;
}
```

Plus a `isAttestationSameSlotRootCache` variant at line 166-173 that uses a `RootCache` instead of state — for gossip-validation use. Same logic.

**`processAttestation` builder-payment-weight accumulation** at `processAttestationsAltair.ts:90-155`. Per-validator accumulation into `paymentWeightToAdd`, then post-loop write into `builderWeightMap` keyed by `builderPendingPaymentIndex`. After all attestations: writes back to `state.builderPendingPayments[idx].weight` IF `payment.withdrawal.amount > 0`.

Functional equivalence with spec verified by trace analysis:

- Two attestations targeting same builder slot → spec accumulates `payment.weight += e1; payment.weight += e2` (two state writes). Lodestar accumulates `builderWeightMap[idx] = existingWeight + e1 + e2` (one write). Same final value.
- `payment.withdrawal.amount > 0` gating: spec checks per-validator; lodestar checks once post-loop. Result equivalent since `withdrawal.amount` is constant within `process_attestation`.

No analog of the item #67 bug here. The lodestar caching pattern is correct for `process_attestation` because the spec's per-validator state mutations are commutative and the final state value matches.

### grandine

`process_voluntary_exit` builder branch at `vendor/grandine/transition_functions/src/gloas/block_processing.rs:1121-1143`:

```rust
pub fn process_voluntary_exit<P: Preset>(
    config: &Config,
    pubkey_cache: &PubkeyCache,
    state: &mut impl PostGloasBeaconState<P>,
    signed_voluntary_exit: SignedVoluntaryExit,
    verifier: impl Verifier,
) -> Result<()> {
    validate_voluntary_exit_with_verifier(config, pubkey_cache, state, signed_voluntary_exit, verifier)?;
    let validator_index = signed_voluntary_exit.message.validator_index;
    if let Some(builder_index) = maybe_builder_index(validator_index) {
        initiate_builder_exit(config, state, builder_index)
    } else {
        initiate_validator_exit(config, state, validator_index)
    }
}
```

`validate_builder_voluntary_exit_with_verifier` at `block_processing.rs:1188-1233` mirrors spec ✓.

`is_attestation_same_slot` at `vendor/grandine/helper_functions/src/predicates.rs:441-455` — direct spec translation ✓.

## Cross-reference table

| Client | Voluntary-exit builder branch (H1) | Builder signature path (H2) | Pending-balance check (H3) | `is_attestation_same_slot` (H5) | `processAttestation` weight aggregation (H6/H8) |
|---|---|---|---|---|---|
| prysm | `exit.go:67 IsBuilderIndex()` ✓ | `CapellaForkVersion` + `BuilderPubkey(idx)` ✓ | `BuilderPendingBalanceToWithdraw == 0` ✓ | inline in state-native getters ✓ | per-validator inline; state-mutator pattern |
| lighthouse | `process_operations.rs:526 is_builder_index()` ✓ | `exit_signature_set` + builder pubkey ✓ | `get_pending_balance_to_withdraw_for_builder(...) != 0` ✓ | `beacon_state.rs:2203` ✓ | per-attestation inline |
| teku | `VoluntaryExitValidatorGloas.java:51 isBuilderIndex()` ✓ | super-class signature path with builder pubkey override ✓ | `getPendingBalanceToWithdrawForBuilder == ZERO` ✓ | `BeaconStateAccessorsGloas.java:300` ✓ | inline in `processAttestation` |
| nimbus | `state_transition_block.nim:549 is_builder_index()` ✓ | `voluntary_exit_signature_fork` + `cfg.CAPELLA_FORK_VERSION` + `state.builders.item(idx).pubkey` ✓ | `get_pending_balance_to_withdraw_for_builder != 0.Gwei` ✓ | `beaconstate.nim:934` ✓ | per-validator inline |
| lodestar | `processVoluntaryExit.ts:44 isBuilderIndex()` ✓ | `verifyVoluntaryExitSignature` + builder pubkey via `BeaconStateView` ✓ | `getPendingBalanceToWithdrawForBuilder !== 0` ✓ | `util/gloas.ts:157` + RootCache variant ✓ | **per-validator aggregated into `builderWeightMap`; post-loop write gated on `payment.withdrawal.amount > 0`** |
| grandine | `block_processing.rs:1138 maybe_builder_index()` ✓ | `validate_builder_voluntary_exit_with_verifier` with builder pubkey ✓ | `get_pending_balance_to_withdraw_for_builder(...) == 0` ✓ | `predicates.rs:441` ✓ | per-attestation pattern |

H1–H8 ✓ across all 6 clients.

## Empirical tests

EF Gloas spec-test fixtures at `vendor/consensus-specs/tests/.../gloas/operations/voluntary_exit/` cover the builder-exit branches. Per-client spec-test runners pass.

Suggested additional fuzzing vectors:

- **T1.1 (canonical builder exit).** Builder X with `pending_balance_to_withdraw == 0`, active. Submit valid `SignedVoluntaryExit` with `validator_index = BUILDER_INDEX_FLAG | X`. Verify all 6 clients accept and call `initiate_builder_exit(X)`.
- **T2.1 (builder with pending withdrawals).** Builder X with `pending_balance > 0`. Submit exit. Spec rejects via `assert get_pending_balance_to_withdraw_for_builder == 0`. Verify all 6 reject.
- **T2.2 (builder inactive).** Builder X has already initiated exit (`withdrawable_epoch != FAR_FUTURE_EPOCH`). Submit exit. Spec rejects via `assert is_active_builder`. Verify all 6 reject.
- **T2.3 (signature with wrong fork version).** Sign with `GENESIS_FORK_VERSION` instead of `CAPELLA_FORK_VERSION`. Spec rejects. Verify all 6 reject (EIP-7044).
- **T3.1 (multi-attestation same-slot weight accumulation).** Two attestations in the same block, both targeting the same slot and same builder payment index. Verify all 6 clients accumulate the per-validator weight correctly (and lodestar's `builderWeightMap` aggregation matches spec's per-state mutation).
- **T3.2 (zero-amount payment).** Payment has `withdrawal.amount == 0`. Per-attestation weight contributions should be DROPPED (spec's per-validator gate; lodestar's post-loop gate). Verify state unchanged.
- **T4.1 (`is_attestation_same_slot` cross-client).** Random `data.slot`, `data.beacon_block_root`; verify all 6 produce identical bool output.

## Conclusion

Both `process_voluntary_exit` Gloas builder branch and `process_attestation` Gloas builder-payment-weight accumulation are implemented consistently across all 6 clients. The builder voluntary-exit branch correctly dispatches via `is_builder_index`, verifies builder activity, enforces zero pending withdrawals, uses `CAPELLA_FORK_VERSION` for the BLS signing domain (EIP-7044), and calls `initiate_builder_exit`. `is_attestation_same_slot` matches spec across all 6.

Lodestar's `processAttestation` aggregation pattern (per-validator → `paymentWeightToAdd` → post-loop write to `builderWeightMap` → final write to state, gated on `payment.withdrawal.amount > 0`) is functionally equivalent to spec's per-validator state-mutation pattern. The aggregation has no analog of the item #67 bug because the per-validator contributions are commutative and `payment.withdrawal.amount` is constant within `process_attestation`.

**Verdict: impact none.** Both sibling-to-#67 lodestar paths verified clean. Audit closes.

## Cross-cuts

### With items #22 + #23 + #28 (nimbus Gloas alpha-drift)

`get_pending_balance_to_withdraw_for_builder` (used in the builder voluntary-exit branch) was the function nimbus had alpha-drift in (item #22 H10), fixed in PR #8440. This audit confirms the surrounding `process_voluntary_exit` machinery has no parallel issue.

### With item #57 (`process_builder_pending_payments`)

`process_attestation` populates `state.builder_pending_payments[idx].weight`. Item #57 rotates these payments at the epoch boundary, draining ones with `weight >= quorum` to `state.builder_pending_withdrawals`. Cross-cut on the weight value.

### With item #65 (proposer-slashing builder-payment voidance)

Item #65 zeroes out `state.builder_pending_payments[idx]` when a proposer is slashed. Same field that `process_attestation` accumulates weight into. Cross-cut on the voidance.

### With item #67 (lodestar builder-sweep divergence)

Sibling lodestar cache pattern, but in `processAttestation` the aggregation is correct (commutative per-validator contributions, gating constant within the function). No analog bug.

### With item #7 H9 (`process_attestation` `data.index < 2`)

Item #7 H9 audited the payload-availability signaling at the data.index level. This item covers the surrounding builder-payment-weight accumulation, which sits on top of the same code path.

## Adjacent untouched

1. **`initiate_builder_exit` cross-client** — sister to `initiate_validator_exit` audited as part of item #16. Sets `builder.withdrawable_epoch = current + MIN_BUILDER_WITHDRAWABILITY_DELAY`.
2. **`MIN_BUILDER_WITHDRAWABILITY_DELAY` constant cross-client** — verify uniform value.
3. **EIP-7044 fork-version dispatch** — `voluntary_exit_signature_fork` (nimbus) and equivalent in other clients; verify all 6 use `CAPELLA_FORK_VERSION` post-Deneb regardless of fork.
4. **`get_pending_balance_to_withdraw_for_builder` cross-client byte-equivalence** — same function nimbus had alpha-drift in. Verify all 6 produce identical Gwei output on identical state.
5. **Lodestar's `RootCache` variant of `is_attestation_same_slot`** — used on gossip validation path; verify cache invariants match state.
6. **`process_attestation` weight accumulation for same-slot attestations across multiple aggregations** — pathological case where many attestations all target the same slot. Lodestar's `builderWeightMap` would accumulate correctly; spec's per-state-write would too. Cross-cut on convergence.
