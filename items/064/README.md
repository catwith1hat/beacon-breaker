---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [22, 23, 28, 57, 60, 63]
eips: [EIP-7732, EIP-8061]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 64: `upgrade_to_gloas` fork-upgrade migration

## Summary

All six clients implement `upgrade_to_gloas` (consensus-specs `fork.md:121-197`) consistently and spec-conformantly. Each carries forward every Fulu state field unchanged, drops `latest_execution_payload_header` in favor of the new `latest_block_hash` + `latest_execution_payload_bid` fields, populates the seven Gloas-new fields (`builders`, `next_withdrawal_builder_index`, `execution_payload_availability` as all-1 bits, `builder_pending_payments` as 2×SLOTS_PER_EPOCH defaults, `builder_pending_withdrawals` as empty list, `latest_execution_payload_bid` with `block_hash` carryover + `hash_tree_root(ExecutionRequests())` for `execution_requests_root`, and `payload_expected_withdrawals` as empty list), initializes `ptc_window` via `initialize_ptc_window` (96 rows on mainnet: 32 zero rows + 2×32 PTC rows), and onboards builders from pending deposits via `onboard_builders_from_pending_deposits`.

**One literal ordering deviation, functionally equivalent**: lighthouse (`upgrade/gloas.rs:124-126`) and nimbus (`beaconstate.nim:2974-2975`) call `onboard_builders_from_pending_deposits` **before** `initialize_ptc_window`; the spec (`fork.md:189-194`) calls `initialize_ptc_window` first (as part of the BeaconState constructor) and `onboard_builders_from_pending_deposits` second. The two functions operate on disjoint state slices — `initialize_ptc_window` reads `state.validators` / `state.randao_mixes` / `state.slot` (PTC seed + balance-weighted selection); `onboard_builders` mutates `state.pending_deposits` and `state.builders` only — so order swap produces byte-identical post-state. No reachable input distinguishes the two orders.

Nimbus's PR #4513 → PR #4788 revert-window history (items #22 + #23, both fixed in PR #8440 `550c7a3f0`) suggested this was the highest-risk Gloas area; the audit confirms the fix landed cleanly and no parallel alpha-drift bug exists in the upgrade path. **Verdict: impact none.**

## Question

Pyspec `upgrade_to_gloas` at `vendor/consensus-specs/specs/gloas/fork.md:121-197`:

```python
def upgrade_to_gloas(pre: fulu.BeaconState) -> BeaconState:
    epoch = fulu.get_current_epoch(pre)

    post = BeaconState(
        # ... 30+ carryover fields from Fulu (validators, balances, randao_mixes, ...)
        fork=Fork(
            previous_version=pre.fork.current_version,
            current_version=GLOAS_FORK_VERSION,         # [Modified Gloas:EIP7732]
            epoch=epoch,
        ),
        # [Removed Gloas:EIP7732] latest_execution_payload_header
        latest_block_hash=pre.latest_execution_payload_header.block_hash,  # [New Gloas:EIP7732]
        # [New Gloas:EIP7732] fields:
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
        ptc_window=initialize_ptc_window(pre),         # [New Gloas:EIP7732]
    )

    # [New Gloas:EIP7732]
    onboard_builders_from_pending_deposits(post)

    return post
```

Spec `initialize_ptc_window` at `fork.md:36-56`:

```python
def initialize_ptc_window(
    state: BeaconState,
) -> Vector[Vector[ValidatorIndex, PTC_SIZE], (2 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH]:
    empty_previous_epoch = [
        Vector[ValidatorIndex, PTC_SIZE]([ValidatorIndex(0) for _ in range(PTC_SIZE)])
        for _ in range(SLOTS_PER_EPOCH)
    ]
    ptcs = []
    current_epoch = get_current_epoch(state)
    for e in range(1 + MIN_SEED_LOOKAHEAD):
        epoch = Epoch(current_epoch + e)
        start_slot = compute_start_slot_at_epoch(epoch)
        ptcs += [compute_ptc(state, Slot(start_slot + i)) for i in range(SLOTS_PER_EPOCH)]
    return empty_previous_epoch + ptcs
```

Spec `onboard_builders_from_pending_deposits` at `fork.md:61-107`:

```python
def onboard_builders_from_pending_deposits(state: BeaconState) -> None:
    validator_pubkeys = [v.pubkey for v in state.validators]
    pending_deposits = []
    for deposit in state.pending_deposits:
        if deposit.pubkey in validator_pubkeys:
            pending_deposits.append(deposit)
            continue
        builder_pubkeys = [b.pubkey for b in state.builders]   # re-read each iter (mutable)
        is_existing_builder = deposit.pubkey in builder_pubkeys
        has_builder_credentials = is_builder_withdrawal_credential(deposit.withdrawal_credentials)
        if is_existing_builder or has_builder_credentials:
            apply_deposit_for_builder(state, deposit.pubkey, ..., deposit.slot)
            continue
        if is_valid_deposit_signature(deposit.pubkey, ..., deposit.signature):
            validator_pubkeys.append(deposit.pubkey)
            pending_deposits.append(deposit)
    state.pending_deposits = pending_deposits
```

Configuration: `GLOAS_FORK_VERSION = 0x07000000`, `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` (mainnet, override on custom configs).

Open questions before source review:

1. **Field-init order** — spec uses keyword constructor; per-client may use explicit setter chains. Verify all fields get the same value.
2. **`execution_payload_availability` bitvector init** — spec is "all 1s" (past payloads are by definition available). Per-client representation: `vec![0xFF; len/8]`, individual setBit, etc.
3. **`latest_execution_payload_bid` default fields** — spec sets only `block_hash` and `execution_requests_root`; other fields default. Per-client zero-equivalents.
4. **`onboard_builders` ordering** — spec runs AFTER `initialize_ptc_window`; per-client may swap.
5. **`initialize_ptc_window` input** — spec passes `pre` (the Fulu state); per-client may pass `post` (the partially-built Gloas state).

## Hypotheses

- **H1.** All six clients carry forward every Fulu field unchanged (validators, balances, randao_mixes, slashings, participation, finality, sync committees, Capella/Electra/Fulu-specific fields).
- **H2.** All six update `fork`: `previous_version` ← `pre.fork.current_version`, `current_version` ← `GLOAS_FORK_VERSION`, `epoch` ← `current_epoch`.
- **H3.** All six set `latest_block_hash` ← `pre.latest_execution_payload_header.block_hash` (replacing `latest_execution_payload_header`).
- **H4.** All six initialize `execution_payload_availability` as all-1 bits (SLOTS_PER_HISTORICAL_ROOT bits).
- **H5.** All six initialize `builder_pending_payments` as 2*SLOTS_PER_EPOCH default-`BuilderPendingPayment` entries.
- **H6.** All six initialize `builders`, `builder_pending_withdrawals`, `payload_expected_withdrawals` as empty lists.
- **H7.** All six initialize `latest_execution_payload_bid` with `block_hash = pre.latest_execution_payload_header.block_hash`, `execution_requests_root = hash_tree_root(ExecutionRequests::default())`, all other fields default-zero.
- **H8.** All six call `initialize_ptc_window` and produce a 96-row (mainnet: `(2 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH`) PTC window with the first 32 rows being all-zero ValidatorIndex vectors.
- **H9.** All six call `onboard_builders_from_pending_deposits` and produce identical `state.builders` + `state.pending_deposits` post-state.
- **H10** *(forward-fragility)*. `onboard_builders` re-reads `state.builders` each iteration since `apply_deposit_for_builder` may extend the registry — per-client preserves this iteration semantic.
- **H11** *(literal-vs-functional)*. Spec calls `initialize_ptc_window` BEFORE `onboard_builders_from_pending_deposits`. Some clients may swap. Functionally equivalent if the input slices to each function are disjoint.

## Findings

All six clients implement `upgrade_to_gloas` spec-conformantly. Two clients (lighthouse, nimbus) swap the `onboard_builders` / `initialize_ptc_window` ordering — functionally equivalent.

### prysm

Orchestrator at `vendor/prysm/beacon-chain/core/gloas/upgrade.go:147-163`:

```go
func UpgradeToGloas(beaconState state.BeaconState) (state.BeaconState, error) {
    s, err := upgradeToGloas(beaconState)
    if err != nil { return nil, errors.Wrap(err, "could not convert to gloas") }
    ptcWindow, err := initializePTCWindow(context.Background(), s)
    if err != nil { return nil, errors.Wrap(err, "failed to initialize ptc window") }
    if err := s.SetPTCWindow(ptcWindow); err != nil { return nil, ... }
    if err := s.OnboardBuildersFromPendingDeposits(); err != nil { return nil, ... }
    return s, nil
}
```

Order: state-struct construction → PTC window → onboard builders. **Matches spec order.**

