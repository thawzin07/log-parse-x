from __future__ import annotations

import csv
import io
import json
import re
import shlex
import string
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from dateutil import parser as date_parser

from app.models import SchemaProfile


CANONICAL_FIELDS = {
    "timestamp",
    "tool_id",
    "tool_family",
    "vendor",
    "chamber",
    "wafer_id",
    "lot_id",
    "recipe",
    "stage",
    "status",
    "severity",
    "alarm_code",
    "message",
}

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "timestamp": ("timestamp", "time", "event_time", "ts", "@timestamp", "date", "datetime"),
    "tool_id": ("tool_id", "tool", "eqp_id", "machineid", "machine_id", "tool_name", "TOOL"),
    "tool_family": ("tool_family", "module", "machine_type", "tooltype", "tool_type"),
    "vendor": ("vendor", "maker", "oem", "vendorname", "VendorName"),
    "chamber": ("chamber", "module_no", "station", "ch", "CH"),
    "wafer_id": ("wafer_id", "wafer", "substrate_id", "WAFER"),
    "lot_id": ("lot_id", "lot", "batch_id", "LOT"),
    "recipe": ("recipe", "rcp", "recipe_name", "process_recipe"),
    "stage": ("stage", "step", "phase", "process_step"),
    "status": ("status", "state", "event_status", "tool_state"),
    "severity": ("severity", "level", "priority", "sev"),
    "alarm_code": ("alarm", "alarm_code", "fault", "ALM"),
    "message": ("message", "msg", "description", "detail", "event", "text"),
}

METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "temperature_c": ("temp", "TEMP", "temperature", "temperature_c", "tempC", "chuck_temp_c", "chuckTemp"),
    "pressure_mtorr": ("pressure", "PRESS", "pressure_mtorr", "chamber_pressure"),
    "rf_power_w": ("rf_power", "RF", "power_w", "rfPower"),
    "gas_flow_sccm": ("gas_flow", "flow", "mfc_sccm", "gasFlow"),
    "spindle_rpm": ("rpm", "RPM", "spindle_speed", "rotation"),
    "dose_mj": ("dose", "dose_mj", "exposureDose", "DOSE"),
    "overlay_nm": ("overlay", "overlay_nm", "alignment_error_nm", "OVL"),
    "duration_ms": ("duration_ms", "elapsed_ms", "cycle_time", "runtime"),
    "helium_backside_pressure_torr": ("helium_backside_pressure_torr", "he_back_pressure", "backsideHe", "HeP"),
    "source_voltage_v": ("source_voltage_v", "sourceV", "src_voltage", "HV_SUPPLY"),
    "bias_voltage_v": ("bias_voltage_v", "biasV", "rf_bias_voltage", "BIAS"),
    "servo_load_pct": ("servo_load_pct", "servoLoad", "axis_load_pct", "motor_load"),
    "particle_count": ("particle_count", "particles", "particle_ct", "defect_particles"),
    "endpoint_confidence": ("endpoint_confidence", "endpointScore", "ept_conf", "endpoint_prob"),
    "leak_rate_pa_m3_s": ("leak_rate_pa_m3_s", "leak_rate", "vac_leak", "leakMetric"),
    "vibration_mm_s": ("vibration_mm_s", "vibration", "vibe_mm_s", "table_vibe"),
    "stage_position_mm": ("stage_position_mm", "stage_pos_mm", "axis_position", "STAGE_POS"),
    "laser_power_mw": ("laser_power_mw", "laserPower", "beam_power_mw", "LZR_PWR"),
    "humidity_rh": ("humidity_rh", "humidity", "RH", "ambient_rh"),
    "line_freq_hz": ("line_freq_hz", "lineFreq", "mains_hz", "facility_freq"),
    "wafer_orientation_deg": ("wafer_orientation_deg", "wafer_angle_deg", "notch_angle", "orientation"),
    "vision_alignment_score": ("vision_alignment_score", "align_score", "visionScore", "optical_align"),
}

SEMANTIC_EXTRAS = {
    "slot",
    "robot",
    "operator",
    "endpoint_signal",
    "recipe_revision",
    "firmware_build",
    "maintenance_due",
    "gas_ratio",
    "cassette_id",
}


@dataclass
class ParsedRecord:
    record_index: int
    raw_record: dict[str, Any]
    normalized: dict[str, Any]
    metrics: dict[str, Any]
    unknown_fields: dict[str, Any]


@dataclass
class ParseResult:
    detected_format: str
    records: list[ParsedRecord]
    confidence: float
    warnings: list[str] = field(default_factory=list)
    raw_text: str | None = None
    hex_preview: str | None = None
    observations: list[dict[str, Any]] = field(default_factory=list)


