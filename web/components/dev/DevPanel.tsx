"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { Crown } from "@/components/TopBar";
import RunDetail from "@/components/dev/RunDetail";
import RunList from "@/components/dev/RunList";
import styles from "@/components/dev/dev.module.css";
import {
  errorText,
  fetchRegistry,
  fetchRuns,
  fetchWhoami,
  type Registry,
  type RunSummary,
  signInUrl,
} from "@/lib/devapi";

type RunsState = { kind: "loading" } | { kind: "ready"; runs: RunSummary[] } | { kind: "error"; message: string };
// Signed in = the API accepted the operator's Access token (credentialed GET /api/w/whoami).
type Auth = { kind: "checking" } | { kind: "in"; email: string } | { kind: "out" };

const noSubscribe = () => () => {};
const getHere = () => window.location.href;
const getServerHere = () => "";

export default function DevPanel() {
  const here = useSyncExternalStore(noSubscribe, getHere, getServerHere);
  const [auth, setAuth] = useState<Auth>({ kind: "checking" });
  const [runs, setRuns] = useState<RunsState>({ kind: "loading" });
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  // Bumped after every write (start, re-run, cancel): the run list and the open run reload.
  const [tick, setTick] = useState(0);
  const changed = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let alive = true;
    fetchWhoami().then(
      (w) => alive && setAuth({ kind: "in", email: w.email }),
      () => alive && setAuth({ kind: "out" }),
    );
    return () => {
      alive = false;
    };
  }, []);

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
  }, [tick]);

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
  const signedIn = auth.kind === "in";

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
        {auth.kind === "in" ? (
          <p>Signed in as {auth.email}. Controls are enabled.</p>
        ) : auth.kind === "checking" ? (
          <p>Checking sign-in…</p>
        ) : (
          <>
            <p>Signed out. Controls are disabled.</p>
            {/* Cloudflare Access sign-in on the API host, as a top-level navigation (see lib/devapi.ts). */}
            <a className={styles.signIn} href={signInUrl(here)}>
              Sign in
            </a>
          </>
        )}
      </div>
      {runs.kind === "error" ? (
        <p className={styles.notice} role="status">
          {runs.message}
        </p>
      ) : (
        <div className={styles.grid}>
          <RunList
            runs={runs.kind === "ready" ? runs.runs : null}
            selected={selected}
            signedIn={signedIn}
            onSelect={setPicked}
            onChanged={changed}
          />
          <RunDetail
            key={selected ?? ""}
            runId={selected}
            registry={registry}
            signedIn={signedIn}
            tick={tick}
            onSelect={setPicked}
            onChanged={changed}
          />
        </div>
      )}
    </div>
  );
}
