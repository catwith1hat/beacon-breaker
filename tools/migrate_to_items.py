"""One-shot migration: itemN/ → items/0NN/.

Mirrors evm-breaker's driver/migrate_to_items.py (commit 02dd1a2):

  1. Build the rename map for top-level itemN/ directories.
  2. mkdir -p items/, then `git mv` each entry to its 3-digit zero-padded
     slot under items/.
  3. Sweep tracked files for `\\bitem(\\d+)/` (strict trailing slash —
     only path references match) and rewrite to `items/0NN/`.

Pure renames in step 2 (no content changes), so git records them as
renames in the resulting commit. Step 3 rewrites in-place.

Use --dry-run first to inspect the plan without touching anything.

beacon-breaker has no item-name suffixes (item1..item56, all numeric),
so the regex is simpler than evm-breaker's; the principle is identical.
"""
from __future__ import annotations

import argparse
import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

ITEM_DIR_RE = re.compile(r"^item(\d+)$")
PATH_REF_RE = re.compile(r"\bitem(\d+)/")


def find_item_dirs(root: Path):
    pairs = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        m = ITEM_DIR_RE.match(entry.name)
        if not m:
            continue
        num = int(m.group(1))
        dst = root / "items" / f"{num:03d}"
        pairs.append((entry, dst))
    pairs.sort(key=lambda p: int(ITEM_DIR_RE.match(p[0].name).group(1)))
    return pairs


def build_rewrite_map(pairs):
    return {f"{src.name}/": f"items/{dst.name}/" for src, dst in pairs}


def list_tracked(root: Path):
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        capture_output=True, text=True, check=True,
    )
    return [root / line for line in out.stdout.splitlines() if line]


def rewrite_text(text: str, rmap: dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        return rmap.get(m.group(0), m.group(0))
    return PATH_REF_RE.sub(repl, text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    here = Path(__file__).resolve().parent
    root = here.parent

    if (root / "items").exists() and any((root / "items").iterdir()):
        logger.error("'items/' already exists and is non-empty — aborting")
        return 1

    pairs = find_item_dirs(root)
    if not pairs:
        logger.error("no item directories found")
        return 1
    logger.info("found %d item directories to rename", len(pairs))

    rmap = build_rewrite_map(pairs)

    if args.dry_run:
        logger.info("DRY RUN — first 5 renames:")
        for src, dst in pairs[:5]:
            logger.info("  %s/ → %s/", src.name, dst.relative_to(root))
        logger.info("  ... (%d more)", max(0, len(pairs) - 5))
    else:
        (root / "items").mkdir(exist_ok=True)
        for src, dst in pairs:
            subprocess.run(
                ["git", "-C", str(root), "mv",
                 str(src.relative_to(root)),
                 str(dst.relative_to(root))],
                check=True,
            )
        logger.info("renamed %d directories", len(pairs))

    logger.info("sweeping tracked files for path references")
    tracked = list_tracked(root)
    changed = []
    for f in tracked:
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new_text = rewrite_text(text, rmap)
        if new_text != text:
            changed.append(f)
            if not args.dry_run:
                f.write_text(new_text, encoding="utf-8")
    logger.info("%d files %srewritten", len(changed),
                "would be " if args.dry_run else "")
    for f in changed[:5]:
        logger.info("  %s", f.relative_to(root))
    if len(changed) > 5:
        logger.info("  ... (%d more)", len(changed) - 5)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
