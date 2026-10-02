"""Small multilingual posting index; no model calls or SQLite extensions."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator


def normalized_search_text(text: str) -> str:
    # Half-width kana/full-width Latin and decomposed voiced marks must share
    # postings with their ordinary spelling. Do not transliterate proper names.
    return unicodedata.normalize('NFKC', text).casefold()


def normalized_search_offsets(text: str) -> tuple[str, list[int]]:
    """Map normalized English/CJK match offsets back to the quoted source."""
    pieces, offsets = [], []
    start = 0
    for index in range(1, len(text) + 1):
        # Dakuten can be a combining mark or a half-width modifier letter.
        if index < len(text) and (unicodedata.combining(text[index]) or text[index] in '\uff9e\uff9f'):
            continue
        piece = normalized_search_text(text[start:index])
        pieces.append(piece)
        offsets.extend([start] * len(piece))
        start = index
    return ''.join(pieces), offsets


def term_occurrences(text: str) -> Iterator[str]:
    """Yield occurrences, in source order; sets are only for posting lookups."""
    normalized = normalized_search_text(text)
    for match in re.finditer(
        r"[a-z0-9_\u00c0-\u024f]{2,}|[\u3040-\u30ff\u3400-\u9fff\u3005]+", normalized
    ):
        run = match.group()
        if re.match(r"[a-z0-9_\u00c0-\u024f]", run):
            yield run
        elif len(run) == 1:
            yield run
        else:
            yield from (run[i:i + 2] for i in range(len(run) - 1))


def terms(text: str) -> set[str]:
    return set(term_occurrences(text))


def memory_text(content: dict) -> str:
    pieces = []
    for key, value in content.items():
        if key in {"children", "message_ids", "source_ids", "period_start", "period_end", "timezone"}:
            continue
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    pieces.append(str(item.get("text", item.get("value", ""))))
                else:
                    pieces.append(str(item))
        elif value:
            pieces.append(str(value))
    return "；".join(pieces)
