# Shared parsing helpers for per-client runners. Source from each runner.
#
# After `parse_fixture <abs-path-to-fixture-dir>`, the following env vars
# are set:
#   BB_CATEGORY  — one of: sanity_blocks | epoch_processing |
#                  unsupported
#   BB_PRESET    — mainnet | minimal
#   BB_FORK      — electra | deneb | capella | ...
#   BB_HELPER    — for epoch_processing: e.g. effective_balance_updates
#   BB_TEST_NAME — basename of the fixture dir
#
# Returns non-zero on unsupported fixture.

parse_fixture() {
    local abs="$1"
    BB_CATEGORY=
    BB_PRESET=
    BB_FORK=
    BB_HELPER=
    BB_TEST_NAME="$(basename "$abs")"

    case "$abs" in
        */consensus-spec-tests/tests/mainnet/*/sanity/blocks/pyspec_tests/*)
            BB_CATEGORY=sanity_blocks
            BB_PRESET=mainnet
            ;;
        */consensus-spec-tests/tests/minimal/*/sanity/blocks/pyspec_tests/*)
            BB_CATEGORY=sanity_blocks
            BB_PRESET=minimal
            ;;
        */consensus-spec-tests/tests/mainnet/*/epoch_processing/*/pyspec_tests/*)
            BB_CATEGORY=epoch_processing
            BB_PRESET=mainnet
            ;;
        */consensus-spec-tests/tests/minimal/*/epoch_processing/*/pyspec_tests/*)
            BB_CATEGORY=epoch_processing
            BB_PRESET=minimal
            ;;
        */consensus-spec-tests/tests/mainnet/*/operations/*/pyspec_tests/*)
            BB_CATEGORY=operations
            BB_PRESET=mainnet
            ;;
        */consensus-spec-tests/tests/minimal/*/operations/*/pyspec_tests/*)
            BB_CATEGORY=operations
            BB_PRESET=minimal
            ;;
        *)
            BB_CATEGORY=unsupported
            return 1
            ;;
    esac

    BB_FORK="$(echo "$abs" | sed -E "s|.*/${BB_PRESET}/([^/]+)/.*|\\1|")"
    if [[ "$BB_CATEGORY" == "epoch_processing" ]]; then
        BB_HELPER="$(echo "$abs" | sed -E 's|.*/epoch_processing/([^/]+)/.*|\1|')"
    elif [[ "$BB_CATEGORY" == "operations" ]]; then
        BB_HELPER="$(echo "$abs" | sed -E 's|.*/operations/([^/]+)/.*|\1|')"
    fi
}

# Convert snake_case to CamelCase: effective_balance_updates → EffectiveBalanceUpdates
snake_to_camel() {
    echo "$1" | awk -F_ '{for(i=1;i<=NF;i++) printf "%s%s", toupper(substr($i,1,1)), substr($i,2); print ""}'
}

# Capitalize first letter only: electra → Electra
capitalize() {
    local s="$1"
    echo "${s:0:1}" | tr a-z A-Z | tr -d '\n'
    echo "${s:1}"
}
