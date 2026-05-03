# Item #24 — `is_valid_switch_to_compounding_request` (Pectra-NEW security gate for switch path)

**Status:** no-divergence-pending-source-review — audited 2026-05-02.
The **6-check security gate** before items #21 (`queue_excess_active_balance`)
and #22 (`switch_to_compounding_validator`) execute from item #2's
`process_consolidation_request` switch fast path.

## Why this item

Pectra introduced the **switch-to-compounding fast path** in
`process_consolidation_request`: when a validator wants to convert
its 0x01 (eth1 address) credentials to 0x02 (compounding), it sends
a `ConsolidationRequest` with `source_pubkey == target_pubkey`. This
is recognized as a "switch request" instead of a real consolidation.

Before the switch executes, **6 checks must ALL pass** (any failure
returns `False`, ignoring the request silently):

```python
def is_valid_switch_to_compounding_request(state, consolidation_request) -> bool:
    # Check 1: Switch requires source == target (self-consolidation)
    if consolidation_request.source_pubkey != consolidation_request.target_pubkey:
        return False
    # Check 2: Source pubkey exists in validator registry
    source_pubkey = consolidation_request.source_pubkey
    validator_pubkeys = [v.pubkey for v in state.validators]
    if source_pubkey not in validator_pubkeys:
        return False
    source_validator = state.validators[ValidatorIndex(validator_pubkeys.index(source_pubkey))]
    # Check 3: Request authorized by eth1 address embedded in credentials[12:31]
    if source_validator.withdrawal_credentials[12:] != consolidation_request.source_address:
        return False
    # Check 4: Source must currently be 0x01 (eligible for switching to 0x02)
    if not has_eth1_withdrawal_credential(source_validator):
        return False
    # Check 5: Source must be active
    current_epoch = get_current_epoch(state)
    if not is_active_validator(source_validator, current_epoch):
        return False
    # Check 6: Source must NOT have initiated exit
    if source_validator.exit_epoch != FAR_FUTURE_EPOCH:
        return False
    return True
```

