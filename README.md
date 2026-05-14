# beacon-breaker — LLM-driven CL cross-client audit

An autonomous audit of the Ethereum consensus layer across six production clients, driven entirely by a large language model. Current fork target: Fulu (live mainnet) and Glamsterdam (Gloas CL + Amsterdam EL, looking forward).

**Clients audited:** prysm · lighthouse · teku · nimbus · lodestar · grandine

---

## Methodology

Each item picks a candidate divergence surface, audits six client source trees in parallel, records hypotheses + findings, and where source review surfaces a candidate divergence, runs the corresponding EF state-test fixtures across the wired clients (prysm, lighthouse, lodestar, grandine; teku and nimbus via internal CI).

Full methodology, prompt templates, and repository conventions: [METHODOLOGY.md](METHODOLOGY.md). Project mission and out-of-scope notes: [BEACONBREAKER.md](BEACONBREAKER.md), [OUT_OF_SCOPE.md](OUT_OF_SCOPE.md). Agent instructions: [AGENTS.md](AGENTS.md).

Every item in the audit (whether or not it produced a divergence): [ITEM_TOC.md](ITEM_TOC.md)

---

## Active findings (as of 2026-05-14)

| # | Finding | Split | Mainnet reach |
|---|---|---|---|
| [#41](items/041/) | nimbus encodes the ENR `cgc` field as SSZ uint8 (1 byte always); the spec and the other 5 clients use variable-length BE with leading-zero stripping (`cgc=0` → empty bytes) — wire-format divergence on cgc=0 and silent overflow at cgc≥256 | nimbus (1-vs-5) | D — synthetic state |
| [#67](items/067/) | lodestar emits Gloas builder sweep withdrawal with queue-decremented cached balance instead of pre-block builder.balance (suspected state-root divergence when an exited builder has pending queue entries; spec `get_builders_sweep_withdrawals` reads `state.builders[idx].balance` directly); empirical verification recommended | lodestar (1-vs-5) | Unknown |
| [#71](items/071/) | TBD — drafting `engine_getPayloadV5` builder-vs-self-build dispatch audit (Gloas ePBS impact on getPayload; CL chooses local-build (BUILDER_INDEX_SELF_BUILD) vs external-builder) | — | Unknown |
| [#72](items/072/) | TBD — drafting PeerDAS custody column selection audit (runtime usage of the cgc field; column-selection algorithm + custody-set computation per node) | — | Unknown |
| [#73](items/073/) | TBD — drafting `get_data_column_sidecars` construction audit (column-from-block construction; KZG inclusion proofs; cross-client byte-equivalence on the constructed sidecar SSZ bytes) | — | Unknown |

## Remediated findings

| # | Finding | Split | Mainnet reach |
|---|---|---|---|
| [#22](items/022/) | nimbus treated 0x03 (builder) credentials as compounding at Gloas+ via stale `has_compounding_withdrawal_credential` OR-fold (1-vs-5; fixed upstream in nimbus 550c7a3f0 / PR #8440 "align two Gloas state transition functions with alpha.7 spec") | nimbus (1-vs-5) | mainnet-glamsterdam |
| [#23](items/023/) | nimbus `get_pending_balance_to_withdraw` OR-folded `builder_pending_withdrawals` + `builder_pending_payments` into the validator-side accessor at Gloas+ (1-vs-5; fixed upstream in nimbus 550c7a3f0 / PR #8440 "align two Gloas state transition functions with alpha.7 spec") | nimbus (1-vs-5) | mainnet-glamsterdam |
| [#28](items/028/) | meta-audit — both nimbus PR #4513 → #4788 revert-window OR-folds (items #22 + #23) and the prior lighthouse Pattern M ePBS cohort (items #14, #19, #22 H10, #23 H8, #24, #25, #26) closed; the EIP-8061 churn family and the EIP-7732 ePBS lifecycle are uniform across all six clients (1-vs-5 nimbus Pattern N divergences fixed upstream in nimbus 550c7a3f0 / PR #8440) | nimbus (1-vs-5) | mainnet-glamsterdam |

## Cross-cutting observations

**0 confirmed Pectra or Fulu mainnet divergences across 56 finalized items.** All six clients have run Fulu mainnet for 5+ months without observed consensus divergence. The audit has driven all three identified Gloas-activation divergences upstream (items #22, #23 fixed in nimbus PR #8440; the prior lighthouse Pattern M ePBS cohort closed under `unstable` HEAD `1a6863118`); only the synthetic-state ENR `cgc` encoding divergence in item #41 remains. Items #57–#62 are open drafts (hypotheses formed; source review pending).

**Nimbus PR #4513 → PR #4788 revert window** ([#22](items/022/), [#23](items/023/) — both remediated): both Gloas divergences shared the same root cause. PR #4513 added `Modified` Gloas sections to `has_compounding_withdrawal_credential` and `get_pending_balance_to_withdraw`; PR #4788 removed them when builders became a separate `state.builders` registry. Nimbus shipped the intermediate v1.6.0-beta.0 code and did not roll back; fixed upstream in nimbus PR [#8440](https://github.com/status-im/nimbus-eth2/pull/8440) (commit `550c7a3f0`, 2026-05-14).

**Lighthouse EIP-7732 ePBS cohort closed under `unstable`.** The prior recheck flagged six lighthouse-only ePBS gaps (items #7, #9, #12, #13, #14, #19, plus #15 V5). All vacated under the per-client Glamsterdam branches (lighthouse + nimbus `unstable`, prysm `EIP-8061`, teku `glamsterdam-devnet-2`, grandine `glamsterdam-devnet-3`). See [items/028/README.md](items/028/README.md) for the full pattern catalogue (A–II).

---

## Repository layout

```
items/NNN/        per-item audit (62 items; #57–#62 in drafting)
  README.md       Jekyll-style front matter + hypotheses, findings, cross-refs
ITEM_TOC.md       auto-regenerated flat table of every item
WORKLOG.md        sequential audit log
METHODOLOGY.md    audit loop and prompt templates
driver/           regen scripts, presubmit, runners-of-runners
tools/runners/    per-client EF fixture runners
vendor/           client source submodules + consensus-specs + EF tests
```

Submodule pins and fork target in [WORKLOG.md](WORKLOG.md) header.
