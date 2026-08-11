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
    requires_base = ">=0.2,<1"
    survey = "simple"
    memory_rules = (
        "These are private reflections. Extract goals, intentions, worries, "
        "and realizations about the agent themselves."
    )

    def _build_ponder_system_prompt(self, ctx: ActivityContext) -> str:
        """Build the full system prompt for pondering.
        Appends ponder guidance and menu preview to the base identity prompt."""
        base = ctx.app.base_prompt()

        ponder_block = (
            "You are taking some time to think, reflecting on your future, your "
            "experiences, and what matters to you. Things you might turn over:\n"
            "- What do you want to achieve or experience?\n"
            "- What matters to you right now?\n"
            "- Are there friendships you want to deepen, things you want to "
            "learn, things you want to finish?\n"
            "- What would make your days feel more meaningful?\n\n"
            "Be honest and genuine. Think about what you actually want, not "
            "what seems like the right answer. There is nothing you have to "
            "arrive at here, and no one is reading over your shoulder.\n\n"
            "If you have already shared thoughts in this session, visible above "
            "in the conversation, let each round go somewhere new or somewhere "
            "deeper rather than restating what you have already said."
        )

        try:
            entries = ctx.app.registry.menu_entries()
        except Exception:
            entries = []
        menu_lines = []
        if entries:
            menu_lines.append(
                "Available menu options (for reference only \u2014 not available "
                "during this activity, listed so you know what to do after "
                "returning to menu):"
            )
            for i, entry in enumerate(entries):
                letter = chr(ord("A") + i)
                status = f" ({entry['status']})" if entry.get("status") else ""
                menu_lines.append(f"{letter}) {entry['label']}{status}")
            menu_lines.append(
                "\nYou must return to menu if you want to choose another menu "
                "option. If you would like to stop the current task and go do "
                "another task from the menu, you must set return_to_menu to true."
            )

        parts = [base, ponder_block]
        if menu_lines:
            parts.append("\n".join(menu_lines))
        return "\n\n".join(parts)

    async def run(self, ctx: ActivityContext) -> str:
        # Set ponder system prompt (base identity + ponder guidance + menu)
        ctx.app.provider.set_system_prompt(
            self._build_ponder_system_prompt(ctx)
        )

        memories = await ctx.recall("goals, plans, and things I care about")
        memory_block = ""
        if memories:
            memory_block = "Threads you've pulled on before:\n- " + "\n- ".join(memories) + "\n\n"

        opening = (
            "Take some time to reflect on your life, your future, and what "
            "matters to you. Think about your experiences and what you want "
            "going forward."
        )
        prompt = f"{memory_block}{opening}"

        rounds = 0
        for _ in range(MAX_ROUNDS):
            thought, done = await ctx.chat(prompt)
            rounds += 1
            print(f"\n{ctx.persona.name}: {thought}")
            ctx.remember("assistant", thought)
            if done:
                break
            prompt = (
                "Continue pondering if you'd like. Reflect further on what's on "
                "your mind, dig deeper, or explore a new thread. Set "
                "return_to_menu when you've thought enough and want to do "
                "something else."
            )

        return f"You spent a while lost in thought ({rounds} round{'s' if rounds != 1 else ''})."
