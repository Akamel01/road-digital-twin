import styles from "@/components/dev/dev.module.css";
import type { RunSummary } from "@/lib/devapi";

// "20261108T090000Z" from the API as "2026-11-08 09:00:00 UTC".
export function formatStarted(s: string): string {
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/.exec(s);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]} UTC` : s;
}

interface Props {
  runs: RunSummary[] | null;
  selected: string | null;
  onSelect: (id: string) => void;
}

export default function RunList({ runs, selected, onSelect }: Props) {
  return (
    <section className={styles.panel} aria-labelledby="runs-h">
      <div className={styles.panelHead}>
        <h2 id="runs-h" className={styles.h2}>
          Runs
        </h2>
        {/* Starting a run is a write: disabled until sign-in (ticket 13b). */}
        <button type="button" className={styles.button} disabled title="Sign in to start a run">
          New run
        </button>
      </div>
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
