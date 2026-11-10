import pytest
from fastapi.testclient import TestClient

from optimizer.web import create_app
from test_scheduler import make

H = {"X-Requested-With": "hp-optimizer"}


@pytest.fixture
def app_opt(tmp_path):
    opt, sess, clock = make(tmp_path, "observe")
    return create_app(opt, allowed_ips=frozenset({"testclient"})), opt


def test_non_ingress_forbidden(tmp_path):
    opt, _, _ = make(tmp_path, "observe")
    c = TestClient(create_app(opt))  # default allowlist: 172.30.32.2 / 127.0.0.1 only
    assert c.get("/").status_code == 403
    assert c.post("/api/pause", headers=H).status_code == 403


def test_dashboard_and_actions(app_opt):
    app, opt = app_opt
    c = TestClient(app)
    opt.store.event("x", "<script>alert(1)</script>")
    r = c.get("/")
    assert r.status_code == 200 and "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text
    assert "no-store" in r.headers.get("Cache-Control", "")
    assert "default-src" in r.headers.get("Content-Security-Policy", "")
    assert c.post("/api/pause").status_code == 403          # missing CSRF header
    assert c.post("/api/pause", headers=H).status_code == 200 and opt.paused
    assert c.post("/api/resume", headers=H).status_code == 200 and not opt.paused
    assert c.post("/api/shutdown", headers=H).status_code == 404
    assert c.get("/api/status").json()["mode"] == "observe"
    assert c.get("/docs").status_code == 404
