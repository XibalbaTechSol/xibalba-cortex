import sqlite3

from xibalba_cortex.ingest_tokens import issue_token, list_tokens, revoke_token, verify_token


def test_issued_token_verifies_and_returns_its_label(tmp_path):
    token = issue_token(tmp_path, "perplexity-personal")
    assert verify_token(tmp_path, token) == "perplexity-personal"


def test_unknown_token_does_not_verify(tmp_path):
    issue_token(tmp_path, "harness-a")
    assert verify_token(tmp_path, "not-a-real-token") is None


def test_empty_or_missing_token_does_not_verify(tmp_path):
    issue_token(tmp_path, "harness-a")
    assert verify_token(tmp_path, "") is None


def test_revoked_token_no_longer_verifies(tmp_path):
    token = issue_token(tmp_path, "harness-a")
    [row] = list_tokens(tmp_path)
    assert revoke_token(tmp_path, row["id"]) is True
    assert verify_token(tmp_path, token) is None


def test_revoking_an_unknown_or_already_revoked_id_reports_false(tmp_path):
    assert revoke_token(tmp_path, "does-not-exist") is False
    token = issue_token(tmp_path, "harness-a")
    [row] = list_tokens(tmp_path)
    revoke_token(tmp_path, row["id"])
    assert revoke_token(tmp_path, row["id"]) is False


def test_list_tokens_never_exposes_the_raw_token_or_its_hash(tmp_path):
    raw_token = issue_token(tmp_path, "harness-a")
    [row] = list_tokens(tmp_path)
    assert "token_hash" not in row
    assert "token" not in row
    assert raw_token not in str(row)


def test_multiple_harnesses_are_independently_issued_and_revoked(tmp_path):
    token_a = issue_token(tmp_path, "harness-a")
    token_b = issue_token(tmp_path, "harness-b")
    rows = {row["label"]: row["id"] for row in list_tokens(tmp_path)}

    revoke_token(tmp_path, rows["harness-a"])

    assert verify_token(tmp_path, token_a) is None
    assert verify_token(tmp_path, token_b) == "harness-b"


def test_a_single_shared_deployment_is_just_one_row(tmp_path):
    """No special-cased 'shared token' mode -- a single deployment issuing one token under
    a shared label is just the n=1 case of the same mechanism."""
    token = issue_token(tmp_path, "default")
    assert len(list_tokens(tmp_path)) == 1
    assert verify_token(tmp_path, token) == "default"


def test_verify_updates_last_used_at(tmp_path):
    token = issue_token(tmp_path, "harness-a")
    [before] = list_tokens(tmp_path)
    assert before["last_used_at"] is None

    verify_token(tmp_path, token)

    [after] = list_tokens(tmp_path)
    assert after["last_used_at"] is not None


def test_legacy_token_table_gets_least_privilege_defaults(tmp_path):
    database = tmp_path / "ingest_tokens.sqlite3"
    with sqlite3.connect(database) as conn:
        conn.execute(
            """CREATE TABLE ingest_tokens (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_used_at TEXT,
                revoked_at TEXT
            )"""
        )

    issue_token(tmp_path, "migration-trigger")

    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO ingest_tokens(id, label, token_hash) VALUES (?, ?, ?)",
            ("legacy-default-check", "legacy", "not-a-real-hash"),
        )
        profile_id, roles_json, scopes_json = conn.execute(
            "SELECT profile_id, roles_json, scopes_json FROM ingest_tokens WHERE id = ?",
            ("legacy-default-check",),
        ).fetchone()

    assert profile_id == "default"
    assert roles_json == '["reader"]'
    assert scopes_json == '["memory:read"]'


def test_issue_rejects_an_empty_label(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        issue_token(tmp_path, "")
    with pytest.raises(ValueError):
        issue_token(tmp_path, "   ")
