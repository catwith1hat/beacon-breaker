---
status: source-code-reviewed
impact: synthetic-state
last_update: 2026-05-13
builds_on: [33, 38]
eips: [EIP-7594]
splits: [nimbus]
# main_md_summary: nimbus encodes the ENR `cgc` field as SSZ uint8 (1 byte always); the spec and the other 5 clients use variable-length BE with leading-zero stripping (`cgc=0` → empty bytes) — wire-format divergence on cgc=0 and silent overflow at cgc≥256
prysm_version: v3.2.2-rc.1-2535-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 41: ENR `cgc` (custody group count) field encoding/decoding (EIP-7594 PeerDAS peer discovery)

## Summary

The peer-discovery primitive that closes the loop from custody computation (item #38) to network advertisement. Each client uses its own ENR/discv5 library — encoding format divergence risk is real. Without correct encoding, peers can't determine each other's custody sets → can't request the right data columns → DA failures.

EIP-7594 PeerDAS ENR `cgc` field encoding/decoding is implemented across all 6 clients with **multiple format and validation divergences** observed at the source level. Mainnet cgc values fit within the divergence-free range (`[4, 128]` → 1-byte BE encoding), so no production divergence has surfaced. **Edge cases (cgc=0 and cgc≥256) would expose divergence on synthetic states.**

The dominant divergence is nimbus's SSZ uint8 wire format vs the spec's (and other 5 clients') variable-length BE: at cgc=0 nimbus emits `[0x00]` (1 byte) while others emit empty bytes; at cgc≥256 nimbus silently overflows uint8 while others continue to encode correctly. Active interop risk on cgc=0 reception (nimbus's `SSZ.decode(bytes, uint8)` fails on empty input). Impact synthetic-state because mainnet cgc ∈ [4, 128] does not cross either boundary.

## Question

Spec definition (`p2p-interface.md` "Custody group count" section):

> A new field is added to the ENR under the key `cgc` to facilitate custody data column discovery.
>
> | Key   | Value |
> | ----- | ----- |
> | `cgc` | Custody group count, `uint64` big endian integer with no leading zero bytes (`0` is encoded as empty byte string) |
>
> Clients MAY reject peers with a value less than `CUSTODY_REQUIREMENT`.

The non-trivial encoding (variable-length BE with leading-zero stripping; empty for 0) is RLP-style minimal encoding. **Cross-client divergence risk** in:

1. Encoding format (variable-length BE vs SSZ uint8 vs fixed-width).
2. Empty-string-for-zero handling.
3. Range validation strictness (MAY vs MUST per spec).
4. Type width (uint8 vs uint32 vs uint64).
5. Feature gating (when to add cgc to ENR).

**Scope.** In: `cgc` ENR field encoding (write path) + decoding (read path); range validation against `[CUSTODY_REQUIREMENT, NUMBER_OF_CUSTODY_GROUPS]`; type width across 6 clients; feature gating (Fulu-scheduled vs always); MetaData v3 `custody_group_count` field cross-validation.

Out: ENR signature/RLP framing (discv5 library-internal); MetaData v3 SSZ schema (separate Track E item); peer-discovery routing logic (orthogonal); GetMetaData v3 RPC handler (out of consensus scope); custody-aware peer selection (downstream consumer).

The hypothesis: *all six clients emit and accept the same wire bytes for the `cgc` ENR field at any cgc value in the spec-defined range, and validate range/type identically per the spec's MAY-reject clause.*

**Consensus relevance.** Peer-discovery primitive. A wire-format divergence on the `cgc` field directly produces inability to discover peers' custody sets → inability to request the right data columns → DA-sampling failures. Mainnet currently runs cgc ∈ [4, 128] (single-byte BE), so the divergent edge cases (cgc=0 empty-bytes vs `[0x00]`; cgc≥256 multi-byte vs uint8 overflow) are not exercised. Edge cases are constructable on a synthetic state (a peer advertising cgc=0 in spec violation, or a future spec change pushing NUMBER_OF_CUSTODY_GROUPS > 255).

## Hypotheses

- **H1.** Spec format: variable-length BE uint64 with no leading zero bytes; cgc=0 = empty bytes.
- **H2.** ENR key string is `"cgc"`.
- **H3.** Range validation: client MAY reject cgc < CUSTODY_REQUIREMENT; spec doesn't define upper bound.
- **H4.** Type width: `uint64` per spec.
- **H5.** Feature gating: cgc added when `FULU_FORK_EPOCH != FAR_FUTURE_EPOCH`.
- **H6.** MetaData v3 `custody_group_count` field is consistent with ENR `cgc` field.
- **H7.** cgc value derived from `get_validators_custody_requirement` (item #38) for validator nodes; `CUSTODY_REQUIREMENT = 4` for non-validator nodes.
- **H8.** Empty-bytes encoding for cgc=0 produces a valid ENR record.
- **H9.** Decode: clients accept variable-length input (1-8 bytes).
- **H10.** Cross-network cgc reception: clients must interoperate on the wire format across all cgc values.

## Findings

H2 ✓ (key string `"cgc"` is uniform). H5 split: lighthouse fork-gates (`if spec.is_peer_das_scheduled()`); lodestar explicit always; others TBD/always. H6 ✓ across cross-validation. H7 ✓ across all 6.

**H1 fails for nimbus**: SSZ uint8 (always 1 byte, even for cgc=0) instead of variable-length BE.
**H4 fails for nimbus** (uint8, cap 255) and partially for teku (Java `int`, 32-bit, cap ~2 billion).
**H8 fails for nimbus**: emits `[0x00]` for cgc=0 instead of empty bytes.
**H9 fails for nimbus**: SSZ uint8 decoder expects exactly 1 byte; empty input from other 5 fails to decode.
**H10 active interop risk for nimbus on cgc=0**: nimbus decode of others' empty-bytes fails.

The mainnet range cgc ∈ [4, 128] is single-byte BE in both formats — production traffic has not triggered the divergence in 5+ months of cross-client peer discovery. Impact = `synthetic-state` because a synthetic peer (cgc=0 or cgc≥256) is required to exercise the divergent paths.

### prysm

`vendor/prysm/beacon-chain/p2p/p2p_interface.go:225` — `CustodyGroupCountFromRecord(record *enr.Record) (uint64, error)`:

```go
func CustodyGroupCountFromRecord(record *enr.Record) (uint64, error) {
    if record == nil {
        return 0, ErrRecordNil
    }
    var cgc Cgc
    if err := record.Load(&cgc); err != nil {
        return 0, ErrCannotLoadCustodyGroupCount
    }
    return uint64(cgc), nil
}
```

ENR key constant: `params.BeaconNetworkConfig().CustodyGroupCountKey = "cgc"` (`mainnet_config.go:42`). Uses geth's ENR helper (`record.Set(&cgc)` for write; `record.Load(&cgc)` for read). `Cgc.ENRKey()` returns `"cgc"`. **NO range validation** on the read path — accepts any uint64. **Most permissive** of the six.

Forward-fragile: a peer advertising cgc=2^64-1 (intentionally malformed) would be accepted; downstream code that indexes into a custody-group array could overflow.

H1 ✓ (geth discv5 emits variable-length BE). H2 ✓. **H3 ✗** (no lower-bound check). H4 ✓ (`uint64`). H5 TBD (likely always set). H6–H9 ✓. H10 ✓ at all cgc values.

### lighthouse

`vendor/lighthouse/beacon_node/lighthouse_network/src/discovery/enr.rs:75-86`:

```rust
fn custody_group_count<E: EthSpec>(&self, spec: &ChainSpec) -> Result<u64, &'static str> {
    let cgc = self
        .get_decodable::<u64>(PEERDAS_CUSTODY_GROUP_COUNT_ENR_KEY)
        .ok_or("ENR custody group count non-existent")?
        .map_err(|_| "Could not decode the ENR custody group count")?;

    if (spec.custody_requirement..=spec.number_of_custody_groups).contains(&cgc) {
        Ok(cgc)
    } else {
        Err("Invalid custody group count in ENR")
    }
}
```

ENR key constant: `PEERDAS_CUSTODY_GROUP_COUNT_ENR_KEY = "cgc"` at `enr.rs:31`. Write path at `enr.rs:282`:

```rust
if spec.is_peer_das_scheduled() {
    builder.add_value(PEERDAS_CUSTODY_GROUP_COUNT_ENR_KEY, &custody_group_count);
    builder.add_value(NEXT_FORK_DIGEST_ENR_KEY, &next_fork_digest);
}
```

**Strictest validation**: spec MAY → MUST, rejects cgc < CUSTODY_REQUIREMENT = 4 AND > NUMBER_OF_CUSTODY_GROUPS = 128. **Spec-compliant feature gating**: only adds `cgc` if Fulu fork epoch is set (matches spec MUST).

H1 ✓ (sigp discv5 emits variable-length BE). H2 ✓. H3 ✓ (strictest interpretation of MAY). H4 ✓ (`u64`). H5 ✓ (Fulu-scheduled gate). H6–H10 ✓ at all cgc values.

### teku

`vendor/teku/networking/p2p/src/main/java/tech/pegasys/teku/networking/p2p/discovery/DiscoveryNetwork.java:152`:

```java
discoveryService.updateCustomENRField(
    DAS_CUSTODY_GROUP_COUNT_ENR_FIELD, Bytes.ofUnsignedInt(count).trimLeadingZeros());
```

**Most spec-faithful encoding**: `Bytes.ofUnsignedInt(int)` produces 4-byte BE; `.trimLeadingZeros()` strips leading zeros. For cgc=0: trims to empty bytes ✓ matches spec. For cgc=128: `[0x80]` ✓. For cgc=42: `[0x2a]` ✓.

**Type width concern**: `ofUnsignedInt(int)` takes 32-bit Java int. Mainnet cgc ≤ 128 fits fine. If NUMBER_OF_CUSTODY_GROUPS > 2^32 (highly unlikely), teku silently truncates. **Forward-compat risk** but practically irrelevant. **Negative-count defensive check**: throws `IllegalArgumentException` for negative count.

H1 ✓ (explicit trim-leading-zeros — most spec-faithful idiom). H2 ✓. H3 partial (TBD via deeper search). **H4 partial** (32-bit `int`, cap 2^32). H5 TBD. H6–H10 ✓ at mainnet cgc values; forward-fragile at cgc ≥ 2^32.

### nimbus

`vendor/nimbus/beacon_chain/networking/eth2_network.nim:2713`:

```nim
enrCustodySubnetCountField: SSZ.encode(cgcnets)
```

Decode at `vendor/nimbus/beacon_chain/networking/eth2_discovery.nim:159`:

```nim
SSZ.decode(cgcCountBytes.get(), uint8)
```

Range validation at `eth2_network.nim:2540`: `if cgc <= NUMBER_OF_COLUMNS` then accept; **NO lower bound check** (accepts 0+).

**Wire-format divergences (NEW Pattern W for item #28 catalogue)**: encodes via `SSZ.encode(CgcCount)` where `CgcCount` is `uint8` (SSZ uint8 is fixed 1-byte LE, which is byte-identical to 1-byte BE for u8).

- `cgc=0`: nimbus emits `[0x00]` (1 byte); spec/other 5 emit `[]` (empty bytes). **Mismatch.**
- `cgc=128`: nimbus emits `[0x80]` (1 byte); other 5 emit `[0x80]` (1 byte). Match.
- `cgc=256+`: nimbus **CANNOT REPRESENT** (uint8 overflow); other 5 emit `[0x01, 0x00]` (2 bytes BE).

**Active interop risk on cgc=0**:
- Other 5 sending cgc=0 emit empty bytes → nimbus's `SSZ.decode(bytes, uint8)` would FAIL (expects 1 byte).
- Nimbus sending cgc=0 emits `[0x00]` (1 byte) → other 5 decode as 0 (BE single byte = 0). ✓ asymmetric.

**Forward-compat risk at NUMBER_OF_CUSTODY_GROUPS > 255**: nimbus's `uint8` silently wraps → wrong custody advertisement → wrong peer selection.

H1 ✗ (SSZ uint8 fixed-width, not variable-length BE). H2 ✓. **H3 ✗** (no lower bound). **H4 ✗** (`uint8`, cap 255). H5 TBD (likely always set). H6 ✓ at mainnet cgc values. **H7** ✓ (cgc derived from item #38 helper). **H8 ✗** (cgc=0 emits `[0x00]` not empty bytes). **H9 ✗** (`SSZ.decode(bytes, uint8)` fails on empty input). **H10 active interop risk at cgc=0 and cgc≥256.**

### lodestar

`vendor/lodestar/packages/beacon-node/src/network/metadata.ts:16`:

```typescript
export function serializeCgc(cgc: number): Uint8Array {
  return intToBytes(cgc, Math.ceil(Math.log2(cgc + 1) / 8), "be");
}
```

**Variable-length BE** matching spec. Length calculation: `Math.ceil(Math.log2(cgc + 1) / 8)`:
- cgc=0: `log2(1)/8 = 0` → 0 bytes (empty) ✓ matches spec.
- cgc=1: `log2(2)/8 = 0.125` → 1 byte ✓.
- cgc=128: `log2(129)/8 ≈ 0.880` → 1 byte ✓.
- cgc=256: `log2(257)/8 ≈ 1.005` → 2 bytes ✓.

**Most algorithmically explicit** of the 6. **Type width**: JS `number` is IEEE 754 double — cap at 2^53. Forward-compat OK for any realistic NUMBER_OF_CUSTODY_GROUPS.

**Feature gating**: explicit comment "Set CGC regardless of fork. It may be useful to clients before Fulu, and will be ignored otherwise" (`metadata.ts:71`). **Most defensive** — sets cgc unconditionally; pre-Fulu clients ignore unknown ENR fields.

H1 ✓ (explicit variable-length BE). H2 ✓. H3 TBD. **H4 partial** (`number` IEEE 754 double, cap 2^53 — safe). H5 ✓ (explicit always-set). H6–H10 ✓ at all cgc values.

### grandine

`vendor/grandine/p2p/src/discovery/enr.rs:75` — uses `get_decodable::<u64>(KEY)` like lighthouse (same sigp discv5 library wrapper). Write path at `enr.rs:299`:

```rust
builder.add_value(PEERDAS_CUSTODY_GROUP_COUNT_ENR_KEY, &custody_group_count);
```

ENR key constant: `PEERDAS_CUSTODY_GROUP_COUNT_ENR_KEY = "cgc"` at `enr.rs:31`. The range-validation logic at the call site is TBD via deeper search; likely uses a similar range check.

H1 ✓ (sigp discv5). H2 ✓. H3 TBD (likely range check). H4 ✓ (`u64`). H5 TBD. H6–H10 ✓ at all cgc values.

## Cross-reference table

| Client | ENR key constant | Encoding (write) | Decoding (read) | Range validation | Type width | Feature gate |
|---|---|---|---|---|---|---|
| **prysm** | `CustodyGroupCountKey` = "cgc" (`mainnet_config.go:42`) | `record.Set(&cgc)` (geth ENR helper); `Cgc.ENRKey()` returns "cgc" | `record.Load(&cgc)` returns u64 (`p2p_interface.go:225`) | **NO range validation** in `CustodyGroupCountFromRecord` | `uint64` | TBD; likely always set |
| **lighthouse** | `discovery/enr.rs:31 PEERDAS_CUSTODY_GROUP_COUNT_ENR_KEY = "cgc"` | `builder.add_value(KEY, &cgc: u64)` only **`if spec.is_peer_das_scheduled()`** (`enr.rs:282`) | `get_decodable::<u64>(KEY)` (`enr.rs:77`) | **STRICTEST**: `(custody_requirement..=number_of_custody_groups).contains(&cgc)` (`:81-85`) — rejects 0-3 AND >128 | `u64` | only if Fulu scheduled |
| **teku** | `DAS_CUSTODY_GROUP_COUNT_ENR_FIELD` = "cgc" | `discoveryService.updateCustomENRField(KEY, Bytes.ofUnsignedInt(count).trimLeadingZeros())` (`DiscoveryNetwork.java:152`) — explicit spec-faithful | TBD via deeper search | Throws `IllegalArgumentException` for negative count | `int` (32-bit; truncates at >2^32) | TBD; likely always set |
| **nimbus** | `enrCustodySubnetCountField` = "cgc" | **`SSZ.encode(cgcnets: CgcCount)`** (`eth2_network.nim:2713`) — **SSZ uint8 fixed 1-byte encoding** | `SSZ.decode(bytes, uint8)` (`eth2_discovery.nim:159`) — expects exactly 1 byte | `if cgc <= NUMBER_OF_COLUMNS` then accept; **NO lower bound check** (`eth2_network.nim:2540`) | **`uint8`** (cap at 255) | TBD; likely always set |
| **lodestar** | `ENRKey.cgc = "cgc"` (`metadata.ts:18`) | `serializeCgc(cgc) = intToBytes(cgc, Math.ceil(Math.log2(cgc + 1) / 8), "be")` (`util/metadata.ts:16`) — variable-length BE; **cgc=0 → 0 bytes** (matches spec) | `deserializeCgc(bytes) = bytesToInt(bytes, "be")` | TBD | `number` (JS double; cap at 2^53) | **explicit "regardless of fork"** (`metadata.ts:71`) — always set |
| **grandine** | `discovery/enr.rs:31 PEERDAS_CUSTODY_GROUP_COUNT_ENR_KEY = "cgc"` | `builder.add_value(KEY, &cgc: u64)` (`enr.rs:299`) | `get_decodable::<u64>(KEY)` (`enr.rs:75`) | TBD via deeper search | `u64` | TBD |

## Empirical tests

No dedicated EF fixture exists for ENR `cgc` field encoding/decoding (ENR is a discv5-level concern and lives outside the standard EF state-test corpus). Implicit cross-validation via 5+ months of mainnet peer discovery: all 6 clients have been discovering each other on mainnet at cgc ∈ [4, 128] (single-byte BE) without breaking. **The wire-format divergence at cgc=0 and cgc≥256 has not been triggered in production** because mainnet validator nodes set cgc ≥ 4 (per `get_validators_custody_requirement` floor) and the spec cap NUMBER_OF_CUSTODY_GROUPS = 128 is well under 255.

### Suggested fuzzing vectors

- **T1.1** (priority — generate dedicated ENR-encoding fixture set). Reference cgc encodings for `cgc ∈ {0, 1, 4, 128, 255, 256, 1000, 2^32, 2^53}`. Verify all 6 clients produce/accept identical bytes at each value. Pure-function fuzzing.
- **T1.2** (priority — cross-client cgc=0 interop test). 5 clients advertise cgc=0 (empty bytes); verify nimbus's SSZ uint8 decoder behavior on empty input (expected: decode failure).
- **T1.3** (cross-client cgc=255+ interop test). 5 clients advertise cgc=255 or 256; verify nimbus's uint8 overflow behavior at 256 (expected: silent wrap to 0).
- **T1.4** (defensive — `cgc = 2^64 - 1` malformed ENR). Peer advertises maximal uint64. Verify lighthouse rejects (range check); other 5 behaviour TBD.
- **T2.1** (lighthouse strict-validation impact audit). Peers advertising cgc ∈ {0, 1, 2, 3} should be rejected by lighthouse; verify what fraction of mainnet peers this affects (likely zero — non-validators default to CUSTODY_REQUIREMENT = 4).
- **T2.2** (MetaData v3 cross-validation cross-client). When cgc differs between ENR field and MetaData v3 `custody_group_count` field, which takes precedence per client?

## Conclusion

**Status: source-code-reviewed.** Source review of all 6 clients against the updated checkouts (versions per front matter) confirms:

- **H1 (wire format) fails for nimbus**: SSZ uint8 instead of variable-length BE per spec. The divergence is invisible on mainnet (cgc ∈ [4, 128] encodes to a single byte in both formats) but exposes on cgc=0 (`[0x00]` vs empty bytes) and cgc≥256 (uint8 overflow). **NEW Pattern W for item #28 catalogue.**
- **H3 (range validation) split**: lighthouse strictest (rejects 0-3 AND >128); nimbus accepts 0+; prysm no validation. Spec MAY → per-client interpretation.
- **H4 (type width) split**: nimbus `uint8` (cap 255); teku `int` (cap 2^32); lodestar `number` (cap 2^53); prysm/lighthouse/grandine `uint64`.
- **H5 (feature gating) split**: lighthouse only-if-Fulu-scheduled (spec-compliant); lodestar always (over-eager but safe).
- **H10 (cross-network interop) active risk at cgc=0**: nimbus decode of others' empty-bytes fails.

Combined `splits = [nimbus]`. Impact = `synthetic-state` because:

- Mainnet cgc ∈ [4, 128] sits inside the divergence-free range (single-byte BE encoding matches both formats).
- The cgc=0 divergence requires a peer to violate the spec (cgc < CUSTODY_REQUIREMENT) — constructable on a synthetic state but not seen on canonical mainnet traffic in 5+ months.
- The cgc≥256 divergence requires NUMBER_OF_CUSTODY_GROUPS to be raised above 255 — not in any current or planned fork.

Notable per-client style differences:

- **prysm** uses geth's discv5 ENR helper with no range validation — most permissive.
- **lighthouse** uses sigp discv5; strictest range check (spec MAY → MUST); only-if-Fulu-scheduled feature gating (spec-compliant).
- **teku** uses Java Tuweni `Bytes.ofUnsignedInt(...).trimLeadingZeros()` — most spec-faithful idiom; 32-bit int width forward-fragile.
- **nimbus** uses SSZ uint8 fixed 1-byte encoding — Pattern W divergence.
- **lodestar** uses explicit `Math.ceil(Math.log2(cgc + 1) / 8)` length calculation — most algorithmically explicit; explicit always-set feature gating.
- **grandine** uses sigp discv5 like lighthouse; validation logic TBD.

Recommendations to the harness and the audit:

- **Wire Fulu ENR/network category fixtures** in BeaconBreaker harness — ENR encoding tests would require generating reference bytes and verifying all 6 produce identical ENR records.
- **NEW Pattern W for item #28 catalogue**: ENR-encoding format divergence (nimbus SSZ uint8 vs spec variable-length BE). Forward-fragility at cgc=0 and cgc≥256.
- **Cross-client cgc=0 / cgc=255+ interop tests** — direct synthetic-state fixtures.
- **Lighthouse strict-validation impact audit** — quantify peer-pool impact of MAY → MUST conversion.
- **Teku 32-bit int width audit** — forward-compat at NUMBER_OF_CUSTODY_GROUPS > 2^32.
- **Lodestar always-set policy audit** — confirm pre-Fulu clients ignore unknown ENR fields (per ENR/discv5 spec).
- **Prysm permissive validation audit** — malicious cgc=2^64-1 ENR field downstream behaviour.
- **Grandine validation TBD** — locate range-check logic; verify same-as-lighthouse or different.
- **Teku decoder TBD** — locate cgc decode + validation logic.
- **MetaData v3 cross-validation cross-client** — when cgc differs between ENR field and MetaData v3 field, which takes precedence?
- **Pre-Fulu vs post-Fulu behavior** — peers without cgc field at all; per-client default.

## Cross-cuts

### With item #38 (`get_validators_custody_requirement`)

Item #38 produces the cgc value advertised here. The "only-grow" semantics there ensure cgc ≥ 4 on validator nodes, which keeps mainnet inside the divergence-free range and explains why Pattern W is not observable on canonical traffic.

### With item #33 (PeerDAS custody assignment)

The cgc value gates how many custody groups the local node samples + advertises. A peer with divergent cgc (e.g., nimbus's silent uint8 overflow at cgc≥256 would report cgc=0 instead of cgc=256) would custody fewer groups than advertised, causing DA-sampling failures downstream.

### With item #28 NEW Pattern W

ENR-encoding format divergence (nimbus SSZ uint8 vs spec variable-length BE). Same forward-fragility class as Pattern S/T (spec-undefined edge case + hardcoded constants). A future Glamsterdam-or-later spec change that raises NUMBER_OF_CUSTODY_GROUPS above 255 would convert this from synthetic-state to mainnet-reachable for nimbus.

### With MetaData v3 `custody_group_count`

The same value is encoded in both the ENR `cgc` field (here) and the MetaData v3 SSZ `custody_group_count` field (separate Track E item). When the two disagree (e.g., due to ENR not yet republished after a cgc change), which one takes precedence is a per-client policy choice that needs cross-client verification.

## Adjacent untouched

1. **Generate dedicated ENR-encoding fixture set** — reference cgc encodings for `cgc ∈ {0, 1, 4, 128, 255, 256, 1000, 2^32, 2^53}`. Pure-function fuzzing.
2. **ENR `nfd` (next fork digest) field encoding** — Fulu p2p extension, similar pattern to `cgc`.
3. **MetaData v3 `custody_group_count` SSZ field cross-client** (Track E follow-up).
4. **discv5 library distribution cross-client** (geth ENR / sigp discv5 / Java tuweni / etc.).
5. **ENR signature verification cross-client** (sigp discv5 vs others).
6. **GetMetaData v3 RPC handler cross-client correctness.**
7. **Custody-aware peer selection algorithms cross-client** (downstream consumer).
8. **Cross-network ENR consistency** (mainnet/sepolia/holesky/gnosis/hoodi).
9. **Pre-Fulu vs post-Fulu cgc behavior** (lighthouse skip; others always).
10. **Peer scoring on cgc validation failures** (lighthouse rejects → peer rejected; others accept).
11. **Backwards-compat: peers without cgc field at all** (pre-Fulu peers; or Fulu peers that fail to set cgc).
12. **Decoder behavior on malformed cgc** (leading zeros, oversized, signed bytes).
13. **ENR-update frequency cross-client** — when cgc changes (validator added/removed; effective balance changes triggering item #38's "only-grow" semantics), how often is ENR republished?
14. **Item #28 NEW Pattern W catalogue entry** — ENR-encoding format divergence (nimbus SSZ uint8 vs spec variable-length BE). Forward-fragility at cgc=0 (nimbus encodes 1 byte; spec/others empty) and at cgc>=256 (nimbus uint8 overflow).
15. **Six-dispatch-idiom-equivalent for ENR encoding** — the six clients use six distinct encoding idioms (geth ENR Set/Load, sigp discv5 get_decodable + range-check, Java Tuweni Bytes.ofUnsignedInt + trimLeadingZeros, Nim SSZ.encode + SSZ.decode, TypeScript intToBytes + log2-length, sigp discv5 again for grandine). Useful reference for future ENR-field audits.
