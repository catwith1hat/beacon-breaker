# Methodology — reproducing the beacon-breaker cross-client audit

This file captures the **prompts** and **process** that drive the audit, so a fresh
operator (or a fresh agent session) can pick up where the trail stopped and produce
artifacts in the same shape as items #30–#56.

The audit itself is described in [BEACONBREAKER.md](./BEACONBREAKER.md) (mission,
scope, reachability tiers, audit surfaces) and [AGENTS.md](./AGENTS.md) (working
conventions, hard rules, common pitfalls). This file documents how the work is
*driven* — the prompt templates, the repository conventions they assume, and the
human-in-the-loop pacing.

Mirrors evm-breaker's `METHODOLOGY.md` (sister project at the EL surface). Where
beacon-breaker's conventions diverge from that template, the local convention
wins (different clients, different fixture format, different track taxonomy).

---

## 0. Repository assumptions

Before any prompt fires, the working tree must contain:

- All six client trees and the three spec/fixture submodules under `vendor/`:
  `vendor/prysm/`, `vendor/lighthouse/`, `vendor/teku/`, `vendor/nimbus/`,
  `vendor/lodestar/`, `vendor/grandine/`, plus `vendor/consensus-specs/`,
  `vendor/consensus-spec-tests/`, `vendor/beacon-APIs/`. After a fresh clone,
  `git submodule sync && git submodule update --init` re-attaches the worktrees.
- `WORKLOG.md` as the single index of items, with a prioritization section listing
  audit tracks (currently A through G + the Fulu-NEW open queue) and per-item
  bodies under `## Findings (per-item bodies)`.
- `BEACONBREAKER.md` describing the mission, reachability classes (C/A/F/M),
  status vocabulary, audit-surface checklist, and the per-item README template.
- `AGENTS.md` describing hard rules, working conventions, and common pitfalls.
- One `items/NNN/` directory per finalized audit (3-digit zero-padded), each with
  a `README.md`.
- A loaded session memory: the agent should have read `WORKLOG.md` and skimmed the
  recent `items/NNN/README.md` files for current style before starting.

If any of those are missing, run the bootstrap prompt in §6 first.

---

## 1. The driver prompt (recurring loop)

The single highest-leverage prompt in this project is:

> **Continue with the next most promising item. Research it using source code
> review and comparison between all 6 clients, note your findings, and also
> include future research ideas you come across. Then commit to WORKLOG.md and
> a separate item README.**

Issued verbatim, once per item. It assumes the agent will:

1. Read `WORKLOG.md` — specifically the prioritization section and the most
   recent `## Findings (per-item bodies)` entries — to identify a candidate
   surface. Look at the prior item's "Future research ideas" / "Adjacent
   untouched" sections; that's where the queue lives in beacon-breaker (instead
   of an explicit `S<x>.<y>` taxonomy).
2. Allocate a fresh item number (next integer after the last `### N.` block in
   WORKLOG.md).
3. Audit all six clients per the §3 audit template.
4. Write `items/NNN/README.md` per the §4 README template.
5. Update WORKLOG.md: add a new `### N. <title>` block under
   `## Findings (per-item bodies)` and the corresponding line in the
   prioritization list.
6. Commit only `items/NNN/README.md` and `WORKLOG.md` with the message format in §7.

After commit, the agent stops and waits. No "do the next one too" — pacing is
human-controlled to allow review and to keep blast radius bounded.

### When to use

Whenever the prior item surfaced new follow-up candidates. Items #49–#56 were
each produced by exactly one issuance of this prompt.

### When NOT to use

- When the prioritization queue / future-research lists are empty. Use the
  scope-discovery prompt (§8) instead.
- When the user wants to override priority (use the explicit prompt §2).
- When fixing a defect in a previously committed item (use the rework prompt §9).

---

## 2. The explicit-scope prompt

When the user wants a specific scope rather than next-in-list:

> **Audit `<EIP / spec function / boundary>` across all six clients. Produce
> `items/NNN/README.md` and a `WORKLOG.md` stub. Commit when done.**

