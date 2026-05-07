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
- `vendor/prysm/`, `vendor/lighthouse/`, `vendor/teku/`, `vendor/nimbus/`, `vendor/lodestar/`, `vendor/grandine/` —
  client submodules (pinned).
- `vendor/consensus-specs/` — spec + pyspec reference implementation.
- `vendor/consensus-spec-tests/` — EF reference fixtures (shallow clone; large).
- `vendor/beacon-APIs/` — beacon-API spec (out of scope but useful context).

## Working in submodules

The client submodules are pinned. Do **not** pull or rebase them as part of
an audit — the pinned commit defines what "this client diverges" means for a
given finding. If you need to bump a submodule, do it in a separate commit
and re-run any affected fixtures.

When citing code, use the path inside the submodule, e.g.
`vendor/prysm/beacon-chain/state/state-native/setters_validator.go:142-168`.

## Working with pyspec

`tools/pyspec/` should hold a Python venv with the spec installed in editable
mode (`pip install -e consensus-specs[lint,test]`). Import paths look like
`from eth2spec.electra import mainnet as spec`. Use pyspec to:
- Generate fixtures from a (pre-state, block) pair.
- Cross-check a hypothesis against the canonical Python implementation.
- Trace the exact predicate sequence in `process_*` functions.

## Running fixtures against the clients

Every fixture goes through `scripts/run_fixture.sh`. It walks
`tools/runners/{prysm,lighthouse,teku,nimbus,lodestar,grandine}.sh` in
order and prints a per-client PASS / FAIL / SKIP table. A runner exits
77 when it doesn't handle the fixture's category (e.g. teku /
nimbus on epoch_processing); the harness reports SKIP rather than FAIL.

```
./scripts/run_fixture.sh consensus-spec-tests/tests/mainnet/electra/sanity/blocks/pyspec_tests/attestation
./scripts/run_fixture.sh consensus-spec-tests/tests/mainnet/electra/epoch_processing/effective_balance_updates/pyspec_tests/effective_balance_hysteresis
```

Currently supported fixture categories:

| Category | prysm | lighthouse | teku | nimbus | lodestar | grandine |
|---|---|---|---|---|---|---|
| `sanity/blocks` | ✓ go test | ✓ lcli | ✓ teku transition | ✓ ncli | ✓ vitest | ✓ test bin |
| `epoch_processing/<helper>` | ✓ go test | ✓ ef_tests bin | SKIP | SKIP | ✓ vitest | ✓ test bin |

(`tools/runners/_lib.sh` does the fixture-path parsing — `parse_fixture`
sets `BB_CATEGORY`, `BB_FORK`, `BB_HELPER`, `BB_TEST_NAME`. Per-runner
case statements dispatch on `BB_CATEGORY`.)

To wire teku/nimbus for epoch_processing in the future: teku would need
either a new `teku transition epoch-processing` subcommand or a per-call
gradle invocation (~30s startup); nimbus would need a standalone build
of `tests/consensus_spec/test_fixture_state_transition_epoch.nim` with
a name-filter flag.

A clean run looks like:

```
client       result
------       ------
prysm:       PASS  OK (TestMainnet_Electra_Sanity_Blocks/attestation)
lighthouse:  PASS  OK 212bed418e76bcc39b403b7be4401f6d2dab4eb887ef198f019287c40f40f6b4
teku:        PASS  OK 212bed418e76bcc39b403b7be4401f6d2dab4eb887ef198f019287c40f40f6b4
nimbus:      PASS  OK 212bed418e76bcc39b403b7be4401f6d2dab4eb887ef198f019287c40f40f6b4
lodestar:    PASS  OK (vitest: 1 passed for electra/sanity/blocks/pyspec_tests/attestation$)
grandine:    PASS  OK (electra_mainnet_sanity/attestation)
```

Comparison method: lighthouse / teku / nimbus output a post-state to a
temp file and the runner sha256s it against the snappy-decompressed
`post.ssz_snappy`. prysm / grandine / lodestar pipe through their own
spec-test runner (which compares structurally) and the runner just
parses the pass/fail line. All paths converge on the same verdict.

