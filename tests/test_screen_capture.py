from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.screen_capture import (
    _capture_mss,
    _capture_scrot,
    capture,
    capture_region,
    image_to_base64,
    load_image_as_jpeg,
)


@patch("src.screen_capture._capture_scrot")
@patch("src.screen_capture._capture_mss")
def test_capture_routing(mock_mss, mock_scrot):
    """Test that capture() routes to the correct backend."""
    mock_mss.return_value = b"mss_bytes"
    mock_scrot.return_value = b"scrot_bytes"

    # Default should be mss
    assert capture() == b"mss_bytes"
    mock_mss.assert_called_once_with(0, 75)
    mock_scrot.assert_not_called()

    mock_mss.reset_mock()

    # Specific arguments for mss
    assert capture(method="mss", monitor=1, jpeg_quality=80) == b"mss_bytes"
    mock_mss.assert_called_once_with(1, 80)
    mock_scrot.assert_not_called()

    mock_mss.reset_mock()

    # Scrot routing
    assert capture(method="scrot", jpeg_quality=90) == b"scrot_bytes"
    mock_scrot.assert_called_once_with(90)
    mock_mss.assert_not_called()


@patch("src.screen_capture.io.BytesIO")
def test_capture_mss_success(mock_bytes_io):
    """Test _capture_mss success path."""
    with patch.dict("sys.modules", {"mss": MagicMock(), "PIL": MagicMock()}) as mocked_mods:
        mock_mss_module = mocked_mods["mss"]
        mock_pil_module = mocked_mods["PIL"]

        # Setup mss mock
        mock_sct = MagicMock()
        mock_mss_module.mss.return_value.__enter__.return_value = mock_sct
        mock_sct.monitors = ["virtual", "monitor1"]

        mock_raw = MagicMock()
        mock_raw.size = (1920, 1080)
        mock_raw.rgb = b"rgb_data"
        mock_sct.grab.return_value = mock_raw

        # Setup PIL mock
        mock_img = MagicMock()
        mock_pil_module.Image.frombytes.return_value = mock_img

        # Setup io mock
        mock_buf = MagicMock()
        mock_buf.getvalue.return_value = b"jpeg_data"
        mock_bytes_io.return_value = mock_buf

        # Run
        result = _capture_mss(monitor=1, jpeg_quality=85)

        # Asserts
        assert result == b"jpeg_data"
        mock_sct.grab.assert_called_once_with("monitor1")
        mock_pil_module.Image.frombytes.assert_called_once_with("RGB", (1920, 1080), b"rgb_data")
        mock_img.save.assert_called_once_with(mock_buf, format="JPEG", quality=85, optimize=True)


@patch("src.screen_capture.io.BytesIO")
@patch("src.screen_capture.logger")
def test_capture_mss_monitor_fallback(mock_logger, mock_bytes_io):
    """Test _capture_mss fallback when monitor index is out of bounds."""
    with patch.dict("sys.modules", {"mss": MagicMock(), "PIL": MagicMock()}) as mocked_mods:
        mock_mss_module = mocked_mods["mss"]

        mock_sct = MagicMock()
        mock_mss_module.mss.return_value.__enter__.return_value = mock_sct
        mock_sct.monitors = ["virtual"]  # Only index 0 exists

        mock_buf = MagicMock()
        mock_buf.getvalue.return_value = b"jpeg_data"
        mock_bytes_io.return_value = mock_buf

        # Call with out of bounds monitor (1)
        _capture_mss(monitor=1, jpeg_quality=75)

        # Should log warning and fallback to monitor 0 ("virtual")
        mock_logger.warning.assert_called_once()
        mock_sct.grab.assert_called_once_with("virtual")


def test_capture_mss_import_error():
    """Test _capture_mss raises RuntimeError when mss is not installed."""
    with patch.dict("sys.modules", {"mss": None}):
        with pytest.raises(RuntimeError, match="mss is not installed"):
            _capture_mss(monitor=0, jpeg_quality=75)


