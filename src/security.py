# SPDX-License-Identifier: GPL-3.0-or-later
"""Central security utilities for Linux AI NPU Assistant.

All security-sensitive operations are consolidated here so they can be
reviewed, tested, and updated in one place.

## Responsibilities
- URL validation: block external hosts when ``network.allow_external`` is off.
- Response sanitisation: strip control characters / oversized AI output before
  it reaches the UI or tool dispatcher.
- Secure file I/O: atomic writes with owner-only (0o600) permissions.
- Path permission checks: warn when config/history files are world-readable.
- Rate limiting: token-bucket guard on AI backend calls.
- Tool argument validation: sanitise AI-supplied JSON args before dispatch.
- Secret masking: redact API keys in log output.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import stat
import socket
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────


class ExternalNetworkBlockedError(RuntimeError):
    """Raised when a request to an external host is attempted while
    ``network.allow_external`` is ``False``."""


class RateLimitExceededError(RuntimeError):
    """Raised when the backend call rate limit is exceeded."""


# ── URL guard ─────────────────────────────────────────────────────────────────


def is_local_url(url: str) -> bool:
    """Return *True* if *url* resolves to a loopback or RFC-1918 private address.

    Only bare IP addresses and the hostname ``localhost``/``::1`` are accepted
    as local.  Any hostname that is not a bare IP (e.g. ``my-server.lan``) is
    treated as potentially external and rejected when external traffic is off.
    """
    host = urlparse(url).hostname or ""
    if host.lower() in ("localhost", "::1"):
        return True
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_loopback or addr.is_private
    except ValueError:
        pass

    try:
        resolved_ip = socket.gethostbyname(host)
        addr = ipaddress.ip_address(resolved_ip)
        return addr.is_loopback or addr.is_private
    except Exception:
        return False


def assert_local_url(url: str, allow_external: bool) -> None:
    """Raise :class:`ExternalNetworkBlockedError` if *url* is external and
    external traffic is not permitted.

    Args:
        url:
            Full URL to validate.
        allow_external:
            If ``True`` the check is skipped entirely.  Set this only when the
            user has explicitly opted in via ``network.allow_external: true``.
    """
    if allow_external:
        return
    if not is_local_url(url):
        raise ExternalNetworkBlockedError(
            f"Blocked attempt to contact external host: {url!r}\n"
            "All AI processing must stay local (network.allow_external is false).\n"
            "Point your backend URL at localhost or a private-network address."
        )


# ── Response sanitisation ─────────────────────────────────────────────────────

# Characters that should never appear in AI output reaching the UI.
# ANSI CSI escape sequences are matched first so the full sequence is stripped
# in one pass.  After that, remaining bare C0/C1 control codes are stripped.
# Printable Unicode, newlines, and tabs are preserved.
_CONTROL_CHAR_RE = re.compile(
    r"\x1b\[[0-9;]*[A-Za-z]"  # ANSI CSI sequences  (must be first)
    r"|\x1b."  # Other 2-char ESC sequences
    r"|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"  # C0 except \t \n \r
    r"|[\x80-\x9f]"  # C1 control range
)

# Hard limit on AI response text returned per streaming chunk to the UI.
_MAX_RESPONSE_CHARS = 100_000  # 100 KiB of text is more than enough per call


def sanitize_ai_response(text: str, max_chars: int = _MAX_RESPONSE_CHARS) -> str:
    """Strip dangerous characters from *text* before it reaches the UI.

    - Removes ANSI escape sequences.
    - Removes C0/C1 control characters (keeps tab, newline, carriage-return).
    - Truncates to *max_chars* to prevent memory exhaustion from a runaway model.

    Args:
        text:
            Raw text received from the AI backend.
        max_chars:
            Maximum number of characters to return.  Text beyond this is silently
            dropped (the UI will show the truncation naturally during streaming).

    Returns:
        Sanitised text, safe to display in the UI.
    """
    if not text:
        return text
    cleaned = _CONTROL_CHAR_RE.sub("", text)
    if len(cleaned) > max_chars:
        logger.warning(
            "AI response truncated from %d to %d characters.",
            len(cleaned),
            max_chars,
        )
        cleaned = cleaned[:max_chars]
    return cleaned


# ── Secure file I/O ───────────────────────────────────────────────────────────


def secure_write(path: str | Path, data: str, mode: int = 0o600) -> None:
    """Write *data* to *path* atomically with restricted permissions.

    The file is written to a sibling ``.tmp`` file first, then renamed so the
    target is never partially written.  After the rename the file's mode is set
    to *mode* (default ``0o600`` — owner read/write only).

    Args:
        path:
            Destination file path.
        data:
            Text content to write (UTF-8 encoded).
        mode:
            POSIX file permission bits.  Default ``0o600`` restricts the file to
            the owning user, preventing other local users from reading sensitive
            data such as conversation history or config files.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    try:
        # Remove any existing .tmp file to prevent hijacking and permission retention
        if tmp.exists():
            tmp.unlink()

        # Create file with restrictive permissions atomically to avoid TOCTOU vulnerability
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)

        # Defense-in-depth: explicitly enforce permissions in case umask or OS ignores `mode`
        tmp.chmod(mode)

        tmp.replace(p)
    except OSError:
        # Clean up the temp file if anything went wrong
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


