---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [2, 3, 13, 14]
eips: [EIP-7685, EIP-7732]
prysm_version: v3.2.2-rc.1-2535-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 15: `get_execution_requests_list` + `requestsHash` (EIP-7685, CL→EL boundary)

## Summary

EIP-7685 introduces a unified framework for the EL to receive CL-aggregated request lists (deposits, withdrawals, consolidations) and verify them as part of block-hash computation. The CL's job is twofold: (1) encode the three request lists into a flat `Sequence[bytes]` per the spec, with each entry being `request_type_byte || ssz_serialize(list)`, **filtering out empty lists**; (2) pass that list to the EL via `engine_newPayloadV4` at Pectra (or `V5` at Gloas). The EL computes `requestsHash = sha256(sha256(req0) || sha256(req1) || ... || sha256(reqN))` per EIP-7685 and uses it for block-hash verification.

**Pectra surface (the function body itself):** all six clients implement the encoding correctly — identical type bytes (`0x00`, `0x01`, `0x02`), spec-order serialization (deposits → withdrawals → consolidations), `type_byte || ssz_serialize(list)` concatenation, empty-list filtering, and `engine_newPayloadV4` Engine API dispatch. Two of the six (lighthouse, nimbus) additionally compute the EIP-7685 `requestsHash` locally for redundant validation; the other four delegate to the EL. No dedicated EF fixtures exist; implicit cross-validation via the 280-fixture cumulative coverage from items #2/#3/#4/#5/#6/#7/#8/#9/#12/#14 (all decoding ExecutionRequests from SSZ block bodies).

**Gloas surface (new at the Glamsterdam target):** the encoding helper itself (`get_execution_requests_list`) and the EIP-7685 hash algorithm are **unchanged** at Gloas — same type bytes, same order, same `type_byte || ssz_serialize(list)` format, same nested-SHA256 hash. What changes is the **Engine API method name**: `engine_newPayloadV4` (Pectra) → `engine_newPayloadV5` (Gloas). The Gloas V5 method extends V4 with the new fields required by EIP-7732 ePBS (`parent_execution_requests`, payload bid fields, etc.). At the CL-EL boundary, this is a direct version bump in the JSON-RPC call.

All six clients implement V5 dispatch at Gloas. The dispatch idioms vary per client (Go constant + fork-keyed method selection, Rust constant + capability gate, Java dedicated class, Nim vendored web3 binding, TypeScript ForkSeq-routed http call, Rust constant + match-arm dispatch), but the observable Engine API behaviour is uniform.

No splits at the current pins. The earlier finding (H10 lighthouse + grandine missing V5) was a stale-pin artifact. Lighthouse `unstable` HEAD `1a6863118` now has `ENGINE_NEW_PAYLOAD_V5` at `engine_api/http.rs:38` plus `new_payload_v5_gloas` (line 907) plumbed into the capability-gated dispatch at line 1417-1420. Grandine `glamsterdam-devnet-3` HEAD `15dd0225d4` has `ENGINE_NEW_PAYLOAD_V5` at `eth1_api/src/eth1_api/mod.rs:28` and the dispatch arm at `http_api.rs:354-361`.

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

**Consensus relevance**: this is the CL-EL boundary for Pectra/Gloas request framework. A divergence in the encoding (H1–H5, H7–H8) would cause cross-client desync at block-relay time. A divergence in the Engine API version (H10) at Gloas would cause the EL to either reject the call entirely or accept it but misinterpret the new V5-specific fields. Both surfaces are now uniform across all six clients.

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

H1–H10 satisfied across all six clients at the current Glamsterdam-target pins. The Pectra-surface bits (H1–H9) align on encoding shape and the EIP-7685 hash idiom; the Gloas-target H10 is implemented by all six clients via six distinct dispatch idioms.

### prysm