@patch("src.screen_capture.subprocess.run")
@patch("tempfile.NamedTemporaryFile")
@patch("src.screen_capture.io.BytesIO")
def test_capture_scrot_success(mock_bytes_io, mock_tempfile, mock_run):
    """Test _capture_scrot success path."""
    with patch.dict("sys.modules", {"PIL": MagicMock()}) as mocked_mods:
        mock_pil_module = mocked_mods["PIL"]

        # Setup tempfile
        mock_tmp = MagicMock()
        mock_tmp.name = "/tmp/fake.png"
        mock_tempfile.return_value.__enter__.return_value = mock_tmp

        # Setup Path mock for unlink check
        with patch("src.screen_capture.Path") as mock_path_cls:
            mock_path_obj = MagicMock()
            mock_path_obj.__str__.return_value = "/tmp/fake.png"
            mock_path_cls.return_value = mock_path_obj

            # Setup PIL
            mock_img = MagicMock()
            mock_pil_module.Image.open.return_value.convert.return_value = mock_img

            # Setup io
            mock_buf = MagicMock()
            mock_buf.getvalue.return_value = b"scrot_jpeg"
            mock_bytes_io.return_value = mock_buf

            # Run
            result = _capture_scrot(jpeg_quality=80)

            # Asserts
            assert result == b"scrot_jpeg"
            mock_run.assert_called_once_with(
                ["scrot", "/tmp/fake.png"],
                check=True,
                capture_output=True,
            )
            mock_img.save.assert_called_once_with(mock_buf, format="JPEG", quality=80, optimize=True)
            mock_path_obj.unlink.assert_called_once_with(missing_ok=True)


@patch("src.screen_capture.subprocess.run")
@patch("tempfile.NamedTemporaryFile")
def test_capture_scrot_cleanup_on_error(mock_tempfile, mock_run):
    """Test _capture_scrot unlinks temp file even if subprocess fails."""
    mock_tmp = MagicMock()
    mock_tmp.name = "/tmp/fake.png"
    mock_tempfile.return_value.__enter__.return_value = mock_tmp

    mock_run.side_effect = Exception("Subprocess failed")

    with patch("src.screen_capture.Path") as mock_path_cls:
        mock_path_obj = MagicMock()
        mock_path_cls.return_value = mock_path_obj

        with pytest.raises(Exception, match="Subprocess failed"):
            _capture_scrot(jpeg_quality=75)

        mock_path_obj.unlink.assert_called_once_with(missing_ok=True)


@patch("src.screen_capture.io.BytesIO")
def test_capture_region_success(mock_bytes_io):
    """Test capture_region success path."""
    with patch.dict("sys.modules", {"mss": MagicMock(), "PIL": MagicMock()}) as mocked_mods:
        mock_mss_module = mocked_mods["mss"]
        mock_pil_module = mocked_mods["PIL"]

        mock_sct = MagicMock()
        mock_mss_module.mss.return_value.__enter__.return_value = mock_sct

        mock_raw = MagicMock()
        mock_raw.size = (100, 200)
        mock_raw.rgb = b"rgb"
        mock_sct.grab.return_value = mock_raw

        mock_img = MagicMock()
        mock_pil_module.Image.frombytes.return_value = mock_img

        mock_buf = MagicMock()
        mock_buf.getvalue.return_value = b"region_jpeg"
        mock_bytes_io.return_value = mock_buf

        result = capture_region(10, 20, 100, 200, jpeg_quality=90)

        assert result == b"region_jpeg"
        mock_sct.grab.assert_called_once_with({"top": 20, "left": 10, "width": 100, "height": 200})
        mock_img.save.assert_called_once_with(mock_buf, format="JPEG", quality=90, optimize=True)


def test_capture_region_import_error():
    """Test capture_region raises RuntimeError when mss is not installed."""
    with patch.dict("sys.modules", {"mss": None}):
        with pytest.raises(RuntimeError, match="mss is not installed"):
            capture_region(0, 0, 100, 100)


def test_image_to_base64():
    """Test image_to_base64 conversion."""
    result = image_to_base64(b"hello")
    assert result == "aGVsbG8="


@patch("src.screen_capture.io.BytesIO")
def test_load_image_as_jpeg(mock_bytes_io):
    """Test load_image_as_jpeg success path."""
    with patch.dict("sys.modules", {"PIL": MagicMock()}) as mocked_mods:
        mock_pil_module = mocked_mods["PIL"]

        mock_img = MagicMock()
        mock_pil_module.Image.open.return_value.convert.return_value = mock_img

        mock_buf = MagicMock()
        mock_buf.getvalue.return_value = b"loaded_jpeg"
        mock_bytes_io.return_value = mock_buf

        result = load_image_as_jpeg("fake/path.png", jpeg_quality=85)

        assert result == b"loaded_jpeg"
        mock_pil_module.Image.open.assert_called_once_with("fake/path.png")
        mock_pil_module.Image.open.return_value.convert.assert_called_once_with("RGB")
        mock_img.save.assert_called_once_with(mock_buf, format="JPEG", quality=85)
