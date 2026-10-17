"""Regression tests for OllamaLLM's request payload.

`think` used to sit inside `options`, where Ollama ignores it, so reasoning models
(qwen3, muse-glimmer) reasoned on every call. Their hidden tokens also overran the old
caps: 20 tokens for a relevance score, 800 for a 25-video category batch.
"""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

from app.summarizer import OllamaLLM


def _response(content: str):
    body = json.dumps({"message": {"content": content}, "done_reason": "stop"}).encode()
    return io.BytesIO(body)


@pytest.fixture
def calls():
    """Capture each payload OllamaLLM sends; reply with queued contents."""
    sent, replies = [], []

    def fake_urlopen(req, timeout=None):
        sent.append(json.loads(req.data))
        return _response(replies.pop(0) if replies else "{}")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        yield sent, replies


def test_think_is_top_level_not_in_options(calls):
    sent, _ = calls
    OllamaLLM("muse-glimmer:30b-16k")._chat("sys", "user")
    assert sent[0]["think"] is False
    assert "think" not in sent[0]["options"]


def test_relevance_score_budget_fits_reasoning_overhead(calls):
    sent, replies = calls
    replies.append("7")
    score = OllamaLLM("muse-glimmer:30b-16k").score_relevance("A summary", "criteria")
    assert score == pytest.approx(0.7)
    assert sent[0]["options"]["num_predict"] >= 512


def test_category_and_taxonomy_budgets(calls):
    sent, replies = calls
    llm = OllamaLLM("muse-glimmer:30b-16k")
    replies.append(json.dumps({"1": "Tech"}))
    assert llm.assign_categories_bulk([{"id": 1, "title": "t", "summary": "s"}], ["Tech"]) == {1: "Tech"}
    replies.append(json.dumps([{"name": "Tech", "description": "d"}]))
    assert llm.derive_taxonomy(["s"]) == [{"name": "Tech", "description": "d"}]
    assert sent[0]["options"]["num_predict"] >= 3000
    assert sent[1]["options"]["num_predict"] >= 2000


def test_summarize_default_budget(calls):
    sent, replies = calls
    replies.append(json.dumps({"summary": "s", "takeaways": ["t"]}))
    assert OllamaLLM("gemma3:27b").summarize("transcript") == {"summary": "s", "takeaways": ["t"]}
    assert sent[0]["options"]["num_predict"] >= 1500
