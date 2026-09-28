from __future__ import annotations

import sqlite3

from xibalba_cortex.canonical import (
    CANONICAL_JSON_V1,
    CANONICAL_JSON_V2,
    canonical_json_bytes,
    canonical_json_v2_bytes,
)
from xibalba_cortex.store import GraphStore


def test_sdk_jcs_v2_is_distinct_from_historical_json_v1_for_non_ascii():
    value = {"text": "café"}

    assert CANONICAL_JSON_V1 != CANONICAL_JSON_V2
    assert canonical_json_bytes(value) == b'{"text":"caf\\u00e9"}'
    assert canonical_json_v2_bytes(value) == '{"text":"café"}'.encode("utf-8")


def test_new_store_uses_sdk_jcs_and_reports_its_version(tmp_path):
    home = tmp_path / "graph"
    store = GraphStore(home)

    assert store.status()["schema_version"] == 16
    assert store.status()["canonicalization"] == CANONICAL_JSON_V2
    assert store._canonical_json({"text": "café"}) == '{"text":"café"}'
    store.close()
    readonly = GraphStore(home, readonly=True)
    assert readonly.status()["canonicalization"] == CANONICAL_JSON_V2
    readonly.close()


def test_legacy_store_tag_keeps_historical_canonicalization(tmp_path):
    home = tmp_path / "graph"
    store = GraphStore(home)
    store.close()
    connection = sqlite3.connect(home / "graph-memory.sqlite3")
    connection.execute(
        "UPDATE deployment_profile SET canonicalization = ? WHERE id = 1",
        (CANONICAL_JSON_V1,),
    )
    connection.commit()
    connection.close()

    reopened = GraphStore(home)
    assert reopened.status()["canonicalization"] == CANONICAL_JSON_V1
    assert reopened._canonical_json({"text": "café"}) == '{"text":"caf\\u00e9"}'
    reopened.close()
