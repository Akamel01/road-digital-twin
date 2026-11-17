"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import styles from "@/components/dev/dev.module.css";
import {
  loadSites,
  loadSite,
  loadLabels,
  saveLabels,
  approve,
  newVersion,
  type SiteMeta,
  type GeoJsonFeatureCollection,
} from "@/lib/labels";
import { actionText, errorText } from "@/lib/devapi";

export default function DevLabelsPage() {
  const [sites, setSites] = useState<string[]>([]);
  const [site, setSite] = useState("");
  const [meta, setMeta] = useState<SiteMeta | null>(null);
  const [labelsText, setLabelsText] = useState("");
  const [approvedBy, setApprovedBy] = useState("operator");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const loadOne = useCallback(async (s: string) => {
    if (!s) {
      setMeta(null);
      setLabelsText("");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const [m, labels] = await Promise.all([loadSite(s), loadLabels(s)]);
      setMeta(m);
      setLabelsText(JSON.stringify(labels, null, 2));
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
        setLabelsText("");
      }
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }, [site]);

  useEffect(() => {
    loadSites().then(setSites).catch((e) => setError(errorText(e)));
  }, []);

  useEffect(() => {
    if (site) loadOne(site);
  }, [site, loadOne]);

  async function handleSave() {
    if (!site || !meta) return;
    let parsed: GeoJsonFeatureCollection;
    try {
      parsed = JSON.parse(labelsText) as GeoJsonFeatureCollection;
    } catch {
      setError("Invalid JSON in labels.");
      return;
    }
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const m = await saveLabels(site, meta.version, parsed);
      setMeta(m);
      setInfo("Saved.");
    } catch (e) {
      setError(actionText(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleApprove() {
    if (!site) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const m = await approve(site, approvedBy || "operator");
      setMeta(m);
      setInfo("Approved.");
    } catch (e) {
      setError(actionText(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleNewVersion() {
    if (!site) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const m = await newVersion(site);
      setMeta(m);
      await loadOne(site);
      setInfo("New version created.");
    } catch (e) {
      setError(actionText(e));
    } finally {
      setBusy(false);
    }
  }

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
          <select value={site} onChange={(e) => setSite(e.target.value)} disabled={busy}>
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
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
          <button type="button" className={styles.button} onClick={handleSave} disabled={busy || !meta || meta.frozen}>
            Save
          </button>
          <button type="button" className={styles.button} onClick={handleApprove} disabled={busy || !meta || meta.frozen}>
            Approve
          </button>
          <button type="button" className={styles.button} onClick={handleNewVersion} disabled={busy || !meta}>
            New version
          </button>
        </div>
        <label className={styles.field} style={{ marginTop: 12 }}>
          <span>Approved by</span>
          <input value={approvedBy} onChange={(e) => setApprovedBy(e.target.value)} disabled={busy} />
        </label>
        {error ? <p className={styles.notice} role="alert" style={{ marginTop: 8 }}>{error}</p> : null}
        {info ? <p className={styles.notice} role="status" style={{ marginTop: 8 }}>{info}</p> : null}
      </section>
      <section className={styles.panel} style={{ marginTop: 12 }}>
        <div className={styles.panelHead}>
          <h2 className={styles.h2}>Labels JSON</h2>
        </div>
        <textarea
          value={labelsText}
          onChange={(e) => setLabelsText(e.target.value)}
          disabled={busy}
          spellCheck={false}
          style={{ width: "100%", minHeight: 320, fontFamily: "ui-monospace, monospace", fontSize: 12 }}
        />
      </section>
    </div>
  );
}
