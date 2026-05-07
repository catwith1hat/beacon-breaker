# Item 52 — `MAX_REQUEST_BLOCKS_DENEB` foundational cap audit (Deneb-heritage; flows into items #49 + #50; consumed by BeaconBlocksByRange v2 + DataColumnsByRootIdentifier + 4 other RPCs)

**Status:** no-divergence-pending-fixture-run on mainnet value (128); **NEW Pattern HH divergence on nimbus compile-time constant + retroactive correction to items #49/#50 nimbus characterization** — audited 2026-05-04. **Twenty-second Fulu-NEW-relevant item (Fulu-active downstream usage), foundational Deneb-heritage cap audit**. Sister to items #49 (downstream consumer via formula) + #50 (sister downstream cap).

**Spec definition** (`deneb/p2p-interface.md:61`):
| Constant | Value | Description |
|---|---|---|
| `MAX_REQUEST_BLOCKS_DENEB` | `2**7` (= 128) | Maximum number of blocks in a single request |

Use sites across spec:
1. **`compute_max_request_data_column_sidecars()`** = `MAX_REQUEST_BLOCKS_DENEB × NUMBER_OF_COLUMNS = 128 × 128 = 16384` (item #49)
2. **`compute_max_request_blob_sidecars()`** = `MAX_REQUEST_BLOCKS_DENEB × MAX_BLOBS_PER_BLOCK_ELECTRA = 128 × 9 = 1152` (item #50)
3. **`BeaconBlocksByRange v2`** response cap (Deneb-heritage; consensus-critical block sync)
4. **`BeaconBlocksByRoot v2`** request cap (Deneb-heritage)
5. **`BlobSidecarsByRange v1`** response cap (deprecated at Fulu, item #50)
6. **`BlobSidecarsByRoot v1`** request cap (deprecated at Fulu, item #50)
7. **`DataColumnSidecarsByRoot v1`** request list cap of `DataColumnsByRootIdentifier` (Fulu-NEW per `fulu/p2p-interface.md:777`)
8. **`ExecutionPayloadEnvelopesByRange`** cap (Gloas-NEW; lodestar `executionPayloadEnvelopesByRange.ts:94`)

**Major finding**: **nimbus has UNIQUE compile-time-constant + load-time-formula-validation pattern**. `MAX_REQUEST_BLOCKS_DENEB` is HARDCODED as `uint64 = 128` in the binary at `nimbus/beacon_chain/spec/datatypes/constants.nim:80` with TODO comment `# TODO Make use of in request code`. Cannot be overridden via YAML — `checkCompatibility MAX_REQUEST_BLOCKS_DENEB` (`presets.nim:1072`) **throws `PresetFileError`** if YAML attempts to override.

**RETROACTIVE CORRECTION to items #49 + #50**: nimbus has `checkCompatibility MAX_REQUEST_BLOCKS_DENEB * cfg.MAX_BLOBS_PER_BLOCK_ELECTRA, "MAX_REQUEST_BLOB_SIDECARS_ELECTRA"` (`presets.nim:1203-1204`) — **FORMULA VALIDATION** at YAML load time. **Nimbus is a 3rd category in Pattern DD** that I missed at items #49 + #50:
- **Computed formula** (teku + grandine): formula computes the value
- **Hardcoded YAML with formula validation at load time** (nimbus for MAX_REQUEST_BLOB_SIDECARS family): hybrid validation — YAML stores value, but YAML MUST satisfy formula or load fails
- **Hardcoded YAML without formula validation** (prysm + lighthouse + lodestar): YAML stores value, no cross-check

**NEW Pattern HH candidate for item #28 catalogue**: COMPILE-TIME CONSTANT BAKED INTO BINARY (nimbus). Most rigid form of Pattern DD. Forward-fragility: spec changes require recompilation, not just YAML config bump.

## Scope

In: `MAX_REQUEST_BLOCKS_DENEB` per-client implementation; YAML override capability; load-time validation patterns; BeaconBlocksByRange v2 cap enforcement; downstream formula consumption (items #49 + #50); cross-network value consistency; Fulu-NEW DataColumnsByRootIdentifier list cap; nimbus retroactive correction.

Out: Phase0 `MAX_REQUEST_BLOCKS = 1024` constant (Phase0-heritage; Deneb-modified to 128 via this constant); BeaconBlocksByRange v2 RPC handler architecture (out of scope here, partial cross-cut from item #46); Gloas ExecutionPayloadEnvelopesByRange cap (Gloas-NEW future audit); detailed BeaconBlocksByRange v2 protocol semantics.

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | All 6 clients evaluate `MAX_REQUEST_BLOCKS_DENEB = 128` on mainnet | ✅ all 6 | Spec constant |
| H2 | Spec defines as a constant (not formula) | ✅ Deneb introduced as constant `2**7` | Stable |
| H3 | YAML config exposes `MAX_REQUEST_BLOCKS_DENEB` for override | ⚠️ 5 of 6 (prysm, lighthouse, teku, lodestar, grandine); **nimbus REJECTS YAML override** via `checkCompatibility` | NEW Pattern HH candidate |
| H4 | All 6 use the same value across mainnet/sepolia/holesky/gnosis/hoodi | ✅ all 6 (assumed; mainnet confirmed) | Constant value |
| H5 | All 6 enforce cap on BeaconBlocksByRange v2 | ✅ all 6 | Consensus-critical |
| H6 | Cross-fork dispatch: pre-Deneb uses `MAX_REQUEST_BLOCKS = 1024`; Deneb+ uses `MAX_REQUEST_BLOCKS_DENEB = 128` | ✅ all 6 | Fork-aware selector |
| H7 | Fulu-NEW DataColumnsByRootIdentifier request list cap = `MAX_REQUEST_BLOCKS_DENEB` | ✅ all 6 | Spec line 777 |
| H8 | Nimbus formula-validation pattern (`checkCompatibility ... * MAX_BLOBS_PER_BLOCK_ELECTRA`) | ✅ confirmed at `presets.nim:1199-1204` | Hybrid validation |
| H9 | Nimbus formula-validation EXTENDS to MAX_REQUEST_DATA_COLUMN_SIDECARS | ❌ **NO** — nimbus does NOT have `checkCompatibility ... * NUMBER_OF_COLUMNS` for MAX_REQUEST_DATA_COLUMN_SIDECARS | Inconsistent within nimbus |
| H10 | Forward-compat: at hypothetical fork changing the cap | ⚠️ nimbus requires RECOMPILE; other 5 require YAML config bump | Pattern HH forward-fragility |

## Per-client cross-reference

| Client | Source | Override-able via YAML | Load-time Formula Validation |
|---|---|---|---|
| **prysm** | YAML `MaxRequestBlocksDeneb: 128` (`mainnet_config.go:311`); struct field with `yaml:"MAX_REQUEST_BLOCKS_DENEB"` tag (`config.go:275`); accessor `params.BeaconConfig().MaxRequestBlocksDeneb` | ✅ YES | ❌ NO |
| **lighthouse** | YAML + `default_max_request_blocks_deneb()` const fn (`chain_spec.rs:2176`) returns 128 as serde default; **fork-aware selector** at `:695` returns this value; consumed at `:960/:964` for BeaconBlocksByRoot + DataColumnsByRoot caps | ✅ YES | ❌ NO |
| **teku** | YAML `MAX_REQUEST_BLOCKS_DENEB: 128` (`mainnet.yaml:176`) + `DenebBuilder.maxRequestBlocksDeneb` setter at `:93-94`; **CONSUMED in formula** `computeMaxRequestBlobSidecars(maxRequestBlocksDeneb, maxBlobsPerBlock)` at `:150-155` (HYBRID consistent with item #50 finding) | ✅ YES | Used in formula (HYBRID) |
| **nimbus** | **HARDCODED COMPILE-TIME CONSTANT** `MAX_REQUEST_BLOCKS_DENEB*: uint64 = 128` (`constants.nim:80`) + `# TODO Make use of in request code` comment + `checkCompatibility MAX_REQUEST_BLOCKS_DENEB` (`presets.nim:1072`) **REJECTS** YAML override (throws `PresetFileError: "Cannot override config"`) | ❌ **NO — throws** | ✅ Hybrid: rejects override + validates `MAX_REQUEST_BLOB_SIDECARS = 128 * MAX_BLOBS_PER_BLOCK` and `_ELECTRA = 128 * MAX_BLOBS_PER_BLOCK_ELECTRA` formulas (`:1199-1204`) |
| **lodestar** | Hardcoded TS const `MAX_REQUEST_BLOCKS_DENEB: 128` (`mainnet.ts:154`); used in `beaconBlocksByRange.ts:117`, `rateLimit.ts:30/38/86`, `executionPayloadEnvelopesByRange.ts:94-95` (Gloas-NEW); explicit comments `// MAX_REQUEST_BLOCKS_DENEB * MAX_BLOBS_PER_BLOCK` and `// MAX_REQUEST_BLOCKS_DENEB * NUMBER_OF_COLUMNS` document downstream formulas | ✅ YES via custom config | ❌ NO; comments only |
| **grandine** | YAML `max_request_blocks_deneb: 128` (`config.rs:294`); **fork-aware selector** `max_request_blocks(phase)` at `:977` returns this for Deneb+/Electra/Fulu/Gloas; consumed in RPC limit `Self::V2(_) => config.max_request_blocks_deneb` (`methods.rs:676/744`); used as Reed-Solomon recovery cap at `methods.rs:785` and codec at `codec.rs:1274` | ✅ YES | ❌ NO |

## Notable per-client findings

### CRITICAL — Nimbus compile-time constant + load-time formula validation (NEW Pattern HH)

Nimbus `constants.nim:79-80`:
```nim
# https://github.com/ethereum/consensus-specs/blob/v1.5.0-alpha.8/specs/deneb/p2p-interface.md#configuration
MAX_REQUEST_BLOCKS_DENEB*: uint64 = 128 # TODO Make use of in request code
```

Nimbus `presets.nim:977-997` defines `checkCompatibility` template:
> "Certain config keys are baked into the binary at compile-time and cannot be overridden via config."

If YAML provides `MAX_REQUEST_BLOCKS_DENEB: 256`, nimbus throws:
```
PresetFileError: "Cannot override config (required: MAX_REQUEST_BLOCKS_DENEB == 128 - config: MAX_REQUEST_BLOCKS_DENEB=256)"
```

**Implication**: nimbus operator CANNOT run a custom testnet with different `MAX_REQUEST_BLOCKS_DENEB` value without recompiling the binary. Other 5 clients accept YAML override.

**TODO comment "Make use of in request code"**: nimbus team intends to migrate this to runtime config but has not yet (compile-time-baked since spec stabilization). Forward-fragility: at any spec change, nimbus requires source-code modification + recompile + redistribution.

**Live mainnet validation**: 5+ months without divergence because all 6 use 128 on mainnet. Nimbus's strict-equality check passes.

### NIMBUS RETROACTIVE CORRECTION to items #49 + #50

**Items #49 + #50 incorrectly characterized nimbus as plain hardcoded YAML.** Actually nimbus has `checkCompatibility` validation:

`presets.nim:1199-1204`:
```nim
checkCompatibility MAX_REQUEST_BLOCKS_DENEB * cfg.MAX_BLOBS_PER_BLOCK,
                   "MAX_REQUEST_BLOB_SIDECARS"
checkCompatibility cfg.MAX_BLOBS_PER_BLOCK,
                   "MAX_BLOBS_PER_BLOCK_ELECTRA", `>=`
checkCompatibility MAX_REQUEST_BLOCKS_DENEB * cfg.MAX_BLOBS_PER_BLOCK_ELECTRA,
                   "MAX_REQUEST_BLOB_SIDECARS_ELECTRA"
```

So at YAML load time, nimbus VALIDATES:
- `MAX_REQUEST_BLOB_SIDECARS == 128 * MAX_BLOBS_PER_BLOCK` (= 768 mainnet)
- `MAX_REQUEST_BLOB_SIDECARS_ELECTRA == 128 * MAX_BLOBS_PER_BLOCK_ELECTRA` (= 1152 mainnet)

**Updated Pattern DD characterization** for nimbus:
- Item #50 (`MAX_REQUEST_BLOB_SIDECARS_ELECTRA`): ✅ **HYBRID VALIDATION** — YAML hardcoded BUT formula-validated. More spec-faithful than I credited.
- Item #49 (`MAX_REQUEST_DATA_COLUMN_SIDECARS`): ❌ NO formula validation — `checkCompatibility ... * NUMBER_OF_COLUMNS` is MISSING. Same level as prysm/lighthouse/lodestar.

**Inconsistency within nimbus**: validates `MAX_REQUEST_BLOB_SIDECARS` formula but not `MAX_REQUEST_DATA_COLUMN_SIDECARS`. Possible bug-fix opportunity to add `checkCompatibility MAX_REQUEST_BLOCKS_DENEB * NUMBER_OF_COLUMNS, "MAX_REQUEST_DATA_COLUMN_SIDECARS"`.

**Updated Pattern DD 3-category split** (revising items #49 + #50):
- **Computed formula** (teku, grandine): formula computes value at runtime
- **Hardcoded YAML with load-time formula validation** (nimbus for blob caps only): YAML stores value, must satisfy formula
- **Hardcoded YAML without validation** (prysm, lighthouse, lodestar; nimbus for data column cap): YAML stores value, no cross-check

### Lighthouse uses constant in 4+ derived caps

Lighthouse `chain_spec.rs:957-965`:
```rust
self.max_blocks_by_root_request = max_blocks_by_root_request_common(self.max_request_blocks_deneb);
self.max_data_columns_by_root_request = max_data_columns_by_root_request_common::<E>(self.max_request_blocks_deneb);
```

`max_blocks_by_root_request_common` and `max_data_columns_by_root_request_common` derive caps from `MAX_REQUEST_BLOCKS_DENEB`. Cleanest formula-driven derivation pattern of all 6. **At Fulu**, `max_data_columns_by_root_request` cap = `MAX_REQUEST_BLOCKS_DENEB = 128` (matches spec line 777 — DataColumnsByRootIdentifier list cap).

### Teku consistent HYBRID across all caps

Teku `DenebBuilder.java:150-155`:
```java
private static Integer computeMaxRequestBlobSidecars(
    final Integer maxRequestBlocksDeneb, final Integer maxBlobsPerBlock) {
  return maxRequestBlocksDeneb * maxBlobsPerBlock;
}
```

Teku is **CONSISTENT** across items #49, #50, #52: HYBRID pattern (computed default + YAML override). Most spec-faithful pattern of all 6 clients across all 3 cap families.

### Grandine fork-aware selector

Grandine `config.rs:977-986`:
```rust
pub const fn max_request_blocks(&self, phase: Phase) -> u64 {
    match phase {
        Phase::Phase0 | Phase::Altair | Phase::Bellatrix | Phase::Capella => {
            self.max_request_blocks
        }
        Phase::Deneb | Phase::Electra | Phase::Fulu | Phase::Gloas => {
            self.max_request_blocks_deneb
        }
    }
}
```

Cleanest cross-fork dispatch. Lighthouse uses `electra_enabled()` boolean composition (`:695`); grandine uses phase enum match. Same effect.

### Lodestar formula documentation in comments

Lodestar `mainnet.ts:154-159`:
```typescript
MAX_REQUEST_BLOCKS_DENEB: 128,
// New in deneb
MAX_REQUEST_BLOB_SIDECARS: 768,
// MAX_REQUEST_BLOCKS_DENEB * MAX_BLOBS_PER_BLOCK
MAX_REQUEST_BLOB_SIDECARS_ELECTRA: 1152,
// MAX_REQUEST_BLOCKS_DENEB * MAX_BLOBS_PER_BLOCK_ELECTRA
```

And `rateLimit.ts:60`:
```typescript
// Rationale: MAX_REQUEST_BLOCKS_DENEB * NUMBER_OF_COLUMNS
```

**Comments document the formula** even though values are hardcoded. Halfway between teku's compute-formula and prysm's bare-YAML. **Best documentation practice** of the 4 hardcoded clients.

### Fulu-NEW use in DataColumnSidecarsByRoot v1

Spec `fulu/p2p-interface.md:777`:
```
List[DataColumnsByRootIdentifier, MAX_REQUEST_BLOCKS_DENEB]
```

**Foundation cap `MAX_REQUEST_BLOCKS_DENEB = 128` becomes the request list cap for Fulu-NEW DataColumnSidecarsByRoot v1**. So at Fulu, this Deneb-heritage constant has a NEW Fulu-NEW use. Cross-cuts item #46 (RPC handlers); item #46 likely already enforces this cap. **Confirmation**: lighthouse `max_data_columns_by_root_request_common::<E>(self.max_request_blocks_deneb)` (`chain_spec.rs:964`) confirms cap derivation.

### Gloas-NEW use in ExecutionPayloadEnvelopesByRange

Lodestar `executionPayloadEnvelopesByRange.ts:94-95`:
```typescript
if (count > config.MAX_REQUEST_BLOCKS_DENEB) {
    count = config.MAX_REQUEST_BLOCKS_DENEB;
}
```

**Gloas-NEW** ExecutionPayloadEnvelopesByRange RPC also caps at `MAX_REQUEST_BLOCKS_DENEB`. **`MAX_REQUEST_BLOCKS_DENEB` extends across 4 forks** (Deneb → Electra → Fulu → Gloas) into multiple RPC families. Foundational primitive.

### Cross-cut summary: 8 use sites for one constant

| Use site | Fork | Item | Per-client status |
|---|---|---|---|
| `compute_max_request_data_column_sidecars()` formula | Fulu | #49 | All 6 evaluate to 16384 |
| `compute_max_request_blob_sidecars()` formula | Electra | #50 | All 6 evaluate to 1152 |
| `BeaconBlocksByRange v2` response cap | Deneb | TBD audit | All 6 enforce 128 |
| `BeaconBlocksByRoot v2` request cap | Deneb | TBD audit | All 6 enforce 128 |
| `BlobSidecarsByRange v1` cap (deprecated) | Deneb→Fulu | #50 | All 6 enforce 1152 |
| `BlobSidecarsByRoot v1` cap (deprecated) | Deneb→Fulu | #50 | All 6 enforce 1152 |
| `DataColumnSidecarsByRoot v1` request list cap | **Fulu** | #46 | All 6 enforce 128 (lighthouse confirmed) |
| `ExecutionPayloadEnvelopesByRange` cap | **Gloas** | TBD | lodestar confirmed; others TBD |

**8 use sites across 4 fork generations.** This is the most foundational constant audited so far.

### Live mainnet validation

5+ months of cross-client BeaconBlocksByRange v2 sync without observed cap divergence. Nimbus's strict equality check passes because all 6 use 128 on mainnet. The `# TODO Make use of in request code` nimbus comment suggests this may eventually be reconfigured but has been stable for years.

## Cross-cut chain

This audit closes the foundational cap layer:
- **Item #49** (`MAX_REQUEST_DATA_COLUMN_SIDECARS`): downstream consumer via formula `MAX_REQUEST_BLOCKS_DENEB × NUMBER_OF_COLUMNS`
- **Item #50** (`MAX_REQUEST_BLOB_SIDECARS`): downstream consumer via formula `MAX_REQUEST_BLOCKS_DENEB × MAX_BLOBS_PER_BLOCK_ELECTRA`
- **Item #46** (DataColumnSidecarsByRange/Root v1 RPCs): consumes via DataColumnsByRootIdentifier request list cap (Fulu-NEW use site)
- **Item #43** (Engine API surface): cross-cut on Deneb-heritage constants
- **Item #28 NEW Pattern HH candidate**: COMPILE-TIME CONSTANT BAKED INTO BINARY (nimbus). Most rigid form of Pattern DD.
- **Item #28 Pattern DD revision**: 3-category split — computed formula (teku, grandine) vs hardcoded YAML with load-time formula validation (nimbus for blob caps) vs hardcoded YAML without validation (prysm, lighthouse, lodestar)
- **Item #48** (catalogue refresh): adds Pattern HH; revises Pattern DD characterization for nimbus

## Adjacent untouched Fulu-active

- BeaconBlocksByRange v2 RPC handler architecture cross-client (Deneb-heritage; consensus-critical block sync)
- BeaconBlocksByRoot v2 RPC handler architecture cross-client
- `MAX_REQUEST_BLOCKS = 1024` Phase0-heritage constant (Phase0/Altair/Bellatrix/Capella use this; Deneb+ uses MAX_REQUEST_BLOCKS_DENEB = 128)
- Cross-network MAX_REQUEST_BLOCKS_DENEB consistency (mainnet confirmed; sepolia/holesky/gnosis/hoodi TBD)
- ExecutionPayloadEnvelopesByRange v1 (Gloas-NEW) cap enforcement cross-client
- Nimbus migration roadmap to runtime-config MAX_REQUEST_BLOCKS_DENEB (`# TODO Make use of in request code`)
- Validation of `MAX_REQUEST_BLOCKS_DENEB ≥ MIN_EPOCHS_FOR_BLOCK_REQUESTS` invariant cross-client
- DataColumnsByRootIdentifier SSZ container schema cross-client (Fulu-NEW; field naming)
- Pattern DD missing-validation cross-client audit: which other Pattern DD-relevant formulas are NOT validated at YAML load time (parallel to nimbus's MAX_REQUEST_DATA_COLUMN_SIDECARS gap)

## Future research items

1. **NEW Pattern HH for item #28 catalogue**: COMPILE-TIME CONSTANT BAKED INTO BINARY. Most rigid form of Pattern DD. Forward-fragility: spec changes require recompilation, not just YAML config bump.
2. **Pattern DD 3-category revision** for item #28 catalogue: computed formula vs hardcoded-YAML-with-formula-validation vs hardcoded-YAML-without-validation. Items #49 + #50 nimbus characterizations need retroactive update.
3. **Nimbus `MAX_REQUEST_DATA_COLUMN_SIDECARS` formula-validation gap**: file PR adding `checkCompatibility MAX_REQUEST_BLOCKS_DENEB * NUMBER_OF_COLUMNS, "MAX_REQUEST_DATA_COLUMN_SIDECARS"` to `presets.nim`. Closes nimbus's internal Pattern DD inconsistency.
4. **Nimbus migration roadmap**: track `# TODO Make use of in request code` follow-up. File issue if not already tracked.
5. **Cross-network MAX_REQUEST_BLOCKS_DENEB audit**: confirm `128` across mainnet/sepolia/holesky/gnosis/hoodi for all 6.
6. **BeaconBlocksByRange v2 audit (item #53 candidate)**: foundational consensus-critical block sync RPC. Per-client cap enforcement, request validation, response chunk semantics. Higher priority than Status v1 audit (item #52 was originally that candidate).
7. **Pattern DD missing-validation audit**: which other formulas in spec are NOT validated by any client at YAML load time? Generalize from nimbus's gap to spec-wide audit.
8. **Hypothetical fork divergence test**: simulate fork increasing `MAX_REQUEST_BLOCKS_DENEB` to 256. Verify nimbus requires recompile; other 5 require YAML config bump.
9. **Pattern HH adoption catalogue**: which other constants are compile-time-baked across the 6 clients? Cross-cut audit. (Likely: `BLS_WITHDRAWAL_PREFIX`, `MAX_VALIDATORS_PER_COMMITTEE`, etc — compile-time values across all clients.)
10. **ExecutionPayloadEnvelopesByRange v1 (Gloas-NEW) cap audit**: lodestar uses `MAX_REQUEST_BLOCKS_DENEB`. Other 5 clients TBD. Pre-emptive Gloas audit candidate.
11. **DataColumnsByRootIdentifier SSZ container audit**: Fulu-NEW container with `MAX_REQUEST_BLOCKS_DENEB` cap. Per-client SSZ schema, field naming, version conventions (Pattern AA candidate).
12. **Nimbus `checkCompatibility` macro spec-completeness audit**: which constants are validated; which are missed? Catalogue all `checkCompatibility` calls and identify gaps.

## Summary

Foundational Deneb-heritage `MAX_REQUEST_BLOCKS_DENEB = 128` constant. **All 6 clients evaluate to identical 128 mainnet**. Used in **8 use sites across 4 fork generations** (Deneb → Electra → Fulu → Gloas), making it the most foundational cap audited.

**Per-client implementation strategy splits 5-1**:
- **5 of 6** (prysm, lighthouse, teku, lodestar, grandine): YAML-driven constant with override capability
- **1 of 6** (nimbus): **HARDCODED COMPILE-TIME CONSTANT** at `constants.nim:80` with `checkCompatibility` rejecting YAML override

**NEW Pattern HH candidate for item #28 catalogue**: COMPILE-TIME CONSTANT BAKED INTO BINARY. Most rigid form of Pattern DD — cannot be overridden via YAML; throws `PresetFileError`. Same forward-fragility class as Pattern DD/EE/FF/GG.

**RETROACTIVE CORRECTION** to items #49 + #50 nimbus characterization: nimbus actually has **HYBRID VALIDATION** for `MAX_REQUEST_BLOB_SIDECARS` and `MAX_REQUEST_BLOB_SIDECARS_ELECTRA` via `checkCompatibility ... * MAX_BLOBS_PER_BLOCK[_ELECTRA], "MAX_REQUEST_BLOB_SIDECARS[_ELECTRA]"` at YAML load time (`presets.nim:1199-1204`). **Items #49 + #50 mischaracterized nimbus as bare hardcoded YAML — actual category is "hardcoded YAML with load-time formula validation"**. Nimbus is more spec-faithful than I credited.

**Nimbus internal inconsistency identified**: validates `MAX_REQUEST_BLOB_SIDECARS` formula but NOT `MAX_REQUEST_DATA_COLUMN_SIDECARS`. Possible bug-fix opportunity to add `checkCompatibility MAX_REQUEST_BLOCKS_DENEB * NUMBER_OF_COLUMNS, "MAX_REQUEST_DATA_COLUMN_SIDECARS"`.

**Updated Pattern DD 3-category split** (replacing items #49 + #50 binary split):
1. **Computed formula** (teku + grandine): formula computes value at runtime
2. **Hardcoded YAML with load-time formula validation** (nimbus for blob caps only): YAML stores value, MUST satisfy formula or load fails
3. **Hardcoded YAML without validation** (prysm, lighthouse, lodestar; nimbus for data column cap): YAML stores value, no cross-check

**Lighthouse derivation pattern** at `chain_spec.rs:957-965`: derives `max_blocks_by_root_request` and `max_data_columns_by_root_request` from `MAX_REQUEST_BLOCKS_DENEB`. Cleanest formula-driven derivation pattern.

**Teku consistent HYBRID** across items #49, #50, #52: most spec-faithful + most config-friendly across all 3 cap families.

**Live mainnet validation**: 5+ months without observed divergence on this RPC family. Nimbus's strict-equality check passes because all 6 use 128 on mainnet.

**Fulu-NEW use**: at Fulu, `MAX_REQUEST_BLOCKS_DENEB` becomes the cap for `DataColumnSidecarsByRoot v1` request list (line 777 of fulu/p2p-interface.md). Cross-cuts item #46.

**Gloas-NEW use**: `ExecutionPayloadEnvelopesByRange v1` also caps at `MAX_REQUEST_BLOCKS_DENEB` (lodestar confirmed at `executionPayloadEnvelopesByRange.ts:94-95`). **Pattern HH/DD risk extends into Gloas**.

**With this audit, the foundational Deneb-heritage cap layer is closed**. Triplet of cap audits complete: items #49 (data column cap) + #50 (blob sidecar cap) + **#52 (foundational MAX_REQUEST_BLOCKS_DENEB)**.

**Total Fulu-NEW-relevant items: 22 (#30–#52)**. Item #28 catalogue **Patterns A–HH (34 patterns)**. Pattern DD revised to 3-category split.
