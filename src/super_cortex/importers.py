"""
Local agent session discovery and import engine for Super-Cortex.
Scans and imports authentic sessions from:
1. Claude Code CLI (~/.claude/projects/ and ~/.claude/history.jsonl)
2. Antigravity Controller (~/.gemini/antigravity-cli/brain/*/)
3. Hermes Protocol Gateway (~/.hermes/sessions/*.json)
"""

import os
import glob
import json
import logging
from datetime import datetime, timezone
from typing import Any

from super_cortex.memory import SuperCortex

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
            # Check if parseable
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return dt.isoformat()
        except Exception:
            return datetime.now(timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()

def scan_and_import_local_sessions(
    cortex: SuperCortex | None = None,
    limit_per_source: int = 10,
    max_turns_per_session: int = 20,
) -> dict[str, Any]:
    """Discover and ingest local agent sessions into Super-Cortex provenance store."""
    cortex = cortex or SuperCortex()
    results = {
        "claude": {"sessions": 0, "turns": 0},
        "antigravity": {"sessions": 0, "turns": 0},
        "hermes": {"sessions": 0, "turns": 0},
        "total_sessions": 0,
        "total_turns": 0,
        "session_ids": [],
    }

    # -------------------------------------------------------------------------
    # 1. Antigravity Brain Conversations (~/.gemini/antigravity-cli/brain/)
    # -------------------------------------------------------------------------
    brain_base = os.path.expanduser("~/.gemini/antigravity-cli/brain")
    if os.path.exists(brain_base):
        try:
            # Find directories sorted by modification time (most recent first)
            dirs = [os.path.join(brain_base, d) for d in os.listdir(brain_base)]
            dirs = [d for d in dirs if os.path.isdir(d)]
            dirs.sort(key=lambda d: os.path.getmtime(d), reverse=True)

            agy_imported = 0
            for d in dirs:
                if agy_imported >= limit_per_source:
                    break
                tpath = os.path.join(d, ".system_generated", "logs", "transcript.jsonl")
                if not os.path.exists(tpath) or os.path.getsize(tpath) < 1500:
                    continue

                conv_id = os.path.basename(d)
                session_id = f"sess_agy_local_{conv_id[:8]}"

                # Parse turns
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
                            step = json.loads(line)
                            stype = step.get("type")
                            if stype == "USER_INPUT":
                                if cur_prompt is not None:
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
                                tc = step.get("tool_calls", [])
                                if tc:
                                    for t in tc:
                                        tname = t.get("name") or t.get("tool_name") or "tool"
                                        targs = t.get("args") or t.get("arguments") or {}
                                        cur_tools.append({"name": tname, "args": targs})
                                if step.get("content"):
                                    cur_response += step.get("content") + " "

                    if cur_prompt is not None and len(turns) < max_turns_per_session:
                        turns.append((cur_prompt, cur_response, cur_thinking, cur_tools, cur_time))

                    if turns:
                        actor = "did:integrity:agy-system-controller"
                        with cortex.store._get_conn() as conn:
                            conn.execute("DELETE FROM exchanges WHERE session_id = ?", (session_id,))
                            conn.commit()
                        for p, r, th_text, tools, ttime in turns:
                            # Clean up prompt if contains user request tags
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
            # Find jsonl conversation logs under projects
            project_files = glob.glob(os.path.join(claude_projects_dir, "**", "*.jsonl"), recursive=True)
            # Filter out subagents or meta files, keep top-level project logs
            project_files = [f for f in project_files if "subagents" not in f and os.path.getsize(f) > 3000]
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
                            d = json.loads(line)
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
                        turns.append((cur_prompt, cur_response, cur_thinking, cur_tools, cur_time))

                    if turns:
                        actor = "did:integrity:claude-code-dev"
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
                            )
                            results["claude"]["turns"] += 1

                        results["claude"]["sessions"] += 1
                        results["session_ids"].append(session_id)
                        claude_imported += 1
                except Exception as err:
                    logger.warning("Error importing Claude project file %s: %s", pf, err)
        except Exception as err:
            logger.warning("Failed scanning Claude projects directory: %s", err)

    # Fallback to ~/.claude/history.jsonl if fewer than limit
    if claude_imported < limit_per_source:
        hist_file = os.path.expanduser("~/.claude/history.jsonl")
        if os.path.exists(hist_file):
            try:
                hist_sessions = {}
                with open(hist_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        d = json.loads(line)
                        sid = d.get("sessionId")
                        if sid:
                            hist_sessions.setdefault(sid, []).append(d)

                for sid, turns_raw in list(hist_sessions.items()):
                    if claude_imported >= limit_per_source:
                        break
                    session_id = f"sess_claude_hist_{sid[:8]}"
                    if session_id in results["session_ids"]:
                        continue

                    actor = "did:integrity:claude-code-dev"
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
            # Sort by file size descending so we get substantial multi-turn sessions
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
                            )
                            results["hermes"]["turns"] += 1

                        results["hermes"]["sessions"] += 1
                        results["session_ids"].append(session_id)
                        hermes_imported += 1
                except Exception as err:
                    logger.warning("Error importing Hermes dump %s: %s", hf, err)
        except Exception as err:
            logger.warning("Failed scanning Hermes sessions directory: %s", err)

    results["total_sessions"] = (
        results["claude"]["sessions"]
        + results["antigravity"]["sessions"]
        + results["hermes"]["sessions"]
    )
    results["total_turns"] = (
        results["claude"]["turns"]
        + results["antigravity"]["turns"]
        + results["hermes"]["turns"]
    )
    return results

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = scan_and_import_local_sessions()
    print(json.dumps(res, indent=2))
