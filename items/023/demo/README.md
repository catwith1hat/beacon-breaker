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

**Option A — compile against actual nimbus code (confirmed working):**

```bash
cp items/023/demo/test_item_23_repro.nim vendor/nimbus/tests/
cd vendor/nimbus

# nimbus's build needs nimbus-build-system.paths pointing at the inner
# vendor/ dir. If the file is stale or points at the wrong layout
# (e.g. /home/.../nimbus/vendor/ instead of /home/.../vendor/nimbus/vendor/),
# either run `make update` to regenerate it, or sed-fix the prefix:
#
#   sed -i 's|/old/prefix/nimbus/vendor/|/new/prefix/vendor/nimbus/vendor/|g' \
#       nimbus-build-system.paths

NIMBUS_BUILD_SYSTEM=yes nim c \
    --threads:on \
    -d:const_preset=mainnet \
    -d:disable_libbacktrace \
    -o:/tmp/test_item_23_repro \
    tests/test_item_23_repro.nim

/tmp/test_item_23_repro
echo "exit: $?"   # 1 = bug present, 0 = bug fixed
```

`-d:disable_libbacktrace` avoids the C++ `__cxa_demangle` linker dependency
in libbacktrace's demangler (otherwise pull in `-lstdc++`).

First build compiles ~170k lines of nimbus source in ~55 s; subsequent
rebuilds re-link only the test object (a few seconds).

**Option B — wire into `tests/all_tests.nim` and run via the nimbus suite:**

```bash
cp items/023/demo/test_item_23_repro.nim vendor/nimbus/tests/
echo 'import ./test_item_23_repro' >> vendor/nimbus/tests/all_tests.nim
cd vendor/nimbus
make test
```

## Verified

Compiled and ran successfully against `vendor/nimbus` at HEAD
`3802d96291` (unstable, 2026-05-13). Reproduces the divergence exactly
as described in [../README.md](../README.md):

```
spec / prysm / lighthouse / teku / lodestar / grandine  -> 0 gwei
nimbus (beaconstate.nim:1590-1607)                      -> 1000000000 gwei
```

Exit code 1.

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
