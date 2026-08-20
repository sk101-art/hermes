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
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                print(f"Loading local embedding model ({self.model_name}) on {self.device}...", flush=True)
                self._model = SentenceTransformer(self.model_name, device=self.device)
            except Exception as e:
                # If specified device fails, fall back to CPU
                if self.device != "cpu":
                    print(f"[Warning] Failed loading on {self.device} ({e}). Falling back to CPU.", flush=True)
                    self.device = "cpu"
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self.model_name, device="cpu")
                else:
                    raise e
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
