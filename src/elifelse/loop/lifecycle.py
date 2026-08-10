"""The shared activity lifecycle — what the base does around EVERY activity.

Done once, generically (instead of copy-pasted per activity):

1. status tracker set -> broadcast
2. activity tracker records start
3. if the activity declares isolate_context: snapshot context + timestamps
4. swap in the activity's system prompt, run its loop
5. on finish:
   a. collect the messages generated during the activity
   b. summary system generates + stores a summary (BEFORE any restore)
   c. if the activity declares a survey: run it
   d. profile manager updates from survey results
   e. memory system flushes extraction with the activity's declared rules,
      for every buffer the activity filled, not only its declared subject
   f. if isolated: restore the pre-activity context, then inject ONE compact
      line: "[You just finished X]\nWhat happened: {summary}"
6. tracker records completion; the note returns to the menu
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from elifelse.providers.base import GenerationError
from elifelse.textutils import print_system

if TYPE_CHECKING:
    from elifelse.activities.base import Activity
    from elifelse.app import App


async def _flush_activity_memory(app: App, activity: Activity, subject: str) -> None:
    """Extract everything this activity buffered, whatever it keyed it under.

    `ctx.remember(subject=...)` files a message under `<key>_<subject>`, and an
    activity that picks its subject partway through its own run cannot have
    declared it in `get_subject()`, which is read before `run()` starts. Chat
    knows who it is talking to up front; a module that offers a menu of people,
    channels or save files does not.

    So the subject computed above is a hint, not the whole answer. Every buffer
    belonging to this activity is flushed: the bare key, the declared subject,
    and anything else filed under `<key>_...` while it ran. Missing one used to
    mean the tail of a conversation sat in the buffer until the next session
    with the same person happened to fill a batch.
    """
    keys = {activity.key}
    if subject:
        keys.add(f"{activity.key}_{subject}")

    prefix = f"{activity.key}_"
    game = activity.memory_mode == "game_batch"
    # push_game_message files under "game_<session key>"; strip that back off so
    # both modes are asking about the same names.
    for buffered in list(app.memory.buffers):
        name = buffered[len("game_"):] if game and buffered.startswith("game_") else buffered
        if name == activity.key or name.startswith(prefix):
            keys.add(name)

    for key in sorted(keys):
        if game:
            await app.memory.flush_game_remaining(key)
        else:
            await app.memory.flush_remaining(key)


async def run_activity(app: App, activity: Activity, subject: str = "") -> str:
    ctx = app.registry.ctx_for(activity)
    label = activity.menu_label
    subject = subject or activity.get_subject(ctx)

    # 1-2. status + tracker
    app.status.set_activity(activity.key, {"subject": subject} if subject else None)
    app.activity_tracker.record_start(activity.key, subject)
    app.stats.increment(f"activity.{activity.key}")

    # 3. snapshot — always taken (it also marks where this activity's messages
    # start, for summaries/extraction); only isolated activities restore it.
    snapshot = app.provider.context.snapshot()

    # 4. activity system prompt + run
    prompt = activity.get_prompt(app.persona)
    if prompt:
        app.provider.set_system_prompt(prompt)

    note = ""
    outcome = "completed"
    try:
        note = await activity.run(ctx)
    except GenerationError as e:
        print_system(f"'{label}' ended early: {e}")
        note = f"{label} ended early because the model failed to produce a valid response."
        outcome = "no_response"

    # 5a. everything this activity added to the context
    new_messages = app.provider.context.messages_since(snapshot)

    # 5b. summary — BEFORE restore, while the messages still exist
    summary = None
    if app.summaries is not None and new_messages:
        summary = await app.summaries.generate_and_store(
            activity_type=activity.key,
            subject=subject or label,
            messages=new_messages,
            formatter=activity.format_transcript,
        )

    # 5c-d. survey + profile update
    if activity.survey and app.innerlife is not None:
        await app.innerlife.run_survey(activity.survey, subject or label, activity.key)

    # 5e. flush buffered memory extraction for this activity
    if app.memory is not None:
        await _flush_activity_memory(app, activity, subject)

    # 5f. restore + compact injection (isolated activities only)
    if activity.isolate_context:
        app.provider.context.restore(snapshot)  # also restores the base system prompt
        compact = f"[You just finished {label}]"
        if summary:
            compact += f"\nWhat happened: {summary}"
        app.provider.context.add("user", compact)
    else:
        # Non-isolated: keep the messages, but always return to the base prompt.
        app.provider.set_system_prompt(app.base_prompt())

    # 6. completion
    app.activity_tracker.record_complete(activity.key, subject, outcome)
    app.status.set_activity("choosing what to do")
    return note
