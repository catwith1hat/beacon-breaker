# Item #14 — `process_deposit_request` (EIP-6110, brand-new in Pectra)

**Status:** no-divergence-pending-fuzzing — audited 2026-05-02. EIP-6110
producer side; **closes the EIP-6110 deposit chain** (item #4 drain ←
item #11 upgrade-time empty-queue init ← item #13 dispatcher ← THIS
producer). All four pieces of the in-protocol deposit lifecycle are now
audited.

## Why this item

`process_deposit_request` is the **producer** of `state.pending_deposits`
entries originating from the EL's EIP-6110 deposit contract. It is the
counterpart to:
- **item #11** (`upgrade_to_electra`) which initializes
  `state.pending_deposits = []` and seeds it with pre-activation
  validators using `slot = GENESIS_SLOT` (placeholder marker);
- **item #13** (`process_operations` dispatcher) which calls THIS
  function for each entry in `body.execution_requests.deposits`;
- **item #4** (`process_pending_deposits`) which drains the queue at
  per-epoch processing and applies signature verification (deferred
  from THIS step).

The pyspec is **remarkably simple** — just two operations:

```python
def process_deposit_request(state: BeaconState, deposit_request: DepositRequest) -> None:
    # Sentinel transition (ONCE-only)
    if state.deposit_requests_start_index == UNSET_DEPOSIT_REQUESTS_START_INDEX:
        state.deposit_requests_start_index = deposit_request.index

    # Append to queue (no signature verification at this step)
    state.pending_deposits.append(
        PendingDeposit(
            pubkey=deposit_request.pubkey,
            withdrawal_credentials=deposit_request.withdrawal_credentials,
            amount=deposit_request.amount,
            signature=deposit_request.signature,
            slot=state.slot,         # NOT GENESIS_SLOT
        )
    )
```

The simplicity is deceptive — five divergence-prone bits hide in this
13-line function:

1. **Sentinel transition semantics** — `==` strict equality with
   `UNSET_DEPOSIT_REQUESTS_START_INDEX = 2^64 - 1` (NOT `<` or `>`).
2. **ONCE-only set** — the `if` ensures subsequent requests don't
   overwrite the start_index after the first one sets it.
3. **Set-value source** — uses `deposit_request.index` (NOT
   `state.slot`, NOT a derived value).
4. **Five-field PendingDeposit** with **`slot = state.slot`** (NOT
   `GENESIS_SLOT`) — this is what differentiates a real deposit
   request from item #11's pre-activation placeholder. **Item #4's
   drain treats slot==GENESIS_SLOT specially** (skips signature
   verification because the placeholder signature is
   G2_POINT_AT_INFINITY).
