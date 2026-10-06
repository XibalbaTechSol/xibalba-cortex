import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest
import requests

from xibalba_cortex.provider_adapters import PerplexityAdapter, ProviderTelemetryPolicy
from xibalba_cortex.runtime_controller import XibalbaRuntimeController
from xibalba_cortex.store import GraphStore
from xibalba_cortex.perplexity_runtime import sse_events

AGENT = 'did:integrity:perplexity-owner'


def stream_fixture():
    return [
        {'type': 'response.created', 'sequence_number': 0, 'response': {'id': 'resp_1', 'status': 'in_progress'}},
        {'type': 'response.output_text.delta', 'sequence_number': 1, 'delta': 'same'},
        {'type': 'response.output_text.delta', 'sequence_number': 2, 'delta': 'same'},
        {'type': 'response.output_item.added', 'sequence_number': 3, 'item': {'id': 'tool_1', 'type': 'mcp_call', 'name': 'recall'}},
        {'type': 'response.output_item.done', 'sequence_number': 4, 'item': {'id': 'tool_1', 'type': 'mcp_call', 'name': 'recall',
            'arguments': '{"query":"private"}', 'output': 'result', 'error': None}},
        {'type': 'response.reasoning.delta', 'sequence_number': 5, 'delta': 'hidden reasoning'},
        {'type': 'response.completed', 'sequence_number': 6, 'response': {'id': 'resp_1', 'status': 'completed',
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'answer private'}]},
                       {'type': 'reasoning', 'content': 'hidden reasoning'}],
            'usage': {'input_tokens': 3, 'output_tokens': 4}}}]


class Response:
    def __init__(self, events=None, *, code=200, body=None, fail=False):
        self.events, self.status_code, self.body, self.fail = events, code, body, fail
        self.headers = {'Content-Type': 'text/event-stream' if events is not None else 'application/json'}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def json(self): return self.body
    def iter_content(self, **kwargs):
        if self.events is None:
            yield json.dumps(self.body).encode()
        else:
            for line in self.iter_lines(**kwargs):
                yield line + b'\n'
    def iter_lines(self, **kwargs):
        for event in self.events:
            yield b': heartbeat'
            yield ('data: '+json.dumps(event)).encode()
            yield b''
        if self.fail:
            raise requests.ConnectionError('authorization secret provider body')


class Transport:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []
    def request(self, method, endpoint, **kwargs):
        self.calls.append((method, endpoint, kwargs))
        return self.responses.pop(0)


@contextmanager
def recorder(tmp_path, transport, raw=False, consent=True):
    store = GraphStore(tmp_path)
    adapter = PerplexityAdapter(XibalbaRuntimeController(store),
        ProviderTelemetryPolicy('perplexity', consent, allow_raw_payloads=raw))
    runtime = adapter.recorder(http=transport)
    try:
        yield runtime, store
    finally:
        runtime.close(); store.close()


def test_stream_persists_before_yield_correlates_tools_and_deduplicates(tmp_path):
    events = stream_fixture()
    transport = Transport(Response(events))
    with recorder(tmp_path, transport) as (runtime, store):
        live = list(runtime.start(agent_id=AGENT, api_key='api-secret', payload={'input': 'private'}, run_id='run'))
        assert len(live) == len(events)
        replay = runtime.replay(run_id='run', agent_id=AGENT)
        assert replay[1:] == live
        assert runtime.status(run_id='run', agent_id=AGENT)['status'] == 'completed'
        assert runtime.status(run_id='run', agent_id=AGENT)['cursor'] == 6
        assert len([r for r in replay if r['event']['tool_name'] == 'response.output_text.delta']) == 2
        calls = [r['event'] for r in replay if r['event']['tool_name'].startswith('response.output_item')]
        assert calls[0]['invocation_id'] == calls[1]['invocation_id'] == 'tool_1'
        assert 'private' not in json.dumps(replay)
        assert 'api-secret' not in json.dumps(replay)
        assert 'hidden reasoning' not in json.dumps(replay)
        before = len(store.session_otel_events('perplexity:run'))
        runtime._provider_event('run', AGENT, events[-1], 'repeat')
        runtime.flush('run', AGENT)
        assert len(store.session_otel_events('perplexity:run')) == before
        assert transport.calls[0][2]['json']['background'] is True
        assert transport.calls[0][2]['json']['stream'] is True
        assert transport.calls[0][2]['allow_redirects'] is False


