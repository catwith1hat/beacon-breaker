---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-12
builds_on: [2, 3, 13, 14]
eips: [EIP-7685, EIP-7732]
splits: [lighthouse, grandine]
# main_md_summary: lighthouse and grandine have not implemented `engine_newPayloadV5` (Gloas) — both still on V4 only; the other four clients (prysm, teku, nimbus, lodestar) have the V5 plumbing wired
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 15: `get_execution_requests_list` + `requestsHash` (EIP-7685, CL→EL boundary)

## Summary

EIP-7685 introduces a unified framework for the EL to receive CL-aggregated request lists (deposits, withdrawals, consolidations) and verify them as part of block-hash computation. The CL's job is twofold: (1) encode the three request lists into a flat `Sequence[bytes]` per the spec, with each entry being `request_type_byte || ssz_serialize(list)`, **filtering out empty lists**; (2) pass that list to the EL via `engine_newPayloadV4` at Pectra (or `V5` at Gloas). The EL computes `requestsHash = sha256(sha256(req0) || sha256(req1) || ... || sha256(reqN))` per EIP-7685 and uses it for block-hash verification.

**Pectra surface (the function body itself):** all six clients implement the encoding correctly — identical type bytes (`0x00`, `0x01`, `0x02`), spec-order serialization (deposits → withdrawals → consolidations), `type_byte || ssz_serialize(list)` concatenation, empty-list filtering, and `engine_newPayloadV4` Engine API dispatch. Two of the six (lighthouse, nimbus) additionally compute the EIP-7685 `requestsHash` locally for redundant validation; the other four delegate to the EL. No dedicated EF fixtures exist; implicit cross-validation via the 280-fixture cumulative coverage from items #2/#3/#4/#5/#6/#7/#8/#9/#12/#14 (all decoding ExecutionRequests from SSZ block bodies).

**Gloas surface (new at the Glamsterdam target):** the encoding helper itself (`get_execution_requests_list`) and the EIP-7685 hash algorithm are **unchanged** at Gloas — same type bytes, same order, same `type_byte || ssz_serialize(list)` format, same nested-SHA256 hash. What changes is the **Engine API method name**: `engine_newPayloadV4` (Pectra) → `engine_newPayloadV5` (Gloas). The Gloas V5 method extends V4 with the new fields required by EIP-7732 ePBS (`parent_execution_requests`, payload bid fields, etc.). At the CL-EL boundary, this is a direct version bump in the JSON-RPC call.

Survey of all six clients: prysm, teku, nimbus, lodestar have V5 wired into their Engine API plumbing; **lighthouse and grandine are still on V4 only** — lighthouse's HTTP client at `vendor/lighthouse/beacon_node/execution_layer/src/engine_api/http.rs:37` defines `ENGINE_NEW_PAYLOAD_V4 = "engine_newPayloadV4"` with NO V5 constant, and the Gloas-flavour method is misleadingly named `new_payload_v4_gloas` (line 886) — it dispatches V4 with a Gloas payload. Grandine's `vendor/grandine/eth1_api/src/eth1_api/mod.rs:22-25` lists only `ENGINE_NEW_PAYLOAD_V1..V4` with no V5 entry. **2-vs-4 split** — a different cohort from the lighthouse-only EIP-7732 pattern of items #7/#9/#12/#13/#14.

## Question

EIP-7685 spec (encoding):

```python
def get_execution_requests_list(execution_requests: ExecutionRequests) -> List[bytes]:
    requests = [
        (DEPOSIT_REQUEST_TYPE, execution_requests.deposits),
        (WITHDRAWAL_REQUEST_TYPE, execution_requests.withdrawals),
        (CONSOLIDATION_REQUEST_TYPE, execution_requests.consolidations),
    ]
    return [
        bytes([request_type]) + ssz_serialize(request_data)
        for request_type, request_data in requests
        if len(request_data) > 0  # filter empty lists
    ]
```

EIP-7685 spec (hash, computed by the EL):

