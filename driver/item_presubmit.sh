#!/usr/bin/env bash
# Presubmit: check that each itemN[suffix]/README.md matches the structure
# required by driver/recheck_and_reformat.item-prompt.
#
# Required structure (see recheck_and_reformat.item-prompt for the source of
# truth). Front matter goes at the top (Jekyll-style) so GitHub renders it
# as a metadata table; placing it after the H1 makes the closing `---` a
# setext H2 underline that swallows the fields.
#
#   line 1                : ---
#   front-matter (any order, between the two ---):
#       status:    drafting | hypotheses-formed | source-code-reviewed | fuzzed | final
#       impact:    unknown | none | contained | synthetic-state | custom-chain
#                  | mainnet-proposer | mainnet-everyone | mainnet-glamsterdam
#         (`contained` = divergence at EVM level but caught by an upstream
#          layer — newPayload validation, RLP decode, tx-pool admission;
#          `custom-chain` also covers mainnet bugs whose trigger threshold
#          is unreachable given realistic capital — see #45b.
#          `mainnet-glamsterdam` = mainnet-reachable on canonical traffic
#          but only once the Glamsterdam fork activates — used for
#          forward-looking BAL / EIP-8037 / etc. audit items where the
#          spec is fixed and the divergence will materialise on day 1
#          of activation.)
#       last_update: YYYY-MM-DD
#       builds_on:   [<item-number>, ...]   (use [] if none)
#       eips:        [EIP-<n>, ...]          (use [] if none)
#       splits:      [<client>, ...]         required iff impact != none;
#                                            forbidden when impact == none.
#                                            Entries from {prysm, lighthouse,
#                                            teku, nimbus, lodestar, grandine}.
#       # main_md_summary: <text>            YAML comment line, required iff
#                                            impact != none; one-line summary
#                                            in the shape of the main
#                                            README.md's Findings-table cell.
#       remediated:  true                    optional; when present must be
#                                            `true`. Marks an item whose
#                                            divergence was fixed upstream.
#       prysm_version:
#       lighthouse_version:
#       teku_version:
#       nimbus_version:
#       lodestar_version:
#       grandine_version:
#   then ---
#   then a blank line, then # <designation>: <description>
#   then the following H2 headings, in order:
#       ## Summary
#       ## Question
#       ## Hypotheses
#       ## Findings
#       ## Cross-reference table
#       ## Empirical tests
#       ## Mainnet reachability   (only when impact is mainnet-*)
#       ## Conclusion
#   under ## Findings (before the next ##), in order:
#       ### prysm
#       ### lighthouse
#       ### teku
#       ### nimbus
#       ### lodestar
#       ### grandine

set -euo pipefail

prog=$(basename "$0")
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
project_root=$(cd "$script_dir/.." && pwd)

usage() {
    cat <<EOF
Usage: $prog [item-dir ...]

Validate that each items/NNN[suffix]/README.md conforms to the
structure prescribed by driver/recheck_and_reformat.item-prompt.

With no arguments, every items/NNN[suffix] directory directly under
$project_root/items/ is checked.

Prints one violation per line to stderr. Exits 0 if all READMEs conform,
1 otherwise.
EOF
}

if [[ ${1-} == "-h" || ${1-} == "--help" ]]; then
    usage; exit 0
fi