State-struct construction at `upgrade.go:219-374`. Carries forward every Fulu field; sets:
- `Fork{Previous: pre.fork.Current, Current: GloasForkVersion, Epoch: CurrentEpoch(state)}` (lines 320-324).
- `execution_payload_availability` initialized as `0xFF` bytes for `(SLOTS_PER_HISTORICAL_ROOT + 7) / 8` bytes — all-1 bits (lines 297-300).
- `builder_pending_payments` as `SLOTS_PER_EPOCH * 2` default `BuilderPendingPayment` entries with zeroed `FeeRecipient` (lines 302-309).
- `latest_execution_payload_bid` with `BlockHash: payloadHeader.BlockHash()`, `ExecutionRequestsRoot: emptyExecutionRequestsRoot[:]`, all other fields zero-buffers (lines 345-352).
- `LatestBlockHash: payloadHeader.BlockHash()` (line 371).
- `Builders: []`, `BuilderPendingWithdrawals: []`, `PayloadExpectedWithdrawals: []` (lines 366, 370, 372).

`initializePTCWindow` at `upgrade.go:189-217`:

```go
func initializePTCWindow(ctx context.Context, st state.ReadOnlyBeaconState) ([]*ethpb.PTCs, error) {
    currentEpoch := slots.ToEpoch(st.Slot())
    slotsPerEpoch := params.BeaconConfig().SlotsPerEpoch
    windowSize := slotsPerEpoch.Mul(uint64(2 + params.BeaconConfig().MinSeedLookahead))
    window := make([]*ethpb.PTCs, 0, windowSize)
    // Previous epoch has no cached data at fork time — fill with empty slots.
    for range slotsPerEpoch {
        window = append(window, &ethpb.PTCs{
            ValidatorIndices: make([]primitives.ValidatorIndex, fieldparams.PTCSize),
        })
    }
    // Compute PTC for current epoch through lookahead.
    startSlot, err := slots.EpochStart(currentEpoch)
    if err != nil { return nil, err }
    totalSlots := slotsPerEpoch.Mul(uint64(1 + params.BeaconConfig().MinSeedLookahead))
    for i := range totalSlots {
        ptc, err := computePTC(ctx, st, startSlot+i)
        if err != nil { return nil, err }
        window = append(window, &ethpb.PTCs{ValidatorIndices: ptc})
    }
    return window, nil
}
```

Matches spec: 32 zero-PTC rows + 64 computed PTC rows = 96 rows on mainnet. ✓

EF spec-test runner at `vendor/prysm/testing/spectest/shared/gloas/fork/upgrade_to_gloas.go` exercises this directly.

### lighthouse

Orchestrator at `vendor/lighthouse/consensus/state_processing/src/upgrade/gloas.rs:30-129`:

```rust
pub fn upgrade_state_to_gloas<E: EthSpec>(
    pre_state: &mut BeaconState<E>,
    spec: &ChainSpec,
) -> Result<BeaconState<E>, Error> {
    let epoch = pre_state.current_epoch();
    let pre = pre_state.as_fulu_mut()?;
    let mut post = BeaconState::Gloas(BeaconStateGloas {
        // ... 30+ fields carried forward via mem::take or clone ...
        fork: Fork {
            previous_version: pre.fork.current_version,
            current_version: spec.gloas_fork_version,
            epoch,
        },
        latest_execution_payload_bid: ExecutionPayloadBid {
            block_hash: pre.latest_execution_payload_header.block_hash,
            execution_requests_root: ExecutionRequests::<E>::default().tree_hash_root(),
            ..Default::default()
        },
        builders: List::default(),
        next_withdrawal_builder_index: 0,
        execution_payload_availability: BitVector::from_bytes(
            vec![0xFFu8; E::SlotsPerHistoricalRoot::to_usize() / 8].into(),
        ).map_err(|_| Error::InvalidBitfield)?,
        builder_pending_payments: Vector::from_elem(BuilderPendingPayment::default())?,
        builder_pending_withdrawals: List::default(),
        latest_block_hash: pre.latest_execution_payload_header.block_hash,
        payload_expected_withdrawals: List::default(),
        ptc_window: Vector::from_elem(FixedVector::from_elem(0))?, // placeholder, init below
        // ... caches ...
    });
    // [New in Gloas:EIP7732]
    onboard_builders_from_pending_deposits(&mut post, spec)?;
    initialize_ptc_window(&mut post, spec)?;

    Ok(post)
}
```

**Order-swap (H11)**: `onboard_builders_from_pending_deposits` is called BEFORE `initialize_ptc_window`. Spec orders these the other way (PTC first via the constructor call). Functionally equivalent because `onboard_builders` mutates only `state.pending_deposits` and `state.builders` (and the latter is empty when `initialize_ptc_window` runs anyway — it would not read `state.builders`).

`initialize_ptc_window` at `gloas.rs:136-163`:

```rust
fn initialize_ptc_window<E: EthSpec>(state: &mut BeaconState<E>, spec: &ChainSpec) -> Result<(), Error> {
    let slots_per_epoch = E::slots_per_epoch() as usize;
    let empty_previous_epoch = vec![FixedVector::<u64, E::PTCSize>::from_elem(0); slots_per_epoch];
    let mut ptcs = empty_previous_epoch;
    let current_epoch = state.current_epoch();
    for e in 0..=spec.min_seed_lookahead.as_u64() {
        let epoch = current_epoch.safe_add(e)?;
        let committee_cache = state.initialize_committee_cache_for_lookahead(epoch, spec)?;
        let start_slot = epoch.start_slot(E::slots_per_epoch());
        for i in 0..slots_per_epoch {
            let slot = start_slot.safe_add(i as u64)?;
            let ptc = state.compute_ptc_with_cache(slot, &committee_cache, spec)?;
            // ... push entry ...
        }
    }
    *state.ptc_window_mut()? = Vector::new(ptcs)?;
    Ok(())
}
```

Matches spec semantics; uses `initialize_committee_cache_for_lookahead` as an optimization (single cache per epoch, reused across slots).

`onboard_builders_from_pending_deposits` at `gloas.rs:166-236`. Mirrors spec; **optimization**: uses `state.get_validator_index(pubkey)` (efficient lookup) instead of the spec's `if deposit.pubkey in validator_pubkeys` linear scan. Tracks `new_validator_pubkeys: HashSet` to capture pubkeys added mid-iteration. The TODO comment at line 191 (`linear scan could be optimized, see github issue #8783`) flags this as a known performance hotspot for the builders re-scan.

### teku

`GloasStateUpgrade` at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/forktransition/GloasStateUpgrade.java:71-161`:

```java
@Override
public BeaconStateGloas upgrade(final BeaconState preState) {
  final UInt64 epoch = beaconStateAccessors.getCurrentEpoch(preState);
  final BeaconStateFulu preStateFulu = BeaconStateFulu.required(preState);

  return BeaconStateGloas.required(schemaDefinitions.getBeaconStateSchema().createEmpty())
      .updatedGloas(state -> {
        BeaconStateFields.copyCommonFieldsFromSource(state, preState);
        state.setFork(new Fork(
            preState.getFork().getCurrentVersion(),
            specConfig.getGloasForkVersion(),
            epoch));
        // ... carries forward sync committees, participation, inactivity, withdrawals, etc. ...
        state.setLatestBlockHash(latestBlockHash);
        // ... Capella / Electra / Fulu carryover fields ...
        state.setBuilders(...getBuildersSchema().of());                            // empty list
        state.setNextWithdrawalBuilderIndex(UInt64.ZERO);
        final SszBitvector executionPayloadAvailability =
            schemaDefinitions.getExecutionPayloadAvailabilitySchema()
                .ofBits(IntStream.range(0, specConfig.getSlotsPerHistoricalRoot()).toArray());
        state.setExecutionPayloadAvailability(executionPayloadAvailability);
        final List<BuilderPendingPayment> builderPendingPayments =
            Collections.nCopies(2 * specConfig.getSlotsPerEpoch(),
                schemaDefinitions.getBuilderPendingPaymentSchema().getDefault());
        state.setBuilderPendingPayments(...);
        state.setBuilderPendingWithdrawals(...getBuilderPendingWithdrawalsSchema().of());
        state.setLatestExecutionPayloadBid(
            schemaDefinitions.getExecutionPayloadBidSchema()
                .create(Bytes32.ZERO, Bytes32.ZERO, latestBlockHash, Bytes32.ZERO,
                        Bytes20.ZERO, UInt64.ZERO, UInt64.ZERO, UInt64.ZERO, UInt64.ZERO, UInt64.ZERO,
                        schemaDefinitions.getBlobKzgCommitmentsSchema().of(),
                        schemaDefinitions.getExecutionRequestsSchema().getDefault().hashTreeRoot()));
        state.setPayloadExpectedWithdrawals(
            schemaDefinitions.getExecutionPayloadSchema().getWithdrawalsSchemaRequired().of());
        state.setPtcWindow(beaconStateAccessors.initializePtcWindow(preState));
        onboardBuildersFromPendingDeposits(state);
      });
}
```

Order: PTC window first, then onboard. **Matches spec order.**

`executionPayloadAvailability`: `ofBits(IntStream.range(0, SLOTS_PER_HISTORICAL_ROOT).toArray())` — explicitly sets every bit to 1. ✓

`latestExecutionPayloadBid`: all fields enumerated explicitly with `Bytes32.ZERO` / `Bytes20.ZERO` / `UInt64.ZERO` for default-equivalent values; `latestBlockHash` for `blockHash`; `getExecutionRequestsSchema().getDefault().hashTreeRoot()` for `executionRequestsRoot`. ✓

`onboardBuildersFromPendingDeposits` at lines 164-202. Mirrors spec; uses `.stream().filter()` for the iteration; **re-reads `state.builders` inside the filter** (line 174-177) — matches spec's "must be recomputed each iteration" semantic. ✓

### nimbus

`upgrade_to_next` at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:2887-2976`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.7.0-alpha.5/specs/gloas/fork.md#upgrading-the-state
# upgrade_to_gloas
func upgrade_to_next*(
    cfg: RuntimeConfig, pre: fulu.BeaconState, cache: var StateCache):
    gloas.BeaconState =
  let epoch = get_current_epoch(pre)

  const full_execution_payload_availability = block:
    var res: BitArray[int(SLOTS_PER_HISTORICAL_ROOT)]
    for i in 0 ..< res.len:
      setBit(res, i)
    res

  template post: untyped = result
  post = gloas.BeaconState(
    # ... 30+ carryover fields ...
    fork: Fork(
      previous_version: pre.fork.current_version,
      current_version: cfg.GLOAS_FORK_VERSION,
      epoch: epoch
    ),
    latest_execution_payload_bid: gloas.ExecutionPayloadBid(
      block_hash: pre.latest_execution_payload_header.block_hash,
      execution_requests_root: hash_tree_root(default(ExecutionRequests)),
    ),
    # ... Capella/Electra/Fulu carryover ...
    # [New in Gloas:EIP7732]
    # builder_pending_payments, builder_pending_withdrawals, and
    # latest_withdrawals_root are default() values; omit.
    execution_payload_availability: full_execution_payload_availability,
    latest_block_hash: pre.latest_execution_payload_header.block_hash
  )
  onboard_builders_from_pending_deposits(cfg, post)
  initialize_ptc_window(post, cache)
