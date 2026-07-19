from pathlib import Path

from fastapi.testclient import TestClient

from junto.config import Settings
from junto.main import create_app
from tests.conftest import CapturingScheduler, ManualClock


def test_health_and_browser_route_fallback(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<main>Junto shell</main>", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
    app = create_app(
        app_settings=Settings(session_secret="test-session-secret"),
        scheduler=CapturingScheduler(),
        clock=ManualClock(),
        frontend_dist=tmp_path,
    )
    client = TestClient(app)
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/create").text == "<main>Junto shell</main>"
    assert client.get("/host/example").status_code == 200
    favicon = client.get("/favicon.svg")
    assert favicon.text == "<svg></svg>"
    assert favicon.headers["content-type"].startswith("image/svg+xml")
    unknown_api = client.get("/api/does-not-exist")
    assert unknown_api.status_code == 404
    assert unknown_api.headers["content-type"].startswith("application/json")
