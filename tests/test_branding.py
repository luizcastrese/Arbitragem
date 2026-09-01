"""A marca Valinor precisa estar nos arquivos servidos pela plataforma."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_logo_files_exist():
    assert (ROOT / "frontend" / "public" / "valinor-hero.webp").is_file()
    assert (ROOT / "frontend" / "public" / "valinor-mark.png").is_file()
    assert (ROOT / "frontend" / "public" / "favicon.png").is_file()
    assert (ROOT / "app" / "assets" / "valinor-mark.png").is_file()


def test_frontend_renders_the_valinor_mark():
    source = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'valinor-mark.png' in source
    assert 'valinor-hero.webp' in source
    assert "Scale size=" not in source
    assert 'favicon.png' in html
