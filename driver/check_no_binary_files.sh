#!/usr/bin/env bash
# Reject binary files in the repository.
#
# Usage:
#   check_no_binary_files.sh --staged         # check files in `git diff --cached`
#   check_no_binary_files.sh --tracked        # check all `git ls-files`
#   check_no_binary_files.sh <path> [<path>…]  # check explicit paths
#
# Detection: `file --mime-encoding -b` returns `binary` for non-text files.
# Submodule entries (gitlinks) and symlinks are skipped — they have no file
# bytes the policy applies to. Missing paths are also skipped (a deletion
# can't introduce a binary). Exits 0 if every checked path is text, 1 if
# any binary was found.

set -euo pipefail

prog=$(basename "$0")

usage() {
    cat <<EOF
Usage: $prog --staged
       $prog --tracked
       $prog <path> [<path>…]

Reports any binary file among the selected paths. Prints one violation per
line to stderr. Exits 0 if all paths are text, 1 otherwise.
EOF
}

if [[ $# -eq 0 || ${1-} == "-h" || ${1-} == "--help" ]]; then
    usage; exit 2
fi

declare -a paths=()
case "${1-}" in
    --staged)
        shift
        while IFS= read -r p; do
            [[ -n "$p" ]] && paths+=("$p")
        done < <(git diff --cached --name-only --diff-filter=ACMR)
        ;;
    --tracked)
        shift
        while IFS= read -r p; do
            [[ -n "$p" ]] && paths+=("$p")
        done < <(git ls-files)
        ;;
    *)
        paths=("$@")
        ;;
esac

if (( ${#paths[@]} == 0 )); then
    exit 0
fi

failed=0
for p in "${paths[@]}"; do
    # Skip anything that isn't a regular file (submodule gitlinks, symlinks,
    # deleted entries). The pre-commit caller already restricts to ACMR via
    # --diff-filter, but defensive skipping keeps `--tracked` and explicit
    # path modes safe too.
    if [[ ! -f "$p" || -L "$p" ]]; then
        continue
    fi
    enc=$(file --mime-encoding -b -- "$p" 2>/dev/null || echo "binary")
    if [[ "$enc" == "binary" ]]; then
        echo "$prog: binary file: $p" >&2
        failed=$(( failed + 1 ))
    fi
done

if (( failed > 0 )); then
    echo "$prog: $failed binary file(s) detected" >&2
    exit 1
fi

exit 0
