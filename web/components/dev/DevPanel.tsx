"use client";

import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Crown } from "@/components/TopBar";
import RunDetail, { errorText } from "@/components/dev/RunDetail";
import RunList from "@/components/dev/RunList";
import styles from "@/components/dev/dev.module.css";
import { fetchRegistry, fetchRuns, type Registry, type RunSummary, signInUrl } from "@/lib/devapi";

// Signed-in detection is ticket 13b. Until then every viewer is treated as signed out.
type RunsState = { kind: "loading" } | { kind: "ready"; runs: RunSummary[] } | { kind: "error"; message: string };

const noSubscribe = () => () => {};
const getHere = () => window.location.href;
const getServerHere = () => "";

export default function DevPanel() {
  const here = useSyncExternalStore(noSubscribe, getHere, getServerHere);
  const [runs, setRuns] = useState<RunsState>({ kind: "loading" });
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [picked, setPicked] = useState<string | null>(null);

  // Lists runs; polls every 5 s while any run is running.
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function load() {
      try {
        const list = await fetchRuns();
        if (!alive) return;
        setRuns({ kind: "ready", runs: list });
        if (list.some((r) => r.status === "running")) timer = setTimeout(load, 5000);
      } catch (e) {
        if (!alive) return;
        setRuns({ kind: "error", message: errorText(e) });
      }
    }
    load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    fetchRegistry().then(
      (r) => alive && setRegistry(r),
      () => undefined, // the run list already shows the unreachable message
    );
    return () => {
      alive = false;
    };
  }, []);

  // Default to the newest run until one is picked.
  const selected = picked ?? (runs.kind === "ready" ? (runs.runs[0]?.run_id ?? null) : null);

  return (
    <div className={styles.root}>
      <header className={styles.top}>
        <Link className={styles.back} href="/">
          ← Map
        </Link>
        <div className={styles.brand}>
          <Crown />
          Developer panel
        </div>
      </header>
      <div className={styles.banner} role="status">
        <p>Signed out. Controls are visible but disabled.</p>
        {/* Cloudflare Access sign-in on the API host, as a top-level navigation (see lib/devapi.ts). */}
        <a className={styles.signIn} href={signInUrl(here)}>
          Sign in
        </a>
      </div>
      {runs.kind === "error" ? (
        <p className={styles.notice} role="status">
          {runs.message}
        </p>
      ) : (
        <div className={styles.grid}>
          <RunList runs={runs.kind === "ready" ? runs.runs : null} selected={selected} onSelect={setPicked} />
          <RunDetail runId={selected} registry={registry} onSelect={setPicked} />
        </div>
      )}
    </div>
  );
}
