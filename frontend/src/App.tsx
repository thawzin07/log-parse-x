import { FormEvent, useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BarChart3,
  Database,
  FileUp,
  LayoutDashboard,
  Pencil,
  PlusCircle,
  RefreshCw,
  Search,
  Settings2,
  Trash2
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

type Dataset = {
  id: number;
  file_name: string;
  content_type?: string | null;
  detected_format: string;
  status: string;
  record_count: number;
  confidence: number;
  warnings: string[];
  hex_preview?: string | null;
  created_at: string;
};

type LogRecord = {
  id: number;
  record_index: number;
  timestamp?: string | null;
  tool_id?: string | null;
  tool_family?: string | null;
  vendor?: string | null;
  chamber?: string | null;
  wafer_id?: string | null;
  lot_id?: string | null;
  recipe?: string | null;
  stage?: string | null;
  status?: string | null;
  severity?: string | null;
  alarm_code?: string | null;
  message?: string | null;
  metrics: Record<string, unknown>;
  unknown_fields: Record<string, unknown>;
  raw_record: Record<string, unknown>;
};

type RecordsPage = {
  total: number;
  items: LogRecord[];
};

type Analytics = {
  totals: Record<string, unknown>;
  severity_counts: { name: string; value: number }[];
  status_counts: { name: string; value: number }[];
  alarm_counts: { name: string; value: number }[];
  tool_counts: { name: string; value: number }[];
  metric_ranges: { name: string; min: number; max: number; avg: number }[];
  unknown_fields: { name: string; count: number; samples: unknown[] }[];
  timeline: { time: string; records: number }[];
};

type SchemaProfile = {
  id: number;
  name: string;
  description?: string | null;
  format?: string | null;
  known_keys: string[];
  field_mappings: Record<string, string[] | string>;
  timestamp_field?: string | null;
  severity_field?: string | null;
  message_field?: string | null;
};

type Page = "dashboard" | "schemas";

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, options);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

const defaultMapping = {
  timestamp: ["event_time", "time"],
  tool_id: ["eqp_id", "machineId"],
  severity: ["level", "sev"],
  message: ["detail", "msg"],
  temperature_c: ["tempC", "temperature"]
};

