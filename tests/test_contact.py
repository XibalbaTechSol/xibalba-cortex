"""Public inquiries must deliver, fail honestly, and stay outside memory/auth scopes."""
import threading
from http.server import ThreadingHTTPServer

import pytest
import requests
from starlette.testclient import TestClient

from xibalba_cortex import contact
from xibalba_cortex.contact import ContactError, ContactInbox
from xibalba_cortex.email_delivery import EmailDeliveryError
from xibalba_cortex.local_api import _make_handler
from xibalba_cortex.managed.api import create_app
from xibalba_cortex.managed.config import ManagedConfig
from xibalba_cortex.store import GraphStore

INQUIRY = {'name': 'Test founder', 'email': 'founder@example.com', 'organization': 'Example', 'message': 'I would like to discuss a managed Cortex workspace.'}


def test_delivery_uses_configured_inbox_without_user_control_of_headers(monkeypatch):
    delivered = []
    monkeypatch.setenv('CORTEX_CONTACT_TO', 'sales@example.com')
    monkeypatch.setattr(contact, 'send_email', lambda *args: delivered.append(args))
    assert ContactInbox().submit(INQUIRY, 'client')['message'].startswith('Your inquiry has been sent')
    assert delivered[0][0:2] == ('sales@example.com', 'Cortex product inquiry')
    assert 'Reply to: founder@example.com' in delivered[0][2]


def test_delivery_failure_is_not_reported_as_success(monkeypatch):
    def fail(*args):
        raise EmailDeliveryError('internal SMTP configuration')
    monkeypatch.setattr(contact, 'send_email', fail)
    with pytest.raises(ContactError) as error:
        ContactInbox().submit(INQUIRY, 'client')
    assert error.value.status == 503
    assert 'internal SMTP' not in str(error.value)


def test_invalid_inquiries_and_honeypots_never_send_mail(monkeypatch):
    delivered = []
    monkeypatch.setattr(contact, 'send_email', lambda *args: delivered.append(args))
    inbox = ContactInbox()
    for body in [{**INQUIRY, 'email': 'a@example.com\r\nBcc: other@example.com'}, {**INQUIRY, 'message': 'short'}]:
        with pytest.raises(ContactError): inbox.submit(body, 'client')
    inbox.submit({**INQUIRY, 'website': 'bot.example'}, 'client')
    assert delivered == []
    with pytest.raises(ContactError) as error: inbox.submit(INQUIRY, 'client')
    assert error.value.status == 429


@pytest.mark.parametrize('managed', [False, True])
def test_public_endpoint_accepts_same_origin_without_login_and_rejects_foreign_origin(tmp_path, monkeypatch, managed):
    delivered = []
    monkeypatch.setattr(contact, 'send_email', lambda *args: delivered.append(args))
    if managed:
        origin = 'http://localhost:8430'
        client = TestClient(create_app(ManagedConfig(home=tmp_path, public_url=origin)), base_url=origin)
        try:
            assert client.post('/api/contact', json=INQUIRY, headers={'Origin': 'https://foreign.example'}).status_code == 403
            assert client.post('/api/contact', json=INQUIRY, headers={'Origin': origin}).status_code == 202
        finally: client.close()
    else:
        store = GraphStore(tmp_path, features={'inference': False, 'embeddings': False})
        server = ThreadingHTTPServer(('127.0.0.1', 0), _make_handler(store, allowed_origins=('*',)))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        try:
            assert requests.post(origin + '/api/contact', json=INQUIRY, headers={'Origin': 'https://foreign.example'}, timeout=3).status_code == 403
            assert requests.post(origin + '/api/contact', json=INQUIRY, headers={'Origin': origin}, timeout=3).status_code == 202
        finally: server.shutdown(); server.server_close(); thread.join(); store.close()
    assert len(delivered) == 1
