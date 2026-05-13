# beacon-breaker — LLM-driven CL cross-client audit

An autonomous audit of the Ethereum consensus layer across six production clients at the **Fulu** hard fork (active on mainnet since 2025-12-03, epoch 411392), driven entirely by a large language model.

**Clients audited:** prysm · lighthouse · teku · nimbus · lodestar · grandine

**Scope:** 56 items completed — 29 at the Pectra (Electra) surface, 26 Fulu-NEW (items #30–#56), and 1 cross-corpus meta-audit catalogue refresh (item #48). Coverage spans PeerDAS (EIP-7594) end-to-end, deterministic proposer lookahead (EIP-7917), BPO hardforks (EIP-7892), retention periods, RPC + gossip layers, SSZ container detail, and Track D fork choice.

The completed Pectra surface covers: request processing (EIP-7002 / 7251 / 6110), pending-deposit and pending-consolidation drains, registry updates, slashings, attestations and the EIP-7549 multi-committee aggregation, sync committee selection, withdrawals, execution-payload validation, the EIP-7685 execution-requests pipeline, BLS signature verification, and the foundational signing-domain primitives.

The Fulu-NEW surface (items #30–#56) covers: PeerDAS DataColumnSidecar end-to-end (validation, gossip, RPC, custody, ENR, MetaData, Status), Reed-Solomon recovery math, KZG cell proofs, BPO mainnet transitions (9 → 15 → 21 blobs), `upgrade_to_fulu` state transition, deterministic proposer lookahead, deprecated RPC/gossip handling, foundational caps (`MAX_REQUEST_BLOCKS_DENEB`, `MAX_REQUEST_BLOB_SIDECARS`, `MAX_REQUEST_DATA_COLUMN_SIDECARS`), 4 Fulu-NEW SSZ container schemas, retention period, and Track D fork choice (`is_data_available`, `on_block`).

---

## Methodology

The audit is structured as a sequence of hypothesis-driven items. Each item picks a candidate divergence surface, audits six client source trees in parallel, records the finding, and where source review surfaces a candidate divergence, runs the corresponding EF state-test fixtures across all six clients to confirm or reject it. Wired runners (prysm, lighthouse, lodestar, grandine) execute fixtures end-to-end; teku and nimbus are exercised through their internal CI on the same fixture set.

Full methodology, prompt templates, and repository conventions: [METHODOLOGY.md](METHODOLOGY.md). Project mission and out-of-scope notes: [BEACONBREAKER.md](BEACONBREAKER.md), [OUT_OF_SCOPE.md](OUT_OF_SCOPE.md). Agent instructions: [AGENTS.md](AGENTS.md).

---

## Active findings (as of 2026-05-13)

| # | Finding | Split | Mainnet reach |
|---|---|---|---|
| [#22](items/022/) | nimbus treats 0x03 (builder) credentials as compounding at Gloas+ via stale `has_compounding_withdrawal_credential` OR-fold — pre-Gloas 0x03 deposit forks effective_balance at Gloas activation | nimbus (1-vs-5) | mainnet-glamsterdam |
| [#23](items/023/) | nimbus get_pending_balance_to_withdraw OR-folds builder_pending_withdrawals + builder_pending_payments at Gloas+ — rejects voluntary_exit / withdrawal_request / consolidation_request on validators whose index collides with an active builder index | nimbus (1-vs-5) | mainnet-glamsterdam |
| [#28](items/028/) | meta-audit — nimbus stale PR #4513 → #4788 revert-window OR-folds (items #22 + #23) cause mainnet-glamsterdam forks at Gloas; lighthouse missing ePBS surface (items #14, #19, #22, #23, #24, #25, #26 cohort) prevents Gloas wiring | nimbus, lighthouse (2-vs-4) | mainnet-glamsterdam |

## Remediated findings

_(none)_

## Cross-cutting observations

**0 confirmed Pectra or Fulu mainnet divergences across 56 items.** All 6 clients have run Fulu mainnet for 5+ months without observed consensus divergence. The active-findings table above is dominated by `mainnet-glamsterdam` rows — code paths whose divergence will materialise at Gloas activation (`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` today). Observed differences at Pectra and Fulu are entirely in caching, dispatch idiom, source organization, forward-compat patches, and naming conventions.

**35 forward-fragility patterns catalogued (A–II)** — code paths that are observable-equivalent today but predict cross-client divergence at future forks (Gloas, Heze) or at adversarial inputs (cgc=0, empty validator set, malicious peer publishing to deprecated topic).

**Multiple bug-fix opportunities identified** across nimbus, teku, prysm, grandine — none are active Pectra/Fulu divergences, all are forward-fragility or naming/casing inconsistencies.

### Audit corpus structure

| Surface | Items | Notes |
|---|---|---|
| Pectra (Electra) state-transition core | #1–#27 | All confirmed conformant; 23 inherited unchanged at Fulu |
| Cross-corpus catalogue (Pattern A–L → A–II) | #28, #48 | Meta-audits; refreshed at #48 covering Patterns A–CC; extended to A–II by #56 |
| Heze surprise (teku leadership) | #29 | Discovered teku has full `HezeStateUpgrade.java`; flipped Gloas-laggard ranking |
| Fulu state-transition / proposer lookahead / BPO | #30–#36, #43 | EIP-7917 + EIP-7892; retroactively corrected V4/V5 Engine API ambiguity |
| PeerDAS — custody, gossip, KZG, Reed-Solomon | #33–#42, #44 | DataColumnSidecar end-to-end + ENR cgc/nfd |
| PeerDAS — metadata, RPC, handshake, caps | #45–#47, #49, #52 | MetaData v3, Status v2, RPC handlers, response cap, MAX_REQUEST_BLOCKS_DENEB |
| Heritage-deprecation tracking | #50, #51 | RPC layer (BlobSidecarsByRange/Root v1) + gossip layer (`blob_sidecar_{subnet_id}`) |
| Fulu-NEW SSZ container detail | #45, #47, #53, #54 | MetaData v3, Status v2, DataColumnsByRootIdentifier, DataColumnSidecar |
| Retention period | #55 | `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` |
| Track D fork choice (FIRST audit) | #56 | `is_data_available` + `on_block` |

### Pattern catalogue (35 patterns, A–II)

The catalogue is the central forward-fragility tracking document. Selected highlights:

- **Pattern E/F/M (Gloas A-tier triad)** — committee index, sync committee selection, proposer indices via `compute_balance_weighted_selection`. 3-leader / 3-laggard split.
- **Pattern P + V (grandine hardcoded gindex 11)** — symmetric consumer + producer divergence at Heze. Triple-fragility extended at #54: gindex 11 verify + gindex 11 produce + compile-time-baked depth 4.
- **Pattern Y (lighthouse Gloas V5 readiness gap)** — pre-emptive fix candidate.
- **Pattern Z (PartialDataColumnSidecar)** — implementation gap; only nimbus implements; nimbus has apparent bug in `verify_partial_data_column_sidecar_kzg_proofs`.
- **Pattern AA (per-client SSZ container divergence)** — version numbering (V2 vs V3), field naming (nimbus `indices` vs spec `columns`), casing (lodestar camelCase), internal class-vs-SSZ-name inconsistency (teku), Go field naming (prysm singular Request vs plural REQUESTS).
- **Pattern DD (3-category split)** — computed formula vs hardcoded YAML with formula validation vs hardcoded YAML without validation (caps for sidecar RPC responses).
- **Pattern EE/GG (heritage-deprecation handling)** — RPC + gossip deprecation. INVERTED DEFENSE on teku: most defensive on RPC deprecation (item #50), least defensive on gossip deprecation (item #51).
- **Pattern HH (compile-time constant baked into binary)** — nimbus + grandine for wire-protocol invariants (gindex depth, request caps); refined to NOT apply to operator-tunable parameters (retention windows).
- **Pattern II (fork choice DA architecture divergence)** — 6 distinct architectures (most diverse finding); A-tier sampling-vs-custody divergence at high blob loads.

Full catalogue with per-pattern source refs: [items/028/README.md](items/028/README.md) (original A–L) and [items/048/README.md](items/048/README.md) (refresh A–CC). Patterns DD–II added in items #49–#56.

### Active interop risks today

3 patterns have observable cross-client divergence today (none manifested in mainnet operation):

| Risk | Pattern | Trigger |
|---|---|---|
| nimbus SSZ uint8 cgc encoding | W | A peer setting `cgc=0` (empty bytes) |
| lodestar empty-validator-set returns 4 | T | Empty validator set during testing |
| teku subscribes to deprecated `blob_sidecar` at Fulu fork digest | GG | Malicious peer publishing BlobSidecars at Fulu fork digest |

### Per-client forward-compat readiness

| Client | Pectra | Fulu mainnet | Gloas | Heze |
|---|---|---|---|---|
| nimbus | ✅ | ✅ (5+ months) | **leader** (incl. `gloasColumnQuarantine` pre-implemented) | none |
| grandine | ✅ | ✅ (5+ months) | leader | none |
| lighthouse | ✅ | ✅ (5+ months) | active | none |
| prysm | ✅ | ✅ (5+ months) | active | constants only (`.ethspecify.yml`) |
| lodestar | ✅ | ✅ (5+ months) | active | none |
| teku | ✅ | ✅ (5+ months) | minimal in core | **leader** (full `HezeStateUpgrade.java`) |

### Notable per-client divergences (selected)

- **prysm** — most defensive request-side validation (dual error types for cap exceeded, item #49); singular Go field name `MinEpochsForDataColumnSidecarsRequest` vs plural spec (item #55).
- **lighthouse** — cleanest cross-fork derivation (`max_blocks_by_root_request_common(self.max_request_blocks_deneb)`, item #52); `#[superstruct(variants(Fulu, Gloas))]` hints at DataColumnSidecar Gloas variant (item #54).
- **teku** — CONSISTENT HYBRID pattern (compute formula + YAML override) across items #49/#50/#52; **Pattern J** separate `AvailabilityChecker` classes per fork (item #56); INVERTED DEFENSE on heritage deprecation (most defensive RPC, least defensive gossip).
- **nimbus** — most spec-faithful comments (`fulu_preset.nim:15` derives gindex from BeaconBlockBody; `nimbus_beacon_node.nim:1473` "Deliberately don't handle blobs"); compile-time-baked constants via `checkCompatibility` (Pattern HH); 3-quarantine architecture (item #56); Gloas pre-implementation leader.
- **lodestar** — systematic camelCase across all SSZ containers (Pattern AA); Pattern R DAType enum union dispatch (item #56); CLI exposes retention extension.
- **grandine** — `saturating_mul` for overflow safety; type-level `U4` for KZG depth (Pattern HH); Pattern P + V symmetric (gindex 11 verify + produce); storage-mode-aware retention accessor (item #55); BlobReconstructionPool for fork-choice DA (item #56).

### Cross-cutting observations

- **6 distinct fork-dispatch idioms** observed end-to-end: prysm runtime version check; lighthouse superstruct enum; teku subclass override; nimbus 3-quarantine type-union; lodestar numeric `ForkSeq`; grandine module-namespace.
- **All six clients use BLST or BLST-based wrappers** (items #20, #25). No BLS-library-family divergence at the verification surface.
- **Spec-undefined edge cases (Pattern T family)**: empty validator sets, empty list validation, duplicate index handling, deprecated-RPC behavior, V1↔V2 default values, DA timeout policies. Each client interprets differently.
- **Heritage-deprecation tracking spans 2 layers**: RPC (item #50) + gossip (item #51). teku has INVERTED DEFENSE (most defensive RPC, least defensive gossip).
- **Triple-fragility for grandine at Heze**: gindex 11 verify (Pattern P) + gindex 11 produce (Pattern V) + compile-time-baked depth 4 (Pattern HH). A-tier pre-emptive fix priority.
- **Sampling-vs-custody A-tier divergence at fork choice DA** (item #56): 3-3 split. At hypothetical 100+ blobs per block, sampling-aware (prysm, teku, lodestar) MAY accept blocks that custody-aware (lighthouse, nimbus, grandine) reject.

---

## Repository layout

```
itemNN/             per-item audit (56 items: #1–#29 Pectra, #30–#56 Fulu-NEW + meta)
  README.md         hypotheses, per-client cross-reference, findings, future research
WORKLOG.md          full sequential audit log (Goal + Fork Target + Re-scope status + per-item bodies)
BEACONBREAKER.md    project mission, scope, tracks, methodology rationale
METHODOLOGY.md      audit loop and prompt templates
AGENTS.md           agent instructions
OUT_OF_SCOPE.md     surfaces explicitly out of scope (with flag-if-encountered notes)
URGENT.md           triage list for any high-severity finding
tools/runners/      per-client EF fixture runners (prysm, lighthouse, teku, nimbus, lodestar, grandine)
tools/test-configs/ pyspec custom configs for spec-test fork-from-genesis fixtures
tools/ssz/          SSZ helper utilities
prysm/ lighthouse/  client source submodules (pinned in WORKLOG.md "Clients & Versions")
teku/ nimbus/
lodestar/ grandine/
consensus-specs/    pyspec submodule
consensus-spec-tests/  EF test fixtures submodule
beacon-APIs/        beacon-API spec submodule
```

Submodule pins, fork target, and active EIPs in scope: [WORKLOG.md](WORKLOG.md) header.

---

## Status snapshot (2026-05-04)

- **56 items committed**, **35 patterns catalogued** (A–II), **0 active mainnet divergences**
- **Fulu mainnet**: all 6 clients, 5+ months stable, 2 BPO transitions executed (9 → 15 → 21 blobs)
- **Heritage-RPC + gossip deprecation tracking**: BlobSidecarsByRange/Root v1 (4.5 months past cutoff); `blob_sidecar_{subnet_id}` gossip (deprecated at Fulu)
- **Track D opened** at item #56: many fork choice cross-client audits pending (tie-breaking, proposer boost, LMD GHOST, score calculation)
- **Forward-research priorities**: lighthouse Gloas V5 readiness (Pattern Y); grandine Heze triple-fragility (Patterns P + V + HH-depth); nimbus PartialDataColumnSidecar bug (item #44); cross-client interop fixtures for active risks (Patterns W/T/CC/GG); pre-emptive Gloas DA layer audit (only nimbus has gloasColumnQuarantine)
