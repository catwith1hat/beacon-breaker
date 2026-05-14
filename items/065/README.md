---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [57]
eips: [EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 65: `process_proposer_slashing` Gloas modification — `BuilderPendingPayment` voidance

## Summary

All six clients implement the Gloas-new `BuilderPendingPayment` voidance branch in `process_proposer_slashing` (consensus-specs `beacon-chain.md:1786-1819`) consistently and spec-conformantly. Each client:

- Computes the proposal-epoch index `payment_index = SLOTS_PER_EPOCH + slot % SLOTS_PER_EPOCH` for current-epoch proposals, `slot % SLOTS_PER_EPOCH` for previous-epoch proposals (matches spec).
- No-ops for proposals > 2 epochs old.
- Zeroes out the slot via the default-constructed `BuilderPendingPayment` value.
- Sequences the voidance **between** the slashing verification and `slash_validator`.

**One literal-vs-functional deviation in teku**: teku's `AbstractBlockProcessor.processProposerSlashings` calls `processProposerSlashingsNoValidation` (non-signature validation → voidance → `slashValidator`) **before** `verifyProposerSlashings` (BLS signature check). The spec verifies signatures inline at step 4 of `process_proposer_slashing`, before the voidance branch. Teku's order: non-signature validation → voidance → slash → signature verification. Functionally equivalent because invalid blocks reject wholesale (the state mutations never escape), but a literal departure from spec sequencing. Mirrors the same eager-state-mutate / late-verify-BLS pattern teku uses elsewhere.

**Verdict: impact none.** No divergence. Audit closes.

## Question

Pyspec `process_proposer_slashing` (Gloas-modified) at `vendor/consensus-specs/specs/gloas/beacon-chain.md:1786-1819`:

```python
def process_proposer_slashing(state: BeaconState, proposer_slashing: ProposerSlashing) -> None:
    header_1 = proposer_slashing.signed_header_1.message
    header_2 = proposer_slashing.signed_header_2.message

    # Verify header slots match
    assert header_1.slot == header_2.slot
    # Verify header proposer indices match
    assert header_1.proposer_index == header_2.proposer_index
    # Verify the headers are different
    assert header_1 != header_2
    # Verify the proposer is slashable
    proposer = state.validators[header_1.proposer_index]
    assert is_slashable_validator(proposer, get_current_epoch(state))
    # Verify signatures
    for signed_header in (proposer_slashing.signed_header_1, proposer_slashing.signed_header_2):
        domain = get_domain(state, DOMAIN_BEACON_PROPOSER, compute_epoch_at_slot(signed_header.message.slot))
        signing_root = compute_signing_root(signed_header.message, domain)
        assert bls.Verify(proposer.pubkey, signing_root, signed_header.signature)

    # [New in Gloas:EIP7732]
    # Remove the BuilderPendingPayment corresponding to
    # this proposal if it is still in the 2-epoch window.
    slot = header_1.slot
    proposal_epoch = compute_epoch_at_slot(slot)
    if proposal_epoch == get_current_epoch(state):
        payment_index = SLOTS_PER_EPOCH + slot % SLOTS_PER_EPOCH
        state.builder_pending_payments[payment_index] = BuilderPendingPayment()
    elif proposal_epoch == get_previous_epoch(state):
        payment_index = slot % SLOTS_PER_EPOCH
        state.builder_pending_payments[payment_index] = BuilderPendingPayment()

    slash_validator(state, header_1.proposer_index)
```

Window layout: `state.builder_pending_payments: Vector[BuilderPendingPayment, 2 * SLOTS_PER_EPOCH]`. First `SLOTS_PER_EPOCH` rows = previous epoch's pending payments (indices `0..SE-1`); last `SLOTS_PER_EPOCH` rows = current epoch's (indices `SE..2*SE-1`). `slot % SE` is the offset within an epoch.

Spec order of operations:
1. Verify header slots match.
2. Verify proposer indices match.
3. Verify headers differ.
4. Verify proposer is slashable.
5. Verify BLS signatures (both header_1 and header_2).
6. **[Gloas-new]** Remove `BuilderPendingPayment` for slot's epoch if within 2-epoch window.
7. `slash_validator(state, proposer_index)`.

Open questions before source review:

1. **Index formula** — exact match for current/previous epoch index, no off-by-one.
2. **No-op branch** — proposal older than 2 epochs: silently skip (no error).
3. **Order vs `slash_validator`** — voidance happens BEFORE `slash_validator` per spec; per-client.
4. **Order vs signature verification** — voidance happens AFTER signature verification per spec; per-client may swap (eager-mutate / late-verify pattern).
5. **`BuilderPendingPayment()` default-value semantics** — zero-weight, default `BuilderPendingWithdrawal`. Per-client equivalent zero-init.

## Hypotheses

- **H1.** All six clients implement the Gloas-new voidance branch.
- **H2.** All six use `payment_index = SLOTS_PER_EPOCH + slot % SLOTS_PER_EPOCH` for current-epoch proposals.
- **H3.** All six use `payment_index = slot % SLOTS_PER_EPOCH` for previous-epoch proposals.
- **H4.** All six no-op (silently skip) for proposals older than 2 epochs.
- **H5.** All six call the voidance BEFORE `slash_validator` (matching spec).
- **H6.** All six fork-gate the voidance on Gloas activation.
- **H7** *(literal-vs-functional)*. Per-client signature-verification position relative to voidance: spec verifies signatures BEFORE voidance; some clients may defer signature verification to after state mutations as an optimization. Functionally equivalent if invalid blocks reject wholesale.
- **H8** *(forward-fragility)*. Idempotency: voiding an already-default slot is a no-op (no error). Per-client robust.

## Findings

All six clients implement the voidance branch spec-conformantly. Teku has a literal-vs-functional deviation on the signature-verification ordering.

### prysm

Top-level orchestrator at `vendor/prysm/beacon-chain/core/blocks/proposer_slashing.go:122-146`:

```go
func processProposerSlashing(
    ctx context.Context,
    beaconState state.BeaconState,
    slashing *ethpb.ProposerSlashing,
    exitInfo *validators.ExitInfo,
) (state.BeaconState, error) {
    if exitInfo == nil { return nil, errors.New("...") }

    var err error
    // [New in Gloas:EIP7732]: remove the BuilderPendingPayment corresponding to the slashed proposer within 2 epoch window
    if beaconState.Version() >= version.Gloas {
        err = gloas.RemoveBuilderPendingPayment(beaconState, slashing.Header_1.Header)
        if err != nil { return nil, err }
    }

    beaconState, err = validators.SlashValidator(ctx, beaconState, slashing.Header_1.Header.ProposerIndex, exitInfo)
    if err != nil { return nil, errors.Wrapf(err, "could not slash proposer index %d", ...) }
    return beaconState, nil
}
```

Verification happens earlier at `ProcessProposerSlashing` (line 92-105) via `VerifyProposerSlashing` (line 148-180) — full sig + slot + proposer-index + slashable check. Order: verify → voidance → slash. ✓ matches spec.

`RemoveBuilderPendingPayment` at `vendor/prysm/beacon-chain/core/gloas/proposer_slashing.go:28-47`:

```go
func RemoveBuilderPendingPayment(st state.BeaconState, header *eth.BeaconBlockHeader) error {
    proposalEpoch := slots.ToEpoch(header.Slot)
    currentEpoch := time.CurrentEpoch(st)
    slotsPerEpoch := params.BeaconConfig().SlotsPerEpoch

    var paymentIndex primitives.Slot
    if proposalEpoch == currentEpoch {
        paymentIndex = slotsPerEpoch + header.Slot%slotsPerEpoch
    } else if proposalEpoch+1 == currentEpoch {
        paymentIndex = header.Slot % slotsPerEpoch
    } else {
        return nil
    }

    if err := st.ClearBuilderPendingPayment(paymentIndex); err != nil {
        return errors.Wrap(err, "could not clear builder pending payment")
    }
    return nil
}
```

`proposalEpoch + 1 == currentEpoch` is equivalent to `proposalEpoch == get_previous_epoch(state)`. ✓ Index formulas match spec. No-op (return nil) for older proposals matches H4.

State-mutator `ClearBuilderPendingPayment` at `vendor/prysm/beacon-chain/state/state-native/setters_gloas.go:115-131` clears the slot to `emptyBuilderPendingPayment` (default value). Range-checked.

### lighthouse

Inline in `vendor/lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:379-433`:

```rust
pub fn process_proposer_slashings<E: EthSpec>(
    state: &mut BeaconState<E>,
    proposer_slashings: &[ProposerSlashing],
    verify_signatures: VerifySignatures,
    ctxt: &mut ConsensusContext<E>,
    spec: &ChainSpec,
) -> Result<(), BlockProcessingError> {
    state.build_slashings_cache()?;

    proposer_slashings.iter().enumerate().try_for_each(|(i, proposer_slashing)| {
        verify_proposer_slashing(proposer_slashing, state, verify_signatures, spec)
            .map_err(|e| e.into_with_index(i))?;

        // [New in Gloas:EIP7732]
        // Remove the BuilderPendingPayment corresponding to this proposal
        // if it is still in the 2-epoch window.
        if state.fork_name_unchecked().gloas_enabled() {
            let slot = proposer_slashing.signed_header_1.message.slot;
            let proposal_epoch = slot.epoch(E::slots_per_epoch());
            let slot_in_epoch = slot.as_usize().safe_rem(E::SlotsPerEpoch::to_usize())?;

            let payment_index = if proposal_epoch == state.current_epoch() {
                Some(E::SlotsPerEpoch::to_usize().safe_add(slot_in_epoch)?)
            } else if proposal_epoch == state.previous_epoch() {
                Some(slot_in_epoch)
            } else {
                None
            };

            if let Some(index) = payment_index {
                let payment = state
                    .builder_pending_payments_mut()?
                    .get_mut(index)
                    .ok_or(BlockProcessingError::BuilderPaymentIndexOutOfBounds(index))?;
                *payment = BuilderPendingPayment::default();
            }
        }

        slash_validator(state, proposer_slashing.signed_header_1.message.proposer_index as usize, None, ctxt, spec)?;
        Ok(())
    })
}
```

Order: `verify_proposer_slashing` (full sig + slot + indices + slashable) → voidance → `slash_validator`. ✓ matches spec. Fork-gated by `state.fork_name_unchecked().gloas_enabled()`. Uses `safe_add` + `safe_rem` for index arithmetic (overflow-safe per lighthouse's consensus-crate rule). `get_mut(index)` is bounds-checked.

### teku

Top-level orchestrator at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/common/block/AbstractBlockProcessor.java:468-513`:

```java
@Override
public void processProposerSlashings(
    final MutableBeaconState state,
    final SszList<ProposerSlashing> proposerSlashings,
    final BLSSignatureVerifier signatureVerifier)
    throws BlockProcessingException {
  final Supplier<ValidatorExitContext> validatorExitContextSupplier = getValidatorExitContextSupplier(state);
  processProposerSlashingsNoValidation(state, proposerSlashings, validatorExitContextSupplier);
  final BlockValidationResult validationResult =
      verifyProposerSlashings(state, proposerSlashings, signatureVerifier);
  if (!validationResult.isValid()) {
    throw new BlockProcessingException("Slashing signature is invalid");
  }
}

protected void processProposerSlashingsNoValidation(...) throws BlockProcessingException {
  safelyProcess(() -> {
    for (ProposerSlashing proposerSlashing : proposerSlashings) {
      Optional<OperationInvalidReason> invalidReason =
          operationValidator.validateProposerSlashing(state.getFork(), state, proposerSlashing);
      checkArgument(invalidReason.isEmpty(), "process_proposer_slashings: %s", ...);

      removeBuilderPendingPayment(proposerSlashing, state);

      beaconStateMutators.slashValidator(
          state,
          proposerSlashing.getHeader1().getMessage().getProposerIndex().intValue(),
          validatorExitContextSupplier);
    }
  });
}

protected void removeBuilderPendingPayment(
    final ProposerSlashing proposerSlashing, final MutableBeaconState state) {
  // NO-OP until Gloas
}
```

**Literal-vs-functional deviation (H7)**: Order is:
1. `validateProposerSlashing` — non-signature checks (slots match, proposer indices match, headers differ, validator slashable).
2. `removeBuilderPendingPayment` — voidance (Gloas-only).
3. `slashValidator` — slash.
4. `verifyProposerSlashings` — **BLS signature verification, deferred to after all state mutations**.

Spec order: signature verification at step 5 (BEFORE voidance). Teku defers signatures because BLS verification is the expensive step; bundling all signature checks at the end allows batch verification (`signatureVerifier`). If signatures fail, the whole block-transition is rejected — invalid state mutations never escape. **Functionally equivalent on every reachable input.**

Gloas override at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/block/BlockProcessorGloas.java:317-337`:

```java
// Remove the BuilderPendingPayment corresponding to this proposal if it is still in the 2-epoch window.
@Override
protected void removeBuilderPendingPayment(
    final ProposerSlashing proposerSlashing, final MutableBeaconState state) {
  final UInt64 slot = proposerSlashing.getHeader1().getMessage().getSlot();
  final UInt64 proposalEpoch = miscHelpers.computeEpochAtSlot(slot);
  OptionalInt paymentIndex = OptionalInt.empty();
  if (proposalEpoch.equals(beaconStateAccessors.getCurrentEpoch(state))) {
    paymentIndex = OptionalInt.of(
        specConfig.getSlotsPerEpoch() + slot.mod(specConfig.getSlotsPerEpoch()).intValue());
  } else if (proposalEpoch.equals(beaconStateAccessors.getPreviousEpoch(state))) {
    paymentIndex = OptionalInt.of(slot.mod(specConfig.getSlotsPerEpoch()).intValue());
  }
  paymentIndex.ifPresent(
      index -> MutableBeaconStateGloas.required(state)
          .getBuilderPendingPayments()
          .set(index, schemaDefinitionsGloas.getBuilderPendingPaymentSchema().getDefault()));
}
```

Index formulas match spec ✓. Uses `OptionalInt.empty()` for the no-op case (H4 ✓). Default-value via `getBuilderPendingPaymentSchema().getDefault()` ✓.

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:193-219`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-beta.0/specs/gloas/beacon-chain.md#modified-process_proposer_slashing
proc process_proposer_slashing*(
    cfg: RuntimeConfig, state: var ForkyBeaconState,
    proposer_slashing: SomeProposerSlashing, flags: UpdateFlags,
    exit_queue_info: ExitQueueInfo, cache: var StateCache):
    Result[(Gwei, ExitQueueInfo), cstring] =
  let proposer_index = ? check_proposer_slashing(state, proposer_slashing, flags)

  # [New in Gloas:EIP7732]
  # Remove the BuilderPendingPayment corresponding to
  # this proposal if it is still in the 2-epoch window.
  when typeof(state).kind >= ConsensusFork.Gloas:
    let
      slot = proposer_slashing.signed_header_1.message.slot
      proposal_epoch = slot.epoch()
      current_epoch = get_current_epoch(state)

    if proposal_epoch == current_epoch:
      let payment_index = SLOTS_PER_EPOCH + (slot mod SLOTS_PER_EPOCH)
      state.builder_pending_payments[payment_index.int] = BuilderPendingPayment()
    elif proposal_epoch == get_previous_epoch(state):
      let payment_index = slot mod SLOTS_PER_EPOCH
      state.builder_pending_payments[payment_index.int] = BuilderPendingPayment()
  slash_validator(cfg, state, proposer_index, exit_queue_info, cache)
```

Order: `check_proposer_slashing` (full verification, gated by `flags`) → voidance → `slash_validator`. ✓ matches spec. Fork-gated by compile-time `when typeof(state).kind >= ConsensusFork.Gloas`. Index formulas match spec ✓. `BuilderPendingPayment()` default constructor ✓.

### lodestar

`vendor/lodestar/packages/state-transition/src/block/processProposerSlashing.ts:18-56`:

```typescript
export function processProposerSlashing(
  fork: ForkSeq,
  state: CachedBeaconStateAllForks,
  proposerSlashing: phase0.ProposerSlashing,
  verifySignatures = true
): void {
  const proposer = state.validators.getReadonly(proposerSlashing.signedHeader1.message.proposerIndex);
  assertValidProposerSlashing(
    state.config, state.epochCtx.pubkeyCache, state.slot, proposerSlashing, proposer, verifySignatures
  );

  if (fork >= ForkSeq.gloas) {
    const slot = Number(proposerSlashing.signedHeader1.message.slot);
    const proposalEpoch = computeEpochAtSlot(slot);
    const currentEpoch = state.epochCtx.epoch;
    const previousEpoch = currentEpoch - 1;

    const paymentIndex =
      proposalEpoch === currentEpoch
        ? SLOTS_PER_EPOCH + (slot % SLOTS_PER_EPOCH)
        : proposalEpoch === previousEpoch
          ? slot % SLOTS_PER_EPOCH
          : undefined;

    if (paymentIndex !== undefined) {
      (state as CachedBeaconStateGloas).builderPendingPayments.set(
        paymentIndex,
        ssz.gloas.BuilderPendingPayment.defaultViewDU()
      );
    }
  }

  slashValidator(fork, state, proposerSlashing.signedHeader1.message.proposerIndex);
}
```

Order: `assertValidProposerSlashing` (full sig + slot + indices + slashable; signature check gated by `verifySignatures`) → voidance → `slashValidator`. ✓ matches spec. Fork-gated by runtime `fork >= ForkSeq.gloas`. Index formulas match spec ✓. `previousEpoch = currentEpoch - 1` underflows for epoch 0 but Gloas activation is post-Phase0; unreachable on real chains. ✓

### grandine

`vendor/grandine/transition_functions/src/gloas/block_processing.rs:1277-1318`:

```rust
pub fn process_proposer_slashing<P: Preset>(
    config: &Config,
    pubkey_cache: &PubkeyCache,
    state: &mut impl PostGloasBeaconState<P>,
    proposer_slashing: ProposerSlashing,
    verifier: impl Verifier,
    slot_report: impl SlotReport,
) -> Result<()> {
    unphased::validate_proposer_slashing_with_verifier(config, pubkey_cache, state, proposer_slashing, verifier)?;

    // > Remove the BuilderPendingPayment corresponding to this proposal if it is still in the 2-epoch window.
    let slot = proposer_slashing.signed_header_1.message.slot;
    let proposal_epoch = compute_epoch_at_slot::<P>(slot);
    if proposal_epoch == get_current_epoch(state) {
        *state.builder_pending_payments_mut()
            .mod_index_mut(builder_payment_index_for_current_epoch::<P>(slot)) =
            BuilderPendingPayment::default();
    } else if proposal_epoch == get_previous_epoch(state) {
        *state.builder_pending_payments_mut()
            .mod_index_mut(builder_payment_index_for_previous_epoch::<P>(slot)) =
            BuilderPendingPayment::default();
    }

    let index = proposer_slashing.signed_header_1.message.proposer_index;

    slash_validator(config, state, index, None, SlashingKind::Proposer, slot_report)
}
```

Order: `validate_proposer_slashing_with_verifier` (full verification) → voidance → `slash_validator`. ✓ matches spec. Gloas-only function (separate file from earlier forks); `process_operations` dispatches to this at Gloas. Index formulas via dedicated const-fn helpers at `vendor/grandine/helper_functions/src/misc.rs:71-78`:

```rust
pub const fn builder_payment_index_for_current_epoch<P: Preset>(slot: Slot) -> u64 {
    P::SlotsPerEpoch::U64.saturating_add(slot % P::SlotsPerEpoch::U64)
}
pub const fn builder_payment_index_for_previous_epoch<P: Preset>(slot: Slot) -> u64 {
    slot % P::SlotsPerEpoch::U64
}
```

Same helpers used by item #58 / #57 (`process_execution_payload_bid` + `process_builder_pending_payments`) — single source of truth across multiple block-processing call sites.

## Cross-reference table

| Client | `process_proposer_slashing` Gloas location | Current-epoch index (H2) | Previous-epoch index (H3) | No-op for old proposals (H4) | Order: verify → voidance → slash (H5) | Signature-verify position (H7) | Fork-gate idiom (H6) |
|---|---|---|---|---|---|---|---|
| prysm | `proposer_slashing.go:122` + `gloas/proposer_slashing.go:28 RemoveBuilderPendingPayment` | `slotsPerEpoch + slot % slotsPerEpoch` ✓ | `slot % slotsPerEpoch` (when `proposalEpoch+1 == currentEpoch`) ✓ | `return nil` | ✓ spec | inline at `VerifyProposerSlashing` (before voidance) — matches spec | `beaconState.Version() >= version.Gloas` runtime |
| lighthouse | `process_operations.rs:379-433` inline | `E::SlotsPerEpoch::to_usize().safe_add(slot_in_epoch)?` ✓ | `slot_in_epoch` ✓ | `None`, then `if let Some(index)` | ✓ spec | inline at `verify_proposer_slashing` (before voidance) — matches spec | `state.fork_name_unchecked().gloas_enabled()` runtime |
| teku | `AbstractBlockProcessor.java:468 + BlockProcessorGloas.java:320 removeBuilderPendingPayment` | `SLOTS_PER_EPOCH + slot.mod(SLOTS_PER_EPOCH)` ✓ | `slot.mod(SLOTS_PER_EPOCH)` ✓ | `OptionalInt.empty()` | ✓ non-signature spec | **deferred — runs AFTER voidance + slashValidator** (`verifyProposerSlashings` at AbstractBlockProcessor.java:476-480) | virtual-method override (no-op base, Gloas impl) |
| nimbus | `state_transition_block.nim:195` inline `when typeof(state).kind >= ConsensusFork.Gloas` | `SLOTS_PER_EPOCH + (slot mod SLOTS_PER_EPOCH)` ✓ | `slot mod SLOTS_PER_EPOCH` ✓ | implicit no-op (no else branch) | ✓ spec | inline at `check_proposer_slashing` (before voidance) — matches spec | compile-time `when` |
| lodestar | `processProposerSlashing.ts:18` inline | `SLOTS_PER_EPOCH + (slot % SLOTS_PER_EPOCH)` ✓ | `slot % SLOTS_PER_EPOCH` ✓ | `undefined`, then `if (paymentIndex !== undefined)` | ✓ spec | inline at `assertValidProposerSlashing` (before voidance) — matches spec | `fork >= ForkSeq.gloas` runtime |
| grandine | `block_processing.rs:1277` (Gloas-only fn) | `builder_payment_index_for_current_epoch::<P>(slot)` ✓ | `builder_payment_index_for_previous_epoch::<P>(slot)` ✓ | implicit no-op (no else branch) | ✓ spec | inline at `validate_proposer_slashing_with_verifier` (before voidance) — matches spec | Gloas-specific function dispatched by `process_operations` |

All 6 clients match H1–H6 and H8. H7 partial: **teku** defers BLS signature verification to after voidance + slash. Functionally equivalent under all reachable inputs (the whole block-transition rolls back on signature failure).

## Empirical tests

EF spec-test fixtures at `vendor/consensus-specs/tests/.../gloas/operations/proposer_slashing/` cover the Gloas-modified voidance branch. Per-client spec-test wrappers run these and pass cross-client on the published fixture corpus (no observed divergence).

Suggested fuzzing vectors (none presently wired):

- **T1.1 (canonical, current epoch).** Slash a proposer whose `signed_header_1.message.slot` is in the current epoch and whose `builder_pending_payments[SE + slot % SE]` is non-default. Verify all 6 clear the slot.
- **T1.2 (canonical, previous epoch).** Same with `slot` in the previous epoch. Verify all 6 clear `builder_pending_payments[slot % SE]`.
- **T2.1 (no-op for old proposal).** `slot` more than 2 epochs old. Verify all 6 leave `builder_pending_payments` unchanged.
- **T2.2 (idempotency).** Slash with `slot` matching an already-default slot. Verify all 6 do not error (set default to default = no-op).
- **T2.3 (interleaved with churn).** Slash a proposer who is being processed for an unrelated exit churn. Verify the voidance + slash sequence does not corrupt churn state.
- **T2.4 (teku eager-mutate, invalid signature).** Inject a `ProposerSlashing` with valid slot/index/headers-differ/slashable but **invalid signature**. Verify teku rejects the block wholesale (signature check at end) and that the state never observes the voidance + slash mutations.

## Conclusion

All six clients implement the Gloas-new `BuilderPendingPayment` voidance branch in `process_proposer_slashing` consistently and spec-conformantly. Index formulas (`SE + slot%SE` for current epoch, `slot%SE` for previous epoch) are uniform. No-op for old proposals is uniform. Voidance happens before `slash_validator` in all 6.

**Teku** defers BLS signature verification to after voidance + slash as an eager-state-mutate / late-verify-BLS optimization. Functionally equivalent because invalid blocks reject wholesale — no state mutation escapes. Literal-vs-functional deviation worth noting but not a divergence.

**Verdict: impact none.** No divergence. Audit closes.

## Cross-cuts

### With item #57 (`process_builder_pending_payments`)

Item #57 is the epoch-boundary rotation of `state.builder_pending_payments`. This item is the per-block voidance of individual slots. Round-trip cross-cut: the voidance reaches slots within the 2-epoch window, then rotation drops them.

### With item #58 (`process_execution_payload_bid`)

Item #58 writes to `state.builder_pending_payments[SE + bid.slot % SE]` when a bid is accepted. Same index formulas as the voidance branch. Cross-cut on the index helpers (grandine's `builder_payment_index_for_current_epoch` is shared).

### With `process_attester_slashing` Gloas modifications — adjacent untouched

Spec corpus does not (currently) modify `process_attester_slashing` at Gloas. Worth confirming as a separate audit — attester slashing does NOT void builder payments per spec, but cross-checking the surrounding state mutations is worthwhile.

### With item #64 (`upgrade_to_gloas`)

`upgrade_to_gloas` initializes `state.builder_pending_payments` to `2 * SLOTS_PER_EPOCH` default `BuilderPendingPayment()` entries. The voidance branch sets a slot back to the same default. Same value semantics.

### With teku's eager-mutate / late-verify-BLS pattern

Cross-cut: teku uses the same pattern in `processAttesterSlashings` and elsewhere. Worth verifying the rollback path is robust (test T2.4).

## Adjacent untouched

1. **`slash_validator` Gloas modifications** — does the slash mutation interact with `state.builders` (for 0x03 builder credentials)? Verify the slashing path correctly handles builder-credential validators.
2. **`process_attester_slashing` Gloas non-modifications** — confirm no Gloas-new side effect on attester slashing.
3. **`builder_payment_index_for_*` helper functions cross-client** — different clients use different idioms (inline arithmetic vs named const fns); verify byte-equivalence on every (slot, epoch) input.
4. **Teku eager-mutate rollback path** — test T2.4 to verify state observability of failed-signature slashings.
5. **Idempotent voidance** — test T2.2 to verify clearing an already-default slot does not error.
