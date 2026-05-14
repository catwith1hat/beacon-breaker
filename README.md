# beacon-breaker — LLM-driven CL cross-client audit

An autonomous audit of the Ethereum consensus layer across six production clients, driven entirely by a large language model. Current fork target: Fulu (live mainnet) and Glamsterdam (Gloas CL + Amsterdam EL, looking forward).

**Clients audited:** prysm · lighthouse · teku · nimbus · lodestar · grandine

---

## Summary (2026-05-14)

This repository contains an LLM-driven audit of 85 items across the six consensus clients, with a focus on the Glamsterdam fork target. The recent Gloas fork-choice + state-transition cluster (items #67, #76–#85) surfaced nine candidate spec-vs-implementation gaps that may be worth a closer look by client maintainers — eight tagged `mainnet-glamsterdam` and one (#67) tagged `synthetic-state` after a follow-up reachability re-analysis; three earlier nimbus items (#22, #23, #28) have already been remediated upstream. Each item cites the relevant spec lines and per-client source lines so a reviewer can quickly check the underlying claims; a Python simulator harness at `items/076/demo/` and in-tree vitest demos in `items/067/demo/` and `items/077/demo/` reproduce several of the divergences against real client source. **These are LLM-generated observations against published spec text and have not been independently verified by client teams — please treat them as suggestions to investigate rather than authoritative findings, and reach out via the linked items if anything looks off.**

---

## Methodology

Each item picks a candidate divergence surface, audits six client source trees in parallel, records hypotheses + findings, and where source review surfaces a candidate divergence, runs the corresponding EF state-test fixtures across the wired clients (prysm, lighthouse, lodestar, grandine; teku and nimbus via internal CI).

Full methodology, prompt templates, and repository conventions: [METHODOLOGY.md](METHODOLOGY.md). Project mission and out-of-scope notes: [BEACONBREAKER.md](BEACONBREAKER.md), [OUT_OF_SCOPE.md](OUT_OF_SCOPE.md). Agent instructions: [AGENTS.md](AGENTS.md).

Every item in the audit (whether or not it produced a divergence): [ITEM_TOC.md](ITEM_TOC.md)

---

## Active findings (as of 2026-05-14)

| # | Finding | Split | Mainnet reach |
|---|---|---|---|
| [#67](items/067/) | lodestar emits Gloas builder sweep withdrawal with queue-decremented cached balance instead of pre-block builder.balance; only surfaces on a hand-built or fuzz-generated state since process_voluntary_exit precondition blocks the queue+sweep collision in honest block production | lodestar (1-vs-5) | D — synthetic state |
| [#77](items/077/) | lodestar fork-choice drops the `blob_data_available` half of the PTC vote — `notifyPtcMessages` accepts only `payloadPresent`, no `payloadDataAvailabilityVote` map exists, and `shouldExtendPayload` checks `isPayloadTimely` alone instead of spec's `is_payload_timely AND is_payload_data_available`; mainnet-reachable on Gloas-active networks when PTC majority votes payload_present=True but blob_data_available=False | lodestar (1-vs-5) | mainnet-glamsterdam |
| [#78](items/078/) | prysm's `ExecutionPayloadEnvelope` SSZ container is missing the `parent_beacon_block_root` field (spec PR #5152 from 2026-04-24) — 4 fields vs spec's 5, so prysm cannot deserialize envelopes from the other 5 clients; consequently `verify_execution_payload_envelope` lacks the `envelope.parent_beacon_block_root == state.latest_block_header.parent_root` and `envelope.beacon_block_root == hash_tree_root(header)` asserts; cross-CL incompatibility post-Glamsterdam | prysm (1-vs-5) | mainnet-glamsterdam |
| [#79](items/079/) | nimbus's main fork-choice subsystem (`proto_array.nim`, `fork_choice.nim`) has NO Gloas payload-status tracking — `findHead` is pure phase-0 style; no FULL/EMPTY/PENDING variants per consensus block; no `is_supporting_vote`-equivalent; no `should_extend_payload`; no `is_payload_data_available`; no `is_payload_timely`; once Glamsterdam activates, nimbus cannot participate in Gloas fork-choice | nimbus (1-vs-5) | mainnet-glamsterdam |
| [#80](items/080/) | spec `is_supporting_vote` returns False for FULL/EMPTY variants when `message.slot == block.slot` (same-slot vote) — lighthouse and teku correctly route same-slot votes to PENDING bucket only; prysm asymmetrically routes same-slot FULL votes to FULL bucket (EMPTY votes to PENDING); lodestar routes same-slot votes directly to FULL/EMPTY variants per `payloadPresent`; grandine accumulates same-slot votes into FULL/EMPTY buckets via `attesting_balances.full/empty`; affects fork-choice scoring of FULL/EMPTY variants of any block from 2+ slots ago | prysm, lodestar, grandine (3-vs-3) | mainnet-glamsterdam |
| [#81](items/081/) | spec `get_weight` returns 0 for FULL/EMPTY variants when `block.slot + 1 == current_slot` (previous-slot block) — lighthouse/teku/lodestar implement the zeroing; prysm's `choosePayloadContent` uses raw fn.weight/en.weight comparison at previous-slot, falling back to `shouldExtendPayload` only on weight ties (spec uses tiebreaker exclusively); grandine's segment-based scoring lacks the previous-slot zeroing entirely — uses `attesting_balances.full/empty` raw at previous-slot | prysm, grandine (2-vs-4) | mainnet-glamsterdam |
| [#82](items/082/) | spec `record_block_timeliness` records 2 booleans per block (`[ATTESTATION_TIMELINESS_INDEX, PTC_TIMELINESS_INDEX]`) used by `should_apply_proposer_boost` to suppress boost when an early (PTC-timely) equivocation exists from the same proposer — only lighthouse implements both the 2-tuple tracking and the equivocation suppression branch; teku tracks both but skips the suppression (TODO); prysm/lodestar use single-boolean timeliness; grandine uses raw equivocation count without PTC-timeliness filter (more strict than spec) | prysm, teku, lodestar, grandine (4-vs-2) | mainnet-glamsterdam |
| [#83](items/083/) | spec Gloas `is_head_weak` adds equivocating-validator weight from head-slot committees to head_weight for monotonicity ("more attestations can only change output from True to False, not vice-versa") — lighthouse/teku/grandine implement the addition; prysm and lodestar use raw consensus-node weight without the equivocating term; affects late-block reorg decisions when equivocations exist in head-slot committees | prysm, lodestar (2-vs-4) | mainnet-glamsterdam |
| [#84](items/084/) | Gloas reorg-helper trio audit — `is_parent_strong` (prysm uses raw consensus-node weight not variant-specific; grandine unimplemented), `update_proposer_boost_root` canonical-proposer-index check (prysm and lodestar lack the proposer-index match gate, applying boost to any timely first-seen block regardless of whether proposer matches canonical chain), and `is_head_late` (grandine has no equivalent, missing late-head-reorg machinery entirely) | prysm, lodestar, grandine (3-vs-3) | mainnet-glamsterdam |

## Remediated findings

| # | Finding | Split | Mainnet reach |
|---|---|---|---|
| [#22](items/022/) | nimbus treated 0x03 (builder) credentials as compounding at Gloas+ via stale `has_compounding_withdrawal_credential` OR-fold (1-vs-5; fixed upstream in nimbus 550c7a3f0 / PR #8440 "align two Gloas state transition functions with alpha.7 spec") | nimbus (1-vs-5) | mainnet-glamsterdam |
| [#23](items/023/) | nimbus `get_pending_balance_to_withdraw` OR-folded `builder_pending_withdrawals` + `builder_pending_payments` into the validator-side accessor at Gloas+ (1-vs-5; fixed upstream in nimbus 550c7a3f0 / PR #8440 "align two Gloas state transition functions with alpha.7 spec") | nimbus (1-vs-5) | mainnet-glamsterdam |
| [#28](items/028/) | meta-audit — both nimbus PR #4513 → #4788 revert-window OR-folds (items #22 + #23) and the prior lighthouse Pattern M ePBS cohort (items #14, #19, #22 H10, #23 H8, #24, #25, #26) closed; the EIP-8061 churn family and the EIP-7732 ePBS lifecycle are uniform across all six clients (1-vs-5 nimbus Pattern N divergences fixed upstream in nimbus 550c7a3f0 / PR #8440) | nimbus (1-vs-5) | mainnet-glamsterdam |

## Cross-cutting observations

**No confirmed Pectra or Fulu mainnet divergences identified.** All six clients have run Fulu mainnet for 5+ months without observed consensus divergence in the surfaces the audit examined. Forward-looking items targeting Glamsterdam are surfaced as suggestions for client teams to review.

**Gloas fork-choice cluster (items #67, #76–#85).** A focused review of the Gloas (Glamsterdam CL) fork-choice and state-transition surfaces produced nine candidate spec-vs-implementation gaps documented in items #67 and #77–#84. Item #76 indexes the surface scan; #85 documents `upgrade_to_gloas` as cross-client conformant. Item #67 (lodestar builder sweep + queue cache-read) was initially tagged `mainnet-glamsterdam` and later downgraded to `synthetic-state` after a closer reading of `process_voluntary_exit:1647` showed the colliding state is unreachable from honest block production. Findings cluster around three patterns: spec lag relative to recent consensus-specs revisions, missing payload-status awareness on the Gloas FULL/EMPTY/PENDING variant model, and partial implementation of the PTC-timeliness equivocation-suppression branch in `should_apply_proposer_boost`. Resolution options are spelled out per item.

**Nimbus PR #4513 → PR #4788 revert window** ([#22](items/022/), [#23](items/023/) — both remediated): both Gloas divergences shared the same root cause. PR #4513 added `Modified` Gloas sections to `has_compounding_withdrawal_credential` and `get_pending_balance_to_withdraw`; PR #4788 removed them when builders became a separate `state.builders` registry. Nimbus shipped the intermediate v1.6.0-beta.0 code and did not roll back; the fix landed upstream in nimbus PR [#8440](https://github.com/status-im/nimbus-eth2/pull/8440) (commit `550c7a3f0`, 2026-05-14).

**Lighthouse EIP-7732 ePBS cohort closed under `unstable`.** An earlier recheck flagged six lighthouse-only ePBS gaps (items #7, #9, #12, #13, #14, #19, plus #15 V5). All vacated under the per-client Glamsterdam branches (lighthouse + nimbus `unstable`, prysm `EIP-8061`, teku `glamsterdam-devnet-2`, grandine `glamsterdam-devnet-3`). See [items/028/README.md](items/028/README.md) for the full pattern catalogue (A–II).

---

## Repository layout

```
items/NNN/        per-item audit (85 items as of 2026-05-14)
  README.md       Jekyll-style front matter + hypotheses, findings, cross-refs
  demo/           optional empirical artefacts (Python harnesses, in-tree client tests)
ITEM_TOC.md       auto-regenerated flat table of every item
WORKLOG.md        sequential audit log
METHODOLOGY.md    audit loop and prompt templates
driver/           regen scripts, presubmit, runners-of-runners
tools/runners/    per-client EF fixture runners
vendor/           client source submodules + consensus-specs + EF tests
```

Submodule pins and fork target in [WORKLOG.md](WORKLOG.md) header.
