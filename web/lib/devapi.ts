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
}

export class ApiUnreachable extends Error {}

export class ApiStatus extends Error {
  status: number;
  constructor(status: number) {
    super(`HTTP ${status}`);
    this.status = status;
  }
}

async function getJson<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { credentials: "include" });
  } catch {
    throw new ApiUnreachable();
  }
  if (!res.ok) throw new ApiStatus(res.status);
  return (await res.json()) as T;
}

export const fetchRuns = () => getJson<RunSummary[]>("/api/r/runs");
export const fetchRun = (id: string) => getJson<Manifest>(`/api/r/runs/${encodeURIComponent(id)}`);
export const fetchRegistry = () => getJson<Registry>("/api/r/registry");

// Stage output folders are "<number>_<name>" (twin/runner.py); manifest files are relative to that folder.
export function stageFileUrl(runId: string, stage: RegistryStage, file: string): string {
  const path = `${stage.number}_${stage.name}/${file}`;
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  return `${API_BASE}/api/r/runs/${encodeURIComponent(runId)}/files/${encoded}`;
}

// Sign-in: a top-level navigation to the Access login on the API host, not a fetch.
// docs/research/cloudflare-access.md: fetch cannot complete the Access login redirect under CORS, and the
// CF_Authorization cookie is set on the API host after a top-level visit. The /cdn-cgi/access/login?redirect_url=
// form is the Cloudflare Access convention named in the ticket; that doc does not spell it out. Verify on day 1.
export function signInUrl(currentPage: string): string {
  return `${API_BASE}/cdn-cgi/access/login?redirect_url=${encodeURIComponent(currentPage)}`;
}

// Stage name to the params sections it owns (PARAM_STAGE in twin/contracts.py). "select" is setup, not a stage.
export const STAGE_PARAM_KEYS: Record<string, string[]> = {
  load: ["facilities", "seed"],
  mask: ["mask"],
  align: ["align"],
  ground: ["ground"],
  features: ["features"],
  colour: ["colour"],
  profile: ["profile"],
  isd: ["isd"],
  accuracy: ["accuracy"],
};

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
