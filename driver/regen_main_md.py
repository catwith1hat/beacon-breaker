"""Regenerate the Findings tables in the project-root README.md.

Walks every `items/<NNN>[suffix]/` directory, reads each `README.md`'s
front matter, filters for `impact != none`, splits into two buckets by
the optional `remediated:` flag, and rewrites two sections:

  ## Active findings (as of YYYY-MM-DD)
      | # | Finding | Split | Mainnet reach |
      …rows for impact != none AND remediated unset…

  ## Remediated findings
      | # | Finding | Split | Mainnet reach |
      …rows for items with `remediated: true`…

Column semantics:
- `#`              — `[#<designation>](items/<NNN>[suffix]/)` link.
- `Finding`        — content of the `# main_md_summary:` YAML-comment
                     line in the item's front matter.
- `Split`          — comma-separated splits list followed by an
                     auto-computed `(N-vs-M)` ratio against the
                     six-client total.
- `Mainnet reach`  — derived from the front-matter `impact` value.

The "as of" date is today's date when the script runs. Both tables sort
by impact severity then by item number.

Run from the repo root or anywhere; locates the project via the script's
parent directory.
"""

from __future__ import annotations

import datetime
import logging
import re
import sys
from pathlib import Path
from typing import NamedTuple

from driver.get_all_items import Item, iter_items


logger = logging.getLogger(__name__)

NUM_CLIENTS = 6

# Severity ordering: row sort key (lower = higher in the table).
IMPACT_RANK: dict[str, int] = {
    "mainnet-everyone": 0,
    "mainnet-proposer": 1,
    "custom-chain": 2,
    "synthetic-state": 3,
    "contained": 4,
    "unknown": 5,
}

# Mainnet-reach column text per impact value.
IMPACT_REACH: dict[str, str] = {
    "mainnet-everyone": "Active — anyone",
    "mainnet-proposer": "Active — proposer",
    "custom-chain": "D — custom chain",
    "synthetic-state": "D — synthetic state",
    "contained": "D — contained upstream",
    "unknown": "Unknown",
}


class Finding(NamedTuple):
    item: Item
    impact: str
    splits: list[str]
    summary: str
    remediated: bool

    @property
    def designation(self) -> str:
        return f"{self.item.number}{self.item.suffix}"


def parse_front_matter(readme_path: Path) -> dict[str, str] | None:
    """Return a dict of front-matter fields, or None if no front matter.

    The `# main_md_summary:` YAML-comment line is captured under the key
    `main_md_summary`. Other comment lines are ignored.
    """
    text = readme_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = next(
        (i for i in range(1, len(lines)) if lines[i].strip() == "---"),
        None,
    )
    if end is None:
        return None

    fm: dict[str, str] = {}
    summary_re = re.compile(r"^# main_md_summary:\s*(.+)$")
    field_re = re.compile(r"^([a-z_]+):\s*(.*)$")
    for line in lines[1:end]:
        m = summary_re.match(line)
        if m:
            fm["main_md_summary"] = m.group(1).strip()
            continue
        m = field_re.match(line)
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return fm


def parse_splits(value: str) -> list[str]:
    """Parse `[prysm, grandine]` into `['prysm', 'grandine']`. `[]` → `[]`."""
    s = value.strip()
    if not (s.startswith("[") and s.endswith("]")):
        raise ValueError(f"splits value not bracketed: {value!r}")
    inner = s[1:-1].strip()
    if not inner:
        return []
    return [token.strip() for token in inner.split(",")]


def gather_findings(root: Path) -> list[Finding]:
    """Walk `root` for items with `impact != none` and a populated summary."""
    findings: list[Finding] = []
    for item in iter_items(root):
        readme = item.path / "README.md"
        if not readme.is_file():
            logger.warning("%s: no README.md, skipping", item.name)
            continue
        fm = parse_front_matter(readme)
        if fm is None:
            logger.warning("%s: no front matter, skipping", item.name)
            continue
        impact = fm.get("impact", "")
        if impact in ("", "none"):
            continue
        try:
            splits = parse_splits(fm.get("splits", "[]"))
        except ValueError as e:
            logger.warning("%s: %s, skipping", item.name, e)
            continue
        summary = fm.get("main_md_summary", "").strip()
        if not summary:
            logger.warning("%s: impact=%s but no main_md_summary, skipping",
                           item.name, impact)
            continue
        remediated = fm.get("remediated", "").strip() == "true"
        findings.append(Finding(item, impact, splits, summary, remediated))
    return findings


