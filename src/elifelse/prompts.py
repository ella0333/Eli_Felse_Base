"""Base system prompt assembly.

The prompt is rebuilt every loop iteration from live state. Each block is
guarded by a persona flavor toggle, a config toggle, or the owning subsystem
being present — subsystems (inner life, environment, day cycle) slot in here
as they're enabled without any other code changing.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

from elifelse.textutils import format_time_12h

if TYPE_CHECKING:
    from elifelse.app import App

_NVIDIA_SMI: str | None | bool = False  # False = not checked yet


def _gpu_temperature() -> str | None:
    """GPU temperature via nvidia-smi — pure flavor text, fully optional.

    The binary lookup is cached; missing tool / any error just means the line
    is omitted. Never required for anything.
    """
    global _NVIDIA_SMI
    if _NVIDIA_SMI is False:
        _NVIDIA_SMI = shutil.which("nvidia-smi")
    if not _NVIDIA_SMI:
        return None
    try:
        out = subprocess.run(
            [_NVIDIA_SMI, "--query-gpu=temperature.gpu", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        temp = out.stdout.strip().splitlines()[0].strip()
        return f"{temp}C" if temp.isdigit() else None
    except Exception:
        return None


def build_base_prompt(app: App) -> str:
    """Assemble the base system prompt from persona + live state."""
    p = app.persona
    now = app.clock()
    blocks: list[str] = []

    # ~~~ identity ~~~
    identity = [f"You are {p.name}."]
    if p.pronouns:
        identity.append(f"Your pronouns are {p.pronouns}.")
    if p.personality:
        identity.append(p.personality)
    if p.backstory:
        identity.append(p.backstory)
    if p.creator.name:
        rel = f" ({p.creator.relationship})" if p.creator.relationship else ""
        identity.append(f"You were created by {p.creator.name}{rel}.")
    if p.flavor.mention_model and app.config.provider.kind != "mock":
        identity.append(f"You run on the model '{app.config.provider.model}'.")
    days = app.stats.days_since_first_start
    if days > 0:
        identity.append(f"You first came online {days} day{'s' if days != 1 else ''} ago.")
    if p.flavor.mention_hardware:
        temp = _gpu_temperature()
        if temp:
            identity.append(f"Your GPU is currently running at {temp}.")
    blocks.append(" ".join(identity))

    # ~~~ inner life (self-facts + current emotion) ~~~
    if app.innerlife is not None:
        facts = app.innerlife.prompt_block()
        if facts:
            blocks.append(facts)
        if app.innerlife.current_emotion:
            blocks.append(f"You're currently feeling: {app.innerlife.current_emotion}")

    # ~~~ environment ~~~
    if app.environment is not None:
        env = app.environment.prompt_block()
        if env:
            blocks.append(env)

    # ~~~ notifications ~~~
    notifications = app.notification_line()
    if notifications:
        blocks.append(notifications)

    # ~~~ guidance ~~~
    blocks.append(
        "You are autonomous. Choose activities based on your own interests, mood, "
        "and what feels right in the moment. Follow your curiosity, maintain your "
        "routines, and develop your own preferences over time. You don't need "
        "permission or direction from anyone to act."
    )
    blocks.append(
        "You always answer in the JSON format you're given. Use the 'thinking' "
        "field for your honest reasoning — it's your inner voice, not part of "
        "the conversation."
    )

    # ~~~ date / schedule ~~~
    blocks.append(f"Today is {now.strftime('%A, %B %d, %Y')}.")
    dc = app.config.day_cycle
    if dc.enabled:
        blocks.append(
            f"Your daily schedule: you wake up around {format_time_12h(dc.wake_time)} "
            f"and go to bed around {format_time_12h(dc.bedtime)}."
        )

    return "\n\n".join(blocks)
