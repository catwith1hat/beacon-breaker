# Item 48 — Cross-corpus forward-fragility pattern catalogue REFRESH (extends item #28; covers Patterns A–CC across 47 audits)

**Status:** consolidation-meta-audit (refresh) — audited 2026-05-04. Refresh of item #28's "Cross-corpus pre-emptive Gloas-fork divergence consolidated tracking audit" — the original catalogued **Patterns A–L (12 patterns)** consolidating findings across 22 of 27 prior items. Items #29–#47 added **17 new patterns (M–CC)** spanning Heze surprise + Fulu state-transition + PeerDAS surface + ENR layer + RPC layer + EL boundary. **Total: 29 patterns (A–CC)** across the 47-item corpus.

This refresh provides:
1. **Full Pattern catalogue** (A–CC) with cross-references to source items
2. **Updated per-client forward-readiness scorecard** for Pectra/Fulu/Gloas/Heze
3. **Tier-ranked divergence vectors** at upcoming forks
4. **Roadmap** of unaudited surfaces + future research priorities
5. **NOT a new function audit** — synthesis of prior findings

## Scope

In: synthesis of all forward-fragility patterns across items #1–#47; per-client readiness scorecard refresh; tier-ranked divergence vectors at Gloas + Heze; pattern classification (encoding/orchestration/multi-fork-definition/spec-undefined/implementation-gap); cross-pattern relationships.

Out: any new audit; corrections to prior items (separate retroactive task); Track D fork choice items beyond #35; Track E SSZ schemas not yet covered (BlobAndProofV2, ExecutionBundleFulu, DataColumnsByRootIdentifier).

## Pattern catalogue (A–CC; 29 patterns)

### Item #28 original catalogue (A–L; 12 patterns)

| # | Pattern | Source items | Tier | Description |
|---|---|---|---|---|
| **A** | `0x03` BUILDER credential prefix (pre-Gloas) | #1, #22 | C-tier | nimbus + prysm pre-emptive `is_builder_withdrawal_credential` constants and Gloas-aware `has_compounding_withdrawal_credential` |
| **B** | Builder pending-withdrawals accumulator (pre-Gloas) | #3, #23 | C-tier | nimbus + grandine separate `get_pending_balance_to_withdraw_for_builder` for Gloas |
| **C** | `getActivationChurnLimit` Gloas branch | #4 | C-tier | lodestar Gloas branch uses `getActivationChurnLimit` (not `getActivationExitChurnLimit`); other 5 don't have Gloas branch |
| **D** | `CONSOLIDATION_CHURN_LIMIT_QUOTIENT` independent quotient | #16 | C-tier | lodestar Gloas branch uses INDEPENDENT quotient (not residual model); other 5 don't |
| **E** | Committee index `< 2` post-Gloas | #7 | A-tier | prysm `data.index < 2` post-Gloas (vs `== 0` Electra); other 5 still `== 0` |
| **F** | Sync committee selection (`compute_balance_weighted_selection`) post-Gloas | #27 | A-tier | lighthouse + grandine separate post-Gloas paths; other 4 don't |
| **G** | Builder deposit handling (`applyDepositForBuilder`) | #14, #20, #21, #40 | A-tier | lodestar/grandine/nimbus have on-the-fly BLS verify variants; other 3 don't |
| **H** | Dispatcher exclusion gates (`fork < ForkSeq.gloas`) | #13 | A-tier | lodestar/prysm have explicit Gloas dispatcher removal; other 4 still run Pectra dispatcher |
| **I** | Multi-fork-definition (separate per-fork function bodies) | #6, #9, #10, #12, #14, #15, #17, #19, #31, #32 | F-tier | nimbus + grandine ship separate function bodies per fork; teku subclass extension |
| **J** | Type-union silent inclusion (`electra \| fulu \| gloas`) | #1, #8, #14, #16, #18, #21, #23 | F-tier | nimbus type-union compile-time dispatch; lighthouse `BeaconState::Gloas(_)` enum match arms |
| **K** | Engine API V5 (`engine_newPayloadV5`) | #15, #43 | A-tier (Gloas) | **CORRECTED at item #43**: V5 is GLOAS-NEW (not Fulu-NEW as items #15/#19/#32/#36 originally said) |
| **L** | Voluntary-exit signing-domain (CAPELLA pin extension) | #6 | (no divergence) | grandine 4-fork OR-list explicit; other 5 implicit via `>= Capella` semantics |

