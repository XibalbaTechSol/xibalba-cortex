"""Regression coverage: transcript_ingest, wiki_ingest, and session_sync must be
able to run against a real, non-default tenant profile home (the shape
xibalba_cortex.tenant_onboarding provisions) without a store profile-mismatch
error. Before this fix all three constructed GraphStore(home) directly, which
always defaulted to profile_id="default" and crashed against any profile whose
config.yaml records a real tenant profile_id -- these connectors could never
actually be pointed at a properly-provisioned tenant profile at all."""
from __future__ import annotations

import json
import sys

import yaml

from xibalba_cortex.session_sync import finalize
from xibalba_cortex.store import GraphStore
from xibalba_cortex.transcript_ingest import main as transcript_main
from xibalba_cortex.wiki_ingest import main as wiki_main


def _provision(home, profile_id: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(yaml.safe_dump({
        "profile_id": profile_id,
        "storage": {"backend": "sqlite", "home": str(home)},
    }))


def test_transcript_ingest_main_runs_against_a_real_tenant_profile(tmp_path, monkeypatch):
    home = tmp_path / "tenant-a"
    _provision(home, "tenant-a")
    transcript = tmp_path / "s.jsonl"
    transcript.write_text(json.dumps({
        "type": "user", "sessionId": "s1", "uuid": "u1",
        "message": {"role": "user", "content": "hello"},
    }) + "\n")

    monkeypatch.setattr(sys, "argv", ["prog", "--home", str(home), "--transcript", str(transcript)])
    transcript_main()  # must not raise a store profile-mismatch error

    store = GraphStore(home, profile_id="tenant-a")
    assert store.status()["memory_count"] >= 1
    store.close()


def test_wiki_ingest_main_runs_against_a_real_tenant_profile(tmp_path, monkeypatch):
    home = tmp_path / "tenant-b"
    _provision(home, "tenant-b")
    wiki_dir = tmp_path / "wiki"
    (wiki_dir / "concepts").mkdir(parents=True)
    (wiki_dir / "concepts" / "thing.md").write_text(
        "---\ntitle: Thing\ntype: concept\ntags: []\nconfidence: high\nsource_files: []\n---\n"
        "See [Other](../concepts/other.md) and [Another](../concepts/another.md).\n"
    )
    (wiki_dir / "concepts" / "other.md").write_text(
        "---\ntitle: Other\ntype: concept\ntags: []\nconfidence: high\nsource_files: []\n---\n"
        "See [Thing](thing.md) and [Another](another.md).\n"
    )
    (wiki_dir / "concepts" / "another.md").write_text(
        "---\ntitle: Another\ntype: concept\ntags: []\nconfidence: high\nsource_files: []\n---\n"
        "See [Thing](thing.md) and [Other](other.md).\n"
    )

    monkeypatch.setattr(sys, "argv", ["prog", "--home", str(home), "--wiki-dir", str(wiki_dir)])
    wiki_main()  # must not raise a store profile-mismatch error

    store = GraphStore(home, profile_id="tenant-b")
    assert store.status()["memory_count"] >= 3
    store.close()


def test_session_sync_finalize_runs_against_a_real_tenant_profile(tmp_path):
    home = tmp_path / "tenant-c"
    _provision(home, "tenant-c")

    result = finalize(session_id="drill-1", runtime="claude", source_home=home)  # must not raise

    assert result["session"]["external_session_id"] == "drill-1"
    store = GraphStore(home, profile_id="tenant-c")
    assert store.status()["memory_count"] >= 1
    store.close()
