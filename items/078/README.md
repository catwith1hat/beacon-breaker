---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-14
builds_on: [76]
eips: [EIP-7732]
splits: [prysm]
# main_md_summary: prysm's `ExecutionPayloadEnvelope` SSZ container is missing the `parent_beacon_block_root` field (spec PR #5152 from 2026-04-24) — 4 fields vs spec's 5, so prysm cannot deserialize envelopes from the other 5 clients; consequently `verify_execution_payload_envelope` lacks the `envelope.parent_beacon_block_root == state.latest_block_header.parent_root` and `envelope.beacon_block_root == hash_tree_root(header)` asserts; cross-CL incompatibility post-Glamsterdam
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 78: `verify_execution_payload_envelope` + `on_execution_payload_envelope` — prysm lags spec PR #5152, missing `parent_beacon_block_root` field

## Summary

Gloas's `verify_execution_payload_envelope` (`vendor/consensus-specs/specs/gloas/fork-choice.md:790-834`) verifies a `SignedExecutionPayloadEnvelope` against the post-block state before storing it in `store.payloads`. Spec asserts the envelope is consistent with the beacon block, the committed bid, and the EL's recomputation of the payload.

Two consistency asserts in particular bind envelope-side fields to state-side fields:

```python
# Verify consistency with the beacon block
header = copy(state.latest_block_header)
header.state_root = hash_tree_root(state)
assert envelope.beacon_block_root == hash_tree_root(header)
assert envelope.parent_beacon_block_root == state.latest_block_header.parent_root
```

The `parent_beacon_block_root` field on `ExecutionPayloadEnvelope` was added by spec PR #5152 (commit `c9e0d02c2`, merged 2026-04-24). Before that, the container had 4 fields; after, 5.

**Five of six clients (lighthouse, teku, nimbus, lodestar, grandine) have adopted the spec update.** Their SSZ containers carry the 5th field; their `verify_execution_payload_envelope` implementations contain both asserts.

**Prysm has not adopted the spec update.** Its `ExecutionPayloadEnvelope` protobuf/SSZ container at `vendor/prysm/proto/prysm/v1alpha1/gloas.proto:491-498` defines only 4 fields:

```proto
message ExecutionPayloadEnvelope {
  ethereum.engine.v1.ExecutionPayloadGloas payload = 1;
  ethereum.engine.v1.ExecutionRequests execution_requests = 2;
  uint64 builder_index = 3 [...];
  bytes beacon_block_root = 4 [(ethereum.eth.ext.ssz_size) = "32"];
}
```

Consequently, `validatePayloadConsistency` at `vendor/prysm/beacon-chain/core/gloas/payload.go:109-183` lacks both asserts. The function carries a pinned spec excerpt (function hash `0261931f`, lines 24-65) that predates PR #5152 — the comment text itself shows the older 4-field container and the older `parent_beacon_block_root=state.latest_block_header.parent_root` form in the EL call.

This is a **spec-tracking gap** rather than an implementation bug per se. But its effects are mainnet-glamsterdam-reachable along two distinct vectors:

1. **Wire-layer incompatibility**: prysm cannot SSZ-deserialize the 5-field `SignedExecutionPayloadEnvelope` that the other 5 clients now emit. `hash_tree_root` of the same logical envelope differs across the two container shapes. A prysm node cannot validate envelopes gossiped by lighthouse/teku/nimbus/lodestar/grandine, and vice versa.
2. **Missing consensus check**: even if prysm picked up the new field but missed the new assert, a malicious builder could set `envelope.parent_beacon_block_root != state.latest_block_header.parent_root` while keeping `payload.block_hash` consistent with `state.latest_block_header.parent_root` (which is what the EL actually uses, since prysm passes `st.LatestBlockHeader().ParentRoot` to the EL call at `vendor/prysm/beacon-chain/blockchain/receive_execution_payload_envelope.go:255`). Spec-conformant clients reject via the new assert; prysm accepts. Result: `store.payloads` membership differs → `is_payload_verified` differs → `is_payload_timely` / `should_extend_payload` / fork-choice tiebreaker differ → head selection differs.

Vector #1 is the immediate, certain consequence of the spec lag. Vector #2 becomes operational once prysm picks up the field but if (as is typical with mid-fork spec updates) the assert is left off.