This is the **security gate** — it ensures only the legitimate
0x01-credential validator can switch to 0x02. The `source_address`
in the request is matched against the eth1 address embedded in
`withdrawal_credentials[12:31]`. The EL transaction that produces
the ConsolidationRequest is signed by the holder of that eth1
address, so passing this check proves authorization.

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | 6 checks in spec order: source==target → pubkey exists → creds[12:]==source_address → has_eth1 → is_active → exit_epoch == FAR_FUTURE | ✅ 5/6 use spec order; **lodestar reorders** (pubkey-exists FIRST then source==target) — observable-equivalent because both reject identically |
| H2 | Returns `False` on ANY failure (any-of-6 short-circuit) | ✅ all 6 |
| H3 | Returns `True` ONLY if all 6 pass (all-of-6) | ✅ all 6 |
| H4 | `withdrawal_credentials[12:31]` 20-byte slice (eth1 address embedded in 32-byte credentials) | ✅ all 6 |
| H5 | Pubkey lookup uses cached `validator_pubkey → index` map (NOT linear scan; spec uses `validator_pubkeys.index` linear) | ✅ all 6 (cached for performance) |
| H6 | `has_eth1_withdrawal_credential` (item #22) for Check 4 | ✅ all 6 |
| H7 | `is_active_validator(source_validator, current_epoch)` for Check 5 | ✅ all 6 |
| H8 | Strict `!=` comparison on `exit_epoch != FAR_FUTURE_EPOCH` for Check 6 | ✅ all 6 |
| H9 | Called BEFORE the main consolidation path in item #2's process_consolidation_request | ✅ all 6 |

## Per-client cross-reference

| Client | Function location | Pubkey-check placement | Notable |
|---|---|---|---|
| **prysm** | `core/electra/consolidations.go:134-172` (PUBLIC `IsValidSwitchToCompoundingRequest`) + `core/requests/consolidations.go:240-278` (private duplicate) | INSIDE predicate (Check 2) | DUPLICATE implementations (same as item #22's switchToCompoundingValidator); explicit `len(creds) != 32 || len(addr) != 20` defensive validation; uses `bytes.HasSuffix(creds, sourceAddress)` for the slice comparison |
| **lighthouse** | `state_processing/src/per_block_processing/process_operations.rs:629-682` | INSIDE predicate (Check 2) | Returns `Result<bool, BlockProcessingError>`; uses `state.pubkey_cache().get(&pubkey)`; `.get(12..).map(Address::from_slice)` safe slice; assumes Electra fork (no inner fork guard) |
| **teku** | `versions/electra/execution/ExecutionRequestsProcessorElectra.java:443-482` | INSIDE predicate (Check 2) | Uses `Predicates.getExecutionAddressUnchecked(creds)` (extracts via `creds.slice(12)`); `Optional<Integer>` chaining |
| **nimbus** | `spec/state_transition_block.nim:626-655` (predicate def) + `:658-674` (caller hoist) | **HOISTED OUTSIDE** predicate | Pubkey-existence check moved to caller `process_consolidation_request:666-669` via `findValidatorIndex`; predicate receives pre-resolved `source_validator`; comment in code: `# process_consolidation_request() verifies pubkey exists` |
| **lodestar** | `block/processConsolidationRequest.ts:107-149` (predicate `isValidSwitchToCompoundRequest`) + `:21-23` (parent hoist) | **HOISTED OUTSIDE** predicate (re-checked inside as defensive) | Parent function checks `isPubkeyKnown(state, sourcePubkey) && isPubkeyKnown(state, targetPubkey)` BEFORE calling predicate; **REORDERED** check 1 ↔ 2 (pubkey-exists comes first); explicit comment "this check is mainly to make the compiler happy, pubkey is checked by the consumer already" |
| **grandine** | `transition_functions/src/electra/block_processing.rs:1296-1341` (with `compute_source_address` helper at `:1343-1345`) | INSIDE predicate (Check 2) | Single definition (no multi-fork-definition risk); uses `compute_source_address` helper that dynamically computes `prefix_len = H256::len_bytes() - ExecutionAddress::len_bytes() = 12`; `let Some(...) else { return Ok(false) }` Rust pattern |

## Notable per-client divergences (all observable-equivalent)

### nimbus + lodestar: pubkey-existence HOISTED outside the predicate

Both clients move Check 2 (pubkey exists) OUT of the predicate to
the caller. **Pyspec puts it inside.** This is observable-equivalent
because the caller does the check immediately before the predicate
call — same short-circuit behavior.

**Item #2 audit's claim** ("nimbus and lodestar hoist pubkey-existence
checks before the switch fast path (pyspec does them inside
`is_valid_switch_to_compounding_request`)") is **VERIFIED**.

The hoisting has two motivations:
1. **Performance**: The caller often needs the validator index
   anyway (to call `switch_to_compounding_validator(state, source_index)`
   afterwards). Doing the lookup once and passing the index avoids
   a redundant `state.validators.index_of` lookup inside the
   predicate.
2. **Type safety**: nimbus's predicate signature takes
   `source_validator: Validator` (not `state` + `pubkey`), making the
   precondition (validator exists) part of the type signature. Cleaner
   API.

### lodestar: REORDERED checks 1 and 2

Lodestar's predicate body:
```typescript
// Check 1 (REORDERED): Pubkey exists (sourceIndex === null check)
if (sourceIndex === null) {
  // "this check is mainly to make the compiler happy, pubkey is checked by the consumer already"
  return false;
}
// Check 2 (REORDERED): Switch to compounding requires source and target be equal
if (sourceIndex !== targetIndex) {
  return false;
}
```

Lodestar reorders pubkey-existence to FIRST and source==target to
SECOND. **Observable-equivalent** because both checks return false
identically. The reorder is for type-system reasons (after the
pubkey-exists check, `sourceIndex` is known to be non-null).

### prysm: DUPLICATE implementations (same code-duplication pattern as item #22)

```go
// PUBLIC: core/electra/consolidations.go:134-172 (IsValidSwitchToCompoundingRequest)
// PRIVATE: core/requests/consolidations.go:240-278 (isValidSwitchToCompoundingRequest)
```

Two functionally-identical implementations. Same forward-fragility
concern as item #22's switchToCompoundingValidator. **F-tier today**
(both line-identical) but a refactor risk.

### prysm: explicit length validation for `withdrawal_credentials[12:]`

```go
withdrawalCreds := srcV.GetWithdrawalCredentials()
if len(withdrawalCreds) != 32 || len(sourceAddress) != 20 ||
   !bytes.HasSuffix(withdrawalCreds, sourceAddress) {
    return false
}
```

Prysm explicitly validates BOTH the credentials length (must be 32)
AND the source address length (must be 20) BEFORE the slice
comparison. **Most defensive** of the six. SSZ schema enforces these
lengths, so the explicit checks are dead defensive code today, but
they protect against any future schema change.

The `bytes.HasSuffix(creds, sourceAddress)` idiom is also unusual —
other clients explicitly slice `creds[12:]` and compare. `HasSuffix`
checks if `creds` ENDS WITH `sourceAddress` which is observable-
equivalent to `creds[12:] == sourceAddress` for 32-byte creds + 20-byte
address (because `32 - 20 = 12`).

### lighthouse: safe `.get(12..)` returns Option, gracefully handles bounds

```rust
source_validator.withdrawal_credentials.as_slice().get(12..)
    .map(Address::from_slice)
```

Lighthouse uses `.get(12..)` which returns `Option<&[u8]>` (None on
out-of-bounds). The `.map(Address::from_slice)` then constructs
the Address only if the slice succeeded. **No panic on
out-of-bounds**, even theoretically. Most defensive in terms of
panic-safety.

### nimbus: Nim's `toOpenArray(12, 31)` inclusive-range slice

```nim
if source_validator.withdrawal_credentials.data.toOpenArray(12, 31) !=
    consolidation_request.source_address.data:
```

Nim's `toOpenArray(12, 31)` extracts bytes 12 through 31 INCLUSIVE
(20 bytes). Most explicit about the byte range. Other languages use
half-open ranges (`[12:]`, `[12..32]`, `[12..]`).

### grandine: compute_source_address helper with dynamic prefix length

```rust
fn compute_source_address(validator: &Validator) -> ExecutionAddress {
    let prefix_len = H256::len_bytes() - ExecutionAddress::len_bytes();
    ExecutionAddress::from_slice(&validator.withdrawal_credentials[prefix_len..])
}
```

Grandine computes `prefix_len = 32 - 20 = 12` from the type-associated
constants `H256::len_bytes()` and `ExecutionAddress::len_bytes()`.
**Most type-traceable** — if either type's byte length ever changes,
this helper auto-adapts. Defensive against type-system changes (not
applicable today but elegant).

### teku: extracted helper `Predicates.getExecutionAddressUnchecked`

```java
public static Eth1Address getExecutionAddressUnchecked(final Bytes32 withdrawalCredentials) {
    return Eth1Address.fromBytes(withdrawalCredentials.slice(12));
}
```

Teku has a static helper `Predicates.getExecutionAddressUnchecked` —
"unchecked" because it doesn't validate that `creds[0] == 0x01`
(callers must validate that separately). Reusable across the
codebase. The `slice(12)` extracts bytes 12 onwards (20 bytes for a
Bytes32).

## EF fixture status — implicit coverage via item #2

This audit has **no dedicated EF fixture set** because the predicate
is an internal helper. It is exercised IMPLICITLY via:

| Item | Fixtures × clients | Calls this predicate |
|---|---|---|
| **#2** consolidation_request | 10 × 4 = 40 | item #2's process_consolidation_request fast path → predicate gate |

**Total implicit cross-validation evidence**: **40 EF fixture PASSes**
across 10 unique fixtures. Critical fixtures testing each predicate
check:

| Fixture | Hypothesis tested |
|---|---|
| `basic_switch_to_compounding` | H1+H2+H3 (all 6 checks pass → switch) |
| `incorrect_not_enough_consolidation_churn_available` | indirect (covers main path, not switch) |
| `incorrect_source_pubkey_not_in_state` | H5 (Check 2: pubkey exists) |
| `incorrect_source_pubkey_not_active` | H7 (Check 5: is_active) |
| `incorrect_source_pubkey_exit_initiated` | H8 (Check 6: exit_epoch != FAR_FUTURE) |
| `incorrect_source_address_mismatch` | H4 (Check 3: creds[12:] == source_address) |
| `incorrect_source_creds_not_eth1` | H6 (Check 4: has_eth1 — actually source must currently be 0x01) |

A dedicated fixture for `is_valid_switch_to_compounding_request`
would be `(state, consolidation_request) → bool` — 6 boundary cases
+ all-pass case = 7 fixtures. **Pure function, easily fuzzable.**

## Cross-cut chain — closes the switch-fast-path security gate

This audit closes the security gate before the switch path executes:

```
[item #2 process_consolidation_request]:
    ConsolidationRequest received from EL
                ↓
[item #24 (this) is_valid_switch_to_compounding_request]:
    6-check security gate:
    1. source == target (self-consolidation = switch request)
    2. pubkey exists in registry (cached lookup)
    3. creds[12:] == source_address (EL transaction signer authorized)
    4. has_eth1_withdrawal_credential (item #22 — currently 0x01)
    5. is_active_validator (eligible)
    6. exit_epoch == FAR_FUTURE (not exiting)
                ↓ if ALL 6 pass:
[item #22 switch_to_compounding_validator]:
    creds[0] = 0x02 (compounding prefix)
    queue_excess_active_balance(state, idx)
                ↓
[item #21 queue_excess_active_balance]:
    if balance > MIN_ACTIVATION_BALANCE:
        balance reset to MIN
        state.pending_deposits.append(PendingDeposit{
            sig=G2_POINT_AT_INFINITY,
            slot=GENESIS_SLOT
        })
                ↓ next epoch
[item #4/#20 process_pending_deposits + apply_pending_deposit]:
    placeholder skipped sig verify (slot==GENESIS_SLOT)
    existing-validator top-up (pubkey already in registry)
    increase_balance(state, idx, excess_balance)
                ↓
balance restored: MIN_ACTIVATION_BALANCE + excess (now in 0x02 regime, churn-paced)
```

The complete switch-to-compounding lifecycle from gate to drain is
now audited end-to-end.

## Adjacent untouched

- **Generate dedicated EF fixture set** for `is_valid_switch_to_compounding_request`
  — pure-function 7-case fuzzing.
- **prysm code duplication contract test** for the two
  `IsValidSwitchToCompoundingRequest` implementations (same as item
  #22's switchToCompoundingValidator).
- **lodestar reordered-check audit** — verify the reorder doesn't
  break the cross-client agreement on observable behavior. Generate
  a fixture where checks 1 and 2 BOTH fail and verify all 6 clients
  return false.
- **nimbus + lodestar pubkey-hoist contract test** — assert that
  the parent function's pubkey check matches the predicate's expected
  precondition (otherwise the predicate could be called with
  unverified input).
- **`compute_source_address` standalone helper audit** (grandine
  unique) — codify the `prefix_len = type_size - addr_size = 12`
  derivation as documentation.
- **`Predicates.getExecutionAddressUnchecked` audit** (teku unique)
  — verify "unchecked" semantics don't cause issues if creds[0] is
  not 0x01 (the caller must validate this — but what happens if
  not? Returns 0xZ-bytes, but the comparison would fail).
- **prysm `bytes.HasSuffix` vs explicit slice** — equivalence test
  for the case `creds = [0xZZ, 0xZZ, ..., 20-byte-addr]`. The
  HasSuffix call would match if the last 20 bytes match, regardless
  of the prefix bytes. Worth documenting that this is correct only
  when `len(creds) == 32` and `len(addr) == 20`.
- **lighthouse `Address::from_slice` panic safety** — `Address::from_slice`
  may panic on wrong length. The `.get(12..)` returns 20 bytes
  exactly (for 32-byte creds), so this is safe today.
- **Cross-fork upgrade interaction** — at Pectra activation, all
  validators are pre-existing (no new ones in the fork-transition
  block). Their credentials may be 0x00, 0x01, or even 0x02 (if item
  #11's upgrade-time early-adopter loop converted them). A switch
  request immediately after upgrade should work identically to one
  hours later. Worth a stateful fixture.

## Future research items

1. **Generate dedicated EF fixture set** for the predicate (7 boundary
   cases + all-pass).
2. **prysm code duplication contract test** — same concern as item
   #22.
3. **lodestar reordered-check observable-equivalence verification**.
4. **nimbus + lodestar pubkey-hoist invariant assertion** —
   parent's pubkey check must match the predicate's precondition.
5. **grandine `compute_source_address` helper** documentation.
6. **teku `Predicates.getExecutionAddressUnchecked`** safety audit
   (unchecked means caller must validate creds[0]).
7. **prysm `bytes.HasSuffix` correctness** equivalence with explicit
   slice (depends on length validation).
8. **lighthouse `Address::from_slice` panic safety** under unusual
   input (length != 20).
9. **Cross-fork upgrade interaction stateful fixture** — switch
   request immediately after Pectra activation.
10. **`source_address` field semantics** — the EL transaction's
    `from` address is signed by the EOA holding the eth1 address.
    Verify cross-client this matches the credentials's embedded
    address.
11. **`COMPOUNDING_WITHDRAWAL_PREFIX` already-set source** — what
    happens if a validator already in 0x02 sends a switch request?
    Check 4 (`has_eth1_withdrawal_credential`) returns `false` →
    predicate returns `false` → switch silently rejected. Worth a
    fixture.
12. **0x00 (BLS) source switch** — what happens if a 0x00 validator
    sends a switch request? Check 3 (`creds[12:] == source_address`)
    would compare 20 bytes of source_address against 20 zero bytes
    of the BLS withdrawal credentials [12:31]. Almost always fails
    (unless source_address is also all zeros, which is implausible).
    Then Check 4 (has_eth1) would also fail. Worth a fixture for
    completeness.
