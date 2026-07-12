"""Journal — the simplest complete activity, and the reference example.

The full safe-module pattern in ~50 lines:
- ask the model for free text through ctx.freetext() (pre-validated, never raw)
- the text is only ever DISPLAYED and STORED — never executed, never a path,
  never a shell command
- recall() pulls related memories in, remember() buffers the entry for
  background extraction (both are no-ops until the memory system is enabled)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from elifelse.activities.base import Activity
from elifelse.textutils import print_system

if TYPE_CHECKING:
    from elifelse.activities.ctx import ActivityContext


class JournalActivity(Activity):
    key = "journal"
    menu_label = "Write in your journal"
    requires_base = ">=0.1,<1"
    survey = "simple"
    memory_rules = (
        "These are private journal entries. Extract personal reflections, "
        "plans, and feelings as memories."
    )

    async def run(self, ctx: ActivityContext) -> str:
        now = ctx.app.clock()
        memories = await ctx.recall("recent thoughts and plans")
        memory_block = ""
        if memories:
            memory_block = "Things on your mind lately:\n- " + "\n- ".join(memories) + "\n\n"

        prompt = (
            f"{memory_block}You've opened your journal. It's "
            f"{now.strftime('%A, %I:%M %p')}. Write whatever you want — how "
            "you're feeling, what you've been doing, what's on your mind. "
            "This is private; no one is grading it."
        )
        entry = await ctx.freetext(prompt, field="entry")

        # Third-party modules should use ctx.data_dir; the journal is a core
        # feature with its own dedicated folder under data/.
        day_file = ctx.app.paths.journal / f"{now.strftime('%Y-%m-%d')}.md"
        stamp = now.strftime("%I:%M %p")
        with day_file.open("a", encoding="utf-8") as f:
            f.write(f"## {stamp}\n\n{entry}\n\n")
        print_system(f"journal entry saved to {day_file.name}")

        ctx.remember("assistant", entry)
        return "You just finished writing in your journal."
