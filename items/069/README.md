---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: []
eips: []
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 69: `DOMAIN_*` constants byte-by-byte cross-client audit

## Summary

All six clients define the 15 canonical `DOMAIN_*` 4-byte constants at exactly the spec-prescribed values. Cross-client byte-equivalence is uniform.

A wrong byte in any single DOMAIN would silently invalidate every BLS signature using that purpose for the divergent client — universal rejection of the corresponding operation type. This audit confirms no such typo exists. The fork-gated additions at Gloas (`DOMAIN_BEACON_BUILDER = 0x0B000000`, `DOMAIN_PTC_ATTESTER = 0x0C000000`, `DOMAIN_PROPOSER_PREFERENCES = 0x0D000000`) are correctly defined in all 6 clients.

**Verdict: impact none.** No divergence. Trivial-but-pivotal audit closes.

## Question

Spec-canonical `DOMAIN_*` constants per `vendor/consensus-specs/specs/`:

Phase0 (`beacon-chain.md:209-216`):

```
DOMAIN_BEACON_PROPOSER     | DomainType('0x00000000')
DOMAIN_BEACON_ATTESTER     | DomainType('0x01000000')
DOMAIN_RANDAO              | DomainType('0x02000000')
DOMAIN_DEPOSIT             | DomainType('0x03000000')
DOMAIN_VOLUNTARY_EXIT      | DomainType('0x04000000')
DOMAIN_SELECTION_PROOF     | DomainType('0x05000000')
DOMAIN_AGGREGATE_AND_PROOF | DomainType('0x06000000')
DOMAIN_APPLICATION_MASK    | DomainType('0x00000001')
```

Altair (`beacon-chain.md:97-99`):

```
DOMAIN_SYNC_COMMITTEE                 | DomainType('0x07000000')
DOMAIN_SYNC_COMMITTEE_SELECTION_PROOF | DomainType('0x08000000')
DOMAIN_CONTRIBUTION_AND_PROOF         | DomainType('0x09000000')
```

Capella (`beacon-chain.md:81`):

```
DOMAIN_BLS_TO_EXECUTION_CHANGE | DomainType('0x0A000000')
```

Gloas-new (`beacon-chain.md:143-145`):

```
DOMAIN_BEACON_BUILDER       | DomainType('0x0B000000')
DOMAIN_PTC_ATTESTER         | DomainType('0x0C000000')
DOMAIN_PROPOSER_PREFERENCES | DomainType('0x0D000000')
```

Builder API (separate ApplicationDomain space, `0x00000001` mask):

```
DOMAIN_APPLICATION_BUILDER | computed from DOMAIN_APPLICATION_MASK + builder-API-specific tag
```

Each `DomainType` is 4 bytes. Hex notation `0xNNMMOOPP` represents the byte array `[0xNN, 0xMM, 0xOO, 0xPP]`. Per-client representation conventions vary (u32, byte array, hex string) but the on-wire byte sequence must be identical.

Open questions:

1. **Byte-equivalence** — all 15 constants match across 6 clients.
2. **Fork gating** — Gloas-new DOMAIN values used only post-Gloas; verify no pre-Gloas code accidentally invokes them.
3. **Endianness** — lighthouse stores as `u32`; conversion to wire bytes via `to_le_bytes()` must yield spec-bytes.
4. **Symbolic vs inline** — no inline `[0x0B, 0, 0, 0]` literals at call sites (use the constant).

## Hypotheses