The `beacon_block_root == hash_tree_root(header_with_state_root)` assert is similarly missing in prysm but is **defensive** rather than consensus-impacting: in well-formed stores the state retrieved via `store.block_states[envelope.beacon_block_root]` has a `latest_block_header` that, when its `state_root` is filled with `hash_tree_root(state)`, hashes back to `envelope.beacon_block_root` by construction. Skipping the check does not enable any attacker-induced divergence under normal store semantics.

## Question

Spec at `vendor/consensus-specs/specs/gloas/fork-choice.md:790-834`:

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
    assert execution_engine.verify_and_notify_new_payload(
        NewPayloadRequest(
            execution_payload=payload,
            versioned_hashes=[
                kzg_commitment_to_versioned_hash(commitment)
                for commitment in bid.blob_kzg_commitments
            ],
            parent_beacon_block_root=envelope.parent_beacon_block_root,
            execution_requests=envelope.execution_requests,
        )
    )
```

Container at `vendor/consensus-specs/specs/gloas/beacon-chain.md:303-309`:

```python
class ExecutionPayloadEnvelope(Container):
    payload: ExecutionPayload
    execution_requests: ExecutionRequests
    builder_index: BuilderIndex
    beacon_block_root: Root
    parent_beacon_block_root: Root
```

`on_execution_payload_envelope` at `fork-choice.md:922-948`:

```python
def on_execution_payload_envelope(
    store: Store, signed_envelope: SignedExecutionPayloadEnvelope
) -> None:
    envelope = signed_envelope.message
    assert envelope.beacon_block_root in store.block_states
    assert is_data_available(envelope.beacon_block_root)
    state = store.block_states[envelope.beacon_block_root]
    verify_execution_payload_envelope(state, signed_envelope, EXECUTION_ENGINE)
    store.payloads[envelope.beacon_block_root] = envelope
```

`is_payload_verified` at `fork-choice.md:253-263`:

```python
def is_payload_verified(store: Store, root: Root) -> bool:
    return root in store.payloads
