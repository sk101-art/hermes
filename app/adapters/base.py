from abc import ABC, abstractmethod
from typing import Any, Dict, List
from app.models.schemas import Event


class SourceAdapter(ABC):
    """Abstract base class for all data source adapters."""

    @property
    def source_name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def fetch(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch raw items from the data source."""
        pass

    @abstractmethod
    def normalize(self, raw_item: Dict[str, Any]) -> Event:
        """Convert a raw data item into a normalized Event model."""
        pass

    def checkpoint(self) -> Dict[str, Any]:
        """Optional checkpointing state for incremental fetching."""
        return {}
