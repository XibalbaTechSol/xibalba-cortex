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
    import subprocess
    from .api import create_app

    dist_dir = Path(__file__).resolve().parent.parent.parent / "viewer" / "dist"
    if not dist_dir.exists() or not (dist_dir / "index.html").exists():
        console.print("[yellow]Viewer dist not found. Building now with npm...[/yellow]")
        subprocess.run(["npm", "run", "build"], cwd=dist_dir.parent, check=True)

    app_instance = create_app()
    console.print(f"[bold green]Starting Super-Cortex Studio at http://{host}:{port}[/bold green]")
    uvicorn.run(app_instance, host=host, port=port, log_level="warning")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
