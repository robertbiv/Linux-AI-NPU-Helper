# SPDX-License-Identifier: GPL-3.0-or-later
"""File and image reading utilities.

## Resource efficiency
- All file I/O is streamed; large files are read in chunks and the caller
  receives text/bytes incrementally rather than as one giant buffer.
- Pillow is imported only at the point of image loading, not at module import.
- Callers are encouraged to ``del`` the returned bytes/string once consumed.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)

# Maximum size for a text file that will be returned as a single string.
# Files larger than this are streamed via :func:`stream_text_file`.
_TEXT_CHUNK_SIZE = 8 * 1024  # 8 KiB per chunk
_MAX_INLINE_TEXT_BYTES = 512 * 1024  # 512 KiB – warn above this

# MIME prefixes treated as "image"
_IMAGE_MIME_PREFIXES = ("image/",)

# Plain-text MIME types (beyond text/*)
_EXTRA_TEXT_TYPES = {
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-yaml",
    "application/toml",
    "application/x-sh",
}


def classify_file(path: str | Path) -> str:
    """Return ``'image'``, ``'text'``, or ``'binary'`` for *path*."""
    mime, _ = mimetypes.guess_type(str(path))
    if mime is None:
        # Fall back to reading a few bytes
        try:
            sample = Path(path).read_bytes()[:512]
            if b"\x00" in sample:
                return "binary"
            return "text"
        except OSError:
            return "binary"
    if any(mime.startswith(p) for p in _IMAGE_MIME_PREFIXES):
        return "image"
    if mime.startswith("text/") or mime in _EXTRA_TEXT_TYPES:
        return "text"
    return "binary"


# ── Text files ────────────────────────────────────────────────────────────────


def read_text_file(path: str | Path, encoding: str = "utf-8") -> str:
    """Read a text file and return its entire contents as a string.

    For large files use :func:`stream_text_file` instead to avoid holding the
    whole file in RAM.
    """
    p = Path(path)
    size = p.stat().st_size
    if size > _MAX_INLINE_TEXT_BYTES:
        logger.warning(
            "File %s is %.1f KiB; consider using stream_text_file() for "
            "large files to reduce memory usage.",
            path,
            size / 1024,
        )
    return p.read_text(encoding=encoding, errors="replace")


def stream_text_file(
    path: str | Path,
    encoding: str = "utf-8",
    chunk_size: int = _TEXT_CHUNK_SIZE,
) -> Generator[str, None, None]:
    """Yield the contents of a text file in chunks.

    Each chunk is at most *chunk_size* bytes decoded as *encoding*.  The file
    handle is open only for the duration of iteration.
    """
    with open(path, "r", encoding=encoding, errors="replace") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            yield chunk


# ── Image files ───────────────────────────────────────────────────────────────


def read_image_file(
    path: str | Path,
    jpeg_quality: int = 85,
    max_dimension: int = 1920,
) -> bytes:
    """Load an image file and return JPEG-compressed bytes.

    The image is down-scaled if either dimension exceeds *max_dimension* so
    that large photos don't consume excessive memory or network bandwidth.

    Args:
        path: Path to any image format supported by Pillow.
        jpeg_quality: JPEG quality (1–95).  Lower values reduce memory and transfer size.
        max_dimension: If the image is larger than this in either dimension it is resized
            while preserving aspect ratio before encoding.

    Returns:
        Raw JPEG bytes.  Delete the reference once forwarded to the AI.
    """
    import io  # stdlib – cheap

    # Deferred heavy import
    try:
        from PIL import Image  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is not installed.  Install it with: pip install Pillow"
        ) from exc

    img = Image.open(path)
    try:
        img = img.convert("RGB")

        # Resize if necessary to keep memory/bandwidth low
        w, h = img.size
        if max(w, h) > max_dimension:
            scale = max_dimension / max(w, h)
            new_size = (int(w * scale), int(h * scale))
            img = img.resize(new_size, Image.LANCZOS)
            logger.debug(
                "Resized image from %dx%d to %dx%d.", w, h, new_size[0], new_size[1]
            )

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
        return buf.getvalue()
    finally:
        # Always close the PIL image to release the file handle and its
        # internal pixel buffer immediately.
        img.close()


# ── Unified loader ────────────────────────────────────────────────────────────


def load_attachment(
    path: str | Path,
    jpeg_quality: int = 85,
    max_image_dimension: int = 1920,
) -> tuple[str, bytes | str]:
    """Load a user-supplied file and return ``(kind, data)``.

    ``kind`` is ``'image'``, ``'text'``, or ``'binary'``.
    ``data`` is JPEG bytes for images, a UTF-8 string for text, and raw bytes
    for binary files.

    Raises:
        FileNotFoundError: If *path* does not exist.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Attachment not found: {p}")

    kind = classify_file(p)
    logger.debug(
        "Loading attachment %s (kind=%s, size=%d B)", p, kind, p.stat().st_size
    )

    if kind == "image":
        data: bytes | str = read_image_file(
            p, jpeg_quality=jpeg_quality, max_dimension=max_image_dimension
        )
    elif kind == "text":
        data = read_text_file(p)
    else:
        data = p.read_bytes()

    return kind, data
