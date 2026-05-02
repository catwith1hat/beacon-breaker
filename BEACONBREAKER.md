# BeaconBreaker — Cross-Client Consensus Audit for the Beacon Chain

A methodology document for systematically finding consensus divergences across
Ethereum consensus-layer (CL) clients via source-to-source comparison and
fixture generation.

This document is the CL analog of the project that audits execution-layer (EL)
clients (geth, erigon, besu, nethermind, ethrex, revm/reth). The CL has
different surfaces, different reachability tiers, and different fixture
formats — but the same loop applies: pick a consensus-critical surface,
compare implementations across clients, hypothesize a divergence, verify in
source, generate a fixture if reachable.

---

## 1. Mission and scope

**Goal**: surface consensus-relevant differences across CL implementations
before they are exploited or cause a chain split. Produce a structured corpus
of findings (per-item README + worklog entries + fixtures) that can be turned
into bug reports, EF state tests, or proposer-side defense-in-depth proposals.

**Scope (in)**:
- State transition function (block processing, epoch processing).
- Fork choice (LMD-GHOST, Casper FFG, filter block tree).
- SSZ serialization, hashing (Merkleization), size limits.
- BLS signature verification, aggregation, subgroup checks, identity handling.
- Validator lifecycle: deposits, activations, exits, slashings, withdrawal
  credentials, consolidations.
- Sync committee selection, signature aggregation, rewards.
- Electra/Pectra-specific surfaces: MAX_EFFECTIVE_BALANCE=2048 ETH (EIP-7251),
  EL deposits (EIP-6110), EL triggered exits (EIP-7002), consolidations
  (EIP-7251), `0x02` withdrawal-credentials prefix.
- Block-header invariants (proposer index, slot, parent_root, state_root,
  body_root).
- Engine API CL→EL boundary (newPayload, forkchoiceUpdated): payload assembly,
  validation responses, and how each CL handles EL errors.

**Scope (out, but flag if encountered)**:
- P2P gossip rules (libp2p layer behavior). These are network-level and
  intersect with consensus only via "ignore vs reject vs disconnect" decisions.
- Builder API (mev-boost interface). Out of consensus per se but worth a
  parallel audit.
- Light client protocol divergences (different attack model).
- RPC API: `/eth/v1/beacon/...` endpoints.

---

## 2. The clients

Six (or more) production CL clients to audit. Use git submodules so versions
are pinned.

```bash
# .gitmodules
[submodule "prysm"]
    path = prysm
    url = https://github.com/prysmaticlabs/prysm
    branch = master
[submodule "lighthouse"]
    path = lighthouse
    url = https://github.com/sigp/lighthouse
    branch = unstable
[submodule "teku"]
    path = teku
    url = https://github.com/Consensys/teku
    branch = master
[submodule "nimbus"]
    path = nimbus
    url = https://github.com/status-im/nimbus-eth2
    branch = unstable
[submodule "lodestar"]
    path = lodestar
    url = https://github.com/ChainSafe/lodestar
    branch = unstable
[submodule "grandine"]
    path = grandine
    url = https://github.com/grandinetech/grandine
    branch = main
```