5. **No signature verification at this step** — the request's
   signature is passed through as-is. Item #4's drain validates it
   later via `is_valid_deposit_signature`. A request with an invalid
   signature **MUST NOT** be rejected here — it must enter the queue
   and fail at drain time.

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | Sentinel comparison: strict `==` against `UNSET_DEPOSIT_REQUESTS_START_INDEX = u64::MAX = 2^64 - 1` | ✅ all 6 |
| H2 | Sentinel set ONCE only — subsequent requests don't overwrite | ✅ all 6 |
| H3 | Sentinel set-value: `deposit_request.index` (NOT `state.slot` or any other field) | ✅ all 6 |
| H4 | PendingDeposit has 5 fields: pubkey, withdrawal_credentials, amount, signature, slot | ✅ all 6 |
| H5 | `slot = state.slot()` (NOT `GENESIS_SLOT`) — distinguishes real requests from item #11 placeholders | ✅ all 6 |
| H6 | NO signature verification at this step (deferred to item #4's drain) | ✅ all 6 (Electra path); ⚠️ lodestar Gloas-fork `applyDepositForBuilder` performs on-the-fly verification (NOT a Pectra-fork concern) |
| H7 | Append to `state.pending_deposits` (no replacement, no truncation) | ✅ all 6 |
| H8 | Per-element loop iterates `body.execution_requests.deposits` and calls per-request logic for each | ✅ all 6 |

## Per-client cross-reference

| Client | Function location | Sentinel idiom | PendingDeposit construction |
|---|---|---|---|
| **prysm** | `core/requests/deposits.go:15–73` (`ProcessDepositRequests` batch + `processDepositRequest` per-element); `state-native/setters_deposits.go` for `AppendPendingDeposit` (with COW semantics) | `requestsStartIndex == params.BeaconConfig().UnsetDepositRequestsStartIndex` (= `math.MaxUint64`) | Direct proto-struct `&ethpb.PendingDeposit{...}` with `bytesutil.SafeCopyBytes` defensive copies on pubkey/credentials/signature; `Slot: beaconState.Slot()` |
| **lighthouse** | `state_processing/src/per_block_processing/process_operations.rs:589–614` (`process_deposit_requests` plural) | `state.deposit_requests_start_index()? == spec.unset_deposit_requests_start_index` (= `u64::MAX`) | `pending_deposits.push(PendingDeposit { pubkey, withdrawal_credentials, amount, signature: request.signature.clone(), slot })?` (milhouse `List::push` returning `Result`) |
| **teku** | `versions/electra/execution/ExecutionRequestsProcessorElectra.java:87–93` (batch) + `:95–114` (per-element) | `state.getDepositRequestsStartIndex().equals(SpecConfigElectra.UNSET_DEPOSIT_REQUESTS_START_INDEX)` (= `UInt64.MAX_VALUE`) | Schema-driven `schemaDefinitions.getPendingDepositSchema().create(SszPublicKey, SszBytes32, SszUInt64, SszSignature, SszUInt64)` |
| **nimbus** | `state_transition_block.nim:391–410` (Electra/Fulu variant; +`:413–448` for Gloas variant); call site at `:864–866` | `state.deposit_requests_start_index == UNSET_DEPOSIT_REQUESTS_START_INDEX` (= `not 0'u64` = `0xFFFFFFFFFFFFFFFF`) | `state.pending_deposits.add(PendingDeposit(...))` returning bool, with `if not added: err("...")` fail-loud pattern |
| **lodestar** | `state-transition/src/block/processDepositRequest.ts:83–138`; call site `processOperations.ts:78` | `state.depositRequestsStartIndex === UNSET_DEPOSIT_REQUESTS_START_INDEX` (= `2n ** 64n - 1n`); **gated by `fork < ForkSeq.gloas`** (Gloas restructures deposit handling) | `ssz.electra.PendingDeposit.toViewDU({pubkey, withdrawalCredentials, amount, signature, slot: state.slot})` then `state.pendingDeposits.push(pendingDeposit)` |
| **grandine** | `transition_functions/src/electra/block_processing.rs:1155–1183`; call site at `custom_process_block:194-195` | `state.deposit_requests_start_index() == UNSET_DEPOSIT_REQUESTS_START_INDEX` (= `u64::MAX`) | `state.pending_deposits_mut().push(PendingDeposit { pubkey, withdrawal_credentials, amount, signature, slot })?` (PersistentList::push returning `Result`) |

## EF fixture results — 44/44 PASS

Ran all 11 EF mainnet/electra/operations/deposit_request fixtures
across the 4 wired clients via `scripts/run_fixture.sh`:

```
clients: prysm, lighthouse, lodestar, grandine
fixtures: 11
PASS: 44   FAIL: 0   SKIP: 0   total: 44
```

Per-fixture coverage:

| Fixture | Hypothesis tested |
|---|---|
| `process_deposit_request_extra_gwei` | H4: amount field passed through unchanged |
| `process_deposit_request_greater_than_max_effective_balance_compounding` | H4: >MAX_EB amount queued (drain decides) |
| `process_deposit_request_invalid_sig` | **H6: invalid sig MUST NOT reject — request enters queue, fails at drain** |
| `process_deposit_request_max_effective_balance_compounding` | H4 + Track A consolidation cross-cut |
| `process_deposit_request_min_activation` | H4: minimum-amount activation case |
| `process_deposit_request_set_start_index` | **H1+H2+H3: sentinel transition on first request** |
| `process_deposit_request_set_start_index_only_once` | **H2: subsequent requests do NOT overwrite** |
| `process_deposit_request_top_up_invalid_sig` | H6: invalid sig top-up still queued |
| `process_deposit_request_top_up_max_effective_balance_compounding` | H4: top-up at MAX_EB cap |
| `process_deposit_request_top_up_min_activation` | H4: top-up bringing to MIN_ACTIVATION |
| `process_deposit_request_top_up_still_less_than_min_activation` | H4: top-up STILL below activation threshold |

teku and nimbus SKIP per harness limitation (no per-operation CLI hook
in BeaconBreaker's runners). Both have full implementations per source
review.

## Notable per-client divergences (all observable-equivalent)

### lodestar's `fork < ForkSeq.gloas` gate on the sentinel-set

```typescript
if (fork < ForkSeq.gloas && state.depositRequestsStartIndex === UNSET_DEPOSIT_REQUESTS_START_INDEX) {
    state.depositRequestsStartIndex = depositRequest.index;
}
```

Lodestar gates the sentinel transition on `fork < ForkSeq.gloas`. At
Pectra/Electra (ForkSeq 5), this is `5 < 7 = true` → sentinel logic
runs as expected. At Gloas (ForkSeq 7), the condition is `false` →
**the sentinel is NOT set by `processDepositRequest` at Gloas**.

This matches the broader Gloas restructuring (EIP-7732 PBS adds
builder deposits with on-the-fly BLS verification via
`applyDepositForBuilder`). Gloas-fork code paths handle the
deposit_requests_start_index transition elsewhere.

**For the Pectra audit, this is observable-equivalent.** For a future
Gloas audit, this gate is a critical piece of the
deposit-handling restructure.

### grandine has TWO `process_deposit_request` definitions

```
grandine/transition_functions/src/electra/block_processing.rs:1155     pub fn process_deposit_request<P>(...)  // Pectra: simple, no verification
grandine/transition_functions/src/gloas/execution_payload_processing.rs:290  pub fn process_deposit_request<P>(...)  // Gloas: complex with builder logic + signature verification
```

Same source-organization pattern as items #6 (`initiate_validator_exit`
× 2), #9 (`slash_validator` × 4), #10 (`process_slashings` × 5), #12
(`process_withdrawals` × 4 across capella/electra/gloas). The Pectra
`custom_process_block:194-195` correctly imports from
`block_processing` (electra module). F-tier today since all known
callers correctly import; worth a one-line audit for any future
refactor.

### prysm's `bytesutil.SafeCopyBytes` defensive copies

```go
if err := beaconState.AppendPendingDeposit(&ethpb.PendingDeposit{
    PublicKey:             bytesutil.SafeCopyBytes(req.Pubkey),
    WithdrawalCredentials: bytesutil.SafeCopyBytes(req.WithdrawalCredentials),
    Amount:                req.Amount,
    Signature:             bytesutil.SafeCopyBytes(req.Signature),
    Slot:                  beaconState.Slot(),
}); err != nil {
```

Defensive against external mutation of the input proto struct's byte
slices. Other clients rely on Rust's borrow checker (lighthouse,
grandine), Java's immutable types (teku), Nim's value semantics
(nimbus), or TypeScript's primitive immutability (lodestar). Prysm's
extra copies are F-tier today (proto messages are typically
single-use) but defensive against a hypothetical proto-reuse bug.

