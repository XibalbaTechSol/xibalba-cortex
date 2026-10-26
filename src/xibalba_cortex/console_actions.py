"""Console actions that write or reach outward: document import, backups, upload hygiene.

The rule every function here serves is the one the console states on screen: **the browser sends an
id, a hash or bytes it chose, never a path, and never learns one.** A backup destination, a vault, a
DAG home and an anchor service are server configuration (environment variables). So:

  * a backup is written to ``$XIBALBA_BACKUP_DIR`` under a name the SERVER generates; a reconcile
    names an existing backup by that generated name, which is matched against the directory
    listing, so ``../../etc/passwd`` is not a backup name, it is simply not in the list;
  * an uploaded file's bytes go to a temp file the server picks, under the profile's own folder, and
    the client's filename is reduced to a safe display name and never used as a path;
  * an imported document becomes memories with ``source.kind = imported_document``, status
    ``candidate``; entities and relations found in it are PROPOSALS that wait for review, never graph
    writes (extraction is proposal-only in this system).

Pure functions plus thin store calls, so they are unit-tested without HTTP.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_CHUNKS = 200
CHUNK_TARGET_CHARS = 3000
MAX_EXPORT_IDS = 500

_BACKUP_NAME = re.compile(r"^cortex-backup-\d{8}T\d{6}Z(?:-[0-9a-f]{6})?\.sqlite3$")
_MEDIA_TYPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,62}/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,62}$")


# --- uploads ----------------------------------------------------------------------------------------------

def safe_display_name(raw: str | None, *, default: str = "upload") -> str:
    """A filename for DISPLAY and provenance only. Reduced to its last path component, stripped of
    control and path characters, and bounded: the server never opens a path built from it."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    name = re.sub(r"[^A-Za-z0-9._ \-()]", "_", name)
    return name[:120] or default


def clean_media_type(raw: str | None) -> str:
    """The declared media type if it is a plausible `type/subtype`, else `application/octet-stream`.
    A header is attacker-controlled text; it is stored as a label, never interpreted."""
    value = (raw or "").split(";", 1)[0].strip().lower()
    return value if _MEDIA_TYPE.match(value) else "application/octet-stream"


# --- document import --------------------------------------------------------------------------------------

def split_document(text: str) -> list[tuple[str, str]]:
    """Split a text or Markdown document into (title, body) chunks.

    Markdown headings start a new chunk, and the heading is the chunk's title. A section longer than
    CHUNK_TARGET_CHARS is cut at paragraph boundaries, so no single memory is a wall of text. Blank
    chunks are dropped. Deterministic: the same text always yields the same chunks in the same order,
    which is what makes re-importing a file idempotent.
    """
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            sections.append((heading.group(1).strip(), []))
        else:
            sections[-1][1].append(line)
    chunks: list[tuple[str, str]] = []
    for title, lines in sections:
        paragraphs = [p.strip() for p in "\n".join(lines).split("\n\n") if p.strip()]
        current = ""
        for paragraph in paragraphs:
            if current and len(current) + len(paragraph) + 2 > CHUNK_TARGET_CHARS:
                chunks.append((title, current))
                current = ""
            # a single paragraph longer than the target is kept whole rather than cut mid-sentence
            current = f"{current}\n\n{paragraph}" if current else paragraph
        if current:
            chunks.append((title, current))
    return chunks


def decode_document(data: bytes) -> str:
    if not data:
        raise ValueError("the file is empty")
    if len(data) > MAX_IMPORT_BYTES:
        raise ValueError(f"the file is larger than the {MAX_IMPORT_BYTES // (1024 * 1024)} MB import limit")
    if b"\x00" in data[:8192]:
        raise ValueError("this looks like a binary file; import accepts text and Markdown")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("the file is not UTF-8 text; import accepts text and Markdown") from exc


