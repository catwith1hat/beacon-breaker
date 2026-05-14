---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [19, 58]
eips: [EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 59: `verify_execution_payload_envelope` + `on_execution_payload_envelope` (Gloas fork-choice envelope verification, EIP-7732 ePBS)

## Summary

Item #19 verified the wiring (every client has `verify_execution_payload_envelope` and an `on_execution_payload_envelope` analog); this item audits the **13 spec assertions** inside the verification function and the **store-side handler** that drives it.

**All six clients implement spec-equivalent behaviour on canonical (signed-by-honest-builder) envelopes.** All six verify the BLS signature against `state.latest_execution_payload_bid.builder_index`'s pubkey under `DOMAIN_BEACON_BUILDER = 0x0B000000` (or, for self-build envelopes, the proposer's pubkey). All six verify the 4 bid-consistency fields (builder_index, prev_randao, gas_limit, block_hash, execution_requests_root) and the 4 payload-consistency fields (slot, parent_hash, timestamp, withdrawals_root).

**Coverage observation on prysm:** the explicit `envelope.beacon_block_root == hash_tree_root(header)` and `envelope.parent_beacon_block_root == state.latest_block_header.parent_root` checks from spec are **not present** in prysm's `validatePayloadConsistency`. The other 5 clients have both. The omitted checks are defense-in-depth (both fields are part of the signed envelope, so any tampering invalidates the signature; the binding to the prestate is also implicit in prysm's `getPayloadEnvelopePrestate(envelope.BeaconBlockRoot())` lookup). **No mainnet-reachable consensus divergence**, but the omitted explicit asserts are a forward-fragility class.

**Impact: none.**

## Question

Pyspec `verify_execution_payload_envelope` (Gloas, `vendor/consensus-specs/specs/gloas/fork-choice.md:790-834`):

```python
def verify_execution_payload_envelope(
    state: BeaconState,
    signed_envelope: SignedExecutionPayloadEnvelope,
    execution_engine: ExecutionEngine,
) -> None:
    envelope = signed_envelope.message
    payload = envelope.payload

    # Verify signature
    assert verify_execution_payload_envelope_signature(state, signed_envelope)

    # Verify consistency with the beacon block
    header = copy(state.latest_block_header)
    header.state_root = hash_tree_root(state)
    assert envelope.beacon_block_root == hash_tree_root(header)
    assert envelope.parent_beacon_block_root == state.latest_block_header.parent_root

    # Verify consistency with the committed bid
    bid = state.latest_execution_payload_bid
    assert envelope.builder_index == bid.builder_index
    assert payload.prev_randao == bid.prev_randao
    assert payload.gas_limit == bid.gas_limit
    assert payload.block_hash == bid.block_hash
    assert hash_tree_root(envelope.execution_requests) == bid.execution_requests_root

    # Verify the execution payload is valid
    assert payload.slot_number == state.slot
    assert payload.parent_hash == state.latest_block_hash
    assert payload.timestamp == compute_time_at_slot(state, state.slot)
    assert hash_tree_root(payload.withdrawals) == hash_tree_root(state.payload_expected_withdrawals)
    assert execution_engine.verify_and_notify_new_payload(NewPayloadRequest(
        execution_payload=payload,
        versioned_hashes=[kzg_commitment_to_versioned_hash(c) for c in bid.blob_kzg_commitments],
        parent_beacon_block_root=envelope.parent_beacon_block_root,
        execution_requests=envelope.execution_requests,
    ))
```

Pyspec `verify_execution_payload_envelope_signature` (`:771-787`):

```python
def verify_execution_payload_envelope_signature(state, signed_envelope) -> bool:
    builder_index = signed_envelope.message.builder_index
    if builder_index == BUILDER_INDEX_SELF_BUILD:
        validator_index = state.latest_block_header.proposer_index
        pubkey = state.validators[validator_index].pubkey
    else:
        pubkey = state.builders[builder_index].pubkey
    signing_root = compute_signing_root(signed_envelope.message, get_domain(state, DOMAIN_BEACON_BUILDER))
    return bls.Verify(pubkey, signing_root, signed_envelope.signature)
```

Pyspec `on_execution_payload_envelope` handler (`:922-948`):

```python
def on_execution_payload_envelope(store, signed_envelope) -> None:
    envelope = signed_envelope.message
    assert envelope.beacon_block_root in store.block_states
    assert is_data_available(envelope.beacon_block_root)
    state = store.block_states[envelope.beacon_block_root]
    verify_execution_payload_envelope(state, signed_envelope, EXECUTION_ENGINE)
    store.payloads[envelope.beacon_block_root] = envelope
```

## Hypotheses

