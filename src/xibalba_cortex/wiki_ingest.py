"""Ingest the Integrity Protocol wiki (integrity-core/docs/wiki/) as graph memory.

Per docs/wiki/WIKI_SCHEMA.md (read before building this, not guessed): the wiki is the
canonical, actively-maintained knowledge base for the Integrity Protocol monorepo -- one page
per concept/entity/query under concepts/, entities/, queries/, each with required YAML
frontmatter (title, type, tags, confidence, source_files) and required `[Title](relative.md)`
wikilinks to other pages (minimum 2 per page). That structure is what this ingests as an actual
entity graph, not just prose: one entity per page (subject=title, predicate=is_a, object=type),
one relates_to relation per wikilink that resolves to another wiki page (links leaving the wiki
tree, e.g. into docs/design/ or spec/, are left as plain content -- they're not pages this store
has memories for).

Idempotent by design, safe to re-run after the wiki changes:
  - Memory storage: store_memory's own content-hash dedup (find_memory_id_by_content) means an
    unchanged page reuses its existing memory; a changed page calls supersede_memory instead of
    creating a duplicate, keyed by the page's own locator (file://<path>).
  - Entities: link_entities already reuses entities by (normalized_name, entity_type) via
    _get_or_create_entity -- no duplicate entity nodes across runs.
  - Relations: unlike entities, relations have no uniqueness constraint in the schema (multiple
    evidence for the same claim is a legitimate use elsewhere), so this module tracks
    (subject, predicate, object) triples already present before writing and skips exact repeats
    itself, rather than assuming the store does it.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml

from .config import load_config
from .store import GraphStore

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[[^\]]+\]\(([^)\s]+\.md)[^)]*\)")
_WIKI_SUBDIRS = ("concepts", "entities", "queries")


def _parse_page(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    frontmatter = yaml.safe_load(match.group(1)) or {}
    body = text[match.end():]
    return frontmatter, body


def _resolve_wikilinks(page_path: Path, body: str, path_to_title: dict[Path, str]) -> list[str]:
    """Titles of other wiki pages this page links to -- only links that resolve to a real page
    already indexed in path_to_title; links leaving docs/wiki/ (../../design/..., ../../../spec/...)
    resolve to paths outside that map and are correctly skipped, not guessed at.
    """
    titles = []
    for match in _WIKILINK_RE.finditer(body):
        target = (page_path.parent / match.group(1)).resolve()
        title = path_to_title.get(target)
        if title:
            titles.append(title)
    return titles


def ingest_wiki(store: GraphStore, wiki_dir: str | Path) -> dict[str, object]:
    wiki_dir = Path(wiki_dir).expanduser().resolve()
    page_paths = sorted(
        p for subdir in _WIKI_SUBDIRS for p in (wiki_dir / subdir).glob("*.md")
    )

    parsed = {path: _parse_page(path) for path in page_paths}
    path_to_title = {
        path: frontmatter["title"]
        for path, (frontmatter, _body) in parsed.items()
        if frontmatter.get("title")
    }

    existing_relation_triples = {
        (r["subject_name"], r["predicate"], r["object_name"]) for r in store.list_relations(limit=10000)
    }

    stored_memories: list[str] = []
    reused_memories: list[str] = []
    resynced_memories: list[str] = []
    relations_created = 0
    relations_skipped_existing = 0
    skipped_no_frontmatter: list[str] = []

    for path, (frontmatter, body) in parsed.items():
        title = frontmatter.get("title")
        if not title:
            skipped_no_frontmatter.append(str(path))
            continue
        locator = f"file://{path}"
        page_type = frontmatter.get("type", "unknown")

        existing_id = store.find_memory_id_by_content(body)
        if existing_id:
            memory_id = existing_id
            reused_memories.append(memory_id)
        else:
            # Any key beyond store_memory's known source fields (kind, locator, role, ...) is
            # automatically folded into the returned source.metadata -- no separate "metadata"
            # wrapper key needed (nesting one would land as source.metadata.metadata, not
            # source.metadata.title).
            source = {
                "kind": "imported_document",
                "locator": locator,
                "title": title,
                "wiki_type": page_type,
                "tags": frontmatter.get("tags", []),
                "confidence": frontmatter.get("confidence"),
            }
            prior_id = store.find_memory_id_by_locator(locator)
            if prior_id:
                memory = store.supersede_memory(
                    prior_id, body, source=source, status="active", evidence_class="extracted_proposition"
                )
                resynced_memories.append(memory["id"])
            else:
                memory = store.store_memory(
                    body, source=source, status="active", evidence_class="extracted_proposition"
                )
                stored_memories.append(memory["id"])
            memory_id = memory["id"]

        is_a_triple = (title, "is_a", page_type)
        if is_a_triple not in existing_relation_triples:
            store.link_entities(title, "is_a", page_type, evidence_memory_id=memory_id)
            existing_relation_triples.add(is_a_triple)
            relations_created += 1
        else:
            relations_skipped_existing += 1

        for linked_title in _resolve_wikilinks(path, body, path_to_title):
            triple = (title, "relates_to", linked_title)
            if triple in existing_relation_triples:
                relations_skipped_existing += 1
                continue
            store.link_entities(title, "relates_to", linked_title, evidence_memory_id=memory_id)
            existing_relation_triples.add(triple)
            relations_created += 1

    return {
        "pages_found": len(page_paths),
        "stored_memories": stored_memories,
        "reused_memories": reused_memories,
        "resynced_memories": resynced_memories,
        "relations_created": relations_created,
        "relations_skipped_existing": relations_skipped_existing,
        "skipped_no_frontmatter": skipped_no_frontmatter,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, help="xibalba-cortex profile home")
    parser.add_argument(
        "--wiki-dir", required=True, help="path to integrity-core/docs/wiki"
    )
    args = parser.parse_args()

    config = load_config(home=args.home)
    store = GraphStore(config.storage.home, profile_id=config.profile_id, quotas=config.quotas.as_dict())
    try:
        result = ingest_wiki(store, args.wiki_dir)
        print(
            f"pages_found={result['pages_found']} "
            f"stored={len(result['stored_memories'])} "
            f"reused={len(result['reused_memories'])} "
            f"resynced={len(result['resynced_memories'])} "
            f"relations_created={result['relations_created']} "
            f"relations_skipped_existing={result['relations_skipped_existing']}"
        )
        if result["skipped_no_frontmatter"]:
            print(f"skipped (no frontmatter): {result['skipped_no_frontmatter']}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
