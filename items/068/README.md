---
status: drafting
impact: unknown
last_update: 2026-05-14
builds_on: [27, 60]
eips: [EIP-7732]
splits: []
# main_md_summary: TBD — drafting `compute_balance_weighted_selection` triple-call cross-cut audit (used by `compute_proposer_indices`, `compute_ptc`, sync-committee selection; divergence cascades to all 3 consumers)
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 68: `compute_balance_weighted_selection` triple-call cross-cut audit

## Summary

> **DRAFT — hypotheses-pending.** Gloas-introduced primitive used by three distinct consumers:
> 1. `compute_proposer_indices` (Pectra carry-forward) — block proposer selection per slot.
> 2. `compute_ptc` (Gloas-new, item #60) — PTC member selection per slot.
> 3. Sync-committee selection (item #27) — sync committee per period.
>
> A divergence in this primitive cascades to all three consumers. Item #60's prysm review confirmed prysm conforms; the other 5 clients have not been per-line cross-checked on this specific helper.

## Question

Pyspec `compute_balance_weighted_selection` (Gloas, `vendor/consensus-specs/specs/gloas/beacon-chain.md`):

```python
def compute_balance_weighted_selection(
    state: BeaconState,
    indices: Sequence[ValidatorIndex],
    seed: Bytes32,
    size: uint64,
    shuffle_indices: bool,
) -> Sequence[ValidatorIndex]:
    MAX_RANDOM_VALUE = 2**16 - 1
    total = uint64(len(indices))
    assert total > 0
    effective_balances = [state.validators[index].effective_balance for index in indices]
    selected: List[ValidatorIndex] = []
    i = uint64(0)
    while len(selected) < size:
        offset = i % 16 * 2
        if offset == 0:
            random_bytes = hash(seed + uint_to_bytes(i // 16))
        next_index = i % total
        if shuffle_indices:
            next_index = compute_shuffled_index(next_index, total, seed)
        weight = effective_balances[next_index] * MAX_RANDOM_VALUE
        random_value = bytes_to_uint64(random_bytes[offset : offset + 2])
        threshold = MAX_EFFECTIVE_BALANCE_ELECTRA * random_value
        if weight >= threshold:
            selected.append(indices[next_index])
        i += 1
    return selected
```

Subtle implementation hazards:

1. **`i // 16` block-cache** — `random_bytes` only re-hashes when `offset == 0` (every 16 iterations). Per-client caching equivalence?
2. **`bytes_to_uint64(random_bytes[offset : offset + 2])` little/big-endian** — only 2 bytes read; verify endianness.
3. **`MAX_EFFECTIVE_BALANCE_ELECTRA * random_value` overflow** — `random_value ∈ [0, 65535]`, `MAX_EFFECTIVE_BALANCE_ELECTRA = 2048 ETH = 2048 * 10^9 Gwei`. Product fits in u128 / Gwei*u16. Per-client multiplier-width handling.
4. **`shuffle_indices=False` semantics** — used by `compute_ptc` (item #60); wraps `i % total`. Per-client wraparound vs explicit modulo.
5. **`shuffle_indices=True` semantics** — used by `compute_proposer_indices` and sync-committee; calls `compute_shuffled_index`. Per-client agreement.

## Hypotheses

- **H1.** All six clients implement `compute_balance_weighted_selection` byte-equivalently for any input.
- **H2.** All six cache `random_bytes` over 16-iteration blocks identically.
- **H3.** All six read 2 bytes at `offset` via little-endian `bytes_to_uint64`.
- **H4.** All six handle the multiplier-width safely (no overflow at `MAX_EFFECTIVE_BALANCE_ELECTRA * 65535`).
- **H5.** All six handle the `shuffle_indices=False` wraparound identically.
- **H6.** All six handle the `shuffle_indices=True` shuffled-index lookup identically (cross-cut with `compute_shuffled_index`).
- **H7** *(forward-fragility)*. Empty-indices input (`total == 0`) — spec asserts; per-client error handling.

## Findings

> **TBD — drafting.** Each client subsection below is a stub awaiting source review.

### prysm

TBD — drafting. Partial review in item #60: `selectByBalanceFill` at `payload_attestation.go:228` matches spec for `shuffle_indices=False`. Verify `shuffle_indices=True` path and proposer-indices usage.

### lighthouse

TBD — drafting. Entry point: `BeaconState::compute_balance_weighted_selection` at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs` (referenced by item #60's `compute_ptc_with_cache`).

### teku

TBD — drafting. Entry point: `vendor/teku/ethereum/spec/.../gloas/helpers/MiscHelpersGloas.java computeBalanceWeightedSelection`.

### nimbus

TBD — drafting. Entry point: `vendor/nimbus/beacon_chain/spec/beaconstate.nim compute_balance_weighted_selection`.

### lodestar

TBD — drafting.

### grandine

TBD — drafting. Entry point: `vendor/grandine/helper_functions/src/misc.rs compute_balance_weighted_selection`.

## Cross-reference table

| Client | `compute_balance_weighted_selection` location | Cache block-size (H2) | Endian (H3) | Overflow guard (H4) | `shuffle_indices=False` impl (H5) |
|---|---|---|---|---|---|
| prysm | `payload_attestation.go:228` | TBD | TBD | TBD | linear iter + outer refetch loop |
| lighthouse | TBD | TBD | TBD | TBD | TBD |
| teku | TBD | TBD | TBD | TBD | TBD |
| nimbus | TBD | TBD | TBD | TBD | TBD |
| lodestar | TBD | TBD | TBD | TBD | TBD |
| grandine | TBD | TBD | TBD | TBD | TBD |

## Empirical tests

> **TBD — drafting.** Implicit coverage via every Pectra+ block-processing fixture (proposer selection), every Gloas fixture (PTC), and every Altair+ sync-committee fixture. All pass cross-client per the corpus.

### Suggested fuzzing vectors

- **T1.1 (cross-client byte-equivalence).** Random `indices` + `seed` + `size`; compute under all 6 clients with both `shuffle_indices=True` and `False`. Diff outputs byte-for-byte.
- **T2.1 (boundary `total = 1`).** Single-candidate selection. Verify the wraparound semantics.
- **T2.2 (high-weight-only).** All candidates at `MAX_EFFECTIVE_BALANCE_ELECTRA`; `random_value` must hit `MAX_RANDOM_VALUE` for selection (deterministic given seed).
- **T2.3 (zero-effective-balance edge).** Candidates with `effective_balance = 0`; verify never selected.
- **T2.4 (16-iteration block-cache).** Spot-check `random_bytes` recomputation at `i ∈ {16, 32, 48, ...}`.

## Conclusion

> **TBD — drafting.** Source review pending. Expected outcome: implementation idioms differ (iteration style, cache-block boundary handling) but byte-equivalent on every reachable input. Worth nailing down because divergence cascades to 3 consumers.

## Cross-cuts

### With item #60 (`compute_ptc`)

Item #60 verified prysm's `shuffle_indices=False` path; this item covers the other 5 clients.

### With item #27 (sync-committee selection)

Sync-committee uses `shuffle_indices=True` + period-keyed seed. Cross-cut.

### With `compute_proposer_indices`

Pectra carry-forward; uses `shuffle_indices=True`.

### With `compute_shuffled_index`

Dependency on the per-iteration shuffle. Sibling primitive; worth verifying cross-client (probably stable since Phase0).

## Adjacent untouched

1. **`compute_shuffled_index` cross-client byte-equivalence** — sibling primitive.
2. **`MAX_EFFECTIVE_BALANCE_ELECTRA` constant** — verify `2048 ETH` value across all 6 clients (cross-cut item #69 spirit).
3. **`bytes_to_uint64` endianness regression test** — if any client wraps `binary.BigEndian` instead of `LittleEndian` for the 2-byte read, selection diverges entirely.
