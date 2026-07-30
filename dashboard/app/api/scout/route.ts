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
  rank_score: number | null;
  fit: number | null;
  reason: string | null;
  bucket: string | null;
}

export interface ScoutResult {
  generated_at: string;
  cv: string;
  profile_source: string | null;
  total_matches: number;
  jobs: ScoutJob[];
}

export async function POST(request: NextRequest) {
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
    return NextResponse.json(result);
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
