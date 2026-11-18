"""`super-cortex eval ...` and `super-cortex engine ...` commands."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from ..config import resolve_api_key
from .dataset import generate_queries, lexical_overlap, sample_cortex_corpus, write_jsonl
from .runner import compare, control_check, evaluate, load_jsonl, render_markdown
from .targets import HttpTarget, RandomTarget

DEFAULT_DIR = Path.home() / ".super-cortex" / "eval"
DEFAULT_CORTEX_DB = Path.home() / ".claude" / "xibalba-cortex-claude" / "graph-memory.sqlite3"

eval_app = typer.Typer(help="Retrieval evaluation harness (data stays under ~/.super-cortex/eval)")
engine_app = typer.Typer(help="SuperCortex engine server")


@eval_app.command("build")
def build(
    corpus_size: int = typer.Option(600, help="Documents in the haystack"),
    query_count: int = typer.Option(150, help="Documents that get a known-item query"),
    source_db: Path = typer.Option(DEFAULT_CORTEX_DB, help="Cortex SQLite store, opened read-only"),
    out_dir: Path = typer.Option(DEFAULT_DIR),
    seed: int = typer.Option(42),
) -> None:
    """Sample a corpus and generate queries with Gemini (free tier; resumable)."""
    corpus = sample_cortex_corpus(source_db, corpus_size, seed=seed)
    write_jsonl(corpus, out_dir / "corpus.jsonl")
    queries = generate_queries(corpus[:query_count], out_dir / "queries.jsonl")
    by_id = {d["id"]: d for d in corpus}
    overlap = sum(lexical_overlap(q["query"], by_id[q["relevant"][0]]["content"]) for q in queries) / max(1, len(queries))
    typer.echo(json.dumps({"corpus": len(corpus), "queries": len(queries), "mean_lexical_overlap": round(overlap, 3)}))


def _targets(namespace: str, include_engine: bool, include_supermemory: bool, engine_url: str, supermemory_url: str,
             memories: bool = False):
    targets = []
    if memories:
        key = os.getenv("SUPER_CORTEX_ENGINE_API_KEY", "")
        if include_supermemory:
            targets.append(HttpTarget("supermemory:memories", supermemory_url, namespace, resolve_api_key(),
                                      ingest_extras={"taskType": "memory"}, search_extras={"searchMode": "memories"}))
        if include_engine:
            targets.append(HttpTarget("supercortex:memories", engine_url, namespace, key,
                                      ingest_extras={"taskType": "memory"}, search_extras={"searchMode": "memories"}))
            targets.append(HttpTarget("supercortex:combined", engine_url, namespace, key,
                                      search_extras={"searchMode": "combined"}))
            targets.append(HttpTarget("supercortex:hybrid", engine_url, namespace, key))
        return targets
    if include_supermemory:
        targets.append(HttpTarget("supermemory", supermemory_url, namespace, resolve_api_key(),
                                  ingest_extras={"taskType": "superrag"}, search_extras={"searchMode": "chunks"}))
    if include_engine:
        key = os.getenv("SUPER_CORTEX_ENGINE_API_KEY", "")
        targets.append(HttpTarget("supercortex:hybrid", engine_url, namespace, key))
        targets.append(HttpTarget("supercortex:lexical", engine_url, namespace, key, search_extras={"searchMode": "lexical"}))
        targets.append(HttpTarget("supercortex:vector", engine_url, namespace, key, search_extras={"searchMode": "vector"}))
    return targets


@eval_app.command("ingest")
def ingest(
    namespace: str = typer.Option("eval-v1"),
    data_dir: Path = typer.Option(DEFAULT_DIR),
    engine: bool = typer.Option(True), supermemory: bool = typer.Option(True),
    engine_url: str = typer.Option("http://127.0.0.1:6768"),
    supermemory_url: str = typer.Option("http://127.0.0.1:6767"),
    memories: bool = typer.Option(False, help="Ingest with taskType=memory (LLM extraction) instead of superrag"),
    limit: int = typer.Option(0, help="Only the first N corpus documents (0 = all)"),
) -> None:
    """Load the corpus into each target. Default taskType=superrag (no LLM extraction)."""
    corpus = load_jsonl(data_dir / "corpus.jsonl")
    corpus = corpus[:limit] if limit else corpus
    for target in _targets(namespace, engine, supermemory, engine_url, supermemory_url, memories):
        if target.name.endswith((":lexical", ":vector")) or (memories and target.name.endswith((":hybrid", ":combined"))):
            continue  # same store as supercortex:hybrid
        target.ingest(corpus)
        typer.echo(f"{target.name}: {len(corpus)} documents")


@eval_app.command("run")
def run(
    namespace: str = typer.Option("eval-v1"),
    data_dir: Path = typer.Option(DEFAULT_DIR),
    engine: bool = typer.Option(True), supermemory: bool = typer.Option(True),
    engine_url: str = typer.Option("http://127.0.0.1:6768"),
    supermemory_url: str = typer.Option("http://127.0.0.1:6767"),
    k: int = typer.Option(10),
    label: str = typer.Option("run"),
    memories: bool = typer.Option(False, help="Score learned-memory search (hits map to their source documents)"),
    limit: int = typer.Option(0, help="Corpus size that was ingested (0 = all); queries outside it are dropped"),
) -> None:
    """Evaluate every target plus the random control; write JSON and Markdown reports."""
    corpus = load_jsonl(data_dir / "corpus.jsonl")
    corpus = corpus[:limit] if limit else corpus
    in_corpus = {d["id"] for d in corpus}
    queries = [q for q in load_jsonl(data_dir / "queries.jsonl") if q["relevant"][0] in in_corpus]
    control = RandomTarget([d["id"] for d in corpus])
    targets = _targets(namespace, engine, supermemory, engine_url, supermemory_url, memories) + [control]
    report = evaluate(targets, queries, k)
    comparisons = {}
    if engine and supermemory and not memories:
        comparisons["supercortex:hybrid − supermemory"] = compare(report, "supercortex:hybrid", "supermemory")
    if engine and supermemory and memories:
        comparisons["supercortex:memories − supermemory:memories"] = compare(report, "supercortex:memories", "supermemory:memories")
    check = control_check(report, control.name)
    md = render_markdown(report, comparisons, check)
    out = data_dir / "reports"
    out.mkdir(parents=True, exist_ok=True)
    slim = {**report, "targets": {n: {k2: v for k2, v in t.items() if k2 != "per_query"} for n, t in report["targets"].items()}}
    (out / f"{label}.json").write_text(json.dumps({"report": slim, "comparisons": comparisons, "control": check}, indent=2))
    (out / f"{label}.md").write_text(md + "\n")
    typer.echo(md)


@engine_app.command("serve")
def serve() -> None:
    """Run the engine API (SUPER_CORTEX_ENGINE_DB / _HOST / _PORT / _API_KEY, SUPER_CORTEX_EMBEDDER)."""
    from ..engine.app import main

    main()


@engine_app.command("dream")
def dream(
    max_requests: int = typer.Option(..., help="Hard cap on Gemini requests for this run"),
    db: Path = typer.Option(Path(os.getenv("SUPER_CORTEX_ENGINE_DB", str(Path.home() / ".super-cortex" / "engine.db")))),
    daily_budget: int = typer.Option(200, help="Stop when today's (Pacific) request count reaches this"),
    rpm: float = typer.Option(12.0, help="Requests per minute (free tier for flash-lite is 15)"),
    docs_per_request: int = typer.Option(3),
) -> None:
    """Run dreaming once over the pending queue (Gemini free tier; needs GEMINI_API_KEY)."""
    from ..engine.dreaming import GeminiExtractor, run_dreaming
    from ..engine.embedder import default_embedder
    from ..engine.store import EngineStore

    store = EngineStore(db, default_embedder())
    stats = run_dreaming(store, GeminiExtractor(), max_requests=max_requests, daily_budget=daily_budget, rpm=rpm,
                         docs_per_request=docs_per_request)
    typer.echo(json.dumps({**stats.as_dict(), "queue": store.dream_counts()}, indent=2))
