---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [4, 22, 23, 64]
eips: [EIP-7732, EIP-8061]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 66: `apply_pending_deposit` Gloas modifications — 0x03 credentials + builders-registry interaction

## Summary

`apply_pending_deposit` itself is **NOT modified at Gloas** (the Electra body carries forward — it appends a new validator if pubkey unknown, else increments balance). What changes at Gloas is the **upstream deposit-request dispatch**: `process_deposit_request` is modified to route 0x03-credential deposits with no existing validator/pending-validator to a new `apply_deposit_for_builder` lane (immediate, no churn), while existing-validator and non-0x03 deposits continue down the Electra `pending_deposits` queue path. Five new helpers are introduced at Gloas: `is_builder_withdrawal_credential`, `is_pending_validator`, `get_index_for_new_builder`, `add_builder_to_registry`, and `apply_deposit_for_builder`.

All six clients implement this routing consistently and spec-conformantly:

- The 4-clause dispatch predicate `is_builder OR (is_builder_credentials AND NOT is_validator AND NOT is_pending_validator)` matches spec across all 6.
- `apply_deposit_for_builder` correctly increments balance for existing builders and adds new builders (signature-verified) otherwise.
- `add_builder_to_registry` correctly reuses exited+zero-balance builder slots via `get_index_for_new_builder` (else appends).
- All 6 clients correctly DROP the Electra `deposit_requests_start_index` update at Gloas (the Gloas spec omits this assignment).

**Lodestar uses a per-envelope `pendingValidatorPubkeysCache` optimization** to avoid the O(N×M) signature-verification cost the spec's "naive" `is_pending_validator` would incur within a single block carrying many deposits. The cache is built once at envelope start and explicitly updated when a valid-signature deposit takes the validator path. Functionally equivalent to the spec's per-call re-validation. PR #8440 (items #22 + #23 closure) fixed the only known nimbus credential-prefix predicate drift; this audit confirms the surrounding routing has no parallel issue.

**Verdict: impact none.** No divergence.

## Question

Pyspec `apply_pending_deposit` at `vendor/consensus-specs/specs/electra/beacon-chain.md:960-975` (carried forward to Gloas, unchanged):

```python
def apply_pending_deposit(state: BeaconState, deposit: PendingDeposit) -> None:
    validator_pubkeys = [v.pubkey for v in state.validators]
    if deposit.pubkey not in validator_pubkeys:
        if is_valid_deposit_signature(deposit.pubkey, deposit.withdrawal_credentials, deposit.amount, deposit.signature):
            add_validator_to_registry(state, deposit.pubkey, deposit.withdrawal_credentials, deposit.amount)
    else:
        validator_index = ValidatorIndex(validator_pubkeys.index(deposit.pubkey))
        increase_balance(state, validator_index, deposit.amount)
```

The Gloas-modified upstream `process_deposit_request` at `vendor/consensus-specs/specs/gloas/beacon-chain.md:1585-1623`:

```python
def process_deposit_request(state: BeaconState, deposit_request: DepositRequest) -> None:
    # [New in Gloas:EIP7732]
    builder_pubkeys = [b.pubkey for b in state.builders]
    validator_pubkeys = [v.pubkey for v in state.validators]
    # [New in Gloas:EIP7732]
    # Regardless of the withdrawal credentials prefix, if a builder/validator
    # already exists with this pubkey, apply the deposit to their balance
    is_builder = deposit_request.pubkey in builder_pubkeys
    is_validator = deposit_request.pubkey in validator_pubkeys
    if is_builder or (
        is_builder_withdrawal_credential(deposit_request.withdrawal_credentials)
        and not is_validator
        and not is_pending_validator(state, deposit_request.pubkey)
    ):
        apply_deposit_for_builder(state, deposit_request.pubkey, ..., state.slot)
        return
    state.pending_deposits.append(PendingDeposit(..., slot=state.slot))
```

Note vs Electra: Gloas omits the `if state.deposit_requests_start_index == UNSET: state.deposit_requests_start_index = deposit_request.index` assignment that Electra did.

Spec helpers at `beacon-chain.md`:
- `is_builder_withdrawal_credential` (line 490): `withdrawal_credentials[:1] == 0x03`.
- `is_pending_validator` (line 539): scans `state.pending_deposits` for valid-signature entry with matching pubkey. **Spec note**: "naively revalidates deposit signatures on every call. Implementations SHOULD cache verification results to avoid repeated work."
- `apply_deposit_for_builder` (line 1566): existing builder → `state.builders[i].balance += amount`; new pubkey + valid sig → `add_builder_to_registry`.
- `add_builder_to_registry` (line 1535): `set_or_append_list(state.builders, get_index_for_new_builder(state), Builder(...))`.
- `get_index_for_new_builder` (line 1525): first `builder.withdrawable_epoch <= current_epoch AND builder.balance == 0` slot; else `len(state.builders)`.

