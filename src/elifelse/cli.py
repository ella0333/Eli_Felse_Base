"""The `elifelse` command: run / init / saves.

`elifelse run --provider mock --max-iterations N` works with ZERO config files —
defaults + a built-in persona — which is also the one-command end-to-end check.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from elifelse import __version__
from elifelse.config import Config, ConfigError, load_config
from elifelse.persona import Persona, load_persona
from elifelse.textutils import print_system

DEFAULT_PERSONA = Persona(
    name="Ada",
    pronouns="she/her",
    personality="Curious, upbeat, and a little dry. Likes small routines.",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="elifelse",
        description="Eli Felse Base Module — an always-on agent framework. The model only ever "
        "answers schema-constrained menus; Python does everything else.",
    )
    parser.add_argument("--version", action="version", version=f"elifelse {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="start the agent loop")
    run.add_argument("--config", default="config.yaml", help="path to config.yaml")
    run.add_argument("--persona", default="persona.yaml", help="path to persona.yaml")
    run.add_argument("--data-dir", default="", help="override the data directory")
    run.add_argument(
        "--provider", default="", choices=["", "mock", "openai_compat"],
        help="override provider.kind (mock = no model needed)",
    )
    run.add_argument(
        "--max-iterations", type=int, default=None,
        help="stop after N menu loops (default: run forever)",
    )
    run.add_argument(
        "--fresh", action="store_true",
        help="start fresh: ignore (and clear) any leftover crash context",
    )
    run.add_argument(
        "--load", default="",
        help="start from a named save (see 'elifelse saves')",
    )

    sub.add_parser("init", help="interactive setup wizard (creates config.yaml + persona.yaml)")
    saves = sub.add_parser("saves", help="list named saves")
    saves.add_argument("--config", default="config.yaml", help="path to config.yaml")
    saves.add_argument("--data-dir", default="", help="override the data directory")
    return parser


def _load(args: argparse.Namespace) -> tuple[Config, Persona]:
    config_path = Path(args.config)
    if config_path.exists():
        config = load_config(config_path)
    elif args.provider == "mock":
        config = Config()  # defaults are all a mock run needs
    else:
        raise ConfigError(
            f"Config file not found: {config_path}\n"
            "Run 'elifelse init' to create one, or try the no-setup demo:\n"
            "  elifelse run --provider mock --max-iterations 3"
        )

    if args.provider:
        config.provider.kind = args.provider
    if args.data_dir:
        config.data_dir = args.data_dir
    if config.provider.kind == "mock":
        # Mock runs are instant; a fake pacing delay would just be confusing,
        # and nobody wants the demo to spend 10 real minutes "eating".
        config.provider.response_delay_min = 0
        config.provider.response_delay_max = 0
        eat = config.activities.setdefault("eat", {})
        eat.setdefault("meal_minutes", 0)
        eat.setdefault("snack_minutes", 0)
        if config.day_cycle.enabled:
            # A mock demo started during the sleep window would answer the
            # bedtime menu and then REALLY sleep until morning.
            config.day_cycle.enabled = False
            print_system("mock: day cycle disabled (a mock run would sleep for real hours)")

    persona_path = Path(args.persona)
    if persona_path.exists():
        persona = load_persona(persona_path)
    elif config.provider.kind == "mock":
        persona = DEFAULT_PERSONA
    else:
        raise ConfigError(
            f"Persona file not found: {persona_path}\n"
            "Run 'elifelse init' to create one, or copy persona.example.yaml."
        )
    return config, persona


async def _run(args: argparse.Namespace) -> int:
    from elifelse.app import App
    from elifelse.state.startup import select_startup

    config, persona = _load(args)
    app = App(config, persona)
    await app.startup()
    note = select_startup(app, fresh=args.fresh, load=args.load)
    try:
        await app.run(max_iterations=args.max_iterations, initial_note=note)
    finally:
        await app.shutdown()
    return 0


def _list_saves(args: argparse.Namespace) -> int:
    from elifelse.paths import Paths
    from elifelse.state.saves import list_saves

    config_path = Path(args.config)
    config = load_config(config_path) if config_path.exists() else Config()
    if args.data_dir:
        config.data_dir = args.data_dir

    entries = list_saves(Paths(config.data_dir).saves)
    if not entries:
        print_system("no saves yet (the agent saves at sleep, pause, and stop)")
        return 0
    for e in entries:
        print_system(f"{e['name']:<20} saved {e['saved_at']}  [{e['file']}]")
    print_system("start from one with: elifelse run --load NAME")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    try:
        if args.command == "run":
            return asyncio.run(_run(args))
        if args.command == "init":
            from elifelse.wizard import run_wizard

            return run_wizard()
        if args.command == "saves":
            return _list_saves(args)
    except ConfigError as e:
        print(f"[config error] {e}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print_system("Interrupted (Ctrl+C). State can be resumed from the crash "
                     "context on next run.")
        return 130
    return 0
