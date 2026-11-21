from __future__ import annotations

import asyncio
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table

from .config import SuperCortexConfig
from .memory import SuperCortex
from .server import create_server

app = typer.Typer(help="Super-Cortex: Cryptographic Memory Engine backed by Supermemory Local")
console = Console()

from .retrieval_eval.cli import engine_app, eval_app  # noqa: E402

app.add_typer(eval_app, name="eval")
app.add_typer(engine_app, name="engine")

from .extract_cli import extract_app  # noqa: E402

app.add_typer(extract_app, name="extract")


@app.command()
def doctor() -> None:
    """Check connectivity to Supermemory Local, verify database integrity, and display operational health."""
    config = SuperCortexConfig()
    cortex = SuperCortex(config)

    table = Table(title="Super-Cortex Diagnostic & Health Report")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details", style="dim")

    # 1. Supermemory Daemon Check
    alive = asyncio.run(cortex.client.ping())
    if alive:
        table.add_row("Supermemory Daemon", "[green]ONLINE[/green]", config.supermemory_url)
    else:
        table.add_row("Supermemory Daemon", "[red]OFFLINE[/red]", f"Cannot reach {config.supermemory_url}")

    # 2. API Key Check
    if config.supermemory_api_key:
        masked_key = f"{config.supermemory_api_key[:6]}...{config.supermemory_api_key[-4:]}"
        table.add_row("API Key", "[green]CONFIGURED[/green]", masked_key)
    else:
        table.add_row("API Key", "[yellow]MISSING[/yellow]", "No key found in env or ~/.supermemory/api-key")

    # 3. Database & Hash Chain Check
    chain = cortex.verify_chain()
    if chain.get("valid"):
        table.add_row(
            "Provenance Ledger",
            "[green]VERIFIED[/green]",
            f"{chain.get('event_count', 0)} events, head={chain.get('head_hash', '')[:12]}...",
        )
    else:
        table.add_row("Provenance Ledger", "[red]CORRUPTED[/red]", str(chain.get("error")))

    # 4. Identity DID
    table.add_row("Actor DID", "[blue]ACTIVE[/blue]", config.actor_did)

    console.print(table)


@app.command()
def run(transport: str = typer.Option("stdio", help="MCP transport: stdio or sse")) -> None:
    """Run the Super-Cortex MCP server."""
    server = create_server()
    if transport != "stdio":
        console.print(f"[bold green]Starting Super-Cortex MCP server using {transport} transport...[/bold green]")
    server.run(transport=transport)


@app.command()
def remember(
    text: str = typer.Argument(..., help="Memory text to store"),
    namespace: Optional[str] = typer.Option(None, "--namespace", "-n", help="Namespace"),
    epistemic_class: str = typer.Option("fact", "--class", "-c", help="Epistemic class (fact, inference, etc.)"),
) -> None:
    """Store a memory into both Supermemory Local and the cryptographic provenance ledger."""
    cortex = SuperCortex()
    res = asyncio.run(
        cortex.remember(
            text=text,
            epistemic_class=epistemic_class,
            namespace=namespace,
        )
    )
    console.print("[green]Memory committed successfully![/green]")
    console.print(res)


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    namespace: Optional[str] = typer.Option(None, "--namespace", "-n", help="Namespace"),
    limit: int = typer.Option(5, "--limit", "-l", help="Max results"),
) -> None:
    """Perform semantic hybrid search across Supermemory Local."""
    cortex = SuperCortex()
    res = asyncio.run(cortex.hybrid_retrieve(query=query, namespace=namespace, limit=limit))
    results = res.get("results", [])

    if not results:
        console.print("[yellow]No matching memories found.[/yellow]")
        return

    table = Table(title=f"Search Results for: '{query}'")
    table.add_column("Similarity", style="cyan")
    table.add_column("ID", style="bold")
    table.add_column("Content")
    table.add_column("Provenance", style="dim")

    for r in results:
        prov = r.get("provenance", {})
        table.add_row(
            f"{r.get('similarity', 0.0):.3f}",
            str(r.get("id")),
            str(r.get("content"))[:120],
            f"Class: {prov.get('epistemic_class')}, Status: {prov.get('lifecycle_status')}",
        )

    console.print(table)


@app.command()
def verify() -> None:
    """Verify the cryptographic hash-chain across all events."""
    cortex = SuperCortex()
    res = cortex.verify_chain()
    if res.get("valid"):
        console.print(
            f"[bold green]✓ Event chain verified valid![/bold green] Total events: {res.get('event_count')}, Head hash: {res.get('head_hash')}"
        )
    else:
        console.print(f"[bold red]✗ Verification failed:[/bold red] {res.get('error')}")


