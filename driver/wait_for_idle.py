"""Poll a GNU screen session and return when its visible content stops changing.

Library port of wait-for-idle.sh. Used by other driver modules to wait until
an LLM agent running inside a screen session has gone idle.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import time

from driver.screen_session import ScreenSession


logger = logging.getLogger(__name__)

# Seconds between consecutive hardcopy snapshots. Two unchanged snapshots
# `_INTERVAL` apart constitute "idle". Tuned to be longer than typical
# inter-token gaps while still catching idle states promptly.
_INTERVAL = 20


def session_exists(target: ScreenSession) -> bool:
    """Return True iff `screen -ls` lists `target.session`.

    Accepts either the bare session name (e.g. ``evmbreaker``) or the
    fully-qualified ``pid.name`` form (e.g. ``28575.evmbreaker``).
    `screen -ls` always lists matching sessions as ``<pid>.<name>``, so
    we make the leading ``<pid>.`` optional in the match.
    """
    result = subprocess.run(
        ["screen", "-ls", target.session],
        capture_output=True,
        text=True,
    )
    pattern = re.compile(
        rf"(?:^|\s)(?:[0-9]+\.)?{re.escape(target.session)}\s"
    )
    return bool(pattern.search(result.stdout))


def hardcopy(target: ScreenSession) -> str:
    """Snapshot the visible content of `target` via screen's hardcopy command."""
    fd, path = tempfile.mkstemp(prefix="wait-for-idle-", suffix=".hc")
    os.close(fd)
    try:
        subprocess.run(
            ["screen", "-S", target.session, "-p", target.window,
             "-X", "hardcopy", path],
            check=True,
        )
        with open(path, "rb") as f:
            return f.read().decode("utf-8", errors="replace")
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def wait_for_idle(target: ScreenSession, timeout: int) -> int:
    """Block until `target`'s visible content has been unchanged for `_INTERVAL` s.

    Exit codes match wait-for-idle.sh: 0 idle, 2 timeout, 3 session not found.
    """
    if timeout < 0:
        raise ValueError("timeout must be >= 0")

    if not session_exists(target):
        logger.error("screen session %r not found", target.session)
        return 3

    logger.info(
        "watching %s every %ds%s",
        target, _INTERVAL,
        f" (timeout {timeout}s)" if timeout else "",
    )

    start = time.monotonic()
    prev = hardcopy(target)
    while True:
        time.sleep(_INTERVAL)
        curr = hardcopy(target)
        if curr == prev:
            logger.info("%s idle (no change in %ds)", target, _INTERVAL)
            return 0
        logger.debug("%s still active", target)
        prev = curr
        if timeout > 0 and time.monotonic() - start >= timeout:
            logger.warning("timeout after %ds — %s still active", timeout, target)
            return 2