def test_disconnect_resume_after_restart_uses_committed_cursor(tmp_path):
    with recorder(tmp_path, Transport(Response(stream_fixture()[:3], fail=True))) as (runtime, store):
        with pytest.raises(RuntimeError, match='capture interrupted'):
            list(runtime.start(agent_id=AGENT, api_key='key', payload={'input': 'x'}, run_id='restart'))
        assert runtime.status(run_id='restart', agent_id=AGENT)['cursor'] == 2
    resumed = Transport(Response(stream_fixture()[2:]))
    with recorder(tmp_path, resumed) as (runtime, store):
        list(runtime.resume(run_id='restart', agent_id=AGENT, api_key='key'))
        assert resumed.calls[0][0] == 'GET'
        assert resumed.calls[0][2]['params'] == {'stream': 'true', 'starting_after': 2}
        assert runtime.status(run_id='restart', agent_id=AGENT)['status'] == 'completed'
        assert len([r for r in runtime.replay(run_id='restart', agent_id=AGENT)
                    if r['event']['tool_name'] == 'response.output_text.delta']) == 2


def test_expired_resume_snapshot_is_explicit_capture_gap(tmp_path):
    transport = Transport(Response(stream_fixture()[:1]), Response(code=400),
        Response(body=stream_fixture()[-1]['response']))
    with recorder(tmp_path, transport) as (runtime, store):
        list(runtime.start(agent_id=AGENT, api_key='key', payload={'input': 'x'}, run_id='gap'))
        list(runtime.resume(run_id='gap', agent_id=AGENT, api_key='key'))
        status = runtime.status(run_id='gap', agent_id=AGENT)
        assert status['gap'] == 1 and status['status'] == 'completed'
        replay = runtime.replay(run_id='gap', agent_id=AGENT)
        assert any(r['event']['tool_name'] == 'cortex.capture_gap' for r in replay)
        assert not any(r['event']['tool_name'] == 'response.output_text.delta' for r in replay)


def test_cancel_is_asynchronous_then_snapshot_confirms(tmp_path):
    transport = Transport(Response(stream_fixture()[:1]), Response(body={'status': 'cancelling'}),
                          Response(body={'id': 'resp_1', 'status': 'cancelled', 'output': []}))
    with recorder(tmp_path, transport) as (runtime, store):
        list(runtime.start(agent_id=AGENT, api_key='key', payload={'input': 'x'}, run_id='cancel'))
        assert runtime.cancel(run_id='cancel', agent_id=AGENT, api_key='key')['status'] == 'cancelling'
        assert transport.calls[1][1].endswith('/resp_1/cancel')
        list(runtime.snapshot(run_id='cancel', agent_id=AGENT, api_key='key'))
        assert runtime.status(run_id='cancel', agent_id=AGENT)['status'] == 'cancelled'


def test_content_mode_excludes_reasoning_and_redacts_complete_secret(tmp_path):
    response = stream_fixture()[-1]['response']
    response['output'][0]['content'][0]['text'] = 'Authorization: Bearer test-secret-token-abcdefghijklmnopqrstuvwxyz'
    events = stream_fixture()[:1] + [{'type': 'response.output_text.delta', 'sequence_number': 1,
        'delta': 'Authorization: Bearer test-secret-'}, {'type': 'response.output_text.delta', 'sequence_number': 2,
        'delta': 'token-abcdefghijklmnopqrstuvwxyz'}, {'type': 'response.completed', 'sequence_number': 3, 'response': response}]
    with recorder(tmp_path, Transport(Response(events)), raw=True) as (runtime, store):
        list(runtime.start(agent_id=AGENT, api_key='key', payload={'input': 'x'}, run_id='raw'))
        dumped = json.dumps(runtime.replay(run_id='raw', agent_id=AGENT))
        assert 'test-secret' not in dumped
        assert 'hidden reasoning' not in dumped
        assert 'redacted' in dumped


def test_consent_and_agent_isolation_precede_network(tmp_path):
    transport = Transport(Response(stream_fixture()))
    with recorder(tmp_path, transport, consent=False) as (runtime, store):
        with pytest.raises(PermissionError):
            list(runtime.start(agent_id=AGENT, api_key='key', payload={'input': 'x'}))
        assert not transport.calls
    with recorder(tmp_path, transport) as (runtime, store):
        list(runtime.start(agent_id=AGENT, api_key='key', payload={'input': 'x'}, run_id='private'))
        for operation in [runtime.replay, runtime.status, runtime.cancel]:
            with pytest.raises(PermissionError):
                kwargs = {'api_key': 'key'} if operation == runtime.cancel else {}
                operation(run_id='private', agent_id='did:integrity:other', **kwargs)
        with pytest.raises(Exception):
            list(runtime.start(agent_id=AGENT, api_key='key', payload={'input': 'x'}, run_id='private'))
        assert len(transport.calls) == 1


