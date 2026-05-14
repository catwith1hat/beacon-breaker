---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: [58, 70]
eips: [EIP-7732]
splits: []
# main_md_summary: TBD — drafting `engine_getPayloadV5` builder-vs-self-build dispatch audit (Gloas ePBS impact on getPayload; CL chooses local-build (BUILDER_INDEX_SELF_BUILD) vs external-builder)
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 71: `engine_getPayloadV5` builder-vs-self-build dispatch

## Summary

> **DRAFT — hypotheses-pending.** Gloas ePBS changes block-proposal flow: instead of "EL builds payload → CL signs block → CL gossips", the CL chooses between:
> 1. **Self-build**: CL signs `BUILDER_INDEX_SELF_BUILD` as the chosen builder, calls `engine_getPayloadV5` for an EL-built payload, bundles it as an envelope.
> 2. **External builder**: CL accepts a `SignedExecutionPayloadBid` (item #58) from an external builder, signs a beacon block referencing it, waits for the envelope from the builder.
>
> The dispatch decision is per-slot, per-proposer-preference, and per-policy (mev-boost / commit-boost / etc.). This item audits the CL-side branching logic for `engine_getPayloadV5` invocation: when does each CL invoke the EL vs an external builder?

## Question

Gloas builder-vs-self-build decision (per the consensus-specs + EIP-7732 spec corpus, TBD):

```python
# Conceptual CL-side logic at block proposal time:
def propose_block(state, validator_index, slot):
    preferences = get_proposer_preferences(state, validator_index)
    if preferences.use_external_builder and has_active_bid(slot):
        # Use external builder
        bid = receive_external_bid(slot)
        block.builder_index = bid.builder_index
        block.execution_payload_root = bid.execution_payload_root
        # Builder reveals envelope; CL doesn't call engine_getPayloadV5 here
    else:
        # Self-build
        block.builder_index = BUILDER_INDEX_SELF_BUILD
        envelope = engine_getPayloadV5(...)  # local EL build
        block.execution_payload_root = hash_tree_root(envelope.payload)
```

Open questions:

1. **`BUILDER_INDEX_SELF_BUILD` constant value** — TBD spec value (`0` or `MAX_BUILDERS` or sentinel).
2. **Preference-broadcast lifecycle** — when is `ProposerPreferences` broadcast? How does the CL receive it?
3. **External-builder integration** — mev-boost / commit-boost / direct relay? Per-client policy.
4. **Self-build fallback** — what if external builder fails to reveal envelope by attestation deadline? Per-client recovery policy.
5. **`engine_getPayloadV5` request schema** — same as V4 with additional Gloas fields? Or restructured?

## Hypotheses

- **H1.** All six clients implement `engine_getPayloadV5` dispatch identically for self-build.
- **H2.** All six handle the `BUILDER_INDEX_SELF_BUILD` sentinel consistently.
- **H3.** All six implement the external-builder integration via mev-boost (or a documented sibling).
- **H4.** All six implement the self-build fallback (timeout-on-builder → switch to local-build).
- **H5** *(forward-fragility)*. Race conditions at the bid/envelope boundary — per-client locking.
- **H6** *(operational)*. Per-client mev-boost API compatibility — verify all 6 work with current mev-boost release.

## Findings

> **TBD — drafting.** Each client subsection below is a stub awaiting source review.

### prysm

TBD — drafting.

### lighthouse

TBD — drafting.

### teku

TBD — drafting.

### nimbus

TBD — drafting.

### lodestar

TBD — drafting.

### grandine

TBD — drafting.

## Cross-reference table

| Client | `engine_getPayloadV5` dispatch | `BUILDER_INDEX_SELF_BUILD` constant | External-builder integration | Self-build fallback (H4) |
|---|---|---|---|---|
| prysm | TBD | TBD | TBD | TBD |
| lighthouse | TBD | TBD | TBD | TBD |
| teku | TBD | TBD | TBD | TBD |
| nimbus | TBD | TBD | TBD | TBD |
| lodestar | TBD | TBD | TBD | TBD |
| grandine | TBD | TBD | TBD | TBD |

## Empirical tests

> **TBD — drafting.** Devnet block-proposal cross-client run with mixed builder configurations.

### Suggested fuzzing vectors

- **T1.1 (self-build canonical).** Validator with no external-builder preference; verify `engine_getPayloadV5` called locally.
- **T1.2 (external-builder canonical).** Validator with external-builder preference + active bid; verify NO local `engine_getPayloadV5` call.
- **T2.1 (builder-timeout fallback).** External builder configured but unresponsive; verify per-client fallback to self-build.
- **T2.2 (mid-slot preference change).** Preference toggled mid-slot; verify per-client lock semantics.
- **T2.3 (cross-client interop).** CL A proposes via builder; CL B imports the block. Verify acceptance.

## Conclusion

> **TBD — drafting.** Source review pending. Operationally significant for the Gloas mev-boost ecosystem.

## Cross-cuts

### With item #58 (`process_execution_payload_bid`)

Item #58 is the bid-consumption side. This item is the bid-generation / external-builder integration side.

### With item #70 (`engine_newPayloadV5`)

Sibling Engine API method.

### With `ProposerPreferences` broadcast

Cross-cut: per-validator builder preferences and how they're communicated.

## Adjacent untouched

1. **mev-boost / commit-boost integration cross-client** — sibling audit.
2. **Builder API specification** — `builder-specs` GitHub repo; per-client compliance.
3. **Bid auction model** — multi-bid selection (highest bid wins?). Per-client.
