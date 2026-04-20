# SPDX-License-Identifier: GPL-3.0-or-later
"""Model selector — list, choose, and validate AI models against NPU capabilities.

Supports Ollama and OpenAI-compatible backends.  For each model it evaluates
NPU compatibility and emits a human-readable warning when the model is unlikely
to run efficiently on the AMD Ryzen AI NPU.

All network calls respect the application's ``network.allow_external`` guard —
model listings are fetched only from the locally configured backend URL.

## Example
>>> selector = ModelSelector(config)
>>> models = selector.list_models()
>>> for m in models:
...     warn = selector.npu_warning(m)
...     print(m.name, "— WARNING:", warn if warn else "OK")
>>> selector.set_model("llama3.2:3b-instruct-q4_K_M")
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── NPU compatibility rules ───────────────────────────────────────────────────
#
# Compatibility levels:
#   "ok"      — known to work well on NPU (small, quantized ONNX)
#   "warn"    — may work with reduced performance (large or unquantized)
#   "no"      — will not run on NPU without custom ONNX export
#
# Rules are checked in order; first match wins.

_NPU_RULES: list[dict[str, Any]] = [
    # Explicit ONNX path — always fine (includes vision ONNX models)
    {"pattern": r"\.onnx$", "level": "ok",
     "reason": None},
    # ONNX vision models by known key — explicitly supported on NPU
    {"pattern": r"\b(phi-3-v|phi-3\.5-vision|florence-2|florence2|moondream2)\b",
     "level": "ok",
     "reason": None},
    # Very large models (>30 B params) — memory likely insufficient
    {"pattern": r"\b(70b|65b|40b|34b|33b)\b", "level": "no",
     "reason": "Models larger than ~30 B parameters typically exceed NPU memory limits. "
               "Use a quantized model ≤13 B (e.g. Q4_K_M) or run on CPU/GPU instead."},
    # Vision models without ONNX — need custom ONNX export to run on NPU
    {"pattern": r"\b(llava|bakllava|cogvlm|internvl|minicpm-v)\b",
     "level": "warn",
     "reason": "This vision model requires a custom ONNX export to run on the NPU. "
               "Use the bundled Phi-3-vision ONNX or another catalog model instead. "
               "Inference will fall back to the CPU/GPU backend."},
    # Medium models without quantization — may be slow
    {"pattern": r"\b(13b|14b|20b|24b)\b.*?(?!q[0-9])", "level": "warn",
     "reason": "Models in the 13–24 B range may be slow without aggressive quantization. "
               "Consider a Q4_K_M or Q5_K_M variant for better NPU throughput."},
    # Well-quantized small/medium models — good fit
    {"pattern": r"\b[0-9]b.*?q[0-9]|q[0-9].*?\b[0-9]b\b", "level": "ok",
     "reason": None},
    # Embedding-only models — not suitable for chat
    {"pattern": r"\b(embed|embedding|nomic-embed|mxbai-embed|all-minilm)\b", "level": "warn",
     "reason": "Embedding models are not designed for conversational use. "
               "They will work technically but will not produce natural language replies."},
    # Models explicitly requiring full-precision or large context
    {"pattern": r"\b(f16|f32|fp16|fp32|bf16)\b", "level": "warn",
     "reason": "Full-precision (f16/f32) models are significantly slower on NPU. "
               "Prefer a 4-bit or 8-bit quantized variant (e.g. Q4_K_M)."},
]


@dataclass
class ModelInfo:
    """Metadata about a single model available from the backend.

    Attributes
    name:
        Model identifier as returned by the backend (e.g. ``"llama3:8b-q4_K_M"``).
    size_bytes:
        Raw model size in bytes as reported by the backend (0 if unknown).
    family:
        Model family string (e.g. ``"llama"``), lower-cased.
    quantization:
        Quantization level string if detectable from the name (e.g. ``"q4_k_m"``).
    is_vision:
        ``True`` when the model is known to accept image inputs.
    raw:
        Full raw dict from the backend API for advanced use.
    """

    name: str
    size_bytes: int = 0
    family: str = ""
    quantization: str = ""
    is_vision: bool = False
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def size_gb(self) -> float:
        """Model size in gigabytes (0.0 if unknown)."""
        return self.size_bytes / (1024 ** 3) if self.size_bytes else 0.0

    def __str__(self) -> str:
        size = f"  {self.size_gb:.1f} GB" if self.size_gb else ""
        quant = f"  [{self.quantization}]" if self.quantization else ""
        vision = "  👁 vision" if self.is_vision else ""
        return f"{self.name}{size}{quant}{vision}"


def _parse_model_info(name: str, raw: dict) -> ModelInfo:
    """Extract structured metadata from a raw backend model record."""
    name_lower = name.lower()

    # Size
    size_bytes: int = raw.get("size", 0)
    if not size_bytes:
        # Ollama stores size under details.parameter_size sometimes
        details = raw.get("details", {})
        param_size = details.get("parameter_size", "")
        if isinstance(param_size, (int, float)):
            size_bytes = int(param_size)

    # Family
    family: str = raw.get("details", {}).get("family", "")
    if not family:
        # Guess from name
        for f in ("llama", "mistral", "gemma", "phi", "qwen", "deepseek",
                  "codellama", "vicuna", "falcon", "mpt", "starcoder"):
            if f in name_lower:
                family = f
                break

    # Quantization
    quant_match = re.search(r"\b(q[0-9](?:_k_[ms])?|f16|f32|bf16|int8)\b", name_lower)
    quantization: str = quant_match.group(1) if quant_match else (
        raw.get("details", {}).get("quantization_level", "")
    )

    # Vision
    is_vision = bool(re.search(
        r"\b(llava|bakllava|moondream|cogvlm|internvl|minicpm-v|phi-3-vision|vision)\b",
        name_lower,
    ))

    return ModelInfo(
        name=name,
        size_bytes=size_bytes,
        family=family,
        quantization=quantization,
        is_vision=is_vision,
        raw=raw,
    )


class ModelSelector:
    """List, select, and validate models for the configured AI backend.

    Args:
    config:
        The application :class:`~src.config.Config` object.

    Usage
    -----
    ::

        selector = ModelSelector(config)
        models   = selector.list_models()          # fetch from backend
        current  = selector.get_current_model()    # from config
        warning  = selector.npu_warning(models[0]) # None → ok
        selector.set_model("llama3.2:3b-q4_K_M")  # update config in-memory
    """

    def __init__(self, config: Any) -> None:  # noqa: ANN001
        self._config = config
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    # ── Query backend ─────────────────────────────────────────────────────────

    def list_models(self, timeout: int = 10) -> concurrent.futures.Future[list[ModelInfo]]:
        """Return a Future for all models available from the currently configured backend.

        Network calls are made only to the locally configured backend URL.
        Returns a Future containing an empty list (with a log warning) when the backend is
        unreachable rather than raising an exception.

        Args:
        timeout:
            Seconds to wait for the backend to respond.

        Returns:
        concurrent.futures.Future[list[ModelInfo]]
            Future that resolves to models sorted alphabetically by name.
        """
        def _fetch() -> list[ModelInfo]:
            backend = self._config.backend
            try:
                if backend == "ollama":
                    return self._list_ollama(timeout)
                elif backend == "openai":
                    return self._list_openai(timeout)
                elif backend == "npu":
                    return self._list_npu()
                else:
                    logger.warning("Unknown backend %r; cannot list models.", backend)
                    return []
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not list models from %r backend: %s", backend, exc)
                return []

        return self._executor.submit(_fetch)

    def _list_ollama(self, timeout: int) -> list[ModelInfo]:
        import requests
        from src.security import assert_local_url

        cfg = self._config.ollama
        base_url = cfg["base_url"].rstrip("/")
        url = f"{base_url}/api/tags"
        allow_external = self._config.network.get("allow_external", False)
        assert_local_url(url, allow_external)

        resp = requests.get(url, timeout=timeout, verify=True,
                            headers={"Connection": "close"})
        resp.raise_for_status()
        data = resp.json()
        models = [
            _parse_model_info(m["name"], m)
            for m in data.get("models", [])
        ]
        return sorted(models, key=lambda m: m.name)

    def _list_openai(self, timeout: int) -> list[ModelInfo]:
        import requests
        from src.security import assert_local_url

        cfg = self._config.openai
        base_url = cfg["base_url"].rstrip("/")
        api_key = cfg.get("api_key", "")
        url = f"{base_url}/models"
        allow_external = self._config.network.get("allow_external", False)
        assert_local_url(url, allow_external)

        headers = {"Connection": "close"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        resp = requests.get(url, timeout=timeout, verify=True, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        models = [
            _parse_model_info(m.get("id", ""), m)
            for m in data.get("data", [])
            if m.get("id")
        ]
        return sorted(models, key=lambda m: m.name)

    def _list_npu(self) -> list[ModelInfo]:
        """For the NPU backend, return a single entry for the configured model path."""
        model_path = self._config.npu.get("model_path", "")
        if not model_path:
            return []
        return [ModelInfo(name=model_path, raw={"path": model_path})]

    # ── Current model ─────────────────────────────────────────────────────────

    def get_current_model(self) -> str:
        """Return the model name currently configured for the active backend.

        Returns an empty string if no model is configured.
        """
        backend = self._config.backend
        if backend == "ollama":
            return self._config.ollama.get("model", "")
        elif backend == "openai":
            return self._config.openai.get("model", "")
        elif backend == "npu":
            return self._config.npu.get("model_path", "")
        return ""

    def set_model(self, model_name: str) -> None:
        """Update the in-memory config to use *model_name* for the active backend.

        This does **not** persist to disk automatically — call
        :meth:`~src.settings.SettingsManager.save` to write the change.

        Args:
        model_name:
            Model identifier accepted by the active backend.
        """
        backend = self._config.backend
        if backend == "ollama":
            self._config._data["ollama"]["model"] = model_name
        elif backend == "openai":
            self._config._data["openai"]["model"] = model_name
        elif backend == "npu":
            self._config._data["npu"]["model_path"] = model_name
        logger.info("Model updated to %r (backend=%r)", model_name, backend)

    # ── NPU compatibility check ────────────────────────────────────────────────

    def npu_warning(self, model: ModelInfo | str) -> str | None:
        """Return a warning string if *model* is unlikely to work well on NPU.

        Returns ``None`` when no issues are detected (the model should run
        fine on the AMD Ryzen AI NPU or the current backend is not NPU).

        Args:
        model:
            A :class:`ModelInfo` instance or a bare model name string.

        Returns:
        str | None
            Human-readable warning, or ``None`` if no warning applies.
        """
        if isinstance(model, str):
            model = ModelInfo(name=model)

        name_lower = model.name.lower()

        for rule in _NPU_RULES:
            if re.search(rule["pattern"], name_lower, re.IGNORECASE):
                level: str = rule["level"]
                reason: str | None = rule["reason"]
                if level == "no":
                    return f"⛔ Not recommended for NPU: {reason}"
                if level == "warn":
                    return f"⚠ NPU warning: {reason}"
                # level == "ok"
                return None

        # No rule matched — give a generic size-based check
        cfg_warn_gb: float = float(
            self._config.get("model_selector", {}).get("size_warning_gb", 13.0)
            if hasattr(self._config, "get") else 13.0
        )
        try:
            from src.npu_benchmark import probe_hardware
            hw = probe_hardware()
            if hw.ram_gb > 0:
                # NPU models share system RAM. Usually half of system RAM is a safe threshold
                cfg_warn_gb = max(4.0, hw.ram_gb * 0.5)

            # Speed/compute limits based on TOPS
            if hw.npu_tops > 0:
                if hw.npu_tops < 10:
                    cfg_warn_gb = min(cfg_warn_gb, 3.0)
                elif hw.npu_tops < 30:
                    cfg_warn_gb = min(cfg_warn_gb, 8.0)
        except Exception:
            pass
        if model.size_gb and model.size_gb > cfg_warn_gb:
            return (
                f"⚠ NPU warning: This model is {model.size_gb:.1f} GB which may "
                f"exceed NPU capabilities (threshold: {cfg_warn_gb:.0f} GB). "
                "Consider a smaller or more aggressively quantized variant."
            )

        return None

    # ── Convenience summary ────────────────────────────────────────────────────

    def model_summary(self, model: ModelInfo) -> dict[str, Any]:
        """Return a dict suitable for display in the settings UI.

        Keys: ``name``, ``size_gb``, ``family``, ``quantization``,
        ``is_vision``, ``npu_ok``, ``npu_warning``.
        """
        warning = self.npu_warning(model)
        return {
            "name":         model.name,
            "size_gb":      round(model.size_gb, 2),
            "family":       model.family,
            "quantization": model.quantization,
            "is_vision":    model.is_vision,
            "npu_ok":       warning is None,
            "npu_warning":  warning or "",
        }

    # ── NPU model suggestions ──────────────────────────────────────────────────

    @staticmethod
    def get_npu_suggestions() -> list[Any]:
        """Return the curated catalog of NPU-recommended models.

        Returns entries from :data:`~src.npu_model_installer.MODEL_CATALOG`
        sorted by NPU fit (best first).  Vision-capable models are listed
        before text-only models within the same fit tier.

        Returns:
        list[ModelCatalogEntry]
            Catalog entries rated ``"excellent"`` or ``"good"``.

        Example:
        ::

            for entry in ModelSelector.get_npu_suggestions():
                print(entry.name, entry.npu_fit_label, "vision=" + str(entry.is_vision))
        """
        from src.npu_model_installer import get_npu_suggestions
        return get_npu_suggestions()

    @staticmethod
    def get_vision_model_suggestions() -> list[Any]:
        """Return only vision-capable models from the catalog.

        Returns:
        list[ModelCatalogEntry]
            Vision-capable catalog entries sorted by NPU fit.

        Example

        ::

            for entry in ModelSelector.get_vision_model_suggestions():
                print(entry.name, entry.size_description)
        """
        from src.npu_model_installer import get_vision_models
        return get_vision_models()

    @staticmethod
    def get_default_npu_model_info() -> dict[str, Any]:
        """Return metadata for the default bundled NPU vision model.

        Returns:
        dict
            Same keys as :meth:`NPUModelInstaller.model_info`.
        """
        from src.npu_model_installer import NPUModelInstaller
        return NPUModelInstaller().model_info()
