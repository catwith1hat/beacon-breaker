"""Regenerate ITEM_TOC.md — a flat table of every item.

Walks every `items/<NNN>[suffix]/` directory, reads each README's
front matter `status` field and the H1 title that appears after the
front matter, and writes a three-column table:

    | # | Title | Status |

  * `#`      — `[#<designation>](items/<NNN>[suffix]/)` link.
  * `Title`  — the H1 with the leading `<designation>:` prefix stripped.
  * `Status` — the `status:` field from the front matter, verbatim.

Unlike regen_main_md.py, this lists every item (not just impact != none).
Rows are sorted by item number then suffix.

Run from anywhere; locates the project via the script's parent directory.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import NamedTuple

from driver.get_all_items import Item, iter_items


logger = logging.getLogger(__name__)


class Row(NamedTuple):
    item: Item
    title: str
    status: str

    @property
    def designation(self) -> str:
        return f"{self.item.number}{self.item.suffix}"


def parse_status(text: str) -> str:
    """Return the value of the `status:` front-matter field, or empty."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    end = next(
        (i for i in range(1, len(lines)) if lines[i].strip() == "---"),
        None,
    )
    if end is None:
        return ""
    field_re = re.compile(r"^status:\s*(.*)$")
    for line in lines[1:end]:
        m = field_re.match(line)
        if m:
            return m.group(1).strip()
    return ""


def parse_title(text: str, designation: str) -> str:
    """Return the H1 title with the leading `<designation>:` stripped.

    Skips any `# <something>` lines that appear inside the front matter
    (e.g. the `# main_md_summary:` YAML comment). Only the first H1 after
    the closing `---` is taken.
    """
    lines = text.splitlines()
    body_start = 0
    if lines and lines[0].strip() == "---":
        end = next(
            (i for i in range(1, len(lines)) if lines[i].strip() == "---"),
            None,
        )
        if end is not None:
            body_start = end + 1
    for line in lines[body_start:]:
        s = line.lstrip()
        if not s.startswith("# "):
            continue
        if s.startswith("## "):
            continue
        title = s[2:].strip()
        # Strip the `<designation>: ` prefix if present.
        prefix = f"{designation}:"
        if title.startswith(prefix):
            title = title[len(prefix):].strip()
        return title
    return ""


def gather_rows(root: Path) -> list[Row]:
    rows: list[Row] = []
    for item in iter_items(root):
        readme = item.path / "README.md"
        if not readme.is_file():
            logger.warning("%s: no README.md, skipping", item.name)
            continue
        text = readme.read_text(encoding="utf-8")
        designation = f"{item.number}{item.suffix}"
        status = parse_status(text)
        title = parse_title(text, designation)
        if not title:
            logger.warning("%s: no H1 title found", item.name)
        rows.append(Row(item, title, status))
    return rows


def render(rows: list[Row]) -> str:
    out = [
        "# Item Table of Contents",
        "",
        "All items in this audit, sorted by number. For only the items "
        "that produced a confirmed cross-client divergence, see the "
        "Active findings table on the [project README](README.md).",
        "",
        "| # | Title | Status |",
        "|---|---|---|",
    ]
    for row in rows:
        d = row.designation
        link = f"[#{d}](items/{row.item.path.name}/)"
        # Escape pipes inside cells so they can't break the table.
        title = row.title.replace("|", "\\|")
        status = (row.status or "—").replace("|", "\\|")
        out.append(f"| {link} | {title} | {status} |")
    out.append("")
    return "\n".join(out)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    here = Path(__file__).resolve().parent
    project_root = here.parent
    out_path = project_root / "ITEM_TOC.md"

    rows = gather_rows(project_root)
    text = render(rows)
    previous = out_path.read_text(encoding="utf-8") if out_path.is_file() else ""
    if text == previous:
        logger.info("%d items: %s unchanged", len(rows), out_path)
        return 0
    out_path.write_text(text, encoding="utf-8")
    logger.info("%d items written to %s", len(rows), out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
