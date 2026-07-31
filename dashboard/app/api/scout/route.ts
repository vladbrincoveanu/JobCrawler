import { NextRequest, NextResponse } from "next/server";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

/**
 * CV upload + scan.
 *
 * This shells out to scripts/scout.py (the existing, working CV-matching CLI)
 * rather than reimplementing its ~900 lines of scoring/dedupe/source logic in
 * TypeScript. scout.py already extracts a skill profile from the uploaded PDF
 * (LLM-assisted if NVIDIA_API_KEY is set, keyword-lexicon fallback otherwise),
 * queries live free job sources, scores + dedupes, and (via --json-out) emits
 * one structured JSON payload instead of sending Telegram or writing HTML.
 */

export const dynamic = "force-dynamic";
export const maxDuration = 300;

const REPO_ROOT = process.env.SCOUT_REPO_ROOT ?? path.resolve(process.cwd(), "..");
const SCOUT_SCRIPT = path.join(REPO_ROOT, "scripts", "scout.py");
const MAX_UPLOAD_BYTES = 15 * 1024 * 1024;
// adzuna/jooble are accepted but no-op unless their API keys are in the server
// env; scout.py logs the skip and the scan continues on the other sources.
const ALLOWED_SOURCES = new Set([
  "jobhive", "apis", "karriere", "stepstone", "adzuna", "jooble",
  // "none" queries no board at all: the CV is still parsed and profiled, so it
  // answers "is this PDF readable and does the pipeline run" in a second or two
  // instead of after a full multi-minute scan.
  "none",
]);

/**
 * StepStone is deliberately NOT in the default set. Its Akamai WAF answers 403
 * to a concurrent scan and will IP-block on a burst, so leaving it in the
 * interactive default made the whole feature fail intermittently through no
 * fault of the user's CV. It stays available by passing `sources` explicitly.
 * jobhive is out of the default too: it needs duckdb plus a large remote
 * parquet download, which is minutes, not seconds.
 */
const DEFAULT_SOURCES =
  process.env.SCOUT_DEFAULT_SOURCES ?? "apis,karriere,adzuna,jooble";

/**
 * scout.py needs pypdf/requests/duckdb, which a bare system `python3` almost
 * never has -- the README's own setup puts them in the repo venv. Preferring
 * that venv means an ordinary checkout works without anyone having to discover
 * SCOUT_PYTHON_BIN from a stack trace saying "No module named 'pypdf'".
 */
