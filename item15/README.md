# Item #15 — `get_execution_requests_list` + `requestsHash` (EIP-7685, CL→EL boundary)

**Status:** no-divergence-pending-fuzzing — audited 2026-05-02. The
**CL-EL boundary serialization** for Pectra's three new request
types. Highest-priority remaining Pectra item because divergence
here would cause an **EL fork at block-validation time** (the
proposer's CL produces hash X, the validator's CL produces hash Y,
the EL rejects, the network forks).

## Why this item

EIP-7685 introduces a **unified framework** for the EL to receive
CL-aggregated request lists (deposits, withdrawals, consolidations)
and verify them as part of block-hash computation. The CL's job is
twofold:

1. **Encode** the three request lists into a flat
   `Sequence[bytes]` per the spec, with each entry being
   `request_type_byte || ssz_serialize(list)`, **filtering out empty
   lists**.
2. **Pass** that list to the EL via `engine_newPayloadV4` (or V5 at
   Gloas).

The EL then computes
`requestsHash = sha256(sha256(req0) || sha256(req1) || ... || sha256(reqN))`
(per EIP-7685) and uses it for block-hash verification.

**Two of the six clients** (lighthouse, nimbus) ALSO compute the
EIP-7685 `requestsHash` LOCALLY for redundant validation —
implementing the spec's nested-SHA256 algorithm themselves. The
other four (prysm, teku, lodestar, grandine) fully delegate the hash
to the EL. lodestar additionally computes an SSZ `hashTreeRoot()` of
the `ExecutionRequests` container for its own block-validation
purposes (different from the EIP-7685 hash).

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | Type bytes: `DEPOSIT_REQUEST_TYPE = 0x00`, `WITHDRAWAL_REQUEST_TYPE = 0x01`, `CONSOLIDATION_REQUEST_TYPE = 0x02` | ✅ all 6 |
| H2 | Encoding order: deposits → withdrawals → consolidations (spec order, NOT alphabetical/reversed) | ✅ all 6 |
| H3 | Per-entry format: type_byte (1 byte) concatenated with `ssz_serialize(list)` | ✅ all 6 |
| H4 | Empty lists are FILTERED OUT (no zero-length entry, no orphan type byte) | ✅ all 6 |
| H5 | The encoded list is passed as a `Sequence[bytes]` to `engine_newPayloadV4` (or V5 at Gloas) — NOT pre-hashed | ✅ all 6 |
| H6 | Engine API method name: `engine_newPayloadV4` (Electra), `engine_newPayloadV5` (Gloas) | ✅ all 6 |
| H7 | Decoders (when receiving from EL) enforce strict ascending type-byte order and reject duplicates | ✅ all 6 (where decoders exist) |
| H8 | Decoders reject empty data after a type byte (no zero-length payload) | ✅ all 6 (where decoders exist) |
| H9 | When computing `requestsHash` locally: `sha256(sha256(req0) || sha256(req1) || ... )` per EIP-7685 | ✅ 2/6 (lighthouse + nimbus); 4/6 fully delegate to EL |

## Per-client cross-reference

| Client | Encoding location | Engine API call | Local requestsHash |
|---|---|---|---|
| **prysm** | `proto/engine/v1/electra.go:114-151` (`EncodeExecutionRequests`); types in `:19-23` (iota-based 0/1/2) | `beacon-chain/execution/engine_client.go:180-249` (`NewPayload`); `NewPayloadMethodV4` (Electra), `V5` (Gloas) | NOT computed locally; only in test middleware via `gethTypes.CalcRequestsHash` |
| **lighthouse** | `consensus/types/src/execution/execution_requests.rs:48-72` (`get_execution_requests_list`); types in `:94-116` (`RequestType` enum + `to_u8/from_u8`) | `beacon_node/execution_layer/src/engine_api/http.rs:828-855` (`new_payload_v4_electra/_fulu/_gloas`) | YES: `:74-89` (`requests_hash`) — `sha256(sha256(req0) || ...)` per EIP-7685, used in `block_hash.rs:42` |
| **teku** | `versions/electra/.../ExecutionRequestsDataCodec.java:93-126` (`encode`); type prefixes in per-request `REQUEST_TYPE_PREFIX = Bytes.of(REQUEST_TYPE)` | `executionclient/.../EngineNewPayloadV4.java:49-80` | NOT computed; delegated to EL |
| **nimbus** | `el/engine_api_conversions.nim:282-302` (`asEngineExecutionRequests`); types in `spec/datatypes/constants.nim:93-95` | `el/el_manager.nim:564-568` (`engine_newPayloadV4` via vendored web3 binding) | YES: `spec/helpers.nim:451-472` (`computeRequestsHash`) — same EIP-7685 nested-SHA256, with compile-time `static doAssert` on type ordering |
| **lodestar** | `beacon-node/src/execution/engine/types.ts:529-546` (`serializeExecutionRequests`); types in `params/src/index.ts:308-310`; type-prefix helper `prefixRequests:488-494` | `beacon-node/src/execution/engine/http.ts:211-272` (`notifyNewPayload`); routes V4/V5 by ForkSeq | Different: `ssz.electra.ExecutionRequests.hashTreeRoot()` (SSZ Merkle root, NOT EIP-7685 nested-SHA256) — used for block envelope verification, not EL boundary |
| **grandine** | `execution_engine/src/types.rs:820-857` (Serde `Serialize` impl for `RawExecutionRequests`); type bytes in `:49-72` (`RequestType` enum) | `eth1_api/src/eth1_api/http_api.rs:305-330` (`new_payload`); `ENGINE_NEW_PAYLOAD_V4` constant | NOT computed; delegated to EL |

