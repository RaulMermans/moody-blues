// Builds the evidence directories the E2E backend serves, then exits. Run before uvicorn starts.
// The recorded bundles are the real committed ones. One extra entry is a copy of a real bundle
// whose content no longer matches its manifest hash: that is how a tampered record looks.
// The ledger is a labeled fixture past its limit, so a chargeable mission is refused for real.
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", ".e2e");
const recorded = join(root, "recorded");
const artifacts = join(root, "artifacts");
export const TAMPERED_ID = "inv_0bad0bad0bad";

rmSync(root, { recursive: true, force: true });
mkdirSync(join(artifacts, "live-spend"), { recursive: true });
cpSync(join(here, "..", "..", "evidence", "recorded"), recorded, { recursive: true });

const manifestPath = join(recorded, "manifest.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf-8"));
const source = manifest.cases[0];
const file = `${TAMPERED_ID}.json`;
const body = JSON.parse(readFileSync(join(recorded, source.file), "utf-8"));
body.summary.investigation_id = TAMPERED_ID;
body.summary.outcome = "no_violation_found";
writeFileSync(join(recorded, file), JSON.stringify(body));
manifest.cases.push({ ...source, investigation_id: TAMPERED_ID, file });
writeFileSync(manifestPath, JSON.stringify(manifest));

// A real report, as committed. The page must read its label from the record.
mkdirSync(join(root, "containment"), { recursive: true });
cpSync(
  join(here, "..", "..", "evidence", "containment", "report.json"),
  join(root, "containment", "report.json"),
);

const at = "2026-11-05T00:00:00Z";
const entry = "spend_e2efixture00";
const line = (kind, extra) =>
  JSON.stringify({ kind, entry_id: entry, at, label: "e2e-fixture", amount_usd: 5.5, ...extra });
writeFileSync(
  join(artifacts, "live-spend", "ledger.jsonl"),
  `${line("reserve", {})}\n${line("settle", { prompt_tokens: 0, completion_tokens: 0, usage_complete: true })}\n`,
);
