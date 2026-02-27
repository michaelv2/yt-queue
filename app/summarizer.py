"""Pluggable LLM abstraction for summarization and relevance scoring."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class BaseLLM:
    def summarize(self, transcript: str, max_words: int = 80) -> str:
        raise NotImplementedError

    def score_relevance(self, summary: str, criteria: str) -> float:
        """Return 0.0–1.0; 1.0 = highly relevant."""
        raise NotImplementedError


class NullLLM(BaseLLM):
    """No-op — used when llm_provider='none'."""

    def summarize(self, transcript: str, max_words: int = 80) -> str:
        return ""

    def score_relevance(self, summary: str, criteria: str) -> float:
        return 0.0


class AnthropicLLM(BaseLLM):
    def __init__(self, model: str, api_key: str):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def summarize(self, transcript: str, max_words: int = 80) -> str:
        prompt = (
            f"Produce a ≤{max_words}-word plain-English summary of this YouTube video transcript. "
            "Include the main topic, key points, and tone. "
            "Return only the summary text, no preamble.\n\n"
            f"Transcript:\n{transcript[:12000]}"
        )
        try:
            msg = self._client.messages.create(
                model=self._model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text.strip()
        except Exception as e:
            log.warning("AnthropicLLM.summarize failed: %s", e)
            return ""

    def score_relevance(self, summary: str, criteria: str) -> float:
        prompt = (
            "Given this video summary and the user's interest criteria, "
            "rate how likely this video is worth watching on a scale of 0 to 10. "
            "Return only the integer, nothing else.\n\n"
            f"Summary: {summary}\n\nCriteria: {criteria}"
        )
        try:
            msg = self._client.messages.create(
                model=self._model,
                max_tokens=10,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            return min(1.0, max(0.0, int(raw) / 10.0))
        except Exception as e:
            log.warning("AnthropicLLM.score_relevance failed: %s", e)
            return 0.0


class OpenAILLM(BaseLLM):
    def __init__(self, model: str, api_key: str, base_url: str = ""):
        from openai import OpenAI
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._model = model

    def summarize(self, transcript: str, max_words: int = 80) -> str:
        prompt = (
            f"Produce a ≤{max_words}-word plain-English summary of this YouTube video transcript. "
            "Include the main topic, key points, and tone. "
            "Return only the summary text, no preamble.\n\n"
            f"Transcript:\n{transcript[:12000]}"
        )
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            log.warning("OpenAILLM.summarize failed: %s", e)
            return ""

    def score_relevance(self, summary: str, criteria: str) -> float:
        prompt = (
            "Given this video summary and the user's interest criteria, "
            "rate how likely this video is worth watching on a scale of 0 to 10. "
            "Return only the integer, nothing else.\n\n"
            f"Summary: {summary}\n\nCriteria: {criteria}"
        )
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                max_tokens=10,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.choices[0].message.content.strip()
            return min(1.0, max(0.0, int(raw) / 10.0))
        except Exception as e:
            log.warning("OpenAILLM.score_relevance failed: %s", e)
            return 0.0


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks emitted by reasoning models (e.g. Qwen3)."""
    import re
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return text.strip()


class OllamaLLM(BaseLLM):
    _SYSTEM = (
        "You are a concise summarizer. Follow instructions exactly. "
        "Never add preamble, explanation, or reasoning — output only what is asked."
    )

    def __init__(self, model: str, base_url: str = "http://localhost:11434"):
        self._model = model
        self._base_url = base_url.rstrip("/")

    def _chat(self, system: str, user: str, max_tokens: int = 800) -> str:
        import json
        import urllib.request

        payload = json.dumps({
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            # think:false disables Qwen3 reasoning mode; ignored by other models
            "options": {"num_predict": max_tokens, "think": False},
        }).encode()
        req = urllib.request.Request(
            f"{self._base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = json.loads(resp.read())["message"]["content"]
        return _strip_think_tags(raw)

    def summarize(self, transcript: str, max_words: int = 80) -> str:
        user = (
            "Write 2-3 sentences capturing what this video covers and why it's interesting. "
            "Your sentences should build on each other — start broad, then get specific. "
            "Plain prose only, no lists.\n\n"
            f"Transcript:\n{transcript[:12000]}"
        )
        try:
            return self._chat(self._SYSTEM, user)
        except Exception as e:
            log.warning("OllamaLLM.summarize failed: %s", e)
            return ""

    def score_relevance(self, summary: str, criteria: str) -> float:
        user = (
            "Rate how relevant this video is to the user's interest criteria on a scale of 0 to 10. "
            "Output only the integer, nothing else.\n\n"
            f"Summary: {summary}\n\nCriteria: {criteria}"
        )
        try:
            raw = self._chat(self._SYSTEM, user, max_tokens=20)
            import re
            m = re.search(r"\d+", raw)
            score = int(m.group()) if m else 0
            return min(1.0, max(0.0, score / 10.0))
        except Exception as e:
            log.warning("OllamaLLM.score_relevance failed: %s", e)
            return 0.0


def get_llm(settings) -> BaseLLM:
    """Factory — returns LLM provider based on settings.llm_provider."""
    provider = settings.llm_provider.lower()
    if provider == "anthropic":
        return AnthropicLLM(model=settings.llm_model, api_key=settings.llm_api_key)
    if provider == "openai":
        return OpenAILLM(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
    if provider == "ollama":
        base_url = settings.llm_base_url or "http://localhost:11434"
        return OllamaLLM(model=settings.llm_model, base_url=base_url)
    return NullLLM()