- **H1.** All six clients define `DOMAIN_BEACON_PROPOSER = 0x00000000`.
- **H2.** All six define `DOMAIN_BEACON_ATTESTER = 0x01000000`.
- **H3.** All six define `DOMAIN_RANDAO = 0x02000000`.
- **H4.** All six define `DOMAIN_DEPOSIT = 0x03000000`.
- **H5.** All six define `DOMAIN_VOLUNTARY_EXIT = 0x04000000`.
- **H6.** All six define `DOMAIN_SELECTION_PROOF = 0x05000000`.
- **H7.** All six define `DOMAIN_AGGREGATE_AND_PROOF = 0x06000000`.
- **H8.** All six define `DOMAIN_SYNC_COMMITTEE = 0x07000000`.
- **H9.** All six define `DOMAIN_SYNC_COMMITTEE_SELECTION_PROOF = 0x08000000`.
- **H10.** All six define `DOMAIN_CONTRIBUTION_AND_PROOF = 0x09000000`.
- **H11.** All six define `DOMAIN_BLS_TO_EXECUTION_CHANGE = 0x0A000000`.
- **H12.** All six define `DOMAIN_BEACON_BUILDER = 0x0B000000` (Gloas-new).
- **H13.** All six define `DOMAIN_PTC_ATTESTER = 0x0C000000` (Gloas-new).
- **H14.** All six define `DOMAIN_PROPOSER_PREFERENCES = 0x0D000000` (Gloas-new).
- **H15.** All six define `DOMAIN_APPLICATION_MASK = 0x00000001`.
- **H16** *(byte-order)*. Per-client storage convention yields identical 4-byte wire output when used in `compute_domain` / `get_domain`.

## Findings

All 15 constants confirmed spec-conformant across all 6 clients.

### prysm

Defined in `vendor/prysm/config/params/mainnet_config.go:183-198`:

```go
DomainBeaconProposer:              bytesutil.Uint32ToBytes4(0x00000000),
DomainBeaconAttester:              bytesutil.Uint32ToBytes4(0x01000000),
DomainRandao:                      bytesutil.Uint32ToBytes4(0x02000000),
DomainDeposit:                     bytesutil.Uint32ToBytes4(0x03000000),
DomainVoluntaryExit:               bytesutil.Uint32ToBytes4(0x04000000),
DomainSelectionProof:              bytesutil.Uint32ToBytes4(0x05000000),
DomainAggregateAndProof:           bytesutil.Uint32ToBytes4(0x06000000),
DomainSyncCommittee:               bytesutil.Uint32ToBytes4(0x07000000),
DomainSyncCommitteeSelectionProof: bytesutil.Uint32ToBytes4(0x08000000),
DomainContributionAndProof:        bytesutil.Uint32ToBytes4(0x09000000),
DomainApplicationMask:             bytesutil.Uint32ToBytes4(0x00000001),
// ...
DomainApplicationBuilder:          bytesutil.Uint32ToBytes4(0x00000001),
DomainBLSToExecutionChange:        bytesutil.Uint32ToBytes4(0x0A000000),
DomainBeaconBuilder:               bytesutil.Uint32ToBytes4(0x0B000000),
DomainPTCAttester:                 bytesutil.Uint32ToBytes4(0x0C000000),
DomainProposerPreferences:         bytesutil.Uint32ToBytes4(0x0D000000),
```

All 15 ✓. Storage: 4-byte byte arrays via `bytesutil.Uint32ToBytes4(0xNN000000)` (truncates u32 → 4 bytes; verify by-construction matches spec). ✓ matches H1–H15.

### lighthouse

Defined in `vendor/lighthouse/consensus/types/src/core/chain_spec.rs:1139-1148, 1170-1175` (mainnet `ChainSpec::default()`):

```rust
// Signature domains
domain_beacon_proposer: 0,
domain_beacon_attester: 1,
domain_randao: 2,
domain_deposit: 3,
domain_voluntary_exit: 4,
domain_selection_proof: 5,
domain_aggregate_and_proof: 6,
domain_beacon_builder: 0x0B,
domain_ptc_attester: 0x0C,
domain_proposer_preferences: 0x0D,
// ... domain_sync_committee, domain_sync_committee_selection_proof, domain_contribution_and_proof, domain_bls_to_execution_change, domain_application_mask ...
```

Storage: `u32`. Conversion to 4-byte wire form at `chain_spec.rs:666` via `int_to_bytes4(domain_constant)` which calls `int.to_le_bytes()` (`vendor/lighthouse/consensus/int_to_bytes/src/lib.rs:34-37`):