@app.command()
def sessions() -> None:
    """View temporal distribution of all agent interaction sessions."""
    cortex = SuperCortex()
    session_list = cortex.get_session_distribution()

    if not session_list:
        console.print("[yellow]No agent sessions recorded in the provenance ledger yet.[/yellow]")
        return

    table = Table(title="Agent Session Temporal Distribution")
    table.add_column("Session ID", style="cyan")
    table.add_column("Turns", justify="right", style="bold")
    table.add_column("Tools", justify="right", style="magenta")
    table.add_column("Start Time", style="dim")
    table.add_column("Merkle Root", style="green")

    for s in session_list:
        table.add_row(
            str(s["session_id"]),
            str(s["turn_count"]),
            str(s["tool_execution_count"]),
            str(s["start_time"])[:19],
            f"{s['merkle_root'][:12]}...",
        )

    console.print(table)


@app.command()
def viewer(
    port: int = typer.Option(4174, "--port", "-p", help="Port to serve the viewer on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host interface"),
) -> None:
    """Launch the Super-Cortex interactive Graph & Timeline web interface."""
    import uvicorn
    from pathlib import Path
    from .api import create_app

    viewer_dir = Path(__file__).resolve().parent.parent.parent / "viewer"
    if not (viewer_dir / "index.html").exists():
        console.print("[red]Viewer index.html not found.[/red]")
        raise typer.Exit(code=1)

    app_instance = create_app()
    console.print(f"[bold green]Starting Super-Cortex Studio at http://{host}:{port}[/bold green]")
    uvicorn.run(app_instance, host=host, port=port, log_level="warning")


@app.command()
def context(
    scope: str = typer.Option("shared", "--scope", "-s", help="Scope enclave (e.g. shared, agent:xibalba, all)"),
    format: str = typer.Option("markdown", "--format", "-f", help="Output format: markdown or json"),
) -> None:
    """Generate and print zero-inference prompt-ready context markdown for LLM injection."""
    cortex = SuperCortex()
    memories = cortex.store.list_memories(scope=scope if scope != "all" else None, limit=100)
    
    valid_mems = [m for m in memories if m.get("valid_time", {}).get("is_currently_valid", True)]
    rules = [m for m in valid_mems if m.get("epistemic_class") == "rule"]
    facts = [m for m in valid_mems if m.get("epistemic_class") == "fact"]
    decisions = [m for m in valid_mems if m.get("epistemic_class") == "decision"]
    
    all_triples = []
    for m in valid_mems:
        triples = m.get("triples") or []
        for t in triples:
            all_triples.append(t)
    
    if format == "json":
        import json
        payload = {
            "scope": scope,
            "rules": [r.get("text", r.get("content", "")) for r in rules],
            "facts": [f.get("text", f.get("content", "")) for f in facts],
            "decisions": [d.get("text", d.get("content", "")) for d in decisions],
            "triples": all_triples,
            "total_memories": len(valid_mems)
        }
        console.print(json.dumps(payload, indent=2))
        return

    lines = [
        f"<!-- SUPER-CORTEX DETERMINISTIC CONTEXT INJECTION (Zero-Inference) -->",
        f"<SUPER_CORTEX_MEMORY_FABRIC scope='{scope.upper()}'>",
        f"## Active Scope Enclave: {scope.upper()}",
        "",
        "### Epistemic Rules & Invariants:"
    ]
    if rules:
        for r in rules:
            lines.append(f"- {r.get('text', r.get('content', ''))}")
    else:
        lines.append("- (No active rules defined in this scope)")
    
    if decisions:
        lines.append("")
        lines.append("### Architectural Decisions:")
        for d in decisions:
            lines.append(f"- {d.get('text', d.get('content', ''))}")
            
    if all_triples:
        lines.append("")
        lines.append("### Relational Knowledge Triples (SOP):")
        for t in all_triples[:25]:
            lines.append(f"- [{t.get('subject')}] ──({t.get('predicate')})──▶ [{t.get('object')}]")

    lines.append("")
    lines.append("</SUPER_CORTEX_MEMORY_FABRIC>")
    print("\n".join(lines))


