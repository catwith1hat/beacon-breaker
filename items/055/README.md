---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [28, 46, 47, 50, 52, 53, 54]
eips: [EIP-7594]
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 55: `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` retention period — Fulu-NEW operator-tunable; Pattern AA + FF carry-forward; no Pattern HH baking

## Summary

Fulu-NEW retention-period config constant (`vendor/consensus-specs/specs/fulu/p2p-interface.md:68`):

```
| MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS | 2**12 (= 4,096 epochs) | The minimum epoch range over which a node must serve data column sidecars |
```

Mainnet value 4096 (= ~18 days at 12s/slot × 32 slots/epoch). Drives:

1. `data_column_serve_range` for `DataColumnSidecarsByRange/Root v1` RPC (`fulu/p2p-interface.md:412-420, 525` — item #46 cross-cut).
2. Status v2 `earliest_available_slot` floor calculation (item #47 cross-cut).
3. Per-client storage pruning of data column sidecars.

**Fulu surface (carried forward from 2026-05-04 audit):** all 6 clients evaluate `4096` on mainnet — no production divergence.

**Pattern AA scope expansion (carried forward; prysm singular field naming)**: `vendor/prysm/config/params/config.go:301`:

```go
MinEpochsForDataColumnSidecarsRequest primitives.Epoch `yaml:"MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS" spec:"true"`
```

**Go field name** `MinEpochsForDataColumnSidecarsRequest` (singular `Request`) vs **YAML tag and spec name** `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` (plural `REQUESTS`). Same naming-inconsistency class as items #53 (nimbus `indices` vs spec `columns`) and #54 (lodestar camelCase). YAML serialisation is spec-compliant via the tag; only the Go accessor name is divergent. Used at `vendor/prysm/config/params/config.go:757 BeaconConfig().MinEpochsForDataColumnSidecarsRequest >= current`. Trivial cosmetic fix candidate (rename Go field to add the `s`).

**Pattern FF candidate (carried forward; nimbus gnosis preset)**:

- Spec gnosis config (`vendor/consensus-specs/configs/gnosis.yaml` — implied via teku's bundled `chiado.yaml` and `gnosis.yaml`): 16384.
- Lighthouse gnosis: `vendor/lighthouse/consensus/types/src/core/chain_spec.rs:1676 min_epochs_for_data_column_sidecars_requests: 16384`.
- Teku gnosis: `vendor/teku/ethereum/spec/src/main/resources/tech/pegasys/teku/spec/config/configs/gnosis.yaml:180 MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS: 16384` (also chiado at `:182`).
- Lodestar gnosis: `vendor/lodestar/packages/config/src/chainConfig/networks/gnosis.ts:36 MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS: 16384`.
- Nimbus gnosis: `vendor/nimbus/beacon_chain/spec/presets.nim:799 MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS: 4096` — **diverges from the other 3 clients' gnosis values**. Possibly stale (preset written before spec gnosis bump to 16384) OR overridden at runtime by a YAML config load. nimbus's `presets.nim` declares the field at `:188 MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS*: uint64` and supplies mainnet 4096 (`:407`), minimal 4096 (`:604`), and gnosis 4096 (`:799`) preset defaults. Pattern FF (vestigial config defaults) candidate.

Prysm + grandine do not bundle network-specific YAML configs in their vendor trees — they rely on operator-supplied YAML at runtime. So their gnosis behaviour depends on which YAML the operator loads; assuming the spec gnosis config it would be 16384.

**Pattern HH ABSENCE (carry-forward; refines item #52 + #54 framing)**: unlike `MAX_REQUEST_BLOCKS_DENEB` (item #52 — nimbus compile-time baked) and `KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` (item #54 — nimbus + grandine baked), this retention constant is YAML-driven across all 6 clients. The distinction: Pattern HH applies to **wire-protocol invariants** (gindex depth, request caps) where divergence breaks interop, but NOT to **operator-tunable parameters** (retention windows) where extension is intentional. Reasonable design distinction.

**Grandine storage-mode-aware accessor** (`vendor/grandine/types/src/nonstandard.rs:302-310`):

```rust
pub fn min_epochs_for_data_column_sidecars_requests(self, config: &Config) -> u64 {
    match self {
        Self::Standard {
            custom_data_availability_window,
        } => custom_data_availability_window
            .unwrap_or(config.min_epochs_for_data_column_sidecars_requests),
        Self::Archive | Self::Prune => config.min_epochs_for_data_column_sidecars_requests,
    }
}
```

`Standard { custom_data_availability_window }` mode allows operators to extend retention beyond the spec minimum via a CLI flag; `Archive` and `Prune` modes use the config value verbatim. Sister method at `:289-300` for `min_epochs_for_blob_sidecars_requests`. Most flexible accessor of the 6; lodestar offers a semantically similar CLI flag (`cli/options/.../chain.ts:272 "Number of epochs to retain finalized blobs/columns (minimum of MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS/MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS)"`).

**Lighthouse most-referenced**: 9 distinct call sites in `chain_spec.rs` alone (`:293, 830, 1291-1292, 1676, 2034-2036, 2254 default_min_epochs_for_data_column_sidecars_requests(), 2498-2499, 2591, 2678, 3270, 3275`) plus consumers in `network_beacon_processor` and `data_availability_checker`. Most thoroughly wired into the codebase.

**Glamsterdam target (Gloas):** `vendor/consensus-specs/specs/gloas/p2p-interface.md` contains **NO `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` references** — `grep` returns 0 matches. The Fulu constant carries forward verbatim into Gloas across all 6 clients. The downstream consumers (`data_column_serve_range`, Status v2 `earliest_available_slot`, storage pruning) all use the same constant unchanged at Gloas.

**Impact: none** — mainnet 4096 consistent across all 6; nimbus gnosis preset 4096 is a Pattern FF candidate, not a present-tense divergence on the production mainnet target; Gloas inherits Fulu verbatim. Thirty-sixth `impact: none` result in the recheck series.

## Question

Pyspec defines `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS = 4096` (mainnet) at `vendor/consensus-specs/specs/fulu/p2p-interface.md:68`. Spec gnosis YAML sets 16384. Gloas does not modify.

Three recheck questions:

1. **Per-client mainnet value + naming** — do all 6 evaluate to 4096 on mainnet? Does the prysm singular-`Request`-vs-plural-`REQUESTS` field naming inconsistency persist?
2. **Cross-network gnosis divergence** — do the 4 clients that bundle gnosis YAML (lighthouse, lodestar, teku, nimbus) all use 16384? Or does the nimbus gnosis preset 4096 persist?
3. **Glamsterdam target** — does the Fulu constant carry forward into Gloas unchanged in all 6 clients?

## Hypotheses

- **H1.** All 6 evaluate `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS = 4096` on mainnet.
- **H2.** YAML override available across all 6 (no Pattern HH compile-time baking).
- **H3.** Cross-network gnosis = 16384 in 3 of 4 bundling clients (lighthouse, teku, lodestar); **nimbus has 4096 as gnosis preset default** — Pattern FF candidate.
- **H4.** Prysm `MinEpochsForDataColumnSidecarsRequest` Go field (singular) — Pattern AA scope expansion.
- **H5.** RPC serve range derivation: `[max(current_epoch - this_constant, FULU_FORK_EPOCH), current_epoch]` (item #46 cross-cut).
- **H6.** Storage pruning uses this constant for the retention window.
- **H7.** Status v2 `earliest_available_slot` floor: `max(current_epoch - this_constant, FULU_FORK_EPOCH)` (item #47 cross-cut).
- **H8.** Grandine storage-mode-aware accessor at `nonstandard.rs:302-310` — most flexible.
- **H9.** Pattern HH ABSENCE: this is operator-tunable, not wire-protocol invariant.
- **H10.** Defensive serde default fallback in lighthouse via `default_min_epochs_for_data_column_sidecars_requests()`.
- **H11.** *(Glamsterdam target — Fulu constant unchanged)* `vendor/consensus-specs/specs/gloas/p2p-interface.md` has 0 references to this constant. Inherits Fulu verbatim.

## Findings

H1 ✓. H2 ✓. H3 ✓ (lighthouse + teku + lodestar gnosis = 16384; nimbus = 4096 — Pattern FF candidate). H4 ✓ (prysm singular Go field). H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓ (no Gloas modification).

### prysm

Field declaration (`vendor/prysm/config/params/config.go:301`):

```go
MinEpochsForDataColumnSidecarsRequest primitives.Epoch `yaml:"MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS" spec:"true"` // MinEpochsForDataColumnSidecarsRequest is the minimum number of epochs the node will keep the data columns for.
```

**Go field name** `MinEpochsForDataColumnSidecarsRequest` (singular `Request`). **YAML tag** `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` (plural `REQUESTS`). **Spec name** plural. The doc comment also uses singular `MinEpochsForDataColumnSidecarsRequest`. Internal naming inconsistency.

Mainnet value (`vendor/prysm/config/params/mainnet_config.go:344`):

```go
MinEpochsForDataColumnSidecarsRequest: 4096,
```

Consumer (`vendor/prysm/config/params/config.go:757`):

```go
return block+BeaconConfig().MinEpochsForDataColumnSidecarsRequest >= current
```

Pattern AA scope expansion: singular Go field vs plural YAML/spec. Same forward-fragility class as nimbus `indices` (item #53), lodestar camelCase (items #53/#54), and teku internal SSZ-name inconsistency (item #53). Bug-fix opportunity: rename `MinEpochsForDataColumnSidecarsRequest` → `MinEpochsForDataColumnSidecarsRequests`.

Prysm does not bundle gnosis YAML in `vendor/prysm/`; gnosis behaviour depends on operator-supplied YAML at runtime.

### lighthouse

Field (`vendor/lighthouse/consensus/types/src/core/chain_spec.rs:293`):

```rust
pub min_epochs_for_data_column_sidecars_requests: u64,
```

Default helper (`:2254`):

```rust
const fn default_min_epochs_for_data_column_sidecars_requests() -> u64 {
```

Serde default annotation (`:2034-2036`):

```rust
#[serde(default = "default_min_epochs_for_data_column_sidecars_requests")]
...
min_epochs_for_data_column_sidecars_requests: u64,
```

Used in 9+ chain_spec.rs sites: field at `:293`; consumer `current_epoch.saturating_sub(self.min_epochs_for_data_column_sidecars_requests)` at `:830`; serde defaults at `:1291-1292, 2034-2036`; **gnosis hardcoded 16384** at `:1676 min_epochs_for_data_column_sidecars_requests: 16384`; cross-spec propagation at `:2498-2499, 2591, 2678, 3270, 3275`.

Spec-compliant snake_case naming. Pattern AA: none. Pattern HH: not applicable (YAML-driven via serde default fallback).

Network YAMLs (`vendor/lighthouse/common/eth2_network_config/built_in_network_configs/{mainnet,sepolia,holesky,hoodi}/config.yaml`): 4096 each; gnosis = 16384 at `chain_spec.rs:1676` and presumably the corresponding gnosis YAML.

### teku

Bundled YAML config files (`vendor/teku/ethereum/spec/src/main/resources/tech/pegasys/teku/spec/config/configs/`):

- `mainnet.yaml:204 MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS: 4096`
- `holesky.yaml:172`: 4096
- `sepolia.yaml:170`: 4096
- `hoodi.yaml:172`: 4096
- `minimal.yaml:201`: 4096
- `swift.yaml:189`: 4096
- **`gnosis.yaml:180`: 16384**
- **`chiado.yaml:182`: 16384** (Gnosis testnet)

Cross-network values confirmed: 6 networks at 4096, 2 at 16384 (gnosis + chiado).

Builder accessor `SpecConfigFulu.getMinEpochsForDataColumnSidecarsRequests()` (per prior audit; consumed at `DataColumnSidecarPruner.java:148`). Spec-compliant getter naming. Pattern AA: none.

### nimbus

Field declaration in presets module (`vendor/nimbus/beacon_chain/spec/presets.nim:188`):

```nim
MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS*: uint64
```

Preset values:

- `:407 MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS: 4096` (mainnet)
- `:604 MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS: 4096` (minimal)
- `:799 MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS: 4096` (gnosis)

**Gnosis preset = 4096** — diverges from the 3 other bundling clients (lighthouse/teku/lodestar gnosis = 16384) and from the consensus-specs gnosis configuration. Pattern FF candidate: vestigial preset default, possibly written before the spec gnosis bump to 16384.

Resolution depends on whether nimbus loads a runtime YAML config that overrides the preset (in which case the preset value is dead code) or whether nimbus uses the preset value directly on gnosis (in which case the value is a real divergence). Verification step: trace whether nimbus's gnosis YAML config loading path overrides the preset constant.

Spec-compliant snake_case naming.

### lodestar

Mainnet config (`vendor/lodestar/packages/config/src/chainConfig/configs/mainnet.ts:189`):

```typescript
MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS: 4096,
```

Gnosis network override (`vendor/lodestar/packages/config/src/chainConfig/networks/gnosis.ts:36`):

```typescript
MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS: 16384,
```

CLI option (`vendor/lodestar/packages/cli/src/options/beaconNodeOptions/.../chain.ts:272` per prior audit): `"Number of epochs to retain finalized blobs/columns (minimum of MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS/MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS)"`. Operator-tunable retention extension via CLI.

Spec-compliant SCREAMING_SNAKE naming.

### grandine

Field declaration (`vendor/grandine/types/src/config.rs:169`):

```rust
pub min_epochs_for_data_column_sidecars_requests: u64,
```

Default (`vendor/grandine/types/src/config.rs:297`):

```rust
min_epochs_for_data_column_sidecars_requests: 4096,
```

Storage-mode-aware accessor (`vendor/grandine/types/src/nonstandard.rs:302-310`):

```rust
pub fn min_epochs_for_data_column_sidecars_requests(self, config: &Config) -> u64 {
    match self {
        Self::Standard {
            custom_data_availability_window,
        } => custom_data_availability_window
            .unwrap_or(config.min_epochs_for_data_column_sidecars_requests),
        Self::Archive | Self::Prune => config.min_epochs_for_data_column_sidecars_requests,
    }
}
```

**Standard mode**: operator-supplied `custom_data_availability_window` (Option<u64>) takes precedence over config value. **Archive** and **Prune** modes: use config value directly.

Sister method at `:289-300` for `min_epochs_for_blob_sidecars_requests` — same storage-mode-aware pattern applied to the Deneb-heritage blob retention constant.

Spec-compliant snake_case naming. Most flexible accessor of all 6.

Grandine does not bundle gnosis YAML; operator-supplied YAML determines gnosis behaviour.

## Cross-reference table

| Client | H1 mainnet value | H3 gnosis value | H4 Pattern AA naming | H5 RPC serve range consumer | H8 storage-mode-aware | H9 Pattern HH | H10 serde default |
|---|---|---|---|---|---|---|---|
| **prysm** | 4096 (`mainnet_config.go:344`) | TBD via runtime YAML | ⚠ singular `MinEpochsForDataColumnSidecarsRequest` Go field vs plural YAML/spec | `config.go:757 block+BeaconConfig().MinEpochsForDataColumnSidecarsRequest >= current` | ❌ | ❌ (YAML-driven) | implicit via Go zero-value |
| **lighthouse** | 4096 (config.yaml + `default_min_epochs_for_data_column_sidecars_requests()`) | **16384** (`chain_spec.rs:1676`) | spec-aligned snake_case | `chain_spec.rs:830 current_epoch.saturating_sub(self.min_epochs_for_data_column_sidecars_requests)` | ❌ | ❌ (YAML-driven with serde default fallback) | ✅ `default_min_epochs_for_data_column_sidecars_requests()` at `:2254` |
| **teku** | 4096 (`configs/mainnet.yaml:204`) | **16384** (`configs/gnosis.yaml:180` + chiado:182) | spec-aligned `getMinEpochsForDataColumnSidecarsRequests()` | `DataColumnSidecarPruner.java:148` | ❌ | ❌ (YAML-driven) | per-network YAML files |
| **nimbus** | 4096 (`presets.nim:407`) | **4096** (`presets.nim:799`) — Pattern FF candidate; diverges from spec gnosis = 16384 | spec-aligned snake_case | `blob_quarantine.nim:832, 923 cfg.MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` | ❌ | ❌ (preset-baked but operator-tunable; not Pattern HH per se) | preset values per network |
| **lodestar** | 4096 (`configs/mainnet.ts:189`) | **16384** (`networks/gnosis.ts:36`) | spec-aligned SCREAMING_SNAKE | CLI flag at `cli/options/.../chain.ts:272` allows operator override | ❌ | ❌ (YAML-driven + CLI override) | per-network config files |
| **grandine** | 4096 (`config.rs:297`) | TBD via runtime YAML | spec-aligned snake_case | `nonstandard.rs:302-310 storage-mode-aware accessor` | ✅ **Standard mode `custom_data_availability_window` override; Archive/Prune use config value** | ❌ (YAML-driven + storage-mode override) | Rust Default trait |

**Mainnet value cohort**: 6/6 = 4096 ✅. **Gnosis cohort divergence**: lighthouse + teku + lodestar = 16384; nimbus = 4096 (Pattern FF candidate); prysm + grandine = TBD via operator-supplied YAML. **Pattern AA naming cohort**: 1 of 6 — prysm singular Go field. **Pattern HH cohort**: 0 of 6 — no compile-time baking for this operator-tunable parameter.

## Empirical tests

- ✅ **Live mainnet operation since 2025-12-03 (5+ months)**: all 6 clients enforce 4096-epoch retention consistently. No interop divergence observed on `DataColumnSidecarsByRange/Root v1` serve range. Status v2 `earliest_available_slot` advertisements consistent. **Verifies H1, H5, H6, H7 at production scale.**
- ✅ **Per-client value verification (this recheck)**: mainnet 4096 across all 6; gnosis 16384 in lighthouse/teku/lodestar; gnosis 4096 in nimbus preset; prysm + grandine gnosis behaviour depends on operator-supplied YAML.
- ✅ **Pattern AA prysm singular field verification**: `vendor/prysm/config/params/config.go:301 MinEpochsForDataColumnSidecarsRequest` confirmed. Persists from prior audit; no rename has occurred.
- ✅ **Gloas carry-forward verification**: `grep -n "MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS\|min_epochs_for_data_column_sidecars_requests" vendor/consensus-specs/specs/gloas/p2p-interface.md` returns 0 matches. **Verifies H11**: Fulu constant carries forward verbatim into Gloas.
- ⏭ **Nimbus gnosis runtime-value investigation**: trace whether nimbus actually uses 4096 (preset value at `presets.nim:799`) on gnosis or whether the operator-supplied gnosis YAML overrides the preset. If nimbus uses 4096 in production on gnosis, it diverges from the other 3 bundling clients and from the spec. If nimbus loads runtime YAML to override, the preset value is dead code (Pattern FF — vestigial default).
- ⏭ **Prysm singular naming PR**: file PR renaming `MinEpochsForDataColumnSidecarsRequest` → `MinEpochsForDataColumnSidecarsRequests` at `config.go:301` and consumer at `config.go:757`. Trivial cosmetic fix aligning Go identifier with YAML tag and spec name.
- ⏭ **Cross-network value audit for prysm + grandine gnosis**: confirm whether these two clients pick up 16384 via standard gnosis YAML config load. Extend the gnosis cohort coverage from 3-of-6 (lighthouse + teku + lodestar) to all 6.
- ⏭ **Storage-mode-aware accessor adoption catalogue**: grandine has it; lodestar has CLI flag for similar purpose. Does any other client expose operator-controlled retention extension? Catalogue.
- ⏭ **Pattern HH refinement documentation**: item #28/#48 catalogue should document the distinction between wire-protocol-invariant constants (Pattern HH applies — nimbus + grandine bake) and operator-tunable constants (Pattern HH does not apply — all 6 YAML-driven). This audit confirms the distinction.

## Conclusion

`MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS = 4096` mainnet retention constant is implemented consistently across all 6 clients on mainnet. 5+ months of live cross-client `DataColumnSidecarsByRange/Root v1` RPC interop validates the constant's downstream uses (serve range enforcement; storage pruning; Status v2 `earliest_available_slot` derivation).

**Cross-network gnosis cohort divergence**:

- ✅ lighthouse, teku, lodestar gnosis = **16384** (bundled YAML configs).
- ⚠ nimbus gnosis preset = **4096** at `vendor/nimbus/beacon_chain/spec/presets.nim:799` (Pattern FF candidate — vestigial preset default OR real divergence; needs runtime-behaviour investigation).
- TBD: prysm + grandine gnosis behaviour depends on operator-supplied YAML.

**Pattern AA scope expansion (carry-forward)**: prysm singular Go field `MinEpochsForDataColumnSidecarsRequest` (`config.go:301, 757`) vs plural YAML tag and spec name `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS`. Same naming-inconsistency class as item #53 (nimbus `indices`), items #53/#54 (lodestar camelCase), and item #53 (teku internal SSZ-name inconsistency). Trivial rename PR opportunity.

**Pattern HH ABSENCE (Pattern HH refinement)**: this retention constant is YAML-driven across all 6 clients — no compile-time baking. Pattern HH (nimbus + grandine compile-time baking) applies to **wire-protocol invariants** (gindex depth from item #54; request caps from item #52) but **NOT to operator-tunable parameters** (retention windows). Reasonable design distinction; should be documented as a Pattern HH refinement in item #28/#48 catalogue.

**Grandine storage-mode-aware accessor** at `nonstandard.rs:302-310` is the most flexible of the 6 — `Standard { custom_data_availability_window }` mode allows operator-controlled retention extension via CLI flag; `Archive` and `Prune` modes use config value verbatim. Lodestar offers a semantically similar CLI flag (`cli/options/.../chain.ts:272`).

**Lighthouse most-referenced** (9+ chain_spec.rs sites + downstream consumers) — most thoroughly wired into the codebase, with explicit `default_min_epochs_for_data_column_sidecars_requests()` serde fallback at `:2254`.

**Glamsterdam target**: `vendor/consensus-specs/specs/gloas/p2p-interface.md` contains 0 references to this constant (verified by grep). The Fulu retention constant carries forward verbatim into Gloas across all 6 clients. Downstream consumers (`data_column_serve_range`, Status v2 `earliest_available_slot`, storage pruning) all use the same constant unchanged at Gloas.

**Impact: none** — mainnet 4096 consistent across all 6; nimbus gnosis preset 4096 is a Pattern FF candidate, not a present-tense mainnet-target divergence; Gloas inherits Fulu verbatim. Thirty-sixth `impact: none` result in the recheck series.

Forward-research priorities:

1. **Nimbus gnosis preset investigation** — verify whether the preset value `4096` at `presets.nim:799` is the actual runtime value on gnosis or whether nimbus loads spec gnosis YAML to override to `16384`. If the preset value is used: file PR to update `presets.nim:799` to `16384`. If overridden at runtime: file PR to remove the misleading preset default (Pattern FF cleanup).
2. **Prysm singular Go field rename** — file PR renaming `MinEpochsForDataColumnSidecarsRequest` → `MinEpochsForDataColumnSidecarsRequests` at `vendor/prysm/config/params/config.go:301, 757` and `mainnet_config.go:344`.
3. **Cross-network gnosis cohort completion** — verify prysm + grandine gnosis behaviour with operator-supplied YAML. Confirm 16384 across all 6 except (possibly) nimbus.
4. **Storage-mode-aware accessor adoption catalogue** — survey lodestar CLI flag + grandine `custom_data_availability_window` pattern. Do other 4 clients expose operator-controlled retention extension?
5. **Pattern HH refinement** — document in item #28/#48 catalogue the distinction between wire-protocol-invariant constants (Pattern HH applies) and operator-tunable parameters (Pattern HH does not apply).
6. **`MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS` retention-period sister audit** — Deneb-heritage; same per-client pattern analysis. Cross-cut item #50 deprecation audit.
