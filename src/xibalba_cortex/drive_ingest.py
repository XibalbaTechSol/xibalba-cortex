"""Ingest Integrity-Protocol-relevant Google Drive documents as graph memory.

Reuses the credential Hermes Agent's own "Google Workspace" skill already maintains at
~/.hermes/google_token.json (drive.readonly + documents.readonly scopes already granted,
confirmed live/refreshed, and already exercised against these exact documents once before --
see integrity-core/docs/drive/ORIGINAL_DOCUMENT_MANIFEST.json). No new OAuth app registration
here -- this only reads that existing token file, the same pattern
xibalba-agents/*/framework/skills/productivity/google-workspace/scripts/google_api.py already
uses (get_credentials/build_service), reimplemented minimally rather than importing that script
(it lives in a different project, per-persona-duplicated, not a shared library).

Requires the optional `drive` extra (google-api-python-client, google-auth, pypdf) --
deliberately not a core dependency, since most deployments of this store never touch Drive.

Broad sweep, not scoped to a fixed document list: `files().list` with a fullText query for
"Integrity Protocol" / "Xibalba Shield", paginated. Routes by mimeType:
  - application/vnd.google-apps.document -> Docs API documents().get(), plain-text extraction
    (same structure-walk google_api.py's docs_get() already implements).
  - application/pdf -> files().get_media() + pypdf text extraction.
  - anything else -> skipped and logged, not silently dropped (Sheets, Slides, images, etc.).

Idempotent by locator (drive://<file_id>) + Drive's own modifiedTime: unchanged files are
skipped without re-downloading; changed files call supersede_memory via
GraphStore.find_memory_id_by_locator rather than duplicating.
"""
from __future__ import annotations

import argparse
import io
from pathlib import Path
from typing import Any

try:  # Optional Drive extra.
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - exercised through _require_drive_extra.
    Request = None  # type: ignore[assignment]
    Credentials = None  # type: ignore[assignment]
    PdfReader = None  # type: ignore[assignment]

    def build(*_args: Any, **_kwargs: Any) -> Any:  # type: ignore[no-redef]
        _require_drive_extra()

from .connector_policy import ConnectorRateLimiter, profile_credential_path, retry_call
from .config import load_config
from .store import GraphStore

_DEFAULT_TOKEN_PATH = Path.home() / ".hermes" / "google_token.json"
_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
]
_DEFAULT_QUERY = "fullText contains 'Integrity Protocol' or fullText contains 'Xibalba Shield'"
_GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
_PDF_MIME = "application/pdf"
_PLAIN_TEXT_MIMES = {"text/plain", "text/markdown"}


def _require_drive_extra() -> None:
    if Request is None or Credentials is None or PdfReader is None:
        raise RuntimeError(
            "Drive ingestion requires optional dependencies. Install with "
            "`uv sync --extra drive` before running xibalba-cortex-drive-ingest."
        )


def _get_credentials(token_path: Path):
    _require_drive_extra()
    if not token_path.exists():
        raise FileNotFoundError(
            f"no Google OAuth token at {token_path} -- run the Hermes google-workspace skill's "
            "setup.py first (this module reuses that credential, it does not create one)"
        )
    creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
    if not creds.valid:
        raise RuntimeError(f"token at {token_path} is invalid -- re-run the skill's setup.py")
    return creds


def _extract_doc_text(doc: dict[str, Any]) -> str:
    """Same structure-walk google_api.py's docs_get() already implements: paragraph elements'
    textRun.content, concatenated."""
    parts = []
    for element in doc.get("body", {}).get("content", []):
        for pe in element.get("paragraph", {}).get("elements", []):
            content = pe.get("textRun", {}).get("content")
            if content:
                parts.append(content)
    return "".join(parts)


def _extract_pdf_text(data: bytes) -> str:
    _require_drive_extra()
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _search_files(drive_service, query: str, *, limiter: ConnectorRateLimiter) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    page_token = None
    while True:
        response = retry_call(
            lambda: drive_service.files().list(
                q=query,
                pageSize=100,
                pageToken=page_token,
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, owners(emailAddress), webViewLink)",
            ).execute(),
            limiter=limiter,
        )
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return files