- **H1.** All six implement the self-build / non-self-build pubkey lookup identically: `BUILDER_INDEX_SELF_BUILD` → `state.validators[state.latest_block_header.proposer_index].pubkey`; else → `state.builders[builder_index].pubkey`.
- **H2.** All six use `DOMAIN_BEACON_BUILDER = 0x0B000000` for the envelope signature domain (same as item #58 bid signature).
- **H3.** All six verify `envelope.beacon_block_root == hash_tree_root(latest_block_header with state_root filled in)`.
- **H4.** All six verify `envelope.parent_beacon_block_root == state.latest_block_header.parent_root`.
- **H5.** All six verify the 5 bid-consistency fields: `builder_index`, `prev_randao`, `gas_limit`, `block_hash`, `execution_requests_root` (where the envelope side uses `hash_tree_root(envelope.execution_requests)` and the bid side uses `bid.execution_requests_root`).
- **H6.** All six verify the 4 payload-consistency fields: `slot`, `parent_hash`, `timestamp`, `withdrawals_root` (= `hash_tree_root(payload.withdrawals) == hash_tree_root(state.payload_expected_withdrawals)`).
- **H7.** All six implement an `on_execution_payload_envelope`-equivalent handler that (a) checks `envelope.beacon_block_root` is known, (b) checks `is_data_available`, (c) fetches the state, (d) calls `verify_execution_payload_envelope`, (e) stores the payload.
- **H8.** All six delegate the EL execution (`execution_engine.verify_and_notify_new_payload`) to a separate code path — the spec inlines it inside `verify_execution_payload_envelope` but per-client architectures pull it out for parallelism with state-side checks.
- **H9** *(predicate coverage)*. All six explicitly include the `envelope.beacon_block_root` and `envelope.parent_beacon_block_root` checks. (Forward-fragility hedge — both are defense-in-depth checks redundant with signature verification, so omitting them is observable-equivalent on canonical traffic, but the explicit asserts make the verification self-contained.)

## Findings

H1, H2, H5, H6, H7, H8 satisfied uniformly. **H9 partial: prysm's `validatePayloadConsistency` omits the explicit `envelope.beacon_block_root` and `envelope.parent_beacon_block_root` checks** that the other 5 implement explicitly. Both omitted checks are defense-in-depth (envelope.signature is over the full envelope including these fields, and prysm's prestate lookup is keyed by `envelope.BeaconBlockRoot()` so the binding is implicit). **No consensus divergence on canonical traffic.** H3, H4 explicit-coverage status: prysm ✗, others ✓.

### prysm

`vendor/prysm/beacon-chain/core/gloas/payload.go:66-81 VerifyExecutionPayloadEnvelope` (orchestrator) → `:181-225 ExecutionPayloadEnvelopeSignatureBatch` (signature) + `:107-180 validatePayloadConsistency` (consistency checks).

```go
func VerifyExecutionPayloadEnvelope(ctx, st, signedEnvelope) error {
    if err := verifyExecutionPayloadEnvelopeSignature(st, signedEnvelope); err != nil {
        return errors.Wrap(err, "signature verification failed")
    }
    envelope, _ := signedEnvelope.Envelope()
    return validatePayloadConsistency(ctx, st, envelope)
}

func validatePayloadConsistency(ctx, st, envelope) error {
    if envelope.Slot() != st.Slot() { ... }
    latestBid, _ := st.LatestExecutionPayloadBid()
    if envelope.BuilderIndex() != latestBid.BuilderIndex() { ... }
    if executionRequestsRoot != bidExecutionRequestsRoot { ... }
    payload := envelope.Execution()
    if !bytes.Equal(payload.PrevRandao(), latestBid.PrevRandao()[:]) { ... }
    if !st.WithdrawalsMatchPayloadExpected(withdrawals) { ... }
    if latestBid.GasLimit() != payload.GasLimit() { ... }
    if !bytes.Equal(latestBid.BlockHash()[:], payload.BlockHash()) { ... }
    if !bytes.Equal(payload.ParentHash(), latestBlockHash[:]) { ... }
    if payload.Timestamp() != uint64(t.Unix()) { ... }
    return nil
}
```

Signature path: `ExecutionPayloadEnvelopeSignatureBatch` (lines 181-225) builds a BLS `SignatureBatch` for deferred batch verification using `params.BeaconConfig().DomainBeaconBuilder` (= `0x0B000000`). `envelopePublicKey(st, builderIdx)` resolves the self-build (`state.validators[proposer_index].pubkey`) vs non-self-build (`state.builders[builderIdx].pubkey`) case (verified at `:228-280`).

**Coverage gap (H9 ✗ for prysm)**: no `envelope.BeaconBlockRoot() == hash_tree_root(headerWithStateRoot)` check; no `envelope.ParentBeaconBlockRoot() == state.latest_block_header.parent_root` check. These spec assertions are omitted. Defense-in-depth via:
- Signature verification — `envelope.beacon_block_root` is part of the SignedExecutionPayloadEnvelope SSZ tree, so the signature commits to it. A builder tampering with the field invalidates the signature.
- `getPayloadEnvelopePrestate(envelope.BeaconBlockRoot())` lookup at `blockchain/receive_execution_payload_envelope.go:60` — the state used for verification is selected by the envelope's beacon_block_root; if the lookup fails (unknown root), prysm rejects at the store-level pre-check.

The `on_execution_payload_envelope` handler is `vendor/prysm/beacon-chain/blockchain/receive_execution_payload_envelope.go:47-127`. It runs `g.Go(VerifyExecutionPayloadEnvelope)` and `g.Go(validateExecutionOnEnvelope)` in parallel (CL state-side checks + EL execution), then checks data availability via `s.areDataColumnsAvailable(ctx, root, envelope.Slot())` and persists via `s.savePostPayload` + `s.InsertPayload`.

