---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: [15]
eips: [EIP-7732]
splits: []
# main_md_summary: TBD — drafting `engine_newPayloadV5` schema + V4↔V5 dispatch audit (Gloas Engine API; field additions over V4; fork-gated per-client dispatch)
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 70: `engine_newPayloadV5` schema + V4↔V5 dispatch

## Summary

> **DRAFT — hypotheses-pending.** Gloas Engine API version V5. Item #15 closed at V4 (Pectra) and the V4/V5-dispatch decision level. This item is the V5 wire schema audit per-field: parameter ordering, field types, nullable handling, and the per-client fork-gated decision of "use V4 vs V5 at this slot."

V5 carries the new ePBS fields (TBD: bid? envelope? execution_requests still as bytes-list?). Each client's Engine API client (`engine_client.go` / `execution_layer.rs` / Web3SignerClient / etc.) must:

1. Serialize the request with V5's field set.
2. Deserialize the V5 response (`PayloadStatusV1` extended? or unchanged?).
3. Fork-gate dispatch: `slot < gloas_fork_epoch → V4; slot >= gloas_fork_epoch → V5`.

A divergence here is a direct CL-EL communication failure on the Gloas activation slot.

## Question

Gloas `engine_newPayloadV5` schema per the EIP corpus (TBD: cite EIP + Engine API spec PR):

```
params: [
    ExecutionPayloadV5,            # Gloas-modified payload (TBD field set)
    Array[Bytes32],                # versioned hashes (unchanged from V3+)
    Bytes32,                       # parent beacon block root (unchanged from V4+)
    Array[Bytes],                  # execution_requests bytes-list (item #15)
    # Gloas additions (TBD):
    #   execution_payload_envelope?
    #   bid?
]
returns: PayloadStatusV1
```

Open questions:

1. **V5 ExecutionPayload field additions** — Gloas adds `block_hash` field semantics? Removes `block_hash` (since bid commits separately)? Verify spec.
2. **Engine API spec source** — `vendor/execution-apis/` or `ethereum/execution-apis` GitHub? Pin the canonical schema.
3. **`PayloadStatusV1` extensions** — Gloas might add error codes for "bid mismatch" or "envelope invalid".
4. **Per-client fork-gating decision** — `if slot ≥ gloas_fork_epoch: V5 else V4`. Per-client identical?
5. **V4/V5 simultaneous-support window** — clients may dispatch V4 for pre-Gloas slots and V5 for Gloas+. Verify no off-by-one at boundary.

## Hypotheses

- **H1.** All six clients implement `engine_newPayloadV5` with the same parameter ordering + types.
- **H2.** All six fork-gate the dispatch decision identically: V5 at `slot ≥ gloas_fork_epoch`, else V4.
- **H3.** All six handle the `PayloadStatusV1` response identically (no Gloas-specific error codes introduced).
- **H4.** All six accept V4 responses for pre-Gloas slots even if the EL has already upgraded (forward-compat).
- **H5.** All six handle JSON-RPC field naming / casing identically (camelCase vs snake_case mismatches in past have caused per-client bugs).
- **H6** *(forward-fragility)*. Engine API timeout / retry policy — per-client; not consensus-relevant but operationally significant.

## Findings

> **TBD — drafting.** Each client subsection below is a stub awaiting source review.

### prysm

TBD — drafting. Entry point: `vendor/prysm/beacon-chain/execution/engine_client.go NewPayload` (line 180 reviewed for item #15; needs V5 dispatch verification).

### lighthouse

TBD — drafting. Entry point: `vendor/lighthouse/beacon_node/execution_layer/src/engine_api/`.

### teku

TBD — drafting. Entry point: `vendor/teku/ethereum/executionlayer/src/main/java/tech/pegasys/teku/ethereum/executionlayer/`.

### nimbus

TBD — drafting. Entry point: `vendor/nimbus/beacon_chain/eth1/eth1_monitor.nim` or `engine_api_conversions.nim`.

### lodestar

TBD — drafting. Entry point: `vendor/lodestar/packages/beacon-node/src/execution/engine/`.

### grandine

TBD — drafting. Entry point: `vendor/grandine/execution_engine/` (TBD path).

## Cross-reference table

| Client | `engine_newPayloadV5` location | Fork-gating idiom (H2) | Response handling (H3) | JSON field casing (H5) |
|---|---|---|---|---|
| prysm | TBD | TBD | TBD | TBD |
| lighthouse | TBD | TBD | TBD | TBD |
| teku | TBD | TBD | TBD | TBD |
| nimbus | TBD | TBD | TBD | TBD |
| lodestar | TBD | TBD | TBD | TBD |
| grandine | TBD | TBD | TBD | TBD |

## Empirical tests

> **TBD — drafting.** EF Engine API test fixtures (if any). Devnet cross-client run with mixed EL pairings.

### Suggested fuzzing vectors

- **T1.1 (canonical V5 newPayload).** Standard Gloas block; verify all 6 CLs produce identical V5 JSON wire output.
- **T2.1 (V4↔V5 boundary).** Slot at `gloas_fork_epoch - 1` and `gloas_fork_epoch`; verify per-client dispatches V4 then V5.
- **T2.2 (cross-CL ↔ EL pairing matrix).** 6 CLs × 6 ELs = 36 pairs. Confirm all pairs work for V5.
- **T2.3 (JSON casing).** Per-client request inspection: `executionRequests` vs `execution_requests` vs `execution-requests`. Verify EL acceptance.

## Conclusion

> **TBD — drafting.** Source review pending. Expected outcome: all clients agree on the wire schema; minor JSON-casing differences may exist but be normalized by the EL.

## Cross-cuts

### With item #15 (CL-EL boundary encoding)

Item #15 closed at the bytes-list encoding + V4/V5 dispatch decision. This item is the next-layer audit on V5 specifically.

### With item #62 (`requestsHash`)

`engine_newPayloadV5` carries the bytes-list; the EL computes `requestsHash` from it. Cross-cut at the boundary.

### With item #71 (`engine_getPayloadV5`)

Sibling Engine API method for the other direction (proposing).

## Adjacent untouched

1. **`engine_forkchoiceUpdatedV5`** — fork choice update dispatch.
2. **`engine_getBlobsV2`** — Fulu blob-pool API.
3. **Engine API authentication (JWT)** — per-client header handling.
4. **CL↔EL gRPC/IPC alternatives** — non-HTTP transports.