```
requestsHash = sha256(sha256(req0) || sha256(req1) || ... || sha256(reqN))
```

where each `reqN` is the corresponding entry in the list from `get_execution_requests_list`. The CL sends the list of bytes (not the hash) to the EL via `engine_newPayloadV4(payload, ..., requests_list)`; the EL computes the hash itself and uses it for block-hash verification.

Nine hypotheses (H1–H9) cover type bytes, encoding order, format, empty-list filtering, list-not-hash dispatch, the Engine API method name, decoder rejection of malformed input, and the local `requestsHash` computation when present (2/6 clients).

**Glamsterdam target.** Gloas does not modify `get_execution_requests_list` or the EIP-7685 hash algorithm — the encoding remains identical (same type bytes, same order, same format, same nested-SHA256 hash). What changes is the **Engine API method**: at Gloas, the CL must call `engine_newPayloadV5` instead of `engine_newPayloadV4`. The V5 method extends V4 to carry the EIP-7732 ePBS fields (parent execution payload bid, parent execution requests, etc.). The `requests_list` parameter format is identical between V4 and V5 — same list-of-bytes shape.

The Gloas spec implicitly requires V5 by virtue of the V5 fields being part of the Gloas payload structure. The consensus-specs reference `verify_and_notify_new_payload` (`vendor/consensus-specs/specs/gloas/fork-choice.md:823`) without naming the JSON-RPC method directly; the canonical naming convention `engine_newPayloadV<N>` follows the execution-apis spec.

The hypothesis: *all six clients implement the EIP-7685 encoding identically at Pectra (H1–H8 + H9 conditional), and at the Glamsterdam target all six dispatch the encoded request list via `engine_newPayloadV5` instead of V4 (H10).*

**Consensus relevance**: this is the CL-EL boundary for Pectra/Gloas request framework. A divergence in the encoding (H1–H5, H7–H8) would cause cross-client desync at block-relay time — the proposer's CL produces hash X, the validator's CL produces hash Y, EL rejects, chain forks. A divergence in the Engine API version (H10) at Gloas would cause the EL to either reject the call entirely (if V4 is no longer accepted at Gloas) or accept it but misinterpret the new V5-specific fields. Either way, blocks produced by V4-only clients cannot land on a V5-required mainnet.

## Hypotheses

- **H1.** Type bytes: `DEPOSIT_REQUEST_TYPE = 0x00`, `WITHDRAWAL_REQUEST_TYPE = 0x01`, `CONSOLIDATION_REQUEST_TYPE = 0x02`.
- **H2.** Encoding order: deposits → withdrawals → consolidations (spec order, NOT alphabetical/reversed).
- **H3.** Per-entry format: type_byte (1 byte) concatenated with `ssz_serialize(list)`.
- **H4.** Empty lists are FILTERED OUT (no zero-length entry, no orphan type byte).
- **H5.** The encoded list is passed as a `Sequence[bytes]` to `engine_newPayloadV4` (or V5 at Gloas) — NOT pre-hashed.
- **H6.** Engine API method name: `engine_newPayloadV4` at Electra/Fulu (Pectra surface).
- **H7.** Decoders (when receiving from EL) enforce strict ascending type-byte order and reject duplicates.
- **H8.** Decoders reject empty data after a type byte (no zero-length payload).
- **H9.** When computing `requestsHash` locally: `sha256(sha256(req0) || sha256(req1) || ... )` per EIP-7685. (Only 2/6 clients compute locally — lighthouse and nimbus.)
- **H10** *(Glamsterdam target — Gloas Engine API V5)*. At the Gloas fork gate, all six clients dispatch the encoded request list via `engine_newPayloadV5` instead of `engine_newPayloadV4`. The V5 method carries the EIP-7732 ePBS fields in addition to the V4 fields; the `requests_list` parameter shape is identical (a list of `type_byte || ssz_serialize(list)` bytes).

## Findings

