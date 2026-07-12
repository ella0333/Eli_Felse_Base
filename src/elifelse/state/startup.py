"""Startup selection: fresh start, a named save, or crash recovery.

Priority: an explicit --load wins; --fresh wipes any crash context; otherwise a
leftover crash context (the process died or was Ctrl+C'd) resumes automatically.
Returns the note shown at the top of the agent's first menu.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from elifelse.state.crash import clear_crash_context, load_crash_context, recover_from_crash

if TYPE_CHECKING:
    from elifelse.app import App


def select_startup(app: App, fresh: bool = False, load: str = "") -> str:
    if load:
        return app.saves.load(load)
    if fresh:
        clear_crash_context(app)
        return ""
    data = load_crash_context(app)
    if data is not None:
        return recover_from_crash(app, data)
    return ""
