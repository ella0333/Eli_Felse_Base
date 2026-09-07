"""The dashboard's module surface, over real HTTP.

A module that ships a dashboard page gets a tab, a state endpoint, and its own
files served from its own folder. Nothing else in the module is reachable.
"""

import json
import textwrap
import urllib.error
import urllib.request

import pytest

from elifelse.dashboard import Dashboard


@pytest.fixture
def served(app):
    """A running dashboard on an ephemeral port, with one viewer module."""
    folder = app.paths.modules / "viewer"
    (folder / "dashboard").mkdir(parents=True)
    (folder / "dashboard" / "index.html").write_text("<h1>table</h1>", encoding="utf-8")
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

    dash = Dashboard(app, port=0)
    dash.start()
    # Port 0 means the OS picked one; the server knows which.
    port = dash._server.server_address[1]
    yield f"http://127.0.0.1:{port}"
    dash.stop()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.read().decode("utf-8")


def test_module_views_lists_the_tab(served):
    status, body = _get(f"{served}/api/module-views")
    assert status == 200
    assert json.loads(body) == [{"key": "viewer", "label": "Viewer"}]


def test_module_state_is_polled_by_key(served):
    _, body = _get(f"{served}/api/module-state?key=viewer")
    assert json.loads(body) == {"pot": 120}


def test_an_unknown_key_answers_empty_rather_than_erroring(served):
    status, body = _get(f"{served}/api/module-state?key=nobody")
    assert status == 200 and json.loads(body) == {}


def test_the_module_page_is_served_from_the_module_folder(served):
    status, body = _get(f"{served}/modules/viewer/")
    assert status == 200 and body == "<h1>table</h1>"


def test_the_rest_of_the_module_is_not_reachable(served):
    for escape in ("../secret.py", "..%2Fsecret.py", "dashboard/../../secret.py"):
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _get(f"{served}/modules/viewer/{escape}")
        assert excinfo.value.code == 404


def test_an_unknown_module_is_a_404(served):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{served}/modules/nobody/")
    assert excinfo.value.code == 404
