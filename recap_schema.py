from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PRIORITY_SUM_TOLERANCE = 0.02


class RecapImage(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    page: int = Field(ge=1)
    priority: float = Field(gt=0.0, le=1.0)

    @field_validator("priority")
    @classmethod
    def priority_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("priority must be finite")
        return value


class RecapSegment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    speech: str = Field(min_length=1)
    images: list[RecapImage] = Field(min_length=1)

    @field_validator("speech")
    @classmethod
    def speech_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("speech must not be blank")
        return stripped

    @model_validator(mode="after")
    def validate_images(self) -> "RecapSegment":
        pages = [image.page for image in self.images]
        if len(pages) != len(set(pages)):
            raise ValueError("image pages must be unique within a segment")
        total = sum(image.priority for image in self.images)
        if not math.isfinite(total) or round(abs(total - 1.0), 10) > PRIORITY_SUM_TOLERANCE:
            raise ValueError("image priorities must sum to 1.0")
        return self


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def parse_recap_data(value: Any, *, max_page: int | None = None) -> list[RecapSegment]:
    if not isinstance(value, list) or not value:
        raise ValueError("recap must be a non-empty list")
    segments = [RecapSegment.model_validate(item) for item in value]
    if max_page is not None:
        if max_page < 1:
            raise ValueError("max_page must be positive")
        for segment in segments:
            for image in segment.images:
                if image.page > max_page:
                    raise ValueError(f"page {image.page} exceeds available page count {max_page}")
    return segments


def load_recap(path: str | Path, *, max_page: int | None = None) -> list[RecapSegment]:
    recap_path = Path(path)
    raw = recap_path.read_text(encoding="utf-8")
    value = json.loads(raw, parse_constant=_reject_non_finite)
    return parse_recap_data(value, max_page=max_page)


def load_recap_dicts(path: str | Path, *, max_page: int | None = None) -> list[dict[str, Any]]:
    return [segment.model_dump(mode="json") for segment in load_recap(path, max_page=max_page)]


def validate_recap_file(path: str | Path, *, max_page: int | None = None) -> bool:
    try:
        load_recap(path, max_page=max_page)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return True
