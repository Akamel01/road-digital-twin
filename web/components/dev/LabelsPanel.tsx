"use client";

import styles from "@/components/dev/dev.module.css";
import type { SiteMeta } from "@/lib/labels";

interface Props {
  site: string;
  meta: SiteMeta | null;
  sites: string[];
  onSelectSite: (site: string) => void;
  onReload: () => void;
  onSave: () => void;
  onApprove: () => void;
  onNewVersion: () => void;
  busy: boolean;
  error: string | null;
  info: string | null;
}

export default function LabelsPanel({
  site,
  meta,
  sites,
  onSelectSite,
  onReload,
  onSave,
  onApprove,
  onNewVersion,
  busy,
  error,
  info,
}: Props) {
  return (
    <section className={styles.panel} aria-labelledby="labels-h">
      <div className={styles.panelHead}>
        <h2 id="labels-h" className={styles.h2}>
          Label sites
        </h2>
        <button type="button" className={styles.button} onClick={onReload} disabled={busy}>
          Reload
        </button>
      </div>
      <p className={styles.muted} style={{ marginBottom: 8 }}>
        Sample: <code>twin labels draft seaport-dev-1 --area seaport</code>
      </p>
      <label className={styles.field}>
        <span>Site</span>
        <select value={site} onChange={(e) => onSelectSite(e.target.value)}>
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
        <button type="button" className={styles.button} onClick={onSave} disabled={busy || !meta || meta.frozen}>
          Save
        </button>
        <button type="button" className={styles.button} onClick={onApprove} disabled={busy || !meta || meta.frozen}>
          Approve
        </button>
        <button type="button" className={styles.button} onClick={onNewVersion} disabled={busy || !meta}>
          New version
        </button>
      </div>
      {error ? <p className={styles.notice} role="alert" style={{ marginTop: 8 }}>{error}</p> : null}
      {info ? <p className={styles.notice} role="status" style={{ marginTop: 8 }}>{info}</p> : null}
    </section>
  );
}
