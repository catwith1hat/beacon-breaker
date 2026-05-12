---
status: source-code-reviewed
impact: mainnet-everyone
last_update: 2026-05-12
builds_on: [1, 2, 11, 12, 18, 21]
eips: [EIP-7251, EIP-7732]
splits: [nimbus]
# main_md_summary: nimbus treats 0x03 (builder) credentials as compounding at Gloas+ via stale `has_compounding_withdrawal_credential` OR-fold — pre-Gloas 0x03 deposit forks effective_balance at Gloas activation
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.3
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.3.1
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 22: Compounding/credential subsystem helpers (predicates + `switch_to_compounding_validator`)

## Summary

Five small Pectra-NEW (or Pectra-modified) helpers that gate `0x02` vs `0x01` vs `0x00` behaviour across the Pectra surface, plus the Pectra-NEW mutator `switch_to_compounding_validator`. Foundational primitives — used by items #1, #2, #3, #6, #11, #12, #18, #21.

**Pectra surface:** all six clients implement identical strict-prefix-byte predicates with identical `0x00`/`0x01`/`0x02` constants, identical OR semantics for `has_execution_withdrawal_credential = has_eth1 OR has_compounding`, and a `switch_to_compounding_validator` mutator that overwrites only byte `[0]` then calls `queue_excess_active_balance` (item #21). H1–H9 (Pectra-surface invariants) hold across all six.

**Gloas surface (at the Glamsterdam target): nimbus diverges from spec + 5 other clients.** The current Gloas spec (`vendor/consensus-specs/specs/gloas/beacon-chain.md`, v1.7.0-alpha.7-21-g0e70a492d) introduces `BUILDER_WITHDRAWAL_PREFIX = 0x03` and a NEW predicate `is_builder_withdrawal_credential` (`:487-491`) — but **does NOT** modify `has_compounding_withdrawal_credential` to fold in `0x03`. Builders live in `state.builders` (separate from `state.validators`) per the EIP-7732 "non-validating staked actors" design; commit `601829f1a` (2026-01-05, "Make builders non-validating staked actors", PR #4788) explicitly REMOVED an earlier draft's `Modified has_compounding_withdrawal_credential` section.

Nimbus's `has_compounding_withdrawal_credential` in `vendor/nimbus/beacon_chain/spec/beaconstate.nim:59-68` is **fork-gated**: at `consensusFork >= ConsensusFork.Gloas`, it ORs `is_compounding_withdrawal_credential` with `is_builder_withdrawal_credential` (= true for `0x03`). The comment URL at line 58 points to the now-removed `#modified-has_compounding_withdrawal_credential` section. The other five clients implement strict-`0x02` predicates at Gloas matching the current spec.

**Mainnet-reachable consequence:** any pre-Gloas depositor can submit a `DepositRequest` with `withdrawal_credentials[0] = 0x03` (the Pectra `process_deposit_request` and downstream item #18 `get_validator_from_deposit` accept arbitrary credentials prefix). The validator gets added to `state.validators` with `0x03` credentials. At Gloas activation, nimbus's `has_compounding_withdrawal_credential` flips to true for this validator; nimbus's `get_max_effective_balance` returns `MAX_EFFECTIVE_BALANCE_ELECTRA = 2048 ETH` while the other five clients return `MIN_ACTIVATION_BALANCE = 32 ETH`. The next `process_effective_balance_updates` (item #1) diverges on this validator's `effective_balance` field — state-root fork. Attack cost: ≥ 33 ETH locked permanently (no withdrawal path for `0x03` validators).

splits: [nimbus] — 1-vs-5 split with nimbus alone diverging.

## Question

Pyspec Pectra-NEW predicates and mutator (`vendor/consensus-specs/specs/electra/beacon-chain.md:491-541, 734-740`):

```python
# Pectra-NEW constant:
COMPOUNDING_WITHDRAWAL_PREFIX = Bytes1('0x02')

def is_compounding_withdrawal_credential(withdrawal_credentials: Bytes32) -> bool:
    return withdrawal_credentials[:1] == COMPOUNDING_WITHDRAWAL_PREFIX

def has_compounding_withdrawal_credential(validator: Validator) -> bool:
    """Check if ``validator`` has an 0x02 prefixed "compounding" withdrawal credential."""
    return is_compounding_withdrawal_credential(validator.withdrawal_credentials)

def has_execution_withdrawal_credential(validator: Validator) -> bool:
    """Check if ``validator`` has a 0x01 or 0x02 prefixed withdrawal credential."""
    return (
        has_eth1_withdrawal_credential(validator)         # 0x01
        or has_compounding_withdrawal_credential(validator)  # 0x02
    )

def switch_to_compounding_validator(state: BeaconState, index: ValidatorIndex) -> None:
    validator = state.validators[index]
    validator.withdrawal_credentials = (
        COMPOUNDING_WITHDRAWAL_PREFIX + validator.withdrawal_credentials[1:]
    )
    queue_excess_active_balance(state, index)
```

Pyspec Gloas-NEW (`vendor/consensus-specs/specs/gloas/beacon-chain.md:159, 487-491`):

```python
# Gloas-NEW constant
BUILDER_WITHDRAWAL_PREFIX = Bytes1('0x03')

# Gloas-NEW predicate
def is_builder_withdrawal_credential(withdrawal_credentials: Bytes32) -> bool:
    return withdrawal_credentials[:1] == BUILDER_WITHDRAWAL_PREFIX
```

**Critical**: `has_compounding_withdrawal_credential` is NOT modified at Gloas — it continues to return true ONLY for `0x02`. Validators with `0x03` credentials are NOT treated as compounding at Gloas under the spec.

Two recheck questions:
1. Do all six clients still implement the Pectra-surface invariants (H1–H9) on their updated checkouts?
2. **At Gloas (the new target)**: do any clients fold `0x03` into `has_compounding_withdrawal_credential`? The earlier nimbus audit (2026-05-02) flagged a "pre-emptive Gloas readiness" treatment. With the spec now removing that modification, is this an observable divergence?

## Hypotheses

- **H1.** `COMPOUNDING_WITHDRAWAL_PREFIX = 0x02`, `ETH1_ADDRESS_WITHDRAWAL_PREFIX = 0x01`, `BLS_WITHDRAWAL_PREFIX = 0x00` strict byte values across all six clients.
- **H2.** `is_compounding_withdrawal_credential` = strict `[0] == 0x02` byte-equality.
- **H3.** `has_compounding_withdrawal_credential(validator)` wraps the byte predicate (Pectra surface).
- **H4.** `has_eth1_withdrawal_credential(validator)` = strict `[0] == 0x01` (Capella heritage).
- **H5.** `has_execution_withdrawal_credential(validator) = has_eth1 OR has_compounding` (NOT AND).
- **H6.** `switch_to_compounding_validator` modifies ONLY byte `[0]` (preserves bytes `[1:32]` for the `0x01 → 0x02` transition).
- **H7.** `switch_to_compounding_validator` calls `queue_excess_active_balance` (item #21) after credential update.
- **H8.** Single-byte assignment is observable-equivalent to the pyspec's `COMPOUNDING_WITHDRAWAL_PREFIX + ...[1:]` slice-and-concat across all six clients.
- **H9.** `0x00` (BLS) credentials are NEVER returned true by `has_execution_withdrawal_credential` (defense-in-depth: BLS validators cannot withdraw).
- **H10.** *(Glamsterdam target — Gloas-NEW constants)*. `BUILDER_WITHDRAWAL_PREFIX = 0x03` defined in all six clients; `is_builder_withdrawal_credential(creds) = ([0] == 0x03)` defined in five clients (prysm, teku, nimbus, lodestar, grandine). **Lighthouse has the constant but NOT the predicate** (`vendor/lighthouse/consensus/types/src/core/chain_spec.rs:93, 1054, 1448` define `builder_withdrawal_prefix_byte: u8 = 0x03`; no `is_builder_withdrawal_credential` function exists in `vendor/lighthouse/`) — propagation of items #14 H9 / #19 H10 lighthouse Gloas-readiness gap.
- **H11.** *(Glamsterdam target — current spec gating of `has_compounding_withdrawal_credential`)*. `has_compounding_withdrawal_credential` is NOT modified at Gloas under the current spec (`vendor/consensus-specs/specs/gloas/beacon-chain.md` — no `Modified has_compounding_withdrawal_credential` heading; commit `601829f1a` removed it). At Gloas, `has_compounding_withdrawal_credential(validator)` returns true ONLY for `0x02`, NOT for `0x03`.
- **H12.** *(Glamsterdam target — divergent client)*. **Nimbus diverges from spec + 5 other clients.** `vendor/nimbus/beacon_chain/spec/beaconstate.nim:59-68` fork-gates `has_compounding_withdrawal_credential` to OR with `is_builder_withdrawal_credential` at `consensusFork >= ConsensusFork.Gloas`. The five other clients implement strict-`0x02` at Gloas matching the current spec. Mainnet-reachable via pre-Gloas `0x03` deposit (at least 33+ ETH locked permanently). Splits = [nimbus].

## Findings

H1–H11 satisfied; **H12 is the active mainnet-everyone divergence.**

### prysm

`vendor/prysm/beacon-chain/state/state-native/readonly_validator.go:93-106`:

```go
func (v readOnlyValidator) HasETH1WithdrawalCredentials() bool {
    return v.validator.WithdrawalCredentials[0] == params.BeaconConfig().ETH1AddressWithdrawalPrefixByte
}

func (v readOnlyValidator) HasCompoundingWithdrawalCredentials() bool {
    return v.validator.WithdrawalCredentials[0] == params.BeaconConfig().CompoundingWithdrawalPrefixByte
}

func (v readOnlyValidator) HasExecutionWithdrawalCredentials() bool {
    return v.HasETH1WithdrawalCredentials() || v.HasCompoundingWithdrawalCredentials()
}
```

Constants in `vendor/prysm/config/params/mainnet_config.go:96-99`: `BLSWithdrawalPrefixByte=0`, `ETH1AddressWithdrawalPrefixByte=1`, `CompoundingWithdrawalPrefixByte=2`, `BuilderWithdrawalPrefixByte=3`. Note the `0x03` prefix constant exists at Pectra, but `HasCompoundingWithdrawalCredentials` strictly checks `0x02` only — **no fork-gated fold-in of `0x03`**. The `0x03` constant is consumed only by the Gloas-conditional builder deposit-routing path (`vendor/prysm/beacon-chain/core/gloas/deposit_request.go:133 IsBuilderWithdrawalCredential`).

`SwitchToCompoundingValidator` in `vendor/prysm/beacon-chain/core/electra/validator.go:56-81`:

```go
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
```

`vendor/prysm/beacon-chain/core/requests/consolidations.go:280-294` contains a line-for-line DUPLICATE `switchToCompoundingValidator` (private). Forward-fragility concern (carried forward from earlier audit) — same body but two locations.

`vendor/prysm/beacon-chain/core/helpers/builder.go:9-12`:

```go
func IsBuilderWithdrawalCredential(withdrawalCredentials []byte) bool {
    return len(withdrawalCredentials) > 0 &&
        withdrawalCredentials[0] == params.BeaconConfig().BuilderWithdrawalPrefixByte
}
```

Separate `IsBuilderWithdrawalCredential` predicate; NOT folded into `HasCompoundingWithdrawalCredentials`. **Spec-conformant at Gloas.**

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓ (constant + predicate). H11 ✓ (no Gloas fold-in). H12: **prysm is on the correct side** of the 1-vs-5 split.

### lighthouse

`vendor/lighthouse/consensus/types/src/validator/validator.rs:159-170`:

```rust
pub fn has_eth1_withdrawal_credential(&self, spec: &ChainSpec) -> bool {
    self.withdrawal_credentials
        .as_slice()
        .first()
        .map(|byte| *byte == spec.eth1_address_withdrawal_prefix_byte)
        .unwrap_or(false)
}

pub fn has_compounding_withdrawal_credential(&self, spec: &ChainSpec) -> bool {
    is_compounding_withdrawal_credential(self.withdrawal_credentials, spec)
}
```

Standalone byte predicate at `:311-320 is_compounding_withdrawal_credential`. Strict `[0] == spec.compounding_withdrawal_prefix_byte`. Defensive `.first().unwrap_or(false)` for zero-length credentials (academic — SSZ enforces 32-byte length).

`switch_to_compounding_validator` as a state method at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2692-2706`:

```rust
pub fn switch_to_compounding_validator(
    &mut self,
    validator_index: usize,
    spec: &ChainSpec,
) -> Result<(), Error> {
    let validator = self.get_validator_mut(validator_index)?;
    validator.withdrawal_credentials.as_mut_slice()[0] = spec.compounding_withdrawal_prefix_byte;
    self.queue_excess_active_balance(validator_index, spec)?;
    Ok(())
}
```

Constants in `vendor/lighthouse/consensus/types/src/core/chain_spec.rs:90-93, 1051-1054, 1444-1448`: `bls_withdrawal_prefix_byte=0x00`, `eth1_address_withdrawal_prefix_byte=0x01`, `compounding_withdrawal_prefix_byte=0x02`, `builder_withdrawal_prefix_byte=0x03` (mainnet + minimal presets).

**Critical lighthouse Gloas-readiness gap:** `builder_withdrawal_prefix_byte` constant exists, but **no `is_builder_withdrawal_credential` function** anywhere in `vendor/lighthouse/` (grep confirms — only the constant matches). This is propagation of items #14 H9 / #19 H10 (lighthouse hasn't wired the EIP-7732 builder deposit path). At Gloas, lighthouse cannot route `0x03` deposits to `state.builders` because the predicate doesn't exist.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✗** (constant present, predicate missing — propagates from items #14/#19 lighthouse gap). H11 ✓ (no fold-in, but only because the predicate's missing entirely). H12: lighthouse is on the correct side of the split for THIS item's surface (`has_compounding_withdrawal_credential` returns false for `0x03`). The lighthouse Gloas-readiness gap is a SEPARATE issue at items #14 H9 / #19 H10 — not nimbus's predicate divergence.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/PredicatesElectra.java:98-119`:

```java
@Override
public boolean hasExecutionWithdrawalCredential(final Validator validator) {
    return hasEth1WithdrawalCredential(validator) || hasCompoundingWithdrawalCredential(validator);
}

@Override
public boolean hasCompoundingWithdrawalCredential(final Validator validator) {
    return isCompoundingWithdrawalCredential(validator.getWithdrawalCredentials());
}

@Override
public boolean isCompoundingWithdrawalCredential(final Bytes32 withdrawalCredentials) {
    return withdrawalCredentials.get(0) == COMPOUNDING_WITHDRAWAL_BYTE;
}
```

`PredicatesGloas extends PredicatesElectra` in `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/helpers/PredicatesGloas.java:30-70`:

```java
public class PredicatesGloas extends PredicatesElectra {
    public PredicatesGloas(final SpecConfig specConfig) { super(specConfig); }

    public boolean isBuilderIndex(final UInt64 validatorIndex) { ... }
    public boolean isActiveBuilder(final BeaconState state, final UInt64 builderIndex) { ... }

    public boolean isBuilderWithdrawalCredential(final Bytes32 withdrawalCredentials) {
        return withdrawalCredentials.get(0) == BUILDER_WITHDRAWAL_BYTE;
    }
}
```

`PredicatesGloas` adds `isBuilderWithdrawalCredential` but **does NOT override `hasCompoundingWithdrawalCredential`** — the strict-`0x02` Electra implementation is inherited. Cleanest subclass-override pattern (same as items #8/#9/#10/#16/#17/#19).

`switch_to_compounding_validator` in `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/helpers/BeaconStateMutatorsElectra.java:176-188`:

```java
public void switchToCompoundingValidator(final MutableBeaconState state, final int index) {
    final Validator validator = state.getValidators().get(index);
    final Bytes32 currentCredentials = validator.getWithdrawalCredentials();
    final Bytes32 newCredentials = Bytes32.wrap(
        Bytes.concatenate(COMPOUNDING_WITHDRAWAL_PREFIX, currentCredentials.slice(1)));
    state.getValidators().set(index, validator.withWithdrawalCredentials(newCredentials));
    queueExcessActiveBalance(state, index);
}
```

Most spec-faithful construction — uses `Bytes.concatenate(COMPOUNDING_WITHDRAWAL_PREFIX, currentCredentials.slice(1))`, exactly mirroring pyspec's `COMPOUNDING_WITHDRAWAL_PREFIX + validator.withdrawal_credentials[1:]`. Constants in `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/constants/WithdrawalPrefixes.java:19-29`: `BLS_WITHDRAWAL_BYTE=0x00`, `ETH1_ADDRESS_WITHDRAWAL_BYTE=0x01`, `COMPOUNDING_WITHDRAWAL_BYTE=0x02`, `BUILDER_WITHDRAWAL_BYTE=0x03`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12: **teku is on the correct side** of the split.

### nimbus

`vendor/nimbus/beacon_chain/spec/beaconstate.nim:47-68`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.5.0-alpha.3/specs/electra/beacon-chain.md#new-is_compounding_withdrawal_credential
func is_compounding_withdrawal_credential*(
    withdrawal_credentials: Eth2Digest): bool =
  withdrawal_credentials.data[0] == COMPOUNDING_WITHDRAWAL_PREFIX

# https://github.com/ethereum/consensus-specs/blob/v1.6.0-beta.0/specs/gloas/beacon-chain.md#new-is_builder_withdrawal_credential
func is_builder_withdrawal_credential*(
    withdrawal_credentials: Eth2Digest): bool =
  withdrawal_credentials.data[0] == BUILDER_WITHDRAWAL_PREFIX

# https://github.com/ethereum/consensus-specs/blob/v1.6.0-beta.0/specs/electra/beacon-chain.md#new-has_compounding_withdrawal_credential
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-beta.0/specs/gloas/beacon-chain.md#modified-has_compounding_withdrawal_credential
func has_compounding_withdrawal_credential*(
    consensusFork: static ConsensusFork, validator: Validator): bool =
  when consensusFork >= ConsensusFork.Gloas:
    ## Check if ``validator`` has an 0x02 or 0x03 prefixed withdrawal credential.
    is_compounding_withdrawal_credential(validator.withdrawal_credentials) or
        is_builder_withdrawal_credential(validator.withdrawal_credentials)
  else:
    ## Check if ``validator`` has an 0x02 prefixed "compounding" withdrawal
    ## credential.
    is_compounding_withdrawal_credential(validator.withdrawal_credentials)
```

**This is the H12 divergence.** The comment at line 58 references `#modified-has_compounding_withdrawal_credential` in v1.6.0-beta.0 — which existed at the time but was REMOVED by commit `601829f1a` (PR #4788, "Make builders non-validating staked actors", 2026-01-05). The current spec at `vendor/consensus-specs/specs/gloas/beacon-chain.md` (v1.7.0-alpha.7-21-g0e70a492d) does NOT modify `has_compounding_withdrawal_credential`. Builders are now non-validating staked actors living in `state.builders` (separate `List[Builder, BUILDER_REGISTRY_LIMIT]` state field); validators in `state.validators` should NEVER have `0x03` credentials under spec-conformant state.

The nimbus `consensusFork: static ConsensusFork` parameter forces compile-time fork dispatch — at `ConsensusFork.Gloas`, the `when` branch unconditionally ORs the two byte predicates. This Gloas-aware fold cascades into `has_execution_withdrawal_credential` (`:1472-1476`):

```nim
func has_execution_withdrawal_credential*(
    consensusFork: static ConsensusFork, validator: Validator): bool =
  has_compounding_withdrawal_credential(consensusFork, validator) or
    has_eth1_withdrawal_credential(validator)
```

So at Gloas+, nimbus's `has_execution_withdrawal_credential` ALSO returns true for `0x03` — the divergence propagates into withdrawal-eligibility checks (`is_fully_withdrawable_validator`, `is_partially_withdrawable_validator` at `:1480-1513`) and into `get_max_effective_balance` (`:71-77 — uses has_compounding_withdrawal_credential to dispatch between 2048 ETH and 32 ETH ceiling`).

**Reachability**: any pre-Gloas depositor can submit a `DepositRequest` with `withdrawal_credentials[0] = 0x03`. The Pectra `process_deposit_request` (item #14) and downstream item #18 `get_validator_from_deposit` accept arbitrary credentials prefix. The validator gets added to `state.validators` with `0x03` credentials, effective_balance ≤ 32 ETH at Pectra (all 6 clients agree: predicate returns false at Pectra/Electra/Fulu for `0x03`). The 0x03 validator persists across the Fulu → Gloas upgrade (`upgrade_to_gloas` inherits `validators=pre.validators`).

At Gloas activation's first `process_effective_balance_updates` (item #1):
- nimbus's `get_max_effective_balance(Gloas, validator)` returns `MAX_EFFECTIVE_BALANCE_ELECTRA = 2048 ETH` for this `0x03` validator.
- Other 5 clients' equivalents return `MIN_ACTIVATION_BALANCE = 32 ETH`.
- If `balance > 32 ETH + UPWARD_HYSTERESIS_THRESHOLD` (`= 32 + 1.25 = 33.25 ETH`), hysteresis fires:
  - nimbus: `effective_balance = min(balance - balance % EBI, 2048) ≈ balance`.
  - others: `effective_balance = min(balance, 32) = 32 ETH`.
- DIVERGENCE on this validator's `validator.effective_balance` field → state-root mismatch.

`switch_to_compounding_validator` in `vendor/nimbus/beacon_chain/spec/beaconstate.nim:1534-1539`:

```nim
proc switch_to_compounding_validator*(
    state: var (electra.BeaconState | fulu.BeaconState | gloas.BeaconState),
    index: ValidatorIndex) =
  state.validators.mitem(index).withdrawal_credentials.data[0] =
    COMPOUNDING_WITHDRAWAL_PREFIX
  queue_excess_active_balance(state, index.uint64)
```

Standard `[0]`-byte assignment. Constants in `vendor/nimbus/beacon_chain/spec/datatypes/constants.nim:87-90` (COMPOUNDING + BUILDER) and `vendor/nimbus/beacon_chain/spec/presets.nim:24-25` (BLS + ETH1).

H1 ✓. H2 ✓. H3 ✓ (Pectra surface). H4 ✓. H5 ✓ (Pectra surface; Gloas surface diverges). H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓ (constant + predicate). **H11 ✗** (Gloas-aware OR is stale relative to current spec). **H12 ✗ — splits=[nimbus]**.

### lodestar

`vendor/lodestar/packages/state-transition/src/util/electra.ts:7-15`:

```typescript
export function hasCompoundingWithdrawalCredential(withdrawalCredentials: Uint8Array): boolean {
  return withdrawalCredentials[0] === COMPOUNDING_WITHDRAWAL_PREFIX;
}

export function hasExecutionWithdrawalCredential(withdrawalCredentials: Uint8Array): boolean {
  return (
    hasCompoundingWithdrawalCredential(withdrawalCredentials) || hasEth1WithdrawalCredential(withdrawalCredentials)
  );
}
```

Strict `[0] === 0x02`. No fork-gated fold-in. `vendor/lodestar/packages/state-transition/src/util/gloas.ts:24-26`:

```typescript
export function isBuilderWithdrawalCredential(withdrawalCredentials: Uint8Array): boolean {
  return withdrawalCredentials[0] === BUILDER_WITHDRAWAL_PREFIX;
}
```

Separate Gloas-NEW predicate, not folded into `hasCompoundingWithdrawalCredential`. Constants in `vendor/lodestar/packages/params/src/index.ts:145-147`: `BLS_WITHDRAWAL_PREFIX=0x00`, `ETH1_ADDRESS_WITHDRAWAL_PREFIX=0x01`, `COMPOUNDING_WITHDRAWAL_PREFIX=0x02`, `BUILDER_WITHDRAWAL_PREFIX=0x03`.

`switchToCompoundingValidator` at `vendor/lodestar/packages/state-transition/src/util/electra.ts:17-34`:

```typescript
export function switchToCompoundingValidator(
  state: CachedBeaconStateElectra | CachedBeaconStateGloas,
  index: ValidatorIndex
): void {
  const validator = state.validators.get(index);
  // directly modifying the byte leads to ssz missing the modification resulting into
  // wrong root compute, although slicing can be avoided but anyway this is not going
  // to be a hot path so its better to clean slice and avoid side effects
  const newWithdrawalCredentials = Uint8Array.prototype.slice.call(
    validator.withdrawalCredentials, 0, validator.withdrawalCredentials.length
  );
  newWithdrawalCredentials[0] = COMPOUNDING_WITHDRAWAL_PREFIX;
  validator.withdrawalCredentials = newWithdrawalCredentials;
  queueExcessActiveBalance(state, index);
}
```

Explicit slice-and-assign to force SSZ ViewDU cache invalidation (JavaScript-specific concern documented in the comment). Type signature `CachedBeaconStateElectra | CachedBeaconStateGloas` confirms single implementation across both forks.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12: **lodestar is on the correct side** of the split.

### grandine

`vendor/grandine/helper_functions/src/predicates.rs:383-411`:

```rust
#[must_use]
pub fn is_compounding_withdrawal_credential(withdrawal_credentials: H256) -> bool {
    withdrawal_credentials.as_bytes().starts_with(COMPOUNDING_WITHDRAWAL_PREFIX)
}

// > Check if ``validator`` has an 0x02 prefixed "compounding" withdrawal credential.
#[must_use]
pub fn has_compounding_withdrawal_credential(validator: &Validator) -> bool {
    is_compounding_withdrawal_credential(validator.withdrawal_credentials)
}

// > Check if ``validator`` has a 0x01 or 0x02 prefixed withdrawal credential.
#[must_use]
pub fn has_execution_withdrawal_credential(validator: &Validator) -> bool {
    has_compounding_withdrawal_credential(validator) || has_eth1_withdrawal_credential(validator)
}

#[must_use]
pub fn is_builder_withdrawal_credential(withdrawal_credentials: H256) -> bool {
    withdrawal_credentials.as_bytes().starts_with(BUILDER_WITHDRAWAL_PREFIX)
}

#[must_use]
pub fn has_builder_withdrawal_credential(validator: &Validator) -> bool {
    is_builder_withdrawal_credential(validator.withdrawal_credentials)
}
```

Strict-`0x02` `has_compounding_withdrawal_credential`; separate `has_builder_withdrawal_credential` for `0x03`. No fork-conditional fold-in. **Grandine is the ONLY client (other than nimbus) to expose `has_builder_withdrawal_credential` as a public validator-method form** — used in `vendor/grandine/helper_functions/src/fork.rs:981` for the Gloas upgrade's builder onboarding (`onboard_builders_from_pending_deposits`).

`switch_to_compounding_validator` at `vendor/grandine/helper_functions/src/mutators.rs:135-147`:

```rust
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

`[..PREFIX.len()]` slice-and-copy expresses the spec's "replace prefix" intent most clearly. Constants in `vendor/grandine/types/src/electra/consts.rs:10` (compounding), `vendor/grandine/types/src/gloas/consts.rs:30` (builder), `vendor/grandine/types/src/phase0/consts.rs:19` (eth1).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12: **grandine is on the correct side** of the split.

## Cross-reference table

| Client | `has_compounding` Gloas behaviour | `is_builder` predicate | Gloas fork dispatch | H12 verdict |
|---|---|---|---|---|
| prysm | strict `0x02` (`readonly_validator.go:99-101`) | `core/helpers/builder.go:9 IsBuilderWithdrawalCredential` (Gloas-specific routing only) | none — single Pectra impl reused at Gloas | ✓ spec-conformant |
| lighthouse | strict `0x02` (`validator.rs:168-170`) | **MISSING** (only `chain_spec.rs:93 builder_withdrawal_prefix_byte` constant) | none — items #14 H9 / #19 H10 propagation | ✓ at this surface (separate Gloas gap) |
| teku | strict `0x02` (`PredicatesElectra.java:108`); `PredicatesGloas` inherits without override | `PredicatesGloas.java:62 isBuilderWithdrawalCredential` | subclass extension; no override of `hasCompoundingWithdrawalCredential` | ✓ spec-conformant |
| **nimbus** | **OR-folded with `0x03` at `consensusFork >= ConsensusFork.Gloas`** (`beaconstate.nim:59-68`) | `beaconstate.nim:53-55 is_builder_withdrawal_credential` | `when consensusFork >= ConsensusFork.Gloas` compile-time dispatch | **✗ DIVERGES from spec + 5 others** |
| lodestar | strict `0x02` (`util/electra.ts:7-9`) | `util/gloas.ts:24-26 isBuilderWithdrawalCredential` | none — single Pectra impl reused at Gloas | ✓ spec-conformant |
| grandine | strict `0x02` (`predicates.rs:391-394`); separate `has_builder_withdrawal_credential` | `predicates.rs:403-406 is_builder_withdrawal_credential` + `:410 has_builder_withdrawal_credential` | none — separate predicate, not folded | ✓ spec-conformant |

## Empirical tests

### Pectra-surface implicit coverage

No dedicated EF fixture set — these are predicates and a small mutator. Exercised IMPLICITLY via every prior Pectra audit item using them:

| Item | Predicate(s) used |
|---|---|
| #1 effective_balance_updates | `has_compounding_withdrawal_credential` (via `get_max_effective_balance`) |
| #2 consolidation_request | `has_eth1`, `has_compounding` (in `is_valid_switch_to_compounding_request`); `switch_to_compounding_validator` |
| #3 withdrawal_request | `has_compounding`, `has_execution_withdrawal_credential` |
| #11 upgrade_to_electra | `has_compounding` (early-adopter loop) |
| #12 process_withdrawals | `has_execution_withdrawal_credential` (gates `is_*_withdrawable_validator`) |
| #18 add_validator_to_registry | `has_compounding` (via `get_max_effective_balance`) |
| #21 queue_excess_active_balance | called by `switch_to_compounding_validator` |

**Cumulative implicit cross-validation evidence**: ~250 unique fixtures × 4 wired clients = **~1000 EF fixture PASSes** flow through these helpers on the Pectra surface. No divergence surfaced.

### Gloas-surface

No Gloas fixtures wired for these predicates yet. H11 / H12 are source-only.

The Gloas state-transition test corpus (`vendor/consensus-specs/tests/core/pyspec/eth2spec/test/gloas/`) does not yet include a fixture that places a `0x03`-credentialled validator in `state.validators` and tests `process_effective_balance_updates` — this gap is exactly the implicit coverage that would surface the nimbus divergence.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — dedicated EF fixture set for the four predicates).** Inputs: 32-byte credentials with prefix `0x00`, `0x01`, `0x02`, `0x03`, plus malformed (`0x04` upward). Expected outputs cross-table:
  | Prefix | `is_compounding` | `has_compounding` | `has_eth1` | `has_execution` | `is_builder` |
  | ---: | :-: | :-: | :-: | :-: | :-: |
  | `0x00` | F | F | F | F | F |
  | `0x01` | F | F | T | T | F |
  | `0x02` | T | T | F | T | F |
  | `0x03` | F | F | F | F | T |
  | `0x04+` | F | F | F | F | F |
  
  At Gloas, **nimbus would return `has_compounding(0x03) = T` and `has_execution(0x03) = T`** — observable divergence from the table at the predicate-level cross-client test.

- **T1.2 (priority — `switch_to_compounding_validator` per-byte preservation).** Pre-state with credentials `[0x01, a, b, c, ..., z]`. Call. Expected post: credentials `[0x02, a, b, c, ..., z]` (bytes `[1:32]` UNCHANGED). All 6 clients.

#### T2 — Adversarial probes
- **T2.1 (Glamsterdam-target — H12 fork attack).** Pre-Gloas: submit DepositRequest with `withdrawal_credentials = 0x03 || <31 bytes>` and amount = 32 ETH. Wait for activation. Top-up to balance > 33.25 ETH (must clear UPWARD_HYSTERESIS_THRESHOLD = 1.25 ETH). Wait for Gloas activation. Run `process_effective_balance_updates`. Assert: nimbus's `validator.effective_balance > 32 ETH`; other 5 clients' `validator.effective_balance = 32 ETH`. **State root divergence at Gloas activation epoch + 1.**

- **T2.2 (adversarial — withdrawal-eligibility divergence).** Same `0x03` validator. At Gloas+, check `is_partially_withdrawable_validator` / `is_fully_withdrawable_validator`. For nimbus: `has_execution_withdrawal_credential(Gloas, validator) = T`. Other 5: `F`. If conditions align (effective_balance == max_effective_balance, balance > max_effective_balance, withdrawable_epoch ≤ epoch), nimbus would produce a Withdrawal entry; others would not. Additional state divergence at `expected_withdrawals` queue + `next_withdrawal_index`.

- **T2.3 (defensive — `switch_to_compounding_validator` preconditions).** Pre-state with `0x00` (BLS) credentials. Call `switch_to_compounding_validator`. Pyspec doesn't restrict source credentials — sets `[0]=0x02`, preserves `[1:32]` (zeros or arbitrary). Item #2's `is_valid_switch_to_compounding_request` gates the realistic call path (requires source `= 0x01`), but the helper itself doesn't enforce. Cross-client: all 6 should unconditionally write `0x02` to byte `[0]`. Document the precondition.

- **T2.4 (defensive — defense-in-depth `0x00` BLS gating).** Confirm `has_execution_withdrawal_credential(validator)` returns `false` for `0x00` credentials across all 6 clients — BLS validators MUST NOT be withdrawable. Critical for item #12's `is_*_withdrawable_validator` gating.

- **T2.5 (Glamsterdam-target — prysm code duplication contract test).** Assert `core/electra/validator.go::SwitchToCompoundingValidator` and `core/requests/consolidations.go::switchToCompoundingValidator` produce identical state mutations on the same input. Forward-fragility hedge.

## Mainnet reachability

**impact: mainnet-everyone.** Reachable by any pre-Gloas depositor at cost ≥ 33 ETH locked permanently.

**Attack mechanism (1-vs-5 fork at Gloas activation, splits=[nimbus]):**

1. **Pre-Gloas — any time before `GLOAS_FORK_EPOCH`.** Attacker submits a Pectra-era `DepositRequest` (or legacy Eth1 deposit) via the L1 deposit contract with:
   - any valid BLS pubkey + matching signature
   - `withdrawal_credentials = 0x03 || <31 arbitrary bytes>`
   - `amount = 32 ETH`
   
   The L1 deposit contract emits the Deposit event unchanged. The CL's Pectra `process_deposit_request` (item #14, electra surface) does NOT gate on the credentials prefix byte — only routes builder-credentialled deposits to `apply_deposit_for_builder` AT GLOAS, not at Pectra. The deposit is enqueued in `state.pending_deposits`.

2. **Pre-Gloas — drain.** Item #4's `process_pending_deposits` drains the pending deposit. Item #20's `apply_pending_deposit` checks signature (valid), runs new-validator path → item #18's `add_validator_to_registry` → `get_validator_from_deposit` creates a validator with `withdrawal_credentials[0] = 0x03`. At Pectra/Electra/Fulu, `has_compounding_withdrawal_credential(validator) = false` for all 6 clients (predicate is strict-`0x02` everywhere pre-Gloas) → `effective_balance ≤ MIN_ACTIVATION_BALANCE = 32 ETH`.

3. **Pre-Gloas — top-up.** Attacker submits a second `DepositRequest` to the same pubkey with `amount ≥ 1.5 ETH`. Item #14 enqueues; item #4 drains; item #20 dispatches to existing-pubkey top-up path (`increase_balance`). Validator's underlying `balance` now > 33.25 ETH (clears the UPWARD_HYSTERESIS_THRESHOLD = 1.25 ETH); `effective_balance` remains at 32 ETH (capped at MAX = 32 ETH per non-Gloas-aware predicate).

4. **Gloas activates** (`upgrade_to_gloas`, `vendor/consensus-specs/specs/gloas/fork.md:122-197`). Post-state inherits `validators = pre.validators` from Fulu, including the `0x03` validator. No early-adopter loop fires (per item #21 audit — `upgrade_to_gloas` is purposely empty of validator-credential re-processing).

5. **Gloas activation epoch + 1 — first `process_effective_balance_updates`** (item #1):
   - **nimbus** evaluates `get_max_effective_balance(Gloas, validator)` → `has_compounding_withdrawal_credential(Gloas, validator)` returns true (because `is_builder_withdrawal_credential(0x03) = true` and the Gloas branch ORs it in) → returns `MAX_EFFECTIVE_BALANCE_ELECTRA = 2048 ETH`. Hysteresis fires (`balance ≈ 33.3 ETH > effective_balance (32) + UPWARD_THRESHOLD (1.25)`). New `effective_balance = min(33.3 - 33.3 % EBI, 2048) ≈ 33 ETH`.
   - **prysm, lighthouse, teku, lodestar, grandine** evaluate the same call → `has_compounding_withdrawal_credential(validator)` returns false (strict-`0x02`) → returns `MIN_ACTIVATION_BALANCE = 32 ETH`. Same hysteresis fires. New `effective_balance = min(33.3, 32) = 32 ETH`.
   - **DIVERGENCE on `validator.effective_balance` field** for this validator.

6. **State root mismatch.** The block at Gloas activation epoch + 1 has a `state_root` computed by the proposer's client. Other clients reject the block as INVALID (their computed state_root differs).

**Block-production side:**
- A nimbus proposer producing the block at Gloas+1 includes `effective_balance ≈ 33 ETH` in its post-state. Other clients reject it.
- A prysm/lighthouse/teku/lodestar/grandine proposer includes `effective_balance = 32 ETH`. Nimbus rejects it.

**Resulting chain split**: nimbus follows one head; the other 5 follow another. Both heads are valid under their respective clients' rules. Finalization stalls; consensus protocol attempts to resolve via fork choice but both sides are equally weighted (modulo nimbus's stake share).

**Cost to attacker**: ~33 ETH locked permanently (no withdrawal path for `0x03` validators on any of the 6 clients — `has_execution_withdrawal_credential` returns false for `0x03` on prysm/lighthouse/teku/lodestar/grandine at all forks, and nimbus only flips `has_execution_withdrawal_credential(0x03)` to true at Gloas+, by which time the fork is already in progress). The 33 ETH cannot be recovered. At current ETH valuation, this is ~$80K-100K — well within "realistic capital" for an actor motivated to fork the network at Gloas activation.

**Mitigation:** nimbus updates `vendor/nimbus/beacon_chain/spec/beaconstate.nim:59-68` to remove the Gloas-aware OR-fold of `is_builder_withdrawal_credential`. Strict-`0x02` matches the current spec. The fix is a one-line removal of the `when consensusFork >= ConsensusFork.Gloas` branch.

**Detection (operational):** monitor the CL beacon-state RPC for validators with `withdrawal_credentials[0] = 0x03`. Any such validator on mainnet (pre-Gloas) is a fork-attack precursor.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Pectra-surface invariants (H1–H9) hold across all six. H10 (Gloas-NEW `0x03` constants + `is_builder_withdrawal_credential` predicate) holds for five clients; **lighthouse lacks the predicate** (only the constant present) — propagation of items #14 H9 / #19 H10 lighthouse Gloas-readiness gap, separate from this item's nimbus divergence.

**Glamsterdam-target finding (H12 — mainnet-everyone divergence).** Nimbus's `has_compounding_withdrawal_credential` at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:59-68` is fork-gated to OR-fold `is_builder_withdrawal_credential` at `consensusFork >= ConsensusFork.Gloas`. The current Gloas spec (v1.7.0-alpha.7-21-g0e70a492d) does NOT modify this predicate — commit `601829f1a` (PR #4788, 2026-01-05, "Make builders non-validating staked actors") REMOVED an earlier-draft `Modified has_compounding_withdrawal_credential` section when builders were redesigned as non-validating staked actors living in a separate `state.builders` registry. Nimbus's stale Gloas-aware OR-fold cascades through `has_execution_withdrawal_credential` (`:1472-1476`) into `get_max_effective_balance` (`:71-77`), `is_partially_withdrawable_validator` / `is_fully_withdrawable_validator` (`:1480-1513`), and the effective-balance-update math (item #1).

The divergence is **mainnet-everyone-reachable**: any pre-Gloas depositor can submit a 32 ETH deposit with `withdrawal_credentials[0] = 0x03` + a 1.5 ETH top-up to push balance > 33.25 ETH (clearing UPWARD_HYSTERESIS_THRESHOLD). At Gloas activation's first `process_effective_balance_updates`, nimbus's `effective_balance` for this validator diverges from the other 5 clients. State-root mismatch → chain split at Gloas activation epoch + 1. Splits = [nimbus]; 1-vs-5.

**Attacker cost**: ≥ 33 ETH locked permanently (no withdrawal path for `0x03` validators at any current fork on any client). Cheap for a motivated fork-attack adversary.

**Two other Glamsterdam-target observations from the recheck**:
- **lighthouse Gloas-readiness gap (items #14 H9 / #19 H10 propagation)**: `chain_spec.rs:93 builder_withdrawal_prefix_byte = 0x03` constant exists, but no `is_builder_withdrawal_credential` function anywhere in `vendor/lighthouse/`. This is the broader Gloas ePBS gap, not nimbus's predicate divergence — separate audit item. Lighthouse is on the *correct* side of nimbus's H12 split at this item's surface (`has_compounding_withdrawal_credential` returns false for `0x03`).
- **prysm code duplication**: `SwitchToCompoundingValidator` exists in both `vendor/prysm/beacon-chain/core/electra/validator.go:56-81` (public) and `vendor/prysm/beacon-chain/core/requests/consolidations.go:280-294` (private, line-identical). Forward-fragility — if one is updated and the other isn't, divergent behaviour. F-tier today; flag in adjacent untouched.

**Code-change recommendation (nimbus)**: in `vendor/nimbus/beacon_chain/spec/beaconstate.nim:59-68`, remove the `when consensusFork >= ConsensusFork.Gloas` branch. Replace with the unconditional Pectra body:

```nim
func has_compounding_withdrawal_credential*(
    consensusFork: static ConsensusFork, validator: Validator): bool =
  is_compounding_withdrawal_credential(validator.withdrawal_credentials)
```

The `consensusFork` parameter can stay (for API stability with callers in item #1's `get_max_effective_balance` etc.) but the body becomes fork-independent. Update the doc comment URL at line 58 to point to current Electra spec only.

**Audit-direction recommendations**:
- **Mainnet pre-Gloas monitoring**: deploy a CL beacon-state RPC poller that scans `state.validators` for `withdrawal_credentials[0] == 0x03`. Any positive hit is a fork-attack precursor signal — alert ASAP.
- **Generate dedicated EF fixture set for the four predicates** — cross-client byte-level table fuzz (T1.1).
- **Generate dedicated EF fixture set for `process_effective_balance_updates` on `0x03`-credentialled validator at Gloas** — directly cross-validates the H12 divergence.
- **Cross-client `has_execution_withdrawal_credential(0x03)` contract**: assert all 6 clients return false for `0x03` at Gloas (T2.4 + T2.2 combined). Lock down via spec-test.
- **Sister-item audit: lighthouse Gloas builder-deposit routing** — propagation of items #14 H9 / #19 H10.
- **Sister-item audit: prysm `SwitchToCompoundingValidator` duplication** — codify a contract test asserting both code paths produce identical state mutations.
- **Spec-clarification PR (consensus-specs)**: add a `Modified is_compounding_withdrawal_credential` heading at Gloas explicitly stating "this function is NOT modified at Gloas; `0x03` credentials are NOT compounding-eligible. See `is_builder_withdrawal_credential` for the new builder predicate." This kind of explicit-non-modification heading would have prevented the nimbus stale-comment bug.

## Cross-cuts

### With item #1 (`process_effective_balance_updates`)

Item #1 calls `get_max_effective_balance(validator)` which dispatches on `has_compounding_withdrawal_credential(validator)`. The H12 divergence flows directly into item #1's computation of every validator's new `effective_balance` at every epoch boundary. For non-`0x03` validators, no observable difference. For `0x03` validators, nimbus computes a different `effective_balance` than the other 5 clients.

### With item #12 (`process_withdrawals`)

Item #12 uses `has_execution_withdrawal_credential` (via `is_partially_withdrawable_validator` and `is_fully_withdrawable_validator`) to gate withdrawals. Nimbus's H12-divergent `has_execution_withdrawal_credential(Gloas, 0x03_validator) = true`; other 5 return false. If conditions align, nimbus would compute Withdrawal entries for `0x03` validators while others would not — additional divergence at `expected_withdrawals`, `next_withdrawal_index`, `next_withdrawal_validator_index`. Stacks on top of item #1's effective_balance divergence.

### With item #14 (`process_deposit_request`) + item #18 (`add_validator_to_registry`)

Item #14 (Pectra surface) accepts deposits with arbitrary `withdrawal_credentials` prefix. Item #18 creates validators verbatim from deposit data. Neither item gates on `0x03`. This is what makes the H12 attack reachable — there's no upstream filter to prevent a `0x03`-credentialled validator from being created at Pectra.

At Gloas, item #14's modified `process_deposit_request` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1585-1623`) routes NEW `0x03` deposits to `apply_deposit_for_builder` (writes to `state.builders`), but only if the pubkey isn't already a validator. Pre-existing `0x03` validators (created pre-Gloas) persist in `state.validators` — exactly the H12 attack surface.

### With item #21 (`queue_excess_active_balance`)

`switch_to_compounding_validator` calls `queue_excess_active_balance` (item #21). Item #21's audit confirmed function-body unchanged at Gloas with caller-routing migration to ePBS. The H12 nimbus divergence is upstream — at `has_compounding_withdrawal_credential` — and doesn't propagate into item #21's function body. Item #21's invariants remain satisfied.

### With Gloas `apply_deposit_for_builder` + `state.builders` registry

The Gloas-NEW `apply_deposit_for_builder` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1556-1583`) writes to `state.builders`, not `state.validators`. Builders are non-validating staked actors per EIP-7732 (post-redesign in commit `601829f1a`). The redesign is exactly what motivated removing the `Modified has_compounding_withdrawal_credential` section: builders no longer need to be folded into the validator-side compounding check because they're a separate state structure entirely. Nimbus's stale OR-fold predates this redesign.

## Adjacent untouched

1. **Nimbus fix**: remove the `when consensusFork >= ConsensusFork.Gloas` branch from `vendor/nimbus/beacon_chain/spec/beaconstate.nim:59-68 has_compounding_withdrawal_credential`.
2. **EF fixture set for the credential predicates** — cross-client byte-level prefix table (T1.1).
3. **EF fixture set: `0x03`-credentialled validator at Gloas + process_effective_balance_updates** — directly cross-validates H12.
4. **Mainnet pre-Gloas monitoring**: scan `state.validators` for `withdrawal_credentials[0] == 0x03`; alert on any hit.
5. **Sister audit: lighthouse Gloas builder predicate gap** (items #14 H9 / #19 H10 propagation).
6. **Sister audit: prysm `SwitchToCompoundingValidator` duplication** (`core/electra/validator.go` vs `core/requests/consolidations.go`) — contract test.
7. **Spec-clarification PR**: add explicit-non-modification headings for predicates that were modified in earlier drafts and walked back, to prevent stale-comment bugs in clients that bookmark intermediate spec versions.
8. **`has_execution_withdrawal_credential(0x00) = false` defense-in-depth**: cross-client codification.
9. **`switch_to_compounding_validator` precondition assertion**: document that the helper assumes source credentials are `0x01` (enforced by item #2's `is_valid_switch_to_compounding_request`); the helper itself doesn't enforce.
10. **Cross-client `0x03` validator withdrawal-blocking contract**: assert all 6 clients return false for `has_execution_withdrawal_credential(0x03)` at all forks (catches the H12 cascade into withdrawals).
11. **Spec-test for `upgrade_to_gloas` on pre-state containing `0x03` validator** — assert no state mutation specific to `0x03` (the validator persists unchanged into Gloas state).
12. **`switch_to_compounding_validator` Gloas surface review** — at Gloas, the ePBS routing of consolidations through `apply_parent_execution_payload` means switch-to-compounding is reached through a different surface; verify the helper's body is unchanged (which item #21 confirmed for `queue_excess_active_balance`).
