---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: [41]
eips: [EIP-7594]
splits: []
# main_md_summary: TBD — drafting PeerDAS custody column selection audit (runtime usage of the cgc field; column-selection algorithm + custody-set computation per node)
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 72: PeerDAS custody column selection — runtime usage of the `cgc` field

## Summary

> **DRAFT — hypotheses-pending.** Item #41 covered the ENR `cgc` field wire encoding (synthetic-state nimbus divergence on uint8-vs-variable-BE). This item is the **runtime semantics** audit: given a peer's advertised `cgc`, which specific column indices does it custody? The per-node custody-column set is derived from `node_id + cgc` via a deterministic algorithm. Cross-client byte-equivalence on which 64-of-128 (or N-of-128) columns a node serves is critical for PeerDAS reconstruction.

## Question

Pyspec `get_custody_columns` (Fulu, `vendor/consensus-specs/specs/fulu/das-core.md`, TBD line):

```python
def get_custody_columns(node_id: NodeID, custody_subnet_count: uint64) -> Sequence[ColumnIndex]:
    # TODO[drafting]: paste exact spec body.
    # Captures: node_id + cgc → deterministic column-set mapping.
```

Open questions:

1. **Algorithm** — `hash(node_id || cgc) → columns`? Or stride-based?
2. **`NUMBER_OF_COLUMNS` constant** — typically 128.
3. **`CUSTODY_REQUIREMENT` / `DATA_COLUMN_SIDECAR_SUBNET_COUNT`** — minimum subnets.
4. **`cgc=0` edge** — does it return empty, or default to CUSTODY_REQUIREMENT?
5. **`cgc=NUMBER_OF_COLUMNS`** — does it return all columns?

## Hypotheses

- **H1.** All six clients implement `get_custody_columns` byte-equivalently.
- **H2.** All six produce the same column-set for any (`node_id`, `cgc`) pair.
- **H3.** Edge cases: `cgc=0`, `cgc=NUMBER_OF_COLUMNS`, `cgc < CUSTODY_REQUIREMENT` — per-client identical.
- **H4** *(cross-cut item #41)*. Wire-encoded `cgc=0` (where nimbus historically encoded as 1-byte `0x00` and others as empty bytes) — does the runtime decode round-trip to the same column-set?
- **H5** *(forward-fragility)*. NodeID format — verify the same 32-byte representation across clients (vs. truncated 16-byte etc).

## Findings

> **TBD — drafting.** Each client subsection below is a stub awaiting source review.

### prysm

TBD — drafting. Entry point: `vendor/prysm/beacon-chain/p2p/custody.go` or `peerdas/`.

### lighthouse

TBD — drafting. Entry point: `vendor/lighthouse/beacon_node/lighthouse_network/src/peer_manager/peerdas.rs`.

### teku

TBD — drafting. Entry point: `vendor/teku/networking/p2p/src/main/java/tech/pegasys/teku/networking/p2p/peerdas/`.

### nimbus

TBD — drafting. Entry point: `vendor/nimbus/beacon_chain/networking/peerdas.nim`.

### lodestar

TBD — drafting. Entry point: `vendor/lodestar/packages/beacon-node/src/network/peerdas/`.

### grandine

TBD — drafting. Entry point: `vendor/grandine/p2p/src/peerdas/`.

## Cross-reference table

| Client | `get_custody_columns` location | Algorithm idiom | `cgc=0` edge | `cgc=NUMBER_OF_COLUMNS` edge |
|---|---|---|---|---|
| prysm | TBD | TBD | TBD | TBD |
| lighthouse | TBD | TBD | TBD | TBD |
| teku | TBD | TBD | TBD | TBD |
| nimbus | TBD | TBD | TBD | TBD |
| lodestar | TBD | TBD | TBD | TBD |
| grandine | TBD | TBD | TBD | TBD |

## Empirical tests

> **TBD — drafting.** EF Fulu DAS fixtures (if any). Devnet PeerDAS cross-client run.

### Suggested fuzzing vectors

- **T1.1 (cross-client byte-equivalence).** Random `node_id` + `cgc` pairs; compute column-set across 6 clients; diff.
- **T2.1 (edge `cgc=0`).** Verify per-client return value matches across all clients.
- **T2.2 (edge `cgc=NUMBER_OF_COLUMNS`).** All-columns case.
- **T2.3 (item #41 round-trip).** Wire-encode `cgc=0` per client; decode per client; pass to `get_custody_columns`; verify identical column-set.

## Conclusion

> **TBD — drafting.** Source review pending.

## Cross-cuts

### With item #41 (nimbus ENR `cgc` encoding)

Item #41 was wire-only divergence on `cgc=0` (nimbus 1-byte vs others empty). This item verifies the runtime semantics post-decode are equivalent — particularly important since the decoded `cgc` drives `get_custody_columns`.

### With item #73 (`get_data_column_sidecars`)

This item is the custody-set selection; item #73 is the sidecar-construction. Cross-cut on the column-index basis.

### With PeerDAS gossip topic subscriptions

Per-client subnet subscription policy depends on the custody column-set. Adjacent audit.

## Adjacent untouched

1. **`NUMBER_OF_COLUMNS` constant cross-client verification**.
2. **`CUSTODY_REQUIREMENT` constant cross-client**.
3. **PeerDAS gossip topic subscription mapping** — column-set → topic-set.
4. **Custody validation on incoming column sidecars** — does the receiver verify the sender's claimed custody matches their NodeID?
