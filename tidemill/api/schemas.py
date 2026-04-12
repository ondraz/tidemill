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


# ── Auth & API Keys ─────────────────────────────────────────────────────


class UserResponse(BaseModel):
    id: str
    email: str
    name: str | None = None
    avatar_url: str | None = None


class ApiKeyCreate(BaseModel):
    name: str


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiKeyCreated(ApiKeyResponse):
    key: str


# ── Dashboards & Charts ─────────────────────────────────────────────────


class DashboardCreate(BaseModel):
    name: str
    description: str | None = None


class DashboardUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class SectionCreate(BaseModel):
    title: str
    position: int = 0


class SectionUpdate(BaseModel):
    title: str | None = None
    position: int | None = None


class SavedChartCreate(BaseModel):
    name: str
    config: dict[str, Any]


class SavedChartUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None


class DashboardChartAdd(BaseModel):
    saved_chart_id: str
    section_id: str
    position: int = 0