```

Open questions:

1. **Container shape per-client.** Does each client's `ExecutionPayloadEnvelope` SSZ container have 5 fields (per spec PR #5152) or the older 4-field form?
2. **`beacon_block_root` consistency assert.** Does each client check `envelope.beacon_block_root == hash_tree_root(header_with_state_root)`?
3. **`parent_beacon_block_root` consistency assert.** Does each client check `envelope.parent_beacon_block_root == state.latest_block_header.parent_root`?
4. **EL `NewPayload` input.** Does each client pass `envelope.parent_beacon_block_root` (current spec) or `state.latest_block_header.parent_root` (older spec) to the EL?
5. **`is_payload_verified` storage.** Does each client persist envelopes into a store keyed by `beacon_block_root` after acceptance, and gate downstream fork-choice predicates on that?

## Hypotheses

- **H1.** All six clients have the new 5-field `ExecutionPayloadEnvelope` container.
- **H2.** All six implement `verify_execution_payload_envelope` with both consistency asserts (beacon_block_root + parent_beacon_block_root).
- **H3.** All six pass `envelope.parent_beacon_block_root` (the new spec form) to the EL's `NewPayload` call.
- **H4.** All six store the envelope into a `store.payloads`-equivalent on acceptance and gate `is_payload_verified` on membership.
- **H5** *(divergence)*. Prysm fails H1, H2, H3 — pinned to a pre-PR-5152 spec version. Container has 4 fields; verify lacks both asserts; EL call uses state-side parent root.

## Findings

### prysm

**Container at `vendor/prysm/proto/prysm/v1alpha1/gloas.proto:481-498`**:

```proto
// Spec:
// class ExecutionPayloadEnvelope(Container):
//     payload: ExecutionPayload
//     execution_requests: ExecutionRequests
//     builder_index: BuilderIndex
//     beacon_block_root: Root
message ExecutionPayloadEnvelope {
  ethereum.engine.v1.ExecutionPayloadGloas payload = 1;
  ethereum.engine.v1.ExecutionRequests execution_requests = 2;
  uint64 builder_index = 3 [...];
  bytes beacon_block_root = 4 [(ethereum.eth.ext.ssz_size) = "32"];
}
```

**4 fields** — no `parent_beacon_block_root`. Spec comment also reflects the older 4-field form. ✗ H1.

`VerifyExecutionPayloadEnvelope` at `vendor/prysm/beacon-chain/core/gloas/payload.go:66-81`:

```go
func VerifyExecutionPayloadEnvelope(
    ctx context.Context,
    st state.BeaconState,
    signedEnvelope interfaces.ROSignedExecutionPayloadEnvelope,
) error {
    if err := verifyExecutionPayloadEnvelopeSignature(st, signedEnvelope); err != nil {
        return errors.Wrap(err, "signature verification failed")
    }
    envelope, err := signedEnvelope.Envelope()
    if err != nil { ... }
    return validatePayloadConsistency(ctx, st, envelope)
}
```

Pinned spec excerpt at `payload.go:24-65` (function hash `0261931f`) shows the older spec form with `parent_beacon_block_root=state.latest_block_header.parent_root` in the EL call and no `parent_beacon_block_root == state.latest_block_header.parent_root` assert.

`validatePayloadConsistency` at `payload.go:109-183` checks:

- `envelope.Slot() == st.Slot()` ✓ (spec H10).
- `envelope.BuilderIndex() == latestBid.BuilderIndex()` ✓.
- `executionRequestsRoot == bidExecutionRequestsRoot` ✓.
- `payload.PrevRandao() == latestBid.PrevRandao()` ✓.
- Withdrawals match `state.payload_expected_withdrawals` ✓.
- `latestBid.GasLimit() == payload.GasLimit()` ✓.
- `bidBlockHash == payload.BlockHash()` ✓.
- `payload.ParentHash() == latestBlockHash` ✓.
- `payload.Timestamp() == expected` ✓.

**Missing**:
- `envelope.beacon_block_root == hash_tree_root(state.latest_block_header_with_state_root)` ✗ — not in code (defensive check; tautological in well-formed stores).
- `envelope.parent_beacon_block_root == state.latest_block_header.parent_root` ✗ — not in code (field doesn't exist in container).

EL call path (`vendor/prysm/beacon-chain/blockchain/receive_execution_payload_envelope.go:238-256`):

```go
func (s *Service) notifyNewEnvelope(ctx context.Context, st state.BeaconState, envelope interfaces.ROExecutionPayloadEnvelope) (bool, error) {
    payload, err := envelope.Execution()
    ...
    return s.callNewPayload(ctx, payload, versionedHashes, common.Hash(bytesutil.ToBytes32(st.LatestBlockHeader().ParentRoot)), envelope.ExecutionRequests(), envelope.Slot())
}
```

Passes `st.LatestBlockHeader().ParentRoot` (state-side value), not `envelope.parent_beacon_block_root` (envelope-side value). Matches the older spec form. ✗ H3.

`InsertPayload` at `vendor/prysm/beacon-chain/forkchoice/doubly-linked-tree/gloas.go:376-402`:

```go
func (f *ForkChoice) InsertPayload(pe interfaces.ROExecutionPayloadEnvelope) error {
    ...
    s.fullNodeByRoot[root] = fn  // marks the consensus node FULL
    payloadInsertedCount.Inc()
    f.updateNewFullNodeWeight(fn)
    return nil
}
```

Prysm tracks payload-imported state via `fullNodeByRoot[root]` (parallel to spec's `store.payloads[root]`). `is_payload_verified` is equivalent to `fullNodeByRoot[root] != nil`. ✓ H4.

### lighthouse

**Container**: has 5-field form (confirmed via type definition; tree-hash includes `parent_beacon_block_root`). ✓ H1.

`verify_execution_payload_envelope` at `vendor/lighthouse/consensus/state_processing/src/envelope_processing.rs:105-234`:

```rust
// Verify consistency with the beacon block.
let mut header = state.latest_block_header().clone();
if header.state_root == Hash256::default() {
    header.state_root = block_state_root;
}
let latest_block_header_root = header.tree_hash_root();
envelope_verify!(
    envelope.beacon_block_root == latest_block_header_root,
    EnvelopeProcessingError::LatestBlockHeaderMismatch { ... }
);
envelope_verify!(
    envelope.parent_beacon_block_root == state.latest_block_header().parent_root,
    EnvelopeProcessingError::ParentBeaconBlockRootMismatch { ... }
);
```

Both asserts present at `envelope_processing.rs:128-141`. ✓ H2.

### teku

**Container**: 5-field form. ✓ H1.

`ExecutionPayloadVerifierGloas.verifyExecutionPayloadEnvelope` at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/execution/ExecutionPayloadVerifierGloas.java:76-84`:

