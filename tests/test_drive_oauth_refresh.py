"""Real (not mocked) coverage of xibalba_cortex.drive_ingest._get_credentials -- the one slice
of Drive ingestion every other test in tests/test_drive_ingest.py patches away entirely
(`@patch("xibalba_cortex.drive_ingest._get_credentials", ...)`), leaving it with ZERO test
coverage of any kind, not even mocked. `docs/PROJECT_STATE.md`'s G2/G5 rows name "real Google
Drive OAuth evidence" as the one item that stays genuinely external -- a real end user consenting
to a real Google Cloud OAuth app cannot be automated in this environment, and this file does not
attempt that. What it DOES close: everything in the credential-refresh code path SHORT OF the
real OAuth handshake -- real `google-auth`/`google-oauth2` library code (Credentials construction
from a real on-disk JSON file, the real `.expired` property, the real `.refresh(Request())` HTTP
call and response parsing, the real `.to_json()` write-back), exercised against a real local
HTTP server standing in for Google's token endpoint rather than the real
`https://oauth2.googleapis.com/token`. Only the actual final network hop is swapped; nothing
about how `_get_credentials` itself calls into the real library is mocked.

`google.oauth2.credentials.from_authorized_user_info` hardcodes the real Google token endpoint
into every constructed `Credentials` object ("token_uri=_GOOGLE_OAUTH2_TOKEN_ENDPOINT, # always
overrides") -- there is no per-call override, so the module-level constant itself is monkeypatched
for the duration of each test, exactly the same shape of substitution
`tests/test_hermes_bridge.py`'s sibling `integrity-core` repo uses in `bcc_middleware`'s spool
tests (redirect one real dependency's real endpoint to a real local server, mock nothing else).
"""

from __future__ import annotations

import http.server
import json
import threading

import google.auth.exceptions
import google.oauth2.credentials
import pytest

from xibalba_cortex.drive_ingest import _get_credentials

_EXPIRED_TIMESTAMP = "2020-01-01T00:00:00Z"


class _TokenEndpointHandler(http.server.BaseHTTPRequestHandler):
    """Stands in for https://oauth2.googleapis.com/token. `server.response` (set per-test)
    controls what a POST to /token returns -- a real HTTP status/body round-trip, not a mock."""

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)  # drain the real refresh-token POST body; content not asserted here
        status, body = self.server.response
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())


@pytest.fixture
def token_endpoint():
    server = http.server.HTTPServer(("127.0.0.1", 0), _TokenEndpointHandler)
    server.response = (200, {"access_token": "refreshed-real-flow-token", "expires_in": 3600, "token_type": "Bearer"})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(autouse=True)
def _redirect_token_endpoint(monkeypatch, token_endpoint):
    port = token_endpoint.server_address[1]
    monkeypatch.setattr(
        google.oauth2.credentials, "_GOOGLE_OAUTH2_TOKEN_ENDPOINT", f"http://127.0.0.1:{port}/token"
    )


def _write_expired_token(token_path, **overrides):
    payload = {
        "refresh_token": "real-shaped-refresh-token",
        "client_id": "test-client-id.apps.googleusercontent.com",
        "client_secret": "test-client-secret",
        "token": "stale-access-token",
        "expiry": _EXPIRED_TIMESTAMP,
        "scopes": [
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/documents.readonly",
        ],
    }
    payload.update(overrides)
    token_path.write_text(json.dumps(payload))


def test_get_credentials_performs_a_real_refresh_round_trip_and_persists_the_new_token(tmp_path):
    token_path = tmp_path / "google_token.json"
    _write_expired_token(token_path)

    creds = _get_credentials(token_path)

    assert creds.valid
    assert creds.token == "refreshed-real-flow-token"

    # Real file write-back, not just an in-memory object -- re-read from disk independently.
    persisted = json.loads(token_path.read_text())
    assert persisted["token"] == "refreshed-real-flow-token"


def test_get_credentials_surfaces_a_real_refresh_error_rather_than_silently_swallowing_it(
    tmp_path, token_endpoint
):
    token_endpoint.response = (400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
    token_path = tmp_path / "google_token.json"
    _write_expired_token(token_path)

    with pytest.raises(google.auth.exceptions.RefreshError):
        _get_credentials(token_path)


def test_get_credentials_does_not_refresh_a_still_valid_token(tmp_path, token_endpoint):
    # A far-future expiry means creds.expired is False -- _get_credentials must never call the
    # (here, deliberately failing) token endpoint at all for an already-valid token.
    token_endpoint.response = (500, {"error": "should_not_be_called"})
    token_path = tmp_path / "google_token.json"
    _write_expired_token(token_path, expiry="2099-01-01T00:00:00Z", token="still-fresh-token")

    creds = _get_credentials(token_path)

    assert creds.valid
    assert creds.token == "still-fresh-token"
