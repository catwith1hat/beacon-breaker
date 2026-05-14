---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: [15]
eips: [EIP-7685]
splits: []
# main_md_summary: TBD — drafting `requestsHash` cross-client byte-for-byte Merkleization equivalence audit (direct CL-EL boundary)
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 62: `requestsHash` cross-client byte-for-byte Merkleization equivalence (EIP-7685, CL-EL boundary)

## Summary

> **DRAFT — hypotheses-pending.** Direct CL-EL boundary; a hash mismatch causes immediate EL fork. Item #15 closed at the encoding + V4/V5-dispatch level; this item is the **bytes-level Merkleization audit** — the actual 32-byte `requestsHash` value computed locally by lighthouse + nimbus (and delegated to the EL by prysm/teku/lodestar/grandine).

EIP-7685 defines `requestsHash` as:

```
requestsHash = sha256(sha256(req0) || sha256(req1) || ... || sha256(reqN))
```

where each `reqN` is `request_type_byte || ssz_serialize(list)` from `get_execution_requests_list` (item #15). The EL computes this hash and includes it in the block header for verification. Two CLs (lighthouse, nimbus per item #15 H9) compute it locally for redundant verification before passing the list to the EL via `engine_newPayloadV{4,5}`.

The audit:
1. **Byte-level equivalence**: lighthouse's local `requests_hash()` and nimbus's local `computeRequestsHash` must produce identical 32-byte outputs on identical inputs.
2. **Spec-conformance**: both implementations must match the EIP-7685 reference (nested SHA256, NOT SSZ Merkleization, NOT a Merkle tree, NOT keccak).
3. **Delegated-to-EL equivalence**: the four delegating clients (prysm, teku, lodestar, grandine) pass the encoded list to the EL; the EL's hash MUST match the local computation.
4. **Cross-CL ↔ EL parity**: a CL receiving a block from another CL must compute (or accept) the same `requestsHash` as the block's proposer.

## Question

EIP-7685 hash algorithm:

```python
def compute_requests_hash(requests_list: Sequence[bytes]) -> bytes32:
    """Per EIP-7685."""
    return sha256(b"".join(sha256(req) for req in requests_list))
```

Equivalent unrolled form (for fuzzing readability):

```python
def compute_requests_hash_unrolled(requests_list: Sequence[bytes]) -> bytes32:
    inner_concat = b""
    for req in requests_list:
        inner_concat += sha256(req).digest()
    return sha256(inner_concat).digest()
```

Open questions:

1. **Empty list** — `requests_list == []` (no execution requests in this block). What does `sha256(b"")` produce? `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` per EIP-7685, but verify cross-client.
2. **Single-element list** — `len == 1`. The outer hash is `sha256(sha256(req0))`. Verify the per-client implementations don't accidentally skip the outer hash for single-element lists.
3. **Big-endian vs little-endian byte ordering** — SHA256 output is byte-ordered; verify cross-client serialization to wire format.
4. **Streaming vs one-shot SHA256** — lighthouse uses `DynamicContext` (incremental); nimbus uses `MDigest` (one-shot). Both should produce identical output, but worth confirming.

## Hypotheses

- **H1.** Lighthouse's `requests_hash()` and nimbus's `computeRequestsHash` produce identical 32-byte outputs on identical input bytes-lists.
- **H2.** Both match the EIP-7685 reference: nested SHA256, outer = `sha256(concat(sha256(req_i) for i in 0..n))`.
- **H3.** Empty list (`[]`) produces `sha256(b"")` = `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
- **H4.** Single-element list produces `sha256(sha256(req0))`, NOT `sha256(req0)`.
- **H5.** The EL's `requestsHash` (computed by geth/erigon/besu/nethermind/reth/ethrex) on the same bytes-list matches the CL's local computation.
- **H6** *(consistency across V4/V5)*. The `requestsHash` field appears in the block header at both V4 (Pectra) and V5 (Gloas) Engine API methods; the algorithm is unchanged.
- **H7** *(forward-fragility)*. Streaming vs one-shot SHA256 cross-client byte-equivalence over a wide range of input sizes (including > 1 MB, since EIP-7685 supports `MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192` × 192 bytes ≈ 1.6 MB per entry).

## Findings

> **TBD — drafting.** Each client subsection below is a stub awaiting source review.

### prysm

TBD — drafting. **No local `requestsHash` computation** (delegates to EL via `engine_newPayloadV{4,5}`). Verify delegation correctness.

### lighthouse

TBD — drafting. Entry points: `vendor/lighthouse/consensus/types/src/execution/execution_requests.rs:74-89 requests_hash` and consumer at `block_hash.rs:42`. Uses `DynamicContext` (incremental SHA256).

### teku

TBD — drafting. **No local `requestsHash` computation** (delegates to EL). Verify delegation correctness.

### nimbus

TBD — drafting. Entry points: `vendor/nimbus/beacon_chain/spec/helpers.nim:451-472 computeRequestsHash`. Compile-time `static doAssert` on type-byte ordering.

### lodestar

TBD — drafting. **Different semantic locally** — computes `ssz.electra.ExecutionRequests.hashTreeRoot()` (SSZ Merkle root) for its own block-envelope verification scheme, NOT EIP-7685. The EL is responsible for the canonical `requestsHash`. Verify the lodestar local hash isn't mistakenly used in the engine-newPayload call.

### grandine

TBD — drafting. **No local `requestsHash` computation** (delegates to EL). Verify delegation correctness.

## Cross-reference table

| Client | Local `requestsHash` computed? | Algorithm | Empty-list output (H3) | Single-element output (H4) | Streaming vs one-shot |
|---|---|---|---|---|---|
| prysm | no (delegated) | n/a | n/a | n/a | n/a |
| lighthouse | yes | EIP-7685 nested SHA256 | TBD | TBD | streaming (`DynamicContext`) |
| teku | no (delegated) | n/a | n/a | n/a | n/a |
| nimbus | yes | EIP-7685 nested SHA256 | TBD | TBD | one-shot (`MDigest`) |
| lodestar | yes (DIFFERENT semantic — SSZ Merkle root, not EIP-7685) | SSZ `hashTreeRoot()` | (different output) | (different output) | (different) |
| grandine | no (delegated) | n/a | n/a | n/a | n/a |

## Empirical tests

> **TBD — drafting.** Plan to generate dedicated cross-client byte-equivalence fixtures.

### Suggested fuzzing vectors

- **T1.1 (priority — cross-client byte-equivalence fixture).** Generate 100 random `ExecutionRequests` inputs (covering empty deposits/withdrawals/consolidations, single-entry, multi-entry, near-cap). Compute `get_execution_requests_list` → bytes-list. Hex-encode and feed to:
  - lighthouse's `requests_hash()`,
  - nimbus's `computeRequestsHash`,
  - the EIP-7685 reference implementation (Python).
  Hex-diff outputs. All three must agree byte-for-byte.
- **T1.2 (priority — empty list).** `requests_list = []`. Verify both lighthouse and nimbus produce `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (sha256 of empty input).
- **T1.3 (priority — single-element).** `requests_list = [b"\x00" + ssz([])]` (just an empty deposits list with type byte). Verify nested SHA256 fires (not flat SHA256).
- **T1.4 (priority — max-deposit stress).** 8192 deposit-request entries (1.6 MB encoded). Verify no OOM, no overflow, identical output across lighthouse/nimbus/reference.
- **T2.1 (cross-CL ↔ EL round-trip).** CL A computes the local hash; passes bytes-list to its EL; EL computes its own hash; both hashes match. Devnet test.
- **T2.2 (cross-CL block import).** CL A proposes a block with `requestsHash = X`; CL B (different vendor) imports the block; verify CL B's local hash (or its EL's response) matches X.
- **T2.3 (lodestar SSZ vs EIP-7685 disambiguation).** Confirm lodestar's `hashTreeRoot()` is documented and NOT confused with EIP-7685's `requestsHash` in any consumer.

