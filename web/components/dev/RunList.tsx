import { useState } from "react";
import styles from "@/components/dev/dev.module.css";
import { actionText, fetchRun, type RunSummary, startRun } from "@/lib/devapi";

// "20261108T090000Z" from the API as "2026-11-08 09:00:00 UTC".
export function formatStarted(s: string): string {
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/.exec(s);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]} UTC` : s;
}

interface Props {
  runs: RunSummary[] | null;
  selected: string | null;
  signedIn: boolean;
  onSelect: (id: string) => void;
  onChanged: () => void;
}

export default function RunList({ runs, selected, signedIn, onSelect, onChanged }: Props) {
  const [open, setOpen] = useState(false);
  const [scene, setScene] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // New run: the selected run's scene, pipeline and params (the server's defaults when none is selected).
  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const body: { scene_token: string; pipeline?: unknown; params?: unknown } = { scene_token: scene.trim() };
      if (selected) {
        const m = await fetchRun(selected);
        body.pipeline = m.pipeline;
        body.params = m.params;
      }
      const res = await startRun(body);
      setOpen(false);
      onChanged();
      onSelect(res.run_id);
    } catch (e) {
      setError(actionText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={styles.panel} aria-labelledby="runs-h">
      <div className={styles.panelHead}>
        <h2 id="runs-h" className={styles.h2}>
          Runs
        </h2>
        <button
          type="button"
          className={styles.button}
          disabled={!signedIn}
          title={signedIn ? undefined : "Sign in to start a run"}
          aria-expanded={open}
          onClick={() => {
            if (!open) setScene(runs?.find((r) => r.run_id === selected)?.scene_token ?? "");
            setOpen(!open);
          }}
        >
          New run
        </button>
      </div>
      {open ? (
        <form
          className={styles.newRun}
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <label>
            Scene token{" "}
            <input
              type="text"
              value={scene}
              onChange={(e) => setScene(e.target.value)}
              required
              pattern="\S+"
              aria-describedby="new-run-hint"
            />
          </label>
          <small id="new-run-hint" className={styles.muted}>
            {selected ? `Settings copied from ${selected}.` : "No run selected: default settings."}
          </small>
          <button type="submit" className={styles.button} disabled={busy}>
            {busy ? "Starting…" : "Start run"}
          </button>
        </form>
      ) : null}
      {error ? (
        <p className={styles.notice} role="alert">
          {error}
        </p>
      ) : null}
      {runs === null ? (
        <p className={styles.muted}>Loading runs…</p>
      ) : runs.length === 0 ? (
        <p className={styles.muted}>No runs yet.</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Run</th>
              <th scope="col">Scene</th>
              <th scope="col">Parent</th>
              <th scope="col">Status</th>
              <th scope="col">Started</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.run_id}>
                <td>
                  <button
                    type="button"
                    className={styles.rowButton}
                    aria-pressed={selected === r.run_id}
                    onClick={() => onSelect(r.run_id)}
                  >
                    {r.run_id}
                  </button>
                </td>
                <td className={styles.muted}>{r.scene_token.slice(0, 8)}</td>
                <td className={styles.muted}>{r.parent ?? "—"}</td>
                <td>
                  <span className={styles.pill} data-status={r.status}>
                    {r.status}
                  </span>
                </td>
                <td className={styles.muted}>{formatStarted(r.started)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