H1–H9 satisfied for the Pectra surface. **H10 fails for two clients**: lighthouse and grandine both lack `engine_newPayloadV5` entirely; their Engine API plumbing only knows V1–V4. The other four (prysm, teku, nimbus, lodestar) have V5 wired.

### prysm

`vendor/prysm/proto/engine/v1/electra.go:114-151` — `EncodeExecutionRequests`. Type bytes at `:19-23` (iota-based 0/1/2 — relies on iota ordering matching spec). `vendor/prysm/beacon-chain/execution/engine_client.go:180-249` — `NewPayload` with `NewPayloadMethodV4` (Electra) and `NewPayloadMethodV5` (Gloas) constants. The Gloas `engine_newPayloadV5` plumbing is described in `vendor/prysm/changelog/terence_gloas-engine-api-v5.md` (changelog entry confirming the V5 wiring).

No local `requestsHash` computation (delegated to EL).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 — n/a (delegated). **H10 ✓** (`NewPayloadMethodV5` constant wired).

### lighthouse

`vendor/lighthouse/consensus/types/src/execution/execution_requests.rs:48-72` — `get_execution_requests_list`. Type bytes via `RequestType` enum at `:94-116` with explicit `from_u8`/`to_u8` matches (most-explicit type-byte mapping; spec-traceable).

Local `requestsHash` computation (H9 ✓) at `:74-89` (`requests_hash`) — `sha256(sha256(req0) || ...)` per EIP-7685, used in `vendor/lighthouse/consensus/types/src/execution/block_hash.rs:42`.

`vendor/lighthouse/beacon_node/execution_layer/src/engine_api/http.rs`:
- Line 37: `pub const ENGINE_NEW_PAYLOAD_V4: &str = "engine_newPayloadV4";` — **no V5 constant**.
- Line 553/581/1200/1341-1345: `new_payload_v4` capability flag and dispatch logic.
- Line 828-855: `new_payload_v4_electra`.
- Line 857-885: `new_payload_v4_fulu`.
- Line 886-913: `new_payload_v4_gloas` — **dispatches V4 with a Gloas payload structure**. The method name is misleading: it's the Gloas-flavoured V4 call, not a true V5.