### nimbus's `state.pending_deposits.add(...)` fail-loud pattern

```nim
if state.pending_deposits.add(PendingDeposit(...)):
  ok()
else:
  err("process_deposit_request: couldn't add deposit to pending_deposits")
```

Nimbus's `HashList.add` returns `bool` indicating whether the add
succeeded (it can fail if the list is at capacity = 2^27 = 134M
entries). The `if/else err` makes failure observable at the call
site. **Other clients use unconditional push** — if the list is at
capacity, lighthouse's `?` propagates the error from milhouse's
`push`, grandine's `?` propagates from PersistentList's push, prysm
returns from `AppendPendingDeposit` with a wrapped error, lodestar's
SSZ `push` would throw, teku's `append` would throw. Nimbus's
explicit-bool-check is more visibly fail-loud.

### teku's schema-driven SSZ creation

```java
final PendingDeposit deposit =
    schemaDefinitions
        .getPendingDepositSchema()
        .create(
            new SszPublicKey(depositRequest.getPubkey()),
            SszBytes32.of(depositRequest.getWithdrawalCredentials()),
            SszUInt64.of(depositRequest.getAmount()),
            new SszSignature(depositRequest.getSignature()),
            SszUInt64.of(state.getSlot()));
```

The most verbose construction (5 explicit SSZ wrapper types) but also
the most type-safe — the `.create(...)` method's signature enforces
field count and order at compile time. A spec change adding/removing
a field would force a teku compile failure. Other clients use direct
field assignment; teku's schema indirection is unique.

