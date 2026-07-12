"""The main loop.

Each iteration:
1. write the crash-context file (a crash can resume from the last known state)
2. budget check — over the daily token cap, the agent auto-sleeps until reset
3. pause/stop control check (graceful shutdown path)
4. scheduler interrupts (bedtime menu, module pre-menu hooks)
5. build the main menu dynamically from every installed activity
6. send it with a menu schema whose enum is exactly the visible letters
7. dispatch the validated choice through the registry + shared lifecycle
8. the activity's note is shown at the top of the next menu
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from elifelse.loop.lifecycle import run_activity
from elifelse.loop.menus import build_main_menu
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

    async def main_loop(self, max_iterations: int | None = None, initial_note: str = "") -> None:
        app = self.app
        self.note = initial_note
        menu_failures = 0

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
            menu = build_main_menu(
                entries, note=self.note, now=app.clock(), notifications=app.notification_line()
            )
            self.note = ""

            # Display the menu so the user can see the options.
            print(f"\n{'=' * 40}")
            print(menu.text)
            print(f"{'=' * 40}")

            result = await app.provider.generate(menu.text, schema=app.schemas.menu(menu.letters))

            if "error" in result:
                menu_failures += 1
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
            print(f"Choice: {choice_letter} — {activity.menu_label}")
            self.note = await run_activity(app, activity)

        # loop budget reached (only used with --max-iterations)
        clear_crash_context(app)

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
