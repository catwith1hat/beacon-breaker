---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [15]
eips: [EIP-7685]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 62: `requestsHash` cross-client byte-for-byte Merkleization equivalence (EIP-7685, CL-EL boundary)

## Summary

EIP-7685 defines `requestsHash = sha256(sha256(req_0) || sha256(req_1) || ... || sha256(req_N))` where each `req_i = request_type_byte || ssz_serialize(list)` per the consensus-specs `get_execution_requests_list` (Electra `beacon-chain.md:1390-1401`). The EL computes this hash and includes it in its block header.

**Only two CLs compute the EIP-7685 `requestsHash` locally on the CL side**: lighthouse (`execution_requests.rs:73`) and nimbus (`helpers.nim:452`). Both use it for the same purpose — reconstructing the EL block header inside their CL-side `compute_execution_block_hash` path so the CL can verify the EL's claimed `executionBlockHash` against an independent re-derivation. Source review confirms both implementations are byte-identical on all inputs (nested SHA256, empty-list filter, same type-byte ordering 0/1/2 = deposit/withdrawal/consolidation, same iteration order).

The other four clients (prysm, teku, lodestar, grandine) **delegate entirely** to the EL: they construct the bytes-list per `get_execution_requests_list`, pass it via `engine_newPayloadV{4,5}`, and rely on the EL to compute and embed `requestsHash` in its header. No local CL-side computation.

At Gloas a **second, distinct hash** appears on the CL side: `executionRequestsRoot = hash_tree_root(execution_requests)` — SSZ Merkleization, **not** EIP-7685 nested SHA256. This is the bid-commitment hash used by `is_valid_execution_payload_envelope` to verify the envelope matches the prior bid (grandine `store.rs:3429-3436`; lodestar `upgradeStateToGloas.ts:51-53`). It is a separate semantic and is not interchangeable with the EIP-7685 `requestsHash`. Cross-cut: both hashes coexist at Gloas; auditors must not conflate them.

**Verdict: impact none.** No divergence on the EIP-7685 hash among the two CLs that compute it locally. The four delegating CLs cannot diverge here (the hash is computed by their EL counterpart, which is audited separately in evm-breaker). The CL ↔ EL boundary remains a cross-corpus audit candidate.

## Question

EIP-7685 hash algorithm (per the EIP body):

```
requestsHash = sha256(sha256(req_0) || sha256(req_1) || ... || sha256(req_N))
```

where each `req_i = request_type_byte || raw_request_bytes`. The consensus-specs `get_execution_requests_list` at `vendor/consensus-specs/specs/electra/beacon-chain.md:1390-1401` defines the `raw_request_bytes` as the full SSZ-serialized list of operations of that type:

```python
def get_execution_requests_list(execution_requests: ExecutionRequests) -> Sequence[bytes]:
    requests = [
        (DEPOSIT_REQUEST_TYPE, execution_requests.deposits),
        (WITHDRAWAL_REQUEST_TYPE, execution_requests.withdrawals),
        (CONSOLIDATION_REQUEST_TYPE, execution_requests.consolidations),
    ]
    return [
        request_type + ssz_serialize(request_data)
        for request_type, request_data in requests
        if len(request_data) != 0
    ]
```

Type bytes per EIP-7685: `DEPOSIT_REQUEST_TYPE = 0x00`, `WITHDRAWAL_REQUEST_TYPE = 0x01`, `CONSOLIDATION_REQUEST_TYPE = 0x02`. Empty per-type lists are **excluded** from the bytes-list. The fixed-size SSZ encoding of `DepositRequest` (192 B), `WithdrawalRequest` (76 B), `ConsolidationRequest` (116 B) means `ssz_serialize(List[X, N])` is equivalent to the byte-concatenation of per-element SSZ encodings (no length prefix; lists of fixed-size elements have no implicit length-prefix overhead).

At Gloas an additional, separate hash appears on the CL bid path: `executionRequestsRoot = hash_tree_root(ExecutionRequests)` — SSZ Merkle root. **Not** the EIP-7685 hash. Used by the envelope validator to verify the post-Gloas bid commitment matches the eventual payload contents. This audit is about EIP-7685; the Gloas bid hash is documented as a cross-cut.

Open questions:

