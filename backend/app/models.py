from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

JSON_FIELD = JSON().with_variant(JSONB, "postgresql")


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120))
    detected_format: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="parsed", nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON_FIELD, default=list, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    hex_preview: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    records: Mapped[list["LogRecord"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )
    parse_runs: Mapped[list["ParseRun"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class ParseRun(Base):
    __tablename__ = "parse_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    parser_method: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON_FIELD, default=list, nullable=False)
    llm_provider: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped[Dataset] = relationship(back_populates="parse_runs")


class LogRecord(Base):
    __tablename__ = "log_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    record_index: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    tool_id: Mapped[str | None] = mapped_column(String(120), index=True)
    tool_family: Mapped[str | None] = mapped_column(String(120), index=True)
    vendor: Mapped[str | None] = mapped_column(String(120))
    chamber: Mapped[str | None] = mapped_column(String(120))
    wafer_id: Mapped[str | None] = mapped_column(String(120))
    lot_id: Mapped[str | None] = mapped_column(String(120))
    recipe: Mapped[str | None] = mapped_column(String(160), index=True)
    stage: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str | None] = mapped_column(String(80), index=True)
    severity: Mapped[str | None] = mapped_column(String(80), index=True)
    alarm_code: Mapped[str | None] = mapped_column(String(120), index=True)
    message: Mapped[str | None] = mapped_column(Text)
    raw_record: Mapped[dict] = mapped_column(JSON_FIELD, default=dict, nullable=False)
    normalized: Mapped[dict] = mapped_column(JSON_FIELD, default=dict, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON_FIELD, default=dict, nullable=False)
    unknown_fields: Mapped[dict] = mapped_column(JSON_FIELD, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped[Dataset] = relationship(back_populates="records")


class SchemaProfile(Base):
    __tablename__ = "schema_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    format: Mapped[str | None] = mapped_column(String(40), index=True)
    known_keys: Mapped[list[str]] = mapped_column(JSON_FIELD, default=list, nullable=False)
    field_mappings: Mapped[dict] = mapped_column(JSON_FIELD, default=dict, nullable=False)
    timestamp_field: Mapped[str | None] = mapped_column(String(160))
    severity_field: Mapped[str | None] = mapped_column(String(160))
    message_field: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SchemaObservation(Base):
    __tablename__ = "schema_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    field_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    sample_values: Mapped[list] = mapped_column(JSON_FIELD, default=list, nullable=False)
    frequency: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    suggested_mapping: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