def test_no_id_means_no_creation_retry(tmp_path):
    transport = Transport(Response([], fail=True))
    with recorder(tmp_path, transport) as (runtime, store):
        with pytest.raises(RuntimeError):
            list(runtime.start(agent_id=AGENT, api_key='key', payload={'input': 'x'}, run_id='unknown'))
        with pytest.raises(RuntimeError, match='do not automatically repeat'):
            list(runtime.resume(run_id='unknown', agent_id=AGENT, api_key='key'))
        assert len(transport.calls) == 1


def test_lost_mirror_ack_recovery_does_not_duplicate(tmp_path, monkeypatch):
    with recorder(tmp_path, Transport(Response(stream_fixture()))) as (runtime, store):
        list(runtime.start(agent_id=AGENT, api_key='key', payload={'input': 'x'}, run_id='ack'))
        before = len(store.session_otel_events('perplexity:ack'))
        with runtime.db:
            runtime.db.execute('UPDATE events SET delivered=0')
        runtime.flush('ack', AGENT)
        assert len(store.session_otel_events('perplexity:ack')) == before


def test_scoped_memory_injection(tmp_path):
    transport = Transport(Response(stream_fixture()))
    with recorder(tmp_path, transport) as (runtime, store):
        store.store_memory('violet telescope', source={'kind': 'test', 'agent_id': AGENT}, status='active')
        store.store_memory('violet secret-other', source={'kind': 'test', 'agent_id': 'did:integrity:other'}, status='active')
        list(runtime.start(agent_id=AGENT, api_key='key', payload={'input': 'x'}, run_id='memory', memory_query='violet'))
        instructions = transport.calls[0][2]['json']['instructions']
        assert 'violet telescope' in instructions
        assert 'secret-other' not in instructions
        assert 'untrusted data' in instructions


def test_sse_multiline_and_oversize():
    response = Response([])
    response.iter_lines = lambda **kw: iter([b': heartbeat', b'event: response.created',
        b'data: {"type":', b'data: "response.created"}', b'', b'data: [DONE]', b''])
    assert list(sse_events(response)) == [{'type': 'response.created'}]
    response.iter_lines = lambda **kw: iter([b'data: '+b'x'*1_048_577])
    with pytest.raises(ValueError, match='limit'):
        list(sse_events(response))


def test_unterminated_sse_line_is_rejected_before_reading_unbounded_input():
    response = Response([])
    consumed = 0
    def chunks(**kwargs):
        nonlocal consumed
        # No newline: iter_lines would retain the whole response before yielding.
        for _ in range(300):
            consumed += 8192
            yield b'x' * 8192
    response.iter_content = chunks
    with pytest.raises(ValueError, match='limit'):
        list(sse_events(response))
    assert consumed < 2 * 1_048_576


def test_sse_crlf_split_unicode_and_frame_bounds():
    response = Response([])
    wire = ': heartbeat\r\ndata: {"type":"test","text":"héllo"}\r\n\r\ndata: [DONE]\r\n\r\n'.encode()
    response.iter_content = lambda **kwargs: (bytes([byte]) for byte in wire)
    assert list(sse_events(response)) == [{'type': 'test', 'text': 'héllo'}]
    response.iter_content = lambda **kwargs: iter([b'data: '+b' ' * 600000+b'\n',
                                                   b'data: '+b' ' * 600000+b'\n'])
    with pytest.raises(ValueError, match='limit'):
        list(sse_events(response))


def test_complete_json_tool_arguments_and_results_use_key_redaction(tmp_path):
    events = stream_fixture()[:1] + [{'type': 'response.output_item.done', 'sequence_number': 1,
        'item': {'type': 'mcp_call', 'id': 'tool', 'arguments': '{"password":"PRIVATE_PASSWORD","nested":{"api-key":"PRIVATE_API_KEY"}}',
                 'output': '{"authorization":"PRIVATE_AUTHORIZATION","answer":"safe"}'}}]
    with recorder(tmp_path, Transport(Response(events)), raw=True) as (runtime, store):
        list(runtime.start(agent_id=AGENT, api_key='key', payload={'input': 'x'}, run_id='json'))
        saved = json.dumps(runtime.replay(run_id='json', agent_id=AGENT))
        assert 'PRIVATE_' not in saved
        assert 'safe' in saved and '[REDACTED]' in saved
        assert 'PRIVATE_' not in json.dumps(store.session_otel_events('perplexity:json'))


