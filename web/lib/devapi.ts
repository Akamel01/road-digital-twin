// Read-only client for the control API (/api/r/*). Types mirror twin/contracts.py and twin/api.py; keep in sync.

export const API_BASE = (process.env.NEXT_PUBLIC_TWIN_API || "https://twin-api.papyrus-ai.net").replace(/\/+$/, "");

export interface RunSummary {
  run_id: string;
  scene_token: string;
  parent: string | null;
  status: string;
  started: string;
}

export interface StageRecord {
  name: string;
  method: string;
  status: string;
  started: string;
  seconds: number;
  files: string[];
}

export interface Manifest {
  run_id: string;
  parent: { run_id: string; from_stage: string } | null;
  data: { scene_token: string };
  pipeline: Record<string, { method: string; enabled: boolean }>;
  params: Record<string, unknown>;
  stages: StageRecord[];
  metrics: Record<string, unknown>;
}

export interface RegistryStage {
  name: string;
  number: number;
  methods: string[];
  requires: string[];
  outputs: string[];
  optional: boolean;
}

// The subset of JSON Schema that pydantic emits for Params.
export interface JsonSchema {
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  type?: string;
  enum?: string[];
  minimum?: number;
  maximum?: number;
  default?: unknown;
  properties?: Record<string, JsonSchema>;
}

export interface Registry {
  stages: RegistryStage[];
  params_schema: JsonSchema;
  // Top-level params key -> stage that uses it (PARAM_STAGE in twin/contracts.py). null: setup, no re-run.
  param_stage: Record<string, string | null>;
}

// One row of GET /api/r/compare: the value at a dotted path in each run, or null when absent.
export interface DiffRow {
  path: string;
  a: unknown;
  b: unknown;
}

export class ApiUnreachable extends Error {}

export class ApiStatus extends Error {
  status: number;
  detail: string | null; // FastAPI {"detail": "..."} text, when the API sent one
  constructor(status: number, detail: string | null = null) {
    super(`HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

// Every request carries credentials, so the Access cookie is sent to the API host.
async function send<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { credentials: "include", ...init });
  } catch {
    throw new ApiUnreachable();
  }
  if (!res.ok) {
    let detail: string | null = null;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      // FastAPI validation errors (422) send a list of {loc, msg}.
      if (Array.isArray(body.detail))
        detail = body.detail
          .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg ?? ""}`)
          .join("; ");
    } catch {
      // no JSON body: the status alone is the message
    }
    throw new ApiStatus(res.status, detail);
  }
  return (await res.json()) as T;
}