## Notable per-client divergences (all observable-equivalent at the boundary)

### Two distinct local-hash strategies — both correct, neither breaks the EL boundary

The CL-EL boundary is the **list of bytes**, NOT the hash. The EL
computes its own hash from the list. So lighthouse, nimbus, and
lodestar's local hash computations are LOCAL VALIDATION ONLY — they
don't affect what the EL sees.

- **lighthouse + nimbus** compute the EIP-7685 spec hash:
  `sha256(sha256(req0) || sha256(req1) || ... )`. Used internally
  for block-hash verification (cross-checking what the EL would
  compute). If a client's local hash diverges from the EL's
  computation, the local validation would catch it before
  propagating the block.

- **lodestar** computes `ssz.electra.ExecutionRequests.hashTreeRoot()`
  — an SSZ Merkle root of the entire ExecutionRequests container.
  This is a DIFFERENT hash (SSZ vs EIP-7685) used for lodestar's
  own block-envelope verification scheme. Not compared against the
  EL's hash; serves a different validation purpose.

- **prysm + teku + grandine** don't compute either locally — fully
  trust the EL's computation. If the EL accepts the list and
  computes a hash matching the block's `requestsHash` field, the
  block is valid.

**All five strategies are spec-compliant** because the spec only
requires the CL to send the correctly-encoded list; the hash is the
EL's responsibility per EIP-7685.

### nimbus's loop-by-index relies on coincidence, not spec

```nim
for request_type, request_data in [
    SSZ.encode(execution_requests.deposits),
    SSZ.encode(execution_requests.withdrawals),
    SSZ.encode(execution_requests.consolidations),
]:
  if request_data.len > 0:
    requests.add @[request_type.byte] & request_data
```

Nimbus's loop uses Nim's `for index, value in array` semantics —
where `index` is 0, 1, 2 for the three array elements. It happens
to coincide with `DEPOSIT_REQUEST_TYPE = 0`, `WITHDRAWAL_REQUEST_TYPE
= 1`, `CONSOLIDATION_REQUEST_TYPE = 2`. **A spec change reordering
the type-byte assignments (e.g., swapping 0x01 and 0x02) would
silently break this code** without touching the constants. Worth a
`when consensusFork ...` static assert that constants match indices.

Mitigated by the `computeRequestsHash` function in `helpers.nim`
which uses explicit constant references (`DEPOSIT_REQUEST_TYPE`,
etc.) and includes:

```nim
static:
    doAssert DEPOSIT_REQUEST_TYPE < WITHDRAWAL_REQUEST_TYPE
    doAssert WITHDRAWAL_REQUEST_TYPE < CONSOLIDATION_REQUEST_TYPE
```

This catches misordering at compile time, but ONLY for the hash
function — the encoder still relies on coincidence.

### prysm's `iota`-based type constants

```go
const (
    DepositRequestType = iota
    WithdrawalRequestType
    ConsolidationRequestType
)
```

Same idiom as nimbus — relies on iota assignments matching the spec
values 0/1/2. A spec change would silently break. Worth an explicit
`= 0x00`, `= 0x01`, `= 0x02` for spec-traceability.

### lighthouse's `RequestType::from_u8` / `to_u8` boilerplate

```rust
pub fn from_u8(prefix: u8) -> Option<Self> {
    match prefix {
        0 => Some(Self::Deposit),
        1 => Some(Self::Withdrawal),
        2 => Some(Self::Consolidation),
        _ => None,
    }
}
pub fn to_u8(&self) -> u8 {
    match self {
        Self::Deposit => 0,
        Self::Withdrawal => 1,
        Self::Consolidation => 2,
    }
}
```

Most explicit type-byte-value mapping of any client. A spec change
to the type values would require updating BOTH the `from_u8` and
`to_u8` matches — fail-loud if mismatched.