Languages span Go, Rust, Java, Nim, TypeScript — wider than EL (where we have
mostly Go/Rust/Java/C#/Rust). This makes source-to-source comparison harder
but the diversity catches more class-of-bug divergences.

Also clone the spec and reference fixtures:

```bash
[submodule "consensus-specs"]
    path = consensus-specs
    url = https://github.com/ethereum/consensus-specs
[submodule "consensus-spec-tests"]
    path = consensus-spec-tests
    url = https://github.com/ethereum/consensus-spec-tests
[submodule "beacon-APIs"]
    path = beacon-APIs
    url = https://github.com/ethereum/beacon-APIs
```

The Python pyspec at `consensus-specs/specs/<fork>/...` is the **reference
implementation** — any divergence between a client and pyspec is a finding by
definition. Cross-client divergence is a finding too even if all clients
diverge from pyspec the same way (because pyspec has its own subtle bugs).

---

## 3. Repository layout

```
beaconbreaker/
├── .gitmodules
├── BEACONBREAKER.md       # this file
├── METHODOLOGY.md          # short loop description
├── WORKLOG.md              # master log: prioritization list + per-item bodies
├── URGENT.md               # subagent-style work prompts (when fan-out helps)
│
├── prysm/                  # submodule
├── lighthouse/             # submodule
├── teku/                   # submodule
├── nimbus/                 # submodule
├── lodestar/               # submodule
├── grandine/               # submodule
├── consensus-specs/        # submodule
├── consensus-spec-tests/   # submodule
│
├── item1/
│   └── README.md           # finding details (template below)
├── item2/
│   ├── README.md
│   └── fixture/            # generated SSZ + YAML fixture for this finding
│       ├── pre.ssz
│       ├── post.ssz
│       ├── meta.yaml
│       └── README.md
├── item3/
│   └── README.md
│   ...
│
├── tools/
│   ├── ssz/                # SSZ encode/decode/hash helpers
│   ├── bls/                # BLS sign/verify/aggregate helpers
│   ├── pyspec/             # python venv with pyspec installed
│   └── runners/            # per-client harnesses to run a fixture
│       ├── prysm.sh
│       ├── lighthouse.sh
│       ├── teku.sh
│       ├── nimbus.sh
│       ├── lodestar.sh
│       └── grandine.sh
│
└── scripts/
    ├── run_fixture.sh      # run one fixture against all six clients
    ├── extract_item.sh     # bundle an item dir as a self-contained patch
    └── new_item.sh         # scaffold the next itemN/ directory
```

Each item's README lives in its own directory so that fixtures can be
co-located. The WORKLOG indexes findings; per-item READMEs hold the detail.

---

## 4. The audit loop

The findings loop is the same one used in EL audits, adapted to CL surfaces.

### 4.1 Pick the next item

Open `WORKLOG.md` and find the next prioritization entry. Prioritize:
- Recent fork changes (Pectra/Electra at time of writing): fresh code paths,
  smaller exposure window, more divergence likely.
- Surfaces touched by multiple EIPs (cross-cuts catch composition bugs).
- Anything that derives a hash, root, or signature (one-bit divergences are
  catastrophic).
- Code paths flagged as "untouched" in prior items' "adjacent untouched"
  sections.

### 4.2 Form a hypothesis

Write down:
- **What might diverge** — name the specific predicate, threshold, encoding,
  or formula that could differ.
- **Why it might diverge** — language idiom mismatch, library choice
  difference, ambiguous spec wording, off-by-one prone integer math.
- **What input would expose it** — describe a beacon block / attestation /
  state that would force the divergence.
- **Hypotheses H1..Hn** — concrete, falsifiable claims about what each client
  does.

A hypothesis like "all six handle `MAX_EFFECTIVE_BALANCE` consistently at the
Pectra fork" is a falsifiable claim — going through the source either confirms
or disconfirms it.

### 4.3 Source-to-source comparison

Read the relevant code in **all** clients. For each client, capture:
- File path and line range.
- Verbatim code excerpt (if short) or paraphrase.
- Any constants / enums / fork-gating predicates referenced.

Build a cross-reference table. Example shape:

| Client | Location | Constant value | Fork gating |
|---|---|---|---|
| prysm | `state-transition/...` | `MAX_EFFECTIVE_BALANCE_ELECTRA = 2048 ETH` | `params.IsElectra` |
| lighthouse | `consensus/types/...` | `2048 ETH` | `Fork::Electra` |
| teku | `spec/.../SpecConfigElectra.java` | `Wei.fromEth(2048)` | spec config swap |
| nimbus | `consensus/.../validator_helpers.nim` | `2048.GweiToEth` | post-Electra branch |
| lodestar | `params/.../electra.ts` | `2048n * 10n**9n` | fork gating in spec table |
| grandine | `types/electra/...` | `2048 * GWEI_PER_ETH` | electra fork match |

If the table is uniform → "no-divergence-pending-fuzzing" finding (still worth
a fixture if reachable). If non-uniform → divergence finding, classify by
reachability.

### 4.4 Reachability classification

CL reachability tiers (analogous to A/D/M from EL audits):

- **C (canonical)**: a divergence reachable through normal beacon chain
  operation — well-formed blocks produced by canonical proposers, valid
  attestations from honest validators. *Highest severity*: a real chain split
  is one such input away.
- **A (adversarial)**: requires a malicious actor with proposer rights or
  aggregator selection. The adversary still has to follow consensus rules to
  some extent, but can craft messages within their allotted authority (e.g.,
  proposer can include any valid txs in any order; can choose to skip).
- **F (forensic)**: requires post-finalization replay of a synthetic block
  that can never appear on the canonical chain (e.g., a block with
  inconsistent parent_root that no honest proposer would ever sign). Useful
  for state-test corpora but cannot cause a live chain split.
- **M (mainnet-impossible)**: prevented by network-layer or beacon-API rules
  before reaching state transition. Examples: malformed SSZ rejected at
  gossip ingress; signatures invalid before block deserializes.

When in doubt, mark **F** and elevate to **A** if you find a way an adversary
can reach the input.

### 4.5 Fixture generation

For any item with reachability C, A, or F, produce a fixture:

- **State and block**: SSZ-encode pre-state, block(s), and expected post-state
  using pyspec or a small Python/Rust helper.
- **Format**: align with EF consensus-spec-tests layout —
  `pre.ssz_snappy`, `block_<n>.ssz_snappy`, `post.ssz_snappy`, `meta.yaml`.
  Use the EF format so fixtures can be dropped into the official suite later.
- **Run against all six**: `./scripts/run_fixture.sh itemN/fixture/` should
  emit a per-client pass/fail line.
- **Document the result** in the item README under a "Fixture" section.

If your hypothesis was "all six agree", a passing fixture corroborates it.
If your hypothesis was "client X diverges", a failing-on-X / passing-on-rest
fixture is the bug report.

For inputs that aren't expressible as a state-test (e.g., fork-choice
divergences requiring multiple competing chains), use the
`fork_choice/` test format from consensus-spec-tests instead.

