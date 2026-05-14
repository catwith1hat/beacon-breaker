---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [6, 8]
eips: [EIP-7251, EIP-7732, EIP-8061]
prysm_version: v3.2.2-rc.1-2535-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 9: `process_proposer_slashing` (slash_validator pair, Pectra-affected)

## Summary

Second of two slashing operations in a Beacon block. Structurally unchanged from Phase0 at Pectra but inherits the Pectra-modified `slash_validator` primitive: `MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA = 4096` (was 32 in Phase0, 64 in Altair, 128 in Bellatrix–Deneb) and `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA = 4096` (was 512). Unlike voluntary exits (item #6), proposer-slashing signature verification uses **runtime current-fork `DOMAIN_BEACON_PROPOSER`**, NOT a fork-version pin.

**Pectra surface (the function body itself):** all six clients implement the four predicates (slot-eq, proposer-eq, header-inequality, slashability) and signature verification identically, and all six route the Pectra quotients through `slash_validator` correctly. 15/15 EF `proposer_slashing` operations fixtures pass uniformly on the four wired clients (prysm, lighthouse, lodestar, grandine); teku and nimbus pass these in internal CI but the local harness SKIPs them.

**Gloas surface (new at the Glamsterdam target):** all six clients implement the two interlocking Gloas surfaces.

1. **H9 — Gloas EIP-7732 `BuilderPendingPayment` clearing.** Gloas adds a step **before** `slash_validator(state, header_1.proposer_index)` that zeroes out `state.builder_pending_payments[payment_index]` for the slashed proposer's slot if the proposal is within the 2-epoch sliding window (current or previous epoch). Rationale: a slashed proposer's builder bid must not pay out. Survey: all six clients implement the clearing; lighthouse does so via `if state.fork_name_unchecked().gloas_enabled()` branch at `process_operations.rs:398-421`.
2. **H10 — Gloas EIP-8061 churn cascade via `slash_validator`.** `slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn` cascades through the same EIP-8061-Modified churn helper that items #3 H8 / #6 H8 / #8 H9 all share. With those vacated under the per-client Glamsterdam branches, every entry-point — including proposer slashing — inherits the spec-correct `get_exit_churn_limit` pacing across all six clients.

No splits at the current pins. The earlier finding (H9 lighthouse-only divergence + H10 5-vs-1 cohort split) was a stale-pin artifact. Lighthouse `unstable` HEAD `1a6863118` carries both the BuilderPendingPayment clearing AND the inherited churn fork-gate (item #6's name-polymorphism dispatch). The other five clients carry their own Gloas implementations on their respective feature branches.

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

**Consensus relevance**: a proposer slashing transfers `effective_balance` → `state.slashings` vector, reduces slashed proposer's balance, rewards block proposer + whistleblower, and at Gloas clears the slashed proposer's pending builder payment. A divergence in any Pectra-surface bit (predicates, sig domain, quotients) would split the chain immediately. A divergence in H9 (BuilderPendingPayment clearing) would write a different `state.builder_pending_payments` vector. A divergence in H10 (churn cascade) would write different `validators[i].exit_epoch` / `validators[i].withdrawable_epoch` for the slashed proposer. Both are now uniform across all six clients.

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

H1–H10 satisfied across all six clients at the current Glamsterdam-target pins. The Pectra-surface bits (H1–H8) align on body shape; the Gloas-target H9 (BuilderPendingPayment clearing) is implemented by all six clients via six distinct dispatch idioms; the Gloas-target H10 (EIP-8061 churn cascade) inherits from item #6 H8 via the `slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn` chain, and item #6's six dispatch idioms for the churn fork-gate apply here unchanged.

### prysm

`vendor/prysm/beacon-chain/core/blocks/proposer_slashing.go:122-182` — `ProcessProposerSlashings` (process) and `VerifyProposerSlashing` (verify). The Pectra-surface predicates use `proto.Equal(h1, h2)` for header inequality (protobuf-level structural equality over all 5 fields). Domain selector at the verify step uses `signing.Domain(state.fork, epoch, DomainBeaconProposer, ...)` — runtime fork from `state.fork()`, NOT pinned.

**H9 dispatch (Gloas helper module).** At line 135 of `proposer_slashing.go`:

```go
err = gloas.RemoveBuilderPendingPayment(beaconState, slashing.Header_1.Header)
```

`RemoveBuilderPendingPayment` lives in `vendor/prysm/beacon-chain/core/gloas/proposer_slashing.go` and walks the same `current-epoch` / `previous-epoch` payment-index logic as the spec.

`SlashValidator` (`vendor/prysm/beacon-chain/core/validators/validator.go:235-305`) calls `InitiateValidatorExitForTotalBal(ctx, s, slashedIdx, exitInfo, totalActiveBalance)` near the top — same function audited in items #6 / #8. That delegates to `state.ExitEpochAndUpdateChurnForTotalBal(...)`, whose inner `exitEpochAndUpdateChurn` at `vendor/prysm/beacon-chain/state/state-native/setters_churn.go:62-67` uses `helpers.ExitChurnLimitForVersion(b.version, totalActiveBalance)` — the runtime version wrapper that dispatches to `exitChurnLimitGloas` for Gloas (per item #6's H8 dispatch).

H1 ✓ (`proto.Equal`). H2 ✓ (`!=` raw uint64). H3 ✓. H4 ✓. H5 ✓ (runtime-fork domain). H6 ✓ (per-header epoch). H7 ✓ (`SlashingParamsPerVersion(s.Version())` returns Electra constants for `version >= Electra`). H8 ✓. **H9 ✓**. **H10 ✓**.

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing/verify_proposer_slashing.rs:18-65` + `vendor/lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:379-432` (`process_proposer_slashings<E>`). Uses `verify!(header_1 != header_2, ...)` with derived `PartialEq` on `BeaconBlockHeader`. Domain selector `spec.get_domain(epoch, Domain::BeaconProposer, &state.fork(), gvr)` — runtime fork.

**H9 dispatch (runtime `fork_name_unchecked().gloas_enabled()` branch).** `process_proposer_slashings` (`process_operations.rs:398-421`) interleaves the clearing between `verify_proposer_slashing` and `slash_validator`:

```rust
// [New in Gloas:EIP7732]
// Remove the BuilderPendingPayment corresponding to this proposal
// if it is still in the 2-epoch window.
if state.fork_name_unchecked().gloas_enabled() {
    let slot = proposer_slashing.signed_header_1.message.slot;
    let proposal_epoch = slot.epoch(E::slots_per_epoch());
    let slot_in_epoch = slot.as_usize().safe_rem(E::SlotsPerEpoch::to_usize())?;

    let payment_index = if proposal_epoch == state.current_epoch() {
        Some(E::SlotsPerEpoch::to_usize().safe_add(slot_in_epoch)?)
    } else if proposal_epoch == state.previous_epoch() {
        Some(slot_in_epoch)
    } else {
        None
    };

    if let Some(index) = payment_index {
        let payment = state
            .builder_pending_payments_mut()?
            .get_mut(index)
            .ok_or(BlockProcessingError::BuilderPaymentIndexOutOfBounds(index))?;
        *payment = BuilderPendingPayment::default();
    }
}
```

`slash_validator` (`vendor/lighthouse/consensus/state_processing/src/common/slash_validator.rs:16-79`) calls `state.initiate_validator_exit(slashed_index, spec)?` near the top — same as items #6 / #8. That calls `compute_exit_epoch_and_update_churn(effective_balance, spec)?` at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2896-2935`, which now internally fork-gates via `if self.fork_name_unchecked().gloas_enabled() { self.get_exit_churn_limit(spec)? } else { self.get_activation_exit_churn_limit(spec)? }` (per item #6's H8 dispatch).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (via `state.get_min_slashing_penalty_quotient(spec)` / `state.get_whistleblower_reward_quotient(spec)`). H8 ✓. **H9 ✓**. **H10 ✓**.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/common/operations/validation/ProposerSlashingValidator.java:43-69` (validate) + `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/common/block/AbstractBlockProcessor.java:483-508` (mutation). Validation uses `Objects.equals(h1, h2)` for inequality (Container5 structural eq). Domain selection via `beaconStateAccessors.getDomain(BEACON_PROPOSER, epoch, fork, gvr)` — no Electra/Gloas override (correct: proposer domain follows runtime fork).

**H9 dispatch (Java subclass override).** `AbstractBlockProcessor.java:500` calls a protected `removeBuilderPendingPayment(proposerSlashing, state)` hook (declared at `:510` with a no-op default body); `BlockProcessorGloas` overrides this hook at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/block/BlockProcessorGloas.java:322` to implement the spec's 2-epoch-window clearing.

`slashValidator` (`BeaconStateMutators.java`) calls `initiateValidatorExit(state, index, validatorExitContextSupplier)` near the top — same function audited in item #6. The Electra subclass `BeaconStateMutatorsElectra` calls `computeExitEpochAndUpdateChurn(stateElectra, validator.getEffectiveBalance())`; at Gloas, Java virtual dispatch resolves to `BeaconStateMutatorsGloas.computeExitEpochAndUpdateChurn` (`:71-99`) which `@Override`s the Electra method and substitutes `getExitChurnLimit(state)` (per item #6's H8 dispatch).

H1 ✓ (`Objects.equals`). H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (subclass-override polymorphism). H8 ✓. **H9 ✓**. **H10 ✓**.

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:145-185` (`check_proposer_slashing`) + `:195-220` (`process_proposer_slashing*`). Header inequality via `if not (header_1 != header_2)` (Nim's auto-generated `!=`). Domain selector via `verify_block_signature` calling `get_domain(fork, DOMAIN_BEACON_PROPOSER, epoch, gvr)` — runtime fork.

**H9 dispatch (compile-time `when` branch).** `state_transition_block.nim:202-212`:

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

`slash_validator` calls `initiate_validator_exit(cfg, state, slashed_index, exit_queue_info, cache)` at the start — same as items #6 / #8. That calls `compute_exit_epoch_and_update_churn`, whose body at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:353-388` now selects the per-epoch churn at compile time via `when typeof(state).kind >= ConsensusFork.Gloas: get_exit_churn_limit(cfg, state, cache) else: get_activation_exit_churn_limit(...)` (per item #6's H8 dispatch).

H1 ✓ (auto-generated `!=`). H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (compile-time `when state is electra | fulu | gloas`). H8 ✓. **H9 ✓**. **H10 ✓**.

### lodestar

`vendor/lodestar/packages/state-transition/src/block/processProposerSlashing.ts:18-56` + validation at `:58-102`. Header inequality via `ssz.phase0.BeaconBlockHeaderBigint.equals(header1, header2)` (SSZ deep equality — critically NOT `===` reference identity). Domain selector via `config.getDomain(stateSlot, DOMAIN_BEACON_PROPOSER, Number(signedHeader.message.slot))` — runtime fork, per-header epoch.

**H9 dispatch (runtime ternary).** `processProposerSlashing.ts:34-50`:

```typescript
if (fork >= ForkSeq.gloas) {
    // ... compute payment_index for current or previous epoch ...
    (state as CachedBeaconStateGloas).builderPendingPayments.set(
        paymentIndex,
        ssz.gloas.BuilderPendingPayment.defaultViewDU()
    );
}
```

`slashValidator` (`vendor/lodestar/packages/state-transition/src/block/slashValidator.ts:24-59`) calls `initiateValidatorExit(fork, state, slashedIndex)` near the top — same as items #6 / #8. That at `vendor/lodestar/packages/state-transition/src/block/initiateValidatorExit.ts:27-62` calls `computeExitEpochAndUpdateChurn(state, BigInt(validator.effectiveBalance))`. Its body at `vendor/lodestar/packages/state-transition/src/util/epoch.ts:50-77` is the fork-gated runtime ternary (per item #6's H8 dispatch).

H1 ✓ (`equals`). H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (5-deep nested ternary on `ForkSeq`). H8 ✓. **H9 ✓**. **H10 ✓**.

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

The Pectra `slash_validator` (`vendor/grandine/helper_functions/src/electra.rs:153`) is still the one called for Gloas — calls `initiate_validator_exit` → `compute_exit_epoch_and_update_churn`, whose body at `vendor/grandine/helper_functions/src/mutators.rs:172-208` now fork-gates via `if state.is_post_gloas() { get_exit_churn_limit(config, state) } else { get_activation_exit_churn_limit(config, state) }` (per item #6's H8 dispatch).

Source-organization note preserved from prior audit: grandine has FOUR `slash_validator` definitions (one per fork: phase0/altair/bellatrix/electra). Pectra and Gloas callers import the Electra version explicitly.

H1 ✓ (`ensure!`). H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (`P::MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA` compile-time). H8 ✓. **H9 ✓**. **H10 ✓**.

## Cross-reference table

| Client | Verify entry point | Gloas `BuilderPendingPayment` clearing (H9) | `slash_validator` → churn cascade (H10) |
|---|---|---|---|
| prysm | `proposer_slashing.go:122-146` (process), `:149-182` (verify) | ✓ Gloas helper module (`gloas.RemoveBuilderPendingPayment` at `:135`) | ✓ runtime wrapper (`setters_churn.go:67` `helpers.ExitChurnLimitForVersion(b.version, ...)`) |
| lighthouse | `verify_proposer_slashing.rs:18-65`; `process_operations.rs:379-432` | ✓ inline `if state.fork_name_unchecked().gloas_enabled()` branch (`process_operations.rs:398-421`) | ✓ name-polymorphism (`beacon_state.rs:2906-2910` internal `gloas_enabled()` branch) |
| teku | `ProposerSlashingValidator.java:43-69`; `AbstractBlockProcessor.java:483-508` | ✓ subclass override (`BlockProcessorGloas.removeBuilderPendingPayment:322`) | ✓ subclass override (`BeaconStateMutatorsGloas.computeExitEpochAndUpdateChurn:71-99`) |
| nimbus | `state_transition_block.nim:145-185` (check), `:195-220` (process) | ✓ compile-time `when typeof(state).kind >= ConsensusFork.Gloas` (`:202-212`) | ✓ compile-time `when typeof(state).kind >= ConsensusFork.Gloas` (`beaconstate.nim:362-365`) |
| lodestar | `processProposerSlashing.ts:18-56`, validation `:58-102` | ✓ runtime ternary `if (fork >= ForkSeq.gloas)` (`:34-50` clears via `builderPendingPayments.set(...)` to `BuilderPendingPayment.defaultViewDU()`) | ✓ runtime ternary (`util/epoch.ts:50-77` fork-gates `getExitChurnLimit` at `fork >= ForkSeq.gloas`) |
| grandine | `electra/block_processing.rs:627-653` (Electra), `gloas/block_processing.rs:1173-1213` (Gloas wrapper) | ✓ Gloas wrapper calls `mod_index_mut(...) = BuilderPendingPayment::default()` before `slash_validator` | ✓ `state.is_post_gloas()` predicate (`mutators.rs:181-185`) |

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
- **T1.3 (Glamsterdam-target — proposer slashing clears pending builder payment).** Gloas state with `state.builder_pending_payments[payment_index].withdrawal.amount > 0` for the slashed proposer's slot in the current epoch. Expected per Gloas spec: every client resets the entry to `BuilderPendingPayment::default()` before `slash_validator` runs. Cross-client `state_root` should match.
- **T1.4 (Glamsterdam-target — proposer slashing clears previous-epoch builder payment).** Same as T1.3 but the slot is in the previous epoch (`payment_index = slot % SLOTS_PER_EPOCH`). Distinguishes the two-window logic.

#### T2 — Adversarial probes
- **T2.1 (priority — proposer == whistleblower self-slashing).** Block proposer including the slashing IS the slashed validator. Covered by `slashed_and_proposer_index_the_same`.
- **T2.2 (defensive — header inequality boundary).** Headers differ in `state_root` only (typical "two roots, same body" attack). Currently `invalid_headers_are_same_sigs_are_different` covers the dual case; consider a body-equal / state-root-different fixture.
- **T2.3 (defensive — block_header_from_future slot semantics).** `block_header_from_future` confirms header.slot > state.slot is allowed; consider also a header.slot in the past before validator's activation.
- **T2.4 (Glamsterdam-target — slashing outside 2-epoch window).** Gloas state with a slashed proposer whose proposal_epoch is **older** than `get_previous_epoch(state)`. Spec: no `builder_pending_payments` clearing (the entry has already aged out of the 2-epoch window). Verify all six clients leave the vector unchanged for this case.
- **T2.5 (Glamsterdam-target — Gloas churn cascade).** Sister to items #6 T2.5 / #8 T2.6 — synthetic Gloas state where slashing a high-balance proposer triggers an `earliest_exit_epoch` recomputation. Cross-client `state_root` should match.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H8) remain satisfied: header inequality, slot/proposer equality, slashability predicate, per-header runtime-domain BLS signature verification, Pectra-quotient routing through `slash_validator`, and the `MAX_PROPOSER_SLASHINGS == 16` SSZ limit all aligned across the six clients. All 15 EF `proposer_slashing` fixtures still pass uniformly on prysm + lighthouse + lodestar + grandine; teku and nimbus pass internally. The slashing constants (`MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA`, `WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA`) are not modified at Gloas, so H7 continues to hold.

**Glamsterdam-target findings:**

- **H9 ✓ across all six clients.** Every client implements the Gloas-modified pre-`slash_validator` step that zeroes out `state.builder_pending_payments[payment_index]` for the slashed proposer's slot when the proposal_epoch is in the current or previous epoch. Six distinct dispatch idioms: prysm calls a Gloas-module helper (`gloas.RemoveBuilderPendingPayment`); lighthouse uses an inline `if state.fork_name_unchecked().gloas_enabled()` branch in `process_proposer_slashings`; teku uses a Java subclass override hook (`BlockProcessorGloas.removeBuilderPendingPayment`); nimbus uses a compile-time `when typeof(state).kind >= ConsensusFork.Gloas` block; lodestar uses a runtime `if (fork >= ForkSeq.gloas)` ternary; grandine uses a separate `gloas/block_processing.rs` wrapper function.
- **H10 ✓ across all six clients.** `slash_validator → initiate_validator_exit → compute_exit_epoch_and_update_churn` cascades into the EIP-8061-Modified churn helper, which all six clients now fork-gate per the six distinct dispatch idioms catalogued in item #6 (prysm `ExitChurnLimitForVersion` runtime wrapper, lighthouse `fork_name_unchecked().gloas_enabled()` name-polymorphism, teku `BeaconStateMutatorsGloas` subclass override, nimbus compile-time `when`, lodestar runtime ternary, grandine `state.is_post_gloas()` predicate).

The earlier finding (H9 lighthouse-only divergence + H10 5-vs-1 cohort split) was a stale-pin artifact. Lighthouse `unstable` HEAD `1a6863118` carries both the BuilderPendingPayment clearing AND the inherited churn fork-gate; prysm/teku/grandine on their Glamsterdam feature branches and nimbus/lodestar on `unstable` carry their own implementations. With each client now on the branch where its actual Glamsterdam work lives, the cross-client surface is uniform.

This was the **sixth installment of the EIP-8061 churn family** to vacate: items #2 H6 (consolidation), #3 H8 (partial withdrawals), #4 H8 (deposit activation), #6 H8 (voluntary exits + EL full-exits), #8 H9 (attester slashing → `slash_validator`), #9 H10 (proposer slashing → `slash_validator`). All six entry-points now produce uniform post-state across the six clients at Gloas activation.

Notable per-client styles (all observable-equivalent on the Pectra surface):

- **prysm** uses `proto.Equal()` for header inequality and a central `SlashingParamsPerVersion` switch for quotients.
- **lighthouse** uses `verify!()` macros and `state.get_min_slashing_penalty_quotient(spec)` for fork-keyed quotient selection. The Gloas BuilderPendingPayment clearing is inline in the per-slashing loop rather than dispatched through a separate function.
- **teku** uses `Objects.equals()` and subclass-override polymorphism for quotients; the Gloas BuilderPendingPayment hook is also injected via subclass override.
- **nimbus** uses Nim's auto-generated struct `!=` and compile-time `when` blocks for fork dispatch.
- **lodestar** uses `ssz.phase0.BeaconBlockHeaderBigint.equals` (NOT `===`) and a 5-deep nested ternary for the penalty quotient.
- **grandine** uses derived `PartialEq` and type-associated constants; has FOUR `slash_validator` definitions (one per fork: phase0/altair/bellatrix/electra) and the Gloas wrapper at `gloas/block_processing.rs` imports the Electra version explicitly.

Recommendations to the harness and the audit:

- Generate the **T1.3 / T1.4 Gloas BuilderPendingPayment-clearing fixtures** (current-epoch and previous-epoch variants) to convert the source-only H9 conclusion into an empirically-pinned one.
- Generate the **T2.5 Gloas churn-cascade fixture** for proposer slashings; sister to items #6 T2.5 / #8 T2.6.
- Generate the **T2.4 outside-2-epoch-window fixture** to lock the "no-op" branch (proposal_epoch older than previous_epoch).
- Generate the **cross-fork slashing fixture** (T1.2): proposer signs headers across a fork boundary, signature domains differ per-header. Currently no fixture spans a fork boundary.

## Cross-cuts

### With item #6 (`initiate_validator_exit` + `compute_exit_epoch_and_update_churn`)

This item's `slash_validator` calls `initiate_validator_exit(state, proposer_index)` — the same Pectra-modified function audited in item #6. The H10 inheritance here is identical to item #6's H8 — only the upstream entry-point differs (voluntary exit vs proposer slashing). With item #6 H8 vacated, this item's H10 vacates by-construction.

### With item #8 (`process_attester_slashing`)

This item and item #8 both call `slash_validator` and both inherit the EIP-8061 cascade. Combined cumulative evidence on the Pectra surface across items #6 (25 fixtures) + #8 (30 fixtures) + #9 (15 fixtures) = 70 operations fixtures × 4 wired clients = **280 PASS** results.

### With Gloas `process_attestation` (item #7 H10 — builder_pending_payments writes)

Item #7 writes to `state.builder_pending_payments[*].weight` from attestation processing (Gloas). This item zeroes out a `BuilderPendingPayment` entry on slashing. If both happen in the same block, the slashing clearing must run AFTER any same-slot attestation weight increments, OR the weights for the slashed proposer's slot are correctly discarded. Verify the operations-ordering invariant matches across clients.

### With `process_slashings` per-epoch helper (WORKLOG #10)

`slash_validator` writes `state.slashings[epoch % EPOCHS_PER_SLASHINGS_VECTOR] += effective_balance`. The per-epoch `process_slashings` reads this vector and applies a proportional penalty. Pectra changed the proportional multiplier.

### With Gloas EIP-7732 ePBS builder lifecycle

This item, item #7 (H10 builder-payment weight increment), and the future `process_builder_pending_payments` (Gloas-new epoch helper) form a triangle around the `state.builder_pending_payments` vector. Each builder slot's lifecycle: weight accumulates from same-slot attestations (item #7), entry is zeroed if the proposer is slashed (this item), entry is settled at epoch boundary (process_builder_pending_payments — separate audit). With H9 and item #7 H10 now uniform, the producer/clearer sides of the lifecycle are no longer divergence axes; the settlement side remains a future audit.

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
10. **Six-dispatch-idiom uniformity for BuilderPendingPayment clearing** — H9 is now a clean example of how the six clients converge on identical observable Gloas semantics through six different language-idiomatic dispatch mechanisms. Useful reference catalog for future ePBS audits.
11. **EIP-8061 churn-family standalone audit** — items #2 H6, #3 H8, #4 H8, #6 H8, #8 H9, #9 H10 all share the same dispatch-idiom catalog. A single coordinated audit item on `compute_exit_epoch_and_update_churn` / `get_exit_churn_limit` / `get_activation_churn_limit` / `get_consolidation_churn_limit` as a family is now a uniform-implementation cross-cut rather than a divergence axis.
12. **Cross-fork slashing fixture** — Proposer signs two block headers straddling a fork epoch boundary; per-header domain computation should pick different fork versions. Currently no EF fixture spans a fork boundary.
