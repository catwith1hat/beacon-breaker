#!/usr/bin/env bash
# run_fixture.sh — run a fixture against all CL clients and report PASS/FAIL.
#
# Usage:
#   scripts/run_fixture.sh itemN/fixture/
#
# Expects the fixture directory to contain:
#   pre.ssz_snappy
#   block_0.ssz_snappy   (or blocks_*.ssz_snappy)
#   post.ssz_snappy
#   meta.yaml
#
# Each per-client harness lives at tools/runners/<client>.sh and must:
#   - take the fixture directory as $1
#   - exit 0 on state-root match, non-zero on mismatch or run failure
#   - print "OK <state_root>" on success or "FAIL <expected> vs <got>" on
#     mismatch, all on stdout

set -u

FIXTURE="${1:?usage: $0 <fixture-dir>}"

if [[ ! -d "$FIXTURE" ]]; then
    echo "fixture directory not found: $FIXTURE" >&2
    exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNERS_DIR="$ROOT_DIR/tools/runners"

CLIENTS=(prysm lighthouse teku nimbus lodestar grandine)

printf '%-12s %s\n' "client" "result"
printf '%-12s %s\n' "------" "------"

overall_rc=0
for client in "${CLIENTS[@]}"; do
    runner="$RUNNERS_DIR/$client.sh"
    if [[ ! -x "$runner" ]]; then
        printf '%-12s %s\n' "$client:" "SKIP (no runner at $runner)"
        continue
    fi
    output="$("$runner" "$FIXTURE" 2>&1)"
    rc=$?
    if [[ $rc -eq 0 ]]; then
        printf '%-12s %s\n' "$client:" "PASS  $output"
    elif [[ $rc -eq 77 ]]; then
        # POSIX-style "skipped" — runner declined the fixture (e.g.,
        # category not yet wired). Don't fail the overall run.
        printf '%-12s %s\n' "$client:" "SKIP  $output"
    else
        printf '%-12s %s\n' "$client:" "FAIL  $output"
        overall_rc=1
    fi
done

exit "$overall_rc"