H1 ✓. H2 ✓ (`DomainBeaconBuilder`). H3 ✗ (no explicit check). H4 ✗ (no explicit check). H5 ✓. H6 ✓. H7 ✓ (handler at `receive_execution_payload_envelope.go:47-127`). H8 ✓ (parallel `g.Go`). **H9 partial — 2 checks missing**.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/envelope_processing.rs:105-234` — `verify_execution_payload_envelope`:

```rust
pub fn verify_execution_payload_envelope<E: EthSpec>(
    state: &BeaconState<E>,
    signed_envelope: &SignedExecutionPayloadEnvelope<E>,
    verify_signatures: VerifySignatures,
    block_state_root: Hash256,
    spec: &ChainSpec,
) -> Result<(), EnvelopeProcessingError> {
    if verify_signatures.is_true() && !signed_envelope.verify_signature_with_state(state, spec)? {
        return Err(EnvelopeProcessingError::BadSignature);
    }
    let envelope = &signed_envelope.message;
    let payload = &envelope.payload;

    // Verify consistency with the beacon block.
    let mut header = state.latest_block_header().clone();
    if header.state_root == Hash256::default() {
        header.state_root = block_state_root;
    }
    let latest_block_header_root = header.tree_hash_root();
    envelope_verify!(envelope.beacon_block_root == latest_block_header_root, ...);
    envelope_verify!(envelope.parent_beacon_block_root == state.latest_block_header().parent_root, ...);
    envelope_verify!(envelope.slot() == state.slot(), ...);

    // Verify consistency with the committed bid
    let committed_bid = state.latest_execution_payload_bid()?;
    envelope_verify!(envelope.builder_index == committed_bid.builder_index, ...);
    envelope_verify!(committed_bid.prev_randao == payload.prev_randao, ...);

    // Verify consistency with expected withdrawals
    envelope_verify!(
        payload.withdrawals.len() == state.payload_expected_withdrawals()?.len()
            && payload.withdrawals.iter().eq(state.payload_expected_withdrawals()?.iter()),
        ...
    );

    envelope_verify!(committed_bid.gas_limit == payload.gas_limit, ...);
    envelope_verify!(committed_bid.block_hash == payload.block_hash, ...);
    envelope_verify!(payload.parent_hash == *state.latest_block_hash()?, ...);

    let state_timestamp = compute_timestamp_at_slot(state, state.slot(), spec)?;
    envelope_verify!(payload.timestamp == state_timestamp, ...);

    let execution_requests_root = envelope.execution_requests.tree_hash_root();
    envelope_verify!(execution_requests_root == committed_bid.execution_requests_root, ...);

    // TODO(gloas): newPayload happens here in the spec, ensure we wire that up correctly
    Ok(())
}
```

All 12 spec checks (except EL execute, which is the `TODO` at line 231 — handled externally). Withdrawals comparison uses **element-wise iterator equality** rather than hash-tree-root (line 173-181) — observable-equivalent (same equality semantics) but faster on the canonical case (avoids both Merkle computations).

Signature verification via `verify_signature_with_state` (defined at `consensus/types/src/execution/signed_execution_payload_envelope.rs`). Per-client `VerifySignatures` flag allows skipping the signature check when pre-validated upstream (e.g., gossip already verified).

The `on_execution_payload_envelope` analog lives at `vendor/lighthouse/beacon_node/beacon_chain/src/payload_envelope_verification/execution_pending_envelope.rs`; the verify-call site in production is wired through fork-choice machinery.

H1 ✓ (via `verify_signature_with_state`). H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (`execution_pending_envelope.rs`). H8 ✓ (TODO + external EL). H9 ✓ (all 12 explicit).

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/execution/ExecutionPayloadVerifierGloas.java:61-145 verifyExecutionPayloadEnvelope`:

```java
public void verifyExecutionPayloadEnvelope(...) throws ExecutionPayloadVerificationException {
    final ExecutionPayloadEnvelope envelope = signedEnvelope.getMessage();
    final ExecutionPayload payload = envelope.getPayload();

    // Verify signature
    if (!verifyExecutionPayloadEnvelopeSignature(state, signedEnvelope, signatureVerifier)) { throw ...; }

    // Verify consistency with the beacon block
    if (!envelope.getBeaconBlockRoot().equals(BeaconBlockHeader.fromState(state).hashTreeRoot())) { throw ...; }
    if (!envelope.getParentBeaconBlockRoot().equals(state.getLatestBlockHeader().getParentRoot())) { throw ...; }
    if (!envelope.getSlot().equals(state.getSlot())) { throw ...; }

    // Verify consistency with the committed bid
    final ExecutionPayloadBid committedBid = stateGloas.getLatestExecutionPayloadBid();
    if (!envelope.getBuilderIndex().equals(committedBid.getBuilderIndex())) { throw ...; }
    if (!envelope.getPayload().getPrevRandao().equals(committedBid.getPrevRandao())) { throw ...; }
    if (!committedBid.getGasLimit().equals(payload.getGasLimit())) { throw ...; }
    if (!committedBid.getBlockHash().equals(payload.getBlockHash())) { throw ...; }
    if (!committedBid.getExecutionRequestsRoot().equals(envelope.getExecutionRequests().hashTreeRoot())) { throw ...; }

    // Verify the execution payload is valid
    if (!payload.getParentHash().equals(stateGloas.getLatestBlockHash())) { throw ...; }
    if (!payload.getTimestamp().equals(miscHelpers.computeTimeAtSlot(state.getGenesisTime(), state.getSlot()))) { throw ...; }
    if (!ExecutionPayloadCapella.required(payload).getWithdrawals().hashTreeRoot()
            .equals(stateGloas.getPayloadExpectedWithdrawals().hashTreeRoot())) { throw ...; }

    if (payloadExecutor.isPresent()) {
      final NewPayloadRequest payloadToExecute = computeNewPayloadRequest(envelope, committedBid.getBlobKzgCommitments());
      final boolean optimisticallyAccept = payloadExecutor.get().optimisticallyExecute(Optional.empty(), payloadToExecute);
      if (!optimisticallyAccept) { throw ...; }
    }
}

public boolean verifyExecutionPayloadEnvelopeSignature(state, signedEnvelope, signatureVerifier) {
    final UInt64 builderIndex = signedEnvelope.getMessage().getBuilderIndex();
    final BLSPublicKey pubkey;
    if (builderIndex.equals(BUILDER_INDEX_SELF_BUILD)) {
      final UInt64 validatorIndex = state.getLatestBlockHeader().getProposerIndex();
      pubkey = beaconStateAccessors.getValidatorPubKey(state, validatorIndex).orElseThrow();
    } else {
      pubkey = beaconStateAccessors.getBuilderPubKey(state, builderIndex).orElseThrow();
    }
    final Bytes32 domain = beaconStateAccessors.getDomain(state.getForkInfo(), Domain.BEACON_BUILDER, miscHelpers.computeEpochAtSlot(state.getSlot()));
    final Bytes signingRoot = miscHelpers.computeSigningRoot(signedEnvelope.getMessage(), domain);
    return signatureVerifier.verify(pubkey, signingRoot, signedEnvelope.getSignature());
}
```

