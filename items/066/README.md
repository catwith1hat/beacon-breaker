---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: [4, 22, 23]
eips: [EIP-7732, EIP-8061]
splits: []
# main_md_summary: TBD — drafting `apply_pending_deposit` Gloas modification audit (builders-registry interaction; 0x03 credentials → builder activation vs validator activation)
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 66: `apply_pending_deposit` Gloas modification — 0x03 credentials + builders registry

## Summary

> **DRAFT — hypotheses-pending.** Gloas adds a 0x03 (`BUILDER_WITHDRAWAL_PREFIX`) credential prefix. `apply_pending_deposit` is the deposit-drain (item #4) called from `process_pending_deposits`; at Gloas it must distinguish 0x03 (builder activation → `state.builders` registry) from 0x01/0x02 (validator activation → `state.validators` registry). Branch-coverage audit cross-cutting with items #22 (nimbus 0x03 + compounding bug, fixed) and #23 (nimbus builder/validator OR-fold bug, fixed). PR #8440 history suggests this code path is the most likely place for residual alpha-drift.

## Question

Pyspec `apply_pending_deposit` Gloas modification (`vendor/consensus-specs/specs/gloas/beacon-chain.md`, TBD line):

```python
def apply_pending_deposit(state: BeaconState, deposit: PendingDeposit) -> None:
    # TODO[drafting]: paste exact Gloas-modified spec body.
    # Captures: 0x03 → state.builders append vs 0x01/0x02 → state.validators append.
```

Open questions:

1. **Credential-prefix dispatch** — is the 0x03 branch a separate function call, an `if` arm, or a polymorphic dispatch?
2. **Builder activation epoch** — same `compute_activation_exit_epoch(current_epoch)` as validators (item #61)? Or different?
3. **Initial builder balance** — from the deposit `amount`, identical to validator init?
4. **Builder pubkey uniqueness** — same dedup check as validators (`state.validators` index lookup → `state.builders` index lookup)?
5. **Signature verification path** — does the 0x03 branch use the same `DepositMessage` signature scheme, or a builder-specific domain?

## Hypotheses

- **H1.** All six clients implement the 0x03 → `state.builders` append branch identically.
- **H2.** All six use `compute_activation_exit_epoch(get_current_epoch(state))` for the builder's `activation_epoch` (cross-cut item #61).
- **H3.** All six dedup builder pubkeys via `state.builders` lookup (separate from validator dedup).
- **H4.** All six preserve the Pectra/Electra deposit semantics for 0x01/0x02 paths (no regression).
- **H5.** All six verify deposit signatures using `DOMAIN_DEPOSIT` regardless of credential prefix.
- **H6** *(forward-fragility)*. Top-up deposits to existing builders — verify the balance-merge branch.
- **H7** *(cross-cut)*. Cross-prefix top-up: deposit with 0x03 credentials but matching an existing validator pubkey (or vice versa). Spec says reject? Verify per-client.

## Findings

> **TBD — drafting.** Each client subsection below is a stub awaiting source review.

### prysm

TBD — drafting.

### lighthouse

TBD — drafting.

### teku

TBD — drafting.

### nimbus

TBD — drafting. PR #8440 history — verify post-fix state.

### lodestar

TBD — drafting.

### grandine

TBD — drafting.

## Cross-reference table

| Client | `apply_pending_deposit` Gloas location | 0x03 branch dispatch | Builder activation epoch (H2) | Cross-prefix top-up (H7) |
|---|---|---|---|---|
| prysm | TBD | TBD | TBD | TBD |
| lighthouse | TBD | TBD | TBD | TBD |
| teku | TBD | TBD | TBD | TBD |
| nimbus | TBD | TBD | TBD | TBD |
| lodestar | TBD | TBD | TBD | TBD |
| grandine | TBD | TBD | TBD | TBD |

## Empirical tests

> **TBD — drafting.** EF Gloas operations fixtures: `vendor/consensus-specs/tests/.../gloas/operations/deposit/` (TBD path).

### Suggested fuzzing vectors

- **T1.1 (canonical 0x03 activation).** New deposit with 0x03 credentials. Verify `state.builders` gets the new entry; `state.validators` does not.
- **T1.2 (canonical 0x01/0x02 activation).** Verify the Pectra path is unchanged.
- **T2.1 (top-up to existing builder).** Verify balance merges, no duplicate registry entry.
- **T2.2 (cross-prefix top-up).** Deposit with 0x03 credentials matching an existing 0x01 validator pubkey. Verify per-client rejection or merge semantics.
- **T2.3 (signature-verification path).** Verify `DOMAIN_DEPOSIT` used for both prefixes (cross-cut item #69).

## Conclusion

> **TBD — drafting.** Source review pending.

## Cross-cuts

### With items #22 + #23 (nimbus closed)

Both were credential-prefix predicate bugs. PR #8440 fixed them. This item verifies the surrounding `apply_pending_deposit` body has no parallel issue.

### With item #4 (`process_pending_deposits` drain)

Item #4 is the outer drain loop; this is the per-deposit body. Cross-cut.

### With item #67 (builder withdrawal flow)

Mirror operation: deposit (in) ↔ withdrawal (out) for 0x03 credentials.

## Adjacent untouched

1. **`process_deposit_request` Gloas modifications** — the EL-side deposit request handler; sibling.
2. **0x02 (compounding) vs 0x03 (builder) credential-prefix matrix** — feature-pairing audit.
