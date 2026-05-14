---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: []
eips: []
splits: []
# main_md_summary: TBD — drafting `DOMAIN_*` constants byte-by-byte cross-client audit (15+ domain constants; wrong byte invalidates every signature for that purpose; trivial to audit, high consequence)
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 69: `DOMAIN_*` constants byte-by-byte cross-client audit

## Summary

> **DRAFT — hypotheses-pending.** 15+ `DOMAIN_*` 4-byte constants drive signature-domain separation (DOMAIN_BEACON_PROPOSER, DOMAIN_RANDAO, DOMAIN_DEPOSIT, DOMAIN_VOLUNTARY_EXIT, DOMAIN_SELECTION_PROOF, DOMAIN_AGGREGATE_AND_PROOF, DOMAIN_SYNC_COMMITTEE, DOMAIN_SYNC_COMMITTEE_SELECTION_PROOF, DOMAIN_CONTRIBUTION_AND_PROOF, DOMAIN_BLS_TO_EXECUTION_CHANGE, DOMAIN_BEACON_ATTESTER, DOMAIN_PTC_ATTESTER=0x0C, DOMAIN_BEACON_BUILDER=0x0B, DOMAIN_APPLICATION_BUILDER, DOMAIN_APPLICATION_MASK).
>
> A wrong byte in any single constant silently invalidates every BLS signature using that purpose for the client that has it wrong — the signature won't verify against the canonical pubkey set, so the client rejects all (or accepts none) of that operation. Easy to detect under EF testing but worth a one-pass cross-client audit because:
> 1. Gloas added new constants (DOMAIN_PTC_ATTESTER, DOMAIN_BEACON_BUILDER).
> 2. Constant tables are easy to typo and easy to miss in code review.
> 3. Trivial to audit (single 4-byte value lookup per constant per client).

## Question

Canonical DOMAIN constants per the consensus-specs corpus:

```
DOMAIN_BEACON_PROPOSER                  = 0x00000000
DOMAIN_BEACON_ATTESTER                  = 0x01000000
DOMAIN_RANDAO                           = 0x02000000
DOMAIN_DEPOSIT                          = 0x03000000
DOMAIN_VOLUNTARY_EXIT                   = 0x04000000
DOMAIN_SELECTION_PROOF                  = 0x05000000
DOMAIN_AGGREGATE_AND_PROOF              = 0x06000000
DOMAIN_SYNC_COMMITTEE                   = 0x07000000
DOMAIN_SYNC_COMMITTEE_SELECTION_PROOF   = 0x08000000
DOMAIN_CONTRIBUTION_AND_PROOF           = 0x09000000
DOMAIN_BLS_TO_EXECUTION_CHANGE          = 0x0A000000
DOMAIN_BEACON_BUILDER                   = 0x0B000000  # Gloas
DOMAIN_PTC_ATTESTER                     = 0x0C000000  # Gloas
DOMAIN_APPLICATION_BUILDER              = 0x00000001  # builder API
DOMAIN_APPLICATION_MASK                 = 0x00000001
```

Open questions:

1. **All constants present** — does every client define all 13+ standard `DOMAIN_*` values + the Gloas additions?
2. **Byte-for-byte agreement** — typo audit.
3. **Where are they defined** — runtime config, compile-time constants, or hardcoded?
4. **Used vs defined** — any constants defined but never used? Or used somewhere with a wrong inline literal?

## Hypotheses

- **H1.** All six clients define all 13+ canonical `DOMAIN_*` constants at the byte-equivalent values listed above.
- **H2.** All six use the constants symbolically (no inline `[0x0B, 0, 0, 0]` literals at call sites).
- **H3.** All six fork-gate `DOMAIN_PTC_ATTESTER` and `DOMAIN_BEACON_BUILDER` correctly (Gloas-only; not used pre-Gloas).
- **H4.** No client has stale Altair-era constants that drifted (e.g., `DOMAIN_SYNC_COMMITTEE` originally `0x07` then re-aliased — verify).

## Findings

> **TBD — drafting.** Each client subsection below is a stub awaiting source review.

### prysm

TBD — drafting. Entry point: `vendor/prysm/config/params/mainnet_config.go` `DomainBeaconProposer`/etc.

### lighthouse