# ── Path permission checks ────────────────────────────────────────────────────


def check_path_permissions(path: str | Path, label: str = "file") -> None:
    """Log a warning if *path* is readable by group or world.

    Sensitive files such as conversation history and config files should be
    readable only by the owning user (mode ``0o600`` or ``0o400``).

    Args:
        path:
            File to inspect.
        label:
            Human-readable label used in warning messages (e.g. ``"config file"``).
    """
    p = Path(path)
    if not p.exists():
        return
    try:
        file_stat = p.stat()
        if file_stat.st_mode & (stat.S_IRGRP | stat.S_IROTH):
            logger.warning(
                "Security: %s %s is readable by group or world (mode=%o). "
                "Consider restricting it with: chmod 600 %s",
                label,
                p,
                file_stat.st_mode & 0o777,
                p,
            )
    except OSError as exc:
        logger.debug("Could not check permissions of %s: %s", p, exc)


# ── Rate limiter ──────────────────────────────────────────────────────────────


class RateLimiter:
    """Thread-safe token-bucket rate limiter for AI backend calls.

        Args:
            calls_per_minute:
                Maximum number of calls allowed per minute.  ``0`` disables limiting.
    ## Usage

            ::

                limiter = RateLimiter(calls_per_minute=30)
                limiter.check()   # raises RateLimitExceededError if over limit
    """

    def __init__(self, calls_per_minute: int = 0) -> None:
        self._limit = calls_per_minute
        self._lock = threading.Lock()
        # Token bucket state
        self._tokens: float = float(max(calls_per_minute, 0))
        self._last_refill: float = time.monotonic()

    def _refill(self) -> None:
        """Replenish tokens based on elapsed time (must hold self._lock)."""
        if self._limit <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_refill
        # Add tokens proportional to elapsed time (rate = limit/60 per second)
        added = elapsed * (self._limit / 60.0)
        self._tokens = min(self._tokens + added, float(self._limit))
        self._last_refill = now

    def check(self) -> None:
        """Consume one token or raise :class:`RateLimitExceededError`.

        Call this immediately before every AI backend request.
        """
        if self._limit <= 0:
            return  # Limiting disabled
        with self._lock:
            self._refill()
            if self._tokens < 1.0:
                raise RateLimitExceededError(
                    f"AI backend rate limit exceeded ({self._limit} calls/min). "
                    "Please wait a moment before sending another message."
                )
            self._tokens -= 1.0

    @property
    def enabled(self) -> bool:
        return self._limit > 0


# ── Tool argument validation ──────────────────────────────────────────────────

# Maximum length for any single string argument supplied by the AI.
_MAX_ARG_STRING_LEN = 4096

# Characters that must never appear in tool arguments (null byte, etc.)
_DANGEROUS_ARG_CHARS_RE = re.compile(r"[\x00]")


