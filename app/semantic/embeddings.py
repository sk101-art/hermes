import re
from typing import List, Optional
import numpy as np

from app.models.schemas import Event


def prepare_event_text(event: Event, max_chars: int = 2500) -> str:
    """Deterministic extraction of textual content for embedding generation."""
    parts = [event.title]
    if event.text:
        parts.append(event.text)
    if event.topics:
        parts.append("Topics: " + ", ".join(event.topics))

    combined = " | ".join(parts)
    # Clean whitespace
    cleaned = re.sub(r"\s+", " ", combined).strip()
    return cleaned[:max_chars]


class EmbeddingService:
    """Local embedding service using sentence-transformers on CPU."""
    _cached_models = {}

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: str = "cpu",
        batch_size: int = 16,
    ):
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self._model = None

    def _load_model(self):
        cache_key = (self.model_name, self.device)
        if cache_key not in EmbeddingService._cached_models:
            try:
                from sentence_transformers import SentenceTransformer

                print(f"Loading local embedding model ({self.model_name}) on {self.device}...", flush=True)
                EmbeddingService._cached_models[cache_key] = SentenceTransformer(self.model_name, device=self.device)
            except Exception as e:
                # If specified device fails, fall back to CPU
                if self.device != "cpu":
                    print(f"[Warning] Failed loading on {self.device} ({e}). Falling back to CPU.", flush=True)
                    self.device = "cpu"
                    from sentence_transformers import SentenceTransformer

                    EmbeddingService._cached_models[(self.model_name, "cpu")] = SentenceTransformer(self.model_name, device="cpu")
                else:
                    raise e
        self._model = EmbeddingService._cached_models.get(cache_key) or EmbeddingService._cached_models.get((self.model_name, "cpu"))
        return self._model

    def embed(self, text: str) -> np.ndarray:
        """Generate normalized float32 embedding for a single text."""
        model = self._load_model()
        vec = model.encode(text, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vec, dtype=np.float32)

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        """Generate normalized float32 embeddings for a batch of texts."""
        if not texts:
            return np.empty((0, 384), dtype=np.float32)
        model = self._load_model()
        vecs = model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vecs, dtype=np.float32)

    def unload(self) -> None:
        """Releases the underlying model reference from instance and triggers garbage collection."""
        self._model = None
        import gc
        gc.collect()
