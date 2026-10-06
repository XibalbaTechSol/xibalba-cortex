import json
import socket
import threading
import time

import httpx
import jwt
import pytest
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa

from xibalba_cortex.hosted_connector import ConnectorVerifier, build_connector, connector_app
from xibalba_cortex.ingest_tokens import issue_token, revoke_token
from xibalba_cortex.store import GraphStore


def test_oauth_bindings_and_claim_validation(tmp_path):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    bindings = tmp_path / 'bindings.json'
    bindings.write_text(json.dumps({'user': {'enabled': True, 'profile_id': 'default',
        'agent_id': 'one', 'scopes': ['memory:read']}}))
    verifier = ConnectorVerifier(tmp_path, 'default', issuer='https://issuer.test',
        resource='https://cortex.test/mcp', jwks_url='https://issuer.test/jwks', bindings=bindings)
    class Keys:
        def get_signing_key_from_jwt(self, token):
            return type('Key', (), {'key': private.public_key()})()
    verifier.jwks = Keys()
    claims = {'iss': verifier.issuer, 'aud': verifier.resource, 'sub': 'user',
              'iat': int(time.time()), 'exp': int(time.time())+60, 'scope': 'memory:read memory:write'}
    def encoded(**overrides):
        return jwt.encode(claims | overrides, private, algorithm='RS256')
    assert verifier._verify(encoded()).scopes == ['memory:read']
    for changes in [{'aud': 'other'}, {'iss': 'other'}, {'exp': 1}, {'sub': 'unknown'}]:
        assert verifier._verify(encoded(**changes)) is None
    bindings.write_text('{}')
    assert verifier._verify(encoded()) is None


@pytest.mark.parametrize('surface', ['perplexity', 'spark'])
def test_real_http_memory_isolation_and_recorder(tmp_path, surface):
    store = GraphStore(tmp_path)
    verifier = ConnectorVerifier(tmp_path, 'default')
    tokens = [issue_token(tmp_path, name, agent_id=name, scopes=('memory:read', 'memory:write'))
              for name in ['one', 'two']]
    reader = issue_token(tmp_path, 'reader', agent_id='one', roles=('reader',), scopes=('memory:read',))
    unbound = issue_token(tmp_path, 'unbound', scopes=('memory:read',))
    bindings = tmp_path / 'bindings.json'
    if surface == 'spark':
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        bindings.write_text(json.dumps({name: {'enabled': True, 'profile_id': 'default',
            'agent_id': 'one' if name == 'reader' else name,
            'scopes': ['memory:read'] if name == 'reader' else ['memory:read', 'memory:write']}
            for name in ['one', 'two', 'reader']}))
        verifier = ConnectorVerifier(tmp_path, 'default', issuer='https://issuer.test',
            resource='https://cortex.test/mcp', jwks_url='https://issuer.test/jwks', bindings=bindings)
        class Keys:
            def get_signing_key_from_jwt(self, token):
                return type('Key', (), {'key': private.public_key()})()
        verifier.jwks = Keys()
        def signed(name):
            return jwt.encode({'iss': verifier.issuer, 'aud': verifier.resource, 'sub': name,
                'iat': int(time.time()), 'exp': int(time.time())+60,
                'scope': 'memory:read memory:write'}, private, algorithm='RS256')
        tokens, reader, unbound = [signed(n) for n in ['one', 'two']], signed('reader'), signed('unknown')
    app = connector_app(build_connector(store, verifier, surface=surface), verifier)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    uv = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
    thread = threading.Thread(target=uv.run, daemon=True); thread.start()
    deadline = time.monotonic()+5
    while not uv.started and time.monotonic() < deadline:
        time.sleep(.02)
    assert uv.started
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False) as client:
            def call(token, method, params):
                return client.post('/mcp', headers={'Authorization': 'Bearer '+token,
                    'Accept': 'application/json, text/event-stream'}, json={
                    'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
            def tool(token, name, arguments):
                response = call(token, 'tools/call', {'name': name, 'arguments': arguments})
                assert response.status_code == 200, response.text
                result = response.json()['result']
                if result.get('isError'): return result
                return result.get('structuredContent') or json.loads(result['content'][0]['text'])
            denied = call(unbound, 'tools/list', {})
            assert denied.status_code == 401
            if surface == 'spark':
                assert 'resource_metadata=' in denied.headers['www-authenticate']
                metadata = client.get('/.well-known/oauth-protected-resource/mcp').json()
                assert metadata['authorization_servers'] == ['https://issuer.test']
            else:
                assert client.get('/.well-known/oauth-protected-resource/mcp').status_code == 404
            initialized = call(tokens[0], 'initialize', {'protocolVersion': '2026-06-18',
                'capabilities': {}, 'clientInfo': {'name': 'connector-canary', 'version': '1'}})
            assert initialized.status_code == 200
            assert call(tokens[0], 'tools/list', {}).status_code == 200
            first = tool(tokens[0], 'cortex_remember', {'content': 'violet telescope', 'idempotency_key': 'same'})
            again = tool(tokens[0], 'cortex_remember', {'content': 'violet telescope', 'idempotency_key': 'same'})
            assert first['result'] == again['result']
            assert tool(reader, 'cortex_remember', {'content': 'no', 'idempotency_key': 'no'})['isError']
            own = tool(tokens[0], 'cortex_recall', {'query': 'violet'})
            other = tool(tokens[1], 'cortex_recall', {'query': 'violet'})
            assert 'violet telescope' in json.dumps(own)
            assert 'violet telescope' not in json.dumps(other)
            status = tool(tokens[0], 'cortex_connection_status', {})
            assert status['result']['internal_agent_events_available'] is False
            assert store.get_session(status['session_id'])['agent_id'] == store.storage_agent_id('one')
            events = store._connection.execute('SELECT attributes_json FROM otel_events').fetchall()
            assert len(events) >= 10
            assert 'violet telescope' not in str([tuple(e) for e in events])
            if surface == 'spark':
                bindings.write_text('{}')
            else:
                from xibalba_cortex.ingest_tokens import verify_token_record
                revoke_token(tmp_path, verify_token_record(tmp_path, tokens[0])['id'])
            assert call(tokens[0], 'tools/list', {}).status_code == 401
    finally:
        uv.should_exit = True; thread.join(5); store.close()