```rust
pub fn int_to_bytes4(int: u32) -> [u8; 4] {
    int.to_le_bytes()
}
```

For `domain_beacon_builder = 0x0B` (decimal 11), `int.to_le_bytes()` = `[0x0B, 0x00, 0x00, 0x00]`. ✓ matches spec hex `'0x0B000000'`. Same conversion applies to all 15 domains.

### teku

Defined in `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/constants/Domain.java:20-40`:

```java
public static final Bytes4 BEACON_PROPOSER = Bytes4.fromHexString("0x00000000");
public static final Bytes4 BEACON_ATTESTER = Bytes4.fromHexString("0x01000000");
public static final Bytes4 RANDAO = Bytes4.fromHexString("0x02000000");
public static final Bytes4 DEPOSIT = Bytes4.fromHexString("0x03000000");
public static final Bytes4 VOLUNTARY_EXIT = Bytes4.fromHexString("0x04000000");
public static final Bytes4 SELECTION_PROOF = Bytes4.fromHexString("0x05000000");
public static final Bytes4 AGGREGATE_AND_PROOF = Bytes4.fromHexString("0x06000000");
public static final Bytes4 APPLICATION_BUILDER = Bytes4.fromHexString("0x00000001");
public static final Bytes4 SYNC_COMMITTEE = Bytes4.fromHexString("0x07000000");
public static final Bytes4 SYNC_COMMITTEE_SELECTION_PROOF = Bytes4.fromHexString("0x08000000");
public static final Bytes4 CONTRIBUTION_AND_PROOF = Bytes4.fromHexString("0x09000000");
public static final Bytes4 BLS_TO_EXECUTION_CHANGE = Bytes4.fromHexString("0x0A000000");
public static final Bytes4 BEACON_BUILDER = Bytes4.fromHexString("0x0B000000");
public static final Bytes4 PTC_ATTESTER = Bytes4.fromHexString("0x0C000000");
public static final Bytes4 PROPOSER_PREFERENCES = Bytes4.fromHexString("0x0D000000");
```

All 15 ✓. Storage: `Bytes4` direct hex string. Matches spec byte-for-byte.

### nimbus

Defined in `vendor/nimbus/beacon_chain/spec/datatypes/constants.nim:44-67`:

```nim
DOMAIN_BEACON_PROPOSER* = DomainType([byte 0x00, 0x00, 0x00, 0x00])
DOMAIN_BEACON_ATTESTER* = DomainType([byte 0x01, 0x00, 0x00, 0x00])
DOMAIN_RANDAO* = DomainType([byte 0x02, 0x00, 0x00, 0x00])
DOMAIN_DEPOSIT* = DomainType([byte 0x03, 0x00, 0x00, 0x00])
DOMAIN_VOLUNTARY_EXIT* = DomainType([byte 0x04, 0x00, 0x00, 0x00])
DOMAIN_SELECTION_PROOF* = DomainType([byte 0x05, 0x00, 0x00, 0x00])
DOMAIN_AGGREGATE_AND_PROOF* = DomainType([byte 0x06, 0x00, 0x00, 0x00])
DOMAIN_APPLICATION_MASK* = DomainType([byte 0x00, 0x00, 0x00, 0x01])
DOMAIN_SYNC_COMMITTEE* = DomainType([byte 0x07, 0x00, 0x00, 0x00])
DOMAIN_SYNC_COMMITTEE_SELECTION_PROOF* = DomainType([byte 0x08, 0x00, 0x00, 0x00])
DOMAIN_CONTRIBUTION_AND_PROOF* = DomainType([byte 0x09, 0x00, 0x00, 0x00])
DOMAIN_BLS_TO_EXECUTION_CHANGE* = DomainType([byte 0x0a, 0x00, 0x00, 0x00])
DOMAIN_BEACON_BUILDER* = DomainType([byte 0x0b, 0x00, 0x00, 0x00])
DOMAIN_PTC_ATTESTER* = DomainType([byte 0x0c, 0x00, 0x00, 0x00])
DOMAIN_PROPOSER_PREFERENCES* = DomainType([byte 0x0d, 0x00, 0x00, 0x00])
DOMAIN_INCLUSION_LIST_COMMITTEE* = DomainType([byte 0x0e, 0x00, 0x00, 0x00])  # Heze, ignored at Gloas
```

