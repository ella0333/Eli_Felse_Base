"""The main loop.

Each iteration:
1. write the crash-context file (a crash can resume from the last known state)
2. budget check — over the daily token cap, the agent auto-sleeps until reset
3. pause/stop control check (graceful shutdown path)
4. scheduler interrupts (bedtime menu, module pre-menu hooks)
5. build the main menu dynamically from every installed activity, with whatever
   was picked last turn held back so the agent cannot loop on one activity
6. send it with a menu schema whose enum is exactly the selectable letters
7. dispatch the validated choice through the registry + shared lifecycle
8. the activity's note is shown at the top of the next menu
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from elifelse.loop.lifecycle import run_activity
from elifelse.loop.menus import build_main_menu
from elifelse.providers.base import is_transient_error
from elifelse.state.crash import clear_crash_context, write_crash_context
from elifelse.textutils import print_system

if TYPE_CHECKING:
    from elifelse.app import App

MAX_CONSECUTIVE_MENU_FAILURES = 3


class Controller:
    def __init__(self, app: App) -> None:
        self.app = app
        self.note = ""
        self.iterations_run = 0
        # The activity picked last turn, held back from the next menu.
        self.last_choice_key = ""

    async def main_loop(self, max_iterations: int | None = None, initial_note: str = "") -> None:
        app = self.app
        self.note = initial_note
        menu_failures = 0

        # 0. first run only: the agent picks its environment before anything
        # else. Restoring a save or a crash context sets one already, so this
        # comes up once in the agent's life, not once per boot.
        if app.environment is not None and not app.environment.chosen:
            print_system("environment: choosing where to exist")
            opening = await app.environment.select(app)
            self.note = "\n".join(filter(None, [self.note, opening]))

        while max_iterations is None or self.iterations_run < max_iterations:
            self.iterations_run += 1

            # 1. crash context
            write_crash_context(app, self.note)

            # 2. budget cap: auto-sleep until the daily reset
            if app.provider.budget.exceeded:
                await self._budget_sleep()
                continue

            # 3. graceful pause/stop
            if app.control.stop_requested:
                await self._graceful_exit()
                return
            if app.control.pause_requested:
                await self._graceful_pause()
                continue

            # 4. scheduler interrupts (bedtime, module hooks)
            interrupt_notes = await app.scheduler.run_pre_menu()
            if interrupt_notes:
                self.note = "\n".join(filter(None, [self.note, *interrupt_notes]))

            # 5-6. menu
            app.provider.set_system_prompt(app.base_prompt())
            entries = app.registry.menu_entries()
            if not entries:
                print_system("No activities available; nothing to do. Exiting loop.")
                return
            # Kept so a menu the provider never answered doesn't swallow the
            # note the last activity left.
            note_before_menu = self.note
            blocked_key, blocked_note = self._repeat_block(entries)
            menu = build_main_menu(
                entries,
                note=self.note,
                now=app.clock(),
                notifications=app.notification_line(),
                blocked_key=blocked_key,
                blocked_note=blocked_note,
            )
            self.note = ""

            # Display the menu so the user can see the options.
            print(f"\n{'=' * 40}")
            print(menu.text)
            print(f"{'=' * 40}")

            result = await app.provider.generate(menu.text, schema=app.schemas.menu(menu.letters))

            if "error" in result:
                if is_transient_error(result["error"]):
                    # The provider is down, not broken. It has already been
                    # waited on inside the call and will be waited on again
                    # before the next one, so the agent holds at the menu until
                    # the provider comes back rather than tripping the breaker
                    # and ending a run that was only ever rate-limited.
                    print_system("Provider unavailable; holding at the menu")
                    app.status.set_activity("waiting for the provider")
                    self.note = note_before_menu
                    continue
                menu_failures += 1
                self.note = note_before_menu
                print_system(f"Menu generation failed ({result['error']})")
                if menu_failures >= MAX_CONSECUTIVE_MENU_FAILURES:
                    raise RuntimeError(
                        "The model failed to answer the menu "
                        f"{MAX_CONSECUTIVE_MENU_FAILURES} times in a row — check the provider."
                    )
                continue
            menu_failures = 0

            # Show the model's reasoning and choice.
            if result.get("thinking"):
                print(f"\nThinking: {result['thinking']}")
            choice_letter = result["choice"]
            activity = app.registry.get(menu.mapping[choice_letter])
            # get_menu_label, not menu_label: an activity whose entry changes
            # with the time of day (nap becoming "Go to bed") must be echoed
            # back as the thing that was actually on the menu.
            label = activity.get_menu_label(app.registry.ctx_for(activity))
            print(f"Choice: {choice_letter} — {label}")
            self.last_choice_key = activity.key
            self.note = await run_activity(app, activity)

        # loop budget reached (only used with --max-iterations)
        clear_crash_context(app)

    def _repeat_block(self, entries: list[dict[str, Any]]) -> tuple[str, str]:
        """Which activity is held back this turn, and the reason to show.

        Whatever was picked last turn, unless it says otherwise. Every module
        gets this for free, including ones installed later: the rule lives on
        the menu, not in any activity, and an activity only ever opts a single
        turn out of it through allow_repeat().
        """
        key = self.last_choice_key
        if not key or not any(entry["key"] == key for entry in entries):
            return "", ""
        try:
            activity = self.app.registry.get(key)
            ctx = self.app.registry.ctx_for(activity)
            if activity.allow_repeat(ctx):
                return "", ""
            return key, activity.repeat_blocked_note(ctx)
        except Exception as e:
            # A module that raises here loses the block, never the menu.
            print_system(f"activity '{key}' repeat check failed: {e}")
            return "", ""

    async def _budget_sleep(self) -> None:
        app = self.app
        seconds = app.provider.budget.seconds_until_reset()
        print_system(
            f"Daily token budget reached ({app.provider.budget.used} used). "
            f"Sleeping until the daily reset (~{int(seconds // 60)} min)."
        )
        app.status.set_activity("sleeping (token budget reached)")
        if app.daycycle is not None:
            await app.daycycle.budget_sleep(seconds)
        else:
            await app.sleep_fn(seconds)

    async def _graceful_pause(self) -> None:
        app = self.app
        print_system("Paused. The agent will resume at the main menu.")
        app.status.set_activity("paused")
        await app.save_now("pause")
        await app.control.wait_for_resume()
        if not app.control.stop_requested:
            print_system("Resumed.")

    async def _graceful_exit(self) -> None:
        app = self.app
        print_system("Stopping: saving state and exiting cleanly.")
        await app.save_now("stop")
        clear_crash_context(app)
        app.status.set_activity("stopped")
