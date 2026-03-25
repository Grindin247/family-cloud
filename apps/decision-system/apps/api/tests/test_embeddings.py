from __future__ import annotations

from app.services import embeddings


def test_embed_texts_falls_back_when_openai_provider_errors(monkeypatch) -> None:
    class _EmbeddingsClient:
        def create(self, **kwargs):
            raise RuntimeError("quota exceeded")

    class _OpenAIClient:
        def __init__(self, **kwargs):
            self.embeddings = _EmbeddingsClient()

    monkeypatch.setattr(embeddings.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(embeddings, "OpenAI", _OpenAIClient)

    vectors = embeddings.embed_texts(["hello world"], dim=8)

    assert len(vectors) == 1
    assert len(vectors[0]) == 8
    assert vectors[0] == embeddings.embed_text("hello world", dim=8)