const getJson = <T>(path: string) => send<T>(path);
const postJson = <T>(path: string, body?: unknown) =>
  send<T>(path, {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const fetchRuns = () => getJson<RunSummary[]>("/api/r/runs");
export const fetchRun = (id: string) => getJson<Manifest>(`/api/r/runs/${encodeURIComponent(id)}`);
export const fetchRegistry = () => getJson<Registry>("/api/r/registry");
export const fetchCompare = (a: string, b: string) =>
  getJson<DiffRow[]>(`/api/r/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);

// Signed in = the operator's Access token is accepted. Any failure reads as signed out.
export const fetchWhoami = () => getJson<{ email: string }>("/api/w/whoami");

export interface NewRunBody {
  scene_token: string;
  pipeline?: unknown;
  params?: unknown;
}
export const startRun = (body: NewRunBody) => postJson<{ run_id: string }>("/api/w/runs", body);
export const rerunRun = (id: string, body: { from_stage: string; params?: Record<string, unknown> }) =>
  postJson<{ run_id: string }>(`/api/w/runs/${encodeURIComponent(id)}/rerun`, body);
export const cancelRun = (id: string) => postJson<{ run_id: string }>(`/api/w/runs/${encodeURIComponent(id)}/cancel`);

// Stage output folders are "<number>_<name>" (twin/runner.py); manifest files are relative to that folder.
export function stageFileUrl(runId: string, stage: RegistryStage, file: string): string {
  const path = `${stage.number}_${stage.name}/${file}`;
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  return `${API_BASE}/api/r/runs/${encodeURIComponent(runId)}/files/${encoded}`;
}

// Sign-in: a top-level navigation to /api/w/signin on the API host, which Access guards and then
// redirects to `currentPage` (the API only redirects to the panel origin). A fetch cannot complete
// the Access login under CORS (docs/research/cloudflare-access.md), so this is a plain link.
export function signInUrl(currentPage: string): string {
  return `${API_BASE}/api/w/signin?next=${encodeURIComponent(currentPage)}`;
}

// Param keys a stage owns, from the registry (never a copy of PARAM_STAGE in TS).
export function paramKeysFor(registry: Registry, stage: string): string[] {
  return Object.entries(registry.param_stage)
    .filter(([, owner]) => owner === stage)
    .map(([key]) => key);
}

// Stage that owns a dotted param path: undefined for an unknown key, null for setup ("select").
export function stageForPath(registry: Registry, path: string): string | null | undefined {
  return registry.param_stage[path.split(".")[0]];
}

// Earliest stage that owns a changed param path. null when none does (setup only, e.g. "select").
export function earliestStage(registry: Registry, paths: string[]): string | null {
  const order = registry.stages.map((s) => s.name);
  let best: string | null = null;
  for (const path of paths) {
    const stage = stageForPath(registry, path);
    if (!stage) continue; // null: setup; undefined: unknown key
    if (best === null || order.indexOf(stage) < order.indexOf(best)) best = stage;
  }
  return best;
}

// Nested partial override for the rerun body: "ground.voxel_m" = 0.1 becomes {ground: {voxel_m: 0.1}}.
export function setPath(obj: Record<string, unknown>, path: string, value: unknown): void {
  const keys = path.split(".");
  let node = obj;
  keys.slice(0, -1).forEach((key) => {
    const next = (node[key] ?? {}) as Record<string, unknown>;
    node[key] = next;
    node = next;
  });
  node[keys[keys.length - 1]] = value;
}

export interface ParamField {
  path: string; // dotted path into the run's params, as in twin/api.py _flat
  kind: "number" | "integer" | "boolean" | "enum" | "text";
  min?: number;
  max?: number;
  options?: string[];
  default?: unknown;
}

function resolveRef(root: JsonSchema, node: JsonSchema): JsonSchema {
  if (!node.$ref) return node;
  const name = node.$ref.split("/").pop() ?? "";
  return root.$defs?.[name] ?? {};
}

// Leaf fields under one params section, with their min/max from the schema.
export function paramFields(root: JsonSchema, key: string): ParamField[] {
  const out: ParamField[] = [];
  const walk = (node: JsonSchema, path: string) => {
    const s = resolveRef(root, node);
    if (s.properties) {
      for (const [name, child] of Object.entries(s.properties)) walk(child, `${path}.${name}`);
      return;
    }
    let kind: ParamField["kind"] = "text";
    if (s.enum) kind = "enum";
    else if (s.type === "boolean") kind = "boolean";
    else if (s.type === "integer") kind = "integer";
    else if (s.type === "number") kind = "number";
    out.push({ path, kind, min: s.minimum, max: s.maximum, options: s.enum, default: s.default });
  };
  const top = root.properties?.[key];
  if (top) walk(top, key);
  return out;
}

export function getPath(obj: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((node, key) => {
    if (node && typeof node === "object") return (node as Record<string, unknown>)[key];
    return undefined;
  }, obj);
}

// Leaf values keyed by dotted path, as twin/api.py _flat does for compare.
export function flatten(node: unknown, path = ""): Record<string, unknown> {
  if (node && typeof node === "object") {
    const out: Record<string, unknown> = {};
    const entries = Array.isArray(node)
      ? node.map((v, i) => [`[${i}]`, v] as const)
      : Object.entries(node as Record<string, unknown>).map(([k, v]) => [k, v] as const);
    for (const [key, value] of entries) {
      const sep = key.startsWith("[") ? "" : path ? "." : "";
      Object.assign(out, flatten(value, `${path}${sep}${key}`));
    }
    return out;
  }
  return { [path]: node };
}

const UNREACHABLE = "Live API unreachable — showing nothing; public views still work.";

export function errorText(e: unknown): string {
  if (e instanceof ApiUnreachable) return UNREACHABLE;
  if (e instanceof ApiStatus) return e.status === 404 ? "Run not found." : `Live API returned HTTP ${e.status}.`;
  return "Live API error.";
}

// Text for a failed write. The API's own message (409 busy, 422 refused re-run, 507 low disk) is shown as sent.
export function actionText(e: unknown): string {
  if (e instanceof ApiStatus) {
    if (e.status === 401 || e.status === 403) return "Not signed in as the operator. Sign in again.";
    if (e.detail) return e.detail;
    return `Live API returned HTTP ${e.status}.`;
  }
  return errorText(e);
}
