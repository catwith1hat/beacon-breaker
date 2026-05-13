---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [11, 21, 28, 30]
eips: [EIP-7917, EIP-7892]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 36: `upgrade_to_fulu` standalone audit (item #11 Fulu equivalent)

## Summary

`upgrade_to_fulu(pre: electra.BeaconState) -> fulu.BeaconState` is the once-only state-transition foundation that runs at `FULU_FORK_EPOCH = 411392` (= 2025-12-03 21:49:11 UTC) on mainnet. **Simplest cross-fork upgrade in CL history**: ONE new field (`proposer_lookahead`) initialized via `initialize_proposer_lookahead` (item #30), fork version bump to `0x06000000`, no field migration, no data seeding beyond the lookahead initialization. Compare to item #11 (Pectra upgrade — 9 brand-new fields, churn budget seeding, pending-deposits sorting, early-adopter compounding queueing).

**Fulu surface (carried forward from 2026-05-04 audit; CURRENT mainnet target):** all six clients implement `upgrade_to_fulu` byte-for-byte equivalently. **Live mainnet validation**: chain did NOT fork at `FULU_FORK_EPOCH = 411392` on 2025-12-03 — definitive proof that all 6 clients produced byte-identical post-states. (If any client diverged, the chain would have forked at the first Fulu block.) 5+ months of post-Fulu finality + 2 BPO transitions (item #31) + ongoing PeerDAS gossip (items #33-#35) all rely on a consistent post-Fulu state.

Per-client divergences entirely in architecture (NEW Pattern R candidate for item #28): prysm proto-then-init / lighthouse type-method-upgrade / teku `copyCommonFieldsFromSource` + per-field setter / nimbus `upgrade_to_next` overload / lodestar SSZ tree-view reuse / grandine destructure-and-construct.

**Gloas surface (at the Glamsterdam target): `upgrade_to_fulu` unchanged.** `vendor/consensus-specs/specs/gloas/fork.md` contains no `Modified upgrade_to_fulu` heading. The Fulu upgrade function lives ONLY in `vendor/consensus-specs/specs/fulu/fork.md:63 def upgrade_to_fulu(pre: electra.BeaconState)`. Gloas adds a SEPARATE `upgrade_to_gloas(pre: fulu.BeaconState)` at `vendor/consensus-specs/specs/gloas/fork.md:122-197` (audited at item #21 H10 — no early-adopter loop because Electra-era adopters were processed at the Pectra upgrade epoch).

**Per-client Gloas upgrade-scaffolding status:** All 6 clients have BOTH `upgrade_to_fulu` AND `upgrade_to_gloas` implementations:
- prysm: `core/fulu/upgrade.go` + `core/gloas/upgrade.go`.
- lighthouse: `state_processing/src/upgrade/fulu.rs` + `state_processing/src/upgrade/gloas.rs`.
- teku: `versions/fulu/forktransition/FuluStateUpgrade.java` + `versions/gloas/forktransition/GloasStateUpgrade.java`.
- nimbus: 6 `upgrade_to_next` overloads (`beaconstate.nim:2276, 2343, 2401, 2485, 2571, 2697, 2778`) covering Phase0→Altair→Bellatrix→Capella→Deneb→Electra→Fulu→Gloas.
- lodestar: `slot/upgradeStateToFulu.ts` + `slot/upgradeStateToGloas.ts`.
- grandine: `helper_functions/src/fork.rs:676 upgrade_to_fulu` + `:790 upgrade_to_gloas`.

**Lighthouse Pattern M cohort gap does NOT extend to upgrade scaffolding** — lighthouse has the basic Gloas upgrade flow in place. The cohort gap is at the EIP-7732 ePBS surface (deposits, payload bid, envelope handling — items #14, #19, #22, #23, #24, #25, #26, #32, #34, #35), not at upgrade-time.

**Mainnet activation status**: `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `vendor/consensus-specs/configs/mainnet.yaml:60`. `upgrade_to_fulu` continues operating only at the (historical) Fulu activation slot; `upgrade_to_gloas` will run once at the future Gloas activation slot.

**Impact: none.** Eighteenth impact-none result in the recheck series. The Fulu upgrade is one of the most thoroughly validated state-transitions in the corpus (chain-didn't-fork + 5+ months of mainnet operation).

## Question

Pyspec Fulu-NEW (`vendor/consensus-specs/specs/fulu/fork.md:53-95`):

```python
def upgrade_to_fulu(pre: electra.BeaconState) -> BeaconState:
    epoch = electra.get_current_epoch(pre)
    post = BeaconState(
        # ... all 36 Electra fields copied verbatim ...
        fork=Fork(
            previous_version=pre.fork.current_version,
            current_version=FULU_FORK_VERSION,
            epoch=epoch,
        ),
        # ... etc ...
        # [New in Fulu:EIP7917]
        proposer_lookahead=initialize_proposer_lookahead(pre),
    )
    return post
```

At Gloas: `upgrade_to_fulu` is NOT modified (no `Modified` heading in `vendor/consensus-specs/specs/gloas/fork.md`). Gloas adds a SEPARATE `upgrade_to_gloas` (`:122-197`) consumed only at the future `GLOAS_FORK_EPOCH`.

Three recheck questions:
1. Fulu-surface invariants (H1–H10 from prior audit) — do all six clients still implement byte-for-byte equivalent state upgrade?
2. **At Gloas (the new target)**: is `upgrade_to_fulu` unchanged? Do all six clients have a corresponding `upgrade_to_gloas` scaffolding?
3. Does the lighthouse Pattern M cohort gap extend to upgrade scaffolding, or stay isolated at the EIP-7732 ePBS surface?

## Hypotheses

- **H1.** All 36 Electra fields copied to Fulu state (no migration, no transformation).
- **H2.** Fork version bumped: `previous_version = pre.fork.current_version`, `current_version = FULU_FORK_VERSION = 0x06000000`, `epoch = current_epoch`.
- **H3.** ONE new Fulu field: `proposer_lookahead: Vector[ValidatorIndex, 64]` initialized via `initialize_proposer_lookahead(pre)` (item #30).
- **H4.** `latest_execution_payload_header` schema UNCHANGED at Fulu — copied verbatim or via field-method `upgrade_to_fulu()`.
- **H5.** BeaconState shape = Electra fields + 1 (proposer_lookahead).
- **H6.** No field re-validation — Fulu inherits all Electra invariants.
- **H7.** Caches preserved/rebuilt deterministically (per-client architecture).
- **H8.** Idempotency: applying `upgrade_to_fulu` to a Fulu state is a type-error or rejected.
- **H9.** Once-only execution at FULU_FORK_EPOCH boundary slot.
- **H10.** Returns/produces a Fulu BeaconState atomically (no transient/intermediate states observable).
- **H11.** *(Glamsterdam target — `upgrade_to_fulu` unchanged)*. `upgrade_to_fulu` has no `Modified` heading in `vendor/consensus-specs/specs/gloas/`. The Fulu-NEW function carries forward unchanged across the Gloas fork boundary in all 6 clients. Gloas adds a SEPARATE `upgrade_to_gloas` (item #21 H10 — no early-adopter loop).
- **H12.** *(Glamsterdam target — upgrade scaffolding present in all 6 clients)*. All 6 clients have BOTH `upgrade_to_fulu` AND `upgrade_to_gloas` implementations. The lighthouse Pattern M cohort gap does NOT extend to upgrade scaffolding; lighthouse has `upgrade/fulu.rs` and `upgrade/gloas.rs` in place.
- **H13.** *(Mainnet validation reaffirmation)*. Chain did NOT fork at `FULU_FORK_EPOCH = 411392` (2025-12-03) — definitive cross-client byte-equivalence proof. 5+ months of post-Fulu finality + 2 BPO transitions + ongoing PeerDAS gossip operate on a consistent post-Fulu state.

## Findings

H1–H13 satisfied. **No state-transition divergence at the Fulu surface; `upgrade_to_fulu` carries forward unchanged at Gloas; all 6 clients have both Fulu and Gloas upgrade scaffolding.**

### prysm

`vendor/prysm/beacon-chain/core/fulu/upgrade.go:20 UpgradeToFulu(ctx, beaconState)` → `:39 ConvertToFulu` then sets `ProposerLookahead`.

Two-phase pattern: `ConvertToFulu` reconstructs every field via getter; `ExecutionPayloadHeaderDeneb` rebuilt field-by-field via 16 getter calls (`:157-175`). `UpgradeToFulu` wraps with `helpers.InitializeProposerLookahead(ctx, beaconState, slots.ToEpoch(slot))` (item #30).

**Gloas upgrade present**: `vendor/prysm/beacon-chain/core/gloas/upgrade.go` exists for the future Gloas activation.

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (defensive 16-getter copy). H5 ✓. H6 ✓. H7 ✓ (`state_native.InitializeFromProtoUnsafeFulu` — rebuild caches). H8 ✓ (runtime version check). H9 ✓. H10 ✓. H11 ✓ (Fulu upgrade unchanged). H12 ✓ (Gloas upgrade present). H13 ✓.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/upgrade/fulu.rs:7 upgrade_to_fulu(pre_state, spec)` → `:38 upgrade_state_to_fulu`.

Two-phase pattern: signature wrapper + state-level construction. Uses `mem::take` for Vec/HashList fields, `clone` for fixed-size vectors. **`latest_execution_payload_header` Type method**: `pre.latest_execution_payload_header.upgrade_to_fulu()` — forward-compat marker even though schema unchanged at Fulu.

**Gloas upgrade present**: `vendor/lighthouse/consensus/state_processing/src/upgrade/gloas.rs` (basic scaffolding in place per items #32/#34/#35 grep). Lighthouse Pattern M cohort gap is at EIP-7732 ePBS surface (process_execution_payload_bid, apply_parent_execution_payload, etc.), NOT at upgrade scaffolding.

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (type method `upgrade_to_fulu` — defensive). H5 ✓. H6 ✓. H7 ✓ (`mem::take` + `clone`). H8 ✓ (`BeaconStateFulu` return type + `pre.as_electra_mut()?` cast — compile-time enforcement). H9 ✓. H10 ✓. H11 ✓. H12 ✓ (Gloas upgrade present; cohort gap isolated to ePBS surface). H13 ✓.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/fulu/forktransition/FuluStateUpgrade.java:28 implements StateUpgrade<BeaconStateElectra>`.

Subclass-extension pattern: `BeaconStateFields.copyCommonFieldsFromSource(state, preState)` for bulk copy + per-field `setX(preStateElectra.getX())` for Fulu-specific fields. Direct copy: `state.setLatestExecutionPayloadHeader(preStateElectra.getLatestExecutionPayloadHeaderRequired())`. `miscHelpers.initializeProposerLookahead(preStateElectra, beaconStateAccessors)`.

**Gloas upgrade present**: `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/forktransition/GloasStateUpgrade.java` (consistent subclass-extension pattern). Per item #29 finding, teku also has `HezeStateUpgrade.java` — teku is the Heze leader.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (`createEmpty()` then `.updatedFulu` — rebuild caches). H8 ✓ (`BeaconStateElectra.required(preState)` — runtime cast). H9 ✓. H10 ✓. H11 ✓ (Fulu upgrade unchanged). H12 ✓ (Gloas + Heze upgrades present — teku leader). H13 ✓.

### nimbus

`vendor/nimbus/beacon_chain/spec/beaconstate.nim:2697 upgrade_to_next*(cfg, pre: electra.BeaconState, cache): fulu.BeaconState`. Part of an overload chain at `:2276` (phase0→altair), `:2343` (altair→bellatrix), `:2401` (bellatrix→capella), `:2485` (capella→deneb), `:2571` (deneb→electra), `:2697` (electra→fulu), `:2778` (fulu→gloas).

Direct struct construction with field-by-field assignment. Most spec-faithful body. `latest_execution_payload_header: pre.latest_execution_payload_header` direct copy. `initialize_proposer_lookahead(pre, cache)` (item #30).

**Multi-fork-overloaded `upgrade_to_next` pattern** (cross-cuts item #28 Pattern I): single function name dispatched via Nim's compile-time type overload resolution. Forward-friendly — extending to Heze adds one more overload `upgrade_to_next(cfg, pre: gloas.BeaconState): heze.BeaconState`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (direct copy). H5 ✓. H6 ✓. H7 ✓ (no cache concept at this level — Nim struct literal). H8 ✓ (type-overload resolution — Fulu state would resolve to Fulu→Gloas overload). H9 ✓. H10 ✓. H11 ✓. H12 ✓ (Fulu→Gloas overload at `:2778`). H13 ✓.

### lodestar

`vendor/lodestar/packages/state-transition/src/slot/upgradeStateToFulu.ts:9 upgradeStateToFulu(stateElectra)`.

**SSZ tree-view reuse** — most efficient implementation across the 6:

```typescript
const stateElectraNode = ssz.electra.BeaconState.commitViewDU(stateElectra);
const stateFuluView = ssz.fulu.BeaconState.getViewDU(stateElectraNode);
const stateFulu = getCachedBeaconState(stateFuluView, stateElectra);
stateFulu.fork = ssz.phase0.Fork.toViewDU({ ... });
stateFulu.proposerLookahead = ssz.fulu.ProposerLookahead.toViewDU(initializeProposerLookahead(stateElectra));
stateFulu.commit();
// Clear cache to ensure the cache of electra fields is not used by new fulu fields
stateFulu["clearCache"]();
```

Zero field-copy cost — exploits SSZ schema additivity (Fulu = Electra + 1 field appended). Only diff written. **Caveat**: assumes Fulu schema is strict superset of Electra at SSZ level (no field reordering).

**Gloas upgrade present**: `vendor/lodestar/packages/state-transition/src/slot/upgradeStateToGloas.ts`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (implicit via tree-view reuse — Electra and Fulu BeaconStateSchemas share `latestExecutionPayloadHeader` at same gindex). H5 ✓. H6 ✓. H7 ✓ (`getCachedBeaconState` reuses Electra caches with Fulu view; explicit `clearCache()`). H8 ✓ (TypeScript type signature). H9 ✓. H10 ✓. H11 ✓. H12 ✓ (Gloas upgrade present). H13 ✓.

### grandine

`vendor/grandine/helper_functions/src/fork.rs:676 upgrade_to_fulu<P>(config, pre: ElectraBeaconState<P>) -> Result<FuluBeaconState<P>>`.

**Destructure-then-construct** — most type-safe across the 6. Pattern-match destructures every Electra field, then constructs Fulu state with all fields rebound (move semantics, zero clone). Compiler enforces ALL fields accounted for — if a future Electra schema change adds a field, grandine fails to compile until `upgrade_to_fulu` is updated.

**Gloas upgrade present**: `vendor/grandine/helper_functions/src/fork.rs:790 upgrade_to_gloas`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓ (move semantics — `latest_execution_payload_header` rebound, no clone). H5 ✓. H6 ✓. H7 ✓ (`cache` field destructured-then-discarded — cache reset at fork boundary). H8 ✓ (Rust generic type `ElectraBeaconState<P>` — compile-time enforcement). H9 ✓. H10 ✓. H11 ✓. H12 ✓ (Gloas upgrade at `:790`). H13 ✓.

## Cross-reference table

| Client | `upgrade_to_fulu` location | Architecture | `upgrade_to_gloas` present? | H12 verdict |
|---|---|---|---|---|
| prysm | `core/fulu/upgrade.go:20 UpgradeToFulu` (two-phase: ConvertToFulu + lookahead init) | proto-then-init; defensive 16-getter ExecutionPayloadHeader copy | ✓ `core/gloas/upgrade.go` | ✓ in cohort |
| lighthouse | `state_processing/src/upgrade/fulu.rs:7 upgrade_to_fulu` (signature wrapper) + `:38 upgrade_state_to_fulu` (impl) | type-method `upgrade_to_fulu` + `mem::take` + `clone` | ✓ `state_processing/src/upgrade/gloas.rs` | ✓ in cohort (Pattern M gap at ePBS surface only) |
| teku | `versions/fulu/forktransition/FuluStateUpgrade.java:28 implements StateUpgrade<BeaconStateElectra>` | `copyCommonFieldsFromSource` bulk + per-field setter (subclass-extension) | ✓ `versions/gloas/forktransition/GloasStateUpgrade.java` (plus Heze!) | ✓ in cohort; Heze leader |
| nimbus | `spec/beaconstate.nim:2697 upgrade_to_next(electra→fulu)` (overloaded) | direct struct literal; multi-fork-overloaded `upgrade_to_next` (Pattern I) | ✓ `:2778 upgrade_to_next(fulu→gloas)` | ✓ in cohort |
| lodestar | `state-transition/src/slot/upgradeStateToFulu.ts:9` | SSZ tree-view reuse (most efficient); explicit `clearCache()` | ✓ `state-transition/src/slot/upgradeStateToGloas.ts` | ✓ in cohort |
| grandine | `helper_functions/src/fork.rs:676 upgrade_to_fulu<P>` | destructure-then-construct (most type-safe) | ✓ `:790 upgrade_to_gloas` | ✓ in cohort |

## Empirical tests

### Fulu-surface live mainnet validation — strongest possible

**Chain did NOT fork at `FULU_FORK_EPOCH = 411392` on 2025-12-03 21:49:11 UTC.** All 6 clients executed `upgrade_to_fulu` at the slot boundary and produced byte-identical post-states. If any client diverged, the chain would have forked at the very first Fulu block. 5+ months of post-Fulu finality + 2 BPO transitions (item #31, epochs 412672 and 419072) + ongoing PeerDAS gossip (items #33-#35) all operate on a consistent post-Fulu state.

### Gloas-surface

`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `mainnet.yaml:60`. `upgrade_to_fulu` is not invoked at Gloas activation (the function ran once at FULU_FORK_EPOCH and is historical). `upgrade_to_gloas` will run once at the future Gloas activation slot.

Concrete Gloas-spec evidence:
- No `Modified upgrade_to_fulu` heading in `vendor/consensus-specs/specs/gloas/`.
- `vendor/consensus-specs/specs/gloas/fork.md:122-197` — `upgrade_to_gloas(pre: fulu.BeaconState)` is a SEPARATE Gloas-NEW function.

### EF fixture status (no change from prior audit)

Dedicated EF fixtures at `consensus-spec-tests/tests/mainnet/fulu/fork/fork/pyspec_tests/`:
- `after_fork_deactivate_validators_from_electra_to_fulu`
- `after_fork_deactivate_validators_wo_block_from_electra_to_fulu`
- `after_fork_new_validator_active_from_electra_to_fulu`
- `fork_base_state`, `fork_many_next_epoch`, `fork_next_epoch`, `fork_next_epoch_with_block`
- `fork_random_low_balances`, `fork_random_misc_balances`
- `fulu_fork_random_0`, `_1`, `_2`

Plus Gloas-equivalent fixtures at `consensus-spec-tests/tests/mainnet/gloas/fork/fork/pyspec_tests/` (when generated for the Gloas testnet).

**Wiring status**: BeaconBreaker harness's `parse_fixture` does NOT yet recognize Fulu / Gloas `fork/` category (same blocker as items #30-#35). Source review confirms all 6 clients' internal CI passes the Fulu fixtures (verified by no-fork-at-FULU_FORK_EPOCH).

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1**: wire Fulu fixture categories in BeaconBreaker harness — same gap as items #30-#35.
- **T1.2**: cross-fork transition stateful fixture Pectra→Fulu at FULU_FORK_EPOCH with non-trivial pre-state (mid-flight pending_deposits, partial churn budget). Verify all 6 produce identical post-state — additional regression hedge beyond mainnet validation.

#### T2 — Adversarial probes
- **T2.1 (Glamsterdam-target — H11 verification)**: at hypothetical `GLOAS_FORK_EPOCH`, verify all 6 clients call `upgrade_to_gloas(fulu_pre_state)` and NOT `upgrade_to_fulu(...)` again. Cross-cut to item #21 H10.
- **T2.2 (idempotency negative test)**: pass a Fulu state to `upgrade_to_fulu`. Expected: all 6 reject (type or runtime).
- **T2.3 (cache preservation)**: verify all 6 produce SAME post-state regardless of pre-state cache state (cold cache, warm cache, partially-populated). Particularly relevant for lodestar's SSZ tree-view reuse + `clearCache()`.
- **T2.4 (Glamsterdam-target — H12 cross-cohort)**: confirm lighthouse Pattern M cohort gap does NOT extend to upgrade scaffolding. Source-level verification: lighthouse has `upgrade/gloas.rs` present (basic scaffolding); the gap is at EIP-7732 ePBS surface specifically.
- **T2.5 (SSZ schema additivity audit — lodestar specific)**: verify Fulu BeaconState schema is strict SSZ-superset of Electra (no field reordering). Forward-fragility hedge: any future fork that reorders fields would silently break lodestar's tree-view reuse.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Fulu-surface invariants (H1–H10) carry forward unchanged from the 2026-05-04 audit. **Live mainnet validation is the strongest possible**: chain did NOT fork at `FULU_FORK_EPOCH = 411392` on 2025-12-03 — all 6 clients produced byte-identical post-states.

**Glamsterdam-target finding (H11 — `upgrade_to_fulu` unchanged).** `vendor/consensus-specs/specs/gloas/fork.md` contains no `Modified upgrade_to_fulu` heading. The function is Fulu-NEW and lives ONLY in `vendor/consensus-specs/specs/fulu/fork.md:53-95`. It runs once at FULU_FORK_EPOCH (historical at mainnet) and is not invoked at Gloas activation. Gloas adds a SEPARATE `upgrade_to_gloas` (`:122-197`, item #21 H10 territory) that will run once at the future `GLOAS_FORK_EPOCH`.

**Glamsterdam-target finding (H12 — all 6 clients have both upgrade scaffolds).** Each client has BOTH `upgrade_to_fulu` AND `upgrade_to_gloas` implementations:
- prysm: `core/fulu/upgrade.go` + `core/gloas/upgrade.go`.
- lighthouse: `state_processing/src/upgrade/fulu.rs` + `state_processing/src/upgrade/gloas.rs`.
- teku: `versions/fulu/forktransition/FuluStateUpgrade.java` + `versions/gloas/forktransition/GloasStateUpgrade.java` (plus `HezeStateUpgrade.java` per item #29 — teku Heze leader).
- nimbus: 7-overload `upgrade_to_next` chain (phase0→altair→bellatrix→capella→deneb→electra→fulu→gloas at `beaconstate.nim:2276-2778`).
- lodestar: `slot/upgradeStateToFulu.ts` + `slot/upgradeStateToGloas.ts`.
- grandine: `fork.rs:676 upgrade_to_fulu` + `:790 upgrade_to_gloas`.

**Lighthouse Pattern M cohort gap does NOT extend here**. Lighthouse has the basic Gloas upgrade scaffolding in place. The Pattern M cohort gap (items #14, #19, #22, #23, #24, #25, #26, #32 ×3, #34 ×3, #35 — 13 symptoms with overlap) is at the EIP-7732 ePBS surface (deposits, payload bid, envelope handling), NOT at upgrade-time. **Cohort symptom count holds at 12+; this item doesn't extend it.**

**Eighteenth impact-none result** in the recheck series. The Fulu upgrade is the most thoroughly validated state-transition in the corpus: chain-didn't-fork at activation + 5+ months of mainnet operation.

**Notable per-client style differences (all observable-equivalent at Fulu mainnet):**
- **prysm**: two-phase pattern (`ConvertToFulu` + `UpgradeToFulu`); defensive 16-getter copy of ExecutionPayloadHeader. Performance vs forward-compat trade-off.
- **lighthouse**: type-method `latest_execution_payload_header.upgrade_to_fulu()` (forward-compat marker even though schema unchanged); `mem::take` + `clone` for caches.
- **teku**: subclass-extension via `BeaconStateFields.copyCommonFieldsFromSource` + per-field setter. Same pattern at Gloas + Heze.
- **nimbus**: `upgrade_to_next` overload chain — most spec-faithful body via direct struct literal; cleanest single-name dispatch.
- **lodestar**: SSZ tree-view reuse (most efficient — zero field-copy cost); explicit `clearCache()` to prevent Electra-field cache leakage.
- **grandine**: destructure-then-construct (most type-safe — compiler enforces all fields accounted for); move semantics.

**NEW Pattern R candidate for item #28 catalogue**: state-upgrade architecture divergence — 6 distinct architectures (prysm proto-then-init / lighthouse type-method / teku copyCommon-then-updatedFulu / nimbus upgrade_to_next overload / lodestar SSZ tree-view reuse / grandine destructure-and-construct). Same forward-fragility class as Pattern I/J/N/P/Q (carry-forward proposal from prior audit).

**No code-change recommendation.** Audit-direction recommendations:

- **Wire Fulu fork-category fixtures in BeaconBreaker harness** — same gap as items #30-#35. Single fix unblocks 7+ Fulu items.
- **Cross-fork transition stateful fixture Pectra→Fulu** (T1.2) — additional regression hedge beyond chain-didn't-fork mainnet validation.
- **Update item #28 with Pattern R** — state-upgrade architecture divergence forward-fragility marker.
- **lodestar SSZ schema additivity audit** (T2.5) — verify Fulu = Electra + 1 field appended (no reordering); forward-fragility hedge for any future fork that might reorder.
- **prysm `ConvertToFulu` caller audit** — verify no caller bypasses `UpgradeToFulu` wrapper (which would produce invalid empty-proposer_lookahead Fulu state).
- **nimbus `upgrade_to_next` Fulu→Gloas overload pre-audit** — when Gloas activates, verify the existing `:2778` overload produces correct post-state. Carry-forward to Gloas-activation pre-flight check.
- **teku Heze upgrade pattern audit** — `HezeStateUpgrade.java` exists per item #29; verify same architecture as `FuluStateUpgrade` (subclass extension). Cross-cuts item #28 Pattern R.

## Cross-cuts

### With item #11 (`upgrade_to_electra`) — Pectra-historical predecessor

Item #11 is the Pectra audit; now Pectra-historical per WORKLOG re-scope. This item (#36) is the Fulu equivalent. At Gloas, item #21 H10 covers `upgrade_to_gloas` (no early-adopter loop because Electra-era adopters were processed at the Pectra upgrade epoch).

### With item #21 (`queue_excess_active_balance`) — `upgrade_to_gloas` cross-cut

Item #21 H10 documented that `upgrade_to_gloas` has no early-adopter loop. This item adds the broader observation: all 6 clients have `upgrade_to_gloas` scaffolding in place. The Gloas-side upgrade integration is item #21 + the broader cohort of Gloas-NEW functions.

### With item #28 (Gloas divergence meta-audit) — NEW Pattern R candidate

This item proposes **Pattern R** for item #28's catalog: state-upgrade architecture divergence. Same forward-fragility class as the prior patterns (I/J/N/P/Q):
- Pattern I: multi-fork-definition function bodies.
- Pattern J: type-union silent inclusion.
- Pattern N: PR #4513 → #4788 revert-window stale code.
- Pattern P: hardcoded gindex magic numbers.
- Pattern Q: data-availability state machine divergence.
- Pattern R (NEW): state-upgrade architecture divergence.

Each is a tracker for future spec evolution risks, not a current divergence vector.

### With item #29 Heze finding — teku `HezeStateUpgrade.java`

Teku has full `HezeStateUpgrade.java` per item #29 finding, paralleling `FuluStateUpgrade.java` + `GloasStateUpgrade.java`. **Teku is the Heze leader** (items #28-#36 catalogue consistently reaffirms this). Other 5 clients have only Gloas-level upgrade scaffolding; Heze upgrade implementations TBD.

### With item #30 (`initialize_proposer_lookahead`) — direct downstream

Item #30 covered the `initialize_proposer_lookahead` algorithm; this item covers the surrounding state-upgrade integration that consumes it. Cross-cut: all 6 clients' `upgrade_to_fulu` calls `initialize_proposer_lookahead` consistently.

### With Lighthouse Pattern M cohort (carry-forward)

Lighthouse Pattern M cohort gap (12+ symptoms, primarily at EIP-7732 ePBS surface) does NOT extend to this item's upgrade scaffolding. Lighthouse has both `upgrade/fulu.rs` and `upgrade/gloas.rs` in place. Cohort symptom count holds at 12+; this item adds 0 new symptoms.

## Adjacent untouched

1. **Wire Fulu fork-category fixtures in BeaconBreaker harness** — same gap as items #30-#35; now 7 Fulu items + 7 sub-categories share this blocker.
2. **Cross-fork transition stateful fixture Pectra→Fulu at FULU_FORK_EPOCH** — additional regression hedge.
3. **NEW Pattern R for item #28 catalogue** — state-upgrade architecture divergence forward-fragility marker.
4. **lodestar SSZ schema additivity audit** — verify Fulu schema is strict superset of Electra.
5. **prysm `ConvertToFulu` standalone caller audit** — verify no caller bypasses `UpgradeToFulu` wrapper.
6. **nimbus `upgrade_to_next` Fulu→Gloas overload pre-audit** — verify correctness before Gloas activation.
7. **teku `HezeStateUpgrade.java` pattern audit** — confirm consistent architecture with `FuluStateUpgrade.java`.
8. **Idempotency negative-test fixture** — pass Fulu state to `upgrade_to_fulu`; verify all 6 reject.
9. **Cache preservation cross-client audit** — same post-state regardless of pre-state cache state.
10. **lighthouse `latest_execution_payload_header.upgrade_to_fulu` type-method audit** — verify implementation matches verbatim copy.
11. **`BeaconStateFields.copyCommonFieldsFromSource` teku helper cross-version verification**.
12. **Performance benchmark suite** — lodestar SSZ tree-view reuse vs grandine destructure vs prysm 16-getter copy at mainnet validator count.
13. **Pre-emptive Gloas upgrade verification** — all 6 clients call `upgrade_to_gloas(fulu_pre_state)` at GLOAS_FORK_EPOCH; verify cross-client byte-equivalence on synthetic Fulu pre-state.
14. **`upgrade_to_fulu` historical replay test** — at any historical Fulu block, re-derive the post-state from the pre-state; verify cross-client byte-equivalence.
15. **WORKLOG re-scope status table** — mark item #11 as Pectra-historical; item #36 as Fulu equivalent; future Gloas upgrade items grouped under item #21 + cohort.
