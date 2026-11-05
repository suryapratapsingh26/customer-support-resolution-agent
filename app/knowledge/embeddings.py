from collections.abc import Sequence
import logging
import math

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    pass


class SentenceTransformerEmbedder:
    """Lazy local sentence-transformer; document and query vectors share one model."""

    def __init__(self, model_name: str, device: str = "cpu"):
        self.model_name, self.device = model_name, device
        self._model = None
        self._dimension: int | None = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name, device=self.device)
                get_dimension = getattr(self._model, "get_embedding_dimension", None)
                if get_dimension is None:
                    get_dimension = self._model.get_sentence_embedding_dimension
                self._dimension = int(get_dimension())
            except Exception as exc:
                raise EmbeddingError(f"Could not load embedding model '{self.model_name}': {exc}") from exc
        return self._model

    @property
    def dimension(self) -> int:
        self._load()
        return self._dimension  # type: ignore[return-value]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise EmbeddingError("Embedding input must contain non-empty text.")
        try:
            vectors = self._load().encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
            result = [[float(value) for value in vector] for vector in vectors]
            if len(result) != len(texts):
                raise ValueError("Model returned a different number of embeddings than inputs.")
            if any(
                len(vector) != self.dimension
                or any(not math.isfinite(value) for value in vector)
                for vector in result
            ):
                raise ValueError("Model returned an invalid embedding.")
            return result
        except EmbeddingError:
            raise
        except Exception as exc:
            logger.exception("Embedding generation failed")
            raise EmbeddingError(f"Embedding generation failed: {exc}") from exc
