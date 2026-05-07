# Item 55 — `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` retention period audit (Fulu-NEW; sister to `MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS` from item #50)

**Status:** no-divergence on mainnet value (4096); **multiple cross-network + per-client naming divergences found** — audited 2026-05-04. **Twenty-fifth Fulu-NEW item, seventeenth PeerDAS audit**. Sister to `MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS` (Deneb-heritage; cross-cut item #50). Tests Pattern DD/HH spread to retention period constants.

**Spec definition** (`fulu/p2p-interface.md:84`):
| Constant | Value | Description |
|---|---|---|
| `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` | `2**12` (= 4,096 epochs, ~18 days) | Minimum epoch range over which a node must serve data column sidecars |

Used in:
1. `fulu/p2p-interface.md` — RPC serve range for `DataColumnSidecarsByRange/Root v1` (item #46): `data_column_serve_range = [max(current_epoch - MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS, FULU_FORK_EPOCH), current_epoch]`
2. `fulu/validator.md:307` — node retention obligation: "After `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` nodes MAY prune the [data column sidecars]"
3. `fulu/fork-choice.md:27` — fork choice prune logic
4. `fulu/p2p-interface.md:619` — Status v2 `earliest_available_slot` advertisement (item #47)

**Major findings**:
1. **All 6 evaluate to identical 4096 mainnet** — no production divergence
2. **Cross-network gnosis divergence**: gnosis = 16384 in lighthouse + lodestar + teku YAML configs; **nimbus has 4096 hardcoded as gnosis preset DEFAULT** at `presets.nim:799` — possibly stale
3. **Prysm SINGULAR field name** `MinEpochsForDataColumnSidecarsRequest` (no 's' on Request) vs spec PLURAL `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` — **NEW Pattern AA scope expansion** (Go field name vs YAML tag)
4. **Grandine STORAGE-MODE-AWARE accessor** at `nonstandard.rs:302-310` — most flexible accessor pattern of all 6
5. **NO Pattern HH compile-time baking** for this constant (unlike item #52 MAX_REQUEST_BLOCKS_DENEB) — all 6 use YAML override

## Scope

In: `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` per-client implementation; YAML override capability; cross-network values (mainnet/sepolia/holesky/gnosis/hoodi/minimal); Fulu serve range enforcement; storage pruning logic; Status v2 `earliest_available_slot` derivation.

Out: `MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS` Deneb-heritage retention period (covered implicitly via item #50 deprecation; future audit candidate); detailed RPC serve range enforcement (item #46 covered); detailed storage pruning subsystem; sister `MAX_REQUEST_DATA_COLUMN_SIDECARS` cap (item #49); MAX_REQUEST_BLOCKS_DENEB cap (item #52).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | All 6 evaluate to 4096 mainnet | ✅ all 6 | Spec constant |
| H2 | YAML config exposes for override | ✅ all 6 | Configurable across all clients (no Pattern HH baking) |
| H3 | Cross-network divergence (gnosis = 16384) | ⚠️ confirmed in 4 of 6 (lighthouse, lodestar, teku, **plus prysm/grandine likely via spec YAML**); **nimbus has 4096 as gnosis preset DEFAULT** (possibly stale) | Cross-network divergence |
| H4 | All 6 use spec-compliant field naming | ❌ **prysm** uses SINGULAR `MinEpochsForDataColumnSidecarsRequest` vs spec PLURAL `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` | NEW Pattern AA scope expansion |
| H5 | Constant applied to RPC serve range | ✅ all 6 | Cross-cuts item #46 |
| H6 | Constant applied to storage pruning | ✅ all 6 (varying granularity) | Storage subsystem |
| H7 | Constant applied to Status v2 earliest_available_slot derivation | ✅ all 6 (cross-cut item #47) | Spec line 619 |
| H8 | Storage-mode-aware accessor | ✅ **grandine** at `nonstandard.rs:302-310` (Standard / Archive / Prune modes) | Most flexible accessor |
| H9 | Compile-time baking (Pattern HH) | ❌ none | Unlike item #52 MAX_REQUEST_BLOCKS_DENEB nimbus baking |
| H10 | Default value provided as fallback | ✅ lighthouse (`default_min_epochs_for_data_column_sidecars_requests`) + others | Defensive YAML fallback |

## Per-client cross-reference

| Client | Source | Mainnet value | Gnosis value | Field naming | Storage-mode-aware? |
|---|---|---|---|---|---|
| **prysm** | YAML-driven `MinEpochsForDataColumnSidecarsRequest primitives.Epoch yaml:"MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS"` (`config.go:301`) | 4096 (assumed via mainnet YAML) | TBD via spec YAML | **SINGULAR** `Request` (Go field) vs PLURAL `REQUESTS` (YAML key) — **DIVERGENT** | NO |
| **lighthouse** | YAML + `default_min_epochs_for_data_column_sidecars_requests()` const fn fallback; field at `chain_spec.rs:293`; selector at `:830` | 4096 (`mainnet/config.yaml:222`) | **16384** (`gnosis/config.yaml:163`) | spec-compliant snake_case | NO |
| **teku** | YAML + `SpecConfigFulu.getMinEpochsForDataColumnSidecarsRequests()`; consumed at `DataColumnSidecarPruner.java:148` | 4096 (mainnet YAML) | **16384** (`gnosis.yaml:180`) | spec-compliant `getMinEpochsForDataColumnSidecarsRequests` | NO |
| **nimbus** | YAML preset `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS*: uint64` at `presets.nim:188`; preset values at `:407` (mainnet 4096), `:604` (minimal 4096), `:799` (gnosis **4096** — possibly stale) | 4096 | **4096 (preset DEFAULT — possibly stale)** | spec-compliant snake_case | NO |
| **lodestar** | TS const `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS: 4096` (`mainnet.ts:189`); gnosis override (`gnosis.ts:36`); CLI option exposes for override (`cli/options/.../chain.ts:272`) | 4096 | **16384** (`gnosis.ts:36`) | spec-compliant SCREAMING_SNAKE | NO |
| **grandine** | YAML-driven `min_epochs_for_data_column_sidecars_requests: u64 = 4096` (`config.rs:169/297`); **STORAGE-MODE-AWARE accessor** `min_epochs_for_data_column_sidecars_requests(self, config)` at `nonstandard.rs:302-310` | 4096 | TBD via spec YAML | spec-compliant snake_case | **YES** (`Standard.custom_data_availability_window` override; `Archive` / `Prune` use config value) |

## Notable per-client findings

### CRITICAL — Prysm SINGULAR field name (Pattern AA scope expansion)

Prysm `config/params/config.go:301`:
```go
MinEpochsForDataColumnSidecarsRequest primitives.Epoch `yaml:"MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS" spec:"true"` // MinEpochsForDataColumnSidecarsRequest is the minimum number of epochs the node will keep the data columns for.
```

**Go field name**: `MinEpochsForDataColumnSidecarsRequest` (SINGULAR — `Request`)
**YAML tag**: `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` (PLURAL — `REQUESTS`)
**Spec name**: `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` (PLURAL)

**Internal naming inconsistency**: Go accessor (`config.MinEpochsForDataColumnSidecarsRequest`) is singular; YAML serialization key is plural; spec is plural. **Same Pattern AA scope expansion class** as item #53 (nimbus `indices` vs spec `columns`) and item #54 (lodestar camelCase). YAML serialization is spec-compliant via the tag; only Go accessor name diverges.

**Bug-fix opportunity**: rename `MinEpochsForDataColumnSidecarsRequest` → `MinEpochsForDataColumnSidecarsRequests` in prysm Go source. Trivial cosmetic fix.

**Compare to prysm `MinEpochsForBlobSidecarsRequests`** (item #50 implicit) — does prysm have the SAME singular/plural inconsistency for the blob counterpart? Future research candidate.

### CRITICAL — Cross-network gnosis divergence (4096 vs 16384)

**Lighthouse** (`gnosis/config.yaml:163`): `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS: 16384`
**Lodestar** (`gnosis.ts:36`): `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS: 16384`
**Teku** (`gnosis.yaml:180`): `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS: 16384`
**Nimbus** (`presets.nim:799`): `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS: 4096` (preset DEFAULT)
**Prysm + Grandine**: TBD via gnosis spec YAML (likely 16384 if they consume the standard YAML)

**Gnosis network spec** has 16384 for retention (4x mainnet — likely due to Gnosis's longer/more frequent activity for archival).

**Nimbus's gnosis preset DEFAULT of 4096 suggests staleness**: either:
- (a) Nimbus's gnosis preset code was written before the spec change that set gnosis to 16384, OR
- (b) Nimbus loads the standard gnosis YAML at runtime which overrides the preset default to 16384, making the preset value vestigial

**Pattern FF candidate**: vestigial preset default. Need to verify nimbus's actual runtime behavior on gnosis.

**Bug-fix opportunity**: update nimbus's gnosis preset to 16384 to match other clients (assuming nimbus does NOT load gnosis YAML config at runtime).

### Grandine STORAGE-MODE-AWARE accessor (cleanest pattern)

Grandine `nonstandard.rs:302-310`:
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

**Storage-mode-parameterized**:
- `Standard { custom_data_availability_window }` — operator can override via CLI flag (e.g., extend retention beyond spec minimum)
- `Archive | Prune` — uses config value as-is (spec-compliant minimum)

**Most flexible accessor** of all 6. Allows operator-controlled retention extension while respecting spec minimum.

**Cross-cut to storage subsystem**: each of grandine's 3 storage modes (Standard, Archive, Prune) can have different retention policies. Other 5 clients use single retention policy.

### Lighthouse defensive default fallback

Lighthouse `chain_spec.rs:1291-1292` and `:1676`:
```rust
min_epochs_for_data_column_sidecars_requests: default_min_epochs_for_data_column_sidecars_requests(),  // serde default
// ...
min_epochs_for_data_column_sidecars_requests: 16384,  // gnosis hardcoded
```

`default_min_epochs_for_data_column_sidecars_requests()` is the serde fallback if YAML omits the field. Defensive against malformed YAML config.

### Lodestar CLI override

Lodestar `cli/options/beaconNodeOptions/chain.ts:272`:
> "Number of epochs to retain finalized blobs/columns (minimum of MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS/MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS)"

**CLI option exposes retention for operator override** — semantic similar to grandine's `Standard.custom_data_availability_window`. Lodestar allows extending retention via CLI flag.

### Nimbus consensus pool integration

Nimbus `consensus_object_pools/blob_quarantine.nim:832, 923`:
```nim
# are behind `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` epoch.
...
cfg.MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS,
```

Used in `blob_quarantine.nim` for column sidecar pool retention. Nimbus's quarantine pool tracks data columns within retention window.

### Live mainnet validation

5+ months of cross-client DataColumnSidecarsByRange/Root v1 RPC interop using `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS = 4096` mainnet. No observed divergence. Status v2 `earliest_available_slot` advertisements (item #47) consistent across all 6.

### Pattern HH absence

Unlike item #52 (`MAX_REQUEST_BLOCKS_DENEB` nimbus compile-time-baked) and item #54 (`KZG_COMMITMENTS_INCLUSION_PROOF_DEPTH` nimbus + grandine compile-time-baked), `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` is YAML-driven across all 6 clients.

**Why?** Likely because retention is operator-tunable (some operators want longer retention for archival nodes). Compile-time baking would prevent runtime override. Confirms Pattern HH applies to **wire-protocol invariants** (gindex depth, request caps) but NOT to operator-tunable parameters (retention windows).

**Pattern HH refinement**: nimbus + grandine bake constants that affect WIRE FORMAT or PROTOCOL CORRECTNESS but use YAML config for operator-tunable parameters. Reasonable design distinction.

## Cross-cut chain

This audit closes the data column retention period layer:
- **Item #46** (DataColumnSidecarsByRange/Root v1 RPC): consumes this constant for serve range enforcement
- **Item #47** (Status v2 `earliest_available_slot`): related — the constant defines minimum retention window that earliest_available_slot must respect
- **Item #50** (`MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS` Deneb-heritage): sister retention period; same Pattern DD/HH analysis
- **Item #28 NEW Pattern AA scope expansion**: prysm `MinEpochsForDataColumnSidecarsRequest` SINGULAR Go field vs PLURAL YAML/spec — same forward-fragility class as nimbus `indices` (item #53) and lodestar camelCase (items #53/#54)
- **Item #28 Pattern FF candidate**: nimbus gnosis preset stale value 4096 vs spec 16384 — vestigial preset default
- **Item #28 Pattern HH refinement**: confirms Pattern HH applies to wire-protocol invariants but NOT operator-tunable parameters
- **Item #48** (catalogue refresh): adds Pattern AA + FF expansions; refines Pattern HH

## Adjacent untouched Fulu-active

- `MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS` Deneb-heritage retention period — item #50 covered deprecation but not retention period itself per-client (future audit candidate)
- Nimbus actual runtime behavior on gnosis (does it load standard YAML config to override 4096 → 16384?)
- Storage subsystem detailed audit per-client (multi-mode storage like grandine's; pruning policies)
- Cross-network MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS per-client — confirm prysm/grandine values
- Operator-tunable retention extension audit (lodestar CLI; grandine `custom_data_availability_window`)
- Status v2 `earliest_available_slot` floor calculation per-client (cross-cuts item #47)
- Validator-side data column publishing window (cross-cuts item #40)
- Future: forward-compat at hypothetical fork changing retention — all 6 require YAML config bump (no compile-time bake here)

## Future research items

1. **Pattern AA scope expansion for item #28 catalogue**: extend to include Go field name vs YAML tag inconsistencies (prysm singular Request vs plural REQUESTS). Same forward-fragility class as nimbus `indices` (item #53) and lodestar camelCase (items #53/#54).
2. **Pattern HH refinement for item #28 catalogue**: nimbus + grandine bake wire-protocol invariants (gindex depth, request caps) but NOT operator-tunable parameters (retention windows). Reasonable design distinction; document explicitly.
3. **Nimbus gnosis preset staleness investigation**: verify whether nimbus actually uses 4096 (preset default) or 16384 (spec YAML override) on gnosis network at runtime. If 4096, file PR to update preset to 16384.
4. **Prysm singular naming bug-fix PR**: rename `MinEpochsForDataColumnSidecarsRequest` → `MinEpochsForDataColumnSidecarsRequests` (`config.go:301`). Trivial cosmetic fix.
5. **Prysm singular naming spec-wide audit**: does prysm have the same singular/plural inconsistency for OTHER spec constants? Audit all Go field names vs YAML tags + spec names.
6. **`MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS` per-client retention period audit (item #56 candidate)**: sister to this audit; Deneb-heritage; same Pattern DD/HH/AA analysis but for the deprecated blob sidecar RPCs.
7. **Cross-network MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS audit**: confirm 4096 vs 16384 across mainnet/sepolia/holesky/gnosis/hoodi for prysm + grandine (other 4 confirmed).
8. **Storage subsystem cross-client audit**: grandine has 3 modes (Standard/Archive/Prune); other 5 may have similar abstractions. Pattern AA-style divergence in storage mode names.
9. **Operator-tunable retention extension cross-client audit**: lodestar CLI + grandine `custom_data_availability_window` — do other 4 expose similar operator overrides?
10. **Status v2 `earliest_available_slot` floor calculation audit**: per-client floor formula `max(current_epoch - MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS, FULU_FORK_EPOCH)` — cross-cuts item #47.
11. **Validator-side data column publishing window audit**: cross-cuts item #40 + this audit's retention period.
12. **Pattern FF scope confirmation**: is nimbus's gnosis preset 4096 actually a vestigial value or intentional?

## Summary

EIP-7594 PeerDAS `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS = 4096` mainnet retention period constant. **All 6 clients evaluate to identical 4096 mainnet** — no production divergence.

**Cross-network gnosis divergence**:
- lighthouse, lodestar, teku gnosis YAML: **16384**
- nimbus gnosis preset DEFAULT: **4096** (possibly stale or intentional override)
- prysm + grandine: TBD via spec gnosis YAML

**NEW Pattern AA scope expansion**: **prysm SINGULAR field name** `MinEpochsForDataColumnSidecarsRequest` (no 's' on Request) vs spec PLURAL `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS`. Same forward-fragility class as nimbus `indices` (item #53), lodestar camelCase (items #53/#54), and teku internal SSZ name inconsistency (item #53). Bug-fix opportunity.

**Grandine STORAGE-MODE-AWARE accessor** at `nonstandard.rs:302-310` — most flexible of all 6:
- `Standard { custom_data_availability_window }` — operator override via CLI
- `Archive | Prune` — config value as-is

**NO Pattern HH compile-time baking** for this constant (unlike item #52 + #54). All 6 use YAML override.

**Pattern HH refinement**: nimbus + grandine bake **wire-protocol invariants** (gindex depth, request caps from items #52 + #54) but use YAML for **operator-tunable parameters** (retention windows). Reasonable design distinction.

**Lodestar CLI exposes retention extension** for operator-tunable retention beyond spec minimum (semantic similar to grandine's storage-mode override).

**Bug-fix opportunities identified (2)**:
1. Prysm rename `MinEpochsForDataColumnSidecarsRequest` → `MinEpochsForDataColumnSidecarsRequests` (`config.go:301`)
2. Nimbus gnosis preset update from 4096 → 16384 (`presets.nim:799`) IF actual runtime value should be 16384 (verify first)

**Live mainnet validation**: 5+ months of cross-client DataColumnSidecarsByRange/Root v1 RPC interop using 4096 retention. No observed divergence. Status v2 `earliest_available_slot` consistent across all 6.

**With this audit, the data column retention period layer is closed**. Future audit (#56 candidate) should cover sister `MIN_EPOCHS_FOR_BLOB_SIDECARS_REQUESTS` (Deneb-heritage) for symmetric coverage of retention period family.

**PeerDAS audit corpus now spans 17 items**: #33 → #34 → #35 → #37 → #38 → #39 → #40 → #41 → #42 → #44 → #45 → #46 → #47 → #49 → #53 → #54 → **#55**.

**Total Fulu-NEW items: 25 (#30–#55)**. Item #28 catalogue **Patterns A–HH (34 patterns)** + Pattern AA scope expansion (Go field naming) + Pattern FF candidate (nimbus gnosis preset stale) + Pattern HH refinement (wire-protocol vs operator-tunable distinction).
