#!/usr/bin/env node
import { copyFileSync, mkdirSync } from "node:fs";
const src = new URL("../../docs/evals/recon-v2-results.json", import.meta.url);
const destDir = new URL("../public/evals/", import.meta.url);
mkdirSync(destDir, { recursive: true });
copyFileSync(src, new URL("recon-v2-results.json", destDir));
console.log("synced docs/evals/recon-v2-results.json -> web/public/evals/");