def validate_tool_args(
    args: dict[str, Any], schema: dict | None = None
) -> dict[str, Any]:
    """Sanitise AI-supplied tool arguments before dispatch.

    - Strips null bytes from all string values.
    - Truncates oversized string values to :data:`_MAX_ARG_STRING_LEN`.
    - Optionally validates *args* against a JSON-schema ``properties`` map to
      ensure required fields are present and types match.

    Args:
        args:
            Raw argument dict supplied by the AI (already JSON-decoded).
        schema:
            Optional JSON Schema dict with a ``"properties"`` key.  Used only for
            presence and basic type checks; full JSON Schema validation is not
            performed.

    Returns:
        Sanitised copy of *args*.

    Raises:
        ValueError: If a required field from the schema is missing.
        TypeError: If a field\'s value is of the wrong primitive type.
    """
    cleaned: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            # Strip null bytes
            value = _DANGEROUS_ARG_CHARS_RE.sub("", value)
            # Truncate oversized strings
            if len(value) > _MAX_ARG_STRING_LEN:
                logger.warning(
                    "Tool arg %r truncated from %d to %d chars.",
                    key,
                    len(value),
                    _MAX_ARG_STRING_LEN,
                )
                value = value[:_MAX_ARG_STRING_LEN]
        elif isinstance(value, list):
            # Sanitise string items in lists
            value = [
                _DANGEROUS_ARG_CHARS_RE.sub("", v)[:_MAX_ARG_STRING_LEN]
                if isinstance(v, str)
                else v
                for v in value
            ]
        cleaned[key] = value

    if schema:
        properties: dict = schema.get("properties", {})
        required: list[str] = schema.get("required", [])
        for field in required:
            if field not in cleaned:
                raise ValueError(f"Tool call is missing required argument: {field!r}")
        for field, field_schema in properties.items():
            if field not in cleaned:
                continue
            expected_type = field_schema.get("type")
            value = cleaned[field]
            _check_json_type(field, value, expected_type)

    return cleaned


def _check_json_type(field: str, value: Any, expected_type: str | None) -> None:
    """Raise TypeError if *value* doesn't match the JSON Schema *expected_type*."""
    if expected_type is None:
        return
    _type_map: dict[str, type | tuple] = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    py_type = _type_map.get(expected_type)
    if py_type is None:
        return
    # In JSON Schema, booleans are a subtype of integer in Python; handle that.
    if expected_type == "integer" and isinstance(value, bool):
        raise TypeError(f"Tool argument {field!r} expected integer, got boolean.")
    if not isinstance(value, py_type):
        raise TypeError(
            f"Tool argument {field!r} expected {expected_type}, "
            f"got {type(value).__name__}."
        )


# ── Secret masking ────────────────────────────────────────────────────────────

_MASK = "***"
_MIN_SECRET_LEN = 4  # Don't mask empty or trivially short "secrets"


def mask_secret(value: str) -> str:
    """Return a masked version of *value* safe for logging.

        Only the first two and last two characters are kept; everything in between
        is replaced with ``***``.  Values shorter than 8 characters are fully
        masked.
    Examples:
    >>> mask_secret("sk-abc123xyz")
    'sk***yz'
    >>> mask_secret("short")
    '***'
    """
    if not value or len(value) < _MIN_SECRET_LEN:
        return _MASK
    if len(value) < 8:
        return _MASK
    return f"{value[:2]}{_MASK}{value[-2:]}"


def get_api_key_from_env(env_var: str) -> str:
    """Retrieve an API key from an environment variable.

    The key is **never** read from the config file directly — it must always
    come from the process environment so it is not accidentally committed to
    version control.

    Args:
        env_var:
            Name of the environment variable to read.

    Returns:
        The API key value, or an empty string if the variable is not set.
    """
    if not env_var:
        return ""
    value = os.environ.get(env_var, "")
    if value:
        logger.debug("API key loaded from environment variable %r.", env_var)
    else:
        logger.debug("Environment variable %r is not set; no API key used.", env_var)
    return value
