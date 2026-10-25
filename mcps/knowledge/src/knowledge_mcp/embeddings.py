from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from knowledge_mcp.config import EmbeddingConfig


class Embedder(Protocol):
    @property
    def max_tokens(self) -> int: ...

    def count_tokens(self, text: str) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...

    def identity(self) -> dict[str, Any]: ...


class SentenceTransformerEmbedder:
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.config.model)
        return self._model

    @property
    def max_tokens(self) -> int:
        model = self._get_model()
        return int(model.max_seq_length)

    def count_tokens(self, text: str) -> int:
        tokenizer = self._get_model().tokenizer
        return len(tokenizer.tokenize(text)) + tokenizer.num_special_tokens_to_add(pair=False)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        encoder = getattr(model, "encode_document", model.encode)
        result = encoder(
            list(texts),
            batch_size=self.config.batch_size,
            normalize_embeddings=self.config.normalize,
            show_progress_bar=False,
        )
        return result.tolist()

    def embed_query(self, text: str) -> list[float]:
        model = self._get_model()
        encoder = getattr(model, "encode_query", model.encode)
        result = encoder(
            [text],
            batch_size=1,
            normalize_embeddings=self.config.normalize,
            show_progress_bar=False,
        )
        return result[0].tolist()

    def identity(self) -> dict[str, Any]:
        model = self._get_model()
        dimension_getter = getattr(model, "get_embedding_dimension", None)
        if dimension_getter is None:
            dimension_getter = model.get_sentence_embedding_dimension
        dimension = dimension_getter()
        revision = self._resolved_revision()
        return {
            "provider": "sentence_transformers",
            "model": self.config.model,
            "resolved_revision": revision,
            "dimension": int(dimension) if dimension is not None else None,
            "normalize": self.config.normalize,
            "max_tokens": self.max_tokens,
            "query_prompt": None,
            "document_prompt": None,
        }

    def _resolved_revision(self) -> str | None:
        model_path = Path(self.config.model).expanduser()
        if model_path.exists():
            return str(model_path.resolve())
        try:
            from huggingface_hub import try_to_load_from_cache

            cached_config = try_to_load_from_cache(self.config.model, "config.json")
        except Exception:
            return None
        if not isinstance(cached_config, str):
            return None
        cached_path = Path(cached_config)
        if cached_path.parent.parent.name == "snapshots":
            return cached_path.parent.name
        return None


EMBEDDER_FACTORIES = {
    "sentence_transformers": SentenceTransformerEmbedder,
}


def create_embedder(config: EmbeddingConfig) -> Embedder:
    try:
        factory = EMBEDDER_FACTORIES[config.provider]
    except KeyError as exc:
        raise ValueError(f"Unknown embedding provider: {config.provider}") from exc
    return factory(config)
