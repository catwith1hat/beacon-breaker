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
| [#76](items/076/) | surface scan of the 28+ fork-choice Gloas modifications — high-risk area, dedicated multi-item audit recommended; identified is_payload_verified / is_payload_timely / get_ancestor → ForkChoiceNode / is_supporting_vote / should_extend_payload / get_payload_status_tiebreaker / get_attestation_score / record_block_timeliness as the highest-leverage follow-up targets | — | Unknown |
| [#67](items/067/) | lodestar emits Gloas builder sweep withdrawal with queue-decremented cached balance instead of pre-block builder.balance — empirically confirmed via items/067/demo/spec_vs_lodestar.py; mainnet-reachable post-Glamsterdam by any builder that initiates exit while having pending payments | lodestar (1-vs-5) | mainnet-glamsterdam |
| [#77](items/077/) | lodestar fork-choice drops the `blob_data_available` half of the PTC vote — `notifyPtcMessages` accepts only `payloadPresent`, no `payloadDataAvailabilityVote` map exists, and `shouldExtendPayload` checks `isPayloadTimely` alone instead of spec's `is_payload_timely AND is_payload_data_available`; mainnet-reachable on Gloas-active networks when PTC majority votes payload_present=True but blob_data_available=False | lodestar (1-vs-5) | mainnet-glamsterdam |
| [#78](items/078/) | prysm's `ExecutionPayloadEnvelope` SSZ container is missing the `parent_beacon_block_root` field (spec PR #5152 from 2026-04-24) — 4 fields vs spec's 5, so prysm cannot deserialize envelopes from the other 5 clients; consequently `verify_execution_payload_envelope` lacks the `envelope.parent_beacon_block_root == state.latest_block_header.parent_root` and `envelope.beacon_block_root == hash_tree_root(header)` asserts; cross-CL incompatibility post-Glamsterdam | prysm (1-vs-5) | mainnet-glamsterdam |
| [#79](items/079/) | nimbus's main fork-choice subsystem (`proto_array.nim`, `fork_choice.nim`) has NO Gloas payload-status tracking — `findHead` is pure phase-0 style; no FULL/EMPTY/PENDING variants per consensus block; no `is_supporting_vote`-equivalent; no `should_extend_payload`; no `is_payload_data_available`; no `is_payload_timely`; once Glamsterdam activates, nimbus cannot participate in Gloas fork-choice | nimbus (1-vs-5) | mainnet-glamsterdam |
| [#80](items/080/) | spec `is_supporting_vote` returns False for FULL/EMPTY variants when `message.slot == block.slot` (same-slot vote) — lighthouse and teku correctly route same-slot votes to PENDING bucket only; prysm asymmetrically routes same-slot FULL votes to FULL bucket (EMPTY votes to PENDING); lodestar routes same-slot votes directly to FULL/EMPTY variants per `payloadPresent`; grandine accumulates same-slot votes into FULL/EMPTY buckets via `attesting_balances.full/empty`; affects fork-choice scoring of FULL/EMPTY variants of any block from 2+ slots ago | prysm, lodestar, grandine (3-vs-3) | mainnet-glamsterdam |
| [#81](items/081/) | spec `get_weight` returns 0 for FULL/EMPTY variants when `block.slot + 1 == current_slot` (previous-slot block) — lighthouse/teku/lodestar implement the zeroing; prysm's `choosePayloadContent` uses raw fn.weight/en.weight comparison at previous-slot, falling back to `shouldExtendPayload` only on weight ties (spec uses tiebreaker exclusively); grandine's segment-based scoring lacks the previous-slot zeroing entirely — uses `attesting_balances.full/empty` raw at previous-slot | prysm, grandine (2-vs-4) | mainnet-glamsterdam |

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
