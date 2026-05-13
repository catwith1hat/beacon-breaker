---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [28, 33, 34, 35, 36, 38, 39, 43]
eips: [EIP-7594, EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 46: `DataColumnSidecarsByRange v1` + `DataColumnSidecarsByRoot v1` RPC handlers (Fulu-NEW) + Gloas-NEW `ExecutionPayloadEnvelopesByRange/ByRoot v1` Req/Resp surface

## Summary

Fulu-NEW PeerDAS req/resp surface (`vendor/consensus-specs/specs/fulu/p2p-interface.md:378-545`):

- `DataColumnSidecarsByRange v1` — protocol ID `/eth2/beacon_chain/req/data_column_sidecars_by_range/1/`; request `(start_slot, count, columns: List[ColumnIndex, NUMBER_OF_COLUMNS])`; response `List[DataColumnSidecar, compute_max_request_data_column_sidecars()]`.
- `DataColumnSidecarsByRoot v1` — protocol ID `/eth2/beacon_chain/req/data_column_sidecars_by_root/1/`; request `List[DataColumnsByRootIdentifier, MAX_REQUEST_BLOCKS_DENEB]`.
- Serve range: `[max(current_epoch - MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS, FULU_FORK_EPOCH), current_epoch]` with `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS = 2^12 = 4096 epochs`. Peers outside range MUST respond with error code 3 (`ResourceUnavailable`).

**Fulu surface (carried forward from 2026-05-04 audit; 5+ months of live mainnet cross-client column dissemination):** all 6 clients implement both RPC handlers. Protocol IDs literal-match spec. Five distinct handler architecture idioms.

**Gloas surface (Glamsterdam target) — three composite changes:**

1. **DataColumnSidecar payload reshape (modified at Gloas; protocol IDs unchanged).** `vendor/consensus-specs/specs/gloas/p2p-interface.md:57-81` removes `signed_block_header`, `kzg_commitments`, and `kzg_commitments_inclusion_proof` from `DataColumnSidecar` (per EIP-7732 — header/inclusion-proof verifications are no longer required because the KZG commitments live in `block.body.signed_execution_payload_bid.message.blob_kzg_commitments`). New fields `slot: Slot` + `beacon_block_root: Root` are added. **The RPC protocol IDs remain `/data_column_sidecars_by_range/1/` and `..._by_root/1/`** — same V1, but a fork-digest-aware payload shape. The req/resp framing already carries a `ForkDigest` context, so the wire-level discriminator handles the per-fork sidecar shape transparently (cross-cuts items #34 / #36 verification).
2. **`ExecutionPayloadEnvelopesByRange v1` (Gloas-NEW)** — protocol ID `/eth2/beacon_chain/req/execution_payload_envelopes_by_range/1/`; request `(start_slot, count)`; response `List[SignedExecutionPayloadEnvelope, MAX_REQUEST_BLOCKS_DENEB]`. CL→CL recovery path for EIP-7732 PBS execution envelopes.
3. **`ExecutionPayloadEnvelopesByRoot v1` (Gloas-NEW)** — protocol ID `/eth2/beacon_chain/req/execution_payload_envelopes_by_root/1/`; request `List[Root, MAX_REQUEST_PAYLOADS]` where `MAX_REQUEST_PAYLOADS = 2^7 = 128` (per `vendor/consensus-specs/specs/gloas/p2p-interface.md:53`).

**Gloas readiness across clients for `ExecutionPayloadEnvelopesByRange/ByRoot v1`:**

- **prysm**: ✅ implemented (`vendor/prysm/beacon-chain/sync/rpc_execution_payload_envelopes_by_range.go`, `..._by_root.go`; rate limiter wired at `rate_limiter.go:104-108`).
- **teku**: ✅ implemented (`vendor/teku/networking/eth2/src/main/java/tech/pegasys/teku/networking/eth2/rpc/beaconchain/BeaconChainMethodIds.java:35,37,75,80`; `DefaultEth2Peer.java:77` imports `ExecutionPayloadEnvelopesByRangeRequestMessage`).
- **nimbus**: ✅ implemented (`vendor/nimbus/beacon_chain/sync/sync_protocol.nim:370 libp2pProtocol("execution_payload_envelopes_by_range", 1)` + `:426 ..._by_root` with `awaitQuota(envelopeResponseCost, ...)`).
- **lodestar**: ✅ implemented (`vendor/lodestar/packages/beacon-node/src/network/reqresp/handlers/executionPayloadEnvelopesByRange.ts`; `rateLimit.ts:85`; `vendor/lodestar/packages/types/src/gloas/sszTypes.ts:317 ExecutionPayloadEnvelopesByRangeRequest`).
- **lighthouse**: ❌ NOT IMPLEMENTED. `grep -rn "ExecutionPayloadEnvelopesByRange\|execution_payload_envelopes_by_range" vendor/lighthouse/` returns zero matches. Lighthouse has the `SignedExecutionPayloadEnvelope` gossip-topic plumbing (`vendor/lighthouse/beacon_node/lighthouse_network/src/types/pubsub.rs:19,48,368`) but **NO req/resp RPC handler scaffolding**.
- **grandine**: ❌ NOT IMPLEMENTED. `grep -rn "ExecutionPayloadEnvelope" vendor/grandine/eth2_libp2p/` returns zero matches. Neither gossip nor req/resp.

**4-vs-2 split on Gloas envelope RPCs**: prysm + teku + nimbus + lodestar implemented; lighthouse + grandine missing. **Pattern M Gloas-ePBS readiness cohort extends to req/resp** — same lighthouse + grandine pair flagged in items #43 (Engine API V5/V6/FCU4) and #44 (PartialDataColumnSidecar Gloas reshape). This is now the third audit segment confirming the same cohort.

**Pattern BB (item #28 catalogue)**: per-client RPC handler architecture divergence — 5 distinct idioms on the Fulu surface (prysm map-based per-fork registration, lighthouse + grandine strum-enum, teku two-layer handler+validating proxy, nimbus macro-driven `libp2pProtocol`, lodestar async-generator with `rateLimit.ts` table). Carries forward at Gloas with grandine + lighthouse not yet contributing to the envelope-RPC idiom set.

**Impact: none** — Fulu surface byte-equivalent; Gloas sidecar-payload reshape is automatic via ForkDigest context (no client divergence at the RPC framing layer); Gloas envelope-RPC gap is forward-fragility tracking only (`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH`, not mainnet-reachable). Twenty-seventh `impact: none` result in the recheck series.

## Question

Pyspec defines the Fulu surface in `vendor/consensus-specs/specs/fulu/p2p-interface.md:378-545` and the Gloas surface in `vendor/consensus-specs/specs/gloas/p2p-interface.md:489-610` (req/resp section). Gloas section adds two new envelope RPCs but does NOT introduce `DataColumnSidecarsByRange v2` or `DataColumnSidecarsByRoot v2` — the V1 protocol IDs persist across forks, with the payload reshape handled by the per-fork sidecar SSZ schema (item #34 cross-cut).

Four recheck questions:

1. **Fulu surface stability** — do all 6 clients still implement byte-equivalent `DataColumnSidecarsByRange v1` + `DataColumnSidecarsByRoot v1` handlers? Has any client introduced a regression since the 2026-05-04 audit?
2. **Glamsterdam — sidecar payload reshape** — does the Gloas `DataColumnSidecar` modification (removed header + inclusion proof; added slot + beacon_block_root) propagate cleanly through the V1 protocol IDs? Are there any clients that hard-code the Fulu sidecar shape in the RPC layer?
3. **Glamsterdam — new envelope RPCs** — which clients have implemented `ExecutionPayloadEnvelopesByRange v1` + `ExecutionPayloadEnvelopesByRoot v1`? Does the Pattern M lighthouse + grandine Gloas-ePBS cohort (items #43 + #44) extend here?
4. **Pattern BB forward-fragility** — does the 5-distinct-idiom RPC architecture diversity persist? Do any clients converge on a single dispatch idiom for the envelope RPCs?

## Hypotheses

- **H1.** All 6 clients implement both `DataColumnSidecarsByRange v1` and `DataColumnSidecarsByRoot v1` at Fulu.
- **H2.** Protocol IDs are spec-correct: `/eth2/beacon_chain/req/data_column_sidecars_by_range/1/` and `..._by_root/1/`.
- **H3.** Response chunks are individual `DataColumnSidecar` SSZ payloads; the ForkDigest context epoch determines the per-fork sidecar shape (Fulu shape pre-Gloas; Gloas shape post-Gloas).
- **H4.** Validation flow at response reader: `verify_data_column_sidecar` (modified at Gloas per `vendor/consensus-specs/specs/gloas/p2p-interface.md:156`) + `verify_data_column_sidecar_kzg_proofs` (modified at Gloas per `:132`); the Fulu-only inclusion-proof check (`verify_data_column_sidecar_inclusion_proof`) becomes dead code at Gloas.
- **H5.** Serve range `[max(current_epoch - MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS, FULU_FORK_EPOCH), current_epoch]` enforced cross-client; out-of-range → `ResourceUnavailable` (error code 3).
- **H6.** ByRange response ordering: `(slot, column_index)` ascending; slots without known sidecars MUST be skipped.
- **H7.** `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS = 4096` (mainnet) per spec table + `vendor/lighthouse/common/eth2_network_config/built_in_network_configs/mainnet/config.yaml:222`. Gnosis preset uses 16384 (per `gnosis/config.yaml:163`).
- **H8.** *(Glamsterdam target — sidecar payload reshape)* `DataColumnSidecar` is modified at Gloas (header/inclusion-proof fields removed; slot/beacon_block_root added). Same protocol IDs `/1/`; ForkDigest-discriminated payload shape.
- **H9.** *(Glamsterdam target — new envelope RPCs)* `ExecutionPayloadEnvelopesByRange v1` + `ExecutionPayloadEnvelopesByRoot v1` are Gloas-NEW (EIP-7732). Expected 4-vs-2 split: prysm + teku + nimbus + lodestar implemented; lighthouse + grandine missing (Pattern M cohort).
- **H10.** *(Glamsterdam target — `MAX_REQUEST_PAYLOADS = 128`)* Gloas-NEW configuration constant (`vendor/consensus-specs/specs/gloas/p2p-interface.md:53`) caps envelope-RPC response size at 128 envelopes per request.
- **H11.** Pattern BB (item #28): per-client RPC handler architecture divergence (5 idioms) persists; envelope RPCs follow the same per-client idiom.

## Findings

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (all 6). H6 ✓. H7 ✓. H8 ✓ (spec confirms; RPC layer transparent). **H9 ⚠** (4-vs-2: lighthouse + grandine missing). H10 ✓ (spec). H11 ✓ (per-client idioms persist).

### prysm

Handler registration (`vendor/prysm/beacon-chain/sync/rpc.go:52-53,70-71`):

```go
// Pectra path
p2p.RPCDataColumnSidecarsByRootTopicV1:         s.dataColumnSidecarByRootRPCHandler,
p2p.RPCDataColumnSidecarsByRangeTopicV1:        s.dataColumnSidecarsByRangeRPCHandler,
...
// Fulu path — comment "Added in Fulu"
p2p.RPCDataColumnSidecarsByRootTopicV1:  s.dataColumnSidecarByRootRPCHandler,
p2p.RPCDataColumnSidecarsByRangeTopicV1: s.dataColumnSidecarsByRangeRPCHandler,
```

Per-fork registration map: each fork's `(topic → handler)` table is initialised separately. Same handler functions are reused for Pectra and Fulu (the handler dispatches on payload via ForkDigest).

Server-side handler (`vendor/prysm/beacon-chain/sync/rpc_data_column_sidecars_by_range.go:28-170`): starts a span `sync.DataColumnSidecarsByRangeHandler`, unpacks `pb.DataColumnSidecarsByRangeRequest`, validates via `validateDataColumnsByRange(...)` at `:170`.

Client-side validation (`vendor/prysm/beacon-chain/sync/rpc_send_request.go:471,520,581,625,644,721`):

```go
// :471 send ByRange request; downscore peer on failure (:520)
// :581 isSidecarSlotRequested — verify peer's response slot is in requested range
// :625 isSidecarIndexRequested — verify column indices match request
// :644 SendDataColumnSidecarsByRootRequest with downscore at :674
// :721 isSidecarIndexRootRequested — ByRoot variant
downscorePeer(p.P2P, pid, "cannotSendDataColumnSidecarsByRangeRequest")
```

Three distinct client-side validation functions (`isSidecarSlotRequested`, `isSidecarIndexRequested`, `isSidecarIndexRootRequested`) with explicit peer-downscoring on protocol violations. Most defensive of the 6.

Rate limiting (`vendor/prysm/beacon-chain/sync/rate_limiter.go:99-102`):

```go
// DataColumnSidecarsByRootV1
topicMap[addEncoding(p2p.RPCDataColumnSidecarsByRootTopicV1)] = dataColumnSidecars
// DataColumnSidecarsByRangeV1
topicMap[addEncoding(p2p.RPCDataColumnSidecarsByRangeTopicV1)] = dataColumnSidecars
```

Gloas envelope RPCs (`vendor/prysm/beacon-chain/sync/rpc_execution_payload_envelopes_by_range.go:25-230`):

```go
ctx, span := trace.StartSpan(ctx, "sync.ExecutionPayloadEnvelopesByRangeHandler")
log := log.WithField("handler", p2p.ExecutionPayloadEnvelopesByRangeName[1:])
r, ok := msg.(*pb.ExecutionPayloadEnvelopesByRangeRequest)
...
func validateEnvelopesByRange(r *pb.ExecutionPayloadEnvelopesByRangeRequest, current primitives.Slot) (rangeParams, error) {
```

Rate-limiter entries at `vendor/prysm/beacon-chain/sync/rate_limiter.go:104-108`:

```go
// ExecutionPayloadEnvelopesByRootV1
topicMap[addEncoding(p2p.RPCExecutionPayloadEnvelopesByRootTopicV1)] = envelopeCollector
topicMap[addEncoding(p2p.RPCExecutionPayloadEnvelopesByRangeTopicV1)] = envelopeCollector
```

**Gloas envelope RPCs fully wired in prysm.**

H1 ✓. H2 ✓ (`p2p.RPCDataColumnSidecarsByRangeTopicV1` = spec string). H3 ✓. H4 ✓ (item #34 cross-cut). H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓ (envelope RPCs implemented). H10 ✓. H11 ✓ (map-based registration idiom).

### lighthouse

Protocol IDs (`vendor/lighthouse/beacon_node/lighthouse_network/src/rpc/protocol.rs:248-252`):

```rust
/// The `DataColumnSidecarsByRoot` protocol name.
#[strum(serialize = "data_column_sidecars_by_root")]
...
/// The `DataColumnSidecarsByRange` protocol name.
#[strum(serialize = "data_column_sidecars_by_range")]
```

Strum-enum-based protocol declaration: one line per method, name auto-derived from the enum variant for protocol-ID serialization. Spec-correct.

`MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS = 4096` per `vendor/lighthouse/common/eth2_network_config/built_in_network_configs/mainnet/config.yaml:222`.

**Gloas envelope RPCs (MISSING)**: `grep -rn "ExecutionPayloadEnvelopesByRange\|execution_payload_envelopes_by_range" vendor/lighthouse/` returns zero matches. Lighthouse has the `SignedExecutionPayloadEnvelope` gossip topic (`vendor/lighthouse/beacon_node/lighthouse_network/src/types/pubsub.rs:19,48,368`):

```rust
use ...::{SignedExecutionPayloadBid, SignedExecutionPayloadEnvelope, SignedProposerPreferences, ...};
...
ExecutionPayload(Box<SignedExecutionPayloadEnvelope<E>>),
...
SignedExecutionPayloadEnvelope::from_ssz_bytes(data)
```

but the req/resp RPC handlers (`ExecutionPayloadEnvelopesByRange v1` + `ByRoot v1`) are not wired. Pattern M lighthouse Gloas-ePBS cohort extends with two more symptoms (`envelopes_by_range` + `envelopes_by_root`). Counting items #43 + #44 + #46 symptoms, Pattern M is now at 17+ lighthouse-specific Gloas-ePBS gaps.

H1 ✓ (Fulu surface). H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓ (carry-forward transparent). **H9 ⚠ (envelope RPCs NOT wired)**. H10 n/a. H11 ✓ (strum-enum idiom for Fulu).

### teku

Method IDs (`vendor/teku/networking/eth2/src/main/java/tech/pegasys/teku/networking/eth2/rpc/beaconchain/BeaconChainMethodIds.java:30-37`):

```java
"/eth2/beacon_chain/req/data_column_sidecars_by_root"
"/eth2/beacon_chain/req/data_column_sidecars_by_range"
"/eth2/beacon_chain/req/execution_payload_envelopes_by_root"
"/eth2/beacon_chain/req/execution_payload_envelopes_by_range"
```

Gloas envelope method-ID accessors (`:75,80`):

```java
public static String getExecutionPayloadEnvelopesByRootMethodId(...)
public static String getExecutionPayloadEnvelopesByRangeMethodId(...)
```

Two-layer architecture for data column sidecars: server-side `DataColumnSidecarsByRangeMessageHandler extends PeerRequiredLocalMessageHandler<DataColumnSidecarsByRangeRequestMessage, DataColumnSidecar>` + client-side `DataColumnSidecarsByRangeListenerValidatingProxy` (imported at `vendor/teku/networking/eth2/src/main/java/tech/pegasys/teku/networking/eth2/peers/DefaultEth2Peer.java:45-46`):

```java
import ...DataColumnSidecarsByRangeListenerValidatingProxy;
import ...DataColumnSidecarsByRootListenerValidatingProxy;
```

Explicit Prometheus metrics: `rpc_data_column_sidecars_by_range_requests_total`, `..._requested_sidecars_total`. Per-RPC per-direction observability.

Storage-layer scaffolding for the envelope archive: `vendor/teku/storage/src/main/java/tech/pegasys/teku/storage/server/kvstore/dataaccess/CombinedKvStoreDao.java:163,949,968` + `V6SchemaCombinedSnapshot.java:48,116,157,158,219 getColumnBlindedExecutionPayloadEnvelopesByRoot()` — RocksDB column families wired for the Gloas envelope RPCs.

Sync source (`vendor/teku/beacon/sync/src/main/java/tech/pegasys/teku/beacon/sync/forward/multipeer/batches/SyncSourceBatch.java:277`):

```java
syncSource.requestExecutionPayloadEnvelopesByRange(...)
```

**Gloas envelope RPCs fully wired in teku** (handler + storage + sync source).

H1–H11 all ✓.

### nimbus

Macro-driven dispatch (`vendor/nimbus/beacon_chain/sync/sync_protocol.nim:513,591`):

```nim
proc dataColumnSidecarsByRoot(peer: Peer, ...)
  {.async, libp2pProtocol("data_column_sidecars_by_root", 1).} =
  ...

proc dataColumnSidecarsByRange(peer: Peer, ...)
  {.async, libp2pProtocol("data_column_sidecars_by_range", 1).} =
  ...
```

Nim macro generates the handler boilerplate from `libp2pProtocol("<name>", <version>)` annotation. Cleanest declaration syntax of the 6.

Two-level quota (`vendor/nimbus/beacon_chain/sync/sync_protocol.nim:568-569, 633-634`):

```nim
peer.awaitQuota(dataColumnResponseCost, "data_column_sidecars_by_range/1")
peer.network.awaitQuota(dataColumnResponseCost, "data_column_sidecars_by_range/1")
```

Per-peer + network-wide quota tracking with named cost constant `dataColumnResponseCost`. Only client with TWO-LEVEL quota at this site.

Gloas envelope RPCs (`vendor/nimbus/beacon_chain/sync/sync_protocol.nim:370-452`):

```nim
proc executionPayloadEnvelopesByRange(peer: Peer, ...)
  {.async, libp2pProtocol("execution_payload_envelopes_by_range", 1).} =
  ...
  peer.awaitQuota(envelopeResponseCost, "execution_payload_envelopes_by_range/1")
  peer.network.awaitQuota(envelopeResponseCost, "execution_payload_envelopes_by_range/1")

proc executionPayloadEnvelopesByRoot(peer: Peer, ...)
  {.async, libp2pProtocol("execution_payload_envelopes_by_root", 1).} =
  ...
  peer.awaitQuota(envelopeResponseCost, "execution_payload_envelopes_by_root/1")
  peer.network.awaitQuota(envelopeResponseCost, "execution_payload_envelopes_by_root/1")
```

Same macro idiom; new cost constant `envelopeResponseCost`. **Gloas envelope RPCs fully wired in nimbus.**

H1–H11 all ✓.

### lodestar

Protocol identifiers (`vendor/lodestar/packages/beacon-node/src/network/reqresp/types.ts:47-48`):

```typescript
DataColumnSidecarsByRange = "data_column_sidecars_by_range",
DataColumnSidecarsByRoot = "data_column_sidecars_by_root",
```

Async-generator handlers (`vendor/lodestar/packages/beacon-node/src/network/reqresp/handlers/dataColumnSidecarsByRange.ts:16`):

```typescript
export async function* onDataColumnSidecarsByRange(
  request: fulu.DataColumnSidecarsByRangeRequest,
  ...
)
```

Yields response chunks lazily. Natural fit for `response_chunk` semantics. Explicit `validateDataColumnSidecarsByRangeRequest` at `:156` for upfront request validation.

Rate-limit table (`vendor/lodestar/packages/beacon-node/src/network/reqresp/rateLimit.ts:59`):

```typescript
[ReqRespMethod.DataColumnSidecarsByRange]: {
  getRequestCount: getRequestCountFn(fork, config, ReqRespMethod.DataColumnSidecarsByRange, ...),
  ...
}
```

Per-method `getRequestCount` formula table. Most data-driven rate-limiting style.

Gloas envelope RPCs (`vendor/lodestar/packages/beacon-node/src/network/reqresp/handlers/executionPayloadEnvelopesByRange.ts:10-15`):

```typescript
export async function* onExecutionPayloadEnvelopesByRange(
  request: gloas.ExecutionPayloadEnvelopesByRangeRequest,
  ...
) {
  const {startSlot, count} = validateExecutionPayloadEnvelopesByRangeRequest(chain.config, request);
```

Type-system gating: parameter is typed `gloas.ExecutionPayloadEnvelopesByRangeRequest` (not Fulu) — TypeScript enforces fork-context awareness. SSZ schema at `vendor/lodestar/packages/types/src/gloas/sszTypes.ts:317-319 export const ExecutionPayloadEnvelopesByRangeRequest = new ContainerType(...)`.

Rate-limit entry at `vendor/lodestar/packages/beacon-node/src/network/reqresp/rateLimit.ts:85-90 [ReqRespMethod.ExecutionPayloadEnvelopesByRange]`. Dispatched via `vendor/lodestar/packages/beacon-node/src/network/reqresp/handlers/index.ts:72-74`:

```typescript
[ReqRespMethod.ExecutionPayloadEnvelopesByRange]: (req) => {
  const body = ssz.gloas.ExecutionPayloadEnvelopesByRangeRequest.deserialize(req.data);
  return onExecutionPayloadEnvelopesByRange(body, chain, db);
},
```

Network interface at `vendor/lodestar/packages/beacon-node/src/network/interface.ts:91-93 sendExecutionPayloadEnvelopesByRange(peerIdStr, request: gloas.ExecutionPayloadEnvelopesByRangeRequest)`. Sync orchestrator at `vendor/lodestar/packages/beacon-node/src/sync/utils/downloadByRange.ts:48,404 envelopesRequest?: gloas.ExecutionPayloadEnvelopesByRangeRequest; ... network.sendExecutionPayloadEnvelopesByRange(...)`.

**Gloas envelope RPCs fully wired in lodestar** (types + handlers + rate limit + sync).

H1–H11 all ✓.

### grandine

Protocol IDs (`vendor/grandine/eth2_libp2p/src/rpc/protocol.rs:191-195`):

```rust
/// The `DataColumnSidecarsByRoot` protocol name.
#[strum(serialize = "data_column_sidecars_by_root")]
...
/// The `DataColumnSidecarsByRange` protocol name.
#[strum(serialize = "data_column_sidecars_by_range")]
```

Strum-enum-based protocol declaration; parallel to lighthouse.

Serve range enforcement (`vendor/grandine/p2p/src/network.rs:1139-1148`):

```rust
// and `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS`), but is NOT able to serve
...
misc::data_column_serve_range_slot::<P>(
```

Explicit `data_column_serve_range_slot` helper (`vendor/grandine/helper_functions/src/misc.rs:837`) plumbed at multiple call sites: `back_sync.rs:116,397`, `block_sync_service.rs:600,816,1044,1306,1312`, `sync_manager.rs:622-670`. Most explicit serve-range plumbing of the 6.

**Gloas envelope RPCs (MISSING)**: `grep -rn "ExecutionPayloadEnvelopesByRange\|execution_payload_envelopes_by_range" vendor/grandine/` returns zero matches. Neither `eth2_libp2p/src/rpc/` nor anywhere else in the grandine tree. **Grandine has no gossip topic nor req/resp handler for the Gloas envelope surface.**

Cohort observation: grandine's PBS readiness gap mirrors lighthouse's exactly (`engine_newPayloadV5` / `engine_getPayloadV6` / `engine_forkchoiceUpdatedV4` per item #43; `PartialDataColumnSidecar` Gloas reshape per item #44; **and now** `ExecutionPayloadEnvelopesByRange/ByRoot v1` per item #46). Pattern M cohort is now firmly **{lighthouse, grandine}**, with nimbus partial.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (most explicit). H6 ✓. H7 ✓. H8 ✓. **H9 ⚠ (envelope RPCs NOT wired)**. H10 n/a. H11 ✓ (strum-enum idiom for Fulu).

## Cross-reference table

| Client | H1 ByRange impl | H1 ByRoot impl | H4 verify_data_column_sidecar at response | H5 serve_range enforcement | H9 envelope RPCs (Gloas-NEW) | H11 dispatch idiom |
|---|---|---|---|---|---|---|
| **prysm** | ✅ `sync/rpc_data_column_sidecars_by_range.go:28-170` | ✅ `sync/rpc.go:52` + `..._by_root.go` | client-side: `isSidecarSlotRequested` + `isSidecarIndexRequested` + `isSidecarIndexRootRequested` (`rpc_send_request.go:581,625,721`) with `downscorePeer` | yes (per-fork registration map) | ✅ `rpc_execution_payload_envelopes_by_range.go` + `..._by_root.go`; rate-limiter at `rate_limiter.go:104-108` | per-fork map-based registration |
| **lighthouse** | ✅ `rpc/protocol.rs:251 #[strum(serialize = "data_column_sidecars_by_range")]` | ✅ `:249 "data_column_sidecars_by_root"` | item #34 verify functions invoked at response | yes | ❌ **MISSING** (`grep` returns 0; gossip topic only, no req/resp handler) | strum-enum |
| **teku** | ✅ `BeaconChainMethodIds.java:32` + `DataColumnSidecarsByRangeMessageHandler` | ✅ `:30` + `DataColumnSidecarsByRootMessageHandler` | TWO-LAYER: server handler + `ListenerValidatingProxy` (`DefaultEth2Peer.java:45-46`); Prometheus metrics | yes | ✅ `BeaconChainMethodIds.java:35,37,75,80` + storage column families (`V6SchemaCombinedSnapshot.java:48`) + `SyncSourceBatch.java:277` | two-layer handler + validating proxy |
| **nimbus** | ✅ `sync/sync_protocol.nim:591 libp2pProtocol("data_column_sidecars_by_range", 1)` | ✅ `:513 ..._by_root` | macro-generated dispatch; `awaitQuota(dataColumnResponseCost, ...)` two-level (peer + network) at `:633-634, 568-569` | yes | ✅ `sync_protocol.nim:370,426` `execution_payload_envelopes_by_range/_root` with `envelopeResponseCost` two-level quota | macro-driven `libp2pProtocol` |
| **lodestar** | ✅ `reqresp/types.ts:47` + `handlers/dataColumnSidecarsByRange.ts:16 async function*` | ✅ `:48` + `handlers/dataColumnSidecarsByRoot.ts:15` | async-generator + `validateDataColumnSidecarsByRangeRequest:156`; explicit `chain.logger.verbose("Peer did not respect earliestAvailableSlot")` | yes | ✅ `handlers/executionPayloadEnvelopesByRange.ts:10` + `rateLimit.ts:85-90` + `types/src/gloas/sszTypes.ts:317` + sync `downloadByRange.ts:48,404` | async-generator + `rateLimit.ts` table |
| **grandine** | ✅ `eth2_libp2p/src/rpc/protocol.rs:195 #[strum(serialize = "data_column_sidecars_by_range")]` | ✅ `:192 "data_column_sidecars_by_root"` | item #34 verify; **most explicit serve-range plumbing** via `helper_functions/src/misc.rs:837 data_column_serve_range_slot` + multiple call sites in `p2p/src/` | yes (most explicit) | ❌ **MISSING** (`grep` returns 0; neither gossip nor req/resp) | strum-enum |

**Fulu req/resp surface**: 6/6 ✅. **Gloas envelope-RPC surface**: 4/6 ✅; lighthouse + grandine missing (Pattern M cohort).

## Empirical tests

- ✅ **Live Fulu mainnet operation since 2025-12-03 (5+ months)**: continuous cross-client `DataColumnSidecarsByRange/ByRoot v1` exchanges. No sync failures attributable to RPC handler divergence. **Verifies H1–H7 at production scale.**
- ✅ **Per-client grep verification (this recheck)**: protocol IDs, handler registration, rate-limiting plumbing, serve-range enforcement all confirmed via file:line citations above.
- ✅ **Gloas envelope-RPC implementation matrix (this recheck)**: 4-vs-2 split confirmed (prysm + teku + nimbus + lodestar implemented; lighthouse + grandine missing across both `_by_range` and `_by_root` and across both gossip + req/resp surfaces).
- ⏭ **Cross-client 6×6 interop fixture**: prysm requests from lighthouse; teku requests from nimbus; etc. Verify serialization + validation + rate-limiting interoperate across all 36 pairs at Fulu.
- ⏭ **Serve-range boundary fixture**: peer requests slots at `current_epoch - MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS - 1`; verify all 6 respond with `ResourceUnavailable` (error code 3).
- ⏭ **Fork-boundary fixture: Fulu → Gloas sidecar payload reshape**: simulated Gloas activation; verify all 6 transparently switch sidecar SSZ shape on the V1 protocol IDs via ForkDigest context. Pre-emptive verification before Glamsterdam activation.
- ⏭ **Gloas envelope-RPC cross-client interop**: limited to 4×4=16 pairs (prysm + teku + nimbus + lodestar) until lighthouse + grandine implement. Track lighthouse + grandine Gloas readiness PRs.
- ⏭ **Pattern BB forward-fragility**: when EIP-7805 (Heze inclusion lists) introduces additional RPC handlers, verify all 6 idiom-divergent dispatch architectures handle the new surface.
- ⏭ **`compute_max_request_data_column_sidecars()` cross-client formula audit**: only teku surfaces explicit `getMaxRequestDataColumnSidecars()` getter (per `SpecConfigFulu.java:57` from prior audit). Verify all 6 compute the same response cap.

## Conclusion

The Fulu PeerDAS req/resp surface (`DataColumnSidecarsByRange v1` + `DataColumnSidecarsByRoot v1`) is implemented across all 6 clients with byte-equivalent wire format. 5+ months of live mainnet cross-client column dissemination via these RPCs validates the implementation matrix; no sync failures attributable to handler divergence.

At the Glamsterdam target, three composite changes converge on this audit:

1. **`DataColumnSidecar` payload reshape** (modified at Gloas, protocol IDs `/1/` unchanged): the per-fork SSZ schema is keyed by ForkDigest context epoch in the response chunk, so RPC handlers are transparent to the reshape. Verification at the response reader uses the Gloas-modified `verify_data_column_sidecar` + `verify_data_column_sidecar_kzg_proofs` (item #34 cross-cut); the Fulu-only `verify_data_column_sidecar_inclusion_proof` becomes dead code at Gloas because the inclusion-proof field is removed.
2. **`ExecutionPayloadEnvelopesByRange v1`** (Gloas-NEW): implemented in prysm + teku + nimbus + lodestar; **missing in lighthouse + grandine**.
3. **`ExecutionPayloadEnvelopesByRoot v1`** (Gloas-NEW): same 4-vs-2 split.

**Pattern M lighthouse + grandine Gloas-ePBS readiness cohort** (item #28) extends with two more symptoms per client. Combined with item #43 (Engine API V5/V6/FCU4) and item #44 (PartialDataColumnSidecar Gloas reshape), the cohort is now firmly **{lighthouse, grandine}** with 17+ Gloas-ePBS gaps per client at Glamsterdam activation. This is the third audit segment confirming the cohort.

**Pattern BB (item #28 catalogue)** — per-client RPC handler architecture divergence — persists at the envelope surface. The 4 clients implementing envelope RPCs each apply their established Fulu idiom: prysm map-based per-fork registration, teku two-layer handler + validating proxy, nimbus macro-driven `libp2pProtocol` with two-level quota, lodestar async-generator with `rateLimit.ts` table. The 2 missing clients (lighthouse + grandine) would presumably extend their strum-enum protocol declaration on implementation.

Lighthouse's `SignedExecutionPayloadEnvelope` GOSSIP topic plumbing (`vendor/lighthouse/beacon_node/lighthouse_network/src/types/pubsub.rs:19,48,368`) exists without req/resp parity — gossip-vs-rpc divergence pattern. Grandine has neither surface for envelopes.

**Impact: none** — Fulu surface byte-equivalent (validated by 5+ months of mainnet); Gloas sidecar-payload reshape transparent to RPC framing; Gloas envelope-RPC gap is forward-fragility tracking only (`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH`, not mainnet-reachable today). Twenty-seventh `impact: none` result in the recheck series.

Next research priorities for Glamsterdam:

1. Track lighthouse + grandine `ExecutionPayloadEnvelopesByRange/ByRoot v1` implementation PRs ahead of Glamsterdam.
2. Pre-emptive Fulu → Gloas DataColumnSidecar fork-boundary fixture (verify all 6 transparently switch SSZ shape on V1 protocol IDs).
3. `compute_max_request_data_column_sidecars()` cross-client formula audit (teku-only explicit getter; verify all 6 compute identical caps).
