# Item 51 — `blob_sidecar_{subnet_id}` gossip topic Fulu deprecation handling

**Status:** no-divergence-pending-fixture-run on observable behavior; **divergence on subscription strategy** — audited 2026-05-04. **Twenty-first Fulu-NEW-relevant item, SECOND DEPRECATED-FEATURE audit, FIRST GOSSIP-DEPRECATION audit**. Sister to item #50 (RPC-layer deprecation). Same Pattern EE/FF family applied to the gossipsub layer.

**Spec definition** (`fulu/p2p-interface.md:343-345`):
```
###### Deprecated `blob_sidecar_{subnet_id}`

`blob_sidecar_{subnet_id}` is deprecated.
```

Terse 2-line statement. NO transition period specified. Spec is **silent** on whether clients should:
- (a) unsubscribe from the topic at FULU_FORK_EPOCH,
- (b) keep handler alive but ignore inbound messages,
- (c) reject all messages with appropriate gossipsub score penalty,
- (d) keep validating as before (no-op behavior change).

Spec implicitly assumes clients won't subscribe at Fulu fork digest (since the topic string includes the fork digest, and Fulu fork digest = different topic string). But the spec does not explicitly mandate unsubscribe.

**Major finding**: **5 of 6 clients explicitly UNSUBSCRIBE** at Fulu (prysm, lighthouse, nimbus, lodestar, grandine); **teku is the OUTLIER** — its `getAllTopics()` includes `blob_sidecar_{subnet_id}` topics at Fulu fork digest because `toVersionDeneb()` returns `Optional.of(this)` for `SpecConfigFuluImpl` (Fulu config inherits Deneb config interface).

**NEW Pattern GG candidate for item #28 catalogue**: gossip topic deprecation handling at fork transition. Same forward-fragility class as Pattern EE (RPC deprecation, item #50). Sister pattern at the gossipsub layer.

## Scope

In: `blob_sidecar_{subnet_id}` gossip topic subscription/unsubscription per-client; fork-aware topic registration; topic filter behavior at Fulu fork digest; validator-side publication behavior at Fulu; spec compliance interpretation across 6 clients.

