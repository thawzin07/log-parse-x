# LogParseX

AI-powered smart tool log parser prototype for the Micron @ AISG National AI Student Challenge.

LogParseX ingests synthetic semiconductor equipment logs, detects their format, parses records, normalizes known fields, preserves unknown schema drift, stores everything in PostgreSQL, and presents a dashboard for engineering analysis.

## What It Demonstrates

- Log file ingestion through a browser UI.
- Pattern recognition for `JSON`, `XML`, `CSV`, `KV`, `SYSLOG`, plain text, and binary/hex-like logs.
- Tokenizing and normalization into canonical fields such as timestamp, tool ID, recipe, status, severity, alarm code, and sensor metrics.
- Raw record, unknown field, and metric preservation in PostgreSQL `JSONB`.
- Query and dashboard analytics for parsed equipment records.
- Custom schema profiles so users can add known keys and aliases without changing code.
- Optional LLM schema inference through Ollama, OpenAI, or Gemini.

## Architecture

```text
Raw log upload
  -> format detection
  -> deterministic parser
  -> schema profile matching
  -> optional LLM schema inference
  -> canonical normalization
  -> PostgreSQL storage
  -> dashboard, query, analytics, schema management
```

Services:

- `frontend`: React + TypeScript + Vite dashboard.
- `backend`: FastAPI parser and API service.
- `postgres`: PostgreSQL database.
- `ollama`: optional local LLM service behind the Docker Compose `llm` profile.

## Quick Start

```bash
cp .env.example .env
docker compose up --build
```

`docker compose up --build` already reuses existing containers when their configuration still matches. If the containers do not exist, Compose creates them. If an image or service configuration changed, Compose recreates only what it needs.

Open:

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs
- PostgreSQL: `localhost:5432`, database `logparsex`, user `logparsex`, password `logparsex`

## Container Lifecycle

Docker Compose has fixed behavior for `down`: it stops and removes the Compose containers and network. This project cannot override that built-in command safely from `docker-compose.yml`.

Use these commands for the behavior you asked for:

```bash
# Create containers if missing, otherwise reuse existing containers where possible.
docker compose up --build

# Stop containers without deleting them. They will be reused by the next up.
docker compose stop

# Same safe stop behavior through the project Makefile.
make stop

# Project helper for up --build.
make up
```

The included `Makefile` intentionally maps `make down` to `docker compose stop` so demos can use a familiar command name without deleting containers. If you run Docker's real `docker compose down`, Docker will remove the containers, but the named PostgreSQL volume remains unless you add `-v`.

## Environment Variables

All variables used by the app and Docker Compose are listed in `.env.example`.

| Variable | Default | Used by | Purpose |
| --- | --- | --- | --- |
| `PROJECT_NAME` | `logparsex` | Docker Compose | Compose project name and generated container/network prefixes. |
| `FRONTEND_PORT` | `5173` | Docker Compose | Host port for the React dashboard. |
| `BACKEND_PORT` | `8000` | Docker Compose | Host port for the FastAPI backend. |
| `POSTGRES_PORT` | `5432` | Docker Compose | Host port for PostgreSQL. |
| `OLLAMA_PORT` | `11434` | Docker Compose | Host port for optional Ollama. |
| `POSTGRES_DB` | `logparsex` | PostgreSQL | Database name created by the container. |
| `POSTGRES_USER` | `logparsex` | PostgreSQL | Database username. |
| `POSTGRES_PASSWORD` | `logparsex` | PostgreSQL | Database password. |
| `DATABASE_URL` | `postgresql+psycopg2://logparsex:logparsex@postgres:5432/logparsex` | Backend | SQLAlchemy connection string used inside Docker. |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Backend | Browser origins allowed to call the API. |
| `VITE_API_URL` | `http://localhost:8000` | Frontend | API base URL used by the dashboard in the browser. |
| `LLM_PROVIDER` | `openai` | Backend | LLM provider for schema inference: `openai`, `ollama`, `gemini`, or `none`. |
| `OLLAMA_URL` | `http://ollama:11434` | Backend | Internal Ollama URL when running through Compose. |
| `OLLAMA_MODEL` | `llama3.1:8b` | Backend | Ollama model name. |
| `OPENAI_API_KEY` | empty | Backend | OpenAI API key when `LLM_PROVIDER=openai`. |
| `OPENAI_MODEL` | `gpt-5.4-mini` | Backend | OpenAI model for schema inference. |
| `GEMINI_API_KEY` | empty | Backend | Gemini API key when `LLM_PROVIDER=gemini`. |
| `GEMINI_MODEL` | `gemini-1.5-flash` | Backend | Gemini model for schema inference. |

For local Docker usage, the default `DATABASE_URL` should keep `postgres` as the host because that is the Compose service name. If running the backend outside Docker, change the host to `localhost`.

## Optional Ollama Setup

Start the optional Ollama container:

```bash
docker compose --profile llm up --build
```

Pull a model into the Ollama container:

```bash
docker compose exec ollama ollama pull llama3.1:8b
```

The backend defaults to OpenAI:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.4-mini
```

Ollama can still be used for local LLM inference:

```env
LLM_PROVIDER=ollama
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=llama3.1:8b
```

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-1.5-flash
```

## Generate Synthetic Logs With LogForge

Clone the referenced generator outside this project:

```bash
git clone https://github.com/zayyartun-cgm/LogForge.git
cd LogForge
```

Generate representative samples:

```bash
./logforge --output JSON --count 50 --destination sample.json
./logforge --output XML --count 50 --destination sample.xml
./logforge --output CSV --count 50 --destination sample.csv
./logforge --output TEXT --count 50 --destination sample.log
./logforge --output KV --count 50 --destination sample.kv
./logforge --output SYSLOG --count 50 --destination sample.syslog
```

Generate schema-drift samples:

```bash
./logforge --output JSON --count 80 --future-fields --destination drift.json
./logforge --output XML --count 80 --schema-drift --destination drift.xml
./logforge --output CSV --count 80 --future-fields --destination drift.csv
```

Upload those files in the LogParseX UI.

## Demo Workflow

1. Start the stack with `docker compose up --build`.
2. Generate LogForge samples.
3. Upload one or more files from the dashboard.
4. Select a dataset from the left panel.
5. Review format, confidence, warnings, records, charts, metric ranges, and unknown fields.
6. Open the `Schema mappings` page to add, inspect, modify, or delete custom schema profiles.
7. Click `Reparse` to apply the new mapping without changing the database structure.

## Custom Schema Profiles

Schema profiles let users adapt to changed machine logs.

Example mapping:

```json
{
  "timestamp": ["event_time", "time", "ts"],
  "tool_id": ["eqp_id", "machineId", "tool"],
  "severity": ["level", "sev"],
  "message": ["detail", "msg"],
  "temperature_c": ["tempC", "temperature"]
}
```

Mappings can target canonical fields or flexible metrics. Unknown fields remain stored in `unknown_fields` until a user maps them.

Manual adaptation options:

- Use the schema form to write mappings directly as JSON.
- Use the Unknown Fields panel to add a field into the mapping JSON with one click.
- Use the `Schema mappings` page to view every custom mapping, edit it, or delete it.
- Save the same schema name again to update it; the backend treats `POST /api/schemas` as create-or-update by name for faster iteration.
- Click `Reparse` after saving mappings. The system reuses the stored raw text and rewrites normalized records without changing the database schema.
- Nested JSON fields are flattened into dotted paths for matching, while the original raw object remains preserved.

Examples:

```json
{
  "timestamp": ["event.header.time", "event_time"],
  "tool_id": ["equipment.id", "eqp_id"],
  "chuck_temp_c": ["future_payload.esc.temp"],
  "endpoint_confidence": ["endpointScore"]
}
```

## Backend API

- `POST /api/datasets/upload`: upload log files.
- `GET /api/datasets`: list uploaded datasets.
- `GET /api/datasets/{id}`: get dataset details.
- `GET /api/datasets/{id}/records`: query parsed records.
- `GET /api/datasets/{id}/analytics`: get dashboard aggregates.
- `GET /api/schemas`: list custom schema profiles.
- `POST /api/schemas`: create schema profile.
- `PATCH /api/schemas/{id}`: update schema profile.
- `DELETE /api/schemas/{id}`: delete schema profile.
- `POST /api/datasets/{id}/reparse`: reparse a dataset using updated schema mappings.
- `POST /api/llm/infer-schema`: infer a schema from a sample payload.

## Database Tables

- `datasets`: uploaded file metadata, detected format, parse status, record count.
- `parse_runs`: parser method, confidence, warnings, provider metadata.
- `log_records`: canonical columns plus `raw_record`, `normalized`, `metrics`, and `unknown_fields` as JSONB.
- `schema_profiles`: user-created known log type definitions.
- `schema_observations`: detected unknown fields and suggested mappings.

## Binary And Hex Logs

True vendor-proprietary binary decoding is not possible without vendor tools. This prototype detects binary-like content, stores a hex preview, extracts printable strings, and keeps undecodable sections flagged for review. Hex-like text files are treated similarly and can be passed to the LLM inference endpoint for best-effort schema hints.

## Cases Considered

- Structured logs: JSON, XML, and CSV are parsed with standard parsers first because these formats have explicit record and field boundaries.
- Semi-structured logs: key-value and syslog-style files are tokenized line by line because vendors often append arbitrary telemetry fields without changing the whole format.
- Unstructured text logs: text is parsed with timestamp, severity, tool ID, and key-value extraction heuristics because these logs usually contain mixed human messages and machine parameters.
- Schema drift: unknown fields are never discarded. They are stored in `unknown_fields`, summarized in analytics, and can be promoted into a schema profile.
- Alias drift: common semiconductor log aliases are mapped automatically, for example `eqp_id`, `machineId`, `tool`, `tempC`, `PRESS`, `sev`, and `event_time`.
- Nested payloads: nested JSON dictionaries are flattened into dotted paths for mapping, which lets users handle payloads such as `event.header.time` or `sensor.chuck.temp` without code changes.
- Numeric values with units: values such as `42 C`, `0.5 mTorr`, `72 mJ/cm2`, and `9.5 nm` are converted into numeric metrics where possible.
- Binary/proprietary logs: the app performs safe best-effort extraction only. It stores a hex preview and printable strings because true proprietary decoding normally requires vendor tools.
- LLM fallback: deterministic parsing is always attempted first. LLM inference is optional because local/offline demos should still work without API keys.
- Database flexibility: canonical columns support dashboard queries, while JSONB columns preserve raw records, metrics, normalized extras, and unknown fields for future adaptation.

## Development Commands

Backend only:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend only:

```bash
cd frontend
npm install
npm run dev
```

## Notes For Presentation

The main design decision is to separate stable canonical fields from flexible raw/unknown fields. Engineers can query common fields immediately, while `JSONB` preserves schema drift and lets the UI or LLM suggest new mappings. This keeps the system adaptable when machine vendors change log keys, firmware versions, or optional telemetry fields.
