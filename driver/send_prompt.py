"""Send a prompt into a GNU screen window via screen's register/paste mechanism.

Library port of send_prompt.sh, factored into small primitives. Idle-checking
between sends is intentionally not part of this module — callers compose with
`driver.wait_for_idle` (or any other coordination) themselves.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time

from driver.screen_session import ScreenSession


logger = logging.getLogger(__name__)

# Screen registers are single-byte slots (one char each). 'P' for "prompt" —
# unlikely to collide with user-set registers (which are usually lowercase).
_REGISTER = "P"

# Pause between consecutive `screen -X` commands. `screen -X` returns when the
# command is delivered to the daemon, not when it has been applied — without
# this pause, paste can race readreg, or CR can race paste. Also has to
# outlast the temp file: it must be unlinked only after the daemon has read
# it. 1.0s comfortably covers both on a normal machine.
_SETTLE = 1.0


def stuff(target: ScreenSession, text: str) -> None:
    """Type `text` literally into `target` via screen's `stuff` command.

    Use "\\r" to press Enter. This is also the building block for sending
    arbitrary keystrokes into the agent.
    """
    subprocess.run(
        ["screen", "-S", target.session, "-p", target.window,
         "-X", "stuff", text],
        check=True,
    )


def load_register(target: ScreenSession, register: str, file_path: str) -> None:
    """Read `file_path` into screen register `register` on `target.session`.

    `file_path` must be absolute: screen's `readreg` resolves relative paths
    against the screen daemon's cwd, not the caller's. Note that `readreg`
    is session-scoped — `target.window` is unused but accepted so callers
    can pass the same `ScreenSession` to every primitive.
    """
    if len(register) != 1:
        raise ValueError("register must be a single character")
    subprocess.run(
        ["screen", "-S", target.session, "-X", "readreg", register, file_path],
        check=True,
    )


def paste_register(target: ScreenSession, register: str) -> None:
    """Paste the contents of screen register `register` into `target`."""
    if len(register) != 1:
        raise ValueError("register must be a single character")
    subprocess.run(
        ["screen", "-S", target.session, "-p", target.window,
         "-X", "paste", register],
        check=True,
    )


def send_prompt(target: ScreenSession, prompt: str) -> None:
    """Send `prompt` (raw text) into `target` and press Enter.

    Stages the text through a temp file and an internal screen register,
    then pastes it and sends CR, with internal `_SETTLE` pauses between
    each so screen's IPC has time to apply one command before the next is
    dispatched.
    """
    fd, path = tempfile.mkstemp(prefix="send_prompt-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(prompt)

        logger.info("loading %d bytes into %s", len(prompt), target)
        load_register(target, _REGISTER, path)
        time.sleep(_SETTLE)

        logger.info("pasting into %s", target)
        paste_register(target, _REGISTER)
        time.sleep(_SETTLE)

        logger.debug("sending CR to %s", target)
        stuff(target, "\r")
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
