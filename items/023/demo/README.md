# Item #23 demo — nimbus `get_pending_balance_to_withdraw` OR-fold

Two reproducers demonstrating the divergence documented in
[../README.md](../README.md):

## 1. `spec_vs_nimbus.py` — pure-Python side-by-side reproducer

Transliterates BOTH the spec algorithm (consensus-specs Electra,
inherited unchanged at Gloas after PR #4788) AND nimbus's actual
algorithm (`vendor/nimbus/beacon_chain/spec/beaconstate.nim:1590-1607`)
into Python, constructs a synthetic Gloas state in which validator
index `V=5` numerically collides with a recent unsettled builder bid
at `builder_index=5`, and queries `get_pending_balance_to_withdraw`
through both.

```
python3 items/023/demo/spec_vs_nimbus.py
```

Exit code 1 = divergence demonstrated as expected (bug present);
exit code 0 = bug appears fixed (test should be inverted).

No dependencies. Self-contained. Suitable for CI regression-guarding
or for reading as a precise specification of what the OR-fold computes.

## 2. `test_item_23_repro.nim` — Nim test against actual nimbus code

Imports the actual `get_pending_balance_to_withdraw` function from
`beacon_chain/spec/beaconstate`, builds the same synthetic Gloas state,
and asserts the divergence. This is the "ground-truth" demonstration —
it exercises nimbus's compiled code, not a transliteration.

### How to run

The file is structured as a drop-in nimbus test using the conventional
`../beacon_chain/spec/...` relative imports. Two paths:

**Option A — drop into nimbus's `tests/` dir and use the nimbus build:**

```bash
cp items/023/demo/test_item_23_repro.nim vendor/nimbus/tests/
cd vendor/nimbus
# nimbus's standard build first generates nimbus-build-system.paths
# pointing at the vendored deps; check whether it already exists and is current:
ls nimbus-build-system.paths

# if it's stale / missing, regenerate via the nimbus build:
make update    # initializes vendored submodules + regenerates paths
make test      # runs the full suite

# then compile + run the reproducer:
nim c -r -d:const_preset=mainnet tests/test_item_23_repro.nim
```

**Option B — wire into `tests/all_tests.nim`:**

```bash
cp items/023/demo/test_item_23_repro.nim vendor/nimbus/tests/
echo 'import ./test_item_23_repro' >> vendor/nimbus/tests/all_tests.nim
cd vendor/nimbus
make test
```

### Expected output

```
========================================================================
Item #23 reproducer: nimbus get_pending_balance_to_withdraw OR-fold
========================================================================

Synthetic Gloas state:
  state.pending_partial_withdrawals  = []  (validator V=5 has no pending)
  state.builder_pending_payments[0]  = BuilderPendingPayment(
      withdrawal.builder_index = 5,
      withdrawal.amount        = 1000000000 gwei (1 ETH)
  )

Query: get_pending_balance_to_withdraw(state, validator_index=5)

  spec / prysm / lighthouse / teku / lodestar / grandine  -> 0 gwei
  nimbus (beaconstate.nim:1590-1607)                      -> 1000000000 gwei

DIVERGENCE: nimbus over-counts by 1000000000 gwei.

Downstream impact at Gloas:
  - process_voluntary_exit (state_transition_block.nim:513):
      spec gate `pending_balance == 0` passes -> exit accepted.
      nimbus gate sees 1000000000 > 0     -> exit REJECTED.
  ...
```

Exit code 1 indicates the bug is still present.

## Mitigation

The fix is two-line: drop the `when type(state).kind >= ConsensusFork.Gloas`
branch from `vendor/nimbus/beacon_chain/spec/beaconstate.nim:1599-1606`
(see item #23 README's "Mainnet reachability" → "Mitigation" section).
The Gloas-NEW separate accessor `get_pending_balance_to_withdraw_for_builder`
at `beaconstate.nim:3085-3097` is already correct and is what builder-side
callers (e.g. the builder-exit branch of `process_voluntary_exit`) should
use.