def ingest_drive(
    store: GraphStore, *, token_path: Path | None = None, query: str = _DEFAULT_QUERY
) -> dict[str, object]:
    if token_path is None:
        token_path = profile_credential_path(store.home, store.home / "credentials" / "google_token.json")
    else:
        # Explicit paths remain available for controlled tests/migrations; normal CLI
        # operation always uses the profile-confined default above.
        token_path = Path(token_path).expanduser().resolve()
    limiter = ConnectorRateLimiter(rate_per_second=2.0, burst=2)
    creds = _get_credentials(token_path)
    drive_service = build("drive", "v3", credentials=creds)
    docs_service = build("docs", "v1", credentials=creds)

    files = _search_files(drive_service, query, limiter=limiter)

    stored_memories: list[str] = []
    resynced_memories: list[str] = []
    unchanged_skipped: list[str] = []
    unsupported_skipped: list[dict[str, str]] = []
    empty_skipped: list[str] = []

    for file in files:
        file_id = file["id"]
        locator = f"drive://{file_id}"
        mime_type = file["mimeType"]

        prior_id = store.find_memory_id_by_locator(locator)
        if prior_id:
            prior_memory = store.get_memory(prior_id)
            if prior_memory["source"]["metadata"].get("modified_time") == file.get("modifiedTime"):
                unchanged_skipped.append(file_id)
                continue

        if mime_type == _GOOGLE_DOC_MIME:
            text = _extract_doc_text(retry_call(lambda: docs_service.documents().get(documentId=file_id).execute(), limiter=limiter))
        elif mime_type == _PDF_MIME:
            data = retry_call(lambda: drive_service.files().get_media(fileId=file_id).execute(), limiter=limiter)
            text = _extract_pdf_text(data)
        elif mime_type in _PLAIN_TEXT_MIMES:
            data = retry_call(lambda: drive_service.files().get_media(fileId=file_id).execute(), limiter=limiter)
            text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)
        else:
            unsupported_skipped.append({"id": file_id, "name": file.get("name", ""), "mimeType": mime_type})
            continue

        if not text.strip():
            empty_skipped.append(file_id)
            continue

        source = {
            "kind": "imported_document",
            "locator": locator,
            "title": file.get("name"),
            "mime_type": mime_type,
            "modified_time": file.get("modifiedTime"),
            "owners": [o.get("emailAddress") for o in file.get("owners", [])],
            "web_view_link": file.get("webViewLink"),
        }
        if prior_id:
            memory = store.supersede_memory(
                prior_id, text, source=source, status="active", evidence_class="extracted_proposition"
            )
            resynced_memories.append(memory["id"])
        else:
            memory = store.store_memory(
                text, source=source, status="active", evidence_class="extracted_proposition"
            )
            stored_memories.append(memory["id"])

    return {
        "files_found": len(files),
        "stored_memories": stored_memories,
        "resynced_memories": resynced_memories,
        "unchanged_skipped": unchanged_skipped,
        "unsupported_skipped": unsupported_skipped,
        "empty_skipped": empty_skipped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, help="xibalba-cortex profile home")
    parser.add_argument("--query", default=_DEFAULT_QUERY, help="Drive fullText search query")
    parser.add_argument("--token-path", default=None, help="profile-local OAuth token path (defaults to <home>/credentials/google_token.json)")
    args = parser.parse_args()

    config = load_config(home=args.home)
    store = GraphStore(config.storage.home, profile_id=config.profile_id, quotas=config.quotas.as_dict())
    try:
        result = ingest_drive(store, token_path=Path(args.token_path) if args.token_path else None, query=args.query)
        print(
            f"files_found={result['files_found']} "
            f"stored={len(result['stored_memories'])} "
            f"resynced={len(result['resynced_memories'])} "
            f"unchanged={len(result['unchanged_skipped'])} "
            f"unsupported={len(result['unsupported_skipped'])} "
            f"empty={len(result['empty_skipped'])}"
        )
        if result["unsupported_skipped"]:
            print(f"unsupported mimeTypes skipped: {result['unsupported_skipped']}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