```

`full_execution_payload_availability` built at compile time via `setBit` loop ✓ (line 2894-2897). The comment "builder_pending_payments, builder_pending_withdrawals, and latest_withdrawals_root are default() values; omit" relies on nim's `gloas.BeaconState()` constructor zero-initializing unspecified fields — verified equivalent to spec defaults:
- `builder_pending_payments: Vector[BuilderPendingPayment, 2*SLOTS_PER_EPOCH]` → default is fixed-size vector of default `BuilderPendingPayment` ✓
- `builder_pending_withdrawals: List[..., MAX_BUILDER_PENDING_WITHDRAWALS]` → default is empty list ✓
- `payload_expected_withdrawals: List[Withdrawal, MAX_WITHDRAWALS_PER_PAYLOAD]` → default is empty list ✓

**Order-swap (H11)**: `onboard_builders_from_pending_deposits(cfg, post)` is called BEFORE `initialize_ptc_window(post, cache)` (lines 2974-2975). Functionally equivalent (same argument as lighthouse).

Helper `onboard_builders_from_pending_deposits` at `beaconstate.nim:2260` (header), `initialize_ptc_window` at `beaconstate.nim:2368` (header). Both spec-conformant.

EF tests pass per `vendor/nimbus/ConsensusSpecPreset-mainnet.md` and `ConsensusSpecPreset-minimal.md` (fork-upgrade fixtures implicitly exercised via state-transition test suite).

### lodestar

`upgradeStateToGloas` at `vendor/lodestar/packages/state-transition/src/slot/upgradeStateToGloas.ts:14-85`:

```typescript
export function upgradeStateToGloas(stateFulu: CachedBeaconStateFulu): CachedBeaconStateGloas {
  const {config} = stateFulu;
  ssz.fulu.BeaconState.commitViewDU(stateFulu);
  const stateGloasCloned = stateFulu;
  const stateGloasView = ssz.gloas.BeaconState.defaultViewDU();

  stateGloasView.genesisTime = stateGloasCloned.genesisTime;
  // ... ~30 lines of explicit field-by-field carryover ...
  stateGloasView.fork = ssz.phase0.Fork.toViewDU({
    previousVersion: stateFulu.fork.currentVersion,
    currentVersion: config.GLOAS_FORK_VERSION,
    epoch: stateFulu.epochCtx.epoch,
  });
  // ... more carryover ...
  stateGloasView.latestExecutionPayloadBid.blockHash = stateFulu.latestExecutionPayloadHeader.blockHash;
  stateGloasView.latestExecutionPayloadBid.executionRequestsRoot = ssz.electra.ExecutionRequests.hashTreeRoot(
    ssz.electra.ExecutionRequests.defaultValue()
  );
  // ... more carryover ...
  stateGloasView.ptcWindow = ssz.gloas.PtcWindow.toViewDU(initializePtcWindow(stateFulu));

  for (let i = 0; i < SLOTS_PER_HISTORICAL_ROOT; i++) {
    stateGloasView.executionPayloadAvailability.set(i, true);
  }
  stateGloasView.latestBlockHash = stateFulu.latestExecutionPayloadHeader.blockHash;

  const stateGloas = getCachedBeaconState(stateGloasView, stateFulu);

  // Process pending builder deposits at the fork boundary
  onboardBuildersFromPendingDeposits(stateGloas);

  stateGloas.commit();
  stateGloas["clearCache"]();   // biome-ignore: protected attribute
  return stateGloas;
}
```

Order: PTC window first (line 67), then onboard (line 77). **Matches spec order.**

`executionPayloadAvailability`: explicit `for` loop setting every bit to `true` (lines 69-71). ✓

`latestExecutionPayloadBid`: only `blockHash` + `executionRequestsRoot` explicitly set (lines 50-53); other fields take the SSZ schema defaults (zero). ✓

`onboardBuildersFromPendingDeposits` at lines 91-151 mirrors spec; uses `Set<string>` of hex-encoded pubkeys for both `validatorPubkeys` and `builderPubkeys`; **re-tracks newly-added builders** via `state.builders.length` delta detection (lines 116-128) — equivalent to spec's "re-read each iteration" semantic.

### grandine

`upgrade_to_gloas` at `vendor/grandine/helper_functions/src/fork.rs:790-922`:

```rust
pub fn upgrade_to_gloas<P: Preset>(
    config: &Config,
    pubkey_cache: &PubkeyCache,
    pre: FuluBeaconState<P>,
) -> Result<GloasBeaconState<P>> {
    let epoch = accessors::get_current_epoch(&pre);
    let ptc_window = initialize_ptc_window(&pre)?;       // PRE-state, then move-destructured
    let FuluBeaconState { /* ... move-destructure all fields ... */ } = pre;

    let fork = Fork {
        previous_version: fork.current_version,
        current_version: config.gloas_fork_version,
        epoch,
    };
    let latest_execution_payload_bid = ExecutionPayloadBid {
        block_hash: latest_execution_payload_header.block_hash,
        execution_requests_root: ExecutionRequests::<P>::default().hash_tree_root(),
        ..Default::default()
    };
    let mut post_state = GloasBeaconState {
        // ... 30+ moved fields ...
        latest_block_hash: latest_execution_payload_header.block_hash,
        // ... Gloas-new fields ...
        builders: PersistentList::default(),
        next_withdrawal_builder_index: 0,
        execution_payload_availability: BitVector::new(true),
        builder_pending_payments: PersistentVector::default(),
        builder_pending_withdrawals: PersistentList::default(),
        latest_execution_payload_bid,
        payload_expected_withdrawals: PersistentList::default(),
        ptc_window,
        cache,
    };
    onboard_builders(config, pubkey_cache, &mut post_state)?;
    Ok(post_state)
}
```

Order: `initialize_ptc_window(&pre)` FIRST (on the pre-state, matching spec), then state construction, then `onboard_builders`. **Matches spec order exactly.**

`BitVector::new(true)` — bitvector with all bits set to true ✓. `PersistentVector::default()` for `builder_pending_payments` — defaults to fixed-length vector of default `BuilderPendingPayment` ✓.

`initialize_ptc_window` at `fork.rs:940-954`:

```rust
fn initialize_ptc_window<P: Preset>(state: &FuluBeaconState<P>) -> Result<PtcWindow<P>> {
    let current_epoch = accessors::get_current_epoch(state);
    let start_slot = misc::compute_start_slot_at_epoch::<P>(current_epoch);
    let previous_epoch = (0..P::SlotsPerEpoch::U64).map(|_| Ok(Ptc::<P>::default()));

    let current_and_lookahead_epochs = (start_slot
        ..start_slot + (1 + P::MinSeedLookahead::U64) * P::SlotsPerEpoch::U64)
        .map(|slot| accessors::ptc_for_slot(state, slot));

    let window = previous_epoch
        .chain(current_and_lookahead_epochs)
        .collect::<Result<Vec<_>>>()?;

    PtcWindow::<P>::try_from_iter(window).map_err(Into::into)
}
```

32 empty rows + 64 computed rows = 96 mainnet rows ✓.

EF tests: `vendor/grandine/transition_functions/src/combined.rs:506,701` shows the upgrade is called from spec-test runner paths.

## Cross-reference table

| Client | `upgrade_to_gloas` location | Order: PTC vs onboard (H11) | `execution_payload_availability` init (H4) | `latest_execution_payload_bid` shape (H7) | `initialize_ptc_window` input | EF spec-test wrapper |
|---|---|---|---|---|---|---|
| prysm | `upgrade.go:147` | PTC first, then onboard ✓ spec | `0xFF` bytes for ceil(SLOTS_PER_HISTORICAL_ROOT/8) | `BlockHash` + `ExecutionRequestsRoot` + zero buffers | `s` (post-construct state with same `validators`/`randao_mixes`/`slot` as pre) | `testing/spectest/.../fork/upgrade_to_gloas.go` |
| lighthouse | `upgrade/gloas.rs:30` | **onboard first, PTC second** (swapped) | `BitVector::from_bytes(vec![0xFF; len/8])` | `block_hash` + `execution_requests_root` + `..Default::default()` | `&mut post` (after onboard runs; valid because onboard doesn't touch validators/randao_mixes/slot) | EF runner |
| teku | `GloasStateUpgrade.java:71` | PTC first, then onboard ✓ spec | `ofBits(IntStream.range(0, SLOTS_PER_HISTORICAL_ROOT).toArray())` (every bit set) | every field enumerated; `ZERO`/`ZERO`/`latestBlockHash`/... | `preState` (the Fulu state) | EF reference-test runner |
| nimbus | `beaconstate.nim:2887` | **onboard first, PTC second** (swapped) | `BitArray[SLOTS_PER_HISTORICAL_ROOT]` with all bits set via `setBit` loop | `block_hash` + `execution_requests_root`; other fields nim-default | `post` (the Gloas state) | EF mainnet+minimal preset passes |
| lodestar | `upgradeStateToGloas.ts:14` | PTC first, then onboard ✓ spec | explicit `for` loop calling `set(i, true)` for SLOTS_PER_HISTORICAL_ROOT | `blockHash` + `executionRequestsRoot`; other fields SSZ-schema-default | `stateFulu` (the Fulu state) | EF runner |
| grandine | `fork.rs:790` | PTC first ✓ spec (computes on `&pre` BEFORE move-destructure) | `BitVector::new(true)` (all-true) | `block_hash` + `execution_requests_root` + `..Default::default()` | `&pre` (the Fulu state) — matches spec exactly | `transition_functions/src/combined.rs:506,701` via spec-test Phase trait |

H1–H9 ✓ for all clients. H10 ✓ — each client re-reads `state.builders` inside the onboard iteration (or tracks newly-added pubkeys via a parallel set/HashSet/length-delta). H11 partial — lighthouse + nimbus swap; functionally equivalent because `onboard_builders` only mutates `state.pending_deposits` and `state.builders`, while `initialize_ptc_window` reads `state.validators` / `state.randao_mixes` / `state.slot` / effective balances — disjoint input slices.

## Empirical tests

All six clients run EF `gloas/fork/upgrade_to_gloas` fixtures via their spec-test runners:

- prysm: `vendor/prysm/testing/spectest/shared/gloas/fork/upgrade_to_gloas.go:22 RunUpgradeToGloas` unmarshals pre/post states, calls `gloas.UpgradeToGloas(preState)`, byte-diffs against `post.ssz_snappy`.
- lighthouse, lodestar, grandine: equivalent runners in their respective spec-test harnesses (cross-referenced from `vendor/.../fork.test.ts`, `vendor/grandine/transition_functions/src/combined.rs`, etc.).
- teku: `referenceTest` Gradle task exercises the EF fork-upgrade vectors.
- nimbus: `ConsensusSpecPreset-mainnet.md` and `-minimal.md` show the upgrade-to-gloas test family passes on both presets.

No observed cross-client divergence on the EF fixture corpus.

Suggested fuzzing vectors (none presently wired):

- **T1.1 (canonical Electra→Gloas).** Stock EF fixture; verify byte-identical `post.ssz_snappy` across all 6.
- **T2.1 (builders-onboarding active branches).** Pre-state with pending deposits split across (a) existing-validator pubkey, (b) builder-credential pubkey, (c) new-validator pubkey with valid signature, (d) new pubkey with invalid signature. Verify all 6 produce identical `state.builders` and `state.pending_deposits` after onboard.
- **T2.2 (cross-prefix collision).** Pending deposit with builder credentials matching an existing validator pubkey. Spec keeps it in pending (validator-side path); verify all 6 agree.
- **T2.3 (newly-added builder re-scan).** Pending deposit with builder credentials A. Followed by pending deposit with pubkey A and builder credentials (top-up). Spec's "re-read `builder_pubkeys` each iteration" must fire: the second deposit must route to `apply_deposit_for_builder` as an existing-builder top-up, not a new builder. All 6 must agree.
- **T2.4 (PTC window first-row contents).** Verify the first 32 rows are all-zero `Vector[ValidatorIndex, PTC_SIZE]` across all 6 clients (spec's `empty_previous_epoch`).
- **T2.5 (order-swap diff).** Synthetic pre-state where order swap would matter (none reachable — would require `onboard_builders` to mutate `state.validators` or `state.randao_mixes` or `state.slot`, which spec does not). T2.5 confirms H11 holds.
- **T2.6 (state-root regression).** Upgrade pre-state at epoch N; advance to epoch N+1; verify state-root matches spec.

## Conclusion

All six clients implement `upgrade_to_gloas` spec-conformantly. Field-by-field carryover is uniform. Gloas-new field initialization is uniform (empty registries, all-1 `execution_payload_availability`, default `BuilderPendingPayment` × 2*SLOTS_PER_EPOCH, `latest_execution_payload_bid` with `block_hash` carryover + `hash_tree_root(ExecutionRequests::default())`). The PTC window initialization is uniform (32 zero rows + `(1 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH` computed rows). The builders-onboarding loop is uniform with per-client micro-optimizations on the `state.builders` re-scan.

Two clients (lighthouse, nimbus) swap the order of `onboard_builders_from_pending_deposits` and `initialize_ptc_window` relative to spec. The order swap is **functionally equivalent under all reachable inputs** because the two functions operate on disjoint state slices: `initialize_ptc_window` reads `state.validators` / `state.randao_mixes` / `state.slot` / effective balances; `onboard_builders` mutates only `state.pending_deposits` and `state.builders`. Cross-cut with grandine's similar literal-vs-functional deviation in item #60 — the codebase ecosystem tolerates these where the input slices prove disjoint.

**Verdict: impact none.** No divergence. The PR #8440 closure of items #22 + #23 fixed the only known Gloas-alpha-drift in the upgrade path; this audit confirms no parallel bug exists. Audit closes.

## Cross-cuts

### With items #22 + #23 + #28 (nimbus Gloas alpha drift, closed via PR #8440)

PR #8440 fixed the nimbus credential-prefix predicates that drove items #22 and #23. This audit verifies the surrounding `upgrade_to_gloas` machinery (which depends on those predicates via `is_builder_withdrawal_credential` inside `onboard_builders`) does not have parallel issues. Confirmed clean.

### With item #57 (`process_builder_pending_payments`)

`upgrade_to_gloas` initializes `state.builder_pending_payments` to 2*SLOTS_PER_EPOCH default entries; `process_builder_pending_payments` (item #57) is the rotation/drain side. Round-trip cross-cut.

### With item #60 (`compute_ptc`)

`initialize_ptc_window` calls `compute_ptc` for `(1 + MIN_SEED_LOOKAHEAD) * SLOTS_PER_EPOCH` slots; item #60 audited `compute_ptc` directly. Cross-cut.

### With item #63 (`process_ptc_window`)

`upgrade_to_gloas` initializes the PTC window via `initialize_ptc_window`; the first `process_ptc_window` invocation post-upgrade rotates that initial population. Round-trip cross-cut.

### With item #66 (`apply_pending_deposit` Gloas modifications) and item #67 (builder withdrawal flow)

`onboard_builders_from_pending_deposits` calls `apply_deposit_for_builder` — same builder-onboarding primitive that the regular `process_pending_deposits` drain (item #66) and the withdrawal flow (item #67) interact with. Audit of `apply_deposit_for_builder` and `is_builder_withdrawal_credential` is owed in those sibling items.

## Adjacent untouched

1. **`apply_deposit_for_builder` cross-client byte-equivalence** — sister primitive used by `onboard_builders`. Audit-worthy in item #66 cross-cut.
2. **`is_builder_withdrawal_credential` cross-client** — the 0x03-prefix predicate that drove items #22 + #23. Cross-cut with item #66.
3. **EF `gloas/fork/upgrade_to_gloas` fixture coverage of edge cases** — empty validators, max-size `pending_deposits`, mid-iteration builder additions. Worth a dedicated cross-client fixture run.
4. **Custom-config Gloas fork epochs** — devnets activate Gloas at non-FAR_FUTURE epochs; verify the fork-schedule loader correctly triggers `upgrade_to_gloas` exactly once per chain.
5. **Re-org across the fork boundary** — replay-from-cold of a state immediately post-Gloas-upgrade must produce byte-identical state. Not in this audit; worth a devnet test.
6. **Lighthouse `state.get_validator_index` optimization** — verifying the HashSet-based new-validator-pubkey tracking does not skip any spec edge case (e.g., pubkey appears in `state.validators` AND in a prior pending deposit).
