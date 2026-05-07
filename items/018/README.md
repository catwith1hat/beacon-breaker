# Item #18 — `add_validator_to_registry` + `get_validator_from_deposit` Pectra-modified

**Status:** no-divergence-pending-source-review — audited 2026-05-02.
The **producer of new validators** after deposit drain. Pectra-modified
`get_validator_from_deposit` enables compounding-credentials handling.
Cross-cuts items #4 (deposit drain calls these helpers), #11
(upgrade-time pre-activation seeding flows through item #4), #14
(deposit_request producer enqueues for item #4), and #1
(`get_max_effective_balance` is the credential-dependent helper used
here).

## Why this item

Pectra's compounding-credentials feature (EIP-7251) requires that a
new validator's `effective_balance` cap depend on its **withdrawal
credentials prefix**:
- `0x01` (legacy execution): cap at `MIN_ACTIVATION_BALANCE = 32 ETH`
- `0x02` (compounding, NEW): cap at `MAX_EFFECTIVE_BALANCE_ELECTRA = 2048 ETH`

This is implemented by a small but pivotal change to
`get_validator_from_deposit`:

```python
# Pre-Electra (Phase0/Altair/Bellatrix/Capella/Deneb): single-step
def get_validator_from_deposit(pubkey, withdrawal_credentials, amount):
    effective_balance = min(amount - amount % EFFECTIVE_BALANCE_INCREMENT, MAX_EFFECTIVE_BALANCE)
    return Validator(
        pubkey=pubkey,
        withdrawal_credentials=withdrawal_credentials,
        effective_balance=effective_balance,    # Fixed 32-ETH cap
        slashed=False,
        activation_eligibility_epoch=FAR_FUTURE_EPOCH,
        activation_epoch=FAR_FUTURE_EPOCH,
        exit_epoch=FAR_FUTURE_EPOCH,
        withdrawable_epoch=FAR_FUTURE_EPOCH,
    )

# Pectra (NEW): two-step (need credentials before computing EB cap)
def get_validator_from_deposit(pubkey, withdrawal_credentials, amount):
    validator = Validator(
        pubkey=pubkey,
        withdrawal_credentials=withdrawal_credentials,
        effective_balance=Gwei(0),    # STEP 1: Initially 0
        slashed=False,
        activation_eligibility_epoch=FAR_FUTURE_EPOCH,
        activation_epoch=FAR_FUTURE_EPOCH,
        exit_epoch=FAR_FUTURE_EPOCH,
        withdrawable_epoch=FAR_FUTURE_EPOCH,
    )
    # [Modified in Electra:EIP7251] STEP 2: read credentials, compute cap, set EB
    max_effective_balance = get_max_effective_balance(validator)   # 32 or 2048 ETH
    validator.effective_balance = min(
        amount - amount % EFFECTIVE_BALANCE_INCREMENT,
        max_effective_balance
    )
    return validator
```

The two-step construction is **structurally required** because
`get_max_effective_balance(validator)` reads
`validator.withdrawal_credentials` to determine the cap.

`add_validator_to_registry` itself is **structurally Altair-heritage**
(unchanged from Altair): it allocates an index, creates the validator
via `get_validator_from_deposit`, and appends to the 5 per-validator
lists (validators, balances, previous_epoch_participation,
current_epoch_participation, inactivity_scores).

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | Two-step `get_validator_from_deposit` construction (initial `effective_balance = 0`, then compute cap, then set) | ✅ all 6 |
| H2 | `get_max_effective_balance(validator)` (item #1's helper) returns 2048 ETH for 0x02, 32 ETH for 0x01, used as the cap | ✅ all 6 |
| H3 | Downward rounding to `EFFECTIVE_BALANCE_INCREMENT = 1 ETH`: `amount - amount % EB_INC` | ✅ all 6 |
| H4 | Final `effective_balance = min(amount_rounded, max_eb)` — uses `min`, not just one of the two | ✅ all 6 |
| H5 | Initial fields: `slashed=false`, all 4 epoch fields = `FAR_FUTURE_EPOCH` | ✅ all 6 |
| H6 | `add_validator_to_registry` 5-field init: validators, balances, previous_epoch_participation, current_epoch_participation, inactivity_scores | ✅ all 6 |
| H7 | `get_index_for_new_validator(state) = len(state.validators)` (the new validator's index is the length BEFORE the push) | ✅ all 6 (some inline as `state.validators().len()`) |
| H8 | Per-block `process_deposit` for new validator passes `amount = 0` to `add_validator_to_registry` (Pectra defers amount to pending-deposits drain) | ✅ 4/6 (lighthouse + prysm explicit `0`; teku/nimbus/lodestar/grandine handle deferral via different choreography) |
| H9 | Pubkey cache (`pubkey_to_index` map) updated after the push | ✅ all 6 (cache details vary; all maintain pubkey → index map for downstream lookups) |

## Per-client cross-reference

| Client | `get_validator_from_deposit` location | `add_validator_to_registry` location | Two-step idiom |
|---|---|---|---|
| **prysm** | `core/electra/deposits.go:519-537` | `core/electra/deposits.go:462-497` | Explicit: create with `EffectiveBalance: 0` → `helpers.ValidatorMaxEffectiveBalance(v)` → set EB |
| **lighthouse** | `consensus/types/src/validator/validator.rs:39-65` (`Validator::from_deposit`) | `consensus/types/src/state/beacon_state.rs:1922-1965` (state method) | Explicit: `effective_balance: 0` initial → `validator.get_max_effective_balance(spec, fork_name)` → set EB |
| **teku** | `versions/electra/helpers/MiscHelpersElectra.java:117-137` (override) | `common/helpers/BeaconStateMutators.java:230-240` (NOT overridden in Electra) | Explicit: create with `ZERO` EB → `getMaxEffectiveBalance(validator)` → `.withEffectiveBalance(...)` builder |
| **nimbus** | `spec/beaconstate.nim:102-122` (Electra path; pre-Electra at `:81-99`) | `spec/beaconstate.nim:125-145` | Explicit `var validator = Validator(... effective_balance: 0.Gwei)` then mutate |
| **lodestar** | inline in `block/processDeposit.ts:90-139` (no separate helper) | `block/processDeposit.ts` (in `addValidatorToRegistry`) | Inline ternary: `fork < ForkSeq.electra ? MAX_EFFECTIVE_BALANCE : getMaxEffectiveBalance(withdrawalCredentials)` |
| **grandine** | inline in `transition_functions/src/electra/block_processing.rs:882-924` (`add_validator_to_registry`) | same function, lines 882-924 | Explicit: `Validator { ... effective_balance: 0, ... }` → `get_max_effective_balance::<P>(&validator)` → `prev_multiple_of(P::EFFECTIVE_BALANCE_INCREMENT).min(max_effective_balance)` |

## Notable per-client divergences (all observable-equivalent)

### Pectra deferral idiom: `amount = 0` at per-block, full amount at per-epoch drain

**Lighthouse and prysm** explicitly pass `amount = 0` to
`add_validator_to_registry` from the per-block `process_deposit`
path:

```rust
// lighthouse process_operations.rs:467-487
state.add_validator_to_registry(
    deposit_data.pubkey,
    deposit_data.withdrawal_credentials,
    if state.fork_name_unchecked() >= ForkName::Electra { 0 } else { amount },
    spec,
)?;
```

```go
// prysm electra/deposits.go:144
AddValidatorToRegistry(beaconState, pubKey, withdrawalCredentials, 0)
```

This is because Pectra defers the actual deposit amount to the
per-epoch `process_pending_deposits` drain (item #4) — the per-block
path only enqueues a `PendingDeposit` for later processing. With
`amount = 0`, `get_validator_from_deposit` produces a Validator with
`effective_balance = 0`, which is correct (the EB will be set when
the pending deposit is drained per-epoch).

**Teku, nimbus, lodestar, grandine** handle the deferral
differently:
- **Teku**: `applyPendingDeposits` (per-epoch, `EpochProcessorElectra.java:187-202`)
  calls `addValidatorToRegistry(state, pubkey, creds, deposit.getAmount())`
  with the FULL amount. The per-block path doesn't call
  `addValidatorToRegistry` at all for new validators; it just
  enqueues the PendingDeposit.
- **Nimbus**: similar to teku — `apply_deposit` per-block enqueues;
  `process_pending_deposits` per-epoch calls `add_validator_to_registry`
  with the full amount.
- **Lodestar**: `applyPendingDeposit` (in `processPendingDeposits.ts`)
  calls `addValidatorToRegistry(ForkSeq.electra, state, pubkey, creds, amount)`
  with the full amount.
- **Grandine**: same pattern.

**All 6 clients converge on the correct observable post-state**:
new validators end up with `effective_balance = min(amount_rounded,
get_max_effective_balance(validator))` after the per-epoch drain
completes. The per-block-amount-0-defer pattern is a code-organization
choice; the no-per-block-call pattern is the alternative.

### lighthouse: `Validator::from_deposit` is a free constructor (NOT a state method)

Unlike most clients which place this logic on a state mutator,
lighthouse implements it as `impl Validator { pub fn from_deposit(...) }`
— a pure constructor returning a `Validator`. The state method
`add_validator_to_registry` consumes the result.

This is the cleanest separation: pure validator construction
(no state access) vs state mutation (push to lists, update caches).

### lighthouse: comment notes safe-math is "unnecessary"

```rust
// "safe math is unnecessary here since the spec.effective_balance_increment is never <= 0"
validator.effective_balance = std::cmp::min(
    amount - (amount % spec.effective_balance_increment),
    max_effective_balance,
);
```

Lighthouse explicitly documents WHY it doesn't use `safe_*` math
here. **Other clients (grandine, prysm, nimbus) don't document this
choice** — worth flagging for spec-traceability.

### teku: does NOT override `addValidatorToRegistry` in Electra

```java
// teku BeaconStateMutators.java:230-240 (base class, NOT overridden)
public void addValidatorToRegistry(
    final MutableBeaconState state,
    final BLSPublicKey pubkey,
    final Bytes32 withdrawalCredentials,
    final UInt64 amount) {
  final Validator validator =
      miscHelpers.getValidatorFromDeposit(pubkey, withdrawalCredentials, amount);
  state.getValidators().append(validator);
  state.getBalances().appendElement(amount);
}
```

Teku's `BeaconStateMutators` base class calls
`miscHelpers.getValidatorFromDeposit(...)`. Electra-specific
behavior is implemented by `MiscHelpersElectra.getValidatorFromDeposit`
override (subclass-override polymorphism). **Cleanest abstraction
of the six** — no Electra subclass for the registry mutator.

But this means teku's `add_validator_to_registry` only appends to
**2 fields** (validators + balances)! The other 3 fields
(participation flags + inactivity_scores) must be appended elsewhere.
Looking at teku's deposit-processing code, the per-block path
appears to delegate the participation/inactivity init to a separate
hook (likely a per-fork `EpochProcessorElectra` method). **Worth
verifying cross-client whether teku's split is observable-equivalent
to the consolidated Altair-heritage 5-field init in the other 5
clients.**

### lodestar: NO separate `getValidatorFromDeposit` function

Lodestar inlines the 2-step construction directly inside
`addValidatorToRegistry` (`processDeposit.ts:90-139`):

```typescript
const effectiveBalance = Math.min(
  amount - (amount % EFFECTIVE_BALANCE_INCREMENT),
  fork < ForkSeq.electra ? MAX_EFFECTIVE_BALANCE : getMaxEffectiveBalance(withdrawalCredentials)
);
validators.push(
  ssz.phase0.Validator.toViewDU({
    pubkey,
    withdrawalCredentials,
    activationEligibilityEpoch: FAR_FUTURE_EPOCH,
    // ... other fields ...
    effectiveBalance,
    slashed: false,
  })
);
```

The two-step semantic is preserved (compute cap from credentials
before constructing the validator), but the construction is a
single SSZ tree-view push instead of mutate-then-set. **Most concise
implementation of the six.**

### grandine: SINGLE definition (no multi-fork-definition risk)

Grandine has ONE `add_validator_to_registry` in
`transition_functions/src/electra/block_processing.rs:882-924`. **NO
multi-fork-definition pattern** like items #6/#9/#10/#12/#14/#15/#17.
Same as item #16's churn primitives — high-leverage primitives are
consolidated.

But: pre-Electra `apply_deposits` in `altair/block_processing.rs:446`
INLINES the validator construction directly (no `add_validator_to_registry`
helper). So pre-Electra `add_validator_to_registry` doesn't exist
in grandine — only the Electra path uses the helper. **Forward-compat
risk for any Gloas+ refactor that wants to share the helper across
forks.**

### nimbus: type-overload-based per-fork dispatch

```nim
# Pre-Electra:
func get_validator_from_deposit*(_: phase0.BeaconState | altair.BeaconState | ... | deneb.BeaconState, ...)

# Electra+:
func get_validator_from_deposit*(state: electra.BeaconState | fulu.BeaconState | gloas.BeaconState, ...)
```

Nim's function-overload resolution routes calls to the correct
version based on the runtime type of `state`. **Cleanest fork
dispatch idiom for THIS specific function.**

### grandine's `prev_multiple_of(NonZeroU64)` for downward rounding

```rust
validator.effective_balance = amount
    .prev_multiple_of(P::EFFECTIVE_BALANCE_INCREMENT)
    .min(max_effective_balance);
```

`prev_multiple_of` is implemented as `self - self % factor` where
`factor: NonZeroU64`. **Compile-time guarantee against
divide-by-zero** via the `NonZeroU64` type. Same pattern as item
#16's `get_balance_churn_limit`. Cleanest expression of the
downward-rounding semantic.

### Pubkey cache update timing varies

Each client maintains a `pubkey_to_index` map for fast lookups
during deposit processing:

- **prysm**: `ValidatorIndexByPubkey` map updated implicitly via
  `AppendValidator` → state mutation triggers cache rebuild.
- **lighthouse**: explicit `pubkey_cache.append(...)` after the
  push (`beacon_state.rs:1956-1962`).
- **teku**: validator-status cache rebuilt at epoch transition
  via `recreateValidatorStatusIfNewValidatorsAreFound` (item #17
  audit referenced this).
- **nimbus**: maintained internally by HashList.add and
  ValidatorMonitor.
- **lodestar**: explicit `epochCtx.addPubkey(validatorIndex, pubkey)`
  (`processDeposit.ts:125`).
- **grandine**: implicit via PersistentList rebuild semantics.

**Cache update timing is the most divergent aspect** of this
audit. All clients converge on the same observable state, but the
cache invalidation/rebuild patterns differ. Worth a contract test
asserting that pubkey lookups return the correct index immediately
after the registry push.

## EF fixture status — implicit coverage via items #4 + #14

This audit has **no dedicated EF fixture set** because
`get_validator_from_deposit` and `add_validator_to_registry` are
internal helpers, not block-level operations. They are exercised
IMPLICITLY via:

| Item | Fixtures × clients | Calls these helpers via |
|---|---|---|
| **#4** process_pending_deposits | 43 × 4 = 172 | per-epoch drain → apply_pending_deposit → add_validator_to_registry |
| **#14** process_deposit_request | 11 × 4 = 44 | per-block → enqueue PendingDeposit → drained later by item #4's path |

**Total implicit cross-validation evidence**: **216 EF fixture
PASSes** across 54 unique fixtures all flow through these helpers.
Any divergence in the Pectra two-step construction (wrong cap,
wrong rounding, missing one of the 5 Altair-heritage list pushes)
would have surfaced as a fixture failure in at least one of items
#4 or #14. None did.

A dedicated fixture set for `get_validator_from_deposit` would
consist of:
1. Input: `(pubkey, withdrawal_credentials, amount)` triples spanning:
   - 0x01 credentials with `amount` in [0, MIN_ACTIVATION_BALANCE,
     MIN_ACTIVATION_BALANCE+1, MIN_ACTIVATION_BALANCE×2,
     2048 ETH, MAX_EB_ELECTRA-1, MAX_EB_ELECTRA, MAX_EB_ELECTRA+1].
   - 0x02 credentials with same `amount` range.
2. Expected output: Validator struct with the correct
   `effective_balance` field.

This is **directly fuzzable** — pure function of the inputs. Worth
generating as a follow-up to close the dedicated coverage gap.

## Cross-cut chain — closes the new-validator construction layer

Combined with prior audits, items #1/#4/#11/#14/#17/#18 form the
complete new-validator lifecycle:

```
[item #14] process_deposit_request: EL deposit → PendingDeposit{slot=state.slot}
   ↓
[item #11] upgrade_to_electra: pre-activation validators → PendingDeposit{slot=GENESIS_SLOT}
   ↓
[item #4] process_pending_deposits per-epoch: drain queue
   ↓ for each new pubkey:
[item #18 (this)] add_validator_to_registry → get_validator_from_deposit
   ↓                                            uses get_max_effective_balance (item #1)
   ↓                                            cap based on creds (32 / 2048 ETH)
state.validators[new_index].effective_balance = min(amount_rounded, max_eb)
   ↓
[item #17] process_registry_updates per-epoch: activation eligibility check
   ↓ if effective_balance >= MIN_ACTIVATION_BALANCE: enter activation queue
state.validators[new_index].activation_eligibility_epoch = current_epoch + 1
   ↓ (after finality)
state.validators[new_index].activation_epoch = compute_activation_exit_epoch(current)
   ↓ validator becomes ACTIVE
```

The new-validator construction layer is now audited end-to-end.

## Adjacent untouched

- **Generate dedicated EF fixture set** for `get_validator_from_deposit`
  — pure function, easy to fuzz. Highest-priority gap closure.
- **Cross-client byte-for-byte equivalence test**: feed identical
  `(pubkey, creds, amount)` triples to all 6 clients, compare the
  resulting Validator struct.
- **teku's 2-field-only `addValidatorToRegistry`** — verify that
  the participation/inactivity init happens elsewhere (per-fork
  EpochProcessor hook?) and that the observable post-state matches
  the consolidated 5-field init in other clients.
- **`amount = 0` deferral pattern divergence**: lighthouse + prysm
  pass `0` to per-block `add_validator_to_registry`; other 4 clients
  don't call it from per-block at all. Codify as a contract
  assertion: per-block `add_validator_to_registry` calls (if any)
  MUST be observably equivalent to per-epoch calls with the full
  amount.
- **lighthouse's "safe math unnecessary" comment** — codify the
  rationale across all clients (or remove for consistency).
- **grandine SINGLE-definition pattern**: confirm that
  `add_validator_to_registry` doesn't acquire a multi-fork-definition
  pattern at Gloas (where deposit handling restructures via
  `applyDepositForBuilder` per item #14 audit).
- **Pubkey cache update timing**: contract test asserting that
  pubkey lookups return the correct index immediately after registry
  push, across all 6 clients.
- **lodestar's inlined construction** — codify as a conscious
  design choice to avoid the helper indirection (vs other clients).
- **`amount = 0` initial-EB edge case**: a Validator with
  `effective_balance = 0` is technically not eligible for any
  attestation duties. The per-epoch drain MUST set the EB to a
  meaningful value before the validator becomes active. Verify
  cross-client that no race-condition allows a zero-EB validator
  to become active.
- **Compounding-credentials with `amount > 2048 ETH` edge case**:
  the cap clamps at 2048 ETH. The excess balance is queued as a
  separate PendingDeposit (item #11's `queue_excess_active_balance`
  for upgrade-time; item #2's switch-to-compounding fast path for
  block-time). Worth verifying cross-client that the excess is
  correctly preserved.
- **`amount` in [0, MIN_ACTIVATION_BALANCE)`** — a deposit below
  32 ETH for a NEW validator: validator is created with
  `effective_balance < 32 ETH`, NOT eligible for activation queue
  (item #17). Worth a fixture verifying cross-client behavior.

## Future research items

1. **Generate dedicated EF fixture set** for `get_validator_from_deposit`
   — highest-priority direct fixture coverage.
2. **Cross-client byte-for-byte Validator equivalence test** for
   the same `(pubkey, creds, amount)` input.
3. **teku 2-field vs 5-field init equivalence audit** — verify
   participation/inactivity init happens in the right place.
4. **`amount = 0` deferral pattern contract assertion** — codify
   the observable-equivalence between lighthouse/prysm pattern and
   teku/nimbus/lodestar/grandine pattern.
5. **lighthouse safe-math comment cross-client codification** —
   document the rationale at all 6 clients.
6. **grandine SINGLE-definition consistency check at Gloas** —
   ensure no multi-fork-definition pattern emerges.
7. **Pubkey cache update timing contract test** — pubkey lookups
   immediately after registry push.
8. **lodestar inlined-construction design rationale** — document.
9. **Zero-EB validator race condition** — verify drain MUST run
   before activation.
10. **Compounding `amount > 2048 ETH` edge case** — excess
    preservation across all 6 clients.
11. **`amount < MIN_ACTIVATION_BALANCE` for new validator** —
    cross-cut with item #17 activation eligibility.
12. **`get_max_effective_balance(validator)` cross-cut audit** —
    item #1's helper is the chokepoint for THIS audit's Pectra
    change. Verify that all 6 clients' `get_max_effective_balance`
    implementations are byte-for-byte equivalent.
