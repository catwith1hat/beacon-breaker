---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [28, 43, 46, 49, 50]
eips: [EIP-7594, EIP-7691, EIP-7732]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 52: `MAX_REQUEST_BLOCKS_DENEB` foundational cap — Deneb-heritage constant feeding 8 RPC use-sites across Deneb → Electra → Fulu → Gloas

## Summary

Deneb-introduced constant `MAX_REQUEST_BLOCKS_DENEB = 2^7 = 128` (`vendor/consensus-specs/specs/deneb/p2p-interface.md:63`). Spec lists it as the cap for `BeaconBlocksByRange v2` + `BeaconBlocksByRoot v2` + `BlobSidecarsByRange v1` + `BlobSidecarsByRoot v1` (deprecated at Fulu per item #50) AND as the multiplicand in `compute_max_request_blob_sidecars()` (item #50) and `compute_max_request_data_column_sidecars()` (item #49). Fulu adds a new use site (`DataColumnSidecarsByRoot v1` request list cap, `vendor/consensus-specs/specs/fulu/p2p-interface.md:494`) and Gloas adds another (`ExecutionPayloadEnvelopesByRange v1` response list cap, `vendor/consensus-specs/specs/gloas/p2p-interface.md:545`). Eight downstream use sites across four fork generations.

**Fulu surface (carried forward from 2026-05-04 audit; cap value):** all 6 clients evaluate `MAX_REQUEST_BLOCKS_DENEB = 128` on mainnet. **No production divergence.**

**Pattern DD 3-category revision** (carried forward, recharacterising nimbus from items #49 + #50):

1. **Computed formula** (teku + grandine) — derives cap from constituent constants at build time.
2. **Hardcoded YAML/preset with load-time formula validation** (nimbus for blob caps only) — YAML stores value but `checkCompatibility` template rejects load if value does not equal the formula's expected product.
3. **Hardcoded YAML/preset without validation** (prysm + lighthouse + lodestar; also nimbus for `MAX_REQUEST_DATA_COLUMN_SIDECARS`) — YAML stores value, no cross-check.

**Pattern HH (item #28 catalogue candidate)**: compile-time constant baked into binary. Most rigid form of Pattern DD — cannot be YAML-overridden. **Only nimbus** exhibits this for `MAX_REQUEST_BLOCKS_DENEB`. From `vendor/nimbus/beacon_chain/spec/datatypes/constants.nim:80`:

```nim
MAX_REQUEST_BLOCKS_DENEB*: uint64 = 128 # TODO Make use of in request code
```

`vendor/nimbus/beacon_chain/spec/presets.nim:1072 checkCompatibility MAX_REQUEST_BLOCKS_DENEB` **throws `PresetFileError`** if YAML attempts to override. Five `# TODO MAX_REQUEST_BLOCKS_DENEB: 128,` commented-out entries (`presets.nim:167, 377, 574, 769`, plus an instance at `:1072` itself) trace the deliberate omission from the YAML-overridable surface. Forward-fragility: any spec change to this constant requires recompilation, not a YAML config bump.

**Retroactive correction to items #49 + #50 (carried forward from prior audit):** nimbus also performs load-time formula validation for the BLOB sidecar caps (`presets.nim:1199-1204`):

```nim
checkCompatibility MAX_REQUEST_BLOCKS_DENEB * cfg.MAX_BLOBS_PER_BLOCK,
                   "MAX_REQUEST_BLOB_SIDECARS"
checkCompatibility cfg.MAX_BLOBS_PER_BLOCK,
                   "MAX_BLOBS_PER_BLOCK_ELECTRA", `>=`
checkCompatibility MAX_REQUEST_BLOCKS_DENEB * cfg.MAX_BLOBS_PER_BLOCK_ELECTRA,
                   "MAX_REQUEST_BLOB_SIDECARS_ELECTRA"
```

So at YAML load time nimbus enforces `MAX_REQUEST_BLOB_SIDECARS == 128 × MAX_BLOBS_PER_BLOCK` (= 768) AND `MAX_REQUEST_BLOB_SIDECARS_ELECTRA == 128 × MAX_BLOBS_PER_BLOCK_ELECTRA` (= 1152 mainnet). Items #49 + #50 originally characterised nimbus as plain hardcoded YAML; the correct category is "hardcoded YAML with load-time formula validation" for the blob caps — more spec-faithful than first credited.

**Nimbus internal inconsistency persists (this recheck)**: `presets.nim:1199-1204` validates `MAX_REQUEST_BLOB_SIDECARS` and `MAX_REQUEST_BLOB_SIDECARS_ELECTRA` formulas, but **does NOT validate** `MAX_REQUEST_DATA_COLUMN_SIDECARS == MAX_REQUEST_BLOCKS_DENEB × NUMBER_OF_COLUMNS` (= 16384 mainnet). The grep across `presets.nim` returns no `checkCompatibility … * NUMBER_OF_COLUMNS …` site. Bug-fix opportunity: add `checkCompatibility MAX_REQUEST_BLOCKS_DENEB * NUMBER_OF_COLUMNS, "MAX_REQUEST_DATA_COLUMN_SIDECARS"`.

**Glamsterdam target (Gloas):** spec does NOT modify `MAX_REQUEST_BLOCKS_DENEB`. The Deneb-heritage constant carries forward unchanged into Gloas. A new use site is added at Gloas — `ExecutionPayloadEnvelopesByRange v1` response cap (`vendor/consensus-specs/specs/gloas/p2p-interface.md:545 List[SignedExecutionPayloadEnvelope, MAX_REQUEST_BLOCKS_DENEB]`) — but the value is unchanged. The Pattern HH (nimbus compile-time-baked) and Pattern DD (cross-client formula-vs-hardcoded) risk classes both carry forward into Gloas.

**Impact: none** — all 6 evaluate to `128` on mainnet; Gloas inherits the Deneb constant verbatim. Thirty-third `impact: none` result in the recheck series.

## Question

Pyspec defines `MAX_REQUEST_BLOCKS_DENEB = 128` at Deneb (`vendor/consensus-specs/specs/deneb/p2p-interface.md:63`). Multiple downstream use sites at Deneb, Electra, Fulu, and Gloas all multiply against this constant. Gloas adds a new use site (`ExecutionPayloadEnvelopesByRange v1`) without modifying the constant.

Three recheck questions:

1. **Per-client implementation strategy** — does the 5-vs-1 split (5 YAML-overridable; nimbus compile-time-baked) persist? Has nimbus migrated to runtime config since the 2026-05-04 audit?
2. **Pattern DD 3-category status** — does nimbus still validate the blob sidecar formulas at YAML load time but omit the data-column-sidecar formula validation?
3. **Glamsterdam target** — does Gloas add new use sites? Are all 6 clients aligned on the Gloas-NEW `ExecutionPayloadEnvelopesByRange v1` cap = `MAX_REQUEST_BLOCKS_DENEB`?

## Hypotheses

- **H1.** All 6 clients evaluate `MAX_REQUEST_BLOCKS_DENEB = 128` on mainnet.
- **H2.** Spec defines as a constant (not a formula); Deneb-introduced (`p2p-interface.md:63`).
- **H3.** 5 of 6 expose YAML override (`MAX_REQUEST_BLOCKS_DENEB` config key); nimbus REJECTS via `checkCompatibility` (Pattern HH).
- **H4.** Cross-network: same `128` for mainnet/sepolia/holesky/gnosis/hoodi.
- **H5.** All 6 enforce cap on `BeaconBlocksByRange v2` (Deneb-heritage; consensus-critical block sync).
- **H6.** Cross-fork: pre-Deneb uses `MAX_REQUEST_BLOCKS = 1024`; Deneb+ uses `MAX_REQUEST_BLOCKS_DENEB = 128`. Per-client selector dispatches on fork.
- **H7.** Fulu-NEW use: `DataColumnSidecarsByRoot v1` request list cap = `MAX_REQUEST_BLOCKS_DENEB` (`vendor/consensus-specs/specs/fulu/p2p-interface.md:494`).
- **H8.** Nimbus load-time formula validation for `MAX_REQUEST_BLOB_SIDECARS[_ELECTRA]` at `presets.nim:1199-1204`.
- **H9.** Nimbus internal inconsistency: no validation for `MAX_REQUEST_DATA_COLUMN_SIDECARS = MAX_REQUEST_BLOCKS_DENEB × NUMBER_OF_COLUMNS`.
- **H10.** Forward-compat at hypothetical fork changing the cap: nimbus requires recompile (Pattern HH); other 5 require YAML/preset bump (Pattern DD).
- **H11.** *(Glamsterdam target — `ExecutionPayloadEnvelopesByRange v1` NEW use site)* `vendor/consensus-specs/specs/gloas/p2p-interface.md:545` lists `List[SignedExecutionPayloadEnvelope, MAX_REQUEST_BLOCKS_DENEB]` as the response cap.
- **H12.** *(Glamsterdam target — constant unchanged)* `MAX_REQUEST_BLOCKS_DENEB` is not modified at Gloas; the Deneb value carries forward.

## Findings

H1 ✓ (all 6 = 128). H2 ✓. H3 ✓ (5 YAML-overridable; nimbus compile-time-baked). H4 ✓ (mainnet confirmed; cross-network TBD). H5 ✓. H6 ✓. H7 ✓ (spec line 494). H8 ✓ (`presets.nim:1199-1204`). H9 ✓ (no `NUMBER_OF_COLUMNS` `checkCompatibility` site). H10 ✓. H11 ✓ (Gloas spec line 545). H12 ✓ (Deneb value carries forward; constant unchanged).

### prysm

Struct field (`vendor/prysm/config/params/config.go:275`):

```go
MaxRequestBlocksDeneb            uint64           `yaml:"MAX_REQUEST_BLOCKS_DENEB" spec:"true"`              // MaxRequestBlocksDeneb is the maximum number of blocks in a single request after the deneb epoch.
```

Mainnet value (`vendor/prysm/config/params/mainnet_config.go:311`):

```go
MaxRequestBlocksDeneb:            128,
```

YAML-overridable via `MAX_REQUEST_BLOCKS_DENEB` key. Accessor `params.BeaconConfig().MaxRequestBlocksDeneb` is read at RPC enforcement sites for BeaconBlocksByRange v2 cap.

**Pattern DD category**: hardcoded YAML without validation. **Pattern HH**: not applicable.

### lighthouse

ChainSpec field (`vendor/lighthouse/consensus/types/src/core/chain_spec.rs:275`):

```rust
max_request_blocks_deneb: u64,
```

Default helpers (`:1257, 1651`) use `default_max_request_blocks_deneb()` returning `128`. Fork-aware selector at `:695`:

```rust
self.max_request_blocks_deneb as usize
```

Returns the deneb cap when caller passes a Deneb-or-later fork name. Downstream derivations at `:960, 964`:

```rust
max_blocks_by_root_request_common(self.max_request_blocks_deneb);
max_data_columns_by_root_request_common::<E>(self.max_request_blocks_deneb);
```

Used at `:1121` (codec) and other sites. Cleanest formula-driven derivation pattern of the 6 — multiple downstream caps explicitly derive from `max_request_blocks_deneb`. At Fulu, `max_data_columns_by_root_request` cap derives from this constant; matches `vendor/consensus-specs/specs/fulu/p2p-interface.md:494`.

**Pattern DD category**: hardcoded YAML without validation. **Pattern HH**: not applicable. But the derivation pattern at `:960, 964` is functionally similar to teku's HYBRID — derived caps update automatically if `max_request_blocks_deneb` changes.

### teku

DenebBuilder field (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/config/builder/DenebBuilder.java:38`):

```java
private Integer maxRequestBlocksDeneb;
```

Setter at `:93-94`:

```java
public DenebBuilder maxRequestBlocksDeneb(final Integer maxRequestBlocksDeneb) {
  this.maxRequestBlocksDeneb = maxRequestBlocksDeneb;
```

Formula consumer at `:150-155`:

```java
return computeMaxRequestBlobSidecars(maxRequestBlocksDeneb, maxBlobsPerBlock);
...
private static Integer computeMaxRequestBlobSidecars(
    final Integer maxRequestBlocksDeneb, final Integer maxBlobsPerBlock) {
  return maxRequestBlocksDeneb * maxBlobsPerBlock;
}
```

**Pattern DD category**: HYBRID (formula default + YAML override). teku is consistent across items #49, #50, #52 — same hybrid pattern for all three cap families. **Pattern HH**: not applicable.

### nimbus

**Compile-time constant** (`vendor/nimbus/beacon_chain/spec/datatypes/constants.nim:80`):

```nim
MAX_REQUEST_BLOCKS_DENEB*: uint64 = 128 # TODO Make use of in request code
```

YAML rejection (`vendor/nimbus/beacon_chain/spec/presets.nim:1072`):

```nim
checkCompatibility MAX_REQUEST_BLOCKS_DENEB
```

The `checkCompatibility` template (`presets.nim:977-997`) compares the spec-baked binary constant against any YAML-loaded value; mismatch throws `PresetFileError`. **YAML cannot override.**

Commented TODO entries (`presets.nim:167, 377, 574, 769`):

```nim
# TODO MAX_REQUEST_BLOCKS_DENEB*: uint64
...
# TODO MAX_REQUEST_BLOCKS_DENEB: 128,
```

Trace the deliberate omission from the YAML preset structures. The `# TODO Make use of in request code` comment at `constants.nim:80` indicates a planned migration to runtime config, but no migration has occurred since the 2026-05-04 audit.

Load-time formula validations for BLOB caps (`presets.nim:1199-1204`):

```nim
checkCompatibility MAX_REQUEST_BLOCKS_DENEB * cfg.MAX_BLOBS_PER_BLOCK,
                   "MAX_REQUEST_BLOB_SIDECARS"
checkCompatibility cfg.MAX_BLOBS_PER_BLOCK,
                   "MAX_BLOBS_PER_BLOCK_ELECTRA", `>=`
checkCompatibility MAX_REQUEST_BLOCKS_DENEB * cfg.MAX_BLOBS_PER_BLOCK_ELECTRA,
                   "MAX_REQUEST_BLOB_SIDECARS_ELECTRA"
```

So at YAML load time nimbus VALIDATES:

- `MAX_REQUEST_BLOB_SIDECARS == 128 × MAX_BLOBS_PER_BLOCK` (= 768 mainnet)
- `MAX_REQUEST_BLOB_SIDECARS_ELECTRA == 128 × MAX_BLOBS_PER_BLOCK_ELECTRA` (= 1152 mainnet)

**Pattern DD category for blob caps**: hardcoded YAML with load-time formula validation. Items #49 and #50 originally characterised nimbus as plain hardcoded — this retroactive correction (carried forward from the prior audit) recognises nimbus as more spec-faithful than first credited.

**Internal inconsistency (persists in this recheck)**: `presets.nim` contains NO `checkCompatibility MAX_REQUEST_BLOCKS_DENEB * NUMBER_OF_COLUMNS, "MAX_REQUEST_DATA_COLUMN_SIDECARS"` site. `grep -n "NUMBER_OF_COLUMNS\|MAX_REQUEST_DATA_COLUMN_SIDECARS" vendor/nimbus/beacon_chain/spec/presets.nim` returns no formula-validation hit. So for `MAX_REQUEST_DATA_COLUMN_SIDECARS` (item #49) nimbus falls back to hardcoded YAML without validation — same category as prysm + lighthouse + lodestar. Bug-fix opportunity: add the parallel `checkCompatibility` line.

**Pattern HH category**: nimbus is the sole exemplar. `MAX_REQUEST_BLOCKS_DENEB` is the only constant in the prior audit's catalogue confirmed compile-time-baked AND configured to reject YAML override.

### lodestar

TypeScript const (`vendor/lodestar/packages/config/src/chainConfig/configs/mainnet.ts:154-169`):

```typescript
MAX_REQUEST_BLOCKS_DENEB: 128,
// New in deneb
MAX_REQUEST_BLOB_SIDECARS: 768,
// MAX_REQUEST_BLOCKS_DENEB * MAX_BLOBS_PER_BLOCK
MAX_REQUEST_BLOB_SIDECARS_ELECTRA: 1152,
// MAX_REQUEST_BLOCKS_DENEB * MAX_BLOBS_PER_BLOCK_ELECTRA
```

Comments document the downstream formulas, but the values are hardcoded literals. No load-time validation.

**Pattern DD category**: hardcoded YAML without validation. **Pattern HH**: not applicable. The inline comments make lodestar the best-documented of the 4 non-formula clients.

### grandine

Config field (`vendor/grandine/types/src/config.rs:163`):

```rust
pub max_request_blocks_deneb: u64,
```

Default at `:294 max_request_blocks_deneb: 128`. Fork-aware selector at `:977-990`:

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

Consumed downstream at `:983, 990, 1121` (codec). Also feeds the formula at `:1005-1017 max_request_blob_sidecars(phase) = max_request_blocks(phase).saturating_mul(...)` per item #50 finding.

**Pattern DD category**: formula at downstream consumers (`max_request_blob_sidecars`, `max_request_data_column_sidecars`). Plain hardcoded YAML at the source constant. **Pattern HH**: not applicable. Forward-compat: any YAML bump propagates through the formula automatically — same auto-update path as teku's hybrid.

## Cross-reference table

| Client | H1 mainnet value | H3 YAML-overridable | H8 load-time formula validation | H9 nimbus internal inconsistency | H11 Gloas use site (envelope RPC cap) | Pattern HH | Pattern DD category |
|---|---|---|---|---|---|---|---|
| **prysm** | 128 (`mainnet_config.go:311`) | ✅ via `MAX_REQUEST_BLOCKS_DENEB` YAML key | ❌ | n/a | TBD (`executionPayloadEnvelopesByRange` cap) | ❌ | hardcoded YAML without validation |
| **lighthouse** | 128 (`chain_spec.rs:275, 1257, 1651` `default_max_request_blocks_deneb()`) | ✅ | ❌ but cleanest downstream derivation at `:960, 964` | n/a | TBD | ❌ | hardcoded YAML without validation (downstream-derived) |
| **teku** | 128 (`DenebBuilder.java:38, 93-94`) consumed in formula at `:155 maxRequestBlocksDeneb * maxBlobsPerBlock` | ✅ via setter | n/a (HYBRID = formula default) | n/a | implicit via formula | ❌ | HYBRID (computed default + YAML override) |
| **nimbus** | 128 (`constants.nim:80` compile-time `uint64 = 128`); rejected at `presets.nim:1072` | ❌ — `checkCompatibility` throws `PresetFileError` | ✅ for `MAX_REQUEST_BLOB_SIDECARS[_ELECTRA]` at `presets.nim:1199-1204`; ❌ for `MAX_REQUEST_DATA_COLUMN_SIDECARS` (no `checkCompatibility … * NUMBER_OF_COLUMNS` site) | **YES** — validates blob formulas but not column formula | TBD | ✅ **only client** | compile-time + load-time formula validation (hybrid: HH for the constant; DD load-time-validated for blob caps; DD un-validated for data column cap) |
| **lodestar** | 128 (`mainnet.ts:154` with formula comments at `:159, 169`) | ✅ via custom config | ❌ comments only | n/a | ✅ confirmed (`executionPayloadEnvelopesByRange.ts:94-95 if (count > config.MAX_REQUEST_BLOCKS_DENEB) { count = config.MAX_REQUEST_BLOCKS_DENEB; }`) | ❌ | hardcoded TypeScript const + comments |
| **grandine** | 128 (`config.rs:163, 294 max_request_blocks_deneb: 128`); fork-aware selector at `:977-990 max_request_blocks(phase)` | ✅ | ❌ at the source constant; downstream `max_request_blob_sidecars(phase)` formula at `:1005-1017` auto-propagates | n/a | TBD | ❌ | hardcoded YAML at source; formula at consumers |

**Pattern HH count**: 1/6 (nimbus only). **Pattern DD 3-category counts**: 2 formula (teku + grandine); 1 load-time-formula-validated (nimbus, for blob caps only); 3 hardcoded-without-validation (prysm + lighthouse + lodestar; nimbus for data column cap).

## Empirical tests

- ✅ **Live mainnet operation since 2025-12-03 (5+ months)**: all 6 evaluate `128` on mainnet; no observable BeaconBlocksByRange v2 cap divergence. Nimbus's strict-equality check passes. **Verifies H1, H4, H5, H6 at production scale.**
- ✅ **Per-client implementation verification (this recheck)**: 5-vs-1 split (5 YAML-overridable; nimbus compile-time-baked) unchanged from 2026-05-04 audit. Confirmed via file:line citations.
- ✅ **Nimbus formula validation verification**: `vendor/nimbus/beacon_chain/spec/presets.nim:1199-1204` retains the `checkCompatibility MAX_REQUEST_BLOCKS_DENEB * cfg.MAX_BLOBS_PER_BLOCK[, "_ELECTRA"], "MAX_REQUEST_BLOB_SIDECARS[_ELECTRA]"` pair. Nimbus internal inconsistency persists: no `* NUMBER_OF_COLUMNS, "MAX_REQUEST_DATA_COLUMN_SIDECARS"` site.
- ✅ **Gloas-NEW use site verification**: `vendor/consensus-specs/specs/gloas/p2p-interface.md:545 List[SignedExecutionPayloadEnvelope, MAX_REQUEST_BLOCKS_DENEB]` confirmed. lodestar already enforces the cap at `vendor/lodestar/packages/beacon-node/src/network/reqresp/handlers/executionPayloadEnvelopesByRange.ts:94-95`. Other 4 implementers (prysm, teku, nimbus) for `ExecutionPayloadEnvelopesByRange` TBD on cap enforcement (item #46 cross-cut — lighthouse + grandine don't implement the RPC yet).
- ⏭ **Pattern HH adoption catalogue audit**: which other constants are compile-time-baked across the 6 clients? Likely candidates: `BLS_WITHDRAWAL_PREFIX`, `MAX_VALIDATORS_PER_COMMITTEE` — both compile-time in all 6.
- ⏭ **Nimbus migration roadmap**: track the `# TODO Make use of in request code` comment at `constants.nim:80` — file issue if not already tracked. When nimbus migrates to runtime-config, Pattern HH dissolves.
- ⏭ **Nimbus `MAX_REQUEST_DATA_COLUMN_SIDECARS` validation gap fix**: file PR adding `checkCompatibility MAX_REQUEST_BLOCKS_DENEB * NUMBER_OF_COLUMNS, "MAX_REQUEST_DATA_COLUMN_SIDECARS"` to `presets.nim`. Closes the internal inconsistency.
- ⏭ **Hypothetical fork divergence test**: simulate fork increasing `MAX_REQUEST_BLOCKS_DENEB` to 256. Verify nimbus requires source-code modification + recompile; verify prysm + lighthouse + lodestar require YAML/preset bump; verify teku + grandine auto-update downstream caps. Pattern HH and Pattern DD impact comparison.
- ⏭ **Pattern DD missing-validation audit**: which other formulas in spec are NOT validated at YAML load time by any client? Generalise from nimbus's data-column-sidecar gap to a spec-wide audit. Candidates: `compute_subnets_for_data_column`, `MAX_PAYLOAD_SIZE`, downstream-product caps generally.
- ⏭ **Cross-network value audit**: `MAX_REQUEST_BLOCKS_DENEB = 128` for sepolia/holesky/gnosis/hoodi cross-client. Mainnet confirmed; extend to other 4 networks.
- ⏭ **`ExecutionPayloadEnvelopesByRange v1` cap enforcement** cross-client. lodestar uses `MAX_REQUEST_BLOCKS_DENEB` directly. prysm + teku + nimbus need verification. lighthouse + grandine don't implement the RPC yet (per item #46 cohort finding).

## Conclusion

`MAX_REQUEST_BLOCKS_DENEB = 128` is the most foundational cap in the audited corpus — feeding 8 downstream RPC use sites across Deneb (BeaconBlocksByRange/ByRoot v2, BlobSidecarsByRange/ByRoot v1, `compute_max_request_blob_sidecars`) + Electra (`compute_max_request_blob_sidecars` with Electra blob multiplier) + Fulu (`compute_max_request_data_column_sidecars`, `DataColumnSidecarsByRoot v1` request list cap) + Gloas (`ExecutionPayloadEnvelopesByRange v1` response list cap). All 6 clients evaluate to the same `128` on mainnet; 5+ months of live cross-client BeaconBlocksByRange v2 sync without observed cap divergence.

**Pattern DD 3-category revision (carried forward from items #49 + #50):**

1. **Computed formula**: teku (`DenebBuilder.java:150-155 maxRequestBlocksDeneb * maxBlobsPerBlock` with `LOG.debug` substitution) + grandine (`config.rs:977-1017 max_request_blocks(phase)` + `max_request_blob_sidecars(phase).saturating_mul(...)`).
2. **Hardcoded YAML/preset with load-time formula validation**: nimbus for `MAX_REQUEST_BLOB_SIDECARS` and `MAX_REQUEST_BLOB_SIDECARS_ELECTRA` (via `checkCompatibility` at `presets.nim:1199-1204`). Items #49 + #50 originally mischaracterised nimbus as plain hardcoded — retroactive correction recognises nimbus as more spec-faithful than first credited.
3. **Hardcoded YAML/preset without validation**: prysm + lighthouse + lodestar; also nimbus for `MAX_REQUEST_DATA_COLUMN_SIDECARS` (no `checkCompatibility … * NUMBER_OF_COLUMNS` site — bug-fix opportunity).

**Pattern HH (compile-time constant baked into binary)**: nimbus's `MAX_REQUEST_BLOCKS_DENEB*: uint64 = 128` at `constants.nim:80` + `checkCompatibility` rejection at `presets.nim:1072` make nimbus the sole exemplar. Forward-fragility: any spec change to this constant requires source-code modification + recompile + redistribution. The `# TODO Make use of in request code` comment at `constants.nim:80` indicates planned migration; no migration has occurred since the 2026-05-04 audit.

**Glamsterdam target**: `MAX_REQUEST_BLOCKS_DENEB` is unchanged at Gloas. A new use site is added — `ExecutionPayloadEnvelopesByRange v1` response list cap (`vendor/consensus-specs/specs/gloas/p2p-interface.md:545`) — but the value is the same `128`. lodestar already enforces the cap at `executionPayloadEnvelopesByRange.ts:94-95`; other 4 implementers (prysm, teku, nimbus per item #46) need verification.

**Impact: none** — all 6 evaluate to `128` on mainnet; Gloas inherits the Deneb constant verbatim. Thirty-third `impact: none` result in the recheck series.

Forward-research priorities:

1. **Nimbus `MAX_REQUEST_DATA_COLUMN_SIDECARS` validation gap fix** — file PR adding `checkCompatibility MAX_REQUEST_BLOCKS_DENEB * NUMBER_OF_COLUMNS, "MAX_REQUEST_DATA_COLUMN_SIDECARS"` to `presets.nim`. Closes nimbus's internal Pattern DD inconsistency.
2. **Nimbus migration roadmap** — track the `# TODO Make use of in request code` comment; file issue if not already tracked. When nimbus migrates to runtime config, Pattern HH dissolves for `MAX_REQUEST_BLOCKS_DENEB`.
3. **`ExecutionPayloadEnvelopesByRange v1` cap enforcement audit** — verify prysm + teku + nimbus apply `MAX_REQUEST_BLOCKS_DENEB` cap (lodestar already does). lighthouse + grandine don't implement the RPC yet per item #46.
4. **Pattern HH catalogue audit** — which other constants are compile-time-baked across the 6 clients? Cross-cut audit.
5. **Pattern DD missing-validation audit** — generalise from nimbus's data-column-sidecar gap to a spec-wide check: which downstream products are not validated at YAML load time by any client?
6. **Cross-network `MAX_REQUEST_BLOCKS_DENEB` audit** — extend the mainnet finding to sepolia/holesky/gnosis/hoodi across all 6 clients.
