"use client";

import { useState } from "react";
import type { ScoutJob } from "@/app/api/scout/route";
import { hasSalary } from "@/components/MatchFilters";

/**
 * One rendering of a ranked job list, shared by the interactive scan (/scout)
 * and the scheduled feed (/matches) so a match looks the same however it was
 * produced. Test IDs are kept as they were when this lived inside
 * app/scout/page.tsx -- the existing scout specs assert on them.
 */
export function MatchTable({ jobs }: { jobs: ScoutJob[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            {["Title", "Company", "Location", "Posted", "Salary", "Match", "Why matched"].map(
              (h) => (
                <th
                  key={h}
                  className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500"
                >
                  {h}
                </th>
              ),
            )}
            <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500" />
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {jobs.map((job, i) => (
            <MatchRow key={`${job.apply_url ?? job.title}-${i}`} job={job} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Colour the match by how much of the candidate's stack the ad actually asks
 *  for, so a weak match reads as weak at a glance instead of as a blue badge
 *  indistinguishable from a strong one. */
function matchTone(pct: number): string {
  if (pct >= 50) return "bg-green-50 text-green-700";
  if (pct >= 25) return "bg-amber-50 text-amber-700";
  return "bg-gray-100 text-gray-500";
}

function formatPosted(posted: string | null): string {
  if (!posted) return "—";
  const t = Date.parse(posted);
  if (Number.isNaN(t)) return posted;
  return new Date(t).toLocaleDateString();
}

function formatSalary(salary: number | string | null): string {
  if (!hasSalary(salary)) return "—";
  if (typeof salary === "number") return `€${Math.round(salary).toLocaleString()}/yr`;
  return String(salary);
}

function MatchRow({ job }: { job: ScoutJob }) {
  const pct = job.match_pct;
  const matched = job.matched_skills ?? [];
  const [showReview, setShowReview] = useState(false);
  const review = job.company_review ?? null;

  return (
    <>
      <tr data-testid="scout-job-row">
        <td className="px-4 py-2 text-sm text-gray-900">{job.title ?? "—"}</td>
        <td className="px-4 py-2 text-sm text-gray-700">
          {job.company ?? "—"}
          {review && (
            <button
              data-testid="company-review-toggle"
              onClick={() => setShowReview((v) => !v)}
              className="ml-2 rounded bg-purple-50 px-1.5 py-0.5 text-xs text-purple-700 hover:bg-purple-100"
            >
              {showReview ? "hide" : "reviews"}
            </button>
          )}
        </td>
        <td className="px-4 py-2 text-sm text-gray-700">{job.location ?? "—"}</td>
        <td data-testid="scout-posted" className="px-4 py-2 text-sm text-gray-700">
          {formatPosted(job.posted ?? null)}
        </td>
        <td data-testid="scout-salary" className="px-4 py-2 text-sm text-gray-700">
          {formatSalary(job.salary ?? null)}
        </td>
        <td className="px-4 py-2 text-sm">
          <span
            data-testid="scout-match-pct"
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${matchTone(pct ?? 0)}`}
          >
            {pct === null || pct === undefined ? "—" : `${pct}%`}
          </span>
        </td>
        <td className="px-4 py-2 text-sm text-gray-500">
          {matched.length ? (
            <span data-testid="scout-matched-skills" className="flex flex-wrap gap-1">
              {matched.slice(0, 6).map((s) => (
                <span
                  key={s}
                  className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600"
                >
                  {s}
                </span>
              ))}
            </span>
          ) : (
            <span className="text-xs italic text-gray-400">
              no skills from your CV appear in this ad
            </span>
          )}
          {job.reason && <div className="mt-1 text-xs">{job.reason}</div>}
        </td>
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
      {review && showReview && (
        <tr data-testid="company-review-panel">
          <td colSpan={8} className="bg-purple-50/40 px-4 py-3">
            <div className="grid gap-4 sm:grid-cols-2">
              <ProsCons label="Pros" items={review.pros} tone="text-green-700" />
              <ProsCons label="Cons" items={review.cons} tone="text-red-700" />
            </div>
            <p className="mt-2 text-xs text-gray-500">
              {review.summary}
              <br />
              <span data-testid="company-review-caveat" className="italic">
                Generated by a language model from its own training data, not read
                from Glassdoor or any review site. Treat as a starting point to
                verify, not as sourced fact.
              </span>
            </p>
          </td>
        </tr>
      )}
    </>
  );
}

function ProsCons({
  label,
  items,
  tone,
}: {
  label: string;
  items: string[];
  tone: string;
}) {
  return (
    <div>
      <h4 className={`text-xs font-semibold uppercase tracking-wide ${tone}`}>{label}</h4>
      {items?.length ? (
        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-sm text-gray-700">
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-sm italic text-gray-400">nothing reported</p>
      )}
    </div>
  );
}