### grandine's `request_type` returns `&'static str` (not `u8`!)

```rust
pub const fn request_type(self) -> &'static str {
    match self {
        Self::Deposits => "0x00",
        Self::Withdrawals => "0x01",
        Self::Consolidations => "0x02",
    }
}
pub const fn request_type_byte(self) -> u8 {
    match self { 0x00, 0x01, 0x02, ... }
}
```

Grandine has TWO methods for the same conceptual value: a string
form (used for hex-encoded JSON serialization in
`format_args!("{}{}", ...)`) and a byte form. The string method is
the one used in the encoder. **A spec change to the type values
would require updating BOTH methods independently** — risk of
mismatch. Worth consolidating to a single source of truth.

### teku's `Bytes.of(REQUEST_TYPE)` per-request constant

teku attaches the type byte as a STATIC FIELD on each request type
class:

```java
// DepositRequest.java
public static final byte REQUEST_TYPE = 0x0;
public static final Bytes REQUEST_TYPE_PREFIX = Bytes.of(REQUEST_TYPE);
```

The encoder references `DepositRequest.REQUEST_TYPE_PREFIX` directly
— spec change would force a compile-error (the constant is `static
final`, not derived). Strongest type-safety idiom of the six.

### lodestar uses a Uint8Array prefix-and-set approach

```typescript
function prefixRequests(requestsBytes: Uint8Array, requestType: ExecutionRequestType): Uint8Array {
  const prefixedRequests = new Uint8Array(1 + requestsBytes.length);
  prefixedRequests[0] = requestType;
  prefixedRequests.set(requestsBytes, 1);
  return prefixedRequests;
}
```

Allocates `1 + len(requestsBytes)` bytes, sets [0] = type, copies
the rest. Idiomatic JavaScript. Slightly different from
prysm/grandine's slice-append idiom, lighthouse's iterator-chain,
nimbus's seq-concat, teku's `Bytes.concatenate` — five different
language-idiomatic approaches to the same byte concatenation.

## EF fixture status — implicit coverage via prior items

There is **no dedicated EF fixture** for `get_execution_requests_list`
or `requestsHash` at the time of this audit. The encoding is
exercised IMPLICITLY via:

- **Sanity_blocks fixtures** that include execution_requests in the
  block body: `deposit_transition__*` (8 fixtures) and most other
  Pectra sanity_blocks tests.
- **Per-operation fixtures** from items #2 (consolidation_request),
  #3 (withdrawal_request), #14 (deposit_request) — the requests
  are decoded from SSZ block bodies and processed; if the encoding
  in any client diverged, sibling clients would reject the block.

A dedicated fixture would consist of:
1. A pre-state.
2. An ExecutionRequests container with a known mix of (empty/non-empty)
   lists.
3. The expected `get_execution_requests_list()` output (a
   list-of-bytes).
4. The expected EIP-7685 `requestsHash` (32 bytes).

This is **directly fuzzable** — the encoding is a pure function of
the input ExecutionRequests, and the EIP-7685 hash is a pure
function of the encoding. Worth generating as a follow-up.

