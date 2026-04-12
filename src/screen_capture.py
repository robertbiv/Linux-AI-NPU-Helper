# SPDX-License-Identifier: GPL-3.0-or-later
"""Screen capture utilities.

Supports two backends:
- ``mss``   – fast, pure-Python, no external tools required (default)
- ``scrot`` – uses the external ``scrot`` command-line tool

Resource efficiency
-------------------
All heavy imports (``mss``, ``PIL``) are deferred to the moment of capture so
the module has zero import cost when idle.  Image bytes are returned as plain
``bytes`` objects; callers should delete or overwrite the reference as soon as
the bytes have been forwarded to the AI backend so memory is reclaimed by GC
without waiting for the next cycle.
"""

from __future__ import annotations

import io
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def capture(
    method: str = "mss",
    monitor: int = 0,
    jpeg_quality: int = 75,
) -> bytes:
    """Capture the screen and return JPEG image bytes.

    Parameters
    ----------
    method:
        ``"mss"`` (default) or ``"scrot"``.
    monitor:
        Monitor index.  ``0`` means the full virtual desktop (all monitors
        combined) when using mss; ``1`` is the primary physical monitor.
    jpeg_quality:
        JPEG compression quality (1 – 95).

    Returns
    -------
    bytes
        Raw JPEG bytes of the captured screen.
    """
    if method == "scrot":
        return _capture_scrot(jpeg_quality)
    return _capture_mss(monitor, jpeg_quality)


def _capture_mss(monitor: int, jpeg_quality: int) -> bytes:
    """Capture using the *mss* library."""
    try:
        import mss  # type: ignore[import]
        import mss.tools  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "mss is not installed.  Install it with: pip install mss"
        ) from exc

    from PIL import Image  # type: ignore[import]

    with mss.mss() as sct:
        monitors = sct.monitors  # index 0 = virtual desktop, 1..N = physical
        if monitor >= len(monitors):
            logger.warning(
                "Monitor index %d out of range (have %d); using 0.",
                monitor,
                len(monitors),
            )
            monitor = 0
        target = monitors[monitor]
        raw = sct.grab(target)
        img = Image.frombytes("RGB", raw.size, raw.rgb)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
    return buf.getvalue()


def _capture_scrot(jpeg_quality: int) -> bytes:
    """Capture using the external *scrot* tool."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        subprocess.run(
            ["scrot", str(tmp_path)],
            check=True,
            capture_output=True,
        )
        from PIL import Image  # type: ignore[import]

        img = Image.open(tmp_path).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
        return buf.getvalue()
    finally:
        tmp_path.unlink(missing_ok=True)


def capture_region(
    x: int,
    y: int,
    width: int,
    height: int,
    jpeg_quality: int = 75,
) -> bytes:
    """Capture a rectangular region of the screen and return JPEG bytes.

    Parameters
    ----------
    x, y:
        Top-left corner of the region.
    width, height:
        Dimensions of the region.
    jpeg_quality:
        JPEG compression quality (1 – 95).
    """
    try:
        import mss  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "mss is not installed.  Install it with: pip install mss"
        ) from exc

    from PIL import Image  # type: ignore[import]

    region = {"top": y, "left": x, "width": width, "height": height}
    with mss.mss() as sct:
        raw = sct.grab(region)
        img = Image.frombytes("RGB", raw.size, raw.rgb)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
    return buf.getvalue()


def image_to_base64(image_bytes: bytes) -> str:
    """Return the base64-encoded string of *image_bytes* (no data-URI prefix)."""
    import base64

    return base64.b64encode(image_bytes).decode("utf-8")


def load_image_as_jpeg(path: str | Path, jpeg_quality: int = 85) -> bytes:
    """Load an image file and convert it to JPEG bytes.

    Parameters
    ----------
    path:
        Path to any image format supported by Pillow.
    jpeg_quality:
        JPEG compression quality (1 – 95).
    """
    from PIL import Image  # type: ignore[import]

    img = Image.open(path).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality)
    return buf.getvalue()