Substitute the scope, e.g. "EIP-7805 inclusion-list signing domain" or
"PartialDataColumnSidecar SSZ schema cross-check."

The agent picks the next free `N` and follows the same template as §1.

---

## 3. The per-item audit template (what the agent does internally)

Every item follows this skeleton.

### 3.1 Surface enumeration

Read `BEACONBREAKER.md §6` (audit surfaces, priority-ordered). For the chosen
scope, write down 5–10 *surfaces* — discrete points where two clients could
differ. Examples drawn from the existing corpus:

- **Constants**: `MAX_REQUEST_BLOCKS_DENEB`, `NUMBER_OF_COLUMNS`,
  `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH`, fork epochs, churn-limit quotients.
- **State-transition predicates**: validator-active-at-epoch, `is_eligible_for_*`,
  `process_pending_*` queue-drain ordering, `compute_balance_weighted_selection`.
- **Encodings**: SSZ container field naming (`columns` vs `indices`), ENR
  variable-length BE vs SSZ uint8 (Pattern W), JSON snake_case vs camelCase
  (Pattern AA).
- **Hash domains**: `compute_signing_root`, `compute_fork_data_root`, BPO
  `compute_fork_digest` post-Fulu XOR layout.
- **Validation orderings**: gossip-time vs fork-choice-time DA verification;
  partial-verify (`partially_verify_execution_payload`) vs full.
- **Fork dispatch idiom**: prysm runtime version check, lighthouse superstruct
  enum, teku subclass override, nimbus type-union compile-time, lodestar numeric
  `ForkSeq`, grandine module-namespace.
- **Library substitutions**: c-kzg-4844 vs rust-kzg, BLST wrapper variants.
- **Custody / sampling boundaries**: `CUSTODY_REQUIREMENT`, `SAMPLES_PER_SLOT`,
  `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS`.

Cast each surface as a hypothesis `H1, H2, …` of the form "all six clients do X."
The hit pattern to look for is **5-of-6 agreement with one dissenter** — that's
where the corpus's most actionable findings have lived (Pattern W nimbus uint8,
Pattern T lodestar empty-set, Pattern Y lighthouse Gloas V5, the teku ByRoot
deprecation gap).

### 3.2 Per-client read

For each surface, open the relevant file in **all six** client trees under
`vendor/<client>/`. Quote the relevant code with `file:line` anchors.

Bash one-liners to navigate each tree quickly:

```bash
# Grep across one client's source for a constant or symbol
grep -rn "compute_max_request_data_column_sidecars" vendor/prysm/

# Find the EIP-7594 implementation by file naming convention
find vendor/ -type f \( -name "*peerdas*" -o -name "*data_column*" \) | head
```

Use the `Read` and `Grep` tools (or `Agent` with `subagent_type=Explore` for
multi-round searches across all six trees in parallel). Per `AGENTS.md`,
**never** rely on secondary sources (blog posts, summaries, EIP text alone).
Always read source — and verify the agent's report (an Explore agent can
mis-classify; see §11 failure modes).

### 3.3 Cross-reference table

After per-client findings, summarize as a markdown table with columns =
`Hypothesis | prysm | lighthouse | teku | nimbus | lodestar | grandine` (or
`Client | Source | Strategy | …` for compare-by-strategy items). A glance at the
table should reveal which surfaces agreed and which dissented.

### 3.4 Fixture / fuzzing vectors

Per `BEACONBREAKER.md §7`, every audit produces fixture vectors that are
**executable PoC specifications**, not prose. The unit is an EF state-test
fixture: `pre.ssz_snappy`, `block_<n>.ssz_snappy` (or operation), `post.ssz_snappy`,
`meta.yaml`. Run via `scripts/run_fixture.sh items/NNN/fixture/` against the
four wired runners (prysm, lighthouse, lodestar, grandine); teku and nimbus are
exercised through their internal CI on the same fixture corpus.

Group the vectors:

- `T1.x` — mainline / canonical (honest-proposer reachable; class **C**).
- `T2.x` — adversarial within authority (class **A** — equivocation, malformed
  attestations within signing authority, etc.).
