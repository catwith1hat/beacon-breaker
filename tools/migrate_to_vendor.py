"""One-shot migration: <submodule>/ → vendor/<submodule>/ for vendored submodules.

Mirrors evm-breaker's driver/migrate_to_vendor.py (commit 48d204c).

Run from anywhere; the script locates the repo via its parent directory.

Steps:
  1. `git mv` each submodule into vendor/. Updates .gitmodules and the
     index entries automatically.
  2. Sweep markdown files: rewrite path-shaped references inside
     `single-backtick` code spans only. The regex handles three forms:
       <submodule>/...        →  vendor/<submodule>/...
       ./<submodule>(/...)?   →  ./vendor/<submodule>(/...)?
       ../<submodule>(/...)?  →  ../vendor/<submodule>(/...)?
     Bare `<submodule>` (no slash, no relative prefix) is left alone
     (those are name labels, not paths). The match is anchored at the
     start of each span so mid-path occurrences (e.g. Java package
     paths like `tech/pegasys/teku/...`) are NOT touched.

Non-markdown path references (shell scripts, fixture configs, source
literals) are NOT swept automatically because comments and string
literals in code files can collide with prose. Those (if any) are
hand-edited after running this script.

Likewise, code-block (triple-backtick) content in markdown is NOT swept
automatically — the few cases where a path appears in a code block are
hand-edited.

After cloning post-migration, run `git submodule sync && git submodule
update --init` to re-attach the worktrees.

This script is one-shot. Delete in a follow-up commit after the move.
"""
from __future__ import annotations

import argparse
import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Order matters: longer names first so the alternation prefers
# `consensus-spec-tests` over `consensus-specs` over bare prefixes.
SUBMODULES: tuple[str, ...] = (
    "consensus-spec-tests",
    "consensus-specs",
    "beacon-APIs",
    "lighthouse",
    "lodestar",
    "grandine",
    "nimbus",
    "prysm",
    "teku",
)

_SUBS_ALT = "|".join(re.escape(s) for s in SUBMODULES)

# Anchored at the START of the span content (with optional leading
# whitespace). Two alternatives:
#   variant A: ./submodule or ../submodule  (relative path)
#   variant B: submodule/                    (bare name with following /)
# Mid-path occurrences (e.g. `tech/pegasys/teku/...` where teku is a
# Java package directory, not the submodule root) are NOT matched
# because the regex requires the submodule name to start the span.
_INNER_RE = re.compile(
    r"^(\s*)"
    r"(?:"
    r"((?:\.\.?/)+)\b(" + _SUBS_ALT + r")(?=\b)"
    r"|"
    r"\b(" + _SUBS_ALT + r")(?=/)"
    r")"
)

_SPAN_RE = re.compile(r"`([^`]+)`")


def _inner_repl(m: re.Match[str]) -> str:
    leading = m.group(1)
    if m.group(2) is not None:  # variant A: ./submodule or ../submodule
        return f"{leading}{m.group(2)}vendor/{m.group(3)}"
    return f"{leading}vendor/{m.group(4)}"  # variant B: submodule/


def rewrite_md(text: str) -> str:
    """Rewrite submodule path references inside single-backtick spans only.

    Only the start of each span content is considered (with optional
    leading whitespace). Mid-span occurrences (e.g. Java package paths)
    are left alone.
    """
    def span_repl(m: re.Match[str]) -> str:
        content = m.group(1)
        new_content, n = _INNER_RE.subn(_inner_repl, content, count=1)
        return f"`{new_content}`" if n else m.group(0)
    return _SPAN_RE.sub(span_repl, text)


def list_tracked(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        capture_output=True, text=True, check=True,
    )
    return [root / line for line in out.stdout.splitlines() if line]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="print what would change without touching files")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    here = Path(__file__).resolve().parent
    root = here.parent

    if (root / "vendor").exists() and any((root / "vendor").iterdir()):
        logger.error("'vendor/' already exists and is non-empty at %s — aborting",
                     root / "vendor")
        return 1

    missing = [s for s in SUBMODULES if not (root / s).exists()]
    if missing:
        logger.error("missing top-level entries: %s", missing)
        return 1

    logger.info("planning to move %d submodules into vendor/", len(SUBMODULES))
    if args.dry_run:
        for s in SUBMODULES:
            logger.info("DRY RUN: git mv %s vendor/%s", s, s)
    else:
        (root / "vendor").mkdir(exist_ok=True)
        for s in SUBMODULES:
            subprocess.run(
                ["git", "-C", str(root), "mv", s, f"vendor/{s}"],
                check=True,
            )
        logger.info("moved %d submodules", len(SUBMODULES))

    logger.info("sweeping markdown files (inside-backticks only)")
    md_changed: list[Path] = []
    for f in list_tracked(root):
        if not f.is_file() or f.suffix != ".md":
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new_text = rewrite_md(text)
        if new_text != text:
            md_changed.append(f)
            if not args.dry_run:
                f.write_text(new_text, encoding="utf-8")

    logger.info("%d markdown files %srewritten", len(md_changed),
                "would be " if args.dry_run else "")
    for f in md_changed[:8]:
        logger.info("  %s", f.relative_to(root))
    if len(md_changed) > 8:
        logger.info("  ... (%d more)", len(md_changed) - 8)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
