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
    menu_label = "Go somewhere else"
    requires_base = ">=0.1,<1"
    survey = "simple"

    def available(self, ctx: ActivityContext) -> bool:
        env = ctx.app.environment
        return env is not None and len(env.locations) > 1

    def get_status(self, ctx: ActivityContext) -> str:
        env = ctx.app.environment
        return f"currently: {env.current.name}" if env is not None else ""

    async def run(self, ctx: ActivityContext) -> str:
        env = ctx.app.environment
        lines = ["Where would you like to be?"]
        for key, loc in env.locations.items():
            here = " (you are here)" if key == env.current_key else ""
            lines.append(f"- {key}: {loc.name}{here} — {loc.description}")

        choice = await ctx.choose("\n".join(lines), list(env.locations))
        if choice == env.current_key:
            return f"You looked around, but decided to stay at {env.current.name}."

        env.set_current(choice)
        await env.refresh()  # new place, fetch its weather
        return f"You moved to {env.current.name}."