All 13 spec checks present. EL execute is conditional on `payloadExecutor.isPresent()` — when present, runs INLINE inside the verify function (line 135-144); when absent, deferred. Uses `BeaconBlockHeader.fromState(state).hashTreeRoot()` for the header-root computation (line 77).

Predicate order: spec-conformant.

H1 ✓. H2 ✓ (`Domain.BEACON_BUILDER`). H3 ✓ (line 77). H4 ✓ (line 81). H5 ✓. H6 ✓. H7 ✓ (handler in `ethereum/statetransition/.../forkchoice/ForkChoice.java`). H8 ✓ (inline conditional). H9 ✓.

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:1833-1899 verify_execution_payload_envelope*`:

```nim
proc verify_execution_payload_envelope*(
    timeParams: TimeParams, fork: Fork,
    state: gloas.HashedBeaconState | heze.HashedBeaconState,
    signed_envelope: SignedExecutionPayloadEnvelope,
    genesis_validators_root: Eth2Digest): Result[void, cstring] =
  template envelope: auto = signed_envelope.message
  template payload: auto = envelope.payload
  template bid: auto = state.data.latest_execution_payload_bid

  # Resolve builder public key
  let builderIndex = envelope.builder_index
  let pubkey =
    if builderIndex == BUILDER_INDEX_SELF_BUILD:
      let proposerIndex = state.data.latest_block_header.proposer_index
      if proposerIndex >= state.data.validators.lenu64:
        return err("verify_execution_payload_envelope: invalid proposer index")
      state.data.validators.item(proposerIndex).pubkey
    else:
      if builderIndex >= state.data.builders.lenu64:
        return err("verify_execution_payload_envelope: invalid builder index")
      state.data.builders.item(builderIndex).pubkey

  # Verify signature
  if not verify_execution_payload_envelope_signature(
      fork, genesis_validators_root, payload.slot_number.epoch,
      envelope, pubkey, signed_envelope.signature):
    return err("verify_execution_payload_envelope: invalid signature")

  # Verify consistency with the beacon block
  var header = state.data.latest_block_header
  header.state_root = state.root
  if envelope.beacon_block_root != hash_tree_root(header):
    return err("verify_execution_payload_envelope: beacon_block_root mismatch")
  if envelope.parent_beacon_block_root != state.data.latest_block_header.parent_root:
    return err("verify_execution_payload_envelope: parent_beacon_block_root mismatch")

  # Verify consistency with the committed bid
  if envelope.builder_index != bid.builder_index:
    return err("verify_execution_payload_envelope: builder_index mismatch")
  if payload.prev_randao != bid.prev_randao:
    return err("verify_execution_payload_envelope: prev_randao mismatch")
  if payload.gas_limit != bid.gas_limit:
    return err("verify_execution_payload_envelope: gas_limit mismatch")
  if payload.block_hash != bid.block_hash:
    return err("verify_execution_payload_envelope: block_hash mismatch")
  if hash_tree_root(envelope.execution_requests) != bid.execution_requests_root:
    return err("verify_execution_payload_envelope: execution_requests_root mismatch")

  # Verify the execution payload is valid
  if payload.slot_number != state.data.slot:
    return err("verify_execution_payload_envelope: slot mismatch")
  if payload.parent_hash != state.data.latest_block_hash:
    return err("verify_execution_payload_envelope: parent_hash mismatch")
  if payload.timestamp != timeParams.compute_timestamp_at_slot(state.data, state.data.slot):
    return err("verify_execution_payload_envelope: timestamp mismatch")
  if hash_tree_root(payload.withdrawals) != hash_tree_root(state.data.payload_expected_withdrawals):
    return err("verify_execution_payload_envelope: withdrawals mismatch")

  ok()
