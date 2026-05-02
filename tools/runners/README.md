# Per-client fixture runners

Each runner is a small script that:

1. Takes a fixture directory as `$1`.
2. Builds the per-client invocation that runs the state transition on the
   fixture's `pre.ssz_snappy` + `block_*.ssz_snappy`.
3. Compares the resulting state-root against `post.ssz_snappy`'s root.
4. Exits 0 on match, non-zero on mismatch or run failure.
5. Prints `OK <state_root>` on success or `FAIL <expected> vs <got>` on mismatch.

`scripts/run_fixture.sh` invokes each runner in turn and produces the
per-client PASS/FAIL table.

## Runner-by-runner notes

- **prysm** — use `bazel run //tools/specs-checker:specs-checker` or the
  `process_blocks` test harness in `beacon-chain/state/state-native`.
- **lighthouse** — `lcli transition --pre … --block … --post …`.
- **teku** — there's a Tuweni-based reference runner in
  `acceptance-tests/src/test/java/...` or use `teku transition`.
- **nimbus** — `nimbus_beacon_node ncli_transition` (see
  `ncli/ncli_transition.nim`).
- **lodestar** — there's a CLI runner in `packages/cli/test/utils`. May
  need a small ts-node wrapper.
- **grandine** — similar pattern; see `grandine/eth2-cache` and the
  state-transition crate for the entry point.

Budget 30-60 minutes per client to wire the harness the first time.
Once wired, each runner should just work — keep them dumb.

## Stub runner skeleton

```bash
#!/usr/bin/env bash
set -u
FIXTURE="${1:?usage: $0 <fixture-dir>}"
# … invoke the client; capture its computed state-root …
expected="$(<extract from post.ssz_snappy>)"
got="$(<run client>)"
if [[ "$expected" == "$got" ]]; then
    echo "OK $got"
    exit 0
fi
echo "FAIL $expected vs $got"
exit 1
```
