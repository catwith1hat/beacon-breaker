---
status: source-code-reviewed
impact: mainnet-glamsterdam
last_update: 2026-05-12
builds_on: [6, 8]
eips: [EIP-7251, EIP-7732, EIP-8061]
splits: [prysm, lighthouse, teku, nimbus, grandine]
# main_md_summary: lighthouse lacks the Gloas EIP-7732 `BuilderPendingPayment` clearing in `process_proposer_slashing`; the same five clients also propagate the EIP-8061 churn divergence via `slash_validator` (sister to items #6 H8 / #8 H9)
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 9: `process_proposer_slashing` (slash_validator pair, Pectra-affected)

## Summary

Second of two slashing operations in a Beacon block. Structurally unchanged from Phase0 at Pectra but inherits the Pectra-modified `slash_validator` primitive: `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA = 4096` (was 32 in Phase0, 64 in Altair, 128 in Bellatrix–Deneb) and `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA = 4096` (was 512). Unlike voluntary exits (item #6), proposer-slashing signature verification uses **runtime current-fork `DOMAIN_BEACON_PROPOSER`**, NOT a fork-version pin.

**Pectra surface (the function body itself):** all six clients implement the four predicates (slot-eq, proposer-eq, header-inequality, slashability) and signature verification identically, and all six route the Pectra quotients through `slash_validator` correctly. 15/15 EF `proposer_slashing` operations fixtures pass uniformly on the four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus pass these in internal CI but the local harness SKIPs them.

**Gloas surface (new at the Glamsterdam target):** two distinct divergences.

1. **H9 — Gloas EIP-7732 `BuilderPendingPayment` clearing.** Gloas adds a step **before** `slash_validator(state, header_1.proposer_index)` that zeroes out `state.builder_pending_payments[payment_index]` for the slashed proposer's slot if the proposal is within the 2-epoch sliding window (current or previous epoch). The rationale: a slashed proposer's builder bid must not pay out. Survey: prysm, teku, nimbus, lodestar, grandine implement the clearing; **lighthouse does not** — no `>= ForkName::Gloas` branch in `verify_proposer_slashing.rs` or `process_operations.rs`, no `builder_pending_payments` references in `per_block_processing/`. State-root divergence on every Gloas-slot block carrying a proposer slashing (any slashed proposer with a pending builder payment in the 2-epoch window).
2. **H10 — Gloas EIP-8061 churn cascade via `slash_validator`.** `slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn` cascades through the same EIP-8061-Modified churn helper as items #3 H8 / #6 H8 / #8 H9. Only lodestar fork-gates the helper to consume `get_exit_churn_limit` at Gloas; prysm, lighthouse, teku, nimbus, grandine retain the Electra `get_activation_exit_churn_limit` even on Gloas states. Each slashed proposer's `exit_epoch` and `withdrawable_epoch` therefore differ across the 5-vs-1 cohort. Sixth installment of the EIP-8061 family.

Combined `splits` = the same five clients (lighthouse fails on both axes; prysm/teku/nimbus/grandine fail only on H10; lodestar is spec-aligned on both).

## Question

`process_proposer_slashing` is the second of two slashing operations in a Beacon block. Pyspec (Pectra-typed):

```python
def process_proposer_slashing(state, proposer_slashing):
    header_1 = proposer_slashing.signed_header_1.message
    header_2 = proposer_slashing.signed_header_2.message
    assert header_1.slot == header_2.slot
    assert header_1.proposer_index == header_2.proposer_index
    assert header_1 != header_2
    proposer = state.validators[header_1.proposer_index]
    assert is_slashable_validator(proposer, get_current_epoch(state))
    for signed_header in (proposer_slashing.signed_header_1, proposer_slashing.signed_header_2):
        domain = get_domain(state, DOMAIN_BEACON_PROPOSER, compute_epoch_at_slot(signed_header.message.slot))
        signing_root = compute_signing_root(signed_header.message, domain)
        assert bls.Verify(proposer.pubkey, signing_root, signed_header.signature)
    slash_validator(state, header_1.proposer_index)
```

Pectra-relevant constants (via `slash_validator`):

- `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA = 4096` (was 128 in Bellatrix–Deneb).
- `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA = 4096` (was 512).

**Glamsterdam target.** Gloas modifies `process_proposer_slashing` (`vendor/consensus-specs/specs/gloas/beacon-chain.md` "Modified `process_proposer_slashing`"). The function gains a pre-`slash_validator` step:

```python
# [New in Gloas:EIP7732]
# Remove the BuilderPendingPayment corresponding to
# this proposal if it is still in the 2-epoch window.
slot = header_1.slot
proposal_epoch = compute_epoch_at_slot(slot)
if proposal_epoch == get_current_epoch(state):
    payment_index = SLOTS_PER_EPOCH + slot % SLOTS_PER_EPOCH
    state.builder_pending_payments[payment_index] = BuilderPendingPayment()
elif proposal_epoch == get_previous_epoch(state):
    payment_index = slot % SLOTS_PER_EPOCH
    state.builder_pending_payments[payment_index] = BuilderPendingPayment()

slash_validator(state, header_1.proposer_index)
```

`slash_validator` itself remains unchanged at Gloas (no Modified heading), but its internal cascade into `compute_exit_epoch_and_update_churn` IS modified (EIP-8061; see items #3 H8 / #6 H8 / #8 H9). The slashing constants `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` and `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA` are also unchanged at Gloas.

The hypothesis: *all six clients implement the four pre-Pectra predicates (H1–H4), the per-header runtime-domain signature verification (H5–H6), the Pectra quotient routing (H7), and the SSZ MAX_PROPOSER_SLASHINGS limit (H8); and at the Glamsterdam target all six implement the Gloas `BuilderPendingPayment` clearing pre-`slash_validator` (H9) and fork-gate the underlying `compute_exit_epoch_and_update_churn` to use `get_exit_churn_limit` (H10).*

**Consensus relevance**: a proposer slashing transfers `effective_balance` → `state.slashings` vector, reduces slashed proposer's balance, rewards block proposer + whistleblower, and at Gloas clears the slashed proposer's pending builder payment. A divergence in any Pectra-surface bit (predicates, sig domain, quotients) would split the chain immediately. A divergence in H9 (BuilderPendingPayment clearing) writes a different `state.builder_pending_payments` vector — `hash_tree_root(state)` diverges. A divergence in H10 (churn cascade) writes different `validators[i].exit_epoch` / `validators[i].withdrawable_epoch` for the slashed proposer — same divergence pattern as the rest of the EIP-8061 family.

## Hypotheses

- **H1.** Header inequality is full struct (slot+proposer_index+parent_root+state_root+body_root), not just signature/roots.
- **H2.** `header_1.slot == header_2.slot` strict equality (not epoch-loose).
- **H3.** `header_1.proposer_index == header_2.proposer_index` strict equality.
- **H4.** `is_slashable_validator(proposer, current_epoch)` predicate (NOT exit/withdrawable variants).
- **H5.** Both signatures verified per-header with `DOMAIN_BEACON_PROPOSER` and **current** fork version (NOT pinned).
- **H6.** Per-header epoch sourced from header's slot via `compute_epoch_at_slot(signed_header.message.slot)` (NOT state slot) — matters when `block_header_from_future` straddles a fork epoch.
- **H7.** `slash_validator` invocation routes to the **Electra** quotient version (4096 / 4096), not Phase0/Altair/Bellatrix. Continues at Gloas (no quotient change).
- **H8.** `MAX_PROPOSER_SLASHINGS == 16` per-block limit enforced.
- **H9** *(Glamsterdam target — `BuilderPendingPayment` clearing)*. At the Gloas fork gate, all six clients zero out `state.builder_pending_payments[payment_index]` for the slashed proposer's slot **before** calling `slash_validator`, gated on the proposal being in the current or previous epoch.
- **H10** *(Glamsterdam target — EIP-8061 churn cascade via `slash_validator`)*. At the Gloas fork gate, every `slash_validator(state, proposer_index)` call paces the slashed proposer's `exit_epoch` via `compute_exit_epoch_and_update_churn` consuming `get_exit_churn_limit(state)` (Gloas) rather than `get_activation_exit_churn_limit(state)` (Electra). Pre-Gloas, all six retain the Electra formula. Same finding as items #6 H8 / #8 H9.

## Findings

H1–H8 satisfied for the Pectra surface — function bodies, predicates, runtime-fork domain selection, Pectra quotient routing, SSZ limit all aligned. **H9 fails for lighthouse alone**. **H10 fails for 5 of 6 clients** (same set as items #6 H8 / #8 H9). Source-level divergence on both axes; no Gloas operations fixtures yet exist.

### prysm

`vendor/prysm/beacon-chain/core/blocks/proposer_slashing.go:122-182` — `ProcessProposerSlashings` (process) and `VerifyProposerSlashing` (verify). The Pectra-surface predicates use `proto.Equal(h1, h2)` for header inequality (protobuf-level structural equality over all 5 fields). Domain selector at the verify step uses `signing.Domain(state.fork, epoch, DomainBeaconProposer, ...)` — runtime fork from `state.fork()`, NOT pinned.

**Gloas builder-payment clearing (H9 ✓)** at line 135 of `proposer_slashing.go`:

```go
err = gloas.RemoveBuilderPendingPayment(beaconState, slashing.Header_1.Header)
```

`RemoveBuilderPendingPayment` lives in `vendor/prysm/beacon-chain/core/gloas/proposer_slashing.go` and walks the same `current-epoch` / `previous-epoch` payment-index logic as the spec.

`SlashValidator` (`vendor/prysm/beacon-chain/core/validators/validator.go:235-305`) calls `InitiateValidatorExit(ctx, s, slashedIdx, exitInfo)` near the top — same function audited in items #6 / #8. That delegates to `state.ExitEpochAndUpdateChurn(EffectiveBalance)`, which at `vendor/prysm/beacon-chain/state/state-native/setters_churn.go:67` runs the Electra `ActivationExitChurnLimit` formula unconditionally.

H1 ✓ (`proto.Equal`). H2 ✓ (`!=` raw uint64). H3 ✓. H4 ✓. H5 ✓ (runtime-fork domain). H6 ✓ (per-header epoch). H7 ✓ (`SlashingParamsPerVersion(s.Version())` returns Electra constants for `version >= Electra`). H8 ✓. **H9 ✓**. **H10 ✗** (inherited from item #6's prysm finding).

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing/verify_proposer_slashing.rs:18-65` + `vendor/lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:219` (`process_proposer_slashings<E>`). Uses `verify!(header_1 != header_2, ...)` with derived `PartialEq` on `BeaconBlockHeader`. Domain selector `spec.get_domain(epoch, Domain::BeaconProposer, &state.fork(), gvr)` — runtime fork.

**No Gloas branch (H9 ✗).** `verify_proposer_slashing.rs` and `process_operations.rs` contain zero references to `builder_pending_payments`, `>= ForkName::Gloas`, or `fork_name_unchecked().gloas_enabled()`. The state field IS defined at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:628` (`builder_pending_payments: Vector<BuilderPendingPayment, ...>`) and allocated by the Gloas upgrade at `vendor/lighthouse/consensus/state_processing/src/upgrade/gloas.rs:101-103`, but no per-block-processing code path mutates it. A slashed proposer's pending builder payment will not be cleared on lighthouse; the other five will clear it.

`slash_validator` (`vendor/lighthouse/consensus/state_processing/src/common/slash_validator.rs:16-79`) calls `state.initiate_validator_exit(slashed_index, spec)?` near the top — same as items #6 / #8. That calls `compute_exit_epoch_and_update_churn(effective_balance, spec)?` at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2708-2752`, which uses `self.get_activation_exit_churn_limit(spec)?` unconditionally even on a Gloas state variant.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (via `state.get_min_slashing_penalty_quotient(spec)` / `state.get_whistleblower_reward_quotient(spec)`). H8 ✓. **H9 ✗** (no Gloas branch). **H10 ✗** (inherited from item #6's lighthouse finding).

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/common/operations/validation/ProposerSlashingValidator.java:43-69` (validate) + `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/common/block/AbstractBlockProcessor.java:483-508` (mutation). Validation uses `Objects.equals(h1, h2)` for inequality (Container5 structural eq). Domain selection via `beaconStateAccessors.getDomain(BEACON_PROPOSER, epoch, fork, gvr)` — no Electra/Gloas override (correct: proposer domain follows runtime fork).

**Gloas builder-payment clearing (H9 ✓)** via subclass-override polymorphism: `AbstractBlockProcessor.java:500` calls a protected `removeBuilderPendingPayment(proposerSlashing, state)` hook (declared at `:510` with a no-op default body); `BlockProcessorGloas` overrides this hook at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/block/BlockProcessorGloas.java:322` to implement the spec's 2-epoch-window clearing.

`slashValidator` (`BeaconStateMutators.java`) calls `initiateValidatorExit(state, index, validatorExitContextSupplier)` near the top — same function audited in item #6. `BeaconStateMutatorsElectra.computeExitEpochAndUpdateChurn` at lines 77-104 of that file uses `stateAccessorsElectra.getActivationExitChurnLimit(state)` unconditionally; `BeaconStateMutatorsGloas` does not override.

H1 ✓ (`Objects.equals`). H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (subclass-override polymorphism). H8 ✓. **H9 ✓**. **H10 ✗** (inherited from item #6's teku finding).

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:145-185` (`check_proposer_slashing`) + `:195-220` (`process_proposer_slashing*`). Header inequality via `if not (header_1 != header_2)` (Nim's auto-generated `!=`). Domain selector via `verify_block_signature` calling `get_domain(fork, DOMAIN_BEACON_PROPOSER, epoch, gvr)` — runtime fork.

**Gloas builder-payment clearing (H9 ✓)** at `state_transition_block.nim:202-212`:

```nim
# [New in Gloas:EIP7732]
# Remove the BuilderPendingPayment corresponding to
# this proposal if it is still in the 2-epoch window.
when typeof(state).kind >= ConsensusFork.Gloas:
  let
    slot = proposer_slashing.signed_header_1.message.slot
    proposal_epoch = slot.epoch()
    current_epoch = get_current_epoch(state)
  # ... clear state.builder_pending_payments[payment_index] ...
```

Compile-time fork dispatch — zero runtime overhead.

`slash_validator` (`vendor/nimbus/beacon_chain/spec/beaconstate.nim:379-407`) calls `initiate_validator_exit(cfg, state, slashed_index, exit_queue_info, cache)` at the start — same as items #6 / #8. That at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:286-314` calls `get_activation_exit_churn_limit` even on a `gloas.BeaconState`.

H1 ✓ (auto-generated `!=`). H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (compile-time `when state is electra | fulu | gloas`). H8 ✓. **H9 ✓**. **H10 ✗** (inherited from item #6's nimbus finding).

### lodestar

`vendor/lodestar/packages/state-transition/src/block/processProposerSlashing.ts:18-56` + validation at `:58-102`. Header inequality via `ssz.phase0.BeaconBlockHeaderBigint.equals(header1, header2)` (SSZ deep equality — critically NOT `===` reference identity). Domain selector via `config.getDomain(stateSlot, DOMAIN_BEACON_PROPOSER, Number(signedHeader.message.slot))` — runtime fork, per-header epoch.

**Gloas builder-payment clearing (H9 ✓)** at `processProposerSlashing.ts:34-50`:

```typescript
if (fork >= ForkSeq.gloas) {
    // ... compute payment_index for current or previous epoch ...
    (state as CachedBeaconStateGloas).builderPendingPayments.set(
        paymentIndex,
        ssz.gloas.BuilderPendingPayment.defaultViewDU()
    );
}
```

`slashValidator` (`vendor/lodestar/packages/state-transition/src/block/slashValidator.ts:24-59`) calls `initiateValidatorExit(fork, state, slashedIndex)` near the top — same as items #6 / #8. That at `vendor/lodestar/packages/state-transition/src/block/initiateValidatorExit.ts:27-62` calls `computeExitEpochAndUpdateChurn(state, BigInt(validator.effectiveBalance))`. Its body at `vendor/lodestar/packages/state-transition/src/util/epoch.ts:50-77` IS the **fork-gated** implementation (per items #3 / #6).

H1 ✓ (`equals`). H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (5-deep nested ternary on `ForkSeq`). H8 ✓. **H9 ✓**. **H10 ✓** — the only client where `slash_validator` correctly paces the slashed proposer's exit at Gloas.

### grandine

Two layers. `vendor/grandine/transition_functions/src/electra/block_processing.rs:627-653` is the Pectra `process_proposer_slashing`. `vendor/grandine/transition_functions/src/gloas/block_processing.rs:1173-1213` is the Gloas wrapper that adds the builder-payment clearing before calling `slash_validator`:

```rust
pub fn process_proposer_slashing<P: Preset>(
    config: &Config,
    pubkey_cache: &PubkeyCache,
    state: &mut impl PostGloasBeaconState<P>,
    proposer_slashing: ProposerSlashing,
    verifier: impl Verifier,
    slot_report: impl SlotReport,
) -> Result<()> {
    unphased::validate_proposer_slashing_with_verifier(config, pubkey_cache, state, proposer_slashing, verifier)?;

    // > Remove the BuilderPendingPayment corresponding to this proposal if it is still in the 2-epoch window.
    let slot = proposer_slashing.signed_header_1.message.slot;
    let proposal_epoch = compute_epoch_at_slot::<P>(slot);
    if proposal_epoch == get_current_epoch(state) {
        *state.builder_pending_payments_mut()
            .mod_index_mut(builder_payment_index_for_current_epoch::<P>(slot)) = BuilderPendingPayment::default();
    } else if proposal_epoch == get_previous_epoch(state) {
        *state.builder_pending_payments_mut()
            .mod_index_mut(builder_payment_index_for_previous_epoch::<P>(slot)) = BuilderPendingPayment::default();
    }

    let index = proposer_slashing.signed_header_1.message.proposer_index;
    slash_validator(config, state, index, None, SlashingKind::Proposer, slot_report)
}
```

The Pectra `slash_validator` (`vendor/grandine/helper_functions/src/electra.rs:153`) is still the one called for Gloas — calls `initiate_validator_exit` → `compute_exit_epoch_and_update_churn`, whose body at `vendor/grandine/helper_functions/src/mutators.rs:177-208` uses `get_activation_exit_churn_limit` unconditionally.

Source-organization note preserved from prior audit: grandine has FOUR `slash_validator` definitions (one per fork: phase0/altair/bellatrix/electra). Pectra and Gloas callers import the Electra version explicitly.

H1 ✓ (`ensure!`). H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (`P::MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` compile-time). H8 ✓. **H9 ✓**. **H10 ✗** (inherited from item #6's grandine finding).

## Cross-reference table

| Client | Verify entry point | Gloas `BuilderPendingPayment` clearing (H9) | `slash_validator` → churn cascade (H10) |
|---|---|---|---|
| prysm | `proposer_slashing.go:122-146` (process), `:149-182` (verify) | **✓** (`:135` calls `gloas.RemoveBuilderPendingPayment`) | ✗ (`state-native/setters_churn.go:67` calls `helpers.ActivationExitChurnLimit` unconditionally) |
| lighthouse | `verify_proposer_slashing.rs:18-65`; `process_operations.rs:219` | **✗** (no `>= ForkName::Gloas` branch; state field present but never mutated by per_block_processing) | ✗ (`beacon_state.rs:2708-2752` calls `get_activation_exit_churn_limit` unconditionally) |
| teku | `ProposerSlashingValidator.java:43-69`; `AbstractBlockProcessor.java:483-508` | **✓** (`AbstractBlockProcessor.java:500` calls hook; `BlockProcessorGloas.java:322 removeBuilderPendingPayment` overrides) | ✗ (`BeaconStateMutatorsElectra.java:77-104` calls `getActivationExitChurnLimit`; `BeaconStateMutatorsGloas` doesn't override) |
| nimbus | `state_transition_block.nim:145-185` (check), `:195-220` (process) | **✓** (`:202-212` `when typeof(state).kind >= ConsensusFork.Gloas`) | ✗ (`beaconstate.nim:286-314` body uses `get_activation_exit_churn_limit` even with `gloas.BeaconState` signature) |
| lodestar | `processProposerSlashing.ts:18-56`, validation `:58-102` | **✓** (`:34-50` `if (fork >= ForkSeq.gloas)` clears via `builderPendingPayments.set(...)` to `BuilderPendingPayment.defaultViewDU()`) | **✓** (`util/epoch.ts:50-77` fork-gates `getExitChurnLimit` at `fork >= ForkSeq.gloas`) |
| grandine | `electra/block_processing.rs:627-653` (Electra), `gloas/block_processing.rs:1173-1213` (Gloas wrapper) | **✓** (Gloas wrapper calls `mod_index_mut(...) = BuilderPendingPayment::default()` before `slash_validator`) | ✗ (`mutators.rs:177-208` calls `get_activation_exit_churn_limit` unconditionally) |

## Empirical tests

### Pectra-surface fixture run

`consensus-spec-tests/tests/mainnet/electra/operations/proposer_slashing/pyspec_tests/` — 15 EF fixtures. Run via `scripts/run_fixture.sh` against all six clients on 2026-05-02. **60/60** (15 × 4 wired clients):

```
basic
block_header_from_future
invalid_different_proposer_indices
invalid_headers_are_same_sigs_are_different
invalid_headers_are_same_sigs_are_same
invalid_incorrect_proposer_index
invalid_incorrect_sig_1
invalid_incorrect_sig_1_and_2
invalid_incorrect_sig_1_and_2_swap
invalid_incorrect_sig_2
invalid_proposer_is_not_activated
invalid_proposer_is_slashed
invalid_proposer_is_withdrawn
invalid_slots_of_different_epochs
slashed_and_proposer_index_the_same
```

All PASS on prysm + lighthouse + lodestar + grandine. teku and nimbus SKIP per harness limit (no per-operation CLI hook); both pass these in their internal CI.

### Gloas-surface

No Gloas operations fixtures yet exist for `process_proposer_slashing`. H9 and H10 are currently source-only. (Cumulative slashing-machinery evidence across items #6 + #8 + #9 is 70 operations fixtures × 4 wired clients = 280 PASS results on the Pectra surface.)

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — slashing a high-balance compounding validator).** Effective balance = 2048 ETH. Tests both Pectra quotients at the upper boundary.
- **T1.2 (priority — cross-fork slashing).** Proposer signs two block headers straddling a fork epoch boundary (one pre-Electra, one post-Electra). The per-header domain computation should pick different fork versions; verify all 6 clients agree on signature acceptance.
- **T1.3 (Glamsterdam-target — proposer slashing clears pending builder payment).** Gloas state with `state.builder_pending_payments[payment_index].withdrawal.amount > 0` for the slashed proposer's slot in the current epoch. Expected per Gloas spec: the entry is reset to `BuilderPendingPayment::default()` before `slash_validator` runs. Lighthouse will not clear; the other five will. State-root divergence on the `builder_pending_payments` field.
- **T1.4 (Glamsterdam-target — proposer slashing clears previous-epoch builder payment).** Same as T1.3 but the slot is in the previous epoch (`payment_index = slot % SLOTS_PER_EPOCH`). Distinguishes the two-window logic.

#### T2 — Adversarial probes
- **T2.1 (priority — proposer == whistleblower self-slashing).** Block proposer including the slashing IS the slashed validator. Covered by `slashed_and_proposer_index_the_same`.
- **T2.2 (defensive — header inequality boundary).** Headers differ in `state_root` only (typical "two roots, same body" attack). Currently `invalid_headers_are_same_sigs_are_different` covers the dual case; consider a body-equal / state-root-different fixture.
- **T2.3 (defensive — block_header_from_future slot semantics).** `block_header_from_future` confirms header.slot > state.slot is allowed; consider also a header.slot in the past before validator's activation.
- **T2.4 (Glamsterdam-target — slashing outside 2-epoch window).** Gloas state with a slashed proposer whose proposal_epoch is **older** than `get_previous_epoch(state)`. Spec: no `builder_pending_payments` clearing (the entry has already aged out of the 2-epoch window). Verify all six clients leave the vector unchanged for this case. Pre-emptive test that lighthouse's "do nothing" matches the spec for the older-than-window case (so the test passes for lighthouse — important to flag that lighthouse's correctness is coincidental, not engineered).
- **T2.5 (Glamsterdam-target — Gloas churn cascade).** Sister to items #6 T2.5 / #8 T2.6 — synthetic Gloas state where slashing a high-balance proposer triggers an `earliest_exit_epoch` recomputation. The five Electra-formula clients diverge from lodestar.

## Mainnet reachability

**Reachable on canonical traffic at Glamsterdam activation, on every block that contains a proposer slashing.** Proposer slashings are rare on mainnet but not impossible — and the H9 divergence triggers on every such slashing regardless of how rare slashings are individually.

**Trigger A (H9 — lighthouse skips BuilderPendingPayment clearing).** The first Gloas-slot block carrying a proposer slashing whose proposal_epoch is within the 2-epoch window (current or previous epoch from the slashing block's perspective) — i.e., the canonical case for in-protocol slashing. Five clients zero out `state.builder_pending_payments[payment_index]`; lighthouse leaves the field untouched. The post-state `state.builder_pending_payments[payment_index]` therefore differs immediately — `hash_tree_root(state)` diverges on every such block.

**Trigger B (H10 — five clients lag on EIP-8061 exit-churn).** Same trigger as items #6 H8 and #8 H9: `slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn` cascades through the EIP-8061-Modified churn helper. The slashed proposer's `exit_epoch` and `withdrawable_epoch` are written via per_epoch_churn that differs across the 5-vs-1 cohort.

**Severity.** H9 fires on every Gloas-slot proposer-slashing block (the 2-epoch window covers practically all in-protocol slashings — only deeply backdated slashings fall outside, and those are uncommon). H10 fires whenever the slashed proposer's effective_balance triggers an `earliest_exit_epoch` recomputation (also routine). Both materialise immediately as state-root divergence.

**Mitigation window.** Source-only at audit time; no Gloas EF operations fixtures yet for this routine. Closing requires:

- (a) Lighthouse to add a `>= ForkName::Gloas` branch in `process_proposer_slashings` (or its called `verify_proposer_slashing`) that performs the BuilderPendingPayment clearing per the spec's 2-epoch-window logic, using the existing `BeaconStateGloas.builder_pending_payments` field.
- (b) The five Electra-churn clients (prysm, lighthouse, teku, nimbus, grandine) ship the EIP-8061 churn-helper fork-gate before Glamsterdam fork-cut. One coordinated PR per client covers items #2 H6, #3 H8, #4 H8, #6 H8, #8 H9, and this item's H10 together — they all touch the same family of churn accessors.

Without (a), lighthouse forks off on the first slashing block. Without (b), all five forks off on the first slashing block. Combined: every slashing block at Gloas activation produces a 5-way / 6-way state-root split until reconciled.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H8) remain satisfied: header inequality, slot/proposer equality, slashability predicate, per-header runtime-domain BLS signature verification, Pectra-quotient routing through `slash_validator`, and the `MAX_PROPOSER_SLASHINGS == 16` SSZ limit all aligned across the six clients. All 15 EF `proposer_slashing` fixtures still pass uniformly on prysm + lighthouse + lodestar + grandine; teku and nimbus pass internally. The slashing constants (`MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA`, `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA`) are not modified at Gloas, so H7 continues to hold.

**Glamsterdam-target findings (new):**

- **H9** (Gloas EIP-7732 `BuilderPendingPayment` clearing on slash) fails for **lighthouse alone**. The Gloas-modified `process_proposer_slashing` (`vendor/consensus-specs/specs/gloas/beacon-chain.md` "Modified `process_proposer_slashing`") inserts a pre-`slash_validator` step that zeroes out `state.builder_pending_payments[payment_index]` for the slashed proposer's slot if in the current or previous epoch. Five clients implement the clearing (prysm: `gloas.RemoveBuilderPendingPayment` at `proposer_slashing.go:135`; teku: `BlockProcessorGloas.removeBuilderPendingPayment` override at line 322; nimbus: `when typeof(state).kind >= ConsensusFork.Gloas` block at `state_transition_block.nim:202-212`; lodestar: `if (fork >= ForkSeq.gloas)` branch at `processProposerSlashing.ts:34-50`; grandine: Gloas wrapper at `gloas/block_processing.rs:1173-1213`). Lighthouse has the state field allocated and the `builder_pending_payments` upgrade step but **never mutates the vector from per_block_processing/** — the per-block logic has no Gloas branch.
- **H10** (Gloas EIP-8061 churn cascade via `slash_validator`) fails for **5 of 6 clients** — same finding as items #3 H8 / #6 H8 / #8 H9. Each slashed proposer's `exit_epoch` advance is paced via `compute_exit_epoch_and_update_churn`, which 5 of 6 clients still consume via `get_activation_exit_churn_limit` (Electra formula) on Gloas states. Only lodestar uses the Gloas-correct `get_exit_churn_limit`.

Combined `splits` = `[prysm, lighthouse, teku, nimbus, grandine]`. Lighthouse fails both axes; prysm/teku/nimbus/grandine fail only H10; lodestar is spec-aligned on both.

This is the **sixth installment of the EIP-8061 churn family**: items #2 H6 (consolidation), #3 H8 (partial withdrawals), #4 H8 (deposit activation), #6 H8 (voluntary exits + EL full-exits), #8 H9 (attester slashing → `slash_validator`), #9 H10 (proposer slashing → `slash_validator`). Same five lagging clients on all six items.

Notable per-client styles (all observable-equivalent on the Pectra surface):

- **prysm** uses `proto.Equal()` for header inequality and a central `SlashingParamsPerVersion` switch for quotients.
- **lighthouse** uses `verify!()` macros and `state.get_min_slashing_penalty_quotient(spec)` for fork-keyed quotient selection.
- **teku** uses `Objects.equals()` and subclass-override polymorphism for quotients; the Gloas BuilderPendingPayment hook is also injected via subclass override.
- **nimbus** uses Nim's auto-generated struct `!=` and compile-time `when` blocks for fork dispatch.
- **lodestar** uses `ssz.phase0.BeaconBlockHeaderBigint.equals` (NOT `===`) and a 5-deep nested ternary for the penalty quotient; is the only client whose underlying `compute_exit_epoch_and_update_churn` is fork-gated.
- **grandine** uses derived `PartialEq` and type-associated constants; has FOUR `slash_validator` definitions (one per fork: phase0/altair/bellatrix/electra) and the Gloas wrapper at `gloas/block_processing.rs` imports the Electra version explicitly.

Recommendations to the harness and the audit:

- Generate the **T1.3 / T1.4 Gloas BuilderPendingPayment-clearing fixtures** (current-epoch and previous-epoch variants) to pin the H9 lighthouse-only divergence numerically.
- Generate the **T2.5 Gloas churn-cascade fixture** for proposer slashings; sister to items #6 T2.5 / #8 T2.6.
- File the lighthouse Gloas branch in `process_proposer_slashings`. Reference implementations: prysm's `gloas.RemoveBuilderPendingPayment` (Go), teku's `BlockProcessorGloas.removeBuilderPendingPayment` (Java), nimbus's `when typeof(state).kind >= ConsensusFork.Gloas` (Nim), lodestar's `if (fork >= ForkSeq.gloas)` (TypeScript), grandine's `gloas/block_processing.rs` wrapper (Rust).
- Coordinate the **EIP-8061 churn-helper fork-gate** PR per lagging client to close items #2, #3, #4, #6, #8, #9 together.
- Generate the **cross-fork slashing fixture** (T1.2): proposer signs headers across a fork boundary, signature domains differ per-header. Currently no fixture spans a fork boundary.

## Cross-cuts

### With item #6 (`initiate_validator_exit` + `compute_exit_epoch_and_update_churn`)

This item's `slash_validator` calls `initiate_validator_exit(state, proposer_index)` — the same Pectra-modified function audited in item #6. The H10 finding here is identical to item #6's H8 — only the upstream entry-point differs (voluntary exit vs proposer slashing).

### With item #8 (`process_attester_slashing`)

This item and item #8 both call `slash_validator` and both inherit the EIP-8061 cascade. Combined cumulative evidence on the Pectra surface across items #6 (25 fixtures) + #8 (30 fixtures) + #9 (15 fixtures) = 70 operations fixtures × 4 wired clients = **280 PASS** results.

### With Gloas `process_attestation` (item #7 H10 — builder_pending_payments writes)

Item #7 writes to `state.builder_pending_payments[*].weight` from attestation processing (Gloas). This item zeroes out a `BuilderPendingPayment` entry on slashing. If both happen in the same block, the slashing clearing must run AFTER any same-slot attestation weight increments, OR the weights for the slashed proposer's slot are correctly discarded. Verify the operations-ordering invariant matches across clients.

### With `process_slashings` per-epoch helper (WORKLOG #10)

`slash_validator` writes `state.slashings[epoch % EPOCHS_PER_SLASHINGS_VECTOR] += effective_balance`. The per-epoch `process_slashings` reads this vector and applies a proportional penalty. Pectra changed the proportional multiplier.

### With Gloas EIP-7732 ePBS builder lifecycle

This item, item #7 (H10 builder-payment weight increment), and the future `process_builder_pending_payments` (Gloas-new epoch helper) form a triangle around the `state.builder_pending_payments` vector. Each builder slot's lifecycle: weight accumulates from same-slot attestations (item #7), entry is zeroed if the proposer is slashed (this item), entry is settled at epoch boundary (process_builder_pending_payments — separate audit).

## Adjacent untouched Electra/Gloas-active consensus paths

1. **`process_slashings` per-epoch** (WORKLOG #10) — reads `state.slashings` vector this item writes; Pectra changed the multiplier.
2. **Header inequality semantics — what *is* a "different" header?** A field-isolation matrix is small (5 fields × 2 diff/same = 32 cases).
3. **Domain epoch sourced from header.slot vs state.slot** — pyspec computes per-header. A regression to using state's epoch would silently use the wrong fork version when a slashing is included after a fork transition for a pre-fork header.
4. **Source-organization risk in grandine** — 4 `slash_validator` definitions across phase0/altair/bellatrix/electra; future audit walking `use` chains should verify all Pectra/Gloas callers import the Electra version.
5. **Self-slashing reward math** when proposer == whistleblower == slashed. Three increments to the same balance with one decrement.
6. **`MAX_PROPOSER_SLASHINGS == 16` unchanged at Pectra** (vs `MAX_ATTESTER_SLASHINGS_ELECTRA` which was reduced). Asymmetric for a reason worth documenting.
7. **prysm's `ExitInformation` cache reuse** across both slashing types in the same block — stateful fixture: 2 proposer slashings + 1 attester slashing all touching the churn pool.
8. **Lighthouse's `safe_*` overflow-checked arithmetic** in `slash_validator` — quotient `4096` div produces ≥ 1 gwei for any effective_balance ≥ 4096, so the div-by-zero branch is dead code.
9. **Lodestar's BigInt-vs-Number coercion** for `slot` — safe for slot < 2^53 (lifetime of the chain).
10. **Lighthouse's `is_attestation_same_slot` orphan helper** (item #7 H10 finding) — same pattern as the missing Gloas branch here: a helper is defined but not called from per_block_processing. A reviewer might mistake "helper exists" for "Gloas is implemented".
11. **EIP-8061 churn-family standalone audit** — items #2 H6, #3 H8, #4 H8, #6 H8, #8 H9, #9 H10 all share the same five-vs-one cohort. A single coordinated audit item on `compute_exit_epoch_and_update_churn` / `get_exit_churn_limit` / `get_activation_churn_limit` / `get_consolidation_churn_limit` as a family would be the highest-leverage Glamsterdam-readiness item.
12. **Cross-fork slashing fixture** — Proposer signs two block headers straddling a fork epoch boundary; per-header domain computation should pick different fork versions. Currently no EF fixture spans a fork boundary.