```java
// Verify consistency with the beacon block
if (!envelope.getBeaconBlockRoot().equals(BeaconBlockHeader.fromState(state).hashTreeRoot())) {
    throw new ExecutionPayloadVerificationException(
        "Envelope beacon block root is not consistent with the latest beacon block from the state");
}
if (!envelope.getParentBeaconBlockRoot().equals(state.getLatestBlockHeader().getParentRoot())) {
    throw new ExecutionPayloadVerificationException(
        "Envelope parent beacon block root is not consistent with the latest beacon block parent root from the state");
}
```

Both asserts present. ✓ H2.

EL call at line 169-181 uses `envelope.getParentBeaconBlockRoot()` ✓ H3.

### nimbus

**Container**: `vendor/nimbus/beacon_chain/spec/datatypes/gloas.nim` has 5-field form. ✓ H1.

`verify_execution_payload_envelope` at `vendor/nimbus/beacon_chain/spec/state_transition_block.nim:1832-1900`:

```nim
if envelope.beacon_block_root != hash_tree_root(header):
    return err("verify_execution_payload_envelope: beacon_block_root mismatch")
if envelope.parent_beacon_block_root != state.latest_block_header.parent_root:
    return err("verify_execution_payload_envelope: parent_beacon_block_root mismatch")
```

Both asserts present at lines 1866-1871. ✓ H2.

### lodestar

**Container** at `vendor/lodestar/packages/types/src/gloas/sszTypes.ts`:

```typescript
export const ExecutionPayloadEnvelope = new ContainerType(
  {
    payload: ExecutionPayload,
    executionRequests: electraSsz.ExecutionRequests,
    builderIndex: BuilderIndex,
    beaconBlockRoot: Root,
    parentBeaconBlockRoot: Root,
  },
  {typeName: "ExecutionPayloadEnvelope", jsonCase: "eth2"}
);
```

5-field form. ✓ H1.

`verifyExecutionPayloadEnvelope` at `vendor/lodestar/packages/beacon-node/src/chain/blocks/verifyExecutionPayloadEnvelope.ts:41-50`:

```typescript
if (!byteArrayEquals(envelope.beaconBlockRoot, headerRoot)) {
    throw new Error(`Envelope's block is not the latest block header envelope=${...} latestBlockHeader=${...}`);
}
if (!byteArrayEquals(envelope.parentBeaconBlockRoot, state.latestBlockHeader.parentRoot)) {
    throw new Error(`Envelope's parent_beacon_block_root mismatch envelope=${...} state=${...}`);
}
```

Both asserts present. ✓ H2.

### grandine

**Container**: `vendor/grandine/types/src/gloas/containers.rs:172` — has `parent_beacon_block_root: H256` field. ✓ H1.

`validate_execution_payload_envelope` at `vendor/grandine/fork_choice_store/src/store.rs:3411-3427`:

```rust
ensure!(
    envelope.message.beacon_block_root == header_root,
    Error::<P>::ExecutionPayloadBeaconBlockRootMismatch { ... },
);

let parent_beacon_block_root = state.latest_block_header().parent_root;