**No V5 method anywhere** in the Engine API plumbing. At Gloas, lighthouse calls `engine_newPayloadV4` with Gloas payload fields — which an EL that requires V5 will reject (and which an EL that accepts V4 will misinterpret the V4-extended fields if any).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓** (lighthouse is one of two clients with local `requestsHash`). **H10 ✗** (V4 only; no V5 entry).

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/datastructures/execution/versions/electra/ExecutionRequestsDataCodec.java:93-126` — `encode`. Type prefixes via per-request `REQUEST_TYPE_PREFIX = Bytes.of(REQUEST_TYPE)` static-final fields on each request class (strongest type-safety idiom across the six).

Engine API V5: `vendor/teku/ethereum/executionclient/src/main/java/tech/pegasys/teku/ethereum/executionclient/methods/EngineNewPayloadV5.java` — dedicated class for V5; sibling to `EngineNewPayloadV4`. Dispatch routes via the per-fork client classes (`AbstractExecutionEngineClient.java`, `MetricRecordingExecutionEngineClient.java`).

No local `requestsHash` (delegated to EL).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 — n/a. **H10 ✓** (`EngineNewPayloadV5.java` present).

### nimbus

`vendor/nimbus/beacon_chain/el/engine_api_conversions.nim:282-302` — `asEngineExecutionRequests`. Type bytes from `vendor/nimbus/beacon_chain/spec/datatypes/constants.nim:93-95`. The encoder uses Nim's `for index, value in array` semantics — `index` coincidentally matches `DEPOSIT_REQUEST_TYPE = 0`, `WITHDRAWAL_REQUEST_TYPE = 1`, `CONSOLIDATION_REQUEST_TYPE = 2` (relies on the convention; mitigated by compile-time `static doAssert` in `spec/helpers.nim:451-472`'s hash computation).

Local `requestsHash` (H9 ✓) at `vendor/nimbus/beacon_chain/spec/helpers.nim:451-472` (`computeRequestsHash`) — same EIP-7685 nested-SHA256 with compile-time `static doAssert` on type ordering.

Engine API V5: `vendor/nimbus/beacon_chain/el/el_manager.nim` references engine V5 via the vendored web3 binding at `vendor/nimbus/vendor/nim-web3/web3/engine_api.nim`. Plumbing confirmed wired.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓** (nimbus is the second of two clients with local `requestsHash`). **H10 ✓** (V5 wired via web3 binding).

### lodestar

`vendor/lodestar/packages/beacon-node/src/execution/engine/types.ts:529-546` — `serializeExecutionRequests`. Type bytes via `params/src/index.ts:308-310`; type-prefix helper `prefixRequests:488-494`.

Engine API V5: `vendor/lodestar/packages/beacon-node/src/execution/engine/http.ts:211-272` (`notifyNewPayload`); routes V4/V5 by ForkSeq. `vendor/lodestar/packages/beacon-node/src/execution/engine/types.ts` defines V5-specific types. `vendor/lodestar/packages/beacon-node/src/execution/engine/mock.ts` mock supports V5.

Local hash: lodestar computes `ssz.electra.ExecutionRequests.hashTreeRoot()` (SSZ Merkle root) — a DIFFERENT hash from EIP-7685's nested-SHA256, used for lodestar's own block-envelope verification scheme. Not comparable with lighthouse/nimbus's `requestsHash`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 — different semantic (SSZ Merkle root, not EIP-7685). **H10 ✓** (V4/V5 routing by ForkSeq).

### grandine

`vendor/grandine/execution_engine/src/types.rs:820-857` — Serde `Serialize` impl for `RawExecutionRequests`. Type bytes via `RequestType` enum at `:49-72` (with TWO methods: `request_type()` returning `&'static str` for hex serialization, `request_type_byte()` returning `u8` — risk of mismatch if a future spec change touches type values).

Engine API methods at `vendor/grandine/eth1_api/src/eth1_api/mod.rs:22-25`:

```rust
pub const ENGINE_NEW_PAYLOAD_V1: &str = "engine_newPayloadV1";
pub const ENGINE_NEW_PAYLOAD_V2: &str = "engine_newPayloadV2";
pub const ENGINE_NEW_PAYLOAD_V3: &str = "engine_newPayloadV3";
pub const ENGINE_NEW_PAYLOAD_V4: &str = "engine_newPayloadV4";
```

**No `ENGINE_NEW_PAYLOAD_V5` constant**. The `embed_api.rs` similarly lists only V1–V4. At Gloas, grandine cannot dispatch V5.

No local `requestsHash` (delegated to EL).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 — n/a. **H10 ✗** (no V5 constant; V4 only).

## Cross-reference table

