from unittest.mock import MagicMock, patch

import pytest

from xibalba_cortex.drive_ingest import ingest_drive
from xibalba_cortex.store import GraphStore


def _doc_response(text: str) -> dict:
    return {"body": {"content": [{"paragraph": {"elements": [{"textRun": {"content": text}}]}}]}}


def _files_list_response(files: list[dict]) -> dict:
    return {"files": files, "nextPageToken": None}


@pytest.fixture
def store(tmp_path):
    s = GraphStore(tmp_path / "graph")
    yield s
    s.close()


def _mock_services(files: list[dict], doc_texts: dict[str, str]):
    """Build fake drive_service/docs_service objects matching the chained
    .files().list().execute() / .documents().get().execute() call shape."""
    drive_service = MagicMock()
    drive_service.files.return_value.list.return_value.execute.return_value = _files_list_response(files)

    docs_service = MagicMock()

    def _get(documentId):
        result = MagicMock()
        result.execute.return_value = _doc_response(doc_texts[documentId])
        return result

    docs_service.documents.return_value.get.side_effect = _get
    return drive_service, docs_service


@patch("xibalba_cortex.drive_ingest._get_credentials", return_value=MagicMock())
@patch("xibalba_cortex.drive_ingest.build")
def test_ingest_drive_stores_google_docs_and_skips_unsupported(mock_build, _mock_creds, store, tmp_path):
    files = [
        {"id": "doc1", "name": "Integrity Protocol Overview", "mimeType": "application/vnd.google-apps.document",
         "modifiedTime": "2026-08-01T00:00:00Z", "owners": [{"emailAddress": "jacob.v.universe@gmail.com"}],
         "webViewLink": "https://docs.google.com/document/d/doc1"},
        {"id": "sheet1", "name": "Some Spreadsheet", "mimeType": "application/vnd.google-apps.spreadsheet",
         "modifiedTime": "2026-08-01T00:00:00Z", "owners": []},
    ]
    drive_service, docs_service = _mock_services(files, {"doc1": "Integrity Protocol overview content."})
    mock_build.side_effect = lambda name, version, credentials: (
        drive_service if name == "drive" else docs_service
    )

    result = ingest_drive(store, token_path=tmp_path / "token.json")

    assert result["files_found"] == 2
    assert len(result["stored_memories"]) == 1
    assert result["unsupported_skipped"] == [{"id": "sheet1", "name": "Some Spreadsheet", "mimeType": "application/vnd.google-apps.spreadsheet"}]

    memory = store.get_memory(result["stored_memories"][0])
    assert memory["content"] == "Integrity Protocol overview content."
    assert memory["source"]["metadata"]["title"] == "Integrity Protocol Overview"
    assert memory["source"]["locator"] == "drive://doc1"


@patch("xibalba_cortex.drive_ingest._get_credentials", return_value=MagicMock())
@patch("xibalba_cortex.drive_ingest.build")
def test_ingest_drive_skips_unchanged_and_resyncs_changed(mock_build, _mock_creds, store, tmp_path):
    file_v1 = {"id": "doc1", "name": "Doc", "mimeType": "application/vnd.google-apps.document",
               "modifiedTime": "2026-08-01T00:00:00Z", "owners": []}

    drive_service, docs_service = _mock_services([file_v1], {"doc1": "Version one content."})
    mock_build.side_effect = lambda name, version, credentials: (
        drive_service if name == "drive" else docs_service
    )
    first = ingest_drive(store, token_path=tmp_path / "token.json")
    assert len(first["stored_memories"]) == 1

    # Re-run with the same modifiedTime -- should skip without re-fetching document content.
    second = ingest_drive(store, token_path=tmp_path / "token.json")
    assert second["unchanged_skipped"] == ["doc1"]
    assert second["stored_memories"] == []
    assert second["resynced_memories"] == []

    # Re-run with a changed modifiedTime and new content -- should supersede, not duplicate.
    file_v2 = dict(file_v1, modifiedTime="2026-08-02T00:00:00Z")
    drive_service.files.return_value.list.return_value.execute.return_value = _files_list_response([file_v2])
    docs_service.documents.return_value.get.side_effect = lambda documentId: MagicMock(
        execute=MagicMock(return_value=_doc_response("Version two content."))
    )
    third = ingest_drive(store, token_path=tmp_path / "token.json")
    assert third["resynced_memories"] == [first["stored_memories"][0]] or len(third["resynced_memories"]) == 1

    active_memories = store.list_memories()
    doc1_memories = [m for m in active_memories if m["source"]["locator"] == "drive://doc1"]
    assert len(doc1_memories) == 1
    assert doc1_memories[0]["content"] == "Version two content."


@patch("xibalba_cortex.drive_ingest._get_credentials", return_value=MagicMock())
@patch("xibalba_cortex.drive_ingest.build")
def test_ingest_drive_extracts_plain_text_and_markdown(mock_build, _mock_creds, store, tmp_path):
    files = [
        {"id": "md1", "name": "Notes.md", "mimeType": "text/markdown",
         "modifiedTime": "2026-08-01T00:00:00Z", "owners": []},
    ]
    drive_service = MagicMock()
    drive_service.files.return_value.list.return_value.execute.return_value = _files_list_response(files)
    drive_service.files.return_value.get_media.return_value.execute.return_value = b"# Markdown content"
    docs_service = MagicMock()
    mock_build.side_effect = lambda name, version, credentials: (
        drive_service if name == "drive" else docs_service
    )

    result = ingest_drive(store, token_path=tmp_path / "token.json")

    assert len(result["stored_memories"]) == 1
    memory = store.get_memory(result["stored_memories"][0])
    assert memory["content"] == "# Markdown content"


def test_ingest_drive_raises_when_token_missing(store, tmp_path):
    with pytest.raises(FileNotFoundError, match="no Google OAuth token"):
        ingest_drive(store, token_path=tmp_path / "no-such-token.json")