ensure!(
    envelope.message.parent_beacon_block_root == parent_beacon_block_root,
    Error::<P>::ExecutionPayloadParentBeaconBlockRootMismatch { ... },
);
```

Both asserts present. ✓ H2.

EL call at line 3493-3509 uses the local `parent_beacon_block_root` variable (the state's value), but it has just been asserted equal to `envelope.message.parent_beacon_block_root` — semantically equivalent to the new spec. ✓ H3.

## Cross-reference table

| Client | Container has 5 fields (H1) | `beacon_block_root` consistency assert (H2a) | `parent_beacon_block_root` consistency assert (H2b) | EL call uses envelope.parent_beacon_block_root (H3) |
|---|---|---|---|---|
| **prysm** | **✗ 4 fields** (`gloas.proto:491-498`) | **✗ missing** (defensive only) | **✗ missing** (field doesn't exist) | **✗ uses state.latest_block_header.parent_root** (`receive_execution_payload_envelope.go:255`) |
| lighthouse | ✓ 5 fields | ✓ `envelope_processing.rs:128-134` | ✓ `envelope_processing.rs:135-141` | ✓ via subsequent EL call |
| teku | ✓ 5 fields | ✓ `ExecutionPayloadVerifierGloas.java:77-80` | ✓ `:81-84` | ✓ `:179` |
| nimbus | ✓ 5 fields (`gloas.nim`) | ✓ `state_transition_block.nim:1866-1867` | ✓ `:1868-1871` | ✓ |
| lodestar | ✓ 5 fields (`sszTypes.ts`) | ✓ `verifyExecutionPayloadEnvelope.ts:41-45` | ✓ `:46-50` | ✓ |
| grandine | ✓ 5 fields | ✓ `store.rs:3411-3417` | ✓ `:3421-3427` | (uses local var asserted equal — semantically equivalent) |

**H1 ✓ for 5 of 6 clients, ✗ for prysm.**
**H2a ✓ for 5 of 6 clients, ✗ for prysm** (defensive, not consensus-impacting).
**H2b ✓ for 5 of 6 clients, ✗ for prysm** (consensus-impacting; would matter once prysm picks up the field but if the assert is omitted).
**H3 ✓ for 5 of 6 clients; ✗ for prysm** (uses older state-side form).
**H4 ✓ for all 6** — `is_payload_verified` equivalent exists in each client's fork-choice.

## Empirical tests

### Spec hash trace

Prysm's `verify_execution_payload_envelope` is annotated with spec function hash `0261931f` (`payload.go:24`). The current spec content at `vendor/consensus-specs/specs/gloas/fork-choice.md:790-834` hashes differently because of the new `parent_beacon_block_root` assert and the changed EL-call argument. The `parent_beacon_block_root` field was added by spec PR #5152, commit `c9e0d02c2` on 2026-04-24 — see `cd vendor/consensus-specs && git show c9e0d02c2`.

### Wire-layer empirical check (suggested)

Serialize a 5-field `SignedExecutionPayloadEnvelope` in lodestar; attempt to deserialize in prysm. Expected: deserialize fails (SSZ length mismatch, or extra trailing bytes interpreted differently). Conversely, prysm-serialized 4-field envelope → lighthouse/teku/nimbus/lodestar/grandine deserialization fails.

The `hash_tree_root` of the same logical envelope differs between the 4-field and 5-field shapes because SSZ Merkleization pads to the next power of 2 (with 4 fields → 2-leaf tree, with 5 fields → 4-leaf tree with 3 zero leaves). Signature `signing_root` therefore also differs, so signatures don't transfer either.

### Adversarial check (suggested, once prysm picks up the field)

If prysm updates the container but not the assert: a malicious builder constructs envelope with `envelope.parent_beacon_block_root = X ≠ state.latest_block_header.parent_root = Y`, while keeping `payload.block_hash` consistent with the EL using `Y` (which is what prysm passes). Prysm accepts; spec-conformant clients reject (assert fails). Fork-choice `store.payloads` membership diverges → `is_payload_verified` diverges → head divergence.

## Mainnet reachability

Two distinct paths.

### Path A: wire-layer interop break (immediate, certain)

Once Glamsterdam activates and `ExecutionPayloadEnvelope` traffic begins on mainnet, prysm and the 5 other clients use different SSZ container shapes. Prysm's 4-field envelopes cannot be deserialized by the other 5; the others' 5-field envelopes cannot be deserialized by prysm. Gossip and req-resp both break.

**Triggering actor**: any builder producing envelopes for either subgraph. As soon as Glamsterdam ships with the current versions, the network bifurcates into a prysm subgraph and a 5-other-clients subgraph. Neither can validate the other's envelopes.

**Frequency**: every slot of Gloas.

**Consequence**: prysm cannot validate any block whose `payload` is delivered via the new envelope format. `is_payload_verified` on prysm is never true for blocks from the other subgraph, forcing prysm to treat all such blocks as EMPTY in fork-choice. The other subgraph treats them based on PTC votes (FULL when timely+available). Different fork-choice → different heads → finalization stall.

This is structurally identical to a Gloas-fork-readiness gap. The fix is straightforward: prysm rebases on the post-PR-#5152 spec.

### Path B: adversarial `parent_beacon_block_root` mismatch (conditional)

Path B is only relevant **after** prysm picks up the new field but **if** the assert is omitted. The attacker is a registered builder; the divergent state is `store.payloads` membership; the consequence is fork-choice head divergence (same shape as item #77's lodestar divergence).

This path is not currently triggerable (Path A wins by deserialization rejection), but it documents the second consequence of prysm's spec-tracking gap.

**Pre-Glamsterdam mainnet impact**: zero. Gloas is `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` on mainnet. Both paths are only operational on Gloas-active testnets and on mainnet after Glamsterdam activation. Hence the impact classification `mainnet-glamsterdam`.

## Conclusion

Prysm has not adopted spec PR #5152 (`parent_beacon_block_root` added to `ExecutionPayloadEnvelope`, merged 2026-04-24). Prysm's container has 4 fields where the other 5 clients have 5. Prysm's `verify_execution_payload_envelope` lacks the two new consistency asserts. Prysm's EL call still uses the older `state.latest_block_header.parent_root` form.

**Verdict: impact mainnet-glamsterdam.** This is a spec-tracking gap, not an implementation bug. Once prysm rebases on the post-PR-#5152 spec, all three sub-findings resolve in a single commit.

**Severity vs items #67 and #77 (lodestar)**: this is a structurally simpler issue (spec lag) but with broader impact (wire-layer interop, not just head selection). Item #67 and #77 are implementation bugs in lodestar that require code reasoning to find and fix; item #78 is a fork-readiness gap in prysm that requires only a spec re-sync.

**Comparison with item #76's T1 scope**: T1 was specified as "`is_payload_verified` + `on_execution_payload_envelope` round-trip per-client byte-equivalence." This item closes T1. The byte-equivalence is broken at the container layer (prysm's 4 fields vs other 5's 5 fields). All other byte-equivalence checks in `verify_execution_payload_envelope` are consistent across the 6 clients on the fields they share — the divergence is exclusively about the new field's presence and the asserts that bind it.

Resolution options:

1. **Prysm rebases on the current spec.** Add `parent_beacon_block_root` to `ExecutionPayloadEnvelope` proto/SSZ container. Add the two consistency asserts to `validatePayloadConsistency`. Update the EL call at `receive_execution_payload_envelope.go:255` to pass `envelope.ParentBeaconBlockRoot()` instead of `st.LatestBlockHeader().ParentRoot`. Update the pinned spec hash in `payload.go:24`. **Recommended.**
2. **Spec spec-test corpus exercises the new field.** Add a fixture that constructs envelopes with the new field; verify all 6 clients accept/reject consistently. The EF test corpus at `vendor/consensus-specs/tests/.../gloas/fork_choice/` may not yet cover the new field.

## Cross-cuts

### With item #76 (fork-choice surface scan)

Item #76's T1 entry is now closed: "`is_payload_verified` + `on_execution_payload_envelope` round-trip per-client byte-equivalence." Result: byte-equivalence is broken between prysm and the other 5 clients at the container layer.

### With item #77 (lodestar `should_extend_payload` data-availability gap)

#77 documented lodestar's missing `is_payload_data_available` in fork-choice. #78 documents prysm's missing `parent_beacon_block_root` in envelope verification. Both surface as fork-choice head-selection divergences; both are mainnet-glamsterdam.

### With item #67 (lodestar builder-sweep)

Both #67 and #78 are mainnet-glamsterdam-impact divergences but with different splits (#67: lodestar 1-vs-5; #78: prysm 1-vs-5). They are independent.

### With evm-breaker's EL `parent_beacon_block_root` handling

EIP-4788 specifies how EL clients consume `parent_beacon_block_root` (writing to the BEACON_ROOTS contract storage). Prysm's CL passes `state.latest_block_header.parent_root` to its EL regardless of envelope content. Other 5 CLs pass `envelope.parent_beacon_block_root` (after the assert). Per-EL behavior is unchanged because the value reaching the EL is the same after the assert holds. Cross-corpus: no new EL audit needed.

## Adjacent untouched

1. **Prysm's planned upgrade timing.** When does prysm intend to rebase on the post-PR-#5152 spec? Check prysm's tracking issue / `EPBS_STATUS.md` equivalent.
2. **Other clients' spec hash currency.** Lighthouse, teku, nimbus, lodestar, grandine all have the 5-field container; do they all reference post-PR-#5152 spec versions in their `specrefs` / spec-link comments?
3. **EF spec-test corpus coverage of the new field.** Does `vendor/consensus-specs/tests/.../gloas/fork_choice/...` exercise the `parent_beacon_block_root` consistency assert?
4. **Other spec changes between prysm's pinned hash and current.** Spot-check for additional drift in the same neighborhood.
5. **Gossip-validation envelope size limits.** With 5 fields, the serialized envelope is 32 bytes longer. Verify gossip topic size limits are tracked correctly per-client.
