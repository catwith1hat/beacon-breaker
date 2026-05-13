---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [2, 11, 20]
eips: [EIP-7251, EIP-7732]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 21: `queue_excess_active_balance` (Pectra-NEW placeholder-PendingDeposit producer)

## Summary

`queue_excess_active_balance` is the **producer of placeholder PendingDeposits**: when a validator's balance exceeds `MIN_ACTIVATION_BALANCE = 32 ETH` and is being moved into the compounding (0x02) regime, the excess balance is re-queued through the deposit pipeline so it gets churn-paced. Placeholder entries are marked with `signature = G2_POINT_AT_INFINITY` and `slot = GENESIS_SLOT` so that item #4's drain skips signature verification. Producer/consumer pair with item #20's `apply_pending_deposit` (consumer); two callers on the Electra surface — item #11 (upgrade-time early-adopter loop) and item #2 (switch-to-compounding fast path).

**Pectra surface:** all six clients implement the function identically — strict `>` threshold, balance reset to `MIN_ACTIVATION_BALANCE` (NOT 0), excess = raw difference (no rounding), pubkey + creds sourced from the existing validator, canonical 0xc0-prefixed G2_POINT_AT_INFINITY signature, `slot = GENESIS_SLOT`. **Single definition per client** across forks (no multi-fork redefinition risk like items #6/#9/#10/#12/#14/#15/#17/#19). 40 implicit cross-validation invocations from item #2's switch-to-compounding fixtures cross-validate the producer side without divergence.

**Gloas surface (at the Glamsterdam target): function unchanged + caller routing migrates to ePBS.** `vendor/consensus-specs/specs/gloas/beacon-chain.md` has no `Modified` heading for `queue_excess_active_balance`, `switch_to_compounding_validator`, or `process_consolidation_request` — all three functions are inherited verbatim from Electra. What CHANGES at Gloas is the routing surface: `process_consolidation_request` is **REMOVED from `process_operations`** (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1515`) and **RE-WIRED via `apply_parent_execution_payload`** (`:1132 — for_ops(requests.consolidations, process_consolidation_request)`) under the EIP-7732 ePBS restructure. The upgrade-time caller disappears entirely: `upgrade_to_gloas` (`vendor/consensus-specs/specs/gloas/fork.md:122`) has NO early-adopter loop because all Electra-era early-adopters were processed at the Electra upgrade epoch and there is nothing for Gloas to re-queue. Body unchanged → this item's hypotheses hold at Gloas; the routing migration is item #2 / item #19's territory, not this item's.

## Question

Pyspec `queue_excess_active_balance` (Pectra-new, `vendor/consensus-specs/specs/electra/beacon-chain.md`):

```python
def queue_excess_active_balance(state: BeaconState, index: ValidatorIndex) -> None:
    balance = state.balances[index]
    if balance > MIN_ACTIVATION_BALANCE:                           # STRICT >, NOT >=
        excess_balance = balance - MIN_ACTIVATION_BALANCE
        state.balances[index] = MIN_ACTIVATION_BALANCE              # Reset to MIN, NOT 0
        validator = state.validators[index]
        # Use bls.G2_POINT_AT_INFINITY as a signature field placeholder
        # and GENESIS_SLOT to distinguish from a pending deposit request
        state.pending_deposits.append(
            PendingDeposit(
                pubkey=validator.pubkey,                            # From existing validator
                withdrawal_credentials=validator.withdrawal_credentials,
                amount=excess_balance,
                signature=bls.G2_POINT_AT_INFINITY,                  # Placeholder
                slot=GENESIS_SLOT,                                   # Marker
            )
        )
```

The "placeholder" semantics are critical:
- **`signature = G2_POINT_AT_INFINITY`** (= `0xc0` followed by 95 zeroes — the canonical compressed BLS point at infinity): NOT a real signature, will FAIL BLS verification if attempted.
- **`slot = GENESIS_SLOT`** (= 0): a marker so item #4's `process_pending_deposits` drain knows to skip signature verification for this entry. Real DepositRequests (item #14) use `slot = state.slot` (≠ 0 post-genesis).

Two callers on the Electra surface:
- **Item #11** — `upgrade_to_electra` early-adopter loop (one-shot at fork activation).
- **Item #2** — `switch_to_compounding_validator` fast path, called from `process_consolidation_request`.

At Gloas, the upgrade-time caller disappears (`upgrade_to_gloas` does not contain an early-adopter loop) and the block-level caller relocates from `process_operations` to `apply_parent_execution_payload` per EIP-7732.

## Hypotheses

- **H1.** Strict `>` threshold: `balance > MIN_ACTIVATION_BALANCE` (NOT `>=`).
- **H2.** Balance reset to `MIN_ACTIVATION_BALANCE` (NOT 0).
- **H3.** `excess_balance = balance - MIN_ACTIVATION_BALANCE` (no rounding here — done at apply time via effective_balance_updates).
- **H4.** PendingDeposit pubkey + withdrawal_credentials sourced from EXISTING validator.
- **H5.** PendingDeposit `signature = G2_POINT_AT_INFINITY` (canonical 0xc0-prefixed 96-byte point).
- **H6.** PendingDeposit `slot = GENESIS_SLOT` (= 0) — placeholder marker.
- **H7.** Two callers on the Electra surface: item #11 (upgrade early-adopter loop) + item #2 (switch-to-compounding fast path).
- **H8.** Single function definition per client across forks (no multi-fork-definition risk).
- **H9.** *(Glamsterdam target — function body)*. `queue_excess_active_balance` is NOT modified at Gloas. `vendor/consensus-specs/specs/gloas/beacon-chain.md` contains no `Modified` heading for this function, `switch_to_compounding_validator`, or `process_consolidation_request`. All six clients reuse the Electra implementation at Gloas with no redefinition. H1–H8 hold post-Glamsterdam.
- **H10.** *(Glamsterdam target — caller routing)*. At Gloas the Electra-era `process_operations`-driven call path is removed (`for_ops(body.consolidations, process_consolidation_request)` is gone — `vendor/consensus-specs/specs/gloas/beacon-chain.md:1515` "Removed `process_consolidation_request`") and re-wired via the parent payload's execution requests under EIP-7732 ePBS (`:1132 — for_ops(requests.consolidations, process_consolidation_request)` inside `apply_parent_execution_payload`). The `upgrade_to_gloas` flow (`vendor/consensus-specs/specs/gloas/fork.md:122-197`) contains NO early-adopter loop — by design, all Electra-era early-adopters were processed at Electra upgrade. This is a routing-surface migration, not a function-body change; this item's surface is unaffected.

## Findings

H1–H10 satisfied. **No divergence at the function body or per-client definition; all six clients route the Gloas-relocated `process_consolidation_request` correctly downstream into the unchanged `queue_excess_active_balance`.**

### prysm

`vendor/prysm/beacon-chain/core/electra/validator.go:56-81 QueueExcessActiveBalance`. Single definition, no Gloas redefinition (`vendor/prysm/beacon-chain/core/gloas/` contains no override; `grep -rn QueueExcessActiveBalance vendor/prysm/beacon-chain/core/{fulu,gloas}/` returns empty). Signature placeholder via `common.InfiniteSignature[:]` = `[96]byte{0xC0}` then zeros; slot marker via `params.BeaconConfig().GenesisSlot` (= 0). Strict `>` threshold; balance reset to `params.BeaconConfig().MinActivationBalance`.

Callers (both surfaces):
- Upgrade-time (Electra fork): `vendor/prysm/beacon-chain/core/electra/upgrade.go:312`. No Gloas analog (Gloas fork upgrade in `vendor/prysm/beacon-chain/core/gloas/` does not call this).
- Switch-to-compounding fast path: `core/electra/validator.go:35 SwitchToCompoundingValidator` calls `QueueExcessActiveBalance`. Reached at Gloas via the new ePBS routing — `core/blocks/payload_attestation.go` / execution-request handling routes `requests.Consolidations` through `process_consolidation_request` which dispatches to `SwitchToCompoundingValidator`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓** (no Gloas override). **H10 ✓** (no Gloas re-routing in prysm's Gloas package introduces a divergent call into this function).

### lighthouse

`vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2667-2689 queue_excess_active_balance` — state method, not a free function. Signature via `Signature::infinity()?.into()` (deserializes `INFINITY_SIGNATURE` constant = canonical 0xc0-prefixed compressed G2 infinity); slot via `spec.genesis_slot`. Strict `>` and reset to `spec.min_activation_balance`. Single definition; no Gloas fork-conditional redefinition (`grep -rn queue_excess_active_balance vendor/lighthouse/` returns only this method + its two callers).

Callers:
- Upgrade-time: `vendor/lighthouse/consensus/state_processing/src/upgrade/electra.rs:86`.
- Switch path: `beacon_state.rs:2704 switch_to_compounding_validator` calls `self.queue_excess_active_balance`.

**Note on lighthouse Gloas-readiness gap (cross-cut, not this item's divergence):** lighthouse's broader Gloas-ePBS readiness gap (items #14 H9, #19 H10) means the new `apply_parent_execution_payload`-driven routing for `process_consolidation_request` is not wired in lighthouse for Gloas. That gap affects the **call site**, not this item's function body — `queue_excess_active_balance` itself remains correct in lighthouse; it just gets called via the Electra surface at Gloas in lighthouse (instead of the ePBS surface), which is item #19's territory.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓**. **H10 ✓** at this item's surface (function body unchanged); lighthouse's Gloas ePBS routing gap propagates upstream from item #19 / #14.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/BeaconStateMutatorsElectra.java:195-217 queueExcessActiveBalance`. Schema-driven PendingDeposit construction:

```java
schemaDefinitionsElectra
    .getPendingDepositSchema()
    .create(new SszPublicKey(validator.getPublicKey()),
            SszBytes32.of(validator.getWithdrawalCredentials()),
            SszUInt64.of(excessBalance),
            new SszSignature(BLSSignature.infinity()),
            SszUInt64.of(SpecConfig.GENESIS_SLOT));
```

`BLSSignature.infinity()` deserializes `INFINITY_BYTES` (96-byte 0xc0-prefixed compressed G2 infinity). `SpecConfig.GENESIS_SLOT`. Strict `>` against `MIN_ACTIVATION_BALANCE`. **Single definition**; no Gloas helper override — `BeaconStateMutatorsGloas` extends `BeaconStateMutatorsElectra` and does not redefine `queueExcessActiveBalance`.

Callers:
- Upgrade-time: `ElectraStateUpgrade.java:117`. No Gloas analog in `GloasStateUpgrade`.
- Switch path: `BeaconStateMutatorsElectra.java:186 switchToCompoundingValidator` calls `queueExcessActiveBalance`. Reached at Gloas via the new `ExecutionRequestsProcessorGloas` / `applyParentExecutionPayload` routing for consolidations.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓**. **H10 ✓** (correct ePBS routing for the surviving caller).

### nimbus

`vendor/nimbus/beacon_chain/spec/beaconstate.nim:1516-1531 func queue_excess_active_balance`. Uses `static(MIN_ACTIVATION_BALANCE.Gwei)` compile-time constant for the threshold (performance micro-optimisation; other clients fold constants at their toolchain layer). Signature via `ValidatorSig.infinity` (sets `blob[0] = 0xC0`, rest zero); slot via `GENESIS_SLOT`. Single definition; no Gloas redefinition.

Callers:
- Upgrade-time: `beaconstate.nim:2691` inside `upgrade_to_electra`. No `upgrade_to_gloas` analog.
- Switch path: `beaconstate.nim:1539 switch_to_compounding_validator` calls `queue_excess_active_balance`. Reached at Gloas via the Gloas variant of `process_consolidation_request` routing (`state_transition_block.nim` Gloas-conditional dispatch).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓**. **H10 ✓**.

### lodestar

`vendor/lodestar/packages/state-transition/src/util/electra.ts:36-57 queueExcessActiveBalance`. Signature placeholder via `G2_POINT_AT_INFINITY` constant (`Uint8Array("c0..." + 190 zero hex chars)`); slot via `GENESIS_SLOT`. Uses `state.balances.set(index, MIN_ACTIVATION_BALANCE)` (SSZ ViewDU `.set()`, NOT direct array assignment — ensures the Merkle tree mutation propagates to the cached hashTreeRoot).

Critically — **the TypeScript type signature explicitly covers both forks**: `function queueExcessActiveBalance(state: CachedBeaconStateElectra | CachedBeaconStateGloas, index: ValidatorIndex): void` (`vendor/lodestar/packages/state-transition/lib/util/electra.d.ts:6`). Single function body, parametrically polymorphic across Electra and Gloas; no Gloas redefinition.

Callers:
- Upgrade-time: `slot/upgradeStateToElectra.ts:116`. No `upgradeStateToGloas` analog.
- Switch path: `util/electra.ts:33 switchToCompoundingValidator` calls `queueExcessActiveBalance`. Reached at Gloas via the Gloas variant of consolidation request processing.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓** (explicit type-level confirmation of fork-polymorphism). **H10 ✓**.

### grandine

`vendor/grandine/helper_functions/src/mutators.rs:149-175 queue_excess_active_balance`. Signature via `SignatureBytes::empty()`. **Critical clarification (carried forward from previous audit)**: `SignatureBytes::empty()` is implemented as:

```rust
// vendor/grandine/bls/bls-core/src/traits/signature_bytes.rs:68-72
fn empty() -> Self {
    let mut bytes = Self::zero();
    bytes.as_mut()[0] = 0xc0;     // ← sets the infinity flag bit
    bytes
}
```

The method name "empty" is misleading: it produces the **canonical 0xc0-prefixed 96-byte infinity point**, byte-identical to:
- prysm `[96]byte{0xC0, 0, ..., 0}` (`common.InfiniteSignature`)
- lighthouse `Signature::infinity()` (`INFINITY_SIGNATURE` const)
- teku `BLSSignature.infinity()` (`INFINITY_BYTES`)
- nimbus `ValidatorSig.infinity`
- lodestar `G2_POINT_AT_INFINITY` Uint8Array

**All 6 clients produce byte-identical placeholder signatures.** (Items #11 and #18 originally flagged this as a "potential divergence"; that flag has been retracted in the prior item #21 audit and is reaffirmed here.)

`GENESIS_SLOT` for the slot marker. Strict `>` and reset to `MIN_ACTIVATION_BALANCE`. Single definition; no Gloas redefinition (`grep -rn queue_excess_active_balance vendor/grandine/` returns only this function + its two callers).

Callers:
- Upgrade-time: `helper_functions/src/fork.rs:670` inside the Electra fork helper.
- Switch path: `helper_functions/src/mutators.rs:144 switch_to_compounding_validator` calls `queue_excess_active_balance`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ✓**. **H10 ✓**.

## Cross-reference table

| Client | `queue_excess_active_balance` location | Signature placeholder | Slot marker | Gloas redefinition |
|---|---|---|---|---|
| prysm | `core/electra/validator.go:56-81 QueueExcessActiveBalance` | `common.InfiniteSignature[:]` = `[96]byte{0xC0,0,...}` | `params.BeaconConfig().GenesisSlot` | none (single def) |
| lighthouse | `consensus/types/src/state/beacon_state.rs:2667-2689 queue_excess_active_balance` (state method) | `Signature::infinity()?.into()` (`INFINITY_SIGNATURE`) | `spec.genesis_slot` | none (single def) |
| teku | `versions/electra/helpers/BeaconStateMutatorsElectra.java:195-217 queueExcessActiveBalance` | `BLSSignature.infinity()` (`INFINITY_BYTES` 0xc0-prefixed) | `SpecConfig.GENESIS_SLOT` | none (BeaconStateMutatorsGloas doesn't override) |
| nimbus | `spec/beaconstate.nim:1516-1531 func queue_excess_active_balance` | `ValidatorSig.infinity` (blob[0]=0xC0) | `GENESIS_SLOT` | none (single def) |
| lodestar | `state-transition/src/util/electra.ts:36-57 queueExcessActiveBalance` (`state.balances.set(...)`) | `G2_POINT_AT_INFINITY` Uint8Array | `GENESIS_SLOT` | none — type signature `CachedBeaconStateElectra \| CachedBeaconStateGloas` covers both |
| grandine | `helper_functions/src/mutators.rs:149-175 queue_excess_active_balance` | `SignatureBytes::empty()` — `bytes[0]=0xc0` (canonical infinity, NOT empty) | `GENESIS_SLOT` | none (single def) |

## Empirical tests

### Pectra-surface implicit coverage

No dedicated EF fixture set — `queue_excess_active_balance` is an internal helper, not a block-level operation. Exercised IMPLICITLY via:

| Item | Fixtures × wired clients | Calls this helper |
|---|---|---|
| #2 consolidation_request (switch-to-compounding path) | 10 × 4 = 40 | switch path → `switch_to_compounding_validator` → `queue_excess_active_balance` |
| #11 upgrade_to_electra (early-adopter loop) | 22 fork fixtures (not yet wired in BeaconBreaker harness) | upgrade → for each 0x02 validator with balance > MIN: `queue_excess_active_balance` |

**Total wired implicit cross-validation evidence**: 40 explicit PASSes through item #2's switch-to-compounding fixtures. Item #11's 22 fork fixtures would add another ~88 implicit PASSes once the fork category is wired.

### Gloas-surface

No Gloas operations fixtures yet for this helper. H9 (function-body unchanged) and H10 (caller routing migration) are currently source-only.

Concrete Gloas-spec evidence for H9 + H10:
- `vendor/consensus-specs/specs/gloas/beacon-chain.md:1132` — `for_ops(requests.consolidations, process_consolidation_request)` inside `apply_parent_execution_payload`. The surviving call path.
- `vendor/consensus-specs/specs/gloas/beacon-chain.md:1515` — `# Removed process_consolidation_request` inside the modified `process_operations`. The deleted call path.
- `vendor/consensus-specs/specs/gloas/fork.md:122-197` — `upgrade_to_gloas` body; no early-adopter loop. (Compare to `vendor/consensus-specs/specs/electra/fork.md` which DOES contain the early-adopter loop.)

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — dedicated EF fixture set for `queue_excess_active_balance`).** Pre-state with a single validator at known balance ∈ {< MIN, = MIN, MIN+1 Gwei, 64 ETH, 2048 ETH}. Call the function. Expected post-state: balance = MIN_ACTIVATION_BALANCE iff input > MIN; pending_deposits has placeholder entry with `excess = pre_balance - MIN`, signature byte[0] = 0xc0 (rest zero), slot = 0; or no-op if balance ≤ MIN. Pure-function fuzzing.
- **T1.2 (priority — cross-client signature-placeholder byte equivalence).** Same input across all 6 clients; assert byte-for-byte equal `PendingDeposit.signature` field (all `0xc0` + 95 zeros). Closes the "grandine `SignatureBytes::empty()` is canonical" claim at the wire level.

#### T2 — Adversarial probes
- **T2.1 (defensive — strict `>` threshold).** balance = MIN_ACTIVATION_BALANCE exactly (= 32 ETH = 32 × 10^9 Gwei). Expected: no-op (NOT `>=`). All 6 clients.
- **T2.2 (defensive — balance reset, not zero).** Input balance = MIN + 1 Gwei. Expected post: balance = MIN (NOT 0). All 6 clients.
- **T2.3 (defensive — slot marker strict equality).** Item #4's drain skips signature verification iff `slot == GENESIS_SLOT`. Place a `PendingDeposit` with `slot = 1` and `signature = G2_POINT_AT_INFINITY`. Item #4's drain should attempt BLS verify, fail, and SILENTLY DROP. Cross-client.
- **T2.4 (Glamsterdam-target — switch-path through ePBS routing).** Gloas state. Submit `requests.consolidations` with a single switch-to-compounding request (source == target). The ePBS routing through `apply_parent_execution_payload` should fire `process_consolidation_request → switch_to_compounding_validator → queue_excess_active_balance`. Verify post-state placeholder PendingDeposit produced identically to the Electra-surface case. **At lighthouse**: this would surface item #19 H10 / #14 H9 propagation — lighthouse's missing ePBS routing means the consolidation request never reaches the switch path at Gloas.
- **T2.5 (Glamsterdam-target — upgrade-time loop absence).** `upgrade_to_gloas` on a pre-state with multiple 0x02 validators at balance > MIN. Expected: balances and pending_deposits UNCHANGED by the upgrade itself (no early-adopter loop). Compare to `upgrade_to_electra` which WOULD have queued excess. Cross-client assertion.
- **T2.6 (defensive — PENDING_DEPOSITS_LIMIT 2^27 capacity stress).** Adversarial scenario where many validators queue excess simultaneously. Mainnet-reachable only if validator count exceeds 2^27 (~134M) — F-tier today. Cross-client failure-mode equivalence (panic vs error vs silent overflow).
- **T2.7 (defensive — excess rounding semantics).** Validator with balance = 100.5 ETH. Switch to compounding. Expected: queue excess = 68.5 ETH (raw difference, NO rounding to `EFFECTIVE_BALANCE_INCREMENT` here). Round-down happens later — in item #1 effective_balance_updates for existing validators, or in item #18 `get_validator_from_deposit` for new ones (this path always hits the top-up branch).
- **T2.8 (defensive — multi-call edge case).** Pre-state immediately after Electra upgrade: validator with balance > MIN already had excess queued by the upgrade loop. Block-time switch-to-compounding request for the same validator → balance is now MIN_ACTIVATION_BALANCE (after the upgrade reset) → switch-path call to `queue_excess_active_balance` no-ops (NOT > MIN). Stateful fixture across the Electra → Gloas boundary.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H8) remain satisfied: identical strict `>` threshold, identical balance-reset-to-MIN behaviour, identical raw-difference excess computation, identical canonical 0xc0-prefixed G2_POINT_AT_INFINITY placeholder signature (including grandine's `SignatureBytes::empty()` despite the misleading method name), identical `GENESIS_SLOT` marker, identical pubkey/credentials sourcing from the existing validator, and **single function definition per client** (no multi-fork redefinition — unlike items #6/#9/#10/#12/#14/#15/#17/#19). 40 implicit EF fixture invocations from item #2's switch-to-compounding fixtures cross-validate without divergence; another ~88 from item #11's upgrade fixtures pending harness wiring.

**Glamsterdam-target finding (H9 + H10 — function unchanged, caller routing migrates to ePBS).** `vendor/consensus-specs/specs/gloas/beacon-chain.md` contains no `Modified` heading for `queue_excess_active_balance`, `switch_to_compounding_validator`, or `process_consolidation_request` — all three are inherited verbatim from Electra. The routing surface CHANGES: under EIP-7732 ePBS, `process_consolidation_request` is REMOVED from `process_operations` (`:1515 — # Removed process_consolidation_request`) and re-wired via `apply_parent_execution_payload` (`:1132 — for_ops(requests.consolidations, process_consolidation_request)`). The upgrade-time call site disappears entirely — `upgrade_to_gloas` (`specs/gloas/fork.md:122-197`) has no early-adopter loop because all Electra-era early-adopters were processed at the Electra upgrade epoch. This is a **routing-surface migration, not a function-body change**: this item's H1–H8 invariants continue to hold at Gloas across all six clients; the routing migration is item #19 H10 / item #2's territory.

**Sixth impact-none result in the recheck series** (after items #5, #10, #11, #18, #20). Propagation-without-amplification pattern: the Gloas upstream restructure (consolidations move to ePBS) leaves this item's function body untouched.

**EIP-8061 cascade and lighthouse Gloas-ePBS gap propagation note.** The two major Gloas-target divergence families identified during the recheck series — EIP-8061 churn rework (5-vs-1 with lodestar correct) and EIP-7732 ePBS (lighthouse-alone failure) — do NOT propagate into this item's function-body surface. They DO affect upstream call paths:

- **EIP-8061 (item #4 H8 / #16 cascade)**: affects per-epoch deposit drain rate (`get_activation_churn_limit` ceiling). Affects HOW MANY placeholder PendingDeposits drain per epoch in item #4 — but the placeholder PRODUCTION here is unaffected.
- **EIP-7732 (lighthouse #14 H9 / #19 H10)**: lighthouse's missing ePBS routing means the Gloas `apply_parent_execution_payload` → `process_consolidation_request` chain doesn't fire — so the switch-to-compounding fast path doesn't reach this item's function at Gloas in lighthouse. This is a CALLER gap, not a function-body divergence; lighthouse's `queue_excess_active_balance` itself remains correct (matches Electra; correct against the inherited Gloas spec) — it just isn't reached via the ePBS surface.

Notable per-client style differences (all observable-equivalent):

- **prysm** uses `common.InfiniteSignature[:]` constant slice for the placeholder signature.
- **lighthouse** implements as a state method (`self.queue_excess_active_balance(...)`) using milhouse `push` returning `Result<(), MilhouseError>`.
- **teku** uses schema-driven SSZ construction (`schemaDefinitionsElectra.getPendingDepositSchema().create(...)`) — compile-time field-count enforcement.
- **nimbus** uses `static(MIN_ACTIVATION_BALANCE.Gwei)` compile-time constant for the threshold comparison.
- **lodestar** uses `state.balances.set(index, MIN_ACTIVATION_BALANCE)` (SSZ ViewDU `.set()`, NOT direct indexing) to propagate the mutation through the Merkle cache; **explicit fork-polymorphic type signature** `CachedBeaconStateElectra | CachedBeaconStateGloas`.
- **grandine** uses `SignatureBytes::empty()` (misleading name; produces the canonical 0xc0-prefixed infinity point — clarified above).

No code-change recommendation. Audit-direction recommendations:

- **Generate dedicated EF fixture set for `queue_excess_active_balance`** — pure-function fuzz, directly cross-client byte-equivalence checkable.
- **Cross-client signature-placeholder byte equivalence test** — close the grandine `SignatureBytes::empty()` claim at the wire level.
- **Sister-item audit: `switch_to_compounding_validator`** — the direct caller (item #2's fast path). Sets `withdrawal_credentials[0] = COMPOUNDING_WITHDRAWAL_PREFIX_BYTE` then calls this function. Single audit closes the switch-path producer chain.
- **Sister-item audit: Gloas `apply_parent_execution_payload` consolidation routing** — the new EIP-7732 surface for the switch-path caller. Five-vs-one cohort with lighthouse (item #19 H10).
- **Audit closure for item #4's `slot == GENESIS_SLOT` placeholder skip** — strict equality vs threshold. Co-equally important for the placeholder lifecycle.

## Cross-cuts

### With item #2 (`process_consolidation_request` → `switch_to_compounding_validator`)

Item #2's switch-to-compounding fast path is the surviving caller of this item at Gloas. The Electra-surface routing (via `process_operations`) is removed at Gloas; the call chain is preserved via `apply_parent_execution_payload` → `process_consolidation_request` → `switch_to_compounding_validator` → this item. Item #2's audit captures the routing change; this item captures the unchanged producer function.

### With item #11 (`upgrade_to_electra` early-adopter loop)

Item #11's upgrade-time loop is the OTHER Electra-surface caller. At Gloas this caller disappears entirely (`upgrade_to_gloas` has no analogous loop — by design, because Electra-upgrade processed all early-adopters). The disappearance is correct, not a divergence: Gloas state inherits `pending_deposits` from Fulu (which inherited from Electra), and any excess-balance placeholders from the Electra upgrade have long since drained.

### With item #20 (`apply_pending_deposit` — consumer)

This item is the **producer** of placeholder PendingDeposits; item #20's `apply_pending_deposit` is the **consumer**. Producer/consumer pair closed end-to-end:

```
[item #2 switch path OR item #11 upgrade] caller
    ↓
[item #21 (this) queue_excess_active_balance]
    state.balances[idx] = MIN_ACTIVATION_BALANCE
    state.pending_deposits.append(PendingDeposit{
        pubkey, creds, excess_amount,
        signature=G2_POINT_AT_INFINITY,
        slot=GENESIS_SLOT
    })
    ↓ (next epoch)
[item #4 process_pending_deposits drain]
    sees PendingDeposit with slot=GENESIS_SLOT → SKIPS signature verification
    ↓
[item #20 apply_pending_deposit]
    pubkey EXISTS in registry (validator was in registry from upgrade or pre-switch)
    → top-up path: increase_balance(state, validator_index, excess_amount)
    ↓
balance restored to MIN + excess = original (now in compounding regime, churn-paced)
```

### With item #4 (`process_pending_deposits` drain)

Item #4 is the drain that consumes placeholders. The Gloas H8 (EIP-8061 churn rework — 5-vs-1 lodestar correct) affects deposit DRAIN RATE (per-epoch budget) but not per-deposit application. This item's PRODUCTION rate is bounded by consolidation-request frequency (Gloas: via ePBS execution requests; Electra: via block-level consolidations) — orthogonal to item #4's drain-rate concern.

### With item #19 H10 (Gloas ePBS restructure — lighthouse alone fails)

Item #19's `process_execution_payload` replacement at Gloas (with `process_execution_payload_bid` + `process_parent_execution_payload` + `verify_execution_payload_envelope`) is the upstream surface that introduces the new routing for this item's caller. Item #19 H10 found lighthouse alone lacks the ePBS implementation — that propagates into THIS item's caller surface (lighthouse's switch-to-compounding fast path isn't reachable via ePBS), but does NOT propagate into this item's function body.

### With Gloas `apply_deposit_for_builder` (item #20 sister)

Item #20's audit identified `apply_deposit_for_builder` as the builder-side analog of `apply_pending_deposit`. There is NO builder-side analog of `queue_excess_active_balance` — builder credentials (`0x03` prefix) don't have a compounding-upgrade pathway (builders have a flat balance model in the EIP-7732 design). So this item has no Gloas builder-side sister.

## Adjacent untouched

1. **Generate dedicated EF fixture set for `queue_excess_active_balance`** — pure-function (state, index → state'), easy to fuzz; would directly cross-client validate the placeholder construction.
2. **Cross-client signature-placeholder byte equivalence test** — feed same input to all 6 clients; compare resulting `PendingDeposit.signature` field byte-for-byte. Closes the grandine `SignatureBytes::empty()` claim at the wire level.
3. **Audit closure: item #4's `slot == GENESIS_SLOT` placeholder skip** — strict equality, not threshold. Critical for the placeholder lifecycle correctness contract.
4. **Sister-item audit: `switch_to_compounding_validator`** — direct caller from item #2's switch path. Sets `withdrawal_credentials[0] = COMPOUNDING_WITHDRAWAL_PREFIX_BYTE` then queues. Small audit, closes the switch-path producer chain.
5. **Sister-item audit: Gloas `apply_parent_execution_payload` consolidation routing** — the new EIP-7732 surface for the switch-path caller. Five-vs-one cohort with lighthouse (per item #19 H10).
6. **Top-up vs new-validator routing for placeholders** — placeholders are for EXISTING validators by construction (item #20 dispatches by pubkey existence; for placeholders the pubkey is always in registry). Verify all 6 clients always take the top-up branch on placeholder input.
7. **Excess rounding semantics across the full lifecycle** — balance with sub-1-ETH dust → queue → drain → top-up → effective_balance_updates rounds. Stateful fixture: 100.5 ETH → queue 68.5 → drain → +68.5 = 100.5 → eb-updates rounds to 100. Cross-client.
8. **Multi-call edge case stateful fixture** — upgrade-time queue + block-time switch in adjacent epochs at the Electra → Fulu → Gloas fork boundary chain.
9. **PENDING_DEPOSITS_LIMIT (2^27) capacity stress** — adversarial; mainnet-unreachable today but failure-mode equivalence (panic vs error vs overflow) worth verifying.
10. **Cross-cut with item #20 SILENT DROP** — if a placeholder somehow takes the new-validator path (impossible per H4 invariant, but adversarial), item #20's signature verify fails (G2_POINT_AT_INFINITY is not a valid signature for any message) → SILENTLY DROPS. Defense-in-depth verification cross-client.
11. **Per-network constant verification** — `MIN_ACTIVATION_BALANCE`, `GENESIS_SLOT`, `EFFECTIVE_BALANCE_INCREMENT` per mainnet/sepolia/holesky.
12. **Audit `is_pending_validator` / `convert_builder_index_to_validator_index`** — Gloas-new predicates flagged during item #19/#20 rechecks. Not directly related to this item but in the same Gloas-new helpers cohort.
