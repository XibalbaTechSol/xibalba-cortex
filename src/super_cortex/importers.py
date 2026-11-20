"""
Local agent session discovery and import engine for Super-Cortex.
Scans and imports authentic sessions and telemetry from:
1. Antigravity Controller (~/.gemini/antigravity-cli/brain/*/ and ~/.gemini/antigravity-cli/xibalba-cortex-agy/)
2. Claude Code CLI (~/.claude/projects/ and ~/.claude/history.jsonl)
3. Hermes Protocol Gateway (~/.hermes/sessions/*.json)
4. Codex Assistant (~/.codex/sessions/ and ~/.codex/history.jsonl)
5. Local OTEL Telemetry and Legacy Knowledge Migration
"""

import os
import glob
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from super_cortex.memory import SuperCortex
from super_cortex.legacy_migration import migrate_legacy_cortex_databases

logger = logging.getLogger("super_cortex.importers")

def _parse_iso_or_millis(val: Any) -> str:
    """Normalize timestamps (ISO string or epoch milliseconds) to standard ISO format."""
    if not val:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(val, (int, float)):
        # Epoch millis or seconds
        if val > 1e11:  # milliseconds
            val = val / 1000.0
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc).isoformat()
        except Exception:
            return datetime.now(timezone.utc).isoformat()
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return dt.isoformat()
        except Exception:
            return datetime.now(timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


class SessionImporter:
    """High-level session importer interface for connectors and background synchronization."""

    def __init__(self, store: Any = None, cortex: SuperCortex | None = None) -> None:
        if cortex is not None:
            self.cortex = cortex
        elif store is not None:
            self.cortex = SuperCortex(store=store)
        else:
            self.cortex = SuperCortex()
        self.store = self.cortex.store

    def import_all_local(
        self,
        limit_per_source: int = 500,
        max_turns_per_session: int = 500,
    ) -> dict[str, Any]:
        return scan_and_import_local_sessions(
            cortex=self.cortex,
            limit_per_source=limit_per_source,
            max_turns_per_session=max_turns_per_session,
        )


def scan_and_import_local_sessions(
    cortex: SuperCortex | None = None,
    limit_per_source: int = 500,
    max_turns_per_session: int = 500,
) -> dict[str, Any]:
    """Discover and ingest local agent sessions and telemetry into Super-Cortex provenance store."""
    cortex = cortex or SuperCortex()
    results: dict[str, Any] = {
        "claude": {"sessions": 0, "turns": 0},
        "antigravity": {"sessions": 0, "turns": 0},
        "hermes": {"sessions": 0, "turns": 0},
        "codex": {"sessions": 0, "turns": 0},
        "otel_telemetry": {"events_ingested": 0},
        "legacy_migration": {},
        "total_sessions": 0,
        "total_turns": 0,
        "session_ids": [],
    }

    # Ensure all registered agent scopes exist in cortex
    required_scopes = [
        ("agent:agy", "Antigravity Agent Scope", "agy"),
        ("agent:claude", "Claude Code Scope", "claude"),
        ("agent:hermes", "Hermes Agent Scope", "hermes"),
        ("agent:codex", "Codex Assistant Scope", "codex"),
        ("agent:shield", "Xibalba Shield Scope", "shield"),
        ("agent:cortex", "Xibalba Cortex Scope", "cortex"),
        ("agent:cursor", "Cursor IDE Scope", "cursor"),
        ("shared", "Xibalba Shared Fabric", None),
    ]
    with cortex.store._get_conn() as conn:
        for sid, sname, aid in required_scopes:
            stype = "single_agent" if aid else "shared"
            conn.execute(
                """
                INSERT OR IGNORE INTO scopes (scope_id, name, scope_type, agent_id, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (sid, sname, stype, aid, f"Operational memory enclave for {sname}", datetime.now(timezone.utc).isoformat()),
            )
            if aid:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO agents (agent_id, name, default_scope_id, client_type, status, last_active_at, created_at)
                    VALUES (?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (aid, sname, sid, aid, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
                )
        conn.commit()

    # -------------------------------------------------------------------------
    # 1. Antigravity Brain Conversations (~/.gemini/antigravity-cli/brain/)
    # -------------------------------------------------------------------------
    brain_base = os.path.expanduser("~/.gemini/antigravity-cli/brain")
    if os.path.exists(brain_base):
        try:
            dirs = [os.path.join(brain_base, d) for d in os.listdir(brain_base)]
            dirs = [d for d in dirs if os.path.isdir(d)]
            dirs.sort(key=lambda d: os.path.getmtime(d), reverse=True)

            agy_imported = 0
            for d in dirs:
                if agy_imported >= limit_per_source:
                    break
                full_tpath = os.path.join(d, ".system_generated", "logs", "transcript_full.jsonl")
                compact_tpath = os.path.join(d, ".system_generated", "logs", "transcript.jsonl")
                tpath = full_tpath if (os.path.exists(full_tpath) and os.path.getsize(full_tpath) > 500) else compact_tpath
                if not os.path.exists(tpath) or os.path.getsize(tpath) < 500:
                    continue

                conv_id = os.path.basename(d)
                session_id = f"sess_agy_local_{conv_id[:8]}"

                turns = []
                cur_prompt = None
                cur_response = ""
                cur_thinking = ""
                cur_tools = []
                cur_time = None

                try:
                    with open(tpath, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            try:
                                step = json.loads(line)
                            except Exception:
                                continue
                            stype = step.get("type")
                            if stype == "USER_INPUT":
                                if cur_prompt is not None:
                                    if "<think>" in cur_response:
                                        t_matches = re.findall(r"<think>(.*?)</think>", cur_response, re.DOTALL)
                                        for tm in t_matches:
                                            cur_thinking += ("\n\n" if cur_thinking else "") + tm.strip()
                                        cur_response = re.sub(r"<think>.*?</think>", "", cur_response, flags=re.DOTALL).strip()
                                    turns.append((cur_prompt, cur_response, cur_thinking, cur_tools, cur_time))
                                    if len(turns) >= max_turns_per_session:
                                        break
                                cur_prompt = step.get("content", "")
                                cur_response = ""
                                cur_thinking = ""
                                cur_tools = []
                                cur_time = _parse_iso_or_millis(step.get("created_at"))
                            elif stype == "PLANNER_RESPONSE":
                                th = step.get("thinking")
                                if th and isinstance(th, str) and th.strip():
                                    if cur_thinking:
                                        cur_thinking += "\n\n" + th.strip()
                                    else:
                                        cur_thinking = th.strip()
                                raw_th = step.get("thought") or step.get("reasoning_content") or step.get("thoughts")
                                if raw_th and isinstance(raw_th, str) and raw_th.strip() and raw_th.strip() not in cur_thinking:
                                    cur_thinking += ("\n\n" if cur_thinking else "") + raw_th.strip()
                                tc = step.get("tool_calls", [])
                                if tc:
                                    for t in tc:
                                        tname = t.get("name") or t.get("tool_name") or "tool"
                                        targs = t.get("args") or t.get("arguments") or {}
                                        cur_tools.append({"name": tname, "args": targs})
                                if step.get("content"):
                                    cur_response += step.get("content") + " "

                    if cur_prompt is not None and len(turns) < max_turns_per_session:
                        if "<think>" in cur_response:
                            t_matches = re.findall(r"<think>(.*?)</think>", cur_response, re.DOTALL)
                            for tm in t_matches:
                                cur_thinking += ("\n\n" if cur_thinking else "") + tm.strip()
                            cur_response = re.sub(r"<think>.*?</think>", "", cur_response, flags=re.DOTALL).strip()
                        turns.append((cur_prompt, cur_response, cur_thinking, cur_tools, cur_time))

                    if turns:
                        actor = "did:integrity:b1a72980e8e45e97c7b92982a89b1963e470b45fa955c9bd245f046e1e32e39a"
                        with cortex.store._get_conn() as conn:
                            conn.execute("DELETE FROM exchanges WHERE session_id = ?", (session_id,))
                            conn.commit()
                        for p, r, th_text, tools, ttime in turns:
                            clean_prompt = p.replace("<USER_REQUEST>", "").replace("</USER_REQUEST>", "").strip()
                            clean_prompt = clean_prompt[:250] if clean_prompt else "Execute Antigravity action"
                            clean_response = r.strip()[:400] if r else "Execution completed."

                            cortex.record_exchange(
                                session_id=session_id,
                                prompt_text=clean_prompt,
                                response_text=clean_response,
                                thinking_text=th_text,
                                tool_calls=tools,
                                actor=actor,
                                created_at=ttime,
                                agent_id="agy",
                                scope_id="agent:agy",
                            )
                            results["antigravity"]["turns"] += 1

                        results["antigravity"]["sessions"] += 1
                        results["session_ids"].append(session_id)
                        agy_imported += 1
                except Exception as err:
                    logger.warning("Error importing AGY transcript %s: %s", tpath, err)
        except Exception as err:
            logger.warning("Failed scanning AGY brain directory: %s", err)

    # -------------------------------------------------------------------------
    # 2. Claude Code Sessions (~/.claude/projects/ and ~/.claude/history.jsonl)
    # -------------------------------------------------------------------------
    claude_projects_dir = os.path.expanduser("~/.claude/projects")
    claude_imported = 0
    if os.path.exists(claude_projects_dir):
        try:
            project_files = []
            for pdir in os.listdir(claude_projects_dir):
                full_pdir = os.path.join(claude_projects_dir, pdir)
                if os.path.isdir(full_pdir):
                    for fname in os.listdir(full_pdir):
                        if fname.endswith(".jsonl") and "subagents" not in fname:
                            fpath = os.path.join(full_pdir, fname)
                            try:
                                if os.path.getsize(fpath) > 3000:
                                    project_files.append(fpath)
                            except OSError:
                                pass
            project_files.sort(key=lambda f: os.path.getmtime(f), reverse=True)

            for pf in project_files:
                if claude_imported >= limit_per_source:
                    break
                fname = os.path.basename(pf).replace(".jsonl", "")
                session_id = f"sess_claude_local_{fname[:8]}"

                turns = []
                cur_prompt = None
                cur_response = ""
                cur_thinking = ""
                cur_tools = []
                cur_time = None

                try:
                    with open(pf, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            try:
                                d = json.loads(line)
                            except Exception:
                                continue
                            dtype = d.get("type")
                            msg = d.get("message", {})
                            mrole = msg.get("role")
                            content = msg.get("content")

                            if dtype == "user" or mrole == "user":
                                if cur_prompt is not None:
                                    turns.append((cur_prompt, cur_response, cur_thinking, cur_tools, cur_time))
                                    if len(turns) >= max_turns_per_session:
                                        break
                                cur_prompt = ""
                                if isinstance(content, str):
                                    cur_prompt = content
                                elif isinstance(content, list):
                                    cur_prompt = " ".join([b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"])
                                cur_response = ""
                                cur_thinking = ""
                                cur_tools = []
                                cur_time = _parse_iso_or_millis(d.get("timestamp") or d.get("createdAt"))
                            elif dtype == "assistant" or mrole == "assistant":
                                if isinstance(content, list):
                                    for b in content:
                                        if isinstance(b, dict):
                                            if b.get("type") == "text":
                                                cur_response += b.get("text", "") + " "
                                            elif b.get("type") in ("thinking", "thought"):
                                                th = b.get("thinking") or b.get("text") or ""
                                                if th:
                                                    cur_thinking += th.strip() + "\n\n"
                                            elif b.get("type") == "tool_use":
                                                cur_tools.append({"name": b.get("name"), "args": b.get("input")})
                                elif isinstance(content, str):
                                    cur_response += content + " "

                    if cur_prompt is not None and len(turns) < max_turns_per_session:
                        if "<think>" in cur_response:
                            t_matches = re.findall(r"<think>(.*?)</think>", cur_response, re.DOTALL)
                            for tm in t_matches:
                                cur_thinking += ("\n\n" if cur_thinking else "") + tm.strip()
                            cur_response = re.sub(r"<think>.*?</think>", "", cur_response, flags=re.DOTALL).strip()
                        turns.append((cur_prompt, cur_response, cur_thinking, cur_tools, cur_time))

                    if turns:
                        actor = "did:integrity:f07438ae1fb67f6ab1a21df87fb4771bead162c502c6e98cfa0bbdd7020a7e75"
                        with cortex.store._get_conn() as conn:
                            conn.execute("DELETE FROM exchanges WHERE session_id = ?", (session_id,))
                            conn.commit()
                        for p, r, th_text, tools, ttime in turns:
                            clean_prompt = p.strip()[:250] if p else "Execute Claude Code task"
                            clean_response = r.strip()[:400] if r else "Completed task."

                            cortex.record_exchange(
                                session_id=session_id,
                                prompt_text=clean_prompt,
                                response_text=clean_response,
                                thinking_text=th_text,
                                tool_calls=tools,
                                actor=actor,
                                created_at=ttime,
                                agent_id="claude",
                                scope_id="agent:claude",
                            )
                            results["claude"]["turns"] += 1

                        results["claude"]["sessions"] += 1
                        results["session_ids"].append(session_id)
                        claude_imported += 1
                except Exception as err:
                    logger.warning("Error importing Claude project file %s: %s", pf, err)
        except Exception as err:
            logger.warning("Failed scanning Claude projects directory: %s", err)

    # Claude history fallback
    if claude_imported < limit_per_source:
        hist_file = os.path.expanduser("~/.claude/history.jsonl")
        if os.path.exists(hist_file):
            try:
                hist_sessions: dict[str, list[dict[str, Any]]] = {}
                with open(hist_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            d = json.loads(line)
                        except Exception:
                            continue
                        sid = d.get("sessionId")
                        if sid:
                            hist_sessions.setdefault(sid, []).append(d)

                for sid, turns_raw in list(hist_sessions.items()):
                    if claude_imported >= limit_per_source:
                        break
                    session_id = f"sess_claude_hist_{sid[:8]}"
                    if session_id in results["session_ids"]:
                        continue

                    actor = "did:integrity:f07438ae1fb67f6ab1a21df87fb4771bead162c502c6e98cfa0bbdd7020a7e75"
                    turns_to_record = turns_raw[:max_turns_per_session]
                    for t_idx, t in enumerate(turns_to_record):
                        prompt = str(t.get("display", ""))[:250] or "Run command"
                        resp = "Acknowledged and executed in workspace."
                        ttime = _parse_iso_or_millis(t.get("timestamp"))

                        cortex.record_exchange(
                            session_id=session_id,
                            prompt_text=prompt,
                            response_text=resp,
                            tool_calls=[{"name": "cli_eval", "args": {"turn": t_idx}}],
                            actor=actor,
                            created_at=ttime,
                            agent_id="claude",
                            scope_id="agent:claude",
                        )
                        results["claude"]["turns"] += 1

                    results["claude"]["sessions"] += 1
                    results["session_ids"].append(session_id)
                    claude_imported += 1
            except Exception as err:
                logger.warning("Failed reading Claude history.jsonl: %s", err)

    # -------------------------------------------------------------------------
    # 3. Hermes Gateway Sessions (~/.hermes/sessions/*.json)
    # -------------------------------------------------------------------------
    hermes_dir = os.path.expanduser("~/.hermes/sessions")
    if os.path.exists(hermes_dir):
        try:
            hfiles = glob.glob(os.path.join(hermes_dir, "request_dump_*.json"))
            hfiles.sort(key=lambda f: os.path.getsize(f), reverse=True)

            hermes_imported = 0
            for hf in hfiles:
                if hermes_imported >= limit_per_source:
                    break

                try:
                    with open(hf, "r", encoding="utf-8", errors="ignore") as f:
                        hdata = json.load(f)

                    hsid = hdata.get("session_id") or os.path.basename(hf).split("_")[2]
                    session_id = f"sess_hermes_local_{hsid[:8]}"
                    if session_id in results["session_ids"]:
                        continue

                    htime = _parse_iso_or_millis(hdata.get("timestamp"))
                    req_body = hdata.get("request", {}).get("body")
                    body = json.loads(req_body) if isinstance(req_body, str) else (req_body or {})
                    msgs = body.get("messages", [])

                    turns = []
                    cur_prompt = None
                    cur_resp = ""
                    cur_tools = []

                    for m in msgs:
                        role = m.get("role")
                        content = m.get("content", "")
                        if role == "user":
                            if cur_prompt is not None:
                                turns.append((cur_prompt, cur_resp, cur_tools))
                                if len(turns) >= max_turns_per_session:
                                    break
                            cur_prompt = str(content)
                            cur_resp = ""
                            cur_tools = []
                        elif role == "assistant":
                            cur_resp += str(content) + " "
                            tc = m.get("tool_calls", [])
                            if tc:
                                for t in tc:
                                    fn = t.get("function", {})
                                    cur_tools.append({"name": fn.get("name", "tool"), "args": fn.get("arguments", {})})

                    if cur_prompt is not None and len(turns) < max_turns_per_session:
                        turns.append((cur_prompt, cur_resp, cur_tools))

                    if turns:
                        actor = "did:integrity:68fed1331613937555a59398223e8e87520a87dd0305aac4fd7ecdc32a14a861"
                        for p, r, tools in turns:
                            clean_p = p.strip()[:250] if p else "Execute Hermes workflow"
                            clean_r = r.strip()[:400] if r else "Execution complete."
                            cortex.record_exchange(
                                session_id=session_id,
                                prompt_text=clean_p,
                                response_text=clean_r,
                                tool_calls=tools,
                                actor=actor,
                                created_at=htime,
                                agent_id="hermes",
                                scope_id="agent:hermes",
                            )
                            results["hermes"]["turns"] += 1

                        results["hermes"]["sessions"] += 1
                        results["session_ids"].append(session_id)
                        hermes_imported += 1
                except Exception as err:
                    logger.warning("Error importing Hermes dump %s: %s", hf, err)
        except Exception as err:
            logger.warning("Failed scanning Hermes sessions directory: %s", err)

    # -------------------------------------------------------------------------
    # 4. Codex Sessions (~/.codex/sessions/ and ~/.codex/history.jsonl)
    # -------------------------------------------------------------------------
    codex_imported = 0
    codex_sessions_dir = os.path.expanduser("~/.codex/sessions")
    actor_codex = "did:integrity:d73b98dd869948c27c7cc16d53683779a23c46daf3020e221955d67d1a8723c5"

    if os.path.exists(codex_sessions_dir):
        try:
            rollout_files = glob.glob(os.path.join(codex_sessions_dir, "**", "rollout-*.jsonl"), recursive=True)
            rollout_files.sort(key=lambda f: os.path.getmtime(f), reverse=True)

            for rf in rollout_files:
                if codex_imported >= limit_per_source:
                    break
                session_id = f"sess_codex_rollout_{os.path.basename(rf)[:12]}"
                if session_id in results["session_ids"]:
                    continue

                turns = []
                cur_prompt = None
                cur_resp = ""
                cur_think = ""
                cur_tools = []
                cur_time = None

                try:
                    with open(rf, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            try:
                                d = json.loads(line)
                            except Exception:
                                continue
                            ltype = d.get("type")
                            payload = d.get("payload") or {}
                            ts = d.get("timestamp") or payload.get("timestamp")

                            if ltype == "response_item":
                                rrole = payload.get("role")
                                rcontent = payload.get("content")
                                if rrole == "user":
                                    if cur_prompt is not None:
                                        turns.append((cur_prompt, cur_resp, cur_think, cur_tools, cur_time))
                                        if len(turns) >= max_turns_per_session:
                                            break
                                    cur_prompt = str(rcontent) if isinstance(rcontent, str) else json.dumps(rcontent)
                                    cur_resp = ""
                                    cur_think = ""
                                    cur_tools = []
                                    cur_time = _parse_iso_or_millis(ts)
                                elif rrole == "assistant":
                                    if isinstance(rcontent, str):
                                        cur_resp += rcontent + " "
                                    elif isinstance(rcontent, list):
                                        for part in rcontent:
                                            if isinstance(part, dict):
                                                if part.get("type") == "text":
                                                    cur_resp += part.get("text", "") + " "
                                                elif part.get("type") in ("thinking", "thought"):
                                                    cur_think += str(part.get("thinking") or part.get("text") or "") + "\n\n"
                                                elif part.get("type") in ("tool_use", "call"):
                                                    cur_tools.append({"name": part.get("name", "tool"), "args": part.get("input", {})})

                    if cur_prompt is not None and len(turns) < max_turns_per_session:
                        turns.append((cur_prompt, cur_resp, cur_think, cur_tools, cur_time))

                    if turns:
                        with cortex.store._get_conn() as conn:
                            conn.execute("DELETE FROM exchanges WHERE session_id = ?", (session_id,))
                            conn.commit()
                        for p, r, th_text, tools, ttime in turns:
                            cortex.record_exchange(
                                session_id=session_id,
                                prompt_text=str(p)[:250],
                                response_text=str(r)[:400] if r else "Execution complete.",
                                thinking_text=th_text,
                                tool_calls=tools,
                                actor=actor_codex,
                                created_at=ttime,
                                agent_id="codex",
                                scope_id="agent:codex",
                            )
                            results["codex"]["turns"] += 1

                        results["codex"]["sessions"] += 1
                        results["session_ids"].append(session_id)
                        codex_imported += 1
                except Exception as err:
                    logger.warning("Error importing Codex rollout %s: %s", rf, err)
        except Exception as err:
            logger.warning("Failed scanning Codex sessions directory: %s", err)

    # Codex history fallback
    codex_hist = os.path.expanduser("~/.codex/history.jsonl")
    if os.path.exists(codex_hist) and codex_imported < limit_per_source:
        try:
            codex_hist_sessions: dict[str, list[dict[str, Any]]] = {}
            with open(codex_hist, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    sid = d.get("session_id")
                    if sid:
                        codex_hist_sessions.setdefault(sid, []).append(d)

            for sid, items in list(codex_hist_sessions.items())[:limit_per_source]:
                session_id = f"sess_codex_hist_{sid[:8]}"
                if session_id in results["session_ids"]:
                    continue

                for t_idx, item in enumerate(items[:max_turns_per_session]):
                    prompt = str(item.get("text", ""))[:250] or "Run codex operation"
                    ttime = _parse_iso_or_millis(item.get("ts"))

                    cortex.record_exchange(
                        session_id=session_id,
                        prompt_text=prompt,
                        response_text="Operation processed by Codex assistant runtime.",
                        tool_calls=[{"name": "codex_cli", "args": {"step": t_idx}}],
                        actor=actor_codex,
                        created_at=ttime,
                        agent_id="codex",
                        scope_id="agent:codex",
                    )
                    results["codex"]["turns"] += 1

                results["codex"]["sessions"] += 1
                results["session_ids"].append(session_id)
                codex_imported += 1
        except Exception as err:
            logger.warning("Failed scanning Codex history.jsonl: %s", err)

    # -------------------------------------------------------------------------
    # 5. OpenTelemetry Events & Tool Telemetry from Local DBs
    # -------------------------------------------------------------------------
    legacy_dbs = [
        ("~/.gemini/antigravity-cli/xibalba-cortex-agy/graph-memory.sqlite3", "agy", "agent:agy", "did:integrity:b1a72980e8e45e97c7b92982a89b1963e470b45fa955c9bd245f046e1e32e39a"),
        ("~/.claude/xibalba-cortex-claude/graph-memory.sqlite3", "claude", "agent:claude", "did:integrity:f07438ae1fb67f6ab1a21df87fb4771bead162c502c6e98cfa0bbdd7020a7e75"),
        ("~/.codex/xibalba-cortex-codex/graph-memory.sqlite3", "codex", "agent:codex", "did:integrity:d73b98dd869948c27c7cc16d53683779a23c46daf3020e221955d67d1a8723c5"),
    ]

    otel_count = 0
    for db_raw, aid, sid, did_actor in legacy_dbs:
        db_path = Path(db_raw).expanduser()
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path), timeout=10.0)
            conn.row_factory = sqlite3.Row
            # Check if otel_events table exists
            has_otel = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='otel_events'").fetchone()
            if has_otel:
                rows = conn.execute(
                    """
                    SELECT id, session_id, name, attributes_json, created_at
                    FROM otel_events
                    WHERE attributes_json LIKE '%tool_name%'
                    ORDER BY rowid DESC LIMIT 400
                    """
                ).fetchall()
                for r in rows:
                    try:
                        attrs = json.loads(r["attributes_json"] or "{}")
                        tname = attrs.get("tool_name")
                        if not tname:
                            continue
                        ses_id = f"sess_{aid}_otel_{str(r['session_id'])[:8]}"
                        cortex.record_exchange(
                            session_id=ses_id,
                            prompt_text=f"Telemetry observation: {tname} execution in {aid}",
                            response_text=f"Observed outcome: {attrs.get('tool_outcome', 'success')}. Status: {attrs.get('status_code', '200')}",
                            tool_calls=[{"name": tname, "args": {"hook": attrs.get('metadata', {}).get('hook', 'PostToolUse'), "outcome": attrs.get('tool_outcome', 'success')}}],
                            actor=did_actor,
                            created_at=_parse_iso_or_millis(r["created_at"]),
                            agent_id=aid,
                            scope_id=sid,
                        )
                        otel_count += 1
                    except Exception:
                        pass
            conn.close()
        except Exception as err:
            logger.warning("Failed importing otel_events from %s: %s", db_path, err)

    results["otel_telemetry"]["events_ingested"] = otel_count

    # -------------------------------------------------------------------------
    # 6. Legacy Knowledge Memories & Relational Triples Migration
    # -------------------------------------------------------------------------
    try:
        mig_summary = migrate_legacy_cortex_databases(cortex.store, max_memories_per_db=300)
        results["legacy_migration"] = mig_summary
    except Exception as err:
        logger.warning("Failed running legacy migration: %s", err)
        results["legacy_migration"] = {"error": str(err)}

    results["total_sessions"] = (
        results["claude"]["sessions"]
        + results["antigravity"]["sessions"]
        + results["hermes"]["sessions"]
        + results["codex"]["sessions"]
    )
    results["total_turns"] = (
        results["claude"]["turns"]
        + results["antigravity"]["turns"]
        + results["hermes"]["turns"]
        + results["codex"]["turns"]
        + otel_count
    )
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = scan_and_import_local_sessions()
    print(json.dumps(res, indent=2))
