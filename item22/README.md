# Item #22 — Compounding/credential subsystem helpers (predicates + `switch_to_compounding_validator`)

**Status:** no-divergence-pending-source-review — audited 2026-05-02.
**Five small Pectra-NEW (or Pectra-modified) helpers** that gate
0x02 vs 0x01 vs 0x00 behavior across the entire Pectra surface. Used
by items #1, #2, #3, #6, #11, #12, #18, #21 — foundational primitives.

## Why this item

Pectra introduces the `0x02` (compounding) withdrawal-credential
prefix, alongside Phase0's `0x00` (BLS) and Capella's `0x01` (eth1
address). Five small helpers gate behavior across the Pectra surface:

```python
# Pectra-NEW constants:
COMPOUNDING_WITHDRAWAL_PREFIX = Bytes1('0x02')   # NEW

# Capella-heritage:
ETH1_ADDRESS_WITHDRAWAL_PREFIX = Bytes1('0x01')

# Phase0-heritage:
BLS_WITHDRAWAL_PREFIX = Bytes1('0x00')

# Pectra-NEW predicates:
def is_compounding_withdrawal_credential(creds: Bytes32) -> bool:
    return creds[:1] == COMPOUNDING_WITHDRAWAL_PREFIX

def has_compounding_withdrawal_credential(validator) -> bool:
    return is_compounding_withdrawal_credential(validator.withdrawal_credentials)

def has_eth1_withdrawal_credential(validator) -> bool:    # Capella heritage
    return validator.withdrawal_credentials[:1] == ETH1_ADDRESS_WITHDRAWAL_PREFIX

def has_execution_withdrawal_credential(validator) -> bool:    # Pectra-NEW (OR semantics)
    return has_eth1_withdrawal_credential(validator) or has_compounding_withdrawal_credential(validator)

# Pectra-NEW mutator:
def switch_to_compounding_validator(state, index) -> None:
    validator = state.validators[index]
    validator.withdrawal_credentials = (
        COMPOUNDING_WITHDRAWAL_PREFIX + validator.withdrawal_credentials[1:]
    )
    queue_excess_active_balance(state, index)
```

Critical invariants:
1. Constants: 0x00 / 0x01 / 0x02 strict byte values.
2. Predicates: strict prefix-byte equality.
3. `has_execution` = OR (NOT AND) of has_eth1 OR has_compounding.
4. `switch_to_compounding_validator` modifies ONLY byte [0] (preserves
   bytes [1:31] which encode the eth1 address for 0x01 → 0x02
   transition).

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | `COMPOUNDING_WITHDRAWAL_PREFIX = 0x02` constant | ✅ all 6 |
| H2 | `ETH1_ADDRESS_WITHDRAWAL_PREFIX = 0x01` constant | ✅ all 6 |
| H3 | `BLS_WITHDRAWAL_PREFIX = 0x00` constant | ✅ all 6 |
| H4 | `is_compounding_withdrawal_credential` = strict `[0] == 0x02` | ✅ all 6 |
| H5 | `has_compounding_withdrawal_credential(validator)` wraps the byte predicate | ✅ all 6 |
| H6 | `has_eth1_withdrawal_credential(validator)` = strict `[0] == 0x01` (Capella heritage) | ✅ all 6 |
| H7 | `has_execution_withdrawal_credential` = `has_eth1 OR has_compounding` (NOT AND) | ✅ all 6 |
| H8 | `switch_to_compounding_validator` modifies ONLY byte [0] (preserves bytes [1:31]) | ✅ all 6 |
| H9 | `switch_to_compounding_validator` calls `queue_excess_active_balance` after credential update | ✅ all 6 |

## Per-client cross-reference