def import_document(
    store: Any,
    *,
    filename: str | None,
    data: bytes,
    source_agent_id: str | None = None,
    persisted_agent_id: str | None = None,
    propose_entities: bool = True,
) -> dict[str, object]:
    """Store a document as candidate memories, and queue structural entity proposals for review.

    Idempotent per (document bytes, chunk number): importing the same file twice stores nothing new
    and says so. Nothing here writes to the knowledge graph: proposals wait in Review.
    """
    text = decode_document(data)
    chunks = split_document(text)
    if not chunks:
        raise ValueError("the file has no text to import")
    if len(chunks) > MAX_IMPORT_CHUNKS:
        raise ValueError(f"the document splits into {len(chunks)} sections; the limit is {MAX_IMPORT_CHUNKS}. Split the file and import the parts")
    digest = hashlib.sha256(data).hexdigest()
    name = safe_display_name(filename, default="document")
    imported: list[str] = []
    duplicates = 0
    proposals = 0
    for index, (title, body) in enumerate(chunks, start=1):
        key = f"import:{digest}:{index}"
        source: dict[str, object] = {
            "kind": "imported_document",
            "locator": f"import://{digest[:16]}/{name}#{index}",
            "title": title or name,
            "filename": name,
            "document_sha256": f"sha256:{digest}",
            "chunk": index,
            "chunks": len(chunks),
        }
        if source_agent_id:
            source["agent_id"] = source_agent_id
        existed = store.find_memory_id_by_idempotency_key(key)
        memory = store.store_memory(
            body, source=source, status="candidate", evidence_class="extracted_proposition",
            idempotency_key=key, persisted_agent_id=persisted_agent_id,
        )
        if existed:
            duplicates += 1
            continue
        imported.append(str(memory["id"]))
        if propose_entities:
            try:
                store.run_structural_extraction(str(memory["id"]), claimed_by="console-import")
                proposals += 1
            except Exception:  # a failed proposal run must not lose the memory that was stored
                pass
    return {
        "document": {"name": name, "sha256": f"sha256:{digest}", "bytes": len(data), "sections": len(chunks)},
        "imported": len(imported),
        "already_present": duplicates,
        "memory_ids": imported,
        "proposal_runs": proposals,
        "status": "candidate",
        "note": "Stored as candidate memories (source: imported document). Entities and relations found in them are proposals that wait in Review; nothing was added to the graph.",
    }


# --- backups ----------------------------------------------------------------------------------------------

def configured_backup_dir(environ: dict[str, str] | None = None) -> Path | None:
    value = (environ if environ is not None else os.environ).get("XIBALBA_BACKUP_DIR", "").strip()
    return Path(value).expanduser() if value else None


def new_backup_name(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"cortex-backup-{stamp}-{secrets.token_hex(3)}.sqlite3"


def list_backups(directory: Path) -> list[dict[str, object]]:
    """Backups in the configured directory, newest first: a name, a size and a time. Never a path."""
    if not directory.is_dir():
        return []
    out = []
    for entry in directory.iterdir():
        if not _BACKUP_NAME.match(entry.name) or not entry.is_file():
            continue
        stat = entry.stat()
        out.append({
            "name": entry.name,
            "bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        })
    return sorted(out, key=lambda b: str(b["modified_at"]), reverse=True)


def resolve_backup(directory: Path, name: str) -> Path:
    """The file for a backup name the server itself listed. Anything else is KeyError (HTTP 404).

    The name must match the server's own naming pattern AND be present in the directory listing, and
    the resolved path must sit directly inside the directory: a traversal string fails the first
    check, and a symlink pointing elsewhere fails the last.
    """
    if not isinstance(name, str) or not _BACKUP_NAME.match(name):
        raise KeyError(name)
    candidate = (directory / name)
    if not candidate.is_file() or candidate.resolve().parent != directory.resolve():
        raise KeyError(name)
    return candidate


def public_backup_result(result: dict[str, object], name: str) -> dict[str, object]:
    """A backup result without its destination path, naming the file by its generated name only."""
    recon = result.get("reconciliation") if isinstance(result.get("reconciliation"), dict) else None
    return {
        "name": name,
        "integrity_check": result.get("integrity_check"),
        "schema_version": result.get("schema_version"),
        "reconciliation": summarize_reconciliation(recon) if recon else None,
        "claim": backup_claim(result.get("integrity_check"), recon),
    }


def summarize_reconciliation(recon: dict[str, object]) -> dict[str, object]:
    per_domain = recon.get("domains") if isinstance(recon.get("domains"), dict) else {}
    return {
        "equal": bool(recon.get("equal")),
        "domains": {
            str(name): {"equal": bool(d.get("equal")), "live_leaf_count": d.get("live_leaf_count"), "destination_leaf_count": d.get("destination_leaf_count")}
            for name, d in per_domain.items() if isinstance(d, dict)
        },
    }


def backup_claim(integrity_check: object, recon: dict[str, object] | None) -> str:
    """What a backup result does and does not show, in one sentence.

    A complete copy is not a restorable one: this checks the copy is structurally sound and that its
    canonical content matches the live store RIGHT NOW. It does not restore anything, and it does not
    prove the copy would have matched the store at some earlier time.
    """
    if integrity_check != "ok":
        return "The copy failed SQLite's own integrity check. Do not rely on it."
    if recon is None:
        return "The copy passed SQLite's integrity check. Its content was not compared with the live store."
    if not recon.get("equal"):
        return "The copy is structurally sound but its content DIFFERS from the live store. It is incomplete or the store changed while it was taken."
    return "The copy is complete: structurally sound, and its memories, entities and relations match the live store as of now. This does not show it restores."