```

Single function for both Gloas and Heze (state-type union). All 12 spec checks; EL execute is delegated to the caller (Nimbus's fork-choice / sync paths). Defensive bounds-checks on `proposerIndex` and `builderIndex` against `.lenu64` (lines 1846, 1850).

`verify_execution_payload_envelope_signature` (helper in `signatures.nim`) uses `DOMAIN_BEACON_BUILDER`. Spec URL in source: `v1.7.0-alpha.7/specs/gloas/fork-choice.md#new-verify_execution_payload_envelope` — current spec.

H1 ✓ (self-build/non-self-build pubkey resolution). H2 ✓. H3 ✓ (`header.state_root = state.root`). H4 ✓. H5 ✓. H6 ✓. H7 ✓ (handler in `gossip_processing/gossip_validation.nim` + `consensus_object_pools/block_clearance.nim`). H8 ✓ (external EL). H9 ✓.

### lodestar

`vendor/lodestar/packages/beacon-node/src/chain/blocks/verifyExecutionPayloadEnvelope.ts` — `verifyExecutionPayloadEnvelope` (state-side checks, signature + EL execute separate):

```typescript
export function verifyExecutionPayloadEnvelope(
  config, state, envelope, opts?: VerifyExecutionPayloadEnvelopeOpts
): void {
  const {verifyExecutionRequestsRoot = true} = opts ?? {};
  const payload = envelope.payload;

  // Verify consistency with the beacon block.
  const headerValue = ssz.phase0.BeaconBlockHeader.clone(state.latestBlockHeader);
  if (byteArrayEquals(headerValue.stateRoot, ssz.Root.defaultValue())) {
    headerValue.stateRoot = state.hashTreeRoot();
  }
  const headerRoot = ssz.phase0.BeaconBlockHeader.hashTreeRoot(headerValue);
  if (!byteArrayEquals(envelope.beaconBlockRoot, headerRoot)) { throw Error(...); }
  if (!byteArrayEquals(envelope.parentBeaconBlockRoot, state.latestBlockHeader.parentRoot)) { throw Error(...); }

  // Verify consistency with the committed bid
  const bid = state.latestExecutionPayloadBid;
  if (envelope.builderIndex !== bid.builderIndex) { throw Error(...); }
  if (!byteArrayEquals(bid.prevRandao, payload.prevRandao)) { throw Error(...); }
  if (Number(bid.gasLimit) !== payload.gasLimit) { throw Error(...); }
  if (!byteArrayEquals(bid.blockHash, payload.blockHash)) { throw Error(...); }
  if (verifyExecutionRequestsRoot) {
    const requestsRoot = ssz.electra.ExecutionRequests.hashTreeRoot(envelope.executionRequests);
    if (!byteArrayEquals(requestsRoot, bid.executionRequestsRoot)) { throw Error(...); }
  }

  // Verify the execution payload is valid
  if (payload.slotNumber !== state.slot) { throw Error(...); }
  if (!byteArrayEquals(payload.parentHash, state.latestBlockHash)) { throw Error(...); }
  const expectedTimestamp = computeTimeAtSlot(config, state.slot, state.genesisTime);
  if (payload.timestamp !== expectedTimestamp) { throw Error(...); }

  // Verify consistency with expected withdrawals
  const payloadWithdrawalsRoot = ssz.capella.Withdrawals.hashTreeRoot(payload.withdrawals);
  const expectedWithdrawalsRoot = ssz.capella.Withdrawals.hashTreeRoot(state.payloadExpectedWithdrawals);
  if (!byteArrayEquals(payloadWithdrawalsRoot, expectedWithdrawalsRoot)) { throw Error(...); }
}

export async function verifyExecutionPayloadEnvelopeSignature(
  config, state, pubkeyCache, signedEnvelope, proposerIndex, bls: IBlsVerifier
): Promise<boolean> {
  const signatureSet = getExecutionPayloadEnvelopeSignatureSet(config, pubkeyCache, state, signedEnvelope, proposerIndex);
  return bls.verifySignatureSets([signatureSet]);
}
```

All 12 spec checks present (signature in a separate function — same architectural choice as prysm). The `verifyExecutionRequestsRoot` is gated by an opt flag (default true, can be skipped when pre-validated during gossip) — a perf optimization. EL execute runs separately via `importExecutionPayload`.

The on_execution_payload_envelope handler is `vendor/lodestar/packages/beacon-node/src/chain/blocks/importExecutionPayload.ts` + gossip validation at `chain/validation/executionPayloadEnvelope.ts`. The three steps (state-side checks, signature, EL execute) run in parallel.

H1 ✓ (via `getExecutionPayloadEnvelopeSignatureSet`). H2 ✓. H3 ✓ (header clone + hashTreeRoot). H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (separate `importExecutionPayload`). H9 ✓.

### grandine

`vendor/grandine/fork_choice_store/src/store.rs:3286-3500 validate_execution_payload_envelope_with_state` (state-side checks, inline):

