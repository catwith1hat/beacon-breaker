# Item #9 — `process_proposer_slashing` (slash_validator pair, Pectra-affected)

**Status:** no-divergence-pending-fuzzing — audited 2026-05-02. Slashing
operation; **closes the proposer/attester slashing pair** (item #8 was
`process_attester_slashing`); third item in the `slash_validator`
cross-cut chain after items #6 and #8.

## Why this item

`process_proposer_slashing` is the second of two slashing operations in
a Beacon block. Like attester slashing, it is structurally unchanged
from Phase0 but inherits the Pectra-modified `slash_validator`
primitive: `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA = 4096` (was 32 in
Phase0, 64 in Altair, 128 in Bellatrix–Deneb) and
`WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA = 4096` (was 512). Both
constants moved 64×–128× — any client that forgot to plumb these for
the proposer-slashing call site would diverge by orders of magnitude
in the slashing penalty and reward arithmetic, with the divergence
visible in the post-state's `validators[i].effective_balance` and
`balances[whistleblower_idx]` after a single block carrying a slashing.

Unlike voluntary exits (item #6), proposer slashing's signature
verification uses **runtime current-fork DOMAIN_BEACON_PROPOSER**, NOT
a fork-version pin. This is correct per spec — proposer slashings
target a specific block-header signature in a specific slot, and the
domain follows that slot's epoch.

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | Header inequality is full struct (slot+proposer_index+parent_root+state_root+body_root), not just signature/roots | ✅ all 6 |
| H2 | `header_1.slot == header_2.slot` strict equality (not epoch-loose) | ✅ all 6 |
| H3 | `header_1.proposer_index == header_2.proposer_index` strict equality | ✅ all 6 |
| H4 | `is_slashable_validator(proposer, current_epoch)` predicate (NOT exit/withdrawable variants) | ✅ all 6 |
| H5 | Both signatures verified per-header with `DOMAIN_BEACON_PROPOSER` and **current** fork version (NOT pinned) | ✅ all 6 |
| H6 | Per-header epoch sourced from header's slot via `compute_epoch_at_slot(signed_header.message.slot)` (NOT state slot) — matters when `block_header_from_future` straddles a fork epoch | ✅ all 6 |
| H7 | `slash_validator` invocation routes to the **Electra** quotient version (4096 / 4096), not Phase0/Altair/Bellatrix | ✅ all 6 |
| H8 | `MAX_PROPOSER_SLASHINGS == 16` per-block limit enforced (SSZ schema across all clients; runtime guard varies) | ✅ all 6 |

## Per-client cross-reference

| Client | Verify entry point | Header inequality | Slot/proposer eq | Domain selector | Slash dispatch |
|---|---|---|---|---|---|
| **prysm** | `proposer_slashing.go:122–146` (process), `:149–182` (verify) | `proto.Equal(h1, h2)` (proto-level, all 5 fields) | `!=` raw uint64 | `signing.Domain(state.fork, epoch, DomainBeaconProposer, …)` | `validators.SlashValidator` → `SlashingParamsPerVersion(s.Version())` switch |
| **lighthouse** | `verify_proposer_slashing.rs:18–65` | `verify!(header_1 != header_2, …)` (derived `PartialEq`) | `verify!(slot ==, idx ==)` macros | `spec.get_domain(epoch, Domain::BeaconProposer, &state.fork(), gvr)` | `slash_validator(state, idx, None, ctxt, spec)` → `state.get_min_slashing_penalty_quotient(spec)` |
| **teku** | `ProposerSlashingValidator.java:43–69`; mutation in `AbstractBlockProcessor.java:483–508` | `!Objects.equals(h1, h2)` (Container5 structural eq) | `header1.getSlot().equals(header2.getSlot())` etc | `beaconStateAccessors.getDomain(BEACON_PROPOSER, epoch, fork, gvr)`; no Electra override | `BeaconStateMutatorsElectra.slashValidator` (subclass override of `getMinSlashingPenaltyQuotient` etc) |
| **nimbus** | `state_transition_block.nim:145–185` (check), `:195–219` (process) | `if not (header_1 != header_2)` (auto-generated `==` on object) | `==` UInt64 | `verify_block_signature` → `get_domain(fork, DOMAIN_BEACON_PROPOSER, epoch, gvr)` | `slash_validator(cfg, state, idx, …)` with compile-time `when state is electra/fulu/gloas.BeaconState` quotient blocks |
| **lodestar** | `processProposerSlashing.ts:18–56`, validation `:58–102` | `ssz.phase0.BeaconBlockHeaderBigint.equals(h1, h2)` (NOT `===` reference identity) | `header1.slot !== header2.slot` (bigint), `proposerIndex !==` (number) | `config.getDomain(stateSlot, DOMAIN_BEACON_PROPOSER, Number(signedHeader.message.slot))` | `slashValidator` with 5-deep ternary on ForkSeq for penalty + binary branch for whistleblower |
| **grandine** | `transition_functions/electra/block_processing.rs:627–653` (process), `unphased/block_processing.rs:226–286` (validate) | `ensure!(header_1 != header_2)` (derived `PartialEq`) | `ensure!(==)` macros | `accessors::get_domain(config, state, DOMAIN_BEACON_PROPOSER, Some(epoch))` via `SignForSingleFork` trait | `helper_functions::electra::slash_validator` → `P::MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` (compile-time per Preset) |

## Source-organization risk surfaced — grandine has FOUR `slash_validator`s

```
vendor/grandine/helper_functions/src/phase0.rs:81     pub fn slash_validator<P: Preset>(...)
grandine/helper_functions/src/altair.rs:20     pub fn slash_validator<P: Preset>(...)
grandine/helper_functions/src/bellatrix.rs:18  pub fn slash_validator<P: Preset>(...)
grandine/helper_functions/src/electra.rs:153   pub fn slash_validator<P: Preset>(...)
```

The Pectra `transition_functions/src/electra/block_processing.rs`
correctly imports the **electra** version (line 17 `use
helper_functions::electra::slash_validator;`) — verified against the
60/60 fixture pass. **Same source-organization risk** as item #6's
`initiate_validator_exit` (which has Phase0 + Electra variants), only
worse: four definitions instead of two. A future audit walking import
paths could mistake any of the per-fork versions; F-tier today since
all known callers correctly import. Worth noting for any future
refactor that consolidates the four into one fork-keyed dispatcher.

## EF fixture results — 60/60 PASS

Ran all 15 EF mainnet/electra/operations/proposer_slashing fixtures
across the 4 wired clients via `scripts/run_fixture.sh`:

```
clients: prysm, lighthouse, lodestar, grandine
fixtures: 15
PASS: 60   FAIL: 0   SKIP: 0   total: 60
```

Per-fixture coverage breakdown:

| Fixture | Tests |
|---|---|
| `basic` | happy path: full slash applied, balances + slashings vector updated |
| `block_header_from_future` | slot in future of state.slot — must still slash (no slot-vs-state.slot gate) |
| `invalid_different_proposer_indices` | H3: rejected |
| `invalid_headers_are_same_sigs_are_different` | H1: same headers (different sigs) — rejected |
| `invalid_headers_are_same_sigs_are_same` | H1: identical SignedBeaconBlockHeaders — rejected |
| `invalid_incorrect_proposer_index` | proposer_index out of range / wrong validator — rejected |
| `invalid_incorrect_sig_1` | H5: sig1 fails BLS verify — rejected |
| `invalid_incorrect_sig_1_and_2` | H5: both sigs fail — rejected |
| `invalid_incorrect_sig_1_and_2_swap` | H5: sigs verify but for wrong header (swapped) — rejected |
| `invalid_incorrect_sig_2` | H5: sig2 fails — rejected |
| `invalid_proposer_is_not_activated` | H4: activation_epoch > current_epoch — rejected |
| `invalid_proposer_is_slashed` | H4: validator.slashed already true — rejected |
| `invalid_proposer_is_withdrawn` | H4: withdrawable_epoch ≤ current_epoch — rejected |
| `invalid_slots_of_different_epochs` | H2: different slots (which also implies different epochs) — rejected |
| `slashed_and_proposer_index_the_same` | self-test: slashed=true and idx==proposer — rejected (also via H4) |

teku and nimbus SKIP per harness limitation (no per-operation CLI hook
in BeaconBreaker's runners). Both have proposer_slashing handling in
their internal CI per source review.

## Notable per-client styles

### prysm
Uses `proto.Equal()` for header inequality — protobuf-level structural
equality covers all 5 fields. Validation order differs slightly from
pyspec: slot eq → proposer-idx eq → header inequality → slashability →
sig verify. Caches `ExitInformation(state)` once per block and reuses
across all proposer + attester slashings within the block to amortize
churn-state computation. Has Gloas (EIP-7732) builder-payment cleanup
hook in `processProposerSlashing`: `RemoveBuilderPendingPayment()` —
no-op at Pectra, dead code today. Sequential signature verification (no
batching at this layer); block-level `BlockSignatureVerifier` exists
but the per-fixture operations path doesn't invoke it.

### lighthouse
`verify!()` macro for short-circuit validation with structured
`Invalid::*` variants. Uses derived `PartialEq` on `BeaconBlockHeader`
(struct-level `!=`). Fork-keyed quotient via state methods
`get_min_slashing_penalty_quotient(spec)` and
`get_whistleblower_reward_quotient(spec)` — same idiom as item #8's
attester slashing (single source of truth). Per-fixture path verifies
sigs individually via `signature_set.verify()`; block path collects
into a `BlockSignatureVerifier` for batch. `safe_*` arithmetic in
`slash_validator` (overflow-checked div/mul/add/sub).

### teku
Uses `Objects.equals()` for header inequality (Container5 structural
eq, all 5 fields). Validation via `firstOf(...)` combinator
short-circuits at first failed predicate. Quotient dispatch via
**subclass-override polymorphism** — `BeaconStateMutatorsElectra
extends BeaconStateMutatorsBellatrix` overrides
`getMinSlashingPenaltyQuotient()` and `getWhistleblowerRewardQuotient()`
— same pattern as item #8. Confirmed `BeaconStateAccessorsElectra` does
**NOT** override `getDomain()` for proposer (correct: proposer uses
runtime fork, unlike voluntary exit which uses `getVoluntaryExitDomain`
with the EIP-7044 Capella pin). `OperationInvalidReason` enum-based
result type (no exceptions for validation failures).

### nimbus
`if not (header_1 != header_2)` — uses Nim's auto-generated `!=`
operator on `BeaconBlockHeader` objects (structural over all fields).
Quotient dispatch via compile-time `when state is electra.BeaconState |
fulu.BeaconState | gloas.BeaconState` blocks — zero runtime overhead.
Uses `?` macro for early-return error propagation through the
Result-based pipeline. Borrows validator via `unsafeAddr
state.validators[idx]` to avoid copy while staying memory-safe in
scope. Like prysm and grandine, has a Gloas branch in
`process_proposer_slashing` (`when typeof(state).kind >= ConsensusFork.Gloas`)
for builder payment clearing — dead at Pectra.

### lodestar
**Uses `ssz.phase0.BeaconBlockHeaderBigint.equals(header1, header2)`**
for header inequality — critically NOT `===` (which would be reference
identity in JS and always return `false` for distinct objects, falsely
*allowing* identical-content headers to be slashed). The `Bigint`
variant is used because `slot` is bigint-typed in the SSZ schema and
JS `===` on bigints is value equality, but the deep struct comparison
needs SSZ's `equals`. **5-deep nested ternary** on `ForkSeq` for
penalty quotient (per-fork explicit), binary branch for whistleblower
reward (Electra cutover). Block-level batch sig verification via
`SignatureSetType.indexed`; per-fixture operations path runs
`verifySignatureSet` per call. Coerces `slot` bigint to `Number` for
epoch math — safe since slot < 2^53 for the lifetime of the chain.

### grandine
`ensure!(header_1 != header_2)` — uses derived `PartialEq` on the
container struct. Dispatch via the `SignForSingleFork<P>` trait
(`DOMAIN_TYPE: DomainType = DOMAIN_BEACON_PROPOSER` per impl) computes
`signing_root` via `accessors::get_domain(config, state,
DOMAIN_BEACON_PROPOSER, Some(epoch))` — runtime fork from
`state.fork()`, NOT pinned. Quotient via type-associated constants
`P::MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` (compile-time per Preset).
Slash dispatch imported as
`use helper_functions::electra::slash_validator` (correct;
`helper_functions/{phase0,altair,bellatrix,electra}.rs` each define
one — see source-organization risk above). `Verifier` trait abstracts
single/batch BLS verification; the operations path uses
`SingleVerifier`, the block path uses `MultiVerifier` for batch.

## Cross-cut chain — confirmed third pass

Items #6 (voluntary exit), #8 (attester slashing), and #9 (proposer
slashing — this item) all converge on `slash_validator` (#8 + #9) and
`initiate_validator_exit` (all three). The cumulative fixture evidence
across the chain:

| Item | Fixtures | Cumulative |
|---|---|---|
| #6 voluntary_exit | 25/25 | 25 |
| #8 attester_slashing | 30/30 | 55 |
| #9 proposer_slashing (this) | 15/15 | 70 |

70 ops fixtures × 4 wired clients = **280 PASS results** all
exercising the Pectra-modified slashing/exit machinery (modulo the
quotient changes). Strongest evidence yet for this surface.

The `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` and
`WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA` constants are now confirmed
correctly plumbed into both slashing operations across all 4 wired
clients (and per source review, all 6).

## Adjacent untouched Electra-active

- **`process_slashings` per-epoch helper** (WORKLOG #10) — reads the
  `state.slashings` vector that this item writes (along with item #8).
  Pectra changed the proportional multiplier; the vector index
  (`epoch % EPOCHS_PER_SLASHINGS_VECTOR`) interaction with item #9's
  +epoch-shift writes is the natural follow-up.
- **Header inequality semantics — what *is* a "different" header?** A
  proposer signing two headers with same slot/proposer_index/body_root
  but different state_root (typical "two roots, same body" attack) is
  the canonical case. Worth crafting a fixture with body_root
  identical, state_root differing — currently
  `invalid_headers_are_same_sigs_are_different` covers the dual case.
- **`block_header_from_future` slot semantics** — the fixture confirms
  that header.slot > state.slot is allowed for slashing (the slashing
  predicates don't reference state.slot beyond domain computation).
  But what about header.slot in the **past** before validator's
  activation? Covered by `invalid_proposer_is_not_activated` indirectly
  (via current_epoch slashability), but the slot-itself constraint is
  not directly tested.
- **Domain epoch sourced from header.slot vs state.slot** — pyspec
  computes `domain` per-header from `compute_epoch_at_slot(signed_header.message.slot)`.
  All 6 clients do likewise. **A regression to using state's epoch**
  would silently use the wrong fork version when a slashing is
  included after a fork transition for a pre-fork header — F-tier
  today (no fixture spans a fork boundary) but high-leverage for
  fuzzing.
- **Source-organization risk in grandine** (4 `slash_validator`
  definitions across phase0/altair/bellatrix/electra) — same pattern
  as item #6's `initiate_validator_exit`. Worth a one-line audit
  asserting all callers in `transition_functions/electra/` import from
  `helper_functions::electra::`.
- **Self-slashing** — what happens when proposer == whistleblower
  (i.e., the block proposer including the slashing IS the slashed
  validator)? `slashed_and_proposer_index_the_same` covers this — but
  the reward math (`whistleblower_reward = ...; proposer_reward =
  whistleblower_reward * PROPOSER_WEIGHT / WEIGHT_DENOMINATOR; …;
  increase_balance(state, whistleblower_index, whistleblower_reward -
  proposer_reward)`) when `whistleblower_index == proposer_index ==
  slashed_index` deserves explicit verification — three increments to
  the same balance with one decrement.
- **MAX_ATTESTER_SLASHINGS_ELECTRA was reduced; MAX_PROPOSER_SLASHINGS
  unchanged at 16** — the asymmetry was deliberate (attester
  slashings carry up to 131,072 indices each post-EIP-7549). Worth
  documenting in a `consts.md`.
- **prysm's `ExitInformation` cache reuse across both slashing types
  in the same block** — assumes the cached state.churn slots don't
  change between the per-block validation entry and the actual
  slashing application. If a slashing in the same block already
  consumed the churn budget, the cache would be stale. Worth
  generating a stateful fixture: 2 proposer slashings + 1 attester
  slashing in one block, all touching the churn pool, to verify
  cache-vs-fresh-read parity.
- **Lighthouse's `safe_*` overflow-checked arithmetic** in
  `slash_validator` — the 4096 quotient div produces ≥ 1 gwei for any
  effective_balance ≥ 4096, but safe_div's "div by zero" branch is
  dead code (quotient is `NonZero` at the type level in some clients
  but raw u64 in lighthouse). Audit closure.
- **lodestar's BigInt-vs-Number coercion** — `Number(slot)` for epoch
  math is safe today (slot < 2^53), but the type-system-level mixing
  is a forward-looking divergence vector for any client that switches
  to all-bigint or all-number. Pre-emptive fuzz target: a fixture with
  slot near 2^53 (academic).

## Future research items

1. **`process_slashings` per-epoch** (WORKLOG #10) — closes the
   slashings vector write-then-read cycle.
2. **State upgrade function** at the Pectra activation slot (Track C
   #13) — defines the `state.slashings` vector layout that #9 writes
   into.
3. **Cross-fork slashing fixture** — proposer signs two block headers
   straddling a fork epoch boundary (one pre-Electra, one post-Electra).
   The per-header domain computation should pick different fork
   versions; verify all 6 clients agree on signature acceptance.
4. **`PROPOSER_WEIGHT / WEIGHT_DENOMINATOR` Altair-onwards reward
   split** — present in lighthouse's `slash_validator` as
   `state.fork_name_unchecked().altair_enabled()`. Clients that
   short-circuit pre-Altair behavior have a dead branch worth pruning.
5. **MAX_PROPOSER_SLASHINGS over-the-wire test** — block with 17
   proposer slashings; SSZ deserialization should reject before
   processing.
6. **Header inequality fuzz** — generate header pairs varying one
   field at a time (slot / proposer_index — covered explicitly above
   the inequality; parent_root / state_root / body_root — only covered
   by the diff-everywhere `basic` and same-body diff-state-root
   variants in EF). A field-isolation matrix is small (5 fields × 2
   diff/same = 32 cases).
7. **prysm's `SlashingParamsPerVersion` Gloas-readiness** — already
   has a Gloas branch (verify it returns Gloas-correct constants
   should Gloas change them).
8. **Lighthouse's `BlockSignatureVerifier` block-level batch sig path**
   — currently bypassed by per-fixture operations path. A fixture
   harness that exercises the batch path would add coverage for the
   batched proposer/attester slashing signatures together.
