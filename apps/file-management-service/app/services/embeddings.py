from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import numpy as np

from app.core.config import settings

LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_encoder():
    import onnxruntime as ort
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        settings.file_embedding_model_id,
        cache_dir=settings.file_embedding_cache_dir,
    )
    snapshot_dir = Path(
        snapshot_download(
            repo_id=settings.file_embedding_model_id,
            cache_dir=settings.file_embedding_cache_dir,
            allow_patterns=["onnx/*"],
        )
    )
    model_path = snapshot_dir / "onnx" / "model.onnx"
    if not model_path.exists():
        candidates = sorted(snapshot_dir.glob("onnx/*.onnx"))
        if not candidates:
            raise FileNotFoundError(f"no ONNX model found under {snapshot_dir / 'onnx'}")
        model_path = candidates[0]
    model = ort.InferenceSession(
        str(model_path),
        providers=["CPUExecutionProvider"],
    )
    input_names = {item.name for item in model.get_inputs()}
    return tokenizer, model, input_names


def _run_model(model, input_names: set[str], encoded: dict[str, np.ndarray]) -> np.ndarray:
    ort_inputs = {
        name: np.asarray(encoded[name], dtype=np.int64)
        for name in input_names
        if name in encoded
    }
    if not ort_inputs:
        raise RuntimeError("tokenizer produced no compatible ONNX inputs")
    outputs = model.run(None, ort_inputs)
    if not outputs:
        raise RuntimeError("ONNX model returned no outputs")
    hidden = np.asarray(outputs[0])
    if hidden.ndim == 3:
        return hidden[:, 0, :]
    if hidden.ndim == 2:
        return hidden
    raise RuntimeError(f"unexpected embedding output shape: {hidden.shape}")


def _normalize_vectors(vectors: np.ndarray, *, target_dim: int) -> np.ndarray:
    if target_dim < vectors.shape[1]:
        vectors = vectors[:, :target_dim]
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.clip(norms, a_min=1e-12, a_max=None)
    return vectors / norms


def _prepare_inputs(values: list[str], *, is_query: bool) -> list[str]:
    prepared = values
    if is_query and settings.file_embedding_query_instruction.strip():
        prepared = [f"{settings.file_embedding_query_instruction}{item}" for item in values]
    return prepared


def embed_texts(texts: Iterable[str], *, is_query: bool = False, dim: int | None = None) -> list[list[float]]:
    values = [str(item or "").strip() for item in texts if str(item or "").strip()]
    if not values:
        return []
    target_dim = dim or settings.file_embedding_dim
    prepared = _prepare_inputs(values, is_query=is_query)
    try:
        tokenizer, model, input_names = _load_encoder()
        all_vectors: list[list[float]] = []
        batch_size = max(1, settings.file_embedding_batch_size)
        for start in range(0, len(prepared), batch_size):
            batch = prepared[start : start + batch_size]
            encoded = tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=settings.file_embedding_max_length,
                return_tensors="np",
            )
            vectors = _run_model(model, input_names, encoded)
            vectors = _normalize_vectors(vectors, target_dim=target_dim)
            all_vectors.extend(vectors.astype(float).tolist())
        return all_vectors
    except Exception as exc:
        LOGGER.warning("file_embedding_provider_failed error=%s", exc)
        raise RuntimeError(f"embedding provider failed: {exc}") from exc