`vendor/prysm/proto/engine/v1/electra.go:114-151` — `EncodeExecutionRequests`. Type bytes at `:19-23` (iota-based 0/1/2 — relies on iota ordering matching spec). `vendor/prysm/beacon-chain/execution/engine_client.go:180-249` — `NewPayload` with `NewPayloadMethodV4` (Electra) and `NewPayloadMethodV5` (Gloas) constants. The Gloas `engine_newPayloadV5` plumbing is described in `vendor/prysm/changelog/terence_gloas-engine-api-v5.md` (changelog entry confirming the V5 wiring).

No local `requestsHash` computation (delegated to EL).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 — n/a (delegated). **H10 ✓** (`NewPayloadMethodV5` constant wired).

### lighthouse

`vendor/lighthouse/consensus/types/src/execution/execution_requests.rs:48-72` — `get_execution_requests_list`. Type bytes via `RequestType` enum at `:94-116` with explicit `from_u8`/`to_u8` matches (most-explicit type-byte mapping; spec-traceable).

Local `requestsHash` computation (H9 ✓) at `:74-89` (`requests_hash`) — `sha256(sha256(req0) || ...)` per EIP-7685, used in `vendor/lighthouse/consensus/types/src/execution/block_hash.rs:42`.

**H10 dispatch (Rust constant + capability gate).** `vendor/lighthouse/beacon_node/execution_layer/src/engine_api/http.rs`:
- Line 38: `pub const ENGINE_NEW_PAYLOAD_V5: &str = "engine_newPayloadV5";`
- Line 81: V5 listed in the supported-method set.
- Line 907: `new_payload_v5_gloas` — the V5 method implementation with Gloas payload structure.
- Line 1258: `new_payload_v5: capabilities.contains(ENGINE_NEW_PAYLOAD_V5)` — capability detection.
- Line 1417-1420: fork-gated dispatch:

```rust
if engine_capabilities.new_payload_v5 {
    self.new_payload_v5_gloas(new_payload_request_gloas).await
} else {
    Err(Error::RequiredMethodUnsupported("engine_newPayloadV5"))
}
```

The earlier `new_payload_v4_gloas` (line 886, retained for compatibility with V4-only ELs) coexists with the new V5 path; capability detection routes to V5 when available.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓** (lighthouse is one of two clients with local `requestsHash`). **H10 ✓**.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/datastructures/execution/versions/electra/ExecutionRequestsDataCodec.java:93-126` — `encode`. Type prefixes via per-request `REQUEST_TYPE_PREFIX = Bytes.of(REQUEST_TYPE)` static-final fields on each request class (strongest type-safety idiom across the six).

**H10 dispatch (Java dedicated class).** `vendor/teku/ethereum/executionclient/src/main/java/tech/pegasys/teku/ethereum/executionclient/methods/EngineNewPayloadV5.java` — dedicated class for V5; sibling to `EngineNewPayloadV4`. Dispatch routes via the per-fork client classes (`AbstractExecutionEngineClient.java`, `MetricRecordingExecutionEngineClient.java`).

No local `requestsHash` (delegated to EL).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 — n/a. **H10 ✓** (`EngineNewPayloadV5.java` present).

### nimbus

`vendor/nimbus/beacon_chain/el/engine_api_conversions.nim:282-302` — `asEngineExecutionRequests`. Type bytes from `vendor/nimbus/beacon_chain/spec/datatypes/constants.nim:93-95`. The encoder uses Nim's `for index, value in array` semantics — `index` coincidentally matches `DEPOSIT_REQUEST_TYPE = 0`, `WITHDRAWAL_REQUEST_TYPE = 1`, `CONSOLIDATION_REQUEST_TYPE = 2` (relies on the convention; mitigated by compile-time `static doAssert` in `spec/helpers.nim:451-472`'s hash computation).

Local `requestsHash` (H9 ✓) at `vendor/nimbus/beacon_chain/spec/helpers.nim:451-472` (`computeRequestsHash`) — same EIP-7685 nested-SHA256 with compile-time `static doAssert` on type ordering.

**H10 dispatch (vendored web3 binding).** `vendor/nimbus/beacon_chain/el/el_manager.nim` references engine V5 via the vendored web3 binding at `vendor/nimbus/vendor/nim-web3/web3/engine_api.nim`. Plumbing confirmed wired.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓** (nimbus is the second of two clients with local `requestsHash`). **H10 ✓**.

### lodestar

`vendor/lodestar/packages/beacon-node/src/execution/engine/types.ts:529-546` — `serializeExecutionRequests`. Type bytes via `params/src/index.ts:308-310`; type-prefix helper `prefixRequests:488-494`.

**H10 dispatch (TypeScript ForkSeq-routed http call).** `vendor/lodestar/packages/beacon-node/src/execution/engine/http.ts:211-272` (`notifyNewPayload`); routes V4/V5 by ForkSeq. `vendor/lodestar/packages/beacon-node/src/execution/engine/types.ts` defines V5-specific types. `vendor/lodestar/packages/beacon-node/src/execution/engine/mock.ts` mock supports V5.

Local hash: lodestar computes `ssz.electra.ExecutionRequests.hashTreeRoot()` (SSZ Merkle root) — a DIFFERENT hash from EIP-7685's nested-SHA256, used for lodestar's own block-envelope verification scheme. Not comparable with lighthouse/nimbus's `requestsHash`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 — different semantic (SSZ Merkle root, not EIP-7685). **H10 ✓**.

### grandine

`vendor/grandine/execution_engine/src/types.rs:820-857` — Serde `Serialize` impl for `RawExecutionRequests`. Type bytes via `RequestType` enum at `:49-72` (with TWO methods: `request_type()` returning `&'static str` for hex serialization, `request_type_byte()` returning `u8` — risk of mismatch if a future spec change touches type values).

