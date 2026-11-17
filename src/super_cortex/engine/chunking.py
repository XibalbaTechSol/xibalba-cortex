"""Split documents into retrieval chunks.

Paragraph-first, then sentence packing up to `max_chars`, with one sentence of overlap between
neighbouring chunks so a fact that straddles a boundary is still retrievable whole. Short
documents -- most agent memories -- stay a single chunk.
"""

from __future__ import annotations

import re

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'`(\[])")


def chunk_text(text: str, max_chars: int = 800) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    sentences: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        for sentence in _SENTENCE.split(para):
            sentence = sentence.strip()
            # A single over-long sentence (logs, code) is hard-wrapped rather than dropped.
            while len(sentence) > max_chars:
                sentences.append(sentence[:max_chars])
                sentence = sentence[max_chars:]
            if sentence:
                sentences.append(sentence)
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for sentence in sentences:
        if current and size + len(sentence) + 1 > max_chars:
            chunks.append(" ".join(current))
            overlap = current[-1]
            current = [overlap] if len(overlap) + len(sentence) + 1 <= max_chars else []
            size = sum(len(s) + 1 for s in current)
        current.append(sentence)
        size += len(sentence) + 1
    if current:
        chunks.append(" ".join(current))
    return chunks
