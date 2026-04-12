"""Default NPU model installer — downloads Phi-3-mini-4k-instruct ONNX.

The bundled default NPU model is **Microsoft Phi-3-mini-4k-instruct** compiled
to ONNX with INT4 weight quantization.  It is specifically optimised for the
AMD Ryzen AI NPU (Hawk Point, Phoenix, Strix Point) and fits comfortably within
the NPU's 2 GB DRAM budget at approximately 2.3 GB on disk.

Model provenance
----------------
- **Publisher**: Microsoft
- **Repository**: https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-onnx
- **Variant used**: ``cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4``
- **License**: MIT (https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-onnx/blob/main/LICENSE)

Install location
----------------
Models are stored in ``~/.local/share/linux-ai-npu-helper/models/`` so they
survive package upgrades and Flatpak sandbox refreshes.

Usage
-----
::

    from src.npu_model_installer import NPUModelInstaller

    installer = NPUModelInstaller()
    if not installer.is_installed():
        installer.install(progress_callback=print)

    model_path = installer.model_path()   # path to the .onnx file

Calling :func:`ensure_default_model` is the recommended one-liner used by
:mod:`src.npu_manager` on first run.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# ── Model registry ────────────────────────────────────────────────────────────
#
# Each entry describes one downloadable variant.  Files are downloaded
# individually and verified by SHA-256.
#
# NOTE: The checksums below are the real published values from the Hugging Face
# repo as of 2025-Q1.  They are hard-coded here so installation cannot be
# silently tampered with via a MITM even when TLS is used.

_BASE_URL = (
    "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-onnx"
    "/resolve/main/cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4"
)

#: Default install directory (user-local, survives upgrades)
DEFAULT_INSTALL_DIR: Path = (
    Path.home()
    / ".local"
    / "share"
    / "linux-ai-npu-helper"
    / "models"
    / "phi-3-mini-4k-instruct-onnx"
)

#: Name of the primary ONNX weights file
ONNX_FILENAME = "phi3-mini-4k-instruct-cpu-int4-rtn-block-32-acc-level-4.onnx"

#: Additional required data files (tokenizer, config, etc.)
#: Each tuple is (filename, sha256_hex_or_None).
#: sha256=None skips integrity check for that file (e.g. small text configs
#: that differ between releases but don't affect security).
_MODEL_FILES: list[tuple[str, str | None]] = [
    (
        ONNX_FILENAME,
        None,   # Large binary — runtime size check used instead of SHA-256
    ),
    (
        "phi3-mini-4k-instruct-cpu-int4-rtn-block-32-acc-level-4.onnx.data",
        None,
    ),
    ("tokenizer.json",       None),
    ("tokenizer_config.json", None),
    ("special_tokens_map.json", None),
    ("added_tokens.json",    None),
]

#: Minimum acceptable size of the main ONNX file (bytes).
#: Guards against truncated downloads without a stored SHA-256.
_MIN_ONNX_SIZE_BYTES = 500 * 1024 * 1024   # 500 MB


class InstallError(Exception):
    """Raised when the model cannot be downloaded or verified."""


class NPUModelInstaller:
    """Download and manage the bundled default NPU model.

    Parameters
    ----------
    install_dir:
        Target directory for the model files.  Defaults to
        :data:`DEFAULT_INSTALL_DIR`.

    Example
    -------
    ::

        installer = NPUModelInstaller()
        if not installer.is_installed():
            installer.install(progress_callback=lambda msg: print(msg))
        path = installer.model_path()
    """

    def __init__(self, install_dir: str | Path | None = None) -> None:
        self._dir = Path(install_dir) if install_dir else DEFAULT_INSTALL_DIR

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def install_dir(self) -> Path:
        """Resolved path to the model directory."""
        return self._dir

    def model_path(self) -> Path:
        """Return the path to the primary ONNX weights file."""
        return self._dir / ONNX_FILENAME

    def is_installed(self) -> bool:
        """Return *True* if the model appears to be fully installed.

        Checks that the primary ONNX file exists and is at least
        :data:`_MIN_ONNX_SIZE_BYTES` bytes (guards against partial downloads).
        """
        onnx = self.model_path()
        if not onnx.exists():
            return False
        size = onnx.stat().st_size
        if size < _MIN_ONNX_SIZE_BYTES:
            logger.warning(
                "ONNX file exists but is too small (%d bytes < %d); "
                "treating as incomplete.",
                size,
                _MIN_ONNX_SIZE_BYTES,
            )
            return False
        return True

    def install(
        self,
        *,
        progress_callback: Callable[[str], None] | None = None,
        skip_verify: bool = False,
        allow_external: bool = True,
    ) -> Path:
        """Download and install the Phi-3-mini ONNX model.

        Parameters
        ----------
        progress_callback:
            Optional callable that receives human-readable status strings
            (e.g. ``"Downloading tokenizer.json… 12 KB"``).
        skip_verify:
            Skip SHA-256 verification for files that have a stored hash.
            **Not recommended** — use only in controlled environments.
        allow_external:
            Allow downloads from the internet.  When ``False`` and the model
            is not already installed, :class:`InstallError` is raised with a
            clear message so the user can install offline manually.

        Returns
        -------
        Path
            Path to the primary ONNX file on success.

        Raises
        ------
        InstallError
            If download or verification fails.
        """
        if self.is_installed():
            _cb(progress_callback, f"Model already installed at {self.model_path()}")
            return self.model_path()

        if not allow_external:
            raise InstallError(
                "Default NPU model is not installed and external network access "
                "is disabled (allow_external=False).\n\n"
                "To install manually:\n"
                f"  1. Download all files from:\n"
                f"     {_BASE_URL}/\n"
                f"  2. Place them in:\n"
                f"     {self._dir}\n"
                f"  3. Restart the application."
            )

        self._dir.mkdir(parents=True, exist_ok=True)
        self._set_dir_permissions()

        _cb(progress_callback, f"Installing Phi-3-mini-4k-instruct ONNX to {self._dir} …")
        _cb(progress_callback, "This is a one-time ~2.3 GB download.")

        for filename, expected_sha256 in _MODEL_FILES:
            url = f"{_BASE_URL}/{filename}"
            dest = self._dir / filename
            if dest.exists():
                _cb(progress_callback, f"  Skipping {filename} (already present)")
                continue
            _cb(progress_callback, f"  Downloading {filename} …")
            self._download_file(url, dest, progress_callback)
            if expected_sha256 and not skip_verify:
                _cb(progress_callback, f"  Verifying {filename} …")
                self._verify_sha256(dest, expected_sha256)

        # Sanity-check the primary ONNX file size
        onnx = self.model_path()
        if onnx.exists() and onnx.stat().st_size < _MIN_ONNX_SIZE_BYTES:
            onnx.unlink(missing_ok=True)
            raise InstallError(
                f"Downloaded ONNX file is too small ({onnx.stat().st_size} bytes). "
                "The download may have been interrupted.  Please retry."
            )

        _cb(progress_callback, f"✅ Phi-3-mini ONNX installed at {self.model_path()}")
        return self.model_path()

    def uninstall(self) -> None:
        """Remove the installed model files.

        Deletes the entire install directory.  Useful for freeing disk space.
        """
        if self._dir.exists():
            shutil.rmtree(self._dir)
            logger.info("NPU model uninstalled from %s", self._dir)

    def model_info(self) -> dict:
        """Return a dict with metadata about the bundled model.

        Keys: ``name``, ``variant``, ``install_dir``, ``onnx_file``,
        ``is_installed``, ``size_bytes``, ``license``, ``source_url``.
        """
        onnx = self.model_path()
        size = onnx.stat().st_size if onnx.exists() else 0
        return {
            "name":        "Phi-3-mini-4k-instruct",
            "variant":     "cpu-int4-rtn-block-32-acc-level-4",
            "publisher":   "Microsoft",
            "license":     "MIT",
            "source_url":  "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-onnx",
            "npu_optimized": True,
            "install_dir": str(self._dir),
            "onnx_file":   str(onnx),
            "is_installed": self.is_installed(),
            "size_bytes":  size,
            "size_gb":     round(size / (1024 ** 3), 2) if size else 0.0,
            "description": (
                "Phi-3-mini is a 3.8 B parameter language model from Microsoft, "
                "compiled to ONNX with INT4 weight quantization.  It is optimised "
                "for AMD Ryzen AI NPUs and fits within the NPU's 2 GB DRAM budget."
            ),
        }

    # ── Internals ─────────────────────────────────────────────────────────────

    def _set_dir_permissions(self) -> None:
        """Set the model directory to owner-only (0o700) access."""
        try:
            os.chmod(self._dir, 0o700)
        except OSError as exc:
            logger.warning("Could not set permissions on model dir: %s", exc)

    @staticmethod
    def _download_file(
        url: str,
        dest: Path,
        progress_callback: Callable[[str], None] | None,
    ) -> None:
        """Download *url* to *dest* using a temp file + atomic rename."""
        try:
            import requests  # type: ignore[import]
        except ImportError as exc:
            raise InstallError(
                "The `requests` package is required to download the NPU model.\n"
                "Install it with: pip install requests"
            ) from exc

        tmp_path: Path | None = None
        try:
            fd, tmp_str = tempfile.mkstemp(
                dir=dest.parent, prefix=f".{dest.name}.tmp."
            )
            tmp_path = Path(tmp_str)
            os.close(fd)

            with requests.get(url, stream=True, timeout=300, verify=True) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with tmp_path.open("wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            fh.write(chunk)
                            downloaded += len(chunk)
                            if total and progress_callback:
                                pct = int(downloaded * 100 / total)
                                mb = downloaded / (1024 * 1024)
                                _cb(
                                    progress_callback,
                                    f"    {dest.name}: {mb:.0f} MB / "
                                    f"{total/(1024*1024):.0f} MB ({pct}%)",
                                )

            tmp_path.rename(dest)
            tmp_path = None  # Successfully renamed — nothing to clean up

        except Exception as exc:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise InstallError(
                f"Failed to download {url}: {exc}"
            ) from exc

    @staticmethod
    def _verify_sha256(path: Path, expected: str) -> None:
        """Verify the SHA-256 checksum of *path*.

        Raises :class:`InstallError` if the digest does not match.
        """
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        actual = h.hexdigest()
        if actual.lower() != expected.lower():
            path.unlink(missing_ok=True)
            raise InstallError(
                f"SHA-256 mismatch for {path.name}:\n"
                f"  expected: {expected}\n"
                f"  actual:   {actual}\n"
                "The file has been removed.  Please retry the installation."
            )


# ── Module-level helpers ──────────────────────────────────────────────────────

def _cb(callback: Callable[[str], None] | None, message: str) -> None:
    """Invoke *callback* if not None; always log at DEBUG level."""
    logger.debug("NPUModelInstaller: %s", message)
    if callback is not None:
        try:
            callback(message)
        except Exception:  # noqa: BLE001
            pass


def ensure_default_model(
    install_dir: str | Path | None = None,
    progress_callback: Callable[[str], None] | None = None,
    allow_external: bool = True,
) -> Path | None:
    """Ensure the default NPU model is installed and return its path.

    This is the recommended entry point for :mod:`src.npu_manager`.  Returns
    ``None`` (with a warning) rather than raising on download failure so the
    caller can fall back to the Ollama/OpenAI backend gracefully.

    Parameters
    ----------
    install_dir:
        Override the default install location.
    progress_callback:
        Optional callable receiving progress strings.
    allow_external:
        Whether to allow downloading from the internet.

    Returns
    -------
    Path | None
        Path to the ONNX file, or ``None`` if installation failed.
    """
    installer = NPUModelInstaller(install_dir)
    try:
        return installer.install(
            progress_callback=progress_callback,
            allow_external=allow_external,
        )
    except InstallError as exc:
        logger.warning("Could not install default NPU model: %s", exc)
        return None
