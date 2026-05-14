# Gloas fork-choice simulator harness

`forkchoice_simulator.py` is a semantic simulator that demonstrates each
fork-choice divergence documented in items #77, #80, #81, #82, #83, #84.
It is **not** a full fork-choice replay engine — each spec function is
implemented inline alongside each divergent client variant, and the
scenarios construct minimal fork-choice store fragments that exercise
the divergent semantics.

The purpose: convert source-level divergence claims into reproducible
executable evidence.

## Running

```bash
python3 forkchoice_simulator.py
```

No dependencies beyond Python 3.10+ (dataclasses, typing).

## Coverage matrix

| Scenario | Item | Spec function | Divergent clients |
|---|---|---|---|
| #77 | `should_extend_payload` drops `is_payload_data_available` | `is_payload_timely AND is_payload_data_available` | lodestar |
| #80 Case A | Same-slot EMPTY vote routing | `is_supporting_vote` (Branch A) | lodestar, grandine |
| #80 Case B | Same-slot FULL vote routing (gated by validation, but shown for routing semantic) | `is_supporting_vote` (Branch A) | lodestar, prysm |
| #81 | Previous-slot `get_weight` zeroing | `get_weight` returns 0 for FULL/EMPTY when `block.slot + 1 == current_slot` | prysm, grandine |
| #82 | Proposer-boost equivocation suppression | `should_apply_proposer_boost` checks PTC-timely equivocations | lodestar, teku |
| #83 | `is_head_weak` equivocating-committee monotonicity | `is_head_weak` adds equivocating-validator weight from head-slot committees | prysm, lodestar |
| #84-A | `is_parent_strong` payload-status-aware | `is_parent_strong` uses parent's specific variant weight | prysm, grandine (unimplemented) |
| #84-B | Canonical-proposer check in `update_proposer_boost_root` | `block.proposer_index == get_beacon_proposer_index(head_state)` gate | prysm, lodestar |
| #84-C | `is_head_late` | `not block_timeliness[head_root][ATTESTATION_TIMELINESS_INDEX]` | grandine (unimplemented) |

## Run output (2026-05-14)

Every scenario where divergence is documented in items #77, #80, #81, #82,
#83, #84 produces a `✗ DIVERGE` line in the harness output. Scenarios
where the divergent client happens to match spec for a different reason
are flagged with explanatory text.

Highlights:

- **#77**: lodestar's `should_extend_payload` returns True where spec returns
  False (PTC timely=300 votes > 256 threshold, but data-available=10 votes ≪
  256, and proposer-boost set to an adversarial child whose parent_payload
  is EMPTY).
- **#80**: lodestar and grandine route same-slot EMPTY votes to the EMPTY
  bucket (32 ETH credited) where spec routes only to PENDING.
- **#81**: prysm and grandine return raw 3.2 ETH × 100 weight on FULL(B) at
  previous-slot where spec returns 0.
- **#82**: lodestar and teku return True (apply boost) where spec returns
  False (suppress: early equivocation exists). Prysm and grandine "match"
  spec for the wrong reason — prysm rejects because parent is weak;
  grandine rejects because ANY equivocation exists (not just PTC-timely).
- **#83**: prysm and lodestar return True (head weak) where spec returns
  False because the equivocating-committee term pushes head_weight above
  the reorg threshold.
- **#84-A**: prysm uses combined consensus-Node weight (sum of variants)
  where spec uses the specific parent variant matching head's chain. With
  parent.FULL.weight = 32 ETH and parent.EMPTY.weight = 800 ETH and
  threshold = 160 ETH, spec says NOT strong; prysm says strong. Grandine
  has no `is_parent_strong` implementation at all.
- **#84-B**: prysm and lodestar would apply proposer-boost to a block whose
  `proposer_index` doesn't match the canonical-chain proposer at the
  current slot.
- **#84-C**: grandine has no `is_head_late` equivalent anywhere in
  `fork_choice_store/` or `fork_choice_control/`.

## Limitations

The harness is **semantic, not behavioural**:

- It does not implement full fork-choice (no `get_head` walk, no
  `find_head`, no proto-array maintenance).
- It does not replay attestation aggregation, gossip, or block import.
- It does not exercise cross-fork transition.
- It treats each client's divergent function as a stand-alone Python
  function (re-implemented per the source code) rather than calling into
  the client's actual binaries.

Each scenario verifies the spec-vs-client divergence at the level of a
single predicate or score computation, with the surrounding store state
hand-constructed to exhibit the divergence.

## What this proves (and what it doesn't)

**Proves**: each documented divergence is reachable from a constructed
store state. The spec semantics and the client semantics differ when
called on the same input.

**Does not prove**: end-to-end fork-choice outcomes differ across clients
in real network traffic. That would require either (a) running the actual
client binaries in a coordinated harness, or (b) building a complete
fork-choice replay engine.

Each item's `## Empirical tests` section already lists scenario suggestions
for in-tree client tests (e.g., #67's `lodestar_intree_test.ts`) — those
would be the next step beyond this simulator.

## Extending

To add a new scenario:

1. Implement the spec function (if not already present) per
   `vendor/consensus-specs/specs/gloas/fork-choice.md`.
2. Implement each divergent client variant inline with a docstring citing
   the source line.
3. Write a `scenario_NN_<name>()` function that constructs the minimal
   store fragment and calls both spec and client variants.
4. Add the scenario call to `main()`.

The pattern is intentionally simple — one Python file, no external
dependencies, one function per (client, semantic). New scenarios should
follow the same shape.
