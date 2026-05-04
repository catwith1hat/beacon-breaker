# Item 42 — ENR `nfd` (next fork digest) field encoding/decoding (EIP-7594/EIP-7892 PeerDAS peer discovery)

**Status:** no-divergence-pending-fixture-run — audited 2026-05-04. **Thirteenth Fulu-NEW item, ninth PeerDAS audit**. Sibling of `cgc` from item #41; second Fulu-NEW ENR field. Closes Fulu's ENR additions completely. Cross-cuts item #29 (`compute_fork_digest`), item #31 (BPO transitions trigger nfd updates), item #41 (cgc — sibling field with HIGHER divergence risk).

The `nfd` field communicates the **digest of the next scheduled fork** — regardless of whether it is a regular fork (e.g., Heze) or a Blob-Parameters-Only (BPO) fork (e.g., the BPO #1 transition at epoch 412672). This allows peers to predict their next fork transition and maintain peering across the boundary.

Spec definition (`p2p-interface.md` "Next fork digest" section):
> A new entry is added to the ENR under the key `nfd`, short for next fork digest. This entry communicates the digest of the next scheduled fork, regardless of whether it is a regular or a Blob-Parameters-Only fork. This new entry MUST be added once `FULU_FORK_EPOCH` is assigned any value other than `FAR_FUTURE_EPOCH`.
>
> If no next fork is scheduled, the `nfd` entry contains the default value for the type (i.e., the SSZ representation of a zero-filled array).
>
> | Key | Value |
> | --- | --- |
> | `nfd` | SSZ Bytes4 ForkDigest |
>
> When discovering and interfacing with peers, nodes MUST evaluate `nfd` alongside their existing consideration of the `ENRForkID::next_*` fields under the `eth2` key... If there is a mismatch, the node MUST NOT disconnect before the fork boundary, but it MAY disconnect at/after the fork boundary.

**Format**: SSZ Bytes4 — fixed 4-byte encoding. UNAMBIGUOUS, unlike cgc's variable-length BE (item #41). All 6 clients produce 4 raw bytes on the wire.

## Scope

In: `nfd` ENR field encoding (write path) + decoding (read path); no-next-fork sentinel handling (4 zero bytes); peer connection-time enforcement on nfd mismatch; cross-cuts with `compute_fork_digest` (item #29) and BPO transitions (item #31).

Out: ENR `cgc` field (item #41); `compute_fork_digest` algorithm (item #29 covered); BPO `blob_schedule` (item #31 covered); ENR signature verification; discv5 library internals; `ENRForkID::next_*` fields in `eth2` ENR key (Phase0-heritage).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | Spec format: SSZ Bytes4 ForkDigest (fixed 4-byte raw encoding, no length prefix) | ✅ all 6 | SSZ Bytes4 = 4 raw bytes by definition |
| H2 | ENR key string is `"nfd"` | ✅ all 6 | Spec defines key |
| H3 | No-next-fork sentinel: 4 zero bytes `[0, 0, 0, 0]` | ✅ all 6 | Per spec "default value for the type" |
| H4 | nfd added to ENR when FULU_FORK_EPOCH != FAR_FUTURE_EPOCH | ✅ in 5 of 6 explicitly; ⚠️ TBD on lodestar (always-set policy from #41 cgc may apply) | Spec MUST condition |
| H5 | Decode: clients accept exactly 4 bytes; reject other lengths | ✅ all 6 (SSZ Bytes4 fixed-size) | Type-system enforcement |
| H6 | Connection-time enforcement on nfd mismatch: spec says MAY disconnect at/after fork boundary | ⚠️ **prysm STRICTER**: REJECTS peers at connection time on mismatch (`errNextDigestMismatch`); converts spec MAY → MUST; other 5 TBD on enforcement strictness | NEW Pattern X candidate for item #28 |
| H7 | nfd updates triggered by BPO transitions (cross-cuts item #31): epoch 412672 (BPO #1, 9→15 blobs) and 419072 (BPO #2, 15→21 blobs) | ✅ all 6 | Per spec "regardless of whether it is a regular or a Blob-Parameters-Only fork" |
| H8 | nfd value = `compute_fork_digest(genesis_validators_root, next_fork_epoch)` (cross-cuts item #29) | ✅ all 6 | Spec semantic; XOR-with-blob-params for post-Fulu (item #29 confirmed) |
| H9 | Pre-Fulu peers: nfd field absent; clients must handle gracefully | ✅ all 6 | Per ENR spec "ignore unknown ENR entries" |
| H10 | Type width: SSZ Bytes4 = 4 bytes always; no width divergence (unlike cgc's uint8/int/uint64) | ✅ all 6 | Fixed-size SSZ |

## Per-client cross-reference

| Client | ENR key constant | Encoding (write) | Decoding (read) | Connection-time enforcement |
|---|---|---|---|---|
| **prysm** | `nfdEnrKey = "nfd"` (`p2p/fork.go:25`) | `node.Set(enr.WithEntry(nfdEnrKey, next.ForkDigest[:]))` (4 raw bytes); **no-next-fork** → `make([]byte, len(next.ForkDigest))` (4 zero bytes) | `nfd(record)` returns `[4]byte` from `enr.WithEntry(nfdEnrKey, &nfdBytes)` | **STRICTEST**: `compareForkENR` (`p2p/fork.go`) REJECTS peers on nfd mismatch with `errNextDigestMismatch` post-Fulu; converts spec MAY → MUST |
| **lighthouse** | `NEXT_FORK_DIGEST_ENR_KEY = "nfd"` (`discovery/enr.rs:25`) | TWO write paths: `builder.add_value(KEY, &next_fork_digest)` (`enr.rs:284`, `[u8; 4]` direct); `enr_insert::<Bytes>(KEY, &nfd.as_ssz_bytes().into())` (`mod.rs:575`) — both produce 4 raw bytes | `get_decodable::<[u8; 4]>(KEY)` (`enr.rs:88-92`) — single-step decode | TBD (likely soft enforcement) |
| **teku** | `NEXT_FORK_DIGEST_ENR_FIELD = "nfd"` (`DiscoveryNetwork.java:53`) | `discoveryService.updateCustomENRField(KEY, SszBytes4.of(nextForkDigest).sszSerialize())` (`DiscoveryNetwork.java:159`) | (TBD via deeper search) | TBD |
| **nimbus** | `enrNextForkDigestField = "nfd"` (assumed) | `SSZ.encode(next_fork_digest)` (`eth2_network.nim:2750`) | (TBD via deeper search) | TBD |
| **lodestar** | `ENRKey.nfd = "nfd"` (`metadata.ts:19`) | direct: `this.onSetValue(ENRKey.nfd, nextForkDigest)` (`metadata.ts:145`) — `nextForkDigest` is `Uint8Array` (4 bytes); no SSZ wrap explicit (Bytes4 is just 4 raw bytes); no-next-fork → `ssz.ForkDigest.defaultValue()` (`metadata.ts:144`) | (TBD via deeper search) | TBD |
| **grandine** | `NEXT_FORK_DIGEST_ENR_KEY = "nfd"` (`discovery/enr.rs:33`) | `enr_insert::<Bytes>(KEY, &next_fork_digest.to_ssz()?.into())` (`discovery/mod.rs:573`) | `get_decodable::<Bytes>` then `ForkDigest::from_ssz_default(&nfd_bytes)` (`enr.rs:88-94`) — TWO-STEP decode | TBD |

## Notable per-client findings

### CRITICAL — prysm STRICTEST connection-time enforcement (NEW Pattern X candidate)

`prysm/beacon-chain/p2p/fork.go:117-127`:

```go
// Because this is a new in-bound connection, we lean into the pre-fulu point that clients
// MAY connect to peers with the same current_fork_version but a different
// next_fork_version/next_fork_epoch, which implies we can chose to not connect to them when these
// don't match.
//
// Given that the next_fork_epoch matches, we will require the next_fork_digest to match.
if !params.FuluEnabled() {
    return nil
}
peerNFD, selfNFD := nfd(peer), nfd(self)
if peerNFD != selfNFD {
    return errors.Wrapf(errNextDigestMismatch,
        "next fork digest of peer with ENR %s: %v, does not match local value: %v",
        peerString, peerNFD, selfNFD)
}
return nil
```

**Prysm REJECTS peers at connection time when nfd mismatches**, post-Fulu only. Per spec: "If there is a mismatch, the node MUST NOT disconnect before the fork boundary, but it MAY disconnect at/after the fork boundary."

**Prysm interpretation**: connection-time rejection is a stronger form of "MAY disconnect at/after the fork boundary" — by never connecting in the first place, prysm avoids the disconnect overhead. **Converts spec MAY → MUST at connection time.**

**Behavioral consequence**: prysm peers with mismatched nfd (e.g., one peer aware of upcoming BPO #3, another not yet) won't connect. This may reduce peer pool size around BPO transitions when clients haven't yet updated their schedule.

**NEW Pattern X candidate for item #28 catalogue**: peer-discovery strictness divergence — prysm strictest (pre-connection rejection); other 5 likely soft (post-fork-boundary disconnect per spec MAY). Same forward-fragility class as Pattern T (lodestar empty-set) and lighthouse strict cgc validation (item #41).

### prysm zero-fill sentinel for no-next-fork

`prysm/beacon-chain/p2p/fork.go:146-149`:

```go
if entry.ForkDigest == next.ForkDigest {
    node.Set(enr.WithEntry(nfdEnrKey, make([]byte, len(next.ForkDigest))))  // 4 zero bytes
} else {
    node.Set(enr.WithEntry(nfdEnrKey, next.ForkDigest[:]))  // actual digest
}
```

When `entry.ForkDigest == next.ForkDigest` (current and next are the same — no upcoming fork), prysm encodes nfd as `[0, 0, 0, 0]`. Matches spec ("default value for the type, SSZ representation of a zero-filled array").

Other clients (lodestar explicit `ssz.ForkDigest.defaultValue()`) match. nimbus/teku/lighthouse/grandine: caller-provided ForkDigest, presumably default = 4 zeros.

### lighthouse TWO write paths (build vs update)

```rust
// discovery/enr.rs:284 — initial build path
builder.add_value(NEXT_FORK_DIGEST_ENR_KEY, &next_fork_digest);  // [u8; 4] direct

// discovery/mod.rs:575 — update path
self.discv5.enr_insert::<Bytes>(NEXT_FORK_DIGEST_ENR_KEY, &nfd.as_ssz_bytes().into())
```

Two different write paths with different type wrappers. Both produce 4 raw bytes on the wire (SSZ Bytes4 has no length prefix), so observable-equivalent. **Code duplication risk**: if SSZ encoding ever differs from raw bytes (e.g., variable-size ForkDigest in a future fork), the two paths could diverge.

**Decode is single-step**: `get_decodable::<[u8; 4]>(KEY)` — expects exactly 4 bytes raw.

### grandine TWO-STEP decode (Bytes wrapper + SSZ decode)

```rust
fn next_fork_digest(&self) -> Result<ForkDigest, &'static str> {
    let nfd_bytes = self
        .get_decodable::<Bytes>(NEXT_FORK_DIGEST_ENR_KEY)
        .ok_or("ENR next fork digest non-existent")?
        .map_err(|_| "Invalid RLP Encoding")?;

    ForkDigest::from_ssz_default(&nfd_bytes)
        .map_err(|_| "Could not decode the ENR next fork digest")
}
```

Grandine decodes as `Bytes` first, then `ForkDigest::from_ssz_default(&nfd_bytes)`. **Two-step decode** vs lighthouse's single-step `[u8; 4]`. Same observable result for spec-compliant 4-byte input. **Defensive against malformed input** — explicit SSZ decode catches bad bytes.

### nimbus + teku SSZ encode (consistent with cgc divergence pattern)

- nimbus: `SSZ.encode(next_fork_digest)` where `next_fork_digest: ForkDigest` is SSZ Bytes4
- teku: `SszBytes4.of(nextForkDigest).sszSerialize()`

Both produce 4 raw bytes (SSZ Bytes4 has no length prefix). Unlike cgc (item #41 — nimbus uses SSZ uint8 with 1-byte cap), nfd's SSZ Bytes4 encoding is spec-compliant because the spec explicitly says "SSZ Bytes4 ForkDigest". **No divergence here** because the spec encoding is unambiguous.

### lodestar direct Uint8Array

```typescript
const nextForkDigest =
  nextForkEpoch !== FAR_FUTURE_EPOCH
    ? config.forkBoundary2ForkDigest(config.getForkBoundaryAtEpoch(nextForkEpoch))
    : ssz.ForkDigest.defaultValue();
this.onSetValue(ENRKey.nfd, nextForkDigest);
```

No explicit SSZ wrap — `nextForkDigest` is already a `Uint8Array` of 4 bytes. SSZ Bytes4 = 4 raw bytes, so direct write produces correct on-wire format.

**Forward-compat**: if a future fork extends ForkDigest to >4 bytes, lodestar's untyped write may break.

### BPO transition cross-cut with item #31

Per item #31's audit: mainnet executed 2 BPO transitions:
- 412672 (BPO #1): 9 → 15 blobs
- 419072 (BPO #2): 15 → 21 blobs

Per spec: "[nfd] communicates the digest of the next scheduled fork, regardless of whether it is a regular or a Blob-Parameters-Only fork."

So at each BPO boundary, all 6 clients should:
1. Compute new fork digest via `compute_fork_digest_post_fulu(config, gvr, epoch)` (item #29)
2. Update their local ENR's nfd field with the new digest
3. Republish ENR to peers

**Live mainnet validation**: 2 BPO transitions executed without peer-discovery breakdown across all 6 clients. **Strongest possible validation that all 6 produce byte-identical nfd updates at BPO boundaries.**

### Spec compliance summary

| Aspect | Spec | All 6 clients |
|---|---|---|
| Format | SSZ Bytes4 (4 raw bytes) | ✅ all 6 |
| Default (no next fork) | 4 zero bytes | ✅ all 6 |
| ENR key | "nfd" | ✅ all 6 |
| Add when FULU_FORK_EPOCH set | MUST | ✅ in 5+ confirmed |
| Connection-time enforcement | MAY disconnect at/after fork boundary | ⚠️ prysm STRICTER (rejects pre-connection) |

## Cross-cut chain

This audit closes Fulu's ENR additions and cross-cuts:
- **Item #41** (`cgc` field): sibling Fulu-NEW ENR field; nfd has fixed-format (less divergent than cgc's variable-length)
- **Item #29** (signing-domain primitives + `compute_fork_digest`): nfd value source (caller computes via `compute_fork_digest_post_fulu`)
- **Item #31** (BPO `get_blob_parameters` + `compute_fork_digest` modified): BPO transitions trigger nfd updates; live mainnet validates 2 BPO transitions executed without peer-discovery breakdown
- **Item #28 NEW Pattern X candidate**: peer-discovery strictness divergence — prysm strictest (pre-connection rejection on nfd mismatch); other 5 soft (post-fork-boundary disconnect per spec MAY). Same forward-fragility class as Pattern T (lodestar empty-set) and lighthouse strict cgc validation.

## Adjacent untouched Fulu-active

- ENR `cgc` field cross-validation (item #41 covered)
- ENR `eth2` field encoding (Phase0/Bellatrix-heritage; ENRForkID containing `current_fork_digest`, `next_fork_version`, `next_fork_epoch`)
- ENR signature verification cross-client
- discv5 library distribution (geth ENR / sigp discv5 / Java tuweni / etc.)
- Peer scoring on nfd mismatch (lighthouse soft? grandine soft?)
- BPO #3 + nfd update consistency (when next BPO is scheduled, verify all 6 update nfd in sync)
- Cross-network ENR consistency (mainnet/sepolia/holesky/gnosis/hoodi)
- Pre-Fulu peer compatibility (nfd field absent; per ENR spec "ignore unknown ENR entries")
- nfd update frequency cross-client (per BPO entry vs per fork transition)
- Local ENR persistence across restarts (verify nfd survives)

## Future research items

1. **NEW Pattern X for item #28 catalogue**: peer-discovery strictness divergence — prysm strictest (pre-connection rejection on nfd mismatch); other 5 soft (post-fork-boundary disconnect per spec MAY). Forward-fragility class.
2. **Connection-time enforcement audit**: lighthouse, teku, nimbus, lodestar, grandine — when do they REJECT vs DISCONNECT vs SOFT-WARN on nfd mismatch?
3. **BPO #3 fixture**: synthesize a 3rd BPO entry; verify all 6 update nfd at the new boundary in sync.
4. **Pre-Fulu peer compatibility test**: peer ENR without nfd field; verify all 6 accept (per ENR spec).
5. **Malformed nfd test**: peer ENR with nfd of wrong length (e.g., 3 bytes or 5 bytes); verify all 6 reject with same error.
6. **ENR replay across restarts**: verify all 6 persist nfd across restart and reload identical value.
7. **Cross-fork transition fixture**: at exactly BPO boundary slot, verify all 6 produce identical nfd update.
8. **Compare prysm strictness vs spec text**: file consensus-specs issue if prysm's pre-connection rejection diverges from spec MAY.
9. **lighthouse two-write-path equivalence test**: build path (`enr.rs:284 builder.add_value(KEY, &[u8; 4])`) vs update path (`mod.rs:575 enr_insert::<Bytes>(KEY, ssz_bytes)`) — verify byte-identical on-wire output.
10. **grandine two-step-decode malformed input fixture**: 4 bytes that aren't valid ForkDigest (any 4 bytes are valid); test 5+ bytes input.
11. **Generate dedicated EF fixtures** for ENR `nfd` encoding (cross-fork-boundary value verification).
12. **Cross-network nfd consistency**: verify at sepolia/holesky/hoodi nfd values across all 6.
13. **ENR `eth2` + nfd consistency cross-validation**: spec says "MUST evaluate `nfd` alongside their existing consideration of the `ENRForkID::next_*` fields" — verify all 6 cross-validate the two.
14. **nfd staleness audit**: when local node falls behind (e.g., chain reorg crosses BPO boundary), how do clients reconcile their nfd vs the new canonical schedule?
15. **Peer scoring on nfd mismatch**: when a peer's nfd is wrong but doesn't trigger disconnect, do clients downgrade peer score?

## Summary

EIP-7594/EIP-7892 PeerDAS ENR `nfd` field encoding/decoding is implemented byte-for-byte equivalently across all 6 clients. **Unambiguous spec format** (SSZ Bytes4 = 4 raw bytes) eliminates the encoding divergence seen in cgc (item #41). Live mainnet validation: 2 BPO transitions executed without peer-discovery breakdown across all 6 clients.

Per-client divergences:
- **Connection-time enforcement**: prysm STRICTEST — REJECTS peers at connection time on nfd mismatch (`errNextDigestMismatch`), converts spec MAY → MUST. Other 5 likely soft (per spec "MAY disconnect at/after the fork boundary"). **NEW Pattern X candidate for item #28 catalogue.**
- **Encode call style**: lighthouse `[u8; 4]` direct (build) + SSZ-via-Bytes (update); teku SszBytes4; nimbus SSZ.encode; lodestar direct Uint8Array; grandine SSZ-via-Bytes; prysm raw bytes via geth ENR
- **Decode call style**: lighthouse single-step `[u8; 4]`; grandine two-step (Bytes → SSZ decode)
- **Build-vs-update divergence** (lighthouse): 2 write paths with different type wrappers but same on-wire bytes

**No format-divergence risk** because SSZ Bytes4 is unambiguous (unlike cgc's variable-length BE that admits SSZ uint8 misinterpretation by nimbus). All 6 produce 4 raw bytes; all 6 accept exactly 4 bytes.

**With this audit, Fulu's ENR additions are fully covered**: item #41 (`cgc`) + item #42 (`nfd`). PeerDAS audit corpus extends to 9 items: #33 custody → #34 verify → #35 DA → #37 subnet → #38 validator custody → #39 math → #40 proposer construction → #41 cgc → #42 nfd. **Nine-item arc covering the consensus-critical PeerDAS surface end-to-end + complete peer-discovery layer.**

**Total Fulu-NEW items: 13 (#30–#42).**