## Conclusion

> **TBD — drafting.** Source review pending; expected outcome: H1–H7 all hold (the EIP-7685 algorithm is too simple to diverge under careful implementation), but the audit is worth doing because:
> - A hash mismatch is immediate-EL-fork-causing — high consequence per slot.
> - Two CLs compute locally; four delegate. The two local computations need byte-equivalence proof.
> - The lodestar `hashTreeRoot()` quirk is a documented forward-fragility (a future refactor might accidentally substitute it).
> - No dedicated EF fixture exists; coverage is purely implicit via block-import success.

## Cross-cuts

### With item #15 (CL-EL boundary encoding)

Item #15 closed at the encoding level (`get_execution_requests_list` produces identical bytes-list across all 6 CLs) and at the V4/V5-dispatch level. This item closes the third leg: the hash of that bytes-list must be byte-identical across CLs that compute it locally.

### With evm-breaker's EL-side `requestsHash` audit

The EL clients (geth/erigon/besu/nethermind/reth/ethrex) compute `requestsHash` independently per EIP-7685. This item's CL ↔ EL parity check is a cross-corpus audit — relies on the EL side being correct (which evm-breaker should have audited or is auditing).

### With Engine API V5 (item #15 H10)

V5 carries the new ePBS fields; `requestsHash` semantics are unchanged. Verify the V5 RPC schema preserves the field name and byte encoding.

## Adjacent untouched

1. **EIP-7685 Python reference implementation** — pin a canonical reference (`vendor/consensus-specs/.../get_execution_requests_list` if it exists; otherwise EL spec or PR).
2. **`MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192` over-the-wire** — 1.6 MB encoded list. Verify Engine API JSON-RPC tolerates this size.
3. **`hashTreeRoot()` vs `requestsHash` lodestar disambiguation** — document semantic difference; verify no consumer confuses them.
4. **Streaming vs one-shot SHA256 stress** — single-element inputs near 1 MB; verify cross-client.
5. **EL fork-from-CL-hash-mismatch scenario** — devnet test where the CL claims one hash, the EL computes another; verify graceful error vs panic per client.
6. **Cross-CL ↔ EL pairing matrix** — 6 × 6 (CLs × ELs) compatibility matrix for `requestsHash` computation. Cross-corpus audit candidate.
