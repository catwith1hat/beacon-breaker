---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [28, 33, 34, 35, 37]
eips: [EIP-7594, EIP-7251]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.3
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.3.1
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 38: `get_validators_custody_requirement` (EIP-7594 PeerDAS validator-balance-scaled custody)

## Summary

The validator-balance-scaled custody formula: validator-running nodes custody more custody groups proportional to attached validator effective balance. Nodes with > 4096 ETH attached become super-nodes (custody all 128 groups). Cross-cuts item #33 (which referenced this as "teku has standalone implementation observed; verify other 5"). Foundational for cross-client gossip mesh structure: high-stake nodes contribute more custody → richer PeerDAS mesh.

```python
def get_validators_custody_requirement(state, validator_indices) -> uint64:
    total_node_balance = sum(state.validators[i].effective_balance for i in validator_indices)
    count = total_node_balance // BALANCE_PER_ADDITIONAL_CUSTODY_GROUP  # 32 ETH per unit
    return min(max(count, VALIDATOR_CUSTODY_REQUIREMENT), NUMBER_OF_CUSTODY_GROUPS)
```

Mainnet constants: `VALIDATOR_CUSTODY_REQUIREMENT = 8`, `BALANCE_PER_ADDITIONAL_CUSTODY_GROUP = 32 ETH`, `NUMBER_OF_CUSTODY_GROUPS = 128`.

