---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [28, 33, 34, 35]
eips: [EIP-7594]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 37: `compute_subnet_for_data_column_sidecar` + `DATA_COLUMN_SIDECAR_SUBNET_COUNT` (EIP-7594 PeerDAS gossip subnet derivation)

## Summary

The gossipsub subnet derivation primitive that maps a column index to its data column sidecar subnet topic:

```python
def compute_subnet_for_data_column_sidecar(column_index: ColumnIndex) -> SubnetID:
    return SubnetID(column_index % DATA_COLUMN_SIDECAR_SUBNET_COUNT)
```

Foundational for all PeerDAS gossip: every publish/subscribe operation depends on this. Cross-client divergence would cause sidecars to be sent on wrong subnets → peers don't see them → PeerDAS DA failure → finality loss.

**Mainnet preset**: `NUMBER_OF_COLUMNS = 128` and `DATA_COLUMN_SIDECAR_SUBNET_COUNT = 128`, so the modulo reduces to identity (`column_index % 128 = column_index` for `column_index < 128`).

**Fulu surface (carried forward from 2026-05-04 audit; CURRENT mainnet target):** all six clients implement the formula byte-for-byte equivalently on mainnet. Live mainnet PeerDAS gossip has been operational since Fulu activation (2025-12-03) — 5+ months. Per-client divergences in:
- **nimbus**: HARDCODED `DATA_COLUMN_SIDECAR_SUBNET_COUNT = 128` constant at `datatypes/fulu.nim:52` (NOT runtime config) + `static: doAssert DATA_COLUMN_SIDECAR_SUBNET_COUNT == NUMBER_OF_COLUMNS` compile-time invariant at `network.nim:142` + explicit "subnet number and column ID semi-interchangeably" comment. **Pattern S forward-fragility marker.**
- **lighthouse**: `safe_rem` with explicit `expect` message — defensive div-by-zero handling.
- **lodestar**: silent NaN on `DATA_COLUMN_SIDECAR_SUBNET_COUNT = 0` (TypeScript `%` semantics) — only client without explicit error.
- **lodestar**: private `computeSubnetForDataColumn` (no `Sidecar` suffix; not exported); cosmetic naming divergence.
- **grandine**: `const fn` annotation (compile-time evaluable).

**Gloas surface (at the Glamsterdam target): function unchanged.** `vendor/consensus-specs/specs/gloas/` contains no `Modified compute_subnet_for_data_column_sidecar` heading. The function is referenced unchanged in the Gloas gossip validation contract at `vendor/consensus-specs/specs/gloas/p2p-interface.md:455`:

```
- _[REJECT]_ The sidecar is for the correct subnet -- i.e.
  `compute_subnet_for_data_column_sidecar(sidecar.index) == subnet_id`.
```