function resolvePython(): string {
  if (process.env.SCOUT_PYTHON_BIN) return process.env.SCOUT_PYTHON_BIN;
  const venv = path.join(REPO_ROOT, ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python3";
}

export interface ScoutJob {
  title: string | null;
  company: string | null;
  location: string | null;
  posted: string | null;
  salary: number | string | null;
  source: string | null;
  apply_url: string | null;
  score: number | null;
  rank: number | null;
  /** Percentile within this result set — the BEST job always scores ~100 even
   *  when nothing in the set fits. Not a fit measure; don't show it as one. */
  rank_score: number | null;
  /** Share of the candidate's own skill weight the ad actually asks for. This
   *  is the number to display. */
  match_pct: number | null;
  /** Which profile skills the ad mentioned, strongest first. */
  matched_skills: string[];
  /** The profile's skills, strongest first — lets the UI say what was missed. */
  profile_skills: string[];
  fit: number | null;
  reason: string | null;
  bucket: string | null;
  /** Company pros/cons, attached only when the scan ran with review
   *  enrichment on (`scout.py --company-reviews`). Model-generated, not
   *  scraped from a review site — see CompanyReview.source. */
  company_review?: CompanyReview | null;
}

export interface CompanyReview {
  company: string;
  pros: string[];
  cons: string[];
  summary: string;
  source: string;
  generated_at: string;
}

export interface ScoutFilters {
  days: number;
  top: number;
  sources: string;
  require_salary: boolean;
}

export interface ScoutResult {
  generated_at: string;
  cv: string;
  profile_source: string | null;
  total_matches: number;
  jobs: ScoutJob[];
  /** Present on API responses; absent in the raw scout.py file it wraps. */
  filters?: ScoutFilters;
}

export async function POST(request: NextRequest) {
  // This route spawns python and waits minutes for it. On the Vercel deployment
  // there is no python and the function is killed long before a scan finishes,
  // so it fails -- but it fails as a timeout after several minutes, which reads
  // as "my CV broke it". Refusing up front, with the reason, is the honest
  // version. Scheduled scans are the deployed path; see /cvs.
  if (process.env.SCOUT_LOCAL_SCAN !== "1" && !existsSync(SCOUT_SCRIPT)) {
    return NextResponse.json(
      {
        error:
          "Upload-and-scan runs scripts/scout.py, which only exists on a local " +
          "checkout. On this deployment, scans run on GitHub Actions: configure " +
          "a CV under /cvs and use Scan now.",
      },
      { status: 501 },
    );
  }

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return NextResponse.json(
      { error: "Expected multipart/form-data with a 'cv' file." },
      { status: 400 },
    );
  }

  const file = form.get("cv");
  if (!file || typeof file === "string") {
    return NextResponse.json(
      { error: "Missing 'cv' file upload (PDF)." },
      { status: 400 },
    );
  }
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    return NextResponse.json({ error: "Only PDF CVs are supported." }, { status: 400 });
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return NextResponse.json({ error: "CV file too large (max 15MB)." }, { status: 400 });
  }

  const workDir = await mkdtemp(path.join(tmpdir(), "scout-"));
  const cvPath = path.join(workDir, "cv.pdf");
  const jsonPath = path.join(workDir, "result.json");

  try {
    const bytes = Buffer.from(await file.arrayBuffer());
    await writeFile(cvPath, bytes);

    const days = clampInt(form.get("days"), 30, 1, 90);
    const top = clampInt(form.get("top"), 25, 1, 100);
    // Query string is accepted as well as the form field so a caller can pick
    // sources without rebuilding the multipart body.
    const sources = normalizeSources(
      form.get("sources") ?? request.nextUrl.searchParams.get("sources"),
    );

    const args = [
      SCOUT_SCRIPT,
      "--dry-run",
      "--cv",
      cvPath,
      "--sources",
      sources,
      "--days",
      String(days),
      "--top",
      String(top),
      "--json-out",
      jsonPath,
    ];
    // Drops every ad that states no pay at all. Off by default because most
    // Austrian listings omit salary entirely -- turning this on typically cuts
    // the result set by more than half, which is a choice, not a default.
    if (isTruthy(form.get("require_salary"))) {
      args.push("--require-salary");
    }
    // Keyword-lexicon scoring works with no key at all; only ask for an LLM
    // rerank when a key is actually configured, so the demo works out of the box.
    if (!process.env.NVIDIA_API_KEY) {
      args.push("--no-llm");
    }

    const { code, stderr } = await runScout(args);
    if (code !== 0) {
      return NextResponse.json(
        { error: "Scan failed.", detail: stderr.slice(-4000) },
        { status: 502 },
      );
    }

    const raw = await readFile(jsonPath, "utf-8");
    const result = JSON.parse(raw) as ScoutResult;
    // Echo the filters back so the UI can state what the result set was
    // narrowed by -- "12 matches" means something different with
    // require_salary on, and the page shouldn't have to guess from its own
    // form state what the server actually ran.
    return NextResponse.json({
      ...result,
      filters: {
        days,
        top,
        sources,
        require_salary: isTruthy(form.get("require_salary")),
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      { error: "Scan failed to run.", detail: message },
      { status: 500 },
    );
  } finally {
    await rm(workDir, { recursive: true, force: true });
  }
}

function runScout(args: string[]): Promise<{ code: number; stderr: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(resolvePython(), args, { cwd: REPO_ROOT, env: process.env });
    let stderr = "";
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
    });
    child.on("error", reject);
    child.on("close", (code) => resolve({ code: code ?? 1, stderr }));
  });
}

/** HTML checkboxes post "on"; JSON/fetch callers send "true" or "1". */
function isTruthy(value: FormDataEntryValue | null): boolean {
  return typeof value === "string" && ["on", "true", "1", "yes"].includes(value.toLowerCase());
}

function clampInt(
  value: FormDataEntryValue | null,
  fallback: number,
  min: number,
  max: number,
): number {
  const n = typeof value === "string" ? parseInt(value, 10) : NaN;
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

function normalizeSources(value: FormDataEntryValue | null): string {
  if (typeof value !== "string" || !value.trim()) return DEFAULT_SOURCES;
  const picked = value
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter((s) => ALLOWED_SOURCES.has(s));
  return picked.length ? picked.join(",") : DEFAULT_SOURCES;
}
