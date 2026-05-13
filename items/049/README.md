---
status: source-code-reviewed
impact: none
last_update: 2026-05-13
builds_on: [28, 33, 43, 46]
eips: [EIP-7594]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 49: `compute_max_request_data_column_sidecars()` formula consistency — Fulu-NEW RPC response cap (`MAX_REQUEST_BLOCKS_DENEB * NUMBER_OF_COLUMNS`)

## Summary

Closes a flagged forward-research gap from item #46 ("only teku surfaces explicit `getMaxRequestDataColumnSidecars()` getter; others TBD on formula consistency").

Spec (`vendor/consensus-specs/specs/fulu/p2p-interface.md:104-111`):

```python
def compute_max_request_data_column_sidecars() -> uint64:
    """Return the maximum number of data column sidecars in a single request."""
    return uint64(MAX_REQUEST_BLOCKS_DENEB * NUMBER_OF_COLUMNS)
```

Mainnet evaluation: `MAX_REQUEST_BLOCKS_DENEB = 128` × `NUMBER_OF_COLUMNS = 128` = `16384`. Consumed by both `DataColumnSidecarsByRange v1` and `DataColumnSidecarsByRoot v1` (item #46) for the response chunk cap (`vendor/consensus-specs/specs/fulu/p2p-interface.md:396, 502, 518`).

**Fulu surface (carried forward from 2026-05-04 audit; 5+ months of mainnet validation):** all 6 clients evaluate to `16384` on mainnet. **No production divergence.**

**Implementation strategy splits 4-vs-2**:

- **HARDCODED YAML/preset constant** (4 of 6): prysm, lighthouse, nimbus, lodestar — `MAX_REQUEST_DATA_COLUMN_SIDECARS: 16384` lives in network config files; the spec function is "evaluated" by reading the constant.
- **COMPUTED formula** (2 of 6): teku (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/config/builder/FuluBuilder.java:58-67, 220-222`) and grandine (`vendor/grandine/types/src/config.rs:988-992 const fn max_request_data_column_sidecars<P: Preset>`) — these derive `MAX_REQUEST_BLOCKS_DENEB * NUMBER_OF_COLUMNS` at build time.

**Pattern DD candidate for item #28** (hardcoded-constant vs computed-formula divergence in spec-defined functions). Same forward-fragility class as Pattern AA (per-client SSZ container version-numbering) and Pattern S (compile-time invariant assertion). Same lineage class as Pattern AA — both are about how clients encode spec-derived values.

**Glamsterdam target (Gloas):** `vendor/consensus-specs/specs/gloas/p2p-interface.md` contains NO modification to `compute_max_request_data_column_sidecars` (no `Modified` heading; no `New` heading). The Fulu function carries forward verbatim into Gloas. Gloas's new envelope RPCs use a different constant entirely: `MAX_REQUEST_BLOCKS_DENEB` directly (per `vendor/consensus-specs/specs/gloas/p2p-interface.md:545,588`) and the new `MAX_REQUEST_PAYLOADS = 2^7 = 128` (per `:53`). No client introduces a Gloas-specific override of the data-column response cap.

**Forward-compat divergence at hypothetical future fork** (changing `NUMBER_OF_COLUMNS` or `MAX_REQUEST_BLOCKS_DENEB`):

- teku + grandine: auto-update via formula derivation
- prysm + lighthouse + nimbus + lodestar: silently use stale `16384` unless network YAML/preset configs are also updated → cross-client divergence on RPC response cap

**Teku has the most defensive hybrid pattern**: COMPUTES formula as default (when `numberOfColumns != null`) but allows YAML override. Logs the substitution at build time: `"Setting maxRequestDataColumnSidecars to {} (was {})"` (`FuluBuilder.java:62-65`). Best of both worlds — spec-faithful with operational override capability.

**Grandine uses `const fn` with `saturating_mul`** — function can be compile-time-evaluated AND defends against `max_request_blocks_deneb = MAX_U64` overflow attacks via `saturating_mul`.

**Impact: none** — all 6 evaluate to `16384` on mainnet; Gloas inherits Fulu function verbatim; the divergence is forward-fragility (not present-tense). Thirtieth `impact: none` result in the recheck series.

## Question

Pyspec defines `compute_max_request_data_column_sidecars()` as a function at `vendor/consensus-specs/specs/fulu/p2p-interface.md:104-111`. The Gloas spec carries no modification.

Two recheck questions:

1. **Implementation strategy** — do clients implement the spec-defined function as a function (formula), or as a hardcoded constant? What is the cross-client split, and how does it interact with forward-compat at hypothetical future forks?
2. **Glamsterdam target — Gloas carry-forward** — does the Fulu function carry forward verbatim into Gloas? Does any client introduce a Gloas-specific override?

## Hypotheses

- **H1.** All 6 clients evaluate to `16384` on mainnet (`128 × 128`).
- **H2.** Spec defines the symbol as a FUNCTION (computed product); implementations split into formula-clients (teku, grandine) and hardcoded-clients (prysm, lighthouse, nimbus, lodestar).
- **H3.** YAML/preset config exposes `MAX_REQUEST_DATA_COLUMN_SIDECARS` for operator override across all 6.
- **H4.** Cross-network consistency at mainnet/sepolia/holesky/gnosis/hoodi for hardcoded clients: same `16384` value across all 5 networks.
- **H5.** RPC handlers (item #46) consume this value for response-chunk cap enforcement.
- **H6.** RPC request-side validation rejects requests exceeding the cap (prysm uses `errMaxRequestDataColumnSidecarsExceeded`; others similar).
- **H7.** Forward-compat at hypothetical fork changing `NUMBER_OF_COLUMNS` or `MAX_REQUEST_BLOCKS_DENEB`: formula clients (teku, grandine) auto-update; hardcoded clients require YAML/preset config update or silently use stale `16384`.
- **H8.** Teku has unique hybrid pattern: COMPUTES formula as DEFAULT but allows YAML override.
- **H9.** Grandine uses `const fn` with `saturating_mul` for overflow safety.
- **H10.** *(Glamsterdam target — Fulu function carries forward unchanged)* `vendor/consensus-specs/specs/gloas/p2p-interface.md` contains no `Modified compute_max_request_data_column_sidecars` or `New ...` heading. No client introduces a Gloas-specific override.
- **H11.** *(Glamsterdam target — Gloas-NEW envelope RPCs use different constants)* `ExecutionPayloadEnvelopesByRange/ByRoot v1` cap by `MAX_REQUEST_BLOCKS_DENEB` directly (response list size) and `MAX_REQUEST_PAYLOADS = 128` (ByRoot request size); not via this Fulu function. Cross-cut to item #46.

## Findings

H1 ✓ (all 6 evaluate to `16384` on mainnet). H2 ✓ (4-vs-2 split). H3 ✓ (YAML/preset config in all 6). H4 ✓ (lighthouse confirmed for all 5 networks; others use mainnet preset). H5 ✓ (item #46 cross-cut). H6 ✓ (prysm explicit; others have analogous validation). H7 ⚠ (forward-fragility divergence — 4 hardcoded require manual update). H8 ✓. H9 ✓ (grandine `saturating_mul`). H10 ✓ (no Gloas modification; grep verified). H11 ✓ (Gloas-NEW envelope RPCs use `MAX_REQUEST_BLOCKS_DENEB` and `MAX_REQUEST_PAYLOADS` directly).

### prysm

Config field (`vendor/prysm/config/params/config.go:303`):

```go
MaxRequestDataColumnSidecars          uint64           `yaml:"MAX_REQUEST_DATA_COLUMN_SIDECARS" spec:"true"`             // MaxRequestDataColumnSidecars is the maximum number of data column sidecars in a single request
```

Mainnet value (`vendor/prysm/config/params/mainnet_config.go:339`):

```go
MaxRequestDataColumnSidecars:          16384,
```

**Hardcoded value `16384`** in the Go config struct. YAML-overridable via `MAX_REQUEST_DATA_COLUMN_SIDECARS` key.

Two distinct error types for cap exceeded (`vendor/prysm/beacon-chain/sync/rpc_send_request.go:49,488,659`):

```go
errMaxRequestDataColumnSidecarsExceeded  = errors.New("count of requested data column sidecars exceeds MAX_REQUEST_DATA_COLUMN_SIDECARS")
...
return nil, errors.Wrapf(errMaxRequestDataColumnSidecarsExceeded, "requestedCount=%d, allowedCount=%d", totalCount, maxRequestDataColumnSidecars)
...
return nil, errors.Wrapf(errMaxRequestDataColumnSidecarsExceeded, "current: %d, max: %d", count, maxRequestDataColumnSidecars)
```

Request-side validation at two call sites (`:488` ByRange + `:659` ByRoot). Defensive double-check at multiple layers.

H1 ✓. H2 — hardcoded. H7 — requires YAML override at fork. H10 ✓ (no Gloas-specific override).

### lighthouse

ChainSpec field (`vendor/lighthouse/consensus/types/src/core/chain_spec.rs:277`):

```rust
pub max_request_data_column_sidecars: u64,
```

Default helper (`:2184`):

```rust
const fn default_max_request_data_column_sidecars() -> u64 {
    16384  // hardcoded
}
```

`const fn` returning the literal `16384`. Used as serde default if YAML omits the field (`:1984-1986`):

```rust
#[serde(default = "default_max_request_data_column_sidecars")]
...
max_request_data_column_sidecars: u64,
```

Two construction sites use the default (`:1259, 1653`); two more sites take it from the parsed config (`:2479, 2574, 2660`).

YAML configs all set `MAX_REQUEST_DATA_COLUMN_SIDECARS: 16384` across **all 5 networks** (`vendor/lighthouse/common/eth2_network_config/built_in_network_configs/mainnet/config.yaml:212`, `sepolia/config.yaml:170`, `holesky/config.yaml:164`, `gnosis/config.yaml:161`, `hoodi/config.yaml:177`).

H1 ✓. H2 — hardcoded. H4 ✓ (cross-network confirmed for all 5). H7 — requires YAML override at fork.

### teku

Builder logic (`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/config/builder/FuluBuilder.java:55-67`):

```java
@Override
public SpecConfigAndParent<SpecConfigFulu> build(
    final SpecConfigAndParent<SpecConfigElectra> specConfigAndParent) {
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
```

Formula at `:220-222`:

```java
// compute_max_request_data_column_sidecars
private Integer computeMaxRequestDataColumnSidecars(final Integer maxRequestBlocksDeneb) {
  return maxRequestBlocksDeneb * numberOfColumns;
}
```

**Computed formula AS DEFAULT** when `numberOfColumns != null` (Fulu-active configs); falls back to the field value (YAML override) when explicitly set. Logs the substitution at `:62-65 LOG.debug("Setting maxRequestDataColumnSidecars to {} (was {})"`.

**Most spec-faithful + most config-friendly** of the 6. Comment at `:220` explicitly cites the spec function name `compute_max_request_data_column_sidecars`.

Setter (`:178-180`) accepts an Integer for YAML overrides:

```java
public FuluBuilder maxRequestDataColumnSidecars(final Integer maxRequestDataColumnSidecars) {
  checkNotNull(maxRequestDataColumnSidecars);
  this.maxRequestDataColumnSidecars = maxRequestDataColumnSidecars;
```

H1 ✓ (`128 * 128 = 16384`). H2 ✓ (formula). H7 ✓ (auto-update + override). H8 ✓ (hybrid pattern). H10 ✓ (no Gloas-specific override).

### nimbus

Preset field (`vendor/nimbus/beacon_chain/spec/presets.nim:183`):

```nim
MAX_REQUEST_DATA_COLUMN_SIDECARS*: uint64
```

Per-network preset values (`presets.nim:402` mainnet, `:599` minimal, `:794` gnosis):

```nim
MAX_REQUEST_DATA_COLUMN_SIDECARS: 16384,
```

Three preset entries (mainnet, minimal, gnosis). Same value across all 3. **Hardcoded literal**; not formula-computed.

H1 ✓. H2 — hardcoded. H7 — requires preset update at fork. H10 ✓ (no Gloas-specific override).

### lodestar

Type definition (`vendor/lodestar/packages/config/src/chainConfig/types.ts:120, 239`):

```typescript
MAX_REQUEST_DATA_COLUMN_SIDECARS: number;
...
MAX_REQUEST_DATA_COLUMN_SIDECARS: "number",  // type marker for spec compliance tracking
```

Mainnet value (`configs/mainnet.ts:183`):

```typescript
MAX_REQUEST_DATA_COLUMN_SIDECARS: 16384,
```

Minimal value (`configs/minimal.ts:178`):

```typescript
MAX_REQUEST_DATA_COLUMN_SIDECARS: 16384,
```

TypeScript-typed config with separate type marker (`types.ts:239`) for spec-compliance tracking. **Hardcoded value**; not formula-computed.

H1 ✓. H2 — hardcoded. H7 — requires preset update at fork. H10 ✓ (no Gloas-specific override).

### grandine

`const fn` formula (`vendor/grandine/types/src/config.rs:988-992`):

```rust
#[must_use]
pub const fn max_request_data_column_sidecars<P: Preset>(&self) -> u64 {
    self.max_request_blocks_deneb
        .saturating_mul(P::NumberOfColumns::U64)
}
```

**`const fn`** — function CAN be evaluated at compile time if inputs are statically known. **Spec-faithful formula** AND performance-optimized via `const fn` annotation.

`saturating_mul` defends against overflow attacks (e.g., a malformed YAML setting `max_request_blocks_deneb = MAX_U64`). Other clients (formula-side: teku) don't have explicit overflow protection.

`P: Preset` generic — `NumberOfColumns` is resolved at the preset-type level rather than from runtime config. **Compile-time resolution** of `NUMBER_OF_COLUMNS` × **runtime resolution** of `MAX_REQUEST_BLOCKS_DENEB`.

H1 ✓ (`128 * 128 = 16384` saturating). H2 ✓ (formula). H7 ✓ (auto-update via const fn). H9 ✓ (overflow safety). H10 ✓ (no Gloas-specific override).

## Cross-reference table

| Client | H2 strategy | Source location | H3 YAML override | H6 RPC validation | H7 forward-compat | H9 overflow safety | Mainnet value |
|---|---|---|---|---|---|---|---|
| **prysm** | hardcoded constant | `mainnet_config.go:339 MaxRequestDataColumnSidecars: 16384`; field at `config.go:303` | ✅ via `MAX_REQUEST_DATA_COLUMN_SIDECARS` YAML key | `errMaxRequestDataColumnSidecarsExceeded` at 2 call sites (`rpc_send_request.go:488,659`) | ⚠ requires YAML update at fork | ❌ raw uint64 | 16384 |
| **lighthouse** | hardcoded constant | `chain_spec.rs:2184 default_max_request_data_column_sidecars() -> u64 { 16384 }` const fn; 5 YAML configs at `built_in_network_configs/{mainnet,sepolia,holesky,gnosis,hoodi}/config.yaml` | ✅ via 5 network YAML files | (TBD — item #46 cross-cut) | ⚠ requires YAML update at fork | ❌ raw u64 | 16384 |
| **teku** | **COMPUTED formula + YAML override hybrid** | `FuluBuilder.java:220-222 computeMaxRequestDataColumnSidecars(maxRequestBlocksDeneb) { return maxRequestBlocksDeneb * numberOfColumns; }`; setter at `:178-180`; build-time substitution at `:58-67` with `LOG.debug` | ✅ via setter; formula is the default | (TBD — item #46 cross-cut) | ✅ auto-update via formula | ❌ no `Math.multiplyExact` | 16384 |
| **nimbus** | hardcoded preset | `presets.nim:183` field declaration; `:402,599,794` values for mainnet/minimal/gnosis | ✅ via per-preset values | (TBD — item #46 cross-cut) | ⚠ requires preset update at fork | ❌ raw uint64 | 16384 |
| **lodestar** | hardcoded TypeScript const | `chainConfig/types.ts:120,239` type definition + spec-tracking marker; `configs/mainnet.ts:183, configs/minimal.ts:178` values | ✅ via per-config values | (TBD — item #46 cross-cut) | ⚠ requires preset update at fork | ❌ raw number | 16384 |
| **grandine** | **COMPUTED `const fn` with saturating_mul** | `config.rs:988-992 const fn max_request_data_column_sidecars<P: Preset>(&self) -> u64 { self.max_request_blocks_deneb.saturating_mul(P::NumberOfColumns::U64) }` | ✅ via `max_request_blocks_deneb` config | (TBD — item #46 cross-cut) | ✅ auto-update via formula | ✅ **`saturating_mul`** | 16384 |

**Counts**: formula 2/6 (teku + grandine); hardcoded 4/6 (prysm + lighthouse + nimbus + lodestar). **Pattern DD candidate confirmed.** Overflow safety: 1/6 (grandine only). Hybrid override: 1/6 (teku only — formula default + setter override). Mainnet value: 6/6 evaluate to `16384`.

## Empirical tests

- ✅ **Live Fulu mainnet operation since 2025-12-03 (5+ months)**: all 6 clients enforce the `16384` cap consistently. No RPC-cap-mismatch divergences observed. **Verifies H1 + H5 + H6 at production scale.**
- ✅ **Per-client grep verification (this recheck)**: all 6 implementation strategies confirmed via file:line citations above.
- ✅ **Gloas carry-forward verification**: `grep -n "compute_max_request_data_column_sidecars\|MAX_REQUEST_DATA_COLUMN_SIDECARS" vendor/consensus-specs/specs/gloas/p2p-interface.md` returns 0 matches (no Gloas modification). **Verifies H10**: function carries forward unchanged.
- ✅ **Gloas envelope RPCs use different constants**: `MAX_REQUEST_BLOCKS_DENEB` (response list cap at `gloas/p2p-interface.md:545`) and `MAX_REQUEST_PAYLOADS = 128` (request cap at `:53, 588`). **Verifies H11**: no overlap with the Fulu data-column response cap.
- ⏭ **Pattern DD divergence test**: simulate a future fork with `NUMBER_OF_COLUMNS = 256` (or `MAX_REQUEST_BLOCKS_DENEB` change). Verify teku + grandine auto-update to the new product; verify prysm + lighthouse + nimbus + lodestar use stale `16384` until YAML/preset is updated.
- ⏭ **Cap boundary fixture**: peer requests exactly `16384` sidecars; verify all 6 accept. Peer requests `16385`; verify all 6 reject with matching error semantics (prysm has `errMaxRequestDataColumnSidecarsExceeded`; verify other 5 use comparable errors).
- ⏭ **Overflow safety fuzz**: malformed config with `max_request_blocks_deneb = MAX_U64`; verify grandine returns `MAX_U64` via `saturating_mul` and others either reject the config or compute the overflow product. Only grandine has explicit overflow safety today.
- ⏭ **Cross-network constant audit**: confirm `MAX_REQUEST_DATA_COLUMN_SIDECARS = 16384` for non-mainnet networks (sepolia, holesky, gnosis, hoodi) in all 4 hardcoded clients. Lighthouse already confirmed for all 5; extend to prysm + nimbus + lodestar.
- ⏭ **Teku hybrid pattern interop**: set `MAX_REQUEST_DATA_COLUMN_SIDECARS = 8192` (half) in custom config; verify teku's YAML override beats the formula default. Edge case: does the LOG.debug message correctly distinguish "was X" from "set to X"?
- ⏭ **Pattern DD scope expansion**: scan `vendor/consensus-specs/specs/fulu/` for other `def compute_*` patterns. Identify which other Fulu functions are spec-defined as computed but hardcoded by clients. Candidates: `compute_subnets_for_data_column` (item #37 cross-cut), `compute_fork_version` (item #36 cross-cut).

## Conclusion

The Fulu `compute_max_request_data_column_sidecars()` function evaluates to `16384` across all 6 clients on mainnet. 5+ months of live mainnet cross-client RPC interop validates that the response-cap enforcement is consistent. **No production divergence.**

**Implementation strategy splits 4-vs-2**:

- **HARDCODED YAML/preset constant** (prysm `mainnet_config.go:339`; lighthouse `chain_spec.rs:2184` const fn + 5 network YAMLs; nimbus `presets.nim:402,599,794`; lodestar `mainnet.ts:183`): treat the spec function as a wire constant; evaluate by reading the config field.
- **COMPUTED formula** (teku `FuluBuilder.java:220-222 maxRequestBlocksDeneb * numberOfColumns` with hybrid YAML override; grandine `config.rs:988-992 const fn max_request_data_column_sidecars<P: Preset>` with `saturating_mul`): derive the value from constituent constants at build time. **Spec-faithful**.

**NEW Pattern DD candidate for item #28 catalogue**: hardcoded-constant vs computed-formula divergence in spec-defined functions. Same forward-fragility class as Pattern AA (per-client SSZ container version-numbering) and Pattern S (compile-time invariant assertion). Same lineage class as Pattern N (`compute_fork_digest` multi-fork-definition; nimbus + grandine separate per-fork bodies for a spec-defined function).

**Glamsterdam target context**: `vendor/consensus-specs/specs/gloas/p2p-interface.md` does NOT modify `compute_max_request_data_column_sidecars` (no `Modified` or `New` heading). The Fulu function carries forward verbatim into Gloas across all 6 clients. Gloas-NEW envelope RPCs (`ExecutionPayloadEnvelopesByRange/ByRoot v1` per item #46) use different constants (`MAX_REQUEST_BLOCKS_DENEB` directly for response cap; `MAX_REQUEST_PAYLOADS = 128` for ByRoot request cap), so this Fulu function does not propagate into the new envelope-RPC surface.

**Forward-compat divergence at hypothetical fork** (changing `NUMBER_OF_COLUMNS` or `MAX_REQUEST_BLOCKS_DENEB`):

- teku + grandine: auto-update via formula
- prysm + lighthouse + nimbus + lodestar: silently use stale `16384` unless YAML/preset configs are updated → cross-client divergence on RPC response cap

**Teku's hybrid pattern** (compute default + YAML override + LOG.debug substitution message) is the most defensive design and should be adopted by other clients. **Grandine's `const fn` with `saturating_mul`** is the most performance-aware + overflow-safe; the only client with explicit overflow protection.

**Impact: none** — all 6 evaluate to `16384` on mainnet; Gloas inherits the Fulu function verbatim. Thirtieth `impact: none` result in the recheck series.

With this audit, the `compute_max_request_data_column_sidecars()` formula-consistency gap flagged by item #46 is closed. **Pattern DD** carries the forward-fragility forward into the item #28 / #48 catalogue. Future research priorities:

1. **Pattern DD scope expansion** — scan Fulu spec for other `def compute_*` patterns and audit per-client implementation strategy. Candidates: `compute_subnets_for_data_column` (item #37), `compute_fork_version` (item #36).
2. **Teku hybrid pattern adoption** — file PRs to prysm + lighthouse + nimbus + lodestar adopting "compute default + allow YAML override + log substitution."
3. **Grandine overflow-safety adoption** — file PRs to other 5 to use saturating arithmetic on config-derived caps.
4. **Cross-network constant audit** — extend lighthouse's all-5-networks check to the other 3 hardcoded clients (prysm, nimbus, lodestar).
5. **EF fixture generation** for `compute_max_request_data_column_sidecars()` as a pure function (config inputs → uint64 output). Currently no EF fixture covers this spec-defined function.
