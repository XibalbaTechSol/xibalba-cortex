from pathlib import Path

from xibalba_graph.store import GraphStore
from xibalba_graph.wiki_ingest import ingest_wiki


def _write_page(path: Path, *, title: str, page_type: str, tags: list[str], body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tags_yaml = "[" + ", ".join(tags) + "]"
    path.write_text(
        f"---\ntitle: {title}\ntype: {page_type}\ntags: {tags_yaml}\nconfidence: high\n---\n{body}\n"
    )


def _wiki_fixture(tmp_path: Path) -> Path:
    wiki_dir = tmp_path / "wiki"
    _write_page(
        wiki_dir / "concepts" / "bcc.md",
        title="Behavioral Commitment Chain",
        page_type="concept",
        tags=["cryptography"],
        body=(
            "A signed commitment object. See [DID](did.md) for identity binding and "
            "[out-of-tree design note](../../design/bcc-design.md) for background."
        ),
    )
    _write_page(
        wiki_dir / "concepts" / "did.md",
        title="DID",
        page_type="concept",
        tags=["identity"],
        body="A decentralized identifier, referenced by [BCC](bcc.md).",
    )
    _write_page(
        wiki_dir / "entities" / "oracle.md",
        title="Integrity Oracle",
        page_type="entity",
        tags=["infrastructure"],
        body="The Rust/Axum scoring service, no outbound wikilinks in this fixture.",
    )
    # A page with no frontmatter -- should be skipped, not crash the run.
    (wiki_dir / "queries").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "queries" / "stray.md").write_text("# No frontmatter here\n")
    return wiki_dir


def test_ingest_wiki_creates_memories_entities_and_relations(tmp_path):
    store = GraphStore(tmp_path / "graph")
    wiki_dir = _wiki_fixture(tmp_path)

    result = ingest_wiki(store, wiki_dir)

    assert result["pages_found"] == 4
    assert len(result["stored_memories"]) == 3
    assert result["skipped_no_frontmatter"] == [str((wiki_dir / "queries" / "stray.md").resolve())]

    counts = store.counts()
    assert counts["memories"] == 3
    # 3 pages -> 3 entities, plus 3 "is_a" object entities (concept x2, entity x1, deduped to
    # "concept" and "entity") -> 5 total: BCC, DID, Integrity Oracle, concept, entity.
    assert counts["entities"] == 5

    relations = store.list_relations()
    triples = {(r["subject_name"], r["predicate"], r["object_name"]) for r in relations}
    assert ("Behavioral Commitment Chain", "is_a", "concept") in triples
    assert ("Integrity Oracle", "is_a", "entity") in triples
    # In-tree wikilink resolves to a relation both directions (each page links the other).
    assert ("Behavioral Commitment Chain", "relates_to", "DID") in triples
    assert ("DID", "relates_to", "Behavioral Commitment Chain") in triples
    # Out-of-tree link (../../design/bcc-design.md) does not resolve to any wiki page, so no
    # relates_to relation should exist for it.
    assert not any(r["predicate"] == "relates_to" and "design" in (r["object_name"] or "") for r in relations)
    store.close()


def test_ingest_wiki_is_idempotent_on_rerun(tmp_path):
    store = GraphStore(tmp_path / "graph")
    wiki_dir = _wiki_fixture(tmp_path)

    ingest_wiki(store, wiki_dir)
    first_counts = store.counts()

    result_two = ingest_wiki(store, wiki_dir)
    second_counts = store.counts()

    assert second_counts == first_counts
    assert result_two["stored_memories"] == []
    assert result_two["relations_created"] == 0
    assert len(result_two["reused_memories"]) == 3
    store.close()


def test_ingest_wiki_resyncs_a_changed_page_without_duplicating(tmp_path):
    store = GraphStore(tmp_path / "graph")
    wiki_dir = _wiki_fixture(tmp_path)
    ingest_wiki(store, wiki_dir)

    _write_page(
        wiki_dir / "concepts" / "bcc.md",
        title="Behavioral Commitment Chain",
        page_type="concept",
        tags=["cryptography"],
        body="Updated body text, referencing [DID](did.md) again.",
    )
    ingest_wiki(store, wiki_dir)

    memories = store.list_memories()
    bcc_memories = [m for m in memories if m["source"]["metadata"]["title"] == "Behavioral Commitment Chain"]
    assert len(bcc_memories) == 1
    assert "Updated body text" in bcc_memories[0]["content"]
    store.close()
