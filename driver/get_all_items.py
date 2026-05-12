"""Iterate over all work-item directories (`items/<NNN>[suffix]`) in a project root."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


ITEM_PATTERN = re.compile(r"^(\d+)([a-z]*)$")


@dataclass(frozen=True, order=True)
class Item:
    """A work item directory. Ordered naturally by (number, suffix)."""
    number: int
    suffix: str
    path: Path

    @property
    def name(self) -> str:
        return self.path.name


def iter_items(root: Path | str) -> Iterator[Item]:
    """Yield every `items/<NNN>[suffix]` directory under `root`.

    Yielded in numeric+lexicographic order, so 009 < 010 < 045 < 045a < 045b
    (Item.number is the integer, not the zero-padded string). Non-directories
    and unrelated entries inside `root/items/` are skipped.
    """
    items_dir = Path(root) / "items"
    if not items_dir.is_dir():
        return
    matched: list[Item] = []
    for entry in items_dir.iterdir():
        if not entry.is_dir():
            continue
        m = ITEM_PATTERN.match(entry.name)
        if not m:
            continue
        matched.append(Item(number=int(m.group(1)), suffix=m.group(2), path=entry))
    matched.sort()
    yield from matched