| Client | Encoding location | Local `requestsHash` (H9) | Engine API V4 (Pectra) | Engine API V5 (Gloas, H10) |
|---|---|---|---|---|
| prysm | `proto/engine/v1/electra.go:114-151 EncodeExecutionRequests`; iota types at `:19-23` | not computed (delegated to EL) | `engine_client.go NewPayloadMethodV4` | **✓** (`NewPayloadMethodV5` per changelog entry `terence_gloas-engine-api-v5.md`) |
| lighthouse | `consensus/types/src/execution/execution_requests.rs:48-72 get_execution_requests_list`; explicit `RequestType::from_u8/to_u8` at `:94-116` | **✓** at `:74-89` (`requests_hash`), used in `block_hash.rs:42` | `engine_api/http.rs:37 ENGINE_NEW_PAYLOAD_V4` + `new_payload_v4_electra/_fulu/_gloas` | **✗** (no V5 constant; `new_payload_v4_gloas` at line 886 dispatches V4 with Gloas payload) |
| teku | `versions/electra/.../ExecutionRequestsDataCodec.java:93-126 encode`; per-request `REQUEST_TYPE_PREFIX = Bytes.of(REQUEST_TYPE)` static fields | not computed (delegated to EL) | `EngineNewPayloadV4.java` | **✓** (`EngineNewPayloadV5.java`) |
| nimbus | `el/engine_api_conversions.nim:282-302 asEngineExecutionRequests`; index-based loop relies on type coincidence | **✓** at `spec/helpers.nim:451-472 computeRequestsHash`, with compile-time `static doAssert` on type ordering | `el_manager.nim engine_newPayloadV4` via web3 binding | **✓** (V5 in vendored web3 binding `nim-web3/web3/engine_api.nim`) |
| lodestar | `beacon-node/src/execution/engine/types.ts:529-546 serializeExecutionRequests`; `prefixRequests:488-494` | different (`ssz.electra.ExecutionRequests.hashTreeRoot()` — SSZ Merkle root, not EIP-7685 nested-SHA256) | `engine/http.ts notifyNewPayload V4 route` | **✓** (`engine/http.ts:211-272` routes V4/V5 by ForkSeq) |
| grandine | `execution_engine/src/types.rs:820-857 RawExecutionRequests Serialize`; two-method type-byte mapping at `:49-72` | not computed (delegated to EL) | `eth1_api/src/eth1_api/mod.rs:25 ENGINE_NEW_PAYLOAD_V4` | **✗** (no V5 constant in `mod.rs:22-25`; embed_api.rs:46 lists only V1-V4) |

## Empirical tests

### Pectra-surface fixture status

There is **no dedicated EF fixture** for `get_execution_requests_list` or `requestsHash` at the time of this audit. The encoding is exercised IMPLICITLY via:

- **Sanity_blocks fixtures** that include `execution_requests` in the block body: `deposit_transition__*` (8 fixtures) and most other Pectra sanity_blocks tests.
- **Per-operation fixtures** from items #2 (consolidation_request), #3 (withdrawal_request), #14 (deposit_request) — the requests are decoded from SSZ block bodies; if encoding in any client diverged, sibling clients would reject the block.

**Implicit cross-validation evidence**: 280+ sanity_blocks/operation fixtures from items #2/#3/#4/#5/#6/#7/#8/#9/#12/#14 all decode `ExecutionRequests` from SSZ block bodies and route them through `process_operations` dispatch (item #13) — uniformly PASS on the four wired clients. This demonstrates encoding/decoding round-trip parity across all 4 wired clients on the Pectra surface.

### Gloas-surface

No Gloas Engine API fixtures yet exist (and the engine API itself lives in a separate spec). H10 is currently source-only — verified by walking each client's `ENGINE_NEW_PAYLOAD_V5` constant presence (or absence).

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — generate dedicated EIP-7685 encoding fixture set).** Pre-state + ExecutionRequests with known mix of (empty/non-empty) lists → expected `get_execution_requests_list()` bytes-list + expected EIP-7685 `requestsHash` (32 bytes). Direct CL-EL boundary fixture. Pure functions of the input, so trivially fuzzable.
- **T1.2 (priority — cross-client byte-for-byte encoding equivalence test).** Feed the same ExecutionRequests to all 6 encoders; hex-diff the output lists.
- **T1.3 (priority — cross-client EIP-7685 requestsHash equivalence).** Between lighthouse + nimbus (both compute the spec hash); compare byte-for-byte.
- **T1.4 (Glamsterdam-target — Gloas V5 dispatch).** Local devnet test: CL produces a Gloas-slot block, observe which Engine API method is invoked. Lighthouse and grandine will invoke V4 (incorrect at Gloas); the other four will invoke V5.