def parse_log_bytes(
    content: bytes,
    filename: str,
    schema_profiles: list[SchemaProfile] | None = None,
) -> ParseResult:
    schema_profiles = schema_profiles or []
    binary = _looks_binary(content)
    text = _decode_text(content)
    hex_preview = content[:512].hex(" ")

    if binary:
        printable = _extract_printable(content)
        raw = {
            "file_name": filename,
            "hex_preview": hex_preview,
            "printable_text": printable,
            "undecodable": True,
        }
        parsed = _normalize_records([raw], schema_profiles, detected_format="BINARY")
        parsed.hex_preview = hex_preview
        parsed.raw_text = printable
        parsed.warnings.append("Binary/proprietary content was handled with best-effort printable text and hex preview extraction.")
        return parsed

    detected_format = detect_format(text, filename)
    raw_records, warnings = records_from_text(text, detected_format)
    result = _normalize_records(raw_records, schema_profiles, detected_format)
    result.raw_text = text[:500_000]
    result.hex_preview = hex_preview if detected_format == "HEX" else None
    result.warnings.extend(warnings)
    return result


def detect_format(text: str, filename: str = "") -> str:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    stripped = text.strip()
    if not stripped:
        return "EMPTY"
    if suffix == "bin":
        return "HEX" if _looks_hex_text(stripped) else "BINARY"
    if _looks_hex_text(stripped):
        return "HEX"
    if suffix == "json" or stripped[:1] in {"[", "{"}:
        try:
            json.loads(stripped)
            return "JSON"
        except json.JSONDecodeError:
            pass
    if suffix == "xml" or stripped.startswith("<"):
        try:
            ET.fromstring(stripped)
            return "XML"
        except ET.ParseError:
            pass
    if suffix == "csv" or _looks_csv(stripped):
        return "CSV"
    lines = [line for line in stripped.splitlines() if line.strip()]
    if lines and sum(1 for line in lines[:20] if re.match(r"^<\d{1,3}>", line.strip())) >= max(1, len(lines[:20]) // 2):
        return "SYSLOG"
    if lines and _kv_ratio(lines[:20]) >= 0.45:
        return "KV"
    return "TEXT"


def records_from_text(text: str, detected_format: str) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    stripped = text.strip()
    if not stripped:
        return [], ["Uploaded file is empty."]

    try:
        if detected_format == "JSON":
            data = json.loads(stripped)
            if isinstance(data, list):
                return [_ensure_dict(item) for item in data], warnings
            return [_ensure_dict(data)], warnings
        if detected_format == "XML":
            return _parse_xml(stripped), warnings
        if detected_format == "CSV":
            return [dict(row) for row in csv.DictReader(io.StringIO(stripped))], warnings
        if detected_format == "SYSLOG":
            return [_parse_syslog_line(line) for line in stripped.splitlines() if line.strip()], warnings
        if detected_format == "KV":
            return [_parse_kv_line(line) for line in stripped.splitlines() if line.strip()], warnings
        if detected_format == "HEX":
            return [{"hex_text": stripped[:4000], "printable_text": _hex_to_printable(stripped)}], warnings
    except Exception as exc:  # noqa: BLE001 - parser must degrade gracefully for demos.
        warnings.append(f"{detected_format} parser failed, falling back to plain text: {exc}")

    return [_parse_text_line(line) for line in stripped.splitlines() if line.strip()], warnings


def _normalize_records(
    raw_records: list[dict[str, Any]],
    schema_profiles: list[SchemaProfile],
    detected_format: str,
) -> ParseResult:
    alias_map = _build_alias_map(schema_profiles, detected_format)
    records: list[ParsedRecord] = []
    unknown_counter: Counter[str] = Counter()
    unknown_samples: dict[str, list[Any]] = defaultdict(list)
    recognized_fields = 0
    total_fields = 0

    for idx, raw in enumerate(raw_records):
        normalized: dict[str, Any] = {}
        metrics: dict[str, Any] = {}
        unknown: dict[str, Any] = {}
        flattened = _flatten_record(raw)

        for raw_key, value in flattened.items():
            total_fields += 1
            canonical = alias_map.get(_key_id(raw_key))
            if canonical in CANONICAL_FIELDS:
                normalized[canonical] = _clean_canonical_value(canonical, value)
                recognized_fields += 1
            elif canonical:
                parsed_metric = _parse_metric_value(value)
                metrics[canonical] = parsed_metric if parsed_metric is not None else value
                recognized_fields += 1
            else:
                guessed_metric = _maybe_metric(raw_key, value)
                if guessed_metric is not None:
                    metrics[_metric_name(raw_key)] = guessed_metric
                    recognized_fields += 1
                elif _key_id(raw_key) in {_key_id(item) for item in SEMANTIC_EXTRAS}:
                    normalized[_metric_name(raw_key)] = value
                    recognized_fields += 1
                else:
                    unknown[raw_key] = value
                    unknown_counter[raw_key] += 1
                    if len(unknown_samples[raw_key]) < 5:
                        unknown_samples[raw_key].append(value)

        _derive_from_text(flattened, normalized, metrics)
        records.append(
            ParsedRecord(
                record_index=idx,
                raw_record=raw,
                normalized=normalized,
                metrics=metrics,
                unknown_fields=unknown,
            )
        )

    confidence = 0.4 if detected_format in {"TEXT", "HEX", "BINARY"} else 0.68
    if total_fields:
        confidence = min(0.98, confidence + 0.3 * (recognized_fields / total_fields))
    if not raw_records:
        confidence = 0.0

    observations = [
        {
            "field_name": field_name,
            "frequency": count,
            "sample_values": samples,
            "suggested_mapping": _suggest_mapping(field_name),
        }
        for field_name, count in unknown_counter.most_common(100)
        for samples in [unknown_samples[field_name]]
    ]

    warnings = []
    if observations:
        warnings.append(f"{len(observations)} unknown field(s) were preserved for manual schema mapping.")
    if detected_format in {"TEXT", "HEX", "BINARY"}:
        warnings.append(f"{detected_format} parsing is best-effort and may need a custom schema or LLM inference.")

    return ParseResult(
        detected_format=detected_format,
        records=records,
        confidence=round(confidence, 3),
        warnings=warnings,
        observations=observations,
    )


def _build_alias_map(schema_profiles: list[SchemaProfile], detected_format: str) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases + (canonical,):
            alias_map[_key_id(alias)] = canonical
    for canonical, aliases in METRIC_ALIASES.items():
        for alias in aliases + (canonical,):
            alias_map[_key_id(alias)] = canonical

    for profile in schema_profiles:
        if profile.format and profile.format.upper() not in {detected_format, "ANY", "*"}:
            continue
        field_mappings = profile.field_mappings or {}
        for canonical, aliases in field_mappings.items():
            values = aliases if isinstance(aliases, list) else [aliases]
            for alias in values + [canonical]:
                if alias:
                    alias_map[_key_id(str(alias))] = canonical
        if profile.timestamp_field:
            alias_map[_key_id(profile.timestamp_field)] = "timestamp"
        if profile.severity_field:
            alias_map[_key_id(profile.severity_field)] = "severity"
        if profile.message_field:
            alias_map[_key_id(profile.message_field)] = "message"
    return alias_map


def _flatten_record(record: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in record.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flattened.update(_flatten_record(value, path))
        else:
            flattened[path] = value
    return flattened


def _parse_xml(text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(text)
    candidates = list(root.findall(".//event")) or list(root)
    records: list[dict[str, Any]] = []
    for node in candidates:
        record: dict[str, Any] = {}
        if list(node):
            for child in list(node):
                record[child.tag] = child.text
        else:
            record[node.tag] = node.text
        record.update(node.attrib)
        if record:
            records.append(record)
    return records or [{root.tag: root.text, **root.attrib}]


def _parse_kv_line(line: str) -> dict[str, Any]:
    record: dict[str, Any] = {"line": line}
    try:
        parts = shlex.split(line)
    except ValueError:
        parts = line.split()
    for part in parts:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        record[key.strip()] = value.strip().strip('"')
    return record


def _parse_syslog_line(line: str) -> dict[str, Any]:
    record = {"line": line}
    match = re.match(r"^<(?P<pri>\d+)>(?P<body>.*)$", line.strip())
    body = line.strip()
    if match:
        record["priority"] = match.group("pri")
        body = match.group("body").strip()

    header = re.match(
        r"(?P<timestamp>\S+(?:\s+\S+)?)\s+(?P<tool_id>[A-Za-z]+-\d+|\S+)\s+(?P<stage>[^:]+):\s+(?P<rest>.*)",
        body,
    )
    if header:
        record.update(header.groupdict())
        record.pop("rest", None)
        rest = header.group("rest")
    else:
        rest = body
    record.update(_parse_kv_line(rest))
    if not record.get("message"):
        record["message"] = re.split(r"\s+\w+=", rest, maxsplit=1)[0].strip()
    return record


def _parse_text_line(line: str) -> dict[str, Any]:
    record = {"line": line}
    record.update(_parse_kv_line(line))
    severity = re.search(r"\[(INFO|NOTICE|WARN|WARNING|ERROR|CRITICAL|ALARM)\]", line, re.I)
    if severity:
        record["severity"] = severity.group(1)
    timestamp = re.match(r"^(\d{4}[-/]\d{2}[-/]\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)", line)
    if timestamp:
        record["timestamp"] = timestamp.group(1)
    tool = re.search(r"\b([A-Z]{3}-\d{2})\b", line)
    if tool:
        record["tool_id"] = tool.group(1)
    if "message" not in record:
        record["message"] = line[:1000]
    return record


def _derive_from_text(raw: dict[str, Any], normalized: dict[str, Any], metrics: dict[str, Any]) -> None:
    line = str(raw.get("line") or raw.get("message") or "")
    if not line:
        return
    if not normalized.get("tool_id"):
        match = re.search(r"\b([A-Z]{3}-\d{2})\b", line)
        if match:
            normalized["tool_id"] = match.group(1)
    if not normalized.get("severity"):
        match = re.search(r"\b(INFO|NOTICE|WARN|WARNING|ERROR|CRITICAL|ALARM)\b", line, re.I)
        if match:
            normalized["severity"] = _clean_canonical_value("severity", match.group(1))
    for key, value in re.findall(r"([A-Za-z_][\w.-]*)=([^\s|:]+)", line):
        metric = _maybe_metric(key, value)
        if metric is not None:
            metrics[_metric_name(key)] = metric


def _clean_canonical_value(canonical: str, value: Any) -> Any:
    if value in {"", None}:
        return None
    if canonical == "timestamp":
        return _parse_timestamp(value)
    if canonical in {"severity", "status"}:
        return str(value).upper().replace("WARNING", "WARN")
    return value


def _parse_timestamp(value: Any) -> datetime | None:
    if value in {"", None}:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, tz=timezone.utc)
    try:
        parsed = date_parser.parse(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, TypeError, OverflowError):
        return None


def _parse_metric_value(value: Any) -> Any:
    if value in {"", None}:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    match = re.search(r"-?\d+(?:\.\d+)?(?:e[+-]?\d+)?", str(value), re.I)
    if not match:
        return value
    number = float(match.group(0))
    return int(number) if number.is_integer() else number


def _maybe_metric(key: str, value: Any) -> Any | None:
    key_text = _key_id(key)
    metric_words = (
        "temp",
        "pressure",
        "power",
        "flow",
        "rpm",
        "dose",
        "overlay",
        "duration",
        "voltage",
        "particle",
        "confidence",
        "score",
        "humidity",
        "freq",
        "vibration",
        "position",
        "load",
        "count",
    )
    if any(word in key_text for word in metric_words):
        return _parse_metric_value(value)
    return None


def _metric_name(key: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(key)).strip("_").lower()
    return text or "metric"


def _suggest_mapping(field_name: str) -> str | None:
    key = _key_id(field_name)
    for canonical, aliases in FIELD_ALIASES.items():
        if key in {_key_id(item) for item in aliases} or canonical in key:
            return canonical
    for canonical, aliases in METRIC_ALIASES.items():
        if key in {_key_id(item) for item in aliases} or canonical.replace("_", "") in key:
            return canonical
    return None


def _key_id(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _ensure_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    return {"value": item}


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _looks_binary(content: bytes) -> bool:
    if not content:
        return False
    if b"\x00" in content[:2048]:
        return True
    sample = content[:4096]
    printable = set(bytes(string.printable, "ascii"))
    non_printable = sum(1 for byte in sample if byte not in printable)
    return non_printable / max(len(sample), 1) > 0.28


def _extract_printable(content: bytes) -> str:
    text = "".join(chr(byte) if 32 <= byte <= 126 or byte in {9, 10, 13} else " " for byte in content)
    chunks = re.findall(r"[ -~]{4,}", text)
    return "\n".join(chunks[:200])[:20_000]


def _hex_to_printable(text: str) -> str:
    compact = re.sub(r"[^0-9a-fA-F]", "", text)
    try:
        return _extract_printable(bytes.fromhex(compact[:8000]))
    except ValueError:
        return ""


def _looks_hex_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 32 or len(compact) % 2:
        return False
    if not re.fullmatch(r"[0-9a-fA-F]+", compact):
        return False
    return len(compact) / max(len(text), 1) > 0.55


def _looks_csv(text: str) -> bool:
    sample = "\n".join(text.splitlines()[:5])
    try:
        dialect = csv.Sniffer().sniff(sample)
        has_header = csv.Sniffer().has_header(sample)
        return dialect.delimiter in {",", "\t", ";"} and has_header
    except csv.Error:
        return False


def _kv_ratio(lines: list[str]) -> float:
    if not lines:
        return 0.0
    return sum(1 for line in lines if re.search(r"\b[\w@.-]+=", line)) / len(lines)
