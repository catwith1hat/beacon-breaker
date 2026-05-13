# beacon-breaker — LLM-driven CL cross-client audit

An autonomous audit of the Ethereum consensus layer across six production clients, driven entirely by a large language model. Current fork target: Fulu (live mainnet) and Glamsterdam (Gloas CL + Amsterdam EL, looking forward).

**Clients audited:** prysm · lighthouse · teku · nimbus · lodestar · grandine

---

## Methodology

Each item picks a candidate divergence surface, audits six client source trees in parallel, records hypotheses + findings, and where source review surfaces a candidate divergence, runs the corresponding EF state-test fixtures across the wired clients (prysm, lighthouse, lodestar, grandine; teku and nimbus via internal CI).

Full methodology, prompt templates, and repository conventions: [METHODOLOGY.md](METHODOLOGY.md). Project mission and out-of-scope notes: [BEACONBREAKER.md](BEACONBREAKER.md), [OUT_OF_SCOPE.md](OUT_OF_SCOPE.md). Agent instructions: [AGENTS.md](AGENTS.md).

Every item in the audit (whether or not it produced a divergence): [ITEM_TOC.md](ITEM_TOC.md)

---

## Active findings (as of 2026-05-13)

| # | Finding | Split | Mainnet reach |
|---|---|---|---|
| [#41](items/041/) | nimbus encodes the ENR `cgc` field as SSZ uint8 (1 byte always); the spec and the other 5 clients use variable-length BE with leading-zero stripping (`cgc=0` → empty bytes) — wire-format divergence on cgc=0 and silent overflow at cgc≥256 | nimbus (1-vs-5) | D — synthetic state |
| [#22](items/022/) | nimbus treats 0x03 (builder) credentials as compounding at Gloas+ via stale `has_compounding_withdrawal_credential` OR-fold — pre-Gloas 0x03 deposit forks effective_balance at Gloas activation | nimbus (1-vs-5) | mainnet-glamsterdam |
| [#23](items/023/) | nimbus get_pending_balance_to_withdraw OR-folds builder_pending_withdrawals + builder_pending_payments at Gloas+ — rejects voluntary_exit / withdrawal_request / consolidation_request on validators whose index collides with an active builder index | nimbus (1-vs-5) | mainnet-glamsterdam |
| [#28](items/028/) | meta-audit — two nimbus stale PR #4513 → #4788 revert-window OR-folds (items #22 + #23) cause mainnet-glamsterdam forks at Gloas; the prior lighthouse Pattern M cohort (items #14, #19, #22 H10, #23 H8, #24, #25, #26) has fully closed under the unstable HEAD pin | nimbus (1-vs-5) | mainnet-glamsterdam |

## Remediated findings

_(none)_

## Cross-cutting observations

**0 confirmed Pectra or Fulu mainnet divergences across 56 items.** All six clients have run Fulu mainnet for 5+ months without observed consensus divergence. The active findings above are dominated by `mainnet-glamsterdam` rows — code paths whose divergence materialises at Gloas activation (`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` today).

**Nimbus PR #4513 → PR #4788 revert window** ([#22](items/022/), [#23](items/023/)): both active Gloas divergences share the same root cause. PR #4513 added `Modified` Gloas sections to `has_compounding_withdrawal_credential` and `get_pending_balance_to_withdraw`; PR #4788 removed them when builders became a separate `state.builders` registry. Nimbus shipped the intermediate v1.6.0-beta.0 code and did not roll back. Two one-line fixes close both.

**Lighthouse EIP-7732 ePBS cohort closed under `unstable`.** The prior recheck flagged six lighthouse-only ePBS gaps (items #7, #9, #12, #13, #14, #19, plus #15 V5). All have vacated under the per-client Glamsterdam branches (lighthouse + nimbus `unstable`, prysm `EIP-8061`, teku `glamsterdam-devnet-2`, grandine `glamsterdam-devnet-3`). See [items/028/README.md](items/028/README.md) for the full pattern catalogue (A–II).

---

## Repository layout

```
items/NNN/        per-item audit (56 items)
  README.md       Jekyll-style front matter + hypotheses, findings, cross-refs
ITEM_TOC.md       auto-regenerated flat table of every item
WORKLOG.md        sequential audit log
METHODOLOGY.md    audit loop and prompt templates
driver/           regen scripts, presubmit, runners-of-runners
tools/runners/    per-client EF fixture runners
vendor/           client source submodules + consensus-specs + EF tests
```

Submodule pins and fork target in [WORKLOG.md](WORKLOG.md) header.
