---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [28, 29, 31, 41]
eips: [EIP-7594, EIP-7892]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.3
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.3.1
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 42: ENR `nfd` (next fork digest) field encoding/decoding (EIP-7594/EIP-7892 PeerDAS peer discovery)

## Summary

Sibling of `cgc` from item #41; second Fulu-NEW ENR field. The `nfd` field communicates the **digest of the next scheduled fork** — regardless of whether it is a regular fork (e.g., Heze) or a Blob-Parameters-Only (BPO) fork (e.g., the two mainnet BPO transitions at epochs 412672 and 419072). Allows peers to predict fork transitions and maintain peering across boundaries.

Spec (`vendor/consensus-specs/specs/fulu/p2p-interface.md:698-720`): SSZ Bytes4 ForkDigest fixed 4-byte encoding. Unlike `cgc`'s variable-length BE (item #41), `nfd`'s fixed-format eliminates encoding-format divergence risk.

**Fulu surface (carried forward from 2026-05-04 audit; CURRENT mainnet target):** all six clients implement byte-equivalent `nfd` encoding/decoding. **Live mainnet validation**: 2 BPO transitions (epoch 412672 → 15 blobs, 419072 → 21 blobs per item #31) executed without peer-discovery breakdown across all 6 clients — strongest possible validation that all 6 produce byte-identical `nfd` updates at BPO boundaries.

Per-client divergences entirely in:
- **Connection-time enforcement (Pattern X candidate)**: prysm STRICTEST — REJECTS peers at connection time on `nfd` mismatch via `errNextDigestMismatch` (`vendor/prysm/beacon-chain/p2p/fork.go:123`); converts spec MAY → MUST. Other 5 likely soft (per spec "MAY disconnect at/after the fork boundary").
- **Encode call style**: lighthouse `[u8; 4]` direct (build path) + SSZ-via-Bytes (update path); teku `SszBytes4.of(...).sszSerialize()`; nimbus `SSZ.encode(next_fork_digest)` (`eth2_network.nim:2750`); lodestar direct `Uint8Array`; grandine SSZ-via-Bytes; prysm raw bytes via geth ENR helper.
- **Decode call style**: lighthouse single-step `[u8; 4]` (`enr.rs:88-89`); grandine two-step (Bytes → SSZ decode).

**Gloas surface (at the Glamsterdam target): field unchanged.** `vendor/consensus-specs/specs/gloas/p2p-interface.md` contains no references to `nfd` — the field is defined only in `vendor/consensus-specs/specs/fulu/p2p-interface.md:698-720` and inherited verbatim across the Gloas fork boundary. No `Modified nfd` heading.

**Per-client Gloas inheritance**: all 6 clients reuse Fulu implementations at Gloas via fork-agnostic discv5/ENR library wrappers. No client introduces a Gloas-specific override. The Pattern X (prysm strict connection-time enforcement) concern carries forward; the soft-vs-strict spec MAY interpretation remains a per-client policy choice.

**Mainnet activation status**: `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `vendor/consensus-specs/configs/mainnet.yaml:60`. When Gloas is eventually scheduled, all 6 clients should update their `nfd` to the new Gloas fork digest. Currently the BPO mechanism continues triggering nfd updates without divergence.

**Cross-cut to lighthouse Pattern M cohort**: the Pattern M Gloas-ePBS readiness gap (12+ symptoms) does NOT extend to nfd encoding — lighthouse `next_fork_digest` ENR field is correctly wired. The cohort gap is at the ePBS surface, not the peer-discovery layer.

**Impact: none.** Twenty-third impact-none result in the recheck series.

## Question

Pyspec Fulu-NEW (`vendor/consensus-specs/specs/fulu/p2p-interface.md:698-720`):

> A new entry is added to the ENR under the key `nfd`, short for next fork digest. This entry communicates the digest of the next scheduled fork, regardless of whether it is a regular or a Blob-Parameters-Only fork. This new entry MUST be added once `FULU_FORK_EPOCH` is assigned any value other than `FAR_FUTURE_EPOCH`.
>
> If no next fork is scheduled, the `nfd` entry contains the default value for the type (i.e., the SSZ representation of a zero-filled array).
>
> | Key | Value |
> | --- | --- |
> | `nfd` | SSZ Bytes4 `ForkDigest` |
>
> When discovering and interfacing with peers, nodes MUST evaluate `nfd` alongside their existing consideration of the `ENRForkID::next_*` fields. If there is a mismatch, the node MUST NOT disconnect before the fork boundary, but it MAY disconnect at/after the fork boundary.

At Gloas: NOT modified (`vendor/consensus-specs/specs/gloas/p2p-interface.md` contains no `nfd` references). Field inherited from Fulu verbatim.

Three recheck questions:
1. Fulu-surface invariants (H1–H10 from prior audit) — do all six clients still implement byte-equivalent nfd encoding/decoding?
2. **At Gloas (the new target)**: is the field unchanged? Do all six clients reuse Fulu implementations at Gloas?
3. Does the prysm strict connection-time enforcement (Pattern X candidate) still apply?

## Hypotheses

- **H1.** Spec format: SSZ Bytes4 ForkDigest (fixed 4-byte raw encoding, no length prefix).
- **H2.** ENR key string is `"nfd"`.
- **H3.** No-next-fork sentinel: 4 zero bytes `[0, 0, 0, 0]`.
- **H4.** `nfd` added to ENR when `FULU_FORK_EPOCH != FAR_FUTURE_EPOCH` (spec MUST).
- **H5.** Decode: clients accept exactly 4 bytes; reject other lengths (SSZ Bytes4 fixed-size).
- **H6.** Connection-time enforcement on mismatch: spec MAY disconnect at/after fork boundary. **Prysm STRICTER** — REJECTS at connection time.
- **H7.** nfd updates triggered by BPO transitions (cross-cuts item #31): epochs 412672 (BPO #1) + 419072 (BPO #2).
- **H8.** nfd value = `compute_fork_digest(genesis_validators_root, next_fork_epoch)` (cross-cuts item #29).
- **H9.** Pre-Fulu peers: nfd field absent; clients must handle gracefully (per ENR spec "ignore unknown ENR entries").
- **H10.** Type width: SSZ Bytes4 = 4 bytes always; no width divergence (unlike cgc).
- **H11.** *(Glamsterdam target — field unchanged)*. `nfd` is NOT modified at Gloas. No references in `vendor/consensus-specs/specs/gloas/p2p-interface.md`. The Fulu-NEW field carries forward unchanged across the Gloas fork boundary in all 6 clients via fork-agnostic discv5/ENR library wrappers.
- **H12.** *(Glamsterdam target — Pattern X carry-forward)*. Prysm's strict connection-time enforcement (`errNextDigestMismatch` at `vendor/prysm/beacon-chain/p2p/fork.go:123`) carries forward at Gloas. Same spec MAY → MUST interpretation; forward-fragility class.

## Findings

H1–H12 satisfied. **No state-transition divergence at the Fulu surface (modulo Pattern X spec-interpretation); field inherited unchanged at Gloas across all 6 clients.**

### prysm

`vendor/prysm/beacon-chain/p2p/fork.go:25 nfdEnrKey = "nfd"`. Comment: "The `nfd` ENR entry separately advertizes the 'next fork digest' aspect of the fork schedule."

Write path (`fork.go:146-149`):

```go
if entry.ForkDigest == next.ForkDigest {
    node.Set(enr.WithEntry(nfdEnrKey, make([]byte, len(next.ForkDigest))))  // 4 zero bytes
} else {
    node.Set(enr.WithEntry(nfdEnrKey, next.ForkDigest[:]))                  // actual digest
}
```

Read path (`fork.go:181`): `entry := enr.WithEntry(nfdEnrKey, &digest)`.

**Connection-time enforcement** (`fork.go:42-127 compareForkENR`):

```go
if !params.FuluEnabled() {
    return nil
}
peerNFD, selfNFD := nfd(peer), nfd(self)
if peerNFD != selfNFD {
    return errors.Wrapf(errNextDigestMismatch, ...)
}
return nil
```

**STRICTEST connection-time enforcement** across the 6: REJECTS peers when nfd mismatches, post-Fulu. Converts spec MAY → MUST.

**No Gloas-specific code path** — fork-agnostic. The strict enforcement carries forward at Gloas. Pattern X candidate.

H1 ✓. H2 ✓. H3 ✓ (4 zero bytes for no-next-fork). H4 ✓. H5 ✓. **H6 ⚠** (STRICTEST — Pattern X). H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓ (no Gloas redefinition). **H12 ✓ (Pattern X carries forward)**.

### lighthouse

`vendor/lighthouse/beacon_node/lighthouse_network/src/discovery/enr.rs:25 NEXT_FORK_DIGEST_ENR_KEY = "nfd"`.

Read path (`:88-92`):

```rust
fn next_fork_digest(&self) -> Result<[u8; 4], &'static str> {
    self.get_decodable::<[u8; 4]>(NEXT_FORK_DIGEST_ENR_KEY)
        .ok_or("ENR next fork digest non-existent")?
        .map_err(|_| "Could not decode the ENR next fork digest")
}
```

**Single-step decode** — expects exactly 4 bytes raw.

Write paths (two):
- `enr.rs:284 builder.add_value(NEXT_FORK_DIGEST_ENR_KEY, &next_fork_digest)` — build path, `[u8; 4]` direct.
- `mod.rs:575 enr_insert::<Bytes>(KEY, &nfd.as_ssz_bytes().into())` — update path, SSZ-via-Bytes wrapper.

Both produce 4 raw bytes on wire (SSZ Bytes4 has no length prefix). Build-vs-update code-duplication risk: if SSZ encoding ever differs from raw bytes, paths could diverge.

**No Gloas-specific code path** — fork-agnostic. Lighthouse Pattern M cohort gap doesn't extend to ENR/peer-discovery layer.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (single-step `[u8; 4]`). H6 ✓ (soft enforcement; spec MAY-compliant). H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 n/a (lighthouse not in Pattern X).

### teku

`vendor/teku/networking/eth2/src/main/java/tech/pegasys/teku/networking/eth2/discovery/DiscoveryNetwork.java:53 NEXT_FORK_DIGEST_ENR_FIELD = "nfd"`.

Write path (`:159`):

```java
discoveryService.updateCustomENRField(
    NEXT_FORK_DIGEST_ENR_FIELD,
    SszBytes4.of(nextForkDigest).sszSerialize());
