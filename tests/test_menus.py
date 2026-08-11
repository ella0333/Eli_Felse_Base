"""Every choice put to the model is lettered: main menu, bedtime, and the
sub-menus activities ask through ctx.choose(). The letters are the enum; the
option values stay on the Python side."""

import pytest

from elifelse.activities.base import Activity
from elifelse.loop.menus import build_choice_menu, build_main_menu, letters_for
from elifelse.providers.base import GenerationError


# ~~~ the builder ~~~
def test_letters_wrap_past_z():
    letters = letters_for(30)
    assert letters[:3] == ["A", "B", "C"]
    assert letters[25:28] == ["Z", "AA", "AB"]
    assert len(set(letters)) == 30


def test_choice_menu_renders_letters_and_maps_back():
    menu = build_choice_menu(
        "Where would you like to be?",
        options=["garden", "attic"],
        labels=["The Garden - walled, quiet", "The Attic - dusty boxes"],
        footer="Either is fine.",
    )
    assert menu.letters == ["A", "B"]
    assert menu.mapping == {"A": "garden", "B": "attic"}
    assert menu.text == (
        "Where would you like to be?\n"
        "\n"
        "A) The Garden - walled, quiet\n"
        "B) The Attic - dusty boxes\n"
        "\n"
        "Either is fine."
    )


def test_choice_menu_defaults_labels_to_options():
    menu = build_choice_menu("Pick one", options=["red", "blue"])
    assert "A) red" in menu.text and "B) blue" in menu.text


def test_choice_menu_rejects_mismatched_labels():
    with pytest.raises(ValueError):
        build_choice_menu("Pick one", options=["a", "b"], labels=["only one"])


# ~~~ the one-turn repeat block ~~~
_ENTRIES = [
    {"key": "journal", "label": "Write in your journal", "status": "last: 2 hours ago"},
    {"key": "ponder", "label": "Sit and think for a while", "status": ""},
]


def test_blocked_entry_keeps_its_line_but_leaves_the_enum():
    menu = build_main_menu(_ENTRIES, blocked_key="journal", blocked_note="you just did this")
    assert "A) Write in your journal (last: 2 hours ago) (you just did this)" in menu.text
    assert menu.letters == ["B"]
    assert menu.mapping == {"B": "ponder"}


def test_letters_do_not_shift_when_an_entry_is_blocked():
    """Ponder is B on both menus. A blocked entry that renumbered the rest
    would move every option the agent just read."""
    assert "B) Sit and think for a while" in build_main_menu(_ENTRIES).text
    assert "B) Sit and think for a while" in build_main_menu(
        _ENTRIES, blocked_key="journal"
    ).text


def test_the_only_activity_is_never_blocked():
    menu = build_main_menu(_ENTRIES[:1], blocked_key="journal")
    assert menu.letters == ["A"]
    assert menu.mapping == {"A": "journal"}


# ~~~ ctx.choose ~~~
class _Chooser(Activity):
    key = "chooser"
    menu_label = "Choose"

    async def run(self, ctx):
        return await ctx.choose(
            "Which door?", options=["left", "right"], labels=["The left door", "The right door"]
        )


async def test_choose_sends_letters_and_returns_the_option(app, mock_provider):
    app.registry.register(_Chooser)
    activity = app.registry.get("chooser")
    mock_provider.feed({"thinking": "right feels lucky", "choice": "B"})

    assert await activity.run(app.registry.ctx_for(activity)) == "right"

    call = mock_provider.calls[0]
    assert call["schema"]["properties"]["choice"]["enum"] == ["A", "B"]
    menu_text = str(call["messages"])
    assert "A) The left door" in menu_text
    assert "B) The right door" in menu_text
    # The values the module gets back are never put in front of the model.
    assert "left\\n" not in menu_text


async def test_choose_rejects_a_letter_that_is_not_on_the_menu(app, mock_provider):
    app.registry.register(_Chooser)
    activity = app.registry.get("chooser")
    # Five identical out-of-enum answers exhaust the provider's retries.
    mock_provider.feed(*[{"thinking": "t", "choice": "Z"} for _ in range(6)])

    with pytest.raises(GenerationError):
        await activity.run(app.registry.ctx_for(activity))