export default function App() {
  const queryClient = useQueryClient();
  const [activePage, setActivePage] = useState<Page>("dashboard");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [editingSchemaId, setEditingSchemaId] = useState<number | null>(null);
  const [schemaJson, setSchemaJson] = useState(JSON.stringify(defaultMapping, null, 2));
  const [schemaName, setSchemaName] = useState("Custom XML Tool");
  const [schemaFormat, setSchemaFormat] = useState("XML");
  const [knownKeys, setKnownKeys] = useState("event_time, eqp_id, level, msg, tempC");
  const [schemaDescription, setSchemaDescription] = useState("");
  const [schemaMessage, setSchemaMessage] = useState<string | null>(null);
  const [fieldTargets, setFieldTargets] = useState<Record<string, string>>({});

  const datasets = useQuery({
    queryKey: ["datasets"],
    queryFn: () => api<Dataset[]>("/api/datasets"),
    refetchInterval: 5000
  });

  const activeDataset = useMemo(() => {
    const items = datasets.data ?? [];
    return items.find((item) => item.id === selectedId) ?? items[0] ?? null;
  }, [datasets.data, selectedId]);

  const analytics = useQuery({
    queryKey: ["analytics", activeDataset?.id],
    enabled: Boolean(activeDataset?.id),
    queryFn: () => api<Analytics>(`/api/datasets/${activeDataset!.id}/analytics`)
  });

  const records = useQuery({
    queryKey: ["records", activeDataset?.id, search],
    enabled: Boolean(activeDataset?.id),
    queryFn: () => {
      const params = new URLSearchParams({ limit: "80" });
      if (search) params.set("search", search);
      return api<RecordsPage>(`/api/datasets/${activeDataset!.id}/records?${params}`);
    }
  });

  const schemas = useQuery({
    queryKey: ["schemas"],
    queryFn: () => api<SchemaProfile[]>("/api/schemas")
  });

  const uploadMutation = useMutation({
    mutationFn: async (files: FileList) => {
      const form = new FormData();
      Array.from(files).forEach((file) => form.append("files", file));
      return api<Dataset[]>("/api/datasets/upload", { method: "POST", body: form });
    },
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["datasets"] });
      setSelectedId(created[0]?.id ?? null);
      setActivePage("dashboard");
    }
  });

  const schemaMutation = useMutation({
    mutationFn: async () => {
      const payload = buildSchemaPayload(
        schemaName,
        schemaDescription,
        schemaFormat,
        knownKeys,
        schemaJson
      );
      const path = editingSchemaId ? `/api/schemas/${editingSchemaId}` : "/api/schemas";
      return api<SchemaProfile>(path, {
        method: editingSchemaId ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    },
    onSuccess: (schema) => {
      setEditingSchemaId(schema.id);
      setSchemaMessage("Schema profile saved.");
      queryClient.invalidateQueries({ queryKey: ["schemas"] });
    },
    onError: (error) => setSchemaMessage(error instanceof Error ? error.message : "Schema save failed.")
  });

  const deleteSchemaMutation = useMutation({
    mutationFn: async (schemaId: number) =>
      api<{ status: string }>(`/api/schemas/${schemaId}`, { method: "DELETE" }),
    onSuccess: (_, schemaId) => {
      if (editingSchemaId === schemaId) resetSchemaForm();
      setSchemaMessage("Schema profile deleted.");
      queryClient.invalidateQueries({ queryKey: ["schemas"] });
    },
    onError: (error) => setSchemaMessage(error instanceof Error ? error.message : "Schema delete failed.")
  });

  const reparseMutation = useMutation({
    mutationFn: async (datasetId: number) =>
      api<Dataset>(`/api/datasets/${datasetId}/reparse`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["datasets"] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
      queryClient.invalidateQueries({ queryKey: ["records"] });
    }
  });

  const handleUpload = (event: FormEvent<HTMLInputElement>) => {
    const files = event.currentTarget.files;
    if (files?.length) uploadMutation.mutate(files);
  };

  const resetSchemaForm = () => {
    setEditingSchemaId(null);
    setSchemaName("Custom XML Tool");
    setSchemaFormat("XML");
    setKnownKeys("event_time, eqp_id, level, msg, tempC");
    setSchemaDescription("");
    setSchemaJson(JSON.stringify(defaultMapping, null, 2));
    setSchemaMessage(null);
  };

  const editSchema = (schema: SchemaProfile) => {
    setEditingSchemaId(schema.id);
    setSchemaName(schema.name);
    setSchemaFormat(schema.format ?? "ANY");
    setKnownKeys(schema.known_keys.join(", "));
    setSchemaDescription(schema.description ?? "");
    setSchemaJson(JSON.stringify(schema.field_mappings ?? {}, null, 2));
    setSchemaMessage(`Editing ${schema.name}.`);
    setActivePage("schemas");
  };

  const addUnknownFieldMapping = (fieldName: string) => {
    const target = (fieldTargets[fieldName] || suggestTarget(fieldName)).trim();
    if (!target) {
      setSchemaMessage("Enter a canonical field or metric name before adding the mapping.");
      return;
    }
    try {
      const parsed = JSON.parse(schemaJson) as Record<string, string[] | string>;
      const existing = parsed[target];
      const aliases = Array.isArray(existing) ? existing : existing ? [existing] : [];
      parsed[target] = Array.from(new Set([...aliases, fieldName]));
      setSchemaJson(JSON.stringify(parsed, null, 2));
      setKnownKeys(mergeCsvValue(knownKeys, fieldName));
      setSchemaFormat(activeDataset?.detected_format ?? schemaFormat);
      setSchemaMessage(`${fieldName} will map to ${target}. Save the profile, then reparse.`);
      setActivePage("schemas");
    } catch {
      setSchemaMessage("Schema mapping JSON is invalid. Fix it before adding field mappings.");
    }
  };

  return (
    <main className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Micron Smart Tool Log Parser Prototype</p>
          <h1>LogParseX</h1>
          <p className="subhead">
            Ingest diverse equipment logs, normalize them into queryable records, and inspect schema drift from one dashboard.
          </p>
        </div>
        <div className="topActions">
          <nav className="navTabs" aria-label="Primary">
            <button
              className={`tabButton ${activePage === "dashboard" ? "active" : ""}`}
              onClick={() => setActivePage("dashboard")}
            >
              <LayoutDashboard size={18} />
              Dashboard
            </button>
            <button
              className={`tabButton ${activePage === "schemas" ? "active" : ""}`}
              onClick={() => setActivePage("schemas")}
            >
              <Settings2 size={18} />
              Schema mappings
            </button>
          </nav>
          <label className="uploadButton">
            <FileUp size={20} />
            <span>{uploadMutation.isPending ? "Uploading..." : "Upload logs"}</span>
            <input
              type="file"
              multiple
              onChange={handleUpload}
              accept=".json,.xml,.csv,.txt,.log,.kv,.syslog,.bin"
            />
          </label>
        </div>
      </header>

      {activePage === "dashboard" ? (
        <DashboardPage
          activeDataset={activeDataset}
          datasets={datasets.data ?? []}
          analytics={analytics.data}
          records={records.data}
          search={search}
          setSearch={setSearch}
          selectedId={selectedId}
          setSelectedId={setSelectedId}
          fieldTargets={fieldTargets}
          setFieldTargets={setFieldTargets}
          addUnknownFieldMapping={addUnknownFieldMapping}
        />
      ) : (
        <SchemaMappingsPage
          schemas={schemas.data ?? []}
          activeDataset={activeDataset}
          editingSchemaId={editingSchemaId}
          schemaName={schemaName}
          schemaFormat={schemaFormat}
          knownKeys={knownKeys}
          schemaDescription={schemaDescription}
          schemaJson={schemaJson}
          schemaMessage={schemaMessage}
          schemaMutationPending={schemaMutation.isPending}
          deleteSchemaPending={deleteSchemaMutation.isPending}
          reparsePending={reparseMutation.isPending}
          setSchemaName={setSchemaName}
          setSchemaFormat={setSchemaFormat}
          setKnownKeys={setKnownKeys}
          setSchemaDescription={setSchemaDescription}
          setSchemaJson={setSchemaJson}
          resetSchemaForm={resetSchemaForm}
          editSchema={editSchema}
          deleteSchema={(schemaId) => deleteSchemaMutation.mutate(schemaId)}
          saveSchema={() => schemaMutation.mutate()}
          reparseActiveDataset={() => activeDataset && reparseMutation.mutate(activeDataset.id)}
        />
      )}
    </main>
  );
}

function DashboardPage({
  activeDataset,
  datasets,
  analytics,
  records,
  search,
  setSearch,
  selectedId,
  setSelectedId,
  fieldTargets,
  setFieldTargets,
  addUnknownFieldMapping
}: {
  activeDataset: Dataset | null;
  datasets: Dataset[];
  analytics?: Analytics;
  records?: RecordsPage;
  search: string;
  setSearch: (value: string) => void;
  selectedId: number | null;
  setSelectedId: (value: number) => void;
  fieldTargets: Record<string, string>;
  setFieldTargets: Dispatch<SetStateAction<Record<string, string>>>;
  addUnknownFieldMapping: (fieldName: string) => void;
}) {
  return (
    <section className="layout">
      <aside className="panel datasetPanel">
        <div className="panelHeader">
          <Database size={18} />
          <h2>Datasets</h2>
        </div>
        <div className="datasetList">
          {datasets.map((dataset) => (
            <button
              className={`datasetItem ${activeDataset?.id === dataset.id || selectedId === dataset.id ? "active" : ""}`}
              key={dataset.id}
              onClick={() => setSelectedId(dataset.id)}
            >
              <span>{dataset.file_name}</span>
              <small>
                {dataset.detected_format} · {dataset.record_count} records · {Math.round(dataset.confidence * 100)}%
              </small>
            </button>
          ))}
          {!datasets.length && <p className="empty">Upload LogForge samples to begin.</p>}
        </div>
      </aside>

      <section className="workspace">
        <Stats dataset={activeDataset} analytics={analytics} />

        {activeDataset?.warnings?.length ? (
          <div className="warningBar">
            <AlertTriangle size={18} />
            <span>{activeDataset.warnings.join(" ")}</span>
          </div>
        ) : null}

        <div className="grid two">
          <ChartPanel title="Severity" data={analytics?.severity_counts ?? []} barKey="value" />
          <ChartPanel title="Status" data={analytics?.status_counts ?? []} barKey="value" />
        </div>

        <section className="panel">
          <div className="panelHeader spread">
            <div>
              <div className="inlineTitle">
                <Search size={18} />
                <h2>Record Explorer</h2>
              </div>
              <p className="muted">{records?.total ?? 0} matching records</p>
            </div>
            <input
              className="searchInput"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search message, tool, alarm"
            />
          </div>
          <RecordTable records={records?.items ?? []} />
        </section>

        <div className="grid two">
          <section className="panel">
            <div className="panelHeader">
              <BarChart3 size={18} />
              <h2>Metric Ranges</h2>
            </div>
            <div className="metricList">
              {(analytics?.metric_ranges ?? []).slice(0, 12).map((metric) => (
                <div className="metricRow" key={metric.name}>
                  <strong>{metric.name}</strong>
                  <span>
                    min {metric.min} · avg {metric.avg} · max {metric.max}
                  </span>
                </div>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="panelHeader">
              <AlertTriangle size={18} />
              <h2>Unknown Fields</h2>
            </div>
            <div className="metricList">
              {(analytics?.unknown_fields ?? []).slice(0, 12).map((field) => (
                <div className="metricRow" key={field.name}>
                  <strong>{field.name}</strong>
                  <span>
                    {field.count} hits · {field.samples.map((item) => String(item)).join(", ")}
                  </span>
                  <div className="mappingControls">
                    <input
                      value={fieldTargets[field.name] ?? suggestTarget(field.name)}
                      onChange={(event) =>
                        setFieldTargets((current) => ({ ...current, [field.name]: event.target.value }))
                      }
                      placeholder="canonical field or metric name"
                    />
                    <button type="button" onClick={() => addUnknownFieldMapping(field.name)}>
                      Add mapping
                    </button>
                  </div>
                </div>
              ))}
              {!analytics?.unknown_fields?.length && <p className="empty">No unknown fields in the selected dataset.</p>}
            </div>
          </section>
        </div>

        <section className="panel">
          <div className="panelHeader">
            <BarChart3 size={18} />
            <h2>Record Timeline</h2>
          </div>
          <div className="chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={analytics?.timeline ?? []}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="time" tick={{ fontSize: 11 }} />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Line type="monotone" dataKey="records" stroke="#287c76" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
      </section>
    </section>
  );
}

function SchemaMappingsPage({
  schemas,
  activeDataset,
  editingSchemaId,
  schemaName,
  schemaFormat,
  knownKeys,
  schemaDescription,
  schemaJson,
  schemaMessage,
  schemaMutationPending,
  deleteSchemaPending,
  reparsePending,
  setSchemaName,
  setSchemaFormat,
  setKnownKeys,
  setSchemaDescription,
  setSchemaJson,
  resetSchemaForm,
  editSchema,
  deleteSchema,
  saveSchema,
  reparseActiveDataset
}: {
  schemas: SchemaProfile[];
  activeDataset: Dataset | null;
  editingSchemaId: number | null;
  schemaName: string;
  schemaFormat: string;
  knownKeys: string;
  schemaDescription: string;
  schemaJson: string;
  schemaMessage: string | null;
  schemaMutationPending: boolean;
  deleteSchemaPending: boolean;
  reparsePending: boolean;
  setSchemaName: (value: string) => void;
  setSchemaFormat: (value: string) => void;
  setKnownKeys: (value: string) => void;
  setSchemaDescription: (value: string) => void;
  setSchemaJson: (value: string) => void;
  resetSchemaForm: () => void;
  editSchema: (schema: SchemaProfile) => void;
  deleteSchema: (schemaId: number) => void;
  saveSchema: () => void;
  reparseActiveDataset: () => void;
}) {
  return (
    <section className="schemaPage">
      <section className="panel">
        <div className="panelHeader spread">
          <div>
            <div className="inlineTitle">
              <Settings2 size={18} />
              <h2>{editingSchemaId ? "Edit Schema Mapping" : "Create Schema Mapping"}</h2>
            </div>
            <p className="muted">
              Map vendor-specific keys to canonical fields or flexible metric names, then reparse the selected dataset.
            </p>
          </div>
          <div className="formActions compact">
            <button className="secondaryButton" type="button" onClick={resetSchemaForm}>
              <PlusCircle size={18} />
              New
            </button>
            {activeDataset ? (
              <button
                className="iconButton"
                onClick={reparseActiveDataset}
                disabled={reparsePending}
                title="Reparse selected dataset"
              >
                <RefreshCw size={18} />
                Reparse {activeDataset.file_name}
              </button>
            ) : null}
          </div>
        </div>

        <form
          className="schemaForm"
          onSubmit={(event) => {
            event.preventDefault();
            saveSchema();
          }}
        >
          <input value={schemaName} onChange={(event) => setSchemaName(event.target.value)} placeholder="Schema name" />
          <input value={schemaFormat} onChange={(event) => setSchemaFormat(event.target.value.toUpperCase())} placeholder="Format or ANY" />
          <input value={knownKeys} onChange={(event) => setKnownKeys(event.target.value)} placeholder="Known keys, comma-separated" />
          <input
            className="schemaDescriptionInput"
            value={schemaDescription}
            onChange={(event) => setSchemaDescription(event.target.value)}
            placeholder="Description"
          />
          <textarea value={schemaJson} onChange={(event) => setSchemaJson(event.target.value)} rows={10} />
          <div className="formActions">
            <button type="submit" disabled={schemaMutationPending}>
              {editingSchemaId ? "Update mapping" : "Save mapping"}
            </button>
            <button className="secondaryButton" type="button" onClick={resetSchemaForm}>
              Clear form
            </button>
          </div>
          {schemaMessage ? <p className="muted">{schemaMessage}</p> : null}
        </form>
      </section>

      <section className="panel">
        <div className="panelHeader">
          <Database size={18} />
          <h2>Saved Custom Mappings</h2>
        </div>
        <div className="schemaCards">
          {schemas.map((schema) => (
            <article className={`schemaCard ${editingSchemaId === schema.id ? "active" : ""}`} key={schema.id}>
              <div className="schemaCardHeader">
                <div>
                  <h3>{schema.name}</h3>
                  <p className="schemaMeta">
                    {schema.format || "ANY"} · {schema.known_keys.length} known keys · {Object.keys(schema.field_mappings ?? {}).length} mappings
                  </p>
                </div>
                <div className="schemaActions">
                  <button className="secondaryButton" type="button" onClick={() => editSchema(schema)}>
                    <Pencil size={16} />
                    Edit
                  </button>
                  <button
                    className="dangerButton"
                    type="button"
                    onClick={() => deleteSchema(schema.id)}
                    disabled={deleteSchemaPending}
                  >
                    <Trash2 size={16} />
                    Delete
                  </button>
                </div>
              </div>
              {schema.description ? <p>{schema.description}</p> : null}
              <div className="mappingPreview">
                {Object.entries(schema.field_mappings ?? {}).map(([target, aliases]) => (
                  <span key={target}>
                    <strong>{target}</strong>: {Array.isArray(aliases) ? aliases.join(", ") : aliases}
                  </span>
                ))}
              </div>
            </article>
          ))}
          {!schemas.length && <p className="empty">No custom mappings yet.</p>}
        </div>
      </section>
    </section>
  );
}

function buildSchemaPayload(
  name: string,
  description: string,
  format: string,
  knownKeys: string,
  mappingJson: string
) {
  return {
    name,
    description: description || null,
    format: format || null,
    known_keys: knownKeys
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    field_mappings: JSON.parse(mappingJson),
    timestamp_field: null,
    severity_field: null,
    message_field: null
  };
}

function mergeCsvValue(existing: string, value: string) {
  const values = existing
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (!values.includes(value)) values.push(value);
  return values.join(", ");
}

function suggestTarget(fieldName: string) {
  const key = fieldName.toLowerCase().replace(/[^a-z0-9]/g, "");
  if (key.includes("time") || key.includes("timestamp")) return "timestamp";
  if (key.includes("tool") || key.includes("eqp") || key.includes("machine")) return "tool_id";
  if (key.includes("wafer")) return "wafer_id";
  if (key.includes("lot") || key.includes("batch")) return "lot_id";
  if (key.includes("recipe") || key.includes("rcp")) return "recipe";
  if (key.includes("severity") || key.includes("level") || key.includes("sev")) return "severity";
  if (key.includes("alarm") || key.includes("fault")) return "alarm_code";
  if (key.includes("message") || key.includes("detail") || key.includes("description")) return "message";
  return fieldName.replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase() || "custom_metric";
}

function Stats({ dataset, analytics }: { dataset: Dataset | null; analytics?: Analytics }) {
  const stats = [
    ["Format", dataset?.detected_format ?? "None"],
    ["Records", dataset?.record_count ?? 0],
    ["Confidence", dataset ? `${Math.round(dataset.confidence * 100)}%` : "0%"],
    ["Unknown Fields", String(analytics?.totals?.unknownFieldCount ?? 0)]
  ];
  return (
    <section className="stats">
      {stats.map(([label, value]) => (
        <div className="stat" key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </section>
  );
}

function ChartPanel({ title, data, barKey }: { title: string; data: { name: string; value: number }[]; barKey: string }) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <BarChart3 size={18} />
        <h2>{title}</h2>
      </div>
      <div className="chart">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Bar dataKey={barKey} fill="#287c76" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function RecordTable({ records }: { records: LogRecord[] }) {
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Time</th>
            <th>Tool</th>
            <th>Status</th>
            <th>Severity</th>
            <th>Recipe</th>
            <th>Message</th>
            <th>Metrics</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => (
            <tr key={record.id}>
              <td>{record.record_index}</td>
              <td>{record.timestamp ? new Date(record.timestamp).toLocaleString() : "—"}</td>
              <td>{record.tool_id ?? "—"}</td>
              <td>{record.status ?? "—"}</td>
              <td>
                <span className={`badge ${record.severity?.toLowerCase() ?? ""}`}>{record.severity ?? "—"}</span>
              </td>
              <td>{record.recipe ?? "—"}</td>
              <td className="messageCell">{record.message ?? "—"}</td>
              <td>{Object.keys(record.metrics ?? {}).slice(0, 4).join(", ") || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