def split_cell(splits: list[str]) -> str:
    """Render the splits column: `client1, client2 (N-vs-M)`."""
    if not splits:
        return "—"
    clients = ", ".join(splits)
    ratio = f"{len(splits)}-vs-{NUM_CLIENTS - len(splits)}"
    return f"{clients} ({ratio})"


def render_table(findings: list[Finding]) -> str:
    """Render the four-column table. Returns an em-dash placeholder if empty."""
    if not findings:
        return "_(none)_"
    rows = ["| # | Finding | Split | Mainnet reach |",
            "|---|---|---|---|"]
    findings_sorted = sorted(
        findings,
        key=lambda f: (IMPACT_RANK.get(f.impact, 99), f.item.number, f.item.suffix),
    )
    for f in findings_sorted:
        d = f.designation
        link = f"[#{d}](items/{f.item.path.name}/)"
        # Escape pipes so cell content can't break the table.
        summary = f.summary.replace("|", "\\|")
        reach = IMPACT_REACH.get(f.impact, f.impact)
        rows.append(f"| {link} | {summary} | {split_cell(f.splits)} | {reach} |")
    return "\n".join(rows)


# Heading lines that the regenerator owns. When walking the README, any of
# these starts the findings region; the region ends at the next H2 that is
# NOT one of these.
_OWNED_HEADINGS = (
    "## Findings",                # legacy
    "## Active findings",         # current
    "## Remediated findings",
)


def _is_owned_h2(line: str) -> bool:
    return any(line.startswith(h) for h in _OWNED_HEADINGS)


def replace_findings_section(
    readme_path: Path,
    active_table: str,
    remediated_table: str,
    today: str,
) -> bool:
    """Replace the entire findings region with two regenerated sections.

    Region = from the first `## Findings`/`## Active findings`/
    `## Remediated findings` heading through to (but not including) the
    next H2 heading that isn't one of those. Replaced wholesale by:

        ## Active findings (as of <today>)

        <active_table>

        ## Remediated findings

        <remediated_table>

    Returns True if the file changed on disk.
    """
    text = readme_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Find the first owned-H2.
    start = next(
        (i for i, line in enumerate(lines) if _is_owned_h2(line)),
        None,
    )
    if start is None:
        raise RuntimeError(
            f"no '## Findings' / '## Active findings' / '## Remediated findings' "
            f"heading found in {readme_path}"
        )

    # Find the end: the first H2 after `start` that isn't one of ours.
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## ") and not _is_owned_h2(lines[i]):
            end = i
            break

    # Build replacement.
    replacement_lines = [
        f"## Active findings (as of {today})",
        "",
        active_table,
        "",
        "## Remediated findings",
        "",
        remediated_table,
        "",
    ]

    new_lines = lines[:start] + replacement_lines + lines[end:]
    new_text = "\n".join(new_lines)
    if text.endswith("\n"):
        new_text += "\n"

    if new_text == text:
        return False
    readme_path.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    here = Path(__file__).resolve().parent
    project_root = here.parent
    readme = project_root / "README.md"
    if not readme.is_file():
        logger.error("README.md not found at %s", readme)
        return 1

    findings = gather_findings(project_root)
    active = [f for f in findings if not f.remediated]
    remediated = [f for f in findings if f.remediated]
    today = datetime.date.today().isoformat()

    active_table = render_table(active)
    remediated_table = render_table(remediated)
    changed = replace_findings_section(readme, active_table, remediated_table, today)
    logger.info(
        "%d active + %d remediated written to %s (%s)",
        len(active), len(remediated), readme,
        "modified" if changed else "no changes",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
