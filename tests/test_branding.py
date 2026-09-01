"""A marca Valinor precisa estar nos arquivos servidos pela plataforma."""

from __future__ import annotations

import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _png_ihdr(path: Path) -> tuple[int, int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    length, chunk = struct.unpack(">I4s", data[8:16])
    assert chunk == b"IHDR"
    assert length == 13
    width, height, _bit_depth, color_type = struct.unpack(">IIBB", data[16:26])
    return width, height, color_type


def test_logo_files_exist():
    assert (ROOT / "frontend" / "public" / "valinor-hero.webp").is_file()
    assert (ROOT / "frontend" / "public" / "valinor-mark.png").is_file()
    assert (ROOT / "frontend" / "public" / "favicon.png").is_file()
    assert (ROOT / "app" / "assets" / "valinor-mark.png").is_file()


def test_mark_is_the_transparent_tree_emblem():
    width, height, color_type = _png_ihdr(ROOT / "frontend" / "public" / "valinor-mark.png")
    assert color_type == 6  # RGBA — the official mark is keyed on white
    assert width >= 256 and height >= 256
    app_width, app_height, app_color = _png_ihdr(ROOT / "app" / "assets" / "valinor-mark.png")
    assert app_color == 6
    assert (app_width, app_height) == (width, height)
    fav_w, fav_h, fav_color = _png_ihdr(ROOT / "frontend" / "public" / "favicon.png")
    assert fav_color == 6
    assert fav_w == 32 and fav_h == 32
    styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    brand = styles.split(".brand-mark {", 1)[1].split("}", 1)[0]
    assert "object-fit: contain" in brand


def test_frontend_renders_the_valinor_mark():
    source = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "valinor-mark.png" in source
    assert "valinor-hero.webp" in source
    assert "Scale size=" not in source
    assert "favicon.png" in html
