#!/usr/bin/env bash
# new_item.sh — scaffold the next itemN/ directory with a README from the
# template in BEACONBREAKER.md §7.
#
# Usage:
#   scripts/new_item.sh "<one-line title>"
#
# Picks N as the next free integer. Creates itemN/README.md prefilled with
# placeholders. Does not create the fixture/ subdirectory until you have one.

set -euo pipefail

TITLE="${1:?usage: $0 \"<one-line title>\"}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Find the highest existing item number.
n=0
shopt -s nullglob
for d in "$ROOT_DIR"/item[0-9]*; do
    base="$(basename "$d")"
    num="${base#item}"
    [[ "$num" =~ ^[0-9]+$ ]] || continue
    if (( num > n )); then n=$num; fi
done
shopt -u nullglob

next=$((n + 1))
dir="$ROOT_DIR/item$next"
mkdir -p "$dir"

today="$(date -u +%Y-%m-%d)"

cat > "$dir/README.md" <<EOF
# Item #$next — $TITLE

**Status:** _<no-divergence-pending-fuzzing | divergence-confirmed | dormant-divergence-on-X | mainnet-impossible>_ — audited $today. **_<Hypothesis disconfirmed / confirmed / partially confirmed>._**

**Builds on:** _items #X (subject), #Y (subject)._

**_<Fork>_-active.** _<One-sentence describe why this matters for consensus root.>_

## Question

_<2-4 paragraphs describing the surface, the spec, the cross-cut, and the
exact predicate / value / encoding under audit. Cite sections of the spec
or relevant EIPs.>_

The hypothesis: *<one-sentence formal hypothesis about what could diverge>.*

**Consensus relevance**: _<one paragraph explaining the bad outcome of a divergence.>_

## Hypotheses

- **H1.** _<Falsifiable claim 1.>_
- **H2.** _<Falsifiable claim 2.>_

## Findings

H1, H2 _<satisfied | unsatisfied>_. **_<No divergence | divergence on Hk>._**

### prysm (\`<package>/<file.go>:<lines>\`)
_<verbatim-or-paraphrased excerpt + ✓/✗ per hypothesis>_

### lighthouse (\`<crate>/<file.rs>:<lines>\`)
_<...>_

### teku (\`<package>/<File.java>:<lines>\`)
_<...>_

### nimbus (\`<package>/<file.nim>:<lines>\`)
_<...>_

### lodestar (\`<package>/<file.ts>:<lines>\`)
_<...>_

### grandine (\`<crate>/<file.rs>:<lines>\`)
_<...>_

## Cross-reference table

| Client | Location | _<key behavior>_ | _<key constant>_ |
|---|---|---|---|
| prysm | ... | ... | ... |
| lighthouse | ... | ... | ... |
| teku | ... | ... | ... |
| nimbus | ... | ... | ... |
| lodestar | ... | ... | ... |
| grandine | ... | ... | ... |

## Cross-cuts

### with #X (_<topic>_)
_<paragraph explaining how this audit composes with item #X>_

## Fixture

\`fixture/\`: _<what the fixture exercises; expected per-client outcomes>._

## Fuzzing vectors

### T1 — Mainline canonical
- **T1.1 (priority — _<name>_).** _<description>_. Expected: _<outcome>_.

### T2 — Adversarial probes
- **T2.1 (priority — _<name>_).** _<description>_.

## Conclusion

_<Status one-line restated.>_ _<2-3 sentences on what was confirmed or
disconfirmed and any code-change recommendation (or "no code changes
warranted").>_

## Adjacent untouched _<fork>_-active consensus paths

1. **_<Path>_** — _<one-line note on what's untouched and why it's worth a
   future item.>_
EOF

echo "scaffolded $dir/README.md"
echo "next: fill in the template; add fixture/ when you have one; update WORKLOG.md"
