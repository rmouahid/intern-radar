import re
import shutil
import subprocess

import pytest

from intern_radar import __version__
from intern_radar.dashboard.app import Request
from intern_radar.dashboard.routes import (
    USERSCRIPT,
    Context,
    build_app,
    render_userscript,
)
from intern_radar.store import Store


def test_userscript_is_rendered_with_the_app_address():
    script = render_userscript("http://100.1.2.3:8787", "100.1.2.3")
    assert 'const BASE = "http://100.1.2.3:8787";' in script
    assert "// @connect      100.1.2.3" in script
    assert f"// @version      {__version__}" in script
    assert "__BASE__" not in script and "__HOST__" not in script
    matches = re.findall(r"// @match\s+(\S+)", script)
    assert set(matches) == {
        "https://job-boards.greenhouse.io/*",
        "https://job-boards.eu.greenhouse.io/*",
        "https://boards.greenhouse.io/*",
        "https://boards.eu.greenhouse.io/*",
        "https://jobs.lever.co/*",
        "https://jobs.eu.lever.co/*",
        "https://jobs.ashbyhq.com/*",
    }


def test_userscript_never_submits_or_touches_captchas():
    source = USERSCRIPT.read_text().lower()
    assert "captcha" not in source
    assert ".submit(" not in source and "requestsubmit" not in source
    # The only programmatic clicks are on radio choices.
    assert re.findall(r"\b(\w+)\.click\(\)", source) == ["choice"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_userscript_is_valid_javascript(tmp_path):
    path = tmp_path / "radar.user.js"
    path.write_text(render_userscript("http://x", "x"))
    subprocess.run(["node", "--check", str(path)], check=True)


def test_userscript_and_install_routes(tmp_path):
    db = str(tmp_path / "u.db")
    Store(db).close()
    app = build_app(Context(db))
    headers = {"host": "100.1.2.3:8787"}
    script = app.handle(Request("GET", "/radar.user.js", {}, {}, headers))
    assert script.content_type.startswith("text/javascript")
    assert b'const BASE = "http://100.1.2.3:8787";' in script.body
    page = app.handle(Request("GET", "/autofill", {}, {}, headers)).body.decode()
    assert (
        'href="http://100.1.2.3:8787/radar.user.js"' in page and "Userscripts" in page
    )
    more = app.handle(Request("GET", "/more", {})).body.decode()
    assert 'href="/autofill"' in more
