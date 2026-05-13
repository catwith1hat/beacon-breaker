---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [2, 21, 22]
eips: [EIP-7251, EIP-7732]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 24: `is_valid_switch_to_compounding_request` (Pectra-NEW 6-check security gate for the switch path)

## Summary

`is_valid_switch_to_compounding_request(state, consolidation_request) -> bool` is the Pectra-NEW 6-check security gate that runs before `switch_to_compounding_validator` (item #22) and `queue_excess_active_balance` (item #21) execute from item #2's `process_consolidation_request` switch fast path. A `ConsolidationRequest` with `source_pubkey == target_pubkey` is recognized as a "self-consolidation" → switch-to-compounding request; this predicate decides whether to accept it. The 6 checks are: (1) source == target; (2) source pubkey exists; (3) `creds[12:32] == source_address` (proves the EL transaction was signed by the holder of the embedded eth1 address); (4) source has `0x01` credentials; (5) source is active; (6) source has not initiated exit.

**Pectra surface:** all six clients implement the predicate as a 6-check all-conjunction returning `false` on any failure. H1–H9 hold. Two style divergences (carried forward from the 2026-05-02 audit, both observable-equivalent): nimbus + lodestar HOIST the pubkey-existence check OUT of the predicate to the caller; lodestar additionally REORDERS pubkey-exists before source==target. prysm carries a DUPLICATE implementation (public `IsValidSwitchToCompoundingRequest` in `core/electra/consolidations.go` and private `isValidSwitchToCompoundingRequest` in `core/requests/consolidations.go`) — same forward-fragility concern as items #21, #22.

**Gloas surface (at the Glamsterdam target): function body unchanged + caller routing migrates to ePBS.** `vendor/consensus-specs/specs/gloas/beacon-chain.md` does not contain a `Modified is_valid_switch_to_compounding_request` heading; the function is inherited verbatim from Electra. Its dependencies (`has_eth1_withdrawal_credential`, `is_active_validator`) are also unchanged at Gloas. What CHANGES is the routing surface: under EIP-7732 ePBS, `process_consolidation_request` is REMOVED from `process_operations` (`:1515 — # Removed process_consolidation_request`) and re-wired via `apply_parent_execution_payload` (`:1132 — for_ops(requests.consolidations, process_consolidation_request)`). The predicate is reached through the new ePBS surface, but its body and decision semantics are unchanged. Same routing-surface migration as items #21, #22 — this item is on the receiving end of the migration, not the source.

**Cross-cut with item #22 H12 (nimbus stale `has_compounding_withdrawal_credential`)**: this predicate uses `has_eth1_withdrawal_credential` (item #22's strict-`0x01` predicate), NOT `has_compounding_withdrawal_credential` (item #22's stale-Gloas-aware predicate). All 6 clients implement `has_eth1_withdrawal_credential` as strict-`0x01` at Gloas — nimbus's H12 divergence does NOT propagate here. A `0x03` (builder-credentialled) validator submitting a switch request would correctly fail at Check 4 on all 6 clients.

**Lighthouse Gloas-readiness gap (items #14 H9 / #19 H10 / #22 H10 / #23 H8 propagation)**: lighthouse's missing ePBS routing means switch requests don't reach this predicate at all at Gloas in lighthouse — a CALLER-surface gap, not a function-body divergence. This item's predicate is correct in isolation; the gap lives upstream at items #19 / #14.

**Impact: none.** Seventh impact-none result in the recheck series. Propagation-without-amplification.

## Question

Pyspec Pectra-NEW (`vendor/consensus-specs/specs/electra/beacon-chain.md:1828-1864`):

```python
def is_valid_switch_to_compounding_request(
    state: BeaconState, consolidation_request: ConsolidationRequest
) -> bool:
    # Switch to compounding requires source and target be equal
    if consolidation_request.source_pubkey != consolidation_request.target_pubkey:
        return False
    # Verify pubkey exists
    source_pubkey = consolidation_request.source_pubkey
    validator_pubkeys = [v.pubkey for v in state.validators]
    if source_pubkey not in validator_pubkeys:
        return False
    source_validator = state.validators[
        ValidatorIndex(validator_pubkeys.index(source_pubkey))
    ]
    # Verify request has been authorized
    if source_validator.withdrawal_credentials[12:] != consolidation_request.source_address:
        return False
    # Verify source withdrawal credentials
    if not has_eth1_withdrawal_credential(source_validator):
        return False
    # Verify the source is active
    current_epoch = get_current_epoch(state)
    if not is_active_validator(source_validator, current_epoch):
        return False
    # Verify exit for source has not been initiated
    if source_validator.exit_epoch != FAR_FUTURE_EPOCH:
        return False
    return True
```

Called from `process_consolidation_request` (`vendor/consensus-specs/specs/electra/beacon-chain.md:1872`):

```python
if is_valid_switch_to_compounding_request(state, consolidation_request):
    switch_to_compounding_validator(state, source_index)
    return
```

At Gloas, `process_consolidation_request` is inherited unchanged from Electra. The `for_ops(requests.consolidations, process_consolidation_request)` call site MOVES from `process_operations` (`vendor/consensus-specs/specs/electra/beacon-chain.md:1502`) to `apply_parent_execution_payload` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1132`) under EIP-7732 ePBS routing.

Three recheck questions:
1. Do all six clients still implement the Pectra-surface 6-check all-conjunction semantics (H1–H9)?
2. **At Gloas**: any client modify this predicate (e.g., to also accept `0x03` builder credentials, or to add a builder-side analog)? Or any client's dependency predicate (`has_eth1_withdrawal_credential`) drift Gloas-aware?
3. Does the new ePBS routing surface introduce any per-client caller gap that would prevent this predicate from being reached?

## Hypotheses

- **H1.** 6 checks in spec order: source==target → pubkey exists → `creds[12:]==source_address` → `has_eth1` → `is_active` → `exit_epoch == FAR_FUTURE`.
- **H2.** Returns `false` on ANY failure (any-of-6 short-circuit).
- **H3.** Returns `true` ONLY if all 6 pass (all-of-6 conjunction).
- **H4.** `withdrawal_credentials[12:32]` is a 20-byte slice (eth1 address embedded in the 32-byte credentials).
- **H5.** Pubkey lookup uses cached `pubkey → index` map (NOT linear scan; spec's `validator_pubkeys.index` is for readability).
- **H6.** Check 4 uses `has_eth1_withdrawal_credential` (item #22 strict-`0x01` predicate).
- **H7.** Check 5 uses `is_active_validator(source_validator, current_epoch)` (phase0 helper, unchanged across all forks).
- **H8.** Check 6 is strict `!=` comparison `source_validator.exit_epoch != FAR_FUTURE_EPOCH`.
- **H9.** Predicate is called BEFORE the main consolidation path in `process_consolidation_request` (the switch fast path).
- **H10.** *(Glamsterdam target — function body)*. `is_valid_switch_to_compounding_request` is NOT modified at Gloas. No `Modified is_valid_switch_to_compounding_request` heading exists in `vendor/consensus-specs/specs/gloas/beacon-chain.md` — the function is inherited from Electra. Dependencies (`has_eth1_withdrawal_credential`, `is_active_validator`) are unchanged. All six clients reuse the Electra implementation at Gloas with no Gloas-conditional fork-dispatch in the predicate body.
- **H11.** *(Glamsterdam target — caller routing)*. At Gloas, the predicate is reached through the new EIP-7732 ePBS routing surface: `apply_parent_execution_payload` (`:1132`) → `process_consolidation_request` (inherited from Electra, unchanged body) → `is_valid_switch_to_compounding_request` (this item). The Electra `process_operations`-driven path is removed. This is the same routing-surface migration as items #21 H10 / #22 H12-context. The migration is item #19 / item #2's territory; this item's surface is unaffected.
- **H12.** *(Glamsterdam target — item #22 nimbus divergence does not propagate)*. Nimbus's stale `has_compounding_withdrawal_credential` Gloas-aware OR-fold (item #22 H12) does NOT affect this predicate. Check 4 uses `has_eth1_withdrawal_credential` (strict-`0x01`), not `has_compounding`. A `0x03` validator submitting a switch request fails Check 4 on all 6 clients → predicate returns `false`. No divergence.

## Findings

H1–H12 satisfied. **No divergence at the function body or per-client definition; predicate is correct in isolation across all six clients at both Pectra and Gloas surfaces.**

### prysm

`vendor/prysm/beacon-chain/core/electra/consolidations.go:93-172 IsValidSwitchToCompoundingRequest` (PUBLIC) — line-identical DUPLICATE in `vendor/prysm/beacon-chain/core/requests/consolidations.go:240-278 isValidSwitchToCompoundingRequest` (private). Forward-fragility concern carried forward from prior audits (same pattern as items #21 / #22 prysm duplications).

```go
func IsValidSwitchToCompoundingRequest(st state.BeaconState, req *enginev1.ConsolidationRequest) bool {
    if req.SourcePubkey == nil || req.TargetPubkey == nil {
        return false
    }
    if !bytes.Equal(req.SourcePubkey, req.TargetPubkey) {
        return false
    }
    srcIdx, ok := st.ValidatorIndexByPubkey(bytesutil.ToBytes48(req.SourcePubkey))
    if !ok {
        return false
    }
    srcV, err := st.ValidatorAtIndexReadOnly(srcIdx)
    if err != nil {
        return false
    }
    sourceAddress := req.SourceAddress
    withdrawalCreds := srcV.GetWithdrawalCredentials()
    if len(withdrawalCreds) != 32 || len(sourceAddress) != 20 ||
       !bytes.HasSuffix(withdrawalCreds, sourceAddress) {
        return false
    }
    if !srcV.HasETH1WithdrawalCredentials() {
        return false
    }
    curEpoch := slots.ToEpoch(st.Slot())
    if !helpers.IsActiveValidatorUsingTrie(srcV, curEpoch) {
        return false
    }
    if srcV.ExitEpoch() != params.BeaconConfig().FarFutureEpoch {
        return false
    }
    return true
}
```

Notable: prysm uses `bytes.HasSuffix(withdrawalCreds, sourceAddress)` instead of an explicit `creds[12:32]` slice. For 32-byte `creds` and 20-byte `sourceAddress`, this is observable-equivalent (since `32 - 20 = 12`). Explicit length validation `len(withdrawalCreds) != 32 || len(sourceAddress) != 20` is dead defensive code today (SSZ schema enforces lengths) but forward-resilient.

`HasETH1WithdrawalCredentials` is the strict-`0x01` predicate from item #22 (`vendor/prysm/beacon-chain/state/state-native/readonly_validator.go:94-96`). No Gloas fork-conditional in the predicate body. The predicate's caller (`process_consolidation_request`) is the Pectra-surface entry point at the moment; at Gloas, the call would route through the new ePBS surface — that wiring is item #19's territory.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (cached `ValidatorIndexByPubkey`). H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓ (uses strict `HasETH1WithdrawalCredentials`).

### lighthouse

`vendor/lighthouse/consensus/state_processing/src/per_block_processing/process_operations.rs:629-682`:

```rust
fn is_valid_switch_to_compounding_request<E: EthSpec>(
    state: &BeaconState<E>,
    consolidation_request: &ConsolidationRequest,
    spec: &ChainSpec,
) -> Result<bool, BlockProcessingError> {
    if consolidation_request.source_pubkey != consolidation_request.target_pubkey {
        return Ok(false);
    }
    let Some(source_index) = state.pubkey_cache().get(&consolidation_request.source_pubkey) else {
        return Ok(false);
    };
    let source_validator = state.get_validator(source_index)?;

    // Note: We need to specifically check for eth1 withdrawal credentials here
    // If the validator is already compounding, the compounding request is not valid.
    if let Some(withdrawal_address) = source_validator
        .has_eth1_withdrawal_credential(spec)
        .then(|| {
            source_validator.withdrawal_credentials.as_slice().get(12..).map(Address::from_slice)
        })
        .flatten()
    {
        if withdrawal_address != consolidation_request.source_address {
            return Ok(false);
        }
    } else {
        return Ok(false);
    }

    let current_epoch = state.current_epoch();
    if !source_validator.is_active_at(current_epoch) {
        return Ok(false);
    }
    if source_validator.exit_epoch != spec.far_future_epoch {
        return Ok(false);
    }
    Ok(true)
}
```

Returns `Result<bool, BlockProcessingError>`. Pubkey-cache lookup via `state.pubkey_cache().get(...)`. **Fuses Checks 3 and 4** (creds[12:] match AND has_eth1) into a single `.then(|| ...).flatten()` chain — observable-equivalent: if not eth1, the `else` returns false (covers Check 4 failure); if eth1, the inner `if withdrawal_address != source_address` returns false (covers Check 3 failure); if both pass, control continues. Safe `.get(12..)` returns `Option<&[u8]>` (None on out-of-bounds — academic given SSZ length enforcement, but panic-free).

`has_eth1_withdrawal_credential(spec)` is the strict-`0x01` validator method from item #22 (`vendor/lighthouse/consensus/types/src/validator/validator.rs:159-165`). No Gloas fork-conditional. The Gloas-readiness gap at H8/H10 in adjacent items (items #14/#19/#22/#23) is a CALLER-surface gap — lighthouse's `process_consolidation_request` itself is wired but reached via the Electra surface (`process_operations`); at Gloas, the ePBS-surface call from `apply_parent_execution_payload` is missing. That's separate from this predicate's correctness.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓ (fused with Check 3). H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓ at predicate-body level; lighthouse's broader ePBS routing gap is upstream. H12 ✓.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/execution/ExecutionRequestsProcessorElectra.java:443-482 isValidSwitchToCompoundingRequest`:

```java
private boolean isValidSwitchToCompoundingRequest(
    final BeaconState state, final ConsolidationRequest consolidationRequest) {
  if (!consolidationRequest.getSourcePubkey().equals(consolidationRequest.getTargetPubkey())) {
    return false;
  }
  final Optional<Integer> maybeSourceValidatorIndex =
      validatorsUtil.getValidatorIndex(state, consolidationRequest.getSourcePubkey());
  if (maybeSourceValidatorIndex.isEmpty()) {
    return false;
  }
  final int sourceValidatorIndex = maybeSourceValidatorIndex.get();
  final Validator sourceValidator = state.getValidators().get(sourceValidatorIndex);

  final Eth1Address sourceValidatorExecutionAddress =
      Predicates.getExecutionAddressUnchecked(sourceValidator.getWithdrawalCredentials());
  if (!sourceValidatorExecutionAddress.equals(
      Eth1Address.fromBytes(consolidationRequest.getSourceAddress().getWrappedBytes()))) {
    return false;
  }
  if (!predicates.hasEth1WithdrawalCredential(sourceValidator)) {
    return false;
  }
  final UInt64 currentEpoch = miscHelpers.computeEpochAtSlot(state.getSlot());
  if (!predicates.isActiveValidator(sourceValidator, currentEpoch)) {
    return false;
  }
  return sourceValidator.getExitEpoch().equals(FAR_FUTURE_EPOCH);
}
```

`Predicates.getExecutionAddressUnchecked(creds)` extracts `creds.slice(12)` (20 bytes for `Bytes32`). Naming convention: "unchecked" means it doesn't validate `creds[0] == 0x01` — Check 4 is responsible for that downstream. `predicates.hasEth1WithdrawalCredential(sourceValidator)` is the strict-`0x01` predicate from item #22 (`PredicatesElectra.java`); `PredicatesGloas` extends `PredicatesElectra` without overriding it.

No Gloas helper override of this predicate. The `ExecutionRequestsProcessorElectra` is the Pectra-surface processor; teku's Gloas processor (`ExecutionRequestsProcessorGloas`) inherits the consolidation-handling path through subclass extension.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓.

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:626-655`:

```nim
func is_valid_switch_to_compounding_request(
    state: electra.BeaconState | fulu.BeaconState | gloas.BeaconState,
    consolidation_request: ConsolidationRequest,
    source_validator: Validator): bool =
  # Switch to compounding requires source and target be equal
  if consolidation_request.source_pubkey != consolidation_request.target_pubkey:
    return false

  # process_consolidation_request() verifies pubkey exists

  # Verify request has been authorized
  if source_validator.withdrawal_credentials.data.toOpenArray(12, 31) !=
      consolidation_request.source_address.data:
    return false

  # Verify source withdrawal credentials
  if not has_eth1_withdrawal_credential(source_validator):
    return false

  # Verify the source is active
  let current_epoch = get_current_epoch(state)
  if not is_active_validator(source_validator, current_epoch):
    return false

  # Verify exit for source has not been initiated
  if source_validator.exit_epoch != FAR_FUTURE_EPOCH:
    return false

  true
```

**Pubkey-existence check HOISTED** to caller `process_consolidation_request` at `:664-669`:

```nim
let
  request_source_pubkey = consolidation_request.source_pubkey
  source_index = findValidatorIndex(
      state.validators.asSeq, bucketSortedValidators,
      request_source_pubkey).valueOr:
    return

if is_valid_switch_to_compounding_request(
    state, consolidation_request, state.validators.item(source_index)):
  switch_to_compounding_validator(state, source_index)
  return
```

Predicate signature takes pre-resolved `source_validator: Validator` (NOT `state` + `pubkey`). Type-safe API: precondition (validator exists) is in the type signature. Comment at line 635 explicitly documents the hoist: `# process_consolidation_request() verifies pubkey exists`.

Generic over `electra.BeaconState | fulu.BeaconState | gloas.BeaconState` — same body across all three forks; no Gloas-conditional `when` branch. Critically, **nimbus's stale `has_compounding_withdrawal_credential` Gloas-aware OR-fold from item #22 does NOT propagate here** — Check 4 calls `has_eth1_withdrawal_credential` (`:1467-1469`), which is strict-`0x01` across all forks.

`toOpenArray(12, 31)` is Nim's inclusive-range slice (bytes 12 through 31 inclusive = 20 bytes). Most explicit byte-range expression of the six.

H1 ✓ (5/6 of the original spec checks; pubkey hoisted to caller). H2 ✓. H3 ✓. H4 ✓. H5 ✓ (`bucketSortedValidators` cached lookup). H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓ (uses strict `has_eth1_withdrawal_credential`).

### lodestar

`vendor/lodestar/packages/state-transition/src/block/processConsolidationRequest.ts:107-149 isValidSwitchToCompoundRequest`:

```typescript
function isValidSwitchToCompoundRequest(
  state: CachedBeaconStateElectra | CachedBeaconStateGloas,
  consolidationRequest: electra.ConsolidationRequest
): boolean {
  const {sourcePubkey, targetPubkey, sourceAddress} = consolidationRequest;
  const sourceIndex = state.epochCtx.getValidatorIndex(sourcePubkey);
  const targetIndex = state.epochCtx.getValidatorIndex(targetPubkey);

  // Verify pubkey exists
  if (sourceIndex === null) {
    // this check is mainly to make the compiler happy, pubkey is checked by the consumer already
    return false;
  }

  // Switch to compounding requires source and target be equal
  if (sourceIndex !== targetIndex) {
    return false;
  }

  const sourceValidator = state.validators.getReadonly(sourceIndex);
  const sourceWithdrawalAddress = sourceValidator.withdrawalCredentials.subarray(12);
  if (!byteArrayEquals(sourceWithdrawalAddress, sourceAddress)) {
    return false;
  }

  if (!hasEth1WithdrawalCredential(sourceValidator.withdrawalCredentials)) {
    return false;
  }

  if (!isActiveValidator(sourceValidator, state.epochCtx.epoch)) {
    return false;
  }

  if (sourceValidator.exitEpoch !== FAR_FUTURE_EPOCH) {
    return false;
  }

  return true;
}
```

**Reorders checks 1 and 2** (pubkey-exists comes first, then source==target). Observable-equivalent: comment at line 117 explicitly notes the pubkey-exists check is for the type system (`null` narrowing). The caller at line 32 (`processConsolidationRequest`) ALSO checks `isPubkeyKnown` before invoking — the in-predicate check is defensive.

Type signature `CachedBeaconStateElectra | CachedBeaconStateGloas` confirms single body across both forks; no Gloas fork-dispatch. `hasEth1WithdrawalCredential` is the strict-`0x01` predicate from item #22 (`util/electra.ts`). Note the subtle index-equality short-circuit: `sourceIndex !== targetIndex` is equivalent to `source_pubkey != target_pubkey` GIVEN both pubkeys resolve to valid indices (which the previous null check ensures).

H1 ✓ (5/6 in non-spec order; pubkey-exists first, source==target second; observable-equivalent). H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓.

### grandine

`vendor/grandine/transition_functions/src/electra/block_processing.rs:1296-1346`:

```rust
fn is_valid_switch_to_compounding_request<P: Preset>(
    state: &impl PostElectraBeaconState<P>,
    consolidation_request: ConsolidationRequest,
) -> Result<bool> {
    let ConsolidationRequest { source_address, source_pubkey, target_pubkey } = consolidation_request;

    if source_pubkey != target_pubkey {
        return Ok(false);
    }
    let Some(source_index) = index_of_public_key(state, &source_pubkey) else {
        return Ok(false);
    };
    let source_validator = state.validators().get(source_index)?;

    if compute_source_address(source_validator) != source_address {
        return Ok(false);
    }
    if !has_eth1_withdrawal_credential(source_validator) {
        return Ok(false);
    }
    let current_epoch = get_current_epoch(state);
    if !is_active_validator(source_validator, current_epoch) {
        return Ok(false);
    }
    if source_validator.exit_epoch != FAR_FUTURE_EPOCH {
        return Ok(false);
    }
    Ok(true)
}

fn compute_source_address(validator: &Validator) -> ExecutionAddress {
    let prefix_len = H256::len_bytes() - ExecutionAddress::len_bytes();
    ExecutionAddress::from_slice(&validator.withdrawal_credentials[prefix_len..])
}
```

Generic over `PostElectraBeaconState<P>` trait bound — single body across Electra/Fulu/Gloas. The `compute_source_address` helper computes `prefix_len = H256::len_bytes() - ExecutionAddress::len_bytes() = 32 - 20 = 12` from type-associated constants — most type-traceable construction of the six. `has_eth1_withdrawal_credential` is the strict-`0x01` predicate from item #22 (`predicates.rs`).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓ (`PostElectraBeaconState<P>` covers Gloas). H11 ✓. H12 ✓.

## Cross-reference table

| Client | Predicate location | Pubkey-check placement | Check 4 binding | Gloas redefinition |
|---|---|---|---|---|
| prysm | `core/electra/consolidations.go:134-172 IsValidSwitchToCompoundingRequest` (+ private dup at `core/requests/consolidations.go:240-278`) | INSIDE predicate | `srcV.HasETH1WithdrawalCredentials()` (strict 0x01) | none — Pectra impl reused |
| lighthouse | `state_processing/src/per_block_processing/process_operations.rs:629-682` | INSIDE predicate | `source_validator.has_eth1_withdrawal_credential(spec)` (strict 0x01); fused with Check 3 | none (single Pectra impl) |
| teku | `versions/electra/execution/ExecutionRequestsProcessorElectra.java:443-482 isValidSwitchToCompoundingRequest` | INSIDE predicate | `predicates.hasEth1WithdrawalCredential(sourceValidator)` (strict 0x01) | none — `ExecutionRequestsProcessorGloas` inherits without override |
| nimbus | `spec/state_transition_block.nim:626-655` (with caller hoist at `:664-669`) | **HOISTED to caller** | `has_eth1_withdrawal_credential(source_validator)` (strict 0x01) | none — generic over `electra/fulu/gloas.BeaconState` |
| lodestar | `block/processConsolidationRequest.ts:107-149 isValidSwitchToCompoundRequest` | **HOISTED + REORDERED** (pubkey-exists is Check 1; source==target is Check 2) | `hasEth1WithdrawalCredential(creds)` (strict 0x01) | none — type-polymorphic `CachedBeaconStateElectra \| CachedBeaconStateGloas` |
| grandine | `transition_functions/src/electra/block_processing.rs:1296-1341` (with `compute_source_address` helper at `:1343-1345`) | INSIDE predicate | `has_eth1_withdrawal_credential(source_validator)` (strict 0x01) | none — `PostElectraBeaconState<P>` covers Gloas |

## Empirical tests

### Pectra-surface implicit coverage (carried forward from prior audit)

No dedicated EF fixture set — the predicate is an internal helper. Exercised IMPLICITLY via item #2's consolidation_request fixture series:

| Item | Fixtures × wired clients | Calls this predicate |
|---|---|---|
| #2 consolidation_request | 10 × 4 = 40 | item #2's `process_consolidation_request` fast path → predicate |

**Cumulative Pectra implicit cross-validation evidence**: 40 EF fixture PASSes across 10 unique fixtures. Per-check fixture coverage from prior audit:

| Fixture | Hypothesis tested |
|---|---|
| `basic_switch_to_compounding` | H1 + H2 + H3 (all 6 pass → switch) |
| `incorrect_source_pubkey_not_in_state` | Check 2 / H5 |
| `incorrect_source_pubkey_not_active` | Check 5 / H7 |
| `incorrect_source_pubkey_exit_initiated` | Check 6 / H8 |
| `incorrect_source_address_mismatch` | Check 3 / H4 |
| `incorrect_source_creds_not_eth1` | Check 4 / H6 |

### Gloas-surface

No Gloas-specific fixtures wired for this predicate yet. H10–H12 are source-only.

Concrete Gloas-spec evidence:
- `vendor/consensus-specs/specs/gloas/beacon-chain.md:1132` — `for_ops(requests.consolidations, process_consolidation_request)` inside `apply_parent_execution_payload`. The surviving routing surface.
- `vendor/consensus-specs/specs/gloas/beacon-chain.md:1515` — `# Removed process_consolidation_request` inside the modified `process_operations`. The deleted Electra-surface call path.
- No `Modified is_valid_switch_to_compounding_request` heading anywhere in `vendor/consensus-specs/specs/gloas/`.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — dedicated EF fixture set for the predicate).** Pure `(state, consolidation_request) → bool` fuzz. Boundary cases: 6 failure cases (one per check) + 1 all-pass = 7 fixtures minimum. Cross-client byte-level equivalence.
- **T1.2 (Glamsterdam-target — ePBS routing surface fixture).** Gloas state. Submit a `ConsolidationRequest` with `source_pubkey == target_pubkey` via `requests.consolidations` (parent-payload execution requests). Expected: post-state has `validator[source].withdrawal_credentials[0] = 0x02` and a placeholder PendingDeposit appended. The routing chain `apply_parent_execution_payload` → `process_consolidation_request` → `is_valid_switch_to_compounding_request` → `switch_to_compounding_validator` → `queue_excess_active_balance` is exercised end-to-end. **At lighthouse**: would surface items #14 H9 / #19 H10 / #22 H10 / #23 H8 propagation — the ePBS routing isn't wired, so the consolidation request doesn't reach this predicate.

#### T2 — Adversarial probes
- **T2.1 (defensive — 0x03 source rejection).** Gloas state with a validator that has `0x03` credentials (created pre-Gloas per item #22 H12 attack path — depositor submitted `0x03` deposit). Submit a switch request for this validator. Expected: Check 4 (`has_eth1_withdrawal_credential = false` for `0x03`) fails on ALL 6 clients → predicate returns `false` → switch silently rejected. **Item #22's nimbus `has_compounding` divergence does NOT propagate here** — Check 4 uses strict-`0x01` `has_eth1_withdrawal_credential`.
- **T2.2 (defensive — 0x02 source rejection).** Validator already in `0x02` (compounding) submits a switch request. Expected: Check 4 fails on all 6 clients → silent reject. No-op.
- **T2.3 (defensive — 0x00 BLS source rejection).** Validator with `0x00` (BLS) credentials submits a switch request. Check 3 (`creds[12:] == source_address`) likely fails (creds[12:] is all zeros for BLS unless the address is also all zeros — implausible). Check 4 (`has_eth1`) also fails. Belt-and-suspenders defense.
- **T2.4 (defensive — exit-initiated source rejection).** Validator with `exit_epoch != FAR_FUTURE_EPOCH` submits a switch request. Check 6 fails on all 6 clients → silent reject.
- **T2.5 (defensive — inactive source rejection).** Validator not yet active OR already exited (per `is_active_validator`) submits a switch request. Check 5 fails on all 6 clients → silent reject.
- **T2.6 (defensive — `source_address` mismatch).** Validator with `0x01` credentials submits a switch request where `source_address` does NOT match `creds[12:32]`. Check 3 fails on all 6 clients → silent reject. **This is the security gate** — only the holder of the eth1 address can authorize the switch.
- **T2.7 (defensive — source != target).** Two distinct pubkeys submitted. Check 1 fails on all 6 clients → falls through to the regular consolidation path (per item #2). Not specifically this predicate's territory.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Pectra-surface invariants (H1–H9) hold across all six with the two carried-forward style divergences (nimbus + lodestar pubkey-hoist; lodestar check 1/2 reorder; prysm public/private duplication) — all observable-equivalent.

**Glamsterdam-target finding (H10 + H11 — function unchanged, caller routing migrates to ePBS).** `vendor/consensus-specs/specs/gloas/beacon-chain.md` contains no `Modified is_valid_switch_to_compounding_request` heading — the function is inherited verbatim from Electra. Its dependencies (`has_eth1_withdrawal_credential`, `is_active_validator`) are also unchanged at Gloas across all six clients. The routing surface CHANGES: `process_consolidation_request` migrates from `process_operations` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1515 # Removed process_consolidation_request`) to `apply_parent_execution_payload` (`:1132 — for_ops(requests.consolidations, process_consolidation_request)`) under EIP-7732 ePBS. This is a routing-surface migration, not a function-body change; this item's predicate decisions are unaffected.

**Cross-cut with item #22 nimbus divergence (H12 — no propagation).** Item #22 found nimbus's `has_compounding_withdrawal_credential` is stale-Gloas-aware (ORs in `0x03` at Gloas+). This predicate uses `has_eth1_withdrawal_credential` (strict-`0x01`), not `has_compounding`. All six clients implement `has_eth1_withdrawal_credential` as strict-`0x01` at Gloas. A `0x03` (builder-credentialled) validator submitting a switch request would correctly fail at Check 4 on all six clients → silent reject. **Item #22's H12 mainnet-everyone divergence does NOT extend to this predicate.**

**Seventh impact-none result** in the recheck series (after items #5, #10, #11, #18, #20, #21). Same propagation-without-amplification pattern as item #21: the Gloas ePBS routing relocates the caller, but the predicate body is unchanged across all six clients.

**Lighthouse Gloas-readiness gap (carried-forward observation).** Lighthouse's missing ePBS routing for `apply_parent_execution_payload → process_consolidation_request` means switch requests don't reach this predicate at Gloas on lighthouse. This is the broader items #14 H9 / #19 H10 / #22 H10 / #23 H8 gap, NOT a divergence at this item's surface. Lighthouse's predicate body itself is correct in isolation; the routing gap is upstream.

**Notable per-client style differences (all observable-equivalent at both Pectra and Gloas):**
- **prysm**: `bytes.HasSuffix` idiom + explicit length validation (`len(creds) != 32 || len(addr) != 20`). Most defensive against schema-change drift. PUBLIC/private duplicate (forward-fragility).
- **lighthouse**: fused Checks 3 + 4 via `.then(|| ...).flatten()`. Safe `.get(12..)` returns `Option`. Most panic-safe.
- **teku**: extracted `Predicates.getExecutionAddressUnchecked` static helper. Reusable across the codebase.
- **nimbus**: pubkey-hoist + `toOpenArray(12, 31)` inclusive-range slice. Type-safe predicate signature.
- **lodestar**: pubkey-hoist + reorder check 1↔2 (type-narrowing reason). Type signature `CachedBeaconStateElectra | CachedBeaconStateGloas` confirms fork-polymorphism.
- **grandine**: `compute_source_address` helper with dynamic `prefix_len = type_size - addr_size` derivation. Most type-traceable.

**No code-change recommendation.** Audit-direction recommendations:

- **Generate dedicated EF fixture set for the predicate** (T1.1) — 7-boundary-case pure-function fuzz. Highest-priority gap closure.
- **Gloas-surface end-to-end fixture** (T1.2) — exercises the full ePBS routing chain `apply_parent_execution_payload → process_consolidation_request → predicate → switch_to_compounding_validator → queue_excess_active_balance`. Would surface lighthouse's H8 gap.
- **Cross-client byte-equivalence test for `0x03` source rejection at Gloas** (T2.1) — confirms item #22's nimbus divergence does NOT propagate to this predicate.
- **prysm public/private duplicate contract test** — assert both implementations produce identical decisions on the same input. Carry-forward from items #21 / #22 prysm duplications.
- **nimbus/lodestar pubkey-hoist invariant assertion** — codify the precondition that the parent's pubkey check matches what the predicate would have checked internally.
- **Sister-item audit: lighthouse Gloas ePBS routing for consolidations** — `apply_parent_execution_payload → process_consolidation_request` wiring. Same five-vs-one cohort as items #14 H9 / #19 H10.
- **Spec-clarification PR (consensus-specs)**: add explicit non-modification notes for predicates that survive unchanged across forks despite related forks-driven activity nearby (e.g., this predicate at Gloas given the ePBS routing migration).

## Cross-cuts

### With item #2 (`process_consolidation_request`)

Item #2's audit covered the full `process_consolidation_request` (the regular consolidation path AND the switch fast path). This item zooms in on the switch-fast-path security gate. At Gloas, `process_consolidation_request` is inherited from Electra (no Modified heading) and re-routed from `process_operations` to `apply_parent_execution_payload`. Item #2 captures the routing change; this item captures the predicate body unchanged.

### With item #21 (`queue_excess_active_balance`)

If this predicate returns `true`, item #22's `switch_to_compounding_validator` runs, which calls item #21's `queue_excess_active_balance`. Item #21's audit confirmed function-body unchanged at Gloas with caller-routing migration to ePBS. The chain from this predicate down to item #21 is preserved at Gloas modulo the routing-surface migration.

### With item #22 (`has_eth1_withdrawal_credential` + `switch_to_compounding_validator`)

Item #22 found two main observations:
1. **`has_compounding_withdrawal_credential` nimbus H12 divergence** — does NOT propagate here (this predicate uses `has_eth1_withdrawal_credential`, strict-`0x01`).
2. **`switch_to_compounding_validator` mutator** — invoked downstream of this predicate's `true` return. Item #22 confirmed function-body unchanged across all six clients (no `0x03`-aware fold-in in the mutator).

So the predicate-gate (this item) + mutator (item #22's `switch_to_compounding_validator`) form a clean two-step pipeline at Gloas with no fork divergence at the predicate-body or mutator-body level.

### With item #14 H9 / item #19 H10 / item #22 H10 / item #23 H8 (lighthouse Gloas-ePBS gap)

All four prior audits flagged lighthouse's missing ePBS routing (no `is_builder_withdrawal_credential`, no `get_pending_balance_to_withdraw_for_builder`, no `apply_parent_execution_payload` consolidation routing). This item is the FIFTH symptom in the cohort: switch requests don't reach this predicate at Gloas in lighthouse. The single-cause fix at the items #14/#19 level would close all five symptoms simultaneously.

### With item #23 (`get_pending_balance_to_withdraw`)

Item #23's H10 nimbus divergence affects the regular consolidation path's source-gate (`if get_pending_balance_to_withdraw(state, source_index) > 0: return`), NOT the switch fast path. The switch fast path uses `is_valid_switch_to_compounding_request` instead, which does not call `get_pending_balance_to_withdraw`. So item #23's nimbus mainnet-everyone divergence does NOT propagate to this item's predicate. Switch requests for a `0x01` validator V (which is on the predicate's eligible path) are decided by this predicate independently of any builder-pending state.

## Adjacent untouched

1. **Generate dedicated EF fixture set for the predicate** — 6 single-check-fails + 1 all-pass = 7 cases. Pure function, easily fuzzable.
2. **Gloas-surface end-to-end fixture** for the full ePBS routing chain (T1.2). Surfaces lighthouse's H8 gap.
3. **`0x03` source rejection cross-client equivalence** (T2.1) — confirms item #22's H12 doesn't propagate here.
4. **prysm code-duplication contract test** — `core/electra/consolidations.go::IsValidSwitchToCompoundingRequest` vs `core/requests/consolidations.go::isValidSwitchToCompoundingRequest`. Assert behavioural equivalence.
5. **nimbus + lodestar pubkey-hoist invariant codification** — parent's pubkey check must match the predicate's precondition.
6. **Sister-item audit: lighthouse Gloas ePBS routing for consolidations** — single-fix-closes-five-symptoms cohort.
7. **grandine `compute_source_address` helper standalone audit** — `prefix_len = type_size - addr_size` derivation; defensive against future schema changes.
8. **teku `Predicates.getExecutionAddressUnchecked` safety contract** — verify "unchecked" semantics don't cause issues when callers omit the `creds[0] == 0x01` validation.
9. **prysm `bytes.HasSuffix` correctness** — equivalence with explicit `creds[12:]` slice depends on `len(creds) == 32 && len(addr) == 20` (which prysm explicitly checks above the HasSuffix call). Document the precondition.
10. **lighthouse `Address::from_slice` panic safety** — `.get(12..)` returns `&[u8]` of length 20 for 32-byte credentials. `Address::from_slice` assumes 20 bytes. Safe by construction; codify.
11. **Cross-fork upgrade interaction stateful fixture** — switch request submitted at exactly the Pectra activation slot. Edge case for state-cache initialization.
12. **`COMPOUNDING_WITHDRAWAL_PREFIX` already-set source rejection** (T2.2) — codify silent-reject behaviour.
13. **`0x00` (BLS) source switch rejection** (T2.3) — defense-in-depth verification.
14. **`source_address` field semantics audit** — EL transaction `from` address must match the eth1 address embedded in the validator's credentials. Cross-cut with the EL deposit-contract behaviour (item #14 EL surface).
