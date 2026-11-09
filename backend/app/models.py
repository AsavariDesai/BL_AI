"""Pydantic models shared across the extraction pipeline and API."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Source = Literal["rules", "kie", "user"]


class FieldValue(BaseModel):
    key: str
    value: Optional[str] = None
    confidence: float = 0.0            # 0.0 - 1.0
    page: Optional[int] = None         # 1-based page the value was found on
    bbox: Optional[tuple[float, float, float, float]] = None  # x0,y0,x1,y1 in PDF points
    source: Source = "rules"


class ExtractionResult(BaseModel):
    doc_id: str
    file_name: str
    engine: str
    detected_format: Optional[str] = None
    has_scanned_pages: bool = False
    fields: list[FieldValue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def as_map(self) -> dict[str, Optional[str]]:
        return {f.key: f.value for f in self.fields}

    def get(self, key: str) -> Optional[FieldValue]:
        return next((f for f in self.fields if f.key == key), None)
