# Item #20 — `apply_pending_deposit` + `is_valid_deposit_signature` (Pectra-NEW per-deposit application + EIP-7044-style signature pinning)

**Status:** no-divergence-pending-source-review — audited 2026-05-02.
The **per-deposit application logic** at item #4's
`process_pending_deposits` drain. Pectra-NEW. Cross-cuts items #4
(drain), #18 (`add_validator_to_registry` for new-validator path),
and Track F (BLS — first cross-client BLS-library audit in the
corpus).

## Why this item

`apply_pending_deposit` is the **inner per-deposit logic** that
item #4's `process_pending_deposits` drain calls for each pending
deposit. It dispatches between two paths:

```python
def apply_pending_deposit(state: BeaconState, deposit: PendingDeposit) -> None:
    """Applies ``deposit`` to the ``state``."""
    validator_pubkeys = [v.pubkey for v in state.validators]
    if deposit.pubkey not in validator_pubkeys:
        # NEW VALIDATOR PATH: verify signature, then add_validator_to_registry
        if is_valid_deposit_signature(
            deposit.pubkey,
            deposit.withdrawal_credentials,
            deposit.amount,
            deposit.signature,
        ):
            add_validator_to_registry(
                state, deposit.pubkey, deposit.withdrawal_credentials, deposit.amount
            )
        # CRITICAL: failed signature → SILENTLY DROP (deposit consumed but not applied)
    else:
        # EXISTING VALIDATOR PATH: top-up
        validator_index = ValidatorIndex(validator_pubkeys.index(deposit.pubkey))
        increase_balance(state, validator_index, deposit.amount)


def is_valid_deposit_signature(
    pubkey: BLSPubkey, withdrawal_credentials: Bytes32, amount: uint64, signature: BLSSignature
) -> bool:
    deposit_message = DepositMessage(
        pubkey=pubkey,
        withdrawal_credentials=withdrawal_credentials,
        amount=amount,
    )
    # Fork-agnostic domain since deposits are valid across forks
    domain = compute_domain(DOMAIN_DEPOSIT)   # NO fork_version arg → GENESIS_FORK_VERSION
    signing_root = compute_signing_root(deposit_message, domain)
    return bls.Verify(pubkey, signing_root, signature)
```

Two critical Pectra-divergence-prone bits:

1. **SILENT DROP on failed signature**: a deposit with an invalid
   signature is **consumed from the queue** (item #4's drain advances
   the cursor) but **NOT applied** — no validator is added, no
   balance is increased, no error is returned. This is structurally
   important: a malicious EL could send an invalid-sig deposit to
   waste a queue slot. The CL gracefully drops it.