**H10 dispatch (Rust constant + match-arm dispatch).** `vendor/grandine/eth1_api/src/eth1_api/mod.rs:28`:

```rust
pub const ENGINE_NEW_PAYLOAD_V5: &str = "engine_newPayloadV5";
```

Listed alongside V1–V4 at `:48`. The dispatch arm at `vendor/grandine/eth1_api/src/eth1_api/http_api.rs:354-361` selects V5 for the Gloas payload variant:

```rust
self.execute(
    ENGINE_NEW_PAYLOAD_V5,
    params,
    Some(ENGINE_NEW_PAYLOAD_TIMEOUT),
    None,
)
.await
```

Imported in `http_api.rs:51` alongside V3 and V4. Documented at `:246-255` referencing the Amsterdam execution-apis spec.

No local `requestsHash` (delegated to EL).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 — n/a. **H10 ✓**.

## Cross-reference table

| Client | Encoding location | Local `requestsHash` (H9) | Engine API V4 (Pectra) | Engine API V5 (Gloas, H10) |
|---|---|---|---|---|
| prysm | `proto/engine/v1/electra.go:114-151 EncodeExecutionRequests`; iota types at `:19-23` | not computed (delegated to EL) | `engine_client.go NewPayloadMethodV4` | ✓ Go constant + fork-keyed method selection (`NewPayloadMethodV5` per changelog `terence_gloas-engine-api-v5.md`) |
| lighthouse | `consensus/types/src/execution/execution_requests.rs:48-72 get_execution_requests_list`; explicit `RequestType::from_u8/to_u8` at `:94-116` | ✓ at `:74-89` (`requests_hash`), used in `block_hash.rs:42` | `engine_api/http.rs:37 ENGINE_NEW_PAYLOAD_V4` + `new_payload_v4_electra/_fulu/_gloas` | ✓ Rust constant + capability gate (`engine_api/http.rs:38 ENGINE_NEW_PAYLOAD_V5`; `new_payload_v5_gloas:907`; capability dispatch at `:1417-1420`) |
| teku | `versions/electra/.../ExecutionRequestsDataCodec.java:93-126 encode`; per-request `REQUEST_TYPE_PREFIX = Bytes.of(REQUEST_TYPE)` static fields | not computed (delegated to EL) | `EngineNewPayloadV4.java` | ✓ Java dedicated class (`EngineNewPayloadV5.java`) |
| nimbus | `el/engine_api_conversions.nim:282-302 asEngineExecutionRequests`; index-based loop relies on type coincidence | ✓ at `spec/helpers.nim:451-472 computeRequestsHash`, with compile-time `static doAssert` on type ordering | `el_manager.nim engine_newPayloadV4` via web3 binding | ✓ vendored web3 binding (V5 in `nim-web3/web3/engine_api.nim`) |
| lodestar | `beacon-node/src/execution/engine/types.ts:529-546 serializeExecutionRequests`; `prefixRequests:488-494` | different (`ssz.electra.ExecutionRequests.hashTreeRoot()` — SSZ Merkle root, not EIP-7685 nested-SHA256) | `engine/http.ts notifyNewPayload V4 route` | ✓ TypeScript ForkSeq-routed http call (`engine/http.ts:211-272` routes V4/V5 by ForkSeq) |
| grandine | `execution_engine/src/types.rs:820-857 RawExecutionRequests Serialize`; two-method type-byte mapping at `:49-72` | not computed (delegated to EL) | `eth1_api/src/eth1_api/mod.rs:25 ENGINE_NEW_PAYLOAD_V4` | ✓ Rust constant + match-arm dispatch (`eth1_api/src/eth1_api/mod.rs:28 ENGINE_NEW_PAYLOAD_V5`; `http_api.rs:354-361` Gloas-payload variant calls V5) |

