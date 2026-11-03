"""Termos e privacidade têm endereço próprio na interface (/ui/termos, /ui/privacidade)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import FRONTEND_CLIENT_ROUTES, mount_frontend


def _client(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>Valinor</title>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log(1)", encoding="utf-8")
    application = FastAPI()
    mount_frontend(application, tmp_path)
    return TestClient(application)


def test_client_routes_serve_the_index(tmp_path):
    client = _client(tmp_path)
    for slug in FRONTEND_CLIENT_ROUTES:
        response = client.get(f"/ui/{slug}")
        assert response.status_code == 200, slug
        assert "<title>Valinor</title>" in response.text


def test_static_assets_and_root_still_work(tmp_path):
    client = _client(tmp_path)
    assert client.get("/ui/").status_code == 200
    assert client.get("/ui/app.js").text == "console.log(1)"
    assert client.get("/ui/nao-existe").status_code == 404


def test_the_real_app_registers_the_routes_when_the_build_exists():
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    if any(path == "/ui" for path in paths):  # só quando frontend/dist existe
        assert "/ui/termos" in paths and "/ui/privacidade" in paths