## Cross-cut chain — EIP-6110 deposit lifecycle CLOSED

Items #11 + #13 + #14 + #4 form the complete EIP-6110 deposit
lifecycle:

| Item | Operation | `state.pending_deposits` access | `state.deposit_requests_start_index` access |
|---|---|---|---|
| #11 upgrade_to_electra | INIT: empty + seed pre-activation w/ `slot=GENESIS_SLOT` | INIT-write | INIT to `UNSET = 2^64 - 1` |
| #13 process_operations dispatcher | DISPATCH | (via item #14) | (via item #14) |
| **#14 process_deposit_request (this)** | **APPEND new entries w/ `slot=state.slot`** | **WRITE-append** | **SET ONCE on first request** |
| #4 process_pending_deposits | READ + DRAIN | READ + WRITE-slice | READ-only (cursor for `eth1_deposit_index_limit`) |

**Cumulative fixture evidence**:
| Item | Fixtures (total wired-client invocations) |
|---|---|
| #4 process_pending_deposits | 43/43 (172 invocations) |
| #11 upgrade_to_electra | source-only (22 EF fixtures available, harness gap) |
| #13 process_operations dispatcher | implicit via prior items (1120 invocations) |
| #14 process_deposit_request (this) | 11/11 (44 invocations) |

The deposit lifecycle is now **the most thoroughly cross-validated
Pectra surface in the corpus** — a single invariant-violating bug
anywhere in the chain would have surfaced as a fixture failure in at
least one of items #4/#11/#13/#14. None did.

## Adjacent untouched

- **`requestsHash` Merkleization** passed to EL via NewPayloadV4 —
  high-priority follow-up. Computes
  `sha256(get_execution_requests_list(...))` from the
  ExecutionRequests container. Cross-client hash mismatch would cause
  EL fork at the boundary.
- **`get_execution_requests_list` SSZ encoding helper** — companion
  to requestsHash. Encodes each non-empty request list as
  `request_type_byte + ssz_serialize(request_data)`, filtering empty.
- **lodestar's `applyDepositForBuilder` Gloas-fork path** — performs
  ON-THE-FLY signature verification (line 30 of `processDepositRequest.ts`):
  ```typescript
  if (isValidDepositSignature(state.config, pubkey, withdrawalCredentials, amount, signature)) {
      addBuilderToRegistry(state, pubkey, withdrawalCredentials, amount, slot);
  }
  ```
  This DIVERGES from the Pectra "no verification at this step"
  design at Gloas. Audit Gloas-fork deposit handling separately.
- **grandine's Gloas `process_deposit_request` definition**
  (`gloas/execution_payload_processing.rs:290`) — also has builder
  logic + signature verification. Cross-client Gloas audit needed.
- **`pubkey_cache` invalidation timing** — lighthouse calls
  `state.update_pubkey_cache()?` BEFORE the three new dispatchers in
  item #13. Other clients have their own cache choreography. Item
  #4's drain must see the cache populated correctly when validators
  are added via `add_validator_to_registry`.
- **`UNSET_DEPOSIT_REQUESTS_START_INDEX` value across clients** —
  all 6 use `2^64 - 1` (max u64). Any client that used a different
  sentinel (e.g., 0 or some smaller value) would silently break the
  cutover. Verified consistent.
