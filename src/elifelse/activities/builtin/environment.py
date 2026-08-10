"""Change surroundings — move between the configured environment locations.

Pure ambience: the choice enum is the configured location keys, the note says
where the agent went, and nothing is extracted to memory (moving rooms is not
an event worth remembering).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from elifelse.activities.base import Activity

if TYPE_CHECKING:
    from elifelse.activities.ctx import ActivityContext


class EnvironmentActivity(Activity):
    key = "environment"
    menu_label = "Change the environment"
    requires_base = ">=0.2,<1"
    survey = "simple"

    def available(self, ctx: ActivityContext) -> bool:
        env = ctx.app.environment
        return env is not None and len(env.locations) > 1

    def get_status(self, ctx: ActivityContext) -> str:
        env = ctx.app.environment
        return f"currently: {env.current.name}" if env is not None else ""

    async def run(self, ctx: ActivityContext) -> str:
        # Same routine the first run uses to ask where it wants to be, so a
        # move mid-day and the opening choice read and behave identically.
        return await ctx.app.environment.select(ctx.app, "Where would you like to be?")