| Client | Predicate location | Switch location |
|---|---|---|
| **prysm** | `state-native/readonly_validator.go:94-106` (`HasETH1WithdrawalCredentials`, `HasCompoundingWithdrawalCredentials`, `HasExecutionWithdrawalCredentials`); constants in `params/mainnet_config.go:96-99` | `core/electra/validator.go:22-36` (PUBLIC `SwitchToCompoundingValidator`) + DUPLICATE in `core/requests/consolidations.go:280-294` (private `switchToCompoundingValidator`) |
| **lighthouse** | `consensus/types/src/validator/validator.rs:159-165, 168-170, 275-279, 311-320` (validator methods + standalone `is_compounding_withdrawal_credential`); constants in `chain_spec.rs:90-92, 1051-1053` | `consensus/types/src/state/beacon_state.rs:2692-2706` (state method) |
| **teku** | `versions/electra/helpers/PredicatesElectra.java:108-120` (override `hasExecutionWithdrawalCredential` for OR semantics); constants in `constants/WithdrawalPrefixes.java:19-26` | `versions/electra/helpers/BeaconStateMutatorsElectra.java:176-187` |
| **nimbus** | `spec/beaconstate.nim:48-50, 59-68, 1467-1469, 1472-1476`; constants in `datatypes/constants.nim:87, 90` (COMPOUNDING + BUILDER) and `presets.nim:24-25` (BLS + ETH1) | `spec/beaconstate.nim:1534-1539` |
| **lodestar** | `state-transition/src/util/electra.ts:7-9, 11-15` + `util/capella.ts:6-8`; constants in `params/src/index.ts:145-146` | `state-transition/src/util/electra.ts:17-34` |
| **grandine** | `helper_functions/src/predicates.rs:303-312, 384-400`; constants in `types/src/electra/consts.rs:10` (compounding) + `types/src/phase0/consts.rs:19` (eth1) | `helper_functions/src/mutators.rs:135-147` |

## Notable per-client divergences (all observable-equivalent at Pectra)

### prysm: DUPLICATE `switch_to_compounding_validator` implementations

```go
// core/electra/validator.go:22-36 (PUBLIC, spec-conformant):
func SwitchToCompoundingValidator(s state.BeaconState, idx primitives.ValidatorIndex) error {
    v, err := s.ValidatorAtIndex(idx)
    if err != nil { return err }
    if len(v.WithdrawalCredentials) == 0 {
        return errors.New("validator has no withdrawal credentials")
    }
    v.WithdrawalCredentials[0] = params.BeaconConfig().CompoundingWithdrawalPrefixByte
    if err := s.UpdateValidatorAtIndex(idx, v); err != nil { return err }
    return QueueExcessActiveBalance(s, idx)
}

// core/requests/consolidations.go:280-294 (private, IDENTICAL logic):
func switchToCompoundingValidator(st state.BeaconState, idx primitives.ValidatorIndex) error {
    // ... line-for-line identical ...
}
```

**Code duplication concern**: if one is updated and the other isn't,
divergent behavior. Both implementations are line-identical at audit
time (same defensive nil-check, same prefix-byte mutation, same
queue-excess call). **F-tier today** (working in lockstep) but
forward-fragile.

### prysm: NO standalone `IsCompoundingWithdrawalCredential`

Prysm only exposes the validator-method form
`HasCompoundingWithdrawalCredentials()`. The byte-level standalone
predicate is INLINED into the method body. Other clients (lighthouse,
nimbus, lodestar, grandine) expose both forms. **Reduced API surface**
but slightly less reusable for non-validator credential bytes.

### prysm: pre-emptive Gloas constant `BuilderWithdrawalPrefixByte = 0x03`

```go
// prysm config/params/mainnet_config.go:96-99
BLSWithdrawalPrefixByte:         byte(0),
ETH1AddressWithdrawalPrefixByte: byte(1),
CompoundingWithdrawalPrefixByte: byte(2),
BuilderWithdrawalPrefixByte:     byte(3),     // ← Gloas pre-emptive
```

prysm defines the `0x03` (Gloas builder) prefix at Pectra time, but
no Pectra-active code path uses it. **Pre-emptive Gloas readiness**.

### nimbus: Gloas-aware `has_compounding_withdrawal_credential`

