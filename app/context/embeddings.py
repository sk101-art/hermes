from typing import Optional, Tuple
import numpy as np

from app.semantic.embeddings import EmbeddingService
from app.storage.db import Database

_global_embedder: Optional[EmbeddingService] = None


def get_embedder() -> EmbeddingService:
    global _global_embedder
    if _global_embedder is None:
        _global_embedder = EmbeddingService()
    return _global_embedder


def get_or_create_project_embedding(
    project_id: str,
    profile_text: str,
    profile_hash: str,
    db: Database,
) -> Tuple[np.ndarray, bool]:
    """
    Retrieves a cached project embedding if profile_hash matches,
    otherwise generates a local embedding with all-MiniLM-L6-v2 and caches it.
    Returns: (embedding_array, was_newly_generated)
    """
    embedder = get_embedder()
    model_name = embedder.model_name

    # 1. Check if an exact cached embedding exists for this content_hash
    cached_emb = db.get_cached_project_embedding(content_hash=profile_hash, model_name=model_name)
    if cached_emb is not None:
        # Also ensure it is mapped to current project_id
        db.save_project_embedding(project_id, model_name, cached_emb, profile_hash)
        return cached_emb, False

    # 2. Check if project already has embedding with same hash
    existing_emb = db.get_project_embedding(project_id, model_name)
    if existing_emb is not None:
        return existing_emb, False

    emb = embedder.embed(profile_text)
    db.save_project_embedding(project_id, model_name, emb, profile_hash)
    return emb, True


def unload_embedder() -> None:
    """Releases the global embedder instance and cleans up memory."""
    global _global_embedder
    if _global_embedder is not None:
        _global_embedder.unload()
        _global_embedder = None
