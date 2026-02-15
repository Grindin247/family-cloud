from __future__ import annotations


def chunk_text(text: str, *, max_chars: int = 1800) -> list[str]:
    """
    Cheap chunking strategy suitable for embedding baselines.
    """
    text = (text or "").strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]

