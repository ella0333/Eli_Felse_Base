"""Activity discovery + registration.

Three install paths, all working at launch:
1. built-ins (ship with the base)
2. drop-in folders: data/modules/<name>/ with an __init__.py exposing
   ACTIVITIES = [ActivityClass, ...] — auto-discovered at startup
3. pip entry points in the "elifelse.activities" group

Every module declares `requires_base`; incompatible modules are SKIPPED with a
clear message instead of crashing mid-loop. Modules missing declared config
keys are also skipped, with the exact missing key named.

Trust tiers:
- built-in: ships with the base
- official: maintained by the base author (listed in trusted_modules.json)
- approved: community module reviewed and approved (listed in trusted_modules.json)
- community: installed but unreviewed
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from elifelse import __version__
from elifelse.activities.base import Activity
from elifelse.activities.ctx import ActivityContext
from elifelse.textutils import print_system

if TYPE_CHECKING:
    from elifelse.app import App

ENTRY_POINT_GROUP = "elifelse.activities"

# Trust manifest shipped with the base package.
_TRUST_MANIFEST: dict[str, Any] | None = None


def _load_trust_manifest() -> dict[str, Any]:
    global _TRUST_MANIFEST
    if _TRUST_MANIFEST is not None:
        return _TRUST_MANIFEST
    manifest_path = Path(__file__).resolve().parent.parent.parent.parent / "trusted_modules.json"
    if manifest_path.exists():
        try:
            _TRUST_MANIFEST = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            _TRUST_MANIFEST = {}
    else:
        _TRUST_MANIFEST = {}
    return _TRUST_MANIFEST


def module_tier(name: str) -> str:
    """Return 'official', 'approved', or 'community' for a module name."""
    manifest = _load_trust_manifest()
    if name in manifest.get("official", {}):
        return "official"
    if name in manifest.get("approved", {}):
        return "approved"
    return "community"


class ActivityRegistry:
    def __init__(self, app: App) -> None:
        self.app = app
        self.activities: dict[str, Activity] = {}
        self._contexts: dict[str, ActivityContext] = {}
        self.skipped: list[tuple[str, str]] = []  # (name, reason) — for diagnostics

    # ~~~ registration ~~~
    def register(self, activity: Activity | type[Activity], origin: str = "built-in") -> bool:
        """Register one activity. Returns False (and records why) if skipped."""
        if isinstance(activity, type):
            activity = activity()
        name = activity.key or activity.__class__.__name__

        if self._disabled(activity):
            self.skipped.append((name, "disabled in config.yaml"))
            print_system(
                f"Activity '{name}' is off (activities.{activity.key}.enabled: false)"
            )
            return False

        reason = self._compat_reason(activity)
        if reason:
            self.skipped.append((name, reason))
            print_system(f"Skipping activity '{name}': {reason}")
            return False

        for schema_name, schema in activity.schemas.items():
            self.app.schemas.register(f"{activity.key}.{schema_name}", schema)
        self.activities[activity.key] = activity
        self._contexts[activity.key] = ActivityContext(self.app, activity)
        if origin != "built-in":
            print_system(f"Loaded activity '{name}' ({origin})")
        return True

    def _disabled(self, activity: Activity) -> bool:
        """True when config.yaml turns this activity off.

        Checked before compatibility, so switching a module off also silences
        any complaint about the config keys it would otherwise require. Applies
        to built-ins and drop-in modules alike; absent means enabled.
        """
        section = self.app.config.activities.get(activity.key, {})
        return not section.get("enabled", True)

    def _compat_reason(self, activity: Activity) -> str | None:
        if not activity.key or not activity.menu_label:
            return "activity must define both 'key' and 'menu_label'"
        if activity.key in self.activities:
            return f"an activity with key '{activity.key}' is already registered"
        if activity.requires_base:
            try:
                spec = SpecifierSet(activity.requires_base)
            except InvalidSpecifier:
                return f"invalid requires_base specifier: {activity.requires_base!r}"
            if Version(__version__) not in spec:
                return (
                    f"needs base {activity.requires_base}, you have {__version__} — "
                    f"update the base or the module"
                )
        section = self.app.config.activities.get(activity.key, {})
        for req in activity.requires:
            if not section.get(req) and not os.environ.get(req):
                return (
                    f"missing required setting '{req}' — add it under "
                    f"'activities.{activity.key}.{req}' in config.yaml (or as an "
                    f"environment variable), or leave the module disabled"
                )
        return None

    # ~~~ discovery ~~~
    def load_builtins(self) -> None:
        from elifelse.activities.builtin import BUILTIN_ACTIVITIES

        for cls in BUILTIN_ACTIVITIES:
            self.register(cls, origin="built-in")

    def load_dropins(self, modules_dir: Path) -> None:
        """data/modules/<name>/__init__.py exposing ACTIVITIES = [...]."""
        if not modules_dir.exists():
            return
        for folder in sorted(modules_dir.iterdir()):
            init = folder / "__init__.py"
            if not folder.is_dir() or not init.exists():
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"elifelse_dropin_{folder.name}", init,
                    submodule_search_locations=[str(folder)],
                )
                assert spec and spec.loader
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
            except Exception as e:
                self.skipped.append((folder.name, f"failed to import: {e}"))
                print_system(f"Skipping module folder '{folder.name}': failed to import: {e}")
                continue
            activities = getattr(module, "ACTIVITIES", None)
            if not activities:
                self.skipped.append((folder.name, "no ACTIVITIES list in __init__.py"))
                print_system(f"Skipping module folder '{folder.name}': no ACTIVITIES list")
                continue
            tier = module_tier(folder.name)
            tier_label = {"official": "official", "approved": "approved", "community": "community - unreviewed"}[tier]
            print_system(f"Loading drop-in module '{folder.name}' ({tier_label})")
            for cls in activities:
                instance = cls() if isinstance(cls, type) else cls
                # The folder is the root a dashboard view and its assets are
                # resolved against. Only the loader knows it.
                instance.module_dir = folder.resolve()
                self.register(instance, origin=f"drop-in: {folder.name}")

    def load_entry_points(self) -> None:
        try:
            eps = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
        except TypeError:  # pragma: no cover - py3.10/3.11 compat shape
            eps = importlib.metadata.entry_points().get(ENTRY_POINT_GROUP, [])
        for ep in eps:
            try:
                obj = ep.load()
            except Exception as e:
                self.skipped.append((ep.name, f"failed to load entry point: {e}"))
                print_system(f"Skipping installed module '{ep.name}': {e}")
                continue
            tier = module_tier(ep.name)
            tier_label = {"official": "official", "approved": "approved", "community": "community - unreviewed"}[tier]
            print_system(f"Loading installed module '{ep.name}' ({tier_label})")
            classes = obj if isinstance(obj, list | tuple) else [obj]
            for cls in classes:
                self.register(cls, origin=f"pip: {ep.name}")

    def discover_all(self) -> None:
        self.load_builtins()
        self.load_dropins(self.app.paths.modules)
        self.load_entry_points()

    # ~~~ runtime ~~~
    def ctx_for(self, activity: Activity) -> ActivityContext:
        return self._contexts[activity.key]

    def get(self, key: str) -> Activity:
        return self.activities[key]

    def menu_entries(self) -> list[dict[str, Any]]:
        """(key, label, status, group) for every currently-available activity.

        `group` is the shared main-menu line an activity asks to sit under, or
        "" for its own line. The menu builder does the collapsing; the registry
        only reports what each activity declared.
        """
        entries = []
        for key, activity in self.activities.items():
            ctx = self._contexts[key]
            try:
                if not activity.available(ctx):
                    continue
                status = activity.get_status(ctx)
            except Exception as e:
                print_system(f"activity '{key}' status error: {e}")
                status = ""
            entries.append({
                "key": key,
                "label": activity.get_menu_label(ctx),
                "status": status,
                "group": activity.menu_group,
            })
        return entries

    # ~~~ dashboard ~~~
    def _module_root(self, activity: Activity) -> Path | None:
        """The folder an activity's dashboard files are resolved against."""
        if activity.module_dir is not None:
            return activity.module_dir
        module = sys.modules.get(activity.__class__.__module__)
        file = getattr(module, "__file__", None)
        return Path(file).resolve().parent if file else None

    def dashboard_views(self) -> list[dict[str, str]]:
        """One entry per activity offering a dashboard page.

        The dashboard turns each into a tab. An activity that declares a view
        it does not actually ship is left out rather than serving a broken tab.
        """
        views = []
        for key, activity in self.activities.items():
            if not activity.dashboard_view:
                continue
            root = self._module_root(activity)
            if root is None or not (root / activity.dashboard_view).is_file():
                print_system(f"activity '{key}' declares a dashboard view it does not ship")
                continue
            views.append({"key": key, "label": activity.menu_label})
        return views

    def dashboard_file(self, key: str, relative: str) -> Path | None:
        """Resolve a request for one of a module's dashboard files.

        Only the folder holding `dashboard_view` is reachable, never the rest
        of the module, and never anything outside it: the resolved path must
        still be inside that folder or this returns None. An empty `relative`
        means the view itself.
        """
        activity = self.activities.get(key)
        if activity is None or not activity.dashboard_view:
            return None
        root = self._module_root(activity)
        if root is None:
            return None
        view = (root / activity.dashboard_view).resolve()
        folder = view.parent
        if not relative:
            return view if view.is_file() else None
        try:
            target = (folder / relative).resolve()
            target.relative_to(folder)
        except (ValueError, OSError):
            return None
        return target if target.is_file() else None

    def dashboard_state(self, key: str) -> dict[str, Any]:
        """Live state for one module's page. Never raises into the HTTP thread."""
        activity = self.activities.get(key)
        if activity is None:
            return {}
        try:
            return activity.dashboard_state(self._contexts[key]) or {}
        except Exception as e:
            print_system(f"activity '{key}' dashboard state error: {e}")
            return {}

    async def run_startups(self) -> None:
        for key, activity in list(self.activities.items()):
            try:
                await activity.startup(self._contexts[key])
            except Exception as e:
                # A module that can't start is removed, not fatal.
                del self.activities[key]
                self.skipped.append((key, f"startup failed: {e}"))
                print_system(f"Activity '{key}' failed to start and was disabled: {e}")
