"""Common extractor interface."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import ExtractionResult


class Extractor(ABC):
    name: str = "base"

    @abstractmethod
    def extract(
        self,
        pdf_path: str,
        *,
        doc_id: str,
        doc_type: str = "bill_of_lading",
        examples: list[dict] | None = None,
    ) -> ExtractionResult:
        """Read the BL at ``pdf_path`` and return one FieldValue per canonical key.

        ``examples`` is an optional list of past human corrections for similar
        BLs, used by the learning loop to steer the model.
        """
        raise NotImplementedError
