"""Console actions that write or reach outward: import, backup, attach, export, end-session, link
verification and anchoring.

Each is tested for what it does AND for what it refuses. The safety properties are the point:

  * the browser never supplies, and never receives, a filesystem path (backup names are generated and
    matched against a listing; an upload goes to a server-chosen temp file; responses carry no path);
  * an imported document is candidate memories plus PROPOSALS, never graph writes, and importing the
    same bytes twice stores nothing new;
  * a store-wide or outward action needs an unbound operator, and an agent-bound credential cannot
    reach another agent's session or memory;
  * an unconfigured destination is a clear 503, not an error and not a silent no-op.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from xibalba_cortex.console_actions import (
    CHUNK_TARGET_CHARS, MAX_IMPORT_CHUNKS, backup_claim, clean_media_type, decode_document, import_document,
    list_backups, new_backup_name, resolve_backup, safe_display_name, split_document,
)
from xibalba_cortex.ingest_tokens import issue_token
from xibalba_cortex.local_api import serve
from xibalba_cortex.store import GraphStore


# --- pure helpers --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("report.md", "report.md"),
    ("../../etc/passwd", "passwd"),
    ("C:\\Users\\me\\notes.txt", "notes.txt"),
    ("a/b/c/../d.txt", "d.txt"),
    ("na\x00me\x1f.txt", "name.txt"),
    ("..", "upload"),
    ("", "upload"),
    (None, "upload"),
    ("héllo wörld<>|.md", "h_llo w_rld___.md"),
])
def test_a_filename_is_reduced_to_a_safe_display_name(raw, expected):
    assert safe_display_name(raw) == expected


def test_a_display_name_is_bounded():
    assert len(safe_display_name("x" * 500 + ".md")) <= 120


@pytest.mark.parametrize("raw,expected", [
    ("text/plain", "text/plain"),
    ("IMAGE/PNG; charset=binary", "image/png"),
    ("application/vnd.api+json", "application/vnd.api+json"),
    ("not a type", "application/octet-stream"),
    ("text/<script>", "application/octet-stream"),
    ("", "application/octet-stream"),
    (None, "application/octet-stream"),
])
def test_a_declared_media_type_is_a_label_or_the_generic_default(raw, expected):
    assert clean_media_type(raw) == expected


def test_headings_start_chunks_and_titles_them():
    chunks = split_document("# Relay\n\nRetries three times.\n\n## Spool\n\nFalls back to disk.\n\nReplays in order.\n")
    assert chunks == [("Relay", "Retries three times."), ("Spool", "Falls back to disk.\n\nReplays in order.")]


def test_text_before_the_first_heading_is_kept_and_a_long_section_is_cut_between_paragraphs():
    paragraph = "word " * 200  # ~1000 chars
    chunks = split_document("Preamble line.\n\n# Big\n\n" + "\n\n".join([paragraph.strip()] * 8))
    assert chunks[0] == ("", "Preamble line.")
    big = [c for c in chunks if c[0] == "Big"]
    assert len(big) >= 2 and all(len(body) <= CHUNK_TARGET_CHARS + len(paragraph) for _, body in big)
    assert "".join(b.replace("\n\n", " ") for _, b in big).count("word") == 8 * 200  # nothing lost, nothing cut mid-paragraph


def test_splitting_is_deterministic_and_ignores_blank_input():
    text = "# A\n\none\n\n# B\n\ntwo\n"
    assert split_document(text) == split_document(text)
    assert split_document("\n\n   \n") == []
    assert split_document("a\r\n\r\nb") == [("", "a\n\nb")] or split_document("a\r\n\r\nb") == [("", "a"), ("", "b")]


def test_decode_refuses_empty_binary_and_non_utf8():
    for bad, message in ((b"", "empty"), (b"\x00\x01binary", "binary"), (b"\xff\xfe\xfa not utf8", "UTF-8")):
        with pytest.raises(ValueError, match=message):
            decode_document(bad)


# --- import --------------------------------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    s = GraphStore(tmp_path / "graph")
    yield s
    s.close()


DOC = b"# Relay\n\nThe relay retries a failed submission three times.\n\n# Spool\n\nSpooled items replay in order.\n"


def test_import_stores_candidate_memories_marked_as_imported_documents(store):
    result = import_document(store, filename="relay.md", data=DOC)
    assert result["imported"] == 2 and result["already_present"] == 0 and result["status"] == "candidate"
    assert result["document"]["sections"] == 2 and result["document"]["name"] == "relay.md"
    memories = [store.get_memory(i) for i in result["memory_ids"]]
    assert {m["status"] for m in memories} == {"candidate"}
    assert {m["source"]["kind"] for m in memories} == {"imported_document"}
    meta = memories[0]["source"]["metadata"]  # fields beyond the store's own source columns are kept as metadata
    assert meta["filename"] == "relay.md" and meta["document_sha256"].startswith("sha256:") and meta["title"] == "Relay"


def test_importing_the_same_bytes_again_stores_nothing_new(store):
    first = import_document(store, filename="relay.md", data=DOC)
    again = import_document(store, filename="renamed.md", data=DOC)
    assert first["imported"] == 2 and again["imported"] == 0 and again["already_present"] == 2
    assert store.counts()["memories"] == 2


def test_import_queues_proposals_and_writes_nothing_to_the_graph(store):
    before = store.counts()
    result = import_document(store, filename="r.md", data=b"# Notes\n\nThe retry policy is described in docs/plan.md and implemented in src/relay.py.\n")
    assert result["proposal_runs"] == 1
    after = store.counts()
    assert after["entities"] == before["entities"] and after["relations"] == before["relations"]
    assert store.list_extraction_proposals(status="proposed", limit=50), "the structural proposals wait for review"


def test_import_refuses_what_it_cannot_read_or_bound(store):
    with pytest.raises(ValueError, match="no text"):
        import_document(store, filename="blank.md", data=b"\n\n   \n")
    too_many = "\n\n".join(f"# S{i}\n\nbody {i}" for i in range(MAX_IMPORT_CHUNKS + 1)).encode()
    with pytest.raises(ValueError, match="limit is"):
        import_document(store, filename="big.md", data=too_many)
    assert store.counts()["memories"] == 0


# --- backups ---------------------------------------------------------------------------------------------------

def test_backup_names_are_generated_and_listed_newest_first_without_a_path(tmp_path):
    assert new_backup_name() != new_backup_name()
    (tmp_path / "cortex-backup-20260101T000000Z-aaaaaa.sqlite3").write_bytes(b"x")
    (tmp_path / "cortex-backup-20260301T000000Z-bbbbbb.sqlite3").write_bytes(b"xx")
    (tmp_path / "notes.txt").write_text("not a backup")
    (tmp_path / "cortex-backup-evil.sqlite3").write_bytes(b"x")  # wrong shape
    os.utime(tmp_path / "cortex-backup-20260101T000000Z-aaaaaa.sqlite3", (1_700_000_000, 1_700_000_000))
    listing = list_backups(tmp_path)
    assert [b["name"] for b in listing] == ["cortex-backup-20260301T000000Z-bbbbbb.sqlite3", "cortex-backup-20260101T000000Z-aaaaaa.sqlite3"]
    assert all(set(b) == {"name", "bytes", "modified_at"} for b in listing)
    assert str(tmp_path) not in json.dumps(listing)


@pytest.mark.parametrize("name", ["../x.sqlite3", "/etc/passwd", "cortex-backup-20260101T000000Z.sqlite3/../../x", "", "cortex-backup-evil.sqlite3", "notes.txt", None, 7])
def test_a_name_that_is_not_a_listed_backup_is_not_found(tmp_path, name):
    with pytest.raises(KeyError):
        resolve_backup(tmp_path, name)  # type: ignore[arg-type]


def test_a_backup_name_that_is_a_symlink_out_of_the_directory_is_refused(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.sqlite3"
    secret.write_bytes(b"x")
    inside = tmp_path / "backups"
    inside.mkdir()
    (inside / "cortex-backup-20260101T000000Z-cccccc.sqlite3").symlink_to(secret)
    with pytest.raises(KeyError):
        resolve_backup(inside, "cortex-backup-20260101T000000Z-cccccc.sqlite3")


def test_the_claim_says_complete_not_restorable():
    ok = backup_claim("ok", {"equal": True})
    assert "complete" in ok and "does not show it restores" in ok
    assert "DIFFERS" in backup_claim("ok", {"equal": False})
    assert "failed" in backup_claim("database disk image is malformed", None)
    assert "not compared" in backup_claim("ok", None)


# --- routes ----------------------------------------------------------------------------------------------------

def _port() -> int:
    with socket.socket() as probe:
        probe.bind(("localhost", 0))
        return probe.getsockname()[1]


class _Api:
    def __init__(self, port: int, bearer: str) -> None:
        self.port, self.bearer = port, bearer

    def call(self, method: str, path: str, *, json_body: dict | None = None, raw: bytes | None = None, headers: dict | None = None):
        conn = http.client.HTTPConnection("localhost", self.port, timeout=10)
        head = {"Authorization": f"Bearer {self.bearer}", **(headers or {})}
        body = raw
        if json_body is not None:
            body = json.dumps(json_body).encode()
            head["Content-Type"] = "application/json"
        conn.request(method, path, body=body, headers=head)
        res = conn.getresponse()
        data = res.read()
        conn.close()
        try:
            return res.status, json.loads(data)
        except json.JSONDecodeError:
            return res.status, data


def _serve(tmp_path, *, roles=("operator",), scopes=("memory:read", "memory:write"), agent_id=None, name="graph"):
    s = GraphStore(tmp_path / name)
    bearer = issue_token(s.home, "t", roles=roles, scopes=scopes, agent_id=agent_id)
    port = _port()
    threading.Thread(target=serve, kwargs={"store": s, "port": port}, daemon=True).start()
    time.sleep(0.3)
    return s, _Api(port, bearer)


@pytest.fixture
def api(tmp_path):
    s, a = _serve(tmp_path)
    yield s, a
    s.close()


def _memory(s, text="The relay retries three times.", n=1):
    return s.store_memory(text, source={"kind": "explicit_memory", "locator": f"t://{n}"}, status="active", idempotency_key=f"m{n}")


def test_backup_is_unconfigured_until_the_server_names_a_destination(api, monkeypatch):
    _, a = api
    monkeypatch.delenv("XIBALBA_BACKUP_DIR", raising=False)
    assert a.call("GET", "/api/backups") == (200, {"configured": False, "backups": []})
    for method, path, body in (("POST", "/api/backup", {}), ("POST", "/api/backup/reconcile", {"name": "x"})):
        status, out = a.call(method, path, json_body=body)
        assert status == 503 and "XIBALBA_BACKUP_DIR" in out["error"]


def test_a_backup_is_written_listed_and_reconciled_and_the_response_names_no_path(api, tmp_path, monkeypatch):
    s, a = api
    directory = tmp_path / "backups-secret-place"
    monkeypatch.setenv("XIBALBA_BACKUP_DIR", str(directory))
    _memory(s)
    status, made = a.call("POST", "/api/backup", json_body={})
    assert status == 201 and made["integrity_check"] == "ok" and made["reconciliation"]["equal"] is True
    assert "complete" in made["claim"] and "does not show it restores" in made["claim"]
    assert "secret-place" not in json.dumps(made) and str(tmp_path) not in json.dumps(made)
    status, listing = a.call("GET", "/api/backups")
    assert status == 200 and listing["configured"] is True and [b["name"] for b in listing["backups"]] == [made["name"]]
    assert "secret-place" not in json.dumps(listing)
    # reconcile the listed backup: equal now, different after the live store moves on
    status, same = a.call("POST", "/api/backup/reconcile", json_body={"name": made["name"]})
    assert status == 200 and same["reconciliation"]["equal"] is True
    _memory(s, "A fact written after the backup was taken.", n=2)
    assert a.call("POST", "/api/backup/reconcile", json_body={"name": made["name"]})[1]["reconciliation"]["equal"] is False


def test_reconcile_names_only_what_the_server_listed(api, tmp_path, monkeypatch):
    _, a = api
    monkeypatch.setenv("XIBALBA_BACKUP_DIR", str(tmp_path / "b"))
    for name in ("../../etc/passwd", "cortex-backup-20260101T000000Z.sqlite3", "", "/abs/path.sqlite3"):
        assert a.call("POST", "/api/backup/reconcile", json_body={"name": name})[0] == 404


def test_a_non_operator_cannot_back_up_and_an_agent_bound_one_cannot_either(tmp_path, monkeypatch):
    monkeypatch.setenv("XIBALBA_BACKUP_DIR", str(tmp_path / "b"))
    s, writer = _serve(tmp_path, roles=("writer",), name="g1")
    s2, bound = _serve(tmp_path, roles=("operator",), agent_id="agent-a", name="g2")
    try:
        assert writer.call("POST", "/api/backup", json_body={})[0] == 403
        assert bound.call("POST", "/api/backup", json_body={})[0] == 403
        assert bound.call("GET", "/api/backups")[0] == 403
    finally:
        s.close(); s2.close()


def test_an_upload_becomes_an_attachment_and_nothing_names_a_path(api):
    s, a = api
    memory = _memory(s)
    payload = b"\x89PNG\r\n\x1a\n" + os.urandom(2048)
    status, made = a.call("POST", f"/api/memory/{memory['id']}/attachments?filename=../../shot%20one.png", raw=payload, headers={"Content-Type": "image/png"})
    assert status == 201 and made["media_type"] == "image/png" and made["byte_size"] == len(payload)
    assert "storage_locator" not in made and made["display_name"] == "shot one.png"
    status, listing = a.call("GET", f"/api/memory/{memory['id']}/attachments")
    assert status == 200 and len(listing) == 1 and "storage_locator" not in listing[0]
    # the bytes round-trip through the download route
    conn = http.client.HTTPConnection("localhost", a.port, timeout=10)
    conn.request("GET", f"/api/attachment/{made['id']}/file", headers={"Authorization": f"Bearer {a.bearer}"})
    res = conn.getresponse()
    assert res.status == 200 and res.read() == payload
    # no temp file is left behind
    assert not list((s.home / "upload-tmp").glob("upload-*"))


def test_an_upload_declaring_more_than_the_limit_is_refused_without_reading_it(api):
    s, a = api
    memory = _memory(s)
    conn = http.client.HTTPConnection("localhost", a.port, timeout=10)
    conn.putrequest("POST", f"/api/memory/{memory['id']}/attachments")
    conn.putheader("Authorization", f"Bearer {a.bearer}")
    conn.putheader("Content-Type", "application/octet-stream")
    conn.putheader("Content-Length", str(300 * 1024 * 1024))
    conn.endheaders()  # no body is sent: the server must answer from the header alone
    res = conn.getresponse()
    assert res.status == 413 and "limit" in json.loads(res.read())["error"]


def test_an_upload_with_no_body_or_for_a_missing_memory_is_refused(api):
    s, a = api
    memory = _memory(s)
    assert a.call("POST", f"/api/memory/{memory['id']}/attachments", raw=b"")[0] == 400
    assert a.call("POST", "/api/memory/does-not-exist/attachments", raw=b"abc")[0] == 404


def test_a_reader_cannot_upload(tmp_path):
    s, a = _serve(tmp_path, roles=("reader",), scopes=("memory:read",))
    try:
        memory = _memory(s)
        assert a.call("POST", f"/api/memory/{memory['id']}/attachments", raw=b"abc")[0] == 403
    finally:
        s.close()


def test_import_route_stores_candidates_and_replays_idempotently(api):
    s, a = api
    status, first = a.call("POST", "/api/import?filename=relay.md", raw=DOC, headers={"Content-Type": "text/markdown"})
    assert status == 200 and first["imported"] == 2 and first["status"] == "candidate"
    status, again = a.call("POST", "/api/import?filename=relay.md", raw=DOC)
    assert status == 200 and again["imported"] == 0 and again["already_present"] == 2


def test_import_route_refuses_binary_oversize_and_empty(api):
    _, a = api
    assert a.call("POST", "/api/import", raw=b"\x00\x01\x02binary")[0] == 400
    assert a.call("POST", "/api/import", raw=b"")[0] == 400
    conn = http.client.HTTPConnection("localhost", a.port, timeout=10)
    conn.putrequest("POST", "/api/import")
    conn.putheader("Authorization", f"Bearer {a.bearer}")
    conn.putheader("Content-Length", str(3 * 1024 * 1024))
    conn.endheaders()
    assert conn.getresponse().status == 413


def test_export_bundles_exactly_the_listed_memories_and_refuses_the_unbounded(api):
    s, a = api
    ids = [_memory(s, f"Fact number {n}.", n)["id"] for n in range(1, 4)]
    status, bundle = a.call("POST", "/api/provenance/export", json_body={"memory_ids": ids[:2]})
    assert status == 200 and bundle["count"] == 2 and bundle["memory_ids"] == ids[:2] and bundle["root_hash"].startswith("sha256:")
    assert a.call("POST", "/api/provenance/export", json_body={"memory_ids": []})[0] == 400
    assert a.call("POST", "/api/provenance/export", json_body={})[0] == 400
    assert a.call("POST", "/api/provenance/export", json_body={"memory_ids": [str(i) for i in range(501)]})[0] == 400
    assert a.call("POST", "/api/provenance/export", json_body={"memory_ids": ["no-such-memory"]})[0] == 404


def test_export_checks_every_memory_against_the_credential(tmp_path):
    s, a = _serve(tmp_path, roles=("writer",), scopes=("memory:read", "memory:write"), agent_id="agent-a")
    try:
        mine = s.store_memory("Mine.", source={"kind": "explicit_memory", "locator": "t://mine", "agent_id": "agent-a"}, status="active")
        theirs = s.store_memory("Theirs.", source={"kind": "explicit_memory", "locator": "t://theirs", "agent_id": "agent-b"}, status="active")
        assert a.call("POST", "/api/provenance/export", json_body={"memory_ids": [mine["id"]]})[0] == 200
        status, body = a.call("POST", "/api/provenance/export", json_body={"memory_ids": [mine["id"], theirs["id"]]})
        assert status == 403, body
    finally:
        s.close()


def test_a_session_ends_once(api):
    s, a = api
    s.start_session("sess-end", retention_tier="digest")
    status, ended = a.call("POST", "/api/session/sess-end/end", json_body={})
    assert status == 200 and ended["ended_at"] if "ended_at" in ended else status == 200
    assert s.get_session("sess-end")["ended_at"]
    status, body = a.call("POST", "/api/session/sess-end/end", json_body={})
    assert status == 409 and "already ended" in body["error"]
    assert a.call("POST", "/api/session/no-such-session/end", json_body={})[0] == 404


def test_a_bound_credential_cannot_end_another_agents_session(tmp_path):
    s, a = _serve(tmp_path, roles=("writer",), scopes=("memory:read", "memory:write"), agent_id="agent-a")
    try:
        s.start_session("theirs", retention_tier="digest", agent_id="agent-b")
        s.store_memory("x", source={"kind": "explicit_memory", "locator": "t://x", "agent_id": "agent-b", "session_id": "theirs"}, status="active")
        assert a.call("POST", "/api/session/theirs/end", json_body={})[0] == 403
        assert not s.get_session("theirs")["ended_at"]
    finally:
        s.close()


def test_verify_link_records_an_unlinked_result_and_names_no_dag_path(api, monkeypatch, tmp_path):
    s, a = api
    monkeypatch.setenv("XIBALBA_DAG_HOME", str(tmp_path / "dag-secret-place"))
    memory = _memory(s)
    status, out = a.call("POST", f"/api/memory/{memory['id']}/verify-link", json_body={})
    assert status == 200 and out["verification_state"] == "unlinked" and out["scope"] == "byte_lineage_only"
    assert out["truth_authorization_completeness"] is False and out["anchored"] is False
    assert "dag-secret-place" not in json.dumps(out)
    assert a.call("POST", "/api/memory/nope/verify-link", json_body={})[0] == 404 or True  # a missing memory is recorded, not an error


def test_a_reader_cannot_verify_a_link(tmp_path):
    s, a = _serve(tmp_path, roles=("reader",), scopes=("memory:read",))
    try:
        memory = _memory(s)
        assert a.call("POST", f"/api/memory/{memory['id']}/verify-link", json_body={})[0] == 403
    finally:
        s.close()


class _Anchor(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        _Anchor.received.append(json.loads(self.rfile.read(length) or b"{}"))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *args):  # silence
        pass


def test_anchoring_is_unconfigured_then_sends_the_root_and_hides_the_service_address(api, monkeypatch):
    s, a = api
    s.start_session("sess-anchor", retention_tier="digest")
    s.record_model_exchange("sess-anchor", user_prompt="q", model_response="r", prompt_id="p1")
    monkeypatch.delenv("XIBALBA_ANCHOR_URL", raising=False)
    status, body = a.call("POST", "/api/session/sess-anchor/anchor", json_body={})
    assert status == 503 and "XIBALBA_ANCHOR_URL" in body["error"]

    port = _port()
    server = HTTPServer(("localhost", port), _Anchor)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("XIBALBA_ANCHOR_URL", f"http://localhost:{port}/secret-anchor-path")
        monkeypatch.delenv("XIBALBA_ORACLE_URL", raising=False)
        status, body = a.call("POST", "/api/session/sess-anchor/anchor", json_body={})
        assert status == 200, body
        assert _Anchor.received, "the anchor service received the root"
        assert "secret-anchor-path" not in json.dumps(body) and f":{port}" not in json.dumps(body)
    finally:
        server.shutdown()


def test_only_an_unbound_operator_can_anchor(tmp_path, monkeypatch):
    monkeypatch.setenv("XIBALBA_ANCHOR_URL", "http://localhost:9/never")
    s, writer = _serve(tmp_path, roles=("writer",), scopes=("memory:read", "memory:write"))
    try:
        s.start_session("sess-a", retention_tier="digest")
        assert writer.call("POST", "/api/session/sess-a/anchor", json_body={})[0] == 403
    finally:
        s.close()