```rust
pub fn validate_execution_payload_envelope_with_state(
    &self,
    envelope: Arc<SignedExecutionPayloadEnvelope<P>>,
    origin: &ExecutionPayloadEnvelopeOrigin,
    block_info: impl FnOnce() -> Option<(Arc<SignedBeaconBlock<P>>, PayloadStatus)>,
    state_fn: impl FnOnce() -> Option<Arc<BeaconState<P>>>,
    execution_engine: impl ExecutionEngine<P> + Send,
) -> Result<ExecutionPayloadEnvelopeAction<P>> {
    let slot = envelope.slot();
    let beacon_block_root = envelope.block_root();
    let builder_index = envelope.builder_index();

    // Gossip-rule pre-checks (REJECT/IGNORE conditions)
    if let Some(payload_action) = self.validate_execution_payload_envelope_for_gossip_rules(&envelope, origin) {
        return Ok(payload_action);
    }
    ensure!(!self.rejected_block_roots.contains(&beacon_block_root), ...);

    // Wait for the block referenced by envelope.beacon_block_root
    let Some((block, block_payload_status)) = block_info() else {
        return Ok(ExecutionPayloadEnvelopeAction::DelayUntilBeaconBlock(envelope, beacon_block_root));
    };
    ensure!(!block_payload_status.is_invalid(), ...);

    // Resolve the bid from the block body
    let Some(bid) = block.message().body().with_payload_bid().map(|body| &body.signed_execution_payload_bid().message)
    else { return Err(Error::PayloadEnvelopeInvalidBlock {...}.into()); };

    // Bid-consistency checks
    ensure!(builder_index == bid.builder_index, Error::<P>::BuilderIndexMismatch {...});
    ensure!(envelope.message.payload.prev_randao == bid.prev_randao, ...);
    ensure!(envelope.message.payload.gas_limit == bid.gas_limit, ...);
    ensure!(envelope.message.payload.block_hash == bid.block_hash, ...);

    // Data-availability deferral
    if self.should_check_data_availability_at_slot(slot) && !self.indices_of_missing_data_columns(&block).is_empty() {
        return Ok(ExecutionPayloadEnvelopeAction::DelayUntilData(envelope, block.clone_arc()));
    }

    // Wait for state
    let Some(state) = state_fn() else { return Ok(ExecutionPayloadEnvelopeAction::DelayUntilState(...)); };

    // Slot, beacon_block_root, parent_beacon_block_root checks
    ensure!(state.slot() == slot, ...);
    let mut header = state.latest_block_header();
    header.state_root = state.hash_tree_root();
    let header_root = header.hash_tree_root();
    ensure!(envelope.message.beacon_block_root == header_root, ...);
    ensure!(envelope.message.parent_beacon_block_root == state.latest_block_header().parent_root, ...);
    ensure!(envelope.message.execution_requests.hash_tree_root() == bid.execution_requests_root, ...);

    // Post-Gloas-state payload checks
    let Some(post_gloas_state) = state.post_gloas() else { return Err(...); };
    ensure!(envelope.message.payload.parent_hash == post_gloas_state.latest_block_hash(), ...);
    let expected_timestamp = ...;  // compute_timestamp_at_slot
    // ... timestamp + withdrawals checks ...
}
```

All 13 spec checks distributed across the validation function (some block-side via `bid` lookup, some state-side after state resolution). The function also handles GOSSIP rules + the "wait for block / wait for state / wait for data" deferrals before running the consensus-level asserts — this is the most complete on_execution_payload_envelope-equivalent across the six.

Signature verification is via `verify_execution_payload_envelope_signature` in `vendor/grandine/helper_functions/src/signing.rs:477+` (using `DOMAIN_BEACON_BUILDER`); called by the controller before this function in the fork-choice flow.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (inline gossip + state deferrals). H8 ✓ (`execution_engine` parameter). H9 ✓.

## Cross-reference table

| Client | `verify_execution_payload_envelope` location | Sig in same fn? | beacon_block_root (H3) | parent_beacon_block_root (H4) | EL execute (H8) | exec_requests_root |
|---|---|---|---|---|---|---|
| prysm | `core/gloas/payload.go:66-180 VerifyExecutionPayloadEnvelope` + `:181-225 ExecutionPayloadEnvelopeSignatureBatch` | inline orchestrator calls sig + consistency separately | **✗ (not explicitly checked; implicit via prestate lookup keyed by envelope.BeaconBlockRoot)** | **✗ (not explicitly checked)** | parallel via `g.Go(validateExecutionOnEnvelope)` | hashTreeRoot equality check ✓ |
| lighthouse | `consensus/state_processing/src/envelope_processing.rs:105-234` | inline (gated by `verify_signatures.is_true()`) | ✓ (header clone + `block_state_root` parameter) | ✓ | external (TODO at `:231`) | tree_hash_root equality ✓ |
| teku | `versions/gloas/execution/ExecutionPayloadVerifierGloas.java:61-145` | inline | ✓ (`BeaconBlockHeader.fromState(state).hashTreeRoot()`) | ✓ | conditional inline via `payloadExecutor` parameter; spec-conformant | hashTreeRoot equality ✓ |
| nimbus | `state_transition_block.nim:1833-1899` | inline (via `verify_execution_payload_envelope_signature` call) | ✓ (`header.state_root = state.root; hash_tree_root(header)`) | ✓ | external (caller-side wired) | hash_tree_root equality ✓ |
| lodestar | `beacon-node/src/chain/blocks/verifyExecutionPayloadEnvelope.ts` + separate `verifyExecutionPayloadEnvelopeSignature` + `importExecutionPayload` | separate (3 functions ran in parallel) | ✓ (header clone + `state.hashTreeRoot()`) | ✓ | external via `importExecutionPayload` | gated by `opts.verifyExecutionRequestsRoot` (default true) ✓ |
| grandine | `fork_choice_store/src/store.rs:3286-3500 validate_execution_payload_envelope_with_state` (also `:3212 validate_execution_payload_envelope` outer; `:3257 _for_gossip_rules`) | inline (signature via controller upstream) | ✓ (`header.state_root = state.hash_tree_root(); header_root`) | ✓ | `execution_engine` parameter; inline EL call | hash_tree_root equality ✓ |

