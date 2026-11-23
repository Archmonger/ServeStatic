from __future__ import annotations

from servestatic.media_types import MediaTypes


def test_matched_filename():
    result = MediaTypes().get_type("static/apple-app-site-association")
    assert result == "application/json"


def test_matched_filename_cased():
    result = MediaTypes().get_type("static/Apple-App-Site-Association")
    assert result == "application/json"


def test_matched_extension():
    result = MediaTypes().get_type("static/app.js")
    assert result == "text/javascript"


def test_matched_extension_html():
    result = MediaTypes().get_type("static/index.html")
    assert result == "text/html"


def test_unmatched_extension():
    result = MediaTypes().get_type("static/app.example-unmatched")
    assert result == "application/octet-stream"


def test_extra_types():
    types = MediaTypes(extra_types={".js": "application/javascript"})
    result = types.get_type("static/app.js")
    assert result == "application/javascript"


def test_matched_extension_woff():
    result = MediaTypes().get_type("static/font.woff")
    assert result == "font/woff"