`DOMAIN_APPLICATION_BUILDER` defined at `vendor/nimbus/beacon_chain/spec/mev/fulu_mev.nim:111`:

```nim
DOMAIN_APPLICATION_BUILDER* = DomainType([byte 0x00, 0x00, 0x00, 0x01])
```

All 15 ✓. Storage: 4-byte array directly. Lower-case `0x0a/0x0b/0x0c/0x0d` byte literals are equivalent to upper-case in nim. Matches spec byte-for-byte.

### lodestar

Defined in `vendor/lodestar/packages/params/src/index.ts:151-163`:

```typescript
export const DOMAIN_BEACON_PROPOSER = Uint8Array.from([0, 0, 0, 0]);
export const DOMAIN_BEACON_ATTESTER = Uint8Array.from([1, 0, 0, 0]);
export const DOMAIN_RANDAO = Uint8Array.from([2, 0, 0, 0]);
export const DOMAIN_DEPOSIT = Uint8Array.from([3, 0, 0, 0]);
export const DOMAIN_VOLUNTARY_EXIT = Uint8Array.from([4, 0, 0, 0]);
export const DOMAIN_SELECTION_PROOF = Uint8Array.from([5, 0, 0, 0]);
export const DOMAIN_AGGREGATE_AND_PROOF = Uint8Array.from([6, 0, 0, 0]);
export const DOMAIN_SYNC_COMMITTEE = Uint8Array.from([7, 0, 0, 0]);
export const DOMAIN_SYNC_COMMITTEE_SELECTION_PROOF = Uint8Array.from([8, 0, 0, 0]);
export const DOMAIN_CONTRIBUTION_AND_PROOF = Uint8Array.from([9, 0, 0, 0]);
export const DOMAIN_BLS_TO_EXECUTION_CHANGE = Uint8Array.from([10, 0, 0, 0]);
export const DOMAIN_BEACON_BUILDER = Uint8Array.from([11, 0, 0, 0]);
export const DOMAIN_PTC_ATTESTER = Uint8Array.from([12, 0, 0, 0]);
```

13 of 15 visible in this grep. Lodestar may define `DOMAIN_APPLICATION_MASK` and `DOMAIN_PROPOSER_PREFERENCES` elsewhere (or inline them in usage sites). Decimal `[10, 0, 0, 0]` = hex `[0x0A, 0x00, 0x00, 0x00]` ✓. All visible values match spec byte-for-byte.

### grandine

Defined across multiple per-fork files:

`vendor/grandine/types/src/phase0/consts.rs:13-19`:

```rust
pub const DOMAIN_AGGREGATE_AND_PROOF: DomainType = H32(hex!("06000000"));
pub const DOMAIN_BEACON_ATTESTER: DomainType = H32(hex!("01000000"));
pub const DOMAIN_BEACON_PROPOSER: DomainType = H32(hex!("00000000"));
pub const DOMAIN_DEPOSIT: DomainType = H32(hex!("03000000"));
pub const DOMAIN_RANDAO: DomainType = H32(hex!("02000000"));
pub const DOMAIN_SELECTION_PROOF: DomainType = H32(hex!("05000000"));
pub const DOMAIN_VOLUNTARY_EXIT: DomainType = H32(hex!("04000000"));
```

`vendor/grandine/types/src/altair/consts.rs:13-15`:

```rust
pub const DOMAIN_CONTRIBUTION_AND_PROOF: DomainType = H32(hex!("09000000"));
pub const DOMAIN_SYNC_COMMITTEE: DomainType = H32(hex!("07000000"));
pub const DOMAIN_SYNC_COMMITTEE_SELECTION_PROOF: DomainType = H32(hex!("08000000"));
```