TBD — drafting. Entry point: `vendor/lighthouse/consensus/types/src/core/chain_spec.rs` `Domain` enum / constants.

### teku

TBD — drafting. Entry point: `vendor/teku/ethereum/spec/.../config/spec_config.yaml` + `Domain.java` constants.

### nimbus

TBD — drafting. Entry point: `vendor/nimbus/beacon_chain/spec/datatypes/base.nim` `DOMAIN_*` consts.

### lodestar

TBD — drafting. Entry point: `vendor/lodestar/packages/params/src/constants.ts` `DOMAIN_*` exports.

### grandine

TBD — drafting. Entry point: `vendor/grandine/types/src/phase0/consts.rs` + `gloas/consts.rs`.

## Cross-reference table

| DOMAIN | Spec value | prysm | lighthouse | teku | nimbus | lodestar | grandine |
|---|---|---|---|---|---|---|---|
| `BEACON_PROPOSER` | `0x00000000` | TBD | TBD | TBD | TBD | TBD | TBD |
| `BEACON_ATTESTER` | `0x01000000` | TBD | TBD | TBD | TBD | TBD | TBD |
| `RANDAO` | `0x02000000` | TBD | TBD | TBD | TBD | TBD | TBD |
| `DEPOSIT` | `0x03000000` | TBD | TBD | TBD | TBD | TBD | TBD |
| `VOLUNTARY_EXIT` | `0x04000000` | TBD | TBD | TBD | TBD | TBD | TBD |
| `SELECTION_PROOF` | `0x05000000` | TBD | TBD | TBD | TBD | TBD | TBD |
| `AGGREGATE_AND_PROOF` | `0x06000000` | TBD | TBD | TBD | TBD | TBD | TBD |
| `SYNC_COMMITTEE` | `0x07000000` | TBD | TBD | TBD | TBD | TBD | TBD |
| `SYNC_COMMITTEE_SELECTION_PROOF` | `0x08000000` | TBD | TBD | TBD | TBD | TBD | TBD |
| `CONTRIBUTION_AND_PROOF` | `0x09000000` | TBD | TBD | TBD | TBD | TBD | TBD |
| `BLS_TO_EXECUTION_CHANGE` | `0x0A000000` | TBD | TBD | TBD | TBD | TBD | TBD |
| `BEACON_BUILDER` (Gloas) | `0x0B000000` | TBD | TBD | TBD | TBD | TBD | TBD |
| `PTC_ATTESTER` (Gloas) | `0x0C000000` | TBD | TBD | TBD | TBD | TBD | TBD |
| `APPLICATION_BUILDER` | `0x00000001` | TBD | TBD | TBD | TBD | TBD | TBD |

## Empirical tests

> **TBD — drafting.** Coverage from every signature-verifying fixture. Cross-client mismatch on any DOMAIN would surface as universal rejection of the corresponding operation type for the divergent client.

### Suggested fuzzing vectors

- **T1.1 (single-block import).** Block carrying every operation type at least once. Verify all clients accept (proves all 13+ DOMAIN constants are correct enough to verify signatures).
- **T2.1 (PTC vote).** Gloas-specific: PTC attestation. Verifies `DOMAIN_PTC_ATTESTER`.
- **T2.2 (Builder signature).** Gloas-specific: builder bid signature. Verifies `DOMAIN_BEACON_BUILDER`.

## Conclusion

> **TBD — drafting.** Expected outcome: all constants identical. Trivial-but-pivotal audit. Worth running once.

## Cross-cuts

### With item #60 (`is_valid_indexed_payload_attestation`)

Uses `DOMAIN_PTC_ATTESTER`. Cross-cut: if any client mis-defines it, item #60's BLS check fails universally.

### With item #58 (`process_execution_payload_bid`)

Uses `DOMAIN_BEACON_BUILDER`. Cross-cut.

### With every signature-bearing operation in the spec

If any DOMAIN is wrong, the corresponding operation type fails universally.

## Adjacent untouched

1. **`compute_signing_root` / `compute_domain` cross-client** — the function that combines the 4-byte DOMAIN with `fork_version` + `genesis_validators_root` into the 32-byte signing domain. Sibling audit.
2. **`compute_fork_data_root` cross-client** — input to `compute_domain`.
3. **`genesis_validators_root` propagation** — verify all 6 clients persist it identically across reboots / re-syncs.
