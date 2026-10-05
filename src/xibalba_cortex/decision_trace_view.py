"""Small self-contained local audit view for a DecisionTrace projection."""

from __future__ import annotations

from html import escape
from typing import Any


def _short(value: Any, length: int = 18) -> str:
    text = str(value or "")
    return text if len(text) <= length else f"{text[:length // 2]}…{text[-length // 2:]}"


def render_decision_trace_html(projection: dict[str, Any]) -> str:
    events = list(projection.get("events") or [])
    valid = bool(projection.get("valid"))
    trace_id = escape(str(projection.get("trace_id") or "unknown"))
    root = escape(str(projection.get("root") or "not available"))
    status = "Verified locally" if valid else "Verification failed"
    status_class = "good" if valid else "bad"
    cards: list[str] = []
    for index, item in enumerate(events):
        envelope = dict(item.get("envelope") or {})
        advisory = dict(item.get("advisory") or {})
        probabilities = advisory.get("transition_probabilities") or {}
        probability_html = "".join(
            f'<span class="prob"><b>{escape(str(name))}</b> {float(value):.0%}</span>'
            for name, value in sorted(probabilities.items(), key=lambda pair: str(pair[0]))
        ) or '<span class="muted">No advisory probability available</span>'
        advisory_status = escape(str(advisory.get("status") or "not requested"))
        cards.append(f"""
        <article class="event-card">
          <div class="event-index">{index + 1:02d}</div>
          <div class="event-main">
            <div class="event-top"><span class="event-type">{escape(str(envelope.get('event_type') or 'event'))}</span><span class="time">{escape(str(envelope.get('timestamp') or ''))}</span></div>
            <h2>{escape(str(envelope.get('policy_decision') or 'observed transition'))}</h2>
            <div class="meta"><span>event <code>{escape(_short(item.get('event_id')))}</code></span><span>invocation <code>{escape(_short(envelope.get('invocation_id')))}</code></span><span>parent <code>{escape(_short(item.get('parent_event_hash')))}</code></span></div>
            <div class="advisory"><div><span class="label">Jev advisory</span><span class="advisory-status">{advisory_status}</span></div><div class="probabilities">{probability_html}</div><small>Observational estimate; causal claim: false.</small></div>
          </div>
        </article>
        """)
    empty = '<div class="empty">No DecisionTrace events have been recorded for this session.</div>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>DecisionTrace · {trace_id}</title>
<style>
:root {{ color-scheme: dark; --bg:#0b1118; --panel:#121b25; --panel2:#172332; --text:#edf4f8; --muted:#96a8b5; --line:#2c3b49; --accent:#66d4b1; --blue:#7db8ff; --danger:#ff8d8d; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:linear-gradient(135deg,#0b1118 0%,#101a24 58%,#0c161d 100%); color:var(--text); font:14px/1.5 Inter,ui-sans-serif,system-ui,sans-serif; }}
.shell {{ max-width:1180px; margin:0 auto; padding:42px 26px 64px; }} .eyebrow {{ color:var(--accent); text-transform:uppercase; letter-spacing:.14em; font-size:11px; font-weight:700; }}
h1 {{ margin:8px 0 8px; font-size:clamp(30px,5vw,52px); letter-spacing:-.045em; line-height:1.02; }} .subtitle {{ color:var(--muted); max-width:690px; margin:0 0 28px; font-size:15px; }}
.summary {{ display:grid; grid-template-columns:1.4fr 1fr 1fr; gap:12px; margin-bottom:28px; }} .metric,.boundary,.event-card {{ background:rgba(18,27,37,.88); border:1px solid var(--line); border-radius:16px; box-shadow:0 16px 42px rgba(0,0,0,.18); }} .metric {{ padding:18px; }} .label {{ color:var(--muted); display:block; font-size:11px; text-transform:uppercase; letter-spacing:.1em; }} .metric strong {{ display:block; margin-top:6px; font-size:17px; }} .good {{ color:var(--accent); }} .bad {{ color:var(--danger); }} code {{ color:var(--blue); font:12px ui-monospace,SFMono-Regular,monospace; }}
.layout {{ display:grid; grid-template-columns:minmax(0,1fr) 280px; gap:18px; }} .section-title {{ font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:.12em; margin:0 0 12px; }} .timeline {{ position:relative; padding-left:28px; }} .timeline:before {{ content:""; position:absolute; left:9px; top:4px; bottom:4px; width:1px; background:var(--line); }}
.event-card {{ position:relative; display:flex; gap:14px; padding:17px; margin-bottom:12px; }} .event-index {{ position:absolute; left:-28px; top:17px; width:20px; height:20px; border:1px solid var(--accent); border-radius:50%; background:var(--bg); color:var(--accent); font-size:9px; display:grid; place-items:center; font-weight:700; }} .event-main {{ min-width:0; width:100%; }} .event-top,.meta,.advisory>div:first-child {{ display:flex; align-items:center; justify-content:space-between; gap:12px; }} .event-type {{ color:var(--blue); font-weight:700; }} .time,.muted,small {{ color:var(--muted); }} h2 {{ margin:7px 0 8px; font-size:20px; text-transform:capitalize; }} .meta {{ justify-content:flex-start; flex-wrap:wrap; color:var(--muted); font-size:12px; }} .advisory {{ margin-top:15px; padding:12px; background:var(--panel2); border-radius:11px; }} .advisory-status {{ color:var(--accent); margin-left:8px; font-weight:700; }} .probabilities {{ display:flex; flex-wrap:wrap; gap:8px; margin:9px 0 7px; }} .prob {{ border:1px solid #385465; padding:4px 8px; border-radius:999px; color:var(--muted); font-size:12px; }} .prob b {{ color:var(--text); }}
.boundary {{ padding:18px; height:max-content; }} .boundary h2 {{ font-size:16px; margin:0 0 12px; }} .boundary p {{ color:var(--muted); font-size:13px; margin:10px 0; }} .boundary li {{ color:var(--muted); margin:8px 0; }} .empty {{ color:var(--muted); padding:30px; border:1px dashed var(--line); border-radius:14px; }}
@media(max-width:800px) {{ .summary,.layout {{ grid-template-columns:1fr; }} .shell {{ padding:28px 16px 46px; }} .boundary {{ order:-1; }} .event-top {{ align-items:flex-start; flex-direction:column; gap:2px; }} }}
</style></head><body><main class="shell">
<div class="eyebrow">Integrity · Local audit surface</div><h1>DecisionTrace</h1>
<p class="subtitle">A verifiable timeline of observed agent transitions and advisory analysis. The trace shows correlation and probabilities without claiming causality or replacing enforcement.</p>
<section class="summary"><div class="metric"><span class="label">Trace</span><strong>{trace_id}</strong></div><div class="metric"><span class="label">Evidence status</span><strong class="{status_class}">{status}</strong></div><div class="metric"><span class="label">Domain-separated root</span><strong><code>{root}</code></strong></div></section>
<div class="layout"><section><p class="section-title">Observed sequence · {len(events)} events</p><div class="timeline">{''.join(cards) or empty}</div></section>
<aside class="boundary"><h2>Authority boundary</h2><p>Jev is advisory. Deterministic Shield/OPA/BCC remains the enforcement authority.</p><ul><li>Raw prompts and completions excluded</li><li>Parent links and Merkle inclusion verified locally</li><li>Probabilities are observational</li><li>Causal claim: <b>false</b></li></ul><p>Root<br><code>{root}</code></p></aside></div></main></body></html>"""


__all__ = ["render_decision_trace_html"]
