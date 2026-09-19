"""Tests for HbkPageReader HTML decoding (UTF-8 BOM handling)."""

import io
import zipfile

from mcp_bsl_context.infrastructure.hbk.content_reader import HbkContext


def _reader_with(zip_file: zipfile.ZipFile) -> HbkContext:
    # read_page does not use the TOC structure; a stub is enough.
    return HbkContext(toc=None, zip_file=zip_file)


def _zip_with(entries: dict[str, bytes]) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf)


class TestHbkPageReader:
    def test_strips_utf8_bom(self):
        page = "\ufeff<html>Метод</html>".encode("utf-8")
        with _zip_with({"40e2f8bd6951/html/1.html": page}) as zf:
            reader = _reader_with(zf)
            result = reader.read_page("/40e2f8bd6951/html/1.html")
        assert result is not None
        assert not result.startswith("\ufeff")
        assert "Метод" in result

    def test_plain_utf8_without_bom(self):
        page = "<html>Метод</html>".encode("utf-8")
        with _zip_with({"page.html": page}) as zf:
            reader = _reader_with(zf)
            assert reader.read_page("/page.html") == "<html>Метод</html>"

    def test_case_insensitive_match(self):
        with _zip_with({"UpperCase.Html": b"\xef\xbb\xbf<meta>"}) as zf:
            reader = _reader_with(zf)
            assert reader.read_page("/uppercase.html") == "<meta>"

    def test_missing_page_returns_none(self):
        with _zip_with({}) as zf:
            reader = _reader_with(zf)
            assert reader.read_page("/nope.html") is None

    def test_empty_path_returns_none(self):
        with _zip_with({}) as zf:
            reader = _reader_with(zf)
            assert reader.read_page("") is None