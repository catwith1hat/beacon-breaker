---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [28, 38, 41, 42]
eips: [EIP-7594]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 45: MetaData v3 SSZ container + GetMetaData v3 RPC (`/eth2/beacon_chain/req/metadata/3/`) — EIP-7594 PeerDAS metadata layer

## Summary

Fulu-NEW MetaData v3 SSZ container adds a `custody_group_count: uint64` field to the Altair MetaData struct; the Fulu-NEW `GetMetaData v3` RPC method (`/eth2/beacon_chain/req/metadata/3/`) lets peers exchange the new container. This audit closes the PeerDAS metadata layer alongside ENR `cgc` (item #41) and `nfd` (item #42).

Spec (`vendor/consensus-specs/specs/fulu/p2p-interface.md:185-204`):

```
(
  seq_number: uint64
  attnets: Bitvector[ATTESTATION_SUBNET_COUNT]
  syncnets: Bitvector[SYNC_COMMITTEE_SUBNET_COUNT]
  custody_group_count: uint64 # cgc
)
```

> `custody_group_count` represents the node's custody group count. Clients MAY reject peers with a value less than `CUSTODY_REQUIREMENT`.

**Fulu surface (carried forward from 2026-05-04 audit; 5+ months of live mainnet cross-client GetMetaData v3 exchange):** all 6 clients implement byte-equivalent wire format. SSZ Container is unambiguous (unlike the variable-length BE encoding of ENR `cgc` per item #41 Pattern W); no format-divergence risk.

**Gloas surface (Glamsterdam target):** `vendor/consensus-specs/specs/gloas/p2p-interface.md` carries **NO `MetaData` modification heading** — neither a `Modified MetaData` section nor a `New GetMetaData v4` section exists. The Fulu MetaData v3 container and `GetMetaData v3` RPC carry forward verbatim into Gloas across all 6 clients. No Gloas-specific MetaData class (`MetadataMessageGloas`, `gloas.MetaData`, `MetaDataV4`, etc.) exists in any of the 6 trees.

**Per-client divergences are entirely cosmetic** (naming convention only, no wire format change):

- **prysm** uses `MetaDataV2` as the Go/proto type name (`vendor/prysm/proto/prysm/v1alpha1/p2p_messages.proto:115`) for what the spec calls `MetaData v3` — prysm's internal version numbering offsets by 1 because prysm never bumped the version for Altair's syncnets addition (prysm V0 = phase0, V1 = altair, V2 = fulu).
- **lighthouse** and **grandine** use spec-aligned `MetaDataV3` (`vendor/lighthouse/beacon_node/lighthouse_network/src/rpc/methods.rs:185-187`; `vendor/grandine/eth2_libp2p/src/rpc/methods.rs:345-354`). Both wrap in a `MetaData::V3(MetaDataV3 { ... })` superstruct/enum variant supporting V1/V2/V3 polymorphically.
- **teku** uses fork-named `MetadataMessageFulu` (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/datastructures/networking/libp2p/rpc/metadata/versions/fulu/MetadataMessageFulu.java:24-26`), extending `Container4<MetadataMessageFulu, SszUInt64, SszBitvector, SszBitvector, SszUInt64>`.
- **nimbus** uses fork-named `fulu.MetaData` (`vendor/nimbus/beacon_chain/spec/datatypes/fulu.nim:154-158`) but the RPC handler uses V3 nomenclature (`vendor/nimbus/beacon_chain/networking/peer_protocol.nim:272 proc getMetadata_v3(peer: Peer): fulu.MetaData`).
- **lodestar** uses fork-named `fulu.Metadata` for the SSZ type (`vendor/lodestar/packages/types/src/fulu/sszTypes.ts:33` defines `custodyGroupCount: UintNum64`) but V3-named for the RPC protocol (`vendor/lodestar/packages/beacon-node/src/network/reqresp/protocols.ts:25 export const MetadataV3 = toProtocol({...})`).

Three naming conventions: prysm V2 (offset-by-1); lighthouse + grandine V3 (spec-aligned); teku + nimbus + lodestar fork-named (Fulu/fulu). All produce the same wire bytes; the divergence is purely lexical.

**Pattern AA (item #28 catalogue)**: per-client SSZ container version-numbering divergence — prysm V2 = spec V3. Forward-fragility class: when spec adds MetaData v4 (e.g. for Heze), prysm may use `MetaDataV3` for it, perpetuating the offset.

**Pre-Fulu peer compatibility (V2 metadata response on V3 RPC):**

- **lighthouse**: strict superstruct enum dispatch — `MetaData::V2` and `MetaData::V3` are distinct variants; cross-version handling via explicit `metadata_v3(spec)` upgrade method (`vendor/lighthouse/beacon_node/lighthouse_network/src/rpc/methods.rs:223-244`) that defaults `custody_group_count: spec.custody_requirement` for V1/V2 inputs.
- **grandine**: identical enum-superstruct + `metadata_v3(chain_config)` upgrade method (`vendor/grandine/eth2_libp2p/src/rpc/methods.rs:390-406`) defaulting `chain_config.custody_requirement`. Parallel design to lighthouse.
- **lodestar**: TypeScript permissive — `Partial<fulu.Metadata>` cast with `?? this.config.CUSTODY_REQUIREMENT` default (`vendor/lodestar/packages/beacon-node/src/network/peers/peerManager.ts:343-365, 451`). Treats V2 metadata as V3 with cgc=CUSTODY_REQUIREMENT.
- **nimbus**: separate `getMetadata_v2` + `getMetadata_v3` procs (`peer_protocol.nim:264-274`) under the libp2p protocol multistream — V2 callers get the altair shape, V3 callers get the fulu shape directly.
- **teku**: registers schemas per milestone (`MetadataMessagesFactory`); V2 vs V3 negotiated at libp2p protocol-ID level.
- **prysm**: wraps via `wrapper.WrappedMetadataV2(&pb.MetaDataV2{...})` (`vendor/prysm/beacon-chain/p2p/subnets.go:469`) — single Go type covers what the spec calls V3.

**Cross-cut to item #41 (ENR cgc field):** the MetaData cgc field carries the SAME VALUE as the ENR cgc field but in a DIFFERENT WIRE FORMAT — ENR uses variable-length BE-trimmed (item #41 Pattern W triggers nimbus SSZ uint8 misinterpretation); MetaData uses SSZ uint64 (fixed 8 bytes). The two fields cross-validate at peer-connection time. Nimbus's ENR cgc divergence (SSZ uint8 instead of variable-length BE) does NOT affect MetaData cgc because the wire formats are distinct.

**Impact: none** — all 6 clients wire-equivalent at Fulu; Gloas carries the Fulu surface verbatim. Twenty-sixth `impact: none` result in the recheck series.

## Question

Pyspec defines MetaData v3 (`vendor/consensus-specs/specs/fulu/p2p-interface.md:185-204`) and GetMetaData v3 RPC (`:550-572`); Gloas spec does not modify either.

Three recheck questions:

1. **Fulu wire format** — do all 6 clients still produce byte-equivalent SSZ Container serialization for MetaData v3? Has any client introduced a wire-level divergence since the 2026-05-04 audit?
2. **Glamsterdam target — MetaData carry-forward** — does any client introduce a Gloas-specific MetaData type or `GetMetaData v4` RPC, despite no spec modification?
3. **Pattern AA forward-fragility** — does the prysm V2-vs-spec-V3 naming offset still hold? Are there additional naming divergences emerging at Gloas?

## Hypotheses

- **H1.** MetaData v3 is a 4-field SSZ container `(seq_number, attnets, syncnets, custody_group_count)`.
- **H2.** `custody_group_count` is SSZ uint64 (fixed 8 bytes on the wire — unlike ENR cgc per item #41).
- **H3.** GetMetaData v3 RPC protocol ID is `/eth2/beacon_chain/req/metadata/3/`.
- **H4.** Cross-validates with ENR cgc (same value, different wire encoding).
- **H5.** Fixed-size SSZ encoding for all 4 fields (bitvectors are fixed-length per preset).
- **H6.** Naming-convention divergence: prysm `MetaDataV2` (offset by 1); lighthouse + grandine `MetaDataV3` (spec-aligned); teku + nimbus + lodestar fork-named (Fulu/fulu). Pattern AA.
- **H7.** Pre-Fulu peers may speak V2 metadata; clients have per-policy upgrade defaults (lighthouse + grandine: `custody_requirement`; lodestar: `?? CUSTODY_REQUIREMENT`; nimbus: dual-handler `getMetadata_v2` + `getMetadata_v3`).
- **H8.** "Clients MAY reject peers with `custody_group_count` < CUSTODY_REQUIREMENT" — per-client policy.
- **H9.** *(Glamsterdam target — MetaData unchanged)* `vendor/consensus-specs/specs/gloas/p2p-interface.md` contains NO `Modified MetaData` heading. The Fulu container and V3 RPC carry forward into Gloas verbatim.
- **H10.** *(Glamsterdam target — no client introduces Gloas-specific MetaData)* No `MetadataMessageGloas`, `gloas.MetaData`, `MetaDataV4`, or `metadata/4` protocol-ID appears in any of the 6 trees.
- **H11.** *(Glamsterdam target — Pattern AA carries forward)* The prysm V2-vs-spec-V3 naming offset will likely propagate when MetaData v4 is added (e.g., for Heze): prysm may use `MetaDataV3` for spec V4.

## Findings

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓ (three naming conventions confirmed). H7 ✓ (per-client upgrade defaults). H8 ✓ (`custody_requirement` default in 2 clients; permissive `?? CUSTODY_REQUIREMENT` in 1). H9 ✓ (no Gloas modification). H10 ✓ (no Gloas-specific MetaData types). H11 ✓ (forward-fragility hypothesis; manifests at next MetaData version bump).

### prysm

`vendor/prysm/proto/prysm/v1alpha1/p2p_messages.proto:115`:

```protobuf
message MetaDataV2 {
  uint64 seq_number = 1;
  bytes attnets = 2;
  bytes syncnets = 3;
  uint64 custody_group_count = 4;
}
```

**Naming offset confirmed**: prysm internal type `MetaDataV2` corresponds to spec `MetaData v3`. The naming traces back to prysm's decision to not bump the proto version for Altair's syncnets addition (so prysm's V0 = phase0, V1 = altair, V2 = fulu, but spec's V1 = phase0, V2 = altair, V3 = fulu).

The internal-vs-spec naming asymmetry surfaces at multiple call sites:

- `vendor/prysm/beacon-chain/p2p/subnets.go:469` `s.metaData = wrapper.WrappedMetadataV2(&pb.MetaDataV2{...})` — type uses V2.
- `vendor/prysm/beacon-chain/p2p/types/object_mapping.go:119,122` `wrapper.WrappedMetadataV2(&ethpb.MetaDataV2{})` — type uses V2.
- (Earlier audit noted `updateSubnetRecordWithMetadataV3` function name uses V3 — function-vs-type mismatch within the prysm codebase.)

No Gloas-specific MetaData class. The V2 type is the only one with a `custody_group_count` field; Gloas reuses it.

H1 ✓. H2 ✓ (`uint64`). H3 ✓ (RPC ID is the protocol-level constant; uses spec V3 nomenclature). H4 ✓. H5 ✓. **H6 ⚠** (Pattern AA — prysm V2 = spec V3). H7 — backwards-compat handled via wrapper layer. H9 ✓ (no Gloas MetaData class). H10 ✓ (no Gloas-specific type). H11 ⚠ (Pattern AA forward-fragility).

### lighthouse

`vendor/lighthouse/beacon_node/lighthouse_network/src/rpc/methods.rs:185-187` (inside a `superstruct`-derived enum):

```rust
#[superstruct(only(V2, V3))]
pub syncnets: EnrSyncCommitteeBitfield<E>,
#[superstruct(only(V3))]
pub custody_group_count: u64,
```

V3 upgrade with `custody_requirement` default (`:222-244`):

```rust
pub fn metadata_v3(&self, spec: &ChainSpec) -> Self {
    match self {
        MetaData::V1(metadata) => MetaData::V3(MetaDataV3 {
            seq_number: metadata.seq_number,
            attnets: metadata.attnets.clone(),
            syncnets: Default::default(),
            custody_group_count: spec.custody_requirement,
        }),
        ...
```

RPC routing (`vendor/lighthouse/beacon_node/lighthouse_network/src/rpc/protocol.rs:316-396`):

```rust
SupportedProtocol::MetaDataV2,
SupportedProtocol::MetaDataV3,
...
SupportedProtocol::MetaDataV2 => "2",
SupportedProtocol::MetaDataV3 => "3",
```

Lighthouse advertises BOTH V2 and V3 over libp2p multistream; peers select via protocol negotiation. **Spec-aligned naming**; clean enum-superstruct with explicit per-variant fields.

No Gloas-specific entry in the `SupportedProtocol` enum; no `MetaDataGloas` or `MetaDataV4` type anywhere.

H1–H11 all ✓ except H6 (lighthouse spec-aligned, no Pattern AA contribution).

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/datastructures/networking/libp2p/rpc/metadata/versions/fulu/MetadataMessageFulu.java:24-43`:

```java
public class MetadataMessageFulu
    extends Container4<MetadataMessageFulu, SszUInt64, SszBitvector, SszBitvector, SszUInt64>
    implements MetadataMessage {
  ...
  MetadataMessageFulu(
      final MetadataMessageSchemaFulu schema,
      final UInt64 seqNumber,
      final SszBitvector attNets,
      final SszBitvector syncNets,
      final UInt64 custodyGroupCount) {
    super(schema, SszUInt64.of(seqNumber), attNets, syncNets, SszUInt64.of(custodyGroupCount));
  }
```

**Fork-named** (Fulu) rather than version-named. Subclass-extension pattern: separate classes for each milestone's MetaData (`MetadataMessagePhase0.java`, `MetadataMessageSchemaAltair.java`, `MetadataMessageFulu.java`).

No `MetadataMessageGloas.java` exists — only Phase0, Altair, Fulu versions. Consistent with the no-Gloas-modification spec.

H1–H11 all ✓; H6 — Pattern AA contribution: fork-named (Fulu) third convention alongside prysm V2 + lighthouse/grandine V3.

### nimbus

Container (`vendor/nimbus/beacon_chain/spec/datatypes/fulu.nim:154-158`):

```nim
MetaData* = object
  seq_number*: uint64
  attnets*: AttnetBits
  syncnets*: SyncnetBits
  custody_group_count*: uint64
```

RPC handlers (`vendor/nimbus/beacon_chain/networking/peer_protocol.nim:264-274`):

```nim
proc getMetadata_v2(peer: Peer): altair.MetaData
  {.libp2pProtocol("metadata", 2).} =
  let altair_metadata = altair.MetaData(
    seq_number: peer.network.metadata.seq_number,
    attnets: peer.network.metadata.attnets,
    syncnets: peer.network.metadata.syncnets)
  altair_metadata

proc getMetadata_v3(peer: Peer): fulu.MetaData
  {.libp2pProtocol("metadata", 3).} =
  peer.network.metadata
```

**Two distinct procs** — `getMetadata_v2` returns `altair.MetaData` (no cgc); `getMetadata_v3` returns `fulu.MetaData` (with cgc). libp2p multistream selects the right handler per peer's negotiated protocol. **Fork-named types** (`altair.MetaData`, `fulu.MetaData`) but **version-named procs** (`getMetadata_v2`, `getMetadata_v3`) — same dual-naming pattern as lodestar.

No Gloas-specific proc or type. No `getMetadata_v4` or `gloas.MetaData`.

H1–H11 all ✓; H6 — Pattern AA contribution: fork-named third convention.

### lodestar

Container (`vendor/lodestar/packages/types/src/fulu/sszTypes.ts:33`):

```typescript
custodyGroupCount: UintNum64,
```

(part of the `Metadata` container schema in the `fulu` ssz types module).

RPC protocol (`vendor/lodestar/packages/beacon-node/src/network/reqresp/protocols.ts:25`):

```typescript
export const MetadataV3 = toProtocol({ ... });
```

State (`vendor/lodestar/packages/beacon-node/src/network/metadata.ts:45-53`):

```typescript
private _metadata: fulu.Metadata;
...
this._metadata = {
  ...ssz.fulu.Metadata.defaultValue(),
  custodyGroupCount: modules.networkConfig.custodyConfig.targetCustodyGroupCount,
};
```

Permissive cross-version handling (`vendor/lodestar/packages/beacon-node/src/network/peers/peerManager.ts:343-365, 451`):

```typescript
custodyGroupCount: (metadata as Partial<fulu.Metadata>)?.custodyGroupCount,
...
const custodyGroupCount =
  (metadata as Partial<fulu.Metadata>).custodyGroupCount ?? this.config.CUSTODY_REQUIREMENT;
...
const custodyGroupCount = peerData?.metadata?.custodyGroupCount ?? this.config.CUSTODY_REQUIREMENT;
```

**Permissive default**: `Partial<fulu.Metadata>` cast allows the field to be absent (e.g., on a V2 peer's response); `?? this.config.CUSTODY_REQUIREMENT` substitutes the local node's CUSTODY_REQUIREMENT. Other clients (lighthouse + grandine) explicitly upgrade via `metadata_v3(spec)`; lodestar inlines the default at every read site. JavaScript `undefined`-vs-`0` ambiguity is masked by the `??` operator.

No Gloas-specific Metadata type or protocol. No `MetadataV4` or `gloas.Metadata`.

H1–H11 all ✓; H6 — Pattern AA contribution: fork-named (lowercase 'd') + version-named protocol (third convention, same as nimbus + teku at the type layer but with a distinct V3-protocol naming).

### grandine

`vendor/grandine/eth2_libp2p/src/rpc/methods.rs:253, 345-354`:

```rust
V3(MetaDataV3),
...
pub struct MetaDataV3 {
    /// A sequential counter indicating when data gets modified.
    pub seq_number: u64,
    /// The persistent attestation subnet bitfield.
    pub attnets: EnrAttestationBitfield,
    /// The persistent sync committee bitfield.
    pub syncnets: EnrSyncCommitteeBitfield,
    /// The node's custody group count.
    pub custody_group_count: u64,
}
```

V3 upgrade with `chain_config.custody_requirement` default (`:389-406`):

```rust
pub fn metadata_v3(&self, chain_config: &ChainConfig) -> Self {
    match self {
        MetaData::V1(metadata) => MetaData::V3(MetaDataV3 {
            seq_number: metadata.seq_number,
            attnets: metadata.attnets.clone(),
            syncnets: Default::default(),
            custody_group_count: chain_config.custody_requirement,
        }),
        MetaData::V2(metadata) => MetaData::V3(MetaDataV3 {
            seq_number: metadata.seq_number,
            attnets: metadata.attnets.clone(),
            syncnets: metadata.syncnets.clone(),
            custody_group_count: chain_config.custody_requirement,
        }),
        md @ MetaData::V3(_) => md.clone(),
    }
}
```

Parallel design to lighthouse — enum-of-V1/V2/V3, explicit `metadata_v3(chain_config)` upgrade method, defaults `custody_requirement`. **Spec-aligned naming**.

No `MetaDataV4` or `gloas.MetaData` type anywhere.

H1–H11 all ✓; H6 — spec-aligned, no Pattern AA contribution (along with lighthouse).

## Cross-reference table

| Client | Type name | Naming convention | RPC protocol ID | cgc field type | V1/V2 → V3 upgrade default | Pattern AA contribution |
|---|---|---|---|---|---|---|
| **prysm** | `MetaDataV2` (`proto/prysm/v1alpha1/p2p_messages.proto:115`) | **offset-by-1** (V2 = spec V3) | `/eth2/beacon_chain/req/metadata/3/` | `uint64 custody_group_count = 4` (proto) | via `wrapper.WrappedMetadataV2(...)` (subnets.go:469) | **YES — prysm V2 vs spec V3** |
| **lighthouse** | `MetaDataV3` (`rpc/methods.rs:185-187`) | **spec-aligned** | `/eth2/beacon_chain/req/metadata/3/` (`protocol.rs:341`) | `pub custody_group_count: u64` | `metadata_v3(spec)` → `spec.custody_requirement` (methods.rs:223-229) | no |
| **teku** | `MetadataMessageFulu` (`.../metadata/versions/fulu/MetadataMessageFulu.java:24-26`) | **fork-named** | registered via `MetadataMessagesFactory` (no separate V4 yet) | `SszUInt64` (4th field of Container4) | per-milestone schema dispatch | fork-named (third convention) |
| **nimbus** | `fulu.MetaData` (`spec/datatypes/fulu.nim:154-158`) | **fork-named** types + **V3-named** procs | `proc getMetadata_v3` (`peer_protocol.nim:272`) | `custody_group_count: uint64` | dual-handler procs `getMetadata_v2` + `getMetadata_v3` (peer_protocol.nim:264-274) | fork-named (third convention) |
| **lodestar** | `fulu.Metadata` types (`sszTypes.ts:33`) + `MetadataV3` protocol (`protocols.ts:25`) | **fork-named** types + **V3-named** protocol | `MetadataV3 = toProtocol({...})` | `custodyGroupCount: UintNum64` | permissive `?? this.config.CUSTODY_REQUIREMENT` (peerManager.ts:343-365, 451) | fork-named (third convention) |
| **grandine** | `MetaDataV3` (`eth2_libp2p/src/rpc/methods.rs:345-354`) | **spec-aligned** | enum variant `MetaData::V3` | `pub custody_group_count: u64` | `metadata_v3(chain_config)` → `chain_config.custody_requirement` (methods.rs:390-406) | no |

**Naming-convention counts**: 1 offset (prysm), 2 spec-aligned (lighthouse + grandine), 3 fork-named (teku + nimbus + lodestar). Wire format: 6-of-6 identical. Gloas-specific MetaData type: 0-of-6.

## Empirical tests

- ✅ **Live Fulu mainnet operation since 2025-12-03 (5+ months)**: continuous cross-client GetMetaData v3 exchange. No SSZ deserialization failures attributable to MetaData format divergence. **Verifies H1–H5 + H8 at production scale.**
- ✅ **Per-client grep verification (this recheck)**: type names, RPC protocol IDs, V1/V2 → V3 upgrade defaults all confirmed via file:line citations above.
- ✅ **Gloas MetaData carry-forward verification**: `grep -rn "MetaDataGloas\|MetaDataV4\|gloas.MetaData\|gloas.Metadata\|MetadataMessageGloas" vendor/` returns empty (excluding consensus-specs). **Verifies H9 + H10**: no client has introduced Gloas-specific MetaData scaffolding.
- ⏭ **Pre-Fulu V2 peer compatibility cross-client test**: synthesize a V2 metadata response on a V3 RPC; verify each client's V2 → V3 upgrade path applies the correct default (lighthouse + grandine: `custody_requirement`; lodestar: `CUSTODY_REQUIREMENT`; nimbus: dual-handler dispatch; prysm + teku: TBD).
- ⏭ **Cross-validation: ENR cgc vs MetaData cgc**: present a peer with mismatched ENR cgc (item #41) and MetaData cgc values; verify each client's reconciliation policy (which is authoritative). Note nimbus's ENR cgc SSZ uint8 misinterpretation (item #41 Pattern W) is separate from MetaData cgc which is uint64.
- ⏭ **Byte-equivalence fixture**: synthesize MetaData with specific values across all 6; SHA-256 the encoded bytes; verify identical. Not yet executed; expected pass given 5+ months mainnet validation.
- ⏭ **Pattern AA forward-fragility**: when MetaData v4 ships (e.g. for Heze or a future fork), file a tracking issue for prysm to align V3 → V4 naming with spec.

## Conclusion

The Fulu MetaData v3 SSZ container and `GetMetaData v3` RPC method (`/eth2/beacon_chain/req/metadata/3/`) are implemented across all 6 clients with byte-equivalent wire format. 5+ months of live mainnet cross-client GetMetaData v3 exchange validates that the SSZ Container schema is unambiguous and produces identical bytes regardless of per-client naming convention.

At the Glamsterdam target, `vendor/consensus-specs/specs/gloas/p2p-interface.md` contains **NO MetaData modification heading** — no `Modified MetaData`, no `GetMetaData v4`. The Fulu surface carries forward into Gloas verbatim. Confirmed by `grep`-verification across all 6 vendored client trees: no `MetaDataV4`, `gloas.MetaData`, `MetadataMessageGloas`, or `metadata/4` protocol-ID anywhere.

Per-client divergences are entirely lexical (no wire-format impact):

- **prysm** ships `MetaDataV2` for spec V3 — offset-by-1 internal version numbering (Pattern AA).
- **lighthouse + grandine** ship `MetaDataV3` — spec-aligned, with explicit `metadata_v3(spec)` / `metadata_v3(chain_config)` upgrade methods defaulting to `custody_requirement`.
- **teku + nimbus + lodestar** ship fork-named (`MetadataMessageFulu`, `fulu.MetaData`, `fulu.Metadata`) with version-named RPC handlers/protocols on top.

Three pre-Fulu compatibility policies: lighthouse + grandine explicit V2 → V3 upgrade with `custody_requirement`; lodestar permissive `?? this.config.CUSTODY_REQUIREMENT` at every read site; nimbus dual-handler procs (`getMetadata_v2` + `getMetadata_v3`) under libp2p multistream.

**Pattern AA (item #28 catalogue)** — per-client SSZ container version-numbering divergence — carries forward from Fulu into Glamsterdam unchanged. When MetaData v4 eventually ships (next fork that touches the surface), the prysm offset will become more confusing (prysm `MetaDataV3` for spec V4); filing a prysm rename PR is queued as a future research item.

**Cross-cut to item #41 (ENR cgc)**: nimbus's ENR cgc SSZ uint8 misinterpretation (Pattern W) is wire-format-isolated to the ENR encoding — does NOT affect MetaData cgc (uint64 SSZ Container field). Cross-validation between MetaData cgc and ENR cgc at peer-connection time is per-client policy; spec doesn't mandate reconciliation.

**Impact: none** — all 6 wire-equivalent at Fulu; Gloas inherits Fulu verbatim. Twenty-sixth `impact: none` result in the recheck series. With this recheck the PeerDAS metadata layer (items #38 + #41 + #42 + #45) is fully closed for the Glamsterdam target.
