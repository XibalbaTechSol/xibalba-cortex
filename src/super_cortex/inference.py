from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any

import httpx

from .models import ProviderRecord, ProviderType
from .store import SuperCortexStore

logger = logging.getLogger(__name__)


def extract_json_array(text: str) -> list[dict[str, Any]]:
    """Robustly extract a JSON array from model output."""
    text = text.strip()
    # 1. Try direct json.loads
    try:
        val = json.loads(text)
        if isinstance(val, list):
            return val
    except Exception:
        pass

    # 2. Try markdown code fence
    fence_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence_match:
        try:
            val = json.loads(fence_match.group(1))
            if isinstance(val, list):
                return val
        except Exception:
            pass

    # 3. Try finding brackets
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        try:
            val = json.loads(text[start : end + 1])
            if isinstance(val, list):
                return val
        except Exception:
            pass

    return []


async def call_llm(
    prompt: str,
    system_prompt: str = "",
    provider: ProviderRecord | None = None,
    model: str | None = None,
    timeout: float = 90.0,
    response_mime_type: str | None = None,
) -> dict[str, Any]:
    """Execute an LLM completion request against any configured provider (Claude, Gemini, OpenAI, etc.)."""
    if not provider:
        raise ValueError("No inference provider configured or active.")

    chosen_model = model or provider.default_model
    start_time = time.perf_counter()

    async with httpx.AsyncClient(timeout=timeout) as client:
        # 1. ANTHROPIC CLAUDE
        if provider.provider_type == ProviderType.ANTHROPIC.value:
            key = provider.api_key or os.getenv("ANTHROPIC_API_KEY") or ""
            if not key:
                raise ValueError("Anthropic API key is required. Please configure it in Provider Settings.")
            api_url = f"{provider.base_url.rstrip('/')}/messages" if not provider.base_url.endswith("/messages") else provider.base_url
            headers = {
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            payload: dict[str, Any] = {
                "model": chosen_model or "claude-3-7-sonnet-20250219",
                "max_tokens": provider.settings.get("max_tokens", 2048),
                "messages": [{"role": "user", "content": prompt}],
            }
            if system_prompt:
                payload["system"] = system_prompt

            resp = await client.post(api_url, headers=headers, json=payload)
            if not resp.is_success:
                raise RuntimeError(f"Anthropic API error ({resp.status_code}): {resp.text}")

            data = resp.json()
            content_blocks = data.get("content", [])
            text_parts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
            result_text = "".join(text_parts)
            usage = data.get("usage", {})
            tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

        # 2. GOOGLE GEMINI
        elif provider.provider_type == ProviderType.GEMINI.value:
            key = provider.api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
            if not key:
                raise ValueError("Google Gemini API key is required. Please configure it in Provider Settings.")
            gemini_model = chosen_model or "gemini-2.5-flash"
            base = provider.base_url.rstrip("/") if provider.base_url else "https://generativelanguage.googleapis.com/v1beta"
            api_url = f"{base}/models/{gemini_model}:generateContent?key={key}"
            headers = {"content-type": "application/json"}
            generation_config: dict[str, Any] = {
                "temperature": 0.2,
                "maxOutputTokens": 8192,
                "thinkingConfig": {"thinkingBudget": 1024},
            }
            if response_mime_type:
                generation_config["responseMimeType"] = response_mime_type

            payload: dict[str, Any] = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": generation_config,
            }
            if system_prompt:
                payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

            max_retries = 3
            resp = None
            for attempt in range(max_retries):
                resp = await client.post(api_url, headers=headers, json=payload)
                if resp.status_code == 503 and attempt < max_retries - 1:
                    wait_time = 2.0 * (attempt + 1)
                    logger.warning(
                        "Gemini API 503 (high demand), retrying in %.1fs (attempt %d/%d)...",
                        wait_time,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(wait_time)
                    continue
                elif resp.status_code == 429 and gemini_model != "gemini-3.5-flash":
                    logger.warning(
                        "Gemini model %s quota exceeded (429). Gracefully falling back to gemini-3.5-flash...",
                        gemini_model,
                    )
                    gemini_model = "gemini-3.5-flash"
                    chosen_model = gemini_model
                    api_url = f"{base}/models/{gemini_model}:generateContent?key={key}"
                    continue
                break

            if resp is None or not resp.is_success:
                raise RuntimeError(
                    f"Gemini API error ({resp.status_code if resp else 'no response'}): {resp.text if resp else ''}"
                )

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError("Gemini returned empty candidate list.")
            parts = candidates[0].get("content", {}).get("parts", [])
            result_text = "".join(p.get("text", "") for p in parts)
            usage_meta = data.get("usageMetadata", {})
            tokens = usage_meta.get("totalTokenCount", 0)

        # 3. OPENAI / GROQ / OPENROUTER / OLLAMA / CUSTOM
        else:
            base = provider.base_url.rstrip("/") if provider.base_url else "https://api.openai.com/v1"
            api_url = f"{base}/chat/completions"
            headers = {"Content-Type": "application/json"}
            key = provider.api_key or (os.getenv("OPENAI_API_KEY") if provider.provider_type == "openai" else os.getenv("GROQ_API_KEY") if provider.provider_type == "groq" else "")
            if key:
                headers["Authorization"] = f"Bearer {key}"

            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            payload = {
                "model": chosen_model or "gpt-4o",
                "messages": messages,
            }
            if "max_tokens" in provider.settings:
                payload["max_tokens"] = provider.settings["max_tokens"]

            resp = await client.post(api_url, headers=headers, json=payload)
            if not resp.is_success:
                raise RuntimeError(f"OpenAI-compatible provider error ({resp.status_code}): {resp.text}")

            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("Provider returned empty choices array.")
            result_text = choices[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            tokens = usage.get("total_tokens", 0)

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return {
        "text": result_text,
        "model": chosen_model,
        "provider": provider.name,
        "provider_type": provider.provider_type,
        "elapsed_ms": elapsed_ms,
        "tokens": tokens,
    }


async def test_provider_connection(provider: ProviderRecord) -> dict[str, Any]:
    """Test connectivity and latency for a given provider configuration."""
    test_prompt = "Super-Cortex health check. Reply in one short sentence confirming online status."
    try:
        res = await call_llm(
            prompt=test_prompt,
            system_prompt="You are a health check responder.",
            provider=provider,
            timeout=12.0,
        )
        return {
            "success": True,
            "provider_id": provider.id,
            "provider_name": provider.name,
            "model": res["model"],
            "reply": res["text"][:120].strip(),
            "elapsed_ms": res["elapsed_ms"],
        }
    except Exception as e:
        logger.error("Provider test failed for %s: %s", provider.id, e)
        return {
            "success": False,
            "provider_id": provider.id,
            "provider_name": provider.name,
            "error": str(e),
        }


def assemble_full_graph_context(store: SuperCortexStore, scope: str = "all") -> dict[str, Any]:
    """Assemble the entire knowledge graph dataset (memories, entities, relations, scopes, thoughts) without truncation."""
    with store._get_conn() as conn:
        # 1. Scopes & Agents
        s_cursor = conn.execute("SELECT scope_id, name, scope_type FROM scopes")
        scopes = [dict(r) for r in s_cursor.fetchall()]

        a_cursor = conn.execute("SELECT agent_id, name, default_scope_id, status FROM agents")
        agents = [dict(r) for r in a_cursor.fetchall()]

        # 2. Entire set of active memories
        m_cursor = conn.execute(
            """
            SELECT id, text, epistemic_class, lifecycle_status, metadata_json, created_at
            FROM memories
            WHERE lifecycle_status != 'forgotten'
            ORDER BY created_at ASC
            """
        )
        raw_mems = m_cursor.fetchall()

        # 3. Entire set of knowledge relations
        r_cursor = conn.execute(
            """
            SELECT relation_id, subject, predicate, object, confidence, created_at
            FROM relations
            ORDER BY rowid ASC
            """
        )
        raw_rels = r_cursor.fetchall()

        # 4. Entire set of knowledge entities
        e_cursor = conn.execute("SELECT entity_id, label FROM entities ORDER BY rowid ASC")
        raw_entities = [r["label"] for r in e_cursor.fetchall()]

        # 5. Recent chain-of-thought exchanges
        th_cursor = conn.execute(
            """
            SELECT exchange_id, session_id, agent_id, thinking_text, prompt_text, response_text, created_at
            FROM exchanges
            WHERE thinking_text != ''
            ORDER BY rowid DESC LIMIT 50
            """
        )
        raw_thoughts = th_cursor.fetchall()

    # Filter memories by scope if specific scope selected
    memories: list[dict[str, Any]] = []
    epistemic_buckets: dict[str, list[dict[str, Any]]] = {
        "rule": [],
        "decision": [],
        "fact": [],
        "goal": [],
        "belief": [],
        "inference": [],
        "observation": [],
    }

    for m in raw_mems:
        try:
            meta = json.loads(m["metadata_json"])
        except Exception:
            meta = {}
        m_scope = meta.get("scope", "shared")
        if scope != "all" and m_scope != scope:
            continue

        item = {
            "id": m["id"],
            "text": m["text"],
            "epistemic_class": m["epistemic_class"],
            "scope": m_scope,
            "agent_id": meta.get("agent_id"),
            "para": meta.get("para", {}),
            "triples": meta.get("triples", []),
            "created_at": m["created_at"],
        }
        memories.append(item)
        ep_key = m["epistemic_class"].lower()
        if ep_key in epistemic_buckets:
            epistemic_buckets[ep_key].append(item)
        else:
            epistemic_buckets["fact"].append(item)

    relations = [dict(r) for r in raw_rels]

    # Format human/LLM-readable full graph topology string
    topo_lines: list[str] = []
    topo_lines.append(f"## KNOWLEDGE GRAPH TOPOLOGY OVERVIEW (Scope: {scope})")
    topo_lines.append(f"- Total Active Memories: {len(memories)}")
    topo_lines.append(f"- Total Relational Links: {len(relations)}")
    topo_lines.append(f"- Total Knowledge Entities: {len(raw_entities)}")
    topo_lines.append(f"- Total Registered Scopes: {len(scopes)}")
    topo_lines.append(f"- Total Agents: {len(agents)}")

    # Rules Section
    rules = epistemic_buckets.get("rule", [])
    topo_lines.append(f"\n### 1. GOVERNANCE RULES & INVARIANTS ({len(rules)} nodes):")
    for r in rules:
        topo_lines.append(f"- [{r['id']}] (Scope: {r['scope']}): {r['text']}")

    # Decisions Section
    decisions = epistemic_buckets.get("decision", [])
    topo_lines.append(f"\n### 2. ARCHITECTURAL DECISIONS ({len(decisions)} nodes):")
    for d in decisions:
        topo_lines.append(f"- [{d['id']}] (Scope: {d['scope']}): {d['text']}")

    # Facts & Observations Section
    facts = epistemic_buckets.get("fact", []) + epistemic_buckets.get("observation", [])
    topo_lines.append(f"\n### 3. GROUNDED FACTS & KNOWLEDGE ({len(facts)} nodes):")
    for f in facts:
        topo_lines.append(f"- [{f['id']}] (Scope: {f['scope']}): {f['text']}")

    # Full Relations Matrix
    topo_lines.append(f"\n### 4. COMPLETE RELATIONAL PROPOSITIONS ({len(relations)} edges):")
    for rel in relations:
        topo_lines.append(f"- [{rel['subject']}] ──({rel['predicate']})──▶ [{rel['object']}] (Conf: {rel.get('confidence', 0.95)})")

    # Complete Entities List
    topo_lines.append(f"\n### 5. KNOWLEDGE ENTITY CATALOG ({len(raw_entities)} vertices):")
    topo_lines.append(", ".join(raw_entities))

    # Recent Chain-of-Thought
    if raw_thoughts:
        topo_lines.append(f"\n### 6. RECENT AGENT CHAIN-OF-THOUGHT REASONING ({len(raw_thoughts)} deliberated turns):")
        for th in raw_thoughts[:15]:
            th_preview = th["thinking_text"].replace("\n", " ")[:140]
            topo_lines.append(f"- Agent {th['agent_id']} ({th['created_at'][:19]}): {th_preview}...")

    formatted_topology = "\n".join(topo_lines)

    return {
        "scopes": scopes,
        "agents": agents,
        "memories": memories,
        "epistemic_buckets": epistemic_buckets,
        "relations": relations,
        "entities": raw_entities,
        "formatted_topology": formatted_topology,
        "stats": {
            "total_memories": len(memories),
            "total_relations": len(relations),
            "total_entities": len(raw_entities),
            "total_scopes": len(scopes),
            "total_agents": len(agents),
        },
    }


async def run_graph_synthesis(
    store: SuperCortexStore,
    scope: str = "all",
    focus: str = "",
    provider: ProviderRecord | None = None,
) -> dict[str, Any]:
    """Synthesize high-level patterns, invariants, and strategic insights across the entire knowledge graph."""
    if not provider:
        raise ValueError("An active inference provider (Claude, Gemini, or OpenAI) is required for graph synthesis.")

    # Ingest the entire graph dataset
    graph_ctx = assemble_full_graph_context(store, scope=scope)

    system_prompt = (
        "You are the Super-Cortex Cognitive Architect. You have complete visibility over the entire knowledge graph "
        "dataset of autonomous AI agents. Formulate rigorous, mathematically grounded strategic summaries, highlight "
        "governance invariant compliance, and formulate actionable new knowledge axioms."
    )
    user_prompt = (
        f"You have been provided with the ENTIRE knowledge graph dataset below for scope '{scope}'.\n"
        f"{f'User Operational Focus / Goal: {focus}' if focus else ''}\n\n"
        f"{graph_ctx['formatted_topology']}\n\n"
        "Please provide a comprehensive analytical report covering:\n"
        "1. **Core Architectural Insights**: Synthesis of overarching operational themes, policies, and active capabilities.\n"
        "2. **Risk & Governance Boundaries**: Verification of stop-losses, scope boundaries, and AIS invariants.\n"
        "3. **Proposed New Graph Axioms**: 3 concise, high-value propositions with epistemic classes (rule or fact) "
        "that should be committed into the 3D graph to bridge disparate concepts."
    )

    result = await call_llm(prompt=user_prompt, system_prompt=system_prompt, provider=provider)
    return {
        "scope": scope,
        "synthesis": result["text"],
        "model": result["model"],
        "provider": result["provider"],
        "elapsed_ms": result["elapsed_ms"],
        "tokens": result["tokens"],
        "stats": graph_ctx["stats"],
    }


async def run_link_discovery(
    store: SuperCortexStore,
    scope: str = "all",
    provider: ProviderRecord | None = None,
) -> dict[str, Any]:
    """Use the LLM with entire graph visibility to discover latent, high-value relational links between entities."""
    if not provider:
        raise ValueError("An active inference provider is required for link discovery.")

    graph_ctx = assemble_full_graph_context(store, scope=scope)
    entities = graph_ctx["entities"]
    relations = graph_ctx["relations"]
    memories = graph_ctx["memories"]

    if not entities and not memories:
        return {"discovered_links": [], "count": 0, "provider": provider.name}

    entity_list_str = ", ".join(f'"{e}"' for e in entities)
    existing_rels_str = "\n".join(f"- {r['subject']} ──({r['predicate']})──▶ {r['object']}" for r in relations)

    system_prompt = (
        "You are the Super-Cortex Relational Graph Engine. You have access to the ENTIRE knowledge graph. "
        "Your mission is to discover latent, non-obvious, high-confidence semantic relationships (Subject-Object-Predicate triples) "
        "between existing entities and concepts.\n"
        "Output ONLY a valid JSON array of objects with the exact schema:\n"
        '[{"subject": "Entity A", "predicate": "relation_verb", "object": "Entity B", "confidence": 0.95, "rationale": "one sentence explanation"}]'
    )
    user_prompt = (
        f"All Current Graph Entities ({len(entities)} vertices):\n{entity_list_str}\n\n"
        f"Existing Graph Relations ({len(relations)} edges):\n{existing_rels_str}\n\n"
        f"Full Graph Context Summary:\n{graph_ctx['formatted_topology'][:8000]}\n\n"
        "Discover 6 to 12 new, high-value relational edges that connect previously unlinked or isolated entities. "
        "Ensure subjects and objects match or clearly map to existing knowledge entities. Output ONLY the JSON array."
    )

    res = await call_llm(
        prompt=user_prompt,
        system_prompt=system_prompt,
        provider=provider,
        response_mime_type="application/json",
    )
    raw_text = res["text"].strip()

    # Extract JSON array
    discovered_links: list[dict[str, Any]] = extract_json_array(raw_text)
    if not discovered_links:
        logger.warning("Failed to parse discovered links from model response: %s", raw_text[:300])

    return {
        "discovered_links": discovered_links,
        "count": len(discovered_links),
        "model": res["model"],
        "provider": res["provider"],
        "elapsed_ms": res["elapsed_ms"],
        "stats": graph_ctx["stats"],
    }


async def run_graph_rag_query(
    store: SuperCortexStore,
    query: str,
    scope: str = "all",
    provider: ProviderRecord | None = None,
) -> dict[str, Any]:
    """Execute grounded natural language question answering with complete access to the entire knowledge graph."""
    if not provider:
        raise ValueError("An active inference provider is required for graph query.")

    graph_ctx = assemble_full_graph_context(store, scope=scope)

    system_prompt = (
        "You are the Super-Cortex Grounded Graph Oracle. You have access to the ENTIRE knowledge graph "
        "(all memory nodes, epistemic rules, decisions, facts, and relational edges). "
        "Answer user queries strictly grounded in the provided graph evidence. "
        "Always cite specific memory IDs (e.g. `[mem_...]`) when asserting rules or facts."
    )
    user_prompt = (
        f"User Query: {query}\n\n"
        f"--- COMPLETE GRAPH EVIDENCE DATASET ---\n"
        f"{graph_ctx['formatted_topology']}\n\n"
        "Provide an authoritative, clear answer grounded in the verified graph evidence above."
    )

    res = await call_llm(prompt=user_prompt, system_prompt=system_prompt, provider=provider)

    # Detect cited memory IDs in response
    cited_ids = list(set(re.findall(r"mem_[a-f0-9]{12,16}", res["text"])))

    return {
        "query": query,
        "answer": res["text"],
        "cited_ids": cited_ids,
        "model": res["model"],
        "provider": res["provider"],
        "elapsed_ms": res["elapsed_ms"],
        "tokens": res["tokens"],
        "stats": graph_ctx["stats"],
    }
