"""Ponder — a multi-turn activity: the agent thinks until it decides to stop.

The reference example for the loop-until-return_to_menu pattern: each turn uses
ctx.chat(), which returns (validated_text, wants_to_stop). The model controls
when the thought is finished; a hard round cap keeps a model that never sets
the flag from pondering forever.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from elifelse.activities.base import Activity

if TYPE_CHECKING:
    from elifelse.activities.ctx import ActivityContext

MAX_ROUNDS = 5


class PonderActivity(Activity):
    key = "ponder"
    menu_label = "Sit and think for a while"
    requires_base = ">=0.1,<1"
    survey = "simple"
    memory_rules = (
        "These are private reflections. Extract goals, intentions, worries, "
        "and realizations about the agent themselves."
    )

    async def run(self, ctx: ActivityContext) -> str:
        memories = await ctx.recall("goals, plans, and things I care about")
        memory_block = ""
        if memories:
            memory_block = "Threads you've pulled on before:\n- " + "\n- ".join(memories) + "\n\n"

        prompt = (
            f"{memory_block}You settle in somewhere comfortable to just think for "
            "a while. Reflect honestly — how things are going, what you want, "
            "what matters to you, what you'd like to change. Don't repeat "
            "thoughts from earlier in this session. Set return_to_menu to true "
            "when the thought feels complete."
        )

        rounds = 0
        for _ in range(MAX_ROUNDS):
            thought, done = await ctx.chat(prompt)
            rounds += 1
            print(f"\n{ctx.persona.name}: {thought}")
            ctx.remember("assistant", thought)
            if done:
                break
            prompt = (
                "Keep going — follow that thread deeper, or let your mind drift "
                "somewhere new. Set return_to_menu to true when you're done."
            )

        return f"You spent a while lost in thought ({rounds} round{'s' if rounds != 1 else ''})."