### 4.6 Document and commit

Per-item README structure (template below). Update `WORKLOG.md` with both:
- A one-line entry in the prioritization list (top of file): a candidate
  before audit, a confirmed/disconfirmed finding after.
- A per-item body section (bottom of file): status, builds-on, finding
  paragraph (~3-6 sentences with concrete file:line citations), adjacent
  untouched paths.

Commit each finding separately. One item per commit so history is bisectable
and bug reports can be cherry-picked.

---

## 5. Reachability examples

To calibrate: a few hypothetical CL findings and their tier.

| Finding | Tier | Why |
|---|---|---|
| Two clients compute different rewards for the same attestation by 1 gwei | **C** | Honest proposer can include the attestation; state root diverges immediately |
| Slashing penalty calculation differs at exactly the validator-set-size boundary that triggers EIP-7251 fork-choice change | **A** | Adversary needs to be the proposer at the exact slot; can be arranged |
| State transition rejects a block where `slot == STATE_ROOTS_LIMIT - 1` (off-by-one in array index) | **C** | Hits during normal operation at the limit slot |
| BLS aggregate signature accepts signatures from a non-prime-order subgroup | **A** | Adversary needs to construct invalid pubkey set; reachable via deposit |
| SSZ deserializer accepts overlong-encoded uint64 (non-canonical) | **F** | Prevented by gossip-layer validators in canonical flow |
| Fork-choice tiebreaker uses different ordering when two blocks have identical weight | **A** | Equivocating proposer can produce two blocks; honest validators see both |

A divergence at C is a critical pre-merge-style bug. A divergence at A is
worth a paper. A divergence at F still warrants a fix (defense-in-depth) and
an EF state test. M findings are documentation-only.

---

## 6. Audit surfaces (priority-ordered)

Use this list as a starting backlog. Each entry is a candidate item.

### 6.1 State transition (highest signal)

1. **Per-slot processing**: `process_slot`, advancing state without a block.
   - State-root caching (`historical_summaries`, `state_roots`).
   - Slashings counter per epoch.
