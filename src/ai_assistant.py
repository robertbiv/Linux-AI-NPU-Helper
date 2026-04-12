"""AI assistant backend — vision-capable LLM interaction.

Supported backends
------------------
- **ollama**  – Local Ollama server (recommended; supports llava and other
  vision models out of the box).  Uses the ``/api/chat`` endpoint so
  conversation history is passed natively.
- **openai**  – OpenAI-compatible REST API (gpt-4o or any vision endpoint).
  Passes the full ``messages`` array so multi-turn conversations work.
- **npu**     – AMD Ryzen AI ONNX model running on the NPU / iGPU.

Backend resource efficiency
---------------------------
- ``requests`` is imported lazily; no persistent ``Session`` is kept between
  calls (``Connection: close`` is sent with every request so the socket is
  released immediately after the response).
- Responses are streamed token-by-token and yielded to the caller so the UI
  can update incrementally without buffering the full reply in RAM.
- Screenshot / image bytes are passed in and can be deleted by the caller as
  soon as :func:`~AIAssistant.ask` returns — they are not retained here.
- NPU sessions are unloaded right after inference (see :mod:`npu_manager`).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Generator, Iterator

if TYPE_CHECKING:
    from src.conversation import ConversationHistory

logger = logging.getLogger(__name__)


class AIAssistant:
    """Facade for talking to a vision-capable LLM backend.

    Parameters
    ----------
    config:
        The application :class:`~src.config.Config` object.
    npu_manager:
        An optional :class:`~src.npu_manager.NPUManager`.  Only used when
        ``backend == "npu"``.
    """

    def __init__(self, config, npu_manager=None) -> None:  # noqa: ANN001
        self._config = config
        self._npu_manager = npu_manager

    # ── Main entry point ──────────────────────────────────────────────────────

    def ask(
        self,
        prompt: str,
        *,
        history: "ConversationHistory | None" = None,
        screenshot_jpeg: bytes | None = None,
        attachment_image_jpegs: list[bytes] | None = None,
        attachment_texts: list[str] | None = None,
        max_context_messages: int | None = 40,
    ) -> Generator[str, None, None]:
        """Send a prompt (with optional images/text/history) and stream the reply.

        This is a **generator**: iterate over it to receive response tokens as
        they arrive from the model.  The caller should delete
        ``screenshot_jpeg`` and any attachment bytes once this function returns
        to free memory.

        Parameters
        ----------
        prompt:
            The user's natural-language question or instruction.
        history:
            :class:`~src.conversation.ConversationHistory` whose past messages
            are passed to the model for multi-turn context.
        screenshot_jpeg:
            JPEG bytes of the current screen (optional).
        attachment_image_jpegs:
            List of JPEG bytes for user-uploaded images (optional).
        attachment_texts:
            List of text file contents to include in the context (optional).
        max_context_messages:
            How many of the most recent past messages to include in the
            request.  ``None`` includes all of them.

        Yields
        ------
        str
            Incremental response tokens as they arrive.
        """
        backend = self._config.backend
        if backend == "ollama":
            yield from self._ask_ollama(
                prompt, history, screenshot_jpeg,
                attachment_image_jpegs, attachment_texts,
                max_context_messages,
            )
        elif backend == "openai":
            yield from self._ask_openai(
                prompt, history, screenshot_jpeg,
                attachment_image_jpegs, attachment_texts,
                max_context_messages,
            )
        elif backend == "npu":
            yield from self._ask_npu(prompt, screenshot_jpeg)
        else:
            raise ValueError(f"Unknown backend: {backend!r}")

    # ── Ollama backend ────────────────────────────────────────────────────────

    def _ask_ollama(
        self,
        prompt: str,
        history: "ConversationHistory | None",
        screenshot_jpeg: bytes | None,
        attachment_images: list[bytes] | None,
        attachment_texts: list[str] | None,
        max_context: int | None,
    ) -> Iterator[str]:
        import base64

        cfg = self._config.ollama
        base_url = cfg["base_url"].rstrip("/")
        model = cfg["model"]
        timeout = cfg.get("timeout", 120)
        stream = self._config.resources.get("stream_response", True)

        # Build previous-turn messages from history
        if history is not None:
            messages = history.to_ollama_messages(max_context=max_context)
        else:
            messages = []

        # Collect images to attach to the current user turn
        images_b64: list[str] = []
        if screenshot_jpeg:
            images_b64.append(base64.b64encode(screenshot_jpeg).decode())
        for img in (attachment_images or []):
            images_b64.append(base64.b64encode(img).decode())

        # Build the current user message
        user_text = _build_text_prompt(prompt, attachment_texts)
        user_msg: dict = {"role": "user", "content": user_text}
        if images_b64:
            user_msg["images"] = images_b64
        messages.append(user_msg)

        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }

        try:
            import requests  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "requests is not installed.  Install it with: pip install requests"
            ) from exc

        url = f"{base_url}/api/chat"
        logger.debug("Sending request to Ollama at %s (model=%s)", url, model)

        # Backend resource efficiency: close the TCP socket after this request
        headers = {"Connection": "close"}

        try:
            with requests.post(
                url,
                json=payload,
                stream=stream,
                timeout=timeout,
                headers=headers,
            ) as resp:
                resp.raise_for_status()
                if stream:
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            yield token
                        if chunk.get("done"):
                            break
                else:
                    data = resp.json()
                    yield data.get("message", {}).get("content", "")
        except Exception as exc:
            logger.error("Ollama request failed: %s", exc)
            raise

    # ── OpenAI-compatible backend ─────────────────────────────────────────────

    def _ask_openai(
        self,
        prompt: str,
        history: "ConversationHistory | None",
        screenshot_jpeg: bytes | None,
        attachment_images: list[bytes] | None,
        attachment_texts: list[str] | None,
        max_context: int | None,
    ) -> Iterator[str]:
        import base64

        cfg = self._config.openai
        base_url = cfg["base_url"].rstrip("/")
        api_key = cfg.get("api_key", "")
        model = cfg["model"]
        timeout = cfg.get("timeout", 60)
        stream = self._config.resources.get("stream_response", True)

        # Start from persisted conversation history
        if history is not None:
            messages = history.to_openai_messages(max_context=max_context)
        else:
            messages = []

        # Build the current user message with optional images
        user_text = _build_text_prompt(prompt, attachment_texts)
        content: list[dict] = [{"type": "text", "text": user_text}]

        def _img_block(jpeg_bytes: bytes) -> dict:
            b64 = base64.b64encode(jpeg_bytes).decode()
            return {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}",
                    "detail": "auto",
                },
            }

        if screenshot_jpeg:
            content.append(_img_block(screenshot_jpeg))
        for img in (attachment_images or []):
            content.append(_img_block(img))

        messages.append({"role": "user", "content": content})

        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }

        try:
            import requests  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "requests is not installed.  Install it with: pip install requests"
            ) from exc

        url = f"{base_url}/chat/completions"
        # Backend resource efficiency: close socket after response
        headers: dict[str, str] = {
            "Authorization": f"Bearer {api_key}",
            "Connection": "close",
        }

        logger.debug("Sending request to OpenAI-compatible API at %s", url)

        try:
            with requests.post(
                url,
                json=payload,
                headers=headers,
                stream=stream,
                timeout=timeout,
            ) as resp:
                resp.raise_for_status()
                if stream:
                    for line in resp.iter_lines():
                        if not line or line == b"data: [DONE]":
                            continue
                        raw = line.decode("utf-8", errors="replace")
                        if raw.startswith("data: "):
                            raw = raw[6:]
                        try:
                            chunk = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        delta = (
                            chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if delta:
                            yield delta
                else:
                    data = resp.json()
                    yield (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
        except Exception as exc:
            logger.error("OpenAI API request failed: %s", exc)
            raise

    # ── NPU backend ───────────────────────────────────────────────────────────

    def _ask_npu(
        self,
        prompt: str,
        screenshot_jpeg: bytes | None,
    ) -> Iterator[str]:
        """Run inference on the AMD NPU via ONNX Runtime.

        The model is loaded, queried, and **immediately unloaded** so NPU
        memory is reclaimed right away (handled by NPUManager.run_inference).
        """
        if self._npu_manager is None:
            raise RuntimeError(
                "NPU backend selected but no NPUManager was provided."
            )

        try:
            import numpy as np  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "numpy is required for NPU inference: pip install numpy"
            ) from exc

        logger.info(
            "Running NPU inference (model=%s)", self._config.npu.get("model_path")
        )

        # Encode prompt as byte tokens (placeholder — real models need their
        # tokenizer here).
        token_ids = np.frombuffer(prompt.encode("utf-8"), dtype=np.uint8).astype(
            np.int64
        )[np.newaxis, :]

        feeds: dict = {"input_ids": token_ids}
        if screenshot_jpeg:
            feeds["image"] = np.frombuffer(screenshot_jpeg, dtype=np.uint8)[np.newaxis, :]

        # run_inference loads the model, runs it, then unloads it immediately
        outputs = self._npu_manager.run_inference(feeds)

        if outputs:
            result = outputs[0]
            if hasattr(result, "tobytes"):
                yield result.tobytes().decode("utf-8", errors="replace")
            else:
                yield str(result)
        else:
            yield ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_text_prompt(
    user_prompt: str,
    attachment_texts: list[str] | None,
) -> str:
    """Combine the user prompt with any text-file attachments."""
    parts: list[str] = []
    if attachment_texts:
        for i, text in enumerate(attachment_texts, start=1):
            parts.append(f"[Attached file {i}]\n{text}")
    parts.append(user_prompt)
    return "\n\n".join(parts)
