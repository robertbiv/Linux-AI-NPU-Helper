"""Tests for src/conversation.py."""

from __future__ import annotations
import threading
from unittest.mock import patch
from src.conversation import ConversationHistory, Message


class TestMessage:
    def test_to_dict_roundtrip(self):
        m = Message(role="user", content="hello", has_image=True)
        d = m.to_dict()
        m2 = Message.from_dict(d)
        assert m2.role == "user"
        assert m2.content == "hello"
        assert m2.has_image is True

    def test_timestamp_set_automatically(self):
        m = Message(role="user", content="hi")
        assert m.timestamp  # non-empty


class TestConversationHistory:
    def test_add_message(self, tmp_path):
        h = ConversationHistory(persist_path=None)
        h.add("user", "hello")
        assert len(h) == 1

    def test_add_returns_message(self, tmp_path):
        h = ConversationHistory(persist_path=None)
        m = h.add("user", "hi")
        assert isinstance(m, Message)
        assert m.content == "hi"

    def test_clear(self, tmp_path):
        h = ConversationHistory(persist_path=None)
        h.add("user", "hi")
        h.clear()
        assert len(h) == 0

    def test_all_messages_snapshot(self, tmp_path):
        h = ConversationHistory(persist_path=None)
        h.add("user", "a")
        h.add("assistant", "b")
        msgs = h.all_messages()
        assert len(msgs) == 2
        assert msgs[0].content == "a"

    def test_recent(self, tmp_path):
        h = ConversationHistory(persist_path=None)
        for i in range(10):
            h.add("user", str(i))
        recent = h.recent(3)
        assert len(recent) == 3
        assert recent[-1].content == "9"

    def test_max_messages_trimmed(self, tmp_path):
        h = ConversationHistory(max_messages=5, persist_path=None)
        for i in range(10):
            h.add("user", str(i))
        assert len(h) == 5
        assert h.all_messages()[0].content == "5"

    def test_to_openai_messages(self, tmp_path):
        h = ConversationHistory(persist_path=None)
        h.add("user", "hi")
        h.add("assistant", "hello")
        msgs = h.to_openai_messages(include_system=False)
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_to_openai_messages_with_system(self, tmp_path):
        h = ConversationHistory(persist_path=None, system_prompt="sys")
        h.add("user", "hi")
        msgs = h.to_openai_messages(include_system=True)
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "sys"

    def test_to_openai_max_context(self, tmp_path):
        h = ConversationHistory(persist_path=None)
        for i in range(10):
            h.add("user", str(i))
        msgs = h.to_openai_messages(include_system=False, max_context=3)
        assert len(msgs) == 3

    def test_to_ollama_messages(self, tmp_path):
        h = ConversationHistory(persist_path=None)
        h.add("user", "ping")
        msgs = h.to_ollama_messages()
        assert any(m["role"] == "user" for m in msgs)

    def test_iter(self, tmp_path):
        h = ConversationHistory(persist_path=None)
        h.add("user", "a")
        h.add("assistant", "b")
        contents = [m.content for m in h]
        assert contents == ["a", "b"]

    def test_persistence(self, tmp_path):
        p = tmp_path / "history.json"
        h = ConversationHistory(persist_path=p)
        h.add("user", "remember me")
        h2 = ConversationHistory(persist_path=p)
        assert len(h2) == 1
        assert h2.all_messages()[0].content == "remember me"

    def test_history_file_mode_600(self, tmp_path):
        p = tmp_path / "history.json"
        h = ConversationHistory(persist_path=p)
        h.add("user", "secret")
        assert (p.stat().st_mode & 0o777) == 0o600

    def test_corrupted_file_ignored(self, tmp_path):
        p = tmp_path / "history.json"
        p.write_text("INVALID JSON")
        h = ConversationHistory(persist_path=p)
        assert len(h) == 0

    def test_thread_safe_add(self, tmp_path):
        h = ConversationHistory(persist_path=None)
        errors = []

        def add_msgs():
            try:
                for _ in range(20):
                    h.add("user", "x")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_msgs) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert len(h) <= 200  # default max

    @patch("src.conversation.secure_write")
    def test_save_oserror(self, mock_secure_write, tmp_path, caplog):
        """Test that OSError during save is caught and logged."""
        mock_secure_write.side_effect = OSError("Mock error")
        p = tmp_path / "history.json"
        h = ConversationHistory(persist_path=p)
        h.add("user", "test message")
        assert "Could not save conversation history: Mock error" in caplog.text
