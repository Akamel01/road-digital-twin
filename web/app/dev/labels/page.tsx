"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import styles from "@/components/dev/dev.module.css";
import {
  loadSites,
  loadSite,
  type SiteMeta,
} from "@/lib/labels";
import LabelsMapEditor from "@/components/dev/LabelsMapEditor";
import { errorText } from "@/lib/devapi";
import { loadArea, type AreaIndex } from "@/lib/showcase";

export default function DevLabelsPage() {
  const [sites, setSites] = useState<string[]>([]);
  const [site, setSite] = useState("");
  const [meta, setMeta] = useState<SiteMeta | null>(null);
  const [area, setArea] = useState<AreaIndex | null>(null);
  const [run, setRun] = useState<string>(process.env.NEXT_PUBLIC_TWIN_RUN ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadOne = useCallback(async (s: string) => {
    if (!s) {
      setMeta(null);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const m = await loadSite(s);
      setMeta(m);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const reloadSites = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const list = await loadSites();
      setSites(list);
      if (site && !list.includes(site)) {
        setSite("");
        setMeta(null);
      }
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }, [site]);

  useEffect(() => {
    let cancelled = false;
    loadSites()
      .then((list) => {
        if (!cancelled) setSites(list);
      })
      .catch((e) => {
        if (!cancelled) setError(errorText(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadArea()
      .then((a) => {
        if (cancelled) return;
        setArea(a);
        setRun((prev) => (prev ? prev : a.drives[0]?.run_id ?? ""));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className={styles.root}>
      <header className={styles.top}>
        <Link className={styles.back} href="/dev">
          ← Dev
        </Link>
        <b className={styles.brand}>Label sites (dev)</b>
      </header>
      <p className={styles.muted} style={{ marginBottom: 8 }}>
        Generate a sample site: <code>twin labels draft seaport-dev-1 --area seaport</code>
      </p>
      <section className={styles.panel}>
        <div className={styles.panelHead}>
          <h2 className={styles.h2}>Label sites</h2>
          <button type="button" className={styles.button} onClick={reloadSites} disabled={busy}>
            Reload
          </button>
        </div>
        <label className={styles.field}>
          <span>Site</span>
          <select
            value={site}
            onChange={(e) => {
              const v = e.target.value;
              setSite(v);
              void loadOne(v);
            }}
            disabled={busy}
          >
            <option value="">Select…</option>
            {sites.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        {meta ? (
          <div style={{ marginTop: 10, fontSize: 12, lineHeight: 1.5 }}>
            <div><b>Role:</b> {meta.role}</div>
            <div><b>Version:</b> {meta.version}</div>
            <div><b>Frozen:</b> {meta.frozen ? "yes" : "no"}</div>
            <div><b>Source area:</b> {meta.source_area}</div>
            <div><b>Approved:</b> {meta.approved_by ? `${meta.approved_by} (${meta.approved_at ?? ""})` : "—"}</div>
          </div>
        ) : (
          <p className={styles.muted} style={{ marginTop: 8 }}>No site loaded.</p>
        )}
        {error ? <p className={styles.notice} role="alert" style={{ marginTop: 8 }}>{error}</p> : null}
      </section>
      <section className={styles.panel} style={{ marginTop: 12 }}>
        <div className={styles.panelHead}>
          <h2 className={styles.h2}>Labels map</h2>
        </div>
        <label className={styles.field}>
          <span>Showcase run</span>
          <input value={run} onChange={(e) => setRun(e.target.value)} disabled={busy} list="runs" />
          <datalist id="runs">
            {(area?.drives ?? []).map((d) => (
              <option key={d.run_id} value={d.run_id} />
            ))}
          </datalist>
        </label>
        {site && meta ? (
          <LabelsMapEditor site={site} meta={meta} onMeta={setMeta} run={run} />
        ) : (
          <p className={styles.muted}>Select a site to edit labels.</p>
        )}
      </section>
    </div>
  );
}