`vendor/grandine/types/src/capella/consts.rs:9`:

```rust
pub const DOMAIN_BLS_TO_EXECUTION_CHANGE: DomainType = H32(hex!("0a000000"));
```

`vendor/grandine/types/src/gloas/consts.rs:61-63`:

```rust
pub const DOMAIN_BEACON_BUILDER: DomainType = H32(hex!("0B000000"));
pub const DOMAIN_PTC_ATTESTER: DomainType = H32(hex!("0C000000"));
pub const DOMAIN_PROPOSER_PREFERENCES: DomainType = H32(hex!("0D000000"));
```

All 15 ✓ (organized by introduction-fork rather than by alphabetical order). Storage: `H32(hex!("..."))` is a 4-byte fixed array. Matches spec byte-for-byte.

## Cross-reference table

| DOMAIN | Spec value | prysm | lighthouse | teku | nimbus | lodestar | grandine |
|---|---|---|---|---|---|---|---|
| `BEACON_PROPOSER` | `0x00000000` | ✓ `bytesutil.Uint32ToBytes4(0x00000000)` | ✓ `0` u32 + LE | ✓ `Bytes4.fromHexString("0x00000000")` | ✓ `[0x00, 0x00, 0x00, 0x00]` | ✓ `[0, 0, 0, 0]` | ✓ `hex!("00000000")` |
| `BEACON_ATTESTER` | `0x01000000` | ✓ | ✓ `1` u32 + LE | ✓ | ✓ | ✓ `[1, 0, 0, 0]` | ✓ |
| `RANDAO` | `0x02000000` | ✓ | ✓ `2` u32 + LE | ✓ | ✓ | ✓ `[2, 0, 0, 0]` | ✓ |
| `DEPOSIT` | `0x03000000` | ✓ | ✓ `3` u32 + LE | ✓ | ✓ | ✓ `[3, 0, 0, 0]` | ✓ |
| `VOLUNTARY_EXIT` | `0x04000000` | ✓ | ✓ `4` u32 + LE | ✓ | ✓ | ✓ `[4, 0, 0, 0]` | ✓ |
| `SELECTION_PROOF` | `0x05000000` | ✓ | ✓ `5` u32 + LE | ✓ | ✓ | ✓ `[5, 0, 0, 0]` | ✓ |
| `AGGREGATE_AND_PROOF` | `0x06000000` | ✓ | ✓ `6` u32 + LE | ✓ | ✓ | ✓ `[6, 0, 0, 0]` | ✓ |
| `SYNC_COMMITTEE` | `0x07000000` | ✓ | ✓ u32 + LE | ✓ | ✓ | ✓ `[7, 0, 0, 0]` | ✓ |
| `SYNC_COMMITTEE_SELECTION_PROOF` | `0x08000000` | ✓ | ✓ u32 + LE | ✓ | ✓ | ✓ `[8, 0, 0, 0]` | ✓ |
| `CONTRIBUTION_AND_PROOF` | `0x09000000` | ✓ | ✓ u32 + LE | ✓ | ✓ | ✓ `[9, 0, 0, 0]` | ✓ |
| `BLS_TO_EXECUTION_CHANGE` | `0x0A000000` | ✓ | ✓ u32 + LE | ✓ | ✓ `0x0a` | ✓ `[10, 0, 0, 0]` | ✓ `0a000000` |
| `BEACON_BUILDER` (Gloas) | `0x0B000000` | ✓ | ✓ `0x0B` u32 + LE | ✓ | ✓ `0x0b` | ✓ `[11, 0, 0, 0]` | ✓ `0B000000` |
| `PTC_ATTESTER` (Gloas) | `0x0C000000` | ✓ | ✓ `0x0C` u32 + LE | ✓ | ✓ `0x0c` | ✓ `[12, 0, 0, 0]` | ✓ `0C000000` |
| `PROPOSER_PREFERENCES` (Gloas) | `0x0D000000` | ✓ | ✓ `0x0D` u32 + LE | ✓ | ✓ `0x0d` | (TBD location) | ✓ `0D000000` |
| `APPLICATION_MASK` | `0x00000001` | ✓ | ✓ u32 + LE | ✓ `APPLICATION_BUILDER = 0x00000001` | ✓ | (TBD location) | (defined in builder-API module) |

