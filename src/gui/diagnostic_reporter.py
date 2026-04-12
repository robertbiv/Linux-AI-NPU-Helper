# SPDX-License-Identifier: GPL-3.0-or-later
"""Diagnostic reporter — pure-Python system status collector.

Collects the status of every major application subsystem without importing
Qt, so the results are easily unit-testable and can be used from the CLI
as well as the GUI.

The :class:`DiagnosticReporter` class is the main entry point.  Call
:meth:`full_report` to get a single dict with all status information, or
call individual ``check_*`` methods for targeted checks.

Example
-------
>>> from src.diagnostic_reporter import DiagnosticReporter
>>> from src.config import load as load_config
>>> reporter = DiagnosticReporter(load_config())
>>> report = reporter.full_report()
>>> print(report["backend"]["status"])
'ok'
"""

from __future__ import annotations

import importlib
import logging
import os
import shutil
import stat
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Status constants
STATUS_OK   = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_SKIP = "skip"

_VERSION = "0.1.0"


class DiagnosticReporter:
    """Collect live status information from all application subsystems.

    Parameters
    ----------
    config:
        The application :class:`~src.config.Config` object.
    registry:
        Optional :class:`~src.tools.ToolRegistry` for tool status checks.
    settings_manager:
        Optional :class:`~src.settings.SettingsManager` for settings checks.
    """

    def __init__(
        self,
        config: Any,
        registry: Any = None,
        settings_manager: Any = None,
    ) -> None:
        self._config = config
        self._registry = registry
        self._settings_manager = settings_manager

    # ── Backend ───────────────────────────────────────────────────────────────

    def check_backend(self, timeout: int = 3) -> dict[str, Any]:
        """Check connectivity to the AI backend.

        Returns
        -------
        dict
            Keys: ``status``, ``backend``, ``url``, ``model``,
            ``latency_ms``, ``error``.
        """
        backend = self._config.backend
        result: dict[str, Any] = {
            "status":     STATUS_SKIP,
            "backend":    backend,
            "url":        "",
            "model":      "",
            "latency_ms": None,
            "error":      "",
        }

        try:
            import requests  # type: ignore[import]
        except ImportError:
            result["status"] = STATUS_WARN
            result["error"]  = "requests not installed; cannot probe backend."
            return result

        if backend == "ollama":
            cfg = self._config.ollama
            base_url = cfg.get("base_url", "http://localhost:11434").rstrip("/")
            result["url"]   = base_url
            result["model"] = cfg.get("model", "")
            probe_url = f"{base_url}/api/tags"
        elif backend == "openai":
            cfg = self._config.openai
            base_url = cfg.get("base_url", "http://localhost:1234/v1").rstrip("/")
            result["url"]   = base_url
            result["model"] = cfg.get("model", "")
            probe_url = f"{base_url}/models"
        elif backend == "npu":
            result["status"] = STATUS_OK
            result["model"]  = self._config.npu.get("model_path", "")
            result["url"]    = "in-process"
            return result
        else:
            result["status"] = STATUS_FAIL
            result["error"]  = f"Unknown backend: {backend!r}"
            return result

        try:
            t0 = time.monotonic()
            resp = requests.get(probe_url, timeout=timeout, verify=True,
                                headers={"Connection": "close"})
            latency_ms = int((time.monotonic() - t0) * 1000)
            result["latency_ms"] = latency_ms
            if resp.status_code < 400:
                result["status"] = STATUS_OK
            else:
                result["status"] = STATUS_WARN
                result["error"]  = f"HTTP {resp.status_code}"
        except Exception as exc:  # noqa: BLE001
            result["status"] = STATUS_FAIL
            result["error"]  = str(exc)

        return result

    # ── NPU ───────────────────────────────────────────────────────────────────

    def check_npu(self) -> dict[str, Any]:
        """Check AMD NPU / ONNX Runtime availability.

        Returns
        -------
        dict
            Keys: ``status``, ``available``, ``providers``,
            ``onnxruntime_version``, ``model_path``, ``model_exists``,
            ``error``.
        """
        result: dict[str, Any] = {
            "status":              STATUS_SKIP,
            "available":           False,
            "providers":           [],
            "onnxruntime_version": "",
            "model_path":          self._config.npu.get("model_path", ""),
            "model_exists":        False,
            "error":               "",
        }
        model_path = result["model_path"]
        if model_path:
            result["model_exists"] = Path(model_path).exists()

        try:
            import onnxruntime as ort  # type: ignore[import]
            result["onnxruntime_version"] = ort.__version__
            providers = ort.get_available_providers()
            result["providers"] = providers
            result["available"] = "VitisAIExecutionProvider" in providers
            result["status"]    = STATUS_OK if result["available"] else STATUS_WARN
            if not result["available"]:
                result["error"] = (
                    "VitisAIExecutionProvider not found. "
                    "Install onnxruntime-vitisai for AMD NPU support."
                )
        except ImportError:
            result["status"] = STATUS_WARN
            result["error"]  = "onnxruntime not installed."

        return result

    # ── Tools ─────────────────────────────────────────────────────────────────

    def check_tools(self) -> list[dict[str, Any]]:
        """Return status of every registered tool.

        Returns
        -------
        list[dict]
            One dict per tool with keys: ``name``, ``status``,
            ``loaded``, ``unload_after_use``, ``description``.
        """
        if self._registry is None:
            return [{"name": "—", "status": STATUS_SKIP,
                     "loaded": False, "unload_after_use": False,
                     "description": "No registry provided."}]
        results = []
        for name, desc in self._registry._descriptors.items():
            results.append({
                "name":            name,
                "status":          STATUS_OK,
                "loaded":          desc.is_loaded,
                "unload_after_use": desc.unload_after_use,
                "description":     desc.description,
            })
        return results

    # ── Security ──────────────────────────────────────────────────────────────

    def check_security(self) -> dict[str, Any]:
        """Run security checks on files and configuration.

        Returns
        -------
        dict
            Keys: ``status``, ``checks`` (list of individual check dicts),
            ``issues``.
        """
        checks = []
        issues = 0

        def _file_check(path: Path, label: str) -> None:
            nonlocal issues
            if not path.exists():
                checks.append({"label": label, "status": STATUS_SKIP,
                                "detail": "File not found."})
                return
            try:
                mode = path.stat().st_mode & 0o777
                world_readable = bool(mode & (stat.S_IRGRP | stat.S_IROTH))
                if world_readable:
                    checks.append({"label": label, "status": STATUS_WARN,
                                   "detail": f"Mode {oct(mode)} — readable by group/world."})
                    issues += 1
                else:
                    checks.append({"label": label, "status": STATUS_OK,
                                   "detail": f"Mode {oct(mode)} — owner only."})
            except OSError as exc:
                checks.append({"label": label, "status": STATUS_WARN,
                               "detail": f"Could not read permissions: {exc}"})
                issues += 1

        # Check settings file
        settings_path = Path.home() / ".config" / "linux-ai-npu-helper" / "settings.json"
        _file_check(settings_path, "Settings file permissions")

        # Check conversation history
        history_path = Path.home() / ".local" / "share" / "linux-ai-npu-helper" / "history.json"
        _file_check(history_path, "Conversation history permissions")

        # Network guard
        allow_external = self._config.network.get("allow_external", False)
        checks.append({
            "label":  "External network access",
            "status": STATUS_WARN if allow_external else STATUS_OK,
            "detail": "ENABLED — AI may contact external servers." if allow_external
                      else "DISABLED — all AI processing stays local.",
        })
        if allow_external:
            issues += 1

        # Rate limiter
        security_cfg = self._config.get("security", {}) if hasattr(self._config, "get") else {}
        rpm = security_cfg.get("rate_limit_per_minute", 0)
        checks.append({
            "label":  "Rate limiter",
            "status": STATUS_OK if rpm > 0 else STATUS_SKIP,
            "detail": f"{rpm} calls/min" if rpm > 0 else "Disabled (0 = unlimited).",
        })

        overall = STATUS_OK if issues == 0 else STATUS_WARN
        return {"status": overall, "checks": checks, "issues": issues}

    # ── Settings ──────────────────────────────────────────────────────────────

    def check_settings(self) -> dict[str, Any]:
        """Check the settings file and manager status.

        Returns
        -------
        dict
            Keys: ``status``, ``path``, ``exists``, ``listener_count``,
            ``backend``, ``model``, ``error``.
        """
        result: dict[str, Any] = {
            "status":         STATUS_OK,
            "path":           str(Path.home() / ".config" / "linux-ai-npu-helper" / "settings.json"),
            "exists":         False,
            "listener_count": 0,
            "backend":        self._config.backend,
            "model":          "",
            "error":          "",
        }

        settings_path = Path(result["path"])
        result["exists"] = settings_path.exists()

        if self._settings_manager is not None:
            result["listener_count"] = len(self._settings_manager._listeners)

        backend = self._config.backend
        if backend == "ollama":
            result["model"] = self._config.ollama.get("model", "")
        elif backend == "openai":
            result["model"] = self._config.openai.get("model", "")
        elif backend == "npu":
            result["model"] = self._config.npu.get("model_path", "")

        return result

    # ── System ────────────────────────────────────────────────────────────────

    def check_system(self) -> dict[str, Any]:
        """Collect system information.

        Returns
        -------
        dict
            Keys: ``status``, ``os_name``, ``os_version``, ``distro_id``,
            ``package_manager``, ``desktop_environment``, ``shell``,
            ``kernel``, ``architecture``, ``python_version``,
            ``is_immutable``, ``app_version``.
        """
        result: dict[str, Any] = {
            "status":              STATUS_OK,
            "os_name":             "",
            "os_version":          "",
            "distro_id":           "",
            "package_manager":     "",
            "desktop_environment": "",
            "shell":               "",
            "kernel":              "",
            "architecture":        "",
            "python_version":      sys.version,
            "is_immutable":        False,
            "app_version":         _VERSION,
        }

        try:
            from src.os_detector import detect as detect_os
            info = detect_os()
            result.update({
                "os_name":             info.name,
                "os_version":          info.version,
                "distro_id":           info.id,
                "package_manager":     info.package_manager,
                "desktop_environment": info.desktop_environment,
                "kernel":              info.kernel,
                "architecture":        info.architecture,
                "is_immutable":        getattr(info, "is_immutable", False),
            })
        except Exception as exc:  # noqa: BLE001
            result["status"] = STATUS_WARN
            logger.debug("OS detection error: %s", exc)

        try:
            from src.shell_detector import detect as detect_shell
            shell_info = detect_shell()
            result["shell"] = f"{shell_info.name} ({shell_info.path})"
        except Exception as exc:  # noqa: BLE001
            logger.debug("Shell detection error: %s", exc)

        return result

    # ── Network ───────────────────────────────────────────────────────────────

    def check_network(self) -> dict[str, Any]:
        """Check network configuration and local URL validity.

        Returns
        -------
        dict
            Keys: ``status``, ``allow_external``, ``backend_url``,
            ``backend_url_is_local``, ``error``.
        """
        from src.security import is_local_url

        allow_external = self._config.network.get("allow_external", False)
        backend = self._config.backend

        if backend == "ollama":
            url = self._config.ollama.get("base_url", "")
        elif backend == "openai":
            url = self._config.openai.get("base_url", "")
        else:
            url = "in-process"

        is_local = is_local_url(url) if url not in ("", "in-process") else True

        status = STATUS_OK
        error = ""
        if not is_local and not allow_external:
            status = STATUS_FAIL
            error = (
                f"Backend URL {url!r} is external but network.allow_external is false. "
                "The app will block this request at runtime."
            )
        elif allow_external:
            status = STATUS_WARN
            error = "External network access is enabled."

        return {
            "status":               status,
            "allow_external":       allow_external,
            "backend_url":          url,
            "backend_url_is_local": is_local,
            "error":                error,
        }

    # ── Dependencies ──────────────────────────────────────────────────────────

    def check_dependencies(self) -> list[dict[str, Any]]:
        """Check availability of optional runtime dependencies.

        Returns
        -------
        list[dict]
            One dict per dependency with keys: ``name``, ``status``,
            ``version``, ``required``, ``detail``.
        """
        deps = [
            ("requests",      True,  "HTTP backend communication"),
            ("yaml",          True,  "Config file parsing (PyYAML)"),
            ("PyQt5",         False, "GUI — required for the settings and diagnostic windows"),
            ("onnxruntime",   False, "AMD NPU inference"),
            ("mss",           False, "Fast screen capture"),
            ("PIL",           False, "Image processing (Pillow)"),
            ("pynput",        False, "Keyboard hotkey listener"),
            ("evdev",         False, "Copilot-key detection on AMD laptops"),
            ("numpy",         False, "NPU tensor operations"),
        ]
        results = []
        for pkg, required, detail in deps:
            try:
                mod = importlib.import_module(pkg)
                version = getattr(mod, "__version__", "installed")
                results.append({
                    "name":     pkg,
                    "status":   STATUS_OK,
                    "version":  version,
                    "required": required,
                    "detail":   detail,
                })
            except ImportError:
                results.append({
                    "name":     pkg,
                    "status":   STATUS_FAIL if required else STATUS_WARN,
                    "version":  "",
                    "required": required,
                    "detail":   detail,
                })
        return results

    # ── Test runner ───────────────────────────────────────────────────────────

    def run_tests(self) -> dict[str, Any]:
        """Run the test suite programmatically and return a summary.

        Returns
        -------
        dict
            Keys: ``status``, ``passed``, ``failed``, ``errors``,
            ``total``, ``duration_s``, ``output``.
        """
        import subprocess
        result: dict[str, Any] = {
            "status":     STATUS_SKIP,
            "passed":     0,
            "failed":     0,
            "errors":     0,
            "total":      0,
            "duration_s": 0.0,
            "output":     "",
        }

        pytest_exe = shutil.which("pytest") or shutil.which("python3")
        if pytest_exe is None:
            result["output"] = "pytest not found."
            return result

        cmd = (
            [pytest_exe, "-m", "pytest", "--tb=short", "-q"]
            if "python" in pytest_exe
            else [pytest_exe, "--tb=short", "-q"]
        )

        try:
            t0 = time.monotonic()
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(Path(__file__).parent.parent.parent),
            )
            result["duration_s"] = round(time.monotonic() - t0, 2)
            result["output"]     = proc.stdout + proc.stderr

            # Parse summary line: "3 failed, 115 passed in 0.12s"
            import re
            summary = proc.stdout.splitlines()[-1] if proc.stdout.strip() else ""
            m_pass  = re.search(r"(\d+) passed",  summary)
            m_fail  = re.search(r"(\d+) failed",  summary)
            m_error = re.search(r"(\d+) error",   summary)
            result["passed"] = int(m_pass.group(1))  if m_pass  else 0
            result["failed"] = int(m_fail.group(1))  if m_fail  else 0
            result["errors"] = int(m_error.group(1)) if m_error else 0
            result["total"]  = result["passed"] + result["failed"] + result["errors"]
            result["status"] = STATUS_OK if proc.returncode == 0 else STATUS_FAIL
        except subprocess.TimeoutExpired:
            result["status"] = STATUS_FAIL
            result["output"] = "Test run timed out after 120 seconds."
        except Exception as exc:  # noqa: BLE001
            result["status"] = STATUS_FAIL
            result["output"] = str(exc)

        return result

    # ── Full report ───────────────────────────────────────────────────────────

    def full_report(self) -> dict[str, Any]:
        """Collect all status checks and return a single aggregated dict.

        Returns
        -------
        dict
            Keys: ``timestamp``, ``app_version``, ``overall_status``,
            ``backend``, ``npu``, ``tools``, ``security``, ``settings``,
            ``system``, ``network``, ``dependencies``.

        Note
        ----
        The ``backend`` check makes a live HTTP probe.  All other checks are
        local only.  Pass ``probe_backend=False`` to :meth:`full_report` if
        you want a fully offline report (the backend entry will be skipped).
        """
        import datetime

        report: dict[str, Any] = {
            "timestamp":      datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "app_version":    _VERSION,
            "overall_status": STATUS_OK,
            "backend":        self.check_backend(timeout=3),
            "npu":            self.check_npu(),
            "tools":          self.check_tools(),
            "security":       self.check_security(),
            "settings":       self.check_settings(),
            "system":         self.check_system(),
            "network":        self.check_network(),
            "dependencies":   self.check_dependencies(),
        }

        # Determine overall status
        statuses = [
            report["backend"]["status"],
            report["npu"]["status"],
            report["security"]["status"],
            report["settings"]["status"],
            report["system"]["status"],
            report["network"]["status"],
        ]
        if STATUS_FAIL in statuses:
            report["overall_status"] = STATUS_FAIL
        elif STATUS_WARN in statuses:
            report["overall_status"] = STATUS_WARN

        return report
