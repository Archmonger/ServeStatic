from __future__ import annotations

from servestatic.utils import ensure_leading_trailing_slash


def test_none():
    assert ensure_leading_trailing_slash(None) == "/"


def test_empty():
    assert ensure_leading_trailing_slash("") == "/"


def test_slash():
    assert ensure_leading_trailing_slash("/") == "/"


def test_contents():
    assert ensure_leading_trailing_slash("/foo/") == "/foo/"


def test_leading():
    assert ensure_leading_trailing_slash("/foo") == "/foo/"


def test_trailing():
    assert ensure_leading_trailing_slash("foo/") == "/foo/"
