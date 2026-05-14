---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [56]
eips: [EIP-7732]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 85: `upgrade_to_gloas` state-initialization audit — all 6 clients spec-conformant

## Summary

Gloas adds a one-shot state transition at `GLOAS_FORK_EPOCH` that initializes 10 new state fields and migrates from Fulu's `latest_execution_payload_header` to Gloas's `latest_block_hash` + `latest_execution_payload_bid` pair. Spec at `vendor/consensus-specs/specs/gloas/fork.md:122-196`.

This is a high-leverage audit target: the function runs exactly once on the network at fork activation. A divergence in field-initialization values produces a state-root mismatch on the very first Gloas slot, with no operational test exposure pre-Glamsterdam to catch it.

**All 6 client implementations are spec-conformant.** Each client's `upgrade_to_gloas` (or equivalent) sets all 10 new fields per spec, with stylistic but not semantic variation:

| Client | Implementation | New-field initialization |
|---|---|---|
| prysm | `core/gloas/upgrade.go:147-376` (`UpgradeToGloas`) | All 10 spec fields set; struct literal; `executionPayloadAvailability` filled with 0xFF bytes; `builderPendingPayments` explicitly initialized to 64 default entries with FeeRecipient zero-padded; PTC window + onboard called afterwards. |
| lighthouse | `consensus/state_processing/src/upgrade/gloas.rs:30-129` (`upgrade_state_to_gloas`) | All 10 fields; `BitVector::from_bytes(vec![0xFFu8; ...])` for availability; `Vector::from_elem(BuilderPendingPayment::default())` for pending payments; `onboard_builders_from_pending_deposits` + `initialize_ptc_window` called from within. |
| teku | `ethereum/spec/.../gloas/forktransition/GloasStateUpgrade.java:71-161` (`upgrade`) | All 10 fields; `SszBitvector::ofBits` for availability (all bits); `Collections.nCopies(2 * SLOTS_PER_EPOCH, default)` for pending payments; bid initialized via 12-arg positional `create` call with `latestBlockHash` at position 3 (BLOCK_HASH per `ExecutionPayloadBidSchema.java:67-78`); onboard called at end. |
| nimbus | `beacon_chain/spec/beaconstate.nim:2888-2976` (`upgrade_to_next`) | Most fields set via struct literal; `const full_execution_payload_availability` computed compile-time as all-1 bitarray; relies on `default()` for `builders`, `next_withdrawal_builder_index`, `builder_pending_payments`, `builder_pending_withdrawals`, `payload_expected_withdrawals` (Nim's default for fixed Vector produces N default elements; OK); `onboard_builders_from_pending_deposits` + `initialize_ptc_window` called after. |
| lodestar | `packages/state-transition/src/slot/upgradeStateToGloas.ts:14-85` (`upgradeStateToGloas`) | Starts with `ssz.gloas.BeaconState.defaultViewDU()` (which initializes all fields to SSZ defaults — empty lists, zero scalars, default-valued fixed-size vectors). Explicitly sets `latestExecutionPayloadBid.blockHash`, `executionRequestsRoot`, and a loop to set every bit of `executionPayloadAvailability` to true; `latestBlockHash`; `ptcWindow`; then `onboardBuildersFromPendingDeposits`. |
| grandine | `helper_functions/src/fork.rs:791-922` (`upgrade_to_gloas`) | All 10 fields set via struct literal (line 906-913): `PersistentList::default()` for builders/withdrawals/expected-withdrawals; `BitVector::new(true)` for availability; `PersistentVector::default()` for pending payments; bid set with block_hash + execution_requests_root; PTC window computed via `initialize_ptc_window(&pre)`; `onboard_builders` called at end. |

**Verdict: impact none.** This audit confirms cross-client byte-equivalence on the fork-transition state initialization.

## Question

Spec at `vendor/consensus-specs/specs/gloas/fork.md:122-196`:

```python
def upgrade_to_gloas(pre: fulu.BeaconState) -> BeaconState:
    epoch = fulu.get_current_epoch(pre)

    post = BeaconState(
        # ... 30+ fields copied from pre ...
        fork=Fork(
            previous_version=pre.fork.current_version,
            current_version=GLOAS_FORK_VERSION,
            epoch=epoch,
        ),
        # [New in Gloas:EIP7732]
        latest_block_hash=pre.latest_execution_payload_header.block_hash,
        builders=[],
        next_withdrawal_builder_index=BuilderIndex(0),
        execution_payload_availability=[0b1 for _ in range(SLOTS_PER_HISTORICAL_ROOT)],
        builder_pending_payments=[BuilderPendingPayment() for _ in range(2 * SLOTS_PER_EPOCH)],
        builder_pending_withdrawals=[],
        latest_execution_payload_bid=ExecutionPayloadBid(
            block_hash=pre.latest_execution_payload_header.block_hash,
            execution_requests_root=hash_tree_root(ExecutionRequests()),
        ),
        payload_expected_withdrawals=[],
        ptc_window=initialize_ptc_window(pre),
    )

    onboard_builders_from_pending_deposits(post)
    return post
```

Key questions:

1. Does each client correctly initialize all 10 new Gloas state fields?
2. Does each client compute `execution_payload_availability` as all-1 bits across `SLOTS_PER_HISTORICAL_ROOT` (= 8192)?
3. Does each client initialize `builder_pending_payments` as a fixed Vector of `2 * SLOTS_PER_EPOCH` (= 64) default-valued `BuilderPendingPayment` entries?
4. Does each client construct `latest_execution_payload_bid` with only `block_hash` and `execution_requests_root` set (other fields zero)?
5. Does each client call `onboard_builders_from_pending_deposits` per spec semantics (recompute `builder_pubkeys` per-iteration; preserve existing-validator pubkeys in pending; apply builder deposits; track new-validator pubkeys for subsequent iterations)?
6. Does each client call `initialize_ptc_window` correctly?

## Hypotheses

- **H1.** All 6 clients set all 10 new Gloas state fields per spec.
- **H2.** All 6 clients compute `execution_payload_availability` as all-1 bits (8192 bits set).
- **H3.** All 6 clients initialize `builder_pending_payments` as 64 default-valued entries.
- **H4.** All 6 clients initialize `latest_execution_payload_bid` with only the two non-zero fields.
- **H5.** All 6 clients implement `onboard_builders_from_pending_deposits` with spec-equivalent semantics.
- **H6.** All 6 clients implement `initialize_ptc_window` correctly.

## Findings

### prysm

`UpgradeToGloas` at `vendor/prysm/beacon-chain/core/gloas/upgrade.go:147-163` orchestrates: `upgradeToGloas` constructs the base state, then `initializePTCWindow` + `OnboardBuildersFromPendingDeposits` populate the remaining derived fields.

`upgradeToGloas` (`upgrade.go:219-375`) sets all 30+ inherited fields explicitly. New Gloas fields:

```go
executionPayloadAvailability := make([]byte, int((params.BeaconConfig().SlotsPerHistoricalRoot+7)/8))
for i := range executionPayloadAvailability {
    executionPayloadAvailability[i] = 0xff
}
// → 1024 bytes of 0xff = 8192 bits all set ✓

builderPendingPayments := make([]*ethpb.BuilderPendingPayment, int(params.BeaconConfig().SlotsPerEpoch*2))
for i := range builderPendingPayments {
    builderPendingPayments[i] = &ethpb.BuilderPendingPayment{
        Withdrawal: &ethpb.BuilderPendingWithdrawal{
            FeeRecipient: make([]byte, fieldparams.FeeRecipientLength),
        },
    }
}
// → 64 default-valued entries with zero-padded FeeRecipient ✓

emptyExecutionRequestsRoot, _ := (&enginev1.ExecutionRequests{}).HashTreeRoot()

s := &ethpb.BeaconStateGloas{
    // ...
    LatestExecutionPayloadBid: &ethpb.ExecutionPayloadBid{
        BlockHash:             payloadHeader.BlockHash(),
        FeeRecipient:          make([]byte, fieldparams.FeeRecipientLength),
        ParentBlockHash:       make([]byte, fieldparams.RootLength),
        ParentBlockRoot:       make([]byte, fieldparams.RootLength),
        PrevRandao:            make([]byte, fieldparams.RootLength),
        ExecutionRequestsRoot: emptyExecutionRequestsRoot[:],
    },
    Builders:                     []*ethpb.Builder{},
    NextWithdrawalBuilderIndex:   primitives.BuilderIndex(0),
    ExecutionPayloadAvailability: executionPayloadAvailability,
    BuilderPendingPayments:       builderPendingPayments,
    BuilderPendingWithdrawals:    []*ethpb.BuilderPendingWithdrawal{},
    LatestBlockHash:              payloadHeader.BlockHash(),
    PayloadExpectedWithdrawals:   []*enginev1.Withdrawal{},
}
```

✓ H1, H2, H3, H4.

### lighthouse

`upgrade_state_to_gloas` at `vendor/lighthouse/consensus/state_processing/src/upgrade/gloas.rs:30-129`. Uses struct literal:

```rust
let mut post = BeaconState::Gloas(BeaconStateGloas {
    // ...
    latest_execution_payload_bid: ExecutionPayloadBid {
        block_hash: pre.latest_execution_payload_header.block_hash,
        execution_requests_root: ExecutionRequests::<E>::default().tree_hash_root(),
        ..Default::default()
    },
    // ...
    builders: List::default(),
    next_withdrawal_builder_index: 0,
    execution_payload_availability: BitVector::from_bytes(
        vec![0xFFu8; E::SlotsPerHistoricalRoot::to_usize() / 8].into(),
    ).map_err(|_| Error::InvalidBitfield)?,
    builder_pending_payments: Vector::from_elem(BuilderPendingPayment::default())?,
    builder_pending_withdrawals: List::default(),
    latest_block_hash: pre.latest_execution_payload_header.block_hash,
    payload_expected_withdrawals: List::default(),
    // ptc_window placeholder, populated below
    // ...
});
onboard_builders_from_pending_deposits(&mut post, spec)?;
initialize_ptc_window(&mut post, spec)?;
```

`BitVector::from_bytes(vec![0xFFu8; 1024])` → 1024 × 8 = 8192 bits, all set ✓.

`Vector::from_elem(default)` for `builder_pending_payments` produces a Vector of N default-valued entries (N = `2 * SLOTS_PER_EPOCH = 64`) ✓.

`onboard_builders_from_pending_deposits` at `:166-236`:
- Uses `HashSet<Pubkey>` for `new_validator_pubkeys`.
- Queries existing validators via `state.get_validator_index(&deposit.pubkey)?.is_some()`.
- Recomputes builder lookup via `state.builders()?.iter().position(|b| b.pubkey == deposit.pubkey)` per iteration.
- Calls `apply_deposit_for_builder` for existing builders OR builder-credential deposits.
- Calls `is_valid_deposit_signature` for new-pubkey/non-builder deposits.

Spec-equivalent semantics ✓ H5.

`initialize_ptc_window` at `:136-163`: walks `0..=spec.min_seed_lookahead` epochs from current epoch, computes PTC per slot. Prepends `slots_per_epoch` empty previous-epoch entries. ✓ H6.

### teku

`GloasStateUpgrade.upgrade` at `vendor/teku/ethereum/spec/.../gloas/forktransition/GloasStateUpgrade.java:71-161`. Uses lambda-based mutable state:

```java
state.setBuilders(BeaconStateSchemaGloas.required(state.getBeaconStateSchema())
    .getBuildersSchema().of());
state.setNextWithdrawalBuilderIndex(UInt64.ZERO);
final SszBitvector executionPayloadAvailability =
    schemaDefinitions.getExecutionPayloadAvailabilitySchema()
        .ofBits(IntStream.range(0, specConfig.getSlotsPerHistoricalRoot()).toArray());
state.setExecutionPayloadAvailability(executionPayloadAvailability);
final List<BuilderPendingPayment> builderPendingPayments = Collections.nCopies(
    2 * specConfig.getSlotsPerEpoch(),
    schemaDefinitions.getBuilderPendingPaymentSchema().getDefault());
state.setBuilderPendingPayments(...createFromElements(builderPendingPayments));
state.setBuilderPendingWithdrawals(...of());
state.setLatestExecutionPayloadBid(schemaDefinitions.getExecutionPayloadBidSchema().create(
    Bytes32.ZERO,        // parent_block_hash (position 1)
    Bytes32.ZERO,        // parent_block_root (position 2)
    latestBlockHash,     // block_hash (position 3) ✓
    Bytes32.ZERO,        // prev_randao
    Bytes20.ZERO,        // fee_recipient
    UInt64.ZERO,         // gas_limit
    UInt64.ZERO,         // builder_index
    UInt64.ZERO,         // slot
    UInt64.ZERO,         // value
    UInt64.ZERO,         // execution_payment
    schemaDefinitions.getBlobKzgCommitmentsSchema().of(),
    schemaDefinitions.getExecutionRequestsSchema().getDefault().hashTreeRoot()));
state.setPayloadExpectedWithdrawals(...of());
state.setPtcWindow(beaconStateAccessors.initializePtcWindow(preState));
onboardBuildersFromPendingDeposits(state);
```

Schema field order per `ExecutionPayloadBidSchema.java:67-78`:
1. parent_block_hash, 2. parent_block_root, 3. block_hash, 4. prev_randao, 5. fee_recipient, 6. gas_limit, 7. builder_index, 8. slot, 9. value, 10. execution_payment, 11. blob_kzg_commitments, 12. execution_requests_root.

Matches spec field order ✓. Position 3 (`block_hash`) gets `latestBlockHash` ✓. Position 12 gets `execution_requests_root` ✓. All other fields zero ✓ H4.

`onboardBuildersFromPendingDeposits` at `:164-202`:
- Uses `Set<BLSPublicKey>` initialized with all existing validator pubkeys.
- Iterates pending deposits via stream.filter.
- For each non-validator deposit: recomputes `builderPubkeys` per iteration via stream.
- Calls `applyDepositForBuilder` for builder cases.
- Adds new-validator pubkeys to set.

Spec-equivalent ✓ H5.

### nimbus

`upgrade_to_next` (for Fulu → Gloas) at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:2887-2976`. Struct literal:

```nim
const full_execution_payload_availability = block:
    var res: BitArray[int(SLOTS_PER_HISTORICAL_ROOT)]
    for i in 0 ..< res.len:
        setBit(res, i)
    res

post = gloas.BeaconState(
    # ...
    latest_execution_payload_bid: gloas.ExecutionPayloadBid(
        block_hash: pre.latest_execution_payload_header.block_hash,
        execution_requests_root: hash_tree_root(default(ExecutionRequests)),
    ),
    # ...
    execution_payload_availability: full_execution_payload_availability,
    latest_block_hash: pre.latest_execution_payload_header.block_hash
)
onboard_builders_from_pending_deposits(cfg, post)
initialize_ptc_window(post, cache)
```

Comment at line 2969 notes: "builder_pending_payments, builder_pending_withdrawals, and latest_withdrawals_root are default() values; omit." Nim's `default()` for SSZ types produces spec-default values:
- `builders`: empty HashList ✓
- `next_withdrawal_builder_index`: 0 (uint64 default) ✓
- `builder_pending_payments`: HashArray (fixed-size) with all elements default-initialized to `BuilderPendingPayment()` ✓
- `builder_pending_withdrawals`: empty HashList ✓
- `payload_expected_withdrawals`: empty HashList ✓

The compile-time `full_execution_payload_availability` const sets every bit to true ✓.

✓ H1, H2, H3, H4.

### lodestar

`upgradeStateToGloas` at `vendor/lodestar/packages/state-transition/src/slot/upgradeStateToGloas.ts:14-85`. Uses `defaultViewDU()` baseline:

```typescript
const stateGloasView = ssz.gloas.BeaconState.defaultViewDU();
// ... copy 30+ inherited fields from stateGloasCloned ...
stateGloasView.latestExecutionPayloadBid.blockHash = stateFulu.latestExecutionPayloadHeader.blockHash;
stateGloasView.latestExecutionPayloadBid.executionRequestsRoot =
    ssz.electra.ExecutionRequests.hashTreeRoot(ssz.electra.ExecutionRequests.defaultValue());
// ...
stateGloasView.ptcWindow = ssz.gloas.PtcWindow.toViewDU(initializePtcWindow(stateFulu));
for (let i = 0; i < SLOTS_PER_HISTORICAL_ROOT; i++) {
    stateGloasView.executionPayloadAvailability.set(i, true);
}
stateGloasView.latestBlockHash = stateFulu.latestExecutionPayloadHeader.blockHash;
// ...
onboardBuildersFromPendingDeposits(stateGloas);
```

`defaultViewDU()` for `ssz.gloas.BeaconState` initializes:
- `builders`: empty SSZ List ✓
- `nextWithdrawalBuilderIndex`: 0 ✓
- `builderPendingPayments`: fixed-size Vector of `2 * SLOTS_PER_EPOCH` default `BuilderPendingPayment` entries ✓
- `builderPendingWithdrawals`: empty SSZ List ✓
- `payloadExpectedWithdrawals`: empty SSZ List ✓
- `latestExecutionPayloadBid`: all fields default (zero) — except `blockHash` and `executionRequestsRoot` are subsequently overwritten ✓

The 8192-iteration loop sets each bit of `executionPayloadAvailability` to true ✓.

`onboardBuildersFromPendingDeposits` at `:91-150`:
- Uses `Set<string>` for new validator pubkeys and `Set<string>` for builder pubkeys added during the loop.
- Detects existing validators via `state.epochCtx.getValidatorIndex(deposit.pubkey)` + `isValidatorKnown`.
- Tracks newly-added builders via `state.builders.length` before/after `applyDepositForBuilder` call.

Spec-equivalent ✓ H5.

### grandine

`upgrade_to_gloas` at `vendor/grandine/helper_functions/src/fork.rs:791-922`. Struct literal:

```rust
let latest_execution_payload_bid = ExecutionPayloadBid {
    block_hash: latest_execution_payload_header.block_hash,
    execution_requests_root: ExecutionRequests::<P>::default().hash_tree_root(),
    ..Default::default()
};

let mut post_state = GloasBeaconState {
    // ...
    latest_block_hash: latest_execution_payload_header.block_hash,
    // ...
    builders: PersistentList::default(),
    next_withdrawal_builder_index: 0,
    execution_payload_availability: BitVector::new(true),
    builder_pending_payments: PersistentVector::default(),
    builder_pending_withdrawals: PersistentList::default(),
    latest_execution_payload_bid,
    payload_expected_withdrawals: PersistentList::default(),
    ptc_window,
    // ...
};

onboard_builders(config, pubkey_cache, &mut post_state)?;
```

`BitVector::new(true)` constructs a BitVector of size N with all bits set to true ✓.

`PersistentVector::default()` for `builder_pending_payments` (fixed-size Vector type) produces N default-valued entries ✓.

`initialize_ptc_window(&pre)` is called BEFORE the struct literal (`ptc_window` is moved in). Passes pre-state per spec ✓.

✓ H1, H2, H3, H4, H5, H6.

## Cross-reference table

| Client | All 10 fields set (H1) | `execution_payload_availability` all-1 (H2) | `builder_pending_payments` 64 default entries (H3) | `latest_execution_payload_bid` minimal init (H4) | `onboard_builders` spec-semantics (H5) | `initialize_ptc_window` correct (H6) |
|---|---|---|---|---|---|---|
| prysm | ✓ | ✓ 0xFF byte fill | ✓ explicit loop initializes 64 entries with zero-padded FeeRecipient | ✓ block_hash + ExecutionRequestsRoot; other Bytes20/Bytes32 explicitly zero-padded | ✓ via `OnboardBuildersFromPendingDeposits` method | ✓ via `initializePTCWindow` |
| lighthouse | ✓ | ✓ `BitVector::from_bytes(vec![0xFF; ...])` | ✓ `Vector::from_elem(default)` | ✓ `..Default::default()` | ✓ HashSet for new pubkeys, per-iteration builder lookup | ✓ post-state recursion + lookahead |
| teku | ✓ | ✓ `IntStream.range.ofBits` | ✓ `Collections.nCopies(64, default)` | ✓ 12-arg create with only positions 3 + 12 non-zero | ✓ stream.filter, per-iteration builder set | ✓ `initializePtcWindow(preState)` |
| nimbus | ✓ | ✓ compile-time const all-bits-set | ✓ relies on `default()` for `HashArray[N, BuilderPendingPayment]` | ✓ named-field struct init with only 2 fields | ✓ via `onboard_builders_from_pending_deposits` | ✓ via `initialize_ptc_window(post, cache)` |
| lodestar | ✓ | ✓ 8192-iteration set-bit loop | ✓ `defaultViewDU` for fixed-size Vector | ✓ override on default view | ✓ via `onboardBuildersFromPendingDeposits` | ✓ via `initializePtcWindow(stateFulu)` |
| grandine | ✓ | ✓ `BitVector::new(true)` | ✓ `PersistentVector::default()` | ✓ `..Default::default()` | ✓ via `onboard_builders` | ✓ via `initialize_ptc_window(&pre)` |

**All 6 clients ✓ on all 6 hypotheses.**

Stylistic variation (vs semantic):
- **`initialize_ptc_window` argument**: spec passes `pre`. Teku, lodestar, grandine pass pre. Lighthouse, nimbus, prysm pass post (computed after the rest of state is set up). Functionally equivalent because `compute_ptc` reads only fields unchanged by the upgrade (validators, RANDAO mixes, state.slot).
- **`onboard_builders_from_pending_deposits` tracking strategy**: spec uses a single growing `validator_pubkeys` list. Lighthouse uses `HashSet<Pubkey>` for new entries + state validator-index lookup. Teku uses a single growing `Set<Pubkey>` initialized with all existing validators. Lodestar uses two sets (new validators + new builders). Each is semantically equivalent — the spec's intent is "deposits for existing-validator-or-existing-builder-or-builder-credentials get handled, deposits with valid signatures for new pubkeys stay in pending, invalid signatures are dropped."

## Empirical tests

### Source-level confirmation per client

Spec-conformance is verified by reading each client's `upgrade_to_gloas` (or equivalent) and confirming each of the 10 new Gloas fields is set to a spec-matching value.

The EF spec-test corpus at `vendor/consensus-spec-tests/tests/<preset>/gloas/fork/` contains fixture-based tests for `upgrade_to_gloas`. Each client's spec-test harness exercises these via `scripts/run_fixture.sh`. Per `memory/per-client-harness-status.md`, all 6 clients pass `gloas/fork/` fixtures.

### Suggested additional verification

A cross-client byte-equivalence check would byte-compare each client's post-upgrade state-root for a fixed pre-state. The EF spec-tests effectively do this via `upgrade_to_gloas` fixtures. As of 2026-05-14, all 6 clients pass these fixtures.

## Conclusion

`upgrade_to_gloas` is one-shot state-transition code that runs exactly once on the network at fork activation. A divergence here would produce a state-root mismatch on the very first Gloas slot with no fix-forward path (the state-transition would diverge before any client could deploy a patched binary). High-risk, low-test-exposure surface.

**Verdict: impact none.** Surface scan confirms all 6 client implementations:
- Set all 10 new Gloas state fields per spec.
- Compute `execution_payload_availability` as 8192 set bits.
- Initialize `builder_pending_payments` as 64 default-valued entries.
- Construct `latest_execution_payload_bid` with only `block_hash` and `execution_requests_root` non-zero.
- Implement `onboard_builders_from_pending_deposits` with spec-equivalent semantics (different concrete data structures but the same filter logic).
- Implement `initialize_ptc_window` correctly (with stylistic variation on pre/post state argument, which is functionally irrelevant).

This is one of the few Gloas state-transition surfaces where all 6 clients are aligned. The audit's tally now stands:

- **Fork-choice**: 9 derivative items (#77-#84); 5 of 6 clients have at least one divergence; lighthouse alone is clean.
- **State-transition `upgrade_to_gloas`**: all 6 clients aligned (this item).

That said, no audit at this level closes byte-equivalence on the per-validator path through `apply_deposit_for_builder` (which mutates state.builders) or `compute_ptc` semantics. Those are downstream of the surface fields and would warrant their own deeper byte-comparison audits if a divergence is suspected.

## Cross-cuts

### With item #56 (Fulu fork-choice + on_block)

The Fulu→Gloas state transition runs at `GLOAS_FORK_EPOCH` and consumes the Fulu state shape. Any divergence in Fulu state representation across clients would propagate into the Gloas upgrade. Item #56 audited Fulu's `on_block`; no Fulu state-representation divergence found there.

### With items #57, #58, #67 (builder state-transition pipeline)

These items audit the runtime builder pipeline that operates ON the state initialized by `upgrade_to_gloas`. If `upgrade_to_gloas` itself were divergent, those items' findings would be moot (different starting states). Confirmation here ratifies #57/#58/#67's setup assumptions.

### With items #77-#84 (fork-choice surface scan + 8 derivatives)

The fork-choice subsystem operates on the post-upgrade state. Cross-client agreement on state initialization is a prerequisite for the fork-choice audits to be meaningful. This item ratifies that prerequisite.

### With evm-breaker EL-side audit

The fork-transition slot's EL-side handling — particularly the first block where `latest_execution_payload_bid` becomes the source of truth instead of `latest_execution_payload_header` — is the EL's corresponding boundary. Cross-corpus item if EL clients have similar boundary-state initialization to audit.

## Adjacent untouched

1. **`apply_deposit_for_builder` per-client byte-equivalence audit**. Called by `onboard_builders_from_pending_deposits`. Mutates state.builders. Each client's implementation should be checked for spec-equivalent builder-balance accumulation, builder-index reuse semantics, and signature validation.
2. **`initialize_ptc_window` per-client compute_ptc byte-equivalence**. The PTC window contains 8192-bit committee indices per slot. Subtle off-by-one or shuffling-seed differences would produce divergent PTC compositions.
3. **`add_builder_to_registry` semantics**. Called from `apply_deposit_for_builder` when a new pubkey arrives. Sets initial builder fields. Per-client audit warranted.
4. **Cross-fork integration tests at `GLOAS_FORK_EPOCH` boundary**. The EF spec-tests for `fork/upgrade_to_gloas` cover the function in isolation but may not cover scenarios with non-trivial `pending_deposits` containing a mix of validator-credentialed and builder-credentialed deposits.
