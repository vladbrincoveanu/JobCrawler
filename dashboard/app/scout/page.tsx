"use client";

import { useState } from "react";
import type { ScoutJob, ScoutResult } from "@/app/api/scout/route";

type Status = "idle" | "scanning" | "done" | "error";

export default function ScoutPage() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [result, setResult] = useState<ScoutResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleScan() {
    if (!file) return;
    setStatus("scanning");
    setError(null);
    setResult(null);

    const body = new FormData();
    body.append("cv", file);

    try {
      const res = await fetch("/api/scout", { method: "POST", body });
      const data = await res.json();
      if (!res.ok) {
        setError(data?.detail || data?.error || `Scan failed (${res.status}).`);
        setStatus("error");
        return;
      }
      setResult(data as ScoutResult);
      setStatus("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed to run.");
      setStatus("error");
    }
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold text-gray-900">CV Scout</h1>
        <p className="mt-1 text-sm text-gray-600">
          Upload a CV (PDF) and scan live job sources for the best matches right now.
        </p>
      </header>

      <section
        data-testid="scout-upload"
        className="rounded-lg border border-gray-200 bg-white p-6 space-y-4"
      >
        <div className="flex flex-wrap items-center gap-3">
          <input
            data-testid="scout-cv-input"
            type="file"
            accept="application/pdf,.pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm text-gray-700 file:mr-3 file:rounded-md file:border-0 file:bg-gray-100 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-gray-700 hover:file:bg-gray-200"
          />
          <button
            data-testid="scout-scan-button"
            onClick={handleScan}
            disabled={!file || status === "scanning"}
            className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {status === "scanning" ? "Scanning…" : "Scan"}
          </button>
          {file && <span className="text-sm text-gray-500">{file.name}</span>}
        </div>
        <p className="text-xs text-gray-400">
          Sources: karriere.at plus the free no-auth APIs (Arbeitnow, Remotive, Jobicy,
          Himalayas), and Adzuna/Jooble when their keys are configured. Scoring falls
          back to keyword matching automatically if no LLM key is configured.
        </p>
      </section>

      {status === "scanning" && (
        <div
          data-testid="scout-loading"
          className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500"
        >
          Scanning live job sources against your CV — this can take a little while…
        </div>
      )}

      {status === "error" && (
        <div
          data-testid="scout-error"
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {status === "done" && result && <ScoutResults result={result} />}
    </div>
  );
}

function ScoutResults({ result }: { result: ScoutResult }) {
  if (result.jobs.length === 0) {
    return (
      <div
        data-testid="scout-results-empty"
        className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500"
      >
        No matches found in this scan (0 of {result.total_matches} total scored jobs met the
        threshold). This can also mean the live job sources were unreachable — try again later.
      </div>
    );
  }

  return (
    <section className="space-y-3" data-testid="scout-results">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold text-gray-900">
          {result.jobs.length} matches
        </h2>
        <span className="text-xs text-gray-400">
          profile: {result.profile_source ?? "unknown"} · generated{" "}
          {new Date(result.generated_at).toLocaleString()}
        </span>
      </div>
      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                Title
              </th>
              <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                Company
              </th>
              <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                Location
              </th>
              <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                Score
              </th>
              <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                Why matched
              </th>
              <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {result.jobs.map((job, i) => (
              <ScoutRow key={`${job.apply_url ?? job.title}-${i}`} job={job} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ScoutRow({ job }: { job: ScoutJob }) {
  return (
    <tr data-testid="scout-job-row">
      <td className="px-4 py-2 text-sm text-gray-900">{job.title ?? "—"}</td>
      <td className="px-4 py-2 text-sm text-gray-700">{job.company ?? "—"}</td>
      <td className="px-4 py-2 text-sm text-gray-700">{job.location ?? "—"}</td>
      <td className="px-4 py-2 text-sm">
        <span className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
          {job.rank_score ?? job.fit ?? "—"}
        </span>
      </td>
      <td className="px-4 py-2 text-sm text-gray-500">{job.reason ?? "—"}</td>
      <td className="px-4 py-2 text-sm">
        {job.apply_url ? (
          <a
            href={job.apply_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline"
          >
            Apply ↗
          </a>
        ) : (
          "—"
        )}
      </td>
    </tr>
  );
}
