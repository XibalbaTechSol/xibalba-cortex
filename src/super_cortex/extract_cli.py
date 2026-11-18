"""`super-cortex extract`: memory extraction on the model you already pay for.

    super-cortex extract run --with "claude -p"          # loop: claim -> your agent CLI -> submit
    super-cortex extract claim -n agent-claude > job.json  # or do it by hand
    super-cortex extract submit <claimId> answer.json --model my-model
    super-cortex extract release <claimId>

`run` pipes each claim's instructions and prompt to the agent command on stdin and reads JSON
back from its stdout, so any CLI that answers a prompt on stdin works (claude -p, codex exec,
gemini -p, a local llama.cpp wrapper, ...). The engine grounds every memory against its
document, so a sloppy answer is rejected memory by memory, not trusted.
"""

from __future__ import annotations

import asyncio
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import typer

from .client import SupermemoryClient
from .config import SuperCortexConfig

extract_app = typer.Typer(help="Extract memories with your own agent's model (needs the SuperCortex engine).")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def agent_prompt(claim: dict[str, Any]) -> str:
    """What an agent CLI receives: the extractor instructions, the documents, the answer format."""
    return (
        f"{claim['instructions']}\n\n{claim['prompt']}\n\n"
        "Reply with ONLY a JSON object (no prose, no code fence) matching this schema:\n"
        f"{json.dumps(claim['responseSchema'])}"
    )


def parse_answer(text: str) -> list[dict[str, Any]]:
    """The `documents` list from an agent's reply; tolerates a code fence or text around the JSON."""
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the agent's reply")
    data = json.loads(cleaned[start:end + 1])
    documents = data.get("documents") if isinstance(data, dict) else None
    if not isinstance(documents, list):
        raise ValueError('the reply has no "documents" list')
    return documents


def call_agent(command: str, prompt: str, timeout: float) -> str:
    result = subprocess.run(shlex.split(command), input=prompt, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"agent command exited {result.returncode}: {result.stderr.strip()[:300]}")
    return result.stdout


async def run_extraction(client: SupermemoryClient, namespace: str, command: str, model: str,
                         max_claims: int = 10, limit: int = 5, timeout: float = 600.0,
                         echo=lambda message: None) -> dict[str, int]:
    """Claim, ask the agent, submit; until the queue is empty or `max_claims` is reached.

    A reply that cannot be parsed releases the claim and stops the run: the same agent would
    fail the same documents again, and a release does not count as an attempt.
    """
    totals = {"claims": 0, "documents": 0, "stored": 0, "merged": 0, "candidates": 0, "ungrounded": 0}
    while totals["claims"] < max_claims:
        claim = await client.claim_extraction(namespace, limit)
        if not claim.get("claimId"):
            echo("nothing left to extract")
            break
        totals["claims"] += 1
        try:
            reply = await asyncio.to_thread(call_agent, command, agent_prompt(claim), timeout)
            documents = parse_answer(reply)
        except (RuntimeError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            await client.release_extraction(claim["claimId"])
            echo(f"claim {claim['claimId']} released: {exc}")
            totals["failed"] = 1
            break
        stats = await client.submit_extraction(claim["claimId"], model, documents=documents)
        for key in ("documents", "stored", "merged", "candidates", "ungrounded"):
            totals[key] += int(stats.get(key, 0))
        echo(f"claim {totals['claims']}: {stats.get('documents', 0)} documents, {stats.get('stored', 0)} stored, "
             f"{stats.get('ungrounded', 0)} ungrounded")
    return totals


def _client() -> tuple[SupermemoryClient, SuperCortexConfig]:
    config = SuperCortexConfig()
    return SupermemoryClient(config), config


def _namespace(config: SuperCortexConfig, namespace: Optional[str]) -> str:
    if not namespace:
        return config.default_namespace
    return config.shared_namespace if namespace == "shared" else namespace


@extract_app.command("run")
def run_command(
    with_: str = typer.Option(..., "--with", help='Agent command that reads a prompt on stdin, e.g. "claude -p".'),
    namespace: Optional[str] = typer.Option(None, "--namespace", "-n", help="Default: this agent's namespace."),
    model: Optional[str] = typer.Option(None, help="Recorded on each memory as session:<model>. Default: the command name."),
    max_claims: int = typer.Option(10, help="Stop after this many claims."),
    limit: int = typer.Option(5, help="Documents per claim (max 10)."),
    timeout: float = typer.Option(600.0, help="Seconds to wait for the agent per claim."),
) -> None:
    """Extract pending documents with your agent CLI, claim by claim, until the queue is empty."""
    client, config = _client()
    used = model or Path(shlex.split(with_)[0]).name
    totals = asyncio.run(run_extraction(client, _namespace(config, namespace), with_, used, max_claims, limit,
                                        timeout, echo=typer.echo))
    typer.echo(json.dumps(totals))
    if totals.get("failed"):
        raise typer.Exit(1)


@extract_app.command("claim")
def claim_command(
    namespace: Optional[str] = typer.Option(None, "--namespace", "-n"),
    limit: int = typer.Option(5),
    prompt_only: bool = typer.Option(False, "--prompt", help="Print only the agent prompt (claimId goes to stderr)."),
) -> None:
    """Lease pending documents and print the claim (or just the prompt to give your model)."""
    client, config = _client()
    claim = asyncio.run(client.claim_extraction(_namespace(config, namespace), limit))
    if prompt_only:
        if not claim.get("claimId"):
            raise typer.Exit(3)
        typer.echo(claim["claimId"], err=True)
        typer.echo(agent_prompt(claim))
    else:
        typer.echo(json.dumps(claim, indent=2))


@extract_app.command("submit")
def submit_command(
    claim_id: str,
    answer: Optional[Path] = typer.Argument(None, help="File with the model's JSON reply; default stdin."),
    model: str = typer.Option(..., help="The model that produced the answer."),
) -> None:
    """Submit a model's JSON reply for a claim."""
    client, _ = _client()
    text = answer.read_text() if answer else sys.stdin.read()
    stats = asyncio.run(client.submit_extraction(claim_id, model, documents=parse_answer(text)))
    typer.echo(json.dumps(stats, indent=2))


@extract_app.command("release")
def release_command(claim_id: str) -> None:
    """Give a claim back unfinished."""
    client, _ = _client()
    typer.echo(json.dumps(asyncio.run(client.release_extraction(claim_id))))