## Empirical tests

No Gloas EF fork-choice fixtures yet exist for `on_execution_payload_envelope`. The closest is the `consensus-spec-tests/tests/mainnet/gloas/fork_choice/` test corpus, which is sparse.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (canonical envelope from non-self-build).** Envelope signed by builder B (active, has funds), correct beacon_block_root, all 4 bid-consistency checks pass, all 4 payload-consistency checks pass. Expected: all 6 accept; envelope stored in `store.payloads[beacon_block_root]`.
- **T1.2 (canonical self-build envelope).** `builder_index == BUILDER_INDEX_SELF_BUILD`; signature against `state.validators[state.latest_block_header.proposer_index].pubkey`. Expected: all 6 accept.

#### T2 — Adversarial probes
- **T2.1 (wrong builder signature).** Envelope signed by a different builder's key than the one in `state.latest_execution_payload_bid`. Expected: all 6 reject at signature check.
- **T2.2 (tampered beacon_block_root, valid signature against original).** Modify `envelope.beacon_block_root` post-sign. Expected: all 6 reject — the 5 with explicit H3 check reject explicitly; prysm rejects via signature failure (the signature was over a different value).
- **T2.3 (tampered parent_beacon_block_root, valid signature against original).** Same pattern. Same observable: 5 reject explicitly, prysm via signature failure.
- **T2.4 (envelope claiming beacon_block_root that has different post-state).** Construct an envelope whose `beacon_block_root` is a known block-root in store BUT not the block whose post-state matches the envelope's claimed `bid.builder_index` etc. Trigger: would only be possible by submitting envelope with valid signature against state A, but with envelope claiming block B (where block B has a different post-state than state A). **Coverage gap test: prysm's `getPayloadEnvelopePrestate(envelope.BeaconBlockRoot)` fetches state at block_root; the spec asserts `envelope.beacon_block_root == hash_tree_root(header_at_that_state)`. If prysm's lookup is by block-root but the binding is incorrect, would prysm accept where the other 5 reject?** Worth a synthetic test.
- **T2.5 (bid-consistency mismatch).** Envelope where `envelope.builder_index != state.latest_execution_payload_bid.builder_index`. Expected: all 6 reject.
- **T2.6 (payload-consistency mismatch).** Envelope where `payload.parent_hash != state.latest_block_hash`. Expected: all 6 reject.
- **T2.7 (withdrawals mismatch).** Envelope's payload withdrawals do not equal `state.payload_expected_withdrawals`. Expected: all 6 reject. Note lighthouse uses element-wise iterator equality (faster path) and the other 5 use `hash_tree_root` equality — observable-equivalent.
- **T2.8 (data unavailable).** Envelope arrives but `is_data_available(envelope.beacon_block_root) == false`. Expected: per spec, payload MAY be queued and reconsidered when data becomes available. All 6 implement deferral logic; verify behaviour is uniform (queue vs reject).
- **T2.9 (envelope arrives before block).** Envelope's `beacon_block_root` not yet in `store.block_states`. Expected: per spec, reject (assert fails). lighthouse / grandine implement deferral (grandine `DelayUntilBeaconBlock`). Verify cross-client deferral policy.

## Conclusion

**Status: source-code-reviewed.** All six clients implement `verify_execution_payload_envelope` spec-equivalently. The 9 hypotheses split: H1, H2, H5, H6, H7, H8 satisfied uniformly; **H3 + H4 explicit-coverage observation on prysm** — prysm's `validatePayloadConsistency` omits the explicit `envelope.beacon_block_root == hash_tree_root(header)` and `envelope.parent_beacon_block_root == state.latest_block_header.parent_root` asserts that the other 5 clients have explicit. The omissions are defense-in-depth (both fields are part of the signed envelope so the signature commits to them; the prestate lookup is keyed by `envelope.BeaconBlockRoot()` so the binding is implicit).

**Impact: none.** No mainnet-reachable consensus divergence on canonical traffic. On adversarial inputs (tampered envelope), the 6 clients all reject — 5 explicitly at the H3/H4 checks, prysm implicitly via signature verification failing on the tampered bytes.

Notable per-client style differences:

