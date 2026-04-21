"""Extensive tests for src/ai_assistant.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest

from src.ai_assistant import AIAssistant
from src.security import ExternalNetworkBlockedError


# ── Config helpers ─────────────────────────────────────────────────────────────


def _make_config(
    backend="ollama",
    allow_external=False,
    stream=True,
    rate_limit=0,
    ollama_model="llava",
    openai_model="local-model",
    npu_model="",
):
    cfg = MagicMock()
    cfg.backend = backend
    cfg.ollama = {
        "base_url": "http://localhost:11434",
        "model": ollama_model,
        "timeout": 5,
    }
    cfg.openai = {
        "base_url": "https://localhost:1234/v1",
        "api_key": "sk-test",
        "model": openai_model,
        "timeout": 5,
    }
    cfg.npu = {"model_path": npu_model}
    cfg.network = {"allow_external": allow_external}
    cfg.resources = {"stream_response": stream}
    cfg.get = MagicMock(return_value={"rate_limit_per_minute": rate_limit})
    return cfg


def _make_history(messages=None):
    h = MagicMock()
    h.to_ollama_messages.return_value = messages or []
    h.to_openai_messages.return_value = messages or []
    return h


# ── Initialisation ────────────────────────────────────────────────────────────


class TestInit:
    def test_creates_rate_limiter(self):
        cfg = _make_config()
        assistant = AIAssistant(cfg)
        assert assistant._rate_limiter is not None

    def test_stores_config(self):
        cfg = _make_config()
        assistant = AIAssistant(cfg)
        assert assistant._config is cfg

    def test_stores_npu_manager(self):
        cfg = _make_config()
        npu = MagicMock()
        assistant = AIAssistant(cfg, npu_manager=npu)
        assert assistant._npu_manager is npu

    def test_stores_registry(self):
        cfg = _make_config()
        reg = MagicMock()
        assistant = AIAssistant(cfg, registry=reg)
        assert assistant._registry is reg


# ── System prompt ─────────────────────────────────────────────────────────────


class TestBuildSystemPrompt:
    def test_basic_prompt_not_empty(self):
        assistant = AIAssistant(_make_config())
        prompt = assistant._build_system_prompt()
        assert len(prompt) > 10

    def test_includes_os_info(self):
        cfg = _make_config()
        os_info = MagicMock()
        os_info.to_system_prompt_block.return_value = "OS: Arch Linux"
        assistant = AIAssistant(cfg, os_info=os_info)
        prompt = assistant._build_system_prompt()
        assert "OS: Arch Linux" in prompt

    def test_includes_tools_section(self):
        cfg = _make_config()
        registry = MagicMock()
        registry.system_prompt_section.return_value = "Available tools: find_files"
        assistant = AIAssistant(cfg, registry=registry)
        prompt = assistant._build_system_prompt()
        assert "find_files" in prompt

    def test_no_os_info_no_crash(self):
        assistant = AIAssistant(_make_config(), os_info=None)
        prompt = assistant._build_system_prompt()
        assert isinstance(prompt, str)

    def test_empty_tool_section_omitted(self):
        cfg = _make_config()
        registry = MagicMock()
        registry.system_prompt_section.return_value = ""
        assistant = AIAssistant(cfg, registry=registry)
        prompt = assistant._build_system_prompt()
        assert isinstance(prompt, str)


# ── ask() dispatch ────────────────────────────────────────────────────────────


class TestAskDispatch:
    def test_unknown_backend_raises(self):
        cfg = _make_config(backend="invalid")
        assistant = AIAssistant(cfg)
        with pytest.raises(ValueError, match="Unknown backend"):
            list(assistant.ask("hello"))

    def test_dispatches_to_ollama(self):
        cfg = _make_config(backend="ollama")
        assistant = AIAssistant(cfg)
        with patch.object(assistant, "_ask_ollama", return_value=iter(["hi"])) as mock:
            tokens = list(assistant.ask("hello"))
        mock.assert_called_once()
        assert tokens == ["hi"]

    def test_dispatches_to_openai(self):
        cfg = _make_config(backend="openai")
        assistant = AIAssistant(cfg)
        with patch.object(assistant, "_ask_openai", return_value=iter(["ok"])) as mock:
            tokens = list(assistant.ask("hello"))
        mock.assert_called_once()
        assert tokens == ["ok"]

    def test_dispatches_to_npu(self):
        npu = MagicMock()
        cfg = _make_config(backend="npu", npu_model="/model.onnx")
        assistant = AIAssistant(cfg, npu_manager=npu)
        with patch.object(assistant, "_ask_npu", return_value=iter(["npu"])) as mock:
            tokens = list(assistant.ask("hello"))
        mock.assert_called_once()
        assert tokens == ["npu"]


# ── Rate limiting ─────────────────────────────────────────────────────────────


class TestRateLimit:
    def test_rate_limit_exceeded_raises(self):
        from src.security import RateLimitExceededError

        cfg = _make_config(rate_limit=1)
        assistant = AIAssistant(cfg)
        # Force the rate limiter to raise
        assistant._rate_limiter.check = MagicMock(
            side_effect=RateLimitExceededError("Too many requests")
        )
        with pytest.raises(RateLimitExceededError):
            list(assistant.ask("hello"))


# ── Ollama backend ────────────────────────────────────────────────────────────


class TestAskOllama:
    def _fake_stream_resp(self, chunks: list[str]) -> MagicMock:
        lines = [
            json.dumps({"message": {"content": c}, "done": False}).encode()
            for c in chunks
        ]
        lines.append(json.dumps({"message": {"content": ""}, "done": True}).encode())
        resp = MagicMock()
        resp.iter_lines.return_value = lines
        resp.raise_for_status = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def _fake_nonstream_resp(self, content: str) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {"message": {"content": content}}
        resp.raise_for_status = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_stream_yields_tokens(self):
        cfg = _make_config(backend="ollama", stream=True)
        assistant = AIAssistant(cfg)
        resp = self._fake_stream_resp(["Hello", " world"])
        with patch("requests.post", return_value=resp):
            tokens = list(assistant.ask("hi"))
        assert "Hello" in tokens
        assert " world" in tokens

    def test_non_stream_yields_full_content(self):
        cfg = _make_config(backend="ollama", stream=False)
        assistant = AIAssistant(cfg)
        resp = self._fake_nonstream_resp("All at once")
        with patch("requests.post", return_value=resp):
            tokens = list(assistant.ask("hi"))
        assert "All at once" in "".join(tokens)

    def test_history_included(self):
        cfg = _make_config(backend="ollama", stream=False)
        assistant = AIAssistant(cfg)
        history = _make_history([{"role": "user", "content": "prev"}])
        resp = self._fake_nonstream_resp("answer")
        with patch("requests.post", return_value=resp) as mock_post:
            list(assistant.ask("hi", history=history))
        payload = mock_post.call_args[1]["json"]
        roles = [m["role"] for m in payload["messages"]]
        assert "system" in roles
        assert "user" in roles

    def test_screenshot_included_as_image(self):
        import base64

        cfg = _make_config(backend="ollama", stream=False)
        assistant = AIAssistant(cfg)
        resp = self._fake_nonstream_resp("yes")
        fake_jpeg = b"\xff\xd8\xff" + b"\x00" * 10
        with patch("requests.post", return_value=resp) as mock_post:
            list(assistant.ask("hi", screenshot_jpeg=fake_jpeg))
        payload = mock_post.call_args[1]["json"]
        user_msg = next(m for m in payload["messages"] if m["role"] == "user")
        assert "images" in user_msg
        assert base64.b64encode(fake_jpeg).decode() in user_msg["images"]

    def test_text_attachment_included(self):
        cfg = _make_config(backend="ollama", stream=False)
        assistant = AIAssistant(cfg)
        resp = self._fake_nonstream_resp("ok")
        with patch("requests.post", return_value=resp) as mock_post:
            list(assistant.ask("hi", attachment_texts=["file content here"]))
        payload = mock_post.call_args[1]["json"]
        user_msg = next(m for m in payload["messages"] if m["role"] == "user")
        assert "file content here" in user_msg["content"]

    def test_external_url_blocked(self):
        cfg = _make_config(backend="ollama", allow_external=False)
        cfg.ollama = {
            "base_url": "https://api.openai.com",
            "model": "gpt-4",
            "timeout": 5,
        }
        assistant = AIAssistant(cfg)
        with pytest.raises(ExternalNetworkBlockedError):
            list(assistant.ask("hi"))

    def test_verify_true_in_requests(self):
        cfg = _make_config(backend="ollama", stream=False)
        assistant = AIAssistant(cfg)
        resp = self._fake_nonstream_resp("ok")
        with patch("requests.post", return_value=resp) as mock_post:
            list(assistant.ask("hi"))
        _, kwargs = mock_post.call_args
        assert kwargs.get("verify") is True

    def test_connection_close_header(self):
        cfg = _make_config(backend="ollama", stream=False)
        assistant = AIAssistant(cfg)
        resp = self._fake_nonstream_resp("ok")
        with patch("requests.post", return_value=resp) as mock_post:
            list(assistant.ask("hi"))
        _, kwargs = mock_post.call_args
        assert kwargs.get("headers", {}).get("Connection") == "close"

    def test_invalid_json_line_skipped(self):
        cfg = _make_config(backend="ollama", stream=True)
        assistant = AIAssistant(cfg)
        resp = MagicMock()
        resp.iter_lines.return_value = [
            b"not json",
            json.dumps({"message": {"content": "ok"}, "done": False}).encode(),
            json.dumps({"done": True}).encode(),
        ]
        resp.raise_for_status = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("requests.post", return_value=resp):
            tokens = list(assistant.ask("hi"))
        assert "ok" in tokens

    def test_empty_lines_skipped(self):
        cfg = _make_config(backend="ollama", stream=True)
        assistant = AIAssistant(cfg)
        resp = MagicMock()
        resp.iter_lines.return_value = [
            b"",
            json.dumps({"message": {"content": "token"}, "done": True}).encode(),
        ]
        resp.raise_for_status = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("requests.post", return_value=resp):
            tokens = list(assistant.ask("hi"))
        assert "token" in tokens


# ── OpenAI-compatible backend ─────────────────────────────────────────────────


class TestAskOpenAI:
    def _fake_stream_resp(self, deltas: list[str]) -> MagicMock:
        lines = [
            (b"data: " + json.dumps({"choices": [{"delta": {"content": d}}]}).encode())
            for d in deltas
        ]
        lines.append(b"data: [DONE]")
        resp = MagicMock()
        resp.iter_lines.return_value = lines
        resp.raise_for_status = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def _fake_nonstream_resp(self, content: str) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {"choices": [{"message": {"content": content}}]}
        resp.raise_for_status = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_stream_yields_tokens(self):
        cfg = _make_config(backend="openai", stream=True)
        assistant = AIAssistant(cfg)
        resp = self._fake_stream_resp(["Hi", " there"])
        with patch("requests.post", return_value=resp):
            tokens = list(assistant.ask("hello"))
        assert "Hi" in tokens
        assert " there" in tokens

    def test_non_stream_yields_content(self):
        cfg = _make_config(backend="openai", stream=False)
        assistant = AIAssistant(cfg)
        resp = self._fake_nonstream_resp("Full answer")
        with patch("requests.post", return_value=resp):
            tokens = list(assistant.ask("hello"))
        assert "Full answer" in "".join(tokens)

    def test_api_key_in_auth_header(self):
        cfg = _make_config(backend="openai", stream=False)
        assistant = AIAssistant(cfg)
        resp = self._fake_nonstream_resp("ok")
        with patch("requests.post", return_value=resp) as mock_post:
            list(assistant.ask("hello"))
        _, kwargs = mock_post.call_args
        assert "Authorization" in kwargs.get("headers", {})
        assert "sk-test" in kwargs["headers"]["Authorization"]

    def test_verify_true(self):
        cfg = _make_config(backend="openai", stream=False)
        assistant = AIAssistant(cfg)
        resp = self._fake_nonstream_resp("ok")
        with patch("requests.post", return_value=resp) as mock_post:
            list(assistant.ask("hello"))
        _, kwargs = mock_post.call_args
        assert kwargs.get("verify") is True

    def test_api_key_over_http_raises_error(self):
        cfg = _make_config(backend="openai", stream=False)
        # Force HTTP instead of HTTPS
        cfg.openai["base_url"] = "http://localhost:1234/v1"
        assistant = AIAssistant(cfg)
        with pytest.raises(ValueError, match="insecure HTTP connections"):
            list(assistant.ask("hello"))

    def test_done_sentinel_skipped(self):
        cfg = _make_config(backend="openai", stream=True)
        assistant = AIAssistant(cfg)
        resp = MagicMock()
        resp.iter_lines.return_value = [b"data: [DONE]"]
        resp.raise_for_status = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("requests.post", return_value=resp):
            tokens = list(assistant.ask("hello"))
        assert tokens == []

    def test_external_url_blocked(self):
        cfg = _make_config(backend="openai", allow_external=False)
        cfg.openai = {
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-xxx",
            "model": "gpt-4",
            "timeout": 5,
        }
        assistant = AIAssistant(cfg)
        with pytest.raises(ExternalNetworkBlockedError):
            list(assistant.ask("hi"))

    def test_screenshot_attached_as_image_url(self):
        cfg = _make_config(backend="openai", stream=False)
        assistant = AIAssistant(cfg)
        resp = self._fake_nonstream_resp("yes")
        fake_jpeg = b"\xff\xd8\xff" + b"\x00" * 10
        with patch("requests.post", return_value=resp) as mock_post:
            list(assistant.ask("describe", screenshot_jpeg=fake_jpeg))
        payload = mock_post.call_args[1]["json"]
        user_msg = payload["messages"][-1]
        content = user_msg["content"]
        assert any(
            block.get("type") == "image_url"
            for block in content
            if isinstance(block, dict)
        )


# ── NPU backend ───────────────────────────────────────────────────────────────


class TestAskNPU:
    @patch("src.ai_assistant.probe_hardware")
    def test_no_npu_detected_raises(self, mock_probe):
        mock_probe.return_value.npu_available = False
        cfg = _make_config(backend="npu")
        npu = MagicMock()
        assistant = AIAssistant(cfg, npu_manager=npu)
        with pytest.raises(
            RuntimeError,
            match="No NPU detected. GPU support is coming soon, but right now it is NPU only.",
        ):
            list(assistant.ask("hello"))

    @patch("src.ai_assistant.probe_hardware")
    def test_no_npu_manager_raises(self, mock_probe):
        mock_probe.return_value.npu_available = True
        cfg = _make_config(backend="npu")
        assistant = AIAssistant(cfg, npu_manager=None)
        with pytest.raises(RuntimeError, match="NPUManager"):
            list(assistant.ask("hello"))

    @patch("src.ai_assistant.probe_hardware")
    def test_no_numpy_raises(self, mock_probe):
        mock_probe.return_value.npu_available = True
        cfg = _make_config(backend="npu")
        npu = MagicMock()
        assistant = AIAssistant(cfg, npu_manager=npu)
        with patch.dict("sys.modules", {"numpy": None}):
            with pytest.raises((RuntimeError, ImportError)):
                list(assistant.ask("hello"))

    @patch("src.ai_assistant.probe_hardware")
    def test_npu_inference_called(self, mock_probe):
        mock_probe.return_value.npu_available = True
        numpy = pytest.importorskip("numpy")
        cfg = _make_config(backend="npu")
        npu = MagicMock()
        result_array = numpy.array(
            [72, 101, 108, 108, 111], dtype=numpy.uint8
        )  # "Hello"
        npu.run_inference.return_value = [result_array]
        assistant = AIAssistant(cfg, npu_manager=npu)
        tokens = list(assistant.ask("test prompt"))
        npu.run_inference.assert_called_once()
        assert "".join(tokens)  # Non-empty output

    @patch("src.ai_assistant.probe_hardware")
    def test_npu_empty_output_yields_empty_string(self, mock_probe):
        mock_probe.return_value.npu_available = True
        pytest.importorskip("numpy")
        cfg = _make_config(backend="npu")
        npu = MagicMock()
        npu.run_inference.return_value = []
        assistant = AIAssistant(cfg, npu_manager=npu)
        tokens = list(assistant.ask("hello"))
        assert tokens == [""]


# ── Response sanitisation ─────────────────────────────────────────────────────


class TestSanitisation:
    def test_control_chars_stripped_from_ollama(self):
        cfg = _make_config(backend="ollama", stream=False)
        assistant = AIAssistant(cfg)
        resp = MagicMock()
        resp.json.return_value = {"message": {"content": "clean\x00\x08text"}}
        resp.raise_for_status = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("requests.post", return_value=resp):
            tokens = list(assistant.ask("hi"))
        assert "\x00" not in "".join(tokens)
        assert "\x08" not in "".join(tokens)