### Items #29–#34 (M–P; 4 new patterns from Fulu state-transition + PeerDAS gossip)

| # | Pattern | Source items | Tier | Description |
|---|---|---|---|---|
| **M** | `compute_proposer_indices` post-Gloas (`compute_balance_weighted_selection`) | #30 | A-tier | lighthouse + nimbus + grandine pre-emptive Gloas branches; prysm + teku + lodestar TBD. Same 3-leader/3-laggard split as Pattern F (sync committee selection) |
| **N** | `compute_fork_digest` Fulu-modified multi-fork-definition | #31 | F-tier | nimbus + grandine separate `compute_fork_digest_pre_fulu` / `_post_fulu` functions; multi-fork-definition Pattern I scope expansion |
| **O** | PeerDAS API-surface unsorted-vs-sorted divergence | #33 | F-tier | lighthouse + grandine return `HashSet<CustodyIndex>` UNORDERED; prysm + teku + nimbus + lodestar return sorted Sequence. Set equality preserved; iteration-order divergent |
| **P** | Hardcoded gindex (consumer-side) | #34 | F-tier (B-tier at Heze) | grandine `index_at_commitment_depth = 11` hardcoded for `verify_sidecar_inclusion_proof`. Forward-fragile at Heze if BeaconBlockBody schema gains new fields (per item #29 teku Heze finding) |

### Items #35–#42 (Q–X; 8 new patterns from Fulu fork-choice + PeerDAS production + ENR)

| # | Pattern | Source items | Tier | Description |
|---|---|---|---|---|
| **Q** | Data-availability state machine | #35 | F-tier | grandine 5-state explicit (`Irrelevant`/`Complete`/`AnyPending`/`CompleteWithReconstruction`/`Missing`); teku 4-state SamplingEligibility; lodestar 4-state DAType; lighthouse 2-state Availability; prysm + nimbus single-result. **Most divergence** in PeerDAS surface |
| **R** | State-upgrade architecture (6 distinct patterns) | #36 | F-tier | prysm proto-then-init / lighthouse type-method / teku copyCommon-then-updatedFulu / nimbus upgrade_to_next overload / lodestar SSZ tree-view reuse / grandine destructure-and-construct |
| **S** | Hidden compile-time invariant assertion (gossip-subnet/column ratio) | #37 | F-tier | nimbus `static: doAssert DATA_COLUMN_SIDECAR_SUBNET_COUNT == NUMBER_OF_COLUMNS` with explicit "subnet number and column ID semi-interchangeably" comment. Forward-fragile at any spec change to subnet/column ratio |
| **T** | Spec-undefined edge-case divergence (empty input) | #38 | F-tier | lodestar empty-validator-set returns `CUSTODY_REQUIREMENT = 4` (non-validator default); other 5 return `VALIDATOR_CUSTODY_REQUIREMENT = 8`. Spec-undefined behavior |
| **U** | Reed-Solomon orchestration architecture (5 distinct patterns) | #39 | F-tier | prysm errgroup; lighthouse library-direct; teku ForkJoinPool common pool (contention); nimbus Taskpool (with code-duplication risk); lodestar async; grandine dedicated_executor. Plus 2 KZG library families (c-kzg-4844 vs rust-kzg) |
| **V** | Hardcoded inclusion-proof construction (producer-side dual of Pattern P) | #40 | F-tier (B-tier at Heze) | grandine `kzg_commitments_inclusion_proof` MANUALLY CONSTRUCTS Merkle proof using hardcoded field positions. **Symmetric Pattern P + V**: at Heze, grandine PRODUCER generates wrong proofs AND CONSUMER fails to verify correct ones → double-failure mesh fragmentation |
| **W** | ENR-encoding format divergence (SSZ uint8 vs spec variable-length BE) | #41 | F-tier (active edge case) | nimbus uses SSZ uint8 encoding for ENR cgc field (1 byte even for cgc=0); other 5 use variable-length BE per spec. **Active interop risk on cgc=0** (nimbus decoder fails on empty bytes) |
| **X** | Peer-discovery strictness divergence (pre-connection rejection) | #42 | F-tier | prysm REJECTS peers at connection time on nfd mismatch (converts spec MAY → MUST); other 5 likely soft (per spec "MAY disconnect at/after the fork boundary") |

