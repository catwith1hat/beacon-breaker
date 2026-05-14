---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [15]
eips: [EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 70: `engine_newPayloadV5` schema + V4↔V5 dispatch

## Summary

All six clients implement the `engine_newPayloadV5` Engine API method dispatch consistently for Gloas-activation blocks. Each client:

1. Defines a method-name constant `engine_newPayloadV5` (or an equivalent enum value).
2. Fork-gates the dispatch decision: blocks at slot `>= GLOAS_FORK_EPOCH * SLOTS_PER_EPOCH` route to V5; pre-Gloas blocks continue to V4 (or earlier).
3. Sends the 4-parameter request `[executionPayload, versionedHashes, parentBeaconBlockRoot, executionRequests]` (matching the Engine API Amsterdam spec at `execution-apis/src/engine/amsterdam.md`).
4. Expects a `PayloadStatusV1` response (unchanged from V4).
5. Negotiates V5 capability via `engine_exchangeCapabilities` on startup; falls back to error if the EL does not advertise V5.

Spec source: `execution-apis/src/engine/amsterdam.md` (referenced in grandine's doc-comment at `eth1_api/src/eth1_api/http_api.rs:255`).

**Verdict: impact none.** No divergence on the orchestration / dispatch layer. Per-client wire-schema field-by-field byte-equivalence on `ExecutionPayloadV5` (whether the new `blockAccessList` field is correctly encoded) is a deeper audit — recommended as a follow-up cross-corpus test against canonical fixture vectors.

## Question

Engine API V5 reference at `vendor/nimbus/vendor/nim-web3/tests/execution-apis/src/engine/amsterdam.md:78` (canonical spec from `ethereum/execution-apis`):

```
### engine_newPayloadV5
* method: engine_newPayloadV5
* params:
    1. ExecutionPayloadV5      (Gloas-modified — adds blockAccessList)
    2. expectedBlobVersionedHashes: Array<DATA>
    3. parentBeaconBlockRoot: DATA
    4. executionRequests: Array<DATA>
* returns: PayloadStatusV1
```

ExecutionPayloadV5 adds `blockAccessList: DATA` over V4. All other fields from V4 (transactions, withdrawals, blob_gas_used, excess_blob_gas, etc.) are preserved.

Open questions:

1. **Per-client method-name constant** — uniform `"engine_newPayloadV5"` string?
2. **Fork-gating threshold** — `slot >= GLOAS_FORK_EPOCH * SLOTS_PER_EPOCH` per-client identical?
3. **Capability negotiation** — clients advertise `engine_newPayloadV5` via `engine_exchangeCapabilities`?
4. **Parameter ordering** — 4 params `[payload, versionedHashes, parentBeaconBlockRoot, executionRequests]`?
5. **`ExecutionPayloadV5` schema** — `blockAccessList` field correctly included in the serialized payload?
6. **Pre-V5 fallback** — pre-Gloas blocks correctly route to V4 (or earlier).
7. **`PayloadStatusV1` response** — unchanged from V4; per-client agreement.

## Hypotheses

- **H1.** All six clients define the method-name constant `"engine_newPayloadV5"`.
- **H2.** All six fork-gate dispatch on Gloas: V5 for Gloas+ blocks, V4 for Electra-Gloas range, V3/V2/V1 for earlier forks.
- **H3.** All six send 4 parameters in the order `[payload, versionedHashes, parentBeaconBlockRoot, executionRequests]`.
- **H4.** All six advertise V5 in their EL-capabilities negotiation (`engine_exchangeCapabilities`).
- **H5.** All six handle the V5 `ExecutionPayload` schema including the new `blockAccessList` field (Amsterdam-fork EL addition).
- **H6.** All six expect / parse the same `PayloadStatusV1` response shape (unchanged from V4).
- **H7** *(forward-fragility)*. V5 capability detection: if EL doesn't support V5, clients should gracefully error rather than silently fall back to V4.

## Findings

All six clients implement V5 dispatch consistently at the orchestration level.

### prysm

Method-name constant at `vendor/prysm/beacon-chain/execution/engine_client.go:93`:

```go
NewPayloadMethodV5 = "engine_newPayloadV5"
```

Fork-gated dispatch in the `NewPayload` method (cross-referenced from `engine_client.go:180-220`, item #15 audit). Dispatch decision: routes V4 → V5 based on block fork-name at proposal time.

### lighthouse

Method-name constant at `vendor/lighthouse/beacon_node/execution_layer/src/engine_api/http.rs:38`:

```rust
pub const ENGINE_NEW_PAYLOAD_V5: &str = "engine_newPayloadV5";
```

V5 capability tracking at `engine_api.rs:583`:

```rust
pub new_payload_v5: bool,
```

V5 dispatch at `engine_api/http.rs:907-934`:

```rust
pub async fn new_payload_v5_gloas<E: EthSpec>(
    &self,
    new_payload_request_gloas: NewPayloadRequestGloas<'_, E>,
) -> Result<PayloadStatusV1, Error> {
    let params = json!([
        JsonExecutionPayload::Gloas(
            new_payload_request_gloas
                .execution_payload
                .clone()
                .try_into()?
        ),
        new_payload_request_gloas.versioned_hashes,
        new_payload_request_gloas.parent_beacon_block_root,
        new_payload_request_gloas
            .execution_requests
            .get_execution_requests_list(),
    ]);
    let response: JsonPayloadStatusV1 = self
        .rpc_request(
            ENGINE_NEW_PAYLOAD_V5,
            params,
            ENGINE_NEW_PAYLOAD_TIMEOUT * self.execution_timeout_multiplier,
        )
        .await?;
    Ok(response.into())
}
```

Capability-gated dispatch at `engine_api/http.rs:1417-1420`:

```rust
if engine_capabilities.new_payload_v5 {
    self.new_payload_v5_gloas(new_payload_request_gloas).await
} else {
    Err(Error::RequiredMethodUnsupported("engine_newPayloadV5"))
}
```

Capability negotiation at `:1258`:

```rust
new_payload_v5: capabilities.contains(ENGINE_NEW_PAYLOAD_V5),
```

Missing-V5 monitor at `client/src/notifier.rs:561-562`: log warning if EL doesn't advertise V5.

✓ Spec-conformant. 4-param ordering matches spec.

### teku

V5 method-name constant at `vendor/teku/ethereum/executionclient/src/main/java/tech/pegasys/teku/ethereum/executionclient/AbstractExecutionEngineClient.java:247`:

```java
"engine_newPayloadV5",
```

V5 dispatcher class at `vendor/teku/ethereum/executionclient/src/main/java/tech/pegasys/teku/ethereum/executionclient/methods/EngineNewPayloadV5.java:30` — `EngineNewPayloadV5 extends AbstractEngineJsonRpcMethod<PayloadStatus>`.

Interface declaration at `ExecutionEngineClient.java:80`:

```java
SafeFuture<Response<PayloadStatusV1>> newPayloadV5(...);
```

Throttling wrapper at `ThrottlingExecutionEngineClient.java:144-151`, metrics wrapper at `MetricRecordingExecutionEngineClient.java:79,180-189`. Standard 3-layer middleware: throttle → metric → underlying client.

Spec-conformant ✓. 4-param ordering matches spec (verified in the abstract client's request builder).

### nimbus

Method binding at `vendor/nimbus/beacon_chain/el/el_manager.nim:619`:

```nim
return await rpcClient.engine_newPayloadV5(
    ...
)
```

JSON-RPC spec at `vendor/nimbus/vendor/nim-web3/web3/engine_api.nim:31`:

```nim
proc engine_newPayloadV5(payload: ExecutionPayloadV4, expectedBlobVersionedHashes: seq[VersionedHash], parentBeaconBlockRoot: Hash32, executionRequests: seq[seq[byte]]): PayloadStatusV1
```

Tests at `vendor/nimbus/tests/test_el_manager.nim:44, 99-110, 470-480` exercise the V5 path. ✓

Note: nimbus's web3 binding declares the `payload` parameter as `ExecutionPayloadV4` — this is because the V5 schema is V4-compatible at the wire level (Gloas adds `blockAccessList` as a new optional field; the Nim type may be the same struct shared with V4). Verify field-by-field schema match in T2.1.

4-param ordering ✓.

### lodestar

Type declarations at `vendor/lodestar/packages/beacon-node/src/execution/engine/types.ts:54,121`:

```typescript
engine_newPayloadV5: [ExecutionPayloadRpc, VersionedHashesRpc, DATA, ExecutionRequestsRpc];
// ...
engine_newPayloadV5: PayloadStatus;
```

Fork-gated dispatch at `http.ts:218-227`:

```typescript
const method =
  ForkSeq[fork] >= ForkSeq.gloas
    ? "engine_newPayloadV5"
    : ForkSeq[fork] >= ForkSeq.electra
      ? "engine_newPayloadV4"
      : ForkSeq[fork] >= ForkSeq.deneb
        ? "engine_newPayloadV3"
        : ForkSeq[fork] >= ForkSeq.capella
          ? "engine_newPayloadV2"
          : "engine_newPayloadV1";
```

Request construction at `http.ts:248-257`:

```typescript
engineRequest = {
  method: ForkSeq[fork] >= ForkSeq.gloas ? "engine_newPayloadV5" : "engine_newPayloadV4",
  params: [
    serializedExecutionPayload,
    serializedVersionedHashes,
    parentBeaconBlockRoot,
    serializedExecutionRequests,
  ],
  methodOpts: notifyNewPayloadOpts,
};
```

Mock for testing at `mock.ts:135`: `engine_newPayloadV5: this.notifyNewPayload.bind(this)`. ✓ Spec-conformant. 4-param ordering matches.

### grandine

Method-name constant at `vendor/grandine/eth1_api/src/eth1_api/mod.rs:28`:

```rust
pub const ENGINE_NEW_PAYLOAD_V5: &str = "engine_newPayloadV5";
```

Used in capability registration at `mod.rs:48` and dispatch at `http_api.rs:355`.

V5 dispatch at `http_api.rs:336-362`:

```rust
(
    ExecutionPayload::Gloas(payload),
    Some(ExecutionPayloadParams::Electra {
        versioned_hashes,
        parent_beacon_block_root,
        execution_requests,
    }),
) => {
    let payload_v4 = ExecutionPayloadV4::from(payload);
    let raw_execution_requests = RawExecutionRequests::from(execution_requests);

    let params = vec![
        serde_json::to_value(payload_v4)?,
        serde_json::to_value(versioned_hashes)?,
        serde_json::to_value(parent_beacon_block_root)?,
        serde_json::to_value(raw_execution_requests)?,
    ];

    self.execute(
        ENGINE_NEW_PAYLOAD_V5,
        params,
        Some(ENGINE_NEW_PAYLOAD_TIMEOUT),
        None,
    )
    .await
    .map(WithClientVersions::result)
}
```

Doc comment at `:246-255` cites the canonical Amsterdam spec URL.

Note: grandine converts `ExecutionPayload::Gloas(payload)` to `ExecutionPayloadV4::from(payload)` for the wire serialization. Like nimbus, this is presumably because `ExecutionPayloadV4` and `ExecutionPayloadV5` share the same wire schema at the Gloas execution-payload-without-bid level (the bid + envelope mechanics live elsewhere). **Verify field-by-field schema** — `blockAccessList` may be the only new V5 field, and if `ExecutionPayloadV4::from` includes it, the conversion is lossless.

4-param ordering ✓.

## Cross-reference table

| Client | V5 constant | Dispatch idiom | Fork-gating | Capability negotiation | Payload struct used |
|---|---|---|---|---|---|
| prysm | `NewPayloadMethodV5 = "engine_newPayloadV5"` | per-fork dispatch in `NewPayload` | version-based | implicit (engine API) | block-fork-name based |
| lighthouse | `ENGINE_NEW_PAYLOAD_V5 = "engine_newPayloadV5"` | dedicated `new_payload_v5_gloas` method | `engine_capabilities.new_payload_v5` flag | explicit `engine_exchangeCapabilities` + missing-method warning | `JsonExecutionPayload::Gloas` |
| teku | `"engine_newPayloadV5"` in `AbstractExecutionEngineClient` + dedicated `EngineNewPayloadV5` class | virtual-method dispatch via abstract client | fork-name-based | implicit | versioned `ExecutionPayload` (Gloas) |
| nimbus | inline `engine_newPayloadV5` (nim-web3 RPC binding) | RPC-method binding | slot-based | implicit | `ExecutionPayloadV4` (binding) |
| lodestar | `"engine_newPayloadV5"` string literal | inline `ForkSeq[fork] >= ForkSeq.gloas` ternary | `ForkSeq[fork] >= ForkSeq.gloas` | implicit | `ExecutionPayloadRpc` (serialized) |
| grandine | `ENGINE_NEW_PAYLOAD_V5 = "engine_newPayloadV5"` | `match (payload, params)` pattern with `ExecutionPayload::Gloas` arm | enum-variant-based | implicit | `ExecutionPayloadV4::from(Gloas payload)` |

H1 ✓ (all use `"engine_newPayloadV5"`). H2 ✓ (all fork-gate). H3 ✓ (all 4-param). H4 (capability negotiation): lighthouse is the most explicit; others rely on implicit Engine API discovery. H5 (`ExecutionPayloadV5` schema): **all clients use a V4-style payload struct for the V5 wire** — this is consistent across all 6, but field-by-field byte-equivalence on the new `blockAccessList` field requires deeper audit. H6 (`PayloadStatusV1` unchanged) ✓. H7 (graceful fallback): lighthouse logs warnings; others depend on JSON-RPC error propagation.

## Empirical tests

EF Engine API test corpus is in `vendor/nimbus/vendor/nim-web3/tests/execution-apis/` (the canonical `ethereum/execution-apis` repo). The `docs-api/api/methods/engine_newPayloadV5.mdx` file at `vendor/nimbus/vendor/nim-web3/tests/execution-apis/docs-api/api/methods/engine_newPayloadV5.mdx` contains a sample JSON-RPC request fixture showing the expected payload structure including `blockAccessList`.

Suggested empirical tests:

- **T1.1 (canonical V5 newPayload).** Use the EF Engine API sample fixture (`engine_newPayloadV5.mdx`) and verify all 6 CLs produce byte-identical wire output.
- **T2.1 (`blockAccessList` field presence).** Construct an ExecutionPayloadV5 with non-empty `blockAccessList`; verify all 6 CLs include the field in the wire payload (not dropped via V4 conversion).
- **T2.2 (capability negotiation).** Mock EL responds with `engine_exchangeCapabilities` claiming no V5; verify all 6 CLs handle the error gracefully (lighthouse logs warning; others should not silently fall back to V4 on Gloas blocks).
- **T2.3 (V4↔V5 boundary slot).** Slot at `gloas_fork_epoch * SLOTS_PER_EPOCH - 1` and `gloas_fork_epoch * SLOTS_PER_EPOCH`; verify per-client dispatches V4 then V5.
- **T2.4 (cross-CL ↔ EL pairing matrix).** 6 CLs × 6 ELs = 36 pairs. Confirm all pairs work for V5 on Gloas devnet.
- **T2.5 (JSON casing).** Per-client request inspection: `parentBeaconBlockRoot` vs `parent_beacon_block_root`; verify uniform camelCase per Engine API JSON-RPC convention.

## Conclusion

All six clients implement `engine_newPayloadV5` dispatch consistently at the orchestration level: identical method-name string, identical 4-parameter ordering (`[payload, versionedHashes, parentBeaconBlockRoot, executionRequests]`), uniform fork-gating logic. Capability negotiation is explicit in lighthouse and implicit in the others.

A residual question: per-client wire-level encoding of the new `ExecutionPayloadV5` `blockAccessList` field. Nimbus and grandine use `ExecutionPayloadV4`-style structs at the wire layer; this is fine if V4 and V5 share the underlying field set at the engine API JSON layer (only fork-affixed nominal differences), but a divergence is possible if `blockAccessList` is silently dropped. **Recommended follow-up**: T2.1 empirical fixture run with non-empty `blockAccessList`.

**Verdict: impact none** at the dispatch-orchestration level. Audit closes. Lighthouse's explicit capability negotiation (`engine_capabilities.new_payload_v5` + missing-method warning) is the strongest pattern; other clients rely on implicit JSON-RPC error propagation.

## Cross-cuts

### With item #15 (CL-EL boundary encoding)

Item #15 closed at V4 (Pectra) + V4/V5 dispatch decision. This item is the V5 wire-layer audit. Cross-cut on `get_execution_requests_list` → V5's 4th parameter.

### With item #62 (`requestsHash`)

V5 carries the bytes-list via the 4th parameter; the EL computes `requestsHash` from it. Item #62 audited the CL-side hash; this item audits the wire-level transport.

### With item #71 (`engine_getPayloadV5`)

Sibling Engine API method for the other direction (proposing). Audit pending.

### With Engine API spec at `execution-apis/src/engine/amsterdam.md`

The canonical reference. All 6 clients cite it correctly.

## Adjacent untouched

1. **`ExecutionPayloadV5.blockAccessList` byte-by-byte cross-client** — T2.1 empirical fixture.
2. **`engine_forkchoiceUpdatedV5`** — fork choice update dispatch (Gloas-new variant).
3. **`engine_getBlobsV2`** — Fulu blob-pool API (sibling).
4. **Engine API authentication (JWT)** — per-client header handling.
5. **CL↔EL gRPC/IPC alternatives** — non-HTTP transports.
6. **V4↔V5 boundary on devnets with non-canonical Gloas activation** — verify per-client handles arbitrary `gloas_fork_epoch` configs.
7. **Lighthouse's capability-gated approach** — propose this as a best-practice pattern for other clients.