2. **Per-block processing**:
   - `process_randao` reveal verification + mixin.
   - `process_eth1_data` voting period transitions at fork boundaries.
   - `process_proposer_slashing` — duplicate-message detection,
     penalty calculation, withdrawable_epoch update.
   - `process_attester_slashing` — `is_slashable_attestation_data`,
     intersection of attesting indices.
   - `process_attestation` — committee membership, signature, inclusion delay.
   - `process_deposit` (EIP-6110): deposit-tree-root verification, signature
     check skipped for top-up vs new validator.
   - `process_voluntary_exit` — churn limit, current_epoch checks.
   - `process_bls_to_execution_change` (Capella).
   - `process_withdrawal_request` (EIP-7002, Pectra) — request validity,
     fee scaling, queue position.
   - `process_consolidation_request` (EIP-7251, Pectra) — source/target
     validation, withdrawal-credentials prefix check.
   - `process_execution_payload` — payload-header consistency, EL response
     interpretation.
3. **Per-epoch processing**:
   - `process_justification_and_finalization` — bit-arithmetic on the
     `justification_bits` field.
   - `process_inactivity_updates` — per-validator inactivity score adjustment.
   - `process_rewards_and_penalties` — flag-based attestation rewards
     (Altair+), inactivity leak penalty, head/target/source flags.
   - `process_registry_updates` — activation queue, exit queue, churn limit.
   - `process_slashings` — proportional slashing factor (3x post-Bellatrix),
     `MAX_SLASHABLE_BALANCE_INCREMENT` boundary.
   - `process_eth1_data_reset`.
   - `process_effective_balance_updates` — hysteresis quanta.
   - `process_slashings_reset`.
   - `process_randao_mixes_reset`.
   - `process_historical_summaries_update` (Capella+).
   - `process_participation_flag_updates`.
   - `process_sync_committee_updates` — every-period rotation.
   - `process_pending_consolidations` (EIP-7251).
   - `process_pending_deposits` (EIP-6110, post-Pectra).

### 6.2 Fork choice

4. **LMD-GHOST**: latest-message rule, vote weights from balances.
5. **Casper FFG**: justification + finalization; conflict resolution between
   LMD-GHOST and FFG.
6. **`filter_block_tree`** — viable head determination.
7. **Equivocation handling** — proposer slashing at the fork-choice level
   (proposer score boost behavior under equivocation).
8. **Proposer score boost** — the 40% rule; behavior at slot boundary; reorg
   resistance.
9. **Reorg detection and unrealized justification**.
10. **Pull-up tip** behavior (post-Capella).

### 6.3 SSZ

11. **Variable-size container offsets** — overlapping ranges, non-monotonic
    offsets, offset pointing past end.
12. **List length cap** — exactly-N-element lists, N+1 rejection, empty-list
    handling.
13. **Bitlist / Bitvector** — last-bit-set sentinel, unset trailing bits in
    bitvector, length-encoding edge cases.
14. **Merkleization** — chunk padding for non-power-of-2 lists;
    `mix_in_length` correctness.
15. **Hash-tree-root** of containers with optional fields (Optional[X]).
16. **Stable hashing of historical types** at fork boundaries.

### 6.4 BLS

17. **Subgroup membership** for G1 and G2 — pubkey and signature.
18. **Identity (point-at-infinity)** handling — pubkey, signature.
19. **Aggregate of empty set** — must reject.
20. **`fast_aggregate_verify`** — same `domain` across signatures; pubkey
    aggregation order independence.
21. **`hash_to_point`** parameters — DST per fork (`BLS_SIG_BLS_PROOF_OF_POSSESSION`).
22. **Library family**: BLST (most), gnark-crypto, custom Nim/Go bindings —
    cross-library parity.

### 6.5 Validator lifecycle

23. **Activation queue ordering** at the same activation_eligibility_epoch.
24. **Exit queue ordering** with simultaneous exits at the same epoch.
25. **Churn limit calculation** at validator-set-size step boundaries
    (Pectra changes the formula — likely divergence vector).
26. **Withdrawal credentials transitions** — `0x00` → `0x01` (Capella) →
    `0x02` (Pectra). Validator can only transition forward; transitions are
    one-way.
27. **`MAX_EFFECTIVE_BALANCE`** application at hysteresis boundaries —
    32 ETH old, 2048 ETH Pectra. Credit and debit asymmetry.
28. **Pending deposits** queue (EIP-6110 + Pectra) — ordering, max-deposits
    per slot, queue prioritization vs activation eligibility.
29. **Consolidation request processing** (EIP-7251) — source not slashed,
    target valid, withdrawal credentials match, balance transfer math.
