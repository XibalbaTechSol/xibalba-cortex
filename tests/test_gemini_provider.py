"""Gemini free-tier provider: contract, secrecy, quota discipline, and the real PARA path."""
import json
from pathlib import Path

import pytest

from xibalba_cortex.config import load_config
from xibalba_cortex.para_worker import process_para_tasks
from xibalba_cortex.providers import GeminiInferenceProvider, _Throttle
from xibalba_cortex.store import GraphStore

SECRET = "AIza-test-secret-value"


def _reply(text: str) -> bytes:
    return json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode()


class Transport:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, url, *, key, body, timeout):
        self.calls.append({"url": url, "key": key, "body": json.loads(body), "timeout": timeout})
        return self.responses.pop(0)


def _provider(transport, monkeypatch, **kw):
    monkeypatch.setenv("TEST_GEMINI_KEY", SECRET)
    slept: list[float] = []
    throttle = _Throttle(kw.pop("requests_per_minute", 600), sleep=slept.append)
    p = GeminiInferenceProvider(api_key_env="TEST_GEMINI_KEY", transport=transport, throttle=throttle, **kw)
    return p, slept


def test_infer_returns_text_and_keeps_key_out_of_the_url(monkeypatch):
    t = Transport((200, {}, _reply('{"ok": true}')))
    p, _ = _provider(t, monkeypatch)
    assert p.infer("hello", timeout=7) == '{"ok": true}'
    call = t.calls[0]
    assert call["key"] == SECRET and SECRET not in call["url"]
    assert call["url"].endswith("/models/gemini-3.5-flash:generateContent")
    assert call["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert call["timeout"] == 7


def test_missing_key_fails_closed_without_calling_out(monkeypatch):
    monkeypatch.delenv("TEST_GEMINI_KEY", raising=False)
    t = Transport()
    with pytest.raises(RuntimeError, match="TEST_GEMINI_KEY is not set"):
        GeminiInferenceProvider(api_key_env="TEST_GEMINI_KEY", transport=t).infer("x")
    assert t.calls == []


def test_429_retries_honouring_retry_after_then_succeeds(monkeypatch):
    t = Transport((429, {"Retry-After": "4"}, b"{}"), (200, {}, _reply("done")))
    p, slept = _provider(t, monkeypatch)
    assert p.infer("x") == "done"
    assert len(t.calls) == 2 and 4.0 in slept


def test_persistent_429_gives_up_and_never_leaks_the_key(monkeypatch):
    t = Transport(*[(429, {}, SECRET.encode())] * 4)
    p, _ = _provider(t, monkeypatch, max_retries=3)
    with pytest.raises(RuntimeError) as exc:
        p.infer("x")
    assert "429" in str(exc.value) and SECRET not in str(exc.value)
    assert len(t.calls) == 4


@pytest.mark.parametrize("body", [b"not json", b"{}", json.dumps({"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}).encode(), _reply("  ")])
def test_unusable_responses_raise(monkeypatch, body):
    p, _ = _provider(Transport((200, {}, body)), monkeypatch)
    with pytest.raises(RuntimeError, match="gemini returned"):
        p.infer("x")


def test_throttle_spaces_calls_to_the_free_tier_rate():
    now, slept = [0.0], []
    th = _Throttle(10, clock=lambda: now[0], sleep=slept.append)  # 10 rpm -> 6s apart
    th.wait(); th.wait(); th.wait()
    assert slept == [6.0, 12.0]


def test_gemini_drives_the_real_para_worker_end_to_end(tmp_path: Path, monkeypatch):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Prepare the quarterly launch plan by Friday.", source={"kind": "test"}, status="active")
    answer = '{"category":"project","confidence":0.9,"rationale":"Concrete deliverable with a deadline.","signals":[],"alternatives":[]}'
    p, _ = _provider(Transport(*[(200, {}, _reply("```json\n" + answer + "\n```"))] * 3), monkeypatch)
    result = process_para_tasks(store, runner=lambda prompt: p.infer(prompt), worker_id="gemini-test")
    assert result["failed"] == 0 and result["completed"] >= 1
    done = store.list_inference_tasks(status="completed")[0]
    assert done["output"]["source_content_hash"] == memory["content_hash"]
    assert store.get_para_classification(done["id"])["status"] == "proposed"  # review-gated, never auto-final


def _write(home: Path, body: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(body)


def test_config_refuses_gemini_without_the_external_content_ack(tmp_path: Path):
    _write(tmp_path, "inference:\n  provider: gemini\n")
    with pytest.raises(ValueError, match="external_content_ack"):
        load_config(home=tmp_path)


def test_config_accepts_gemini_with_ack_and_keeps_native_default(tmp_path: Path):
    _write(tmp_path, "inference:\n  provider: gemini\n  external_content_ack: true\n  requests_per_minute: 12\n")
    cfg = load_config(home=tmp_path).inference
    assert (cfg.provider, cfg.requests_per_minute, cfg.api_key_env) == ("gemini", 12.0, "GEMINI_API_KEY")
    other = tmp_path / "other"; _write(other, "inference:\n  enabled: true\n")
    assert load_config(home=other).inference.provider == "native_harness"
    bad = tmp_path / "bad"; _write(bad, "inference:\n  provider: nope\n")
    with pytest.raises(ValueError, match="native_harness or gemini"):
        load_config(home=bad)



def test_daily_quota_exhaustion_fails_fast_without_retrying(monkeypatch):
    body = json.dumps({"error": {"status": "RESOURCE_EXHAUSTED", "details": [{"violations": [
        {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}).encode()
    t = Transport((429, {}, body))
    p, slept = _provider(t, monkeypatch)
    with pytest.raises(RuntimeError, match="daily quota exhausted"):
        p.infer("x")
    assert len(t.calls) == 1 and slept == []