### Items #43–#47 (Y–CC; 5 new patterns from EL boundary + RPC + ENR + metadata)

| # | Pattern | Source items | Tier | Description |
|---|---|---|---|---|
| **Y** | Per-client Engine API method version dispatch architecture (5 distinct patterns) | #43 | F-tier | lodestar ForkSeq ternary chain; prysm payload-type-based switch; teku milestone-keyed JSON-RPC method registry; lighthouse function-named-by-fork (Gloas V5 readiness gap!); nimbus async dispatch. **Lighthouse Gloas V5 readiness gap** flagged for pre-emptive fix |
| **Z** | Implementation gap on optional spec features (5-of-6 missing) | #44 | F-tier (would be B-tier if mandatory) | PartialDataColumnSidecar — only nimbus implements; other 5 have ZERO references (prysm has spec-tracking metadata only). Production impact LOW because optional gossip optimization. Forward-fragile if spec promotes to mandatory at higher blob counts |
| **AA** | Per-client SSZ container version-numbering divergence | #45, #47 | F-tier | prysm `MetaDataV2` for spec V3 (offset by 1; doesn't increment for Altair); lighthouse + grandine V-named (spec-aligned); teku + nimbus + lodestar fork-named. **Pattern AA scope EXPANDS at #47**: also applies to Status messages — teku `StatusMessageFulu` |
| **BB** | Per-client RPC handler architecture (5 distinct patterns) | #46 | F-tier | prysm map-based registration; lighthouse + grandine strum-enum; teku two-layer handler+proxy; nimbus macro-driven libp2pProtocol; lodestar async-generator |
| **CC** | V1↔V2 default value handling divergence | #47 | F-tier | 4 of 6 silently default `earliest_available_slot = 0`; teku strict-required (throws if absent); nimbus symbolic `GENESIS_SLOT`. Same forward-fragility class as Pattern T |

## Per-client forward-readiness scorecard (refreshed)

Updated post-#47 with Fulu mainnet validation + Heze pre-emptive findings + per-pattern source-aware ranking.