declare -a items=()
if [[ $# -gt 0 ]]; then
    items=("$@")
else
    while IFS= read -r d; do
        items+=("$d")
    done < <(find "$project_root/items" -mindepth 1 -maxdepth 1 -type d \
                  -regextype posix-extended -regex '.*/items/[0-9]+[a-z]*$' | sort)
fi

if (( ${#items[@]} == 0 )); then
    echo "$prog: no item directories to check" >&2
    exit 1
fi

required_meta=(
    "status:"
    "impact:"
    "last_update:"
    "builds_on:"
    "eips:"
    "prysm_version:"
    "lighthouse_version:"
    "teku_version:"
    "nimbus_version:"
    "lodestar_version:"
    "grandine_version:"
)

declare -A enum_values=(
    ["status:"]="drafting hypotheses-formed source-code-reviewed fuzzed final"
    ["impact:"]="unknown none contained synthetic-state custom-chain mainnet-proposer mainnet-everyone mainnet-glamsterdam"
)

# Per-field value-format regexes (extended). Empty → no format check beyond
# any enum_values check.
declare -A value_regex=(
    ["last_update:"]='^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    ["builds_on:"]='^\[([0-9]+[a-z]*([[:space:]]*,[[:space:]]*[0-9]+[a-z]*)*)?\]$'
    ["eips:"]='^\[(EIP-[0-9]+([[:space:]]*,[[:space:]]*EIP-[0-9]+)*)?\]$'
    ["splits:"]='^\[((prysm|lighthouse|teku|nimbus|lodestar|grandine)([[:space:]]*,[[:space:]]*(prysm|lighthouse|teku|nimbus|lodestar|grandine))*)?\]$'
)

# Standard H2 sequence (excluding the conditional ## Mainnet reachability).
required_h2_base=(
    "## Summary"
    "## Question"
    "## Hypotheses"
    "## Findings"
    "## Cross-reference table"
    "## Empirical tests"
    "## Conclusion"
)

# Insertion point of ## Mainnet reachability, when present (between
# ## Empirical tests and ## Conclusion).
reachability_heading="## Mainnet reachability"
mainnet_impacts="mainnet-proposer mainnet-everyone mainnet-glamsterdam"

required_h3=(
    "### prysm"
    "### lighthouse"
    "### teku"
    "### nimbus"
    "### lodestar"
    "### grandine"
)

# Find the line index (0-based) of the first array element matching `target`
# exactly, starting at offset `from`. Echos -1 if not found.
find_line() {
    local target=$1 from=$2
    shift 2
    local -a arr=("$@")
    local i
    for ((i=from; i<${#arr[@]}; i++)); do
        if [[ "${arr[$i]}" == "$target" ]]; then
            echo "$i"; return
        fi
    done
    echo "-1"
}

check_item() {
    local item_dir=$1
    local readme="$item_dir/README.md"
    local item_name; item_name=$(basename "$item_dir")
    local label="$item_name/README.md"
    local rc=0

    if [[ ! -f "$readme" ]]; then
        echo "$label: missing" >&2
        return 1
    fi

    local -a lines
    mapfile -t lines < "$readme"
    local n=${#lines[@]}
    # item_name is the basename of the items/<NNN>[suffix] directory
    # (e.g. "045b"). Strip leading zeros to get the displayed designation.
    local designation
    if [[ "$item_name" =~ ^0*([0-9]+)([a-z]*)$ ]]; then
        designation="${BASH_REMATCH[1]}${BASH_REMATCH[2]}"
    else
        designation="$item_name"
    fi

    # Front matter — line 1 opens with --- ; find closing ---.
    if [[ "${lines[0]-}" != "---" ]]; then
        echo "$label: line 1 must be '---' to open front matter (got: '${lines[0]-}')" >&2
        rc=1
    fi
    local fm_close
    fm_close=$(find_line "---" 1 "${lines[@]}")
    if (( fm_close < 0 )); then
        echo "$label: front-matter close '---' not found" >&2
        rc=1
    fi

    # H1 — first non-blank line after the closing front-matter '---' must be
    # "# <designation>: <description>".
    local h1_idx=-1 i
    if (( fm_close >= 0 )); then
        for ((i=fm_close+1; i<n; i++)); do
            if [[ -n "${lines[$i]// /}" ]]; then
                h1_idx=$i; break
            fi
        done
        if (( h1_idx < 0 )); then
            echo "$label: no H1 found after front matter" >&2
            rc=1
        elif ! [[ "${lines[$h1_idx]}" =~ ^"# ${designation}: ".+ ]]; then
            echo "$label: H1 must be '# ${designation}: <description>' (got: '${lines[$h1_idx]}')" >&2
            rc=1
        fi
    fi

    # Track parsed impact value so we can decide whether the
    # ## Mainnet reachability section is required.
    local impact_value=""

    if (( fm_close >= 0 )); then
        local field
        for field in "${required_meta[@]}"; do
            local found_idx=-1 i
            for ((i=1; i<fm_close; i++)); do
                if [[ "${lines[$i]}" == ${field}* ]]; then
                    found_idx=$i; break
                fi
            done
            if (( found_idx < 0 )); then
                echo "$label: front matter missing field '$field'" >&2; rc=1
                continue
            fi
            # Extract value (text after the colon, leading whitespace stripped).
            local value=""
            if [[ "${lines[$found_idx]}" =~ ^[^:]+:[[:space:]]*(.*)$ ]]; then
                value="${BASH_REMATCH[1]}"
                # Trim trailing whitespace.
                value="${value%"${value##*[![:space:]]}"}"
            fi
            if [[ "$field" == "impact:" ]]; then
                impact_value="$value"
            fi
            # Enum check.
            local allowed="${enum_values[$field]-}"
            if [[ -n "$allowed" ]]; then
                local match=0 a
                for a in $allowed; do
                    if [[ "$value" == "$a" ]]; then match=1; break; fi
                done
                if (( ! match )); then
                    echo "$label: ${field%:} value '$value' not in {${allowed// /, }}" >&2
                    rc=1
                fi
            fi
            # Format-regex check.
            local re="${value_regex[$field]-}"
            if [[ -n "$re" ]]; then
                if ! [[ "$value" =~ $re ]]; then
                    echo "$label: ${field%:} value '$value' does not match expected format" >&2
                    rc=1
                fi
            fi
        done
    fi

    # `splits:` is conditional: required when impact != none, forbidden
    # when impact == none. Look it up directly in the front matter rather
    # than via required_meta.
    local splits_present=0 splits_value=""
    if (( fm_close >= 0 )); then
        local i
        for ((i=1; i<fm_close; i++)); do
            if [[ "${lines[$i]}" == "splits:"* ]]; then
                splits_present=1
                if [[ "${lines[$i]}" =~ ^[^:]+:[[:space:]]*(.*)$ ]]; then
                    splits_value="${BASH_REMATCH[1]}"
                    splits_value="${splits_value%"${splits_value##*[![:space:]]}"}"
                fi
                break
            fi
        done
    fi
    if [[ "$impact_value" == "none" ]]; then
        if (( splits_present )); then
            echo "$label: 'splits:' present but impact=none (only allowed when impact != none)" >&2
            rc=1
        fi
    elif [[ -n "$impact_value" ]]; then
        if (( ! splits_present )); then
            echo "$label: 'splits:' field required when impact='$impact_value'" >&2
            rc=1
        else
            local splits_re="${value_regex["splits:"]}"
            if ! [[ "$splits_value" =~ $splits_re ]]; then
                echo "$label: splits value '$splits_value' does not match expected format (e.g. [prysm, grandine])" >&2
                rc=1
            fi
        fi
    fi

    # `# main_md_summary:` — YAML-comment line in the front matter.
    # Required when impact != none, forbidden when impact == none. Mirrors
    # the splits: rule.
    local mms_present=0 mms_value=""
    if (( fm_close >= 0 )); then
        local i
        for ((i=1; i<fm_close; i++)); do
            if [[ "${lines[$i]}" =~ ^"# main_md_summary:"[[:space:]]*(.+)$ ]]; then
                mms_present=1
                mms_value="${BASH_REMATCH[1]}"
                mms_value="${mms_value%"${mms_value##*[![:space:]]}"}"
                break
            fi
        done
    fi
    if [[ "$impact_value" == "none" ]]; then
        if (( mms_present )); then
            echo "$label: '# main_md_summary:' present but impact=none (only allowed when impact != none)" >&2
            rc=1
        fi
    elif [[ -n "$impact_value" ]]; then
        if (( ! mms_present )); then
            echo "$label: '# main_md_summary: <text>' comment line required when impact='$impact_value'" >&2
            rc=1
        elif [[ -z "$mms_value" ]]; then
            echo "$label: '# main_md_summary:' must have non-empty text" >&2
            rc=1
        fi
    fi

    # `remediated:` — optional flag. When present, value must be `true`.
    if (( fm_close >= 0 )); then
        local i
        for ((i=1; i<fm_close; i++)); do
            if [[ "${lines[$i]}" == "remediated:"* ]]; then
                local rem_value=""
                if [[ "${lines[$i]}" =~ ^[^:]+:[[:space:]]*(.*)$ ]]; then
                    rem_value="${BASH_REMATCH[1]}"
                    rem_value="${rem_value%"${rem_value##*[![:space:]]}"}"
                fi
                if [[ "$rem_value" != "true" ]]; then
                    echo "$label: 'remediated:' must be 'true' if present (got: '$rem_value')" >&2
                    rc=1
                fi
                break
            fi
        done
    fi

    # Build the required H2 sequence based on impact.
    local -a required_h2
    local needs_reachability=0 a
    for a in $mainnet_impacts; do
        if [[ "$impact_value" == "$a" ]]; then needs_reachability=1; break; fi
    done
    if (( needs_reachability )); then
        required_h2=(
            "## Summary"
            "## Question"
            "## Hypotheses"
            "## Findings"
            "## Cross-reference table"
            "## Empirical tests"
            "$reachability_heading"
            "## Conclusion"
        )
    else
        required_h2=("${required_h2_base[@]}")
    fi

    # H2 sections — must appear in the prescribed order.
    local search_from=$(( fm_close >= 0 ? fm_close + 1 : 0 ))
    local h
    for h in "${required_h2[@]}"; do
        local pos; pos=$(find_line "$h" "$search_from" "${lines[@]}")
        if (( pos < 0 )); then
            echo "$label: missing or out-of-order section '$h'" >&2
            rc=1
        else
            search_from=$(( pos + 1 ))
        fi
    done

    # If reachability is NOT required, it must NOT appear at all.
    if (( ! needs_reachability )); then
        local stray; stray=$(find_line "$reachability_heading" 0 "${lines[@]}")
        if (( stray >= 0 )); then
            echo "$label: '$reachability_heading' present but impact='$impact_value' (only allowed for mainnet-* impacts)" >&2
            rc=1
        fi
    fi

    # H3 subsections under ## Findings, before the next ## heading, in order.
    local findings_start
    findings_start=$(find_line "## Findings" 0 "${lines[@]}")
    if (( findings_start >= 0 )); then
        local findings_end=$n i
        for ((i=findings_start+1; i<n; i++)); do
            if [[ "${lines[$i]}" =~ ^##[[:space:]] ]]; then
                findings_end=$i; break
            fi
        done
        local h3_from=$(( findings_start + 1 ))
        for h in "${required_h3[@]}"; do
            local pos=-1 j
            for ((j=h3_from; j<findings_end; j++)); do
                if [[ "${lines[$j]}" == "$h" ]]; then
                    pos=$j; break
                fi
            done
            if (( pos < 0 )); then
                echo "$label: ## Findings missing or out-of-order subsection '$h'" >&2
                rc=1
            else
                h3_from=$(( pos + 1 ))
            fi
        done
    fi

    return $rc
}

failed=0
for item in "${items[@]}"; do
    if ! check_item "$item"; then
        failed=$(( failed + 1 ))
    fi
done

if (( failed > 0 )); then
    echo "$prog: $failed of ${#items[@]} item(s) failed presubmit checks" >&2
    exit 1
fi

echo "$prog: all ${#items[@]} item(s) conform"
exit 0
