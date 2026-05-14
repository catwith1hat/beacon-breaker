---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [28, 34, 37, 40, 50]
eips: [EIP-7594]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 51: `blob_sidecar_{subnet_id}` gossip topic Fulu deprecation handling — Pattern GG gossip-layer deprecation cohort

## Summary

Spec deprecation (`vendor/consensus-specs/specs/fulu/p2p-interface.md:224-226`):

```
###### Deprecated `blob_sidecar_{subnet_id}`

`blob_sidecar_{subnet_id}` is deprecated.
```

Terse two-line spec — no transition period, no MUST/SHOULD/MAY guidance. Spec implicitly assumes clients won't subscribe at Fulu fork digest (each fork has a distinct topic string `/eth2/<fork_digest>/blob_sidecar_<subnet_id>/ssz_snappy`), but does not explicitly mandate unsubscribe behavior.

**Fulu surface (carried forward from 2026-05-04 audit):**

- **5 of 6 clients explicitly EXCLUDE Fulu fork digest from `blob_sidecar_{subnet_id}` subscription**:
  - prysm: `vendor/prysm/beacon-chain/sync/subscriber.go:307` epoch gate (`ElectraForkEpoch <= nse.Epoch && nse.Epoch < FuluForkEpoch`) with explicit comment.
  - lighthouse: `vendor/lighthouse/beacon_node/lighthouse_network/src/types/topics.rs:85-89 fork_name.deneb_enabled() && !fork_name.fulu_enabled()` boolean composition.
  - nimbus: `vendor/nimbus/beacon_chain/nimbus_beacon_node.nim:1738` dispatch table entry uses `addCapellaMessageHandlers` (skipping Deneb's blob_sidecar subscription), with comment at `:1473-1474 "Deliberately don't handle blobs, which Deneb and Electra contain, in lieu of columns. Last common ancestor fork for gossip environment is Capellla."` (typo preserved).
  - lodestar: `vendor/lodestar/packages/beacon-node/src/network/gossip/topic.ts:273 ForkSeq[fork] >= ForkSeq.deneb && ForkSeq[fork] < ForkSeq.fulu` ordinal-comparison gate.
  - grandine: `vendor/grandine/eth2_libp2p/src/types/topics.rs:86 current_phase >= Phase::Deneb && !current_phase.is_peerdas_activated()` PeerDAS-activation gate.

- **teku is the OUTLIER**: `vendor/teku/networking/eth2/src/main/java/tech/pegasys/teku/networking/eth2/gossip/topics/GossipTopics.java:110-116` calls `spec.forMilestone(specMilestone).getConfig().toVersionDeneb().ifPresent(config -> addBlobSidecarSubnetTopics(config.getBlobSidecarSubnetCount(), topics, forkDigest, gossipEncoding))`. Because `SpecConfigFuluImpl extends SpecConfigElectraImpl extends SpecConfigDenebImpl`, `toVersionDeneb()` returns `Optional.of(config)` for Fulu — meaning teku adds `blob_sidecar_{subnet_id}` topics at the Fulu fork digest. No explicit `fulu_enabled()` exclusion. Pattern GG outlier persists in the current checkout.

**Pattern GG** (item #28 catalogue candidate): gossip topic deprecation handling at fork transition. Sister to Pattern EE (item #50, RPC deprecation). Spec is silent on deprecation interpretation, leaving both compliant — but **teku is the only client that subscribes to the dead topic** at the Fulu fork digest.

**Inverted-defense cross-cut with item #50**: at the RPC layer, teku is the most defensive (item #50 finding: teku introduced `blobSidecarsDeprecationSlot()` checks for BOTH ByRange and ByRoot, and lighthouse later joined the cohort with explicit `fulu_start_slot` handling). At the gossip layer, **teku is the least defensive**: it subscribes to the deprecated topic while the other 5 explicitly exclude it. Same client, opposite stances at the two deprecation layers.

**Glamsterdam target (Gloas):** `vendor/consensus-specs/specs/gloas/p2p-interface.md` contains **NO `blob_sidecar` references** — `grep -n "blob_sidecar\|Deprecated\|deprecat" vendor/consensus-specs/specs/gloas/p2p-interface.md` returns 0 matches. The Fulu deprecation continues across the Gloas fork boundary; no Gloas-specific re-enablement or further modification. Each Gloas fork digest produces a distinct topic string; teku will continue to subscribe to `blob_sidecar_{subnet_id}` at the Gloas fork digest too (via the same `toVersionDeneb().ifPresent(...)` path; Gloas config also extends Deneb).

**Production impact today**: NONE. Topic strings include fork digest, isolating Fulu (and Gloas) fork digest topics from Electra. No client publishes BlobSidecars post-Fulu — all 6 use item #40's DataColumnSidecar construction path at FULU_FORK_EPOCH. Teku subscribes to a dead topic — wasted gossipsub heartbeats only.

**Forward-fragility concern**: a malicious peer publishing BlobSidecars at the Fulu fork digest would be received only by teku. Active interop divergence vector, currently unexploitable because no honest publisher produces such messages.

**Impact: none** — gossip-topic isolation by fork digest contains the divergence; no observable consensus split. Thirty-second `impact: none` result in the recheck series.

## Question

Pyspec defines the deprecation at `vendor/consensus-specs/specs/fulu/p2p-interface.md:224-226` with no transition guidance. Gloas spec adds nothing on this surface.

Two recheck questions:

1. **Per-client subscription strategy** — does the 5-vs-1 Pattern GG split persist, or has teku adopted explicit Fulu exclusion since the 2026-05-04 audit?
2. **Gloas inheritance** — does the Fulu deprecation carry forward across the Gloas fork boundary unchanged in all 6 clients?

## Hypotheses

- **H1.** Spec defines `blob_sidecar_{subnet_id}` as deprecated at Fulu (`fulu/p2p-interface.md:224-226`).
- **H2.** No transition period specified (unlike RPC deprecation in item #50 which had `FULU_FORK_EPOCH + MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS`).
- **H3.** 5 of 6 clients explicitly exclude Fulu from blob_sidecar subscription; teku is the OUTLIER.
- **H4.** Topic strings include fork digest (`/eth2/<fork_digest>/blob_sidecar_<subnet_id>/ssz_snappy`); per-fork-digest topic isolation contains the divergence.
- **H5.** No client publishes BlobSidecars post-Fulu (item #40 cross-cut — all 6 switch to DataColumnSidecar construction at FULU_FORK_EPOCH).
- **H6.** teku's anomalous subscription via `toVersionDeneb().ifPresent(...)` covers Fulu (and Gloas) because the Fulu/Gloas config classes extend Deneb config via class hierarchy.
- **H7.** Production impact: NONE today (no honest publisher; topic isolation).
- **H8.** Forward-fragility: malicious peer publishing at Fulu fork digest is received only by teku.
- **H9.** Defensive comments: nimbus has the most spec-faithful comment ("Deliberately don't handle blobs ... in lieu of columns. Last common ancestor fork for gossip environment is Capellla.").
- **H10.** *(Glamsterdam target — Gloas inherits Fulu deprecation)* `vendor/consensus-specs/specs/gloas/p2p-interface.md` contains NO modification of blob_sidecar topic. Deprecation continues across Gloas.
- **H11.** *(Glamsterdam target — teku Gloas behavior)* teku's `toVersionDeneb().ifPresent(...)` will also fire for Gloas fork digest (Gloas config extends Deneb), so teku subscribes at Gloas fork digest too.
- **H12.** Cross-layer inversion: item #50 shows teku is most defensive at RPC layer; item #51 shows teku is least defensive at gossip layer. Same client, opposite stance.

## Findings

H1 ✓. H2 ✓ (spec is terse). H3 ✓ (5-vs-1 split unchanged). H4 ✓. H5 ✓ (per item #40). H6 ✓ (class hierarchy: `SpecConfigFuluImpl extends SpecConfigElectraImpl extends SpecConfigDenebImpl`). H7 ✓ (no observable divergence). H8 ✓ (forward-fragility). H9 ✓. H10 ✓ (Gloas spec has 0 references). H11 ✓ (Gloas config also extends Deneb; teku's gate fires again at Gloas fork digest). H12 ✓ (item #50 + #51 inverse stance).

### prysm

Subscription gate (`vendor/prysm/beacon-chain/sync/subscriber.go:307`):

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

Explicit epoch-range gate: `ElectraForkEpoch <= nse.Epoch && nse.Epoch < FuluForkEpoch`. Comment `// New gossip topic in Electra, removed in Fulu` documents the deprecation. Separate subscription blocks for Deneb (lines ~291-304) and Electra (lines 307-319) — each gated to its specific window. **Most explicitly documented** of the 6.

Pattern GG cohort member: ✅ explicit exclude.

### lighthouse

Topic registration (`vendor/lighthouse/beacon_node/lighthouse_network/src/types/topics.rs:85-89`):

```rust
if fork_name.deneb_enabled() && !fork_name.fulu_enabled() {
    // All of deneb blob topics are core topics
    for i in 0..spec.blob_sidecar_subnet_count(fork_name) {
        topics.push(GossipKind::BlobSidecar(i));
    }
}
```

Followed by `if fork_name.fulu_enabled() { ... }` for the replacement `DataColumnSidecar` topics (line 92).

`fork_name.deneb_enabled()` returns true for Deneb/Electra/Fulu/Gloas; `!fork_name.fulu_enabled()` excludes Fulu+. Cleanest boolean-composition gate of the 6.

Pattern GG cohort member: ✅ explicit exclude.

### teku

Topic addition (`vendor/teku/networking/eth2/src/main/java/tech/pegasys/teku/networking/eth2/gossip/topics/GossipTopics.java:110-116`):

```java
spec.forMilestone(specMilestone)
    .getConfig()
    .toVersionDeneb()
    .ifPresent(
        config ->
            addBlobSidecarSubnetTopics(
                config.getBlobSidecarSubnetCount(), topics, forkDigest, gossipEncoding));
```

`toVersionDeneb()` returns `Optional.of(this)` for any config extending `SpecConfigDenebImpl` — which includes `SpecConfigElectraImpl`, `SpecConfigFuluImpl`, and `SpecConfigGloasImpl`. So `addBlobSidecarSubnetTopics()` IS called for Fulu fork digest AND Gloas fork digest. No `fulu_enabled()` exclusion.

Helper at `:147-154`:

```java
private static void addBlobSidecarSubnetTopics(
    final int blobSidecarSubnetCount,
    final Set<String> topics,
    final Bytes4 forkDigest,
    final GossipEncoding gossipEncoding) {
  for (int i = 0; i < blobSidecarSubnetCount; i++) {
    topics.add(getBlobSidecarSubnetTopic(forkDigest, i, gossipEncoding));
  }
}
```

`config.getBlobSidecarSubnetCount()` returns the Deneb-defined subnet count (6 on mainnet) — and teku adds 6 `blob_sidecar_{subnet_id}` topics at the Fulu fork digest. The corresponding `getAllDataColumnSidecarSubnetTopics(gossipEncoding, forkDigest, spec)` is also added at `:118`, so teku subscribes to BOTH the deprecated blob_sidecar topics AND the new data_column_sidecar topics at Fulu fork digest.

**Pattern GG outlier persists in current checkout.** No fix has been applied since the 2026-05-04 audit. Teku will continue subscribing to deprecated topics at Fulu fork digest AND at Gloas fork digest (since `SpecConfigGloasImpl` also extends Deneb via the class hierarchy).

**Cross-layer inversion with item #50**: at the RPC layer, teku is the most defensive (per item #50 recheck, teku introduced the `blobSidecarsDeprecationSlot()` check first; lighthouse joined the cohort in this recheck pass). At the gossip layer, teku is the least defensive — sole outlier. Same client, opposite stance at the two deprecation layers.

Pattern GG cohort member: ❌ NOT in the cohort (anomalous subscription).

### nimbus

Dispatch table (`vendor/nimbus/beacon_chain/nimbus_beacon_node.nim:1731-1740`):

```nim
const addMessageHandlers: array[ConsensusFork, auto] = [
  addPhase0MessageHandlers,
  addAltairMessageHandlers,
  addAltairMessageHandlers,  # bellatrix (altair handlers, different forkDigest)
  addCapellaMessageHandlers,
  addDenebMessageHandlers,
  addElectraMessageHandlers,
  addCapellaMessageHandlers, # no blobs; updateDataColumnSidecarHandlers for rest
  addGloasMessageHandlers
]
```

**Fulu entry is `addCapellaMessageHandlers`**, NOT `addDenebMessageHandlers`. Capella handlers don't include blob_sidecar subscription. Defense-in-depth via the dispatch table.

Comment at `:1472-1475`:

```nim
proc removeFuluMessageHandlers(node: BeaconNode, forkDigest: ForkDigest) =
  # Deliberately don't handle blobs, which Deneb and Electra contain, in lieu
  # of columns. Last common ancestor fork for gossip environment is Capellla.
  node.removeCapellaMessageHandlers(forkDigest)
```

**Most spec-faithful comment of all 6 clients** — explicitly documents WHY blob handlers are skipped at Fulu. Typo "Capellla" preserved from prior audit; opportunity for trivial docfix.

`removeGloasMessageHandlers` (`:1486-1490`) calls `removeFuluMessageHandlers` and additionally unsubscribes Gloas-NEW PBS topics (`getExecutionPayloadBidTopic`, `getExecutionPayloadTopic`, `getPayloadAttestationMessageTopic`). Gloas continues to skip blob_sidecar via the Capella-handler chain.

Pattern GG cohort member: ✅ explicit exclude (via dispatch table indirection + comment).

### lodestar

Topic registration (`vendor/lodestar/packages/beacon-node/src/network/gossip/topic.ts:267-277`):

```typescript
// After fulu also track data_column_sidecar_{index}
if (ForkSeq[fork] >= ForkSeq.fulu) {
    ...
}

// After Deneb and before Fulu also track blob_sidecar_{subnet_id}
if (ForkSeq[fork] >= ForkSeq.deneb && ForkSeq[fork] < ForkSeq.fulu) {
    ...
}
```

`ForkSeq` ordinal comparison: `>= ForkSeq.deneb && < ForkSeq.fulu`. Comment "After Deneb and before Fulu also track blob_sidecar_{subnet_id}" documents the intent.

Pattern GG cohort member: ✅ explicit exclude.

### grandine

Topic registration (`vendor/grandine/eth2_libp2p/src/types/topics.rs:86-90`):

```rust
if current_phase >= Phase::Deneb && !current_phase.is_peerdas_activated() {
    // blob_sidecar topics
}

if current_phase.is_peerdas_activated() {
    // data_column_sidecar topics
}
```

`is_peerdas_activated()` semantic helper (returns true for Fulu/Gloas) — most semantically meaningful of the 6. Reads cleanly: "subscribe to blob_sidecar if Deneb-or-later AND PeerDAS-not-yet-activated."

Pattern GG cohort member: ✅ explicit exclude.

## Cross-reference table

| Client | H3 subscription gate at Fulu | Source | H9 defensive comment | Pattern GG cohort |
|---|---|---|---|---|
| **prysm** | EXCLUDE — explicit `ElectraForkEpoch <= nse.Epoch && nse.Epoch < FuluForkEpoch` | `subscriber.go:307` | `// New gossip topic in Electra, removed in Fulu` — most explicit | ✅ in cohort |
| **lighthouse** | EXCLUDE — `fork_name.deneb_enabled() && !fork_name.fulu_enabled()` boolean composition | `topics.rs:85-89` | "All of deneb blob topics are core topics" | ✅ in cohort |
| **teku** | **INCLUDE (outlier)** — `toVersionDeneb().ifPresent(...)` fires for Fulu config because `SpecConfigFuluImpl extends SpecConfigDenebImpl`; same for Gloas | `GossipTopics.java:110-116` | NONE — no Fulu exclusion documented | ❌ NOT in cohort |
| **nimbus** | EXCLUDE — dispatch table entry at `:1738 addCapellaMessageHandlers` skips Deneb's blob handler | `nimbus_beacon_node.nim:1738`; comment at `:1473-1474` | **"Deliberately don't handle blobs, which Deneb and Electra contain, in lieu of columns. Last common ancestor fork for gossip environment is Capellla."** — most spec-faithful of all 6 | ✅ in cohort |
| **lodestar** | EXCLUDE — `ForkSeq[fork] >= ForkSeq.deneb && ForkSeq[fork] < ForkSeq.fulu` ordinal comparison | `topic.ts:273` | "After Deneb and before Fulu also track blob_sidecar_{subnet_id}" | ✅ in cohort |
| **grandine** | EXCLUDE — `current_phase >= Phase::Deneb && !current_phase.is_peerdas_activated()` PeerDAS-activation helper | `topics.rs:86-90` | (helper name is itself semantic) | ✅ in cohort |

**Pattern GG cohort**: 5/6 explicit exclude; teku 1/6 outlier (subscribes to deprecated topic at Fulu and Gloas fork digests). Unchanged from 2026-05-04 audit.

## Empirical tests

- ✅ **Live mainnet operation since 2025-12-03 (5+ months)**: no observable consensus divergence on this surface. Topic-per-fork-digest isolation contains teku's anomalous subscription. **Verifies H4, H5, H7 at production scale.**
- ✅ **Per-client subscription gate verification (this recheck)**: all 6 client gates confirmed via file:line citations above. Pattern GG cohort status unchanged from prior audit.
- ✅ **teku class-hierarchy verification**: `SpecConfigFuluImpl extends SpecConfigElectraImpl extends SpecConfigDenebImpl`, so `toVersionDeneb()` returns present for Fulu and Gloas configs. Verified via `vendor/teku/networking/eth2/src/main/java/tech/pegasys/teku/networking/eth2/gossip/topics/GossipTopics.java:110-116` + the class hierarchy. **Verifies H6 + H11.**
- ✅ **Gloas carry-forward verification**: `grep -n "blob_sidecar\|Deprecated\|deprecat" vendor/consensus-specs/specs/gloas/p2p-interface.md` returns 0 matches. **Verifies H10.**
- ⏭ **teku bug-fix PR**: file PR adding explicit Fulu exclusion to `GossipTopics.java:110-116` — for example, wrap the `toVersionDeneb().ifPresent(...)` call with an `if (!specMilestone.isGreaterThanOrEqualTo(SpecMilestone.FULU))` precondition. Aligns teku with the other 5 clients.
- ⏭ **Malicious-publisher fuzz**: craft a peer that publishes a valid-shape BlobSidecar message at the Fulu fork digest topic; verify teku is the only client that receives + validates. Quantify teku's gossip score / mesh impact.
- ⏭ **gossipsub MeshSize at Fulu fork digest**: profile teku's gossipsub overhead for the 6 anomalous blob_sidecar subscriptions at Fulu fork digest. Resource cost ≈ 6 subnets × MeshSize × heartbeat × no traffic.
- ⏭ **Cross-layer inversion test**: confirm teku's gossip-layer outlier status against item #50's RPC-layer leadership (teku and lighthouse cohort). Suggest combined PR to bring teku's gossip-layer behavior to parity.
- ⏭ **nimbus typo fix**: change "Capellla" → "Capella" at `vendor/nimbus/beacon_chain/nimbus_beacon_node.nim:1474`.
- ⏭ **Cross-client documentation audit**: nimbus has the most spec-faithful comment. Other 5 (especially teku once fixed) should adopt analogous documentation.
- ⏭ **Pattern EE + GG joint cross-cut**: track which clients are consistent across the two deprecation layers (RPC + gossip). Today teku is inverted (defensive on RPC, anomalous on gossip); lighthouse is consistent (defensive on both); prysm + nimbus + lodestar + grandine are consistent (implicit on RPC, defensive on gossip).

## Conclusion

The Fulu `blob_sidecar_{subnet_id}` gossip deprecation has spec at `vendor/consensus-specs/specs/fulu/p2p-interface.md:224-226` — terse two-line declaration with no transition guidance. Per-client subscription strategy splits 5-vs-1:

- **5 of 6 explicitly exclude Fulu fork digest** from blob_sidecar subscription (prysm epoch-range gate, lighthouse boolean composition, nimbus dispatch-table indirection + comment, lodestar ForkSeq comparison, grandine PeerDAS-activation helper).
- **teku subscribes anomalously** at Fulu fork digest via `toVersionDeneb().ifPresent(...)` in `GossipTopics.java:110-116` because `SpecConfigFuluImpl` extends `SpecConfigDenebImpl` via class hierarchy. No fix has been applied since the 2026-05-04 audit. The same path fires at Gloas fork digest (Gloas config also extends Deneb).

Pattern GG (item #28 catalogue candidate): gossip topic deprecation handling at fork transition. Sister to Pattern EE (item #50, RPC deprecation). Spec is silent on deprecation interpretation, leaving both technically compliant — but teku is the only client carrying the anomalous subscription.

**Cross-layer inversion with item #50**: at the RPC layer, teku is the most defensive (introduced `blobSidecarsDeprecationSlot()` checks first, now consistent across ByRange + ByRoot; lighthouse joined the cohort in the 2026-05-13 recheck pass). At the gossip layer, **teku is the least defensive** — sole outlier. Same client, opposite stance at the two deprecation layers. Lighthouse is consistent (defensive at both); prysm + nimbus + lodestar + grandine are consistent (implicit on RPC, defensive on gossip).

**Glamsterdam target context**: `vendor/consensus-specs/specs/gloas/p2p-interface.md` contains NO `blob_sidecar` references — verified by grep. The Fulu deprecation continues across the Gloas fork boundary unchanged. Each Gloas fork digest produces a distinct topic string; teku continues subscribing to `blob_sidecar_{subnet_id}` at the Gloas fork digest via the same class-hierarchy path. The other 5 clients continue to explicitly exclude both Fulu and Gloas fork digests.

**Production impact today**: NONE. Topic strings include fork digest, isolating Fulu and Gloas fork digest topics from Electra. No client publishes BlobSidecars post-Fulu (item #40 cross-cut). Teku subscribes to a dead topic — wasted gossipsub heartbeats only.

**Forward-fragility concern**: a malicious peer publishing valid-shape BlobSidecars at the Fulu (or Gloas) fork digest would be received only by teku. Active interop divergence vector, currently unexploitable because no honest publisher produces such messages.

**Impact: none** — gossip-topic isolation by fork digest contains the divergence; no observable consensus split. Thirty-second `impact: none` result in the recheck series.

Forward-research priorities:

1. **Teku bug-fix PR** — add explicit Fulu exclusion to `GossipTopics.java:110-116`. Wrap the `toVersionDeneb().ifPresent(...)` call with a `!specMilestone.isGreaterThanOrEqualTo(SpecMilestone.FULU)` precondition. Aligns teku with the other 5 clients and closes the active interop divergence vector.
2. **Pattern EE + GG joint cohort analysis** — track which clients are consistent across the two deprecation layers (RPC item #50 + gossip item #51). Currently teku is inverted; lighthouse is consistent (defensive at both); other 4 are consistent (implicit at RPC, defensive at gossip).
3. **nimbus typo fix** — `"Capellla"` → `"Capella"` at `vendor/nimbus/beacon_chain/nimbus_beacon_node.nim:1474`.
4. **Future heritage-deprecation audits** — Status v1 (`/status/1/`), MetaData v2 (`/metadata/2/`), BeaconBlocksByRange v1, BeaconBlocksByRoot v1. Pattern EE and GG family extends naturally.
5. **Cross-client documentation audit** — nimbus has the most spec-faithful deprecation comment. Other 5 should adopt analogous documentation.