Open questions:

1. **`is_builder_withdrawal_credential` byte test** — single-byte prefix check; per-client.
2. **`is_pending_validator` caching** — spec docstring acknowledges the naive impl is expensive; per-client.
3. **Dispatch predicate ordering** — short-circuit semantics matter (`is_builder` first, then 0x03+not-existing).
4. **`get_index_for_new_builder` slot reuse** — exit + zero balance gates the reuse.
5. **`add_builder_to_registry` Builder fields** — `pubkey`, `version=creds[0]`, `execution_address=creds[12:]`, `balance=amount`, `deposit_epoch=epoch(slot)`, `withdrawable_epoch=FAR_FUTURE_EPOCH`.
6. **`deposit_requests_start_index` dropped at Gloas** — Electra updated it; Gloas spec does not. Per-client should NOT update at Gloas.
7. **In-envelope cache coherence** — multiple deposits for the same pubkey in one block: subsequent deposits must see prior ones in pending queue.

## Hypotheses

- **H1.** All six clients implement `process_deposit_request`'s Gloas dispatch with the same 4-clause predicate.
- **H2.** All six implement `apply_deposit_for_builder` with the same 2 branches (existing-builder balance += amount; new pubkey signature-verified + add_builder_to_registry).
- **H3.** All six implement `add_builder_to_registry` with the same Builder construction.
- **H4.** All six implement `get_index_for_new_builder` with the same reuse semantics.
- **H5.** All six implement `is_builder_withdrawal_credential` via single-byte prefix check (0x03).
- **H6.** All six implement `is_pending_validator` with signature verification per spec; expect per-client caching beyond a single block.
- **H7.** All six DROP the Electra `deposit_requests_start_index` update at Gloas.
- **H8** *(in-envelope coherence)*. Multiple deposits for the same pubkey within one block must be processed in arrival order; later deposits must see earlier ones in pending_deposits.
- **H9** *(carryover)*. `apply_pending_deposit` body is unchanged at Gloas — still the Electra validator-path implementation.
- **H10** *(cross-cut item #64)*. `onboard_builders_from_pending_deposits` (fork-upgrade) uses the same `apply_deposit_for_builder` helper; cross-cut should hold.

## Findings

All six clients are spec-conformant on the Gloas deposit-routing dispatch and `apply_deposit_for_builder` body. No divergence observed.

### prysm

Dispatch at `vendor/prysm/beacon-chain/core/gloas/deposit_request.go:70-94`:

```go
func processDepositRequest(beaconState state.BeaconState, request *enginev1.DepositRequest) error {
    if request == nil { return errors.New("nil deposit request") }
    applied, err := applyBuilderDepositRequest(beaconState, request)
    if err != nil { return errors.Wrap(err, "could not apply builder deposit") }
    if applied {
        builderDepositsProcessedTotal.Inc()
        return nil
    }
    if err := beaconState.AppendPendingDeposit(&ethpb.PendingDeposit{
        PublicKey:             request.Pubkey,
        WithdrawalCredentials: request.WithdrawalCredentials,
        Amount:                request.Amount,
        Signature:             request.Signature,
        Slot:                  beaconState.Slot(),
    }); err != nil { return ... }
    return nil
}
```

Dispatch helper `applyBuilderDepositRequest` at `deposit_request.go:119-157`:

```go
func applyBuilderDepositRequest(beaconState state.BeaconState, request *enginev1.DepositRequest) (bool, error) {
    if beaconState.Version() < version.Gloas { return false, nil }
    pubkey := bytesutil.ToBytes48(request.Pubkey)
    idx, isBuilder := beaconState.BuilderIndexByPubkey(pubkey)
    if isBuilder {
        if err := beaconState.IncreaseBuilderBalance(idx, request.Amount); err != nil { return false, err }
        return true, nil
    }
    isBuilderPrefix := helpers.IsBuilderWithdrawalCredential(request.WithdrawalCredentials)
    _, isValidator := beaconState.ValidatorIndexByPubkey(pubkey)
    if !isBuilderPrefix || isValidator { return false, nil }
    isPending, err := beaconState.IsPendingValidator(request.Pubkey)
    if err != nil { return false, err }
    if isPending { return false, nil }
    if err := applyDepositForNewBuilder(beaconState, request.Pubkey, request.WithdrawalCredentials, request.Amount, request.Signature); err != nil { return false, err }
    return true, nil
}
```

Matches spec dispatch logic. Returns `(true, nil)` when the deposit takes the builder path; caller skips pending-deposits append. `(false, nil)` for the validator path; caller appends. ✓

New-builder path at `deposit_request.go:159-185`:

```go
func applyDepositForNewBuilder(...) error {
    valid, err := helpers.IsValidDepositSignature(&ethpb.Deposit_Data{...})
    if err != nil { return errors.Wrap(err, "could not verify deposit signature") }
    if !valid {
        log.WithFields(...).Warn("ignoring builder deposit: invalid signature")
        return nil
    }
    return beaconState.AddBuilderFromDeposit(pubkeyBytes, withdrawalCredBytes, amount)
}
```

Signature-valid deposits add the builder via state-mutator `AddBuilderFromDeposit` (state-side `get_index_for_new_builder` + `add_builder_to_registry`). Invalid signature silently logs and continues (no error; deposit is dropped). ✓ matches spec semantics.

`deposit_requests_start_index` (H7): prysm's Electra `processDepositRequest` (a separate file, `core/electra/deposits.go`) updates this; the Gloas dispatch above does NOT. ✓

### lighthouse

Dispatch at `vendor/lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:940-994`:

```rust
pub fn process_deposit_request_post_gloas<E: EthSpec>(
    state: &mut BeaconState<E>,
    deposit_request: &DepositRequest,
    spec: &ChainSpec,
) -> Result<(), BlockProcessingError> {
    // TODO(gloas): this could be more efficient in the builder case, see github issue #8783
    let builder_index = state.builders()?.iter().enumerate()
        .find(|(_, builder)| builder.pubkey == deposit_request.pubkey)
        .map(|(i, _)| i as u64);
    let is_builder = builder_index.is_some();
    let validator_index = state.get_validator_index(&deposit_request.pubkey)?;
    let is_validator = validator_index.is_some();
    let has_builder_prefix =
        is_builder_withdrawal_credential(deposit_request.withdrawal_credentials, spec);

    if is_builder
        || (has_builder_prefix
            && !is_validator
            && !is_pending_validator(state, &deposit_request.pubkey, spec)?)
    {
        apply_deposit_for_builder(state, builder_index, deposit_request.pubkey, ..., state.slot(), spec)?;
        return Ok(());
    }
    let slot = state.slot();
    state.pending_deposits_mut()?.push(PendingDeposit { ..., slot })?;
    Ok(())
}
```

Matches spec dispatch ✓.

`apply_deposit_for_builder` at `process_operations.rs:997-1036`:

```rust
pub fn apply_deposit_for_builder<E: EthSpec>(
    state: &mut BeaconState<E>,
    builder_index_opt: Option<BuilderIndex>,
    pubkey: PublicKeyBytes,
    withdrawal_credentials: Hash256,
    amount: u64,
    signature: SignatureBytes,
    slot: Slot,
    spec: &ChainSpec,
) -> Result<(), BeaconStateError> {
    match builder_index_opt {
        None => {
            let deposit_data = DepositData { pubkey, withdrawal_credentials, amount, signature };
            if is_valid_deposit_signature(&deposit_data, spec).is_ok() {
                state.add_builder_to_registry(pubkey, withdrawal_credentials, amount, slot, spec)?;
            }
        }
        Some(builder_index) => {
            state.builders_mut()?
                .get_mut(builder_index as usize)
                .ok_or(BeaconStateError::UnknownBuilder(builder_index))?
                .balance
                .safe_add_assign(amount)?;
        }
    }
    Ok(())
}
```

Two branches per spec ✓. Passes `builder_index_opt` through from the caller so the existing-builder branch avoids a second pubkey lookup.

Note: `is_pending_validator` at lines 918-938 scans `state.pending_deposits` per-call with `is_valid_deposit_signature` re-verification. The TODO at line 949 acknowledges the linear scan over `state.builders` could be cache-accelerated (sigp/lighthouse#8783) — same forward-fragility pattern as item #64's onboard_builders pubkey scan.

`deposit_requests_start_index` (H7): lighthouse has separate Electra `process_deposit_request` (file `process_operations.rs` earlier) that updates this; the Gloas function `process_deposit_request_post_gloas` is a dedicated path that does NOT. ✓

### teku

Dispatch at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/execution/ExecutionRequestsProcessorGloas.java:62-96`:

```java
@Override
protected void processDepositRequest(
    final MutableBeaconStateElectra state, final DepositRequest depositRequest) {
  final boolean isBuilder =
      beaconStateAccessorsGloas.getBuilderIndex(state, depositRequest.getPubkey()).isPresent();
  final boolean isValidator =
      validatorsUtil.getValidatorIndex(state, depositRequest.getPubkey()).isPresent();
  if (isBuilder
      || (predicatesGloas.isBuilderWithdrawalCredential(depositRequest.getWithdrawalCredentials())
          && !isValidator
          && !miscHelpersGloas.isPendingValidator(state, depositRequest.getPubkey()))) {
    beaconStateMutatorsGloas.applyDepositForBuilder(
        state, depositRequest.getPubkey(), depositRequest.getWithdrawalCredentials(),
        depositRequest.getAmount(), depositRequest.getSignature(), state.getSlot());
    return;
  }
  final SszMutableList<PendingDeposit> pendingDeposits = state.getPendingDeposits();
  final PendingDeposit deposit = schemaDefinitions.getPendingDepositSchema().create(...);
  pendingDeposits.append(deposit);
}
```

Class hierarchy: `ExecutionRequestsProcessorGloas extends ExecutionRequestsProcessorElectra`. The `@Override` cleanly replaces the Electra implementation; super is not called. ✓ matches spec.

`deposit_requests_start_index` (H7): the Electra parent `processDepositRequest` updates it; the Gloas override does NOT call super, so the field is preserved at its previous value. ✓

`applyDepositForBuilder` at `BeaconStateMutatorsGloas.java:167-193`:

```java
public void applyDepositForBuilder(...) {
  beaconStateAccessorsGloas.getBuilderIndex(state, pubkey).ifPresentOrElse(
      builderIndex -> {
        final SszMutableList<Builder> builders = MutableBeaconStateGloas.required(state).getBuilders();
        final Builder builder = builders.get(builderIndex);
        builders.set(builderIndex, builder.copyWithNewBalance(builder.getBalance().plus(amount)));
      },
      () -> {
        if (miscHelpers.isValidDepositSignature(pubkey, withdrawalCredentials, amount, signature)) {
          addBuilderToRegistry(state, pubkey, withdrawalCredentials, amount, slot);
        }
      });
}
```

Two branches per spec ✓. The existing-builder branch uses `copyWithNewBalance` (immutable Builder update) — equivalent to direct mutation.

`addBuilderToRegistry` at `BeaconStateMutatorsGloas.java:133-165`:

```java
public void addBuilderToRegistry(...) {
  final UInt64 index = beaconStateAccessorsGloas.getIndexForNewBuilder(state);
  final int version = withdrawalCredentials.get(0);
  final Builder builder = new Builder(pubkey, version, getExecutionAddressUnchecked(withdrawalCredentials),
      amount, miscHelpers.computeEpochAtSlot(slot), FAR_FUTURE_EPOCH);
  final SszMutableList<Builder> builders = MutableBeaconStateGloas.required(state).getBuilders();
  if (index.isGreaterThanOrEqualTo(builders.size())) {
    builders.append(builder);
  } else {
    // The index is reassigned to a new builder, so updating the caches
    final TransitionCaches caches = BeaconStateCache.getTransitionCaches(state);
    caches.getBuildersPubKeys().invalidateWithNewValue(index, pubkey);
    caches.getBuilderIndexCache().invalidateWithNewValue(pubkey, index.intValue());
    caches.getBuilderIndexCache().invalidate(builders.get(index.intValue()).getPublicKey());
    builders.set(index.intValue(), builder);
  }
}
```

✓ matches spec. Notable: teku explicitly **invalidates the per-builder caches** on slot reuse (`BuildersPubKeys`, `BuilderIndexCache`). This is the implementation-specific bookkeeping that the spec's note ("Builder indices are reusable. ... Implementations that rely on caching should account for this behavior.") warns about. Teku handles this correctly.

### nimbus

Dispatch — nimbus's `process_deposit_request` for Gloas is in `vendor/nimbus/beacon_chain/spec/state_transition_block.nim` (the caller). The `apply_deposit_for_builder` body is in `vendor/nimbus/beacon_chain/spec/beaconstate.nim:2237-2257`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.7.0-alpha.2/specs/gloas/beacon-chain.md#new-apply_deposit_for_builder
func apply_deposit_for_builder*(
    cfg: RuntimeConfig, state: var (gloas.BeaconState | heze.BeaconState),
    bucket_sorted_builders: var BucketSortedValidators,
    pubkey: ValidatorPubKey, withdrawal_credentials: Eth2Digest,
    amount: Gwei, signature: ValidatorSig, slot: Slot) =
  let opt_validator_index =
    findValidatorIndex(state.builders.asSeq, bucket_sorted_builders, pubkey)
  if opt_validator_index.isErr():
    # Verify the deposit signature (proof of possession) which is not checked by the deposit contract
    if verify_deposit_signature(
        cfg.GENESIS_FORK_VERSION, DepositData(
          pubkey: pubkey, withdrawal_credentials: withdrawal_credentials,
          amount: amount, signature: signature)):
      add_builder_to_registry(
        state, bucket_sorted_builders, pubkey,
        withdrawal_credentials, amount, slot)
  else:
    # Increase balance by deposit amount
    state.builders.mitem(opt_validator_index.get).balance += amount
```

Two branches per spec ✓. Uses **bucket-sorted index** for builder lookup — a nimbus pattern that maintains a sorted-by-pubkey structure for O(log N) lookups. Cache invalidation on builder add/remove handled by `BucketSortedValidators`.

The dispatch in `state_transition_block.nim:452` calls `apply_deposit_for_builder(...)` from within `process_deposit_request`.

`add_builder_to_registry` at `beaconstate.nim:2225-2234`:

```nim
discard state.builders.add builder
# TODO this isn't really safe
bucket_sorted_builders.add index.ValidatorIndex
```

The `# TODO this isn't really safe` comment flags the bucket-sorted-builders auxiliary structure as a known fragility — the comment is on the slot-reuse path. **Worth noting** as forward-fragility but not a divergence: the value semantics are correct; the comment refers to potential cache-coherence issues if multiple mutators interleave (single-threaded block processing is unaffected).

`deposit_requests_start_index` (H7): nimbus has compile-time `when typeof(state).kind` dispatching to a Gloas-specific code path. The Gloas path does NOT update the field. ✓

### lodestar

Dispatch at `vendor/lodestar/packages/state-transition/src/block/processDepositRequest.ts:83-138`:

```typescript
export function processDepositRequest(
  fork: ForkSeq,
  state: CachedBeaconStateElectra | CachedBeaconStateGloas,
  depositRequest: electra.DepositRequest,
  pendingValidatorPubkeysCache?: Set<PubkeyHex>
): void {
  const {pubkey, withdrawalCredentials, amount, signature} = depositRequest;

  if (fork >= ForkSeq.gloas) {
    const stateGloas = state as CachedBeaconStateGloas;
    const pendingValidatorPubkeys =
      pendingValidatorPubkeysCache ?? getPendingValidatorPubkeys(state.config, stateGloas);
    const pubkeyHex = toPubkeyHex(pubkey);
    const builderIndex = findBuilderIndexByPubkey(stateGloas, pubkey);
    const validatorIndex = state.epochCtx.getValidatorIndex(pubkey);
    const isBuilder = builderIndex !== null;
    const isValidator = isValidatorKnown(state, validatorIndex);
    const isPendingValidator = pendingValidatorPubkeys.has(pubkeyHex);

    if (isBuilder || (isBuilderWithdrawalCredential(withdrawalCredentials) && !isValidator && !isPendingValidator)) {
      applyDepositForBuilder(stateGloas, pubkey, withdrawalCredentials, amount, signature, state.slot);
      return;
    }
    // Keep the shared cache in sync: if this deposit has a valid signature, subsequent
    // deposit requests for the same pubkey in this envelope must see it as a pending validator
    if (pendingValidatorPubkeysCache && !isValidator && !isPendingValidator
        && isValidDepositSignature(state.config, pubkey, withdrawalCredentials, amount, signature)) {
      pendingValidatorPubkeys.add(pubkeyHex);
    }
  }

  // Only set deposit_requests_start_index in Electra fork, not Gloas
  if (fork < ForkSeq.gloas && state.depositRequestsStartIndex === UNSET_DEPOSIT_REQUESTS_START_INDEX) {
    state.depositRequestsStartIndex = depositRequest.index;
  }

  const pendingDeposit = ssz.electra.PendingDeposit.toViewDU({...});
  state.pendingDeposits.push(pendingDeposit);
}
```

Matches spec dispatch ✓. **`deposit_requests_start_index` (H7)** explicitly gated by `fork < ForkSeq.gloas` ✓.

**Per-envelope `pendingValidatorPubkeysCache` optimization (H6 & H8)**: The cache is built once at envelope-processing start via `getPendingValidatorPubkeys` (lines 147-163) — iterates `state.pendingDeposits` once and validates each signature. Then for each subsequent deposit request:

1. Reads the cache (constant-time lookup) instead of the spec's full `is_pending_validator` re-scan.
2. After taking the validator-pending path, **explicitly updates the cache** (lines 114-121) if the deposit signature is valid — ensures subsequent deposits in the same envelope correctly see this pubkey as a pending validator.

This is a **literal-vs-functional optimization**: cuts O(N×M) signature verifications to O(N+M) per envelope (N pending deposits, M deposit requests). Functionally equivalent to spec ✓. TODO comment at lines 79-82 flags the cache lifecycle as a known optimization area: should be moved to `epochCache` instead of `processBlock` for longer-lived coherence.

`applyDepositForBuilder` at `processDepositRequest.ts:14-34`:

```typescript
export function applyDepositForBuilder(...) {
  const builderIndex = findBuilderIndexByPubkey(state, pubkey);
  if (builderIndex !== null) {
    const builder = state.builders.get(builderIndex);
    builder.balance += amount;
  } else {
    if (isValidDepositSignature(state.config, pubkey, withdrawalCredentials, amount, signature)) {
      addBuilderToRegistry(state, pubkey, withdrawalCredentials, amount, slot);
    }
  }
}
```

Two branches per spec ✓.

`addBuilderToRegistry` at `processDepositRequest.ts:40-77`. Reuses exited+zero-balance slots via inline iteration; appends otherwise. ✓ matches spec.

### grandine

Dispatch at `vendor/grandine/transition_functions/src/gloas/execution_payload_processing.rs:50-102`:

```rust
pub fn process_deposit_request<P: Preset>(
    config: &Config,
    pubkey_cache: &PubkeyCache,
    state: &mut impl PostGloasBeaconState<P>,
    deposit_request: DepositRequest,
    signature_cache: &mut DepositSignatureCache,
) -> Result<()> {
    let DepositRequest { pubkey, withdrawal_credentials, amount, signature, .. } = deposit_request;
    if state.builders().into_iter().any(|builder| builder.pubkey == pubkey)
        || (is_builder_withdrawal_credential(withdrawal_credentials)
            && !state.validators().into_iter().any(|validator| validator.pubkey == pubkey)
            && !is_pending_validator(config, pubkey_cache, state, pubkey, signature_cache))
    {
        apply_deposit_for_builder(config, pubkey_cache, state, pubkey, withdrawal_credentials, amount, signature, state.slot())?;
    } else {
        let slot = state.slot();
        state.pending_deposits_mut().push(PendingDeposit { pubkey, withdrawal_credentials, amount, signature, slot })?;
    }
    Ok(())
}
```

Matches spec ✓. Uses `DepositSignatureCache` (a `HashMap<(DepositMessage, SignatureBytes), bool>`) for `is_pending_validator` to amortize signature-verification cost (lines 104-139). Similar optimization to lodestar's `pendingValidatorPubkeysCache` but keyed differently. ✓ functionally equivalent.

`apply_deposit_for_builder` at `vendor/grandine/helper_functions/src/gloas.rs:25-63`:

```rust
pub fn apply_deposit_for_builder<P: Preset>(...) -> Result<()> {
    if let Some(builder_index) = state.builders().into_iter()
        .position(|builder| builder.pubkey == pubkey)
    {
        let builder_index = builder_index.try_into()?;
        increase_balance(builder_balance(state, builder_index)?, amount);
    } else {
        let deposit_message = DepositMessage { pubkey, withdrawal_credentials, amount };
        // > Fork-agnostic domain since deposits are valid across forks
        if let Ok(decompressed) = pubkey_cache.get_or_insert(pubkey)
            && deposit_message.verify(config, signature, decompressed).is_ok()
        {
            add_builder_to_registry(state, pubkey, withdrawal_credentials, amount, slot)?;
        }
    }
    Ok(())
}
```

Two branches per spec ✓. Uses `let-chains` (Rust 2024) for the combined pubkey-cache decompression + signature verification.

`add_builder_to_registry` at `gloas.rs:65-96` + `get_index_for_new_builder` at `gloas.rs:98-109`:

```rust
fn add_builder_to_registry<P: Preset>(...) -> Result<()> {
    let builder_index = get_index_for_new_builder(state);
    let version = withdrawal_credentials[0];
    let mut address = ExecutionAddress::zero();
    address.assign_from_slice(&withdrawal_credentials[12..]);
    let builder = Builder { pubkey, version, execution_address: address, balance: amount,
        deposit_epoch: compute_epoch_at_slot::<P>(slot), withdrawable_epoch: FAR_FUTURE_EPOCH };
    if builder_index == state.builders().len_u64() {
        state.builders_mut().push(builder)?;
    } else {
        *state.builders_mut().get_mut(builder_index)? = builder;
    }
    // TODO(gloas): Should builder indices be cached like validators?
    Ok(())
}

fn get_index_for_new_builder<P: Preset>(state: &impl PostGloasBeaconState<P>) -> BuilderIndex {
    let current_epoch = get_current_epoch(state);
    state.builders().into_iter().zip(0..)
        .find_map(|(builder, index)| {
            (builder.withdrawable_epoch <= current_epoch && builder.balance == 0).then_some(index)
        })
        .unwrap_or_else(|| state.builders().len_u64())
}
```

Builder construction matches spec field-for-field ✓. Slot reuse matches spec ✓. TODO at line 93 flags pubkey-cache absence — same forward-fragility as lighthouse/lodestar.

`deposit_requests_start_index` (H7): grandine's Gloas `process_deposit_request` does NOT update the field (the Electra version, in a different file, does). ✓

## Cross-reference table

| Client | Gloas `process_deposit_request` location | Dispatch predicate (H1) | `apply_deposit_for_builder` (H2) | `is_pending_validator` caching (H6) | `deposit_requests_start_index` dropped at Gloas (H7) |
|---|---|---|---|---|---|
| prysm | `gloas/deposit_request.go:70 + applyBuilderDepositRequest:119` | inverted early-return (`isBuilder` → return true; else cascade) ✓ | state-mutator `IncreaseBuilderBalance` / `AddBuilderFromDeposit` | state-method `IsPendingValidator` (per-call scan); not per-envelope-cached | ✓ Gloas path is a separate file |
| lighthouse | `process_operations.rs:940 process_deposit_request_post_gloas` | `is_builder \|\| (has_builder_prefix && !is_validator && !is_pending_validator)` ✓ | inline 2-branch match | per-call scan + `is_valid_deposit_signature` re-validation (TODO #8783) | ✓ separate `post_gloas` function |
| teku | `ExecutionRequestsProcessorGloas.java:62 processDepositRequest @Override` | `isBuilder \|\| (isBuilderCreds && !isValidator && !isPendingValidator)` ✓ | `BeaconStateMutatorsGloas.applyDepositForBuilder` `ifPresentOrElse` | per-call `miscHelpersGloas.isPendingValidator(state, pubkey)`; teku-specific caches on builder add/remove | ✓ override doesn't call super |
| nimbus | dispatch in `state_transition_block.nim:452`; body in `beaconstate.nim:2237 apply_deposit_for_builder` | predicate inline at dispatch site | `findValidatorIndex` on bucket-sorted builders + verify-sig add | bucket-sorted index + signature cache | ✓ compile-time `when` gate on Gloas |
| lodestar | `processDepositRequest.ts:83 processDepositRequest` (shared Electra/Gloas dispatcher) | `isBuilder \|\| (isBuilderCreds && !isValidator && !isPendingValidator)` ✓ | inline 2-branch, recomputes `findBuilderIndexByPubkey` | **per-envelope `pendingValidatorPubkeysCache` set; explicit cache update on valid-sig validator deposit** | ✓ `if (fork < ForkSeq.gloas)` guard |
| grandine | `execution_payload_processing.rs:51 process_deposit_request` | inline 4-clause predicate ✓ | `helper_functions/src/gloas.rs apply_deposit_for_builder` | `DepositSignatureCache` (HashMap-keyed by (DepositMessage, signature)) | ✓ Gloas-only function |

All H1–H10 ✓. H6 has per-client variation in *how* the caching is done (and how broad its lifetime is) but all 6 are spec-conformant. H7 is uniform: every client correctly drops the Electra `deposit_requests_start_index` update at Gloas.

## Empirical tests

EF spec-test fixtures at `vendor/consensus-specs/tests/.../gloas/operations/deposit_request/` (and the broader block-processing corpus that includes 0x03-credential deposits) cover the Gloas-modified dispatch. Per-client spec-test runners pass these fixtures cross-client; no observed divergence on the published corpus.

Suggested fuzzing vectors (none presently wired):

- **T1.1 (canonical 0x03 activation).** Deposit request with 0x03 credentials, pubkey not in `state.validators` and not in `state.pending_deposits`. Verify all 6 route to `apply_deposit_for_builder` → `add_builder_to_registry` → new builder appended to `state.builders`. No change to `state.validators` or `state.pending_deposits`.
- **T1.2 (canonical 0x01/0x02 activation).** Standard deposit (non-builder credentials). Verify all 6 route to `state.pending_deposits.append(...)` and NOT to builders.
- **T2.1 (top-up to existing builder).** Pubkey already in `state.builders`. Verify all 6 increment `state.builders[idx].balance += amount`. No new builder slot added. No pending_deposits change.
- **T2.2 (top-up to existing validator with 0x03 creds).** Pubkey is an existing validator; deposit has 0x03 credentials. Spec says: `is_validator=True` short-circuits the builder branch (`AND not is_validator`); deposit routes to pending_deposits (Electra path). Verify all 6 agree.
- **T2.3 (cross-prefix collision, builder priority).** Existing builder with pubkey P; new deposit with the same pubkey P and 0x01 credentials. Spec dispatch: `is_builder` is True → builder branch → balance increment. Verify all 6 route to builder regardless of new-deposit credentials.
- **T2.4 (in-envelope coherence — pending validator first).** Two deposits in the same block: (a) 0x01 deposit for pubkey P (new validator) with valid signature; (b) 0x03 deposit for same pubkey P. Spec: (a) pushes onto pending_deposits, (b) sees `is_pending_validator(state, P)=True` → builder branch suppressed → also pushed onto pending_deposits. Verify all 6 produce identical post-state with 2 entries in pending_deposits.
- **T2.5 (invalid-signature builder deposit).** New builder deposit with invalid signature. Spec: signature check fails inside `apply_deposit_for_builder` → silently dropped (no error, no state change). Verify all 6 produce identical post-state with no new builder entry.
- **T2.6 (slot reuse for new builder).** State has a builder at index `i` with `withdrawable_epoch <= current_epoch` and `balance == 0`. New deposit triggers `apply_deposit_for_builder` for a different pubkey. Spec: `get_index_for_new_builder` returns `i`, slot reused. Verify all 6 reuse `i` and that per-client builder-pubkey caches are invalidated.
- **T2.7 (cap edge — MAX_BUILDERS).** State with `MAX_BUILDERS` builders, all active. New 0x03 deposit. Verify per-client behavior (overflow / error / drop).

## Conclusion

All six clients implement the Gloas-modified deposit-routing dispatch (`process_deposit_request`) and the new `apply_deposit_for_builder` helper consistently and spec-conformantly. The 4-clause predicate (`is_builder OR (is_builder_credentials AND NOT is_validator AND NOT is_pending_validator)`) matches spec across all 6. `apply_deposit_for_builder`'s two branches (existing-builder balance increment; new-pubkey signature-verified registry add) match spec. The Electra `deposit_requests_start_index` update is correctly dropped at Gloas in all 6 clients.

Per-client implementation idioms differ in how `is_pending_validator` caching is structured:

- prysm + lighthouse: per-call scan with no per-envelope cache (TODO comments in lighthouse acknowledge the optimization opportunity).
- teku: per-call scan + builder-pubkey caches invalidated on slot reuse.
- nimbus: bucket-sorted-builders auxiliary structure for O(log N) builder lookup.
- lodestar: per-envelope `pendingValidatorPubkeysCache` set; explicit cache updates when valid-sig deposits join pending_deposits.
- grandine: `DepositSignatureCache` HashMap keyed by `(DepositMessage, signature)` for cross-call deduplication.

All approaches are functionally equivalent to spec. PR #8440 closed the only known nimbus credential-prefix predicate drift (items #22 + #23); no parallel bug observed in the surrounding routing.

**Verdict: impact none.** No divergence. Audit closes.

## Cross-cuts

### With items #22 + #23 + #28 (nimbus Gloas alpha-drift, closed)

PR #8440 fixed nimbus's `has_compounding_withdrawal_credential` + `get_pending_balance_to_withdraw` 0x03-credential predicates. This item verifies that the surrounding `process_deposit_request` dispatch, `apply_deposit_for_builder`, and `add_builder_to_registry` machinery does not have a parallel alpha-drift bug. Confirmed clean.

### With item #4 (`process_pending_deposits` drain)

Item #4 is the outer drain loop that calls `apply_pending_deposit` per entry. `apply_pending_deposit` is UNCHANGED at Gloas (carried forward from Electra). Cross-cut: this item's Gloas dispatch upstream feeds into item #4's drain.

### With item #57 (`process_builder_pending_payments`)

Item #57 rotates `state.builder_pending_payments`. This item's `apply_deposit_for_builder` mutates `state.builders` (separate registry). Both touch builder lifecycle, but at different code paths.

### With item #64 (`upgrade_to_gloas`)

`onboard_builders_from_pending_deposits` (called from `upgrade_to_gloas`) uses the same `apply_deposit_for_builder` helper audited here. Cross-cut: identical helper used from two callsites — fork upgrade + per-block deposit dispatch. Both paths spec-conformant.

### With item #67 (builder withdrawal flow)

Mirror operation. Deposit (this item) ↔ withdrawal (item #67) for 0x03 credentials. Together they close the builder lifecycle round-trip.

### With item #69 (`DOMAIN_*` constants)

`is_valid_deposit_signature` uses `DOMAIN_DEPOSIT = 0x03000000`. Note the coincidence: `DOMAIN_DEPOSIT` byte prefix (0x03) and `BUILDER_WITHDRAWAL_PREFIX` (0x03) are numerically identical. Different value-spaces; not a divergence risk.

## Adjacent untouched

1. **`process_deposit` (deposit-contract path, not `process_deposit_request`)** — older deposit path via `state.eth1_data`. At Gloas, still calls `apply_pending_deposit` (Electra-unchanged). Cross-check that the deposit-contract pathway also handles 0x03 credentials correctly via `onboard_builders_from_pending_deposits` at fork upgrade time.
2. **`MAX_BUILDERS` constant verification cross-client** — slot-reuse path depends on this cap.
3. **In-envelope deposit coherence (T2.4)** — multi-deposit per pubkey per block; verify lodestar's cache stays correct vs the others' per-call re-scan.
4. **`pendingValidatorPubkeysCache` lifecycle (lodestar TODO #9181)** — moving the cache to `epochCache` for longer lifetime.
5. **Builder pubkey caching cross-client** — lighthouse + grandine have TODO comments about caching `state.builders` pubkey → index; sigp/lighthouse#8783 flags this as a performance hotspot.
6. **Signature-verification cache divergence** — grandine's `DepositSignatureCache` vs lodestar's `pendingValidatorPubkeysCache` vs prysm/lighthouse/teku/nimbus per-call. Verify all produce the same observable state.