| Client | Pectra | Fulu | Gloas readiness | Heze readiness | Notable risks |
|---|---|---|---|---|---|
| **prysm** | ✅ | ✅ (mainnet 5+ months) | leader on V5 dispatch (Pattern Y); explicit Gloas dispatcher removal (Pattern H); committee index `< 2` (Pattern E) | constants only in `.ethspecify.yml` (Pattern Z partial — prysm has more Heze metadata than other clients but no implementation) | Pattern Y dispatch architecture forward-fragility; Pattern AA naming offset (V2 = spec V3) |
| **lighthouse** | ✅ | ✅ (mainnet 5+ months) | leader on builder pending-withdrawals (Pattern B), sync committee selection (Pattern F), proposer indices (Pattern M); strict cgc validation (Pattern X cousin) | none beyond inheritance | **Lighthouse Gloas V5 readiness gap** (Pattern Y `new_payload_v4_gloas` calls V4 not V5) — high-priority pre-emptive fix |
| **teku** | ✅ | ✅ (mainnet 5+ months) | minimal in core; subclass extension friendly (Pattern I/AA) | **LEADER on Heze**: full `HezeStateUpgrade.java` implementation; `MetadataMessageFulu` + `StatusMessageFulu` fork-naming (Pattern AA); strict-required `Optional` handling (Pattern CC) | Pattern AA fork-naming confusion across teams |
| **nimbus** | ✅ | ✅ (mainnet 5+ months) | leader on `0x03` BUILDER credential (Pattern A), builder pending-withdrawals (Pattern B), sync committee selection (Pattern F), proposer indices (Pattern M); pre-emptive type-union (Pattern J); separate per-fork function bodies (Pattern I); ONLY client implementing PartialDataColumnSidecar (Pattern Z) | minimal | **APPARENT BUG** in `verify_partial_data_column_sidecar_kzg_proofs` (uses blob index instead of column_index — item #44); ENR cgc SSZ uint8 encoding (Pattern W); hidden compile-time invariant (Pattern S); type-overload silent inclusion (Pattern J); Optional retention on Opt.none (Pattern T cousin) |
| **lodestar** | ✅ | ✅ (mainnet 5+ months) | leader on Gloas churn (Patterns C + D); explicit Gloas dispatcher gate (Pattern H); pre-computed-proofs optimization (item #39 EL-level); strict cross-validation on Status v2 (item #47); explicit rate limit table (Pattern BB) | none beyond inheritance | Pattern C/D unique churn semantics — others must follow at Gloas; Pattern T empty-set; Pattern CC permissive defaults; ENR cgc silent NaN on div-by-zero (Pattern W cousin) |
| **grandine** | ✅ | ✅ (mainnet 5+ months) | leader on builder pending-withdrawals (Pattern B), sync committee selection (Pattern F), proposer indices (Pattern M); pre-emptive Gloas modules (Pattern I); KzgBackend swappable (Pattern U) | none beyond inheritance | **Patterns P + V (symmetric forward-fragility)**: hardcoded gindex 11 in BOTH consumer (item #34) AND producer (item #40) — at Heze, grandine PeerDAS gossip mesh fragments (double-failure mode); EIP-7044 4-fork OR-list (Pattern L cousin) requires explicit Heze extension; SINGULAR `get_validator_custody_requirement` naming (Pattern AA cousin) |

### Headline forward-readiness rankings:

**Heze leadership** (post-Gloas, EIP-7805 inclusion lists):
1. **teku** — full `HezeStateUpgrade.java` + `SpecMilestone.HEZE` + `getHezeForkEpoch/Version` (per item #29 finding)
2. **prysm** — Heze constants in `.ethspecify.yml` (no implementation code)
3. lighthouse, nimbus, lodestar, grandine — no Heze references

**Gloas-readiness** (per item #28 original ranking, refreshed):
1. **nimbus** — 11+ surfaces; type-union compile-time dispatch (cheapest extension)
2. **grandine** — 9+ surfaces; dedicated `gloas/` modules; **2 forward-fragility risks** (Patterns P + V symmetric)
3. **lighthouse** — 6+ surfaces; enum match arms; **1 forward-fragility risk** (Pattern Y Gloas V5 gap)
4. **prysm** — 5+ surfaces; runtime version checks
5. **lodestar** — 6+ surfaces; explicit Gloas branches in churn (Patterns C + D unique)
6. **teku** — minimal in core (subclass extension implicit); **LEADER on Heze**

## Tier-ranked divergence vectors at upcoming forks (refreshed)

### A-tier at Gloas activation (immediate fork on first matching block)

1. **Pattern E** (committee index `< 2`) — prysm only; first multi-committee attestation at Gloas with `data.index = 1` would diverge
2. **Pattern F** (sync committee selection) — lighthouse + grandine + nimbus have separate Gloas paths; other 3 don't → different sync aggregate signers → different finality
3. **Pattern M** (`compute_proposer_indices` post-Gloas) — same 3-leader/3-laggard split as Pattern F; different proposer indices = different blocks
4. **Pattern G** (builder deposit handling) — lodestar + grandine + nimbus have on-the-fly BLS verify; other 3 don't → different validator set after first builder deposit
5. **Pattern H** (dispatcher exclusion gates) — lodestar + prysm have explicit Gloas dispatcher removal; other 4 still run Pectra dispatcher → double-process of execution requests
6. **Pattern K** (Engine API V5) + **Pattern Y** (lighthouse V5 readiness gap) — lighthouse `new_payload_v4_gloas` calls V4 (not V5) → EL rejection at Gloas activation. **Highest-priority pre-emptive fix**

### A-tier at Heze activation (immediate fork or gossip mesh fragmentation)

7. **Pattern P + V** (grandine hardcoded gindex 11 — symmetric consumer + producer) — at Heze, BeaconBlockBody schema may add new fields (per teku Heze finding item #29). Grandine's PRODUCER generates wrong inclusion proofs AND CONSUMER fails to verify correct proofs from peers using updated schema → grandine PeerDAS gossip mesh fragments

### C-tier at Gloas (throughput/limit math diverges over time)

8. **Pattern C** (lodestar `getActivationChurnLimit`) — different deposit-drain throughput at Gloas
9. **Pattern D** (lodestar `CONSOLIDATION_CHURN_LIMIT_QUOTIENT`) — different consolidation throughput
10. **Pattern A** (nimbus + prysm `0x03` builder credential) — different effective_balance for builder validators
11. **Pattern B** (nimbus + grandine builder pending withdrawals) — different exit-eligibility verdicts

### F-tier (forward-fragile patterns; not divergence today)

- Pattern I (multi-fork-definition) — historical Electra blocks may fail to verify after Gloas-fork code added
- Pattern J (type-union silent inclusion) — Gloas-specific tweaks may be missed
- Pattern N (compute_fork_digest multi-fork-definition) — same as Pattern I
- Pattern O (HashSet vs sorted Sequence) — observable-equivalent set membership; iteration-order divergent
- Pattern Q (DA state machine) — observable-equivalent verdicts; reconstruction-trigger may differ
- Pattern R (state-upgrade architecture) — code duplication risk in multi-fork upgrades
- Pattern S (nimbus subnet/column compile-time invariant) — at any spec change to ratio
- Pattern T (lodestar empty-set) — Pattern CC analog; spec-undefined edge cases
- Pattern U (Reed-Solomon orchestration) — performance trade-offs; KZG library family divergence
- Pattern W (ENR cgc SSZ uint8) — active interop risk on cgc=0 (rare in practice)
- Pattern X (prysm pre-connection rejection on nfd mismatch) — peer pool reduction around BPO transitions
- Pattern Z (PartialDataColumnSidecar implementation gap) — would become B-tier if mandatory
- Pattern AA (SSZ container naming) — cross-team confusion (cosmetic)
- Pattern BB (RPC handler architecture) — code maintainability
- Pattern CC (V1↔V2 default value handling) — spec-undefined edge case

### Active interop risks today (not just forward-fragility)

- **Pattern W**: cgc=0 → nimbus SSZ uint8 decoder fails on empty bytes from other 5
- **Pattern T** (item #38 lodestar empty-set returns 4; others return 8) — observable divergence on edge case
- **Pattern Z** (PartialDataColumnSidecar) — nimbus's partial publishing wasted on other 5

## Pattern classification (cross-cuts)

| Class | Patterns | Description |
|---|---|---|
| **Encoding format divergence** | W (cgc), CC (V1↔V2 defaults) | Wire-format byte-level disagreements |
| **Architecture divergence** | I (multi-fork-def), J (type-union), R (state-upgrade), U (Reed-Solomon orchestration), Y (Engine API dispatch), BB (RPC handlers) | Code structure differs; observable-equivalent today |
| **Hardcoded constant divergence** | P (consumer gindex 11), V (producer manual proof), S (nimbus subnet/column ratio), AA (naming offset) | Magic numbers / hardcoded knowledge of spec |
| **Spec-undefined edge case** | T (empty validator set), CC (V1↔V2 defaults) | Per-client interpretation of unspecified behavior |
| **Implementation gap** | Z (5-of-6 missing PartialDataColumnSidecar) | Optional spec feature not implemented |
| **API surface divergence** | O (sorted vs unsorted), AA (V2 vs V3 vs Fulu naming) | Cross-team confusion + tooling friction |
| **Strictness divergence** | C/D (lodestar Gloas churn), E/F/M (Gloas pre-emptive paths), G/H (Gloas dispatcher), X (prysm pre-connection), Q (DA state machine) | Validation strictness or code-path divergence |
| **Forward-compat marker** | L (CAPELLA pin), N (compute_fork_digest split) | Defensive code for future-fork modifications |

## Cross-pattern relationships

- **Pattern P + V (symmetric)**: grandine hardcoded gindex 11 on both consumer (item #34) AND producer (item #40) sides. Double-failure mode at Heze. **Highest-priority forward-fragility pair.**
- **Pattern T + CC (related)**: spec-undefined edge cases handled differently per client (lodestar empty-set + V1→V2 default value). Same root cause: spec doesn't define behavior; per-client interpretation diverges.
- **Pattern AA scope-expansion**: covers MetaData v3 (item #45) AND Status v2 (item #47) — teku consistently fork-names SSZ containers; other 5 V-named.
- **Pattern I + N + R (multi-fork-definition family)**: nimbus + grandine ship separate per-fork function bodies for state-transition functions (I), `compute_fork_digest` (N), and `upgrade_to_*` (R). Forward-fragility class.
- **Pattern Y + K (Engine API)**: Pattern Y dispatch architecture cross-cuts Pattern K (Gloas V5 method); lighthouse Gloas V5 readiness gap is the active risk.
- **Pattern E + F + M (Gloas A-tier triad)**: 3 attestation/sync-committee/proposer-selection patterns all involving `compute_balance_weighted_selection` post-Gloas. **Most A-tier divergence concentration in PeerDAS-adjacent surfaces.**

## Roadmap of unaudited surfaces

### Critical unaudited at Fulu mainnet target

- **Track D fork choice** beyond #35: `update_proposer_boost_root`, `compute_pulled_up_tip`, `update_checkpoints` (called from `on_block`) — Phase0/Bellatrix-heritage but consensus-critical
- **Track E SSZ schemas not yet covered**: BlobAndProofV2 (engine_getBlobsV2 response), ExecutionBundleFulu (engine_getPayloadV5 response), DataColumnsByRootIdentifier (item #46 request type)
- **`compute_max_request_data_column_sidecars()` formula consistency** (item #46 cross-cut)
- **BlobSidecarsByRange v1 / BlobSidecarsByRoot v1** (Deneb-heritage but Fulu-active for blob backfill)
- **Cross-fork transition Pectra → Fulu fixture** at FULU_FORK_EPOCH = 411392
- **`compute_signed_block_header`** (validator helper)

### Pre-emptive Gloas audits (when Gloas activates)

- **A-tier vector pre-emptive fixtures** for Patterns E, F, G, H, K (committee index `< 2`, sync committee selection, builder deposit handling, dispatcher exclusion gates, Engine API V5)
- **`compute_balance_weighted_selection`** standalone audit (used by Patterns F + M)
- **EIP-7732 PBS** items (`process_execution_payload_bid`, `process_builder_payment`, etc.)
- **`process_execution_payload_envelope`** Gloas-NEW

### Pre-emptive Heze audits (per item #29 finding)

- **`HezeStateUpgrade.java`** (teku-only standalone) — track teku's Heze code progression
- **EIP-7805 inclusion list** items
- **BeaconBlockBody schema cross-fork audit** for grandine Patterns P + V mitigation
- **Cross-client Heze readiness scorecard**

### Infrastructure / fixtures

- **Wire Fulu fixture categories** in BeaconBreaker harness — would unblock 18 audited Fulu items
- **Generate cross-client interop fixtures** for Patterns W (cgc=0), T (empty-set), CC (V1↔V2)
- **Items #15/#19/#32/#36 retroactive corrections** (V5 confusion per item #43)

## Summary

Item #28's original Pattern catalogue (A–L; 12 patterns) covered Gloas pre-emptive findings across 22 of 27 prior items. Items #29–#47 added **17 new patterns (M–CC)** spanning:
- **Heze surprise** (items #29 teku full Heze + prysm constants; #36/#42 cross-cuts)
- **Fulu state-transition** (items #30/#31/#32/#36 producing Patterns M/N/R)
- **PeerDAS surface** (items #33/#34/#35/#37/#38/#39/#40 producing Patterns O/P/Q/S/T/U/V)
- **ENR + RPC layer** (items #41/#42/#43/#44/#45/#46/#47 producing Patterns W/X/Y/Z/AA/BB/CC)

**29 patterns total** classified into 8 cross-cut categories:
- **Encoding format divergence** (2): W, CC
- **Architecture divergence** (6): I, J, R, U, Y, BB
- **Hardcoded constant divergence** (4): P, V, S, AA
- **Spec-undefined edge case** (2): T, CC
- **Implementation gap** (1): Z
- **API surface divergence** (2): O, AA
- **Strictness divergence** (8): C, D, E, F, M, G, H, X, Q
- **Forward-compat marker** (2): L, N

### A-tier divergence vectors at Gloas activation (5):

1. Pattern E (committee index `< 2`) — prysm
2. Pattern F (sync committee selection) — lighthouse + grandine + nimbus
3. Pattern M (proposer indices post-Gloas) — same 3 leaders as F
4. Pattern G (builder deposit handling) — lodestar + grandine + nimbus
5. Pattern H (dispatcher exclusion gates) — lodestar + prysm
6. Pattern K + Y (Engine API V5) — **lighthouse Gloas V5 readiness gap** (highest-priority pre-emptive fix)

### A-tier divergence vectors at Heze activation (1):

7. Pattern P + V (grandine hardcoded gindex 11 — symmetric consumer + producer) — **double-failure mode**

### Active interop risks today (3):

- Pattern W (cgc=0 — nimbus SSZ uint8 decoder fails on empty bytes)
- Pattern T (lodestar empty-validator-set returns 4; others return 8)
- Pattern Z (PartialDataColumnSidecar — only nimbus implements; other 5 ignore nimbus's partial publishing)

### Per-client forward-readiness leaders:

- **Heze**: teku (full HezeStateUpgrade) > prysm (constants only) > others (none)
- **Gloas**: nimbus > grandine > lighthouse > prysm > lodestar > teku
- **Fulu mainnet**: all 6 ✅ (5+ months without divergence)

**Status**: 47 audits committed, 29 forward-fragility patterns catalogued, comprehensive roadmap into Gloas + Heze + remaining unaudited surfaces. **Total item count: 48 (#1-#48)**. The catalogue is now the central forward-fragility tracking document for the corpus and should be re-refreshed every ~10 audits or when major new patterns surface.

Forward-research priorities (in order):
1. **Lighthouse Gloas V5 readiness gap** (Pattern Y, item #43) — pre-emptive fix before Gloas
2. **Grandine Patterns P + V mitigation** (items #34, #40) — replace hardcoded gindex 11 with dynamic resolution before Heze
3. **Nimbus PartialDataColumnSidecar bug verification** (item #44) — `cell_indices` uses blob index instead of column_index
4. **Cross-client interop fixtures for Patterns W/T/CC** — exercise spec-undefined edge cases
5. **Wire Fulu fixture categories in BeaconBreaker harness** — unblock 18 audited Fulu items
6. **Track D fork choice + Track E SSZ schemas** — close remaining unaudited consensus-critical surfaces