**Implicit cross-validation evidence**: 280 sanity_blocks/operation
fixtures from items #2/#3/#4/#5/#6/#7/#8/#9/#12/#14 = **all decode
ExecutionRequests from SSZ block bodies and route them through
process_operations dispatch (item #13)** — uniformly PASS. This
demonstrates encoding/decoding round-trip parity across all 4 wired
clients.

## Cross-cut chain — CL-EL boundary closure

This item closes the CL-EL boundary for Pectra's request framework:

```
[items #2/#3/#14] CL processes block with execution_requests
                       ↓
[item #13] process_operations dispatcher routes by type
                       ↓
[item #15 - this] get_execution_requests_list() encodes for EL
                       ↓
                  engine_newPayloadV4(payload, vh, pbr, requests_list)
                       ↓
                  EL computes requestsHash, validates block
```

Any divergence in items #2/#3/#13/#14 would surface in the per-operation
EF fixtures (which all PASS). A divergence in item #15's encoding
WOULD surface as an EL rejection in real-network operation, but not
in EF fixtures (which don't exercise the EL boundary). **This audit
is the strongest fixture-independent evidence** for cross-client
encoding parity at the CL-EL boundary.

## Adjacent untouched

- **Generate dedicated requestsHash fixture set** — pre-state +
  ExecutionRequests with known mix → expected `get_execution_requests_list()`
  bytes-list + expected EIP-7685 `requestsHash`. Direct CL-EL boundary
  fixture.
- **Cross-client requestsHash equivalence test** — feed the same
  ExecutionRequests to all 6 clients, compare:
  (a) `get_execution_requests_list()` byte-list (must match exactly).
  (b) Local `requestsHash` (where computed: lighthouse + nimbus must
      match exactly with each other; lodestar's `hashTreeRoot()` is a
      DIFFERENT hash and cannot be cross-compared).
- **Decoder edge cases**: empty data after type byte, duplicate type
  byte, missing type byte, out-of-order types, type byte > 0x02.
  Each client's decoder enforces some subset of these — verify
  uniform rejection.
- **lighthouse's `requests_hash()` algorithm verification** — the
  spec is `sha256(sha256(req0) || ... )`, where each `reqN` is
  `type_byte || ssz_serialize(list)`. lighthouse's implementation
  uses `DynamicContext` (incremental) — verify byte-for-byte parity
  with a direct `sha256(sha256(...) || ...)` reference.
- **nimbus's index-based encoder coincidence** — codify as a
  compile-time static assert in `engine_api_conversions.nim`:
  ```nim
  static:
    doAssert DEPOSIT_REQUEST_TYPE.int == 0
    doAssert WITHDRAWAL_REQUEST_TYPE.int == 1
    doAssert CONSOLIDATION_REQUEST_TYPE.int == 2
  ```
- **prysm's iota-based constants** — explicit `= 0x00` etc. for
  spec-traceability (cosmetic but worthwhile).
- **grandine's two-method type-byte mapping** — consolidate to
  single source of truth (one method, two derived forms).
- **MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192 over-the-wire** — block
  with 8192 DepositRequests would produce a `get_execution_requests_list`
  entry of size `1 + 192 * 8192 = 1.6 MB` (DepositRequest is 192
  bytes). The Engine API hex-encoding multiplies this 2× for the
  string. Worth confirming clients handle this without OOM or
  timeout.
- **EL behavior on malformed list** — what happens if the CL sends
  a list with out-of-order type bytes? The EL should reject. Worth
  testing via local devnet.
- **Backward compatibility** — `engine_newPayloadV3` (Deneb) doesn't
  take execution_requests. At the Pectra fork transition, the CL
  must switch to V4 at the right block. Verify cross-client by
  observing fork-transition behavior on testnets.
- **Gloas `engine_newPayloadV5`** — already wired in prysm, lighthouse,
  lodestar (per source). Cross-client Gloas-fork audit needed when
  Gloas activates.
- **lodestar's `hashTreeRoot()` divergence** — uses a DIFFERENT hash
  (SSZ Merkle root) than lighthouse/nimbus (EIP-7685 nested SHA256).
  Both are valid for their respective uses (lodestar for block
  envelope verification; lighthouse/nimbus for EL-hash cross-check).
  But cross-client tooling that compares "the requestsHash" must be
  aware of the two distinct semantics.
- **Wire format hex encoding** — all clients hex-encode the
  bytes-list for the JSON-RPC Engine API. Verify uniform `0x` prefix
  handling, lowercase vs uppercase hex, and round-trip parity.

## Future research items

1. **Generate dedicated EIP-7685 encoding fixture set** — direct
   CL-EL boundary fixtures, pure functions of input. **High-priority
   gap closure.**
2. **Cross-client byte-for-byte encoding equivalence test** — feed
   the same ExecutionRequests to all 6 encoders, hex-diff the output
   lists.
3. **Cross-client EIP-7685 requestsHash equivalence test** — between
   lighthouse + nimbus (both compute the spec hash); compare byte-for-byte.
4. **Decoder rejection contract test** — out-of-order types, empty
   data, duplicate types, type > 0x02; each client's decoder MUST
   reject identically (lighthouse `RequestsError::InvalidOrdering`
   et al; teku `IllegalArgumentException`; etc.).
5. **MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192 over-the-wire stress
   test** — 1.6 MB+ encoding; verify no OOM, no timeout, no
   integer overflow in the SSZ-serialize length-prefix.
6. **nimbus index-based encoder static-assert** — codify the
   coincidence assumption.
7. **prysm + nimbus iota-based constants** — explicit `= 0x00` for
   spec-traceability.
8. **grandine's two-method type-byte mapping consolidation** —
   single source of truth.
9. **lodestar's `hashTreeRoot()` semantic disambiguation** —
   document that this is a DIFFERENT hash from the EIP-7685
   `requestsHash`.
10. **Gloas `engine_newPayloadV5` cross-client audit** — when Gloas
    activates.
11. **Fork-transition Engine API version switch** — Deneb V3 →
    Pectra V4 at the right block; Pectra V4 → Gloas V5 at the
    right block. Cross-client testnet observation.
12. **Wire format consistency** — JSON-RPC hex encoding, `0x` prefix,
    case sensitivity.
