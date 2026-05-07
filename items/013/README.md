# Item #13 — `process_operations` Pectra dispatcher (EIP-6110 cutover + EIP-7685 requests routing)

**Status:** no-divergence-pending-source-review — audited 2026-05-02.
The **outer routing function** that dispatches Pectra's three new
request types (deposits, withdrawals, consolidations) and gates the
EIP-6110 legacy-deposit cutover. Cross-cuts every audited operation
item (#2/#3/#6/#7/#8/#9 + future deposit_request audit) — they all
flow through this dispatcher.

## Why this item

`process_operations` is the **block-body fan-out** function — it
receives the parsed `BeaconBlockBody` and dispatches each operation
list to its per-operation processor. Pectra adds two distinct
modifications:

1. **EIP-6110 legacy-deposit cutover** (head of `process_operations`):
   ```python
   eth1_deposit_index_limit = min(
       state.eth1_data.deposit_count, state.deposit_requests_start_index
   )
   if state.eth1_deposit_index < eth1_deposit_index_limit:
       assert len(body.deposits) == min(MAX_DEPOSITS, eth1_deposit_index_limit - state.eth1_deposit_index)
   else:
       assert len(body.deposits) == 0   # Legacy mechanism disabled
   ```
   At the upgrade slot, `deposit_requests_start_index =
   UNSET_DEPOSIT_REQUESTS_START_INDEX = 2^64 - 1` (item #11). The
   `min` returns `state.eth1_data.deposit_count` → legacy mode active.
   When the EL eventually sends the first `DepositRequest`,
   `process_deposit_request` sets
   `state.deposit_requests_start_index = first_request.index`
   (sentinel transition) → `min` now returns the smaller value →
   legacy deposits drain to that index, then the second branch
   (`assert len == 0`) takes over permanently.

2. **EIP-7685 three new request dispatchers** (tail of
   `process_operations`):
   ```python
   for_ops(body.execution_requests.deposits,       process_deposit_request)
   for_ops(body.execution_requests.withdrawals,    process_withdrawal_request)
   for_ops(body.execution_requests.consolidations, process_consolidation_request)
   ```
   The order is **canonical and observable** — each per-operation
   processor mutates state, and (e.g.) a deposit-then-consolidation
   in the same block must process the deposit first (sees the
   pre-state validator set; the consolidation may then operate on
   the post-deposit state).

## Hypotheses

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | `eth1_deposit_index_limit = min(state.eth1_data.deposit_count, state.deposit_requests_start_index)` — using `min` (NOT `max` or just one of the two) | ✅ all 6 |
| H2 | `state.deposit_requests_start_index = UNSET (= 2^64 - 1)` keeps legacy mode active because `min(N, 2^64-1) = N` | ✅ all 6 |
| H3 | Branch 1: `state.eth1_deposit_index < limit` requires `len(body.deposits) == min(MAX_DEPOSITS = 16, limit - state.eth1_deposit_index)` | ✅ all 6 |
| H4 | Branch 2: `state.eth1_deposit_index >= limit` requires `len(body.deposits) == 0` (NOT `<= MAX_DEPOSITS`) | ✅ all 6 |
| H5 | Three new dispatchers in EXACT order: deposits → withdrawals → consolidations (NOT alphabetical, NOT reversed) | ✅ all 6 |
| H6 | Each dispatcher iterates `body.execution_requests.<list>` and calls per-operation processor for each | ✅ all 6 |
| H7 | Per-list SSZ caps: `MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192`, `MAX_WITHDRAWAL_REQUESTS_PER_PAYLOAD = 16`, `MAX_CONSOLIDATION_REQUESTS_PER_PAYLOAD = 2` (mainnet) | ✅ all 6 |
| H8 | The three new dispatchers run AFTER all the legacy-Capella operations (proposer_slashings → attester_slashings → attestations → deposits → voluntary_exits → bls_to_execution_changes) | ✅ all 6 |
| H9 | `body.execution_requests` SSZ container has exactly THREE fields (deposits, withdrawals, consolidations), no Phase0 leftovers | ✅ all 6 |

## Per-client cross-reference

| Client | Function location | Cutover idiom | Dispatcher style |
|---|---|---|---|
| **prysm** | `core/transition/electra.go:23–124` (`electraOperations`); cutover in `core/electra/transition.go:134–151` (`VerifyBlockDepositLength`) | `min(eth1Data.DepositCount, requestsStartIndex)` Go `min` builtin | three sequential `for _, X := range requests.Deposits/Withdrawals/Consolidations` loops with per-element nil-checks |
| **lighthouse** | `state_processing/src/per_block_processing/process_operations.rs:12–53`; cutover in `process_deposits():363–391` | `state.deposit_requests_start_index().unwrap_or(u64::MAX)` (defensive default to sentinel) + `safe_sub` overflow check | three sequential `process_<request>_requests(state, &block_body.execution_requests()?.<field>, spec)?` calls gated by `state.fork_name_unchecked().electra_enabled()` |
| **teku** | `versions/electra/block/BlockProcessorElectra.java:138–149` (override); cutover at `:168–191` (`verifyOutstandingDepositsAreProcessed`) | `state.getEth1Data().getDepositCount().min(BeaconStateElectra.required(state).getDepositRequestsStartIndex())` | three sequential `executionRequestsProcessor.process<X>Requests(state, executionRequests.get<X>())` calls; subclass-override of parent's `processOperationsNoValidation` |
| **nimbus** | `state_transition_block.nim:784–872`; cutover at `:793–815` | inline `min(state.eth1_data.deposit_count, state.deposit_requests_start_index)` with `when consensusFork >= ConsensusFork.Electra` branch | three sequential `for op in body.execution_requests.<list>` loops in `when consensusFork in ConsensusFork.Electra .. ConsensusFork.Fulu` block |
| **lodestar** | `state-transition/src/block/processOperations.ts:35–95`; cutover in `util/deposit.ts:5–22` (`getEth1DepositCount` helper) | `Number(electraState.depositRequestsStartIndex)` BigInt→number coercion + ternary | three sequential `for (const X of bodyElectra.executionRequests.<list>)` loops gated by `if (fork >= ForkSeq.electra && fork < ForkSeq.gloas)` |
| **grandine** | `transition_functions/src/electra/block_processing.rs:488–624` (`process_operations`); dispatchers actually live in `custom_process_block:193–206` (separated from `process_operations`) | `state.eth1_data().deposit_count.min(state.deposit_requests_start_index())` | three sequential `for X in &block.body.execution_requests.<list>` loops in `custom_process_block` (NOT `process_operations`) — structural divergence |

## Notable structural divergences (all observable-equivalent)

### grandine separates the dispatchers from `process_operations`

Pyspec puts the three new dispatchers AT THE END of `process_operations`.
Grandine's `process_operations` (lines 488–624) handles only the
EIP-6110 cutover and the legacy operations; the three new request
dispatchers live in `custom_process_block:193–206` as a separate
phase AFTER `process_operations` returns. The observable post-state
is identical because `custom_process_block` calls `process_operations`
first, then iterates the three request lists in order — but the call
graph differs from spec.

**Implications**:
- A future spec change that puts something AFTER the three dispatchers
  but inside `process_operations` would silently misorder in grandine.
- Code reviewers grep'ing for `process_deposit_request` callers see
  it called from `custom_process_block`, not from `process_operations`.
  Less spec-traceable.

### prysm's `VerifyBlockDepositLength` is a separate function from `electraOperations`

Pyspec's cutover assertion is INSIDE `process_operations`. Prysm
extracts it to `core/electra/transition.go:134–151`
(`VerifyBlockDepositLength`) and calls it from
`transition_no_verify_sig.go` BEFORE `electraOperations`. Same
observable behavior, different call graph.

### lighthouse handles `deposit_requests_start_index().unwrap_or(u64::MAX)` defensively

```rust
let deposit_requests_start_index = state.deposit_requests_start_index().unwrap_or(u64::MAX);
```

If the state accessor returns `Err` (e.g., pre-Electra state queried
post-Electra-fork), this falls back to `u64::MAX` — which is the
sentinel value, so `min(deposit_count, u64::MAX) = deposit_count` →
legacy mode active. Defensive but masks a programming error
(querying pre-Electra state in Electra path) silently. Worth a
`debug_assert!(electra_enabled)` for fail-loud semantics.

### lodestar's BigInt→number coercion at the cutover comparison

```typescript
const eth1DataIndexLimit: UintNum64 =
  eth1DataToUse.depositCount < electraState.depositRequestsStartIndex
    ? eth1DataToUse.depositCount
    : Number(electraState.depositRequestsStartIndex);
```

`depositRequestsStartIndex` is `bigint` (UintBn64), `depositCount`
is `number`. The `<` comparison silently coerces the number to
bigint via JS semantics. Then if the ternary picks `depositRequestsStartIndex`,
it converts BACK to number via `Number(...)`. This is safe today
because `deposit_count < 2^53` for the lifetime of mainnet (current
deposit count is ~10^6), but **a regression to comparing two raw
bigints would require updating callers downstream that expect
number**. F-tier today; pre-emptive concern.

### lodestar's ForkSeq guard `fork >= ForkSeq.electra && fork < ForkSeq.gloas`

Lodestar's dispatcher block excludes Gloas (ForkSeq 7) from running
the three request dispatchers. **This matches prysm's Gloas
behavior** — at Gloas, EIP-7732 (PBS) restructures payload
processing and the three request dispatchers move elsewhere. Both
clients have the Gloas-aware divergence; teku/nimbus/lighthouse/
grandine handle this via different mechanisms (per-fork class
overrides, `when` blocks, custom_process_block).

### nimbus uses `bsv[]` (bucket-sorted validators) optimization

Nimbus passes a `bsv[]` (bucket-sorted validators) cache to the
withdrawal_request and consolidation_request processors. This is a
performance optimization for the per-request validator lookups —
not a divergence vector but a notable optimization.

### prysm has per-element nil-checks on each request type

```go
for _, d := range requests.Deposits {
    if d == nil { return nil, electra.NewExecReqError("nil deposit request") }
}
```

Defensive against malformed proto inputs. Other clients rely on the
SSZ deserialization layer to enforce non-null elements. Prysm's
extra check is dead code if SSZ deserialization is correct, but
defensive against a hypothetical proto-level bug.

## EF fixture status — partial coverage via sanity_blocks deposit_transition__* fixtures

The dispatcher is exercised indirectly via:

- **`sanity/blocks/pyspec_tests/deposit_transition__*`** (8 fixtures)
  — directly tests the EIP-6110 cutover state machine:
  - `process_eth1_deposits`: pre-cutover, legacy deposits processed
  - `process_eth1_deposits_up_to_start_index`: cutover boundary
  - `start_index_is_set`: first DepositRequest sets the start index
  - `process_max_eth1_deposits`: MAX_DEPOSITS branch
  - `deposit_and_top_up_same_block`: concurrent legacy + new
  - `deposit_with_same_pubkey_different_withdrawal_credentials`
  - `invalid_eth1_deposits_overlap_in_protocol_deposits`
  - `invalid_not_enough_eth1_deposits`, `invalid_too_many_eth1_deposits`
- **`sanity/blocks/pyspec_tests/cl_exit_and_el_withdrawal_request_in_same_block`**
  — tests cross-dispatch ordering between legacy `voluntary_exit`
  and new `withdrawal_request` for the same validator in one block
- **`sanity/blocks/pyspec_tests/basic_btec_and_el_withdrawal_request_in_same_block`**
  — tests `bls_to_execution_change` then `withdrawal_request`
  ordering for the same validator
- All per-operation fixtures from items #2/#3/#7/#8/#9/#12 implicitly
  exercise the dispatchers (they all flow through `process_operations`)

A dedicated harness wiring for the `deposit_transition__*` fixtures
is straightforward (`sanity_blocks` category, electra fork) and
confirmed working in the existing harness. Running these is the
first follow-up.

**Implicit coverage tally** from prior items: 80 (item #12 withdrawals)
+ 30 (item #8 attester_slashings) + 25 (item #6 voluntary_exits) +
45 (item #7 attestations) + 15 (item #9 proposer_slashings) + 19
(item #3 withdrawal_requests) + 10 (item #2 consolidation_requests)
+ 13 (item #5 pending_consolidations) + 43 (item #4 pending_deposits)
= **280 fixtures** all PASS uniformly across 4 wired clients = 1120
PASS results that all flow through `process_operations`. Strongest
evidence yet that the dispatcher is correct across all 6 clients.

## Cross-cut chain — process_operations is the FAN-OUT root

Every audited block-level operation flows through this dispatcher:

```
process_operations (item #13 - this)
├── eth1_deposit_index_limit cutover (EIP-6110)
├── process_proposer_slashing (item #9)
├── process_attester_slashing (item #8)
├── process_attestation (item #7)
├── process_deposit (Capella-heritage)
├── process_voluntary_exit (item #6)
├── process_bls_to_execution_change (Capella-heritage)
├── process_deposit_request (EIP-6110, future audit)
├── process_withdrawal_request (item #3)
└── process_consolidation_request (item #2)
```

**Track A operations** (#2/#3 + future deposit_request) are the three
NEW request dispatchers; their per-operation correctness was audited
independently (items #2, #3) and must agree with the dispatcher's
ordering and per-element invocation pattern. **No divergence found
in either layer.**

## Adjacent untouched Electra-active

- **`process_deposit_request` (EIP-6110)** — the only major Pectra
  operation NOT yet audited as a standalone item. Sets the
  `deposit_requests_start_index` sentinel transition on first
  invocation. Closes the deposit chain (item #4 drain, item #11
  upgrade-time queue, this dispatcher, future deposit_request
  producer).
- **`requestsHash` Merkleization passed to EL via NewPayloadV4** —
  the CL computes `sha256(get_execution_requests_list(...))` and
  passes to the EL via `verify_and_notify_new_payload`. Cross-client
  hash mismatch would diverge at the EL boundary. **High-priority
  audit candidate.**
- **`get_execution_requests_list` encoding helper** — the SSZ
  serialization + type-byte prefix of the three request lists,
  filtering empty lists. Strict spec on which entries to include
  (only non-empty lists get a type byte + serialized data). Cross-
  client encoding parity needed.
- **lodestar/prysm `fork < ForkSeq.gloas` exclusion** — at Gloas
  (EIP-7732), the three dispatchers move elsewhere. The current
  gate ensures Gloas blocks don't run them via this path. Verify
  the Gloas-fork code re-implements correctly.
- **grandine's `custom_process_block` separation** — dispatchers
  outside `process_operations`. A spec change adding state mutation
  AFTER the dispatchers but INSIDE `process_operations` would
  silently misorder in grandine. Forward-compat audit.
- **Lighthouse's `update_pubkey_cache()?` before the dispatchers**
  (line 42) — necessary because `process_deposit_request` can add
  new validators with new pubkeys, and the cache must be ready.
  Other clients likely have similar cache-prep; verify cross-client
  consistency.
- **prysm's per-element nil-checks** (`if d == nil`) — defensive
  against proto-level malformation. Other clients rely on SSZ-level
  enforcement. Worth a contract test.
- **`MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192` is HUGE** vs
  `MAX_WITHDRAWAL_REQUESTS_PER_PAYLOAD = 16` and
  `MAX_CONSOLIDATION_REQUESTS_PER_PAYLOAD = 2`. The asymmetry
  reflects the expected request-rate ratios. Verify SSZ
  deserialization rejects 8193+ deposits cleanly.
- **`UNSET_DEPOSIT_REQUESTS_START_INDEX = 2^64 - 1` sentinel
  transition timing** — the FIRST `DepositRequest` in any block
  AFTER the Pectra activation sets this field. Until that happens,
  legacy deposits continue. The exact slot of transition is
  EL-determined (when the EL EIP-6110 deposit contract starts
  emitting requests). Worth a stateful fixture spanning the
  transition point.
- **Cross-cut with item #11**: `upgrade_to_electra` initializes
  `state.deposit_requests_start_index = UNSET`. Item #13 (this) is
  the first to consume it; until set, legacy deposits flow.
  Stateful fixture: pre-state with sentinel + block with no deposit
  requests + block with 1 deposit request → verify the
  start_index transitions correctly.

## Future research items

1. **Audit `process_deposit_request` (EIP-6110)** — the only major
   Pectra operation not yet audited. Sets the
   `deposit_requests_start_index` sentinel transition.
2. **Audit `requestsHash` (the SSZ-encoded requests list passed to
   EL)** — `sha256(get_execution_requests_list(...))` cross-client
   hash parity. **High-priority** because divergence would cause an
   EL fork.
3. **Audit `get_execution_requests_list` encoding** — type-byte
   prefix + SSZ serialize, filtering empty lists. Cross-client
   encoding test (deterministic, easy to fixture).
4. **Generate a stateful fixture spanning the EIP-6110 cutover** —
   block N with sentinel start_index → block N+1 with first
   DepositRequest → block N+2 with `assert len(body.deposits) == 0`
   active. Verify all 6 clients transition state machine identically.
5. **Run the 8 `deposit_transition__*` sanity_blocks fixtures** via
   the existing harness (already supports sanity_blocks/electra) —
   first concrete fixture verification of this dispatcher's behavior.
6. **lighthouse's `state.deposit_requests_start_index().unwrap_or(u64::MAX)`
   defensive default** — should be `debug_assert!(electra_enabled)`
   for fail-loud semantics.
7. **lodestar's BigInt→number coercion at the cutover comparison** —
   pre-emptive fuzz target for the unlikely scenario where
   `deposit_count > 2^53`.
8. **grandine's separation of dispatchers from `process_operations`**
   — codify as a spec-traceability test that flags any future
   per-spec function definition that doesn't match the call graph.
9. **prysm's per-element nil-checks** — equivalence test against the
   SSZ-level enforcement in other clients.
10. **`MAX_DEPOSIT_REQUESTS_PER_PAYLOAD = 8192` over-the-wire test**
    — block with 8193 deposit requests should be rejected at SSZ
    deserialization across all clients.
11. **Gloas (EIP-7732) dispatcher relocation audit** — both prysm
    (explicit `gloas.go:20–58` removal) and lodestar (`fork < ForkSeq.gloas`
    gate) handle this; verify the Gloas re-implementation in all
    clients matches.
12. **Multi-request-type-same-block ordering** — block with 1 deposit
    + 1 withdrawal + 1 consolidation request all targeting the same
    validator. Test that all 6 clients process in deposit → withdrawal
    → consolidation order, and that state mutations are observable
    in that exact sequence.