- `T3.x` — forensic / synthetic (class **F** — gossip-rejected inputs, reorg
  edge cases, pre-existing EF coverage gaps).
- `N1..N4` — negative controls (cases that must NOT trigger the surface).

Mark one or two as **priority** based on which vector is most likely to surface
a real-world divergence. For Fulu items, the priority is often the on-network
mainnet trace at a specific BPO transition or fork-choice tie.

When fixture generation isn't yet wired (the corpus has many of these — Fulu
state-transition fixture categories are pending in the harness), declare
`Status: no-divergence-pending-fixture-run` and document the candidate vector
specs anyway. The next round of harness wiring picks them up.

### 3.5 Conclusion

End with: `Status:` (per `BEACONBREAKER.md §7` vocabulary —
`no-divergence-pending-fuzzing`, `no-divergence-pending-fixture-run`,
`divergence-confirmed`, `dormant-divergence-on-X`, `mainnet-impossible`),
reachability class (C/A/F/M per `BEACONBREAKER.md §5`), and either
`No code changes warranted.` or specific bug-fix candidates if found.

---

## 4. README template (`items/NNN/README.md`)

Use the layout in `BEACONBREAKER.md §7`. The shared shape across items #49–#56:

```markdown
# Item NNN — <one-line title at the audit fork target>

**Status:** <status> — audited YYYY-MM-DD. <One-line classification:
Nth Fulu-NEW item, Mth PeerDAS audit, etc.>

<2–3 sentence framing: spec citation, why this surface might diverge,
which prior item(s) it cross-cuts.>

**Spec definition** (`vendor/consensus-specs/specs/<fork>/<file>.md`):
\```python
<spec snippet>
\```

**Major findings**:
1. <bullet>
2. <bullet>
...

## Scope

In: <surfaces audited>.
Out: <surfaces deferred to future items>.

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | All 6 ... | ✅ all 6 | ... |
| H2 | ... | ⚠️ 5 of 6; <dissenter> ... | ... |

## Per-client cross-reference

| Client | <field 1> | <field 2> | ... |
|---|---|---|---|
| **prysm** | ... | ... | ... |
| **lighthouse** | ... | ... | ... |
| **teku** | ... | ... | ... |
| **nimbus** | ... | ... | ... |
| **lodestar** | ... | ... | ... |
| **grandine** | ... | ... | ... |

## Notable per-client findings

### CRITICAL — <dissenter highlight>
<file:line + quoted code + observation>

### <other client> <subtitle>
...

## Cross-cut chain

This audit closes <surface>:
- **Item #M** (<surface>): <relation>
- **Item #28 NEW Pattern <X> candidate**: <description>
...

## Adjacent untouched <fork>-active

- <future audit candidate>
- <future audit candidate>

## Future research items

1. <item description>
2. ...

## Summary

<one-paragraph synthesis>
```

Length: 200–400 lines. Items #49–#56 ran 280–360. Don't pad — terseness is a
feature.

---

## 5. WORKLOG.md stub template

Append a new `### N. <title>` block under `## Findings (per-item bodies)`,
positioned at the end (after the prior `### N-1.` body):

```markdown
### N. <title>

**Status:** <status> — audited YYYY-MM-DD. <classification>.

<one-paragraph synopsis: scope, audited surfaces, primary mechanism>.

<key per-client findings, structured as: hypotheses-confirmed list → key
per-client mechanisms → divergence-flagged-or-not → divergence-dormancy
reasoning if dormant>.

<one-paragraph future-research summary referencing item #M cross-cuts and
NEW Pattern <X> candidates>.

See [items/NNN/README.md](items/NNN/README.md).
```

Then update the prioritization line (numbered list at the top) for the audited
candidate. The prioritization list in beacon-breaker is reverse-chronological:
new entries go at the top of the relevant track section.

---

## 6. Bootstrap prompt (cold-session warmup)

If starting a fresh session with no agent memory of the project, prefix any
work with:

> **Read `BEACONBREAKER.md`, `AGENTS.md`, the prioritization section in
> `WORKLOG.md`, and the most recent 2–3 `items/NNN/README.md` files. Then
> summarize the project state in ≤150 words — what's the audit goal, which
> surfaces remain, and what status vocabulary is in play. Do not start
> auditing yet.**