30. **Execution-layer triggered withdrawals** (EIP-7002) — fee escalation
    formula, request queue caps, validation of source.

### 6.6 Sync committee

31. **Sync committee selection** — period rotation; randao seed mixing.
32. **Sync committee message verification** — slot N attests to slot N-1
    head; signature aggregation across participants.
33. **Sync committee rewards** — proportional to participation; relationship
    to attestation rewards.

### 6.7 Engine API CL→EL boundary

34. **`engine_newPayloadV*`**: validation of payload-vs-header consistency.
35. **`engine_forkchoiceUpdatedV*`**: head/safe/finalized consistency
    checks; payload attribute generation.
36. **EL error response interpretation**: `INVALID_BLOCK_HASH` vs `INVALID`
    vs `SYNCING` — which response causes the CL to mark the block invalid vs
    to defer.
37. **Payload assembly** when proposer in this slot — local builder vs
    mev-boost flow; default-on-fail behavior.
38. **Cancun→Prague fields**: `excessBlobGas`, `blobGasUsed`,
    `requestsHash` propagation through the API.

### 6.8 Fork-boundary specifics

39. **Pre-Pectra → Pectra transition**: exact slot of activation; state
    upgrade function correctness; new-field initialization defaults.
40. **EL deposits backstop** at Pectra activation: how the legacy 1559-based
    deposit contract fades out; the genesis-of-history.

### 6.9 Network-adjacent (fuzz only)

41. **BeaconBlocksByRange / BeaconBlocksByRoot** response framing —
    consensus-relevant only when a malformed response causes re-sync stalls.
42. **Status message** consistency at fork boundaries.

---

## 7. Per-item README template

Use this as the contents of `itemN/README.md`. Match the structure to
existing items so future readers can scan headings.

```markdown
# Item #N — <One-line title at the audit fork target>

**Status:** <no-divergence-pending-fuzzing | divergence-confirmed | dormant-divergence-on-X | mainnet-impossible> — audited <YYYY-MM-DD>. **<Hypothesis disconfirmed / confirmed / partially confirmed>.**

**Builds on:** items #X (subject), #Y (subject).

**<Fork>-active.** <One-sentence describe why this matters for consensus root.>

## Question

<2-4 paragraphs describing the surface, the spec, the cross-cut, and the
exact predicate / value / encoding under audit. Cite sections of the spec
or relevant EIPs.>

The hypothesis: *<one-sentence formal hypothesis about what could diverge>.*

**Consensus relevance**: <one paragraph explaining the bad outcome of a divergence.>

## Hypotheses

- **H1.** <Falsifiable claim 1.>
- **H2.** <Falsifiable claim 2.>
- ...

## Findings

H1, H2, ... <satisfied | unsatisfied>. **<No divergence | divergence on Hk>.**

### prysm (`<package>/<file.go>:<lines>`)
<verbatim-or-paraphrased excerpt + ✓/✗ per hypothesis>

### lighthouse (`<crate>/<file.rs>:<lines>`)
<...>

### teku (`<package>/<File.java>:<lines>`)
<...>

### nimbus (`<package>/<file.nim>:<lines>`)
<...>

### lodestar (`<package>/<file.ts>:<lines>`)
<...>

### grandine (`<crate>/<file.rs>:<lines>`)
<...>

## Cross-reference table

| Client | Location | <key behavior> | <key constant> |
|---|---|---|---|
| prysm | ... | ... | ... |
| lighthouse | ... | ... | ... |
...

## Cross-cuts

### with #X (<topic>)
<paragraph explaining how this audit composes with item #X>

## Fixture

`fixture/`: <what the fixture exercises; expected per-client outcomes>.

## Fuzzing vectors

### T1 — Mainline canonical
- **T1.1 (priority — <name>).** <description>. Expected: <outcome>.

### T2 — Adversarial probes
- **T2.1 (priority — <name>).** <description>.

## Conclusion

<Status one-line restated.> <2-3 sentences on what was confirmed or
disconfirmed and any code-change recommendation (or "no code changes
warranted").>

## Adjacent untouched <fork>-active consensus paths

1. **<Path>** — <one-line note on what's untouched and why it's worth a
   future item.>
2. ...
```

---

## 8. Worklog template