1. **Per-CL semantics** — which CLs compute `requestsHash` locally vs delegating to the EL?
2. **Byte-equivalence** — among CLs that compute locally, do they produce identical 32-byte output on identical input?
3. **Empty list / empty per-type list** — `requests_list == []` → `sha256(b"")` = `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. Empty per-type list excluded from the bytes-list.
4. **Single-element list** — nested SHA256 fires: `sha256(sha256(req_0))`, not flat SHA256.
5. **Gloas separation** — does the new bid `executionRequestsRoot` get accidentally substituted for the EIP-7685 `requestsHash` anywhere?

## Hypotheses

- **H1.** Lighthouse's `requests_hash()` and nimbus's `computeRequestsHash` produce identical 32-byte outputs on identical input `ExecutionRequests`.
- **H2.** Both match the EIP-7685 reference: nested SHA256, outer = `sha256(concat(sha256(req_i) for i in 0..n))`.
- **H3.** Empty `ExecutionRequests` (deposits, withdrawals, consolidations all empty) produces `sha256(b"")` = `e3b0c4...b855`.
- **H4.** Single-non-empty-type-list produces `sha256(sha256(type_byte || ssz(list)))`, not flat SHA256.
- **H5.** Prysm, teku, lodestar, grandine do **not** compute the EIP-7685 hash locally — they delegate to their EL counterpart via the Engine API.
- **H6** *(Gloas-specific cross-cut)*. The Gloas bid `executionRequestsRoot` is computed via `hash_tree_root(ExecutionRequests)` (SSZ Merkleization), **not** via EIP-7685 nested SHA256. Verify no client conflates the two.
- **H7** *(forward-fragility)*. Streaming SHA256 (lighthouse `DynamicContext`) vs one-shot SHA256 (nimbus `computeDigest` block) produces byte-identical output on all sizes (including large `MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192` cases).

## Findings

### prysm

**No local CL-side EIP-7685 `requestsHash` computation.** Verified by grep across `vendor/prysm/beacon-chain`: zero matches for nested-SHA256 / `requestsHash` / `RequestsHash` patterns outside of test fixtures and Engine API wire-encoding.

Prysm constructs the bytes-list via `pb.EncodeExecutionRequests(executionRequests)` (called from `vendor/prysm/beacon-chain/execution/engine_client.go:210,220`) and passes it as the `executionRequests` parameter to `engine_newPayloadV{4,5}`. The EL computes the hash and embeds it in its header; prysm trusts the EL's response and the prior CL ↔ EL trust boundary.

### lighthouse

Local CL-side EIP-7685 computation at `vendor/lighthouse/consensus/types/src/execution/execution_requests.rs:70-85`:

```rust
/// Generate the execution layer `requests_hash` based on EIP-7685.
///
/// `sha256(sha256(requests_0) ++ sha256(requests_1) ++ ...)`
pub fn requests_hash(&self) -> Hash256 {
    let mut hasher = DynamicContext::new();

    for request in self.get_execution_requests_list().iter() {
        let mut request_hasher = DynamicContext::new();
        request_hasher.update(request);
        let request_hash = request_hasher.finalize();

        hasher.update(&request_hash);
    }

    hasher.finalize().into()
}
```

Inputs come from `get_execution_requests_list` (same file, lines 44-68), which:

- Filters empty per-type lists (only non-empty `deposits` / `withdrawals` / `consolidations` are pushed).
- Concatenates `[RequestType::X.to_u8()]` with `self.<type>.as_ssz_bytes()` (whole list SSZ-serialized).
- Preserves the spec order (`deposits`, then `withdrawals`, then `consolidations`).

Type bytes (lines 105-111): `Deposit => 0`, `Withdrawal => 1`, `Consolidation => 2`. Matches EIP-7685.

Empty-`ExecutionRequests` behaviour: `get_execution_requests_list` returns `vec![]`, the for-loop body never runs, `hasher.finalize()` returns `sha256(b"")` = `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. Matches H3.

Single-non-empty-type-list (e.g., deposits only): for-loop runs once with `request = [0x00] || ssz(deposits)`, inner hasher returns `sha256(req)`, outer hasher updates with that 32-byte digest, finalize returns `sha256(sha256(req))`. Matches H4.

**Call site** at `vendor/lighthouse/beacon_node/execution_layer/src/block_hash.rs:42`:

```rust
let requests_root = execution_requests.map(|requests| requests.requests_hash());
```

The locally-computed hash is passed to `ExecutionBlockHeader::from_payload` for the local CL-side keccak256(RLP(header)) re-derivation; lighthouse uses this to verify the EL's claimed `executionBlockHash` matches what the EL header should produce.