2. **GENESIS_FORK_VERSION fork-version pin**: the deposit signature
   is verified against `compute_domain(DOMAIN_DEPOSIT)` which
   defaults to `GENESIS_FORK_VERSION` (NOT current fork). This is
   the same EIP-7044-style pin as voluntary exits (item #6), but for
   deposits — deposits signed at any point in chain history remain
   valid because the signing domain is fork-pinned to genesis.

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | Two-branch dispatch on pubkey existence (cached pubkey→index map for O(1)) | ✅ all 6 |
| H2 | New-validator path: signature verify → if valid: `add_validator_to_registry` | ✅ all 6 |
| H3 | Existing-validator path: `increase_balance(state, validator_index, deposit.amount)` (top-up) | ✅ all 6 |
| H4 | **SILENT DROP on failed signature**: no error, deposit just doesn't apply | ✅ all 6 |
| H5 | DepositMessage has 3 fields (pubkey, withdrawal_credentials, amount) — NO signature field | ✅ all 6 |
| H6 | `compute_domain(DOMAIN_DEPOSIT)` uses **GENESIS_FORK_VERSION** (NOT current fork) | ✅ all 6 |
| H7 | Single `bls.Verify(pubkey, signing_root, signature)` call (NOT aggregate) | ✅ all 6 |
| H8 | DOMAIN_DEPOSIT = `0x03000000` (constant across all 6 clients) | ✅ all 6 |
| H9 | Pubkey decompression failure → return `false` (NOT panic/error) | ✅ all 6 (with implementation-style variations) |

## Per-client cross-reference

| Client | `apply_pending_deposit` location | `is_valid_deposit_signature` location | BLS library |
|---|---|---|---|
| **prysm** | `core/electra/deposits.go:437-460` (`ApplyPendingDeposit`) | `core/electra/deposits.go:168-179` (`IsValidDepositSignature`) | **BLST** (with herumi fallback during init) |
| **lighthouse** | `state_processing/src/per_epoch_processing/single_pass.rs:383-406` (INLINED, NOT a separate function) | `state_processing/src/per_block_processing/verify_deposit.rs:18-28` (`is_valid_deposit_signature`) | **blst** (supranational) via `bls` crate wrapper |
| **teku** | `versions/electra/.../EpochProcessorElectra.java:187-202` (`applyPendingDeposit` override) | `common/helpers/MiscHelpers.java:410-423` (`isValidDepositSignature`) | `tech.pegasys.teku.bls` (`BLSSignatureVerifier` DI interface) |
| **nimbus** | `state_transition_epoch.nim:1185-1204` (`apply_pending_deposit`) | `signatures.nim:209-216` public + `:200-207` internal (`verify_deposit_signature`) | **blscurve** (BLST Nim wrapper) |
| **lodestar** | `epoch/processPendingDeposits.ts:110-139` (`applyPendingDeposit`) | `block/processDeposit.ts:141-166` (`isValidDepositSignature`) | **@chainsafe/blst** (BLST TypeScript wrapper) |
| **grandine** | `transition_functions/src/electra/epoch_processing.rs:319-344` (`apply_pending_deposit`) | `transition_functions/src/electra/epoch_processing.rs:346-369` (`is_valid_deposit_signature`) | **bls-blst** (BLST default; `bls-zkcrypto` alternative via feature flag) |

**All 6 clients use BLST or BLST-based wrappers** for deposit signature verification. This is the **first cross-client BLS-library audit** in the corpus — no library-family divergence (e.g., gnark vs BLST) at this surface.

## Notable per-client divergences (all observable-equivalent)

### lighthouse: NOT a separate function — inlined in single_pass.rs

Lighthouse does NOT expose a named `apply_pending_deposit()`
function. The two-branch dispatch is INLINED inside the per-epoch
loop at `single_pass.rs:383-406`:

```rust
if let Some(validator_index) = state.get_validator_index(&deposit_data.pubkey)? {
    state.get_balance_mut(validator_index)?
        .safe_add_assign(deposit_data.amount)?;
} else if is_valid_deposit_signature(&deposit_data, spec).is_ok() {
    let validator_index = state.add_validator_to_registry(
        deposit_data.pubkey, deposit_data.withdrawal_credentials, deposit_data.amount, spec,
    )?;
    added_validators.push((deposit_data.pubkey, validator_index));
}
```

Same single-pass-folding pattern as items #10 (slashings), #17
(registry updates). **`is_valid_deposit_signature` IS a separate
function** at `verify_deposit.rs:18-28` and is reused by both the
pre-Electra `process_deposits` path AND the Pectra
`process_pending_deposits` path.

### prysm: batch signature verification optimization

```go
// prysm/beacon-chain/core/electra/deposits.go:378
allSignaturesVerified, err := helpers.BatchVerifyPendingDepositsSignatures(ctx, pendingDeposits)
```

Prysm batches all deposit signatures for a given drain via
`BatchVerifyPendingDepositsSignatures` BEFORE the per-deposit loop.
If batch passes, individual per-deposit signature verification is
skipped. If batch fails, falls back to individual verification.

**Performance optimization for the common case** (all sigs valid).
Other clients verify per-deposit sequentially. This is observable-
equivalent because:
- A valid batch = all individual sigs valid → same per-deposit decision.
- A failed batch falls back to per-deposit → same result either way.

But the batch call exposes a subtle assumption: **the same
`compute_signing_root` MUST be reproducible per-deposit and as a
batch input** — otherwise the batch and individual paths could
diverge.

### lodestar: `pendingValidatorPubkeysCache` for batched-sig avoidance

```typescript
// processDepositRequest.ts:79-82 (cited in agent report)
// COMMENT: "Acknowledges the cache is naive and should move to
// epochCache for longer lifetime to avoid duplicated signature computation"
```

Lodestar maintains a per-block `pendingValidatorPubkeysCache:
Set<PubkeyHex>` that tracks pubkeys with verified signatures. If a
deposit's pubkey is in this cache, the per-deposit signature
verification is skipped. **Pre-emptive optimization** for the case
where multiple deposits target the same new pubkey within one block.

### nimbus: explicit pubkey-load failure handling

```nim
# signatures.nim:209-216
proc verify_deposit_signature*(genesis_fork_version: Version,
                               deposit: DepositData): bool =
  let pubkey = deposit.pubkey.load().valueOr:
    return false   # PUBKEY DECOMPRESSION FAILED → return false
  verify_deposit_signature(genesis_fork_version, deposit, pubkey)
```

Nimbus's `valueOr: return false` pattern explicitly handles pubkey
decompression failure. **Same observable behavior across all 6
clients** (failed pubkey load = invalid signature = silent drop in
apply_pending_deposit), but Nimbus's explicit handling is the most
visible.

### teku: dependency injection via `BLSSignatureVerifier` interface

```java
// teku MiscHelpers.java:410-423
public boolean isValidDepositSignature(...) {
  try {
    return specConfig
        .getBLSSignatureVerifier()           // INJECTED — not direct BLS call
        .verify(pubkey, ..., signature);
  } catch (final BlsException e) {
    return false;
  }
}
```

Teku's `BLSSignatureVerifier` is a dependency-injected interface,
allowing test mocking. Other clients use direct BLS library calls.
This is the **most testable** of the six — though it adds a layer
of indirection.

### grandine: `pubkey_cache.get_or_insert(pubkey)` lazy decompression

```rust
// grandine epoch_processing.rs:367
pubkey_cache
    .get_or_insert(pubkey)
    .and_then(|decompressed| deposit_message.verify(config, signature, decompressed))
    .is_ok()
```

Grandine's pubkey cache stores DECOMPRESSED pubkeys; `get_or_insert`
lazily computes and caches the decompression on first access. **Most
efficient pubkey-cache design** of the six — others either decompress
per-call (lighthouse, lodestar) or store compressed and decompress in
the verify call (prysm, nimbus, teku).

### Five distinct GENESIS_FORK_VERSION pin idioms

All 6 clients correctly use GENESIS_FORK_VERSION, but with five
distinct dispatch styles:

- **prysm**: `signing.ComputeDomain(domainType, nil, nil)` — `nil`
  fork_version triggers `params.BeaconConfig().GenesisForkVersion`
  default.
- **lighthouse**: `spec.get_deposit_domain()` (named getter that
  hardcodes `genesis_fork_version` per spec comment "Deposits are
  valid across forks").
- **teku**: `computeDomain(DOMAIN_DEPOSIT)` overload (no
  fork_version arg) → internally uses
  `specConfig.getGenesisForkVersion()`.
- **nimbus**: `compute_domain(DOMAIN_DEPOSIT, genesis_fork_version)`
  with explicit `cfg.GENESIS_FORK_VERSION` argument passed by caller.
- **lodestar**: explicit `computeDomain(DOMAIN_DEPOSIT,
  config.GENESIS_FORK_VERSION, ZERO_HASH)`.
- **grandine**: trait-based with `const DOMAIN_TYPE = DOMAIN_DEPOSIT`
  and `compute_domain(config, ..., None, None)` defaulting to
  `config.genesis_fork_version`.

**All converge on the same domain bytes** for any given (network,
deposit) pair.

## EF fixture status — implicit coverage via item #4

This audit has **no dedicated EF fixture set** because
`apply_pending_deposit` and `is_valid_deposit_signature` are
internal helpers. They are exercised IMPLICITLY via:

| Item | Fixtures × clients | Calls these helpers |
|---|---|---|
| **#4** process_pending_deposits | 43 × 4 = 172 | item #4's drain → `apply_pending_deposit` → `is_valid_deposit_signature` |
| **#14** process_deposit_request | 11 × 4 = 44 | item #14 enqueues → item #4 drains → these helpers |

**Total implicit cross-validation evidence**: **216 EF fixture
PASSes** across 54 unique fixtures all flow through these helpers.
Critical fixtures testing the SILENT DROP path:
- `pending_deposits_with_bad_signatures` — multiple invalid-sig
  deposits, verified that they silently consume queue slots without
  state mutation.
- `pending_deposits_with_genesis_fork_version_signed_*` — confirms
  GENESIS_FORK_VERSION pin (signatures from genesis-era still valid
  post-Pectra).

A dedicated fixture set for the helpers would consist of:
1. `apply_pending_deposit`: input `(state, deposit)` triples covering
   all 4 paths (new+valid sig, new+invalid sig, existing pubkey,
   existing+invalid sig irrelevant).
2. `is_valid_deposit_signature`: input `(pubkey, creds, amount, sig)`
   covering valid sig, invalid sig, malformed pubkey, malformed sig.

**Both are directly fuzzable** (pure functions of inputs).

## Cross-cut chain — closes the BLS Track F first audit + EIP-7685 deposit-pipeline coverage

This audit closes the BLS-library cross-client comparison for
deposits (Track F first audit in the corpus — confirms all 6
clients use BLST or BLST wrappers). Combined with prior items, the
EIP-7685 deposit pipeline is now audited end-to-end:

```
[item #14] process_deposit_request: EL → PendingDeposit{slot=state.slot}
[item #11] upgrade_to_electra:      pre-activation → PendingDeposit{slot=GENESIS_SLOT, sig=G2_INFINITY}
                ↓
[item #4] process_pending_deposits per-epoch: outer drain (loop, churn budget, postpone)
                ↓ for each pending deposit
[item #20 (this)] apply_pending_deposit:
    - cached pubkey lookup
    - new path: is_valid_deposit_signature with GENESIS_FORK_VERSION pin
    - existing path: increase_balance (top-up)
    - SILENT DROP on failed sig
                ↓ if new + valid sig:
[item #18] add_validator_to_registry → get_validator_from_deposit
    - uses item #1's get_max_effective_balance for credential-dependent cap
                ↓ next epoch:
[item #17] process_registry_updates: activation eligibility + activation
```

End-to-end Pectra deposit lifecycle audited. Items #1, #4, #11,
#14, #17, #18, #20 (this) cover the complete chain.

## Adjacent untouched

- **Generate dedicated EF fixture set** for `is_valid_deposit_signature`
  — pure-function cross-client byte-for-byte equivalence test.
- **Cross-client BLS library version audit**: prysm BLST 0.3.x,
  lighthouse blst 0.3.x, teku blst via tek-bls (version-pinned),
  nimbus blscurve (specific BLST commit), lodestar @chainsafe/blst
  v2.2.0, grandine bls-blst. Verify all use compatible BLST versions.
- **Pre-emptive Gloas audit**: at Gloas, lodestar's
  `applyDepositForBuilder` performs ON-THE-FLY signature verification
  (item #14 audit). Verify other clients' Gloas-fork code path.
- **GENESIS_FORK_VERSION constant value verification**: each
  network has a distinct genesis_fork_version (mainnet, sepolia,
  holesky, etc.). Verify cross-client agreement per network.
- **prysm batch-vs-individual signature path equivalence**: assert
  that batch verification + per-deposit fallback always produce the
  same per-deposit decisions.
- **lodestar `pendingValidatorPubkeysCache` correctness**: verify
  that cache hits don't cause stale "valid sig" decisions if the
  same pubkey appears multiple times with different
  withdrawal_credentials in the same block (each deposit message
  is distinct because amount + creds are different — verify the
  cache key is safely chosen).
- **nimbus pubkey decompression failure path**: cross-client
  verification that all clients return `false` (not error/panic)
  on malformed pubkey bytes.
- **teku `BLSSignatureVerifier` mock injection** — useful for
  fuzzing-style testing where the verifier returns predetermined
  results.
- **grandine pubkey cache eviction policy**: bounded-size cache
  with eviction could regress to per-call decompression under
  adversarial input. Worth verifying.
- **DepositMessage SSZ root computation cross-client**: the
  `compute_signing_root(deposit_message, domain)` step computes
  `hash_tree_root(deposit_message)` then mixes in the domain.
  Verify all 6 clients compute identical roots.
- **`bls.Verify` semantics**: when the pubkey is the identity
  point (G1_POINT_AT_INFINITY), BLS verify behavior differs
  between libraries. Verify all 6 clients reject identity-pubkey
  deposits identically.
- **Subgroup check enforcement**: lodestar's `PublicKey.fromBytes(pubkey, true)`
  passes `true` to enable subgroup checks. Verify other clients
  enforce subgroup checks identically (security-critical against
  small-subgroup attacks).

## Future research items

1. **Generate dedicated EF fixture set** for `is_valid_deposit_signature`
   — direct cross-client BLS-output comparison.
2. **Cross-client BLS library version compatibility audit** — all
   6 use BLST or BLST wrappers; verify version compatibility.
3. **GENESIS_FORK_VERSION cross-client per-network constant
   verification** — mainnet, sepolia, holesky, etc.
4. **prysm batch-vs-individual signature path equivalence test**.
5. **lodestar `pendingValidatorPubkeysCache` correctness fuzz** —
   same pubkey, different `(amount, creds)` cases.
6. **nimbus pubkey decompression failure cross-client equivalence
   test** (malformed pubkey bytes → all return false uniformly).
7. **teku `BLSSignatureVerifier` mock-injection fuzzing harness** —
   test-time assertion that injected results don't propagate to
   state.
8. **grandine pubkey cache eviction policy under adversarial
   input** — bounded-size cache regression to per-call.
9. **DepositMessage SSZ root cross-client byte-for-byte equivalence**.
10. **`bls.Verify` identity-pubkey edge case** cross-client
    rejection contract.
11. **Subgroup check enforcement audit** — lodestar passes `true`
    explicitly; verify other clients enforce identically (security-
    critical against small-subgroup attacks).
12. **Pre-emptive Gloas-fork audit**: lodestar
    `applyDepositForBuilder` on-the-fly signature verification
    pattern; cross-client Gloas-fork divergence.
13. **`compute_signing_root` vs `hash_tree_root + mix_in(domain)`
    equivalence** — verify all 6 clients compute the same signing
    root for the same DepositMessage + domain.
14. **EF fixture coverage gap audit** — list every Pectra-NEW
    helper without dedicated EF coverage (item #15 requestsHash,
    item #16 churn primitives, item #18 add_validator_to_registry,
    item #20 (this) apply_pending_deposit + is_valid_deposit_signature).