Single `WORKLOG.md` indexes everything. Top half: prioritization list
(forward-looking candidates). Bottom half: per-item bodies (audited
findings).

```markdown
# BeaconBreaker — Work Log

## Goal

Cross-client audit of CL implementations at the <Fork> fork target on
mainnet, finding consensus-relevant divergences and producing fixtures.

## Clients & Versions

| Client | Repo | Pinned commit |
|---|---|---|
| prysm | github.com/prysmaticlabs/prysm | <sha> |
| lighthouse | github.com/sigp/lighthouse | <sha> |
| teku | github.com/Consensys/teku | <sha> |
| nimbus | github.com/status-im/nimbus-eth2 | <sha> |
| lodestar | github.com/ChainSafe/lodestar | <sha> |
| grandine | github.com/grandinetech/grandine | <sha> |

## Fork Target

<Fork name> (e.g., Electra/Pectra). Active EIPs: <list>.

## Areas Investigated

<Numbered prioritization list. Each entry one line.>

1. **<Title>** (Pectra-active, <surface>) → item #1 (<status>; <one-line
   finding>).
2. ...

## Speculative Unexplored Areas (<date>)

<Things that look interesting but haven't been audited yet — preserve as
candidates for future items.>

### Prioritization

50. <Forward-looking candidate>.
51. ...

These are candidates for items #N onward, not findings.

## Findings (per-item bodies)

### 1. <Title>

**Status:** ... (See item1/README.md for full body.)

<3-6 sentences summarizing finding, files, conclusion, cross-cuts.>

**Adjacent untouched <fork>-active**: <list>.

See [item1/README.md](item1/README.md).

### 2. <Title>
...
```

---

## 9. Cross-cuts and architectural composition

Many findings come from **composing** features that the spec defines
independently. Examples (CL):

- EIP-7251 (consolidation) × EIP-7002 (EL exit): a validator with a
  consolidation pending and an EL exit submitted in the same block — which
  takes precedence?
- EIP-6110 (deposits) × `MAX_EFFECTIVE_BALANCE_ELECTRA` × hysteresis: a
  deposit that pushes balance from 31.5 ETH to 33 ETH at exactly the
  hysteresis quantum.
- LMD-GHOST × `proposer_score_boost`: an equivocating proposer that races
  two blocks, both within the boost window.
- Sync committee × randao at fork boundary: the sync committee at slot K of
  the fork-activation epoch.
- Fork choice × Engine API: payload validation lag causes EL to return
  `SYNCING`; how does each CL handle the deferred-validation contract?

When you find a clean uniform implementation, write a "no-divergence" item
**including** a cross-cut analysis. Disconfirmed hypotheses that document
correct composition are valuable — they constrain future regressions.

---

## 10. Tooling

Recommended tooling stack:

- **pyspec** (`consensus-specs/pysetup.py`): reference Python implementation
  of the spec; serves as fixture generator and oracle.
  ```bash
  cd consensus-specs && python -m venv .venv && . .venv/bin/activate
  pip install -e .[lint,test]
  ```
- **ssz CLI** (e.g., from lighthouse's `lcli` or NimbusEth2's
  `ssz_recompile`): SSZ encode/decode/hash from the command line.
- **BLS CLI**: BLST has `blst_dump`/`blst_test`; or use Python's
  `py_ecc.bls`.
- **Diff helpers**: `delta` for cross-client output diffs;
  `state_summary.py` to print first 50 fields of two BeaconStates side by
  side.
- **Per-client harness**: a tiny script per client that takes
  `pre.ssz_snappy + block.ssz_snappy + post.ssz_snappy` and runs the state
  transition, comparing the resulting state-root with the expected one.
  Each client has different invocation; budget 30-60 min per client to
  build the harness.

A single `scripts/run_fixture.sh itemN/fixture/` invocation should run the
fixture against all six and report:

```
prysm:      PASS  (state_root match)
lighthouse: PASS
teku:       FAIL  (state_root mismatch: 0x... vs 0x...)
nimbus:     PASS
lodestar:   PASS
grandine:   PASS
```

When all six PASS or all six FAIL the same way, the fixture corroborates
uniform behavior. When the split is k-vs-(6-k), you have a reproducer.

---

