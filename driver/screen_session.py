"""Reference to a specific GNU screen session and window."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScreenSession:
    """Identifies a `(session, window)` pair for screen IPC commands.

    `session` is the screen session name (or PID.name); `window` is a window
    number or name as accepted by `screen -p`.
    """
    session: str
    window: str

    def __str__(self) -> str:
        return f"{self.session}:{self.window}"