## Empirical tests

### Pectra-surface fixture status

There is **no dedicated EF fixture** for `get_execution_requests_list` or `requestsHash` at the time of this audit. The encoding is exercised IMPLICITLY via:

- **Sanity_blocks fixtures** that include `execution_requests` in the block body: `deposit_transition__*` (8 fixtures) and most other Pectra sanity_blocks tests.
- **Per-operation fixtures** from items #2 (consolidation_request), #3 (withdrawal_request), #14 (deposit_request) — the requests are decoded from SSZ block bodies; if encoding in any client diverged, sibling clients would reject the block.

**Implicit cross-validation evidence**: 280+ sanity_blocks/operation fixtures from items #2/#3/#4/#5/#6/#7/#8/#9/#12/#14 all decode `ExecutionRequests` from SSZ block bodies and route them through `process_operations` dispatch (item #13) — uniformly PASS on the four wired clients. This demonstrates encoding/decoding round-trip parity across all 4 wired clients on the Pectra surface.

### Gloas-surface

No Gloas Engine API fixtures yet exist (and the engine API itself lives in a separate spec). H10 is currently source-only — verified by walking each client's `ENGINE_NEW_PAYLOAD_V5` constant presence.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — generate dedicated EIP-7685 encoding fixture set).** Pre-state + ExecutionRequests with known mix of (empty/non-empty) lists → expected `get_execution_requests_list()` bytes-list + expected EIP-7685 `requestsHash` (32 bytes). Direct CL-EL boundary fixture. Pure functions of the input, so trivially fuzzable.
- **T1.2 (priority — cross-client byte-for-byte encoding equivalence test).** Feed the same ExecutionRequests to all 6 encoders; hex-diff the output lists.
- **T1.3 (priority — cross-client EIP-7685 requestsHash equivalence).** Between lighthouse + nimbus (both compute the spec hash); compare byte-for-byte.
- **T1.4 (Glamsterdam-target — Gloas V5 dispatch).** Local devnet test: CL produces a Gloas-slot block, observe which Engine API method is invoked. All six clients should invoke V5 at Gloas; verify capability detection on each.