## 11. The "weird corner" mindset

After auditing standard surfaces, divergences cluster at:

- **Boundary conditions**: 0, MAX-1, MAX, MAX+1, exactly the threshold,
  one above, one below.
- **Empty inputs**: empty attestation list, empty deposits, no validators,
  zero balance.
- **Optional fields**: pre/post fork-boundary handling of new fields;
  unset Optional[X] in containers.
- **Cross-fork transitions**: behavior at the exact slot a fork activates;
  state upgrade function behavior on edge-case pre-states.
- **Off-by-one in epoch math**: `current_epoch` vs `previous_epoch` boundary;
  inclusion delays at slot 0 of an epoch.
- **Integer overflow/underflow**: u64 boundaries in gwei (gwei-overflow at
  `2^64 / 1e9 ≈ 18.4 billion ETH` is unreachable, but intermediate values in
  reward formulas can overflow earlier).
- **Hash collisions in unkeyed sets**: validator-set membership tested by
  index vs by pubkey hash.
- **Library substitution**: BLST vs gnark-crypto vs custom; SSZ encoders
  with different alignment assumptions.

When you've audited the listed surfaces and want fresh material, scan the
existing items' "Adjacent untouched" sections — that's where future material
accumulates.

---

## 12. Output artifacts

For each finding, the durable artifacts are:

1. `itemN/README.md` — the finding write-up.
2. `itemN/fixture/*` — generated SSZ + meta.yaml fixture (if reachable).
3. `WORKLOG.md` entries — prioritization line + per-item body.
4. A git commit per item with a descriptive message in the form:
   ```
   Add item #N: <one-line title>

   <2-4 sentences summarizing the finding, including which clients
   diverge (if any), what the cross-cut covers, and the recommended
   action (none vs file bug vs propose spec clarification).>

   Hypothesis <confirmed | disconfirmed>.
   ```

When you accumulate ~5-10 high-severity findings, file them as bug reports
on the affected client repos and/or as PRs against
consensus-spec-tests.

---

## 13. The driver prompt

When running this loop with an AI assistant in a long-running session, a
prompt like:

> Continue with the next open highest priority item. Fully research it,
> make notes, especially for potentially other consensus critical paths.
> Then git commit your findings. Focus on consensus-critical items for the
> latest fork.

— is sufficient context to drive ~50+ items without micromanagement. After
direct surfaces saturate, switch to:

> I have another agent working on the findings. Please resume the audit to
> produce more findings. Try to combine techniques. Look in weird corners.
> Get creative. Target is still <fork> on mainnet.

This pivots from base-surface audits to cross-cut compositions, which tend
to surface more interesting findings when the standalone surfaces are clean.

---

## 14. Out-of-scope but worth flagging

If during an audit you encounter:

- A spec ambiguity (multiple defensible readings of pyspec): write up as a
  "spec-ambiguity" item even if all six clients happen to agree on one
  reading. Future re-audits at a later spec revision may surface a
  divergence.
- A proposer-side optimization that affects observable timing (e.g., when
  an attestation gets included): out of strict consensus but relevant for
  MEV / liveness. Flag in WORKLOG, not as a numbered item.
- A network-layer message that, if accepted, causes a denial-of-service:
  flag separately. DOS surface is real but distinct from chain-split risk.

Keep these in a `OUT_OF_SCOPE.md` (separate from WORKLOG) so the main
worklog stays focused on chain-split risk.

---

## 15. Calibration: what "good" looks like

After ~50 items, a healthy worklog should have:

- ~3-5 confirmed cross-client divergences (any reachability).
- ~10-15 dormant-divergence-on-malformed findings (F-tier).
- ~30-40 no-divergence findings, each with a fixture and cross-cut analysis
  that constrains future regressions.
- A "speculative unexplored areas" section with another 30-50 candidates.

If you reach 50 items with zero divergences found, recheck calibration:
either the surface is exceptionally clean (rare for a fresh fork) or the
audit isn't probing weird corners. Try cross-cut audits, fork-boundary
probes, and adversarial-input fixtures.

---

End of `BEACONBREAKER.md`. Copy this file as the seed of a new project,
populate `.gitmodules` with the six (or more) CL clients, scaffold
`item1/README.md` with the template above, and start the loop.