def test_stale_snapshots_do_not_regress_cancellation_or_terminal_status(tmp_path):
    transport = Transport(Response(stream_fixture()[:1]), Response(body={'status': 'cancelling'}),
        Response(body={'id': 'resp_1', 'status': 'in_progress', 'output': []}),
        Response(body={'id': 'resp_1', 'status': 'cancelled', 'output': []}),
        Response(body={'id': 'resp_1', 'status': 'in_progress', 'output': []}))
    with recorder(tmp_path, transport) as (runtime, store):
        list(runtime.start(agent_id=AGENT, api_key='key', payload={'input': 'x'}, run_id='stale'))
        runtime.cancel(run_id='stale', agent_id=AGENT, api_key='key')
        list(runtime.snapshot(run_id='stale', agent_id=AGENT, api_key='key'))
        assert runtime.status(run_id='stale', agent_id=AGENT)['status'] == 'cancelling'
        list(runtime.snapshot(run_id='stale', agent_id=AGENT, api_key='key'))
        assert runtime.status(run_id='stale', agent_id=AGENT)['status'] == 'cancelled'
        list(runtime.snapshot(run_id='stale', agent_id=AGENT, api_key='key'))
        assert runtime.status(run_id='stale', agent_id=AGENT)['status'] == 'cancelled'


@pytest.mark.parametrize('extra', [{'item_id': {'secret': 'PRIVATE'}},
    {'response': {'id': 'resp_1', 'model': {'secret': 'PRIVATE'}}},
    {'item': {'id': {'secret': 'PRIVATE'}}}, {'output_index': True}])
def test_structured_metadata_is_rejected_before_journal_capture(tmp_path, extra):
    events = stream_fixture()[:1] + [{'type': 'response.output_text.delta', 'sequence_number': 1, **extra}]
    with recorder(tmp_path, Transport(Response(events))) as (runtime, store):
        with pytest.raises(RuntimeError, match='capture interrupted'):
            list(runtime.start(agent_id=AGENT, api_key='key', payload={'input': 'x'}, run_id='bad-metadata'))
        assert runtime.status(run_id='bad-metadata', agent_id=AGENT)['cursor'] == 0
        assert 'PRIVATE' not in json.dumps(runtime.replay(run_id='bad-metadata', agent_id=AGENT))


def test_live_yield_corresponds_to_accepted_event_despite_other_append(tmp_path, monkeypatch):
    with recorder(tmp_path, Transport(Response(stream_fixture()))) as (runtime, store):
        original = runtime._provider_event
        def concurrent_append(run_id, agent_id, event, occurrence):
            accepted = original(run_id, agent_id, event, occurrence)
            if event['type'] == 'response.output_text.delta':
                runtime._append(runtime._run(run_id, agent_id), agent_id, 'other:'+occurrence,
                                'cortex.concurrent_observation', {})
            return accepted
        monkeypatch.setattr(runtime, '_provider_event', concurrent_append)
        live = list(runtime.start(agent_id=AGENT, api_key='key', payload={'input': 'x'}, run_id='live'))
        assert [row['event']['tool_name'] for row in live] == [event['type'] for event in stream_fixture()]


def test_real_http_stream(tmp_path):
    received = []
    release = threading.Event()
    continued = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            for index, event in enumerate(stream_fixture()):
                if index == 1:
                    release.wait(3)
                    continued.set()
                self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode()); self.wfile.flush()
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        session = requests.Session(); session.trust_env = False
        with recorder(tmp_path, session) as (runtime, store):
            runtime.adapter.endpoint = f'http://127.0.0.1:{server.server_port}/v1/agent'
            iterator = runtime.start(agent_id=AGENT, api_key='key', payload={'input': 'x'}, run_id='http')
            first = next(iterator)
            assert first['event']['tool_name'] == 'response.created'
            assert not continued.is_set()
            release.set()
            assert runtime.status(run_id='http', agent_id=AGENT)['cursor'] == 0
            list(iterator)
            assert received[0]['stream'] is True
        session.close()
    finally:
        release.set()
        server.shutdown(); server.server_close(); thread.join(5)