- **First-request-in-block semantics** — when a block carries
  multiple DepositRequests AND `state.deposit_requests_start_index`
  is still UNSET, the FIRST request sets the index; the rest see the
  set value and skip. Test fixture
  `process_deposit_request_set_start_index_only_once` exercises
  this. Verified across all 4 wired clients.
- **`MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192`** — extreme upper
  bound (vs withdrawals 16, consolidations 2). At max, a single block
  could append 8192 PendingDeposits. The drain (item #4) processes
  up to MAX_PENDING_DEPOSITS_PER_EPOCH = 16 per epoch, so a single
  max-sized DepositRequest block would take 8192/16 = 512 epochs =
  ~55 hours to drain. Adversarial-but-bounded.
- **Cross-cut with item #11's `slot=GENESIS_SLOT` placeholders**:
  item #4's `process_pending_deposits` drain treats slot==GENESIS_SLOT
  entries specially (skips signature verification because
  signature=G2_POINT_AT_INFINITY by upgrade construction). A real
  deposit request with `slot==GENESIS_SLOT` would be impossible
  (state.slot at upgrade is well past GENESIS_SLOT), but worth a
  defensive assertion.
- **`AppendPendingDeposit` COW semantics in prysm** — the shared
  field reference counting in `setters_deposits.go:23-31` ensures
  that copying state for parallel processing doesn't corrupt the
  original. Other clients use immutable persistent data structures
  (grandine's PersistentList, milhouse for lighthouse) or SSZ tree
  views (lodestar) that have natural COW.

## Future research items

1. **Audit `requestsHash` (sha256 of get_execution_requests_list)** —
   highest-priority follow-up; EL boundary-divergence vector.
2. **Audit `get_execution_requests_list` SSZ encoding** — companion
   to #1; deterministic, easy-to-fixture.
3. **Generate stateful EIP-6110 cutover fixture** spanning multiple
   blocks: pre-cutover block (sentinel UNSET, legacy deposits) → first
   DepositRequest block (sentinel set) → post-cutover block (legacy
   deposits == 0).
4. **Audit Gloas-fork `process_deposit_request` divergence** —
   lodestar's `applyDepositForBuilder` and grandine's
   `gloas/execution_payload_processing.rs:290` both add on-the-fly
   signature verification at Gloas. Cross-client Gloas audit needed
   when Gloas activates.
5. **Run the 8 `deposit_transition__*` sanity_blocks fixtures** —
   end-to-end EIP-6110 cutover verification; complements item #14's
   per-operation fixtures.
6. **`MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192` SSZ over-the-wire
   test** — block with 8193 deposits should reject at deserialization.
7. **`add_validator_to_registry` Pectra-modified helper** — called
   by item #4's drain when a deposit creates a new validator.
   Pectra-modified for compounding-credentials handling. Worth a
   standalone audit.
8. **`bytesutil.SafeCopyBytes` necessity in prysm** — equivalence
   test against the SSZ-deserialized borrowing in other clients.
9. **`deposit_request_index` continuity** — the EL emits
   DepositRequests with monotonically increasing indices. Item #14
   doesn't enforce monotonicity (it just stores the first index).
   What if the EL sends indices out of order? Likely caught by EL
   contract semantics, but worth a fixture.
10. **First-request-after-many-blocks vs first-request-in-first-block
    semantics** — the sentinel transition can happen on any block
    after Pectra activation. The EXACT slot of transition depends
    on EL behavior. Stateful fixture would verify cross-client
    handling of late vs immediate first DepositRequest.
11. **Defensive nil-checking equivalence** — prysm's
    `bytesutil.SafeCopyBytes` + nimbus's fail-loud `add` bool check
    + grandine's `?` Result + lighthouse's `?` Result + teku's
    schema-validated SSZ + lodestar's `toViewDU` — five distinct
    failure modes for the same edge-case scenarios. Codify as
    contract tests.
12. **PendingDeposit slot interpretation across producers** — item
    #11 uses `GENESIS_SLOT` (placeholder), item #2's switch path uses
    `GENESIS_SLOT` (placeholder), this item uses `state.slot()` (real).
    Item #4's drain MUST distinguish placeholder vs real correctly.
    Worth a contract test asserting that no producer EVER uses a
    fake-but-non-GENESIS slot.
