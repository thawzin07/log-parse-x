Map raw semiconductor tool log fields to canonical fields.

Canonical fields:
timestamp, tool_id, tool_family, vendor, chamber, wafer_id, lot_id, recipe, stage, status, severity, alarm_code, message.

Return strict JSON only:
{
  "canonical_mappings": {
    "canonical_field": ["raw_field_1", "raw_field_2"]
  },
  "metrics": {
    "metric_name": {
      "raw_fields": ["raw_field"],
      "unit": "unit or null"
    }
  },
  "unknown_fields": ["preserved_field"],
  "confidence": 0.0
}

Raw fields and sample values:
{sample}
