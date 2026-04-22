from __future__ import annotations

import os
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.llm import LLMUnavailable, infer_schema
from app.models import Dataset, LogRecord, ParseRun, SchemaObservation, SchemaProfile
from app.parser import ParseResult, parse_log_bytes
from app.schemas import (
    AnalyticsOut,
    DatasetOut,
    InferSchemaRequest,
    InferSchemaResponse,
    LogRecordOut,
    RecordsPage,
    SchemaProfileIn,
    SchemaProfileOut,
)


app = FastAPI(title="LogParseX", version="0.1.0")

origins = [item.strip() for item in os.getenv("CORS_ORIGINS", "*").split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/datasets/upload", response_model=list[DatasetOut])
async def upload_datasets(
    files: Annotated[list[UploadFile], File()],
    db: Annotated[Session, Depends(get_db)],
) -> list[Dataset]:
    profiles = list(db.scalars(select(SchemaProfile)).all())
    created: list[Dataset] = []
    for upload in files:
        content = await upload.read()
        result = parse_log_bytes(content, upload.filename or "uploaded.log", profiles)
        dataset = _store_parse_result(db, upload, result)
        created.append(dataset)
    db.commit()
    for dataset in created:
        db.refresh(dataset)
    return created


@app.get("/api/datasets", response_model=list[DatasetOut])
def list_datasets(db: Annotated[Session, Depends(get_db)]) -> list[Dataset]:
    return list(db.scalars(select(Dataset).order_by(Dataset.created_at.desc())).all())


@app.get("/api/datasets/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: int, db: Annotated[Session, Depends(get_db)]) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


@app.get("/api/datasets/{dataset_id}/records", response_model=RecordsPage)
def get_records(
    dataset_id: int,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    tool_id: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    recipe: str | None = None,
    search: str | None = None,
) -> RecordsPage:
    if not db.get(Dataset, dataset_id):
        raise HTTPException(status_code=404, detail="Dataset not found")
    query = select(LogRecord).where(LogRecord.dataset_id == dataset_id)
    count_query = select(func.count()).select_from(LogRecord).where(LogRecord.dataset_id == dataset_id)

    filters = []
    if tool_id:
        filters.append(LogRecord.tool_id == tool_id)
    if status:
        filters.append(LogRecord.status == status.upper())
    if severity:
        filters.append(LogRecord.severity == severity.upper())
    if recipe:
        filters.append(LogRecord.recipe == recipe)
    if search:
        pattern = f"%{search}%"
        filters.append(
            or_(
                LogRecord.message.ilike(pattern),
                LogRecord.tool_id.ilike(pattern),
                LogRecord.alarm_code.ilike(pattern),
            )
        )
    for item in filters:
        query = query.where(item)
        count_query = count_query.where(item)

    total = db.scalar(count_query) or 0
    items = list(
        db.scalars(query.order_by(LogRecord.record_index.asc()).limit(limit).offset(offset)).all()
    )
    return RecordsPage(total=total, items=[LogRecordOut.model_validate(item) for item in items])


@app.get("/api/datasets/{dataset_id}/analytics", response_model=AnalyticsOut)
def get_analytics(dataset_id: int, db: Annotated[Session, Depends(get_db)]) -> AnalyticsOut:
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    rows = list(db.scalars(select(LogRecord).where(LogRecord.dataset_id == dataset_id)).all())
    severity = _count_field(rows, "severity")
    status = _count_field(rows, "status")
    alarms = _count_field(rows, "alarm_code", skip_values={None, "", "NONE"})
    tools = _count_field(rows, "tool_id")
    unknown = _count_unknown(rows)
    ranges = _metric_ranges(rows)
    timeline = _timeline(rows)
    totals = {
        "records": len(rows),
        "format": dataset.detected_format,
        "confidence": dataset.confidence,
        "unknownFieldCount": len(unknown),
        "toolCount": len([item for item in tools if item["name"] != "UNKNOWN"]),
    }
    return AnalyticsOut(
        totals=totals,
        severity_counts=severity,
        status_counts=status,
        alarm_counts=alarms,
        tool_counts=tools,
        metric_ranges=ranges,
        unknown_fields=unknown,
        timeline=timeline,
    )


@app.get("/api/schemas", response_model=list[SchemaProfileOut])
def list_schemas(db: Annotated[Session, Depends(get_db)]) -> list[SchemaProfile]:
    return list(db.scalars(select(SchemaProfile).order_by(SchemaProfile.name.asc())).all())


@app.post("/api/schemas", response_model=SchemaProfileOut)
def create_schema(
    payload: SchemaProfileIn,
    db: Annotated[Session, Depends(get_db)],
) -> SchemaProfile:
    profile = db.scalar(select(SchemaProfile).where(SchemaProfile.name == payload.name))
    if profile:
        for key, value in payload.model_dump().items():
            setattr(profile, key, value)
    else:
        profile = SchemaProfile(**payload.model_dump())
        db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@app.patch("/api/schemas/{schema_id}", response_model=SchemaProfileOut)
def update_schema(
    schema_id: int,
    payload: SchemaProfileIn,
    db: Annotated[Session, Depends(get_db)],
) -> SchemaProfile:
    profile = db.get(SchemaProfile, schema_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Schema profile not found")
    for key, value in payload.model_dump().items():
        setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


@app.delete("/api/schemas/{schema_id}")
def delete_schema(schema_id: int, db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    profile = db.get(SchemaProfile, schema_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Schema profile not found")
    db.delete(profile)
    db.commit()
    return {"status": "deleted"}


@app.post("/api/datasets/{dataset_id}/reparse", response_model=DatasetOut)
def reparse_dataset(dataset_id: int, db: Annotated[Session, Depends(get_db)]) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if not dataset.raw_text:
        raise HTTPException(status_code=400, detail="Dataset raw text is not available for reparsing")

    profiles = list(db.scalars(select(SchemaProfile)).all())
    result = parse_log_bytes(dataset.raw_text.encode("utf-8"), dataset.file_name, profiles)
    db.execute(delete(LogRecord).where(LogRecord.dataset_id == dataset_id))
    db.execute(delete(SchemaObservation).where(SchemaObservation.dataset_id == dataset_id))
    dataset.detected_format = result.detected_format
    dataset.record_count = len(result.records)
    dataset.confidence = result.confidence
    dataset.warnings = result.warnings
    dataset.hex_preview = result.hex_preview
    _store_records(db, dataset, result)
    db.commit()
    db.refresh(dataset)
    return dataset


@app.post("/api/llm/infer-schema", response_model=InferSchemaResponse)
async def infer_schema_endpoint(payload: InferSchemaRequest) -> InferSchemaResponse:
    try:
        provider, result = await infer_schema(payload.sample, payload.detected_format)
    except (LLMUnavailable, Exception) as exc:  # noqa: BLE001 - return useful UI feedback.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return InferSchemaResponse(provider=provider, result=result)


def _store_parse_result(db: Session, upload: UploadFile, result: ParseResult) -> Dataset:
    dataset = Dataset(
        file_name=upload.filename or "uploaded.log",
        content_type=upload.content_type,
        detected_format=result.detected_format,
        status="parsed",
        record_count=len(result.records),
        confidence=result.confidence,
        warnings=result.warnings,
        raw_text=result.raw_text,
        hex_preview=result.hex_preview,
    )
    db.add(dataset)
    db.flush()
    _store_records(db, dataset, result)
    return dataset


def _store_records(db: Session, dataset: Dataset, result: ParseResult) -> None:
    db.add(
        ParseRun(
            dataset_id=dataset.id,
            parser_method=f"deterministic:{result.detected_format}",
            confidence=result.confidence,
            warnings=result.warnings,
        )
    )
    for record in result.records:
        normalized = record.normalized
        db.add(
            LogRecord(
                dataset_id=dataset.id,
                record_index=record.record_index,
                timestamp=normalized.get("timestamp"),
                tool_id=normalized.get("tool_id"),
                tool_family=normalized.get("tool_family"),
                vendor=normalized.get("vendor"),
                chamber=normalized.get("chamber"),
                wafer_id=normalized.get("wafer_id"),
                lot_id=normalized.get("lot_id"),
                recipe=normalized.get("recipe"),
                stage=normalized.get("stage"),
                status=normalized.get("status"),
                severity=normalized.get("severity"),
                alarm_code=normalized.get("alarm_code"),
                message=normalized.get("message"),
                raw_record=record.raw_record,
                normalized=_json_safe(normalized),
                metrics=_json_safe(record.metrics),
                unknown_fields=record.unknown_fields,
            )
        )
    for observation in result.observations:
        db.add(
            SchemaObservation(
                dataset_id=dataset.id,
                field_name=observation["field_name"],
                sample_values=observation["sample_values"],
                frequency=observation["frequency"],
                suggested_mapping=observation["suggested_mapping"],
            )
        )


def _json_safe(payload: dict) -> dict:
    safe = {}
    for key, value in payload.items():
        if hasattr(value, "isoformat"):
            safe[key] = value.isoformat()
        else:
            safe[key] = value
    return safe


def _count_field(rows: list[LogRecord], field: str, skip_values: set | None = None) -> list[dict]:
    skip_values = skip_values or {None, ""}
    counts: dict[str, int] = {}
    for row in rows:
        value = getattr(row, field)
        if value in skip_values:
            value = "UNKNOWN"
        counts[str(value)] = counts.get(str(value), 0) + 1
    return [{"name": key, "value": value} for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)]


def _count_unknown(rows: list[LogRecord]) -> list[dict]:
    counts: dict[str, int] = {}
    samples: dict[str, list] = {}
    for row in rows:
        for key, value in (row.unknown_fields or {}).items():
            counts[key] = counts.get(key, 0) + 1
            samples.setdefault(key, [])
            if len(samples[key]) < 3:
                samples[key].append(value)
    return [
        {"name": key, "count": counts[key], "samples": samples[key]}
        for key in sorted(counts, key=counts.get, reverse=True)[:30]
    ]


def _metric_ranges(rows: list[LogRecord]) -> list[dict]:
    values: dict[str, list[float]] = {}
    for row in rows:
        for key, value in (row.metrics or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.setdefault(key, []).append(float(value))
    return [
        {
            "name": key,
            "min": round(min(items), 4),
            "max": round(max(items), 4),
            "avg": round(sum(items) / len(items), 4),
        }
        for key, items in sorted(values.items())[:40]
        if items
    ]


def _timeline(rows: list[LogRecord]) -> list[dict]:
    buckets: dict[str, int] = {}
    for row in rows:
        if row.timestamp:
            key = row.timestamp.isoformat()[:13] + ":00"
        else:
            key = f"record-{row.record_index // 25}"
        buckets[key] = buckets.get(key, 0) + 1
    return [{"time": key, "records": value} for key, value in sorted(buckets.items())]