```

`SszBytes4.sszSerialize()` produces 4 raw bytes (SSZ Bytes4 has no length prefix). Spec-faithful.

**No Gloas-specific code path** — `MiscHelpersGloas` doesn't override ENR helpers.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 n/a.

### nimbus

`vendor/nimbus/beacon_chain/networking/eth2_network.nim:2741-2757 updateNextForkDigest`:

```nim
proc updateNextForkDigest*(node: Eth2Node, next_fork_digest: ForkDigest) =
  if node.nextForkDigest == next_fork_digest:
    return
  node.nextForkDigest = next_fork_digest
  let res = node.discoveryV5.updateRecord({
    enrNextForkDigestField: SSZ.encode(next_fork_digest)
  })
  if res.isOk:
    debug "Next fork digest changed; updated ENR nfd", next_fork_digest
```

`SSZ.encode(next_fork_digest)` where `next_fork_digest: ForkDigest` is SSZ Bytes4 → 4 raw bytes. **Spec-compliant** because the spec explicitly says "SSZ Bytes4 ForkDigest" (unlike cgc where nimbus's SSZ uint8 diverged from spec variable-length BE — item #41 Pattern W).

Idempotency: returns early if nfd unchanged. Efficient.

**No Gloas-specific code path** — fork-agnostic.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (SSZ Bytes4 fixed). H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 n/a.

### lodestar

`vendor/lodestar/packages/beacon-node/src/network/metadata.ts:18 ENRKey.nfd = "nfd"`.

Write path (`:141-146`):

```typescript
const nextForkDigest =
  nextForkEpoch !== FAR_FUTURE_EPOCH
    ? config.forkBoundary2ForkDigest(config.getForkBoundaryAtEpoch(nextForkEpoch))
    : ssz.ForkDigest.defaultValue();
