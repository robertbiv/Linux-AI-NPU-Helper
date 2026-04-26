"""Tests for src/file_handler.py."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.file_handler import (
    classify_file,
    read_text_file,
    stream_text_file,
    read_image_file,
    load_attachment,
    _MAX_INLINE_TEXT_BYTES,
    _TEXT_CHUNK_SIZE,
)


class TestClassifyFile:
    def test_classify_image(self, tmp_path):
        p = tmp_path / "test.jpg"
        p.write_bytes(b"fake image data")
        assert classify_file(p) == "image"

        p = tmp_path / "test.png"
        p.write_bytes(b"fake image data")
        assert classify_file(p) == "image"

    def test_classify_text(self, tmp_path):
        p = tmp_path / "test.txt"
        p.write_text("hello world")
        assert classify_file(p) == "text"

        p = tmp_path / "test.py"
        p.write_text("print('hello')")
        assert classify_file(p) == "text"

    def test_classify_extra_text_types(self, tmp_path):
        # We use extensions that we know should match either text/* or _EXTRA_TEXT_TYPES
        # Note: .yaml might be application/yaml or application/x-yaml depending on system
        # .toml might not be recognized by mimetypes
        mapping = {
            "test.json": "text",
            "test.xml": "text",
            "test.js": "text",
            "test.sh": "text",
        }
        for name, expected in mapping.items():
            p = tmp_path / name
            p.write_text("content")
            assert classify_file(p) == expected, f"Failed for {name}"

    def test_classify_fallback_text(self, tmp_path):
        # Unknown extension (mimetypes returns None) but contains text
        p = tmp_path / "test.really_unknown_ext"
        p.write_text("just some text")
        with patch("mimetypes.guess_type", return_value=(None, None)):
            assert classify_file(p) == "text"

    def test_classify_fallback_binary(self, tmp_path):
        # Unknown extension but contains null byte
        p = tmp_path / "test.really_unknown_ext_bin"
        p.write_bytes(b"some data\x00 more data")
        with patch("mimetypes.guess_type", return_value=(None, None)):
            assert classify_file(p) == "binary"

    def test_classify_nonexistent_fallback(self):
        # Should handle OSError and return binary when mime is None
        with patch("mimetypes.guess_type", return_value=(None, None)):
            assert classify_file("nonexistent_file_xyz.really_unknown") == "binary"

    def test_classify_known_binary(self, tmp_path):
        p = tmp_path / "test.exe"
        p.write_bytes(b"MZ\x00\x01")
        # mimetypes might return application/x-msdownload or similar,
        # which is not in _EXTRA_TEXT_TYPES and doesn't start with image/ or text/
        assert classify_file(p) == "binary"


class TestReadTextFile:
    def test_read_small_file(self, tmp_path):
        p = tmp_path / "small.txt"
        content = "hello world"
        p.write_text(content)
        assert read_text_file(p) == content

    def test_read_encoding(self, tmp_path):
        p = tmp_path / "latin.txt"
        content = "héllo"
        p.write_text(content, encoding="latin-1")
        assert read_text_file(p, encoding="latin-1") == content

    def test_read_large_file_warning(self, tmp_path):
        p = tmp_path / "large.txt"
        # Create a file slightly larger than _MAX_INLINE_TEXT_BYTES
        content = "a" * (_MAX_INLINE_TEXT_BYTES + 1)
        p.write_text(content)

        with patch("src.file_handler.logger") as mock_logger:
            res = read_text_file(p)
            assert res == content
            mock_logger.warning.assert_called()
            args, _ = mock_logger.warning.call_args
            assert "consider using stream_text_file()" in args[0]


class TestStreamTextFile:
    def test_stream_chunks(self, tmp_path):
        p = tmp_path / "stream.txt"
        content = "abcdefghijklmnopqrstuvwxyz"
        p.write_text(content)

        # Use a small chunk size for testing
        chunks = list(stream_text_file(p, chunk_size=5))
        assert chunks == ["abcde", "fghij", "klmno", "pqrst", "uvwxy", "z"]
        assert "".join(chunks) == content

    def test_stream_default_chunk_size(self, tmp_path):
        p = tmp_path / "large_stream.txt"
        content = "a" * (_TEXT_CHUNK_SIZE + 100)
        p.write_text(content)

        chunks = list(stream_text_file(p))
        assert len(chunks) == 2
        assert len(chunks[0]) == _TEXT_CHUNK_SIZE
        assert len(chunks[1]) == 100
        assert "".join(chunks) == content


class TestReadImageFile:
    def test_read_image_success(self, tmp_path):
        mock_pil = MagicMock()
        mock_image_module = MagicMock()
        mock_pil.Image = mock_image_module

        mock_img = MagicMock()
        mock_image_module.open.return_value = mock_img
        mock_img.size = (100, 100)
        mock_img.convert.return_value = mock_img

        def fake_save(buf, format, quality, optimize):
            buf.write(b"fake jpeg data")

        mock_img.save.side_effect = fake_save

        p = tmp_path / "test.jpg"
        p.write_bytes(b"input data")

        with patch.dict(
            "sys.modules", {"PIL": mock_pil, "PIL.Image": mock_image_module}
        ):
            data = read_image_file(p)
            assert data == b"fake jpeg data"
            mock_img.close.assert_called_once()

    def test_read_image_resize(self, tmp_path):
        mock_pil = MagicMock()
        mock_image_module = MagicMock()
        mock_pil.Image = mock_image_module

        mock_img = MagicMock()
        mock_image_module.open.return_value = mock_img
        # Image larger than default 1920
        mock_img.size = (4000, 2000)
        mock_img.convert.return_value = mock_img
        mock_img.resize.return_value = mock_img

        p = tmp_path / "test.jpg"
        p.write_bytes(b"input data")

        with patch.dict(
            "sys.modules", {"PIL": mock_pil, "PIL.Image": mock_image_module}
        ):
            read_image_file(p, max_dimension=1000)

            # Check resize was called. 4000x2000 -> 1000x500
            mock_img.resize.assert_called_once()
            args, _ = mock_img.resize.call_args
            assert args[0] == (1000, 500)

    def test_read_image_no_pillow(self, tmp_path):
        # Force ImportError when PIL.Image is imported
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            p = tmp_path / "test.jpg"
            p.write_bytes(b"data")
            with pytest.raises(RuntimeError) as excinfo:
                read_image_file(p)
            assert "Pillow is not installed" in str(excinfo.value)


class TestLoadAttachment:
    def test_load_attachment_text(self, tmp_path):
        p = tmp_path / "test.txt"
        content = "hello"
        p.write_text(content)

        kind, data = load_attachment(p)
        assert kind == "text"
        assert data == content

    def test_load_attachment_binary(self, tmp_path):
        p = tmp_path / "test.dat"
        content = b"bin\x00data"
        p.write_bytes(content)

        kind, data = load_attachment(p)
        assert kind == "binary"
        assert data == content

    @patch("src.file_handler.read_image_file")
    def test_load_attachment_image(self, mock_read_image, tmp_path):
        p = tmp_path / "test.jpg"
        p.write_bytes(b"fake image")
        mock_read_image.return_value = b"jpeg data"

        kind, data = load_attachment(p)
        assert kind == "image"
        assert data == b"jpeg data"
        mock_read_image.assert_called_once()

    def test_load_attachment_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_attachment("nonexistent_file")
