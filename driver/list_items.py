"""Print a markdown table of every work item's status, impact, and title.

Reads each `item<N>[suffix]/README.md`, parses the YAML-style frontmatter
between `---` delimiters, and emits one row per item. Items whose
frontmatter is missing or unparseable get a row with "—" placeholders so
the table doubles as a checklist for items that still need updating.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from driver.get_all_items import Item, iter_items


DRIVER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DRIVER_DIR.parent

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TITLE_RE = re.compile(r"^#\s+(?:Item\s+#\d+\s+[—-]\s+)?(?:\d+[a-z]*[:.]\s+)?(.+?)\s*$")
UNKNOWN = "—"


@dataclass(frozen=True)
class ItemSummary:
    designation: str
    title: str
    status: str
    impact: str


def parse_frontmatter(text: str) -> dict[str, str]:
    """Return a flat dict of scalar frontmatter fields. Lists are kept as raw strings."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        fields[key.strip()] = value.strip()
    return fields


def extract_title(text: str) -> str:
    """First markdown heading after the frontmatter, with leading 'N:' or 'Item #N —' stripped."""
    body = FRONTMATTER_RE.sub("", text, count=1)
    for line in body.splitlines():
        if line.startswith("# "):
            m = TITLE_RE.match(line)
            return m.group(1) if m else line[2:].strip()
    return UNKNOWN


def summarize(item: Item) -> ItemSummary:
    designation = f"{item.number}{item.suffix}"
    readme = item.path / "README.md"
    if not readme.is_file():
        return ItemSummary(designation, UNKNOWN, UNKNOWN, UNKNOWN)
    try:
        text = readme.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ItemSummary(designation, UNKNOWN, UNKNOWN, UNKNOWN)
    fields = parse_frontmatter(text)
    return ItemSummary(
        designation=designation,
        title=extract_title(text),
        status=fields.get("status", UNKNOWN),
        impact=fields.get("impact", UNKNOWN),
    )


def render_table(summaries: list[ItemSummary]) -> str:
    header = "| Item | Status | Impact | Title |\n|---|---|---|---|"
    rows = [
        f"| {s.designation} | {s.status} | {s.impact} | {escape_pipe(s.title)} |"
        for s in summaries
    ]
    return "\n".join([header, *rows])


def escape_pipe(text: str) -> str:
    return text.replace("|", "\\|")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=PROJECT_ROOT,
        help="Project root containing item<N>/ directories (default: %(default)s)",
    )
    args = parser.parse_args()

    summaries = [summarize(item) for item in iter_items(args.root)]
    print(render_table(summaries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