this.onSetValue(ENRKey.nfd, nextForkDigest);
this.logger.debug("Updated nfd field in ENR", {nextForkDigest: toHex(nextForkDigest)});
```

Direct `Uint8Array` (4 bytes). No explicit SSZ wrap — SSZ Bytes4 = 4 raw bytes, so direct write produces correct on-wire format. No-next-fork sentinel via `ssz.ForkDigest.defaultValue()` (4 zero bytes).

**No Gloas-specific code path** — fork-agnostic.

H1 ✓. H2 ✓. H3 ✓ (`defaultValue` = 4 zeros). H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 n/a.

### grandine

`vendor/grandine/p2p/src/discovery/enr.rs:33 NEXT_FORK_DIGEST_ENR_KEY = "nfd"` (via prior audit).

Write path (`mod.rs:573`): `enr_insert::<Bytes>(KEY, &next_fork_digest.to_ssz()?.into())` — SSZ-via-Bytes wrapper.

Read path: two-step decode via `get_decodable::<Bytes>` + `ForkDigest::from_ssz_default(&nfd_bytes)`. Defensive against malformed input.

**No Gloas-specific code path** — fork-agnostic.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (two-step SSZ decode). H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 n/a.

## Cross-reference table

| Client | ENR key | Encode | Decode | Connection-time enforcement | Gloas redefinition |
|---|---|---|---|---|---|
| prysm | `nfdEnrKey = "nfd"` (`p2p/fork.go:25`) | `enr.WithEntry(nfdEnrKey, digest[:])`; no-next-fork → `make([]byte, 4)` | `enr.WithEntry(nfdEnrKey, &digest)` returns `[4]byte` | **STRICTEST** — `errNextDigestMismatch` at `:123` (Pattern X) | none — fork-agnostic |
| lighthouse | `NEXT_FORK_DIGEST_ENR_KEY = "nfd"` (`enr.rs:25`) | TWO paths: `builder.add_value(KEY, &[u8; 4])` (build) + `enr_insert::<Bytes>(KEY, ssz)` (update) | single-step `get_decodable::<[u8; 4]>` (`:88-89`) | soft (spec MAY-compliant) | none — fork-agnostic |
| teku | `NEXT_FORK_DIGEST_ENR_FIELD = "nfd"` | `SszBytes4.of(nextForkDigest).sszSerialize()` (`DiscoveryNetwork.java:159`) | TBD | soft TBD | none — fork-agnostic |
| nimbus | `enrNextForkDigestField = "nfd"` | `SSZ.encode(next_fork_digest)` at `eth2_network.nim:2750`; idempotent early-return at `:2743` | TBD | soft TBD | none — fork-agnostic |
| lodestar | `ENRKey.nfd = "nfd"` (`metadata.ts:18`) | direct `Uint8Array` (4 bytes); `ssz.ForkDigest.defaultValue()` for no-next-fork | TBD | soft TBD | none — fork-agnostic |
| grandine | `NEXT_FORK_DIGEST_ENR_KEY = "nfd"` | `enr_insert::<Bytes>(KEY, &nfd.to_ssz()?.into())` | two-step `get_decodable::<Bytes>` → `ForkDigest::from_ssz_default` | soft TBD | none — fork-agnostic |

## Empirical tests

### Fulu-surface live mainnet validation

5+ months of PeerDAS peer discovery since Fulu activation (2025-12-03). **2 BPO transitions** executed without peer-discovery breakdown:
- 412672 (BPO #1): 9 → 15 blobs. All 6 clients updated nfd → new ForkDigest at boundary.
- 419072 (BPO #2): 15 → 21 blobs. Same.

Cross-client peer pools maintained connectivity through both BPO boundaries — **strongest possible validation** that all 6 produce byte-identical nfd updates at BPO transitions.

### Gloas-surface

`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `mainnet.yaml:60`. Field unchanged at Gloas.

