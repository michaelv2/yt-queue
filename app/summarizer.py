"""Pluggable LLM abstraction for summarization and relevance scoring."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _extract_json(text: str):
    """Try to parse JSON from LLM output, tolerating surrounding prose."""
    import json
    import re
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r'(\[.*\]|\{.*\})', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return None


class BaseLLM:
    def summarize(self, transcript: str, max_words: int = 80) -> dict:
        """Return {"summary": "...", "takeaways": ["...", ...]}"""
        raise NotImplementedError

    def score_relevance(self, summary: str, criteria: str) -> float:
        """Return 0.0–1.0; 1.0 = highly relevant."""
        raise NotImplementedError

    def derive_taxonomy(self, summaries: list[str], n: int = 12) -> list[dict]:
        """Return a list of {name, description} category dicts."""
        raise NotImplementedError

    def assign_categories_bulk(self, videos: list[dict], category_names: list[str]) -> dict[int, str]:
        """Return {transcript_id: category_name} for a batch of videos."""
        raise NotImplementedError


class NullLLM(BaseLLM):
    """No-op — used when llm_provider='none'."""

    def summarize(self, transcript: str, max_words: int = 80) -> dict:
        return {"summary": "", "takeaways": []}

    def score_relevance(self, summary: str, criteria: str) -> float:
        return 0.0

    def derive_taxonomy(self, summaries: list[str], n: int = 12) -> list[dict]:
        return []

    def assign_categories_bulk(self, videos: list[dict], category_names: list[str]) -> dict[int, str]:
        return {}


class AnthropicLLM(BaseLLM):
    def __init__(self, model: str, api_key: str):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def summarize(self, transcript: str, max_words: int = 80) -> dict:
        prompt = (
            "Analyze this YouTube video transcript and return a JSON object with two fields:\n"
            f'1. "summary": A ≤{max_words}-word plain-English summary covering the main topic, key points, and tone.\n'
            '2. "takeaways": An array of specific, actionable takeaways or key points '
            "(vary the count based on content — fewer for simple videos, more for dense ones). "
            "Each should be a single concise sentence capturing a distinct insight, strategy, or recommendation.\n\n"
            "Return ONLY valid JSON, no other text.\n\n"
            f"Transcript:\n{transcript[:12000]}"
        )
        try:
            msg = self._client.messages.create(
                model=self._model,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            parsed = _extract_json(raw)
            if isinstance(parsed, dict) and "summary" in parsed:
                return {
                    "summary": parsed.get("summary", ""),
                    "takeaways": parsed.get("takeaways", []),
                }
            return {"summary": raw, "takeaways": []}
        except Exception as e:
            log.warning("AnthropicLLM.summarize failed: %s", e)
            return {"summary": "", "takeaways": []}

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

    def derive_taxonomy(self, summaries: list[str], n: int = 12) -> list[dict]:
        sample = "\n\n".join(f"- {s}" for s in summaries[:150])
        prompt = (
            f"Here are summaries of YouTube videos in a personal library.\n\n{sample}\n\n"
            f"Derive exactly {n} category names covering all content types present. "
            f'Return only a JSON array: [{{"name": "...", "description": "one sentence"}}, ...]. No other text.'
        )
        try:
            msg = self._client.messages.create(
                model=self._model, max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            data = _extract_json(msg.content[0].text.strip())
            if isinstance(data, list):
                return [{"name": d["name"], "description": d.get("description", "")} for d in data if "name" in d]
        except Exception as e:
            log.warning("AnthropicLLM.derive_taxonomy failed: %s", e)
        return []

    def assign_categories_bulk(self, videos: list[dict], category_names: list[str]) -> dict[int, str]:
        cats = ", ".join(f'"{c}"' for c in category_names)
        items = "\n".join(
            f'{v["id"]}: {v["title"]} — {(v.get("summary") or "")[:120]}' for v in videos
        )
        prompt = (
            f"Categories: [{cats}]\n\nVideos (id: title — summary):\n{items}\n\n"
            "Assign each video to its best category. "
            'Return only JSON: {"id": "category", ...}. Use exact category names. No other text.'
        )
        try:
            msg = self._client.messages.create(
                model=self._model, max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            data = _extract_json(msg.content[0].text.strip())
            if isinstance(data, dict):
                valid = set(category_names)
                result = {}
                for k, v in data.items():
                    try:
                        if v in valid:
                            result[int(k)] = v
                    except (ValueError, TypeError):
                        pass
                return result
        except Exception as e:
            log.warning("AnthropicLLM.assign_categories_bulk failed: %s", e)
        return {}


class OpenAILLM(BaseLLM):
    def __init__(self, model: str, api_key: str, base_url: str = ""):
        from openai import OpenAI
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._model = model

    def summarize(self, transcript: str, max_words: int = 80) -> dict:
        prompt = (
            "Analyze this YouTube video transcript and return a JSON object with two fields:\n"
            f'1. "summary": A ≤{max_words}-word plain-English summary covering the main topic, key points, and tone.\n'
            '2. "takeaways": An array of specific, actionable takeaways or key points '
            "(vary the count based on content — fewer for simple videos, more for dense ones). "
            "Each should be a single concise sentence capturing a distinct insight, strategy, or recommendation.\n\n"
            "Return ONLY valid JSON, no other text.\n\n"
            f"Transcript:\n{transcript[:12000]}"
        )
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.choices[0].message.content.strip()
            parsed = _extract_json(raw)
            if isinstance(parsed, dict) and "summary" in parsed:
                return {
                    "summary": parsed.get("summary", ""),
                    "takeaways": parsed.get("takeaways", []),
                }
            return {"summary": raw, "takeaways": []}
        except Exception as e:
            log.warning("OpenAILLM.summarize failed: %s", e)
            return {"summary": "", "takeaways": []}

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

    def derive_taxonomy(self, summaries: list[str], n: int = 12) -> list[dict]:
        sample = "\n\n".join(f"- {s}" for s in summaries[:150])
        prompt = (
            f"Here are summaries of YouTube videos in a personal library.\n\n{sample}\n\n"
            f"Derive exactly {n} category names covering all content types present. "
            f'Return only a JSON array: [{{"name": "...", "description": "one sentence"}}, ...]. No other text.'
        )
        try:
            resp = self._client.chat.completions.create(
                model=self._model, max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            data = _extract_json(resp.choices[0].message.content.strip())
            if isinstance(data, list):
                return [{"name": d["name"], "description": d.get("description", "")} for d in data if "name" in d]
        except Exception as e:
            log.warning("OpenAILLM.derive_taxonomy failed: %s", e)
        return []

    def assign_categories_bulk(self, videos: list[dict], category_names: list[str]) -> dict[int, str]:
        cats = ", ".join(f'"{c}"' for c in category_names)
        items = "\n".join(
            f'{v["id"]}: {v["title"]} — {(v.get("summary") or "")[:120]}' for v in videos
        )
        prompt = (
            f"Categories: [{cats}]\n\nVideos (id: title — summary):\n{items}\n\n"
            "Assign each video to its best category. "
            'Return only JSON: {"id": "category", ...}. Use exact category names. No other text.'
        )
        try:
            resp = self._client.chat.completions.create(
                model=self._model, max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            data = _extract_json(resp.choices[0].message.content.strip())
            if isinstance(data, dict):
                valid = set(category_names)
                result = {}
                for k, v in data.items():
                    try:
                        if v in valid:
                            result[int(k)] = v
                    except (ValueError, TypeError):
                        pass
                return result
        except Exception as e:
            log.warning("OpenAILLM.assign_categories_bulk failed: %s", e)
        return {}


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

    def summarize(self, transcript: str, max_words: int = 80) -> dict:
        user = (
            "Analyze this YouTube video transcript and return a JSON object with two fields:\n"
            f'1. "summary": A ≤{max_words}-word plain-English summary covering the main topic, key points, and tone.\n'
            '2. "takeaways": An array of specific, actionable takeaways or key points '
            "(vary the count based on content — fewer for simple videos, more for dense ones). "
            "Each should be a single concise sentence capturing a distinct insight, strategy, or recommendation.\n\n"
            "Return ONLY valid JSON, no other text.\n\n"
            f"Transcript:\n{transcript[:12000]}"
        )
        try:
            raw = self._chat(self._SYSTEM, user)
            parsed = _extract_json(raw)
            if isinstance(parsed, dict) and "summary" in parsed:
                return {
                    "summary": parsed.get("summary", ""),
                    "takeaways": parsed.get("takeaways", []),
                }
            return {"summary": raw, "takeaways": []}
        except Exception as e:
            log.warning("OllamaLLM.summarize failed: %s", e)
            return {"summary": "", "takeaways": []}

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

    def derive_taxonomy(self, summaries: list[str], n: int = 12) -> list[dict]:
        sample = "\n\n".join(f"- {s}" for s in summaries[:150])
        user = (
            f"Here are summaries of YouTube videos in a personal library.\n\n{sample}\n\n"
            f"Derive exactly {n} category names covering all content types present. "
            f'Return only a JSON array: [{{"name": "...", "description": "one sentence"}}, ...]. No other text.'
        )
        try:
            raw = self._chat(self._SYSTEM, user, max_tokens=800)
            data = _extract_json(raw)
            if isinstance(data, list):
                return [{"name": d["name"], "description": d.get("description", "")} for d in data if "name" in d]
        except Exception as e:
            log.warning("OllamaLLM.derive_taxonomy failed: %s", e)
        return []

    def assign_categories_bulk(self, videos: list[dict], category_names: list[str]) -> dict[int, str]:
        cats = ", ".join(f'"{c}"' for c in category_names)
        items = "\n".join(
            f'{v["id"]}: {v["title"]} — {(v.get("summary") or "")[:120]}' for v in videos
        )
        user = (
            f"Categories: [{cats}]\n\nVideos (id: title — summary):\n{items}\n\n"
            "Assign each video to its best category. "
            'Return only JSON: {"id": "category", ...}. Use exact category names. No other text.'
        )
        try:
            raw = self._chat(self._SYSTEM, user, max_tokens=800)
            data = _extract_json(raw)
            if isinstance(data, dict):
                valid = set(category_names)
                result = {}
                for k, v in data.items():
                    try:
                        if v in valid:
                            result[int(k)] = v
                    except (ValueError, TypeError):
                        pass
                return result
        except Exception as e:
            log.warning("OllamaLLM.assign_categories_bulk failed: %s", e)
        return {}


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