```nim
func has_compounding_withdrawal_credential*(
    consensusFork: static ConsensusFork, validator: Validator): bool =
  when consensusFork >= ConsensusFork.Gloas:
    # Gloas+: 0x02 OR 0x03 (builder)
    is_compounding_withdrawal_credential(validator.withdrawal_credentials) or
        is_builder_withdrawal_credential(validator.withdrawal_credentials)
  else:
    # Pre-Gloas (Electra/Fulu): 0x02 only
    is_compounding_withdrawal_credential(validator.withdrawal_credentials)
```

Nimbus's `has_compounding_withdrawal_credential` takes a compile-time
`consensusFork: static ConsensusFork` parameter and `when`-dispatches:
at Gloas+, BUILDER credentials (0x03) are ALSO treated as
"compounding"; at Pectra/Electra, only 0x02 qualifies. **Pre-emptive
Gloas implementation that's invisible at Pectra.**

This Gloas-aware divergence was previously flagged in item #1's audit
("Nimbus is the only client whose `has_compounding_withdrawal_credential`
is fork-gated to also accept `0x03` (builder) credentials at Gloas+").
**At Pectra, observable-equivalent across all 6 clients.**

### nimbus: pre-emptive Gloas `is_builder_withdrawal_credential`

```nim
# beaconstate.nim:53-55
func is_builder_withdrawal_credential*(
    withdrawal_credentials: Eth2Digest): bool =
  withdrawal_credentials.data[0] == BUILDER_WITHDRAWAL_PREFIX  # = 0x03
```

Same pre-emptive Gloas readiness as prysm — the constant + predicate
are present at Pectra but only used at Gloas. **F-tier today.**

### teku: subclass-override polymorphism for `hasExecutionWithdrawalCredential`

```java
// PredicatesElectra.java:98-100 (Pectra OR override)
@Override
public boolean hasExecutionWithdrawalCredential(final Validator validator) {
    return hasEth1WithdrawalCredential(validator) || hasCompoundingWithdrawalCredential(validator);
}
```

Teku's parent class `Predicates` only has `hasEth1WithdrawalCredential`
(Capella). `PredicatesElectra` overrides `hasExecutionWithdrawalCredential`
to add the OR with compounding. **Same subclass-override pattern as
items #8/#9/#10/#16/#17/#19** — cleanest fork-isolation.

### lighthouse: standalone `is_compounding_withdrawal_credential` + validator method

```rust
// validator.rs:311-320 (standalone)
pub fn is_compounding_withdrawal_credential(
    withdrawal_credentials: Hash256,
    spec: &ChainSpec,
) -> bool {
    withdrawal_credentials.as_slice().first()
        .map(|prefix_byte| *prefix_byte == spec.compounding_withdrawal_prefix_byte)
        .unwrap_or(false)   // Defensive: zero-length credentials → false
}
```

lighthouse defensively handles zero-length credentials via
`.first().unwrap_or(false)`. **Academic** — SSZ enforces credentials
length = 32 — but defensive against any future schema change.

### grandine: `[..PREFIX.len()]` slice-and-copy idiom

```rust
// mutators.rs:135-147
pub fn switch_to_compounding_validator<P: Preset>(
    state: &mut impl PostElectraBeaconState<P>,
    index: ValidatorIndex,
) -> Result<()> {
    let validator = state.validators_mut().get_mut(index)?;
    validator.withdrawal_credentials[..COMPOUNDING_WITHDRAWAL_PREFIX.len()]
        .copy_from_slice(COMPOUNDING_WITHDRAWAL_PREFIX);
    queue_excess_active_balance(state, index)?;
    Ok(())
}
```

grandine uses `[..PREFIX.len()]` slice-and-copy (where
`COMPOUNDING_WITHDRAWAL_PREFIX = &[0x02]` is a 1-byte slice). Same
result as direct byte assignment, but expresses the intent of
"replace the prefix" more clearly. **Most spec-traceable
construction**.

### lodestar: explicit slice-copy to prevent SSZ root cache invalidation

```typescript
// electra.ts:17-34
export function switchToCompoundingValidator(
  state: CachedBeaconStateElectra | CachedBeaconStateGloas,
  index: ValidatorIndex
): void {
  const validator = state.validators.get(index);
  const newWithdrawalCredentials = Uint8Array.prototype.slice.call(
    validator.withdrawalCredentials, 0, validator.withdrawalCredentials.length
  );
  newWithdrawalCredentials[0] = COMPOUNDING_WITHDRAWAL_PREFIX;
  validator.withdrawalCredentials = newWithdrawalCredentials;
  queueExcessActiveBalance(state, index);
}
```

lodestar explicitly creates a NEW Uint8Array (not in-place mutation)
to prevent SSZ root cache invalidation issues. Other clients use
direct in-place byte mutation. **JavaScript-specific concern**: the
SSZ ViewDU cache may not detect direct array mutation; explicit
re-assignment forces cache invalidation.

## Cross-cut chain — closes the credential gating subsystem

This audit closes the **credential gating subsystem** that's
referenced across the entire Pectra audit corpus:

```
[Pectra-NEW constant]: COMPOUNDING_WITHDRAWAL_PREFIX = 0x02
                ↓
[item #22 (this) predicates]:
    is_compounding_withdrawal_credential
    has_compounding_withdrawal_credential
    has_eth1_withdrawal_credential
    has_execution_withdrawal_credential
                ↓ used by:
[item #1] effective balance updates: get_max_effective_balance dispatches on has_compounding
[item #2] consolidation request: is_valid_switch_to_compounding_request gates on has_eth1
[item #3] withdrawal request: partial-only-for-0x02 gates on has_compounding
[item #6] voluntary exit: pending_balance_to_withdraw == 0 check (cross-cut)
[item #11] upgrade: early-adopter loop iterates has_compounding validators
[item #12] withdrawals: get_max_effective_balance + is_partially_withdrawable
[item #18] add_validator_to_registry: get_max_effective_balance via credentials

[item #22 mutator] switch_to_compounding_validator:
                ↓ called by:
[item #2] process_consolidation_request: switch fast path
                ↓ which calls
[item #21] queue_excess_active_balance:
                ↓ produces
state.pending_deposits.append(PendingDeposit{
    sig=G2_POINT_AT_INFINITY,
    slot=GENESIS_SLOT
})
                ↓ drained by
[item #4] process_pending_deposits: skip sig verify for slot==GENESIS_SLOT
                ↓ applied by
[item #20] apply_pending_deposit: existing-validator top-up path (pubkey already in registry)
```

Every predicate-gated decision in the Pectra surface ultimately
flows through this audit's helpers. **Foundational closure.**

## EF fixture status — implicit coverage via items #1-#21

This audit has **no dedicated EF fixture set** because the helpers
are pure predicates and a small mutator. They are exercised
IMPLICITLY via every prior audit item that uses them:

| Item | Predicate(s) used |
|---|---|
| #1 effective_balance_updates | has_compounding |
| #2 consolidation_request | has_eth1, has_compounding (in is_valid_switch_to_compounding_request) |
| #3 withdrawal_request | has_compounding |
| #6 voluntary_exit | has_compounding (for pending_balance_to_withdraw) |
| #11 upgrade_to_electra | has_compounding (early-adopter loop) |
| #12 process_withdrawals | has_execution_withdrawal_credential |
| #18 add_validator_to_registry | has_compounding (via get_max_effective_balance) |
| #21 queue_excess_active_balance | called by switch_to_compounding_validator |

**Cumulative implicit cross-validation evidence**: ~250 EF fixtures
× 4 wired clients = **~1000 PASSes** across items that use these
predicates. Any divergence in the predicate semantics or the switch
mutator would have surfaced as a fixture failure in at least one
of the prior items. None did.

A dedicated fixture set for the credential helpers would be:
1. Predicates: byte-vector inputs (32 bytes with various prefix
   bytes) → bool outputs across all 4 predicates. **Pure functions,
   trivially fuzzable.**
2. `switch_to_compounding_validator`: pre-state with one validator
   → post-state with credentials[0] = 0x02 + a PendingDeposit
   appended.

## Adjacent untouched

- **Generate dedicated EF fixture set** for the predicates and the
  mutator — pure-function cross-client equivalence test.
- **prysm code duplication audit**: `core/electra/validator.go`
  vs `core/requests/consolidations.go` `switchToCompoundingValidator`
  — codify a contract test that asserts both implementations behave
  identically; consider deduplication via shared helper.
- **prysm + nimbus pre-emptive Gloas readiness**: codify the
  `0x03` (BUILDER) prefix as Gloas-only. Verify the predicate
  doesn't accidentally treat 0x03 as "execution withdrawable" at
  Pectra (would be a security issue — 0x03 validators shouldn't
  be withdrawable until Gloas activates).
- **nimbus Gloas-aware `has_compounding_withdrawal_credential`** —
  cross-client codification: at Gloas, lodestar/grandine/lighthouse
  may also need to update their predicate to include 0x03. Track for
  Gloas activation.
- **lighthouse defensive `.first().unwrap_or(false)`** — codify the
  rationale (zero-length credentials are unreachable per SSZ
  schema, but the defensive check protects against future schema
  changes).
- **lodestar Uint8Array slice-copy idiom** — verify cross-client
  that direct in-place byte mutation doesn't cause SSZ root cache
  staleness in other clients (lighthouse, prysm, teku, nimbus,
  grandine). lodestar's defensive copy is unique among the 6.
- **`is_compounding_withdrawal_credential` standalone form**:
  prysm doesn't expose it; the others do. Cross-client API surface
  consistency.
- **Constants centralization**: prysm has them in
  `params/mainnet_config.go`; lighthouse in `chain_spec.rs`;
  teku in dedicated `WithdrawalPrefixes.java`; nimbus split between
  `presets.nim` (BLS+ETH1) and `constants.nim` (compounding+builder)
  — split organization could mask a renaming refactor; grandine
  split between `phase0/consts.rs` and `electra/consts.rs`. The
  per-client organization is observable-equivalent but worth
  documenting.
- **Defense-in-depth: 0x00 (BLS) credentials gating**: BLS-prefixed
  validators can NOT withdraw (item #12 confirms). Verify cross-client
  that this is enforced via the `has_execution_withdrawal_credential`
  predicate (returning false for 0x00 → no withdrawal path).
- **`switch_to_compounding_validator` 0x00 → 0x02 case**: pyspec
  doesn't restrict source credentials. If somehow the source has
  0x00, the switch would set [0]=0x02 and preserve bytes [1:31]
  (which could be arbitrary). At item #2 the switch is gated by
  `is_valid_switch_to_compounding_request` which requires source
  credentials are 0x01 (eth1) — but the helper itself doesn't
  enforce this. Worth documenting the precondition.

## Future research items

1. **Generate dedicated EF fixture set** for the 4 predicates and
   the switch mutator — pure-function fuzzing.
2. **prysm code duplication contract test**: assert
   `core/electra/validator.go::SwitchToCompoundingValidator` and
   `core/requests/consolidations.go::switchToCompoundingValidator`
   produce identical state mutations.
3. **prysm + nimbus pre-emptive Gloas `0x03` treatment audit**:
   verify the BUILDER prefix is NOT treated as "execution
   withdrawable" at Pectra activation.
4. **Cross-client Gloas-aware predicate audit at Gloas activation**:
   when Gloas activates, ensure all 6 clients update
   `has_compounding_withdrawal_credential` (or equivalent) to
   include 0x03 — currently only nimbus has the Gloas-aware
   dispatch.
5. **lighthouse defensive `.first().unwrap_or(false)` rationale**
   codification.
6. **lodestar Uint8Array slice-copy SSZ-cache-invalidation**
   cross-client equivalence test (verify other clients' in-place
   mutation doesn't cause stale roots).
7. **Constants centralization documentation** — per-client
   organization differences.
8. **`has_execution_withdrawal_credential = false` for 0x00**
   defense-in-depth verification (BLS validators must NOT be
   withdrawable).
9. **`switch_to_compounding_validator` precondition** documentation:
   the helper assumes source credentials are 0x01 (enforced by
   item #2's `is_valid_switch_to_compounding_request`); the helper
   itself doesn't enforce this. Codify as a contract assertion.
10. **`is_compounding_withdrawal_credential` standalone form**
    cross-client API consistency — add to prysm for parity with
    other 5 clients.
