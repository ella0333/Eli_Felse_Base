# Developing modules

A module is a Python package implementing the `Activity` interface:

```python
from elifelse.activities import Activity

class Tarot(Activity):
    key = "tarot"
    menu_label = "Draw a Tarot Card"
    requires = []            # config keys it needs (empty = key-free)
    requires_base = ">=0.1"  # base version range
    isolate_context = False  # snapshot/restore context around it?
    memory_rules = ""        # extraction guidance (empty = base default)
    survey = None            # survey type, or None

    def get_status(self, ctx) -> str:
        return ""            # menu status line, e.g. "last drawn 2h ago"

    async def run(self, ctx) -> str:
        card = draw_random_card()                      # plain Python
        reaction = await ctx.freetext(f"You drew {card}. How does it strike you?")
        return f"You drew {card}."                     # the menu note
```

## The ctx API

`ctx` gives you typed, pre-validated results instead of raw LLM responses:

```python
choice = await ctx.choose(prompt, options=["draw", "shuffle", "menu"])
# -> one validated enum member. You never see the JSON.

text = await ctx.freetext(prompt)
# -> text, DISPLAY-OR-STORE ONLY.

move = await ctx.constrained(prompt, pattern=r"[a-h][1-8][a-h][1-8]")
# -> free text validated against a pattern before you get it.
```

Plus: `ctx.recall(query)`, `ctx.remember(...)`, `ctx.config` (your config section),
`ctx.data_dir` (your storage folder), `ctx.channels`, `ctx.limits` (daily limits),
`ctx.set_status(text)`.

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
2. **pip entry point**: register under the `elifelse.activities` entry-point group.
3. Add a row to [modules](modules.md) via PR to get listed.

The built-in activities in `src/elifelse/activities/builtin/` are the reference
implementations; small, commented, meant to be copied.

## Testing

Use the mock provider, no model needed:

```python
from elifelse.providers.mock import MockProvider
```

Script its responses (or "always pick option N") and drive your whole activity flow in a
test. See `tests/test_builtin_activities.py` in the base repo for examples.