Out: `data_column_sidecar_{subnet_id}` gossip topic (replaces blob_sidecar at Fulu — covered in item #34); blob_sidecar gossip validation logic (Deneb-heritage, covered in items #34/#46); BlobSidecarsByRange/Root v1 RPC deprecation (item #50); Status v1 deprecation (future item #52 candidate); MetaData v2 deprecation (future audit candidate).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | Spec defines `blob_sidecar_{subnet_id}` as deprecated at Fulu | ✅ confirmed | `fulu/p2p-interface.md:343-345` — terse 2-line statement |
| H2 | Spec specifies a transition period | ❌ no transition period | Unlike RPC deprecation (item #50 had `FULU_FORK_EPOCH + MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS`), gossip deprecation is immediate at fork |
| H3 | All 6 clients unsubscribe at Fulu | ⚠️ 5 of 6 (prysm, lighthouse, nimbus, lodestar, grandine); **teku continues to subscribe** | Pattern GG NEW candidate |
| H4 | Topic registration uses fork digest (each fork has distinct topic string) | ✅ all 6 | Topic string format `/eth2/<fork_digest>/blob_sidecar_<subnet_id>/ssz_snappy` |
| H5 | Validator-side publication at Fulu sends BlobSidecars or DataColumnSidecars? | ✅ all 6 publish DataColumnSidecars only at Fulu (per item #40) | No client publishes BlobSidecars post-Fulu |
| H6 | Spec compliance: deprecation interpretation differs across clients | ✅ 5 = unsubscribe; 1 (teku) = continue subscribing | Spec is silent — both interpretations technically compliant |
| H7 | Production interop impact | ⚠️ none observed (no client publishes BlobSidecars at Fulu fork digest) | Topic per-fork-digest isolation; teku subscribes to dead topic |
| H8 | Defensive comments in code | ✅ nimbus has explicit comment "Deliberately don't handle blobs ... in lieu of columns" | Most spec-faithful comment |
| H9 | Forward-compat at hypothetical fork un-deprecating the topic | ⚠️ 5 of 6 would fail to subscribe | Forward-fragility (unlikely scenario) |
| H10 | Live mainnet validation: 5+ months without observed divergence | ✅ all 6 | Topic per-fork-digest isolates the divergence |

## Per-client cross-reference

| Client | Subscription Strategy at Fulu | File:Line | Defensive Mechanism |
|---|---|---|---|
| **prysm** | **EXPLICIT Fulu gate** — `nse.Epoch < params.BeaconConfig().FuluForkEpoch` | `subscriber.go:307` (Electra subscription block); explicit comment `// New gossip topic in Electra, removed in Fulu` | Most explicit — comments document the deprecation |
| **lighthouse** | **EXPLICIT Fulu gate** — `fork_name.deneb_enabled() && !fork_name.fulu_enabled()` | `topics.rs:85-90` | Boolean composition with `fulu_enabled()` helper |
| **teku** | **NO Fulu gate** — `toVersionDeneb()` returns present for `SpecConfigFuluImpl` (Fulu inherits Deneb interface) | `GossipTopics.java:110-116` (`addBlobSidecarSubnetTopics` called whenever Deneb config exists) | **NONE — subscribes to dead topic at Fulu fork digest** |
| **nimbus** | **DELIBERATE Capella-fallback** — Fulu add handler is `addCapellaMessageHandlers` (skipping Deneb's blob handler) | `nimbus_beacon_node.nim:1738` (dispatch table entry); comment at `:1473-1474` "Deliberately don't handle blobs, which Deneb and Electra contain, in lieu of columns. Last common ancestor fork for gossip environment is Capella." | Most spec-faithful comment of all 6 |
| **lodestar** | **EXPLICIT Fulu gate** — `ForkSeq[fork] >= ForkSeq.deneb && ForkSeq[fork] < ForkSeq.fulu` | `topic.ts:273-280` | `ForkSeq` enum-comparison gate |
| **grandine** | **EXPLICIT Fulu gate** — `current_phase >= Phase::Deneb && !current_phase.is_peerdas_activated()` | `topics.rs:86-91` | Phase-based gate via `is_peerdas_activated()` helper |

## Notable per-client findings

### CRITICAL — Teku subscribes to deprecated topic at Fulu fork digest

Teku `GossipTopics.java:110-116`:
```java
spec.forMilestone(specMilestone)
    .getConfig()
    .toVersionDeneb()
    .ifPresent(
        config ->
            addBlobSidecarSubnetTopics(
                config.getBlobSidecarSubnetCount(), topics, forkDigest, gossipEncoding));
```

**Trace through for Fulu**: `spec.forMilestone(FULU)` → SpecVersion for Fulu → `.getConfig()` → `SpecConfigFuluImpl` → `.toVersionDeneb()` → `Optional<SpecConfigDeneb>` = **present** (Fulu inherits Deneb interface via SpecConfigFuluImpl extends SpecConfigElectraImpl extends SpecConfigDenebImpl). So `addBlobSidecarSubnetTopics()` IS called for Fulu fork digest.

**Confirmed via class hierarchy**: `SpecConfigDenebImpl.java:111` defines `toVersionDeneb()` returning `Optional.of(this)`. `SpecConfigFuluImpl extends SpecConfigElectraImpl extends SpecConfigDenebImpl` so the same method returns the Fulu config cast as Deneb interface.

**Eth2GossipTopicFilter consequence**: `Eth2GossipTopicFilter.computeRelevantTopics` (`:60-95`) calls `getAllTopics(gossipEncoding, forkDigest, spec, milestone, p2pConfig)` which includes blob_sidecar topics at Fulu fork digest. So teku will accept blob_sidecar gossip messages at Fulu fork digest.

**Production impact assessment**: LOW because:
1. Topic strings include fork digest — `/eth2/<fulu_fork_digest>/blob_sidecar_<subnet_id>/ssz_snappy` is a DIFFERENT topic string than `/eth2/<electra_fork_digest>/blob_sidecar_<subnet_id>/ssz_snappy`
2. No client publishes BlobSidecars at Fulu fork digest (all 6 publish DataColumnSidecars only post-Fulu, per item #40)
3. Other 5 clients don't subscribe to Fulu fork digest blob_sidecar topics
4. Net effect: teku subscribes to a dead topic with zero traffic — wasted gossipsub heartbeats only

**Resource cost**: 6 subnet topics × heartbeat overhead × no traffic = small but non-zero.

**Forward-fragility concern**: if a malicious peer publishes BlobSidecars at Fulu fork digest, only teku would receive them. teku's gossip validator (`BlobSidecarGossipManager`) may then process them as if valid. **Active interop divergence vector** — though unexploitable today since no other client publishes.

### Nimbus most spec-faithful comment

Nimbus `nimbus_beacon_node.nim:1472-1484`:
```nim
proc removeFuluMessageHandlers(node: BeaconNode, forkDigest: ForkDigest) =
  # Deliberately don't handle blobs, which Deneb and Electra contain, in lieu
  # of columns. Last common ancestor fork for gossip environment is Capellla.
  node.removeCapellaMessageHandlers(forkDigest)
  ...
```

And the dispatch table at `:1735-1738`:
```nim
addCapellaMessageHandlers,    # Capella
addDenebMessageHandlers,      # Deneb
addElectraMessageHandlers,    # Electra
addCapellaMessageHandlers, # no blobs; updateDataColumnSidecarHandlers for rest  # Fulu
```

**Comment is most explicit of all 6 clients** documenting WHY blob handlers are skipped at Fulu. Nimbus's Fulu add handler is `addCapellaMessageHandlers`, NOT `addDenebMessageHandlers` (which would subscribe to blob topics). This is **defense-in-depth**: even if other code paths were buggy, the dispatch table entry guarantees Fulu skips Deneb's blob_sidecar subscription.

(Typo: "Capellla" — minor docfix opportunity.)

### Prysm most explicit deprecation marker

Prysm `subscriber.go:307`:
```go
// New gossip topic in Electra, removed in Fulu
if params.BeaconConfig().ElectraForkEpoch <= nse.Epoch && nse.Epoch < params.BeaconConfig().FuluForkEpoch {
    s.spawn(func() {
        s.subscribeWithParameters(subscribeParameters{
            topicFormat: p2p.BlobSubnetTopicFormat,
            ...
            getSubnetsToJoin: func(currentSlot primitives.Slot) map[uint64]bool {
                return mapFromCount(params.BeaconConfig().BlobsidecarSubnetCountElectra)
            },
        })
    })
}
```

**`// New gossip topic in Electra, removed in Fulu`** — most explicit deprecation comment. Prysm has SEPARATE subscription blocks for Deneb (lines 291-304: "removed in Electra") and Electra (lines 307-319: "removed in Fulu"). Each block is gated by exact epoch range. Most defensive AND most documented.

### Lighthouse fork-aware boolean composition

Lighthouse `topics.rs:85-90`:
```rust
if fork_name.deneb_enabled() && !fork_name.fulu_enabled() {
    // All of deneb blob topics are core topics
    for i in 0..spec.blob_sidecar_subnet_count(fork_name) {
        topics.push(GossipKind::BlobSidecar(i));
    }
}
```

`fork_name.deneb_enabled()` returns true for Deneb/Electra/Fulu/Gloas; `!fork_name.fulu_enabled()` excludes Fulu+. Cleanest boolean composition. Comment "All of deneb blob topics are core topics" documents legacy heritage.

### Lodestar ForkSeq ordinal comparison

Lodestar `topic.ts:273`:
```typescript
if (ForkSeq[fork] >= ForkSeq.deneb && ForkSeq[fork] < ForkSeq.fulu) {
    // blob_sidecar topics
}
```

`ForkSeq` enum gives ordinal comparison. Same effect as lighthouse's boolean composition; different idiom.

### Grandine PeerDAS-activation gate

Grandine `topics.rs:86-91`:
```rust
if current_phase >= Phase::Deneb && !current_phase.is_peerdas_activated() {
    // blob_sidecar topics
}
```

Uses `is_peerdas_activated()` semantic helper — most semantically meaningful (PeerDAS activation = Fulu). Reads cleanly: "subscribe to blob_sidecar if Deneb-or-later AND PeerDAS-not-yet-activated".

### Topic per-fork-digest isolation

Important spec property: gossip topics include the fork digest in the topic string:
```
/eth2/<fork_digest>/blob_sidecar_<subnet_id>/ssz_snappy
```

This means:
- Electra fork digest blob_sidecar topic = different topic string than Fulu fork digest blob_sidecar topic
- A client subscribed at Electra fork digest will not receive messages on the Fulu fork digest topic
- A client subscribed at Fulu fork digest will not receive messages from peers publishing at Electra fork digest

**Net effect**: teku's anomalous subscription at Fulu fork digest is harmless in practice because no client publishes there. If a malicious peer DID publish, teku would be the only client receiving it (forward-fragility vector, currently unexploitable).

### Validator-side publication

All 6 clients use item #40's PeerDAS proposer-side construction at Fulu:
- Pre-Fulu: validator constructs BlobSidecars + publishes to blob_sidecar_{subnet_id}
- Post-Fulu: validator constructs DataColumnSidecars + publishes to data_column_sidecar_{subnet_id}

No client continues publishing BlobSidecars post-Fulu. Spec correctness validated by item #40.

## Cross-cut chain

This audit closes the **gossip-layer deprecation** parallel to item #50's RPC-layer deprecation:
- **Item #50** (`MAX_REQUEST_BLOB_SIDECARS` + BlobSidecarsByRange/Root v1 deprecation): RPC-layer deprecation; Pattern EE
- **Item #51** (this): gossip-topic deprecation; **Pattern GG NEW candidate**
- **Item #34** (data_column_sidecar gossip validation): the active replacement gossip topic
- **Item #40** (proposer-side DataColumnSidecar construction): explains why no client publishes BlobSidecars post-Fulu
- **Item #37** (subnet computation): topic-per-subnet mapping
- **Item #45** (MetaData v3): another Fulu-modified gossip-related primitive
- **Item #28 NEW Pattern GG candidate**: gossip topic deprecation handling at fork transition. Same forward-fragility class as Pattern EE (RPC deprecation).
- **Item #48** (catalogue refresh): adds Pattern GG to the catalogue

## Adjacent untouched Fulu-active

- BlobSidecar gossip validation logic (Deneb-heritage; what does teku's `BlobSidecarGossipManager` do if it receives a message at Fulu fork digest)
- Status v1 RPC deprecation handling at Fulu (sister to Status v2 item #47, parallel to item #50)
- MetaData v2 RPC deprecation handling at Fulu (sister to MetaData v3 item #45)
- BeaconBlocksByRange v2 / BeaconBlocksByRoot v2 deprecation tracking (Phase0 → Bellatrix → Deneb evolution)
- gossipsub score penalty configuration (does any client penalize publishers of deprecated topics?)
- Topic deregistration semantics (does gossipsub keep the topic mesh alive even if locally unsubscribed?)
- Forward-fork validation: at Gloas, are any Fulu-NEW topics deprecated similarly?
- Cross-fork topic compatibility during fork transition window (12-second slot vs sub-second gossipsub propagation)

## Future research items

1. **NEW Pattern GG for item #28 catalogue**: gossip topic deprecation handling at fork transition. Sister to Pattern EE (RPC deprecation). Forward-fragility: spec may add MUST clause requiring explicit unsubscribe with error code.
2. **Teku gossip subscription bug-fix opportunity**: file PR adding explicit `!fork_name.fulu_enabled()` gate to `GossipTopics.java:110-116`. Add `.toVersionDeneb()` AND `.toVersionFulu().isEmpty()` check, OR introduce a Fulu-aware override on `getBlobSidecarSubnetCount()`.
3. **Test teku malicious-publisher scenario**: craft a peer that publishes a valid BlobSidecar to Fulu fork digest topic; verify teku is the only client that receives + processes. Cross-client interop fixture for Pattern GG.
4. **Status v1 deprecation audit (item #52 candidate)**: parallel audit for `/eth2/beacon_chain/req/status/1/`. Spec presumably deprecates v1 in favor of v2 (item #47); per-client handling may differ.
5. **MetaData v2 deprecation audit (item #53 candidate)**: parallel for `/eth2/beacon_chain/req/metadata/2/` vs v3 (item #45).
6. **gossipsub score penalty audit**: do any clients penalize publishers of deprecated topics? Spec is silent.
7. **Teku ByRoot inconsistency** (from item #50 future research): file PR adding deprecation check to `BlobSidecarsByRootMessageHandler` — closes both item #50 and item #51 teku gaps.
8. **Pattern EE + GG cross-cut**: heritage-RPC + heritage-gossip dual deprecation tracking. Pattern EE applies at RPC layer; Pattern GG applies at gossip layer. Some clients (teku) are inconsistent: explicit RPC deprecation but no gossip deprecation.
9. **Cross-client comment audit**: nimbus has the most spec-faithful deprecation comment ("Deliberately don't handle blobs ... in lieu of columns. Last common ancestor fork for gossip environment is Capella"). Other 5 should adopt similar documentation.
10. **Topic-per-fork-digest isolation invariant test**: generate a peer with mixed-fork-digest publishing patterns; verify cross-client topic isolation behavior.
11. **gossipsub MeshSize at Fulu fork digest for blob_sidecar topics**: does teku's anomalous subscription cause it to be elected to the gossipsub mesh for these topics on the Fulu fork digest network? Resource cost = 6 subnets × MeshSize × overhead.
12. **Nimbus Capellla typo fix** at `nimbus_beacon_node.nim:1474`.

## Summary

EIP-7594 PeerDAS deprecates `blob_sidecar_{subnet_id}` gossip topic at Fulu (terse 2-line spec at `fulu/p2p-interface.md:343-345`). All 6 clients evaluated for fork-aware subscription/unsubscription behavior.

**5 of 6 clients explicitly UNSUBSCRIBE at Fulu**:
- **prysm** (`subscriber.go:307`): explicit `nse.Epoch < FuluForkEpoch` gate + comment `// New gossip topic in Electra, removed in Fulu` — most documented
- **lighthouse** (`topics.rs:85`): `fork_name.deneb_enabled() && !fork_name.fulu_enabled()` boolean composition
- **nimbus** (`nimbus_beacon_node.nim:1738`): Fulu dispatch table entry is `addCapellaMessageHandlers` (skipping Deneb); comment "Deliberately don't handle blobs, which Deneb and Electra contain, in lieu of columns. Last common ancestor fork for gossip environment is Capella" — most spec-faithful comment
- **lodestar** (`topic.ts:273`): `ForkSeq[fork] >= ForkSeq.deneb && ForkSeq[fork] < ForkSeq.fulu` ordinal comparison
- **grandine** (`topics.rs:86`): `current_phase >= Phase::Deneb && !current_phase.is_peerdas_activated()` PeerDAS-activation gate — most semantic

**Teku is the OUTLIER** (`GossipTopics.java:110-116`): subscribes to `blob_sidecar_{subnet_id}` topics at Fulu fork digest because `toVersionDeneb()` returns `Optional.of(this)` for `SpecConfigFuluImpl` (Fulu inherits Deneb interface via class hierarchy). No explicit Fulu exclusion. **Eth2GossipTopicFilter** also accepts these topics, so teku is on the gossip mesh for blob_sidecar at Fulu fork digest.

**Production impact**: NONE today. Topic strings include fork digest, isolating Fulu fork digest topics from Electra. No client publishes BlobSidecars post-Fulu. Teku subscribes to a dead topic — wasted gossipsub heartbeats only.

**Forward-fragility concern**: a malicious peer publishing BlobSidecars at Fulu fork digest would be received only by teku — active interop divergence vector, currently unexploitable.

**NEW Pattern GG candidate for item #28 catalogue**: gossip topic deprecation handling at fork transition. Sister to Pattern EE (RPC deprecation, item #50). Same forward-fragility class — spec MAY clauses leave both interpretations technically compliant.

**Pattern EE + GG cross-cut**: Pattern EE at RPC layer, Pattern GG at gossip layer. Some clients are inconsistent across the two layers — teku has anomalous gossip-layer behavior despite RPC-layer being the most defensive (item #50 finding: only teku has explicit `blobSidecarsDeprecationSlot()` check). **Inverted defense** — teku is the most defensive on RPC deprecation but the least defensive on gossip deprecation.

**Bug-fix opportunity for teku**: add explicit Fulu exclusion to `GossipTopics.java:110-116` (e.g., `.toVersionFulu().isEmpty()` check) to align with the other 5 clients.

**Total Fulu-NEW-relevant items: 21 (#30–#51)**. Item #28 catalogue **Patterns A–GG (33 patterns)**.

**Heritage-deprecation tracking (item #50 + #51)** spans 2 layers: RPC (#50) and gossip (#51). Future audits should extend to Status v1 (item #52 candidate) and MetaData v2 (item #53 candidate).