#### T2 — Adversarial probes
- **T2.1 (priority — decoder rejection contract).** Out-of-order types, empty data after type byte, duplicate types, type byte > 0x02. Each client's decoder MUST reject identically (lighthouse `RequestsError::InvalidOrdering` et al; teku `IllegalArgumentException`; etc.).
- **T2.2 (priority — `MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192` over-the-wire stress).** Block with 8192 DepositRequests would produce a `get_execution_requests_list` entry of size `1 + 192 × 8192 = ~1.6 MB` (DepositRequest is 192 bytes; the Engine API hex-encoding multiplies 2× for the string). Verify no OOM, no timeout, no integer overflow in the SSZ-serialize length-prefix.
- **T2.3 (defensive — nimbus index-based encoder coincidence).** Codify the compile-time `static doAssert DEPOSIT_REQUEST_TYPE.int == 0` etc. in `engine_api_conversions.nim` so a spec change to the type byte values doesn't silently break the index-based encoder.
- **T2.4 (defensive — prysm iota-based constants).** Replace `iota` with explicit `= 0x00` / `0x01` / `0x02` for spec-traceability (cosmetic but worthwhile).
- **T2.5 (defensive — grandine two-method type-byte mapping consolidation).** Consolidate the `request_type()` string and `request_type_byte()` u8 to a single source of truth (one method, two derived forms).
- **T2.6 (Glamsterdam-target — EL rejection of V4 at Gloas).** On a Gloas-required EL (Amsterdam), submit an `engine_newPayloadV4` call from a V4-only CL (lighthouse, grandine). Expected: EL rejects with `methodNotFound` or similar; the V4-only CL is unable to relay any Gloas-slot block. Critical reachability vector for the H10 divergence.

## Mainnet reachability

**Reachable on canonical traffic at Glamsterdam activation, on every Gloas-slot block** — every block at Gloas+ requires the CL to call the EL via the Gloas-compatible Engine API method to validate the new payload.

**Trigger.** The first Gloas-slot block. The CL receives the block, decodes the `ExecutionRequests` (unchanged encoding), and must dispatch via `engine_newPayloadV5` per the Gloas Engine API spec. On lighthouse and grandine, only V4 is wired — they would either:

- **Best case**: the EL is V4-backward-compatible and accepts V4 calls at Gloas slots, but the new V5-specific fields (`parent_execution_requests` etc. carried by EIP-7732 ePBS) are absent from the V4 call payload — the EL produces a block-hash that the rest of the network disagrees with.
- **Worst case**: the EL rejects V4 at Gloas slots as `methodNotFound` or `unsupportedFork` — lighthouse and grandine cannot propagate any Gloas-slot block.

Either way: chain split between (a) the 4-client cohort using V5 with full Gloas payload fields and (b) the 2-client cohort using V4 with missing fields.

**Severity.** Failure to propagate or validate any Gloas-slot block from block 1. Adversaries can't trigger this (it's a built-in client misconfiguration), but the divergence triggers automatically on every Gloas block once activation passes.

**Mitigation window.** Source-only at audit time; engine-API spec is separate from the consensus-specs repo, so the Gloas V5 spec isn't directly visible in this audit context. Closing requires:

1. Lighthouse to add `ENGINE_NEW_PAYLOAD_V5` constant in `engine_api/http.rs:37`, define `new_payload_v5_gloas` (or repurpose `new_payload_v4_gloas` with a V5 method name), and wire it into the fork-gated dispatch logic at `:1341-1345`.
2. Grandine to add `ENGINE_NEW_PAYLOAD_V5` constant in `eth1_api/src/eth1_api/mod.rs:22-25`, update `embed_api.rs:46` to list V5, and wire it into the payload dispatch path.

Reference implementations: prysm's `NewPayloadMethodV5` (Go), teku's `EngineNewPayloadV5.java` (Java), nimbus's web3-binding V5 (Nim), lodestar's `notifyNewPayload`-by-ForkSeq routing (TypeScript).

