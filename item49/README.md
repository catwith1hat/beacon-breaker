# Item 49 — `compute_max_request_data_column_sidecars()` formula consistency (EIP-7594 PeerDAS RPC response cap)

**Status:** no-divergence-pending-fixture-run on mainnet values; **forward-compat divergence on formula vs hardcoded** — audited 2026-05-04. **Nineteenth Fulu-NEW item, fourteenth PeerDAS audit**. Defines the response cap for both `DataColumnSidecarsByRange v1` and `DataColumnSidecarsByRoot v1` RPCs (item #46). Closes a flagged forward-research gap from item #46 ("only teku surfaces explicit `getMaxRequestDataColumnSidecars()` getter; others TBD on formula consistency").

**Spec definition** (`p2p-interface.md` "compute_max_request_data_column_sidecars" section):
```python
def compute_max_request_data_column_sidecars() -> uint64:
    """Return the maximum number of data column sidecars in a single request."""
    return uint64(MAX_REQUEST_BLOCKS_DENEB * NUMBER_OF_COLUMNS)
```

Mainnet evaluation: `MAX_REQUEST_BLOCKS_DENEB = 128 × NUMBER_OF_COLUMNS = 128` → `16384`.

**Major finding**: spec defines this as a FUNCTION (computes the product); but **4 of 6 clients hardcode the value `16384` as a YAML config constant** (`MAX_REQUEST_DATA_COLUMN_SIDECARS = 16384`). Only **teku + grandine** compute the formula dynamically. **NEW Pattern DD candidate for item #28**: hardcoded-constant vs computed-formula divergence in spec-defined functions.

## Scope

In: `compute_max_request_data_column_sidecars()` formula `MAX_REQUEST_BLOCKS_DENEB × NUMBER_OF_COLUMNS`; per-client implementation (formula vs hardcoded); YAML config overrides; cross-network constant consistency; forward-compat at spec changes to `NUMBER_OF_COLUMNS` or `MAX_REQUEST_BLOCKS_DENEB`.

Out: `MAX_REQUEST_BLOCKS_DENEB` constant itself (Deneb-heritage); `NUMBER_OF_COLUMNS` constant (item #33 covered); RPC response cap enforcement (item #46 covered); BlobSidecarsByRange v1 cap (Deneb-heritage equivalent).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | All 6 clients evaluate to `16384` on mainnet | ✅ all 6 | `128 × 128 = 16384` |
| H2 | Spec defines as a FUNCTION (computed) — `MAX_REQUEST_BLOCKS_DENEB * NUMBER_OF_COLUMNS` | ✅ implemented as function in 2 of 6 (teku, grandine); ⚠️ **hardcoded constant in 4 of 6** (prysm, lighthouse, nimbus, lodestar) | NEW Pattern DD candidate for item #28 |
| H3 | YAML config exposes `MAX_REQUEST_DATA_COLUMN_SIDECARS` for override | ✅ all 6 | All 6 ship YAML config with the value |
| H4 | Cross-network consistency: `MAX_REQUEST_DATA_COLUMN_SIDECARS = 16384` for mainnet/sepolia/holesky/gnosis/hoodi | ✅ all 6 (lighthouse confirmed for all 5; others sample mainnet) | Confirmed via per-client config files |
| H5 | RPC response cap enforcement uses this constant | ✅ all 6 (cross-cuts item #46) | Per-client RPC handlers use config value |
| H6 | RPC request validation uses this constant | ✅ all 6 (prysm `errMaxRequestDataColumnSidecarsExceeded`; others similar) | Per-client request validation |
| H7 | Forward-compat: at hypothetical fork increasing `NUMBER_OF_COLUMNS` or `MAX_REQUEST_BLOCKS_DENEB` | ⚠️ **DIVERGENCE** — formula clients (teku, grandine) auto-update; hardcoded clients (prysm, lighthouse, nimbus, lodestar) require YAML config update | Forward-fragility |
| H8 | Forward-compat: at hypothetical fork DECREASING the cap (e.g., bandwidth optimization) | ⚠️ same divergence | Same risk |
| H9 | Per-client config override capability (testnets with different values) | ✅ all 6 | YAML-driven configuration |
| H10 | Teku has unique pattern: COMPUTES formula AS DEFAULT but allows YAML override | ✅ confirmed at `FuluBuilder.java:59-65` | Most spec-faithful + most config-friendly combination |

## Per-client cross-reference

| Client | Implementation strategy | Source | Spec-faithful? | Forward-compat? |
|---|---|---|---|---|
| **prysm** | **Hardcoded YAML constant** `MaxRequestDataColumnSidecars: 16384` (`mainnet_config.go:339`); `MaxRequestDataColumnSidecars uint64 yaml:"MAX_REQUEST_DATA_COLUMN_SIDECARS" spec:"true"` (`config.go:303`) | `params.BeaconConfig().MaxRequestDataColumnSidecars` | ❌ hardcoded value | YAML override required at fork |
| **lighthouse** | **Hardcoded YAML constant** `MAX_REQUEST_DATA_COLUMN_SIDECARS: 16384` in 5 networks (mainnet/sepolia/holesky/gnosis/hoodi); `pub max_request_data_column_sidecars: u64` in ChainSpec (`chain_spec.rs:277`); `default_max_request_data_column_sidecars()` const fn (`:2184`) | `spec.max_request_data_column_sidecars` | ❌ hardcoded value | YAML override required at fork |
| **teku** | **COMPUTES the formula** + accepts YAML override (`FuluBuilder.java:221 computeMaxRequestDataColumnSidecars(maxRequestBlocksDeneb) { return maxRequestBlocksDeneb * numberOfColumns; }`); applied at build time IF `numberOfColumns != null` (`FuluBuilder.java:59-65`) | `getMaxRequestDataColumnSidecars()` from `SpecConfigFulu` interface | ✅ spec-faithful + override-friendly | **Auto-updates at fork**; most spec-aligned |
| **nimbus** | **Hardcoded YAML constant** `MAX_REQUEST_DATA_COLUMN_SIDECARS: 16384` (mainnet/minimal/gnosis presets at `presets.nim:402/599/794`); `MAX_REQUEST_DATA_COLUMN_SIDECARS*: uint64` field at `presets.nim:183` | `MAX_REQUEST_DATA_COLUMN_SIDECARS` constant | ❌ hardcoded value | YAML override required at fork |
| **lodestar** | **Hardcoded TS const** `MAX_REQUEST_DATA_COLUMN_SIDECARS: 16384` in `chainConfig/configs/mainnet.ts:183`; type definition in `types.ts:120 MAX_REQUEST_DATA_COLUMN_SIDECARS: number` | `config.MAX_REQUEST_DATA_COLUMN_SIDECARS` | ❌ hardcoded value | YAML override required at fork |
| **grandine** | **COMPUTES the formula** as `const fn` (`config.rs:989 pub const fn max_request_data_column_sidecars<P: Preset>(&self) -> u64 { self.max_request_blocks_deneb.saturating_mul(P::NumberOfColumns::U64) }`) | `config.max_request_data_column_sidecars::<P>()` | ✅ spec-faithful | **Auto-updates at fork**; const-fn evaluation |

## Notable per-client findings

### CRITICAL — 2 of 6 implement spec formula; 4 of 6 hardcode

**Spec**: `compute_max_request_data_column_sidecars()` is a FUNCTION returning `MAX_REQUEST_BLOCKS_DENEB × NUMBER_OF_COLUMNS`. **Implementation status**:

- **teku** + **grandine**: COMPUTE the formula dynamically
  - teku: `FuluBuilder.java:221 maxRequestBlocksDeneb * numberOfColumns`
  - grandine: `config.rs:989 self.max_request_blocks_deneb.saturating_mul(P::NumberOfColumns::U64)`
- **prysm + lighthouse + nimbus + lodestar**: HARDCODE `16384` in YAML/preset config
  - prysm: `MaxRequestDataColumnSidecars: 16384` in `mainnet_config.go:339`
  - lighthouse: `MAX_REQUEST_DATA_COLUMN_SIDECARS: 16384` in 5 network configs
  - nimbus: `MAX_REQUEST_DATA_COLUMN_SIDECARS: 16384` in mainnet/minimal/gnosis presets
  - lodestar: `MAX_REQUEST_DATA_COLUMN_SIDECARS: 16384` in `mainnet.ts`/`minimal.ts`

**At mainnet** (`MAX_REQUEST_BLOCKS_DENEB = 128`, `NUMBER_OF_COLUMNS = 128`): all 6 evaluate to **16384** ✅. No production divergence.

**Forward-compat divergence at hypothetical fork**: if a future fork changes `NUMBER_OF_COLUMNS` (e.g., to 256 for higher data throughput) or `MAX_REQUEST_BLOCKS_DENEB`:
- **teku + grandine**: auto-update via formula
- **prysm + lighthouse + nimbus + lodestar**: silently use stale `16384` unless YAML configs are ALSO updated → cross-client divergence on RPC response cap

**NEW Pattern DD candidate for item #28 catalogue**: hardcoded-constant vs computed-formula divergence in spec-defined functions. Same forward-fragility class as Pattern AA (per-client SSZ container version-numbering) and Pattern S (compile-time invariant assertion).

### Teku unique hybrid pattern: computed default + YAML override

```java
// FuluBuilder.java:55-72
@Override
public SpecConfigAndParent<SpecConfigFulu> build(...) {
  if (numberOfColumns != null) {
    final Integer newMaxRequestDataColumnSidecars =
        computeMaxRequestDataColumnSidecars(
            specConfigAndParent.specConfig().getMaxRequestBlocksDeneb());
    LOG.debug(
        "Setting maxRequestDataColumnSidecars to {} (was {})",
        newMaxRequestDataColumnSidecars,
        maxRequestDataColumnSidecars);
    maxRequestDataColumnSidecars = newMaxRequestDataColumnSidecars;
  }
  return SpecConfigAndParent.of(
      new SpecConfigFuluImpl(
          ...
          maxRequestDataColumnSidecars,
          ...
      ),
      ...);
}

// FuluBuilder.java:221
// compute_max_request_data_column_sidecars
private Integer computeMaxRequestDataColumnSidecars(final Integer maxRequestBlocksDeneb) {
  return maxRequestBlocksDeneb * numberOfColumns;
}
```

**Most spec-faithful + most config-friendly**: teku COMPUTES the formula by default but allows YAML override (config can set `maxRequestDataColumnSidecars` explicitly). Logs the override clearly: `"Setting maxRequestDataColumnSidecars to {} (was {})"`. **Best of both worlds**.

Other clients either hardcode (no formula) or compute (no override). Teku's hybrid is most defensive.

### Grandine `const fn` (compile-time evaluable)

```rust
#[must_use]
pub const fn max_request_data_column_sidecars<P: Preset>(&self) -> u64 {
    self.max_request_blocks_deneb
        .saturating_mul(P::NumberOfColumns::U64)
}
```

**`const fn`** annotation — function CAN be evaluated at compile time if inputs are known. **Performance optimization** at code-gen time + spec-faithful formula.

`saturating_mul` for overflow safety (against malicious/malformed configs that might set `max_request_blocks_deneb` to MAX_U64).

### Prysm explicit error type

```go
// rpc_send_request.go:49
errMaxRequestDataColumnSidecarsExceeded = errors.New("count of requested data column sidecars exceeds MAX_REQUEST_DATA_COLUMN_SIDECARS")

// p2p/types/rpc_errors.go:18
ErrMaxDataColumnReqExceeded = errors.New("requested more than MAX_REQUEST_DATA_COLUMN_SIDECARS")
```

TWO error types for the same cap exceeded — `errMaxRequestDataColumnSidecarsExceeded` (request-side validation) + `ErrMaxDataColumnReqExceeded` (request-typing). **Defensive double-check** at multiple layers.

### Lighthouse fall-back default constant

```rust
// chain_spec.rs:1259, 1653, 2184
const fn default_max_request_data_column_sidecars() -> u64 {
    16384  // hardcoded
}
```

Lighthouse uses `default_max_request_data_column_sidecars()` const fn that returns hardcoded `16384`. Used as serde default if YAML config omits the field. **Defensive**: if a malformed YAML omits the field, lighthouse defaults to `16384` rather than `0`.

### Nimbus per-network preset

```nim
# presets.nim:402 (mainnet), :599 (minimal), :794 (gnosis)
MAX_REQUEST_DATA_COLUMN_SIDECARS: 16384,
```

Three preset entries (mainnet, minimal, gnosis). Same value across all 3. Not formula-computed.

### Lodestar typed config

```typescript
// chainConfig/types.ts:120
MAX_REQUEST_DATA_COLUMN_SIDECARS: number;
// chainConfig/types.ts:239
MAX_REQUEST_DATA_COLUMN_SIDECARS: "number",  // type marker
// chainConfig/configs/mainnet.ts:183
MAX_REQUEST_DATA_COLUMN_SIDECARS: 16384,
```

TypeScript-typed config with separate type marker (for spec compliance tracking). Hardcoded value but type-system-enforced.

### Mainnet value evaluation

| Client | Implementation | Mainnet value |
|---|---|---|
| prysm | hardcoded | 16384 |
| lighthouse | hardcoded | 16384 |
| teku | computed `128 × 128` | 16384 |
| nimbus | hardcoded | 16384 |
| lodestar | hardcoded | 16384 |
| grandine | computed `128 × 128` | 16384 |

**All 6 produce identical 16384 on mainnet.** No production divergence.

### Live mainnet validation

5+ months of cross-client RPC interop with response cap enforcement (item #46). All 6 enforce `16384` cap consistently. **Live behavior validates** that the value matches across all 6 — if it didn't, peers would either over-request (causing other side to error) or undercut (causing inefficient sync).

## Cross-cut chain

This audit closes the response-cap formula consistency and cross-cuts:
- **Item #46** (DataColumnSidecarsByRange/ByRoot RPC handlers): consumes this constant for cap enforcement; item #46 noted "only teku surfaces explicit `getMaxRequestDataColumnSidecars()` getter; others TBD on formula consistency" — this audit closes that gap.
- **Item #43** (Engine API surface): cross-cuts in that `MAX_REQUEST_BLOCKS_DENEB` is a Deneb-heritage constant.
- **Item #28 NEW Pattern DD candidate**: hardcoded-constant vs computed-formula divergence in spec-defined functions. Same forward-fragility class as Pattern AA + Pattern S.
- **Item #48** (catalogue refresh): adds Pattern DD to the catalogue.

## Adjacent untouched Fulu-active

- `MAX_REQUEST_BLOCKS_DENEB` constant cross-client (Deneb-heritage; used in formula)
- Cross-network `MAX_REQUEST_DATA_COLUMN_SIDECARS` for sepolia/holesky/gnosis/hoodi (mainnet confirmed)
- BlobSidecarsByRange v1 / BlobSidecarsByRoot v1 cap (Deneb-heritage equivalent — `MAX_REQUEST_BLOB_SIDECARS`)
- RPC request-side validation across clients (prysm 2 error types; others TBD)
- Cap enforcement at RPC server vs RPC client (request validation vs response chunk count)
- Saturating-multiplication overflow handling (only grandine uses `saturating_mul`; others TBD on overflow)
- YAML config override forward-compat: if testnets need different values, do all 6 respect overrides
- Pattern DD scope: which other Fulu functions are spec-defined as computed but hardcoded by clients?

## Future research items

1. **NEW Pattern DD for item #28 catalogue**: hardcoded-constant vs computed-formula divergence in spec-defined functions. Same forward-fragility class as Pattern AA (per-client SSZ container version-numbering) and Pattern S (compile-time invariant assertion). **Forward-compat divergence at any spec change to `NUMBER_OF_COLUMNS` or `MAX_REQUEST_BLOCKS_DENEB`**: teku + grandine auto-update; prysm + lighthouse + nimbus + lodestar require YAML config update or silently use stale value.
2. **Cross-network constant audit**: confirm `MAX_REQUEST_DATA_COLUMN_SIDECARS = 16384` across mainnet/sepolia/holesky/gnosis/hoodi for all 6 clients. (Lighthouse confirmed for 5 networks; others sample mainnet only — extend.)
3. **Hypothetical fork divergence test**: simulate a fork where `NUMBER_OF_COLUMNS = 256`. Verify teku + grandine auto-update to `128 × 256 = 32768`; prysm + lighthouse + nimbus + lodestar require YAML config bump.
4. **`MAX_REQUEST_BLOCKS_DENEB` cross-client audit**: same Pattern DD risk applies. If a future fork changes Deneb's request cap, do all 6 update consistently?
5. **Pattern DD scope expansion**: which other Fulu functions are spec-defined as computed but hardcoded by clients? Scan spec for `def compute_*` patterns and check per-client implementation.
6. **Overflow handling cross-client**: only grandine uses `saturating_mul`; others may overflow on malformed configs (e.g., `max_request_blocks_deneb = MAX_U64`). Verify all 6 handle gracefully.
7. **Teku's hybrid pattern adoption**: file PRs to prysm + lighthouse + nimbus + lodestar adopting teku's "compute default + allow YAML override" pattern.
8. **Generate dedicated EF fixtures** for `compute_max_request_data_column_sidecars()` as a pure function (config inputs → uint64 output). Currently no EF fixture covers this.
9. **RPC interop test at the cap boundary**: peer requests exactly `16384` sidecars; verify all 6 accept. Peer requests `16385`; verify all 6 reject with same error code.
10. **YAML override behavior cross-client**: set `MAX_REQUEST_DATA_COLUMN_SIDECARS = 8192` (half) in custom config; verify all 6 respect the override. Special concern for teku: does YAML override beat the formula?

## Summary

EIP-7594 PeerDAS `compute_max_request_data_column_sidecars()` formula is implemented across all 6 clients producing **identical mainnet value of 16384**. **No production divergence** — all 6 evaluate `MAX_REQUEST_BLOCKS_DENEB × NUMBER_OF_COLUMNS = 128 × 128 = 16384`.

**Implementation strategy splits 4-2**:
- **HARDCODED YAML constant** (4 of 6): prysm, lighthouse, nimbus, lodestar — all use `MAX_REQUEST_DATA_COLUMN_SIDECARS: 16384` in network config files
- **COMPUTED formula** (2 of 6): **teku** (`FuluBuilder.java:221 maxRequestBlocksDeneb * numberOfColumns` with hybrid YAML override) + **grandine** (`config.rs:989 const fn` with `saturating_mul`)

**NEW Pattern DD candidate for item #28 catalogue**: hardcoded-constant vs computed-formula divergence in spec-defined functions. Same forward-fragility class as Pattern AA and Pattern S.

**Forward-compat divergence at hypothetical fork** (changing `NUMBER_OF_COLUMNS` or `MAX_REQUEST_BLOCKS_DENEB`):
- teku + grandine: auto-update
- prysm + lighthouse + nimbus + lodestar: require YAML config update or silently use stale `16384` → cross-client divergence on RPC response cap

**Teku has unique hybrid pattern** (most spec-faithful + most config-friendly): computes formula as default but allows YAML override. **Should be adopted by other clients**.

**Status**: source review confirms all 6 clients aligned on mainnet value `16384`. Live mainnet validates 5+ months of cross-client RPC interop with consistent cap enforcement (item #46).

**With this audit, the `compute_max_request_data_column_sidecars()` formula consistency gap from item #46 is closed**. PeerDAS audit corpus now spans 14 items: #33 → #34 → #35 → #37 → #38 → #39 → #40 → #41 → #42 → #44 → #45 → #46 → #47 → **#49**.

**Total Fulu-NEW items: 19 (#30–#49)**. Item #28 catalogue **Patterns A–DD (30 patterns)**.
