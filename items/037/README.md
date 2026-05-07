# Item 37 — `compute_subnet_for_data_column_sidecar` + `DATA_COLUMN_SIDECAR_SUBNET_COUNT` (EIP-7594 PeerDAS gossip subnet derivation)

**Status:** no-divergence-pending-fixture-run — audited 2026-05-04. **Eighth Fulu-NEW item, fourth PeerDAS audit** (after #33 custody, #34 verify pipeline, #35 fork-choice DA). The gossipsub subnet derivation primitive: maps a column index to its data column sidecar subnet topic. Cross-client divergence here would cause sidecars to be sent on wrong subnets → peers don't see them → PeerDAS DA failure.

The function is trivially small (1 line of pseudocode):
```python
def compute_subnet_for_data_column_sidecar(column_index: ColumnIndex) -> SubnetID:
    return SubnetID(column_index % DATA_COLUMN_SIDECAR_SUBNET_COUNT)
```

But it's foundational: every PeerDAS gossip publish/subscribe operation depends on this. Cross-cuts items #33 (custody assignment derives column indices) + #34 (gossip validation checks `compute_subnet_for_data_column_sidecar(sidecar.index) == subnet_id`) + #35 (fork-choice DA depends on receiving sidecars via correct subnets).

**Mainnet preset**: `NUMBER_OF_COLUMNS = 128` and `DATA_COLUMN_SIDECAR_SUBNET_COUNT = 128`, so the modulo is trivially `column_index` itself. **All 6 clients consistent on mainnet behavior; divergence risk is purely in the formula correctness for non-mainnet presets.**

## Scope

In: `compute_subnet_for_data_column_sidecar(column_index)` — single-line modulo function; `DATA_COLUMN_SIDECAR_SUBNET_COUNT = 128` constant cross-network consistency; `compute_subnets_from_custody_group` derived function (cross-cuts item #33); gossip-validation usage (sidecar subnet match check).

Out: gossipsub topic encoding (`data_column_sidecar_{subnet_id}` topic name; gossip-layer protocol); ENR `cgc` field encoding; `DataColumnsByRootIdentifier` SSZ schema (Track E); `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` boundary (item #35 covered).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | `compute_subnet_for_data_column_sidecar(column_index) = column_index % DATA_COLUMN_SIDECAR_SUBNET_COUNT` | ✅ all 6 | Spec single-line. |
| H2 | `DATA_COLUMN_SIDECAR_SUBNET_COUNT = 128` on mainnet (matches `NUMBER_OF_COLUMNS`) | ✅ all 6 | Confirmed in `consensus-specs/configs/mainnet.yaml` + nimbus `presets.nim` + others. |
| H3 | At mainnet preset, `compute_subnet_for_data_column_sidecar(c) = c` for all `c < 128` (trivial identity) | ✅ all 6 | `c % 128 = c` when `c < 128`. |
| H4 | At non-mainnet presets where `DATA_COLUMN_SIDECAR_SUBNET_COUNT != NUMBER_OF_COLUMNS`, the modulo is non-trivial | ✅ all 6 (formula correctness) | All 6 use `%` operator. |
| H5 | Gossip-validation usage: REJECT sidecar if `compute_subnet_for_data_column_sidecar(sidecar.index) != subnet_id` | ✅ all 6 | Standard p2p contract. |
| H6 | `compute_subnets_from_custody_group(g)` = unique-set of `compute_subnet_for_data_column_sidecar(c)` for `c in compute_columns_for_custody_group(g)` | ✅ all 6 | Composed from H1 + item #33's `compute_columns_for_custody_group`. |
| H7 | Type signature: `column_index: ColumnIndex (uint64)` → `SubnetID (uint64)` | ✅ all 6 | All 6 use uint64. |
| H8 | Pre-Fulu: function not defined; gossip uses blob_sidecar subnets instead | ✅ all 6 | Function gated on Fulu fork. |
| H9 | Per-network override: testnets may use different constants | ✅ all 6 | Constant read from config, not hardcoded (with one exception — see Notable findings). |
| H10 | The mapping is deterministic and bijection on `[0, NUMBER_OF_COLUMNS) → [0, DATA_COLUMN_SIDECAR_SUBNET_COUNT)` only when both equal | ✅ all 6 | At mainnet (128 == 128), bijection; at devnets where SUBNET_COUNT < NUMBER_OF_COLUMNS, multiple columns share a subnet. |

## Per-client cross-reference

| Client | Function location | Implementation | Constant source |
|---|---|---|---|
| **prysm** | `core/peerdas/p2p_interface.go:207` `ComputeSubnetForDataColumnSidecar(columnIndex uint64) uint64` | `columnIndex % params.BeaconConfig().DataColumnSidecarSubnetCount` | runtime config |
| **lighthouse** | `consensus/types/src/data/data_column_subnet_id.rs:28` `DataColumnSubnetId::from_column_index(column_index, spec)` | `column_index.safe_rem(spec.data_column_sidecar_subnet_count).expect(...)` | runtime config; safe arithmetic |
| **teku** | `MiscHelpersFulu.java:152` `computeSubnetForDataColumnSidecar(columnIndex) -> UInt64` | `columnIndex.mod(specConfigFulu.getDataColumnSidecarSubnetCount())` | runtime config |
| **nimbus** | `spec/network.nim:140` `compute_subnet_for_data_column_sidecar(column_index)` | `column_index mod DATA_COLUMN_SIDECAR_SUBNET_COUNT` with **`static: doAssert DATA_COLUMN_SIDECAR_SUBNET_COUNT == NUMBER_OF_COLUMNS`** at line 142 | **HARDCODED constant** `DATA_COLUMN_SIDECAR_SUBNET_COUNT* = 128` at `datatypes/fulu.nim:52` |
| **lodestar** | `beacon-node/src/util/dataColumns.ts:144` `computeSubnetForDataColumn(config, columnIndex) -> number` | `columnIndex % config.DATA_COLUMN_SIDECAR_SUBNET_COUNT` | runtime config |
| **grandine** | `helper_functions/src/misc.rs:356` `compute_subnet_for_data_column_sidecar(config, column_index) -> SubnetId` | `column_index % config.data_column_sidecar_subnet_count` | runtime config |

## Notable per-client findings

### Nimbus has a load-bearing compile-time invariant assertion

`nimbus/beacon_chain/spec/network.nim:139-144`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-alpha.3/specs/fulu/p2p-interface.md#compute_subnet_for_data_column_sidecar
func compute_subnet_for_data_column_sidecar*(column_index: ColumnIndex): uint64 =
  # Parts of Nimbus use the subnet number and column ID semi-interchangeably
  static: doAssert DATA_COLUMN_SIDECAR_SUBNET_COUNT == NUMBER_OF_COLUMNS

  column_index mod DATA_COLUMN_SIDECAR_SUBNET_COUNT
```

**Compile-time assertion**: `static: doAssert DATA_COLUMN_SIDECAR_SUBNET_COUNT == NUMBER_OF_COLUMNS`. This BAKES IN the assumption that the mapping is the identity on mainnet. The comment is explicit: **"Parts of Nimbus use the subnet number and column ID semi-interchangeably"**.

**Forward-fragility class** (NEW Pattern S for item #28):
- If a future spec change makes `DATA_COLUMN_SIDECAR_SUBNET_COUNT != NUMBER_OF_COLUMNS` (e.g., Heze halves the subnet count for fewer-but-richer subnets), nimbus would fail to compile — explicit fail.
- BUT the comment warns that "parts of nimbus use the subnet number and column ID semi-interchangeably" — even if nimbus is updated to use the modulo correctly in this function, OTHER parts of nimbus that conflate subnet ID and column ID would silently produce wrong results.
- **Hidden coupling**: any change to the subnet/column relationship requires auditing ALL nimbus call sites, not just `compute_subnet_for_data_column_sidecar`.

**Only client with this hidden coupling.** Other 5 use `runtime config` for the constant — would automatically adapt to spec changes.

### Nimbus also HARDCODES the constant in code

`nimbus/beacon_chain/spec/datatypes/fulu.nim:52`:
```nim
DATA_COLUMN_SIDECAR_SUBNET_COUNT* = 128
```

A compile-time constant, NOT read from runtime config. Other 5 read from config (per-network overridable). At mainnet, both produce 128, but **nimbus would NOT pick up a runtime config override**.

**Cross-network risk**: if a testnet (e.g., devnet-13) sets `DATA_COLUMN_SIDECAR_SUBNET_COUNT: 64` in its YAML config, nimbus would still use 128 (compile-time) while other 5 would correctly read 64. **Observable divergence on non-mainnet.**

**Mitigation**: nimbus's `mainnet-non-overriden-config.yaml:166` lists DATA_COLUMN_SIDECAR_SUBNET_COUNT as non-overridden — confirming the design choice that this constant is fixed per nimbus build, not per network.

### Lighthouse uses `safe_rem` with explicit panic message

`lighthouse/consensus/types/src/data/data_column_subnet_id.rs:28-35`:
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

`safe_rem` returns `Result<u64, ArithError>` (handles div-by-zero). The `.expect()` documents the invariant. **Defensive against divide-by-zero** if config is malformed (`DATA_COLUMN_SIDECAR_SUBNET_COUNT = 0`).

Other 5 clients would crash/error on div-by-zero without the explicit message:
- prysm: Go `%` returns runtime panic `integer divide by zero`
- teku: Java `mod()` throws `ArithmeticException: / by zero`
- nimbus: Nim `mod` returns runtime error
- lodestar: TypeScript `%` returns `NaN` (silent!)
- grandine: Rust `%` panics on div-by-zero

**Lodestar's silent NaN is concerning** — would propagate as `NaN` subnet ID, causing downstream silent failures vs explicit panic.

### Grandine `const fn` (compile-time evaluable)

`grandine/helper_functions/src/misc.rs:356`:
```rust
#[must_use]
pub const fn compute_subnet_for_data_column_sidecar(
    config: &Config,
    column_index: ColumnIndex,
) -> SubnetId {
    column_index % config.data_column_sidecar_subnet_count
}
```

`const fn` annotation — function CAN be evaluated at compile time if the inputs are known. **Performance optimization** at code-gen time. Other 5 clients evaluate at runtime.

### Lodestar function is NOT exported

`lodestar/packages/beacon-node/src/util/dataColumns.ts:144`:
```typescript
function computeSubnetForDataColumn(config: ChainForkConfig, columnIndex: ColumnIndex): number {
  return columnIndex % config.DATA_COLUMN_SIDECAR_SUBNET_COUNT;
}
```

NO `export` keyword — this is a **PRIVATE function** within `dataColumns.ts`. The exported version (used elsewhere) is `computeSubnetForDataColumnSidecar` per item #34's lodestar gossip validation. Two functions for the same operation; **internal duplication risk**.

### Naming: lodestar uses `computeSubnetForDataColumn` (no `Sidecar` suffix)

Lodestar's private function name: `computeSubnetForDataColumn` (no `Sidecar`). Spec uses `compute_subnet_for_data_column_sidecar`. Other 5 clients match spec naming. **Cosmetic divergence** — not behaviorally significant but easy to confuse with a different function (especially since lodestar may have BOTH `computeSubnetForDataColumn` private AND `computeSubnetForDataColumnSidecar` public elsewhere — verify cross-cut at item #34's `dataColumnSidecar.ts:44 computeSubnetForDataColumnSidecar`).

### Live mainnet validation

5+ months of PeerDAS gossip since 2025-12-03 with all 6 clients agreeing on subnet derivation. If any client computed different subnets, sidecars would be sent on wrong topics → peers wouldn't see them → DA failures → finality loss. **Live behavior validates source review.**

## Cross-cut chain

This audit closes the PeerDAS gossip-subnet derivation surface and cross-cuts:
- **Item #33** (PeerDAS custody assignment): `compute_columns_for_custody_group(g) = [g]` (mainnet) maps custody groups to column indices; `compute_subnet_for_data_column_sidecar(c) = c` (mainnet) maps column indices to subnets. Composition: custody group `g` → subnet `g` (identity at mainnet).
- **Item #34** (PeerDAS sidecar verification): gossip validation checks `compute_subnet_for_data_column_sidecar(sidecar.index) == subnet_id`; nimbus uses this in `gossip_processing/gossip_validation.nim:656`.
- **Item #35** (fork-choice DA): depends on receiving sidecars via correct subnets; cross-client subnet divergence would cause sidecars to be missed → DA failures.
- **Item #28 NEW Pattern S**: hidden compile-time invariant assertion — nimbus alone has `static: doAssert DATA_COLUMN_SIDECAR_SUBNET_COUNT == NUMBER_OF_COLUMNS` with explicit "subnet number and column ID semi-interchangeably" comment. Same forward-fragility class as Pattern P (grandine hardcoded gindex 11).

## Adjacent untouched Fulu-active

- `data_column_sidecar_{subnet_id}` gossipsub topic name encoding cross-client
- ENR `cgc` (custody group count) field encoding/decoding
- `DataColumnsByRootIdentifier` SSZ schema (Track E)
- `compute_subnets_from_custody_group` cross-client (item #33 partially covered; lighthouse explicit `compute_subnets_for_node`)
- `BLOB_SIDECAR_SUBNET_COUNT` (Deneb-heritage) cross-client consistency
- Cross-network `DATA_COLUMN_SIDECAR_SUBNET_COUNT` consistency at mainnet/sepolia/holesky
- `MAX_REQUEST_DATA_COLUMN_SIDECARS` wire limit cross-client
- nimbus "subnet number and column ID semi-interchangeable" call sites — full audit needed
- Heze pre-emptive: if Heze changes the subnet/column ratio, identify nimbus call sites that would silently break
- div-by-zero defense cross-client (lighthouse explicit; lodestar silent NaN; others panic)
- Cross-fork transition Pectra → Fulu (subnet derivation switches from blob to column)

## Future research items

1. **Wire Fulu networking-category fixtures** in BeaconBreaker harness — same blocker as items #30/#31/#32/#33/#34/#35/#36 (now spans 8 Fulu items + 7 sub-categories). **Highest-priority follow-up** — single fix unblocks all 8 items.
2. **NEW Pattern S for item #28 catalogue**: hidden compile-time invariant assertion (nimbus `static: doAssert DATA_COLUMN_SIDECAR_SUBNET_COUNT == NUMBER_OF_COLUMNS`) + explicit "subnet number and column ID semi-interchangeably" comment. Same forward-fragility class as Pattern P (grandine hardcoded gindex 11).
3. **Nimbus "subnet number and column ID semi-interchangeably" call-site audit** — find all sites where nimbus conflates subnet_id with column_index; identify which would silently break if `DATA_COLUMN_SIDECAR_SUBNET_COUNT != NUMBER_OF_COLUMNS`.
4. **Cross-network testnet consistency audit** — verify all 6 clients respect runtime `DATA_COLUMN_SIDECAR_SUBNET_COUNT` overrides at testnets. **Nimbus is the suspected divergent client** (compile-time hardcoded constant at `datatypes/fulu.nim:52`).
5. **Div-by-zero defensive programming audit** — lodestar would silently produce NaN; other 5 panic. Generate negative-test fixture with `DATA_COLUMN_SIDECAR_SUBNET_COUNT = 0` (malformed config); verify behavior.
6. **Lodestar private vs public function audit** — `computeSubnetForDataColumn` (private) vs `computeSubnetForDataColumnSidecar` (public, item #34) — verify both produce same result; check for code duplication / bug-divergence risk.
7. **Cross-fork transition fixture: Pectra → Fulu at FULU_FORK_EPOCH** — subnet derivation switches from `compute_subnet_for_blob_sidecar` to `compute_subnet_for_data_column_sidecar`; verify all 6 transition cleanly at the boundary.
8. **Devnet-style fixture with `DATA_COLUMN_SIDECAR_SUBNET_COUNT = 64`** (half-mainnet) — test that all 6 clients correctly compute non-trivial modulo (e.g., column 64 → subnet 0; column 127 → subnet 63). **Nimbus expected to fail** at compile time.
9. **`compute_subnets_from_custody_group` cross-client equivalence test** — given a custody group, verify all 6 produce same set of subnets.
10. **Generate dedicated EF fixtures** for `compute_subnet_for_data_column_sidecar` as a pure function (column_index, config → subnet_id). Currently no `compute_subnet_for_data_column_sidecar` category in EF tests; only implicit via gossip-validation tests.
11. **Heze pre-emptive: subnet derivation changes** — verify if Heze (per item #29 + item #36 forward-research) modifies the subnet/column ratio; if so, nimbus's compile-time assertion is the canary.
12. **`compute_subnet_for_blob_sidecar` cross-cut** — same modulo pattern for Deneb/Electra; verify all 6 use consistent formula across blob-vs-column subnet derivation.

## Summary

EIP-7594 PeerDAS gossip-subnet derivation is implemented byte-for-byte equivalently across all 6 clients on mainnet (where `DATA_COLUMN_SIDECAR_SUBNET_COUNT = NUMBER_OF_COLUMNS = 128` makes the modulo trivially the identity). 5 months of live mainnet PeerDAS gossip without DA failures validates source review.

Per-client divergences:
- **Nimbus has a HIDDEN compile-time invariant**: `static: doAssert DATA_COLUMN_SIDECAR_SUBNET_COUNT == NUMBER_OF_COLUMNS` with explicit "subnet number and column ID semi-interchangeably" comment. **Hardcoded constant** at `datatypes/fulu.nim:52` (NOT read from runtime config). **Forward-fragile** at any spec change to the subnet/column ratio + at non-mainnet testnets. **NEW Pattern S for item #28 catalogue.**
- **Lighthouse uses `safe_rem` with explicit `expect` message** — defensive against div-by-zero.
- **Lodestar's `%` would silently produce NaN** on `DATA_COLUMN_SIDECAR_SUBNET_COUNT = 0` — silent vs other 5's panic.
- **Lodestar function is PRIVATE** (`computeSubnetForDataColumn` not exported) — duplicates the public `computeSubnetForDataColumnSidecar`.
- **Grandine uses `const fn`** for compile-time evaluability.

**NEW Pattern S for item #28**: hidden compile-time invariant assertion (nimbus). Same forward-fragility class as Pattern P (grandine hardcoded gindex 11) — both are baked-in spec assumptions that silently break at future spec changes.

**Status**: source review confirms all 6 clients aligned at Fulu mainnet (5 months of live PeerDAS gossip without DA failures). **Fixture run pending Fulu networking-category wiring in BeaconBreaker harness** (same blocker as items #30-#36 — now 8 items).

**With this audit, the PeerDAS gossip-subnet derivation surface is closed. PeerDAS audit corpus** now spans: custody (#33) → sidecar verification (#34) → fork-choice DA (#35) → subnet derivation (#37) — four-item arc covering the consensus-critical PeerDAS surface end-to-end. Remaining PeerDAS items: `compute_matrix` / `recover_matrix` Reed-Solomon (Track F follow-up); PartialDataColumnSidecar variants; ENR `cgc` field encoding.