Streaming hash impl: `DynamicContext` (incremental SHA256 from `ethereum_hashing` crate). No size cap; updates are byte-streamed.

### teku

**No local CL-side EIP-7685 `requestsHash` computation.** Verified by grep across `vendor/teku/ethereum/spec/src`: zero matches for `requestsHash` / `RequestsHash` / `requests_hash` outside of test code. Teku constructs the bytes-list and passes to EL; the EL computes the hash.

### nimbus

Local CL-side EIP-7685 computation at `vendor/nimbus/beacon_chain/spec/helpers.nim:451-473`:

```nim
# https://eips.ethereum.org/EIPS/eip-7685
func computeRequestsHash*(
    requests: electra.ExecutionRequests): EthHash32 =

  template individualHash(requestType, requestList): Digest =
    computeDigest:
      h.update([requestType.byte])
      for request in requestList:
        h.update SSZ.encode(request)

  let requestsHash = computeDigest:
    template mixInRequests(requestType, requestList): untyped =
      if requestList.len > 0:
        h.update(individualHash(requestType, requestList).data)

    static:
      doAssert DEPOSIT_REQUEST_TYPE < WITHDRAWAL_REQUEST_TYPE
      doAssert WITHDRAWAL_REQUEST_TYPE < CONSOLIDATION_REQUEST_TYPE
    mixInRequests(DEPOSIT_REQUEST_TYPE, requests.deposits)
    mixInRequests(WITHDRAWAL_REQUEST_TYPE, requests.withdrawals)
    mixInRequests(CONSOLIDATION_REQUEST_TYPE, requests.consolidations)

  requestsHash.to(EthHash32)
```

The `individualHash` template hashes `[type_byte] ++ SSZ.encode(req_0) ++ SSZ.encode(req_1) ++ ...` — iterating individual operations. Because `DepositRequest`/`WithdrawalRequest`/`ConsolidationRequest` are all fixed-size SSZ types, `concat(SSZ.encode(req_i))` is byte-equivalent to `SSZ.encode(list)`. Spec-conformant.

The `mixInRequests` template fires only when `requestList.len > 0`, filtering empty per-type lists. Order matches EIP-7685 (deposit → withdrawal → consolidation), backed by a compile-time `static doAssert` guard.

Empty-`ExecutionRequests` behaviour: outer `computeDigest` block runs but neither `mixInRequests` call appends anything; the digest is `sha256(b"")` = `e3b0c4...b855`. Matches H3.

**Call sites** at `vendor/nimbus/beacon_chain/spec/helpers.nim:566` (pre-Gloas Electra/Fulu, via `body.execution_requests`) and `:584` (Gloas, via `envelope.execution_requests` in the payload-envelope block-hash reconstruction). Both pass the hash to `compute_execution_block_hash` for the keccak256(RLP(header)) re-derivation — identical purpose to lighthouse.

One-shot hash impl: nim's `computeDigest` block accumulates `h.update(...)` calls; `Digest = MDigest[256]` from `nimcrypto`. Produces identical byte output to lighthouse's streaming `DynamicContext` for any input (both standard SHA256).

### lodestar

**No local CL-side EIP-7685 `requestsHash` computation.** Lodestar constructs the bytes-list in `vendor/lodestar/packages/beacon-node/src/execution/engine/types.ts:529-546` (`serializeExecutionRequests`, documented as "identical to `get_execution_requests_list`" at line 526-527) and passes to the EL via `engine_newPayloadV{4,5}`.

Lodestar **does** compute a separate, distinct hash on the CL side: `ssz.electra.ExecutionRequests.hashTreeRoot()` at `vendor/lodestar/packages/state-transition/src/block/processParentExecutionPayload.ts:28` and `vendor/lodestar/packages/state-transition/src/slot/upgradeStateToGloas.ts:51-53`. This is the Gloas bid `executionRequestsRoot` (SSZ Merkleization), **not** the EIP-7685 `requestsHash`. Cross-cut: see H6.

### grandine

**No local CL-side EIP-7685 `requestsHash` computation.** Grandine constructs the bytes-list and delegates to the EL via Engine API.

Grandine also uses the SSZ `hash_tree_root` form for the Gloas bid commitment at `vendor/grandine/fork_choice_store/src/store.rs:3429-3436`:

```rust
// [REJECT] hash_tree_root(envelope.execution_requests) == bid.execution_requests_root
ensure!(
    envelope.message.execution_requests.hash_tree_root() == bid.execution_requests_root,
    Error::<P>::ExecutionPayloadRequestsHashMismatch { ... },
);
```

Confirms the H6 cross-cut: the Gloas bid path uses SSZ `hash_tree_root` (32-byte Merkle root over the SSZ field tree), **not** EIP-7685 nested SHA256.

## Cross-reference table

| Client | Local EIP-7685 `requestsHash`? | Algorithm/file | Empty-list (H3) | Single-elem (H4) | Delegates to EL (H5) | Gloas SSZ `hashTreeRoot` use (H6) |
|---|---|---|---|---|---|---|
| prysm | **no** | n/a (`engine_client.go:210` bytes-list to EL) | n/a | n/a | YES | (via SSZ types library on bid path; not in scope for this audit) |
| lighthouse | **yes** | nested SHA256 via `DynamicContext` (`execution_requests.rs:73`) | `sha256(b"") = e3b0...b855` ✓ | `sha256(sha256(req_0))` ✓ | NO (local verify path) | (via SSZ types library on bid path) |
| teku | **no** | n/a (engine API delegation) | n/a | n/a | YES | (via SSZ schema library on bid path) |
| nimbus | **yes** | nested SHA256 via one-shot `computeDigest` (`helpers.nim:452`) | `sha256(b"") = e3b0...b855` ✓ | `sha256(sha256(req_0))` ✓ | NO (local verify path) | (via `hash_tree_root` on envelope path) |
| lodestar | **no** | bytes-list only (`types.ts:529 serializeExecutionRequests`) — DIFFERENT local hash via `ssz.electra.ExecutionRequests.hashTreeRoot()` for Gloas bid | n/a | n/a | YES (for EIP-7685) | YES (`upgradeStateToGloas.ts:51`, `processParentExecutionPayload.ts:28`) |
| grandine | **no** | n/a (engine API delegation) — Gloas bid uses `hash_tree_root()` (`store.rs:3431`) | n/a | n/a | YES | YES (`store.rs:3431`) |

**H1 (byte-equivalence between lighthouse and nimbus)**: source review confirms equivalent: both nested SHA256, same type bytes (0/1/2), same iteration order (deposit/withdrawal/consolidation), both filter empty per-type lists. ✓

**H2 (matches EIP-7685 reference)**: ✓ for both.

**H3 (empty-list = `e3b0c4...b855`)**: ✓ for both (verified by code-path analysis; empty for-loop body in both impls).

**H4 (single-element nested)**: ✓ for both.

**H5 (delegation)**: ✓ — prysm, teku, lodestar, grandine all delegate.

**H6 (Gloas bid uses SSZ `hash_tree_root`, NOT EIP-7685)**: ✓ — confirmed in lodestar `upgradeStateToGloas.ts:51` and grandine `store.rs:3431`. No conflation observed in any client.

**H7 (streaming vs one-shot byte-equivalence)**: ✓ — both `DynamicContext` and `computeDigest` are standard SHA256 (FIPS-180); produce identical output regardless of update-chunking.

## Empirical tests

