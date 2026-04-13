# SPDX-License-Identifier: GPL-3.0-or-later
"""Conversation history — in-memory storage with optional disk persistence.

Messages are kept in a plain Python list so they are always available for
context without any I/O.  The list is also written to a JSON file on disk
(in the user's data directory) so prior conversations survive restarts.

Design notes
------------
- No database dependency; JSON is self-contained and human-readable.
- Only text content is persisted.  Image attachments are *not* stored on
  disk (they can be large and are usually transient).  The ``has_image``
  flag lets the UI indicate that images were part of a turn.
- ``max_messages`` caps the in-memory list so RAM stays bounded during
  very long sessions.  Older messages are trimmed from the *front* (oldest
  first), preserving the most recent context.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from src.security import check_path_permissions, secure_write

logger = logging.getLogger(__name__)

_DEFAULT_MAX_MESSAGES = 200
_DEFAULT_HISTORY_FILE = (
    Path.home() / ".local" / "share" / "linux-ai-npu-assistant" / "history.json"
)


@dataclass
class Message:
    """A single turn in the conversation."""

    role: str               # "user" | "assistant" | "system"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    has_image: bool = False  # True when the turn included a screenshot or uploaded image

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        return cls(
            role=d["role"],
            content=d["content"],
            timestamp=d.get("timestamp", ""),
            has_image=d.get("has_image", False),
        )


class ConversationHistory:
    """Thread-safe, persistent conversation history.

    Parameters
    ----------
    max_messages:
        Maximum number of messages kept in memory.  When the list exceeds
        this limit the oldest messages are removed first.
    persist_path:
        JSON file path for persistence.  Pass ``None`` to disable disk
        persistence (history lives only for the current session).
    system_prompt:
        An optional system message prepended to every API call to establish
        the assistant's persona / instructions.
    """

    def __init__(
        self,
        max_messages: int = _DEFAULT_MAX_MESSAGES,
        persist_path: Path | str | None = _DEFAULT_HISTORY_FILE,
        system_prompt: str = "",
    ) -> None:
        self._max = max_messages
        self._path = Path(persist_path) if persist_path else None
        self._system_prompt = system_prompt
        self._messages: list[Message] = []
        self._lock = threading.Lock()

        self._load()

    # ── Mutation ──────────────────────────────────────────────────────────────

    def add(
        self,
        role: str,
        content: str,
        *,
        has_image: bool = False,
    ) -> Message:
        """Append a message and persist immediately.

        Parameters
        ----------
        role:
            ``"user"`` or ``"assistant"``.
        content:
            Text content of the message.
        has_image:
            Set to ``True`` when the turn included an image (screenshot or
            uploaded file).  The image itself is not stored here.

        Returns
        -------
        Message
            The newly added message object.
        """
        msg = Message(role=role, content=content, has_image=has_image)
        with self._lock:
            self._messages.append(msg)
            # Trim oldest messages if over the cap
            if len(self._messages) > self._max:
                self._messages = self._messages[-self._max :]
        self._save()
        return msg

    def clear(self) -> None:
        """Remove all messages from memory and erase the on-disk file."""
        with self._lock:
            self._messages.clear()
        self._save()
        logger.info("Conversation history cleared.")

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def all_messages(self) -> list[Message]:
        """Return a snapshot of all messages (oldest first)."""
        with self._lock:
            return list(self._messages)

    def recent(self, n: int) -> list[Message]:
        """Return the *n* most recent messages."""
        with self._lock:
            return list(self._messages[-n:])

    def __iter__(self) -> Iterator[Message]:
        return iter(self.all_messages())

    def __len__(self) -> int:
        with self._lock:
            return len(self._messages)

    # ── API payload helpers ───────────────────────────────────────────────────

    def to_openai_messages(
        self,
        *,
        include_system: bool = True,
        max_context: int | None = None,
    ) -> list[dict]:
        """Return the message list in OpenAI ``/chat/completions`` format.

        Parameters
        ----------
        include_system:
            Prepend the system prompt if one is configured.
        max_context:
            Only include the most recent *max_context* messages (besides the
            system message).  Use this to avoid hitting context-length limits.
        """
        messages: list[dict] = []
        if include_system and self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})

        history = self.all_messages()
        if max_context is not None:
            history = history[-max_context:]

        for msg in history:
            messages.append({"role": msg.role, "content": msg.content})
        return messages

    def to_ollama_messages(
        self,
        *,
        max_context: int | None = None,
    ) -> list[dict]:
        """Return the message list in Ollama ``/api/chat`` format.

        Ollama's chat endpoint mirrors the OpenAI format, so this is a thin
        wrapper around :meth:`to_openai_messages`.
        """
        return self.to_openai_messages(
            include_system=True, max_context=max_context
        )

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            with self._lock:
                data = [m.to_dict() for m in self._messages]
            # Atomic write with owner-only permissions (0o600) so conversation
            # history is never readable by other local users.
            secure_write(
                self._path,
                json.dumps(data, indent=2, ensure_ascii=False),
                mode=0o600,
            )
        except OSError as exc:
            logger.warning("Could not save conversation history: %s", exc)

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        # Warn if the history file is readable by group or world.
        check_path_permissions(self._path, label="conversation history file")
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            with self._lock:
                self._messages = [Message.from_dict(d) for d in raw]
                # Enforce max even on loaded history
                if len(self._messages) > self._max:
                    self._messages = self._messages[-self._max :]
            logger.info(
                "Loaded %d messages from %s", len(self._messages), self._path
            )
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("Could not load conversation history: %s", exc)
