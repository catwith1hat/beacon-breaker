# AGENTS.md — Working in BeaconBreaker

This repository is a cross-client consensus audit project for Ethereum
consensus-layer (CL) clients. Read `BEACONBREAKER.md` first — it is the full
methodology document. This file is the short version for AI agents driving
the loop.

## What this project is

A structured corpus of consensus-layer findings produced by source-to-source
comparison across six (or more) production CL clients (prysm, lighthouse,
teku, nimbus, lodestar, grandine), with the Python pyspec as the reference
oracle. Each finding lives in `itemN/` with its own README and (when
reachable) an SSZ fixture.

The fork target at the time of writing is **Electra/Pectra** on mainnet.

## The loop, in one paragraph

Open `WORKLOG.md`, pick the next prioritization candidate, form a
falsifiable hypothesis about a possible cross-client divergence, read the
relevant code in **all** clients (file:line citations are mandatory), build
a cross-reference table, classify reachability (C / A / F / M), generate a
fixture if reachability is C/A/F, document under `itemN/README.md` using
the template in §7 of `BEACONBREAKER.md`, update `WORKLOG.md` (both the
prioritization line and the per-item body), and commit. One item per commit.

## Hard rules for items

- **All six clients.** Every audit must inspect every client. "I checked four
  and they agree" is not an item — finish the table.
- **Cite file:line.** Every claim about client behavior must point to a
  specific path and line range in the submodule. Paraphrases are allowed for
  long blocks; verbatim is required for the load-bearing predicate.
- **Pyspec is the oracle.** When a client diverges from pyspec, that's a
  finding even if no other client diverges. When all clients agree but
  diverge from pyspec, that's also a finding.
- **Reachability tier is mandatory.** Every item declares C / A / F / M with
  one sentence of justification. When in doubt, mark **F** and elevate.
- **Fixtures use the EF format.** `pre.ssz_snappy`, `block_<n>.ssz_snappy`,
  `post.ssz_snappy`, `meta.yaml` — so they can be upstreamed to
  consensus-spec-tests later.
- **One item per commit.** Bisectable history. Commit message format is in
  §12 of `BEACONBREAKER.md`.

## Where things live

- `BEACONBREAKER.md` — full methodology. Read this once.
- `METHODOLOGY.md` — short loop description (the "driver prompt" form).
- `WORKLOG.md` — master log: prioritization list (top) + per-item bodies (bottom).
- `URGENT.md` — subagent fan-out prompts for parallelizable batches.
- `OUT_OF_SCOPE.md` — spec ambiguities, MEV/timing observations,
  network-layer DOS surfaces — anything flagged but not chain-split risk.
- `itemN/README.md` — finding write-ups (template in §7 of `BEACONBREAKER.md`).
- `itemN/fixture/` — co-located SSZ fixtures for that finding.
- `tools/` — pyspec venv, ssz/bls helpers, per-client harness scripts.
- `scripts/run_fixture.sh` — run a fixture against all six clients.
- `scripts/new_item.sh` — scaffold the next `itemN/` directory.
- `scripts/extract_item.sh` — bundle an item directory as a self-contained patch.
- `prysm/`, `lighthouse/`, `teku/`, `nimbus/`, `lodestar/`, `grandine/` —
  client submodules (pinned).
- `consensus-specs/` — spec + pyspec reference implementation.
- `consensus-spec-tests/` — EF reference fixtures (shallow clone; large).
- `beacon-APIs/` — beacon-API spec (out of scope but useful context).

## Working in submodules

The client submodules are pinned. Do **not** pull or rebase them as part of
an audit — the pinned commit defines what "this client diverges" means for a
given finding. If you need to bump a submodule, do it in a separate commit
and re-run any affected fixtures.

When citing code, use the path inside the submodule, e.g.
`prysm/beacon-chain/state/state-native/setters_validator.go:142-168`.

## Working with pyspec

`tools/pyspec/` should hold a Python venv with the spec installed in editable
mode (`pip install -e consensus-specs[lint,test]`). Import paths look like
`from eth2spec.electra import mainnet as spec`. Use pyspec to:
- Generate fixtures from a (pre-state, block) pair.
- Cross-check a hypothesis against the canonical Python implementation.
- Trace the exact predicate sequence in `process_*` functions.

## Reachability tiers (cheat sheet)

- **C (canonical)** — reachable via well-formed blocks from honest
  proposers. Chain-split risk. Highest severity.
- **A (adversarial)** — reachable by an actor with proposer rights or
  aggregator selection, acting within their authority.
- **F (forensic)** — requires a synthetic block that no honest proposer
  would sign. Defense-in-depth and EF-state-test material; cannot split a
  live chain.
- **M (mainnet-impossible)** — gossip / beacon-API rejects before state
  transition sees it. Documentation-only.

## Style

- Status line in every item README is mandatory and matches the template.
- Hypotheses are numbered H1..Hn and explicitly marked satisfied /
  unsatisfied in the Findings section.
- Cross-reference table compares **all** clients on the same axes.
- "Adjacent untouched paths" section is mandatory — it feeds the next
  iteration's prioritization list.

## Common pitfalls

- Reading only one or two clients then declaring uniform behavior — finish
  the table.
- Conflating spec ambiguity with implementation divergence — a spec
  ambiguity is its own item type (see `OUT_OF_SCOPE.md`).
- Forgetting fork-gating: a constant that exists post-Electra may have a
  pre-Electra counterpart with a different value. Both matter.
- Citing line numbers without quoting the predicate — line numbers shift on
  rebase; the verbatim predicate is durable.
- Generating a fixture and not running it against all six clients — the
  cross-client run **is** the experiment.

## Driver prompts

Two prompts drive the loop, depending on phase:

**Phase 1 (direct surfaces):**
> Continue with the next open highest priority item. Fully research it,
> make notes, especially for potentially other consensus critical paths.
> Then git commit your findings. Focus on consensus-critical items for the
> latest fork.

**Phase 2 (cross-cuts and weird corners, after ~30+ items):**
> I have another agent working on the findings. Please resume the audit to
> produce more findings. Try to combine techniques. Look in weird corners.
> Get creative. Target is still Electra/Pectra on mainnet.
