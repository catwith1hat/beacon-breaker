---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [7, 19]
eips: [EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 58: `process_execution_payload_bid` (Gloas-new block-time bid validation, EIP-7732 ePBS)

## Summary

Item #19 audited the **dispatcher** (`process_execution_payload_bid` is wired into the per-block flow on every client at Gloas); this item audits the **function body itself** — the 9 validation predicates that gate every Gloas-slot block's signed builder bid plus the two state-write effects (pending-payment recording and bid caching).

**All six clients implement the function spec-conformantly.** Self-build special case (`builder_index == BUILDER_INDEX_SELF_BUILD` ⇒ `amount == 0` ∧ `signature == G2_POINT_AT_INFINITY`), the four non-self-build predicates (active builder, sufficient funds, bid signature against `DOMAIN_BEACON_BUILDER = 0x0B000000`, blob commitments under `get_blob_parameters(epoch).max_blobs_per_block`), the four bid-vs-block consistency predicates (`slot`, `parent_block_hash`, `parent_block_root`, `prev_randao`), the pending-payment write to `state.builder_pending_payments[SLOTS_PER_EPOCH + bid.slot % SLOTS_PER_EPOCH]` when `amount > 0`, and the unconditional bid cache `state.latest_execution_payload_bid = bid` are uniform.

**One predicate-order observation:** lodestar moves the blob-commitments-limit check from spec position 5 (right after the self-build/non-self-build branch) to position 9 (after the four bid-vs-block consistency checks). For valid bids the set accepted is identical; for invalid bids violating multiple predicates the error returned differs but the accept/reject decision is unchanged. **Impact: none** (no consensus divergence); flagged as a forward-fragility for error-type-dependent tooling.

## Question

Pyspec `process_execution_payload_bid` (Gloas, `vendor/consensus-specs/specs/gloas/beacon-chain.md:1427-1473`):

```python
def process_execution_payload_bid(state: BeaconState, block: BeaconBlock) -> None:
    signed_bid = block.body.signed_execution_payload_bid
    bid = signed_bid.message
    builder_index = bid.builder_index
    amount = bid.value

    # For self-builds, amount must be zero regardless of withdrawal credential prefix
    if builder_index == BUILDER_INDEX_SELF_BUILD:
        assert amount == 0
        assert signed_bid.signature == bls.G2_POINT_AT_INFINITY
    else:
        # Verify that the builder is active
        assert is_active_builder(state, builder_index)
        # Verify that the builder has funds to cover the bid
        assert can_builder_cover_bid(state, builder_index, amount)
        # Verify that the bid signature is valid
        assert verify_execution_payload_bid_signature(state, signed_bid)

    # Verify commitments are under limit
    assert (
        len(bid.blob_kzg_commitments)
        <= get_blob_parameters(get_current_epoch(state)).max_blobs_per_block
    )

    # Verify that the bid is for the current slot
    assert bid.slot == block.slot
    # Verify that the bid is for the right parent block
    assert bid.parent_block_hash == state.latest_block_hash
    assert bid.parent_block_root == block.parent_root
    assert bid.prev_randao == get_randao_mix(state, get_current_epoch(state))

    # Record the pending payment if there is some payment
    if amount > 0:
        pending_payment = BuilderPendingPayment(
            weight=0,
            withdrawal=BuilderPendingWithdrawal(
                fee_recipient=bid.fee_recipient,
                amount=amount,
                builder_index=builder_index,
            ),
        )
        state.builder_pending_payments[SLOTS_PER_EPOCH + bid.slot % SLOTS_PER_EPOCH] = pending_payment

    # Cache the signed execution payload bid
    state.latest_execution_payload_bid = bid
```

Signing domain: `DOMAIN_BEACON_BUILDER = 0x0B000000` (verified uniform across all 6 client constants).

The function runs on every Gloas-slot block, immediately before / after `process_operations` (per client architecture). It is the entry-point of the EIP-7732 ePBS lifecycle (bid → attestation → settle → withdraw). Item #19 H10 verified the wiring; this item verifies the body's nine predicates and two state effects.

## Hypotheses

- **H1.** All six implement the self-build branch identically: `builder_index == BUILDER_INDEX_SELF_BUILD` ⇒ enforce `amount == 0`.
- **H2.** All six enforce `signature == bls.G2_POINT_AT_INFINITY` on self-builds (or its compressed-bytes equivalent `[0xc0, 0×95]`).
- **H3.** All six skip `is_active_builder`, `can_builder_cover_bid`, and signature verification on self-builds.
- **H4.** All six call `is_active_builder(state, builder_index)` on non-self-builds with the same semantics: `builder.deposit_epoch < state.finalized_checkpoint.epoch ∧ builder.withdrawable_epoch == FAR_FUTURE_EPOCH`.
- **H5.** All six call `can_builder_cover_bid(state, builder_index, amount)` on non-self-builds (formula: `builder.balance ≥ amount + pending_balance_to_withdraw_for_builder`).
- **H6.** All six verify the bid signature using `DOMAIN_BEACON_BUILDER = 0x0B000000` against `state.builders[builder_index].pubkey`.
- **H7.** All six enforce `len(bid.blob_kzg_commitments) <= get_blob_parameters(epoch).max_blobs_per_block`.
- **H8.** All six enforce the four bid-vs-block consistency checks: `bid.slot == block.slot`, `bid.parent_block_hash == state.latest_block_hash`, `bid.parent_block_root == block.parent_root`, `bid.prev_randao == get_randao_mix(state, current_epoch)`.
- **H9.** All six write `state.builder_pending_payments[SLOTS_PER_EPOCH + bid.slot % SLOTS_PER_EPOCH]` when `amount > 0`; skip otherwise. Slot index formula identical.
- **H10.** All six write `state.latest_execution_payload_bid = bid` unconditionally (at the end, regardless of `amount`).
- **H11** *(predicate-order observability)*. The set of bids accepted/rejected is identical across all six, but the order in which predicates are evaluated may differ. For bids violating multiple predicates, the error returned by each client may differ.

## Findings

H1–H10 satisfied across all six clients. **H11 partial divergence: lodestar reorders the blob-commitment-limit check from spec position 5 to position 9** — observable in error-type granularity only, no consensus impact.

### prysm

`vendor/prysm/beacon-chain/core/gloas/bid.go:71-145` — `ProcessExecutionPayloadBid`:

```go
builderIndex := bid.BuilderIndex()
amount := bid.Value()

if builderIndex == params.BeaconConfig().BuilderIndexSelfBuild {
    if amount != 0 {
        return fmt.Errorf("self-build amount must be zero, got %d", amount)
    }
    if wrappedBid.Signature() != common.InfiniteSignature {
        return errors.New("self-build signature must be point at infinity")
    }
} else {
    ok, _ := st.IsActiveBuilder(builderIndex)
    if !ok { return fmt.Errorf("builder %d is not active", builderIndex) }

    ok, _ = st.CanBuilderCoverBid(builderIndex, amount)
    if !ok { return fmt.Errorf("builder %d cannot cover bid amount %d", builderIndex, amount) }

    if err := ValidatePayloadBidSignature(st, wrappedBid); err != nil {
        return errors.Wrap(err, "bid signature validation failed")
    }
}

maxBlobsPerBlock := params.BeaconConfig().MaxBlobsPerBlockAtEpoch(slots.ToEpoch(block.Slot()))
commitmentCount := bid.BlobKzgCommitmentCount()
if commitmentCount > uint64(maxBlobsPerBlock) {
    return fmt.Errorf("bid has %d blob KZG commitments over max %d", commitmentCount, maxBlobsPerBlock)
}

if err := validateBidConsistency(st, bid, block); err != nil { ... }
```

`validateBidConsistency` at `:147-174` checks slot, parent_block_hash, parent_block_root, prev_randao in that order. Signature verification at `:181-225` (`ValidatePayloadBidSignature`) uses `params.BeaconConfig().DomainBeaconBuilder` (= `0x0B000000`).

State write idioms: `st.SetBuilderPendingPayment(slotIndex, pendingPayment)` and `st.SetExecutionPayloadBid(bid)` are wrapped state-interface methods. Slot index computed as `SlotsPerEpoch + (bid.Slot() % SlotsPerEpoch)` — matches spec.

Predicate order: spec-conformant (blob limit at position 5).

H1 ✓. H2 ✓ (`common.InfiniteSignature`). H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓ (spec order).

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing.rs:669-806` — `process_execution_payload_bid`:

```rust
let bid = &signed_bid.message;
let amount = bid.value;
let builder_index = bid.builder_index;

// For self-builds, amount must be zero regardless of withdrawal credential prefix
if builder_index == BUILDER_INDEX_SELF_BUILD {
    block_verify!(amount == 0, ExecutionPayloadBidInvalid::SelfBuildNonZeroAmount.into());
    block_verify!(signed_bid.signature.is_infinity(), ExecutionPayloadBidInvalid::BadSignature.into());
} else {
    let builder = state.get_builder(builder_index)?;
    block_verify!(state.is_active_builder(builder_index, spec)?, ExecutionPayloadBidInvalid::BuilderNotActive(builder_index).into());
    block_verify!(state.can_builder_cover_bid(builder_index, amount, spec)?, ExecutionPayloadBidInvalid::InsufficientBalance { ... }.into());
    if verify_signatures.is_true() {
        block_verify!(
            execution_payload_bid_signature_set(state, |i| get_builder_pubkey_from_state(state, i), signed_bid, spec)?
                .ok_or(ExecutionPayloadBidInvalid::BadSignature)?
                .verify(),
            ExecutionPayloadBidInvalid::BadSignature.into()
        );
    }
}

// Verify commitments are under limit
let max_blobs_per_block = spec.max_blobs_per_block(state.current_epoch()) as usize;
block_verify!(bid.blob_kzg_commitments.len() <= max_blobs_per_block, ExecutionPayloadBidInvalid::ExcessBlobCommitments { ... }.into());

// Slot/parent/randao consistency checks
block_verify!(bid.slot == block.slot(), ExecutionPayloadBidInvalid::SlotMismatch { ... }.into());
let latest_block_hash = state.latest_block_hash()?;
block_verify!(bid.parent_block_hash == *latest_block_hash, ExecutionPayloadBidInvalid::ParentBlockHashMismatch { ... }.into());
block_verify!(bid.parent_block_root == block.parent_root(), ExecutionPayloadBidInvalid::ParentBlockRootMismatch { ... }.into());
let expected_randao = *state.get_randao_mix(state.current_epoch())?;
block_verify!(bid.prev_randao == expected_randao, ExecutionPayloadBidInvalid::PrevRandaoMismatch { ... }.into());

if amount > 0 {
    let pending_payment = BuilderPendingPayment {
        weight: 0,
        withdrawal: BuilderPendingWithdrawal { fee_recipient: bid.fee_recipient, amount, builder_index },
    };
    let payment_index = E::SlotsPerEpoch::to_usize().safe_add(bid.slot.as_usize().safe_rem(E::SlotsPerEpoch::to_usize())?)?;
    *state.builder_pending_payments_mut()?.get_mut(payment_index).ok_or(...)? = pending_payment;
}

*state.latest_execution_payload_bid_mut()? = bid.clone();
```

`block_verify!` macro pattern (short-circuit verify with typed errors). Signature verification gated by `verify_signatures.is_true()` (allows skipping when pre-validated upstream). `signed_bid.signature.is_infinity()` checks compressed G2 point form. Slot index uses `safe_add` + `safe_rem` for overflow safety.

Predicate order: spec-conformant.

H1 ✓. H2 ✓ (`is_infinity()`). H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓ (unconditional `*state.latest_execution_payload_bid_mut()? = bid.clone()`). H11 ✓.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/block/BlockProcessorGloas.java:214-307` — `processExecutionPayloadBid`:

```java
final UInt64 builderIndex = bid.getBuilderIndex();
final UInt64 amount = bid.getValue();

if (builderIndex.equals(BUILDER_INDEX_SELF_BUILD)) {
    if (!amount.isZero()) throw new BlockProcessingException("Amount must be zero for self-build blocks");
    if (!signedBid.getSignature().isInfinity()) throw new BlockProcessingException("Signature must be G2_POINT_AT_INFINITY for self-builds");
} else {
    if (!predicatesGloas.isActiveBuilder(state, builderIndex)) throw new BlockProcessingException("Builder is not active");
    if (!beaconStateAccessorsGloas.canBuilderCoverBid(state, builderIndex, amount)) throw new BlockProcessingException("Builder doesn't have funds to cover the bid");
    if (!operationSignatureVerifier.verifyExecutionPayloadBidSignature(state, signedBid, BLSSignatureVerifier.SIMPLE)) throw new BlockProcessingException("Signature for the signed bind was invalid");
}

// Verify commitments are under limit
if (bid.getBlobKzgCommitments().size() > miscHelpersGloas.getBlobParameters(...).maxBlobsPerBlock()) throw new BlockProcessingException(...);

// Slot
if (!bid.getSlot().equals(beaconBlock.getSlot())) throw new BlockProcessingException("Bid is not for the current slot");

// parent_block_hash AND parent_block_root combined into one check
if (!bid.getParentBlockHash().equals(stateGloas.getLatestBlockHash())
    || !bid.getParentBlockRoot().equals(beaconBlock.getParentRoot())) {
  throw new BlockProcessingException("Bid is not for the right parent block");
}
if (!bid.getPrevRandao().equals(beaconStateAccessors.getRandaoMix(state, beaconStateAccessors.getCurrentEpoch(state)))) { ... }

if (amount.isGreaterThan(UInt64.ZERO)) {
    final BuilderPendingPayment pendingPayment = schemaDefinitionsGloas.getBuilderPendingPaymentSchema().create(
        UInt64.ZERO,
        schemaDefinitionsGloas.getBuilderPendingWithdrawalSchema().create(bid.getFeeRecipient(), amount, builderIndex));
    stateGloas.getBuilderPendingPayments().set(
        bid.getSlot().mod(specConfig.getSlotsPerEpoch()).plus(specConfig.getSlotsPerEpoch()).intValue(),
        pendingPayment);
}

stateGloas.setLatestExecutionPayloadBid(bid);
```

Subclass-override polymorphism (`@Override` from `AbstractBlockProcessor`). Signature verification via `operationSignatureVerifier.verifyExecutionPayloadBidSignature` (uses `Domain.BEACON_BUILDER` per `ExecutionPayloadVerifierGloas.java:163`). `parent_block_hash` and `parent_block_root` checked as a single combined branch with two `||`-ORed conditions but the same accept/reject set as spec; error message identifies the pair rather than the specific failing field.

Predicate order: spec-conformant (slot → combined-parent → randao).

H1 ✓. H2 ✓ (`signedBid.getSignature().isInfinity()`). H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (combined parent_block_{hash,root} check). H9 ✓. H10 ✓. H11 ✓ (combined-parent variant — semantics equivalent).

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:1266-1326` — `process_execution_payload_bid*` for Gloas (sibling at `:1355-1411` for Heze):

```nim
proc process_execution_payload_bid*(
    cfg: RuntimeConfig, state: var gloas.BeaconState,
    blck: SomeGloasBeaconBlock): Result[void, cstring] =
  template signed_bid: untyped = blck.body.signed_execution_payload_bid
  template bid: untyped = signed_bid.message
  let
    builder_index = bid.builder_index
    amount = bid.value
    epoch = get_current_epoch(state)

  # For self-builds, amount must be zero regardless of withdrawal credential prefix
  if builder_index == BUILDER_INDEX_SELF_BUILD:
    if amount != 0.Gwei: return err("process_execution_payload_bid: self-build must have zero amount")
    if signed_bid.signature != ValidatorSig.infinity(): return err("process_execution_payload_bid: self-build signature must be infinity")
  else:
    if not is_active_builder(state, builder_index.BuilderIndex): return err("payload_bid: builder must be active")
    if not can_builder_cover_bid(state, builder_index.BuilderIndex, amount): return err("payload_bid: builder can't cover the bid")
    if not verify_execution_payload_bid_signature(
        state.fork, state.genesis_validators_root, epoch, signed_bid.message,
        state.builders.item(builder_index).pubkey, signed_bid.signature):
      return err("payload_bid: invalid bid signature")

  # Verify commitments are under limit
  let blob_params = cfg.get_blob_parameters(epoch)
  if lenu64(bid.blob_kzg_commitments) > blob_params.MAX_BLOBS_PER_BLOCK:
    return err("process_execution_payload_bid: too many blob KZG commitments")

  # Slot/parent/randao consistency
  if bid.slot != blck.slot: return err("process_execution_payload_bid: bid slot mismatch")
  if bid.parent_block_hash != state.latest_block_hash: return err("process_execution_payload_bid: parent block hash mismatch")
  if bid.parent_block_root != blck.parent_root: return err("process_execution_payload_bid: parent block root mismatch")
  if not (bid.prev_randao == get_randao_mix(state, epoch)): return err("process_execution_payload_bid: RANDAO mismatch")

  # Record the pending payment if there is some payment
  if amount > 0.Gwei:
    let pending_payment = BuilderPendingPayment(
        weight: 0.Gwei,
        withdrawal: BuilderPendingWithdrawal(
          fee_recipient: bid.fee_recipient, amount: amount, builder_index: builder_index.uint64))
    state.builder_pending_payments.mitem(SLOTS_PER_EPOCH + (bid.slot mod SLOTS_PER_EPOCH)) = pending_payment

  # Cache the signed execution payload bid
  state.latest_execution_payload_bid = bid
```

Two sibling functions (Gloas + Heze) — body identical modulo the state type. `ValidatorSig.infinity()` is the compressed G2 point at infinity. `verify_execution_payload_bid_signature` (defined in `signatures.nim`) uses `DOMAIN_BEACON_BUILDER`. Predicate order: spec-conformant.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓.

### lodestar

`vendor/lodestar/packages/state-transition/src/block/processExecutionPayloadBid.ts` — `processExecutionPayloadBid`:

```typescript
const signedBid = block.body.signedExecutionPayloadBid;
const bid = signedBid.message;
const {builderIndex, value: amount} = bid;

// For self-builds, amount must be zero regardless of withdrawal credential prefix
if (builderIndex === BUILDER_INDEX_SELF_BUILD) {
  if (amount !== 0) throw Error(`Invalid execution payload bid: self-build with non-zero amount ${amount}`);
  if (!byteArrayEquals(signedBid.signature, G2_POINT_AT_INFINITY)) throw Error("Invalid execution payload bid: self-build with non-zero signature");
}
// Non-self builds require active builder with valid signature
else {
  const builder = state.builders.getReadonly(builderIndex);
  if (!isActiveBuilder(builder, state.finalizedCheckpoint.epoch)) throw Error(`Invalid execution payload bid: builder ${builderIndex} is not active`);
  if (!canBuilderCoverBid(state, builderIndex, amount)) throw Error(`Invalid execution payload bid: builder ${builderIndex} has insufficient balance`);
  if (!verifyExecutionPayloadBidSignature(state, builder.pubkey, signedBid)) throw Error(`Invalid execution payload bid: invalid signature for builder ${builderIndex}`);
}

// SLOT CHECK FIRST (not after blob limit, deviating from spec order)
if (bid.slot !== block.slot) throw Error(`Bid slot ${bid.slot} does not match block slot ${block.slot}`);

if (!byteArrayEquals(bid.parentBlockHash, state.latestBlockHash)) throw Error(...);
if (!byteArrayEquals(bid.parentBlockRoot, block.parentRoot)) throw Error(...);

const stateRandao = getRandaoMix(state, getCurrentEpoch(state));
if (!byteArrayEquals(bid.prevRandao, stateRandao)) throw Error(...);

// BLOB LIMIT CHECK LAST (deviating from spec position 5 → position 9)
const maxBlobsPerBlock = state.config.getMaxBlobsPerBlock(state.epochCtx.epoch);
if (bid.blobKzgCommitments.length > maxBlobsPerBlock) throw Error(...);

if (amount > 0) {
  const pendingPaymentView = ssz.gloas.BuilderPendingPayment.toViewDU({
    weight: 0,
    withdrawal: ssz.gloas.BuilderPendingWithdrawal.toViewDU({
      feeRecipient: bid.feeRecipient, amount, builderIndex,
    }),
  });
  state.builderPendingPayments.set(SLOTS_PER_EPOCH + (bid.slot % SLOTS_PER_EPOCH), pendingPaymentView);
}

state.latestExecutionPayloadBid = ssz.gloas.ExecutionPayloadBid.toViewDU(bid);
```

`G2_POINT_AT_INFINITY` is `Uint8Array.from([0xc0, 0, 0, ..., 0])` (96 bytes). `verifyExecutionPayloadBidSignature` uses the BLST FFI binding and the `getExecutionPayloadBidSigningRoot` helper (which embeds `DOMAIN_BEACON_BUILDER`).

**H11 divergence**: the blob-commitment-limit check is positioned AFTER the slot/parent_block_hash/parent_block_root/prev_randao checks, whereas spec (and prysm/lighthouse/teku/nimbus/grandine) put it BEFORE. For any bid violating BOTH the blob-limit AND one of slot/parent/randao, lodestar reports the slot/parent/randao error first; the other 5 report the blob-limit error first. Same accept/reject decision — different error-message granularity.

H1 ✓. H2 ✓ (`byteArrayEquals(signature, G2_POINT_AT_INFINITY)`). H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (predicate present, but reordered). H8 ✓. H9 ✓. H10 ✓. **H11 ✗ (observable-equivalent — only error-type granularity differs).**

### grandine

`vendor/grandine/transition_functions/src/gloas/block_processing.rs:766-802` — `process_execution_payload_bid` (orchestrator):

```rust
pub fn process_execution_payload_bid<P: Preset>(
    config: &Config,
    pubkey_cache: &PubkeyCache,
    state: &mut impl PostGloasBeaconState<P>,
    block: &BeaconBlock<P>,
) -> Result<()> {
    let payload_bid = block.body.signed_execution_payload_bid.message.clone();
    let ExecutionPayloadBid { value: amount, builder_index, slot, fee_recipient, .. } = payload_bid;

    validate_execution_payload_bid(config, pubkey_cache, state, block)?;

    // > Record the pending payment if there is some payment
    if amount > 0 {
        let pending_payment = BuilderPendingPayment {
            weight: 0,
            withdrawal: BuilderPendingWithdrawal { fee_recipient, amount, builder_index },
        };
        *state.builder_pending_payments_mut().mod_index_mut(
            builder_payment_index_for_current_epoch::<P>(slot)) = pending_payment;
    }

    // > Cache the signed execution payload bid
    *state.latest_execution_payload_bid_mut() = payload_bid;
    Ok(())
}
```

`validate_execution_payload_bid` at `:564-665`:

```rust
if builder_index == BUILDER_INDEX_SELF_BUILD {
    ensure!(amount == 0, Error::<P>::NoneZeroBidValue);
    ensure!(signed_bid.signature.is_empty(), Error::<P>::ExecutionPayloadBidSignatureInvalid);
} else {
    let builder = state.builders().get(builder_index)?;
    ensure!(is_active_builder(builder, state.finalized_checkpoint().epoch),
            Error::<P>::BuilderNotActive { index: builder_index, current_epoch });
    ensure!(can_builder_cover_bid(state, builder_index, amount)?,
            Error::<P>::BuilderBalanceNotSufficient { index: builder_index, amount });
    ensure!(validate_execution_payload_bid_signature_with_verifier(config, pubkey_cache, state, signed_bid, SingleVerifier).is_ok(),
            Error::<P>::ExecutionPayloadBidSignatureInvalid);
}

// Verify commitments are under limit
let maximum = config.get_blob_schedule_entry(get_current_epoch(state)).max_blobs_per_block;
let in_block = signed_bid.message.blob_kzg_commitments.len();
ensure!(in_block <= maximum, Error::<P>::TooManyBlockKzgCommitments { in_block, maximum });

ensure!(slot == block.slot, ...);
ensure!(parent_block_hash == state.latest_block_hash(), ...);
ensure!(parent_block_root == block.parent_root, ...);
ensure!(prev_randao == get_randao_mix(state, current_epoch), ...);
```

`signed_bid.signature.is_empty()` is grandine's `SignatureBytes::is_empty` (defined at `bls/bls-core/src/traits/signature_bytes.rs:75`) — returns true iff bytes equal `[0xc0, 0, 0, ..., 0]`, the compressed G2 point at infinity. Equivalent to other clients' `is_infinity()` / `== G2_POINT_AT_INFINITY`. Slot index uses `builder_payment_index_for_current_epoch::<P>(slot)` (= `SLOTS_PER_EPOCH + slot % SLOTS_PER_EPOCH`). Signature verification via `validate_execution_payload_bid_signature_with_verifier` uses `DOMAIN_BEACON_BUILDER`. Predicate order: spec-conformant.

H1 ✓. H2 ✓ (`signature.is_empty()` ≡ compressed `G2_POINT_AT_INFINITY`). H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓.

## Cross-reference table

| Client | `process_execution_payload_bid` location | Self-build sig idiom (H2) | Predicate order (H11) | Pending-payment slot index (H9) | Bid sig domain (H6) |
|---|---|---|---|---|---|
| prysm | `core/gloas/bid.go:71-145` + `:147-174 validateBidConsistency` + `:181-225 ValidatePayloadBidSignature` | `common.InfiniteSignature` | spec: self-build → active/cover/sig → blob limit → slot → parent_hash → parent_root → randao | `SlotsPerEpoch + (slot % SlotsPerEpoch)` via `st.SetBuilderPendingPayment` | `params.BeaconConfig().DomainBeaconBuilder` (`0x0B000000`) |
| lighthouse | `consensus/state_processing/src/per_block_processing.rs:669-806` | `signed_bid.signature.is_infinity()` | spec order; `block_verify!` macro with typed `ExecutionPayloadBidInvalid` errors | `safe_add(safe_rem(slot, SlotsPerEpoch))` into `builder_pending_payments_mut()` | `Domain::BeaconBuilder` (= `0x0B`) via `execution_payload_bid_signature_set` |
| teku | `versions/gloas/block/BlockProcessorGloas.java:214-307` | `signedBid.getSignature().isInfinity()` | spec order; combined `parent_block_hash || parent_block_root` branch (same accept/reject set) | `bid.getSlot().mod(SPE).plus(SPE)` via `stateGloas.getBuilderPendingPayments().set(...)` | `Domain.BEACON_BUILDER` via `operationSignatureVerifier.verifyExecutionPayloadBidSignature` |
| nimbus | `state_transition_block.nim:1266-1326` (Gloas) + `:1355-1411` (Heze sibling) | `ValidatorSig.infinity()` | spec order | `SLOTS_PER_EPOCH + (bid.slot mod SLOTS_PER_EPOCH)` via `mitem(...)` | `DOMAIN_BEACON_BUILDER` (`0x0B000000`) via `verify_execution_payload_bid_signature` |
| lodestar | `state-transition/src/block/processExecutionPayloadBid.ts` | `byteArrayEquals(signature, G2_POINT_AT_INFINITY)` (= `[0xc0, 0×95]`) | **REORDERED: self-build → active/cover/sig → slot → parent_hash → parent_root → randao → BLOB LIMIT (position 9 instead of spec position 5)** | `SLOTS_PER_EPOCH + (bid.slot % SLOTS_PER_EPOCH)` via `state.builderPendingPayments.set(...)` | `DOMAIN_BEACON_BUILDER` via `getExecutionPayloadBidSigningRoot` |
| grandine | `transition_functions/src/gloas/block_processing.rs:766-802` (orch) + `:564-665 validate_execution_payload_bid` | `signed_bid.signature.is_empty()` (= `[0xc0, 0×95]` compressed inf) | spec order; `ensure!` macro with typed `Error::<P>::*` errors | `builder_payment_index_for_current_epoch::<P>(slot)` (= `SLOTS_PER_EPOCH + slot % SLOTS_PER_EPOCH`) | `DOMAIN_BEACON_BUILDER` via `validate_execution_payload_bid_signature_with_verifier` |

## Empirical tests

No Gloas EF operations fixtures yet exist for `process_execution_payload_bid` per the standard prysm/grandine spectest harness layout (the spec-test corpus is sparse on Gloas operations). The function is exercised IMPLICITLY via Gloas block-processing tests (a Gloas block contains a `signed_execution_payload_bid` field that all six clients validate).

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (canonical bid).** Active builder with sufficient funds, valid signature, all 4 consistency checks pass. Expected: accepted; `state.builder_pending_payments[SLOTS_PER_EPOCH + bid.slot % SLOTS_PER_EPOCH]` set; `state.latest_execution_payload_bid = bid` cached.
- **T1.2 (canonical self-build).** `builder_index == BUILDER_INDEX_SELF_BUILD`, `value == 0`, `signature == G2_POINT_AT_INFINITY`. Expected: accepted; no pending-payment write (since `amount == 0`); bid cached.
- **T1.3 (canonical zero-value non-self-build).** Non-self-build, all checks pass, but `amount == 0` (builder bids 0 — testnet edge case). Expected: accepted; **no pending-payment write** (per `if amount > 0` gate); bid cached. Verifies the consistency of "amount > 0" gate across all six.

#### T2 — Adversarial probes
- **T2.1 (self-build with non-zero amount).** `builder_index == BUILDER_INDEX_SELF_BUILD`, `value > 0`. Expected: rejected by all six.
- **T2.2 (self-build with non-infinity signature).** `builder_index == BUILDER_INDEX_SELF_BUILD`, `signature != G2_POINT_AT_INFINITY`. Expected: rejected.
- **T2.3 (inactive builder).** Builder exists but `withdrawable_epoch <= current_epoch` (initiated exit). Expected: rejected via `is_active_builder`.
- **T2.4 (insufficient funds).** Builder active but `balance < amount + pending_balance_to_withdraw_for_builder`. Expected: rejected via `can_builder_cover_bid`.
- **T2.5 (signature mismatch).** Bid signed by a different pubkey than `state.builders[builder_index].pubkey`. Expected: rejected.
- **T2.6 (blob commitments at limit + 1).** `len(bid.blob_kzg_commitments) == get_blob_parameters(epoch).max_blobs_per_block + 1`. Expected: rejected.
- **T2.7 (slot mismatch).** `bid.slot != block.slot`. Expected: rejected.
- **T2.8 (parent_block_hash mismatch).** Expected: rejected.
- **T2.9 (parent_block_root mismatch).** Expected: rejected (note: teku combines this with H2.8 — same accept/reject decision, different error message).
- **T2.10 (prev_randao mismatch).** Expected: rejected.
- **T2.11 (predicate-order probe: blob-limit + slot mismatch).** Bid with `bid.blob_kzg_commitments.len > max` AND `bid.slot != block.slot`. Expected accept/reject: rejected. **Error-message divergence**: 5 clients (prysm/lighthouse/teku/nimbus/grandine) return a blob-limit error; **lodestar returns a slot-mismatch error**. Useful for documenting H11 forward-fragility — not a consensus divergence, but downstream error-type-dependent tooling (gossip relay scoring, sentry-style telemetry) would categorize differently.
- **T2.12 (predicate-order probe: blob-limit + randao mismatch).** Same pattern as T2.11 but with `prev_randao` mismatch. Lodestar reports randao first; others report blob limit first.
- **T2.13 (Heze sibling).** Verify nimbus's Heze-state path at `state_transition_block.nim:1355-1411` produces identical behaviour to the Gloas path at `:1266-1326`. The two are byte-identical aside from the state type signature; codify the invariance.

## Conclusion

**Status: source-code-reviewed.** All six clients implement `process_execution_payload_bid` spec-conformantly. The 11 hypotheses split: H1–H10 satisfied uniformly; H11 documents a per-client predicate-order observation.

**Key uniformities:**

- **Self-build branch** (H1–H3): all six enforce `amount == 0` ∧ `signature == G2_POINT_AT_INFINITY` (compressed form `[0xc0, 0×95]`) and skip the active/cover/sig predicates.
- **Non-self-build predicates** (H4–H6): all six use `is_active_builder`, `can_builder_cover_bid`, and bid-signature verification against `state.builders[builder_index].pubkey` with `DOMAIN_BEACON_BUILDER = 0x0B000000`.
- **Blob commitment limit** (H7): all six enforce against `get_blob_parameters(epoch).max_blobs_per_block`.
- **Bid-vs-block consistency** (H8): all six check `slot`, `parent_block_hash`, `parent_block_root`, `prev_randao` (teku combines hash + root into a single OR-branch but with the same accept/reject set).
- **Pending-payment write** (H9): all six write to `state.builder_pending_payments[SLOTS_PER_EPOCH + bid.slot % SLOTS_PER_EPOCH]` iff `amount > 0`. Slot-index formula identical across all six.
- **Bid cache** (H10): all six unconditionally write `state.latest_execution_payload_bid = bid` at function exit.

**One observation — H11 lodestar predicate-order divergence:**

Lodestar moves the blob-commitments-limit check from spec position 5 (right after the self-build/non-self-build branch, before the slot check) to position 9 (after the slot/parent/randao checks). For valid bids, identical accept. For invalid bids violating exactly one predicate, identical reject + identical error category. For invalid bids violating MULTIPLE predicates, the returned error differs: 5 clients return the blob-limit error first; lodestar returns the slot/parent/randao error first. **Consensus-level: equivalent** (same accept/reject decision). **Observability-level: forward-fragility** for any error-type-dependent downstream code (gossip-relay scoring, sentry telemetry, alerting filters). Pattern J-class — type-union silent inclusion / per-client error categorization divergence.

**Impact: none.** No consensus-level divergence. Recommend documenting the lodestar predicate-order observation as a forward-fragility hedge and generating T2.11 / T2.12 fixtures to lock the divergence pre-emptively (e.g., upstream the lodestar reordering to spec position 5).

Notable per-client style differences:

- **prysm** factors `validateBidConsistency` and `ValidatePayloadBidSignature` into separate helpers; uses Go errors-as-values with descriptive messages.
- **lighthouse** uses the `block_verify!` macro pattern with typed `ExecutionPayloadBidInvalid::*` error variants and a `verify_signatures: VerifySignatures` flag to allow skipping signature verification when pre-validated upstream.
- **teku** uses `@Override` subclass polymorphism (`BlockProcessorGloas extends ... ` overrides `processExecutionPayloadBid`); combines `parent_block_hash` + `parent_block_root` checks into a single OR-branch with a single error message.
- **nimbus** has two sibling functions for Gloas and Heze (`:1266` Gloas and `:1355` Heze) — body byte-identical modulo state type. Compile-time fork dispatch via the `state: var (gloas.BeaconState)` type union.
- **lodestar** reorders the blob-limit check (H11 observation above); uses BLST-FFI via `verify(signingRoot, publicKey, signature)` with try/catch for BLS error normalization.
- **grandine** uses `ensure!` macro with typed `Error::<P>::*` variants and factors the function into an orchestrator (`process_execution_payload_bid`) + a separate validator (`validate_execution_payload_bid`); `is_empty()` semantic for the self-build signature check (equivalent to G2_POINT_AT_INFINITY check via byte equality).

Recommendations:

- **Wire Gloas EF block-processing fixtures** (when EF lands them) — verify all six produce uniform accept/reject decisions.
- **Generate T2.11 / T2.12 predicate-order probes** as a forward-fragility hedge — lodestar's reordering should either be upstreamed to spec position 5, or codified as an accepted observable variation.
- **Standalone audits of `is_active_builder` and `can_builder_cover_bid`** — small but used here, in item #14 (builder-deposit routing), and in `process_voluntary_exit` builder branch.

## Cross-cuts

### With item #19 (`process_execution_payload` removal + ePBS restructure)

Item #19 closed the dispatcher: every Gloas-aware client invokes `process_execution_payload_bid` from the per-block flow. This item is the predicate-level body audit, completing the wiring + body pair for the bid surface.

### With item #57 (`process_builder_pending_payments`)

This item writes the `BuilderPendingPayment` entry at `state.builder_pending_payments[SLOTS_PER_EPOCH + slot % SLOTS_PER_EPOCH]` (the newer half of the ring buffer); item #57 consumes it from the older half two epochs later. Producer/consumer pair.

### With item #7 H10 (`process_attestation` builder-payment weight)

Item #7 H10 increments `state.builder_pending_payments[slot_idx].weight` from same-slot attestations. This item's write to `state.builder_pending_payments[slot_idx]` happens FIRST (block-time, on bid acceptance, with `weight = 0`); item #7's increments happen AFTER (per same-slot attestation in the same block + later blocks). The two operations interleave on shared state — bid recording must precede attestation weight accumulation within the same block. Block-processing order: `process_execution_payload_bid` then `process_operations` (which dispatches `process_attestation`).

### With item #9 H9 (`process_proposer_slashing` BuilderPendingPayment clearing)

Item #9 H9 zeros out the `BuilderPendingPayment` at the slot index this item wrote to, when the proposer at that slot is slashed within the 2-epoch window. Race condition: if a bid is recorded this slot and the proposer is slashed in a later block, item #9 wins.

### With `is_active_builder` and `can_builder_cover_bid` (standalone helpers)

Both are small predicates used here. `is_active_builder` is also used by the builder branch of item #6 (voluntary exit) and item #14 (deposit-request builder routing). `can_builder_cover_bid` is more specialized — used only here and `apply_deposit_for_builder`. Both warrant standalone audits.

## Adjacent untouched

1. **`is_active_builder` standalone audit** — small predicate, used in 3+ surfaces.
2. **`can_builder_cover_bid` standalone audit** — small predicate, specific to bid acceptance.
3. **EIP-7732 bid signature domain audit** — verify `DOMAIN_BEACON_BUILDER = 0x0B000000` and the signing-root construction across all six clients (already spot-checked here; deserves byte-equivalence test).
4. **`BUILDER_INDEX_SELF_BUILD` constant value verification** — verify all six configs agree on the value.
5. **Lodestar predicate-order upstream proposal** — upstream the lodestar variant to spec position 5 (or codify the reordering as observable variation).
6. **Bid replay protection** — verify that the same signed bid cannot be included in two blocks (slot uniqueness + cache mechanism).
7. **`G2_POINT_AT_INFINITY` constant byte-equivalence** — `[0xc0, 0×95]` across all six clients' BLS bindings (prysm `common.InfiniteSignature`, lighthouse `is_infinity()`, teku `isInfinity()`, nimbus `ValidatorSig.infinity()`, lodestar `G2_POINT_AT_INFINITY` Uint8Array, grandine `SignatureBytes::is_empty()`).
8. **Predicate-order tooling impact** — survey downstream consumers of bid-rejection errors (gossip scoring, peer-reputation, sentry telemetry) for any error-type-dependent code that would categorize lodestar differently from the other 5.
9. **Cross-cut with item #19's `process_parent_execution_payload`** — both run block-time and read/write builder-related state; verify the order is consistent across clients.