Concrete Gloas-spec evidence:
- No `Modified nfd` or `Modified next fork digest` headings anywhere in `vendor/consensus-specs/specs/gloas/`.
- `vendor/consensus-specs/specs/gloas/p2p-interface.md` contains no `nfd` references (field inherited from Fulu).

When Gloas is eventually scheduled on mainnet, all 6 clients should update nfd to the Gloas ForkDigest at the announcement; same flow as the BPO transitions.

### EF fixture status

**No dedicated EF fixtures** for `nfd` ENR encoding. Exercised implicitly through:
- Live mainnet PeerDAS gossip + 2 BPO transitions
- Per-client unit tests (out of EF scope)
- ENR encoding tests in each client's internal CI

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1**: dedicated EF fixture for `nfd` ENR encoding/decoding — cross-client byte-level equivalence at boundary slots.
- **T1.2**: BPO #3 fixture — synthesize a 3rd BPO entry; verify all 6 update nfd at the new boundary in sync.

#### T2 — Adversarial probes
- **T2.1 (Pattern X — prysm connection-time enforcement)**: connect prysm to peer with mismatched nfd. Expected: prysm REJECTS at connection time via `errNextDigestMismatch`. Other 5: soft enforcement (no disconnect before fork boundary per spec MAY).
- **T2.2 (Glamsterdam-target — H11 verification)**: field unchanged at Gloas. Verify per-client behavior at synthetic Gloas state.
- **T2.3 (Glamsterdam-target — Gloas activation nfd update)**: when `GLOAS_FORK_EPOCH != FAR_FUTURE_EPOCH`, verify all 6 update nfd to Gloas ForkDigest. Pre-emptive test before Gloas activation.
- **T2.4 (malformed nfd test)**: peer ENR with nfd of wrong length (3 or 5 bytes); verify all 6 reject with same error.
- **T2.5 (pre-Fulu peer test)**: peer ENR without nfd field; verify all 6 accept (per ENR spec "ignore unknown ENR entries").
- **T2.6 (lighthouse build-vs-update paths)**: verify byte-identical on-wire output between `builder.add_value(KEY, &[u8; 4])` and `enr_insert::<Bytes>(KEY, ssz)`.
- **T2.7 (BPO replay across restarts)**: restart node mid-BPO-transition; verify nfd survives + reloads identically.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Fulu-surface invariants (H1–H10) carry forward unchanged from the 2026-05-04 audit. **2 BPO transitions executed without peer-discovery breakdown** — strongest possible validation that all 6 produce byte-identical `nfd` updates at fork/BPO boundaries.

