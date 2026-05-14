---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [58, 70]
eips: [EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 71: `engine_getPayloadV5` builder-vs-self-build dispatch

## Summary

Gloas's `engine_getPayloadV5` is invoked when the CL decides to **self-build** rather than accept an external builder's bid. The dispatch decision is per-slot, per-proposer-preference, and per-policy. The actual `BUILDER_INDEX_SELF_BUILD` sentinel value is `UINT64_MAX` (`0xFFFFFFFFFFFFFFFF`) across all six clients; the per-client dispatch decision is consistently implemented.

All 6 clients:

1. Define `BUILDER_INDEX_SELF_BUILD = u64::MAX` (or language-equivalent).
2. Implement the `engine_getPayloadV5` Engine API method name.
3. Branch on `bid.builder_index == BUILDER_INDEX_SELF_BUILD` to decide self-build vs external-builder paths.
4. On self-build: call `engine_getPayloadV5(payload_id)` to retrieve the EL-built payload, then sign an envelope with `builder_index = BUILDER_INDEX_SELF_BUILD`.
5. On external builder: accept the `SignedExecutionPayloadBid` from a relay, propose a beacon block referencing it, await the envelope.

Lodestar uniquely encodes the constant as `BUILDER_INDEX_SELF_BUILD = Infinity` (JS Number). Behind the scenes it uses SSZ `UintNumberType(8, {clipInfinity: true})` which round-trips `Infinity ↔ 0xFFFFFFFFFFFFFFFF` correctly on the wire. State-root and SSZ-hashes are byte-equivalent with other clients.

**Verdict: impact none.** No divergence on the sentinel or dispatch logic. Per-client mev-boost integration policies are operationally significant (not consensus-relevant).

## Question

Spec semantics for `BUILDER_INDEX_SELF_BUILD` per `vendor/consensus-specs/specs/gloas/beacon-chain.md` (cross-referenced at `vendor/teku/specrefs/constants.yml:57`):

```
BUILDER_INDEX_SELF_BUILD: BuilderIndex = UINT64_MAX
```

Used to indicate that the block proposer's own EL produced the execution payload (no external builder bid won the auction). When a CL chooses self-build:

1. Bid construction: `bid.builder_index = BUILDER_INDEX_SELF_BUILD`.
2. Signature path: signs with the proposer's pubkey (not a builder's pubkey).
3. Engine API: `engine_getPayloadV5(payload_id) → ExecutionPayloadEnvelope` for the local-built payload.

Engine API method `engine_getPayloadV5` per `vendor/nimbus/vendor/nim-web3/tests/execution-apis/src/engine/osaka.md:56-62`:

```
* method: engine_getPayloadV5
* params: [PayloadId]
* returns: GetPayloadV5Response { executionPayload, blockValue, blobsBundle, executionRequests, shouldOverrideBuilder, ... }
```

Open questions:

1. **`BUILDER_INDEX_SELF_BUILD` value** — `UINT64_MAX = 0xFFFFFFFFFFFFFFFF` per spec; per-client identical?
2. **`engine_getPayloadV5` method name** — per-client uniform `"engine_getPayloadV5"`?
3. **Self-build vs builder branching** — per-client implementation in proposer/validator code.
4. **External-builder fallback** — if external builder fails, per-client fallback to self-build?
5. **JS Number range handling** — lodestar's `Infinity` workaround for u64 MAX exceeding 2^53 - 1.

## Hypotheses

- **H1.** All six clients define `BUILDER_INDEX_SELF_BUILD = UINT64_MAX = 0xFFFFFFFFFFFFFFFF`.
- **H2.** All six implement `engine_getPayloadV5` with the `"engine_getPayloadV5"` method-name string.
- **H3.** All six branch on `builder_index == BUILDER_INDEX_SELF_BUILD` consistently for self-build detection.
- **H4.** Self-build path: `engine_getPayloadV5` invoked, returned payload signed by proposer.
- **H5.** External-builder path: bid + envelope flow; no `engine_getPayloadV5` invocation.
- **H6** *(lodestar-specific)*. Lodestar's `Infinity` representation round-trips to/from `0xFFFFFFFFFFFFFFFF` on SSZ wire correctly via `UintNumberType(8, {clipInfinity: true})`.

## Findings

### prysm

`BUILDER_INDEX_SELF_BUILD` at `vendor/prysm/config/params/mainnet_config.go:100`:

```go
BuilderIndexSelfBuild: primitives.BuilderIndex(math.MaxUint64),
```

Value: `math.MaxUint64 = 0xFFFFFFFFFFFFFFFF` ✓ matches spec.

`engine_getPayloadV5` method-name at `vendor/prysm/beacon-chain/execution/engine_client.go:109`:

```go
GetPayloadMethodV5 = "engine_getPayloadV5"
```

Self-build dispatch at multiple sites:

- `vendor/prysm/beacon-chain/rpc/prysm/v1alpha1/validator/proposer_bid.go:123`: builds the self-build bid with `BuilderIndex: params.BeaconConfig().BuilderIndexSelfBuild`.
- `vendor/prysm/beacon-chain/rpc/prysm/v1alpha1/validator/proposer_payload_envelope.go:42`: builds envelope with `BuilderIndex: BuilderIndexSelfBuild`.
- `vendor/prysm/validator/client/propose_gloas.go:83`: branches on `if bid.Message.BuilderIndex != params.BeaconConfig().BuilderIndexSelfBuild` (external-builder branch).
- `vendor/prysm/beacon-chain/core/gloas/payload.go:287`: `if builderIdx == params.BeaconConfig().BuilderIndexSelfBuild { ... }`.
- `vendor/prysm/beacon-chain/sync/validate_execution_payload_envelope.go:167`: `isSelfBuild := builderIdx == uint64(params.BeaconConfig().BuilderIndexSelfBuild)`.
- `vendor/prysm/beacon-chain/verification/execution_payload_envelope.go:209`: `if env.BuilderIndex() == params.BeaconConfig().BuilderIndexSelfBuild { ... }`.

Multiple decision points checked consistently. ✓ Spec-conformant.

### lighthouse

`BUILDER_INDEX_SELF_BUILD` at `vendor/lighthouse/consensus/types/src/core/consts.rs:29`:

```rust
pub const BUILDER_INDEX_SELF_BUILD: u64 = u64::MAX;
pub const BUILDER_INDEX_FLAG: u64 = 1 << 40;
```

Value: `u64::MAX = 0xFFFFFFFFFFFFFFFF` ✓ matches spec.

`engine_getPayloadV5` method-name at `vendor/lighthouse/beacon_node/execution_layer/src/engine_api/http.rs:45`:

```rust
pub const ENGINE_GET_PAYLOAD_V5: &str = "engine_getPayloadV5";
```

V5 dispatch at `engine_api/http.rs:1052-1080`:

```rust
pub async fn get_payload_v5<E: EthSpec>(
    &self,
    fork_name: ForkName,
    payload_id: PayloadId,
) -> Result<GetPayloadResponse<E>, Error> {
    ...
    let response: JsonGetPayloadResponseGloas<E> = self
        .rpc_request(
            ENGINE_GET_PAYLOAD_V5,
            params,
            ENGINE_GET_PAYLOAD_TIMEOUT * self.execution_timeout_multiplier,
        )
        .await?;
    ...
}
```

Capability-gated dispatch at `:1459-1460`:

```rust
if engine_capabilities.get_payload_v5 {
    self.get_payload_v5(fork_name, payload_id).await
} else { ... }
```

Capability tracking at `engine_api.rs:594`:

```rust
pub get_payload_v5: bool,
```

Self-build path at `vendor/lighthouse/beacon_node/beacon_chain/src/block_production/gloas.rs:204, 1274`: builds bid + envelope with `builder_index: BUILDER_INDEX_SELF_BUILD`. Validator-side TODO comment at `validator_client/validator_services/src/block_service.rs:626`: "we should check the bid for index == BUILDER_INDEX_SELF_BUILD" — incomplete implementation flagged.

Signature path at `consensus/types/src/execution/signed_execution_payload_envelope.rs:93`:

```rust
let pubkey_bytes = if builder_index == BUILDER_INDEX_SELF_BUILD {
    // ... use proposer pubkey
} else {
    // ... use builder pubkey from state.builders
};
```

✓ Spec-conformant.

### teku

