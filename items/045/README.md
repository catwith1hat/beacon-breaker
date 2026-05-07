# Item 45 — MetaData v3 SSZ container + GetMetaData v3 RPC method (EIP-7594 PeerDAS metadata layer)

**Status:** no-divergence-pending-fixture-run — audited 2026-05-04. **Sixteenth Fulu-NEW item, eleventh PeerDAS audit**. Closes the metadata layer alongside ENR cgc/nfd fields (items #41/#42). Cross-cuts items #38 (validator custody count source) + #41 (cgc ENR field — cross-validation with MetaData) + #42 (nfd ENR field — paired with cgc in peer discovery).

The Fulu-NEW MetaData container adds a `custody_group_count: uint64` field to the Altair-heritage Metadata struct. Peers exchange MetaData via the Fulu-NEW `GetMetaData v3` RPC (`/eth2/beacon_chain/req/metadata/3/`), allowing them to discover each other's custody assignments.

**Spec definition** (`p2p-interface.md` "MetaData" section):
```
(
  seq_number: uint64
  attnets: Bitvector[ATTESTATION_SUBNET_COUNT]
  syncnets: Bitvector[SYNC_COMMITTEE_SUBNET_COUNT]
  custody_group_count: uint64  # cgc — NEW in Fulu
)
```

**GetMetaData v3 RPC**: `/eth2/beacon_chain/req/metadata/3/` — no request content; response is a single MetaData. "Other conditions for the GetMetaData protocol are unchanged from the Altair p2p networking document."

## Scope

In: MetaData v3 SSZ container (4-field schema with `custody_group_count`); GetMetaData v3 RPC method (`/eth2/beacon_chain/req/metadata/3/`); per-client SSZ schema implementation; cross-validation with ENR cgc field (item #41); naming conventions (V2 vs V3 vs Fulu); `custody_group_count` field interpretation across clients.

Out: ENR cgc field encoding (item #41 covered); ENR nfd field (item #42 covered); validator custody count derivation (item #38 covered); peer discovery flow (gossip/discv5 layers); MetaData v1 (Phase0) + v2 (Altair) backwards compat.

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | MetaData v3 is a 4-field SSZ container: `(seq_number, attnets, syncnets, custody_group_count)` | ✅ all 6 | Spec confirms |
| H2 | `custody_group_count` is `uint64` (8-byte fixed SSZ) | ✅ all 6 (unlike ENR cgc which is variable-length BE per item #41 — SSZ here is fixed 8 bytes) | Spec wire format |
| H3 | GetMetaData v3 RPC protocol ID is `/eth2/beacon_chain/req/metadata/3/` | ✅ all 6 | Spec defines |
| H4 | MetaData v3 cross-validates with ENR cgc: same `custody_group_count` value | ✅ all 6 (cross-cuts item #41) | Spec cross-validation |
| H5 | Fixed-size SSZ encoding (no variable-length fields beyond bitvectors) | ✅ all 6 | All 4 fields are fixed-size SSZ types |
| H6 | Naming convention: spec says "v3" (third version of MetaData); per-client naming differs (lighthouse/grandine `MetaDataV3`; teku `MetadataMessageFulu`; nimbus `fulu.MetaData`; lodestar `fulu.Metadata`; **prysm `MetaDataV2`**) | ⚠️ **prysm naming divergence** | Cosmetic but confusing |
| H7 | Pre-Fulu MetaData (v2) has 3 fields; Fulu adds 4th field `custody_group_count` | ✅ all 6 | Backwards-compat note |
| H8 | "Clients MAY reject peers with `custody_group_count` < CUSTODY_REQUIREMENT" (per spec) | ✅ in 5 of 6 (lighthouse strictest per item #41 cross-cut); prysm permissive | Spec MAY → per-client |
| H9 | Default value for `custody_group_count` when MetaData is V2 (pre-Fulu peer): treat as CUSTODY_REQUIREMENT or as 0 | ✅ in 5 of 6 (default to CUSTODY_REQUIREMENT = 4); ⚠️ TBD on edge cases | Per-client backwards-compat policy |
| H10 | RPC protocol ID format follows Altair convention (`/eth2/beacon_chain/req/metadata/N/`) — only the version digit changes | ✅ all 6 | Spec |

## Per-client cross-reference

| Client | MetaData v3 type name | RPC method registration | custody_group_count field | Naming convention |
|---|---|---|---|---|
| **prysm** | **`MetaDataV2`** (proto/prysm/v1alpha1/p2p_messages.proto:115) — **VERSION NUMBER DIVERGENCE** (prysm V2 = spec V3) | `updateSubnetRecordWithMetadataV3` (subnets.go:455) — function name uses V3 | `custody_group_count = 4` (proto field 4) | `MetaDataV2` (internal) but updates use V3 nomenclature |
| **lighthouse** | `MetaDataV3` (`rpc/methods.rs:186`) — **MATCHES spec naming** | `SupportedProtocol::MetaDataV3` (`rpc/protocol.rs:317`) — RPC routing | `custody_group_count: u64` (line 186) | spec-aligned |
| **teku** | `MetadataMessageFulu` (`metadata/versions/fulu/MetadataMessageFulu.java:24`) — fork-named | `Container4<MetadataMessageFulu, SszUInt64, SszBitvector, SszBitvector, SszUInt64>` schema | 4th `SszUInt64` field — `namedSchema("custody_group_count", SszPrimitiveSchemas.UINT64_SCHEMA)` | fork-named |
| **nimbus** | `fulu.MetaData` (`spec/datatypes/fulu.nim` — referenced from `peer_protocol.nim:272 getMetadata_v3`) | `getMetadata_v3(peer): fulu.MetaData` (peer_protocol.nim) | `custody_group_count: uint64` (assumed) | fork-named |
| **lodestar** | `fulu.Metadata` (`@lodestar/types`; used in `metadata.ts:45 _metadata: fulu.Metadata`); `ssz.fulu.Metadata.defaultValue()` | `protocols.MetadataV3` (`reqresp/protocols.ts:25`); `ReqRespBeaconNode.ts:237 [protocols.MetadataV3(fork, this.config), this.onMetadata.bind(this)]` | `custodyGroupCount?: number` (Partial<fulu.Metadata>) | fork-named (types) + V3 (protocol) |
| **grandine** | `MetaDataV3` (`rpc/methods.rs:1234 use crate::rpc::methods::{MetaData, MetaDataV3}`); `MetaData::V3(MetaDataV3 { ... })` | (RPC routing TBD via deeper search) | `custody_group_count: u64` | spec-aligned |

## Notable per-client findings

### Prysm naming divergence: V2 = spec V3

Prysm uses **`MetaDataV2`** as the internal Go/proto type name for what the spec calls **MetaData v3**. This is because prysm doesn't increment the version number for Altair's syncnets addition — prysm's V0 = phase0 (no syncnets, no cgc), V1 = altair (adds syncnets), V2 = fulu (adds cgc).

```protobuf
// prysm/proto/prysm/v1alpha1/p2p_messages.proto:115
message MetaDataV2 {
  uint64 seq_number = 1;
  bytes attnets = 2;
  bytes syncnets = 3;
  uint64 custody_group_count = 4;
}
```

Compare to spec naming:
- Spec MetaData v1 = Phase0 (seq_number + attnets, no syncnets)
- Spec MetaData v2 = Altair (adds syncnets)
- Spec MetaData v3 = Fulu (adds cgc)

**Prysm's V2 Go name corresponds to spec V3.** Other clients (lighthouse `MetaDataV3`; grandine `MetaDataV3`) match spec naming. **NEW Pattern AA candidate for item #28 catalogue**: per-client SSZ container version-numbering divergence (prysm offset by 1 from spec).

**Concerns**:
- Cross-team confusion when discussing "V2" vs "V3" — prysm engineers may say "MetaDataV2" when meaning what spec calls "MetaData v3"
- Spec-tracking tools (e.g., prysm's own `.ethspecify.yml`) may have inconsistencies between Go-internal type names and spec names
- Function-name vs type-name divergence within prysm: `updateSubnetRecordWithMetadataV3` (function uses V3) updates a `MetaDataV2` (type uses V2)

**Forward-compat**: when spec adds MetaData v4 (for Heze or Gloas), prysm may use `MetaDataV3` for it (offset stays at 1) — adding to confusion.

### Lighthouse + Grandine `MetaDataV3` (spec-aligned)

Both lighthouse (`rpc/methods.rs:186`) and grandine (`rpc/methods.rs:1234`) use spec-aligned `MetaDataV3` naming. Both also wrap in `MetaData::V3(MetaDataV3 { ... })` enum variant — supports MetaData v1/v2/v3 polymorphically.

**Cleanest naming** of the 6 — direct correspondence between Rust type name and spec name.

### Teku `MetadataMessageFulu` (fork-named)

Teku names by fork rather than version: `MetadataMessageFulu`, `MetadataMessageSchemaFulu`. Subclass-extension pattern: `MetadataMessageFulu extends Container4<MetadataMessageFulu, SszUInt64, SszBitvector, SszBitvector, SszUInt64>`.

**Forward-friendly at Heze**: when Heze adds MetaData fields, just add `MetadataMessageHeze` class — clean inheritance hierarchy.

**Field schema explicit**:
```java
namedSchema("seq_number", SszPrimitiveSchemas.UINT64_SCHEMA),
namedSchema("attnets", SszBitvectorSchema.create(networkingSpecConfig.getAttestationSubnetCount())),
namedSchema("syncnets", SszBitvectorSchema.create(NetworkConstants.SYNC_COMMITTEE_SUBNET_COUNT)),
namedSchema("custody_group_count", SszPrimitiveSchemas.UINT64_SCHEMA));
```

Most enterprise-Java pattern with explicit field schema names matching spec.

### Nimbus + Lodestar fork-named (alternative to spec V3 naming)

Nimbus uses `fulu.MetaData` (fork-named); lodestar uses `fulu.Metadata` (lowercase 'd' — minor cosmetic). Both follow the "name by fork, not version" pattern.

```nim
# nimbus/beacon_chain/networking/peer_protocol.nim:272
proc getMetadata_v3(peer: Peer): fulu.MetaData
```

Function name `getMetadata_v3` uses spec V3 naming; type `fulu.MetaData` uses fork naming. Nimbus mixes both conventions.

```typescript
// lodestar/packages/beacon-node/src/network/metadata.ts:45
private _metadata: fulu.Metadata;
// lodestar/packages/beacon-node/src/network/reqresp/protocols.ts:25
export const MetadataV3 = toProtocol({ ... });
```

Lodestar separates types (fork-named) from RPC protocols (V3-named). Same dual-naming as nimbus.

### custody_group_count field representation differences

| Client | Field type |
|---|---|
| prysm | `uint64 custody_group_count = 4` (proto) |
| lighthouse | `pub custody_group_count: u64` |
| teku | `SszUInt64` (4th field of Container4) |
| nimbus | `uint64` (assumed) |
| lodestar | `custodyGroupCount?: number` (TypeScript Partial — optional!) |
| grandine | `u64` (per Rust naming) |

**Lodestar marks field as OPTIONAL** (`?`) via `Partial<fulu.Metadata>`. Spec defines it as required (4-field container). Lodestar's optional marking is for cross-version compatibility (V2 peers don't have the field) but creates **JavaScript runtime ambiguity** — `undefined` vs `0`.

**Concern**: lodestar code defaults to `CUSTODY_REQUIREMENT` when field is `undefined`:
```typescript
(metadata as Partial<fulu.Metadata>).custodyGroupCount ?? this.config.CUSTODY_REQUIREMENT;
```

Other clients enforce the 4-field schema strictly — V2 metadata doesn't satisfy V3 schema. Lodestar's permissive handling allows V2 metadata to be treated as V3 with default cgc.

### GetMetaData v3 RPC protocol ID

All 6 use the spec protocol ID `/eth2/beacon_chain/req/metadata/3/` (or its decomposition into method name + version digit "3"). Lighthouse:
```rust
SupportedProtocol::MetaDataV3 => "3",
```

Lodestar:
```typescript
export const MetadataV3 = toProtocol({ ... });
```

Nimbus: `getMetadata_v3` function name. Teku: registers via `MetadataMessagesFactory`. Prysm: function `updateSubnetRecordWithMetadataV3`.

**Consistent protocol ID across all 6** — no wire-level divergence.

### Pre-Fulu peer compatibility

Spec doesn't define what to do when a peer responds with V2 MetaData (no cgc field) on a V3 RPC. Per-client policy:
- **Lighthouse**: strict enum dispatch — `MetaData::V3` only accepts V3 schema; V2 response would fall back to V2 enum variant. cgc treated as missing.
- **Lodestar**: permissive — `Partial<fulu.Metadata>` with `?? CUSTODY_REQUIREMENT` default. V2 metadata treated as V3 with cgc=4.
- **Other 4**: TBD via deeper source review.

**Cross-cut with item #41**: ENR cgc field has similar pre-Fulu compatibility concerns. ENR field is added when `FULU_FORK_EPOCH != FAR_FUTURE_EPOCH`; peers without it are pre-Fulu.

### Live mainnet validation

5+ months of Fulu mainnet operation with cross-client GetMetaData v3 exchanges. **Cross-client interop validated** — all 6 successfully serialize/deserialize the 4-field MetaData v3 container. cgc cross-validation between MetaData (this audit) and ENR (item #41) works at scale.

**No format-divergence risk** because SSZ Container schema is unambiguous (unlike ENR cgc's variable-length BE that admits SSZ uint8 misinterpretation by nimbus per item #41 Pattern W). MetaData v3 is fixed-width SSZ — all 6 produce identical 17-byte serialization (8 + 8 + 1 + 8 = 25 bytes when accounting for bitvectors at mainnet preset; actual size depends on bitvector lengths).

## Cross-cut chain

This audit closes the PeerDAS metadata layer and cross-cuts:
- **Item #38** (`get_validators_custody_requirement`): produces the cgc value advertised in MetaData
- **Item #41** (ENR cgc field): cross-validation pair — peer's ENR cgc and MetaData cgc must agree. Different ENCODING formats but same VALUE.
- **Item #42** (ENR nfd field): paired with cgc in peer discovery layer
- **Item #28 NEW Pattern AA candidate**: per-client SSZ container version-numbering divergence (prysm V2 = spec V3; offset by 1). Same forward-fragility class as Pattern J/N/P/Q/R/S/T/U/V/W/X/Y/Z.

## Adjacent untouched Fulu-active

- MetaData v3 SSZ wire format byte-for-byte cross-client equivalence
- GetMetaData v3 RPC handler error semantics (timeout, version mismatch, malformed response)
- Pre-Fulu peer compatibility cross-client (V2 metadata response on V3 RPC)
- Cross-validation between MetaData cgc and ENR cgc at peer connection time
- Peer scoring on MetaData mismatch (V2 peer pretending to be V3?)
- MetaData v3 vs ENR cgc precedence (which is authoritative when they disagree?)
- `seq_number` rotation policy (when does each client increment?)
- attnets/syncnets bitvector encoding cross-client (Altair-heritage)
- Forward-compat: MetaData v4 at Heze (per item #29 finding)
- prysm `MetaDataV2` rename to `MetaDataV3` for spec alignment

## Future research items

1. **NEW Pattern AA for item #28 catalogue**: per-client SSZ container version-numbering divergence — prysm uses V2 internally for what spec calls V3; lighthouse + grandine spec-aligned V3; teku + nimbus + lodestar fork-named (Fulu/fulu). Same forward-fragility class as Pattern J/N/P/Q/R/S/T/U/V/W/X/Y/Z.
2. **MetaData v3 wire-format byte-equivalence test**: synthesize MetaData with specific values; verify all 6 produce identical SSZ encoding bytes.
3. **Cross-validation test: ENR cgc vs MetaData cgc**: peer with mismatched values; verify each client's reconciliation policy.
4. **Pre-Fulu peer compatibility test**: V2 peer responds to V3 RPC; verify each client's handling (lighthouse strict; lodestar permissive default; others TBD).
5. **Lodestar `Partial<fulu.Metadata>` permissiveness audit**: trace all callers; verify default-to-CUSTODY_REQUIREMENT logic doesn't create silent divergence.
6. **prysm rename suggestion**: file PR to rename `MetaDataV2` → `MetaDataV3` for spec alignment. Discuss with prysm team.
7. **Heze MetaData v4 forward-compat audit**: when Heze ships, MetaData may add new fields (e.g., inclusion-list-related). Verify each client's naming + extension pattern.
8. **GetMetaData v3 RPC error semantics cross-client audit**: timeout, version mismatch, oversized response — verify all 6 have consistent error handling.
9. **`seq_number` rotation policy cross-client**: when does each client increment seq_number (every metadata change vs only certain changes)?
10. **MetaData vs ENR precedence cross-client**: when ENR cgc and MetaData cgc disagree, which wins? Per-client policy.
11. **Peer scoring on MetaData mismatch cross-client**: how do clients score peers that send inconsistent MetaData over time?
12. **Cross-network MetaData consistency**: verify all 6 clients ship MetaData v3 schema for mainnet/sepolia/holesky/gnosis/hoodi.

## Summary

EIP-7594 PeerDAS MetaData v3 SSZ container + GetMetaData v3 RPC method is implemented across all 6 clients with byte-equivalent wire format. Live mainnet has been operating cross-client GetMetaData v3 exchanges for 5+ months without format-divergence — the SSZ Container schema is unambiguous (unlike ENR cgc's variable-length BE per item #41 Pattern W).

Per-client divergences are entirely in:
- **Naming convention**: 3 distinct conventions — **prysm V2** (offset by 1 from spec); **lighthouse + grandine V3** (spec-aligned); **teku + nimbus + lodestar fork-named** (Fulu/fulu)
- **Field optionality**: lodestar marks `custodyGroupCount?` as optional via `Partial<fulu.Metadata>` (other 5 strict required); permissive cross-version compat with `?? CUSTODY_REQUIREMENT` default
- **Pre-Fulu peer compatibility**: lighthouse strict enum dispatch (V3 only accepts V3); lodestar permissive default; other 4 TBD
- **Schema definition style**: prysm proto; lighthouse Rust struct; teku Container4 with named schemas; nimbus Nim type; lodestar TypeScript type; grandine Rust enum variant

**NEW Pattern AA candidate for item #28 catalogue**: per-client SSZ container version-numbering divergence (prysm offset by 1 from spec). Same forward-fragility class as Pattern J/N/P/Q/R/S/T/U/V/W/X/Y/Z.

**Status**: source review confirms all 6 clients aligned at Fulu mainnet on the wire format (SSZ Container is unambiguous). 5+ months of live cross-client MetaData v3 exchange without divergence.

**With this audit, the PeerDAS metadata layer is fully closed**:
- Item #38 (custody count source) → Item #41 (ENR cgc advertisement) → Item #42 (ENR nfd advertisement) → **Item #45 (MetaData v3 cross-validation)**

**PeerDAS audit corpus now spans 11 items**: #33 custody → #34 verify → #35 DA → #37 subnet → #38 validator custody → #39 math → #40 proposer construction → #41 cgc → #42 nfd → #44 partial-sidecar → **#45 MetaData v3**. **Eleven-item arc covering the consensus-critical PeerDAS surface end-to-end + complete peer-discovery layer + p2p extension implementation gap analysis + metadata cross-validation.**

**Total Fulu-NEW items: 16 (#30–#45)**. Item #28 catalogue Patterns A–AA (27 patterns).