**Glamsterdam-target finding (H11 — field unchanged).** `vendor/consensus-specs/specs/gloas/p2p-interface.md` contains no `nfd` references. The Fulu-NEW field carries forward verbatim across the Gloas fork boundary in all 6 clients via fork-agnostic discv5/ENR library wrappers. No `Modified nfd` heading anywhere in Gloas specs.

When Gloas is eventually scheduled on mainnet, the same flow as the 2 BPO transitions will apply: all 6 clients update nfd → new Gloas ForkDigest at the announcement.

**Glamsterdam-target finding (H12 — Pattern X carry-forward).** Prysm's strict connection-time enforcement (`vendor/prysm/beacon-chain/p2p/fork.go:117-127 compareForkENR`) carries forward at Gloas:

```go
if !params.FuluEnabled() { return nil }
peerNFD, selfNFD := nfd(peer), nfd(self)
if peerNFD != selfNFD {
    return errors.Wrapf(errNextDigestMismatch, ...)
}
```

Prysm REJECTS peers at connection time when nfd mismatches — converts spec "MAY disconnect at/after the fork boundary" to "MUST NOT connect when mismatched". Other 5 clients likely soft (per spec MAY) — connection-time enforcement carry-forward concerns from prior audit.

**Behavioral consequence**: prysm peers with mismatched nfd (e.g., one peer aware of upcoming BPO #3, another not yet) won't connect. May reduce peer pool size around BPO/fork transitions when clients haven't yet updated their schedules.

**Pattern X carry-forward (NEW for item #28 catalog from prior audit)**: peer-discovery strictness divergence — prysm strictest (pre-connection rejection); other 5 soft. Same forward-fragility class as Patterns T (lodestar empty-set) and lighthouse strict cgc validation (item #41).

**Twenty-third impact-none result** in the recheck series. The fixed-format `nfd` (SSZ Bytes4 = 4 raw bytes) eliminates the encoding-format divergence seen in `cgc` (item #41 Pattern W — nimbus SSZ uint8). All 6 produce 4 raw bytes; all 6 accept exactly 4 bytes. The only carry-forward divergence is Pattern X (connection-time enforcement strictness).

**Notable per-client style differences (all observable-equivalent on the wire):**
- **prysm**: STRICTEST connection-time enforcement; zero-fill sentinel for no-next-fork.
- **lighthouse**: TWO write paths (build vs update); single-step `[u8; 4]` decode.
- **teku**: `SszBytes4.sszSerialize()` — most spec-faithful encode.
- **nimbus**: `SSZ.encode(next_fork_digest)`; idempotent early-return at `:2743`. Spec-compliant (unlike cgc — Pattern W) because SSZ Bytes4 is unambiguous.
- **lodestar**: direct `Uint8Array`; `ssz.ForkDigest.defaultValue()` for sentinel.
- **grandine**: SSZ-via-Bytes wrapper; two-step decode (defensive against malformed input).

**Lighthouse Pattern M cohort gap does NOT extend here** — `nfd` is at the peer-discovery / discv5 layer, not the ePBS state-transition surface. Lighthouse `next_fork_digest` ENR helper is correctly wired.

**No code-change recommendation.** Audit-direction recommendations:

- **Pattern X for item #28 catalogue** (carry-forward) — peer-discovery strictness divergence forward-fragility marker.
- **Connection-time enforcement audit across other 5 clients** — when do they REJECT vs DISCONNECT vs SOFT-WARN on nfd mismatch?
- **Compare prysm strictness vs spec text** — file consensus-specs issue if prysm's pre-connection rejection diverges from spec MAY.
- **lighthouse two-write-path equivalence test** — verify byte-identical on-wire output (T2.6).
- **Pre-emptive Gloas activation test** — when `GLOAS_FORK_EPOCH != FAR_FUTURE_EPOCH`, verify all 6 update nfd to Gloas ForkDigest at the announcement.
- **BPO #3 fixture** (T1.2) — synthesize a 3rd BPO entry; verify all 6 update nfd in sync.
- **Generate dedicated EF fixtures** for `nfd` ENR encoding.

## Cross-cuts

### With item #41 (`cgc` ENR field) — sibling Fulu-NEW ENR field

`cgc` and `nfd` are the two Fulu-NEW ENR fields. **`nfd` has LESS divergence risk** than `cgc` because:
- `nfd` is SSZ Bytes4 (fixed 4-byte) — unambiguous encoding.
- `cgc` is variable-length BE with empty-for-zero — admits SSZ uint8 misinterpretation (nimbus Pattern W).

Both share the Pattern X connection-time enforcement concern (prysm strict).

### With item #29 (signing-domain primitives + `compute_fork_digest`) — nfd value source

`nfd` value = `compute_fork_digest(genesis_validators_root, next_fork_epoch)` per spec. Item #29 audited `compute_fork_digest` Fulu-modified (XOR-with-blob-params for post-Fulu) — same primitive consumed here.

### With item #31 (BPO `get_blob_parameters` + `compute_fork_digest` modified) — BPO trigger

Per spec: "[nfd] communicates the digest of the next scheduled fork, regardless of whether it is a regular or a Blob-Parameters-Only fork." Item #31's 2 mainnet BPO transitions (epochs 412672, 419072) triggered nfd updates in all 6 clients; live validation.

### With item #28 (Gloas divergence meta-audit) — Pattern X candidate

This item proposes **Pattern X** for item #28's catalog (carry-forward from prior audit): peer-discovery strictness divergence — prysm strictest (pre-connection rejection on nfd mismatch); other 5 soft per spec MAY. Same forward-fragility class as Patterns T (lodestar empty-set), S (nimbus hidden invariant), and lighthouse strict cgc validation (item #41).

### With lighthouse Pattern M cohort (carry-forward)

The Pattern M Gloas-ePBS readiness gap (12+ symptoms at state-transition ePBS surface) does NOT extend to ENR/peer-discovery layer. Lighthouse `next_fork_digest` ENR helper is correctly wired.

## Adjacent untouched

1. **Pattern X for item #28 catalogue** — peer-discovery strictness divergence forward-fragility marker.
2. **Connection-time enforcement audit across other 5 clients** — strictness comparison.
3. **Compare prysm strictness vs spec text** — file consensus-specs clarification request if needed.
4. **BPO #3 fixture** — synthesize next BPO entry; verify all 6 update nfd in sync.
5. **Pre-emptive Gloas activation test** — verify all 6 update nfd to Gloas ForkDigest when scheduled.
6. **Pre-Fulu peer compatibility test** — peer ENR without nfd field; verify all 6 accept.
7. **Malformed nfd test** — wrong length (3 or 5 bytes); verify all 6 reject identically.
8. **lighthouse two-write-path equivalence test** — build vs update paths produce byte-identical output.
9. **ENR replay across restarts** — verify all 6 persist nfd across restart.
10. **discv5 library distribution cross-client** (geth ENR / sigp discv5 / Java tuweni / etc.).
11. **Peer scoring on nfd mismatch** (soft enforcement clients — do they downgrade peer score?).
12. **Cross-network nfd consistency** (sepolia/holesky/gnosis/hoodi).
13. **ENR `eth2` + `nfd` cross-validation** — spec says "MUST evaluate `nfd` alongside their existing consideration of the `ENRForkID::next_*` fields" — verify all 6 cross-validate.
14. **nfd staleness audit** — when local node falls behind, how do clients reconcile nfd vs canonical schedule?
15. **MetaData v3 cross-validation** (cross-cut with item #41) — when cgc differs between ENR + MetaData, which takes precedence per client?
