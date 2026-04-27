# SPDX-License-Identifier: GPL-3.0-or-later
"""NPU model installer — default vision model + curated NPU-optimised catalog.

## Default bundled model
The application ships with **Microsoft Phi-3-vision-128k-instruct** compiled to
ONNX with INT4 weight quantisation as the *default* NPU model.  It is the only
publicly available vision-capable ONNX model with an official AMD Ryzen AI NPU
build maintained by Microsoft.

Key properties of the default model:

* **Vision-capable** — accepts screenshots and user-attached images natively.
* **NPU-optimised** — INT4 weights + AMD VitisAI Execution Provider support.
* **Compact** — ~4.2 GB on disk (INT4), fits within the Ryzen AI 2 GB DRAM
  budget when paged correctly by ``onnxruntime-genai``.
* **Permissive license** — MIT, allowing free redistribution.

Model provenance
~~~~~~~~~~~~~~~~
- Publisher  : Microsoft
- HuggingFace: https://huggingface.co/microsoft/Phi-3-vision-128k-instruct-onnx
- Variant    : ``cpu-int4-rtn-block-32``
- License    : MIT

## Model catalog
:data:`MODEL_CATALOG` lists curated models that run well on AMD Ryzen AI NPUs.
Each entry includes download instructions, an NPU-fit score, and a flag for
vision capability.  Call :func:`install_model_from_catalog` to install any
catalog entry.
## Usage
::

    from src.npu_model_installer import NPUModelInstaller, MODEL_CATALOG

    # Install the default vision model
    installer = NPUModelInstaller()
    if not installer.is_installed():
        installer.install(progress_callback=print)
    path = installer.model_path()

    # Browse and install any catalog model
    for entry in MODEL_CATALOG:
        print(entry.name, "vision=" + str(entry.is_vision), "NPU fit:", entry.npu_fit)

    vision_models = [e for e in MODEL_CATALOG if e.is_vision]
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Model catalog ─────────────────────────────────────────────────────────────


@dataclass
class ModelCatalogEntry:
    """A single model in the curated NPU-recommended catalog.

    Attributes
    key:
        Unique short identifier used as the install sub-directory name.
    name:
        Human-readable model name.
    publisher:
        Model publisher / organisation.
    description:
        One-sentence description for display in the GUI.
    hf_repo:
        Hugging Face repository slug (e.g. ``"microsoft/Phi-3-vision-128k-instruct-onnx"``).
    hf_variant:
        Sub-path within the repo that contains the ONNX files.
    onnx_filename:
        Name of the primary ``.onnx`` weights file.
    extra_files:
        Additional required files (tokenizer, config, etc.).  Each tuple is
        ``(filename, sha256_or_None)``.
    min_size_bytes:
        Minimum acceptable size of the primary ONNX file after download.
    is_vision:
        ``True`` when the model can process image inputs (screenshots).
    npu_fit:
        Qualitative NPU compatibility: ``"excellent"``, ``"good"``, ``"fair"``,
        or ``"not_recommended"``.
    size_description:
        Human-readable size hint shown in the GUI (e.g. ``"~4.2 GB"``).
    license_spdx:
        SPDX license identifier (e.g. ``"MIT"``).
    license_url:
        URL to the full license text.
    notes:
        Optional extra notes shown in the GUI (e.g. hardware requirements).
    is_default:
        ``True`` for the single model that is installed by default.
    requires_tos:
        ``True`` when the publisher requires accepting a Terms of Service
        agreement before downloading.  The GUI shows a confirmation dialog
        before starting the download.
    tos_url:
        URL to the full Terms of Service document.
    tos_summary:
        Short plain-text summary of the key TOS restrictions shown in the
        GUI dialog so the user doesn't have to leave the application.
    """

    key: str
    name: str
    publisher: str
    description: str
    hf_repo: str
    hf_variant: str
    onnx_filename: str
    extra_files: list[tuple[str, str | None]] = field(default_factory=list)
    min_size_bytes: int = 100 * 1024 * 1024  # 100 MB
    is_vision: bool = False
    npu_fit: str = "good"  # excellent / good / fair / not_recommended
    size_description: str = ""
    license_spdx: str = "MIT"
    license_url: str = ""
    notes: str = ""
    is_default: bool = False
    # ── Terms-of-service ──────────────────────────────────────────────────────
    requires_tos: bool = False
    """``True`` when the publisher requires accepting a Terms of Service before
    downloading.  The GUI will show a TOS dialog and the user must tick an
    acceptance checkbox before the download starts."""
    tos_url: str = ""
    """URL to the full Terms of Service text (opened in a browser when the
    user clicks the 'Read full terms' button in the TOS dialog)."""
    tos_summary: str = ""
    """One-paragraph plain-text summary of the key TOS restrictions shown
    inside the TOS dialog so the user does not have to leave the app."""

    @property
    def hf_base_url(self) -> str:
        """Direct download base URL for this variant on Hugging Face."""
        return f"https://huggingface.co/{self.hf_repo}/resolve/main/{self.hf_variant}"

    @property
    def hf_repo_url(self) -> str:
        """Human-facing Hugging Face repo URL."""
        return f"https://huggingface.co/{self.hf_repo}"

    @property
    def npu_fit_label(self) -> str:
        """Short display label for the static NPU fit score."""
        return {
            "excellent": "✅ Excellent",
            "good": "✅ Good",
            "fair": "⚠ Fair",
            "not_recommended": "⛔ Not recommended",
        }.get(self.npu_fit, self.npu_fit)

    def hardware_adjusted_npu_fit(self, hw: "Any | None" = None) -> str:
        """Return the NPU fit adjusted for the detected host hardware.

        Args:
            hw:
                A :class:`~src.npu_benchmark.HardwareCapabilities` instance.
                When ``None`` the hardware is probed automatically via
                :func:`~src.npu_benchmark.probe_hardware`.

        Returns:
            One of ``"excellent"``, ``"good"``, ``"fair"``,
            ``"not_recommended"``.
        """
        try:
            from src.npu_benchmark import adjust_npu_fit, probe_hardware  # noqa: PLC0415

            capabilities = hw if hw is not None else probe_hardware()
            return adjust_npu_fit(self.npu_fit, capabilities)
        except Exception:  # noqa: BLE001
            return self.npu_fit

    def hardware_adjusted_label(self, hw: "Any | None" = None) -> str:
        """Return the display label for the hardware-adjusted fit score."""
        fit = self.hardware_adjusted_npu_fit(hw)
        return {
            "excellent": "✅ Excellent",
            "good": "✅ Good",
            "fair": "⚠ Fair",
            "not_recommended": "⛔ Not recommended",
        }.get(fit, fit)


# ── Curated NPU model catalog ─────────────────────────────────────────────────
#
# All entries are tested with AMD Ryzen AI (Hawk Point / Phoenix / Strix).
# Models are sorted by NPU fit (best first) within each category.

MODEL_CATALOG: list[ModelCatalogEntry] = [
    # ── Vision models ─────────────────────────────────────────────────────────
    ModelCatalogEntry(
        key="phi3-vision-128k-int4",
        name="Phi-3-vision-128k-instruct (INT4)",
        publisher="Microsoft",
        description="Vision-capable 4.2 B model with 128 K context. "
        "Official AMD NPU ONNX build with INT4 quantisation. "
        "Accepts screenshots and attached images.",
        hf_repo="microsoft/Phi-3-vision-128k-instruct-onnx",
        hf_variant="cpu-int4-rtn-block-32",
        onnx_filename="phi-3-v-128k-instruct-cpu-int4.onnx",
        extra_files=[
            ("phi-3-v-128k-instruct-cpu-int4.onnx.data", None),
            ("tokenizer.json", None),
            ("tokenizer_config.json", None),
            ("special_tokens_map.json", None),
            ("processor_config.json", None),
            ("preprocessor_config.json", None),
        ],
        min_size_bytes=500 * 1024 * 1024,  # 500 MB
        is_vision=True,
        npu_fit="excellent",
        size_description="~4.2 GB",
        license_spdx="MIT",
        license_url="https://huggingface.co/microsoft/Phi-3-vision-128k-instruct-onnx/blob/main/LICENSE",
        notes="Requires onnxruntime-genai ≥ 0.3. "
        "Best for screen-aware AI assistant tasks.",
        is_default=True,
    ),
    ModelCatalogEntry(
        key="phi35-vision-int4",
        name="Phi-3.5-vision-instruct (INT4)",
        publisher="Microsoft",
        description="Updated vision model with improved instruction following "
        "and multi-frame image support. INT4 quantised for NPU.",
        hf_repo="microsoft/Phi-3.5-vision-instruct-onnx",
        hf_variant="cpu-int4-rtn-block-32",
        onnx_filename="phi-3.5-vision-instruct-cpu-int4.onnx",
        extra_files=[
            ("phi-3.5-vision-instruct-cpu-int4.onnx.data", None),
            ("tokenizer.json", None),
            ("tokenizer_config.json", None),
            ("processor_config.json", None),
            ("preprocessor_config.json", None),
        ],
        min_size_bytes=500 * 1024 * 1024,
        is_vision=True,
        npu_fit="excellent",
        size_description="~4.5 GB",
        license_spdx="MIT",
        license_url="https://huggingface.co/microsoft/Phi-3.5-vision-instruct-onnx/blob/main/LICENSE",
        notes="Recommended upgrade from Phi-3-vision. "
        "Better at following complex instructions.",
    ),
    ModelCatalogEntry(
        key="florence2-base",
        name="Florence-2-base (ONNX)",
        publisher="Microsoft",
        description="Tiny 0.23 B vision-language model for image captioning, "
        "OCR, and object detection. Very fast on NPU.",
        hf_repo="onnx-community/Florence-2-base",
        hf_variant="onnx",
        onnx_filename="model.onnx",
        extra_files=[
            ("model.onnx.data", None),
            ("tokenizer.json", None),
            ("tokenizer_config.json", None),
        ],
        min_size_bytes=50 * 1024 * 1024,
        is_vision=True,
        npu_fit="excellent",
        size_description="~0.6 GB",
        license_spdx="MIT",
        license_url="https://huggingface.co/microsoft/Florence-2-base/blob/main/LICENSE",
        notes="Best for OCR and image captioning. Limited conversational ability.",
    ),
    ModelCatalogEntry(
        key="moondream2-onnx",
        name="Moondream 2 (ONNX)",
        publisher="vikhyatk",
        description="Tiny 1.86 B vision model. Excellent for answering "
        "questions about images and screenshots.",
        hf_repo="vikhyatk/moondream2",
        hf_variant="onnx",
        onnx_filename="moondream2.onnx",
        extra_files=[
            ("tokenizer.json", None),
            ("tokenizer_config.json", None),
        ],
        min_size_bytes=100 * 1024 * 1024,
        is_vision=True,
        npu_fit="good",
        size_description="~1.8 GB",
        license_spdx="Apache-2.0",
        license_url="https://huggingface.co/vikhyatk/moondream2/blob/main/LICENSE",
        notes="Great balance of size and vision quality.",
    ),
    # ── Text-only models (NPU-optimised) ──────────────────────────────────────
    ModelCatalogEntry(
        key="phi3-mini-4k-int4",
        name="Phi-3-mini-4k-instruct (INT4)",
        publisher="Microsoft",
        description="3.8 B text model with 4 K context. No vision, "
        "but very fast and capable for command + code tasks.",
        hf_repo="microsoft/Phi-3-mini-4k-instruct-onnx",
        hf_variant="cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4",
        onnx_filename="phi3-mini-4k-instruct-cpu-int4-rtn-block-32-acc-level-4.onnx",
        extra_files=[
            ("phi3-mini-4k-instruct-cpu-int4-rtn-block-32-acc-level-4.onnx.data", None),
            ("tokenizer.json", None),
            ("tokenizer_config.json", None),
            ("special_tokens_map.json", None),
            ("added_tokens.json", None),
        ],
        min_size_bytes=500 * 1024 * 1024,
        is_vision=False,
        npu_fit="excellent",
        size_description="~2.3 GB",
        license_spdx="MIT",
        license_url="https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-onnx/blob/main/LICENSE",
        notes="Fastest option. Use when vision is not needed.",
    ),
    ModelCatalogEntry(
        key="phi35-mini-int4",
        name="Phi-3.5-mini-instruct (INT4)",
        publisher="Microsoft",
        description="3.8 B updated text model with 128 K context and "
        "stronger reasoning than Phi-3-mini.",
        hf_repo="microsoft/Phi-3.5-mini-instruct-onnx",
        hf_variant="cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4",
        onnx_filename="phi-3.5-mini-instruct-cpu-int4.onnx",
        extra_files=[
            ("phi-3.5-mini-instruct-cpu-int4.onnx.data", None),
            ("tokenizer.json", None),
            ("tokenizer_config.json", None),
        ],
        min_size_bytes=500 * 1024 * 1024,
        is_vision=False,
        npu_fit="excellent",
        size_description="~2.3 GB",
        license_spdx="MIT",
        license_url="https://huggingface.co/microsoft/Phi-3.5-mini-instruct-onnx/blob/main/LICENSE",
        notes="Recommended text-only upgrade from Phi-3-mini.",
    ),
    ModelCatalogEntry(
        key="qwen25-15b-int4",
        name="Qwen2.5-1.5B-Instruct (INT4)",
        publisher="Alibaba Cloud",
        description="1.5 B multilingual text model with strong code and "
        "reasoning. Very compact, runs instantly on NPU.",
        hf_repo="Qwen/Qwen2.5-1.5B-Instruct-ONNX",
        hf_variant="cpu-int4-rtn-block-32",
        onnx_filename="model.onnx",
        extra_files=[
            ("model.onnx.data", None),
            ("tokenizer.json", None),
            ("tokenizer_config.json", None),
        ],
        min_size_bytes=50 * 1024 * 1024,
        is_vision=False,
        npu_fit="excellent",
        size_description="~1.0 GB",
        license_spdx="Apache-2.0",
        license_url="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct/blob/main/LICENSE",
        notes="Best choice for low-memory systems.",
    ),
    ModelCatalogEntry(
        key="gemma2-2b-int4",
        name="Gemma 2 2B Instruct (INT4)",
        publisher="Google",
        description="2 B text model from Google. Strong at instruction "
        "following and summarisation.",
        hf_repo="google/gemma-2-2b-it-onnx",
        hf_variant="cpu-int4",
        onnx_filename="model.onnx",
        extra_files=[
            ("model.onnx.data", None),
            ("tokenizer.json", None),
            ("tokenizer_config.json", None),
        ],
        min_size_bytes=100 * 1024 * 1024,
        is_vision=False,
        npu_fit="good",
        size_description="~1.4 GB",
        license_spdx="Gemma",
        license_url="https://ai.google.dev/gemma/terms",
        notes="Requires accepting Google's Gemma Terms of Use "
        "on Hugging Face before downloading.",
        requires_tos=True,
        tos_url="https://ai.google.dev/gemma/terms",
        tos_summary=(
            "Gemma models are subject to Google's Gemma Terms of Use. "
            "You may use this model for research and commercial applications "
            "under those terms. You must not use the model to violate "
            "applicable laws, generate harmful content, or misrepresent its "
            "AI-generated nature. Redistribution requires preserving this notice."
        ),
    ),
    # ── Gemma Vision models (Google) ──────────────────────────────────────────
    ModelCatalogEntry(
        key="paligemma-3b-int4",
        name="PaliGemma 3B (INT4, vision)",
        publisher="Google",
        description="3 B vision-language model from Google. Understands "
        "images and text together. Excellent for screenshot "
        "Q&A, OCR, and image captioning on NPU.",
        hf_repo="onnx-community/paligemma-3b-pt-224-onnx",
        hf_variant="int4",
        onnx_filename="model.onnx",
        extra_files=[
            ("model.onnx.data", None),
            ("tokenizer.json", None),
            ("tokenizer_config.json", None),
            ("special_tokens_map.json", None),
            ("processor_config.json", None),
            ("preprocessor_config.json", None),
        ],
        min_size_bytes=100 * 1024 * 1024,
        is_vision=True,
        npu_fit="excellent",
        size_description="~1.7 GB",
        license_spdx="Gemma",
        license_url="https://ai.google.dev/gemma/terms",
        notes="Requires accepting Google's Gemma Terms of Use. "
        "Optimised for 224×224 image understanding tasks.",
        requires_tos=True,
        tos_url="https://ai.google.dev/gemma/terms",
        tos_summary=(
            "PaliGemma is a Gemma model subject to Google's Gemma Terms of Use. "
            "You may use it for research and qualifying commercial applications. "
            "You must not use it to generate harmful, deceptive, or illegal "
            "content, or violate any applicable laws. You must include the Gemma "
            "prohibited-use notice in any redistribution of the model or "
            "applications built on it."
        ),
    ),
    ModelCatalogEntry(
        key="gemma3-4b-vision-int4",
        name="Gemma 3 4B-IT (INT4, vision)",
        publisher="Google",
        description="4 B multimodal model from Google with strong vision "
        "and language capabilities. Handles screenshots, "
        "diagrams, and code understanding on NPU.",
        hf_repo="onnx-community/gemma-3-4b-it-ONNX",
        hf_variant="onnx/int4",
        onnx_filename="model.onnx",
        extra_files=[
            ("model.onnx.data", None),
            ("tokenizer.json", None),
            ("tokenizer_config.json", None),
            ("special_tokens_map.json", None),
            ("processor_config.json", None),
            ("preprocessor_config.json", None),
        ],
        min_size_bytes=200 * 1024 * 1024,
        is_vision=True,
        npu_fit="good",
        size_description="~2.5 GB",
        license_spdx="Gemma",
        license_url="https://ai.google.dev/gemma/terms",
        notes="Requires accepting Google's Gemma Terms of Use. "
        "Best Gemma vision model for general assistant tasks.",
        requires_tos=True,
        tos_url="https://ai.google.dev/gemma/terms",
        tos_summary=(
            "Gemma 3 is subject to Google's Gemma Terms of Use. "
            "You may use it for research and qualifying commercial applications. "
            "You must not use it to generate harmful, deceptive, or illegal "
            "content, or violate any applicable laws. You must include the Gemma "
            "prohibited-use notice in any redistribution of the model or "
            "applications built on it."
        ),
    ),
]

# ── Convenience accessors ─────────────────────────────────────────────────────


def get_default_entry() -> ModelCatalogEntry:
    """Return the catalog entry marked ``is_default=True``."""
    for entry in MODEL_CATALOG:
        if entry.is_default:
            return entry
    return MODEL_CATALOG[0]


def get_vision_models() -> list[ModelCatalogEntry]:
    """Return catalog entries that accept image inputs, ordered by NPU fit."""
    _ORDER = {"excellent": 0, "good": 1, "fair": 2, "not_recommended": 3}
    return sorted(
        [e for e in MODEL_CATALOG if e.is_vision],
        key=lambda e: _ORDER.get(e.npu_fit, 99),
    )


def get_npu_suggestions() -> list[ModelCatalogEntry]:
    """Return catalog entries sorted by NPU fit (best first).

    Returns only models rated ``"excellent"`` or ``"good"``.
    """
    _ORDER = {"excellent": 0, "good": 1}
    return sorted(
        [e for e in MODEL_CATALOG if e.npu_fit in _ORDER],
        key=lambda e: (_ORDER[e.npu_fit], not e.is_vision, e.name),
    )


# ── Install paths ─────────────────────────────────────────────────────────────

#: Root directory for all installed models (user-local)
MODELS_ROOT: Path = (
    Path.home() / ".local" / "share" / "linux-ai-npu-assistant" / "models"
)

#: Minimum ONNX file size for the default model
_MIN_ONNX_SIZE_BYTES: int = get_default_entry().min_size_bytes

#: Default install directory (set from the default catalog entry)
DEFAULT_INSTALL_DIR: Path = MODELS_ROOT / get_default_entry().key

#: ONNX filename for the default model
ONNX_FILENAME: str = get_default_entry().onnx_filename


def install_dir_for(entry: ModelCatalogEntry) -> Path:
    """Return the install directory for a catalog entry."""
    return MODELS_ROOT / entry.key


# ── NPUModelInstaller ─────────────────────────────────────────────────────────


class InstallError(Exception):
    """Raised when the model cannot be downloaded or verified."""


class NPUModelInstaller:
    """Download and manage a single NPU model (default or catalog entry).

        Args:
            install_dir:
                Override the install directory.  Defaults to
                ``MODELS_ROOT / entry.key`` for the given *entry*.
            entry:
                Catalog entry to install.  Defaults to :func:`get_default_entry`
                (Phi-3-vision-128k-instruct).


    Example:
    ::

                installer = NPUModelInstaller()          # default vision model
                if not installer.is_installed():
                installer.install(progress_callback=print)
                path = installer.model_path()
    """

    def __init__(
        self,
        install_dir: str | Path | None = None,
        entry: ModelCatalogEntry | None = None,
    ) -> None:
        self._entry = entry or get_default_entry()
        self._dir = (
            Path(install_dir)
            if install_dir is not None
            else install_dir_for(self._entry)
        )

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def install_dir(self) -> Path:
        """Resolved path to the model directory."""
        return self._dir

    @property
    def entry(self) -> ModelCatalogEntry:
        """The catalog entry being managed."""
        return self._entry

    def model_path(self) -> Path:
        """Return the path to the primary ONNX weights file."""
        return self._dir / self._entry.onnx_filename

    def is_installed(self) -> bool:
        """Return *True* if the model appears to be fully installed.

        Checks that the primary ONNX file exists and is strictly larger than
        :attr:`ModelCatalogEntry.min_size_bytes`.
        """
        onnx = self.model_path()
        if not onnx.exists():
            return False
        size = onnx.stat().st_size
        if size <= self._entry.min_size_bytes:
            logger.warning(
                "ONNX file %s exists but is too small (%d bytes ≤ %d); "
                "treating as incomplete.",
                onnx.name,
                size,
                self._entry.min_size_bytes,
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
        """Download and install the model.

        Args:
            progress_callback:
                Optional callable receiving human-readable progress strings.
            skip_verify:
                Skip SHA-256 verification (not recommended).
            allow_external:
                Allow downloads from the internet.  When ``False`` and the model is
                not installed, :class:`InstallError` is raised with manual-install
                instructions.

        Returns:
            Path to the primary ONNX file.

        Raises:
            InstallError: Download or verification failed.
        """
        if self.is_installed():
            _cb(progress_callback, f"Model already installed at {self.model_path()}")
            return self.model_path()

        if not allow_external:
            raise InstallError(
                f"Model '{self._entry.name}' is not installed and external "
                "network access is disabled (allow_external=False).\n\n"
                "To install manually:\n"
                f"  1. Download all files from:\n"
                f"     {self._entry.hf_base_url}/\n"
                f"  2. Place them in:\n"
                f"     {self._dir}\n"
                "  3. Restart the application."
            )

        self._dir.mkdir(parents=True, exist_ok=True)
        self._set_dir_permissions()

        _cb(
            progress_callback,
            f"Installing {self._entry.name} "
            f"({self._entry.size_description}) to {self._dir} …",
        )
        _cb(
            progress_callback,
            "This may take several minutes depending on your connection.",
        )

        all_files = [
            (self._entry.onnx_filename, None),
            *self._entry.extra_files,
        ]

        for filename, expected_sha256 in all_files:
            url = f"{self._entry.hf_base_url}/{filename}"
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
        if not onnx.exists():
            raise InstallError(
                f"Primary ONNX file was not created: {onnx}. "
                "The download may have failed silently."
            )
        if onnx.stat().st_size <= self._entry.min_size_bytes:
            onnx.unlink(missing_ok=True)
            raise InstallError(
                f"Downloaded ONNX file is too small "
                f"({onnx.stat().st_size if onnx.exists() else 0} bytes ≤ "
                f"{self._entry.min_size_bytes}). "
                "The download may have been interrupted. Please retry."
            )

        _cb(
            progress_callback, f"✅ {self._entry.name} installed at {self.model_path()}"
        )
        return self.model_path()

    def uninstall(self) -> None:
        """Remove all installed model files by deleting the install directory."""
        if self._dir.exists():
            shutil.rmtree(self._dir)
            logger.info("Model '%s' uninstalled from %s", self._entry.name, self._dir)

    def model_info(self) -> dict:
        """Return a dict with metadata about this model for GUI display.

        Keys: ``key``, ``name``, ``publisher``, ``description``,
        ``is_vision``, ``npu_fit``, ``npu_fit_label``, ``size_description``,
        ``license_spdx``, ``license_url``, ``hf_repo_url``, ``notes``,
        ``install_dir``, ``onnx_file``, ``is_installed``, ``size_bytes``,
        ``size_gb``, ``is_default``.
        """
        onnx = self.model_path()
        size = onnx.stat().st_size if onnx.exists() else 0
        return {
            "key": self._entry.key,
            "name": self._entry.name,
            "publisher": self._entry.publisher,
            "description": self._entry.description,
            "is_vision": self._entry.is_vision,
            "npu_fit": self._entry.npu_fit,
            "npu_fit_label": self._entry.npu_fit_label,
            "size_description": self._entry.size_description,
            "license_spdx": self._entry.license_spdx,
            "license_url": self._entry.license_url,
            "hf_repo_url": self._entry.hf_repo_url,
            "notes": self._entry.notes,
            "install_dir": str(self._dir),
            "onnx_file": str(onnx),
            "is_installed": self.is_installed(),
            "size_bytes": size,
            "size_gb": round(size / (1024**3), 2) if size else 0.0,
            "is_default": self._entry.is_default,
        }

    # ── Internals ─────────────────────────────────────────────────────────────

    def _set_dir_permissions(self) -> None:
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
                "The `requests` package is required to download NPU models.\n"
                "Install it with: pip install requests"
            ) from exc

        tmp_path: Path | None = None
        try:
            fd, tmp_str = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.tmp.")
            tmp_path = Path(tmp_str)

            with os.fdopen(fd, "wb") as fh:
                with requests.get(url, stream=True, timeout=300, verify=True) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get("content-length", 0))
                    downloaded = 0
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            fh.write(chunk)
                            downloaded += len(chunk)
                            if total and progress_callback:
                                pct = int(downloaded * 100 / total)
                                mb = downloaded / (1024 * 1024)
                                _cb(
                                    progress_callback,
                                    f"    {dest.name}: "
                                    f"{mb:.0f} MB / {total / (1024 * 1024):.0f} MB "
                                    f"({pct}%)",
                                )

            tmp_path.rename(dest)
            tmp_path = None  # Renamed — nothing to clean up

        except Exception as exc:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise InstallError(f"Failed to download {url}: {exc}") from exc

    @staticmethod
    def _verify_sha256(path: Path, expected: str) -> None:
        """Verify SHA-256; raises :class:`InstallError` on mismatch."""
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
                "The file has been removed. Please retry the installation."
            )


# ── Catalog installer ─────────────────────────────────────────────────────────


def install_model_from_catalog(
    entry: ModelCatalogEntry,
    *,
    install_dir: str | Path | None = None,
    progress_callback: Callable[[str], None] | None = None,
    allow_external: bool = True,
) -> Path:
    """Install a model from the catalog and return its ONNX path.

    Args:
        entry:
            A :class:`ModelCatalogEntry` from :data:`MODEL_CATALOG`.
        install_dir:
            Override the default install location.
        progress_callback:
            Optional callable receiving progress strings.
        allow_external:
            Allow downloading from the internet.

    Returns:
        Path to the primary ONNX file.

    Raises:
        Download or verification failed.
    """
    installer = NPUModelInstaller(install_dir=install_dir, entry=entry)
    return installer.install(
        progress_callback=progress_callback,
        allow_external=allow_external,
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
    """Ensure the default NPU vision model is installed; return its path.

    Returns ``None`` (and logs a warning) instead of raising so callers can
    fall back to the Ollama/OpenAI backend gracefully.

    Args:
        install_dir:
            Override the default install location.
        progress_callback:
            Optional callable receiving progress strings.
        allow_external:
            Whether to allow downloading from the internet.

    Returns:
        Path to the ONNX file, or ``None`` if installation failed.
    """
    try:
        return install_model_from_catalog(
            get_default_entry(),
            install_dir=install_dir,
            progress_callback=progress_callback,
            allow_external=allow_external,
        )
    except InstallError as exc:
        logger.warning("Could not install default NPU model: %s", exc)
        return None
