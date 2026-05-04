# beacon-breaker — LLM-driven CL cross-client audit

An autonomous audit of the Ethereum consensus layer across six production clients at the **Fulu** hard fork (active on mainnet since 2025-12-03, epoch 411392), driven entirely by a large language model.

**Clients audited:** prysm · lighthouse · teku · nimbus · lodestar · grandine

**Scope:** 29 items completed at the Pectra (Electra) surface, of which 23 are inherited unchanged at Fulu and remain authoritative; 3 are Pectra-historical with Fulu follow-ups queued; 2 are cross-corpus meta-audits. **Fulu-NEW surfaces (PeerDAS / EIP-7594, deterministic proposer lookahead / EIP-7917, BPO hardforks / EIP-7892) are queued as items #30+ and not yet audited.**

The completed Pectra surface covers: request processing (EIP-7002 / 7251 / 6110), pending-deposit and pending-consolidation drains, registry updates, slashings, attestations and the EIP-7549 multi-committee aggregation, sync committee selection, withdrawals, execution-payload validation, the EIP-7685 execution-requests pipeline, BLS signature verification, and the foundational signing-domain primitives.

---

## Methodology

The audit is structured as a sequence of hypothesis-driven items. Each item picks a candidate divergence surface, audits six client source trees in parallel, records the finding, and where source review surfaces a candidate divergence, runs the corresponding EF state-test fixtures across all six clients to confirm or reject it. Wired runners (prysm, lighthouse, lodestar, grandine) execute fixtures end-to-end; teku and nimbus are exercised through their internal CI on the same fixture set.

Full methodology, prompt templates, and repository conventions: [METHODOLOGY.md](METHODOLOGY.md). Project mission and out-of-scope notes: [BEACONBREAKER.md](BEACONBREAKER.md), [OUT_OF_SCOPE.md](OUT_OF_SCOPE.md). Agent instructions: [AGENTS.md](AGENTS.md).

---

## Findings

**0 confirmed Pectra-fork divergences across 29 items.** ~1620 explicit fixture PASSes + ~6000 implicit PASSes through cross-cut helpers. The Pectra surface — inherited unchanged at Fulu — is consistent across all six clients at the algorithm level; observed differences are entirely in caching, dispatch idiom, source organization, and forward-compat patches.

**Fulu-NEW surfaces are not yet covered**: PeerDAS (DataColumnSidecar, custody groups, KZG cell proofs, Reed-Solomon matrix recovery, column gossip), deterministic proposer lookahead (`proposer_lookahead` field, `process_proposer_lookahead`, modified `get_beacon_proposer_index`), and Blob Parameter Only / BPO hardforks (runtime per-epoch blob limit via `blob_schedule`, modified `process_execution_payload`, modified `compute_fork_digest` with XOR masking). Mainnet has already executed two BPO transitions: 9 → 15 blobs at epoch 412672 (2025-12-09), then → 21 at epoch 419072 (2026-01-07). See [WORKLOG.md](WORKLOG.md) re-scope status table for the full classification of items #1–#29 and the queued Fulu items #30+.

What the audit *did* surface, beyond Pectra-surface conformance, is a **forward-compat divergence catalogue** at the Pectra → Gloas → Heze boundary: code paths that are dead today but predict cross-client divergence at the next two forks.

### Forward-compat divergence vectors at Gloas

