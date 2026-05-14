---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [4, 18]
eips: [EIP-7251, EIP-7044, EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 20: `apply_pending_deposit` + `is_valid_deposit_signature` (Pectra-NEW per-deposit application + EIP-7044-style signature pinning)

## Summary

`apply_pending_deposit` is the **inner per-deposit logic** called by item #4's `process_pending_deposits` drain. Two-branch dispatch on pubkey existence: (a) NEW VALIDATOR path — verify signature via `is_valid_deposit_signature`, then `add_validator_to_registry` (item #18); (b) EXISTING VALIDATOR path — `increase_balance`. Two critical Pectra-divergence-prone bits: **SILENT DROP on failed signature** (deposit consumed from queue but not applied; no error returned) and **GENESIS_FORK_VERSION fork-version pin** for the signing domain (deposits valid across all forks because the domain is fork-pinned to genesis).

**Pectra surface (the function bodies themselves):** all six clients implement the two-branch dispatch, GENESIS_FORK_VERSION pin, single-pubkey `bls.Verify` (NOT aggregate), and silent-drop semantics identically. **All six use BLST or BLST-based wrappers** for deposit signature verification — first cross-client BLS-library audit in the corpus confirms no library-family divergence. 216 implicit cross-validation invocations from items #4 + #14 (54 unique fixtures × 4 wired clients) flow through these helpers.

**Gloas surface (at the Glamsterdam target): no change.** Neither `apply_pending_deposit` nor `is_valid_deposit_signature` is modified at Gloas — no `Modified` headings in `vendor/consensus-specs/specs/gloas/beacon-chain.md`. The validator-side deposit path continues through these helpers unchanged. The Gloas chapter adds a **builder-side sister function** `apply_deposit_for_builder` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1556`) which performs on-the-fly BLS signature verification (different from this item's deferred-verification pattern); that handles the builder-deposit lifecycle and is the natural sister audit item. The EIP-8061 cascade from item #4 H8 (which affects the `get_activation_churn_limit` ceiling on per-epoch deposit drain volume) affects **which** deposits drain per epoch but does not propagate into this item's per-deposit application logic.

## Question

Pyspec `apply_pending_deposit` (Pectra-new, `vendor/consensus-specs/specs/electra/beacon-chain.md:957`):

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
    domain = compute_domain(DOMAIN_DEPOSIT)   # NO fork_version arg → GENESIS_FORK_VERSION default
    signing_root = compute_signing_root(deposit_message, domain)
    return bls.Verify(pubkey, signing_root, signature)
```

Nine Pectra-relevant divergence-prone bits (H1–H9 unchanged from the prior audit): two-branch dispatch, new-validator path signature gate, existing-validator path top-up, **silent drop on failed signature**, DepositMessage 3-field shape, **GENESIS_FORK_VERSION pin**, single `bls.Verify` call (NOT aggregate), `DOMAIN_DEPOSIT = 0x03000000`, pubkey-decompression-failure-returns-false.

**Glamsterdam target.** Neither function is modified at Gloas. `vendor/consensus-specs/specs/gloas/beacon-chain.md` has no `Modified apply_pending_deposit` or `Modified is_valid_deposit_signature` heading. The Gloas chapter adds a **new parallel helper** for the builder side:

- **`apply_deposit_for_builder`** (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1556`) — performs on-the-fly BLS signature verification and applies the deposit to `state.builders` (Gloas-new state field). Called from the Gloas-modified `process_deposit_request` (item #14 H9 finding) when the deposit's pubkey matches an existing builder OR carries `0x03` builder withdrawal credentials.

This is a **different code path** from this item's `apply_pending_deposit`. Builder deposits at Gloas bypass the validator-queue entirely (they're applied immediately at block time, not queued for per-epoch drain). Validator deposits (non-builder) continue to flow through item #4's drain → this item's `apply_pending_deposit` → item #18's `add_validator_to_registry`.

The hypothesis: *all six clients implement the Pectra two-branch dispatch, GENESIS_FORK_VERSION pin, and silent-drop semantics identically (H1–H9), and at the Glamsterdam target the function bodies are unchanged so H1–H9 continue to hold for validator-side deposits (H10).*

**Consensus relevance**: every new validator and every top-up flows through this code. A divergence in the silent-drop semantics would propagate as state-root mismatch (one client adds a validator on bad sig; others don't). A divergence in the GENESIS_FORK_VERSION pin would cause one client to reject all deposits signed pre-current-fork. The audit at Pectra finds these unanimously implemented; the recheck at Gloas finds the function bodies unchanged, so the conclusion carries forward unchanged for validator-side deposits.

## Hypotheses

- **H1.** Two-branch dispatch on pubkey existence (cached pubkey→index map for O(1)).
- **H2.** New-validator path: signature verify → if valid: `add_validator_to_registry`.
- **H3.** Existing-validator path: `increase_balance(state, validator_index, deposit.amount)` (top-up).
- **H4.** **SILENT DROP on failed signature**: no error, deposit just doesn't apply.
- **H5.** DepositMessage has 3 fields (pubkey, withdrawal_credentials, amount) — NO signature field.
- **H6.** `compute_domain(DOMAIN_DEPOSIT)` uses **GENESIS_FORK_VERSION** (NOT current fork).
- **H7.** Single `bls.Verify(pubkey, signing_root, signature)` call (NOT aggregate).
- **H8.** DOMAIN_DEPOSIT = `0x03000000` (constant across all 6 clients).
- **H9.** Pubkey decompression failure → return `false` (NOT panic/error).
- **H10** *(Glamsterdam target)*. Neither `apply_pending_deposit` nor `is_valid_deposit_signature` is modified at Gloas. The validator-side deposit path continues through these helpers unchanged. The Gloas-new `apply_deposit_for_builder` handles the builder-side path (sister-item out of scope). H1–H9 continue to hold post-Glamsterdam.

## Findings

H1–H10 satisfied. **No divergence at the source-level predicate or the EF-fixture level on either the Pectra or Glamsterdam surface.**

### prysm

`vendor/prysm/beacon-chain/core/electra/deposits.go:437-460` — `ApplyPendingDeposit`. Two-branch dispatch via `state.ValidatorIndexByPubkey`. Existing path: `helpers.IncreaseBalance(state, validatorIndex, amount)`. New path: `IsValidDepositSignature(...)` gate → `AddValidatorToRegistry(...)` (item #18).

`vendor/prysm/beacon-chain/core/electra/deposits.go:168-179` — `IsValidDepositSignature`. Uses `signing.ComputeDomain(DomainDeposit, nil, nil)` — the `nil` fork-version arg defaults to `params.BeaconConfig().GenesisForkVersion`. **BLST via gnark crypto** for signature verification.

**Batch optimisation**: `vendor/prysm/beacon-chain/core/electra/deposits.go:378` — `BatchVerifyPendingDepositsSignatures` runs before the per-deposit loop. If batch passes, individual verification is skipped. If batch fails, falls back to per-deposit. Observable-equivalent because the batch and individual paths use the same signing-root computation.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** (function unchanged at Gloas; Gloas `process_deposit_request` builder-routing branch at `core/gloas/deposit_request.go:120-135` invokes `apply_deposit_for_builder` for builder-credentialled deposits — out of scope here).

### lighthouse

**`apply_pending_deposit` is NOT a separate function** — the two-branch dispatch is INLINED in the per-epoch loop at `vendor/lighthouse/consensus/state_processing/src/per_epoch_processing/single_pass.rs:383-406`:

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

Same single-pass-folding pattern as items #10 / #17. `is_valid_deposit_signature` IS a separate function at `vendor/lighthouse/consensus/state_processing/src/per_block_processing/verify_deposit.rs:18-28`, reused by both the pre-Electra `process_deposits` path AND the Pectra `process_pending_deposits` path.

Domain selection via `spec.get_deposit_domain()` (`vendor/lighthouse/consensus/types/src/chain_spec.rs:545-547`): `compute_domain(Domain::Deposit, self.genesis_fork_version, Hash256::zero())`. **blst** (supranational) via the `bls` crate wrapper.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** (single-pass dispatch unchanged at Gloas; the lighthouse Gloas-readiness gap is at item #14 H9 / #19 H10 — the builder-deposit routing — NOT at this item's validator-side path).

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/electra/statetransition/epoch/EpochProcessorElectra.java:187-202` — `applyPendingDeposit` override. Uses `validatorsUtil.getValidatorIndex(state, pubkey).ifPresentOrElse(idx -> increaseBalance(state, idx, amount), () -> { if (isValidPendingDepositSignature(deposit)) addValidatorToRegistry(...); })` — `Optional<Integer>` returns from cached validator-index map.

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/common/helpers/MiscHelpers.java:410-423` — `isValidDepositSignature`. Dependency-injected via `specConfig.getBLSSignatureVerifier()` interface — most testable of the six (mock-injectable). `try { ... } catch (final BlsException e) { return false; }` wraps the verify call. Domain via `computeDomain(Domain.DEPOSIT)` with internal `specConfig.getGenesisForkVersion()`.

**`tech.pegasys.teku.bls.BLSSignatureVerifier`** interface — pluggable BLS implementation; production uses `blst-jni`.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** (function unchanged at Gloas; teku's `ExecutionRequestsProcessorGloas.processDepositRequest` per item #14 H9 routes builder-credentialled deposits to `applyDepositForBuilder` via `BeaconStateMutatorsGloas`).

### nimbus

`vendor/nimbus/beacon_chain/spec/state_transition_epoch.nim:1185-1204` — `apply_pending_deposit`. Two-branch dispatch via precomputed `validator_index: Opt[ValidatorIndex]`. New-validator branch calls `verify_deposit_signature(cfg.GENESIS_FORK_VERSION, deposit_data)` — explicit genesis fork version arg passed by caller.

`vendor/nimbus/beacon_chain/spec/signatures.nim:209-216` (public) + `:200-207` (internal) — `verify_deposit_signature`. Explicit pubkey-load failure handling:

```nim
proc verify_deposit_signature*(genesis_fork_version: Version,
                               deposit: DepositData): bool =
  let pubkey = deposit.pubkey.load().valueOr:
    return false   # PUBKEY DECOMPRESSION FAILED → return false
  verify_deposit_signature(genesis_fork_version, deposit, pubkey)
```

`valueOr: return false` is the most visible H9 handling across the six clients.

**blscurve** (BLST Nim wrapper).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** (function unchanged at Gloas; the Gloas builder-routing is in the `process_deposit_request` Gloas variant at `state_transition_block.nim:413-448`, not in `apply_pending_deposit`).

### lodestar

`vendor/lodestar/packages/state-transition/src/epoch/processPendingDeposits.ts:110-139` — `applyPendingDeposit`. Two-branch dispatch via `pubkeyCache.getIndex`. New-validator path: `isValidDepositSignature(...)` → `addValidatorToRegistry(...)`. **`pendingValidatorPubkeysCache: Set<PubkeyHex>`** tracks pubkeys with verified signatures within the block for batched-sig avoidance.

`vendor/lodestar/packages/state-transition/src/block/processDeposit.ts:141-166` — `isValidDepositSignature`. Explicit `computeDomain(DOMAIN_DEPOSIT, config.GENESIS_FORK_VERSION, ZERO_HASH)`. Pubkey loaded via `PublicKey.fromBytes(pubkey, true)` — **explicit subgroup-check enable** (security-critical against small-subgroup attacks).

**@chainsafe/blst** (BLST TypeScript wrapper).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** (function unchanged at Gloas; lodestar's `processDepositRequest.ts applyDepositForBuilder` Gloas-fork path handles builder deposits separately).

### grandine

`vendor/grandine/transition_functions/src/electra/epoch_processing.rs:319-344` — `apply_pending_deposit`. Two-branch dispatch via `state.cached_index_of_public_key(...)`.

`vendor/grandine/transition_functions/src/electra/epoch_processing.rs:346-369` — `is_valid_deposit_signature`. Uses `pubkey_cache.get_or_insert(pubkey)` — **lazy decompression with caching**:

```rust
pubkey_cache
    .get_or_insert(pubkey)
    .and_then(|decompressed| deposit_message.verify(config, signature, decompressed))
    .is_ok()
```

Most efficient pubkey-cache design of the six (others either decompress per-call or store compressed). Domain via `compute_domain(config, DOMAIN_DEPOSIT, None, None)` — `None` fork-version arg defaults to `config.genesis_fork_version`.

**bls-blst** (BLST default; `bls-zkcrypto` alternative via feature flag).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. **H10 ✓** (function unchanged at Gloas; grandine's `gloas/execution_payload_processing.rs:290` Gloas-specific `process_deposit_request` handles builder deposits per item #14 H9 finding).

## Cross-reference table

| Client | `apply_pending_deposit` location | `is_valid_deposit_signature` location | BLS library | Gloas builder cross-cut (out of scope) |
|---|---|---|---|---|
| prysm | `core/electra/deposits.go:437-460 ApplyPendingDeposit` | `core/electra/deposits.go:168-179 IsValidDepositSignature` | **BLST** + batch optimisation at `:378 BatchVerifyPendingDepositsSignatures` | `core/gloas/deposit_request.go:120-135` (builder routing) |
| lighthouse | inlined at `single_pass.rs:383-406` (NOT a separate function) | `per_block_processing/verify_deposit.rs:18-28` | **blst (supranational)** via `bls` crate wrapper | **(no Gloas builder routing — item #14 H9 lighthouse-only gap)** |
| teku | `versions/electra/.../EpochProcessorElectra.java:187-202 applyPendingDeposit` (override) | `common/helpers/MiscHelpers.java:410-423 isValidDepositSignature` (DI via `BLSSignatureVerifier`) | `tech.pegasys.teku.bls` (`blst-jni`) | `ExecutionRequestsProcessorGloas.processDepositRequest` + `BeaconStateMutatorsGloas.applyDepositForBuilder` |
| nimbus | `state_transition_epoch.nim:1185-1204 apply_pending_deposit` | `signatures.nim:209-216 verify_deposit_signature*` + `:200-207` internal | **blscurve** (BLST Nim wrapper) | `state_transition_block.nim:413-448` Gloas variant |
| lodestar | `epoch/processPendingDeposits.ts:110-139 applyPendingDeposit` + `pendingValidatorPubkeysCache` | `block/processDeposit.ts:141-166 isValidDepositSignature` + explicit subgroup-check at `PublicKey.fromBytes(pubkey, true)` | **@chainsafe/blst** | `processDepositRequest.ts applyDepositForBuilder` Gloas branch |
| grandine | `transition_functions/src/electra/epoch_processing.rs:319-344 apply_pending_deposit` | `:346-369 is_valid_deposit_signature` + `pubkey_cache.get_or_insert` lazy decompression | **bls-blst** (BLST default; `bls-zkcrypto` feature-gated alternative) | `gloas/execution_payload_processing.rs:290` Gloas `process_deposit_request` |

## Empirical tests

### Pectra-surface implicit coverage

**No dedicated EF fixture set** because these are internal helpers, not block-level operations. Exercised IMPLICITLY via:

| Item | Fixtures × wired clients | Calls these helpers |
|---|---|---|
| #4 process_pending_deposits | 43 × 4 = 172 | drain → `apply_pending_deposit` → `is_valid_deposit_signature` |
| #14 process_deposit_request | 11 × 4 = 44 | enqueue → drained by item #4 → these helpers |

**Total implicit cross-validation evidence**: 54 unique fixtures × 4 wired clients = **216 EF fixture PASS** results all flow through these helpers. Critical fixtures testing the SILENT DROP path: `pending_deposits_with_bad_signatures` (multiple invalid-sig deposits silently consume queue slots without state mutation); `apply_pending_deposit_incorrect_sig_new_deposit` (single invalid-sig deposit dropped at new-validator path); `pending_deposits_with_genesis_fork_version_signed_*` (confirms GENESIS_FORK_VERSION pin — signatures from genesis-era remain valid post-Pectra).

### Gloas-surface

No Gloas operations fixtures yet for these helpers. H10 is currently source-only — confirmed by walking each client's Gloas-state handling: validator-side deposits continue through this item's path unchanged; builder-side deposits route to the Gloas-new `apply_deposit_for_builder` (separate sister-audit).

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1 (priority — dedicated EF fixture set for `is_valid_deposit_signature`).** Inputs: `(pubkey, creds, amount, sig)` quadruples covering valid sig, invalid sig (wrong message), invalid sig (wrong pubkey), malformed pubkey bytes, malformed sig bytes. Expected output: boolean. Pure-function fuzzing, directly cross-clientable.
- **T1.2 (priority — silent-drop new-validator path).** `apply_pending_deposit` with a new pubkey + invalid signature. Expected: cursor advances (item #4's drain), no validator added, no error returned. Already covered by `apply_pending_deposit_incorrect_sig_new_deposit`.
- **T1.3 (priority — silent-drop top-up path).** `apply_pending_deposit` with an existing pubkey + invalid signature. Expected: balance INCREASES regardless (signature is not checked for top-ups). Covered by `apply_pending_deposit_top_up_invalid_sig`.

#### T2 — Adversarial probes
- **T2.1 (defensive — pubkey decompression failure).** PendingDeposit with malformed pubkey bytes (e.g., not a valid G1 point in compressed form). All six clients should return `false` from `is_valid_deposit_signature` (not panic/error). Verify cross-client.
- **T2.2 (defensive — subgroup check enforcement).** Pubkey is a valid G1-curve point but NOT in the BLS12-381 subgroup. Per H9 (and lodestar's `PublicKey.fromBytes(pubkey, true)` explicit subgroup check), should be rejected. Verify all 6 clients enforce identically (security-critical against small-subgroup attacks).
- **T2.3 (defensive — identity pubkey).** Pubkey = G1 identity point. Per BLS spec, identity pubkeys cannot produce valid signatures. Verify all 6 clients reject.
- **T2.4 (defensive — GENESIS_FORK_VERSION cross-network).** Same DepositMessage signed with different network's GENESIS_FORK_VERSION. Verify cross-network rejection (mainnet client rejects sepolia-signed deposit, etc.).
- **T2.5 (Glamsterdam-target — builder-credentialled deposit routing bypass).** Gloas state. Submit a `0x03`-credentialled deposit. Per item #14 H9, it should route to `apply_deposit_for_builder` (NOT this item's `apply_pending_deposit`). Verify that this item's path is NOT invoked for builder deposits at Gloas — sister-item assertion.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms the Pectra-surface hypotheses (H1–H9) remain satisfied: identical two-branch dispatch, identical SILENT DROP semantics on failed signature (deposit consumed from queue but not applied; no error returned), identical GENESIS_FORK_VERSION fork-version pin, identical single-pubkey `bls.Verify` (NOT aggregate), identical `DOMAIN_DEPOSIT = 0x03000000` constant, identical pubkey-decompression-failure-returns-false handling. **All six clients use BLST or BLST-based wrappers** — first cross-client BLS-library audit confirms no library-family divergence at this surface. 216 implicit EF fixture invocations from items #4 + #14 cross-validate without divergence.

**Glamsterdam-target finding (H10 — no change).** Neither `apply_pending_deposit` nor `is_valid_deposit_signature` is modified at Gloas — `vendor/consensus-specs/specs/gloas/beacon-chain.md` has no `Modified` headings for either. The validator-side deposit path continues through these helpers unchanged at Gloas. The Gloas chapter adds a **new parallel helper** `apply_deposit_for_builder` at line 1556 — performs on-the-fly BLS signature verification AND mutates `state.builders` for the builder-deposit lifecycle. That's a different code path entirely (not a drop-in replacement); it handles builder-credentialled deposits (`0x03` prefix) or deposits whose pubkey matches an existing builder, per the Gloas-modified `process_deposit_request` builder-routing branch (item #14 H9).

Each client's Gloas-state handling for validator-side deposits:

- **prysm**: `core/electra/deposits.go ApplyPendingDeposit` unchanged; the Gloas `core/gloas/deposit_request.go:120-135` builder-routing fires before this code path for builder deposits.
- **lighthouse**: `single_pass.rs:383-406` inlined dispatch unchanged. **Note**: lighthouse's broader Gloas-readiness gap is at items #14 H9 and #19 H10 — no Gloas builder routing in `process_deposit_request`; no envelope processing — so at Gloas lighthouse would attempt to queue ALL deposits (including builder-credentialled) through this item's `apply_pending_deposit`, not the Gloas-correct `apply_deposit_for_builder`. This item's H10 holds (function unchanged), but item #14 H9's failure on lighthouse propagates UPSTREAM, leaving lighthouse with a different effective behaviour than the other five clients.
- **teku, nimbus, lodestar, grandine**: function bodies unchanged at Gloas; Gloas builder-routing in their respective `process_deposit_request` Gloas variants correctly bypasses this item's path for builder deposits.

**EIP-8061 cascade from item #4 H8 does NOT propagate here.** Item #4 H8 (lighthouse + 4 others not fork-gating `get_activation_churn_limit` for Gloas) affects HOW MANY deposits drain per epoch (the `available_for_processing` budget) — but once a deposit is being applied via this item's `apply_pending_deposit`, the logic is identical. The cascade affects deposit DRAIN RATE, not per-deposit APPLICATION.

Notable per-client style differences (all observable-equivalent on the Pectra surface):

- **prysm** uses batch signature verification (`BatchVerifyPendingDepositsSignatures`) before the per-deposit loop — performance optimisation for the common all-sigs-valid case.
- **lighthouse** inlines the two-branch dispatch in the single-pass epoch processor (NOT a separate function); only `is_valid_deposit_signature` is a separate function.
- **teku** uses dependency-injected `BLSSignatureVerifier` interface — most testable.
- **nimbus** has the most-visible H9 handling (`valueOr: return false` on pubkey decompression).
- **lodestar** maintains `pendingValidatorPubkeysCache` for batched-sig avoidance + explicit `PublicKey.fromBytes(pubkey, true)` subgroup-check enable.
- **grandine** uses lazy-decompressing pubkey cache (`pubkey_cache.get_or_insert`) — most efficient cache design.

No code-change recommendation. Audit-direction recommendations:

- **Generate dedicated EF fixture set for `is_valid_deposit_signature`** — pure-function cross-client byte-for-byte equivalence test. Highest-priority gap closure for the BLS Track F audit family.
- **Cross-client BLS library version compatibility audit** — all 6 use BLST or BLST wrappers; verify version compatibility (security patches, ABI changes).
- **Sister item: audit `apply_deposit_for_builder` (Gloas-new)** — parallel to this item's audit for builders. On-the-fly signature verification (different from this item's deferred-verification pattern); same 5-vs-1 cohort as item #14 H9 (lighthouse alone fails).
- **GENESIS_FORK_VERSION cross-network per-network constant verification** — mainnet, sepolia, holesky, etc.
- **prysm batch-vs-individual signature path equivalence test** — assert that batch verification + per-deposit fallback always produce the same per-deposit decisions.
- **Subgroup check enforcement audit** — lodestar passes `true` explicitly; verify other clients enforce identically (security-critical).
- **DepositMessage SSZ root cross-client byte-for-byte equivalence** — assert all 6 clients compute identical signing roots for the same DepositMessage + domain.

## Cross-cuts

### With item #4 (`process_pending_deposits`)

Item #4's drain is the upstream caller of this item's `apply_pending_deposit`. At Gloas, item #4 H8 affects the per-epoch deposit drain rate (Gloas-new `get_activation_churn_limit` formula vs Electra `get_activation_exit_churn_limit`), but the per-deposit application logic is unchanged. Each deposit that drains hits this item's two-branch dispatch identically across all six clients on the validator side.

### With item #18 (`add_validator_to_registry` + `get_validator_from_deposit`)

Item #18 is the downstream callee for the new-validator path (`apply_pending_deposit` → `add_validator_to_registry` → `get_validator_from_deposit` → item #1's `get_max_effective_balance`). At Gloas, item #18 is also unchanged. Cross-cut chain: item #4 → item #20 (this) → item #18 → item #17 (eligibility set at next epoch boundary).

### With item #14 (`process_deposit_request`)

Item #14 enqueues deposits into `state.pending_deposits`. At Gloas (item #14 H9), the Gloas-modified `process_deposit_request` adds a builder-routing branch: builder-credentialled deposits bypass the queue and apply immediately via `apply_deposit_for_builder` (a separate code path from this item). Validator-side deposits continue to queue → drain via item #4 → this item.

### With Gloas `apply_deposit_for_builder` (sister item)

The Gloas-new `apply_deposit_for_builder` (`vendor/consensus-specs/specs/gloas/beacon-chain.md:1556`) is the **builder-side analog** of this item. Parallel structure (pubkey-existence check, signature verification, state mutation) but with three key differences:

- **On-the-fly verification** (NOT deferred to a per-epoch drain).
- **State target**: `state.builders` (NOT `state.validators`).
- **Triggered by**: `0x03` builder withdrawal credentials OR existing-builder pubkey match.

Same five-vs-one cohort as item #14 H9 (lighthouse alone fails to implement). Sister audit item.

### With item #19 H10 (Gloas `process_execution_payload` removed)

Item #19 H10 documents the EIP-7732 ePBS restructure: `process_execution_payload` is removed and replaced by `process_execution_payload_bid` + `process_parent_execution_payload` + `verify_execution_payload_envelope`. Items #2/#3/#14 request dispatchers relocate from `process_operations` to `process_parent_execution_payload`. This item's `apply_pending_deposit` is downstream of the relocation: it still gets called from item #4's drain (which is unchanged in scheduling — still in `process_epoch`). So the Gloas relocation upstream of item #14 doesn't propagate into this item.

## Adjacent untouched

1. **Generate dedicated EF fixture set for `is_valid_deposit_signature`** — pure-function fuzz. Closes the BLS Track F audit's primary gap.
2. **Cross-client BLS library version compatibility audit** — version-pin all 6 clients' BLST dependencies.
3. **Sister item: audit `apply_deposit_for_builder` (Gloas-new)** — parallel structure for builders; same 5-vs-1 cohort as item #14 H9.
4. **Pre-emptive Gloas audit at builder paths** — lighthouse Gloas-readiness gap propagates through items #14 H9 and #19 H10; verify other clients' Gloas-fork code paths.
5. **GENESIS_FORK_VERSION constant value verification** per network (mainnet, sepolia, holesky).
6. **prysm batch-vs-individual signature path equivalence**.
7. **lodestar `pendingValidatorPubkeysCache` correctness fuzz** — same pubkey, different `(amount, creds)` cases.
8. **nimbus pubkey decompression failure cross-client equivalence**.
9. **teku `BLSSignatureVerifier` mock-injection fuzzing harness**.
10. **grandine pubkey cache eviction policy under adversarial input**.
11. **DepositMessage SSZ root cross-client byte-for-byte equivalence**.
12. **`bls.Verify` identity-pubkey edge case** cross-client rejection contract.
13. **Subgroup check enforcement audit** — lodestar passes `true` explicitly; verify other clients enforce identically (security-critical against small-subgroup attacks).
14. **`compute_signing_root` vs `hash_tree_root + mix_in(domain)` equivalence** — verify all 6 clients compute the same signing root.
15. **EF fixture coverage gap audit** — items #15 (requestsHash), #16 (churn primitives), #18 (add_validator_to_registry), #20 (this) all lack dedicated EF fixtures despite being pure functions.
16. **Lighthouse's Gloas-readiness chain**: this item's H10 is satisfied (function unchanged), but items #14 H9 / #19 H10 / #15 H10 / #7 H10 / #9 H9 / #12 H11 / #13 H10 are not. The validator-side deposit path through this item continues to work; the broader EIP-7732 ePBS surface does not.