Different cohort from the lighthouse-only EIP-7732 ePBS family (items #7/#9/#12/#13/#14) — grandine joins lighthouse on this axis but is spec-compliant on the others. Lighthouse's Gloas-readiness gap is broader than grandine's.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H9) remain satisfied: identical type bytes (`0x00`, `0x01`, `0x02`), spec-order encoding, `type_byte || ssz_serialize(list)` format, empty-list filtering, `engine_newPayloadV4` Engine API dispatch, and decoder rejection of malformed input. Two of the six (lighthouse, nimbus) compute the EIP-7685 `requestsHash` locally for redundant validation; the other four delegate to the EL. 280+ implicit fixture invocations cross-validate the encoding round-trip on the Pectra surface.

**Glamsterdam-target finding (H10):** at Gloas, the Engine API method changes from V4 to V5. The encoding helper (`get_execution_requests_list`) and the EIP-7685 hash algorithm are unchanged — same type bytes, same order, same nested-SHA256. Only the JSON-RPC method name shifts. Four clients have V5 wired: prysm (`NewPayloadMethodV5` constant + changelog entry), teku (`EngineNewPayloadV5.java`), nimbus (V5 in vendored `nim-web3/web3/engine_api.nim`), lodestar (`engine/http.ts:211-272` fork-gated V4/V5 routing). **Two clients lack V5**: lighthouse (`engine_api/http.rs:37` defines only `ENGINE_NEW_PAYLOAD_V4`; the misleadingly-named `new_payload_v4_gloas` at line 886 dispatches V4 with a Gloas payload structure) and grandine (`eth1_api/src/eth1_api/mod.rs:22-25` lists only V1–V4; no V5 constant).

**2-vs-4 split** — a different cohort from the lighthouse-only EIP-7732 ePBS pattern (items #7/#9/#12/#13/#14). Lighthouse's Gloas-readiness gap is broader (six items now); grandine has narrower Gloas-readiness issues mostly limited to this Engine API version bump.

Combined `splits` = `[lighthouse, grandine]`. Impact `mainnet-glamsterdam` because the divergence materialises on every Gloas-slot block from block 1: V4-only clients cannot dispatch V5 calls and therefore cannot propagate Gloas-slot blocks correctly.

Notable per-client style differences:

- **prysm** uses iota-based type constants (relies on iota order matching spec); changelog entry confirms V5 wiring.
- **lighthouse** uses the most-explicit `RequestType::from_u8 / to_u8` matches; computes EIP-7685 `requestsHash` locally; Engine API V5 missing.
- **teku** uses static-final `REQUEST_TYPE_PREFIX = Bytes.of(REQUEST_TYPE)` per request class — strongest type-safety idiom; dedicated `EngineNewPayloadV5.java`.
- **nimbus** uses index-based encoder loop (relies on coincidence) but mitigated by compile-time `static doAssert` in the hash function; V5 via vendored web3 binding.
- **lodestar** uses `Uint8Array.set` for byte concatenation; computes `hashTreeRoot()` (SSZ Merkle root, different from EIP-7685); V4/V5 routing by ForkSeq.
- **grandine** uses TWO methods for the type-byte mapping (string + u8 — risk of mismatch); Engine API V5 missing.

Recommendations to the harness and the audit:

- Generate the **T1.1 / T1.2 / T1.3 EIP-7685 encoding fixture set** — pure functions of input ExecutionRequests; direct CL-EL boundary fixtures.
- File coordinated PRs against lighthouse and grandine to add `ENGINE_NEW_PAYLOAD_V5` constants and V5 dispatch methods. Reference implementations across the other four clients are listed above.
- Generate **T2.1 decoder-rejection contract test** — out-of-order types, empty data, duplicates, type > 0x02; cross-client rejection-mode equivalence.
- Generate **T2.2 `MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192` over-the-wire stress** — ~1.6 MB encoding; OOM/timeout/overflow check.
- Codify **nimbus's static doAssert on type-byte ordering** in the encoder (currently only in the hash function).
- Codify **prysm's iota → explicit `0x00` / `0x01` / `0x02`** for spec-traceability.
- Codify **grandine's two-method type-byte mapping → single source of truth**.

## Cross-cuts

### With items #2 / #3 / #14 (per-operation processors)

The encoding here is the wire format for `body.execution_requests.{deposits, withdrawals, consolidations}`. Items #2/#3/#14 process the decoded form. A divergence in encoding would surface here as cross-client deserialisation mismatch; a divergence in processing surfaces in those items' per-operation fixtures.

### With item #13 (`process_operations` dispatcher)

Item #13 routes the decoded `body.execution_requests` to the three per-operation processors at Pectra. At Gloas, per item #13 H10, this routing relocates to `apply_parent_execution_payload` — but the encoding/decoding semantics are unchanged. Lighthouse's item #13 H10 failure (still calling Electra dispatchers at Gloas) compounds with item #15 H10 (no V5 plumbing) — even if lighthouse fixed item #13 H10, it would still fail on the Engine API boundary.

### With Gloas EIP-7732 ePBS (items #7 / #9 / #12 / #13 / #14)

The Engine API V5 method extends V4 with the EIP-7732 ePBS fields (parent execution payload bid, parent execution requests, etc.). V5 is therefore the wire-format vehicle for the EIP-7732 surface — a client that fails V5 fails the entire ePBS pipeline at the CL-EL boundary. Lighthouse's failure here compounds with its other five EIP-7732 ePBS gaps; grandine fails here but is spec-compliant on items #7/#9/#12/#13/#14.

### With `verify_and_notify_new_payload` (`vendor/consensus-specs/specs/gloas/fork-choice.md:823`)

The fork-choice helper that invokes the EL via the Engine API. The consensus-specs reference doesn't name the JSON-RPC method directly; the version selection is in the execution-apis spec. At Gloas, this helper is invoked from the new Gloas fork-choice path; clients must route through V5 for it to validate correctly.

## Adjacent untouched

1. **Generate dedicated EIP-7685 encoding fixture set** — pre-state + ExecutionRequests with known mix → expected `get_execution_requests_list()` bytes-list + expected EIP-7685 `requestsHash` (32 bytes). Direct CL-EL boundary fixture.
2. **Cross-client byte-for-byte encoding equivalence test** — feed the same ExecutionRequests to all 6 encoders; hex-diff the output lists.
3. **Cross-client EIP-7685 requestsHash equivalence** — between lighthouse + nimbus (both compute the spec hash); compare byte-for-byte.
4. **Decoder rejection contract test** — out-of-order types, empty data, duplicates, type > 0x02.
5. **lighthouse's `requests_hash()` algorithm verification** — the implementation uses `DynamicContext` (incremental). Verify byte-for-byte parity with a direct `sha256(sha256(...) || ...)` reference.
6. **nimbus index-based encoder static-assert** — codify in `engine_api_conversions.nim`.
7. **prysm iota-based constants** — explicit `= 0x00` / `0x01` / `0x02` for spec-traceability.
8. **grandine's two-method type-byte mapping** — single source of truth.
9. **MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192 over-the-wire** — verify ~1.6 MB encoding handles cleanly.
10. **EL behaviour on malformed list** — local devnet test of out-of-order type bytes.
11. **Backward compatibility V3 → V4 / V4 → V5 fork-transition** — observe Engine API method switch on testnets at fork boundaries.
12. **Lighthouse's broader Gloas-readiness** — items #7 H10 + #9 H9 + #12 H11 + #13 H10 + #14 H9 + #15 H10 = six lighthouse-only EIP-7732 ePBS-related gaps.
13. **Grandine's narrow Gloas-readiness gap** — limited to this Engine API V5 axis; the EIP-7732 ePBS state-processing logic (items #7/#9/#12/#13/#14) is correctly implemented.
14. **Wire format hex encoding** — JSON-RPC `0x` prefix, lowercase vs uppercase hex, round-trip parity.
15. **lodestar's `hashTreeRoot()` semantic disambiguation** — document that this is a DIFFERENT hash from the EIP-7685 `requestsHash`. Both are valid for their respective uses.
