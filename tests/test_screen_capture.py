import pytest
from unittest.mock import patch, MagicMock
from src.screen_capture import capture, _capture_mss, _capture_scrot, capture_region, image_to_base64, load_image_as_jpeg
import io

import sys

# Mock deferred imports so that they don't try to load actual native libraries
# and fail when running headless in CI
pil_mock = MagicMock()
pil_image_mock = MagicMock()
pil_mock.Image = pil_image_mock
sys.modules["PIL"] = pil_mock
sys.modules["PIL.Image"] = pil_image_mock
sys.modules["mss"] = MagicMock()

@patch("src.screen_capture._capture_scrot")
def test_capture_scrot(mock_scrot):
    capture(method="scrot", jpeg_quality=90)
    mock_scrot.assert_called_once_with(90)

@patch("src.screen_capture._capture_mss")
def test_capture_mss_default(mock_mss):
    capture()
    mock_mss.assert_called_once_with(0, 75)

def test_image_to_base64():
    assert image_to_base64(b"test") == "dGVzdA=="

@patch("subprocess.run")
@patch("tempfile.NamedTemporaryFile")
def test__capture_scrot_impl(mock_temp, mock_run):
    mock_temp.return_value.__enter__.return_value.name = "/tmp/fake.png"
    with patch("PIL.Image.open") as mock_img_open:
        mock_img = MagicMock()
        mock_img.convert.return_value = mock_img
        mock_img_open.return_value = mock_img

        _capture_scrot(75)

        mock_run.assert_called_once()
        mock_img.save.assert_called_once()

def test__capture_mss_impl():
    with patch("mss.mss") as mock_mss_cls, patch("PIL.Image.frombytes") as mock_frombytes:
        mock_sct = MagicMock()
        mock_sct.monitors = [{"width": 100}]
        mock_raw = MagicMock()
        mock_raw.size = (100, 100)
        mock_raw.rgb = b"fake_rgb"
        mock_sct.grab.return_value = mock_raw
        mock_mss_cls.return_value.__enter__.return_value = mock_sct

        mock_img = MagicMock()
        mock_frombytes.return_value = mock_img

        _capture_mss(0, 75)

        mock_sct.grab.assert_called_once_with({"width": 100})
        mock_img.save.assert_called_once()

def test__capture_mss_impl_out_of_range():
    with patch("mss.mss") as mock_mss_cls, patch("PIL.Image.frombytes") as mock_frombytes:
        mock_sct = MagicMock()
        mock_sct.monitors = [{"width": 100}]
        mock_raw = MagicMock()
        mock_raw.size = (100, 100)
        mock_raw.rgb = b"fake_rgb"
        mock_sct.grab.return_value = mock_raw
        mock_mss_cls.return_value.__enter__.return_value = mock_sct

        mock_img = MagicMock()
        mock_frombytes.return_value = mock_img

        _capture_mss(5, 75)

        mock_sct.grab.assert_called_once_with({"width": 100})
        mock_img.save.assert_called_once()

def test_capture_region():
    with patch("mss.mss") as mock_mss_cls, patch("PIL.Image.frombytes") as mock_frombytes:
        mock_sct = MagicMock()
        mock_raw = MagicMock()
        mock_raw.size = (100, 100)
        mock_raw.rgb = b"fake_rgb"
        mock_sct.grab.return_value = mock_raw
        mock_mss_cls.return_value.__enter__.return_value = mock_sct

        mock_img = MagicMock()
        mock_frombytes.return_value = mock_img

        capture_region(10, 20, 30, 40)

        mock_sct.grab.assert_called_once_with({"top": 20, "left": 10, "width": 30, "height": 40})
        mock_img.save.assert_called_once()

def test_load_image_as_jpeg():
    with patch("PIL.Image.open") as mock_img_open:
        mock_img = MagicMock()
        mock_img.convert.return_value = mock_img
        mock_img_open.return_value = mock_img

        load_image_as_jpeg("fake.png")
        mock_img_open.assert_called_once_with("fake.png")
        mock_img.save.assert_called_once()
