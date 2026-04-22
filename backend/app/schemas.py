from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_name: str
    content_type: str | None
    detected_format: str
    status: str
    record_count: int
    confidence: float
    warnings: list[str]
    hex_preview: str | None
    created_at: datetime


class LogRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dataset_id: int
    record_index: int
    timestamp: datetime | None
    tool_id: str | None
    tool_family: str | None
    vendor: str | None
    chamber: str | None
    wafer_id: str | None
    lot_id: str | None
    recipe: str | None
    stage: str | None
    status: str | None
    severity: str | None
    alarm_code: str | None
    message: str | None
    raw_record: dict[str, Any]
    normalized: dict[str, Any]
    metrics: dict[str, Any]
    unknown_fields: dict[str, Any]


class RecordsPage(BaseModel):
    total: int
    items: list[LogRecordOut]


class SchemaProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    format: str | None = None
    known_keys: list[str] = Field(default_factory=list)
    field_mappings: dict[str, list[str] | str] = Field(default_factory=dict)
    timestamp_field: str | None = None
    severity_field: str | None = None
    message_field: str | None = None


class SchemaProfileOut(SchemaProfileIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class InferSchemaRequest(BaseModel):
    sample: str
    detected_format: str | None = None


class InferSchemaResponse(BaseModel):
    provider: str
    result: dict[str, Any]


class AnalyticsOut(BaseModel):
    totals: dict[str, Any]
    severity_counts: list[dict[str, Any]]
    status_counts: list[dict[str, Any]]
    alarm_counts: list[dict[str, Any]]
    tool_counts: list[dict[str, Any]]
    metric_ranges: list[dict[str, Any]]
    unknown_fields: list[dict[str, Any]]
    timeline: list[dict[str, Any]]