#### T2 — Adversarial probes
- **T2.1 (priority — decoder rejection contract).** Out-of-order types, empty data after type byte, duplicate types, type byte > 0x02. Each client's decoder MUST reject identically (lighthouse `RequestsError::InvalidOrdering` et al; teku `IllegalArgumentException`; etc.).
- **T2.2 (priority — `MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192` over-the-wire stress).** Block with 8192 DepositRequests would produce a `get_execution_requests_list` entry of size `1 + 192 × 8192 = ~1.6 MB` (DepositRequest is 192 bytes; the Engine API hex-encoding multiplies 2× for the string). Verify no OOM, no timeout, no integer overflow in the SSZ-serialize length-prefix.
- **T2.3 (defensive — nimbus index-based encoder coincidence).** Codify the compile-time `static doAssert DEPOSIT_REQUEST_TYPE.int == 0` etc. in `engine_api_conversions.nim` so a spec change to the type byte values doesn't silently break the index-based encoder.
- **T2.4 (defensive — prysm iota-based constants).** Replace `iota` with explicit `= 0x00` / `0x01` / `0x02` for spec-traceability (cosmetic but worthwhile).
- **T2.5 (defensive — grandine two-method type-byte mapping consolidation).** Consolidate the `request_type()` string and `request_type_byte()` u8 to a single source of truth (one method, two derived forms).
- **T2.6 (Glamsterdam-target — EL rejection of V4 at Gloas).** On a Gloas-required EL (Amsterdam), submit an `engine_newPayloadV5` call from each of the six CLs at a Gloas-slot block. Expected: EL accepts uniformly. Now a confirmation fixture rather than a divergence-detection fixture.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H9) remain satisfied: identical type bytes (`0x00`, `0x01`, `0x02`), spec-order encoding, `type_byte || ssz_serialize(list)` format, empty-list filtering, `engine_newPayloadV4` Engine API dispatch, and decoder rejection of malformed input. Two of the six (lighthouse, nimbus) compute the EIP-7685 `requestsHash` locally for redundant validation; the other four delegate to the EL. 280+ implicit fixture invocations cross-validate the encoding round-trip on the Pectra surface.

**Glamsterdam-target finding (H10 ✓ across all six clients):** at Gloas, the Engine API method changes from V4 to V5. The encoding helper (`get_execution_requests_list`) and the EIP-7685 hash algorithm are unchanged — same type bytes, same order, same nested-SHA256. Only the JSON-RPC method name shifts. Six distinct dispatch idioms: prysm uses a Go constant + fork-keyed method selection (`NewPayloadMethodV5`); lighthouse uses a Rust constant + capability gate (`ENGINE_NEW_PAYLOAD_V5` at `engine_api/http.rs:38` + `new_payload_v5_gloas` at `:907` + capability dispatch at `:1417-1420`); teku uses a Java dedicated class (`EngineNewPayloadV5.java`); nimbus uses the vendored web3 binding; lodestar uses a TypeScript ForkSeq-routed http call (`engine/http.ts:211-272`); grandine uses a Rust constant + match-arm dispatch (`ENGINE_NEW_PAYLOAD_V5` at `eth1_api/src/eth1_api/mod.rs:28` + `http_api.rs:354-361` Gloas-payload arm).

The earlier finding (H10 lighthouse + grandine missing V5) was a stale-pin artifact. Lighthouse had been on `stable` (v8.1.3) and grandine had been on mainline `develop`, neither of which carried the V5 wiring landed on the per-client Glamsterdam branches. With each client now on the branch where its actual Glamsterdam implementation lives, V5 is present across all six clients.

Notable per-client style differences:

- **prysm** uses iota-based type constants (relies on iota order matching spec); changelog entry confirms V5 wiring.
- **lighthouse** uses the most-explicit `RequestType::from_u8 / to_u8` matches; computes EIP-7685 `requestsHash` locally; V5 plumbing coexists with a retained `new_payload_v4_gloas` for V4-backward-compatible ELs.
- **teku** uses static-final `REQUEST_TYPE_PREFIX = Bytes.of(REQUEST_TYPE)` per request class — strongest type-safety idiom; dedicated `EngineNewPayloadV5.java`.
- **nimbus** uses index-based encoder loop (relies on coincidence) but mitigated by compile-time `static doAssert` in the hash function; V5 via vendored web3 binding.
- **lodestar** uses `Uint8Array.set` for byte concatenation; computes `hashTreeRoot()` (SSZ Merkle root, different from EIP-7685); V4/V5 routing by ForkSeq.
- **grandine** uses TWO methods for the type-byte mapping (string + u8 — risk of mismatch); V5 via match-arm dispatch on the Gloas payload variant.

Recommendations to the harness and the audit:

- Generate the **T1.1 / T1.2 / T1.3 EIP-7685 encoding fixture set** — pure functions of input ExecutionRequests; direct CL-EL boundary fixtures.
- Generate **T1.4 Gloas V5 dispatch fixture** — confirmation test on a Gloas-required EL across all six clients.
- Generate **T2.1 decoder-rejection contract test** — out-of-order types, empty data, duplicates, type > 0x02; cross-client rejection-mode equivalence.
- Generate **T2.2 `MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192` over-the-wire stress** — ~1.6 MB encoding; OOM/timeout/overflow check.
- Codify **nimbus's static doAssert on type-byte ordering** in the encoder (currently only in the hash function).
- Codify **prysm's iota → explicit `0x00` / `0x01` / `0x02`** for spec-traceability.
- Codify **grandine's two-method type-byte mapping → single source of truth**.

## Cross-cuts

### With items #2 / #3 / #14 (per-operation processors)

The encoding here is the wire format for `body.execution_requests.{deposits, withdrawals, consolidations}`. Items #2/#3/#14 process the decoded form. A divergence in encoding would surface here as cross-client deserialisation mismatch; a divergence in processing surfaces in those items' per-operation fixtures.

### With item #13 (`process_operations` dispatcher)

Item #13 routes the decoded `body.execution_requests` to the three per-operation processors at Pectra. At Gloas, per item #13 H10, this routing relocates to `apply_parent_execution_payload` — but the encoding/decoding semantics are unchanged. With item #13 H10 vacated and item #15 H10 vacated, the entire CL-EL boundary plus routing layer is uniform across all six clients.

### With Gloas EIP-7732 ePBS (items #7 / #9 / #12 / #13 / #14)

The Engine API V5 method extends V4 with the EIP-7732 ePBS fields (parent execution payload bid, parent execution requests, etc.). V5 is therefore the wire-format vehicle for the EIP-7732 surface. With all six EIP-7732 axes vacated (items #7 H9/H10, #9 H9, #12 H11/H12, #13 H10, #14 H9, this item H10), the entire ePBS pipeline is symmetric across all six clients at the current pins.

### With `verify_and_notify_new_payload` (`vendor/consensus-specs/specs/gloas/fork-choice.md:823`)

The fork-choice helper that invokes the EL via the Engine API. The consensus-specs reference doesn't name the JSON-RPC method directly; the version selection is in the execution-apis spec. At Gloas, this helper is invoked from the new Gloas fork-choice path; all six clients now route through V5 for it to validate correctly.

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
12. **Lighthouse's V4-backward-compatibility branch** — `new_payload_v4_gloas` retained at `engine_api/http.rs:886` for V4-only ELs; capability gate at `:1417-1420` routes to V5 when supported. Worth flagging as the cleanest factoring of the capability-detection pattern.
13. **Capability detection symmetry** — verify that all six clients gracefully fall back to V4 when an EL doesn't advertise V5 capability, or fail with a clear error rather than silently mis-dispatching.
14. **Wire format hex encoding** — JSON-RPC `0x` prefix, lowercase vs uppercase hex, round-trip parity.
15. **lodestar's `hashTreeRoot()` semantic disambiguation** — document that this is a DIFFERENT hash from the EIP-7685 `requestsHash`. Both are valid for their respective uses.
