"""Eat — food and drink options generated behind the scenes, then the character picks.

Food and drink ideas come from an isolated model call (raw_completion — no
character context, no pacing) so the character doesn't "invent" its own
choices. The pick still goes through ctx.choose() with a schema-constrained
enum.

Custom food/drink overrides can be set via the dashboard (stored in
data/activities/eat/overrides.json). When present, those replace the
model-generated options.

Both choices are tracked in history.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from elifelse.activities.base import Activity
from elifelse.textutils import print_system

if TYPE_CHECKING:
    from elifelse.activities.ctx import ActivityContext

HISTORY_SIZE = 5  # recently eaten foods excluded from new suggestions

# Schema for the behind-the-scenes generation (no "thinking" — this is
# a utility call, not the character speaking).
IDEAS_SCHEMA = {
    "type": "object",
    "properties": {
        "meal": {"type": "string"},
        "snack1": {"type": "string"},
        "snack2": {"type": "string"},
        "drink": {"type": "string"},
        "caffeine_drink": {"type": "string"},
    },
    "required": ["meal", "snack1", "snack2", "drink", "caffeine_drink"],
    "additionalProperties": False,
}

# Fallback when the background generation fails.
_FALLBACK_IDEAS = {
    "meal": "a sandwich", "snack1": "an apple", "snack2": "crackers",
    "drink": "juice", "caffeine_drink": "coffee",
}

_REQUIRED_FIELDS = ("meal", "snack1", "snack2", "drink", "caffeine_drink")

OVERRIDES_FILE = "overrides.json"


def load_overrides(data_dir) -> dict:
    """Load custom food/drink overrides from disk. Returns {} if none."""
    path = data_dir / OVERRIDES_FILE
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_overrides(data_dir, overrides: dict) -> None:
    """Save custom food/drink overrides to disk."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / OVERRIDES_FILE
    path.write_text(json.dumps(overrides, indent=2), encoding="utf-8")


class EatActivity(Activity):
    key = "eat"
    menu_label = "Have something to eat"
    requires_base = ">=0.1,<1"
    survey = "simple"
    schemas = {"eat_ideas": IDEAS_SCHEMA}
    memory_rules = (
        "A meal, not an event. Only extract something if it was genuinely "
        "notable (a strong preference discovered, a memory it stirred up)."
    )

    # ~~~ per-activity storage (ctx.data_dir) ~~~
    def _history(self, ctx: ActivityContext) -> list[str]:
        path = ctx.data_dir / "eaten.json"
        if path.exists():
            try:
                return list(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
        return []

    def _save_history(self, ctx: ActivityContext, history: list[str]) -> None:
        path = ctx.data_dir / "eaten.json"
        path.write_text(json.dumps(history[-HISTORY_SIZE:], indent=2), encoding="utf-8")

    async def _generate_ideas(self, ctx: ActivityContext, avoid: str) -> dict:
        """Generate food and drink options via an isolated model call."""
        prompt = (
            "Invent one proper meal and two snack options, plus two non-alcoholic "
            "drink options for someone right now: one regular drink and one "
            "caffeinated drink. Return realistic, everyday items. "
            "Keep names short (2-4 words each)."
        )
        if avoid:
            prompt += f" Avoid these recent items: {avoid}."

        raw = await ctx.app.provider.raw_completion(
            messages=[{"role": "user", "content": prompt}],
            schema=IDEAS_SCHEMA,
        )
        if raw is None:
            return dict(_FALLBACK_IDEAS)
        try:
            ideas = json.loads(raw)
            if all(ideas.get(k) for k in _REQUIRED_FIELDS):
                return ideas
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
        return dict(_FALLBACK_IDEAS)

    async def run(self, ctx: ActivityContext) -> str:
        history = self._history(ctx)
        avoid = ", ".join(history) if history else ""

        # Check for dashboard overrides first.
        overrides = load_overrides(ctx.data_dir)
        custom_foods = [f for f in overrides.get("foods", []) if f]
        custom_drinks = [d for d in overrides.get("drinks", []) if d]

        if custom_foods and len(custom_foods) >= 2:
            # Use custom food options — first is treated as the "meal".
            food_options = list(dict.fromkeys(custom_foods))
            meal_item = food_options[0]
        else:
            # Generate food and drink ideas behind the scenes.
            ideas = await self._generate_ideas(ctx, avoid)
            food_options = list(dict.fromkeys(
                [ideas["meal"], ideas["snack1"], ideas["snack2"]]
            ))
            meal_item = ideas["meal"]

        if custom_drinks:
            drink_options = ["No drink", "Water"] + list(dict.fromkeys(
                d for d in custom_drinks if d.lower() != "water"
            ))
        else:
            if custom_foods:
                # Custom foods but no custom drinks — generate drinks only.
                ideas = await self._generate_ideas(ctx, avoid)
            drink_options = ["No drink", "Water"] + list(dict.fromkeys(
                d for d in [ideas["drink"], ideas["caffeine_drink"]]
                if d.lower() != "water"
            ))

        menu = "What sounds good?\n" + "\n".join(
            f"- {name}" + (" (meal)" if name == meal_item else " (snack)")
            for name in food_options
        )
        food_choice = await ctx.choose(menu, food_options)

        # Drink choice.
        drink_choice = await ctx.choose(
            "Would you like something to drink with that?",
            drink_options,
        )

        # The character describes the experience.
        is_meal = food_choice == meal_item
        minutes = (
            int(ctx.config.get("meal_minutes", 10))
            if is_meal
            else int(ctx.config.get("snack_minutes", 5))
        )

        drink_desc = f" with {drink_choice.lower()}" if drink_choice != "No drink" else ""
        meal_type = "meal" if is_meal else "snack"
        ctx.set_status(f"eating {food_choice}{drink_desc} ({minutes} min)")
        print_system(f"{meal_type} — {minutes} min")
        taste = await ctx.freetext(
            f"You settle in and eat the {food_choice}{drink_desc}. How is it?"
        )
        if minutes > 0:
            await ctx.app.sleep_fn(minutes * 60)  # eating takes real time

        history.append(food_choice)
        self._save_history(ctx, history)
        ctx.remember("assistant", f"Ate {food_choice}{drink_desc}: {taste}")
        return f"You just finished eating ({food_choice}{drink_desc})."