### Environmental requirements

- **First-time build**: each client needs to be built once — see the
  per-client wiring section below. Subsequent runs are fast.
- **PATH / env that must be set for the fixture run**:
  - `tools/cc-shim/` should be on `PATH` for any rebuild that touches a
    C++ native dep (lighthouse `leveldb-sys`, lodestar `classic-level`).
    The shim works around a nix gcc-wrapper bug — `<cstdlib>`'s
    `#include_next <stdlib.h>` fails because glibc-dev/include is
    placed before the C++ stdlib in the include search path. Stripping
    the offending `-isystem` from `NIX_CFLAGS_COMPILE` fixes it.
  - `pnpm` and `node 24` must be on `PATH` for the lodestar runner. The
    sandbox provides them; if invoking outside, set
    `PATH=/nix/store/*-pnpm-*/bin:/nix/store/*-nodejs-24*/bin:$PATH`
    and `PNPM=pnpm`.
  - Lodestar's runner expects the spec-tests at
    `lodestar/packages/beacon-node/spec-tests` — the runner symlinks
    this on first invocation. Don't commit the symlink; it's
    gitignored.
- **Custom fork config**: pyspec EF fixtures' pre-states have `slot=32`
  but mainnet's real Electra fork epoch is 364032. The standalone CLI
  runners (lcli, teku transition, ncli) all use
  `tools/test-configs/electra-from-genesis/` to override fork epochs to
  0. Future fork-targeted fixtures will need a parallel config dir.

### Per-client build wiring

Each runner builds (or expects pre-built) one binary. Build commands
that have been validated in this sandbox:

| Client | Build command | Output path |
|---|---|---|
| prysm | `(cd prysm && go test -count=0 -run TestMainnet_Electra_Sanity_Blocks ./testing/spectest/mainnet/)` to warm the module cache; runner uses `go test` directly | (no separate binary; `go test` recompiles) |
| lighthouse | `(cd lighthouse && PATH=tools/cc-shim:$PATH CARGO_TARGET_DIR=/tmp/lighthouse-target cargo build --release --bin lcli)` | `/tmp/lighthouse-target/release/lcli` |
| teku | `(cd teku && ./gradlew installDist --no-daemon -x test)` | `teku/build/install/teku/bin/teku` |
| nimbus | `(cd nimbus && git submodule update --init --recursive --depth=1 && make ncli)` | `nimbus/build/ncli` |
| lodestar | `(cd lodestar && PATH=tools/cc-shim:$PATH pnpm install --frozen-lockfile && pnpm build)` | TS in `packages/*/lib/`, harness uses `pnpm exec vitest` |
| grandine | `(cd grandine && git submodule update --init --recursive && CARGO_TARGET_DIR=/tmp/grandine-target cargo test -p transition_functions --release --features bls/blst --no-run)` | `/tmp/grandine-target/release/deps/transition_functions-*` |

prysm uses `go test` (not `bazel test`) because the outer nix sandbox
prevents bazel from setting up its own sandbox; the runner spoofs
`RUNFILES_DIR` so `bazel.Runfile()` resolves without bazel.

### Debugging a single-client FAIL

When `run_fixture.sh` shows one client failing:

1. Re-invoke that client's runner directly:
   `./tools/runners/<client>.sh <fixture-dir>`. The runner prints the
   tail of the underlying tool's log on failure.
2. For lighthouse/teku/nimbus mismatches: dump the post-state
   side-by-side against `post.ssz_snappy` after snappy-decompressing
   both with `tools/bin/snappy_codec d`. Compare via `cmp -l` or the
   pyspec `state_summary.py` helper.
3. For prysm/grandine/lodestar: their spec-test runner prints which
   field diverges — quote that in the item README under "Findings".

The state-root sha256 in the PASS line is the canonical fingerprint
for that fixture. When you generate a new fixture, record the
expected sha256 in the item README so future runs can detect drift
without re-running all six clients.

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