No dedicated EF spec fixture exercises `requestsHash` byte-equivalence in isolation (it's an EL-side primitive per EIP-7685, not a CL state-transition rule). Implicit coverage:

- **Devnet / mainnet Pectra activation**: every block with `len(execution_requests) > 0` exercises the round-trip (CL → EL bytes-list → EL `requestsHash` → EL block header → CL block-hash re-verification). Lighthouse + nimbus's local `requests_hash` / `computeRequestsHash` must agree byte-for-byte with the EL's computation for the CL block-hash check to pass. 5+ months of Fulu mainnet history with no observed mismatch.
- **EF block-header spec fixtures (Electra+)**: implicitly exercise the bytes-list construction (`get_execution_requests_list`) cross-client. All 6 CLs pass.

Suggested fuzzing vectors (none presently wired):

- **T1.1 (priority — cross-client byte-equivalence fixture).** Generate 100 random `ExecutionRequests` inputs (covering empty per-type, single-entry, multi-entry, near-cap). Compute `get_execution_requests_list` → bytes-list. Hex-encode and feed to:
  - lighthouse's `requests_hash()`
  - nimbus's `computeRequestsHash`
  - an EIP-7685 Python reference
  Hex-diff outputs. All three must agree byte-for-byte.
- **T1.2 (empty-list canonical).** `requests_list = []`. Verify both lighthouse + nimbus produce `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
- **T1.3 (single deposit-only).** `[(0x00) || ssz(deposits_with_one_entry)]`. Verify `sha256(sha256(...))` fires, not flat `sha256`.
- **T1.4 (max-cap stress).** 8192 deposit requests (1.572 MiB encoded). Verify no OOM/overflow, identical output across lighthouse/nimbus/reference.
- **T2.1 (CL ↔ EL round-trip on devnet).** CL A computes the local hash; passes bytes-list to its EL; EL computes its own hash; verify both hashes match. Devnet test.
- **T2.2 (cross-CL block import).** CL A proposes a block; CL B (different vendor) imports the block; verify CL B's local hash (if it computes one) or its EL's response matches A's claim.
- **T3.1 (Gloas H6 disambiguation).** Verify `ssz.electra.ExecutionRequests.hashTreeRoot(...)` and `requests_hash()` produce **different** 32-byte outputs on the same input (they should, since they use entirely different algorithms). Documents the H6 cross-cut empirically.

## Conclusion

All six clients are spec-conformant on EIP-7685 `requestsHash` handling. Two CLs (lighthouse, nimbus) compute the hash locally for CL-side EL block-hash verification; both produce byte-identical 32-byte outputs (source-review-verified across nested SHA256, empty-list filtering, type-byte ordering, list iteration). Four CLs (prysm, teku, lodestar, grandine) delegate entirely to the EL via Engine API.

At Gloas a second, distinct hash appears on the CL side: `executionRequestsRoot = hash_tree_root(ExecutionRequests)` (SSZ Merkleization). This is the bid-commitment hash, **not** the EIP-7685 `requestsHash`. Both lodestar and grandine use this correctly on the envelope-validation path; no conflation observed.

**Verdict: impact none.** No divergence among the local-compute CLs. The delegating CLs cannot diverge here (their hash is computed by their EL counterpart). The CL ↔ EL boundary remains a cross-corpus audit candidate handled by evm-breaker. Audit closes.

## Cross-cuts

### With item #15 (CL-EL boundary encoding)

Item #15 closed at the encoding level (`get_execution_requests_list` produces identical bytes-list across all 6 CLs) and at the V4/V5-dispatch level. This item closes the third leg: the hash of that bytes-list is byte-identical across the two CLs that compute it locally.

### With evm-breaker's EL-side `requestsHash` audit

The EL clients (geth / erigon / besu / nethermind / reth / ethrex) compute `requestsHash` independently per EIP-7685. The CL ↔ EL parity check is a cross-corpus audit handled by evm-breaker.

### With Gloas bid `executionRequestsRoot` (H6 — the SSZ `hash_tree_root` hash)

Distinct from EIP-7685. Used by the envelope-validator (grandine `store.rs:3429-3436`) and bid initializer (lodestar `upgradeStateToGloas.ts:51-53`) to verify the post-Gloas envelope matches the prior bid commitment. Auditor must not conflate this with the EL block-header `requestsHash`. Audit-worthy as its own item: cross-client SSZ `hash_tree_root(ExecutionRequests)` byte-equivalence.

### With item #59 (envelope verification)

Item #59 audited `verify_execution_payload_envelope`. The envelope-vs-bid `execution_requests_root` check (grandine `store.rs:3431`) lives on that same code path. Cross-cut on the hashing semantic.

## Adjacent untouched

1. **EL-side `requestsHash` cross-client byte-equivalence** — handled by evm-breaker; not in scope here.
2. **Gloas bid `executionRequestsRoot` (SSZ `hash_tree_root`) audit** — separate audit item; same `ExecutionRequests` input, completely different hash algorithm.
3. **`MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192` over-the-wire** — 1.572 MiB encoded list. Verify Engine API JSON-RPC and CL gossip tolerate this size end-to-end.
4. **Streaming vs one-shot SHA256 stress at sizes > 1 MiB** — single-non-empty-type-list near 1 MiB; verify cross-client (lighthouse streaming + nimbus one-shot must agree).
5. **EL fork-from-CL-hash-mismatch scenario** — devnet test where the CL claims one hash, the EL computes another; verify graceful error vs panic per CL on lighthouse + nimbus (the two locally-computing CLs).
6. **Cross-CL ↔ EL pairing matrix** — 6 × 6 (CLs × ELs) compatibility for `requestsHash` computation. Cross-corpus audit candidate.
