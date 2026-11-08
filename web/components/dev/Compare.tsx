import { useEffect, useState } from "react";
import styles from "@/components/dev/dev.module.css";
import { type DiffRow, errorText, fetchCompare } from "@/lib/devapi";

const SECTIONS = ["pipeline", "params", "metrics"] as const;

function show(value: unknown): string {
  if (value === undefined || value === null) return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

// Differences between a run and its parent: pipeline, params and metrics (twin/api.py compare).
// Changed metrics are highlighted. Public read, so it works signed out.
export default function Compare({ a, b, tick }: { a: string; b: string; tick: number }) {
  const [state, setState] = useState<{ key: string; rows?: DiffRow[]; error?: string } | null>(null);
  const key = `${a}|${b}|${tick}`;

  useEffect(() => {
    let alive = true;
    fetchCompare(a, b).then(
      (rows) => alive && setState({ key: `${a}|${b}|${tick}`, rows }),
      (e) => alive && setState({ key: `${a}|${b}|${tick}`, error: errorText(e) }),
    );
    return () => {
      alive = false;
    };
  }, [a, b, tick]);

  const current = state?.key === key ? state : null;
  return (
    <section className={styles.compare} aria-label="Compare with parent">
      <h3 className={styles.h2}>Compare with parent</h3>
      <p className={styles.muted}>
        {a} (parent) and {b} (this run)
      </p>
      {!current ? (
        <p className={styles.muted}>Loading comparison…</p>
      ) : current.error ? (
        <p className={styles.notice}>{current.error}</p>
      ) : current.rows!.length === 0 ? (
        <p className={styles.muted}>No differences.</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Path</th>
              <th scope="col">Parent</th>
              <th scope="col">This run</th>
            </tr>
          </thead>
          <tbody>
            {SECTIONS.flatMap((section) => {
              const rows = current.rows!.filter((r) => r.path.split(".")[0].split("[")[0] === section);
              return rows.map((r) => (
                <tr key={r.path} className={section === "metrics" ? styles.changed : undefined}>
                  <td className={styles.muted}>{r.path}</td>
                  <td>{show(r.a)}</td>
                  <td>{show(r.b)}</td>
                </tr>
              ));
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