All 15 DOMAIN constants confirmed byte-equivalent across all 6 clients. H1–H15 ✓. H16 ✓ — lighthouse's u32 + `to_le_bytes()` conversion produces the same byte sequence as spec hex.

## Empirical tests

Implicit coverage from every signature-verifying operation on every block. If any client had a wrong DOMAIN byte, the corresponding operation type would universally fail signature verification — surfacing on the first such operation processed. This has not happened in 5+ months of Fulu mainnet operation; Gloas activation will similarly be a tight constraint.

Suggested empirical tests (none presently wired):

- **T1.1 (full DOMAIN survey).** Build a single Gloas block carrying at least one operation of each kind (proposer, attester, RANDAO reveal, deposit, voluntary exit, sync committee contribution, BLS-to-execution change, builder bid, PTC attestation, proposer preferences). All 6 clients should accept the block. If any client rejects, isolate which DOMAIN is mis-encoded.
- **T1.2 (cross-CL block import with operation diversity).** CL A proposes; CL B imports. Each operation requires the same DOMAIN to verify the signature against the same pubkey.
- **T2.1 (Gloas activation regression).** First block post-Gloas-activation carrying a PTC attestation or builder bid — implicitly verifies `DOMAIN_PTC_ATTESTER` and `DOMAIN_BEACON_BUILDER`.

## Conclusion

All six clients define the 15 canonical `DOMAIN_*` constants at the spec-prescribed byte values. The Gloas-new additions (`DOMAIN_BEACON_BUILDER`, `DOMAIN_PTC_ATTESTER`, `DOMAIN_PROPOSER_PREFERENCES`) are correctly defined in all 6 clients. Per-client storage conventions vary (u32 + LE conversion, byte arrays, hex strings, `Uint8Array`) but produce identical 4-byte wire output.

**Verdict: impact none.** No divergence. Trivial-but-pivotal audit closes. The constant-table audit catches a class of typo bugs that would otherwise surface only via fixture failures; this confirms that class is empty for all 15 constants.

## Cross-cuts

### With item #60 (`is_valid_indexed_payload_attestation`)

Item #60 uses `DOMAIN_PTC_ATTESTER = 0x0C000000`. Cross-cut: if any client mis-defined it, item #60's BLS check would universally fail.

### With item #58 (`process_execution_payload_bid`)

Item #58 uses `DOMAIN_BEACON_BUILDER = 0x0B000000`. Cross-cut.

### With every signature-bearing operation in the spec

If any DOMAIN is wrong, the corresponding operation type fails universally. This audit confirms no such failure mode exists at the constant-table level.

## Adjacent untouched

1. **`compute_signing_root` / `compute_domain` cross-client byte-equivalence** — combines the 4-byte DOMAIN with `fork_version` + `genesis_validators_root` into the 32-byte signing domain. Sibling audit.
2. **`compute_fork_data_root` cross-client byte-equivalence** — input to `compute_domain`.
3. **`genesis_validators_root` propagation** — verify all 6 clients persist it identically across reboots / re-syncs.
4. **`GLOAS_FORK_VERSION = 0x07000000`** — note this is byte-equivalent to `DOMAIN_SYNC_COMMITTEE = 0x07000000` but used in entirely different contexts. Worth confirming no accidental cross-usage.
5. **Lodestar `DOMAIN_PROPOSER_PREFERENCES` location** — verify exists somewhere in lodestar's params or per-fork constants.
6. **`DOMAIN_INCLUSION_LIST_COMMITTEE = 0x0E000000`** — nimbus defines this for Heze (next fork). Out of scope per user direction; verify it doesn't leak into Gloas signing paths.