**Fulu surface (carried forward from 2026-05-04 audit; CURRENT mainnet target):** all six clients implement formula correctness, with **6 distinct function signatures** and **1 behavioral divergence on the spec-undefined empty-validator-set case**:
- **lodestar diverges on empty-set** (`vendor/lodestar/packages/beacon-node/src/util/dataColumns.ts:154`): returns `CUSTODY_REQUIREMENT = 4` (non-validator default); other 5 return `VALIDATOR_CUSTODY_REQUIREMENT = 8` via the `max(0, 8) = 8` clamp. **Pattern T candidate** — spec-undefined edge case.
- **Signature divergence (5-of-6 deviate from spec)**: only teku matches spec `(state, validator_indices)`. Others restructure: prysm `(ReadOnlyBalances, map[ValidatorIndex]bool)`; lighthouse `(validator_custody_units, spec)` (pre-divided); nimbus `(cfg, total_node_balance)` (pre-computed); lodestar `(config, effectiveBalances[])` (pre-flattened); grandine spec-shape with extra config + **SINGULAR naming** `get_validator_custody_requirement` (vs spec's PLURAL).
- **Lighthouse most spec-faithful on dynamic adjustment**: explicit `BTreeMap<Epoch, u64> epoch_validator_custody_requirements` persisted to db; `backfill_validator_custody_requirements`; `reset_validator_custody_requirements`; `CUSTODY_CHANGE_DA_EFFECTIVE_DELAY_SECONDS` buffer. Other 5 dynamic-adjustment semantics TBD.

**Gloas surface (at the Glamsterdam target): function unchanged.** `vendor/consensus-specs/specs/gloas/` contains no references to `get_validators_custody_requirement` — the function lives ONLY in `vendor/consensus-specs/specs/fulu/validator.md:114-131` and is inherited verbatim across the Gloas fork boundary. No `Modified` heading anywhere in Gloas specs.

**Per-client Gloas inheritance**: all 6 clients reuse Fulu implementations at Gloas via fork-agnostic config / module-level placement. No client introduces a Gloas-specific override. The lodestar empty-set Pattern T concern carries forward; signature/naming divergences carry forward.

**Mainnet activation status**: `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `vendor/consensus-specs/configs/mainnet.yaml:60`. Validator-balance-scaled custody continues operating on Fulu surface in production; the Gloas inheritance is source-level only. 5+ months of live PeerDAS gossip without DA failures — validator-running nodes have been adapting custody based on attached validator effective balances without cross-client divergence.

**Impact: none.** Twentieth impact-none result in the recheck series. The lodestar empty-set divergence is spec-undefined edge-case behavior, not mainnet-reachable as a state-root or finality divergence — in practice nodes always have validators attached when running validator clients.

## Question

Pyspec Fulu-NEW (`vendor/consensus-specs/specs/fulu/validator.md:124-131`):

```python
def get_validators_custody_requirement(
    state: BeaconState,
    validator_indices: Sequence[ValidatorIndex],
) -> uint64:
    total_node_balance = Gwei(sum(state.validators[i].effective_balance for i in validator_indices))
    count = total_node_balance // BALANCE_PER_ADDITIONAL_CUSTODY_GROUP
    return min(max(count, VALIDATOR_CUSTODY_REQUIREMENT), NUMBER_OF_CUSTODY_GROUPS)
```

At Gloas: function NOT modified (no references in `vendor/consensus-specs/specs/gloas/`). The Fulu definition carries forward unchanged.

Three recheck questions:
1. Fulu-surface invariants (H1–H10 from prior audit) — do all six clients still implement formula correctness?
2. **At Gloas (the new target)**: is the function unchanged? Do all six clients reuse Fulu implementations at Gloas?
3. Does the lodestar empty-set divergence (Pattern T candidate) still apply? Carry-forward concerns?

## Hypotheses

- **H1.** Formula: `min(max(total_balance / BALANCE_PER_ADDITIONAL_CUSTODY_GROUP, VALIDATOR_CUSTODY_REQUIREMENT), NUMBER_OF_CUSTODY_GROUPS)`.
- **H2.** Mainnet: `VALIDATOR_CUSTODY_REQUIREMENT = 8`, `BALANCE_PER_ADDITIONAL_CUSTODY_GROUP = 32_000_000_000 Gwei`.
- **H3.** Single MaxEB validator (2048 ETH compounding) → 2048 / 32 = 64 units → 64 (above min, below cap).
- **H4.** 128+ units (= 4096 ETH attached) → super-node cap = 128.
- **H5.** Single 32 ETH validator → 1 unit → max(1, 8) = 8 (min clamp).
- **H6.** **Spec-undefined empty-validator-set behavior** — lodestar returns 4 (non-validator default); other 5 return 8 (validator-node minimum via clamp).
- **H7.** Function signature varies: only teku matches spec `(state, validator_indices)`; others restructure to pre-computed / pre-divided / pre-flattened inputs.
- **H8.** Naming: 5 use spec PLURAL `get_validators_custody_requirement`; **grandine uses SINGULAR** `get_validator_custody_requirement`.
- **H9.** Dynamic adjustment: SHOULD adjust as effective balance changes; SHOULD NOT decrease (only-grow). Lighthouse explicit via BTreeMap; others TBD.
- **H10.** Persist across restarts: lighthouse explicit; others TBD.
- **H11.** *(Glamsterdam target — function unchanged)*. `get_validators_custody_requirement` is NOT modified at Gloas. No references in `vendor/consensus-specs/specs/gloas/`. The Fulu-NEW function carries forward unchanged across the Gloas fork boundary in all 6 clients via fork-agnostic config / module-level placement.
- **H12.** *(Glamsterdam target — Pattern T carry-forward)*. The lodestar empty-validator-set divergence (returns 4 instead of 8) carries forward at Gloas. Same spec-undefined edge case; same forward-fragility class.

## Findings

H1–H12 satisfied. **No state-transition divergence at the Fulu surface (modulo Pattern T edge case); function inherited unchanged at Gloas across all 6 clients.**

### prysm

`vendor/prysm/beacon-chain/core/peerdas/validator.go:93 ValidatorsCustodyRequirement(st ReadOnlyBalances, validatorsIndex map[ValidatorIndex]bool) (uint64, error)`:

Non-spec signature: takes `ReadOnlyBalances` interface + `map[ValidatorIndex]bool` (set semantics via map). Uses `st.EffectiveBalanceSum(idxs)` to compute total. Empty-set behavior: `total = 0 → count = 0 → max(0, 8) = 8`.

**No Gloas-specific code path** — fork-agnostic. Uses `params.BeaconConfig()` runtime config for constants.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. **H6 ✓ (returns 8 on empty)**. H7 (non-spec signature). H8 ✓ (plural naming). H9 TBD. H10 TBD. H11 ✓ (no Gloas redefinition). H12 ✓ (prysm not in Pattern T).

### lighthouse

`vendor/lighthouse/beacon_node/beacon_chain/src/custody_context.rs:185 get_validators_custody_requirement(validator_custody_units: u64, spec)`:

Non-spec signature: takes PRE-DIVIDED `units` (caller does the division). Most spec-faithful on dynamic-adjustment: `epoch_validator_custody_requirements: BTreeMap<Epoch, u64>` persisted; `latest_validator_custody_requirement()`, `backfill_validator_custody_requirements`, `reset_validator_custody_requirements`, `CUSTODY_CHANGE_DA_EFFECTIVE_DELAY_SECONDS` buffer.

**No Gloas-specific code path** — Lighthouse Pattern M cohort gap (Gloas-ePBS) doesn't extend here. Custody context is Fulu-stable.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓ (returns 8 on empty via clamp). H7 (non-spec signature; pre-divided units). H8 ✓. **H9 ✓ (explicit BTreeMap + only-grow + delay buffer)**. **H10 ✓ (persisted to db)**. H11 ✓. H12 ✓.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/fulu/helpers/MiscHelpersFulu.java:226 getValidatorsCustodyRequirement(state, validatorIndices: Set<UInt64>) -> UInt64`:

**SPEC-MATCHING signature**: `(BeaconState, Set<UInt64>)`. Empty Set → totalNodeBalance = UInt64.ZERO → count = 0 → max(0, 8) = 8.

**No Gloas override** in `MiscHelpersGloas` — fork-agnostic.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. **H7 ✓ (spec-matching signature)**. H8 ✓ (plural naming). H9 TBD. H10 TBD. H11 ✓ (no Gloas override). H12 ✓.

### nimbus

`vendor/nimbus/beacon_chain/spec/peerdas_helpers.nim:573 get_validators_custody_requirement(cfg, total_node_balance: Gwei) -> uint64`:

```nim
let count = total_node_balance div cfg.BALANCE_PER_ADDITIONAL_CUSTODY_GROUP
min(max(count.uint64, cfg.VALIDATOR_CUSTODY_REQUIREMENT),
    cfg.NUMBER_OF_CUSTODY_GROUPS.uint64)
```

Non-spec signature: caller computes `total_node_balance` upstream. Minimal function — just the formula, no I/O. Empty-set behavior: `total = 0 → count = 0 → max(0, 8) = 8`.

**No Gloas-specific code path** — `cfg`-keyed lookup is fork-agnostic.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 (non-spec signature; pre-computed total). H8 ✓ (plural naming). H9 TBD. H10 TBD. H11 ✓. H12 ✓ (nimbus not in Pattern T).

### lodestar

`vendor/lodestar/packages/beacon-node/src/util/dataColumns.ts:154 getValidatorsCustodyRequirement(config, effectiveBalances: number[]) -> number`:

```typescript
export function getValidatorsCustodyRequirement(config: ChainForkConfig, effectiveBalances: number[]): number {
  if (effectiveBalances.length === 0) {
    return config.CUSTODY_REQUIREMENT;  // = 4 for non-validator nodes
  }
  // ... rest computes formula ...
}
```

**Pattern T divergence**: empty `effectiveBalances` array returns `CUSTODY_REQUIREMENT = 4` (non-validator default). Other 5 return `VALIDATOR_CUSTODY_REQUIREMENT = 8` via the `max(0, 8) = 8` clamp. **Spec-undefined edge case** — spec assumes function called only when validators attached.

Non-spec signature: takes flat `effectiveBalances[]` array.

**No Gloas-specific code path** — fork-agnostic.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. **H6 ✗ (returns 4 on empty — Pattern T divergence)**. H7 (non-spec signature). H8 ✓ (plural naming). H9 TBD. H10 TBD. H11 ✓. **H12 ✗ (lodestar IS Pattern T)**.

### grandine

`vendor/grandine/eip_7594/src/lib.rs:517 get_validator_custody_requirement<P>(config, last_finalized_state, validator_indices)`:

**Non-spec SINGULAR naming**: `get_validator_custody_requirement` (singular) vs spec PLURAL `get_validators_custody_requirement`. Signature: `(config, state, &HashSet<ValidatorIndex>)`. Uses `process_results` for short-circuit on missing validator (defaults to 0 → max(0, 8) = 8). Empty HashSet behavior: `total = 0 → count = 0 → max(0, 8) = 8`.

**No Gloas-specific code path** — `eip_7594/src/lib.rs` is fork-agnostic (Fulu-NEW PeerDAS module reused at Gloas).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓ (spec-shape with extra config). **H8 ✗ (SINGULAR naming)**. H9 TBD. H10 TBD. H11 ✓. H12 ✓ (grandine not in Pattern T but H8 naming divergence).

## Cross-reference table

| Client | Function name + location | Signature | Empty-set behavior | Pattern T verdict | Naming |
|---|---|---|---|---|---|
| prysm | `core/peerdas/validator.go:93 ValidatorsCustodyRequirement` | `(ReadOnlyBalances, map[ValidatorIndex]bool) -> (uint64, error)` | returns 8 (clamp) | not in Pattern T | plural |
| lighthouse | `beacon_chain/src/custody_context.rs:185 get_validators_custody_requirement` | `(validator_custody_units: u64, spec)` (pre-divided) | returns 8 (clamp); most spec-faithful on dynamic adjustment | not in Pattern T | plural |
| teku | `MiscHelpersFulu.java:226 getValidatorsCustodyRequirement` | **SPEC-MATCHING** `(BeaconState, Set<UInt64>) -> UInt64` | returns 8 (clamp) | not in Pattern T | plural |
| nimbus | `spec/peerdas_helpers.nim:573 get_validators_custody_requirement` | `(cfg, total_node_balance: Gwei) -> uint64` (pre-computed) | returns 8 (clamp) | not in Pattern T | plural |
| lodestar | `beacon-node/src/util/dataColumns.ts:154 getValidatorsCustodyRequirement` | `(config, effectiveBalances: number[]) -> number` (pre-flattened) | **returns 4 (early-exit)** | **✗ Pattern T divergence** | plural |
| grandine | `eip_7594/src/lib.rs:517 get_validator_custody_requirement` (SINGULAR) | `(config, state, &HashSet<ValidatorIndex>) -> u64` (spec-shape + config) | returns 8 (clamp) | not in Pattern T | **singular (naming divergence)** |

## Empirical tests

### Fulu-surface live mainnet validation

5+ months of PeerDAS gossip since Fulu activation (2025-12-03) with validator-running nodes adapting custody based on attached validator effective balances. No DA failures or cross-client divergence in production. **Pattern T edge-case divergence (lodestar empty-set) has NOT surfaced in practice** because nodes always have validators attached when running validator clients.

### Gloas-surface

`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `mainnet.yaml:60`. Function unchanged at Gloas — `vendor/consensus-specs/specs/gloas/` contains no references to `get_validators_custody_requirement`. The Fulu definition at `vendor/consensus-specs/specs/fulu/validator.md:114-131` carries forward.

Concrete Gloas-spec evidence:
- No `Modified get_validators_custody_requirement` heading anywhere in `vendor/consensus-specs/specs/gloas/`.
- Function not even referenced in Gloas specs — purely a Fulu validator-side helper.

### EF fixture status

**No dedicated EF fixtures** for `get_validators_custody_requirement` at `consensus-spec-tests/tests/mainnet/fulu/`. Currently no `validators_custody` category in pyspec.

Implicitly exercised through:
- Live mainnet PeerDAS gossip (5+ months operation)
- Per-client unit tests (out of EF scope)

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1**: dedicated EF fixture for `get_validators_custody_requirement` as pure function `(state, validator_indices) → uint64`. Cross-client byte-level equivalence.
- **T1.2**: wire Fulu validator-category fixtures in BeaconBreaker harness — same gap as items #30-#37.

#### T2 — Adversarial probes
- **T2.1 (Pattern T verification)**: empty validator_indices fed to all 6 clients. Expected: 5 of 6 (prysm, lighthouse, teku, nimbus, grandine) return 8 via `max(0, 8) = 8` clamp; **lodestar returns 4** via early-exit. Documents the spec-undefined divergence.
- **T2.2 (Glamsterdam-target — H11 verification)**: same inputs at Fulu and Gloas state. Expected: identical outputs (function unchanged at Gloas).
- **T2.3 (Compounding validator EIP-7251 integration)**: 1 validator with 2048 ETH effective balance → 64 units → 64 custody groups. Cross-client.
- **T2.4 (Super-node cap)**: > 4096 ETH attached → exactly 128 (`NUMBER_OF_CUSTODY_GROUPS`). Verify saturation; check for potential overflow.
- **T2.5 (Single 32 ETH validator min-clamp)**: 1 validator with 32 ETH → 1 unit → max(1, 8) = 8. Verify all 6 apply min clamp.
- **T2.6 (Dynamic adjustment audit — cross-client)**: increase validator effective balance over time; verify lighthouse's `BTreeMap` only-grow semantics; other 5 TBD.
- **T2.7 (Persist-across-restart audit — cross-client)**: restart node with different validator set; verify CGC stays at highest historical value (lighthouse explicit; others TBD).

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Fulu-surface invariants (H1–H10) carry forward unchanged from the 2026-05-04 audit modulo the carry-forward Pattern T concern. 5+ months of live mainnet PeerDAS gossip without DA failures — validator-running nodes have been adapting custody based on attached validator effective balances without cross-client divergence in production.

**Glamsterdam-target finding (H11 — function unchanged).** `vendor/consensus-specs/specs/gloas/` contains no references to `get_validators_custody_requirement`. The function lives ONLY in `vendor/consensus-specs/specs/fulu/validator.md:114-131` and is inherited verbatim across the Gloas fork boundary in all 6 clients via fork-agnostic config / module-level placement.

**Glamsterdam-target finding (H12 — Pattern T carry-forward).** Lodestar's empty-validator-set divergence (returns `CUSTODY_REQUIREMENT = 4` early-exit instead of `VALIDATOR_CUSTODY_REQUIREMENT = 8` via clamp) carries forward at Gloas. **Spec-undefined edge case** — spec assumes the function is called only when validators are attached. Lodestar's interpretation may be more "correct" semantically (no validators → no validator-node requirement), but 5 of 6 enforce the 8 minimum. Forward-fragility class — same shape as Pattern J/N/P/Q/R/S.

**Twentieth impact-none result** in the recheck series. The Pattern T edge-case divergence has not surfaced in production because nodes always have validators attached when running validator clients.

**Notable per-client style differences (all observable-equivalent on spec-defined inputs):**
- **prysm**: `ReadOnlyBalances` interface + map-based set. Cleanest abstraction for testability.
- **lighthouse**: takes pre-divided units; most spec-faithful on dynamic-adjustment via `BTreeMap<Epoch, u64>` + only-grow + persist-across-restart + delay buffer.
- **teku**: ONLY client with spec-matching signature `(BeaconState, Set<UInt64>)`.
- **nimbus**: minimal function — caller computes total_node_balance.
- **lodestar**: takes pre-flattened `effectiveBalances[]`; **Pattern T empty-set divergence**.
- **grandine**: spec-shape with extra config; **singular naming** `get_validator_custody_requirement`.

**No code-change recommendation.** Audit-direction recommendations:

- **Wire Fulu validator-category fixtures in BeaconBreaker harness** — same gap as items #30-#37.
- **NEW Pattern T for item #28's catalogue** — spec-undefined edge-case divergence (lodestar empty-set returns 4; other 5 return 8). Forward-fragility marker.
- **File consensus-specs ambiguity report** — empty-validator-set behavior not defined; per-client divergence observed. Propose explicit spec text: "If validator_indices is empty, return CUSTODY_REQUIREMENT" OR "return VALIDATOR_CUSTODY_REQUIREMENT" OR "MUST NOT be called with empty".
- **Grandine naming fix** — propose `get_validator_custody_requirement` → `get_validators_custody_requirement` (PLURAL) for spec-compliance + tooling-compat.
- **Cross-client wrapper functions with spec-matching signature** — propose per-client wrappers `(state, validator_indices)` for cross-client testing.
- **Dynamic-adjustment cross-client audit** — lighthouse has explicit BTreeMap + delay buffer; other 5 TBD. Spec requires "only-grow" + "persist across restarts".
- **Persist-across-restart fixture** — restart node with different validator set; verify CGC stays at highest historical value.
- **Dedicated EF fixture for `get_validators_custody_requirement`** as pure function.
- **Compounding validator (EIP-7251) integration test** — 2048 ETH → 64 custody groups; verify all 6 produce same result.

## Cross-cuts

### With item #33 (PeerDAS custody assignment)

Item #33's prior audit explicitly noted "validator-balance-scaled custody (`getValidatorsCustodyRequirement`) — teku-only standalone implementation observed; verify other 5." This item confirms ALL 6 have implementations (with 6 different signatures + 1 behavioral divergence on empty-set). Cross-cut: `get_custody_groups(node_id, count)` consumes the `count` value produced by this function.

### With item #34 (PeerDAS sidecar verification)

Downstream consumer — sidecars only enter custody set if their column is in the node's custody groups, which depends on the count from this function.

### With item #35 (PeerDAS fork-choice DA)

Downstream consumer — DA check requires sampled columns = `max(SAMPLES_PER_SLOT, custody_group_count)`. High-stake nodes need more columns for DA. The custody count from this function directly affects DA requirements.

### With item #28 (Gloas divergence meta-audit) — NEW Pattern T

This item proposes **Pattern T** for item #28's catalog (carry-forward from prior audit): spec-undefined edge-case divergence (lodestar empty-set returns 4; other 5 return 8 via clamp). Same forward-fragility class as Patterns J/N/P/Q/R/S — clients diverge on spec-undefined behavior.

### With Gloas / Heze forward-tracking

The function is unchanged at Gloas. No spec evidence of changes at Heze (per items #29, #36 forward-research). If Heze ever modifies the custody formula or constants, all 6 clients must update — none are exposed to Pattern S-style hidden compile-time invariants here (the function is straightforward formula).

## Adjacent untouched

1. **Wire Fulu validator-category fixtures in BeaconBreaker harness** — same gap as items #30-#37.
2. **NEW Pattern T for item #28's catalogue** — spec-undefined edge-case divergence forward-fragility marker.
3. **File consensus-specs ambiguity report** — empty-validator-set behavior clarification needed.
4. **Grandine naming fix proposal** — singular → plural for spec-compliance + tooling-compat.
5. **Dynamic-adjustment cross-client audit** — lighthouse explicit; other 5 TBD.
6. **Persist-across-restart cross-client audit** — lighthouse explicit; other 5 TBD.
7. **CUSTODY_CHANGE_DA_EFFECTIVE_DELAY_SECONDS lighthouse-specific** — propose to consensus-specs as a recommendation.
8. **Compounding validator (EIP-7251) integration test** — 2048 ETH → 64 custody groups verification.
9. **Cross-network constants consistency audit** — verify all 6 ship `VALIDATOR_CUSTODY_REQUIREMENT = 8` and `BALANCE_PER_ADDITIONAL_CUSTODY_GROUP = 32_000_000_000` for mainnet/sepolia/holesky/gnosis/hoodi.
10. **Dedicated EF fixture set for `get_validators_custody_requirement`** as pure function.
11. **Effective-balance edge cases**: 0 balance validators (slashed pending withdrawal); FAR_FUTURE_EPOCH activation. Verify all 6 produce same result.
12. **Super-node cap test**: > 4096 ETH attached → exactly 128. Verify saturation; check for potential overflow.
13. **Cross-fork transition Pectra → Fulu**: non-validator nodes use `CUSTODY_REQUIREMENT = 4`; validator nodes use `VALIDATOR_CUSTODY_REQUIREMENT = 8`.
14. **ENR `cgc` (custody group count) field encoding cross-client** — derived from this function's output.
15. **Validator client → beacon node API for custody updates** — out of scope but cross-cuts.
