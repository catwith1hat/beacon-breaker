# Item #21 — `queue_excess_active_balance` (Pectra-NEW placeholder-PendingDeposit producer)

**Status:** no-divergence-pending-source-review — audited 2026-05-02.
The **producer of placeholder PendingDeposits** (slot=GENESIS_SLOT,
signature=G2_POINT_AT_INFINITY). Cross-cuts items #11 (upgrade-time
early-adopter loop), #2 (switch-to-compounding fast path), and #20
(`apply_pending_deposit` consumes these placeholders; item #4's drain
checks `slot == GENESIS_SLOT` to skip signature verification).

## Why this item

When a validator's balance exceeds `MIN_ACTIVATION_BALANCE = 32 ETH`
and the validator is being moved into the compounding (0x02) regime,
the EXCESS balance must be re-queued through the deposit pipeline so
it gets churn-paced like any normal deposit. This is what
`queue_excess_active_balance` does:

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
- **`signature = G2_POINT_AT_INFINITY`** (= `0xc0` followed by 95
  zeroes — the canonical compressed BLS point at infinity): NOT a
  real signature, will FAIL BLS verification if attempted.
- **`slot = GENESIS_SLOT`** (= 0): a marker so item #4's
  `process_pending_deposits` drain knows to skip signature
  verification for this entry. Real DepositRequests (item #14) use
  `slot = state.slot` (= current slot, never 0 post-genesis).

This is the COMPLEMENT of item #20's `apply_pending_deposit`:
- **Producer** (this item): writes placeholders to `pending_deposits`.
- **Consumer** (item #20 + item #4's drain): recognizes placeholders
  by `slot == GENESIS_SLOT` and skips signature verification.

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | Strict `>` threshold: `balance > MIN_ACTIVATION_BALANCE` (NOT `>=`) | ✅ all 6 |
| H2 | Balance reset to `MIN_ACTIVATION_BALANCE` (NOT 0) | ✅ all 6 |
| H3 | `excess_balance = balance - MIN_ACTIVATION_BALANCE` (no rounding here — done at apply time) | ✅ all 6 |
| H4 | PendingDeposit pubkey + withdrawal_credentials sourced from EXISTING validator | ✅ all 6 |
| H5 | PendingDeposit `signature = G2_POINT_AT_INFINITY` (canonical 0xc0-prefixed 96-byte point) | ✅ all 6 |
| H6 | PendingDeposit `slot = GENESIS_SLOT` (= 0) — placeholder marker | ✅ all 6 |
| H7 | Two callers: item #11 (upgrade early-adopter loop) + item #2 (switch-to-compounding fast path) | ✅ all 6 |
| H8 | Single function definition (no multi-fork-definition risk like items #6/#9/#10/#12/#14/#15/#17/#19) | ✅ all 6 |

## Per-client cross-reference

| Client | Function location | Signature placeholder | Slot marker |
|---|---|---|---|
| **prysm** | `core/electra/validator.go:56-81` (`QueueExcessActiveBalance`) | `common.InfiniteSignature[:]` = `[96]byte{0xC0}` then zeros | `params.BeaconConfig().GenesisSlot` (= 0) |
| **lighthouse** | `consensus/types/src/state/beacon_state.rs:2667-2689` (`queue_excess_active_balance` state method) | `Signature::infinity()?.into()` (deserializes `INFINITY_SIGNATURE` constant) | `spec.genesis_slot` |
| **teku** | `versions/electra/helpers/BeaconStateMutatorsElectra.java:195-217` (`queueExcessActiveBalance`) | `BLSSignature.infinity()` = `BLSSignature.fromBytesCompressed(INFINITY_BYTES)` (96 bytes 0xc0-prefixed) | `SpecConfig.GENESIS_SLOT` |
| **nimbus** | `spec/beaconstate.nim:1516-1531` (`func queue_excess_active_balance`) | `ValidatorSig.infinity` (sets `blob[0] = 0xC0`) | `GENESIS_SLOT` |
| **lodestar** | `state-transition/src/util/electra.ts:36-57` (`queueExcessActiveBalance`) | `G2_POINT_AT_INFINITY` constant = `Uint8Array("c0..." + 190 hex chars)` | `GENESIS_SLOT` |
| **grandine** | `helper_functions/src/mutators.rs:149-175` (`queue_excess_active_balance`) | `SignatureBytes::empty()` — sets `bytes[0] = 0xc0` (CORRECTED: this IS the canonical infinity point) | `GENESIS_SLOT` |

## Notable per-client divergences (all observable-equivalent)

### Correction: grandine `SignatureBytes::empty()` IS the canonical G2_POINT_AT_INFINITY

**Items #11 and #18 audits incorrectly characterized** grandine's
`SignatureBytes::empty()` as "differing from explicit G2_POINT_AT_INFINITY."
This audit reveals the actual implementation:

```rust
// grandine bls/bls-core/src/traits/signature_bytes.rs:68-72
fn empty() -> Self {
    let mut bytes = Self::zero();
    bytes.as_mut()[0] = 0xc0;     // ← sets the infinity flag bit
    bytes
}
```

The trait method `empty()` is named misleadingly but produces the
**canonical 0xc0-prefixed 96-byte infinity point**, identical to:
- prysm's `[96]byte{0xC0, 0, 0, ..., 0}`
- lighthouse's `Signature::infinity()`
- teku's `BLSSignature.infinity()` returning compressed `INFINITY_BYTES`
- nimbus's `ValidatorSig.infinity`
- lodestar's `G2_POINT_AT_INFINITY` Uint8Array

**All 6 clients produce byte-identical placeholder signatures.** No
divergence. The previously-flagged "strict-spec compliance concern"
in items #11 and #18 is RETRACTED.

### Single definition across all 6 clients (no multi-fork risk)

Unlike items #6/#9/#10/#12/#14/#15/#17/#19 which have multi-fork
definitions in grandine, **`queue_excess_active_balance` has ONE
definition per client**. This makes sense because:
- The function is Pectra-NEW (no Phase0/Altair/etc. predecessor).
- It's only called from Pectra-NEW code paths (item #11 upgrade,
  item #2 switch path).
- Future forks (Fulu, Gloas) inherit the Pectra implementation.

Same single-definition pattern as items #16 (churn primitives) and
#18 (add_validator_to_registry).

### Nimbus `static(MIN_ACTIVATION_BALANCE.Gwei)` compile-time constant

```nim
if balance > static(MIN_ACTIVATION_BALANCE.Gwei):
```

Nimbus uses `static(...)` to force the constant to be evaluated at
compile time, allowing the compiler to inline the comparison
constant. Performance optimization. Other clients use the constant
directly (with implicit compile-time folding by their respective
toolchains).

### Teku schema-driven 5-field PendingDeposit creation

```java
schemaDefinitionsElectra
    .getPendingDepositSchema()
    .create(
        new SszPublicKey(validator.getPublicKey()),
        SszBytes32.of(validator.getWithdrawalCredentials()),
        SszUInt64.of(excessBalance),
        new SszSignature(BLSSignature.infinity()),
        SszUInt64.of(SpecConfig.GENESIS_SLOT));
```

Most verbose construction (5 explicit SSZ wrapper types). Same idiom
as item #14's deposit_request audit. Compile-time field-count
enforcement.

### Lodestar SSZ tree mutation via `.set()` not direct assignment

```typescript
state.balances.set(index, MIN_ACTIVATION_BALANCE);
```

Lodestar uses `.set()` on the SSZ ViewDU collection, NOT direct
array indexing. This ensures the underlying SSZ Merkle tree is
properly updated (otherwise the next `hashTreeRoot()` call would
return a stale cached root). Other clients use direct mutable
indexing or copy-on-write semantics.

### Lighthouse uses milhouse `pop_front` and `push` for List operations

```rust
self.pending_deposits_mut()?.push(PendingDeposit { ... })?;
```

Lighthouse's `milhouse::List::push` returns `Result<(), MilhouseError>`
which is propagated via `?` and mapped to `BeaconStateError::MilhouseError`.
Failure mode: the list is at PENDING_DEPOSITS_LIMIT = 2^27 = ~134M
entries. F-tier today (no realistic mainnet scenario hits this), but
defensive.

### Caller chain symmetry

All 6 clients correctly route the two callers:

**Item #11 (upgrade-time early-adopter loop)**:
- prysm: `core/electra/upgrade.go:311-315`
- lighthouse: `state_processing/src/upgrade/electra.rs:86`
- teku: `ElectraStateUpgrade.java:117`
- nimbus: `beaconstate.nim:2691` (in `upgrade_to_next`)
- lodestar: `slot/upgradeStateToElectra.ts:116`
- grandine: `helper_functions/src/fork.rs` (in Pectra fork upgrade)

**Item #2 (switch-to-compounding fast path)**:
- prysm: `core/electra/validator.go:35` (`SwitchToCompoundingValidator`)
- lighthouse: `state_processing/src/per_block_processing/process_operations.rs:698` via `switch_to_compounding_validator`
- teku: `BeaconStateMutatorsElectra.java:186` (`switchToCompoundingValidator`)
- nimbus: `beaconstate.nim:1539` (in `switch_to_compounding_validator`)
- lodestar: `state-transition/src/util/electra.ts:33` (`switchToCompoundingValidator`)
- grandine: `helper_functions/src/mutators.rs:144` (in `switch_to_compounding_validator`)

## EF fixture status — implicit coverage via items #2 + #11 fixtures

This audit has **no dedicated EF fixture set** because
`queue_excess_active_balance` is an internal helper. It is exercised
IMPLICITLY via:

| Item | Fixtures × clients | Calls this helper |
|---|---|---|
| **#2** consolidation_request (switch-to-compounding) | 10 × 4 = 40 | switch path → switch_to_compounding_validator → queue_excess_active_balance |
| **#11** upgrade_to_electra (early-adopter loop) | 22 EF fork fixtures | upgrade → for each 0x02 validator with balance > MIN: queue_excess_active_balance (NOT yet wired in BeaconBreaker harness) |

**Total implicit cross-validation evidence**: 40 explicit PASSes
through item #2's fixtures (switch-to-compounding cases). Item #11's
22 fork fixtures would add another 88 implicit PASSes once the fork
category is wired in BeaconBreaker's harness.

A dedicated fixture set for `queue_excess_active_balance` would
consist of:
1. Pre-state with single validator at known balance.
2. Call the function.
3. Expected post-state: balance = MIN_ACTIVATION_BALANCE (if balance
   was > MIN); pending_deposits has new placeholder entry with the
   excess; OR no-op if balance ≤ MIN.

Pure function (state, index → state'); directly fuzzable.

## Cross-cut chain — closes the placeholder PendingDeposit producer/consumer pair

This audit closes the **placeholder PendingDeposit lifecycle**:

```
[item #11 upgrade] early-adopter loop:
    for each pre-existing 0x02 validator with balance > MIN_ACTIVATION_BALANCE:
        ↓
[item #21 (this) queue_excess_active_balance]:
    state.balances[idx] = MIN_ACTIVATION_BALANCE
    state.pending_deposits.append(PendingDeposit{
        pubkey, creds, excess_amount,
        signature=G2_POINT_AT_INFINITY,
        slot=GENESIS_SLOT
    })
        ↓
[item #2 switch path] consolidation_request switch-to-compounding:
    same call from process_operations
        ↓ (next epoch)
[item #4 process_pending_deposits drain]:
    sees PendingDeposit with slot=GENESIS_SLOT
    SKIPS signature verification (signature is G2_POINT_AT_INFINITY,
        would fail BLS verify; the slot=GENESIS_SLOT marker is the
        skip condition)
        ↓
[item #20 apply_pending_deposit]:
    pubkey is EXISTING (the validator was in registry from
        upgrade-time or pre-switch)
    → existing-validator path: increase_balance(state, validator_index, excess_amount)
        ↓
balance restored: MIN_ACTIVATION_BALANCE + excess = original balance
(but now in the compounding regime, with churn-paced re-application)
```

The placeholder lifecycle is now audited end-to-end.

## Adjacent untouched

- **Generate dedicated EF fixture set** for `queue_excess_active_balance`
  — pure-function cross-client equivalence test.
- **Cross-client signature-placeholder byte equivalence test**: feed
  the same input to all 6 clients, compare the resulting PendingDeposit
  signature field byte-for-byte. The "all six produce 0xc0 + 95
  zeros" claim should be verified at the byte level.
- **Item #11 + #18 audit corrections**: previously characterized
  grandine `SignatureBytes::empty()` as "differing from G2_POINT_AT_INFINITY"
  — this is INCORRECT (it produces the canonical 0xc0-prefixed
  point). Update items #11 and #18 documentation. **Note: the
  observable behavior was correctly characterized as "no divergence"
  in those items; only the per-client style commentary needs
  correction.**
- **Slot=GENESIS_SLOT marker semantics** — the marker is what item
  #4's drain uses to skip signature verification. A real DepositRequest
  produced by item #14 uses `slot=state.slot` which is never 0
  post-genesis. Cross-cut: any client that accidentally allowed a
  PendingDeposit with `slot=0` to bypass the placeholder check
  would silently bypass all deposit signature verification. **Audit
  closure: confirm item #4's drain uses strict `slot == GENESIS_SLOT`
  comparison (not `slot < some_threshold`).**
- **Top-up vs new-validator routing for placeholders**: item #20's
  apply_pending_deposit dispatches by pubkey existence. Placeholders
  produced by THIS function are for EXISTING validators (pubkey is
  in registry from upgrade or pre-switch), so they always take the
  top-up path (`increase_balance`). Verify cross-client.
- **Excess rounding semantics**: the excess is `balance -
  MIN_ACTIVATION_BALANCE` raw. NO downward-rounding to
  EFFECTIVE_BALANCE_INCREMENT is done here. The downward-rounding
  happens later in item #18's `get_validator_from_deposit` (for
  new validators) or implicitly via the `effective_balance_updates`
  (item #1) for existing validators. Stateful fixture: validator
  with balance = 100.5 ETH → queue 68.5 ETH excess → drain → top-up
  100.5 ETH again → eb-updates rounds to 100 ETH. Verify.
- **Multi-call edge case**: item #11 + item #2 could in principle
  both call this function for the same validator in the same epoch
  (upgrade time). Since item #11 is upgrade-time and item #2 is
  block-time, this can't happen on the same epoch (item #11 runs
  AT the upgrade slot; item #2 runs in subsequent blocks).
  Theoretical concern: a validator with balance > MIN at upgrade
  AND switching to compounding via consolidation in the next block
  → upgrade queues excess → block-time switch queues "excess" of
  remaining balance MIN_ACTIVATION_BALANCE which is NOT > MIN, so
  the switch path no-ops. Correct behavior. Worth a stateful fixture.

## Future research items

1. **Generate dedicated EF fixture set** for `queue_excess_active_balance`
   — pure-function, easy to fuzz.
2. **Cross-client signature-placeholder byte equivalence test** —
   verify all 6 produce identical 96 bytes.
3. **Update items #11 and #18 documentation** — retract the
   incorrect "grandine differs from G2_POINT_AT_INFINITY" note
   based on this audit's finding (grandine `SignatureBytes::empty()`
   sets `bytes[0] = 0xc0` to produce the canonical point).
4. **Audit closure: item #4's `slot == GENESIS_SLOT` placeholder
   skip** — strict equality, not threshold.
5. **Top-up vs new-validator routing for placeholders** — verify
   placeholders always take the top-up path.
6. **Excess rounding semantics** — balance with sub-1-ETH dust →
   queue → top-up → eb-updates → rounded.
7. **Multi-call edge case stateful fixture** — upgrade + switch in
   adjacent epochs.
8. **PENDING_DEPOSITS_LIMIT (2^27) capacity stress** — adversarial
   scenario where many validators queue excess simultaneously
   (impossible at upgrade time bounded by validator count).
9. **`switch_to_compounding_validator` standalone audit** — the
   function that calls THIS one from item #2's fast path. Sets
   `withdrawal_credentials[0] = COMPOUNDING_WITHDRAWAL_PREFIX_BYTE`
   then queues. Worth a small audit.
10. **Cross-cut with item #20 SILENT DROP**: if a placeholder
    deposit somehow took the new-validator path (impossible per H4
    invariant, but adversarial), item #20's signature verify would
    fail (G2_POINT_AT_INFINITY is not a valid signature for any
    message), and the deposit would SILENTLY DROP. Worth verifying
    cross-client that this defense-in-depth holds.
