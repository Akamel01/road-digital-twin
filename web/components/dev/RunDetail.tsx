import { useEffect, useState } from "react";
import ParamForm from "@/components/dev/ParamForm";
import styles from "@/components/dev/dev.module.css";
import {
  ApiStatus,
  ApiUnreachable,
  fetchRun,
  flatten,
  type JsonSchema,
  type Manifest,
  type Registry,
  type RegistryStage,
  stageFileUrl,
} from "@/lib/devapi";

const UNREACHABLE = "Live API unreachable — showing nothing; public views still work.";

export function errorText(e: unknown): string {
  if (e instanceof ApiUnreachable) return UNREACHABLE;
  if (e instanceof ApiStatus) return e.status === 404 ? "Run not found." : `Live API returned HTTP ${e.status}.`;
  return "Live API error.";
}

// Same rule as twin/api.py _status: the first of failed, cancelled, running, pending, else ok.
export function runStatus(m: Manifest): string {
  const statuses = new Set(m.stages.map((s) => s.status));
  for (const name of ["failed", "cancelled", "running", "pending"]) if (statuses.has(name)) return name;
  return statuses.size ? "ok" : "pending";
}

interface Props {
  runId: string | null;
  registry: Registry | null;
  onSelect: (id: string) => void;
}

type Loaded = { id: string; manifest?: Manifest; error?: string };

export default function RunDetail({ runId, registry, onSelect }: Props) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  // Polls every 5 s while a stage is running. Results are tagged with the run id, so a stale one is ignored.
  useEffect(() => {
    const id = runId;
    if (!id) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const manifest = await fetchRun(id);
        if (!alive) return;
        setLoaded({ id, manifest });
        if (manifest.stages.some((s) => s.status === "running")) timer = setTimeout(load, 5000);
      } catch (e) {
        if (!alive) return;
        setLoaded({ id, error: errorText(e) });
      }
    };
    load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [runId]);

  if (!runId) return <Shell><p className={styles.muted}>Select a run.</p></Shell>;
  if (!loaded || loaded.id !== runId) return <Shell><p className={styles.muted}>Loading run…</p></Shell>;
  if (loaded.error) return <Shell><p className={styles.notice}>{loaded.error}</p></Shell>;
  const m = loaded.manifest!;
  const schema: JsonSchema | null = registry?.params_schema ?? null;
  const stageSpec = (name: string): RegistryStage | undefined => registry?.stages.find((s) => s.name === name);
  const metricRows = Object.entries(flatten(m.metrics));

  return (
    <Shell>
      <div className={styles.panelHead}>
        <h2 className={styles.h2}>{m.run_id}</h2>
        <span className={styles.pill} data-status={runStatus(m)}>
          {runStatus(m)}
        </span>
      </div>
      <p className={styles.muted}>
        Scene {m.data.scene_token}
        {m.parent ? (
          <>
            {" · parent "}
            <button type="button" className={styles.rowButton} onClick={() => onSelect(m.parent!.run_id)}>
              {m.parent.run_id}
            </button>
            {` from ${m.parent.from_stage}`}
          </>
        ) : null}
      </p>
      <div className={styles.panelHead}>
        <h3 className={styles.h2}>Stages</h3>
        {/* Cancel and re-run are writes: disabled until sign-in (ticket 13b). */}
        <button type="button" className={styles.button} disabled title="Sign in to cancel">
          Cancel run
        </button>
      </div>
      {m.stages.map((st, i) => {
        const spec = stageSpec(st.name);
        const pipe = m.pipeline[st.name];
        return (
          <section key={st.name} className={styles.stage} aria-label={`Stage ${st.name}`}>
            <div className={styles.stageHead}>
              <strong>
                {spec?.number ?? i + 1}. {st.name}
              </strong>
              <label>
                Method{" "}
                <select defaultValue={st.method} disabled aria-label={`Method for ${st.name}`}>
                  {(spec?.methods ?? [st.method]).map((meth) => (
                    <option key={meth} value={meth}>
                      {meth}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <input type="checkbox" defaultChecked={pipe?.enabled ?? true} disabled /> On
              </label>
              <span className={styles.pill} data-status={st.status}>
                {st.status}
              </span>
              <span className={styles.muted}>{st.seconds.toFixed(1)} s</span>
              <button type="button" className={styles.button} disabled title="Sign in to re-run">
                Re-run from here
              </button>
            </div>
            {st.files.length > 0 ? (
              <ul className={styles.stageFiles}>
                {st.files.map((f) =>
                  spec ? (
                    <li key={f}>
                      <a href={stageFileUrl(m.run_id, spec, f)} target="_blank" rel="noopener noreferrer">
                        {f}
                      </a>
                    </li>
                  ) : (
                    <li key={f} className={styles.muted}>
                      {f}
                    </li>
                  ),
                )}
              </ul>
            ) : null}
            {schema ? (
              <details className={styles.params}>
                <summary>Parameters</summary>
                <ParamForm stage={st.name} schema={schema} params={m.params} />
              </details>
            ) : null}
          </section>
        );
      })}
      <h3 className={styles.h2} style={{ marginTop: 16 }}>
        Metrics
      </h3>
      {metricRows.length === 0 ? (
        <p className={styles.muted}>No metrics yet.</p>
      ) : (
        <table className={`${styles.table} ${styles.metrics}`}>
          <thead>
            <tr>
              <th scope="col">Path</th>
              <th scope="col">Value</th>
            </tr>
          </thead>
          <tbody>
            {metricRows.map(([path, value]) => (
              <tr key={path}>
                <td className={styles.muted}>{path}</td>
                <td>{value === null ? "—" : String(value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <section className={styles.panel} aria-label="Run detail">{children}</section>;
}
