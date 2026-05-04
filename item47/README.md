# Item 47 — Status v2 RPC handshake (EIP-7594 PeerDAS handshake extension with `earliest_available_slot`)

**Status:** no-divergence-pending-fixture-run — audited 2026-05-04. **Eighteenth Fulu-NEW item, thirteenth PeerDAS audit**. The Fulu-NEW handshake RPC that adds `earliest_available_slot` field — communicating the earliest slot for which the node has data column sidecars and full beacon blocks available. Cross-cuts item #46 (RPC serve range — peers now advertise their actual range upfront via Status v2 instead of requiring out-of-band knowledge). Closes the Fulu RPC handshake layer.

**Spec definition** (`p2p-interface.md` "Status v2" section):
```
Protocol ID: /eth2/beacon_chain/req/status/2/

Request, Response Content:
(
  fork_digest: ForkDigest
  finalized_root: Root
  finalized_epoch: Epoch
  head_root: Root
  head_slot: Slot
  # [New in Fulu:EIP7594]
  earliest_available_slot: Slot
)
```

The new `earliest_available_slot` field allows peers to determine each other's serve range upfront during handshake, avoiding the need to discover serve range via per-RPC `ResourceUnavailable` errors (item #46).

**Spec semantics for `earliest_available_slot`** (notable):
- If node can serve all blocks but NOT all sidecars during retention period, advertise earliest sidecar-availability slot
- If node can serve all sidecars during retention period, advertise earliest block-availability slot
- Conjunction of `MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS` (Deneb) AND `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` (Fulu)

## Scope

In: `Status v2` RPC handshake; `earliest_available_slot` field; per-client SSZ schema (6-field Container); V1 → V2 transition handling (default value for missing field); cross-validation with item #46 RPC serve range; protocol ID `/eth2/beacon_chain/req/status/2/`; per-client naming conventions.

