"""Activity discovery: builtins, drop-ins, compatibility gates."""

import textwrap

from elifelse.activities.base import Activity


class PingActivity(Activity):
    key = "ping"
    menu_label = "Ping"

    async def run(self, ctx):
        return "pong"


class FutureActivity(Activity):
    key = "future"
    menu_label = "From The Future"
    requires_base = ">=99.0"

    async def run(self, ctx):
        return ""


class NeedsKeyActivity(Activity):
    key = "needskey"
    menu_label = "Needs A Key"
    requires = ["api_token"]

    async def run(self, ctx):
        return ""


class HiddenActivity(Activity):
    key = "hidden"
    menu_label = "Hidden"

    def available(self, ctx):
        return False

    async def run(self, ctx):
        return ""


def test_builtins_load(app):
    app.registry.load_builtins()
    assert "journal" in app.registry.activities


def test_register_and_menu_entry(app):
    assert app.registry.register(PingActivity)
    entries = app.registry.menu_entries()
    assert [e["key"] for e in entries] == ["ping"]
    assert entries[0]["label"] == "Ping"


def test_duplicate_key_skipped(app):
    assert app.registry.register(PingActivity)
    assert not app.registry.register(PingActivity)
    assert any("already registered" in reason for _, reason in app.registry.skipped)


def test_incompatible_base_version_skipped(app):
    assert not app.registry.register(FutureActivity)
    name, reason = app.registry.skipped[-1]
    assert name == "future"
    assert "needs base >=99.0" in reason


def test_missing_required_config_key_skipped_with_key_named(app):
    assert not app.registry.register(NeedsKeyActivity)
    _, reason = app.registry.skipped[-1]
    assert "api_token" in reason
    assert "activities.needskey.api_token" in reason


def test_required_config_key_satisfied(app):
    app.config.activities["needskey"] = {"api_token": "abc"}
    assert app.registry.register(NeedsKeyActivity)


def test_unavailable_activity_hidden_from_menu(app):
    app.registry.register(PingActivity)
    app.registry.register(HiddenActivity)
    keys = [e["key"] for e in app.registry.menu_entries()]
    assert "ping" in keys
    assert "hidden" not in keys


def test_dropin_discovery(app):
    folder = app.paths.modules / "greeter"
    folder.mkdir(parents=True)
    (folder / "__init__.py").write_text(
        textwrap.dedent(
            """
            from elifelse.activities.base import Activity

            class GreeterActivity(Activity):
                key = "greeter"
                menu_label = "Say Hi"

                async def run(self, ctx):
                    return "hi"

            ACTIVITIES = [GreeterActivity]
            """
        ),
        encoding="utf-8",
    )
    app.registry.load_dropins(app.paths.modules)
    assert "greeter" in app.registry.activities


def test_broken_dropin_skipped_not_fatal(app):
    folder = app.paths.modules / "broken"
    folder.mkdir(parents=True)
    (folder / "__init__.py").write_text("raise RuntimeError('boom')", encoding="utf-8")
    app.registry.load_dropins(app.paths.modules)
    assert "broken" not in app.registry.activities
    assert any(name == "broken" for name, _ in app.registry.skipped)


async def test_failed_startup_disables_activity(app):
    class BadStart(Activity):
        key = "badstart"
        menu_label = "Bad Start"

        async def startup(self, ctx):
            raise RuntimeError("no service")

        async def run(self, ctx):
            return ""

    app.registry.register(BadStart)
    await app.registry.run_startups()
    assert "badstart" not in app.registry.activities