Same usage as Fulu (`vendor/consensus-specs/specs/fulu/p2p-interface.md:242`). The Gloas-Modified `DataColumnSidecar` (item #34 H11) removes 3 fields and adds 2, but the `index: ColumnIndex` field (used by this function) is unchanged. The subnet derivation logic operates on the same `index` input at Gloas.

**Per-client Gloas inheritance**: all 6 clients reuse Fulu implementations at Gloas via fork-agnostic config / module-level placement. No client introduces a Gloas-specific override.

**Mainnet activation status**: `GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `vendor/consensus-specs/configs/mainnet.yaml:60`. PeerDAS gossip subnet derivation continues operating on Fulu surface in production; the Gloas inheritance is source-level only.

**Cross-cut to item #28**: NEW Pattern S candidate (nimbus hidden compile-time invariant) carries forward — same forward-fragility class as Pattern P (grandine hardcoded gindex `11`).

**Impact: none.** Nineteenth impact-none result in the recheck series.

## Question

Pyspec Fulu-NEW (`vendor/consensus-specs/specs/fulu/p2p-interface.md:178-184`):

```python
def compute_subnet_for_data_column_sidecar(column_index: ColumnIndex) -> SubnetID:
    return SubnetID(column_index % DATA_COLUMN_SIDECAR_SUBNET_COUNT)
```

At Gloas: function NOT modified (no `Modified` heading in `vendor/consensus-specs/specs/gloas/`). Same usage in gossip validation contract at `vendor/consensus-specs/specs/gloas/p2p-interface.md:455`. `DataColumnSidecar.index` field unchanged at Gloas.

Three recheck questions:
1. Fulu-surface invariants (H1–H10 from prior audit) — do all six clients still implement byte-for-byte equivalent subnet derivation?
2. **At Gloas (the new target)**: is the function unchanged? Do all six clients reuse Fulu implementations at Gloas?
3. Does the nimbus hidden compile-time invariant (Pattern S candidate) still apply? Carry-forward concerns?

## Hypotheses

- **H1.** `compute_subnet_for_data_column_sidecar(column_index) = column_index % DATA_COLUMN_SIDECAR_SUBNET_COUNT`.
- **H2.** `DATA_COLUMN_SIDECAR_SUBNET_COUNT = 128` on mainnet (matches `NUMBER_OF_COLUMNS`).
- **H3.** At mainnet preset: `compute_subnet_for_data_column_sidecar(c) = c` for all `c < 128`.
- **H4.** At non-mainnet presets where `DATA_COLUMN_SIDECAR_SUBNET_COUNT != NUMBER_OF_COLUMNS`, the modulo is non-trivial.
- **H5.** Gossip validation: REJECT sidecar if `compute_subnet_for_data_column_sidecar(sidecar.index) != subnet_id`.
- **H6.** `compute_subnets_from_custody_group(g) = unique-set` of `compute_subnet_for_data_column_sidecar(c)` for `c in compute_columns_for_custody_group(g)`.
- **H7.** Type signature: `ColumnIndex (uint64) → SubnetID (uint64)`.
- **H8.** Pre-Fulu: function not defined; gossip uses blob_sidecar subnets.
- **H9.** Per-network override: testnets may use different constants (read from runtime config).
- **H10.** Mapping is deterministic; bijection on `[0, NUMBER_OF_COLUMNS)` only when both equal.
- **H11.** *(Glamsterdam target — function unchanged)*. `compute_subnet_for_data_column_sidecar` is NOT modified at Gloas. The Fulu-NEW function carries forward unchanged across the Gloas fork boundary in all 6 clients.
- **H12.** *(Glamsterdam target — DataColumnSidecar.index unchanged)*. Despite item #34's Gloas-Modified `DataColumnSidecar` (3 fields removed, 2 added), the `index: ColumnIndex` field (the function's only input) is unchanged. Subnet derivation operates on identical input at Gloas.
- **H13.** *(Glamsterdam target — nimbus Pattern S forward-fragility carry-forward)*. Nimbus's hidden compile-time invariant `static: doAssert DATA_COLUMN_SIDECAR_SUBNET_COUNT == NUMBER_OF_COLUMNS` + hardcoded constant + "subnet number and column ID semi-interchangeably" coupling carries forward at Gloas. If Heze ever modifies the subnet/column ratio, nimbus would silently break at multiple call sites beyond this function.

## Findings

H1–H13 satisfied. **No state-transition divergence at the Fulu surface; function inherited unchanged at Gloas; nimbus Pattern S concern persists unchanged.**

### prysm

`vendor/prysm/beacon-chain/core/peerdas/p2p_interface.go:207 ComputeSubnetForDataColumnSidecar(columnIndex uint64) uint64`:

```go
return columnIndex % params.BeaconConfig().DataColumnSidecarSubnetCount
```

Runtime config-keyed. No Gloas-specific code path — the function is fork-agnostic (no `version` check needed).

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓ (runtime config). H10 ✓. H11 ✓ (no Gloas redefinition). H12 ✓. H13 n/a (prysm not exposed to Pattern S).

### lighthouse

`vendor/lighthouse/consensus/types/src/data/data_column_subnet_id.rs:28-35 DataColumnSubnetId::from_column_index`:

```rust
pub fn from_column_index(column_index: ColumnIndex, spec: &ChainSpec) -> Self {
    column_index
        .safe_rem(spec.data_column_sidecar_subnet_count)
        .expect(
            "data_column_sidecar_subnet_count should never be zero if this function is called",
        )
        .into()
}
```

`safe_rem` returns `Result<u64, ArithError>` (div-by-zero safe); `.expect()` documents the invariant. Most defensive of the 6 against malformed config.

**No Gloas-specific code path.** `spec.data_column_sidecar_subnet_count` is fork-agnostic. Lighthouse Pattern M cohort gap (Gloas-ePBS) doesn't extend here — this surface is Fulu-stable.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓. H13 n/a.

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/fulu/helpers/MiscHelpersFulu.java:152 computeSubnetForDataColumnSidecar(columnIndex) -> UInt64`:

```java
return columnIndex.mod(specConfigFulu.getDataColumnSidecarSubnetCount());
```

Runtime config-keyed via `specConfigFulu`. **No Gloas override** in `MiscHelpersGloas` — fork-agnostic.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓ (no override). H12 ✓. H13 n/a.

### nimbus

`vendor/nimbus/beacon_chain/spec/network.nim:139-144`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-alpha.3/specs/fulu/p2p-interface.md#compute_subnet_for_data_column_sidecar
func compute_subnet_for_data_column_sidecar*(column_index: ColumnIndex): uint64 =
  # Parts of Nimbus use the subnet number and column ID semi-interchangeably
  static: doAssert DATA_COLUMN_SIDECAR_SUBNET_COUNT == NUMBER_OF_COLUMNS

  column_index mod DATA_COLUMN_SIDECAR_SUBNET_COUNT
```

**Pattern S candidate carry-forward**:
1. `static: doAssert DATA_COLUMN_SIDECAR_SUBNET_COUNT == NUMBER_OF_COLUMNS` — compile-time invariant. BAKES IN the mainnet assumption.
2. Explicit comment "Parts of Nimbus use the subnet number and column ID semi-interchangeably" — documents hidden coupling.
3. **Hardcoded constant**: `vendor/nimbus/beacon_chain/spec/datatypes/fulu.nim:52 DATA_COLUMN_SIDECAR_SUBNET_COUNT* = 128` — NOT runtime config. Nimbus would not pick up a testnet config override.

**Forward-fragility implications**:
- If a future spec change makes `DATA_COLUMN_SIDECAR_SUBNET_COUNT != NUMBER_OF_COLUMNS`, nimbus fails to compile here — explicit fail.
- BUT the comment warns OTHER call sites in nimbus conflate subnet_id with column_index — those would silently break.
- At Gloas: spec unchanged, so the invariant holds. **No current divergence.**
- At Heze: TBD; if Heze adjusts the subnet/column ratio, nimbus needs broader auditing.

`mainnet-non-overriden-config.yaml:166` lists `DATA_COLUMN_SIDECAR_SUBNET_COUNT` as non-overridden — confirming the design choice (fixed per nimbus build).

H1 ✓. H2 ✓. H3 ✓. **H4 ⚠** (formula correct, but hidden coupling at other call sites would break). H5 ✓. H6 ✓. H7 ✓. H8 ✓. **H9 ⚠** (hardcoded constant; non-mainnet config override silently ignored). H10 ✓. H11 ✓ (no Gloas redefinition). H12 ✓. **H13 ✓ (Pattern S concern persists)**.

### lodestar

`vendor/lodestar/packages/beacon-node/src/util/dataColumns.ts:144`:

```typescript
function computeSubnetForDataColumn(config: ChainForkConfig, columnIndex: ColumnIndex): number {
  return columnIndex % config.DATA_COLUMN_SIDECAR_SUBNET_COUNT;
}
```

Runtime config-keyed. **No `export` keyword** — function is PRIVATE within `dataColumns.ts`. Public version `computeSubnetForDataColumnSidecar` is at item #34's gossip-validation entry point. Naming divergence: lodestar's private function drops the `Sidecar` suffix.

**Silent NaN concern**: TypeScript `%` returns `NaN` for `0` divisor (silent). Other 5 panic. If `DATA_COLUMN_SIDECAR_SUBNET_COUNT` is misconfigured to 0, lodestar would propagate NaN through subnet IDs.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓. H13 n/a.

### grandine

`vendor/grandine/helper_functions/src/misc.rs:356`:

```rust
#[must_use]
pub const fn compute_subnet_for_data_column_sidecar(
    config: &Config,
    column_index: ColumnIndex,
) -> SubnetId {
    column_index % config.data_column_sidecar_subnet_count
}
```

`const fn` annotation — compile-time evaluable when inputs are known. Runtime config-keyed. **No Gloas-specific code path** — fork-agnostic.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓. H13 n/a.

## Cross-reference table

| Client | Function location | Constant source | Div-by-zero handling | Gloas redefinition |
|---|---|---|---|---|
| prysm | `core/peerdas/p2p_interface.go:207 ComputeSubnetForDataColumnSidecar` | runtime config | Go `%` panics | none — fork-agnostic |
| lighthouse | `data/data_column_subnet_id.rs:28 DataColumnSubnetId::from_column_index` | runtime config | `safe_rem` + explicit `expect` (most defensive) | none — fork-agnostic |
| teku | `MiscHelpersFulu.java:152 computeSubnetForDataColumnSidecar` | runtime config | Java `mod()` throws `ArithmeticException` | none — `MiscHelpersGloas` doesn't override |
| nimbus | `spec/network.nim:139-144` (with `static: doAssert` invariant at `:142`) | **HARDCODED** at `datatypes/fulu.nim:52` | Nim `mod` runtime error | none — fork-agnostic (but Pattern S forward-fragility) |
| lodestar | `beacon-node/src/util/dataColumns.ts:144 computeSubnetForDataColumn` (PRIVATE, no `Sidecar` suffix) | runtime config | **silent NaN** (TypeScript `%`) | none — fork-agnostic |
| grandine | `helper_functions/src/misc.rs:356` (`const fn`) | runtime config | Rust `%` panics | none — fork-agnostic |

## Empirical tests

### Fulu-surface live mainnet validation

5+ months of PeerDAS gossip since 2025-12-03 with all 6 clients agreeing on subnet derivation. If any client computed different subnets, sidecars would be sent on wrong topics → peers wouldn't see them → DA failures → finality loss. **Live behavior validates source review.**

### Gloas-surface

`GLOAS_FORK_EPOCH = FAR_FUTURE_EPOCH` per `mainnet.yaml:60`. Function unchanged at Gloas.

Concrete Gloas-spec evidence:
- `vendor/consensus-specs/specs/gloas/p2p-interface.md:455` — same `compute_subnet_for_data_column_sidecar(sidecar.index) == subnet_id` validation rule as Fulu.
- No `Modified compute_subnet_for_data_column_sidecar` heading anywhere in `vendor/consensus-specs/specs/gloas/`.

### EF fixture status

**No dedicated EF fixtures** for `compute_subnet_for_data_column_sidecar` family at `consensus-spec-tests/tests/mainnet/fulu/networking/`. Only custody fixtures (`get_custody_groups`, `compute_columns_for_custody_group`) and the `get_custody_groups_max_node_id_*` overflow fixtures (item #33).

Implicitly exercised through:
- Live mainnet PeerDAS gossip
- Gossip validation tests in each client's internal CI (out of EF scope)
- Per-client unit tests

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1**: dedicated EF fixture for `compute_subnet_for_data_column_sidecar` as pure function `(column_index, config) → subnet_id`. Cross-client byte-level equivalence at Fulu and Gloas state inputs.
- **T1.2**: wire Fulu networking-category fixtures in BeaconBreaker harness — same gap as items #30, #31, #32, #33, #34, #35, #36.

#### T2 — Adversarial probes
- **T2.1 (Pattern S forward-fragility — nimbus)**: synthetic devnet config with `DATA_COLUMN_SIDECAR_SUBNET_COUNT = 64` (half-mainnet). Expected: 5 of 6 clients compute non-trivial modulo (e.g., column 64 → subnet 0; column 127 → subnet 63). **Nimbus expected to fail at compile time** due to `static: doAssert` invariant. Forward-tracker only.
- **T2.2 (div-by-zero defensive cross-client)**: malformed config with `DATA_COLUMN_SIDECAR_SUBNET_COUNT = 0`. Expected: lighthouse logs explicit message via `.expect()`; prysm + teku + nimbus + grandine panic with default messages; **lodestar silently returns NaN**. Documents the silent-NaN risk.
- **T2.3 (Glamsterdam-target — H11 verification)**: same inputs at Fulu and Gloas state. Expected: identical subnet IDs (function unchanged at Gloas; `sidecar.index` field unchanged in the Gloas-Modified DataColumnSidecar).
- **T2.4 (nimbus "subnet semi-interchangeably" call-site audit)**: grep nimbus for sites where `subnet_id` and `column_index` are conflated. Each is a Pattern S forward-fragility risk if the subnet/column ratio ever changes.
- **T2.5 (compute_subnets_from_custody_group composition)**: given a custody group, verify all 6 produce the same set of subnets via the H6 composition rule.

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Fulu-surface invariants (H1–H10) carry forward unchanged from the 2026-05-04 audit. Live mainnet PeerDAS gossip has been operational for 5+ months — strongest possible validation that all 6 clients agree on subnet derivation.

**Glamsterdam-target finding (H11 — function unchanged).** `vendor/consensus-specs/specs/gloas/p2p-interface.md` references `compute_subnet_for_data_column_sidecar` at `:455` in the gossip-validation contract with the same usage as Fulu (`vendor/consensus-specs/specs/fulu/p2p-interface.md:242`). No `Modified` heading. The Fulu-NEW function carries forward unchanged across the Gloas fork boundary in all 6 clients via fork-agnostic config / module-level placement.

**Glamsterdam-target finding (H12 — `sidecar.index` unchanged in Modified DataColumnSidecar).** Item #34 H11 documented the Gloas-Modified `DataColumnSidecar` (3 fields REMOVED: `signed_block_header`, `kzg_commitments`, `kzg_commitments_inclusion_proof`; 2 fields ADDED: `slot`, `beacon_block_root`). The `index: ColumnIndex` field (this function's only input) is UNCHANGED. Subnet derivation operates on identical input across Fulu and Gloas.

**Glamsterdam-target finding (H13 — nimbus Pattern S forward-fragility carry-forward).** Nimbus's hidden compile-time invariant at `vendor/nimbus/beacon_chain/spec/network.nim:142`:

```nim
static: doAssert DATA_COLUMN_SIDECAR_SUBNET_COUNT == NUMBER_OF_COLUMNS
```

plus hardcoded constant at `datatypes/fulu.nim:52` (`DATA_COLUMN_SIDECAR_SUBNET_COUNT* = 128`, NOT runtime config) plus explicit "subnet number and column ID semi-interchangeably" comment. At Gloas, the invariant holds (no spec change to the ratio) — **no current divergence**. Forward-fragility marker for Heze where any subnet/column ratio change would (a) fail nimbus compile at this function and (b) silently break at OTHER nimbus call sites conflating subnet_id with column_index.

**Pattern S candidate for item #28 catalogue** (carry-forward from prior audit): hidden compile-time invariant assertion. Same forward-fragility class as Pattern P (grandine hardcoded gindex `11`) — both are baked-in spec assumptions that silently break at future spec changes.

**Nineteenth impact-none result** in the recheck series. The subnet derivation primitive is the most operationally validated PeerDAS function — 5+ months of live mainnet PeerDAS gossip without DA failures.

**Notable per-client style differences (all observable-equivalent at mainnet):**
- **prysm**: runtime config; standard Go `%`.
- **lighthouse**: `safe_rem` with explicit `.expect()` message — most defensive against div-by-zero.
- **teku**: runtime config via `specConfigFulu`; `MiscHelpersGloas` inherits without override.
- **nimbus**: HARDCODED constant + compile-time invariant + "semi-interchangeably" coupling. Pattern S forward-fragility.
- **lodestar**: private `computeSubnetForDataColumn` (no `Sidecar` suffix); silent NaN on div-by-zero.
- **grandine**: `const fn` annotation — compile-time evaluable.

**No code-change recommendation.** Audit-direction recommendations:

- **Wire Fulu networking-category fixtures in BeaconBreaker harness** — same gap as items #30-#36.
- **Add Pattern S to item #28's catalogue** — hidden compile-time invariant forward-fragility marker. Same shape as Pattern P (grandine hardcoded gindex).
- **Nimbus "subnet number and column ID semi-interchangeably" call-site audit** — find all sites where nimbus conflates `subnet_id` with `column_index`; identify which would silently break at any future spec change to the subnet/column ratio.
- **Dedicated EF fixture for `compute_subnet_for_data_column_sidecar`** — pure-function cross-client byte-level equivalence at Fulu and Gloas state inputs.
- **Cross-network testnet consistency audit** — verify all 6 clients respect runtime `DATA_COLUMN_SIDECAR_SUBNET_COUNT` overrides at testnets. **Nimbus suspected divergent at non-mainnet** (compile-time hardcoded constant).
- **Div-by-zero defensive programming cross-client** — lodestar silent NaN concern.
- **Lodestar private vs public function audit** — `computeSubnetForDataColumn` (private, this item) vs `computeSubnetForDataColumnSidecar` (public, item #34). Verify both produce same result; check for code-duplication / bug-divergence risk.

## Cross-cuts

### With item #33 (PeerDAS custody assignment)

`compute_columns_for_custody_group(g) = [g]` (mainnet) maps custody groups to column indices; `compute_subnet_for_data_column_sidecar(c) = c` (mainnet) maps column indices to subnets. Composition: custody group `g` → subnet `g` (identity at mainnet). At Gloas: same identity composition.

### With item #34 (PeerDAS sidecar verification)

Gossip validation at `vendor/consensus-specs/specs/gloas/p2p-interface.md:455` checks `compute_subnet_for_data_column_sidecar(sidecar.index) == subnet_id`. Item #34's Gloas-Modified `DataColumnSidecar` preserves the `index` field unchanged — subnet derivation operates on identical input. Cross-cut: lighthouse Pattern M cohort gap (`DataColumnSidecar::Gloas(_)` rejected) prevents the gossip-validation chain from reaching this subnet check on Gloas — but the subnet derivation function itself is correctly implemented.

### With item #35 (fork-choice DA)

DA depends on receiving sidecars via correct subnets. Cross-client subnet divergence would cause sidecars to be missed → DA failures. This item's stability is a precondition for item #35's correctness — and 5+ months of mainnet validation confirms both.

### With item #28 (Gloas divergence meta-audit)

This item proposes **Pattern S** for item #28's catalog (carry-forward from prior audit): hidden compile-time invariant assertion (nimbus `static: doAssert DATA_COLUMN_SIDECAR_SUBNET_COUNT == NUMBER_OF_COLUMNS`). Forward-fragility class — same shape as Pattern P (grandine hardcoded gindex `11`). Not a current divergence vector at Gloas; tracker only.

### With future Heze (per items #29, #36 forward-research)

If Heze ever modifies the subnet/column ratio (currently no spec evidence, but tracking via item #29's Heze finding), nimbus's hidden coupling would silently break at multiple call sites. **Heze pre-emptive audit needed**: enumerate nimbus call sites that conflate `subnet_id` and `column_index`.

## Adjacent untouched

1. **Wire Fulu networking-category fixtures in BeaconBreaker harness** — same gap as items #30-#36. Single fix unblocks 8+ Fulu items.
2. **Add Pattern S to item #28's catalogue** — hidden compile-time invariant forward-fragility marker.
3. **Nimbus "subnet number and column ID semi-interchangeably" call-site audit** — enumerate all sites where nimbus conflates subnet_id and column_index.
4. **Cross-network testnet `DATA_COLUMN_SIDECAR_SUBNET_COUNT` override audit** — verify all 6 clients respect runtime config overrides at testnets; nimbus suspected divergent.
5. **Dedicated EF fixture for `compute_subnet_for_data_column_sidecar`** — pure-function fixture set.
6. **Div-by-zero defensive programming cross-client** — lodestar silent NaN; others panic.
7. **Lodestar private vs public function audit** — `computeSubnetForDataColumn` (private) vs `computeSubnetForDataColumnSidecar` (public, item #34).
8. **`compute_subnets_from_custody_group` cross-client equivalence test** — given a custody group, verify all 6 produce same set of subnets.
9. **`compute_subnet_for_blob_sidecar` (Deneb-heritage) cross-client consistency** — same modulo pattern for pre-Fulu blob sidecars.
10. **Cross-fork transition fixture Pectra → Fulu** — subnet derivation switches from blob to column.
11. **Heze pre-emptive: subnet derivation changes** — if Heze modifies the subnet/column ratio (no current spec evidence), nimbus's compile-time assertion is the canary.
12. **`MAX_REQUEST_DATA_COLUMN_SIDECARS` wire limit cross-client** — gates how many sidecars peers request per subnet.
13. **`data_column_sidecar_{subnet_id}` gossipsub topic name encoding cross-client** — verify topic strings match.
14. **ENR `cgc` (custody group count) field encoding/decoding** — gates peer subnet subscription.