- **prysm** uses Go errors-as-values with descriptive messages; factors signature into `ExecutionPayloadEnvelopeSignatureBatch` for deferred batch verification; runs the state-side and EL-side checks in parallel via `g.Go`. Omits H3 + H4 explicit checks (compensated architecturally).
- **lighthouse** uses the `envelope_verify!` macro pattern with typed `EnvelopeProcessingError::*` variants; **uses element-wise iterator equality for withdrawals** rather than hash_tree_root equality (`payload.withdrawals.iter().eq(state.payload_expected_withdrawals().iter())`) — observable-equivalent but skips both Merkle computations on the canonical case. Has explicit `block_state_root` parameter for the H3 header-root computation (caller must provide post-block state root). TODO comment at `:231` notes EL execute is wired externally.
- **teku** uses subclass override polymorphism (`ExecutionPayloadVerifierGloas implements ExecutionPayloadVerifier`); the EL execute is conditional on `payloadExecutor.isPresent()` — when present, runs INLINE inside `verifyExecutionPayloadEnvelope` (line 135-144) matching the spec's `verify_and_notify_new_payload`. Most spec-faithful inline pattern of the six.
- **nimbus** uses `Result[void, cstring]` errors with descriptive `err()` strings; supports both Gloas and Heze states via type union. Defensive bounds-checks on proposerIndex and builderIndex against `.lenu64`. Comment URL references `v1.7.0-alpha.7` (current spec).
- **lodestar** separates state-side checks (`verifyExecutionPayloadEnvelope`), signature verification (`verifyExecutionPayloadEnvelopeSignature`), and EL execute (`importExecutionPayload`) into 3 functions that run in parallel. The execution-requests-root check is gated by `opts.verifyExecutionRequestsRoot` (default `true`) to allow skipping when pre-validated during gossip.
- **grandine** has the most complete `on_execution_payload_envelope` analog: `validate_execution_payload_envelope_with_state` handles GOSSIP rules + "wait for block / wait for state / wait for data" deferrals + all consensus-level asserts in a single function. Uses `ExecutionPayloadEnvelopeAction::DelayUntilBeaconBlock / DelayUntilState / DelayUntilData` for the deferral cases — most-explicit deferral state machine across the six.

Recommendations:

- **Generate T2.2 / T2.3 tampered-envelope fixtures** to lock in the cross-client rejection invariant (prysm rejects via signature; others reject explicitly).
- **Generate T2.4 binding-mismatch fixture** as a forward-fragility hedge against any future refactor of prysm's prestate-lookup path that might break the implicit binding.
- **Generate T2.8 / T2.9 deferral-policy fixtures** to lock the queue-vs-reject behaviour cross-client.
- **Codify prysm's missing-check observation** (H9 partial) as a forward-fragility hedge: if prysm's prestate lookup is ever refactored to be more permissive, the implicit binding could break. An explicit `envelope.BeaconBlockRoot == hash_tree_root(headerWithStateRoot)` check would future-proof.
- **Document lighthouse's element-wise withdrawals comparison** — it's faster than hash_tree_root and observable-equivalent, but if `payload.withdrawals` SSZ type ever changes to a non-comparable container, the path would break.

## Cross-cuts

### With item #19 (`process_execution_payload` removal + ePBS restructure)

Item #19 verified the wiring: every client has `verify_execution_payload_envelope` and an `on_execution_payload_envelope` analog. This item verifies the predicate body (13 spec assertions). Together they close the envelope-verification audit.

### With item #58 (`process_execution_payload_bid`)

Item #58's `process_execution_payload_bid` writes `state.latest_execution_payload_bid = bid` block-time. This item's `verify_execution_payload_envelope` reads `state.latest_execution_payload_bid` to verify the envelope's 5 bid-consistency fields. Producer / consumer pair on `state.latest_execution_payload_bid`.

### With item #57 (`process_builder_pending_payments`)

Both items operate within the EIP-7732 ePBS lifecycle. Item #57 settles bids into withdrawals (epoch-time); this item is the gating step for whether the payload itself is accepted into the store (fork-choice-time).

### With Gloas data availability (item #56 cross-cut)

`on_execution_payload_envelope` calls `is_data_available(envelope.beacon_block_root)`. Item #56 audits the DA layer for Gloas. Cross-cut on the per-client DA-deferral architecture (Pattern II from item #28).

### With `state.payload_expected_withdrawals` writer

Item #12 H11 writes `state.builder_pending_withdrawals` (epoch-time, settled bids). The `state.payload_expected_withdrawals` field is computed elsewhere (process_parent_execution_payload or similar) and compared here. Cross-cut on the expected-withdrawals producer.

## Adjacent untouched

1. **`SignedExecutionPayloadEnvelope` SSZ ser/de cross-client** — new container at Gloas; byte-equivalence for gossip relay.
2. **`is_data_available` standalone audit** — used by `on_execution_payload_envelope` and item #56. Per-client DA-quarantine architecture (Pattern II).
3. **Envelope gossip topic** — verify topic name (`execution_payload_envelope`?) + subscription policy cross-client.
4. **Envelope RPC handler** — `ExecutionPayloadEnvelopesByRoot` / `ExecutionPayloadEnvelopesByRange` request types.
5. **Builder slashing for double-envelope** — if a builder signs two conflicting envelopes for the same bid, is it slashable? Audit-worthy as its own item.
6. **Late-envelope retrospective execution** — does any client allow envelope arrival N+1 to retroactively execute block N's payload? Per-client deferral-policy audit.
7. **prysm's missing H3 + H4 explicit asserts** — file an upstream PR to add the spec assertions explicitly (forward-fragility hedge).
8. **lighthouse element-wise withdrawals comparison** — verify it remains observable-equivalent across all `payload.withdrawals` SSZ schema variants.
9. **lodestar `verifyExecutionRequestsRoot` opt-skip safety** — when gossip-validation skips, ensure the same fixture is re-checked at block-import time.
10. **grandine deferral state machine** — extract `ExecutionPayloadEnvelopeAction` enum behaviour into a separate audit; the deferral logic is the most complex of the six.
