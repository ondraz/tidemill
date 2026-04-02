"""Pydantic v2 request/response models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from datetime import datetime


class MetricQueryRequest(BaseModel):
    params: dict[str, Any] = {}
    spec: QuerySpecSchema | None = None


class QuerySpecSchema(BaseModel):
    dimensions: list[str] = []
    filters: dict[str, Any] = {}
    granularity: str | None = None
    time_range: tuple[str, str] | None = None


class SourceCreate(BaseModel):
    type: str
    name: str
    config: dict[str, Any] = {}


class SourceResponse(BaseModel):
    id: str
    type: str
    name: str | None = None
    last_synced_at: datetime | None = None
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    database: bool
    kafka: bool


class MetricResponse(BaseModel):
    metric: str
    result: Any