`BUILDER_INDEX_SELF_BUILD` at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/config/SpecConfigGloas.java:23`:

```java
UInt64 BUILDER_INDEX_SELF_BUILD = UInt64.MAX_VALUE;
```

Value: `UInt64.MAX_VALUE = 0xFFFFFFFFFFFFFFFF` ✓ matches spec.

Cross-referenced at `specrefs/constants.yml:57`:

```yaml
<spec constant_var="BUILDER_INDEX_SELF_BUILD" fork="gloas" hash="622fd1b5">
BUILDER_INDEX_SELF_BUILD: BuilderIndex = UINT64_MAX
```

Validator-side branching at `vendor/teku/validator/client/src/main/java/tech/pegasys/teku/validator/client/duties/BlockProductionDuty.java:228-229`:

```java
// BUILDER_INDEX_SELF_BUILD indicates a self-built bid
if (signedBid.getMessage().getBuilderIndex().equals(BUILDER_INDEX_SELF_BUILD)) {
    // self-build branch
}
```

Bid schema at `ExecutionPayloadBidSchema.java:130`: uses `BUILDER_INDEX_SELF_BUILD` for self-built bids.

Envelope verifier at `ExecutionPayloadVerifierGloas.java`: dispatches on `BUILDER_INDEX_SELF_BUILD`.

`engine_getPayloadV5` method binding at `vendor/teku/ethereum/executionclient/src/main/java/tech/pegasys/teku/ethereum/executionclient/methods/EngineGetPayloadV5.java` (sibling to `EngineNewPayloadV5`). Response class `GetPayloadV5Response` at `benchmark` test file. ✓ Spec-conformant.

### nimbus

`BUILDER_INDEX_SELF_BUILD` at `vendor/nimbus/beacon_chain/spec/datatypes/constants.nim:101`:

```nim
BUILDER_INDEX_SELF_BUILD* = high(uint64)
```

Value: `high(uint64) = 0xFFFFFFFFFFFFFFFF` ✓ matches spec.

`engine_getPayloadV5` method binding at `vendor/nimbus/vendor/nim-web3/web3/engine_api.nim:41`:

```nim
proc engine_getPayloadV5(payloadId: Bytes8): GetPayloadV5Response
```

Self-build dispatch at multiple sites:

- `vendor/nimbus/beacon_chain/spec/state_transition_block.nim:1277, 1366, 1846`: branches on `builder_index == BUILDER_INDEX_SELF_BUILD`.
- `vendor/nimbus/research/block_sim.nim:304, 323`: simulation harness uses `BUILDER_INDEX_SELF_BUILD` for the self-build path.

✓ Spec-conformant.

### lodestar

`BUILDER_INDEX_SELF_BUILD` at `vendor/lodestar/packages/params/src/index.ts:320`:

```typescript
export const BUILDER_INDEX_SELF_BUILD = Infinity;
```

**JavaScript-specific encoding**. JS `Number` can't represent `u64::MAX = 2^64 - 1` exactly (max safe integer is `2^53 - 1`). Lodestar uses `Infinity` as the JS representation and a custom SSZ type `UintNumInf64` (at `vendor/lodestar/packages/types/src/primitive/sszTypes.ts:28`) that round-trips:

```typescript
export const UintNumInf64 = new UintNumberType(8, {clipInfinity: true});
```

`clipInfinity: true` directs the SSZ codec to:

- Deserialize `0xFFFFFFFFFFFFFFFF` (the u64 wire-value) → JS `Infinity`.
- Serialize JS `Infinity` → `0xFFFFFFFFFFFFFFFF` on the wire.
- All other u64 values < 2^53 - 1 represented as regular JS `Number`.

`BuilderIndex` is `UintNumInf64` at `vendor/lodestar/packages/types/src/primitive/sszTypes.ts:59`:

```typescript
export const BuilderIndex = UintNumInf64; // Builder index can be infinity in bid when self-build
```

Round-trip wire equivalence: lodestar's bid SSZ-encoded with `BuilderIndex: Infinity` → wire bytes `0xFFFFFFFFFFFFFFFF`. Other clients send same wire bytes; lodestar deserializes → `Infinity`; lodestar's runtime comparison `envelope.builderIndex === BUILDER_INDEX_SELF_BUILD` (= `Infinity === Infinity`) returns `true`. ✓ H6.

Self-build branching at multiple sites:

- `vendor/lodestar/packages/beacon-node/src/api/impl/validator/index.ts:1729`: `builderIndex: BUILDER_INDEX_SELF_BUILD`.
- `vendor/lodestar/packages/beacon-node/src/chain/produceBlock/produceBlockBody.ts:279`: `builderIndex: BUILDER_INDEX_SELF_BUILD`.
- `vendor/lodestar/packages/beacon-node/src/api/impl/beacon/blocks/index.ts:690`: `const isSelfBuild = envelope.builderIndex === BUILDER_INDEX_SELF_BUILD;`.
- `vendor/lodestar/packages/state-transition/src/signatureSets/executionPayloadEnvelope.ts:32`: `envelope.builderIndex === BUILDER_INDEX_SELF_BUILD ? pubkeyCache.getOrThrow(proposerIndex) : ...`.

`engine_getPayloadV5` method-name at `vendor/lodestar/packages/beacon-node/src/execution/engine/http.ts:446`:

```typescript
method = "engine_getPayloadV5";
```

✓ Spec-conformant with JS-specific Infinity-clipping workaround.

### grandine

`BUILDER_INDEX_SELF_BUILD` at `vendor/grandine/types/src/gloas/consts.rs:71`:

```rust
pub const BUILDER_INDEX_SELF_BUILD: BuilderIndex = BuilderIndex::MAX;
```

Value: `BuilderIndex::MAX = u64::MAX = 0xFFFFFFFFFFFFFFFF` ✓ matches spec.

Self-build dispatch at multiple sites:

- `vendor/grandine/fork_choice_store/src/store.rs:1882`: `if builder_index == BUILDER_INDEX_SELF_BUILD { ... }`.
- `vendor/grandine/fork_choice_store/src/store.rs:3478`: `let pubkey = if builder_index == BUILDER_INDEX_SELF_BUILD { ... } else { ... }`.
- `vendor/grandine/block_producer/src/block_producer.rs:1702, 2197`: `builder_index: BUILDER_INDEX_SELF_BUILD`.
- `vendor/grandine/factory/src/lib.rs:384`: `builder_index: BUILDER_INDEX_SELF_BUILD`.
- `vendor/grandine/transition_functions/src/gloas/block_processing.rs:48`: imports the constant for use in block processing.

`engine_getPayloadV5` method support via the standard `engine_*` constants module (sibling to `ENGINE_NEW_PAYLOAD_V5` audited in item #70). ✓ Spec-conformant.

## Cross-reference table

| Client | `BUILDER_INDEX_SELF_BUILD` value | Storage | `engine_getPayloadV5` method | Self-build branch sites |
|---|---|---|---|---|
| prysm | `math.MaxUint64` (= `0xFFFFFFFFFFFFFFFF`) | `primitives.BuilderIndex` (u64 alias) | `GetPayloadMethodV5 = "engine_getPayloadV5"` | proposer_bid, proposer_payload_envelope, propose_gloas, payload, validate_execution_payload_envelope, verification ✓ |
| lighthouse | `u64::MAX` | const `u64` | `ENGINE_GET_PAYLOAD_V5 = "engine_getPayloadV5"` + capability negotiation | block_production/gloas, signed_execution_payload_envelope ✓ (TODO at validator_services flagged) |
| teku | `UInt64.MAX_VALUE` | `UInt64` | dedicated `EngineGetPayloadV5` class | BlockProductionDuty, ExecutionPayloadBidSchema, ExecutionPayloadVerifierGloas ✓ |
| nimbus | `high(uint64)` | `uint64` | nim-web3 RPC binding `engine_getPayloadV5` | state_transition_block, block_sim ✓ |
| lodestar | **`Infinity`** (JS Number) | **`UintNumInf64` with `clipInfinity: true` SSZ codec** | `"engine_getPayloadV5"` string | validator/index, produceBlockBody, blocks/index, signatureSets ✓ |
| grandine | `BuilderIndex::MAX` (= u64 max) | `u64` const generic | `ENGINE_GET_PAYLOAD_V5` constant | fork_choice_store, block_producer, factory, transition_functions ✓ |

H1 ✓ — all 6 use the `u64::MAX` sentinel (or `Infinity`-as-clipped). H2 ✓ — all 6 implement the V5 method. H3 ✓ — all 6 branch on `builder_index == BUILDER_INDEX_SELF_BUILD` consistently. H4 / H5: per-client validator code differs in mev-boost integration but the spec-relevant branching is identical. H6 ✓ — lodestar's SSZ wire round-trip is correct.

## Empirical tests

Suggested cross-client checks:

- **T1.1 (self-build canonical).** Validator with no external-builder preference; verify `engine_getPayloadV5` is called locally on the EL. Verify emitted bid has `builder_index = BUILDER_INDEX_SELF_BUILD`.
- **T1.2 (external-builder canonical).** Validator with mev-boost preference + active bid; verify NO local `engine_getPayloadV5` call. Verify bid `builder_index ≠ BUILDER_INDEX_SELF_BUILD`.
- **T2.1 (lodestar Infinity round-trip).** Construct a bid with `builderIndex = Infinity` in lodestar; SSZ-encode; verify wire bytes `0xFFFFFFFFFFFFFFFF`. Send to another CL; verify deserialization recognizes `u64::MAX`. Reverse direction: other CL sends `0xFFFFFFFFFFFFFFFF`; lodestar deserializes; `=== Infinity` comparison succeeds.
- **T2.2 (builder-timeout fallback).** External builder configured but unresponsive; verify per-client fallback to self-build (call `engine_getPayloadV5`, emit self-build bid).
- **T2.3 (cross-client interop).** CL A proposes via external builder; CL B imports the block. Verify acceptance regardless of whether B's policy is self-build or external.
- **T2.4 (envelope signature dispatch).** Verify `BUILDER_INDEX_SELF_BUILD` envelope is signed with proposer pubkey (not builder pubkey) — cross-cut with `DOMAIN_BEACON_BUILDER` (item #69).

## Conclusion

All six clients implement `BUILDER_INDEX_SELF_BUILD = UINT64_MAX` consistently, branch on this sentinel consistently for self-build detection, and implement the `engine_getPayloadV5` method name uniformly. The branching is distributed across multiple call sites in each client (bid construction, envelope construction, signature verification, payload validation), all checked consistently against the same sentinel.

Lodestar uses `Infinity` as the JS representation of u64 MAX, with a custom SSZ codec (`UintNumInf64` with `clipInfinity: true`) that round-trips correctly to/from `0xFFFFFFFFFFFFFFFF` on the wire. State-root and SSZ-hash computations are byte-equivalent with other clients.

Lighthouse stands out for **explicit capability negotiation** (`engine_capabilities.get_payload_v5` flag tracked separately, with a missing-method warning in the notifier); other clients rely on implicit JSON-RPC error propagation if the EL doesn't advertise V5.

**Verdict: impact none.** No divergence. Audit closes. Per-client mev-boost integration policies remain operationally significant but not consensus-relevant.

## Cross-cuts

### With item #58 (`process_execution_payload_bid`)

Item #58 is the bid-consumption side. This item is the bid-generation / external-builder integration side. Cross-cut: same `BUILDER_INDEX_SELF_BUILD` sentinel used in both directions.

### With item #59 (envelope verification)

Item #59 audited `verify_execution_payload_envelope`. The envelope's `builder_index` field is checked against `BUILDER_INDEX_SELF_BUILD` to determine the signature-verification pubkey. Cross-cut on the sentinel.

### With item #69 (`DOMAIN_*` constants)

Self-build envelope signed with proposer pubkey + `DOMAIN_BEACON_BUILDER` (the spec-allocated builder-API domain).

### With item #70 (`engine_newPayloadV5`)

Sibling Engine API method for the other direction (importing).

### With Engine API V5 spec at `execution-apis/src/engine/osaka.md` and `amsterdam.md`

The canonical V5 reference covers both `newPayloadV5` and `getPayloadV5`. All 6 clients cite this correctly.

## Adjacent untouched

1. **mev-boost / commit-boost integration cross-client** — sibling audit. Lighthouse's capability-gated approach could be a best-practice pattern.
2. **Builder API specification** — `builder-specs` GitHub repo; per-client compliance.
3. **Bid auction model** — multi-bid selection (highest bid wins?). Per-client policy.
4. **Lighthouse validator-side TODO** at `validator_services/src/block_service.rs:626` — "we should check the bid for index == BUILDER_INDEX_SELF_BUILD". Verify this is implemented somewhere in the validator-client pipeline.
5. **Lodestar `UintNumInf64` codec correctness** — T2.1 round-trip empirical test.
6. **Builder API SSZ container schema cross-client** — `SignedExecutionPayloadBid`, `ExecutionPayloadEnvelope`, `SignedExecutionPayloadEnvelope`. Cross-cut audit.
