# Item 38 — `get_validators_custody_requirement` (EIP-7594 PeerDAS validator-balance-scaled custody)

**Status:** no-divergence-pending-fixture-run — audited 2026-05-04. **Ninth Fulu-NEW item, fifth PeerDAS audit** (after #33 custody, #34 verify pipeline, #35 fork-choice DA, #37 subnet derivation). The validator-balance-scaled custody formula: nodes with validators attached custody more groups based on total effective balance. Cross-cuts item #33 (which referenced this as "teku has standalone implementation observed; verify other 5"). Foundational for cross-client gossip mesh structure: high-stake nodes contribute more custody → richer PeerDAS mesh.

```python
def get_validators_custody_requirement(state, validator_indices) -> uint64:
    total_node_balance = sum(state.validators[i].effective_balance for i in validator_indices)
    count = total_node_balance // BALANCE_PER_ADDITIONAL_CUSTODY_GROUP  # = 32 ETH per unit
    return min(max(count, VALIDATOR_CUSTODY_REQUIREMENT = 8), NUMBER_OF_CUSTODY_GROUPS = 128)
```

Mainnet defaults: `VALIDATOR_CUSTODY_REQUIREMENT = 8` (minimum for a validator-running node), `BALANCE_PER_ADDITIONAL_CUSTODY_GROUP = 32_000_000_000` (32 ETH per additional group), `NUMBER_OF_CUSTODY_GROUPS = 128` (super-node cap). A node with 32 ETH ⇒ 1 unit ⇒ clamped to min 8. A node with 128*32 = 4096 ETH ⇒ 128 units ⇒ super-node. EIP-7251 changed effective balance ceiling to 2048 ETH, so a single MaxEB validator = 64 units = below super-node.

## Scope

In: `get_validators_custody_requirement(state, validator_indices)` formula; `VALIDATOR_CUSTODY_REQUIREMENT = 8` (Fulu-NEW constant); `BALANCE_PER_ADDITIONAL_CUSTODY_GROUP = 32 ETH` (Fulu-NEW); `NUMBER_OF_CUSTODY_GROUPS = 128` cap (cross-cuts item #33); empty-validator-set behavior; cross-client function signature divergence; persist-across-restart semantics (lighthouse-only).

Out: ENR `cgc` field encoding (separate item); custody backfill mechanism (lighthouse `backfill_validator_custody_requirements`); CUSTODY_CHANGE_DA_EFFECTIVE_DELAY_SECONDS handling (lighthouse-specific); validator client API for custody updates.

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | Formula: `min(max(total_balance / BALANCE_PER_ADDITIONAL_CUSTODY_GROUP, VALIDATOR_CUSTODY_REQUIREMENT), NUMBER_OF_CUSTODY_GROUPS)` | ✅ all 6 | Spec single-line. |
| H2 | Mainnet: VALIDATOR_CUSTODY_REQUIREMENT = 8, BALANCE_PER_ADDITIONAL_CUSTODY_GROUP = 32_000_000_000 Gwei | ✅ all 6 | Confirmed in `mainnet/config.yaml` + each client's config defaults. |
| H3 | Single MaxEB validator (2048 ETH compounding) → 2048 / 32 = 64 units → 64 (above min, below cap) | ✅ all 6 | Standard formula application. |
| H4 | 128+ units (= 4096 ETH attached) → super-node cap = 128 | ✅ all 6 | min(...) clamp. |
| H5 | Single 32 ETH validator → 1 unit → max(1, 8) = 8 (min clamp) | ✅ all 6 | max(...) clamp. |
| H6 | Empty-validator-set behavior: spec assumes function called only when validators attached; behavior undefined | ⚠️ **DIVERGENCE**: lodestar returns `CUSTODY_REQUIREMENT = 4` (non-validator default); other 5 return `VALIDATOR_CUSTODY_REQUIREMENT = 8` | **NEW Pattern T candidate** — spec-undefined edge-case divergence |
| H7 | Function signature: takes `(state, validator_indices)` per spec | ⚠️ **DIVERGENCE in 4 of 6**: only teku matches spec; prysm takes `ReadOnlyBalances + map`; nimbus takes pre-computed `Gwei`; lodestar takes `effectiveBalances[]`; lighthouse takes pre-divided `validator_custody_units`; grandine takes spec-correct `(config, state, validator_indices)` | Per-client API design divergence |
| H8 | Naming: `get_validators_custody_requirement` (PLURAL "validators") | ⚠️ **DIVERGENCE**: grandine uses `get_validator_custody_requirement` (SINGULAR) | Cosmetic but breaks search/refactoring tooling |
| H9 | Dynamic adjustment: SHOULD adjust as effective balance changes; SHOULD NOT decrease (only-grow) | ✅ implemented in lighthouse (`epoch_validator_custody_requirements` BTreeMap with persist-across-restart); other 5 TBD on dynamic-adjustment semantics | lighthouse most spec-faithful per "only-grow" requirement |
| H10 | Persist across restarts (spec: "previous (highest) `custody_group_count` SHOULD persist across node restarts") | ✅ in lighthouse (explicit BTreeMap `epoch_validator_custody_requirements` persisted to db); ⚠️ TBD in other 5 | lighthouse most spec-faithful |

## Per-client cross-reference

| Client | Function name + location | Signature | Empty-set behavior | Persist-across-restart? |
|---|---|---|---|---|
| **prysm** | `core/peerdas/validator.go:93` `ValidatorsCustodyRequirement(st ReadOnlyBalances, validatorsIndex map[ValidatorIndex]bool) -> (uint64, error)` | non-spec: `(ReadOnlyBalances, map[ValidatorIndex]bool)`; uses `EffectiveBalanceSum(idxs)` to compute total | total = 0 → count = 0 → max(0, 8) = 8 | TBD (separate file) |
| **lighthouse** | `beacon_chain/src/custody_context.rs:185` `get_validators_custody_requirement(validator_custody_units: u64, spec)` | non-spec: takes PRE-DIVIDED `units` (caller does the division) | units = 0 → max(0, 8) = 8 | **YES** — `epoch_validator_custody_requirements: BTreeMap<Epoch, u64>` persisted; `latest_validator_custody_requirement()` getter; explicit `backfill_validator_custody_requirements` + `reset_validator_custody_requirements` |
| **teku** | `MiscHelpersFulu.java:226` `getValidatorsCustodyRequirement(state, validatorIndices: Set<UInt64>) -> UInt64` | **SPEC-MATCHING signature**: `(BeaconState, Set<UInt64>)` | empty Set → totalNodeBalance = UInt64.ZERO → count = 0 → max(0, 8) = 8 | TBD |
| **nimbus** | `spec/peerdas_helpers.nim:573` `get_validators_custody_requirement(cfg, total_node_balance: Gwei) -> uint64` | non-spec: takes PRE-COMPUTED `total_node_balance` (caller computes the sum) | total = 0 → count = 0 → max(0, 8) = 8 | TBD |
| **lodestar** | `beacon-node/src/util/dataColumns.ts:154` `getValidatorsCustodyRequirement(config, effectiveBalances: number[]) -> number` | non-spec: takes flat `effectiveBalances[]` array | **DIVERGENT**: empty array → returns `CUSTODY_REQUIREMENT = 4` (non-validator default) early-exit | TBD |
| **grandine** | `eip_7594/src/lib.rs:517` `get_validator_custody_requirement<P>(config, last_finalized_state, validator_indices)` (note: SINGULAR "validator") | non-spec naming: SINGULAR; signature: `(config, state, &HashSet<ValidatorIndex>)` | empty HashSet → total = 0 → count = 0 → max(0, 8) = 8 | TBD |

## Notable per-client findings

### CRITICAL: lodestar diverges on empty-validator-set

```typescript
export function getValidatorsCustodyRequirement(config: ChainForkConfig, effectiveBalances: number[]): number {
  if (effectiveBalances.length === 0) {
    return config.CUSTODY_REQUIREMENT;  // = 4 for non-validator nodes
  }
  // ... rest computes formula ...
}
```

**Lodestar returns `CUSTODY_REQUIREMENT = 4`** (the non-validator default) when called with empty validator set. Other 5 return `VALIDATOR_CUSTODY_REQUIREMENT = 8` (the validator-node minimum) via the `max(0, 8) = 8` clamp.

**Spec assumes function called only with validators attached**: "A node with validators attached downloads and custodies a higher minimum of custody groups per slot, determined by `get_validators_custody_requirement(state, validator_indices)`." Empty case is undefined per spec.

**Behavioral consequence**: a beacon node with validator client temporarily disconnected (empty active validator set) would advertise:
- lodestar: 4 custody groups (non-validator behavior)
- other 5: 8 custody groups (validator-node minimum)

**Cross-client divergence at the gossip layer**: peers see different `custody_group_count` for what is otherwise the same node. **Bandwidth + DA divergence on edge case.**

**Spec ambiguity**: probably should be flagged to consensus-specs for clarification. Lodestar's 4 may be more "correct" interpretation (no validators → no validator-node requirement), but 5 of 6 enforce the 8 minimum.

### Function signature divergence — 6 distinct shapes

| Client | Signature | Pattern |
|---|---|---|
| spec | `(state: BeaconState, validator_indices: Sequence[ValidatorIndex]) -> uint64` | reference |
| prysm | `(st ReadOnlyBalances, validatorsIndex map[ValidatorIndex]bool) -> (uint64, error)` | non-spec — interface + map-to-bool (set semantics via map) |
| lighthouse | `(validator_custody_units: u64, spec: &ChainSpec) -> u64` | non-spec — caller does division; minimal function |
| teku | `(BeaconState, Set<UInt64>) -> UInt64` | **closest to spec** |
| nimbus | `(cfg: RuntimeConfig, total_node_balance: Gwei) -> uint64` | non-spec — caller computes total |
| lodestar | `(config: ChainForkConfig, effectiveBalances: number[]) -> number` | non-spec — caller flattens to array |
| grandine | `(config: &Config, state: &impl BeaconState<P>, &HashSet<ValidatorIndex>) -> u64` | spec-shape with extra config |

**Only teku matches the spec signature exactly.** Other 5 either pre-compute, restructure, or take different intermediate types. This makes cross-client testing harder (different fixture inputs needed).

### Naming: grandine SINGULAR vs spec PLURAL

Spec: `get_validators_custody_requirement` (PLURAL "validators").
Grandine: `get_validator_custody_requirement` (SINGULAR).

**Cosmetic divergence** but:
- Breaks `grep`-based cross-reference tooling
- Spec-compliance scripts (specrefs/) wouldn't auto-detect grandine's mapping
- Confusion risk: easy to think there are TWO functions when there's one

### Lighthouse most spec-faithful on dynamic adjustment

Spec dynamic-adjustment requirements:
- "A node SHOULD dynamically adjust its custody groups (without any input from the user) following any changes to the total effective balances of attached validators."
- "If the node's custody requirements are increased, it SHOULD immediately advertise the updated `custody_group_count`."
- "If a node's custody requirements decrease, it SHOULD NOT update the `custody_group_count` to reflect this reduction."
- "The previous (highest) `custody_group_count` SHOULD persist across node restarts."

**Lighthouse implementation** (`custody_context.rs`):
- `epoch_validator_custody_requirements: BTreeMap<Epoch, u64>` — per-epoch custody log
- `latest_validator_custody_requirement()` — returns highest historical value
- `backfill_validator_custody_requirements(effective_epoch, expected_cgc)` — handles backfill after sync
- `reset_validator_custody_requirements(effective_epoch)` — restart sync
- `CUSTODY_CHANGE_DA_EFFECTIVE_DELAY_SECONDS` — buffer before applying new CGC (allows time to subscribe to new subnets)
- Persisted to db across restarts (per `latest_validator_custody_requirement` calls in `http_api/lib.rs:3034`)

**Most spec-faithful** of the 6. Other 5 likely have simpler/missing dynamic-adjustment logic — verify in future research.

**Lighthouse signature implication**: takes `validator_custody_units` (already-divided count) instead of raw balance — because the unit count is what's PERSISTED to db (not the raw balance). The function is the "round to spec" step; persistence handles the dynamic adjustment.

### Prysm prepares `ReadOnlyBalances` interface

```go
func ValidatorsCustodyRequirement(st beaconState.ReadOnlyBalances, validatorsIndex map[primitives.ValidatorIndex]bool) (uint64, error) {
    ...
    totalBalance, err := st.EffectiveBalanceSum(idxs)
    ...
}
```

Uses an INTERFACE (`ReadOnlyBalances`) rather than the full `BeaconState`. **Cleanest abstraction** — easy to mock/test, doesn't require full state. But map-to-bool for set semantics is Go-idiomatic but unusual.

### Nimbus pre-computed `total_node_balance`

```nim
func get_validators_custody_requirement*(cfg: RuntimeConfig,
                                         total_node_balance: Gwei):
                                         uint64 =
  let count = total_node_balance div cfg.BALANCE_PER_ADDITIONAL_CUSTODY_GROUP
  min(max(count.uint64, cfg.VALIDATOR_CUSTODY_REQUIREMENT),
      cfg.NUMBER_OF_CUSTODY_GROUPS.uint64)
```

Caller must compute `total_node_balance` upstream. **Minimal function** — just the formula, no I/O. Very testable.

**Concern**: callers may compute total_node_balance differently (sum over validator_indices vs sum over active validators vs cached value). Easy to introduce bug at the call site that doesn't show up in this function.

### Grandine `process_results` for short-circuit on missing validator

```rust
let total_node_balance = validator_indices
    .iter()
    .map(|index| {
        last_finalized_state
            .validators()
            .get(*index)
            .map(|validator| validator.effective_balance)
    })
    .process_results(|iter| iter.sum::<Gwei>())
    .unwrap_or(0);
```

**Defensive**: if any `validator_index` is out of bounds (e.g., not yet activated), `process_results` short-circuits and the `.unwrap_or(0)` defaults to 0 → max(0, 8) = 8. **Same observable result as treating missing validators as 0 balance.**

Other 5 clients TBD on missing-validator handling.

### Live mainnet validation

All 6 clients have been operating Fulu PeerDAS for 5+ months without DA failures. Validator-running nodes have been adapting custody based on attached validator effective balances. **Live behavior validates source review** — but EDGE CASE divergence (lodestar empty-set) hasn't surfaced because in practice nodes always have validators attached when running validator clients.

## Cross-cut chain

This audit closes the validator-scaled custody surface and cross-cuts:
- **Item #33** (PeerDAS custody assignment): explicitly noted "validator-balance-scaled custody (`getValidatorsCustodyRequirement`) — teku-only standalone implementation observed; verify other 5". This audit confirms ALL 6 have implementations (with 6 different signatures + 1 behavioral divergence on empty-set).
- **Item #34** (PeerDAS sidecar verification): downstream consumer — sidecars only enter custody set if their column is in the node's custody groups, which depends on the count from this function.
- **Item #35** (PeerDAS fork-choice DA): downstream consumer — DA check requires sampled columns = MAX(SAMPLES_PER_SLOT, custody_group_count). High-stake nodes need more columns for DA.
- **Item #28 NEW Pattern T candidate**: spec-undefined edge-case divergence — lodestar's empty-set behavior (returns CUSTODY_REQUIREMENT = 4) vs other 5 (return VALIDATOR_CUSTODY_REQUIREMENT = 8). Same forward-fragility class as Pattern J/N/P/Q/R/S — clients diverge on spec-undefined behavior.

## Adjacent untouched Fulu-active

- ENR `cgc` (custody group count) field encoding/decoding cross-client (separate item)
- Custody backfill mechanism cross-client (lighthouse explicit; others TBD)
- `CUSTODY_CHANGE_DA_EFFECTIVE_DELAY_SECONDS` lighthouse-specific buffer logic
- Dynamic-adjustment "only-grow" semantics cross-client (lighthouse explicit via BTreeMap; others TBD)
- Persist-across-restart semantics cross-client (lighthouse explicit; others TBD)
- Validator client → beacon node API for custody updates
- Cross-network constants consistency (mainnet/sepolia/holesky/gnosis/hoodi all confirmed = 8/32 ETH/128 in lighthouse configs; verify other 5)
- Effective-balance edge cases: 0 balance validators, slashed validators, validators with FAR_FUTURE_EPOCH activation
- Compounding (0x02) validators with > 32 ETH (EIP-7251) — should contribute proportionally more custody
- super-node behavior consistency (≥4096 ETH attached → 128 groups → all 128 columns)
- Cross-fork transition Pectra → Fulu — non-validator nodes use CUSTODY_REQUIREMENT = 4; validator nodes use VALIDATOR_CUSTODY_REQUIREMENT = 8

## Future research items

1. **Wire Fulu validator-category fixtures** in BeaconBreaker harness — same blocker as items #30-#37 (now spans 9 Fulu items + 8 sub-categories). Single fix unblocks all.
2. **NEW Pattern T for item #28 catalogue**: spec-undefined edge-case divergence — lodestar empty-set returns 4; other 5 return 8. Forward-fragility class.
3. **Empty-validator-set fixture**: pass empty set to all 6; verify divergence (5 return 8, lodestar returns 4). File issue with consensus-specs to clarify.
4. **Spec issue: file consensus-specs ambiguity report** — empty-validator-set behavior not defined; per-client divergence observed. Suggest spec text: "If validator_indices is empty, return CUSTODY_REQUIREMENT" (lodestar) OR "If validator_indices is empty, return VALIDATOR_CUSTODY_REQUIREMENT" (other 5) OR "Function MUST NOT be called with empty validator_indices" (defensive contract).
5. **Cross-client function signature normalization** — propose per-client wrapper functions with spec-matching signature `(state, validator_indices)` for cross-client testing.
6. **Grandine naming fix**: rename `get_validator_custody_requirement` → `get_validators_custody_requirement` (PLURAL) for spec-compliance and tooling-compat. File grandine PR.
7. **Dynamic-adjustment cross-client audit** — lighthouse has explicit BTreeMap + delay buffer; teku/nimbus/lodestar/grandine/prysm TBD. Spec requires "only-grow" + "persist across restarts" — verify all 6 implement.
8. **Persist-across-restart fixture** — restart node with different validator set; verify CGC stays at highest historical value (lighthouse explicit; others TBD).
9. **CUSTODY_CHANGE_DA_EFFECTIVE_DELAY_SECONDS lighthouse-specific** — propose to consensus-specs as a recommendation; cross-client behavior at custody-change boundary.
10. **Compounding validator (EIP-7251) integration test**: 1 validator with 2048 ETH effective balance → 64 units → 64 custody groups → custody assignment for super-validator. Verify all 6 produce same `custody_group_count`.
11. **Cross-network constants consistency audit** — verify all 6 ship `VALIDATOR_CUSTODY_REQUIREMENT = 8` and `BALANCE_PER_ADDITIONAL_CUSTODY_GROUP = 32_000_000_000` for mainnet/sepolia/holesky/gnosis/hoodi.
12. **Generate dedicated EF fixtures** for `get_validators_custody_requirement` as a pure function: input (state, validator_indices) → output (uint64). Currently no `validators_custody` category in pyspec.
13. **Effective-balance edge cases**: 0 balance validators (slashed pending withdrawal) — should they contribute 0 to total_node_balance? Verify all 6 produce same result.
14. **Super-node cap test**: > 4096 ETH attached → exactly 128 (NUMBER_OF_CUSTODY_GROUPS) — verify saturation. Some implementations may overflow.
15. **Spec-compliance audit at testnets** — verify all 6 actually produce correct `custody_group_count` ENR field on testnets where validator counts vary widely.

## Summary

EIP-7594 PeerDAS validator-balance-scaled custody is implemented across all 6 clients with formula correctness, but **6 distinct function signatures** and **1 behavioral divergence on empty-validator-set**.

Per-client divergences:
- **lodestar diverges on empty-validator-set**: returns `CUSTODY_REQUIREMENT = 4` (non-validator default) when called with empty validators; other 5 return `VALIDATOR_CUSTODY_REQUIREMENT = 8` via the `max(0, 8) = 8` clamp. **Spec-undefined edge case** — observable divergence on misuse.
- **6 distinct function signatures**: only teku matches spec `(state, validator_indices)`; prysm uses `ReadOnlyBalances + map`; lighthouse takes pre-divided `units`; nimbus takes pre-computed `Gwei`; lodestar takes `effectiveBalances[]` array; grandine takes spec-correct shape with extra config.
- **Naming divergence**: grandine uses SINGULAR `get_validator_custody_requirement` vs spec PLURAL `get_validators_custody_requirement`.
- **Lighthouse most spec-faithful on dynamic adjustment**: explicit BTreeMap `epoch_validator_custody_requirements` for "only-grow" semantics + persist-across-restart + CUSTODY_CHANGE_DA_EFFECTIVE_DELAY_SECONDS buffer. Other 5 dynamic-adjustment semantics TBD.

**NEW Pattern T candidate for item #28 catalogue**: spec-undefined edge-case divergence — lodestar's empty-set behavior. Same forward-fragility class as Pattern J/N/P/Q/R/S.

**Status**: source review confirms all 6 clients aligned at Fulu mainnet on the spec-defined cases (validator-set non-empty). 5+ months of live PeerDAS gossip without DA failures. **Edge-case divergence (empty-set) hasn't surfaced in production** because nodes always have validators attached when running validator clients.

**With this audit, the PeerDAS custody assignment surface is complete**: items #33 (custody groups → columns) → #37 (columns → subnets) → #38 (validator balance → custody count). Three-item arc covering custody-derivation end-to-end. PeerDAS audit corpus now spans 5 items: #33, #34, #35, #37, #38.
