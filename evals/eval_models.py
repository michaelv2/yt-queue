"""Compare Ollama models on yt-queue's LLM tasks using videos already in the archive.

Every task goes through the production OllamaLLM prompts and parsing in
app/summarizer.py:
  1. summarize              — JSON validity, word budget, takeaways, latency
  2. score_relevance        — parse rate, how well scores separate flagged videos
                              from the rest, latency
  3. assign_categories_bulk — coverage, agreement with the archive's current labels

Each run is MODEL@VARIANT:
  asis     OllamaLLM exactly as in production
  nothink  `think: false` sent at the top level (production nests it in `options`,
           where Ollama ignores it) and num_predict floored at 256 — a reasoning model
           spends ~60 hidden tokens even with thinking off, so production's 20-token
           relevance budget comes back empty
  low      `think: "low"` with num_predict floored at 1024

Ground truth for relevance is thin: is_flagged marks videos you found worth keeping,
is_marked_for_deletion marks ones you didn't. Category "agreement" is measured against
labels the current production model assigned, so it favours that model.

Reads data/ytqueue.db read-only. Results go to evals/results/<timestamp>/.

Usage:
  .venv/bin/python3 evals/eval_models.py                 # default runs
  .venv/bin/python3 evals/eval_models.py --smoke         # a few videos per task
  .venv/bin/python3 evals/eval_models.py --runs gemma3:27b@asis muse-glimmer:30b@low
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.summarizer import OllamaLLM, _extract_json, _strip_think_tags  # noqa: E402

DEFAULT_RUNS = ["gemma3:27b@asis", "muse-glimmer:30b@asis", "muse-glimmer:30b@nothink"]
VARIANTS = {
    "asis": None,
    "nothink": {"think": False, "min_tokens": 256},
    "low": {"think": "low", "min_tokens": 1024},
}
CATEGORY_BATCH = 25  # matches _run_categorization in app/main.py
MAX_WORDS = 80       # YTQUEUE_SUMMARY_MAX_WORDS default


class EvalLLM(OllamaLLM):
    """OllamaLLM that records each call. Prompts and parsing are inherited unchanged."""

    def __init__(self, model: str, base_url: str, variant: str):
        super().__init__(model, base_url)
        self._variant = VARIANTS[variant]
        self.last_call: dict = {}

    def _chat(self, system: str, user: str, max_tokens: int = 800) -> str:
        t0 = time.time()
        call = {"max_tokens": max_tokens, "content": "", "thinking_chars": None, "done_reason": None}
        try:
            if self._variant is None:
                call["content"] = super()._chat(system, user, max_tokens)
            else:
                call.update(self._chat_variant(system, user, max_tokens))
            return call["content"]
        except Exception as e:
            call["error"] = str(e)
            raise
        finally:
            call["seconds"] = round(time.time() - t0, 2)
            self.last_call = call

    def _chat_variant(self, system: str, user: str, max_tokens: int) -> dict:
        num_predict = max(max_tokens, self._variant["min_tokens"])
        payload = json.dumps({
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "think": self._variant["think"],
            "options": {"num_predict": num_predict},
        }).encode()
        req = urllib.request.Request(
            f"{self._base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
        msg = data.get("message") or {}
        return {
            "content": _strip_think_tags(msg.get("content") or ""),
            "thinking_chars": len(msg.get("thinking") or ""),
            "done_reason": data.get("done_reason"),
            "num_predict": num_predict,
        }


# ── Data ──────────────────────────────────────────────────────────────────────

def load_samples(db_path: Path, n_summarize: int, n_score: int, seed: int) -> dict:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT id, title, full_text, summary, category, is_flagged, is_marked_for_deletion "
        "FROM transcripts WHERE length(coalesce(full_text, '')) > 500 "
        "AND coalesce(summary, '') != '' ORDER BY id"
    )]
    categories = [r[0] for r in con.execute("SELECT name FROM categories ORDER BY name")]
    con.close()

    rng = random.Random(seed)
    flagged = [r for r in rows if r["is_flagged"]]
    marked = [r for r in rows if r["is_marked_for_deletion"] and not r["is_flagged"]]
    other = [r for r in rows if not r["is_flagged"] and not r["is_marked_for_deletion"]]
    rng.shuffle(other)

    score_set = flagged + marked + other[: max(0, n_score - len(flagged) - len(marked))]
    score_set = score_set[:n_score]
    summarize_set = (flagged + other)[:n_summarize]
    return {"summarize": summarize_set, "score": score_set, "categories": categories}


def build_criteria(criteria_file: str | None) -> str:
    if criteria_file:
        return Path(criteria_file).read_text(encoding="utf-8")
    import recommend
    goals = ROOT / "goals.md"
    return recommend.build_criteria(
        recommend.scan_projects(recommend.PROJECT_DIRS),
        goals.read_text(encoding="utf-8") if goals.exists() else None,
    )


# ── Tasks ─────────────────────────────────────────────────────────────────────

def run_summarize(llm: EvalLLM, videos: list[dict]) -> list[dict]:
    out = []
    for i, v in enumerate(videos, 1):
        result = llm.summarize(v["full_text"], max_words=MAX_WORDS)
        call = llm.last_call
        parsed = _extract_json(call.get("content", ""))
        summary = result.get("summary", "")
        out.append({
            "id": v["id"], "title": v["title"],
            "json_ok": isinstance(parsed, dict) and "summary" in parsed,
            "summary": summary,
            "words": len(summary.split()),
            "takeaways": len(result.get("takeaways") or []),
            **{k: call.get(k) for k in ("seconds", "thinking_chars", "done_reason", "error")},
        })
        print(f"    summarize {i}/{len(videos)}  {call.get('seconds')}s  "
              f"json_ok={out[-1]['json_ok']} words={out[-1]['words']}", flush=True)
    return out


def run_score(llm: EvalLLM, videos: list[dict], criteria: str) -> list[dict]:
    out = []
    for i, v in enumerate(videos, 1):
        # Same input the archive re-score endpoint builds (app/main.py _run_score_archive)
        text = f"{v['title']}\n\n{v['summary']}"
        score = llm.score_relevance(text, criteria)
        call = llm.last_call
        out.append({
            "id": v["id"], "title": v["title"],
            "group": "flagged" if v["is_flagged"] else "marked" if v["is_marked_for_deletion"] else "other",
            "score": score,
            "parse_ok": bool(re.search(r"\d+", call.get("content", ""))),
            "raw": call.get("content", "")[:40],
            **{k: call.get(k) for k in ("seconds", "thinking_chars", "done_reason", "error")},
        })
        if i % 10 == 0 or i == len(videos):
            print(f"    score {i}/{len(videos)}", flush=True)
    return out


def run_categorize(llm: EvalLLM, videos: list[dict], categories: list[str]) -> list[dict]:
    out = []
    for i in range(0, len(videos), CATEGORY_BATCH):
        chunk = videos[i: i + CATEGORY_BATCH]
        assigned = llm.assign_categories_bulk(chunk, categories)
        call = llm.last_call
        for v in chunk:
            out.append({
                "id": v["id"], "current": v["category"], "assigned": assigned.get(v["id"]),
                "batch_json_ok": isinstance(_extract_json(call.get("content", "")), dict),
            })
        print(f"    categorize {min(i + CATEGORY_BATCH, len(videos))}/{len(videos)}  "
              f"{call.get('seconds')}s  assigned={len(assigned)}/{len(chunk)}", flush=True)
        out[-1]["batch_seconds"] = call.get("seconds")
    return out


# ── Metrics ───────────────────────────────────────────────────────────────────

def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def auc(pos: list[float], neg: list[float]) -> float | None:
    """Probability a random positive outscores a random negative (ties count half)."""
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    var = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return cov / var if var else None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def summarize_metrics(res: dict) -> dict:
    s, sc, c = res["summarize"], res["score"], res["categorize"]
    by = {g: [r["score"] for r in sc if r["group"] == g] for g in ("flagged", "marked", "other")}
    return {
        "summarize": {
            "n": len(s),
            "json_ok": _mean([r["json_ok"] for r in s]),
            "empty": _mean([not r["summary"] for r in s]),
            "over_budget": _mean([r["words"] > MAX_WORDS for r in s if r["summary"]]),
            "mean_words": _mean([r["words"] for r in s if r["summary"]]),
            "mean_takeaways": _mean([r["takeaways"] for r in s if r["summary"]]),
            "mean_seconds": _mean([r["seconds"] for r in s]),
        },
        "score": {
            "n": len(sc),
            "parse_ok": _mean([r["parse_ok"] for r in sc]),
            "mean_flagged": _mean(by["flagged"]),
            "mean_marked": _mean(by["marked"]),
            "mean_other": _mean(by["other"]),
            "auc_flagged_vs_rest": auc(by["flagged"], by["marked"] + by["other"]),
            "auc_flagged_vs_marked": auc(by["flagged"], by["marked"]),
            "mean_seconds": _mean([r["seconds"] for r in sc]),
        },
        "categorize": {
            "n": len(c),
            "coverage": _mean([r["assigned"] is not None for r in c]),
            "agreement_with_current": _mean([r["assigned"] == r["current"] for r in c if r["assigned"]]),
            "mean_batch_seconds": _mean([r.get("batch_seconds") for r in c]),
        },
    }


# ── Report ────────────────────────────────────────────────────────────────────

def _fmt(v, pct=False):
    if v is None:
        return "—"
    if isinstance(v, bool):
        return str(v)
    return f"{v * 100:.0f}%" if pct else f"{v:.2f}"


def write_report(out_dir: Path, results: dict[str, dict], n_examples: int) -> str:
    runs = list(results)
    metrics = {r: results[r]["metrics"] for r in runs}
    head = "| Metric | " + " | ".join(runs) + " |\n|---|" + "---|" * len(runs)

    def table(task, rows):
        lines = [head]
        for key, label, pct in rows:
            lines.append(f"| {label} | " + " | ".join(_fmt(metrics[r][task][key], pct) for r in runs) + " |")
        return "\n".join(lines)

    md = [f"# yt-queue model comparison — {datetime.now():%Y-%m-%d %H:%M}", ""]
    md += ["## Summarize", "", table("summarize", [
        ("json_ok", "Valid JSON", True), ("empty", "Empty summary", True),
        ("over_budget", f"Over {MAX_WORDS} words", True), ("mean_words", "Mean words", False),
        ("mean_takeaways", "Mean takeaways", False), ("mean_seconds", "Seconds / video", False),
    ]), ""]
    md += ["## Relevance score", "", table("score", [
        ("parse_ok", "Returned a number", True), ("mean_flagged", "Mean score: flagged", False),
        ("mean_marked", "Mean score: marked for deletion", False), ("mean_other", "Mean score: other", False),
        ("auc_flagged_vs_rest", "AUC flagged vs rest", False),
        ("auc_flagged_vs_marked", "AUC flagged vs marked", False),
        ("mean_seconds", "Seconds / video", False),
    ]), ""]

    # Rank agreement between runs on the same videos
    pairs = []
    for i, a in enumerate(runs):
        for b in runs[i + 1:]:
            sa = {r["id"]: r["score"] for r in results[a]["score"] if r["parse_ok"]}
            sb = {r["id"]: r["score"] for r in results[b]["score"] if r["parse_ok"]}
            ids = sorted(sa.keys() & sb.keys())
            rho = spearman([sa[x] for x in ids], [sb[x] for x in ids])
            pairs.append(f"- {a} vs {b}: Spearman {_fmt(rho)} over {len(ids)} videos")
    md += ["Score rank agreement:", ""] + pairs + [""]

    md += ["## Categorize", "", table("categorize", [
        ("coverage", "Videos assigned a valid category", True),
        ("agreement_with_current", "Agreement with current labels", True),
        ("mean_batch_seconds", f"Seconds / batch of {CATEGORY_BATCH}", False),
    ]), ""]

    md += ["## Summaries side by side", ""]
    first = results[runs[0]]["summarize"][:n_examples]
    for idx, item in enumerate(first):
        md += [f"### {item['title']}", ""]
        for r in runs:
            s = results[r]["summarize"][idx]
            md += [f"**{r}** ({s['words']} words, {s['takeaways']} takeaways): {s['summary'] or '_(empty)_'}", ""]

    text = "\n".join(md)
    (out_dir / "summary.md").write_text(text, encoding="utf-8")
    return text


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", nargs="+", default=DEFAULT_RUNS, help="MODEL@VARIANT entries (variants: asis, nothink, low)")
    p.add_argument("--base-url", default=os.environ.get("YTQUEUE_LLM_BASE_URL") or "http://llm-server:11434")
    p.add_argument("--db", default=str(ROOT / "data" / "ytqueue.db"))
    p.add_argument("--criteria-file", help="Scoring criteria text (default: build it like recommend.py)")
    p.add_argument("--n-summarize", type=int, default=20)
    p.add_argument("--n-score", type=int, default=100)
    p.add_argument("--examples", type=int, default=6, help="Side-by-side summaries in the report")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--smoke", action="store_true", help="Tiny sample to check the plumbing")
    args = p.parse_args()

    if args.smoke:
        args.n_summarize, args.n_score, args.examples = 2, 4, 2
    for run in args.runs:
        if "@" not in run or run.rsplit("@", 1)[1] not in VARIANTS:
            p.error(f"bad run {run!r}: expected MODEL@VARIANT with VARIANT in {list(VARIANTS)}")

    out_dir = ROOT / "evals" / "results" / f"{datetime.now():%Y%m%d-%H%M%S}{'-smoke' if args.smoke else ''}"
    out_dir.mkdir(parents=True)

    samples = load_samples(Path(args.db), args.n_summarize, args.n_score, args.seed)
    criteria = build_criteria(args.criteria_file)
    (out_dir / "criteria.txt").write_text(criteria, encoding="utf-8")
    print(f"Ollama: {args.base_url}")
    print(f"Samples: {len(samples['summarize'])} summarize, {len(samples['score'])} score/categorize "
          f"({sum(v['is_flagged'] for v in samples['score'])} flagged, "
          f"{sum(bool(v['is_marked_for_deletion']) for v in samples['score'])} marked for deletion)")
    print(f"Criteria: {len(criteria)} chars -> {out_dir / 'criteria.txt'}")

    results = {}
    for run in args.runs:
        model, variant = run.rsplit("@", 1)
        llm = EvalLLM(model, args.base_url, variant)
        print(f"\n== {run} ==", flush=True)
        # Untimed warm-up so the model load (15-150s) isn't charged to the first video
        try:
            llm._chat("Reply with OK.", "OK", 300)
        except Exception as e:
            print(f"    warm-up failed: {e}", flush=True)
        t0 = time.time()
        res = {
            "model": model, "variant": variant,
            "summarize": run_summarize(llm, samples["summarize"]),
            "score": run_score(llm, samples["score"], criteria),
            "categorize": run_categorize(llm, samples["score"], samples["categories"]),
        }
        res["metrics"] = summarize_metrics(res)
        res["wall_seconds"] = round(time.time() - t0, 1)
        results[run] = res
        (out_dir / f"{run.replace(':', '_').replace('@', '__')}.json").write_text(
            json.dumps(res, indent=2), encoding="utf-8")
        print(f"   done in {res['wall_seconds']}s", flush=True)

    print("\n" + write_report(out_dir, results, args.examples))
    print(f"\nResults in {out_dir}")


if __name__ == "__main__":
    main()