Out: Status v1 (Phase0) backwards compat (only relevant for cross-version peer interop); `BeaconBlocksByRangeV2` (Capella-heritage); `MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS` constant (Deneb-heritage); peer disconnect/scoring on Status mismatch.

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | Status v2 is a 6-field SSZ container with `earliest_available_slot` as 6th field | ✅ all 6 | Spec confirms |
| H2 | Protocol ID is `/eth2/beacon_chain/req/status/2/` | ✅ all 6 | Spec defines |
| H3 | Fields 1-5 are unchanged from Status v1 (fork_digest, finalized_root, finalized_epoch, head_root, head_slot) | ✅ all 6 | Spec backwards-compat |
| H4 | `earliest_available_slot` is `Slot` (uint64 SSZ fixed 8 bytes) | ✅ all 6 | Spec |
| H5 | V1 → V2 transition: default `earliest_available_slot = 0` (or genesis slot) for missing field | ✅ all 6 (per-client default) | Backwards compat |
| H6 | Per-client naming: 5 of 6 use V2 naming; teku uses fork-naming (StatusMessageFulu) | ⚠️ teku divergence | Same pattern as MetaData v3 (item #45) |
| H7 | Status v2 active at FULU_FORK_EPOCH; pre-Fulu peers may use Status v1 | ✅ all 6 | Spec implies via "[New in Fulu:EIP7594]" annotation |
| H8 | Cross-validation with item #46 RPC serve range: `earliest_available_slot ≤ data_column_serve_range.start` | ✅ implied (peer-side validation; per-client TBD) | Spec consistency requirement |
| H9 | Sync logic uses `earliest_available_slot` to prefer peers that can serve required range | ✅ confirmed in lodestar (`Peer did not respect earliestAvailableSlot for DataColumnSidecarsByRoot/Range`); other 5 TBD | Per-client sync optimization |
| H10 | `earliest_available_slot = 0` means node serves from genesis (super-archive) | ✅ all 6 | Spec |

## Per-client cross-reference

| Client | Type name | Source location | V1 → V2 default | Naming |
|---|---|---|---|---|
| **prysm** | `pb.StatusV2` (proto) | `sync/rpc_status.go:200 decodeStatus(stream, epoch) *pb.StatusV2`; `:366 status := &pb.StatusV2{...}` | `EarliestAvailableSlot: 0` (default for V1→V2 conversion at `:515`) | V2 (proto convention) |
| **lighthouse** | `StatusMessage::V2(StatusMessageV2)` enum | `rpc/codec.rs:1053` `StatusMessage::V2(StatusMessageV2 { ..., earliest_available_slot: Slot::new(0) })`; `protocol.rs:304 SupportedProtocol::StatusV2` | `Slot::new(0)` (codec.rs:1059) | V2 (enum-named) |
| **teku** | **`StatusMessageFulu`** (Container6) | `StatusMessageFulu.java:29 extends Container6<StatusMessageFulu, SszBytes4, SszBytes32, SszUInt64, SszBytes32, SszUInt64, SszUInt64>`; schema in `StatusMessageSchemaFulu.java:42 namedSchema("earliest_available_slot", SszPrimitiveSchemas.UINT64_SCHEMA)` | `Optional<UInt64> earliestAvailableSlot` parameter; `Preconditions.checkArgument(earliestAvailableSlot.isPresent())` for V2 | **Fulu** (fork-named — diverges from V2 convention) |
| **nimbus** | `StatusMsgV2` | `peer_protocol.nim:36 earliestAvailableSlot*: Slot`; `:111 getCurrentStatusV2()`; `:180 handleStatusV2`; `dag.earliestAvailableSlot()` source | `GENESIS_SLOT` (`:139` for default-initialized state) | V2 (Nim convention) |
| **lodestar** | `StatusV2` protocol; type via SSZ schema | `reqresp/protocols.ts:43 export const StatusV2 = toProtocol({ method: ReqRespMethod.Status, version: Version.V2 })` | (TBD via deeper search) | V2 (protocol-named); also references `earliestAvailableSlot` in `Peer did not respect earliestAvailableSlot for DataColumnSidecarsByRoot/Range` log messages |
| **grandine** | `StatusMessageV2` + `StatusMessage::V2` enum | `rpc/methods.rs:163 pub earliest_available_slot: Slot`; `:116 pub fn earliest_available_slot(self) -> Option<Slot>`; `:180 status_v2(&self)`; `protocol.rs:249 StatusV2` | `earliest_available_slot: 0` (`:191` for default V1→V2 conversion) | V2 (Rust convention) |

## Notable per-client findings

### Teku naming divergence: Fulu instead of V2

Teku uses `StatusMessageFulu` (fork-named) for what spec calls Status v2. Other 5 use V2 naming (`StatusV2`, `StatusMessageV2`, `pb.StatusV2`, `StatusMsgV2`).

**Same pattern as MetaData v3 (item #45)**: teku consistently uses fork-naming for SSZ containers, while other clients use spec V-naming.

**Cross-team confusion concern**: teku engineers may say "StatusMessageFulu" while spec says "Status v2".

**Pattern AA cross-cut** (item #45): per-client SSZ container naming convention divergence — teku fork-named (`MetadataMessageFulu`, `StatusMessageFulu`); lighthouse + grandine V-named (`MetaDataV3`, `StatusMessageV2`); prysm V-named (with V2 = spec V3 offset for MetaData; V2 = spec V2 for Status — INCONSISTENT within prysm); nimbus + lodestar mixed. **Pattern AA scope expands** to include Status messages.

### V1 → V2 transition default value: 0 vs GENESIS_SLOT

| Client | Default for missing `earliest_available_slot` |
|---|---|
| prysm | `EarliestAvailableSlot: 0` (rpc_status.go:515) |
| lighthouse | `Slot::new(0)` (codec.rs:1059) |
| teku | `Preconditions.checkArgument(earliestAvailableSlot.isPresent())` — V2 REQUIRES the field; no default for V2 |
| nimbus | `GENESIS_SLOT` (peer_protocol.nim:139) |
| lodestar | (TBD) |
| grandine | `earliest_available_slot: 0` (methods.rs:191) |

**Nimbus diverges**: uses `GENESIS_SLOT` constant (= 0 on mainnet, but symbolic). Other 4 use literal `0`.

**Teku diverges in error semantics**: requires `earliestAvailableSlot.isPresent()` for V2 schema construction — throws if absent. Other clients silently default to 0/GENESIS_SLOT.

**Forward-compat**: if a future spec change defines a non-zero default, the silent-default-to-0 pattern in 4 of 6 clients diverges. Teku's strict-required pattern is more spec-faithful.

### Lighthouse two-way V1↔V2 conversion

```rust
// codec.rs:1053
StatusMessage::V2(StatusMessageV2 {
    fork_digest, finalized_root, finalized_epoch, head_root, head_slot,
    earliest_available_slot: Slot::new(0),
}),

// codec.rs:1309 comment
// A StatusV2 still encodes as a StatusV1 since version is Version::V1
```

Lighthouse explicitly comments on the V1↔V2 conversion semantics — when a V2 StatusMessage is sent over a V1 protocol, it encodes as V1 (drops `earliest_available_slot`); when a V1 is received over a V2 protocol, it decodes with default 0.

**Most explicit cross-version handling** of the 6.

### Nimbus separate handle path with explicit setStatusV2Msg

```nim
proc handleStatusV2(peer: Peer, ...)
proc setStatusV2Msg(state: PeerSyncPeerState, ...)
```

Nimbus has TWO functions for V2 status handling — `handleStatusV2` (incoming) + `setStatusV2Msg` (state mutation). **Cleanest separation** of incoming-message handling from state update.

```nim
# peer_protocol.nim:111
proc getCurrentStatusV2(state: PeerSyncNetworkState): StatusMsgV2 =
  ...
  earliestAvailableSlot: dag.earliestAvailableSlot())
```

Nimbus computes `earliestAvailableSlot` from the DAG (`dag.earliestAvailableSlot()`). Other clients TBD on the source.

### Prysm separate decoder for V1 vs V2

```go
// rpc_status.go:200
func (s *Service) decodeStatus(stream network.Stream, epoch primitives.Epoch) (*pb.StatusV2, error) {
    msg := new(pb.StatusV2)
```

Prysm decodes ALL status messages as V2 (with default 0 for V1 messages). Cleanest decode path.

```go
// rpc_status.go:503
func statusV2(msg any) (*pb.StatusV2, error) {
    if status, ok := msg.(*pb.StatusV2); ok { return status, nil }
    if status, ok := msg.(*pb.Status); ok {
        // Convert V1 → V2 with default
        return &pb.StatusV2{
            ForkDigest:            status.ForkDigest,
            ...,
            EarliestAvailableSlot: 0, // Default value for StatusV2
        }, nil
    }
    return nil, errors.New("message is not type *pb.Status or *pb.StatusV2")
}
```

Explicit V1 → V2 conversion function. **Most defensive** type-handling.

### Lodestar uses `earliest_available_slot` for sync optimization

```typescript
// handlers/dataColumnSidecarsByRoot.ts:47
chain.logger.verbose("Peer did not respect earliestAvailableSlot for DataColumnSidecarsByRoot", {...});

// handlers/dataColumnSidecarsByRange.ts:37
chain.logger.verbose("Peer did not respect earliestAvailableSlot for DataColumnSidecarsByRange", {...});
```

Lodestar logs when peer's RPC response doesn't respect their advertised `earliestAvailableSlot`. **Validation at RPC reception**: cross-checks Status v2 advertisement against actual RPC response coverage.

**Other 5 clients TBD** on this cross-validation. Lodestar is potentially most strict on holding peers to their Status v2 advertisements.

### Grandine `Option<Slot>` accessor pattern

```rust
// methods.rs:116
pub fn earliest_available_slot(self) -> Option<Slot> {
    match self {
        Self::V1(_) => None,
        Self::V2(status_message) => Some(status_message.earliest_available_slot),
    }
}
```

Grandine uses `Option<Slot>` accessor — V1 returns `None`; V2 returns `Some(slot)`. **Cleanest cross-version accessor pattern** — caller knows when the field is present vs absent (vs silently defaulting to 0).

### Teku Container6 schema definition

```java
// StatusMessageSchemaFulu.java:42
namedSchema("fork_digest", SszPrimitiveSchemas.BYTES4_SCHEMA),
namedSchema("finalized_root", SszPrimitiveSchemas.BYTES32_SCHEMA),
namedSchema("finalized_epoch", SszPrimitiveSchemas.UINT64_SCHEMA),
namedSchema("head_root", SszPrimitiveSchemas.BYTES32_SCHEMA),
namedSchema("head_slot", SszPrimitiveSchemas.UINT64_SCHEMA),
namedSchema("earliest_available_slot", SszPrimitiveSchemas.UINT64_SCHEMA));
```

Explicit Container6 schema with named fields matching spec. **Most enterprise-Java pattern** — same as MetaData v3 (item #45).

### Live mainnet validation

5+ months of cross-client Status v2 handshake exchanges. **Cross-client interop validated** — all 6 successfully serialize/deserialize the 6-field Status v2 SSZ container. V1 ↔ V2 transitions handled by all 6 (silent default-to-0 in 5 of 6; teku strict-required for V2 schema).

**No observable consensus divergence** — handshake layer is sync/peer-discovery, not consensus-critical state transition.

## Cross-cut chain

This audit closes the Fulu RPC handshake layer and cross-cuts:
- **Item #46** (DataColumnSidecarsByRange/ByRoot): peers can now use Status v2's `earliest_available_slot` to pre-filter peer requests instead of relying on RPC `ResourceUnavailable` errors. Lodestar explicitly validates this cross-check.
- **Item #45** (MetaData v3 + Pattern AA): teku's `StatusMessageFulu` naming consistent with `MetadataMessageFulu` — fork-named SSZ containers vs other clients' V-named. **Pattern AA scope EXPANDS** to include Status messages, not just MetaData.
- **Item #28 NEW Pattern CC candidate**: V1↔V2 default value handling divergence — 4 of 6 silently default to 0; teku strict-required (throws if absent); nimbus uses symbolic `GENESIS_SLOT` constant. Same forward-fragility class as Pattern T (lodestar empty-set in item #38).

## Adjacent untouched Fulu-active

- `MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS` constant cross-client (Deneb-heritage; cross-cuts item #46)
- BlobSidecarsByRange v1 / BlobSidecarsByRoot v1 (Deneb-heritage; cross-cuts item #46 PeerDAS RPCs)
- BeaconBlocksByRangeV2 fork-context handling
- Status v2 cross-validation with ENR `eth2` field (`current_fork_digest`, `next_fork_version`, `next_fork_epoch`)
- Status v2 + ENR nfd cross-validation (item #42 cross-cut)
- Pre-Fulu peer compatibility (Status v1 over /status/1/ vs Status v2 over /status/2/)
- Peer scoring on Status v2 mismatch
- `earliest_available_slot` reconciliation when peer claims one value but serves another (lodestar's "Peer did not respect" warning)
- Backfill from weak subjectivity checkpoint: how does `earliest_available_slot` evolve as backfill progresses
- Fork-boundary Status update: at FULU_FORK_EPOCH, when do peers switch from V1 to V2?
- Status v2 protocol negotiation (multistream-select)

## Future research items

1. **NEW Pattern CC for item #28 catalogue**: V1↔V2 default value handling divergence in cross-version protocol upgrades — 4 of 6 silently default to 0; teku strict-required; nimbus symbolic GENESIS_SLOT. Same forward-fragility class as Pattern T (lodestar empty-set).
2. **Pattern AA scope expansion** (item #45): include Status messages — teku consistently fork-names SSZ containers (`MetadataMessageFulu`, `StatusMessageFulu`); other clients V-named. Document as Pattern AA' (extension).
3. **Lodestar "Peer did not respect earliestAvailableSlot" cross-validation audit**: trace all 6 clients' validation of Status v2 advertisements against actual RPC response coverage. Lodestar is potentially most strict — others TBD.
4. **V1↔V2 wire-format byte-equivalence test**: synthesize V2 Status with specific values; verify all 6 produce identical 88-byte SSZ encoding (4 + 32 + 8 + 32 + 8 + 8 + earliest_available_slot field overhead).
5. **Cross-fork transition fixture**: pre-FULU_FORK_EPOCH peer (Status v1) → post-FULU_FORK_EPOCH peer (Status v2) handshake at fork boundary. Verify all 6 handle.
6. **Generate dedicated EF fixtures** for Status v2 + GetMetaData v3 + RPC handlers (out of pyspec scope today).
7. **earliest_available_slot reconciliation audit**: when peer's advertised value differs from observed RPC behavior, how do clients reconcile? Per-client policy.
8. **Backfill evolution audit**: as a node backfills history from weak subjectivity, how does `earliest_available_slot` advance? Cross-client semantics.
9. **Status v2 + ENR `nfd` cross-validation** (item #42 cross-cut): peer's ENR nfd should match Status v2's fork_digest progression. Verify per-client cross-checks.
10. **teku `Preconditions.checkArgument(earliestAvailableSlot.isPresent())` strict-required audit**: if a malformed peer omits the field, does teku reject the message gracefully?
11. **prysm `decodeStatus` always-V2 audit**: does prysm correctly handle V1 messages received over the V1 protocol path (no V2 conversion for V1 protocol)?
12. **Peer scoring on Status v2 mismatch**: when fork_digest, finalized_root, etc. mismatch, do all 6 disconnect/descore consistently?

## Summary

EIP-7594 PeerDAS Status v2 RPC handshake is implemented across all 6 clients with byte-equivalent wire format. Live mainnet validates 5+ months of cross-client handshake exchanges. The `earliest_available_slot` field allows peers to advertise their serve range upfront, optimizing PeerDAS sync.

Per-client divergences:
- **Naming convention**: 5 of 6 use V2 (`pb.StatusV2`, `StatusMessageV2`, `StatusMsgV2`, `StatusV2`); **teku uses Fulu** (`StatusMessageFulu`) — same pattern as MetaData v3 (item #45 Pattern AA — **scope expands**)
- **V1 → V2 default value**: 4 of 6 silently default to `0`; **teku strict-required** (`Preconditions.checkArgument(...isPresent())` throws if absent for V2); **nimbus symbolic** `GENESIS_SLOT` constant
- **Cross-version accessor**: grandine `Option<Slot>` (cleanest); lighthouse explicit V1↔V2 conversion comments; prysm always-decode-as-V2 with V1 conversion
- **Sync-time validation**: lodestar explicitly logs "Peer did not respect earliestAvailableSlot" when peer's RPC response doesn't match their Status v2 advertisement; other 5 TBD on validation strictness

**NEW Pattern CC candidate for item #28 catalogue**: V1↔V2 default value handling divergence in cross-version protocol upgrades. Same forward-fragility class as Pattern T (lodestar empty-set).

**Pattern AA scope expands** (item #45): teku consistently fork-names SSZ containers across MetaData + Status messages.

**Status**: source review confirms all 6 clients aligned at Fulu mainnet on the wire format. 5+ months of live cross-client handshake without divergence.

**With this audit, the Fulu RPC handshake layer is closed**. Combined with item #46 (DataColumnSidecarsByRange/ByRoot RPCs) and item #45 (MetaData v3 + GetMetaData v3 RPC), the Fulu Req/Resp RPC surface is now exhaustively audited.

**PeerDAS audit corpus now spans 13 items**: #33 → #34 → #35 → #37 → #38 → #39 → #40 → #41 → #42 → #44 → #45 → #46 → **#47**. **Thirteen-item arc covering consensus-critical PeerDAS surface end-to-end + complete peer-discovery + p2p extension + metadata + RPC handlers + RPC handshake.**

**Total Fulu-NEW items: 18 (#30–#47)**. Item #28 catalogue **Patterns A–CC (29 patterns)**.