11 distinct pre-emptive patterns observed across 22 of 27 prior items, condensed to **9 forward-compat divergence vectors at Gloas activation** (item #28):

| Tier | Vector | Permissive / pre-emptive client(s) | Reach at Gloas |
|---|---|---|---|
| **A** | committee index `< 2` post-Gloas | prysm | A-tier fork on first multi-committee attestation |
| **A** | sync committee selection (`compute_balance_weighted_selection`) | lighthouse + grandine | A-tier — different sync aggregate signers |
| **A** | builder deposit handling (`applyDepositForBuilder`, on-the-fly BLS) | lodestar + grandine + nimbus | A-tier — different validator set after first builder deposit |
| **A** | dispatcher exclusion gates (`fork < ForkSeq.gloas`) | lodestar + prysm | A-tier — double-process of execution requests |
| **A** | Engine API V5 (`engine_newPayloadV5`) | prysm + lighthouse + lodestar | A-tier — EL rejection at the boundary |
| **C** | `getActivationChurnLimit` Gloas branch | lodestar | different deposit-drain throughput |
| **C** | `CONSOLIDATION_CHURN_LIMIT_QUOTIENT` independent quotient | lodestar | different consolidation throughput |
| **C** | `0x03` BUILDER credential prefix | nimbus + prysm | different `effective_balance` for builder validators |
| **C** | builder pending-withdrawals accumulator | nimbus + grandine | different exit-eligibility verdicts |

Tier definitions: **A** = immediate fork on the first Gloas block matching the trigger; **C** = throughput / limit math that diverges over time.

Full catalogue with per-pattern source refs: [item28/README.md](item28/README.md).

### Per-client forward-compat readiness

Updated post-#29 with the Heze surprise (see Cross-cutting observations). **Fulu column not yet audited**; all six clients run Fulu on mainnet today, so the column is presumed ✅ at the integration level but pending source-level audit.

| Client | Pectra | Fulu | Gloas | Heze |
|---|---|---|---|---|
| nimbus | ✅ | (mainnet ✅, source-audit pending) | leader (11+ surfaces) | none |
| grandine | ✅ | (mainnet ✅, source-audit pending) | leader (9+ surfaces) | none |
| lighthouse | ✅ | (mainnet ✅, source-audit pending) | active (6+ surfaces) | none |
| prysm | ✅ | (mainnet ✅, source-audit pending) | active (5+ surfaces) | constants only (`.ethspecify.yml`) |
| lodestar | ✅ | (mainnet ✅, source-audit pending) | active (6+ surfaces) | none |
| teku | ✅ | (mainnet ✅, source-audit pending) | minimal in core | **leader** (full `HezeStateUpgrade.java`) |

### Cross-cutting observations

**Multi-fork-definition source-organization pattern** (items #6/#9/#10/#12/#14/#15/#17/#19): nimbus and grandine ship separate function bodies per fork. Forward-fragile for cross-fork refactors that touch the Electra body.

**Six distinct per-fork dispatch idioms** observed end-to-end: prysm runtime version check; lighthouse superstruct enum; teku subclass override; nimbus type-union compile-time; lodestar numeric `ForkSeq`; grandine module-namespace.

**All six clients use BLST or BLST-based wrappers** (confirmed at items #20 and #25). No BLS-library-family divergence at the verification surface.

**3 of 6 clients explicitly deduplicate the attesting-indices set** (item #26): prysm, lighthouse, grandine. teku, nimbus, lodestar rely on "unique by construction" through committee shuffling — observable-equivalent today, forward-fragile if shuffling ever changes.

**Heze leadership inversion** (item #29 surprise): item #28 ranked teku as the Gloas-readiness laggard based on its sparse Gloas surface in state-transition core. Reading teku's `MiscHelpers.computeForkVersion` while auditing the signing-domain primitives surfaced a **full Heze (post-Gloas, EIP-7805 inclusion lists) implementation** in teku — `HezeStateUpgrade.java`, `SpecMilestone.HEZE`, `getHezeForkEpoch()` / `getHezeForkVersion()`. prysm has Heze constants in `.ethspecify.yml`. The other four clients have no Heze references. **teku is in fact the LEADER on the post-Gloas Heze surface.**

**grandine EIP-7044 4-fork OR-list is forward-fragile at Heze** (item #29): grandine's voluntary-exit signing-domain pin enumerates `deneb || electra || fulu || gloas`. Without an explicit Heze extension, voluntary exits signed under Heze fork version will FAIL grandine BLS verification at Heze activation. High-priority pre-emptive fix.

### Selected non-divergences

- **prysm `BatchVerifyPendingDepositsSignatures`** — appeared to deviate from the per-deposit verification path; confirmed observable-equivalent (item #20).
- **lodestar `pendingValidatorPubkeysCache`** — batched-sig avoidance pattern; confirmed correct caching invariants (item #20).
- **lodestar BigInt-vs-u64 overflow gap in `invalid_large_withdrawable_epoch`** — deliberate documented skip with spec-linked TODO; not a real divergence (item #17).
- **lighthouse lcli `pre_state.all_caches_built()` panic on transition fixtures** — runner limitation; lighthouse internal CI passes the same fixtures (item #23).
- **grandine `SignatureBytes::empty()` placeholder PendingDeposit signature** — initially flagged as differing from canonical G2_POINT_AT_INFINITY across items #11/#18; correction in item #21 confirmed it sets `bytes[0] = 0xc0` to produce the byte-equivalent canonical infinity point.
- **teku `IndexedAttestationLight` internal record without sorted check** — uniqueness is guaranteed by construction; observable-equivalent to the wire-format `IndexedAttestation` sorted check (item #25).

---

## Repository layout

```
itemNN/             per-item audit (29 items at Pectra surface; Fulu items #30+ queued)
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
