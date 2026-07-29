# Developing modules

A module is a Python package implementing the `Activity` interface. Drop it in
`data/modules/<name>/` and the base finds it at startup:

```
data/modules/tarot/
├── __init__.py              # from .src.tarot.activity import Tarot
│                            # ACTIVITIES = [Tarot]
├── requirements.txt         # your own dependencies, if any
└── src/
    ├── __init__.py
    └── tarot/
        ├── __init__.py
        └── activity.py
```

The folder name (`tarot`) is what the base prints and what it looks up in
`trusted_modules.json`; the only thing it requires of you is that
`__init__.py` exposes an `ACTIVITIES` list.

```python
from elifelse.activities import Activity

class Tarot(Activity):
    key = "tarot"                # unique; also your config + storage namespace
    menu_label = "Draw a Tarot Card"
    requires = []                # config keys it needs (empty = key-free)
    requires_base = ">=0.2,<1"   # base version range you built against
    isolate_context = False      # snapshot/restore context around it?
    memory_rules = ""            # extraction guidance (empty = base default)
    survey = None                # survey type, or None

    def available(self, ctx) -> bool:
        return True              # False hides it from the menu entirely

    async def run(self, ctx) -> str:
        card = draw_random_card()                      # plain Python
        reaction = await ctx.freetext(f"You drew {card}. How does it strike you?")
        return f"You drew {card}."                     # the menu note
```

`get_status()` is the line after your label on the main menu. **Don't override it
unless you have something better to say**. The default is the base's
"last: 2 hours ago", which is what the agent actually needs to pace itself.
Override it for live state ("3 unread messages", "currently: The Garden") and fall
back to `super().get_status(ctx)` when there's nothing live to report.

## The ctx API

`ctx` gives you typed, pre-validated results instead of raw LLM responses:

```python
choice = await ctx.choose("What now?", options=["draw", "shuffle", "menu"])
# -> one validated option. You never see the JSON.

choice = await ctx.choose(
    "Which card do you want to turn over?",
    options=[c.key for c in cards],            # what you get back
    labels=[f"{c.name}: {c.meaning}" for c in cards],  # what the model reads
)

text = await ctx.freetext(prompt)
# -> text, DISPLAY-OR-STORE ONLY.

move = await ctx.constrained(prompt, pattern=r"[a-h][1-8][a-h][1-8]")
# -> free text validated against a pattern before you get it.
```

Plus: `ctx.recall(query)`, `ctx.remember(...)`, `ctx.config` (your config section),
`ctx.data_dir` (your storage folder), `ctx.channels`, `ctx.limits` (daily limits),
`ctx.set_status(text)`.

### Menus are always lettered

`ctx.choose` renders every sub-menu the same way the main menu is rendered, and
the schema enum is the letters, never the option values:

```
Which card do you want to turn over?

A) The Tower: sudden upheaval
B) The Star: quiet hope
```

```json
{"choice": {"type": "string", "enum": ["A", "B"]}}
```

So the model answers `B` and your module gets `"star"` back. This is the same
frame the main menu, the bedtime prompt, and every built-in sub-menu use, so an
agent only ever learns one way to answer.

Two things that follow from this:

- **Don't render your own option list into the prompt text.** `ctx.choose` prints
  the options; a hand-rolled list on top of it just shows the agent the menu twice.
- **Keys and IDs stay on the Python side.** Put the human-readable thing in
  `labels` and keep the value in `options`, so the model never has to reproduce a
  filename, a channel ID, or a database key.

If you genuinely need a menu `ctx.choose` can't express, build it with
`build_choice_menu()` from `elifelse.loop.menus` so it still matches.

## Base compatibility

`requires_base` is a PEP 440 specifier checked against the base's version at load
time. If it doesn't match, your module is **skipped with a printed reason** rather
than crashing the run. The agent just carries on without it.

- Declare the version you developed against, capped below the next major:
  `">=0.2,<1"`.
- Additions to the `Activity` / `ctx` interface land in **minor** versions
  (`0.2` → `0.3`). Your module keeps working; you only need to raise
  `requires_base` when you start using something new.
- Breaking changes bump the **major**, which is what the `<1` cap protects you
  from.

The current base version is in `elifelse.__version__`.

## The module contract

Every action in a module must be executed by **programmed Python code**. The LLM cannot
directly call functions, access files, or make network requests. There are no AI agent
tools for the model to invoke. Instead, it interacts through a **menu system**
(`ctx.choose`, `ctx.freetext`, `ctx.constrained`) that returns validated, schema-constrained
JSON. Your Python code then decides what to do with the validated result.

LLM output may be (1) displayed, (2) stored, or (3) passed to a constrained parser (an
enum, a pattern, a game engine, a sandbox). It may NEVER reach a shell, an eval, a
filesystem path, or an outbound request.

## Installing and publishing

1. **Drop-in folder** (primary path): put your package in `data/modules/<name>/` with an
   `__init__.py` exposing `ACTIVITIES = [YourActivity]`. Auto-discovered at startup.
   Install your own dependencies into the base's venv (`pip install -r
   requirements.txt` from inside your module folder).
2. **pip entry point**: register under the `elifelse.activities` entry-point group.
3. Add a row to [modules](modules.md) via PR to get listed.

Anything the user has to set up (tokens, accounts, game files) belongs in a setup
script in your own repo, writing to your module's folder. The base's
`elifelse init` wizard doesn't know about your module.

The built-in activities in `src/elifelse/activities/builtin/` are the reference
implementations; small, commented, meant to be copied.

## Testing

Use the mock provider, no model needed:

```python
from elifelse.providers.mock import MockProvider
```

Script its responses (or "always pick option N") and drive your whole activity flow in a
test. Menu answers are scripted as letters, matching what a real model can send:

```python
provider.feed(
    {"thinking": "the Star, I think", "choice": "B"},   # ctx.choose
    {"thinking": "hopeful", "response": "It fits."},    # ctx.freetext
)
```

See `tests/test_builtin_activities.py` and `tests/test_menus.py` in the base repo
for examples.