@app.command()
def ingest(
    target: str = typer.Argument(..., help="File path or URL to ingest"),
    scope: str = typer.Option("shared", "--scope", "-s", help="Target scope enclave"),
) -> None:
    """Ingest a web URL or local file directly into memory and provenance ledger."""
    cortex = SuperCortex()
    
    if target.startswith("http://") or target.startswith("https://"):
        import httpx
        import re
        console.print(f"[cyan]Scraping and ingesting URL:[/cyan] {target}")
        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                resp = client.get(target)
                html = resp.text
            
            title_m = re.search(r'<title>(.*?)</title>', html, re.I | re.S)
            title = title_m.group(1).strip() if title_m else target
            clean_text = re.sub(r'<script.*?</script>', '', html, flags=re.I | re.S)
            clean_text = re.sub(r'<style.*?</style>', '', clean_text, flags=re.I | re.S)
            clean_text = re.sub(r'<.*?>', ' ', clean_text)
            clean_text = ' '.join(clean_text.split())[:3000]
            
            text_to_save = f"Web URL [{title}]: {clean_text}"
            res = asyncio.run(cortex.remember(
                text=text_to_save,
                epistemic_class="fact",
                namespace=scope,
                metadata={"url": target, "source_origin": "cli_url_ingest"}
            ))
            console.print(f"[bold green]✓ Ingested URL successfully![/bold green] Memory ID: {res.get('memory_id')}")
        except Exception as e:
            console.print(f"[bold red]✗ URL ingestion failed:[/bold red] {e}")
    else:
        from pathlib import Path
        p = Path(target).resolve()
        if not p.exists():
            console.print(f"[bold red]File not found:[/bold red] {p}")
            return
        
        console.print(f"[cyan]Ingesting local document:[/cyan] {p.name}")
        content = p.read_text(encoding="utf-8", errors="ignore")[:4000]
        text_to_save = f"Document [{p.name}]: {content}"
        res = asyncio.run(cortex.remember(
            text=text_to_save,
            epistemic_class="fact",
            namespace=scope,
            metadata={"filename": p.name, "source_origin": "cli_file_ingest"}
        ))
        console.print(f"[bold green]✓ Ingested file successfully![/bold green] Memory ID: {res.get('memory_id')}")


@app.command()
def watch(
    directory: str = typer.Argument(..., help="Directory path to monitor"),
    scope: str = typer.Option("shared", "--scope", "-s", help="Target scope enclave"),
    interval: float = typer.Option(2.0, "--interval", "-i", help="Polling interval in seconds"),
) -> None:
    """Continuously watch a directory and auto-ingest new or modified text/markdown files."""
    from pathlib import Path
    import time
    
    dir_path = Path(directory).resolve()
    if not dir_path.exists() or not dir_path.is_dir():
        console.print(f"[bold red]Directory not found:[/bold red] {dir_path}")
        return
        
    cortex = SuperCortex()
    console.print(f"[bold green]Watching directory:[/bold green] {dir_path} (scope: {scope})")
    console.print("[dim]Press Ctrl+C to stop watcher...[/dim]")
    
    seen_files: dict[str, float] = {}
    for p in dir_path.rglob("*"):
        if p.is_file() and p.suffix.lower() in [".md", ".txt", ".json", ".yaml", ".yml"]:
            seen_files[str(p)] = p.stat().st_mtime

    try:
        while True:
            time.sleep(interval)
            for p in dir_path.rglob("*"):
                if not p.is_file() or p.suffix.lower() not in [".md", ".txt", ".json", ".yaml", ".yml"]:
                    continue
                spath = str(p)
                mtime = p.stat().st_mtime
                if spath not in seen_files or mtime > seen_files[spath]:
                    seen_files[spath] = mtime
                    console.print(f"[cyan]Detected change:[/cyan] {p.name}")
                    try:
                        content = p.read_text(encoding="utf-8", errors="ignore")[:3500]
                        res = asyncio.run(cortex.remember(
                            text=f"Auto-Watched Document [{p.name}]: {content}",
                            epistemic_class="fact",
                            namespace=scope,
                            metadata={"filename": p.name, "source_origin": "directory_watcher"}
                        ))
                        console.print(f"  [green]✓ Ingested:[/green] {p.name} (id: {res.get('memory_id')})")
                    except Exception as err:
                        console.print(f"  [red]✗ Ingestion error:[/red] {err}")
    except KeyboardInterrupt:
        console.print("[yellow]Watcher stopped.[/yellow]")


@app.command("migrate-legacy")
def migrate_legacy(
    max_per_db: int = typer.Option(250, "--max-per-db", help="Maximum high-signal memories to migrate per legacy DB"),
) -> None:
    """Migrate memories, entities, and relations from legacy xibalba-cortex SQLite databases into Super-Cortex."""
    from .legacy_migration import migrate_legacy_cortex_databases

    cortex = SuperCortex()
    res = migrate_legacy_cortex_databases(cortex.store, max_memories_per_db=max_per_db)
    table = Table(title="Legacy Cortex -> Super-Cortex Migration Summary")
    table.add_column("Agent / Profile", style="cyan")
    table.add_column("Scope", style="magenta")
    table.add_column("Memories", justify="right", style="green")
    table.add_column("Entities", justify="right", style="blue")
    table.add_column("Relations", justify="right", style="yellow")
    for item in res.get("per_database", []):
        table.add_row(
            str(item["agent_id"]),
            str(item["scope_id"]),
            str(item["memories_migrated"]),
            str(item["entities_migrated"]),
            str(item["relations_migrated"]),
        )
    console.print(table)
    console.print(
        f"[bold green]✓ Migrated {res['memories_migrated']} memories, "
        f"{res['entities_migrated']} entities, and {res['relations_migrated']} relations "
        f"across {res['databases_scanned']} databases.[/bold green]"
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
