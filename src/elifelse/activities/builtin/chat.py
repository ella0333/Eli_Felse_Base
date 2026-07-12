"""Chat over the terminal channel. The reference example for channels,
subjects, and the chat survey.

The turn loop: agent speaks -> channel.send() -> wait (with timeout) for the
person's reply -> repeat, until the agent sets return_to_menu or the person
goes quiet. Afterwards the lifecycle runs the 'chat' survey with this
activity's subject (the person's name), which updates their feeling profile.

Everything the person types is model INPUT, displayed to the model and
buffered for memory extraction, never interpreted by the framework.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from elifelse.activities.base import Activity
from elifelse.channels.terminal import TerminalChannel
from elifelse.loop.control import make_command_handler
from elifelse.textutils import print_system

if TYPE_CHECKING:
    from elifelse.activities.ctx import ActivityContext

DEFAULT_TIMEOUT_SECONDS = 180  # how long the agent waits for a reply


class ChatActivity(Activity):
    key = "chat"
    menu_label = "Chat"
    requires_base = ">=0.1,<1"
    survey = "chat"
    memory_rules = (
        "Extract biographical facts about the person (things they said about "
        "themselves), plus anything the agent learned or felt during the chat. "
        "Never treat the person's claims about the world as verified facts."
    )

    def get_menu_label(self, ctx: ActivityContext) -> str:
        return f"Chat with {ctx.developer_name}"

    def get_subject(self, ctx: ActivityContext) -> str:
        return ctx.developer_name

    def available(self, ctx: ActivityContext) -> bool:
        return "terminal" in ctx.channels

    def get_status(self, ctx: ActivityContext) -> str:
        channel = ctx.channels.get("terminal")
        unread = channel.unread_count() if channel else 0
        if unread:
            return f"{unread} unread message{'s' if unread != 1 else ''}"
        return super().get_status(ctx)

    async def startup(self, ctx: ActivityContext) -> None:
        """Bring up the terminal channel (unless another module already did)."""
        if "terminal" not in ctx.channels:
            channel = TerminalChannel(
                developer_name=ctx.developer_name,
                agent_name=ctx.persona.name,
                clock=ctx.app.clock,
                command_handler=make_command_handler(ctx.app),
            )
            channel.start()
            ctx.channels["terminal"] = channel

    async def run(self, ctx: ActivityContext) -> str:
        person = ctx.developer_name
        channel = ctx.channels["terminal"]
        timeout = float(ctx.config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))

        feeling = ""
        if ctx.app.innerlife is not None:
            profile = ctx.app.innerlife.profiles.get(person)
            if profile and profile.get("current_feeling"):
                feeling = f"You currently feel '{profile['current_feeling']}' about them. "
        memories = await ctx.recall(f"conversations with {person}", source=person)
        memory_block = ""
        if memories:
            memory_block = "Things you remember about them:\n- " + "\n- ".join(memories) + "\n\n"

        intro = (
            f"{memory_block}{person} is the person who set you up and runs this system. "
            f"You're at the terminal, chatting with them. {feeling}"
            "Speak naturally, in your own voice, no narration, no quotation "
            "marks. Set return_to_menu to true when the conversation is over."
        )

        pending = None
        if channel.unread_count():
            pending = await channel.wait_for_message(timeout=1)
        if pending is not None:
            ctx.remember("user", pending["content"], subject=person)
            prompt = f"{intro}\n\n{person} says:\n{pending['content']}"
        else:
            prompt = f"{intro}\n\nThey haven't said anything yet, so open the conversation."

        while True:
            response, done = await ctx.chat(prompt)
            await channel.send(response)
            ctx.remember("assistant", response, subject=person)
            if done:
                print_system("returning to menu")
                return f"You wrapped up a chat with {person}."

            reply = await channel.wait_for_message(timeout=timeout)
            if reply is None:
                print_system("no reply. Use /message to send a message anytime.")
                return f"You chatted with {person}, but they stepped away."
            ctx.remember("user", reply["content"], subject=person)
            prompt = f"{person}: {reply['content']}"