This loads the right context before the §1 driver prompt fires. Without it, an
agent may write item READMEs in the wrong shape (no hypothesis enumeration, no
fixture vectors, no cross-reference table).

---

## 7. Commit format

Each item commit:

```
item #N: <title at the audit fork target>

<optional body — major findings, NEW Pattern letters, retroactive corrections,
bug-fix opportunities identified>
```

Stage **only** `items/NNN/README.md` and `WORKLOG.md`. Do not stage:

- vendored client trees (the `vendor/<client>/` worktrees show as untracked
  changes whenever submodule HEADs drift; leave them alone)
- the user-dropped `evm-breaker/` reference checkout if present
- editor/scratch files (`continue.prompt`, `.claude/`)
- build artifacts (`tools/runners/build/`, `tools/bin/`, `out/`)

Verify before committing:

```bash
git status --short | grep -E '^(M |A |R )' | head
# expected, e.g.:
#  M WORKLOG.md
# A  items/NNN/README.md
```

---

## 8. Scope-discovery prompt (when the queue is empty)

When the future-research lists across recent items have all been audited, the
next prompt is:

> **The current item-driven queue is exhausted. Read the most recent 5 item
> READMEs and identify 3–5 new audit candidates (surfaces that could plausibly
> harbor cross-client divergence). Add them to the relevant track in
> `WORKLOG.md`'s prioritization section, with a one-line probe description
> each. Do not start auditing — just propose. Commit the WORKLOG addition.**

This produces the next batch. The user reviews, may reorder, and the §1 driver
prompt resumes.

The audit tracks used so far in beacon-breaker:

- **Track A** — Pectra/Electra state-transition core (items #1–#27, complete).
- **Track B** — cross-corpus pattern catalogue (items #28, #48 refresh).
- **Track C** — Heze surprise + signing-domain primitives (item #29).
- **Track D** — Fork choice (opened at item #56; many follow-ups pending:
  tie-breaking, proposer boost, LMD GHOST, score calculation).
- **Track E** — SSZ schemas (#45, #47, #53, #54 covered; PartialDataColumn-
  Sidecar/Header/PartsMetadata family + DataColumnSidecar Gloas variant pending).
- **Track F** — Fulu-NEW state transition + PeerDAS (items #30–#42, #44,
  #49–#52, #55).
- **Track G** — Heritage-deprecation tracking (#50 RPC + #51 gossip; Status v1
  + MetaData v2 deprecation tracking pending).

New audit candidates can extend these tracks or open new ones (Heze pre-emptive,
Gloas pre-emptive, Track H = validator behavior, etc.).

---

## 9. Rework prompt (defect found in committed item)

If a previously committed item has a flaw (missing client coverage, wrong
file:line, mischaracterized dissent, retroactive correction across multiple
items):

> **Re-open `items/NNN/README.md`. The flaw is `<specific defect>`. Re-audit
> the affected surface(s) only — do not rewrite the unaffected sections.
> Update the README in place, update the WORKLOG stub if the verdict changed,
> note the retroactive correction in the most recent item's "Cross-cut chain"
> section, and commit with subject `Fix item #N: <one-line description>`.**

Avoid the temptation to rewrite the whole item. Targeted fixes preserve git
history and reviewability.

Examples from the corpus:

- **Item #43** retroactively corrected items #15/#19/#32/#36 on V4/V5 Engine
  API ambiguity (V5 is Gloas-NEW, not Fulu-NEW).
- **Item #52** retroactively corrected items #49/#50 on nimbus's Pattern DD
  characterization (nimbus has hybrid load-time formula validation via
  `checkCompatibility`, not bare hardcoded YAML).

When the correction is large enough to span 3+ prior items, prefer documenting
it in the new item that surfaced the correction, with `**RETROACTIVE
CORRECTION**` headers, rather than amending old commits.

---

## 10. Item-extraction script (legacy refactor reference)

`scripts/extract_item.sh` is the historical recipe for migrating WORKLOG-inlined
items into per-item READMEs. The post-#1 corpus has always written
`items/NNN/README.md` from the start, so this script is no longer the primary
path — but it remains the canonical recipe for any future cleanup of inlined
WORKLOG items if a track grows that way before being split out.

`scripts/new_item.sh` is the forward-direction helper (allocate next `N`,
scaffold `items/NNN/`).

---

## 11. Common failure modes

Observed in past sessions; avoid:

- **Hypothesis padding.** Inflating H-list with trivially-true hypotheses
  ("every client is written in a memory-safe-or-managed language") to look
  thorough. Each hypothesis must be a discriminator — something a buggy client
  could plausibly get wrong.
- **Trusting an Explore agent's classification.** The agent reads code in
  excerpts and can misjudge architecture. Verify dissenters directly with
  `Read` before declaring a Pattern letter. Item #56 nimbus was initially
  flagged "INCOMPLETE" by Explore; direct read showed nimbus has a
  3-quarantine architecture (different shape, not a gap).
- **Quoting EIPs instead of code.** EIP text is not source. The audit's value
  is in reading the actual implementations under `vendor/<client>/`.
- **Skipping teku or nimbus because Java/Nim is harder to read.** These have
  produced some of the most actionable findings (item #29 Heze surprise = teku;
  item #44 PartialDataColumnSidecar bug = nimbus). Always read all six.
- **Conflating "no test failure" with "no divergence."** Per `AGENTS.md`:
  absence of fixture failure is not evidence the surface is conformant; the
  fixture may not exercise it. Dissent found in source review still warrants
  a Pattern entry even when fixtures pass.
- **Treating bare client names as path references.** During the vendor/ sweep,
  prose like `nimbus > grandine > lighthouse` and Java package paths like
  `tech/pegasys/teku/...` look path-shaped but aren't. The migration regex
  anchors at backtick-span start to avoid this; new prose should follow the
  same convention (use backticks only for actual paths).
- **Auto-staging untracked directories.** `git add -A` pulls in the user's
  `evm-breaker/` reference clone, the `vendor/grandine/` worktree drift, and
  any in-flight scratch. Always stage only `items/NNN/README.md` and
  `WORKLOG.md` (plus tooling under `tools/` when explicitly working on it).
- **Misclassifying hardcoded-with-validation as plain hardcode.** Item #52's
  retroactive correction caught this for nimbus's `checkCompatibility` macro —
  the value is hardcoded but the formula is validated at YAML-load time.
  Always grep for `checkCompatibility` (nimbus), `default_*` const fns
  (lighthouse), `compute*` builder methods (teku) before declaring a client
  in the "bare hardcoded" bucket.
- **Branch-pinning bias on Gloas/Heze readiness.** lighthouse and nimbus are
  pinned to release branches (`stable`); their unmerged feature work
  (e.g. `gloas/fork-choice` in nimbus) is invisible. Any forward-readiness
  ranking based on default-branch source review is materially incomplete.

---

## 12. Reproducibility checklist

After running the §1 driver prompt once, verify:

- [ ] `items/NNN/README.md` exists with all template sections from §4.
- [ ] `WORKLOG.md` has a new `### N. <title>` block under
      `## Findings (per-item bodies)` plus a corresponding prioritization line.
- [ ] All six clients are referenced by `vendor/<client>/file:line` in the
      README.
- [ ] At least one cross-reference table is present (hypotheses or per-client).
- [ ] Fixture vectors specified (T1/T2/T3 + N1-4) OR explicit
      `no-divergence-pending-fixture-run` declared with reason.
- [ ] Status field uses one of `BEACONBREAKER.md §7` vocabulary terms.
- [ ] Reachability tier (C/A/F/M) declared with justification.
- [ ] One commit, two files staged, message follows §7 format.
- [ ] No untracked directories were added (no `vendor/`, no `evm-breaker/`,
      no scratch).
- [ ] If a dissent was found, a Pattern letter (existing or NEW candidate) is
      cited in the cross-cut chain.

If any check fails, the §9 rework prompt is the right tool.
