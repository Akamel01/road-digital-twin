import { useEffect, useState } from "react";
import Compare from "@/components/dev/Compare";
import ParamForm, { type EditValue, type Edits } from "@/components/dev/ParamForm";
import styles from "@/components/dev/dev.module.css";
import {
  actionText,
  cancelRun,
  errorText,
  earliestStage,
  fetchRun,
  flatten,
  paramKeysFor,
  type JsonSchema,
  type Manifest,
  type Registry,
  type RegistryStage,
  rerunRun,
  setPath,
  stageFileUrl,
} from "@/lib/devapi";

// Same rule as twin/api.py _status: the first of failed, cancelled, running, pending, else ok.
export function runStatus(m: Manifest): string {
  const statuses = new Set(m.stages.map((s) => s.status));
  for (const name of ["failed", "cancelled", "running", "pending"]) if (statuses.has(name)) return name;
  return statuses.size ? "ok" : "pending";
}

interface Props {
  runId: string | null;
  registry: Registry | null;
  signedIn: boolean;
  tick: number; // the panel bumps this after a write, so the run reloads
  onSelect: (id: string) => void;
  onChanged: () => void;
}

type Loaded = { id: string; manifest?: Manifest; error?: string };

function withEdit(prev: Edits, path: string, value: EditValue | undefined): Edits {
  const next = { ...prev };
  if (value === undefined) delete next[path];
  else next[path] = value;
  return next;
}

export default function RunDetail({ runId, registry, signedIn, tick, onSelect, onChanged }: Props) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [edits, setEdits] = useState<Edits>({});
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

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
  }, [runId, tick]);

  if (!runId) return <Shell><p className={styles.muted}>Select a run.</p></Shell>;
  if (!loaded || loaded.id !== runId) return <Shell><p className={styles.muted}>Loading run…</p></Shell>;
  if (loaded.error) return <Shell><p className={styles.notice}>{loaded.error}</p></Shell>;
  const m = loaded.manifest!;
  const schema: JsonSchema | null = registry?.params_schema ?? null;
  const stageSpec = (name: string): RegistryStage | undefined => registry?.stages.find((s) => s.name === name);
  const metricRows = Object.entries(flatten(m.metrics));
  const status = runStatus(m);

  // Changed parameters: the re-run starts at the earliest stage that uses one of them.
  const changed = Object.keys(edits);
  const fromStage = registry ? earliestStage(registry, changed) : null;

  // One write at a time. On success the panel reloads its lists; `select` moves to the new run.
  async function write(call: () => Promise<{ run_id: string }>, select: boolean) {
    setBusy(true);
    setActionError(null);
    try {
      const res = await call();
      onChanged();
      if (select) onSelect(res.run_id);
      else setEdits({});
    } catch (e) {
      setActionError(actionText(e));
    } finally {
      setBusy(false);
    }
  }

  // Re-run sends only the changed params as a partial override; the API merges them onto the parent.
  function rerun(from: string) {
    const params: Record<string, unknown> = {};
    for (const [path, value] of Object.entries(edits)) setPath(params, path, value);
    return write(() => rerunRun(m.run_id, { from_stage: from, params }), true);
  }

  return (
    <Shell>
      <div className={styles.panelHead}>
        <h2 className={styles.h2}>{m.run_id}</h2>
        <span className={styles.pill} data-status={status}>
          {status}
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
      {actionError ? (
        <p className={styles.notice} role="alert">
          {actionError}
        </p>
      ) : null}
      {signedIn && changed.length > 0 ? (
        <div className={styles.changeBar} role="status">
          <span>Changed: {changed.join(", ")}</span>
          {fromStage === null ? <span className={styles.muted}>Setup parameters only: nothing to re-run.</span> : null}
          <button type="button" className={styles.button} disabled={busy} onClick={() => setEdits({})}>
            Discard
          </button>
          <button
            type="button"
            className={styles.button}
            disabled={busy || fromStage === null}
            onClick={() => fromStage && rerun(fromStage)}
          >
            {fromStage ? `Re-run from ${fromStage}` : "Re-run"}
          </button>
        </div>
      ) : null}
      <div className={styles.panelHead}>
        <h3 className={styles.h2}>Stages</h3>
        <button
          type="button"
          className={styles.button}
          disabled={!signedIn || busy || (status !== "running" && status !== "pending")}
          title={signedIn ? undefined : "Sign in to cancel"}
          onClick={() => write(() => cancelRun(m.run_id), false)}
        >
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
              <button
                type="button"
                className={styles.button}
                disabled={!signedIn || busy || changed.length === 0}
                title={signedIn ? "Re-run from this stage with the changed params" : "Sign in to re-run"}
                onClick={() => rerun(st.name)}
              >
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
                <ParamForm
                  keys={registry ? paramKeysFor(registry, st.name) : []}
                  schema={schema}
                  params={m.params}
                  edits={edits}
                  disabled={!signedIn || busy}
                  onEdit={(path, value) => setEdits((prev) => withEdit(prev, path, value))}
                />
              </details>
            ) : null}
          </section>
        );
      })}
      {m.parent ? <Compare a={m.parent.run_id} b={m.run_id} tick={tick} /> : null}
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
