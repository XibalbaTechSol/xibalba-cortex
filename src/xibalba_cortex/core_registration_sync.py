"""Strict adapter for syncing CORE's on-chain agent directory into Cortex.

The adapter is deliberately transport-agnostic: an authenticated indexer fetches the
CORE response, then passes the decoded payload here. Cortex only accepts exact canonical
DIDs whose controller matches the account binding and whose snapshot is marked finalized.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
from urllib.request import Request, urlopen
import argparse
import os
import re

from .accounts import sync_account_registrations


def registered_agents_for_controller(payload: Mapping[str, object], controller: str) -> list[str]:
    if payload.get("finalized") is not True:
        raise ValueError("CORE registration snapshot is not finalized")
    # The operator bit alone is not a finality proof.  Require the oracle's
    # finalized execution-client cursor and ensure it covers the directory
    # cursor being applied; otherwise a caller could mark an arbitrary/latest
    # snapshot as finalized and widen Cortex access across a reorg boundary.
    try:
        block_number = int(payload["block_number"])
        finalized_block_number = int(payload["finalized_block_number"])
        finalized_block_hash = str(payload["finalized_block_hash"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("CORE snapshot is missing its finalized chain cursor") from exc
    if block_number < 0 or finalized_block_number < block_number:
        raise ValueError("CORE snapshot block is newer than its finalized cursor")
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", finalized_block_hash):
        raise ValueError("CORE snapshot has an invalid finalized block hash")
    expected = str(controller).strip().lower()
    if len(expected) != 42 or not expected.startswith("0x"):
        raise ValueError("controller must be a 20-byte EVM address")
    raw_agents = payload.get("agents")
    if not isinstance(raw_agents, list):
        raise ValueError("CORE registration snapshot must contain an agents list")
    result: set[str] = set()
    for row in raw_agents:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("controller") or "").strip().lower() != expected:
            continue
        agent_id = str(row.get("id") or "").strip()
        if not agent_id.startswith("did:integrity:") or len(agent_id) <= len("did:integrity:"):
            raise ValueError("CORE returned a non-canonical agent id")
        result.add(agent_id)
    return sorted(result)


def sync_account_from_core(payload: Mapping[str, object], *, home: str, account_id: str, controller: str) -> list[str]:
    agent_ids = registered_agents_for_controller(payload, controller)
    try:
        chain_id = int(payload["chain_id"])
        block_number = int(payload["block_number"])
        tx_hash = str(payload["snapshot_id"])
        log_index = int(payload.get("log_index", 0))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("CORE snapshot is missing its finalized chain cursor") from exc
    if not sync_account_registrations(home, account_id=account_id, chain_id=chain_id, block_number=block_number, tx_hash=tx_hash, log_index=log_index, agent_ids=agent_ids, finalized=True):
        raise LookupError("account is not active")
    return agent_ids


def sync_account_from_core_endpoint(*, endpoint: str, home: str, account_id: str, controller: str, timeout: float = 5.0) -> list[str]:
    """Fetch `/v1/agents/snapshot` and apply it; transport errors never mutate access."""
    url = endpoint.rstrip("/") + "/v1/agents/snapshot"
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, Mapping):
        raise ValueError("CORE snapshot response must be an object")
    return sync_account_from_core(payload, home=home, account_id=account_id, controller=controller)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync a Cortex account from finalized CORE registrations")
    parser.add_argument("--endpoint", default=os.environ.get("XIBALBA_CORE_ORACLE_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--home", default=os.environ.get("XIBALBA_CORTEX_HOME"), required=not bool(os.environ.get("XIBALBA_CORTEX_HOME")))
    parser.add_argument("--account-id", default=os.environ.get("XIBALBA_CORTEX_ACCOUNT_ID"), required=not bool(os.environ.get("XIBALBA_CORTEX_ACCOUNT_ID")))
    parser.add_argument("--controller", default=os.environ.get("XIBALBA_CORTEX_CONTROLLER"), required=not bool(os.environ.get("XIBALBA_CORTEX_CONTROLLER")))
    args = parser.parse_args()
    ids = sync_account_from_core_endpoint(endpoint=args.endpoint, home=args.home, account_id=args.account_id, controller=args.controller)
    print(json.dumps({"synced": True, "account_id": args.account_id, "agent_ids": ids}))
