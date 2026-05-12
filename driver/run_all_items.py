"""Run a recheck prompt against every work-item directory in sequence.

For each `item<N>[suffix]` under the project root: wait for the screen
session to go idle, render the prompt template with that item's designation
substituted in, send it into the agent, and move on. A final idle-wait runs
after the last send so this only returns when the agent has finished the
last item.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from driver.get_all_items import Item, iter_items
from driver.screen_session import ScreenSession
from driver.send_prompt import send_prompt
from driver.wait_for_idle import wait_for_idle


logger = logging.getLogger(__name__)

PLACEHOLDER = "${ITEM}"

DRIVER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DRIVER_DIR.parent
TEMPLATE_PATH = DRIVER_DIR / "recheck_and_reformat.item-prompt"


def designation(item: Item) -> str:
    """Return the user-visible item identifier (e.g. '127', '45b')."""
    return f"{item.number}{item.suffix}"


def render_prompt(template: str, item: Item) -> str:
    """Substitute ${ITEM} in `template` with `item`'s designation."""
    if PLACEHOLDER not in template:
        raise ValueError(f"template does not contain {PLACEHOLDER!r}")
    return template.replace(PLACEHOLDER, designation(item))


def run_all_items(
    root: Path,
    template_path: Path,
    target: ScreenSession,
    timeout: int,
) -> None:
    """Iterate every item under `root`, prompting the agent once per item.

    Loop body per item: wait_for_idle → render template → send_prompt.
    A trailing wait_for_idle confirms the agent finished the last item.
    Raises RuntimeError if any wait_for_idle returns non-zero.
    """
    template = Path(template_path).read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise ValueError(
            f"template at {template_path} does not contain {PLACEHOLDER!r}"
        )

    items = list(iter_items(root))
    if not items:
        raise RuntimeError(f"no item<N>[suffix] directories found under {root}")
    logger.info("found %d items under %s", len(items), root)

    for n, item in enumerate(items, 1):
        tag = designation(item)
        logger.info("[%d/%d] item %s — waiting for idle", n, len(items), tag)

        rc = wait_for_idle(target, timeout)
        if rc != 0:
            raise RuntimeError(
                f"wait_for_idle failed before item {tag} (rc={rc})"
            )

        logger.info("[%d/%d] item %s — sending prompt", n, len(items), tag)
        send_prompt(target, render_prompt(template, item))

    logger.info("final wait — confirming agent finished last item")
    rc = wait_for_idle(target, timeout)
    if rc != 0:
        raise RuntimeError(f"final wait_for_idle failed (rc={rc})")

    logger.info("done — sent %d prompts", len(items))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_all_items.py",
        description=(
            "Send the recheck prompt template into a screen session once per "
            "item<N>[suffix] directory, waiting for the agent to go idle "
            "between sends."
        ),
    )
    p.add_argument("session", help="GNU screen session name (or PID.name)")
    p.add_argument("window", help="screen window number or name")
    p.add_argument(
        "-t", "--timeout",
        type=int,
        default=0,
        help="per-wait timeout in seconds (default: 0 = no limit)",
    )
    args = p.parse_args(argv)
    if args.timeout < 0:
        p.error("--timeout must be >= 0")
    return args


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ns = _parse_args()
    run_all_items(
        root=PROJECT_ROOT,
        template_path=TEMPLATE_PATH,
        target=ScreenSession(session=ns.session, window=ns.window),
        timeout=ns.timeout,
    )
