#!/usr/bin/env bash
# driver/get_versions.sh — print the current version tag for each audited
# CL client.
#
# All six CL clients (prysm, lighthouse, teku, nimbus, lodestar, grandine)
# currently produce a sensible string from `git describe --tags --always`,
# either an exact tag match or `<tag>-<ahead>-g<sha>`. Unlike the EL
# clients, none of them require special handling for build-time version
# injection, hotfix-branch tag placement, or out-of-tree version manifests.
# If a quirk appears (e.g. a client starts injecting the version at build
# time and stops tagging HEAD's ancestor), mirror the per-client block
# pattern from evm-breaker/driver/get_versions.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

version_from_describe() {
    git -C "$1" describe --tags --always 2>/dev/null || echo "unknown"
}

for client in prysm lighthouse teku nimbus lodestar grandine; do
    printf "%-12s %s\n" "$client" "$(version_from_describe "$ROOT/vendor/$client")"
done
