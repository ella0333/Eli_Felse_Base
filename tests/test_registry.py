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


# ~~~ the activities.<key>.enabled switch ~~~
def test_disabled_activity_not_registered(app):
    app.config.activities["ping"] = {"enabled": False}
    assert not app.registry.register(PingActivity)
    assert "ping" not in app.registry.activities
    assert app.registry.skipped[-1] == ("ping", "disabled in config.yaml")


def test_enabled_true_and_absent_both_register(app):
    app.config.activities["ping"] = {"enabled": True}
    assert app.registry.register(PingActivity)
    assert app.registry.register(HiddenActivity)  # no section at all


def test_disabled_beats_missing_required_key(app):
    """Switching a module off silences the config key it would have needed."""
    app.config.activities["needskey"] = {"enabled": False}
    assert not app.registry.register(NeedsKeyActivity)
    _, reason = app.registry.skipped[-1]
    assert reason == "disabled in config.yaml"


def test_disabled_applies_to_dropins(app):
    app.config.activities["greeter"] = {"enabled": False}
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
    assert "greeter" not in app.registry.activities


def test_disabled_builtin_hidden_from_menu(app):
    app.config.activities["nap"] = {"enabled": False}
    app.registry.load_builtins()
    assert "nap" not in app.registry.activities
    assert "journal" in app.registry.activities


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


# ~~~ dashboard views ~~~
def _viewer_dropin(app, name="viewer"):
    """A drop-in shipping a dashboard page, plus a secret beside it."""
    folder = app.paths.modules / name
    (folder / "dashboard").mkdir(parents=True)
    (folder / "dashboard" / "index.html").write_text("<h1>table</h1>", encoding="utf-8")
    (folder / "dashboard" / "table.css").write_text("body{}", encoding="utf-8")
    (folder / "secret.py").write_text("TOKEN = 'hunter2'", encoding="utf-8")
    (folder / "__init__.py").write_text(
        textwrap.dedent(
            """
            from elifelse.activities.base import Activity

            class ViewerActivity(Activity):
                key = "viewer"
                menu_label = "Viewer"
                dashboard_view = "dashboard/index.html"

                def dashboard_state(self, ctx):
                    return {"pot": 120}

                async def run(self, ctx):
                    return ""

            ACTIVITIES = [ViewerActivity]
            """
        ),
        encoding="utf-8",
    )
    app.registry.load_dropins(app.paths.modules)
    return folder


def test_a_module_view_is_listed_and_served(app):
    _viewer_dropin(app)
    assert app.registry.dashboard_views() == [{"key": "viewer", "label": "Viewer"}]
    assert app.registry.dashboard_file("viewer", "").read_text(encoding="utf-8") == "<h1>table</h1>"
    assert app.registry.dashboard_file("viewer", "table.css") is not None


def test_module_state_comes_back_as_a_dict(app):
    _viewer_dropin(app)
    assert app.registry.dashboard_state("viewer") == {"pot": 120}
    # An activity with no view, and an unknown key, both answer empty.
    assert app.registry.dashboard_state("nobody") == {}


def test_a_module_state_error_never_reaches_the_http_thread(app):
    class Exploding(Activity):
        key = "exploding"
        menu_label = "Exploding"

        def dashboard_state(self, ctx):
            raise RuntimeError("boom")

        async def run(self, ctx):
            return ""

    app.registry.register(Exploding)
    assert app.registry.dashboard_state("exploding") == {}


def test_nothing_outside_the_dashboard_folder_is_reachable(app):
    """The module's own source sits one level up from the page it serves."""
    _viewer_dropin(app)
    for escape in (
        "../secret.py",
        "../__init__.py",
        r"..\secret.py",
        "dashboard/../../secret.py",
        "/etc/passwd",
    ):
        assert app.registry.dashboard_file("viewer", escape) is None


def test_a_view_that_is_not_shipped_is_not_listed(app):
    class Missing(Activity):
        key = "missing"
        menu_label = "Missing"
        dashboard_view = "dashboard/nope.html"

        async def run(self, ctx):
            return ""

    app.registry.register(Missing)
    assert app.registry.dashboard_views() == []
