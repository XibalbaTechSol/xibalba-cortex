"""Build an evaluation corpus and known-item queries from our own memory stores.

Corpus: a seeded sample of memories, read from a SQLite store opened read-only, with anything
that looks like a credential dropped before it can be sent to an LLM or a search engine.

Queries: for a subset of corpus documents, an LLM writes the question a teammate would later
ask whose answer is in that document ("known-item" queries). The prompt forbids copying
distinctive phrases, because a query that quotes its passage is a keyword lookup and would
flatter the keyword channel. Each query's single relevant document is the one it was written
from; near-duplicate documents are a known source of under-counting, reported, not hidden.
"""

from __future__ import annotations

import json
import os
import random
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

import httpx

SECRET_PATTERNS = re.compile(
    r"(sm_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|sk_(live|test)_[A-Za-z0-9]{10,}|rk_(live|test)_|whsec_[A-Za-z0-9]{10,}"
    r"|ghp_[A-Za-z0-9]{20,}|github_pat_|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY"
    r"|eyJhbGciOi[A-Za-z0-9_-]{20,}|postgres(ql)?://[^:@\s]+:[^@\s]{6,}@|0x[0-9a-fA-F]{64}\b)"
)


def looks_secret(text: str) -> bool:
    return bool(SECRET_PATTERNS.search(text))


def sample_cortex_corpus(
    db_path: str | Path,
    size: int,
    seed: int = 42,
    min_chars: int = 150,
    max_chars: int = 1500,
    statuses: tuple[str, ...] = ("active", "confirmed", "candidate"),
) -> list[dict[str, Any]]:
    uri = f"file:{Path(db_path)}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    marks = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"""SELECT id, content, content_hash, created_at FROM memories
            WHERE status IN ({marks}) AND length(content) BETWEEN ? AND ?""",
        (*statuses, min_chars, max_chars),
    ).fetchall()
    conn.close()
    seen: set[str] = set()
    pool = []
    for row in rows:
        if row["content_hash"] in seen or looks_secret(row["content"]):
            continue
        seen.add(row["content_hash"])
        pool.append({"id": f"eval-{row['id']}", "content": row["content"],
                     "metadata": {"source": "cortex", "created_at": row["created_at"]}})
    pool.sort(key=lambda d: d["id"])  # sample from a stable order so the seed is reproducible
    random.Random(seed).shuffle(pool)
    return pool[:size]


QUESTION_PROMPT = """You are building a search test set for an engineering team's memory system.
For each numbered passage below, write ONE question a teammate might ask weeks later, whose
answer is in that passage. Rules:
- Paraphrase. Do not copy distinctive phrases, identifiers, or rare words from the passage.
- Ask about the substance (a decision, result, cause, number, or next step), not its wording.
- One sentence, under 25 words. The question must make sense without seeing the passage.
Return a JSON array of objects: {"n": <passage number>, "question": "<text>"}.

"""


def gemini_generate(prompt: str, api_key: str, model: str = "gemini-2.5-flash", timeout: float = 120.0) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4}}
    for attempt in range(6):
        resp = httpx.post(url, json=body, headers={"x-goog-api-key": api_key}, timeout=timeout)
        if resp.status_code in (429, 500, 503):
            time.sleep(min(60, 8 * 2**attempt))  # free tier: back off instead of failing the run
            continue
        resp.raise_for_status()
        parts = resp.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    raise RuntimeError("Gemini kept refusing (rate limited); rerun later -- generation resumes")


def generate_queries(
    docs: list[dict[str, Any]],
    out_path: str | Path,
    generate: Callable[[str], str] | None = None,
    batch_size: int = 15,
    pause_seconds: float = 7.0,
) -> list[dict[str, Any]]:
    """Write one known-item query per doc to `out_path` (JSONL), resuming if it exists."""
    if generate is None:
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        if not key:
            raise RuntimeError("set GEMINI_API_KEY (free tier) to generate queries")
        generate = lambda prompt: gemini_generate(prompt, key)  # noqa: E731
    out_path = Path(out_path)
    done: dict[str, dict[str, Any]] = {}
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done[row["relevant"][0]] = row
    todo = [d for d in docs if d["id"] not in done]
    with out_path.open("a", encoding="utf-8") as fh:
        for start in range(0, len(todo), batch_size):
            batch = todo[start : start + batch_size]
            prompt = QUESTION_PROMPT + "\n\n".join(
                f"[{i}] {d['content'][:1500]}" for i, d in enumerate(batch, 1)
            )
            try:
                items = json.loads(generate(prompt))
            except json.JSONDecodeError:
                continue  # malformed batch is skipped; a rerun resumes and retries it
            for item in items if isinstance(items, list) else []:
                try:
                    doc = batch[int(item["n"]) - 1]
                except (KeyError, ValueError, IndexError, TypeError):
                    continue
                question = str(item.get("question", "")).strip()
                if not question or doc["id"] in done:
                    continue
                row = {"qid": f"q-{doc['id']}", "query": question, "relevant": [doc["id"]]}
                done[doc["id"]] = row
                fh.write(json.dumps(row) + "\n")
            fh.flush()
            if start + batch_size < len(todo):
                time.sleep(pause_seconds)
    order = {d["id"]: i for i, d in enumerate(docs)}
    return sorted((r for r in done.values() if r["relevant"][0] in order), key=lambda r: order[r["relevant"][0]])


def lexical_overlap(query: str, passage: str) -> float:
    """Share of the query's content words that appear verbatim in its passage.

    A high average means the queries leak their answers' wording and the test mostly measures
    keyword matching. Reported with every dataset so that bias is visible.
    """
    words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 3}
    if not words:
        return 0.0
    text = passage.lower()
    return sum(1 for w in words if w in text) / len(words)


def write_jsonl(rows: list[dict[str, Any]], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
